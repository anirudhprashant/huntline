"""Job sources. Each returns a list of plain dicts:

    title, company, location, url, desc, lo, hi, source, posted, (optional) open, lmia, note, detail

lo/hi are yearly salary in the posting's currency, or None. posted is YYYY-MM-DD or ''.
detail is an API URL holding the full description, fetched only for jobs that pass the
title and location filters, so boards that list without descriptions stay cheap. No source needs a paid key;
Adzuna and Reed are used only when their free keys are set in the environment.
"""
import concurrent.futures as cf
import datetime
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from .store import iso_date

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36",
      "Accept-Language": "en;q=0.9"}


def log(msg):
    print(msg, file=sys.stderr)


def get(url, tries=3, **kw):
    """GET with backoff. Several boards reject bursts, so be polite."""
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=45, **kw)
            if r.ok:
                return r
            if r.status_code in (404, 410):
                return None
        except requests.RequestException as e:
            log(f"  [get] {type(e).__name__} {url[:80]}")
        if i < tries - 1:
            time.sleep(3 * (i + 1))
    return None


def text_of(s):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s or "", flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def yearly(lo, hi, interval="year"):
    mult = {"hour": 2080, "day": 260, "week": 52, "month": 12, "year": 1, "annual": 1}
    m = next((v for k, v in mult.items() if k in (interval or "year").lower()), 1)
    vals = []
    for x in (lo, hi):
        try:
            if x not in (None, "") and float(x) > 0:
                vals.append(float(x) * m)
        except (TypeError, ValueError):
            pass
    return (min(vals), max(vals)) if vals else (None, None)


def rec(**kw):
    base = {"title": "", "company": "", "location": "", "url": "", "desc": "", "lo": None, "hi": None, "source": "",
            "posted": ""}
    base.update(kw)
    base["posted"] = iso_date(base["posted"])
    return base


# ---------- remote boards (no key) ----------

def remoteok(p):
    r = get("https://remoteok.com/api")
    out = []
    for j in (r.json() if r else []):
        if isinstance(j, dict) and j.get("position"):
            out.append(rec(title=j["position"], company=j.get("company", ""), location=j.get("location") or "Remote",
                           url=j.get("url", ""), desc=text_of(j.get("description", "")),
                           lo=j.get("salary_min") or None, hi=j.get("salary_max") or None, source="remoteok",
                           posted=j.get("epoch") or j.get("date")))
    return out


def himalayas(p, pages=5):
    out, offset = [], 0
    for _ in range(pages):
        r = get(f"https://himalayas.app/jobs/api?limit=100&offset={offset}")
        jobs = (r.json().get("jobs") if r else None) or []
        for j in jobs:
            out.append(rec(title=j.get("title", ""), company=j.get("companyName", ""),
                           location=", ".join(j.get("locationRestrictions") or []) or "Remote",
                           url=j.get("applicationLink", ""), desc=text_of(j.get("description") or j.get("excerpt", "")),
                           lo=j.get("minSalary"), hi=j.get("maxSalary"), source="himalayas", posted=j.get("pubDate")))
        if len(jobs) < 100:
            break
        offset += 100
        time.sleep(0.5)
    return out


def wwr(p):
    r = get("https://weworkremotely.com/remote-jobs.rss")
    out = []
    if not r:
        return out
    for item in ET.fromstring(r.content).iter("item"):
        t = lambda tag: (item.findtext(tag) or "").strip()
        company, _, role = t("title").partition(":")
        out.append(rec(title=role.strip() or t("title"), company=company.strip(), location=t("region") or "Remote",
                       url=t("link"), desc=text_of(t("description")), source="wwr", posted=t("pubDate")))
    return out


# ---------- employer ATS boards (no key; the best source) ----------

ATS_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{s}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{s}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{s}?includeCompensation=true",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=100",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{s}?details=true",
    "recruitee": "https://{s}.recruitee.com/api/offers/",
}


