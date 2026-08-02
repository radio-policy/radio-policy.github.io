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

DASHBOARD_URL = 'https://youjinwoong.github.io/radio-policy-ai/'

_VALID_TOPICS = ('urgent', 'assembly')


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
        _trigger_delivery()   # 다음 정시(:25)를 기다리지 않고 바로 배달 시도
    return True


def _trigger_delivery() -> bool:
    """send-subscriber-briefing을 즉시 1회 호출해 큐를 바로 배달시킨다.

    발송 함수 자체가 '구독자의 수신 시각이 지났는가'를 검사하므로, 심야에 호출돼도
    아무에게도 보내지 않는다 — 심야 무발송 원칙은 그대로 유지되고 낮 시간대 지연만 줄어든다.
    매시 :25 정시 실행은 그대로 두어(이 호출이 실패해도) 배달이 누락되지 않는다. fail-open.
    """
    url, secret = os.environ.get('SUPABASE_URL', ''), os.environ.get('CRON_SECRET', '')
    if not url or not secret:
        return False
    try:
        import requests
        resp = requests.post(f'{url}/functions/v1/send-subscriber-briefing',
                             headers={'x-cron-secret': secret}, timeout=30)
        if resp.status_code == 200:
            print(f'[구독자 배달] 즉시 배달 호출 완료 — {resp.text[:120]}')
            return True
        print(f'[구독자 배달] 호출 실패 HTTP {resp.status_code} (정시 :25에 재시도됨)')
    except Exception as e:
        print(f'[구독자 배달] 호출 예외(무시): {e}')
    return False


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
