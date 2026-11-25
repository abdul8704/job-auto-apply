"""Fetch a job posting from a link and turn it into plain text.

Order of attempts:
1. Workday (`*.myworkdayjobs.com`): pages are rendered by JavaScript, so call Workday's public JSON
   endpoint for the posting instead.
2. Any page with schema.org JobPosting JSON-LD (most career sites and ATSs embed it for Google Jobs).
3. Otherwise, the page's visible text.

Links come from users, so every hop is checked against private and internal addresses (SSRF).
"""

import asyncio
import ipaddress
import json
import re
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from app.settings import get_settings

USER_AGENT = "Mozilla/5.0 (compatible; job-auto-apply/0.1; personal job search assistant)"
MAX_REDIRECTS = 5

# Hosts that belong to job boards and applicant tracking systems, not to the employer.
ATS_HOSTS = (
    "myworkdayjobs.com",
    "myworkdaysite.com",
    "workday.com",
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "smartrecruiters.com",
    "icims.com",
    "workable.com",
    "jobvite.com",
    "taleo.net",
    "successfactors.com",
    "successfactors.eu",
    "bamboohr.com",
    "recruitee.com",
    "breezy.hr",
    "zohorecruit.com",
    "zohorecruit.in",
    "keka.com",
    "darwinbox.in",
    "darwinbox.com",
    "freshteam.com",
    "naukri.com",
    "foundit.in",
    "instahyre.com",
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
    "glassdoor.co.in",
    "wellfound.com",
    "angel.co",
    "cutshort.io",
    "hirist.tech",
    "iimjobs.com",
    "internshala.com",
    "google.com",
)
_SUBDOMAIN_PREFIXES = ("www.", "careers.", "career.", "jobs.", "job.", "apply.", "hiring.", "talent.")


class FetchError(ValueError):
    pass


@dataclass
class FetchedJob:
    url: str
    source: str  # workday | jsonld | html
    text: str
    title: str = ""
    company: str = ""
    company_website: str = ""
    hints: dict = field(default_factory=dict)


# --- URL safety ---------------------------------------------------------------------------------


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return addr.is_global and not addr.is_multicast


async def check_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("Only http(s) links can be fetched")
    if parts.username or parts.password:
        raise FetchError("Links with credentials are not allowed")
    host = parts.hostname
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, parts.port or 443)
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve {host}") from exc
    if not infos or not all(_is_public_ip(info[4][0]) for info in infos):
        raise FetchError(f"{host} is not a public address")


