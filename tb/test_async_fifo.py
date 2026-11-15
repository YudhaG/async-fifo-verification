"""cocotb testbench for rtl/async_fifo.sv (dual-clock FIFO).

Why this is harder than a sync FIFO: wfull and rempty are computed from a
pointer that crossed a clock domain, so they lag reality by a few cycles.
A cycle-exact model would be wrong, so the checks are split:

  Always true, every edge (safety):
    - an accepted write never lands in a full FIFO          (no overflow)
    - an accepted read never comes from an empty FIFO       (no underflow)
    - every word comes out once, unchanged, in order         (scoreboard)
    - the Gray pointers change at most one bit per clock     (CDC-safe crossing)

  True once traffic stops and the synchronizers settle (accuracy):
    - wfull == (occupancy == DEPTH), rempty == (occupancy == 0)

  Eventually true (liveness):
    - a FIFO with data in it drains completely when read

Knobs (environment variables, all optional; the Makefile passes them through):
  ASIZE, DSIZE        : must match the DUT build (DEPTH = 2**ASIZE)
  WCLK_NS, RCLK_NS    : clock periods, e.g. fast writer/slow reader
  SEED                : reproduce a random run, e.g.  make SEED=1234
  RANDOM_CYCLES       : write-clock cycles per random phase (default 3000)
"""

import os
import random
from collections import deque

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

ASIZE = int(os.environ.get("ASIZE", "4"))
DEPTH = 1 << ASIZE
WIDTH = int(os.environ.get("DSIZE", "8"))
MASK = (1 << WIDTH) - 1
WCLK_NS = int(os.environ.get("WCLK_NS", "10"))
RCLK_NS = int(os.environ.get("RCLK_NS", "17"))
RANDOM_CYCLES = int(os.environ.get("RANDOM_CYCLES", "3000"))


def popcount(x):
    return bin(x).count("1")


class Coverage:
    BINS = (
        "reached_full",
        "reached_empty",
        "write_when_full",
        "read_when_empty",
        "write_while_reading",
        "wptr_full_lap",   # >= 2*DEPTH writes: Gray pointer incl. MSB wrapped
        "rptr_full_lap",
    )

    def __init__(self):
        self.hits = dict.fromkeys(self.BINS, 0)
        self.levels = set()

    def hit(self, name):
        self.hits[name] += 1

    def holes(self):
        holes = [b for b, n in self.hits.items() if n == 0]
        holes += [f"occupancy=={c}" for c in range(DEPTH + 1) if c not in self.levels]
        return holes

    def report(self, log):
        log.info("---- functional coverage ----")
        for name, n in self.hits.items():
            log.info(f"  {name:<20} {n:>8}  {'HIT' if n else 'MISSING'}")
        log.info(f"  occupancy levels     {len(self.levels):>3}/{DEPTH + 1}")
        log.info(f"  holes: {self.holes() or 'none'}")


