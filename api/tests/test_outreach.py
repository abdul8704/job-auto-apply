import json
from io import BytesIO

import pytest
from pypdf import PdfWriter

import app.contacts.finder as finder_mod
import app.rendering.compile as compile_mod
import app.rendering.service as service
from app.outreach.schema import CoverLetter, TailoredBullet, TailoredItem, TailoringPlan
from app.outreach.tailoring import apply_plan
from app.profile.schema import SkillGroup
from app.rendering.latex import render_cover_letter
from tests.conftest import signup_and_login
from tests.sample import sample_profile

JD = """Backend Engineer at Acme (JR-77)
Contact Priya Sharma, Recruiter, at priya.sharma@acme.com.
Build Python APIs with Redis caching. Must have: Python, Redis, Docker."""

POSTING = {
    "title": "Backend Engineer",
    "company": "Acme",
    "company_website": "https://www.acme.com",
    "job_id": "JR-77",
    "department": "Engineering",
    "required_skills": ["Python", "Redis", "Docker"],
    "referrer_titles": ["Software Engineer", "Engineering Manager"],
    "contacts": [
        {"name": "Priya Sharma", "role": "Recruiter", "email": "priya.sharma@acme.com"},
        {"name": "Ghost Person", "role": "Hiring Manager", "email": "ghost@acme.com"},
    ],
}


def pdf_bytes(_latex: str) -> bytes:
    w = PdfWriter()
    w.add_blank_page(612, 792)
    buf = BytesIO()
    w.write(buf)
    return buf.getvalue()


def plan_for(profile) -> dict:
    exp, proj = profile.experience[0], profile.projects[0]
    return TailoringPlan(
        summary="Backend developer who cut API latency by 40% with Redis.",
        experience=[
            TailoredItem(
                id=exp.id,
                bullets=[
                    TailoredBullet(
                        source_id=exp.bullets[0].id, text="Cut Python API latency 40% with Redis caching"
                    ),
                    TailoredBullet(source_id=exp.bullets[1].id, text="Led a team of 10 building C# tools"),
                    TailoredBullet(source_id="made-up", text="Invented Docker"),
                ],
            )
        ],
        projects=[TailoredItem(id=proj.id, bullets=[TailoredBullet(source_id=proj.bullets[0].id, text="")])],
        skills=[SkillGroup(category="Languages", items=["python", "Docker", "TypeScript"])],
        missing_keywords=["Docker"],
    ).model_dump()


@pytest.fixture
def scripted(fake_llm, monkeypatch):
    """Answer each prompt by what it is for, like a real model would."""
    monkeypatch.setattr(service, "compile_latex", pdf_bytes)
    monkeypatch.setattr(compile_mod, "compile_latex", pdf_bytes)

    async def mx(_d):
        return True

    monkeypatch.setattr(finder_mod, "domain_accepts_mail", mx)
    state = {}

    def respond(request):
        system = request.messages[0].content
        if "You read a job posting" in system:
            return json.dumps(POSTING)
        if "You tailor" in system:
            return json.dumps(plan_for(state["profile"]))
        if "honesty checker" in system:
            lines = json.loads(request.messages[1].content.split("Rewritten lines:\n", 1)[1])
            return json.dumps(
                {
                    "items": [
                        {"id": x["id"], "supported": "Led a team" not in x["text"], "reason": "adds a team"}
                        for x in lines
                    ]
                }
            )
        if "You write job outreach" in system:
            return json.dumps(
                {
                    "referral_request": {
                        "subject": "Referral for Backend Engineer (JR-77)",
                        "body": "Hi {first_name},\nCould you refer me?",
                    },
                    "recruiter_note": {
                        "subject": "Backend Engineer (JR-77)",
                        "body": "Hi {first_name},\nPlease consider me.",
                    },
                    "linkedin_note": "Hi, I'm applying for Backend Engineer at Acme.",
                    "cover_letter": {
                        "greeting": "Dear Hiring Team,",
                        "paragraphs": ["I cut latency 40% & more."],
                        "closing": "Sincerely,",
                    },
                }
            )
        raise AssertionError(system[:80])

    fake_llm.responder = respond
    return state


def test_apply_plan_keeps_only_real_facts():
    profile = sample_profile()
    tailored, changes, report = apply_plan(profile, TailoringPlan.model_validate(plan_for(profile)))
    bullets = tailored.experience[0].bullets
    assert [b.id for b in bullets] == [b.id for b in profile.experience[0].bullets]  # fake id dropped
    assert (
        tailored.projects[0].bullets[0].text == profile.projects[0].bullets[0].text
    )  # empty text -> original
    assert tailored.skills[0].items == ["Python", "TypeScript"]  # profile spelling, no invented Docker
    assert report["rejected_skills"] == ["Docker"] and report["missing_keywords"] == ["Docker"]
    assert {c["id"] for c in changes} == {bullets[0].id, bullets[1].id, "summary"}
    assert tailored.education == profile.education and tailored.contact == profile.contact


def test_cover_letter_latex_is_escaped():
    letter = CoverLetter(paragraphs=["100% sure & ready \\input{/etc/passwd}"])
    tex = render_cover_letter(sample_profile(), letter, company="A_B #1", title="SDE", date="1 Dec 2026")
    assert r"100\% sure \& ready \textbackslash{}input\{/etc/passwd\}" in tex
    assert r"A\_B \#1" in tex and "\\input{" not in tex.replace("\\textbackslash{}input", "")


