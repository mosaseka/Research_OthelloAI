from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'tools'))

import arena  # noqa: E402
import run_ab_stage  # noqa: E402
import validate_candidate  # noqa: E402


EMPTY_SEARCH = {
    'A': {
        'average_depth': None, 'depth_samples': 0,
        'average_nps': None, 'nps_samples': 0,
    },
    'B': {
        'average_depth': None, 'depth_samples': 0,
        'average_nps': None, 'nps_samples': 0,
    },
}


def game(
    pair: int, index: int, score_a: float, discs: int,
    *, status: str = 'completed',
) -> dict[str, object]:
    colour = 'black' if index == 0 else 'white'
    outcome = 'win' if score_a == 1 else 'loss' if score_a == 0 else 'draw'
    return {
        'pair_index': pair, 'game_in_pair': index,
        'opening_seed': 1000 + pair, 'player_a_colour': colour,
        'black_player': 'A' if colour == 'black' else 'B',
        'white_player': 'B' if colour == 'black' else 'A',
        'status': status, 'fault': None,
        'outcome_a': outcome, 'score_a': score_a,
        'disc_difference_a': discs, 'search': EMPTY_SEARCH,
    }


class PairedArenaTests(unittest.TestCase):
    def test_fractional_pair_score_is_not_rounded_to_win(self) -> None:
        records = [game(0, 0, 1.0, 4), game(0, 1, 0.5, 0)]
        paired = arena._paired_perspective_stats(records, 'A')
        self.assertEqual(paired['wins'], 1)
        self.assertEqual(paired['score'], 0.75)
        self.assertEqual(paired['score_rate'], 0.75)
        self.assertEqual(
            paired['wilson_95']['score_rate'],
            arena.wilson_interval(0.75, 1),
        )

    def test_incomplete_pair_is_excluded(self) -> None:
        records = [game(0, 0, 1.0, 4)]
        paired = arena._paired_perspective_stats(records, 'A')
        self.assertEqual(paired['complete_pairs'], 0)
        self.assertEqual(paired['invalid_reasons'], {'game_count': 1})

    def test_mismatched_opening_position_is_excluded(self) -> None:
        records = [game(0, 0, 1.0, 4), game(0, 1, 0.0, -4)]
        records[0]['starting_board'] = ['.' * 8] * 8
        records[1]['starting_board'] = ['0' + '.' * 7] + ['.' * 8] * 7
        paired = arena._paired_perspective_stats(records, 'A')
        self.assertEqual(paired['complete_pairs'], 0)
        self.assertEqual(paired['invalid_reasons'], {'opening_position': 1})

    def test_acceptance_uses_pair_ci_disc_difference_and_faults(self) -> None:
        records: list[dict[str, object]] = []
        for pair in range(512):
            won = pair < 330
            score, discs = (1.0, 2) if won else (0.0, -1)
            records.extend((game(pair, 0, score, discs), game(pair, 1, score, discs)))
        summary = arena.build_summary(records, {'pairs': 512})
        stage = {
            'advance': {
                'require_complete': True, 'faults_max': 0,
                'pair_ci_lower_gt': 0.5,
                'average_disc_difference_gt': 0.0,
            },
        }
        decision = run_ab_stage.assess_summary(summary, stage)
        self.assertTrue(decision['pass'])
        self.assertGreater(
            summary['players']['A']['paired']['wilson_95']['score_rate'][0],
            0.5,
        )
        summary['faults']['total'] = 1
        self.assertFalse(run_ab_stage.assess_summary(summary, stage)['pass'])
        summary['faults']['total'] = 0
        summary['players']['A']['paired']['average_disc_difference'] = 0.0
        self.assertFalse(run_ab_stage.assess_summary(summary, stage)['pass'])
        summary['players']['A']['paired']['average_disc_difference'] = 1.0
        summary['players']['A']['paired']['wilson_95']['score_rate'][0] = 0.5
        self.assertFalse(run_ab_stage.assess_summary(summary, stage)['pass'])


