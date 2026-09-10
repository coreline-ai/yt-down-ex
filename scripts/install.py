#!/usr/bin/env python3
"""Install a user-scoped native host; immutable releases enable atomic rollback."""
import argparse
import contextlib
import fcntl
import json
import os
import platform
import shlex
import signal
import shutil
import subprocess
import sys
import time
import uuid
import venv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
IDENTITY=json.loads((ROOT/'shared/extension-id.json').read_text())
DEFAULT_ROOT=Path.home()/'Library/Application Support/Stash Local'
DEFAULT_BROWSER=Path.home()/'Library/Application Support/Google/Chrome'
MARKER='stash-local-install-v1'

def atomic_json(path,data):
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');os.chmod(temp,0o600);os.replace(temp,path)

def run_bounded(command,timeout,**kwargs):
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,**kwargs)
    try:
        output,error=process.communicate(timeout=timeout)
        if process.returncode:raise RuntimeError('엔진 설치 명령이 실패했습니다.')
        return output
    except BaseException:
        if process.poll() is None:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.communicate()
        raise

def preflight():
    if sys.version_info<(3,11):raise RuntimeError('Python 3.11 이상이 필요합니다.')
    tools={}
    for name in ('ffmpeg','ffprobe','node'):
        runtime=json.loads((ROOT/'runtime.json').read_text()) if (ROOT/'runtime.json').is_file() else {}
        path=runtime.get(name) or shutil.which(name)
        if not path:
            if name=='node':continue
            raise RuntimeError(f'{name}가 없습니다. FFmpeg 공식 설치 안내를 참고해 설치 후 다시 실행하세요.')
        result=subprocess.run([path,'--version' if name=='node' else '-version'],capture_output=True,text=True,timeout=10)
        if result.returncode:raise RuntimeError(f'{name} 실행에 실패했습니다.')
        tools[name]=str(Path(path).absolute())
    return tools

def safe_root(root):
    root=Path(root).expanduser().absolute()
    if any(p.is_symlink() for p in (root,*root.parents)):raise RuntimeError('설치 경로에 심볼릭 링크가 있습니다.')
    if root.exists() and any(root.iterdir()) and not (root/'.owner').is_file():
        raise RuntimeError('앱이 소유하지 않은 폴더입니다. 다른 설치 경로를 선택하세요.')
    if (root/'.owner').exists() and (root/'.owner').read_text()!=MARKER:raise RuntimeError('설치 소유권 표식이 올바르지 않습니다.')
    return root

@contextlib.contextmanager
def installation_lock(root,wait=0):
    lock=(root/'host.lock').open('a+')
    try:
        deadline=time.monotonic()+wait
        while True:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.monotonic()>=deadline:raise RuntimeError('로컬 엔진이 실행 중입니다. 패널을 닫고 15초 후 다시 시도하세요.')
                time.sleep(.1)
        yield
    finally:lock.close()

def run_diagnose(root,release=None):
    if release is None:release=json.loads((root/'active.json').read_text())
    process=subprocess.run([release['python'],'-c','import json;from native.host import diagnose;print(json.dumps(diagnose()))'],cwd=release['release'],capture_output=True,text=True,timeout=45,env={**os.environ,'STASH_DATA_DIR':str(root)})
    if process.returncode:raise RuntimeError('설치된 엔진 진단을 실행하지 못했습니다.')
    result=json.loads(process.stdout)
    if not result['ready'] or result.get('compatible') is False:raise RuntimeError('필수 엔진 또는 검증된 버전 조합 진단이 실패했습니다.')
    return result

def validate_database(root,diagnostics):
    if diagnostics.get('protocolVersion',1)!=1:raise RuntimeError('지원하지 않는 엔진 프로토콜 버전입니다.')
    import sqlite3
    if (root/'jobs.sqlite3').exists():
        with sqlite3.connect('file:'+str(root/'jobs.sqlite3')+'?mode=ro',uri=True) as db:
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version>diagnostics.get('schemaVersion',0):raise RuntimeError('엔진이 현재 기록 DB 버전을 지원하지 않습니다.')

