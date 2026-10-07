"""Interview prep notes for one job, as a Markdown file you can read on your phone.

    huntline prep <id>         requirements from the posting, each paired with your best real
                               evidence from resume.yaml, plus the questions you'll face and ask
    huntline prep <id> --ai    adds likely questions with answer outlines, drafted by your model
                               from your resume only

Like tailoring, the plain version never writes a claim: every piece of evidence is one of
your own bullets, and requirements with no matching bullet are called out as gaps.
"""
import re
from pathlib import Path

from .letter import slug
from .match import Fit, years_required
from .resume import STOP, words
from .store import age_days

ASKS = re.compile(r"\b(must|required|requirements?|you have|you'll have|you will have|you bring|you're|you are|"
                  r"experience (with|in|of)|proficien\w*|familiar\w*|knowledge of|understanding of|ability to|"
                  r"degree|years|fluent|skills?|background in|track record|comfortable|expert\w*|strong)\b", re.I)
SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z])|\s+[•·▪●◦*]\s+|\s+-\s+(?=[A-Z])|\s{2,}")
# Sentences about the employer, not the candidate.
NOISE = re.compile(r"equal opportunity|accommodation|we offer|benefits|privacy|cookie|apply now|salary range|"
                   r"discriminat|background check|e-?verify", re.I)


def asks(desc, n=8):
    """The requirement sentences in a posting, most specific first, in their original order on ties."""
    seen, found = set(), []
    for s in SPLIT.split(desc or ""):
        s = s.strip(" -–•*")
        if 25 <= len(s) <= 320 and ASKS.search(s) and not NOISE.search(s):
            key = " ".join(sorted(words(s)))[:120]
            if key not in seen:
                seen.add(key)
                found.append(s)
    return sorted(found, key=lambda s: -len(words(s) - STOP))[:n] if len(found) > n else found


# Words every requirement uses; sharing them proves nothing.
GENERIC = {"experience", "experienced", "years", "year", "strong", "skills", "skill", "ability", "knowledge",
           "understanding", "proven", "track", "record", "excellent", "good", "great", "hands-on", "including",
           "plus", "bonus", "preferred", "required", "requirements", "must", "using", "working", "least",
           "minimum", "fluent", "comfortable", "background", "familiarity", "proficiency", "proficient", "expert"}


def evidence(resume, ask):
    """Where your resume answers one requirement: (text, where it's from) or None.

    A work bullet sharing two real words wins. Failing that, any other line of your resume
    (skills, projects, certifications, languages) sharing one."""
    q, best, score = words(ask) - GENERIC, None, 0
    for j in resume.get("experience") or []:
        for b in j.get("bullets") or []:
            n = len(q & words(re.sub(r"\*\*", "", str(b))))
            if n > score:
                best, score = (str(b), f"{j.get('title') or ''}, {j.get('company') or ''}".strip(", ")), n
    if score >= 2:
        return best
    other = [(f"{k}: {v}", "skills") for k, v in (resume.get("skills") or {}).items()]
    other += [(f"{x.get('name')}: {x.get('text')}", "projects") for x in resume.get("projects") or []]
    other += [(str(c), "certifications") for c in resume.get("certifications") or []]
    other += [(str(resume["additional"]), "additional")] if resume.get("additional") else []
    other += [(f"{e.get('degree')}, {e.get('school')}", "education") for e in resume.get("education") or []]
    # A word all over your resume ("marketing" for a marketer) is your field, not evidence.
    lines = [str(resume.get("headline") or ""), str(resume.get("summary") or "")] + [t for t, _ in other]
    lines += [f"{j.get('title')} {b}" for j in resume.get("experience") or [] for b in j.get("bullets") or []]
    df = {}
    for line in lines:
        for w in words(line):
            df[w] = df.get(w, 0) + 1
    q = {w for w in q if df.get(w, 0) < 3}
    hits = [(len(q & words(t)), t, where) for t, where in other]
    n, text, where = max(hits, default=(0, "", ""))
    return (text, where) if n >= 1 else None


def money(lo, hi):
    return "" if not hi else (f"{round(lo / 1000)}k-" if lo and lo != hi else "") + f"{round(hi / 1000)}k"


