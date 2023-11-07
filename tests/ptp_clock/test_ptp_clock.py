#!/usr/bin/env python
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
import os

import cocotb_test.simulator

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb.utils import get_sim_time

from cocotbext.eth import PtpClock


class TB:
    def __init__(self, dut):
        self.dut = dut

        self.log = logging.getLogger("cocotb.tb")
        self.log.setLevel(logging.DEBUG)

        cocotb.start_soon(Clock(dut.clk, 6.4, units="ns").start())

        self.ptp_clock = PtpClock(
            ts_tod=dut.ts_tod,
            ts_rel=dut.ts_rel,
            ts_step=dut.ts_step,
            pps=dut.pps,
            clock=dut.clk,
            reset=dut.rst,
            period_ns=6.4
        )

    async def reset(self):
        self.dut.rst.setimmediatevalue(0)
        await RisingEdge(self.dut.clk)
        await RisingEdge(self.dut.clk)
        self.dut.rst.value = 1
        await RisingEdge(self.dut.clk)
        await RisingEdge(self.dut.clk)
        self.dut.rst.value = 0
        await RisingEdge(self.dut.clk)
        await RisingEdge(self.dut.clk)


@cocotb.test()
async def run_default_rate(dut):

    tb = TB(dut)

    await tb.reset()

    await RisingEdge(dut.clk)
    start_time = get_sim_time('sec')
    start_ts_tod = (dut.ts_tod.value.integer >> 48) + ((dut.ts_tod.value.integer & 0xffffffffffff)/2**16*1e-9)
    start_ts_rel = dut.ts_rel.value.integer/2**16*1e-9

    await ClockCycles(dut.clk, 10000)

    stop_time = get_sim_time('sec')
    stop_ts_tod = (dut.ts_tod.value.integer >> 48) + ((dut.ts_tod.value.integer & 0xffffffffffff)/2**16*1e-9)
    stop_ts_rel = dut.ts_rel.value.integer/2**16*1e-9

    time_delta = stop_time-start_time
    ts_tod_delta = stop_ts_tod-start_ts_tod
    ts_rel_delta = stop_ts_rel-start_ts_rel

    tb.log.info("sim time delta : %g s", time_delta)
    tb.log.info("ToD ts delta   : %g s", ts_tod_delta)
    tb.log.info("rel ts delta   : %g s", ts_rel_delta)

    ts_tod_diff = time_delta - ts_tod_delta
    ts_rel_diff = time_delta - ts_rel_delta

    tb.log.info("ToD ts diff    : %g s", ts_tod_diff)
    tb.log.info("rel ts diff    : %g s", ts_rel_diff)

    assert abs(ts_tod_diff) < 1e-12
    assert abs(ts_rel_diff) < 1e-12

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)


@cocotb.test()
async def run_load_timestamps(dut):

    tb = TB(dut)

    await tb.reset()

    tb.ptp_clock.set_ts_tod_ns(12345678)
    tb.ptp_clock.set_ts_rel_ns(12345678)

    await RisingEdge(dut.clk)

    assert dut.ts_tod.value.integer == 12345678*2**16 + (tb.ptp_clock.period_ns << 16) + tb.ptp_clock.period_fns
    assert dut.ts_rel.value.integer == 12345678*2**16 + (tb.ptp_clock.period_ns << 16) + tb.ptp_clock.period_fns
    assert dut.ts_step.value.integer == 1

    start_time = get_sim_time('sec')
    start_ts_tod = (dut.ts_tod.value.integer >> 48) + ((dut.ts_tod.value.integer & 0xffffffffffff)/2**16*1e-9)
    start_ts_rel = dut.ts_rel.value.integer/2**16*1e-9

    await ClockCycles(dut.clk, 2000)

    stop_time = get_sim_time('sec')
    stop_ts_tod = (dut.ts_tod.value.integer >> 48) + ((dut.ts_tod.value.integer & 0xffffffffffff)/2**16*1e-9)
    stop_ts_rel = dut.ts_rel.value.integer/2**16*1e-9

    time_delta = stop_time-start_time
    ts_tod_delta = stop_ts_tod-start_ts_tod
    ts_rel_delta = stop_ts_rel-start_ts_rel

    tb.log.info("sim time delta : %g s", time_delta)
    tb.log.info("ToD ts delta   : %g s", ts_tod_delta)
    tb.log.info("rel ts delta   : %g s", ts_rel_delta)

    ts_tod_diff = time_delta - ts_tod_delta
    ts_rel_diff = time_delta - ts_rel_delta

    tb.log.info("ToD ts diff    : %g s", ts_tod_diff)
    tb.log.info("rel ts diff    : %g s", ts_rel_diff)

    assert abs(ts_tod_diff) < 1e-12
    assert abs(ts_rel_diff) < 1e-12

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)


