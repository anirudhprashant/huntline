"""Offline tests for scoring, freshness, sources, closed-job tracking, notifications, AI ranking and serve."""
import datetime
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import yaml

from huntline import ai, cli, notify, profile, report, scout, serve, sources, store
from huntline.match import Fit, years_required
from huntline.sponsors import Sponsors

DATA = Path(profile.__file__).parent / "data"
TODAY = datetime.date.today()


def ago(n):
    return (TODAY - datetime.timedelta(days=n)).isoformat()


class Resp:
    def __init__(self, data):
        self.data, self.ok, self.status_code = data, True, 200
        self.text = data if isinstance(data, str) else json.dumps(data)
        self.content = self.text.encode()

    def json(self):
        return self.data if not isinstance(self.data, str) else json.loads(self.data)


def make_home(**search):
    home = Path(tempfile.mkdtemp())
    p = yaml.safe_load((DATA / "profile.example.yaml").read_text())
    p["search"].update(search)
    (home / "profile.yaml").write_text(yaml.safe_dump(p))
    (home / "resume.yaml").write_text((DATA / "resume.example.yaml").read_text())
    return profile.load(home)


def regexes(p):
    s = p["search"]
    return scout.words_re(s["include"]), scout.words_re(s["exclude"]), scout.words_re(s["keywords"])


def posting(**kw):
    base = {"title": "CRM Marketing Manager", "company": "Acme", "location": "Toronto", "url": "https://x/1",
            "lo": None, "hi": None, "source": "greenhouse", "desc": "", "posted": ""}
    base.update(kw)
    return base


class Dates(unittest.TestCase):
    def test_iso_date_shapes(self):
        self.assertEqual(store.iso_date("2026-03-04T10:00:00Z"), "2026-03-04")
        self.assertEqual(store.iso_date("Tue, 03 Mar 2026 10:00:00 +0000"), "2026-03-03")
        self.assertEqual(store.iso_date(1772582400000), "2026-03-04")        # Lever: milliseconds
        self.assertEqual(store.iso_date(1772582400), "2026-03-04")           # seconds
        self.assertEqual(store.iso_date("garbage"), "")
        self.assertEqual(store.iso_date(None), "")


class Matching(unittest.TestCase):
    def test_years_required(self):
        self.assertEqual(years_required("You have 5+ years of experience in lifecycle marketing."), 5)
        self.assertEqual(years_required("3-5 years' experience with HubSpot"), 3)
        self.assertEqual(years_required("Minimum of seven years of product marketing experience"), 7)
        self.assertEqual(years_required("8+ yrs experience. Also 2+ years of SQL experience"), 8)
        self.assertIsNone(years_required("We have 10 years and our team has deep experience"))
        self.assertIsNone(years_required(""))

    def test_resume_fit(self):
        f = Fit(yaml.safe_load((DATA / "resume.example.yaml").read_text()))
        self.assertIn("sql", f.tools)                       # "SQL basics" keeps the tool, drops the qualifier
        good = f.score("Own lifecycle email in Klaviyo and HubSpot, report in GA4 and Looker Studio.")
        bad = f.score("Senior Java engineer for distributed systems on Kubernetes and Kafka.")
        self.assertGreater(good, 60)
        self.assertLess(bad, 15)
        self.assertEqual(Fit({}).score("anything"), 0)


