# HANDOFF — donvalue-bot 인수인계 (2026-11-17 기준)

이 레포 작업을 클라우드 채팅에서 **PC의 Claude Code(Code 탭)와 Codex**로 옮기면서 남기는 인계 문서다.
규칙은 `AGENTS.md`가 우선이다. 이 문서는 지금 상태와 소유자 결정, 그리고 그동안 실제로 터졌던 함정을 모아 둔 것이다.

---

## 1. 지금 무엇이 돌아가나

| 채널 | 내용 | 언제 (KST) | 코드 |
|---|---|---|---|
| 인스타 @dongabhana | **「0년」 컷툰 전용.** `toon/epNN/` 그림을 이어 붙인 세로 릴스 | **월·수·금 17:00** (보조 크론 18·19시) | `.github/workflows/toon.yml`, `src/toon.py`, `tools/publish_clock.py`의 `TOON_SLOTS` |
| 유튜브 「돈값하나」 쇼츠 | 매일 1편 | 월~목 21:20 / 금~일 15:30 | `post.yml` → `src/run.py`, 따라올리기 `youtube-shorts.yml` |
| 쓰레드 | **멈춤** (인스타 계정과 묶여 있음) | — | `post.yml`의 `SKIP_THREADS`, `content/microposts.yaml`의 `enabled: false` |
| 텔레그램 | 발행 알림, 매일 22:50 점검표 | — | `src/notify.py`, `status.yml` |

- 모든 발행은 **GitHub Actions(클라우드)**에서 돈다. PC를 꺼도 발행은 계속된다.
- 예약 실행 누락에 대비해 `publish-clock.yml`이 dispatch로 대신 쏘고, `publish-clock-watchdog.yml`이 시계를 살린다.

## 2. 진행 상황 (2026-11-17)

| 항목 | 상태 | 다음 |
|---|---|---|
| 「0년」 컷툰 | ep01~ep06 게시 완료 (`toon/posted.json`) | **ep07 「소금」 대기 → 11/18(수) 17:00** |
| 컷툰 재고 | **ep08 폴더 없음** | 그림이 없으면 11/20(금)부터 "그림 없음" 텔레그램 알림과 함께 쉰다 → ep08 그림 필요 |
| 유튜브 30편 캠페인 (`codex/campaign30.py`) | n22까지 발행 | n23~n30 8편 남음(표지 있음) → 약 11/25 소진 |
| 유튜브 이후 순서 | 첫 10편 → 30편 → **27편 캠페인** → 일반 큐 | `src/campaign.py`의 `CAMPAIGNS` 확인 |
| 「0년」 전체 대본 | 레포 밖. Claude 채팅의 Docs 문서 「0년」 제작 대본에 있음 | 컷툰 화 추가 시 소유자가 GPT로 그림 제작 |

## 3. 역할 분담 (소유자 결정)

| 누가 | 맡는 일 |
|---|---|
| ChatGPT (소유자가 직접) | 컷툰 그림·표지·장면 이미지. 디자인은 GPT가 낫다고 판단(2026-09-29) |
| Claude Code (PC Code 탭) | 영상화·나레이션·발행 코드, 레포 수정·커밋·푸시 |
| Codex (PC, 플러그인) | 코드 검토(`/codex:review`), 긴 작업 위임(`/codex:rescue`) |
| Antigravity `agy` (PC) | 유튜브·구글 조사, 문서 2차 검토 |

## 4. 소유자가 정해 둔 운영 방식

- **승인 없이 순번대로 자동 발행.** 문제 있는 편은 소유자가 직접 들어가 삭제한다 (2026-09-22). 텔레그램 승인 단계를 되살리지 않는다.
- 날짜에 묶지 않고, 앞 편이 나가면 다음 편이 바로 잇는다.
- 할 수 있는 작업은 소유자에게 넘기지 말고 직접 한다. 커밋·푸시도 에이전트가 한다 (압축파일 전달 방식 싫어함).
- 해시태그는 실제로 검색·유입되는 것만 쓴다. 인스타는 5개까지 (`src/tags.py`).
- 유튜브 썸네일은 **표지 그대로**. 유튜브용 영상 마지막 장은 표지 + 좋아요·구독 (A안, 2026-10-06).
- 나레이션: `ko-KR-SunHiNeural`, 속도 +22%, 손으로 쓴 반말 구어체 대본 (`content/narration.yaml`). 화면 글자를 그대로 읽지 않는다.
- 금액이 확인되는 소재는 구체적 금액을 넣는다. 가정값이면 가정이라고 밝힌다 (AGENTS.md 2절).

