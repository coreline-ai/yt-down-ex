# 의존성과 테스트 미디어

- yt-dlp 2026.6.9: [공식 저장소](https://github.com/yt-dlp/yt-dlp), Unlicense. 설치 wheel은 requirements-engine.txt의 SHA-256으로 검증합니다.
- yt-dlp-ejs 0.8.0: [공식 저장소](https://github.com/yt-dlp/ejs), MIT. YouTube 관련 JS 처리 의존성입니다. 설치만으로 모든 YouTube 다운로드 성공을 보장하지 않습니다.
- FFmpeg/ffprobe: [공식 사이트 및 라이선스](https://ffmpeg.org/legal.html). 별도 설치된 실행 파일을 사용하며 빌드 옵션에 따라 LGPL/GPL 등 조건이 달라집니다. 이 프로젝트에서 바이너리를 재배포하지 않습니다.
- Vite: MIT, TypeScript: Apache-2.0, Playwright: Apache-2.0, @types/chrome: MIT. 정확한 버전은 package-lock.json을 참조하세요.
- 로컬 테스트 영상과 음원: FFmpeg testsrc2/sine으로 자동 생성합니다.
- 인터넷 테스트: Big Buck Bunny trailer, © 2008 Blender Foundation / www.bigbuckbunny.org. [출처·CC BY 3.0 안내](https://peach.blender.org/about/), [영상](https://download.blender.org/peach/trailer/trailer_400p.ogg). 테스트 결과 파일 옆에도 출처를 기록합니다.
- Stacher 이름·UI 자산·로고는 사용하지 않습니다. Stash Local은 별도 구현이며 Stacher/yt-dlp/Blender와 제휴하지 않습니다.
