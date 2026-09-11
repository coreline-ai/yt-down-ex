"""Independent skill CLI. stdout final JSON; stderr bounded progress events."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

os.environ["PYTHONNOUSERSITE"]="1"
os.environ.pop("PYTHONPATH",None)
os.environ.pop("PYTHONHOME",None)
BASE=Path(__file__).resolve().parent
sys.path[:0]=[str(BASE),str(BASE/'engine')]
# Deliberately ignore Chrome's STASH_DATA_DIR/STASH_OUTPUT_DIR.
ROOT=Path(os.environ.get('STASH_SKILL_HOME',Path.home()/'Library/Application Support/Stash Media Skill')).expanduser()
from native import config
config.DATA=ROOT
from native.config import AppError,tool
from native.engine import Runner,validate_url,output_root
from native.retry import next_retry
from history import History,TERMINAL


def emit(value):
    try:print(json.dumps(value,ensure_ascii=False,allow_nan=False),file=sys.stderr,flush=True)
    except BrokenPipeError:pass

def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()

def identity(path):
    stat=path.stat();return [stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns]

def checked_file(job):
    if job['state']!='completed':raise AppError('JOB_NOT_COMPLETED','검증 완료한 파일만 재생할 수 있습니다.')
    path=Path(job['result']['path'])
    if any(p.is_symlink() for p in [path,*path.parents]) or not path.is_file():raise AppError('FILE_MISSING','파일이 없거나 경로가 변경되었습니다.')
    if not path.resolve().is_relative_to(Path(job['folder']).resolve()):raise AppError('INVALID_PATH','기록된 저장 폴더 밖의 파일입니다.')
    proof=job.get('verification',{})
    before=identity(path)
    if before!=proof.get('identity') or digest(path)!=proof.get('sha256') or identity(path)!=before:
        raise AppError('FILE_CHANGED','검증 이후 파일이 변경되었습니다. 자동 재생하지 않습니다.')
    return path

def validate_request(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',value):raise AppError('INVALID_REQUEST_ID','요청 ID는 8~128자의 영문·숫자·하이픈·밑줄이어야 합니다.')
    return value

def download(history,args,previous=None):
    url=validate_url(previous['url'] if previous else args.url)
    profile=previous['outputProfile'] if previous else args.format
    quality=previous['quality'] if previous else args.quality
    folder=str(output_root(previous['folder'] if previous else args.folder or str(Path.home()/'Downloads/Stash Media')))
    if Path(folder).is_relative_to(ROOT.resolve()):raise AppError('INVALID_PATH','스킬 실행 환경 안에는 미디어를 저장할 수 없습니다.')
    request_id=validate_request(args.request_id or uuid.uuid4().hex)
    expected={'url':url,'outputProfile':profile,'quality':quality,'folder':folder}
    def duplicate():
        old=history.by_request(request_id)
        if old:
            if any(old.get(k)!=v for k,v in expected.items()):raise AppError('REQUEST_CONFLICT','이 요청 ID는 다른 다운로드에 사용되었습니다.')
            return {'ok':old['state'] not in {'failed','cancelled','interrupted'},'duplicate':True,'job':old}
    found=duplicate()
    if found:return found
    with history.lease():
        history.recover()
        found=duplicate()
        if found:return found
        if previous and previous['state'] not in {'failed','cancelled','interrupted'}:raise AppError('RETRY_NOT_ALLOWED','실패·취소·중단 작업만 다시 시도할 수 있습니다.')
        job={'jobId':uuid.uuid4().hex,'requestId':request_id,'createdAt':time.time(),'state':'queued','attempt':1,'nextRetryAt':None,'cancelRequested':False,**expected}
        if previous:job['retryOf']=previous['jobId']
        history.insert(job);job_id=job['jobId'];stop=threading.Event();done=threading.Event();signal_kind=[None];watch_error=[]
        def on_signal(number,_):signal_kind[0]='interrupted' if number==signal.SIGTERM else 'cancelled';stop.set()
        old_handlers={sig:signal.signal(sig,on_signal) for sig in (signal.SIGINT,signal.SIGTERM)}
        def watch():
            while not done.wait(.2):
                try:
                    if history.get(job_id).get('cancelRequested'):stop.set()
                except Exception as error:watch_error.append(error);stop.set();return
        watcher=threading.Thread(target=watch,daemon=True);watcher.start()
        emit({'jobId':job_id,'requestId':request_id,'state':'queued'})
        def progress(patch):
            history.update(job_id,patch);emit({'jobId':job_id,**patch})
        result=None
        try:
            for attempt in range(1,5):
                progress({'attempt':attempt,'nextRetryAt':None})
                try:
                    result=Runner(stop).download(url,'audio' if profile=='mp3' else 'video',quality,folder,job_id,progress,profile)
                    break
                except AppError as error:
                    due=next_retry(error,attempt,time.time(),random.random())
                    if stop.is_set() or due is None:raise
                    progress({'state':'retry_wait','nextRetryAt':due,'lastError':error.as_dict()})
                    if stop.wait(max(0,due-time.time())):raise AppError('CANCELLED','다운로드를 취소했습니다.')
            if result is None:raise AppError('DOWNLOAD_FAILED','다운로드 결과가 없습니다.')
            progress({'state':'verifying','result':result})
            path=Path(result['path']);before=identity(path)
            try:
                Runner(stop).run([tool('ffmpeg'),'-v','error','-xerror','-nostdin','-i',str(path),'-map','0:v?','-map','0:a?','-f','null','-'],timeout=1800,idle=1800)
            except AppError as error:
                if error.code=='CANCELLED':raise
                raise AppError('VERIFY_FAILED','전체 디코딩 검사에 실패했습니다. 저장 파일은 보존하며 완료로 표시하지 않습니다.') from error
            sha=digest(path)
            if identity(path)!=before:raise AppError('FILE_CHANGED','검증 도중 파일이 변경되었습니다.')
            if stop.is_set():raise AppError('CANCELLED','다운로드를 취소했습니다.')
            if watch_error:raise AppError('DB_WRITE_FAILED','작업 기록 확인에 실패했습니다.')
            job=history.update(job_id,{'state':'completed','error':None,'nextRetryAt':None,'result':result,'verification':{'decodeExitCode':0,'sha256':sha,'identity':before}},finish=True)
        except AppError as error:
            state=signal_kind[0] or ('cancelled' if error.code=='CANCELLED' else 'failed')
            job=history.update(job_id,{'state':state,'nextRetryAt':None,'error':error.as_dict(),**({'result':result} if result else {})})
        except Exception:
            job=history.update(job_id,{'state':'failed','nextRetryAt':None,'error':{'code':'LOCAL_IO_ERROR','message':'로컬 파일 또는 기록 처리에 실패했습니다. 저장 공간·권한을 확인하세요.'}})
        finally:
            done.set();watcher.join(timeout=2)
            for sig,handler in old_handlers.items():signal.signal(sig,handler)
        return {'ok':job['state']=='completed','job':job}

def parser():
    p=argparse.ArgumentParser(description='Chrome-independent verified media downloader')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor')
    q=sub.add_parser('inspect');q.add_argument('url')
    q=sub.add_parser('download');q.add_argument('url');q.add_argument('--format',choices=['mp4','mp3','original'],default='mp4');q.add_argument('--quality',choices=['best','1080','720','480'],default='best');q.add_argument('--folder');q.add_argument('--request-id')
    q=sub.add_parser('list');q.add_argument('--status',choices=['all','active','completed','failed','cancelled','interrupted'],default='all');q.add_argument('--search',default='');q.add_argument('--limit',type=int,default=30);q.add_argument('--offset',type=int,default=0)
    for command in ('status','play','cancel','delete','retry'):
        q=sub.add_parser(command);q.add_argument('job_id')
        if command=='retry':q.add_argument('--request-id')
    return p

def main():
    args=parser().parse_args()
    try:
        if not ROOT.is_absolute() or any(p.is_symlink() for p in [ROOT,*ROOT.parents]):raise AppError('INVALID_PATH','기록 폴더는 심볼릭 링크 없는 절대 경로여야 합니다.')
        if (ROOT/'active.json').exists():raise AppError('WRONG_DATA_ROOT','Chrome 엔진 폴더를 스킬 기록으로 사용할 수 없습니다.')
        history=History(ROOT)
        # Recover after SIGKILL without disturbing a live owner.
        try:
            with history.lease():history.recover()
        except AppError as e:
            if e.code!='DOWNLOAD_BUSY':raise
        if args.command=='doctor':
            versions={}
            for name in ('yt-dlp','ffmpeg','ffprobe','node'):
                path=tool(name);text=subprocess.check_output([path,'-version' if name in ('ffmpeg','ffprobe') else '--version'],stderr=subprocess.STDOUT,text=True,timeout=20)
                versions[name]={'path':path,'version':text.splitlines()[0]}
            reply={'ok':True,'skillVersion':'1.0.0','python':sys.version.split()[0],'pythonPath':sys.executable,'root':str(ROOT),'tools':versions}
        elif args.command=='inspect':reply={'ok':True,'media':Runner().inspect(args.url)}
        elif args.command=='download':reply=download(history,args)
        elif args.command=='retry':reply=download(history,args,history.get(args.job_id))
        elif args.command=='list':
            if not 1<=args.limit<=100 or args.offset<0 or len(args.search)>200:raise AppError('INVALID_OPTIONS','목록 조회 범위를 확인하세요.')
            reply={'ok':True,**history.list(args.status,args.search,args.limit,args.offset)}
        elif args.command=='status':reply={'ok':True,'job':history.get(args.job_id)}
        elif args.command=='cancel':reply={'ok':True,'job':history.cancel(args.job_id)}
        elif args.command=='delete':reply={'ok':True,**history.delete(args.job_id)}
        elif args.command=='play':
            job=history.get(args.job_id);path=checked_file(job)
            subprocess.run(['/usr/bin/open',str(path)],check=True,timeout=15)
            reply={'ok':True,'opened':True,'playbackObserved':False,'jobId':job['jobId'],'path':str(path)}
    except AppError as error:reply={'ok':False,'error':error.as_dict()}
    except (OSError,sqlite3.Error,subprocess.SubprocessError):reply={'ok':False,'error':{'code':'LOCAL_ERROR','message':'로컬 실행·파일·기록 처리에 실패했습니다. 설치 진단과 폴더 권한을 확인하세요.'}}
    print(json.dumps(reply,ensure_ascii=False,allow_nan=False),flush=True)
    return 0 if reply['ok'] else 1
if __name__=='__main__':raise SystemExit(main())
