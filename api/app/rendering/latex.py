"""Render a Profile into LaTeX through Jinja templates.

Everything printed from the profile is LaTeX-escaped automatically (Environment.finalize), so
profile text can never inject commands such as \\write18 or \\input.
"""

import re
from importlib import resources

from jinja2 import BaseLoader, Environment, StrictUndefined, TemplateNotFound

from app.profile.schema import Profile

_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
}
_ESCAPE_RE = re.compile("|".join(re.escape(k) for k in _ESCAPES))


class Raw(str):
    """A string that is already valid LaTeX and must not be escaped again."""


def latex_escape(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Raw):
        return value
    return Raw(_ESCAPE_RE.sub(lambda m: _ESCAPES[m.group()], str(value)))


def latex_url(value: str) -> Raw:
    """For \\href{...}: only allow http(s)/mailto links, and escape the characters LaTeX cares about."""
    url = str(value).strip()
    if not re.match(r"^(https?://|mailto:)", url):
        url = "https://" + url if url else ""
    url = re.sub(r"[\s{}\\]", "", url)
    return Raw(url.replace("%", r"\%").replace("#", r"\#").replace("~", r"\~"))


def display_url(value: str) -> str:
    return re.sub(r"^(https?://)?(www\.)?", "", str(value)).rstrip("/")


class _PackageLoader(BaseLoader):
    def get_source(self, environment, template):
        path = resources.files("app.rendering.templates").joinpath(template)
        if not path.is_file():
            raise TemplateNotFound(template)
        return path.read_text(), template, lambda: True


def make_env() -> Environment:
    env = Environment(
        loader=_PackageLoader(),
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="(((",
        variable_end_string=")))",
        comment_start_string="((=",
        comment_end_string="=))",
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
        finalize=latex_escape,
        autoescape=False,
    )
    env.filters["url"] = latex_url
    env.filters["display_url"] = display_url
    env.globals["latex_escape"] = latex_escape
    env.globals["raw"] = Raw
    return env


TEMPLATES = {"classic": "classic.tex.j2"}


def render_latex(profile: Profile, template: str = "classic") -> str:
    if template not in TEMPLATES:
        raise ValueError(f"unknown template {template!r}; choose from {sorted(TEMPLATES)}")
    return make_env().get_template(TEMPLATES[template]).render(p=profile)
