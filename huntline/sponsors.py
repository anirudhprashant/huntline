"""Official government lists of employers that sponsor foreign workers.

  uk          Home Office register of licensed sponsors (workers), daily CSV
  netherlands IND public register of recognised sponsors
  canada      ESDC positive LMIA employer lists, last 4 published quarters

Each list is downloaded once a week and cached in the huntline home folder. If a download
fails the stale cache is used, so a government site outage never breaks a run.
"""
import html
import io
import json
import re
import sys
import time
from pathlib import Path

from .sources import get

WEEK = 7 * 86400


def norm_co(name):
    n = html.unescape(name or "").lower()
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\b(inc|incorporated|ltd|limited|plc|llp|llc|lp|ulc|corp|corporation|co|company|gmbh|ag|"
               r"b ?v|n ?v|s ?a|the|holdings?|group|international|uk|canada|nederland|netherlands|europe|emea)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _cached(home, name, fetch, min_size):
    f = Path(home) / "cache" / f"sponsors_{name}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(f.read_text()) if f.exists() else {}
    if time.time() - cache.get("ts", 0) < WEEK:
        return set(cache["names"])
    try:
        names = fetch()
        if len(names) >= min_size:      # far fewer means the page changed shape; keep the old list
            f.write_text(json.dumps({"ts": time.time(), "names": sorted(names)}))
            return names
        print(f"  [sponsors {name}] only {len(names)} parsed, using cache", file=sys.stderr)
    except Exception as e:
        print(f"  [sponsors {name}] {type(e).__name__}: {e}", file=sys.stderr)
    return set(cache.get("names", []))


def _uk():
    import csv
    page = get("https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers")
    m = re.search(r'href="(https://assets\.publishing\.service\.gov\.uk/[^"]+\.csv)"', page.text if page else "")
    r = get(m.group(1)) if m else None
    rows = csv.reader(io.StringIO(r.content.decode("utf-8-sig", "replace"))) if r else []
    return {n for n in (norm_co(row[0]) for row in rows if row) if len(n) > 2}


def _nl():
    r = get("https://ind.nl/en/public-register-recognised-sponsors/public-register-work")
    rows = re.findall(r'<th[^>]*scope=["\']?row["\']?[^>]*>([\s\S]*?)</th>', r.text if r else "", re.I)
    return {n for n in (norm_co(re.sub(r"<[^>]+>", "", m)) for m in rows) if len(n) > 2}


def _ca():
    import openpyxl
    pkg = get("https://open.canada.ca/data/api/action/package_show?id=90fed587-1364-4f33-a9ee-208181dc0b97").json()
    urls = sorted((r["url"] for r in pkg["result"]["resources"] if re.search(r"_en\.xlsx$", r["url"])),
                  key=lambda u: u.rsplit("/", 1)[-1])[-4:]
    names = set()
    for u in urls:
        r = get(u)
        body = r.content if r else b""
        if not body.startswith(b"PK"):     # open.canada sometimes serves an HTML page linking the real file
            m = re.search(rb'href="(https://[^"]+\.xlsx)"', body)
            r = get(html.unescape(m.group(1).decode())) if m else None
            body = r.content if r else b""
        if body.startswith(b"PK"):
            ws = openpyxl.load_workbook(io.BytesIO(body), read_only=True).active
            for row in ws.iter_rows(min_row=3, values_only=True):
                if row and len(row) > 2 and row[2]:
                    n = norm_co(str(row[2]))
                    if len(n) > 3 and not n.split()[0].isdigit():
                        names.add(n)
        time.sleep(2)
    return names


REGISTERS = {"uk": (_uk, 20000, "UK licensed sponsor"),
             "netherlands": (_nl, 5000, "IND recognised sponsor"),
             "canada": (_ca, 3000, "had a positive LMIA in the last year")}


class Sponsors:
    def __init__(self, home, countries):
        self.sets = {c: _cached(home, c, REGISTERS[c][0], REGISTERS[c][1]) for c in countries if c in REGISTERS}

    def check(self, company, country):
        """Label if this company is on the country's official sponsor list, else ''."""
        s, c = self.sets.get(country), norm_co(company)
        if not s or len(c) < 3:
            return ""
        if c in s or (len(c) >= 8 and any(n.startswith(c + " ") for n in s)):
            return REGISTERS[country][2]
        return ""
