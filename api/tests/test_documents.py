import io
import json

import docx

from app.profile.schema import Profile
from tests.conftest import signup_and_login
from tests.sample import sample_profile


def _docx_bytes() -> bytes:
    d = docx.Document()
    d.add_paragraph("Aziz Test")
    d.add_paragraph("Backend Intern, Acme & Co, Jun 2025 - Aug 2025")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_upload_docx_parses_into_draft_and_applies(client, auth, fake_llm):
    fake_llm.responses = [json.dumps(sample_profile().model_dump())]
    files = {"file": ("resume.docx", _docx_bytes(), "application/octet-stream")}
    r = client.post("/documents", files=files, headers=auth)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "parsed", doc["error"]
    assert doc["parsed_profile"]["experience"][0]["company"] == "Acme & Co"

    sent = fake_llm.requests[0].messages[-1].content
    assert "Acme & Co" in sent and fake_llm.requests[0].json_schema is not None

    # ids are replaced by the app, not trusted from the model
    assert doc["parsed_profile"]["experience"][0]["id"] != sample_profile().experience[0].id

    applied = client.post(f"/documents/{doc['id']}/apply", headers=auth)
    assert applied.status_code == 200
    assert Profile.model_validate(client.get("/profile", headers=auth).json()).contact.name == "Aziz Test"


def test_tex_upload_sends_source_to_llm(client, auth, fake_llm):
    fake_llm.responses = [json.dumps(Profile().model_dump())]
    tex = rb"\documentclass{article}\begin{document}\textbf{Aziz}\end{document}"
    r = client.post("/documents", files={"file": ("cv.tex", tex, "text/plain")}, headers=auth)
    assert r.json()["status"] == "parsed"
    assert "LaTeX source" in fake_llm.requests[0].messages[-1].content


def test_parse_failure_is_reported(client, auth, fake_llm):
    fake_llm.responses = ["not json", "still not json"]
    r = client.post("/documents", files={"file": ("cv.tex", b"hello", "text/plain")}, headers=auth)
    assert r.json()["status"] == "failed" and "did not match Profile" in r.json()["error"]


def test_unsupported_and_foreign_documents(client, auth, fake_llm):
    assert (
        client.post("/documents", files={"file": ("a.png", b"x", "image/png")}, headers=auth).status_code
        == 415
    )
    fake_llm.responses = [json.dumps(Profile().model_dump())]
    doc_id = client.post("/documents", files={"file": ("cv.tex", b"x", "text/plain")}, headers=auth).json()[
        "id"
    ]
    other = signup_and_login(client, "friend@example.com")
    assert client.get(f"/documents/{doc_id}", headers=other).status_code == 404
    assert client.delete(f"/documents/{doc_id}", headers=other).status_code == 404
    assert client.delete(f"/documents/{doc_id}", headers=auth).status_code == 204
