"""발행 파이프라인 상태 점검.

공개 저장소의 Actions 로그에 찍히므로 비밀값·메시지 내용은 출력하지 않고
편 ID와 상태만 보여준다. 암호화된 상태 파일(codex/state.enc,
content/reviews/*.enc)을 사람이 읽을 수 있게 풀어 주는 유일한 창구다.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.pair_telegram import cipher  # noqa: E402


def main():
    crypt = cipher(os.environ['TELEGRAM_BOT_TOKEN'])
    st = json.loads(crypt.decrypt((ROOT / 'codex/state.enc').read_bytes()))
    items = {i['id']: i for i in json.loads((ROOT / 'codex/content.json').read_text())['items']}
    from codex.engine import fingerprint

    print('== GPT 트랙 기록 (codex/state.enc records)')
    for key, rec in sorted(st.get('records', {}).items()):
        item = items.get(key)
        match = None
        if item and rec.get('manifest') is not None:
            match = fingerprint(item, rec['manifest']) == rec.get('hash')
        ops = {n: o.get('status') for n, o in (rec.get('operations') or {}).items()}
        print(key, '| 예정', item['publish_at'] if item else '(큐에 없음)',
              '|', rec.get('decision'), rec.get('review_kind'),
              '| 승인', rec.get('approved_at'), '| 게시예정', rec.get('scheduled_at'),
              '| 원고일치', match, '| 닫힘', rec.get('closed'), '| 게시', ops)

    print('== Claude 트랙 승인 요청 (content/reviews)')
    reqs = {p.stem: json.loads(crypt.decrypt(p.read_bytes()))
            for p in (ROOT / 'content/reviews').glob('*.enc')}
    shared = st.get('shared_reviews', {})
    for key, req in reqs.items():
        rec = shared.get(key, {})
        print(key[:6], req['item_id'], '| 생성', req.get('created_at'),
              '| 예정', req['context'].get('scheduled_at'), '| 버튼', bool(req.get('message_id')),
              '|', {k: rec.get(k) for k in ('decision', 'approved_at', 'scheduled_at',
                                             'started', 'done', 'needs_review')})
    print('== 요청 파일이 지워진 승인 기록')
    for key, rec in shared.items():
        if key not in reqs:
            print(key[:6], {k: rec.get(k) for k in ('decision', 'approved_at', 'scheduled_at',
                                                     'started', 'done', 'needs_review')})
    print('== 기타: offset', st.get('offset'), '/ 의견', len(st.get('feedback', [])), '건')


if __name__ == '__main__':
    main()
