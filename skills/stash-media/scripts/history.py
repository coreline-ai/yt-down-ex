"""Skill-only journal. One file-producing owner, short SQLite transactions."""
from contextlib import contextmanager
import fcntl
import json
import sqlite3
import time
from pathlib import Path
from native.config import AppError

TERMINAL={'completed','failed','cancelled','interrupted'}
class History:
    def __init__(self,root):
        self.root=Path(root);self.path=self.root/'history.sqlite3'
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        with self.connect() as db:
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):raise AppError('SCHEMA_UNSUPPORTED','이 기록은 더 최신 스킬 버전이 필요합니다.')
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, request_id TEXT UNIQUE, created REAL, state TEXT, data TEXT)')
            db.execute('PRAGMA user_version=1')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=5)
        try:
            with db:yield db
        finally:db.close()
    @contextmanager
    def lease(self):
        with (self.root/'download.lock').open('a+') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise AppError('DOWNLOAD_BUSY','다른 스킬 다운로드가 실행 중입니다. 목록을 확인하거나 완료를 기다리세요.',True)
            yield
    def _write(self,db,job):
        job['updatedAt']=time.time()
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,data=excluded.data',(job['jobId'],job['requestId'],job['createdAt'],job['state'],json.dumps(job,ensure_ascii=False,allow_nan=False)))
        return job
    def insert(self,job):
        with self.connect() as db:return self._write(db,job)
    def by_request(self,rid):
        with self.connect() as db:row=db.execute('SELECT data FROM jobs WHERE request_id=?',(rid,)).fetchone()
        return json.loads(row[0]) if row else None
    def get(self,job_id):
        with self.connect() as db:row=db.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
        if not row:raise AppError('JOB_NOT_FOUND','작업을 찾을 수 없습니다.')
        return json.loads(row[0])
    def update(self,job_id,patch,*,finish=False):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not row:raise AppError('JOB_NOT_FOUND','작업을 찾을 수 없습니다.')
            job=json.loads(row[0]);job.update(patch)
            if finish and job.get('cancelRequested'):
                job.update(state='cancelled',error={'code':'CANCELLED','message':'다운로드를 취소했습니다.'})
            return self._write(db,job)
    def cancel(self,job_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not row:raise AppError('JOB_NOT_FOUND','작업을 찾을 수 없습니다.')
            job=json.loads(row[0])
            if job['state'] not in TERMINAL:job['cancelRequested']=True;self._write(db,job)
            return job
    def list(self,state='all',search='',limit=30,offset=0):
        where=[];values=[]
        if state=='active':where.append("state NOT IN ('completed','failed','cancelled','interrupted')")
        elif state!='all':where.append('state=?');values.append(state)
        if search:where.append("instr(lower(data),lower(?))>0");values.append(search)
        clause=' WHERE '+' AND '.join(where) if where else ''
        with self.connect() as db:
            count=db.execute('SELECT COUNT(*) FROM jobs'+clause,values).fetchone()[0]
            rows=db.execute('SELECT data FROM jobs'+clause+' ORDER BY created DESC,id DESC LIMIT ? OFFSET ?',values+[limit,offset]).fetchall()
        return {'jobs':[json.loads(r[0]) for r in rows],'total':count,'nextOffset':offset+len(rows) if offset+len(rows)<count else None}
    def recover(self):
        # Caller owns the download lease, so no live download can be reset.
        with self.connect() as db:
            rows=db.execute("SELECT data FROM jobs WHERE state NOT IN ('completed','failed','cancelled','interrupted')").fetchall()
            for row in rows:
                job=json.loads(row[0]);job.update(state='interrupted',nextRetryAt=None,error={'code':'INTERRUPTED','message':'이전 실행이 종료되었습니다. 다시 시도할 수 있습니다.'});self._write(db,job)
    def delete(self,job_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not row:raise AppError('JOB_NOT_FOUND','작업을 찾을 수 없습니다.')
            job=json.loads(row[0])
            if job['state'] not in TERMINAL:raise AppError('JOB_ACTIVE','실행 중인 작업은 취소 후 기록을 삭제하세요.')
            db.execute('DELETE FROM jobs WHERE id=?',(job_id,))
        return {'deleted':job_id,'filePreserved':True}
