"""The structured profile: the single source of truth for every resume the app renders.

Every experience, project and bullet has a stable id so later phases can prove each tailored
line came from a real profile item (the honesty check).
"""

import uuid

from pydantic import BaseModel, Field


def _id() -> str:
    return uuid.uuid4().hex[:8]


class Link(BaseModel):
    label: str = Field(description="e.g. GitHub, LinkedIn, Portfolio")
    url: str


class Contact(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[Link] = Field(default_factory=list)


class Bullet(BaseModel):
    id: str = Field(default_factory=_id)
    text: str


class Experience(BaseModel):
    id: str = Field(default_factory=_id)
    company: str
    title: str
    location: str = ""
    start: str = Field(default="", description="As written on the resume, e.g. 'Jun 2024'")
    end: str = Field(default="", description="e.g. 'Aug 2024' or 'Present'")
    bullets: list[Bullet] = Field(default_factory=list)


class Project(BaseModel):
    id: str = Field(default_factory=_id)
    name: str
    description: str = ""
    tech: list[str] = Field(default_factory=list)
    url: str = ""
    featured: bool = Field(default=False, description="One of the user's top 3 projects")
    bullets: list[Bullet] = Field(default_factory=list)


class Education(BaseModel):
    id: str = Field(default_factory=_id)
    institution: str
    degree: str = ""
    field: str = ""
    location: str = ""
    start: str = ""
    end: str = ""
    grade: str = Field(default="", description="e.g. 'CGPA 8.9/10'")
    highlights: list[str] = Field(default_factory=list)


class SkillGroup(BaseModel):
    category: str = Field(description="e.g. Languages, Frameworks, Tools")
    items: list[str] = Field(default_factory=list)


class Profile(BaseModel):
    contact: Contact = Field(default_factory=Contact)
    summary: str = ""
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)

    def with_fresh_ids(self) -> "Profile":
        """Ids from an LLM are untrusted; replace them all with new unique ones."""
        data = self.model_copy(deep=True)
        for group in (data.experience, data.projects, data.education):
            for item in group:
                item.id = _id()
        for item in [*data.experience, *data.projects]:
            for b in item.bullets:
                b.id = _id()
        return data
