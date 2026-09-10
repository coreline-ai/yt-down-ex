import json
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from native.engine import Runner,validate_url,output_root,verify_media,download_error
from native.config import AppError,tool
from tests.fixtures import MediaServer

class EngineTests(unittest.TestCase):
    def test_progress_output_without_newline_is_bounded(self):
        import sys
        with self.assertRaises(AppError) as error:
            Runner().run([sys.executable,'-c','import sys;sys.stdout.write("x"*2000000);sys.stdout.flush()'],lambda line:None)
        self.assertEqual(error.exception.code,'OUTPUT_TOO_LARGE')
    def test_error_categories_do_not_expose_sensitive_logs(self):
        cases=[('HTTP Error 403 caused by Cloudflare anti-bot challenge','SITE_CHALLENGE'),('HTTP Error 403','HTTP_FORBIDDEN'),('HTTP Error 404','HTTP_NOT_FOUND'),('CERTIFICATE_VERIFY_FAILED','TLS_CERTIFICATE_ERROR'),('Requested format is not available','FORMAT_UNAVAILABLE'),('unknown','DOWNLOAD_FAILED')]
        for message,code in cases:
            with self.subTest(code=code):
                error=download_error(message+' https://example.org/?token=secret Cookie: private')
                self.assertEqual(error.code,code)
                self.assertNotIn('secret',str(error));self.assertNotIn('private',str(error))
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name).resolve();cls.server=MediaServer(cls.root/'fixtures')
    @classmethod
    def tearDownClass(cls):cls.server.close();cls.temp.cleanup()
    def download(self,endpoint,mode='video',quality='best'):
        events=[]
        result=Runner().download(self.server.url+endpoint,mode,quality,str(self.root/'output'),uuid.uuid4().hex,events.append)
        self.assertGreater(result['size'],0);self.assertAlmostEqual(result['duration'],2,delta=.5)
        subprocess.run([tool('ffmpeg'),'-v','error','-i',result['path'],'-f','null','-'],check=True,capture_output=True)
        self.assertIn('verifying',[e.get('state') for e in events])
        return result
    def test_direct_video(self):
        result=self.download('/sample.mp4');self.assertEqual({s['codec_type'] for s in result['streams']},{'video','audio'})
    def test_direct_file_identity_in_inspection_and_download(self):
        result=self.download('/identity.mp4')
        self.assertEqual(result['container'],'mp4')
    def test_separate_stream_merge(self):
        self.server.requests.clear();result=self.download('/manifest.mpd')
        self.assertEqual({s['codec_type'] for s in result['streams']},{'video','audio'})
        self.assertTrue(any('chunk-stream0' in r for r in self.server.requests),self.server.requests)
        self.assertTrue(any('chunk-stream1' in r for r in self.server.requests),self.server.requests)
    def test_mp3(self):
        result=self.download('/sample.mp4','audio');self.assertEqual(result['container'],'mp3');self.assertEqual(result['streams'][0]['codec_name'],'mp3')
    def test_bad_url(self):
        for url in ['', 'file:///etc/passwd','https://user:pass@example.org/a','https://x/y?list=abc','https://x:bad/','https://x/\nfoo']:
            with self.assertRaises(AppError):validate_url(url)
    def test_bad_path(self):
        for folder in ['relative','/tmp/../bad']:
            with self.assertRaises(AppError):output_root(folder)
        link=self.root/'linked';link.symlink_to(self.root/'output',target_is_directory=True)
        with self.assertRaises(AppError):output_root(link)
    def test_failure_and_corrupt_media(self):
        for path in ['/missing.mp4','/error.html']:
            with self.assertRaises(AppError):self.download(path)
        corrupt=self.root/'corrupt.mp4';corrupt.write_text('not video')
        with self.assertRaises(AppError):verify_media(corrupt,'video')
    def test_unavailable_format(self):
        with self.assertRaises(AppError):self.download('/sample.mp4','video','480')

    def test_output_permission_denied(self):
        from unittest.mock import patch
        with patch('native.engine.os.access',return_value=False):
            with self.assertRaises(AppError) as error:output_root(self.root/'denied')
        self.assertEqual(error.exception.code,'OUTPUT_UNWRITABLE')

    def test_unicode_title_and_atomic_filename(self):
        result=self.download('/long.html')
        self.assertLessEqual(len(Path(result['path']).name.encode()),200)
        self.assertTrue(Path(result['path']).is_file())
