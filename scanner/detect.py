"""Turn "company name" (+ optional careers URL) into a scanner config.

Tries, in order:
  1. If a URL is given: read the page and recognise the careers system behind it
     (Comeet, Workday, Greenhouse, Lever, SmartRecruiters, Ashby, careers-page.com).
  2. Without a URL: guess the company slug on the public job-board APIs, then try
     common careers-page addresses (name.com/careers, name.co.il/careers ...).
  3. Fallback (URL given but no known system): watch the page's job links.
Returns (config, message) - config is None when nothing worked.
"""
import re
import urllib.parse

from adapters import ADAPTERS
from net import fetch, fetch_json


def _slugs(name):
    base = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    words = base.split()
    cands = ["".join(words), "-".join(words)]
    if len(words) > 1:
        cands.append(words[0])
    cands += [c + suf for c in cands[:2] for suf in ("ltd", "technologies", "tech", "inc", "israel")]
    out = []
    for c in cands:
        if c and c not in out:
            out.append(c)
    return out


def _try(cfg):
    try:
        jobs = ADAPTERS[cfg["type"]](cfg)
        return jobs
    except Exception:
        return None


def from_page(name, url, html_=None):
    if html_ is None:
        html_ = fetch(url)
    # Comeet (WordPress plugin, embedded widget, or comeet.com hosted page)
    uid = (re.search(r'comeet_uid"\s*:\s*"([^"]+)"', html_) or re.search(r'"company_uid"\s*:\s*"([^"]+)"', html_)
           or re.search(r'company-uid="([^"]+)"', html_) or re.search(r'comeet\.com?/jobs/[^/"\']+/([0-9A-F]{2}\.[0-9A-F]{3})', html_))
    tok = (re.search(r'comeet_token"\s*:\s*"([^"]+)"', html_) or re.search(r'"token"\s*:\s*"([A-F0-9]{16,})"', html_)
           or re.search(r'token="([A-F0-9]{16,})"', html_))
    if uid and not tok:
        m = re.search(r'comeet\.com?/jobs/([^/"\']+)/' + re.escape(uid.group(1)), html_)
        if m:
            try:
                h2 = fetch(f"https://www.comeet.com/jobs/{m.group(1)}/{uid.group(1)}")
                tok = re.search(r'"token"\s*:\s*"([A-F0-9]{16,})"', h2)
            except Exception:
                pass
    if uid and tok:
        cfg = {"type": "comeet", "uid": uid.group(1), "token": tok.group(1)}
        if _try(cfg) is not None:
            return cfg
    # Workday
    m = re.search(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", html_ + " " + url)
    if m:
        cfg = {"type": "workday", "host": f"{m.group(1)}.{m.group(2)}.myworkdayjobs.com",
               "tenant": m.group(1), "site": m.group(3), "israel_only": True}
        if _try(cfg) is not None:
            return cfg
    for rx, typ in [(r"boards(?:-api)?\.greenhouse\.io/(?:embed/job_board\?for=|v1/boards/)?([a-z0-9]+)", "greenhouse"),
                    (r"jobs\.lever\.co/([a-z0-9-]+)", "lever"),
                    (r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9]+)", "smartrecruiters"),
                    (r"jobs\.ashbyhq\.com/([A-Za-z0-9.-]+)", "ashby"),
                    (r"apply\.workable\.com/(?:api/v1/widget/accounts/)?([a-z0-9-]+)", "workable"),
                    (r"careers-page\.com/([a-z0-9-]+)", "careerspage")]:
        m = re.search(rx, html_ + " " + url)
        if m:
            cfg = {"type": typ, "slug": m.group(1), "israel_only": typ != "careerspage"}
            jobs = _try(cfg)
            if jobs is not None:
                return cfg
    return None


def detect(name, url=None):
    if url and "scd-infrared.com" in url:
        cfg = {"type": "scd", "url": "https://www.scd-infrared.com/find-a-job/"}
        if _try(cfg):
            return cfg, "זיהיתי את אתר המשרות של SCD"
    if url:
        try:
            cfg = from_page(name, url)
        except Exception as e:
            return None, f"לא הצלחתי לפתוח את הקישור ({type(e).__name__})"
        if cfg:
            return cfg, f"זיהיתי מערכת {cfg['type']}"
        cfg = {"type": "links", "url": url, "need_israel_check": True}
        try:
            page = fetch(url)
            # Comeet-style position ids in the site's own URLs (e.g. /open-positions/CD.658/)
            if len(re.findall(r'href="[^"]*/[0-9A-F]{2}\.[0-9A-F]{3}', page)) >= 2:
                cfg["pattern"] = r"/[0-9A-F]{2}\.[0-9A-F]{3}(?:-[0-9A-F]{2}\.[0-9A-F]{3})?/?$"
        except Exception:
            pass
        jobs = _try(cfg)
        if jobs:
            return cfg, f"לא זיהיתי מערכת גיוס מוכרת, אז אעקוב אחרי קישורי המשרות בעמוד ({len(jobs)} נמצאו)"
        return None, "העמוד לא מכיל קישורי משרות שאני יכול לקרוא (כנראה נטען ב-JavaScript)"

    # no URL: guess job-board slugs
    for slug in _slugs(name):
        for typ in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters"):
            cfg = {"type": typ, "slug": slug, "israel_only": True}
            jobs = _try(cfg)
            if jobs:  # non-empty only, empty boards are often wrong guesses
                return cfg, f"זיהיתי {typ} ({slug})"
    # guess careers pages
    for slug in _slugs(name)[:2]:
        for dom in (".com", ".co.il", ".tech", ".io", ".ai"):
            for path in ("/careers", "/careers/", "/career", "/jobs", "/en/careers"):
                url = f"https://www.{slug}{dom}{path}"
                try:
                    html_ = fetch(url, timeout=12)
                except Exception:
                    continue
                cfg = from_page(name, url, html_)
                if cfg:
                    return cfg, f"מצאתי את עמוד הקריירה {url} ({cfg['type']})"
                break  # domain exists but unknown system: try next domain
    return None, None
