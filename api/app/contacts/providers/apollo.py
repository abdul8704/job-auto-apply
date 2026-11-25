"""Apollo.io adapter: finds people at a company by title, and reveals a named person's email.

API docs: https://docs.apollo.io/reference. People search returns names and titles without spending
credits; revealing an email (people/match) uses credits from the plan.
"""

import httpx

from app.contacts.base import ContactQuery, EmailStatus, FoundContact, ProviderError, SearchResult

BASE = "https://api.apollo.io/api/v1"
RECRUITER_TITLES = ["recruiter", "talent acquisition", "hr", "human resources", "people partner"]

_STATUS: dict[str, EmailStatus] = {
    "verified": "verified",
    "likely to engage": "verified",
    "guessed": "guessed",
    "extrapolated": "guessed",
    "unavailable": "unknown",
    "bounced": "invalid",
    "pending_manual_fulfillment": "unknown",
}


class ApolloProvider:
    name = "apollo"

    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None):
        if not api_key:
            raise ProviderError("APOLLO_API_KEY is not set")
        self.api_key = api_key
        self.transport = transport

    async def _post(self, path: str, body: dict) -> dict:
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            resp = await client.post(
                f"{BASE}/{path}",
                json=body,
                headers={"x-api-key": self.api_key, "Cache-Control": "no-cache"},
            )
        if resp.status_code == 429:
            raise ProviderError("Apollo rate limit or credits reached")
        if resp.status_code in (401, 403):
            raise ProviderError(f"Apollo refused the request ({resp.status_code}): check the key and plan")
        if resp.status_code >= 400:
            raise ProviderError(f"Apollo {path} failed with {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    @staticmethod
    def _email(person: dict) -> tuple[str, EmailStatus]:
        email = person.get("email") or ""
        if not email or "not_unlocked" in email or "domain.com" in email:
            return "", "unknown"
        return email, _STATUS.get((person.get("email_status") or "").lower(), "guessed")

    def _contact(self, person: dict) -> FoundContact:
        email, status = self._email(person)
        return FoundContact(
            first_name=person.get("first_name") or "",
            last_name=person.get("last_name") or "",
            full_name=person.get("name") or "",
            position=person.get("title") or "",
            email=email,
            email_status=status,
            confidence=90 if status == "verified" else 50 if email else 0,
            source="apollo",
            linkedin_url=person.get("linkedin_url") or "",
        )

    async def search(self, query: ContactQuery) -> SearchResult:
        if not query.domain:
            return SearchResult()
        titles = RECRUITER_TITLES + (query.referrer_titles or [query.job_title])
        data = await self._post(
            "mixed_people/api_search",
            {
                "q_organization_domains_list": [query.domain],
                "person_titles": [t for t in titles if t],
                "per_page": query.limit,
                "page": 1,
            },
        )
        people = data.get("people") or data.get("contacts") or []
        # Search may hide last names; such people can't be emailed or guessed, so skip them.
        contacts = [self._contact(p) for p in people if p.get("first_name") and p.get("last_name")]
        return SearchResult(contacts=contacts)

    async def find_email(self, first: str, last: str, domain: str) -> FoundContact | None:
        if not (first and last and domain):
            return None
        data = await self._post("people/match", {"first_name": first, "last_name": last, "domain": domain})
        person = data.get("person") or {}
        c = self._contact(person)
        return c if c.email else None
