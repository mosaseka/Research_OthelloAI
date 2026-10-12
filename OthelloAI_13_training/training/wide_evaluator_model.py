"""Width-48 differentiable evaluator for the original_13 experiment.

This module owns the exact mapping between the 142,812-line width-48 parameter
file and trainable tensors.  It extracts the same 42 pattern occurrences and
three auxiliary features as original_11/12; only the two hidden layers of each
pattern MLP change from 16 units to 48 units.

original_11 uses the exact-mobility schema introduced by original_10 and
deliberately replaces the old line-sum mobility approximation
with ``exact-mobility-v1``: count unique legal squares for the side to move,
clamp the count to 30, and use a positive value for black / negative for white.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Sequence

try:
    import torch
    from torch import Tensor, nn
except ImportError as error:  # pragma: no cover - depends on local environment
    raise ImportError(
        "PyTorch is required for evaluator training. Install a build suitable "
        "for this machine from https://pytorch.org/get-started/locally/ and "
        "then rerun training/train_evaluator.py."
    ) from error

from wide_java_eval import (
    EXPECTED_PARAMETER_COUNT,
    MAX_CANPUT,
    MAX_SURROUND,
    N_ADD_DENSE0,
    N_ADD_DENSE1,
    N_DENSE0,
    N_DENSE1,
    N_PHASES,
    PATTERN_SIZES,
    POW3,
    REVERSE_LINE,
    SURROUND_TABLE,
    Evaluator as ReferenceEvaluator,
    encode_board,
)


PATTERN_COUNTS = (4, 4, 4, 4, 4, 4, 2, 4, 4, 4, 4)
PATTERN_OFFSETS = tuple(
    sum(PATTERN_COUNTS[:index]) for index in range(len(PATTERN_COUNTS) + 1)
)
N_PATTERN_OCCURRENCES = PATTERN_OFFSETS[-1]
FULL_BOARD = (1 << 64) - 1
HORIZONTAL_MASK = 0x7E7E7E7E7E7E7E7E
REVERSE_ORDERS: tuple[tuple[int, ...], ...] = (
    tuple(range(7, -1, -1)),
    tuple(range(7, -1, -1)),
    tuple(range(7, -1, -1)),
    tuple(range(4, -1, -1)),
    tuple(range(5, -1, -1)),
    tuple(range(6, -1, -1)),
    tuple(range(7, -1, -1)),
    tuple(range(9, -1, -1)),
    (0, 4, 7, 9, 1, 5, 8, 2, 6, 3),
    (5, 4, 3, 2, 1, 0, 9, 8, 7, 6),
    (0, 1, 2, 3, 7, 8, 9, 4, 5, 6),
)


@dataclass(frozen=True)
class ModelFeatures:
    pattern_indices: tuple[int, ...]
    phase: int
    player: int
    canput: int
    surround_black: int
    surround_white: int


def _digit(index: int, place: int) -> int:
    return (index // POW3[7 - place]) % 3


def _pop_mid(index: int, high: int, low: int) -> int:
    return (index % POW3[high]) // POW3[low]


def _edge_2x(lines: tuple[int, ...], x: int, y: int) -> int:
    return _digit(lines[x], 1) * POW3[9] + lines[y] * POW3[1] + _digit(lines[x], 6)


def _triangle0(lines: tuple[int, ...], w: int, x: int, y: int, z: int) -> int:
    return (
        lines[w] // POW3[4] * POW3[6]
        + lines[x] // POW3[5] * POW3[3]
        + lines[y] // POW3[6] * POW3[1]
        + lines[z] // POW3[7]
    )


def _triangle1(lines: tuple[int, ...], w: int, x: int, y: int, z: int) -> int:
    return (
        REVERSE_LINE[lines[w]] // POW3[4] * POW3[6]
        + REVERSE_LINE[lines[x]] // POW3[5] * POW3[3]
        + REVERSE_LINE[lines[y]] // POW3[6] * POW3[1]
        + REVERSE_LINE[lines[z]] // POW3[7]
    )


def _edge_block(lines: tuple[int, ...], x: int, y: int) -> int:
    return (
        _digit(lines[x], 0) * POW3[9]
        + _pop_mid(lines[x], 6, 2) * POW3[5]
        + _digit(lines[x], 7) * POW3[4]
        + _pop_mid(lines[y], 6, 2)
    )


def _cross(lines: tuple[int, ...], x: int, y: int, z: int) -> tuple[int, int]:
    forward = (
        lines[x] // POW3[4] * POW3[6]
        + lines[y] // POW3[5] * POW3[3]
        + lines[z] // POW3[5]
    )
    reverse_x = REVERSE_LINE[lines[x]]
    reverse_y = REVERSE_LINE[lines[y]]
    reverse_z = REVERSE_LINE[lines[z]]
    reverse = (
        reverse_x // POW3[4] * POW3[6]
        + _pop_mid(reverse_y, 7, 4) * POW3[3]
        + _pop_mid(reverse_z, 7, 4)
    )
    return forward, reverse


def extract_pattern_indices(lines: tuple[int, ...]) -> tuple[int, ...]:
    """Return all indices in the exact eleven-group Java accumulation order."""

    result: list[int] = []
    result.extend((lines[1], lines[6], lines[9], lines[14]))
    result.extend((lines[2], lines[5], lines[10], lines[13]))
    result.extend((lines[3], lines[4], lines[11], lines[12]))
    result.extend((lines[18] // POW3[3], lines[24] // POW3[3],
                   lines[29] // POW3[3], lines[35] // POW3[3]))
    result.extend((lines[19] // POW3[2], lines[23] // POW3[2],
                   lines[30] // POW3[2], lines[34] // POW3[2]))
    result.extend((lines[20] // POW3[1], lines[22] // POW3[1],
                   lines[31] // POW3[1], lines[33] // POW3[1]))
    result.extend((lines[21], lines[32]))
    result.extend((_edge_2x(lines, 1, 0), _edge_2x(lines, 6, 7),
                   _edge_2x(lines, 9, 8), _edge_2x(lines, 14, 15)))
    result.extend((_triangle0(lines, 0, 1, 2, 3),
                   _triangle0(lines, 7, 6, 5, 4),
                   _triangle0(lines, 15, 14, 13, 12),
                   _triangle1(lines, 15, 14, 13, 12)))
    result.extend((_edge_block(lines, 0, 1), _edge_block(lines, 7, 6),
                   _edge_block(lines, 8, 9), _edge_block(lines, 15, 14)))
    result.extend(_cross(lines, 21, 20, 22))
    result.extend(_cross(lines, 32, 31, 33))
    if len(result) != N_PATTERN_OCCURRENCES:
        raise AssertionError(f"expected {N_PATTERN_OCCURRENCES} pattern indices, got {len(result)}")
    return tuple(result)


def legal_moves_bits(player: int, opponent: int) -> int:
    """Return the exact legal-square bitboard for row-major bitboards."""

    masked_opponent = opponent & HORIZONTAL_MASK
    flip1 = masked_opponent & (player << 1)
    flip7 = masked_opponent & (player << 7)
    flip9 = masked_opponent & (player << 9)
    flip8 = opponent & (player << 8)

    flip1 |= masked_opponent & (flip1 << 1)
    flip7 |= masked_opponent & (flip7 << 7)
    flip9 |= masked_opponent & (flip9 << 9)
    flip8 |= opponent & (flip8 << 8)

    pre1 = masked_opponent & (masked_opponent << 1)
    pre7 = masked_opponent & (masked_opponent << 7)
    pre9 = masked_opponent & (masked_opponent << 9)
    pre8 = opponent & (opponent << 8)
    for _ in range(2):
        flip1 |= pre1 & (flip1 << 2)
        flip7 |= pre7 & (flip7 << 14)
        flip9 |= pre9 & (flip9 << 18)
        flip8 |= pre8 & (flip8 << 16)

    moves = (flip1 << 1) | (flip7 << 7) | (flip9 << 9) | (flip8 << 8)

    flip1 = masked_opponent & (player >> 1)
    flip7 = masked_opponent & (player >> 7)
    flip9 = masked_opponent & (player >> 9)
    flip8 = opponent & (player >> 8)

    flip1 |= masked_opponent & (flip1 >> 1)
    flip7 |= masked_opponent & (flip7 >> 7)
    flip9 |= masked_opponent & (flip9 >> 9)
    flip8 |= opponent & (flip8 >> 8)

    pre1 >>= 1
    pre7 >>= 7
    pre9 >>= 9
    pre8 >>= 8
    for _ in range(2):
        flip1 |= pre1 & (flip1 >> 2)
        flip7 |= pre7 & (flip7 >> 14)
        flip9 |= pre9 & (flip9 >> 18)
        flip8 |= pre8 & (flip8 >> 16)

    moves |= (flip1 >> 1) | (flip7 >> 7) | (flip9 >> 9) | (flip8 >> 8)
    return moves & FULL_BOARD & ~(player | opponent)


def board_bitboards(board: str | Sequence[str]) -> tuple[int, int]:
    """Return absolute black/white row-major bitboards."""

    black = 0
    white = 0
    for cell, value in enumerate(board):
        if value == "0":
            black |= 1 << cell
        elif value == "1":
            white |= 1 << cell
        elif value != ".":
            raise ValueError(f"invalid absolute board symbol: {value!r}")
    return black, white


def exact_canput(board: str | Sequence[str], player: int) -> int:
    """Return the signed, clamped ``exact-mobility-v1`` feature."""

    black, white = board_bitboards(board)
    own, opponent = (black, white) if player == 0 else (white, black)
    count = min(MAX_CANPUT, legal_moves_bits(own, opponent).bit_count())
    return count if player == 0 else -count


def _sfill(line: int, digit_place: int, power: int) -> int:
    return line - POW3[power] + 1 if _digit(line, digit_place) != 2 else line


def _surround(lines: tuple[int, ...], player: int) -> int:
    table = SURROUND_TABLE[player]
    total = sum(table[line] for line in lines[:16])
    for index in (16, 26, 27, 37):
        total += table[_sfill(lines[index], 2, 5)]
    for index in (17, 25, 28, 36):
        total += table[_sfill(lines[index], 3, 4)]
    for index in (18, 24, 29, 35):
        total += table[_sfill(lines[index], 4, 3)]
    for index in (19, 23, 30, 34):
        total += table[_sfill(lines[index], 5, 2)]
    for index in (20, 22, 31, 33):
        total += table[_sfill(lines[index], 6, 1)]
    total += table[lines[21]] + table[lines[32]]
    return min(MAX_SURROUND, total)


def features_from_absolute(board: str | Sequence[str], player: int) -> ModelFeatures:
    encoded = encode_board(board, player)
    phase = max(0, min(3, (encoded.stone_count - 4) // 10 - 2))
    return ModelFeatures(
        extract_pattern_indices(encoded.lines),
        phase,
        player,
        exact_canput(board, player),
        _surround(encoded.lines, 0),
        _surround(encoded.lines, 1),
    )


def absolute_from_relative(relative_board: str, player: int) -> str:
    """Map Egaroucid X=current/O=opponent/-=empty to Java symbols."""

    if len(relative_board) != 64 or set(relative_board) - {"X", "O", "-"}:
        raise ValueError("relative board must be 64 characters from X, O, and -")
    if player == 0:
        translation = str.maketrans({"X": "0", "O": "1", "-": "."})
    elif player == 1:
        translation = str.maketrans({"X": "1", "O": "0", "-": "."})
    else:
        raise ValueError(f"player must be 0 or 1, got {player}")
    return relative_board.translate(translation)


def features_from_relative(relative_board: str, player: int) -> ModelFeatures:
    return features_from_absolute(absolute_from_relative(relative_board, player), player)


def feature_tensors(features: ModelFeatures, target: float | None = None) -> dict[str, Tensor]:
    record = {
        "pattern_indices": torch.tensor(features.pattern_indices, dtype=torch.long),
        "phase": torch.tensor(features.phase, dtype=torch.long),
        "player": torch.tensor(features.player, dtype=torch.long),
        "canput": torch.tensor(features.canput, dtype=torch.long),
        "surround_black": torch.tensor(features.surround_black, dtype=torch.long),
        "surround_white": torch.tensor(features.surround_white, dtype=torch.long),
    }
    if target is not None:
        record["target"] = torch.tensor(target, dtype=torch.float64)
    return record


class PatternMLP(nn.Module):
    def __init__(self, pattern_index: int, pattern_size: int, dtype: torch.dtype):
        super().__init__()
        self.pattern_index = pattern_index
        self.pattern_size = pattern_size
        self.dense0 = nn.Linear(pattern_size * 2, N_DENSE0, dtype=dtype)
        self.dense1 = nn.Linear(N_DENSE0, N_DENSE1, dtype=dtype)
        self.dense2 = nn.Linear(N_DENSE1, 1, dtype=dtype)
        self.register_buffer(
            "divisors",
            torch.tensor([POW3[pattern_size - 1 - i] for i in range(pattern_size)], dtype=torch.long),
            persistent=False,
        )
        self.register_buffer(
            "reverse_order",
            torch.tensor(REVERSE_ORDERS[pattern_index], dtype=torch.long),
            persistent=False,
        )

    def _inputs(self, digits: Tensor) -> Tensor:
        dtype = self.dense0.weight.dtype
        return torch.cat((digits == 0, digits == 1), dim=-1).to(dtype=dtype)

    def _network(self, values: Tensor) -> Tensor:
        values = torch.nn.functional.leaky_relu(self.dense0(values), negative_slope=0.01)
        values = torch.nn.functional.leaky_relu(self.dense1(values), negative_slope=0.01)
        values = torch.nn.functional.leaky_relu(self.dense2(values), negative_slope=0.01)
        return values.squeeze(-1)

    def forward(self, indices: Tensor) -> Tensor:
        digits = torch.remainder(
            torch.div(indices.unsqueeze(-1), self.divisors, rounding_mode="floor"), 3,
        )
        direct = self._network(self._inputs(digits))
        reverse = self._network(self._inputs(digits.index_select(-1, self.reverse_order)))
        return direct + reverse


class AddMLP(nn.Module):
    def __init__(self, dtype: torch.dtype):
        super().__init__()
        self.dense0 = nn.Linear(3, N_ADD_DENSE0, dtype=dtype)
        self.dense1 = nn.Linear(N_ADD_DENSE0, N_ADD_DENSE1, dtype=dtype)

    def forward(self, canput: Tensor, surround_black: Tensor, surround_white: Tensor) -> Tensor:
        dtype = self.dense0.weight.dtype
        inputs = torch.stack((
            canput.to(dtype=dtype) / 30.0,
            (surround_black.to(dtype=dtype) - 15.0) / 15.0,
            (surround_white.to(dtype=dtype) - 15.0) / 15.0,
        ), dim=-1)
        hidden = torch.nn.functional.leaky_relu(self.dense0(inputs), negative_slope=0.01)
        return torch.nn.functional.leaky_relu(self.dense1(hidden), negative_slope=0.01)


class JavaCompatibleEvaluator(nn.Module):
    """The trainable 4-phase/11-pattern width-48 evaluator."""

    def __init__(self, dtype: torch.dtype = torch.float64):
        super().__init__()
        self.patterns = nn.ModuleList([
            nn.ModuleList([
                PatternMLP(pattern_index, pattern_size, dtype)
                for pattern_index, pattern_size in enumerate(PATTERN_SIZES)
            ])
            for _ in range(N_PHASES)
        ])
        self.add_networks = nn.ModuleList(AddMLP(dtype) for _ in range(N_PHASES))
        self.all_dense = nn.Parameter(torch.empty((N_PHASES, 19), dtype=dtype))
        self.all_bias = nn.Parameter(torch.empty((N_PHASES,), dtype=dtype))

    @property
    def parameter_dtype(self) -> torch.dtype:
        return self.all_dense.dtype

    def _forward_phase(self, phase: int, batch: dict[str, Tensor]) -> Tensor:
        indices = batch["pattern_indices"]
        groups: list[Tensor] = []
        for pattern_index, network in enumerate(self.patterns[phase]):
            start = PATTERN_OFFSETS[pattern_index]
            end = PATTERN_OFFSETS[pattern_index + 1]
            groups.append(network(indices[:, start:end]).sum(dim=1))
        additions = self.add_networks[phase](
            batch["canput"], batch["surround_black"], batch["surround_white"],
        )
        all_inputs = torch.cat((torch.stack(groups, dim=1), additions), dim=1)
        return (all_inputs * self.all_dense[phase]).sum(dim=1) + self.all_bias[phase]

    def forward(self, batch: dict[str, Tensor]) -> Tensor:
        batch_size = batch["phase"].shape[0]
        result = torch.empty(batch_size, dtype=self.parameter_dtype, device=batch["phase"].device)
        for phase in range(N_PHASES):
            mask = batch["phase"] == phase
            if not bool(mask.any()):
                continue
            subset = {key: value[mask] for key, value in batch.items() if key != "target"}
            result[mask] = self._forward_phase(phase, subset)
        return torch.where(batch["player"] != 0, -result, result)

    def load_java_parameters(self, parameter_path: str | Path) -> None:
        reference = ReferenceEvaluator(parameter_path)
        with torch.no_grad():
            for phase in range(N_PHASES):
                for pattern_index in range(len(PATTERN_SIZES)):
                    source = reference.patterns[phase][pattern_index]
                    target = self.patterns[phase][pattern_index]
                    target.dense0.weight.copy_(torch.tensor(source.dense0, dtype=self.parameter_dtype))
                    target.dense0.bias.copy_(torch.tensor(source.bias0, dtype=self.parameter_dtype))
                    target.dense1.weight.copy_(torch.tensor(source.dense1, dtype=self.parameter_dtype))
                    target.dense1.bias.copy_(torch.tensor(source.bias1, dtype=self.parameter_dtype))
                    target.dense2.weight.copy_(torch.tensor([source.dense2], dtype=self.parameter_dtype))
                    target.dense2.bias.copy_(torch.tensor([source.bias2], dtype=self.parameter_dtype))

                source_add = reference.add_networks[phase]
                target_add = self.add_networks[phase]
                target_add.dense0.weight.copy_(torch.tensor(source_add.dense0, dtype=self.parameter_dtype))
                target_add.dense0.bias.copy_(torch.tensor(source_add.bias0, dtype=self.parameter_dtype))
                target_add.dense1.weight.copy_(torch.tensor(source_add.dense1, dtype=self.parameter_dtype))
                target_add.dense1.bias.copy_(torch.tensor(source_add.bias1, dtype=self.parameter_dtype))
                self.all_dense[phase].copy_(torch.tensor(reference.all_dense[phase], dtype=self.parameter_dtype))
                self.all_bias[phase].copy_(torch.tensor(reference.all_bias[phase], dtype=self.parameter_dtype))


def model_parameter_values(model: JavaCompatibleEvaluator) -> list[float]:
    """Flatten a model in the Java reader's input-major order."""

    values: list[float] = []
    for phase in range(N_PHASES):
        for pattern_index, pattern_size in enumerate(PATTERN_SIZES):
            network = model.patterns[phase][pattern_index]
            weight0 = network.dense0.weight.detach().cpu()
            for input_index in range(pattern_size * 2):
                for unit in range(N_DENSE0):
                    values.append(float(weight0[unit, input_index]))
            values.extend(float(value) for value in network.dense0.bias.detach().cpu())

            weight1 = network.dense1.weight.detach().cpu()
            for previous in range(N_DENSE0):
                for unit in range(N_DENSE1):
                    values.append(float(weight1[unit, previous]))
            values.extend(float(value) for value in network.dense1.bias.detach().cpu())
            values.extend(float(value) for value in network.dense2.weight.detach().cpu()[0])
            values.append(float(network.dense2.bias.detach().cpu()[0]))

        add = model.add_networks[phase]
        add_weight0 = add.dense0.weight.detach().cpu()
        for input_index in range(3):
            for unit in range(N_ADD_DENSE0):
                values.append(float(add_weight0[unit, input_index]))
        values.extend(float(value) for value in add.dense0.bias.detach().cpu())
        add_weight1 = add.dense1.weight.detach().cpu()
        for previous in range(N_ADD_DENSE0):
            for unit in range(N_ADD_DENSE1):
                values.append(float(add_weight1[unit, previous]))
        values.extend(float(value) for value in add.dense1.bias.detach().cpu())
        values.extend(float(value) for value in model.all_dense.detach().cpu()[phase])
        values.append(float(model.all_bias.detach().cpu()[phase]))

    if len(values) != EXPECTED_PARAMETER_COUNT:
        raise AssertionError(
            f"export produced {len(values)} values, expected {EXPECTED_PARAMETER_COUNT}"
        )
    return values


def read_parameter_values(path: str | Path) -> list[float]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if len(lines) != EXPECTED_PARAMETER_COUNT:
        raise ValueError(
            f"parameter count mismatch in {path}: expected {EXPECTED_PARAMETER_COUNT}, got {len(lines)}"
        )
    values = [float(line) for line in lines]
    non_finite = [index + 1 for index, value in enumerate(values) if not math.isfinite(value)]
    if non_finite:
        raise ValueError(f"non-finite parameters in {path}, first lines: {non_finite[:8]}")
    return values


def export_java_parameters(
    model: JavaCompatibleEvaluator,
    output_path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    output = Path(output_path)
    if output.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing parameter file: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    values = model_parameter_values(model)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("model contains NaN or infinite parameters; export aborted")

    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text("".join(f"{value:.17g}\n" for value in values), encoding="utf-8")
    verified = read_parameter_values(temporary)
    if len(verified) != EXPECTED_PARAMETER_COUNT:
        raise AssertionError("temporary parameter verification failed")
    temporary.replace(output)
    # Exercise the Phase 5 parser as a final format/order guard.
    ReferenceEvaluator(output)
    return output
