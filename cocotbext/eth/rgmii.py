"""

Copyright (c) 2020 Alex Forencich

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

"""

import logging

import cocotb
from cocotb.queue import Queue
from cocotb.triggers import RisingEdge, FallingEdge, Timer, First, Event
from cocotb.utils import get_sim_time, get_sim_steps

from .version import __version__
from .gmii import GmiiFrame
from .constants import EthPre
from .reset import Reset


class RgmiiSource(Reset):

    def __init__(self, data, ctrl, clock, reset=None, enable=None, mii_select=None,
            reset_active_level=True, *args, **kwargs):

        self.log = logging.getLogger(f"cocotb.{data._path}")
        self.data = data
        self.ctrl = ctrl
        self.clock = clock
        self.reset = reset
        self.enable = enable
        self.mii_select = mii_select

        self.log.info("RGMII source")
        self.log.info("cocotbext-eth version %s", __version__)
        self.log.info("Copyright (c) 2020 Alex Forencich")
        self.log.info("https://github.com/alexforencich/cocotbext-eth")

        super().__init__(*args, **kwargs)

        self.active = False
        self.queue = Queue()
        self.current_frame = None
        self.idle_event = Event()
        self.idle_event.set()

        self.ifg = 12
        self.mii_mode = False

        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

        self.width = 8
        self.byte_width = 1

        assert len(self.data) == 4
        self.data.setimmediatevalue(0)
        assert len(self.ctrl) == 1
        self.ctrl.setimmediatevalue(0)

        self._run_cr = None

        self._init_reset(reset, reset_active_level)

    async def send(self, frame):
        frame = GmiiFrame(frame)
        await self.queue.put(frame)
        self.idle_event.clear()
        self.queue_occupancy_bytes += len(frame)
        self.queue_occupancy_frames += 1

    def send_nowait(self, frame):
        frame = GmiiFrame(frame)
        self.queue.put_nowait(frame)
        self.idle_event.clear()
        self.queue_occupancy_bytes += len(frame)
        self.queue_occupancy_frames += 1

    def count(self):
        return self.queue.qsize()

    def empty(self):
        return self.queue.empty()

    def idle(self):
        return self.empty() and not self.active

    def clear(self):
        while not self.queue.empty():
            self.queue.get_nowait()
        self.idle_event.set()
        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

    async def wait(self):
        await self.idle_event.wait()

    def _handle_reset(self, state):
        if state:
            self.log.info("Reset asserted")
            if self._run_cr is not None:
                self._run_cr.kill()
                self._run_cr = None

            self.active = False
            self.data <= 0
            self.ctrl <= 0

            if self.current_frame:
                self.log.warning("Flushed transmit frame during reset: %s", self.current_frame)
                self.current_frame.handle_tx_complete()
                self.current_frame = None

            if self.queue.empty():
                self.idle_event.set()
        else:
            self.log.info("Reset de-asserted")
            if self._run_cr is None:
                self._run_cr = cocotb.scheduler.start_soon(self._run())

    async def _run(self):
        frame = None
        ifg_cnt = 0
        self.active = False
        d = 0
        er = 0
        en = 0

        while True:
            await RisingEdge(self.clock)

            # send high nibble after rising edge, leading in to falling edge
            self.data <= d >> 4
            self.ctrl <= en ^ er

            if self.enable is None or self.enable.value:
                if ifg_cnt > 0:
                    # in IFG
                    ifg_cnt -= 1

                elif frame is None and not self.queue.empty():
                    # send frame
                    frame = self.queue.get_nowait()
                    self.queue_occupancy_bytes -= len(frame)
                    self.queue_occupancy_frames -= 1
                    self.current_frame = frame
                    frame.sim_time_start = get_sim_time()
                    frame.sim_time_sfd = None
                    frame.sim_time_end = None
                    self.log.info("TX frame: %s", frame)
                    frame.normalize()

                    if self.mii_select is not None:
                        self.mii_mode = bool(self.mii_select.value.integer)

                    if self.mii_mode:
                        mii_data = []
                        mii_error = []
                        for b, e in zip(frame.data, frame.error):
                            mii_data.append((b & 0x0F)*0x11)
                            mii_data.append((b >> 4)*0x11)
                            mii_error.append(e)
                            mii_error.append(e)
                        frame.data = mii_data
                        frame.error = mii_error

                    self.active = True

                if frame is not None:
                    d = frame.data.pop(0)
                    er = frame.error.pop(0)
                    en = 1

                    if frame.sim_time_sfd is None and d in (EthPre.SFD, 0xD, 0xDD):
                        frame.sim_time_sfd = get_sim_time()

                    if not frame.data:
                        ifg_cnt = max(self.ifg, 1)
                        frame.sim_time_end = get_sim_time()
                        frame.handle_tx_complete()
                        frame = None
                        self.current_frame = None
                else:
                    d = 0
                    er = 0
                    en = 0
                    self.active = False
                    self.idle_event.set()

            await FallingEdge(self.clock)

            # send low nibble after falling edge, leading in to rising edge
            self.data <= d & 0x0F
            self.ctrl <= en


