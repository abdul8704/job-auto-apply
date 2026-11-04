"""Compile LaTeX to PDF with Tectonic in a throwaway directory, with shell-escape disabled."""

import io
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader

from app.settings import get_settings


class LatexCompileError(RuntimeError):
    def __init__(self, message: str, log: str = ""):
        self.log = log
        tail = "\n".join(log.strip().splitlines()[-25:])
        super().__init__(f"{message}\n{tail}" if tail else message)


def compile_latex(source: str) -> bytes:
    s = get_settings()
    with tempfile.TemporaryDirectory(prefix="latex-") as tmp:
        tex = Path(tmp) / "main.tex"
        tex.write_text(source)
        cmd = [s.tectonic_bin, "--untrusted", "--keep-logs", "--outdir", tmp, str(tex)]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=s.latex_timeout_seconds, cwd=tmp
            )
        except FileNotFoundError as exc:
            raise LatexCompileError(f"Tectonic not found at {s.tectonic_bin!r}") from exc
        except subprocess.TimeoutExpired as exc:
            raise LatexCompileError("LaTeX compile timed out") from exc
        pdf = Path(tmp) / "main.pdf"
        if proc.returncode != 0 or not pdf.exists():
            log = (proc.stderr or "") + (proc.stdout or "")
            raise LatexCompileError("LaTeX compile failed", log=log[-4000:])
        return pdf.read_bytes()


def page_count(pdf: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf)).pages)
