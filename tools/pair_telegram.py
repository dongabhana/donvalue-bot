"""One-time owner pairing. Only encrypted routing data is committed."""
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet

OWNER = Path('content/telegram_owner.enc')
PAIR_HASH = '43107d1e8d02d170ecf788e2accf1a1569f72724d83e7cab5431de8e565eb325'


def api(token, method, **payload):
    try:
        req = Request('https://api.telegram.org/bot' + token + '/' + method,
                      data=json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=35) as r:
            data = json.load(r)
        if not data.get('ok'):
            raise RuntimeError()
        return data['result']
    except Exception:
        raise RuntimeError('Telegram request failed: ' + method) from None


def cipher(token):
    key = hashlib.sha256(('donvalue-owner-v1:' + token).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def select_owner(updates, now):
    candidates = set()
    for update in updates:
        msg = update.get('message', {})
        chat, sender = msg.get('chat', {}), msg.get('from', {})
        if chat.get('type') != 'private' or sender.get('is_bot'):
            continue
        if chat.get('id') != sender.get('id') or not isinstance(chat.get('id'), int):
            continue
        if not 0 <= now - msg.get('date', 0) <= 3600:
            continue
        if hashlib.sha256(msg.get('text', '').strip().encode()).hexdigest() == PAIR_HASH:
            candidates.add((chat['id'], sender['id']))
    if len(candidates) != 1:
        raise RuntimeError('Expected exactly one recent matching private pairing message')
    chat_id, user_id = candidates.pop()
    return {'chat_id': chat_id, 'user_id': user_id}


def git(*args):
    result = subprocess.run(['git', *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Could not persist encrypted owner routing')


def main():
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        raise RuntimeError('Missing TELEGRAM_BOT_TOKEN')
    if api(token, 'getMe').get('username', '').lower() != 'donvalue_approval_bot':
        raise RuntimeError('Unexpected bot identity')
    if OWNER.exists():
        cipher(token).decrypt(OWNER.read_bytes())
        print('Owner already paired; no rebinding or duplicate message')
        return
    if api(token, 'getWebhookInfo').get('url'):
        raise RuntimeError('Existing webhook detected; left unchanged')
    updates = api(token, 'getUpdates', timeout=0, limit=100)
    owner = select_owner(updates, time.time())
    owner['paired_at'] = int(time.time())
    OWNER.parent.mkdir(parents=True, exist_ok=True)
    OWNER.write_bytes(cipher(token).encrypt(json.dumps(owner).encode()))
    git('add', str(OWNER))
    git('-c', 'user.name=donvalue-bot', '-c', 'user.email=bot@users.noreply.github.com',
        'commit', '-m', 'Pair Telegram owner using encrypted routing data')
    git('push')
    api(token, 'sendMessage', chat_id=owner['chat_id'], text=(
        '돈값하나 승인 봇 연결을 확인했어. 이 대화방을 승인 알림 수신처로 등록했어.\n\n'
        '현재 완료: 봇 인증과 대화방 연결.\n'
        '아직 작업 중: 콘텐츠 미리보기, 승인 버튼, 승인 후 예약 게시, 댓글 대응.\n'
        '이 메시지는 연결 확인용이고 SNS 게시 승인을 뜻하지 않아.'))
    print('PAIRING_OK: encrypted routing persisted; confirmation message delivered')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Do not print URLs, update payloads, IDs, or exception details.
        print('PAIRING_FAILED: ' + type(exc).__name__ + '; no sensitive details logged')
        sys.exit(1)
