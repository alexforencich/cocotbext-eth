# Ethernet interface modules for Cocotb

[![Build Status](https://github.com/alexforencich/cocotbext-eth/workflows/Regression%20Tests/badge.svg?branch=master)](https://github.com/alexforencich/cocotbext-eth/actions/)
[![codecov](https://codecov.io/gh/alexforencich/cocotbext-eth/branch/master/graph/badge.svg)](https://codecov.io/gh/alexforencich/cocotbext-eth)
[![PyPI version](https://badge.fury.io/py/cocotbext-eth.svg)](https://pypi.org/project/cocotbext-eth)
[![Downloads](https://pepy.tech/badge/cocotbext-eth)](https://pepy.tech/project/cocotbext-eth)

GitHub repository: https://github.com/alexforencich/cocotbext-eth

## Introduction

Ethernet interface models for [cocotb](https://github.com/cocotb/cocotb).

Includes PHY-attach interface models for MII, GMII, RGMII, and XGMII; PHY chip interface models for MII, GMII, and RGMII; PTP clock simulation models; and a generic Ethernet MAC model that supports rate enforcement and PTP timestamping.

## Installation

Installation from pip (release version, stable):

    $ pip install cocotbext-eth

Installation from git (latest development version, potentially unstable):

    $ pip install https://github.com/alexforencich/cocotbext-eth/archive/master.zip

Installation for active development:

    $ git clone https://github.com/alexforencich/cocotbext-eth
    $ pip install -e cocotbext-eth

## Documentation and usage examples

See the `tests` directory, [verilog-ethernet](https://github.com/alexforencich/verilog-ethernet), and [corundum](https://github.com/corundum/corundum) for complete testbenches using these modules.

### GMII

The `GmiiSource` and `GmiiSink` classes can be used to drive, receive, and monitor GMII traffic.  The `GmiiSource` drives GMII traffic into a design.  The `GmiiSink` receives GMII traffic, including monitoring internal interfaces.  The `GmiiPhy` class is a wrapper around `GmiiSource` and `GmiiSink` that also provides clocking and rate-switching to emulate a GMII PHY chip.

To use these modules, import the one you need and connect it to the DUT:

    from cocotbext.eth import GmiiSource, GmiiSink

    gmii_source = GmiiSource(dut.rxd, dut.rx_er, dut.rx_en, dut.clk, dut.rst)
    gmii_sink = GmiiSink(dut.txd, dut.tx_er, dut.tx_en, dut.clk, dut.rst)

To send data into a design with a `GmiiSource`, call `send()` or `send_nowait()`.  Accepted data types are iterables that can be converted to bytearray or `GmiiFrame` objects.  Optionally, call `wait()` to wait for the transmit operation to complete.  Example:

    await gmii_source.send(GmiiFrame.from_payload(b'test data'))
    # wait for operation to complete (optional)
    await gmii_source.wait()

It is also possible to wait for the transmission of a specific frame to complete by passing an event in the tx_complete field of the `GmiiFrame` object, and then awaiting the event.  The frame, with simulation time fields set, will be returned in the event data.  Example:

    frame = GmiiFrame.from_payload(b'test data', tx_complete=Event())
    await gmii_source.send(frame)
    await frame.tx_complete.wait()
    print(frame.tx_complete.data.sim_time_sfd)

To receive data with a `GmiiSink`, call `recv()` or `recv_nowait()`.  Optionally call `wait()` to wait for new receive data.

    data = await gmii_sink.recv()

The `GmiiPhy` class provides a model of a GMII PHY chip.  It wraps instances of `GmiiSource` (`rx`) and `GmiiSink` (`tx`), provides the necessary clocking components, and provides the `set_speed()` method to change the link speed.  `set_speed()` changes the `tx_clk` and `rx_clk` frequencies, switches between `gtx_clk` and `tx_clk`, and selects the appropriate mode (MII or GMII) on the source and sink instances.  In general, the `GmiiPhy` class is intended to be used for integration tests where the design expects to be directly connected to an external GMII PHY chip and contains all of the necessary IO and clocking logic.  Example:

    from cocotbext.eth import GmiiFrame, GmiiPhy

    gmii_phy = GmiiPhy(dut.txd, dut.tx_er, dut.tx_en, dut.tx_clk, dut.gtx_clk,
        dut.rxd, dut.rx_er, dut.rx_en, dut.rx_clk, dut.rst, speed=1000e6)

    gmii_phy.set_speed(100e6)

    await gmii_phy.rx.send(GmiiFrame.from_payload(b'test RX data'))
    tx_data = await gmii_phy.tx.recv()

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
* _reset_active_level_: reset active level (optional, default `True`)

#### Attributes:

* _queue_occupancy_bytes_: number of bytes in queue
* _queue_occupancy_frames_: number of frames in queue
* _queue_occupancy_limit_bytes_: max number of bytes in queue allowed before backpressure is applied (source only)
* _queue_occupancy_limit_frames_: max number of frames in queue allowed before backpressure is applied (source only)
* _mii_mode_: control MII mode when _mii_select_ signal is not connected

#### Methods

* `send(frame)`: send _frame_ (blocking) (source)
* `send_nowait(frame)`: send _frame_ (non-blocking) (source)
* `recv()`: receive a frame as a `GmiiFrame` (blocking) (sink)
* `recv_nowait()`: receive a frame as a `GmiiFrame` (non-blocking) (sink)
* `count()`: returns the number of items in the queue (all)
* `empty()`: returns _True_ if the queue is empty (all)
* `full()`: returns _True_ if the queue occupancy limits are met (source)
* `idle()`: returns _True_ if no transfer is in progress (all) or if the queue is not empty (source)
* `clear()`: drop all data in queue (all)
* `wait()`: wait for idle (source)
* `wait(timeout=0, timeout_unit='ns')`: wait for frame received (sink)

#### GMII timing diagram

Example transfer via GMII at 1 Gbps:

                  __    __    __    __    _       __    __    __    __
    tx_clk     __/  \__/  \__/  \__/  \__/  ... _/  \__/  \__/  \__/  \__
                        _____ _____ _____ _     _ _____ _____
    tx_d[7:0]  XXXXXXXXX_55__X_55__X_55__X_ ... _X_72__X_fb__XXXXXXXXXXXX

    tx_er      ____________________________ ... _________________________
                        ___________________     _____________
    tx_en      ________/                    ...              \___________


#### GmiiFrame object

The `GmiiFrame` object is a container for a frame to be transferred via GMII.  The `data` field contains the packet data in the form of a list of bytes.  `error` contains the `er` signal level state associated with each byte as a list of ints.

Attributes:

* `data`: bytearray
* `error`: error field, optional; list, each entry qualifies the corresponding entry in `data`.
* `sim_time_start`: simulation time of first transfer cycle of frame.
* `sim_time_sfd`: simulation time at which the SFD was transferred.
* `sim_time_end`: simulation time of last transfer cycle of frame.
* `start_lane`: byte lane in which the start control character was transferred.
* `tx_complete`: event or callable triggered when frame is transmitted.

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

### MII

The `MiiSource` and `MiiSink` classes can be used to drive, receive, and monitor MII traffic.  The `MiiSource` drives MII traffic into a design.  The `MiiSink` receives MII traffic, including monitoring internal interfaces.  The `MiiPhy` class is a wrapper around `MiiSource` and `MiiSink` that also provides clocking and rate-switching to emulate an MII PHY chip.

To use these modules, import the one you need and connect it to the DUT:

    from cocotbext.eth import MiiSource, MiiSink

    mii_source = MiiSource(dut.rxd, dut.rx_er, dut.rx_en, dut.clk, dut.rst)
    mii_sink = MiiSink(dut.txd, dut.tx_er, dut.tx_en, dut.clk, dut.rst)

All signals must be passed separately into these classes.

To send data into a design with an `MiiSource`, call `send()` or `send_nowait()`.  Accepted data types are iterables that can be converted to bytearray or `GmiiFrame` objects.  Optionally, call `wait()` to wait for the transmit operation to complete.  Example:

    await mii_source.send(GmiiFrame.from_payload(b'test data'))
    # wait for operation to complete (optional)
    await mii_source.wait()

It is also possible to wait for the transmission of a specific frame to complete by passing an event in the tx_complete field of the `GmiiFrame` object, and then awaiting the event.  The frame, with simulation time fields set, will be returned in the event data.  Example:

    frame = GmiiFrame.from_payload(b'test data', tx_complete=Event())
    await mii_source.send(frame)
    await frame.tx_complete.wait()
    print(frame.tx_complete.data.sim_time_sfd)

To receive data with an `MiiSink`, call `recv()` or `recv_nowait()`.  Optionally call `wait()` to wait for new receive data.

    data = await mii_sink.recv()

The `MiiPhy` class provides a model of an MII PHY chip.  It wraps instances of `MiiSource` (`rx`) and `MiiSink` (`tx`), provides the necessary clocking components, and provides the `set_speed()` method to change the link speed.  `set_speed()` changes the `tx_clk` and `rx_clk` frequencies.  In general, the `MiiPhy` class is intended to be used for integration tests where the design expects to be directly connected to an external MII PHY chip and contains all of the necessary IO and clocking logic.  Example:

    from cocotbext.eth import GmiiFrame, MiiPhy

    mii_phy = MiiPhy(dut.txd, dut.tx_er, dut.tx_en, dut.tx_clk,
        dut.rxd, dut.rx_er, dut.rx_en, dut.rx_clk, dut.rst, speed=100e6)

    mii_phy.set_speed(10e6)

    await mii_phy.rx.send(GmiiFrame.from_payload(b'test RX data'))
    tx_data = await mii_phy.tx.recv()

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
* _reset_active_level_: reset active level (optional, default `True`)

#### Attributes:

* _queue_occupancy_bytes_: number of bytes in queue
* _queue_occupancy_frames_: number of frames in queue
* _queue_occupancy_limit_bytes_: max number of bytes in queue allowed before backpressure is applied (source only)
* _queue_occupancy_limit_frames_: max number of frames in queue allowed before backpressure is applied (source only)

#### Methods

* `send(frame)`: send _frame_ (blocking) (source)
* `send_nowait(frame)`: send _frame_ (non-blocking) (source)
* `recv()`: receive a frame as a `GmiiFrame` (blocking) (sink)
* `recv_nowait()`: receive a frame as a `GmiiFrame` (non-blocking) (sink)
* `count()`: returns the number of items in the queue (all)
* `empty()`: returns _True_ if the queue is empty (all)
* `full()`: returns _True_ if the queue occupancy limits are met (source)
* `idle()`: returns _True_ if no transfer is in progress (all) or if the queue is not empty (source)
* `clear()`: drop all data in queue (all)
* `wait()`: wait for idle (source)
* `wait(timeout=0, timeout_unit='ns')`: wait for frame received (sink)

#### MII timing diagram

Example transfer via MII at 100 Mbps:

                 _   _   _   _   _   _       _   _   _   _
    tx_clk     _/ \_/ \_/ \_/ \_/ \_/  ... _/ \_/ \_/ \_/ \_
                     ___ ___ ___ ___ _     _ ___ ___
    tx_d[3:0]  XXXXXX_5_X_5_X_5_X_5_X_ ... _X_f_X_b_XXXXXXXX

    tx_er      _______________________ ... _________________
                     _________________     _________
    tx_en      _____/                  ...          \_______


### RGMII

The `RgmiiSource` and `RgmiiSink` classes can be used to drive, receive, and monitor RGMII traffic.  The `RgmiiSource` drives RGMII traffic into a design.  The `RgmiiSink` receives RGMII traffic, including monitoring internal interfaces.  The `RgmiiPhy` class is a wrapper around `RgmiiSource` and `RgmiiSink` that also provides clocking and rate-switching to emulate an RGMII PHY chip.

To use these modules, import the one you need and connect it to the DUT:

    from cocotbext.eth import RgmiiSource, RgmiiSink

    rgmii_source = RgmiiSource(dut.rxd, dut.rx_ctl, dut.clk, dut.rst)
    rgmii_sink = RgmiiSink(dut.txd, dut.tx_ctl, dut.clk, dut.rst)

All signals must be passed separately into these classes.

To send data into a design with an `RgmiiSource`, call `send()` or `send_nowait()`.  Accepted data types are iterables that can be converted to bytearray or `GmiiFrame` objects.  Optionally, call `wait()` to wait for the transmit operation to complete.  Example:

    await rgmii_source.send(GmiiFrame.from_payload(b'test data'))
    # wait for operation to complete (optional)
    await rgmii_source.wait()

It is also possible to wait for the transmission of a specific frame to complete by passing an event in the tx_complete field of the `GmiiFrame` object, and then awaiting the event.  The frame, with simulation time fields set, will be returned in the event data.  Example:

    frame = GmiiFrame.from_payload(b'test data', tx_complete=Event())
    await rgmii_source.send(frame)
    await frame.tx_complete.wait()
    print(frame.tx_complete.data.sim_time_sfd)

To receive data with an `RgmiiSink`, call `recv()` or `recv_nowait()`.  Optionally call `wait()` to wait for new receive data.

    data = await rgmii_sink.recv()

The `RgmiiPhy` class provides a model of an RGMII PHY chip.  It wraps instances of `RgmiiSource` (`rx`) and `RgmiiSink` (`tx`), provides the necessary clocking components, and provides the `set_speed()` method to change the link speed.  `set_speed()` changes the `rx_clk` frequency and selects the appropriate mode (SDR or DDR) on the source and sink instances.  In general, the `RgmiiPhy` class is intended to be used for integration tests where the design expects to be directly connected to an external RGMII PHY chip and contains all of the necessary IO and clocking logic.  Example:

    from cocotbext.eth import GmiiFrame, RgmiiPhy

    rgmii_phy = RgmiiPhy(dut.txd, dut.tx_ctl, dut.tx_clk,
        dut.rxd, dut.rx_ctl, dut.rx_clk, dut.rst, speed=1000e6)

    rgmii_phy.set_speed(100e6)

    await rgmii_phy.rx.send(GmiiFrame.from_payload(b'test RX data'))
    tx_data = await rgmii_phy.tx.recv()

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
* _reset_active_level_: reset active level (optional, default `True`)

#### Attributes:

* _queue_occupancy_bytes_: number of bytes in queue
* _queue_occupancy_frames_: number of frames in queue
* _queue_occupancy_limit_bytes_: max number of bytes in queue allowed before backpressure is applied (source only)
* _queue_occupancy_limit_frames_: max number of frames in queue allowed before backpressure is applied (source only)
* _mii_mode_: control MII mode when _mii_select_ signal is not connected

#### Methods

* `send(frame)`: send _frame_ (blocking) (source)
* `send_nowait(frame)`: send _frame_ (non-blocking) (source)
* `recv()`: receive a frame as a `GmiiFrame` (blocking) (sink)
* `recv_nowait()`: receive a frame as a `GmiiFrame` (non-blocking) (sink)
* `count()`: returns the number of items in the queue (all)
* `empty()`: returns _True_ if the queue is empty (all)
* `full()`: returns _True_ if the queue occupancy limits are met (source)
* `idle()`: returns _True_ if no transfer is in progress (all) or if the queue is not empty (source)
* `clear()`: drop all data in queue (all)
* `wait()`: wait for idle (source)
* `wait(timeout=0, timeout_unit='ns')`: wait for frame received (sink)

#### RGMII timing diagram

Example transfer via RGMII at 1 Gbps:

                 ___     ___     ___     _       ___     ___
    tx_clk     _/   \___/   \___/   \___/  ... _/   \___/   \___
                       ___ ___ ___ ___ ___     ___ ___
    tx_d[3:0]  XXXXXXXX_5_X_5_X_5_X_5_X_5_ ... _f_X_b_XXXXXXXXXX
                       ___________________     _______
    tx_ctl     _______/                    ...        \_________


### XGMII

The `XgmiiSource` and `XgmiiSink` classes can be used to drive, receive, and monitor XGMII traffic.  The `XgmiiSource` drives XGMII traffic into a design.  The `XgmiiSink` receives XGMII traffic, including monitoring internal interfaces.  The modules are capable of operating with XGMII interface widths of 32 or 64 bits.

To use these modules, import the one you need and connect it to the DUT:

    from cocotbext.eth import XgmiiSource, XgmiiSink

    xgmii_source = XgmiiSource(dut.rxd, dut.rxc, dut.clk, dut.rst)
    xgmii_sink = XgmiiSink(dut.txd, dut.txc, dut.clk, dut.rst)

All signals must be passed separately into these classes.

To send data into a design with an `XgmiiSource`, call `send()` or `send_nowait()`.  Accepted data types are iterables that can be converted to bytearray or `XgmiiFrame` objects.  Optionally, call `wait()` to wait for the transmit operation to complete.  Example:

    await xgmii_source.send(XgmiiFrame.from_payload(b'test data'))
    # wait for operation to complete (optional)
    await xgmii_source.wait()

It is also possible to wait for the transmission of a specific frame to complete by passing an event in the tx_complete field of the `XgmiiFrame` object, and then awaiting the event.  The frame, with simulation time fields set, will be returned in the event data.  Example:

    frame = XgmiiFrame.from_payload(b'test data', tx_complete=Event())
    await xgmii_source.send(frame)
    await frame.tx_complete.wait()
    print(frame.tx_complete.data.sim_time_sfd)

To receive data with an `XgmiiSink`, call `recv()` or `recv_nowait()`.  Optionally call `wait()` to wait for new receive data.

    data = await xgmii_sink.recv()

#### Signals

* `txd`, `rxd`: data
* `txc`, `rxc`: control

#### Constructor parameters:

* _data_: data signal (txd, rxd, etc.)
* _ctrl_: control signal (txc, rxc, etc.)
* _clock_: clock signal
* _reset_: reset signal (optional)
* _enable_: clock enable (optional)
* _reset_active_level_: reset active level (optional, default `True`)

#### Attributes:

* _queue_occupancy_bytes_: number of bytes in queue
* _queue_occupancy_frames_: number of frames in queue
* _queue_occupancy_limit_bytes_: max number of bytes in queue allowed before backpressure is applied (source only)
* _queue_occupancy_limit_frames_: max number of frames in queue allowed before backpressure is applied (source only)

#### Methods

* `send(frame)`: send _frame_ (blocking) (source)
* `send_nowait(frame)`: send _frame_ (non-blocking) (source)
* `recv()`: receive a frame as an `XgmiiFrame` (blocking) (sink)
* `recv_nowait()`: receive a frame as an `XgmiiFrame` (non-blocking) (sink)
* `count()`: returns the number of items in the queue (all)
* `empty()`: returns _True_ if the queue is empty (all)
* `full()`: returns _True_ if the queue occupancy limits are met (source)
* `idle()`: returns _True_ if no transfer is in progress (all) or if the queue is not empty (source)
* `clear()`: drop all data in queue (all)
* `wait()`: wait for idle (source)
* `wait(timeout=0, timeout_unit='ns')`: wait for frame received (sink)

#### XGMII timing diagram

Example transfer via 64-bit XGMII:

                  __    __    __    __    __    _       __    __
    tx_clk     __/  \__/  \__/  \__/  \__/  \__/  ... _/  \__/  \__
               __ _____ _____ _____ _____ _____ _     _ _____ _____
    txd[63:56] __X_07__X_d5__X_51__X_01__X_09__X_ ... _X_fb__X_07__
               __ _____ _____ _____ _____ _____ _     _ _____ _____
    txd[55:48] __X_07__X_55__X_5a__X_00__X_08__X_ ... _X_72__X_07__
               __ _____ _____ _____ _____ _____ _     _ _____ _____
    txd[47:40] __X_07__X_55__X_d5__X_00__X_07__X_ ... _X_0d__X_07__
               __ _____ _____ _____ _____ _____ _     _ _____ _____
    txd[39:32] __X_07__X_55__X_d4__X_80__X_06__X_ ... _X_37__X_07__
               __ _____ _____ _____ _____ _____ _     _ _____ _____
    txd[31:24] __X_07__X_55__X_d3__X_55__X_05__X_ ... _X_2d__X_07__
               __ _____ _____ _____ _____ _____ _     _ _____ _____
    txd[23:16] __X_07__X_55__X_d2__X_54__X_04__X_ ... _X_2c__X_07__
               __ _____ _____ _____ _____ _____ _     _ _____ _____
    txd[15:8]  __X_07__X_55__X_d1__X_53__X_03__X_ ... _X_2b__X_07__
               __ _____ _____ _____ _____ _____ _     _ _____ _____
    txd[7:0]   __X_07__X_fb__X_da__X_52__X_02__X_ ... _X_2a__X_fd__
               __ _____ _____ _____ _____ _____ _     _ _____ _____
    txc[7:0]   __X_ff__X_01__X_00__X_00__X_00__X_ ... _X_00__X_ff__


#### XgmiiFrame object

The `XgmiiFrame` object is a container for a frame to be transferred via XGMII.  The `data` field contains the packet data in the form of a list of bytes.  `ctrl` contains the control signal level state associated with each byte as a list of ints.  When `ctrl` is high, the corresponding `data` byte is interpreted as an XGMII control character.

Attributes:

* `data`: bytearray
* `ctrl`: control field, optional; list, each entry qualifies the corresponding entry in `data` as an XGMII control character.
* `sim_time_start`: simulation time of first transfer cycle of frame.
* `sim_time_sfd`: simulation time at which the SFD was transferred.
* `sim_time_end`: simulation time of last transfer cycle of frame.
* `start_lane`: byte lane in which the start control character was transferred.
* `tx_complete`: event or callable triggered when frame is transmitted.

Methods:

* `from_payload(payload, min_len=60)`: create `XgmiiFrame` from payload data, inserts preamble, zero-pads frame to minimum length and computes and inserts FCS (class method)
* `from_raw_payload(payload)`: create `XgmiiFrame` from payload data, inserts preamble only (class method)
* `get_preamble_len()`: locate SFD and return preamble length
* `get_preamble()`: return preamble
* `get_payload(strip_fcs=True)`: return payload, optionally strip FCS
* `get_fcs()`: return FCS
* `check_fcs()`: returns _True_ if FCS is correct
* `normalize()`: pack `ctrl` to the same length as `data`, replicating last element if necessary, initialize to list of `0` if not specified.
* `compact()`: remove `ctrl` if all zero

### Ethernet MAC model

The `EthMac`, `EthMacTx` and `EthMacRx` modules are models of an Ethernet MAC with an AXI stream interface.  The `EthMacRx` module drives Ethernet frames in the form of AXI stream traffic into a design.  The `EthMacTx` module accepts Ethernet frames in the form of AXI stream traffic from a design.  `EthMac` is a wrapper module containing `EthMacRx` (`rx`) and `EthMacTx` (`tx`).  The modules are capable of operating with any interface width.  The MAC models enforce the correct data rates and timings in both the receive and transmit direction, and can also collect PTP timestamps from a PTP hardware clock.

To use these modules, import the one you need and connect it to the DUT:

    from cocotbext.axi import AxiStreamBus
    from cocotbext.eth import EthMac

    mac = EthMac(
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

To send data into a design, call `send()` or `send_nowait()`.  Accepted data types are iterables that can be converted to bytearray or `EthMacFrame` objects.  Optionally, call `wait()` to wait for the transmit operation to complete.  Example:

    await mac.tx.send(EthMacFrame.from_payload(b'test data'))
    # wait for operation to complete (optional)
    await mac.tx.wait()

It is also possible to wait for the transmission of a specific frame to complete by passing an event in the tx_complete field of the `EthMacFrame` object, and then awaiting the event.  The frame, with simulation time fields set, will be returned in the event data.  Example:

    frame = EthMacFrame.from_payload(b'test data', tx_complete=Event())
    await mac.tx.send(frame)
    await frame.tx_complete.wait()
    print(frame.tx_complete.data.sim_time_sfd)

To receive data, call `recv()` or `recv_nowait()`.  Optionally call `wait()` to wait for new receive data.

    data = await mac.tx.recv()

PTP timestamping requires free-running PTP clocks driving the PTP time inputs, synchronous with the corresponding MAC clocks.  The values of these fields are then captured when the frame SFD is transferred and returned either on tuser (for received frames) or on a separate streaming interface (for transmitted frames).  Additionally, on the transmit path, a tag value from tuser is returned along with the timestamp.

#### Signals

* `tdata`: payload data, must be a multiple of 8 bits
* `tvalid`: qualifies all other signals
* `tready`: indicates sink is ready for data (tx only)
* `tlast`: marks the last cycle of a frame
* `tkeep`: qualifies data byte, data bus width must be evenly divisible by `tkeep` signal width
* `tuser`: user data, carries frame error mark and captured receive PTP timestamp (RX) or PTP timestamp tag (TX)
* `ptp_time`: PTP time input from PHC, captured into `ptp_timestamp` field coincident with transfer of frame SFD and output on `ptp_ts` (TX) or `tuser` (RX)
* `ptp_ts`: captured transmit PTP timestamp
* `ptp_ts_tag`: captured transmit PTP timestamp tag
* `ptp_ts_valid`: qualifies captured transmit PTP timestamp

#### Constructor parameters (`EthMacRx` and `EthMacTx`):

* _bus_: `AxiStreamBus` object containing AXI stream interface signals
* _clock_: clock signal
* _reset_: reset signal (optional)
* _ptp_time_: PTP time input from PHC (optional)
* _ptp_ts_: PTP timestamp (optional) (tx)
* _ptp_ts_tag_: PTP timestamp tag (optional) (tx)
* _ptp_ts_valid_: PTP timestamp valid (optional) (tx)
* _reset_active_level_: reset active level (optional, default `True`)
* _ifg_: IFG size in byte times (optional, default `12`)
* _speed_: link speed in bits per second (optional, default `1000e6`)

#### Constructor parameters (`EthMac`):

* _tx_bus_: `AxiStreamBus` object containing transmit AXI stream interface signals
* _tx_clk_: transmit clock
* _tx_rst_: transmit reset (optional)
* _tx_ptp_time_: transmit PTP time input from PHC (optional)
* _tx_ptp_ts_: transmit PTP timestamp (optional)
* _tx_ptp_ts_tag_: transmit PTP timestamp tag (optional)
* _tx_ptp_ts_valid_: transmit PTP timestamp valid (optional)
* _rx_bus_: `AxiStreamBus` object containing receive AXI stream interface signals
* _rx_clk_: receive clock
* _rx_rst_: receive reset (optional)
* _rx_ptp_time_: receive PTP time input from PHC (optional)
* _reset_active_level_: reset active level (optional, default `True`)
* _ifg_: IFG size in byte times (optional, default `12`)
* _speed_: link speed in bits per second (optional, default `1000e6`)

#### Attributes:

* _queue_occupancy_bytes_: number of bytes in queue
* _queue_occupancy_frames_: number of frames in queue
* _queue_occupancy_limit_bytes_: max number of bytes in queue allowed before backpressure is applied (RX only)
* _queue_occupancy_limit_frames_: max number of frames in queue allowed before backpressure is applied (RX only)
* _ifg_: IFG size in byte times
* _speed_: link speed in bits per second

#### Methods

* `send(frame)`: send _frame_ (blocking) (rx)
* `send_nowait(frame)`: send _frame_ (non-blocking) (rx)
* `recv()`: receive a frame as an `EthMacFrame` (blocking) (tx)
* `recv_nowait()`: receive a frame as an `EthMacFrame` (non-blocking) (tx)
* `count()`: returns the number of items in the queue (all)
* `empty()`: returns _True_ if the queue is empty (all)
* `full()`: returns _True_ if the queue occupancy limits are met (rx)
* `idle()`: returns _True_ if no transfer is in progress (all) or if the queue is not empty (rx)
* `clear()`: drop all data in queue (all)
* `wait()`: wait for idle (rx)
* `wait(timeout=0, timeout_unit='ns')`: wait for frame received (tx)

#### EthMacFrame object

The `EthMacFrame` object is a container for a frame to be transferred via XGMII.  The `data` field contains the packet data in the form of a list of bytes.

Attributes:

* `data`: bytearray
* `sim_time_start`: simulation time of first transfer cycle of frame.
* `sim_time_sfd`: simulation time at which the SFD was transferred.
* `sim_time_end`: simulation time of last transfer cycle of frame.
* `ptp_tag`: PTP timestamp tag for transmitted frames.
* `ptp_timestamp`: captured value of `ptp_time` at frame SFD
* `tx_complete`: event or callable triggered when frame is transmitted.

Methods:

* `from_payload(payload, min_len=60)`: create `EthMacFrame` from payload data, zero-pads frame to minimum length and computes and inserts FCS (class method)
* `from_raw_payload(payload)`: create `EthMacFrame` from payload data (class method)
* `get_payload(strip_fcs=True)`: return payload, optionally strip FCS
* `get_fcs()`: return FCS
* `check_fcs()`: returns _True_ if FCS is correct

### PTP clock

The `PtpClock` class implements a PTP hardware clock that produces IEEE 1588 format 96-bit time-of-day and 64-bit relative PTP timestamps.

To use this module, import it and connect it to the DUT:

    from cocotbext.eth import PtpClock

    ptp_clock = PtpClock(
        ts_tod=dut.ts_tod,
        ts_rel=dut.ts_rel,
        ts_step=dut.ts_step,
        pps=dut.pps,
        clock=dut.clk,
        reset=dut.reset,
        period_ns=6.4
    )

Once the clock is instantiated, it will generate a continuous stream of monotonically increasing PTP timestamps on every clock edge.

Internally, the `PtpClock` module uses 32-bit fractional ns fields for higher frequency resolution.  Only the upper 16 bits are returned in the timestamps, but the full fns value can be accessed with the _ts_tod_fns_ and _ts_rel_fns_ attributes.

All APIs that handle fractional values use the `Decimal` type for maximum precision, as the combination of timestamp range and resolution is usually too much for normal floating point numbers to handle without significant loss of precision.

#### Signals

* `ts_tod`: 96-bit time-of-day timestamp (48 bit seconds, 32 bit ns, 16 bit fractional ns)
* `ts_rel`: 64-bit relative timestamp (48 bit ns, 16 bit fractional ns)
* `ts_step`: step output, pulsed when non-monotonic step occurs
* `pps`: pulse-per-second output, pulsed when ts_tod seconds field increments

#### Constructor parameters:

* _ts_tod_: 96-bit time-of-day timestamp signal (optional)
* _ts_rel_: 64-bit relative timestamp signal (optional)
* _ts_step_: timestamp step signal (optional)
* _pps_: pulse-per-second signal (optional)
* _clock_: clock
* _reset_: reset (optional)
* _reset_active_level_: reset active level (optional, default `True`)
* _period_ns_: clock period (nanoseconds, default `6.4`)

#### Attributes:

* _ts_tod_s_: current 96-bit ToD timestamp seconds field
* _ts_tod_ns_: current 96-bit ToD timestamp ns field
* _ts_tod_fns_: current 96-bit ToD timestamp fractional ns field
* _ts_rel_ns_: current 64-bit relative timestamp ns field
* _ts_rel_fns_: current 64-bit relative timestamp fractional ns field

#### Methods

* `set_period(ns, fns)`: set clock period from separate fields
* `set_drift(num, denom)`: set clock drift from separate fields
* `set_period_ns(t)`: set clock period and drift in ns (Decimal)
* `get_period_ns()`: return current clock period in ns (Decimal)
* `set_ts_tod(ts_s, ts_ns, ts_fns)`: set 96-bit ToD timestamp from separate fields
* `set_ts_tod_96(ts)`: set 96-bit ToD timestamp from integer
* `set_ts_tod_ns(t)`: set 96-bit ToD timestamp from ns (Decimal)
* `set_ts_tod_s(t)`: set 96-bit ToD timestamp from seconds (Decimal)
* `set_ts_tod_sim_time()`: set 96-bit ToD timestamp from sim time
* `get_ts_tod()`: return current 96-bit ToD timestamp as separate fields
* `get_ts_tod_96()`: return current 96-bit ToD timestamp as an integer
* `get_ts_tod_ns()`: return current 96-bit ToD timestamp in ns (Decimal)
* `get_ts_tod_s()`: return current 96-bit ToD timestamp in seconds (Decimal)
* `set_ts_rel(ts_ns, ts_fns)`: set 64-bit relative timestamp from separate fields
* `set_ts_rel_64(ts)`: set 64-bit relative timestamp from integer
* `set_ts_rel_ns(t)`: set 64-bit relative timestamp from ns (Decimal)
* `set_ts_rel_s(t)`: set 64-bit relative timestamp from seconds (Decimal)
* `set_ts_rel_sim_time()`: set 64-bit relative timestamp from sim time
* `get_ts_rel()`: return current 64-bit relative timestamp as separate fields
* `get_ts_rel_64()`: return current 64-bit relative timestamp as an integer
* `get_ts_rel_ns()`: return current 64-bit relative timestamp in ns (Decimal)
* `get_ts_rel_s()`: return current 64-bit relative timestamp in seconds (Decimal)

### PTP clock (sim time)

The `PtpClockSimTime` class implements a PTP hardware clock that produces IEEE 1588 format 96-bit time-of-day and 64-bit relative PTP timestamps, derived from the current simulation time.  This module can be used in place of `PtpClock` so that captured PTP timestamps can be easily compared to captured simulation time.

To use this module, import it and connect it to the DUT:

    from cocotbext.eth import PtpClockSimTime

    ptp_clock = PtpClockSimTime(
        ts_tod=dut.ts_tod,
        ts_rel=dut.ts_rel,
        pps=dut.pps,
        clock=dut.clk
    )

Once the clock is instantiated, it will generate a continuous stream of monotonically increasing PTP timestamps on every clock edge.

All APIs that handle fractional values use the `Decimal` type for maximum precision, as the combination of timestamp range and resolution is usually too much for normal floating point numbers to handle without significant loss of precision.

#### Signals

* `ts_tod`: 96-bit time-of-day timestamp (48 bit seconds, 32 bit ns, 16 bit fractional ns)
* `ts_rel`: 64-bit relative timestamp (48 bit ns, 16 bit fractional ns)
* `pps`: pulse-per-second output, pulsed when ts_tod seconds field increments

#### Constructor parameters:

* _ts_tod_: 96-bit time-of-day timestamp signal (optional)
* _ts_rel_: 64-bit relative timestamp signal (optional)
* _pps_: pulse-per-second signal (optional)
* _clock_: clock

#### Attributes:

* _ts_tod_s_: current 96-bit ToD timestamp seconds field
* _ts_tod_ns_: current 96-bit ToD timestamp ns field
* _ts_tod_fns_: current 96-bit ToD timestamp fractional ns field
* _ts_rel_ns_: current 64-bit relative timestamp ns field
* _ts_rel_fns_: current 64-bit relative timestamp fractional ns field

#### Methods

* `get_ts_tod()`: return current 96-bit ToD timestamp as separate fields
* `get_ts_tod_96()`: return current 96-bit ToD timestamp as an integer
* `get_ts_tod_ns()`: return current 96-bit ToD timestamp in ns (Decimal)
* `get_ts_tod_s()`: return current 96-bit ToD timestamp in seconds (Decimal)
* `get_ts_rel()`: return current 64-bit relative timestamp as separate fields
* `get_ts_rel_96()`: return current 64-bit relative timestamp as an integer
* `get_ts_rel_ns()`: return current 64-bit relative timestamp in ns (Decimal)
* `get_ts_rel_s()`: return current 64-bit relative timestamp in seconds (Decimal)
