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

**Referral outreach v1**

- Add a job by link (Workday via its JSON endpoint, any page with schema.org JobPosting data, or
  plain pages) or by pasting the description. The LLM parses it into title, skills, responsibilities
  and the titles of people who could refer you.
- Find people to contact: anyone named in the posting, plus Hunter.io and Apollo.io when their API
  keys are set. People without an email get one from a provider or a guess from the company's email
  pattern, verified through Hunter when possible. Contacts are ranked as recruiter, hiring manager,
  peer or other. You can also add people you found yourself.
- Generate an application kit: a resume tailored to the job (every line traced to a real profile
  bullet, then checked by a second model, with overstated lines reverted), a referral request, a
  recruiter note, a LinkedIn note and a cover letter (text and PDF). Nothing is sent automatically.

**Phase 1: profile and tailoring**

- Job descriptions from a link or pasted text, a tailored resume with an honesty check, outreach
  messages and a cover letter (see Referral outreach below)
- GitHub import: public repos and READMEs summarised into projects (technologies are kept only if the
  README or repo metadata names them), languages added to skills, and your top 3 projects marked
  as featured so tailoring keeps them
- Email delivery of a kit to yourself (console in dev, SMTP or Amazon SES)
- A web app (`web/`, React + Vite) for the whole flow: upload resume, import GitHub, pick top 3,
  edit the profile, add jobs, tailor, open PDFs, email the kit, draft messages to contacts

## Layout

```text
api/
  app/
    auth/        sign-up (invite-only), login, current user
    profile/     profile schema, resume text extraction + LLM parsing, profile API
    documents/   resume upload API
    resumes/     render and download PDFs
    jobs/        add a job by link or text, fetch (Workday, JSON-LD, HTML) and parse it
    contacts/    contact finder, email patterns, providers/ (hunter, apollo)
    outreach/    tailoring with the honesty check, outreach messages, cover letters, kits API
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

## Web app

```bash
cd web && npm install && npm run dev   # http://localhost:5173, proxies /api to localhost:8000
```

With Docker Compose the web app is served by nginx at http://localhost:8080.

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

## Referral outreach

```bash
# 1. Add a job (or send {"text": "..."} with the pasted description)
JOB=$(curl -s -X POST $API/jobs -H "$H" -H 'content-type: application/json' \
  -d '{"url":"https://acme.wd5.myworkdayjobs.com/External/job/Chennai/SDE_JR123"}' | jq -r .id)
curl -s $API/jobs/$JOB -H "$H" | jq '.status, .company_domain, .parsed.title'
# If the domain is missing or wrong:  PATCH /jobs/$JOB {"company_domain": "acme.com"}

# 2. Find contacts (HR/recruiters and likely referrers)
curl -s -X POST $API/jobs/$JOB/contacts/search -H "$H"
curl -s $API/jobs/$JOB/contacts -H "$H" | jq '.[] | {full_name, position, email, email_status, category}'
# Add someone you found on LinkedIn; their email is looked up or guessed
curl -s -X POST $API/jobs/$JOB/contacts -H "$H" -H 'content-type: application/json' \
  -d '{"name":"Ravi Kumar","position":"Software Engineer"}'

# 3. Generate the tailored resume, messages and cover letter
KIT=$(curl -s -X POST $API/jobs/$JOB/kits -H "$H" -H 'content-type: application/json' -d '{}' | jq -r .id)
curl -s $API/kits/$KIT -H "$H" | jq '.status, .honesty_report, .outreach'
curl -s $API/kits/$KIT/messages/<contact_id> -H "$H" | jq   # email personalised for one contact
curl -s $API/kits/$KIT/cover-letter.pdf -H "$H" -o cover-letter.pdf
curl -s $API/resumes/$(curl -s $API/kits/$KIT -H "$H" | jq -r .resume_id)/pdf -H "$H" -o resume.pdf
```

Contact sources (`GET /contacts/providers` shows which are on):

| Source | Needs | What it gives |
| --- | --- | --- |
| The posting | nothing | names and emails written in the job description |
| Pattern guess | nothing | `first.last@company.com`-style guesses, labelled `guessed` |
| Hunter.io | `HUNTER_API_KEY` | HR and team emails, the company's email pattern, email verification |
| Apollo.io | `APOLLO_API_KEY` | people by title at the company, email reveal (uses Apollo credits) |

`CONTACT_PROVIDERS` sets the order. To add another service (Snov.io, RocketReach), write an adapter
with `search()` and `find_email()` in `app/contacts/providers/` and register it in
`build_providers()` in `app/contacts/finder.py`. Guessed emails are never SMTP-probed from the server,
because that gets server IPs blocklisted; they are verified through Hunter, or left as `guessed`.

## GitHub import

`POST /github/imports {"username": "...", "featured": ["repo-a", "repo-b", "repo-c"]}` reads your
public, non-fork repos, then `POST /github/imports/{id}/apply` adds the chosen ones to your profile.
Re-importing updates projects in place (matched by URL). Set `GITHUB_TOKEN` to raise GitHub's rate
limit. Change your top 3 any time with `PUT /profile/featured`.

## Email

`POST /kits/{id}/email` sends the tailored resume and cover letter to your own address. Set
`MAIL_BACKEND=smtp` (with `SMTP_*`) or `MAIL_BACKEND=ses` on AWS; the default only logs the email.

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
