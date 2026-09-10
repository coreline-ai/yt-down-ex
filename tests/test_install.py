import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.install import install,uninstall,rollback,run_diagnose,preflight
from native.protocol import read_message,write_message
WHEELS=Path('artifacts/wheels').resolve()

class InstallTests(unittest.TestCase):
    def setUp(self):
        if not WHEELS.exists() or len(list(WHEELS.glob('*.whl')))<2:raise RuntimeError('npm run setup:tests 실행 후 오프라인 설치 테스트를 실행하세요.')
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name).resolve();self.root=self.base/'한글 설치 폴더';self.browser=self.base/'브라우저 프로필'
    def tearDown(self):self.temp.cleanup()
    def test_lifecycle_and_native_protocol(self):
        result=install(self.root,self.browser,WHEELS if WHEELS.exists() else None)
        proc=subprocess.Popen([str(self.root/'host'),f"chrome-extension://{result['extensionId']}/"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            write_message(proc.stdin,{'protocolVersion':1,'requestId':'test','type':'hello','payload':{}})
            self.assertTrue(read_message(proc.stdout)['ok'])
            proc.stdin.close();self.assertEqual(proc.wait(timeout=10),0)
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
            if not proc.stdin.closed:proc.stdin.close()
            proc.stdout.close();proc.stderr.close()
        old=json.loads((self.root/'active.json').read_text())
        install(self.root,self.browser,WHEELS if WHEELS.exists() else None)
        self.assertNotEqual(json.loads((self.root/'active.json').read_text()),old)
        rollback(self.root);self.assertEqual(json.loads((self.root/'active.json').read_text()),old)
        self.assertTrue(run_diagnose(self.root)['ready'])
        before=(self.root/'active.json').read_bytes()
        with patch('scripts.install.run_diagnose',side_effect=RuntimeError('fault injection')):
            with self.assertRaises(RuntimeError):install(self.root,self.browser,WHEELS if WHEELS.exists() else None)
        self.assertEqual((self.root/'active.json').read_bytes(),before)
        sample=self.base/'downloads'/'preserve.mp4';sample.parent.mkdir();sample.write_bytes(b'preserve')
        uninstall(self.root);self.assertEqual(sample.read_bytes(),b'preserve');self.assertFalse(Path(result['manifest']).exists())
        install(self.root,self.browser,WHEELS if WHEELS.exists() else None);uninstall(self.root)
    def test_missing_dependency_and_foreign_directory(self):
        with patch('scripts.install.shutil.which',return_value=None):
            with self.assertRaises(RuntimeError):preflight()
        self.root.mkdir();(self.root/'unrelated').write_text('keep')
        with self.assertRaises(RuntimeError):uninstall(self.root)
        self.assertEqual((self.root/'unrelated').read_text(),'keep')
    def test_optional_js_runtime_and_missing_binary_diagnosis(self):
        from native.host import diagnose
        from native.config import tool,AppError
        def missing(name):
            if name in ('node','ffprobe'):raise AppError('DEPENDENCY_MISSING','missing')
            return tool(name)
        with patch('native.host.tool',side_effect=missing):
            result=diagnose()
        self.assertFalse(result['tools']['node']['ok']);self.assertFalse(result['ready'])
