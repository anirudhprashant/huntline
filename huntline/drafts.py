"""Puts ready-to-send application emails in your mail drafts. It never sends anything.

You review each draft, change what you like, and press send yourself.

With GMAIL_ADDRESS and GMAIL_APP_PASSWORD set (Google account > Security > App passwords),
drafts go straight into Gmail over IMAP. Any other IMAP provider works with IMAP_HOST.
Without them, .eml files are written to out/drafts/; double-click one to open it in
your mail app.
"""
import imaplib
import os
import re
import time
from email.message import EmailMessage
from pathlib import Path

from . import letter, resume
from .profile import load_resume

BODY = """{greeting}

I'm applying for the {role} role at {company}. {pitch}

My resume and a short cover letter are attached. I'd be glad to talk whenever suits you.

{signoff}
{name}
{contact}"""


def make(p, r, job, use_ai=False):
    home = Path(p["_home"]) / "out" / "applications" / letter.slug(job["company"] + "-" + job["title"])
    home.mkdir(parents=True, exist_ok=True)
    fname = re.sub(r"\W+", "_", p["name"]).strip("_")
    cv = resume.build(p, r, home / f"{fname}_Resume.pdf", job["title"], job.get("desc", ""))
    cl = letter.build(p, letter.draft(p, r, job, use_ai))
    msg = EmailMessage()
    msg["From"] = p.get("email", "")
    msg["To"] = re.sub(r"\s*\(guess\)", "", job.get("email") or "")
    msg["Subject"] = f"{job['title']} - application from {p['name']}"
    msg.set_content(BODY.format(
        greeting=p["letter"]["greeting"], role=job["title"], company=job["company"],
        pitch=p["letter"].get("pitch", ""), signoff=p["letter"]["signoff"], name=p["name"],
        contact=" | ".join(x for x in (p.get("phone"), *(p.get("links") or [])[:1]) if x)))
    for f in (cv, cl):
        msg.add_attachment(Path(f).read_bytes(), maintype="application", subtype="pdf",
                           filename=f"{fname}_Cover_Letter.pdf" if f == cl else Path(f).name)
    return msg


def save(msgs, p):
    user, pw = os.environ.get("GMAIL_ADDRESS"), os.environ.get("GMAIL_APP_PASSWORD")
    if user and pw:
        imap = imaplib.IMAP4_SSL(os.environ.get("IMAP_HOST", "imap.gmail.com"))
        imap.login(user, pw)
        folder = os.environ.get("IMAP_DRAFTS", "[Gmail]/Drafts")
        for m in msgs:
            imap.append(f'"{folder}"', r"\Draft", imaplib.Time2Internaldate(time.time()), m.as_bytes())
        imap.logout()
        return f"{len(msgs)} drafts added to {user}. Open Drafts to review and send."
    out = Path(p["_home"]) / "out" / "drafts"
    out.mkdir(parents=True, exist_ok=True)
    for m in msgs:
        (out / f"{letter.slug(m['Subject'])}.eml").write_bytes(m.as_bytes())
    return f"{len(msgs)} .eml drafts written to {out} (set GMAIL_ADDRESS + GMAIL_APP_PASSWORD to put them in Gmail)."


def run(p, db, limit=10, ids=None, use_ai=False):
    r = load_resume(p)
    if ids:
        jobs = [dict(j) for i in ids for j in db.execute("SELECT * FROM jobs WHERE id=?", (i,))]
    else:
        jobs = [dict(j) for j in db.execute(
            "SELECT * FROM jobs WHERE status IN ('new','shortlisted') AND email != '' ORDER BY score DESC LIMIT ?", (limit,))]
    if not jobs:
        return "No jobs with an email address to draft. Run `huntline scout` first, or pass job ids."
    msgs = []
    for j in jobs:
        print(f"  drafting {j['title']} @ {j['company']}")
        msgs.append(make(p, r, j, use_ai))
        db.execute("UPDATE jobs SET status='shortlisted' WHERE id=? AND status='new'", (j["id"],))
    db.commit()
    return save(msgs, p)
