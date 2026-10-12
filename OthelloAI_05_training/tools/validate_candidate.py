#!/usr/bin/env python3
'''Mechanically gate an evaluator parameter candidate before A/B games.'''

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import heapq
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterable, Iterator, Sequence
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'training'))

from java_eval import EXPECTED_PARAMETER_COUNT, Evaluator  # noqa: E402


@dataclass(frozen=True)
class Position:
    board: str
    target_disc: float
    phase: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parameter_check(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding='utf-8').splitlines()
    bad: list[int] = []
    for number, raw in enumerate(lines, 1):
        try:
            value = float(raw)
        except ValueError:
            bad.append(number)
            continue
        if not math.isfinite(value):
            bad.append(number)
    return {
        'path': str(path.resolve()), 'sha256': sha256(path),
        'count': len(lines), 'expected_count': EXPECTED_PARAMETER_COUNT,
        'all_finite': not bad, 'bad_lines': bad[:16],
        'pass': len(lines) == EXPECTED_PARAMETER_COUNT and not bad,
    }


def rotate90(board: str) -> str:
    return ''.join(board[(7 - x) * 8 + y] for y in range(8) for x in range(8))


def mirror(board: str) -> str:
    return ''.join(board[y * 8 + 7 - x] for y in range(8) for x in range(8))


def d4_variants(board: str) -> tuple[str, ...]:
    result: list[str] = []
    rotated = board
    for _ in range(4):
        result.extend((rotated, mirror(rotated)))
        rotated = rotate90(rotated)
    return tuple(result)


def canonical_d4(board: str) -> str:
    return min(d4_variants(board))


def board_hash(board: str, seed: int, person: bytes = b'oth-eval') -> int:
    digest = hashlib.blake2b(digest_size=8, person=person)
    digest.update(str(seed).encode('ascii'))
    digest.update(b'\0')
    digest.update(canonical_d4(board).encode('ascii'))
    return int.from_bytes(digest.digest(), 'big')


def split_for_board(board: str, config: dict[str, Any]) -> str:
    ratios = config['ratios']
    fraction = board_hash(board, int(config['seed'])) / float(1 << 64)
    if fraction < float(ratios['train']):
        return 'train'
    if fraction < float(ratios['train']) + float(ratios['val']):
        return 'val'
    return 'test'


