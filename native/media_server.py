"""Short-lived, capability-protected loopback transport for completed media."""
import mimetypes
import math
import os
import secrets
import socket
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from native.config import AppError


def fingerprint(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def completed_file(jobs, job_id):
    with jobs.lock:
        job = jobs.get(job_id)
        if job['state'] != 'completed' or not job.get('result'):
            raise AppError('INVALID_STATE', '완료된 파일만 재생할 수 있습니다.')
        path = Path(job['result']['path'])
        if any(p.is_symlink() for p in [path, *path.parents]) or not path.resolve().is_relative_to(Path(job['folder']).resolve()):
            raise AppError('FILE_MISSING', '저장 파일 경로가 변경되었습니다.')
        try:
            stat = path.stat()
            if not path.is_file() or stat.st_size <= 0: raise OSError()
        except OSError:
            raise AppError('FILE_MISSING', '저장 파일을 찾을 수 없습니다.')
        return job, path, fingerprint(stat)


def byte_range(header, size):
    if header is None: return 0, size - 1, 200
    import re
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
    if not match or not any(match.groups()): raise ValueError()
    a, b = match.groups()
    if not a:
        if int(b) <= 0: raise ValueError()
        start, end = max(0, size - int(b)), size - 1
    else:
        start, end = int(a), min(int(b), size - 1) if b else size - 1
    if start >= size or end < start: raise ValueError()
    return start, end, 206


@dataclass
class Session:
    job_id: str
    path: Path
    identity: tuple
    expires: float
    revoked: bool = False
    last_seq: int = 0


class MediaServer:
    def __init__(self, jobs, extension_id, ttl=3600):
        self.jobs, self.origin, self.ttl = jobs, 'chrome-extension://' + extension_id, ttl
        self.lock = threading.RLock()
        self.sessions = {}
        self.server = None
        self.thread = None

    def open(self, job_id):
        job, path, identity = completed_file(self.jobs, job_id)
        with self.lock:
            now = time.monotonic()
            self.sessions = {k: s for k, s in self.sessions.items() if s.expires > now and not s.revoked}
            if len(self.sessions) >= 16: raise AppError('PLAYBACK_LIMIT', '재생 탭은 최대 16개입니다.')
            if self.server is None: self._start()
            token = secrets.token_urlsafe(32)
            self.sessions[token] = Session(job_id, path, identity, now + self.ttl)
            position = job.get('playbackPosition') or {}
            return {'jobId': job_id, 'sessionId': token, 'url': f'http://127.0.0.1:{self.server.server_port}/media/{token}',
                    'title': job['title'], 'result': job['result'], 'position': position.get('seconds', 0) if position.get('identity') == list(identity) else 0,
                    'expiresIn': self.ttl}

    def save_position(self, token, seconds, sequence, ended=False):
        if not isinstance(token,str) or not isinstance(seconds,(int,float)) or isinstance(seconds,bool) or not math.isfinite(seconds) or seconds<0 or not isinstance(sequence,int) or isinstance(sequence,bool) or sequence<1 or not isinstance(ended,bool):
            raise AppError('BAD_REQUEST','재생 위치가 올바르지 않습니다.')
        with self.lock:
            session=self.sessions.get(token)
            if not session or session.revoked or session.expires<=time.monotonic():
                raise AppError('PLAYBACK_EXPIRED','재생 연결이 만료되었습니다. 다시 연결하세요.')
            if sequence<=session.last_seq:return {'saved':False}
            with self.jobs.lock:
                job,path,identity=completed_file(self.jobs,session.job_id)
                if path!=session.path or identity!=session.identity:
                    session.revoked=True
                    raise AppError('FILE_CHANGED','영상 파일이 변경되었습니다. 다시 연결하세요.')
                duration=job['result'].get('duration',0)
                if not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0:
                    raise AppError('VERIFY_FAILED','영상 길이를 확인할 수 없습니다.')
                seconds=min(seconds,duration)
                position=0 if ended or (duration>5 and seconds>=duration-5) else seconds
                self.jobs._save({**job,'playbackPosition':{'seconds':position,'identity':list(identity),'savedAt':time.time()}})
                session.last_seq=sequence;session.expires=time.monotonic()+self.ttl
                return {'saved':True,'seconds':position}

    def close_session(self, token):
        if not isinstance(token,str):raise AppError('BAD_REQUEST','재생 세션이 올바르지 않습니다.')
        with self.lock:
            session = self.sessions.pop(token, None)
            if session: session.revoked = True
        return {'closed': True}

    def revoke(self, job_id):
        with self.lock:
            for token in [t for t,s in self.sessions.items() if s.job_id == job_id]:
                self.close_session(token)

    def _start(self):
        owner = self
        class Server(ThreadingHTTPServer):
            daemon_threads = True
            block_on_close = False
            allow_reuse_address = False
            def __init__(self):
                self.slots = threading.BoundedSemaphore(8)
                super().__init__(('127.0.0.1', 0), Handler)
            def process_request(self, request, address):
                if not self.slots.acquire(blocking=False):
                    self.shutdown_request(request); return
                try: super().process_request(request, address)
                except BaseException:
                    self.slots.release(); raise
            def process_request_thread(self, request, address):
                try: super().process_request_thread(request, address)
                finally: self.slots.release()
            def handle_error(self, request, address): pass
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *_): pass
            def setup(self):
                super().setup(); self.connection.settimeout(10)
            def finish(self):
                try: super().finish()
                except OSError: pass
            def reply(self, status, length=0, headers=None):
                self.send_response(status)
                self.send_header('Content-Length', str(length))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                if self.headers.get('Origin') == owner.origin:
                    self.send_header('Access-Control-Allow-Origin', owner.origin)
                    self.send_header('Vary', 'Origin')
                for k,v in (headers or {}).items(): self.send_header(k,v)
                self.end_headers()
            def do_HEAD(self): self.serve(False)
            def do_GET(self): self.serve(True)
            def serve(self, body):
                try:
                    if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}' or self.headers.get('Origin') not in (None, owner.origin):
                        self.reply(403); return
                    token = self.path.removeprefix('/media/') if self.path.startswith('/media/') else ''
                    with owner.lock: session = owner.sessions.get(token)
                    if not session or session.revoked or session.expires <= time.monotonic():
                        self.reply(403); return
                    try:
                        _, path, identity = completed_file(owner.jobs, session.job_id)
                        if path != session.path or identity != session.identity: raise OSError()
                        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                    except (AppError, OSError):
                        owner.close_session(token); self.reply(404); return
                    with os.fdopen(fd, 'rb') as file:
                        if fingerprint(os.fstat(file.fileno())) != session.identity:
                            owner.close_session(token); self.reply(404); return
                        size = session.identity[2]
                        try: start, end, status = byte_range(self.headers.get('Range'), size)
                        except (ValueError, OverflowError):
                            self.reply(416, headers={'Content-Range': f'bytes */{size}'}); return
                        mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
                        headers = {'Content-Type': mime, 'Accept-Ranges': 'bytes'}
                        if status == 206: headers['Content-Range'] = f'bytes {start}-{end}/{size}'
                        self.reply(status, end-start+1, headers)
                        if body:
                            file.seek(start); remaining = end-start+1
                            while remaining and not session.revoked and time.monotonic() < session.expires:
                                chunk = file.read(min(65536, remaining))
                                if not chunk: break
                                self.wfile.write(chunk); remaining -= len(chunk)
                            if remaining: self.close_connection = True
                except (OSError, socket.timeout): self.close_connection = True
        self.server = Server()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        with self.lock:
            for s in self.sessions.values(): s.revoked = True
            self.sessions.clear()
            server, thread = self.server, self.thread
            self.server = self.thread = None
        if server:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
