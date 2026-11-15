# Asynchronous (Dual-Clock) FIFO: Verification with cocotb

[![regression](https://github.com/YudhaG/async-fifo-verification/actions/workflows/regression.yml/badge.svg)](https://github.com/YudhaG/async-fifo-verification/actions/workflows/regression.yml)

A parameterized dual-clock FIFO in SystemVerilog (Gray-code pointers, 2-flop
synchronizers) with a self-checking, constrained-random
[cocotb](https://www.cocotb.org/) testbench on Icarus Verilog. Every push runs
the regression on GitHub Actions across FIFO depths and clock-frequency
ratios, plus a mutation check that proves the testbench catches injected bugs.

Companion to [fifo-verification](https://github.com/YudhaG/fifo-verification)
(the single-clock version).

## What is in here

```
rtl/async_fifo.sv            DUT: dual-clock FIFO, params DSIZE and ASIZE (DEPTH = 2**ASIZE)
tb/test_async_fifo.py        testbench: two clock domains, monitors, scoreboard, coverage, 4 tests
Makefile                     cocotb + Icarus flow
scripts/mutation_check.sh    injects 6 bugs, expects the testbench to fail on each
.github/workflows/           CI: depth x clock-ratio matrix + mutation job
```

## Design under test

- Write side on `wclk`, read side on `rclk`, with unrelated frequencies.
- Pointers are ASIZE+1 bits. The extra MSB distinguishes full from empty.
- Each pointer crosses to the other domain as **Gray code** (one bit changes
  per increment) through a **2-flop synchronizer**.
- `wfull` and `rempty` are computed in their own domain from the synchronized
  opposite pointer. They are **conservative**: they release a few cycles late
  but never allow overflow or underflow.
- First-word-fall-through: `rdata` shows the oldest entry whenever `!rempty`.

## Why the testbench is structured this way

The flags lag reality by a few cycles because of the synchronizers, so a
cycle-exact reference model would report false errors. The checks are split
by when they must hold:

| When | Check |
|---|---|
| Every clock edge (safety) | No write accepted into a full FIFO (overflow) |
| | No read accepted from an empty FIFO (underflow) |
| | Every word comes out once, unchanged, in order (scoreboard) |
| | `wptr` and `rptr` change at most one bit per clock (CDC-safe Gray crossing) |
| After traffic stops and synchronizers settle (accuracy) | `wfull == (occupancy == DEPTH)` and `rempty == (occupancy == 0)` |
| Eventually (liveness) | A FIFO holding data drains completely when read |

Each clock domain has its own monitor. The write monitor pushes accepted
words into a shared reference queue and the read monitor pops and compares.

### Tests

| Test | Purpose |
|---|---|
| `test_reset_flags` | `rempty=1`, `wfull=0` during and after reset |
| `test_fill_then_drain` | Fill to full with overflow attempts, drain with underflow attempts, exact flags after settling |
| `test_streaming` | Both sides at 100% rate for 50 x DEPTH write cycles |
| `test_random` | 7 constrained-random bias phases with concurrent traffic, flag accuracy checked after each phase, then asserts zero coverage holes |

### Coverage bins

`reached_full`, `reached_empty`, `write_when_full`, `read_when_empty`,
`write_while_reading`, `wptr_full_lap`, `rptr_full_lap` (pointer wrapped
including its MSB), and every occupancy level 0..DEPTH.

### Mutation check

| Mutant | Bug | Caught by |
|---|---|---|
| `full_no_msb_invert` | wrong full comparison | settled-flag check |
| `binary_ptr_crosses` | binary pointer crosses domains instead of Gray | Gray-code check |
| `rempty_resets_low` | FIFO reports not-empty in reset | reset-flag check |
| `write_ignores_full` | memory written while full | scoreboard (data mismatch) |
| `read_ptr_ungated` | read pointer advances while empty | underflow check |
| `data_bit0_corrupt` | bit 0 of stored data flipped | scoreboard (data mismatch) |

## Run it locally

### macOS

```bash
brew install icarus-verilog
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make
```

### Useful variations

```bash
make ASIZE=6 DSIZE=32                 # 64 entries, 32-bit data
make WCLK_NS=10 RCLK_NS=37            # fast writer, slow reader
make WCLK_NS=37 RCLK_NS=10            # slow writer, fast reader
make WCLK_NS=10 RCLK_NS=10            # identical clocks (coincident edges)
make SEED=1234                        # reproduce a random run
make WAVES=1                          # waveform in sim_build/ (GTKWave or Surfer)
./scripts/mutation_check.sh           # prove the testbench catches bugs
make clean
```

## Limitations (honest ones)

- **Metastability is not modeled.** RTL simulation treats every flop as
  resolving cleanly, so a design with a 1-flop synchronizer passes this
  testbench (checked: it does). Synchronizer depth and CDC structure are
  verified with static CDC tools (e.g. Questa CDC, Spyglass) or formal, not
  functional simulation.
- Clocks are fixed-period with no jitter. Varying the ratio across CI jobs
  covers different phase relationships, not true asynchrony.
- This is a cocotb testbench with UVM-style roles, not UVM, which needs a
  commercial simulator.
- Next steps: SVA properties for the Gray-code and flag rules, randomized
  clock periods and jitter per run, and independent asynchronous resets.
