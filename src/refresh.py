"""
장기 토큰(60일) 자동 연장. GitHub Actions 에서 주기적으로 실행된다.
새 토큰을 $GITHUB_OUTPUT 에 실어 워크플로우가 시크릿을 갱신하도록 한다.
"""
from __future__ import annotations

import os
from pathlib import Path

from src import publish


def emit(key: str, value: str) -> None:
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with Path(out).open("a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def main() -> int:
    ig = os.getenv("IG_ACCESS_TOKEN")
    th = os.getenv("TH_ACCESS_TOKEN")

    if ig:
        new = publish.refresh_instagram_token(ig)
        if new and new != ig:
            emit("ig_token", new)
            print("[instagram] 토큰 연장 완료")
        else:
            print("[instagram] 연장 없음 (24시간 미경과이거나 이미 최신)")
    if th:
        new = publish.refresh_threads_token(th)
        if new and new != th:
            emit("th_token", new)
            print("[threads] 토큰 연장 완료")
        else:
            print("[threads] 연장 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
