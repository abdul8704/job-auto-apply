"""Structure a job posting's text with the LLM."""

import re
from importlib import resources

from app.jobs.schema import JobPosting
from app.llm import LLMClient, Message

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _prompt() -> str:
    return resources.files("app.llm.prompts").joinpath("parse_job.md").read_text()


async def parse_job(llm: LLMClient, text: str, max_chars: int = 30_000) -> JobPosting:
    body = text[:max_chars]
    resp = await llm.generate(
        "extract",
        [Message.system(_prompt()), Message.user(f"Job posting:\n\n<posting>\n{body}\n</posting>")],
        schema=JobPosting,
    )
    posting: JobPosting = resp.parsed
    # Keep only emails that really appear in the posting: the model must not invent addresses.
    present = {e.lower() for e in EMAIL_RE.findall(body)}
    for c in posting.contacts:
        if c.email and c.email.lower() not in present:
            c.email = ""
    return posting
