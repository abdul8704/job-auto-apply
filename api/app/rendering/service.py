"""Render a profile to a PDF that fits the page limit, trimming the least important bullets if needed."""

from collections.abc import Callable
from dataclasses import dataclass, field

from app.profile.schema import Profile
from app.rendering.compile import compile_latex, page_count
from app.rendering.latex import render_latex


@dataclass
class RenderResult:
    pdf: bytes
    pages: int
    latex: str
    trimmed: list[str] = field(default_factory=list)  # bullet ids removed to fit the page limit


def _trim_one(profile: Profile) -> str | None:
    """Drop the last bullet of whichever entry has the most bullets (projects before experience)."""
    candidates = [p for p in profile.projects if len(p.bullets) > 1] + [
        x for x in profile.experience if len(x.bullets) > 1
    ]
    if not candidates:
        return None
    target = max(candidates, key=lambda item: len(item.bullets))
    return target.bullets.pop().id


def render_pdf(
    profile: Profile,
    template: str = "classic",
    max_pages: int = 1,
    max_trims: int = 12,
    compiler: Callable[[str], bytes] | None = None,
) -> RenderResult:
    compiler = compiler or compile_latex
    working = profile.model_copy(deep=True)
    trimmed: list[str] = []
    while True:
        latex = render_latex(working, template)
        pdf = compiler(latex)
        pages = page_count(pdf)
        if pages <= max_pages or len(trimmed) >= max_trims:
            return RenderResult(pdf=pdf, pages=pages, latex=latex, trimmed=trimmed)
        removed = _trim_one(working)
        if removed is None:
            return RenderResult(pdf=pdf, pages=pages, latex=latex, trimmed=trimmed)
        trimmed.append(removed)
