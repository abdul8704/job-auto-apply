"""Turn an uploaded resume into a structured Profile: extract text, then let the LLM structure it."""

import io
from importlib import resources

from app.llm import FilePart, LLMClient, Message
from app.profile.schema import Profile

SUPPORTED = {
    ".pdf": ("pdf", "application/pdf"),
    ".docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".tex": ("tex", "application/x-tex"),
}
MIN_TEXT_CHARS = 200  # below this a PDF is probably scanned or oddly built; send the file itself


class UnsupportedFile(ValueError):
    pass


def detect_kind(filename: str) -> tuple[str, str]:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in SUPPORTED:
        raise UnsupportedFile(f"Unsupported file type {suffix or '(none)'}; upload PDF, DOCX or .tex")
    return SUPPORTED[suffix]


def extract_text(kind: str, data: bytes) -> str:
    if kind == "pdf":
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages).strip()
    if kind == "docx":
        import docx

        d = docx.Document(io.BytesIO(data))
        lines = [p.text for p in d.paragraphs]
        for table in d.tables:
            for row in table.rows:
                lines.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(line for line in lines if line.strip())
    if kind == "tex":
        return data.decode("utf-8", errors="replace")
    raise UnsupportedFile(kind)


def _prompt() -> str:
    return resources.files("app.llm.prompts").joinpath("extract_profile.md").read_text()


async def parse_resume(llm: LLMClient, kind: str, text: str, raw: bytes | None = None) -> Profile:
    content: list[str | FilePart] = []
    if kind == "pdf" and len(text) < MIN_TEXT_CHARS and raw is not None:
        content.append(FilePart(data=raw, mime_type="application/pdf"))
        content.append("The resume is the attached PDF.")
    else:
        label = "LaTeX source" if kind == "tex" else "text"
        content.append(f"Resume ({label}):\n\n<resume>\n{text}\n</resume>")
    resp = await llm.generate("extract", [Message.system(_prompt()), Message.user(*content)], schema=Profile)
    return resp.parsed.with_fresh_ids()
