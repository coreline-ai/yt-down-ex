# Chrome 없는 Stash Media 스킬

`stash-media`는 macOS Apple Silicon용 독립 스킬이다. Chrome 확장이나 외부 서버 없이 에이전트가 자연어 요청을 읽고 패키지의 명령 도구를 실행한다. 다운로드 엔진은 기존 앱 코드를 재사용하지만 설치·기록·저장 위치는 별도다.

## 설치

빌드한 `stash-media.zip`을 풀고 다음을 실행한다. Python·Homebrew·Node가 미리 설치되어 있지 않아도 된다.

```sh
/bin/bash /절대경로/stash-media/install.sh
```

설치 스크립트는 파일 체크섬을 검사하고 `${CODEX_HOME:-~/.codex}/skills/stash-media`에 등록한 뒤 필수 도구를 자동 설치한다. 다른 스킬 설치 기능으로 폴더 전체를 등록했다면 첫 `scripts/stash.sh` 실행 시 도구 설치가 진행된다. 기존 같은 이름의 스킬이 있으면 덮어쓰지 않는다.

새 작업에서 스킬을 불러온 뒤 다음처럼 요청한다. 현재 작업의 스킬 목록에 자동으로 즉시 추가됐다는 뜻은 아니며, 명시적으로 `$stash-media`를 사용할 수도 있다.

- `이 주소 MP4로 다운해줘: https://…`
- `이 영상 음원만 MP3로 받아줘: https://…`
- `방금 받은 영상 재생해줘`
- `다운로드 목록 보여줘`, `실패한 다운로드 보여줘`
- `이 작업 취소해줘`, `이 실패 작업 다시 받아줘`, `이 기록 삭제해줘`

자연어를 처리하는 주체는 스킬을 읽는 에이전트다. 패키지에 별도 LLM·음성 인식기는 포함하지 않는다. 대상이 여러 개면 확인하고, 동일 대화에서 반환받은 작업 ID로 “방금 받은 것”을 식별한다.

## 자동 설치와 저장 위치

| 항목 | 기본 위치/내용 |
|---|---|
| 스킬 | `~/.codex/skills/stash-media` (CODEX_HOME 설정 시 해당 위치) |
| 실행 환경·기록 | `~/Library/Application Support/Stash Media Skill` |
| 영상·음원 | `~/Downloads/Stash Media` |
| 런타임 | 독립 Python 3.11, FFmpeg/ffprobe 8, Node 22, yt-dlp 2026.6.9, EJS 0.8.0 |

micromamba 2.3.2-0 공식 배포 바이너리를 SHA-256으로 검증한 뒤 conda-forge 채널만 사용한다. 런타임 패키지의 세부 빌드는 이 버전 범위에서 설치 시 결정되며 전체 conda 패키지 구성이 고정된 잠금 파일은 아니다. 실제 버전은 `doctor`와 `runtime-versions.json`, 상세 패키지는 런타임의 `conda-meta/`에서 확인한다. yt-dlp/EJS는 고정 버전·wheel SHA-256으로 설치한다.

관리자 권한·전역 PATH·쉘 설정·Chrome Native Messaging 등록을 수정하지 않는다. 최초 설치는 인터넷과 런타임용 디스크 공간이 필요하다. 공식 배포 접속 실패는 자동 설치로 해결할 수 없다. 실패한 새 런타임은 활성화하지 않으며 기존 활성 런타임을 유지한다. `setup.lock/pid`의 프로세스가 실행 중이면 잠금을 제거하지 않는다.

