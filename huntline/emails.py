"""Finds a public contact address for an employer, without any paid service.

Order: an address printed in the posting itself, then the company website's contact,
careers and about pages. A guessed info@ is only offered when the domain accepts mail,
and it is always labelled as a guess.
"""
import re
import socket
from urllib.parse import urlparse

from .sources import get, text_of

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HIRING = ("hr", "careers", "career", "jobs", "job", "hiring", "recruit", "people", "talent", "cv", "resume")
GENERAL = ("info", "hello", "contact", "office", "enquir", "inquir", "admin", "mail")
# Mailboxes that never forward an application to anyone who can act on it.
BAD = ("pr", "press", "media", "investor", "ir", "billing", "invoice", "accounts", "support", "help",
       "security", "webmaster", "postmaster", "privacy", "abuse", "legal", "dmca", "noreply", "no-reply")
JUNK = (".png", ".jpg", ".gif", ".webp", "example", "sentry", "wixpress", "@2x", "domain.com", "yourdomain", "test@")
BOARD_HOSTS = ("greenhouse", "lever.co", "ashbyhq", "smartrecruiters", "workable", "recruitee", "indeed", "linkedin",
               "glassdoor", "jobbank", "adzuna", "reed.co", "remoteok", "himalayas", "weworkremotely", "google")


def pick(text, domain=""):
    found = []
    for e in {e.lower().strip(".") for e in EMAIL_RE.findall(text or "")}:
        box = e.split("@")[0]
        if any(j in e for j in JUNK) or any(box == b or box.startswith(b + ".") for b in BAD):
            continue
        tier = 0 if box.startswith(HIRING) else 1 if box.startswith(GENERAL) else 2
        same = 0 if domain and domain.split(".")[0] in e.split("@")[1] else 1
        found.append(((same, tier, len(e)), e))
    return sorted(found)[0][1] if found else ""


def has_mx(domain):
    try:
        import dns.resolver
        return bool(dns.resolver.resolve(domain, "MX", lifetime=5))
    except ImportError:
        try:
            socket.getaddrinfo(domain, 25)
            return True
        except OSError:
            return False
    except Exception:
        return False


def company_domain(job):
    """The employer's own domain, if the job URL is not a job board."""
    host = urlparse(job.get("url") or "").netloc.lower().removeprefix("www.")
    if host and not any(b in host for b in BOARD_HOSTS):
        return host
    slug = re.sub(r"[^a-z0-9]", "", (job.get("company") or "").lower())
    for tld in (".com", ".io", ".co", ".ca", ".co.uk", ".nl"):
        if slug and has_mx(slug + tld):
            return slug + tld
    return ""


def find(job):
    e = pick(job.get("desc", ""))
    if e:
        return e
    dom = company_domain(job)
    if not dom:
        return ""
    for path in ("", "/contact", "/contact-us", "/careers", "/jobs", "/about"):
        r = get(f"https://{dom}{path}", tries=1)
        if r:
            e = pick(r.text + " " + text_of(r.text), dom)
            if e:
                return e
    return f"info@{dom} (guess)" if has_mx(dom) else ""
