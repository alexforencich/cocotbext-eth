#!/usr/bin/env python
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
import os
from decimal import Decimal

import cocotb_test.simulator

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb.utils import get_sim_time

from cocotbext.eth import PtpClockSimTime


class TB:
    def __init__(self, dut):
        self.dut = dut

        self.log = logging.getLogger("cocotb.tb")
        self.log.setLevel(logging.DEBUG)

        cocotb.start_soon(Clock(dut.clk, 6.4, units="ns").start())

        self.ptp_clock = PtpClockSimTime(
            ts_tod=dut.ts_tod,
            ts_rel=dut.ts_rel,
            pps=dut.pps,
            clock=dut.clk
        )

    def get_ts_tod_ns(self):
        ts = self.dut.ts_tod.value.integer
        return Decimal(ts >> 48).scaleb(9) + (Decimal(ts & 0xffffffffffff) / Decimal(2**16))

    def get_ts_rel_ns(self):
        ts = self.dut.ts_rel.value.integer
        return Decimal(ts) / Decimal(2**16)


@cocotb.test()
async def run_test(dut):

    tb = TB(dut)

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    await RisingEdge(dut.clk)
    start_time = Decimal(get_sim_time('fs')).scaleb(-6)
    start_ts_tod = tb.get_ts_tod_ns()
    start_ts_rel = tb.get_ts_rel_ns()

    await ClockCycles(dut.clk, 10000)

    stop_time = Decimal(get_sim_time('fs')).scaleb(-6)
    stop_ts_tod = tb.get_ts_tod_ns()
    stop_ts_rel = tb.get_ts_rel_ns()

    time_delta = stop_time-start_time
    ts_tod_delta = stop_ts_tod-start_ts_tod
    ts_rel_delta = stop_ts_rel-start_ts_rel

    tb.log.info("sim time delta : %s ns", time_delta)
    tb.log.info("ToD ts delta   : %s ns", ts_tod_delta)
    tb.log.info("rel ts delta   : %s ns", ts_rel_delta)

    ts_tod_diff = time_delta - ts_tod_delta
    ts_rel_diff = time_delta - ts_rel_delta

    tb.log.info("ToD ts diff    : %s ns", ts_tod_diff)
    tb.log.info("rel ts diff    : %s ns", ts_rel_diff)

    assert abs(ts_tod_diff) < 1e-3
    assert abs(ts_rel_diff) < 1e-3

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)


# cocotb-test

tests_dir = os.path.dirname(__file__)


def test_ptp_clock(request):
    dut = "test_ptp_clock_sim_time"
    module = os.path.splitext(os.path.basename(__file__))[0]
    toplevel = dut

    verilog_sources = [
        os.path.join(tests_dir, f"{dut}.v"),
    ]

    parameters = {}

    extra_env = {f'PARAM_{k}': str(v) for k, v in parameters.items()}

    sim_build = os.path.join(tests_dir, "sim_build",
        request.node.name.replace('[', '-').replace(']', ''))

    cocotb_test.simulator.run(
        python_search=[tests_dir],
        verilog_sources=verilog_sources,
        toplevel=toplevel,
        module=module,
        parameters=parameters,
        sim_build=sim_build,
        extra_env=extra_env,
    )
