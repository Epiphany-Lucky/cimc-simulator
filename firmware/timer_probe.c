/* Independent GD32F470 timer acceptance firmware, built with Keil Arm Compiler.
 * Mode at SRAM word 31 selects all-timer IRQs (0), PWM/capture (1),
 * GPIO-driven quadrature encoder (2), timer master/slave counting (3),
 * genuine nested timer interrupts with BASEPRI masking (4), or the four
 * advanced timer interrupt vectors and their shared trigger/commutation IRQ (5).
 * Every peripheral effect and interrupt result is produced by ARM instructions.
 */
typedef unsigned int u32;
#define REG(address) (*(volatile u32 *)(address))
#define MAILBOX ((volatile u32 *)0x20000000u)
#define GPIOA 0x40020000u
#define GPIOD 0x40020C00u
#define USART0 0x40011000u
#define RCU_AHB1EN 0x40023830u
#define RCU_APB1EN 0x40023840u
#define RCU_APB2EN 0x40023844u
#define PASS 0x54494D52u
#define FAIL 0x4641494Cu

static const u32 timer_base[14] = {
    0x40010000u, 0x40000000u, 0x40000400u, 0x40000800u,
    0x40000C00u, 0x40001000u, 0x40001400u, 0x40010400u,
    0x40014000u, 0x40014400u, 0x40014800u, 0x40001800u,
    0x40001C00u, 0x40002000u
};
static const u32 timer_irq[14] = {25, 28, 29, 30, 50, 54, 55, 44, 24, 25, 26, 43, 44, 45};
static const u32 timer_enable_bit[14] = {0, 0, 1, 2, 3, 4, 5, 1, 16, 17, 18, 6, 7, 8};

static void uart_init(void) {
    REG(RCU_AHB1EN) |= (1u << 0) | (1u << 3);
    REG(RCU_APB2EN) |= 1u << 4;
    REG(GPIOA) = (REG(GPIOA) & ~(3u << 18)) | (2u << 18);
    REG(GPIOA + 36u) = (REG(GPIOA + 36u) & ~(15u << 4)) | (7u << 4);
    REG(USART0 + 8u) = 0x8Bu;
    REG(USART0 + 12u) = (1u << 13) | (1u << 3);
}

static void uart_text(const char *text) {
    while (*text) {
        while (!(REG(USART0) & (1u << 7))) {}
        REG(USART0 + 4u) = (u32)*text++;
    }
}

static void enable_timer(u32 index) {
    u32 enable = (index == 0u || index == 7u || (index >= 8u && index <= 10u))
        ? RCU_APB2EN : RCU_APB1EN;
    u32 reset = enable - 32u;
    u32 bit = 1u << timer_enable_bit[index];
    REG(enable) |= bit;
    REG(reset) |= bit;
    REG(reset) &= ~bit;
}

static void enable_irq(u32 irq) {
    REG(0xE000E100u + (irq / 32u) * 4u) = 1u << (irq % 32u);
}

static void delay_edges(void) {
    u32 count;
    for (count = 0; count < 16u; ++count) __asm volatile("nop");
}

void Timer_Handler(void) {
    u32 index;
    u32 exception;
    __asm volatile("mrs %0, ipsr" : "=r"(exception));
    exception -= 16u;
    MAILBOX[16u + exception / 32u] |= 1u << (exception % 32u);
    if (MAILBOX[31] == 5u) {
        u32 status = REG(timer_base[0] + 0x10u);
        u32 clear = 0u;
        if (exception == 24u && (status & 0x80u)) { MAILBOX[1]++; clear |= 0x80u; }
        if (exception == 25u && (status & 1u)) { MAILBOX[2]++; clear |= 1u; }
        if (exception == 26u) {
            if (status & 0x20u) { MAILBOX[3]++; clear |= 0x20u; }
            if (status & 0x40u) { MAILBOX[4]++; clear |= 0x40u; }
        }
        if (exception == 27u && (status & 2u)) { MAILBOX[5]++; clear |= 2u; }
        REG(timer_base[0] + 0x10u) = ~clear;
        return;
    }
    if (MAILBOX[31] == 4u) {
        if (exception == 28u) {
            u32 timeout = 100000u;
            MAILBOX[29] = (MAILBOX[29] << 4) | 1u;
            REG(timer_base[2]) = 9u;
            while (!MAILBOX[30] && --timeout) {}
            MAILBOX[29] = (MAILBOX[29] << 4) | 3u;
            MAILBOX[15]++;
            REG(timer_base[1] + 0x10u) = 0u;
        } else if (exception == 29u) {
            MAILBOX[29] = (MAILBOX[29] << 4) | 2u;
            MAILBOX[30]++;
            REG(timer_base[2] + 0x10u) = 0u;
        }
        return;
    }
    if (MAILBOX[31] == 1u) {
        u32 status = REG(timer_base[1] + 0x10u);
        if (status & 2u) {
            u32 captured = REG(timer_base[1] + 0x34u);
            MAILBOX[27] = captured - MAILBOX[25];
            MAILBOX[25] = captured;
            MAILBOX[24]++;
            if (status & (1u << 9)) MAILBOX[28]++;
            REG(timer_base[1] + 0x10u) = ~((1u << 9) | 2u);
        }
        return;
    }
    for (index = 0; index < 14u; ++index) {
        u32 base = timer_base[index];
        if (REG(base + 0x10u) & REG(base + 0x0Cu) & 1u) {
            REG(base) &= ~1u;
            REG(base + 0x10u) = ~1u;
            MAILBOX[index + 1u]++;
        }
    }
}

