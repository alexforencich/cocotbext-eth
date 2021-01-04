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
from collections import deque

import cocotb
from cocotb.triggers import RisingEdge, Timer, First, Event
from cocotb.utils import get_sim_time, get_sim_steps

from .version import __version__
from .gmii import GmiiFrame
from .constants import EthPre
from .reset import Reset


class MiiSource(Reset):

    def __init__(self, data, er, dv, clock, reset=None, enable=None, *args, **kwargs):
        self.log = logging.getLogger(f"cocotb.{data._path}")
        self.data = data
        self.er = er
        self.dv = dv
        self.clock = clock
        self.reset = reset
        self.enable = enable

        self.log.info("MII source")
        self.log.info("cocotbext-eth version %s", __version__)
        self.log.info("Copyright (c) 2020 Alex Forencich")
        self.log.info("https://github.com/alexforencich/cocotbext-eth")

        super().__init__(*args, **kwargs)

        self.active = False
        self.queue = deque()

        self.ifg = 12

        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

        self.width = 4
        self.byte_width = 1

        assert len(self.data) == 4
        self.data.setimmediatevalue(0)
        if self.er is not None:
            assert len(self.er) == 1
            self.er.setimmediatevalue(0)
        assert len(self.dv) == 1
        self.dv.setimmediatevalue(0)

        self._run_cr = None

        self._init_reset(reset)

    async def send(self, frame):
        self.send_nowait(frame)

    def send_nowait(self, frame):
        frame = GmiiFrame(frame)
        self.queue_occupancy_bytes += len(frame)
        self.queue_occupancy_frames += 1
        self.queue.append(frame)

    def count(self):
        return len(self.queue)

    def empty(self):
        return not self.queue

    def idle(self):
        return self.empty() and not self.active

    def clear(self):
        self.queue.clear()
        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

    async def wait(self):
        while not self.idle():
            await RisingEdge(self.clock)

    def _handle_reset(self, state):
        if state:
            self.log.info("Reset asserted")
            if self._run_cr is not None:
                self._run_cr.kill()
                self._run_cr = None
        else:
            self.log.info("Reset de-asserted")
            if self._run_cr is None:
                self._run_cr = cocotb.fork(self._run())

        self.active = False
        self.data <= 0
        if self.er is not None:
            self.er <= 0
        self.dv <= 0

    async def _run(self):
        frame = None
        ifg_cnt = 0
        self.active = False

        while True:
            await RisingEdge(self.clock)

            if self.enable is None or self.enable.value:
                if ifg_cnt > 0:
                    # in IFG
                    ifg_cnt -= 1

                elif frame is None and self.queue:
                    # send frame
                    frame = self.queue.popleft()
                    self.queue_occupancy_bytes -= len(frame)
                    self.queue_occupancy_frames -= 1
                    frame.sim_time_start = get_sim_time()
                    self.log.info("TX frame: %s", frame)
                    frame.normalize()

                    mii_data = []
                    mii_error = []
                    for b, e in zip(frame.data, frame.error):
                        mii_data.append(b & 0x0F)
                        mii_data.append(b >> 4)
                        mii_error.append(e)
                        mii_error.append(e)
                    frame.data = mii_data
                    frame.error = mii_error

                    self.active = True

                if frame is not None:
                    d = frame.data.pop(0)
                    if frame.sim_time_sfd is None and d == 0xD:
                        frame.sim_time_sfd = get_sim_time()
                    self.data <= d
                    if self.er is not None:
                        self.er <= frame.error.pop(0)
                    self.dv <= 1

                    if not frame.data:
                        ifg_cnt = max(self.ifg, 1)
                        frame.sim_time_end = get_sim_time()
                        frame.handle_tx_complete()
                        frame = None
                else:
                    self.data <= 0
                    if self.er is not None:
                        self.er <= 0
                    self.dv <= 0
                    self.active = False


