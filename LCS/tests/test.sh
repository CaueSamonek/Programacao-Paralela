#!/usr/bin/env bash
set -euo pipefail

temporary_directory=$(mktemp -d)
trap 'rm -rf "$temporary_directory"' EXIT
project_root=$(cd "$(dirname "$0")/.." && pwd)

check() {
    local sequence_a=$1
    local sequence_b=$2
    local expected=$3
    local result
    local sequential

    printf '%s\n' "$sequence_a" > "$temporary_directory/fileA.in"
    printf '%s\n' "$sequence_b" > "$temporary_directory/fileB.in"

    sequential=$(cd "$temporary_directory" && "$project_root/bin/lcs_seq")
    [[ "$sequential" == "$expected" ]]

    for processes in 1 2 3; do
        for threads in 1 2 3; do
            result=$(cd "$temporary_directory" && OMP_NUM_THREADS=$threads \
                mpirun -np "$processes" "$project_root/bin/lcs_parallel")
            [[ "$result" == "$expected" ]]
        done
    done
}

check heagawghee pawheae 5
check ABCBDAB BDCABA 4
check ABC123 ABC123 6
check ABCD WXYZ 0
check A1B2C3 Z1B9C3 4
check A A 1
check '' BDCABA 0
check ABCBDAB '' 0
check '' '' 0

tile_sequence=$(printf 'A%.0s' {1..600})
check "$tile_sequence" "$tile_sequence" 600

sequential_timing=$(cd "$temporary_directory" && LCS_TIMING=1 \
    "$project_root/bin/lcs_seq" 2>&1 >/dev/null)
parallel_timing=$(cd "$temporary_directory" && LCS_TIMING=1 OMP_NUM_THREADS=2 \
    mpirun -np 2 "$project_root/bin/lcs_parallel" 2>&1 >/dev/null)
timing_pattern='input=[0-9.]+ allocation=[0-9.]+ kernel=[0-9.]+ total=[0-9.]+'
[[ "$sequential_timing" =~ $timing_pattern ]]
[[ "$parallel_timing" =~ $timing_pattern ]]

mkdir "$temporary_directory/missing"
if missing_output=$(cd "$temporary_directory/missing" && \
    "$project_root/bin/lcs_seq" 2>/dev/null); then
    exit 1
fi
[[ -z "$missing_output" ]]
if missing_output=$(cd "$temporary_directory/missing" && \
    mpirun -np 2 "$project_root/bin/lcs_parallel" 2>/dev/null); then
    exit 1
fi
[[ -z "$missing_output" ]]

echo "Todos os testes passaram."
