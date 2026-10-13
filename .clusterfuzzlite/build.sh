#!/bin/bash -eu
# Builds every fuzz/fuzz_*.py with Atheris (preinstalled in the base image).
cd "$SRC/fleetpilot"
python3 -m pip install --require-hashes -r requirements-lock.txt
for fuzzer in fuzz/fuzz_*.py; do
  compile_python_fuzzer "$fuzzer" --paths "$SRC/fleetpilot"
done
