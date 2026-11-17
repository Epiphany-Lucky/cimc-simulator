"""NVIC grouping and SysTick clock regressions for simultaneous timer sources."""
from pathlib import Path
import struct
import sys
import unittest
from unicorn.arm_const import UC_ARM_REG_BASEPRI, UC_ARM_REG_FAULTMASK

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from simulator import Simulator, SRAM


class InterruptPriorityTests(unittest.TestCase):
    def setUp(self):
        self.sim=Simulator(ROOT)
        self.sim.close()
        self.sim.load((ROOT/'firmware/timer_probe.hex').read_bytes(),'timer_probe.hex')

    def tearDown(self):self.sim.close()

    def configure(self,priority=0x40):
        s=self.sim
        s._write(0xE000ED0C,0x05FA0500)  # Two group bits, two subpriority bits.
        s._write(0xE000E41C,priority)
        s._write(0xE000E100,1<<28)
        s._write(0xE000E200,1<<28)

    def test_basepri_masks_entire_group_including_higher_subpriority(self):
        self.configure()
        self.sim.uc.reg_write(UC_ARM_REG_BASEPRI,0x50)
        self.assertEqual(self.sim._eligible_exception(),0)
        self.sim.uc.reg_write(UC_ARM_REG_BASEPRI,0)
        self.assertEqual(self.sim._eligible_exception(),44)

    def test_basepri_allows_strictly_higher_group(self):
        self.configure(0x30)
        self.sim.uc.reg_write(UC_ARM_REG_BASEPRI,0x50)
        self.assertEqual(self.sim._eligible_exception(),44)

    def test_subpriority_orders_pending_without_preempting_same_group(self):
        self.configure(0x50)
        s=self.sim
        s._write(0xE000E41C,0x4050)
        s._write(0xE000E100,1<<29)
        s._write(0xE000E200,1<<29)
        self.assertEqual(s._eligible_exception(),45)
        s.active_exception=44
        s.in_exception=True
        self.assertEqual(s._eligible_exception(),0)

    def test_faultmask_clears_on_normal_exception_return(self):
        s=self.sim
        s._enter_exception(44)
        s.uc.reg_write(UC_ARM_REG_FAULTMASK,1)
        s._return_exception()
        self.assertEqual(s.uc.reg_read(UC_ARM_REG_FAULTMASK),0)
        self.assertFalse(s.in_exception)

    def test_aircr_requires_write_key_and_reports_read_key(self):
        s=self.sim
        s._write(0xE000ED0C,0x0500)
        self.assertEqual(s._read(0xE000ED0C),0xFA050000)
        s._write(0xE000ED0C,0x05FA0500)
        self.assertEqual(s._read(0xE000ED0C),0xFA050500)

    def test_systick_external_clock_is_hclk_divided_by_eight(self):
        s=self.sim
        s.board['clockTicksPerInstruction']=1  # The 180-instruction budget spans 180 HCLK ticks.
        s.load((ROOT/'firmware/systick.hex').read_bytes(),'systick.hex')
        for _ in range(100):
            s.run_chunk(1)
            if s.systick['ctrl']==7:break
        else:self.fail('Real SysTick fixture did not configure its timer')
        s._write(0xE000E010,0)
        s._write(0xE000ED04,1<<25)
        s._write(0xE000E014,9)
        s._write(0xE000E018,0)
        s._write(0xE000E010,3)
        before=struct.unpack('<I',s.uc.mem_read(SRAM,4))[0]
        s.run_chunk(180)
        after=struct.unpack('<I',s.uc.mem_read(SRAM,4))[0]
        self.assertEqual(after-before,2)
        self.assertNotEqual(s.status,'faulted',s.diagnostics)


if __name__=='__main__':unittest.main()
