import html
import os
import urllib.parse

from net import fetch_json

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def enabled():
    return bool(TOKEN)


def _api(method, params):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    return fetch_json(url, data=params, timeout=40)


def send(text, chat_id=None, preview=False):
    chat_id = chat_id or CHAT_ID
    if not (TOKEN and chat_id):
        print("[telegram disabled]", text[:200].replace("\n", " | "))
        return
    for i in range(0, len(text), 3900):
        try:
            _api("sendMessage", {"chat_id": chat_id, "text": text[i:i + 3900], "parse_mode": "HTML",
                                 "disable_web_page_preview": not preview})
        except Exception as e:
            print("telegram send failed:", e)


def updates(offset):
    if not TOKEN:
        return []
    try:
        return _api("getUpdates", {"offset": offset, "timeout": 0,
                                   "allowed_updates": ["message"]}).get("result", [])
    except Exception as e:
        print("telegram getUpdates failed:", e)
        return []


def esc(s):
    return html.escape(str(s or ""), quote=False)


def job_message(j):
    bar = "🟢" if j["score"] >= 75 else "🟡" if j["score"] >= 55 else "⚪"
    kind = "🎓 משרת סטודנט" if j["kind"] == "student" else "💼 משרה מלאה"
    lines = [
        f"{bar} <b>{j['score']}% התאמה</b> · {kind}",
        f"<b>{esc(j['title'])}</b>",
        f"🏢 {esc(j['company'])}" + (f" · 📍 {esc(j['location'])}" if j.get("location") else ""),
    ]
    if j.get("reasons"):
        lines.append("✔ " + esc(" · ".join(j["reasons"])))
    lines.append(f'<a href="{esc(j["url"])}">לצפייה במשרה ולהגשה ←</a>')
    return "\n".join(lines)
