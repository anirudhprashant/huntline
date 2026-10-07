import tempfile
import unittest
from pathlib import Path

import yaml

from huntline import profile, resume, scout
from huntline.countries import country_of
from huntline.sponsors import Sponsors

DATA = Path(profile.__file__).parent / "data"


class Basics(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        p = yaml.safe_load((DATA / "profile.example.yaml").read_text(encoding="utf-8"))
        p["search"]["needs_sponsorship"] = True
        (self.home / "profile.yaml").write_text(yaml.safe_dump(p), encoding="utf-8")
        (self.home / "resume.yaml").write_text((DATA / "resume.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        self.p = profile.load(self.home)

    def test_remote_tied_to_other_country_is_dropped(self):
        n = ["canada", "remote"]
        self.assertEqual(country_of("Remote", n), "remote")
        self.assertEqual(country_of("Remote (US only)", n), "")
        self.assertEqual(country_of("Toronto, ON", n), "canada")

    def test_sponsorship_refusal_is_dropped(self):
        s = self.p["search"]
        inc, exc, kw = scout.words_re(s["include"]), scout.words_re(s["exclude"]), scout.words_re(s["keywords"])
        base = {"title": "CRM Marketing Manager", "company": "Acme", "location": "Toronto", "url": "u",
                "lo": None, "hi": None, "source": "greenhouse"}
        sp = Sponsors(self.home, [])
        self.assertIsNone(scout.evaluate(self.p, {**base, "desc": "We cannot sponsor visas."}, sp, inc, exc, kw))
        row = scout.evaluate(self.p, {**base, "desc": "Visa sponsorship available."}, sp, inc, exc, kw)
        self.assertEqual(row["tier"], 2)

    def test_tailoring_never_adds_text(self):
        r = profile.load_resume(self.p)
        html = resume.build_html(self.p, r, "SEO Manager", "technical seo audits")
        for j in r["experience"]:
            for b in j["bullets"]:
                self.assertIn(b.split("**")[0][:30], html)
        seo = html.index("technical SEO audits")
        self.assertLess(html.index("Sample Agency"), html.index("Sample Agency") + 1)
        self.assertGreater(seo, 0)


if __name__ == "__main__":
    unittest.main()
