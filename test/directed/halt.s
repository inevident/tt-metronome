; halt when the same thread owns the next clock: nothing after it may run
; expect uo=0x01
        LDI  r0, #1
        OUT  UO, r0
        HALT
        SET  uo7            ; must never run
        SET  uo6
