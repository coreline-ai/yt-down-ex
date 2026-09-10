import subprocess
import venv
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
(root/'artifacts/wheels').mkdir(parents=True,exist_ok=True)
subprocess.run(['python3','-m','pip','download','--require-hashes','-r',str(root/'requirements-engine.txt'),'--dest',str(root/'artifacts/wheels')],check=True)
venv.EnvBuilder(with_pip=True).create(root/'.venv')
subprocess.run([str(root/'.venv/bin/python3'),'-m','pip','install','--disable-pip-version-check','--no-index','--find-links',str(root/'artifacts/wheels'),'--require-hashes','-r',str(root/'requirements-engine.txt')],check=True)
subprocess.run(['npx','playwright','install','chromium'],check=True,env={**__import__('os').environ,'PLAYWRIGHT_BROWSERS_PATH':str(root/'.browsers')})
