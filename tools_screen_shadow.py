# -*- coding: utf-8 -*-
"""관련성 선별 Haiku 5.5 그림자(#318) 읽기 — 요약·눈가림 내보내기·판정 합치기·결과표. **AI 0회 · DB 읽기 전용.**

설계·통과 기준(운영자 확정 2026-10-17): local_docs/선별그림자_설계_261017.md §5.
크롤러(crawler._screen_shadow_*)가 app_config.screen_shadow until까지 news_screen_shadow에 남긴 행을 읽는다.

  py -3.12 tools_screen_shadow.py --summary                       # 판정 수·일치율·방향별 갈림·거부·실패·지연
  py -3.12 tools_screen_shadow.py --export DIR [--seed 1017] [--max 400]
        # 관련/무관 갈림 → 방향별 층화 표본(전체가 --max 이하면 전부), 순서 섞음:
        #   DIR/blind.json   [{bid, title, summary}]  ← 판정자에게 주는 것(어느 모델이 관련이라 했는지 없음)
        #   DIR/key.json     {meta, items: {bid: {id, dir, w}}}  ← 판정 끝날 때까지 판정자에게 주지 않는다
        #   DIR/judge_prompt.md   기준문(그 기간 지문) + 판정 규칙 1~3 + 출력 꼴
  py -3.12 tools_screen_shadow.py --merge DIR j1.json j2.json      # 두 판정자 → DIR/gold_draft.json + DIR/disagree.json
  py -3.12 tools_screen_shadow.py --report DIR gold.json           # 모집단 가중 놓침·과잉 + 통과 기준 Ⓐ~Ⓓ

방향: A = 4.5만 관련(5.5 무관), B = 5.5만 관련(4.5 무관).
  A에서 정답 관련 → 5.5 놓침 / 정답 무관 → 4.5 과잉 · B에서 정답 관련 → 4.5 놓침 / 정답 무관 → 5.5 과잉.
판정 파일 꼴: {"s001": "관련"} 또는 {"s001": {"v": "관련", "why": "…"}} (값은 관련/무관 둘 중 하나).
"""
import argparse
import hashlib
import json
import os
import random
import re
import sys
from collections import Counter

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

TABLE = 'news_screen_shadow'
COLS = ('id,created_at,batch_key,kind,model,criteria_hash,status,prod_ok,ms,detail,n_items,n_prod,n_shadow,'
        'n_diff,n_tag_diff,url,title,summary,prod_relevant,shadow_relevant,prod_tags,shadow_tags')
SHADOW_FAIL = ('error', 'no_tool', 'max_tokens', 'timeout')     # Ⓓ 그림자 실패(거부는 Ⓒ에서 따로)
# 통과 기준 — 운영자 확정 2026-10-17(설계 §5). 바꾸려면 운영자 결정.
CRIT_OVER_SHARE = 0.05       # Ⓑ 과잉 증가 ≤ 비교 배치 4.5 통과 건수의 5 %
CRIT_REFUSAL = 0.02          # Ⓒ 거부 배치 ≤ 2 %
CRIT_FAIL_MARGIN = 0.01      # Ⓓ 그림자 실패율 ≤ 운영 실패율 + 1 %p
# 판정 규칙 1~3 — crawler._SCREEN_RULES의 같은 줄 그대로(tests/test_screen_shadow_tool.py가 대조). 4~5(태그·사건)는 관련성 밖.
JUDGE_RULES = (
    '1. 각 기사를 목록 내 다른 기사·순서와 무관하게 한 건씩 독립적으로 판정하라.\n'
    '2. 위 기준문을 문자 그대로 적용하라. 기준문에 없는 근거로 추측하지 말라.\n'
    '3. 관련/무관이 애매하면 관련으로 판정하라(놓침보다 과잉 포함이 낫다).\n'
)


def screen_hash(s: str) -> str:
    """crawler._screen_hash와 같은 식(공백 정규화 → sha256 앞 16자) — 기준문 지문 대조용."""
    norm = re.sub(r'\s+', ' ', (s or '')).strip()
    return hashlib.sha256(norm.encode('utf-8')).hexdigest()[:16]


def _sb():
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        os.environ.pop(k, None)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
    from sb_client import make_client
    return make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])


def fetch(sb, kind: str, max_id=None) -> list:
    """kind 행 전부(id 순, 1,000행씩). max_id를 주면 그 id까지만(내보낸 뒤 쌓인 행이 분모를 바꾸지 않게)."""
    out, last = [], 0
    while True:
        q = sb.table(TABLE).select(COLS).eq('kind', kind).gt('id', last)
        if max_id is not None:
            q = q.lte('id', max_id)
        data = q.order('id').limit(1000).execute().data or []
        out.extend(data)
        if len(data) < 1000:
            return out
        last = data[-1]['id']


