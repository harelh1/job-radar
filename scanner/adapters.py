"""One fetcher per careers-site system (ATS).

Each adapter takes the company's config dict and returns a list of jobs:
  {key, title, url, location, department, description, posted}
`key` must be stable for the same job across scans.
"""
import re
import urllib.parse

from net import fetch, fetch_json, strip_html

ISRAEL_WORDS = [
    "israel", "ישראל", "tel aviv", "tel-aviv", "תל אביב", "jerusalem", "ירושלים", "haifa", "חיפה",
    "herzliya", "הרצליה", "petah tikva", "petach tikva", "פתח תקווה", "ra'anana", "raanana", "רעננה",
    "rehovot", "רחובות", "yokneam", "yokne'am", "יקנעם", "netanya", "נתניה", "kfar saba", "כפר סבא",
    "hod hasharon", "הוד השרון", "ness ziona", "nes ziona", "נס ציונה", "migdal haemek", "migdal ha'emek",
    "מגדל העמק", "kiryat gat", "קרית גת", "beer sheva", "be'er sheva", "באר שבע", "rosh haayin",
    "rosh ha'ayin", "ראש העין", "caesarea", "קיסריה", "holon", "חולון", "modiin", "modi'in", "מודיעין",
    "airport city", "lod", "לוד", "ramat gan", "רמת גן", "or yehuda", "אור יהודה", "karmiel", "כרמיאל",
    "nazareth", "נצרת", "yavne", "יבנה", "ashdod", "אשדוד", "rishon", "ראשון", "kiryat shmona",
    "dimona", "דימונה", "sderot", "שדרות", "afula", "עפולה", "nesher", "tirat carmel", "טירת כרמל",
    "bnei brak", "בני ברק", "givatayim", "rosh pina", "omer", "ma'alot", "maalot", "kiryat ata",
    "beit shemesh", "בית שמש", "har hotzvim", "yakum", "kiryat bialik", "mevaseret", "netivot",
    "ariel", "kfar yona", "even yehuda", "tefen", "misgav", "kiryat tivon", "ofakim", "ramla", "רמלה",
]


_ISRAEL_RE = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(w) for w in ISRAEL_WORDS) + r")(?!\w)", re.I)


def in_israel(*texts):
    return bool(_ISRAEL_RE.search(" ".join(x for x in texts if x)))


# ---------------------------------------------------------------- Comeet
def comeet(c):
    url = (f"https://www.comeet.co/careers-api/2.0/company/{c['uid']}/positions"
           f"?token={c['token']}&details=true")
    out = []
    for p in fetch_json(url):
        loc = p.get("location") or {}
        desc = " ".join(strip_html(d.get("value")) for d in (p.get("details") or []))
        out.append({
            "key": p.get("uid"),
            "title": p.get("name", ""),
            "url": p.get("url_active_page") or p.get("url_comeet_hosted_page") or p.get("position_url"),
            "location": ", ".join(x for x in [loc.get("city"), loc.get("country")] if x),
            "department": p.get("department") or "",
            "employment": p.get("employment_type") or "",
            "description": desc,
            "posted": p.get("time_updated") or "",
        })
    return out


# ---------------------------------------------------------------- Workday
def workday(c):
    host, tenant, site = c["host"], c["tenant"], c["site"]
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    out, offset, total = [], 0, None
    while True:
        body = {"appliedFacets": {}, "limit": 20, "offset": offset,
                "searchText": c.get("search", "Israel")}
        j = fetch_json(base + "/jobs", body)
        posts = j.get("jobPostings") or []
        if total is None:          # Workday only reports the total on the first page
            total = j.get("total") or 0
        for p in posts:
            path = p.get("externalPath", "")
            out.append({
                "key": path.rsplit("_", 1)[-1] or path,
                "title": p.get("title", ""),
                "url": f"https://{host}/{site}{path}",
                "location": p.get("locationsText", ""),
                "department": "",
                "description": "",
                "posted": p.get("postedOn", ""),
                "_detail": base + path,
            })
        offset += 20
        if not posts or offset >= total or offset > 1000:
            break
    return out


def workday_detail(job):
    """Fetch description + real locations for one Workday job (only for new jobs)."""
    try:
        d = fetch_json(job["_detail"]).get("jobPostingInfo", {})
        job["description"] = strip_html(d.get("jobDescription", ""))
        locs = [d.get("location", "")] + (d.get("additionalLocations") or [])
        job["location"] = ", ".join(x for x in locs if x) or job["location"]
        job["employment"] = d.get("timeType", "")
    except Exception:
        pass


