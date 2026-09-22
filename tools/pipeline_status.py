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


GPT_SLOTS = {0: '21:20', 2: '21:20', 4: '15:30', 5: '15:30'}    # 월·수·금·토
CLAUDE_SLOTS = {1: '21:20', 3: '21:20', 6: '15:30'}            # 화·목·일


def youtube_section(delivery, today, today_posted):
    """점검표의 유튜브 칸. (줄 목록, 경고 목록) 을 돌려준다.

    왜 따로 있나 —
      유튜브는 content/delivery.json 한 곳에만 기록된다. 예전 점검표는
      인스타·쓰레드만 봐서, 인스타에는 나갔는데 유튜브만 빠진 날을
      '이상 없음'으로 넘겼다. 2026-09-22 부터 같은 날 세 곳에 올리므로
      유튜브가 빠졌는지를 여기서 본다. 회귀 테스트 codex/tests/test_status_youtube.py
    """
    done_today = sorted((ops['youtube']['at'][11:16], key)
                        for key, ops in delivery.items()
                        if (ops.get('youtube') or {}).get('status') == 'done'
                        and str(ops['youtube'].get('at', '')).startswith(today))
    lines = ['[유튜브]'] + ([f'{t} {k} ✅' for t, k in done_today] or ['오늘 올라간 편 없음'])

    warn = []
    # in_flight 는 따라올리기가 건너뛴다. 사람이 안 보면 영영 안 올라간다.
    stuck = sorted(k for k, ops in delivery.items()
                   if (ops.get('youtube') or {}).get('status') == 'in_flight')
    if stuck:
        warn.append('유튜브 업로드 중단됨: ' + ', '.join(stuck))
    # 오늘 인스타에 나간 편은 20분 안에 유튜브로 따라 올라가야 한다.
    pending = sorted(k for k in today_posted
                     if (delivery.get(k, {}).get('youtube') or {}).get('status') != 'done')
    if pending:
        warn.append('유튜브 미게시: ' + ', '.join(pending))
    return lines, warn


def daily_summary(now=None):
    """매일 밤 텔레그램으로 보내는 한 장짜리 점검표. 조용한 실패를 없애는 게 목적.

    2026-09-22부터 두 트랙 모두 승인 없이 순번대로 매일 한 편씩 나간다.
    그래서 '오늘 슬롯에 실제로 나갔는지', '내일 무엇이 나갈지', '몇 편 남았는지'만 본다.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    import yaml
    from codex.engine import next_in_line
    now = now or datetime.now(ZoneInfo('Asia/Seoul'))
    today, tomorrow = now.date(), now.date() + timedelta(days=1)
    crypt = cipher(os.environ['TELEGRAM_BOT_TOKEN'])
    st = json.loads(crypt.decrypt((ROOT / 'codex/state.enc').read_bytes()))
    records = st.get('records', {})
    items = json.loads((ROOT / 'codex/content.json').read_text())['items']
    posted = json.loads((ROOT / 'content/posted.json').read_text(encoding='utf-8'))
    queue = yaml.safe_load((ROOT / 'content/queue.yaml').read_text(encoding='utf-8'))
    posted_ids = {p['id'] for p in posted}
    claude_left = [i['id'] for i in queue['items'] if i['id'] not in posted_ids and i.get('verified')]
    gpt_left = [i['id'] for i in next_in_line(items, records)]

    gpt_today = sorted((op['at'][11:16], key) for key, rec in records.items()
                       for name, op in (rec.get('operations') or {}).items()
                       if name == 'instagram' and op.get('status') == 'done'
                       and str(op.get('at', '')).startswith(today.isoformat()))
    claude_today = sorted((p['posted_at'][11:16], p['id']) for p in posted
                          if str(p.get('posted_at', '')).startswith(today.isoformat()))
    warn = []
    lines = ['📋 돈값하나 점검 ' + now.strftime('%m/%d %H:%M'), '[오늘 게시]']
    lines += [f'GPT {t} {k} ✅' for t, k in gpt_today] + [f'Claude {t} {k} ✅' for t, k in claude_today]
    if not gpt_today and not claude_today:
        lines.append('없음')
    for track, slots, done in (('GPT', GPT_SLOTS, gpt_today), ('Claude', CLAUDE_SLOTS, claude_today)):
        hm = slots.get(today.weekday())
        if hm and now.strftime('%H:%M') > hm and not done:
            warn.append(f'{track} 오늘 {hm} 슬롯 미게시')
    for key, rec in records.items():
        if any(op.get('status') in ('needs_review', 'in_flight') for op in (rec.get('operations') or {}).values()):
            warn.append(key + ' 게시 단계 확인 필요')

    delivery = json.loads((ROOT / 'content/delivery.json').read_text(encoding='utf-8'))
    yt_lines, yt_warn = youtube_section(
        delivery, today.isoformat(),
        {k for _, k in gpt_today} | {k for _, k in claude_today})
    lines += yt_lines
    warn += yt_warn

    lines.append('[내일 예정]')
    if tomorrow.weekday() in GPT_SLOTS:
        lines.append(f'GPT {GPT_SLOTS[tomorrow.weekday()]} {(gpt_left or ["없음"])[0]}')
    if tomorrow.weekday() in CLAUDE_SLOTS:
        lines.append(f'Claude {CLAUDE_SLOTS[tomorrow.weekday()]} {(claude_left or ["없음"])[0]}')
    lines.append(f'[남은 편] GPT {len(gpt_left)}편 · Claude {len(claude_left)}편')
    for track, left in (('GPT', gpt_left), ('Claude', claude_left)):
        if len(left) < 6:
            warn.append(f'{track} 남은 편 {len(left)}편 — 채워야 함')
    if warn:
        lines.append('⚠ 확인 필요: ' + ' / '.join(warn))
    else:
        lines.append('이상 없음')
    return '\n'.join(lines)


if __name__ == '__main__':
    if '--notify' in sys.argv:
        from src import notify
        text = daily_summary()
        print(text)
        notify.send_message(text)
    else:
        main()
