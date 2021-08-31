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

import itertools
import logging
import os

import cocotb_test.simulator

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from cocotb.regression import TestFactory

from cocotbext.eth import EthMacFrame, EthMac, PtpClockSimTime
from cocotbext.axi import AxiStreamBus, AxiStreamSource, AxiStreamSink


class TB:
    def __init__(self, dut, speed=10e9):
        self.dut = dut

        self.log = logging.getLogger("cocotb.tb")
        self.log.setLevel(logging.DEBUG)

        cocotb.fork(Clock(dut.tx_clk, 6.4, units="ns").start())
        cocotb.fork(Clock(dut.rx_clk, 6.4, units="ns").start())

        self.mac = EthMac(
            tx_clk=dut.tx_clk,
            tx_rst=dut.tx_rst,
            tx_bus=AxiStreamBus.from_prefix(dut, "tx_axis"),
            tx_ptp_time=dut.tx_ptp_time,
            tx_ptp_ts=dut.tx_ptp_ts,
            tx_ptp_ts_tag=dut.tx_ptp_ts_tag,
            tx_ptp_ts_valid=dut.tx_ptp_ts_valid,
            rx_clk=dut.rx_clk,
            rx_rst=dut.rx_rst,
            rx_bus=AxiStreamBus.from_prefix(dut, "rx_axis"),
            rx_ptp_time=dut.rx_ptp_time,
            ifg=12, speed=speed
        )

        self.tx_ptp = PtpClockSimTime(
            ts_96=dut.tx_ptp_time,
            clock=dut.tx_clk
        )

        self.rx_ptp = PtpClockSimTime(
            ts_96=dut.rx_ptp_time,
            clock=dut.rx_clk
        )

        self.source = AxiStreamSource(AxiStreamBus.from_prefix(dut, "tx_axis"), dut.tx_clk, dut.tx_rst)
        self.sink = AxiStreamSink(AxiStreamBus.from_prefix(dut, "rx_axis"), dut.rx_clk, dut.rx_rst)

    async def reset(self):
        self.dut.tx_rst.setimmediatevalue(0)
        self.dut.rx_rst.setimmediatevalue(0)
        await RisingEdge(self.dut.tx_clk)
        await RisingEdge(self.dut.tx_clk)
        self.dut.tx_rst <= 1
        self.dut.rx_rst <= 1
        await RisingEdge(self.dut.tx_clk)
        await RisingEdge(self.dut.tx_clk)
        self.dut.tx_rst <= 0
        self.dut.rx_rst <= 0
        await RisingEdge(self.dut.tx_clk)
        await RisingEdge(self.dut.tx_clk)


async def run_test_tx(dut, payload_lengths=None, payload_data=None, ifg=12, speed=10e9):

    tb = TB(dut, speed)

    tb.mac.tx.ifg = ifg
    tb.mac.rx.ifg = ifg

    await tb.reset()

    test_frames = [payload_data(x) for x in payload_lengths()]

    for test_data in test_frames:
        test_frame = EthMacFrame.from_payload(test_data)
        await tb.source.send(test_frame)

    for test_data in test_frames:
        rx_frame = await tb.mac.tx.recv()

        assert rx_frame.get_payload() == test_data
        assert rx_frame.check_fcs()

    assert tb.mac.tx.empty()

    await RisingEdge(dut.tx_clk)
    await RisingEdge(dut.tx_clk)


async def run_test_rx(dut, payload_lengths=None, payload_data=None, ifg=12, speed=10e9):

    tb = TB(dut, speed)

    tb.mac.tx.ifg = ifg
    tb.mac.rx.ifg = ifg

    await tb.reset()

    test_frames = [payload_data(x) for x in payload_lengths()]

    for test_data in test_frames:
        test_frame = EthMacFrame.from_payload(test_data)
        await tb.mac.rx.send(test_frame)

    for test_data in test_frames:
        rx_frame = await tb.sink.recv()

        check_frame = EthMacFrame(rx_frame.tdata)

        assert check_frame.get_payload() == test_data
        assert check_frame.check_fcs()

    assert tb.sink.empty()

    await RisingEdge(dut.rx_clk)
    await RisingEdge(dut.rx_clk)


def size_list():
    return list(range(60, 128)) + [512, 1514, 9214] + [60]*10


def incrementing_payload(length):
    return bytearray(itertools.islice(itertools.cycle(range(256)), length))


if cocotb.SIM_NAME:

    for test in [run_test_tx, run_test_rx]:

        factory = TestFactory(test)
        factory.add_option("payload_lengths", [size_list])
        factory.add_option("payload_data", [incrementing_payload])
        factory.add_option("speed", [10e9, 1e9])
        factory.generate_tests()


# cocotb-test

tests_dir = os.path.dirname(__file__)


def test_eth_mac(request):
    dut = "test_eth_mac"
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
