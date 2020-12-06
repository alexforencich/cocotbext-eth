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
from cocotb.triggers import RisingEdge, FallingEdge, ReadOnly, Timer, First, Event
from cocotb.utils import get_sim_time

from .version import __version__
from .gmii import GmiiFrame
from .constants import EthPre


class RgmiiSource(object):

    def __init__(self, data, ctrl, clock, reset=None, enable=None, mii_select=None, *args, **kwargs):
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
        self.queue = deque()

        self.ifg = 12

        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

        self.width = 8
        self.byte_width = 1

        self.reset = reset

        assert len(self.data) == 4
        self.data.setimmediatevalue(0)
        assert len(self.ctrl) == 1
        self.ctrl.setimmediatevalue(0)

        cocotb.fork(self._run())

    def send(self, frame):
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

    async def wait(self):
        while not self.idle():
            await RisingEdge(self.clock)

    async def _run(self):
        frame = None
        ifg_cnt = 0
        self.active = False
        d = 0
        er = 0
        en = 0

        while True:
            await ReadOnly()

            if self.reset is not None and self.reset.value:
                await RisingEdge(self.clock)
                frame = None
                ifg_cnt = 0
                self.active = False
                self.data <= 0
                self.ctrl <= 0
                continue

            await RisingEdge(self.clock)

            if self.mii_select is None or not self.mii_select.value:
                # send high nibble after rising edge, leading in to falling edge
                self.data <= d >> 4
                self.ctrl <= en ^ er

            if self.enable is None or self.enable.value:
                if ifg_cnt > 0:
                    # in IFG
                    ifg_cnt -= 1

                elif frame is None and self.queue:
                    # send frame
                    frame = self.queue.popleft()
                    self.queue_occupancy_bytes -= len(frame)
                    self.queue_occupancy_frames -= 1
                    self.log.info("TX frame: %s", frame)
                    frame.normalize()

                    if self.mii_select is not None and self.mii_select.value:
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
                    er = frame.error.pop(0)
                    en = 1

                    if not frame.data:
                        ifg_cnt = max(self.ifg, 1)
                        frame = None
                else:
                    d = 0
                    er = 0
                    en = 0
                    self.active = False

            await FallingEdge(self.clock)

            # send low nibble after falling edge, leading in to rising edge
            self.data <= d & 0x0F
            self.ctrl <= en


class RgmiiSink(object):

    def __init__(self, data, ctrl, clock, reset=None, enable=None, mii_select=None, *args, **kwargs):
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
        self.queue = deque()
        self.sync = Event()

        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

        self.width = 8
        self.byte_width = 1

        self.reset = reset

        assert len(self.data) == 4
        assert len(self.ctrl) == 1

        cocotb.fork(self._run())

    def recv(self):
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

    async def wait(self, timeout=0, timeout_unit=None):
        if not self.empty():
            return
        self.sync.clear()
        if timeout:
            await First(self.sync.wait(), Timer(timeout, timeout_unit))
        else:
            await self.sync.wait()

    async def _run(self):
        frame = None
        self.active = False
        d_val = 0
        dv_val = 0
        er_val = 0

        while True:
            await ReadOnly()

            if self.reset is not None and self.reset.value:
                await RisingEdge(self.clock)
                frame = None
                self.active = False
                continue

            # capture high nibble after rising edge, leading in to falling edge
            d_val |= self.data.value.integer << 4
            er_val = dv_val ^ self.ctrl.value.integer

            if self.enable is None or self.enable.value:

                if frame is None:
                    if dv_val:
                        # start of frame
                        frame = GmiiFrame(bytearray(), [])
                        frame.rx_sim_time = get_sim_time()
                else:
                    if not dv_val:
                        # end of frame

                        if self.mii_select is not None and self.mii_select.value:
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
                        self.log.info("RX frame: %s", frame)

                        self.queue_occupancy_bytes += len(frame)
                        self.queue_occupancy_frames += 1

                        self.queue.append(frame)
                        self.sync.set()

                        frame = None

                if frame is not None:
                    frame.data.append(d_val)
                    frame.error.append(er_val)

            await FallingEdge(self.clock)
            await ReadOnly()

            # capture low nibble after falling edge, leading in to rising edge
            d_val = self.data.value.integer
            dv_val = self.ctrl.value.integer

            await RisingEdge(self.clock)
