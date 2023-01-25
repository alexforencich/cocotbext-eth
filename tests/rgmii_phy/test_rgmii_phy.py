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

from cocotbext.eth import GmiiFrame, RgmiiSource, RgmiiSink, RgmiiPhy


class TB:
    def __init__(self, dut, speed=1000e6):
        self.dut = dut

        self.log = logging.getLogger("cocotb.tb")
        self.log.setLevel(logging.DEBUG)

        if speed == 1000e6:
            cocotb.start_soon(Clock(dut.phy_tx_clk, 8, units="ns").start())
        elif speed == 100e6:
            cocotb.start_soon(Clock(dut.phy_tx_clk, 40, units="ns").start())
        elif speed == 10e6:
            cocotb.start_soon(Clock(dut.phy_tx_clk, 400, units="ns").start())

        self.rgmii_phy = RgmiiPhy(dut.phy_txd, dut.phy_tx_ctl, dut.phy_tx_clk,
            dut.phy_rxd, dut.phy_rx_ctl, dut.phy_rx_clk, dut.phy_rst, speed=speed)

        self.source = RgmiiSource(dut.phy_txd, dut.phy_tx_ctl, dut.phy_tx_clk, dut.phy_rst)
        self.sink = RgmiiSink(dut.phy_rxd, dut.phy_rx_ctl, dut.phy_rx_clk, dut.phy_rst)

        if speed == 1000e6:
            self.source.mii_mode = False
            self.sink.mii_mode = False
        else:
            self.source.mii_mode = True
            self.sink.mii_mode = True

    async def reset(self):
        self.dut.phy_rst.setimmediatevalue(0)
        await RisingEdge(self.dut.phy_tx_clk)
        await RisingEdge(self.dut.phy_tx_clk)
        self.dut.phy_rst.value = 1
        await RisingEdge(self.dut.phy_tx_clk)
        await RisingEdge(self.dut.phy_tx_clk)
        self.dut.phy_rst.value = 0
        await RisingEdge(self.dut.phy_tx_clk)
        await RisingEdge(self.dut.phy_tx_clk)


async def run_test_tx(dut, payload_lengths=None, payload_data=None, ifg=12, speed=1000e6):

    tb = TB(dut, speed)

    tb.rgmii_phy.rx.ifg = ifg
    tb.source.ifg = ifg

    await tb.reset()

    test_frames = [payload_data(x) for x in payload_lengths()]

    for test_data in test_frames:
        test_frame = GmiiFrame.from_payload(test_data)
        await tb.source.send(test_frame)

    for test_data in test_frames:
        rx_frame = await tb.rgmii_phy.tx.recv()

        assert rx_frame.get_payload() == test_data
        assert rx_frame.check_fcs()
        assert rx_frame.error is None

    assert tb.rgmii_phy.tx.empty()

    await RisingEdge(dut.phy_tx_clk)
    await RisingEdge(dut.phy_tx_clk)


async def run_test_rx(dut, payload_lengths=None, payload_data=None, ifg=12, speed=1000e6):

    tb = TB(dut, speed)

    tb.rgmii_phy.rx.ifg = ifg
    tb.source.ifg = ifg

    await tb.reset()

    test_frames = [payload_data(x) for x in payload_lengths()]

    for test_data in test_frames:
        test_frame = GmiiFrame.from_payload(test_data)
        await tb.rgmii_phy.rx.send(test_frame)

    for test_data in test_frames:
        rx_frame = await tb.sink.recv()

        assert rx_frame.get_payload() == test_data
        assert rx_frame.check_fcs()
        assert rx_frame.error is None

    assert tb.sink.empty()

    await RisingEdge(dut.phy_rx_clk)
    await RisingEdge(dut.phy_rx_clk)


def size_list():
    return list(range(60, 128)) + [512, 1514] + [60]*10


def incrementing_payload(length):
    return bytearray(itertools.islice(itertools.cycle(range(256)), length))


def cycle_en():
    return itertools.cycle([0, 0, 0, 1])


if cocotb.SIM_NAME:

    for test in [run_test_tx, run_test_rx]:

        factory = TestFactory(test)
        factory.add_option("payload_lengths", [size_list])
        factory.add_option("payload_data", [incrementing_payload])
        factory.add_option("speed", [1000e6, 100e6, 10e6])
        factory.generate_tests()


# cocotb-test

tests_dir = os.path.dirname(__file__)


def test_rgmii_phy(request):
    dut = "test_rgmii_phy"
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
