"""Celery app and background tasks. With CELERY_EAGER=true tasks run inline (no Redis needed)."""

import asyncio

from celery import Celery
from sqlalchemy import select

from app.db import get_sessionmaker
from app.llm import get_llm
from app.models import ApplicationKit, Contact, Document, Job, RenderedResume
from app.models import Profile as ProfileRow
from app.profile.parsing import extract_text, parse_resume
from app.profile.schema import Profile
from app.rendering.compile import LatexCompileError
from app.rendering.service import render_pdf
from app.settings import get_settings
from app.storage import get_storage, user_key

settings = get_settings()
celery_app = Celery("job_auto_apply", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_always_eager=settings.celery_eager,
    task_eager_propagates=False,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="documents.parse")
def parse_document(document_id: str) -> str:
    with get_sessionmaker()() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            return "missing"
        doc.status = "parsing"
        db.commit()
        try:
            raw = get_storage().get(doc.storage_key)
            text = extract_text(doc.kind, raw)
            doc.extracted_text = text
            profile = asyncio.run(parse_resume(get_llm(), doc.kind, text, raw))
            doc.parsed_profile = profile.model_dump()
            doc.status = "parsed"
            doc.error = None
        except Exception as exc:  # surfaced to the user via GET /documents/{id}
            doc.status = "failed"
            doc.error = f"{type(exc).__name__}: {exc}"[:2000]
        db.commit()
        return doc.status


@celery_app.task(name="resumes.render")
def render_resume(resume_id: str, profile_data: dict, max_pages: int = 1) -> str:
    with get_sessionmaker()() as db:
        row = db.get(RenderedResume, resume_id)
        if row is None:
            return "missing"
        try:
            result = render_pdf(Profile.model_validate(profile_data), row.template, max_pages=max_pages)
            key = user_key(row.user_id, "resumes", f"{row.id}.pdf")
            get_storage().put(key, result.pdf, "application/pdf")
            row.storage_key, row.pages, row.trimmed_items = key, result.pages, result.trimmed
            row.status, row.error = "done", None
        except LatexCompileError as exc:
            row.status, row.error = "failed", str(exc)[:4000]
        except Exception as exc:
            row.status, row.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        db.commit()
        return row.status


# --- jobs, contacts and application kits ---------------------------------------------------------


@celery_app.task(name="jobs.ingest")
def ingest_job(job_id: str) -> str:
    """Fetch the posting (unless text was pasted), parse it, and work out the company's email domain."""
    from app.jobs.fetch import clean_text, fetch_job, guess_company_domain
    from app.jobs.parsing import parse_job

    with get_sessionmaker()() as db:
        job = db.get(Job, job_id)
        if job is None:
            return "missing"
        job.status = "parsing"
        db.commit()
        try:
            site_hint, title_hint, company_hint = "", "", ""
            if not job.raw_text and job.url:
                fetched = asyncio.run(fetch_job(job.url))
                job.source, job.raw_text = fetched.source, fetched.text
                site_hint, title_hint, company_hint = fetched.company_website, fetched.title, fetched.company
            job.raw_text = clean_text(job.raw_text or "")
            posting = asyncio.run(parse_job(get_llm(), job.raw_text, settings.job_text_max_chars))
            posting.title = posting.title or title_hint
            posting.company = posting.company or company_hint
            job.parsed = posting.model_dump()
            job.title = posting.title[:255] or None
            job.company = posting.company[:255] or None
            if not job.company_domain:
                job.company_domain = (
                    guess_company_domain(site_hint, posting.company_website, job.url or "") or None
                )
            job.status, job.error = "parsed", None
        except Exception as exc:
            job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        db.commit()
        return job.status


