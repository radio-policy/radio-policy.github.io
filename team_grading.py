# -*- coding: utf-8 -*-
"""
팀 채점 세트(#277, 2026-10-04) — 20건 고르기·고칠 몫/확인용 나누기·시험 후보 정리의 **순수 함수**(DB·AI 0).
crawler.py(build_grading_sets·judge_grading_trials·copy_applied_grading_trials)가 DB를 읽어 넘기고 결과를 쓴다.
설계 local_docs/팀채점_설계_261004.md §7(20건 고르기)·§3-2(시험)·§4-4(갈래 — 갈래 계산은 DB 함수 grading_branch).

판정 재료는 운영과 같다: 팀 등급 = urgency_rules.team_rule_decision_judged(그 팀의 켜진 규칙, 제목,
rule_input_text(screen_text, summary), 공통값, 저장된 done 판정) — 크롤러 _rewrite_team_rows·대시보드 재적용과 같은 입력.
사람 수정(human)·ai 행이 있으면 그 값(effective_team_urgency). 매처 두 파일(py·js)은 건드리지 않는다(함수 추가 없음).

갈래(hit_kind, 표 team_grading_items CHECK와 같은 다섯):
  rule_changed   팀 규칙이 걸려 공통과 다른 등급(set/min, 문장 참 포함)            — 설계 A
  word_hit_false 팀 규칙은 안 정했고, 문장 규칙의 낱말은 걸렸는데 판정 거짓        — 설계 B
  rule_same      팀 규칙이 걸렸지만 결과가 공통과 같음                          — A+B가 모자랄 때만 채움(무관 D에 넣지 않는다)
  near           팀 규칙 미적중 + 제목·요약에 팀 규칙 낱말 또는 team_criteria.keywords 부분 일치 — 설계 C
  unrelated      나머지                                                     — 설계 D(공통 등급 층화)
「대기」(문장 규칙 낱말이 걸렸는데 지금 판 판정이 없음)인 기사는 뽑지 않는다(설계 §7-2).

시험 후보(team_grading_trials.candidates 원소, 대시보드 S3가 이 모양으로 넣는다):
  {"rule_id": "기존 규칙 id" | null(새 규칙), "position": 정수, "mode": "min"|"set", "level": "긴급"|"보통"|"참고",
   "any_words": [...], "and_any": [...], "none_words": [...], "sentence": "≤200자" | "", "enabled": true}
noise 시험(크롤러가 세트를 만들 때 넣음)의 후보는 그 팀의 지금 문장 규칙 행 그대로(+ sentence_rev).
"""
import random
import unicodedata

import urgency_rules

SET_SIZE = 20
TARGET_A = 6                 # 규칙이 등급을 바꾼 기사
TARGET_B = 4                 # 낱말은 걸렸지만 문장 거짓(없으면 A로 채움)
TARGET_C = 6                 # 주제 근처(A+B가 10 미만이면 모자란 만큼 더)
TARGET_D = 4                 # 무관 — 공통 등급 층화
D_STRATA = (('긴급', 1), ('보통', 2), ('참고', 1))
MIN_COMMON_URGENT = 3        # 세트 전체 공통 긴급 ≥3(갈래 「공통 긴급 내림」을 잴 수 있게) — 모자라면 D의 긴급 몫을 늘림
POOL_THIN_AB = 10            # A+B가 이보다 적으면 pool_thin
MIN_SET = 14                 # 전체가 이보다 적으면 too_small(채점 안 열림)
EVENT_OVERLAP = 3            # 같은 사건 = 제목 키워드 3개 이상 공유(억제·묶기·리마인드 문턱과 같다) — 세트에 1건만
EVENT_OVERLAP_RULE = 2       # A·B 갈래(규칙 적중)는 그 규칙 낱말을 뺀 키워드 2개 공유 — 한 규칙이 고른 기사들은 규칙 낱말을
                             # 이미 공유해 제목의 나머지가 짧다(10-04 R2: 「유령 공공와이파이」 한 사건이 A 6건을 다 차지)
