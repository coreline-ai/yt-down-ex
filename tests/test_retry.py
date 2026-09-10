import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from native.config import AppError
from native.engine import download_error,Runner
from native.jobs import Jobs
from native.retry import next_retry,retry_after
from tests.test_jobs import wait_for
from tests.fixtures import MediaServer

class RetryTests(unittest.TestCase):
    def test_policy_and_classification(self):
        error=AppError('NETWORK_ERROR','reset')
        self.assertEqual([next_retry(error,n,100,5) for n in range(1,5)],[106,116,146,None])
        for code in ['HTTP_FORBIDDEN','HTTP_NOT_FOUND','TLS_CERTIFICATE_ERROR','FORMAT_UNAVAILABLE','CONVERSION_FAILED','TIMEOUT','DISK_FULL','IO_ERROR','DOWNLOAD_FAILED']:
            self.assertIsNone(next_retry(AppError(code,'error',True),1,100))
        for raw,code in [('HTTP Error 503','HTTP_SERVER_ERROR'),('Connection reset by peer','NETWORK_ERROR'),('Read timed out','NETWORK_TIMEOUT'),('HTTP Error 429','HTTP_RATE_LIMIT')]:
            self.assertEqual(download_error(raw).code,code)
        self.assertEqual(next_retry(AppError('HTTP_RATE_LIMIT','limit',True,60),1,100),160)
        for value in [None,3601,float('nan')]:self.assertIsNone(next_retry(AppError('HTTP_RATE_LIMIT','limit',True,value),1,100))
        self.assertEqual(retry_after('60',100),60);self.assertIsNone(retry_after('invalid',100))
        self.assertEqual(retry_after('Thu, 01 Jan 1970 00:03:20 GMT',100),100)
        self.assertEqual(download_error('Unsupported URL: https://example.org/timeout').code,'DOWNLOAD_FAILED')
        args=Runner().base();self.assertEqual(args[args.index('--retries')+1],'0')

    def test_limit_history_and_manual_retry(self):
        with tempfile.TemporaryDirectory() as tmp,patch('native.jobs.Runner.download',side_effect=AppError('NETWORK_ERROR','reset')) as run:
            m=Jobs(Path(tmp)/'state',delays=(.01,.01,.01),jitter=lambda:0)
            try:
                j=m.enqueue({'url':'https://example.org/a.mp4','folder':str(Path(tmp).resolve())},'a');jid=j['jobId']
                wait_for(lambda:m.get(jid)['state']=='failed')
                result=m.get(jid);self.assertEqual(run.call_count,4);self.assertEqual(result['attempt'],4);self.assertEqual(len(result['attemptHistory']),4);self.assertIsNone(result['nextRetryAt'])
                retry=m.retry(jid,'manual');self.assertNotEqual(retry['jobId'],jid);self.assertEqual(retry['attempt'],1);self.assertEqual(retry['retryOf'],jid)
            finally:m.close()

    def test_wait_releases_worker_cancel_delete_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp,patch('native.jobs.Runner.download',side_effect=AppError('NETWORK_ERROR','reset')) as run:
            m=Jobs(Path(tmp)/'state',clock=lambda:100,jitter=lambda:0)
            try:
                p={'url':'https://example.org/a.mp4','folder':str(Path(tmp).resolve())};a=m.enqueue(p,'a');wait_for(lambda:m.get(a['jobId'])['state']=='retry_wait')
                self.assertEqual(m.get(a['jobId'])['nextRetryAt'],105)
                b=m.enqueue(p,'b');wait_for(lambda:m.get(b['jobId'])['state']=='retry_wait');self.assertEqual(run.call_count,2)
                result=m.delete_many([a['jobId'],'missing']);self.assertEqual(result['deleted'],[]);self.assertEqual(len(result['errors']),2)
                m.cancel(a['jobId']);self.assertIsNone(m.get(a['jobId'])['nextRetryAt']);m.close()
                m=Jobs(Path(tmp)/'state');self.assertEqual(m.get(a['jobId'])['state'],'cancelled');self.assertEqual(m.get(b['jobId'])['state'],'interrupted');self.assertIsNone(m.get(b['jobId'])['nextRetryAt']);self.assertEqual(run.call_count,2)
            finally:m.close()

    def test_nontransient_one_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=Jobs(Path(tmp)/'state',delays=(.01,.01,.01))
            try:
                for code in ['HTTP_FORBIDDEN','HTTP_NOT_FOUND','TLS_CERTIFICATE_ERROR','CONVERSION_FAILED','FORMAT_UNAVAILABLE','IO_ERROR']:
                    with patch('native.jobs.Runner.download',side_effect=AppError(code,'error',True)) as run:
                        j=m.enqueue({'url':'https://example.org/a.mp4','folder':str(Path(tmp).resolve())},code);wait_for(lambda:m.get(j['jobId'])['state']=='failed' and m.active is None);self.assertEqual(run.call_count,1)
            finally:m.close()

    def test_real_503_then_download_one_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            server=MediaServer(Path(tmp)/'fixtures');events=[]
            m=Jobs(Path(tmp)/'state',emit=events.append,delays=(.01,.01,.01),jitter=lambda:0)
            try:
                j=m.enqueue({'url':server.url+'/transient.mp4','folder':str(Path(tmp).resolve()/'output'),'outputProfile':'mp4'},'real')
                wait_for(lambda:m.get(j['jobId'])['state'] in ('completed','failed'),30)
                result=m.get(j['jobId']);self.assertEqual(result['state'],'completed',result.get('error'));self.assertEqual(result['attempt'],2)
                self.assertEqual(len(result['attemptHistory']),1);self.assertTrue(any(e['payload']['state']=='retry_wait' for e in events));self.assertEqual(len(list((Path(tmp)/'output').glob('*.mp4'))),1)
                self.assertEqual(server.failures,1)
            finally:m.close();server.close()

    def test_real_reset_recovery_and_rate_limit_no_early_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            server=MediaServer(Path(tmp)/'fixtures');m=Jobs(Path(tmp)/'state',delays=(.01,.01,.01),jitter=lambda:0)
            try:
                for route,expected in [('reset','completed'),('limited','failed')]:
                    j=m.enqueue({'url':server.url+'/'+route+'.mp4','folder':str(Path(tmp).resolve()/'output')},route)
                    wait_for(lambda:m.get(j['jobId'])['state'] in ('completed','failed'),30)
                    result=m.get(j['jobId']);self.assertEqual(result['state'],expected,result.get('error'))
                    if route=='reset':self.assertEqual(result['attempt'],2)
                    else:self.assertEqual(result['attempt'],1);self.assertEqual(result['error']['retryAfter'],3601)
            finally:m.close();server.close()
