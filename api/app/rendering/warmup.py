"""Compile a sample resume once so Tectonic downloads and caches its packages (run at image build)."""

from app.profile.schema import Bullet, Contact, Experience, Link, Profile, SkillGroup
from app.rendering.compile import compile_latex, page_count
from app.rendering.latex import render_latex

if __name__ == "__main__":
    profile = Profile(
        contact=Contact(
            name="Warm Up", email="a@b.c", links=[Link(label="GitHub", url="https://github.com")]
        ),
        experience=[
            Experience(
                company="Co",
                title="Engineer",
                start="2024",
                end="Present",
                bullets=[Bullet(text="Did things")],
            )
        ],
        skills=[SkillGroup(category="Languages", items=["Python"])],
    )
    pdf = compile_latex(render_latex(profile))
    print(f"tectonic warm-up ok: {page_count(pdf)} page(s)")
