"""LLM output shapes for tailoring and outreach, and what the API returns."""

from pydantic import BaseModel, Field

from app.profile.schema import SkillGroup


class TailoredBullet(BaseModel):
    source_id: str = Field(description="id of the profile bullet this line is based on")
    text: str


class TailoredItem(BaseModel):
    id: str = Field(description="id of the profile experience or project")
    bullets: list[TailoredBullet] = Field(default_factory=list)


class TailoringPlan(BaseModel):
    summary: str = Field(default="", description="2-3 line summary aimed at this job, using only real facts")
    experience: list[TailoredItem] = Field(default_factory=list)
    projects: list[TailoredItem] = Field(default_factory=list, description="Most relevant first, at most 4")
    skills: list[SkillGroup] = Field(default_factory=list, description="Only skills already in the profile")
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(
        default_factory=list, description="Job requirements the profile shows no evidence of"
    )


class CheckItem(BaseModel):
    id: str
    supported: bool
    reason: str = ""


class HonestyCheck(BaseModel):
    items: list[CheckItem] = Field(default_factory=list)


class EmailDraft(BaseModel):
    subject: str
    body: str = Field(description="Plain text. Use {first_name} where the recipient's first name goes.")


class CoverLetter(BaseModel):
    greeting: str = Field(default="Dear Hiring Team,")
    paragraphs: list[str] = Field(default_factory=list)
    closing: str = Field(default="Sincerely,")

    def as_text(self, name: str) -> str:
        return "\n\n".join([self.greeting, *self.paragraphs, f"{self.closing}\n{name}".strip()])


class Outreach(BaseModel):
    referral_request: EmailDraft = Field(description="To an employee who could refer the candidate")
    recruiter_note: EmailDraft = Field(description="To a recruiter or HR person about the role")
    linkedin_note: str = Field(default="", description="Connection request note, under 300 characters")
    cover_letter: CoverLetter = Field(default_factory=CoverLetter)
