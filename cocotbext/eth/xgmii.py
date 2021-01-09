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
from collections import deque

import cocotb
from cocotb.triggers import RisingEdge, Timer, First, Event
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
        if not any(self.ctrl):
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

    def __init__(self, data, ctrl, clock, reset=None, enable=None, *args, **kwargs):
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
        self.queue = deque()

        self.enable_dic = True
        self.ifg = 12
        self.force_offset_start = False

        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

        self.width = len(self.data)
        self.byte_width = len(self.ctrl)

        assert self.width == self.byte_width * 8

        self.idle_d = 0
        self.idle_c = 0

        for k in range(self.byte_width):
            self.idle_d |= XgmiiCtrl.IDLE << k*8
            self.idle_c |= 1 << k

        self.data.setimmediatevalue(0)
        self.ctrl.setimmediatevalue(0)

        self._run_cr = None

        self._init_reset(reset)

    async def send(self, frame):
        self.send_nowait(frame)

    def send_nowait(self, frame):
        frame = XgmiiFrame(frame)
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
        self.ctrl <= 0

    async def _run(self):
        frame = None
        ifg_cnt = 0
        deficit_idle_cnt = 0
        self.active = False

        while True:
            await RisingEdge(self.clock)

            if self.enable is None or self.enable.value:
                if ifg_cnt + deficit_idle_cnt > self.byte_width-1 or (not self.enable_dic and ifg_cnt > 4):
                    # in IFG
                    ifg_cnt = ifg_cnt - self.byte_width
                    if ifg_cnt < 0:
                        if self.enable_dic:
                            deficit_idle_cnt = max(deficit_idle_cnt+ifg_cnt, 0)
                        ifg_cnt = 0

                elif frame is None:
                    # idle
                    if self.queue:
                        # send frame
                        frame = self.queue.popleft()
                        self.queue_occupancy_bytes -= len(frame)
                        self.queue_occupancy_frames -= 1
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

                        if self.byte_width > 4 and (ifg_cnt > min_ifg or self.force_offset_start):
                            ifg_cnt = ifg_cnt-4
                            frame.start_lane = 4
                            frame.data = bytearray([XgmiiCtrl.IDLE]*4)+frame.data
                            frame.ctrl = [1]*4+frame.ctrl

                        if self.enable_dic:
                            deficit_idle_cnt = max(deficit_idle_cnt+ifg_cnt, 0)
                        ifg_cnt = 0
                        self.active = True
                    else:
                        # clear counters
                        deficit_idle_cnt = 0
                        ifg_cnt = 0

                if frame is not None:
                    d_val = 0
                    c_val = 0

                    for k in range(self.byte_width):
                        if frame is not None:
                            d = frame.data.pop(0)
                            if frame.sim_time_sfd is None and d == EthPre.SFD:
                                frame.sim_time_sfd = get_sim_time()
                            d_val |= d << k*8
                            c_val |= frame.ctrl.pop(0) << k

                            if not frame.data:
                                ifg_cnt = max(self.ifg - (self.byte_width-k), 0)
                                frame.sim_time_end = get_sim_time()
                                frame.handle_tx_complete()
                                frame = None
                        else:
                            d_val |= XgmiiCtrl.IDLE << k*8
                            c_val |= 1 << k

                    self.data <= d_val
                    self.ctrl <= c_val
                else:
                    self.data <= self.idle_d
                    self.ctrl <= self.idle_c
                    self.active = False


class XgmiiSink(Reset):

    def __init__(self, data, ctrl, clock, reset=None, enable=None, *args, **kwargs):
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
        self.queue = deque()
        self.sync = Event()

        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

        self.width = len(self.data)
        self.byte_width = len(self.ctrl)

        assert self.width == self.byte_width * 8

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
                for offset in range(self.byte_width):
                    d_val = (self.data.value.integer >> (offset*8)) & 0xff
                    c_val = (self.ctrl.value.integer >> offset) & 1

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

                            self.queue.append(frame)
                            self.sync.set()

                            frame = None
                        else:
                            if frame.sim_time_sfd is None and d_val == EthPre.SFD:
                                frame.sim_time_sfd = get_sim_time()

                            frame.data.append(d_val)
                            frame.ctrl.append(c_val)
