/* GD25Q40E V1 SPI1 acceptance fixture. Actual polling MMIO, no host shortcuts.
 * SRAM 0x20000000: completion magic, JEDEC, readback, busy SR, erased byte.
 * A successful run retains "CIMC FLASH" at address zero for the UI preview.
 */
typedef unsigned int u32;
typedef unsigned char u8;
#define REG(a) (*(volatile u32 *)(a))
#ifdef BOARD_V2
#define SPI 0x40013000u
#define GPIO_CS 0x40020000u
#define CS_PIN 15u
#define COMPLETED 0x53504930u
#else
#define SPI 0x40003800u
#define GPIO_CS 0x40020400u
#define CS_PIN 12u
#define COMPLETED 0x53504931u
#endif
#define GPIOB 0x40020400u
#define RESULT ((volatile u32 *)0x20000000u)
static void cs(u32 high){REG(GPIO_CS+24)=1u<<(high?CS_PIN:CS_PIN+16u);}
static u8 transfer(u8 v){
 while(!(REG(SPI+8)&2u)){}
 REG(SPI+12)=v;
 while(!(REG(SPI+8)&1u)){}
 return (u8)REG(SPI+12);
}
static void command(u8 c){cs(0);transfer(c);cs(1);}
static void address(u32 a){transfer((u8)(a>>16));transfer((u8)(a>>8));transfer((u8)a);}
static u8 status(void){u8 value;cs(0);transfer(5);value=transfer(0xFF);cs(1);return value;}
static void ready(void){while(status()&1u){}}
static void erase(u32 a){command(6);cs(0);transfer(0x20);address(a);cs(1);ready();}
static u8 read_byte(u32 a){u8 b;cs(0);transfer(3);address(a);b=transfer(0xFF);cs(1);return b;}
void Reset_Handler(void){
 u32 i,id=0,value=0;
 static const u8 content[]="CIMC FLASH";
 RESULT[0]=RESULT[1]=RESULT[2]=RESULT[3]=RESULT[4]=0;
#ifdef BOARD_V2
 REG(0x40023830u)|=3u;
 REG(0x40023844u)|=1u<<12;
 cs(1);
 REG(GPIO_CS)=1u<<30;
 REG(GPIOB)=(2u<<6)|(2u<<8)|(2u<<10);
 REG(GPIOB+32)=0x00555000u;
#else
 REG(0x40023830u)|=2u;
 REG(0x40023840u)|=1u<<14;
 cs(1);
 REG(GPIOB)=(1u<<24)|(2u<<26)|(2u<<28)|(2u<<30);
 REG(GPIOB+36)=0x55500000u;
#endif
 REG(SPI)=(1u<<2)|(2u<<3)|(1u<<6)|(1u<<8)|(1u<<9);
 cs(0);transfer(0x9F);for(i=0;i<3;i++)id=(id<<8)|transfer(0xFF);cs(1);
 RESULT[1]=id;
 erase(0);
 command(6);cs(0);transfer(2);address(0);
 for(i=0;i<sizeof(content)-1;i++)transfer(content[i]);cs(1);
 RESULT[3]=status();ready();
 for(i=0;i<4;i++)value|=(u32)read_byte(i)<<(8*i);
 RESULT[2]=value;
 /* Check a separate sector erase without erasing the visible preview. */
 command(6);cs(0);transfer(2);address(4096);transfer(0);cs(1);ready();
 erase(4096);RESULT[4]=read_byte(4096);
 RESULT[0]=(id==0xC84013u && value==0x434D4943u && RESULT[4]==255u)?COMPLETED:0xBAD00001u;
 for(;;)__asm volatile("nop");
}
__attribute__((section(".isr_vector"),used))
const void * const vectors[]={(void*)0x20010000,(void*)Reset_Handler};
