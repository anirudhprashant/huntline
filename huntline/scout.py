"""The daily run: fetch every source, keep what fits you, rank it, save it, write the report."""
import concurrent.futures as cf
import re
import sys
from pathlib import Path

import yaml

from . import emails, learn, notify, report
from .countries import COUNTRIES, NEG_ANY, POS_ANY, country_of
from .match import Fit, years_required
from .sources import FULL_BOARDS, SOURCES, fetch_detail, jobbank_detail, log
from .sponsors import Sponsors, norm_co
from .store import age_days, connect, job_id, today

# Aggregators relist other companies' jobs, so the "employer" is meaningless.
AGGREGATORS = {"jobgether", "jobleads", "talent com", "ziprecruiter", "lensa", "jooble", "neuvoo", "whatjobs",
               "jobrapido", "adzuna", "indeed", "glassdoor", "linkedin", "simplyhired", "randstad", "robert half",
               "hays", "adecco", "manpower", "crossover", "turing", "toptal", "andela", "dataannotation"}


def words_re(words):
    return re.compile(r"\b(" + "|".join(re.escape(w.lower()) for w in words) + r")", re.I) if words else None


def min_salary(p, country):
    m = p["search"].get("min_salary") or 0
    return (m.get(country) or m.get("default") or 0) if isinstance(m, dict) else m


def freshness(posted):
    """Points for a recent posting: early applicants get read."""
    age = age_days(posted)
    if age is None:
        return 3
    return 10 if age <= 3 else 7 if age <= 7 else 4 if age <= 14 else 0


def evaluate(p, r, sponsors, inc, exc, kw, fit=None):
    """Returns the scored row, or None to drop the job."""
    s = p["search"]
    r["title"], r["company"] = str(r.get("title") or "").strip(), str(r.get("company") or "").strip()
    if not r.get("url") or not r.get("title") or norm_co(r["company"]) in AGGREGATORS:
        return None
    if not inc.search(r["title"]) or (exc and exc.search(r["title"])):
        return None
    country = "canada" if r["source"] == "jobbank" else country_of(r["location"], s["countries"])
    if not country and r.get("vague_location") and r.get("detail"):    # "3 Locations": ask the posting where
        fetch_detail(r)
        country = country_of(r["location"], s["countries"])
    if not country:
        return None
    posted = r.get("posted") or ""
    age = age_days(posted)
    if r["source"] != "jobbank" and age is not None and age > s.get("max_age_days", 30):
        return None
    if r["source"] == "jobbank" and not jobbank_detail(r):
        return None
    if r.get("detail") and not r.get("desc"):
        fetch_detail(r)
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
    note = r.get("note", "")
    have, need = s.get("years_experience"), years_required(desc)
    over = (need - have) if (need is not None and have is not None) else 0
    if over > s.get("years_slack", 2):
        return None
    if over > 0:
        note = (note + " · " if note else "") + f"Asks for {need}+ years"

    title_hits = len(set(m.lower() for m in kw.findall(r["title"]))) if kw else 0
    inc_hits = len(set(m.lower() for m in inc.findall(r["title"])))
    desc_hits = len(set(m.lower() for m in kw.findall(desc))) if kw else 0
    fit_pct = fit.score(desc) if fit else 0
    score = min(30, 18 * title_hits) + min(10, 4 * inc_hits) + min(10, 3 * desc_hits) + round(fit_pct * 0.2)
    score += {1: 20, 2: 16, 3: 10}.get(tier, 0) if s.get("needs_sponsorship") else 15
    score += freshness(posted) + (5 if r["hi"] else 0) - 5 * max(0, over)
    return {"id": job_id(r["company"], r["title"]), "found": today(), "title": r["title"][:140],
            "company": r["company"][:80], "location": r["location"][:80], "country": country, "url": r["url"],
            "source": r["source"], "salary_lo": r["lo"], "salary_hi": r["hi"], "score": max(0, min(score, 100)),
            "tier": tier, "visa": visa, "note": note, "email": "", "desc": desc[:6000],
            "posted": posted, "last_seen": today(), "fit": fit_pct, "board": r.get("board", ""),
            "base": max(0, min(score, 100)), "taste": 0}


