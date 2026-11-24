GCC ?= /home/eecs/trazzaque/spec2017-research/toolchain/bin/riscv64-unknown-linux-gnu-gcc
PLUGIN_DIR := $(shell $(GCC) -print-file-name=plugin)
CXX ?= g++
boom_div_select.so: boom_div_select.cpp
	$(CXX) -std=gnu++17 -shared -fPIC -fno-rtti -O2 -Wall -Wno-unused-parameter -I$(PLUGIN_DIR)/include -o $@ $<
