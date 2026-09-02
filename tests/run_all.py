# -*- coding: utf-8 -*-
"""Runs every test_*.py suite in a subprocess; exits 1 if any fails.
Run:  python tests/run_all.py   (or run_tests.bat from the repo root)
Benchmarks (bench_*.py) are NOT run here — they build a large temp DB and take a minute+."""
import os, sys, subprocess, glob
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # קונסולה בעברית/CP1255 לא תפיל הדפסות
here = os.path.dirname(os.path.abspath(__file__))
failed = []
for path in sorted(glob.glob(os.path.join(here, "test_*.py"))):
    name = os.path.basename(path)
    r = subprocess.run([sys.executable, path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    ok = r.returncode == 0
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failed.append(name); print(r.stdout[-3000:]); print(r.stderr[-2000:])
print()
print("ALL SUITES PASSED" if not failed else "FAILED: " + ", ".join(failed))
sys.exit(1 if failed else 0)