def phase_for_board(board: str) -> int:
    stones = 64 - board.count('-')
    return max(0, min(3, (stones - 4) // 10 - 2))


def parse_record(raw: str, source: str, line_number: int) -> Position | None:
    stripped = raw.strip()
    if not stripped:
        return None
    fields = stripped.split()
    if len(fields) != 2:
        raise ValueError(f'{source}:{line_number}: expected board and score')
    board, score_text = fields
    if len(board) != 64 or set(board) - {'X', 'O', '-'}:
        raise ValueError(f'{source}:{line_number}: invalid 64-cell board')
    try:
        score = float(score_text)
    except ValueError as error:
        raise ValueError(f'{source}:{line_number}: invalid score') from error
    stones = 64 - board.count('-')
    if not 4 <= stones <= 64 or not math.isfinite(score) or not -64 <= score <= 64:
        raise ValueError(f'{source}:{line_number}: invalid stones or score')
    return Position(board, score, phase_for_board(board))


def _records_from_lines(lines: Iterable[str], source: str) -> Iterator[Position]:
    for number, raw in enumerate(lines, 1):
        record = parse_record(raw, source, number)
        if record is not None:
            yield record


def iter_records(path: Path) -> Iterator[Position]:
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            names = sorted(name for name in archive.namelist() if name.lower().endswith('.txt'))
            if not names:
                raise ValueError(f'{path}: ZIP contains no text members')
            for name in names:
                with archive.open(name) as binary:
                    lines = (raw.decode('utf-8') for raw in binary)
                    yield from _records_from_lines(lines, f'{path}!/{name}')
    elif path.suffix.lower() == '.gz':
        with gzip.open(path, 'rt', encoding='utf-8') as source:
            yield from _records_from_lines(source, str(path))
    else:
        with path.open('r', encoding='utf-8') as source:
            yield from _records_from_lines(source, str(path))


def _phase_limit(raw: int | dict[str, int], phase: int) -> int:
    return int(raw[str(phase)]) if isinstance(raw, dict) else int(raw)


def select_samples(
    paths: Sequence[Path], config: dict[str, Any]
) -> tuple[dict[int, list[Position]], dict[str, Any]]:
    heaps: dict[int, list[tuple[int, int, Position]]] = {phase: [] for phase in range(4)}
    scanned: Counter[int] = Counter()
    eligible: Counter[int] = Counter()
    serial = 0
    maximum = config.get('max_source_records')
    stop = False
    for path in paths:
        if not path.is_file():
            raise ValueError(f'dataset does not exist: {path}')
        for record in iter_records(path):
            serial += 1
            scanned[record.phase] += 1
            if split_for_board(record.board, config['split']) == config['split_name']:
                eligible[record.phase] += 1
                limit = _phase_limit(config['samples_per_phase'], record.phase)
                key = board_hash(record.board, int(config['sample_seed']), b'oth-gate')
                item = (-key, serial, record)
                heap = heaps[record.phase]
                if len(heap) < limit:
                    heapq.heappush(heap, item)
                elif key < -heap[0][0]:
                    heapq.heapreplace(heap, item)
            if maximum and serial >= int(maximum):
                stop = True
                break
        if stop:
            break
    result = {
        phase: [item[2] for item in sorted(heap, key=lambda item: (-item[0], item[1]))]
        for phase, heap in heaps.items()
    }
    missing = {
        phase: (_phase_limit(config['samples_per_phase'], phase), len(result[phase]))
        for phase in range(4)
        if len(result[phase]) != _phase_limit(config['samples_per_phase'], phase)
    }
    if missing:
        raise ValueError(f'insufficient held-out samples by phase: {missing}')
    digest = hashlib.sha256()
    for phase in range(4):
        for record in result[phase]:
            digest.update(f'{phase}\t{record.board}\t{record.target_disc:.17g}\n'.encode('ascii'))
    scan = {
        'source_paths': [str(path.resolve()) for path in paths],
        'records_scanned': serial,
        'records_by_phase': {str(p): scanned[p] for p in range(4)},
        'eligible_by_phase': {str(p): eligible[p] for p in range(4)},
        'selected_by_phase': {str(p): len(result[p]) for p in range(4)},
        'sample_sha256': digest.hexdigest(),
        'truncated': bool(maximum and serial >= int(maximum)),
    }
    return result, scan


def absolute_board(relative: str) -> str:
    return relative.translate(str.maketrans({'X': '0', 'O': '1', '-': '.'}))


def _rmse_result(
    squares: dict[int, float],
    counts: Counter[int],
    phase_weights: dict[int, int],
) -> dict[str, Any]:
    total_count = sum(counts.values())
    phase_mse = {
        phase: squares[phase] / counts[phase] for phase in range(4)
    }
    total_weight = sum(phase_weights.values())
    weighted_mse = sum(
        phase_mse[phase] * phase_weights[phase] for phase in range(4)
    ) / total_weight
    phases = {
        str(phase): {
            'count': counts[phase],
            'rmse_disc': math.sqrt(phase_mse[phase]),
            'population_weight': phase_weights[phase] / total_weight,
        }
        for phase in range(4)
    }
    return {
        'count': total_count,
        'rmse_disc': math.sqrt(weighted_mse),
        'aggregation': 'heldout_population_weighted',
        'phases': phases,
    }


def evaluate_rmse(
    baseline: Evaluator,
    candidate: Evaluator,
    samples: dict[int, list[Position]],
    phase_weights: dict[int, int],
) -> dict[str, Any]:
    base_squares = {phase: 0.0 for phase in range(4)}
    candidate_squares = {phase: 0.0 for phase in range(4)}
    counts: Counter[int] = Counter()
    for phase in range(4):
        for record in samples[phase]:
            board = absolute_board(record.board)
            base_prediction = baseline.evaluate_details(board, 0).raw_value * 64.0
            candidate_prediction = candidate.evaluate_details(board, 0).raw_value * 64.0
            if not math.isfinite(base_prediction) or not math.isfinite(candidate_prediction):
                raise ValueError('evaluator produced a non-finite prediction')
            base_squares[phase] += (base_prediction - record.target_disc) ** 2
            candidate_squares[phase] += (candidate_prediction - record.target_disc) ** 2
            counts[phase] += 1
    return {
        'baseline': _rmse_result(base_squares, counts, phase_weights),
        'candidate': _rmse_result(candidate_squares, counts, phase_weights),
    }


def rmse_gate(metrics: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    baseline = float(metrics['baseline']['rmse_disc'])
    candidate = float(metrics['candidate']['rmse_disc'])
    absolute = baseline - candidate
    relative = absolute / baseline if baseline > 0.0 else None
    absolute_pass = (
        absolute > float(config['minimum_absolute_disc'])
        or math.isclose(
            absolute, float(config['minimum_absolute_disc']),
            rel_tol=1e-12, abs_tol=1e-12,
        )
    )
    relative_pass = relative is not None and (
        relative > float(config['minimum_relative'])
        or math.isclose(
            relative, float(config['minimum_relative']),
            rel_tol=1e-12, abs_tol=1e-12,
        )
    )
    improvement = (
        absolute_pass or relative_pass
    )
    phase = str(int(config.get('endgame_phase', 3)))
    base_end = float(metrics['baseline']['phases'][phase]['rmse_disc'])
    candidate_end = float(metrics['candidate']['phases'][phase]['rmse_disc'])
    endgame = candidate_end <= base_end + float(config.get('endgame_tolerance_disc', 0.0))
    return {
        'pass': improvement and endgame,
        'improvement_pass': improvement,
        'endgame_nonworsening_pass': endgame,
        'absolute_improvement_disc': absolute,
        'relative_improvement': relative,
        'minimum_absolute_disc': float(config['minimum_absolute_disc']),
        'minimum_relative': float(config['minimum_relative']),
        'endgame_phase': int(phase),
        'endgame_change_disc': candidate_end - base_end,
        'endgame_tolerance_disc': float(config.get('endgame_tolerance_disc', 0.0)),
    }


def _span_summary(raw_spans: Sequence[float], integer_spans: Sequence[int]) -> dict[str, Any]:
    return {
        'positions': len(raw_spans),
        'maximum_span_disc': max(raw_spans) if raw_spans else None,
        'mean_span_disc': sum(raw_spans) / len(raw_spans) if raw_spans else None,
        'rms_span_disc': (
            math.sqrt(sum(value * value for value in raw_spans) / len(raw_spans))
            if raw_spans else None
        ),
        'maximum_span_java_units': max(integer_spans) if integer_spans else None,
    }


def direction_stats(
    evaluator: Evaluator,
    samples: dict[int, list[Position]],
    per_phase: int,
) -> dict[str, Any]:
    all_raw: list[float] = []
    all_integer: list[int] = []
    phases: dict[str, Any] = {}
    for phase in range(4):
        raw_spans: list[float] = []
        integer_spans: list[int] = []
        for record in samples[phase][:per_phase]:
            details = [
                evaluator.evaluate_details(absolute_board(board), 0)
                for board in d4_variants(record.board)
            ]
            raw_values = [item.raw_value * 64.0 for item in details]
            integer_values = [item.value for item in details]
            raw_spans.append(max(raw_values) - min(raw_values))
            integer_spans.append(max(integer_values) - min(integer_values))
        phases[str(phase)] = _span_summary(raw_spans, integer_spans)
        all_raw.extend(raw_spans)
        all_integer.extend(integer_spans)
    result = _span_summary(all_raw, all_integer)
    result['phases'] = phases
    return result


def direction_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    candidate_max = float(candidate['maximum_span_disc'])
    baseline_max = float(baseline['maximum_span_disc'])
    limit = config.get('maximum_candidate_span_disc')
    within_limit = limit is None or candidate_max <= float(limit)
    require_nonworsening = bool(config.get('require_nonworsening', False))
    tolerance = float(config.get('nonworsening_tolerance_disc', 0.0))
    nonworsening = candidate_max <= baseline_max + tolerance
    passed = within_limit and (nonworsening or not require_nonworsening)
    return {
        'pass': passed,
        'inspection_completed': True,
        'within_configured_limit': within_limit,
        'nonworsening': nonworsening,
        'require_nonworsening': require_nonworsening,
        'configured_maximum_candidate_span_disc': limit,
        'candidate_minus_baseline_max_span_disc': candidate_max - baseline_max,
        'nonworsening_tolerance_disc': tolerance,
    }


def run_direction_check(
    baseline: Evaluator,
    candidate: Evaluator,
    samples: dict[int, list[Position]],
    config: dict[str, Any],
) -> dict[str, Any]:
    count = int(config['samples_per_phase'])
    if count <= 0 or any(len(samples[phase]) < count for phase in range(4)):
        raise ValueError('D4 sample count must be available in every phase')
    baseline_stats = direction_stats(baseline, samples, count)
    candidate_stats = direction_stats(candidate, samples, count)
    return {
        'baseline': baseline_stats,
        'candidate': candidate_stats,
        'gate': direction_gate(baseline_stats, candidate_stats, config),
    }


def run_parity(candidate: Path, config: dict[str, Any]) -> dict[str, Any]:
    positions = int(config['positions'])
    command = [
        sys.executable, str(PROJECT_ROOT / 'tests' / 'compare_java_eval.py'),
        '--positions', str(positions),
        '--seed', str(int(config['seed'])),
        '--tolerance', str(float(config.get('tolerance', 1e-12))),
        '--param', str(candidate.resolve()),
    ]
    if config.get('java'):
        command.extend(('--java', str(config['java'])))
    if config.get('javac'):
        command.extend(('--javac', str(config['javac'])))
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command, cwd=PROJECT_ROOT, text=True, encoding='utf-8',
            errors='replace', capture_output=True,
            timeout=float(config.get('timeout_seconds', 900)),
        )
        marker = f'PASS: {positions} reachable positions'
        passed = completed.returncode == 0 and marker in completed.stdout
        return {
            'pass': passed, 'positions': positions, 'command': command,
            'returncode': completed.returncode,
            'stdout': completed.stdout[-8000:], 'stderr': completed.stderr[-8000:],
            'duration_seconds': time.monotonic() - started,
        }
    except subprocess.TimeoutExpired as error:
        return {
            'pass': False, 'positions': positions, 'command': command,
            'returncode': None, 'error': f'timeout: {error}',
            'duration_seconds': time.monotonic() - started,
        }


def resolve_project_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def split_contract(heldout: dict[str, Any]) -> dict[str, Any]:
    path = resolve_project_path(heldout['training_config'])
    training = json.loads(path.read_text(encoding='utf-8'))
    actual = training['data']['split']
    expected = heldout['split']
    actual_ratios = {key: float(value) for key, value in actual['ratios'].items()}
    expected_ratios = {key: float(value) for key, value in expected['ratios'].items()}
    passed = (
        heldout.get('split_name') == 'test'
        and int(actual['seed']) == int(expected['seed'])
        and actual_ratios == expected_ratios
        and set(expected_ratios) == {'train', 'val', 'test'}
        and math.isclose(
            sum(expected_ratios.values()), 1.0,
            rel_tol=0.0, abs_tol=1e-12,
        )
    )
    return {
        'pass': passed,
        'training_config': str(path.resolve()),
        'training_split': actual,
        'heldout_split': expected,
    }


def validate(
    candidate_path: Path,
    baseline_path: Path,
    data_paths: Sequence[Path],
    config: dict[str, Any],
) -> dict[str, Any]:
    report: dict[str, Any] = {
        'schema_version': 1,
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'candidate': parameter_check(candidate_path),
        'baseline': parameter_check(baseline_path),
        'config': config,
        'checks': {},
    }
    parameter_pass = bool(report['candidate']['pass'] and report['baseline']['pass'])
    report['checks']['parameters'] = {
        'pass': parameter_pass,
        'required_count': EXPECTED_PARAMETER_COUNT,
        'all_values_must_be_finite': True,
    }
    if not parameter_pass:
        report['decision'] = {
            'pass': False, 'eligible_for_ab': False,
            'failed_checks': ['parameters'],
        }
        return report

    contract = split_contract(config['heldout'])
    report['checks']['heldout_split_contract'] = contract
    if not contract['pass']:
        report['decision'] = {
            'pass': False, 'eligible_for_ab': False,
            'failed_checks': ['heldout_split_contract'],
        }
        return report

    parity_config = config['java_python_parity']
    if int(parity_config['positions']) != 4096:
        raise ValueError('java_python_parity.positions must be exactly 4096')
    report['checks']['java_python_parity'] = run_parity(candidate_path, parity_config)
    if not report['checks']['java_python_parity']['pass']:
        report['decision'] = {
            'pass': False, 'eligible_for_ab': False,
            'failed_checks': ['java_python_parity'],
        }
        return report
    baseline = Evaluator(baseline_path)
    candidate = Evaluator(candidate_path)
    samples, scan = select_samples(data_paths, config['heldout'])
    report['heldout_sample'] = scan
    phase_weights = {
        phase: int(scan['eligible_by_phase'][str(phase)]) for phase in range(4)
    }
    metrics = evaluate_rmse(baseline, candidate, samples, phase_weights)
    report['rmse'] = metrics
    report['checks']['rmse'] = rmse_gate(metrics, config['rmse_gate'])
    directions = run_direction_check(
        baseline, candidate, samples, config['d4_direction_check'],
    )
    report['d4_direction_difference'] = {
        'baseline': directions['baseline'],
        'candidate': directions['candidate'],
    }
    report['checks']['d4_direction_difference'] = directions['gate']
    failed = [
        name for name, check in report['checks'].items()
        if not bool(check['pass'])
    ]
    report['decision'] = {
        'pass': not failed,
        'eligible_for_ab': not failed,
        'failed_checks': failed,
    }
    return report


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument(
        '--baseline', type=Path,
        default=PROJECT_ROOT / 'resources' / 'param.txt',
    )
    parser.add_argument(
        '--config', type=Path,
        default=PROJECT_ROOT / 'config' / 'candidate_gate.json',
    )
    parser.add_argument(
        '--data', type=Path, action='append',
        help='override heldout.paths; repeat for multiple files',
    )
    parser.add_argument(
        '--report', type=Path,
        default=PROJECT_ROOT / 'artifacts' / 'candidate_validation.json',
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    config_path = resolve_project_path(args.config)
    try:
        config = json.loads(config_path.read_text(encoding='utf-8'))
        configured_paths = config['heldout']['paths']
        data_paths = (
            [resolve_project_path(path) for path in args.data]
            if args.data else [resolve_project_path(path) for path in configured_paths]
        )
        report = validate(
            resolve_project_path(args.candidate),
            resolve_project_path(args.baseline),
            data_paths,
            config,
        )
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        report = {
            'schema_version': 1,
            'decision': {
                'pass': False, 'eligible_for_ab': False,
                'failed_checks': ['execution'],
            },
            'error': f'{type(error).__name__}: {error}',
        }
    write_report(resolve_project_path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['decision']['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
