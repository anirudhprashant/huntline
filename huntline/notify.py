"""Tells you about the best new matches after a run, wherever you'll see them first.

Set any of these in .env (all optional, all free):

  NTFY_TOPIC            push to your phone with the ntfy app (ntfy.sh/<topic>, or NTFY_URL for your own server)
  DISCORD_WEBHOOK_URL   a Discord channel webhook
  SLACK_WEBHOOK_URL     a Slack incoming webhook
  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID

profile.yaml `notify: {min_score: 60, top: 5}` decides what is worth a ping.
"""
import os
import sys

import requests


def money(lo, hi):
    if not hi:
        return ""
    return (f"{round(lo / 1000)}k-" if lo and lo != hi else "") + f"{round(hi / 1000)}k"


def digest(jobs, top=5):
    lines = [f"{len(jobs)} new match{'es' if len(jobs) != 1 else ''}. Best first:"]
    for j in jobs[:top]:
        extra = " · ".join(x for x in (money(j.get("salary_lo"), j.get("salary_hi")), j.get("visa")) if x)
        lines.append(f"\n{j['score']}  {j['title']} @ {j['company']} ({j['location']})"
                     + (f"\n    {extra}" if extra else "") + f"\n    {j['url']}")
    return "\n".join(lines)


def channels():
    env = os.environ.get
    out = []
    if env("NTFY_TOPIC"):
        out.append(("ntfy", lambda t: requests.post(f"{env('NTFY_URL', 'https://ntfy.sh').rstrip('/')}/{env('NTFY_TOPIC')}",
                                                    data=t.encode(), headers={"Title": "Huntline", "Tags": "briefcase"},
                                                    timeout=20)))
    if env("DISCORD_WEBHOOK_URL"):
        out.append(("Discord", lambda t: requests.post(env("DISCORD_WEBHOOK_URL"), json={"content": t[:1990]}, timeout=20)))
    if env("SLACK_WEBHOOK_URL"):
        out.append(("Slack", lambda t: requests.post(env("SLACK_WEBHOOK_URL"), json={"text": t}, timeout=20)))
    if env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID"):
        out.append(("Telegram", lambda t: requests.post(
            f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/sendMessage", timeout=20,
            json={"chat_id": env("TELEGRAM_CHAT_ID"), "text": t[:4000], "disable_web_page_preview": True})))
    return out


def send(p, ranked):
    """Returns the names of the channels that took the message, comma separated, or ''."""
    cfg = p.get("notify") or {}
    worth = [j for j in ranked if j["score"] >= cfg.get("min_score", 0)]
    chans = channels()
    if not worth or not chans:
        return ""
    text = digest(worth, cfg.get("top", 5))
    ok = []
    for name, post in chans:
        try:
            r = post(text)
            if r.ok:
                ok.append(name)
            else:
                print(f"  [notify {name}] HTTP {r.status_code}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  [notify {name}] {type(e).__name__}", file=sys.stderr)
    return ", ".join(ok)
