from io import BytesIO

from pypdf import PdfWriter

import app.rendering.service as service
from tests.conftest import signup_and_login
from tests.sample import sample_profile


def _one_page(_latex: str) -> bytes:
    w = PdfWriter()
    w.add_blank_page(612, 792)
    buf = BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_render_and_download(client, auth, monkeypatch):
    monkeypatch.setattr(service, "compile_latex", _one_page)
    client.put("/profile", json=sample_profile().model_dump(), headers=auth)

    r = client.post("/resumes", json={"template": "classic"}, headers=auth)
    assert r.status_code == 202
    resume = client.get(f"/resumes/{r.json()['id']}", headers=auth).json()
    assert resume["status"] == "done", resume["error"]
    assert resume["pages"] == 1

    pdf = client.get(f"/resumes/{resume['id']}/pdf", headers=auth)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    other = signup_and_login(client, "friend@example.com")
    assert client.get(f"/resumes/{resume['id']}/pdf", headers=other).status_code == 404


def test_compile_errors_are_reported(client, auth, monkeypatch):
    from app.rendering.compile import LatexCompileError

    def broken(_latex):
        raise LatexCompileError("LaTeX compile failed", log="! Undefined control sequence")

    monkeypatch.setattr(service, "compile_latex", broken)
    r = client.post("/resumes", json={}, headers=auth)
    resume = client.get(f"/resumes/{r.json()['id']}", headers=auth).json()
    assert resume["status"] == "failed" and "Undefined control sequence" in resume["error"]


def test_preview_tex_and_templates(client, auth):
    client.put("/profile", json=sample_profile().model_dump(), headers=auth)
    assert client.get("/resumes/templates").json() == ["classic"]
    tex = client.get("/resumes/preview.tex", headers=auth)
    assert tex.status_code == 200 and "FlyByViews" in tex.text
