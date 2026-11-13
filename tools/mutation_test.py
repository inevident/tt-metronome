#!/usr/bin/env python3
"""mutation testing: break the verilog on purpose and check the tests notice.

each mutation is one small, plausible bug. the tests must fail on it. one that
survives means the tests have a blind spot there.

  python tools/mutation_test.py            run every mutation
  python tools/mutation_test.py 3 7        run only mutations 3 and 7
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROGRAMS = os.environ.get("METRO_MUT_PROGRAMS", "60")   # random programs per mutant; directed programs always run
WORKERS = int(os.environ.get("METRO_WORKERS", "2"))        # mutants simulated at once
CORE = (ROOT / "src" / "metro_core.v").read_text()

# (description, text to find, replacement)
MUTATIONS = [
    ("ADC ignores the carry", "(fn == 4'd2) & cq", "1'b0"),
    ("SUB/SBC borrow flag inverted",
     "4'd3, 4'd4: begin alu_r = sub_s[7:0]; alu_c = sub_s[8];", "4'd3, 4'd4: begin alu_r = sub_s[7:0]; alu_c = ~sub_s[8];"),
    ("DJNZ loops one time too many", "if (a != 8'd1) npc = tgt;", "if (a != 8'd0) npc = tgt;"),
    ("JAL saves pc instead of pc+1", "rwd[PW-1:0] = pc1;", "rwd[PW-1:0] = pc[t];"),
    ("using a tick does not clear it",
     "else if (do_ && t == i2[TI-1:0] && consume)  tick[i2] <= 1'b0;", ""),
    ("timer period one clock short",
     "cnt[i2] <= (cnt[i2] == 16'd0) ? per[i2] : cnt[i2] - 16'd1;",
     "cnt[i2] <= (cnt[i2] == 16'd0) ? per[i2] - 16'd1 : cnt[i2] - 16'd1;"),
    ("overrun flag never set", "ovr[i2] <= 1'b1;", "ovr[i2] <= 1'b0;"),
    ("TPH loads the full period", "trst ? per[i2] : {1'b0, per[i2][15:1]}", "per[i2]"),
    ("open-drain drives high instead of releasing",
     "(uio_e & ~uio_d) | (uio_d & ~uio_o)", "(uio_e & ~uio_d) | (uio_d & uio_o)"),
    ("WAIT timeout leaves C clear", "wc = 1'b1; nc = 1'b1; consume = 1'b1;", "wc = 1'b1; nc = 1'b0; consume = 1'b1;"),
    ("START takes effect one slot late", "if (do_ && start && xx == i1[1:0]) begin", "if (1'b0 && start && xx == i1[1:0]) begin"),
    ("SCHED takes effect one clock late",
     "wire [7:0] sched_nx = (do_ & sched_w) ? imm : sched;", "wire [7:0] sched_nx = sched;"),
    ("INL shifts the wrong way", "2'd2: rwd = {pinv, a[7:1]};", "2'd2: rwd = {a[6:0], pinv};"),
    ("GETC reads the output latch, not the pin", "4'd4: begin wc = 1'b1; nc = pinv;", "4'd4: begin wc = 1'b1; nc = latv;"),
    ("only one synchroniser flop on ui", "s2_ui  <= s1_ui;", "s2_ui  <= ui_in;"),
    ("loader shifts LSB first", "wire [15:0] l_word = {shreg[14:0], l_mosi};", "wire [15:0] l_word = {l_mosi, shreg[14:0]};"),
    ("a stalled instruction still takes effect", "wire do_ = ex & ~stall;", "wire do_ = ex;"),
    ("a halted thread runs one more slot", "if (do_ && t == i1[TI-1:0] && halt)  f_run = 1'b0;", ""),
    ("CMPI carry uses <= instead of <", "nc = (a < imm);", "nc = (a <= imm);"),
    ("TSTAT bits swapped", "{6'b0, ovr[t], tk}", "{6'b0, tk, ovr[t]}"),
    ("STOP does not stop the thread", "if (stop && xx == i2[1:0]) run[i2] <= 1'b0;", ""),
    ("START does not clear the fault flag",
     "run[i2] <= 1'b1;  fault[i2] <= 1'b0;  pc[i2] <= tgt;", "run[i2] <= 1'b1;  pc[i2] <= tgt;"),
    ("LD/ST use the immediate as the address", "(op == 4'hB) ? imm[RW-1:0] : b[RW-1:0];", "imm[RW-1:0];"),
    ("ROR drops the carry", "4'd12:      begin alu_r = {cq, b[7:1]};", "4'd12:      begin alu_r = {1'b0, b[7:1]};"),
    ("chip starts with no program loaded", "if (l_cs & ~cs_d & loaded) running <= 1'b1;", "if (l_cs & ~cs_d) running <= 1'b1;"),
    ("branch on tick uses the wrong thread's tick", "4'd5: take = tk;", "4'd5: take = tick[0];"),
]


def run_one(k):
    desc, find, repl = MUTATIONS[k]
    if CORE.count(find) != 1:
        return desc, f"SKIPPED: pattern found {CORE.count(find)} times (update the list)"
    work = ROOT / "test" / "sim_build" / f"mutant_{k}"
    shutil.rmtree(work, ignore_errors=True)
    (work / "src").mkdir(parents=True)
    (work / "src" / "metro_core.v").write_text(CORE.replace(find, repl))
    shutil.copy(ROOT / "src" / "project.v", work / "src" / "project.v")
    out = subprocess.run([sys.executable, str(ROOT / "test" / "run.py"), "--src", str(work / "src"),
                          "--tag", f"mutant{k}", "--programs", PROGRAMS, "--clocks", "1500"],
                         capture_output=True, text=True)
    text = out.stdout + out.stderr
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(ROOT / "test" / "sim_build" / f"rtl_nt2_pw5_ram8_mutant{k}", ignore_errors=True)
    if out.returncode == 0:
        return desc, "SURVIVED: every test still passed"
    m = re.search(r"AssertionError: (.*?clock \d+.*?): (\w+)", text)
    return desc, "caught" + (f" ({m.group(1).strip()}: {m.group(2)})" if m else "")


def main():
    from concurrent.futures import ThreadPoolExecutor
    picks = [int(a) for a in sys.argv[1:]] or list(range(len(MUTATIONS)))
    survived = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for k, (desc, verdict) in zip(picks, pool.map(run_one, picks)):
            survived += verdict.startswith(("SURVIVED", "SKIPPED"))
            print(f"{k:2d}  {desc:45s} {verdict}", flush=True)
    print(f"\n{len(picks) - survived} of {len(picks)} mutations caught")
    sys.exit(1 if survived else 0)


if __name__ == "__main__":
    main()
