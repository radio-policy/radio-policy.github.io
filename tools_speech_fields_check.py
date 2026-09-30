# -*- coding: utf-8 -*-
"""과방위 발언 분야 집계(#248) 공개 전 층화 검증 — 보관 원문(저장소 밖)으로 다시 분류해 표를 낸다. AI 0회·DB 무변경.

  py -3.12 tools_speech_fields_check.py --out <보고서.md> [--gold-out <표본.json>] [--gold-per 50]

정본(`과방위_발언분야_분류검토_260927.md` §7 '전체 데이터 검증') 6단계 중 기계로 되는 것을 한다:
 ① 층화 분포표(회의 종류 × 분야, 막대 밖 비율) ② 기관별 날 상식 검사(단일 피감기관 날 = 그 분야 1위·60%↑, 방송 날 70%↑,
 1소위 = 과학기술+원자력·우주 70%↑, 2소위 = 통신+방송+AI+보안 70%↑) ③ 미분류 기준(회의별 실질의 10%↓, 전체 5%↓,
 인물별 15%↓, 우정·기타는 우정 날 밖 5%↓) ④ 분야별 적중 상위 낱말 + 무작위 문맥(눈 확인용) ⑥ 분기별 추이.
 ⑤ 정답 대조는 --gold-out 으로 층별 무작위 블록(앞 블록 문맥 포함)을 뽑아 세션이 판정한다(API 0회) → --gold-in 으로 채점.
   채점은 모집단 가중 + 분야별 정밀도·재현율을 함께 낸다(2026-10-01 Fable 재검토, 배경역사 #248-보론2) — 층마다 같은 수를 뽑은
   표본을 그대로 합치면 수치가 부풀고, 전체 일치율은 방송·미디어가 좌우해 통신·전파↔보안·개인정보 혼동을 가린다.
   규칙을 고친 뒤에는 같은 정답으로 다시 재지 말고 --seed 를 바꿔 새 표본을 뽑는다(고칠 때 본 표본은 표본 안 수치).
   통과 기준(2026-10-01 운영자 결정, 배경역사 #248-보론3): 09-27의 '낱말 85%·이어받기 75%' 한 쌍으로 통과를 가리지 않는다 —
   표본 밖·모집단 가중·분야별(정밀도, 막대 비율 차이)로 보고 사람이 판단한다. 그래서 ⑤는 수치만 내고 '참고'로 찍는다.
"""
import argparse
import glob
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import speech_fields as sf  # noqa: E402

OUT_KINDS = ('noise', 'chair', 'proc', 'offtopic')


def load_all(raw_dir, since, until):
    out = []
    for p in sorted(glob.glob(os.path.join(raw_dir, '*', '*.json'))):
        m, blocks, src = sf.load_raw(p)
        d = m.get('conf_date') or ''
        if d < since or d > until:
            continue
        info = sf.meeting_info(m, blocks)
        res = sf.classify_blocks(blocks, info)
        out.append((m, blocks, src, info, res))
    return out


def stratum(m, info):
    if info['kind'] == '국정감사':
        return '국감·' + (info['default'] or '복수기관')
    return info['kind']


