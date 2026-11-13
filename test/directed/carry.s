; carry and borrow through adc, sbc, rol, ror, and compares on equal values
; expect uo=0x82
        LDI  r0, #0xFF
        ADDI r0, #1         ; r0 = 0, c = 1
        LDI  r1, #5
        LDI  r2, #3
        ADC  r1, r2         ; 5 + 3 + 1 = 9, c = 0
        CMPI r0, #1         ; 0 < 1, so c = 1
        SBC  r1, r2         ; 9 - 3 - 1 = 5
        CMPI r0, #1         ; c = 1 again
        ROR  r3, r1         ; r3 = 0x82, c = 1
        ROL  r4, r1         ; r4 = 0x0b, c = 0
        LDI  r5, #7
        CMPI r5, #7         ; equal: z = 1, c = 0
        BC   bad
        CMP  r5, r5         ; equal: c = 0
        BC   bad
        CMPI r5, #8         ; 7 < 8: c = 1
        BNC  bad
        OUT  UO, r3
        HALT
bad:    LDI  r6, #0xEE
        OUT  UO, r6
        HALT
