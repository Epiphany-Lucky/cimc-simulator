/* GD32F470 real-machine-code watchdog/IRQ/reset acceptance.
 * USART0 PA9/PA10 AF7 uses the board's real CH340 wiring.
 * Send F for FWDGT reset, W for WWDGT reset, E for EWI servicing and refresh.
 * PD10/PD11 indicate observed FWDGT/WWDGT reset flags after an actual reboot.
 * SRAM0x20001000 words report stage, selected command, EWI count, reset flags.
 */
typedef unsigned int u32;
#define REG(address) (*(volatile u32 *)(address))
#define MAILBOX ((volatile u32 *)0x20001000u)
#define UART0 0x40011000u
#define GPIOD 0x40020C00u
#define RSTSCK 0x40023874u
#define FWDGT 0x40003000u
#define WWDGT 0x40002C00u

static void text(const char *message) {
    while (*message) {
        while (!(REG(UART0) & 0x80u)) {}
        REG(UART0 + 4u) = (u32)*message++;
    }
}

static void init_io(void) {
    REG(0x40023830u) |= (1u << 0) | (1u << 3);
    REG(0x40023844u) |= 1u << 4;
    REG(0x40020000u) = (2u << 18) | (2u << 20);
    REG(0x40020024u) = (7u << 4) | (7u << 8);
    REG(UART0 + 8u) = 139u;
    REG(UART0 + 12u) = (1u << 13) | (1u << 3) | (1u << 2);
    REG(GPIOD) = (1u << 20) | (1u << 22) | (1u << 24);
    REG(GPIOD + 20u) = 0;
}

void WWDGT_IRQHandler(void) {
    if (REG(WWDGT + 8u) & 1u) {
        REG(WWDGT + 8u) = 0;
        if (MAILBOX[1] == 'E') REG(WWDGT) = 0x7Fu;
        MAILBOX[2] += 1u;
        REG(GPIOD + 24u) = 1u << 12;
        text("W EWI\n");
    }
}

void Reset_Handler(void) {
    u32 flags;
    u32 index;
    init_io();
    flags = REG(RSTSCK);
    for (index = 0; index < 4; ++index) MAILBOX[index] = 0;
    MAILBOX[3] = flags;
    if (flags & (1u << 29)) {
        MAILBOX[0] = 0x46574F4Bu; /* FWOK */
        REG(GPIOD + 20u) = 1u << 10;
        text("FWDGT RESET\n");
    } else if (flags & (1u << 30)) {
        MAILBOX[0] = 0x57574F4Bu; /* WWOK */
        REG(GPIOD + 20u) = 1u << 11;
        text("WWDGT RESET\n");
    } else {
        MAILBOX[0] = 0x57414954u; /* WAIT */
        text("WDGT SELECT F W E\n");
    }
    for (;;) {
        if (MAILBOX[1]) __asm volatile("wfi");
        if (!(REG(UART0) & 0x20u)) continue;
        u32 command = REG(UART0 + 4u) & 0xFFu;
        if (command == 'C') {
            REG(RSTSCK) |= 1u << 24;
            MAILBOX[3] = REG(RSTSCK);
            text("FLAGS CLEAR\n");
        } else if (MAILBOX[0] == 0x57414954u && command == 'F') {
            MAILBOX[1] = command;
            REG(RSTSCK) |= 1u << 24;
            REG(FWDGT) = 0x5555u;
            REG(FWDGT + 4u) = 1u;
            REG(FWDGT + 8u) = 3u;
            REG(FWDGT) = 0xAAAAu;
            REG(FWDGT) = 0xCCCCu;
        } else if (MAILBOX[0] == 0x57414954u && (command == 'W' || command == 'E')) {
            MAILBOX[1] = command;
            REG(RSTSCK) |= 1u << 24;
            REG(0x40023840u) |= 1u << 11;
            REG(WWDGT + 4u) = 0x3FFu; /* EWI, divide8, window0x7F. */
            REG(0xE000E100u) = 1u; /* NVIC IRQ0. */
            REG(WWDGT) = 0xC1u;
        }
    }
}

__attribute__((section(".isr_vector"), used))
const void *const vectors[17] = {
    [0] = (void *)0x20010000u,
    [1] = (void *)Reset_Handler,
    [16] = (void *)WWDGT_IRQHandler,
};
