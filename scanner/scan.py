"""Job Radar - scan company careers sites, score jobs, alert on Telegram.

Usage:
  python scanner/scan.py                     # one scan
  python scanner/scan.py --loop 540          # keep scanning for 540s (used by GitHub Actions)
  python scanner/scan.py --git               # commit + push data changes after each scan
  python scanner/scan.py --only "Lumus"      # scan a single company (testing)
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))
import telegram as tg  # noqa: E402
from adapters import ADAPTERS, in_israel, page_detail, workday_detail  # noqa: E402
from detect import detect  # noqa: E402
from scoring import score  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)  # noqa: E731
COMPANIES = P("companies.json")
SETTINGS = P("settings.json")
SEEN = P("state", "seen.json")
JOBS_OUT = P("docs", "data", "jobs.json")
COMP_OUT = P("docs", "data", "companies.json")


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ------------------------------------------------------------------ scanning one company
def scan_company(c, known):
    """Return (jobs, error). `known` = {key: previous job record} to avoid re-fetching details."""
    try:
        raw = ADAPTERS[c["type"]](c)
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:120]}"
    jobs = []
    fresh = [j for j in raw if f"{c['name']}|{j['key']}" not in known]
    # details only for jobs we haven't scored before
    need = [j for j in fresh if j.get("_detail") or j.get("_page")]
    if need:
        with cf.ThreadPoolExecutor(8) as ex:
            list(ex.map(lambda j: workday_detail(j) if j.get("_detail")
                        else page_detail(j, c.get("need_israel_check", False)), need))
    for j in raw:
        jid = f"{c['name']}|{j['key']}"
        rec = known.get(jid, j)
        if c.get("israel_only") or c.get("need_israel_check"):
            if not in_israel(rec.get("location"), rec.get("title")):
                continue
        if jid in known:
            jobs.append(known[jid])
            continue
        pct, reasons, kind = score(j)
        jobs.append({
            "id": jid, "company": c["name"], "title": j["title"].strip(), "url": j.get("url") or c.get("url", ""),
            "location": (j.get("location") or "").strip(", "), "department": j.get("department", ""),
            "posted": j.get("posted", ""), "score": pct, "reasons": reasons, "kind": kind,
            "tags": c.get("tags", []),
        })
    return jobs, None


# ------------------------------------------------------------------ telegram commands
HELP = ("🤖 <b>Job Radar</b>\n"
        "/add שם חברה – להוסיף חברה למעקב\n"
        "/add שם חברה https://קישור-לעמוד-משרות – אם לא מצאתי לבד\n"
        "/remove שם חברה – להסיר\n"
        "/list – רשימת החברות\n"
        "/top – 10 המשרות הכי מתאימות שפתוחות עכשיו (✨ = חדש מאז הפעם הקודמת)\n"
        "/top 20 – אותו דבר עם 20 משרות\n"
        "/min 60 – לשנות את סף ההתראה (אחוז התאמה מינימלי)")


def ranked_message(all_jobs, state, header, n=10):
    """Top-n open jobs by score. Jobs that weren't in any earlier ranked list get a ✨ badge;
    jobs from the previous list that have since closed are listed at the end."""
    shown = set(state.get("shown", []))
    open_ids = {j["id"] for j in all_jobs}
    top = sorted(all_jobs, key=lambda j: (-j["score"], j.get("first_seen", "")))[:n]
    prev_rank = {x["id"]: i for i, x in enumerate(state.get("last_ranked", []), 1)}
    parts, n_new = [header], 0
    for i, j in enumerate(top, 1):
        badge = None
        if shown and j["id"] not in shown:
            badge, n_new = "חדש ברשימה", n_new + 1
        elif j["id"] in prev_rank and prev_rank[j["id"]] > i:
            badge = f"עלה מ-#{prev_rank[j['id']]}"
        parts.append(tg.job_message(j, rank=i, badge=badge))
    if shown:
        parts.insert(1, f"✨ <b>{n_new} חדשות</b> מאז הרשימה הקודמת" if n_new else "אין משרות חדשות ברשימה מאז הפעם הקודמת")
    closed = [x for x in state.get("last_ranked", []) if x["id"] not in open_ids]
    if closed:
        parts.append("❌ <b>נסגרו מאז הרשימה הקודמת:</b>\n" +
                     "\n".join(f"• {tg.esc(x['title'])} ({tg.esc(x['company'])})" for x in closed))
    state["shown"] = sorted(shown | {j["id"] for j in top})
    state["last_ranked"] = [{"id": j["id"], "title": j["title"], "company": j["company"]} for j in top]
    return "\n\n".join(parts)


def handle_commands(companies, settings, state, jobs_by_company):
    ups = tg.updates(state.get("tg_offset", 0))
    added = []
    for u in ups:
        state["tg_offset"] = u["update_id"] + 1
        msg = u.get("message") or {}
        chat = str((msg.get("chat") or {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            continue
        if not tg.CHAT_ID:
            tg.send(f"ה-Chat ID שלך: <code>{chat}</code>\nהכנס אותו ב-GitHub כ-Secret בשם TELEGRAM_CHAT_ID", chat)
            continue
        if chat != tg.CHAT_ID:
            continue
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        arg = arg.strip()
        if cmd in ("/start", "/help"):
            tg.send(HELP)
        elif cmd == "/list":
            lines = [f"{'✅' if c.get('status', {}).get('ok', True) else '⚠️'} {tg.esc(c['name'])} "
                     f"({len(jobs_by_company.get(c['name'], []))})" for c in companies["companies"]]
            if companies.get("pending"):
                lines.append("\n⏳ ממתינות לזיהוי: " + ", ".join(tg.esc(p["name"]) for p in companies["pending"]))
            tg.send(f"<b>{len(companies['companies'])} חברות במעקב</b>\n" + "\n".join(lines))
        elif cmd == "/min" and arg.isdigit():
            settings["alert_min_score"] = max(1, min(99, int(arg)))
            tg.send(f"סף ההתראה עודכן ל-{settings['alert_min_score']}%")
        elif cmd == "/top":
            n = max(1, min(30, int(arg))) if arg.isdigit() else 10
            allj = [j for js in jobs_by_company.values() for j in js]
            tg.send(ranked_message(allj, state, f"<b>🏆 {n} המשרות הכי מתאימות שפתוחות עכשיו</b>", n))
        elif cmd == "/remove" and arg:
            before = len(companies["companies"])
            companies["companies"] = [c for c in companies["companies"] if c["name"].lower() != arg.lower()]
            companies["pending"] = [p for p in companies.get("pending", []) if p["name"].lower() != arg.lower()]
            tg.send("הוסר ✔" if len(companies["companies"]) < before else "לא מצאתי חברה בשם הזה")
        elif cmd == "/add" and arg:
            url = None
            parts = arg.split()
            if parts[-1].startswith("http"):
                url = parts.pop()
            name = " ".join(parts) or url
            if any(c["name"].lower() == name.lower() for c in companies["companies"]) and not url:
                tg.send(f"{tg.esc(name)} כבר במעקב 👍")
                continue
            tg.send(f"🔎 מחפש את עמוד המשרות של {tg.esc(name)}...")
            cfg, why = detect(name, url)
            if cfg:
                cfg = {"name": name, **cfg, "added": now(), "added_by": "telegram"}
                if url:
                    cfg["careers_url"] = url
                companies["companies"] = [c for c in companies["companies"] if c["name"].lower() != name.lower()]
                companies["companies"].append(cfg)
                companies["pending"] = [p for p in companies.get("pending", []) if p["name"].lower() != name.lower()]
                added.append(name)
                tg.send(f"✅ {tg.esc(name)} נוספה למעקב – {tg.esc(why)}. סורק עכשיו...")
            else:
                if not any(p["name"].lower() == name.lower() for p in companies.setdefault("pending", [])):
                    companies["pending"].append({"name": name, "url": url, "requested": now(), "reason": why})
                tg.send(f"⏳ לא מצאתי אוטומטית את עמוד המשרות של {tg.esc(name)}"
                        + (f" ({tg.esc(why)})" if why else "") +
                        ".\nשלח: <code>/add " + tg.esc(name) + " https://...</code> עם קישור לעמוד המשרות, "
                        "או בקש מ-Claude להוסיף אותה (היא נשמרה ברשימת הממתינות).")
    return added


# ------------------------------------------------------------------ one full pass
def run_once(args):
    companies = load(COMPANIES, {"companies": [], "pending": []})
    settings = load(SETTINGS, {"alert_min_score": 55})
    state = load(SEEN, {"seen": {}, "tg_offset": 0})
    prev = load(JOBS_OUT, {"jobs": []})
    known = {j["id"]: j for j in prev.get("jobs", [])}
    jobs_by_company = {}
    for j in prev.get("jobs", []):
        jobs_by_company.setdefault(j["company"], []).append(j)

    tg_offset0, settings0 = state.get("tg_offset"), json.dumps(settings)
    ok0 = {c["name"]: c.get("status", {}).get("ok") for c in companies["companies"]}
    newly_added = handle_commands(companies, settings, state, jobs_by_company)
    if tg.enabled() and not tg.CHAT_ID:
        save(SEEN, state)
        print("TELEGRAM_CHAT_ID not set yet - send /start to the bot to get it. Not scanning until then.")
        return True

    todo = [c for c in companies["companies"] if c.get("enabled", True)
            and (not args.only or c["name"].lower() == args.only.lower())]
    results = {}
    with cf.ThreadPoolExecutor(10) as ex:
        futs = {ex.submit(scan_company, c, known): c for c in todo}
        for f in cf.as_completed(futs):
            results[futs[f]["name"]] = f.result()

    min_score = settings.get("alert_min_score", 55)
    alerts, summaries = [], []
    first_run = not any(state["seen"].values())  # nothing watched before this pass
    for c in todo:
        jobs, err = results[c["name"]]
        st = c.setdefault("status", {})
        if err:
            st.update(ok=False, error=err, last_try=now())
            print(f"  ✗ {c['name']}: {err}")
            continue  # keep previous jobs of this company
        st.update(ok=True, error=None, last_ok=now(), count=len(jobs))
        seen = state["seen"].setdefault(c["name"], {})
        initialized = bool(seen) or c.get("initialized")
        new = [j for j in jobs if j["id"].split("|", 1)[1] not in seen]
        for j in new:
            j["first_seen"] = now()
            seen[j["id"].split("|", 1)[1]] = j["first_seen"]
        for j in jobs:
            j.setdefault("first_seen", seen.get(j["id"].split("|", 1)[1], now()))
        if not initialized:
            c["initialized"] = True
            for j in jobs:
                j["initial"] = True  # existed before we started watching - not "new"
            top = sorted([j for j in jobs if j["score"] >= min_score], key=lambda j: -j["score"])[:5]
            summaries.append((c["name"], len(jobs), top))
        else:
            alerts += [j for j in new if j["score"] >= min_score]
        jobs_by_company[c["name"]] = jobs
        print(f"  ✓ {c['name']}: {len(jobs)} jobs ({len(new)} new)")

    # drop jobs of companies that were removed
    names = {c["name"] for c in companies["companies"]}
    jobs_by_company = {k: v for k, v in jobs_by_company.items() if k in names}

    # notify
    for j in sorted(alerts, key=lambda j: -j["score"]):
        tg.send("🆕 <b>משרה חדשה!</b>\n" + tg.job_message(j))
    total_companies = len(companies["companies"])
    all_jobs = sorted((j for js in jobs_by_company.values() for j in js),
                      key=lambda j: (-j["score"], j.get("first_seen", "")))
    if summaries:
        if first_run:
            head = (f"🚀 <b>Job Radar פעיל!</b> התחלתי לעקוב אחרי {len(summaries)} חברות "
                    f"({sum(n for _, n, _ in summaries)} משרות פתוחות בישראל).\n"
                    f"מעכשיו תקבל הודעה על כל משרה חדשה עם {min_score}%+ התאמה.")
        else:
            head = (f"📥 <b>נוספו למעקב:</b> " + ", ".join(f"{tg.esc(n)} ({c} משרות)" for n, c, _ in summaries)
                    + f"\nסה\"כ במעקב: {total_companies} חברות, {len(all_jobs)} משרות פתוחות בישראל.")
        tg.send(ranked_message(all_jobs, state, head + "\n\n<b>🏆 10 המשרות הכי מתאימות מכל החברות:</b>"))
    save(JOBS_OUT, {"updated": now(), "alert_min_score": min_score, "jobs": all_jobs})
    save(COMP_OUT, {"updated": now(), "pending": companies.get("pending", []),
                    "companies": [{k: c.get(k) for k in ("name", "type", "tags", "status", "careers_url", "note")}
                                  for c in companies["companies"]]})
    save(COMPANIES, companies)
    save(SETTINGS, settings)
    save(SEEN, state)
    print(f"[{now()}] scanned {len(todo)} companies, {len(all_jobs)} jobs, {len(alerts)} alerts")
    changed = ({j["id"] for j in all_jobs} != set(known)) or state.get("tg_offset") != tg_offset0 \
        or json.dumps(settings) != settings0 or ok0 != {c["name"]: c.get("status", {}).get("ok") for c in todo}
    return changed


def git_sync(changed, force):
    """Commit only real changes (new/removed jobs, commands, errors) - or every ~30 min for timestamps."""
    def g(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    if not (changed or force):
        return
    g("add", "-A", "companies.json", "settings.json", "state", "docs/data")
    if not g("diff", "--cached", "--name-only").stdout.strip():
        return
    g("commit", "-q", "-m", "scan: update jobs")
    for _ in range(3):
        if g("push", "-q").returncode == 0:
            return
        g("pull", "-q", "--rebase", "-X", "theirs")
    print("git push failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="keep scanning for N seconds")
    ap.add_argument("--git", action="store_true")
    ap.add_argument("--only")
    args = ap.parse_args()
    interval = load(SETTINGS, {}).get("scan_interval_sec", 150)
    start, last_push = time.time(), 0
    while True:
        t0 = time.time()
        changed = run_once(args)
        if args.git:
            force = time.time() - last_push > 1800
            git_sync(changed, force)
            if changed or force:
                last_push = time.time()
        left = args.loop - (time.time() - start)
        if left < interval + 30:
            break
        # wait, but react to Telegram commands within ~20s
        until = t0 + interval
        while time.time() < until:
            time.sleep(5)
            if tg.enabled() and tg.updates(load(SEEN, {}).get("tg_offset", 0)):
                break


if __name__ == "__main__":
    main()