def notes(p, resume, job):
    fit = Fit(resume)
    desc = job.get("desc") or ""
    age = age_days(job.get("posted"))
    head = " · ".join(x for x in (job.get("location"), money(job.get("salary_lo"), job.get("salary_hi")),
                                  f"posted {age}d ago" if age is not None else "") if x)
    md = [f"# Interview prep: {job['title']} at {job['company']}", "", head, "", job.get("url") or "", ""]
    if job.get("visa"):
        md += [f"**Visa:** {job['visa']}", ""]
    if job.get("ai_fit") is not None:
        md += [f"**AI screen:** {job['ai_fit']}/100. {job.get('ai_note') or ''}", ""]

    md += ["## What they ask for, and your proof", ""]
    reqs = asks(desc)
    if not reqs:
        md += ["_The posting doesn't spell out requirements. Read it in full at the link above._", ""]
    gaps = []
    for i, ask in enumerate(reqs, 1):
        md.append(f"{i}. **{ask}**")
        ev = evidence(resume, ask)
        if ev:
            md.append(f"   - Your proof: {ev[0]} _({ev[1]})_")
            if "," in ev[1]:                                   # a work bullet, not a skills line
                md.append("   - Tell it as a story: the situation, what you did, the result.")
        else:
            md.append("   - No bullet in your resume covers this. Prepare an honest answer: a related example, "
                      "or how you'd get up to speed.")
            gaps.append(ask)
    md.append("")
    need = years_required(desc)
    have = (p.get("search") or {}).get("years_experience")
    if need is not None and have is not None and need > have:
        md += [f"> They ask for {need}+ years; you have {have}. Expect the question. Lead with scope and results, "
               "not time served.", ""]

    tools = fit.tools_in(desc)
    if tools:
        md += ["## Tools they name that you know", "", ", ".join(tools), "",
               "Have one concrete example ready for each.", ""]

    top = next((b for j in resume.get("experience") or [] for b in (j.get("bullets") or [])), "")
    md += ["## Questions you'll almost certainly get", "",
           "- **Tell me about yourself.** Two minutes: " + (str(resume.get("summary") or "").strip() or
                                                          "who you are, what you're best at, why this role next."),
           f"- **Why {job['company']}?** Something specific from your research below, not the job ad.",
           "- **Why this role?** Tie it to the requirements above that you can prove.",
           "- **Your proudest result.** " + (f"Candidate: {top}" if top else "Pick your strongest bullet."),
           "- **A time something went wrong.** What happened, what you changed, what you'd do now.",
           "- **What are your salary expectations?** Know your number before the call."
           + (f" Advertised: {money(job.get('salary_lo'), job.get('salary_hi'))}." if job.get("salary_hi") else "")]
    if gaps:
        md.append("- **Expect probing on your gaps:** " + "; ".join(g.rstrip(".")[:80] for g in gaps[:3]) + ".")
    md.append("")

    md += ["## Research before the call", "",
           f"- {job['company']}'s website: product, customers, latest news",
           "- The team and your likely interviewer on LinkedIn",
           "- Recent funding, layoffs or leadership changes",
           "- Employee reviews: what people praise, what they warn about", ""]
    if (p.get("search") or {}).get("needs_sponsorship"):
        md += ["- Confirm visa sponsorship early, with the recruiter, not the hiring manager", ""]

    md += ["## Questions to ask them", "",
           "- What would make someone in this role a clear success after six months?",
           "- What's the hardest part of this job that the posting doesn't mention?",
           "- How is the team measured, and how is that going this year?",
           "- Why is this role open?",
           "- What does the rest of the hiring process look like, and when will I hear back?", ""]
    return "\n".join(md)


def ai_section(p, resume, job):
    import json

    from .ai import chat
    prompt = ("You are an interview coach. For the job below, list the 6 interview questions this candidate is most "
              "likely to be asked, then for each give a 2-3 line answer outline. RULES: use ONLY facts from the resume; "
              "never invent numbers, employers, tools or results. Where the resume has no evidence, say so and suggest "
              "an honest angle. Markdown only: '### <question>' then the outline as '- ' bullets.\n\n"
              f"RESUME:\n{json.dumps(resume, ensure_ascii=False)[:7000]}\n\n"
              f"JOB: {job['title']} at {job['company']}\n{(job.get('desc') or '')[:5000]}")
    return "## Likely questions and how to answer (AI draft, check every claim)\n\n" + chat(prompt).strip() + "\n"


def write(p, resume, job, use_ai=False):
    text = notes(p, resume, job)
    if use_ai:
        text += "\n" + ai_section(p, resume, job)
    out = Path(p["_home"]) / "out" / "prep" / f"{slug(job['company'] + '-' + job['title'])}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return out