@cocotb.test()
async def run_seconds_increment(dut):

    tb = TB(dut)

    await tb.reset()

    tb.ptp_clock.set_ts_tod_ns(999990000)
    tb.ptp_clock.set_ts_rel_ns(999990000)

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    start_time = get_sim_time('sec')
    start_ts_tod = (dut.ts_tod.value.integer >> 48) + ((dut.ts_tod.value.integer & 0xffffffffffff)/2**16*1e-9)
    start_ts_rel = dut.ts_rel.value.integer/2**16*1e-9

    saw_pps = False

    for k in range(3000):
        await RisingEdge(dut.clk)

        if dut.pps.value.integer:
            saw_pps = True
            assert dut.ts_tod.value.integer >> 48 == 1
            assert dut.ts_tod.value.integer & 0xffffffffffff < 10*2**16

    assert saw_pps

    stop_time = get_sim_time('sec')
    stop_ts_tod = (dut.ts_tod.value.integer >> 48) + ((dut.ts_tod.value.integer & 0xffffffffffff)/2**16*1e-9)
    stop_ts_rel = dut.ts_rel.value.integer/2**16*1e-9

    time_delta = stop_time-start_time
    ts_tod_delta = stop_ts_tod-start_ts_tod
    ts_rel_delta = stop_ts_rel-start_ts_rel

    tb.log.info("sim time delta : %g s", time_delta)
    tb.log.info("ToD ts delta   : %g s", ts_tod_delta)
    tb.log.info("rel ts delta   : %g s", ts_rel_delta)

    ts_tod_diff = time_delta - ts_tod_delta
    ts_rel_diff = time_delta - ts_rel_delta

    tb.log.info("ToD ts diff    : %g s", ts_tod_diff)
    tb.log.info("rel ts diff    : %g s", ts_rel_diff)

    assert abs(ts_tod_diff) < 1e-12
    assert abs(ts_rel_diff) < 1e-12

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)


@cocotb.test()
async def run_frequency_adjustment(dut):

    tb = TB(dut)

    await tb.reset()

    tb.ptp_clock.period_ns = 0x6
    tb.ptp_clock.period_fns = 0x6624

    await RisingEdge(dut.clk)
    start_time = get_sim_time('sec')
    start_ts_tod = (dut.ts_tod.value.integer >> 48) + ((dut.ts_tod.value.integer & 0xffffffffffff)/2**16*1e-9)
    start_ts_rel = dut.ts_rel.value.integer/2**16*1e-9

    await ClockCycles(dut.clk, 10000)

    stop_time = get_sim_time('sec')
    stop_ts_tod = (dut.ts_tod.value.integer >> 48) + ((dut.ts_tod.value.integer & 0xffffffffffff)/2**16*1e-9)
    stop_ts_rel = dut.ts_rel.value.integer/2**16*1e-9

    time_delta = stop_time-start_time
    ts_tod_delta = stop_ts_tod-start_ts_tod
    ts_rel_delta = stop_ts_rel-start_ts_rel

    tb.log.info("sim time delta : %g s", time_delta)
    tb.log.info("ToD ts delta   : %g s", ts_tod_delta)
    tb.log.info("rel ts delta   : %g s", ts_rel_delta)

    ts_tod_diff = time_delta - ts_tod_delta * 6.4/(6+(0x6624+2/5)/2**16)
    ts_rel_diff = time_delta - ts_rel_delta * 6.4/(6+(0x6624+2/5)/2**16)

    tb.log.info("ToD ts diff    : %g s", ts_tod_diff)
    tb.log.info("rel ts diff    : %g s", ts_rel_diff)

    assert abs(ts_tod_diff) < 1e-12
    assert abs(ts_rel_diff) < 1e-12

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)


@cocotb.test()
async def run_drift_adjustment(dut):

    tb = TB(dut)

    await tb.reset()

    tb.ptp_clock.drift_num = 20
    tb.ptp_clock.drift_denom = 5

    await RisingEdge(dut.clk)
    start_time = get_sim_time('sec')
    start_ts_tod = (dut.ts_tod.value.integer >> 48) + ((dut.ts_tod.value.integer & 0xffffffffffff)/2**16*1e-9)
    start_ts_rel = dut.ts_rel.value.integer/2**16*1e-9

    await ClockCycles(dut.clk, 10000)

    stop_time = get_sim_time('sec')
    stop_ts_tod = (dut.ts_tod.value.integer >> 48) + ((dut.ts_tod.value.integer & 0xffffffffffff)/2**16*1e-9)
    stop_ts_rel = dut.ts_rel.value.integer/2**16*1e-9

    time_delta = stop_time-start_time
    ts_tod_delta = stop_ts_tod-start_ts_tod
    ts_rel_delta = stop_ts_rel-start_ts_rel

    tb.log.info("sim time delta : %g s", time_delta)
    tb.log.info("ToD ts delta   : %g s", ts_tod_delta)
    tb.log.info("rel ts delta   : %g s", ts_rel_delta)

    ts_tod_diff = time_delta - ts_tod_delta * 6.4/(6+(0x6666+20/5)/2**16)
    ts_rel_diff = time_delta - ts_rel_delta * 6.4/(6+(0x6666+20/5)/2**16)

    tb.log.info("ToD ts diff    : %g s", ts_tod_diff)
    tb.log.info("rel ts diff    : %g s", ts_rel_diff)

    assert abs(ts_tod_diff) < 1e-12
    assert abs(ts_rel_diff) < 1e-12

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)


# cocotb-test

tests_dir = os.path.dirname(__file__)


def test_ptp_clock(request):
    dut = "test_ptp_clock"
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
