"""Re-read and re-score jobs after changing scoring rules, without sending alerts.

  python scanner/rescore.py Opsys      # one company
  python scanner/rescore.py --all      # every company
Then run scan.py: the jobs are re-read and re-scored; already-seen jobs do not alert again.
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS = os.path.join(ROOT, "docs", "data", "jobs.json")
if len(sys.argv) < 2:
    sys.exit(__doc__)
d = json.load(open(JOBS, encoding="utf-8"))
name = sys.argv[1]
d["jobs"] = [] if name == "--all" else [j for j in d["jobs"] if j["company"] != name]
json.dump(d, open(JOBS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"cleared cached jobs of {name}; run scan.py to re-score")
