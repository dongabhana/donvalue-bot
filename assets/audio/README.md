# 릴스 배경음 넣는 곳

이 폴더에 `.mp3 / .m4a / .wav` 를 넣어두면 `src/audio.py` 가 편 id 를 해시해서
**한 편에 한 곡씩 결정론적으로** 골라 씁니다. (같은 편을 다시 렌더해도 같은 곡)

파일이 하나도 없으면 `src/audio.py` 가 **직접 합성한 배경음**을 씁니다.
합성음은 저작권 자체가 발생하지 않으므로 클레임 위험이 0이고, 발행이 멈추지 않는 안전판입니다.
다만 '트렌딩 음원' 효과는 없으므로, 가능하면 아래에서 받은 실제 음원을 넣는 쪽이 낫습니다.

## 왜 인스타 트렌딩 음원을 코드로 못 붙이나

| 경로 | 가능 여부 | 근거 |
|---|---|---|
| Meta Audio API (`ig_audio` → `audio_configuration`) | ❌ 현재 불가 | 이 API 는 **Instagram API with Facebook Login 전용**. 이 봇은 `graph.instagram.com`(Instagram Login)을 씀 |
| Meta Sound Collection (인앱 음원 보관함) | ❌ 파일로 못 씀 | 메타 플랫폼 **안에서만** 쓰는 라이선스. mp3 로 받아 영상에 믹싱하는 용도가 아님 |
| 저작권 프리 음원을 영상에 직접 믹싱 | ✅ 지금 이 방식 | 어떤 로그인 방식이든 동작. 쓰레드·유튜브 숏츠에도 그대로 재사용 가능 |

> 나중에 **페이스북 로그인 방식으로 재연동**하면 첫 줄이 살아납니다.
> 그때는 `IG_AUDIO_ID` 시크릿만 채우면 `src/publish.py` 의 `audio_configuration` 경로가 바로 동작합니다.
> (`publish.search_audio()` 로 트렌딩 목록을 받아올 수 있습니다.)

## 음원 받을 곳

| 출처 | 라이선스 | 출처 표기 |
|---|---|---|
| [Pixabay Music](https://pixabay.com/music/) | Pixabay Content License — 상업적 사용 허용 | 불필요 |
| [FreePD](https://freepd.com/) | Public Domain (CC0) | 불필요 |
| [Free Music Archive](https://freemusicarchive.org/) | 곡마다 다름 (CC0 / CC BY / NC…) | 곡마다 확인 |
| [Incompetech](https://incompetech.com/music/royalty-free/) | 대부분 CC BY | **필요** |

**곡을 넣기 전에 그 곡의 라이선스 문구를 직접 확인해 주세요.** 사이트 정책은 바뀝니다.
NC(비상업) 조건이 붙은 곡은 계정이 수익화되면 문제가 될 수 있으니 피하는 게 안전합니다.

## 권장 선곡 기준

- **가사 없는 곡** — 자막을 읽어야 하는 카드뉴스형이라 가사가 있으면 둘 다 놓칩니다
- 90–110 BPM 의 로파이/미니멀 — 정보형 릴스에서 제일 무난합니다
- 30초 이상 (짧으면 자동으로 루프됩니다)
- 파일명은 알아보기 쉽게: `lofi-calm-01.mp3`

곡을 넣은 뒤 출처와 라이선스를 `SOURCES.md` 에 적어두면 나중에 확인이 쉽습니다.

## 볼륨 조절

`REEL_MUSIC_DB` 환경변수 (기본 `-3`). 내레이션을 얹게 되면 `-14` 근처로 내리세요.
