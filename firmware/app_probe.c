/* One source, two separately linked Cortex-M4 application images.
 * Build with APP_ID=1 (A) or APP_ID=2 (B); see build-boot-probes.ps1.
 * The application deliberately does not repair VTOR: the Bootloader (or the
 * simulator's explicit reset-vector selection) must provide the correct value.
 */
typedef unsigned int u32;
typedef unsigned char u8;
#define REG(a) (*(volatile u32 *)(a))
#define MAILBOX ((volatile u32 *)0x20000000u)
#define UART0 0x40011000u
#define GPIOA 0x40020000u
#define GPIOD 0x40020C00u

#if APP_ID == 1
#define APP_MSP 0x20018000u
#define APP_MAGIC 0x41505041u
#define TICK_MAGIC 0x54494341u
#define APP_TEXT "APP A READY\r\n"
#define LED_BIT 10u
#elif APP_ID == 2
#define APP_MSP 0x20020000u
#define APP_MAGIC 0x41505042u
#define TICK_MAGIC 0x54494342u
#define APP_TEXT "APP B READY\r\n"
#define LED_BIT 11u
#else
#error "APP_ID must be 1 or 2"
#endif

static void uart_init(void) {
    REG(0x40023830u) |= 1u;
    REG(0x40023844u) |= 1u << 4;
    REG(GPIOA) = (REG(GPIOA) & ~((3u << 18) | (3u << 20)))
               | (2u << 18) | (2u << 20);
    REG(GPIOA + 36) = (REG(GPIOA + 36) & ~((15u << 4) | (15u << 8)))
                    | (7u << 4) | (7u << 8);
    REG(UART0 + 8) = 139u;
    REG(UART0 + 12) = (1u << 13) | (1u << 3) | (1u << 2);
}

static void uart_text(const char *text) {
    while (*text) {
        while (!(REG(UART0) & (1u << 7))) {}
        REG(UART0 + 4) = (u8)*text++;
    }
    while (!(REG(UART0) & (1u << 6))) {}
}

void Tick_Handler(void) {
    MAILBOX[7]++;
    MAILBOX[8] = TICK_MAGIC;
    MAILBOX[9] = REG(0xE000ED08u);
}

__attribute__((noreturn, used))
void App_Main(void) {
    MAILBOX[4] = APP_MAGIC;
    MAILBOX[7] = 0;
    MAILBOX[8] = 0;
    MAILBOX[9] = 0;
    MAILBOX[10] = 0;
    uart_init();
    REG(0x40023830u) |= 1u << 3;
    REG(GPIOD) = (REG(GPIOD) & 0x000FFFFFu) | 0x55500000u;
    REG(GPIOD + 20) = 1u << LED_BIT;
    uart_text(APP_TEXT);
    MAILBOX[10] = 0x52454144u;
    REG(0xE000E010u) = 0;
    REG(0xE000E014u) = 9999u;
    REG(0xE000E018u) = 0;
    REG(0xE000ED04u) = 1u << 25;
    REG(0xE000E010u) = 7u;
    __asm volatile("cpsie i" ::: "memory");
    for (;;) __asm volatile("nop");
}

/* Capture the exact initial MSP before any compiler-generated stack prologue.
 * No initialized data/BSS or C runtime startup is required by these fixtures.
 */
__attribute__((naked, noreturn))
void Reset_Handler(void) {
    __asm volatile(
        "ldr r0, =0x20000014\n"
        "mrs r1, msp\n"
        "str r1, [r0]\n"
        "ldr r0, =0xE000ED08\n"
        "ldr r1, [r0]\n"
        "ldr r0, =0x20000018\n"
        "str r1, [r0]\n"
        "b App_Main\n"
    );
}

__attribute__((section(".isr_vector"), used))
const void * const vectors[] = {
    (void *)APP_MSP, (void *)Reset_Handler,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    (void *)Tick_Handler
};
