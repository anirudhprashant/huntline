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


def connect(home):
    db = sqlite3.connect(Path(home) / "jobs.db")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def job_id(company, title):
    """Same company + same title = same job, whichever board it came from."""
    key = re.sub(r"\W+", " ", f"{company}|{title}".lower()).strip()
    return hashlib.sha1(key.encode()).hexdigest()[:8]


def today():
    return datetime.date.today().isoformat()
