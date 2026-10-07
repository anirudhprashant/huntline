"""Learns your taste from what you do with jobs, and nudges the ranking toward it.

Shortlisting, applying, interviewing and offers say "more like this". Skipping says "less".
(Rejected is the employer's choice, not yours, so it teaches nothing.) From those choices a
small naive-Bayes model weighs title words, companies and countries, then moves each open
job's score by at most TASTE_MAX points. Nothing is learned until you have made at least
MIN_EACH choices of each kind, and a signal must appear in two or more of your choices to count.
"""
import math

from .resume import words
from .sponsors import norm_co

LIKE = ("shortlisted", "applied", "interview", "offer")
DISLIKE = ("skip",)
MIN_EACH = 3
TASTE_MAX = 10


def features(job):
    f = {f"title:{w}" for w in words(job.get("title") or "")}
    if job.get("company") and norm_co(job["company"]):
        f.add(f"company:{norm_co(job['company'])}")
    if job.get("country"):
        f.add(f"country:{job['country']}")
    return f


class Taste:
    def __init__(self, db):
        pos, neg = [], []
        for r in db.execute(f"SELECT title, company, country, status FROM jobs WHERE status IN "
                            f"({','.join('?' * len(LIKE + DISLIKE))})", LIKE + DISLIKE):
            (pos if r["status"] in LIKE else neg).append(features(dict(r)))
        self.n_like, self.n_skip = len(pos), len(neg)
        self.ready = self.n_like >= MIN_EACH and self.n_skip >= MIN_EACH
        self.weights = {}
        if not self.ready:
            return
        count = {}
        for fs, i in [(f, 0) for f in pos] + [(f, 1) for f in neg]:
            for f in fs:
                count.setdefault(f, [0, 0])[i] += 1
        P, N = len(pos), len(neg)
        for f, (a, b) in count.items():
            if a + b >= 2:
                w = math.log((a + 1) / (P + 2)) - math.log((b + 1) / (N + 2))
                if abs(w) > 0.05:
                    self.weights[f] = w

    def of(self, job):
        """Points to add (or take away) for this job, -TASTE_MAX..TASTE_MAX."""
        if not self.ready:
            return 0
        s = sum(self.weights.get(f, 0) for f in features(job))
        return round(TASTE_MAX * math.tanh(s / 3))

    def top(self, n=8):
        ranked = sorted(self.weights.items(), key=lambda kv: kv[1])
        nice = lambda kv: kv[0].split(":", 1)[1] + (f" ({kv[0].split(':')[0]})" if not kv[0].startswith("title:") else "")
        return [nice(kv) for kv in reversed(ranked[-n:]) if kv[1] > 0], [nice(kv) for kv in ranked[:n] if kv[1] < 0]


def apply(db, taste=None):
    """Re-scores every job still marked new. Returns how many changed."""
    taste = taste or Taste(db)
    db.execute("UPDATE jobs SET base=score WHERE base IS NULL")
    changed = []
    for r in db.execute("SELECT id, title, company, country, base, score, taste FROM jobs WHERE status='new'"):
        t = taste.of(dict(r))
        score = max(0, min(100, (r["base"] or 0) + t))
        if t != (r["taste"] or 0) or score != r["score"]:
            changed.append((t, score, r["id"]))
    db.executemany("UPDATE jobs SET taste=?, score=? WHERE id=?", changed)
    db.commit()
    return len(changed)
