// Asynchronous (dual-clock) FIFO, Cummings-style.
//
//  - Write side runs on wclk, read side on rclk; the clocks are unrelated.
//  - Pointers are ASIZE+1 bits: the extra MSB tells "full" from "empty".
//  - Each pointer is converted to Gray code before it crosses into the other
//    clock domain, so only one bit changes per increment, and it passes
//    through a 2-flop synchronizer.
//  - wfull / rempty are computed in their own domain from the synchronized
//    (therefore slightly stale) opposite pointer. They are conservative:
//    the FIFO may report full/empty a few cycles late in releasing, but
//    never overflows or underflows.
//  - rdata shows the oldest entry whenever !rempty (first-word-fall-through).
//
// DEPTH = 2**ASIZE, ASIZE >= 2.
module async_fifo #(
    parameter int DSIZE = 8,
    parameter int ASIZE = 4
) (
    // write clock domain
    input  logic             wclk,
    input  logic             wrst_n,
    input  logic             winc,
    input  logic [DSIZE-1:0] wdata,
    output logic             wfull,

    // read clock domain
    input  logic             rclk,
    input  logic             rrst_n,
    input  logic             rinc,
    output logic [DSIZE-1:0] rdata,
    output logic             rempty
);

  localparam int DEPTH = 1 << ASIZE;

  logic [DSIZE-1:0] mem [0:DEPTH-1];

  logic [ASIZE:0] wbin, wptr;          // write pointer: binary, Gray
  logic [ASIZE:0] rbin, rptr;          // read pointer:  binary, Gray
  logic [ASIZE:0] wq1_rptr, wq2_rptr;  // rptr synchronized into wclk
  logic [ASIZE:0] rq1_wptr, rq2_wptr;  // wptr synchronized into rclk

  // ------------------------------------------------------------ write domain
  wire [ASIZE:0] wbinnext  = wbin + (winc & ~wfull);
  wire [ASIZE:0] wgraynext = (wbinnext >> 1) ^ wbinnext;
  // Full when the next write pointer equals the read pointer with its two
  // MSBs inverted (Gray-code equivalent of "same address, one lap ahead").
  wire wfull_val = (wgraynext == {~wq2_rptr[ASIZE:ASIZE-1], wq2_rptr[ASIZE-2:0]});

  always_ff @(posedge wclk or negedge wrst_n) begin
    if (!wrst_n) begin
      wbin     <= '0;
      wptr     <= '0;
      wq1_rptr <= '0;
      wq2_rptr <= '0;
      wfull    <= 1'b0;
    end else begin
      wbin     <= wbinnext;
      wptr     <= wgraynext;
      wq1_rptr <= rptr;        // 2-flop synchronizer
      wq2_rptr <= wq1_rptr;
      wfull    <= wfull_val;
    end
  end

  always_ff @(posedge wclk) begin
    if (winc && !wfull) mem[wbin[ASIZE-1:0]] <= wdata;
  end

  // ------------------------------------------------------------- read domain
  wire [ASIZE:0] rbinnext  = rbin + (rinc & ~rempty);
  wire [ASIZE:0] rgraynext = (rbinnext >> 1) ^ rbinnext;
  wire rempty_val = (rgraynext == rq2_wptr);

  always_ff @(posedge rclk or negedge rrst_n) begin
    if (!rrst_n) begin
      rbin     <= '0;
      rptr     <= '0;
      rq1_wptr <= '0;
      rq2_wptr <= '0;
      rempty   <= 1'b1;
    end else begin
      rbin     <= rbinnext;
      rptr     <= rgraynext;
      rq1_wptr <= wptr;        // 2-flop synchronizer
      rq2_wptr <= rq1_wptr;
      rempty   <= rempty_val;
    end
  end

  assign rdata = mem[rbin[ASIZE-1:0]];

endmodule
