"""Loads your profile.yaml. Everything personal lives there and in resume.yaml, never in code."""
import os
import sys
from pathlib import Path

import yaml

HOME = Path(os.environ.get("HUNTLINE_HOME", Path.cwd()))

DEFAULTS = {
    "search": {"keywords": [], "include": [], "exclude": [], "countries": ["remote"],
               "needs_sponsorship": False, "min_salary": 0, "max_age_days": 30,
               "years_experience": None, "years_slack": 2},
    "sources": ["ats", "remoteok", "himalayas", "wwr", "jobbank", "arbeitnow", "remotive", "jobicy", "hn",
                "adzuna", "reed"],
    "boards": {},
    "letter": {"greeting": "Dear Hiring Team,", "signoff": "Kind regards,"},
    "notify": {"min_score": 0, "top": 5},
}


def load(home=None):
    home = Path(home or HOME)
    f = home / "profile.yaml"
    if not f.exists():
        sys.exit(f"No profile.yaml in {home}. Run: huntline init")
    p = yaml.safe_load(f.read_text()) or {}
    for k, v in DEFAULTS.items():
        if isinstance(v, dict):
            p[k] = {**v, **(p.get(k) or {})}
        else:
            p.setdefault(k, v)
    s = p["search"]
    for k in ("keywords", "include", "exclude", "countries"):
        s[k] = as_list(s.get(k))
    p["sources"] = as_list(p.get("sources"))
    s["countries"] = [c.lower() for c in s["countries"]]
    from .countries import COUNTRIES
    bad = [c for c in s["countries"] if c not in COUNTRIES]
    if bad:
        sys.exit(f"profile.yaml: unknown countries {bad}; choose from {', '.join(COUNTRIES)}")
    for k in ("max_age_days", "years_experience", "years_slack"):
        if s.get(k) is not None and not isinstance(s[k], (int, float)):
            sys.exit(f"profile.yaml: search.{k} should be a number, not {s[k]!r}")
    if not s["include"]:
        s["include"] = [w for kw in s["keywords"] for w in kw.lower().split() if len(w) > 2]
    p["_home"] = str(home)
    (home / "out").mkdir(exist_ok=True)
    if p["search"]["max_age_days"] is None:
        p["search"]["max_age_days"] = 3650
    return p


def as_list(v):
    """`countries: canada, uk` and `countries: [canada, uk]` both mean a list."""
    if v is None:
        return []
    if isinstance(v, str):
        v = v.split(",")
    return [str(x).strip() for x in v if str(x).strip()]


def load_resume(p):
    f = Path(p["_home"]) / "resume.yaml"
    if not f.exists():
        sys.exit(f"No resume.yaml in {p['_home']}. Run: huntline init")
    return yaml.safe_load(f.read_text())
