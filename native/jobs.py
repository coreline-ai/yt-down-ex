"""Single-owner persistent queue; all mutations happen under one lock."""
import fcntl
import json
import math
import random
from urllib.parse import urlsplit
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from native.config import AppError,DEFAULT_OUTPUT
from native.schema import migrate
from native.retry import next_retry,DELAYS
from native.engine import Runner,TERMINAL,validate_url,validate_options,output_root

class Jobs:
    def __init__(self,data,emit=lambda _:None,*,clock=time.time,delays=DELAYS,jitter=random.random):
        self.clock=clock;self.retry_delays=delays;self.jitter=jitter
        self.data=Path(data);self.data.mkdir(parents=True,exist_ok=True)
        self.instance=(self.data/'host.lock').open('a+')
        try:fcntl.flock(self.instance,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.instance.close();raise AppError('HOST_BUSY','다른 Chrome 프로필이 로컬 엔진을 사용하고 있습니다.',True)
        self.lock=threading.RLock();self.wake=threading.Condition(self.lock);self.emit=emit;self.closed=False
        self.active=None;self.cancel_event=None;self.storage_error=None
        self.db=sqlite3.connect(self.data/'jobs.sqlite3',check_same_thread=False)
        try:migrate(self.db,self.data)
        except BaseException:
            self.db.close();self.instance.close();raise
        self.db.create_function('url_host',1,lambda value:urlsplit(value or '').hostname or '',deterministic=True)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, request_id TEXT UNIQUE, state TEXT, created REAL, data TEXT)')
        self.db.commit()
        for job in self._all():
            if job['state'] not in TERMINAL:
                self._save({**job,'state':'interrupted','nextRetryAt':None,'error':{'code':'INTERRUPTED','message':'이전 작업이 중단되었습니다. 다시 시도하세요.','retryable':True}})
        self.thread=threading.Thread(target=self._work,daemon=True);self.thread.start()

    def _all(self):
        return [json.loads(row[0]) for row in self.db.execute('SELECT data FROM jobs ORDER BY created')]
    def get(self,job_id):
        if not isinstance(job_id,str):raise AppError('INVALID_JOB','작업 ID가 올바르지 않습니다.')
        row=self.db.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
        if not row:raise AppError('JOB_NOT_FOUND','작업을 찾을 수 없습니다.')
        return json.loads(row[0])
    def _save(self,job):
        previous_seq=job.get('seq',0);job={**job,'seq':previous_seq+1,'updated':time.time()}
        try:
            self.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,data=excluded.data',(job['jobId'],job['requestId'],job['state'],job['created'],json.dumps(job,ensure_ascii=False,allow_nan=False)))
            self.db.commit()
        except sqlite3.Error:
            self.db.rollback();raise
        try:self.emit({'protocolVersion':1,'type':'jobUpdated','jobId':job['jobId'],'seq':job['seq'],'payload':job})
        except (BrokenPipeError,OSError):pass
        return job
    def snapshot(self,offset=0,filter='all',search='',cursor=None):
        if not isinstance(offset,int) or isinstance(offset,bool) or offset<0 or filter not in ('all','active','completed','failed') or not isinstance(search,str) or len(search)>200:
            raise AppError('BAD_REQUEST','잘못된 목록 조회 조건입니다.')
        clauses=[];values=[]
        if filter=='active':clauses.append("state NOT IN ('completed','failed','cancelled','interrupted')")
        elif filter!='all':clauses.append('state=?');values.append(filter)
        if search.strip():
            clauses.append("(instr(lower(json_extract(data,'$.title')),lower(?))>0 OR instr(lower(url_host(json_extract(data,'$.url'))),lower(?))>0)")
            values.extend([search.strip(),search.strip()])
        where=' WHERE '+' AND '.join(clauses) if clauses else ''
        with self.lock:
            count=self.db.execute('SELECT COUNT(*) FROM jobs'+where,values).fetchone()[0]
            if cursor is not None:
                if not isinstance(cursor,dict) or not isinstance(cursor.get('id'),str) or not isinstance(cursor.get('created'),(int,float)) or not math.isfinite(cursor['created']):
                    raise AppError('BAD_REQUEST','잘못된 페이지 커서입니다.')
                clauses.append('(created < ? OR (created = ? AND id < ?))');values.extend([cursor['created'],cursor['created'],cursor['id']]);offset=0
            page_where=' WHERE '+' AND '.join(clauses) if clauses else ''
            rows=self.db.execute('SELECT data FROM jobs'+page_where+' ORDER BY created DESC,id DESC LIMIT 11 OFFSET ?',[*values,offset]).fetchall()
            active_ids=[r[0] for r in self.db.execute("SELECT id FROM jobs WHERE state NOT IN ('completed','failed','cancelled','interrupted')")]
            page=[];size=0
            for row in rows[:10]:
                job=json.loads(row[0]);length=len(json.dumps(job,ensure_ascii=False).encode())
                if page and size+length>200*1024:break
                page.append(job);size+=length
            more=len(rows)>len(page)
            next_cursor={'created':page[-1]['created'],'id':page[-1]['jobId']} if more and page else None
            return {'storageError':self.storage_error,'jobs':page,'total':count,'activeCount':len(active_ids),'activeJobIds':active_ids,'nextOffset':offset+len(page) if more else None,'nextCursor':next_cursor}

    def delete_many(self,job_ids):
        if not isinstance(job_ids,list) or not 1<=len(job_ids)<=100 or any(not isinstance(j,str) for j in job_ids):
            raise AppError('BAD_REQUEST','한 번에 1~100개 기록을 삭제할 수 있습니다.')
        deleted=[];errors=[]
        with self.lock:
            for job_id in dict.fromkeys(job_ids):
                try:self.delete(job_id);deleted.append(job_id)
                except AppError as error:errors.append({'jobId':job_id,'error':error.as_dict()})
        return {'deleted':deleted,'errors':errors}

    def enqueue(self,payload,request_id):
        with self.wake:
            if self.storage_error:raise AppError('DB_WRITE_FAILED',self.storage_error['message'])
            if self.closed:raise AppError('HOST_CLOSED','엔진이 종료 중입니다.',True)
            row=self.db.execute('SELECT data FROM jobs WHERE request_id=?',(request_id,)).fetchone()
            if row:return json.loads(row[0])
            url=validate_url(payload.get('url'));mode,quality=validate_options(payload)
            folder=payload.get('folder') or str(DEFAULT_OUTPUT)
            if not isinstance(folder,str) or len(folder)>4096:raise AppError('INVALID_PATH','올바른 저장 폴더를 입력하세요.')
            requested=Path(folder).expanduser()
            if requested.is_absolute() and requested.resolve().is_relative_to(self.data.resolve()):
                raise AppError('INVALID_PATH','엔진 설치 폴더에는 미디어를 저장할 수 없습니다.')
            folder=str(output_root(folder))
            count=self.snapshot()['activeCount']
            if count>=20:raise AppError('QUEUE_FULL','대기열은 최대 20개입니다.')
            job={'jobId':uuid.uuid4().hex,'requestId':request_id,'url':url,'mode':mode,'quality':quality,'folder':folder,'state':'queued','title':'미디어 분석 대기','created':time.time(),'progress':None,'speed':None,'eta':None,'seq':0}
            job.update(outputProfile=payload.get('outputProfile','mp3' if mode=='audio' else 'original'),attempt=1,nextRetryAt=None,attemptHistory=[],playbackPosition=None)
            if payload.get('retryOf'):job['retryOf']=payload['retryOf']
            job=self._save(job);self.wake.notify_all();return job
    def cancel(self,job_id):
        with self.wake:
            job=self.get(job_id)
            if job['state'] in TERMINAL:return job
            if self.active==job_id and self.cancel_event:self.cancel_event.set()
            result=self._save({**job,'state':'cancelled','nextRetryAt':None,'error':None})
            self.wake.notify_all();return result
    def delete(self,job_id):
        with self.lock:
            job=self.get(job_id)
            if job['state'] not in TERMINAL or self.active==job_id:
                raise AppError('INVALID_STATE','작업이 종료된 후 기록을 삭제할 수 있습니다.')
            self.db.execute('DELETE FROM jobs WHERE id=?',(job_id,))
            self.db.commit()
            result={'jobId':job_id}
            try:self.emit({'protocolVersion':1,'type':'jobDeleted','payload':result})
            except (BrokenPipeError,OSError):pass
            return result
    def retry(self,job_id,request_id):
        with self.lock:
            job=self.get(job_id)
            if job['state'] not in ('failed','cancelled','interrupted'):raise AppError('INVALID_STATE','중단되거나 실패한 작업만 재시도할 수 있습니다.')
            return self.enqueue({**job,'retryOf':job_id},request_id)
    def _update(self,job_id,changes):
        with self.lock:
            job=self.get(job_id)
            if job['state'] in TERMINAL:return job
            return self._save({**job,**changes})
    def _work(self):
        while True:
            with self.wake:
                while not self.closed:
                    if self.storage_error:self.wake.wait();continue
                    row=self.db.execute("SELECT data FROM jobs WHERE state='queued' OR (state='retry_wait' AND json_extract(data,'$.nextRetryAt')<=?) ORDER BY created LIMIT 1",(self.clock(),)).fetchone()
                    if row:break
                    due=self.db.execute("SELECT MIN(json_extract(data,'$.nextRetryAt')) FROM jobs WHERE state='retry_wait'").fetchone()[0]
                    self.wake.wait(max(.01,due-self.clock()) if due is not None else None)
                if self.closed:return
                job=json.loads(row[0]);job_id=job['jobId'];self.active=job_id;self.cancel_event=threading.Event();cancel=self.cancel_event
            try:
                try:
                    self._update(job_id,{'state':'inspecting','nextRetryAt':None,'error':None,'progress':None})
                    result=Runner(cancel).download(job['url'],job['mode'],job['quality'],job['folder'],job_id,lambda change:self._update(job_id,change),job.get('outputProfile'))
                    with self.lock:
                        if self.get(job_id)['state'] in TERMINAL:
                            Path(result['path']).unlink(missing_ok=True)
                        else:self._update(job_id,{'state':'completed','result':result,'progress':100,'speed':None,'eta':None})
                except AppError as error:
                    with self.wake:
                        current=self.get(job_id)
                        if current['state'] not in TERMINAL:
                            attempt=current.get('attempt',1);now=self.clock()
                            due=next_retry(error,attempt,now,self.jitter(),self.retry_delays)
                            history=[*current.get('attemptHistory',[]),{'attempt':attempt,'at':now,'error':error.as_dict()}][-4:]
                            self._update(job_id,{'state':'retry_wait' if due is not None else ('cancelled' if error.code=='CANCELLED' else 'failed'),'error':error.as_dict(),'attempt':attempt+1 if due is not None else attempt,'nextRetryAt':due,'attemptHistory':history,'progress':None,'speed':None,'eta':None})
                            self.wake.notify_all()
                except sqlite3.Error:raise
                except Exception as error:
                    code='DISK_FULL' if isinstance(error,OSError) and error.errno==28 else 'IO_ERROR'
                    self._update(job_id,{'state':'failed','error':{'code':code,'message':'파일 처리에 실패했습니다. 저장 공간과 폴더 권한을 확인하세요.','retryable':True}})
            except sqlite3.Error:
                self._storage_failed()
            finally:
                with self.lock:self.active=None;self.cancel_event=None
    def _storage_failed(self):
        with self.wake:
            self.storage_error={'code':'DB_WRITE_FAILED','message':'작업 기록을 저장하지 못해 대기열을 멈췄습니다. 저장 공간·권한을 확인하고 재생 탭과 패널을 닫은 뒤 다시 연결하세요. 저장 폴더의 파일도 확인하세요.','retryable':False}
            try:self.db.rollback()
            except sqlite3.Error:pass
            try:self.emit({'protocolVersion':1,'type':'engineError','payload':self.storage_error})
            except OSError:pass
            self.wake.notify_all()

    def close(self):
        with self.wake:
            if self.closed:return
            self.closed=True
            if self.cancel_event:self.cancel_event.set()
            for job in self._all():
                if job['state'] not in TERMINAL:
                    try:self._save({**job,'state':'interrupted','nextRetryAt':None,'error':{'code':'INTERRUPTED','message':'Chrome 연결이 종료되어 작업이 중단되었습니다.','retryable':True}})
                    except sqlite3.Error:self.db.rollback()
            self.wake.notify_all()
        self.thread.join(timeout=8)
        if self.thread.is_alive():raise RuntimeError('Download worker did not terminate')
        self.db.close();self.instance.close()
