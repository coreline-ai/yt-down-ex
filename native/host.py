import importlib.metadata
import json
import platform
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from native.protocol import read_message,write_message
from native.config import ROOT,DATA,AppError,tool
from native.engine import Runner,validate_url
from native.jobs import Jobs
from native.media_server import MediaServer

def diagnose():
    result={'version':'0.2.0','protocolVersion':1,'schemaVersion':1,'release':str(ROOT),'platform':platform.platform(),'python':sys.version.split()[0],'tools':{}}
    for name in ('yt-dlp','ffmpeg','ffprobe','node'):
        try:
            path=tool(name);version=subprocess.check_output([path,'--version' if name in ('yt-dlp','node') else '-version'],stderr=subprocess.STDOUT,text=True,timeout=10).splitlines()[0]
            result['tools'][name]={'ok':True,'path':path,'version':version[:180]}
        except (AppError,OSError,subprocess.SubprocessError):result['tools'][name]={'ok':False}
    try:
        interpreter=Path(tool('yt-dlp')).parent/'python3'
        if interpreter.is_file():
            result['ejs']=subprocess.check_output([str(interpreter),'-c','import importlib.metadata;print(importlib.metadata.version("yt-dlp-ejs"))'],stderr=subprocess.DEVNULL,text=True,timeout=5).strip()
        else:result['ejs']=importlib.metadata.version('yt-dlp-ejs')
    except (AppError,importlib.metadata.PackageNotFoundError,OSError,subprocess.SubprocessError):result['ejs']=None
    from native.update import catalog,same_version
    result['recommended']={p['name']:p['version'] for p in catalog()['packages']}
    result['compatible']=same_version(result.get('ejs'),result['recommended']['yt-dlp-ejs']) and same_version(result['tools'].get('yt-dlp',{}).get('version'),result['recommended']['yt-dlp'])
    result['ready']=all(result['tools'][n]['ok'] for n in ('yt-dlp','ffmpeg','ffprobe'))
    return result

