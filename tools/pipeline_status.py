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


def daily_summary(now=None):
    """매일 밤 텔레그램으로 보내는 한 장짜리 점검표. 조용한 실패를 없애는 게 목적."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    kst = ZoneInfo('Asia/Seoul')
    now = now or datetime.now(kst)
    crypt = cipher(os.environ['TELEGRAM_BOT_TOKEN'])
    st = json.loads(crypt.decrypt((ROOT / 'codex/state.enc').read_bytes()))
    items = json.loads((ROOT / 'codex/content.json').read_text())['items']
    reqs = {p.stem: json.loads(crypt.decrypt(p.read_bytes()))
            for p in (ROOT / 'content/reviews').glob('*.enc')}
    shared = st.get('shared_reviews', {})
    posted = json.loads((ROOT / 'content/posted.json').read_text(encoding='utf-8'))
    lines, warn = ['📋 돈값하나 점검 ' + now.strftime('%m/%d %H:%M')], []
    for day, label in ((now.date(), '오늘'), (now.date() + timedelta(days=1), '내일')):
        rows = []
        for it in items:
            due = datetime.fromisoformat(it['publish_at'])
            if due.date() != day or it.get('posted_early_on'):
                continue
            rec = st.get('records', {}).get(it['id'], {})
            ops = rec.get('operations', {})
            if all(ops.get(k, {}).get('status') == 'done' for k in ('instagram', 'threads')):
                state_ = '✅ 게시 완료'
            elif any(o.get('status') == 'needs_review' for o in ops.values()):
                state_ = '⚠ 게시 확인 필요'; warn.append(it['id'])
            elif rec.get('decision') == 'approved':
                state_ = '승인됨'
            elif rec.get('message_id'):
                state_ = '승인 대기(텔레그램 버튼)'
            else:
                state_ = '승인 요청 전(전날 저녁에 옴)'
            if now > due and '완료' not in state_:
                state_ += ' ⚠ 예정 시각 지남·미게시'; warn.append(it['id'])
            rows.append(f"GPT {due:%H:%M} {it['id']} — {state_}")
        for key, req in reqs.items():
            when = datetime.fromisoformat(req['context']['scheduled_at'])
            if when.date() != day:
                continue
            rec = shared.get(key, {})
            if rec.get('done'):
                state_ = '✅ 게시 완료'
            elif rec.get('needs_review'):
                state_ = '⚠ 게시 확인 필요'; warn.append(req['item_id'])
            elif rec.get('decision') == 'approved':
                state_ = '승인됨'
            else:
                state_ = '승인 대기(텔레그램 버튼)'
            if now > when and '완료' not in state_:
                state_ += ' ⚠ 예정 시각 지남·미게시'; warn.append(req['item_id'])
            rows.append(f"Claude {when:%H:%M} {req['item_id']} — {state_}")
        if label == '오늘':
            for p in posted:
                if str(p.get('posted_at', '')).startswith(day.isoformat()):
                    rows.append(f"Claude {p['posted_at'][11:16]} {p['id']} — ✅ 게시 완료")
        # Claude 트랙 요일(화·목·일)인데 그날 편이 하나도 안 잡혀 있으면 경고
        if day.weekday() in (1, 3, 6) and not any(r.startswith('Claude') for r in rows):
            rows.append('Claude — ⚠ 이 날 편이 잡혀 있지 않음(전날 21:00 승인 요청 확인)')
            if label == '오늘':
                warn.append('Claude 트랙 ' + day.isoformat())
        lines.append(f'[{label}]')
        lines += sorted(set(rows)) or ['예정된 편 없음']
    waiting = [r['item_id'] for k, r in reqs.items()
               if not shared.get(k, {}).get('decision') and not shared.get(k, {}).get('done')]
    if waiting:
        lines.append('⏳ 승인 대기: ' + ', '.join(waiting))
    if warn:
        lines.append('⚠ 확인 필요: ' + ', '.join(sorted(set(warn))))
    return '\n'.join(lines)


if __name__ == '__main__':
    if '--notify' in sys.argv:
        from src import notify
        text = daily_summary()
        print(text)
        notify.send_message(text)
    else:
        main()
