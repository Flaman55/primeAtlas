import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'prime_sieve'))
from prime_sieve.hybrid_policy import parameters, MAX_TARGET, MAX_FILTER, check_target
from primeatlas.hybrid_controls import HybridControls


class Var:
    def __init__(self, value=''):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class Controls(HybridControls):
    def __init__(self):
        for name in ('quick_status_var', 'quick_primesieve_from_var',
                     'quick_primesieve_floor_var', 'quick_primesieve_width_var'):
            setattr(self, name, Var())
        self.quick_mode_var = Var('hybrid')
        self.launched = False
    def _on_quick_mode_changed(self):
        pass
    def _on_quick_generate_clicked(self):
        self.launched = True


class PolicyTests(unittest.TestCase):
    def test_preflight_updates_fields_and_launches(self):
        ui = Controls()
        ui.quick_hybrid_main_cap_var = Var('100')
        ui.quick_hybrid_filter_prime_count_var = Var('1')
        ui._hybrid_input_snapshot = lambda: 'unchanged'
        ui._hybrid_async = lambda work, done: done(work(), None)
        from unittest.mock import Mock
        ui.loop_console = Mock()
        ui._on_run_hybrid_narrow = Mock()
        ui._prepare_hybrid(110000000, 120000000, 100, 1)
        args = ui._on_run_hybrid_narrow.call_args.args
        self.assertEqual(args[:3], (110000000, 120000000, 100))
        self.assertGreater(args[3], 1)
        self.assertEqual(ui.quick_hybrid_filter_prime_count_var.get(), str(args[3]))

    def test_preflight_cancels_if_inputs_change(self):
        ui = Controls()
        from unittest.mock import Mock
        ui._hybrid_input_snapshot = Mock(side_effect=['before', 'after'])
        ui._hybrid_async = lambda work, done: done(work(), None)
        ui._on_run_hybrid_narrow = Mock()
        ui._prepare_hybrid(10000000, 20000000, 100, 10000)
        ui._on_run_hybrid_narrow.assert_not_called()

    def test_policy_matches_engine_proof(self):
        from prime_sieve.hybrid_policy import _table
        from prime_sieve.hybrid_planner import plan_hybrid_boundaries
        from bisect import bisect_right
        primes = _table()
        p = parameters(100, 10000, 20000000)
        index = bisect_right(primes, p['main']) - 1
        plan = plan_hybrid_boundaries(primes[index],
            primes[index + 1:index + 1 + p['count']], primes[index + 1 + p['count']],
            base_is_contiguous=True, filter_is_consecutive=True)
        self.assertEqual(plan.limit, p['proof_limit'])

    def test_default_and_boundary(self):
        p = parameters(100, 10000)
        self.assertEqual(p['main_prime'], 97)
        self.assertEqual(p['proof_limit'], 10607322)
        self.assertEqual(parameters(100, 10000, p['limit'] + 1)['count'], 10000)
        self.assertGreater(parameters(100, 10000, p['limit'] + 2)['count'], 10000)

    def test_filter_first_and_minimal(self):
        p = parameters(100, 1, 120000001)
        self.assertEqual(p['main'], 100)
        self.assertGreaterEqual(p['limit'], 120000000)
        self.assertLess(parameters(100, p['count'] - 1)['limit'], 120000000)

    def test_main_only_after_max_filter(self):
        p = parameters(100, 10000, MAX_TARGET + 1)
        self.assertEqual(p['count'], MAX_FILTER)
        self.assertEqual(p['limit'], MAX_TARGET)
        self.assertGreater(p['main'], 100)
        self.assertLess(parameters(p['main'] - 1, MAX_FILTER)['limit'], MAX_TARGET)

    def test_main_cap_depends_on_filter(self):
        small, large = parameters(10**30, 1), parameters(10**30, MAX_FILTER)
        self.assertGreater(small['main_max'], large['main_max'])
        for p in (small, large):
            self.assertEqual(p['main'], p['main_max'])
            self.assertEqual(p['limit'], MAX_TARGET)

    def test_global_boundary(self):
        check_target(MAX_TARGET + 1)
        with self.assertRaises(ValueError):
            check_target(MAX_TARGET + 2)
        with self.assertRaises(ValueError):
            check_target(MAX_TARGET + 10_000_000)

    def test_invalid_parameters(self):
        for main, count in ((None, 1), (1, 1), (100, 0), (100, MAX_FILTER + 1)):
            with self.assertRaises(ValueError):
                parameters(main, count)

    def test_handoff_requires_consent_and_preserves_range(self):
        for consent in (False, True):
            ui = Controls()
            with patch('primeatlas.hybrid_controls.messagebox.askyesno', return_value=consent):
                ui._offer_hybrid_primesieve(10**11, 10**11 + 10_000_000)
            self.assertEqual(ui.launched, consent)
            self.assertEqual(ui.quick_mode_var.get(), 'primesieve' if consent else 'hybrid')
            if consent:
                self.assertEqual(ui.quick_primesieve_from_var.get(), str(10**11))
                self.assertEqual(ui.quick_primesieve_width_var.get(), '1')


if __name__ == '__main__':
    unittest.main()
