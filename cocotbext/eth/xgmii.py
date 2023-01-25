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
import struct
import zlib

import cocotb
from cocotb.queue import Queue, QueueFull
from cocotb.triggers import Edge, RisingEdge, Timer, First, Event
from cocotb.utils import get_sim_time

from .version import __version__
from .constants import EthPre, ETH_PREAMBLE, XgmiiCtrl
from .reset import Reset


class XgmiiFrame:
    def __init__(self, data=None, ctrl=None, tx_complete=None):
        self.data = bytearray()
        self.ctrl = None
        self.sim_time_start = None
        self.sim_time_sfd = None
        self.sim_time_end = None
        self.start_lane = None
        self.tx_complete = None

        if type(data) is XgmiiFrame:
            self.data = bytearray(data.data)
            self.ctrl = data.ctrl
            self.sim_time_start = data.sim_time_start
            self.sim_time_sfd = data.sim_time_sfd
            self.sim_time_end = data.sim_time_end
            self.start_lane = data.start_lane
            self.tx_complete = data.tx_complete
        else:
            self.data = bytearray(data)
            self.ctrl = ctrl

        if tx_complete is not None:
            self.tx_complete = tx_complete

    @classmethod
    def from_payload(cls, payload, min_len=60, tx_complete=None):
        payload = bytearray(payload)
        if len(payload) < min_len:
            payload.extend(bytearray(min_len-len(payload)))
        payload.extend(struct.pack('<L', zlib.crc32(payload)))
        return cls.from_raw_payload(payload, tx_complete=tx_complete)

    @classmethod
    def from_raw_payload(cls, payload, tx_complete=None):
        data = bytearray(ETH_PREAMBLE)
        data.extend(payload)
        return cls(data, tx_complete=tx_complete)

    def get_preamble_len(self):
        return self.data.index(EthPre.SFD)+1

    def get_preamble(self):
        return self.data[0:self.get_preamble_len()]

    def get_payload(self, strip_fcs=True):
        if strip_fcs:
            return self.data[self.get_preamble_len():-4]
        else:
            return self.data[self.get_preamble_len():]

    def get_fcs(self):
        return self.data[-4:]

    def check_fcs(self):
        return self.get_fcs() == struct.pack('<L', zlib.crc32(self.get_payload(strip_fcs=True)))

    def normalize(self):
        n = len(self.data)

        if self.ctrl is not None:
            self.ctrl = self.ctrl[:n] + [self.ctrl[-1]]*(n-len(self.ctrl))
        else:
            self.ctrl = [0]*n

    def compact(self):
        if self.ctrl is not None and not any(self.ctrl):
            self.ctrl = None

    def handle_tx_complete(self):
        if isinstance(self.tx_complete, Event):
            self.tx_complete.set(self)
        elif callable(self.tx_complete):
            self.tx_complete(self)

    def __eq__(self, other):
        if type(other) is XgmiiFrame:
            return self.data == other.data

    def __repr__(self):
        return (
            f"{type(self).__name__}(data={self.data!r}, "
            f"ctrl={self.ctrl!r}, "
            f"sim_time_start={self.sim_time_start!r}, "
            f"sim_time_sfd={self.sim_time_sfd!r}, "
            f"sim_time_end={self.sim_time_end!r}, "
            f"start_lane={self.start_lane!r})"
        )

    def __len__(self):
        return len(self.data)

    def __iter__(self):
        return self.data.__iter__()

    def __bytes__(self):
        return bytes(self.data)


