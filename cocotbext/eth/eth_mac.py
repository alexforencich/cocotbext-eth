"""

Copyright (c) 2021 Alex Forencich

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
from cocotb.triggers import RisingEdge, Timer, First, Event
from cocotb.utils import get_sim_time

from cocotbext.axi.stream import define_stream

from .version import __version__
from .reset import Reset

AxiStreamBus, AxiStreamTransaction, AxiStreamSource, AxiStreamSink, AxiStreamMonitor = define_stream("AxiStream",
    signals=["tvalid", "tdata", "tkeep", "tlast", "tuser"],
    optional_signals=["tready"]
)


class EthMacFrame:
    def __init__(self, data=b'', tx_complete=None):
        self.data = b''
        self.sim_time_start = None
        self.sim_time_sfd = None
        self.sim_time_end = None
        self.ptp_timestamp = None
        self.ptp_tag = None
        self.tx_complete = None

        if type(data) is EthMacFrame:
            self.data = bytes(data.data)
            self.sim_time_start = data.sim_time_start
            self.sim_time_sfd = data.sim_time_sfd
            self.sim_time_end = data.sim_time_end
            self.ptp_timestamp = data.ptp_timestamp
            self.ptp_tag = data.ptp_tag
            self.tx_complete = data.tx_complete
        else:
            self.data = bytes(data)

        if tx_complete is not None:
            self.tx_complete = tx_complete

    @classmethod
    def from_payload(cls, payload, min_len=60, tx_complete=None):
        payload = bytearray(payload)
        if len(payload) < min_len:
            payload.extend(bytearray(min_len-len(payload)))
        payload.extend(struct.pack('<L', zlib.crc32(payload)))
        return cls(payload, tx_complete=tx_complete)

    @classmethod
    def from_raw_payload(cls, payload, tx_complete=None):
        return cls(payload, tx_complete=tx_complete)

    def get_payload(self, strip_fcs=True):
        if strip_fcs:
            return self.data[:-4]
        else:
            return self.data

    def get_fcs(self):
        return self.data[-4:]

    def check_fcs(self):
        return self.get_fcs() == struct.pack('<L', zlib.crc32(self.get_payload(strip_fcs=True)))

    def handle_tx_complete(self):
        if isinstance(self.tx_complete, Event):
            self.tx_complete.set(self)
        elif callable(self.tx_complete):
            self.tx_complete(self)

    def __eq__(self, other):
        if type(other) is EthMacFrame:
            return self.data == other.data

    def __repr__(self):
        return (
            f"{type(self).__name__}(data={self.data!r}, "
            f"sim_time_start={self.sim_time_start!r}, "
            f"sim_time_sfd={self.sim_time_sfd!r}, "
            f"sim_time_end={self.sim_time_end!r}, "
            f"ptp_timestamp={self.ptp_timestamp!r}, "
            f"ptp_tag={self.ptp_tag!r})"
        )

    def __len__(self):
        return len(self.data)

    def __iter__(self):
        return self.data.__iter__()

    def __bytes__(self):
        return bytes(self.data)


class EthMacTx(Reset):
    def __init__(self, bus, clock, reset=None, ptp_time=None, ptp_ts=None, ptp_ts_tag=None, ptp_ts_valid=None,
            reset_active_level=True, ifg=12, speed=1000e6, *args, **kwargs):

        self.bus = bus
        self.clock = clock
        self.reset = reset
        self.ptp_time = ptp_time
        self.ptp_ts = ptp_ts
        self.ptp_ts_tag = ptp_ts_tag
        self.ptp_ts_valid = ptp_ts_valid
        self.ifg = ifg
        self.speed = speed
        if bus._name:
            self.log = logging.getLogger(f"cocotb.{bus._entity._name}.{bus._name}")
        else:
            self.log = logging.getLogger(f"cocotb.{bus._entity._name}")

        self.log.info("Ethernet MAC TX model")
        self.log.info("cocotbext-eth version %s", __version__)
        self.log.info("Copyright (c) 2020 Alex Forencich")
        self.log.info("https://github.com/alexforencich/cocotbext-eth")

        super().__init__(*args, **kwargs)

        self.stream = AxiStreamSink(bus, clock, reset, reset_active_level=reset_active_level)
        self.stream.queue_occupancy_limit = 4

        self.active = False
        self.queue = Queue()
        self.active_event = Event()

        self.ts_queue = Queue()

        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

        self.time_scale = cocotb.utils.get_sim_steps(1, 'sec')

        self.width = len(self.bus.tdata)
        self.byte_lanes = 1

        if hasattr(self.bus, "tkeep"):
            self.byte_lanes = len(self.bus.tkeep)

        self.byte_size = self.width // self.byte_lanes
        self.byte_mask = 2**self.byte_size-1

        self.log.info("Ethernet MAC TX model configuration")
        self.log.info("  Byte size: %d bits", self.byte_size)
        self.log.info("  Data width: %d bits (%d bytes)", self.width, self.byte_lanes)
        if hasattr(self.bus, "tkeep"):
            self.log.info("  tkeep width: %d bits", len(self.bus.tkeep))
        else:
            self.log.info("  tkeep: not present")
        if hasattr(self.bus, "tuser"):
            self.log.info("  tuser width: %d bits", len(self.bus.tuser))
        else:
            self.log.info("  tuser: not present")
        if self.ptp_time:
            self.log.info("  ptp_time width: %d bits", len(self.ptp_time))
        else:
            self.log.info("  ptp_time: not present")

        if self.bus.tready is None:
            raise ValueError("tready is required")

        if self.byte_size != 8:
            raise ValueError("Byte size must be 8")

        if self.byte_lanes * self.byte_size != self.width:
            raise ValueError(f"Bus does not evenly divide into byte lanes "
                f"({self.byte_lanes} * {self.byte_size} != {self.width})")

        if self.ptp_ts:
            self.ptp_ts.setimmediatevalue(0)
        if self.ptp_ts_tag:
            self.ptp_ts_tag.setimmediatevalue(0)
        if self.ptp_ts_valid:
            self.ptp_ts_valid.setimmediatevalue(0)

        self._run_cr = None
        self._run_ts_cr = None

        self._init_reset(reset, reset_active_level)

    def _recv(self, frame):
        if self.queue.empty():
            self.active_event.clear()
        self.queue_occupancy_bytes -= len(frame)
        self.queue_occupancy_frames -= 1
        return frame

    async def recv(self):
        frame = await self.queue.get()
        return self._recv(frame)

    def recv_nowait(self):
        frame = self.queue.get_nowait()
        return self._recv(frame)

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
            if self._run_ts_cr is not None:
                self._run_ts_cr.kill()
                self._run_ts_cr = None

            if self.ptp_ts_valid:
                self.ptp_ts_valid.value = 0

            self.active = False

            while not self.ts_queue.empty():
                self.ts_queue.get_nowait()
        else:
            self.log.info("Reset de-asserted")
            if self._run_cr is None:
                self._run_cr = cocotb.start_soon(self._run())
            if self._run_ts_cr is None and self.ptp_ts:
                self._run_ts_cr = cocotb.start_soon(self._run_ts())

    async def _run(self):
        frame = None
        self.active = False

        while True:
            # wait for data
            cycle = await self.stream.recv()

            frame = EthMacFrame()
            data = bytearray()

            frame.sim_time_start = get_sim_time()

            # wait for preamble time
            await Timer(self.time_scale*8*8//self.speed, 'step')

            frame.sim_time_sfd = get_sim_time()

            if self.ptp_time:
                frame.ptp_timestamp = self.ptp_time.value.integer
                frame.ptp_tag = cycle.tuser.integer >> 1
                self.ts_queue.put_nowait((frame.ptp_timestamp, frame.ptp_tag))

            # process frame data
            while True:
                byte_count = 0

                for offset in range(self.byte_lanes):
                    if not hasattr(self.bus, "tkeep") or (cycle.tkeep.integer >> offset) & 1:
                        data.append((cycle.tdata.integer >> (offset * self.byte_size)) & self.byte_mask)
                        byte_count += 1

                # wait for serialization time
                await Timer(self.time_scale*byte_count*8//self.speed, 'step')

                if cycle.tlast.integer:
                    frame.data = bytes(data)
                    frame.sim_time_end = get_sim_time()
                    self.log.info("RX frame: %s", frame)

                    self.queue_occupancy_bytes += len(frame)
                    self.queue_occupancy_frames += 1

                    await self.queue.put(frame)
                    self.active_event.set()

                    frame = None

                    break

                # get next cycle
                # TODO improve underflow handling
                assert not self.stream.empty(), "underflow"
                cycle = await self.stream.recv()

            # wait for IFG
            await Timer(self.time_scale*self.ifg*8//self.speed, 'step')

    async def _run_ts(self):
        clock_edge_event = RisingEdge(self.clock)

        while True:
            await clock_edge_event
            self.ptp_ts_valid.value = 0

            if not self.ts_queue.empty():
                ts, tag = self.ts_queue.get_nowait()
                self.ptp_ts.value = ts
                if self.ptp_ts_tag is not None:
                    self.ptp_ts_tag.value = tag
                self.ptp_ts_valid.value = 1


class EthMacRx(Reset):
    def __init__(self, bus, clock, reset=None, ptp_time=None,
            reset_active_level=True, ifg=12, speed=1000e6, *args, **kwargs):

        self.bus = bus
        self.clock = clock
        self.reset = reset
        self.ptp_time = ptp_time
        self.ifg = ifg
        self.speed = speed
        if bus._name:
            self.log = logging.getLogger(f"cocotb.{bus._entity._name}.{bus._name}")
        else:
            self.log = logging.getLogger(f"cocotb.{bus._entity._name}")

        self.log.info("Ethernet MAC RX model")
        self.log.info("cocotbext-eth version %s", __version__)
        self.log.info("Copyright (c) 2020 Alex Forencich")
        self.log.info("https://github.com/alexforencich/cocotbext-eth")

        super().__init__(*args, **kwargs)

        self.stream = AxiStreamSource(bus, clock, reset, reset_active_level=reset_active_level)
        self.stream.queue_occupancy_limit = 4

        self.active = False
        self.queue = Queue()
        self.dequeue_event = Event()
        self.current_frame = None
        self.idle_event = Event()
        self.idle_event.set()

        self.queue_occupancy_bytes = 0
        self.queue_occupancy_frames = 0

        self.queue_occupancy_limit_bytes = -1
        self.queue_occupancy_limit_frames = -1

        self.time_scale = cocotb.utils.get_sim_steps(1, 'sec')

        self.width = len(self.bus.tdata)
        self.byte_lanes = 1

        if hasattr(self.bus, "tkeep"):
            self.byte_lanes = len(self.bus.tkeep)

        self.byte_size = self.width // self.byte_lanes
        self.byte_mask = 2**self.byte_size-1

        self.log.info("Ethernet MAC RX model configuration")
        self.log.info("  Byte size: %d bits", self.byte_size)
        self.log.info("  Data width: %d bits (%d bytes)", self.width, self.byte_lanes)
        if hasattr(self.bus, "tkeep"):
            self.log.info("  tkeep width: %d bits", len(self.bus.tkeep))
        else:
            self.log.info("  tkeep: not present")
        if hasattr(self.bus, "tuser"):
            self.log.info("  tuser width: %d bits", len(self.bus.tuser))
        else:
            self.log.info("  tuser: not present")
        if self.ptp_time:
            self.log.info("  ptp_time width: %d bits", len(self.ptp_time))
        else:
            self.log.info("  ptp_time: not present")

        if self.byte_size != 8:
            raise ValueError("Byte size must be 8")

        if self.byte_lanes * self.byte_size != self.width:
            raise ValueError(f"Bus does not evenly divide into byte lanes "
                f"({self.byte_lanes} * {self.byte_size} != {self.width})")

        self._run_cr = None

        self._init_reset(reset, reset_active_level)

    async def send(self, frame):
        while self.full():
            self.dequeue_event.clear()
            await self.dequeue_event.wait()
        frame = EthMacFrame(frame)
        await self.queue.put(frame)
        self.idle_event.clear()
        self.queue_occupancy_bytes += len(frame)
        self.queue_occupancy_frames += 1

    def send_nowait(self, frame):
        if self.full():
            raise QueueFull()
        frame = EthMacFrame(frame)
        self.queue.put_nowait(frame)
        self.idle_event.clear()
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

            if self.current_frame:
                self.log.warning("Flushed transmit frame during reset: %s", self.current_frame)
                self.current_frame.handle_tx_complete()
                self.current_frame = None

            if self.queue.empty():
                self.idle_event.set()
        else:
            self.log.info("Reset de-asserted")
            if self._run_cr is None:
                self._run_cr = cocotb.start_soon(self._run())

    async def _run(self):
        frame = None
        frame_offset = 0
        tuser = 0
        self.active = False

        while True:
            # wait for data
            frame = await self.queue.get()
            tuser = 0
            self.dequeue_event.set()
            self.queue_occupancy_bytes -= len(frame)
            self.queue_occupancy_frames -= 1
            self.current_frame = frame
            frame.sim_time_start = get_sim_time()
            frame.sim_time_sfd = None
            frame.sim_time_end = None
            self.log.info("TX frame: %s", frame)
            frame_offset = 0

            # wait for preamble time
            await Timer(self.time_scale*8*8//self.speed, 'step')

            frame.sim_time_sfd = get_sim_time()

            if self.ptp_time:
                frame.ptp_timestamp = self.ptp_time.value.integer
                tuser |= frame.ptp_timestamp << 1

            # process frame data
            while frame is not None:
                byte_count = 0

                cycle = AxiStreamTransaction()

                cycle.tdata = 0
                cycle.tkeep = 0
                cycle.tlast = 0
                cycle.tuser = tuser

                for offset in range(self.byte_lanes):
                    cycle.tdata |= (frame.data[frame_offset] & self.byte_mask) << (offset * self.byte_size)
                    cycle.tkeep |= 1 << offset
                    byte_count += 1
                    frame_offset += 1

                    if frame_offset >= len(frame.data):
                        cycle.tlast = 1
                        frame.sim_time_end = get_sim_time()
                        frame.handle_tx_complete()
                        frame = None
                        self.current_frame = None
                        break

                await self.stream.send(cycle)

                # wait for serialization time
                await Timer(self.time_scale*byte_count*8//self.speed, 'step')

            # wait for IFG
            await Timer(self.time_scale*self.ifg*8//self.speed, 'step')


class EthMac:
    def __init__(self, tx_bus=None, tx_clk=None, tx_rst=None, tx_ptp_time=None, tx_ptp_ts=None, tx_ptp_ts_tag=None,
            tx_ptp_ts_valid=None, rx_bus=None, rx_clk=None, rx_rst=None, rx_ptp_time=None,
            reset_active_level=True, ifg=12, speed=1000e6, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.tx = EthMacTx(tx_bus, tx_clk, tx_rst, tx_ptp_time, tx_ptp_ts, tx_ptp_ts_tag, tx_ptp_ts_valid,
            reset_active_level=reset_active_level, ifg=ifg, speed=speed)
        self.rx = EthMacRx(rx_bus, rx_clk, rx_rst, rx_ptp_time,
            reset_active_level=reset_active_level, ifg=ifg, speed=speed)
