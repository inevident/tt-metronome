![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# Metronome

A small 8-bit processor for bit-banging protocols with exact timing, made for [Tiny Tapeout](https://tinytapeout.com).

- One instruction per clock, always. No interrupts.
- Two hardware threads on a fixed schedule that the program sets.
- A timer per thread, and pin instructions that can wait for its tick.
- 32 words of program on the chip, loaded over three pins that go back to the program afterwards.

[docs/info.md](docs/info.md) describes the chip and how to load it. [docs/ISA.md](docs/ISA.md) is the instruction set.

## Layout

| Path | What |
|---|---|
| `src/` | the Verilog |
| `tools/metro/emu.py` | a model of the chip, exact to the clock. This is the spec |
| `tools/metro/asm.py` | assembler and disassembler |
| `test/` | cocotb tests that compare the Verilog with the model on every clock |
| `programs/` | example programs |

## Running it

    python3 -m venv .venv && . .venv/bin/activate
    pip install -r test/requirements.txt

You also need Icarus Verilog, and Yosys for the gate-level test.

    PYTHONPATH=tools python -m metro.asm programs/uart_hello.s --list
    python test/run.py                # rtl against the model
    python test/run.py --gates        # same, on a yosys netlist
    python tools/fuzz_coverage.py     # what the random programs reach
    python tools/mutation_test.py     # break the verilog, check the tests fail

`cd test && make` works too, as long as the path has no spaces in it.
