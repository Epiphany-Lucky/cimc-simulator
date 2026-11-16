/* Independent, freestanding Cortex-M4 Bootloader acceptance fixture.
 * GD32F470VET6 / CIMC V1: USART0 PA9/PA10 through the fixed H7/CH340 path.
 * This program selects already-programmed applications; it does not erase or
 * program Flash. It never enables external NVIC interrupts.
 */
typedef unsigned int u32;
typedef unsigned char u8;
#define REG(a) (*(volatile u32 *)(a))
#define MAILBOX ((volatile u32 *)0x20000000u)
#define UART0 0x40011000u
#define GPIOA 0x40020000u
#define APP_A 0x08010000u
#define APP_B 0x08020000u
#define APP_SLOT_SIZE 0x10000u

static void uart_init(void) {
    REG(0x40023830u) |= 1u;       /* GPIOA clock */
    REG(0x40023844u) |= 1u << 4; /* USART0 clock */
    REG(GPIOA) = (REG(GPIOA) & ~((3u << 18) | (3u << 20)))
               | (2u << 18) | (2u << 20);
    REG(GPIOA + 36) = (REG(GPIOA + 36) & ~((15u << 4) | (15u << 8)))
                    | (7u << 4) | (7u << 8);
    REG(UART0 + 8) = 139u; /* 115200 baud at the reset IRC16M clock. */
    REG(UART0 + 12) = (1u << 13) | (1u << 3) | (1u << 2);
}

static void uart_text(const char *text) {
    while (*text) {
        while (!(REG(UART0) & (1u << 7))) {}
        REG(UART0 + 4) = (u8)*text++;
    }
    while (!(REG(UART0) & (1u << 6))) {}
}

/* No C code, stack access, or function epilogue may follow MSR MSP.
 * r0 = target initial MSP; r1 = target Thumb Reset_Handler.
 * Bootloader and application run privileged Thread mode on MSP; neither uses
 * PSP, floating point, an RTOS, nor external NVIC interrupts.
 */
__attribute__((naked, noreturn))
static void jump_with_msp(u32 initial_msp, u32 reset_handler) {
    __asm volatile(
        "msr msp, r0\n"
        "bx r1\n"
    );
}

static void launch(u32 base) {
    u32 initial_msp = REG(base);
    u32 reset_handler = REG(base + 4);
    u32 address = reset_handler & ~1u;
    u32 valid_stack = !(initial_msp & 7u)
        && ((initial_msp > 0x20000000u && initial_msp <= 0x20030000u)
            || (initial_msp > 0x10000000u && initial_msp <= 0x10010000u));

    /* Each fixture has a 64 KiB slot. Erased (all-FF) vectors fail this check. */
    if (!valid_stack || !(reset_handler & 1u)
        || address < base || address >= base + APP_SLOT_SIZE) {
        uart_text("APP MISSING OR INVALID\r\n");
        return;
    }

    uart_text(base == APP_A ? "JUMP APP A\r\n" : "JUMP APP B\r\n");
    __asm volatile("cpsid i" ::: "memory");
    REG(0xE000E010u) = 0;      /* Stop the Bootloader's SysTick, if any. */
    REG(0xE000E018u) = 0;
    REG(0xE000ED04u) = 1u << 25; /* ICSR.PENDSTCLR; no fictitious NVIC reset. */
    REG(0xE000ED08u) = base;     /* SCB.VTOR must move with the application. */
    __asm volatile("dsb 0xF\n isb 0xF" ::: "memory");
    jump_with_msp(initial_msp, reset_handler);
}

void Unexpected_Tick_Handler(void) {
    MAILBOX[11] = 0xBAD0000Fu;
    for (;;) __asm volatile("nop");
}

void Reset_Handler(void) {
    u32 i;
    for (i = 0; i < 12; ++i) MAILBOX[i] = 0;
    MAILBOX[0] = 0x424F4F54u;
    uart_init();
    uart_text("BOOT READY\r\n");
    uart_text("SELECT 1 OR 2\r\n");
    for (;;) {
        if (REG(UART0) & (1u << 5)) {
            u8 value = (u8)REG(UART0 + 4);
            if (value == '1' || value == '2') {
                u32 base = value == '1' ? APP_A : APP_B;
                MAILBOX[1] = value - '0';
                MAILBOX[2] = base;
                MAILBOX[3]++;
                launch(base);
            }
        }
    }
}

__attribute__((section(".isr_vector"), used))
const void * const vectors[] = {
    (void *)0x20010000u, (void *)Reset_Handler,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    (void *)Unexpected_Tick_Handler
};
