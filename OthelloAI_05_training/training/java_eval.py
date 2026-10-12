"""Pure-Python reproduction of ``OthelloAI_05.evaluate``.

The implementation deliberately follows the Java loop and accumulation order.
It uses only the Python standard library and reads the existing ``param.txt``
without converting or rewriting it.  Pattern tables are evaluated lazily and
cached; the value is the same as Java's eager ``pre_evaluation`` expansion.

Board symbols are the symbols used by the Java stdin protocol:

* ``0``: black
* ``1``: white
* ``.``: empty

The public ``Evaluator.evaluate`` result is the exact Java integer score after
clamping to [-1, 1], multiplying by 6400, and truncating toward zero.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Sequence


HW = 8
N_LINE = 3**8
N_PHASES = 4
N_PATTERNS = 11
N_DENSE0 = 16
N_DENSE1 = 16
N_ADD_INPUT = 3
N_ADD_DENSE0 = 8
N_ADD_DENSE1 = 8
N_ALL_INPUT = 19
MAX_CANPUT = 30
MAX_SURROUND = 50
SCORE_WEIGHT = 6400
PATTERN_SIZES = (8, 8, 8, 5, 6, 7, 8, 10, 10, 10, 10)
EXPECTED_PARAMETER_COUNT = 25_436
POW3 = tuple(3**i for i in range(11))


# The order is part of the evaluator: 8 rows, 8 columns, 11 diagonals in each
# direction.  Short diagonals are padded with ternary digit 2 by encode_board.
GLOBAL_PLACE: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3, 4, 5, 6, 7),
    (8, 9, 10, 11, 12, 13, 14, 15),
    (16, 17, 18, 19, 20, 21, 22, 23),
    (24, 25, 26, 27, 28, 29, 30, 31),
    (32, 33, 34, 35, 36, 37, 38, 39),
    (40, 41, 42, 43, 44, 45, 46, 47),
    (48, 49, 50, 51, 52, 53, 54, 55),
    (56, 57, 58, 59, 60, 61, 62, 63),
    (0, 8, 16, 24, 32, 40, 48, 56),
    (1, 9, 17, 25, 33, 41, 49, 57),
    (2, 10, 18, 26, 34, 42, 50, 58),
    (3, 11, 19, 27, 35, 43, 51, 59),
    (4, 12, 20, 28, 36, 44, 52, 60),
    (5, 13, 21, 29, 37, 45, 53, 61),
    (6, 14, 22, 30, 38, 46, 54, 62),
    (7, 15, 23, 31, 39, 47, 55, 63),
    (5, 14, 23),
    (4, 13, 22, 31),
    (3, 12, 21, 30, 39),
    (2, 11, 20, 29, 38, 47),
    (1, 10, 19, 28, 37, 46, 55),
    (0, 9, 18, 27, 36, 45, 54, 63),
    (8, 17, 26, 35, 44, 53, 62),
    (16, 25, 34, 43, 52, 61),
    (24, 33, 42, 51, 60),
    (32, 41, 50, 59),
    (40, 49, 58),
    (2, 9, 16),
    (3, 10, 17, 24),
    (4, 11, 18, 25, 32),
    (5, 12, 19, 26, 33, 40),
    (6, 13, 20, 27, 34, 41, 48),
    (7, 14, 21, 28, 35, 42, 49, 56),
    (15, 22, 29, 36, 43, 50, 57),
    (23, 30, 37, 44, 51, 58),
    (31, 38, 45, 52, 59),
    (39, 46, 53, 60),
    (47, 54, 61),
)


def _leaky_relu(value: float) -> float:
    # Java: Math.max(0.01 * x, x)
    return max(0.01 * value, value)


def _ternary_digit(index: int, place: int) -> int:
    """Return Java ``pop_digit[index][place]`` (place 0 is the MS trit)."""

    return (index // POW3[7 - place]) % 3


def _pop_mid(index: int, high: int, low: int) -> int:
    """Return Java ``pop_mid[index][high][low]``."""

    return (index % POW3[high]) // POW3[low]


def _reverse_line(index: int) -> int:
    result = 0
    value = index
    for _ in range(HW):
        result = result * 3 + value % 3
        value //= 3
    return result


REVERSE_LINE = tuple(_reverse_line(index) for index in range(N_LINE))


def _move_line_half(player_bits: int, opponent_bits: int, place: int, side: int) -> int:
    result = 0
    point = 1 << (7 - place)
    if point & (player_bits | opponent_bits):
        return 0
    mask = point << 1 if side == 0 else point >> 1
    while mask != 0 and mask & opponent_bits:
        result += 1
        mask = mask << 1 if side == 0 else mask >> 1
        if mask & player_bits:
            return result
    return 0


def _make_line_feature_tables() -> tuple[tuple[tuple[int, ...], tuple[int, ...]], tuple[tuple[int, ...], tuple[int, ...]]]:
    canput = [[0] * N_LINE for _ in range(2)]
    surround = [[0] * N_LINE for _ in range(2)]
    for index in range(N_LINE):
        black = 0
        white = 0
        value = index
        for bit in range(HW):
            digit = value % 3
            if digit == 0:
                black |= 1 << bit
            elif digit == 1:
                white |= 1 << bit
            value //= 3

        for place in range(HW):
            bit = 1 << place
            if place > 0 and not ((black | white) & (1 << (place - 1))):
                if black & bit:
                    surround[0][index] += 1
                elif white & bit:
                    surround[1][index] += 1
            if place < 7 and not ((black | white) & (1 << (place + 1))):
                if black & bit:
                    surround[0][index] += 1
                elif white & bit:
                    surround[1][index] += 1

        for place in range(HW):
            if (_move_line_half(black, white, place, 0) != 0 or
                    _move_line_half(black, white, place, 1) != 0):
                canput[0][index] += 1
            if (_move_line_half(white, black, place, 0) != 0 or
                    _move_line_half(white, black, place, 1) != 0):
                canput[1][index] += 1

    return (
        (tuple(canput[0]), tuple(canput[1])),
        (tuple(surround[0]), tuple(surround[1])),
    )


(CANPUT_TABLE, SURROUND_TABLE) = _make_line_feature_tables()


@dataclass(frozen=True)
class EncodedBoard:
    """The Java board's 38 ternary lines plus metadata."""

    lines: tuple[int, ...]
    stone_count: int
    player: int


