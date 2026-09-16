# Claude 검토 인계

사용자 요청으로 GPT와 Claude 양쪽의 주제별 표지 86편을 제작한 검토 브랜치입니다. main 병합과 실제 발행은 수행하지 않았습니다.

- 원본 사진: `assets/covers/*.editorial-v3.jpg` (86편, SHA는 이 폴더 asset-manifest.json).
- 최종 표지: 이 폴더의 `*-card.jpg`, 릴스 첫 화면: `*-reel.jpg`. `index.html`은 내려받아 브라우저에서 열면 전체 비교 가능합니다. GitHub에서는 sheet-01.jpg~15.jpg, reels-01.jpg~15.jpg를 바로 볼 수 있습니다.
- GPT: content.json의 47편 표지 경로/SHA, threshold_specs.json 11편 표지, media.py의 조판과 cx112 pop 카드 첫 화면 경로 수정.
- Claude: src/photo_covers.py 추가, render.py 및 reel_scenes.py에서 해당 사진이 있는 편만 사용.
- 본문/일정/발행기록은 변경하지 않았습니다. cx004/cx005/cx008의 기존 승인용 콘텐츠도 보존했습니다. cx005/cx008 새 표지는 별도 검토 이미지입니다.
- 기발행 정수기 002는 새 표지만 준비했으며 삭제/재발행하지 않았습니다.
- 카드 86장과 릴스 첫 화면 86장을 모바일 360px 기준 직접 검토했습니다. 전체 영상/음성/후속 카드/SNS 노출은 미검증입니다.
- 암호화된 최신 승인 상태는 확인하지 못했으므로 병합 전 승인/기발행 대상과 충돌 여부를 확인해야 합니다. 승인된 결과물은 재렌더하지 않고 그대로 발행하는 규칙을 유지해야 합니다.
- 필수 검증: `python -m unittest discover -s codex/tests -q` (50개 통과). 별도 tests.txt는 제작 시점 로그입니다.

우선 확인할 이미지: 002-water-purifier, 003-gym-annual, cx107-filter-service, cx112-charger-drawer.
원고에 이미 있던 가격·정책 등의 최신 사실 검증은 이번 표지 작업 범위에 포함되지 않았습니다.