의존성 출처: [micromamba 공식 설치](https://mamba.readthedocs.io/en/stable/installation/micromamba-installation.html), [고정 bootstrap 배포](https://github.com/mamba-org/micromamba-releases/releases/tag/2.3.2-0), [conda-forge 소개](https://conda-forge.org/docs/user/introduction/), [기존 의존성 안내](third-party-notices.md). 바이너리 런타임은 ZIP에 재배포하지 않고 설치 시 배포처에서 받는다. 설치된 패키지의 라이선스는 conda-meta 및 패키지 정보에 따른다.

## 명령과 제한

```sh
/bin/bash ~/.codex/skills/stash-media/scripts/stash.sh doctor
/bin/bash ~/.codex/skills/stash-media/scripts/stash.sh download 'https://…' --format mp4 --request-id unique-request-id
/bin/bash ~/.codex/skills/stash-media/scripts/stash.sh list
/bin/bash ~/.codex/skills/stash-media/scripts/stash.sh play JOB_ID
```

다운로드는 명령이 끝날 때까지 실행된다. 진행 상황은 stderr, 최종 결과는 stdout의 JSON이다. 에이전트는 실행 세션을 기다려야 한다. 동일 요청 ID 재전송은 기록된 작업을 반환하며 다른 옵션으로 같은 ID를 쓰면 거절한다. 의도적인 재다운로드는 새 요청 ID를 사용한다.

한 번에 다운로드 1개가 실행된다. 다른 다운로드 요청은 `DOWNLOAD_BUSY`로 거절하고, 목록 조회·상태 확인·취소 요청은 가능하다. 재시도는 일시적 네트워크 오류에 한해 최대 3회이며 종료·취소를 존중한다. 강제 종료된 작업은 다음 명령이 실행 잠금을 획득한 뒤 중단으로 정리한다. 기록 삭제는 파일을 보존한다.

완료는 실제 미디어 검사·MP4 변환·전체 디코딩·SHA-256 확인 후 기록한다. 파일 게시 후 디코딩/기록 처리에 실패하면 파일이 남을 수 있지만 완료로 표시하지 않는다. `play`는 파일 식별정보와 해시를 확인하고 macOS 기본 플레이어로 연다. OS 열기 성공은 실제 화면/음성 재생 확인과 구분한다.

Chrome 앱 기록 공유, 전용 플레이어·이어보기, 상주 서비스·에이전트 종료 후 실행 보장, Windows/Linux/Intel Mac, 로그인·DRM 우회는 포함하지 않는다. 실제 YouTube extractor는 이번 인수에서 검증하지 않았다.

## 패키지 개발

```sh
python3 scripts/build_skill.py
python3 -m unittest tests.test_skill_package tests.test_skill_cli -v
```

원본은 `skills/stash-media`, 미디어 엔진은 `native`의 공통 구현을 사용한다. 빌드 시 필요한 모듈만 복사해 저장소 밖에서도 독립적으로 실행되는 `artifacts/stash-media.zip`을 생성한다. 원본 스킬 폴더만 복사하면 엔진 payload가 없으므로 빌드된 패키지를 설치한다.

## 검증 기록 — 2026-09-10~11

- 스킬 형식 검사 및 쉘 문법 검사 통과.
- 기본 macOS PATH(Python·Homebrew·Node 경로 없음)에서 새 런타임 설치 성공, 재실행 시 기존 런타임 재사용.
- 첫 설치는 사용자 site-packages를 참조해 yt-dlp 실행 파일이 누락되는 문제로 실패. `-I`와 `PYTHONNOUSERSITE` 격리 적용 후 새 설치 성공. `artifacts/skill-bootstrap.log`, `skill-bootstrap-recheck.log`.
- 실제 설치 버전: Python 3.11.16, FFmpeg/ffprobe 8.1.2, Node 22.23.2, yt-dlp 2026.06.09, EJS 0.8.0. `artifacts/skill-doctor.json`.
- 자동 검사 4개 통과: 독립 ZIP/변조 거절, 실제 MP4·MP3/요청 중복·충돌/삭제 파일 보존, 실행 잠금·취소·SIGKILL 복구, 변경 파일 재생 거절·실패 재시도·잘못된 URL. `artifacts/skill-tests.log`.
- 실제 사용자 스킬 등록·기존 런타임 재사용 성공: `artifacts/skill-install.log`.
- Chrome을 경유하지 않고 설치된 스킬로 W3 Sintel 주소 다운로드 성공. `/Users/iriver/Downloads/Stash Media/trailer.mp4`, **4,369,173 bytes**, **52.208333초**, H.264 **854×480/yuv420p** + AAC. 전체 디코딩 exit **0**.
- SHA-256: `508b7ca9a93d66bb9846412c52008d4b1ec493b1592faa056193bf9b6caa8966`. `artifacts/skill-external-download.json`.
- 설치된 `play` 명령의 OS 열기 exit **0**, `opened:true`. Computer Use는 timeoutReached를 반환해 **실제 플레이어 화면/음성은 미확인**. `artifacts/skill-play.json`의 `playbackObserved:false`를 유지한다.
- 자연어 요청→명령 매핑과 자동 선택 메타데이터를 검토했다. 새 대화에서 에이전트의 자동 스킬 선택을 별도 종단 테스트한 것은 아니다.
- Chrome 활성 릴리스는 기존 `20260910_182723_1e0abf71` 그대로이며 스킬은 별도 기록 DB를 사용한다. `artifacts/skill-chrome-preserved.json`.

## 사용자 요청에 따른 1턴 검증 — 2026-09-11

현재 작업에서 등록된 stash-media 스킬을 읽고 다운로드→검증→재생 명령을 1회 실행했다. 새 작업 ID `80992c70d5b846f8a11a1e02d48ff02d`, 자동 재시도 없이 첫 시도 성공. 결과 `/Users/iriver/Downloads/Stash Media/trailer (1).mp4`, 4,369,173 bytes, 52.208333초, H.264 854×480/yuv420p + AAC, 전체 디코딩 exit 0 및 SHA-256 재대조 통과.

이번에는 Computer Use 연결도 성공했다. QuickTime이 해당 파일을 연 것을 확인하고 재생 버튼을 눌러 실제 영상 장면과 타임라인 0→3.6558→12.3382초 증가를 확인했다. 12초에서 일시정지해 두었다. 실제 소리를 청취한 것은 아니며 AAC 스트림 존재를 검사했다. 이전 화면 미확인 기록을 이 테스트로 보완한다. 새 대화 자동 선택 종단 테스트와는 구분한다.

증거: `artifacts/skill-one-turn-report.json`, `skill-one-turn-download.json`, `skill-one-turn-playback.png`, `skill-one-turn-paused.png`.
