"""`huntline serve`: your job list as a local app. Click to shortlist, mark applied, or build
the tailored resume and cover letter, without going back to the terminal.

It listens on 127.0.0.1 only. Every action needs a token that is printed into the page it
serves, sent in a custom header, so other websites open in your browser cannot trigger it.
Requests whose Host isn't 127.0.0.1 or localhost are refused, which stops DNS-rebinding sites
from reading that page.
"""
import json
import os
import secrets
from contextlib import closing
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote

from . import learn, letter, prep, report, resume
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
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def local(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            if host in ("127.0.0.1", "localhost", "::1"):
                return True
            self.send(403, '{"error":"huntline serve only answers on 127.0.0.1"}')
            return False

        def do_GET(self):
            if not self.local():
                return
            path = unquote(self.path.split("?", 1)[0])
            if path in ("/", "/index.html"):
                with closing(connect(home)) as db:
                    return self.send(200, report.page(p, db, token), "text/html; charset=utf-8")
            if path.startswith("/files/"):
                f = (out / path[len("/files/"):]).resolve()
                if f.is_file() and f.is_relative_to(out):
                    ctype = {".pdf": "application/pdf", ".csv": "text/csv; charset=utf-8"}.get(
                        f.suffix, "text/plain; charset=utf-8")
                    return self.send(200, f.read_bytes(), ctype)
            self.send(404, '{"error":"not found"}')

        def do_POST(self):
            if not self.local():
                return
            if not secrets.compare_digest(self.headers.get("X-Huntline-Token", ""), token):
                return self.send(403, '{"error":"bad token; reload the page"}')
            try:
                size = int(self.headers.get("Content-Length") or 0)
                if not 0 <= size <= 10_000:
                    return self.send(413, '{"error":"too big"}')
                body = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
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
                    learn.apply(db)
                    report.write(p, db)
                    return self.send(200, '{"ok":true}')
                if action == "resume":
                    f = resume.build(p, load_resume(p), out / "resumes" / f"{letter.slug(job['company'] + '-' + job['title'])}.pdf",
                                     job["title"], job.get("desc", ""))
                elif action == "letter":
                    f = letter.build(p, letter.draft(p, load_resume(p), job))
                elif action == "prep":
                    f = prep.write(p, load_resume(p), job)
                else:
                    return self.send(404, '{"error":"unknown action"}')
                return self.send(200, json.dumps({"ok": True, "file": "/files/" + quote(Path(f).resolve().relative_to(out).as_posix())}))
            except (Exception, SystemExit) as e:
                return self.send(500, json.dumps({"error": str(e) or type(e).__name__}))

    return H


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process bind a port that is already in use.
    allow_reuse_address = os.name != "nt"


def run(p, port=8765, open_browser=True):
    token = secrets.token_urlsafe(18)
    try:
        srv = Server(("127.0.0.1", port), handler(p, token))
    except OSError as e:
        raise SystemExit(f"Can't listen on port {port} ({e.strerror}). Try: huntline serve --port {port + 1}")
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
