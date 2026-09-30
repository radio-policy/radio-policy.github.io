# -*- coding: utf-8 -*-
"""긴급 억제 ①-2 「재보도 대조」 지시문 실측 (#263, 2026-09-30) — 실제 Haiku 4.5 호출, DB 쓰기 없음(api_usage 기록 제외).

tests/fixtures/dedup_match_cases.json(2026-09-13~09-30 실제 크롤 실행 173회 · 새 기사 267건 · Fable 정답표)을 운영 함수
news_dedup.match_prior_reports(운영과 같은 지시문·도구·모델·온도 0)로 다시 판정시켜 정답과 대조한다.
대조는 **결과 단위**다 — 판정기의 답을 「알림 / 리마인드 / 억제」로 바꿔 본다(같은 소식으로 본 대표가 24시간 안이면 억제,
넘었으면 리마인드. ①이 이미 리마인드로 정했던 기사는 답이 없으면 리마인드 그대로). 리마인드 문턱(#256)은 계산하지 않는다.

  py -3.12 tools_dedup_probe.py --dry-run                    # 사례 수·호출 수·어림 비용만(API 0회)
  py -3.12 tools_dedup_probe.py --allow-api                  # 전체 173회 1번(≈$1.0) — 운영자 고지 뒤
  py -3.12 tools_dedup_probe.py --allow-api --only 251,6     # 그 번호(no)의 기사가 든 실행만
  py -3.12 tools_dedup_probe.py --allow-api --repeat 2       # 같은 입력을 2번 — 흔들림(답이 갈린 기사) 확인
  py -3.12 tools_dedup_probe.py --allow-api --save out.jsonl # 실행별 답·판정기가 적은 계기를 파일로

기준선(2026-09-30, 전체 1회 174호출 $1.01, 호출 실패 0 — 배경역사 #263):
  새 소식인데 억제 2건(no 151 같은 통계의 반박 기사 — 애매 / no 225 연속 기획 〈하〉) · 재보도인데 알림 3건(no 95·224·267) ·
  재보도 26/29 묶음 · 그때 오묶음 43건 중 42건 통과 · 결과 합 알림 211·리마인드 28·억제 28(그때 실제: 알림 130·묶임 32·리마인드 22·억제 83).
읽는 법:
  · 「새 소식인데 억제」가 핵심 지표다 — 알림이 사라지는 쪽이라 되돌릴 수 없다. 기준선보다 늘면 지시문을 되돌린다.
  · 「재보도인데 알림」은 중복 알림 한 통의 비용이다 — 늘어도 억제 오류보다 가볍다.
  · 온도 0이어도 드물게 답이 갈린다(44건 중 1건) — 한두 건 차이는 흔들림으로 본다. --repeat로 확인.
  · 지시문·도구는 tests/test_dedup_match.py가 글자 그대로 잠근다 — 고치려면 이 도구로 다시 재고 둘을 함께 고친다.
세션에서 돌릴 때는 HTTP(S)_PROXY를 비운다. api_usage에는 site 'news_dedup.py:match_prior_reports'로 기록된다(운영 판정과 같은 라벨).
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(ROOT, 'tests', 'fixtures', 'dedup_match_cases.json')
REMIND_AFTER_H = 24
BAD = ('F', 'T', 'C', 'X')          # 그때(옛 ①-2) 오묶음으로 판정된 기사 — 새 소식


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace('Z', '+00:00'))


def outcome(run_t: str, new_row: dict, ans_id, arts: dict) -> str:
    """판정기의 답(대표 id | None) → '알림' | '리마인드' | '억제'."""
    base = '리마인드' if str(new_row.get('actual') or '').startswith('REMIND1') else '알림'
    if ans_id is None:
        return base
    age_h = (_ts(run_t) - _ts(arts[ans_id]['at'])).total_seconds() / 3600
    return '억제' if age_h < REMIND_AFTER_H else '리마인드'


def classify(new_row: dict, ans_id, out: str) -> str:
    """결과 한 건의 분류(보고 줄)."""
    g, tg, cls = new_row['gtype'], new_row.get('targets') or [], new_row.get('cls')
    if g == 'hard':
        if ans_id is None:
            return '재보도인데 알림(중복)'
        return '재보도 — 묶음' if ans_id in tg else '재보도 — 다른 대표와 묶음'
    if g in ('soft', 'zero+'):
        if out == '억제' and ans_id not in tg:
            return '재정리·경계 — 범위 밖 억제(검토)'
        return f'재정리·경계 — {out}'
    if out == '억제':
        return '새 소식인데 억제' + ('(그때 오묶음 사례)' if cls in BAD else '')
    if cls in BAD:
        return f'그때 오묶음 사례 — {out}'
    return f'새 소식 — {out}'


def main() -> int:
    ap = argparse.ArgumentParser(description='재보도 대조 지시문 실측(#263)')
    ap.add_argument('--dry-run', action='store_true', help='사례·호출 수·어림 비용만(API 0회)')
    ap.add_argument('--allow-api', action='store_true', help='실제 Haiku 판정(비용 발생, 운영자 고지 뒤)')
    ap.add_argument('--repeat', type=int, default=1, help='같은 입력을 몇 번 판정할지(흔들림 확인, 기본 1)')
    ap.add_argument('--only', default='', help='쉼표로 구분한 기사 번호(no) — 그 기사가 든 실행만')
    ap.add_argument('--after', default='', help='이 시각(ISO)부터의 실행만')
    ap.add_argument('--save', default='', help='실행별 답·계기를 jsonl로 저장')
    a = ap.parse_args()
    with open(FIXTURE, encoding='utf-8') as f:
        fx = json.load(f)
    arts, runs = fx['articles'], [r for r in fx['runs'] if r['cand']]
    if a.only:
        want = {int(x) for x in a.only.split(',') if x.strip()}
        runs = [r for r in runs if any(n['no'] in want for n in r['new'])]
    if a.after:
        runs = [r for r in runs if r['t'] >= a.after]
    n_new = sum(len(r['new']) for r in runs)

    sys.path.insert(0, ROOT)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, '.env'))
    except Exception:
        pass
    import news_dedup                                   # api_usage.install() — 운영과 같은 지시문·도구·모델·온도

    def art(i):
        return {'title': arts[i]['title'], 'event': arts[i]['event'], 'snip': arts[i]['snip']}

    chars = sum(len(news_dedup.build_match_prompt([art(n['id']) for n in r['new']], [art(c) for c in r['cand']])) for r in runs)
    est_in = len(runs) * 1900 + chars * 1.05            # 지시문·도구 ≈ 1.9K 토큰/호출, 한글 ≈ 1자 1토큰(2026-09-30 실측)
    print(f'실행 {len(runs)}회 · 새 기사 {n_new}건 · 반복당 입력 어림 {est_in / 1000:.0f}K 토큰 ≈ ${est_in / 1e6 + len(runs) * 190 * 5 / 1e6:.2f}'
          f' (Haiku 4.5 입력 $1·출력 $5 / 100만 토큰)')
    if a.dry_run or not a.allow_api:
        c = Counter((n['gtype'], n.get('cls')) for r in runs for n in r['new'])
        for k in sorted(c, key=str):
            print(f'   {k[0]:5s} {str(k[1]):4s} {c[k]}')
        if not a.dry_run:
            print('\n실제 판정은 --allow-api 로(비용 발생). 지금은 구성만 보였다.')
        return 0

    key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not key:
        print('오류: ANTHROPIC_API_KEY 없음(.env)')
        return 2
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        os.environ.pop(k, None)
    answers = {}                                        # 기사 no → [반복별 대표 id | None | 'FAIL']
    saved = []
    for rep in range(1, a.repeat + 1):
        tally, detail, failed = Counter(), [], 0
        for r in runs:
            new, cand = [art(n['id']) for n in r['new']], [art(c) for c in r['cand']]
            trace = []
            got = news_dedup.match_prior_reports(new, cand, key, trace=trace)
            if got is None:
                failed += 1
            for k, n in enumerate(r['new']):
                ans = None if got is None or got[k] is None else r['cand'][got[k]]
                answers.setdefault(n['no'], []).append('FAIL' if got is None else ans)
                out = outcome(r['t'], n, ans, arts)
                kind = classify(n, ans, out)
                tally[kind] += 1
                if '억제' in kind and kind.startswith('새 소식') or '(중복)' in kind or '다른 대표' in kind or '범위 밖' in kind:
                    detail.append((n['no'], kind, arts[n['id']]['title'], arts[ans]['title'] if ans else ''))
            if a.save:
                pegs = {}
                for lo, rows in trace:
                    for x in rows:
                        if isinstance(x, dict) and isinstance(x.get('id'), int):
                            pegs[lo + x['id']] = x
                saved.append({'rep': rep, 't': r['t'], 'new': [n['no'] for n in r['new']],
                              'ans': None if got is None else [None if j is None else r['cand'][j] for j in got],
                              'rows': [pegs.get(k + 1) for k in range(len(r['new']))]})
        print(f'\n── 반복 {rep} — 호출 실패 {failed}회 ──')
        for kind in sorted(tally):
            print(f'   {kind}: {tally[kind]}')
        for no, kind, t1, t2 in sorted(detail):
            print(f'     #{no} {kind} :: {t1[:46]}' + (f'  ←  {t2[:40]}' if t2 else ''))
    if a.repeat > 1:
        waver = {no: v for no, v in answers.items() if len(set(map(str, v))) > 1}
        print(f'\n흔들림(반복마다 답이 갈린 기사): {len(waver)}건 / {len(answers)}건')
        for no in sorted(waver):
            print(f'     #{no}: ' + ' | '.join('없음' if x is None else ('실패' if x == 'FAIL' else arts[x]['title'][:24]) for x in waver[no]))
    if a.save:
        with open(a.save, 'w', encoding='utf-8') as f:
            for row in saved:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
        print(f'\n저장: {a.save} ({len(saved)}줄)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
