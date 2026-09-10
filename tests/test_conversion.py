import subprocess
import shutil
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from native.config import AppError,tool
from native.engine import Runner
from tests.fixtures import MediaServer

class ConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name).resolve();cls.server=MediaServer(cls.root/'fixtures')
        shutil.copy(Path('tests/media/theora.ogg'),cls.root/'fixtures/theora.ogg')
        for name,args in [('vp9.webm',['-c:v','libvpx-vp9','-c:a','libopus']),('silent.mp4',['-c:v','copy','-an'])]:
            subprocess.run([tool('ffmpeg'),'-v','error','-i',str(cls.root/'fixtures/sample.mp4'),*args,str(cls.root/'fixtures'/name)],check=True)
    @classmethod
    def tearDownClass(cls):cls.server.close();cls.temp.cleanup()
    def test_all_profiles_produce_playable_mp4(self):
        paths=set()
        for name in ['sample.mp4','vp9.webm','theora.ogg','silent.mp4','manifest.mpd','sample.mp4','long.html']:
            with self.subTest(name=name):
                result=Runner().download(self.server.url+'/'+name,'video','best',str(self.root/'out'),uuid.uuid4().hex,lambda _:None,'mp4')
                self.assertNotIn(result['path'],paths);paths.add(result['path'])
                self.assertLessEqual(len(Path(result['path']).name.encode()),200)
                self.assertEqual(result['container'],'mp4')
                for stream in result['streams']:
                    self.assertEqual(stream['codec_name'],'h264' if stream['codec_type']=='video' else 'aac')
                    if stream['codec_type']=='video':self.assertEqual(stream['pix_fmt'],'yuv420p')
                self.assertEqual(any(s['codec_type']=='audio' for s in result['streams']),name!='silent.mp4')
                subprocess.run([tool('ffmpeg'),'-v','error','-xerror','-i',result['path'],'-f','null','-'],check=True,capture_output=True)
    def test_cancel_conversion_preserves_existing_file(self):
        root=self.root/'cancel';root.mkdir();existing=root/'keep.mp4';existing.write_bytes(b'keep')
        cancelled=threading.Event()
        def emit(e):
            if e.get('processing'):cancelled.set()
        with self.assertRaises(AppError) as error:
            Runner(cancelled).download(self.server.url+'/vp9.webm','video','best',str(root),'cancel',emit,'mp4')
        self.assertEqual(error.exception.code,'CANCELLED');self.assertEqual(list(root.iterdir()),[existing]);self.assertEqual(existing.read_bytes(),b'keep')
    def test_conversion_failure_is_not_completed(self):
        from native.convert import to_mp4
        from native.engine import verify_media
        source=self.root/'fixtures/vp9.webm';probe=verify_media(source,'video');runner=Runner()
        with patch.object(runner,'run',side_effect=AppError('DOWNLOAD_FAILED','bad')):
            with self.assertRaises(AppError) as e:to_mp4(source,probe,runner,lambda _:None)
        self.assertEqual(e.exception.code,'CONVERSION_FAILED')
