/*

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

*/

// Language: Verilog 2001

`timescale 1ns / 1ps

/*
 * Ethernet MAC model test
 */
module test_eth_mac #
(
    parameter PTP_TS_WIDTH = 96,
    parameter PTP_TAG_WIDTH = 16,
    parameter AXIS_DATA_WIDTH = 64,
    parameter AXIS_KEEP_WIDTH = (AXIS_DATA_WIDTH/8),
    parameter AXIS_TX_USER_WIDTH = PTP_TAG_WIDTH+1,
    parameter AXIS_RX_USER_WIDTH = PTP_TS_WIDTH+1
)
(
    inout  wire                           tx_clk,
    inout  wire                           tx_rst,
    inout  wire [AXIS_DATA_WIDTH-1:0]     tx_axis_tdata,
    inout  wire [AXIS_KEEP_WIDTH-1:0]     tx_axis_tkeep,
    inout  wire                           tx_axis_tlast,
    inout  wire [AXIS_TX_USER_WIDTH-1:0]  tx_axis_tuser,
    inout  wire                           tx_axis_tvalid,
    inout  wire                           tx_axis_tready,
    inout  wire [PTP_TS_WIDTH-1:0]        tx_ptp_time,
    inout  wire [PTP_TS_WIDTH-1:0]        tx_ptp_ts,
    inout  wire [PTP_TAG_WIDTH-1:0]       tx_ptp_ts_tag,
    inout  wire                           tx_ptp_ts_valid,

    inout  wire                           rx_clk,
    inout  wire                           rx_rst,
    inout  wire [AXIS_DATA_WIDTH-1:0]     rx_axis_tdata,
    inout  wire [AXIS_KEEP_WIDTH-1:0]     rx_axis_tkeep,
    inout  wire                           rx_axis_tlast,
    inout  wire [AXIS_RX_USER_WIDTH-1:0]  rx_axis_tuser,
    inout  wire                           rx_axis_tvalid,
    inout  wire [PTP_TS_WIDTH-1:0]        rx_ptp_time
);

endmodule