class CandidateValidationTests(unittest.TestCase):
    def test_synthetic_candidate_runs_full_gate(self) -> None:
        split = {
            'seed': 7,
            'ratios': {'train': 0.0, 'val': 0.0, 'test': 1.0},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / 'candidate.txt'
            candidate.write_text('0\n' * 25_436, encoding='utf-8')
            data = root / 'positions.txt'
            data.write_text('\n'.join(
                'X' * stones + '-' * (64 - stones) + ' 0'
                for stones in (4, 34, 44, 54)
            ) + '\n', encoding='utf-8')
            training = root / 'train.json'
            training.write_text(
                json.dumps({'data': {'split': split}}), encoding='utf-8',
            )
            config = {
                'java_python_parity': {'positions': 4096},
                'heldout': {
                    'training_config': str(training), 'paths': [str(data)],
                    'split_name': 'test', 'split': split, 'sample_seed': 9,
                    'samples_per_phase': 1, 'max_source_records': None,
                },
                'rmse_gate': {
                    'minimum_relative': 0.0, 'minimum_absolute_disc': 0.0,
                    'endgame_phase': 3, 'endgame_tolerance_disc': 0.0,
                },
                'd4_direction_check': {
                    'samples_per_phase': 1,
                    'maximum_candidate_span_disc': None,
                    'require_nonworsening': False,
                },
            }
            parity = {
                'pass': True, 'positions': 4096, 'command': ['synthetic'],
                'returncode': 0, 'stdout': 'PASS: 4096 reachable positions',
                'stderr': '', 'duration_seconds': 0.0,
            }
            with mock.patch.object(
                validate_candidate, 'run_parity', return_value=parity,
            ):
                report = validate_candidate.validate(
                    candidate, PROJECT_ROOT / 'resources' / 'param.txt',
                    [data], config,
                )
            self.assertTrue(report['decision']['eligible_for_ab'])
            self.assertEqual(
                report['rmse']['candidate']['rmse_disc'], 0.0,
            )
            self.assertEqual(
                report['d4_direction_difference']['candidate']
                ['maximum_span_java_units'],
                0,
            )

    def test_parameter_count_and_finite_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            good = Path(temporary) / 'good.txt'
            good.write_text('0\n' * 25_436, encoding='utf-8')
            self.assertTrue(validate_candidate.parameter_check(good)['pass'])
            bad = Path(temporary) / 'bad.txt'
            bad.write_text('0\n' * 25_435 + 'nan\n', encoding='utf-8')
            result = validate_candidate.parameter_check(bad)
            self.assertFalse(result['pass'])
            self.assertFalse(result['all_finite'])

    def test_rmse_gate_or_improvement_and_endgame_nonworsening(self) -> None:
        metrics = {
            'baseline': {
                'rmse_disc': 10.0,
                'phases': {'3': {'rmse_disc': 8.0}},
            },
            'candidate': {
                'rmse_disc': 9.9,
                'phases': {'3': {'rmse_disc': 8.0}},
            },
        }
        config = {
            'minimum_relative': 0.01, 'minimum_absolute_disc': 0.1,
            'endgame_phase': 3, 'endgame_tolerance_disc': 0.0,
        }
        self.assertTrue(validate_candidate.rmse_gate(metrics, config)['pass'])
        metrics['candidate']['phases']['3']['rmse_disc'] = 8.001
        self.assertFalse(validate_candidate.rmse_gate(metrics, config)['pass'])

    def test_overall_rmse_uses_heldout_population_weights(self) -> None:
        squares = {0: 1.0, 1: 4.0, 2: 9.0, 3: 16.0}
        counts = Counter({phase: 1 for phase in range(4)})
        result = validate_candidate._rmse_result(
            squares, counts, {0: 4, 1: 1, 2: 1, 3: 1},
        )
        self.assertAlmostEqual(result['rmse_disc'], (33.0 / 7.0) ** 0.5)
        self.assertEqual(result['aggregation'], 'heldout_population_weighted')

    def test_d4_has_all_eight_directions(self) -> None:
        board = ''.join(chr(65 + index) for index in range(64))
        variants = validate_candidate.d4_variants(board)
        self.assertEqual(len(variants), 8)
        self.assertEqual(len(set(variants)), 8)

    def test_heldout_split_must_match_full_training_config(self) -> None:
        split = {
            'seed': 20260715,
            'ratios': {'train': 0.9, 'val': 0.05, 'test': 0.05},
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'train.json'
            path.write_text(
                json.dumps({'data': {'split': split}}), encoding='utf-8',
            )
            heldout = {
                'training_config': str(path), 'split_name': 'test',
                'split': split,
            }
            self.assertTrue(validate_candidate.split_contract(heldout)['pass'])
            heldout['split'] = {
                'seed': 20260715,
                'ratios': {'train': 0.8, 'val': 0.1, 'test': 0.1},
            }
            self.assertFalse(validate_candidate.split_contract(heldout)['pass'])

    def test_stratified_sampling_covers_all_phases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / 'positions.txt'
            rows = [
                'X' * stones + '-' * (64 - stones) + ' 0'
                for stones in (4, 34, 44, 54)
            ]
            data.write_text('\n'.join(rows) + '\n', encoding='utf-8')
            config = {
                'split_name': 'test',
                'split': {
                    'seed': 1,
                    'ratios': {'train': 0.0, 'val': 0.0, 'test': 1.0},
                },
                'sample_seed': 2, 'samples_per_phase': 1,
                'max_source_records': None,
            }
            samples, report = validate_candidate.select_samples([data], config)
            self.assertEqual([len(samples[p]) for p in range(4)], [1, 1, 1, 1])
            self.assertEqual(report['selected_by_phase'], {
                '0': 1, '1': 1, '2': 1, '3': 1,
            })

    def test_ab_gate_binds_both_parameter_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / 'candidate.txt'
            baseline = Path(temporary) / 'baseline.txt'
            candidate.write_text('1\n', encoding='utf-8')
            baseline.write_text('0\n', encoding='utf-8')
            report = {
                'decision': {'eligible_for_ab': True},
                'candidate': {'sha256': run_ab_stage.sha256(candidate)},
                'baseline': {'sha256': run_ab_stage.sha256(baseline)},
            }
            run_ab_stage.verify_candidate_gate(report, candidate, baseline)
            candidate.write_text('2\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'candidate hash'):
                run_ab_stage.verify_candidate_gate(report, candidate, baseline)

    def test_previous_stage_freezes_candidate_config_and_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'summary.json'
            path.write_text(json.dumps({
                'decision': {'advance': True},
                'ab_stage': {
                    'name': 'smoke', 'candidate_sha256': 'candidate',
                    'baseline_sha256': 'baseline', 'config_sha256': 'config',
                    'candidate_validation_sha256': 'gate',
                },
            }), encoding='utf-8')
            stage = {'requires': 'smoke'}
            run_ab_stage.verify_previous(
                stage, path, 'candidate', 'baseline', 'config', 'gate',
            )
            with self.assertRaisesRegex(ValueError, 'config changed'):
                run_ab_stage.verify_previous(
                    stage, path, 'candidate', 'baseline', 'new', 'gate',
                )


if __name__ == '__main__':
    unittest.main()
