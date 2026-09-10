"""Bounded subprocess execution and media download. No shell or user yt-dlp config."""
import json
import math
import os
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from native.config import AppError, tool

TERMINAL = {'completed','failed','cancelled','interrupted'}

def download_error(text):
    """Expose actionable categories without exposing URLs, cookies or raw logs."""
    if 'Cloudflare anti-bot challenge' in text:
        return AppError('SITE_CHALLENGE','사이트의 자동 다운로드 차단으로 접근할 수 없습니다. 브라우저에서 열리는 주소도 다운로드 엔진에서는 차단될 수 있습니다.',False)
    if 'CERTIFICATE_VERIFY_FAILED' in text:
        return AppError('TLS_CERTIFICATE_ERROR','서버 인증서를 검증하지 못했습니다. 시스템 날짜와 인증서 설정을 확인하세요.',False)
    if 'HTTP Error 403' in text:
        return AppError('HTTP_FORBIDDEN','서버가 다운로드 접근을 거부했습니다 (HTTP 403). 주소의 접근 권한을 확인하세요.',False)
    if 'HTTP Error 404' in text:
        return AppError('HTTP_NOT_FOUND','서버에서 미디어를 찾을 수 없습니다 (HTTP 404). 주소를 확인하세요.',False)
    if re.search(r'HTTP Error (500|502|503|504)\b',text):
        return AppError('HTTP_SERVER_ERROR','서버에 일시적 오류가 발생했습니다.',True)
    if 'HTTP Error 429' in text:
        return AppError('HTTP_RATE_LIMIT','서버 요청 한도에 도달했습니다. 서버 대기 시간을 확인할 수 없거나 1시간을 초과하면 자동 재시도하지 않습니다.',True)
    if re.search(r'connection reset|connection aborted|remote end closed|network is unreachable|temporary failure in name resolution',text,re.I):
        return AppError('NETWORK_ERROR','네트워크 연결이 일시적으로 끊겼습니다.',True)
    if re.search(r'timed out|ReadTimeout|ConnectTimeout|socket\.timeout',text,re.I):
        return AppError('NETWORK_TIMEOUT','다운로드 서버 응답 시간이 초과되었습니다.',True)
    if 'Requested format is not available' in text:
        return AppError('FORMAT_UNAVAILABLE','선택한 형식이 없습니다. 최고 화질 또는 다른 옵션을 선택하세요.',True)
    return AppError('DOWNLOAD_FAILED','다운로드에 실패했습니다. 주소·접근 가능 여부·엔진 버전을 확인하세요.',True)

def validate_url(value):
    if not isinstance(value,str) or not value.strip() or len(value)>8192:
        raise AppError('INVALID_URL','올바른 HTTP(S) 주소를 입력하세요.')
    value=value.strip()
    try:
        parts=urlsplit(value)
        if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password or any(ord(c)<32 for c in value):
            raise ValueError()
        _=parts.port
    except ValueError:
        raise AppError('INVALID_URL','HTTP(S) 주소만 지원하며 인증정보가 포함된 주소는 사용할 수 없습니다.')
    if 'list' in parse_qs(parts.query) or parts.path.rstrip('/').endswith('/playlist'):
        raise AppError('PLAYLIST_UNSUPPORTED','재생목록 대신 개별 영상 주소를 입력하세요.')
    return value

def validate_options(payload):
    mode=payload.get('mode','video'); quality=str(payload.get('quality','best'))
    if mode not in ('video','audio') or quality not in ('best','1080','720','480'):
        raise AppError('INVALID_OPTIONS','지원하지 않는 다운로드 옵션입니다.')
    profile=payload.get('outputProfile','mp3' if mode=='audio' else 'original')
    if profile not in ('original','mp4','mp3') or (mode=='audio') != (profile=='mp3'):
        raise AppError('INVALID_OPTIONS','형식과 다운로드 모드가 일치하지 않습니다.')
    return mode,quality

def output_root(value):
    path=Path(value).expanduser()
    if not path.is_absolute() or '..' in path.parts:
        raise AppError('INVALID_PATH','저장 폴더는 상위 경로 이동이 없는 절대 경로여야 합니다.')
    if any(p.is_symlink() for p in [path,*path.parents]):
        raise AppError('INVALID_PATH','심볼릭 링크 폴더에는 저장할 수 없습니다.')
    try:
        path.mkdir(parents=True,exist_ok=True)
        if not os.access(path,os.W_OK): raise PermissionError()
    except OSError:
        raise AppError("OUTPUT_UNWRITABLE","저장 폴더에 쓸 수 없습니다. 폴더 권한을 확인하세요.")
    return path.resolve()

def safe_name(title):
    title=re.sub(r'[\x00-\x1f/\\:*?"<>|]', '_', str(title))
    return title.strip(' .').encode('utf-8')[:180].decode('utf-8','ignore').strip(' .') or 'media'

