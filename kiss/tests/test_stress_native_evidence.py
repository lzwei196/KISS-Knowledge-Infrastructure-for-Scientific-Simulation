import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('stress_evidence', Path(__file__).resolve().parents[2]/'tools/deepseek_ki_stress.py')
stress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stress)


class NativeEvidenceTests(unittest.TestCase):
    def test_known_receipt_and_product_hash_retained(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)/'install'; evidence = Path(td)/'evidence'
            source = root/'binaries/PHREEQC/source/phreeqc-3.8.6-17100'
            binary = source/'build/phreeqc'
            binary.parent.mkdir(parents=True); binary.write_bytes(b'identity fixture')
            (source/'macos-build-receipt.json').write_text('{"source_changes": {}}')
            (root/'installation-test.json').write_text(json.dumps({'binary': str(binary)}))
            stress.preserve_native_evidence(root,evidence,'PHREEQC')
            record=json.loads((evidence/'native-product.json').read_text())
            self.assertEqual(record['sha256'],hashlib.sha256(binary.read_bytes()).hexdigest())
            self.assertEqual(record['size_bytes'],binary.stat().st_size)
            self.assertEqual((evidence/'helper-macos-build-receipt.json').read_text(),'{"source_changes": {}}')

    def test_outside_workspace_product_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'install'; root.mkdir(); evidence=Path(td)/'evidence'
            outside=Path(td)/'external'; outside.write_bytes(b'outside')
            link=root/'linked'; link.symlink_to(outside)
            for binary in [outside, link]:
                (root/'installation-test.json').write_text(json.dumps({'binary':str(binary)}))
                stress.preserve_native_evidence(root,evidence,'PHREEQC')
                self.assertFalse(evidence.exists())

    def test_known_receipt_symlink_is_not_collected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'install'; evidence=Path(td)/'evidence'
            source=root/'binaries/PHREEQC/source/phreeqc-3.8.6-17100'
            binary=source/'build/phreeqc'
            binary.parent.mkdir(parents=True); binary.write_bytes(b'identity fixture')
            settings=root/'settings'; settings.write_text('unrelated configuration')
            (source/'macos-build-receipt.json').symlink_to(settings)
            (root/'installation-test.json').write_text(json.dumps({'binary':str(binary)}))
            stress.preserve_native_evidence(root,evidence,'PHREEQC')
            self.assertTrue((evidence/'native-product.json').is_file())
            self.assertFalse((evidence/'helper-macos-build-receipt.json').exists())
