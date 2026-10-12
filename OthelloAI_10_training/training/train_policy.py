"""Train original_10's lightweight listwise move-ordering policy.

Each teacher row contains a relative root board and the level-11 move played
immediately after Egaroucid's random prefix.  All legal children are generated.
The shared Java-compatible scorer emits a raw value from the child side's
perspective, so the parent move logit is exactly ``-raw``.  No tanh or score
clamp is used in the cross-entropy loss.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import glob
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time
from typing import Any, Iterable, Iterator, Sequence

try:
    import torch
    from torch import Tensor
    from torch.nn import functional as F
    from torch.nn.utils.rnn import pad_sequence
    from torch.utils.data import DataLoader, IterableDataset, get_worker_info
except ImportError as error:  # pragma: no cover
    raise ImportError("PyTorch is required; install a CUDA build for GPU training") from error

from evaluator_model import (
    JavaCompatibleEvaluator,
    export_java_parameters,
    feature_tensors,
    features_from_relative,
    legal_moves_bits,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "train_policy.json"
FULL_BOARD = (1 << 64) - 1
HORIZONTAL_MASK = 0x7E7E7E7E7E7E7E7E
SPLITS = ("train", "val", "test")
FEATURE_SCHEMA = "exact-mobility-v1"
POLICY_SPLIT_ALGORITHM = "sha256-canonical-d4-board-v1"
POLICY_SPLIT_UNIT = "canonical_d4_relative_board"
POLICY_SPLIT_SEED = "20260715"
POLICY_SPLIT_RATIOS = {"train": 0.9, "val": 0.05, "test": 0.05}
POLICY_SAMPLE_ALGORITHM = "fnv1a64-canonical-d4-v1"
POLICY_SAMPLE_UNIT = "canonical_d4_relative_board"
POLICY_SAMPLE_SEED = "20260720"
POLICY_SAMPLE_NUMERATOR = 1
POLICY_SAMPLE_DENOMINATOR = 16


@dataclass(frozen=True)
class Teacher:
    board: str
    move: int


def duration_text(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        return "--:--:--"
    whole = int(seconds)
    hours, remainder = divmod(whole, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def coordinate_to_cell(value: str) -> int:
    if len(value) != 2 or not ("a" <= value[0] <= "h") or not ("1" <= value[1] <= "8"):
        raise ValueError(f"invalid move coordinate: {value!r}")
    return (ord(value[1]) - ord("1")) * 8 + ord(value[0]) - ord("a")


def parse_teacher(raw: str, path: Path, line_number: int) -> Teacher | None:
    stripped = raw.strip()
    if not stripped:
        return None
    fields = stripped.split()
    if len(fields) != 2:
        raise ValueError(f"{path}:{line_number}: expected '<board> <move>'")
    board, move = fields
    if len(board) != 64 or set(board) - {"X", "O", "-"}:
        raise ValueError(f"{path}:{line_number}: invalid relative board")
    return Teacher(board, coordinate_to_cell(move))


def rotate90(board: str) -> str:
    return "".join(board[(7 - x) * 8 + y] for y in range(8) for x in range(8))


def mirror(board: str) -> str:
    return "".join(board[y * 8 + (7 - x)] for y in range(8) for x in range(8))


def rotate90_cell(cell: int) -> int:
    y, x = divmod(cell, 8)
    return x * 8 + (7 - y)


def mirror_cell(cell: int) -> int:
    y, x = divmod(cell, 8)
    return y * 8 + (7 - x)


def transform(board: str, move: int, variant: int) -> tuple[str, int]:
    for _ in range(variant // 2):
        board = rotate90(board)
        move = rotate90_cell(move)
    if variant % 2:
        board = mirror(board)
        move = mirror_cell(move)
    return board, move


def relative_bits(board: str) -> tuple[int, int]:
    own = 0
    opponent = 0
    for cell, value in enumerate(board):
        if value == "X":
            own |= 1 << cell
        elif value == "O":
            opponent |= 1 << cell
    return own, opponent


def ray_left(move: int, player: int, opponent: int, shift: int, mask: int) -> int:
    masked = opponent & mask
    cursor = masked & (move << shift)
    captured = 0
    while cursor:
        captured |= cursor
        next_cursor = cursor << shift
        if next_cursor & player:
            return captured
        cursor = masked & next_cursor
    return 0


def ray_right(move: int, player: int, opponent: int, shift: int, mask: int) -> int:
    masked = opponent & mask
    cursor = masked & (move >> shift)
    captured = 0
    while cursor:
        captured |= cursor
        next_cursor = cursor >> shift
        if next_cursor & player:
            return captured
        cursor = masked & next_cursor
    return 0


def flips_for(move: int, player: int, opponent: int) -> int:
    return (
        ray_left(move, player, opponent, 1, HORIZONTAL_MASK)
        | ray_right(move, player, opponent, 1, HORIZONTAL_MASK)
        | ray_left(move, player, opponent, 7, HORIZONTAL_MASK)
        | ray_right(move, player, opponent, 7, HORIZONTAL_MASK)
        | ray_left(move, player, opponent, 9, HORIZONTAL_MASK)
        | ray_right(move, player, opponent, 9, HORIZONTAL_MASK)
        | ray_left(move, player, opponent, 8, FULL_BOARD)
        | ray_right(move, player, opponent, 8, FULL_BOARD)
    )


def child_relative(player: int, opponent: int, cell: int) -> str:
    move = 1 << cell
    flips = flips_for(move, player, opponent)
    if flips == 0:
        raise ValueError(f"move {cell} has no flips")
    player_after = player | move | flips
    opponent_after = opponent & ~flips
    # Child side to move is the old opponent: swap X/O perspective.
    result = ["-"] * 64
    for index in range(64):
        bit = 1 << index
        if opponent_after & bit:
            result[index] = "X"
        elif player_after & bit:
            result[index] = "O"
    return "".join(result)


def phase_for(board: str) -> int:
    stones = 64 - board.count("-")
    return max(0, min(3, (stones - 4) // 10 - 2))


class PolicyStream(IterableDataset[dict[str, Any]]):
    def __init__(
        self,
        paths: Sequence[Path],
        split: str,
        *,
        seed: int,
        augment_d4: bool,
        color_mode: str,
        strict: bool = True,
    ):
        super().__init__()
        self.paths = tuple(paths)
        self.split = split
        self.seed = seed
        self.augment_d4 = augment_d4
        self.color_mode = color_mode
        self.strict = strict
        self.epoch = 0

    def set_epoch(self, epoch: int) -> None:
        self.epoch = epoch

    def __iter__(self) -> Iterator[dict[str, Any]]:
        epoch_seed = self.seed + self.epoch * 1_000_003
        paths = list(self.paths)
        if self.split == "train":
            # Every worker must derive the same global order before taking its
            # disjoint strided slice.
            random.Random(epoch_seed).shuffle(paths)
        worker = get_worker_info()
        if worker is not None:
            paths = paths[worker.id::worker.num_workers]
            rng = random.Random(epoch_seed + (worker.id + 1) * 97_409)
        else:
            rng = random.Random(epoch_seed)
        for path in paths:
            with path.open("r", encoding="utf-8", errors="strict") as source:
                for line_number, raw in enumerate(source, 1):
                    try:
                        teacher = parse_teacher(raw, path, line_number)
                        if teacher is None:
                            continue
                        board, teacher_move = teacher.board, teacher.move
                        if self.augment_d4:
                            board, teacher_move = transform(board, teacher_move, rng.randrange(8))
                        own, opponent = relative_bits(board)
                        legal = legal_moves_bits(own, opponent)
                        if legal.bit_count() < 2:
                            raise ValueError("policy root must have multiple legal moves")
                        if legal & (1 << teacher_move) == 0:
                            raise ValueError("teacher move is not legal")
                        moves: list[int] = []
                        children: list[str] = []
                        remaining = legal
                        while remaining:
                            bit = remaining & -remaining
                            cell = bit.bit_length() - 1
                            moves.append(cell)
                            children.append(child_relative(own, opponent, cell))
                            remaining ^= bit
                        target = moves.index(teacher_move)
                        if self.color_mode == "random":
                            root_player = rng.randrange(2)
                        elif self.color_mode == "black":
                            root_player = 0
                        else:
                            raise ValueError(f"unknown color_mode: {self.color_mode}")
                        child_player = 1 - root_player
                        features = [
                            feature_tensors(features_from_relative(child, child_player))
                            for child in children
                        ]
                        yield {
                            "children": features,
                            "target": target,
                            "phase": phase_for(board),
                        }
                    except (ValueError, UnicodeError):
                        if self.strict:
                            raise


def collate_policy(samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        raise ValueError("empty policy batch")
    keys = tuple(samples[0]["children"][0].keys())
    flat = [child for sample in samples for child in sample["children"]]
    children = {key: torch.stack([child[key] for child in flat]) for key in keys}
    return {
        "children": children,
        "counts": [len(sample["children"]) for sample in samples],
        "targets": [int(sample["target"]) for sample in samples],
        "phases": [int(sample["phase"]) for sample in samples],
    }


def move_batch(batch: dict[str, Tensor], device: torch.device) -> dict[str, Tensor]:
    return {key: value.to(device=device, non_blocking=True) for key, value in batch.items()}


@dataclass
class Metrics:
    roots: int = 0
    loss_sum: float = 0.0
    top1: int = 0
    top3: int = 0
    phase_counts: Counter[int] | None = None

    def __post_init__(self) -> None:
        if self.phase_counts is None:
            self.phase_counts = Counter()

    def result(self) -> dict[str, Any]:
        return {
            "roots": self.roots,
            "cross_entropy": self.loss_sum / max(1, self.roots),
            "top1": self.top1 / max(1, self.roots),
            "top3": self.top3 / max(1, self.roots),
            "phase_counts": dict(sorted((self.phase_counts or {}).items())),
        }


def listwise_loss(
    raw_child_values: Tensor,
    counts: Sequence[int],
    targets: Sequence[int],
) -> tuple[Tensor, int, int]:
    if len(counts) != len(targets) or not counts:
        raise ValueError("counts and targets must be non-empty and equally sized")
    if any(count <= 0 for count in counts):
        raise ValueError("every policy root must have at least one legal child")
    if any(target < 0 or target >= count for target, count in zip(targets, counts)):
        raise ValueError("policy target is outside its legal-child range")
    if sum(counts) != raw_child_values.numel():
        raise ValueError("policy child counts do not match model output")

    # Child raw values are from the child side's perspective. Splitting and
    # padding keeps the entire ragged batch on the GPU; there is no per-root
    # .item() synchronization.
    segments = torch.split(-raw_child_values, tuple(int(count) for count in counts))
    logits = pad_sequence(
        segments, batch_first=True, padding_value=-torch.inf,
    )
    target_tensor = torch.as_tensor(
        targets, dtype=torch.long, device=raw_child_values.device,
    )

    loss = F.cross_entropy(logits, target_tensor)
    top1_tensor = (torch.argmax(logits, dim=1) == target_tensor).sum()
    top_k = min(3, logits.shape[1])
    top3_tensor = (
        torch.topk(logits, k=top_k, dim=1).indices == target_tensor.unsqueeze(1)
    ).any(dim=1).sum()
    top1, top3 = torch.stack((top1_tensor, top3_tensor)).detach().cpu().tolist()
    return loss, int(top1), int(top3)


def run_loader(
    model: JavaCompatibleEvaluator,
    loader: DataLoader[dict[str, Any]],
    device: torch.device,
    *,
    optimizer: torch.optim.Optimizer | None,
    gradient_clip: float,
    label: str,
    quiet: bool,
    total_roots: int,
    max_steps: int = 0,
) -> Metrics:
    training = optimizer is not None
    model.train(training)
    metrics = Metrics()
    started = time.monotonic()
    last = started
    for step, batch in enumerate(loader, 1):
        if max_steps and step > max_steps:
            break
        children = move_batch(batch["children"], device)
        with torch.set_grad_enabled(training):
            raw = model(children)
            loss, top1, top3 = listwise_loss(raw, batch["counts"], batch["targets"])
            if training:
                assert optimizer is not None
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                if gradient_clip > 0:
                    torch.nn.utils.clip_grad_norm_(model.parameters(), gradient_clip)
                optimizer.step()
        roots = len(batch["counts"])
        metrics.roots += roots
        metrics.loss_sum += float(loss.detach().cpu()) * roots
        metrics.top1 += top1
        metrics.top3 += top3
        assert metrics.phase_counts is not None
        metrics.phase_counts.update(batch["phases"])
        now = time.monotonic()
        if not quiet and now - last >= 1.0:
            rate = metrics.roots / max(0.001, now - started)
            fraction = min(1.0, metrics.roots / max(1, total_roots))
            filled = min(24, int(fraction * 24))
            eta = (
                (now - started) * max(0, total_roots - metrics.roots)
                / metrics.roots
            )
            print(
                f"\r[{label}] |{'#' * filled}{'.' * (24 - filled)}| "
                f"{metrics.roots:,}/{total_roots:,} ({fraction * 100:5.1f}%) | "
                f"{rate:,.0f} roots/s | {duration_text(now - started)} elapsed | "
                f"{duration_text(eta)} ETA | "
                f"CE {metrics.loss_sum / metrics.roots:.5f}",
                end="",
                file=sys.stderr,
                flush=True,
            )
            last = now
    if metrics.roots == 0:
        raise RuntimeError(f"{label} yielded no roots")
    if max_steps == 0 and metrics.roots != total_roots:
        raise RuntimeError(
            f"{label} full pass yielded {metrics.roots:,} roots, "
            f"but manifest requires {total_roots:,}"
        )
    if not quiet:
        now = time.monotonic()
        rate = metrics.roots / max(0.001, now - started)
        fraction = min(1.0, metrics.roots / max(1, total_roots))
        filled = min(24, int(fraction * 24))
        print(
            f"\r[{label}] |{'#' * filled}{'.' * (24 - filled)}| "
            f"{metrics.roots:,}/{total_roots:,} ({fraction * 100:5.1f}%) | "
            f"{rate:,.0f} roots/s | {duration_text(now - started)} elapsed | "
            f"00:00:00 ETA | CE {metrics.loss_sum / max(1, metrics.roots):.5f}",
            file=sys.stderr,
        )
    return metrics


def resolve_paths(patterns: Sequence[str]) -> list[Path]:
    result: set[Path] = set()
    for pattern in patterns:
        absolute = Path(pattern)
        if not absolute.is_absolute():
            absolute = PROJECT_ROOT / absolute
        result.update(Path(value).resolve() for value in glob.glob(str(absolute), recursive=True))
    return sorted((path for path in result if path.is_file()), key=lambda path: str(path).casefold())


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        config = json.load(source)
    if config.get("feature_schema") != FEATURE_SCHEMA:
        raise ValueError(f"feature_schema must be {FEATURE_SCHEMA}")
    return config


def require_policy_hash_contract(manifest: dict[str, Any]) -> None:
    split = manifest.get("split")
    if not isinstance(split, dict):
        raise RuntimeError("policy manifest has no split contract")
    if split.get("algorithm") != POLICY_SPLIT_ALGORITHM:
        raise RuntimeError(
            "policy manifest split algorithm is not the value-data algorithm"
        )
    if split.get("unit") != POLICY_SPLIT_UNIT:
        raise RuntimeError("policy manifest split unit is not canonical-D4 board")
    if str(split.get("seed")) != POLICY_SPLIT_SEED:
        raise RuntimeError("policy manifest split seed differs from value data")
    ratios = split.get("ratios")
    if not isinstance(ratios, dict) or set(ratios) != set(SPLITS):
        raise RuntimeError("policy manifest has invalid split ratios")
    for name in SPLITS:
        try:
            actual = float(ratios[name])
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                f"policy manifest has invalid {name} split ratio"
            ) from error
        if not math.isclose(
            actual, POLICY_SPLIT_RATIOS[name], rel_tol=0.0, abs_tol=1e-12
        ):
            raise RuntimeError(
                f"policy manifest {name} split ratio differs from value data"
            )

    # Sampling and train/val/test assignment are different hash operations.
    # Require the unambiguous nested sampling contract instead of treating the
    # legacy top-level hash_algorithm as the split algorithm.
    sample = manifest.get("sample")
    top_level_sample_algorithm = manifest.get("hash_algorithm")
    if not isinstance(sample, dict):
        raise RuntimeError("policy manifest has no valid nested sample contract")
    if sample.get("algorithm") != POLICY_SAMPLE_ALGORITHM:
        raise RuntimeError("policy manifest sample hash algorithm differs")
    if sample.get("unit") != POLICY_SAMPLE_UNIT:
        raise RuntimeError("policy manifest sample hash unit differs")
    if sample.get("seed") != POLICY_SAMPLE_SEED:
        raise RuntimeError("policy manifest sample seed differs")
    if (
        type(sample.get("numerator")) is not int
        or sample["numerator"] != POLICY_SAMPLE_NUMERATOR
    ):
        raise RuntimeError("policy manifest sample numerator differs")
    if (
        type(sample.get("denominator")) is not int
        or sample["denominator"] != POLICY_SAMPLE_DENOMINATOR
    ):
        raise RuntimeError("policy manifest sample denominator differs")
    if (
        top_level_sample_algorithm is not None
        and top_level_sample_algorithm != sample["algorithm"]
    ):
        raise RuntimeError("policy manifest sample hash algorithms disagree")


def require_policy_provenance(manifest: dict[str, Any]) -> None:
    upstream_sha256 = manifest.get("upstream_manifest_sha256")
    if (
        not isinstance(upstream_sha256, str)
        or len(upstream_sha256) != 64
        or any(character not in "0123456789abcdef" for character in upstream_sha256)
    ):
        raise RuntimeError(
            "policy manifest has no valid lowercase upstream manifest SHA-256"
        )
    if manifest.get("source_paths_matched_upstream") is not True:
        raise RuntimeError("policy source paths were not matched to upstream")
    fingerprints_verified = manifest.get("source_fingerprints_verified")
    if type(fingerprints_verified) is not int or fingerprints_verified != 5_200:
        raise RuntimeError(
            "policy manifest did not verify all 5,200 source fingerprints"
        )
    if manifest.get("all_source_fingerprints_matched") is not True:
        raise RuntimeError("policy source fingerprints did not all match upstream")


def load_policy_manifest(config: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    manifest_path = Path(config["data"]["manifest"])
    if not manifest_path.is_absolute():
        manifest_path = PROJECT_ROOT / manifest_path
    manifest_path = manifest_path.resolve()
    with manifest_path.open("r", encoding="utf-8") as source:
        manifest = json.load(source)
    if manifest.get("status") != "verified-full":
        raise RuntimeError("policy manifest is not verified-full")
    if manifest.get("dataset_kind") != "egaroucid_policy_teacher_v1":
        raise RuntimeError("unexpected policy dataset kind")
    if manifest.get("feature_schema") != FEATURE_SCHEMA:
        raise RuntimeError("policy feature schema mismatch")
    if manifest.get("row_schema") != (
        "relative-board-64 teacher-move-a1h8 multi-legal-roots-only"
    ):
        raise RuntimeError("policy row schema mismatch")
    if manifest.get("upstream_verification") != (
        "egaroucid-v2-manifest-verified-full"
    ):
        raise RuntimeError("policy manifest has no verified v2 provenance")
    if int(manifest.get("schema_version", -1)) != 1:
        raise RuntimeError("unsupported policy manifest schema")
    if int(manifest.get("source_files", -1)) != 5_200 or int(
        manifest.get("source_games", -1)
    ) != 52_000_000:
        raise RuntimeError("policy manifest is not the complete v0002 source set")
    require_policy_hash_contract(manifest)
    require_policy_provenance(manifest)
    by_split = manifest.get("by_split")
    if not isinstance(by_split, dict) or set(by_split) != set(SPLITS):
        raise RuntimeError("policy manifest has invalid split counts")
    if any(int(by_split[split]) <= 0 for split in SPLITS):
        raise RuntimeError("policy manifest contains an empty split")
    if sum(int(by_split[split]) for split in SPLITS) != int(
        manifest.get("selected_records", -1)
    ):
        raise RuntimeError("policy manifest split counts do not add up")
    raw_phases = manifest.get("by_split_and_phase")
    if not isinstance(raw_phases, dict) or set(raw_phases) != set(SPLITS):
        raise RuntimeError("policy manifest has invalid phase counts")
    for split in SPLITS:
        phase_counts = raw_phases[split]
        if not isinstance(phase_counts, dict) or {
            int(phase) for phase in phase_counts
        } != {0, 1, 2, 3}:
            raise RuntimeError(f"policy manifest has invalid {split} phase coverage")
        if sum(int(count) for count in phase_counts.values()) != int(
            by_split[split]
        ):
            raise RuntimeError(f"policy manifest {split} phase counts do not add up")
    return manifest_path, manifest


def verify(config: dict[str, Any], *, scan: bool, quiet: bool) -> dict[str, Any]:
    data = config["data"]
    manifest_path, manifest = load_policy_manifest(config)
    paths = {split: resolve_paths(data["paths_by_split"][split]) for split in SPLITS}
    expected_shards = int(manifest["source_files"])
    if any(len(paths[split]) != expected_shards for split in SPLITS):
        raise RuntimeError(
            "policy shard count differs from the full conversion: "
            + str({split: len(paths[split]) for split in SPLITS})
        )
    result: dict[str, Any] = {
        "manifest": str(manifest_path),
        "status": manifest["status"],
        "selected_records": int(manifest["selected_records"]),
        "shards": {split: len(paths[split]) for split in SPLITS},
    }
    if scan:
        counts = Counter()
        phases = {split: Counter() for split in SPLITS}
        started = time.monotonic()
        for split in SPLITS:
            for path in paths[split]:
                try:
                    random_plies = int(path.parent.name)
                except ValueError as error:
                    raise RuntimeError(f"policy shard parent is not random ply: {path}") from error
                with path.open("r", encoding="utf-8") as source:
                    for line_number, raw in enumerate(source, 1):
                        record = parse_teacher(raw, path, line_number)
                        if record is not None:
                            own, opponent = relative_bits(record.board)
                            legal = legal_moves_bits(own, opponent)
                            if legal.bit_count() < 2 or (
                                legal & (1 << record.move)
                            ) == 0:
                                raise RuntimeError(
                                    f"{path}:{line_number}: invalid multi-legal teacher"
                                )
                            counts[split] += 1
                            phases[split][phase_for(record.board)] += 1
                if not quiet and time.monotonic() - started >= 1:
                    print(
                        f"\r[policy verify] {sum(counts.values()):,} rows",
                        end="", file=sys.stderr, flush=True,
                    )
                    started = time.monotonic()
        if not quiet:
            print(file=sys.stderr)
        expected = {key: int(value) for key, value in manifest["by_split"].items()}
        if dict(counts) != expected:
            raise RuntimeError(f"policy row counts differ: expected={expected}, actual={dict(counts)}")
        result["rows"] = dict(counts)
        result["phases"] = {split: dict(phases[split]) for split in SPLITS}
        expected_phases = {
            split: {
                int(phase): int(count)
                for phase, count in manifest["by_split_and_phase"][split].items()
            }
            for split in SPLITS
        }
        if {
            split: dict(phases[split]) for split in SPLITS
        } != expected_phases:
            raise RuntimeError("policy phase counts differ from manifest")
    return result


def next_candidate(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    digits = ""
    while stem and stem[-1].isdigit():
        digits = stem[-1] + digits
        stem = stem[:-1]
    if not digits:
        raise FileExistsError(f"refusing to overwrite candidate: {path}")
    number = int(digits)
    while True:
        number += 1
        candidate = path.with_name(f"{stem}{number:0{len(digits)}d}{path.suffix}")
        if not candidate.exists():
            return candidate


def choose_device(value: str) -> torch.device:
    if value == "auto":
        return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    device = torch.device(value)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but this PyTorch build cannot use CUDA")
    return device


def parameter_init_path(
    config: dict[str, Any], override: Path | None,
) -> Path:
    path = override if override is not None else Path(config["parameter_init"])
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"policy initial parameter was not found: {path}")
    return path


def training_contract(config: dict[str, Any], init_path: Path) -> dict[str, Any]:
    contract = {
        "dataset_kind": config.get("dataset_kind"),
        "feature_schema": config.get("feature_schema"),
        "seed": config.get("seed"),
        "model": config.get("model"),
        "data": config.get("data"),
        "training": config.get("training"),
        "parameter_init": str(init_path),
        "parameter_init_sha256": hashlib.sha256(init_path.read_bytes()).hexdigest(),
    }
    encoded = json.dumps(
        contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    contract["sha256"] = hashlib.sha256(encoded).hexdigest()
    return contract


def validate_checkpoint(
    checkpoint: Any,
    *,
    contract: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    if not isinstance(checkpoint, dict):
        raise RuntimeError(f"{label} is not a checkpoint object")
    if checkpoint.get("checkpoint_format") != "othello-policy-checkpoint-v1":
        raise RuntimeError(f"{label} has an unsupported checkpoint format")
    if checkpoint.get("feature_schema") != FEATURE_SCHEMA:
        raise RuntimeError(f"{label} feature schema differs")
    saved_contract = checkpoint.get("training_contract")
    if not isinstance(saved_contract, dict) or (
        saved_contract.get("sha256") != contract["sha256"]
    ):
        raise RuntimeError(f"{label} training config or initial parameter differs")
    if not isinstance(checkpoint.get("epoch"), int):
        raise RuntimeError(f"{label} has no completed epoch")
    best_loss = float(checkpoint.get("best_validation_cross_entropy", math.nan))
    if not math.isfinite(best_loss):
        raise RuntimeError(f"{label} has an invalid best validation loss")
    initial_validation = checkpoint.get("initial_validation")
    if not isinstance(initial_validation, dict) or not math.isfinite(
        float(initial_validation.get("cross_entropy", math.nan))
    ):
        raise RuntimeError(f"{label} has no valid initial validation metrics")
    if "model" not in checkpoint or "optimizer" not in checkpoint:
        raise RuntimeError(f"{label} is missing model or optimizer state")
    return checkpoint


def unique_run_directory(root: Path, timestamp: str) -> Path:
    candidate = root / timestamp
    suffix = 1
    while candidate.exists():
        candidate = root / f"{timestamp}_{suffix}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def make_loaders(
    config: dict[str, Any],
    device: torch.device,
) -> tuple[dict[str, PolicyStream], dict[str, DataLoader[dict[str, Any]]]]:
    data = config["data"]
    training = config["training"]
    paths = {split: resolve_paths(data["paths_by_split"][split]) for split in SPLITS}
    seed = int(config["seed"])
    num_workers = int(training.get("num_workers", 0))
    if num_workers < 0:
        raise ValueError("training.num_workers must be non-negative")
    pin_memory = bool(training.get("pin_memory", False)) and device.type == "cuda"
    streams = {
        "train": PolicyStream(
            paths["train"], "train", seed=seed, augment_d4=True,
            color_mode="random", strict=True,
        ),
        "val": PolicyStream(
            paths["val"], "val", seed=seed + 1, augment_d4=False,
            color_mode="black", strict=True,
        ),
        "test": PolicyStream(
            paths["test"], "test", seed=seed + 2, augment_d4=False,
            color_mode="black", strict=True,
        ),
    }
    loaders = {
        split: DataLoader(
            stream,
            batch_size=int(training["batch_size"]),
            num_workers=num_workers,
            pin_memory=pin_memory,
            collate_fn=collate_policy,
        )
        for split, stream in streams.items()
    }
    return streams, loaders


def train(config: dict[str, Any], args: argparse.Namespace) -> Path:
    device = choose_device(args.device or config["training"].get("device", "auto"))
    torch.manual_seed(int(config["seed"]))
    if device.type == "cuda":
        torch.cuda.manual_seed_all(int(config["seed"]))
    dtype = torch.float32 if config["model"].get("dtype", "float32") == "float32" else torch.float64
    model = JavaCompatibleEvaluator(dtype).to(device)
    init_path = parameter_init_path(config, args.init)
    model.load_java_parameters(init_path)
    streams, loaders = make_loaders(config, device)
    training = config["training"]
    _manifest_path, policy_manifest = load_policy_manifest(config)
    split_totals = {
        split: int(policy_manifest["by_split"][split]) for split in SPLITS
    }
    batch_size = int(training["batch_size"])

    def progress_total(split: str, step_key: str) -> int:
        max_steps = int(training.get(step_key, 0))
        if max_steps <= 0:
            return split_totals[split]
        return min(split_totals[split], batch_size * max_steps)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(training["learning_rate"]),
        weight_decay=float(training.get("weight_decay", 0.0)),
    )
    contract = training_contract(config, init_path)
    start_epoch = 0
    best_loss = math.inf
    initial_validation: dict[str, Any] | None = None
    resume_path: Path | None = None
    resumed_state: dict[str, Any] | None = None
    inherited_best: dict[str, Any] | None = None
    if args.resume is not None:
        resume_path = args.resume
        if not resume_path.is_absolute():
            resume_path = PROJECT_ROOT / resume_path
        resume_path = resume_path.resolve()
        if not resume_path.is_file():
            raise FileNotFoundError(f"policy resume checkpoint was not found: {resume_path}")
        resumed = validate_checkpoint(
            torch.load(resume_path, map_location=device, weights_only=False),
            contract=contract,
            label="policy resume checkpoint",
        )
        resumed_state = resumed
        previous_best_path = resume_path.parent / "checkpoint_best.pt"
        if not previous_best_path.is_file():
            raise FileNotFoundError(
                f"policy best checkpoint was not found beside resume file: "
                f"{previous_best_path}"
            )
        inherited_best = validate_checkpoint(
            torch.load(previous_best_path, map_location=device, weights_only=False),
            contract=contract,
            label="policy inherited best checkpoint",
        )
        resumed_best = float(resumed["best_validation_cross_entropy"])
        inherited_best_loss = float(
            inherited_best["best_validation_cross_entropy"]
        )
        if not math.isclose(
            resumed_best, inherited_best_loss, rel_tol=0.0, abs_tol=1e-12,
        ):
            raise RuntimeError(
                "policy resume and checkpoint_best disagree on validation loss"
            )
        if resumed["initial_validation"] != inherited_best["initial_validation"]:
            raise RuntimeError(
                "policy resume and checkpoint_best disagree on initial validation"
            )
        model.load_state_dict(resumed["model"])
        optimizer.load_state_dict(resumed["optimizer"])
        start_epoch = int(resumed["epoch"]) + 1
        best_loss = resumed_best
        initial_validation = dict(resumed["initial_validation"])

    run_root = PROJECT_ROOT / config["output"]["runs_dir"]
    run_dir = unique_run_directory(
        run_root, datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ"),
    )
    metrics_path = run_dir / "metrics.jsonl"
    best_path = run_dir / "checkpoint_best.pt"
    epochs = int(training["epochs"])
    if epochs <= 0:
        raise ValueError("training.epochs must be positive")
    if inherited_best is not None:
        torch.save(inherited_best, best_path)
        assert resumed_state is not None
        torch.save(resumed_state, run_dir / "checkpoint_last.pt")
    run_manifest = {
        "feature_schema": FEATURE_SCHEMA,
        "device": str(device),
        "parameter_init": str(init_path),
        "training_contract_sha256": contract["sha256"],
        "resume_checkpoint": None if resume_path is None else str(resume_path),
        "start_epoch": start_epoch,
        "configured_epochs": epochs,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if inherited_best is None:
        initial_metrics = run_loader(
            model, loaders["val"], device, optimizer=None, gradient_clip=0.0,
            label="policy initial validation", quiet=args.quiet,
            total_roots=progress_total("val", "validation_steps"),
            max_steps=int(training.get("validation_steps", 0)),
        )
        initial_validation = initial_metrics.result()
        best_loss = float(initial_validation["cross_entropy"])
        initial_checkpoint = {
            "checkpoint_format": "othello-policy-checkpoint-v1",
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "epoch": -1,
            "config": config,
            "feature_schema": FEATURE_SCHEMA,
            "training_contract": contract,
            "best_validation_cross_entropy": best_loss,
            "initial_validation": initial_validation,
        }
        torch.save(initial_checkpoint, best_path)
        torch.save(initial_checkpoint, run_dir / "checkpoint_last.pt")
        with metrics_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps({
                "event": "initial_validation",
                "epoch": -1,
                "val": initial_validation,
            }, ensure_ascii=False, sort_keys=True) + "\n")
    assert initial_validation is not None

    for epoch in range(start_epoch, epochs):
        streams["train"].set_epoch(epoch)
        train_metrics = run_loader(
            model, loaders["train"], device, optimizer=optimizer,
            gradient_clip=float(training.get("gradient_clip", 0.0)),
            label=f"policy epoch {epoch + 1}/{epochs} train", quiet=args.quiet,
            total_roots=progress_total("train", "steps_per_epoch"),
            max_steps=int(training.get("steps_per_epoch", 0)),
        )
        val_metrics = run_loader(
            model, loaders["val"], device, optimizer=None, gradient_clip=0.0,
            label=f"policy epoch {epoch + 1}/{epochs} val", quiet=args.quiet,
            total_roots=progress_total("val", "validation_steps"),
            max_steps=int(training.get("validation_steps", 0)),
        )
        event = {
            "epoch": epoch,
            "train": train_metrics.result(),
            "val": val_metrics.result(),
        }
        with metrics_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        val_loss = float(event["val"]["cross_entropy"])
        improved = val_loss < best_loss
        if improved:
            best_loss = val_loss
        checkpoint = {
            "checkpoint_format": "othello-policy-checkpoint-v1",
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "epoch": epoch,
            "config": config,
            "feature_schema": FEATURE_SCHEMA,
            "training_contract": contract,
            "best_validation_cross_entropy": best_loss,
            "initial_validation": initial_validation,
        }
        torch.save(checkpoint, run_dir / "checkpoint_last.pt")
        if improved:
            torch.save(checkpoint, best_path)
    if not best_path.is_file():
        raise RuntimeError(
            "policy training produced no best checkpoint; "
            "resume from a compatible completed epoch or increase training.epochs"
        )
    saved = validate_checkpoint(
        torch.load(best_path, map_location=device, weights_only=False),
        contract=contract,
        label="policy selected best checkpoint",
    )
    model.load_state_dict(saved["model"])
    test_metrics = run_loader(
        model, loaders["test"], device, optimizer=None, gradient_clip=0.0,
        label="policy test", quiet=args.quiet,
        total_roots=progress_total("test", "test_steps"),
        max_steps=int(training.get("test_steps", 0)),
    )
    with metrics_path.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"event": "test", "test": test_metrics.result()}) + "\n")
    requested = PROJECT_ROOT / config["output"]["candidate_path"]
    candidate = next_candidate(requested)
    export_java_parameters(model, candidate)
    manifest = {
        "candidate_path": str(candidate.resolve()),
        "feature_schema": FEATURE_SCHEMA,
        "best_validation_cross_entropy": best_loss,
        "initial_validation": initial_validation,
        "test": test_metrics.result(),
        "parameter_count": 25436,
        "parameter_init": str(init_path),
        "training_contract_sha256": contract["sha256"],
        "resume_checkpoint": None if resume_path is None else str(resume_path),
        "best_epoch": int(saved["epoch"]),
    }
    (run_dir / "export_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({"event": "policy_export", **manifest}, ensure_ascii=False))
    return candidate


def self_test(config: dict[str, Any], init_override: Path | None = None) -> None:
    hash_contract = {
        "split": {
            "algorithm": POLICY_SPLIT_ALGORITHM,
            "unit": POLICY_SPLIT_UNIT,
            "seed": POLICY_SPLIT_SEED,
            "ratios": dict(POLICY_SPLIT_RATIOS),
        },
        "sample": {
            "algorithm": POLICY_SAMPLE_ALGORITHM,
            "unit": POLICY_SAMPLE_UNIT,
            "seed": POLICY_SAMPLE_SEED,
            "numerator": POLICY_SAMPLE_NUMERATOR,
            "denominator": POLICY_SAMPLE_DENOMINATOR,
        },
    }
    require_policy_hash_contract(hash_contract)
    invalid_hash_contract = json.loads(json.dumps(hash_contract))
    invalid_hash_contract["split"]["algorithm"] = "fnv1a64-canonical-d4-v1"
    try:
        require_policy_hash_contract(invalid_hash_contract)
    except RuntimeError:
        pass
    else:
        raise AssertionError("policy split contract accepted the wrong algorithm")
    invalid_sample_contracts = []
    missing_sample = json.loads(json.dumps(hash_contract))
    del missing_sample["sample"]
    invalid_sample_contracts.append(missing_sample)
    wrong_sample_algorithm = json.loads(json.dumps(hash_contract))
    wrong_sample_algorithm["sample"]["algorithm"] = POLICY_SPLIT_ALGORITHM
    invalid_sample_contracts.append(wrong_sample_algorithm)
    wrong_sample_seed = json.loads(json.dumps(hash_contract))
    wrong_sample_seed["sample"]["seed"] = "20260721"
    invalid_sample_contracts.append(wrong_sample_seed)
    wrong_sample_denominator = json.loads(json.dumps(hash_contract))
    wrong_sample_denominator["sample"]["denominator"] = 8
    invalid_sample_contracts.append(wrong_sample_denominator)
    for invalid_sample in invalid_sample_contracts:
        try:
            require_policy_hash_contract(invalid_sample)
        except RuntimeError:
            pass
        else:
            raise AssertionError("policy sample contract accepted invalid metadata")

    provenance_contract = {
        "upstream_manifest_sha256": "a" * 64,
        "source_paths_matched_upstream": True,
        "source_fingerprints_verified": 5_200,
        "all_source_fingerprints_matched": True,
    }
    require_policy_provenance(provenance_contract)
    invalid_provenance_contracts = []
    missing_sha = dict(provenance_contract)
    del missing_sha["upstream_manifest_sha256"]
    invalid_provenance_contracts.append(missing_sha)
    paths_not_matched = dict(provenance_contract)
    paths_not_matched["source_paths_matched_upstream"] = False
    invalid_provenance_contracts.append(paths_not_matched)
    incomplete_fingerprints = dict(provenance_contract)
    incomplete_fingerprints["source_fingerprints_verified"] = 5_199
    invalid_provenance_contracts.append(incomplete_fingerprints)
    fingerprints_not_matched = dict(provenance_contract)
    fingerprints_not_matched["all_source_fingerprints_matched"] = False
    invalid_provenance_contracts.append(fingerprints_not_matched)
    for invalid_provenance in invalid_provenance_contracts:
        try:
            require_policy_provenance(invalid_provenance)
        except RuntimeError:
            pass
        else:
            raise AssertionError("policy provenance contract accepted invalid metadata")

    initial = "---------------------------OX------XO---------------------------"
    teacher = coordinate_to_cell("d3")
    for variant in range(8):
        board, move = transform(initial, teacher, variant)
        own, opponent = relative_bits(board)
        legal = legal_moves_bits(own, opponent)
        if legal & (1 << move) == 0:
            raise AssertionError("D4 transformed teacher became illegal")
        children = []
        remaining = legal
        while remaining:
            bit = remaining & -remaining
            children.append(child_relative(own, opponent, bit.bit_length() - 1))
            remaining ^= bit
        if len(children) != 4:
            raise AssertionError("initial position must have four children")
    init_path = parameter_init_path(config, init_override)
    model = JavaCompatibleEvaluator(torch.float32)
    model.load_java_parameters(init_path)
    features = [feature_tensors(features_from_relative(child, 1)) for child in children]
    batch = {key: torch.stack([item[key] for item in features]) for key in features[0]}
    raw = model(batch)
    loss, _, _ = listwise_loss(raw, [4], [0])
    loss.backward()
    if not math.isfinite(float(loss.detach())):
        raise AssertionError("policy loss is not finite")
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
    contract = training_contract(config, init_path)
    validation = {"cross_entropy": float(loss.detach())}
    validate_checkpoint({
        "checkpoint_format": "othello-policy-checkpoint-v1",
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "epoch": -1,
        "feature_schema": FEATURE_SCHEMA,
        "training_contract": contract,
        "best_validation_cross_entropy": validation["cross_entropy"],
        "initial_validation": validation,
    }, contract=contract, label="self-test checkpoint")
    print(
        "SELF-TEST PASS: d4-move=yes legal-children=yes "
        "raw-listwise-ce=yes checkpoint-contract=yes split-contract=yes "
        "provenance-contract=yes"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--stage", choices=("verify", "train", "all"), default="all")
    parser.add_argument("--device", help="auto, cpu, cuda, cuda:0, ...")
    parser.add_argument(
        "--init",
        type=Path,
        help="value candidate used to initialise policy; config baseline if omitted",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        help="compatible checkpoint_last.pt; resumes at the next completed epoch",
    )
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config.resolve())
    if args.self_test:
        self_test(config, args.init)
        return 0
    if args.dry_run:
        print(json.dumps({
            "stage": args.stage,
            "manifest": config["data"]["manifest"],
            "device": args.device or config["training"].get("device", "auto"),
            "candidate": config["output"]["candidate_path"],
            "parameter_init": str(parameter_init_path(config, args.init)),
            "resume": None if args.resume is None else str(args.resume),
        }, ensure_ascii=False, indent=2))
        return 0
    if args.stage in {"verify", "all"}:
        print(json.dumps(verify(config, scan=True, quiet=args.quiet), ensure_ascii=False))
    if args.stage in {"train", "all"}:
        train(config, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
