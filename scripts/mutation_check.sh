#!/usr/bin/env bash
# Mutation check: inject one bug at a time into a COPY of the RTL and confirm
# the testbench FAILS. A mutant that survives means the testbench has a blind
# spot. The real RTL in rtl/ is never modified.
#
# Usage: scripts/mutation_check.sh        (run from anywhere)
set -u
cd "$(dirname "$0")/.."

SRC=rtl/async_fifo.sv
OUT=mutants
rm -rf "$OUT" && mkdir -p "$OUT"

# name | sed expression
MUTANTS=(
  "full_no_msb_invert|s/{~wq2_rptr\[ASIZE:ASIZE-1\], wq2_rptr\[ASIZE-2:0\]}/wq2_rptr/"
  "binary_ptr_crosses|s/wptr     <= wgraynext;/wptr     <= wbinnext;/"
  "rempty_resets_low|s/rempty   <= 1'b1;/rempty   <= 1'b0;/"
  "write_ignores_full|s/if (winc \&\& !wfull) mem/if (winc) mem/"
  "read_ptr_ungated|s/rbin + (rinc \& ~rempty)/rbin + rinc/"
  "data_bit0_corrupt|s/<= wdata;/<= wdata ^ 1'b1;/"
)

echo "== baseline (unmutated RTL) =="
rm -rf sim_build_base results.xml
if ! make SIM_BUILD=sim_build_base RANDOM_CYCLES=500 >"$OUT/baseline.log" 2>&1 \
   || grep -qE "<(failure|error)" results.xml; then
  echo "BASELINE FAILS - fix the design/testbench first. See $OUT/baseline.log"
  exit 2
fi
echo "baseline passes"
echo

killed=0
survived=0
for entry in "${MUTANTS[@]}"; do
  name="${entry%%|*}"
  expr="${entry#*|}"
  mkdir -p "$OUT/$name"
  sed "$expr" "$SRC" > "$OUT/$name/async_fifo.sv"

  if cmp -s "$SRC" "$OUT/$name/async_fifo.sv"; then
    echo "ERROR: mutant '$name' did not change the RTL (sed pattern is stale)"
    exit 2
  fi

  rm -rf "sim_build_$name" results.xml
  make VERILOG_SOURCES="$PWD/$OUT/$name/async_fifo.sv" SIM_BUILD="sim_build_$name" \
       RANDOM_CYCLES=500 >"$OUT/$name/sim.log" 2>&1
  rc=$?

  if [ $rc -ne 0 ] || [ ! -f results.xml ] || grep -qE "<(failure|error)" results.xml; then
    reason=$(grep -m1 -oE "AssertionError: .*" "$OUT/$name/sim.log" | cut -c1-90)
    echo "KILLED    $name   ${reason}"
    killed=$((killed + 1))
  else
    echo "SURVIVED  $name   <-- testbench did not catch this bug"
    survived=$((survived + 1))
  fi
  rm -rf "sim_build_$name"
done

rm -rf sim_build_base
echo
echo "mutants killed: $killed / $((killed + survived))"
[ "$survived" -eq 0 ]
