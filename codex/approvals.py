"""One Telegram receiver, durable version-bound approvals for both publishers."""
import argparse
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from tools.pair_telegram import cipher

ROOT = Path(__file__).resolve().parent.parent
REQUESTS = ROOT / 'content/reviews'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def claude_source(item, cta):
    return digest({'item': item, 'cta': cta})


def load_requests():
    crypt = cipher(os.environ['TELEGRAM_BOT_TOKEN'])
    return {p.stem: json.loads(crypt.decrypt(p.read_bytes())) for p in REQUESTS.glob('*.enc')}


def state():
    crypt = cipher(os.environ['TELEGRAM_BOT_TOKEN'])
    return json.loads(crypt.decrypt((ROOT / 'codex/state.enc').read_bytes()))


def register(item_id, title, body, video, photos, context):
    from src import notify
    from codex.engine import commit, KST
    if not context:
        raise RuntimeError('Approval requires an immutable content and media context')
    # Reuse an outstanding version instead of invalidating its buttons each run.
    for key, request in load_requests().items():
        if request['item_id'] == item_id and request['context'] == context:
            decision = state().get('shared_reviews', {}).get(key, {})
            if not decision.get('done'):
                # 예전에는 여기서 아무 말 없이 끝냈다. 그 결과 승인 버튼을 한 번
                # 놓치면 다음 발행 실행이 38초 만에 조용히 종료되고, 그 뒤로도
                # 계속 같은 자리에서 멈춘 줄 모르는 상태가 이어졌다(2026-09-20).
                # 버튼 자체는 재발송하지 않는다 — message_id 가 바뀌면 기존
                # 버튼이 '이전 승인창'으로 무효 처리되기 때문이다. 대신 대기
                # 중이라는 사실과 그 결과를 매번 알린다.
                print('APPROVAL_REQUEST_EXISTS: ' + item_id)
                try:
                    notify.send_message(
                        '⏳ 승인 대기 중입니다\n'
                        + title + '\n'
                        + '게시 예정: ' + context['scheduled_at'] + '\n'
                        + '먼저 보낸 메시지의 [승인] 버튼을 눌러주세요. '
                        + '누르지 않으면 이 편도, 뒤에 오는 편도 계속 나가지 않습니다.')
                except Exception as e:                            # noqa: BLE001
                    print('APPROVAL_REMINDER_FAILED: ' + str(e))
                return None
    key = secrets.token_hex(8)
    request = {'item_id': item_id, 'title': title, 'context': context,
               'created_at': datetime.now(KST).isoformat(), 'message_id': None}
    REQUESTS.mkdir(parents=True, exist_ok=True)
    path = REQUESTS / (key + '.enc')
    crypt = cipher(os.environ['TELEGRAM_BOT_TOKEN'])
    path.write_bytes(crypt.encrypt(json.dumps(request, ensure_ascii=False).encode()))
    commit([ROOT / p for p in context['files']] + [path], 'Persist immutable approval request ' + item_id)
    if video:
        notify.send_video(video, title)
    if photos:
        notify.send_photos(photos, title)
    # Include all approval text; Telegram's limit must not silently drop the end.
    for start in range(0, len(body), 3500):
        notify.send_message(body[start:start + 3500])
    message = notify.send_message(
        title + '\n게시 예정: ' + context['scheduled_at'] +
        '\n승인하면 저장 후 확인 메시지를 보내요. 미루면 다시 승인할 때까지 게시하지 않아요.' +
        '\n버튼은 약 5분 간격으로 확인하며 실행 지연이 있을 수 있어요.',
        buttons=[[{'text': '승인', 'callback_data': f'v|{key}|a'},
                  {'text': '미루기', 'callback_data': f'v|{key}|h'}]])
    request['message_id'] = message['message_id']
    path.write_bytes(crypt.encrypt(json.dumps(request, ensure_ascii=False).encode()))
    commit([path], 'Bind approval buttons to immutable request ' + item_id)
    return None


def schedule(original, now):
    return max(datetime.fromisoformat(original), now + timedelta(minutes=1)).isoformat()


def decision_message(title, rec):
    if rec['decision'] == 'approved':
        when = datetime.fromisoformat(rec['scheduled_at']).strftime('%m/%d %H:%M')
        return f'승인됐어요. 승인 기록을 저장했습니다.\n{title}\n게시 예정: {when} (한국시간)'
    return f'미뤘어요. 다시 승인하기 전에는 게시하지 않습니다.\n{title}\n게시하려면 같은 메시지의 승인 버튼을 눌러주세요.'


def flush_notices(engine):
    for records in (engine.state.get('records', {}), engine.state.get('shared_reviews', {})):
        for rec in records.values():
            if rec.get('notice_pending'):
                engine.tell(rec['notice_pending'])
                rec.pop('notice_pending')
                engine.save()


