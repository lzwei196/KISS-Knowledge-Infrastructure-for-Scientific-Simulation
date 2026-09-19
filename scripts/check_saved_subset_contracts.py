"""Run the current Desktop content checks on already-downloaded audit files.

No network, credentials, model execution, or modification of scientific files.
The historical audit includes intentionally retained bad cached outputs.
"""
from collections import Counter
import json
from pathlib import Path

from kiss_cli import data_contract, obs_access


def main():
    results = []
    for batch in ('audit', 'retest', 'fresh'):
        root = Path(f'output/geodata-subset-{batch}-2026-09-14')
        for name in ('raster-downloads.json', 'netcdf-downloads.json'):
            source = root / name
            if not source.exists():
                continue
            for row in json.loads(source.read_text()).get('items', []):
                known = {Path(f['path']).name: f for f in row.get('files', []) if f.get('path')}
                folder = root / 'rasters' / row['dataset_id']
                paths = sorted(folder.glob('*')) if folder.is_dir() else []
                for path in paths:
                    if not path.is_file():
                        continue
                    part = {**known.get(path.name, {}).get('manifest', {}), 'name': path.name}
                    result = {'batch': batch, 'dataset_id': row['dataset_id'], 'file': str(path)}
                    try:
                        result['inspection'] = data_contract.inspect_native_files(folder, row['request'], [part])
                        result['status'] = result['inspection']['status']
                    except ValueError as error:
                        result.update(status='rejected', reason=str(error))
                    results.append(result)
    report = {'mode': 'offline content checks; not new acquisitions or scientific model readiness',
              'counts': dict(Counter(r['status'] for r in results)), 'items': results}
    obs_access._atomic_json(Path('output/geodata-strategy-audit-2026-09-14/native-file-checks.json'), report)
    print(json.dumps({'counts': report['counts'], 'rejections': [r for r in results if r['status'] == 'rejected']}, indent=2))


if __name__ == '__main__':
    main()
