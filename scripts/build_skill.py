"""Build an independent skill from its source and the canonical media engine."""
import hashlib
import shutil
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MODULES=('__init__.py','config.py','engine.py','convert.py','preview.py','retry.py','guard.py')
def build(output=None):
    output=Path(output or ROOT/'artifacts/skill');target=output/'stash-media'
    if target.exists():shutil.rmtree(target)
    shutil.copytree(ROOT/'skills/stash-media',target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    engine=target/'scripts/engine/native';engine.mkdir(parents=True)
    for name in MODULES:shutil.copy2(ROOT/'native'/name,engine/name)
    shutil.copy2(ROOT/'requirements-engine.txt',target/'scripts/requirements-engine.txt')
    paths=sorted(p for p in target.rglob('*') if p.is_file())
    (target/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(target).as_posix()+'\n' for p in paths))
    archive=output.parent/'stash-media.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(target.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(output))
    return target,archive
if __name__=='__main__':
    for p in build():print(p)
