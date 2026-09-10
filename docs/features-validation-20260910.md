# 기능 1~6 구현·검증 기록 — 2026-09-10

**상태: 기능 1~6 구현·사용자 Chrome 적용·인수 검증 완료. 최종 자동 검사는 Python 59개 통과, E2E 최초 9개 통과와 업데이트 1개 재검증 통과를 합산한 결과다.**

작업 계획: `dev-plan/implement_20260910_164023.md`. 코드 자체 검토와 실제 실행 검증이며 독립 외부 감사는 아니다.

## 구현 범위

| 기능 | 구현과 증거 |
|---|---|
| MP4 호환 저장 | H.264/yuv420p + AAC, 필요 시 변환·호환 시 remux, 무음 구분. 7종 원본/충돌/취소/실패 검사와 실제 외부 원본 변환 |
| 미리보기 | 분석 필수, URL 변경 시 취소·오래된 응답 배제, 메타데이터 미확인 구분, 명시적 다운로드 클릭 |
| 기록 관리 | 전체 DB 검색/필터/커서, 선택·실패 일괄 삭제, 다중 패널 동기화, 재생 세션 폐기, 파일 바이트 보존 |
| 자동 재시도 | 일시 오류만 5/15/45초 + 최대 1초 jitter, 최초 포함 최대 4회. 대기 중 worker 반환. 429 확인/상한 정책, 취소·재시작 중단 |
| 엔진 업데이트 | 공식 버전/해시 허용 목록, 별도 환경 설치·진단·활성화, 상태 조회용 연결, 실패 보존·롤백·DB 호환 검사 |
| 재생 | 실제 Chrome MP4 재생, 탐색·음량·배속·전체화면·이어보기, 세션 제한/만료/철회, 루프백 Range 전송 |

## 자동 검증 증거

- `artifacts/phase8-verify.log`: 타입 검사·빌드, Python **58개**, 격리 Chromium 확장 E2E **10개** 통과.
- `artifacts/phase8-final-verify.log`: 마지막 DB 오류 안내/유휴 종료·목록 응답 순서 보완 후 최종 재검사도 타입 검사·빌드, Python **58개**, E2E **10개** 통과. 이후 오류 분류 문자열의 작은 보완은 재시도 6개 회귀로 추가 검증했다.
- `artifacts/phase6-retry.log`, `phase6-e2e.log`: 실제 로컬 HTTP 503/연결 종료 후 회복, 429 상한 초과 시 1회 종료, 취소·중복 저장 방지. 정책 시간은 네이티브 테스트에 주입하고 UI 테스트는 기본 대기 시간을 사용.
- `artifacts/phase7-native.log`: 설치/복구 8개 통과. 정상/동일 버전·오프라인 metadata·해시 불일치·설치/진단 실패·중간 프로세스 종료·복원·DB/파일 보존.
- `artifacts/phase7-e2e.log`: 실제 설치된 엔진 GUI에서 진행 작업/재생 중 업데이트 거절 → 해시 실패 → 검증 버전 재설치 → 이전 릴리스 복원 → 다운로드/재생 통과. 버전 자체를 올린 테스트가 아니라 같은 검증 버전으로 새 릴리스를 설치한 테스트임.
- `artifacts/phase5-file-preservation.log`: 완료 기록 일괄 삭제, 다른 패널 동기화, 새로고침 후 삭제 유지 및 실제 파일 바이트 동일성.
- `artifacts/phase8-retry-classification.log`: URL에 포함된 단어를 시간 초과 오류로 오분류하지 않는 보완 회귀.

## 긴 영상·대용량·기록 규모

- 30분 합성 영상: `artifacts/long/synthetic-30min.mp4`, **23,591,438 bytes**, **1,800초**, H.264 320×180/yuv420p + AAC. 전체 디코딩 exit 0.
- 합성 영상 SHA-256: `d79f33738eba1898d4d9b1779449fd3d56168531995ee355c050e9c1e0e80567`.
- 실제 Google Chrome **152.0.7977.84**의 독립 프로필/사이드 패널에서 다운로드, 재생, **900초로 탐색 후 900.826548초까지 진행**, readyState 4 확인. `artifacts/long/chrome-report.json`, `chrome-player.png`, `artifacts/phase8-long-chrome.log`.
- 30분 동안 연속 재생했다는 뜻이 아니다. 30분 길이의 영상 파일을 생성해 전체 디코딩하고 시작/중간 재생을 검사했다.
- 1 GiB 합성 바이트 Range 206 전송: **1,073,741,824 bytes**, 약 **0.66초**, Python 추적 메모리 피크 약 **0.3 MB**, 고정 64 KiB 버퍼. `artifacts/large-transfer.json`. 영상 다운로드나 전체 프로세스 RSS 측정과 구분한다. 서버 종료 후 포트 재연결 거절 확인.
- 1,000개 기록 생성/검색/커서 순회/삭제 약 **0.09초**. 한글/특수문자·페이지 경계·삭제 후 누락/중복 검사. `artifacts/phase8-final-verify.log`.

## 외부 다운로드 — 실제 MP4 결과