static void test_all_irqs(void) {
    u32 index;
    for (index = 0; index < 14u; ++index) {
        u32 base = timer_base[index];
        u32 timeout = 200000u;
        enable_timer(index);
        enable_irq(timer_irq[index]);
        REG(base + 0x28u) = 7u;
        REG(base + 0x2Cu) = 255u;
        REG(base + 0x14u) = 1u;
        REG(base + 0x10u) = 0u;
        REG(base + 0x0Cu) = 1u;
        MAILBOX[19] = index;
        REG(base) = 1u;
        while (!MAILBOX[index + 1u] && --timeout) {}
        if (!timeout || MAILBOX[index + 1u] != 1u) {
            MAILBOX[20] = index + 1u;
            MAILBOX[0] = FAIL;
            uart_text("TIMER IRQ FAIL\r\n");
            return;
        }
    }
    REG(timer_base[1] + 0x2Cu) = 0xFFFFFFFFu;
    REG(timer_base[4] + 0x2Cu) = 0xFFFFFFFFu;
    REG(timer_base[1] + 0x24u) = 0x89ABCDEFu;
    REG(timer_base[4] + 0x24u) = 0xFEDCBA98u;
    MAILBOX[21] = REG(timer_base[1] + 0x24u);
    MAILBOX[22] = REG(timer_base[4] + 0x24u);
    if (MAILBOX[21] != 0x89ABCDEFu || MAILBOX[22] != 0xFEDCBA98u) {
        MAILBOX[20] = 32u;
        MAILBOX[0] = FAIL;
        uart_text("TIMER WIDTH FAIL\r\n");
        return;
    }
    REG(GPIOD) = (REG(GPIOD) & ~0x0FFF0000u) | 0x05550000u;
    REG(GPIOD + 20u) = 0x3500u;
    MAILBOX[0] = PASS;
    uart_text("ALL14 TIMER IRQ OK\r\n");
}

static void pwm_capture(void) {
    u32 base;
    enable_timer(1u);
    enable_timer(3u);
    /* Real jumpers connect PD12 / TIMER3_CH0 to PA5 / TIMER1_CH0. */
    REG(GPIOA) = (REG(GPIOA) & ~(3u << 10)) | (2u << 10);
    REG(GPIOA + 32u) = (REG(GPIOA + 32u) & ~(15u << 20)) | (1u << 20);
    REG(GPIOD) = (REG(GPIOD) & ~(3u << 24)) | (2u << 24);
    REG(GPIOD + 36u) = (REG(GPIOD + 36u) & ~(15u << 16)) | (2u << 16);
    base = timer_base[1];
    REG(base + 0x2Cu) = 0xFFFFFFFFu;
    REG(base + 0x18u) = 1u;
    REG(base + 0x20u) = 1u;
    REG(base + 0x0Cu) = 2u;
    enable_irq(28u);
    REG(base) = 1u;
    base = timer_base[3];
    REG(base + 0x28u) = 59u;
    REG(base + 0x2Cu) = 999u;
    REG(base + 0x34u) = 250u;
    REG(base + 0x18u) = 6u << 4;
    REG(base + 0x20u) = 1u;
    REG(base + 0x14u) = 1u;
    REG(base + 0x10u) = 0u;
    REG(base) = 1u;
    MAILBOX[23] = 1u;
    while (MAILBOX[24] < 3u) {}
    MAILBOX[0] = PASS;
    uart_text("PWM CAPTURE OK\r\n");
}

static void encoder(void) {
    u32 round;
    u32 base = timer_base[2];
    enable_timer(2u);
    /* PD8 -> PA6 / TIMER2_CH0 and PD9 -> PA7 / TIMER2_CH1. */
    REG(GPIOD) = (REG(GPIOD) & ~(15u << 16)) | (5u << 16);
    REG(GPIOD + 20u) = 0u;
    REG(GPIOA) = (REG(GPIOA) & ~(15u << 12)) | (10u << 12);
    REG(GPIOA + 32u) = (REG(GPIOA + 32u) & ~0xFF000000u) | 0x22000000u;
    REG(base + 0x2Cu) = 0xFFFFu;
    REG(base + 0x18u) = 0x0101u;
    REG(base + 0x20u) = 0x11u;
    REG(base + 8u) = 3u;
    REG(base) = 1u;
    for (round = 0; round < 4u; ++round) {
        REG(GPIOD + 24u) = 1u << 8;
        delay_edges();
        REG(GPIOD + 24u) = 1u << 9;
        delay_edges();
        REG(GPIOD + 24u) = 1u << 24;
        delay_edges();
        REG(GPIOD + 24u) = 1u << 25;
        delay_edges();
    }
    REG(base) = 0u;
    MAILBOX[26] = REG(base + 0x24u);
    MAILBOX[0] = MAILBOX[26] == 16u ? PASS : FAIL;
    uart_text(MAILBOX[0] == PASS ? "ENCODER16 OK\r\n" : "ENCODER FAIL\r\n");
}

