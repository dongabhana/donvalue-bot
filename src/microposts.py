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


def pick(pool: dict, posted_ids: set[str], count: int) -> list[dict]:
    """아직 안 올린 글을 파일에 적힌 순서대로 꺼낸다."""
    remaining = [p for p in (pool.get("posts") or []) if p["id"] not in posted_ids]
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


def run(count: int, dry_run: bool) -> int:
    from src import notify

    pool = load_pool()
    if not pool.get("enabled"):
        print("[micro] enabled 가 false 입니다 → 올리지 않습니다.")
        return 0

    ledger = load_ledger()
    posted_ids = {r["id"] for r in ledger}
    picks = pick(pool, posted_ids, count)
    remaining = len([p for p in pool["posts"] if p["id"] not in posted_ids])

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
        lines = [f"{notify.LABEL} · 쓰레드 단문 {len(sent)}건 발행"]
        lines += [f"· {p['id']} [{p.get('topic_tag') or '태그없음'}]" for p in sent]
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
    args = ap.parse_args()
    return run(args.count, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
