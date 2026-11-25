"""Write the referral request, recruiter note, LinkedIn note and cover letter for a job."""

from importlib import resources

from app.jobs.schema import JobPosting
from app.llm import LLMClient, Message
from app.outreach.schema import EmailDraft, Outreach
from app.profile.schema import Profile


async def write_outreach(llm: LLMClient, profile: Profile, posting: JobPosting, job_url: str) -> Outreach:
    prompt = resources.files("app.llm.prompts").joinpath("write_outreach.md").read_text()
    resp = await llm.generate(
        "write",
        [
            Message.system(prompt),
            Message.user(
                f"Job link: {job_url or '(none)'}\n\nJob:\n{posting.model_dump_json(indent=1)}\n\n"
                f"Candidate profile:\n{profile.model_dump_json(indent=1)}"
            ),
        ],
        schema=Outreach,
    )
    return resp.parsed


def personalize(draft: EmailDraft, first_name: str) -> EmailDraft:
    name = first_name.strip().title() or "there"
    return EmailDraft(
        subject=draft.subject.replace("{first_name}", name), body=draft.body.replace("{first_name}", name)
    )
