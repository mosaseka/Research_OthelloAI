"""Train an original_11 Java-compatible value evaluator.

Expected source line (Egaroucid 7.4/7.5 position dataset):

    -XO-...-OOOX-O- 4

The first token has 64 cells in a1..h8 order.  X is always the side to move,
O is its opponent, and '-' is empty.  The second token is the expected final
disc difference from X's perspective.  Files are streamed and are never copied
into the repository by this program.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import glob
import gzip
import hashlib
import io
import itertools
import json
import math
from pathlib import Path
import random
import re
import shutil
import tempfile
import time
from typing import Any, Iterable, Iterator, Sequence, TextIO
import uuid
import zipfile

try:
    import torch
    from torch import Tensor
    from torch.utils.data import DataLoader, Dataset, IterableDataset, default_collate
except ImportError as error:  # pragma: no cover - depends on local environment
    raise ImportError(
        "PyTorch is required for training. Install it using the command shown "
        "at https://pytorch.org/get-started/locally/ and rerun this script."
    ) from error

from evaluator_model import (
    EXPECTED_PARAMETER_COUNT,
    JavaCompatibleEvaluator,
    absolute_from_relative,
    export_java_parameters,
    feature_tensors,
    features_from_relative,
    read_parameter_values,
)
from java_eval import Evaluator as ReferenceEvaluator
from progress import ProgressReporter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "value_11a_fresh.json"
SPLIT_NAMES = ("train", "val", "test")
PHASES = (0, 1, 2, 3)
PREPARED_MANIFEST_SCHEMA_VERSION = 2
PREPARED_SPLIT_ALGORITHM = "sha256-canonical-d4-board-v1"
PREPARED_SPLIT_UNIT = "canonical_d4_relative_board"
EXPECTED_V0002_SOURCE_FILES = 5_200
EXPECTED_V0002_SOURCE_GAMES = 52_000_000
_PREPARED_ROW = re.compile(
    rb"[XO-]{64} (?:0|-[1-9][0-9]*|[1-9][0-9]*)\n"
)
CHECKPOINT_FORMAT_VERSION = 2
LEGACY_CHECKPOINT_FORMAT_VERSION = 1
FORBIDDEN_DIAGNOSTIC_ROOT = (PROJECT_ROOT / "diagnostics").resolve()


@dataclass(frozen=True)
class SourceRecord:
    board: str
    score: float
    path: str
    line_number: int


class DataFormatError(ValueError):
    pass


def _open_text(path: Path) -> TextIO:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="strict")
    return path.open("r", encoding="utf-8", errors="strict")


def parse_source_line(raw: str, path: str | Path, line_number: int) -> SourceRecord | None:
    stripped = raw.strip()
    if not stripped:
        return None
    fields = stripped.split()
    if len(fields) != 2:
        raise DataFormatError(
            f"{path}:{line_number}: expected '<64 X/O/- cells> <score>', got {len(fields)} fields"
        )
    board, raw_score = fields
    if len(board) != 64 or set(board) - {"X", "O", "-"}:
        raise DataFormatError(
            f"{path}:{line_number}: board must contain exactly 64 X/O/- characters"
        )
    stones = 64 - board.count("-")
    if not 4 <= stones <= 64:
        raise DataFormatError(f"{path}:{line_number}: invalid occupied-cell count {stones}")
    try:
        score = float(raw_score)
    except ValueError as error:
        raise DataFormatError(f"{path}:{line_number}: invalid score {raw_score!r}") from error
    if not math.isfinite(score):
        raise DataFormatError(f"{path}:{line_number}: score must be finite")
    return SourceRecord(board, score, str(path), line_number)


def resolve_data_paths(patterns: Sequence[str]) -> list[Path]:
    paths: set[Path] = set()
    for pattern in patterns:
        expanded = Path(pattern).expanduser()
        absolute_pattern = str(expanded if expanded.is_absolute() else PROJECT_ROOT / expanded)
        matches = [Path(value).resolve() for value in glob.glob(absolute_pattern, recursive=True)]
        for match in matches:
            if match.is_file():
                paths.add(match)
            elif match.is_dir():
                paths.update(path.resolve() for path in match.rglob("*.txt") if path.is_file())
                paths.update(path.resolve() for path in match.rglob("*.gz") if path.is_file())
                paths.update(path.resolve() for path in match.rglob("*.zip") if path.is_file())
    forbidden = [
        path for path in paths
        if path == FORBIDDEN_DIAGNOSTIC_ROOT
        or path.is_relative_to(FORBIDDEN_DIAGNOSTIC_ROOT)
        or "opponent-regression" in path.name.casefold()
    ]
    if forbidden:
        raise ValueError(
            "diagnostic/opponent-regression files are never training data; "
            f"first forbidden path: {forbidden[0]}"
        )
    return sorted(paths, key=lambda path: str(path).casefold())


def resolve_split_data_paths(
    data_config: dict[str, Any],
) -> tuple[dict[str, list[Path]], bool]:
    raw_by_split = data_config.get('paths_by_split')
    if raw_by_split is None:
        patterns = data_config.get('paths')
        if not isinstance(patterns, list):
            raise ValueError('data.paths must be a JSON array')
        shared = resolve_data_paths([str(value) for value in patterns])
        return {split: shared for split in SPLIT_NAMES}, False
    if not isinstance(raw_by_split, dict) or set(raw_by_split) != set(SPLIT_NAMES):
        raise ValueError(
            f'data.paths_by_split must contain exactly {SPLIT_NAMES}'
        )
    result: dict[str, list[Path]] = {}
    seen: set[Path] = set()
    for split in SPLIT_NAMES:
        patterns = raw_by_split[split]
        if not isinstance(patterns, list):
            raise ValueError(f'data.paths_by_split.{split} must be a JSON array')
        resolved = resolve_data_paths([str(value) for value in patterns])
        overlap = seen.intersection(resolved)
        if overlap:
            raise ValueError(
                f'prepared data file occurs in multiple splits: {next(iter(overlap))}'
            )
        seen.update(resolved)
        result[split] = resolved
    return result, True


def _iter_plain_file(path: Path, strict: bool) -> Iterator[SourceRecord]:
    with _open_text(path) as source:
        for line_number, raw in enumerate(source, 1):
            try:
                record = parse_source_line(raw, path, line_number)
            except (DataFormatError, UnicodeError):
                if strict:
                    raise
                continue
            if record is not None:
                yield record


def _iter_zip_file(path: Path, strict: bool) -> Iterator[SourceRecord]:
    """Read every txt member directly; no archive member is extracted."""

    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as error:
        raise DataFormatError(f"cannot open ZIP training data {path}: {error}") from error
    with archive:
        members = sorted(
            (
                info for info in archive.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".txt")
            ),
            key=lambda info: info.filename.casefold(),
        )
        if not members:
            raise DataFormatError(f"ZIP training data contains no .txt members: {path}")
        for info in members:
            member_path = f"{path}!/{info.filename}"
            try:
                binary = archive.open(info, "r")
            except (OSError, RuntimeError, zipfile.BadZipFile) as error:
                if strict:
                    raise DataFormatError(f"cannot read ZIP member {member_path}: {error}") from error
                continue
            with binary:
                with io.TextIOWrapper(binary, encoding="utf-8", errors="strict") as source:
                    for line_number, raw in enumerate(source, 1):
                        try:
                            record = parse_source_line(raw, member_path, line_number)
                        except (DataFormatError, UnicodeError):
                            if strict:
                                raise
                            continue
                        if record is not None:
                            yield record


def iter_source_records(paths: Sequence[Path], strict: bool = True) -> Iterator[SourceRecord]:
    for path in paths:
        if path.suffix.lower() == ".zip":
            yield from _iter_zip_file(path, strict)
        else:
            yield from _iter_plain_file(path, strict)


def rotate90(board: str) -> str:
    return "".join(board[(7 - x) * 8 + y] for y in range(8) for x in range(8))


def mirror(board: str) -> str:
    return "".join(board[y * 8 + (7 - x)] for y in range(8) for x in range(8))


def d4_variants(board: str) -> tuple[str, ...]:
    variants: list[str] = []
    rotated = board
    for _ in range(4):
        variants.append(rotated)
        variants.append(mirror(rotated))
        rotated = rotate90(rotated)
    return tuple(variants)


def canonical_d4(board: str) -> str:
    return min(d4_variants(board))


def board_hash(board: str, split_seed: int) -> int:
    digest = hashlib.blake2b(digest_size=8, person=b"oth-eval")
    digest.update(str(split_seed).encode("ascii"))
    digest.update(b"\0")
    digest.update(canonical_d4(board).encode("ascii"))
    return int.from_bytes(digest.digest(), "big")


def validate_split_ratios(ratios: dict[str, float]) -> dict[str, float]:
    if set(ratios) != set(SPLIT_NAMES):
        raise ValueError(f"split ratios must have exactly {SPLIT_NAMES}")
    result = {name: float(ratios[name]) for name in SPLIT_NAMES}
    if any(value <= 0.0 for value in result.values()):
        raise ValueError("all split ratios must be positive")
    if not math.isclose(sum(result.values()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"split ratios must sum to 1.0, got {sum(result.values())}")
    return result


def split_for_board(board: str, ratios: dict[str, float], split_seed: int) -> str:
    return split_for_hash(board_hash(board, split_seed), ratios)


def split_for_hash(hashed: int, ratios: dict[str, float]) -> str:
    fraction = hashed / float(1 << 64)
    if fraction < ratios["train"]:
        return "train"
    if fraction < ratios["train"] + ratios["val"]:
        return "val"
    return "test"


def phase_for_relative_board(board: str) -> int:
    stones = 64 - board.count("-")
    return max(0, min(3, (stones - 4) // 10 - 2))


def validate_data_supply(
    data_config: dict[str, Any], training_config: dict[str, Any]
) -> tuple[str, tuple[int, ...]]:
    """Validate safeguards that distinguish smoke and production data supply.

    ``full_pass`` is deliberately strict: a finite batch-step limit or source
    record limit would silently turn the single official ZIP into the same
    prefix-biased stream that this mode is intended to avoid.
    """

    sampling = data_config.get("epoch_sampling", {})
    if not isinstance(sampling, dict):
        raise ValueError("data.epoch_sampling must be a JSON object")
    mode = str(sampling.get("mode", "bounded"))
    if mode not in {"bounded", "full_pass"}:
        raise ValueError("data.epoch_sampling.mode must be bounded or full_pass")

    raw_required = sampling.get("required_phases", [])
    if not isinstance(raw_required, list):
        raise ValueError("data.epoch_sampling.required_phases must be a JSON array")
    required_phases = tuple(int(value) for value in raw_required)
    if len(set(required_phases)) != len(required_phases) or any(
        phase not in PHASES for phase in required_phases
    ):
        raise ValueError("data.epoch_sampling.required_phases must be unique values from 0..3")

    if mode == "full_pass":
        step_keys = ("steps_per_epoch", "validation_steps", "test_steps")
        finite_steps = {
            key: int(training_config.get(key, 0))
            for key in step_keys
            if int(training_config.get(key, 0)) != 0
        }
        limits = data_config.get("max_source_records", {})
        if not isinstance(limits, dict):
            raise ValueError("data.max_source_records must be a JSON object")
        finite_sources = {
            split: int(limits.get(split, 0))
            for split in SPLIT_NAMES
            if int(limits.get(split, 0)) != 0
        }
        if finite_steps or finite_sources:
            raise ValueError(
                "full_pass requires zero step and source-record limits; "
                f"finite_steps={finite_steps}, finite_source_limits={finite_sources}"
            )
        if set(required_phases) != set(PHASES):
            raise ValueError("full_pass must require all four phases [0, 1, 2, 3]")
    return mode, required_phases


def collect_stratified_examples(
    records: Iterable[dict[str, Tensor]],
    total: int,
    seed: int,
    progress: ProgressReporter[Any] | None = None,
) -> list[dict[str, Tensor]]:
    """Collect balanced phase quotas from the shuffled training stream.

    This is intentionally used only for the 2,048-example overfit gate. The
    prepared train stream shuffles source shards and has its own shuffle buffer,
    so stopping as soon as every quota is full avoids scanning tens of millions
    of records merely to perform a small implementation sanity check.
    """

    if total < len(PHASES):
        raise ValueError(f"stratified overfit needs at least {len(PHASES)} examples")
    base, remainder = divmod(total, len(PHASES))
    quotas = {phase: base + (1 if phase < remainder else 0) for phase in PHASES}
    buckets: dict[int, list[dict[str, Tensor]]] = {phase: [] for phase in PHASES}
    rng = random.Random(seed)
    selected_count = 0
    for record in records:
        phase = int(record["phase"].item())
        bucket = buckets.get(phase)
        if bucket is None or len(bucket) >= quotas[phase]:
            continue
        bucket.append(record)
        selected_count += 1
        if progress is not None and (
            selected_count % 128 == 0 or selected_count == total
        ):
            progress.update(current=selected_count)
        if selected_count == total:
            break
    if any(len(buckets[phase]) < quotas[phase] for phase in PHASES):
        counts = {phase: len(bucket) for phase, bucket in buckets.items()}
        raise RuntimeError(
            f"stratified overfit requested {quotas}, but the stream supplied {counts}"
        )
    if progress is not None:
        progress.update(current=selected_count, force=True)
    selected = [record for phase in PHASES for record in buckets[phase]]
    rng.shuffle(selected)
    return selected


class PositionStream(IterableDataset[dict[str, Tensor]]):
    """Deterministic streaming dataset with hash-based leakage prevention."""

    def __init__(
        self,
        paths: Sequence[Path],
        split: str,
        data_config: dict[str, Any],
        seed: int,
        *,
        augment_d4: bool,
        pre_split: bool = False,
    ):
        super().__init__()
        if split not in SPLIT_NAMES:
            raise ValueError(f"unknown split: {split}")
        self.paths = tuple(paths)
        self.split = split
        self.strict = bool(data_config.get("strict", True))
        split_config = data_config["split"]
        self.ratios = validate_split_ratios(split_config["ratios"])
        self.split_seed = int(split_config["seed"])
        self.seed = seed
        self.target_scale = float(data_config.get("target_scale", 64.0))
        if self.target_scale <= 0.0:
            raise ValueError("data.target_scale must be positive")
        self.clip_targets = bool(data_config.get("clip_targets", True))
        self.augment_d4 = augment_d4
        self.pre_split = pre_split
        default_color_augmentation = str(data_config.get("color_augmentation", "both"))
        color_key = "train_color_augmentation" if split == "train" else "eval_color_augmentation"
        self.color_augmentation = str(data_config.get(color_key, default_color_augmentation))
        if self.color_augmentation not in {"both", "random", "black_only"}:
            raise ValueError(
                f"data.{color_key} (or data.color_augmentation) must be both, random, or black_only"
            )
        maximums = data_config.get("max_source_records", {})
        self.max_source_records = int(maximums.get(split, 0))
        self.shuffle_buffer = int(data_config.get("shuffle_buffer", 0)) if split == "train" else 0
        self.epoch = 0

    def set_epoch(self, epoch: int) -> None:
        self.epoch = epoch

    def _records(
        self,
        paths: Sequence[Path],
        rng: random.Random,
        worker_record_limit: int | None,
    ) -> Iterator[dict[str, Tensor]]:
        if worker_record_limit == 0:
            return
        matched = 0
        for source in iter_source_records(paths, self.strict):
            hashed = board_hash(source.board, self.split_seed)
            if not self.pre_split and split_for_hash(hashed, self.ratios) != self.split:
                continue
            matched += 1
            board = source.board
            if self.augment_d4:
                board = d4_variants(board)[rng.randrange(8)]
            target = source.score / self.target_scale
            if self.clip_targets:
                target = max(-1.0, min(1.0, target))

            if self.color_augmentation == "both":
                players = (0, 1)
            elif self.color_augmentation == "random":
                players = (rng.randrange(2),)
            else:
                players = (0,)
            for player in players:
                # Both color orientations retain the same side-to-move target.
                yield feature_tensors(features_from_relative(board, player), target)
            if (
                worker_record_limit is not None
                and matched >= worker_record_limit
            ):
                break

    @staticmethod
    def _shuffle(
        records: Iterable[dict[str, Tensor]], buffer_size: int, rng: random.Random
    ) -> Iterator[dict[str, Tensor]]:
        if buffer_size <= 1:
            yield from records
            return
        iterator = iter(records)
        buffer = list(itertools.islice(iterator, buffer_size))
        while buffer:
            index = rng.randrange(len(buffer))
            selected = buffer[index]
            try:
                buffer[index] = next(iterator)
            except StopIteration:
                buffer.pop(index)
            yield selected

    def __iter__(self) -> Iterator[dict[str, Tensor]]:
        worker = torch.utils.data.get_worker_info()
        worker_id = 0 if worker is None else worker.id
        worker_count = 1 if worker is None else worker.num_workers
        epoch_seed = self.seed + self.epoch * 1_000_003
        paths = list(self.paths)
        if self.split == "train":
            # All workers derive the same global shard order before taking
            # disjoint slices. This avoids reading every prepared shard once
            # per worker while retaining deterministic epoch shuffling.
            random.Random(epoch_seed).shuffle(paths)
        active_workers = min(worker_count, len(paths))
        paths = paths[worker_id::worker_count]
        worker_record_limit: int | None = None
        if self.max_source_records > 0 and worker_id < active_workers:
            base, remainder = divmod(self.max_source_records, active_workers)
            worker_record_limit = base + (1 if worker_id < remainder else 0)
        elif self.max_source_records > 0:
            worker_record_limit = 0
        rng = random.Random(epoch_seed + worker_id * 97_409)
        records = self._records(paths, rng, worker_record_limit)
        yield from self._shuffle(records, self.shuffle_buffer, rng)


class CachedRecords(Dataset[dict[str, Tensor]]):
    def __init__(self, records: Sequence[dict[str, Tensor]]):
        self.records = tuple(records)

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> dict[str, Tensor]:
        return self.records[index]


@dataclass
class Metrics:
    count: int = 0
    squared_error: float = 0.0
    absolute_error: float = 0.0
    optimized_loss: float = 0.0
    phase_counts: Counter[int] | None = None

    def __post_init__(self) -> None:
        if self.phase_counts is None:
            self.phase_counts = Counter()

    def update(self, prediction: Tensor, target: Tensor, phase: Tensor, loss: Tensor) -> None:
        error = prediction.detach() - target.detach()
        count = int(error.numel())
        self.count += count
        self.squared_error += float(torch.sum(error * error).cpu())
        self.absolute_error += float(torch.sum(torch.abs(error)).cpu())
        self.optimized_loss += float(loss.detach().cpu()) * count
        assert self.phase_counts is not None
        self.phase_counts.update(int(value) for value in phase.detach().cpu().tolist())

    def as_dict(self, target_scale: float) -> dict[str, Any]:
        if self.count == 0:
            return {
                "count": 0, "loss": None, "mae": None, "rmse": None,
                "mae_score_units": None, "rmse_score_units": None,
                "phase_counts": {},
            }
        mse = self.squared_error / self.count
        mae = self.absolute_error / self.count
        return {
            "count": self.count,
            "loss": self.optimized_loss / self.count,
            "mae": mae,
            "rmse": math.sqrt(mse),
            "mae_score_units": mae * target_scale,
            "rmse_score_units": math.sqrt(mse) * target_scale,
            "phase_counts": dict(sorted((self.phase_counts or {}).items())),
        }


def require_phase_coverage(metrics: Metrics, required: Sequence[int], label: str) -> None:
    if not required:
        return
    actual = set((metrics.phase_counts or {}).keys())
    missing = sorted(set(required) - actual)
    if missing:
        raise RuntimeError(f"{label} did not contain required phases: missing={missing}")


def move_batch(batch: dict[str, Tensor], device: torch.device, dtype: torch.dtype) -> dict[str, Tensor]:
    result = {key: value.to(device=device, non_blocking=True) for key, value in batch.items()}
    result["target"] = result["target"].to(dtype=dtype)
    return result


def train_epoch(
    model: JavaCompatibleEvaluator,
    loader: DataLoader[dict[str, Tensor]],
    optimizer: torch.optim.Optimizer,
    device: torch.device,
    max_steps: int,
    gradient_clip: float,
    phase_weights: Tensor,
    progress: ProgressReporter[Any] | None = None,
) -> Metrics:
    model.train()
    metrics = Metrics()
    for step, raw_batch in enumerate(loader):
        if max_steps > 0 and step >= max_steps:
            break
        batch = move_batch(raw_batch, device, model.parameter_dtype)
        optimizer.zero_grad(set_to_none=True)
        prediction = model(batch)
        errors = prediction - batch["target"]
        weights = phase_weights[batch["phase"]]
        loss = torch.sum(weights * errors * errors) / torch.sum(weights)
        loss.backward()
        if gradient_clip > 0.0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), gradient_clip)
        optimizer.step()
        if progress is not None:
            progress.update(current=step + 1)
        metrics.update(prediction, batch["target"], batch["phase"], loss)
    return metrics


@torch.no_grad()
def evaluate_loader(
    model: JavaCompatibleEvaluator,
    loader: DataLoader[dict[str, Tensor]],
    device: torch.device,
    max_steps: int,
    progress: ProgressReporter[Any] | None = None,
) -> Metrics:
    model.eval()
    metrics = Metrics()
    for step, raw_batch in enumerate(loader):
        if max_steps > 0 and step >= max_steps:
            break
        batch = move_batch(raw_batch, device, model.parameter_dtype)
        prediction = model(batch)
        loss = torch.mean((prediction - batch["target"]) ** 2)
        metrics.update(prediction, batch["target"], batch["phase"], loss)
        if progress is not None:
            progress.update(current=step + 1)
    return metrics


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        config = json.load(source)
    if not isinstance(config, dict):
        raise ValueError("configuration root must be a JSON object")
    return config


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_prepared_manifest(
    config: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, int] | None]:
    data_config = config['data']
    raw_path = data_config.get('prepared_manifest')
    if raw_path is None:
        return None, None
    path = resolve_project_path(raw_path).resolve()
    try:
        with path.open('r', encoding='utf-8') as source:
            manifest = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f'prepared manifest is missing or unreadable; run the C++ converter: {path}'
        ) from error
    if not isinstance(manifest, dict) or manifest.get('status') != 'verified-full':
        raise RuntimeError(
            'prepared manifest is not a completed full conversion; '
            f'rerun the C++ converter: {path}'
        )
    if manifest.get('schema_version') != PREPARED_MANIFEST_SCHEMA_VERSION:
        raise RuntimeError(
            f'prepared manifest schema is not supported; rerun the C++ converter: {path}'
        )
    counts = manifest.get('counts')
    if not isinstance(counts, dict):
        raise RuntimeError(f'prepared manifest has no counts object: {path}')
    raw_by_split = counts.get('by_split')
    if not isinstance(raw_by_split, dict) or set(raw_by_split) != set(SPLIT_NAMES):
        raise RuntimeError(f'prepared manifest has invalid split counts: {path}')
    split_counts = {split: int(raw_by_split[split]) for split in SPLIT_NAMES}
    if any(value <= 0 for value in split_counts.values()):
        raise RuntimeError(f'prepared manifest contains an empty split: {path}')
    prepared_records = int(counts.get('prepared_records', -1))
    skipped = int(counts.get('skipped_no_position', -1))
    source_games = int(counts.get('source_games', -1))
    source_files = int(counts.get('source_files', -1))
    if (
        source_files != EXPECTED_V0002_SOURCE_FILES
        or source_games != EXPECTED_V0002_SOURCE_GAMES
    ):
        raise RuntimeError(
            'prepared manifest is not the complete official v0002 dataset: '
            f'files={source_files:,}, games={source_games:,}'
        )
    if sum(split_counts.values()) != prepared_records:
        raise RuntimeError(f'prepared manifest split counts do not add up: {path}')
    if prepared_records + skipped != source_games:
        raise RuntimeError(f'prepared manifest does not conserve source games: {path}')
    raw_phases = counts.get('prepared_records_by_phase')
    if not isinstance(raw_phases, dict):
        raise RuntimeError(f'prepared manifest has no phase counts: {path}')
    phase_counts = {int(key): int(value) for key, value in raw_phases.items()}
    if set(phase_counts) != set(PHASES) or any(
        value <= 0 for value in phase_counts.values()
    ):
        raise RuntimeError(f'prepared manifest does not cover all phases: {path}')
    if sum(phase_counts.values()) != prepared_records:
        raise RuntimeError(f'prepared manifest phase counts do not add up: {path}')

    split_contract = manifest.get('split')
    if not isinstance(split_contract, dict):
        raise RuntimeError(f'prepared manifest has no split contract: {path}')
    if (
        split_contract.get('algorithm') != PREPARED_SPLIT_ALGORITHM
        or split_contract.get('unit') != PREPARED_SPLIT_UNIT
    ):
        raise RuntimeError(
            'prepared manifest does not use canonical-D4 leakage-safe splits; '
            f'rerun the C++ converter: {path}'
        )
    configured = validate_split_ratios(data_config['split']['ratios'])
    manifest_ratios = split_contract.get('ratios')
    if not isinstance(manifest_ratios, dict):
        raise RuntimeError(f'prepared manifest has invalid split ratios: {path}')
    for split in SPLIT_NAMES:
        if not math.isclose(
            float(manifest_ratios.get(split, -1.0)),
            configured[split],
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise RuntimeError(
                f'prepared manifest split ratio differs for {split}: {path}'
            )
    if str(split_contract.get('seed')) != str(data_config['split']['seed']):
        raise RuntimeError(f'prepared manifest split seed differs: {path}')
    manifest['_resolved_path'] = str(path)
    return manifest, split_counts


def verify_prepared_shards(
    manifest: dict[str, Any],
    paths_by_split: dict[str, list[Path]],
    *,
    progress_enabled: bool = True,
    progress_interval: float = 1.0,
) -> None:
    """Match every prepared shard to its manifest path, row count, and SHA-256."""

    output_root = Path(str(manifest.get('output_root', ''))).resolve()
    sources = manifest.get('sources')
    counts = manifest.get('counts')
    if not isinstance(sources, list) or not isinstance(counts, dict):
        raise RuntimeError('prepared manifest has no complete source/output index')
    expected_source_files = int(counts.get('source_files', -1))
    if len(sources) != expected_source_files:
        raise RuntimeError(
            'prepared manifest source index length differs from source_files: '
            f'{len(sources):,} != {expected_source_files:,}'
        )

    expected: dict[str, dict[Path, tuple[int, int, str]]] = {
        split: {} for split in SPLIT_NAMES
    }
    rows_by_split: Counter[str] = Counter()
    total_bytes = 0
    for source_index, source in enumerate(sources, 1):
        if not isinstance(source, dict):
            raise RuntimeError(
                f'prepared manifest source {source_index} is not an object'
            )
        outputs = source.get('outputs')
        if not isinstance(outputs, dict) or set(outputs) != set(SPLIT_NAMES):
            raise RuntimeError(
                f'prepared manifest source {source_index} has invalid outputs'
            )
        for split in SPLIT_NAMES:
            info = outputs[split]
            if not isinstance(info, dict):
                raise RuntimeError(
                    f'prepared manifest source {source_index} has invalid {split} output'
                )
            relative = info.get('path')
            rows = info.get('rows')
            size_bytes = info.get('size_bytes')
            sha256 = info.get('sha256')
            if (
                not isinstance(relative, str)
                or not isinstance(rows, int)
                or rows < 0
                or not isinstance(size_bytes, int)
                or size_bytes < 0
                or not isinstance(sha256, str)
                or re.fullmatch(r'[0-9a-f]{64}', sha256) is None
            ):
                raise RuntimeError(
                    f'prepared manifest source {source_index} has malformed {split} metadata'
                )
            path = (output_root / Path(relative)).resolve()
            if not path.is_relative_to(output_root):
                raise RuntimeError(
                    f'prepared manifest output escapes output_root: {relative}'
                )
            if path in expected[split]:
                raise RuntimeError(
                    f'prepared manifest repeats an output path: {path}'
                )
            expected[split][path] = (rows, size_bytes, sha256)
            rows_by_split[split] += rows
            total_bytes += size_bytes

    manifest_rows = counts.get('by_split')
    if not isinstance(manifest_rows, dict) or any(
        rows_by_split[split] != int(manifest_rows.get(split, -1))
        for split in SPLIT_NAMES
    ):
        raise RuntimeError(
            'prepared manifest source rows do not add up to counts.by_split'
        )

    for split in SPLIT_NAMES:
        actual_paths = {path.resolve() for path in paths_by_split[split]}
        expected_paths = set(expected[split])
        if actual_paths != expected_paths:
            missing = sorted(expected_paths - actual_paths, key=str)
            extra = sorted(actual_paths - expected_paths, key=str)
            raise RuntimeError(
                f'prepared {split} shard paths differ from manifest; '
                f'missing={missing[:1]}, extra={extra[:1]}'
            )

    completed_bytes = 0
    with ProgressReporter(
        total_bytes,
        label='bytes',
        phase='prepared shard integrity',
        interval=progress_interval,
        quiet=not progress_enabled,
    ) as progress:
        for split in SPLIT_NAMES:
            for path in sorted(expected[split], key=lambda value: str(value).casefold()):
                expected_rows, expected_size, expected_sha256 = expected[split][path]
                digest = hashlib.sha256()
                actual_rows = 0
                actual_size = 0
                try:
                    with path.open('rb') as stream:
                        for line_number, raw_line in enumerate(stream, 1):
                            if _PREPARED_ROW.fullmatch(raw_line) is None:
                                raise RuntimeError(
                                    f'invalid prepared row at {path}:{line_number}'
                                )
                            score = int(raw_line[65:-1])
                            if not -64 <= score <= 64:
                                raise RuntimeError(
                                    f'prepared score out of range at {path}:{line_number}: {score}'
                                )
                            digest.update(raw_line)
                            actual_rows += 1
                            actual_size += len(raw_line)
                except RuntimeError:
                    raise
                except OSError as error:
                    raise RuntimeError(
                        f'cannot verify prepared shard {path}: {error}'
                    ) from error
                actual = (actual_rows, actual_size, digest.hexdigest())
                wanted = (expected_rows, expected_size, expected_sha256)
                if actual != wanted:
                    raise RuntimeError(
                        f'prepared shard differs from manifest: {path}; '
                        f'expected={wanted}, actual={actual}'
                    )
                completed_bytes += actual_size
                progress.update(current=completed_bytes)


def resolve_and_verify_training_data(
    config: dict[str, Any],
    *,
    progress_enabled: bool = True,
    progress_interval: float = 1.0,
    skip_prepared_shard_hash: bool = False,
) -> tuple[
    dict[str, Any] | None,
    dict[str, int] | None,
    dict[str, list[Path]],
    bool,
    list[Path],
]:
    """Resolve configured inputs and fully verify prepared C++ shards."""

    data_config = config['data']
    prepared_manifest, prepared_split_counts = load_prepared_manifest(config)
    paths_by_split, pre_split = resolve_split_data_paths(data_config)
    paths = sorted(
        {path for values in paths_by_split.values() for path in values},
        key=lambda path: str(path).casefold(),
    )
    missing_splits = [
        split for split, values in paths_by_split.items() if not values
    ]
    if not paths or missing_splits:
        message = (
            'no training data matched the configured paths'
            + (f'; empty splits={missing_splits}' if missing_splits else '')
        )
        if prepared_manifest is not None:
            message += '. Run the C++ converter first.'
        raise FileNotFoundError(message)

    if prepared_manifest is not None:
        if not pre_split:
            raise RuntimeError(
                'a prepared manifest requires data.paths_by_split'
            )
        output_root = Path(str(prepared_manifest['output_root'])).resolve()
        outside = [
            path for path in paths
            if not path.resolve().is_relative_to(output_root)
        ]
        if outside:
            raise RuntimeError(
                f'prepared data path is outside manifest output root: {outside[0]}'
            )
        expected_shards_per_split = int(
            prepared_manifest['counts']['source_files']
        )
        mismatched_shards = {
            split: len(values)
            for split, values in paths_by_split.items()
            if len(values) != expected_shards_per_split
        }
        if mismatched_shards:
            raise RuntimeError(
                'prepared shard count differs from the verified manifest: '
                f'expected {expected_shards_per_split:,} per split, '
                f'got {mismatched_shards}'
            )
        if not skip_prepared_shard_hash:
            verify_prepared_shards(
                prepared_manifest,
                paths_by_split,
                progress_enabled=progress_enabled,
                progress_interval=progress_interval,
            )

    return (
        prepared_manifest,
        prepared_split_counts,
        paths_by_split,
        pre_split,
        paths,
    )


def choose_device(requested: str) -> torch.device:
    if requested == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("cpu")
    device = torch.device(requested)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
    return device


def choose_dtype(name: str) -> torch.dtype:
    if name == "float64":
        return torch.float64
    if name == "float32":
        return torch.float32
    raise ValueError("model.dtype must be float64 or float32")


def set_reproducible_seed(seed: int, deterministic: bool) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if deterministic:
        torch.use_deterministic_algorithms(True)
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.benchmark = False


def make_loader(
    dataset: Dataset[dict[str, Tensor]] | IterableDataset[dict[str, Tensor]],
    batch_size: int,
    num_workers: int,
    pin_memory: bool,
    *,
    shuffle: bool = False,
    seed: int = 0,
) -> DataLoader[dict[str, Tensor]]:
    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        pin_memory=pin_memory,
        generator=generator,
        # Recreate workers for each epoch so set_epoch() changes the D4 RNG.
        persistent_workers=False,
    )


def progress_settings(
    config: dict[str, Any], args: argparse.Namespace
) -> tuple[bool, float]:
    settings = config.get('progress', {})
    if not isinstance(settings, dict):
        raise ValueError('progress must be a JSON object')
    enabled = bool(settings.get('enabled', True)) and not bool(
        getattr(args, 'quiet', False)
    )
    interval = float(settings.get('interval_seconds', 1.0))
    if interval < 0.0:
        raise ValueError('progress.interval_seconds must be non-negative')
    return enabled, interval


def expected_split_examples(
    data_config: dict[str, Any],
    split: str,
    split_counts: dict[str, int] | None = None,
) -> tuple[int | None, bool]:
    if split_counts is not None and split in split_counts:
        records = int(split_counts[split])
        estimated = False
    else:
        expected = data_config.get('expected_source_records')
        if expected is None:
            return None, False
        ratios = validate_split_ratios(data_config['split']['ratios'])
        records = round(int(expected) * ratios[split])
        estimated = True

    default_mode = str(data_config.get('color_augmentation', 'both'))
    key = 'train_color_augmentation' if split == 'train' else 'eval_color_augmentation'
    mode = str(data_config.get(key, default_mode))
    multiplier = 2 if mode == 'both' else 1
    return records * multiplier, estimated


def expected_loader_steps(
    data_config: dict[str, Any],
    split: str,
    batch_size: int,
    max_steps: int,
    split_counts: dict[str, int] | None = None,
) -> tuple[int | None, bool]:
    if max_steps > 0:
        return max_steps, False
    examples, estimated = expected_split_examples(data_config, split, split_counts)
    if examples is None:
        return None, False
    return math.ceil(examples / batch_size), estimated


def require_full_pass_count(
    metrics: "Metrics",
    data_config: dict[str, Any],
    split: str,
    split_counts: dict[str, int] | None,
    max_steps: int,
    overfit_enabled: bool,
    label: str,
) -> None:
    """Fail closed if an unrestricted full pass loses or duplicates examples."""

    sampling = data_config.get("epoch_sampling", {})
    source_limits = data_config.get("max_source_records", {})
    is_full_pass = (
        isinstance(sampling, dict)
        and sampling.get("mode") == "full_pass"
        and isinstance(source_limits, dict)
        and int(source_limits.get(split, 0)) == 0
        and max_steps == 0
        and not overfit_enabled
    )
    if not is_full_pass:
        return
    expected, estimated = expected_split_examples(
        data_config, split, split_counts,
    )
    if expected is None or estimated:
        raise RuntimeError(
            f"{label} cannot prove its full-pass example count from the "
            "verified prepared manifest"
        )
    if metrics.count != expected:
        raise RuntimeError(
            f"{label} full-pass count mismatch: expected {expected:,}, "
            f"observed {metrics.count:,}"
        )


def loader_length(loader: DataLoader[dict[str, Tensor]]) -> int | None:
    try:
        return len(loader)
    except TypeError:
        return None


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def capture_rng_state() -> dict[str, Any]:
    state: dict[str, Any] = {
        "python": random.getstate(),
        "torch_cpu": torch.get_rng_state(),
    }
    if torch.cuda.is_available():
        state["torch_cuda"] = torch.cuda.get_rng_state_all()
    return state


def restore_rng_state(state: Any) -> None:
    if not isinstance(state, dict):
        raise RuntimeError("format-2 checkpoint has no RNG state")
    if "python" not in state or "torch_cpu" not in state:
        raise RuntimeError("format-2 checkpoint RNG state is incomplete")
    random.setstate(state["python"])
    torch.set_rng_state(state["torch_cpu"])
    cuda_state = state.get("torch_cuda")
    if cuda_state is not None:
        if not torch.cuda.is_available():
            raise RuntimeError(
                "checkpoint contains CUDA RNG state but CUDA is unavailable"
            )
        torch.cuda.set_rng_state_all(cuda_state)


def build_scheduler(
    optimizer: torch.optim.Optimizer,
    training_config: dict[str, Any],
) -> Any:
    raw = training_config.get("scheduler")
    if not isinstance(raw, dict):
        raise ValueError("training.scheduler must be an object")
    kind = str(raw.get("type", "")).strip().lower()
    if kind != "reduce_on_plateau":
        raise ValueError(
            "original_11 requires training.scheduler.type=reduce_on_plateau"
        )
    factor = float(raw.get("factor", 0.5))
    patience = int(raw.get("patience", 0))
    threshold = float(raw.get("threshold", 0.0))
    min_lr = float(raw.get("min_lr", 0.0))
    if not 0.0 < factor < 1.0:
        raise ValueError("scheduler.factor must be in (0, 1)")
    if patience < 0 or threshold < 0.0 or min_lr < 0.0:
        raise ValueError(
            "scheduler patience, threshold, and min_lr must be non-negative"
        )
    return torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode="min",
        factor=factor,
        patience=patience,
        threshold=threshold,
        threshold_mode="abs",
        min_lr=min_lr,
    )


def early_stopping_settings(
    training_config: dict[str, Any],
) -> dict[str, Any]:
    raw = training_config.get("early_stopping")
    if not isinstance(raw, dict):
        raise ValueError("training.early_stopping must be an object")
    enabled = bool(raw.get("enabled", False))
    patience = int(raw.get("patience", 0))
    min_delta = float(raw.get("min_delta", 0.0))
    minimum_epochs = int(raw.get("minimum_epochs", 0))
    if not enabled:
        raise ValueError("original_11 requires early_stopping.enabled=true")
    if patience <= 0:
        raise ValueError("early_stopping.patience must be positive")
    if min_delta < 0.0 or minimum_epochs <= 0:
        raise ValueError(
            "early_stopping min_delta must be non-negative and minimum_epochs positive"
        )
    return {
        "enabled": enabled,
        "patience": patience,
        "min_delta": min_delta,
        "minimum_epochs": minimum_epochs,
    }


def _atomic_torch_save(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        torch.save(payload, temporary_path)
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def save_checkpoint(
    path: Path,
    model: JavaCompatibleEvaluator,
    optimizer: torch.optim.Optimizer,
    scheduler: Any,
    epoch: int,
    best_validation_rmse: float,
    config: dict[str, Any],
    early_stop_state: dict[str, Any],
    lineage_id: str,
    checkpoint_role: str,
    *,
    model_state_override: dict[str, Any] | None = None,
) -> None:
    if checkpoint_role not in {"last", "best"}:
        raise ValueError("checkpoint_role must be last or best")
    _atomic_torch_save({
        "format_version": CHECKPOINT_FORMAT_VERSION,
        "checkpoint_role": checkpoint_role,
        "lineage_id": lineage_id,
        "epoch": epoch,
        "best_validation_rmse": best_validation_rmse,
        "model_state": (
            model.state_dict()
            if model_state_override is None
            else model_state_override
        ),
        "optimizer_state": optimizer.state_dict(),
        "scheduler_state": scheduler.state_dict(),
        "early_stop_state": dict(early_stop_state),
        "rng_state": capture_rng_state(),
        "config": config,
    }, path)


def resolve_resume_best_checkpoint(resume_path: Path) -> Path:
    """Locate the best-model companion needed for a safe resumed run."""

    resume_path = resume_path.expanduser().resolve()
    if resume_path.name != "checkpoint_last.pt":
        raise RuntimeError(
            "safe continuation requires checkpoint_last.pt; "
            "checkpoint_best.pt is model selection only"
        )
    best_path = resume_path.with_name("checkpoint_best.pt")
    if not best_path.is_file():
        raise RuntimeError(
            "resume requires checkpoint_best.pt beside the selected checkpoint; "
            f"not found: {best_path}"
        )
    return best_path


def resolve_allowed_resume_path(
    raw_path: Path,
    config: dict[str, Any],
) -> Path:
    resume_path = raw_path.expanduser().resolve()
    resume_config = config.get("resume")
    if not isinstance(resume_config, dict):
        raise RuntimeError("config has no explicit resume policy")
    raw_roots = resume_config.get("allowed_roots")
    if not isinstance(raw_roots, list) or not raw_roots:
        raise RuntimeError("resume.allowed_roots must be a non-empty array")
    roots = [resolve_project_path(str(value)).resolve() for value in raw_roots]
    if not any(resume_path.is_relative_to(root) for root in roots):
        raise RuntimeError(
            "resume checkpoint is outside resume.allowed_roots: "
            f"{resume_path}"
        )
    if resume_path.name != "checkpoint_last.pt" or not resume_path.is_file():
        raise RuntimeError(
            "resume path must be an existing checkpoint_last.pt: "
            f"{resume_path}"
        )
    return resume_path


def prepared_manifest_contract_sha256(
    manifest: dict[str, Any] | None,
) -> str | None:
    """Hash only the stable data/split contract, excluding run timing fields."""

    if manifest is None:
        return None
    sources = manifest.get('sources')
    if not isinstance(sources, list):
        raise RuntimeError('prepared manifest has no source index for resume contract')
    stable_sources = []
    stable_keys = (
        'source_id',
        'part',
        'relative_path',
        'random_plies',
        'fingerprint',
        'split',
        'source_transcript_lines',
        'prepared_records',
        'skipped_no_position',
        'outputs',
    )
    for source in sources:
        if not isinstance(source, dict):
            raise RuntimeError('prepared manifest has a malformed source entry')
        stable_sources.append({key: source.get(key) for key in stable_keys})
    payload = {
        'schema_version': manifest.get('schema_version'),
        'status': manifest.get('status'),
        'split': manifest.get('split'),
        'counts': manifest.get('counts'),
        'sources': stable_sources,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def training_resume_contract(config: dict[str, Any]) -> dict[str, Any]:
    """Return settings that must stay identical when continuing a run."""

    training = {
        key: value
        for key, value in config.get('training', {}).items()
        if key not in {'epochs', 'device', 'pin_memory'}
    }
    return {
        'run_name': config.get('run_name'),
        'candidate_name': config.get('candidate_name'),
        'source_model_sha256': config.get('source_model_sha256'),
        'feature_schema': config.get('feature_schema'),
        'experiment': config.get('experiment', {}),
        'dataset_kind': config.get('dataset_kind', 'egaroucid_positions_v1'),
        'seed': config.get('seed'),
        'parameter_init': config.get('parameter_init'),
        'model': config.get('model', {}),
        'data': config.get('data', {}),
        'training': training,
        'overfit': config.get('overfit', {}),
    }


def legacy_training_resume_contract(config: dict[str, Any]) -> dict[str, Any]:
    """Contract preserved when importing the verified original_10 run."""

    ignored = {
        'epochs',
        'device',
        'pin_memory',
        'learning_rate',
        'scheduler',
        'early_stopping',
    }
    training = {
        key: value
        for key, value in config.get('training', {}).items()
        if key not in ignored
    }
    overfit = {
        key: value
        for key, value in config.get('overfit', {}).items()
        if key not in {'required_gate'}
    }
    return {
        'feature_schema': config.get('feature_schema'),
        'dataset_kind': config.get('dataset_kind', 'egaroucid_positions_v1'),
        'seed': config.get('seed'),
        'model': config.get('model', {}),
        'data': config.get('data', {}),
        'training': training,
        'overfit': overfit,
    }


def validate_resume_compatibility(
    checkpoint: dict[str, Any],
    *,
    label: str,
    config: dict[str, Any],
    overfit_enabled: bool,
    prepared_manifest: dict[str, Any] | None,
    continuation_checkpoint: bool,
) -> None:
    format_version = int(checkpoint.get('format_version', -1))
    saved_config = checkpoint.get('config')
    if not isinstance(saved_config, dict):
        raise RuntimeError(f'{label} has no saved training configuration')
    if format_version == CHECKPOINT_FORMAT_VERSION:
        if training_resume_contract(saved_config) != training_resume_contract(config):
            raise RuntimeError(
                f'{label} data/model/optimizer contract differs from the current configuration'
            )
        required = {
            'model_state', 'optimizer_state', 'scheduler_state',
            'early_stop_state', 'rng_state', 'lineage_id',
        }
        missing = sorted(required.difference(checkpoint))
        if missing:
            raise RuntimeError(f'{label} format-2 fields are missing: {missing}')
    elif format_version == LEGACY_CHECKPOINT_FORMAT_VERSION:
        resume_config = config.get('resume', {})
        if not bool(resume_config.get('allow_legacy_format_1', False)):
            raise RuntimeError(f'{label} legacy format-1 import is disabled')
        if legacy_training_resume_contract(saved_config) != legacy_training_resume_contract(config):
            raise RuntimeError(
                f'{label} legacy data/model/optimizer contract is incompatible'
            )
        expected_seed = int(resume_config.get('legacy_expected_seed', -1))
        if int(saved_config.get('seed', -2)) != expected_seed:
            raise RuntimeError(f'{label} legacy seed differs from the pinned seed')
        expected_init = str(resume_config.get('legacy_expected_parameter_init', ''))
        if str(saved_config.get('parameter_init', '')) != expected_init:
            raise RuntimeError(f'{label} legacy parameter_init is not the pinned source')
        expected_epoch = int(resume_config.get('legacy_expected_epoch', -1))
        saved_epoch = int(checkpoint.get('epoch', -1))
        if continuation_checkpoint and saved_epoch != expected_epoch:
            raise RuntimeError(
                f'{label} must end at epoch {expected_epoch}, got {saved_epoch}'
            )
        if not continuation_checkpoint and saved_epoch > expected_epoch:
            raise RuntimeError(f'{label} best epoch exceeds the legacy last epoch')
        if 'model_state' not in checkpoint or 'optimizer_state' not in checkpoint:
            raise RuntimeError(f'{label} has no model/optimizer state')
    else:
        raise RuntimeError(
            f'{label} checkpoint format {format_version} is unsupported'
        )
    saved_resolved = saved_config.get('resolved')
    if not isinstance(saved_resolved, dict):
        raise RuntimeError(f'{label} has no resolved run contract')
    if bool(saved_resolved.get('overfit')) != overfit_enabled:
        raise RuntimeError(f'{label} overfit mode differs from the current run')
    current_manifest_digest = prepared_manifest_contract_sha256(prepared_manifest)
    saved_manifest_digest = saved_resolved.get(
        'prepared_manifest_contract_sha256'
    )
    if saved_manifest_digest != current_manifest_digest:
        raise RuntimeError(
            f'{label} prepared dataset/split contract differs from the current manifest'
        )


def next_candidate_path(requested: Path) -> Path:
    if not requested.exists():
        return requested
    match = re.fullmatch(r"(.*?)(\d+)(\.[^.]+)", requested.name)
    if not match:
        raise FileExistsError(f"candidate already exists and has no numeric suffix: {requested}")
    prefix, digits, suffix = match.groups()
    number = int(digits)
    while True:
        number += 1
        candidate = requested.with_name(f"{prefix}{number:0{len(digits)}d}{suffix}")
        if not candidate.exists():
            return candidate


def scan_dataset(
    paths: Sequence[Path],
    data_config: dict[str, Any],
    limit: int,
    progress: ProgressReporter[Any] | None = None,
) -> dict[str, Any]:
    ratios = validate_split_ratios(data_config["split"]["ratios"])
    split_seed = int(data_config["split"]["seed"])
    strict = bool(data_config.get("strict", True))
    split_counts: Counter[str] = Counter()
    phase_counts: dict[str, Counter[int]] = {name: Counter() for name in SPLIT_NAMES}
    total_phase_counts: Counter[int] = Counter()
    score_min = math.inf
    score_max = -math.inf
    count = 0
    for source in iter_source_records(paths, strict):
        split = split_for_board(source.board, ratios, split_seed)
        split_counts[split] += 1
        phase = phase_for_relative_board(source.board)
        phase_counts[split][phase] += 1
        total_phase_counts[phase] += 1
        score_min = min(score_min, source.score)
        score_max = max(score_max, source.score)
        count += 1
        if progress is not None and count % 4096 == 0:
            progress.update(current=count)
        if limit > 0 and count >= limit:
            break
    if progress is not None:
        progress.update(current=count, force=True)
    return {
        "source_records": count,
        "split_counts": dict(sorted(split_counts.items())),
        "phase_counts": {
            split: dict(sorted(values.items())) for split, values in phase_counts.items()
        },
        "total_phase_counts": dict(sorted(total_phase_counts.items())),
        "score_min": None if count == 0 else score_min,
        "score_max": None if count == 0 else score_max,
    }


def validate_scan_expectations(result: dict[str, Any], data_config: dict[str, Any]) -> None:
    expected_records = data_config.get("expected_source_records")
    if expected_records is not None and result["source_records"] != int(expected_records):
        raise DataFormatError(
            f"source record count mismatch: expected {int(expected_records):,}, "
            f"got {result['source_records']:,}"
        )
    raw_expected_phases = data_config.get("expected_phase_counts")
    if raw_expected_phases is None:
        return
    if not isinstance(raw_expected_phases, dict):
        raise ValueError("data.expected_phase_counts must be a JSON object")
    expected_phases = {int(key): int(value) for key, value in raw_expected_phases.items()}
    actual_phases = {int(key): int(value) for key, value in result["total_phase_counts"].items()}
    if actual_phases != expected_phases:
        raise DataFormatError(
            f"phase distribution mismatch: expected {expected_phases}, got {actual_phases}"
        )


def self_test(config: dict[str, Any]) -> None:
    parameter_path = resolve_project_path(config["parameter_init"])
    original_values = read_parameter_values(parameter_path)
    model = JavaCompatibleEvaluator(torch.float64)
    model.load_java_parameters(parameter_path)
    reference = ReferenceEvaluator(parameter_path)

    build_dir = PROJECT_ROOT / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="training-self-test-", dir=build_dir) as temporary:
        exported = Path(temporary) / "roundtrip.txt"
        export_java_parameters(model, exported)
        roundtrip_values = read_parameter_values(exported)
        unequal = [
            index for index, (before, after) in enumerate(zip(original_values, roundtrip_values), 1)
            if before.hex() != after.hex()
        ]
        if unequal:
            raise AssertionError(f"parameter round-trip changed values; first lines: {unequal[:8]}")

    # Synthetic boards cover all four Java phases without external data.
    boards = []
    for stones in (4, 34, 44, 54, 63):
        occupied = "".join("X" if index % 2 == 0 else "O" for index in range(stones))
        boards.append(occupied + "-" * (64 - stones))
    records = []
    expected = []
    for board in boards:
        for player in (0, 1):
            features = features_from_relative(board, player)
            records.append(feature_tensors(features, 0.0))
            absolute = absolute_from_relative(board, player)
            expected.append(reference.evaluate_details(absolute, player).raw_value)
    batch = default_collate(records)
    with torch.no_grad():
        actual = torch.clamp(model(batch), -1.0, 1.0).tolist()
    errors = [abs(left - right) for left, right in zip(actual, expected)]
    max_error = max(errors, default=0.0)
    if max_error > 2e-12:
        raise AssertionError(f"model/reference forward mismatch: max error {max_error:.3e}")

    # D4-equivalent records must never cross split boundaries.
    sample = "-XO-OOXOOXX-OXOO-XXOXXOOX-OXOOXOOXOOOXXXO-XOOOXXO-O-OO---OOOX-O-"
    if len(sample) != 64:
        raise AssertionError("internal Egaroucid parser sample has the wrong length")
    parsed = parse_source_line(sample + " 4", Path("self-test.txt"), 1)
    if parsed is None or parsed.score != 4.0:
        raise AssertionError("Egaroucid line parser self-test failed")
    split_config = config["data"]["split"]
    ratios = validate_split_ratios(split_config["ratios"])
    split_seed = int(split_config["seed"])
    variant_splits = {
        split_for_board(variant, ratios, split_seed) for variant in d4_variants(sample)
    }
    if len(variant_splits) != 1:
        raise AssertionError(f"D4 variants crossed data splits: {variant_splits}")

    # Verify the no-extraction acquisition path using a tiny disposable ZIP.
    build_dir = PROJECT_ROOT / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="zip-reader-self-test-", dir=build_dir) as temporary:
        archive_path = Path(temporary) / "sample.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("positions/0000000.txt", sample + " 4\n\n")
            archive.writestr("positions/0000001.txt", rotate90(sample) + " -6\n")
            archive.writestr("positions/README.md", "ignored\n")
        zip_records = list(iter_source_records([archive_path], strict=True))
        if len(zip_records) != 2 or [record.score for record in zip_records] != [4.0, -6.0]:
            raise AssertionError("ZIP streaming reader self-test failed")
        zip_scan = scan_dataset([archive_path], config["data"], limit=0)
        if zip_scan["source_records"] != 2:
            raise AssertionError(f"ZIP scan self-test failed: {zip_scan}")

    # Exercise autograd through every phase and every subnetwork.
    model.zero_grad(set_to_none=True)
    prediction = model(batch)
    training_loss = torch.mean(prediction * prediction)
    training_loss.backward()
    missing_or_invalid = [
        name for name, parameter in model.named_parameters()
        if parameter.grad is None or not bool(torch.all(torch.isfinite(parameter.grad)))
    ]
    if missing_or_invalid:
        raise AssertionError(f"autograd self-test failed for: {missing_or_invalid[:8]}")

    stratified = collect_stratified_examples(iter(records), 8, seed=1234)
    stratified_phases = Counter(int(record["phase"].item()) for record in stratified)
    if stratified_phases != Counter({phase: 2 for phase in PHASES}):
        raise AssertionError(f"stratified overfit self-test failed: {stratified_phases}")
    print(
        f"SELF-TEST PASS: parameter_count={len(original_values)}, "
        f"bit_exact_roundtrip=yes, forward_cases={len(expected)}, "
        f"max_abs_error={max_error:.3e}, d4_split=yes, zip_stream=yes, "
        f"stratified_overfit=yes, autograd=yes"
    )


def train(config: dict[str, Any], args: argparse.Namespace) -> Path | None:
    if bool(config.get("safety", {}).get("dry_run_only", False)):
        raise RuntimeError(
            "dry-run-only configs must use tools/dry_run_value_pipeline.py"
        )
    timing_only = bool(args.timing_only)
    if bool(config.get("safety", {}).get("timing_only", False)) and not timing_only:
        raise RuntimeError(
            "timing-only config requires --timing-only; use tools/timing_value_pipeline.py"
        )
    if timing_only:
        safety = config.get("safety", {})
        if not isinstance(safety, dict) or safety.get("timing_only") is not True:
            raise RuntimeError("--timing-only requires safety.timing_only=true")
        if args.resume or args.overfit or not args.no_export:
            raise RuntimeError(
                "timing-only forbids resume/overfit/export; pass --no-export"
            )
        if int(config.get("training", {}).get("epochs", -1)) != 1:
            raise RuntimeError("timing-only requires exactly one full epoch")
    progress_enabled, progress_interval = progress_settings(config, args)
    seed = int(config["seed"])
    training_config = config["training"]
    deterministic = bool(training_config.get("deterministic", True))
    set_reproducible_seed(seed, deterministic)
    device = choose_device(args.device or training_config.get("device", "auto"))
    dtype = choose_dtype(config.get("model", {}).get("dtype", "float64"))
    overfit_config = config.get("overfit", {})
    if not isinstance(overfit_config, dict):
        raise ValueError("overfit must be an object")
    overfit_enabled = bool(args.overfit)
    resume_config = config.get("resume", {})
    if not isinstance(resume_config, dict):
        raise ValueError("resume must be an object")
    output_config_contract = config.get("output")
    if not isinstance(output_config_contract, dict):
        raise ValueError("output must be an object")
    if config.get("output_dir") != output_config_contract.get("runs_dir"):
        raise ValueError("output_dir must equal output.runs_dir")
    if config.get("parameter_export_path") != output_config_contract.get("candidate_path"):
        raise ValueError("parameter_export_path must equal output.candidate_path")
    if overfit_enabled and args.resume:
        raise RuntimeError("overfit gate cannot resume a production checkpoint")
    if not overfit_enabled and bool(resume_config.get("require_checkpoint", False)) and not args.resume:
        raise RuntimeError(
            "this variant requires --resume; use value_11a_fresh.json when the legacy checkpoint is unavailable"
        )
    if args.resume and bool(resume_config.get("forbid_resume", False)):
        raise RuntimeError("this fresh-seed variant forbids --resume")
    if bool(resume_config.get("require_checkpoint", False)):
        pinned = config.get("checkpoint_resume_from")
        if not isinstance(pinned, str) or not pinned:
            raise RuntimeError("checkpoint_resume_from must pin checkpoint_last.pt")
        if not bool(config.get("resume_optimizer_state", False)):
            raise RuntimeError("resume_optimizer_state must be true")
        if args.resume:
            requested_resume = Path(args.resume).expanduser().resolve()
            pinned_resume = resolve_project_path(pinned).resolve()
            if (
                requested_resume != pinned_resume
                and not bool(resume_config.get("allow_format_2_resume", False))
            ):
                raise RuntimeError(
                    "--resume is neither the pinned legacy import nor an allowed format-2 continuation"
                )
    else:
        if config.get("checkpoint_resume_from") is not None:
            raise RuntimeError("fresh variants require checkpoint_resume_from=null")
        if not bool(config.get("resume_optimizer_state", False)):
            raise RuntimeError(
                "resume_optimizer_state must be true for format-2 interruption recovery"
            )
        if args.resume and not bool(resume_config.get("allow_format_2_resume", False)):
            raise RuntimeError("this variant does not allow format-2 continuation")

    # Fail early on a missing, misplaced, corrupt, or unsupported checkpoint,
    # before the expensive prepared-shard verification starts.
    resume_path: Path | None = None
    resume_best_path: Path | None = None
    checkpoint: dict[str, Any] | None = None
    resume_best_checkpoint: dict[str, Any] | None = None
    if args.resume:
        resume_path = resolve_allowed_resume_path(Path(args.resume), config)
        resume_best_path = resolve_resume_best_checkpoint(resume_path)
        checkpoint = torch.load(resume_path, map_location=device, weights_only=False)
        resume_best_checkpoint = torch.load(
            resume_best_path, map_location=device, weights_only=False
        )
        for label, payload in (
            ("resume checkpoint", checkpoint),
            ("resume best checkpoint", resume_best_checkpoint),
        ):
            if not isinstance(payload, dict):
                raise RuntimeError(f"{label} root is not a checkpoint object")
            version = int(payload.get("format_version", -1))
            if version not in {
                LEGACY_CHECKPOINT_FORMAT_VERSION,
                CHECKPOINT_FORMAT_VERSION,
            }:
                raise RuntimeError(f"{label} format {version} is unsupported")
        pinned_raw = config.get("checkpoint_resume_from")
        pinned_path = (
            resolve_project_path(pinned_raw).resolve()
            if isinstance(pinned_raw, str) and pinned_raw else None
        )
        selected_is_pinned = pinned_path is not None and resume_path == pinned_path
        selected_version = int(checkpoint.get("format_version", -1))
        best_version = int(resume_best_checkpoint.get("format_version", -1))
        if selected_is_pinned:
            if selected_version != LEGACY_CHECKPOINT_FORMAT_VERSION or best_version != LEGACY_CHECKPOINT_FORMAT_VERSION:
                raise RuntimeError("the pinned original_10 import must remain format-1")
        else:
            if not bool(resume_config.get("allow_format_2_resume", False)):
                raise RuntimeError("format-2 continuation is disabled for this variant")
            if selected_version != CHECKPOINT_FORMAT_VERSION or best_version != CHECKPOINT_FORMAT_VERSION:
                raise RuntimeError("non-pinned continuation accepts format-2 checkpoints only")

    data_config = config["data"]
    epoch_mode, required_phases = validate_data_supply(data_config, training_config)
    (
        prepared_manifest,
        prepared_split_counts,
        paths_by_split,
        pre_split,
        paths,
    ) = resolve_and_verify_training_data(
        config,
        progress_enabled=progress_enabled,
        progress_interval=progress_interval,
        skip_prepared_shard_hash=bool(args.pipeline_verified),
    )

    parameter_init_path = resolve_project_path(config["parameter_init"]).resolve()
    expected_source_sha256 = str(config.get("source_model_sha256", "")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256):
        raise ValueError("source_model_sha256 must contain 64 lowercase hex digits")
    actual_source_sha256 = file_sha256(parameter_init_path)
    if actual_source_sha256 != expected_source_sha256:
        raise RuntimeError(
            "parameter_init SHA-256 differs from source_model_sha256: "
            f"{parameter_init_path}"
        )
    model = JavaCompatibleEvaluator(dtype)
    model.load_java_parameters(parameter_init_path)
    model.to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(training_config["learning_rate"]),
        weight_decay=float(training_config.get("weight_decay", 0.0)),
    )
    scheduler = build_scheduler(optimizer, training_config)
    early_settings = early_stopping_settings(training_config)
    start_epoch = 0
    best_validation_rmse = math.inf
    early_stop_state: dict[str, Any] = {
        "epochs_without_improvement": 0,
        "completed_epochs": 0,
        "stopped_early": False,
    }
    lineage_id = uuid.uuid4().hex
    if checkpoint is not None and resume_best_checkpoint is not None:
        validate_resume_compatibility(
            checkpoint,
            label='resume checkpoint',
            config=config,
            overfit_enabled=overfit_enabled,
            prepared_manifest=prepared_manifest,
            continuation_checkpoint=True,
        )
        validate_resume_compatibility(
            resume_best_checkpoint,
            label='resume best checkpoint',
            config=config,
            overfit_enabled=overfit_enabled,
            prepared_manifest=prepared_manifest,
            continuation_checkpoint=False,
        )
        if int(checkpoint.get("format_version", -1)) == CHECKPOINT_FORMAT_VERSION:
            if checkpoint.get("checkpoint_role") != "last":
                raise RuntimeError("checkpoint_last.pt has the wrong checkpoint_role")
            if resume_best_checkpoint.get("checkpoint_role") != "best":
                raise RuntimeError("checkpoint_best.pt has the wrong checkpoint_role")
            if checkpoint.get("lineage_id") != resume_best_checkpoint.get("lineage_id"):
                raise RuntimeError("format-2 last/best checkpoints have different lineage_id")
        model.load_state_dict(checkpoint["model_state"])
        optimizer.load_state_dict(checkpoint["optimizer_state"])
        if (
            int(checkpoint.get("format_version", -1))
            == LEGACY_CHECKPOINT_FORMAT_VERSION
            and bool(resume_config.get("override_optimizer_learning_rate", False))
        ):
            configured_lr = float(training_config["learning_rate"])
            for parameter_group in optimizer.param_groups:
                parameter_group["lr"] = configured_lr
                parameter_group["initial_lr"] = configured_lr
        start_epoch = int(checkpoint["epoch"]) + 1
        best_validation_rmse = float(resume_best_checkpoint["best_validation_rmse"])
        checkpoint_best_rmse = float(checkpoint["best_validation_rmse"])
        if not math.isclose(
            checkpoint_best_rmse,
            best_validation_rmse,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise RuntimeError(
                "resume checkpoint and checkpoint_best.pt disagree on best validation RMSE"
            )
        if int(checkpoint.get("format_version", -1)) == CHECKPOINT_FORMAT_VERSION:
            scheduler.load_state_dict(checkpoint["scheduler_state"])
            early_stop_state = dict(checkpoint["early_stop_state"])
            restore_rng_state(checkpoint["rng_state"])
            lineage_id = str(checkpoint["lineage_id"])
        else:
            # The verified original_10 format-1 checkpoint has AdamW state but
            # no scheduler/early-stop/RNG state.  AdamW is continued, the
            # configured lower LR is applied, and only those missing controls
            # start afresh.  This migration is allowed solely by explicit config.
            early_stop_state["completed_epochs"] = start_epoch
    batch_size = int(training_config["batch_size"])
    epochs = int(training_config["epochs"])
    num_workers = int(training_config.get("num_workers", 0))
    pin_memory = (
        bool(training_config.get("pin_memory", device.type == "cuda"))
        and device.type == "cuda"
    )

    train_stream = PositionStream(
        paths_by_split['train'], "train", data_config, seed,
        augment_d4=bool(data_config.get("d4_augmentation", True)),
        pre_split=pre_split,
    )
    val_stream = PositionStream(
        paths_by_split['val'], "val", data_config, seed + 1,
        augment_d4=False, pre_split=pre_split,
    )
    test_stream = PositionStream(
        paths_by_split['test'], "test", data_config, seed + 2,
        augment_d4=False, pre_split=pre_split,
    )
    if overfit_enabled:
        examples = int(overfit_config.get("examples", 2048))
        if bool(overfit_config.get("phase_stratified", False)):
            with ProgressReporter(
                examples,
                label='selected',
                phase='overfit sample',
                interval=progress_interval,
                quiet=not progress_enabled,
            ) as progress:
                cached = collect_stratified_examples(
                    iter(train_stream), examples, seed, progress
                )
        else:
            cached = list(itertools.islice(iter(train_stream), examples))
        if len(cached) < examples:
            raise RuntimeError(f"overfit mode requested {examples} examples, found {len(cached)}")
        cached_dataset = CachedRecords(cached)
        batch_size = int(overfit_config.get("batch_size", batch_size))
        epochs = int(overfit_config.get("epochs", epochs))
        train_loader = make_loader(
            cached_dataset, batch_size, 0, pin_memory, shuffle=True, seed=seed,
        )
        val_loader = make_loader(cached_dataset, batch_size, 0, pin_memory)
        test_loader = make_loader(cached_dataset, batch_size, 0, pin_memory)
        max_train_steps = 0
        max_val_steps = 0
        max_test_steps = 0
    else:
        train_loader = make_loader(train_stream, batch_size, num_workers, pin_memory)
        val_loader = make_loader(val_stream, batch_size, num_workers, pin_memory)
        test_loader = make_loader(test_stream, batch_size, num_workers, pin_memory)
        max_train_steps = int(training_config.get("steps_per_epoch", 0))
        max_val_steps = int(training_config.get("validation_steps", 0))
        max_test_steps = int(training_config.get("test_steps", 0))

    output_config = config["output"]
    artifacts_root = (PROJECT_ROOT / "artifacts").resolve()
    runs_root = resolve_project_path(
        output_config.get("runs_dir", "artifacts/training_runs")
    ).resolve()
    if not runs_root.is_relative_to(artifacts_root):
        raise ValueError("output.runs_dir must stay under artifacts/")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = runs_root / f"run_{timestamp}_seed{seed}"
    suffix = 1
    while run_dir.exists():
        run_dir = runs_root / f"run_{timestamp}_seed{seed}_{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True, exist_ok=False)
    resolved_config = dict(config)
    resolved_config["resolved"] = {
        "project_root": str(PROJECT_ROOT),
        "data_files": [str(path) for path in paths],
        "device": str(device),
        "torch_version": torch.__version__,
        "overfit": overfit_enabled,
        "epoch_mode": epoch_mode,
        "required_phases": list(required_phases),
        "parameter_count": EXPECTED_PARAMETER_COUNT,
        "parameter_init": str(parameter_init_path),
        "parameter_init_sha256": actual_source_sha256,
        "checkpoint_format_version": CHECKPOINT_FORMAT_VERSION,
        "lineage_id": lineage_id,
        "scheduler": training_config["scheduler"],
        "early_stopping": early_settings,
        "prepared_manifest": (
            None
            if prepared_manifest is None
            else prepared_manifest['_resolved_path']
        ),
        "prepared_split_counts": prepared_split_counts,
        "resume_checkpoint": None if resume_path is None else str(resume_path),
        "resume_best_checkpoint": (
            None if resume_best_path is None else str(resume_best_path)
        ),
        "prepared_manifest_contract_sha256": (
            prepared_manifest_contract_sha256(prepared_manifest)
        ),
    }
    (run_dir / "config_resolved.json").write_text(
        json.dumps(resolved_config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metrics_path = run_dir / "metrics.jsonl"
    if resume_best_checkpoint is not None:
        # Normalize an imported format-1 best model into the format-2 lineage.
        # Its optimizer/scheduler fields are never used for continuation; safe
        # continuation always selects checkpoint_last.pt.
        save_checkpoint(
            run_dir / "checkpoint_best.pt",
            model,
            optimizer,
            scheduler,
            int(resume_best_checkpoint["epoch"]),
            float(resume_best_checkpoint["best_validation_rmse"]),
            resolved_config,
            early_stop_state,
            lineage_id,
            "best",
            model_state_override=resume_best_checkpoint["model_state"],
        )
    phase_weights = torch.tensor(
        training_config.get("phase_loss_weights", [1.0, 1.0, 1.0, 1.0]),
        dtype=dtype,
        device=device,
    )
    if phase_weights.shape != (4,) or bool(torch.any(phase_weights <= 0.0)):
        raise ValueError("training.phase_loss_weights must contain four positive values")
    gradient_clip = float(training_config.get("gradient_clip", 0.0))
    target_scale = float(data_config.get("target_scale", 64.0))
    overfit_initial_result: dict[str, Any] | None = None
    if overfit_enabled:
        with ProgressReporter(
            loader_length(val_loader),
            label='batches',
            phase='overfit initial evaluation',
            interval=progress_interval,
            quiet=not progress_enabled,
        ) as progress:
            initial_metrics = evaluate_loader(
                model, val_loader, device, max_val_steps, progress
            )
        require_phase_coverage(initial_metrics, required_phases, "overfit initial sample")
        overfit_initial_result = initial_metrics.as_dict(target_scale)
        initial_record = {
            "event": "overfit_initial",
            "seed": seed,
            "metrics": overfit_initial_result,
        }
        append_jsonl(metrics_path, initial_record)
        print(json.dumps(initial_record, ensure_ascii=False, sort_keys=True), flush=True)

    timing_measurement: dict[str, Any] | None = None
    for epoch in range(start_epoch, epochs):
        train_stream.set_epoch(epoch)
        val_stream.set_epoch(epoch)
        train_total = loader_length(train_loader)
        train_estimated = False
        if train_total is None:
            train_total, train_estimated = expected_loader_steps(
                data_config, 'train', batch_size, max_train_steps,
                prepared_split_counts,
            )
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        train_started = time.perf_counter()
        with ProgressReporter(
            train_total,
            label='batches~' if train_estimated else 'batches',
            phase=f'epoch {epoch + 1}/{epochs} train',
            interval=progress_interval,
            quiet=not progress_enabled,
        ) as progress:
            train_metrics = train_epoch(
                model, train_loader, optimizer, device, max_train_steps,
                gradient_clip, phase_weights, progress,
            )
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        train_elapsed_seconds = time.perf_counter() - train_started
        if train_metrics.count == 0:
            raise RuntimeError("training stream yielded no records; check paths and split settings")
        require_phase_coverage(train_metrics, required_phases, "training epoch")
        require_full_pass_count(
            train_metrics,
            data_config,
            "train",
            prepared_split_counts,
            max_train_steps,
            overfit_enabled,
            "training epoch",
        )
        val_total = loader_length(val_loader)
        val_estimated = False
        if val_total is None:
            val_total, val_estimated = expected_loader_steps(
                data_config, 'val', batch_size, max_val_steps,
                prepared_split_counts,
            )
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        validation_started = time.perf_counter()
        with ProgressReporter(
            val_total,
            label='batches~' if val_estimated else 'batches',
            phase=f'epoch {epoch + 1}/{epochs} validation',
            interval=progress_interval,
            quiet=not progress_enabled,
        ) as progress:
            validation_metrics = evaluate_loader(
                model, val_loader, device, max_val_steps, progress
            )
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        validation_elapsed_seconds = time.perf_counter() - validation_started
        if validation_metrics.count == 0:
            raise RuntimeError("validation stream yielded no records; check split/data limits")
        require_phase_coverage(validation_metrics, required_phases, "validation epoch")
        require_full_pass_count(
            validation_metrics,
            data_config,
            "val",
            prepared_split_counts,
            max_val_steps,
            overfit_enabled,
            "validation epoch",
        )
        train_result = train_metrics.as_dict(target_scale)
        validation_result = validation_metrics.as_dict(target_scale)
        validation_rmse = float(validation_result["rmse"])
        learning_rate_before = float(optimizer.param_groups[0]["lr"])
        previous_best = best_validation_rmse
        improved = validation_rmse < previous_best
        significant_improvement = (
            validation_rmse < previous_best - float(early_settings["min_delta"])
        )
        if improved:
            best_validation_rmse = validation_rmse
        if significant_improvement:
            early_stop_state["epochs_without_improvement"] = 0
        else:
            early_stop_state["epochs_without_improvement"] = (
                int(early_stop_state.get("epochs_without_improvement", 0)) + 1
            )
        early_stop_state["completed_epochs"] = (
            int(early_stop_state.get("completed_epochs", 0)) + 1
        )
        scheduler.step(validation_rmse)
        learning_rate_after = float(optimizer.param_groups[0]["lr"])
        should_stop = (
            int(early_stop_state["completed_epochs"])
            >= int(early_settings["minimum_epochs"])
            and int(early_stop_state["epochs_without_improvement"])
            >= int(early_settings["patience"])
        )
        early_stop_state["stopped_early"] = should_stop
        record = {
            "epoch": epoch,
            "seed": seed,
            "learning_rate": learning_rate_before,
            "learning_rate_next": learning_rate_after,
            "best_validation_rmse": best_validation_rmse,
            "validation_improved": improved,
            "early_stop_state": dict(early_stop_state),
            "train": train_result,
            "val": validation_result,
            "train_elapsed_seconds": train_elapsed_seconds,
            "validation_elapsed_seconds": validation_elapsed_seconds,
            "train_items_per_second": (
                train_metrics.count / max(train_elapsed_seconds, 1e-12)
            ),
            "validation_items_per_second": (
                validation_metrics.count / max(validation_elapsed_seconds, 1e-12)
            ),
        }
        if timing_only:
            timing_measurement = {
                "epoch": epoch,
                "train_items": train_metrics.count,
                "validation_items": validation_metrics.count,
                "train_elapsed_seconds": train_elapsed_seconds,
                "validation_elapsed_seconds": validation_elapsed_seconds,
                "train_items_per_second": record["train_items_per_second"],
                "validation_items_per_second": record[
                    "validation_items_per_second"
                ],
            }
        append_jsonl(metrics_path, record)
        print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)

        if improved:
            save_checkpoint(
                run_dir / "checkpoint_best.pt",
                model,
                optimizer,
                scheduler,
                epoch,
                best_validation_rmse,
                resolved_config,
                early_stop_state,
                lineage_id,
                "best",
            )
        save_checkpoint(
            run_dir / "checkpoint_last.pt",
            model,
            optimizer,
            scheduler,
            epoch,
            best_validation_rmse,
            resolved_config,
            early_stop_state,
            lineage_id,
            "last",
        )
        if should_stop:
            append_jsonl(metrics_path, {
                "event": "early_stop",
                "epoch": epoch,
                "best_validation_rmse": best_validation_rmse,
                "state": dict(early_stop_state),
            })
            break

    if timing_only:
        if timing_measurement is None:
            raise RuntimeError("timing-only run completed no epoch")
        checkpoint_last = run_dir / "checkpoint_last.pt"
        checkpoint_best = run_dir / "checkpoint_best.pt"
        if not checkpoint_last.is_file() or not checkpoint_best.is_file():
            raise RuntimeError("timing-only run did not produce both checkpoints")
        gpu: dict[str, Any] = {
            "requested_device": args.device or training_config.get("device", "auto"),
            "resolved_device": str(device),
            "torch_cuda_available": torch.cuda.is_available(),
        }
        if device.type == "cuda":
            gpu["name"] = torch.cuda.get_device_name(device)
            gpu["capability"] = list(torch.cuda.get_device_capability(device))
        timing_manifest = {
            "schema": "original-11-value-full-pass-timing-v1",
            "status": "complete",
            "timing_only": True,
            "production_code_path_same": True,
            "production_code_path": str(Path(__file__).resolve()),
            "production_data_path_same": True,
            "full_pass": True,
            "required_phases": list(required_phases),
            "epochs": 1,
            "normal_validation": True,
            "heldout_test_run": False,
            "candidate_exported": False,
            "adoption_eligible": False,
            "training_eligible_artifact": False,
            "run_dir": str(run_dir),
            "checkpoint_last": str(checkpoint_last),
            "checkpoint_last_sha256": file_sha256(checkpoint_last),
            "checkpoint_best": str(checkpoint_best),
            "checkpoint_best_sha256": file_sha256(checkpoint_best),
            "checkpoint_format_version": CHECKPOINT_FORMAT_VERSION,
            "lineage_id": lineage_id,
            "seed": seed,
            "source_model_sha256": actual_source_sha256,
            "prepared_manifest_contract_sha256": (
                prepared_manifest_contract_sha256(prepared_manifest)
            ),
            "measurement": timing_measurement,
            "gpu": gpu,
            "interruption_semantics": (
                "No mid-epoch checkpoint is written. After Ctrl+C, rerun timing "
                "from the beginning in a new exclusive run directory."
            ),
        }
        timing_manifest_path = run_dir / "timing_manifest.json"
        with timing_manifest_path.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(timing_manifest, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
        append_jsonl(metrics_path, {"event": "timing_complete", **timing_manifest})
        print(json.dumps(timing_manifest, ensure_ascii=False, sort_keys=True), flush=True)
        return None

    best = torch.load(run_dir / "checkpoint_best.pt", map_location=device, weights_only=False)
    model.load_state_dict(best["model_state"])
    test_total = loader_length(test_loader)
    test_estimated = False
    if test_total is None:
        test_total, test_estimated = expected_loader_steps(
            data_config, 'test', batch_size, max_test_steps,
            prepared_split_counts,
        )
    with ProgressReporter(
        test_total,
        label='batches~' if test_estimated else 'batches',
        phase='test',
        interval=progress_interval,
        quiet=not progress_enabled,
    ) as progress:
        test_metrics = evaluate_loader(
            model, test_loader, device, max_test_steps, progress
        )
    if test_metrics.count == 0:
        raise RuntimeError("test stream yielded no records; check split/data limits")
    require_phase_coverage(test_metrics, required_phases, "test data")
    require_full_pass_count(
        test_metrics,
        data_config,
        "test",
        prepared_split_counts,
        max_test_steps,
        overfit_enabled,
        "test data",
    )
    test_result = test_metrics.as_dict(target_scale)
    append_jsonl(metrics_path, {"event": "test", "seed": seed, "test": test_result})

    overfit_check: dict[str, Any] | None = None
    if overfit_enabled:
        assert overfit_initial_result is not None
        initial_rmse = float(overfit_initial_result["rmse_score_units"])
        final_rmse = float(test_result["rmse_score_units"])
        reduction = (initial_rmse - final_rmse) / initial_rmse if initial_rmse > 0.0 else 0.0
        required_reduction = float(
            overfit_config.get("minimum_relative_rmse_reduction", 0.10)
        )
        passed = (
            math.isfinite(initial_rmse)
            and math.isfinite(final_rmse)
            and final_rmse < initial_rmse
            and reduction >= required_reduction
        )
        overfit_check = {
            "event": "overfit_check",
            "passed": passed,
            "examples": int(overfit_config.get("examples", 2048)),
            "initial_rmse_score_units": initial_rmse,
            "final_rmse_score_units": final_rmse,
            "relative_rmse_reduction": reduction,
            "minimum_relative_rmse_reduction": required_reduction,
            "phase_counts": test_result["phase_counts"],
        }
        append_jsonl(metrics_path, overfit_check)
        print(json.dumps(overfit_check, ensure_ascii=False, sort_keys=True), flush=True)
        if not passed:
            raise RuntimeError(
                "overfit sanity check failed: RMSE did not decrease by the configured margin"
            )

    manifest = {
        "run_name": config.get("run_name"),
        "candidate_name": config.get("candidate_name"),
        "variant": config.get("experiment", {}).get("variant"),
        "candidate_path": None,
        "exported": False,
        "parameter_count": EXPECTED_PARAMETER_COUNT,
        "finite": True,
        "best_epoch": int(best["epoch"]),
        "best_validation_rmse": float(best["best_validation_rmse"]),
        "test": test_result,
        "seed": seed,
        "checkpoint_format_version": CHECKPOINT_FORMAT_VERSION,
        "lineage_id": lineage_id,
        "resume_checkpoint": None if resume_path is None else str(resume_path),
        "scheduler": training_config["scheduler"],
        "early_stopping": {
            "settings": early_settings,
            "state": early_stop_state,
        },
        "source_model_sha256": actual_source_sha256,
        "datasets": config.get("datasets"),
        "prepared_manifest_contract_sha256": (
            prepared_manifest_contract_sha256(prepared_manifest)
        ),
        "source_files": [str(path) for path in paths],
        "overfit_check": overfit_check,
    }
    candidate_path: Path | None = None
    if not args.no_export:
        requested_export = resolve_project_path(
            args.export or output_config["candidate_path"]
        ).resolve()
        if not requested_export.is_relative_to(artifacts_root):
            raise ValueError("candidate export must stay under artifacts/")
        candidate_path = next_candidate_path(requested_export)
        model.to("cpu")
        export_java_parameters(model, candidate_path)
        manifest["candidate_path"] = str(candidate_path)
        manifest["candidate_sha256"] = file_sha256(candidate_path)
        manifest["exported"] = True
    manifest_name = Path(str(config.get("manifest_output_path", "export_manifest.json")))
    if manifest_name.is_absolute() or manifest_name.parent != Path("."):
        raise ValueError("manifest_output_path must be a filename inside the run directory")
    (run_dir / manifest_name).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    event = "export" if candidate_path is not None else "run_complete"
    print(json.dumps({"event": event, **manifest}, ensure_ascii=False, sort_keys=True))
    return candidate_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--self-test", action="store_true", help="parameter round-trip and forward parity; no data needed")
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="verify prepared shards or stream source files; never train",
    )
    parser.add_argument("--scan-limit", type=int, default=0, help="0 scans every source record")
    parser.add_argument("--overfit", action="store_true", help="cache a few thousand examples and train repeatedly")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--device", help="auto, cpu, cuda, cuda:0, ...")
    parser.add_argument("--export", type=Path, help="candidate parameter destination")
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="complete training and checks without writing a parameter candidate",
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='disable CUI progress while preserving JSON and final summaries',
    )
    parser.add_argument(
        '--pipeline-verified',
        action='store_true',
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        '--timing-only',
        action='store_true',
        help='run the dedicated one-epoch full-pass timing path without test/export',
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    if args.scan_only and args.pipeline_verified:
        raise ValueError("--pipeline-verified is not valid with --scan-only")
    if args.self_test:
        self_test(config)
        return 0
    if args.scan_only:
        progress_enabled, progress_interval = progress_settings(config, args)
        if config['data'].get('prepared_manifest') is not None:
            (
                manifest,
                split_counts,
                _paths_by_split,
                _pre_split,
                paths,
            ) = resolve_and_verify_training_data(
                config,
                progress_enabled=progress_enabled,
                progress_interval=progress_interval,
            )
            assert manifest is not None and split_counts is not None
            print(json.dumps({
                'prepared_manifest': manifest['_resolved_path'],
                'status': manifest['status'],
                'source_records': sum(split_counts.values()),
                'split_counts': split_counts,
                'phase_counts': manifest['counts']['prepared_records_by_phase'],
                'shard_files': len(paths),
                'shard_integrity': 'passed',
                'configured_expectations': 'passed',
            }, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        paths = resolve_data_paths(config["data"]["paths"])
        if not paths:
            raise FileNotFoundError("no data files matched config data.paths")
        scan_total = (
            args.scan_limit
            if args.scan_limit > 0
            else config['data'].get('expected_source_records')
        )
        with ProgressReporter(
            None if scan_total is None else int(scan_total),
            label='records',
            phase='scan',
            interval=progress_interval,
            quiet=not progress_enabled,
        ) as progress:
            result = scan_dataset(
                paths, config['data'], args.scan_limit, progress
            )
        if args.scan_limit == 0:
            validate_scan_expectations(result, config["data"])
            result["configured_expectations"] = "passed"
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    candidate = train(config, args)
    if candidate is None:
        print("training/check complete: parameter export disabled")
    else:
        print(f"training complete: {candidate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