class Evaluate(unittest.TestCase):
    def setUp(self):
        self.p = make_home(years_experience=3)
        self.re = regexes(self.p)
        self.sp = Sponsors(self.p["_home"], [])
        self.fit = Fit(profile.load_resume(self.p))

    def ev(self, **kw):
        return scout.evaluate(self.p, posting(**kw), self.sp, *self.re, fit=self.fit)

    def test_stale_postings_dropped_fresh_ranked_higher(self):
        self.assertIsNone(self.ev(posted=ago(60)))
        fresh, older = self.ev(posted=ago(1)), self.ev(posted=ago(20))
        self.assertGreater(fresh["score"], older["score"])
        self.assertEqual(fresh["posted"], ago(1))

    def test_years_filter(self):
        self.assertIsNone(self.ev(desc="You bring 8+ years of experience in CRM."))
        row = self.ev(desc="You bring 4+ years of experience in CRM.")
        self.assertIn("Asks for 4+ years", row["note"])
        self.assertGreater(self.ev(desc="2+ years of experience in CRM.")["score"], row["score"])

    def test_resume_fit_raises_score(self):
        strong = self.ev(desc="Run Klaviyo and HubSpot lifecycle flows; report in GA4 and Looker Studio with SQL.")
        weak = self.ev(desc="Plan trade shows and print collateral for field events.")
        self.assertGreater(strong["fit"], weak["fit"])
        self.assertGreater(strong["score"], weak["score"])

    def test_detail_fetched_only_for_survivors(self):
        with mock.patch.object(sources, "get", return_value=Resp(
                {"jobAd": {"sections": {"jobDescription": {"text": "<p>We cannot sponsor visas.</p>"}}}})) as g:
            p = make_home(needs_sponsorship=True)
            row = scout.evaluate(p, posting(source="smartrecruiters", detail="https://api/x"),
                                 Sponsors(p["_home"], []), *regexes(p))
            self.assertIsNone(row)                       # the refusal was in the fetched description
            self.assertEqual(g.call_count, 1)
            scout.evaluate(p, posting(title="Accountant", detail="https://api/y"), Sponsors(p["_home"], []), *regexes(p))
            self.assertEqual(g.call_count, 1)            # filtered on title first, no fetch


class Sources(unittest.TestCase):
    P = {"search": {"countries": ["germany", "remote"], "keywords": ["marketing"]}, "_home": "."}

    def test_greenhouse_real_company_and_date(self):
        data = {"jobs": [{"title": "CRM Manager", "company_name": "GitLab", "location": {"name": "Remote"},
                          "absolute_url": "u", "content": "&lt;p&gt;Hi&lt;/p&gt;", "first_published": "2026-01-02T00:00:00Z"}]}
        with mock.patch.object(sources, "get", return_value=Resp(data)):
            j = sources.board("greenhouse", "gitlab")[0]
        self.assertEqual((j["company"], j["posted"], j["desc"], j["source"]), ("GitLab", "2026-01-02", "Hi", "greenhouse"))

    def test_lever_millisecond_dates(self):
        data = [{"text": "CRM Manager", "categories": {"location": "Berlin"}, "hostedUrl": "u", "createdAt": 1772582400000}]
        with mock.patch.object(sources, "get", return_value=Resp(data)):
            self.assertEqual(sources.board("lever", "acme")[0]["posted"], "2026-03-04")

    def test_arbeitnow(self):
        page1 = {"data": [{"title": "Marketing Manager", "company_name": "Acme GmbH", "location": "Berlin", "remote": True,
                           "url": "u", "description": "<p>Visa sponsorship available</p>", "tags": ["Marketing"],
                           "created_at": 1772582400}]}
        with mock.patch.object(sources, "get", side_effect=[Resp(page1), Resp({"data": []})]), \
                mock.patch.object(sources.time, "sleep"):
            j = sources.arbeitnow(self.P)[0]
        self.assertEqual(j["location"], "Berlin (Remote)")
        self.assertIn("Visa sponsorship", j["desc"])

    def test_remotive_and_jobicy(self):
        rem = {"jobs": [{"title": "Lifecycle Marketer", "company_name": "Co", "candidate_required_location": "USA",
                         "url": "u", "description": "d", "publication_date": "2026-03-01T00:00:00"}]}
        job = {"jobs": [{"jobTitle": "Growth &amp; CRM", "companyName": "Co", "jobGeo": "Anywhere", "url": "u",
                         "jobDescription": "d", "pubDate": "2026-03-01 10:00:00", "annualSalaryMax": 90000}]}
        with mock.patch.object(sources.time, "sleep"):
            with mock.patch.object(sources, "get", return_value=Resp(rem)):
                self.assertEqual(sources.remotive(self.P)[0]["location"], "USA Remote")
            with mock.patch.object(sources, "get", return_value=Resp(job)):
                j = sources.jobicy(self.P)[0]
        self.assertEqual((j["title"], j["location"], j["hi"]), ("Growth & CRM", "Remote", 90000))

    def test_hn_comment_parsing(self):
        j = sources.hn_post("Acme | Senior Marketing Manager | Berlin, Germany | ONSITE<p>We need you.", 42, "2026-03-01")
        self.assertEqual((j["company"], j["title"]), ("Acme", "Senior Marketing Manager"))
        self.assertIn("Berlin", j["location"])
        self.assertIsNone(sources.hn_post("Just a reply to someone", 1, ""))


