import tempfile
import time
import unittest
from pathlib import Path
from native.jobs import Jobs
from native.config import AppError

class HistoryTests(unittest.TestCase):
    def test_search_cursor_deletion_and_large_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=Jobs(Path(tmp)/'state')
            try:
                start=time.monotonic()
                for n in range(1000):
                    m._save({'jobId':str(n).zfill(5),'requestId':str(n),'state':'failed' if n%2 else 'completed','created':n,'title':f'한글 영상 {n} %_','url':'https://media.example.org/sample.mp4','folder':tmp})
                first=m.snapshot(filter='failed',search='MEDIA.EXAMPLE');self.assertEqual(first['total'],500);self.assertEqual(len(first['jobs']),10)
                cursor=first['nextCursor'];m.delete(first['jobs'][0]['jobId']);second=m.snapshot(filter='failed',search='media.example',cursor=cursor)
                self.assertEqual(second['jobs'][0]['jobId'],'00979')
                self.assertEqual(m.snapshot(search='%_')['total'],999)
                self.assertEqual(m.snapshot(search='한글 영상 998')['total'],1)
                seen=[];cursor=None
                while True:
                    page=m.snapshot(filter='failed',cursor=cursor);seen.extend(j['jobId'] for j in page['jobs']);cursor=page['nextCursor']
                    if cursor is None:break
                self.assertEqual(len(seen),499);self.assertEqual(len(set(seen)),499)
                result=m.delete_many(seen[:100]);self.assertEqual(len(result['deleted']),100)
                self.assertEqual(m.snapshot(filter='failed')['total'],399)
                print('1000 history create/search/paginate/delete seconds:',round(time.monotonic()-start,3))
            finally:m.close()
    def test_partial_delete_reports_missing_and_rejects_invalid_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=Jobs(Path(tmp)/'state')
            try:
                m._save({'jobId':'a','requestId':'a','state':'failed','created':1})
                r=m.delete_many(['a','a','missing']);self.assertEqual(r['deleted'],['a']);self.assertEqual(r['errors'][0]['error']['code'],'JOB_NOT_FOUND')
                for value in [[],['x']*101,'all',[1]]:
                    with self.assertRaises(AppError):m.delete_many(value)
            finally:m.close()
