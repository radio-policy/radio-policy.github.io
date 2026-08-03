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
from datetime import datetime, timedelta, timezone

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
    body = html_text[:3500]
    # 최근 10분 내 같은 내용이 이미 큐에 있으면 건너뛴다 — 원인이 무엇이든 중복 발송을 막는 안전망.
    # (2026-08-03: 크롤러를 수동 실행한 시각이 정기 실행 :50과 겹쳐 두 인스턴스가 동시에 돌았다.
    #  각자 시작 시점에 '기존 URL 목록'을 읽었는데 둘 다 저장 전이라 같은 기사를 서로 새 것으로
    #  판단 → 큐에 24초 간격으로 동일 내용 2행 → 각자 _trigger_delivery까지 호출해 2번 발송됐다.
    #  발송 측 병합(mergeQueueBlocks)은 '한 번의 발송 안에서만' 중복을 없애므로 못 막는다.)
    try:
        since = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        dup = (sb.table('subscriber_queue').select('id')
               .eq('topic', topic).eq('html', body)
               .gte('created_at', since).limit(1).execute().data)
        if dup:
            print(f'[구독자 큐] {topic} 중복 적재 생략 — 10분 내 동일 내용 존재(id={dup[0]["id"]})')
            return False
    except Exception as e:
        print(f'[구독자 큐] 중복 확인 실패(계속 진행): {e}')   # 확인 실패가 적재를 막으면 안 된다
    try:
        sb.table('subscriber_queue').insert({'topic': topic, 'html': body}).execute()
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
    # 제목 변경(2026-08-03): '긴급 전파정책 뉴스' → '통신·전파 정책 주요 뉴스'.
    #  ① 수집 범위가 요금·규제·보안·AI까지 넓어져 '전파정책'이 내용을 못 담는다.
    #  ② 대시보드는 같은 등급을 '🔴 중요'로 부르는데 텔레그램만 '긴급'이라 표기가 갈려 있었다.
    #     실제 성격도 '당장 대응'보다 '중요'에 가깝고, 매일 받는 팀원에게 '긴급'은 피로하다.
    # 발송 측 HEADER_COUNT_RE는 (앞부분)(숫자)(건…) 형태라 문구가 바뀌어도 병합이 유지된다.
    lines = [f'📡 <b>통신·전파 정책 주요 뉴스 {len(urgent_items)}건</b>\n']
    for i, item in enumerate(urgent_items, 1):
        rel = item.get('_related', 0)
        rel_txt = f' <i>(관련 보도 {rel}건)</i>' if rel else ''
        title, url = esc(item.get('title', '')), esc(item.get('url', ''))
        head = f'<a href="{url}">{title}</a>' if url else f'<b>{title}</b>'
        lines.append(f'{i}. {head}{rel_txt}')
        lines.append(f'   <i>{esc(item.get("source", ""))}</i>\n')
    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════
#  기사 단위 큐 (2026-08-03) — 구독 관심분야 태그 필터의 전제
# ═══════════════════════════════════════════════════════
#  기존 방식은 "발송 묶음 1건 = 큐 1행"이라 ①기사 식별자가 없고 ②한 행이 서로 다른 태그의
#  기사 N건을 품어서 태그 필터가 원천 불가능했다. → 기사당 1행으로 바꾸고, 태그를 **데이터로**
#  넘긴다. 헤더 건수와 칩은 구독자마다 다르므로 Python이 미리 구우면 안 된다 —
#  send-subscriber-briefing/index.ts 의 renderNewsItems()가 `{i}. {html}` + 🏷 칩 줄을
#  **순수 append**로 조립한다(html을 역파싱하지 않는다).
#
#  이중 경로: 발송 함수는 news_url이 NOT NULL이면 신규 렌더러, NULL이면 기존 mergeQueueBlocks
#  (구버전 묶음 행·법안 알림)로 간다. 그래서 news_url은 **빈 문자열이라도 NULL이면 안 된다.**
#  format_urgent_html/queue_for_subscribers는 롤백 대비 + assembly 경로용으로 존치.


def format_news_item(item) -> str:
    """기사 1건의 HTML — 헤더·번호·칩 **없이** 제목 링크 + (관련 보도 N건) + 출처만.

    format_urgent_html의 항목 조립부와 같은 모양을 유지할 것. 앞의 번호와 뒤의 칩 줄은
    발송 측(Edge)이 붙인다.
    """
    rel = item.get('_related', 0)
    rel_txt = f' <i>(관련 보도 {rel}건)</i>' if rel else ''
    title, url = esc(item.get('title', '')), esc(item.get('url', ''))
    head = f'<a href="{url}">{title}</a>' if url else f'<b>{title}</b>'
    return f'{head}{rel_txt}\n   <i>{esc(item.get("source", ""))}</i>'


def queue_news_items(sb, items: list) -> bool:
    """긴급 기사 목록 → subscriber_queue에 **기사당 1행**으로 한 번에 적재. 반환=성공 여부.

    어떤 예외도 밖으로 던지지 않는다(fail-open) — 큐 적재 실패가 크롤링·운영자 알림을 죽이면 안 된다.
    """
    if not items:
        return False

    # 최근 10분 내 같은 기사(news_url)가 이미 큐에 있으면 그 기사만 제외한다.
    # (queue_for_subscribers의 '10분 내 동일 내용 생략'과 같은 취지 — 크롤러 두 인스턴스가
    #  동시에 돌아 같은 기사를 각자 새 것으로 판단한 사고(2026-08-03) 방어. 묶음이 아니라
    #  기사 단위이므로 **중복분만 빼고 나머지는 넣는다** — 전체를 버리면 새 기사가 유실된다.)
    dup_urls = set()
    try:
        since = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        recent = (sb.table('subscriber_queue').select('news_url')
                  .eq('topic', 'urgent').gte('created_at', since).execute().data) or []
        dup_urls = {r.get('news_url') for r in recent if r.get('news_url')}
    except Exception as e:
        print(f'[구독자 큐] 중복 확인 실패(계속 진행): {e}')   # 확인 실패가 적재를 막으면 안 된다

    rows, skipped, seen = [], 0, set()
    for it in items:
        url = str(it.get('url') or '').strip()
        if url:
            if url in dup_urls or url in seen:
                skipped += 1
                continue
            seen.add(url)
        body = format_news_item(it)
        if not body.strip():
            continue
        tags = it.get('tags')
        if not isinstance(tags, list):
            tags = []
        # ★ 모든 행의 키 집합이 완전히 같아야 한다 ★ — PostgREST 벌크 insert는 객체 하나라도
        #   키가 다르면 전체가 실패한다. news_url은 빈 문자열이라도 NOT NULL(신·구형 판별자).
        rows.append({'topic': 'urgent', 'news_url': url,
                     'tags': [str(t) for t in tags], 'html': body[:3500]})

    if skipped:
        print(f'[구독자 큐] 10분 내 중복 기사 {skipped}건 제외')
    if not rows:
        print('[구독자 큐] 적재할 신규 기사 없음')
        return False

    try:
        sb.table('subscriber_queue').insert(rows).execute()
        print(f'[구독자 큐] urgent {len(rows)}건 기사 단위 적재 완료 — 각 구독자의 수신 시각에 발송됨')
    except Exception as e:
        print(f'[구독자 큐] 적재 실패(무시): {e}')
        return False
    _trigger_delivery()   # 다음 정시(:25)를 기다리지 않고 바로 배달 시도
    return True
