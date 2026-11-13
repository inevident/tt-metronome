"""random programs and random pin stimulus for testing.

programs lean towards legal, interesting instructions (short timer periods,
both threads started, pins toggled) but also include reserved encodings and
fully random words, since every 16-bit word has defined behaviour.
"""

import random


EDGE_VALUES = [0, 1, 2, 3, 0x7F, 0x80, 0xFE, 0xFF]


def _timer_preamble(rng):
    return [0xA100 | rng.randrange(0, 24),      # tperl small
            0xA200,                              # tperh 0
            0xA300]                              # trst


def rand_sched(rng, nt):
    if rng.random() < 0.8:
        return sum(rng.randrange(nt) << (2 * i) for i in range(4))
    return rng.randrange(256)


def rand_word(rng, words):
    reg = lambda: rng.randrange(8)
    # half the immediates come from a few edge values, so equal operands and
    # carries out of bit 7 happen often instead of once in 256 tries
    imm = lambda: rng.choice(EDGE_VALUES) if rng.random() < 0.5 else rng.randrange(256)
    tgt = lambda: rng.randrange(words)
    tbit = lambda: (1 << 11) if rng.random() < 0.35 else 0
    kind = rng.choices(
        ["imm", "alu", "br", "djnz", "jal", "jr", "pin", "shp", "port", "time",
         "mem", "sys", "fault", "raw"],
        [18, 14, 8, 4, 2, 2, 14, 8, 8, 8, 6, 4, 0.3, 2])[0]
    if kind == "imm":
        return (rng.randrange(1, 4) << 12) | (rng.randrange(2) << 11) | (reg() << 8) | imm()
    if kind == "alu":
        return 0x4000 | (reg() << 8) | (rng.randrange(16) << 4) | reg()
    if kind == "br":
        return 0x5000 | (rng.choice([0, 1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6, 7]) << 8) | tgt()
    if kind == "djnz":
        return 0x6000 | (reg() << 8) | tgt()
    if kind == "jal":
        return 0x6800 | (reg() << 8) | tgt()
    if kind == "jr":
        return 0x0200 | reg()
    if kind == "pin":
        return 0x7000 | tbit() | (rng.randrange(10) << 5) | rng.randrange(32)
    if kind == "shp":
        return 0x8000 | tbit() | (reg() << 8) | (rng.randrange(4) << 6) | rng.randrange(32)
    if kind == "port":
        return 0x9000 | (rng.randrange(2) << 11) | (reg() << 8) | rng.randrange(9)
    if kind == "time":
        sub = rng.choices([0, 1, 2, 3, 4, 9], [3, 2, 0.5, 1, 1, 0.2])[0]
        v = rng.randrange(0, 24) if sub == 1 else (1 if sub == 2 and rng.random() < 0.1 else 0)
        return 0xA000 | (sub << 8) | v
    if kind == "mem":
        return (rng.choice([0xB, 0xC]) << 12) | (rng.randrange(2) << 11) | (reg() << 8) | imm()
    if kind == "sys":
        s = rng.choices(["nop", "halt", "sched", "start", "stop", "res"],
                        [1, 0.3, 1, 1.2, 0.5, 0.2])[0]
        if s == "nop":
            return 0x0000
        if s == "halt":
            return 0x0100
        if s == "sched":
            return 0x0300 | rng.randrange(256)
        if s == "start":
            return 0x0400 | (rng.randrange(4) << 8) | tgt()
        if s == "stop":
            return 0x0800 | (rng.randrange(4) << 8)
        return 0x0C00 | rng.randrange(1024)
    if kind == "fault":
        return (rng.choice([0xD, 0xE, 0xF]) << 12) | rng.randrange(4096)
    return rng.randrange(65536)


def rand_program(rng, cfg):
    """a full memory image for cfg"""
    words = cfg.words
    image = [rand_word(rng, words) for _ in range(words)]
    if rng.random() < 0.15:
        return image                              # no helpful preamble at all
    span = words // cfg.nt
    for th in range(cfg.nt):
        base = th * span
        pre = _timer_preamble(rng)
        if th == 0:
            pre += [0x0400 | (o << 8) | (o * span) for o in range(1, cfg.nt)]   # start others
            pre += [0x0300 | rand_sched(rng, cfg.nt)]                           # sched
        image[base:base + len(pre)] = pre
    return image


def rand_inputs(rng, n, change=0.3):
    """n (ui_in, uio_in) pairs that change only now and then"""
    out, ui, uio = [], rng.randrange(256), rng.randrange(256)
    for _ in range(n):
        if rng.random() < change:
            ui = rng.randrange(256)
        if rng.random() < change:
            uio = rng.randrange(256)
        out.append((ui, uio))
    return out
