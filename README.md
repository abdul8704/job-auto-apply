# job-auto-apply

A personal tool that keeps your resume as structured data, tailors it to each job description, and
(in later phases) fills job application forms through a Chrome extension. It is built for one user
first, with everything scoped per user so friends can be invited later.

Plan and design: [Auto Job-Apply Tool: Plan and Design](https://claude.ai/artifact/DaakToNYgPD5JDeR7Z9ytU)

## Status

**Phase 0: foundations** (this code)

- FastAPI backend with invite-only email and password auth (JWT)
- A structured profile (`app/profile/schema.py`) as the single source of truth
- Resume upload (PDF, DOCX or `.tex`), with text extraction and LLM structuring into a profile draft
  that you review and apply
- A provider-agnostic LLM layer (`app/llm/`) that runs on Gemini today
- LaTeX rendering through Jinja templates with automatic escaping, compiled by Tectonic with
  shell-escape disabled, and bullets trimmed automatically to fit one page
- Celery background jobs (run inline in dev), Postgres + Alembic, local or S3 file storage
- Docker Compose for a laptop or a single EC2 server, and CI with lint, tests, a real LaTeX compile,
  Postgres migrations and a Docker build

Next: Phase 1, which adds GitHub import, top-3 projects and JD-based tailoring with an honesty checker.

## Layout

```text
api/
  app/
    auth/        sign-up (invite-only), login, current user
    profile/     profile schema, resume text extraction + LLM parsing, profile API
    documents/   resume upload API
    resumes/     render and download PDFs
    llm/         provider-agnostic LLM client, providers/ (gemini, fake), prompts/
    rendering/   LaTeX templates, escaping, Tectonic compile, page-fit trimming
    worker.py    Celery app and background tasks
  config/llm.yaml   which provider + model serves each role
  alembic/          database migrations
  tests/
docker-compose.yml
```

## Run it locally (no Docker)

Needs Python 3.12+ and, for PDF output, [Tectonic](https://tectonic-typesetting.github.io/) on your PATH.

```bash
cd api
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp ../.env.example .env        # add GEMINI_API_KEY
uvicorn app.main:app --reload
```

This uses SQLite in `api/data/` and runs background jobs inline, so you don't need Redis or Postgres.
Open http://localhost:8000/docs for the interactive API.

## Run it with Docker Compose

```bash
cp .env.example .env           # add GEMINI_API_KEY and a long random JWT_SECRET
docker compose up --build
```

This starts the API (port 8000), a Celery worker, Postgres (with pgvector) and Redis, and runs migrations
on start. The same setup works on a single EC2 instance.

## Try the flow

```bash
API=http://localhost:8000
curl -s -X POST $API/auth/signup -H 'content-type: application/json' \
  -d '{"email":"me@example.com","password":"a-long-password"}'
TOKEN=$(curl -s -X POST $API/auth/login -d 'username=me@example.com&password=a-long-password' | jq -r .access_token)
H="Authorization: Bearer $TOKEN"

# 1. Upload your resume and check the parsed draft
DOC=$(curl -s -X POST $API/documents -H "$H" -F file=@resume.pdf | jq -r .id)
curl -s $API/documents/$DOC -H "$H" | jq '.status, .parsed_profile'

# 2. Copy it into your profile (or edit it and PUT /profile)
curl -s -X POST $API/documents/$DOC/apply -H "$H"

# 3. Render a PDF
RES=$(curl -s -X POST $API/resumes -H "$H" -H 'content-type: application/json' -d '{}' | jq -r .id)
curl -s $API/resumes/$RES -H "$H" | jq
curl -s $API/resumes/$RES/pdf -H "$H" -o resume.pdf
```

The first account can always sign up and becomes the admin. After that, only emails listed in
`SIGNUP_ALLOWLIST` can sign up.

## LLM providers

Code never names a model. It asks for a role:

```python
from app.llm import Message, get_llm

resp = await get_llm().generate("extract", [Message.user("...")], schema=MyPydanticModel)
resp.parsed  # validated MyPydanticModel
```

`api/config/llm.yaml` maps each role (`extract`, `write`, `verify`, `agent`) to a provider and model,
with optional fallbacks. The client handles retries with backoff on rate limits and 5xx errors,
falls back to the next provider, validates structured output with pydantic (with one repair retry), and
logs token usage.

To add a provider (Claude, OpenAI, Ollama), write an adapter in `app/llm/providers/` with an async
`generate(LLMRequest) -> LLMResponse`, register it in `PROVIDER_FACTORIES` in `app/llm/client.py`, and
point roles at it in `llm.yaml`.

Note: on Gemini's free tier, Google may use prompts to improve its products. Use a paid key before
other people upload their resumes.

## Tests

```bash
cd api && pytest -q && ruff check . && ruff format --check .
```

Tests use SQLite and a scripted fake LLM, so they need no API key or network. The real LaTeX compile
test runs only when `tectonic` is installed, and CI always installs it.
