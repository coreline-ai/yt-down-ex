# Theora 회귀 샘플

`theora.ogg`는 Blender Foundation의 Big Buck Bunny 공개 예고편 앞 2초를 재인코딩 없이 잘라 만든 테스트 입력이다.

- 원본: https://download.blender.org/peach/trailer/trailer_400p.ogg
- 제작: Blender Foundation / Big Buck Bunny 제작진
- 프로젝트 및 이용 조건: https://peach.blender.org/about/
- 라이선스: Creative Commons Attribution 3.0 (https://creativecommons.org/licenses/by/3.0/)
- 변경: FFmpeg `-t 2 -c copy`로 길이 축소. 전체 영상 재배포가 아닌 코덱 회귀 검사용 짧은 발췌.

로컬 FFmpeg에 Theora 인코더가 없어도 디코더와 MP4 변환을 오프라인 검증하기 위한 고정 입력이다.
