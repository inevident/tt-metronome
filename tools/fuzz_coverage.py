#!/usr/bin/env python3
"""what do the random test programs actually reach?

runs the same random programs and stimulus as the cocotb test, in the model
only, and counts which instructions ran, how often they stalled and which rare
events happened. a test that never reaches a feature can't find a bug in it.

  python tools/fuzz_coverage.py [programs] [clocks] [seed] [nt] [pw] [ramb]
"""

import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metro.asm import disasm                                   # noqa: E402
from metro.emu import Config, Machine, loader_waveform         # noqa: E402
from metro.randprog import rand_inputs, rand_program           # noqa: E402


def main():
    a = [int(v) for v in sys.argv[1:]]
    programs, clocks, seed, nt, pw, ramb = (a + [40, 1500, 1, 2, 5, 8][len(a):])[:6]
    cfg = Config(nt=nt, pw=pw, ram_bytes=ramb)
    executed, stalled, events = Counter(), Counter(), Counter()
    thread_clocks = Counter()
    for p in range(programs):
        rng = random.Random(seed * 100003 + p)
        m = Machine(cfg)
        for _ in range(2 + rng.randrange(1, 4)):      # same reset length as the cocotb bench
            m.clock(0, 1, 0)
        for ui in loader_waveform(rand_program(rng, cfg), cfg, rng):
            m.clock(1, ui, 0)
        m.trace = []
        for ui, uio in rand_inputs(rng, clocks):
            before = (list(m.pc), list(m.ovr), list(m.fault), m.sched, list(m.c))
            n = len(m.trace)
            m.clock(1, ui, uio)
            if len(m.trace) == n:
                events["idle clock (no runnable thread in the slot)"] += 1
                continue
            _, t, pc, w = m.trace[-1]
            name = disasm(w).split()[0]
            thread_clocks[t] += 1
            if m.pc[t] == pc and name not in ("JMP", "JR", "DJNZ", "BZ", "BNZ", "BC", "BNC", "BT", "BNT", "JAL", "START"):
                stalled[name] += 1
            else:
                executed[name] += 1
            if m.ovr[t] and not before[1][t]:
                events["timer overrun flag set"] += 1
            if m.fault[t] and not before[2][t]:
                events["fault (reserved opcode)"] += 1
            if m.sched != before[3]:
                events["schedule changed"] += 1
            if name in ("WAIT0.T", "WAIT1.T") and m.pc[t] != pc and m.c[t] == 1:
                events["WAIT timed out"] += 1
        events["programs ending with every thread stopped"] += int(not any(m.run))
    total = sum(executed.values()) + sum(stalled.values())
    print(f"{programs} programs x {clocks} clocks, config nt={nt} pw={pw} ram={ramb}")
    print(f"instruction slots: {total}  per thread: {dict(sorted(thread_clocks.items()))}")
    print("\ncompleted / stalled, by mnemonic:")
    for name in sorted(set(executed) | set(stalled), key=lambda k: -(executed[k] + stalled[k])):
        print(f"  {name:9s} {executed[name]:8d} {stalled[name]:8d}")
    print("\nevents:")
    for k, v in sorted(events.items()):
        print(f"  {v:8d}  {k}")
    from metro.asm import ALU_FN, BRANCHES, IMM_OPS, PIN_OPS, SHP_OPS, TIME_OPS
    every = set(ALU_FN) | set(BRANCHES) | set(IMM_OPS) | set(PIN_OPS) | set(SHP_OPS) | set(TIME_OPS)
    every |= {m + ".T" for m in list(PIN_OPS) + list(SHP_OPS)}
    every |= {"NOP", "HALT", "JR", "SCHED", "START", "STOP", "DJNZ", "JAL", "IN", "OUT", "LDA", "STA", "LD", "ST", ".word"}
    missing = sorted(every - set(executed) - set(stalled))
    print("\nnever reached:", ", ".join(missing) if missing else "nothing; every mnemonic was executed")


if __name__ == "__main__":
    main()
