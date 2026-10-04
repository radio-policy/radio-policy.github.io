# -*- coding: utf-8 -*-
"""
팀 채점 세트 미리 보기(#277) — 크롤러 build_grading_sets와 **같은 함수**(crawler.compose_grading_set)로 그 팀의 20건을 골라
갈래·몫·공통 긴급 수를 보여 준다. **DB에 쓰지 않는다**(세트·항목·시험·큐 행 0).

  py -3.12 tools_grading_probe.py --team 2                 # dry-run(AI 0) — 세트 구성표
  py -3.12 tools_grading_probe.py --team 2 --seed 11       # 같은 seed = 같은 세트
  py -3.12 tools_grading_probe.py --team 2 --noise --allow-api
      # noise 시험을 메모리에서만: 그 팀의 지금 문장 규칙마다 세트 기사 중 낱말이 걸린 것을 운영과 같은 함수
      # (_sentence_input → _judge_jobs → _judge_sentence_batch, 한 묶음 = 한 호출)로 다시 판정해 저장 판정과 대조.
      # 규칙당 ≈$0.01~0.03(Haiku, api_usage 라벨 crawler.py:_judge_sentence_batch). 결과는 화면에만.

수동 실행 전 세션 셸의 HTTP(S)_PROXY를 지울 것(지침 — 사내 프록시가 SSL을 깬다). Python은 py -3.12.
"""
import argparse
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
    os.environ.pop(_k, None)

import crawler  # noqa: E402
import urgency_rules  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description='팀 채점 세트 미리 보기(쓰기 0)')
    ap.add_argument('--team', type=int, required=True, help='teams.id (기술정책팀 = 2)')
    ap.add_argument('--seed', type=int, default=20261004)
    ap.add_argument('--noise', action='store_true', help='noise 시험을 메모리에서 — API 호출(--allow-api 필요)')
    ap.add_argument('--allow-api', action='store_true')
    a = ap.parse_args()
    if a.noise and not a.allow_api:
        print('--noise는 Haiku를 부른다 — --allow-api를 함께 줄 것(규칙당 ≈$0.01~0.03)')
        return 2
    res = crawler.compose_grading_set(a.team, a.seed)
    print(f"[세트 미리 보기] 팀 {a.team} · seed {a.seed} → {res['status']} · {res.get('note', '')}")
    if res['status'] not in ('open', 'too_small'):
        return 1
    pick = res['pick']
    items = sorted(pick['items'], key=lambda c: c['seq'])
    tune = sum(1 for c in items if c['slot'] == 'tune')
    print(f"  {len(items)}건(고칠 몫 {tune} · 확인용 {len(items) - tune}) · 공통 긴급 {pick['common_urgent']} · "
          f"풀 {res['pool']} · 판정 대기 제외 {res['waiting']} · 풀 얇음 {pick['pool_thin']}")
    print('  seq 몫    갈래            공통 팀   출처    규칙(문장)           제목')
    for c in items:
        rule = (c.get('rule_id') or '-') + ('(문장)' if c.get('rule_sentence') else '')
        print(f"  {c['seq']:>3} {c['slot']:<5} {c['kind']:<15} {c['common']:<3} {c['team_level']:<3} "
              f"{c['team_source']:<6} {rule:<20} {(c.get('title') or '')[:46]}")
    if not a.noise:
        return 0
    cands = crawler._noise_candidates(res['rules'], items)
    if not cands:
        print('[noise] 세트 기사에 낱말이 걸리는 문장 규칙 없음 — 호출 0')
        return 0
    news = crawler._fetch_news([c['id'] for c in items], crawler._NEWS_JUDGE_COLS)
    client = crawler._sentence_client()
    if client is None:
        return 1
    t0 = time.monotonic()
    tv, cost = [], 0.0
    for idx, cand in enumerate(cands):
        rule = dict(cand, id=cand['rule_id'])
        hits = [c['id'] for c in items if urgency_rules.match_urgency_rules(
            [rule], c.get('title') or '', c.get('text') or '')]
        inputs = [dict(crawler._sentence_input(news[n]), news_id=n) for n in hits if n in news]
        res_j = crawler._judge_jobs(client, cand['sentence'].strip(), inputs, t0)
        for j, r in zip(inputs, res_j):
            if r is None or r[0] is None:
                print(f"  [noise] {cand['rule_id']} {j['news_id']} 판정 없음")
                continue
            tv.append({'cand_idx': idx, 'news_id': j['news_id'], 'verdict': r[0], 'why': r[1]})
            cost += r[2]
        print(f"[noise] {cand['rule_id']}(판 {cand['sentence_rev']}) 세트 기사 {len(inputs)}건 한 묶음 판정")
    mism, comp = crawler._noise_compare({'candidates': cands}, tv)
    print(f'[noise] AI 흔들림 {len(mism)}/{len(comp)}건(저장 판정과 대조한 기사) · 비용 ≈${cost:.4f}')
    title = {c['id']: c.get('title') or '' for c in items}
    for v in tv:
        mark = '≠' if v['news_id'] in mism else ('=' if v['news_id'] in comp else '?')
        print(f"  {mark} {cands[v['cand_idx']]['rule_id']} {'참' if v['verdict'] else '거짓'} · {title[v['news_id']][:40]} · {v['why']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
