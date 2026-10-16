"""Tiny 3-day Pywr runs: m3/s inputs must move m3/s x 86400 per day in storage,
and run_pywr.py must write real m3/s back out."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

KI = Path(os.environ.get('KI_UNDER_TEST', Path(__file__).resolve().parents[1]))
ASSEMBLE = KI / 'tools/s7_assembly/assemble_pywr_model.py'
RUN = KI / 'tools/s8_execution/run_pywr.py'

try:
    import pywr  # noqa: F401
    HAVE_PYWR = True
except ImportError:
    HAVE_PYWR = False


class FlowUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        r = Path(self.tmp.name)
        self.r = r
        (r/'res.json').write_text(json.dumps({
            'name': 'R', 'geometry': {'dam_height_m': 10},
            'storage': {'max_volume_m3': 1e9, 'min_volume_m3': 0,
                        'initial_volume_m3': 1e6, 'max_volume_mcm': 1000}}))
        (r/'in.csv').write_text('date,inflow_m3s\n2000-01-01,1\n2000-01-02,1\n2000-01-03,1\n')
        # Industrial demand node carries a plain-number max_flow in m3/s.
        (r/'dem.json').write_text(json.dumps({'demands': [{'name': 'ind', 'pywr_node': {
            'name': 'ind', 'type': 'Output', 'max_flow': 2.0, 'cost': -1000}}]}))

    def assemble(self):
        proc = subprocess.run([sys.executable, str(ASSEMBLE), '--reservoir_json', str(self.r/'res.json'),
                               '--inflow_csv', str(self.r/'in.csv'), '--demands_json', str(self.r/'dem.json'),
                               '--start_date', '2000-01-01', '--end_date', '2000-01-03',
                               '--output', str(self.r/'m.json')], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads((self.r/'m.json').read_text())

    def test_assembly_scales_literal_demand_and_marks_units(self):
        model = self.assemble()
        self.assertEqual(model['metadata']['flow_units'], 'm3/day')
        ind = [n for n in model['nodes'] if n['name'] == 'ind'][0]
        self.assertEqual(ind['max_flow'], 2.0 * 86400)

    @unittest.skipUnless(HAVE_PYWR, 'pywr not installed')
    def test_run_mass_balance_and_m3s_output(self):
        self.assemble()
        out = self.r/'out'
        proc = subprocess.run([sys.executable, str(RUN), '--model', str(self.r/'m.json'),
                               '--output_dir', str(out)], capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        storage = pd.read_csv(out/'storage_timeseries.csv')['R_volume_m3'].tolist()
        # 1 m3/s in, 2 m3/s out -> -86400 m3 per day.
        self.assertEqual(storage, [1e6 - 86400, 1e6 - 2*86400, 1e6 - 3*86400])
        flows = pd.read_csv(out/'release_timeseries.csv')
        self.assertEqual(flows['ind_m3s'].tolist(), [2.0, 2.0, 2.0])
        summary = json.loads((out/'summary.json').read_text())
        self.assertEqual(summary['flow_units_in_model'], 'm3/day')

    @unittest.skipUnless(HAVE_PYWR, 'pywr not installed')
    def test_two_day_timestep_string(self):
        model = self.assemble()
        model['timestepper']['timestep'] = '2D'
        model['timestepper']['end'] = '2000-01-04'
        (self.r/'in.csv').write_text('date,inflow_m3s\n' + ''.join(
            f'2000-01-0{d},1\n' for d in range(1, 5)))
        (self.r/'m2d.json').write_text(json.dumps(model))
        out = self.r/'out2d'
        proc = subprocess.run([sys.executable, str(RUN), '--model', str(self.r/'m2d.json'),
                               '--output_dir', str(out)], capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        storage = pd.read_csv(out/'storage_timeseries.csv')
        self.assertEqual(storage['date'].tolist(), ['2000-01-01', '2000-01-03'])
        # net -1 m3/s over 2-day steps -> -172800 m3 per step
        self.assertEqual(storage['R_volume_m3'].tolist(), [1e6 - 172800, 1e6 - 2*172800])
        summary = json.loads((out/'summary.json').read_text())
        # 2 m3/s for 4 days = 0.6912 Mm3
        self.assertEqual(summary['statistics']['flows']['ind_m3s']['total_volume_mcm'], 0.7)
        self.assertEqual(summary['simulation']['timestep_days_max'], 2.0)

    def test_run_without_flow_units_stops(self):
        model = self.assemble()
        del model['metadata']['flow_units']
        (self.r/'m2.json').write_text(json.dumps(model))
        proc = subprocess.run([sys.executable, str(RUN), '--model', str(self.r/'m2.json'),
                               '--output_dir', str(self.r/'out2')], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn('flow units unknown', proc.stdout)


if __name__ == '__main__':
    unittest.main()
