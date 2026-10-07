"""Writes out/jobs.csv and out/jobs.html, a single page you open in any browser.

Opened as a file, its buttons copy the matching `huntline` command. Opened through
`huntline serve`, the same buttons do the work: change status, build the resume and letter.
"""
import csv
import html
import json
from pathlib import Path

COLS = ["id", "found", "posted", "score", "taste", "fit", "ai_fit", "status", "title", "company", "location", "country",
        "salary_lo", "salary_hi", "visa", "email", "source", "url", "note", "ai_note", "closed"]


def rows(db):
    return [dict(r) for r in db.execute(
        "SELECT * FROM jobs WHERE status NOT IN ('skip','rejected') ORDER BY found DESC, score DESC")]


def page(p, db, token=""):
    data = json.dumps([{k: r.get(k) for k in COLS} for r in rows(db)]).replace("</", "<\\/")
    return (PAGE.replace("__DATA__", data).replace("__NAME__", html.escape(p.get("name", "")))
            .replace("__TOKEN__", json.dumps(token)))


def write(p, db):
    out = Path(p["_home"]) / "out"
    out.mkdir(exist_ok=True)
    with open(out / "jobs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows(db))
    (out / "jobs.html").write_text(page(p, db), encoding="utf-8")
    return out / "jobs.html"


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Huntline</title>
<style>
:root{--bg:#F6F4EF;--card:#fff;--ink:#0E1116;--mute:#667080;--line:#E3E0D8;--acc:#E8480F;--good:#1F7A4D;--warn:#9A6400;--info:#2D5BD0}
@media (prefers-color-scheme:dark){:root{--bg:#0E1116;--card:#161B23;--ink:#F4F1EA;--mute:#8A93A1;--line:#252C37;--acc:#FF5A1F;--good:#5FCB93;--warn:#E6B450;--info:#8FB0FF}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,"Segoe UI",system-ui,sans-serif}
header{padding:28px 16px 10px;max-width:1040px;margin:auto;display:flex;gap:14px;align-items:center}
.mark{width:40px;height:40px;flex:none}h1{margin:0;font-size:22px;font-weight:800;letter-spacing:-.02em}h1 span{color:var(--mute);font-weight:500}
.sub{color:var(--mute);font-size:13px}.stats{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.bar{display:flex;gap:8px;flex-wrap:wrap;padding:8px 16px 4px;max-width:1040px;margin:auto;align-items:center}
input,select{font:inherit;padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink)}
input[type=search]{flex:1;min-width:180px}input:focus,select:focus{outline:2px solid var(--acc);outline-offset:-1px}
label{font-size:13px;color:var(--mute);display:flex;gap:6px;align-items:center}
main{max-width:1040px;margin:auto;padding:8px 16px 48px}
.job{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin:10px 0;display:grid;grid-template-columns:56px 1fr;gap:14px;transition:border-color .15s}
.job:hover{border-color:var(--acc)}.job.closed{opacity:.55}
.sc{font:800 22px/1 "JetBrains Mono",Menlo,monospace;color:var(--acc);text-align:center;padding-top:4px}.sc small{display:block;margin-top:4px;font:500 10px Inter,system-ui,sans-serif;color:var(--mute);letter-spacing:.08em;text-transform:uppercase}
.t{font-weight:650;font-size:16px}.t a{color:inherit;text-decoration:none}.t a:hover{color:var(--acc)}.m{color:var(--mute);font-size:13px}
.tags{margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}.tag{font-size:12px;padding:2px 9px;border-radius:99px;border:1px solid var(--line)}
.v{color:var(--good);border-color:currentColor}.e{color:var(--warn);border-color:currentColor}.n{color:var(--acc);border-color:currentColor;font-weight:600}
.ai{color:var(--info);border-color:currentColor}.x{color:var(--mute);text-decoration:line-through}
.why{font-size:13px;margin-top:6px;padding-left:10px;border-left:2px solid var(--info)}
.acts{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
button{font:500 12px Inter,system-ui,sans-serif;padding:5px 10px;border-radius:8px;border:1px solid var(--line);background:transparent;color:var(--ink);cursor:pointer}
button:hover{border-color:var(--acc);color:var(--acc)}button:disabled{opacity:.5;cursor:wait}
code{font:12px "JetBrains Mono",Menlo,monospace;color:var(--mute);margin-left:auto}
#toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:8px 14px;border-radius:10px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none;max-width:90vw}
#toast.on{opacity:1}#toast a{color:inherit}
</style></head><body>
<header><svg class="mark" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="14" fill="#0E1116"/><path d="M12 40 H24 L30 26 L36 40 H44" stroke="#FF5A1F" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="48" cy="40" r="5" fill="none" stroke="#FF5A1F" stroke-width="3"/></svg>
<div><h1>huntline <span>· __NAME__</span></h1><div class="sub" id="mode"></div><div class="stats" id="stats"></div></div></header>
<div class="bar"><input type="search" id="q" placeholder="Filter by title, company, place...">
<select id="c"><option value="">All countries</option></select>
<select id="s"><option value="">Any status</option><option>new</option><option>shortlisted</option><option>applied</option><option>interview</option><option>offer</option></select>
<select id="o"><option value="best">Best match</option><option value="ai">AI fit</option><option value="new">Newest</option><option value="pay">Salary</option></select>
<label><input type="checkbox" id="h" checked> hide closed</label></div>
<main id="list"></main><div id="toast"></div>
<script>
const J=__DATA__,TOKEN=__TOKEN__,LIVE=!!TOKEN&&location.protocol.startsWith("http");
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const money=(a,b)=>!b?"":(a&&a!==b?Math.round(a/1e3)+"k–":"")+Math.round(b/1e3)+"k";
const ago=d=>{if(!d)return"";const n=Math.round((Date.now()-new Date(d+"T12:00:00"))/864e5);return n<=0?"posted today":n===1?"posted yesterday":`posted ${n}d ago`};
const latest=J.reduce((m,j)=>j.found>m?j.found:m,"");
[...new Set(J.map(j=>j.country))].sort().forEach(c=>$("c").insertAdjacentHTML("beforeend",`<option>${esc(c)}</option>`));
$("mode").innerHTML=LIVE?"Live: buttons run on your machine.":"Buttons copy the command. Run <code style=\"margin:0\">huntline serve</code> to make them work here.";
function stats(){const by={};J.forEach(j=>by[j.status]=(by[j.status]||0)+1);const fresh=J.filter(j=>j.found===latest).length;
$("stats").innerHTML=`<span class="tag">${J.length} jobs</span><span class="tag n">${fresh} new</span>`+
["shortlisted","applied","interview","offer"].filter(s=>by[s]).map(s=>`<span class="tag">${by[s]} ${s}</span>`).join("")}
const ORDER={best:(a,b)=>b.score-a.score,ai:(a,b)=>(b.ai_fit??-1)-(a.ai_fit??-1)||b.score-a.score,
new:(a,b)=>(b.posted||b.found).localeCompare(a.posted||a.found)||b.score-a.score,pay:(a,b)=>(b.salary_hi||0)-(a.salary_hi||0)};
function card(j){const pay=money(j.salary_lo,j.salary_hi);return `<div class="job${j.closed?" closed":""}" data-id="${esc(j.id)}"><div class="sc">${j.score}<small>score</small></div><div>
<div class="t"><a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a></div>
<div class="m">${[j.company,j.location,pay,ago(j.posted)].filter(Boolean).map(esc).join(" · ")}</div>
<div class="tags">${j.found===latest&&!j.closed?'<span class="tag n">new</span>':""}${j.closed?'<span class="tag x">closed</span>':""}
${j.ai_fit!=null?`<span class="tag ai">AI fit ${j.ai_fit}</span>`:""}${j.taste?`<span class="tag" title="Learned from what you shortlist and skip">${j.taste>0?"+":"−"}${Math.abs(j.taste)} your taste</span>`:""}${j.fit?`<span class="tag">resume fit ${j.fit}%</span>`:""}
${j.visa?`<span class="tag v">${esc(j.visa)}</span>`:""}${j.email?`<span class="tag e">${esc(j.email)}</span>`:""}
<span class="tag">${esc(j.status)}</span>${j.source?`<span class="tag">${esc(j.source)}</span>`:""}<code>${esc(j.id)}</code></div>
${j.ai_note?`<div class="why">${esc(j.ai_note)}</div>`:""}${j.note?`<div class="m">${esc(j.note)}</div>`:""}
<div class="acts"><button data-a="resume">Resume</button><button data-a="letter">Letter</button><button data-a="prep">Prep</button>
<button data-a="status" data-s="shortlisted">Shortlist</button><button data-a="status" data-s="applied">Applied</button>
<button data-a="status" data-s="skip">Skip</button></div></div></div>`}
function draw(){const q=$("q").value.toLowerCase(),c=$("c").value,s=$("s").value,h=$("h").checked;
const rows=J.filter(j=>(!c||j.country===c)&&(!s||j.status===s)&&(!h||!j.closed)&&(!q||(j.title+" "+j.company+" "+j.location).toLowerCase().includes(q)))
.sort((a,b)=>(!!a.closed-!!b.closed)||ORDER[$("o").value](a,b));
$("list").innerHTML=rows.length?rows.map(card).join(""):'<p class="m">Nothing matches.</p>';stats()}
function toast(html){const t=$("toast");t.innerHTML=html;t.classList.add("on");clearTimeout(t._h);t._h=setTimeout(()=>t.classList.remove("on"),4500)}
$("list").addEventListener("click",async e=>{const b=e.target.closest("button");if(!b)return;
const id=b.closest(".job").dataset.id,a=b.dataset.a,st=b.dataset.s,j=J.find(x=>x.id===id);
if(!LIVE){const cmd=a==="status"?`huntline status ${id} ${st}`:`huntline ${a} ${id}`;
try{await navigator.clipboard.writeText(cmd);toast("Copied: "+esc(cmd))}catch(_){toast(esc(cmd))}return}
b.disabled=true;try{const r=await fetch("/api/"+a,{method:"POST",headers:{"Content-Type":"application/json","X-Huntline-Token":TOKEN},body:JSON.stringify({id,status:st})});
const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);
if(a==="status"){j.status=st;if(st==="skip")J.splice(J.indexOf(j),1);draw();toast(`${esc(id)} → ${esc(st)}`)}
else{window.open(d.file,"_blank");toast(`Made <a href="${esc(d.file)}" target="_blank">${esc(d.file.split("/").pop())}</a>`)}}
catch(err){toast("Failed: "+esc(err.message))}finally{b.disabled=false}});
["q","c","s","o","h"].forEach(id=>$(id).addEventListener("input",draw));draw();
</script></body></html>
"""
