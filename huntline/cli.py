"""huntline: find jobs worth applying to, then tailor a resume, cover letter and email for each.

  huntline init              answer a few questions, get profile.yaml + resume.yaml
  huntline scout             search every source, open out/jobs.html
  huntline resume <id>       resume PDF tailored to one job
  huntline letter <id>       cover letter PDF for one job (--ai to have a model draft it)
  huntline pdf <file.txt>    re-render a letter after you edit it
  huntline drafts            email drafts with both PDFs attached (never sends)
  huntline status <id> applied
  huntline boards            discover more employer job boards in your countries
  huntline doctor            check your setup
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
    try:
        import jobspy  # noqa: F401
        ok(True, "JobSpy (Indeed, LinkedIn)")
    except ImportError:
        ok(False, "JobSpy (Indeed, LinkedIn) - optional", "pip install 'huntline[jobspy]'")
    ok(bool(os.environ.get("ADZUNA_APP_ID")), "Adzuna key - optional", "free at developer.adzuna.com")
    ok(bool(os.environ.get("REED_API_KEY")), "Reed key (UK) - optional", "free at reed.co.uk/developers")
    ok(bool(os.environ.get("GMAIL_APP_PASSWORD")), "Gmail drafts - optional", "else drafts are .eml files")
    ok(bool(os.environ.get("OPENAI_API_KEY")), "AI cover letters - optional", "any OpenAI-compatible key")


def job(db, jid):
    row = db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not row:
        sys.exit(f"No job {jid}. The id is the short code on each card in jobs.html.")
    return dict(row)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="huntline", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", help="folder holding profile.yaml (default: current folder, or $HUNTLINE_HOME)")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("init")
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
    s.add_argument("id")
    s.add_argument("status")
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

    from . import boards, drafts, letter, report, resume, scout
    from .profile import load, load_resume
    from .store import STATUSES, connect
    p = load(home)
    db = connect(home)
    if a.cmd == "scout":
        scout.run(p, a.only, a.emails)
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
        print(drafts.run(p, db, a.limit, a.ids, a.ai))
    elif a.cmd == "status":
        if a.status not in STATUSES:
            sys.exit(f"status must be one of: {', '.join(STATUSES)}")
        job(db, a.id)
        db.execute("UPDATE jobs SET status=? WHERE id=?", (a.status, a.id))
        db.commit()
        report.write(p, db)
        print(f"{a.id} -> {a.status}")
    elif a.cmd == "boards":
        boards.run(p, a.companies)


if __name__ == "__main__":
    main()
