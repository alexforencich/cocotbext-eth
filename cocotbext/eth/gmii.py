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
from cocotb.triggers import RisingEdge, ReadOnly, Timer, First, Event
from cocotb.utils import get_sim_time

from .version import __version__
from .constants import EthPre, ETH_PREAMBLE


class GmiiFrame(object):
    def __init__(self, data=None, error=None):
        self.data = bytearray()
        self.error = None
        self.rx_sim_time = None

        if type(data) is GmiiFrame:
            self.data = bytearray(data.data)
            self.error = data.error
            self.rx_sim_time = data.rx_sim_time
        else:
            self.data = bytearray(data)
            self.error = error

    @classmethod
    def from_payload(cls, payload, min_len=60):
        payload = bytearray(payload)
        if len(payload) < min_len:
            payload.extend(bytearray(min_len-len(payload)))
        payload.extend(struct.pack('<L', zlib.crc32(payload)))
        return cls.from_raw_payload(payload)

    @classmethod
    def from_raw_payload(cls, payload):
        data = bytearray(ETH_PREAMBLE)
        data.extend(payload)
        return cls(data)

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

        if self.error is not None:
            self.error = self.error[:n] + [self.error[-1]]*(n-len(self.error))
        else:
            self.error = [0]*n

    def compact(self):
        if not any(self.error):
            self.error = None

    def __eq__(self, other):
        if type(other) is GmiiFrame:
            return self.data == other.data

    def __repr__(self):
        return (
            f"{type(self).__name__}(data={repr(self.data)}, "
            f"error={repr(self.error)}, "
            f"rx_sim_time={repr(self.rx_sim_time)})"
        )

    def __len__(self):
        return len(self.data)

    def __iter__(self):
        return self.data.__iter__()


class GmiiSource(object):

    def __init__(self, data, er, dv, clock, reset=None, enable=None, mii_select=None, *args, **kwargs):
        self.log = logging.getLogger(f"cocotb.{data._path}")
        self.data = data
        self.er = er
        self.dv = dv
        self.clock = clock
        self.reset = reset
        self.enable = enable
        self.mii_select = mii_select

        self.log.info("GMII source")
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

        assert len(self.data) == 8
        self.data.setimmediatevalue(0)
        if self.er is not None:
            assert len(self.er) == 1
            self.er.setimmediatevalue(0)
        assert len(self.dv) == 1
        self.dv.setimmediatevalue(0)

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

        while True:
            await ReadOnly()

            if self.reset is not None and self.reset.value:
                await RisingEdge(self.clock)
                frame = None
                ifg_cnt = 0
                self.active = False
                self.data <= 0
                if self.er is not None:
                    self.er <= 0
                self.dv <= 0
                continue

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
                    self.data <= frame.data.pop(0)
                    if self.er is not None:
                        self.er <= frame.error.pop(0)
                    self.dv <= 1

                    if not frame.data:
                        ifg_cnt = max(self.ifg, 1)
                        frame = None
                else:
                    self.data <= 0
                    if self.er is not None:
                        self.er <= 0
                    self.dv <= 0
                    self.active = False


class GmiiSink(object):

    def __init__(self, data, er, dv, clock, reset=None, enable=None, mii_select=None, *args, **kwargs):
        self.log = logging.getLogger(f"cocotb.{data._path}")
        self.data = data
        self.er = er
        self.dv = dv
        self.clock = clock
        self.reset = reset
        self.enable = enable
        self.mii_select = mii_select

        self.log.info("GMII sink")
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

        assert len(self.data) == 8
        if self.er is not None:
            assert len(self.er) == 1
        if self.dv is not None:
            assert len(self.dv) == 1

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

        while True:
            await ReadOnly()

            if self.reset is not None and self.reset.value:
                await RisingEdge(self.clock)
                frame = None
                self.active = False
                continue

            if self.enable is None or self.enable.value:
                d_val = self.data.value.integer
                dv_val = self.dv.value.integer
                er_val = 0 if self.er is None else self.er.value.integer

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

            await RisingEdge(self.clock)
