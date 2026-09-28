import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from kiss_cli.native_probe import ctsm_case_boundary

class CTSMStartupTests(unittest.TestCase):
    def test_exact_case_boundary_requires_native_source_identity_and_no_other_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve();b=root/'CTSM/ki-build/cesm.exe';b.parent.mkdir(parents=True);b.touch()
            source=root/'CTSM/components/cmeps/cesm/driver/esmApp.F90';source.parent.mkdir(parents=True);source.write_text('audited test driver')
            out=f"At line 54 of file {source}\nFortran runtime error: Cannot open file 'drv_in': No such file or directory\nError termination. Backtrace:"
            self.assertFalse(ctsm_case_boundary('CLM5___CTSM',b,root,out,2))
            with patch('kiss_cli.native_probe.CTSM_DRIVER_SHA256',hashlib.sha256(source.read_bytes()).hexdigest()):
                self.assertTrue(ctsm_case_boundary('CLM5___CTSM',b,root,out,2))
                for bad in [out.replace('drv_in','missing_library'),out.replace('line 54','line 55'),out+'\ndyld: Library not loaded',out+'\nFortran runtime error: other failure']:
                    self.assertFalse(ctsm_case_boundary('CLM5___CTSM',b,root,bad,2))
                self.assertFalse(ctsm_case_boundary('OTHER',b,root,out,2))
                self.assertFalse(ctsm_case_boundary('CLM5___CTSM',b,root,out,-11))
                self.assertFalse(ctsm_case_boundary('CLM5___CTSM',b,root/'elsewhere',out,2))
                source.unlink();source.symlink_to(b)
                self.assertFalse(ctsm_case_boundary('CLM5___CTSM',b,root,out,2))

    def test_fates_requires_its_own_host_build_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            binary = root / 'FATES/ki-fates-build/cesm.exe'
            binary.parent.mkdir(parents=True)
            binary.touch()
            source = root / 'FATES/components/cmeps/cesm/driver/esmApp.F90'
            source.parent.mkdir(parents=True)
            source.write_text('audited test driver')
            output = f"At line 54 of file {source}\nFortran runtime error: Cannot open file 'drv_in': No such file or directory"
            self.assertFalse(ctsm_case_boundary('FATES', binary, root, output, 2))
            with patch('kiss_cli.native_probe.CTSM_DRIVER_SHA256', hashlib.sha256(source.read_bytes()).hexdigest()):
                self.assertTrue(ctsm_case_boundary('FATES', binary, root, output, 2))
                self.assertFalse(ctsm_case_boundary('CLM5___CTSM', binary, root, output, 2))
                self.assertFalse(ctsm_case_boundary('FATES', binary, root, output, -11))
                self.assertFalse(ctsm_case_boundary('FATES', binary, root, output + '\ndyld: Library not loaded', 2))
