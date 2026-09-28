"""HTML to PDF with whatever Chromium-family browser is installed, or Playwright as a fallback."""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

BROWSERS = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave", "brave-browser",
            "microsoft-edge", "msedge",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def browser():
    env = os.environ.get("HUNTLINE_CHROME")
    if env:
        return env
    for b in BROWSERS:
        found = shutil.which(b) or (b if os.path.isfile(b) else None)
        if found:
            return found
    return None


def pages(pdf_path):
    return len(re.findall(rb"/Type\s*/Page[^s]", Path(pdf_path).read_bytes()))


def render(html_text, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Stage next to the output, not /tmp: snap-packaged browsers cannot read /tmp.
    with tempfile.NamedTemporaryFile("w", suffix=".html", dir=out_path.parent, delete=False) as f:
        f.write(html_text)
        src = Path(f.name)
    try:
        b = browser()
        if b:
            subprocess.run([b, "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
                            f"--print-to-pdf={out_path}", src.as_uri()], check=True, capture_output=True, timeout=120)
        else:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                raise SystemExit("No Chrome/Chromium/Edge/Brave found. Install one, or run:\n"
                                 "  pip install playwright && playwright install chromium")
            with sync_playwright() as pw:
                br = pw.chromium.launch()
                pg = br.new_page()
                pg.goto(src.as_uri())
                pg.pdf(path=str(out_path), prefer_css_page_size=True, print_background=True)
                br.close()
        if not out_path.exists() or out_path.stat().st_size < 2000:
            raise RuntimeError("the browser produced no PDF")
        return out_path
    finally:
        src.unlink(missing_ok=True)
