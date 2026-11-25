"""Find people to contact about a job and work out their email addresses.

Sources, in order: people named in the posting, then each configured provider (Hunter, Apollo, ...).
People found without an email get one from a provider's email finder, or else a guess from the
company's email pattern. Guesses are verified when a verifier (Hunter) is configured.
Every contact is then sorted into recruiter / hiring_manager / peer / other and ranked.
"""

import logging
import re
from dataclasses import dataclass, field

from app.contacts.base import (
    ContactProvider,
    ContactQuery,
    EmailVerifier,
    FoundContact,
    ProviderError,
)
from app.contacts.patterns import domain_accepts_mail, guess_emails, split_name
from app.jobs.fetch import is_ats_host
from app.jobs.parsing import EMAIL_RE
from app.jobs.schema import JobPosting
from app.settings import Settings, get_settings

log = logging.getLogger("app.contacts")

RECRUITER_WORDS = ("recruit", "talent", "human resource", "hr ", "hrbp", "people", "hiring", "staffing")
GENERIC_HR_MAILBOXES = ("careers", "career", "jobs", "hr", "hiring", "recruit", "talent", "resume", "cv")
SKIP_MAILBOXES = ("noreply", "no-reply", "donotreply", "do-not-reply", "privacy", "abuse", "support", "info")
MANAGER_WORDS = ("manager", "lead", "head", "director", "vp", "vice president", "principal", "cto")
STOP_WORDS = {"senior", "junior", "sr", "jr", "i", "ii", "iii", "staff", "the", "and", "of", "intern", "-"}
MAX_FIND_EMAIL_LOOKUPS = 5


@dataclass
class FinderResult:
    contacts: list[FoundContact] = field(default_factory=list)
    categories: dict[str, str] = field(default_factory=dict)  # email-or-name key -> category
    scores: dict[str, int] = field(default_factory=dict)
    email_pattern: str = ""
    warnings: list[str] = field(default_factory=list)


def contact_key(c: FoundContact) -> str:
    return (c.email or "").lower() or re.sub(r"\s+", " ", c.name().lower()).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9+#]+", text.lower()) if t and t not in STOP_WORDS}


def categorize(c: FoundContact, posting: JobPosting) -> str:
    position = f" {c.position.lower()} "
    local = (c.email or "").split("@")[0].lower()
    if any(w in position for w in RECRUITER_WORDS) or (
        not c.name() and local.startswith(GENERIC_HR_MAILBOXES)
    ):
        return "recruiter"
    job_words = _tokens(" ".join([posting.title, posting.department, *posting.referrer_titles]))
    related = bool(_tokens(c.position) & job_words)
    if related and any(w in position for w in MANAGER_WORDS):
        return "hiring_manager"
    if related:
        return "peer"
    return "other"


_CATEGORY_SCORE = {"recruiter": 40, "hiring_manager": 35, "peer": 30, "other": 5}
_STATUS_SCORE = {"verified": 40, "guessed": 10, "risky": 8, "unknown": 0, "invalid": -60}


def score(c: FoundContact, category: str) -> int:
    s = _CATEGORY_SCORE[category] + _STATUS_SCORE[c.email_status] + c.confidence // 10
    if c.source == "posting":
        s += 25  # the posting told us who to contact
    if not c.email:
        s -= 30
    return s


def posting_contacts(posting: JobPosting, raw_text: str, domain: str) -> list[FoundContact]:
    out: list[FoundContact] = []
    seen: set[str] = set()
    for pc in posting.contacts:
        first, last = split_name(pc.name)
        out.append(
            FoundContact(
                full_name=pc.name,
                first_name=first,
                last_name=last,
                position=pc.role,
                email=pc.email,
                email_status="verified" if pc.email else "unknown",
                confidence=95 if pc.email else 0,
                source="posting",
            )
        )
        if pc.email:
            seen.add(pc.email.lower())
    for email in EMAIL_RE.findall(raw_text or ""):
        local, _, host = email.lower().partition("@")
        if email.lower() in seen or local.startswith(SKIP_MAILBOXES) or is_ats_host(host):
            continue
        seen.add(email.lower())
        out.append(
            FoundContact(
                email=email,
                email_status="verified",
                confidence=95,
                source="posting",
                position="Hiring contact" if local.startswith(GENERIC_HR_MAILBOXES) else "",
            )
        )
    return out


