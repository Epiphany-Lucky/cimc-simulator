/* CIMC Lab V0.2 verification firmware. No host-side display/serial shortcuts.
 * Built with Keil Arm Compiler 6 (when licensed) or GNU Arm Embedded.
 * External jumpers: PD10..PD15 -> LED1..LED6; PE7..PE12 -> KEY1..KEY6.
 * V1.0: OLED PB8/PB9. H7 1-3/2-4 connects CH340; H6 1-3/2-4 selects RS485.
 */
typedef unsigned int u32;
typedef unsigned char u8;
#define REG(a) (*(volatile u32 *)(a))
#define GPIOB 0x40020400u
#define GPIOA 0x40020000u
#define GPIOD 0x40020C00u
#define GPIOE 0x40021000u
#define UART0 0x40011000u
#define UART1 0x40004400u
#define UART2 0x40004800u
#define GPIOC 0x40020800u
#define ADC0 0x40012000u
#define SPI1 0x40003800u

static void adc_init(void){
 REG(0x40023830u)|=1u<<2;REG(0x40023844u)|=1u<<8;
 REG(GPIOC)=(REG(GPIOC)&~3u)|3u;
 REG(0x40012304u)=1u<<16;
 REG(ADC0+0x2C)=0;REG(ADC0+0x34)=10;REG(ADC0+8)=1;
 REG(ADC0+8)|=1u<<3;while(REG(ADC0+8)&(1u<<3)){}
 REG(ADC0+8)|=1u<<2;while(REG(ADC0+8)&(1u<<2)){}
}
static u32 adc_read(void){REG(ADC0+8)|=1u<<30;while(!(REG(ADC0)&2)){}return REG(ADC0+0x4C);}
static void adc_text(char *s,u32 v){s[4]='0'+v/1000;s[5]='0'+(v/100)%10;s[6]='0'+(v/10)%10;s[7]='0'+v%10;}

static void pin(u32 base,u32 p,u32 high){REG(base+24)=high?(1u<<p):(1u<<(p+16));}
static u8 spi_byte(u8 b){while(!(REG(SPI1+8)&2)){}REG(SPI1+12)=b;while(!(REG(SPI1+8)&1)){}return (u8)REG(SPI1+12);}
static u32 flash_id(void){u32 id=0,i;pin(GPIOB,12,0);spi_byte(0x9F);for(i=0;i<3;i++)id=(id<<8)|spi_byte(0xFF);pin(GPIOB,12,1);return id;}
static void flash_init(void){
 REG(0x40023840u)|=1u<<14;pin(GPIOB,12,1);
 REG(GPIOB)=(REG(GPIOB)&0x00FFFFFFu)|(1u<<24)|(2u<<26)|(2u<<28)|(2u<<30);
 REG(GPIOB+36)=(REG(GPIOB+36)&0x000FFFFFu)|0x55500000u;
 REG(SPI1)=0x354u;
}
static void delay(void){volatile u32 i;for(i=0;i<2;i++)__asm volatile("nop");}
static void scl(u32 v){pin(GPIOB,8,v);delay();}
static void sda(u32 v){pin(GPIOB,9,v);delay();}
static void start(void){sda(1);scl(1);sda(0);scl(0);}
static void stop(void){scl(0);sda(0);scl(1);sda(1);}
static void byte(u8 b){u32 i;for(i=0;i<8;i++){sda((b&128)!=0);scl(1);scl(0);b<<=1;}sda(1);scl(1);scl(0);}
static void cmd(u8 c){start();byte(0x78);byte(0);byte(c);stop();}
static void uart_put(u32 b,u8 c){if(b==UART1)pin(GPIOA,1,1);while(!(REG(b)&128)){}REG(b+4)=c;while(!(REG(b)&64)){}if(b==UART1)pin(GPIOA,1,0);}
static void puts_uart(u32 b,const char *s){while(*s)uart_put(b,(u8)*s++);}

