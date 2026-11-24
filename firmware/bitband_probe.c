/* Freestanding Cortex-M4 peripheral bit-band acceptance fixture.
 * SRAM 0x20000000 holds results. Word 15 selects a fault case before reset.
 * The normal case performs real LDR/STR accesses to peripheral alias words.
 * Build with firmware/build.ps1 -Target bitband_probe using Keil Arm Compiler 6.
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
#define REG(address) (*(volatile u32 *)(address))
#define BIT(address, bit) REG(0x42000000u + (((address) - 0x40000000u) * 32u) + ((bit) * 4u))
#define RESULT ((volatile u32 *)0x20000000u)
#define RCC_CR 0x40023800u
#define RCC_PLLCFGR 0x40023804u
#define GPIOD 0x40020C00u
#define UNKNOWN_ALIAS 0x424C1A00u /* Reserved address 0x400260D0 beyond DMA0 registers. */

void Reset_Handler(void) {
    u32 index;
    u32 mode = RESULT[15];
    for (index = 0; index < 12; ++index) RESULT[index] = 0;

    if (mode == 1u) {
        RESULT[1] = REG(UNKNOWN_ALIAS);
    } else if (mode == 2u) {
        REG(UNKNOWN_ALIAS) = 1u;
    } else if (mode == 3u) {
        RESULT[1] = REG(0x42470062u); /* Deliberately unaligned word. */
    } else if (mode == 4u) {
        REG(0x42470062u) = 1u;
    } else if (mode == 5u) {
        RESULT[1] = *(volatile u8 *)0x42470060u;
    } else if (mode == 6u) {
        *(volatile u16 *)0x42470060u = 1u;
    } else {
        REG(RCC_CR) = (1u << 16) | 1u;
        BIT(RCC_CR, 24) = 0xFFFFFFFEu;
        RESULT[1] = BIT(RCC_CR, 24);
        BIT(RCC_CR, 24) = 0xFFFFFFFFu;
        RESULT[2] = BIT(RCC_CR, 24);
        RESULT[3] = REG(RCC_CR);

        REG(0x40023830u) |= 1u << 3; /* GPIOD clock. */
        REG(GPIOD) = 0x55555555u;
        REG(GPIOD + 20u) = 0xA5A5u;
        REG(GPIOD + 24u) = (1u << 6) | (1u << 21);
        RESULT[4] = REG(GPIOD + 20u);
        BIT(GPIOD + 20u, 9) = 0xFFFFFFFFu;
        RESULT[5] = REG(GPIOD + 20u);
        BIT(GPIOD + 20u, 8) = 0xFFFFFFFEu;
        RESULT[6] = REG(GPIOD + 20u);
        RESULT[7] = BIT(GPIOD + 20u, 9);
        RESULT[8] = BIT(GPIOD + 20u, 8);

        REG(RCC_PLLCFGR) = 0x0055A5A5u;
        BIT(RCC_PLLCFGR, 31) = 1u;
        RESULT[9] = REG(RCC_PLLCFGR);
        BIT(RCC_PLLCFGR, 31) = 2u;
        RESULT[10] = REG(RCC_PLLCFGR);
    }

    RESULT[0] = 0x42424F4Bu; /* "BBOK" after all actual accesses complete. */
    for (;;) __asm volatile("nop");
}

__attribute__((section(".isr_vector"), used))
const void * const vectors[] = {(void *)0x20010000u, (void *)Reset_Handler};
