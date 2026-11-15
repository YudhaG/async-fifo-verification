# Run with:  make                              (defaults below)
#            make ASIZE=6 DSIZE=32             (DEPTH = 2**ASIZE)
#            make WCLK_NS=10 RCLK_NS=37        (fast writer, slow reader)
#            make SEED=1234                    (reproduce a random run)
#            make WAVES=1                      (waveform into sim_build/)
#            make clean

SIM                 ?= icarus
TOPLEVEL_LANG       := verilog
COCOTB_TOPLEVEL     := async_fifo
COCOTB_TEST_MODULES := test_async_fifo

ASIZE   ?= 4
DSIZE   ?= 8
WCLK_NS ?= 10
RCLK_NS ?= 17
VERILOG_SOURCES ?= $(CURDIR)/rtl/async_fifo.sv

# The testbench reads these from the environment so it always matches the build.
export ASIZE DSIZE WCLK_NS RCLK_NS

COMPILE_ARGS += -g2012 -Pasync_fifo.ASIZE=$(ASIZE) -Pasync_fifo.DSIZE=$(DSIZE)

export PYTHONPATH := $(CURDIR)/tb:$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim
