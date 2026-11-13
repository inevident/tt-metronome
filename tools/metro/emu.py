"""cycle-exact model of the metronome chip (rev a). this is the spec.

one call to clock() is one rising clock edge. it models the whole chip at the
pins: reset, the input synchronisers, the program loader, the thread schedule,
every instruction and the timers. the verilog in src/ is tested against it
clock by clock. docs/ISA.md says the same thing in words.
"""

from dataclasses import dataclass

# configuration

@dataclass(frozen=True)
class Config:
    nt: int = 2          # hardware threads (1, 2 or 4)
    pw: int = 5          # program address bits (2**pw words)
    ram_bytes: int = 8   # data ram bytes (power of two; 0 = none)

    @property
    def words(self):
        return 1 << self.pw


SKY_REV_A = Config(nt=2, pw=5, ram_bytes=8)
PROTOCOL = Config(nt=4, pw=8, ram_bytes=64)

# loader pins on ui_in while the chip is waiting for a program
LOAD_CS_N, LOAD_SCK, LOAD_MOSI = 0, 1, 2

# port numbers for in / out
PORT_UIO, PORT_OE, PORT_OD, PORT_UO, PORT_UI, PORT_FLAGS, PORT_TSTAT, PORT_THR = range(8)


class Machine:
    def __init__(self, cfg: Config = SKY_REV_A):
        self.cfg = cfg
        self.prog = [None] * cfg.words      # None until the loader writes it
        # input synchronisers have no reset. they hold whatever was sampled.
        self.s1_ui = self.s2_ui = 0
        self.s1_uio = self.s2_uio = 0
        self.shreg = 0                      # loader shift register (no reset)
        self.clocks = 0                     # clocks executed while running
        self.trace = None                   # optional list of (clock, thread, pc, word)
        self._reset()

    # reset

    def _reset(self):
        n = self.cfg.nt
        self.running = False
        self.loaded = False                 # at least one word written since reset
        self.cs_d, self.sck_d = 1, 0
        self.bitcnt = 0
        self.laddr = 0
        self.pc = [0] * n
        self.run = [i == 0 for i in range(n)]
        self.fault = [False] * n
        self.reg = [[0] * 8 for _ in range(n)]
        self.z = [0] * n
        self.c = [0] * n
        self.cnt = [0xFFFF] * n
        self.per = [0xFFFF] * n
        self.tick = [0] * n
        self.ovr = [0] * n
        self.uio_o = self.uio_e = self.uio_d = 0
        self.uo = 0
        self.flags = 0
        self.ram = [0] * self.cfg.ram_bytes
        self.sched = 0
        self.phase = 0
        self.clocks = 0

    # pins

    def outputs(self):
        """(uo_out, uio_out, uio_oe) after the last clock edge"""
        uio_out = self.uio_o & ~self.uio_d & 0xFF
        uio_oe = ((self.uio_e & ~self.uio_d) | (self.uio_d & ~self.uio_o)) & 0xFF
        return self.uo, uio_out, uio_oe

    def _pin_read(self, pin):
        grp, bit = pin >> 3, pin & 7
        src = (self.s2_uio, self.uo, self.s2_ui, self.flags)[grp]
        return (src >> bit) & 1

    def _latch_read(self, pin):
        grp, bit = pin >> 3, pin & 7
        src = (self.uio_o, self.uo, 0, self.flags)[grp]
        return (src >> bit) & 1

    def _latch_write(self, pin, val):
        grp, bit = pin >> 3, pin & 7
        m = 1 << bit
        if grp == 0:
            self.uio_o = (self.uio_o & ~m) | (m if val else 0)
        elif grp == 1:
            self.uo = (self.uo & ~m) | (m if val else 0)
        elif grp == 3:
            self.flags = (self.flags & ~m) | (m if val else 0)
        # grp 2 (ui pins) is input only: write ignored

    def _oe_write(self, pin, val):
        if pin >> 3 == 0:
            m = 1 << (pin & 7)
            self.uio_e = (self.uio_e & ~m) | (m if val else 0)

    # one clock edge

    def clock(self, rst_n=1, ui_in=0, uio_in=0):
        """one rising clock edge. inputs are the pad values that were stable
        before the edge. returns outputs() after it."""
        if not rst_n:
            self._reset()
        elif not self.running:
            self._loader()
        else:
            self._execute()
            self.clocks += 1
        # synchronisers always run, in reset or not
        self.s2_ui, self.s1_ui = self.s1_ui, ui_in & 0xFF
        self.s2_uio, self.s1_uio = self.s1_uio, uio_in & 0xFF
        return self.outputs()

    # loader

    def _loader(self):
        cs = (self.s2_ui >> LOAD_CS_N) & 1
        sck = (self.s2_ui >> LOAD_SCK) & 1
        mosi = (self.s2_ui >> LOAD_MOSI) & 1
        if not cs and sck and not self.sck_d:
            word = ((self.shreg << 1) | mosi) & 0xFFFF
            if self.bitcnt == 15:
                self.prog[self.laddr] = word
                self.loaded = True
                self.laddr = (self.laddr + 1) & (self.cfg.words - 1)
            self.shreg = word
            self.bitcnt = (self.bitcnt + 1) & 15
        if cs and not self.cs_d and self.loaded:
            self.running = True
        self.cs_d, self.sck_d = cs, sck

    # execute

    def _execute(self):
        cfg = self.cfg
        nt = cfg.nt
        pcmask = cfg.words - 1
        t = (self.sched >> (2 * self.phase)) & 3
        old_tick = list(self.tick)
        old_cnt = list(self.cnt)
        old_per = list(self.per)

        consume = False      # this thread used up its tick
        restart = None       # None, 'full' (trst) or 'half' (tph)
        ovr_clear = False

        if t < nt and self.run[t]:
            pc = self.pc[t]
            w = self.prog[pc]
            if w is None:
                raise RuntimeError(f"thread {t} executed unloaded word at {pc}")
            if self.trace is not None:
                self.trace.append((self.clocks, t, pc, w))
            reg = self.reg[t]
            op = w >> 12
            x = (w >> 11) & 1
            rd = (w >> 8) & 7
            rs = w & 7
            imm = w & 0xFF
            npc = (pc + 1) & pcmask
            stall = False
            tick_now = old_tick[t]

            if op == 0x0:                                   # sys
                sub, xx = (w >> 10) & 3, (w >> 8) & 3
                if sub == 0:
                    if xx == 1:                             # halt
                        self.run[t] = False
                    elif xx == 2:                           # jr rs
                        npc = reg[rs] & pcmask
                    elif xx == 3:                           # sched #imm
                        self.sched = imm
                elif sub == 1:                              # start th, target
                    if xx < nt:
                        self.run[xx] = True
                        self.fault[xx] = False
                        if xx == t:
                            npc = imm & pcmask
                        else:
                            self.pc[xx] = imm & pcmask
                elif sub == 2:                              # stop th
                    if xx < nt:
                        self.run[xx] = False
            elif op == 0x1:
                if x == 0:                                  # ldi
                    reg[rd] = imm
                else:                                       # addi
                    s = reg[rd] + imm
                    reg[rd] = s & 0xFF
                    self.c[t] = s >> 8
                    self.z[t] = int(reg[rd] == 0)
            elif op == 0x2:                                 # andi / ori
                reg[rd] = (reg[rd] & imm) if x == 0 else (reg[rd] | imm)
                self.z[t] = int(reg[rd] == 0)
            elif op == 0x3:
                if x == 0:                                  # xori
                    reg[rd] ^= imm
                    self.z[t] = int(reg[rd] == 0)
                else:                                       # cmpi
                    self.z[t] = int(reg[rd] == imm)
                    self.c[t] = int(reg[rd] < imm)
            elif op == 0x4:                                 # alu rd, rs
                self._alu(t, (w >> 4) & 15, rd, rs)
            elif op == 0x5:                                 # branches
                cond = (w >> 8) & 15
                take = (cond == 0
                        or (cond == 1 and self.z[t]) or (cond == 2 and not self.z[t])
                        or (cond == 3 and self.c[t]) or (cond == 4 and not self.c[t])
                        or (cond == 5 and tick_now) or (cond == 6 and not tick_now))
                if take:
                    npc = imm & pcmask
            elif op == 0x6:
                if x == 0:                                  # djnz
                    reg[rd] = (reg[rd] - 1) & 0xFF
                    if reg[rd] != 0:
                        npc = imm & pcmask
                else:                                       # jal
                    reg[rd] = npc
                    npc = imm & pcmask
            elif op == 0x7:                                 # pin
                sub, pin = (w >> 5) & 15, w & 31
                val = self._pin_read(pin)
                if sub <= 6:
                    if x and not tick_now:
                        stall = True
                    else:
                        consume = bool(x)
                        if sub == 0:
                            self._latch_write(pin, 0)
                        elif sub == 1:
                            self._latch_write(pin, 1)
                        elif sub == 2:
                            self._latch_write(pin, 1 - self._latch_read(pin))
                        elif sub == 3:
                            self._latch_write(pin, self.c[t])
                        elif sub == 4:
                            self.c[t] = val
                        elif sub == 5:
                            self._oe_write(pin, 1)
                        elif sub == 6:
                            self._oe_write(pin, 0)
                elif sub <= 8:                              # wait0 / wait1
                    level = sub - 7
                    if val == level:
                        if x:
                            self.c[t] = 0
                    elif x and tick_now:                    # timed out
                        self.c[t] = 1
                        consume = True
                    else:
                        stall = True
            elif op == 0x8:                                 # shp: shift through a pin
                mode, pin = (w >> 6) & 3, w & 31
                if x and not tick_now:
                    stall = True
                else:
                    consume = bool(x)
                    v = reg[rd]
                    if mode == 0:                           # outl
                        self._latch_write(pin, v & 1)
                        reg[rd] = v >> 1
                    elif mode == 1:                         # outm
                        self._latch_write(pin, v >> 7)
                        reg[rd] = (v << 1) & 0xFF
                    elif mode == 2:                         # inl
                        reg[rd] = (self._pin_read(pin) << 7) | (v >> 1)
                    else:                                   # inm
                        reg[rd] = ((v << 1) & 0xFF) | self._pin_read(pin)
            elif op == 0x9:                                 # port
                if x == 0:
                    reg[rd] = self._port_read(t, imm, old_tick)
                else:
                    v = reg[rd]
                    if imm == PORT_UIO:
                        self.uio_o = v
                    elif imm == PORT_OE:
                        self.uio_e = v
                    elif imm == PORT_OD:
                        self.uio_d = v
                    elif imm == PORT_UO:
                        self.uo = v
                    elif imm == PORT_FLAGS:
                        self.flags = v
                    elif imm == PORT_TSTAT:
                        consume = bool(v & 1)
                        ovr_clear = bool(v & 2)
            elif op == 0xA:                                 # time
                sub = (w >> 8) & 15
                if sub == 0:                                # waitt
                    if tick_now:
                        consume = True
                    else:
                        stall = True
                elif sub == 1:
                    self.per[t] = (old_per[t] & 0xFF00) | imm
                elif sub == 2:
                    self.per[t] = (old_per[t] & 0x00FF) | (imm << 8)
                elif sub == 3:
                    restart = 'full'
                elif sub == 4:
                    restart = 'half'
            elif op == 0xB:                                 # lda / sta
                self._mem(reg, rd, imm, x)
            elif op == 0xC:                                 # ld / st
                self._mem(reg, rd, reg[rs], x)
            else:                                           # 0xd..0xf reserved
                self.run[t] = False
                self.fault[t] = True

            if not stall:
                self.pc[t] = npc
        else:
            t = -1                                          # idle slot

        # timers run every clock for every thread
        for i in range(nt):
            arrive = old_cnt[i] == 0
            mine = i == t
            if mine and restart:
                self.cnt[i] = old_per[i] if restart == 'full' else old_per[i] >> 1
                self.tick[i] = 0
            else:
                self.cnt[i] = old_per[i] if arrive else old_cnt[i] - 1
                used = mine and consume
                if arrive:
                    self.tick[i] = 1
                elif used:
                    self.tick[i] = 0
                if arrive and old_tick[i] and not used:
                    self.ovr[i] = 1
                elif mine and ovr_clear:
                    self.ovr[i] = 0

        self.phase = (self.phase + 1) & 3

    def _alu(self, t, fn, rd, rs):
        reg = self.reg[t]
        a, b, c = reg[rd], reg[rs], self.c[t]
        r = None
        if fn == 0:                                         # mov (no flags)
            reg[rd] = b
            return
        if fn in (1, 2):                                    # add / adc
            s = a + b + (c if fn == 2 else 0)
            r, self.c[t] = s & 0xFF, s >> 8
        elif fn in (3, 4, 8):                               # sub / sbc / cmp
            s = a - b - (c if fn == 4 else 0)
            r, self.c[t] = s & 0xFF, int(s < 0)
        elif fn == 5:
            r = a & b
        elif fn == 6:
            r = a | b
        elif fn == 7:
            r = a ^ b
        elif fn == 9:                                       # shl
            r, self.c[t] = (b << 1) & 0xFF, b >> 7
        elif fn == 10:                                      # shr
            r, self.c[t] = b >> 1, b & 1
        elif fn == 11:                                      # rol through carry
            r, self.c[t] = ((b << 1) & 0xFF) | c, b >> 7
        elif fn == 12:                                      # ror through carry
            r, self.c[t] = (c << 7) | (b >> 1), b & 1
        else:
            return                                          # reserved: no effect
        self.z[t] = int(r == 0)
        if fn != 8:
            reg[rd] = r

    def _mem(self, reg, rd, addr, store):
        n = self.cfg.ram_bytes
        if n == 0:
            if not store:
                reg[rd] = 0
            return
        addr &= n - 1
        if store:
            self.ram[addr] = reg[rd]
        else:
            reg[rd] = self.ram[addr]

    def _port_read(self, t, port, old_tick):
        if port == PORT_UIO:
            return self.s2_uio
        if port == PORT_OE:
            return self.uio_e
        if port == PORT_OD:
            return self.uio_d
        if port == PORT_UO:
            return self.uo
        if port == PORT_UI:
            return self.s2_ui
        if port == PORT_FLAGS:
            return self.flags
        if port == PORT_TSTAT:
            return (self.ovr[t] << 1) | old_tick[t]
        if port == PORT_THR:
            v = 0
            for i in range(self.cfg.nt):
                v |= (int(self.run[i]) << i) | (int(self.fault[i]) << (4 + i))
            return v
        return 0

    # conveniences (not part of the hardware)

    def load_direct(self, words):
        """put a program in memory and start, skipping the pin loader"""
        self._reset()
        image = list(words) + [0xFFFF] * (self.cfg.words - len(words))
        if len(image) > self.cfg.words:
            raise ValueError("program does not fit")
        self.prog = image
        self.loaded = True
        self.running = True


def loader_waveform(words, cfg=SKY_REV_A, rng=None):
    """ui_in values, one per clock, that shift a full image in through the
    loader pins and start the chip. unused words become 0xFFFF, which faults.
    with rng, each bit's low and high time varies from 1 to 3 clocks."""
    image = list(words) + [0xFFFF] * (cfg.words - len(words))
    if len(image) > cfg.words:
        raise ValueError("program does not fit")
    n = (lambda: rng.randrange(1, 4)) if rng else (lambda: 2)
    cs, sck = 1 << LOAD_CS_N, 1 << LOAD_SCK
    seq = [cs] * 4 + [0] * 2
    for w in image:
        for b in range(15, -1, -1):
            d = ((w >> b) & 1) << LOAD_MOSI
            seq += [d] * n() + [d | sck] * n()
    # cs_n high must pass through the two synchroniser flops before it is seen
    return seq + [0] * 2 + [cs] * 3
