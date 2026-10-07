"""Optional model calls, through any OpenAI-compatible API (OpenAI, StepFun, OpenRouter, Ollama...).

    OPENAI_API_KEY    required
    OPENAI_BASE_URL   default https://api.openai.com/v1
    HUNTLINE_MODEL    default gpt-4o-mini

The model only ever reads your resume and the posting. It never writes into your resume.
"""
import concurrent.futures as cf
import json
import os
import re

import requests


def chat(prompt, json_mode=False):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("--ai needs OPENAI_API_KEY (any OpenAI-compatible provider; set OPENAI_BASE_URL for others)")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    body = {"model": os.environ.get("HUNTLINE_MODEL", "gpt-4o-mini"), "messages": [{"role": "user", "content": prompt}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    res = requests.post(f"{base}/chat/completions", timeout=120, headers={"Authorization": f"Bearer {key}"}, json=body)
    if res.status_code == 400 and json_mode:     # some providers reject response_format; the prompt asks for JSON anyway
        body.pop("response_format")
        res = requests.post(f"{base}/chat/completions", timeout=120, headers={"Authorization": f"Bearer {key}"}, json=body)
    res.raise_for_status()
    text = res.json()["choices"][0]["message"]["content"] or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def parse_json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def review(resume, job):
    """{fit: 0-100, why: str, gaps: str} for one posting, judged like a recruiter screening a CV."""
    prompt = ("You screen candidates for a recruiter. Judge how well this candidate fits this job, using ONLY "
              "the resume and posting below. Be strict: 80+ means a recruiter would almost surely call them; "
              "under 40 means don't bother. Hard requirements they lack (years, degree, language, licence, "
              "clearance, location) weigh most.\n"
              'Reply with JSON only: {"fit": <0-100>, "why": "<one sentence, the strongest match>", '
              '"gaps": "<one sentence, the biggest gap, or empty>"}\n\n'
              f"RESUME:\n{json.dumps(resume, ensure_ascii=False)[:7000]}\n\n"
              f"JOB: {job['title']} at {job['company']} ({job['location']})\n{(job.get('desc') or '')[:5000]}")
    d = parse_json(chat(prompt, json_mode=True))
    try:
        fit = max(0, min(100, int(float(d.get("fit")))))
    except (TypeError, ValueError):
        return None
    return {"fit": fit, "why": str(d.get("why") or "").strip(), "gaps": str(d.get("gaps") or "").strip()}


def rank(p, db, resume, limit=25, ids=None, redo=False, workers=4):
    """Reviews your best unreviewed jobs and stores the verdict next to each one."""
    if ids:
        jobs = [dict(j) for i in ids for j in db.execute("SELECT * FROM jobs WHERE id=?", (i,))]
    else:
        jobs = [dict(j) for j in db.execute(
            "SELECT * FROM jobs WHERE status IN ('new','shortlisted') AND closed='' "
            f"{'' if redo else 'AND ai_fit IS NULL'} ORDER BY score DESC LIMIT ?", (limit,))]
    if not jobs:
        return []

    def one(j):
        try:
            return j, review(resume, j)
        except requests.RequestException as e:
            return j, e
    done = []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for j, v in ex.map(one, jobs):
            if not isinstance(v, dict):
                print(f"  {j['id']}  skipped ({type(v).__name__ if v else 'unreadable answer'})")
                continue
            note = v["why"] + (f" Gap: {v['gaps']}" if v["gaps"] else "")
            db.execute("UPDATE jobs SET ai_fit=?, ai_note=? WHERE id=?", (v["fit"], note, j["id"]))
            done.append((j, v))
            print(f"  {j['id']}  {v['fit']:>3}  {j['title'][:50]} @ {j['company'][:30]}")
    db.commit()
    return done