def migrate_buttons(engine):
    for key, rec in engine.state['records'].items():
        if (rec.get('review_kind') != 'real' or rec.get('operations') or
                not rec.get('message_id') or rec.get('buttons_version') == 2):
            continue
        markup = {'inline_keyboard': [[
            {'text': '승인', 'callback_data': f'a|{key}|{rec["hash"][:12]}'},
            {'text': '미루기', 'callback_data': f'h|{key}|{rec["hash"][:12]}'}]]}
        try:
            engine.tg('editMessageReplyMarkup', chat_id=engine.owner['chat_id'],
                      message_id=rec['message_id'], reply_markup=markup)
            rec['buttons_version'] = 2
            engine.save()
        except RuntimeError:
            print('BUTTON_MIGRATION_NEEDS_REVIEW: ' + key)


def callback(engine, cb, parts, now):
    if len(parts) != 3 or parts[0] != 'v':
        return False
    _, key, action = parts
    request = load_requests().get(key)
    if not request or request['message_id'] != cb['message'].get('message_id') or action not in ('a', 'h'):
        engine.tell('이전 승인창입니다. 최신 콘텐츠 아래의 승인 / 미루기를 사용해주세요.')
        return True
    rec = engine.state.setdefault('shared_reviews', {}).setdefault(key, {})
    if rec.get('done') or rec.get('started'):
        engine.tell('이미 발행됐거나 발행 결과를 확인 중인 콘텐츠입니다. 중복 게시하지 않아요.')
        return True
    context = request['context']
    if action == 'a':
        validate_request(request)
        rec.update(decision='approved', approved_at=now.isoformat(),
                   scheduled_at=schedule(context['scheduled_at'], now))
    else:
        rec['decision'] = 'deferred'
    rec['notice_pending'] = decision_message(request['title'], rec)
    engine.save()  # Confirm to the owner only after the durable save succeeds.
    return True


def validate_request(request):
    from src import run, hooks
    import yaml
    queue = hooks.attach(yaml.safe_load(run.QUEUE.read_text()))
    item = next(i for i in queue['items'] if i['id'] == request['item_id'])
    context = request['context']
    if claude_source(item, queue.get('cta') or {}) != context['source_hash']:
        raise RuntimeError('Content changed after the preview; a new approval is required')
    for name, expected in context['files'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Approved media changed or is missing')
    return context


def approved_context(key, item, cta, now):
    request = load_requests()[key]
    rec = state().get('shared_reviews', {}).get(key, {})
    if (request['item_id'] != item['id'] or rec.get('decision') != 'approved'
            or rec.get('done') or datetime.fromisoformat(rec['scheduled_at']) > now):
        raise RuntimeError('No valid approval for this publication')
    context = validate_request(request)
    return {'decision': 'approved', 'ig_format': context['ig_format'],
            'fingerprint': context['fingerprint'], 'decided_at': rec['approved_at'],
            'files': context['files']}


def publish_due(engine, now):
    from src import run
    for key, request in load_requests().items():
        rec = engine.state.get('shared_reviews', {}).get(key, {})
        if (rec.get('decision') != 'approved' or rec.get('done') or rec.get('started')
                or datetime.fromisoformat(rec['scheduled_at']) > now):
            continue
        args = argparse.Namespace(id=request['item_id'], pick=request['context']['ig_format'],
                                  tomorrow=False, dry_run=False, ask_tomorrow=False, review_key=key)
        old_stagger = os.environ.get('STAGGER_MIN')
        os.environ['STAGGER_MIN'] = '0'
        try:
            validate_request(request)
            rec['started'] = now.isoformat()
            engine.save()
            result = run.run_once(args)
            ledger = json.loads(run.DELIVERY.read_text()).get(request['item_id'], {})
            ig = ledger.get('instagram_reel', ledger.get('instagram', {}))
            th = ledger.get('threads', {})
            if result or ig.get('status') != 'done' or th.get('status') != 'done':
                raise RuntimeError('Some publication stages require review')
            rec['permalinks'] = verify_posts(engine, ig['id'], th['id'])
            rec['done'] = True
            engine.save()
            engine.tell('게시 확인 완료\n' + request['title'] + '\n' + '\n'.join(rec['permalinks'].values()))
        except Exception:
            rec['needs_review'] = True
            engine.save()
            engine.tell('게시 결과 확인이 필요해 자동 재시도를 멈췄어요.\n' + request['title'])
            raise
        finally:
            if old_stagger is None:
                os.environ.pop('STAGGER_MIN', None)
            else:
                os.environ['STAGGER_MIN'] = old_stagger


def verify_posts(engine, instagram, threads):
    result = {}
    for platform, mid in [('ig', instagram), ('th', threads)]:
        data = engine.meta(platform, 'GET', str(mid), fields='id,permalink')
        if str(data.get('id')) != str(mid) or not data.get('permalink'):
            raise RuntimeError('Published post lookup did not confirm the post')
        result[platform] = data['permalink']
        print('VERIFIED_POST: ' + platform + ' ' + data['permalink'], flush=True)
    return result
