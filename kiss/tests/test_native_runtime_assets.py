from pathlib import Path
import tempfile
import hashlib
import unittest
from unittest.mock import patch
from kiss_cli.native_probe import stage_runtime_assets, telemac_case_boundary, TELEMAC_DICO_SHA256

FIXTURE = b'unit test dictionary bytes; never used by a model'
FIXTURE_SHA = hashlib.sha256(FIXTURE).hexdigest()
BANNER = '                        2D    VERSION 9.1    FORTRAN 2003       \n'
CASE = "Fortran runtime error: Cannot open file 'T2DCAS': No such file or directory"

class NativeAssetsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / 'source'
        self.src.write_bytes(FIXTURE)
        registry = patch("kiss_cli.native_probe.AUDITED_ASSETS", {"TELEMAC_MASCARET":{"T2DDICO":FIXTURE_SHA}})
        registry.start()
        self.addCleanup(registry.stop)
        self.dst = self.root / 'probe'
        self.dst.mkdir()
        self.asset = {'source':'source','target':'T2DDICO','sha256':FIXTURE_SHA}

    def stage(self):
        return stage_runtime_assets({'runtime_assets':[self.asset]}, self.root, self.dst, 'TELEMAC_MASCARET')

    def test_original_dictionary_and_only_dictionary(self):
        receipt = self.stage()
        self.assertEqual(self.src.read_bytes(), (self.dst/'T2DDICO').read_bytes())
        self.assertEqual([p.name for p in self.dst.iterdir()], ['T2DDICO'])
        self.assertEqual(receipt, [self.asset])
        self.assertTrue(telemac_case_boundary('TELEMAC_MASCARET', BANNER+CASE, 2, [{'target':'T2DDICO','sha256':TELEMAC_DICO_SHA256}]))

    def test_rejects_unsafe_paths_hashes_and_scientific_inputs(self):
        for key,value in [('source','../source'),('source',str(self.src)),('target','../T2DDICO'),('target','T2DCAS'),('target','CONFIG'),('target','a/b'),('sha256','0'*64)]:
            with self.subTest(key=key,value=value):
                old = self.asset[key]
                self.asset[key] = value
                with self.assertRaises(ValueError): self.stage()
                self.asset[key] = old
        self.src.write_bytes(b'corrupt')
        with self.assertRaises(ValueError): self.stage()
        self.assertFalse(list(self.dst.iterdir()))

    def test_rejects_symlink_directory_and_nonempty_destination(self):
        self.src.unlink()
        self.src.symlink_to(self.dst)
        with self.assertRaises(ValueError): self.stage()
        self.src.unlink()
        self.src.mkdir()
        with self.assertRaises(ValueError): self.stage()
        (self.dst/'T2DCAS').write_text('case')
        with self.assertRaises(ValueError): self.stage()

    def test_negative_case_boundaries(self):
        receipt = [{'target':'T2DDICO','sha256':TELEMAC_DICO_SHA256}]
        for model,output,rc,assets in [
            ('OTHER',BANNER+CASE,2,receipt),('TELEMAC_MASCARET',BANNER+CASE,-11,receipt),
            ('TELEMAC_MASCARET',BANNER+CASE,2,[]),
            ('TELEMAC_MASCARET',BANNER.replace('9.1','9.2')+CASE,2,receipt),
            ('TELEMAC_MASCARET',BANNER+CASE.replace('T2DCAS','T2DDICO'),2,receipt),
            ('TELEMAC_MASCARET',BANNER+CASE+'\ndyld: Library not loaded',2,receipt)]:
            with self.subTest(model=model,output=output,rc=rc):
                self.assertFalse(telemac_case_boundary(model,output,rc,assets))

    def test_verifier_stages_only_runtime_and_retains_receipt(self):
        from types import SimpleNamespace
        import subprocess
        import platform
        from kiss_cli import runnable
        binary = self.root/'telemac2d'
        binary.write_bytes(b'test executable shape is mocked')
        binary.chmod(0o755)
        ki = SimpleNamespace(name='TELEMAC_MASCARET',root=self.root/'ki',meta={'language':'Fortran'})
        cfg = SimpleNamespace(root=self.root,python='/usr/bin/python3')
        man = SimpleNamespace(native_probe={'runtime_assets':[self.asset]})
        def execute(argv, **kwargs):
            cwd = Path(kwargs['cwd'])
            self.assertEqual([p.name for p in cwd.iterdir()], ['T2DDICO'])
            self.assertEqual((cwd/'T2DDICO').read_bytes(), FIXTURE)
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
            return subprocess.CompletedProcess(argv,2,BANNER+CASE,'')
        with patch.object(runnable,'declared_imports',return_value=[]), patch.object(runnable,'_package_module',return_value=''), patch.object(runnable,'select_python',return_value='/usr/bin/python3'), patch('kiss_cli.paths.with_ki_tools_common',return_value={}), patch.object(runnable,'find_binary',return_value=binary), patch.object(runnable,'_file_kind',return_value={'Darwin':'macho','Linux':'elf','Windows':'pe'}[platform.system()]), patch.object(runnable,'_missing_libs',return_value=[]), patch('kiss_cli.native_probe.TELEMAC_DICO_SHA256',FIXTURE_SHA), patch.object(runnable.subprocess,'run',side_effect=execute):
            verdict = runnable.check(ki,man,cfg)
        self.assertTrue(verdict.usable, verdict.detail)
        self.assertEqual(verdict.probe_runtime_assets,[self.asset])
