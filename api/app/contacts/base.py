"""Neutral types for contact finding. Each email-finding service is an adapter behind ContactProvider."""

from typing import Literal, Protocol

from pydantic import BaseModel, Field

EmailStatus = Literal["verified", "guessed", "risky", "invalid", "unknown"]


class ContactQuery(BaseModel):
    company: str = ""
    domain: str = ""
    job_title: str = ""
    department: str = ""
    referrer_titles: list[str] = Field(default_factory=list)
    limit: int = 10


class FoundContact(BaseModel):
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    position: str = ""
    email: str = ""
    email_status: EmailStatus = "unknown"
    confidence: int = 0  # 0-100: how sure the source is about the email
    source: str = ""
    linkedin_url: str = ""

    def name(self) -> str:
        return self.full_name or " ".join(p for p in (self.first_name, self.last_name) if p)


class SearchResult(BaseModel):
    contacts: list[FoundContact] = Field(default_factory=list)
    email_pattern: str = ""  # e.g. "{first}.{last}" when the provider knows the company's format


class ProviderError(RuntimeError):
    pass


class ContactProvider(Protocol):
    name: str

    async def search(self, query: ContactQuery) -> SearchResult:
        """People at the company relevant to the job (recruiters/HR and likely referrers)."""
        ...

    async def find_email(self, first: str, last: str, domain: str) -> FoundContact | None:
        """The email of a named person, or None if this provider can't find one."""
        ...


class EmailVerifier(Protocol):
    name: str

    async def verify(self, email: str) -> tuple[EmailStatus, int]:
        """(status, confidence 0-100)."""
        ...