static void master_slave(void) {
    u32 count;
    enable_timer(1u);
    enable_timer(2u);
    REG(timer_base[2] + 0x2Cu) = 0xFFFFu;
    REG(timer_base[2] + 8u) = (1u << 4) | 7u;
    REG(timer_base[2]) = 1u;
    REG(timer_base[1] + 0x2Cu) = 99u;
    REG(timer_base[1] + 4u) = 2u << 4;
    REG(timer_base[1]) = 1u;
    for (count = 0; count < 1000u; ++count) __asm volatile("nop");
    REG(timer_base[1]) = 0u;
    REG(timer_base[2]) = 0u;
    MAILBOX[26] = REG(timer_base[2] + 0x24u);
    MAILBOX[0] = MAILBOX[26] ? PASS : FAIL;
    uart_text(MAILBOX[0] == PASS ? "TIMER CHAIN OK\r\n" : "TIMER CHAIN FAIL\r\n");
}

static void nested_priorities(void) {
    u32 index;
    enable_timer(1u);
    enable_timer(2u);
    for (index = 1u; index <= 2u; ++index) {
        REG(timer_base[index] + 0x2Cu) = index == 1u ? 3999u : 99u;
        REG(timer_base[index] + 0x14u) = 1u;
        REG(timer_base[index] + 0x10u) = 0u;
        REG(timer_base[index] + 0x0Cu) = 1u;
        enable_irq(timer_irq[index]);
    }
    REG(0xE000ED0Cu) = 0x05FA0000u; /* Four implemented bits used for preemption. */
    REG(0xE000E41Cu) = 0x00002080u; /* IRQ28 low priority 8, IRQ29 high priority 2. */
    __asm volatile("msr basepri, %0\n isb" : : "r"(0x40u) : "memory");
    REG(timer_base[1]) = 9u;
    for (index = 0; index < 4000u; ++index) __asm volatile("nop");
    MAILBOX[28] = (!MAILBOX[29] && (REG(timer_base[1] + 0x10u) & 1u)) ? 1u : 0u;
    __asm volatile("msr basepri, %0\n isb" : : "r"(0u) : "memory");
    while (!MAILBOX[15]) {}
    MAILBOX[0] = (MAILBOX[28] == 1u && MAILBOX[29] == 0x123u && MAILBOX[30] == 1u) ? PASS : FAIL;
    uart_text(MAILBOX[0] == PASS ? "NESTED TIMER IRQ OK\r\n" : "NESTED TIMER IRQ FAIL\r\n");
}

static void advanced_vectors(void) {
    u32 index;
    u32 timeout = 100000u;
    enable_timer(0u);
    for (index = 24u; index <= 27u; ++index) enable_irq(index);
    REG(timer_base[0] + 0x0Cu) = 0xE3u;
    REG(timer_base[0] + 0x14u) = 0xE3u;
    while ((MAILBOX[1] + MAILBOX[2] + MAILBOX[3] + MAILBOX[4] + MAILBOX[5] < 5u) && --timeout) {}
    MAILBOX[0] = PASS;
    for (index = 1u; index <= 5u; ++index) if (MAILBOX[index] != 1u) MAILBOX[0] = FAIL;
    uart_text(MAILBOX[0] == PASS ? "ADVANCED TIMER IRQ OK\r\n" : "ADVANCED TIMER IRQ FAIL\r\n");
}

void Reset_Handler(void) {
    u32 index;
    u32 mode = MAILBOX[31];
    for (index = 0; index < 31u; ++index) MAILBOX[index] = 0u;
    uart_init();
    if (mode == 1u) pwm_capture();
    else if (mode == 2u) encoder();
    else if (mode == 3u) master_slave();
    else if (mode == 4u) nested_priorities();
    else if (mode == 5u) advanced_vectors();
    else test_all_irqs();
    for (;;) __asm volatile("nop");
}

__attribute__((section(".isr_vector"), used))
const void *const vectors[99] = {
    [0] = (void *)0x20020000u, [1] = (void *)Reset_Handler,
    [16 + 24] = (void *)Timer_Handler, [16 + 25] = (void *)Timer_Handler,
    [16 + 26] = (void *)Timer_Handler, [16 + 27] = (void *)Timer_Handler,
    [16 + 28] = (void *)Timer_Handler, [16 + 29] = (void *)Timer_Handler,
    [16 + 30] = (void *)Timer_Handler, [16 + 43] = (void *)Timer_Handler,
    [16 + 44] = (void *)Timer_Handler, [16 + 45] = (void *)Timer_Handler,
    [16 + 46] = (void *)Timer_Handler, [16 + 50] = (void *)Timer_Handler,
    [16 + 54] = (void *)Timer_Handler, [16 + 55] = (void *)Timer_Handler
};
