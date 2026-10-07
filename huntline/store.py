"""One SQLite file holds every job you have seen and what you did about it."""
import datetime
import hashlib
import re
import sqlite3
from pathlib import Path

STATUSES = ("new", "shortlisted", "applied", "interview", "offer", "rejected", "skip")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, found TEXT, title TEXT, company TEXT, location TEXT, country TEXT,
  url TEXT, source TEXT, salary_lo REAL, salary_hi REAL, score INTEGER, tier INTEGER,
  visa TEXT, note TEXT, email TEXT, status TEXT DEFAULT 'new', desc TEXT);
CREATE TABLE IF NOT EXISTS emails (company TEXT PRIMARY KEY, email TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS source_yield (source TEXT PRIMARY KEY, best INTEGER, ts TEXT);
"""

# Columns added after 0.1. Older jobs.db files get them on first connect.
ADDED = {"posted": "TEXT DEFAULT ''", "last_seen": "TEXT DEFAULT ''", "fit": "INTEGER DEFAULT 0",
         "ai_fit": "INTEGER", "ai_note": "TEXT DEFAULT ''", "closed": "TEXT DEFAULT ''",
         "board": "TEXT DEFAULT ''", "base": "INTEGER", "taste": "INTEGER DEFAULT 0"}


def connect(home):
    db = sqlite3.connect(Path(home) / "jobs.db")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    have = {r["name"] for r in db.execute("PRAGMA table_info(jobs)")}
    for col, decl in ADDED.items():
        if col not in have:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {col} {decl}")
    db.commit()
    return db


def job_id(company, title):
    """Same company + same title = same job, whichever board it came from."""
    key = re.sub(r"\W+", " ", f"{company}|{title}".lower()).strip()
    return hashlib.sha1(key.encode()).hexdigest()[:8]


def find_ids(db, prefix):
    """Every id starting with these characters, like git. An exact id always wins."""
    prefix = (prefix or "").strip().lower()
    if not prefix:
        return []
    if db.execute("SELECT 1 FROM jobs WHERE id=?", (prefix,)).fetchone():
        return [prefix]
    return [r["id"] for r in db.execute("SELECT id FROM jobs WHERE substr(id, 1, ?) = ?", (len(prefix), prefix))]


def find_id(db, prefix):
    """Full id from the first few characters. None if missing or ambiguous."""
    ids = find_ids(db, prefix)
    return ids[0] if len(ids) == 1 else None


def today():
    return datetime.date.today().isoformat()


def iso_date(v):
    """Best-effort YYYY-MM-DD from the many date shapes job APIs return, or ''."""
    if v in (None, ""):
        return ""
    try:
        s = str(v).strip()
        if re.fullmatch(r"(19|20)\d{6}", s):                                  # 20260304
            return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:])).isoformat()
        if isinstance(v, (int, float)) or s.isdigit():
            n = float(v)
            n = n / 1000 if n > 1e11 else n
            if n < 1e9:                         # 0 or a tiny number means "no date", not 1970
                return ""
            return datetime.datetime.fromtimestamp(n, datetime.timezone.utc).date().isoformat()
        if m := re.match(r"(\d{4}-\d{2}-\d{2})", s):
            return m.group(1)
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def age_days(posted):
    try:
        return (datetime.date.today() - datetime.date.fromisoformat(posted)).days
    except (TypeError, ValueError):
        return None
