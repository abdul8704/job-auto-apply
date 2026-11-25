"""What the LLM extracts from a job posting."""

from pydantic import BaseModel, Field


class PostingContact(BaseModel):
    """A person named in the posting itself, e.g. 'Contact Priya Sharma (priya@acme.com) to apply'."""

    name: str = ""
    role: str = Field(default="", description="e.g. Recruiter, Hiring Manager, as stated in the posting")
    email: str = ""


class JobPosting(BaseModel):
    title: str = ""
    company: str = ""
    company_website: str = Field(default="", description="The employer's own website if stated, else empty")
    location: str = ""
    job_id: str = Field(default="", description="Requisition or job id, e.g. JR-12345")
    department: str = Field(default="", description="e.g. Engineering, Data, Product, Sales")
    seniority: str = Field(default="", description="e.g. Intern, Entry level, Senior")
    summary: str = Field(default="", description="One or two sentences on what the role is")
    responsibilities: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list, description="Tools, technologies and domain terms")
    referrer_titles: list[str] = Field(
        default_factory=list,
        description="3-5 job titles of employees who would work with this hire and could refer, "
        "e.g. 'Software Engineer', 'Engineering Manager'",
    )
    contacts: list[PostingContact] = Field(default_factory=list)