RULE_CAP_PER_BRANCH = 2      # A·B 갈래마다 한 규칙이 정한 기사 최대 수(10-04 R2 운영자 결정) — 위 문턱으로도 그 사건 12건 중
                             # 3건만 걸러졌다(제목 숫자 표기가 1,600곳·1600곳·1천643곳으로 제각각). 같은 사건이 고칠 몫·확인용에
                             # 갈려 들어가면 과적합 경고가 약해진다. 규칙이 적은 팀은 세트가 작아져 too_small이 될 수 있다(정직한 결과)
BODY_MIN = 200               # 본문(content, 앞뒤 공백 뺀 길이) 하한
PREFETCH = 40                # 본문 길이를 확인할 후보 수(갈래 목록마다 앞에서부터)
KINDS = ('rule_changed', 'rule_same', 'word_hit_false', 'near', 'unrelated')


def _nfc(s):
    return unicodedata.normalize('NFC', s) if isinstance(s, str) else ''


def _flat_words(v):
    """any_words·and_any(평면 배열 또는 배열의 배열)·keywords → 낱말 목록(빈 것 제외)."""
    out = []
    for x in v or []:
        if isinstance(x, str):
            if x.strip():
                out.append(x)
        elif isinstance(x, list):
            out.extend(w for w in x if isinstance(w, str) and w.strip())
    return out


def rule_words(rule) -> list:
    """규칙 하나의 낱말(any_words + and_any) — 같은 사건 비교에서 뺄 것(pick_set rule_words_of)."""
    return _flat_words((rule or {}).get('any_words')) + _flat_words((rule or {}).get('and_any'))


def near_words(team_rules, keywords) -> list:
    """「주제 근처」 낱말 = 팀 규칙의 any_words + and_any 낱말 + team_criteria.keywords(중복 제거, 순서 유지)."""
    seen, out = set(), []
    for w in [w for r in team_rules or [] for w in _flat_words(r.get('any_words')) + _flat_words(r.get('and_any'))] \
            + _flat_words(keywords):
        w = _nfc(w)
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def classify_article(n: dict, team_rules: list, team_row, vrows, words) -> dict:
    """기사 하나의 세트 재료. n = news_feed 행(id·title·screen_text·summary·urgency), team_rules = 그 팀의 켜진 규칙
    (position·id 순), team_row = 그 팀의 team_urgency 행(없으면 None), vrows = 그 기사의 done 판정 행들.
    반환 None = 공통값이 등급 셋 밖(뽑지 않음) / {'waiting': True} = 판정 대기(뽑지 않음) / 그 밖 = 재료."""
    common = n.get('urgency')
    if common not in urgency_rules.LEVELS:
        return None
    title = n.get('title') or ''
    text = urgency_rules.rule_input_text(n.get('screen_text'), n.get('summary')) or ''
    vm = urgency_rules.verdict_map(vrows)
    if urgency_rules.sentence_candidates(team_rules, title, text, vm):
        return {'id': n.get('id'), 'waiting': True}
    rules_by_id = {r.get('id'): r for r in team_rules or []}
    dec = urgency_rules.team_rule_decision_judged(team_rules, title, text, common, vm)
    if team_row and team_row.get('source') in ('human', 'ai'):
        eff = urgency_rules.effective_team_urgency(common, team_row, rules_by_id)
        team_level, source = eff['level'], eff['source']
    elif dec:
        team_level, source = dec['level'], 'rule'
    else:
        team_level, source = common, 'common'
    rule_id, rule_sentence = None, False
    if dec:
        kind = 'rule_changed' if dec['level'] != common else 'rule_same'
        rule_id = dec['rule_id']
        rule_sentence = urgency_rules.has_sentence(rules_by_id.get(rule_id) or {})
    else:
        false_rule = next((r for r in team_rules or [] if urgency_rules.has_sentence(r)
                           and urgency_rules.sentence_verdict(vm, r) is False
                           and urgency_rules.match_urgency_rules([r], title, text)), None)
        if false_rule:
            kind, rule_id, rule_sentence = 'word_hit_false', false_rule.get('id'), True
        else:
            norm = urgency_rules.normalize_text(title, text)
            kind = 'near' if any(w and w in norm for w in words or ()) else 'unrelated'
    return {'id': n.get('id'), 'waiting': False, 'kind': kind, 'common': common, 'team_level': team_level,
            'team_source': source, 'rule_id': rule_id, 'rule_sentence': rule_sentence, 'title': title}


