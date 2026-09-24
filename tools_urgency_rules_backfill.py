"""긴급도 낱말 규칙 과거 기사 재적용 (#216, 운영자 결정 D5) — AI 0회.

최근 N일(수집일 created_at 기준, 기본 60일) news_feed에 공통 규칙(표 urgency_rules, 없으면 비상 사본)을
제목 + summary로 돌린다.
  ① urgency_rule이 비어 있고 적중 → urgency_rule 기록(값이 안 바뀌어도 — 출처 표시·사내 정본)
  ② 적중 규칙 등급 > 현재 등급(min 하한·set 지정) 이고 importance_feedback(사람 수정)에 없고
     오늘(KST) 수집 행이 아니면 → urgency·importance를 규칙 값으로
기존 행 UPDATE는 알림을 만들지 않는다(#161-보론5) — 크롤러는 그 실행의 신규분만 알린다.

  py -3.12 tools_urgency_rules_backfill.py                 # 드라이런(기본): 규칙별 적중·변경 건수 + 변경 목록
  py -3.12 tools_urgency_rules_backfill.py --apply         # 실제 UPDATE
  py -3.12 tools_urgency_rules_backfill.py --since 2026-08-25 --until 2026-09-25 --fallback   # 규칙 삽입 전 실측
"""
import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from sb_client import make_client
import urgency_rules as ur

KST = timezone(timedelta(hours=9))
PAGE = 1000


def load_rules(sb, use_fallback):
    if use_fallback:
        return ur.URGENCY_RULES_FALLBACK, 'fallback'
    rows = sb.table('urgency_rules').select('*').is_('team_id', 'null').eq('enabled', True) \
        .order('position').order('id').execute().data or []
    errs = ur.validate_rules(rows)
    if errs or not rows:
        print('[규칙] 표 형식 오류·0건 — 중단:', errs[:5])
        sys.exit(1)
    return rows, 'db'


def fetch_news(sb, since_iso, until_iso, with_rule=True):
    cols = 'id,title,summary,urgency,importance,created_at' + (',urgency_rule' if with_rule else '')
    out, start = [], 0
    while True:
        q = sb.table('news_feed').select(cols) \
            .gte('created_at', since_iso)
        if until_iso:
            q = q.lt('created_at', until_iso)
        rows = q.order('created_at').order('id').range(start, start + PAGE - 1).execute().data or []
        out.extend(rows)
        if len(rows) < PAGE:
            return out
        start += PAGE


def fetch_feedback_ids(sb):
    ids, start = set(), 0
    while True:
        rows = sb.table('importance_feedback').select('news_id').order('id') \
            .range(start, start + PAGE - 1).execute().data or []
        ids.update(r['news_id'] for r in rows if r.get('news_id'))
        if len(rows) < PAGE:
            return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='실제 UPDATE (없으면 드라이런)')
    ap.add_argument('--days', type=int, default=60)
    ap.add_argument('--since', help='YYYY-MM-DD (KST, created_at) — --days 대신')
    ap.add_argument('--until', help='YYYY-MM-DD (KST, 이 날 제외)')
    ap.add_argument('--fallback', action='store_true', help='표 대신 코드의 비상 사본 규칙으로 측정')
    ap.add_argument('--list', type=int, default=40, help='변경 목록 출력 건수')
    a = ap.parse_args()
    if a.apply and a.fallback:
        sys.exit('--apply는 표 규칙으로만 실행한다(--fallback과 함께 쓰지 말 것)')

    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    rules, src = load_rules(sb, a.fallback)
    print(f'[규칙] {len(rules)}개 로드({src}): ' + ', '.join(r['id'] for r in rules))

    now_kst = datetime.now(KST)
    today_kst = now_kst.date()
    since = datetime.fromisoformat(a.since).replace(tzinfo=KST) if a.since \
        else now_kst - timedelta(days=a.days)
    until = datetime.fromisoformat(a.until).replace(tzinfo=KST) if a.until else None
    news = fetch_news(sb, since.isoformat(), until.isoformat() if until else None, with_rule=not a.fallback)
    fb = fetch_feedback_ids(sb)
    print(f'[대상] {len(news)}건 ({since.date()} ~ {until.date() if until else "지금"}), 사람 수정 {len(fb)}건')

    hits, raised, trans = Counter(), Counter(), Counter()
    rule_only, upgrades, skipped = [], [], Counter()
    for n in news:
        cur = n.get('urgency') or '참고'
        hit = ur.match_urgency_rules(rules, n.get('title') or '', n.get('summary') or '')
        if not hit:
            continue
        hits[hit['id']] += 1
        level, rid, changed = ur.combine(hit, cur)
        upd = {}
        if not n.get('urgency_rule'):
            upd['urgency_rule'] = rid
        if changed:
            created_kst = datetime.fromisoformat(n['created_at']).astimezone(KST).date()
            if n['id'] in fb:
                skipped['사람 수정'] += 1
            elif created_kst == today_kst:
                skipped['오늘 수집'] += 1
            elif ur._RANK[level] < ur._RANK.get(cur, 0):
                skipped['set 하향(1단계 소급 제외)'] += 1
            else:
                upd['urgency'] = upd['importance'] = level
                raised[rid] += 1
                trans[f'{cur}→{level}'] += 1
                upgrades.append((n, cur, level, rid))
        if upd and 'urgency' not in upd:
            rule_only.append((n, upd))
        elif upd:
            n['_upd'] = upd

    print('\n규칙별 적중 / 값 변경')
    for r in rules:
        print(f"  {r['id']:<22} 적중 {hits[r['id']]:>4}  변경 {raised[r['id']]:>3}")
    print(f'  합계 적중 {sum(hits.values())}, 값 변경 {sum(raised.values())} {dict(trans)}, 변경 제외 {dict(skipped)}')
    print(f'  urgency_rule만 기록 {len(rule_only)}건')
    print(f'\n값 변경 목록(앞 {a.list}건)')
    for n, cur, level, rid in upgrades[:a.list]:
        print(f"  {cur}→{level} [{rid}] {n['created_at'][:10]} {(n.get('title') or '')[:70]}")

    if not a.apply:
        print('\n(드라이런 — DB 무변경. 실행은 --apply)')
        return
    done = 0
    for n, upd in rule_only:
        sb.table('news_feed').update(upd).eq('id', n['id']).execute()
        done += 1
    for n, cur, level, rid in upgrades:
        sb.table('news_feed').update(n['_upd']).eq('id', n['id']).execute()
        done += 1
    print(f'\n[적용] {done}행 UPDATE (값 변경 {len(upgrades)}, 기록만 {len(rule_only)}) — 알림 없음')


if __name__ == '__main__':
    main()
