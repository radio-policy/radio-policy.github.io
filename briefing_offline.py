# -*- coding: utf-8 -*-
"""모닝 브리핑 오프라인(세션) 재생성 — Anthropic API 0회 (#161-보론6).

회의록 오프라인 파이프라인(minutes_offline.py, #120)과 같은 방식이다. 스크립트는 재료를
모으고 결과를 넣기만 하며, 브리핑 본문은 세션이 직접 쓴다. 과거 브리핑 재생성은 일회성
작업이라 API(Sonnet+Haiku)를 쓰지 않는다 — 세션은 구독에 포함되어 비용이 0이고, 모델도
더 크다.

  python briefing_offline.py --export --since 2026-07-16 --until 2026-09-12 --out DIR
      → DIR/2026-07-16.json … 하루당 한 파일(그날 24h 창의 클러스터 + 프롬프트 규칙)
      → 세션이 DIR/2026-07-16.out.json 을 {"content": "..."} 형태로 작성한다
  python briefing_offline.py --import --in DIR [--apply]
      → 작성된 본문을 daily_briefings에 반영(미리보기가 기본, --apply로 실제 반영)

**발송하지 않는다.** daily_briefings의 content만 바꾼다. 구독자 발송 함수는 '오늘' 날짜
행만 읽고 구독자별 last_briefing_sent_date로 1일 1회를 막으므로, 과거 날짜 내용을 고쳐도
아무에게도 다시 나가지 않는다. 그래도 안전하게 **오늘 날짜는 대상에서 제외**한다.
"""
import os
import re
import sys
import json
import glob
import argparse
from datetime import datetime, timedelta

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
    os.environ.pop(_k, None)

from dotenv import load_dotenv
load_dotenv()
import morning_briefing as mb


# ── 발송 봉인 ──────────────────────────────────────────────
# 운영자 지시(2026-09-13): "절대 이용자에게 새로 한 데일리브리핑이나 긴급도 바뀐 뉴스를
# 내보내지 말라". morning_briefing 모듈에는 발송 함수가 들어 있으므로, 이 파일에서 import한
# 순간 실수로라도 불릴 수 없게 막는다. 제거하지 말 것.
def _sealed(*_a, **_k):
    raise RuntimeError('briefing_offline은 발송하지 않는다 — 발송 함수 호출이 봉인돼 있다')


for _fn in ('send_telegram', 'send_email', 'send_urgent_email', 'main'):
    if hasattr(mb, _fn):
        setattr(mb, _fn, _sealed)

sb = mb.sb
KST = mb.KST


def split_law_section(content: str):
    """원본에서 브리핑 본문 앞에 붙은 섹션(국회 법안 동향·입법예고)을 분리한다."""
    m = re.search(r'📡[^\n]*모닝 브리핑', content or '')
    idx = m.start() if m else -1
    if idx > 0:
        return content[:idx].rstrip() + '\n\n', content[idx:]
    return '', (content or '')


def fetch_day_items(day: datetime) -> list:
    """그날 브리핑이 봤을 24h 창(전날 06:00 ~ 당일 06:00 KST)의 본문 있는 기사."""
    end = day.replace(hour=6, minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=24)
    resp = sb.table('news_feed') \
        .select('id,title,source,url,published_at,content,urgency') \
        .gte('published_at', start.isoformat()).lt('published_at', end.isoformat()) \
        .not_.is_('content', 'null') \
        .order('published_at', desc=True).limit(500).execute()
    return [it for it in (resp.data or []) if it.get('content') and len(it['content'].strip()) > 50]


def day_terms(day: datetime) -> list:
    """그날 새로 추출된 기술 용어 — 원본 브리핑에서는 시간대 버그로 늘 비어 있었다(#161)."""
    end = day.replace(hour=6, minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=24)
    try:
        r = sb.table('tech_terms').select('term,definition') \
            .gte('created_at', start.isoformat()).lt('created_at', end.isoformat()).execute()
        return r.data or []
    except Exception:
        return []


