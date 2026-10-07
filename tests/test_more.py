"""Offline tests for Workday/Personio/Teamtailor, retries, taste learning, interview prep and hardening."""
import datetime
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import requests

from huntline import ai, cli, learn, prep, profile, serve, sources, store
from test_upgrade import Resp, make_home

TODAY = datetime.date.today()


class Raw:
    """A bare HTTP answer for XML feeds."""
    def __init__(self, text, status=200, headers=None):
        self.text, self.content, self.status_code = text, text.encode(), status
        self.ok, self.headers = 200 <= status < 300, headers or {}

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code))


class Boards(unittest.TestCase):
    def test_smartrecruiters_pages_and_flags_partial(self):
        page = lambda n, total: Resp({"totalFound": total, "content": [{"name": f"Job {i}", "id": i} for i in range(n)]})
        with mock.patch.object(sources, "get", side_effect=[page(100, 150), page(50, 150)]) as g:
            jobs = sources.board("smartrecruiters", "acme")
        self.assertEqual(len(jobs), 150)
        self.assertIn("offset=100", g.call_args_list[1].args[0])
        self.assertFalse(any(j.get("partial") for j in jobs))
        with mock.patch.object(sources, "get", side_effect=[page(100, 5000)] * 10):
            jobs = sources.board("smartrecruiters", "giant")
        self.assertEqual(len(jobs), 1000)
        self.assertTrue(all(j["partial"] for j in jobs))
        self.assertEqual(jobs[0]["board"], "smartrecruiters:giant")

    def test_personio_xml(self):
        xml = """<workzag-jobs><position><id>42</id><subcompany>Acme GmbH</subcompany><office>Berlin</office>
        <additionalOffices><office>Munich</office></additionalOffices><name>CRM Manager</name>
        <jobDescriptions><jobDescription><name>Your tasks</name><value><![CDATA[<p>Own Klaviyo.</p>]]></value>
        </jobDescription></jobDescriptions><createdAt>2026-09-30T10:00:00+00:00</createdAt></position></workzag-jobs>"""
        with mock.patch.object(sources, "get", return_value=Raw(xml)):
            j = sources.board("personio", "acme")[0]
        self.assertEqual((j["company"], j["location"], j["posted"]), ("Acme GmbH", "Berlin / Munich", "2026-09-30"))
        self.assertEqual(j["url"], "https://acme.jobs.personio.de/job/42")
        self.assertIn("Own Klaviyo.", j["desc"])

    def test_teamtailor_rss(self):
        rss = """<rss xmlns:tt="https://teamtailor.com/locations"><channel><item><title>CRM Manager</title>
        <link>https://acme.teamtailor.com/jobs/1</link><description>&lt;p&gt;Hi&lt;/p&gt;</description>
        <pubDate>Tue, 29 Sep 2026 10:00:00 +0000</pubDate><remoteStatus>fully</remoteStatus>
        <tt:locations><tt:location><tt:city>Amsterdam</tt:city><tt:country>Netherlands</tt:country></tt:location>
        </tt:locations></item></channel></rss>"""
        with mock.patch.object(sources, "get", return_value=Raw(rss)):
            j = sources.board("teamtailor", "acme")[0]
        self.assertEqual(j["location"], "Amsterdam, Netherlands (Remote)")
        self.assertEqual((j["posted"], j["desc"]), ("2026-09-29", "Hi"))

    def test_broken_feeds_and_boards_return_nothing(self):
        with mock.patch.object(sources, "get", return_value=Raw("<html>not xml")):
            self.assertEqual(sources.board("personio", "x"), [])
        with mock.patch.object(sources, "get", return_value=Resp({"jobs": "surprise"})), mock.patch.object(sources, "log"):
            self.assertEqual(sources.board("greenhouse", "x"), [])       # shape changed: logged, not raised

    def test_workday_search_detail_and_vague_location(self):
        listing = {"total": 2, "jobPostings": [
            {"title": "CRM Manager", "externalPath": "/job/Toronto/CRM-Manager_R1", "locationsText": "Toronto, ON",
             "postedOn": "Posted 2 Days Ago"},
            {"title": "Lifecycle Marketing Lead", "externalPath": "/job/x/Lead_R2", "locationsText": "3 Locations",
             "postedOn": "Posted Today"}]}
        with mock.patch.object(sources, "post", return_value=Resp(listing)) as po:
            jobs = sources.board("workday", "https://acme.wd5.myworkdayjobs.com/en-US/External/", ["crm"])
        self.assertEqual(po.call_args.args[0], "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/External/jobs")
        self.assertEqual(po.call_args.args[1]["searchText"], "crm")
        a, b = jobs
        self.assertEqual(a["url"], "https://acme.wd5.myworkdayjobs.com/External/job/Toronto/CRM-Manager_R1")
        self.assertEqual(a["posted"], (TODAY - datetime.timedelta(days=2)).isoformat())
        self.assertFalse(a["vague_location"])
        self.assertTrue(b["vague_location"])
        detail = {"jobPostingInfo": {"jobDescription": "<p>Visa sponsorship available.</p>", "location": "Paris",
                                     "additionalLocations": ["Toronto, ON"], "startDate": "2026-10-01"}}
        p = make_home()
        from huntline import scout
        from huntline.sponsors import Sponsors
        s = p["search"]
        res = scout.words_re(s["include"]), scout.words_re(s["exclude"]), scout.words_re(s["keywords"])
        with mock.patch.object(sources, "get", return_value=Resp(detail)):
            row = scout.evaluate(p, b, Sponsors(p["_home"], []), *res)
        self.assertEqual(row["country"], "canada")           # found among the detail's locations
        self.assertIn("Visa sponsorship", row["desc"])

    def test_workday_bad_slug(self):
        with mock.patch.object(sources, "log"):
            self.assertEqual(sources.board("workday", "not a workday url"), [])

    def test_posted_ago(self):
        self.assertEqual(sources.posted_ago("Posted Yesterday"), (TODAY - datetime.timedelta(days=1)).isoformat())
        self.assertEqual(sources.posted_ago("Posted 30+ Days Ago"), (TODAY - datetime.timedelta(days=31)).isoformat())
        self.assertEqual(sources.posted_ago(None), "")


