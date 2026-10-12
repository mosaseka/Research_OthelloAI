"""Network-free integration tests for the v0002 training entrypoint."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRAINING_DIR = PROJECT_ROOT / 'training'
sys.path.insert(0, str(TRAINING_DIR))

import run_training_pipeline as pipeline  # noqa: E402
import train_evaluator as trainer  # noqa: E402


class V0002TrainingIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config_path = PROJECT_ROOT / 'config' / 'train_v0002.json'
        cls.config = trainer.load_config(cls.config_path)

    def test_production_config_and_stage_order(self) -> None:
        pipeline.validate_pipeline_config(self.config)
        self.assertNotIn('preparation', self.config)
        plan = pipeline.command_plan(
            self.config_path,
            self.config,
            'all',
            device='cpu',
            report_override=None,
            resume=None,
            export=None,
            quiet=False,
        )
        self.assertEqual(['verify', 'overfit', 'train'], [name for name, _ in plan])
        verify = plan[0][1]
        self.assertIn('train_evaluator.py', ' '.join(verify))
        self.assertIn('--config', verify)
        self.assertIn('--scan-only', verify)
        self.assertNotIn('prepare_egaroucid_v2.py', ' '.join(verify))
        self.assertNotIn('--quiet', verify)

    def test_quiet_is_propagated_to_every_v0002_child(self) -> None:
        plan = pipeline.command_plan(
            self.config_path,
            self.config,
            'all',
            device=None,
            report_override=None,
            resume=None,
            export=None,
            quiet=True,
        )
        self.assertTrue(all('--quiet' in command for _, command in plan))

    def test_pipeline_dry_run_does_not_prepare_or_train(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = pipeline.main([
                '--config', str(self.config_path),
                '--stage', 'all',
                '--dry-run',
                '--quiet',
            ])
        self.assertEqual(0, result)
        self.assertIn('"stage": "verify"', stdout.getvalue())
        self.assertIn('pipeline dry-run complete', stdout.getvalue())
        self.assertEqual('', stderr.getvalue())

    def test_scan_only_uses_shared_prepared_verifier(self) -> None:
        manifest = {
            '_resolved_path': 'conversion_manifest.json',
            'status': 'verified-full',
            'counts': {
                'prepared_records_by_phase': {
                    '0': 1,
                    '1': 1,
                    '2': 1,
                    '3': 1,
                },
            },
        }
        split_counts = {'train': 2, 'val': 1, 'test': 1}
        resolved = (
            manifest,
            split_counts,
            {'train': [], 'val': [], 'test': []},
            True,
            [Path('train.txt'), Path('val.txt'), Path('test.txt')],
        )
        stdout = io.StringIO()
        with (
            mock.patch.object(
                trainer,
                'load_config',
                return_value={'data': {'prepared_manifest': 'manifest.json'}},
            ),
            mock.patch.object(
                trainer,
                'resolve_and_verify_training_data',
                return_value=resolved,
            ) as verifier,
            redirect_stdout(stdout),
        ):
            result = trainer.main(['--scan-only', '--quiet'])
        self.assertEqual(0, result)
        verifier.assert_called_once()
        self.assertIn('"shard_integrity": "passed"', stdout.getvalue())

    def test_prepared_manifest_supplies_exact_progress_totals(self) -> None:
        with tempfile.TemporaryDirectory(prefix='v2-manifest-') as temporary:
            root = Path(temporary)
            manifest_path = root / 'conversion_manifest.json'
            payload = {
                'schema_version': 2,
                'status': 'verified-full',
                'output_root': str(root),
                'split': {
                    'algorithm': 'sha256-canonical-d4-board-v1',
                    'unit': 'canonical_d4_relative_board',
                    'seed': '7',
                    'ratios': {'train': '0.9', 'val': '0.05', 'test': '0.05'},
                },
                'counts': {
                    'source_files': 5200,
                    'source_games': 52000000,
                    'prepared_records': 51999900,
                    'skipped_no_position': 100,
                    'by_split': {
                        'train': 46799910,
                        'val': 2599995,
                        'test': 2599995,
                    },
                    'prepared_records_by_phase': {
                        '0': 22000000,
                        '1': 10000000,
                        '2': 10000000,
                        '3': 9999900,
                    },
                },
            }
            manifest_path.write_text(
                json.dumps(payload), encoding='utf-8'
            )
            config = {
                'data': {
                    'prepared_manifest': str(manifest_path),
                    'split': {
                        'seed': 7,
                        'ratios': {'train': 0.9, 'val': 0.05, 'test': 0.05},
                    },
                    'train_color_augmentation': 'random',
                    'eval_color_augmentation': 'both',
                },
            }
            manifest, split_counts = trainer.load_prepared_manifest(config)
        self.assertIsNotNone(manifest)
        self.assertEqual(
            {'train': 46799910, 'val': 2599995, 'test': 2599995},
            split_counts,
        )
        self.assertEqual(
            (math.ceil(46799910 / 512), False),
            trainer.expected_loader_steps(
                config['data'], 'train', 512, 0, split_counts
            ),
        )
        self.assertEqual(
            (math.ceil((2599995 * 2) / 512), False),
            trainer.expected_loader_steps(
                config['data'], 'val', 512, 0, split_counts
            ),
        )

    def test_incomplete_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix='v2-bad-manifest-') as temporary:
            path = Path(temporary) / 'manifest.json'
            path.write_text(
                json.dumps({'status': 'verified-limited'}), encoding='utf-8'
            )
            config = {
                'data': {
                    'prepared_manifest': str(path),
                    'split': {
                        'seed': 1,
                        'ratios': {'train': 0.8, 'val': 0.1, 'test': 0.1},
                    },
                },
            }
            with self.assertRaisesRegex(RuntimeError, 'not a completed full'):
                trainer.load_prepared_manifest(config)

    def test_preassigned_split_paths_are_disjoint(self) -> None:
        row = 'X' * 32 + 'O' * 31 + '- 0\n'
        with tempfile.TemporaryDirectory(prefix='v2-splits-') as temporary:
            root = Path(temporary)
            paths_by_split: dict[str, list[str]] = {}
            for split in trainer.SPLIT_NAMES:
                folder = root / split
                folder.mkdir()
                (folder / 'sample.txt').write_text(row, encoding='ascii')
                paths_by_split[split] = [str(folder / '*.txt')]
            resolved, pre_split = trainer.resolve_split_data_paths({
                'paths_by_split': paths_by_split,
            })
        self.assertTrue(pre_split)
        self.assertTrue(all(len(resolved[split]) == 1 for split in trainer.SPLIT_NAMES))
        self.assertEqual(
            3,
            len({path for values in resolved.values() for path in values}),
        )

    def test_shared_prepared_verifier_checks_shard_hash(self) -> None:
        row = ('X' * 32 + 'O' * 31 + '- 0\n').encode('ascii')
        with tempfile.TemporaryDirectory(prefix='v2-integrity-') as temporary:
            root = Path(temporary)
            paths_by_split: dict[str, list[Path]] = {}
            outputs: dict[str, dict[str, object]] = {}
            for split in trainer.SPLIT_NAMES:
                path = root / split / 'sample.txt'
                path.parent.mkdir()
                path.write_bytes(row)
                paths_by_split[split] = [path.resolve()]
                outputs[split] = {
                    'path': path.relative_to(root).as_posix(),
                    'rows': 1,
                    'size_bytes': len(row),
                    'sha256': hashlib.sha256(row).hexdigest(),
                }
            manifest = {
                'output_root': str(root),
                'counts': {
                    'source_files': 1,
                    'by_split': {'train': 1, 'val': 1, 'test': 1},
                },
                'sources': [{'outputs': outputs}],
            }
            config = {
                'data': {
                    'paths_by_split': {
                        split: [str(path)]
                        for split, (path,) in paths_by_split.items()
                    },
                },
            }
            split_counts = {'train': 1, 'val': 1, 'test': 1}
            with mock.patch.object(
                trainer,
                'load_prepared_manifest',
                return_value=(manifest, split_counts),
            ):
                resolved = trainer.resolve_and_verify_training_data(
                    config, progress_enabled=False
                )
                self.assertEqual(3, len(resolved[-1]))

                changed = row[:-2] + b'1\n'
                self.assertEqual(len(row), len(changed))
                paths_by_split['train'][0].write_bytes(changed)
                with self.assertRaisesRegex(RuntimeError, 'differs from manifest'):
                    trainer.resolve_and_verify_training_data(
                        config, progress_enabled=False
                    )

    def test_resume_rejects_a_different_data_contract(self) -> None:
        config = {
            'dataset_kind': 'egaroucid_v0002_games',
            'seed': 7,
            'parameter_init': 'resources/param.txt',
            'model': {'dtype': 'float32'},
            'data': {
                'prepared_manifest': 'manifest.json',
                'split': {
                    'seed': 11,
                    'ratios': {'train': 0.9, 'val': 0.05, 'test': 0.05},
                },
            },
            'training': {
                'epochs': 3,
                'device': 'cpu',
                'batch_size': 512,
                'learning_rate': 0.0001,
            },
            'overfit': {'examples': 2048},
        }
        saved = copy.deepcopy(config)
        saved['resolved'] = {
            'overfit': False,
            'prepared_manifest_contract_sha256': None,
        }
        checkpoint = {'config': saved}
        trainer.validate_resume_compatibility(
            checkpoint,
            label='checkpoint',
            config=config,
            overfit_enabled=False,
            prepared_manifest=None,
        )

        changed = copy.deepcopy(config)
        changed['data']['split']['seed'] = 12
        with self.assertRaisesRegex(RuntimeError, 'contract differs'):
            trainer.validate_resume_compatibility(
                checkpoint,
                label='checkpoint',
                config=changed,
                overfit_enabled=False,
                prepared_manifest=None,
            )

    def test_prepared_manifest_contract_hash_tracks_output_hashes(self) -> None:
        first = {
            'schema_version': 2,
            'status': 'verified-full',
            'split': {'algorithm': 'sha256-canonical-d4-board-v1'},
            'counts': {'source_files': 1},
            'sources': [{
                'source_id': 'part0/release/8/0000000.txt',
                'outputs': {
                    'train': {'sha256': 'a' * 64},
                    'val': {'sha256': 'b' * 64},
                    'test': {'sha256': 'c' * 64},
                },
            }],
        }
        second = copy.deepcopy(first)
        second['sources'][0]['outputs']['train']['sha256'] = 'd' * 64
        self.assertNotEqual(
            trainer.prepared_manifest_contract_sha256(first),
            trainer.prepared_manifest_contract_sha256(second),
        )

    def test_v0002_config_rejects_finite_training_prefix(self) -> None:
        config = copy.deepcopy(self.config)
        config['training']['steps_per_epoch'] = 1
        with self.assertRaisesRegex(ValueError, 'forbids finite limits'):
            pipeline.validate_pipeline_config(config)


if __name__ == '__main__':
    unittest.main()
