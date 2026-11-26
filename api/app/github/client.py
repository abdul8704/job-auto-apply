"""Read a user's public GitHub repos: metadata, languages and READMEs (GitHub REST API)."""

import base64
from dataclasses import dataclass, field

import httpx

API = "https://api.github.com"
README_MAX_CHARS = 12_000


class GitHubError(RuntimeError):
    pass


@dataclass
class RepoInfo:
    name: str
    full_name: str
    url: str
    description: str = ""
    homepage: str = ""
    topics: list[str] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)  # language -> bytes of code
    stars: int = 0
    pushed_at: str = ""
    readme: str = ""


class GitHubClient:
    def __init__(self, token: str = "", transport: httpx.AsyncBaseTransport | None = None):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.AsyncClient(base_url=API, headers=headers, timeout=20, transport=transport)

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.http.aclose()

    async def _get(self, path: str, **params) -> httpx.Response:
        resp = await self.http.get(path, params=params or None)
        if resp.status_code == 404:
            raise GitHubError(f"Not found on GitHub: {path}")
        if resp.status_code in (403, 429):
            raise GitHubError("GitHub rate limit reached; set GITHUB_TOKEN or try again later")
        resp.raise_for_status()
        return resp

    async def list_repos(self, username: str, limit: int = 30) -> list[dict]:
        """Public, non-fork, non-archived repos, most recently pushed first."""
        repos: list[dict] = []
        page = 1
        while len(repos) < limit and page <= 5:
            batch = (
                await self._get(
                    f"/users/{username}/repos", per_page=100, page=page, sort="pushed", type="owner"
                )
            ).json()
            if not batch:
                break
            repos += [r for r in batch if not r.get("fork") and not r.get("archived")]
            page += 1
        return repos[:limit]

    async def readme(self, full_name: str) -> str:
        try:
            data = (await self._get(f"/repos/{full_name}/readme")).json()
        except GitHubError:
            return ""
        if data.get("encoding") != "base64":
            return ""
        return base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")[:README_MAX_CHARS]

    async def languages(self, full_name: str) -> dict[str, int]:
        return (await self._get(f"/repos/{full_name}/languages")).json()

    async def repo_info(self, repo: dict) -> RepoInfo:
        full = repo["full_name"]
        return RepoInfo(
            name=repo["name"],
            full_name=full,
            url=repo.get("html_url", f"https://github.com/{full}"),
            description=repo.get("description") or "",
            homepage=repo.get("homepage") or "",
            topics=repo.get("topics") or [],
            languages=await self.languages(full),
            stars=repo.get("stargazers_count", 0),
            pushed_at=repo.get("pushed_at") or "",
            readme=await self.readme(full),
        )