class Requests(unittest.TestCase):
    def test_final_answers_are_not_retried_and_busy_ones_are(self):
        with mock.patch.object(sources.requests, "request", return_value=Raw("", 403)) as r, \
                mock.patch.object(sources.time, "sleep") as sl:
            self.assertIsNone(sources.get("https://x"))
        self.assertEqual(r.call_count, 1)
        sl.assert_not_called()
        busy = [Raw("", 429, {"Retry-After": "2"}), Raw("", 503), Raw("ok")]
        with mock.patch.object(sources.requests, "request", side_effect=busy) as r, \
                mock.patch.object(sources.time, "sleep") as sl:
            self.assertEqual(sources.get("https://x").text, "ok")
        self.assertEqual(r.call_count, 3)
        self.assertEqual(sl.call_args_list[0].args[0], 2)               # honoured Retry-After

    def test_network_errors_back_off_but_not_after_last_try(self):
        with mock.patch.object(sources.requests, "request", side_effect=requests.ConnectionError), \
                mock.patch.object(sources.time, "sleep") as sl, mock.patch.object(sources, "log"):
            self.assertIsNone(sources.get("https://x", tries=3))
        self.assertEqual(sl.call_count, 2)


class Dates(unittest.TestCase):
    def test_no_date_is_not_1970(self):
        self.assertEqual(store.iso_date(0), "")
        self.assertEqual(store.iso_date("0"), "")
        self.assertEqual(store.iso_date("20260304"), "2026-03-04")


