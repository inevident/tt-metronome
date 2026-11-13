#!/usr/bin/env python3
"""the long verification runs, spread over many cores. meant for a cluster.

runs many copies of the cocotb tests with different seeds, on rtl and on a
gate-level netlist, then the mutation tests. writes results/summary-*.txt.

  python tools/heavy_suite.py --jobs 48
"""

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_tests(tag, extra):
    cmd = [sys.executable, str(ROOT / "test" / "run.py"), "--tag", tag] + extra
    out = subprocess.run(cmd, capture_output=True, text=True)
    text = out.stdout + out.stderr
    (ROOT / "results" / f"{tag}.log").write_text(text)
    last = [l for l in text.splitlines() if "tests passed" in l]
    return tag, out.returncode == 0, last[-1].strip() if last else "no summary line"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--seeds", type=int, default=24, help="parallel runs per configuration")
    ap.add_argument("--programs", type=int, default=250, help="random programs per run")
    a = ap.parse_args()
    (ROOT / "results").mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    lines = [f"heavy suite {stamp}, {a.jobs} jobs"]

    plan = []
    for s in range(a.seeds):
        plan.append((f"rtl2_s{100 + s}", ["--programs", str(a.programs), "--seed", str(100 + s)]))
    for s in range(a.seeds // 2):
        plan.append((f"rtl4_s{200 + s}", ["--nt", "4", "--pw", "6", "--ramb", "16",
                                           "--programs", str(a.programs * 3 // 5), "--seed", str(200 + s)]))
    for s in range(a.seeds // 2):
        plan.append((f"gate2_s{300 + s}", ["--gates", "--programs", str(a.programs * 2 // 5), "--seed", str(300 + s)]))

    t0 = time.time()
    failed = 0
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for tag, ok, summary in pool.map(lambda p: run_tests(*p), plan):
            failed += not ok
            lines.append(f"{'ok  ' if ok else 'FAIL'} {tag:14s} {summary}")
    rtl2 = a.seeds * a.programs
    rtl4 = (a.seeds // 2) * (a.programs * 3 // 5)
    gate = (a.seeds // 2) * (a.programs * 2 // 5)
    lines.append(f"random programs: {rtl2} RTL (2 threads), {rtl4} RTL (4 threads), {gate} gate-level; "
                 f"{failed} of {len(plan)} runs failed; {time.time() - t0:.0f} s")

    env = dict(os.environ, METRO_WORKERS=str(a.jobs))
    mut = subprocess.run([sys.executable, str(ROOT / "tools" / "mutation_test.py")],
                         capture_output=True, text=True, env=env)
    (ROOT / "results" / f"mutation-{stamp}.log").write_text(mut.stdout + mut.stderr)
    lines += ["", "mutation testing:"] + mut.stdout.strip().splitlines()

    summary = ROOT / "results" / f"summary-{stamp}.txt"
    summary.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(1 if failed or mut.returncode else 0)


if __name__ == "__main__":
    main()
