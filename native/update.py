"""Verified engine releases and a short-lived updater handed off from Native Messaging."""
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.request import urlopen
from native.config import ROOT,AppError

BUSY={'queued','waiting','downloading','installing','diagnosing','activating','rolling_back'}

def same_version(a,b):
    try:return tuple(int(x) for x in a.split('.'))==tuple(int(x) for x in b.split('.'))
    except (AttributeError,ValueError):return False

def catalog():return json.loads((ROOT/'shared/engine-releases.json').read_text())

def atomic_json(path,value):
    path=Path(path);temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('w') as f:
            json.dump(value,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        temporary.chmod(0o600);os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)

def fetch_json(url):
    with urlopen(url,timeout=6) as response:
        data=response.read(2*1024*1024+1)
    if len(data)>2*1024*1024:raise ValueError('metadata too large')
    return json.loads(data)

def check_update(diagnostics,fetch=fetch_json):
    allowed=catalog();verified=True;latest={};offline=False
    try:
        for item in allowed['packages']:
            metadata=fetch(f"https://pypi.org/pypi/{item['name']}/{item['version']}/json")
            verified &= any(f.get('filename')==item['filename'] and f.get('digests',{}).get('sha256')==item['sha256'] for f in metadata['urls'])
            latest[item['name']]=fetch(f"https://pypi.org/pypi/{item['name']}/json")['info']['version']
    except (OSError,ValueError,KeyError):offline=True;verified=False
    current={'yt-dlp':diagnostics.get('tools',{}).get('yt-dlp',{}).get('version'),'yt-dlp-ejs':diagnostics.get('ejs')}
    same=all(same_version(current.get(p['name']),p['version']) for p in allowed['packages'])
    unverified=any(not same_version(latest.get(p['name'],p['version']),p['version']) for p in allowed['packages'])
    return {'status':'offline' if offline else 'hash_mismatch' if not verified else 'up_to_date' if same else 'available','recommended':{p['name']:p['version'] for p in allowed['packages']},'latest':latest,'unverifiedLatest':unverified,'verified':verified,'current':current}

def get_status(data):
    path=Path(data)/'update-status.json'
    if not path.exists():return {'state':'idle'}
    result=json.loads(path.read_text())
    if result.get('state') in BUSY:
        try:os.kill(result.get('pid',0),0)
        except (ProcessLookupError,PermissionError):
            result={**result,'state':'interrupted','message':'업데이트 실행이 중단되었습니다. 마지막으로 검증된 활성 엔진을 사용합니다. 진단 후 다시 설치하세요.'};atomic_json(path,result)
    return result

def start_update(data,action='install'):
    data=Path(data)
    if action not in ('install','rollback'):raise AppError('BAD_REQUEST','지원하지 않는 업데이트 동작입니다.')
    if not (data/'active.json').exists() or not (ROOT/'scripts/install.py').exists():
        raise AppError('UPDATE_NOT_INSTALLED','설치된 로컬 엔진에서 사용할 수 있습니다. 먼저 로컬 엔진 설치를 실행하세요.')
    lock=(data/'update.lock').open('a+')
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise AppError('UPDATE_BUSY','이미 업데이트가 진행 중입니다.')
        if action=='rollback' and not (data/'previous.json').is_file():raise AppError('NO_ROLLBACK','이전 엔진 릴리스가 없습니다.')
        operation=uuid.uuid4().hex
        status={'operationId':operation,'action':action,'state':'queued','pid':os.getpid(),'startedAt':time.time(),'message':'엔진 연결 종료를 기다립니다.'}
        atomic_json(data/'update-status.json',status)
        # Inherit the exclusive update lock; the parent releases its copy after spawn.
        process=subprocess.Popen([sys.executable,'-m','native.update',str(data),action,operation,str(lock.fileno())],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,pass_fds=(lock.fileno(),))
        # Child owns subsequent state writes, avoiding a queued write over later stages.
        return {'updateHandoff':True,'operationId':operation,'pid':process.pid}
    except OSError:
        atomic_json(data/'update-status.json',{'state':'failed','message':'업데이트 프로세스를 시작하지 못했습니다.'})
        raise AppError('UPDATE_START_FAILED','업데이트 프로세스를 시작하지 못했습니다.')
    finally:lock.close()

