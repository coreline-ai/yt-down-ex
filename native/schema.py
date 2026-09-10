"""Additive database versioning. Version 1 remains readable by the previous host."""
import sqlite3
import json
import os
from native.config import AppError
SCHEMA_VERSION = 1

def migrate(db, data):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > SCHEMA_VERSION:
        raise AppError('DB_VERSION_UNSUPPORTED', '더 새로운 버전의 작업 기록입니다. 호환되는 엔진으로 업데이트하세요.')
    if version == 0:
        existing = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
        if existing:
            backup_path = data / 'jobs-before-schema-1.sqlite3'
            if not backup_path.exists():
                temporary = backup_path.with_suffix('.tmp')
                backup = sqlite3.connect(temporary)
                try: db.backup(backup)
                finally: backup.close()
                os.replace(temporary, backup_path)
        if existing and 'data' in {row[1] for row in db.execute('PRAGMA table_info(jobs)')}:
            for job_id, raw in db.execute('SELECT id,data FROM jobs').fetchall():
                job = json.loads(raw)
                job.setdefault('outputProfile', 'mp3' if job.get('mode') == 'audio' else 'original')
                job.setdefault('attempt', 1)
                job.setdefault('nextRetryAt', None)
                job.setdefault('attemptHistory', [])
                job.setdefault('playbackPosition', None)
                db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(job, ensure_ascii=False), job_id))
        db.execute('PRAGMA user_version=1')
        db.commit()
