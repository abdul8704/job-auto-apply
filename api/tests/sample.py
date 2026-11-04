from app.profile.schema import Bullet, Contact, Experience, Link, Profile, Project, SkillGroup


def sample_profile() -> Profile:
    return Profile(
        contact=Contact(
            name="Aziz Test",
            email="aziz@example.com",
            phone="+91 90000 00000",
            location="Chennai, India",
            links=[Link(label="GitHub", url="https://github.com/example")],
        ),
        experience=[
            Experience(
                company="Acme & Co",
                title="Backend Intern",
                start="Jun 2025",
                end="Aug 2025",
                bullets=[
                    Bullet(text="Cut API latency by 40% using Redis caching"),
                    Bullet(text="Wrote C# tools"),
                ],
            )
        ],
        projects=[
            Project(
                name="FlyByViews",
                tech=["TypeScript", "Chrome MV3"],
                url="https://github.com/example/flybyviews",
                featured=True,
                bullets=[
                    Bullet(text="Chrome extension with 1k users"),
                    Bullet(text="Uses $DATA_DIR and 100% tests"),
                ],
            )
        ],
        skills=[SkillGroup(category="Languages", items=["Python", "C++", "TypeScript"])],
    )
