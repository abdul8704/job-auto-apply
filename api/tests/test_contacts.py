import asyncio

import httpx
import pytest

import app.contacts.finder as finder_mod
from app.contacts.base import ContactQuery, FoundContact, ProviderError, SearchResult
from app.contacts.finder import ContactFinder, categorize, posting_contacts
from app.contacts.patterns import apply_pattern, guess_emails, split_name, valid_pattern
from app.contacts.providers.apollo import ApolloProvider
from app.contacts.providers.hunter import HunterProvider, hunter_department
from app.jobs.schema import JobPosting, PostingContact
from app.settings import Settings

POSTING = JobPosting(
    title="Backend Engineer",
    company="Acme",
    department="Engineering",
    referrer_titles=["Software Engineer", "Engineering Manager"],
    contacts=[PostingContact(name="Priya Sharma", role="Recruiter")],
)


@pytest.fixture(autouse=True)
def mx_ok(monkeypatch):
    async def accepts(_domain):
        return True

    monkeypatch.setattr(finder_mod, "domain_accepts_mail", accepts)


def test_patterns():
    assert guess_emails("Rahul", "Verma", "acme.com")[:3] == [
        "rahul.verma@acme.com",
        "rahul@acme.com",
        "rverma@acme.com",
    ]
    assert guess_emails("Rahul", "Verma", "acme.com", "{f}{last}") == ["rverma@acme.com"]
    assert apply_pattern("{first}.{last}", "José", "Núñez", "acme.com") == "jose.nunez@acme.com"
    assert apply_pattern("{first}.{last}", "Cher", "", "acme.com") is None
    assert guess_emails("Cher", "", "acme.com") == ["cher@acme.com"]
    assert split_name("Dr. Anita  Rao Iyer") == ("Anita", "Iyer")
    assert valid_pattern("{first}_{l}") and not valid_pattern("{first}@x") and not valid_pattern("")


def test_categorize():
    def c(position, email=""):
        return categorize(
            FoundContact(full_name="A B" if position else "", position=position, email=email), POSTING
        )

    assert c("Senior Talent Acquisition Partner") == "recruiter"
    assert c("HR Business Partner") == "recruiter"
    assert c("Engineering Manager, Platform") == "hiring_manager"
    assert c("Software Engineer II") == "peer"
    assert c("Sales Director") == "other"
    assert c("", "careers@acme.com") == "recruiter"


def test_posting_contacts_skip_noise():
    text = "Apply at careers@acme.com. Questions: noreply@acme.com or apply@greenhouse.io"
    found = posting_contacts(POSTING, text, "acme.com")
    assert [f.email for f in found] == ["", "careers@acme.com"]
    assert found[0].first_name == "Priya" and found[0].source == "posting"


class FakeProvider:
    name = "fakeprov"

    def __init__(self, contacts, pattern="", emails=None, fail=False):
        self.contacts, self.pattern, self.emails, self.fail = contacts, pattern, emails or {}, fail
        self.queries: list[ContactQuery] = []

    async def search(self, query):
        self.queries.append(query)
        if self.fail:
            raise ProviderError("quota reached")
        return SearchResult(contacts=self.contacts, email_pattern=self.pattern)

    async def find_email(self, first, last, domain):
        email = self.emails.get(f"{first} {last}")
        return FoundContact(email=email, email_status="verified", confidence=95) if email else None


class FakeVerifier:
    name = "fakever"

    def __init__(self, valid):
        self.valid, self.calls = set(valid), []

    async def verify(self, email):
        self.calls.append(email)
        return ("verified", 96) if email in self.valid else ("invalid", 5)


