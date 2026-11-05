"""SFR postprocessing contracts (portable) plus optional KDT DAG/convention checks.

ExtractionTests need only numpy + FloPy: they write small MODFLOW 6 compact
(imeth 6) SFR budget files to a temp dir and read them back through FloPy's
real CellBudgetFile. ContractTests need the private KDT package; they are
skipped (not failed) when it is not importable.
"""
import importlib.util, os, struct, sys, tempfile, unittest
from pathlib import Path
import numpy as np
import yaml

os.environ.setdefault('MPLCONFIGDIR', tempfile.mkdtemp(prefix='mpl_'))
KI = Path(os.environ.get('KI_UNDER_TEST', Path(__file__).resolve().parents[1]))
_kdt_root = os.environ.get('KDT_ROOT', 'KISSPATH_INTERNAL_NOT_SHIPPED')
if os.path.isdir(_kdt_root):
    sys.path.insert(0, _kdt_root)
try:
    from auto_dissect_multi_agent import validation_convention as vc, obs_identity
    from calibration_kit.stop import convention_floor
    HAVE_KDT = True
except ImportError:
    HAVE_KDT = False

spec = importlib.util.spec_from_file_location('sfr', KI / 'tools/s11_sfr/parse_sfr_output.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def write_cbc(path, records):
    """records: list of (kstp, kper, totim, text, [(node, node2, q), ...])."""
    with open(path, 'wb') as f:
        for kstp, kper, totim, text, rows in records:
            f.write(struct.pack('<ii', kstp, kper) + text.rjust(16).encode())
            f.write(struct.pack('<iii', max(len(rows), 1), 1, -1))
            f.write(struct.pack('<iddd', 6, 1.0, totim, totim))
            for name in ('GWF_MODEL', 'SFR-1', 'GWF_MODEL', 'SFR-1'):
                f.write(name.ljust(16).encode())
            f.write(struct.pack('<ii', 1, len(rows)))
            for node, node2, q in rows:
                f.write(struct.pack('<iid', node, node2, q))


@unittest.skipUnless(HAVE_KDT, 'private KDT package not available')
class ContractTests(unittest.TestCase):
    def test_every_convention_reference_resolves(self):
        outputs = {o['var']: o for o in yaml.safe_load((KI / 'dag.yaml').read_text())['outputs']}
        for rule in vc.load(KI)['validation']:
            with self.subTest(var=rule['dag_variable'], shape=rule['obs_shape']):
                self.assertIn(rule['dag_variable'], outputs)
                shapes = [s['obs_shape'] for s in outputs[rule['dag_variable']]['observability']['comparable_obs_shapes']]
                self.assertIn(rule['obs_shape'], shapes)

    def test_existing_consumers_and_thresholds(self):
        outputs = {o['var']: o for o in obs_identity.dag_observable_vars(KI)}
        self.assertEqual(outputs['hydraulic_head']['validation_rank'], 1)
        for name in ['streamflow', 'baseflow']:
            self.assertEqual(outputs[name]['unit'], 'm3/s')
            block = vc.find_block(vc.load(KI), name, 'flow_duration_curve'); self.assertIsNotNone(block)
            self.assertEqual(vc.evaluate(block, {'nse': .5, 'pbias': 15})['verdict'], 'validated')
            for metrics in [{'nse': .49, 'pbias': 0}, {'nse': .8, 'pbias': 15.01}, {'nse': .8, 'pbias': -15.01}]:
                self.assertEqual(vc.evaluate(block, metrics)['verdict'], 'not_validated')
            floor = convention_floor(str(KI), 'nse', 'satisfactory', name)
            self.assertEqual(floor['value'], .5); self.assertEqual(floor['pbias_max'], 15)
            self.assertIsNone(vc.find_block(vc.load(KI), name, 'spatial_snapshot'))
        self.assertIsNone(vc.find_block(vc.load(KI), 'misspelled_discharge', 'flow_duration_curve'))


class FormatSpecTests(unittest.TestCase):
    def test_format_spec_projection(self):
        doc = yaml.safe_load((KI / 'docs/format_spec.yaml').read_text())
        outputs = {o['name']: o for o in doc['outputs']['primary']}
        for name in ['streamflow', 'baseflow']:
            self.assertEqual(outputs[name]['unit'], 'm3/s')
            self.assertIn('flow_duration_curve', [s['obs_shape'] for s in outputs[name]['observability']['comparable_obs_shapes']])


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)

    def parser(self, records):
        path = os.path.join(self.tmp.name, 'm.sfr.cbc'); write_cbc(path, records)
        return m.SFROutputParser(budget_file=path)

    def outflow(self, rows, times=(1., 2., 3.)):
        return [(i + 1, 1, t, 'EXT-OUTFLOW', rows) for i, t in enumerate(times)]

    def test_outlet_id_sign_and_units(self):
        rows = [(2, 0, -2.), (1, 0, -8.)]
        out = self.parser(self.outflow(rows)).outlet_flow_time_series([1], length_unit_m=2, time_unit_seconds=4)
        self.assertEqual(out['streamflow'], [16.] * 3); self.assertEqual(out['unit'], 'm3/s')
        out = self.parser(self.outflow(rows)).outlet_flow_time_series([1, 2], length_unit_m=1, time_unit_seconds=1)
        self.assertEqual(out['streamflow'], [10.] * 3)

    def test_closely_spaced_times_are_not_ambiguous(self):
        # FloPy get_data(totim=) uses np.isclose and would match all three.
        times = (100000., 100000.5, 100001.)
        recs = [(i + 1, 1, t, 'EXT-OUTFLOW', [(1, 0, -float(i + 1))]) for i, t in enumerate(times)]
        out = self.parser(recs).outlet_flow_time_series([1], length_unit_m=1, time_unit_seconds=1)
        self.assertEqual(out['times'], list(times)); self.assertEqual(out['streamflow'], [1., 2., 3.])

    def test_duplicate_time_step_or_bad_times_fail(self):
        dup = [(1, 1, 1., 'EXT-OUTFLOW', [(1, 0, -1.)]), (1, 1, 2., 'EXT-OUTFLOW', [(1, 0, -1.)])]
        back = [(1, 1, 2., 'EXT-OUTFLOW', [(1, 0, -1.)]), (2, 1, 1., 'EXT-OUTFLOW', [(1, 0, -1.)])]
        for recs in (dup, back):
            with self.subTest(recs=recs), self.assertRaises(ValueError):
                self.parser(recs).outlet_flow_time_series([1], length_unit_m=1, time_unit_seconds=1)

    def test_invalid_fluxes_units_or_selection_fail(self):
        rows = [(2, 0, -2.), (1, 0, -8.)]
        for ids in [[], [3], [1, 1], [0]]:
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.parser(self.outflow(rows)).outlet_flow_time_series(ids, length_unit_m=1, time_unit_seconds=1)
        for value in [np.nan, np.inf, 1.]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.parser(self.outflow([(1, 0, value)])).outlet_flow_time_series([1], length_unit_m=1, time_unit_seconds=1)
        with self.assertRaises(ValueError):
            self.parser(self.outflow(rows)).outlet_flow_time_series([1], length_unit_m=1, time_unit_seconds=0)
        gwf_only = [(1, 1, 1., 'GWF', [(1, 5, 1.)])]
        with self.assertRaises(ValueError):
            self.parser(gwf_only).outlet_flow_time_series([1], length_unit_m=1, time_unit_seconds=1)

    def test_exchange_by_reach_id_and_units(self):
        recs = [(1, 1, 1., 'GWF', [(2, 7, -3.), (1, 5, 2.)])]
        ex = self.parser(recs).get_stream_aquifer_exchange()
        self.assertEqual(ex['reaches'], [1, 2]); self.assertEqual(ex['exchange'], [2., -3.])
        self.assertIn('native', ex['unit']); self.assertEqual(ex['gaining_reaches'], [1]); self.assertEqual(ex['losing_reaches'], [2])
        ex = self.parser(recs).get_stream_aquifer_exchange(length_unit_m=1, time_unit_seconds=1)
        self.assertEqual(ex['unit'], 'm3/day'); self.assertEqual(ex['exchange'], [2. * 86400, -3. * 86400])
        with self.assertRaises(ValueError):
            self.parser(recs).get_stream_aquifer_exchange(length_unit_m=1)
        with self.assertRaises(ValueError):
            self.parser(self.outflow([(1, 0, -1.)])).get_stream_aquifer_exchange()

    def test_exchange_export_never_writes_missing_as_zero(self):
        recs = [(1, 1, 1., 'GWF', [(1, 5, 2.), (2, 6, -1.)]), (2, 1, 2., 'GWF', [(1, 5, 2.)])]
        out = os.path.join(self.tmp.name, 'ex.csv')
        with self.assertRaises(ValueError):
            self.parser(recs).export_exchange_csv(out)
        good = [(1, 1, 1., 'GWF', [(1, 5, 2.)]), (2, 1, 2., 'GWF', [(1, 5, 4.)])]
        self.parser(good).export_exchange_csv(out, length_unit_m=1, time_unit_seconds=86400)
        lines = Path(out).read_text().splitlines()
        self.assertEqual(lines[0], '# unit: m3/day'); self.assertEqual(lines[1], 'time,reach_1_exchange')
        self.assertEqual(lines[2:], ['1.000000,2.000000', '2.000000,4.000000'])

    def test_entire_missing_record_fails(self):
        # GWF saved at step 1 only, EXT-OUTFLOW at both: step 2 GWF is lost data.
        recs = [(1, 1, 1., 'GWF', [(1, 5, 2.)]), (1, 1, 1., 'EXT-OUTFLOW', [(1, 0, -1.)]),
                (2, 1, 2., 'EXT-OUTFLOW', [(1, 0, -1.)])]
        out = os.path.join(self.tmp.name, 'ex.csv')
        with self.assertRaises(ValueError):
            self.parser(recs).export_exchange_csv(out)
        self.assertFalse(os.path.exists(out))
        with self.assertRaises(ValueError):
            self.parser(recs).get_stream_aquifer_exchange()
        rev = [(1, 1, 1., 'EXT-OUTFLOW', [(1, 0, -1.)]), (1, 1, 1., 'GWF', [(1, 5, 2.)]),
               (2, 1, 2., 'GWF', [(1, 5, 2.)])]
        with self.assertRaises(ValueError):
            self.parser(rev).outlet_flow_time_series([1], length_unit_m=1, time_unit_seconds=1)

    def test_empty_gwf_record_is_valid_no_connection(self):
        recs = [(1, 1, 1., 'GWF', []), (2, 1, 2., 'GWF', [])]
        ex = self.parser(recs).get_stream_aquifer_exchange()
        self.assertEqual(ex['reaches'], []); self.assertEqual(ex['n_connected_reaches'], 0)
        self.assertEqual(ex['total_exchange'], 0.); self.assertIsNone(ex['max_gain'])
        out = os.path.join(self.tmp.name, 'ex.csv'); self.parser(recs).export_exchange_csv(out)
        self.assertEqual(Path(out).read_text().splitlines()[1:], ['time', '1.000000', '2.000000'])

    def test_single_row_observation_csv(self):
        obs = os.path.join(self.tmp.name, 'o.csv'); Path(obs).write_text('time,stage\n1.0,2.5\n')
        self.assertEqual(m.SFROutputParser(obs_file=obs).summary()['observations']['nrecords'], 1)

    def test_missing_input_files_fail(self):
        missing = os.path.join(self.tmp.name, 'nope.sfr.stg')
        for kw in ['stage_file', 'budget_file', 'listing_file', 'obs_file']:
            with self.subTest(kw=kw), self.assertRaises(FileNotFoundError):
                m.SFROutputParser(**{kw: missing})

    def test_filter_math_and_missing_values(self):
        np.testing.assert_allclose(m.lyne_hollick_baseflow([2., 4., 2.], alpha=.5, passes=1), [2., 2.5, 2.])
        # recession then rise: clipped state must feed the next step
        np.testing.assert_allclose(m.lyne_hollick_baseflow([10., 1., 2.], alpha=.5, passes=1), [10., 1., 1.25])
        np.testing.assert_array_equal(m.lyne_hollick_baseflow([2., 2., 2.], alpha=.925, passes=3), [2., 2., 2.])
        for data in [[1, np.nan, 2], [1, -1, 2], [1, np.inf, 2]]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                m.lyne_hollick_baseflow(data, alpha=.925, passes=3)
        for alpha, passes in [(1, 3), (-1, 3), (.925, 0), (.925, 1.5)]:
            with self.subTest(alpha=alpha, passes=passes), self.assertRaises(ValueError):
                m.lyne_hollick_baseflow([1, 2, 1], alpha=alpha, passes=passes)


if __name__ == '__main__':
    unittest.main()