# ---------------------------------------------------------------- Greenhouse
def greenhouse(c):
    j = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{c['slug']}/jobs?content=true")
    return [{
        "key": str(p["id"]), "title": p.get("title", ""), "url": p.get("absolute_url"),
        "location": (p.get("location") or {}).get("name", ""),
        "department": ", ".join(d.get("name", "") for d in p.get("departments") or []),
        "description": strip_html(p.get("content", "")), "posted": p.get("updated_at", ""),
    } for p in j.get("jobs", [])]


# ---------------------------------------------------------------- Lever
def lever(c):
    j = fetch_json(f"https://api.lever.co/v0/postings/{c['slug']}?mode=json")
    return [{
        "key": p["id"], "title": p.get("text", ""), "url": p.get("hostedUrl"),
        "location": (p.get("categories") or {}).get("location", ""),
        "department": (p.get("categories") or {}).get("team", ""),
        "employment": (p.get("categories") or {}).get("commitment", ""),
        "description": p.get("descriptionPlain", "") + " " + " ".join(
            strip_html(l.get("content", "")) for l in p.get("lists") or []),
        "posted": str(p.get("createdAt", "")),
    } for p in j]


# ---------------------------------------------------------------- SmartRecruiters
def smartrecruiters(c):
    out, offset = [], 0
    while True:
        j = fetch_json(f"https://api.smartrecruiters.com/v1/companies/{c['slug']}/postings"
                       f"?limit=100&offset={offset}&country=il")
        for p in j.get("content", []):
            loc = p.get("location") or {}
            out.append({
                "key": p["id"], "title": p.get("name", ""),
                "url": f"https://jobs.smartrecruiters.com/{c['slug']}/{p['id']}",
                "location": ", ".join(x for x in [loc.get("city"), loc.get("country")] if x),
                "department": (p.get("department") or {}).get("label", ""),
                "description": "", "posted": p.get("releasedDate", ""),
            })
        offset += 100
        if offset >= j.get("totalFound", 0):
            break
    return out


# ---------------------------------------------------------------- Ashby
def ashby(c):
    j = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{c['slug']}")
    return [{
        "key": p["id"], "title": p.get("title", ""), "url": p.get("jobUrl"),
        "location": p.get("location", ""), "department": p.get("department", ""),
        "employment": p.get("employmentType", ""),
        "description": p.get("descriptionPlain", ""), "posted": p.get("publishedAt", ""),
    } for p in j.get("jobs", [])]


# ---------------------------------------------------------------- Workable
def workable(c):
    j = fetch_json(f"https://apply.workable.com/api/v1/widget/accounts/{c['slug']}?details=true")
    return [{
        "key": p.get("shortcode") or p.get("id"), "title": p.get("title", ""),
        "url": p.get("url") or p.get("application_url") or f"https://apply.workable.com/{c['slug']}/j/{p.get('shortcode')}/",
        "location": ", ".join(x for x in [p.get("city"), p.get("country")] if x),
        "department": p.get("department", ""), "employment": p.get("employment_type", ""),
        "description": strip_html(p.get("description", "")), "posted": p.get("published_on", ""),
    } for p in j.get("jobs", [])]


# ---------------------------------------------------------------- Elbit (public JSON feed)
def elbit(c):
    j = fetch_json("https://elbitsystemscareer.com/cron/jobs.json")
    out = []
    for p in j:
        if p.get("status") not in (None, 1):
            continue
        desc = " ".join(strip_html(p.get(k)) for k in ("description", "requirements", "skills"))
        city = ""
        m = re.search(r"(?:site|sites) in ([A-Z][A-Za-z' -]+?)[,.]", desc)
        if m:
            city = m.group(1)
        out.append({
            "key": str(p["jobId"]),
            "title": p.get("jobTitle", ""),
            "url": f"https://elbitsystemscareer.com/job/?jid={p['jobId']}",
            "location": ", ".join(x for x in [city or p.get("area") or "", "Israel"] if x),
            "department": p.get("employerName", ""),
            "description": desc,
            "posted": p.get("openDate", ""),
            "code": p.get("jobCode", ""),
        })
    return out


# ---------------------------------------------------------------- SCD (WordPress accordion list, paginated)
def scd(c):
    base = c.get("url", "https://www.scd-infrared.com/find-a-job/")
    out, seen = [], set()
    for page_no in range(1, 15):
        url = base if page_no == 1 else f"{base.rstrip('/')}/page/{page_no}/"
        try:
            page = fetch(url)
        except Exception:
            if page_no == 1:
                raise
            break
        items = re.split(r'<div class="acc_item">', page)[1:]
        if not items:
            break
        for it in items:
            m = re.search(r'<h2 class=["\']acc_title["\']>(.*?)<div class=["\']job_term["\']>(.*?)</div>', it, re.S)
            if not m:
                continue
            title = strip_html(re.sub(r'<div class=["\']plus_anim["\']>.*?</div>', "", m.group(1), flags=re.S))
            if not title or title in seen:
                continue
            seen.add(title)
            d = re.search(r'<div class="acc_desc">(.*?)(?:<form|<div class="float_form"|$)', it, re.S)
            out.append({"key": title, "title": title, "url": base, "location": "Misgav, Israel",
                        "department": strip_html(m.group(2)), "description": strip_html(d.group(1) if d else "")[:8000],
                        "posted": ""})
    return out