class Runner:
    def __init__(self, cancelled=None):
        self.cancelled=cancelled or threading.Event()
        self.process=None
        self.phase_deadline=None

    def run(self,args,on_line=None,timeout=600,idle=90):
        if self.cancelled.is_set(): raise AppError('CANCELLED','다운로드를 취소했습니다.')
        start=last=time.monotonic(); output=bytearray(); buffer=bytearray()
        self.process=subprocess.Popen([sys.executable,str(Path(__file__).with_name("guard.py")),*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        proc=self.process
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout,selectors.EVENT_READ)
                while True:
                    now=time.monotonic()
                    if self.cancelled.is_set(): raise AppError('CANCELLED','다운로드를 취소했습니다.')
                    if (timeout and now-start>timeout) or (idle and now-last>idle) or (self.phase_deadline and now>self.phase_deadline):
                        raise AppError('TIMEOUT','서버 응답 또는 미디어 처리가 제한 시간을 초과했습니다.',True)
                    ready=selector.select(.1)
                    if ready:
                        chunk=os.read(proc.stdout.fileno(),65536)
                        if not chunk: break
                        last=now; output.extend(chunk); buffer.extend(chunk)
                        if on_line and len(output)>65536: output=output[-65536:]
                        elif len(output)>8*1024*1024: raise AppError('OUTPUT_TOO_LARGE','응답 데이터가 너무 큽니다.')
                        while b'\n' in buffer:
                            raw,_,rest=buffer.partition(b'\n');buffer=bytearray(rest)
                            if on_line: on_line(raw.decode('utf-8','replace'))
                        if on_line and len(buffer)>1024*1024:
                            raise AppError('OUTPUT_TOO_LARGE','다운로드 엔진의 출력 한도가 초과되었습니다.')
                    elif proc.poll() is not None: break
                if buffer and on_line: on_line(buffer.decode('utf-8','replace'))
            status=proc.wait(timeout=5)
            if status:
                text=output.decode('utf-8','replace')
                # Never return raw URLs, headers or downloader logs to the UI.
                raise download_error(text)
            return output.decode('utf-8','replace')
        finally:
            if proc.poll() is None:
                try: os.killpg(proc.pid,signal.SIGTERM)
                except ProcessLookupError: pass
                try: proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try: os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait()
            proc.stdout.close();proc.stdin.close();self.process=None

    def base(self,url=None):
        args=[tool('yt-dlp'),'--ignore-config','--no-playlist','--no-warnings','--no-colors','--socket-timeout','30','--retries','0','--fragment-retries','0','--extractor-retries','0','--file-access-retries','0','--ffmpeg-location',str(Path(tool('ffmpeg')).parent)]
        # Direct files use an honest app identity instead of a randomized browser UA.
        if url and Path(urlsplit(url).path).suffix.lower() in {'.mp4','.webm','.m4v','.mov','.ogg','.ogv','.mp3','.m4a','.wav'}:
            args+=['--user-agent','StashLocal/0.1']
        try: args+=['--js-runtimes','node:'+tool('node')]
        except AppError: pass
        return args

    def network_run(self,args,url,**kwargs):
        try:return self.run(args,**kwargs)
        except AppError as error:
            if self.phase_deadline is not None and error.code not in ('CANCELLED','TIMEOUT'):
                raise AppError('CONVERSION_FAILED','미디어 후처리에 실패했습니다. 자동 재시도하지 않습니다.') from error
            if error.code=='TIMEOUT' and self.phase_deadline is None:
                raise AppError('NETWORK_TIMEOUT','다운로드 서버 응답 시간이 초과되었습니다.',True) from error
            if error.code=='HTTP_RATE_LIMIT':
                from urllib.request import Request,build_opener,HTTPRedirectHandler
                from urllib.error import HTTPError
                from native.retry import retry_after
                # Do not follow redirects or infer another server's waiting period.
                class NoRedirect(HTTPRedirectHandler):
                    def redirect_request(self,*args,**kwargs):return None
                try:
                    with build_opener(NoRedirect).open(Request(url,method='HEAD',headers={'User-Agent':'StashLocal/0.1'}),timeout=3):pass
                except HTTPError as response:
                    if response.code==429:error.retry_after=retry_after(response.headers.get('Retry-After'),time.time())
                    response.close()
                except (OSError,ValueError):pass
            raise

    def inspect(self,url,include_thumbnail=False):
        url=validate_url(url)
        info=json.loads(self.network_run(self.base(url)+['--skip-download','--dump-single-json','--',url],url,timeout=30,idle=30))
        if info.get('_type') in ('playlist','multi_video') or info.get('entries') is not None:
            raise AppError('PLAYLIST_UNSUPPORTED','개별 영상만 지원합니다.')
        if info.get('is_live') or info.get('live_status') in ('is_live','is_upcoming'):
            raise AppError('LIVE_UNSUPPORTED','실시간 방송은 지원하지 않습니다.')
        from native.preview import summarize,thumbnail
        result=summarize(info)
        if include_thumbnail:result['thumbnail']=thumbnail(info.get('thumbnail'),self)
        return result

    def download(self,url,mode,quality,folder,job_id,emit,output_profile=None):
        output_profile=output_profile or ('mp3' if mode=='audio' else 'original')
        url=validate_url(url);validate_options({'mode':mode,'quality':quality,'outputProfile':output_profile})
        root=output_root(folder)
        emit({'state':'inspecting'})
        info=self.inspect(url)
        emit({'title':info['title'],'duration':info['duration'],'state':'downloading'})
        with tempfile.TemporaryDirectory(prefix='.stash-'+job_id[:8]+'-',dir=root) as tmp:
            work=Path(tmp); resultfile=work/'result.jsonl'
            fmt='ba/b' if mode=='audio' else ('bv*+ba/b' if quality=='best' else f'bv*[height<={quality}]+ba/b[height<={quality}]')
            args=self.base(url)+['--newline','--progress','--progress-delta','0.25','--no-simulate','--no-continue','--no-overwrites','-f',fmt,'-o',str(work/'media.%(ext)s'),'--progress-template','download:progress:%(progress)j','--progress-template','postprocess:postprocess:%(progress.status)s','--print-to-file','after_move:%(filepath)j',str(resultfile)]
            if mode=='audio':args+=['-x','--audio-format','mp3','--audio-quality','192K']
            last_emit=0
            def line(text):
                nonlocal last_emit
                if text.startswith('postprocess:'):
                    if self.phase_deadline is None:self.phase_deadline=time.monotonic()+600
                    emit({'state':'postprocessing'});return
                if not text.startswith('progress:'):return
                try: p=json.loads(text[9:])
                except ValueError:return
                if time.monotonic()-last_emit < .25 and p.get('status')!='finished':return
                last_emit=time.monotonic()
                total=p.get('total_bytes') or p.get('total_bytes_estimate'); done=p.get('downloaded_bytes',0)
                def finite(v):return v if isinstance(v,(int,float)) and math.isfinite(v) else None
                emit({'progress':min(100,done/total*100) if total and done else None,'speed':finite(p.get('speed')),'eta':finite(p.get('eta'))})
            self.network_run(args+['--',url],url,on_line=line,timeout=None,idle=600)
            emit({'state':'verifying','progress':100})
            try: candidate=Path(json.loads(resultfile.read_text().splitlines()[-1]))
            except (OSError,ValueError,IndexError):raise AppError('VERIFY_FAILED','다운로드 결과 경로를 확인할 수 없습니다.')
            if candidate.is_symlink() or not candidate.resolve().is_relative_to(work.resolve()):
                raise AppError('INVALID_PATH','잘못된 결과 파일 경로입니다.')
            probe=verify_media(candidate,mode,self)
            if output_profile=='mp4':
                from native.convert import to_mp4
                candidate,probe=to_mp4(candidate,probe,self,emit)
                emit({'state':'verifying','progress':100})
            if self.cancelled.is_set():raise AppError('CANCELLED','다운로드를 취소했습니다.')
            suffix=candidate.suffix.lower()
            if not re.fullmatch(r'\.[a-z0-9]{1,10}',suffix):raise AppError('VERIFY_FAILED','잘못된 파일 확장자입니다.')
            name=safe_name(info['title']);dest=root/(name+suffix)
            for n in range(10000):
                dest=root/(name+(f' ({n})' if n else '')+suffix)
                try:
                    # Hard-link publish is atomic and refuses existing names, including symlinks.
                    os.link(candidate,dest);break
                except FileExistsError:continue
            else:raise AppError('FILE_CONFLICT','같은 이름의 파일이 너무 많습니다.')
            return {'path':str(dest),'size':dest.stat().st_size,'container':suffix[1:],'duration':probe['duration'],'streams':probe['streams'],'title':info['title']}

def verify_media(path,mode,runner=None):
    path=Path(path)
    if not path.is_file() or path.stat().st_size<=0:raise AppError('VERIFY_FAILED','결과 파일이 비어 있습니다.')
    runner=runner or Runner()
    try:
        data=json.loads(runner.run([tool('ffprobe'),'-v','error','-show_entries','format=duration:stream=codec_type,codec_name,width,height,pix_fmt','-of','json',str(path)],timeout=60,idle=60))
        streams=data['streams'];duration=float(data.get('format',{}).get('duration',0))
        types={s['codec_type'] for s in streams}
        if duration<=0 or not math.isfinite(duration) or ('video' if mode=='video' else 'audio') not in types:
            raise ValueError()
        if mode=='audio' and ('video' in types or not any(s.get('codec_name')=='mp3' for s in streams)):raise ValueError()
        return {'duration':duration,'streams':streams}
    except (ValueError,KeyError,AppError):raise AppError('VERIFY_FAILED','결과 파일의 미디어 정보를 검증하지 못했습니다.')