@dataclass(frozen=True)
class EvaluationDetails:
    value: int
    raw_value: float
    phase: int
    canput: int
    surround_black: int
    surround_white: int


@dataclass
class PatternNetwork:
    pattern_index: int
    pattern_size: int
    dense0: tuple[tuple[float, ...], ...]
    bias0: tuple[float, ...]
    dense1: tuple[tuple[float, ...], ...]
    bias1: tuple[float, ...]
    dense2: tuple[float, ...]
    bias2: float
    _value_cache: dict[int, float] = field(default_factory=dict, init=False, repr=False)

    def _predict(self, index: int) -> float:
        inputs = [0.0] * (self.pattern_size * 2)
        for place in range(self.pattern_size):
            digit = (index // POW3[self.pattern_size - 1 - place]) % 3
            if digit == 0:
                inputs[place] = 1.0
            elif digit == 1:
                inputs[self.pattern_size + place] = 1.0

        hidden0 = [0.0] * N_DENSE0
        for unit in range(N_DENSE0):
            value = self.bias0[unit]
            weights = self.dense0[unit]
            for input_index in range(self.pattern_size * 2):
                value += inputs[input_index] * weights[input_index]
            hidden0[unit] = _leaky_relu(value)

        result = self.bias2
        for unit in range(N_DENSE1):
            value = self.bias1[unit]
            weights = self.dense1[unit]
            for previous in range(N_DENSE0):
                value += hidden0[previous] * weights[previous]
            value = _leaky_relu(value)
            result += value * self.dense2[unit]
        return _leaky_relu(result)

    def _reverse_index(self, index: int) -> int:
        digits = tuple(
            (index // POW3[self.pattern_size - 1 - place]) % 3
            for place in range(self.pattern_size)
        )
        if self.pattern_index <= 7:
            order = tuple(range(self.pattern_size - 1, -1, -1))
        elif self.pattern_index == 8:
            order = (0, 4, 7, 9, 1, 5, 8, 2, 6, 3)
        elif self.pattern_index == 9:
            order = (5, 4, 3, 2, 1, 0, 9, 8, 7, 6)
        else:
            order = (0, 1, 2, 3, 7, 8, 9, 4, 5, 6)

        result = 0
        for source in order:
            result = result * 3 + digits[source]
        return result

    def value(self, index: int) -> float:
        try:
            return self._value_cache[index]
        except KeyError:
            # calc_rev_idx is an involution for all eleven Java patterns, so
            # tmp_pattern_arr[index] is predict(calc_rev_idx(index)).
            result = self._predict(index) + self._predict(self._reverse_index(index))
            self._value_cache[index] = result
            return result


@dataclass(frozen=True)
class AddNetwork:
    dense0: tuple[tuple[float, ...], ...]
    bias0: tuple[float, ...]
    dense1: tuple[tuple[float, ...], ...]
    bias1: tuple[float, ...]

    def predict(self, canput: int, surround_black: int, surround_white: int) -> tuple[float, ...]:
        inputs = (
            canput / 30.0,
            (surround_black - 15.0) / 15.0,
            (surround_white - 15.0) / 15.0,
        )
        hidden0 = [0.0] * N_ADD_DENSE0
        for unit in range(N_ADD_DENSE0):
            value = self.bias0[unit]
            for input_index in range(N_ADD_INPUT):
                value += inputs[input_index] * self.dense0[unit][input_index]
            hidden0[unit] = _leaky_relu(value)

        result = [0.0] * N_ADD_DENSE1
        for unit in range(N_ADD_DENSE1):
            value = self.bias1[unit]
            for previous in range(N_ADD_DENSE0):
                value += hidden0[previous] * self.dense1[unit][previous]
            result[unit] = _leaky_relu(value)
        return tuple(result)


def _normalise_board(board: str | Sequence[str]) -> str:
    if isinstance(board, str):
        compact = "".join(character for character in board if not character.isspace())
    else:
        compact = "".join(str(row).strip() for row in board)
    if len(compact) != 64:
        raise ValueError(f"board must contain exactly 64 cells, got {len(compact)}")
    invalid = sorted(set(compact) - {"0", "1", "."})
    if invalid:
        raise ValueError(f"board contains invalid symbols: {''.join(invalid)!r}")
    return compact


def encode_board(board: str | Sequence[str], player: int) -> EncodedBoard:
    if player not in (0, 1):
        raise ValueError(f"player must be 0 or 1, got {player}")
    cells = _normalise_board(board)
    lines: list[int] = []
    for places in GLOBAL_PLACE:
        index = N_LINE - 1
        for local_place, global_place in enumerate(places):
            cell = cells[global_place]
            if cell == "0":
                index -= POW3[7 - local_place] * 2
            elif cell == "1":
                index -= POW3[7 - local_place]
        lines.append(index)
    return EncodedBoard(tuple(lines), 64 - cells.count("."), player)


class _ParameterReader:
    def __init__(self, path: Path):
        try:
            raw_lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise ValueError(f"cannot read parameter file {path}: {error}") from error
        if len(raw_lines) != EXPECTED_PARAMETER_COUNT:
            raise ValueError(
                f"parameter count mismatch: expected {EXPECTED_PARAMETER_COUNT}, "
                f"got {len(raw_lines)} in {path}"
            )
        self.values: list[float] = []
        for line_number, raw in enumerate(raw_lines, 1):
            try:
                self.values.append(float(raw))
            except ValueError as error:
                raise ValueError(f"invalid parameter at {path}:{line_number}: {raw!r}") from error
        self.position = 0

    def one(self) -> float:
        value = self.values[self.position]
        self.position += 1
        return value

    def matrix_input_major(self, units: int, inputs: int) -> tuple[tuple[float, ...], ...]:
        matrix = [[0.0] * inputs for _ in range(units)]
        for input_index in range(inputs):
            for unit in range(units):
                matrix[unit][input_index] = self.one()
        return tuple(tuple(row) for row in matrix)

    def vector(self, size: int) -> tuple[float, ...]:
        return tuple(self.one() for _ in range(size))


class Evaluator:
    """Evaluator loaded from the original Java ``param.txt`` format."""

    def __init__(self, parameter_path: str | Path):
        self.parameter_path = Path(parameter_path)
        reader = _ParameterReader(self.parameter_path)
        phase_patterns: list[tuple[PatternNetwork, ...]] = []
        add_networks: list[AddNetwork] = []
        all_dense: list[tuple[float, ...]] = []
        all_bias: list[float] = []

        for _phase in range(N_PHASES):
            patterns: list[PatternNetwork] = []
            for pattern_index, pattern_size in enumerate(PATTERN_SIZES):
                dense0 = reader.matrix_input_major(N_DENSE0, pattern_size * 2)
                bias0 = reader.vector(N_DENSE0)
                dense1 = reader.matrix_input_major(N_DENSE1, N_DENSE0)
                bias1 = reader.vector(N_DENSE1)
                dense2 = reader.vector(N_DENSE1)
                bias2 = reader.one()
                patterns.append(PatternNetwork(
                    pattern_index, pattern_size, dense0, bias0,
                    dense1, bias1, dense2, bias2,
                ))
            phase_patterns.append(tuple(patterns))

            add_dense0 = reader.matrix_input_major(N_ADD_DENSE0, N_ADD_INPUT)
            add_bias0 = reader.vector(N_ADD_DENSE0)
            add_dense1 = reader.matrix_input_major(N_ADD_DENSE1, N_ADD_DENSE0)
            add_bias1 = reader.vector(N_ADD_DENSE1)
            add_networks.append(AddNetwork(add_dense0, add_bias0, add_dense1, add_bias1))
            all_dense.append(reader.vector(N_ALL_INPUT))
            all_bias.append(reader.one())

        if reader.position != EXPECTED_PARAMETER_COUNT:
            raise AssertionError(
                f"internal parameter parser error: consumed {reader.position}, "
                f"expected {EXPECTED_PARAMETER_COUNT}"
            )
        self.patterns = tuple(phase_patterns)
        self.add_networks = tuple(add_networks)
        self.all_dense = tuple(all_dense)
        self.all_bias = tuple(all_bias)

    @staticmethod
    def phase_index(stone_count: int) -> int:
        if not 4 <= stone_count <= 64:
            raise ValueError(f"stone count must be in [4, 64], got {stone_count}")
        return max(0, min(3, (stone_count - 4) // 10 - 2))

    @staticmethod
    def _sfill(line: int, digit_place: int, power: int) -> int:
        return line - POW3[power] + 1 if _ternary_digit(line, digit_place) != 2 else line

    @staticmethod
    def _canput(lines: tuple[int, ...], player: int) -> int:
        table = CANPUT_TABLE[player]
        total = 0
        for line in lines[:16]:
            total += table[line]
        for index in (16, 26, 27, 37):
            total += table[lines[index] - POW3[5] + 1]
        for index in (17, 25, 28, 36):
            total += table[lines[index] - POW3[4] + 1]
        for index in (18, 24, 29, 35):
            total += table[lines[index] - POW3[3] + 1]
        for index in (19, 23, 30, 34):
            total += table[lines[index] - POW3[2] + 1]
        for index in (20, 22, 31, 33):
            total += table[lines[index] - POW3[1] + 1]
        total += table[lines[21]]
        total += table[lines[32]]
        return -total if player != 0 else total

    @classmethod
    def _surround(cls, lines: tuple[int, ...], player: int) -> int:
        table = SURROUND_TABLE[player]
        total = 0
        for line in lines[:16]:
            total += table[line]
        for index in (16, 26, 27, 37):
            total += table[cls._sfill(lines[index], 2, 5)]
        for index in (17, 25, 28, 36):
            total += table[cls._sfill(lines[index], 3, 4)]
        for index in (18, 24, 29, 35):
            total += table[cls._sfill(lines[index], 4, 3)]
        for index in (19, 23, 30, 34):
            total += table[cls._sfill(lines[index], 5, 2)]
        for index in (20, 22, 31, 33):
            total += table[cls._sfill(lines[index], 6, 1)]
        total += table[lines[21]]
        total += table[lines[32]]
        return total

    def _pattern_value(self, phase: int, pattern: int, index: int) -> float:
        return self.patterns[phase][pattern].value(index)

    def _edge_2x(self, phase: int, lines: tuple[int, ...], x: int, y: int) -> float:
        index = _ternary_digit(lines[x], 1) * POW3[9]
        index += lines[y] * POW3[1]
        index += _ternary_digit(lines[x], 6)
        return self._pattern_value(phase, 7, index)

    def _triangle0(self, phase: int, lines: tuple[int, ...], w: int, x: int, y: int, z: int) -> float:
        index = (lines[w] // POW3[4]) * POW3[6]
        index += (lines[x] // POW3[5]) * POW3[3]
        index += (lines[y] // POW3[6]) * POW3[1]
        index += lines[z] // POW3[7]
        return self._pattern_value(phase, 8, index)

    def _triangle1(self, phase: int, lines: tuple[int, ...], w: int, x: int, y: int, z: int) -> float:
        index = (REVERSE_LINE[lines[w]] // POW3[4]) * POW3[6]
        index += (REVERSE_LINE[lines[x]] // POW3[5]) * POW3[3]
        index += (REVERSE_LINE[lines[y]] // POW3[6]) * POW3[1]
        index += REVERSE_LINE[lines[z]] // POW3[7]
        return self._pattern_value(phase, 8, index)

    def _edge_block(self, phase: int, lines: tuple[int, ...], x: int, y: int) -> float:
        index = _ternary_digit(lines[x], 0) * POW3[9]
        index += _pop_mid(lines[x], 6, 2) * POW3[5]
        index += _ternary_digit(lines[x], 7) * POW3[4]
        index += _pop_mid(lines[y], 6, 2)
        return self._pattern_value(phase, 9, index)

    def _cross(self, phase: int, lines: tuple[int, ...], x: int, y: int, z: int) -> float:
        index0 = (lines[x] // POW3[4]) * POW3[6]
        index0 += (lines[y] // POW3[5]) * POW3[3]
        index0 += lines[z] // POW3[5]
        result = self._pattern_value(phase, 10, index0)

        reverse_x = REVERSE_LINE[lines[x]]
        reverse_y = REVERSE_LINE[lines[y]]
        reverse_z = REVERSE_LINE[lines[z]]
        index1 = (reverse_x // POW3[4]) * POW3[6]
        index1 += _pop_mid(reverse_y, 7, 4) * POW3[3]
        index1 += _pop_mid(reverse_z, 7, 4)
        result += self._pattern_value(phase, 10, index1)
        return result

    def _calc_pattern(self, phase: int, lines: tuple[int, ...]) -> float:
        dense = self.all_dense[phase]
        pv = self._pattern_value

        group = pv(phase, 0, lines[1]) + pv(phase, 0, lines[6])
        group += pv(phase, 0, lines[9])
        group += pv(phase, 0, lines[14])
        result = dense[0] * group

        group = pv(phase, 1, lines[2]) + pv(phase, 1, lines[5])
        group += pv(phase, 1, lines[10])
        group += pv(phase, 1, lines[13])
        result += dense[1] * group

        group = pv(phase, 2, lines[3]) + pv(phase, 2, lines[4])
        group += pv(phase, 2, lines[11])
        group += pv(phase, 2, lines[12])
        result += dense[2] * group

        group = pv(phase, 3, lines[18] // POW3[3]) + pv(phase, 3, lines[24] // POW3[3])
        group += pv(phase, 3, lines[29] // POW3[3])
        group += pv(phase, 3, lines[35] // POW3[3])
        result += dense[3] * group

        group = pv(phase, 4, lines[19] // POW3[2]) + pv(phase, 4, lines[23] // POW3[2])
        group += pv(phase, 4, lines[30] // POW3[2])
        group += pv(phase, 4, lines[34] // POW3[2])
        result += dense[4] * group

        group = pv(phase, 5, lines[20] // POW3[1]) + pv(phase, 5, lines[22] // POW3[1])
        group += pv(phase, 5, lines[31] // POW3[1])
        group += pv(phase, 5, lines[33] // POW3[1])
        result += dense[5] * group

        group = pv(phase, 6, lines[21]) + pv(phase, 6, lines[32])
        result += dense[6] * group

        group = self._edge_2x(phase, lines, 1, 0) + self._edge_2x(phase, lines, 6, 7)
        group += self._edge_2x(phase, lines, 9, 8)
        group += self._edge_2x(phase, lines, 14, 15)
        result += dense[7] * group

        group = self._triangle0(phase, lines, 0, 1, 2, 3)
        group += self._triangle0(phase, lines, 7, 6, 5, 4)
        group += self._triangle0(phase, lines, 15, 14, 13, 12)
        group += self._triangle1(phase, lines, 15, 14, 13, 12)
        result += dense[8] * group

        group = self._edge_block(phase, lines, 0, 1) + self._edge_block(phase, lines, 7, 6)
        group += self._edge_block(phase, lines, 8, 9)
        group += self._edge_block(phase, lines, 15, 14)
        result += dense[9] * group

        group = self._cross(phase, lines, 21, 20, 22)
        group += self._cross(phase, lines, 32, 31, 33)
        result += dense[10] * group
        return result

    def evaluate_encoded(self, board: EncodedBoard) -> EvaluationDetails:
        phase = self.phase_index(board.stone_count)
        canput = max(-MAX_CANPUT, min(MAX_CANPUT, self._canput(board.lines, board.player)))
        surround_black = min(MAX_SURROUND, self._surround(board.lines, 0))
        surround_white = min(MAX_SURROUND, self._surround(board.lines, 1))
        add_values = self.add_networks[phase].predict(canput, surround_black, surround_white)

        dense = self.all_dense[phase]
        raw = self.all_bias[phase] + self._calc_pattern(phase, board.lines)
        raw += dense[11] * add_values[0]
        raw += dense[12] * add_values[1]
        raw += dense[13] * add_values[2]
        raw += dense[14] * add_values[3]
        raw += dense[15] * add_values[4]
        raw += dense[16] * add_values[5]
        raw += dense[17] * add_values[6]
        raw += dense[18] * add_values[7]
        if board.player != 0:
            raw = -raw
        raw = max(-1.0, min(1.0, raw))
        # int(float) truncates toward zero, matching Java's double-to-int cast.
        value = int(raw * SCORE_WEIGHT)
        return EvaluationDetails(
            value, raw, phase, canput, surround_black, surround_white,
        )

    def evaluate_details(self, board: str | Sequence[str], player: int) -> EvaluationDetails:
        return self.evaluate_encoded(encode_board(board, player))

    def evaluate(self, board: str | Sequence[str], player: int) -> int:
        return self.evaluate_details(board, player).value


def _default_parameter_path() -> Path:
    return Path(__file__).resolve().parents[1] / "resources" / "param.txt"


def _read_board_from_stdin() -> list[str]:
    rows = []
    while len(rows) < HW:
        line = sys.stdin.readline()
        if not line:
            break
        if line.strip():
            rows.append(line.strip())
    if len(rows) != HW:
        raise ValueError(f"expected 8 non-empty board rows on stdin, got {len(rows)}")
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--param", type=Path, default=_default_parameter_path())
    parser.add_argument("--player", type=int, choices=(0, 1), required=True)
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args(argv)
    evaluator = Evaluator(args.param)
    details = evaluator.evaluate_details(_read_board_from_stdin(), args.player)
    if args.details:
        print(
            f"value={details.value} raw={details.raw_value:.17g} "
            f"phase={details.phase} canput={details.canput} "
            f"surround_black={details.surround_black} "
            f"surround_white={details.surround_white}"
        )
    else:
        print(details.value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