class XgmiiSource(Reset):

    def __init__(self, data, ctrl, clock, reset=None, enable=None, reset_active_level=True, *args, **kwargs):
        self.log = logging.getLogger(f"cocotb.{data._path}")
        self.data = data
        self.ctrl = ctrl
        self.clock = clock
        self.reset = reset
        self.enable = enable

        self.log.info("XGMII source")
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

        self.enable_dic = True
        self.ifg = 12
        self.force_offset_start = False

        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

        self.queue_occupancy_limit_bytes = -1
        self.queue_occupancy_limit_frames = -1

        self.width = len(self.data)
        self.byte_size = 8
        self.byte_lanes = len(self.ctrl)

        assert self.width == self.byte_lanes * self.byte_size

        self.log.info("XGMII source model configuration")
        self.log.info("  Byte size: %d bits", self.byte_size)
        self.log.info("  Data width: %d bits (%d bytes)", self.width, self.byte_lanes)

        self.idle_d = 0
        self.idle_c = 0

        for k in range(self.byte_lanes):
            self.idle_d |= XgmiiCtrl.IDLE << k*8
            self.idle_c |= 1 << k

        self.data.setimmediatevalue(0)
        self.ctrl.setimmediatevalue(0)

        self._run_cr = None

        self._init_reset(reset, reset_active_level)

    async def send(self, frame):
        while self.full():
            self.dequeue_event.clear()
            await self.dequeue_event.wait()
        frame = XgmiiFrame(frame)
        await self.queue.put(frame)
        self.idle_event.clear()
        self.active_event.set()
        self.queue_occupancy_bytes += len(frame)
        self.queue_occupancy_frames += 1

    def send_nowait(self, frame):
        if self.full():
            raise QueueFull()
        frame = XgmiiFrame(frame)
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
            self.ctrl.value = 0

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
        ifg_cnt = 0
        deficit_idle_cnt = 0
        self.active = False

        clock_edge_event = RisingEdge(self.clock)

        enable_event = None
        if self.enable is not None:
            enable_event = RisingEdge(self.enable)

        while True:
            await clock_edge_event

            if self.enable is None or self.enable.value:
                if ifg_cnt + deficit_idle_cnt > self.byte_lanes-1 or (not self.enable_dic and ifg_cnt > 4):
                    # in IFG
                    ifg_cnt = ifg_cnt - self.byte_lanes
                    if ifg_cnt < 0:
                        if self.enable_dic:
                            deficit_idle_cnt = max(deficit_idle_cnt+ifg_cnt, 0)
                        ifg_cnt = 0

                elif frame is None:
                    # idle
                    if not self.queue.empty():
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
                        frame.start_lane = 0
                        assert frame.data[0] == EthPre.PRE
                        assert frame.ctrl[0] == 0
                        frame.data[0] = XgmiiCtrl.START
                        frame.ctrl[0] = 1
                        frame.data.append(XgmiiCtrl.TERM)
                        frame.ctrl.append(1)

                        # offset start
                        if self.enable_dic:
                            min_ifg = 3 - deficit_idle_cnt
                        else:
                            min_ifg = 0

                        if self.byte_lanes > 4 and (ifg_cnt > min_ifg or self.force_offset_start):
                            ifg_cnt = ifg_cnt-4
                            frame.start_lane = 4
                            frame.data = bytearray([XgmiiCtrl.IDLE]*4)+frame.data
                            frame.ctrl = [1]*4+frame.ctrl

                        if self.enable_dic:
                            deficit_idle_cnt = max(deficit_idle_cnt+ifg_cnt, 0)
                        ifg_cnt = 0
                        self.active = True
                        frame_offset = 0
                    else:
                        # clear counters
                        deficit_idle_cnt = 0
                        ifg_cnt = 0

                if frame is not None:
                    d_val = 0
                    c_val = 0

                    for k in range(self.byte_lanes):
                        if frame is not None:
                            d = frame.data[frame_offset]
                            if frame.sim_time_sfd is None and d == EthPre.SFD:
                                frame.sim_time_sfd = get_sim_time()
                            d_val |= d << k*8
                            c_val |= frame.ctrl[frame_offset] << k
                            frame_offset += 1

                            if frame_offset >= len(frame.data):
                                ifg_cnt = max(self.ifg - (self.byte_lanes-k), 0)
                                frame.sim_time_end = get_sim_time()
                                frame.handle_tx_complete()
                                frame = None
                                self.current_frame = None
                        else:
                            d_val |= XgmiiCtrl.IDLE << k*8
                            c_val |= 1 << k

                    self.data.value = d_val
                    self.ctrl.value = c_val
                else:
                    self.data.value = self.idle_d
                    self.ctrl.value = self.idle_c
                    self.active = False

                    if ifg_cnt == 0 and self.queue.empty():
                        self.idle_event.set()
                        self.active_event.clear()
                        await self.active_event.wait()

            elif self.enable is not None and not self.enable.value:
                await enable_event


class XgmiiSink(Reset):

    def __init__(self, data, ctrl, clock, reset=None, enable=None, reset_active_level=True, *args, **kwargs):
        self.log = logging.getLogger(f"cocotb.{data._path}")
        self.data = data
        self.ctrl = ctrl
        self.clock = clock
        self.reset = reset
        self.enable = enable

        self.log.info("XGMII sink")
        self.log.info("cocotbext-eth version %s", __version__)
        self.log.info("Copyright (c) 2020 Alex Forencich")
        self.log.info("https://github.com/alexforencich/cocotbext-eth")

        super().__init__(*args, **kwargs)

        self.active = False
        self.queue = Queue()
        self.active_event = Event()

        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

        self.width = len(self.data)
        self.byte_size = 8
        self.byte_lanes = len(self.ctrl)

        assert self.width == self.byte_lanes * self.byte_size

        self.log.info("XGMII sink model configuration")
        self.log.info("  Byte size: %d bits", self.byte_size)
        self.log.info("  Data width: %d bits (%d bytes)", self.width, self.byte_lanes)

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

        active_event = First(Edge(self.data), Edge(self.ctrl))

        enable_event = None
        if self.enable is not None:
            enable_event = RisingEdge(self.enable)

        idle_d = sum([XgmiiCtrl.IDLE << n*8 for n in range(self.byte_lanes)])
        idle_c = 2**self.byte_lanes-1

        while True:
            await clock_edge_event

            if self.enable is None or self.enable.value:
                data_val = self.data.value.integer
                ctrl_val = self.ctrl.value.integer
                for offset in range(self.byte_lanes):
                    d_val = (data_val >> (offset*8)) & 0xff
                    c_val = (ctrl_val >> offset) & 1

                    if frame is None:
                        if c_val and d_val == XgmiiCtrl.START:
                            # start
                            frame = XgmiiFrame(bytearray([EthPre.PRE]), [0])
                            frame.sim_time_start = get_sim_time()
                            frame.start_lane = offset
                    else:
                        if c_val:
                            # got a control character; terminate frame reception
                            if d_val != XgmiiCtrl.TERM:
                                # store control character if it's not a termination
                                frame.data.append(d_val)
                                frame.ctrl.append(c_val)

                            frame.compact()
                            frame.sim_time_end = get_sim_time()
                            self.log.info("RX frame: %s", frame)

                            self.queue_occupancy_bytes += len(frame)
                            self.queue_occupancy_frames += 1

                            self.queue.put_nowait(frame)
                            self.active_event.set()

                            frame = None
                        else:
                            if frame.sim_time_sfd is None and d_val == EthPre.SFD:
                                frame.sim_time_sfd = get_sim_time()

                            frame.data.append(d_val)
                            frame.ctrl.append(c_val)

                if data_val == idle_d and ctrl_val == idle_c:
                    await active_event

            elif self.enable is not None and not self.enable.value:
                await enable_event
