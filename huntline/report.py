"""Writes out/jobs.csv and out/jobs.html, a single page you open in any browser."""
import csv
import html
import json
from pathlib import Path

COLS = ["id", "found", "score", "status", "title", "company", "location", "country", "salary_lo", "salary_hi",
        "visa", "email", "source", "url", "note"]


def write(p, db):
    out = Path(p["_home"]) / "out"
    rows = [dict(r) for r in db.execute(
        "SELECT * FROM jobs WHERE status NOT IN ('skip','rejected') ORDER BY found DESC, score DESC")]
    with open(out / "jobs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    data = json.dumps([{k: r[k] for k in COLS} for r in rows]).replace("</", "<\\/")
    page = PAGE.replace("__DATA__", data).replace("__NAME__", html.escape(p.get("name", "")))
    (out / "jobs.html").write_text(page)
    return out / "jobs.html"


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Huntline</title>
<style>
:root{--bg:#F6F4EF;--card:#fff;--ink:#0E1116;--mute:#667080;--line:#E3E0D8;--acc:#E8480F;--good:#1F7A4D;--warn:#9A6400}
@media (prefers-color-scheme:dark){:root{--bg:#0E1116;--card:#161B23;--ink:#F4F1EA;--mute:#8A93A1;--line:#252C37;--acc:#FF5A1F;--good:#5FCB93;--warn:#E6B450}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,"Segoe UI",system-ui,sans-serif}
header{padding:28px 16px 10px;max-width:1040px;margin:auto;display:flex;gap:14px;align-items:center}
.mark{width:40px;height:40px;flex:none}h1{margin:0;font-size:22px;font-weight:800;letter-spacing:-.02em}h1 span{color:var(--mute);font-weight:500}
.sub{color:var(--mute);font-size:13px}
.bar{display:flex;gap:8px;flex-wrap:wrap;padding:8px 16px 4px;max-width:1040px;margin:auto}
input,select{font:inherit;padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink)}
input{flex:1;min-width:180px}input:focus,select:focus{outline:2px solid var(--acc);outline-offset:-1px}
main{max-width:1040px;margin:auto;padding:8px 16px 48px}
.job{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin:10px 0;display:grid;grid-template-columns:56px 1fr;gap:14px;transition:border-color .15s}
.job:hover{border-color:var(--acc)}
.sc{font:800 22px/1 "JetBrains Mono",Menlo,monospace;color:var(--acc);text-align:center;padding-top:4px}.sc small{display:block;margin-top:4px;font:500 10px Inter,system-ui,sans-serif;color:var(--mute);letter-spacing:.08em;text-transform:uppercase}
.t{font-weight:650;font-size:16px}.t a{color:inherit;text-decoration:none}.t a:hover{color:var(--acc)}.m{color:var(--mute);font-size:13px}
.tags{margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}.tag{font-size:12px;padding:2px 9px;border-radius:99px;border:1px solid var(--line)}
.v{color:var(--good);border-color:currentColor}.e{color:var(--warn);border-color:currentColor}
code{font:12px "JetBrains Mono",Menlo,monospace;color:var(--mute);margin-left:auto}
</style></head><body>
<header><svg class="mark" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="14" fill="#0E1116"/><path d="M12 40 H24 L30 26 L36 40 H44" stroke="#FF5A1F" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="48" cy="40" r="5" fill="none" stroke="#FF5A1F" stroke-width="3"/></svg>
<div><h1>huntline <span>· __NAME__</span></h1><div class="sub"><span id="n"></span> Best matches first. Track progress with <code style="margin:0">huntline status &lt;id&gt; applied</code></div></div></header>
<div class="bar"><input id="q" placeholder="Filter by title, company, place..."><select id="c"><option value="">All countries</option></select>
<select id="s"><option value="">Any status</option><option>new</option><option>shortlisted</option><option>applied</option><option>interview</option><option>offer</option></select></div>
<main id="list"></main>
<script>
const J=__DATA__;const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const money=(a,b)=>!b?"":(a&&a!==b?Math.round(a/1e3)+"k–":"")+Math.round(b/1e3)+"k";
const cs=[...new Set(J.map(j=>j.country))].sort();const sel=document.getElementById("c");
cs.forEach(c=>sel.insertAdjacentHTML("beforeend",`<option>${esc(c)}</option>`));
document.getElementById("n").textContent=J.length+" jobs.";
function draw(){const q=document.getElementById("q").value.toLowerCase(),c=sel.value,s=document.getElementById("s").value;
const rows=J.filter(j=>(!c||j.country===c)&&(!s||j.status===s)&&(!q||(j.title+" "+j.company+" "+j.location).toLowerCase().includes(q)));
document.getElementById("list").innerHTML=rows.length?rows.map(j=>`<div class="job"><div class="sc">${j.score}<small>score</small></div><div>
<div class="t"><a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a></div>
<div class="m">${esc(j.company)} · ${esc(j.location)} ${money(j.salary_lo,j.salary_hi)?"· "+money(j.salary_lo,j.salary_hi):""}</div>
<div class="tags">${j.visa?`<span class="tag v">${esc(j.visa)}</span>`:""}${j.email?`<span class="tag e">${esc(j.email)}</span>`:""}
<span class="tag">${esc(j.status)}</span><span class="tag">${esc(j.source)}</span><code>${esc(j.id)}</code></div>
${j.note?`<div class="m">${esc(j.note)}</div>`:""}</div></div>`).join(""):'<p class="m">Nothing matches.</p>'}
["q","c","s"].forEach(id=>document.getElementById(id).addEventListener("input",draw));draw();
</script></body></html>
"""