def bucket_lists(classified: list, seed: int) -> dict:
    """재료 → 갈래별 후보 목록(seed로 섞음, 같은 입력·seed = 같은 순서). 대기·None은 뺀다.
    열쇠: A rule_changed · B word_hit_false · S rule_same · C near · D긴급/D보통/D참고 unrelated(공통 등급별)."""
    b = {'A': [], 'B': [], 'S': [], 'C': [], 'D긴급': [], 'D보통': [], 'D참고': []}
    key = {'rule_changed': 'A', 'word_hit_false': 'B', 'rule_same': 'S', 'near': 'C'}
    for c in sorted((c for c in classified if c and not c.get('waiting')), key=lambda c: str(c.get('id'))):
        k = key.get(c['kind']) or ('D' + c['common'])
        b[k].append(c)
    rng = random.Random(seed)
    for k in sorted(b):
        rng.shuffle(b[k])
    return b


def prefetch_ids(buckets: dict, k: int = PREFETCH) -> list:
    """본문 길이를 확인할 기사 id — 갈래 목록마다 앞에서 k개(같은 사건으로 건너뛸 몫까지 넉넉히)."""
    out, seen = [], set()
    for name in sorted(buckets):
        for c in buckets[name][:k]:
            if c['id'] not in seen:
                seen.add(c['id'])
                out.append(c['id'])
    return out


def strip_rule_words(kw, words) -> set:
    """제목 키워드에서 규칙 낱말에 든 것(또는 규칙 낱말을 품은 것)을 뺀다 — 대소문자·공백 무시.
    extract_keywords가 「공공와이파이」를 「공공와이파」로 자르므로 양쪽 부분 일치로 본다."""
    ws = [_nfc(w).replace(' ', '').casefold() for w in words or () if isinstance(w, str) and w.strip()]
    if not ws:
        return set(kw)
    out = set()
    for k in kw:
        kk = _nfc(k).casefold()
        if not any(w in kk or kk in w for w in ws):
            out.add(k)
    return out


