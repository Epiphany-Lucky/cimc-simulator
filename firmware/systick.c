/* Acceptance fixture: real Cortex-M SysTick exception entry and return. */
typedef unsigned int u32;
#define REG(a) (*(volatile u32 *)(a))
void Tick_Handler(void){REG(0x20000000u)++;}
void Reset_Handler(void){
 REG(0x20000000u)=0;
 REG(0xE000E014u)=999;
 REG(0xE000E018u)=0;
 REG(0xE000E010u)=7;
 for(;;)__asm volatile("nop");
}
__attribute__((section(".isr_vector"),used))
const void * const vectors[]={ (void*)0x20010000, (void*)Reset_Handler,0,0,0,0,0,0,0,0,0,0,0,0,0,(void*)Tick_Handler };
