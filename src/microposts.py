"""쓰레드 단문 트랙 — 카드뉴스와 별개로 하루 몇 개씩 나가는 텍스트 글.

왜 따로 두는가
  카드뉴스는 렌더링·승인·이미지 커밋까지 붙어 있어 하루 한 편이 한계다.
  그런데 쓰레드는 글이 자주 올라오는 계정을 더 밀어준다. 그래서 이미지를
  만들지 않는 짧은 글만 별도 큐에서 꺼내 올린다. 본편 큐(queue.yaml,
  codex/content.json)는 건드리지 않는다.

왜 글을 생성하지 않고 손으로 쓴 풀에서 꺼내는가
  매번 문장을 만들어내면 말투가 한 패턴으로 수렴해서 'AI 티'가 난다.
  사람이 미리 써 둔 글을 순서대로 소진하는 편이 낫다. 풀이 바닥나면
  조용히 올리지 않고 알린다.

발행 여부는 content/microposts.yaml 의 enabled 가 정한다.
  파일이 없거나 깨졌거나 enabled 가 false 면 올리지 않는다.
  '기본값은 올리지 않는다' 쪽이다 — 조용히 나가는 것보다 조용히 멈추는
  편이 되돌리기 쉽다.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "content" / "microposts.yaml"
LEDGER = ROOT / "content" / "microposts_posted.json"
KST = timezone(timedelta(hours=9))
MAX_LEN = 500          # Threads 본문 한도
LOW_WATER = 6          # 남은 글이 이보다 적으면 채우라고 알린다
# 글의 성격. content = 계산·비교 본편, soft = 맞팔(스하리)용 인사글.
# track 이 없으면 content 로 본다 — 기존 글을 전부 고치지 않기 위해서다.
TRACKS = ("content", "soft")
# 2026-10-05: GitHub 예약 실행이 주말에 4~5시간씩 밀려 보조 실행(+1h, +2h)을 붙였다.
# 예약 실행끼리는 이 시간 안에 이미 한 편이 나갔으면 건너뛴다(손으로 돌린 실행은 제외).
SCHEDULED_GAP_HOURS = 10
DEFAULT_TRACK = "content"


def track_of(post: dict) -> str:
    return post.get("track") or DEFAULT_TRACK


def render(post: dict) -> str:
    """실제로 쓰레드에 나갈 최종 본문.

    태그를 topic_tag 파라미터로만 넘기면 글에 보이지 않는다. 공식 문서 기준
    한 게시물에 태그는 하나만 유효하고("Only one topic tag is allowed per
    post"), 본문에 쓴 첫 태그가 그 게시물의 태그로 잡힌다. 그래서 파라미터
    대신 본문 끝에 한 개만 눈에 보이게 붙인다.

    여러 개를 붙이지 않는 이유: 두 번째부터는 태그로 등록되지 않고 그냥
    글자로 남아 광고처럼 읽힌다.
    """
    text = post["text"].rstrip()
    tag = post.get("topic_tag")
    return f"{text}\n\n#{tag}" if tag else text


def load_pool() -> dict:
    if not POOL.exists():
        raise RuntimeError("content/microposts.yaml 이 없습니다")
    data = yaml.safe_load(POOL.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RuntimeError("microposts.yaml 최상위는 매핑이어야 합니다")
    posts = data.get("posts") or []
    seen = set()
    for p in posts:
        for key in ("id", "text"):
            if not str(p.get(key, "")).strip():
                raise RuntimeError(f"{p.get('id', '(id 없음)')}: {key} 가 비어 있습니다")
        if p["id"] in seen:
            raise RuntimeError(f"id 중복: {p['id']}")
        seen.add(p["id"])
        tag = p.get("topic_tag")
        if len(render(p)) > MAX_LEN:
            raise RuntimeError(f"{p['id']}: 본문이 {MAX_LEN}자를 넘습니다 "
                               f"(태그 포함 {len(render(p))}자)")
        if tag is not None:
            # 주제 태그는 글당 하나만 달 수 있고, 마침표·앰퍼샌드가 들어가면 API 가 거절한다.
            if not 1 <= len(tag) <= 50 or any(c in tag for c in ".&"):
                raise RuntimeError(f"{p['id']}: 주제 태그 형식이 잘못됐습니다 ({tag!r})")
        if track_of(p) not in TRACKS:
            raise RuntimeError(f"{p['id']}: 모르는 track 입니다 ({p.get('track')!r})")
    return data


def load_ledger() -> list[dict]:
    if not LEDGER.exists():
        return []
    try:
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        # 원장이 깨졌는데 빈 값으로 넘어가면 이미 올린 글을 다시 올린다.
        raise RuntimeError(f"microposts_posted.json 을 읽을 수 없습니다: {e}") from e
    return data if isinstance(data, list) else []


def save_ledger(rows: list[dict]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")


def pick(pool: dict, posted_ids: set[str], count: int,
         track: str | None = None) -> list[dict]:
    """아직 안 올린 글을 파일에 적힌 순서대로 꺼낸다.

    track 을 주면 그 성격의 글만 꺼낸다. 밤 슬롯은 맞팔용(soft), 낮 슬롯은
    본편(content) 으로 나누기 위한 것이다.
    """
    # skip: true — 이미 나간 본편·단문과 소재가 겹치는 글(2026-09-29 중복 발행 정리)
    remaining = [p for p in (pool.get("posts") or [])
                 if p["id"] not in posted_ids and not p.get("skip")]
    if track:
        remaining = [p for p in remaining if track_of(p) == track]
    return remaining[:max(0, count)]


def _git(*args: str) -> str:
    return subprocess.run(("git",) + args, cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit_ledger(message: str) -> bool:
    """원장을 저장소에 남긴다. 남기지 못하면 다음 실행이 같은 글을 또 올린다."""
    _git("add", str(LEDGER))
    if not subprocess.run(("git", "status", "--porcelain", str(LEDGER)),
                          cwd=ROOT, capture_output=True, text=True).stdout.strip():
        return False
    _git("-c", "user.name=donvalue-bot",
         "-c", "user.email=bot@users.noreply.github.com",
         "commit", "-m", message)
    for _ in range(5):
        try:
            _git("push")
            return True
        except subprocess.CalledProcessError:
            try:
                _git("pull", "--rebase")
            except subprocess.CalledProcessError:
                break
    raise RuntimeError("원장 푸시 실패 — 중복 발행을 막기 위해 중단합니다")


def posted_recently(ledger: list[dict], hours: float, now: datetime | None = None) -> str:
    """최근 hours 시간 안에 나간 글 id. 없으면 빈 문자열."""
    now = now or datetime.now(KST)
    for row in reversed(ledger):
        try:
            at = datetime.fromisoformat(str(row.get("posted_at", "")))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=KST)
        if timedelta(0) <= now - at < timedelta(hours=hours):
            return str(row.get("id", ""))
    return ""


def run(count: int, dry_run: bool, track: str | None = None) -> int:
    from src import notify

    if track and track not in TRACKS:
        raise RuntimeError(f"모르는 track 입니다: {track!r}")
    pool = load_pool()
    if not pool.get("enabled"):
        print("[micro] enabled 가 false 입니다 → 올리지 않습니다.")
        return 0
    # 2026-09-29 소유자 요청: 쓰레드는 본편 글 + 스하리(soft) 글만. 단문 콘텐츠 글은 끈다.
    # 허용 목록은 microposts.yaml 의 tracks 가 정한다(없으면 soft 만).
    allowed = [t for t in (pool.get("tracks") or ["soft"]) if t in TRACKS]
    if track and track not in allowed:
        print(f"[micro] {track} 글은 꺼져 있습니다(tracks={allowed}) → 올리지 않습니다.")
        return 0
    if not track:
        track = allowed[0] if len(allowed) == 1 else None

    ledger = load_ledger()
    if os.getenv("SCHEDULE") and not dry_run:
        recent = posted_recently(ledger, SCHEDULED_GAP_HOURS)
        if recent:
            print(f"[micro] 최근 {SCHEDULED_GAP_HOURS}시간 안에 이미 올렸습니다({recent}) → 보조 실행은 건너뜁니다.")
            return 0
    posted_ids = {r["id"] for r in ledger}
    picks = pick(pool, posted_ids, count, track)
    fellback = False
    if track and not picks:
        # 요청한 성격의 글이 떨어졌을 때 다른 성격 글로 채우는 건 허용된 성격끼리만.
        # (예전엔 soft 가 비면 콘텐츠 단문으로 채웠다 — 이제 콘텐츠 단문은 꺼져 있다.)
        others = [t for t in allowed if t != track]
        for t in others:
            picks = pick(pool, posted_ids, count, t)
            if picks:
                break
        fellback = bool(picks)
        print(f"[micro] {track} 풀이 비었습니다" + (" → 다른 허용 글로 대체합니다." if picks else "."))
    remaining = len([p for p in pool["posts"] if p["id"] not in posted_ids and not p.get("skip")])
    left_in_track = len(pick(pool, posted_ids, 10 ** 6, track)) if track else None

    if not picks:
        print("[micro] 올릴 글이 없습니다 — 풀이 비었습니다.")
        if notify.enabled():
            try:
                notify.send_message(f"{notify.LABEL} · 쓰레드 단문 풀이 비었습니다.\n"
                                    "content/microposts.yaml 에 글을 더 넣어주세요.")
            except Exception as e:                                # noqa: BLE001
                print(f"[telegram] 통보 실패: {e}")
        return 0

    if dry_run:
        for p in picks:
            print(f"--- {p['id']}\n{render(p)}\n")
        print(f"[micro] dry-run — 발행하지 않았습니다. 남은 글 {remaining}개")
        return 0

    th_id, th_tok = os.getenv("TH_USER_ID"), os.getenv("TH_ACCESS_TOKEN")
    if not (th_id and th_tok):
        print("[micro] 쓰레드 토큰이 없습니다 → 건너뜀")
        return 0

    from src import publish
    sent, failed = [], []
    for p in picks:
        try:
            # 태그는 render() 가 본문 안에 넣는다. 파라미터로 또 넘기면
            # 한 글에 태그가 둘이 되어 어느 쪽이 잡힐지 문서에 정의돼 있지 않다.
            post_id = publish.publish_threads(th_id, th_tok, [], render(p))
        except Exception as e:                                    # noqa: BLE001
            failed.append((p["id"], str(e)))
            print(f"[micro] {p['id']} 실패: {e}")
            continue
        ledger.append({"id": p["id"], "threads": post_id,
                       "posted_at": datetime.now(KST).isoformat(timespec="seconds")})
        sent.append(p)
        print(f"[micro] {p['id']} 발행 완료 post_id={post_id}")
        # 한 건이라도 올렸으면 그 즉시 원장에 남긴다.
        # 뒤 글에서 터져도 이미 올린 글이 다시 나가면 안 된다.
        save_ledger(ledger)

    if sent:
        commit_ledger("microposts: " + ", ".join(p["id"] for p in sent))

    if notify.enabled():
        label = f"[{track}]" if track else ""
        lines = [f"{notify.LABEL} · 쓰레드 단문 {label} {len(sent)}건 발행".replace("  ", " ")]
        lines += [f"· {p['id']} [{p.get('topic_tag') or '태그없음'}]" for p in sent]
        if fellback:
            lines.append(f"※ {track} 풀이 비어 다른 글로 대체했습니다.")
        elif left_in_track is not None:
            lines.append(f"{track} 남은 글 {left_in_track - len(sent)}개")
        if failed:
            lines += [f"⚠ 실패 {i}: {m}" for i, m in failed]
        left = remaining - len(sent)
        lines.append(f"남은 글 {left}개")
        if left <= LOW_WATER:
            lines.append("※ 곧 바닥납니다. microposts.yaml 을 채워주세요.")
        try:
            notify.send_message("\n".join(lines))
        except Exception as e:                                    # noqa: BLE001
            print(f"[telegram] 통보 실패: {e}")

    return 1 if (failed and not sent) else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=1, help="이번 실행에서 낼 글 수")
    ap.add_argument("--dry-run", action="store_true", help="렌더만 하고 올리지 않음")
    ap.add_argument("--track", choices=TRACKS, default=None,
                    help="content = 계산·비교 본편 / soft = 맞팔(스하리)용")
    args = ap.parse_args()
    return run(args.count, args.dry_run, args.track)


if __name__ == "__main__":
    raise SystemExit(main())
