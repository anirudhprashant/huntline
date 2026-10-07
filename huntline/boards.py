"""Finds employer job boards that have live roles in your countries.

Direct ATS boards (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Personio,
Teamtailor) are the best job source there is: the real employer, the full description, no
rate limits. This probes company names across all of them and keeps the ones that answer.
(Workday can't be guessed from a name; paste a Workday careers URL into profile.yaml instead.)

    huntline boards                      probe the bundled company list
    huntline boards --companies a.txt    probe your own list, one company per line
"""
import concurrent.futures as cf
import json
import re
from pathlib import Path

from .countries import loc_regex
from .sources import ATS_URLS, board


def probe(ats, slug, where):
    jobs = board(ats, slug)
    hits = sum(1 for j in jobs if where.search(j["location"] or ""))
    return {"ats": ats, "slug": slug, "total": len(jobs), "hits": hits} if jobs else None


def run(p, companies_file=None, workers=16):
    names = set()
    if companies_file:
        names = {l.strip() for l in Path(companies_file).read_text(encoding="utf-8").splitlines() if l.strip()}
    else:
        bundled = json.loads((Path(__file__).parent / "data" / "boards.json").read_text(encoding="utf-8"))["boards"]
        names = {s for v in bundled.values() for s in v}
    slugs = sorted({re.sub(r"[^a-z0-9-]", "", n.lower().replace(" ", "")) for n in names} - {""})
    where = loc_regex(p["search"]["countries"])
    tasks = [(a, s) for s in slugs for a in ATS_URLS]
    print(f"probing {len(slugs)} companies x {len(ATS_URLS)} platforms ...")
    best = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(lambda t: probe(*t, where), tasks):
            if res and res["hits"] and (res["slug"] not in best or res["hits"] > best[res["slug"]]["hits"]):
                best[res["slug"]] = res
    out = {}
    for h in best.values():
        out.setdefault(h["ats"], []).append(h["slug"])
    f = Path(p["_home"]) / "boards.json"
    f.write_text(json.dumps({"boards": {k: sorted(v) for k, v in out.items()}}, indent=1), encoding="utf-8")
    print(f"{len(best)} boards with {sum(h['hits'] for h in best.values())} roles in your countries -> {f}")
