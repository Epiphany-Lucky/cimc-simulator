/* V1 VR1/PC0 -> ADC0 channel10 -> SRAM acceptance fixture, Keil ARM machine code. */
typedef unsigned int u32;
#define REG(a) (*(volatile u32 *)(a))
void Reset_Handler(void){
 REG(0x40023830u)|=1u<<2;
 REG(0x40023844u)|=1u<<8;
 REG(0x40020800u)=(REG(0x40020800u)&~3u)|3u;
 REG(0x40012304u)=1u<<16;
 REG(0x4001202Cu)=0;
 REG(0x40012034u)=10;
 REG(0x40012008u)=1;
 REG(0x40012008u)|=1u<<3;
 while(REG(0x40012008u)&(1u<<3)){}
 REG(0x40012008u)|=1u<<2;
 while(REG(0x40012008u)&(1u<<2)){}
 REG(0x20000004u)=0;
 for(;;){
  REG(0x40012008u)|=1u<<30;
  while(!(REG(0x40012000u)&2)){}
  REG(0x20000000u)=REG(0x4001204Cu);
  REG(0x20000004u)++;
 }
}
__attribute__((section(".isr_vector"),used))
const void * const vectors[]={ (void*)0x20010000, (void*)Reset_Handler };
