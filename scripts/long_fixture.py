"""Generate and fully decode a 30-minute synthetic H.264/AAC validation video."""
import hashlib,json,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native.config import tool
from native.engine import verify_media
root=Path('artifacts/long');root.mkdir(parents=True,exist_ok=True);path=root/'synthetic-30min.mp4'
start=time.monotonic()
subprocess.run([tool('ffmpeg'),'-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=2','-f','lavfi','-i','sine=frequency=440:sample_rate=22050','-t','1800','-c:v','libx264','-preset','ultrafast','-crf','35','-pix_fmt','yuv420p','-c:a','aac','-b:a','48k','-movflags','+faststart','-y',str(path)],check=True,timeout=120)
probe=verify_media(path,'video');subprocess.run([tool('ffmpeg'),'-v','error','-xerror','-i',str(path),'-f','null','-'],check=True,timeout=120)
report={'source':'FFmpeg synthetic testsrc2 + sine, not external download','path':str(path.resolve()),'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'media':probe,'decodeExitCode':0,'generationAndDecodeSeconds':round(time.monotonic()-start,3)}
(root/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
