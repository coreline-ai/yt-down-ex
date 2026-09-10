"""MP4 compatibility conversion; never publish an unverified temporary output."""
import math
import time
from native.config import tool, AppError


def compatible_video(stream):
    return stream.get('codec_name') == 'h264' and stream.get('pix_fmt') == 'yuv420p'


def to_mp4(source, probe, runner, emit):
    from native.engine import verify_media
    output = source.with_name('compatible.mp4')
    video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    audios = [s for s in probe['streams'] if s['codec_type'] == 'audio']
    copy_video = compatible_video(video)
    copy_audio = not audios or audios[0].get('codec_name') == 'aac'
    args = [tool('ffmpeg'), '-hide_banner', '-nostdin', '-loglevel', 'error', '-n', '-i', str(source),
            '-map', '0:v:0', '-map', '0:a:0?', '-c:v', 'copy' if copy_video else 'libx264']
    if not copy_video:
        args += ['-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2']
    args += ['-c:a', 'copy' if copy_audio else 'aac']
    if not copy_audio: args += ['-b:a', '192k']
    args += ['-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', str(output)]
    emit({'state': 'postprocessing', 'progress': 0, 'processing': 'remux' if copy_video and copy_audio else 'convert'})
    last = 0
    def line(text):
        nonlocal last
        if not text.startswith('out_time_us='): return
        try: seconds = float(text.split('=',1)[1]) / 1_000_000
        except ValueError: return
        now = time.monotonic()
        if now-last < .25 or not math.isfinite(seconds): return
        last=now
        emit({'progress': max(0, min(99, seconds/probe['duration']*100))})
    try:
        runner.phase_deadline = time.monotonic()+600
        runner.run(args,line,timeout=600,idle=90)
    except AppError as error:
        if error.code in ('CANCELLED','TIMEOUT','OUTPUT_TOO_LARGE'):raise
        raise AppError('CONVERSION_FAILED','MP4 변환에 실패했습니다. 저장 공간과 FFmpeg 상태를 확인하세요.')
    result=verify_media(output,'video',runner)
    if not all(compatible_video(s) for s in result['streams'] if s['codec_type']=='video') or any(s.get('codec_name')!='aac' for s in result['streams'] if s['codec_type']=='audio'):
        raise AppError('VERIFY_FAILED','MP4 호환 코덱 검증에 실패했습니다.')
    if abs(result['duration']-probe['duration']) > .5:
        raise AppError('VERIFY_FAILED','변환 전후 영상 길이가 일치하지 않습니다.')
    return output,result
