import shutil

import pytest

from app.profile.schema import Bullet, Profile, Project
from app.rendering.latex import latex_escape, latex_url, render_latex
from app.rendering.service import render_pdf
from tests.sample import sample_profile


def test_escape_special_characters():
    assert latex_escape("R&D 100% #1 $5 a_b {x} ~ ^ \\") == (
        r"R\&D 100\% \#1 \$5 a\_b \{x\} \textasciitilde{} \textasciicircum{} \textbackslash{}"
    )


def test_profile_text_cannot_inject_latex_commands():
    p = Profile(
        projects=[
            Project(name=r"\input{/etc/passwd}", bullets=[Bullet(text=r"\immediate\write18{rm -rf /}")])
        ]
    )
    tex = render_latex(p)
    assert r"\input{/etc/passwd}" not in tex and r"\write18{" not in tex
    assert r"\textbackslash{}input\{/etc/passwd\}" in tex


def test_urls_are_sanitised():
    assert latex_url("github.com/me") == "https://github.com/me"
    assert latex_url("https://x.com/a%20b#c") == r"https://x.com/a\%20b\#c"
    assert "{" not in latex_url("https://x.com/}{\\evil")


def test_template_renders_all_sections():
    tex = render_latex(sample_profile())
    assert tex.startswith(r"\documentclass"), tex[:80]  # nothing may leak before the preamble
    assert r"\href{mailto:aziz@example.com}" in tex
    for expected in (
        r"Acme \& Co",
        "Backend Intern",
        "FlyByViews",
        r"40\%",
        r"\$DATA\_DIR",
        "github.com/example",
        r"\begin{document}",
        r"\end{document}",
    ):
        assert expected in tex, expected


def _fake_compiler(pages_for):
    from io import BytesIO

    from pypdf import PdfWriter

    def compile_(latex: str) -> bytes:
        w = PdfWriter()
        for _ in range(pages_for(latex)):
            w.add_blank_page(612, 792)
        buf = BytesIO()
        w.write(buf)
        return buf.getvalue()

    return compile_


def test_render_trims_bullets_until_it_fits():
    p = sample_profile()
    # pretend the resume is 2 pages while it has more than 2 bullets in total
    compiler = _fake_compiler(lambda tex: 2 if tex.count(r"\item") > 2 else 1)
    result = render_pdf(p, compiler=compiler)
    assert result.pages == 1 and len(result.trimmed) == 2
    assert p.projects[0].bullets[1].id in result.trimmed  # original profile untouched
    assert len(p.projects[0].bullets) == 2


@pytest.mark.skipif(shutil.which("tectonic") is None, reason="tectonic not installed")
def test_real_compile_produces_one_page_pdf():
    result = render_pdf(sample_profile())
    assert result.pdf.startswith(b"%PDF") and result.pages == 1
