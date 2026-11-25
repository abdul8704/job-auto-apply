"""Hunter.io adapter: domain search (people + the company's email pattern), email finder and verifier.

API docs: https://hunter.io/api-documentation/v2. The free plan includes a small monthly allowance of
searches and verifications, so the finder spends them carefully (see Settings.hunter_verify_guesses).
"""

import httpx

from app.contacts.base import ContactQuery, EmailStatus, FoundContact, ProviderError, SearchResult

BASE = "https://api.hunter.io/v2"

# Hunter's department filter values, keyed by words that show up in a job's department.
_DEPARTMENTS = {
    "engineer": "it",
    "software": "it",
    "developer": "it",
    "data": "it",
    "it": "it",
    "technology": "it",
    "product": "management",
    "design": "design",
    "marketing": "marketing",
    "sales": "sales",
    "finance": "finance",
    "account": "finance",
    "legal": "legal",
    "support": "support",
    "operations": "operations",
}

_STATUS: dict[str, EmailStatus] = {
    "valid": "verified",
    "invalid": "invalid",
    "accept_all": "risky",
    "webmail": "risky",
    "disposable": "invalid",
    "unknown": "unknown",
}


def hunter_department(department: str, job_title: str) -> str | None:
    words = f"{department} {job_title}".lower().replace("/", " ").split()
    for w in words:
        for key, dep in _DEPARTMENTS.items():
            if w.startswith(key):
                return dep
    return None


class HunterProvider:
    name = "hunter"

    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None):
        if not api_key:
            raise ProviderError("HUNTER_API_KEY is not set")
        self.api_key = api_key
        self.transport = transport

    async def _get(self, path: str, params: dict) -> dict:
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            resp = await client.get(f"{BASE}/{path}", params={**params, "api_key": self.api_key})
        if resp.status_code == 429:
            raise ProviderError("Hunter rate limit or monthly quota reached")
        if resp.status_code in (401, 403):
            raise ProviderError("Hunter rejected the API key")
        if resp.status_code == 404:
            return {}
        if resp.status_code >= 400:
            raise ProviderError(f"Hunter {path} failed with {resp.status_code}: {resp.text[:200]}")
        return resp.json().get("data") or {}

    @staticmethod
    def _contact(e: dict) -> FoundContact:
        verification = (e.get("verification") or {}).get("status") or ""
        status = _STATUS.get(verification, "unknown")
        if status == "unknown" and e.get("value"):
            status = "guessed" if (e.get("confidence") or 0) < 90 else "verified"
        return FoundContact(
            first_name=e.get("first_name") or "",
            last_name=e.get("last_name") or "",
            position=e.get("position") or "",
            email=e.get("value") or e.get("email") or "",
            email_status=status,
            confidence=int(e.get("confidence") or e.get("score") or 0),
            source="hunter",
            linkedin_url=e.get("linkedin") or e.get("linkedin_url") or "",
        )

    async def search(self, query: ContactQuery) -> SearchResult:
        base: dict = {"limit": query.limit, "type": "personal"}
        if query.domain:
            base["domain"] = query.domain
        elif query.company:
            base["company"] = query.company
        else:
            return SearchResult()
        result = SearchResult()
        departments = ["hr"]
        if dep := hunter_department(query.department, query.job_title):
            departments.append(dep)
        seen: set[str] = set()
        for dep in departments:
            data = await self._get("domain-search", {**base, "department": dep})
            result.email_pattern = result.email_pattern or (data.get("pattern") or "")
            for e in data.get("emails") or []:
                c = self._contact(e)
                if c.email and c.email.lower() not in seen:
                    seen.add(c.email.lower())
                    result.contacts.append(c)
        return result

    async def find_email(self, first: str, last: str, domain: str) -> FoundContact | None:
        if not (first and last and domain):
            return None
        data = await self._get("email-finder", {"domain": domain, "first_name": first, "last_name": last})
        if not data.get("email"):
            return None
        c = self._contact(data)
        return c.model_copy(update={"first_name": first, "last_name": last})

    async def verify(self, email: str) -> tuple[EmailStatus, int]:
        data = await self._get("email-verifier", {"email": email})
        return _STATUS.get(data.get("status") or data.get("result") or "", "unknown"), int(
            data.get("score") or 0
        )
