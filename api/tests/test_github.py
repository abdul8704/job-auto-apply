import asyncio
import base64
import json

import httpx
import pytest

import app.github.importer as importer
from app.github.client import GitHubClient, RepoInfo
from app.github.importer import (
    GitHubImportResult,
    grounded_tech,
    import_github,
    merge_into_profile,
    set_featured,
)
from app.llm import get_llm
from app.profile.schema import Profile
from tests.conftest import signup_and_login
from tests.sample import sample_profile

REPOS = [
    {
        "name": "FlyByViews",
        "full_name": "me/FlyByViews",
        "html_url": "https://github.com/me/flybyviews",
        "description": "Chrome extension",
        "topics": ["chrome-extension"],
        "stargazers_count": 5,
        "fork": False,
    },
    {
        "name": "dsa-mentor",
        "full_name": "me/dsa-mentor",
        "html_url": "https://github.com/me/dsa-mentor",
        "description": "DSA practice coach",
        "topics": [],
        "stargazers_count": 1,
        "fork": False,
    },
    {"name": "saleor", "full_name": "me/saleor", "html_url": "https://github.com/me/saleor", "fork": True},
]
READMES = {
    "me/FlyByViews": "# FlyByViews\nA Chrome MV3 extension in TypeScript that shows window-seat views.",
    "me/dsa-mentor": "# dsa-mentor\nFastAPI backend with Redis queues and the Gemini API.",
}
LANGS = {"me/FlyByViews": {"TypeScript": 9000, "CSS": 1000}, "me/dsa-mentor": {"Python": 20000}}


def github_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/users/me/repos":
            return httpx.Response(200, json=REPOS if request.url.params.get("page") == "1" else [])
        for full, text in READMES.items():
            if path == f"/repos/{full}/readme":
                return httpx.Response(
                    200, json={"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}
                )
            if path == f"/repos/{full}/languages":
                return httpx.Response(200, json=LANGS[full])
        if path == "/users/ghost/repos":
            return httpx.Response(404, json={})
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def summaries(request) -> str:
    material = request.messages[-1].content
    if "FlyByViews" in material:
        # "React" is not in the material and must be dropped
        return json.dumps(
            {
                "description": "Chrome extension showing window-seat views",
                "tech": ["TypeScript", "Chrome MV3", "React"],
                "bullets": ["Built a Chrome MV3 extension in TypeScript"],
                "domain": "Browser extension",
            }
        )
    return json.dumps(
        {
            "description": "DSA practice coach",
            "tech": ["FastAPI", "Redis", "Kubernetes"],
            "bullets": ["Built a FastAPI backend with Redis queues"],
            "domain": "Web backend",
        }
    )


@pytest.fixture
def gh(fake_llm, monkeypatch):
    fake_llm.responder = summaries
    monkeypatch.setattr(
        importer, "GitHubClient", lambda token="": GitHubClient(token, transport=github_transport())
    )
    return fake_llm


def test_grounded_tech_drops_unmentioned_tools():
    repo = RepoInfo(name="x", full_name="me/x", url="", readme="Uses Node.js and C++", languages={"C++": 1})
    assert grounded_tech(["Node.js", "C++", "Rust"], repo) == ["Node.js", "C++"]


def test_import_summarises_repos_without_inventing(gh):
    result = asyncio.run(import_github(get_llm(), "me", ["dsa-mentor", "missing-repo"]))
    names = [r.name for r in result.repos]
    assert names == ["dsa-mentor", "FlyByViews"]  # featured first, forks skipped
    fly = result.repos[1].project
    assert fly.tech == ["TypeScript", "Chrome MV3"]
    assert result.repos[0].project.tech == ["FastAPI", "Redis"] and result.repos[0].featured
    assert result.languages == ["Python", "TypeScript", "CSS"]
    assert any("missing-repo" in w for w in result.warnings)


def test_merge_is_idempotent_and_adds_languages():
    result = GitHubImportResult.model_validate(
        {
            "username": "me",
            "languages": ["Python", "Go"],
            "repos": [
                {
                    "name": "FlyByViews",
                    "url": "https://github.com/example/flybyviews",
                    "featured": True,
                    "project": {
                        "name": "FlyByViews",
                        "url": "https://github.com/example/flybyviews",
                        "description": "new desc",
                        "tech": ["TypeScript"],
                        "featured": True,
                    },
                },
                {
                    "name": "new",
                    "url": "https://github.com/me/new",
                    "project": {"name": "new", "url": "https://github.com/me/new"},
                },
            ],
        }
    )
    once = merge_into_profile(sample_profile(), result)
    twice = merge_into_profile(once, result)
    assert len(twice.projects) == 2 and twice.projects[0].description == "new desc"
    assert twice.projects[0].featured and twice.projects[0].bullets  # existing bullets kept
    langs = next(g for g in twice.skills if g.category == "Languages").items
    assert langs.count("Python") == 1 and "Go" in langs
    assert sum("github.com/me" in link.url for link in twice.contact.links) == 1


def test_set_featured_limits_and_orders():
    p = sample_profile()
    p.projects.append(p.projects[0].model_copy(update={"id": "p2", "name": "Other", "featured": False}))
    out = set_featured(p, ["p2"])
    assert [x.name for x in out.projects] == ["Other", "FlyByViews"] and not out.projects[1].featured
    with pytest.raises(ValueError):
        set_featured(p, ["a", "b", "c", "d"])
    with pytest.raises(ValueError):
        set_featured(p, ["nope"])


def test_import_api_flow(client, auth, gh):
    r = client.post("/github/imports", json={"username": "me", "featured": ["FlyByViews"]}, headers=auth)
    assert r.status_code == 202
    imp = client.get(f"/github/imports/{r.json()['id']}", headers=auth).json()
    assert imp["status"] == "done", imp["error"]
    profile = client.post(
        f"/github/imports/{imp['id']}/apply", json={"repos": ["FlyByViews"]}, headers=auth
    ).json()
    assert [p["name"] for p in profile["projects"]] == ["FlyByViews"] and profile["projects"][0]["featured"]

    pid = profile["projects"][0]["id"]
    assert (
        client.put("/profile/featured", json={"project_ids": []}, headers=auth).json()["projects"][0][
            "featured"
        ]
        is False
    )
    assert client.put("/profile/featured", json={"project_ids": ["zzz"]}, headers=auth).status_code == 422
    assert client.put("/profile/featured", json={"project_ids": [pid]}, headers=auth).status_code == 200

    other = signup_and_login(client, "friend@example.com")
    assert client.get(f"/github/imports/{imp['id']}", headers=other).status_code == 404
    assert client.post("/github/imports", json={"username": "bad name!"}, headers=auth).status_code == 422


def test_import_failure_is_reported(client, auth, gh):
    imp = client.post("/github/imports", json={"username": "ghost"}, headers=auth).json()
    imp = client.get(f"/github/imports/{imp['id']}", headers=auth).json()
    assert imp["status"] == "failed" and "Not found" in imp["error"]
    assert Profile.model_validate(client.get("/profile", headers=auth).json()).projects == []
