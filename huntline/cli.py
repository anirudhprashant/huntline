"""huntline: find jobs worth applying to, then tailor a resume, cover letter and email for each.

  huntline init              answer a few questions, get profile.yaml + resume.yaml
  huntline scout             search every source, open out/jobs.html
  huntline top               your best open matches, right in the terminal
  huntline show <id>         everything about one job
  huntline serve             the job list as a local app with working buttons
  huntline rank --ai         have a model screen your top jobs against your resume
  huntline learn             what your shortlists and skips have taught the ranking
  huntline prep <id>         interview prep notes for one job (--ai for likely questions)
  huntline resume <id>       resume PDF tailored to one job
  huntline letter <id>       cover letter PDF for one job (--ai to have a model draft it)
  huntline pdf <file.txt>    re-render a letter after you edit it
  huntline drafts            email drafts with both PDFs attached (never sends)
  huntline status <id>... applied
  huntline boards            discover more employer job boards in your countries
  huntline doctor            check your setup

Ids can be shortened to their first few characters, like git.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

from . import __version__

EXAMPLES = Path(__file__).parent / "data"


def ask(q, default=""):
    a = input(f"{q}{f' [{default}]' if default else ''}: ").strip()
    return a or default


def init(home):
    import yaml
    home.mkdir(parents=True, exist_ok=True)
    if (home / "profile.yaml").exists():
        sys.exit(f"{home / 'profile.yaml'} already exists. Edit it directly.")
    print("A few questions. Press Enter to accept the default. You can change everything later in profile.yaml.\n")
    p = yaml.safe_load((EXAMPLES / "profile.example.yaml").read_text())
    p["name"] = ask("Your full name", p["name"])
    p["email"] = ask("Email", p["email"])
    p["phone"] = ask("Phone (optional)", "")
    p["city"] = ask("City, Country", p["city"])
    kws = ask("Job titles or keywords, comma separated", ", ".join(p["search"]["keywords"]))
    p["search"]["keywords"] = [k.strip() for k in kws.split(",") if k.strip()]
    p["search"]["include"] = []
    print("Countries: canada, uk, netherlands, germany, ireland, usa, australia, india, remote")
    cs = ask("Where do you want to work, comma separated", ", ".join(p["search"]["countries"]))
    p["search"]["countries"] = [c.strip().lower() for c in cs.split(",") if c.strip()]
    p["search"]["needs_sponsorship"] = ask("Do you need visa sponsorship? (y/n)", "n").lower().startswith("y")
    yrs = ask("Years of relevant experience (skips jobs asking for far more; blank to keep all)", "")
    p["search"]["years_experience"] = int(yrs) if yrs.isdigit() else None
    (home / "profile.yaml").write_text(yaml.safe_dump(p, sort_keys=False, allow_unicode=True))
    shutil.copy(EXAMPLES / "resume.example.yaml", home / "resume.yaml")
    print(f"\nWrote {home / 'profile.yaml'} and {home / 'resume.yaml'}.")
    print("Next: put your real experience into resume.yaml (it's the only source of truth), then run: huntline scout")


def doctor(home):
    from .pdf import browser
    ok = lambda b, msg, fix="": print(("  ok   " if b else "  --   ") + msg + ("" if b else f"   ({fix})"))
    ok((home / "profile.yaml").exists(), "profile.yaml", "run huntline init")
    ok((home / "resume.yaml").exists(), "resume.yaml", "run huntline init")
    ok(bool(browser()), "Chrome/Chromium for PDFs", "install Chrome, or pip install playwright")
    from importlib.util import find_spec
    ok(find_spec("jobspy") is not None, "JobSpy (Indeed, LinkedIn) - optional", "pip install 'huntline[jobspy]'")
    ok(bool(os.environ.get("ADZUNA_APP_ID")), "Adzuna key - optional", "free at developer.adzuna.com")
    ok(bool(os.environ.get("REED_API_KEY")), "Reed key (UK) - optional", "free at reed.co.uk/developers")
    ok(bool(os.environ.get("GMAIL_APP_PASSWORD")), "Gmail drafts - optional", "else drafts are .eml files")
    ok(bool(os.environ.get("BRAVE_API_KEY")), "Brave Search (finds employer websites) - optional", "free at brave.com/search/api")
    ok(bool(os.environ.get("FIRECRAWL_URL")), "Firecrawl (reads JavaScript sites) - optional", "self-host: github.com/firecrawl/firecrawl")
    ok(bool(os.environ.get("OPENAI_API_KEY")), "AI cover letters + rank --ai - optional", "any OpenAI-compatible key")
    ok(any(os.environ.get(k) for k in ("NTFY_TOPIC", "DISCORD_WEBHOOK_URL", "SLACK_WEBHOOK_URL", "TELEGRAM_BOT_TOKEN")),
       "Notifications after each scout - optional", "NTFY_TOPIC, DISCORD_WEBHOOK_URL, SLACK_WEBHOOK_URL or TELEGRAM_*")
    if (home / "profile.yaml").exists():
        import yaml
        prof = yaml.safe_load((home / "profile.yaml").read_text()) or {}
        ok((prof.get("search") or {}).get("years_experience") is not None, "search.years_experience - optional",
           "set it to drop postings that ask for far more years than you have")
        from .sources import SOURCES
        missing = [n for n in SOURCES if n not in (prof.get("sources") or []) and n != "jobspy"]
        ok(not missing, "all free sources enabled", f"add to sources in profile.yaml: {', '.join(missing)}")


def job(db, jid):
    from .store import find_ids
    ids = find_ids(db, jid)
    if not ids:
        sys.exit(f"No job {jid!r}. The id is the short code on each card in jobs.html.")
    if len(ids) > 1:
        sys.exit(f"{jid!r} matches {len(ids)} jobs ({', '.join(ids[:5])}{'...' if len(ids) > 5 else ''}). Type more of the id.")
    return dict(db.execute("SELECT * FROM jobs WHERE id=?", (ids[0],)).fetchone())


def money(lo, hi):
    from .notify import money as m
    return m(lo, hi)


def top(db, n=15, country=None, sort="score"):
    order = {"score": "score DESC", "ai": "COALESCE(ai_fit,-1) DESC, score DESC", "new": "COALESCE(NULLIF(posted,''),found) DESC"}
    rows = db.execute(f"SELECT * FROM jobs WHERE status IN ('new','shortlisted') AND closed='' "
                      f"{'AND country=?' if country else ''} ORDER BY {order[sort]} LIMIT ?",
                      (country, n) if country else (n,)).fetchall()
    if not rows:
        print("No open matches yet. Run: huntline scout")
    for r in rows:
        ai = f"ai {r['ai_fit']:>3}" if r["ai_fit"] is not None else "      "
        pay = money(r["salary_lo"], r["salary_hi"])
        print(f"{r['id']}  {r['score'] or 0:>3}  {ai}  {(r['title'] or '')[:46]:<46}  {(r['company'] or '')[:24]:<24}  "
              f"{(r['country'] or '')[:10]:<10} {pay}{'  ' + r['visa'][:40] if r['visa'] else ''}")


def learned(db):
    from . import learn
    t = learn.Taste(db)
    if not t.ready:
        print(f"Not enough choices to learn from yet: {t.n_like} liked (shortlisted/applied/interview/offer) and "
              f"{t.n_skip} skipped. Huntline starts adjusting the ranking at {learn.MIN_EACH} of each.")
    else:
        likes, dislikes = t.top()
        print(f"Learned from {t.n_like} jobs you liked and {t.n_skip} you skipped.")
        print("  more like:  " + (", ".join(likes) or "nothing stands out yet"))
        print("  less like:  " + (", ".join(dislikes) or "nothing stands out yet"))
    n = learn.apply(db, t)
    print(f"{n} open job scores updated." if n else "Scores are up to date.")


def show(j):
    from .store import age_days
    age = age_days(j.get("posted"))
    print(f"{j['title']}\n{j['company']} · {j['location']} · {j['country']}")
    for label, v in (("id", j["id"]), ("score", j["score"]), ("your taste", f"{j['taste']:+d}" if j.get("taste") else ""), ("resume fit", f"{j.get('fit') or 0}%"),
                     ("AI fit", j.get("ai_fit")), ("AI says", j.get("ai_note")), ("salary", money(j["salary_lo"], j["salary_hi"])),
                     ("posted", f"{j['posted']} ({age}d ago)" if age is not None else ""), ("visa", j["visa"]),
                     ("email", j["email"]), ("status", j["status"]), ("closed", j.get("closed")), ("note", j["note"]),
                     ("source", j["source"]), ("url", j["url"])):
        if v not in (None, ""):
            print(f"  {label:<11}{v}")
    if j.get("desc"):
        print("\n" + j["desc"][:1200] + ("..." if len(j["desc"]) > 1200 else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="huntline", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", help="folder holding profile.yaml (default: current folder, or $HUNTLINE_HOME)")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("init")
    s = sub.add_parser("top")
    s.add_argument("-n", type=int, default=15)
    s.add_argument("--country")
    s.add_argument("--sort", choices=["score", "ai", "new"], default="score")
    s = sub.add_parser("show")
    s.add_argument("id")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-open", action="store_true")
    sub.add_parser("learn")
    s = sub.add_parser("prep")
    s.add_argument("id")
    s.add_argument("--ai", action="store_true")
    s = sub.add_parser("rank")
    s.add_argument("ids", nargs="*")
    s.add_argument("--ai", action="store_true", required=True, help="use your OpenAI-compatible model")
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--redo", action="store_true", help="re-review jobs that already have an AI fit")
    sub.add_parser("doctor")
    s = sub.add_parser("scout")
    s.add_argument("--only", nargs="+", help="only these sources")
    s.add_argument("--emails", type=int, default=20, help="look up contact emails for the top N (default 20)")
    s = sub.add_parser("resume")
    s.add_argument("id", nargs="?")
    s = sub.add_parser("letter")
    s.add_argument("id")
    s.add_argument("--ai", action="store_true")
    s = sub.add_parser("pdf")
    s.add_argument("file")
    s = sub.add_parser("drafts")
    s.add_argument("ids", nargs="*")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--ai", action="store_true")
    s = sub.add_parser("status")
    s.add_argument("args", nargs="+", metavar="id... status")
    s = sub.add_parser("boards")
    s.add_argument("--companies")
    a = ap.parse_args(argv)

    home = Path(a.home or os.environ.get("HUNTLINE_HOME") or Path.cwd()).expanduser().resolve()
    env = home / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() and not k.startswith("#") and v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
    if a.cmd in (None,):
        ap.print_help()
        return
    if a.cmd == "init":
        return init(home)
    if a.cmd == "doctor":
        return doctor(home)

    from . import ai, boards, drafts, learn, letter, prep, report, resume, scout, serve
    from .profile import load, load_resume
    from .store import STATUSES, connect
    p = load(home)
    db = connect(home)
    if a.cmd == "scout":
        scout.run(p, a.only, a.emails)
    elif a.cmd == "top":
        top(db, a.n, a.country, a.sort)
    elif a.cmd == "show":
        show(job(db, a.id))
    elif a.cmd == "serve":
        serve.run(p, a.port, not a.no_open)
    elif a.cmd == "rank":
        ids = [job(db, i)["id"] for i in a.ids]
        done = ai.rank(p, db, load_resume(p), a.limit, ids, a.redo)
        report.write(p, db)
        print(f"{len(done)} jobs reviewed." if done else "Nothing to review (all your open jobs already have an AI fit; --redo to redo).")
    elif a.cmd == "learn":
        learned(db)
        report.write(p, db)
    elif a.cmd == "prep":
        print(prep.write(p, load_resume(p), job(db, a.id), a.ai))
    elif a.cmd == "resume":
        j = job(db, a.id) if a.id else {"title": "", "desc": "", "company": "general"}
        out = home / "out" / "resumes" / f"{letter.slug(j['company'] + '-' + j['title'])}.pdf"
        print(resume.build(p, load_resume(p), out, j["title"], j.get("desc", "")))
    elif a.cmd == "letter":
        src = letter.draft(p, load_resume(p), job(db, a.id), a.ai)
        print(f"{letter.build(p, src)}\n(edit {src} and run `huntline pdf {src}` to change it)")
    elif a.cmd == "pdf":
        print(letter.build(p, a.file))
    elif a.cmd == "drafts":
        print(drafts.run(p, db, a.limit, [job(db, i)["id"] for i in a.ids], a.ai))
    elif a.cmd == "status":
        *ids, status = a.args
        if status not in STATUSES or not ids:
            sys.exit(f"usage: huntline status <id>... <status>, status one of: {', '.join(STATUSES)}")
        for i in [job(db, i)["id"] for i in ids]:
            db.execute("UPDATE jobs SET status=? WHERE id=?", (status, i))
            print(f"{i} -> {status}")
        db.commit()
        learn.apply(db)
        report.write(p, db)
    elif a.cmd == "boards":
        boards.run(p, a.companies)


if __name__ == "__main__":
    main()
