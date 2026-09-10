import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('STASH_DATA_DIR', Path.home() / 'Library/Application Support/Stash Local'))
DEFAULT_OUTPUT = Path(os.environ.get('STASH_OUTPUT_DIR', Path.home() / 'Downloads/yt-down-interface'))

def tool(name):
    config = ROOT / 'runtime.json'
    if not config.exists(): config = DATA / 'tools.json'
    settings = json.loads(config.read_text()) if config.exists() else {}
    project_tool = ROOT / '.venv/bin' / name
    path = settings.get(name) or (str(project_tool) if project_tool.is_file() else shutil.which(name))
    if not path or not Path(path).is_file() or not os.access(path, os.X_OK):
        raise AppError('DEPENDENCY_MISSING', f'{name} 실행 파일을 찾을 수 없습니다. 설치 진단을 실행하세요.')
    return str(Path(path).absolute())

class AppError(Exception):
    def __init__(self, code, message, retryable=False, retry_after=None):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable
        self.retry_after=retry_after
    def as_dict(self):
        return {'code':self.code, 'message':self.message, 'retryable':self.retryable,**({'retryAfter':self.retry_after} if self.retry_after is not None else {})}