Blender Big Buck Bunny의 공개 OGG 주소를 현재 MP4 호환 프로필로 내려받아 변환했다. 원본 주소: <https://download.blender.org/peach/trailer/trailer_400p.ogg>. 출처/라이선스: [Blender Foundation, CC BY 3.0](https://peach.blender.org/about/).

- 파일: `/Users/iriver/Documents/ChatGPT/yt-down-interface/artifacts/external/trailer_400p.mp4`
- **3,112,274 bytes**, **32.997초**, H.264 **720×400/yuv420p** + AAC, MP4.
- 전체 디코딩 exit **0**.
- SHA-256: `f202aed8cd0c1094d65cd6721c397268e89f0f9f0d6d925c7db3137589b6d8e0`.
- 증거: `artifacts/external/report.json`, `artifacts/phase8-external.log`.

이 결과는 실제 MP4 변환·디코딩 성공이며, 이번 최종 빌드의 사용자 Chrome Computer Use 재생 검증을 대신하지 않는다.

## 사용자 Chrome에서 앞서 완료한 검증

Phase 3에서 Computer Use로 W3 Sintel 영상 다운로드·재생, 24초 이상 재생 시간 증가, 28.4초 일시 정지, ±10초 탐색, 배속 1.5, 음소거/음량, 전체화면, 닫기 후 28.4초 이어보기를 확인했다.

- 파일: `/Users/iriver/Downloads/yt-down-interface/trailer (1).mp4`
- **4,369,172 bytes**, **52.208333초**, H.264 **854×480/yuv420p** + AAC.
- 전체 디코딩 exit 0, SHA-256 `7348e88c23eb286cb3bda36e9f325063498241b22bb04fa75d2f3cf9fc51bad9`.
- 증거: `artifacts/phase3-cua.json` 및 해당 실행의 Computer Use 화면.

초기에는 Mac 잠금으로 최종 인수 검증이 차단됐으나, 사용자 잠금 해제 후 아래 최종 사용자 Chrome 검증을 완료했다. 현재 설치 호스트와 최종 소스가 일치하며 확장 재로드도 완료했다. `artifacts/phase8-application-status.json` 참조.

## 발견·수정한 주요 문제

1. `2026.6.9`와 `2026.06.09`를 다른 버전으로 판단하던 호환 검사: 숫자 버전 구성요소 비교로 수정.
2. Chrome 자식 updater의 복사된 Python 실행 파일이 dyld 시작점에 정지: 설치된 Python을 참조하는 venv 사용, ensurepip 45초/설치 180초 제한과 프로세스 그룹 종료 추가. 수정 후 실제 GUI 설치 성공.
3. 업데이트 상태를 조회하려고 재연결한 호스트가 설치 잠금을 점유할 가능성: updater 실행 중 DB를 열지 않는 상태 조회 경로 추가.
4. DB 쓰기 장애가 worker를 종료시킬 가능성: 큐 중지·오류 안내·신규 작업 거절. 쓰기 불가 상태에서도 호스트 종료 시 잠금을 해제하며 다음 시작 시 미완료 기록을 중단 상태로 복구. 게시된 파일의 기록 저장 실패는 완료로 표시하지 않음.
5. 오래된 목록 응답이 새 검색/조회 결과를 덮을 가능성: 검색 세대와 조회 순서 검사.
6. 산출 로그/JSON/Markdown에서 재생 `/media/<token>` 패턴을 검색해 노출 없음 확인. 실제 URL과 미디어 파일 경로는 의도된 작업 기록/결과 보고에 포함됨.

## 제한

Google ForBiggerFun 샘플의 익명 접근 거부는 해결됐다고 보고하지 않는다. YouTube 실제 다운로드, 모든 사이트·코덱, 실제 디스크 전체 소진·물리 저장장치 손상, 30분 연속 시청을 검증한 것은 아니다. 외부 접근 제한 우회, Chrome 종료 후 계속 다운로드, 웹 스토어 배포, 서명/공증 설치 패키지, Windows/Linux는 범위 밖이다.

