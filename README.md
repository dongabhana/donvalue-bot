# 돈값하나? 자동 발행 봇

미리 준비한 콘텐츠를 GitHub Actions에서 렌더링하고 인스타그램과 Threads에 발행합니다.
PC나 대화창을 켜둘 필요가 없으며, 발행 경로는 Claude/OpenAI 생성 API를 호출하지 않습니다.
따라서 대화 크레딧 소진은 준비된 콘텐츠의 발행을 막지 않습니다. 콘텐츠 큐가 비면 새 원고와 검수가 필요합니다.

현재 운영 일정은 Claude 화·목·일 20시, GPT 월·수·토 20시(KST)입니다.
Claude는 실행 시 Telegram 승인을 최대 45분 기다리고, GPT는 게시 전날 최종 승인한 원고만 게시합니다.
GPT의 15분 실행 주기는 승인과 예약 상태 확인용이며, 15분마다 게시하는 일정이 아닙니다.

```
content/queue.yaml  ─(렌더)→  images/{id}/*.png  ─(git push)→  raw.githubusercontent 공개 URL
                                                                        │
                                              ┌─────────────────────────┴──────────────────────┐
                                              ▼                                                ▼
                                   인스타 캐러셀 발행                                    쓰레드 캐러셀 발행
                                              └─────────────→ content/posted.json ←────────────┘
```

---

## 1. 왜 이 구조인가

| 결정 | 이유 |
|---|---|
| GitHub Actions 를 스케줄러로 | 24시간 켜둘 서버가 필요 없고 무료. cron 만 적으면 끝 |
| 이미지를 리포지토리에 커밋 | 두 API 모두 **이미지를 공개 URL 로만** 받는다. 별도 호스팅(S3, R2) 없이 raw URL 로 해결 |
| 커밋 SHA 를 URL 에 포함 | `raw.githubusercontent.com/{owner}/{repo}/{sha}/...` 는 푸시 직후 즉시 접근 가능. 브랜치명을 쓰면 캐시 지연이 생긴다 |
| `verified` 게이트 | 가격·요금 같은 사실 정보가 틀린 채로 자동 발행되는 걸 막는 안전장치 |
| 발행 실패해도 큐 유지 | 두 플랫폼 모두 실패하면 항목을 소진하지 않고 다음 회차에 재시도 |

> ⚠️ **리포지토리는 Public 이어야 합니다.** Private 이면 raw URL 에 인증이 걸려 Meta 서버가 이미지를 못 읽습니다.
> 큐에 회사 정보나 개인정보를 넣지 마세요.

---

## 2. 사전 준비 (한 번만)

### 2-1. 계정

| 항목 | 필요 조건 |
|---|---|
| 인스타그램 | **프로페셔널 계정**(비즈니스 또는 크리에이터). 개인 계정은 API 발행 불가 |
| 페이스북 페이지 | **불필요.** "Instagram API with Instagram Login" 방식은 페이지 연결을 요구하지 않습니다 |
| 쓰레드 | 인스타 계정과 연결된 일반 쓰레드 프로필이면 됩니다 |
| Meta 개발자 계정 | developers.facebook.com 가입 (무료) |

### 2-2. 앱 심사(App Review)는 필요 없습니다 — 조건부

Meta 문서상 `instagram_business_content_publish` / `threads_content_publish` 는 **일반 사용자에게 쓰려면** 앱 심사가 필요합니다.
하지만 **내 계정에만 올릴 때는** 앱을 개발 모드에 두고 내 계정을 앱의 역할(관리자/테스터)에 추가하면 심사 없이 발행됩니다.
이게 이 프로젝트가 성립하는 핵심 조건입니다.

### 2-3. Meta 앱 만들기

1. developers.facebook.com → **내 앱 → 앱 만들기**
2. 사용 사례에서 **Instagram** 과 **Threads API** 를 각각 추가
3. Instagram 쪽:
   - "Instagram 계정으로 로그인 설정" 선택 (페이스북 로그인 아님)
   - 권한: `instagram_business_basic`, `instagram_business_content_publish`
   - 리디렉션 URI 등록 (`https://localhost/` 같은 아무 주소여도 됩니다. 코드만 복사할 용도)
4. Threads 쪽:
   - 권한: `threads_basic`, `threads_content_publish`
   - **Threads 테스터**로 본인 계정을 초대 → 본인 쓰레드 설정에서 수락
5. 앱은 **개발 모드 그대로 둡니다.**

### 2-4. 토큰 발급

**방법 A (권장)** — 앱 대시보드에 "액세스 토큰 생성" 버튼이 있으면 그걸로 바로 생성.
Instagram / Threads 각각의 설정 화면에 계정별 토큰 생성 UI가 있습니다. 여기서 나온 값이 장기 토큰입니다.

