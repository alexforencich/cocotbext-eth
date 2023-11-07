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
import math
from fractions import Fraction

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .version import __version__
from .reset import Reset


class PtpClock(Reset):

    def __init__(
            self,
            ts_tod=None,
            ts_rel=None,
            ts_step=None,
            pps=None,
            clock=None,
            reset=None,
            reset_active_level=True,
            period_ns=6.4,
            *args, **kwargs):

        self.log = logging.getLogger(f"cocotb.eth.{type(self).__name__}")
        self.ts_tod = ts_tod
        self.ts_rel = ts_rel
        self.ts_step = ts_step
        self.pps = pps
        self.clock = clock
        self.reset = reset

        self.period_ns = 0
        self.period_fns = 0
        self.drift_num = 0
        self.drift_denom = 0
        self.drift_cnt = 0
        self.set_period_ns(period_ns)

        self.log.info("PTP clock")
        self.log.info("cocotbext-eth version %s", __version__)
        self.log.info("Copyright (c) 2020 Alex Forencich")
        self.log.info("https://github.com/alexforencich/cocotbext-eth")

        super().__init__(*args, **kwargs)

        self.ts_tod_s = 0
        self.ts_tod_ns = 0
        self.ts_tod_fns = 0

        self.ts_rel_ns = 0
        self.ts_rel_fns = 0

        self.ts_updated = False

        if self.ts_tod is not None:
            self.ts_tod.setimmediatevalue(0)
        if self.ts_rel is not None:
            self.ts_rel.setimmediatevalue(0)
        if self.ts_step is not None:
            self.ts_step.setimmediatevalue(0)
        if self.pps is not None:
            self.pps.setimmediatevalue(0)

        self._run_cr = None

        self._init_reset(reset, reset_active_level)

    def set_period(self, ns, fns):
        self.period_ns = int(ns)
        self.period_fns = int(fns) & 0xffff

    def set_drift(self, num, denom):
        self.drift_num = int(num)
        self.drift_denom = int(denom)

    def set_period_ns(self, t):
        drift, period = math.modf(t*2**16)
        period = int(period)
        frac = Fraction(drift).limit_denominator(2**16)
        self.period_ns = period >> 16
        self.period_fns = period & 0xffff
        self.drift_num = frac.numerator
        self.drift_denom = frac.denominator

    def get_period_ns(self):
        p = ((self.period_ns << 16) | self.period_fns) / 2**16
        if self.drift_denom:
            return p + self.drift_num / self.drift_rate / 2**16
        return p

    def set_ts_tod(self, ts_s, ts_ns, ts_fns):
        self.ts_tod_s = int(ts_s)
        self.ts_tod_ns = int(ts_ns)
        self.ts_tod_fns = int(ts_fns)
        self.ts_updated = True

    def set_ts_tod_96(self, ts):
        ts = int(ts)
        self.set_ts_tod(ts >> 48, (ts >> 32) & 0x3fffffff, ts & 0xffff)

    def set_ts_tod_ns(self, t):
        self.set_ts_tod_s(t*1e-9)

    def set_ts_tod_s(self, t):
        ts_ns, ts_s = math.modf(t)
        ts_ns *= 1e9
        ts_fns, ts_ns = math.modf(ts_ns)
        ts_fns *= 2**16
        self.set_ts_tod(ts_s, ts_ns, ts_fns)

    def get_ts_tod(self):
        return (self.ts_tod_s, self.ts_tod_ns, self.ts_tod_fns)

    def get_ts_tod_96(self):
        ts_s, ts_ns, ts_fns = self.get_ts_tod()
        return (ts_s << 48) | (ts_ns << 16) | ts_fns

    def get_ts_tod_ns(self):
        ts_s, ts_ns, ts_fns = self.get_ts_tod()
        return ts_s*1e9+ts_ns+ts_fns/2**16

    def get_ts_tod_s(self):
        return self.get_ts_tod_ns()*1e-9

    def set_ts_rel(self, ts_ns, ts_fns):
        self.ts_rel_ns = int(ts_ns)
        self.ts_rel_fns = int(ts_fns)
        self.ts_updated = True

    def set_ts_rel_64(self, ts):
        ts = int(ts)
        self.set_ts_rel(ts >> 16, (ts & 0xffff) << 16)

    def set_ts_rel_ns(self, t):
        ts_fns, ts_ns = math.modf(t)
        ts_fns *= 2**16
        self.set_ts_rel(ts_ns, ts_fns)

    def set_ts_rel_s(self, t):
        self.set_ts_rel_ns(t*1e9)

    def get_ts_rel(self):
        return (self.ts_rel_ns, self.ts_rel_fns)

    def get_ts_rel_64(self):
        ts_ns, ts_fns = self.get_ts_rel()
        return (ts_ns << 16) | (ts_fns >> 16)

    def get_ts_rel_ns(self):
        ts_ns, ts_fns = self.get_ts_rel()
        return ts_ns + ts_fns/2**16

    def get_ts_rel_s(self):
        return self.get_ts_rel()*1e-9

    def _handle_reset(self, state):
        if state:
            self.log.info("Reset asserted")
            if self._run_cr is not None:
                self._run_cr.kill()
                self._run_cr = None

            self.ts_tod_s = 0
            self.ts_tod_ns = 0
            self.ts_tod_fns = 0
            self.ts_rel_ns = 0
            self.ts_rel_fns = 0
            self.drift_cnt = 0
            if self.ts_tod is not None:
                self.ts_tod.value = 0
            if self.ts_rel is not None:
                self.ts_rel.value = 0
            if self.ts_step is not None:
                self.ts_step.value = 0
            if self.pps is not None:
                self.pps.value = 0
        else:
            self.log.info("Reset de-asserted")
            if self._run_cr is None:
                self._run_cr = cocotb.start_soon(self._run())

    async def _run(self):
        clock_edge_event = RisingEdge(self.clock)

        while True:
            await clock_edge_event

            if self.ts_step is not None:
                self.ts_step.value = self.ts_updated
                self.ts_updated = False

            if self.pps is not None:
                self.pps.value = 0

            # increment 96 bit timestamp
            if self.ts_tod is not None or self.pps is not None:
                t = ((self.ts_tod_ns << 16) + self.ts_tod_fns) + ((self.period_ns << 16) + self.period_fns)

                if self.drift_denom and self.drift_cnt == 0:
                    t += self.drift_num

                if t > (1000000000 << 16):
                    self.ts_tod_s += 1
                    t -= (1000000000 << 16)
                    if self.pps is not None:
                        self.pps.value = 1

                self.ts_tod_fns = t & 0xffff
                self.ts_tod_ns = t >> 16

                if self.ts_tod is not None:
                    self.ts_tod.value = (self.ts_tod_s << 48) | (self.ts_tod_ns << 16) | (self.ts_tod_fns)

            # increment 64 bit timestamp
            if self.ts_rel is not None:
                t = ((self.ts_rel_ns << 16) + self.ts_rel_fns) + ((self.period_ns << 16) + self.period_fns)

                if self.drift_denom and self.drift_cnt == 0:
                    t += self.drift_num

                self.ts_rel_fns = t & 0xffff
                self.ts_rel_ns = t >> 16

                self.ts_rel.value = (self.ts_rel_ns << 16) | self.ts_rel_fns

            if self.drift_denom:
                if self.drift_cnt > 0:
                    self.drift_cnt -= 1
                else:
                    self.drift_cnt = self.drift_denom-1


