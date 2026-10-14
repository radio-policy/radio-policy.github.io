# -*- coding: utf-8 -*-
"""이슈맵 뉴스 관련 판정 지시문 실측 (10-12 판정 §3, #296 뒤) — 실제 Sonnet 5 호출, DB 쓰기 없음(api_usage 기록 제외).

tests/fixtures/issue_judge_cases.json(10-07~10-12 자동 연결 실행 13회를 묶음째 재구성한 호출 + (라) 추가 표본 1호출 · 정답)을
네 변형으로 다시 판정시켜 정답과 대조한다. 실행 하나 = 운영의 판정 한 호출(그 실행에서 판정에 간 묶음 전부)이다.
  V0  지금 운영 지시문·입력 그대로(issue_suggest._haiku_relate_batch kind='news' — tests/test_issue_judge_probe.py가 글자 대조)
  A1  A′ — 지시문만 「정의문의 해당/해당 없음이 기준」으로 바꿈, 입력은 묶음 모양 그대로(대표 + 같은 묶음 2건)
  B   기사별 — 이슈마다 정의 1회 + 그 실행에서 그 이슈로 간 묶음들의 새 기사(아직 안 붙은 기사) 제목을 번호로, A′ 기준문
  B2  B + 묶음마다 「묶음 대표」 한 줄(맥락 — 판정 대상 아님)
모델·설정은 운영과 같다(claude-sonnet-5, thinking 끔, 온도 없음 — Sonnet 5는 temperature를 거부). max_tokens: V0·A1 400, B·B2 1000.

채점(판정 §3 — 기준은 이 도구가 바꾸지 않는다): 점수는 '새 기사'(그 실행 전엔 그 이슈에 안 붙어 있던 구성원)만, 정답 '경계'는 뺀다.
V0·A1은 묶음 판정을 그 묶음의 새 기사 전부에 적용(운영이 묶음째 붙이므로), B·B2는 기사 번호 그대로.
  P1 오염   #245 '해당 없음' 연결 수 V0 대비 A1 ≤ 1/3, B·B2 ≤ 1/5
  P2 놓침   #245 '해당' 재현율 V0 대비 ≥ 90 %, 사건 통째 잃음(해당이 과반인 묶음에서 해당 0건 연결) 0
  P3 대조군 #46·#119·#2·#13 '해당' 유지 ≥ 95 %(잃은 기사 전수 목록)
  P4 흔들림 같은 입력 2회 불일치 ≤ 5 %
  P5 비용   호출당 토큰(입력+출력) ≤ 1.5 × V0
  (마) 판정에서 떨어진 묶음은 로그가 없어 세트에 없다 — 세트는 '붙은 것' 쪽으로 치우쳐 있다(F 경로 메모 2주 뒤 2차 측정).

  py -3.12 tools_issue_judge_probe.py --dry-run                     # 세트·호출 수·어림 비용(API 0회)
  py -3.12 tools_issue_judge_probe.py --count-tokens                # count_tokens로 정확한 입력 토큰·비용(무료 API, 생성 0)
  py -3.12 tools_issue_judge_probe.py --allow-api --variants V0,A1,B,B2 --repeat 2 --save local_docs/…/out.jsonl
  py -3.12 tools_issue_judge_probe.py --report local_docs/…/out.jsonl    # 저장한 답으로 다시 채점(API 0회)
세션에서 돌릴 때는 HTTP(S)_PROXY를 비운다(도구가 비운다). api_usage에는 이 도구의 함수 이름으로 기록된다(운영 라벨과 다름).
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
ROOT = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(ROOT, 'tests', 'fixtures', 'issue_judge_cases.json')
MODEL = 'claude-sonnet-5'


def _think_kw() -> dict:
    """운영과 같은 추론 끔: Sonnet 5는 thinking disabled, Sonnet 5.5는 disabled가 400이라 between_tools(effort high 이하만),
    Haiku 5.5는 disabled(effort high 이하). --model 비교 실측용 — 운영 요청(issue_suggest)은 안 바꾼다."""
    if MODEL.startswith('claude-sonnet-5-5'):
        return {'thinking': {'type': 'between_tools'}}
    return {'thinking': {'type': 'disabled'}}
PRICE_IN, PRICE_OUT = 2.0, 10.0          # Sonnet 5 $ / 100만 토큰
CONTROL = (46, 119, 2, 13)

_TAIL = ('JSON 하나만 출력한다: {"belong": [속하는 항목 번호]} — 없으면 {"belong": []}. '
         '다른 말 금지.')
# V0 — issue_suggest._haiku_relate_batch(kind='news')의 system과 글자까지 같아야 한다(테스트가 운영 요청과 대조)
SYS_V0 = ('통신·전파 정책 이슈 관리 보조자다. 각 항목의 기사가 짝지어진 이슈에 '
          '**직접 속하는지**(같은 사건·같은 절차의 후속 보도인지) 판정한다. '
          '같은 회사·같은 업계·같은 분야라는 이유만으로는 아니오다. 애매하면 아니오다. '
          + _TAIL)
_RULE = ('기준은 이슈 정의문이다 — 정의문의 "해당"에 드는 보도면 예, "해당 없음"에 적힌 범위면 '
         '같은 사건의 후속 보도라도 아니오다. 정의문에 해당/해당 없음 구분이 없으면 '
         '같은 사건·같은 절차의 후속 보도인지로 판정한다. '
         '같은 회사·같은 업계·같은 분야라는 이유만으로는 아니오다. 애매하면 아니오다. ')
# A′ — 10-12 판정 §2-2 문안
SYS_A1 = ('통신·전파 정책 이슈 관리 보조자다. 각 항목의 기사가 짝지어진 이슈에 '
          '**직접 속하는지** 판정한다. ' + _RULE + _TAIL)
_TAIL_B = ('JSON 하나만 출력한다: {"belong": [속하는 기사 번호]} — 없으면 {"belong": []}. '
           '다른 말 금지.')
SYS_B = ('통신·전파 정책 이슈 관리 보조자다. 이슈마다 정의문과 번호 붙은 기사 제목이 주어진다. '
         '각 기사가 그 위에 적힌 이슈에 **직접 속하는지** 기사마다 따로 판정한다. ' + _RULE + _TAIL_B)
SYS_B2 = ('통신·전파 정책 이슈 관리 보조자다. 이슈마다 정의문과 번호 붙은 기사 제목이 주어진다. '
          '각 기사가 그 위에 적힌 이슈에 **직접 속하는지** 기사마다 따로 판정한다. '
          '「묶음 대표」 줄은 같은 보도 묶음의 대표 제목으로, 맥락으로만 쓰고 판정 대상이 아니다. '
          + _RULE + _TAIL_B)
VARIANTS = ('V0', 'A1', 'B', 'B2', 'V0L', 'A1L')
# V0L·A1L — V0·A1과 지시문·입력이 글자까지 같고 max_tokens만 4,000(10-12 측정: 지금 정의문으로는 Sonnet 5가 「다른 말 금지」를
# 어기고 항목별 이유를 쓰다 400에서 잘린다 — 끝까지 쓰게 두면 무엇을 고르는지 보는 조건). 운영 후보가 아니라 자료용.
LONG_MAX_TOKENS = 4000


def _issue_line(iss):
    return f'이슈: [{iss["id"]}] {iss["title"]}' + (f' — {iss["definition"]}' if iss.get('definition') else '')


def build_request(variant, call, issues):
    """한 호출의 요청 kwargs와 답 번호 → 채점 단위 지도.
    반환 (kwargs, slots) — slots[k] = 답 번호 k+1이 가리키는 [(issue_id, 기사 id), ...](새 기사만)."""
    iss_of = lambda i: {'id': i, **issues[str(i)]}
    if variant in ('V0L', 'A1L'):
        kw, slots = build_request(variant[:-1], call, issues)
        return {**kw, 'max_tokens': LONG_MAX_TOKENS}, slots
    if variant in ('V0', 'A1'):
        lines, slots = [], []
        for k, g in enumerate(call['groups']):
            m = g['members']
            extra = ' / '.join(r['title'][:40] for r in m[1:3])
            lines.append(f'{k + 1}. 기사: "{m[0]["title"]}"'
                         + (f' (같은 묶음: {extra})' if extra else '')
                         + f'\n   {_issue_line(iss_of(g["issue"]))}')
            slots.append([(g['issue'], r['id']) for r in m if r['fresh']])
        return ({'model': MODEL, 'max_tokens': 400, **_think_kw(),
                 'system': SYS_V0 if variant == 'V0' else SYS_A1,
                 'messages': [{'role': 'user', 'content': '\n'.join(lines)}]}, slots)
    # B / B2 — 이슈 단위(나온 순서), 기사 번호는 호출 전체에 하나
    order, by_iss = [], defaultdict(list)
    for g in call['groups']:
        if g['issue'] not in by_iss:
            order.append(g['issue'])
        by_iss[g['issue']].append(g)
    blocks, slots, seen = [], [], set()
    for i in order:
        rows = [_issue_line(iss_of(i)).replace('이슈: ', '이슈 ', 1)]
        for g in by_iss[i]:
            fresh = [r for r in g['members'] if r['fresh'] and (i, r['id']) not in seen]
            if not fresh:
                continue
            if variant == 'B2' and len(g['members']) > 1:
                rows.append(f'  (묶음 대표: "{g["members"][0]["title"]}")')
            for r in fresh:
                seen.add((i, r['id']))
                slots.append([(i, r['id'])])
                rows.append(f'  {len(slots)}. 기사: "{r["title"]}"')
        blocks.append('\n'.join(rows))
    return ({'model': MODEL, 'max_tokens': 1000, **_think_kw(),
             'system': SYS_B if variant == 'B' else SYS_B2,
             'messages': [{'role': 'user', 'content': '\n\n'.join(blocks)}]}, slots)


def parse_belong(text, n):
    """운영과 같은 파싱 — 첫 { 부터 마지막 } 까지를 JSON으로, 범위 밖 번호는 버린다."""
    m = re.search(r'\{[\s\S]*\}', text or '')
    if not m:
        return None
    try:
        nums = json.loads(m.group(0)).get('belong') or []
    except Exception:
        return None
    return sorted({int(x) for x in nums if str(x).lstrip('-').isdigit() and 1 <= int(x) <= n})


def _load():
    with open(FIXTURE, encoding='utf-8') as f:
        return json.load(f)


def _call_api(client, kw):
    resp = client.messages.create(**kw)
    text = ''.join(b.text for b in resp.content if getattr(b, 'text', None))
    u = resp.usage
    return {'text': text, 'stop': resp.stop_reason, 'in': u.input_tokens, 'out': u.output_tokens}


def score(fx, answers):
    """answers: {(variant, rep, call_idx): {'belong': [..]|None, 'in','out', ...}} → 보고 dict."""
    gold = {(int(i), a): lab for i, d in fx['gold'].items() for a, lab in d.items()}
    calls = fx['calls']
    out = {}
    reps = sorted({r for (_, r, _) in answers})
    for v in VARIANTS:
        if not any(k[0] == v for k in answers):
            continue
        per_rep = []
        for rep in reps:
            linked, fails, tok_in, tok_out, n_calls = {}, 0, 0, 0, 0
            for ci, call in enumerate(calls):
                a = answers.get((v, rep, ci))
                if a is None:
                    continue
                kw, slots = build_request(v, call, fx['issues'])
                n_calls += 1
                tok_in += a.get('in', 0)
                tok_out += a.get('out', 0)
                bel = a.get('belong')
                if bel is None:
                    fails += 1
                    bel = []
                for k, sl in enumerate(slots):
                    for pair in sl:
                        linked[(ci,) + pair] = (k + 1) in bel
            per_rep.append({'linked': linked, 'fails': fails, 'in': tok_in, 'out': tok_out, 'calls': n_calls})
        out[v] = per_rep
    rep_out = {}
    for v, per_rep in out.items():
        rows = []
        for r in per_rep:
            lk = r['linked']
            st = Counter()
            for (ci, i, a), y in lk.items():
                lab = gold.get((i, a))
                if lab is None or lab == '경계':
                    continue
                grp = '245' if i == 245 else 'ctl'
                sset = calls[ci]['set_of'].get(f'{i}:{a}', '?')
                st[(grp, sset, lab, y)] += 1
            # 사건 통째 잃음 — #245 묶음 중 새 기사의 정답 '해당'이 과반인데 해당 0건 연결
            lost = []
            for ci, call in enumerate(calls):
                for g in call['groups']:
                    if g['issue'] != 245:
                        continue
                    lab = [(r['id'], gold.get((245, r['id']))) for r in g['members'] if r['fresh']]
                    lab = [(x, l) for x, l in lab if l in ('해당', '해당 없음')]
                    pos = [x for x, l in lab if l == '해당']
                    if lab and len(pos) * 2 > len(lab) and not any(lk.get((ci, 245, x)) for x in pos):
                        lost.append((ci, g['gid'], g['members'][0]['title'], len(pos)))
            rows.append({'st': st, 'lost': lost, 'fails': r['fails'], 'in': r['in'], 'out': r['out'], 'calls': r['calls']})
        flips = None
        if len(per_rep) >= 2:
            a, b = per_rep[0]['linked'], per_rep[1]['linked']
            keys = set(a) & set(b)
            flips = (sum(1 for k in keys if a[k] != b[k]), len(keys))
        rep_out[v] = {'rows': rows, 'flips': flips}
    return rep_out, out


def _sum(st, grp, lab, y, sset=None):
    return sum(n for (g, s, l, yy), n in st.items() if g == grp and l == lab and yy == y and (sset is None or s == sset))


def print_report(fx, answers):
    rep_out, raw = score(fx, answers)
    gold = {(int(i), a): lab for i, d in fx['gold'].items() for a, lab in d.items()}
    print('\n== 변형별 결과(반복 평균; [반복1 / 반복2]) ==')
    base = {}
    for v, d in rep_out.items():
        R = d['rows']
        def avg(f):
            vals = [f(r) for r in R]
            return sum(vals) / len(vals), vals
        neg, negv = avg(lambda r: _sum(r['st'], '245', '해당 없음', True))
        tp, tpv = avg(lambda r: _sum(r['st'], '245', '해당', True))
        fn, _ = avg(lambda r: _sum(r['st'], '245', '해당', False))
        ctp, ctpv = avg(lambda r: _sum(r['st'], 'ctl', '해당', True))
        cfn, _ = avg(lambda r: _sum(r['st'], 'ctl', '해당', False))
        cneg, _ = avg(lambda r: _sum(r['st'], 'ctl', '해당 없음', True))
        tok, _ = avg(lambda r: (r['in'] + r['out']) / max(r['calls'], 1))
        base[v] = {'neg': neg, 'rec': tp / max(tp + fn, 1), 'crec': ctp / max(ctp + cfn, 1), 'tok': tok,
                   'lost': max(len(r['lost']) for r in R), 'flips': d['flips']}
        print(f'\n[{v}] #245 해당 없음 연결 {neg:.1f} {negv} · 해당 연결 {tp:.1f}/{tp + fn:.0f} (재현율 {base[v]["rec"]:.1%})'
              f' · 대조군 해당 유지 {ctp:.1f}/{ctp + cfn:.0f} ({base[v]["crec"]:.1%}) · 대조군 해당 없음 연결 {cneg:.1f}'
              f' · 호출당 토큰 {tok:.0f} · 실패 {[r["fails"] for r in R]}')
        for sset in ('가', '나', '라'):
            a = sum(_sum(r['st'], '245', '해당 없음', True, sset) for r in R) / len(R)
            an = sum(_sum(r['st'], '245', '해당 없음', True, sset) + _sum(r['st'], '245', '해당 없음', False, sset) for r in R) / len(R)
            b = sum(_sum(r['st'], '245', '해당', True, sset) for r in R) / len(R)
            bn = sum(_sum(r['st'], '245', '해당', True, sset) + _sum(r['st'], '245', '해당', False, sset) for r in R) / len(R)
            print(f'     세트 ({sset}) 해당 없음 연결 {a:.1f}/{an:.0f} · 해당 연결 {b:.1f}/{bn:.0f}')
        if d['flips']:
            print(f'     흔들림 {d["flips"][0]}/{d["flips"][1]} ({d["flips"][0] / max(d["flips"][1], 1):.1%})')
        for k, r in enumerate(R):
            for ci, gid, t, npos in r['lost']:
                print(f'     반복{k + 1} 통째 잃음: {gid} 해당 {npos}건 :: {t[:50]}')
    for bk in ('V0', 'V0L'):
        if bk not in base:
            continue
        b0 = base[bk]
        print(f'\n== 통과 기준(판정 §3, {bk} 대비{" — 참고: 잘림 없는 기준선" if bk == "V0L" else ""}) ==')
        for v, b in base.items():
            if v in ('V0', 'V0L'):
                continue
            lim = 1 / 3 if v in ('A1', 'A1L') else 1 / 5
            p1 = b['neg'] <= b0['neg'] * lim
            p2 = b['rec'] >= b0['rec'] * 0.9 and b['lost'] == 0
            p3 = b['crec'] >= 0.95
            p4 = b['flips'] is not None and b['flips'][0] <= 0.05 * b['flips'][1]
            p5 = b['tok'] <= 1.5 * b0['tok']
            print(f'[{v}] P1 오염 {b["neg"]:.1f} ≤ {b0["neg"] * lim:.1f} {"통과" if p1 else "실패"} · '
                  f'P2 재현율 {b["rec"]:.1%} ≥ {b0["rec"] * 0.9:.1%}·잃음 {b["lost"]} {"통과" if p2 else "실패"} · '
                  f'P3 대조군 {b["crec"]:.1%} {"통과" if p3 else "실패"} · '
                  f'P4 흔들림 {"-" if b["flips"] is None else f"{b["flips"][0]}/{b["flips"][1]}"} {"통과" if p4 else "실패"} · '
                  f'P5 토큰 {b["tok"]:.0f} ≤ {1.5 * b0["tok"]:.0f} {"통과" if p5 else "실패"}')
    # 대조군 잃은 기사 전수(P3 — 운영자 확인용)
    titles = {(g['issue'], r['id']): r['title'] for c in fx['calls'] for g in c['groups'] for r in g['members']}
    for v, per_rep in raw.items():
        miss = Counter()
        for r in per_rep:
            for (ci, i, a), y in r['linked'].items():
                if i != 245 and gold.get((i, a)) == '해당' and not y:
                    miss[(i, a)] += 1
        if miss:
            print(f'\n[{v}] 대조군 해당인데 안 붙은 기사({len(miss)}건, 반복 중 몇 번):')
            for (i, a), n in sorted(miss.items()):
                print(f'     #{i} ×{n} {titles.get((i, a), a)[:60]}')


def main() -> int:
    ap = argparse.ArgumentParser(description='이슈맵 뉴스 관련 판정 지시문 실측(10-12 판정 §3)')
    ap.add_argument('--dry-run', action='store_true', help='세트·호출 수·어림 비용(API 0회)')
    ap.add_argument('--count-tokens', action='store_true', help='count_tokens로 입력 토큰을 정확히(무료, 생성 0)')
    ap.add_argument('--allow-api', action='store_true', help='실제 Sonnet 5 판정(비용 발생, 운영자 고지 뒤)')
    ap.add_argument('--variants', default='V0,A1,B,B2')
    ap.add_argument('--repeat', type=int, default=2)
    ap.add_argument('--save', default='', help='호출별 답을 jsonl로')
    ap.add_argument('--report', default='', help='저장한 jsonl로 다시 채점(API 0회)')
    ap.add_argument('--model', default='', help='비교 실측용 모델(기본 운영 Sonnet 5) — 5.5 계열은 추론 끔 꼴만 바꾼다(_think_kw)')
    a = ap.parse_args()
    global MODEL
    MODEL = a.model or MODEL
    if a.model:
        print(f'[모델] {MODEL} (비교 실측 — 운영 요청은 안 바뀜)')
    fx = _load()
    variants = [v for v in a.variants.split(',') if v]
    for v in variants:
        if v not in VARIANTS:
            print('알 수 없는 변형', v)
            return 2
    calls = fx['calls']
    g = fx['gold']
    print(f'호출(실행) {len(calls)}개 · 묶음 {sum(len(c["groups"]) for c in calls)}개 · '
          f'정답 쌍 {sum(len(d) for d in g.values())}'
          + ' (' + ', '.join(f'#{i} ' + '/'.join(f'{k} {n}' for k, n in sorted(Counter(d.values()).items())) for i, d in g.items()) + ')')
    if a.report:
        answers = {}
        with open(a.report, encoding='utf-8') as f:
            for line in f:
                x = json.loads(line)
                answers[(x['variant'], x['rep'], x['call'])] = x
        print_report(fx, answers)
        return 0
    est = {}
    for v in variants:
        chars = sum(len(build_request(v, c, fx['issues'])[0]['messages'][0]['content']) + len(build_request(v, c, fx['issues'])[0]['system'])
                    for c in calls)
        est[v] = chars
    if a.count_tokens:
        for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
            os.environ.pop(k, None)
        sys.path.insert(0, ROOT)
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, '.env'))
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
        total = 0.0
        for v in variants:
            tin = 0
            for c in calls:
                kw, slots = build_request(v, c, fx['issues'])
                r = client.messages.count_tokens(model=kw['model'], system=kw['system'], messages=kw['messages'],
                                                 thinking=kw['thinking'])
                tin += r.input_tokens
            # 출력 어림: 묶음형은 번호 몇 개(≈30), 기사별은 번호 목록(≈ 기사 수 × 2)
            tout = sum((1500 if v in ('V0L', 'A1L') else 30) if v in ('V0', 'A1', 'V0L', 'A1L') else 10 + 2 * len(build_request(v, c, fx['issues'])[1]) for c in calls)
            cost = (tin * PRICE_IN + tout * PRICE_OUT) / 1e6
            total += cost * a.repeat
            print(f'[{v}] 입력 {tin:,} 토큰(호출당 {tin / len(calls):,.0f}) · 출력 어림 {tout:,} · 1회 ${cost:.3f}')
        print(f'합계({len(variants)}변형 × {a.repeat}회): ${total:.2f} — Sonnet 5 입력 ${PRICE_IN}·출력 ${PRICE_OUT} / 100만 토큰')
        return 0
    if a.dry_run or not a.allow_api:
        for v in variants:
            print(f'[{v}] 입력 어림 {est[v]:,}자(한글 ≈1자 1토큰 안팎) · 호출 {len(calls)}개')
        if not a.dry_run:
            print('\n실제 판정은 --allow-api 로(비용 발생). 지금은 구성만 보였다.')
        return 0

    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        os.environ.pop(k, None)
    sys.path.insert(0, ROOT)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, '.env'))
    import api_usage
    api_usage.install()
    import anthropic
    key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not key:
        print('오류: ANTHROPIC_API_KEY 없음(.env)')
        return 2
    client = anthropic.Anthropic(api_key=key)
    answers = {}
    fout = open(a.save, 'a', encoding='utf-8') if a.save else None
    for rep in range(1, a.repeat + 1):
        for v in variants:
            for ci, c in enumerate(calls):
                kw, slots = build_request(v, c, fx['issues'])
                try:
                    r = _call_api(client, kw)
                    bel = None if r['stop'] == 'max_tokens' else parse_belong(r['text'], len(slots))
                except Exception as e:
                    r, bel = {'text': f'ERR {e}', 'stop': 'error', 'in': 0, 'out': 0}, None
                x = {'variant': v, 'rep': rep, 'call': ci, 'run': c['run'], 'belong': bel, **r}
                answers[(v, rep, ci)] = x
                if fout:
                    fout.write(json.dumps(x, ensure_ascii=False) + '\n')
                    fout.flush()
                print(f'  {v} 반복{rep} {c["run"]} 항목 {len(slots)} → {"실패" if bel is None else len(bel)}'
                      f' (in {r["in"]} / out {r["out"]})')
    if fout:
        fout.close()
    print_report(fx, answers)
    return 0


if __name__ == '__main__':
    sys.exit(main())
