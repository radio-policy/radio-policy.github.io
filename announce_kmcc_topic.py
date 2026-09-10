# -*- coding: utf-8 -*-
"""
일회성 안내 — 구독 봇(정책 AI도우미)에 '📺 방미통위 동향' 토픽이 생겼음을 기존 구독자에게 알린다.
(2026-09-11 10:00 KST 1회 발송 — 운영자 결정. 배경역사 #154)

- 대상: telegram_subscribers.active = true 전원 (기존 구독자는 topic_kmcc = false 로 시작하므로 켜라고 안내)
- 발송: SUBSCRIBER_BOT_TOKEN 으로 sendMessage 직접 호출 (운영자 봇 notify.send_telegram 이 아님 — 다른 봇)
- 403(차단)·400 은 로그만 남기고 다음 사람으로. DB 는 읽기만 한다(active 갱신은 발송 함수의 몫).
- 사실만 적는다(운영자 지시): 무엇이, 언제 오는지. 과장·권유 문구 없음.

  python announce_kmcc_topic.py --dry-run   # 대상 수·문구만 출력
  python announce_kmcc_topic.py             # 실제 발송
"""
import os
import sys
import time
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
from sb_client import make_client

TEXT = (
    '📢 <b>정책 AI도우미에 새 항목이 추가되었습니다</b>\n\n'
    '📺 <b>방미통위 동향</b>\n'
    '방송미디어통신위원회 <b>회의 의사일정</b>(회의 전날 게시)과 <b>보도자료 전건</b>(위원회 결과 포함)을 '
    '게시 직후 보내드립니다. 의사일정은 안건 표 전체, 위원회 결과는 안건별 의결 요지, '
    '그 밖의 보도자료는 제목·담당부서·본문 앞부분과 원문 링크입니다.\n\n'
    '기존 구독자는 <b>꺼짐</b> 상태로 시작합니다. 받으시려면 /settings 에서 '
    '<b>📺 방미통위 동향</b>을 켜 주세요. 받는 시간대(시작~종료 시각)는 기존 설정을 따릅니다.'
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    token = os.environ.get('SUBSCRIBER_BOT_TOKEN', '')
    if not token and not args.dry_run:
        print('[안내] SUBSCRIBER_BOT_TOKEN 없음 — 중단')
        sys.exit(1)
    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    rows = (sb.table('telegram_subscribers').select('chat_id, first_name, username, topic_kmcc')
            .eq('active', True).order('created_at').execute().data) or []
    print('[안내] 대상 %d명' % len(rows))
    print(TEXT)
    if args.dry_run:
        for r in rows:
            print('  - %s (%s) kmcc=%s' % (r.get('first_name') or '-', r.get('username') or r['chat_id'], r.get('topic_kmcc')))
        return

    ok = fail = 0
    for r in rows:
        try:
            resp = requests.post('https://api.telegram.org/bot%s/sendMessage' % token,
                                 json={'chat_id': r['chat_id'], 'text': TEXT, 'parse_mode': 'HTML',
                                       'disable_web_page_preview': True}, timeout=15)
            if resp.status_code == 200:
                ok += 1
                print('  ✓ %s' % (r.get('first_name') or r['chat_id']))
            else:
                fail += 1
                print('  ✗ %s HTTP %s %s' % (r.get('first_name') or r['chat_id'], resp.status_code, resp.text[:100]))
        except Exception as e:
            fail += 1
            print('  ✗ %s %s' % (r.get('first_name') or r['chat_id'], str(e)[:100]))
        time.sleep(0.2)
    print('[안내 완료] 성공 %d · 실패 %d' % (ok, fail))


if __name__ == '__main__':
    main()