def install(root,browser,wheel_dir=None,*,wait=0,progress=lambda *_:None):
    tools=preflight();root=safe_root(root)
    root.mkdir(parents=True,exist_ok=True);os.chmod(root,0o700);(root/'.owner').write_text(MARKER)
    host_manifest=Path(browser)/'NativeMessagingHosts'/f"{IDENTITY['host']}.json"
    if host_manifest.is_symlink():raise RuntimeError('호스트 등록 파일이 심볼릭 링크입니다.')
    if host_manifest.exists() and json.loads(host_manifest.read_text()).get('path')!=str(root/'host'):
        raise RuntimeError('다른 설치의 호스트가 이미 등록되어 있습니다. 해당 설치를 먼저 제거하세요.')
    with installation_lock(root,wait):
        release_path=root/'releases'/(time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);release_path.mkdir(parents=True)
        previous=(root/'active.json').read_bytes() if (root/'active.json').exists() else None
        old_manifest=host_manifest.read_bytes() if host_manifest.exists() else None
        try:
            shutil.copytree(ROOT/'native',release_path/'native',ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT/'shared',release_path/'shared')
            (release_path/'scripts').mkdir();shutil.copy(ROOT/'scripts/install.py',release_path/'scripts/install.py')
            env_path=release_path/'venv';venv.EnvBuilder(with_pip=False,symlinks=True).create(env_path)
            python=str(env_path/'bin/python3')
            run_bounded([python,'-m','ensurepip','--upgrade','--default-pip'],45)
            command=[python,'-m','pip','install','--disable-pip-version-check','--require-hashes','--retries','0','--timeout','20','-r',str(ROOT/'requirements-engine.txt')]
            if wheel_dir:command+=['--no-index','--find-links',str(Path(wheel_dir).resolve())]
            run_bounded(command,180)
            tools['yt-dlp']=str(env_path/'bin/yt-dlp');atomic_json(release_path/'runtime.json',tools)
            shutil.copy(ROOT/'requirements-engine.txt',release_path/'requirements-engine.txt')
            release={'release':str(release_path),'python':python}
            progress('diagnosing','새 엔진과 호환성을 진단합니다.')
            diagnostics=run_diagnose(root,release)
            validate_database(root,diagnostics)
            atomic_json(release_path/'diagnostics.json',diagnostics)
            bootstrap=root/'bootstrap.py'
            bootstrap.write_text('import json,os,sys\nfrom pathlib import Path\nroot=Path(__file__).resolve().parent\nr=json.loads((root/"active.json").read_text())\np=Path(r["release"]).resolve()\nif not p.is_relative_to((root/"releases").resolve()):raise SystemExit(2)\nos.environ["STASH_DATA_DIR"]=str(root)\nos.chdir(p)\nos.execv(r["python"],[r["python"],"-m","native.host",*sys.argv[1:]])\n')
            launcher=root/'host';launcher.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(str(bootstrap))+' "$@"\n');launcher.chmod(0o700)
            progress('activating','검증을 통과한 엔진을 활성화합니다.')
            if previous:atomic_json(root/'previous.json',json.loads(previous))
            atomic_json(root/'active.json',release)
            host_manifest.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(host_manifest,{'name':IDENTITY['host'],'description':'Stash Local media downloader','path':str(launcher),'type':'stdio','allowed_origins':[f"chrome-extension://{IDENTITY['id']}/"]})
            manifests=json.loads((root/'manifests.json').read_text()) if (root/'manifests.json').exists() else []
            if str(host_manifest) not in manifests:manifests.append(str(host_manifest))
            atomic_json(root/'manifests.json',manifests)
            return {'installed':str(root),'manifest':str(host_manifest),'extensionId':IDENTITY['id'],'diagnostics':diagnostics}
        except BaseException:
            if previous:atomic_json(root/'active.json',json.loads(previous))
            else:(root/'active.json').unlink(missing_ok=True)
            if old_manifest:host_manifest.write_bytes(old_manifest)
            elif host_manifest.exists():host_manifest.unlink()
            shutil.rmtree(release_path)
            raise

def rollback(root,*,wait=0):
    root=safe_root(root)
    with installation_lock(root,wait):
        previous=json.loads((root/'previous.json').read_text())
        release_path=Path(previous['release']).resolve()
        if not release_path.is_relative_to((root/'releases').resolve()):raise RuntimeError('이전 릴리스 경로가 올바르지 않습니다.')
        diagnostics=run_diagnose(root,previous)
        validate_database(root,diagnostics)
        current=json.loads((root/'active.json').read_text());atomic_json(root/'active.json',previous);atomic_json(root/'previous.json',current)
    return {'rolledBack':previous['release']}

def uninstall(root):
    root=safe_root(root)
    if not root.exists():return {'uninstalled':False}
    with installation_lock(root):
        manifests=json.loads((root/'manifests.json').read_text()) if (root/'manifests.json').exists() else []
        for filename in manifests:
            path=Path(filename)
            if path.is_symlink():continue
            if path.is_file() and json.loads(path.read_text()).get('path')==str(root/'host'):path.unlink()
        # This dedicated root contains only the host, its private environment and history.
        # Download output lives elsewhere and is never traversed.
        shutil.rmtree(root)
    return {'uninstalled':True,'downloadsPreserved':True}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--browser-data-dir',type=Path,default=DEFAULT_BROWSER)
    parser.add_argument('--wheel-dir',type=Path)
    group=parser.add_mutually_exclusive_group();group.add_argument('--diagnose',action='store_true');group.add_argument('--uninstall',action='store_true');group.add_argument('--rollback',action='store_true')
    args=parser.parse_args()
    try:
        root=args.root.expanduser().absolute()
        if args.diagnose:result=run_diagnose(root)
        elif args.uninstall:result=uninstall(root)
        elif args.rollback:result=rollback(root)
        else:
            if platform.system()!='Darwin':raise RuntimeError('이 설치 도구는 macOS용입니다.')
            result=install(root,args.browser_data_dir,args.wheel_dir)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as error:
        print(f'설치/진단 실패: {error}',file=sys.stderr);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
