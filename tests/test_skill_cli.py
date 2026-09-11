"""Execute the built standalone CLI against real media and separate history."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from scripts.build_skill import build
from tests.fixtures import MediaServer
from native.config import tool

class SkillCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name).resolve()
        cls.package,_=build(cls.root/'package');cls.cli=cls.package/'scripts/cli.py'
        cls.server=MediaServer(cls.root/'fixtures')
    @classmethod
    def tearDownClass(cls):cls.server.close();cls.temp.cleanup()
    def setUp(self):
        self.case=Path(tempfile.mkdtemp(dir=self.root)).resolve();self.data=self.case/'data';self.data.mkdir()
        (self.data/'tools.json').write_text(json.dumps({k:tool(k) for k in ('ffmpeg','ffprobe','node','yt-dlp')}))
        self.env={**os.environ,'STASH_SKILL_HOME':str(self.data),'PYTHONNOUSERSITE':'1','STASH_DATA_DIR':str(self.case/'must-not-touch-chrome')}
        self.out=self.case/'out';self.command=[sys.executable,'-I',str(self.cli)]
    def run_cli(self,*args,ok=True):
        result=subprocess.run([*self.command,*args],env=self.env,capture_output=True,text=True,timeout=90)
        value=json.loads(result.stdout)
        self.assertEqual(value['ok'],ok,result.stderr+result.stdout)
        self.assertEqual(result.returncode,0 if ok else 1)
        return value
    def download(self,*extra,url=None,ok=True):
        return self.run_cli('download',url or self.server.url+'/sample.mp4','--folder',str(self.out),*extra,ok=ok)
    def test_actual_mp4_mp3_dedupe_conflict_and_file_preserving_delete(self):
        first=self.download('--request-id','dedupe-1234')['job'];path=Path(first['result']['path'])
        self.assertEqual(first['verification']['decodeExitCode'],0)
        self.assertEqual(first['verification']['sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual({s['codec_name'] for s in first['result']['streams']},{'h264','aac'})
        again=self.download('--request-id','dedupe-1234');self.assertTrue(again['duplicate']);self.assertEqual(first['jobId'],again['job']['jobId'])
        conflict=self.download('--request-id','dedupe-1234','--format','mp3',ok=False);self.assertEqual(conflict['error']['code'],'REQUEST_CONFLICT')
        audio=self.download('--format','mp3')['job'];self.assertEqual(audio['result']['container'],'mp3');self.assertEqual({s['codec_name'] for s in audio['result']['streams']},{'mp3'})
        self.run_cli('delete',first['jobId']);self.assertTrue(path.is_file());self.assertEqual(len(self.run_cli('list')['jobs']),1)
        self.assertFalse((self.case/'must-not-touch-chrome').exists())
    def test_changed_file_not_opened_failed_retry_and_url_validation(self):
        first=self.download()['job'];Path(first['result']['path']).write_bytes(b'replaced')
        self.assertEqual(self.run_cli('play',first['jobId'],ok=False)['error']['code'],'FILE_CHANGED')
        failure=self.download(url=self.server.url+'/not-found.mp4',ok=False)['job'];self.assertEqual(failure['state'],'failed')
        retry=self.run_cli('retry',failure['jobId'],'--request-id','retry-12345',ok=False)['job'];self.assertEqual(retry['retryOf'],failure['jobId']);self.assertNotEqual(retry['jobId'],failure['jobId'])
        self.assertEqual(self.download(url='file:///etc/passwd',ok=False)['error']['code'],'INVALID_URL')
        self.assertEqual(self.run_cli('list','--status','failed')['total'],2)
    def test_busy_cancel_and_interrupted_owner_recovery(self):
        def start():
            log=(self.case/'progress.log').open('w')
            p=subprocess.Popen([*self.command,'download',self.server.url+'/slow.mp4','--folder',str(self.out)],env=self.env,stdout=subprocess.PIPE,stderr=log,text=True)
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                jobs=self.run_cli('list','--status','active')['jobs']
                if jobs:return p,log,jobs[0]['jobId']
                time.sleep(.1)
            p.kill();p.wait();log.close();self.fail('download never started')
        p,log,job_id=start()
        try:
            self.assertEqual(self.download(ok=False)['error']['code'],'DOWNLOAD_BUSY')
            self.assertEqual(self.run_cli('delete',job_id,ok=False)['error']['code'],'JOB_ACTIVE')
            self.run_cli('cancel',job_id);stdout,_=p.communicate(timeout=15);self.assertEqual(json.loads(stdout)['job']['state'],'cancelled')
        finally:
            if p.poll() is None:p.kill();p.wait()
            log.close()
        p,log,job_id=start()
        p.kill();p.wait(timeout=10);p.stdout.close();log.close()
        self.assertEqual(self.run_cli('status',job_id)['job']['state'],'interrupted')
        self.assertEqual(self.download()['job']['state'],'completed')

if __name__=='__main__':unittest.main()