class Store(unittest.TestCase):
    def test_old_database_is_migrated(self):
        home = Path(tempfile.mkdtemp())
        old = sqlite3.connect(home / "jobs.db")
        old.executescript(store.SCHEMA)
        old.execute("INSERT INTO jobs (id, title) VALUES ('abc12345', 'x')")
        old.commit()
        old.close()
        db = store.connect(home)
        row = dict(db.execute("SELECT * FROM jobs").fetchone())
        for col in store.ADDED:
            self.assertIn(col, row)
        self.assertEqual(store.find_id(db, "abc"), "abc12345")
        self.assertIsNone(store.find_id(db, "zzz"))


class Closed(unittest.TestCase):
    def test_job_missing_from_answering_board_is_closed(self):
        home = Path(tempfile.mkdtemp())
        db = store.connect(home)
        for co, title, src in (("Acme", "CRM Manager", "greenhouse"), ("Acme", "SEO Lead", "greenhouse"),
                               ("Other", "CRM Manager", "greenhouse"), ("Acme", "Email Marketer", "remoteok")):
            db.execute("INSERT INTO jobs (id, company, title, source) VALUES (?,?,?,?)", (store.job_id(co, title), co, title, src))
        raw = [posting(company="Acme", title="CRM Manager")]          # Acme's board answered without the SEO Lead
        self.assertEqual(scout.mark_closed(db, raw), 1)
        closed = {r["title"] for r in db.execute("SELECT title FROM jobs WHERE closed != ''")}
        self.assertEqual(closed, {"SEO Lead"})                         # Other's board didn't answer; remoteok isn't a full board
        scout.mark_closed(db, raw + [posting(company="Acme", title="SEO Lead")])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs WHERE closed != ''").fetchone()[0], 0)


class Notify(unittest.TestCase):
    def test_digest_and_threshold(self):
        jobs = [{"score": 90, "title": "A", "company": "B", "location": "C", "url": "u", "salary_lo": 60000,
                 "salary_hi": 80000, "visa": "UK licensed sponsor"},
                {"score": 30, "title": "Low", "company": "B", "location": "C", "url": "u", "salary_lo": None,
                 "salary_hi": None, "visa": ""}]
        self.assertIn("60k-80k · UK licensed sponsor", notify.digest(jobs))
        sent = []
        with mock.patch.object(notify, "channels", return_value=[("x", lambda t: sent.append(t) or Resp({}))]):
            self.assertEqual(notify.send({"notify": {"min_score": 50}}, jobs), "x")
        self.assertIn("1 new match.", sent[0])
        self.assertNotIn("Low", sent[0])
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(notify.send({}, jobs), "")               # nothing configured, nothing sent


