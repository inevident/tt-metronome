"""assembler and disassembler for the metronome instruction set (rev a).

usage:  python -m metro.asm program.s [-o program.hex] [--list]

one instruction per line:

    ; comment
    .equ  BIT, 520            ; constant
    loop: OUTL.T uo0, r0      ; label, mnemonic, operands
          DJNZ  r1, loop

a ".T" suffix on a pin instruction means wait for this thread's timer tick,
then do it. on WAIT0/WAIT1 it means give up at the tick (carry set on timeout).
"""

import re
import sys

PIN_GROUPS = {"uio": 0, "uo": 8, "ui": 16, "f": 24}
PORTS = {"UIO": 0, "OE": 1, "OD": 2, "UO": 3, "UI": 4, "FLAGS": 5, "TSTAT": 6, "THR": 7}

ALU_FN = {"MOV": 0, "ADD": 1, "ADC": 2, "SUB": 3, "SBC": 4, "AND": 5, "OR": 6,
          "XOR": 7, "CMP": 8, "SHL": 9, "SHR": 10, "ROL": 11, "ROR": 12}
IMM_OPS = {"LDI": (1, 0), "ADDI": (1, 1), "ANDI": (2, 0), "ORI": (2, 1),
           "XORI": (3, 0), "CMPI": (3, 1)}
BRANCHES = {"JMP": 0, "BZ": 1, "BNZ": 2, "BC": 3, "BNC": 4, "BT": 5, "BNT": 6}
PIN_OPS = {"CLR": 0, "SET": 1, "TGL": 2, "PUTC": 3, "GETC": 4, "DRV": 5, "HIZ": 6,
           "WAIT0": 7, "WAIT1": 8}
SHP_OPS = {"OUTL": 0, "OUTM": 1, "INL": 2, "INM": 3}
TIME_OPS = {"WAITT": 0, "TPERL": 1, "TPERH": 2, "TRST": 3, "TPH": 4}


class AsmError(Exception):
    pass


def _reg(tok):
    m = re.fullmatch(r"[rR]([0-7])", tok.strip())
    if not m:
        raise AsmError(f"expected a register r0..r7, got '{tok}'")
    return int(m.group(1))