def test_job_to_contacts_to_kit_end_to_end(client, auth, scripted):
    profile = sample_profile()
    client.put("/profile", json=profile.model_dump(), headers=auth)
    scripted["profile"] = profile

    r = client.post("/jobs", json={"text": JD}, headers=auth)
    assert r.status_code == 202, r.text
    job = client.get(f"/jobs/{r.json()['id']}", headers=auth).json()
    assert job["status"] == "parsed", job["error"]
    assert job["company_domain"] == "acme.com" and job["title"] == "Backend Engineer"
    emails = [c["email"] for c in job["parsed"]["contacts"]]
    assert emails == ["priya.sharma@acme.com", ""]  # invented email removed

    assert client.get("/contacts/providers").json() == {
        "posting": True,
        "pattern_guess": True,
        "hunter": False,
        "apollo": False,
    }
    r = client.post(f"/jobs/{job['id']}/contacts/search", headers=auth)
    assert r.status_code == 202
    assert client.get(f"/jobs/{job['id']}", headers=auth).json()["contacts_status"] == "done"
    contacts = client.get(f"/jobs/{job['id']}/contacts", headers=auth).json()
    assert contacts[0]["email"] == "priya.sharma@acme.com" and contacts[0]["category"] == "recruiter"
    ghost = next(c for c in contacts if c["full_name"] == "Ghost Person")
    assert ghost["email"] == "ghost.person@acme.com" and ghost["email_status"] == "guessed"

    client.patch(f"/jobs/{job['id']}", json={"email_pattern": "{f}{last}"}, headers=auth)
    r = client.post(
        f"/jobs/{job['id']}/contacts",
        json={"name": "Ravi Kumar", "position": "Software Engineer"},
        headers=auth,
    )
    assert r.status_code == 201 and r.json()["email"] == "rkumar@acme.com" and r.json()["category"] == "peer"
    ravi = r.json()

    r = client.post(f"/jobs/{job['id']}/kits", json={}, headers=auth)
    assert r.status_code == 202, r.text
    kit = client.get(f"/kits/{r.json()['id']}", headers=auth).json()
    assert kit["status"] == "done", kit["error"]
    report = kit["honesty_report"]
    assert [x["text"] for x in report["reverted"]] == ["Led a team of 10 building C# tools"]
    bullets = [b["text"] for b in kit["tailored_profile"]["experience"][0]["bullets"]]
    assert bullets == ["Cut Python API latency 40% with Redis caching", "Wrote C# tools"]
    assert kit["cover_letter"].endswith("Sincerely,\nAziz Test") and kit["has_cover_letter_pdf"]
    assert client.get(f"/kits/{kit['id']}/cover-letter.pdf", headers=auth).content.startswith(b"%PDF")

    resume = client.get(f"/resumes/{kit['resume_id']}", headers=auth).json()
    assert resume["status"] == "done" and resume["job_id"] == job["id"]

    msg = client.get(f"/kits/{kit['id']}/messages/{ravi['id']}", headers=auth).json()
    assert (
        msg["kind"] == "referral_request"
        and msg["body"].startswith("Hi Ravi,")
        and msg["to_email"] == "rkumar@acme.com"
    )
    msg = client.get(f"/kits/{kit['id']}/messages/{contacts[0]['id']}", headers=auth).json()
    assert msg["kind"] == "recruiter_note" and msg["body"].startswith("Hi Priya,")

    # Another user can see none of it.
    other = signup_and_login(client, "friend@example.com")
    assert client.get(f"/jobs/{job['id']}", headers=other).status_code == 404
    assert client.get(f"/kits/{kit['id']}", headers=other).status_code == 404
    assert client.get(f"/jobs/{job['id']}/contacts", headers=other).status_code == 404
    assert client.post(f"/jobs/{job['id']}/kits", json={}, headers=other).status_code == 404

    # A new search keeps the contact added by hand.
    client.post(f"/jobs/{job['id']}/contacts/search", headers=auth)
    names = [c["full_name"] for c in client.get(f"/jobs/{job['id']}/contacts", headers=auth).json()]
    assert names.count("Ravi Kumar") == 1 and "Priya Sharma" in names


def test_job_input_validation(client, auth, scripted):
    assert client.post("/jobs", json={}, headers=auth).status_code == 422
    assert client.post("/jobs", json={"url": "file:///etc/passwd"}, headers=auth).status_code == 422
    assert (
        client.post("/jobs", json={"text": "x", "company_domain": "lever.co"}, headers=auth).status_code
        == 422
    )
    job = client.post("/jobs", json={"text": JD}, headers=auth).json()
    assert (
        client.patch(f"/jobs/{job['id']}", json={"email_pattern": "{first}@evil"}, headers=auth).status_code
        == 422
    )
    r = client.patch(
        f"/jobs/{job['id']}", json={"company_domain": "https://careers.acme.org/x"}, headers=auth
    )
    assert r.json()["company_domain"] == "acme.org"
    # No profile yet: a kit can't be generated.
    assert client.post(f"/jobs/{job['id']}/kits", json={}, headers=auth).status_code == 409
    assert client.delete(f"/jobs/{job['id']}", headers=auth).status_code == 204


def test_failed_fetch_is_reported(client, auth, monkeypatch):
    import app.jobs.fetch as fetch

    async def boom(url, transport=None):
        raise fetch.FetchError("Couldn't read the posting from that page")

    monkeypatch.setattr(fetch, "fetch_job", boom)
    job = client.post("/jobs", json={"url": "https://acme.com/jobs/1"}, headers=auth).json()
    job = client.get(f"/jobs/{job['id']}", headers=auth).json()
    assert job["status"] == "failed" and "Couldn't read" in job["error"]
    assert client.post(f"/jobs/{job['id']}/contacts/search", headers=auth).status_code == 409