@celery_app.task(name="contacts.search")
def search_contacts(job_id: str) -> str:
    from app.contacts.finder import ContactFinder, build_providers, contact_key
    from app.jobs.schema import JobPosting

    with get_sessionmaker()() as db:
        job = db.get(Job, job_id)
        if job is None:
            return "missing"
        try:
            providers, verifier = build_providers()
            finder = ContactFinder(providers, verifier)
            posting = JobPosting.model_validate(job.parsed or {})
            result = asyncio.run(
                finder.find(posting, job.raw_text or "", job.company_domain or "", job.email_pattern or "")
            )
            # Replace earlier automatic results; keep contacts the user added by hand.
            for old in db.scalars(
                select(Contact).where(Contact.job_id == job.id, Contact.source != "manual")
            ):
                db.delete(old)
            manual = {
                (c.email or "").lower() for c in db.scalars(select(Contact).where(Contact.job_id == job.id))
            }
            for c in result.contacts:
                if c.email and c.email.lower() in manual:
                    continue
                key = contact_key(c)
                db.add(
                    Contact(
                        user_id=job.user_id,
                        job_id=job.id,
                        full_name=c.name()[:255],
                        first_name=c.first_name[:127],
                        last_name=c.last_name[:127],
                        position=c.position[:255],
                        email=c.email or None,
                        email_status=c.email_status,
                        confidence=c.confidence,
                        category=result.categories[key],
                        score=result.scores[key],
                        source=c.source,
                        linkedin_url=c.linkedin_url or None,
                    )
                )
            job.email_pattern = job.email_pattern or result.email_pattern or None
            job.contacts_warnings = result.warnings
            job.contacts_status = "done"
        except Exception as exc:
            job.contacts_status = "failed"
            job.contacts_warnings = [f"{type(exc).__name__}: {exc}"[:2000]]
        db.commit()
        return job.contacts_status


@celery_app.task(name="kits.generate")
def generate_kit(kit_id: str) -> str:
    """Tailor the resume (with the honesty check), write outreach and a cover letter, render PDFs."""
    from datetime import date

    from app.jobs.schema import JobPosting
    from app.outreach.tailoring import tailor
    from app.outreach.writing import write_outreach
    from app.rendering.compile import compile_latex
    from app.rendering.latex import render_cover_letter

    with get_sessionmaker()() as db:
        kit = db.get(ApplicationKit, kit_id)
        if kit is None:
            return "missing"
        kit.status = "generating"
        db.commit()
        try:
            job = db.get(Job, kit.job_id)
            profile_row = db.scalar(select(ProfileRow).where(ProfileRow.user_id == kit.user_id))
            profile = Profile.model_validate(profile_row.data if profile_row else {})
            posting = JobPosting.model_validate(job.parsed or {})

            async def run():
                tailored, report = await tailor(get_llm(), profile, posting)
                outreach = await write_outreach(get_llm(), tailored, posting, job.url or "")
                return tailored, report, outreach

            tailored, report, outreach = asyncio.run(run())
            kit.tailored_profile = tailored.model_dump()
            kit.honesty_report = report
            kit.outreach = outreach.model_dump()
            kit.cover_letter = outreach.cover_letter.as_text(tailored.contact.name)

            warnings: list[str] = []
            try:
                latex = render_cover_letter(
                    tailored,
                    outreach.cover_letter,
                    company=posting.company,
                    title=posting.title,
                    date=date.today().strftime("%d %B %Y"),
                )
                key = user_key(kit.user_id, "cover_letters", f"{kit.id}.pdf")
                get_storage().put(key, compile_latex(latex), "application/pdf")
                kit.cover_letter_key = key
            except Exception as exc:
                warnings.append(f"Cover letter PDF failed: {type(exc).__name__}: {exc}"[:1000])

            resume = RenderedResume(user_id=kit.user_id, job_id=job.id, template=kit.template)
            db.add(resume)
            db.flush()
            kit.resume_id = resume.id
            kit.warnings = warnings
            kit.status, kit.error = "done", None
            db.commit()
            render_resume.delay(resume.id, kit.tailored_profile, 1)
        except Exception as exc:
            db.rollback()
            kit = db.get(ApplicationKit, kit_id)
            kit.status, kit.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
            db.commit()
        return kit.status


@celery_app.task(name="github.import")
def run_github_import(import_id: str) -> str:
    from app.github.importer import import_github
    from app.models import GitHubImport

    with get_sessionmaker()() as db:
        row = db.get(GitHubImport, import_id)
        if row is None:
            return "missing"
        row.status = "running"
        db.commit()
        try:
            result = asyncio.run(
                import_github(
                    get_llm(), row.username, row.featured or [], row.max_repos, get_settings().github_token
                )
            )
            row.result, row.status, row.error = result.model_dump(), "done", None
        except Exception as exc:
            row.status, row.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        db.commit()
        return row.status
