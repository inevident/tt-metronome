# Metronome instruction set, rev A

This is the specification of the chip submitted to Tiny Tapeout (rev A). The executable version of this document is `tools/metro/emu.py`. Where the two disagree, the emulator is right and this file has a bug.

## The timing rule

One instruction executes per clock. Every instruction takes exactly one clock of its thread's time, including taken branches. There are no interrupts and no pipeline bubbles.

The only instructions that can take longer are the ones that wait: `WAITT`, `WAIT0`, `WAIT1`, and any pin instruction with the `.T` suffix. A waiting instruction repeats in each of its thread's clocks until its condition holds, then completes in one clock like any other.

So the time a piece of code takes is the number of instructions on its path, and the time a pin edge happens is set by a timer, not by how long the code before it took.

## Threads and the schedule

The chip has NT hardware threads (2 on rev A). Each thread has its own program counter, 8 registers, Z and C flags, and timer. Threads share the program memory, the pins, 8 flag bits and the data RAM.

A 4-entry schedule decides which thread owns each clock. Clock 0 of every group of four belongs to the thread named in entry 0, and so on. `SCHED 0,0,0,0` gives thread 0 every clock. `SCHED 0,1,0,1` gives each of two threads every second clock. An entry that names a thread that does not exist, or one that is stopped, is an idle clock.

A thread's timing depends only on its own code and the schedule. Starting, stopping or changing another thread's code never moves its edges. After reset the schedule is `0,0,0,0` and only thread 0 runs.

## Timers

Each thread has a 16-bit down-counter and a period register. The counter decrements every clock. When it reaches 0 it reloads from the period register and sets the thread's tick flag. A period register value of N-1 gives a tick every N clocks. The assembler's `TPER N` pseudo-instruction does the subtraction.

The reload happens by itself, so tick spacing is exact and does not drift, whatever the code does between ticks.

If a tick arrives while the previous one is still unused, the overrun flag is set and stays set. This is how the chip reports that firmware missed a deadline.

Reset sets counter and period to 0xFFFF.

## Tick-synchronised instructions

A pin instruction with `.T` waits for the tick, uses it up, and then acts. `OUTL.T uo0, r0` in a loop puts one bit on the pin per tick, with edges exactly one period apart.

On `WAIT0` and `WAIT1` the suffix means timeout instead: the wait ends when the pin reaches the level (C = 0) or at the tick (C = 1, tick used up), whichever comes first.

For edges with no jitter at all, the period in clocks should be a multiple of the thread's spacing in the schedule (1, 2 or 4).

## Pins

| Pin numbers | Names | What they are |
|---|---|---|
| 0 to 7 | `uio0` to `uio7` | Bidirectional pins. Each has an output latch, an output enable and an open-drain bit |
| 8 to 15 | `uo0` to `uo7` | Output pins |
| 16 to 23 | `ui0` to `ui7` | Input pins |
| 24 to 31 | `f0` to `f7` | Flags: 8 internal bits that behave like pins, for signalling between threads |

Reading a `uio` or `ui` pin returns the pad value after a two-flop synchroniser, so an instruction sees the pad as it was two clocks earlier. Reading a `uo` pin or a flag returns its latch.

With the open-drain bit set, a `uio` pin drives low when its latch is 0 and is released when its latch is 1.

After reset every `uio` pin is an input and every `uo` pin is 0.

## Instruction format

Instructions are 16 bits. The top 4 bits are the opcode. `rd` is always bits 10:8, `rs` is bits 2:0, and an 8-bit immediate or branch target is bits 7:0. Bit 11 is `x`, which selects between two instructions that share an opcode, or is the `.T` bit.

