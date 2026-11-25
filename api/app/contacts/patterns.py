"""Guess a person's work email from their name and the company domain.

Uses the company's known pattern when a provider (e.g. Hunter) reported one; otherwise the most
common corporate formats, most likely first. Guesses are labelled `guessed` until verified.
"""

import asyncio
import re
import unicodedata

# Ordered by how common they are at companies, roughly.
COMMON_PATTERNS = [
    "{first}.{last}",
    "{first}",
    "{f}{last}",
    "{first}{last}",
    "{first}_{last}",
    "{f}.{last}",
    "{first}{l}",
    "{last}.{first}",
    "{last}{f}",
    "{last}",
]
_PATTERN_RE = re.compile(r"^(\{(first|last|f|l)\}|[._-])+$")


def _ascii(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", value.lower())


def split_name(full_name: str) -> tuple[str, str]:
    parts = [p for p in re.split(r"\s+", full_name.strip()) if p]
    parts = [p for p in parts if p.rstrip(".").lower() not in {"mr", "ms", "mrs", "dr", "prof"}]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


def valid_pattern(pattern: str) -> bool:
    return bool(pattern) and bool(_PATTERN_RE.match(pattern))


def apply_pattern(pattern: str, first: str, last: str, domain: str) -> str | None:
    f, la = _ascii(first), _ascii(last)
    if not f or not domain or not valid_pattern(pattern):
        return None
    if ("{last}" in pattern or "{l}" in pattern) and not la:
        return None
    local = pattern.replace("{first}", f).replace("{last}", la).replace("{f}", f[:1]).replace("{l}", la[:1])
    return f"{local}@{domain.lower()}"


def guess_emails(first: str, last: str, domain: str, known_pattern: str = "", limit: int = 4) -> list[str]:
    patterns = [known_pattern] if valid_pattern(known_pattern) else COMMON_PATTERNS
    out: list[str] = []
    for p in patterns:
        email = apply_pattern(p, first, last, domain)
        if email and email not in out:
            out.append(email)
    return out[:limit]


async def domain_accepts_mail(domain: str) -> bool | None:
    """True if the domain has MX records, False if it clearly has none, None if DNS couldn't tell."""
    try:
        import dns.asyncresolver
        import dns.exception
        import dns.resolver
    except ImportError:
        return None
    try:
        answer = await asyncio.wait_for(dns.asyncresolver.resolve(domain, "MX"), timeout=8)
        return len(answer) > 0
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return False
    except (dns.exception.DNSException, TimeoutError, OSError):
        return None