class AI(unittest.TestCase):
    def test_rank_stores_verdicts(self):
        p = make_home()
        db = store.connect(p["_home"])
        db.execute("INSERT INTO jobs (id, title, company, location, score, status, desc) VALUES "
                   "('j1','CRM Manager','Acme','Toronto',80,'new','HubSpot')")
        db.commit()
        reply = 'Sure! ```json\n{"fit": 87, "why": "Ran HubSpot lead routing.", "gaps": "No Marketo."}\n```'
        with mock.patch.object(ai, "chat", return_value=reply), mock.patch("builtins.print"):
            done = ai.rank(p, db, {}, limit=5)
        self.assertEqual(len(done), 1)
        row = db.execute("SELECT ai_fit, ai_note FROM jobs WHERE id='j1'").fetchone()
        self.assertEqual(row["ai_fit"], 87)
        self.assertIn("Gap: No Marketo.", row["ai_note"])
        with mock.patch.object(ai, "chat") as c:
            ai.rank(p, db, {}, limit=5)
            c.assert_not_called()                                    # already reviewed


class EndToEnd(unittest.TestCase):
    def test_scout_run_report_and_cli(self):
        p = make_home(years_experience=4)
        fake = lambda _p: [posting(title="CRM Marketing Manager", posted=ago(2), desc="Klaviyo and HubSpot lifecycle."),
                           posting(title="Lifecycle Marketing Lead", company="Beta", url="u2", posted=ago(90)),
                           posting(title="Head Chef", company="Gamma", url="u3")]
        with mock.patch.dict(scout.SOURCES, {"fake": fake}, clear=True), \
                mock.patch.object(scout.emails, "find", return_value=""), \
                mock.patch.object(scout.notify, "channels", return_value=[]), mock.patch.object(scout, "log"):
            ranked = scout.run(p, ["fake"])
        self.assertEqual([r["title"] for r in ranked], ["CRM Marketing Manager"])
        page = (Path(p["_home"]) / "out" / "jobs.html").read_text()
        self.assertIn("CRM Marketing Manager", page)
        self.assertIn('TOKEN=""', page)                               # static file: buttons copy commands
        jid = ranked[0]["id"]
        with mock.patch("builtins.print"):
            cli.main(["--home", p["_home"], "status", jid[:4], "applied"])
        db = store.connect(p["_home"])
        self.assertEqual(db.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0], "applied")


class Serve(unittest.TestCase):
    def setUp(self):
        self.p = make_home()
        db = store.connect(self.p["_home"])
        db.execute("INSERT INTO jobs (id, title, company, status) VALUES ('j1','CRM Manager','Acme','new')")
        db.commit()
        (Path(self.p["_home"]) / "secret.txt").write_text("private")
        self.token = "t0ken"
        from http.server import ThreadingHTTPServer
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), serve.handler(self.p, self.token))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def call(self, path, body=None, token=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Huntline-Token": token} if token else {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_page_token_and_actions(self):
        code, page = self.call("/")
        self.assertEqual(code, 200)
        self.assertIn('TOKEN="t0ken"', page)
        self.assertEqual(self.call("/api/status", {"id": "j1", "status": "applied"})[0], 403)          # no token
        self.assertEqual(self.call("/api/status", {"id": "j1", "status": "applied"}, "wrong")[0], 403)
        self.assertEqual(self.call("/api/status", {"id": "j1", "status": "hacked"}, self.token)[0], 400)
        self.assertEqual(self.call("/api/status", {"id": "j1", "status": "applied"}, self.token)[0], 200)
        db = store.connect(self.p["_home"])
        self.assertEqual(db.execute("SELECT status FROM jobs").fetchone()[0], "applied")

    def test_files_cannot_escape_out(self):
        self.assertEqual(self.call("/files/../secret.txt")[0], 404)
        self.assertEqual(self.call("/files/%2e%2e/secret.txt")[0], 404)
        self.assertEqual(self.call("/files/jobs.csv")[0], 404)       # not written yet
        report.write(self.p, store.connect(self.p["_home"]))
        self.assertEqual(self.call("/files/jobs.csv")[0], 200)


if __name__ == "__main__":
    unittest.main()