def board(ats, slug):
    """All postings on one employer's board, normalised."""
    r = get(ATS_URLS[ats].format(s=slug), tries=2)
    if not r:
        return []
    try:
        data = r.json()
    except ValueError:
        return []
    co, out = slug.replace("-", " ").title(), []
    if ats == "greenhouse":
        for j in data.get("jobs", []):
            out.append(rec(title=j.get("title", ""), company=j.get("company_name") or co,
                           location=(j.get("location") or {}).get("name", ""), url=j.get("absolute_url"),
                           desc=text_of(html.unescape(j.get("content") or "")),
                           posted=j.get("first_published") or j.get("updated_at")))
    elif ats == "lever":
        for j in data if isinstance(data, list) else []:
            c, sr = j.get("categories") or {}, j.get("salaryRange") or {}
            lo, hi = yearly(sr.get("min"), sr.get("max"), sr.get("interval"))
            out.append(rec(title=j.get("text", ""), company=co,
                           location=" / ".join(c.get("allLocations") or [c.get("location") or ""]),
                           url=j.get("hostedUrl"), desc=j.get("descriptionPlain") or "", lo=lo, hi=hi,
                           posted=j.get("createdAt")))
    elif ats == "ashby":
        for j in data.get("jobs", []):
            comp = ((j.get("compensation") or {}).get("compensationTierSummary") or "")
            nums = [float(a.replace(",", "")) * (1000 if k.upper() == "K" else 1)
                    for a, k in re.findall(r"[$€£]\s?([\d,.]+)\s*([Kk]?)", comp)]
            locs = [j.get("location") or ""] + [x.get("location", "") for x in j.get("secondaryLocations") or []]
            out.append(rec(title=j.get("title", ""), company=co, location=" / ".join(l for l in locs if l),
                           url=j.get("jobUrl"), desc=j.get("descriptionPlain") or "",
                           lo=min(nums) if nums else None, hi=max(nums) if nums else None,
                           posted=j.get("publishedAt")))
    elif ats == "smartrecruiters":
        for j in data.get("content", []):
            loc = j.get("location") or {}
            out.append(rec(title=j.get("name", ""), company=co,
                           location=" ".join(str(loc.get(k) or "") for k in ("city", "region", "country")),
                           url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}", posted=j.get("releasedDate"),
                           detail=f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{j.get('id')}"))
    elif ats == "workable":
        for j in data.get("jobs", []):
            out.append(rec(title=j.get("title", ""), company=co,
                           location=" ".join(str(j.get(k) or "") for k in ("city", "state", "country")),
                           url=j.get("url") or j.get("application_url"), desc=text_of(j.get("description") or ""),
                           posted=j.get("published_on") or j.get("created_at")))
    else:
        for j in data.get("offers", []):
            out.append(rec(title=j.get("title", ""), company=co,
                           location=" ".join(str(j.get(k) or "") for k in ("city", "state_name", "country_name")),
                           url=j.get("careers_url") or j.get("url"), desc=text_of(j.get("description") or ""),
                           posted=j.get("published_at") or j.get("created_at")))
    for o in out:
        o["source"] = ats
    return out


def load_boards(p):
    """Boards from the bundled list plus any found by `huntline boards`."""
    boards = {}
    for f in (Path(__file__).parent / "data" / "boards.json", Path(p["_home"]) / "boards.json"):
        if f.exists():
            for ats, slugs in json.loads(f.read_text()).get("boards", {}).items():
                boards.setdefault(ats, set()).update(slugs)
    for ats, slugs in (p.get("boards") or {}).items():
        boards.setdefault(ats, set()).update(slugs)
    return boards


def ats(p):
    pairs = [(a, s) for a, slugs in load_boards(p).items() if a in ATS_URLS for s in sorted(slugs)]
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        return [r for rs in ex.map(lambda x: board(*x), pairs) for r in rs]


# ---------- Canada Job Bank (no key) ----------

JB = "https://www.jobbank.gc.ca"


# Immigration consultancies flood the foreign-worker streams and are rarely the real employer.
CONSULTANCY = re.compile(r"immigration|visa consult|migration serv", re.I)


def _jobbank_list(query, pages, max_age, fsrc=16):
    out, cutoff = [], datetime.date.today() - datetime.timedelta(days=max_age)
    for pg in range(1, pages + 1):
        r = get(f"{JB}/jobsearch/jobsearch?{query}&sort=D&fsrc={fsrc}&page={pg}")
        blocks = re.split(r'<article id="article-', r.text)[1:] if r else []
        if not blocks:
            break
        old = False
        for b in blocks:
            jid = b.split('"', 1)[0]
            f = lambda cls: text_of(m.group(1)) if (m := re.search(rf'class="{cls}">(.*?)</(?:li|h3)>', b, re.S)) else ""
            try:
                posted = datetime.datetime.strptime(f("date").strip(), "%B %d, %Y").date()
            except ValueError:
                posted = datetime.date.today()
            if posted < cutoff:
                old = True
                continue
            if CONSULTANCY.search(f("business")):
                continue
            sal = f("salary").replace("Salary", "").strip()
            nums = [x.replace(",", "") for x in re.findall(r"\$([\d,]+(?:\.\d+)?)", sal)]
            lo, hi = yearly(nums[0] if nums else None, nums[-1] if nums else None, sal)
            direct = "Direct Apply" in f("appmethod")
            out.append(rec(title=f("noctitle"), company=f("business"), location=f("location").replace("Location", "").strip(),
                           url=f"{JB}/jobsearch/jobposting/{jid}", lo=lo, hi=hi, source="jobbank", posted=posted.isoformat(),
                           note="Direct Apply needs a Job Bank account; try the employer's site or email" if direct else ""))
        if old:
            break
        time.sleep(1.5)
    return out


def jobbank_detail(r):
    """Open one posting. False = drop it. Marks postings that accept foreign applicants."""
    page = get(r["url"])
    if not page:
        return True
    t = text_of(page.text)
    r["desc"] = t[:6000]
    # "If you are not authorized to work in Canada... the employer will not respond" is a ghost for visa seekers.
    if re.search(r"not authori[sz]ed to work in Canada\s*\.?\s*The employer will not respond", t):
        r["ghost"] = True
    until = re.search(r"Advertised until (\d{4}-\d{2}-\d{2})", t)
    if until and until.group(1) < datetime.date.today().isoformat():
        return False
    r["open"] = "with or without a valid Canadian work permit" in t
    lm = re.search(r"LMIA\)? (requested|approved)", t)
    r["lmia"] = lm.group(1) if lm else ""
    time.sleep(1.2)
    return True


def jobbank(p):
    if "canada" not in p["search"]["countries"]:
        return []
    age = p["search"].get("max_age_days", 30)
    out = []
    for kw in p["search"]["keywords"]:
        q = "searchstring=" + requests.utils.quote(kw)
        out += _jobbank_list(q, 3, age)
        if p["search"].get("needs_sponsorship"):
            out += _jobbank_list(q + "&fskl=101010", 2, age + 15)   # LMIA requested
            out += _jobbank_list(q + "&fskl=101020", 2, age + 15)   # LMIA approved
            out += _jobbank_list(q, 2, age + 15, fsrc=32)            # Temporary Foreign Workers stream
    return out


def fetch_detail(r):
    """Fill in the description for records that list without one (SmartRecruiters)."""
    page = get(r.pop("detail"), tries=2)
    try:
        sections = ((page.json().get("jobAd") or {}).get("sections") or {}) if page else {}
    except ValueError:
        sections = {}
    r["desc"] = text_of(" ".join(str((v or {}).get("text") or "") for v in sections.values()))


# ---------- more free boards (no key) ----------

def arbeitnow(p, pages=5):
    """Germany and the EU, many English-speaking roles and many that sponsor."""
    if not {"germany", "netherlands", "ireland", "uk", "remote"} & set(p["search"]["countries"]):
        return []
    out = []
    for pg in range(1, pages + 1):
        r = get(f"https://www.arbeitnow.com/api/job-board-api?page={pg}")
        try:
            jobs = (r.json().get("data") if r else None) or []
        except ValueError:
            jobs = []
        for j in jobs:
            loc = j.get("location") or ""
            if j.get("remote"):
                loc = f"{loc} (Remote)" if loc else "Remote"
            tags = " ".join(j.get("tags") or [])
            out.append(rec(title=j.get("title", ""), company=j.get("company_name", ""), location=loc,
                           url=j.get("url", ""), desc=f"{text_of(j.get('description', ''))} {tags}",
                           source="arbeitnow", posted=j.get("created_at")))
        if not jobs:
            break
        time.sleep(0.5)
    return out


def remotive(p):
    if "remote" not in p["search"]["countries"]:
        return []
    out = []
    for kw in p["search"]["keywords"]:
        r = get("https://remotive.com/api/remote-jobs", params={"search": kw, "limit": 100})
        try:
            jobs = (r.json().get("jobs") if r else None) or []
        except ValueError:
            jobs = []
        for j in jobs:
            out.append(rec(title=j.get("title", ""), company=j.get("company_name", ""),
                           location=f"{j.get('candidate_required_location') or ''} Remote".strip(),
                           url=j.get("url", ""), desc=text_of(j.get("description", "")), source="remotive",
                           posted=j.get("publication_date")))
        time.sleep(1)
    return out


def jobicy(p):
    if "remote" not in p["search"]["countries"]:
        return []
    out = []
    for kw in p["search"]["keywords"]:
        r = get("https://jobicy.com/api/v2/remote-jobs", params={"count": 50, "tag": kw})
        try:
            jobs = (r.json().get("jobs") if r else None) or []
        except ValueError:
            jobs = []
        for j in jobs:
            geo = j.get("jobGeo") or ""
            out.append(rec(title=html.unescape(j.get("jobTitle") or ""), company=html.unescape(j.get("companyName") or ""),
                           location=f"{'' if geo.lower() == 'anywhere' else geo} Remote".strip(), url=j.get("url", ""),
                           desc=text_of(j.get("jobDescription") or j.get("jobExcerpt") or ""), source="jobicy",
                           lo=j.get("annualSalaryMin"), hi=j.get("annualSalaryMax"), posted=j.get("pubDate")))
        time.sleep(1)
    return out


ROLE = re.compile(r"engineer|developer|manager|designer|scientist|analyst|lead|head of|director|architect|"
                  r"specialist|marketing|product|sales|writer|researcher|ops|operations|devops|sre|consultant", re.I)


def hn_post(text, item_id, created):
    """One "Company | Role | Location | ..." comment from the monthly Who's Hiring thread."""
    first = text_of((text or "").split("<p>")[0])
    parts = [x.strip() for x in first.split("|") if x.strip()]
    if len(parts) < 2 or len(first) > 300:
        return None
    title = next((x for x in parts[1:] if ROLE.search(x)), parts[1])
    return rec(title=title, company=parts[0], location=" ".join(parts[1:]),
               url=f"https://news.ycombinator.com/item?id={item_id}", desc=text_of(text), source="hn", posted=created)


def hn(p):
    """Hacker News "Who is hiring?" - startups posting directly, mostly tech."""
    r = get("https://hn.algolia.com/api/v1/search_by_date",
            params={"tags": "story,author_whoishiring", "query": "who is hiring", "hitsPerPage": 5})
    try:
        story = next((h for h in (r.json().get("hits") if r else []) if "hiring" in (h.get("title") or "").lower()), None)
        thread = get(f"https://hn.algolia.com/api/v1/items/{story['objectID']}").json() if story else {}
    except (ValueError, AttributeError):
        thread = {}
    out = []
    for c in thread.get("children") or []:
        job = hn_post(c.get("text"), c.get("id"), c.get("created_at"))
        if job:
            out.append(job)
    return out


# ---------- keyed but free ----------

def adzuna(p):
    from .countries import COUNTRIES
    app_id, key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and key):
        return []
    out = []
    for c in p["search"]["countries"]:
        code = COUNTRIES.get(c, {}).get("adzuna")
        if not code:
            continue
        for term in p["search"]["keywords"]:
            r = get(f"https://api.adzuna.com/v1/api/jobs/{code}/search/1",
                    params={"app_id": app_id, "app_key": key, "results_per_page": 50, "what": term,
                            "max_days_old": p["search"].get("max_age_days", 30)})
            for j in (r.json().get("results", []) if r else []):
                predicted = str(j.get("salary_is_predicted")) == "1"
                out.append(rec(title=j.get("title") or "", company=(j.get("company") or {}).get("display_name") or "",
                               location=(j.get("location") or {}).get("display_name") or "", url=j.get("redirect_url"),
                               desc=j.get("description") or "", source="adzuna", posted=j.get("created"),
                               lo=None if predicted else j.get("salary_min"), hi=None if predicted else j.get("salary_max")))
    return out


