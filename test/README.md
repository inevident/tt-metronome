# Tests

The tests load a program through the chip's loader pins, run it, and compare the Verilog with `tools/metro/emu.py` after every clock.

- `test_uart_hello` runs `programs/uart_hello.s` and decodes the serial output.
- `test_directed` runs the programs in `directed/`. These cover cases random programs rarely reach.
- `test_random_lockstep` runs random programs with random pin activity.
- `test_reset_while_running` resets in the middle of a program and loads another.

Run them with `python test/run.py` from the repo root, or `make` here. `make GATES=yes` is the gate-level run used by the GDS workflow.
