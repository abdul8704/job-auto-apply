import asyncio
import json

import httpx
import pytest

import app.jobs.fetch as fetch
from app.jobs.fetch import (
    FetchError,
    check_public_url,
    guess_company_domain,
    html_to_text,
    normalize_domain,
    parse_html,
    workday_api_url,
)

DESCRIPTION = (
    "<p>Build APIs in <b>Python</b> &amp; FastAPI.</p><ul><li>Own services</li><li>Write tests</li></ul>"
)


def jsonld_page() -> str:
    data = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebPage", "name": "Careers"},
            {
                "@type": "JobPosting",
                "title": "Backend Engineer",
                "description": DESCRIPTION,
                "hiringOrganization": {
                    "@type": "Organization",
                    "name": "Acme",
                    "sameAs": "https://www.acme.com",
                },
                "jobLocation": {
                    "@type": "Place",
                    "address": {"addressLocality": "Chennai", "addressCountry": "IN"},
                },
            },
        ],
    }
    script = f'<script type="application/ld+json">{json.dumps(data)}</script>'
    return f"<html><head>{script}</head><body>x</body></html>"


def test_jsonld_posting_is_preferred():
    job = parse_html("https://boards.greenhouse.io/acme/jobs/1", jsonld_page())
    assert job.source == "jsonld"
    assert job.title == "Backend Engineer" and job.company == "Acme"
    assert job.company_website == "https://www.acme.com"
    assert "Location: Chennai, IN" in job.text
    assert "Python & FastAPI." in job.text and "- Own services" in job.text


def test_plain_page_text_and_short_pages():
    body = "<p>" + "We are hiring a data engineer. " * 10 + "</p><script>var x = 1;</script>"
    job = parse_html(
        "https://acme.com/jobs/1", f"<html><title>Data Engineer</title><body>{body}</body></html>"
    )
    assert job.source == "html" and job.title == "Data Engineer" and "var x" not in job.text
    with pytest.raises(FetchError, match="Paste the job description"):
        parse_html("https://acme.com/jobs/2", "<html><body><div id=root></div></body></html>")


def test_html_to_text_keeps_structure():
    assert html_to_text(DESCRIPTION) == "Build APIs in Python & FastAPI.\n\n- Own services\n\n- Write tests"


def test_workday_links_map_to_the_json_endpoint():
    url = "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Senior-Engineer_JR123?source=x"
    assert workday_api_url(url) == (
        "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Senior-Engineer_JR123"
    )
    assert workday_api_url("https://acme.com/job/1") is None


def test_fetch_workday(monkeypatch):
    async def ok(_url):
        return None

    monkeypatch.setattr(fetch, "check_public_url", ok)
    payload = {
        "jobPostingInfo": {
            "title": "SDE I",
            "jobDescription": DESCRIPTION,
            "location": "Bengaluru",
            "jobReqId": "JR9",
        },
        "hiringOrganization": {"name": "Acme Corp", "url": ""},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.startswith("/wday/cxs/acme/External/job/")
        return httpx.Response(200, json=payload)

    url = "https://acme.wd3.myworkdayjobs.com/External/job/Bengaluru/SDE-I_JR9"
    job = asyncio.run(fetch.fetch_job(url, transport=httpx.MockTransport(handler)))
    assert job.source == "workday" and job.title == "SDE I" and "Job id: JR9" in job.text


def test_redirects_are_checked_each_hop(monkeypatch):
    checked = []

    async def check(url):
        checked.append(url)
        if "169.254" in url:
            raise FetchError("not public")

    monkeypatch.setattr(fetch, "check_public_url", check)

    def handler(request):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    with pytest.raises(FetchError, match="not public"):
        asyncio.run(fetch.fetch_job("https://acme.com/jobs/1", transport=httpx.MockTransport(handler)))
    assert len(checked) == 2


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/x",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "ftp://acme.com/",
        "http://u:p@acme.com/",
    ],
)
def test_private_and_odd_urls_are_refused(url):
    with pytest.raises(FetchError):
        asyncio.run(check_public_url(url))


def test_company_domain_guessing():
    assert normalize_domain("https://careers.acme.co.in/jobs/1") == "acme.co.in"
    assert normalize_domain("www.acme.com") == "acme.com"
    assert normalize_domain("https://acme.wd5.myworkdayjobs.com/x") == ""
    assert normalize_domain("https://jobs.lever.co/acme/1") == ""
    assert guess_company_domain("", "https://boards.greenhouse.io/x", "https://www.acme.io") == "acme.io"