class Assembler:
    def __init__(self, words=32):
        self.max_words = words
        self.symbols = {}

    def _value(self, tok, final=True):
        tok = tok.strip().lstrip("#")
        m = re.fullmatch(r"'(.)'", tok)
        if m:
            return ord(m.group(1))
        try:
            return int(eval(tok, {"__builtins__": {}}, self.symbols))
        except NameError:
            if final:
                raise AsmError(f"unknown symbol in '{tok}'")
            return 0
        except Exception as e:
            raise AsmError(f"bad expression '{tok}': {e}")

    def _pin(self, tok, final):
        t = tok.strip()
        m = re.fullmatch(r"(uio|uo|ui|f)([0-7])", t, re.I)
        if m:
            return PIN_GROUPS[m.group(1).lower()] + int(m.group(2))
        v = self._value(t, final)
        if not 0 <= v <= 31:
            raise AsmError(f"pin number out of range: {tok}")
        return v

    def _port(self, tok, final):
        t = tok.strip()
        if t.upper() in PORTS:
            return PORTS[t.upper()]
        return self._value(t, final) & 0xFF

    def _imm8(self, tok, final):
        v = self._value(tok, final)
        if not -128 <= v <= 255:
            raise AsmError(f"value does not fit in 8 bits: {tok} = {v}")
        return v & 0xFF

    def _encode(self, mnem, ops, final):
        """16-bit words for one source instruction"""
        tick = 0
        if mnem.endswith(".T"):
            mnem, tick = mnem[:-2], 1
        n = len(ops)

        def need(k):
            if n != k:
                raise AsmError(f"{mnem} takes {k} operand(s), got {n}")

        if tick and mnem not in PIN_OPS and mnem not in SHP_OPS:
            raise AsmError(f"{mnem} cannot take the .T suffix")

        if mnem == "NOP":
            need(0); return [0x0000]
        if mnem == "HALT":
            need(0); return [0x0100]
        if mnem == "JR":
            need(1); return [0x0200 | _reg(ops[0])]
        if mnem == "SCHED":
            if n == 4:
                v = 0
                for i, o in enumerate(ops):
                    th = self._value(o, final)
                    if not 0 <= th <= 3:
                        raise AsmError("SCHED thread ids are 0..3")
                    v |= th << (2 * i)
            else:
                need(1); v = self._imm8(ops[0], final)
            return [0x0300 | v]
        if mnem in ("START", "STOP"):
            need(2 if mnem == "START" else 1)
            th = self._value(ops[0], final)
            if not 0 <= th <= 3:
                raise AsmError("thread id must be 0..3")
            if mnem == "START":
                return [0x0400 | (th << 8) | self._imm8(ops[1], final)]
            return [0x0800 | (th << 8)]
        if mnem in IMM_OPS:
            need(2); op, x = IMM_OPS[mnem]
            return [(op << 12) | (x << 11) | (_reg(ops[0]) << 8) | self._imm8(ops[1], final)]
        if mnem in ("INC", "DEC"):
            need(1)
            return [0x1800 | (_reg(ops[0]) << 8) | (1 if mnem == "INC" else 0xFF)]
        if mnem in ALU_FN:
            if n == 1 and mnem in ("SHL", "SHR", "ROL", "ROR"):
                ops = [ops[0], ops[0]]
            elif n != 2:
                raise AsmError(f"{mnem} takes 2 operands")
            return [0x4000 | (_reg(ops[0]) << 8) | (ALU_FN[mnem] << 4) | _reg(ops[1])]
        if mnem in BRANCHES:
            need(1)
            return [0x5000 | (BRANCHES[mnem] << 8) | self._imm8(ops[0], final)]
        if mnem in ("DJNZ", "JAL"):
            need(2); x = 0 if mnem == "DJNZ" else 1
            return [0x6000 | (x << 11) | (_reg(ops[0]) << 8) | self._imm8(ops[1], final)]
        if mnem in PIN_OPS:
            need(1)
            return [0x7000 | (tick << 11) | (PIN_OPS[mnem] << 5) | self._pin(ops[0], final)]
        if mnem in SHP_OPS:
            need(2)
            pin_tok, reg_tok = (ops[0], ops[1]) if mnem.startswith("OUT") else (ops[1], ops[0])
            return [0x8000 | (tick << 11) | (_reg(reg_tok) << 8) | (SHP_OPS[mnem] << 6)
                    | self._pin(pin_tok, final)]
        if mnem == "IN":
            need(2); return [0x9000 | (_reg(ops[0]) << 8) | self._port(ops[1], final)]
        if mnem == "OUT":
            need(2); return [0x9800 | (_reg(ops[1]) << 8) | self._port(ops[0], final)]
        if mnem in TIME_OPS:
            if mnem in ("TPERL", "TPERH"):
                need(1); v = self._imm8(ops[0], final)
            else:
                need(0); v = 0
            return [0xA000 | (TIME_OPS[mnem] << 8) | v]
        if mnem == "TPER":                      # pseudo: period in clocks
            need(1); v = self._value(ops[0], final)
            if final and not 1 <= v <= 65536:
                raise AsmError(f"TPER period must be 1..65536 clocks, got {v}")
            v = (v - 1) & 0xFFFF
            return [0xA100 | (v & 0xFF), 0xA200 | (v >> 8)]
        if mnem == "LDA":
            need(2); return [0xB000 | (_reg(ops[0]) << 8) | self._imm8(ops[1], final)]
        if mnem == "STA":
            need(2); return [0xB800 | (_reg(ops[1]) << 8) | self._imm8(ops[0], final)]
        if mnem in ("LD", "ST"):
            need(2)
            r_tok, m_tok = (ops[0], ops[1]) if mnem == "LD" else (ops[1], ops[0])
            m = re.fullmatch(r"\[\s*(\w+)\s*\]", m_tok.strip())
            if not m:
                raise AsmError(f"{mnem} needs an address like [r1]")
            x = 0 if mnem == "LD" else 1
            return [0xC000 | (x << 11) | (_reg(r_tok) << 8) | _reg(m.group(1))]
        if mnem == ".WORD":
            return [self._value(o, final) & 0xFFFF for o in ops]
        raise AsmError(f"unknown instruction '{mnem}'")

    def assemble(self, text):
        """returns (words, listing). raises AsmError with a line number."""
        lines = []
        for no, raw in enumerate(text.splitlines(), 1):
            src = raw.split(";", 1)[0].strip()
            if src:
                lines.append((no, src, raw.rstrip()))

        def run(final):
            out, listing, addr = [], [], 0
            for no, src, raw in lines:
                try:
                    while True:
                        m = re.match(r"^([A-Za-z_]\w*):\s*", src)
                        if not m:
                            break
                        if not final:
                            if m.group(1) in self.symbols:
                                raise AsmError(f"'{m.group(1)}' defined twice")
                            self.symbols[m.group(1)] = addr
                        src = src[m.end():]
                    if not src:
                        continue
                    parts = src.split(None, 1)
                    mnem = parts[0].upper()
                    ops = [o.strip() for o in parts[1].split(",")] if len(parts) > 1 else []
                    if mnem == ".EQU":
                        if not final:
                            self.symbols[ops[0]] = self._value(ops[1], True)
                        continue
                    words = self._encode(mnem, ops, final)
                    for i, w in enumerate(words):
                        listing.append((addr + i, w, raw if i == 0 else ""))
                    out += words
                    addr += len(words)
                except AsmError as e:
                    raise AsmError(f"line {no}: {e}") from None
            if final and len(out) > self.max_words:
                raise AsmError(f"program is {len(out)} words; memory holds {self.max_words}")
            return out, listing

        self.symbols = {}
        run(False)
        return run(True)