class PtpClockSimTime:

    def __init__(self, ts_tod=None, ts_rel=None, pps=None, clock=None, *args, **kwargs):
        self.log = logging.getLogger(f"cocotb.eth.{type(self).__name__}")
        self.ts_tod = ts_tod
        self.ts_rel = ts_rel
        self.pps = pps
        self.clock = clock

        self.log.info("PTP clock (sim time)")
        self.log.info("cocotbext-eth version %s", __version__)
        self.log.info("Copyright (c) 2020 Alex Forencich")
        self.log.info("https://github.com/alexforencich/cocotbext-eth")

        super().__init__(*args, **kwargs)

        self.ts_tod_s = 0
        self.ts_tod_ns = 0
        self.ts_tod_fns = 0

        self.ts_rel_ns = 0
        self.ts_rel_fns = 0

        self.last_ts_tod_s = 0

        if self.ts_tod is not None:
            self.ts_tod.setimmediatevalue(0)
        if self.ts_rel is not None:
            self.ts_rel.setimmediatevalue(0)
        if self.pps is not None:
            self.pps.value = 0

        self._run_cr = cocotb.start_soon(self._run())

    def get_ts_tod(self):
        return (self.ts_tod_s, self.ts_tod_ns, self.ts_tod_fns)

    def get_ts_tod_96(self):
        ts_s, ts_ns, ts_fns = self.get_ts_tod()
        return (ts_s << 48) | (ts_ns << 16) | ts_fns

    def get_ts_tod_ns(self):
        ts_s, ts_ns, ts_fns = self.get_ts_tod()
        return ts_s*1e9+ts_ns+ts_fns/2**16

    def get_ts_rel(self):
        return (self.ts_rel_ns, self.ts_rel_fns)

    def get_ts_rel_64(self):
        ts_ns, ts_fns = self.get_ts_rel()
        return (ts_ns << 16) | (ts_fns >> 16)

    def get_ts_rel_ns(self):
        ts_ns, ts_fns = self.get_ts_rel()
        return ts_ns + ts_fns/2**16

    def get_ts_rel_s(self):
        return self.get_ts_rel()*1e-9

    async def _run(self):
        clock_edge_event = RisingEdge(self.clock)

        while True:
            await clock_edge_event

            self.ts_rel_fns, self.ts_rel_ns = math.modf(get_sim_time('ns'))

            self.ts_rel_ns = int(self.ts_rel_ns)
            self.ts_rel_fns = int(self.ts_rel_fns*0x10000)

            self.ts_tod_s, self.ts_tod_ns = divmod(self.ts_rel_ns, 1000000000)
            self.ts_tod_fns = self.ts_rel_fns

            if self.ts_tod is not None:
                self.ts_tod.value = (self.ts_tod_s << 48) | (self.ts_tod_ns << 16) | self.ts_tod_fns

            if self.ts_rel is not None:
                self.ts_rel.value = (self.ts_rel_ns << 16) | self.ts_rel_fns

            if self.pps is not None:
                self.pps.value = int(self.last_ts_tod_s != self.ts_tod_s)

            self.last_ts_tod_s = self.ts_tod_s