# ---------------------------------------------------------------- careers-page.com
def careerspage(c):
    html_ = fetch(f"https://careers-page.com/{c['slug']}")
    out, seen = [], set()
    for m in re.finditer(r'href="(/' + re.escape(c["slug"]) + r'/job/([A-Z0-9]+))"[^>]*>(.*?)</a>', html_, re.S):
        if m.group(2) in seen:
            continue
        seen.add(m.group(2))
        out.append({"key": m.group(2), "title": strip_html(m.group(3)),
                    "url": "https://careers-page.com" + m.group(1), "location": c.get("location", ""),
                    "department": "", "description": "", "posted": "", "_page": True})
    return out


# ---------------------------------------------------------------- generic "links on a page"
GENERIC_JOB_LINK = r"(?:job|jobs|career|careers|position|positions|opening|vacanc|משרה|משרות|דרושים)[/_=-]"


def links(c):
    """Watch any careers page: every link matching `pattern` is a job.
    Works for server-rendered pages. Title = link text, or derived from the URL slug."""
    page = fetch(c["url"])
    pat = re.compile(c.get("pattern") or GENERIC_JOB_LINK, re.I)
    out, seen = [], set()
    for m in re.finditer(r'<a\b[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', page, re.S | re.I):
        href = urllib.parse.urljoin(c["url"], m.group(1))
        if not pat.search(href) or href.rstrip("/") == c["url"].rstrip("/") or href in seen:
            continue
        seen.add(href)
        text = strip_html(m.group(2))
        generic = not text or len(text) < 4 or re.fullmatch(r"(?:" + GENERIC_TEXT + r")[\s>»›→←‹«<.:!-]*", text, re.I)
        if generic:
            slug = [s for s in urllib.parse.urlparse(href).path.split("/") if s]
            words = [s for s in slug if not re.fullmatch(
                r"[0-9a-f-]{8,}|[0-9A-F]{2}\.[0-9A-F]{3}.*|\d+|jobs?|careers?|(?:open-)?positions?|openings?|vacancies|en|he",
                s, re.I)]
            text = (words[-1] if words else "").replace("-", " ").replace("_", " ").strip().title()
        out.append({"key": href, "title": text[:150], "url": href, "location": c.get("location", ""),
                    "department": "", "description": "", "posted": "", "_page": True,
                    "_need_title": not text})
    return out


GENERIC_TEXT = (r"apply( now)?|read more|more( info)?|details|view( job| position)?|learn more|לפרטים|"
                r"הגש(ת)? מועמדות|למשרה|קרא עוד|לפרטים נוספים|view open positions|search jobs|job alerts")

FOREIGN = re.compile(r"\b(india|bangalore|bengaluru|germany|munich|usa|u\.s\.|united states|detroit|california|"
                     r"texas|china|shanghai|beijing|japan|tokyo|korea|uk|united kingdom|london|france|paris|italy|"
                     r"spain|netherlands|canada|mexico|taiwan|singapore|poland|hungary|romania|emea|apac)\b", re.I)


def page_detail(job, need_location):
    """For page-based adapters: read the job page itself for scoring text, title and location."""
    try:
        page = fetch(job["url"])
        if job.get("_need_title"):
            cands = []
            for rx in (r"<h1[^>]*>(.*?)</h1>", r"<title[^>]*>(.*?)</title>"):
                m = re.search(rx, page, re.S | re.I)
                if m:
                    cands += [s.strip() for s in re.split(r"\s[|–—]\s|\|", strip_html(m.group(1)))]
            cands = [s for s in cands if len(s) > 3 and not s.isdigit() and s.lower() not in ("careers", "jobs")]
            job["title"] = max(cands, key=len)[:150] if cands else job["url"]
        txt = strip_html(page)[:15000]
        job["description"] = txt
        if need_location and not job["location"]:
            if FOREIGN.search(job["title"]) and not in_israel(job["title"]):
                job["location"] = ""
            else:
                job["location"] = "Israel" if in_israel(txt) else ""
    except Exception:
        pass


ADAPTERS = {
    "comeet": comeet, "workday": workday, "greenhouse": greenhouse, "lever": lever,
    "smartrecruiters": smartrecruiters, "ashby": ashby, "workable": workable, "elbit": elbit,
    "careerspage": careerspage, "links": links, "scd": scd,
}
