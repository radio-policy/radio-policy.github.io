# -*- coding: utf-8 -*-
"""
구독자 봇 알림 큐 적재 모듈

구독자(telegram_subscribers)는 브리핑·긴급뉴스·법안동향을 **각자 고른 시각에 하루 한 번**
모아서 받는다. 그래서 크롤러는 직접 발송하지 않고, 여기서 subscriber_queue에 적재만 한다.
실제 발송은 매시 도는 Edge Function(send-subscriber-briefing)이 담당한다.

왜 큐인가
  긴급 뉴스의 재알림 억제·클러스터링(배경역사 #44)과 법안 상태변경 판정은 이미 Python 크롤러에
  구현돼 있다. 발송 시점을 늦추려고 그 판정을 TS로 재구현하면 두 벌이 되어 어긋난다.
  판정 결과(HTML)만 큐에 넣고, 발송 시점만 Edge Function이 정한다.

설계 원칙
  - fail-open: 큐 적재 실패가 크롤링·기존 운영자 알림을 절대 죽이지 않는다(예외를 밖으로 안 던짐).
  - 호출 위치 주의: 긴급 뉴스는 반드시 suppress_repeat_alerts()+클러스터링을 **거친 뒤** 호출한다.
"""
import os
import html as _html
from datetime import datetime, timezone, timedelta

DASHBOARD_URL = 'https://youjinwoong.github.io/radio-policy-ai/'

_VALID_TOPICS = ('urgent', 'assembly')
_KST = timezone(timedelta(hours=9))


def esc(s) -> str:
    """텔레그램 HTML 이스케이프 — & < > 가 그대로 들어가면 sendMessage가 400으로 전체 실패한다."""
    return _html.escape(str(s or ''), quote=False)


def queue_for_subscribers(sb, topic: str, html_text: str) -> bool:
    """구독자 알림 큐에 적재. 반환=성공 여부. 어떤 예외도 밖으로 던지지 않는다."""
    if topic not in _VALID_TOPICS:
        print(f'[구독자 큐] 알 수 없는 토픽: {topic}')
        return False
    if not html_text or not html_text.strip():
        return False
    try:
        sb.table('subscriber_queue').insert({'topic': topic, 'html': html_text[:3500]}).execute()
        print(f'[구독자 큐] {topic} 적재 완료 — 각 구독자의 수신 시각에 발송됨')
    except Exception as e:
        print(f'[구독자 큐] 적재 실패(무시): {e}')
        return False
    if topic == 'urgent':
        send_urgent_now(sb, html_text)   # 즉시 수신 선택자에게만 바로 발송 (fail-open)
    return True


def send_urgent_now(sb, html_text: str) -> int:
    """긴급 뉴스 '즉시 수신(야간 포함)'을 켠 구독자에게 지금 바로 발송. 반환=발송 성공 수.

    큐 적재는 그대로 두고, 발송한 구독자의 last_urgent_sent_at만 현재로 밀어
    정시 발송(send-subscriber-briefing)에서 같은 건이 다시 나가지 않게 한다.
    구독자 봇 토큰이 없거나 조회에 실패해도 크롤러를 죽이지 않는다(fail-open).
    """
    token = os.environ.get('SUBSCRIBER_BOT_TOKEN', '')
    if not token:
        return 0
    try:
        rows = (sb.table('telegram_subscribers')
                  .select('chat_id,days')
                  .eq('active', True).eq('topic_urgent', True).eq('urgent_now', True)
                  .execute().data or [])
    except Exception as e:
        print(f'[긴급 즉시] 대상 조회 실패(무시): {e}')
        return 0
    if not rows:
        return 0

    import requests
    is_weekend = datetime.now(_KST).weekday() >= 5
    now_iso = datetime.now(timezone.utc).isoformat()
    body = '🚨 <b>긴급 — 즉시 알림</b>\n\n' + html_text[:3500]
    sent = 0
    for r in rows:
        if is_weekend and (r.get('days') or 'daily') == 'weekday':
            continue          # '평일만' 선택자는 주말에 즉시 발송도 하지 않는다
        try:
            resp = requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': r['chat_id'], 'text': body, 'parse_mode': 'HTML',
                      'disable_web_page_preview': True},
                timeout=15)
            if resp.status_code != 200:
                print(f'  [긴급 즉시] {r["chat_id"]} 발송 실패 HTTP {resp.status_code}')
                continue
            # 발송분은 정시 발송에서 제외 — 실패 시엔 갱신하지 않아 정시에 정상 수신된다
            sb.table('telegram_subscribers').update(
                {'last_urgent_sent_at': now_iso}).eq('chat_id', r['chat_id']).execute()
            sent += 1
        except Exception as e:
            print(f'  [긴급 즉시] {r.get("chat_id")} 예외(무시): {e}')
    if sent:
        print(f'[긴급 즉시] {sent}명에게 즉시 발송 (정시 재발송 제외 처리 완료)')
    return sent


def format_urgent_html(urgent_items: list) -> str:
    """긴급 기사 목록 → 구독자용 HTML

    브리핑과 같은 규칙: 별도 링크 줄을 두지 않고 기사 제목 자체를 하이퍼링크로 만든다.
    """
    lines = [f'🚨 <b>긴급 전파정책 뉴스 {len(urgent_items)}건</b>\n']
    for i, item in enumerate(urgent_items, 1):
        rel = item.get('_related', 0)
        rel_txt = f' <i>(관련 보도 {rel}건)</i>' if rel else ''
        title, url = esc(item.get('title', '')), esc(item.get('url', ''))
        head = f'<a href="{url}">{title}</a>' if url else f'<b>{title}</b>'
        lines.append(f'{i}. {head}{rel_txt}')
        lines.append(f'   <i>{esc(item.get("source", ""))}</i>\n')
    return '\n'.join(lines)
