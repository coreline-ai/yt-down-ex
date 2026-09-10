import functools
import http.server
import subprocess
import threading
import time
from pathlib import Path
from native.config import tool

class MediaServer:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.requests=[]
        media=self.root/'sample.mp4'
        if not media.exists():
            subprocess.run([tool('ffmpeg'),'-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=320x180:rate=15','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart','-y',str(media)],check=True)
            subprocess.run([tool('ffmpeg'),'-hide_banner','-loglevel','error','-i',str(media),'-map','0:v','-map','0:a','-c','copy','-f','dash','-seg_duration','1','-adaptation_sets','id=0,streams=v id=1,streams=a',str(self.root/'manifest.mpd')],check=True)
        requests=self.requests
        owner=self;self.failures=0;self.resets=0
        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_HEAD(self):
                if self.path in ("/transient.mp4","/reset.mp4"):self.path="/sample.mp4"
                if self.path=="/limited.mp4":
                    self.send_response(429);self.send_header("Retry-After","3601");self.end_headers();return
                if self.path=="/slow.mp4":
                    self.send_response(200);self.send_header("Content-Type","video/mp4");self.send_header("Content-Length",str(media.stat().st_size));self.end_headers();return
                super().do_HEAD()
            def do_GET(self):
                requests.append(self.path)
                if self.path=='/limited.mp4':self.send_error(429);return
                if self.path=='/reset.mp4':
                    if owner.resets==0:
                        owner.resets+=1;self.connection.close();return
                    self.path='/sample.mp4'
                if self.path=='/transient.mp4':
                    if owner.failures==0:
                        owner.failures+=1;self.send_error(503);return
                    self.path='/sample.mp4'
                if self.path=='/identity.mp4':
                    if self.headers.get('User-Agent')!='StashLocal/0.1':
                        self.send_error(403);return
                    self.path='/sample.mp4'
                if self.path=='/slow.mp4':
                    self.send_response(200);self.send_header('Content-Type','video/mp4');self.send_header('Content-Length',str(media.stat().st_size));self.end_headers()
                    try:
                        data=media.read_bytes()
                        for start in range(0,len(data),512):
                            self.wfile.write(data[start:start+512]);self.wfile.flush();time.sleep(.1)
                    except (BrokenPipeError,ConnectionResetError):pass
                    return
                if self.path=='/long.html':
                    self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(('<html><title>'+('아주 긴 제목 '*50)+'&lt;script&gt;alert(1)&lt;/script&gt;</title><video src="/sample.mp4"></video></html>').encode());return
                if self.path=='/error.html':
                    self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(b'<html>Not media</html>');return
                super().do_GET()
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(self.root)))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join()
