"""`huntline serve`: your job list as a local app. Click to shortlist, mark applied, or build
the tailored resume and cover letter, without going back to the terminal.

It listens on 127.0.0.1 only. Every action needs a token that is printed into the page it
serves, sent in a custom header, so other websites open in your browser cannot trigger it.
"""
import json
import secrets
from contextlib import closing
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote

from . import letter, report, resume
from .profile import load_resume
from .store import STATUSES, connect


def handler(p, token):
    home = Path(p["_home"])
    out = (home / "out").resolve()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json"):
            body = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = unquote(self.path.split("?", 1)[0])
            if path in ("/", "/index.html"):
                with closing(connect(home)) as db:
                    return self.send(200, report.page(p, db, token), "text/html; charset=utf-8")
            if path.startswith("/files/"):
                f = (out / path[len("/files/"):]).resolve()
                if f.is_file() and f.is_relative_to(out):
                    ctype = "application/pdf" if f.suffix == ".pdf" else "text/plain; charset=utf-8"
                    return self.send(200, f.read_bytes(), ctype)
            self.send(404, '{"error":"not found"}')

        def do_POST(self):
            if not secrets.compare_digest(self.headers.get("X-Huntline-Token", ""), token):
                return self.send(403, '{"error":"bad token; reload the page"}')
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except ValueError:
                return self.send(400, '{"error":"bad json"}')
            with closing(connect(home)) as db:
                return self.act(db, body)

        def act(self, db, body):
            row = db.execute("SELECT * FROM jobs WHERE id=?", (str(body.get("id")),)).fetchone()
            if not row:
                return self.send(404, '{"error":"no such job"}')
            job, action = dict(row), self.path.rstrip("/").rsplit("/", 1)[-1]
            try:
                if action == "status":
                    if body.get("status") not in STATUSES:
                        return self.send(400, '{"error":"bad status"}')
                    db.execute("UPDATE jobs SET status=? WHERE id=?", (body["status"], job["id"]))
                    db.commit()
                    report.write(p, db)
                    return self.send(200, '{"ok":true}')
                if action == "resume":
                    f = resume.build(p, load_resume(p), out / "resumes" / f"{letter.slug(job['company'] + '-' + job['title'])}.pdf",
                                     job["title"], job.get("desc", ""))
                elif action == "letter":
                    f = letter.build(p, letter.draft(p, load_resume(p), job))
                else:
                    return self.send(404, '{"error":"unknown action"}')
                return self.send(200, json.dumps({"ok": True, "file": "/files/" + quote(Path(f).resolve().relative_to(out).as_posix())}))
            except (Exception, SystemExit) as e:
                return self.send(500, json.dumps({"error": str(e) or type(e).__name__}))

    return H


def run(p, port=8765, open_browser=True):
    token = secrets.token_urlsafe(18)
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler(p, token))
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"Huntline is open at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
