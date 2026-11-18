#!/usr/bin/env bash
set -euo pipefail

temporary_directory=$(mktemp -d)
trap 'rm -rf "$temporary_directory"' EXIT
project_root=$(cd "$(dirname "$0")/.." && pwd)

check() {
    local file_a=$1
    local file_b=$2
    local expected=$3
    local result
    local sequential

    cp "$file_a" "$temporary_directory/fileA.in"
    cp "$file_b" "$temporary_directory/fileB.in"

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

check fileA.in fileB.in 5
check tests/cases/classicA.in tests/cases/classicB.in 4
check tests/cases/equalA.in tests/cases/equalB.in 6
check tests/cases/differentA.in tests/cases/differentB.in 0
check tests/cases/one.in tests/cases/one.in 1
check tests/cases/empty.in tests/cases/classicB.in 0
check tests/cases/classicA.in tests/cases/empty.in 0
check tests/cases/empty.in tests/cases/empty.in 0

echo "Todos os testes passaram."
