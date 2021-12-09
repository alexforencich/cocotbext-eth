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
            ts_96=dut.ts_96,
            ts_64=dut.ts_64,
            pps=dut.pps,
            clock=dut.clk
        )


@cocotb.test()
async def run_test(dut):

    tb = TB(dut)

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    await RisingEdge(dut.clk)
    start_time = get_sim_time('sec')
    start_ts_96 = (dut.ts_96.value.integer >> 48) + ((dut.ts_96.value.integer & 0xffffffffffff)/2**16*1e-9)
    start_ts_64 = dut.ts_64.value.integer/2**16*1e-9

    await ClockCycles(dut.clk, 10000)

    stop_time = get_sim_time('sec')
    stop_ts_96 = (dut.ts_96.value.integer >> 48) + ((dut.ts_96.value.integer & 0xffffffffffff)/2**16*1e-9)
    stop_ts_64 = dut.ts_64.value.integer/2**16*1e-9

    time_delta = stop_time-start_time
    ts_96_delta = stop_ts_96-start_ts_96
    ts_64_delta = stop_ts_64-start_ts_64

    ts_96_diff = time_delta - ts_96_delta
    ts_64_diff = time_delta - ts_64_delta

    tb.log.info("sim time delta  : %g s", time_delta)
    tb.log.info("96 bit ts delta : %g s", ts_96_delta)
    tb.log.info("64 bit ts delta : %g s", ts_64_delta)
    tb.log.info("96 bit ts diff  : %g s", ts_96_diff)
    tb.log.info("64 bit ts diff  : %g s", ts_64_diff)

    assert abs(ts_96_diff) < 1e-12
    assert abs(ts_64_diff) < 1e-12

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
