# Stash Local 검증 결과

검증 일시: 2026-09-10T15:32:35+09:00

## 결과

**macOS 개발용 MVP 구현 및 검증 완료.** 기본 Chrome용 Native Host 설치와 진단도 완료했다. 사용자의 평소 Chrome 프로필에는 확장을 자동 로드하지 않았으며, 최초 한 번 `chrome://extensions`에서 개발자 모드로 이 프로젝트의 `dist` 폴더를 로드하면 된다.

| 검증 항목 | 결과 | 증거 |
|---|---|---|
| TypeScript 검사 / Vite 빌드 | 통과 | [전체 로그](../artifacts/verify.log) |
| Python 프로토콜·엔진·작업·설치 테스트 | 25건 통과 | [전체 로그](../artifacts/verify.log) |
| 실제 확장 Chromium E2E | 4건 통과 | [구조화 결과](../artifacts/e2e-results.json) |
| 실제 Google Chrome 사이드 패널 | 통과 | [Chrome 보고서](../artifacts/chrome/report.json), [실제 패널 캡처](../artifacts/chrome/side-panel.png) |
| 공개 인터넷 샘플 다운로드 | 통과 | [미디어 보고서](../artifacts/external/report.json) |
| 사용자용 Native Host 설치·진단 | 통과 | [설치 로그](../artifacts/install.log), [진단](../artifacts/installed-diagnostics.log) |

## 실제 파일 검증

- 샘플: Big Buck Bunny 예고편. © 2008 Blender Foundation / www.bigbuckbunny.org, CC BY 3.0. [라이선스 안내](https://peach.blender.org/about/).
- 다운로드: [원본 주소](https://download.blender.org/peach/trailer/trailer_400p.ogg).
- 저장 파일: [trailer_400p (1).ogg](</Users/iriver/Documents/ChatGPT/yt-down-interface/artifacts/external/trailer_400p (1).ogg>).
- 크기: **4,360,399 bytes**. 길이: **32.997초**.
- 영상: Theora, 720×400. 음성: Vorbis. FFmpeg 전체 디코딩 종료 코드: **0**.
- SHA-256: `dcbe6f2ea404a52d4b2f6fc91f274874e69be1671a1097eb3dc19f28f7c6e40f`.
- 실제 Chrome에서는 2초 H.264/AAC MP4 다운로드·미디어 검증·Finder 열기를 확인했다. [보존한 파일](../artifacts/chrome/sample.mp4).
- 보고서의 임시 Chrome 프로필/원래 결과 경로는 테스트 후 삭제된다. 위 보존 파일과 캡처는 프로젝트 artifacts에 남는다.

## 테스트 범위

- 실제 yt-dlp로 MP4 저장, DASH 분리 스트림 각각의 HTTP 요청 및 영상/음성 병합, MP3 변환.
- ffprobe 스트림·길이 확인, FFmpeg 디코딩, 한글 긴 제목의 파일시스템 바이트 길이 처리.
- 잘못된 URL·404·HTML 응답·손상 미디어·사용 불가 형식·쓰기 권한 오류.
- 대기열 제한·중복 requestId·종료 뒤 이벤트·취소·실제 재시도·파일명 충돌.
- 느린 HTTP 전송 취소, 호스트 EOF/강제 종료 복구, 부모 프로세스 사망 시 가드의 자식 종료.
- SQLite 쓰기 실패·디스크 부족은 오류 주입으로 검증했다. 사용자의 실제 디스크를 채우지는 않았다.
- 설치·반복 설치·진단 실패 롤백·직전 버전 복원·제거·재설치. 한글/공백 경로와 누락 실행 파일.
- 실제 확장 폼 입력·패널 페이지 재열기·취소/재시도·오류 화면·320/390px·긴 제목 출력.
- 별도 Google Chrome 프로필에서 공식 CDP로 확장을 로드하고 확장 액션을 실행했다. 일반 탭 대신 실제 사이드 패널 타깃에 연결하여 키 입력과 완료 파일을 검사했다.

## 환경

- macOS 26.5.2, Apple Silicon arm64.
- 실제 Google Chrome **152.0.7977.84**. 자동 E2E: Playwright 제공 Chrome for Testing.
- Python 3.11.15, Node.js 22.22.2, FFmpeg/ffprobe 8.0.1.
- yt-dlp 2026.06.09, yt-dlp-ejs 0.8.0. 전용 가상환경, 공식 wheel SHA-256 검증.
- 고정 확장 ID: `hboflpodmjfndlhjkneifakddogdpbdh`.
- 사용자 설치: `~/Library/Application Support/Stash Local`.
- 기본 Chrome 등록: `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/io.stashlocal.downloader.json`.

## 알려진 제한

- **YouTube 실제 다운로드는 검증하지 않았다.** 위 인터넷 성공은 공개 미디어 URL 성공이며 특정 사이트 extractor 성공과 동일하지 않다.
- Chrome 웹 스토어 배포, Windows/Linux, 서명/공증 설치 패키지는 범위 밖이다.
- 최초 확장 로드는 사용자가 한 번 수행한다. 이미 빌드와 사용자 Native Host 설치는 마쳤다.
- Chrome 완전 종료 후 다운로드를 유지하지 않는다. 강제 종료 중 남은 임시 작업 폴더가 있을 수 있으며 기존 다운로드는 삭제하지 않는다.
- 모든 코덱·사이트·최대 해상도를 보장하지 않는다. 메타데이터에서 높이를 알 수 없는 직접 파일은 화질 제한 옵션이 실패할 수 있으며 최고 화질로 내려받을 수 있다.
- Python/FFmpeg/Node 실행 파일 경로가 바뀌면 호스트 재설치가 필요하다.

## 재현 명령

```sh
npm ci
npm run setup:tests
npm run verify
npm run test:external
npm run test:chrome
npm run diagnose
```

`setup:tests`와 `test:external`에는 네트워크가 필요하다. `verify`의 HTTP 서버와 브라우저 실행은 제한된 샌드박스 밖 실행이 필요할 수 있다. 테스트 실패/차단은 통과로 기록하지 않는다.


## 2026-09-10 실제 Chrome 다운로드 실패 수정

- W3 Sintel MP4: yt-dlp 기본 브라우저 User-Agent 요청의 간헐적 403을 확인. 직접 미디어 URL의 분석과 다운로드 모두 `StashLocal/0.1` User-Agent를 사용하도록 수정. 웹페이지 추출 요청은 기존 설정 유지.
- Google ForBiggerFun 주소는 서버 XML에 익명 사용자 storage.objects.get 권한 거부가 명시됨. 해당 주소의 다운로드 성공을 주장하지 않음.
- curl-cffi 방식도 조사했으나 해결되지 않아 최종 의존성에는 추가하지 않음.
- 엔진 테스트 11개 통과: 요청 식별자가 다르면 403을 반환하는 서버에서 분석부터 실제 파일 다운로드까지 검증하는 회귀 테스트 포함.
- 수정 엔진 설치 후 Computer Use로 기존 W3 실패 작업의 다시 시도 버튼 클릭. 실제 Chrome 패널에서 완료 / MP4 / 4.2 MB 확인.
- 실제 파일: `/Users/iriver/Downloads/yt-down-interface/trailer.mp4` (4,372,373 bytes), H.264 854×480 + AAC, 52.208333초. ffmpeg 전체 디코딩 exit 0.
- 증거: `artifacts/cua-download-success-20260910.json`. Google 실패 기록은 유지.
