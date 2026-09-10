import http.client
import json
import socket
import tempfile
import threading
import time
import tracemalloc
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from native.media_server import MediaServer

class LargeTransferTests(unittest.TestCase):
    def test_one_gib_range_stream_has_bounded_python_memory_and_releases_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();path=root/'transport-only.bin';size=1024**3
            with path.open('wb') as f:f.truncate(size)
            job={'jobId':'large','state':'completed','title':'1 GiB synthetic transport fixture','folder':str(root),'result':{'path':str(path),'size':size,'duration':1}}
            jobs=SimpleNamespace(lock=threading.RLock(),get=lambda _:job)
            server=MediaServer(jobs,'test');url=urlsplit(server.open('large')['url'])
            connection=http.client.HTTPConnection(url.hostname,url.port,timeout=15)
            tracemalloc.start();started=time.monotonic();received=0
            try:
                connection.request('GET',url.path,headers={'Range':f'bytes=0-{size-1}'})
                response=connection.getresponse();self.assertEqual(response.status,206);self.assertEqual(response.getheader('Content-Length'),str(size))
                while block:=response.read(65536):received+=len(block)
                _,peak=tracemalloc.get_traced_memory();self.assertEqual(received,size);self.assertLess(peak,8*1024*1024)
                report={'fixture':'sparse synthetic bytes, not a video download','bytes':received,'seconds':round(time.monotonic()-started,3),'pythonPeakBytes':peak,'bufferBytes':65536}
                Path('artifacts/large-transfer.json').write_text(json.dumps(report,indent=2));print(report)
            finally:tracemalloc.stop();connection.close();server.close()
            with socket.socket() as sock:sock.settimeout(.5);self.assertNotEqual(sock.connect_ex((url.hostname,url.port)),0)
