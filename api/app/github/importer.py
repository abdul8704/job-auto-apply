"""Turn GitHub repos into profile projects.

The LLM summarises each repo only from its README, description, topics and languages; every
technology it lists must appear in that material, so nothing is invented.
"""

import asyncio
import re
from importlib import resources

from pydantic import BaseModel, Field

from app.github.client import GitHubClient, RepoInfo
from app.llm import LLMClient, Message
from app.profile.schema import Bullet, Profile, Project, SkillGroup

MAX_FEATURED = 3


class RepoSummary(BaseModel):
    description: str = Field(description="One sentence: what the project is and does")
    tech: list[str] = Field(default_factory=list, description="Languages, frameworks and tools it uses")
    bullets: list[str] = Field(default_factory=list, description="2-3 resume bullets about what was built")
    domain: str = Field(default="", description="e.g. Web backend, ML, Browser extension, DevOps")


class ImportedRepo(BaseModel):
    name: str
    url: str
    stars: int = 0
    languages: list[str] = Field(default_factory=list)
    featured: bool = False
    project: Project


class GitHubImportResult(BaseModel):
    username: str
    repos: list[ImportedRepo] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list, description="All languages, most code first")
    domains: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _prompt() -> str:
    return resources.files("app.llm.prompts").joinpath("summarize_repo.md").read_text()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+#]", "", s.lower())


def grounded_tech(tech: list[str], repo: RepoInfo) -> list[str]:
    """Keep only technologies that the repo material actually mentions."""
    haystack = _norm(
        " ".join([repo.readme, repo.description, " ".join(repo.topics), " ".join(repo.languages)])
    )
    out: list[str] = []
    for t in tech:
        n = _norm(t)
        if n and n in haystack and t not in out:
            out.append(t)
    return out


async def summarize_repo(llm: LLMClient, repo: RepoInfo) -> RepoSummary:
    material = (
        f"Name: {repo.name}\nDescription: {repo.description}\nTopics: {', '.join(repo.topics)}\n"
        f"Languages: {', '.join(repo.languages)}\nHomepage: {repo.homepage}\n\n"
        f"README:\n<readme>\n{repo.readme or '(no README)'}\n</readme>"
    )
    resp = await llm.generate(
        "extract", [Message.system(_prompt()), Message.user(material)], schema=RepoSummary
    )
    summary: RepoSummary = resp.parsed
    langs = list(repo.languages)
    summary.tech = grounded_tech(summary.tech, repo) or langs[:4]
    return summary


async def import_github(
    llm: LLMClient,
    username: str,
    featured: list[str],
    max_repos: int = 12,
    token: str = "",
    client: GitHubClient | None = None,
) -> GitHubImportResult:
    gh = client or GitHubClient(token)
    result = GitHubImportResult(username=username)
    wanted = {f.lower() for f in featured[:MAX_FEATURED]}
    async with gh:
        repos = await gh.list_repos(username, limit=60)
        # featured repos first, then the most starred / recently pushed
        repos.sort(key=lambda r: (r["name"].lower() not in wanted, -r.get("stargazers_count", 0)))
        found = {r["name"].lower() for r in repos}
        for f in wanted - found:
            result.warnings.append(f"Featured repo {f!r} was not found among public, non-fork repos")
        infos = await asyncio.gather(*(gh.repo_info(r) for r in repos[:max_repos]))

    totals: dict[str, int] = {}
    domains: list[str] = []
    for info in infos:
        for lang, size in info.languages.items():
            totals[lang] = totals.get(lang, 0) + size
        try:
            s = await summarize_repo(llm, info)
        except Exception as exc:  # one bad README must not sink the import
            result.warnings.append(f"{info.name}: summary failed ({type(exc).__name__})")
            s = RepoSummary(description=info.description, tech=list(info.languages)[:4])
        if s.domain and s.domain not in domains:
            domains.append(s.domain)
        is_featured = info.name.lower() in wanted
        result.repos.append(
            ImportedRepo(
                name=info.name,
                url=info.url,
                stars=info.stars,
                languages=list(info.languages),
                featured=is_featured,
                project=Project(
                    name=info.name,
                    description=s.description,
                    tech=s.tech,
                    url=info.url,
                    featured=is_featured,
                    bullets=[Bullet(text=b) for b in s.bullets[:3] if b.strip()],
                ),
            )
        )
    result.languages = [k for k, _ in sorted(totals.items(), key=lambda kv: -kv[1])]
    result.domains = domains
    return result


def merge_into_profile(
    profile: Profile,
    result: GitHubImportResult,
    repo_names: list[str] | None = None,
    add_languages: bool = True,
) -> Profile:
    """Add (or refresh) imported projects. Projects are matched by URL, so re-importing updates them."""
    out = profile.model_copy(deep=True)
    chosen = [r for r in result.repos if repo_names is None or r.name in repo_names]
    by_url = {p.url.rstrip("/").lower(): p for p in out.projects if p.url}
    for repo in chosen:
        key = repo.url.rstrip("/").lower()
        if key in by_url:
            existing = by_url[key]
            existing.description = repo.project.description or existing.description
            existing.tech = repo.project.tech or existing.tech
            if not existing.bullets:
                existing.bullets = repo.project.bullets
            existing.featured = existing.featured or repo.featured
        else:
            out.projects.append(repo.project.model_copy(deep=True))
    if add_languages and result.languages:
        known = {s.lower() for g in out.skills for s in g.items}
        new = [lang for lang in result.languages if lang.lower() not in known]
        if new:
            group = next((g for g in out.skills if g.category.lower() == "languages"), None)
            if group is None:
                out.skills.append(SkillGroup(category="Languages", items=new))
            else:
                group.items += new
    if not any(
        link.url.rstrip("/").lower().endswith(f"github.com/{result.username.lower()}")
        for link in out.contact.links
    ):
        from app.profile.schema import Link

        out.contact.links.append(Link(label="GitHub", url=f"https://github.com/{result.username}"))
    return set_featured(out, [p.id for p in out.projects if p.featured][:MAX_FEATURED])


def set_featured(profile: Profile, project_ids: list[str]) -> Profile:
    if len(project_ids) > MAX_FEATURED:
        raise ValueError(f"Pick at most {MAX_FEATURED} featured projects")
    known = {p.id for p in profile.projects}
    unknown = [i for i in project_ids if i not in known]
    if unknown:
        raise ValueError(f"Unknown project ids: {', '.join(unknown)}")
    out = profile.model_copy(deep=True)
    for p in out.projects:
        p.featured = p.id in project_ids
    # featured projects first, in the order picked
    order = {pid: i for i, pid in enumerate(project_ids)}
    out.projects.sort(key=lambda p: order.get(p.id, len(order)))
    return out