class AsyncFifoEnv:
    def __init__(self, dut):
        self.dut = dut
        self.seed = int(os.environ.get("SEED", random.SystemRandom().randrange(2**32)))
        self.rng = random.Random(self.seed)
        self.q = deque()          # reference model: words written, not yet read
        self.cov = Coverage()
        self.writes = 0
        self.reads = 0
        self._reading = False
        dut._log.info(
            f"DEPTH={DEPTH} DSIZE={WIDTH} WCLK={WCLK_NS}ns RCLK={RCLK_NS}ns SEED={self.seed}"
        )

    # ------------------------------------------------------------- setup
    async def reset(self):
        dut = self.dut
        dut.winc.value = 0
        dut.rinc.value = 0
        dut.wdata.value = 0
        dut.wrst_n.value = 0
        dut.rrst_n.value = 0
        cocotb.start_soon(Clock(dut.wclk, WCLK_NS, unit="ns").start())
        cocotb.start_soon(Clock(dut.rclk, RCLK_NS, unit="ns").start())
        await ClockCycles(dut.wclk, 3)
        await ClockCycles(dut.rclk, 3)
        assert int(dut.rempty.value) == 1, "rempty must be 1 during reset"
        assert int(dut.wfull.value) == 0, "wfull must be 0 during reset"
        dut.wrst_n.value = 1
        dut.rrst_n.value = 1
        await RisingEdge(dut.wclk)
        await RisingEdge(dut.rclk)
        cocotb.start_soon(self._write_monitor())
        cocotb.start_soon(self._read_monitor())

    # ----------------------------------------------------------- drivers
    async def _write_stream(self, p_wr, cycles):
        dut = self.dut
        for _ in range(cycles):
            dut.winc.value = int(self.rng.random() < p_wr)
            dut.wdata.value = self.rng.getrandbits(WIDTH)
            await RisingEdge(dut.wclk)
        dut.winc.value = 0

    async def _read_stream(self, p_rd):
        dut = self.dut
        while self._reading:
            dut.rinc.value = int(self.rng.random() < p_rd)
            await RisingEdge(dut.rclk)
        dut.rinc.value = 0

    async def traffic(self, p_wr, p_rd, wcycles):
        """Write and read concurrently, each on its own clock, for wcycles write clocks."""
        self._reading = True
        reader = cocotb.start_soon(self._read_stream(p_rd))
        await self._write_stream(p_wr, wcycles)
        self._reading = False
        await reader

    async def drain(self):
        """Liveness: everything written must come out within a bounded time."""
        dut = self.dut
        dut.winc.value = 0
        for _ in range(20 * DEPTH + 100):
            if not self.q:
                break
            dut.rinc.value = 1
            await RisingEdge(dut.rclk)
        dut.rinc.value = 0
        assert not self.q, f"liveness: {len(self.q)} entries never came out"

    async def settle_and_check_flags(self):
        """Stop traffic, let both synchronizers settle, then flags must be exact."""
        dut = self.dut
        dut.winc.value = 0
        dut.rinc.value = 0
        await ClockCycles(dut.wclk, 4)
        await ClockCycles(dut.rclk, 4)
        await ClockCycles(dut.wclk, 4)
        n = len(self.q)
        wfull = int(dut.wfull.value)
        rempty = int(dut.rempty.value)
        assert wfull == int(n == DEPTH), f"settled wfull={wfull} but occupancy={n}"
        assert rempty == int(n == 0), f"settled rempty={rempty} but occupancy={n}"

    # ---------------------------------------------- monitors + scoreboard
    async def _write_monitor(self):
        dut, q, cov = self.dut, self.q, self.cov
        prev_gray = None
        while True:
            await RisingEdge(dut.wclk)
            gray = int(dut.wptr.value)
            if prev_gray is not None:
                assert popcount(gray ^ prev_gray) <= 1, (
                    f"wptr Gray code changed {popcount(gray ^ prev_gray)} bits "
                    f"(0x{prev_gray:x} -> 0x{gray:x}): unsafe to cross clock domains"
                )
            prev_gray = gray

            winc = int(dut.winc.value)
            wfull = int(dut.wfull.value)
            if wfull:
                cov.hit("reached_full")
            if winc and wfull:
                cov.hit("write_when_full")
            if winc and not wfull:
                assert len(q) < DEPTH, f"overflow: write accepted with {len(q)} entries stored"
                q.append(int(dut.wdata.value) & MASK)
                self.writes += 1
                if int(dut.rinc.value):
                    cov.hit("write_while_reading")
                if self.writes >= 2 * DEPTH:
                    cov.hit("wptr_full_lap")
            cov.levels.add(len(q))

    async def _read_monitor(self):
        dut, q, cov = self.dut, self.q, self.cov
        prev_gray = None
        while True:
            await RisingEdge(dut.rclk)
            gray = int(dut.rptr.value)
            if prev_gray is not None:
                assert popcount(gray ^ prev_gray) <= 1, (
                    f"rptr Gray code changed {popcount(gray ^ prev_gray)} bits "
                    f"(0x{prev_gray:x} -> 0x{gray:x}): unsafe to cross clock domains"
                )
            prev_gray = gray

            rinc = int(dut.rinc.value)
            rempty = int(dut.rempty.value)
            if rempty:
                cov.hit("reached_empty")
            if rinc and rempty:
                cov.hit("read_when_empty")
            if rinc and not rempty:
                assert q, "underflow: read accepted while FIFO holds no data"
                got = int(dut.rdata.value)
                exp = q.popleft()
                assert got == exp, f"data mismatch: dut=0x{got:x} expected=0x{exp:x}"
                self.reads += 1
                if self.reads >= 2 * DEPTH:
                    cov.hit("rptr_full_lap")
            cov.levels.add(len(q))


# =========================================================================
# Tests
# =========================================================================
@cocotb.test()
async def test_reset_flags(dut):
    """Flags are correct during and after reset; the FIFO starts empty."""
    env = AsyncFifoEnv(dut)
    await env.reset()
    await env.settle_and_check_flags()


@cocotb.test()
async def test_fill_then_drain(dut):
    """Fill to full (overflow attempts ignored), then drain (underflow attempts ignored)."""
    env = AsyncFifoEnv(dut)
    await env.reset()

    await env.traffic(p_wr=1.0, p_rd=0.0, wcycles=2 * DEPTH + 8)
    await env.settle_and_check_flags()
    assert len(env.q) == DEPTH, f"expected a full FIFO, model holds {len(env.q)}"

    await env.drain()
    for _ in range(8):  # keep reading an empty FIFO: must be ignored
        dut.rinc.value = 1
        await RisingEdge(dut.rclk)
    await env.settle_and_check_flags()


@cocotb.test()
async def test_streaming(dut):
    """Both sides at full rate for a long stretch: data integrity across the crossing."""
    env = AsyncFifoEnv(dut)
    await env.reset()
    await env.traffic(p_wr=1.0, p_rd=1.0, wcycles=50 * DEPTH)
    await env.drain()
    await env.settle_and_check_flags()
    assert env.writes == env.reads > 0


@cocotb.test()
async def test_random(dut):
    """Constrained-random traffic in bias phases, then close coverage."""
    env = AsyncFifoEnv(dut)
    await env.reset()

    phases = [  # (P(write) per wclk, P(read) per rclk)
        (0.80, 0.20),
        (0.20, 0.80),
        (0.50, 0.50),
        (1.00, 1.00),
        (1.00, 0.30),
        (0.30, 1.00),
        (0.00, 1.00),
    ]
    for p_wr, p_rd in phases:
        await env.traffic(p_wr, p_rd, RANDOM_CYCLES)
        await env.settle_and_check_flags()

    await env.drain()
    await env.settle_and_check_flags()

    env.cov.report(dut._log)
    dut._log.info(f"scoreboard matched {env.reads} reads of {env.writes} writes")
    holes = env.cov.holes()
    assert not holes, f"coverage holes: {holes}"
