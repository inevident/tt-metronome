# SPDX-License-Identifier: Apache-2.0
"""cocotb tests: the verilog against the python model, clock by clock.

every test resets the chip, shifts a program in through the real loader pins
and runs it. after every clock the three output buses are compared with the
model. in rtl simulation the internal state is compared too.

environment:
  METRO_PROGRAMS  number of random programs (default 40)
  METRO_CLOCKS    clocks to run each random program (default 1500)
  METRO_SEED      base seed (default 1)
"""

import os
import random
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from metro.asm import assemble                      # noqa: E402
from metro.emu import Config, Machine, loader_waveform   # noqa: E402
from metro.randprog import rand_inputs, rand_program     # noqa: E402

CFG = Config(nt=int(os.environ.get("METRO_NT", 2)),
             pw=int(os.environ.get("METRO_PW", 5)),
             ram_bytes=int(os.environ.get("METRO_RAMB", 8)))
GATES = os.environ.get("GATES", "") in ("yes", "local")
PROGRAMS = int(os.environ.get("METRO_PROGRAMS", 40))
CLOCKS = int(os.environ.get("METRO_CLOCKS", 1500))
SEED = int(os.environ.get("METRO_SEED", 1))
HERE = os.path.dirname(os.path.abspath(__file__))


class Bench:
    def __init__(self, dut):
        self.dut = dut
        self.model = Machine(CFG)
        self.core = None if GATES else dut.user_project.core
        self.n = 0                      # clocks since the start of the test
        self.label = ""

    async def start(self):
        dut = self.dut
        cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
        dut.ena.value = 1
        dut.rst_n.value = 0
        dut.ui_in.value = 1
        dut.uio_in.value = 0
        # two clocks with nothing checked: flops are unknown until the first
        # reset edge and the synchronisers until the second
        for _ in range(2):
            await self.step(0, 1, 0, check=False)

    async def step(self, rst_n, ui, uio, check=True):
        """one clock. returns (uo_out, uio_out, uio_oe) read from the chip."""
        dut = self.dut
        await FallingEdge(dut.clk)
        dut.rst_n.value = rst_n
        dut.ui_in.value = ui
        dut.uio_in.value = uio
        await RisingEdge(dut.clk)
        want = self.model.clock(rst_n, ui, uio)
        await ReadOnly()
        self.n += 1
        if not check:
            return None
        got = (self.read(dut.uo_out), self.read(dut.uio_out), self.read(dut.uio_oe))
        if got != want:
            self.fail(f"pins: chip uo/uio_out/uio_oe = {fmt(got)}, model = {fmt(want)}")
        if self.core is not None:
            self.check_state()
        return got

    def read(self, sig):
        v = sig.value
        if not v.is_resolvable:
            self.fail(f"{sig._name} is undefined ({v})")
        return int(v)

    def fail(self, msg):
        m = self.model
        raise AssertionError(
            f"{self.label} clock {self.n} (run clock {m.clocks}): {msg}\n"
            f"  model pc={m.pc} run={m.run} sched={m.sched:#04x} phase={m.phase}")

    def check_state(self):
        c, m, nt = self.core, self.model, CFG.nt
        rd = self.read
        pairs = [
            ("running", rd(c.running), int(m.running)),
            ("loaded", rd(c.loaded), int(m.loaded)),
            ("sched", rd(c.sched), m.sched),
            ("phase", rd(c.phase), m.phase),
            ("run", rd(c.run), bits(m.run)),
            ("fault", rd(c.fault), bits(m.fault)),
            ("zf", rd(c.zf), bits(m.z)),
            ("cf", rd(c.cf), bits(m.c)),
            ("tick", rd(c.tick), bits(m.tick)),
            ("ovr", rd(c.ovr), bits(m.ovr)),
            ("uio_o", rd(c.uio_o), m.uio_o),
            ("uio_e", rd(c.uio_e), m.uio_e),
            ("uio_d", rd(c.uio_d), m.uio_d),
            ("uo", rd(c.uo), m.uo),
            ("flags", rd(c.flags), m.flags),
            ("pc", rd(c.dbg_pc), pack(m.pc, 8)),
            ("cnt", rd(c.dbg_cnt), pack(m.cnt, 16)),
            ("per", rd(c.dbg_per), pack(m.per, 16)),
            ("regs", rd(c.dbg_regs), pack([r for th in m.reg for r in th], 8)),
            ("ram", rd(c.dbg_ram), pack(m.ram, 8)),
        ]
        for name, got, want in pairs:
            if got != want:
                self.fail(f"{name}: chip {got:#x}, model {want:#x}")

    async def reset(self, clocks=3):
        for _ in range(clocks):
            await self.step(0, 1, 0)

    async def load(self, words, rng=None):
        for ui in loader_waveform(words, CFG, rng):
            await self.step(1, ui, 0)
        assert self.model.running


