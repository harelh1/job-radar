"""Small HTTP helpers (stdlib only, so the GitHub Action needs no installs)."""
import html
import json
import re
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 JobRadar/1.0")


def fetch(url, data=None, headers=None, timeout=30):
    h = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
         "Accept-Language": "en-US,en;q=0.9,he;q=0.8"}
    if data is not None and not isinstance(data, (bytes, str)):
        data = json.dumps(data)
        h["Content-Type"] = "application/json"
    if isinstance(data, str):
        data = data.encode("utf-8")
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        charset = r.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, "replace")


def fetch_json(url, data=None, headers=None, timeout=30):
    return json.loads(fetch(url, data, headers, timeout))


_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)


def strip_html(s):
    if not s:
        return ""
    s = html.unescape(s)          # some feeds double-escape
    s = html.unescape(_TAG.sub(" ", s))
    return re.sub(r"\s+", " ", s).strip()