def export(since: str, until: str, out: str):
    os.makedirs(out, exist_ok=True)
    today = datetime.now(KST).strftime('%Y-%m-%d')
    rows = sb.table('daily_briefings').select('briefing_date,content,news_count') \
        .gte('briefing_date', since).lte('briefing_date', until) \
        .order('briefing_date').execute().data or []
    made = 0
    for row in rows:
        d = row['briefing_date']
        if d >= today:
            print(f'{d}: 오늘 이후 — 건너뜀(발송 경로 보호)')
            continue
        day = datetime.strptime(d, '%Y-%m-%d').replace(tzinfo=KST)
        items = fetch_day_items(day)
        if not items:
            print(f'{d}: 본문 기사 0건(보관기간 초과) — 건너뜀')
            continue
        reps = mb.cluster_briefing_items(items, for_date=day)
        picked = mb.select_for_prompt(reps)
        lines = []
        for it in picked:
            icon = {'긴급': '🔴', '보통': '🟡', '참고': '🟢'}.get(it.get('urgency') or '참고', '🟢')
            rel = it.get('_related', 0)
            tags = (f' (관련 보도 {rel + 1}건)' if rel else '') + (' 〔전일 기보도 이어짐〕' if it.get('_prev') else '')
            lines.append({
                'id': it['id'], 'icon': icon, 'title': it['title'] + tags,
                'source': it.get('source', ''), 'url': it.get('url', ''),
                'date': str(it.get('published_at', ''))[:10],
                'body': (it.get('content') or '').replace('\n', ' ').strip()[:400],
            })
        law_part, body = split_law_section(row.get('content') or '')
        payload = {
            'briefing_date': d,
            'system': mb._BRIEFING_SYSTEM,
            'impact_system': mb._IMPACT_SYSTEM,
            'articles_24h': len(items), 'clusters': len(reps), 'given': len(picked),
            'prefix_keep': law_part,
            'terms': day_terms(day),
            'news': lines,
            'original_len': len(row.get('content') or ''),
        }
        with open(os.path.join(out, f'{d}.json'), 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        made += 1
        print(f'{d}: 기사 {len(items)} → 묶음 {len(reps)} → 제공 {len(picked)} · 용어 {len(payload["terms"])}건')
    print(f'\n내보내기 {made}일치 → {out}')


def do_import(indir: str, apply: bool):
    files = sorted(glob.glob(os.path.join(indir, '*.out.json')))
    if not files:
        print('작성된 *.out.json 없음')
        return
    today = datetime.now(KST).strftime('%Y-%m-%d')
    done = 0
    for f in files:
        d = os.path.basename(f).replace('.out.json', '')
        if d >= today:
            print(f'{d}: 오늘 이후 — 건너뜀')
            continue
        data = json.load(open(f, encoding='utf-8'))
        text = (data.get('content') or '').strip()
        if len(text) < 300 or '📡' not in text:
            print(f'{d}: 본문이 짧거나 형식 불일치 — 건너뜀 ({len(text)}자)')
            continue
        src = json.load(open(os.path.join(indir, f'{d}.json'), encoding='utf-8'))
        final = (src.get('prefix_keep') or '') + text
        # 이중 안전장치 — 오늘·미래 날짜는 위에서 걸렀지만, 구독자 발송 상태로 한 번 더 확인한다.
        # 발송 함수는 '오늘' 행만 읽으므로 과거 날짜는 어떤 경우에도 재발송되지 않는다.
        try:
            subs = sb.table('telegram_subscribers').select('last_briefing_sent_date')                 .eq('active', True).eq('topic_briefing', True).execute().data or []
            if any(str(x.get('last_briefing_sent_date')) == d for x in subs):
                print(f'{d}: 구독자 발송 기록이 이 날짜에 걸려 있음 — 안전을 위해 건너뜀')
                continue
        except Exception as e:
            print(f'{d}: 구독자 상태 확인 실패 — 안전을 위해 건너뜀 ({str(e)[:50]})')
            continue
        cur = sb.table('daily_briefings').select('content,news_count').eq('briefing_date', d).limit(1).execute().data
        if not cur:
            print(f'{d}: 기존 행 없음 — 건너뜀')
            continue
        # 퇴행 방지 — 뉴스는 60일 롤링으로 지워지므로, 보존 경계에 걸친 날은 그날 기사의
        # 상당수가 이미 사라져 있다. 그 상태로 다시 쓰면 원본보다 얇은 브리핑으로 덮어써서
        # 기록이 나빠진다(실측 2026-08-30: 원본 92건 → 남은 41건). 원본이 본 기사 수의
        # 60% 미만만 남아 있으면 건너뛴다.
        prev_n = cur[0].get('news_count') or 0
        now_n = src.get('articles_24h') or 0
        if prev_n and now_n < prev_n * 0.6:
            print(f'{d}: 원본 기사 {prev_n}건 중 {now_n}건만 남음 — 퇴행 방지로 건너뜀')
            continue
        prev_items = len(re.findall(r'\[ID:', cur[0]['content'] or ''))
        new_items = len(re.findall(r'\[ID:', text))
        if prev_items and new_items < prev_items:
            print(f'{d}: 항목이 {prev_items} → {new_items}건으로 줄어 건너뜀(퇴행 방지)')
            continue
        print(f'{d}: {len(cur[0]["content"] or "")}자 → {len(final)}자' + ('' if apply else '  [미리보기]'))
        if apply:
            sb.table('daily_briefings').update({
                'content': final, 'news_count': src.get('articles_24h'),
                'terms_count': len(src.get('terms') or []),
            }).eq('briefing_date', d).execute()
        done += 1
    print(f'\n{"반영" if apply else "미리보기"} {done}일치 — 발송 없음(daily_briefings UPDATE만)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--export', action='store_true')
    ap.add_argument('--import', dest='imp', action='store_true')
    ap.add_argument('--since')
    ap.add_argument('--until')
    ap.add_argument('--out')
    ap.add_argument('--in', dest='indir')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    if a.export:
        export(a.since, a.until, a.out)
    elif a.imp:
        do_import(a.indir, a.apply)
    else:
        ap.print_help()


if __name__ == '__main__':
    main()
