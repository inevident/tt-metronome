## How it works

Metronome is a small 8-bit processor for bit-banging serial protocols. It is built so that the time a pin changes is set by a timer and not by how long the code took.

It runs one instruction per clock, and every instruction takes exactly one clock, including taken branches. There are no interrupts. Two hardware threads share the clock through a 4-entry schedule: the program picks which thread owns each clock, so one thread can have every clock or the two can alternate. A thread's timing depends only on its own code and the schedule.

Each thread has 8 registers, zero and carry flags, and a 16-bit timer that reloads by itself and sets a tick flag. A pin instruction can wait for the tick before it acts. In a loop that puts one bit on a pin per tick, the edges land exactly one period apart whatever else the loop does. If the code misses a tick, an overrun flag records it. Waits on a pin can time out at the tick.

All 24 pins belong to the program: 8 inputs, 8 outputs and 8 bidirectional pins with an open-drain mode. Instructions move one bit between a register and any pin and shift the register in the same clock, so a UART or SPI bit loop is two instructions.

The program is 32 instructions of 16 bits, held on the chip. There are 8 bytes of RAM shared by the threads. The full instruction set is in `docs/ISA.md`.

## How to test

After reset the chip waits for a program and drives nothing on the bidirectional pins.

1. Hold `rst_n` low for at least 3 clocks, with `ui[0]` high.
2. Pull `ui[0]` (cs_n) low.
3. Shift in all 32 words, 16 bits each, most significant bit first: put the bit on `ui[2]` (mosi), then pulse `ui[1]` (sck). The chip samples these pins with its own clock, so keep sck low for at least one clock and high for at least one clock. Fill unused words with 0xFFFF.
4. Raise `ui[0]`. The program starts, and `ui[0..2]` become ordinary inputs.

To try it, assemble `programs/uart_hello.s` with `tools/metro/asm.py` and load it. It sends "Hi" as 8N1 serial on `uo[0]`, one bit every 16 clocks.

`tools/metro/emu.py` is a model of the chip that is exact to the clock at the pins. `test/` compares the Verilog against it.

## External hardware

None is needed. A logic analyser or a USB serial adapter on `uo[0]` shows the example program's output.
