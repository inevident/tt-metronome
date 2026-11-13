/*
 * Copyright (c) 2026 Ryan Lim
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// rev a configuration: 2 threads, 32 words of program, 8 bytes of ram.
// the test bench overrides these to check other sizes
`ifndef METRO_NT
`define METRO_NT 2
`endif
`ifndef METRO_PW
`define METRO_PW 5
`endif
`ifndef METRO_RAMB
`define METRO_RAMB 8
`endif

module tt_um_inevident_metronome (
    input  wire [7:0] ui_in,    // dedicated inputs
    output wire [7:0] uo_out,   // dedicated outputs
    input  wire [7:0] uio_in,   // ios: input path
    output wire [7:0] uio_out,  // ios: output path
    output wire [7:0] uio_oe,   // ios: enable path (1 = output)
    input  wire       ena,      // always 1 when the design is powered
    input  wire       clk,
    input  wire       rst_n
);

    metro_core #(
        .NT  (`METRO_NT),
        .PW  (`METRO_PW),
        .RAMB(`METRO_RAMB)
    ) core (
        .clk    (clk),
        .rst_n  (rst_n),
        .ui_in  (ui_in),
        .uio_in (uio_in),
        .uo_out (uo_out),
        .uio_out(uio_out),
        .uio_oe (uio_oe)
    );

    wire _unused = &{ena, 1'b0};

endmodule