def test_finder_merges_ranks_and_guesses():
    provider = FakeProvider(
        [
            FoundContact(
                first_name="Ravi", last_name="Kumar", position="Software Engineer", source="fakeprov"
            ),
            FoundContact(
                first_name="Meena",
                last_name="Iyer",
                position="Technical Recruiter",
                email="meena.iyer@acme.com",
                email_status="verified",
                confidence=97,
                source="fakeprov",
            ),
            FoundContact(first_name="Old", last_name="Name", position="Sales Lead", source="fakeprov"),
        ],
        pattern="{first}.{last}",
        emails={"Ravi Kumar": "ravi.k@acme.com"},
    )
    result = asyncio.run(ContactFinder([provider], settings=Settings()).find(POSTING, "", "acme.com"))
    emails = [c.email for c in result.contacts]
    assert emails[0] == "meena.iyer@acme.com"  # verified recruiter first
    assert "ravi.k@acme.com" in emails  # provider email finder beat the guess
    assert "priya.sharma@acme.com" in emails  # posting name + company pattern
    priya = next(c for c in result.contacts if c.email == "priya.sharma@acme.com")
    assert priya.email_status == "guessed" and result.categories["priya.sharma@acme.com"] == "recruiter"
    assert emails[-1] == "old.name@acme.com"  # unrelated role ranks last
    assert provider.queries[0].domain == "acme.com" and provider.queries[0].referrer_titles


def test_finder_verifies_guesses_and_reports_provider_errors():
    verifier = FakeVerifier({"priya@acme.com"})
    broken = FakeProvider([], fail=True)
    s = Settings(hunter_verify_guesses=3)
    result = asyncio.run(ContactFinder([broken], verifier, settings=s).find(POSTING, "", "acme.com"))
    assert verifier.calls == ["priya.sharma@acme.com", "priya@acme.com"]
    assert result.contacts[0].email == "priya@acme.com" and result.contacts[0].email_status == "verified"
    assert result.warnings == ["fakeprov: quota reached"]


def test_finder_without_domain_or_mail_servers(monkeypatch):
    result = asyncio.run(ContactFinder([], settings=Settings()).find(POSTING, "", ""))
    assert "unknown" in result.warnings[0] and result.contacts[0].email == ""

    async def no_mx(_d):
        return False

    monkeypatch.setattr(finder_mod, "domain_accepts_mail", no_mx)
    result = asyncio.run(ContactFinder([], settings=Settings()).find(POSTING, "", "acme-typo.com"))
    assert "no mail servers" in result.warnings[0]


def test_hunter_adapter():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        assert request.url.params["api_key"] == "k"
        if request.url.path.endswith("domain-search"):
            dep = request.url.params["department"]
            email = {"hr": "meena@acme.com", "it": "ravi@acme.com"}[dep]
            return httpx.Response(
                200,
                json={
                    "data": {
                        "pattern": "{first}",
                        "emails": [
                            {
                                "value": email,
                                "confidence": 94,
                                "first_name": email.split("@")[0].title(),
                                "last_name": "X",
                                "position": "Recruiter" if dep == "hr" else "Engineer",
                                "verification": {"status": "valid"},
                            }
                        ],
                    }
                },
            )
        if request.url.path.endswith("email-verifier"):
            return httpx.Response(200, json={"data": {"status": "accept_all", "score": 60}})
        return httpx.Response(429)

    h = HunterProvider("k", transport=httpx.MockTransport(handler))
    res = asyncio.run(h.search(ContactQuery(domain="acme.com", job_title="Software Engineer")))
    assert res.email_pattern == "{first}"
    assert [c.email for c in res.contacts] == ["meena@acme.com", "ravi@acme.com"]
    assert res.contacts[0].email_status == "verified"
    assert asyncio.run(h.verify("x@acme.com")) == ("risky", 60)
    with pytest.raises(ProviderError, match="quota"):
        asyncio.run(h.find_email("A", "B", "acme.com"))
    assert hunter_department("Data Platform", "") == "it" and hunter_department("", "Chef") is None


def test_apollo_adapter():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "k"
        if request.url.path.endswith("api_search"):
            return httpx.Response(
                200,
                json={
                    "people": [
                        {
                            "first_name": "Ravi",
                            "last_name": "Kumar",
                            "title": "SDE 2",
                            "email": "email_not_unlocked@domain.com",
                        },
                        {"first_name": "Hidden", "last_name": "", "title": "Recruiter"},
                    ]
                },
            )
        return httpx.Response(200, json={"person": {"email": "ravi@acme.com", "email_status": "verified"}})

    a = ApolloProvider("k", transport=httpx.MockTransport(handler))
    res = asyncio.run(a.search(ContactQuery(domain="acme.com", referrer_titles=["Software Engineer"])))
    assert len(res.contacts) == 1 and res.contacts[0].email == ""
    found = asyncio.run(a.find_email("Ravi", "Kumar", "acme.com"))
    assert found.email == "ravi@acme.com" and found.email_status == "verified"
