CC := gcc
MPICC := mpicc
CFLAGS := -std=c11 -O3 -Wall -Wextra -Wpedantic

.PHONY: all test quick experiment calibrate clean

all: bin/lcs_seq bin/lcs_parallel

bin:
	mkdir -p bin

bin/lcs_seq: src/lcs_sequential.c | bin
	$(CC) $(CFLAGS) $< -o $@

bin/lcs_parallel: src/lcs_parallel.c | bin
	$(MPICC) $(CFLAGS) -fopenmp $< -o $@

test: all
	bash tests/test.sh

quick: all
	python3 -B experiments.py quick

experiment: all
	python3 -B experiments.py full

calibrate: bin/lcs_seq
	python3 -B experiments.py calibrate

clean:
	rm -rf bin