class MiiSink(Reset):

    def __init__(self, data, er, dv, clock, reset=None, enable=None, *args, **kwargs):
        self.log = logging.getLogger(f"cocotb.{data._path}")
        self.data = data
        self.er = er
        self.dv = dv
        self.clock = clock
        self.reset = reset
        self.enable = enable

        self.log.info("MII sink")
        self.log.info("cocotbext-eth version %s", __version__)
        self.log.info("Copyright (c) 2020 Alex Forencich")
        self.log.info("https://github.com/alexforencich/cocotbext-eth")

        super().__init__(*args, **kwargs)

        self.active = False
        self.queue = deque()
        self.sync = Event()

        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

        self.width = 4
        self.byte_width = 1

        assert len(self.data) == 4
        if self.er is not None:
            assert len(self.er) == 1
        if self.dv is not None:
            assert len(self.dv) == 1

        self._run_cr = None

        self._init_reset(reset)

    async def recv(self, compact=True):
        while self.empty():
            self.sync.clear()
            await self.sync.wait()
        return self.recv_nowait(compact)

    def recv_nowait(self, compact=True):
        if self.queue:
            frame = self.queue.popleft()
            self.queue_occupancy_bytes -= len(frame)
            self.queue_occupancy_frames -= 1
            return frame
        return None

    def count(self):
        return len(self.queue)

    def empty(self):
        return not self.queue

    def idle(self):
        return not self.active

    def clear(self):
        self.queue.clear()
        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

    async def wait(self, timeout=0, timeout_unit=None):
        if not self.empty():
            return
        self.sync.clear()
        if timeout:
            await First(self.sync.wait(), Timer(timeout, timeout_unit))
        else:
            await self.sync.wait()

    def _handle_reset(self, state):
        if state:
            self.log.info("Reset asserted")
            if self._run_cr is not None:
                self._run_cr.kill()
                self._run_cr = None
        else:
            self.log.info("Reset de-asserted")
            if self._run_cr is None:
                self._run_cr = cocotb.fork(self._run())

        self.active = False

    async def _run(self):
        frame = None
        self.active = False

        while True:
            await RisingEdge(self.clock)

            if self.enable is None or self.enable.value:
                d_val = self.data.value.integer
                dv_val = self.dv.value.integer
                er_val = 0 if self.er is None else self.er.value.integer

                if frame is None:
                    if dv_val:
                        # start of frame
                        frame = GmiiFrame(bytearray(), [])
                        frame.sim_time_start = get_sim_time()
                else:
                    if not dv_val:
                        # end of frame
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

                        self.queue.append(frame)
                        self.sync.set()

                        frame = None

                if frame is not None:
                    if frame.sim_time_sfd is None and d_val == 0xD:
                        frame.sim_time_sfd = get_sim_time()

                    frame.data.append(d_val)
                    frame.error.append(er_val)


class MiiPhy:
    def __init__(self, txd, tx_er, tx_en, tx_clk, rxd, rx_er, rx_dv, rx_clk, reset=None, speed=100e6, *args, **kwargs):
        self.tx_clk = tx_clk
        self.rx_clk = rx_clk

        super().__init__(*args, **kwargs)

        self.tx = MiiSink(txd, tx_er, tx_en, tx_clk, reset)
        self.rx = MiiSource(rxd, rx_er, rx_dv, rx_clk, reset)

        self.tx_clk.setimmediatevalue(0)
        self.rx_clk.setimmediatevalue(0)

        self._clock_cr = None
        self.set_speed(speed)

    def set_speed(self, speed):
        if speed in (10e6, 100e6):
            self.speed = speed
        else:
            raise ValueError("Invalid speed selection")

        if self._clock_cr is not None:
            self._clock_cr.kill()

        self._clock_cr = cocotb.fork(self._run_clocks(4*1e9/self.speed))

    async def _run_clocks(self, period):
        half_period = get_sim_steps(period / 2.0, 'ns')
        t = Timer(half_period)

        while True:
            await t
            self.tx_clk <= 1
            self.rx_clk <= 1
            await t
            self.tx_clk <= 0
            self.rx_clk <= 0