def pick_set(buckets: dict, seed: int, body_ok, kw_of, rule_words_of=None) -> dict:
    """20건 고르기(설계 §7-3~5). body_ok = 본문 ≥BODY_MIN인 기사 id 집합(prefetch_ids로 확인한 것 — 그 밖은 뽑지 않는다),
    kw_of(재료) → 제목 키워드 집합(같은 사건 = EVENT_OVERLAP 이상 공유 → 세트에 1건).
    rule_words_of(재료) → 그 기사를 정한 규칙의 낱말 — 주면 A·B 갈래 후보만 「양쪽에서 그 낱말을 뺀 키워드 EVENT_OVERLAP_RULE
    공유」로 같은 사건을 본다(이미 고른 모든 기사와 비교). 다른 갈래는 그대로 EVENT_OVERLAP. A·B 갈래는 또 한 규칙(rule_id)이
    정한 기사를 갈래마다 RULE_CAP_PER_BRANCH건까지만 뽑는다.
    반환 {'items': [재료 + slot·seq], 'counts': {갈래: 건수}, 'pool_thin', 'too_small', 'common_urgent'}."""
    used, kws, picked = set(), [], {}

    def same_event(name, c, kw):
        if rule_words_of and name in ('A', 'B'):
            words = rule_words_of(c) or ()
            if words:
                mine = strip_rule_words(kw, words)
                return any(len(mine & strip_rule_words(p, words)) >= EVENT_OVERLAP_RULE for p in kws)
        return any(len(kw & p) >= EVENT_OVERLAP for p in kws)

    def take(name, k):
        got = []
        for c in buckets.get(name, []):
            if len(got) >= k:
                break
            if c['id'] in used or c['id'] not in body_ok:
                continue
            rid = c.get('rule_id')
            if name in ('A', 'B') and rid and \
                    sum(1 for p in picked.get(name, []) + got if p.get('rule_id') == rid) >= RULE_CAP_PER_BRANCH:
                continue
            kw = kw_of(c)
            if same_event(name, c, kw):
                continue
            got.append(c)
            used.add(c['id'])
            kws.append(kw)
        picked.setdefault(name, []).extend(got)
        return len(got)

    nb = take('B', TARGET_B)
    na = take('A', TARGET_A + (TARGET_B - nb))            # B가 모자라면 A로
    ns = take('S', max(0, POOL_THIN_AB - na - nb))       # A+B < 10이면 규칙 적중(같은 등급)으로 먼저
    take('C', TARGET_C + max(0, POOL_THIN_AB - na - nb - ns))
    urgent = sum(1 for lst in picked.values() for c in lst if c['common'] == '긴급')
    quota = dict(D_STRATA)
    quota['긴급'] = min(TARGET_D, max(quota['긴급'], MIN_COMMON_URGENT - urgent))
    rest = TARGET_D - quota['긴급']
    quota['보통'] = min(dict(D_STRATA)['보통'], rest)
    quota['참고'] = rest - quota['보통']
    short = 0
    for lv in ('긴급', '보통', '참고'):
        short += quota[lv] - take('D' + lv, quota[lv])
    for lv in ('보통', '참고', '긴급'):                     # 층이 모자라면 다른 층으로(무관 몫 4 유지)
        if short <= 0:
            break
        short -= take('D' + lv, short)
    order = [c for name in ('A', 'B', 'S', 'C', 'D긴급', 'D보통', 'D참고') for c in picked.get(name, [])]
    rng = random.Random(seed * 7919 + 1)
    first = rng.choice(('tune', 'check'))
    other = 'check' if first == 'tune' else 'tune'
    seqs = list(range(1, len(order) + 1))
    rng.shuffle(seqs)                                    # 화면 순서 — 갈래·몫과 무관(순서로 몫을 짐작하지 못하게)
    items = [dict(c, slot=first if i % 2 == 0 else other, seq=seqs[i]) for i, c in enumerate(order)]
    counts = {name: len(picked.get(name, [])) for name in ('A', 'B', 'S', 'C')}
    counts['D'] = sum(len(picked.get('D' + lv, [])) for lv in ('긴급', '보통', '참고'))
    return {'items': items, 'counts': counts, 'pool_thin': (na + nb) < POOL_THIN_AB,
            'too_small': len(items) < MIN_SET, 'common_urgent': sum(1 for c in items if c['common'] == '긴급')}


def candidate_rule(cand, idx: int, team_id) -> tuple:
    """시험 후보 하나 → (규칙 행 모양, 오류 글). 오류가 있으면 규칙은 None. 새 규칙(rule_id null)은 id 'cand_<idx>'."""
    if not isinstance(cand, dict):
        return None, f'{idx}번 후보가 객체가 아님'
    rid = cand.get('rule_id') if isinstance(cand.get('rule_id'), str) and cand.get('rule_id') else f'cand_{idx}'
    rule = {'id': rid, 'team_id': team_id, 'position': cand.get('position', 100), 'mode': cand.get('mode'),
            'level': cand.get('level'), 'any_words': cand.get('any_words'), 'and_any': cand.get('and_any') or [],
            'none_words': cand.get('none_words') or [], 'sentence': cand.get('sentence') or '',
            'sentence_rev': cand.get('sentence_rev', 0), 'enabled': True}
    errs = urgency_rules.validate_rules([rule])
    if errs:
        return None, errs[0]
    if len(rule['sentence']) > 200:
        return None, f'{idx}번 후보 문장이 200자 초과'
    return rule, ''


def same_sentence(a, b) -> bool:
    """두 조건 문장이 같은가 — 표 트리거(urgency_rules_sentence_rev)처럼 NFC·공백 정리 뒤 비교."""
    return ' '.join(_nfc(a or '').split()) == ' '.join(_nfc(b or '').split())
