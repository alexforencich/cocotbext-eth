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
from cocotb.queue import Queue, QueueFull
from cocotb.triggers import RisingEdge, Timer, First, Event
from cocotb.utils import get_sim_time, get_sim_steps

from .version import __version__
from .gmii import GmiiFrame
from .constants import EthPre
from .reset import Reset


class MiiSource(Reset):

    def __init__(self, data, er, dv, clock, reset=None, enable=None, reset_active_level=True, *args, **kwargs):
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
        self.queue = Queue()
        self.dequeue_event = Event()
        self.current_frame = None
        self.idle_event = Event()
        self.idle_event.set()
        self.active_event = Event()

        self.ifg = 12

        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

        self.queue_occupancy_limit_bytes = -1
        self.queue_occupancy_limit_frames = -1

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

        self._init_reset(reset, reset_active_level)

    async def send(self, frame):
        while self.full():
            self.dequeue_event.clear()
            await self.dequeue_event.wait()
        frame = GmiiFrame(frame)
        await self.queue.put(frame)
        self.idle_event.clear()
        self.active_event.set()
        self.queue_occupancy_bytes += len(frame)
        self.queue_occupancy_frames += 1

    def send_nowait(self, frame):
        if self.full():
            raise QueueFull()
        frame = GmiiFrame(frame)
        self.queue.put_nowait(frame)
        self.idle_event.clear()
        self.active_event.set()
        self.queue_occupancy_bytes += len(frame)
        self.queue_occupancy_frames += 1

    def count(self):
        return self.queue.qsize()

    def empty(self):
        return self.queue.empty()

    def full(self):
        if self.queue_occupancy_limit_bytes > 0 and self.queue_occupancy_bytes > self.queue_occupancy_limit_bytes:
            return True
        elif self.queue_occupancy_limit_frames > 0 and self.queue_occupancy_frames > self.queue_occupancy_limit_frames:
            return True
        else:
            return False

    def idle(self):
        return self.empty() and not self.active

    def clear(self):
        while not self.queue.empty():
            frame = self.queue.get_nowait()
            frame.sim_time_end = None
            frame.handle_tx_complete()
        self.dequeue_event.set()
        self.idle_event.set()
        self.active_event.clear()
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
            self.data.value = 0
            if self.er is not None:
                self.er.value = 0
            self.dv.value = 0

            if self.current_frame:
                self.log.warning("Flushed transmit frame during reset: %s", self.current_frame)
                self.current_frame.handle_tx_complete()
                self.current_frame = None

            if self.queue.empty():
                self.idle_event.set()
                self.active_event.clear()
        else:
            self.log.info("Reset de-asserted")
            if self._run_cr is None:
                self._run_cr = cocotb.start_soon(self._run())

    async def _run(self):
        frame = None
        frame_offset = 0
        frame_data = None
        frame_error = None
        ifg_cnt = 0
        self.active = False

        clock_edge_event = RisingEdge(self.clock)

        enable_event = None
        if self.enable is not None:
            enable_event = RisingEdge(self.enable)

        while True:
            await clock_edge_event

            if self.enable is None or self.enable.value:
                if ifg_cnt > 0:
                    # in IFG
                    ifg_cnt -= 1

                elif frame is None and not self.queue.empty():
                    # send frame
                    frame = self.queue.get_nowait()
                    self.dequeue_event.set()
                    self.queue_occupancy_bytes -= len(frame)
                    self.queue_occupancy_frames -= 1
                    self.current_frame = frame
                    frame.sim_time_start = get_sim_time()
                    frame.sim_time_sfd = None
                    frame.sim_time_end = None
                    self.log.info("TX frame: %s", frame)
                    frame.normalize()

                    # convert to MII
                    frame_data = []
                    frame_error = []
                    for b, e in zip(frame.data, frame.error):
                        frame_data.append(b & 0x0F)
                        frame_data.append(b >> 4)
                        frame_error.append(e)
                        frame_error.append(e)

                    self.active = True
                    frame_offset = 0

                if frame is not None:
                    d = frame_data[frame_offset]
                    if frame.sim_time_sfd is None and d == 0xD:
                        frame.sim_time_sfd = get_sim_time()
                    self.data.value = d
                    if self.er is not None:
                        self.er.value = frame_error[frame_offset]
                    self.dv.value = 1
                    frame_offset += 1

                    if frame_offset >= len(frame_data):
                        ifg_cnt = max(self.ifg, 1)
                        frame.sim_time_end = get_sim_time()
                        frame.handle_tx_complete()
                        frame = None
                        self.current_frame = None
                else:
                    self.data.value = 0
                    if self.er is not None:
                        self.er.value = 0
                    self.dv.value = 0
                    self.active = False

                    if ifg_cnt == 0 and self.queue.empty():
                        self.idle_event.set()
                        self.active_event.clear()
                        await self.active_event.wait()

            elif self.enable is not None and not self.enable.value:
                await enable_event


class MiiSink(Reset):

    def __init__(self, data, er, dv, clock, reset=None, enable=None, reset_active_level=True, *args, **kwargs):
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
        self.queue = Queue()
        self.active_event = Event()

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

        self._init_reset(reset, reset_active_level)

    def _recv(self, frame, compact=True):
        if self.queue.empty():
            self.active_event.clear()
        self.queue_occupancy_bytes -= len(frame)
        self.queue_occupancy_frames -= 1
        if compact:
            frame.compact()
        return frame

    async def recv(self, compact=True):
        frame = await self.queue.get()
        return self._recv(frame, compact)

    def recv_nowait(self, compact=True):
        frame = self.queue.get_nowait()
        return self._recv(frame, compact)

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
                self._run_cr = cocotb.start_soon(self._run())

    async def _run(self):
        frame = None
        self.active = False

        clock_edge_event = RisingEdge(self.clock)

        active_event = RisingEdge(self.dv)

        enable_event = None
        if self.enable is not None:
            enable_event = RisingEdge(self.enable)

        while True:
            await clock_edge_event

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

                        self.queue.put_nowait(frame)
                        self.active_event.set()

                        frame = None

                if frame is not None:
                    if frame.sim_time_sfd is None and d_val == 0xD:
                        frame.sim_time_sfd = get_sim_time()

                    frame.data.append(d_val)
                    frame.error.append(er_val)

                if not dv_val:
                    await active_event

            elif self.enable is not None and not self.enable.value:
                await enable_event


class MiiPhy:
    def __init__(self, txd, tx_er, tx_en, tx_clk, rxd, rx_er, rx_dv, rx_clk, reset=None,
            reset_active_level=True, speed=100e6, *args, **kwargs):

        self.tx_clk = tx_clk
        self.rx_clk = rx_clk

        super().__init__(*args, **kwargs)

        self.tx = MiiSink(txd, tx_er, tx_en, tx_clk, reset, reset_active_level=reset_active_level)
        self.rx = MiiSource(rxd, rx_er, rx_dv, rx_clk, reset, reset_active_level=reset_active_level)

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

        self._clock_cr = cocotb.start_soon(self._run_clocks(4*1e9/self.speed))

    async def _run_clocks(self, period):
        half_period = get_sim_steps(period / 2.0, 'ns')
        t = Timer(half_period)

        while True:
            await t
            self.tx_clk.value = 1
            self.rx_clk.value = 1
            await t
            self.tx_clk.value = 0
            self.rx_clk.value = 0
