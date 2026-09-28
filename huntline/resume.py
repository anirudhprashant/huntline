"""Builds a resume tailored to one job, without inventing anything.

Tailoring only SELECTS and ORDERS what is already in your resume.yaml: which headline
fits, which bullet leads each role, which skill line comes first. No text is generated,
so a tailored resume can never claim something your real one does not.
"""
import html
import re

from .pdf import pages, render

STOP = set("and the for with you our will role job team work this that are who have your from into about "
           "their they them what when where which while able must should across within".split())


def words(text):
    return {w for w in re.findall(r"[a-z][a-z0-9+#.-]{2,}", (text or "").lower()) if w not in STOP}


def rank(items, query, text):
    """Most relevant first. Equal scores keep your original order, which was already deliberate."""
    q = words(query)
    return sorted(items, key=lambda it: -len(q & words(text(it))))


def pick_headline(r, query):
    """Choose among your own headline variants by which one's `match` words appear most."""
    best, score = None, 0
    for v in r.get("variants") or []:
        n = sum(len(re.findall(rf"\b{re.escape(w)}", query, re.I)) for w in v.get("match", []))
        if n > score:
            best, score = v, n
    return (best or {}).get("headline") or r.get("headline", ""), (best or {}).get("summary") or r.get("summary", "")


e = lambda s: html.escape(str(s or ""))
# Allow **bold** inside bullets, nothing else.
rich = lambda s: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e(s))


def build_html(p, r, title="", desc=""):
    q = f"{title} {title} {desc}"
    headline, summary = pick_headline(r, q)
    contact = " | ".join(e(x) for x in (p.get("city"), p.get("phone"), p.get("email")) if x)
    links = " | ".join(f'<a href="https://{e(l.removeprefix("https://"))}">{e(l.removeprefix("https://"))}</a>'
                       for l in p.get("links") or [])
    jobs = ""
    for j in r.get("experience") or []:
        lis = "".join(f"<li>{rich(b)}</li>" for b in rank(j.get("bullets") or [], q, str))
        jobs += (f'<div class="job"><div class="hd"><span>{e(j.get("company"))}</span><span>{e(j.get("dates"))}</span></div>'
                 f'<div class="sub"><span>{e(j.get("title"))}</span><span>{e(j.get("location"))}</span></div><ul>{lis}</ul></div>')
    skills = "".join(f"<p><b>{e(k)}:</b> {e(v)}</p>"
                     for k, v in rank(list((r.get("skills") or {}).items()), q, lambda kv: f"{kv[0]} {kv[1]}"))
    projects = "".join(f"<p><b>{e(x.get('name'))}</b>: {rich(x.get('text'))}</p>"
                       for x in rank(r.get("projects") or [], q, lambda x: f"{x.get('name')} {x.get('text')}"))
    edu = "".join(f'<div class="hd"><span>{e(x.get("degree"))}</span><span>{e(x.get("dates"))}</span></div>'
                  f'<p>{e(x.get("school"))}</p>' for x in r.get("education") or [])
    certs = "".join(f"<p>{e(c)}</p>" for c in r.get("certifications") or [])
    highlights = f'<p class="hl">{rich(r["highlights"])}</p>' if r.get("highlights") else ""
    sec = lambda name, body: f"<h2>{name}</h2>{body}" if body else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(p.get('name'))} - Resume</title>
<style>
@page{{size:{r.get('paper', 'A4')};margin:0.55in 0.6in}}*{{box-sizing:border-box}}
body{{margin:0;font-family:Carlito,Calibri,"Helvetica Neue",Arial,sans-serif;color:#1b1b1b;font-size:10pt;line-height:1.3}}
h1{{font-size:21pt;margin:0;letter-spacing:.02em}}.role{{font-size:11pt;font-weight:600;color:#1f4e79;margin:1pt 0 3pt}}
.contact{{font-size:9.5pt;color:#333}}.contact a{{color:#333;text-decoration:none}}
h2{{font-size:10.5pt;text-transform:uppercase;letter-spacing:.08em;color:#1f4e79;border-bottom:1.2px solid #1f4e79;margin:10pt 0 4pt;padding-bottom:1pt}}
.hl{{background:#f2f6fa;border-left:3px solid #1f4e79;padding:5pt 8pt;font-size:9.5pt}}.hl b{{color:#1f4e79}}
.job{{margin:0 0 6pt;break-inside:avoid}}.hd{{display:flex;justify-content:space-between;gap:12px;font-weight:700}}
.sub{{display:flex;justify-content:space-between;gap:12px;font-style:italic;color:#444;font-size:9.5pt}}
ul{{margin:2pt 0 0;padding-left:15px}}li{{margin:0 0 1.5pt}}p{{margin:0 0 3pt}}
</style></head><body>
<h1>{e(p.get('name', '')).upper()}</h1><div class="role">{e(headline)}</div>
<div class="contact">{contact}{'<br>' + links if links else ''}</div>
{sec('Summary', f'<p>{rich(summary)}</p>' if summary else '')}{highlights}
{sec('Experience', jobs)}{sec('Skills', skills)}{sec('Projects', projects)}
{sec('Education', edu)}{sec('Certifications', certs)}
{sec('Additional', f"<p>{rich(r.get('additional'))}</p>" if r.get('additional') else '')}
</body></html>"""


def build(p, r, out, title="", desc=""):
    pdf = render(build_html(p, r, title, desc), out)
    n = pages(pdf)
    limit = r.get("max_pages", 2)
    if n > limit:
        print(f"  note: resume is {n} pages (max_pages is {limit}). Trim bullets rather than shrinking type.")
    return pdf