def download_wheel(item,destination,opener=urlopen):
    digest=hashlib.sha256();size=0;started=time.monotonic()
    with opener(item['url'],timeout=10) as response,Path(destination).open('wb') as output:
        while True:
            block=response.read(65536)
            if not block:break
            size+=len(block)
            if size>32*1024*1024 or time.monotonic()-started>60:raise AppError('UPDATE_DOWNLOAD_LIMIT','엔진 다운로드 제한을 초과했습니다.')
            digest.update(block);output.write(block)
    if digest.hexdigest()!=item['sha256']:raise AppError('UPDATE_HASH_MISMATCH','엔진 파일 해시가 검증 목록과 다릅니다. 기존 엔진을 유지합니다.')

def execute(data,action,operation,*,wheel_dir=None):
    from scripts.install import install,rollback,run_diagnose
    data=Path(data)
    def status(state,message):atomic_json(data/'update-status.json',{'operationId':operation,'action':action,'state':state,'pid':os.getpid(),'updatedAt':time.time(),'message':message})
    status('waiting','기존 엔진 종료를 기다립니다.')
    try:
        # Installer holds host.lock across staging/activation. Never kill a host.
        if action=='rollback':
            status('rolling_back','이전 엔진을 진단하고 복원합니다.');result=rollback(data,wait=20)
        else:
            with tempfile.TemporaryDirectory(prefix='update-',dir=data) as tmp:
                target=Path(tmp);status('downloading','검증된 엔진 파일을 받습니다.')
                for item in catalog()['packages']:
                    if wheel_dir:
                        import shutil
                        shutil.copy(Path(wheel_dir)/item['filename'],target/item['filename'])
                        if hashlib.sha256((target/item['filename']).read_bytes()).hexdigest()!=item['sha256']:raise AppError('UPDATE_HASH_MISMATCH','엔진 파일 해시가 다릅니다.')
                    else:download_wheel(item,target/item['filename'])
                manifests=json.loads((data/'manifests.json').read_text())
                if not manifests:raise AppError('UPDATE_NOT_INSTALLED','호스트 등록 정보를 찾을 수 없습니다.')
                browser=Path(manifests[0]).parent.parent
                status('installing','새 전용 환경에 엔진을 설치합니다.')
                result=install(data,browser,target,wait=20,progress=status)
        status('completed','엔진 복원이 완료되었습니다.' if action=='rollback' else '검증된 엔진 설치가 완료되었습니다.')
        return result
    except Exception as error:
        message=error.message if isinstance(error,AppError) else '엔진 설치 또는 진단에 실패했습니다. 기존 활성 엔진을 유지합니다. 진단 후 다시 시도하세요.'
        status('failed',message);return None



def serve_during_update(data,reader,writer):
    """Report progress without taking host.lock or loading the jobs database."""
    data=Path(data)
    if not (data/'update.lock').exists():return False
    lock=(data/'update.lock').open('a+')
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);return False
        except BlockingIOError:pass
    finally:lock.close()
    while True:
        message=reader()
        if message is None:return True
        result={'protocolVersion':1,'requestId':message.get('requestId'),'ok':False}
        if message.get('protocolVersion')==1 and message.get('type')=='getUpdateStatus':
            status=get_status(data);finished=status.get('state') not in BUSY
            result.update(ok=True,payload={**status,'updateReconnect':finished});writer(result)
            if finished:return True
        else:
            result['error']={'code':'UPDATE_BUSY','message':'엔진 업데이트 중입니다. 잠시 후 다시 연결하세요.','retryable':True};writer(result)

if __name__=='__main__':
    data,action,operation,descriptor=sys.argv[1:];execute(Path(data),action,operation)
