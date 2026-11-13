; open-drain pins, output enables, and reading a pad that differs from its latch
        LDI  r0, #0x0F
        OUT  OD, r0         ; uio0..3 are open-drain
        LDI  r1, #0x35
        OUT  OE, r1
        LDI  r2, #0x5A
        OUT  UIO, r2
        TGL  uio0
        SET  uio1
        CLR  uio2
        HIZ  uio4
        DRV  uio7
        LDI  r3, #8
loop:   GETC uio1           ; c comes from the pad, not the latch
        ROL  r4, r4
        GETC uio5
        ROL  r5, r5
        GETC ui3
        ROL  r6, r6
        DJNZ r3, loop
        OUT  UO, r4
        IN   r7, UIO
        HALT