static const u8 font[][5]={
 {0,0,0,0,0}, /* space */
 {0x3E,0x51,0x49,0x45,0x3E}, /* 0 */
 {0,0x42,0x7F,0x40,0}, {0x42,0x61,0x51,0x49,0x46},
 {0x21,0x41,0x45,0x4B,0x31}, {0x18,0x14,0x12,0x7F,0x10},
 {0x27,0x45,0x45,0x45,0x39}, {0x3C,0x4A,0x49,0x49,0x30},
 {1,0x71,9,5,3}, {0x36,0x49,0x49,0x49,0x36}, {6,0x49,0x49,0x29,0x1E},
 {0x7E,0x11,0x11,0x11,0x7E}, /* A */
 {0x7F,0x49,0x49,0x49,0x36}, {0x3E,0x41,0x41,0x41,0x22},
 {0x7F,0x41,0x41,0x22,0x1C}, {0x7F,0x49,0x49,0x49,0x41},
 {0x7F,9,9,9,1}, {0x3E,0x41,0x49,0x49,0x7A},
 {0x7F,8,8,8,0x7F}, {0,0x41,0x7F,0x41,0},
 {0x20,0x40,0x41,0x3F,1}, {0x7F,8,0x14,0x22,0x41},
 {0x7F,0x40,0x40,0x40,0x40}, {0x7F,2,0x0C,2,0x7F},
 {0x7F,4,8,0x10,0x7F}, {0x3E,0x41,0x41,0x41,0x3E},
 {0x7F,9,9,9,6}, {0x3E,0x41,0x51,0x21,0x5E},
 {0x7F,9,0x19,0x29,0x46}, {0x46,0x49,0x49,0x49,0x31},
 {1,1,0x7F,1,1}, {0x3F,0x40,0x40,0x40,0x3F},
 {0x1F,0x20,0x40,0x20,0x1F}, {0x3F,0x40,0x38,0x40,0x3F},
 {0x63,0x14,8,0x14,0x63}, {7,8,0x70,8,7}, {0x61,0x51,0x49,0x45,0x43}
};
static void line(u8 page,const char *s){
 u32 x=0,i;cmd(0xB0+page);cmd(0);cmd(0x10);start();byte(0x78);byte(0x40);
 while(*s&&x+6<=128){u8 c=(u8)*s++;u32 index=0;
  if(c>='0'&&c<='9')index=1+c-'0';else if(c>='A'&&c<='Z')index=11+c-'A';
  for(i=0;i<5;i++){byte(font[index][i]);x++;}byte(0);x++;
 }while(x++<128)byte(0);stop();
}
static void oled_init(void){
 static const u8 commands[]={0xAE,0xD5,0x80,0xA8,0x1F,0xD3,0,0x40,0x8D,0x14,0x20,2,0xA1,0xC8,0xDA,2,0x81,0x8F,0xD9,0xF1,0xDB,0x40,0xA4,0xA6,0xAF};
 u32 i;for(i=0;i<sizeof(commands);i++)cmd(commands[i]);
 line(0,"CIMC LAB");line(1,"FIRMWARE LIVE");line(2,"PRESS KEY 1 TO 6");line(3,"SERIAL L TO TOGGLE");
}

void Reset_Handler(void){
 u32 i,previous=0,mask=1,count=0,previous_adc=0xFFFFFFFFu;
 const u32 ports[]={UART0,UART1,UART2};
 REG(0x40023830)|=(1<<0)|(1<<1)|(1<<3)|(1<<4);
 REG(0x40023840)|=(1<<17)|(1<<18);
 REG(0x40023844)|=(1<<4);
 REG(GPIOB)=(1u<<16)|(1u<<18)|(2u<<20)|(2u<<22);REG(GPIOB+4)=(1<<8)|(1<<9);
 REG(GPIOB+36)=(7u<<8)|(7u<<12);
 REG(GPIOB+12)=(1u<<16)|(1u<<18);REG(GPIOB+20)=(1<<8)|(1<<9);
 REG(GPIOD)=0x55500000;REG(GPIOD+20)=1<<10;
 REG(GPIOE)=0;REG(GPIOE+12)=0x15554000;
 REG(GPIOA)=(1u<<2)|(2u<<4)|(2u<<6)|(2u<<18)|(2u<<20);REG(GPIOA+20)=0;
 REG(GPIOA+32)=(7u<<8)|(7u<<12);REG(GPIOA+36)=(7u<<4)|(7u<<8);
 adc_init();
 for(i=0;i<3;i++){REG(ports[i]+8)=1250;REG(ports[i]+12)=(1<<13)|(1<<3)|(1<<2);}
 puts_uart(UART0,"CIMC LAB ARM firmware ready\r\n");
 puts_uart(UART1,"RS485 firmware ready\r\n");
 puts_uart(UART2,"TTL USART2 firmware ready\r\n");
 flash_init();
 {u32 id=flash_id();char message[]="FLASH JEDEC 000000\r\n";const char hex[]="0123456789ABCDEF";
  for(i=0;i<6;i++)message[12+i]=hex[(id>>(20-i*4))&15];puts_uart(UART0,message);}
 oled_init();
 puts_uart(UART0,"OLED READY\r\n");
 for(;;){
  u32 analog_value=adc_read();
  if(analog_value!=previous_adc){char analog_line[]="ADC 0000 PC0";adc_text(analog_line,analog_value);line(1,analog_line);previous_adc=analog_value;}
  u32 keys=(~REG(GPIOE+16)>>7)&63;
  if(keys!=previous){
   if(keys){char message[]="KEY COUNT 000";count++;
    message[10]=(char)('0'+(count/100)%10);message[11]=(char)('0'+(count/10)%10);message[12]=(char)('0'+count%10);
    mask=keys;line(2,message);puts_uart(UART0,"KEY pressed\r\n");
   }previous=keys;
  }
  for(i=0;i<3;i++)if(REG(ports[i])&32){u8 c=(u8)REG(ports[i]+4);
   puts_uart(ports[i],"ACK ");uart_put(ports[i],c);puts_uart(ports[i],"\r\n");
   if(c=='A'||c=='a'){char analog_reply[]="ADC 0000 PC0\r\n";adc_text(analog_reply,analog_value);puts_uart(ports[i],analog_reply);}
   else if(c=='L'||c=='l'){mask^=63;line(3,"LED TOGGLED BY UART");}
   else if(c=='C'||c=='c'){count=0;line(2,"COUNTER CLEARED");}
   else line(3,"UART COMMAND RECEIVED");
  }
  REG(GPIOD+20)=mask<<10;
 }
}

__attribute__((section(".isr_vector"),used))
const void * const vectors[]={ (void*)0x20010000, (void*)Reset_Handler };
