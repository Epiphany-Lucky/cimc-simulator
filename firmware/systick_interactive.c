/* Same real interrupt probe, calibrated for the 240 HCLK/instruction profile.
 * LOAD=239999 gives one event per 1000 emulated instructions. At the reset
 * HCLK of 16 MHz its hardware period is 15 ms. This is a throughput fixture.
 */
#define SYSTICK_RELOAD 239999u
#include "systick.c"
