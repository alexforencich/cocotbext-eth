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
from cocotb.triggers import RisingEdge, ReadOnly

from .version import __version__


class PtpClock(object):

    def __init__(
            self,
            ts_96=None,
            ts_64=None,
            ts_step=None,
            pps=None,
            clock=None,
            reset=None,
            period_ns=6.4,
            *args, **kwargs):

        self.log = logging.getLogger(f"cocotb.eth.{type(self).__name__}")
        self.ts_96 = ts_96
        self.ts_64 = ts_64
        self.ts_step = ts_step
        self.pps = pps
        self.clock = clock
        self.reset = reset

        self.period_ns = 0
        self.period_fns = 0
        self.drift_ns = 0
        self.drift_fns = 0
        self.drift_rate = 0
        self.set_period_ns(period_ns)

        self.log.info("PTP clock")
        self.log.info("cocotbext-eth version %s", __version__)
        self.log.info("Copyright (c) 2020 Alex Forencich")
        self.log.info("https://github.com/alexforencich/cocotbext-eth")

        super().__init__(*args, **kwargs)

        self.ts_96_s = 0
        self.ts_96_ns = 0
        self.ts_96_fns = 0

        self.ts_64_ns = 0
        self.ts_64_fns = 0

        self.ts_updated = False

        self.drift_cnt = 0

        if self.ts_96 is not None:
            self.ts_96.setimmediatevalue(0)
        if self.ts_64 is not None:
            self.ts_64.setimmediatevalue(0)
        if self.ts_step is not None:
            self.ts_step.setimmediatevalue(0)
        if self.pps is not None:
            self.pps.setimmediatevalue(0)

        cocotb.fork(self._run())

    def set_period(self, ns, fns):
        self.period_ns = int(ns)
        self.period_fns = int(fns) & 0xffff

    def set_drift(self, ns, fns, rate):
        self.drift_ns = int(ns)
        self.drift_fns = int(fns) & 0xffff
        self.drift_rate = int(rate)

    def set_period_ns(self, t):
        drift, period = math.modf(t*2**16)
        period = int(period)
        frac = Fraction(drift).limit_denominator(2**16)
        drift = frac.numerator
        rate = frac.denominator
        self.period_ns = period >> 16
        self.period_fns = period & 0xffff
        self.drift_ns = drift >> 16
        self.drift_fns = drift & 0xffff
        self.drift_rate = rate

    def get_period_ns(self):
        p = ((self.period_ns << 16) | self.period_fns) / 2**16
        if self.drift_rate:
            return p + ((self.drift_ns << 16) | self.drift_fns) / self.drift_rate / 2**16
        return p

    def set_ts_96(self, ts_s, ts_ns=None, ts_fns=None):
        ts_s = int(ts_s)
        if ts_fns is not None:
            # got separate fields
            self.ts_96_s = ts_s
            self.ts_96_ns = int(ts_ns)
            self.ts_96_fns = int(ts_fns)
        else:
            # got timestamp as integer
            self.ts_96_s = ts_s >> 48
            self.ts_96_ns = (ts_s >> 16) & 0x3fffffff
            self.ts_96_fns = ts_s & 0xffff
        self.ts_updated = True

    def set_ts_96_ns(self, t):
        self.set_ts_96_s(t*1e-9)

    def set_ts_96_s(self, t):
        ts_ns, ts_s = math.modf(t)
        ts_ns *= 1e9
        ts_fns, ts_ns = math.modf(ts_ns)
        ts_fns *= 2**16
        self.set_ts_96(ts_s, ts_ns, ts_fns)

    def get_ts_96(self):
        return (self.ts_96_s << 48) | (self.ts_96_ns << 16) | self.ts_96_fns

    def get_ts_96_ns(self):
        return self.ts_96_s*1e9+self.ts_96_ns+self.ts_96_fns/2**16

    def get_ts_96_s(self):
        return self.get_ts_96_ns()*1e-9

    def set_ts_64(self, ts_ns, ts_fns=None):
        ts_ns = int(ts_ns)
        if ts_fns is not None:
            # got separate fields
            self.ts_64_ns = ts_ns
            self.ts_64_fns = int(ts_fns)
        else:
            # got timestamp as integer
            self.ts_64_ns = ts_ns >> 16
            self.ts_64_fns = ts_ns & 0xffff
        self.ts_updated = True

    def set_ts_64_ns(self, t):
        self.set_ts_64(t*2**16)

    def set_ts_64_s(self, t):
        self.set_ts_64_ns(t*1e9)

    def get_ts_64(self):
        return (self.ts_64_ns << 16) | self.ts_64_fns

    def get_ts_64_ns(self):
        return self.get_ts_64()/2**16

    def get_ts_64_s(self):
        return self.get_ts_64()*1e-9

    async def _run(self):
        while True:
            await ReadOnly()

            if self.reset is not None and self.reset.value:
                await RisingEdge(self.clock)
                self.ts_96_s = 0
                self.ts_96_ns = 0
                self.ts_96_fns = 0
                self.ts_64_ns = 0
                self.ts_64_fns = 0
                self.drift_cnt = 0
                if self.ts_96 is not None:
                    self.ts_96 <= 0
                if self.ts_64 is not None:
                    self.ts_64 <= 0
                if self.ts_step is not None:
                    self.ts_step <= 0
                if self.pps is not None:
                    self.pps <= 0
                continue

            await RisingEdge(self.clock)

            if self.ts_step is not None:
                self.ts_step <= self.ts_updated
                self.ts_updated = False

            if self.pps is not None:
                self.pps <= 0

            # increment 96 bit timestamp
            if self.ts_96 is not None or self.pps is not None:
                t = ((self.ts_96_ns << 16) + self.ts_96_fns) + ((self.period_ns << 16) + self.period_fns)

                if self.drift_rate and self.drift_cnt == 0:
                    t += (self.drift_ns << 16) + self.drift_fns

                if t > (1000000000 << 16):
                    self.ts_96_s += 1
                    t -= (1000000000 << 16)
                    if self.pps is not None:
                        self.pps <= 1

                self.ts_96_fns = t & 0xffff
                self.ts_96_ns = t >> 16

                if self.ts_96 is not None:
                    self.ts_96 <= (self.ts_96_s << 48) | (self.ts_96_ns << 16) | (self.ts_96_fns)

            # increment 64 bit timestamp
            if self.ts_64 is not None:
                t = ((self.ts_64_ns << 16) + self.ts_64_fns) + ((self.period_ns << 16) + self.period_fns)

                if self.drift_rate and self.drift_cnt == 0:
                    t += ((self.drift_ns << 16) + self.drift_fns)

                self.ts_64_fns = t & 0xffff
                self.ts_64_ns = t >> 16

                self.ts_64 <= (self.ts_64_ns << 16) | self.ts_64_fns

            if self.drift_rate:
                if self.drift_cnt > 0:
                    self.drift_cnt -= 1
                else:
                    self.drift_cnt = self.drift_rate-1
