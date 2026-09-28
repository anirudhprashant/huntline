"""Finds a public contact address for an employer, without any paid service.

Order: an address printed in the posting itself, then the company website's contact,
careers and about pages. A guessed info@ is only offered when the domain accepts mail,
and it is always labelled as a guess.
"""
import os
import re
import socket
import time
from urllib.parse import urlparse

import requests

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


_last_brave = [0.0]


def brave_domain(company, location=""):
    """Look up the employer's website with Brave Search (free key, optional)."""
    key = os.environ.get("BRAVE_API_KEY")
    if not key or not company:
        return ""
    wait = 1.1 - (time.time() - _last_brave[0])     # the free plan allows 1 request a second
    if wait > 0:
        time.sleep(wait)
    _last_brave[0] = time.time()
    try:
        r = requests.get("https://api.search.brave.com/res/v1/web/search", timeout=20,
                         headers={"X-Subscription-Token": key, "Accept": "application/json"},
                         params={"q": f"{company} {location.split(',')[0]} official website", "count": 5})
        for hit in (r.json().get("web") or {}).get("results", []) if r.ok else []:
            host = urlparse(hit.get("url", "")).netloc.lower().removeprefix("www.")
            if host and not any(b in host for b in BOARD_HOSTS + SOCIAL):
                return host
    except (requests.RequestException, ValueError):
        pass
    return ""


def fetch_page(url):
    """Page text for email hunting. Uses your Firecrawl (renders JavaScript) when configured."""
    fc = os.environ.get("FIRECRAWL_URL")
    if fc:
        try:
            headers = {"Authorization": f"Bearer {os.environ['FIRECRAWL_API_KEY']}"} if os.environ.get("FIRECRAWL_API_KEY") else {}
            r = requests.post(f"{fc.rstrip('/')}/v1/scrape", headers=headers, timeout=90,
                              json={"url": url, "formats": ["markdown", "rawHtml"], "onlyMainContent": False})
            d = (r.json().get("data") or {}) if r.ok else {}
            if d:
                return (d.get("markdown") or "") + " " + (d.get("rawHtml") or "")
        except (requests.RequestException, ValueError):
            pass
    r = get(url, tries=1)
    return (r.text + " " + text_of(r.text)) if r else ""


SOCIAL = ("facebook", "instagram", "twitter", "x.com", "youtube", "wikipedia", "crunchbase", "bloomberg",
          "zoominfo", "yelp", "bbb.org", "tiktok")


def company_domain(job):
    """The employer's own domain, if the job URL is not a job board."""
    host = urlparse(job.get("url") or "").netloc.lower().removeprefix("www.")
    if host and not any(b in host for b in BOARD_HOSTS):
        return host
    found = brave_domain(job.get("company", ""), job.get("location", ""))
    if found:
        return found
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
        e = pick(fetch_page(f"https://{dom}{path}"), dom)
        if e:
            return e
    return f"info@{dom} (guess)" if has_mx(dom) else ""