| Op | x | Mnemonic | Effect | Flags |
|---|---|---|---|---|
| 0 | | `NOP` | Nothing | |
| 0 | | `HALT` | Stop this thread | |
| 0 | | `JR rs` | PC = rs | |
| 0 | | `SCHED a,b,c,d` | Set the schedule | |
| 0 | | `START th, target` | Thread th: PC = target, run, clear fault | |
| 0 | | `STOP th` | Stop thread th | |
| 1 | 0 | `LDI rd, #k` | rd = k | |
| 1 | 1 | `ADDI rd, #k` | rd = rd + k | Z, C |
| 2 | 0 | `ANDI rd, #k` | rd = rd AND k | Z |
| 2 | 1 | `ORI rd, #k` | rd = rd OR k | Z |
| 3 | 0 | `XORI rd, #k` | rd = rd XOR k | Z |
| 3 | 1 | `CMPI rd, #k` | Compare rd with k | Z, C = (rd < k) |
| 4 | | `MOV rd, rs` | rd = rs | |
| 4 | | `ADD` `ADC` `SUB` `SBC` | Arithmetic. For SUB, SBC and CMP, C = borrow | Z, C |
| 4 | | `AND` `OR` `XOR` | Logic | Z |
| 4 | | `CMP rd, rs` | Compare | Z, C = (rd < rs) |
| 4 | | `SHL` `SHR` `ROL` `ROR` | rd = rs shifted one place. ROL and ROR go through C | Z, C |
| 5 | | `JMP` `BZ` `BNZ` `BC` `BNC` `BT` `BNT` | Branch. BT and BNT test the tick flag without using it up | |
| 6 | 0 | `DJNZ rd, target` | rd = rd - 1, branch if not zero | |
| 6 | 1 | `JAL rd, target` | rd = PC + 1, PC = target | |
| 7 | T | `CLR` `SET` `TGL` `PUTC pin` | Write the pin's latch (0, 1, toggle, C) | |
| 7 | T | `GETC pin` | C = pin | C |
| 7 | T | `DRV` `HIZ pin` | Turn a `uio` pin's output enable on or off | |
| 7 | T | `WAIT0` `WAIT1 pin` | Wait until the pin is 0 or 1. With `.T`: or until the tick | C with `.T` |
| 8 | T | `OUTL pin, rd` | pin = rd bit 0, rd shifts right | |
| 8 | T | `OUTM pin, rd` | pin = rd bit 7, rd shifts left | |
| 8 | T | `INL rd, pin` | rd shifts right, pin enters at bit 7 | |
| 8 | T | `INM rd, pin` | rd shifts left, pin enters at bit 0 | |
| 9 | 0 | `IN rd, port` | rd = port | |
| 9 | 1 | `OUT port, rd` | port = rd | |
| A | | `WAITT` | Wait for the tick and use it up | |
| A | | `TPERL #k` `TPERH #k` | Set the low or high byte of the period register | |
| A | | `TRST` | Counter = period, clear the tick | |
| A | | `TPH` | Counter = period / 2, clear the tick (to sample mid-bit) | |
| B | 0 | `LDA rd, addr` | rd = RAM[addr] | |
| B | 1 | `STA addr, rd` | RAM[addr] = rd | |
| C | 0 | `LD rd, [rs]` | rd = RAM[rs] | |
| C | 1 | `ST [rs], rd` | RAM[rs] = rd | |
| D, E, F | | reserved | Stops the thread and sets its fault bit | |

Sub-fields: opcode 0 uses bits 11:10 (0 = NOP, HALT, JR, SCHED chosen by bits 9:8; 1 = START; 2 = STOP) with the thread number in bits 9:8. Opcode 4 has the function in bits 7:4 (MOV 0, ADD 1, ADC 2, SUB 3, SBC 4, AND 5, OR 6, XOR 7, CMP 8, SHL 9, SHR 10, ROL 11, ROR 12). Opcode 5 has the condition in bits 11:8 (JMP 0, BZ 1, BNZ 2, BC 3, BNC 4, BT 5, BNT 6). Opcode 7 has the operation in bits 8:5 (CLR 0, SET 1, TGL 2, PUTC 3, GETC 4, DRV 5, HIZ 6, WAIT0 7, WAIT1 8) and the pin in bits 4:0. Opcode 8 has the mode in bits 7:6 and the pin in bits 4:0. Opcode A has the operation in bits 11:8 (WAITT 0, TPERL 1, TPERH 2, TRST 3, TPH 4).

Every 16-bit word has defined behaviour. Unassigned sub-field values inside opcodes 0 to C do nothing. The random tests include them.

Assembler pseudo-instructions: `TPER n` (two words), `INC rd`, `DEC rd`, `.equ`, `.word`.

## Ports

| Port | Name | Read | Write |
|---|---|---|---|
| 0 | `UIO` | `uio` pads (synchronised) | `uio` output latches |
| 1 | `OE` | Output enables | Output enables |
| 2 | `OD` | Open-drain bits | Open-drain bits |
| 3 | `UO` | `uo` latches | `uo` latches |
| 4 | `UI` | `ui` pads (synchronised) | Ignored |
| 5 | `FLAGS` | Flag bits | Flag bits |
| 6 | `TSTAT` | Bit 0 = tick, bit 1 = overrun (this thread) | Writing 1 to a bit clears it |
| 7 | `THR` | Bits 3:0 = thread running, bits 7:4 = thread faulted | Ignored |

## Loading a program

After reset the chip does nothing and drives nothing on the `uio` pins. A host shifts the program in on three input pins: `ui0` = cs_n, `ui1` = sck, `ui2` = mosi. Words are 16 bits, most significant bit first, sampled on the rising edge of sck, starting at address 0. The chip samples these pins with its own clock, so sck must be low for at least one clock and high for at least one clock.

When cs_n goes high after at least one word has been written, the chip starts thread 0 at address 0. From then on all 24 pins belong to the program. To load another program, pulse reset.

The loader always writes the whole memory. Unused words are filled with 0xFFFF, which faults if executed.

Hold reset low for at least three clocks so the input synchronisers hold real pad values when it is released.

## Configurations

| | Rev A (Tiny Tapeout, SKY130) | Larger version (planned) |
|---|---|---|
| Threads | 2 | 4 |
| Program memory | 32 words in flip-flops | 256 or more words (SRAM if it hardens, flip-flops if not) |
| Data RAM | 8 bytes | 64 bytes or more |
| Registers per thread | 8 | 8 |
| Opcodes D, E, F | Fault | Reserved for extensions |

Program addresses are 8 bits in the instruction format. Rev A uses the low 5 bits.
