# cocotb makefile, same shape as the tiny tapeout template
#   make                 rtl simulation
#   make GATES=local     gate-level, on a local yosys netlist
#   make GATES=yes       gate-level with the pdk cells (the gds action runs this)

SIM ?= icarus
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../src
PROJECT_SOURCES = project.v metro_core.v

ifeq ($(GATES),yes)

SIM_BUILD        = sim_build/gl
COMPILE_ARGS    += -DGL_TEST -DFUNCTIONAL -DUSE_POWER_PINS -DSIM -DUNIT_DELAY=\#1
VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/primitives.v
VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v
# copied in by the gds action
VERILOG_SOURCES += $(PWD)/gate_level_netlist.v

else ifeq ($(GATES),local)

SIM_BUILD        = sim_build/gl_local
VERILOG_SOURCES += $(shell yosys-config --datdir)/simcells.v
VERILOG_SOURCES += $(PWD)/sim_build/local_netlist.v

else

SIM_BUILD        = sim_build/rtl
COMPILE_ARGS    += -DMETRO_DEBUG
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))

endif

ifeq ($(WAVES),1)
COMPILE_ARGS += -DDUMP_WAVES
endif

COMPILE_ARGS += -I$(SRC_DIR)
VERILOG_SOURCES += $(PWD)/tb.v
TOPLEVEL = tb
COCOTB_TEST_MODULES = test

include $(shell cocotb-config --makefiles)/Makefile.sim
