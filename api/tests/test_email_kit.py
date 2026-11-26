from app.notify.mailer import Attachment, ConsoleMailer, Email, get_mailer
from tests.sample import sample_profile
from tests.test_outreach import JD, scripted  # noqa: F401  (fixture)


def test_email_builds_with_attachments():
    msg = Email("me@example.com", "Hi", "body", [Attachment("resume.pdf", b"%PDF-1")]).build("bot <b@x.y>")
    assert msg["To"] == "me@example.com"
    assert [p.get_filename() for p in msg.iter_attachments()] == ["resume.pdf"]


def test_kit_is_emailed_to_the_user(client, auth, scripted):  # noqa: F811
    profile = sample_profile()
    client.put("/profile", json=profile.model_dump(), headers=auth)
    scripted["profile"] = profile
    job = client.post("/jobs", json={"text": JD}, headers=auth).json()
    kit = client.post(f"/jobs/{job['id']}/kits", json={}, headers=auth).json()

    mailer = get_mailer()
    assert isinstance(mailer, ConsoleMailer)
    mailer.outbox.clear()
    r = client.post(f"/kits/{kit['id']}/email", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json() == {"sent_to": "me@example.com", "attachments": ["resume.pdf", "cover-letter.pdf"]}
    sent = mailer.outbox[-1]
    assert "Backend Engineer" in sent.subject and "Missing" not in sent.text
    assert "Lines reverted by the honesty check: 1" in sent.text
