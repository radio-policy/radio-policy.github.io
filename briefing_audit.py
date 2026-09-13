# -*- coding: utf-8 -*-
"""모닝 브리핑 품질 점검 — 포괄률·중복률·분석·용어를 숫자로 찍는다 (#161).

"빠짐없이 발송됐다"와 "빠짐없이 담겼다"는 다른 말이다. 발송 성공률만 보던 탓에
1주(2026-09-07~13) 동안 브리핑에 언급조차 없는 긴급 사건이 193건이었다.
이 스크립트는 그날 있었던 사건 대비 브리핑이 무엇을 담았는지를 센다.

  python briefing_audit.py                 # 최근 7일
  python briefing_audit.py --days 14
  python briefing_audit.py --since 2026-09-07 --until 2026-09-13 --list 10

AI 호출 0회 · DB 읽기 전용. 주 1회 돌려 결과를 기록해 두면 추세가 보인다.
"""
import os
import re
import sys
import argparse
import datetime
from collections import Counter

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
    os.environ.pop(_k, None)

from dotenv import load_dotenv
load_dotenv()
from sb_client import make_client

sb = make_client(os.environ['SUPABASE_URL'],
                 os.environ.get('SUPABASE_SERVICE_KEY') or os.environ['SUPABASE_KEY'])

ID_RE = re.compile(r'\[ID:([0-9a-f-]{36})\]')
STOP = set('통신 기사 관련 위해 대한 이번 올해 지난 우리 나선다 밝혀 대해 있다 한다 위한 통해 최대 최초 추진 확대 강화 도입 출시'.split())
# 사건 묶음 임계 — 제목 낱말이 이만큼 겹치면 같은 사건으로 본다(news_dedup와 별개의 사후 점검용)
SAME_EVENT = 0.45
# 브리핑 본문이 사건의 핵심 낱말을 이 비율 미만으로 담으면 '미언급'
COVERED = 0.34


def toks(t: str) -> set:
    return {w for w in re.findall(r'[가-힣A-Za-z0-9]{2,}', t or '') if w not in STOP}


def audit_day(date_str: str, content: str, show: int = 5) -> dict:
    day = datetime.date.fromisoformat(date_str)
    lo = (day - datetime.timedelta(days=1)).isoformat() + 'T00:00:00'
    hi = date_str + 'T23:59:59'
    rows = sb.table('news_feed').select('id,title,importance,published_at,source') \
        .gte('published_at', lo).lte('published_at', hi).limit(1000).execute().data or []
    urgent = [r for r in rows if r.get('importance') == '긴급']
    in_brief = set(ID_RE.findall(content))
    missed = [r for r in urgent if r['id'] not in in_brief]

    clusters = []
    for n in missed:
        tk = toks(n['title'])
        for cl in clusters:
            if tk and len(tk & cl['tok']) / max(1, min(len(tk), len(cl['tok']))) >= SAME_EVENT:
                cl['items'].append(n)
                cl['tok'] |= tk
                break
        else:
            clusters.append({'tok': set(tk), 'items': [n]})

    body = toks(content)
    uncovered = []
    for cl in clusters:
        key = Counter()
        for n in cl['items']:
            for w in toks(n['title']):
                key[w] += 1
        core = {w for w, c in key.items() if c >= max(1, len(cl['items']) * 0.6)}
        if core and len(core & body) / len(core) < COVERED:
            uncovered.append((len(cl['items']), cl['items'][0]['title']))
    uncovered.sort(reverse=True)

    slots = len(in_brief)
    prev = len(re.findall(r'전일 기보도 이어짐', content))
    terms = re.search(r'\[저장 결과\][\s\S]*?기술 용어\s*(\d+)\s*건', content)
    analyses = re.findall(r'⚠️ SKT 영향 분석: (.+)', content)
    head = sum(1 for a in analyses if a.startswith('SKT 관점'))
    res = {
        'date': date_str, 'articles': len(rows), 'urgent': len(urgent),
        'slots': slots, 'events_missed': len(uncovered), 'prev': prev,
        'terms': int(terms.group(1)) if terms else 0,
        'analyses': len(analyses), 'analysis_head': head,
        'top_missed': uncovered[:show],
    }
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=7)
    ap.add_argument('--since')
    ap.add_argument('--until')
    ap.add_argument('--list', type=int, default=5, help='날짜별로 보여줄 미언급 사건 수')
    a = ap.parse_args()

    until = a.until or datetime.date.today().isoformat()
    since = a.since or (datetime.date.fromisoformat(until) - datetime.timedelta(days=a.days - 1)).isoformat()
    rows = sb.table('daily_briefings').select('briefing_date,content') \
        .gte('briefing_date', since).lte('briefing_date', until) \
        .order('briefing_date').execute().data or []
    if not rows:
        print(f'[점검] {since}~{until} 브리핑 없음')
        return

    print(f'[모닝 브리핑 점검] {since} ~ {until} · {len(rows)}건\n')
    print(f'{"날짜":<12}{"24h기사":>7}{"긴급":>6}{"수록":>6}{"미언급사건":>10}{"전일재탕":>8}{"용어":>6}{"분석":>6}')
    tot = Counter()
    for r in rows:
        d = audit_day(r['briefing_date'], r['content'] or '', a.list)
        print(f'{d["date"]:<12}{d["articles"]:>7}{d["urgent"]:>6}{d["slots"]:>6}'
              f'{d["events_missed"]:>10}{d["prev"]:>8}{d["terms"]:>6}{d["analyses"]:>6}')
        for k in ('urgent', 'slots', 'events_missed', 'prev', 'terms', 'analyses', 'analysis_head'):
            tot[k] += d[k]
        for cnt, title in d['top_missed']:
            print(f'      └ 미언급({cnt}건) {title[:66]}')
    n = len(rows)
    print(f'\n합계 — 긴급 {tot["urgent"]} · 수록 {tot["slots"]} · 미언급 사건 {tot["events_missed"]}'
          f' · 전일 재탕 {tot["prev"]} · 용어 {tot["terms"]} · 분석 {tot["analyses"]}')
    print(f'하루 평균 — 수록 {tot["slots"]/n:.1f}칸 · 미언급 사건 {tot["events_missed"]/n:.1f} · '
          f'재탕 {tot["prev"]/n:.1f} · 용어 {tot["terms"]/n:.1f}')
    if tot['analysis_head']:
        print(f'⚠️ 분석문 머리말 중복 {tot["analysis_head"]}건 — 프롬프트 점검 필요')
    if tot['terms'] == 0:
        print('⚠️ 기술 용어 0건 — tech_terms 적재 또는 조회 시각 경계 확인')
    if n and tot['events_missed'] / n > 10:
        print('⚠️ 하루 미언급 사건 10건 초과 — 선정 정렬(select_for_prompt)·칸 수 점검')


if __name__ == '__main__':
    main()
