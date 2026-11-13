; waits with a timeout: c tells the program which one ended the wait
; expect uo=0x01
        TPER 12
        TRST
        WAIT1.T f3          ; f3 is never set: ends at the tick with c = 1
        BNC  bad
        WAIT0.T f3          ; already 0: ends at once with c = 0
        BC   bad
        SET  f3
        WAIT1 f3
        SET  uo0
        HALT
bad:    SET  uo7
        HALT