def dedupe(rel: list) -> list:
    """같은 기사(url, 없으면 제목)가 여러 번 갈렸으면 처음 것만 — 기사 하나를 한 번만 판정한다."""
    seen, out = set(), []
    for r in rel:
        k = r.get('url') or ('t:' + (r.get('title') or ''))
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def direction(r: dict) -> str:
    return 'A' if r.get('prod_relevant') else 'B'


def stats(heads: list, rel: list, tags: list) -> dict:
    """batch 행·기사 행 → 요약 수치(순수 함수)."""
    st = Counter(h.get('status') for h in heads)
    nb = len(heads)
    comp = [h for h in heads if h.get('status') == 'ok' and h.get('prod_ok')]
    n_items = sum(h.get('n_items') or 0 for h in comp)
    n_prod = sum(h.get('n_prod') or 0 for h in comp)
    n_shadow = sum(h.get('n_shadow') or 0 for h in comp)
    n_diff = sum(h.get('n_diff') or 0 for h in comp)
    both = sum(((h.get('n_prod') or 0) + (h.get('n_shadow') or 0) - (h.get('n_diff') or 0)) // 2 for h in comp)
    ms = sorted(h['ms'] for h in heads if h.get('status') == 'ok' and isinstance(h.get('ms'), int))
    rel_u = dedupe(rel)
    by_dir = Counter(direction(r) for r in rel_u)
    tag_moves = Counter()
    for r in tags:
        p, s = set(r.get('prod_tags') or []), set(r.get('shadow_tags') or [])
        for t in p - s:
            tag_moves[(t, '4.5만')] += 1
        for t in s - p:
            tag_moves[(t, '5.5만')] += 1
    return {
        'batches': nb, 'status': dict(st),
        'prod_fail': sum(1 for h in heads if not h.get('prod_ok')),
        'compared': len(comp), 'n_items': n_items, 'n_prod': n_prod, 'n_shadow': n_shadow,
        'n_diff': n_diff, 'agree': (1 - n_diff / n_items) if n_items else None,
        'both_relevant': both, 'n_tag_diff': len(tags),
        'rel_rows': len(rel), 'rel_unique': len(rel_u), 'dir': dict(by_dir),
        'refusal_rate': (st.get('refusal', 0) / nb) if nb else None,
        'shadow_fail_rate': (sum(st.get(k, 0) for k in SHADOW_FAIL) / nb) if nb else None,
        'prod_fail_rate': (sum(1 for h in heads if not h.get('prod_ok')) / nb) if nb else None,
        'ms_p50': ms[len(ms) // 2] if ms else None, 'ms_p90': ms[int(len(ms) * 0.9)] if ms else None,
        'ms_max': ms[-1] if ms else None,
        'criteria_hashes': sorted({h.get('criteria_hash') or '' for h in heads}),
        'first': min((h['created_at'] for h in heads), default=None),
        'last': max((h['created_at'] for h in heads), default=None),
        'tag_moves': {f'{t} {side}': n for (t, side), n in sorted(tag_moves.items())},
    }


def _pct(x):
    return '—' if x is None else f'{x * 100:.1f} %'


def print_stats(s: dict) -> None:
    print(f"기간 {s['first']} ~ {s['last']} · 배치 {s['batches']}개 · 상태 {s['status']}")
    print(f"비교된 배치(그림자 ok·운영 ok) {s['compared']}개 · 판정 기사 {s['n_items']}건 · "
          f"4.5 관련 {s['n_prod']} · 5.5 관련 {s['n_shadow']} · 일치율 {_pct(s['agree'])}")
    print(f"관련/무관 갈림 {s['n_diff']}건(행 {s['rel_rows']}, 기사 기준 {s['rel_unique']}) — "
          f"A 4.5만 관련 {s['dir'].get('A', 0)} / B 5.5만 관련 {s['dir'].get('B', 0)}")
    print(f"둘 다 관련 {s['both_relevant']}건 중 태그 갈림 {s['n_tag_diff']}건 · 태그 이동 {s['tag_moves']}")
    print(f"거부 배치 {_pct(s['refusal_rate'])} · 그림자 실패 {_pct(s['shadow_fail_rate'])} · "
          f"운영 실패(키워드 폴백) {_pct(s['prod_fail_rate'])}")
    print(f"그림자 지연 ms p50 {s['ms_p50']} · p90 {s['ms_p90']} · 최대 {s['ms_max']}")
    if len(s['criteria_hashes']) > 1:
        print(f"⚠️ 기준문 지문이 기간 중 {len(s['criteria_hashes'])}개: {s['criteria_hashes']}")


def sample(rel_u: list, seed: int, max_n: int) -> list:
    """방향별 층화 표본 → [(row, dir, weight)] 섞인 순서. 전체 ≤ max_n이면 전부(가중치 1).
    아니면 방향마다 max_n/2씩(한쪽이 모자라면 남는 자리를 다른 쪽에), 가중치 = 방향 모집단 ÷ 방향 표본."""
    rng = random.Random(seed)
    groups = {'A': [r for r in rel_u if direction(r) == 'A'], 'B': [r for r in rel_u if direction(r) == 'B']}
    if len(rel_u) <= max_n:
        take = {d: len(g) for d, g in groups.items()}
    else:
        half = max_n // 2
        take = {d: min(len(g), half) for d, g in groups.items()}
        spare = max_n - sum(take.values())
        for d in ('A', 'B'):
            extra = min(spare, len(groups[d]) - take[d])
            take[d] += extra
            spare -= extra
    picked = []
    for d, g in groups.items():
        chosen = rng.sample(g, take[d]) if take[d] < len(g) else list(g)
        w = (len(g) / take[d]) if take[d] else 0.0
        picked.extend((r, d, w) for r in chosen)
    rng.shuffle(picked)
    return picked


def judge_prompt(criteria: str) -> str:
    return ('# 관련성 판정 — 눈가림\n\n'
            '아래 기준문과 판정 규칙으로 blind.json의 기사마다 「관련」 또는 「무관」 하나를 정하고 근거를 한 줄 적는다.\n'
            '기사 제목과 요약(수집 때 모델이 본 그대로)만 보고 판정한다. 다른 판정자·모델의 판정은 없다.\n\n'
            '## 기준문\n\n' + criteria.strip() + '\n\n'
            '## 판정 규칙\n\n' + JUDGE_RULES + '\n'
            '## 출력\n\nJSON 하나: {"s001": {"v": "관련", "why": "…"}, "s002": {"v": "무관", "why": "…"}, …} — '
            'blind.json의 bid를 하나도 빼지 말 것.\n')


def _v(x):
    v = x.get('v') if isinstance(x, dict) else x
    if v not in ('관련', '무관'):
        raise ValueError(f'판정 값은 관련/무관만: {x!r}')
    return v


def merge(j1: dict, j2: dict) -> tuple:
    """두 판정 → (합의 {bid: v}, 갈림 [bid]). bid 집합이 다르면 오류."""
    if set(j1) != set(j2):
        raise ValueError(f'두 판정의 bid가 다름: 한쪽만 {sorted(set(j1) ^ set(j2))[:5]}')
    agree, split = {}, []
    for bid in sorted(j1):
        a, b = _v(j1[bid]), _v(j2[bid])
        if a == b:
            agree[bid] = a
        else:
            split.append(bid)
    return agree, split


def score(items: dict, gold: dict, s: dict) -> dict:
    """key.json items + 정답 → 모집단 가중 놓침·과잉, 통과 기준 Ⓐ~Ⓓ(순수 함수)."""
    missing = sorted(set(items) - set(gold))
    if missing:
        raise ValueError(f'정답이 빠진 bid {len(missing)}개: {missing[:5]}')
    est = {'miss55': 0.0, 'over45': 0.0, 'miss45': 0.0, 'over55': 0.0}
    raw = Counter()
    for bid, it in items.items():
        g = _v(gold[bid])
        k = {('A', '관련'): 'miss55', ('A', '무관'): 'over45',
             ('B', '관련'): 'miss45', ('B', '무관'): 'over55'}[(it['dir'], g)]
        est[k] += it['w']
        raw[k] += 1
    over_gap = est['over55'] - est['over45']
    crit = {
        'A_miss': est['miss55'] <= est['miss45'],
        'B_over': over_gap <= CRIT_OVER_SHARE * s['n_prod'],
        'C_refusal': (s['refusal_rate'] or 0) <= CRIT_REFUSAL,
        'D_fail': (s['shadow_fail_rate'] or 0) <= (s['prod_fail_rate'] or 0) + CRIT_FAIL_MARGIN,
    }
    return {'est': est, 'raw': dict(raw), 'over_gap': over_gap, 'over_cap': CRIT_OVER_SHARE * s['n_prod'],
            'crit': crit, 'pass': all(crit.values())}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--summary', action='store_true')
    ap.add_argument('--export', metavar='DIR')
    ap.add_argument('--seed', type=int, default=1017)
    ap.add_argument('--max', type=int, default=400)
    ap.add_argument('--merge', nargs=3, metavar=('DIR', 'J1', 'J2'))
    ap.add_argument('--report', nargs=2, metavar=('DIR', 'GOLD'))
    a = ap.parse_args()

    if a.merge:
        d, p1, p2 = a.merge
        load = lambda p: json.load(open(p, encoding='utf-8'))   # noqa: E731
        agree, split = merge(load(p1), load(p2))
        blind = {b['bid']: b for b in json.load(open(os.path.join(d, 'blind.json'), encoding='utf-8'))}
        j1, j2 = load(p1), load(p2)
        json.dump(agree, open(os.path.join(d, 'gold_draft.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        json.dump([dict(blind[b], j1=j1[b], j2=j2[b]) for b in split],
                  open(os.path.join(d, 'disagree.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'합의 {len(agree)}건 → gold_draft.json · 갈림 {len(split)}건 → disagree.json '
              f'(운영자가 정해 gold_draft에 더한 것을 gold.json으로; 30건 넘으면 셋째 판정자 다수결 + 운영자 20건 확인)')
        return

    sb = _sb()
    max_id = None
    if a.report:
        key = json.load(open(os.path.join(a.report[0], 'key.json'), encoding='utf-8'))
        max_id = key['meta']['max_id']
    heads = fetch(sb, 'batch', max_id)
    rel = fetch(sb, 'relevance', max_id)
    tags = fetch(sb, 'tags', max_id)
    s = stats(heads, rel, tags)

    if a.export:
        os.makedirs(a.export, exist_ok=True)
        rel_u = dedupe(rel)
        picked = sample(rel_u, a.seed, a.max)
        blind, items = [], {}
        for n, (r, d, w) in enumerate(picked, 1):
            bid = f's{n:03d}'
            blind.append({'bid': bid, 'title': r.get('title') or '', 'summary': r.get('summary') or ''})
            items[bid] = {'id': r['id'], 'dir': d, 'w': w}
        crow = sb.table('app_config').select('value').eq('key', 'news_relevance_criteria').limit(1).execute().data
        criteria = (crow[0]['value'] if crow else '').strip()
        if screen_hash(criteria) not in s['criteria_hashes']:
            print(f'⚠️ 지금 기준문 지문 {screen_hash(criteria)}이 기간 지문 {s["criteria_hashes"]}에 없다 — '
                  f'기간 중 기준문이 바뀌었다. 판정에 쓸 기준문을 운영자와 정할 것.')
        all_ids = [h['id'] for h in heads] + [r['id'] for r in rel] + [r['id'] for r in tags]
        meta = {'seed': a.seed, 'max': a.max, 'max_id': max(all_ids) if all_ids else 0,
                'N': {'A': s['dir'].get('A', 0), 'B': s['dir'].get('B', 0)},
                'n': dict(Counter(it['dir'] for it in items.values())), 'criteria_hash': screen_hash(criteria)}
        w = lambda name, obj: json.dump(obj, open(os.path.join(a.export, name), 'w', encoding='utf-8'),  # noqa: E731
                                        ensure_ascii=False, indent=1)
        w('blind.json', blind)
        w('key.json', {'meta': meta, 'items': items})
        open(os.path.join(a.export, 'judge_prompt.md'), 'w', encoding='utf-8').write(judge_prompt(criteria))
        print_stats(s)
        print(f"내보냄 {len(blind)}건(A {meta['n'].get('A', 0)}/{meta['N']['A']} · B {meta['n'].get('B', 0)}/{meta['N']['B']}) "
              f"→ {a.export} (blind.json·judge_prompt.md만 판정자에게, key.json은 판정 뒤에)")
        return

    if a.report:
        gold = json.load(open(a.report[1], encoding='utf-8'))
        r = score(key['items'], gold, s)
        print_stats(s)
        e = r['est']
        print(f"\n모집단 가중(표본 원수 {r['raw']}):")
        print(f"  놓침 — 4.5 {e['miss45']:.1f} · 5.5 {e['miss55']:.1f}")
        print(f"  과잉 — 4.5 {e['over45']:.1f} · 5.5 {e['over55']:.1f} (증가 {r['over_gap']:.1f}, 상한 {r['over_cap']:.1f})")
        names = {'A_miss': 'Ⓐ 5.5 놓침 ≤ 4.5 놓침', 'B_over': 'Ⓑ 과잉 증가 ≤ 4.5 통과의 5 %',
                 'C_refusal': 'Ⓒ 거부 배치 ≤ 2 %', 'D_fail': 'Ⓓ 그림자 실패 ≤ 운영 실패 + 1 %p'}
        for k, ok in r['crit'].items():
            print(f"  {'통과' if ok else '미달'}  {names[k]}")
        print(f"\n결론: {'전부 통과 → 5.5 전환 작업(거부 배치 반 나눠 재시도 포함)' if r['pass'] else '미달 있음 → 4.5 유지'}")
        return

    print_stats(s)


if __name__ == '__main__':
    main()
