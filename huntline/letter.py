"""Cover letters as a clean one-page PDF.

`huntline letter <job-id>` writes out/letters/<slug>.txt from your template, filling in
the company, the role and your three most relevant resume bullets. Edit the .txt if you
like, then `huntline pdf <file.txt>` re-renders it. With --ai and an OpenAI-compatible
key set, a model drafts the body using only facts from your resume.yaml.

.txt format:
    company: Acme Ltd
    role: Marketing Manager
    ---
    Dear Hiring Team,

    Paragraph. A blank line separates paragraphs.

    - bullet lines start with "- "; **bold** is allowed

    Kind regards,
"""
import datetime
import html
import json
import os
import re
from pathlib import Path

import requests

from .pdf import pages, render
from .resume import rank

DEFAULT_BODY = """{greeting}

I'm applying for the {role} role at {company}. {pitch}

A few things I've done that match what you're looking for:

{proof}

I'd welcome the chance to talk about how I could help {company}. My resume is attached.

{signoff}"""


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def facts(r):
    return [b for j in r.get("experience") or [] for b in j.get("bullets") or []]


def ai_body(p, r, job):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("--ai needs OPENAI_API_KEY (any OpenAI-compatible provider; set OPENAI_BASE_URL for others)")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    prompt = (f"Write the body of a cover letter, 180-260 words, for {p['name']} applying to '{job['title']}' "
              f"at {job['company']}.\nRULES: use ONLY facts from the resume below; never invent numbers, employers, "
              f"tools or credentials. Plain, specific, no cliches, no em dashes. Start with the greeting "
              f"'{p['letter']['greeting']}' and end with '{p['letter']['signoff']}'. You may include one list of "
              f"2-3 bullets starting with '- '. Output only the letter text.\n\n"
              f"RESUME:\n{json.dumps(r, ensure_ascii=False)[:8000]}\n\nJOB POSTING:\n{(job.get('desc') or '')[:5000]}")
    res = requests.post(f"{base}/chat/completions", timeout=120,
                        headers={"Authorization": f"Bearer {key}"},
                        json={"model": os.environ.get("HUNTLINE_MODEL", "gpt-4o-mini"),
                              "messages": [{"role": "user", "content": prompt}]})
    res.raise_for_status()
    text = res.json()["choices"][0]["message"]["content"]
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def draft(p, r, job, use_ai=False):
    if use_ai:
        body = ai_body(p, r, job)
    else:
        q = f"{job['title']} {job['title']} {job.get('desc', '')}"
        proof = "\n".join(f"- {b}" for b in rank(facts(r), q, str)[:3])
        body = (p["letter"].get("body") or DEFAULT_BODY).format(
            greeting=p["letter"]["greeting"], signoff=p["letter"]["signoff"], role=job["title"],
            company=job["company"], pitch=p["letter"].get("pitch", r.get("summary", "")), proof=proof)
    src = Path(p["_home"]) / "out" / "letters" / f"{slug(job['company'] + '-' + job['title'])}.txt"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(f"company: {job['company']}\nrole: {job['title']}\n---\n{body}\n")
    return src


def inline(s):
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(s))


def build(p, src):
    src = Path(src)
    head, _, body = src.read_text().partition("\n---\n")
    meta = {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in head.splitlines() if ":" in l)}
    parts = []
    for block in re.split(r"\n\s*\n", body.strip()):
        lines = [l.rstrip() for l in block.splitlines() if l.strip()]
        if lines and all(l.startswith("- ") for l in lines):
            parts.append("<ul>" + "".join(f"<li>{inline(l[2:])}</li>" for l in lines) + "</ul>")
        elif lines:
            parts.append(f"<p>{inline(' '.join(lines))}</p>")
    name = html.escape(p.get("name", ""))
    contact = " | ".join(html.escape(x) for x in (p.get("city"), p.get("phone"), p.get("email")) if x)
    links = " | ".join(html.escape(l.removeprefix("https://")) for l in p.get("links") or [])
    date = meta.get("date") or datetime.date.today().strftime("%d %B %Y").lstrip("0")
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>{name} - Cover Letter</title><style>
@page{{size:A4;margin:0}}*{{box-sizing:border-box}}
body{{margin:0;font-family:Georgia,"Liberation Serif","Times New Roman",serif;color:#1a1a1a;font-size:10.6pt;line-height:1.5}}
.page{{width:210mm;min-height:297mm;padding:18mm 22mm 16mm;position:relative}}
.band{{position:absolute;top:0;left:0;right:0;height:5mm;background:#0b2545}}
header{{text-align:center;padding-bottom:7pt;border-bottom:1.2px solid #0b2545;margin-bottom:16pt}}
h1{{font-size:22pt;margin:0 0 3pt;letter-spacing:.08em;text-transform:uppercase;color:#0b2545}}
.contact{{font-size:9.2pt;color:#444}}.meta{{display:flex;justify-content:space-between;margin-bottom:14pt;font-size:10pt}}
.re{{font-weight:700;color:#0b2545;margin:0 0 12pt}}p{{margin:0 0 9pt}}b{{color:#0b2545}}
ul{{margin:0 0 10pt;padding:6pt 10pt 6pt 24pt;border-left:3px solid #0b2545;background:#f1f4f8}}li{{margin:0 0 3pt}}
.sig{{font-weight:700;color:#0b2545;font-size:11.5pt}}
</style></head><body><div class="page"><div class="band"></div>
<header><h1>{name}</h1><div class="contact">{contact}<br>{links}</div></header>
<div class="meta"><div>Hiring Team<br><b>{html.escape(meta.get('company', ''))}</b></div><div>{date}</div></div>
<div class="re">Re: {html.escape(meta.get('role', ''))}</div>
{''.join(parts)}<p class="sig">{name}</p></div></body></html>"""
    pdf = render(doc, src.with_suffix(".pdf"))
    if pages(pdf) > 1:
        print(f"  note: {pdf.name} runs past one page; cut some words from {src.name} and run `huntline pdf` again.")
    return pdf
