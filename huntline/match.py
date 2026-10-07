"""How well a posting fits YOU, read from your resume.yaml rather than your search keywords.

Keywords find a job; the resume decides whether you could do it. Two signals:

  tools     skills you list (HubSpot, SQL, Figma...) that the posting names
  language  how much of your experience's vocabulary the posting shares

And one hard filter: postings that demand far more years of experience than you have.
"""
import re

from .resume import STOP, words

NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
       "ten": 10, "twelve": 12, "fifteen": 15}
# "5+ years of experience", "3-5 years' experience", "minimum of 7 years in product marketing experience"
YEARS = re.compile(r"\b(\d{1,2}|" + "|".join(NUM) + r")\s*\+?\s*(?:(?:-|to|–)\s*\d{1,2}\s*\+?\s*)?"
                   r"(?:years?|yrs?)'?(?:\s+of)?(?:\s+[\w/&-]+){0,4}?\s+experience", re.I)
# Skill entries that say how well, not what: "SQL (basics)", "French (conversational)".
QUALIFIER = re.compile(r"\(.*?\)|\b(basics?|basic|familiar(ity)?|exposure|conversational|working knowledge)\b", re.I)


class Fit:
    def __init__(self, resume):
        r = resume or {}
        self.tools = set()
        for k, v in (r.get("skills") or {}).items():
            for t in re.split(r"[,;/·|]", f"{v}"):
                t = re.sub(r"\s+", " ", QUALIFIER.sub("", t)).strip().lower()
                if len(t) >= 2 and t not in STOP:
                    self.tools.add(t)
        text = " ".join([str(r.get("headline") or ""), str(r.get("summary") or "")] +
                        [str(b) for j in r.get("experience") or [] for b in (j.get("bullets") or [])] +
                        [str(j.get("title") or "") for j in r.get("experience") or []] +
                        [f"{x.get('name')} {x.get('text')}" for x in r.get("projects") or []])
        self.vocab = words(re.sub(r"\*\*", "", text)) | {w for t in self.tools for w in words(t)}
        self._tool_re = {t: re.compile(r"(?<![\w+#])" + re.escape(t) + r"(?![\w+#])", re.I) for t in self.tools}

    def tools_in(self, desc):
        return sorted(t for t, rx in self._tool_re.items() if rx.search(desc or ""))

    def score(self, desc):
        """0-100. Empty when there is nothing to compare."""
        if not desc or not (self.tools or self.vocab):
            return 0
        tool_pts = min(60, 15 * len(self.tools_in(desc)))
        dw = words(desc)
        shared = len(dw & self.vocab) / max(12, min(len(dw), 120))
        return min(100, tool_pts + round(min(1.0, shared * 2.5) * 40))


def years_required(desc):
    """The largest "N years of experience" a posting asks for, or None. Ranges count from their low end."""
    found = []
    for m in YEARS.finditer(desc or ""):
        n = m.group(1).lower()
        n = int(n) if n.isdigit() else NUM[n]
        if 0 < n <= 20:
            found.append(n)
    return max(found) if found else None
