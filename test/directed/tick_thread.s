; each thread sees only its own timer tick. overrun is recorded and can be cleared.
; expect uo=0x01
        START 1, t1
        SCHED 0,1,0,1
        TPER 200            ; thread 0: no tick for 200 clocks
        TRST
        LDI  r0, #10
l0:     BT   bad0           ; must not branch on thread 1's tick
        DJNZ r0, l0
        IN   r1, TSTAT
        STA  0, r1
        HALT
bad0:   SET  uo7
        HALT
t1:     TPER 4
        TRST
        NOP
        NOP
        NOP
        BT   ok1            ; thread 1's own tick is set by now
        SET  uo6
        HALT
ok1:    SET  uo0
        WAITT
        WAITT
        IN   r2, TSTAT      ; overrun is set: bt did not use the tick up
        OUT  FLAGS, r2
        LDI  r3, #2
        OUT  TSTAT, r3      ; clear the overrun bit
        IN   r4, TSTAT
        HALT