class Ids(unittest.TestCase):
    def test_prefixes(self):
        db = store.connect(Path(tempfile.mkdtemp()))
        for i in ("ab12cd34", "ab99ef00", "a%cdef12"):
            db.execute("INSERT INTO jobs (id) VALUES (?)", (i,))
        self.assertEqual(store.find_ids(db, "ab"), ["ab12cd34", "ab99ef00"])
        self.assertEqual(store.find_id(db, "AB1"), "ab12cd34")
        self.assertEqual(store.find_ids(db, "a%"), ["a%cdef12"])          # % is a character, not a wildcard
        self.assertEqual(store.find_ids(db, ""), [])

    def test_cli_explains_ambiguous_ids(self):
        p = make_home()
        db = store.connect(p["_home"])
        for i in ("ab12cd34", "ab99ef00"):
            db.execute("INSERT INTO jobs (id, title, company) VALUES (?, 't', 'c')", (i,))
        db.commit()
        with self.assertRaises(SystemExit) as e:
            cli.main(["--home", p["_home"], "show", "ab"])
        self.assertIn("matches 2 jobs", str(e.exception))


class Profile(unittest.TestCase):
    def test_forgiving_lists_and_clear_errors(self):
        home = Path(tempfile.mkdtemp())
        (home / "profile.yaml").write_text("search:\n  keywords: crm, lifecycle\n  countries: Canada, UK\n", encoding="utf-8")
        p = profile.load(home)
        self.assertEqual(p["search"]["countries"], ["canada", "uk"])
        self.assertEqual(p["search"]["keywords"], ["crm", "lifecycle"])
        (home / "profile.yaml").write_text("search:\n  keywords: [crm]\n  countries: [canda]\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as e:
            profile.load(home)
        self.assertIn("canda", str(e.exception))


class Taste(unittest.TestCase):
    def setUp(self):
        self.db = store.connect(Path(tempfile.mkdtemp()))
        n = 0
        for status, titles in (("applied", ["CRM Marketing Manager", "Lifecycle CRM Lead", "CRM Specialist"]),
                               ("skip", ["Social Media Manager", "Social Media Coordinator", "Events Manager"]),
                               ("rejected", ["CRM Analyst"] * 3)):
            for t in titles:
                n += 1
                self.db.execute("INSERT INTO jobs (id, title, company, country, status, score) VALUES (?,?,?,?,?,50)",
                                (f"x{n}", t, f"Co{n}", "canada", status))
        for i, t in (("n1", "CRM Manager"), ("n2", "Social Media Lead")):
            self.db.execute("INSERT INTO jobs (id, title, company, country, status, score) VALUES (?,?,?,?,?,95)",
                            (i, t, "New Co", "canada", "new"))

    def test_learns_and_nudges_within_bounds(self):
        t = learn.Taste(self.db)
        self.assertTrue(t.ready)
        self.assertEqual((t.n_like, t.n_skip), (3, 3))                 # rejected teaches nothing
        likes, dislikes = t.top()
        self.assertIn("crm", likes)
        self.assertIn("social", dislikes)
        self.assertGreater(t.of({"title": "CRM Manager"}), 0)
        self.assertLess(t.of({"title": "Social Media Lead"}), 0)
        learn.apply(self.db, t)
        rows = {r["id"]: dict(r) for r in self.db.execute("SELECT * FROM jobs WHERE status='new'")}
        self.assertEqual(rows["n1"]["base"], 95)
        self.assertLessEqual(rows["n1"]["score"], 100)                 # clamped
        self.assertLess(rows["n2"]["score"], 95)
        self.assertLessEqual(abs(rows["n2"]["taste"]), learn.TASTE_MAX)
        learn.apply(self.db, t)                                        # idempotent: base never drifts
        self.assertEqual(self.db.execute("SELECT base FROM jobs WHERE id='n2'").fetchone()[0], 95)

    def test_waits_for_enough_choices(self):
        self.db.execute("DELETE FROM jobs WHERE status='skip' AND title LIKE 'Events%'")
        t = learn.Taste(self.db)
        self.assertFalse(t.ready)
        self.assertEqual(t.of({"title": "Social Media Lead"}), 0)


class Prep(unittest.TestCase):
    DESC = ("Requirements: • 5+ years of experience in lifecycle marketing. • Hands-on experience with Klaviyo or "
            "HubSpot email flows and lead scoring. • Strong SQL skills for reporting in Looker Studio. "
            "• Fluent Spanish is a plus. • Experience managing a team of 10 designers. We offer great benefits. "
            "We are an equal opportunity employer and value diversity.")

    def setUp(self):
        self.p = make_home(years_experience=3)
        self.r = profile.load_resume(self.p)
        self.job = {"title": "CRM Manager", "company": "Acme", "location": "Toronto", "url": "https://x",
                    "desc": self.DESC, "salary_lo": 70000, "salary_hi": 85000, "posted": "", "visa": "", "ai_fit": None}

    def test_requirements_extracted_without_employer_boilerplate(self):
        asks = prep.asks(self.DESC)
        self.assertTrue(any("Klaviyo" in a for a in asks))
        self.assertFalse(any("equal opportunity" in a or "benefits" in a for a in asks))

    def test_evidence_is_always_your_own_words(self):
        md = prep.notes(self.p, self.r, self.job)
        mine = [str(b) for j in self.r["experience"] for b in j["bullets"]] + \
               [f"{k}: {v}" for k, v in self.r["skills"].items()] + [self.r["additional"]] + \
               [str(c) for c in self.r["certifications"]] + [f"{x['name']}: {x['text']}" for x in self.r["projects"]]
        proofs = [line.split("Your proof: ", 1)[1].rsplit(" _(", 1)[0] for line in md.splitlines() if "Your proof: " in line]
        self.assertGreaterEqual(len(proofs), 3)
        for proof in proofs:
            self.assertIn(proof, mine)
        self.assertIn("Spanish (conversational)", md)                   # found outside the work history
        self.assertIn("No bullet in your resume covers this", md)       # 10 designers: an honest gap
        self.assertIn("They ask for 5+ years; you have 3", md)
        self.assertIn("hubspot, klaviyo, looker studio, sql", md)

    def test_field_words_are_not_evidence(self):
        self.assertIsNone(prep.evidence(self.r, "Deep experience in marketing"))

    def test_write_and_ai_section(self):
        with mock.patch("huntline.ai.chat", return_value="### Why CRM?\n- Because Klaviyo."):
            out = prep.write(self.p, self.r, self.job, use_ai=True)
        text = out.read_text(encoding="utf-8")
        self.assertTrue(out.name.endswith(".md") and out.parent.name == "prep")
        self.assertIn("AI draft, check every claim", text)


class AIRobustness(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict("os.environ", {"OPENAI_API_KEY": "k"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_backs_off_then_answers(self):
        ok = Raw(json.dumps({"choices": [{"message": {"content": "<think>hm</think>Hello"}}]}))
        with mock.patch.object(ai.requests, "post", side_effect=[Raw("", 429), Raw("", 503), ok]) as po, \
                mock.patch.object(ai.time, "sleep"):
            self.assertEqual(ai.chat("hi"), "Hello")
        self.assertEqual(po.call_count, 3)

    def test_json_mode_falls_back_and_bad_key_is_clear(self):
        ok = Raw(json.dumps({"choices": [{"message": {"content": "{}"}}]}))
        with mock.patch.object(ai.requests, "post", side_effect=[Raw("", 400), ok]) as po:
            ai.chat("hi", json_mode=True)
        self.assertNotIn("response_format", po.call_args.kwargs["json"])
        with mock.patch.object(ai.requests, "post", return_value=Raw("", 401)), self.assertRaises(SystemExit):
            ai.chat("hi")

    def test_rank_survives_one_bad_answer(self):
        p = make_home()
        db = store.connect(p["_home"])
        for i, s in (("a", 90), ("b", 80)):
            db.execute("INSERT INTO jobs (id, title, company, location, score, status) VALUES (?,?,?,?,?, 'new')",
                       (i, "CRM", "Co", "X", s))
        db.commit()
        answers = iter(['{"fit": 70, "why": "ok", "gaps": ""}', "I cannot comply"])
        with mock.patch.object(ai, "chat", side_effect=lambda *a, **k: next(answers)), mock.patch("builtins.print"):
            done = ai.rank(p, db, {}, workers=1)
        self.assertEqual(len(done), 1)


class ServeHardening(unittest.TestCase):
    def setUp(self):
        self.p = make_home()
        db = store.connect(self.p["_home"])
        db.execute("INSERT INTO jobs (id, title, company, status, desc) VALUES "
                   "('j1','CRM Manager','Acme','new','5+ years of experience with Klaviyo flows.')")
        db.commit()
        from http.server import ThreadingHTTPServer
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), serve.handler(self.p, "tok"))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        out = r.status, r.read().decode()
        c.close()
        return out

    def test_dns_rebinding_hosts_are_refused(self):
        self.assertEqual(self.req("GET", "/", headers={"Host": "evil.example:1234"})[0], 403)
        self.assertEqual(self.req("POST", "/api/status", json.dumps({"id": "j1", "status": "skip"}),
                                  {"Host": "evil.example", "X-Huntline-Token": "tok"})[0], 403)
        self.assertEqual(self.req("GET", "/", headers={"Host": f"localhost:{self.port}"})[0], 200)

    def test_bad_bodies(self):
        h = {"X-Huntline-Token": "tok", "Content-Type": "application/json"}
        self.assertEqual(self.req("POST", "/api/status", "x" * 20_000, h)[0], 413)
        self.assertEqual(self.req("POST", "/api/status", "[1, 2]", h)[0], 400)
        self.assertEqual(self.req("POST", "/api/nope", json.dumps({"id": "j1"}), h)[0], 404)

    def test_prep_button(self):
        code, body = self.req("POST", "/api/prep", json.dumps({"id": "j1"}), {"X-Huntline-Token": "tok"})
        self.assertEqual(code, 200)
        f = json.loads(body)["file"]
        self.assertTrue(f.startswith("/files/prep/") and f.endswith(".md"))
        code, text = self.req("GET", f)
        self.assertEqual(code, 200)
        self.assertIn("Interview prep: CRM Manager at Acme", text)

    def test_port_in_use_is_explained(self):
        with self.assertRaises(SystemExit) as e:
            serve.run(self.p, self.port, open_browser=False)
        self.assertIn("--port", str(e.exception))



class Encoding(unittest.TestCase):
    def test_pdf_html_is_utf8_whatever_the_system_encoding(self):
        """Windows defaults to cp1252; Chrome reads the page as UTF-8. Simulate with an ASCII locale."""
        import os
        import subprocess
        import sys
        import textwrap
        out = tempfile.mkdtemp()
        script = textwrap.dedent("""
            import sys
            from pathlib import Path
            from unittest import mock
            from huntline import pdf
            seen = {}
            def run(cmd, **kw):
                seen["b"] = Path(cmd[-1].removeprefix("file://")).read_bytes()
                Path(cmd[-2].split("=", 1)[1]).write_bytes(b"%PDF" + b"x" * 3000)
            with mock.patch.object(pdf, "browser", return_value="chrome"), mock.patch.object(pdf.subprocess, "run", run):
                pdf.render("<p>Sam Rivera \\u00b7 \\u0141\\u00f3d\\u017a</p>", Path(sys.argv[1]) / "x.pdf")
            sys.exit(0 if "\\u0141\\u00f3d\\u017a".encode() in seen["b"] else 3)
        """)
        env = {**os.environ, "LC_ALL": "C", "LANG": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"}
        r = subprocess.run([sys.executable, "-X", "utf8=0", "-c", script, out], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
