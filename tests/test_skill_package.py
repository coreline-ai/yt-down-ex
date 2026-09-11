"""Standalone packaging and execution boundary regressions."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from scripts.build_skill import build

class SkillPackageTests(unittest.TestCase):
    def test_standalone_bundle_has_no_chrome_host_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);package,archive=build(root/'bundle')
            self.assertTrue(archive.is_file())
            self.assertFalse((package/'scripts/engine/native/host.py').exists())
            for line in (package/'SHA256SUMS').read_text().splitlines():
                digest,name=line.split('  ',1)
                self.assertEqual(hashlib.sha256((package/name).read_bytes()).hexdigest(),digest)
            (package/'SKILL.md').write_text('tampered')
            result=subprocess.run(['/bin/bash',str(package/'install.sh')],env={**os.environ,'CODEX_HOME':str(root/'codex')},capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((root/'codex/skills/stash-media').exists())

if __name__=='__main__':unittest.main()