def assemble(text, words=32):
    return Assembler(words).assemble(text)[0]


# disassembler

def _pin_name(p):
    for name, base in (("f", 24), ("ui", 16), ("uo", 8), ("uio", 0)):
        if p >= base:
            return f"{name}{p - base}"


def disasm(w):
    inv = lambda d: {v: k for k, v in d.items()}
    op, x, rd, rs, imm = w >> 12, (w >> 11) & 1, (w >> 8) & 7, w & 7, w & 0xFF
    if op == 0:
        sub, xx = (w >> 10) & 3, (w >> 8) & 3
        if sub == 0:
            return ["NOP", "HALT", f"JR r{rs}",
                    "SCHED " + ",".join(str((imm >> (2 * i)) & 3) for i in range(4))][xx]
        if sub == 1:
            return f"START {xx}, {imm}"
        if sub == 2:
            return f"STOP {xx}"
        return "NOP"
    for name, (o, xx) in IMM_OPS.items():
        if (o, xx) == (op, x):
            return f"{name} r{rd}, #{imm}"
    if op == 4:
        name = inv(ALU_FN).get((w >> 4) & 15)
        return f"{name} r{rd}, r{rs}" if name else "NOP"
    if op == 5:
        name = inv(BRANCHES).get((w >> 8) & 15)
        return f"{name} {imm}" if name else "NOP"
    if op == 6:
        return f"{'JAL' if x else 'DJNZ'} r{rd}, {imm}"
    if op == 7:
        name = inv(PIN_OPS).get((w >> 5) & 15)
        return f"{name}{'.T' if x else ''} {_pin_name(w & 31)}" if name else "NOP"
    if op == 8:
        name = inv(SHP_OPS)[(w >> 6) & 3] + (".T" if x else "")
        pin = _pin_name(w & 31)
        return f"{name} {pin}, r{rd}" if name.startswith("OUT") else f"{name} r{rd}, {pin}"
    if op == 9:
        port = inv(PORTS).get(imm, str(imm))
        return f"OUT {port}, r{rd}" if x else f"IN r{rd}, {port}"
    if op == 10:
        name = inv(TIME_OPS).get((w >> 8) & 15)
        if not name:
            return "NOP"
        return f"{name} #{imm}" if name in ("TPERL", "TPERH") else name
    if op == 11:
        return f"STA {imm}, r{rd}" if x else f"LDA r{rd}, {imm}"
    if op == 12:
        return f"ST [r{rs}], r{rd}" if x else f"LD r{rd}, [r{rs}]"
    return f".word 0x{w:04X}   ; reserved: faults"


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Metronome assembler")
    ap.add_argument("source")
    ap.add_argument("-o", "--output")
    ap.add_argument("--words", type=int, default=32, help="program memory size")
    ap.add_argument("--list", action="store_true", help="print a listing")
    a = ap.parse_args(argv)
    try:
        words, listing = Assembler(a.words).assemble(open(a.source).read())
    except AsmError as e:
        sys.exit(f"{a.source}: {e}")
    if a.list:
        for addr, w, raw in listing:
            print(f"{addr:02X}  {w:04X}  {raw}")
        print(f"; {len(words)} of {a.words} words used")
    if a.output:
        with open(a.output, "w") as f:
            f.write("".join(f"{w:04X}\n" for w in words))


if __name__ == "__main__":
    main(sys.argv[1:])
