"""Tailor a profile to a job, then hold the result to the profile's facts.

The LLM proposes a plan (TailoringPlan); apply_plan() only accepts what can be traced back to real
profile items, and verify() asks a second model to flag any rewritten line that overstates its
source. Flagged lines are reverted to the original wording.
"""

import json
from importlib import resources

from app.jobs.schema import JobPosting
from app.llm import LLMClient, Message
from app.outreach.schema import HonestyCheck, TailoringPlan
from app.profile.schema import Bullet, Experience, Profile, Project, SkillGroup

MAX_PROJECTS = 4


def _prompt(name: str) -> str:
    return resources.files("app.llm.prompts").joinpath(name).read_text()


def _bullets(item: Experience | Project, planned, limit: int, changes: list[dict]) -> list[Bullet]:
    by_id = {b.id: b for b in item.bullets}
    out: list[Bullet] = []
    used: set[str] = set()
    for tb in planned.bullets if planned else []:
        src = by_id.get(tb.source_id)
        if src is None or src.id in used:
            continue  # not a real bullet of this item: drop it
        used.add(src.id)
        text = tb.text.strip() or src.text
        out.append(Bullet(id=src.id, text=text))
        if text != src.text:
            changes.append({"id": src.id, "original": src.text, "text": text})
        if len(out) >= limit:
            break
    return out or [b.model_copy() for b in item.bullets]


def _skills(profile: Profile, planned: list[SkillGroup]) -> tuple[list[SkillGroup], list[str]]:
    known = {s.lower(): s for g in profile.skills for s in g.items}
    groups: list[SkillGroup] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for g in planned:
        items = []
        for s in g.items:
            real = known.get(s.strip().lower())
            if real is None:
                rejected.append(s)
            elif real.lower() not in seen:
                seen.add(real.lower())
                items.append(real)
        if items:
            groups.append(SkillGroup(category=g.category or "Skills", items=items))
    return (groups or [g.model_copy() for g in profile.skills]), rejected


def apply_plan(profile: Profile, plan: TailoringPlan) -> tuple[Profile, list[dict], dict]:
    """Returns (tailored profile, rewritten lines to verify, report)."""
    changes: list[dict] = []
    out = profile.model_copy(deep=True)

    planned_exp = {p.id: p for p in plan.experience}
    out.experience = [
        x.model_copy(update={"bullets": _bullets(x, planned_exp.get(x.id), 4, changes)})
        for x in profile.experience
    ]

    projects_by_id = {p.id: p for p in profile.projects}
    picked: list[Project] = []
    for pp in plan.projects:
        proj = projects_by_id.get(pp.id)
        if proj is None or proj.id in {x.id for x in picked}:
            continue
        picked.append(proj.model_copy(update={"bullets": _bullets(proj, pp, 3, changes)}))
        if len(picked) >= MAX_PROJECTS:
            break
    if picked:
        out.projects = picked

    out.skills, rejected = _skills(profile, plan.skills)

    summary = plan.summary.strip()
    if summary and summary != profile.summary:
        out.summary = summary
        changes.append({"id": "summary", "original": profile.summary, "text": summary})

    report = {
        "rewritten": len(changes),
        "reverted": [],
        "rejected_skills": rejected,
        "matched_keywords": plan.matched_keywords,
        "missing_keywords": plan.missing_keywords,
        "dropped_projects": [p.name for p in profile.projects if p.id not in {x.id for x in out.projects}],
    }
    return out, changes, report


def revert(tailored: Profile, original: Profile, ids: set[str]) -> Profile:
    originals = {b.id: b.text for item in [*original.experience, *original.projects] for b in item.bullets}
    out = tailored.model_copy(deep=True)
    for item in [*out.experience, *out.projects]:
        for b in item.bullets:
            if b.id in ids:
                b.text = originals.get(b.id, b.text)
    if "summary" in ids:
        out.summary = original.summary
    return out


async def tailor(llm: LLMClient, profile: Profile, posting: JobPosting) -> tuple[Profile, dict]:
    resp = await llm.generate(
        "write",
        [
            Message.system(_prompt("tailor_resume.md")),
            Message.user(
                f"Job:\n{posting.model_dump_json(indent=1)}\n\nProfile:\n{profile.model_dump_json(indent=1)}"
            ),
        ],
        schema=TailoringPlan,
    )
    tailored, changes, report = apply_plan(profile, resp.parsed)
    if changes:
        check = await llm.generate(
            "verify",
            [
                Message.system(_prompt("verify_tailoring.md")),
                Message.user(
                    f"Original profile:\n{profile.model_dump_json(indent=1)}\n\n"
                    f"Rewritten lines:\n{json.dumps(changes, indent=1)}"
                ),
            ],
            schema=HonestyCheck,
        )
        verdicts = {i.id: i for i in check.parsed.items}
        # A line the checker didn't return is treated as unsupported: fail closed.
        flagged = {c["id"] for c in changes if not (c["id"] in verdicts and verdicts[c["id"]].supported)}
        tailored = revert(tailored, profile, flagged)
        report["reverted"] = [
            {
                "id": c["id"],
                "text": c["text"],
                "reason": verdicts[c["id"]].reason if c["id"] in verdicts else "not checked",
            }
            for c in changes
            if c["id"] in flagged
        ]
    return tailored, report