def main():
    eid=json.loads((ROOT/'shared/extension-id.json').read_text())['id']
    if len(sys.argv)<2 or sys.argv[1]!=f'chrome-extension://{eid}/':return 2
    send=lambda message:write_message(sys.stdout.buffer,message)
    from native.update import serve_during_update
    if serve_during_update(DATA,lambda:read_message(sys.stdin.buffer),send):return 0
    jobs=None;media=None;pool=ThreadPoolExecutor(max_workers=2);limit=threading.BoundedSemaphore(8);inspect_stop=threading.Event()
    inspections={};inspection_lock=threading.Lock();operation_lock=threading.RLock();maintenance=threading.Event()
    def dispatch(message):
        request_id=message.get('requestId')
        response={'protocolVersion':1,'requestId':request_id,'ok':False}
        try:
            if message.get('protocolVersion')!=1 or not isinstance(request_id,str) or not 0<len(request_id)<=100 or not isinstance(message.get('payload'),dict):
                raise AppError('BAD_REQUEST','지원하지 않는 요청 또는 프로토콜 버전입니다.')
            payload=message['payload'];command=message.get('type')
            if command=='hello':result={'version':'0.2.0','hostVersion':'0.2.0','extensionVersion':payload.get('extensionVersion') if isinstance(payload.get('extensionVersion'),str) and len(payload['extensionVersion'])<=32 else None,'protocolVersion':1,'schemaVersion':1,'capabilities':['playback','playbackPosition','deleteJob','mp4','preview','historySearch','deleteJobs','autoRetry','engineUpdate']}
            elif command=='diagnose':result=diagnose()
            elif command=='checkUpdate':
                from native.update import check_update
                result=check_update(diagnose())
            elif command=='getUpdateStatus':
                from native.update import get_status
                result=get_status(DATA)
            elif command=='startUpdate':
                from native.update import start_update
                import time
                with operation_lock,media.lock,jobs.lock,inspection_lock:
                    if maintenance.is_set() or jobs.snapshot()['activeCount'] or jobs.active or inspections or any(not s.revoked and s.expires>time.monotonic() for s in media.sessions.values()):
                        raise AppError('UPDATE_BUSY','분석·다운로드·재시도 대기·재생을 종료한 후 업데이트하세요.')
                    result=start_update(DATA,payload.get('action','install'));maintenance.set()
            elif command=='inspect':
                with operation_lock:
                    if maintenance.is_set():raise AppError('UPDATE_BUSY','엔진 업데이트 중입니다.')
                    stop=threading.Event()
                    if inspect_stop.is_set():stop.set()
                    with inspection_lock:inspections[request_id]=stop
                try:result=Runner(stop).inspect(validate_url(payload.get('url')),include_thumbnail=True)
                finally:
                    with inspection_lock:inspections.pop(request_id,None)
            elif command=='cancelInspect':
                with inspection_lock:
                    stop=inspections.get(payload.get('inspectRequestId'))
                    if stop:stop.set()
                result={'cancelled':bool(stop)}
            elif command=='getSnapshot':result=jobs.snapshot(payload.get('offset',0),payload.get('filter','all'),payload.get('search',''),payload.get('cursor'))
            elif command in ('enqueue','retry','openPlayback'):
                with operation_lock:
                    if maintenance.is_set():raise AppError('UPDATE_BUSY','엔진 업데이트 중입니다.')
                    result=jobs.enqueue(payload,request_id) if command=='enqueue' else jobs.retry(payload.get('jobId'),request_id) if command=='retry' else media.open(payload.get('jobId'))
            elif command=='cancel':result=jobs.cancel(payload.get('jobId'))
            elif command=='deleteJob':
                result=jobs.delete(payload.get('jobId'));media.revoke(result['jobId'])
            elif command=='deleteJobs':
                result=jobs.delete_many(payload.get('jobIds'))
                for job_id in result['deleted']:media.revoke(job_id)
            elif command=='closePlayback':result=media.close_session(payload.get('sessionId'))
            elif command=='savePlaybackPosition':result=media.save_position(payload.get('sessionId'),payload.get('seconds'),payload.get('seq'),payload.get('ended',False))
            elif command=='revealFile':
                with jobs.lock:
                    job=jobs.get(payload.get('jobId'))
                    if job['state']!='completed':raise AppError('INVALID_STATE','완료한 파일만 열 수 있습니다.')
                    path=Path(job['result']['path'])
                    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(Path(job['folder']).resolve()):raise AppError('FILE_MISSING','저장 파일을 찾을 수 없습니다.')
                    subprocess.run(['/usr/bin/open','-R',str(path)],check=True,timeout=10)
                    result={'revealed':True}
            else:raise AppError('UNSUPPORTED_COMMAND','지원하지 않는 기능입니다. 확장과 로컬 엔진을 같은 검증 버전으로 업데이트하세요.')
            response.update(ok=True,payload=result)
        except AppError as error:response['error']=error.as_dict()
        except Exception:response['error']={'code':'INTERNAL_ERROR','message':'요청을 처리하지 못했습니다. 엔진 진단을 확인하세요.','retryable':True}
        try:send(response)
        except (OSError,ValueError):pass
        finally:limit.release()
    try:
        jobs=Jobs(DATA,send);media=MediaServer(jobs,eid)
        def terminate(*_):raise SystemExit(0)
        signal.signal(signal.SIGTERM,terminate);signal.signal(signal.SIGINT,terminate)
        while True:
            message=read_message(sys.stdin.buffer)
            if message is None:return 0
            if limit.acquire(blocking=False):pool.submit(dispatch,message)
            else:send({'protocolVersion':1,'requestId':message.get('requestId'),'ok':False,'error':{'code':'BUSY','message':'요청이 많습니다. 잠시 후 다시 시도하세요.','retryable':True}})
    except AppError as error:
        # Origin is verified but a competing native host owns the queue.
        try:
            message=read_message(sys.stdin.buffer)
            if message:send({'protocolVersion':1,'requestId':message.get('requestId'),'ok':False,'error':error.as_dict()})
        except (OSError,ValueError):pass
        return 1
    except (ValueError,BrokenPipeError):return 1
    finally:
        inspect_stop.set()
        with inspection_lock:
            for stop in inspections.values():stop.set()
        pool.shutdown(wait=True,cancel_futures=False)
        if media:media.close()
        if jobs:jobs.close()
if __name__=='__main__':raise SystemExit(main())
