"""The daily run: fetch every source, keep what fits you, rank it, save it, write the report."""
import re
import sys

from . import emails, report
from .countries import COUNTRIES, NEG_ANY, POS_ANY, country_of
from .sources import SOURCES, jobbank_detail, log
from .sponsors import Sponsors, norm_co
from .store import connect, job_id, today

# Aggregators relist other companies' jobs, so the "employer" is meaningless.
AGGREGATORS = {"jobgether", "jobleads", "talent com", "ziprecruiter", "lensa", "jooble", "neuvoo", "whatjobs",
               "jobrapido", "adzuna", "indeed", "glassdoor", "linkedin", "simplyhired", "randstad", "robert half",
               "hays", "adecco", "manpower", "crossover", "turing", "toptal", "andela", "dataannotation"}


def words_re(words):
    return re.compile(r"\b(" + "|".join(re.escape(w.lower()) for w in words) + r")", re.I) if words else None


def min_salary(p, country):
    m = p["search"].get("min_salary") or 0
    return (m.get(country) or m.get("default") or 0) if isinstance(m, dict) else m


def evaluate(p, r, sponsors, inc, exc, kw):
    """Returns the scored row, or None to drop the job."""
    s = p["search"]
    r["title"], r["company"] = str(r.get("title") or "").strip(), str(r.get("company") or "").strip()
    if not r.get("url") or not r.get("title") or norm_co(r["company"]) in AGGREGATORS:
        return None
    if not inc.search(r["title"]) or (exc and exc.search(r["title"])):
        return None
    country = "canada" if r["source"] == "jobbank" else country_of(r["location"], s["countries"])
    if not country:
        return None
    if r["source"] == "jobbank" and not jobbank_detail(r):
        return None
    desc = r.get("desc") or ""
    tier, visa = 4, ""
    if s.get("needs_sponsorship"):
        cneg = COUNTRIES[country]["neg"]
        if not r.get("open") and (r.get("ghost") or re.search(NEG_ANY, desc, re.I) or re.search(cneg, desc, re.I)):
            return None
        if r.get("open"):
            tier, visa = 1, "Accepts applicants without a work permit" + (f", LMIA {r['lmia']}" if r.get("lmia") else "")
        elif re.search(POS_ANY, desc, re.I):
            tier, visa = 2, "Posting mentions sponsorship or relocation"
        elif (hit := sponsors.check(r["company"], country)):
            tier, visa = 3, hit[0].upper() + hit[1:]
    floor = min_salary(p, country)
    if r["hi"] and floor and float(r["hi"]) < floor * (0.8 if tier <= 2 else 1):
        return None

    title_hits = len(set(m.lower() for m in kw.findall(r["title"]))) if kw else 0
    inc_hits = len(set(m.lower() for m in inc.findall(r["title"])))
    desc_hits = len(set(m.lower() for m in kw.findall(desc))) if kw else 0
    score = min(35, 20 * title_hits) + min(15, 5 * inc_hits) + min(20, 4 * desc_hits)
    score += {1: 25, 2: 20, 3: 12}.get(tier, 0) if s.get("needs_sponsorship") else 20
    score += 5 if r["hi"] else 0
    return {"id": job_id(r["company"], r["title"]), "found": today(), "title": r["title"][:140],
            "company": r["company"][:80], "location": r["location"][:80], "country": country, "url": r["url"],
            "source": r["source"], "salary_lo": r["lo"], "salary_hi": r["hi"], "score": min(score, 100),
            "tier": tier, "visa": visa, "note": r.get("note", ""), "email": "", "desc": desc[:6000]}


def run(p, only=None, find_emails=20):
    db = connect(p["_home"])
    s = p["search"]
    if not s["keywords"]:
        sys.exit("profile.yaml: search.keywords is empty")
    inc, exc, kw = words_re(s["include"]), words_re(s["exclude"]), words_re(s["keywords"])
    sponsors = Sponsors(p["_home"], s["countries"]) if s.get("needs_sponsorship") else Sponsors(p["_home"], [])

    raw, counts = [], {}
    for name in only or p["sources"]:
        if name not in SOURCES:
            log(f"unknown source {name!r}; choose from {', '.join(SOURCES)}")
            continue
        log(f"fetching {name} ...")
        try:
            got = SOURCES[name](p)
        except Exception as e:
            log(f"  [{name}] failed: {type(e).__name__}: {e}")
            got = []
        counts[name] = len(got)
        raw += got
        log(f"  {name}: {len(got)} postings")

    # A source that quietly drops to zero while still answering is the classic silent failure.
    prev = {r["source"]: r["best"] for r in db.execute("SELECT * FROM source_yield")}
    for name, n in counts.items():
        if n == 0 and prev.get(name, 0) >= 20:
            log(f"WARNING: {name} returned 0 today but has returned {prev[name]} before. It may be broken or blocking you.")
        if n:
            db.execute("INSERT INTO source_yield VALUES (?,?,?) ON CONFLICT(source) DO UPDATE SET "
                       "best=max(best, excluded.best), ts=excluded.ts", (name, n, today()))

    known = {r["id"] for r in db.execute("SELECT id FROM jobs")}
    fresh = {}
    for r in sorted(raw, key=lambda r: r["source"] != "jobbank"):   # Job Bank records are richest, let them win
        jid = job_id(r["company"], r["title"])
        if jid in known or jid in fresh:
            continue
        row = evaluate(p, r, sponsors, inc, exc, kw)
        if row:
            fresh[jid] = row

    ranked = sorted(fresh.values(), key=lambda x: -x["score"])
    for row in ranked[:find_emails]:
        row["email"] = emails.find(row)

    cols = list(ranked[0]) if ranked else []
    for row in ranked:
        db.execute(f"INSERT OR IGNORE INTO jobs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                   [row[c] for c in cols])
    db.commit()
    out = report.write(p, db)
    log(f"\n{len(ranked)} new matching jobs from {len(raw)} postings.")
    log(f"Open your list: {out}")
    return ranked
