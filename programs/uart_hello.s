; uart transmit on uo0, 8n1. the timer sets the bit time.
; thread 0 owns every clock here, so one instruction = one clock
.equ BIT, 16                 ; clocks per bit (16 keeps the simulation short)

        SET   uo0            ; line idles high
        TPER  BIT            ; timer period = one bit time (2 words)
        TRST
next:   LDI   r0, #'H'
        JAL   r7, putc
        LDI   r0, #'i'
        JAL   r7, putc
        HALT

; putc: send r0. uses r1. returns through r7.
putc:   CLR.T uo0            ; start bit, exactly on a tick
        LDI   r1, #8
bit:    OUTL.T uo0, r0       ; one data bit per tick, lsb first
        DJNZ  r1, bit
        SET.T uo0            ; stop bit
        JR    r7