class ContactFinder:
    def __init__(
        self,
        providers: list[ContactProvider],
        verifier: EmailVerifier | None = None,
        settings: Settings | None = None,
    ):
        self.providers = providers
        self.verifier = verifier
        self.settings = settings or get_settings()
        self.verifications_left = self.settings.hunter_verify_guesses
        self.lookups_left = MAX_FIND_EMAIL_LOOKUPS

    async def resolve_email(
        self, c: FoundContact, domain: str, pattern: str, warnings: list[str]
    ) -> FoundContact:
        """Fill in the email for a named person: provider email finders, then a verified guess."""
        if c.email or not domain:
            return c
        first, last = c.first_name, c.last_name
        if not first and c.full_name:
            first, last = split_name(c.full_name)
        if not first:
            return c
        for provider in self.providers:
            if self.lookups_left <= 0:
                break
            try:
                self.lookups_left -= 1
                found = await provider.find_email(first, last, domain)
            except ProviderError as exc:
                warnings.append(f"{provider.name}: {exc}")
                continue
            if found and found.email:
                return c.model_copy(
                    update={
                        "email": found.email,
                        "email_status": found.email_status,
                        "confidence": found.confidence,
                        "first_name": first,
                        "last_name": last,
                    }
                )
        guesses = guess_emails(first, last, domain, pattern)
        if not guesses:
            return c
        base_conf = 70 if pattern else 30
        best = c.model_copy(
            update={
                "email": guesses[0],
                "email_status": "guessed",
                "confidence": base_conf,
                "first_name": first,
                "last_name": last,
            }
        )
        if self.verifier is None:
            return best
        for email in guesses[: 1 if pattern else 2]:
            if self.verifications_left <= 0:
                break
            self.verifications_left -= 1
            try:
                status, conf = await self.verifier.verify(email)
            except ProviderError as exc:
                warnings.append(f"{self.verifier.name}: {exc}")
                break
            if status in ("verified", "risky"):
                return best.model_copy(update={"email": email, "email_status": status, "confidence": conf})
            if status == "invalid" and email == best.email:
                best = best.model_copy(update={"email_status": "invalid", "confidence": conf})
        return best

    async def find(self, posting: JobPosting, raw_text: str, domain: str, pattern: str = "") -> FinderResult:
        result = FinderResult(email_pattern=pattern)
        if domain:
            mx = await domain_accepts_mail(domain)
            if mx is False:
                result.warnings.append(
                    f"{domain} has no mail servers, so it is probably not the company's email domain. "
                    "Set the right domain on the job and search again."
                )
                domain = ""
        else:
            result.warnings.append(
                "The company's email domain is unknown, so emails can't be guessed. "
                "Set company_domain on the job (e.g. acme.com) and search again."
            )

        found = posting_contacts(posting, raw_text, domain)
        query = ContactQuery(
            company=posting.company,
            domain=domain,
            job_title=posting.title,
            department=posting.department,
            referrer_titles=posting.referrer_titles,
            limit=self.settings.contact_search_limit,
        )
        for provider in self.providers:
            try:
                res = await provider.search(query)
            except ProviderError as exc:
                result.warnings.append(f"{provider.name}: {exc}")
                continue
            except Exception as exc:  # a broken provider must not sink the whole search
                log.exception("contact provider %s failed", provider.name)
                result.warnings.append(f"{provider.name}: {type(exc).__name__}: {exc}")
                continue
            result.email_pattern = result.email_pattern or res.email_pattern
            found.extend(res.contacts)

        merged: dict[str, FoundContact] = {}
        for c in found:
            key = contact_key(c)
            if not key:
                continue
            if key not in merged or (not merged[key].email and c.email):
                merged[key] = c

        # Resolve emails for named people, best candidates first so credits go where they matter.
        pending = sorted(merged.values(), key=lambda c: -score(c, categorize(c, posting)))
        resolved: dict[str, FoundContact] = {}
        for c in pending:
            r = await self.resolve_email(c, domain, result.email_pattern, result.warnings)
            key = contact_key(r)
            if key in resolved and resolved[key].email:
                continue
            resolved[key] = r

        for key, c in resolved.items():
            cat = categorize(c, posting)
            result.categories[key] = cat
            result.scores[key] = score(c, cat)
        result.contacts = sorted(resolved.values(), key=lambda c: -result.scores[contact_key(c)])
        result.warnings = list(dict.fromkeys(result.warnings))
        return result


def build_providers(settings: Settings | None = None) -> tuple[list[ContactProvider], EmailVerifier | None]:
    """Providers listed in CONTACT_PROVIDERS that have an API key, plus the verifier if available."""
    s = settings or get_settings()
    providers: list[ContactProvider] = []
    verifier: EmailVerifier | None = None
    for name in s.contact_provider_names:
        if name == "hunter" and s.hunter_api_key:
            from app.contacts.providers.hunter import HunterProvider

            hunter = HunterProvider(s.hunter_api_key)
            providers.append(hunter)
            verifier = hunter
        elif name == "apollo" and s.apollo_api_key:
            from app.contacts.providers.apollo import ApolloProvider

            providers.append(ApolloProvider(s.apollo_api_key))
    return providers, verifier


def provider_status(settings: Settings | None = None) -> dict[str, bool]:
    s = settings or get_settings()
    keys = {"hunter": s.hunter_api_key, "apollo": s.apollo_api_key}
    return {
        "posting": True,
        "pattern_guess": True,
        **{name: bool(keys.get(name)) for name in s.contact_provider_names if name in keys},
    }
