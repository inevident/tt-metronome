// SPDX-License-Identifier: Apache-2.0
//
// metronome rev a core
// one instruction runs per clock. a 4-entry schedule says which thread owns
// each clock, so a thread's timing never depends on the other threads
// tools/metro/emu.py is the reference model this is tested against

`default_nettype none

module metro_core #(
    parameter NT   = 2,   // hardware threads: 2 or 4
    parameter PW   = 5,   // program address bits (at most 8)
    parameter RAMB = 8    // data ram bytes: a power of two, at least 2
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] ui_in,
    input  wire [7:0] uio_in,
    output wire [7:0] uo_out,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe
);

    localparam TI = (NT > 2) ? 2 : 1;                 // thread index bits
    localparam RW = (RAMB > 128) ? 8 : (RAMB > 64) ? 7 : (RAMB > 32) ? 6 :
                    (RAMB > 16)  ? 5 : (RAMB > 8)  ? 4 : (RAMB > 4)  ? 3 :
                    (RAMB > 2)   ? 2 : 1;             // ram address bits

    integer i0, i1, i2, i3;

    // input synchronisers. no reset, they just follow the pads
    reg [7:0] s1_ui, s2_ui, s1_uio, s2_uio;
    always @(posedge clk) begin
        s1_ui  <= ui_in;   s2_ui  <= s1_ui;
        s1_uio <= uio_in;  s2_uio <= s1_uio;
    end

    // program loader. after reset the chip waits while a host shifts words in
    // on ui[2:0] (cs_n, sck, mosi), msb first. cs_n going high starts the
    // program, but only if at least one word was written
    reg          running, loaded, cs_d, sck_d;
    reg  [3:0]   bitcnt;
    reg  [PW-1:0] laddr;
    reg  [15:0]  shreg;

    wire l_cs   = s2_ui[0];
    wire l_sck  = s2_ui[1];
    wire l_mosi = s2_ui[2];
    wire l_shift = rst_n & ~running & ~l_cs & l_sck & ~sck_d;
    wire [15:0] l_word = {shreg[14:0], l_mosi};
    wire l_we   = l_shift & (bitcnt == 4'd15);

    always @(posedge clk) begin
        if (!rst_n) begin
            running <= 1'b0;
            loaded  <= 1'b0;
            cs_d    <= 1'b1;
            sck_d   <= 1'b0;
            bitcnt  <= 4'd0;
            laddr   <= {PW{1'b0}};
        end else if (!running) begin
            cs_d  <= l_cs;
            sck_d <= l_sck;
            if (l_shift) bitcnt <= bitcnt + 4'd1;
            if (l_we) begin
                laddr  <= laddr + 1'b1;
                loaded <= 1'b1;
            end
            if (l_cs & ~cs_d & loaded) running <= 1'b1;
        end
        if (l_shift) shreg <= l_word;
    end

    // program memory. ir is the instruction that runs next clock
    reg [15:0] prog [0:(1<<PW)-1];
    reg [15:0] ir;
    reg [PW-1:0] fetch_addr;

    always @(posedge clk) begin
        if (l_we) prog[laddr] <= l_word;
        ir <= prog[fetch_addr];
    end

    // state
    reg [1:0]    ir_th;                // thread that owns the current clock
    reg          ir_v;                 // 0 = idle slot
    reg [1:0]    phase;                // position in the 4-clock schedule
    reg [7:0]    sched;                // thread id for each phase, 2 bits each

    reg [PW-1:0] pc   [0:NT-1];
    reg [NT-1:0] run, fault, zf, cf;
    reg [7:0]    regs [0:NT*8-1];

    reg [15:0]   cnt  [0:NT-1];        // timer down-counter
    reg [15:0]   per  [0:NT-1];        // timer period minus one
    reg [NT-1:0] tick, ovr;

    reg [7:0]    uio_o, uio_e, uio_d;  // uio pins: latch, enable, open-drain
    reg [7:0]    uo;                   // output pins
    reg [7:0]    flags;                // 8 internal flag bits that act like pins
    reg [7:0]    ram  [0:RAMB-1];

    assign uo_out  = uo;
    assign uio_out = uio_o & ~uio_d;
    assign uio_oe  = (uio_e & ~uio_d) | (uio_d & ~uio_o);

    // decode
    wire [3:0]    op   = ir[15:12];
    wire          x    = ir[11];
    wire [2:0]    rd   = ir[10:8];
    wire [2:0]    rs   = ir[2:0];
    wire [7:0]    imm  = ir[7:0];
    wire [1:0]    xx   = ir[9:8];
    wire [4:0]    pin  = ir[4:0];
    wire [TI-1:0] t    = ir_th[TI-1:0];
    wire          ex   = running & ir_v;

    wire [7:0]    a    = regs[{t, rd}];
    wire [7:0]    b    = regs[{t, rs}];
    wire          zq   = zf[t];
    wire          cq   = cf[t];
    wire          tk   = tick[t];
    wire [PW-1:0] pc1  = pc[t] + 1'b1;
    wire [PW-1:0] tgt  = imm[PW-1:0];

    wire [31:0] pin_all   = {flags, s2_ui, uo, s2_uio};
    wire [31:0] latch_all = {flags, 8'h00, uo, uio_o};
    wire        pinv = pin_all[pin];
    wire        latv = latch_all[pin];

    wire [7:0]    ram_addr = (op == 4'hB) ? imm : b;
    wire [7:0]    ram_rd   = ram[ram_addr[RW-1:0]];

    reg [7:0] thr_rd;
    always @* begin
        thr_rd = 8'h00;
        for (i0 = 0; i0 < NT; i0 = i0 + 1) begin
            thr_rd[i0]     = run[i0];
            thr_rd[4 + i0] = fault[i0];
        end
    end

    reg [7:0] port_rd;
    always @* begin
        case (imm)
            8'd0:    port_rd = s2_uio;
            8'd1:    port_rd = uio_e;
            8'd2:    port_rd = uio_d;
            8'd3:    port_rd = uo;
            8'd4:    port_rd = s2_ui;
            8'd5:    port_rd = flags;
            8'd6:    port_rd = {6'b0, ovr[t], tk};
            8'd7:    port_rd = thr_rd;
            default: port_rd = 8'h00;
        endcase
    end

    // alu
    wire [3:0] fn    = ir[7:4];
    wire [8:0] add_s = {1'b0, a} + {1'b0, b} + {8'b0, (fn == 4'd2) & cq};
    wire [8:0] sub_s = {1'b0, a} - {1'b0, b} - {8'b0, (fn == 4'd4) & cq};

    reg [7:0] alu_r;
    reg       alu_c, alu_wr, alu_wc, alu_wz;
    always @* begin
        alu_r = b; alu_c = cq; alu_wr = 1'b1; alu_wc = 1'b0; alu_wz = 1'b1;
        case (fn)
            4'd0:       alu_wz = 1'b0;                                           // mov
            4'd1, 4'd2: begin alu_r = add_s[7:0]; alu_c = add_s[8]; alu_wc = 1'b1; end
            4'd3, 4'd4: begin alu_r = sub_s[7:0]; alu_c = sub_s[8]; alu_wc = 1'b1; end
            4'd5:       alu_r = a & b;
            4'd6:       alu_r = a | b;
            4'd7:       alu_r = a ^ b;
            4'd8:       begin alu_r = sub_s[7:0]; alu_c = sub_s[8]; alu_wc = 1'b1; alu_wr = 1'b0; end
            4'd9:       begin alu_r = {b[6:0], 1'b0}; alu_c = b[7]; alu_wc = 1'b1; end
            4'd10:      begin alu_r = {1'b0, b[7:1]}; alu_c = b[0]; alu_wc = 1'b1; end
            4'd11:      begin alu_r = {b[6:0], cq};   alu_c = b[7]; alu_wc = 1'b1; end
            4'd12:      begin alu_r = {cq, b[7:1]};   alu_c = b[0]; alu_wc = 1'b1; end
            default:    begin alu_wr = 1'b0; alu_wz = 1'b0; end
        endcase
    end

    wire [8:0] addi_s = {1'b0, a} + {1'b0, imm};

    // what the current instruction does if it completes
    reg          stall;                 // instruction waits: nothing changes
    reg [PW-1:0] npc;
    reg          rw;   reg [7:0] rwd;   // write register rd
    reg          wz, nz, wc, nc;        // flag writes
    reg          halt, flt;
    reg          consume, trst, tph, perl_w, perh_w, ovr_clr;
    reg          lat_w, lat_v, oe_w, oe_v;
    reg          port_w, ram_w, sched_w, start, stop;
    reg          take;

    always @* begin
        stall = 1'b0;  npc = pc1;
        rw = 1'b0;     rwd = imm;
        wz = 1'b0; nz = 1'b0; wc = 1'b0; nc = 1'b0;
        halt = 1'b0; flt = 1'b0;
        consume = 1'b0; trst = 1'b0; tph = 1'b0; perl_w = 1'b0; perh_w = 1'b0; ovr_clr = 1'b0;
        lat_w = 1'b0; lat_v = 1'b0; oe_w = 1'b0; oe_v = 1'b0;
        port_w = 1'b0; ram_w = 1'b0; sched_w = 1'b0; start = 1'b0; stop = 1'b0;
        take = 1'b0;

        case (op)
            4'h0: begin                                         // sys
                case (ir[11:10])
                    2'd0: case (xx)
                        2'd1: halt = 1'b1;                      // halt
                        2'd2: npc = b[PW-1:0];                  // jr rs
                        2'd3: sched_w = 1'b1;                   // sched
                        default: ;                              // nop
                    endcase
                    2'd1: start = 1'b1;                         // start th, target
                    2'd2: stop  = 1'b1;                         // stop th
                    default: ;
                endcase
            end
            4'h1: begin
                rw = 1'b1;
                if (x) begin                                    // addi
                    rwd = addi_s[7:0];
                    wz = 1'b1; nz = (addi_s[7:0] == 8'h00);
                    wc = 1'b1; nc = addi_s[8];
                end                                             // else ldi: rwd = imm
            end
            4'h2: begin                                         // andi / ori
                rw = 1'b1;
                rwd = x ? (a | imm) : (a & imm);
                wz = 1'b1; nz = (rwd == 8'h00);
            end
            4'h3: begin
                if (x) begin                                    // cmpi
                    wz = 1'b1; nz = (a == imm);
                    wc = 1'b1; nc = (a < imm);
                end else begin                                  // xori
                    rw = 1'b1; rwd = a ^ imm;
                    wz = 1'b1; nz = (rwd == 8'h00);
                end
            end
            4'h4: begin                                         // alu
                rw = alu_wr; rwd = alu_r;
                wz = alu_wz; nz = (alu_r == 8'h00);
                wc = alu_wc; nc = alu_c;
            end
            4'h5: begin                                         // branches
                case (ir[11:8])
                    4'd0: take = 1'b1;
                    4'd1: take = zq;
                    4'd2: take = ~zq;
                    4'd3: take = cq;
                    4'd4: take = ~cq;
                    4'd5: take = tk;
                    4'd6: take = ~tk;
                    default: take = 1'b0;
                endcase
                if (take) npc = tgt;
            end
            4'h6: begin
                rw = 1'b1;
                if (x) begin                                    // jal
                    rwd = 8'h00; rwd[PW-1:0] = pc1;
                    npc = tgt;
                end else begin                                  // djnz
                    rwd = a - 8'd1;
                    if (a != 8'd1) npc = tgt;
                end
            end
            4'h7: begin                                         // pin
                if (ir[8:5] <= 4'd6) begin
                    if (x & ~tk) stall = 1'b1;
                    else begin
                        consume = x;
                        case (ir[8:5])
                            4'd0: begin lat_w = 1'b1; lat_v = 1'b0;  end   // clr
                            4'd1: begin lat_w = 1'b1; lat_v = 1'b1;  end   // set
                            4'd2: begin lat_w = 1'b1; lat_v = ~latv; end   // tgl
                            4'd3: begin lat_w = 1'b1; lat_v = cq;    end   // putc
                            4'd4: begin wc = 1'b1; nc = pinv;        end   // getc
                            4'd5: begin oe_w = 1'b1; oe_v = 1'b1;    end   // drv
                            default: begin oe_w = 1'b1; oe_v = 1'b0; end   // hiz
                        endcase
                    end
                end else if (ir[8:5] == 4'd7 || ir[8:5] == 4'd8) begin     // wait0 / wait1
                    if (pinv == ir[8]) begin
                        if (x) begin wc = 1'b1; nc = 1'b0; end
                    end else if (x & tk) begin                              // timed out
                        wc = 1'b1; nc = 1'b1; consume = 1'b1;
                    end else stall = 1'b1;
                end
            end
            4'h8: begin                                         // shp
                if (x & ~tk) stall = 1'b1;
                else begin
                    consume = x;
                    rw = 1'b1;
                    case (ir[7:6])
                        2'd0: begin lat_w = 1'b1; lat_v = a[0]; rwd = {1'b0, a[7:1]}; end   // outl
                        2'd1: begin lat_w = 1'b1; lat_v = a[7]; rwd = {a[6:0], 1'b0}; end   // outm
                        2'd2: rwd = {pinv, a[7:1]};                                         // inl
                        default: rwd = {a[6:0], pinv};                                      // inm
                    endcase
                end
            end
            4'h9: begin                                         // port
                if (x) begin                                    // out
                    port_w = 1'b1;
                    if (imm == 8'd6) begin consume = a[0]; ovr_clr = a[1]; end
                end else begin                                  // in
                    rw = 1'b1; rwd = port_rd;
                end
            end
            4'hA: begin                                         // time
                case (ir[11:8])
                    4'd0: if (tk) consume = 1'b1; else stall = 1'b1;   // waitt
                    4'd1: perl_w = 1'b1;
                    4'd2: perh_w = 1'b1;
                    4'd3: trst = 1'b1;
                    4'd4: tph  = 1'b1;
                    default: ;
                endcase
            end
            4'hB, 4'hC: begin                                   // lda/sta, ld/st
                if (x) ram_w = 1'b1;
                else begin rw = 1'b1; rwd = ram_rd; end
            end
            default: begin halt = 1'b1; flt = 1'b1; end         // reserved: fault
        endcase
    end

    wire do_ = ex & ~stall;             // the instruction completes this clock

    // fetch for the next clock, using the state as it will be after this
    // instruction. start, stop, sched and branches take effect with no bubble
    wire [1:0] pn       = phase + 2'd1;
    wire [7:0] sched_nx = (do_ & sched_w) ? imm : sched;
    wire [1:0] nth      = sched_nx[{pn, 1'b0} +: 2];

    reg [PW-1:0] f_pc;
    reg          f_run;
    always @* begin
        f_pc = {PW{1'b0}}; f_run = 1'b0;
        for (i1 = 0; i1 < NT; i1 = i1 + 1) begin
            if (nth == i1) begin
                if (do_ && start && xx == i1) begin
                    f_pc = tgt; f_run = 1'b1;
                end else begin
                    f_pc  = (do_ && t == i1) ? npc : pc[i1];
                    f_run = run[i1];
                    if (do_ && t == i1 && halt)  f_run = 1'b0;
                    if (do_ && stop && xx == i1) f_run = 1'b0;
                end
            end
        end
        fetch_addr = running ? f_pc : {PW{1'b0}};
    end

    // state update
    always @(posedge clk) begin
        if (!rst_n) begin
            ir_th <= 2'd0;  ir_v <= 1'b1;  phase <= 2'd0;  sched <= 8'h00;
            run   <= {{(NT-1){1'b0}}, 1'b1};
            fault <= {NT{1'b0}};  zf <= {NT{1'b0}};  cf <= {NT{1'b0}};
            tick  <= {NT{1'b0}};  ovr <= {NT{1'b0}};
            uio_o <= 8'h00; uio_e <= 8'h00; uio_d <= 8'h00; uo <= 8'h00; flags <= 8'h00;
            for (i2 = 0; i2 < NT; i2 = i2 + 1) begin
                pc[i2]  <= {PW{1'b0}};
                cnt[i2] <= 16'hFFFF;
                per[i2] <= 16'hFFFF;
            end
            for (i2 = 0; i2 < NT*8; i2 = i2 + 1) regs[i2] <= 8'h00;
            for (i2 = 0; i2 < RAMB; i2 = i2 + 1) ram[i2]  <= 8'h00;
        end else if (running) begin
            phase <= pn;
            ir_th <= nth;
            ir_v  <= f_run;

            if (do_) begin
                pc[t] <= npc;
                if (rw) regs[{t, rd}] <= rwd;
                if (wz) zf[t] <= nz;
                if (wc) cf[t] <= nc;
                if (halt) run[t]   <= 1'b0;
                if (flt)  fault[t] <= 1'b1;
                if (sched_w) sched <= imm;

                if (lat_w) begin
                    case (pin[4:3])
                        2'd0: uio_o[pin[2:0]] <= lat_v;
                        2'd1: uo[pin[2:0]]    <= lat_v;
                        2'd3: flags[pin[2:0]] <= lat_v;
                        default: ;                       // ui pins are inputs
                    endcase
                end
                if (oe_w && pin[4:3] == 2'd0) uio_e[pin[2:0]] <= oe_v;

                if (port_w) begin
                    case (imm)
                        8'd0: uio_o <= a;
                        8'd1: uio_e <= a;
                        8'd2: uio_d <= a;
                        8'd3: uo    <= a;
                        8'd5: flags <= a;
                        default: ;
                    endcase
                end
                if (ram_w) ram[ram_addr[RW-1:0]] <= a;

                // start and stop come last so they win when a thread targets itself
                for (i2 = 0; i2 < NT; i2 = i2 + 1) begin
                    if (start && xx == i2) begin
                        run[i2] <= 1'b1;  fault[i2] <= 1'b0;  pc[i2] <= tgt;
                    end
                    if (stop && xx == i2) run[i2] <= 1'b0;
                end
            end

            // one timer per thread, counting every clock
            for (i2 = 0; i2 < NT; i2 = i2 + 1) begin
                if (do_ && t == i2 && (trst || tph)) begin
                    cnt[i2]  <= trst ? per[i2] : {1'b0, per[i2][15:1]};
                    tick[i2] <= 1'b0;
                end else begin
                    cnt[i2] <= (cnt[i2] == 16'd0) ? per[i2] : cnt[i2] - 16'd1;
                    if (cnt[i2] == 16'd0)                tick[i2] <= 1'b1;
                    else if (do_ && t == i2 && consume)  tick[i2] <= 1'b0;
                    if (cnt[i2] == 16'd0 && tick[i2] && !(do_ && t == i2 && consume))
                        ovr[i2] <= 1'b1;                 // tick arrived before the last one was used
                    else if (do_ && t == i2 && ovr_clr)
                        ovr[i2] <= 1'b0;
                end
                if (do_ && t == i2 && perl_w) per[i2][7:0]  <= imm;
                if (do_ && t == i2 && perh_w) per[i2][15:8] <= imm;
            end
        end else begin
            // waiting for a program: keep thread 0's first instruction ready
            ir_th <= 2'd0;  ir_v <= 1'b1;  phase <= 2'd0;
        end
    end

`ifdef METRO_DEBUG
    // flattened per-thread state, for the testbench only
    reg [NT*8-1:0]   dbg_pc;
    reg [NT*64-1:0]  dbg_regs;
    reg [NT*16-1:0]  dbg_cnt, dbg_per;
    reg [RAMB*8-1:0] dbg_ram;
    always @* begin
        dbg_pc = {(NT*8){1'b0}};
        for (i3 = 0; i3 < NT; i3 = i3 + 1) begin
            dbg_pc[i3*8 +: PW]   = pc[i3];
            dbg_cnt[i3*16 +: 16] = cnt[i3];
            dbg_per[i3*16 +: 16] = per[i3];
        end
        for (i3 = 0; i3 < NT*8; i3 = i3 + 1) dbg_regs[i3*8 +: 8] = regs[i3];
        for (i3 = 0; i3 < RAMB; i3 = i3 + 1) dbg_ram[i3*8 +: 8]  = ram[i3];
    end
`endif

endmodule
