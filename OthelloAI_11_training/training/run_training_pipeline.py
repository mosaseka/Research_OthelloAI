"""Run the gated original_11 value-training workflow.

The original_11 value route consumes the already verified v0002 shards from
the local ASCII workspace.  The external root is explicit in the configuration
and is never written by this pipeline.

The all stage always runs the required data gate first, then the 2,048-example
overfit check, and only then starts full-pass training. Child-process progress
is kept on stderr while JSON stage plans remain on stdout.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / 'config' / 'value_11a_fresh.json'
LEGACY_KIND = 'egaroucid_positions_v1'
V0002_KIND = 'egaroucid_v0002_games'
EXPECTED_RECORDS = 25_514_097
EXPECTED_PHASE_COUNTS = {
    0: 10_514_097,
    1: 5_000_000,
    2: 5_000_000,
    3: 5_000_000,
}
SPLITS = ('train', 'val', 'test')


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def require_artifact_path(path: Path, label: str) -> Path:
    artifacts = (PROJECT_ROOT / 'artifacts').resolve()
    if not path.is_relative_to(artifacts):
        raise ValueError(f'{label} must stay under artifacts/')
    return path


def require_processed_path(path: Path, label: str) -> Path:
    processed = (PROJECT_ROOT / 'data' / 'processed').resolve()
    if not path.is_relative_to(processed):
        raise ValueError(f'{label} must stay under data/processed/')
    return path


def load_config(path: Path) -> dict[str, Any]:
    with path.open('r', encoding='utf-8') as source:
        config = json.load(source)
    if not isinstance(config, dict):
        raise ValueError('configuration root must be a JSON object')
    return config


def _int_mapping(value: Any, label: str) -> dict[int, int]:
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be a JSON object')
    return {int(key): int(count) for key, count in value.items()}


def _ratios(value: Any, label: str) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != set(SPLITS):
        raise ValueError(f'{label} must contain exactly {SPLITS}')
    result = {split: float(value[split]) for split in SPLITS}
    if any(number <= 0.0 for number in result.values()):
        raise ValueError(f'{label} values must be positive')
    if not math.isclose(sum(result.values()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f'{label} values must sum to 1')
    return result


def dataset_kind(config: dict[str, Any]) -> str:
    return str(config.get('dataset_kind', LEGACY_KIND))


def _validate_common(config: dict[str, Any]) -> None:
    required_top_level = {
        'run_name',
        'candidate_name',
        'source_model_sha256',
        'checkpoint_resume_from',
        'resume_optimizer_state',
        'output_dir',
        'best_model_metric',
        'parameter_export_path',
        'manifest_output_path',
        'datasets',
    }
    missing = sorted(required_top_level.difference(config))
    if missing:
        raise ValueError(f'configuration is missing required provenance keys: {missing}')
    if config.get('best_model_metric') != 'validation_rmse':
        raise ValueError('best_model_metric must be validation_rmse')
    if config.get('feature_schema') != 'exact-mobility-v1':
        raise ValueError('feature_schema must be exact-mobility-v1')
    datasets = config.get('datasets')
    if not isinstance(datasets, dict) or set(datasets) != {'train', 'validation', 'heldout'}:
        raise ValueError('datasets must document train, validation, and heldout sources')
    source_sha = str(config.get('source_model_sha256', ''))
    if len(source_sha) != 64 or any(ch not in '0123456789abcdef' for ch in source_sha):
        raise ValueError('source_model_sha256 must be 64 lowercase hex digits')
    output = config.get('output')
    if not isinstance(output, dict):
        raise ValueError('output must be an object')
    if config.get('output_dir') != output.get('runs_dir'):
        raise ValueError('output_dir must equal output.runs_dir')
    if config.get('parameter_export_path') != output.get('candidate_path'):
        raise ValueError('parameter_export_path must equal output.candidate_path')
    data = config['data']
    training = config['training']
    sampling = data.get('epoch_sampling', {})
    if sampling.get('mode') != 'full_pass':
        raise ValueError('pipeline requires data.epoch_sampling.mode=full_pass')
    if set(int(value) for value in sampling.get('required_phases', [])) != {0, 1, 2, 3}:
        raise ValueError('pipeline requires all four evaluator phases')
    finite_steps = {
        key: int(training.get(key, 0))
        for key in ('steps_per_epoch', 'validation_steps', 'test_steps')
        if int(training.get(key, 0)) != 0
    }
    finite_sources = {
        split: int(data.get('max_source_records', {}).get(split, 0))
        for split in SPLITS
        if int(data.get('max_source_records', {}).get(split, 0)) != 0
    }
    if finite_steps or finite_sources:
        raise ValueError(
            'pipeline full pass forbids finite limits: '
            f'steps={finite_steps}, source_records={finite_sources}'
        )

    overfit = config.get('overfit', {})
    if not bool(overfit.get('required_gate', False)):
        raise ValueError('pipeline requires overfit.required_gate=true')
    if bool(overfit.get('enabled', False)):
        raise ValueError(
            'overfit.enabled must stay false; the pipeline gate uses --overfit '
            'and the production train stage must remain full-pass'
        )
    if int(overfit.get('examples', 0)) != 2048:
        raise ValueError('pipeline overfit.examples must be exactly 2048')
    if not bool(overfit.get('phase_stratified', False)):
        raise ValueError('pipeline requires phase-stratified overfit data')
    if float(overfit.get('minimum_relative_rmse_reduction', 0.0)) <= 0.0:
        raise ValueError('pipeline overfit RMSE reduction threshold must be positive')
    if list(training.get('phase_loss_weights', [])) != [1.0, 1.0, 1.0, 1.0]:
        raise ValueError('original_11 comparison requires unchanged phase_loss_weights')
    scheduler = training.get('scheduler')
    early = training.get('early_stopping')
    if not isinstance(scheduler, dict) or scheduler.get('type') != 'reduce_on_plateau':
        raise ValueError('training.scheduler must explicitly use reduce_on_plateau')
    if not isinstance(early, dict) or not bool(early.get('enabled', False)):
        raise ValueError('training.early_stopping.enabled must be true')
    require_artifact_path(
        resolve_project_path(config['output']['candidate_path']),
        'pipeline candidate_path',
    )

    progress = config.get('progress', {})
    if progress and not isinstance(progress, dict):
        raise ValueError('progress must be a JSON object')
    if float(progress.get('interval_seconds', 1.0)) < 0.0:
        raise ValueError('progress.interval_seconds must be non-negative')


def _validate_legacy(config: dict[str, Any]) -> None:
    data = config['data']
    if int(data.get('expected_source_records', -1)) != EXPECTED_RECORDS:
        raise ValueError(f'pipeline expected_source_records must be {EXPECTED_RECORDS}')
    if _int_mapping(
        data.get('expected_phase_counts'), 'data.expected_phase_counts'
    ) != EXPECTED_PHASE_COUNTS:
        raise ValueError(
            f'pipeline expected_phase_counts must be {EXPECTED_PHASE_COUNTS}'
        )
    source_zip_from_config(config)


def _validate_v0002(config: dict[str, Any]) -> None:
    data = config['data']
    manifest = resolve_project_path(data['prepared_manifest'])
    external_root_value = data.get('external_prepared_root')
    if external_root_value is None:
        manifest = require_processed_path(manifest, 'data.prepared_manifest')
    else:
        external_root = resolve_project_path(external_root_value)
        if manifest.parent != external_root:
            raise ValueError(
                'data.prepared_manifest must be directly under '
                'data.external_prepared_root'
            )
        if external_root != Path(
            'C:/Code/OthelloAI_05_training/data/processed/egaroucid_v2'
        ).resolve():
            raise ValueError('unexpected external prepared-data root')
    output_root = manifest.parent

    paths_by_split = data.get('paths_by_split')
    if not isinstance(paths_by_split, dict) or set(paths_by_split) != set(SPLITS):
        raise ValueError(f'data.paths_by_split must contain exactly {SPLITS}')
    for split in SPLITS:
        patterns = paths_by_split[split]
        if not isinstance(patterns, list) or not patterns:
            raise ValueError(f'data.paths_by_split.{split} must not be empty')
        for pattern in patterns:
            static_prefix = str(pattern).split('*', 1)[0].split('?', 1)[0]
            split_root = (output_root / split).resolve()
            if not resolve_project_path(static_prefix).is_relative_to(split_root):
                raise ValueError(
                    f'data.paths_by_split.{split} must stay under {split_root}'
                )

    split = data.get('split')
    if not isinstance(split, dict) or 'seed' not in split:
        raise ValueError('data.split must contain a seed')
    _ratios(split.get('ratios'), 'data.split.ratios')


def validate_pipeline_config(config: dict[str, Any]) -> None:
    """Reject settings that could silently turn production into a smoke run."""

    _validate_common(config)
    kind = dataset_kind(config)
    if kind == LEGACY_KIND:
        _validate_legacy(config)
    elif kind == V0002_KIND:
        _validate_v0002(config)
    else:
        raise ValueError(f'unsupported dataset_kind: {kind}')


def source_zip_from_config(config: dict[str, Any]) -> Path:
    patterns = config['data'].get('paths', [])
    if not isinstance(patterns, list) or len(patterns) != 1:
        raise ValueError('pipeline requires exactly one official ZIP in data.paths')
    raw_path = str(patterns[0])
    if any(character in raw_path for character in '*?[]'):
        raise ValueError(
            'pipeline data.paths must name the ZIP directly, without a glob'
        )
    path = resolve_project_path(raw_path)
    if path.suffix.lower() != '.zip':
        raise ValueError('pipeline data.paths entry must be a ZIP')
    return path


def command_plan(
    config_path: Path,
    config: dict[str, Any],
    stage: str,
    *,
    device: str | None,
    report_override: Path | None,
    resume: Path | None,
    export: Path | None,
    quiet: bool = False,
) -> list[tuple[str, list[str]]]:
    kind = dataset_kind(config)
    resume_policy = config.get('resume', {})
    if resume is not None and stage not in {'all', 'train'}:
        raise ValueError('--resume is only valid with --stage all or train')
    if bool(resume_policy.get('forbid_resume', False)) and resume is not None:
        raise ValueError('this fresh-seed configuration forbids --resume')
    if (
        bool(resume_policy.get('require_checkpoint', False))
        and stage in {'all', 'train'}
        and resume is None
    ):
        raise ValueError('this configuration requires --resume checkpoint_last.pt')
    requires_checkpoint = bool(resume_policy.get('require_checkpoint', False))
    pinned_checkpoint = config.get('checkpoint_resume_from')
    optimizer_resume = bool(config.get('resume_optimizer_state', False))
    if requires_checkpoint:
        if not isinstance(pinned_checkpoint, str) or not pinned_checkpoint:
            raise ValueError('checkpoint_resume_from must pin the legacy checkpoint')
        if not optimizer_resume:
            raise ValueError('value_11a continuation requires resume_optimizer_state=true')
        if resume is not None:
            requested = resolve_project_path(resume).resolve()
            pinned = resolve_project_path(pinned_checkpoint).resolve()
            if requested != pinned and not bool(resume_policy.get('allow_format_2_resume', False)):
                raise ValueError(
                    '--resume is neither the pinned legacy import nor an allowed format-2 continuation'
                )
    else:
        if pinned_checkpoint is not None:
            raise ValueError('fresh variants require checkpoint_resume_from=null')
        if not optimizer_resume:
            raise ValueError(
                'resume_optimizer_state must be true so an interrupted '
                'format-2 run can safely continue'
            )
        if resume is not None and not bool(resume_policy.get('allow_format_2_resume', False)):
            raise ValueError('this variant does not allow format-2 continuation')
    if kind != LEGACY_KIND and report_override is not None:
        raise ValueError('--report is only valid for the legacy ZIP verifier')
    selected = ('verify', 'overfit', 'train') if stage == 'all' else (stage,)
    allowed = {'verify', 'overfit', 'train'}
    if any(value not in allowed for value in selected):
        raise ValueError(
            f'stage {stage} is not valid for {kind}; use verify, overfit, train, or all'
        )

    result: list[tuple[str, list[str]]] = []
    common_quiet = quiet or not bool(
        config.get('progress', {}).get('enabled', True)
    )
    reuse_verified_scan = stage == 'all' and kind == V0002_KIND
    if 'verify' in selected:
        if kind == LEGACY_KIND:
            configured_report = config.get('pipeline', {}).get(
                'verification_report',
                'artifacts/data_validation/egaroucid_full_stats.json',
            )
            report = resolve_project_path(report_override or configured_report)
            command = [
                sys.executable,
                str(PROJECT_ROOT / 'training' / 'parse_egaroucid.py'),
                str(source_zip_from_config(config)),
                '--verify-all',
                '--output',
                str(report),
            ]
        else:
            command = [
                sys.executable,
                str(PROJECT_ROOT / 'training' / 'train_evaluator.py'),
                '--config',
                str(config_path),
                '--scan-only',
            ]
            if common_quiet:
                command.append('--quiet')
        result.append(('verify', command))

    if 'overfit' in selected:
        command = [
            sys.executable,
            str(PROJECT_ROOT / 'training' / 'train_evaluator.py'),
            '--config',
            str(config_path),
            '--overfit',
            '--no-export',
        ]
        if device:
            command.extend(('--device', device))
        if reuse_verified_scan:
            command.append('--pipeline-verified')
        if common_quiet:
            command.append('--quiet')
        result.append(('overfit', command))
    if 'train' in selected:
        command = [
            sys.executable,
            str(PROJECT_ROOT / 'training' / 'train_evaluator.py'),
            '--config',
            str(config_path),
        ]
        if device:
            command.extend(('--device', device))
        if reuse_verified_scan:
            command.append('--pipeline-verified')
        if resume:
            command.extend(('--resume', str(resolve_project_path(resume))))
        if export:
            command.extend((
                '--export',
                str(require_artifact_path(resolve_project_path(export), '--export')),
            ))
        if common_quiet:
            command.append('--quiet')
        result.append(('train', command))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        '--stage',
        choices=('all', 'verify', 'overfit', 'train'),
        default='all',
    )
    parser.add_argument('--device', help='device override passed to train_evaluator.py')
    parser.add_argument(
        '--report',
        type=Path,
        help='legacy ZIP validation-report override',
    )
    parser.add_argument('--resume', type=Path, help='checkpoint used by the train stage')
    parser.add_argument('--export', type=Path, help='candidate path used by the train stage')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='validate config and print commands without running them',
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='disable pipeline and child CUI progress',
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = resolve_project_path(args.config)
    try:
        config = load_config(config_path)
        validate_pipeline_config(config)
        if bool(config.get('overfit', {}).get('required_gate', False)) and args.stage == 'train':
            raise ValueError('required overfit gate would be bypassed; use --stage all')
        plan = command_plan(
            config_path,
            config,
            args.stage,
            device=args.device,
            report_override=args.report,
            resume=args.resume,
            export=args.export,
            quiet=args.quiet,
        )
        for index, (stage, command) in enumerate(plan, 1):
            print(
                json.dumps({'stage': stage, 'command': command}, ensure_ascii=False),
                flush=True,
            )
            if not args.quiet:
                print(
                    f'[pipeline {index}/{len(plan)}] {stage}',
                    file=sys.stderr,
                    flush=True,
                )
            if args.dry_run:
                continue
            completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
            if completed.returncode != 0:
                print(
                    f'pipeline stopped: {stage} exited with {completed.returncode}',
                    file=sys.stderr,
                )
                return completed.returncode
        print('pipeline dry-run complete' if args.dry_run else 'pipeline complete')
        return 0
    except (KeyError, OSError, TypeError, ValueError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('pipeline interrupted', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