def fetch_all(p, names):
    """Every source at once; each one is slow for its own reasons (politeness delays, paging)."""
    def one(name):
        try:
            return SOURCES[name](p)
        except Exception as e:
            log(f"  [{name}] failed: {type(e).__name__}: {e}")
            return []
    raw, counts = [], {}
    log(f"fetching {', '.join(names)} ...")
    with cf.ThreadPoolExecutor(max_workers=max(1, len(names))) as ex:
        futs = {ex.submit(one, n): n for n in names}
        for f in cf.as_completed(futs):
            name, got = futs[f], f.result()
            counts[name] = len(got)
            raw += got
            log(f"  {name}: {len(got)} postings")
    return raw, counts


def mark_closed(db, raw):
    """A full ATS board lists every open role, so a job missing from a board that answered has closed.

    Only boards read completely count: a failed fetch, a keyword-searched Workday or a giant board
    read in part never closes anything."""
    seen = {job_id(r["company"], r["title"]) for r in raw}
    full = [r for r in raw if r["source"] in FULL_BOARDS and r.get("board")]
    partial = {r["board"] for r in full if r.get("partial")}
    boards = {r["board"] for r in full} - partial
    # Jobs saved before 0.2 have no board, so fall back to platform + company for those.
    legacy = {(r["source"], norm_co(r["company"])) for r in full if r["board"] not in partial}
    db.executemany("UPDATE jobs SET last_seen=?, closed='' WHERE id=?", [(today(), i) for i in seen])
    gone = [r["id"] for r in db.execute("SELECT id, source, company, board FROM jobs WHERE closed='' AND "
                                        "status NOT IN ('skip','rejected')")
            if r["id"] not in seen and (r["board"] in boards if r["board"]
                                        else (r["source"], norm_co(r["company"])) in legacy)]
    db.executemany("UPDATE jobs SET closed=? WHERE id=?", [(today(), i) for i in gone])
    return len(gone)


def run(p, only=None, find_emails=20):
    db = connect(p["_home"])
    s = p["search"]
    if not s["keywords"]:
        sys.exit("profile.yaml: search.keywords is empty")
    inc, exc, kw = words_re(s["include"]), words_re(s["exclude"]), words_re(s["keywords"])
    sponsors = Sponsors(p["_home"], s["countries"]) if s.get("needs_sponsorship") else Sponsors(p["_home"], [])
    rf = Path(p["_home"]) / "resume.yaml"
    fit = Fit(yaml.safe_load(rf.read_text(encoding="utf-8")) if rf.exists() else {})

    names = []
    for name in only or p["sources"]:
        if name in SOURCES:
            names.append(name)
        else:
            log(f"unknown source {name!r}; choose from {', '.join(SOURCES)}")
    raw, counts = fetch_all(p, names)

    # A source that quietly drops to zero while still answering is the classic silent failure.
    prev = {r["source"]: r["best"] for r in db.execute("SELECT * FROM source_yield")}
    for name, n in counts.items():
        if n == 0 and prev.get(name, 0) >= 20:
            log(f"WARNING: {name} returned 0 today but has returned {prev[name]} before. It may be broken or blocking you.")
        if n:
            db.execute("INSERT INTO source_yield VALUES (?,?,?) ON CONFLICT(source) DO UPDATE SET "
                       "best=max(best, excluded.best), ts=excluded.ts", (name, n, today()))

    closed = mark_closed(db, raw)
    taste = learn.Taste(db)
    known = {r["id"] for r in db.execute("SELECT id FROM jobs")}
    fresh = {}
    for r in sorted(raw, key=lambda r: r["source"] != "jobbank"):   # Job Bank records are richest, let them win
        jid = job_id(r["company"], r["title"])
        if jid in known or jid in fresh:
            continue
        row = evaluate(p, r, sponsors, inc, exc, kw, fit)
        if row:
            row["taste"] = taste.of(row)
            row["score"] = max(0, min(100, row["base"] + row["taste"]))
            fresh[jid] = row

    ranked = sorted(fresh.values(), key=lambda x: -x["score"])
    for row in ranked[:find_emails]:
        row["email"] = emails.find(row)

    cols = list(ranked[0]) if ranked else []
    for row in ranked:
        db.execute(f"INSERT OR IGNORE INTO jobs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                   [row[c] for c in cols])
    db.commit()
    learn.apply(db, taste)
    out = report.write(p, db)
    log(f"\n{len(ranked)} new matching jobs from {len(raw)} postings."
        + (f" {closed} jobs you saw before have closed." if closed else ""))
    log(f"Open your list: {out}")
    sent = notify.send(p, ranked)
    if sent:
        log(f"Sent the top matches to {sent}.")
    return ranked
