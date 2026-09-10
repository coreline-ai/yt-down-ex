import fcntl
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from native.config import AppError
from native.update import catalog,check_update,download_wheel,execute,get_status,start_update,atomic_json,serve_during_update
from scripts.install import install,rollback,validate_database

WHEELS=Path('artifacts/wheels').resolve()
class UpdateTests(unittest.TestCase):
    def test_official_metadata_comparison_and_unknown_latest(self):
        c=catalog();current={'tools':{'yt-dlp':{'version':c['packages'][0]['version']}},'ejs':c['packages'][1]['version']}
        def fetch(url):
            item=next(p for p in c['packages'] if '/'+p['name']+'/' in url)
            return {'info':{'version':item['version']},'urls':[{'filename':item['filename'],'digests':{'sha256':item['sha256']}}]}
        self.assertEqual(check_update(current,fetch)['status'],'up_to_date')
        self.assertEqual(check_update({},fetch)['status'],'available')
        def newer(url):
            data=fetch(url);data['info']['version']='2099.1.1';return data
        self.assertTrue(check_update(current,newer)['unverifiedLatest'])
        self.assertEqual(check_update(current,lambda _:(_ for _ in ()).throw(OSError()))['status'],'offline')
        self.assertEqual(check_update(current,lambda _: {'urls':[],'info':{'version':'0'}})['status'],'hash_mismatch')

    def test_download_hash_and_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            item={'url':'https://example.invalid','sha256':hashlib.sha256(b'correct').hexdigest()}
            with self.assertRaises(AppError) as e:download_wheel(item,Path(tmp)/'bad',lambda *a,**k:io.BytesIO(b'bad'))
            self.assertEqual(e.exception.code,'UPDATE_HASH_MISMATCH')
            download_wheel(item,Path(tmp)/'good',lambda *a,**k:io.BytesIO(b'correct'))
            self.assertEqual((Path(tmp)/'good').read_bytes(),b'correct')

    def test_staged_install_failures_rollback_and_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp).resolve();root=base/'engine';browser=base/'browser'
            install(root,browser,WHEELS);before=(root/'active.json').read_bytes()
            with sqlite3.connect(root/'jobs.sqlite3') as db:
                db.execute('PRAGMA user_version=1');db.execute('CREATE TABLE preserved (data TEXT)');db.execute('INSERT INTO preserved VALUES (?)',('이어보기 설정',))
            file=base/'keep.mp4';file.write_bytes(b'original media');db_before=(root/'jobs.sqlite3').read_bytes()
            self.assertIsNotNone(execute(root,'install','success',wheel_dir=WHEELS));self.assertEqual(get_status(root)['state'],'completed')
            after=(root/'active.json').read_bytes();self.assertNotEqual(before,after)
            rollback(root);self.assertEqual(json.loads((root/'active.json').read_text()),json.loads(before))
            for target in ['scripts.install.run_diagnose','scripts.install.venv.EnvBuilder.create']:
                active=(root/'active.json').read_bytes()
                with patch(target,side_effect=RuntimeError('injected')):
                    self.assertIsNone(execute(root,'install','failure',wheel_dir=WHEELS))
                self.assertEqual(get_status(root)['state'],'failed');self.assertEqual((root/'active.json').read_bytes(),active)
            bad=base/'bad-wheels';bad.mkdir()
            for item in catalog()['packages']:(bad/item['filename']).write_bytes(b'corrupt')
            self.assertIsNone(execute(root,'install','hash',wheel_dir=bad));self.assertEqual((root/'active.json').read_bytes(),before)
            self.assertEqual(file.read_bytes(),b'original media');self.assertEqual((root/'jobs.sqlite3').read_bytes(),db_before)
            with sqlite3.connect(root/'jobs.sqlite3') as db:db.execute('PRAGMA user_version=999')
            with self.assertRaises(RuntimeError):rollback(root)

    def test_lock_duplicate_progress_proxy_and_interruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'active.json').write_text('{}')
            with (root/'update.lock').open('a+') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(AppError) as e:start_update(root)
                self.assertEqual(e.exception.code,'UPDATE_BUSY')
                atomic_json(root/'update-status.json',{'state':'installing','pid':os.getpid(),'message':'install'})
                messages=iter([{'protocolVersion':1,'type':'getUpdateStatus','requestId':'1'},None]);replies=[]
                self.assertTrue(serve_during_update(root,lambda:next(messages),replies.append));self.assertEqual(replies[0]['payload']['state'],'installing');self.assertFalse((root/'host.lock').exists())
            with patch('native.update.os.kill',side_effect=ProcessLookupError):self.assertEqual(get_status(root)['state'],'interrupted')
            with self.assertRaises(RuntimeError):validate_database(root,{'protocolVersion':2})

    def test_updater_killed_during_diagnosis_keeps_active(self):
        import subprocess,sys
        from tests.test_jobs import wait_for
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp).resolve();root=base/'engine';install(root,base/'browser',WHEELS)
            before=(root/'active.json').read_bytes();marker=base/'diagnosing'
            script='''import time
from pathlib import Path
from unittest.mock import patch
from native.update import execute
import sys
def blocked(*args):
    Path(sys.argv[3]).write_text('ready')
    time.sleep(30)
with patch('scripts.install.run_diagnose',blocked):
    execute(Path(sys.argv[1]),'install','killed',wheel_dir=Path(sys.argv[2]))
'''
            process=subprocess.Popen([sys.executable,'-c',script,str(root),str(WHEELS),str(marker)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                wait_for(marker.exists,30);process.kill();process.wait(timeout=5)
                self.assertEqual((root/'active.json').read_bytes(),before);self.assertEqual(get_status(root)['state'],'interrupted')
            finally:
                if process.poll() is None:process.kill();process.wait()