async def _get(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """GET with manual redirects so every hop passes the public-address check."""
    s = get_settings()
    for _ in range(MAX_REDIRECTS + 1):
        await check_public_url(url)
        resp = await client.get(url, follow_redirects=False, **kwargs)
        if resp.is_redirect and "location" in resp.headers:
            url = urljoin(url, resp.headers["location"])
            continue
        if resp.status_code >= 400:
            raise FetchError(f"{urlsplit(url).hostname} answered {resp.status_code}")
        if len(resp.content) > s.job_fetch_max_bytes:
            raise FetchError("The page is too large")
        return resp
    raise FetchError("Too many redirects")


# --- HTML to text -------------------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "template", "iframe"}
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.jsonld: list[str] = []
        self._skip = 0
        self._in_jsonld = False
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "script" and ("type", "application/ld+json") in [(k, (v or "").lower()) for k, v in attrs]:
            self._in_jsonld = True
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self._skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "script":
            self._in_jsonld = False
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_jsonld:
            self.jsonld.append(data)
        elif self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        return clean_text("".join(self.parts))


def clean_text(text: str) -> str:
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    return p.text()


def _find_job_posting(node) -> dict | None:
    if isinstance(node, list):
        for item in node:
            if found := _find_job_posting(item):
                return found
    elif isinstance(node, dict):
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if "JobPosting" in types:
            return node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node and (found := _find_job_posting(node[key])):
                return found
    return None


def _first(value) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        return str(value.get("name") or value.get("@id") or "")
    return str(value or "")


def _jsonld_location(posting: dict) -> str:
    loc = posting.get("jobLocation")
    loc = loc[0] if isinstance(loc, list) and loc else loc
    if isinstance(loc, dict):
        addr = loc.get("address") or {}
        if isinstance(addr, dict):
            bits = [
                addr.get("addressLocality"),
                addr.get("addressRegion"),
                _first(addr.get("addressCountry")),
            ]
            return ", ".join(str(b) for b in bits if b)
    return ""


def parse_html(url: str, html: str) -> FetchedJob:
    p = _TextExtractor()
    p.feed(html)
    for block in p.jsonld:
        try:
            posting = _find_job_posting(json.loads(block))
        except json.JSONDecodeError:
            continue
        if posting:
            org = posting.get("hiringOrganization") or {}
            org = org if isinstance(org, dict) else {"name": str(org)}
            title = _first(posting.get("title"))
            company = _first(org.get("name"))
            body = html_to_text(str(posting.get("description") or ""))
            header = "\n".join(
                f"{k}: {v}"
                for k, v in [("Title", title), ("Company", company), ("Location", _jsonld_location(posting))]
                if v
            )
            return FetchedJob(
                url=url,
                source="jsonld",
                text=f"{header}\n\n{body}".strip(),
                title=title,
                company=company,
                company_website=_first(org.get("sameAs") or org.get("url")),
            )
    text = p.text()
    if len(text) < 200:
        raise FetchError(
            "Couldn't read the posting from that page (it may need JavaScript or a login). "
            "Paste the job description text instead."
        )
    return FetchedJob(url=url, source="html", text=text, title=clean_text(p.title))


# --- Workday --------------------------------------------------------------------------------------

_WORKDAY_RE = re.compile(
    r"^https?://(?P<host>(?P<tenant>[\w-]+)\.wd\d+\.myworkday(?:jobs|site)\.com)"
    r"(?:/[a-z]{2}-[A-Z]{2})?/(?P<site>[^/]+)/(?:details/|job/)(?P<path>.+?)/?(?:\?.*)?$"
)


def workday_api_url(url: str) -> str | None:
    m = _WORKDAY_RE.match(url)
    if not m:
        return None
    # Both .../job/<location>/<slug> and .../details/<slug> links map to the cxs job endpoint.
    return f"https://{m['host']}/wday/cxs/{m['tenant']}/{m['site']}/job/{m['path']}"


def parse_workday(url: str, data: dict) -> FetchedJob:
    info = data.get("jobPostingInfo") or {}
    org = data.get("hiringOrganization") or {}
    title = info.get("title", "")
    company = org.get("name", "")
    header = "\n".join(
        f"{k}: {v}"
        for k, v in [
            ("Title", title),
            ("Company", company),
            ("Location", info.get("location", "")),
            ("Job id", info.get("jobReqId", "")),
            ("Type", info.get("timeType", "")),
        ]
        if v
    )
    body = html_to_text(info.get("jobDescription", ""))
    return FetchedJob(
        url=url,
        source="workday",
        text=f"{header}\n\n{body}".strip(),
        title=title,
        company=company,
        company_website=org.get("url", ""),
    )


async def fetch_job(url: str, transport: httpx.AsyncBaseTransport | None = None) -> FetchedJob:
    s = get_settings()
    async with httpx.AsyncClient(
        timeout=s.job_fetch_timeout_seconds,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"},
        transport=transport,
    ) as client:
        if api := workday_api_url(url):
            try:
                resp = await _get(client, api, headers={"Accept": "application/json"})
                return parse_workday(url, resp.json())
            except (FetchError, ValueError):
                pass  # fall back to the HTML page
        resp = await _get(client, url, headers={"Accept": "text/html,application/xhtml+xml"})
        return parse_html(str(resp.url), resp.text)


# --- company domain -----------------------------------------------------------------------------


def _host(value: str) -> str:
    value = value.strip().lower()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    return (urlsplit(value).hostname or "").rstrip(".")


def is_ats_host(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in ATS_HOSTS)


def normalize_domain(value: str) -> str:
    """'https://careers.acme.com/jobs' -> 'acme.com'. Returns '' for job boards and ATS hosts."""
    host = _host(value)
    if not host or "." not in host or is_ats_host(host):
        return ""
    try:
        ipaddress.ip_address(host)
        return ""
    except ValueError:
        pass
    for prefix in _SUBDOMAIN_PREFIXES:
        if host.startswith(prefix) and host.count(".") >= 2:
            host = host[len(prefix) :]
    return host


def guess_company_domain(*candidates: str) -> str:
    for c in candidates:
        if c and (d := normalize_domain(c)):
            return d
    return ""
