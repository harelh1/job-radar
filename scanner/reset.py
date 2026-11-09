"""Forget all scan history (next scan re-initialises every company, sending one digest)."""
import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("state/seen.json", "docs/data/jobs.json", "docs/data/companies.json"):
    try:
        os.remove(os.path.join(ROOT, p))
    except FileNotFoundError:
        pass
path = os.path.join(ROOT, "companies.json")
d = json.load(open(path, encoding="utf-8"))
for c in d["companies"]:
    c.pop("status", None); c.pop("initialized", None)
json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("reset done")