def dist(res):
    f = Counter()
    for x in res:
        for k, w in x['w'].items():
            f[k] += w
    return f


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def fmt_dist(f):
    tot = sum(f.values())
    return ' · '.join('%s %.0f' % (k, pct(f[k], tot)) for k in sf.FIELDS if f.get(k)) if tot else '-'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw-dir', default=sf.default_raw_dir())
    ap.add_argument('--since', default='2024-05-30')
    ap.add_argument('--until', default='2099-12-31')
    ap.add_argument('--out', required=True)
    ap.add_argument('--gold-out')
    ap.add_argument('--gold-per', type=int, default=50)
    ap.add_argument('--gold-in', nargs='*', help='세션 판정 파일들(JSON: [{key, label}]) — 규칙 판정과 대조')
    ap.add_argument('--gold-items', help='--gold-out 으로 뽑았던 표본 파일(채점 때 규칙 판정 대조용)')
    ap.add_argument('--seed', type=int, default=248)
    args = ap.parse_args()
    data = load_all(args.raw_dir, args.since, args.until)
    L = ['# 과방위 발언 분야 집계 검증 (%s, 규칙 %s)' % (args.since + '~', sf.RULES_VERSION), '',
         '회의 %d건 · 블록 %d개. 원문 폴더 `%s`. 막대 밖 = 잡음·위원장 사회·의사진행·공방 턴. 실질 = 막대 밖을 뺀 블록.' % (
             len(data), sum(len(b) for _, b, _, _, _ in data), args.raw_dir), '']
    verdict = {}

    # ① 층화 분포표
    st = defaultdict(lambda: {'n': 0, 'blocks': 0, 'kinds': Counter(), 'f': Counter()})
    for m, blocks, src, info, res in data:
        s = st[stratum(m, info)]
        s['n'] += 1
        s['blocks'] += len(blocks)
        s['kinds'].update(x['kind'] for x in res)
        s['f'].update(dist(res))
    L += ['## ① 층화 분포표', '', '| 층 | 회의 | 블록 | 막대 밖 % | 미분류 %(실질) | 이어받기 %(판정) | 분야 분포 % |', '|---|---|---|---|---|---|---|']
    tot_k = Counter()
    for k in sorted(st, key=lambda k: -st[k]['blocks']):
        s = st[k]
        kd = s['kinds']
        tot_k.update(kd)
        out = sum(kd[x] for x in OUT_KINDS)
        subst = s['blocks'] - out
        judged = kd['direct'] + kd['inherit'] + kd['agenda'] + kd['default']
        L.append('| %s | %d | %d | %.0f | %.1f | %.0f | %s |' % (
            k, s['n'], s['blocks'], pct(out, s['blocks']), pct(kd['unclassified'], subst),
            pct(kd['inherit'] + kd['agenda'] + kd['default'], judged), fmt_dist(s['f'])))
    L.append('')
    all_out = sum(tot_k[x] for x in OUT_KINDS)
    all_blocks = sum(tot_k.values())
    L.append('전체: 막대 밖 %.0f%% (잡음 %d · 사회 %d · 의사진행 %d · 공방 턴 %d), 판정 = 낱말 %d · 이어받기 %d · 회의 기본값 %d, 미분류 %d' % (
        pct(all_out, all_blocks), tot_k['noise'], tot_k['chair'], tot_k['proc'], tot_k['offtopic'],
        tot_k['direct'], tot_k['inherit'] + tot_k['agenda'], tot_k['default'], tot_k['unclassified']))
    L.append('')

    # ② 기관별 날 상식 검사
    L += ['## ② 기관·회의 종류별 상식 검사', '', '| 회의 | 날짜 | 종류·기본 분야 | 기대 | 결과 | 분포 % |', '|---|---|---|---|---|---|']
    bad2 = 0
    n2 = 0
    for m, blocks, src, info, res in data:
        f = dist(res)
        tot = sum(f.values())
        if not tot:
            continue
        exp, ok = None, None
        if info['kind'] == '국정감사' and info['default']:
            need = 70 if info['default'] == '방송·미디어' else 60
            top = max(f, key=f.get)
            ok = top == info['default'] and pct(f[info['default']], tot) >= need
            exp = '%s 1위·%d%%↑' % (info['default'], need)
        elif info['kind'] == '1소위':
            v = pct(f['과학기술·R&D'] + f['원자력·우주'], tot)
            ok, exp = v >= 70, '과학+원자력·우주 70%%↑ (%.0f)' % v
        elif info['kind'] == '2소위':
            v = pct(f['통신·전파'] + f['방송·미디어'] + f['AI·디지털'] + f['보안·개인정보'], tot)
            ok, exp = v >= 70, '통신+방송+AI+보안 70%%↑ (%.0f)' % v
        if exp is None:
            continue
        n2 += 1
        bad2 += (not ok)
        L.append('| %s | %s | %s·%s | %s | %s | %s |' % (m['confer_num'], m.get('conf_date'), info['kind'], info['default'] or '-',
                                                    exp, '통과' if ok else '**어긋남**', fmt_dist(f)))
    L.append('')
    L.append('검사 대상 %d회의 중 어긋남 %d.' % (n2, bad2))
    verdict['②'] = (bad2 == 0, '%d/%d 어긋남' % (bad2, n2))
    L.append('')

    # ③ 미분류 기준
    L += ['## ③ 미분류 기준', '']
    per_meeting = []
    tot_unc = tot_sub = 0
    per_person = defaultdict(lambda: [0, 0.0])      # speaker → [미분류, 판정]
    posta = []
    for m, blocks, src, info, res in data:
        out = sum(1 for x in res if x['kind'] in OUT_KINDS)
        sub = len(res) - out
        unc = sum(1 for x in res if x['kind'] == 'unclassified')
        tot_unc += unc
        tot_sub += sub
        per_meeting.append((pct(unc, sub), m['confer_num'], m.get('conf_date'), stratum(m, info), unc, sub))
        f = dist(res)
        tot = sum(f.values())
        is_post = any(re.search(r'우정|우체국|우편', a) for a in info.get('agencies') or [])
        if tot and not is_post and pct(f['우정·기타'], tot) > 5:
            posta.append((m['confer_num'], pct(f['우정·기타'], tot)))
        for b, x in zip(blocks, res):
            if sf.role_of(b.get('pos')) == 'chair':
                continue
            k = sf.speaker_key(b.get('name'))
            if x['kind'] == 'unclassified':
                per_person[k][0] += 1
            elif x['kind'] in ('direct', 'inherit', 'agenda', 'default'):
                per_person[k][1] += 1
    over10 = [x for x in per_meeting if x[0] > 10 and x[5] >= 20]
    avg = pct(tot_unc, tot_sub)
    L.append('- 전체 미분류 %.1f%% (기준 5%% 이하) — %s' % (avg, '통과' if avg <= 5 else '**초과**'))
    L.append('- 회의별 10%% 초과(실질 20블록 이상 회의만): %d건 — %s' % (len(over10), ', '.join('%s(%s %.0f%%)' % (c, s, v) for v, c, d, s, u, n in sorted(over10, reverse=True)[:15])))
    pp = [(pct(u, u + j), k, u, j) for k, (u, j) in per_person.items() if j >= 30]
    over15 = sorted([x for x in pp if x[0] > 15], reverse=True)
    L.append('- 인물별(판정 30건 이상 %d명) 15%% 초과: %d명 — %s' % (len(pp), len(over15), ', '.join('%s %.0f%%' % (k, v) for v, k, u, j in over15[:15])))
    L.append('- 우정 날 아닌 회의에서 우정·기타 5%% 초과: %d건 %s' % (len(posta), posta[:10]))
    verdict['③'] = (avg <= 5 and len(over15) == 0 and not posta,
                    '전체 %.1f%%, 회의 10%%↑ %d, 인물 15%%↑ %d, 우정 %d' % (avg, len(over10), len(over15), len(posta)))
    L.append('')

    # ④ 분야별 적중 상위 낱말 + 무작위 문맥
    rnd = random.Random(args.seed)
    hits = defaultdict(Counter)
    ctx = defaultdict(list)
    for m, blocks, src, info, res in data:
        for b in blocks:
            t = sf.STRIP_RE.sub(' ', sf._norm(b.get('text')))
            for f, rx in list(sf.COMPOUND_RE.items()) + list(sf.CONTENT_RE.items()) + list(sf.WEAK_RE.items()):
                for mm in rx.finditer(t):
                    w = re.sub(r'\s+', '', mm.group(0))
                    hits[f][w] += 1
                    if len(ctx[(f, w)]) < 40:
                        ctx[(f, w)].append(t[max(0, mm.start() - 40):mm.end() + 40])
    L += ['## ④ 분야별 적중 상위 낱말 (문맥 표본은 --gold-out 파일의 fp_contexts)', '']
    fp = {}
    for f in sf.FIELDS:
        top = hits[f].most_common(30)
        L.append('- **%s**: %s' % (f, ', '.join('%s %d' % (w, n) for w, n in top)))
        for w, n in top[:20]:
            c = ctx[(f, w)]
            fp['%s|%s' % (f, w)] = rnd.sample(c, min(8, len(c)))
    L.append('')

    # ⑥ 분기별 추이
    q = defaultdict(Counter)
    for m, blocks, src, info, res in data:
        d = m.get('conf_date') or ''
        q['%s-Q%d' % (d[:4], (int(d[5:7]) - 1) // 3 + 1)].update(dist(res))
    L += ['## ⑥ 분기별 분야 추이 (시기 상식 대조용)', '', '| 분기 | 분포 % |', '|---|---|']
    for k in sorted(q):
        L.append('| %s | %s |' % (k, fmt_dist(q[k])))
    L.append('')

    # ⑤ 정답 대조 표본
    if args.gold_out:
        pool = defaultdict(list)
        for m, blocks, src, info, res in data:
            s = stratum(m, info)
            for i, (b, x) in enumerate(zip(blocks, res)):
                if x['kind'] in OUT_KINDS:
                    continue
                prevs = ['%s(%s): %s' % (pb.get('name'), pb.get('pos'), sf._norm(pb.get('text'))[:400])
                         for pb in blocks[max(0, i - 2):i]]
                pool[s].append({
                    'key': '%s#%d' % (m['confer_num'], i), 'stratum': s, 'meeting': m.get('title'), 'date': m.get('conf_date'),
                    'agenda': (m.get('agenda') or [''])[0][:120], 'agencies': info.get('agencies'), 'pos': b.get('pos'), 'name': b.get('name'),
                    'prev': prevs, 'text': sf._norm(b.get('text'))[:1500], 'rule_kind': x['kind'], 'rule': x['w']})
        gold = []
        for s, items in sorted(pool.items()):
            gold += rnd.sample(items, min(args.gold_per, len(items)))
        json.dump({'fields': sf.FIELDS, 'items': gold, 'fp_contexts': fp}, open(args.gold_out, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        # 판정자에게 줄 파일 — 규칙 답(rule·rule_kind)을 뺀다(눈가림)
        blind = [{k: v for k, v in it.items() if k not in ('rule', 'rule_kind')} for it in gold]
        json.dump(blind, open(args.gold_out.replace('.json', '.blind.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        L.append('⑤ 정답 대조 표본 %d개 → %s' % (len(gold), args.gold_out))

    if args.gold_in:
        g = []
        for fn in args.gold_in:
            with open(fn, encoding='utf-8') as fp:
                g += json.load(fp)
        with open(args.gold_items, encoding='utf-8') as fp:
            gi = {x['key']: x for x in json.load(fp)['items']}
        # 규칙 답은 **지금 규칙으로 다시 계산**한다 — 판정자는 규칙 답을 모르므로(눈가림) 같은 정답으로 여러 규칙판을 채점할 수 있다
        cur = {}
        for m, blocks, src, info, res in data:
            for i, x in enumerate(res):
                cur['%s#%d' % (m['confer_num'], i)] = x
        for k, it in gi.items():
            if k in cur:
                it['rule'], it['rule_kind'] = cur[k]['w'], cur[k]['kind']
        # 모집단 가중(2026-10-01 Fable 재검토): 표본은 층마다 같은 수(50)를 뽑으므로 118블록짜리 청원소위와 6만 9천 블록짜리
        # 전체회의가 같은 무게로 섞인다 — 그대로 합치면 작은 층의 높은 일치율이 전체 수치를 끌어올린다(v3: 비가중 78% ↔ 가중 75%).
        # 층의 실질 블록 수 ÷ 그 층 표본 수를 가중치로 쓴다.
        pop, nsmp = Counter(), Counter()
        for m, blocks, src, info, res in data:
            pop[stratum(m, info)] += sum(1 for x in res if x['kind'] not in OUT_KINDS)
        for j in g:
            if j['key'] in gi:
                nsmp[gi[j['key']]['stratum']] += 1
        agree = defaultdict(lambda: [0, 0])
        wagree = defaultdict(lambda: [0.0, 0.0])
        whole = [0.0, 0.0]                          # 표본 전체(막대 밖·미분류 포함) 같은 분모 일치 — 규칙판끼리 견줄 때 쓴다
        confusion = Counter()
        table = defaultdict(Counter)                # 규칙 분야 → 판정자 분야 (가중)
        for j in g:
            it = gi.get(j['key'])
            if not it:
                continue
            labs = [x for x in (j.get('labels') or []) if x] or [j.get('label')]   # 판정자: 분야 1개(반반이면 2개) 또는 '미분류'
            rule = it['rule']
            w = pop[it['stratum']] / nsmp[it['stratum']] if nsmp[it['stratum']] else 1.0
            if it['rule_kind'] in OUT_KINDS:
                kk, ok, rf = 'out(규칙이 막대 밖으로 뺌)', '미분류' in labs, '막대 밖'
            elif it['rule_kind'] == 'unclassified':
                kk, ok, rf = 'unclassified', '미분류' in labs, '미분류'
            else:
                ok = any(x in rule for x in labs)      # 규칙이 반분이면 둘 중 하나, 판정자가 반반이면 둘 중 하나가 맞으면 일치
                kk = 'direct' if it['rule_kind'] == 'direct' else 'inherit'
                rf = max(rule, key=rule.get)
                if not ok:
                    confusion[(rf, labs[0])] += 1
            table[rf][labs[0]] += w
            agree[kk][0] += ok
            agree[kk][1] += 1
            wagree[kk][0] += w * ok
            wagree[kk][1] += w
            whole[0] += w * ok
            whole[1] += w
            agree[it['stratum']][0] += ok
            agree[it['stratum']][1] += 1
        L += ['## ⑤ 정답 대조 (판정자 눈가림, 규칙 답은 현재 규칙으로 재계산)', '']
        for k, (a, n) in sorted(agree.items()):
            L.append('- %s: %d/%d = %.0f%%' % (k, a, n, pct(a, n)) +
                     (' · 모집단 가중 %.1f%%' % pct(*wagree[k]) if k in wagree else ''))
        L.append('- 표본 전체(막대 밖·미분류 포함) 같은 분모 일치: 모집단 가중 %.1f%% — 규칙판끼리 견줄 때는 이 수치로 본다'
                 '(칸별 수치는 규칙이 블록을 다른 칸으로 옮기면 분모가 바뀐다)' % pct(*whole))
        L.append('- 틀린 짝(규칙 → 판정자) 상위: ' + ', '.join('%s→%s %d' % (a, b, n) for (a, b), n in confusion.most_common(12)))
        # 분야별 정밀도·재현율(가중) — 전체 일치율은 방송·미디어(막대의 60%)가 좌우해 작은 분야의 큰 오류를 가린다
        # (v3: 전체 낱말 판정 87%인데 통신·전파 정밀도 45%, 보안·개인정보 재현율 49%).
        # 막대 비율 차이 = 규칙이 막대 안에 둔 블록에서 규칙의 분야 비율 ↔ 그 블록 중 판정자가 분야를 준 것의 분야 비율(가중).
        rshare = {f: sum(table[f].values()) for f in sf.FIELDS}
        jshare = {f: sum(table[r][f] for r in sf.FIELDS) for f in sf.FIELDS}
        rt, jt = sum(rshare.values()), sum(jshare.values())
        gaps = {}
        L += ['', '| 규칙이 준 분야 | 정밀도(가중) | 재현율(가중) | 막대 비율 규칙 ↔ 판정자 (차이) | 판정자가 가장 많이 준 다른 답 |',
              '|---|---|---|---|---|']
        for f in sf.FIELDS:
            row = table[f]
            tot = sum(row.values())
            rec = sum(table[r][f] for r in table)
            other = [(v, k) for k, v in row.items() if k != f]
            rs, js = pct(rshare[f], rt), pct(jshare[f], jt)
            gaps[f] = rs - js
            L.append('| %s | %s | %s | %.1f%% ↔ %.1f%% (%+.1f%%p) | %s |' % (
                f, ('%.0f%%' % pct(row[f], tot)) if tot else '-', ('%.0f%%' % pct(row[f], rec)) if rec else '-',
                rs, js, rs - js,
                ('%s %.0f%%' % (max(other)[1], pct(max(other)[0], tot))) if other and tot else '-'))
        L += ['', '같은 정답으로 규칙을 고친 뒤 다시 잰 수치는 **표본 안** 수치다(v3의 87%·75%는 새 표본에서 80.5%·70.8%였다). '
              '규칙을 고쳤으면 `--seed`를 바꿔 새 표본을 뽑아 다시 판정할 것.', '']
        # 통과 기준(2026-10-01 운영자 결정, 배경역사 #248-보론3): 09-27의 '낱말 85%·이어받기 75%' 한 쌍으로 통과·미통과를 가리지
        # 않는다. ⓐ 표본 밖(규칙을 고칠 때 보지 않은 표본) ⓑ 모집단 가중 ⓒ 분야별 정밀도와 막대 비율 차이를 함께 보고 사람이 판단한다
        # — 그래서 ⑤는 '참고'로만 찍는다(수치 문턱 없음).
        wd, wi = pct(*wagree['direct']), pct(*wagree['inherit'])
        worst = max(gaps, key=lambda f: abs(gaps[f])) if gaps else None
        prec = {f: pct(table[f][f], sum(table[f].values())) for f in sf.FIELDS if sum(table[f].values())}
        low = min(prec, key=prec.get) if prec else None
        verdict['⑤'] = (None, '표본 전체 %.1f%% · 낱말 %.1f%% · 이어받기 %.1f%% (모집단 가중 — 비가중 %.0f%%·%.0f%%) · '
                              '정밀도 최저 %s %.0f%% · 막대 비율 차이 최대 %s %+.1f%%p' % (
            pct(*whole), wd, wi, pct(*agree['direct']), pct(*agree['inherit']),
            low or '-', prec.get(low, 0), worst or '-', gaps.get(worst, 0)))

    L += ['', '## 판정 요약', '']
    for k, (ok, why) in verdict.items():
        L.append('- %s %s — %s' % (k, {True: '통과', False: '**미통과**', None: '참고(수치 문턱 없음 — 표본 밖·가중·분야별로 사람이 판단)'}[ok], why))
    open(args.out, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('\n'.join(L[-(len(verdict) + 1):]))
    print('보고서:', args.out)


if __name__ == '__main__':
    main()
