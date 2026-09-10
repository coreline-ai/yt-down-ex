import unittest
import tempfile
import subprocess
from pathlib import Path
from native.preview import summarize,thumbnail
from native.engine import Runner
from native.config import tool
from tests.fixtures import MediaServer

class PreviewTests(unittest.TestCase):
    def test_missing_and_exact_metadata(self):
        p=summarize({'title':'x','duration':float('nan'),'formats':[{'height':None,'vcodec':None,'acodec':None}]})
        self.assertIsNone(p['duration']);self.assertIsNone(p['size']);self.assertIsNone(p['hasVideo']);self.assertEqual(p['heights'],[])
        p=summarize({'duration':2,'formats':[{'height':720,'vcodec':'h264','acodec':'none'},{'acodec':'aac','vcodec':'none'}],'requested_formats':[{'filesize':100},{'filesize':20}]})
        self.assertEqual(p['size'],120);self.assertFalse(p['sizeIsEstimate']);self.assertTrue(p['hasVideo']);self.assertTrue(p['hasAudio'])
        p=summarize({'filesize_approx':50});self.assertEqual(p['size'],50);self.assertTrue(p['sizeIsEstimate'])
    def test_thumbnail_bounded_and_failures_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();server=MediaServer(root)
            try:
                subprocess.run([tool('ffmpeg'),'-v','error','-i',str(root/'sample.mp4'),'-frames:v','1',str(root/'thumb.jpg')],check=True,capture_output=True)
                encoded=thumbnail(server.url+'/thumb.jpg',Runner());self.assertTrue(encoded.startswith('data:image/jpeg;base64,'));self.assertLess(len(encoded),90000)
                (root/'large.jpg').write_bytes(b'x'*(2*1024*1024+1))
                for url in [server.url+'/large.jpg',server.url+'/missing.jpg',server.url+'/error.html','file:///etc/passwd']:
                    self.assertIsNone(thumbnail(url,Runner()))
            finally:server.close()