def reed(p):
    key = os.environ.get("REED_API_KEY")
    if not key or "uk" not in p["search"]["countries"]:
        return []
    out = []
    for term in p["search"]["keywords"]:
        try:
            r = requests.get("https://www.reed.co.uk/api/1.0/search", auth=(key, ""), headers=UA, timeout=45,
                             params={"keywords": term, "resultsToTake": 100})
            res = r.json().get("results", []) if r.ok else []
        except requests.RequestException:
            res = []
        for j in res:
            out.append(rec(title=j.get("jobTitle", ""), company=j.get("employerName", ""), location=j.get("locationName", ""),
                           url=j.get("jobUrl"), desc=j.get("jobDescription", ""), lo=j.get("minimumSalary"),
                           hi=j.get("maximumSalary"), source="reed",
                           posted="-".join(reversed(str(j.get("date") or "").split("/")))))
    return out


# ---------- JobSpy: Indeed, LinkedIn, Glassdoor, Google (optional install) ----------

def jobspy(p):
    try:
        from jobspy import scrape_jobs
    except ImportError:
        log("  [jobspy] not installed; run: pip install 'huntline[jobspy]'")
        return []
    from .countries import COUNTRIES
    out, hours = [], 24 * p["search"].get("max_age_days", 30)
    for c in p["search"]["countries"]:
        cc = COUNTRIES.get(c, {})
        for term in p["search"]["keywords"]:
            for site in ("indeed", "linkedin"):
                try:
                    df = scrape_jobs(site_name=[site], search_term=term, location=cc.get("jobspy_location") or "",
                                     country_indeed=cc.get("indeed") or "USA", is_remote=(c == "remote"),
                                     results_wanted=40, hours_old=hours, linkedin_fetch_description=True)
                except Exception as e:
                    log(f"  [jobspy {site}] {type(e).__name__}: {str(e)[:100]}")
                    continue
                for _, row in (df.iterrows() if df is not None else []):
                    g = lambda k: None if str(row.get(k)) in ("nan", "None", "NaT", "") else row.get(k)
                    lo, hi = yearly(g("min_amount"), g("max_amount"), g("interval"))
                    out.append(rec(title=str(g("title") or ""), company=str(g("company") or ""),
                                   location=str(g("location") or ""), url=g("job_url"), desc=str(g("description") or ""),
                                   lo=lo, hi=hi, source=site, posted=str(g("date_posted") or "")))
    return out


SOURCES = {"ats": ats, "remoteok": remoteok, "himalayas": himalayas, "wwr": wwr, "jobbank": jobbank,
           "arbeitnow": arbeitnow, "remotive": remotive, "jobicy": jobicy, "hn": hn,
           "adzuna": adzuna, "reed": reed, "jobspy": jobspy}
