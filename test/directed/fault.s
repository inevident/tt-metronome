; a reserved opcode stops its thread at once, even when it owns the next clock
; expect uo=0x00
        START 1, t1
        SCHED 1,1,1,1       ; thread 1 owns every clock from here
        NOP
t1:     LDI  r1, #3
        .word 0xF123        ; reserved: thread 1 faults
        SET  uo5            ; must never run
        SET  uo4