class RgmiiSink(Reset):

    def __init__(self, data, ctrl, clock, reset=None, enable=None, mii_select=None,
            reset_active_level=True, *args, **kwargs):

        self.log = logging.getLogger(f"cocotb.{data._path}")
        self.data = data
        self.ctrl = ctrl
        self.clock = clock
        self.reset = reset
        self.enable = enable
        self.mii_select = mii_select

        self.log.info("RGMII sink")
        self.log.info("cocotbext-eth version %s", __version__)
        self.log.info("Copyright (c) 2020 Alex Forencich")
        self.log.info("https://github.com/alexforencich/cocotbext-eth")

        super().__init__(*args, **kwargs)

        self.active = False
        self.queue = Queue()
        self.active_event = Event()

        self.mii_mode = False

        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

        self.width = 8
        self.byte_width = 1

        assert len(self.data) == 4
        assert len(self.ctrl) == 1

        self._run_cr = None

        self._init_reset(reset, reset_active_level)

    async def recv(self, compact=True):
        frame = await self.queue.get()
        if self.queue.empty():
            self.active_event.clear()
        self.queue_occupancy_bytes -= len(frame)
        self.queue_occupancy_frames -= 1
        return frame

    def recv_nowait(self, compact=True):
        if not self.queue.empty():
            frame = self.queue.get_nowait()
            if self.queue.empty():
                self.active_event.clear()
            self.queue_occupancy_bytes -= len(frame)
            self.queue_occupancy_frames -= 1
            return frame
        return None

    def count(self):
        return self.queue.qsize()

    def empty(self):
        return self.queue.empty()

    def idle(self):
        return not self.active

    def clear(self):
        while not self.queue.empty():
            self.queue.get_nowait()
        self.active_event.clear()
        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

    async def wait(self, timeout=0, timeout_unit=None):
        if not self.empty():
            return
        if timeout:
            await First(self.active_event.wait(), Timer(timeout, timeout_unit))
        else:
            await self.active_event.wait()

    def _handle_reset(self, state):
        if state:
            self.log.info("Reset asserted")
            if self._run_cr is not None:
                self._run_cr.kill()
                self._run_cr = None

            self.active = False
        else:
            self.log.info("Reset de-asserted")
            if self._run_cr is None:
                self._run_cr = cocotb.scheduler.start_soon(self._run())

    async def _run(self):
        frame = None
        self.active = False
        d_val = 0
        dv_val = 0
        er_val = 0

        while True:
            await RisingEdge(self.clock)

            # capture low nibble on rising edge
            d_val = self.data.value.integer
            dv_val = self.ctrl.value.integer

            await FallingEdge(self.clock)

            # capture high nibble on falling edge
            d_val |= self.data.value.integer << 4
            er_val = dv_val ^ self.ctrl.value.integer

            if self.enable is None or self.enable.value:

                if frame is None:
                    if dv_val:
                        # start of frame
                        frame = GmiiFrame(bytearray(), [])
                        frame.sim_time_start = get_sim_time()
                else:
                    if not dv_val:
                        # end of frame

                        if self.mii_select is not None:
                            self.mii_mode = bool(self.mii_select.value.integer)

                        if self.mii_mode:
                            odd = True
                            sync = False
                            b = 0
                            be = 0
                            data = bytearray()
                            error = []
                            for n, e in zip(frame.data, frame.error):
                                odd = not odd
                                b = (n & 0x0F) << 4 | b >> 4
                                be |= e
                                if not sync and b == EthPre.SFD:
                                    odd = True
                                    sync = True
                                if odd:
                                    data.append(b)
                                    error.append(be)
                                    be = 0
                            frame.data = data
                            frame.error = error

                        frame.compact()
                        frame.sim_time_end = get_sim_time()
                        self.log.info("RX frame: %s", frame)

                        self.queue_occupancy_bytes += len(frame)
                        self.queue_occupancy_frames += 1

                        self.queue.put_nowait(frame)
                        self.active_event.set()

                        frame = None

                if frame is not None:
                    if frame.sim_time_sfd is None and d_val in (EthPre.SFD, 0xD, 0xDD):
                        frame.sim_time_sfd = get_sim_time()

                    frame.data.append(d_val)
                    frame.error.append(er_val)


class RgmiiPhy:
    def __init__(self, txd, tx_ctl, tx_clk, rxd, rx_ctl, rx_clk, reset=None,
            reset_active_level=True, speed=1000e6, *args, **kwargs):

        self.tx_clk = tx_clk
        self.rx_clk = rx_clk

        super().__init__(*args, **kwargs)

        self.tx = RgmiiSink(txd, tx_ctl, tx_clk, reset, reset_active_level=reset_active_level)
        self.rx = RgmiiSource(rxd, rx_ctl, rx_clk, reset, reset_active_level=reset_active_level)

        self.rx_clk.setimmediatevalue(0)

        self._clock_cr = None
        self.set_speed(speed)

    def set_speed(self, speed):
        if speed in (10e6, 100e6, 1000e6):
            self.speed = speed
        else:
            raise ValueError("Invalid speed selection")

        if self._clock_cr is not None:
            self._clock_cr.kill()

        if self.speed == 1000e6:
            self._clock_cr = cocotb.scheduler.start_soon(self._run_clock(8*1e9/self.speed))
            self.tx.mii_mode = False
            self.rx.mii_mode = False
        else:
            self._clock_cr = cocotb.scheduler.start_soon(self._run_clock(4*1e9/self.speed))
            self.tx.mii_mode = True
            self.rx.mii_mode = True

    async def _run_clock(self, period):
        half_period = get_sim_steps(period / 2.0, 'ns')
        t = Timer(half_period)

        while True:
            await t
            self.rx_clk <= 1
            await t
            self.rx_clk <= 0
