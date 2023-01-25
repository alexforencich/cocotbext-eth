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

import itertools
import logging
import os

import cocotb_test.simulator

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from cocotb.regression import TestFactory

from cocotbext.eth import GmiiFrame, RgmiiSource, RgmiiSink


class TB:
    def __init__(self, dut):
        self.dut = dut

        self.log = logging.getLogger("cocotb.tb")
        self.log.setLevel(logging.DEBUG)

        self._enable_generator = None
        self._enable_cr = None

        cocotb.start_soon(Clock(dut.clk, 2, units="ns").start())

        self.source = RgmiiSource(dut.rgmii_d, dut.rgmii_ctl, dut.clk, dut.rst, dut.rgmii_clk_en, dut.rgmii_mii_sel)
        self.sink = RgmiiSink(dut.rgmii_d, dut.rgmii_ctl, dut.clk, dut.rst, dut.rgmii_clk_en, dut.rgmii_mii_sel)

        dut.rgmii_clk_en.setimmediatevalue(1)
        dut.rgmii_mii_sel.setimmediatevalue(0)

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

    def set_enable_generator(self, generator=None):
        if self._enable_cr is not None:
            self._enable_cr.kill()
            self._enable_cr = None

        self._enable_generator = generator

        if self._enable_generator is not None:
            self._enable_cr = cocotb.start_soon(self._run_enable())

    def clear_enable_generator(self):
        self.set_enable_generator(None)

    async def _run_enable(self):
        clock_edge_event = RisingEdge(self.dut.clk)

        for val in self._enable_generator:
            self.dut.rgmii_clk_en.value = val
            await clock_edge_event


async def run_test(dut, payload_lengths=None, payload_data=None, ifg=12, enable_gen=None, mii_sel=False):

    tb = TB(dut)

    tb.source.ifg = ifg
    tb.dut.rgmii_mii_sel.value = mii_sel

    if enable_gen is not None:
        tb.set_enable_generator(enable_gen())

    await tb.reset()

    test_frames = [payload_data(x) for x in payload_lengths()]

    for test_data in test_frames:
        test_frame = GmiiFrame.from_payload(test_data)
        await tb.source.send(test_frame)

    for test_data in test_frames:
        rx_frame = await tb.sink.recv()

        assert rx_frame.get_payload() == test_data
        assert rx_frame.check_fcs()
        assert rx_frame.error is None

    assert tb.sink.empty()

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)


def size_list():
    return list(range(60, 128)) + [512, 1514, 9214] + [60]*10


def incrementing_payload(length):
    return bytearray(itertools.islice(itertools.cycle(range(256)), length))


def cycle_en():
    return itertools.cycle([0, 0, 0, 1])


if cocotb.SIM_NAME:

    factory = TestFactory(run_test)
    factory.add_option("payload_lengths", [size_list])
    factory.add_option("payload_data", [incrementing_payload])
    factory.add_option("ifg", [12, 0])
    factory.add_option(("enable_gen", "mii_sel"), [(None, False), (None, True), (cycle_en, True)])
    factory.generate_tests()


# cocotb-test

tests_dir = os.path.dirname(__file__)


def test_rgmii(request):
    dut = "test_rgmii"
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
