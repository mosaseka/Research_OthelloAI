#!/usr/bin/env python3
"""Deterministically tune original_10 MPC scale settings with a small GA.

The tool treats the existing othello_arena.py as an immutable subprocess.
Candidate and baseline settings are carried by separate Java -D options because
the arena intentionally gives both players the same environment.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


SCHEMA_VERSION = 1
MIN_SCALE = 0.5
MAX_SCALE = 2.5
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ARTIFACT_ROOT = SCRIPT_DIR.parent / "artifacts" / "mpc_ga"
DEFAULT_CHECKPOINT = DEFAULT_ARTIFACT_ROOT / "checkpoint.json"
DEFAULT_OUTPUT = DEFAULT_ARTIFACT_ROOT / "result.json"
DEFAULT_RUNS_DIR = DEFAULT_ARTIFACT_ROOT / "runs"

Individual = Dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def positive_int(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return value


def nonnegative_int(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return value


def probability(text: str) -> float:
    value = float(text)
    if not 0.0 <= value <= 1.0:
        raise argparse.ArgumentTypeError("must be in [0, 1]")
    return value


def nonnegative_float(text: str) -> float:
    value = float(text)
    if value < 0.0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return value


def resolved(path: Path) -> Path:
    return Path(os.path.expanduser(str(path))).resolve()


def normalize_java_target(path: Path) -> Path:
    target = resolved(path)
    if target.suffix.lower() in (".java", ".class"):
        target = target.with_suffix("")
    return target


def java_working_directory(target: Path, arena_root: Path) -> Path:
    working_directory = target.parent
    for directory in target.parents:
        if (directory / "resources").is_dir():
            return directory
        if directory == arena_root:
            break
    return working_directory


def clamp_scale(value: float) -> float:
    return min(MAX_SCALE, max(MIN_SCALE, value))


def rounded_scale(value: float) -> float:
    return round(clamp_scale(value), 8)


def scale_text(value: float) -> str:
    text = f"{rounded_scale(value):.8f}".rstrip("0").rstrip(".")
    return text if "." in text else text + ".0"


def new_individual(mid_scale: float, final_scale: float) -> Individual:
    return {
        "mid_scale": rounded_scale(mid_scale),
        "final_scale": rounded_scale(final_scale),
        "fitness": None,
        "evaluation": None,
    }


def initial_population(rng: random.Random, size: int) -> List[Individual]:
    population = [new_individual(1.0, 1.0)]
    while len(population) < size:
        population.append(
            new_individual(
                rng.uniform(MIN_SCALE, MAX_SCALE),
                rng.uniform(MIN_SCALE, MAX_SCALE),
            )
        )
    return population


def fitness_value(individual: Individual) -> float:
    value = individual.get("fitness")
    if not isinstance(value, (int, float)):
        raise ValueError("selection requires evaluated individuals")
    return float(value)


def disc_tie_break(individual: Individual) -> float:
    evaluation = individual.get("evaluation")
    if not isinstance(evaluation, dict):
        return float("-inf")
    value = evaluation.get("average_disc_difference")
    if not isinstance(value, (int, float)):
        return float("-inf")
    value = float(value)
    return value if value == value else float("-inf")


def rank_population(population: Sequence[Individual]) -> List[Individual]:
    return sorted(
        population,
        key=lambda item: (
            -fitness_value(item),
            -disc_tie_break(item),
            float(item["mid_scale"]),
            float(item["final_scale"]),
        ),
    )


def select_parent(
    population: Sequence[Individual],
    rng: random.Random,
    tournament_size: int,
) -> Individual:
    if not population:
        raise ValueError("cannot select from an empty population")
    count = min(tournament_size, len(population))
    contenders = rng.sample(list(population), count)
    return rank_population(contenders)[0]


def crossover(
    first: Individual,
    second: Individual,
    rng: random.Random,
) -> Individual:
    mid_alpha = rng.random()
    final_alpha = rng.random()
    mid = (
        mid_alpha * float(first["mid_scale"])
        + (1.0 - mid_alpha) * float(second["mid_scale"])
    )
    final = (
        final_alpha * float(first["final_scale"])
        + (1.0 - final_alpha) * float(second["final_scale"])
    )
    return new_individual(mid, final)


def mutate(
    individual: Individual,
    rng: random.Random,
    mutation_rate: float,
    mutation_sigma: float,
) -> Individual:
    result = new_individual(
        float(individual["mid_scale"]),
        float(individual["final_scale"]),
    )
    for key in ("mid_scale", "final_scale"):
        if rng.random() < mutation_rate:
            result[key] = rounded_scale(
                float(result[key]) + rng.gauss(0.0, mutation_sigma)
            )
    return result


def breed_population(
    population: Sequence[Individual],
    rng: random.Random,
    elite_count: int,
    mutation_rate: float,
    mutation_sigma: float,
    tournament_size: int,
) -> List[Individual]:
    ranked = rank_population(population)
    next_population = [
        new_individual(item["mid_scale"], item["final_scale"])
        for item in ranked[:elite_count]
    ]
    while len(next_population) < len(population):
        first = select_parent(ranked, rng, tournament_size)
        second = select_parent(ranked, rng, tournament_size)
        child = crossover(first, second, rng)
        next_population.append(
            mutate(child, rng, mutation_rate, mutation_sigma)
        )
    return next_population


def java_argv(
    java_executable: str,
    target: Path,
    mpc_mode: str,
    mid_scale: float,
    final_scale: float,
) -> List[str]:
    return [
        java_executable,
        "-Dothello.mpcMode=" + mpc_mode,
        "-Dothello.mpcMidScale=" + scale_text(mid_scale),
        "-Dothello.mpcFinalScale=" + scale_text(final_scale),
        "-cp",
        str(target.parent),
        target.name,
    ]


def arena_argv(
    config: Dict[str, Any],
    mid_scale: float,
    final_scale: float,
    jsonl_path: Path,
    summary_path: Path,
) -> List[str]:
    arena = Path(config["arena"])
    candidate_target = Path(config["candidate_ai"])
    baseline_target = Path(config["baseline_ai"])
    candidate_command = java_argv(
        str(config["java"]),
        candidate_target,
        str(config["mpc_mode"]),
        mid_scale,
        final_scale,
    )
    baseline_command = java_argv(
        str(config["java"]),
        baseline_target,
        str(config["mpc_mode"]),
        1.0,
        1.0,
    )
    return [
        str(config["python"]),
        str(arena),
        "--ai-a",
        json.dumps(candidate_command, ensure_ascii=True, separators=(",", ":")),
        "--ai-b",
        json.dumps(baseline_command, ensure_ascii=True, separators=(",", ":")),
        "--name-a",
        "candidate",
        "--name-b",
        "baseline",
        "--cwd-a",
        str(config["candidate_cwd"]),
        "--cwd-b",
        str(config["baseline_cwd"]),
        "--pairs",
        str(int(config["games"]) // 2),
        "--random-opening-plies",
        str(config["random_opening_plies"]),
        "--seed",
        str(config["seed"]),
        "--engine-seed",
        str(config["seed"]),
        "--move-time-ms",
        str(config["time_ms"]),
        "--threads",
        str(config["threads"]),
        "--startup-timeout-ms",
        str(config["startup_timeout_ms"]),
        "--shutdown-timeout-ms",
        str(config["shutdown_timeout_ms"]),
        "--progress",
        "off",
        "--jsonl",
        str(jsonl_path),
        "--summary",
        str(summary_path),
    ]


def random_state_to_json(value: Any) -> Any:
    if isinstance(value, tuple):
        return [random_state_to_json(item) for item in value]
    return value


def random_state_from_json(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(random_state_from_json(item) for item in value)
    return value


def save_checkpoint(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = copy.deepcopy(state)
    payload["saved_at_utc"] = utc_now()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def load_checkpoint(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        state = json.load(handle)
    if not isinstance(state, dict):
        raise ValueError("checkpoint root must be a JSON object")
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported checkpoint schema")
    if state.get("tool") != "tune_mpc_ga":
        raise ValueError("checkpoint belongs to another tool")
    return state


def write_json_exclusive(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def tail(text: Optional[str], limit: int = 4000) -> str:
    if not text:
        return ""
    return text[-limit:]


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def evaluate_summary(
    summary: Optional[Dict[str, Any]],
    games: int,
    abnormal_penalty: float,
    timeout_penalty: float,
    arena_returncode: int,
) -> Dict[str, Any]:
    score_rate_valid = False
    if summary is None:
        paired_rate = 0.0
        average_disc_difference = None
        complete_pairs = 0
        invalid_pairs = games // 2
        pairs_requested = 0
        games_requested = 0
        games_recorded = 0
        completed_games = 0
        forfeit_games = 0
        faults_total = 0
        timeout_faults = 0
        run_status = "missing_summary"
    else:
        players = summary.get("players", {})
        candidate_stats = players.get("A", {}) if isinstance(players, dict) else {}
        paired = (
            candidate_stats.get("paired", {})
            if isinstance(candidate_stats, dict)
            else {}
        )
        raw_rate = paired.get("score_rate") if isinstance(paired, dict) else None
        score_rate_valid = (
            isinstance(raw_rate, (int, float))
            and 0.0 <= float(raw_rate) <= 1.0
        )
        paired_rate = float(raw_rate) if score_rate_valid else 0.0
        raw_disc = (
            paired.get("average_disc_difference")
            if isinstance(paired, dict)
            else None
        )
        average_disc_difference = (
            float(raw_disc)
            if isinstance(raw_disc, (int, float))
            and float(raw_disc) == float(raw_disc)
            else None
        )
        complete_pairs = (
            safe_int(paired.get("complete_pairs"))
            if isinstance(paired, dict)
            else 0
        )
        invalid_pairs = (
            safe_int(paired.get("invalid_pairs"))
            if isinstance(paired, dict)
            else games // 2
        )
        pairs_requested = safe_int(summary.get("pairs_requested"))
        games_requested = safe_int(summary.get("games_requested"))
        games_recorded = safe_int(summary.get("games_recorded"))
        completed_games = safe_int(summary.get("completed_games"))
        forfeit_games = safe_int(summary.get("forfeit_games"))
        faults = summary.get("faults", {})
        by_type = faults.get("by_type", {}) if isinstance(faults, dict) else {}
        faults_total = (
            safe_int(faults.get("total"))
            if isinstance(faults, dict)
            else 0
        )
        timeout_faults = (
            safe_int(by_type.get("timeout"))
            if isinstance(by_type, dict)
            else 0
        )
        run_status = str(summary.get("run_status", "unknown"))

    missing_or_failed_games = max(0, games - completed_games)
    invalid_pair_games = max(0, (games // 2 - complete_pairs) * 2)
    abnormal_games = max(
        missing_or_failed_games,
        invalid_pair_games,
        forfeit_games,
        faults_total,
    )
    clean_checks = {
        "arena_returncode_zero": arena_returncode == 0,
        "run_status_completed": run_status == "completed",
        "games_requested_match": games_requested == games,
        "pairs_requested_match": pairs_requested == games // 2,
        "games_recorded_complete": games_recorded == games,
        "completed_games_complete": completed_games == games,
        "forfeit_games_zero": forfeit_games == 0,
        "faults_total_zero": faults_total == 0,
        "timeout_faults_zero": timeout_faults == 0,
        "complete_pairs_complete": complete_pairs == games // 2,
        "invalid_pairs_zero": invalid_pairs == 0,
        "paired_score_rate_valid": score_rate_valid,
        "average_disc_difference_valid": (
            average_disc_difference is not None
        ),
    }
    clean = all(clean_checks.values())
    fitness = paired_rate if clean else (
        -1.0
        - abnormal_penalty * max(1, abnormal_games) / games
        - timeout_penalty * timeout_faults / games
    )
    return {
        "paired_score_rate": paired_rate,
        "average_disc_difference": average_disc_difference,
        "complete_pairs": complete_pairs,
        "invalid_pairs": invalid_pairs,
        "pairs_requested": pairs_requested,
        "games_requested": games_requested,
        "games_recorded": games_recorded,
        "completed_games": completed_games,
        "forfeit_games": forfeit_games,
        "faults_total": faults_total,
        "abnormal_games": abnormal_games,
        "timeout_faults": timeout_faults,
        "run_status": run_status,
        "clean": clean,
        "clean_checks": clean_checks,
        "failed_clean_checks": [
            name for name, passed in clean_checks.items() if not passed
        ],
        "fitness": fitness,
    }


def evaluate_individual(
    config: Dict[str, Any],
    generation: int,
    index: int,
    individual: Individual,
) -> Dict[str, Any]:
    run_directory = Path(config["runs_dir"]) / (
        f"generation-{generation + 1:03d}"
    )
    run_directory.mkdir(parents=True, exist_ok=True)
    stem = f"individual-{index + 1:03d}"
    jsonl_path = run_directory / (stem + "-games.jsonl")
    summary_path = run_directory / (stem + "-summary.json")
    jsonl_path.unlink(missing_ok=True)
    summary_path.unlink(missing_ok=True)

    command = arena_argv(
        config,
        float(individual["mid_scale"]),
        float(individual["final_scale"]),
        jsonl_path,
        summary_path,
    )
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=str(Path(config["arena"]).parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=False,
    )
    duration = time.monotonic() - started

    summary: Optional[Dict[str, Any]] = None
    summary_error: Optional[str] = None
    if summary_path.is_file():
        try:
            with summary_path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            if isinstance(value, dict):
                summary = value
            else:
                summary_error = "summary root is not an object"
        except (OSError, json.JSONDecodeError) as exc:
            summary_error = str(exc)
    else:
        summary_error = "arena did not create a summary"

    result = evaluate_summary(
        summary,
        int(config["games"]),
        float(config["abnormal_penalty"]),
        float(config["timeout_penalty"]),
        completed.returncode,
    )
    result.update(
        {
            "generation": generation,
            "individual_index": index,
            "mid_scale": individual["mid_scale"],
            "final_scale": individual["final_scale"],
            "arena_returncode": completed.returncode,
            "duration_seconds": duration,
            "jsonl_path": str(jsonl_path),
            "summary_path": str(summary_path),
            "summary_error": summary_error,
            "stdout_tail": tail(completed.stdout),
            "stderr_tail": tail(completed.stderr),
        }
    )
    return result


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--:--:--"
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def progress_line(
    state: Dict[str, Any],
    generation: int,
    index: int,
    population_size: int,
    generations: int,
    phase: str,
) -> None:
    done = int(state["evaluations_completed"])
    total = population_size * generations
    elapsed = float(state["evaluation_seconds"])
    eta = None if done == 0 else (total - done) * elapsed / done
    individual = state["population"][index]
    print(
        "[GA] "
        f"generation {generation + 1}/{generations} "
        f"individual {index + 1}/{population_size} "
        f"{phase} | done {done}/{total} | "
        f"elapsed {format_duration(elapsed)} | ETA {format_duration(eta)} | "
        f"mid={float(individual['mid_scale']):.6f} "
        f"final={float(individual['final_scale']):.6f}",
        file=sys.stderr,
        flush=True,
    )


def make_config(args: argparse.Namespace) -> Dict[str, Any]:
    arena = resolved(args.arena)
    candidate = normalize_java_target(args.candidate_ai)
    baseline = normalize_java_target(
        args.baseline_ai if args.baseline_ai is not None else args.candidate_ai
    )
    return {
        "arena": str(arena),
        "candidate_ai": str(candidate),
        "baseline_ai": str(baseline),
        "candidate_cwd": str(java_working_directory(candidate, arena.parent)),
        "baseline_cwd": str(java_working_directory(baseline, arena.parent)),
        "python": args.python,
        "java": args.java,
        "mpc_mode": args.mpc_mode,
        "games": args.games,
        "time_ms": args.time_ms,
        "threads": args.threads,
        "seed": args.seed,
        "population": args.population,
        "generations": args.generations,
        "elite": args.elite,
        "mutation": args.mutation,
        "mutation_sigma": args.mutation_sigma,
        "tournament": args.tournament,
        "random_opening_plies": args.random_opening_plies,
        "startup_timeout_ms": args.startup_timeout_ms,
        "shutdown_timeout_ms": args.shutdown_timeout_ms,
        "abnormal_penalty": args.abnormal_penalty,
        "timeout_penalty": args.timeout_penalty,
        "runs_dir": str(resolved(args.runs_dir)),
    }


def validate_args(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> None:
    if args.arena is None:
        parser.error("--arena is required unless --self-test is used")
    if args.candidate_ai is None:
        parser.error("--candidate-ai is required unless --self-test is used")
    if args.games % 2:
        parser.error("--games must be even because the arena uses colour-swapped pairs")
    if args.population < 2:
        parser.error("--population must be at least 2")
    if args.elite >= args.population:
        parser.error("--elite must be smaller than --population")
    if not 0 <= args.random_opening_plies <= 60:
        parser.error("--random-opening-plies must be in [0, 60]")

    arena = resolved(args.arena)
    candidate = normalize_java_target(args.candidate_ai)
    baseline = normalize_java_target(
        args.baseline_ai if args.baseline_ai is not None else args.candidate_ai
    )
    if not arena.is_file():
        parser.error(f"arena file was not found: {arena}")
    for label, target in (("candidate", candidate), ("baseline", baseline)):
        class_file = target.with_suffix(".class")
        if not class_file.is_file():
            parser.error(f"{label} Java class was not found: {class_file}")

    checkpoint = resolved(args.checkpoint)
    output = resolved(args.output)
    if checkpoint == output:
        parser.error("--checkpoint and --output must be different paths")
    if not args.dry_run:
        if output.exists():
            parser.error(f"refusing to overwrite final JSON: {output}")
        if args.resume and not checkpoint.is_file():
            parser.error(f"resume checkpoint was not found: {checkpoint}")
        if not args.resume and checkpoint.exists():
            parser.error(
                f"checkpoint already exists: {checkpoint}; "
                "use --resume or choose another path"
            )


def config_differences(
    expected: Dict[str, Any],
    actual: Dict[str, Any],
) -> List[str]:
    keys = sorted(set(expected) | set(actual))
    return [
        key
        for key in keys
        if expected.get(key) != actual.get(key)
    ]


def dry_run(config: Dict[str, Any]) -> int:
    rng = random.Random(int(config["seed"]))
    population = initial_population(rng, int(config["population"]))
    run_root = Path(config["runs_dir"]) / "dry-run"
    print("[GA] dry run: no arena subprocesses will be started")
    for index, individual in enumerate(population):
        command = arena_argv(
            config,
            float(individual["mid_scale"]),
            float(individual["final_scale"]),
            run_root / f"individual-{index + 1:03d}-games.jsonl",
            run_root / f"individual-{index + 1:03d}-summary.json",
        )
        print(
            json.dumps(
                {
                    "generation": 1,
                    "individual": index + 1,
                    "mid_scale": individual["mid_scale"],
                    "final_scale": individual["final_scale"],
                    "argv": command,
                },
                ensure_ascii=False,
            )
        )
    return 0


def initialize_state(config: Dict[str, Any]) -> Tuple[Dict[str, Any], random.Random]:
    rng = random.Random(int(config["seed"]))
    state = {
        "schema_version": SCHEMA_VERSION,
        "tool": "tune_mpc_ga",
        "created_at_utc": utc_now(),
        "status": "running",
        "config": config,
        "generation": 0,
        "population": initial_population(rng, int(config["population"])),
        "history": [],
        "generation_summaries": [],
        "evaluations_completed": 0,
        "evaluation_seconds": 0.0,
        "rng_state": random_state_to_json(rng.getstate()),
    }
    return state, rng


def resume_state(
    checkpoint: Path,
    config: Dict[str, Any],
) -> Tuple[Dict[str, Any], random.Random]:
    state = load_checkpoint(checkpoint)
    stored_config = state.get("config")
    if not isinstance(stored_config, dict):
        raise ValueError("checkpoint has no valid config")
    differences = config_differences(config, stored_config)
    if differences:
        raise ValueError(
            "checkpoint configuration differs for: " + ", ".join(differences)
        )
    if state.get("status") == "completed":
        raise ValueError("checkpoint is already marked completed")
    rng = random.Random()
    rng.setstate(random_state_from_json(state["rng_state"]))
    return state, rng


def final_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    ranked = rank_population(state["population"])
    best = copy.deepcopy(ranked[0])
    mid_text = scale_text(float(best["mid_scale"]))
    final_text = scale_text(float(best["final_scale"]))
    mpc_mode = str(state["config"]["mpc_mode"])
    best["jvm_properties"] = {
        "othello.mpcMode": mpc_mode,
        "othello.mpcMidScale": mid_text,
        "othello.mpcFinalScale": final_text,
    }
    best["environment"] = {
        "OTHELLO_MPC_MODE": mpc_mode,
        "OTHELLO_MPC_MID_SCALE": mid_text,
        "OTHELLO_MPC_FINAL_SCALE": final_text,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "tune_mpc_ga",
        "completed_at_utc": utc_now(),
        "config": state["config"],
        "best": best,
        "final_population": copy.deepcopy(ranked),
        "generation_summaries": copy.deepcopy(state["generation_summaries"]),
        "evaluations": copy.deepcopy(state["history"]),
        "evaluations_completed": state["evaluations_completed"],
        "evaluation_seconds": state["evaluation_seconds"],
        "fitness_definition": (
            "clean runs: players.A.paired.score_rate; dirty runs: "
            "-1 - abnormal_penalty * max(1, abnormal_games)/games "
            "- timeout_penalty * timeout_faults/games"
        ),
        "tie_break": (
            "higher players.A.paired.average_disc_difference, then lower "
            "mid_scale, then lower final_scale"
        ),
    }


def run_ga(
    config: Dict[str, Any],
    checkpoint: Path,
    output: Path,
    resume: bool,
) -> int:
    if resume:
        state, rng = resume_state(checkpoint, config)
        print(
            f"[GA] resumed {checkpoint} at generation "
            f"{int(state['generation']) + 1}",
            file=sys.stderr,
        )
    else:
        state, rng = initialize_state(config)
        save_checkpoint(checkpoint, state)

    population_size = int(config["population"])
    generations = int(config["generations"])
    while int(state["generation"]) < generations:
        generation = int(state["generation"])
        population = state["population"]
        for index, individual in enumerate(population):
            if individual.get("fitness") is not None:
                continue
            progress_line(
                state,
                generation,
                index,
                population_size,
                generations,
                "starting",
            )
            result = evaluate_individual(config, generation, index, individual)
            individual["fitness"] = float(result["fitness"])
            individual["evaluation"] = result
            state["history"].append(copy.deepcopy(result))
            state["evaluations_completed"] = (
                int(state["evaluations_completed"]) + 1
            )
            state["evaluation_seconds"] = (
                float(state["evaluation_seconds"])
                + float(result["duration_seconds"])
            )
            state["rng_state"] = random_state_to_json(rng.getstate())
            save_checkpoint(checkpoint, state)
            progress_line(
                state,
                generation,
                index,
                population_size,
                generations,
                (
                    f"fitness={float(result['fitness']):.6f} "
                    f"paired={float(result['paired_score_rate']):.4f} "
                    f"abnormal={int(result['abnormal_games'])} "
                    f"timeouts={int(result['timeout_faults'])}"
                ),
            )

        ranked = rank_population(population)
        state["generation_summaries"].append(
            {
                "generation": generation,
                "best_mid_scale": ranked[0]["mid_scale"],
                "best_final_scale": ranked[0]["final_scale"],
                "best_fitness": ranked[0]["fitness"],
                "mean_fitness": sum(fitness_value(item) for item in ranked)
                / len(ranked),
            }
        )
        if generation + 1 >= generations:
            break
        state["population"] = breed_population(
            ranked,
            rng,
            int(config["elite"]),
            float(config["mutation"]),
            float(config["mutation_sigma"]),
            int(config["tournament"]),
        )
        state["generation"] = generation + 1
        state["rng_state"] = random_state_to_json(rng.getstate())
        save_checkpoint(checkpoint, state)

    payload = final_payload(state)
    write_json_exclusive(output, payload)
    state["status"] = "completed"
    state["completed_at_utc"] = payload["completed_at_utc"]
    state["rng_state"] = random_state_to_json(rng.getstate())
    save_checkpoint(checkpoint, state)
    best = payload["best"]
    print(
        "[GA] complete | "
        f"mid={float(best['mid_scale']):.8f} "
        f"final={float(best['final_scale']):.8f} "
        f"fitness={float(best['fitness']):.6f}",
        file=sys.stderr,
    )
    print(str(output))
    return 0


def run_self_tests() -> int:
    tests: List[Tuple[str, Any]] = []

    def test_selection() -> None:
        population = [
            new_individual(0.6, 0.7),
            new_individual(1.0, 1.0),
            new_individual(2.0, 2.0),
        ]
        for item, fitness in zip(population, (0.1, 0.9, 0.3)):
            item["fitness"] = fitness
        selected = select_parent(population, random.Random(3), 99)
        assert selected["fitness"] == 0.9
        first_sequence = [
            select_parent(population, random.Random(seed), 2)["fitness"]
            for seed in range(5)
        ]
        second_sequence = [
            select_parent(population, random.Random(seed), 2)["fitness"]
            for seed in range(5)
        ]
        assert first_sequence == second_sequence
        tie_a = new_individual(0.8, 0.9)
        tie_b = new_individual(1.1, 1.2)
        for item, discs in ((tie_a, 0.25), (tie_b, 0.75)):
            item["fitness"] = 0.5
            item["evaluation"] = {
                "average_disc_difference": discs,
            }
        assert rank_population((tie_a, tie_b))[0] is tie_b

    def test_crossover() -> None:
        first = new_individual(MIN_SCALE, MAX_SCALE)
        second = new_individual(MAX_SCALE, MIN_SCALE)
        child_a = crossover(first, second, random.Random(11))
        child_b = crossover(first, second, random.Random(11))
        assert child_a == child_b
        assert MIN_SCALE <= child_a["mid_scale"] <= MAX_SCALE
        assert MIN_SCALE <= child_a["final_scale"] <= MAX_SCALE

    def test_mutation() -> None:
        source = new_individual(1.0, 1.0)
        changed = mutate(source, random.Random(17), 1.0, 0.4)
        assert (
            changed["mid_scale"] != source["mid_scale"]
            or changed["final_scale"] != source["final_scale"]
        )
        assert MIN_SCALE <= changed["mid_scale"] <= MAX_SCALE
        assert MIN_SCALE <= changed["final_scale"] <= MAX_SCALE
        edge = mutate(new_individual(0.5, 2.5), random.Random(2), 1.0, 50.0)
        assert MIN_SCALE <= edge["mid_scale"] <= MAX_SCALE
        assert MIN_SCALE <= edge["final_scale"] <= MAX_SCALE

    def test_checkpoint() -> None:
        rng = random.Random(29)
        rng.random()
        state = {
            "schema_version": SCHEMA_VERSION,
            "tool": "tune_mpc_ga",
            "config": {"sample": True},
            "rng_state": random_state_to_json(rng.getstate()),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            save_checkpoint(path, state)
            loaded = load_checkpoint(path)
            restored = random.Random()
            restored.setstate(random_state_from_json(loaded["rng_state"]))
            assert restored.random() == rng.random()
            final = Path(directory) / "final.json"
            write_json_exclusive(final, {"ok": True})
            try:
                write_json_exclusive(final, {"ok": False})
            except FileExistsError:
                pass
            else:
                raise AssertionError("final JSON overwrite was not rejected")

    def test_command_generation() -> None:
        target = Path("C:/ascii/OthelloAI_10")
        candidate = java_argv("java", target, "legacy", 0.75, 2.25)
        baseline = java_argv("java", target, "legacy", 1.0, 1.0)
        assert "-Dothello.mpcMode=legacy" in candidate
        assert "-Dothello.mpcMidScale=0.75" in candidate
        assert "-Dothello.mpcFinalScale=2.25" in candidate
        assert "-Dothello.mpcMidScale=1.0" in baseline
        assert "-Dothello.mpcFinalScale=1.0" in baseline
        config = {
            "python": "python",
            "arena": "C:/ascii/othello_arena.py",
            "java": "java",
            "mpc_mode": "legacy",
            "candidate_ai": str(target),
            "baseline_ai": str(target),
            "candidate_cwd": "C:/ascii",
            "baseline_cwd": "C:/ascii",
            "games": 4,
            "random_opening_plies": 8,
            "seed": 7,
            "time_ms": 100,
            "threads": 1,
            "startup_timeout_ms": 1000,
            "shutdown_timeout_ms": 1000,
        }
        command = arena_argv(
            config,
            0.75,
            2.25,
            Path("C:/ascii/games.jsonl"),
            Path("C:/ascii/summary.json"),
        )
        assert command[0] == "python"
        assert "--ai-a" in command and "--ai-b" in command
        decoded_a = json.loads(command[command.index("--ai-a") + 1])
        decoded_b = json.loads(command[command.index("--ai-b") + 1])
        assert decoded_a == candidate
        assert decoded_b == baseline
        assert "--pairs" in command
        assert command[command.index("--pairs") + 1] == "2"

    def test_clean_gate() -> None:
        summary = {
            "run_status": "completed",
            "pairs_requested": 2,
            "games_requested": 4,
            "games_recorded": 4,
            "completed_games": 4,
            "forfeit_games": 0,
            "faults": {"total": 0, "by_type": {}},
            "players": {
                "A": {
                    "paired": {
                        "complete_pairs": 2,
                        "invalid_pairs": 0,
                        "score_rate": 0.625,
                        "average_disc_difference": 1.5,
                    }
                }
            },
        }
        clean = evaluate_summary(summary, 4, 1.0, 0.5, 0)
        assert clean["clean"] is True
        assert clean["fitness"] == 0.625
        dirty_summary = copy.deepcopy(summary)
        dirty_summary["faults"]["total"] = 1
        dirty = evaluate_summary(dirty_summary, 4, 0.0, 0.0, 0)
        assert dirty["clean"] is False
        assert dirty["fitness"] < 0.0
        failed_process = evaluate_summary(summary, 4, 0.0, 0.0, 3)
        assert failed_process["clean"] is False
        assert failed_process["fitness"] < 0.0

    tests.extend(
        [
            ("selection", test_selection),
            ("crossover", test_crossover),
            ("mutation", test_mutation),
            ("checkpoint", test_checkpoint),
            ("command generation", test_command_generation),
            ("clean match gate", test_clean_gate),
        ]
    )
    for name, test in tests:
        test()
        print(f"[self-test] PASS: {name}")
    print(f"[self-test] all {len(tests)} tests passed; no matches were run")
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Tune OTHELLO_MPC_MID_SCALE and OTHELLO_MPC_FINAL_SCALE "
            "with deterministic colour-paired arena matches."
        )
    )
    parser.add_argument("--arena", type=Path, help="path to othello_arena.py")
    parser.add_argument(
        "--candidate-ai",
        type=Path,
        help="candidate Java target path, with optional .java/.class suffix",
    )
    parser.add_argument(
        "--baseline-ai",
        type=Path,
        default=None,
        help="baseline Java target path (default: candidate target)",
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--java", default="java")
    parser.add_argument(
        "--mpc-mode",
        choices=("legacy", "nonNested", "retuned"),
        default="legacy",
        help="MPC implementation tuned for both candidate and baseline",
    )
    parser.add_argument("--games", type=positive_int, default=4)
    parser.add_argument("--time-ms", type=positive_int, default=1000)
    parser.add_argument("--threads", type=positive_int, default=1)
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument("--population", type=positive_int, default=8)
    parser.add_argument("--generations", type=positive_int, default=5)
    parser.add_argument("--elite", type=nonnegative_int, default=2)
    parser.add_argument("--mutation", type=probability, default=0.25)
    parser.add_argument(
        "--mutation-sigma",
        type=nonnegative_float,
        default=0.15,
        help="Gaussian mutation standard deviation in scale units",
    )
    parser.add_argument("--tournament", type=positive_int, default=3)
    parser.add_argument("--random-opening-plies", type=nonnegative_int, default=8)
    parser.add_argument("--startup-timeout-ms", type=positive_int, default=60000)
    parser.add_argument("--shutdown-timeout-ms", type=positive_int, default=2000)
    parser.add_argument("--abnormal-penalty", type=nonnegative_float, default=1.0)
    parser.add_argument("--timeout-penalty", type=nonnegative_float, default=0.5)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print generation-one arena argv without running matches or writing files",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="test GA/checkpoint/command logic without running matches",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        return run_self_tests()
    validate_args(args, parser)
    config = make_config(args)
    if args.dry_run:
        return dry_run(config)
    checkpoint = resolved(args.checkpoint)
    output = resolved(args.output)
    try:
        return run_ga(config, checkpoint, output, args.resume)
    except KeyboardInterrupt:
        print(
            "\n[GA] interrupted; resume with the same arguments and --resume",
            file=sys.stderr,
        )
        return 130
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[GA] error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
