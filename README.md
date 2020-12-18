# Ethernet interface modules for Cocotb

[![Build Status](https://github.com/alexforencich/cocotbext-eth/workflows/Regression%20Tests/badge.svg?branch=master)](https://github.com/alexforencich/cocotbext-eth/actions/)
[![codecov](https://codecov.io/gh/alexforencich/cocotbext-eth/branch/master/graph/badge.svg)](https://codecov.io/gh/alexforencich/cocotbext-eth)
[![PyPI version](https://badge.fury.io/py/cocotbext-eth.svg)](https://pypi.org/project/cocotbext-eth)

GitHub repository: https://github.com/alexforencich/cocotbext-eth

## Introduction

Ethernet interface models for [cocotb](https://github.com/cocotb/cocotb).

## Installation

Installation from pip (release version, stable):

    $ pip install cocotbext-eth

Installation from git (latest development version, potentially unstable):

    $ pip install https://github.com/alexforencich/cocotbext-eth/archive/master.zip

Installation for active development:

    $ git clone https://github.com/alexforencich/cocotbext-eth
    $ pip install -e cocotbext-eth

## Documentation and usage examples

See the `tests` directory and [verilog-ethernet](https://github.com/alexforencich/verilog-ethernet) for complete testbenches using these modules.

### GMII

The `GmiiSource` and `GmiiSink` classes can be used to drive, receive, and monitor GMII traffic.  The `GmiiSource` drives GMII traffic into a design.  The `GmiiSink` receives GMII traffic, including monitoring internal interfaces.

To use these modules, import the one you need and connect it to the DUT:

    from cocotbext.eth import GmiiSource, GmiiSink

    gmii_source = GmiiSource(dut.rxd, dut.rx_er, dut.rx_en, dut.clk, dut.rst)
    gmii_sink = GmiiSink(dut.txd, dut.tx_er, dut.tx_en, dut.clk, dut.rst)

To send data into a design with an `GmiiSource`, call `send()`.  Accepted data types are iterables that can be converted to bytearray or `GmiiFrame` objects.  Call `wait()` to wait for the transmit operation to complete.  Example:

    gmii_source.send(GmiiFrame.from_payload(b'test data'))
    await gmii_source.wait()

To receive data with a `GmiiSink`, call `recv()`.  Call `wait()` to wait for new receive data.

    await gmii_sink.wait()
    data = gmii_sink.recv()

#### Signals

* `txd`, `rxd`: data
* `tx_er`, `rx_er`: error (when asserted with `tx_en` or `rx_dv`)
* `tx_en`, `rx_dv`: data valid

#### Constructor parameters:

* _data_: data signal (txd, rxd, etc.)
* _er_: error signal (tx_er, rx_er, etc.) (optional)
* _dv_: data valid signal (tx_en, rx_dv, etc.)
* _clock_: clock signal
* _reset_: reset signal (optional)
* _enable_: clock enable (optional)
* _mii_select_: MII mode select (optional)

#### Attributes:

* _queue_occupancy_bytes_: number of bytes in queue
* _queue_occupancy_frames_: number of frames in queue

#### Methods

* `send(frame)`: send _frame_ (blocking) (source)
* `send_nowait(frame)`: send _frame_ (non-blocking) (source)
* `recv()`: receive a frame as a `GmiiFrame` (blocking) (sink)
* `recv_nowait()`: receive a frame as a `GmiiFrame` (non-blocking) (sink)
* `count()`: returns the number of items in the queue (all)
* `empty()`: returns _True_ if the queue is empty (all)
* `idle()`: returns _True_ if no transfer is in progress (all) or if the queue is not empty (source)
* `wait()`: wait for idle (source)
* `wait(timeout=0, timeout_unit='ns')`: wait for frame received (sink)

#### GmiiFrame object

The `GmiiFrame` object is a container for a frame to be transferred via GMII.  The `data` field contains the packet data in the form of a list of bytes.  `error` contains the `er` signal level state associated with each byte as a list of ints.

Attributes:

* `data`: bytearray
* `error`: error field, optional; list, each entry qualifies the corresponding entry in `data`.
* `rx_sim_time`: simulation time when packet was received by sink.

Methods:

* `from_payload(payload, min_len=60)`: create `GmiiFrame` from payload data, inserts preamble, zero-pads frame to minimum length and computes and inserts FCS (class method)
* `from_raw_payload(payload)`: create `GmiiFrame` from payload data, inserts preamble only (class method)
* `get_preamble_len()`: locate SFD and return preamble length
* `get_preamble()`: return preamble
* `get_payload(strip_fcs=True)`: return payload, optionally strip FCS
* `get_fcs()`: return FCS
* `check_fcs()`: returns _True_ if FCS is correct
* `normalize()`: pack `error` to the same length as `data`, replicating last element if necessary, initialize to list of `0` if not specified.
* `compact()`: remove `error` if all zero

### RGMII

The `RgmiiSource` and `RgmiiSink` classes can be used to drive, receive, and monitor RGMII traffic.  The `RgmiiSource` drives RGMII traffic into a design.  The `RgmiiSink` receives RGMII traffic, including monitoring internal interfaces.

To use these modules, import the one you need and connect it to the DUT:

    from cocotbext.eth import RgmiiSource, RgmiiSink

    rgmii_source = RgmiiSource(dut.rxd, dut.rx_ctl, dut.clk, dut.rst)
    rgmii_sink = RgmiiSink(dut.txd, dut.tx_ctl, dut.clk, dut.rst)

All signals must be passed separately into these classes.

To send data into a design with an `RgmiiSource`, call `send()`.  Accepted data types are iterables that can be converted to bytearray or `GmiiFrame` objects.  Call `wait()` to wait for the transmit operation to complete.  Example:

    rgmii_source.send(GmiiFrame.from_payload(b'test data'))
    await rgmii_source.wait()

To receive data with an `RgmiiSink`, call `recv()`.  Call `wait()` to wait for new receive data.

    await rgmii_sink.wait()
    data = rgmii_sink.recv()

#### Signals

* `txd`, `rxd`: data (DDR)
* `tx_ctl`, `rx_ctl`: control (DDR, combination of valid and error)

#### Constructor parameters:

* _data_: data signal (txd, rxd, etc.)
* _ctrl_: control
* _clock_: clock signal
* _reset_: reset signal (optional)
* _enable_: clock enable (optional)
* _mii_select_: MII mode select (optional)

#### Attributes:

* _queue_occupancy_bytes_: number of bytes in queue
* _queue_occupancy_frames_: number of frames in queue

#### Methods

* `send(frame)`: send _frame_ (blocking) (source)
* `send_nowait(frame)`: send _frame_ (non-blocking) (source)
* `recv()`: receive a frame as a `GmiiFrame` (blocking) (sink)
* `recv_nowait()`: receive a frame as a `GmiiFrame` (non-blocking) (sink)
* `count()`: returns the number of items in the queue (all)
* `empty()`: returns _True_ if the queue is empty (all)
* `idle()`: returns _True_ if no transfer is in progress (all) or if the queue is not empty (source)
* `wait()`: wait for idle (source)
* `wait(timeout=0, timeout_unit='ns')`: wait for frame received (sink)

### XGMII

The `XgmiiSource` and `XgmiiSink` classes can be used to drive, receive, and monitor XGMII traffic.  The `XgmiiSource` drives XGMII traffic into a design.  The `XgmiiSink` receives XGMII traffic, including monitoring internal interfaces.  The modules are capable of operating with XGMII interface widths of 32 or 64 bits.

To use these modules, import the one you need and connect it to the DUT:

    from cocotbext.eth import XgmiiSource, XgmiiSink

    xgmii_source = XgmiiSource(dut.rxd, dut.rxc, dut.clk, dut.rst)
    xgmii_sink = XgmiiSink(dut.txd, dut.txc, dut.clk, dut.rst)

All signals must be passed separately into these classes.

To send data into a design with an `XgmiiSource`, call `send()`.  Accepted data types are iterables that can be converted to bytearray or `XgmiiFrame` objects.  Call `wait()` to wait for the transmit operation to complete.  Example:

    xgmii_source.send(XgmiiFrame.from_payload(b'test data'))
    await xgmii_source.wait()

To receive data with an `XgmiiSink`, call `recv()`.  Call `wait()` to wait for new receive data.

    await xgmii_sink.wait()
    data = xgmii_sink.recv()

#### Signals

* `txd`, `rxd`: data
* `txc`, `rxc`: control

#### Constructor parameters:

* _data_: data signal (txd, rxd, etc.)
* _ctrl_: control signal (txc, rxc, etc.)
* _clock_: clock signal
* _reset_: reset signal (optional)
* _enable_: clock enable (optional)

#### Attributes:

* _queue_occupancy_bytes_: number of bytes in queue
* _queue_occupancy_frames_: number of frames in queue

#### Methods

* `send(frame)`: send _frame_ (blocking) (source)
* `send_nowait(frame)`: send _frame_ (non-blocking) (source)
* `recv()`: receive a frame as an `XgmiiFrame` (blocking) (sink)
* `recv_nowait()`: receive a frame as an `XgmiiFrame` (non-blocking) (sink)
* `count()`: returns the number of items in the queue (all)
* `empty()`: returns _True_ if the queue is empty (all)
* `idle()`: returns _True_ if no transfer is in progress (all) or if the queue is not empty (source)
* `wait()`: wait for idle (source)
* `wait(timeout=0, timeout_unit='ns')`: wait for frame received (sink)

#### XgmiiFrame object

The `XgmiiFrame` object is a container for a frame to be transferred via XGMII.  The `data` field contains the packet data in the form of a list of bytes.  `ctrl` contains the control signal level state associated with each byte as a list of ints.  When `ctrl` is high, the corresponding `data` byte is interpreted as an XGMII control character.

Attributes:

* `data`: bytearray
* `ctrl`: control field, optional; list, each entry qualifies the corresponding entry in `data` as an XGMII control character.
* `rx_sim_time`: simulation time when packet was received by sink.
* `rx_start_lane`: byte lane that the frame start control character was received in.

Methods:

* `from_payload(payload, min_len=60)`: create `XgmiiFrame` from payload data, inserts preamble, zero-pads frame to minimum length and computes and inserts FCS (class method)
* `from_raw_payload(payload)`: create `XgmiiFrame` from payload data, inserts preamble only (class method)
* `get_preamble_len()`: locate SFD and return preamble length
* `get_preamble()`: return preamble
* `get_payload(strip_fcs=True)`: return payload, optionally strip FCS
* `get_fcs()`: return FCS
* `check_fcs()`: returns _True_ if FCS is correct
* `normalize()`: pack `error` to the same length as `data`, replicating last element if necessary, initialize to list of `0` if not specified.
* `compact()`: remove `error` if all zero

### PTP clock

The `PtpClock` class implements a PTP hardware clock that produces IEEE 1588 format 96 and 64 bit PTP timestamps.

To use this module, import it and connect it to the DUT:

    from cocotbext.eth import PtpClock

    ptp_clock = PtpClock(
        ts_96=dut.ts_96,
        ts_64=dut.ts_64,
        ts_step=dut.ts_step,
        pps=dut.pps,
        clock=dut.clk,
        reset=dut.reset,
        period_ns=6.4
    )

Once the clock is instantiated, it will generate a continuous stream of monotonically increasing PTP timestamps on every clock edge.

#### Signals

* `ts_96`: 96-bit timestamp (48 bit seconds, 32 bit ns, 16 bit fractional ns)
* `ts_64`: 64-bit timestamp (48 bit ns, 16 bit fractional ns)
* `ts_step`: step output, pulsed when non-monotonic step occurs
* `pps`: pulse-per-second output, pulsed when ts_96 seconds field increments

#### Constructor parameters:

* _ts_96_: 96-bit timestamp signal (optional)
* _ts_64_: 64-bit timestamp signal (optional)
* _ts_step_: timestamp step signal (optional)
* _pps_: pulse-per-second signal (optional)
* _clock_: clock
* _reset_: reset (optional)
* _period_ns_: clock period (nanoseconds)

#### Attributes:

* _ts_96_s_: current 96-bit timestamp seconds field
* _ts_96_ns_: current 96-bit timestamp ns field
* _ts_96_fns_: current 96-bit timestamp fractional ns field
* _ts_64_ns_: current 64-bit timestamp ns field
* _ts_64_fns_: current 64-bit timestamp fractional ns field

#### Methods

* `set_period(ns, fns)`: set clock period from separate fields
* `set_drift(ns, fns, rate)`: set clock drift from separate fields
* `set_period_ns(t)`: set clock period in ns (float)
* `get_period_ns()`: return current clock period in ns (float)
* `set_ts_96(ts_s, ts_ns=None, ts_fns=None)`: set 96-bit timestamp from integer or from separate fields
* `set_ts_96_ns(t)`: set 96-bit timestamp from ns (float)
* `set_ts_96_s(t)`: set 96-bit timestamp from seconds (float)
* `get_ts_96()`: return current 96-bit timestamp as an integer
* `get_ts_96_ns()`: return current 96-bit timestamp in ns (float)
* `get_ts_96_s()`: return current 96-bit timestamp in seconds (float)
* `set_ts_64(ts_ns, ts_fns=None)`: set 64-bit timestamp from integer or from separate fields
* `set_ts_64_ns(t)`: set 64-bit timestamp from ns (float)
* `set_ts_64_s(t)`: set 64-bit timestamp from seconds (float)
* `get_ts_64()`: return current 64-bit timestamp as an integer
* `get_ts_64_ns()`: return current 64-bit timestamp in ns (float)
* `get_ts_64_s()`: return current 64-bit timestamp in seconds (float)