## 5. 실제로 터졌던 함정 (반복 금지)

| 함정 | 결과 | 지킬 것 |
|---|---|---|
| 테스트 실패한 채 푸시 | 발행 20시간 정지(9/14) | 푸시 전 `python -m unittest discover -s codex/tests -q` → OK일 때만 |
| 발행 시각을 한 곳만 고침 | GPT 트랙 엔진이 매 실행 멈춤(9/21) | 시각은 짝으로 고친다: `src/run.py SLOTS` ↔ `publish_clock.SLOTS`, `src/toon.py SLOTS` ↔ `TOON_SLOTS`, codex 쪽은 `engine.py` validate + `build_threshold_queue.py` |
| 응답 안 된 승인 요청이 남아 있음 | 이후 발행이 40초 만에 조용히 연쇄 종료(9/20~22) | `APPROVAL_REQUIRED=0` 유지. 남은 요청은 `codex.approvals.discard()`로 정리하는 코드 유지 |
| edge-tts에 없는 목소리 이름 | 합성 전부 실패 → **무음 영상이 그대로 나감** | 한국어 목소리는 `SunHi`·`InJoon`·`HyunsuMultilingual` 셋뿐. `KNOWN_VOICES` 검사 유지 |
| TTS 429 | 나레이션 실패 | `assets/tts-cache/` + `tts-prewarm.yml` 유지 |
| 심사 전 유튜브 업로드 | 비공개로 잠기고 원장엔 done → 영영 공개 불가 | `youtube_hold.json` 스위치·`delivery.json` 원장을 우회하는 업로드 코드 금지 |
| `hooks.yaml` flow 리스트에 `?` | YAML 파싱 깨짐 | 블록 스타일로만 |
| 발행 완료 편 수정 | SNS와 레포 불일치 | `posted.json`·`delivery.json`·`toon/posted.json`에 있는 편은 손대지 않음 |

## 6. PC 작업 환경 메모 (회사 Windows PC)

- 작업 폴더는 `C:\Users\USER\Downloads\AI 작업\donvalue-bot` (2026-11-17 새로 clone. 상위 `AI 작업` 폴더가 Code 탭 작업 폴더이고 AI 드림팀 규칙 CLAUDE.md가 있다). 예전에 쓰던 `Downloads\dv`는 PC에 더 이상 없다. 작업 전 항상 `git pull`.
- 파이썬은 `py`로 실행한다 (`python`은 마이크로소프트 스토어 스텁).
- `.git/*.lock`이 남아 git이 멈추면 lock 파일을 지운다.
- 회사 PC라 DLP 보안이 있다. **회사 업무 자료는 이 레포에 넣지 않고, 다른 AI에도 보내지 않는다.**
- 유튜브 채널은 YouTube 스튜디오로 확인한다 (채널 id `UCmHfU4duUteGtxz7O2av1iQ`). `youtube.com/@dongabhana`는 이름이 같은 다른 채널이다.
- GitHub Secrets(이름만): `IG_USER_ID`, `IG_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `YOUTUBE_TOKEN_JSON` 등. 인스타 토큰은 `refresh-token.yml`이 주 1회 연장한다.

## 7. 새 컷툰 화 넣는 법 (요약)

1. `toon/ep08/` 폴더를 만들고 그림을 `01.jpg`~`15.jpg`로 넣는다 (png·webp도 됨).
2. `caption.txt`(캡션, 해시태그 5개), 필요하면 `timing.yaml`(장별 초·효과음).
3. 미리보기: Actions → 「0년 컷툰 릴스」 → `dry_run: true`로 실행 → Artifacts에서 mp4 확인.
4. 다음 게시 슬롯(월·수·금 17:00)에 자동으로 나간다.

## 8. 바로 할 일 후보

- [ ] **ep08 그림 준비** (11/20 금 공백 방지)
- [ ] n30 이후 유튜브 순서(27편 캠페인 표지 대기분)를 확인하고, 표지 없는 편 목록 뽑기
- [ ] Codex로 이 문서와 `AGENTS.md`를 읽게 해서 이해가 같은지 대조
