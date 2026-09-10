"""Bounded display metadata. No raw extractor JSON, credentials or remote scripts."""
import base64
import math
import tempfile
import time
import urllib.request
from pathlib import Path
from native.config import AppError,tool


def finite(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0 else None


def summarize(info):
    formats=info.get('formats') or [info]
    heights=sorted({f['height'] for f in formats if isinstance(f.get('height'),int) and f['height']>0},reverse=True)[:30]
    def presence(field):
        values=[f.get(field) for f in formats]
        if any(v and v!='none' for v in values):return True
        if values and all(v=='none' for v in values):return False
        return None
    # Prefer the exact selected format size; do not add incompatible alternatives.
    requested=info.get('requested_formats') or [info]
    sizes=[finite(f.get('filesize')) for f in requested]
    exact=bool(sizes) and all(n is not None for n in sizes)
    if not exact:sizes=[finite(f.get('filesize') or f.get('filesize_approx')) for f in requested]
    total=sum(sizes) if sizes and all(n is not None for n in sizes) else None
    return {'title':str(info.get('title') or info.get('id') or '미디어')[:300], 'duration':finite(info.get('duration')),
            'heights':heights,'extractor':str(info.get('extractor_key','Generic'))[:80],
            'hasVideo':presence('vcodec'),'hasAudio':presence('acodec'),'size':total,'sizeIsEstimate':not exact if total is not None else None,
            'thumbnail':None}


def thumbnail(url,runner):
    from native.engine import validate_url
    if not url:return None
    try:
        url=validate_url(url);start=time.monotonic()
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'StashLocal/0.1'}),timeout=3) as response:
            validate_url(response.url)
            if not response.headers.get('Content-Type','').lower().startswith('image/'):return None
            data=bytearray()
            while len(data)<=2*1024*1024:
                if runner.cancelled.is_set():raise AppError('CANCELLED','분석을 취소했습니다.')
                if time.monotonic()-start>6:return None
                chunk=response.read(16384)
                if not chunk:break
                data.extend(chunk)
            if len(data)>2*1024*1024:return None
        with tempfile.TemporaryDirectory(prefix='stash-thumb-') as folder:
            source=Path(folder)/'input';output=Path(folder)/'thumb.jpg';source.write_bytes(data)
            runner.run([tool('ffmpeg'),'-v','error','-nostdin','-protocol_whitelist','file,pipe','-max_pixels','16000000','-i',str(source),'-frames:v','1','-vf','scale=240:135:force_original_aspect_ratio=decrease','-q:v','6',str(output)],timeout=5,idle=5)
            encoded=output.read_bytes()
            if len(encoded)>64*1024:return None
            return 'data:image/jpeg;base64,'+base64.b64encode(encoded).decode()
    except AppError as e:
        if e.code=='CANCELLED':raise
        return None
    except (OSError,ValueError):return None