공식 엔진 검증 목록 출처: [yt-dlp PyPI 배포](https://pypi.org/pypi/yt-dlp/2026.6.9/json), [yt-dlp-ejs PyPI 배포](https://pypi.org/pypi/yt-dlp-ejs/0.8.0/json). 실행 환경: macOS 26.5.2 arm64, Python 3.11.15, Node.js 22.22.2, FFmpeg/ffprobe 8.0.1.


## 최종 사용자 Chrome 검증 추가 — 잠금 해제 후 재개

Mac 잠금 해제 후 사용자 Chrome에서 로컬 엔진 설치와 확장 0.2.0 재로드를 수행했다. `artifacts/phase8-user-install.log`에 설치 결과가 있으며, 아래 경로는 Computer Use로 직접 조작했다.

1. W3 주소 입력 → 주소 분석 완료(누락 메타데이터는 미확인) → MP4 호환 선택 → 다운로드 버튼 → `trailer (2).mp4` 생성.
2. 실제 영상/Chrome 오디오 재생 표시·시간 증가, ±10초·음량 0.95·음소거·1.5배속·전체화면, 탭 닫기 후 **20.807509초** 복원.
3. 재생 탭이 열린 상태의 엔진 설치 요청 거절. 탭 종료 후 GUI 검증 버전 재설치 완료, 이전 릴리스 복원 완료, 설치 경로 전환과 원래 기록/파일 보존 확인.
4. 복원 후 같은 외부 주소를 다시 분석·다운로드하여 `trailer (3).mp4` 생성. 실제 영상 재생 10초→29초 증가, 탭 재개방 시 **29.3초** 복원.
5. 이번 검증 중간 기록 `(2)`만 선택 삭제. 원래 `(1)` 기록과 최종 `(3)` 기록 유지, `(2)` 파일 SHA-256 동일. 완료 필터/사이트 검색 2건, 실패 필터 0건 확인.

최종 사용자 파일: `/Users/iriver/Downloads/yt-down-interface/trailer (3).mp4`, **4,369,172 bytes**, **52.208333초**, H.264 **854×480/yuv420p** + AAC. 전체 디코딩 exit 0, SHA-256 `7348e88c23eb286cb3bda36e9f325063498241b22bb04fa75d2f3cf9fc51bad9`.

증거 JSON: `artifacts/phase8-user-cua.json`, `phase8-user-update.json`, `phase8-user-history.json`. 실제 Computer Use 화면: `phase8-cua-playback.png`, `phase8-cua-resume.png`, `phase8-cua-fullscreen.png`, `phase8-cua-rollback.png`, `phase8-cua-history-delete.png`.

기록 선택 검증 중 이어보기 저장 이벤트가 목록 DOM 전체를 교체하는 문제를 추가 발견했다. 화면에 표시하는 필드가 바뀔 때만 목록을 갱신하도록 수정했다. 재생 위치가 갱신돼도 체크박스 DOM과 포커스가 유지되는 회귀를 추가했으며, `artifacts/phase8-final-ui-regression.log` E2E 10개 통과 후 실제 Chrome 선택 삭제도 성공했다.

최종 계약 대조에서 hello에 확장/호스트 버전을 분리해 반환하고 미지원 명령에 업데이트 안내를 추가했다. 썸네일 미제공 시 기본 아이콘도 추가했다. 이 최종 보완은 아래 검사와 최종 설치 적용 기록으로 확인했다.

## 최종 완료 대조

- 최종 타입 검사·빌드·Python **59개** 통과: `artifacts/phase8-release-verify.log`.
- 같은 실행의 E2E는 **9개 통과·업데이트 1개 실패**, 전체 명령 exit **1**. 엔진 파일 수신 단계에서 일반 설치/진단 오류로 종료되어 기대한 해시 오류에 도달하지 않았다. 세부 수신 오류는 기록되지 않아 원인을 확정하지 않는다.
- 코드 변경 없이 같은 업데이트 E2E 재실행: **1개 통과**, **24.7초**, exit **0**. 해시 오류 시 기존 엔진 보존→재설치→롤백→다운로드/재생을 모두 검증했다. `artifacts/phase8-release-update-recheck.log`. 첫 실행 실패는 위 로그에 보존한다. 공식 파일 수신을 사용하는 E2E는 외부 네트워크 상태의 영향을 받는다.
- 최종 설치: `artifacts/phase8-release-user-install.log`, 활성 릴리스 `20260910_182723_1e0abf71`. native Python/공유 JSON/설치 스크립트의 파일 내용이 작업 폴더와 일치. 확장 재로드 후 연결·썸네일 기본 표시·29초 이어보기 확인: `phase8-cua-final-preview.png`, `phase8-cua-final-ready.png`.
- 최신 규모 검사: 1 GiB 전송 **0.873초**, Python 추적 메모리 피크 **295,229 bytes**; 1,000개 기록 **0.065초**. 앞선 측정값은 당시 실행 기록이다.

| 요구 | 완료 근거 |
|---|---|
| 1 MP4 저장 | 변환/원본별 네이티브 검사, 외부 OGG→MP4, 사용자 최종 MP4 ffprobe·전체 디코딩·Chrome 재생 |
| 2 미리보기 | preview 단위/E2E, 실제 주소 분석·옵션 선택, 최종 기본 썸네일 화면 |
| 3 기록 관리 | 1,000건/다중 패널/실패 일괄 삭제 E2E, 사용자 선택 삭제 JSON과 파일 해시 보존 |
| 4 자동 재시도 | 정책/실제 로컬 503·연결 종료·429·취소·재시작 검사와 retry E2E |
| 5 업데이트 | 실패 주입 단위 검사, GUI 해시 실패·설치·롤백 E2E 재검증, 사용자 GUI 설치·롤백 후 실제 외부 다운로드 |
| 6 재생 | 실제 사용자 영상/시간 증가·탐색·음량·배속·전체화면·이어보기 캡처, 실패/수명 E2E |
| 적용·안내 | 최종 설치/확장 재로드·소스 일치, README 설치·복구 안내, 계획 전체 체크와 증거 파일 |

Goal용 원문은 `dev-plan/goal-features-1-6.md`에 보존했다. 미지원 범위는 위 제한 절을 그대로 유지한다.
