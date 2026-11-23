#!/usr/bin/env python3
"""orquestra os experimentos de desempenho do lcs.

o script gera entradas reproduziveis, executa cada configuracao de forma
intercalada e produz arquivos csv com os calculos.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS = ROOT / "resultados"
EXPERIMENT_INPUTS = Path("/tmp/lcs-experiment-inputs")
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
TILE_SIZE = 256
RAW_FIELDS = [
    "phase",
    "program",
    "strategy",
    "input_size",
    "processes",
    "threads",
    "workers",
    "tile_size",
    "repetition",
    "score",
    "kernel_s",
    "total_s",
    "input_s",
    "allocation_s",
]
SUMMARY_FIELDS = [
    "phase",
    "program",
    "strategy",
    "input_size",
    "processes",
    "threads",
    "workers",
    "tile_size",
    "repetitions",
    "score",
    "correct",
    "mean_kernel_s",
    "stddev_kernel_s",
    "mean_total_s",
    "stddev_total_s",
    "cv_total_pct",
    "sequential_mean_total_s",
    "parallel_time_pct",
    "time_reduction_pct",
    "speedup",
    "efficiency",
    "efficiency_pct",
    "weak_efficiency",
    "weak_efficiency_pct",
    "best_layout",
]
STRATEGY_FIELDS = [
    "input_size",
    "strategy",
    "processes",
    "threads",
    "workers",
    "mean_total_s",
    "stddev_total_s",
    "speedup",
    "efficiency_pct",
    "winner",
]


@dataclass(frozen=True)
class Configuration:
    phase: str
    program: str
    input_size: int
    processes: int = 1
    threads: int = 1
    tile_size: int = 0

    @property
    def workers(self) -> int:
        return self.processes * self.threads

    @property
    def strategy(self) -> str:
        if self.program == "sequential":
            return "sequential"
        if self.processes == 1 and self.threads == 1:
            return "parallel_1_worker"
        if self.processes == 1:
            return "openmp"
        if self.threads == 1:
            return "mpi"
        return "openmp_mpi"


def run_command(command: list[str], env: dict[str, str] | None = None,
                check: bool = True,
                cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )


def command_output(command: list[str]) -> str:
    try:
        return run_command(command).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "indisponivel"


def read_optional(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return "indisponivel"


def detect_topology() -> tuple[int, int]:
    logical = os.cpu_count() or 1
    cores: set[tuple[str, str]] = set()
    output = command_output(["lscpu", "-p=CORE,SOCKET"])
    for line in output.splitlines():
        if line and not line.startswith("#"):
            parts = line.split(",")
            if len(parts) == 2:
                cores.add((parts[0], parts[1]))
    return max(1, len(cores)), logical


def cpu_metadata() -> dict[str, str]:
    wanted = {
        "Architecture": "cpu_architecture",
        "Model name": "cpu_model",
        "Socket(s)": "cpu_sockets",
        "Core(s) per socket": "cpu_cores_per_socket",
        "Thread(s) per core": "cpu_threads_per_core",
        "CPU max MHz": "cpu_max_mhz",
        "L1d cache": "cpu_l1d_cache",
        "L1i cache": "cpu_l1i_cache",
        "L2 cache": "cpu_l2_cache",
        "L3 cache": "cpu_l3_cache",
    }
    values: dict[str, str] = {}
    for line in command_output(["lscpu"]).splitlines():
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        if name in wanted:
            values[wanted[name]] = value.strip()
    return values


def memory_metadata() -> dict[str, str]:
    lines = command_output(["free", "-h"]).splitlines()
    if len(lines) < 3:
        return {}
    return {
        "memory_total": lines[1].split()[1],
        "swap_total": lines[2].split()[1],
    }


def collect_metadata() -> dict[str, object]:
    physical, logical = detect_topology()
    return {
        "collected_at": datetime.now().astimezone().isoformat(),
        "operating_system": command_output(["uname", "-srvmo"]),
        **cpu_metadata(),
        "physical_cores": physical,
        "logical_cpus": logical,
        **memory_metadata(),
        "gcc": command_output(["gcc", "--version"]).splitlines()[0],
        "mpicc": command_output(["mpicc", "--version"]).splitlines()[0],
        "mpirun": command_output(["mpirun", "--version"]).splitlines()[0],
        "kernel_governor": read_optional(
            "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
        ),
        "intel_turbo_no_turbo": read_optional(
            "/sys/devices/system/cpu/intel_pstate/no_turbo"
        ),
        "compiler_flags": "-std=c11 -Wall -Wextra -Wpedantic -O3 -fopenmp",
        "omp_dynamic": "false",
        "omp_proc_bind": "close",
    }


def write_sequence(path: Path, length: int, seed: int) -> None:
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    remaining = length
    with path.open("w", encoding="ascii", newline="\n") as output:
        while remaining:
            amount = min(8192, remaining)
            output.write("".join(rng.choices(ALPHABET, k=amount)))
            remaining -= amount
        output.write("\n")


def input_paths(size: int, seed: int) -> tuple[Path, Path]:
    directory = EXPERIMENT_INPUTS / str(seed) / str(size)
    file_a = directory / "fileA.in"
    file_b = directory / "fileB.in"
    if not file_a.exists():
        write_sequence(file_a, size, seed + size * 2)
    if not file_b.exists():
        write_sequence(file_b, size, seed + size * 2 + 1)
    return file_a, file_b


def parse_program_output(
    result: subprocess.CompletedProcess[str],
) -> dict[str, float | int]:
    score_match = re.search(r"^\s*(\d+)\s*$", result.stdout)
    if score_match is None:
        raise RuntimeError(f"Saida invalida:\n{result.stdout}\n{result.stderr}")

    values: dict[str, float | int] = {"score": int(score_match.group(1))}
    for name, value in re.findall(
        r"(input|allocation|kernel|total)=([0-9]+(?:\.[0-9]+)?)",
        result.stderr,
    ):
        values[name] = float(value)
    return values


def execute_once(config: Configuration, seed: int) -> dict[str, float | int]:
    file_a, file_b = input_paths(config.input_size, seed)
    env = os.environ.copy()
    env["LCS_TIMING"] = "1"
    if config.program == "sequential":
        command = [str(ROOT / "bin" / "lcs_seq")]
    else:
        env["OMP_NUM_THREADS"] = str(config.threads)
        env["OMP_DYNAMIC"] = "false"
        env["OMP_PROC_BIND"] = "close"

        physical, _ = detect_topology()
        if config.workers <= physical:
            env["OMP_PLACES"] = "cores"
            placement = ["--bind-to", "core", "--map-by", f"slot:PE={config.threads}"]
        else:
            env["OMP_PLACES"] = "threads"
            placement = [
                "--use-hwthread-cpus",
                "--bind-to",
                "hwthread",
                "--map-by",
                f"slot:PE={config.threads}",
            ]

        command = [
            "mpirun",
            *placement,
            "-np",
            str(config.processes),
            str(ROOT / "bin" / "lcs_parallel"),
        ]

    try:
        start = time.perf_counter()
        result = run_command(command, env=env, cwd=file_a.parent)
        elapsed = time.perf_counter() - start
        measured = parse_program_output(result)
        measured.setdefault("kernel", elapsed)
        measured.setdefault("total", elapsed)
        return measured
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"Falha em {' '.join(command)}\n{error.stdout}\n{error.stderr}"
        ) from error


def initialize_csv(path: Path, fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        csv.DictWriter(output, fieldnames=fields, lineterminator="\n").writeheader()


def append_csv(path: Path, fields: list[str], row: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writerow({field: row.get(field, "") for field in fields})


def run_batch(configurations: list[Configuration], repetitions: int,
              warmups: int, run_dir: Path, seed: int, raw_path: Path) -> None:
    if warmups > 0:
        for index, config in enumerate(configurations, start=1):
            print(
                f"Aquecimento {index}/{len(configurations)}: {config.phase}, "
                f"N={config.input_size}, {config.processes}x{config.threads}",
                flush=True,
            )
            for _ in range(warmups):
                execute_once(config, seed)
    else:
        print("Aquecimentos desabilitados para esta campanha.", flush=True)

    order_rng = random.Random(seed + 9901)
    for repetition in range(1, repetitions + 1):
        ordered = list(configurations)
        order_rng.shuffle(ordered)
        for index, config in enumerate(ordered, start=1):
            print(
                f"Medicao {repetition}/{repetitions}, {index}/{len(ordered)}: "
                f"{config.phase}, N={config.input_size}, "
                f"{config.processes}x{config.threads}",
                flush=True,
            )
            measured = execute_once(config, seed)
            append_csv(
                raw_path,
                RAW_FIELDS,
                {
                    **asdict(config),
                    "strategy": config.strategy,
                    "workers": config.workers,
                    "repetition": repetition,
                    "score": measured["score"],
                    "kernel_s": measured["kernel"],
                    "total_s": measured["total"],
                    "input_s": measured.get("input", ""),
                    "allocation_s": measured.get("allocation", ""),
                },
            )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def numeric(values: list[dict[str, str]], field: str) -> list[float]:
    return [float(row[field]) for row in values if row.get(field, "") != ""]


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else math.nan


def stddev(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def summarize(raw_path: Path, run_dir: Path, worker_counts: list[int]) -> list[dict[str, object]]:
    raw = read_csv(raw_path)
    groups: dict[tuple[str, str, int, int, int, int], list[dict[str, str]]] = defaultdict(list)
    for row in raw:
        key = (
            row["phase"],
            row["program"],
            int(row["input_size"]),
            int(row["processes"]),
            int(row["threads"]),
            int(row["tile_size"]),
        )
        groups[key].append(row)

    baseline: dict[int, dict[str, float | int]] = {}
    for key, rows in groups.items():
        phase, program, size, _, _, _ = key
        if phase == "baseline" and program == "sequential":
            baseline[size] = {
                "total": mean(numeric(rows, "total_s")),
                "kernel": mean(numeric(rows, "kernel_s")),
                "input": mean(numeric(rows, "input_s")),
                "allocation": mean(numeric(rows, "allocation_s")),
                "score": int(rows[0]["score"]),
            }

    preliminary: list[dict[str, object]] = []
    for key, rows in sorted(groups.items()):
        phase, program, size, processes, threads, tile = key
        totals = numeric(rows, "total_s")
        kernels = numeric(rows, "kernel_s")
        total_mean = mean(totals)
        workers = processes * threads
        base = baseline[size]
        speedup = float(base["total"]) / total_mean
        efficiency = speedup / workers
        parallel_time_pct = 100.0 * total_mean / float(base["total"])
        scores = {int(row["score"]) for row in rows}
        correct = len(scores) == 1 and next(iter(scores)) == int(base["score"])
        preliminary.append(
            {
                "phase": phase,
                "program": program,
                "strategy": Configuration(
                    phase, program, size, processes, threads, tile
                ).strategy,
                "input_size": size,
                "processes": processes,
                "threads": threads,
                "workers": workers,
                "tile_size": tile,
                "repetitions": len(rows),
                "score": next(iter(scores)) if len(scores) == 1 else "divergente",
                "correct": "sim" if correct else "nao",
                "mean_kernel_s": mean(kernels),
                "stddev_kernel_s": stddev(kernels),
                "mean_total_s": total_mean,
                "stddev_total_s": stddev(totals),
                "cv_total_pct": 100.0 * stddev(totals) / total_mean,
                "sequential_mean_total_s": float(base["total"]),
                "parallel_time_pct": parallel_time_pct,
                "time_reduction_pct": 100.0 - parallel_time_pct,
                "speedup": speedup,
                "efficiency": efficiency,
                "efficiency_pct": 100.0 * efficiency,
                "weak_efficiency": "",
                "weak_efficiency_pct": "",
                "best_layout": "nao",
            }
        )

    best_layout: dict[int, dict[str, object]] = {}
    for row in preliminary:
        if row["phase"] != "layout" or row["program"] != "parallel":
            continue
        workers = int(row["workers"])
        current = best_layout.get(workers)
        if current is None or float(row["mean_total_s"]) < float(current["mean_total_s"]):
            best_layout[workers] = row
    for row in best_layout.values():
        row["best_layout"] = "sim"

    weak_one = next(
        (
            row for row in preliminary
            if row["phase"] == "weak" and row["program"] == "parallel"
            and row["workers"] == 1
        ),
        None,
    )
    if weak_one is not None:
        weak_reference = float(weak_one["mean_total_s"])
        for row in preliminary:
            if row["phase"] == "weak" and row["program"] == "parallel":
                weak_efficiency = weak_reference / float(row["mean_total_s"])
                row["weak_efficiency"] = weak_efficiency
                row["weak_efficiency_pct"] = 100.0 * weak_efficiency

    summary_path = run_dir / "summary.csv"
    initialize_csv(summary_path, SUMMARY_FIELDS)
    for row in preliminary:
        append_csv(summary_path, SUMMARY_FIELDS, row)

    strategy_path = run_dir / "strategies.csv"
    initialize_csv(strategy_path, STRATEGY_FIELDS)
    for row in preliminary:
        if row["phase"] == "layout" and row["program"] == "parallel":
            append_csv(strategy_path, STRATEGY_FIELDS, {
                **row,
                "winner": row["best_layout"],
            })

    write_amdahl(run_dir, baseline, worker_counts)
    return preliminary


def write_amdahl(run_dir: Path, baseline: dict[int, dict[str, float | int]],
                  worker_counts: list[int]) -> None:
    fields = [
        "input_size",
        "non_parallel_time_s",
        "non_parallel_percentage",
        "parallelizable_time_s",
        "parallelizable_percentage",
        "workers",
        "max_speedup",
    ]
    path = run_dir / "amdahl.csv"
    initialize_csv(path, fields)
    for size, values in sorted(baseline.items()):
        non_parallel_time = float(values["input"]) + float(values["allocation"])
        parallelizable_time = float(values["kernel"])
        serial = non_parallel_time / float(values["total"])
        parallel = 1.0 - serial
        for workers in worker_counts:
            speedup = 1.0 / (serial + parallel / workers)
            append_csv(path, fields, {
                "input_size": size,
                "non_parallel_time_s": non_parallel_time,
                "non_parallel_percentage": 100.0 * serial,
                "parallelizable_time_s": parallelizable_time,
                "parallelizable_percentage": 100.0 * parallel,
                "workers": workers,
                "max_speedup": speedup,
            })
        append_csv(path, fields, {
            "input_size": size,
            "non_parallel_time_s": non_parallel_time,
            "non_parallel_percentage": 100.0 * serial,
            "parallelizable_time_s": parallelizable_time,
            "parallelizable_percentage": 100.0 * parallel,
            "workers": "infinito",
            "max_speedup": 1.0 / serial if serial > 0 else "infinito",
        })


def powers_of_two(limit: int) -> list[int]:
    values = []
    current = 1
    while current <= limit:
        values.append(current)
        current *= 2
    return values


def layout_options(workers: int, physical_cores: int) -> list[tuple[int, int]]:
    options = []
    for processes in range(1, workers + 1):
        if workers % processes == 0 and processes <= physical_cores:
            options.append((processes, workers // processes))
    return options


def best_configurations(raw_path: Path) -> dict[int, tuple[int, int]]:
    raw = read_csv(raw_path)
    grouped: dict[tuple[int, int, int], list[float]] = defaultdict(list)
    for row in raw:
        if row["phase"] == "layout" and row["program"] == "parallel":
            key = (int(row["workers"]), int(row["processes"]), int(row["threads"]))
            grouped[key].append(float(row["total_s"]))

    selected: dict[int, tuple[int, int]] = {}
    selected_time: dict[int, float] = {}
    for (workers, processes, threads), values in grouped.items():
        value = mean(values)
        if workers not in selected_time or value < selected_time[workers]:
            selected[workers] = (processes, threads)
            selected_time[workers] = value
    return selected


def available_memory_bytes() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    return 512 * 1024 * 1024


def calibrate_size(target_seconds: float, start_size: int, seed: int) -> int:
    # cada celula usa dois bytes e o restante fica disponivel para o sistema e o mpi.
    max_size = int(math.sqrt(available_memory_bytes() * 0.60 / 2.0)) - 1
    size = min(start_size, max_size)
    print(f"Calibrando N para aproximadamente {target_seconds:.1f} s.")

    while True:
        config = Configuration("calibration", "sequential", size)
        execute_once(config, seed)
        result = execute_once(config, seed)
        kernel = float(result["kernel"])
        print(f"N={size}: kernel={kernel:.3f} s")
        if kernel >= target_seconds or size >= max_size:
            return size

        if kernel <= 0:
            growth = 2.0
        else:
            growth = 0.92 * math.sqrt(target_seconds / kernel)
            growth = min(2.0, max(1.25, growth))
        next_size = min(max_size, max(size + 1, int(size * growth)))
        if next_size == size:
            return size
        size = next_size


def make_output_dir(name: str | None, quick: bool) -> Path:
    if name:
        path = Path(name)
        return path if path.is_absolute() else ROOT / path
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if quick:
        return Path("/tmp") / f"lcs-quick-{stamp}"
    return DEFAULT_RESULTS


def validate_campaign_arguments(args: argparse.Namespace, quick: bool) -> None:
    positive = ["max_workers", "strong_size", "repetitions"]
    for name in positive:
        value = getattr(args, name, None)
        if value is not None and value <= 0:
            raise ValueError(f"--{name.replace('_', '-')} deve ser positivo")
    if args.warmups is not None and args.warmups < 0:
        raise ValueError("--warmups nao pode ser negativo")
    if not quick and args.repetitions is not None and args.repetitions < 20:
        raise ValueError("a campanha completa exige no minimo 20 repeticoes")


def campaign(args: argparse.Namespace, quick: bool) -> Path:
    validate_campaign_arguments(args, quick)
    run_dir = make_output_dir(args.output, quick)
    run_dir.mkdir(parents=True, exist_ok=run_dir == DEFAULT_RESULTS)
    raw_path = run_dir / "raw.csv"
    initialize_csv(raw_path, RAW_FIELDS)

    if not args.no_build:
        print("Compilando os programas.")
        result = subprocess.run(["make", "all"], cwd=ROOT)
        if result.returncode != 0:
            raise RuntimeError("Falha durante a compilacao.")

    metadata = collect_metadata()
    physical = int(metadata["physical_cores"])
    logical = int(metadata["logical_cpus"])
    maximum_workers = min(args.max_workers or logical, logical)
    worker_counts = powers_of_two(maximum_workers)

    if quick:
        strong_size = args.strong_size or 256
        repetitions = args.repetitions or 2
        warmups = args.warmups if args.warmups is not None else 1
        size_values = sorted({max(32, strong_size // 2), strong_size})
    else:
        repetitions = args.repetitions or 20
        warmups = args.warmups if args.warmups is not None else 3
        strong_size = args.strong_size or calibrate_size(
            args.target_seconds, args.start_size, args.seed
        )
        size_values = sorted({
            max(128, int(strong_size * 0.50)),
            max(128, int(strong_size * 0.75)),
            strong_size,
        })

    weak_base = max(32, int(strong_size / math.sqrt(maximum_workers)))
    weak_sizes = {workers: max(1, round(weak_base * math.sqrt(workers)))
                  for workers in worker_counts}
    all_sizes = sorted(set(size_values) | set(weak_sizes.values()))

    metadata.update({
        "mode": "quick" if quick else "full",
        "repetitions": repetitions,
        "warmups": warmups,
        "seed": args.seed,
        "tile_size": TILE_SIZE,
        "strong_size": strong_size,
        "size_values": size_values,
        "weak_base_size": weak_base,
        "worker_counts": worker_counts,
    })
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    stage_one = [Configuration("baseline", "sequential", size) for size in all_sizes]
    for workers in worker_counts:
        for processes, threads in layout_options(workers, physical):
            stage_one.append(Configuration(
                "layout", "parallel", strong_size, processes, threads,
                TILE_SIZE,
            ))
    run_batch(stage_one, repetitions, warmups, run_dir, args.seed, raw_path)

    selected = best_configurations(raw_path)
    stage_two: list[Configuration] = []
    for size in size_values:
        if size == strong_size:
            continue
        for workers in worker_counts:
            processes, threads = selected[workers]
            stage_two.append(Configuration(
                "size", "parallel", size, processes, threads, TILE_SIZE
            ))
    for workers in worker_counts:
        processes, threads = selected[workers]
        stage_two.append(Configuration(
            "weak", "parallel", weak_sizes[workers], processes, threads,
            TILE_SIZE,
        ))
    run_batch(stage_two, repetitions, warmups, run_dir, args.seed, raw_path)

    summarize(raw_path, run_dir, worker_counts)
    print(f"Resultados gravados em {run_dir}")
    return run_dir


def analyze_command(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir).resolve()
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    summarize(run_dir / "raw.csv", run_dir, list(metadata["worker_counts"]))
    print(f"Analises atualizadas em {run_dir}")


def parser() -> argparse.ArgumentParser:
    main = argparse.ArgumentParser(description=__doc__)
    subparsers = main.add_subparsers(dest="command", required=True)

    def campaign_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--output", help="diretorio de resultados")
        command.add_argument("--repetitions", type=int)
        command.add_argument("--warmups", type=int)
        command.add_argument("--max-workers", type=int)
        command.add_argument("--strong-size", type=int)
        command.add_argument("--seed", type=int, default=1316)
        command.add_argument("--no-build", action="store_true")

    quick = subparsers.add_parser("quick", help="valida o fluxo com entradas pequenas")
    campaign_arguments(quick)

    full = subparsers.add_parser("full", help="executa a campanha completa")
    campaign_arguments(full)
    full.add_argument("--target-seconds", type=float, default=10.0)
    full.add_argument("--start-size", type=int, default=2000)

    analyze = subparsers.add_parser("analyze", help="refaz as analises de um resultado")
    analyze.add_argument("run_dir")
    return main


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "quick":
            campaign(args, quick=True)
        elif args.command == "full":
            campaign(args, quick=False)
        else:
            analyze_command(args)
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Erro: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
