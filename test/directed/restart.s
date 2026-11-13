; start clears a fault, stop stops another thread, thr reports both
; expect uo=0x01
        START 1, bad1
        SCHED 0,1,0,1
        NOP
        NOP
        IN   r0, THR        ; thread 1 has faulted: 0x21
        OUT  UO, r0
        START 1, good1
        NOP
        IN   r1, THR        ; fault cleared, both running: 0x03
        OUT  UO, r1
        STOP 1
        IN   r2, THR        ; 0x01
        OUT  UO, r2
        HALT
bad1:   .word 0xE000
good1:  SET  f0
        JMP  good1
