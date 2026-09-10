import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from native.media_server import MediaServer,byte_range
from native.schema import migrate
from native.config import AppError

class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.path=self.root/'sample.mp4';self.path.write_bytes(bytes(range(256))*1024)
        self.job={'jobId':'a','title':'테스트','state':'completed','folder':str(self.root),'result':{'path':str(self.path),'duration':60}}
        self.jobs=SimpleNamespace(lock=threading.RLock(),get=lambda _:self.job,_save=self.save_job)
        self.server=MediaServer(self.jobs,'test');self.session=self.server.open('a');self.url=urlsplit(self.session['url'])
    def save_job(self,job):self.job=job;return job
    def tearDown(self):self.server.close();self.temp.cleanup()
    def request(self,path=None,headers=None,method='GET'):
        c=http.client.HTTPConnection(self.url.hostname,self.url.port,timeout=3)
        try:
            c.request(method,path or self.url.path,headers=headers or {});r=c.getresponse();return r.status,dict(r.getheaders()),r.read()
        finally:c.close()
    def test_position_resume_stale_and_changed_file(self):
        token=self.session['sessionId']
        self.server.save_position(token,21,2)
        self.assertFalse(self.server.save_position(token,1,1)['saved'])
        resumed=self.server.open('a');self.assertEqual(resumed['position'],21)
        self.server.save_position(token,57,3)
        self.assertEqual(self.server.open('a')['position'],0)
        for value in [float('nan'),-1,True,'1']:
            with self.assertRaises(AppError):self.server.save_position(token,value,4)
        self.path.write_bytes(b'new file')
        with self.assertRaises(AppError):self.server.save_position(token,25,4)
        self.assertEqual(self.server.open('a')['position'],0)

    def test_ranges_and_head(self):
        code,headers,data=self.request(headers={'Range':'bytes=100-199'})
        self.assertEqual(code,206);self.assertEqual(len(data),100);self.assertEqual(data,self.path.read_bytes()[100:200])
        self.assertEqual(headers['Content-Range'],'bytes 100-199/262144')
        self.assertEqual(self.request(headers={'Range':'bytes=-5'})[2],self.path.read_bytes()[-5:])
        code,headers,data=self.request(method='HEAD');self.assertEqual(code,200);self.assertEqual(data,b'');self.assertEqual(headers['Content-Length'],'262144')
        for h in ['bytes=999999-','bytes=3-2','bytes=0-1,4-5','bytes=-0','bad']:
            self.assertEqual(self.request(headers={'Range':h})[0],416)
    def test_access_and_revocation(self):
        for path in ['/','/media/no','/etc/passwd',self.url.path+'?extra']:
            self.assertEqual(self.request(path=path)[0],403)
        self.assertEqual(self.request(headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request(headers={'Host':'evil.example'})[0],403)
        code,headers,_=self.request(headers={'Origin':'chrome-extension://test','Range':'bytes=0-0'})
        self.assertEqual(code,206);self.assertEqual(headers['Access-Control-Allow-Origin'],'chrome-extension://test')
        self.server.close_session(self.session['sessionId']);self.assertEqual(self.request()[0],403)
    def test_expiry_and_file_replacement(self):
        self.path.unlink();self.path.write_bytes(b'changed')
        self.assertEqual(self.request()[0],404)
        s=self.server.open('a');self.url=urlsplit(s['url']);self.server.sessions[s['sessionId']].expires=0
        self.assertEqual(self.request()[0],403)
    def test_symlink_and_unfinished_rejected(self):
        self.job['state']='downloading'
        with self.assertRaises(AppError):self.server.open('a')
        self.job['state']='completed';self.path.unlink();self.path.symlink_to('/etc/hosts')
        with self.assertRaises(AppError):self.server.open('a')
    def test_server_close_releases_port(self):
        import socket
        port=self.url.port;self.server.close()
        with socket.socket() as sock:
            sock.settimeout(.2);self.assertNotEqual(sock.connect_ex(('127.0.0.1',port)),0)

class SchemaTests(unittest.TestCase):
    def test_backup_migration_and_future_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=sqlite3.connect(root/'jobs.sqlite3')
            try:
                db.execute('create table jobs (id text,data text)');db.execute('insert into jobs values (?,?)',('old',json.dumps({'mode':'video','state':'completed'})));db.commit()
                migrate(db,root);self.assertEqual(json.loads(db.execute('select data from jobs').fetchone()[0])['outputProfile'],'original');self.assertEqual(db.execute('pragma user_version').fetchone()[0],1)
                with sqlite3.connect(root/'jobs-before-schema-1.sqlite3') as backup:
                    self.assertEqual(backup.execute('select id from jobs').fetchone()[0],'old')
                    self.assertEqual(backup.execute('pragma user_version').fetchone()[0],0)
                db.execute('pragma user_version=99')
                with self.assertRaises(AppError):migrate(db,root)
            finally:db.close()
