# 개인정보처리방침 / Privacy Policy

**돈값하나 쇼츠 업로더 (donvalue-shorts-uploader)**

최종 수정일: 2026-09-14 · Last updated: 2026-09-14

---

## 한국어

### 1. 이 도구는 무엇인가요

이 도구는 개인이 운영하는 콘텐츠 채널 '돈값하나?'의 세로 영상을 자동으로
만들고, 운영자 본인의 YouTube 채널에 업로드하는 개인용 스크립트입니다.
GitHub Actions에서 실행되며, 소스 코드는
https://github.com/dongabhana/donvalue-bot 에 공개되어 있습니다.

### 2. 이용자

이 도구의 이용자는 **운영자 본인 한 명뿐**입니다. 회원가입 기능이 없고,
제3자가 이 도구에 로그인하거나 데이터를 제공할 수 없습니다.

### 3. 수집하는 정보

이 도구는 **어떤 개인정보도 수집하지 않습니다.**

영상 시청자, 방문자, 제3자로부터 수집하는 정보가 없습니다.
운영자 본인의 정보 중 다음만 GitHub Actions의 암호화된 시크릿으로
저장되어 사용됩니다.

| 항목 | 용도 | 저장 위치 |
|---|---|---|
| Google OAuth 클라이언트 ID·보안 비밀 | 운영자 채널 인증 | GitHub Actions Secrets (암호화) |
| Google OAuth 리프레시 토큰 | 액세스 토큰 갱신 | GitHub Actions Secrets (암호화) |
| Meta(Instagram·Threads) 액세스 토큰 | 운영자 계정 게시 | GitHub Actions Secrets (암호화) |
| Telegram 봇 토큰·채팅 ID | 운영자에게 발행 승인 요청 | GitHub Actions Secrets (암호화) |

### 4. YouTube API 서비스 이용

이 도구는 **YouTube API 서비스**를 사용합니다. 사용 범위는 다음 하나뿐입니다.

- `https://www.googleapis.com/auth/youtube.upload` — 운영자 본인 채널에
  영상을 업로드하기 위한 권한

이 도구는 YouTube API를 통해 **영상 업로드만** 수행하며, 시청자 데이터,
분석 데이터, 댓글, 다른 채널의 정보를 조회하거나 저장하지 않습니다.

이 도구를 사용함으로써 운영자는 다음에 동의합니다.

- [YouTube 서비스 약관](https://www.youtube.com/t/terms)
- [Google 개인정보처리방침](https://policies.google.com/privacy)

### 5. 데이터 보관 및 삭제

- API로 받은 인증 토큰은 GitHub Actions 실행 중 메모리에서만 사용되며,
  실행이 끝나면 사라집니다.
- YouTube에서 받아 저장하는 데이터는 업로드 결과로 받은 **영상 ID뿐**이며,
  중복 업로드를 막기 위한 기록입니다(`content/delivery.json`).
- 운영자는 [Google 계정 보안 설정](https://myaccount.google.com/permissions)
  에서 언제든 이 도구의 접근 권한을 취소할 수 있습니다. 권한을 취소하면
  도구는 더 이상 채널에 접근할 수 없습니다.

### 6. 제3자 제공

수집하는 개인정보가 없으므로 제3자에게 제공하는 정보도 없습니다.
광고, 분석 도구, 추적 스크립트를 사용하지 않습니다.

### 7. 문의

dongabhana@gmail.com

---

## English

### 1. What this is

A personal script that renders vertical videos for the creator's own content
channel ("돈값하나?") and uploads them to the creator's own YouTube channel.
It runs on GitHub Actions. Source code is public at
https://github.com/dongabhana/donvalue-bot

### 2. Users

The **only user is the operator (channel owner)**. There is no sign-up, and
no third party can log in or submit data to this tool.

### 3. Information collected

This tool **collects no personal information** from anyone.

No data is collected from viewers, visitors, or third parties. Only the
operator's own credentials are stored, as encrypted GitHub Actions Secrets:
Google OAuth client ID/secret and refresh token, Meta (Instagram/Threads)
access tokens, and a Telegram bot token used to request the operator's
approval before publishing.

### 4. Use of YouTube API Services

This tool uses **YouTube API Services**, with exactly one scope:

- `https://www.googleapis.com/auth/youtube.upload` — to upload videos to the
  operator's own channel.

The tool performs **uploads only**. It does not retrieve or store viewer
data, analytics, comments, or information about other channels.

By using this tool the operator agrees to the
[YouTube Terms of Service](https://www.youtube.com/t/terms) and the
[Google Privacy Policy](https://policies.google.com/privacy).

### 5. Data retention and deletion

- OAuth tokens exist only in memory during a GitHub Actions run.
- The only data stored from the YouTube API is the returned **video ID**,
  kept to prevent duplicate uploads (`content/delivery.json`).
- The operator can revoke this tool's access at any time via
  [Google account permissions](https://myaccount.google.com/permissions).
  Once revoked, the tool can no longer reach the channel.

### 6. Third parties

Since no personal information is collected, none is shared. No advertising,
analytics, or tracking is used.

### 7. Contact

dongabhana@gmail.com