def bits(flags):
    return sum(int(bool(f)) << i for i, f in enumerate(flags))


def pack(values, width):
    return sum(v << (i * width) for i, v in enumerate(values))


def fmt(t):
    return "/".join(f"{v:02x}" for v in t)


def uart_decode(samples, bit):
    """decode 8N1 bytes from one sample per clock"""
    out, i = [], 1
    while i < len(samples) - 10 * bit:
        if samples[i - 1] == 1 and samples[i] == 0:
            byte = 0
            for b in range(8):
                byte |= samples[i + bit + bit // 2 + b * bit] << b
            out.append(byte)
            i += 9 * bit
        else:
            i += 1
    return bytes(out)


@cocotb.test()
async def test_uart_hello(dut):
    """uart transmit, edges exactly one bit period apart"""
    with open(os.path.join(HERE, "..", "programs", "uart_hello.s")) as f:
        src = f.read()
    b = Bench(dut)
    b.label = "uart_hello"
    await b.start()
    await b.reset()
    await b.load(assemble(src, CFG.words))
    tx = []
    for _ in range(600):
        uo, _, _ = await b.step(1, 1, 0)
        tx.append(uo & 1)
    assert uart_decode(tx, 16) == b"Hi", uart_decode(tx, 16)
    edges = [i for i in range(1, len(tx)) if tx[i] != tx[i - 1]]
    gaps = {b - a for a, b in zip(edges, edges[1:])}
    assert all(g % 16 == 0 for g in gaps), f"edge spacing not a multiple of the bit time: {gaps}"


@cocotb.test()
async def test_directed(dut):
    """hand-written programs for cases random programs rarely reach.
    where a program states its expected result, the model is checked too."""
    import glob
    import re
    import zlib
    b = Bench(dut)
    await b.start()
    files = sorted(glob.glob(os.path.join(HERE, "directed", "*.s")))
    assert files, "no directed programs found"
    for path in files:
        name = os.path.basename(path)
        with open(path) as f:
            src = f.read()
        rng = random.Random(zlib.crc32(name.encode()))
        b.label = f"directed {name}"
        await b.reset()
        await b.load(assemble(src, CFG.words))
        for ui, uio in rand_inputs(rng, 500):
            await b.step(1, ui, uio)
        want = re.search(r";\s*expect uo=(0x[0-9a-fA-F]+)", src)
        if want:
            assert b.model.uo == int(want.group(1), 16), \
                f"{name}: uo = {b.model.uo:#04x}, the program says it should be {want.group(1)}"


@cocotb.test()
async def test_random_lockstep(dut):
    """random programs with random pin activity, compared every clock"""
    b = Bench(dut)
    await b.start()
    for p in range(PROGRAMS):
        rng = random.Random(SEED * 100003 + p)
        b.label = f"random program {p} (seed {SEED})"
        await b.reset(rng.randrange(1, 4))
        await b.load(rand_program(rng, CFG), rng)
        for ui, uio in rand_inputs(rng, CLOCKS):
            await b.step(1, ui, uio)
    dut._log.info(f"{PROGRAMS} random programs x {CLOCKS} clocks matched the model")


@cocotb.test()
async def test_reset_while_running(dut):
    """reset in the middle of a program, then load and run another"""
    b = Bench(dut)
    await b.start()
    rng = random.Random(SEED + 7)
    for p in range(4):
        b.label = f"reset-while-running {p}"
        await b.load(rand_program(rng, CFG), rng)
        for ui, uio in rand_inputs(rng, rng.randrange(20, 300)):
            await b.step(1, ui, uio)
        await b.reset(1)
