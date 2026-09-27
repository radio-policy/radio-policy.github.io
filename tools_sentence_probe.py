# -*- coding: utf-8 -*-
"""팀 규칙 「AI 확인 조건」 판정 지시문의 방향별 탐침 (Fable 재검토 #251, 2026-09-27) — 실제 Haiku 4.5 호출, DB 쓰기 없음.

실측 58건(설계안 §10-2)은 부정 방향(문제 제기) 규칙 하나뿐이라 지시문 규칙 2('성격')가 긍정 방향·발표 방향·주제만 조건에도
맞는지 재지 못했다. tests/fixtures/sentence_rubric_probe.json의 합성 기사 20건(조건 문장 5개)을 crawler._judge_sentence_batch
(운영과 같은 지시문·도구·모델·묶음)로 판정해 expect와 대조한다. expect null = 경계(오답으로 세지 않고 흔들림만 본다).

  py -3.12 tools_sentence_probe.py --dry-run              # 사례 목록·묶음 수·어림 비용만(API 0회)
  py -3.12 tools_sentence_probe.py --allow-api            # 실제 판정 1회(≈$0.02) — 운영자 고지 뒤
  py -3.12 tools_sentence_probe.py --allow-api --repeat 3 # 같은 입력을 3번 — 흔들림(같은 사례의 답이 갈림) 확인

읽는 법: '확실' 사례의 불일치가 0이고 흔들림이 0이면 지시문 유지. 긍정·발표 방향(P1·P2·P6·A2·N1처럼 성격이 섞인 사례)에서
불일치가 나오면 지시문 규칙 2에 긍정 방향 예시 한 쌍과 「성격이 섞이면 중심 성격으로」 한 줄을 더하고, 58건 실측을 다시 잰다
(지시문은 tests/test_crawler_sentence.py test_rubric_and_tool_verbatim이 글자 그대로 잠근다 — 둘을 함께 고친다).
세션에서 돌릴 때는 HTTP(S)_PROXY를 비운다. api_usage에는 site 'crawler.py:_judge_sentence_batch'로 기록된다(운영 판정과 같은 라벨).
"""
import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(ROOT, 'tests', 'fixtures', 'sentence_rubric_probe.json')


def main() -> int:
    ap = argparse.ArgumentParser(description='AI 확인 조건 지시문 방향별 탐침(Fable 재검토 #251)')
    ap.add_argument('--dry-run', action='store_true', help='사례·묶음·어림 비용만(API 0회)')
    ap.add_argument('--allow-api', action='store_true', help='실제 Haiku 판정(비용 발생, 운영자 고지 뒤)')
    ap.add_argument('--repeat', type=int, default=1, help='같은 입력을 몇 번 판정할지(흔들림 확인, 기본 1)')
    ap.add_argument('--set', default='', help='한 조건 묶음만(id: P·N·A·T·G)')
    a = ap.parse_args()
    with open(FIXTURE, encoding='utf-8') as f:
        probe = json.load(f)
    sets = [s for s in probe['sets'] if not a.set or s['id'] == a.set]
    n_cases = sum(len(s['cases']) for s in sets)
    print(f'조건 묶음 {len(sets)}개 · 사례 {n_cases}건 · 호출 {len(sets)}회/반복 (기사당 ≈$0.0013 → 반복당 ≈${n_cases * 0.0013:.3f})')
    if a.dry_run or not a.allow_api:
        for s in sets:
            print(f"\n[{s['id']}] {s['direction']} — «{s['sentence']}»")
            for c in s['cases']:
                exp = '경계' if c['expect'] is None else ('해당' if c['expect'] else '아님')
                print(f"  {c['id']:<3} 기대 {exp:<3} {c['title'][:44]}  ({c.get('note', '')})")
        if not a.dry_run:
            print('\n실제 판정은 --allow-api 로(비용 발생). 지금은 목록만 보였다.')
        return 0

    import crawler                                    # .env·api_usage.install() — 운영과 같은 지시문·도구·모델
    client = crawler._sentence_client()
    if client is None:
        print('오류: ANTHROPIC_API_KEY 없음(.env)')
        return 2
    wrong, waver, cost, n_calls = [], [], 0.0, 0
    answers = {}                                      # 사례 id → [(match, why)…] 반복별
    for rep in range(1, a.repeat + 1):
        for s in sets:
            rows = [{'title': c['title'], 'snippet': c.get('snippet', ''), 'body': c.get('body', '')} for c in s['cases']]
            got, call_cost = crawler._judge_sentence_batch(client, s['sentence'], rows)
            cost += call_cost
            n_calls += 1
            if got is None:
                print(f"[{s['id']}] 반복 {rep}: 호출 실패 — 이 묶음은 건너뜀")
                continue
            for k, c in enumerate(s['cases'], 1):
                v = got.get(k)
                answers.setdefault(c['id'], []).append(v)
    print(f'\n호출 {n_calls}회 · 비용 ${cost:.4f}')
    for s in sets:
        print(f"\n[{s['id']}] {s['direction']} — «{s['sentence']}»")
        for c in s['cases']:
            outs = answers.get(c['id'], [])
            marks = ['?' if v is None else ('해당' if v[0] else '아님') for v in outs]
            if len({m for m in marks}) > 1:
                waver.append(c['id'])
            exp = c['expect']
            bad = exp is not None and any(v is not None and v[0] != exp for v in outs)
            if bad:
                wrong.append(c['id'])
            why = next((v[1] for v in outs if v), '')
            tag = '경계' if exp is None else ('해당' if exp else '아님')
            print(f"  {'✗' if bad else ' '} {c['id']:<3} 기대 {tag:<3} 답 {'/'.join(marks):<12} {c['title'][:40]}  — {why}")
    print(f'\n확실 사례 불일치 {len(wrong)}건 {wrong} · 흔들림 {len(waver)}건 {waver}')
    if wrong:
        print('→ 긍정·발표 방향 불일치면 지시문 규칙 2 보강(긍정 방향 예시 한 쌍 + 「성격이 섞이면 중심 성격으로」) 뒤 58건 실측 재측정.')
    return 1 if wrong else 0


if __name__ == '__main__':
    sys.exit(main())
