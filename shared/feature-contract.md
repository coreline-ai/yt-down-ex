# 기능 1~6 계약 (구현 단계별 capability 공개)

- protocolVersion 1: 기존 프레임 형식 유지. hello는 host version/schemaVersion/capabilities 반환. 미구현 명령은 capability에 포함하지 않는다.
- schemaVersion 1: 기존 jobs 테이블을 유지하는 추가 JSON 필드. 이행 전 SQLite backup API로 `jobs-before-schema-1.sqlite3` 생성. 기존 버전은 미지 필드를 무시하므로 기존 상태 이름에 한해 읽기 가능. 앞으로 retry_wait를 도입하는 단계에서는 구버전 롤백 전에 호스트 유휴·상태 호환 검사 필수.
- outputProfile: original/mp4/mp3. 기존 video는 original, audio는 mp3로 이행. mp4 capability가 생기기 전에는 mp4 실행 불가.
- result: path, size, container, duration, streams의 codec_type/codec_name/width/height. MIME·코덱은 실제 검사 결과로 결정.
- attempt: 최초 1부터 최대 4. nextRetryAt: UTC Unix seconds 또는 null. attemptHistory: 최대 4건의 시각/오류 코드. retry_wait의 attempt는 다음 실행 번호. 5/15/45초 + 0~1초 jitter, 최대 3회 자동 재시도. 대기 중 worker 반환. 종료/재시작 시 interrupted로 보존하며 nextRetryAt 폐기. 수동 재시도는 새 jobId/retryOf.
- playbackPosition: seconds, identity(dev,ino,size,mtime_ns), savedAt. 파일 변경 시 복원하지 않는다. 기록 삭제 시 세션과 위치 함께 폐기.
- openPlayback(jobId): completed 파일만. 반환 sessionId, url, title, result, position, expiresIn. token은 로그/SQLite/chrome.storage에 저장하지 않는다. URI를 열람 가능한 페이지로 공개하지 않는다.
- closePlayback(sessionId): 해당 전송 세션 폐기. 동일 세션 중복 종료는 성공. 임의 파일 경로 입력 없음.
- 재생 세션: 1시간 만료, 최대 16개, 동시 HTTP 요청 최대 8개, 요청 socket 10초 제한, 64 KiB 스트리밍 버퍼. 호스트 종료 시 모든 세션과 포트 폐기.
- 범위 요청: GET/HEAD, 단일 bytes 범위 및 suffix 지원. 정상 200/206, 무효/복수 범위 416. 실패 시 토큰과 파일 경로를 응답에 노출하지 않음.
- 재생 탭은 player runtime port로 호스트 수명 유지. 모든 패널·플레이어·활성 작업이 사라지면 기존 15초 유휴 종료 적용.
- 추가 명령: savePlaybackPosition / deleteJobs / checkUpdate / startUpdate / getUpdateStatus. 구현된 명령을 스키마 enum 및 hello capability에 공개. 업데이트는 단일 긴 요청 대신 영속 작업 상태를 사용.

- 재시도 범위: 연결 종료·일시적 네트워크 시간 초과·HTTP 500/502/503/504. yt-dlp 일반/fragment/extractor/file-access 내부 retries는 0. 429는 원래 주소에 redirect 없는 3초 제한 HEAD로 Retry-After를 확인할 수 있고 1시간 이하일 때만 자동 재시도. 확인 불가/상한 초과는 수동 재시도 안내. 변환/검증/파일/DB 오류는 자동 재시도하지 않는다.

- getSnapshot(filter,search,cursor): DB 전체 검색, created/id 내림차순 커서, 최대 10건 및 200 KiB 본문 한도. activeJobIds/activeCount는 페이지와 무관한 전체 작업 기준. storageError는 DB 쓰기 장애로 멈춘 큐의 오류. 엔진 재시작 시 미종료 기록은 interrupted로 복구.
- deleteJobs(jobIds): 1~100개, ID 중복 제거, deleted와 항목별 errors 반환. 종료 기록만 삭제. 미디어 파일 보존, jobDeleted 이벤트와 세션 폐기.
- checkUpdate: 공식 PyPI metadata와 내장 버전/해시 대조. status offline/hash_mismatch/up_to_date/available, recommended/current/latest 및 unverifiedLatest 반환. 임의 URL·버전 입력 없음.
- startUpdate(action): install 또는 rollback만 허용. 분석/다운로드/재생 중 거절. update.lock 단일 소유권을 독립 updater로 전달한 뒤 updateHandoff 응답으로 기존 native 연결 종료.
- updater: 공식 고정 wheel의 SHA-256 확인, 별도 venv 생성, 진단 및 DB 호환성 확인 후 활성화. ensurepip 45초, 패키지 설치 180초, 기존 host.lock 대기 20초 제한. updater 잠금 중 새 연결은 Jobs를 열지 않고 상태 조회만 처리.
- getUpdateStatus: queued/waiting/downloading/installing/diagnosing/activating/rolling_back/completed/failed/interrupted/idle. 종료 후 updateReconnect로 새 활성 엔진에 연결. 상태 파일에는 재생 토큰이나 미디어 URL을 넣지 않음.
- DB 쓰기 실패 시 engineError(DB_WRITE_FAILED)를 알리고 큐를 일시 중지. 새 다운로드를 거절하며 패널·재생 탭 종료 후 정상 유휴 종료를 허용. 파일 게시 후 기록 쓰기 실패라면 완성 파일이 폴더에 남을 수 있으나 완료로 표시하거나 자동 재시도하지 않음.
