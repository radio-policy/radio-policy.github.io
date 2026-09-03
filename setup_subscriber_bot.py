#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
구독자 봇 초기 설정 — webhook 등록 + 명령어 메뉴 등록 (1회 실행)

사전 준비
  1) BotFather에서 새 봇 생성 → 토큰 확보
  2) .env 에 아래 2개 추가 (토큰은 절대 코드·문서에 하드코딩 금지 — 공개 저장소)
       SUBSCRIBER_BOT_TOKEN=123456:AA...
       TELEGRAM_WEBHOOK_SECRET=아무_긴_랜덤문자열   (Supabase Edge Secrets에 넣은 값과 동일해야 함)
  3) Supabase → Project Settings → Edge Functions → Secrets 에 등록:
       SUBSCRIBER_BOT_TOKEN / TELEGRAM_WEBHOOK_SECRET / CRON_SECRET / ANTHROPIC_API_KEY / OPERATOR_CHAT_ID

사용:  python setup_subscriber_bot.py           (등록)
       python setup_subscriber_bot.py --info    (현재 webhook 상태만 확인)
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')   # 스케줄러 cp949 캡처 대비(지침 #19)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests

TOKEN = os.environ.get('SUBSCRIBER_BOT_TOKEN', '')
SECRET = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')
WEBHOOK_URL = 'https://zwkjedumfuhodckmtxxn.supabase.co/functions/v1/telegram-webhook'

# 채팅방 상단에 보이는 이름(표시명). 사용자명(@radio_policy_law_ai_bot)과는 별개이며
# 표시명은 한글도 가능하다. 사용자명 변경은 BotFather에서만 가능(중복 불가, bot으로 끝나야 함).
BOT_NAME = '정책 AI도우미'
BOT_SHORT_DESC = '전파정책 브리핑·법령 검색·AI 자문'
BOT_DESC = (
    '전파·통신 정책 브리핑을 원하는 시각에 받아보고, 법령 조문을 검색할 수 있는 봇입니다.\n\n'
    '📡 모닝 브리핑 · 📡 주요 뉴스 · 🏛️ 국회·법률 동향 (선택한 시각에 한 번에 도착)\n'
    '   국회·법률 동향 = 국회 법안 · 입법예고(국회·부처) · 과방위 회의록 요약\n'
    '📖 법령 검색 — 예: /law 3G 종료 관련 법령 (조문 번호를 알면 /law 전기통신사업법 19조)\n'
    '🤖 AI 자문 — /ask 질문 (동향·시사점까지, 운영자 최초 1회 승인 필요)\n\n'
    '시작하려면 아래 시작 버튼을 누르세요.'
)

COMMANDS = [
    {'command': 'start',    'description': '구독 시작 · 설정 메뉴'},
    {'command': 'settings', 'description': '수신 설정 변경'},
    # 예시를 자연어로 바꿨다 — 실제 쓰임새는 "조항 번호를 아는" 경우가 아니라
    # "이게 어떤 법과 관련되나"를 묻는 쪽이 대부분이다(운영자, 2026-08-03).
    {'command': 'law',      'description': '법령 검색 (예: /law 3G 종료 관련 법령)'},
    {'command': 'ask',      'description': 'AI 자문 (동향·시사점까지, 최초 1회 승인 필요)'},
    # /stop 은 메뉴에서 뺐다 — /settings 에서 항목 3개를 끄면 같은 결과라 중복이고,
    # "해지 vs 항목 끄기" 두 상태가 있는 것처럼 보여 혼동을 준다. 명령 자체는 살려둔다(하위호환).
]


def api(method: str, **payload):
    r = requests.post(f'https://api.telegram.org/bot{TOKEN}/{method}', json=payload, timeout=15)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {'raw': r.text[:200]}


def main() -> int:
    if not TOKEN:
        print('[오류] .env에 SUBSCRIBER_BOT_TOKEN이 없습니다.')
        return 1

    if '--info' in sys.argv:
        code, res = api('getWebhookInfo')
        print(f'[webhook 상태] HTTP {code}: {res}')
        return 0 if code == 200 else 1

    if not SECRET:
        print('[오류] .env에 TELEGRAM_WEBHOOK_SECRET이 없습니다 (Edge Secrets와 같은 값이어야 함).')
        return 1

    code, res = api('setWebhook', url=WEBHOOK_URL, secret_token=SECRET,
                    allowed_updates=['message', 'callback_query'],
                    drop_pending_updates=True)
    print(f'[setWebhook] HTTP {code}: {res.get("description", res)}')
    if code != 200 or not res.get('ok'):
        return 1

    code, res = api('setMyCommands', commands=COMMANDS)
    print(f'[setMyCommands] HTTP {code}: {res.get("description", res)}')

    # 표시명·소개문 (채팅방 상단 이름). 텔레그램이 하루 변경 횟수를 제한하므로 실패해도 진행.
    for method, payload, label in (
        ('setMyName', {'name': BOT_NAME}, '표시명'),
        ('setMyShortDescription', {'short_description': BOT_SHORT_DESC}, '한줄소개'),
        ('setMyDescription', {'description': BOT_DESC}, '소개문'),
    ):
        code, res = api(method, **payload)
        ok = code == 200 and res.get('ok')
        print(f'[{method}] {"OK" if ok else "실패"} ({label}) — {res.get("description", "")}')

    code, res = api('getMe')
    if code == 200 and res.get('ok'):
        me = res['result']
        print(f'\n✅ 준비 완료 — 텔레그램에서 @{me.get("username")} 를 찾아 /start 를 보내보세요.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