**방법 B** — 버튼이 없거나 실패하면 수동 OAuth:

```bash
pip install -r requirements.txt
python tools/get_tokens.py instagram   # 앱ID / 시크릿 / 리디렉션URI 입력 → code 붙여넣기
python tools/get_tokens.py threads
```

두 방법 모두 결과로 **user_id** 와 **60일짜리 장기 토큰**을 얻습니다.

> Meta 는 문서 경로와 대시보드 UI 를 자주 바꿉니다. 스크립트가 출력하는 URL 이 문서와 다르면
> [인스타 문서](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login) /
> [쓰레드 문서](https://developers.facebook.com/docs/threads/get-started) 를 기준으로 맞추세요.

---

## 3. 리포지토리 세팅

1. 이 폴더를 GitHub **Public 리포지토리**로 push
2. **Settings → Secrets and variables → Actions → New repository secret** 에 아래 등록

| 시크릿 이름 | 값 | 필수 |
|---|---|---|
| `IG_USER_ID` | 인스타 user id | ✅ |
| `IG_ACCESS_TOKEN` | 인스타 장기 토큰 | ✅ |
| `TH_USER_ID` | 쓰레드 user id | ✅ |
| `TH_ACCESS_TOKEN` | 쓰레드 장기 토큰 | ✅ |
| `SECRETS_PAT` | 토큰 자동 연장용 PAT (Secrets: write 권한) | 선택 |
| `YT_CLIENT_ID` | 유튜브 OAuth 클라이언트 ID | 선택 |
| `YT_CLIENT_SECRET` | 유튜브 OAuth 보안 비밀 | 선택 |
| `YT_REFRESH_TOKEN` | 유튜브 리프레시 토큰 | 선택 |
| `YOUTUBE_TOKEN_JSON` | 위 3개 대신 authorized_user JSON 통째로 | 선택 |

유튜브 인증정보가 하나도 없으면 유튜브 단계는 조용히 건너뜁니다
(인스타·쓰레드는 그대로 발행). 발급 방법은 **9. 유튜브 쇼츠** 참고.

3. **Settings → Actions → General → Workflow permissions** 를 `Read and write permissions` 로 변경
   (봇이 이미지와 발행 이력을 커밋해야 합니다)

`SECRETS_PAT` 을 등록하지 않으면 토큰이 60일마다 만료됩니다. 등록해두면 매주 자동 연장되어 사실상 무기한입니다.

---

## 4. 발행 주기

| 워크플로우 | 시각 | 하는 일 |
|---|---|---|
| `post.yml` | **화·목·일 20:00 KST** | Claude 큐의 다음 항목 1건 렌더 → Telegram 승인 → 인스타·Threads 발행 |
| `codex-approval.yml` | 약 15분마다 확인 | GPT 승인·예약 상태 확인. 월·수·토 20시의 전날 승인된 콘텐츠만 발행 |
| `refresh-token.yml` | 매주 월 12:00 KST | 장기 토큰 60일 연장 |

주기를 바꾸려면 `.github/workflows/post.yml` 의 cron 을 수정하세요 (**UTC 기준**, KST = UTC+9).

```yaml
- cron: "0 11 * * 2,5"   # 화·금 20시 KST
- cron: "0 12 * * 1,4"   # 월·목 21시 KST 로 바꾸려면 이렇게
```

---

## 5. 운영 방법

### 발행 전 검수 (유일하게 손이 가는 단계)

`content/queue.yaml` 의 각 항목에는 `verified: false` 와 `verify:` 목록이 있습니다.
`verify` 에 적힌 사실만 확인하고 `verified: true` 로 바꾸면 그 항목은 자동 발행 대상이 됩니다.

```yaml
- id: "001-coupang-wow"
  verified: true          # ← false 인 동안은 절대 발행되지 않음
  verify:
    - "현재 쿠팡 와우 월 구독료"
```

`verified: true`는 사실 검수 표시입니다. 현재 Claude 운영은 각 실행에서 Telegram 승인도 필요하므로, 사실 검수만으로 무인 발행되지는 않습니다.

### 미리보기

```bash
python -m src.run --dry-run --id 001-coupang-wow
```
`images/001-coupang-wow/` 에 카드 6장이 생성되고, 캡션·쓰레드 본문이 터미널에 출력됩니다. API 호출은 없습니다.

### 즉시 발행 / 특정 건 발행

GitHub 리포 → **Actions → 돈값하나 자동 발행 → Run workflow**
`item_id` 를 비우면 큐 순서대로, 입력하면 해당 건만 발행합니다.

### 새 글 추가

`content/queue.yaml` 맨 아래에 항목을 붙이면 됩니다.

| 필드 | 설명 |
|---|---|
| `id` | 고유값. 이미지 폴더명·발행 이력 키로 쓰임 |
| `product` | 표지 대제목 |
| `price` | 표지 노란 뱃지 문구 (짧게) |
| `hook` | 표지 부제 |
| `cards` | 본문 카드 배열. `title` / `body` / `note`(선택) — **3~5개 권장** |
| `verdict` | 0~5 점수. 결론 카드 게이지에 반영 |
| `verdict_text` | 결론 문장 |
| `caption` | 인스타 캡션 |
| `threads_text` | 쓰레드 본문 (500자 제한 주의) |
| `hashtags` | `#` 없이 단어만. 인스타는 전체, 쓰레드는 앞 3개만 붙습니다 |

카드 총 장수 = `1(표지) + len(cards) + 1(결론)`
**인스타 캐러셀 상한은 10장**이므로 `cards` 는 최대 8개입니다.

---

## 6. 제약과 한계 (알고 있어야 할 것)

| 항목 | 값 / 주의사항 |
|---|---|
| 인스타 발행 한도 | 24시간 이동창 기준 100건. 캐러셀은 1건으로 계산 |
| 인스타 캐러셀 | 2~10장. 전체가 **첫 장 비율로 크롭**되므로 모든 카드가 동일 규격(1080×1350)이어야 함 |
| 쓰레드 발행 한도 | 24시간 기준 250건 |
| 쓰레드 캐러셀 | 2~20장 |
| 이미지 호스팅 | 반드시 공개 URL. 로컬 파일 업로드 불가 |
| 장기 토큰 | 60일. `refresh-token.yml` 이 연장. 연장은 발급 24시간 후부터 가능 |
| GitHub cron | 정시 보장 안 됨. 러너 혼잡 시 수 분~수십 분 지연 |
| 릴스·동영상 | 이 버전은 이미지 캐러셀만 지원 |
| 예약 발행 API | Meta 는 미래 시각 예약을 지원하지 않음. **발행 시각 = 워크플로우 실행 시각** |

---

## 7. 막혔을 때

| 증상 | 원인 / 조치 |
|---|---|
| `IG 컨테이너 상태 ERROR` | 이미지 URL 접근 불가. 리포가 Private 이거나 푸시가 안 된 상태 |
| `(#10) Application does not have permission` | 앱 역할에 계정이 추가 안 됨. 테스터 초대 수락 여부 확인 |
| `Invalid OAuth access token` | 토큰 만료. `refresh-token.yml` 수동 실행 → 실패하면 재발급 |
| 이미지가 깨지거나 네모(□) | 러너에 한글 폰트 미설치. 워크플로우의 `fonts-noto-cjk` 단계 확인 |
| 커밋/푸시 실패 | Workflow permissions 가 `Read and write` 인지 확인 |
| 발행은 됐는데 캡션 없음 | `caption` 필드 누락 |

실패한 회차는 큐를 소진하지 않으므로 원인을 고치고 재실행하면 그대로 이어집니다.
실패 시 렌더된 카드는 Actions 실행 화면의 아티팩트(`rendered-cards`)에서 내려받을 수 있습니다.

---

## 8. 파일 구조

```
donvalue-bot/
├─ .github/workflows/
│  ├─ post.yml               주 2회 발행
│  └─ refresh-token.yml      주 1회 토큰 연장
├─ content/
│  ├─ queue.yaml             발행 대기 콘텐츠 (10편 선탑재)
│  └─ posted.json            발행 이력 (자동 기록)
├─ src/
│  ├─ render.py              카드뉴스 PNG 생성
│  ├─ reel.py                세로영상(릴스/쇼츠) 생성
│  ├─ tts.py                 나레이션(음성) 합성·싱크
│  ├─ audio.py               배경음 · 말할 때 음악 더킹
│  ├─ publish.py             인스타/쓰레드 API
│  ├─ youtube.py             유튜브 쇼츠 업로드
│  ├─ youtube_run.py         이미 나간 편을 유튜브에 따라 올리는 백필
│  ├─ refresh.py             토큰 연장
│  └─ run.py                 파이프라인 엔트리포인트
├─ tools/get_tokens.py       최초 토큰 발급 헬퍼(메타)
├─ tools/get_yt_token.py     유튜브 리프레시 토큰 발급 헬퍼
└─ images/                   렌더 결과 (자동 커밋됨)
```

---

## 9. 유튜브 쇼츠 + 나레이션

### 9-1. 뭐가 달라졌나

같은 세로영상 하나를 인스타 릴스와 유튜브 쇼츠에 **둘 다** 올립니다.
추가 제작비는 0인데, 릴스는 며칠이면 도달이 끝나는 반면 유튜브는
검색·추천으로 반년 뒤에도 조회가 붙습니다. 재고로 남는 자산이 다릅니다.

**같은 편이 같은 날 양쪽에 올라갑니다.** 플랫폼별 성장 속도를 비교하는 게
목적이라, 편이 어긋나면 비교 자체가 무의미해지기 때문입니다.
`post.yml` 이 릴스를 만든 그 자리에서 같은 mp4 를 쇼츠로도 올립니다.

이미 인스타에만 나간 과거 편은 `youtube-shorts.yml`(수동 실행)로 따라 올립니다.
채널이 비어 있으면 들어온 사람이 그냥 나가므로 초반에 몇 편 깔아두는 용도입니다.

**콘텐츠 두 갈래를 모두 훑습니다.** 이 저장소에는 `content/queue.yaml`(이쪽
파이프라인)과 `codex/content.json`(GPT 트랙) 두 목록이 있고 인스타에는 둘 다
나갑니다. 한쪽만 보면 유튜브에 구멍이 생기므로 `src/codex_bridge.py` 가
codex 스키마를 이쪽 스키마로 바꿔 함께 대상에 넣습니다.

지금 뭐가 올라갈 수 있는지 보려면:

```bash
python -m src.youtube_run --list
```

영상에는 **사람 목소리 나레이션**이 깔립니다(`src/tts.py`).
글자만 있는 영상은 '읽어야 하는 것'이라 스크롤을 못 잡습니다.
말소리가 나오는 구간에는 배경음이 자동으로 눌렸다가(더킹) 다시 올라옵니다.

| 항목 | 값 |
|---|---|
| 음성 엔진 | edge-tts (무료, API 키 없음) |
| 기본 목소리 | `ko-KR-HyunsuMultilingualNeural` (남성·차분) |
| 다른 선택지 | `ko-KR-SunHiNeural`(여성·밝음) / `ko-KR-InJoonNeural`(남성·뉴스톤) |
| 영상 길이 | 나레이션에 맞춰 늘어남 (대략 28초 → 35~45초) |
| 실패하면 | 나레이션 없이 예전처럼 발행 (발행이 멈추지 않음) |

끄고 싶으면 워크플로 실행 시 `tts: false`, 또는 `REEL_TTS=0`.

### 9-2. ⚠ 먼저 알아야 할 제약 — 심사 전엔 비공개로 잠깁니다

2020-07-28 이후 만든 구글 API 프로젝트로 영상을 올리면 **비공개(private)로
고정**됩니다. 풀려면 구글에 **YouTube API Services 심사(audit)** 를 신청해
통과해야 합니다. 그래서 기본값이 `private` 입니다.

- 심사 신청: [YouTube API Services – Audit and Quota Extension Form](https://support.google.com/youtube/contact/yt_api_form)
- 심사 통과 전까지는 영상이 채널에 비공개로 쌓입니다. 통과 후 워크플로 입력의
  `yt_privacy` 를 `public` 으로 바꾸면 그때부터 바로 공개 발행됩니다.

### 9-3. 세팅 (한 번만)

1. [Google Cloud Console](https://console.cloud.google.com) → 새 프로젝트 생성
2. **API 및 서비스 → 라이브러리** → `YouTube Data API v3` 사용 설정
3. **OAuth 동의 화면** 설정
   - User Type: 외부
   - 범위에 `.../auth/youtube.upload` 추가
   - **반드시 '앱 게시'(프로덕션)로 전환** ← 테스트 상태면 토큰이 7일 만에 죽습니다
4. **사용자 인증 정보 → OAuth 클라이언트 ID → 데스크톱 앱** 생성
5. 내 PC 에서 토큰 발급

   ```bash
   pip install requests
   python tools/get_yt_token.py --id <클라이언트ID> --secret <보안비밀>
   ```

6. 출력된 3개 값을 GitHub Secrets(`YT_CLIENT_ID` / `YT_CLIENT_SECRET` /
   `YT_REFRESH_TOKEN`)에 등록
7. 연결 점검

   ```bash
   YT_CLIENT_ID=... YT_CLIENT_SECRET=... YT_REFRESH_TOKEN=... python -m src.youtube
   ```

### 9-4. 자주 나는 오류

| 증상 | 원인 | 해결 |
|---|---|---|
| `invalid_grant` | 동의 화면이 '테스트' 상태 | 앱 게시로 전환 후 토큰 재발급 |
| 영상이 계속 비공개 | 심사 미통과 | 9-2 의 심사 신청 |
| `403 quotaExceeded` | 일일 할당량 소진 | 다음날 초기화 대기 |
| 나레이션이 안 들어감 | edge-tts 차단/실패 | 로그의 `[tts]` 줄 확인. 발행은 정상 진행됨 |
