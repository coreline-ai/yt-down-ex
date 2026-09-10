import datetime
import hashlib
import json
import subprocess
import sys
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from native.engine import Runner
from native.config import AppError,tool
from native.host import diagnose
URL='https://download.blender.org/peach/trailer/trailer_400p.ogg'
ATTRIBUTION='Big Buck Bunny trailer © 2008 Blender Foundation / www.bigbuckbunny.org — CC BY 3.0 — https://peach.blender.org/about/'

def main():
    directory=ROOT/'artifacts/external';directory.mkdir(parents=True,exist_ok=True)
    report={'url':URL,'source':'https://peach.blender.org/about/','attribution':ATTRIBUTION,'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'environment':diagnose(),'status':'running'}
    previous=None
    def progress(event):
        nonlocal previous
        state=event.get('state')
        if state and state!=previous:print(state,flush=True);previous=state
    try:
        result=Runner().download(URL,'video','best',str(directory),uuid.uuid4().hex,progress,'mp4')
        subprocess.run([tool('ffmpeg'),'-v','error','-xerror','-i',result['path'],'-f','null','-'],capture_output=True,check=True,timeout=90)
        with open(result['path'],'rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        report.update(status='passed',result=result,sha256=digest,decodeExitCode=0)
        (directory/'ATTRIBUTION.txt').write_text(ATTRIBUTION+'\n')
        print(json.dumps(result,ensure_ascii=False),flush=True)
    except Exception as error:
        report.update(status='failed',error=error.as_dict() if isinstance(error,AppError) else {'code':type(error).__name__,'message':'외부 파일 검증 실패'})
    (directory/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
