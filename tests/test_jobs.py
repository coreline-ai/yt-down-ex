import errno
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from native.config import AppError
from native.jobs import Jobs
from native.protocol import read_message,write_message
from tests.fixtures import MediaServer

def wait_for(check,timeout=15):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=check()
        if value:return value
        time.sleep(.04)
    raise AssertionError('Timed out waiting for job')

class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.manager=None
    def tearDown(self):
        if self.manager:self.manager.close()
        self.temp.cleanup()
    def create(self):self.manager=Jobs(self.root/'state');return self.manager
    def payload(self,url='https://example.org/sample.mp4'):
        return {'url':url,'folder':str(self.root/'output')}
    @staticmethod
    def block(runner,*args):
        runner.cancelled.wait(10)
        raise AppError('CANCELLED','cancelled')
    def test_dedup_queue_limit_cancel_and_late_event(self):
        with patch('native.jobs.Runner.download',self.block):
            m=self.create();first=m.enqueue(self.payload(),'same')
            self.assertEqual(m.enqueue(self.payload(),'same')['jobId'],first['jobId'])
            for _ in range(19):m.enqueue(self.payload(),uuid.uuid4().hex)
            with self.assertRaises(AppError) as e:m.enqueue(self.payload(),'overflow')
            self.assertEqual(e.exception.code,'QUEUE_FULL')
            m.cancel(first['jobId']);m._update(first['jobId'],{'state':'completed'})
            self.assertEqual(m.get(first['jobId'])['state'],'cancelled')
    def test_lock_and_restart_recovery(self):
        with patch('native.jobs.Runner.download',self.block):
            m=self.create();job=m.enqueue(self.payload(),'a')
            with self.assertRaises(AppError):Jobs(self.root/'state')
            m.close();self.manager=None
            m=self.create();self.assertEqual(m.get(job['jobId'])['state'],'interrupted')
    def test_disk_full_failure(self):
        with patch('native.jobs.Runner.download',side_effect=OSError(errno.ENOSPC,'full')):
            m=self.create();job=m.enqueue(self.payload(),'a')
            result=wait_for(lambda:next((j for j in m.snapshot()['jobs'] if j['state']=='failed'),None))
            self.assertEqual(result['error']['code'],'DISK_FULL')
    def test_db_failure_does_not_accept_job(self):
        m=self.create()
        m.db.execute('PRAGMA query_only=ON')
        with self.assertRaises(Exception):m.enqueue(self.payload(),'a')
        self.assertEqual(m.snapshot()['total'],0)
        m.db.execute('PRAGMA query_only=OFF')
    def test_delete_terminal_history_persists_and_preserves_file(self):
        with patch('native.jobs.Runner.download',side_effect=AppError('DOWNLOAD_FAILED','failed')):
            m=self.create();job=m.enqueue(self.payload(),'delete')
            wait_for(lambda:m.get(job['jobId'])['state']=='failed' and m.active is None)
            file=self.root/'output'/'keep.mp4';file.write_bytes(b'keep')
            events=[];m.emit=events.append
            m.delete(job['jobId'])
            self.assertEqual(m.snapshot()['total'],0)
            self.assertEqual(events[-1]['type'],'jobDeleted')
            self.assertEqual(file.read_bytes(),b'keep')
            m.close();self.manager=None;m=self.create()
            self.assertEqual(m.snapshot()['total'],0)
    def test_delete_rejects_active_job(self):
        with patch('native.jobs.Runner.download',self.block):
            m=self.create();job=m.enqueue(self.payload(),'active-delete')
            with self.assertRaises(AppError) as error:m.delete(job['jobId'])
            self.assertEqual(error.exception.code,'INVALID_STATE')
            self.assertEqual(m.snapshot()['total'],1)
    def test_snapshot_unicode_byte_budget_and_pagination(self):
        from native.protocol import MAX_MESSAGE
        m=self.create()
        for n in range(12):
            m._save({'jobId':str(n),'requestId':str(n),'state':'failed','created':n,'url':'https://example.org/'+('가'*8000),'folder':'/'+('나'*4000)})
        seen=[];offset=0
        while offset is not None:
            page=m.snapshot(offset)
            self.assertLess(len(json.dumps(page,ensure_ascii=False).encode()),MAX_MESSAGE)
            seen.extend(j['jobId'] for j in page['jobs']);offset=page['nextOffset']
        self.assertEqual(len(seen),12);self.assertEqual(len(set(seen)),12)
    def test_real_retry_and_name_conflict(self):
        server=MediaServer(self.root/'fixtures')
        try:
            m=self.create();job=m.enqueue(self.payload(server.url+'/missing.mp4'),'bad')
            wait_for(lambda:m.get(job['jobId'])['state']=='failed')
            (self.root/'fixtures'/'missing.mp4').write_bytes((self.root/'fixtures'/'sample.mp4').read_bytes())
            retry=m.retry(job['jobId'],'retry');wait_for(lambda:m.get(retry['jobId'])['state']=='completed')
            result=m.get(retry['jobId'])['result'];original=Path(result['path']).read_bytes()
            second=m.enqueue(self.payload(server.url+'/missing.mp4'),'second');wait_for(lambda:m.get(second['jobId'])['state']=='completed')
            self.assertNotEqual(result['path'],m.get(second['jobId'])['result']['path'])
            self.assertEqual(Path(result['path']).read_bytes(),original)
        finally:server.close()
    def test_runner_cancel_terminates_group(self):
        from native.engine import Runner
        cancel=threading.Event();runner=Runner(cancel);errors=[]
        def run():
            try:runner.run([sys.executable,'-c','import time;time.sleep(30)'])
            except AppError as e:errors.append(e.code)
        t=threading.Thread(target=run);t.start();wait_for(lambda:runner.process)
        pid=runner.process.pid;start=time.monotonic();cancel.set();t.join(5)
        self.assertFalse(t.is_alive());self.assertLess(time.monotonic()-start,5);self.assertEqual(errors,['CANCELLED'])
        with self.assertRaises(ProcessLookupError):os.kill(pid,0)
    def test_guard_parent_death(self):
        pidfile=self.root/'pid'
        code='from native.engine import Runner; import sys; Runner().run([sys.executable,"-c",'+repr('import os,time;open('+repr(str(pidfile))+',"w").write(str(os.getpid()));time.sleep(30)')+'])'
        parent=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            wait_for(pidfile.exists);pid=int(pidfile.read_text());parent.kill();parent.wait()
            def gone():
                try:os.kill(pid,0);return False
                except ProcessLookupError:return True
            wait_for(gone,5)
        finally:
            if parent.poll() is None:parent.kill();parent.wait()
            parent.stdout.close();parent.stderr.close()

    def test_slow_download_cancel(self):
        server=MediaServer(self.root/'fixtures')
        try:
            m=self.create();job=m.enqueue(self.payload(server.url+'/slow.mp4'),'slow')
            wait_for(lambda:m.get(job['jobId'])['state']=='downloading')
            time.sleep(.3);start=time.monotonic();m.cancel(job['jobId'])
            wait_for(lambda:m.active is None,5)
            self.assertLess(time.monotonic()-start,5)
            self.assertEqual(m.get(job['jobId'])['state'],'cancelled')
            self.assertEqual(list((self.root/'output').iterdir()),[])
        finally:server.close()

    def test_native_eof_and_kill_recovery(self):
        identity=json.loads(Path('shared/extension-id.json').read_text())['id']
        env={**os.environ,'STASH_DATA_DIR':str(self.root/'native-state')}
        server=MediaServer(self.root/'fixtures')
        try:
            for hard in (False,True):
                proc=subprocess.Popen([sys.executable,'-m','native.host',f'chrome-extension://{identity}/'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
                try:
                    write_message(proc.stdin,{'protocolVersion':1,'requestId':uuid.uuid4().hex,'type':'enqueue','payload':self.payload(server.url+'/slow.mp4')})
                    while True:
                        response=read_message(proc.stdout)
                        if response.get('type')=='jobUpdated' and response['payload']['state']=='downloading':break
                    if hard:proc.kill()
                    else:proc.stdin.close()
                    proc.wait(timeout=8)
                finally:
                    if proc.poll() is None:proc.kill();proc.wait()
                    if not proc.stdin.closed:proc.stdin.close()
                    proc.stdout.close();proc.stderr.close()
                restored=Jobs(self.root/'native-state')
                try:self.assertTrue(all(j['state']=='interrupted' for j in restored.snapshot()['jobs']))
                finally:restored.close()
        finally:server.close()

    def test_output_cannot_live_inside_engine_install(self):
        m=self.create()
        with self.assertRaises(AppError):m.enqueue({'url':'https://example.org/a.mp4','folder':str(m.data/'downloads')},'internal')
        self.assertFalse((m.data/'downloads').exists())

    def test_worker_database_write_failure_pauses_and_releases_lock_on_close(self):
        ready=threading.Event();release=threading.Event()
        def fault(runner,*args):
            ready.set();release.wait(5)
            self.manager.db.execute('PRAGMA query_only=ON')
            args[5]({'state':'downloading'})
        with patch('native.jobs.Runner.download',fault):
            m=self.create();first=m.enqueue(self.payload(),'db-fault');ready.wait(5)
            second=m.enqueue(self.payload(),'db-next');release.set()
            wait_for(lambda:m.storage_error is not None and m.active is None)
            self.assertTrue(m.thread.is_alive());self.assertEqual(m.get(second['jobId'])['state'],'queued')
            self.assertEqual(m.snapshot()['storageError']['code'],'DB_WRITE_FAILED')
            with self.assertRaises(AppError):m.enqueue(self.payload(),'blocked')
            # Closing must release the database and host lock even while read-only.
            m.close();self.manager=None;m=self.create()
            self.assertEqual(m.get(first['jobId'])['state'],'interrupted');self.assertEqual(m.get(second['jobId'])['state'],'interrupted')
