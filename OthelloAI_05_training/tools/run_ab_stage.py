#!/usr/bin/env python3
'''Run one preregistered A/B stage after enforcing all earlier gates.'''

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Sequence

import arena


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / 'config' / 'ab_stages.json'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'expected JSON object: {path}')
    return value


def resolve(path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _check(actual: float, operator: str, expected: float) -> dict[str, Any]:
    passed = {
        '<=': actual <= expected, '>=': actual >= expected, '>': actual > expected,
    }[operator]
    return {
        'pass': passed, 'actual': actual,
        'operator': operator, 'expected': expected,
    }


def assess_summary(
    summary: dict[str, Any],
    stage: dict[str, Any],
    candidate_label: str = 'A',
) -> dict[str, Any]:
    rules = stage['advance']
    paired = summary['players'][candidate_label]['paired']
    checks: dict[str, Any] = {}
    if rules.get('require_complete'):
        passed = (
            summary['games_recorded'] == summary['games_requested']
            and summary['completed_games'] == summary['games_requested']
            and paired['complete_pairs'] == summary['pairs_requested']
            and paired['invalid_pairs'] == 0
        )
        checks['complete'] = {
            'pass': passed,
            'games': summary['games_recorded'],
            'pairs': paired['complete_pairs'],
        }
    if 'faults_max' in rules:
        checks['faults'] = _check(
            float(summary['faults']['total']),
            '<=', float(rules['faults_max']),
        )
    if 'pair_score_rate_min' in rules:
        value = paired['score_rate']
        checks['pair_score_rate'] = {
            'pass': value is not None and value >= rules['pair_score_rate_min'],
            'actual': value, 'operator': '>=',
            'expected': rules['pair_score_rate_min'],
        }
    if 'pair_ci_lower_gt' in rules:
        value = paired['wilson_95']['score_rate'][0]
        checks['pair_ci_lower'] = _check(
            float(value), '>', float(rules['pair_ci_lower_gt']),
        )
    difference = paired['average_disc_difference']
    for key, operator in (
        ('average_disc_difference_min', '>='),
        ('average_disc_difference_gt', '>'),
    ):
        if key not in rules:
            continue
        checks['average_disc_difference'] = {
            'pass': difference is not None and {
                '>=': difference >= rules[key],
                '>': difference > rules[key],
            }[operator],
            'actual': difference, 'operator': operator, 'expected': rules[key],
        }
    passed = bool(checks) and all(item['pass'] for item in checks.values())
    return {
        'pass': passed,
        'advance': passed,
        'checks': checks,
        'candidate_label': candidate_label,
    }


def verify_candidate_gate(
    report: dict[str, Any], candidate: Path, baseline: Path,
) -> None:
    if not report.get('decision', {}).get('eligible_for_ab'):
        raise ValueError('candidate validation report did not pass')
    expected_candidate = report.get('candidate', {}).get('sha256')
    expected_baseline = report.get('baseline', {}).get('sha256')
    if expected_candidate != sha256(candidate):
        raise ValueError('candidate hash differs from validation report')
    if expected_baseline != sha256(baseline):
        raise ValueError('baseline hash differs from validation report')


def verify_previous(
    stage: dict[str, Any],
    previous_path: Path | None,
    candidate_hash: str,
    baseline_hash: str,
    config_hash: str,
    gate_hash: str,
) -> None:
    required = stage['requires']
    if required == 'candidate_gate':
        return
    if previous_path is None or not previous_path.is_file():
        raise ValueError(f'stage requires passing {required} summary')
    previous = read_json(previous_path)
    metadata = previous.get('ab_stage', {})
    if metadata.get('name') != required:
        raise ValueError(f'previous summary is not the required {required} stage')
    if not previous.get('decision', {}).get('advance'):
        raise ValueError(f'previous {required} stage did not pass')
    if metadata.get('candidate_sha256') != candidate_hash:
        raise ValueError('candidate changed since previous stage')
    if metadata.get('baseline_sha256') != baseline_hash:
        raise ValueError('baseline changed since previous stage')
    if metadata.get('config_sha256') != config_hash:
        raise ValueError('A/B stage config changed since previous stage')
    if metadata.get('candidate_validation_sha256') != gate_hash:
        raise ValueError('candidate validation report changed since previous stage')


def command_for_parameter(template: Sequence[str], parameter: Path) -> str:
    if not any('{param}' in item for item in template):
        raise ValueError('--engine-command must contain {param}')
    command = [item.replace('{param}', str(parameter.resolve())) for item in template]
    return json.dumps(command, ensure_ascii=False)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--gate-report', type=Path, required=True)
    parser.add_argument('--previous-summary', type=Path)
    parser.add_argument('--candidate-param', type=Path, required=True)
    parser.add_argument(
        '--baseline-param', type=Path,
        default=PROJECT_ROOT / 'resources' / 'param.txt',
    )
    parser.add_argument(
        '--engine-command', required=True,
        help='one common command containing {param}; JSON argv is recommended',
    )
    parser.add_argument('--cwd', type=Path, default=PROJECT_ROOT)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--overwrite', action='store_true')
    return parser


def _default_output_dir(candidate: Path, candidate_hash: str) -> Path:
    return PROJECT_ROOT / 'results' / f'{candidate.stem}-{candidate_hash[:12]}'


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        config_path = resolve(args.config)
        config = read_json(config_path)
        if args.stage not in config['stages']:
            raise ValueError(f'unknown stage: {args.stage}')
        stage = config['stages'][args.stage]
        candidate = resolve(args.candidate_param)
        baseline = resolve(args.baseline_param)
        gate_path = resolve(args.gate_report)
        for path in (candidate, baseline, gate_path):
            if not path.is_file():
                raise ValueError(f'required file does not exist: {path}')
        gate = read_json(gate_path)
        verify_candidate_gate(gate, candidate, baseline)
        candidate_hash, baseline_hash = sha256(candidate), sha256(baseline)
        output_dir = (
            resolve(args.output_dir) if args.output_dir
            else _default_output_dir(candidate, candidate_hash)
        )
        required = stage['requires']
        previous_path = resolve(args.previous_summary) if args.previous_summary else None
        if previous_path is None and required != 'candidate_gate':
            previous_path = output_dir / f'{required}-summary.json'
        verify_previous(
            stage, previous_path, candidate_hash, baseline_hash,
            sha256(config_path), sha256(gate_path),
        )
        games_path = output_dir / f'{args.stage}-games.jsonl'
        summary_path = output_dir / f'{args.stage}-summary.json'
        if not args.overwrite and (games_path.exists() or summary_path.exists()):
            raise ValueError('stage output already exists; use --overwrite to replace it')
        template = arena.parse_command(args.engine_command)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f'AB stage blocked: {error}', file=sys.stderr)
        return 2

    if config.get('candidate_label') != 'A':
        print('AB stage blocked: candidate_label must be A', file=sys.stderr)
        return 2
    output_dir.mkdir(parents=True, exist_ok=True)
    cwd = resolve(args.cwd)
    opening_seed = int(stage.get('opening_seed', config['opening_seed']))
    arena_args = [
        '--ai-a', command_for_parameter(template, candidate),
        '--ai-b', command_for_parameter(template, baseline),
        '--name-a', 'candidate', '--name-b', 'baseline',
        '--cwd-a', str(cwd), '--cwd-b', str(cwd),
        '--pairs', str(int(stage['pairs'])),
        '--random-opening-plies',
        str(int(stage.get('random_opening_plies', config['random_opening_plies']))),
        '--seed', str(opening_seed),
        '--move-time-ms', str(int(stage['move_time_ms'])),
        '--threads', str(int(config['threads'])),
        '--engine-seed', str(int(config['engine_seed'])),
        '--jsonl', str(games_path),
        '--summary', str(summary_path),
    ]
    arena_code = arena.main(arena_args)
    summary = read_json(summary_path)
    summary['ab_stage'] = {
        'name': args.stage,
        'config_path': str(config_path),
        'config_sha256': sha256(config_path),
        'candidate_sha256': candidate_hash,
        'baseline_sha256': baseline_hash,
        'candidate_validation_report': str(gate_path),
        'candidate_validation_sha256': sha256(gate_path),
        'previous_summary': None if previous_path is None else str(previous_path),
        'stage_config': stage,
    }
    summary['decision'] = assess_summary(summary, stage, config['candidate_label'])
    if args.stage == 'acceptance':
        summary['decision']['adopt_candidate'] = summary['decision']['pass']
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    print(json.dumps({
        'stage': args.stage,
        'summary': str(summary_path),
        'decision': summary['decision'],
    }, ensure_ascii=False, indent=2))
    if arena_code != 0:
        return arena_code
    return 0 if summary['decision']['advance'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
