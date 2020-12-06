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
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from cocotbext.eth import PtpClock


class TB(object):
    def __init__(self, dut):
        self.dut = dut

        self.log = logging.getLogger("cocotb.tb")
        self.log.setLevel(logging.DEBUG)

        cocotb.fork(Clock(dut.clk, 6.4, units="ns").start())

        self.ptp_clock = PtpClock(
            ts_96=dut.ts_96,
            ts_64=dut.ts_64,
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
        self.dut.rst <= 1
        await RisingEdge(self.dut.clk)
        await RisingEdge(self.dut.clk)
        self.dut.rst <= 0
        await RisingEdge(self.dut.clk)
        await RisingEdge(self.dut.clk)


@cocotb.test()
async def run_default_rate(dut):

    tb = TB(dut)

    await tb.reset()

    await RisingEdge(dut.clk)
    start_time = get_sim_time('sec')
    start_ts_96 = (dut.ts_96.value.integer >> 48) + ((dut.ts_96.value.integer & 0xffffffffffff)/2**16*1e-9)
    start_ts_64 = dut.ts_64.value.integer/2**16*1e-9

    for k in range(10000):
        await RisingEdge(dut.clk)

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


@cocotb.test()
async def run_load_timestamps(dut):

    tb = TB(dut)

    await tb.reset()

    tb.ptp_clock.set_ts_96(12345678)
    tb.ptp_clock.set_ts_64(12345678)

    await RisingEdge(dut.clk)

    assert dut.ts_96.value.integer == 12345678+((tb.ptp_clock.period_ns << 16) + tb.ptp_clock.period_fns)
    assert dut.ts_64.value.integer == 12345678+((tb.ptp_clock.period_ns << 16) + tb.ptp_clock.period_fns)
    assert dut.ts_step.value.integer == 1

    start_time = get_sim_time('sec')
    start_ts_96 = (dut.ts_96.value.integer >> 48) + ((dut.ts_96.value.integer & 0xffffffffffff)/2**16*1e-9)
    start_ts_64 = dut.ts_64.value.integer/2**16*1e-9

    for k in range(2000):
        await RisingEdge(dut.clk)

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


@cocotb.test()
async def run_seconds_increment(dut):

    tb = TB(dut)

    await tb.reset()

    tb.ptp_clock.set_ts_96(999990000*2**16)
    tb.ptp_clock.set_ts_64(999990000*2**16)

    await RisingEdge(dut.clk)
    start_time = get_sim_time('sec')
    start_ts_96 = (dut.ts_96.value.integer >> 48) + ((dut.ts_96.value.integer & 0xffffffffffff)/2**16*1e-9)
    start_ts_64 = dut.ts_64.value.integer/2**16*1e-9

    saw_pps = False

    for k in range(3000):
        await RisingEdge(dut.clk)

        if dut.pps.value.integer:
            saw_pps = True
            assert dut.ts_96.value.integer >> 48 == 1
            assert dut.ts_96.value.integer & 0xffffffffffff < 10*2**16

    assert saw_pps

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


@cocotb.test()
async def run_frequency_adjustment(dut):

    tb = TB(dut)

    await tb.reset()

    tb.ptp_clock.period_ns = 0x6
    tb.ptp_clock.period_fns = 0x6624

    await RisingEdge(dut.clk)
    start_time = get_sim_time('sec')
    start_ts_96 = (dut.ts_96.value.integer >> 48) + ((dut.ts_96.value.integer & 0xffffffffffff)/2**16*1e-9)
    start_ts_64 = dut.ts_64.value.integer/2**16*1e-9

    for k in range(10000):
        await RisingEdge(dut.clk)

    stop_time = get_sim_time('sec')
    stop_ts_96 = (dut.ts_96.value.integer >> 48) + ((dut.ts_96.value.integer & 0xffffffffffff)/2**16*1e-9)
    stop_ts_64 = dut.ts_64.value.integer/2**16*1e-9

    time_delta = stop_time-start_time
    ts_96_delta = stop_ts_96-start_ts_96
    ts_64_delta = stop_ts_64-start_ts_64

    ts_96_diff = time_delta - ts_96_delta * 6.4/(6+(0x6624+2/5)/2**16)
    ts_64_diff = time_delta - ts_64_delta * 6.4/(6+(0x6624+2/5)/2**16)

    tb.log.info("sim time delta  : %g s", time_delta)
    tb.log.info("96 bit ts delta : %g s", ts_96_delta)
    tb.log.info("64 bit ts delta : %g s", ts_64_delta)
    tb.log.info("96 bit ts diff  : %g s", ts_96_diff)
    tb.log.info("64 bit ts diff  : %g s", ts_64_diff)

    assert abs(ts_96_diff) < 1e-12
    assert abs(ts_64_diff) < 1e-12

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)


@cocotb.test()
async def run_drift_adjustment(dut):

    tb = TB(dut)

    await tb.reset()

    tb.ptp_clock.drift_ns = 0
    tb.ptp_clock.drift_fns = 20
    tb.ptp_clock.drift_rate = 5

    await RisingEdge(dut.clk)
    start_time = get_sim_time('sec')
    start_ts_96 = (dut.ts_96.value.integer >> 48) + ((dut.ts_96.value.integer & 0xffffffffffff)/2**16*1e-9)
    start_ts_64 = dut.ts_64.value.integer/2**16*1e-9

    for k in range(10000):
        await RisingEdge(dut.clk)

    stop_time = get_sim_time('sec')
    stop_ts_96 = (dut.ts_96.value.integer >> 48) + ((dut.ts_96.value.integer & 0xffffffffffff)/2**16*1e-9)
    stop_ts_64 = dut.ts_64.value.integer/2**16*1e-9

    time_delta = stop_time-start_time
    ts_96_delta = stop_ts_96-start_ts_96
    ts_64_delta = stop_ts_64-start_ts_64

    ts_96_diff = time_delta - ts_96_delta * 6.4/(6+(0x6666+20/5)/2**16)
    ts_64_diff = time_delta - ts_64_delta * 6.4/(6+(0x6666+20/5)/2**16)

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
rtl_dir = os.path.abspath(os.path.join(tests_dir, '..', '..', 'rtl'))


def test_ptp_clock(request):
    dut = "test_ptp_clock"
    module = os.path.splitext(os.path.basename(__file__))[0]
    toplevel = dut

    verilog_sources = [
        os.path.join(tests_dir, f"{dut}.v"),
    ]

    parameters = {}

    extra_env = {f'PARAM_{k}': str(v) for k, v in parameters.items()}

    sim_build = os.path.join(tests_dir,
        "sim_build_"+request.node.name.replace('[', '-').replace(']', ''))

    cocotb_test.simulator.run(
        python_search=[tests_dir],
        verilog_sources=verilog_sources,
        toplevel=toplevel,
        module=module,
        parameters=parameters,
        sim_build=sim_build,
        extra_env=extra_env,
    )
