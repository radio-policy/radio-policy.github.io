"""긴급도 팀 층 두 구현 전체 대조 (#250, 2026-09-27, 설계안 docs/뉴스중요도_공통팀별_설계안_260925.md §5 원칙 8;
문장 조건 규칙·판정 기록 반영 #251, §10-2) — 읽기 전용, AI 0회.

대시보드(JS — supabase/functions/_shared/urgency_rules.js)가 화면에 보이는 팀 등급과 Python 기준 구현
(urgency_rules.py — 크롤러가 수집 때 쓰는 것)이 **최근 기사 × 모든 팀**에서 한 건도 어긋나지 않는지 본다.
케이스 파일(tests/fixtures/urgency_team_cases.json)은 손으로 고른 경계만 보므로, 실제 기사 글(한글·특수문자·
NFD·긴 요약)에서 두 언어의 문자열 처리가 갈리는 곳은 이 도구가 잡는다.

  ① 실데이터 — 최근 N일(created_at, 기본 30일) news_feed 전부 × 팀 전부:
       입력글 rule_input_text / 팀 규칙 판정 team_rule_decision_judged(켜진 팀 규칙이 있는 팀만, 그 기사의
       문장 판정 기록 verdict_map을 반영 — #251) / 문장 후보 sentence_candidates(같은 팀들) /
       팀 등급 effective_team_urgency / 실장 등급 division_urgency(실마다 sort_order 순 팀)
  ② 합성 — 같은 기사에 합성 팀 규칙·팀 등급 행을 얹어(seed 고정) 팀 규칙이 아직 없어도 대조가 의미 있게:
       공통 규칙을 팀 규칙으로 복사(전부 set 참고 / 전부 min 긴급 / 섞음·평면 and_any / 꺼진 규칙·NFD 낱말 /
       none 낱말 추가 / 문장 조건 — 보통 문장·공백만·U+0085·U+FEFF만·NFD 문장·빈 칸, 무작위·정수 아닌 문장 판),
       문장 규칙이 낱말로 걸린 기사에 판정 기록(참·거짓·대기·옛 판·이상한 규칙 id·정수 아닌 판·bool 아닌 값)을 얹고,
       판정 결과로 rule 행을 만들고, 표본 기사에 human·ai·꺼진·없는·다른 팀·등급 밖 행을 덮는다.
       기사도 일부 변형(검색 요약 주입·공백 검색 요약·NFD 제목·공통값 무작위).
  ③ 경계 탐침(실패로 치지 않음) — 공백류 문자 하나짜리 검색 요약으로 Python strip ↔ JS trim 차이를 보인다.
       실데이터에 그런 검색 요약이 생기면 ①의 입력글 대조가 불일치로 잡는다.
  ④ 표류(참고) — 저장된 rule 행 중 지금 규칙·문장 판정 기록으로 다시 판정하면 달라지는 것, 저장 등급 ≠ 화면 등급.
두 쪽 입력은 같은 JSON 파일(임시 폴더)이고 JS 쪽은 `node tests/urgency_audit_node.js`가 계산한다.
①②에서 불일치가 하나라도 있으면 종료 코드 1(앞 10건 상세). node가 없으면 2.

  py -3.12 tools_urgency_audit.py                    # 최근 30일, 실데이터 + 합성
  py -3.12 tools_urgency_audit.py --days 60 --seed 7 --sample 3000
  py -3.12 tools_urgency_audit.py --keep             # 임시 입력·출력 JSON을 남기고 경로를 알려 준다

세션에서 돌릴 때는 HTTP(S)_PROXY를 비운다(세션 프록시가 SSL을 깬다). DB 쓰기 없음 — service key는 읽기에만 쓴다
(team_urgency·teams·urgency_rule_verdicts는 RLS라 anon으로는 못 읽는다). 기사는 url을 받지 않는다(#234 — 중복 대조는
news_known 몫). 판정 기록은 created_at ≥ 창 시작으로 받는다(기록은 기사보다 늦게 생기므로 창 안 기사 것은 빠짐없다).
대조 핵심(build_*·compute_python·run_node·compare·audit)은 DB 없이 import된다 — tests/test_urgency_audit.py.
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone

import urgency_rules as ur

_ROOT = os.path.dirname(os.path.abspath(__file__))
NODE_SCRIPT = os.path.join(_ROOT, 'tests', 'urgency_audit_node.js')
KST = timezone(timedelta(hours=9))
PAGE = 1000

NEWS_COLS = 'id,title,summary,screen_text,importance,urgency,created_at'
RULE_FIELDS = ('id', 'team_id', 'position', 'mode', 'level', 'any_words', 'and_any', 'none_words', 'enabled',
               'sentence', 'sentence_rev')
ROW_FIELDS = ('news_id', 'team_id', 'urgency', 'source', 'rule_id')
VERDICT_FIELDS = ('rule_id', 'sentence_rev', 'news_id', 'verdict', 'status')   # urgency_rule_verdicts(#251)

KINDS = ('txt', 'dec', 'cand', 'eff', 'div', 'max')
KIND_LABEL = {'txt': '입력글', 'dec': '팀 규칙 판정', 'cand': '문장 후보', 'eff': '팀 등급', 'div': '실장 등급',
              'max': '최대 등급'}
GATED = ('live', 'synthetic')           # 이 둘의 불일치 = 실패. probe는 참고
DS_LABEL = {'live': '실데이터', 'synthetic': '합성', 'probe': '경계 탐침'}

SYN_VARIANTS = ('set_low', 'min_high', 'mixed', 'with_off', 'none_word', 'sentence')
ODD_RULE_IDS = ('gone_rule', '__proto__', 'constructor', 'toString')   # 없는 규칙 — JS 객체 조회 함정 포함
BLANKS = ('', '   ', '\t\n', '　', '   ')                     # 두 언어 모두 공백으로 보는 것만
ROW_KINDS = (('human', 4), ('ai', 2), ('human_bad', 1), ('ai_bad', 1), ('rule_off', 1),
             ('rule_missing', 1), ('rule_other', 1), ('rule_null', 1), ('rule_own', 2), ('odd_source', 1))
EXTRA_LEVELS = ('높음', None, '')

# 문장 조건(#251) 합성 — 문장 칸 모양. 빈 문장(공백만)은 낱말 규칙과 같다(has_sentence False).
SENTENCES = ('공공·지하철 와이파이 관련 문제를 제기하는 기사', '통신사에 불리한 규제를 예고하는 기사',
             '정부 정책을 비판하는 기사')
BLANK_SENTENCES = ('', '   ', '\t\n', chr(0x3000))
# Python isspace·JS \s가 갈리는 글자만 — 두 구현 모두 빈 문장으로 쳐야 한다(_blank ≡ isBlank)
ODD_BLANK_SENTENCES = ('\x85', chr(0xFEFF), ' \x85' + chr(0xFEFF) + '\n', '\x1c\x1f')
INVISIBLE_SENTENCE = chr(0x200B)             # 폭 없는 공백 — 공백 문자가 아니라 두 구현 모두 문장으로 본다
ODD_REVS = ('1', True, None, 1.5, -1)        # 문장 판이 정수가 아님(두 구현 모두 0으로 본다) + 음수 판
# 판정 기록 모양 — 참·거짓·대기(pending/wait_body/failed)·옛 판(stale 포함)·이상한 규칙 id·정수 아닌 판·bool 아닌 값·
# 같은 (규칙, 판) 중복(뒤 행이 이긴다 — 두 구현 같은 순서로 읽는다)
VERDICT_KINDS = (('true', 4), ('false', 4), ('pending', 3), ('old_rev', 2), ('odd_rule', 1), ('odd_rev', 2),
                 ('odd_verdict', 1), ('dup', 2))
ODD_VERDICT_RULE_IDS = ('__proto__', 'toString', 'constructor', 'hasOwnProperty', '', None, 7)
# 2.0 같은 '정수 값 float'는 넣지 않는다 — Python json은 float(무시), JS는 정수 2로 읽어 갈린다. DB 칸이 int라
# 실데이터에는 생기지 않는다(판정 기록·규칙 모두 PostgREST가 정수 글자로 준다).
ODD_VERDICT_REVS = ('1', '0', True, False, None, 1.5, [1])
ODD_VERDICTS = ('true', 'false', 1, 0, [True], {'v': True})


# ── 데이터 모양 ───────────────────────────────────────────────────────────────────────────────
def common_level(n):
    """공통값 = importance || urgency || '참고' (대시보드는 마지막 자리가 classifyNewsImportance)."""
    return n.get('importance') or n.get('urgency') or '참고'


def article_view(n):
    return {'id': n['id'], 'title': n.get('title'), 'summary': n.get('summary'),
            'screen_text': n.get('screen_text'), 'common': common_level(n)}


def rule_view(r):
    return {k: r.get(k) for k in RULE_FIELDS}


def row_view(r):
    return {k: r.get(k) for k in ROW_FIELDS}


def verdict_view(v):
    return {k: v.get(k) for k in VERDICT_FIELDS}


def group_verdicts(verdicts):
    """{news_id: 그 기사의 판정 기록 행들(받은 순서)} — verdict_map은 기사 하나 것만 받는다."""
    out = {}
    for v in verdicts or []:
        out.setdefault(v.get('news_id'), []).append(v)
    return out


def _team_sort_key(t):
    so = t.get('sort_order')
    return (so is None, so or 0, t['id'])


def ordered_team_ids(teams):
    return [t['id'] for t in sorted(teams, key=_team_sort_key)]


def build_divisions(teams):
    """{실 이름: [팀 id — sort_order 순]} — 실이 없는 팀은 빠진다."""
    out = {}
    for t in sorted(teams, key=_team_sort_key):
        if t.get('division'):
            out.setdefault(t['division'], []).append(t['id'])
    return out


def build_rulesets(rules):
    """{팀 id 문자열: 그 팀의 켜진 규칙(position, id 순)} — 부르는 쪽이 거르고 정렬한다는 계약을 여기서 한 번만."""
    out = {}
    live = [r for r in rules if r.get('team_id') is not None and r.get('enabled')]
    for r in sorted(live, key=lambda r: (r.get('position') or 0, r['id'])):
        out.setdefault(str(r['team_id']), []).append(r)
    return out


def _queries(n_articles, team_ids, divisions, rulesets):
    dec_teams = [t for t in team_ids if str(t) in rulesets]
    q = []
    for i in range(n_articles):
        q.append(['txt', i])
        q.extend(['dec', i, t] for t in dec_teams)
        q.extend(['cand', i, t] for t in dec_teams)       # 문장 규칙이 없는 팀은 두 쪽 모두 [] — 그것도 대조
        q.extend(['eff', i, t] for t in team_ids)
        q.extend(['div', i, d] for d in divisions)
    return q


def build_live(news, teams, rules, rows, verdicts=None):
    """실데이터 대조 입력. rows·verdicts 중 창 밖 기사의 행은 뺀다(판정할 글이 없다)."""
    arts = [article_view(n) for n in news]
    ids = {a['id'] for a in arts}
    rules_v = [rule_view(r) for r in rules]
    team_ids = ordered_team_ids(teams)
    divisions = build_divisions(teams)
    rulesets = build_rulesets(rules_v)
    return {'articles': arts, 'rules': rules_v, 'rulesets': rulesets,
            'rows': [row_view(r) for r in rows if r.get('news_id') in ids],
            'verdicts': [verdict_view(v) for v in verdicts or [] if v.get('news_id') in ids],
            'divisions': divisions, 'queries': _queries(len(arts), team_ids, divisions, rulesets)}


# ── 합성 ─────────────────────────────────────────────────────────────────────────────────────
def _nfd(s):
    return unicodedata.normalize('NFD', s or '')


def _groups(r):
    g = r.get('and_any') or []
    if g and all(isinstance(x, str) for x in g):
        return [g]
    return [x for x in g if isinstance(x, list) and x]


def _base_common_rules(rules):
    base = [rule_view(r) for r in rules if r.get('team_id') is None and r.get('enabled')]
    if not base:                                   # 표에 공통 규칙이 없으면 비상 사본으로
        base = [dict(rule_view(r), team_id=None, enabled=True) for r in ur.URGENCY_RULES_FALLBACK]
    return sorted(base, key=lambda r: (r.get('position') or 0, r['id']))


def _sentence_shape(k, rng):
    """문장 변형의 k번째 복사 규칙 문장 칸 — 보통 문장·빈 문장·Python/JS 공백 정의가 갈리는 글자만·NFD 문장·
    칸 값 None(낱말 규칙)을 돌아가며."""
    shape = k % 5
    if shape == 0:
        return rng.choice(SENTENCES)
    if shape == 1:
        return rng.choice(BLANK_SENTENCES)
    if shape == 2:
        return rng.choice(ODD_BLANK_SENTENCES)
    if shape == 3:
        return _nfd(rng.choice(SENTENCES))
    return None


def _synthetic_rules(base, team_ids, rng):
    """→ (합성 팀 규칙 목록, {팀 id: 변형 이름}, 꺼진 규칙 id 목록)."""
    out, variant_of, off_ids = [], {}, []
    chosen = rng.sample(team_ids, min(len(SYN_VARIANTS), len(team_ids)))
    for t, var in zip(chosen, SYN_VARIANTS):
        variant_of[t] = var
        for k, b in enumerate(base):
            r = {'id': f'syn{t}_{var}_{b["id"]}', 'team_id': t, 'position': b.get('position') or (k + 1) * 10,
                 'mode': b.get('mode'), 'level': b.get('level'), 'any_words': list(b.get('any_words') or []),
                 'and_any': [list(g) if isinstance(g, list) else g for g in (b.get('and_any') or [])],
                 'none_words': list(b.get('none_words') or []), 'enabled': True,
                 'sentence': b.get('sentence'), 'sentence_rev': b.get('sentence_rev')}
            if var == 'set_low':
                r['mode'], r['level'] = 'set', '참고'
            elif var == 'min_high':
                r['mode'], r['level'] = 'min', '긴급'
            elif var == 'mixed':
                r['mode'], r['level'] = rng.choice(ur.MODES), rng.choice(ur.LEVELS)
                r['position'] = rng.choice((10, 20, 20, 30))                 # 같은 position → id 순
                if len(r['and_any']) == 1 and isinstance(r['and_any'][0], list):
                    r['and_any'] = list(r['and_any'][0])                     # 평면 배열 = 그룹 하나
            elif var == 'with_off':
                if k == 0:
                    r['enabled'] = False
                    off_ids.append(r['id'])
                r['any_words'] = [_nfd(w) for w in r['any_words']]          # NFD 낱말 — 매처가 NFC로 맞춘다
            elif var == 'none_word':
                r['none_words'] = r['none_words'] + [rng.choice(('통신', '정부', '장관', '기자'))]
            elif var == 'sentence':                                         # 문장 조건(#251)
                r['mode'], r['level'] = rng.choice(ur.MODES), rng.choice(ur.LEVELS)
                r['sentence'] = _sentence_shape(k, rng)
                r['sentence_rev'] = rng.choice(ODD_REVS) if rng.random() < 0.25 else rng.randint(0, 3)
            out.append(r)
        if var == 'mixed':                                                  # 흔한 낱말 set 규칙을 맨 앞에
            out.append({'id': f'syn{t}_mixed_front', 'team_id': t, 'position': 5, 'mode': 'set',
                        'level': rng.choice(ur.LEVELS), 'any_words': ['정부', '통신'], 'and_any': [],
                        'none_words': ['야구'], 'enabled': True})
        if var == 'sentence':
            # 흔한 낱말 문장 규칙을 맨 앞에(후보·판정이 자주 걸리게), 폭 없는 공백 문장(= 문장 규칙)과
            # 흔한 낱말의 빈 문장 규칙(갈리는 공백 글자만 = 낱말 규칙, 후보를 거기서 멈춘다)을 뒤에
            out.append({'id': f'syn{t}_sentence_front', 'team_id': t, 'position': 5, 'mode': 'set',
                        'level': rng.choice(ur.LEVELS), 'any_words': ['정부', '통신'], 'and_any': [],
                        'none_words': [], 'enabled': True, 'sentence': rng.choice(SENTENCES),
                        'sentence_rev': rng.randint(0, 2)})
            # 정수 아닌 판·음수 판 규칙 — 하나씩 꼭 있게, 낱말 규칙(복사본)보다 앞에 두어 실제로 판정에 쓰이게
            for j, rev in enumerate(ODD_REVS):
                out.append({'id': f'syn{t}_sentence_rev{j}', 'team_id': t, 'position': 6 + j,
                            'mode': rng.choice(ur.MODES), 'level': rng.choice(ur.LEVELS),
                            'any_words': [('정부', '통신', '기자', '장관', '발표')[j % 5]], 'and_any': [],
                            'none_words': [], 'enabled': True, 'sentence': rng.choice(SENTENCES), 'sentence_rev': rev})
            out.append({'id': f'syn{t}_sentence_zw', 'team_id': t, 'position': 800, 'mode': 'set',
                        'level': rng.choice(ur.LEVELS), 'any_words': ['정부', '장관'], 'and_any': [],
                        'none_words': [], 'enabled': True, 'sentence': INVISIBLE_SENTENCE, 'sentence_rev': 0})
            out.append({'id': f'syn{t}_sentence_tail', 'team_id': t, 'position': 900, 'mode': 'min',
                        'level': rng.choice(ur.LEVELS), 'any_words': ['정부', '통신', '기자'], 'and_any': [],
                        'none_words': [], 'enabled': True, 'sentence': rng.choice(ODD_BLANK_SENTENCES),
                        'sentence_rev': 1})
    return out, variant_of, off_ids


def _inject_text(r, rng):
    words = [rng.choice(r['any_words'])] if r.get('any_words') else []
    words += [rng.choice(g) for g in _groups(r)]
    if r.get('none_words') and rng.random() < 0.25:
        words.append(rng.choice(r['none_words']))
    return ' '.join(['관련'] + words + ['보도'])


def _synthetic_articles(arts, inject_rules, rng):
    out, stat = [], Counter()
    for a in arts:
        b = dict(a)
        if rng.random() < 0.5:
            b['common'] = rng.choice(ur.LEVELS)
            stat['공통값 무작위'] += 1
        x = rng.random()
        if x < 0.30:
            pass
        elif x < 0.45:
            b['screen_text'] = (a.get('summary') or '')[:300]
            stat['검색 요약=요약 앞 300자'] += 1
        elif x < 0.60:
            b['screen_text'] = rng.choice(BLANKS)
            stat['공백 검색 요약'] += 1
        elif x < 0.90:
            b['screen_text'] = _inject_text(rng.choice(inject_rules), rng)
            stat['규칙 낱말 주입'] += 1
        else:
            b['screen_text'] = _nfd(f"{a.get('title') or ''} {a.get('summary') or ''}")[:300]
            stat['NFD 검색 요약'] += 1
        if rng.random() < 0.05:
            b['title'] = _nfd(b.get('title'))
            stat['NFD 제목'] += 1
        out.append(b)
    return out, stat


def _verdict_rows(news_id, r, kind, rng):
    """규칙 r·기사 하나의 판정 기록 행(들) — urgency_rule_verdicts 모양. kind는 VERDICT_KINDS 이름."""
    rev = r.get('sentence_rev')
    cur = rev if isinstance(rev, int) and not isinstance(rev, bool) else 0      # 규칙의 지금 판(두 구현 규칙과 같게)
    row = {'rule_id': r.get('id'), 'sentence_rev': cur, 'news_id': news_id, 'verdict': None, 'status': 'done'}
    if kind in ('true', 'false'):
        row['verdict'] = kind == 'true'
    elif kind == 'pending':
        row['status'] = rng.choice(('pending', 'wait_body', 'failed'))
    elif kind == 'old_rev':                                                   # 문장을 고치기 전 판의 판정
        row['sentence_rev'] = cur + rng.choice((-1, 1, 2))
        row['verdict'], row['status'] = rng.choice((True, False)), rng.choice(('done', 'stale'))
    elif kind == 'odd_rule':
        row['rule_id'], row['verdict'] = rng.choice(ODD_VERDICT_RULE_IDS), True
    elif kind == 'odd_rev':                  # 느슨하게 정수로 바꾸면 지금 판과 같아지는 값 위주 — 받아들이면 결과가 갈린다
        near = (str(cur), [cur], None) + ((True,) if cur == 1 else ()) + ((False,) if cur == 0 else ())
        row['sentence_rev'] = rng.choice(near + ODD_VERDICT_REVS)
        row['verdict'] = True
    elif kind == 'odd_verdict':
        row['verdict'] = rng.choice(ODD_VERDICTS)
    elif kind == 'dup':
        # 같은 (규칙, 판) 두 행 — 뒤 행이 bool이면 뒤 행이 이기고, bool이 아니면(대기·이상한 값) 앞 판정이 남아야 한다
        first = dict(row, verdict=rng.choice((True, False)))
        row['verdict'] = not first['verdict'] if rng.random() < 0.6 else rng.choice((None,) + ODD_VERDICTS)
        return [first, row]
    return [row]


def _synthetic_verdicts(arts, rulesets, rng):
    """문장 조건 판정 기록 합성 → (행 목록, Counter). 문장 규칙이 있는 팀의 규칙 중 **낱말이 걸린 것**(빈 문장
    규칙 포함 — 그 기록은 무시돼야 한다)마다 70%로 기록을 얹는다. 3%는 낱말이 안 걸린 규칙의 기록, 끝에 창 밖 기사
    기록 하나 — 둘 다 결과에 영향이 없어야 한다."""
    rows, stat = [], Counter()
    kinds, weights = zip(*VERDICT_KINDS)
    sent_teams = [t for t, rs in rulesets.items() if any(ur.has_sentence(r) for r in rs)]
    for a in arts:
        text = ur.rule_input_text(a['screen_text'], a['summary'])
        for t in sent_teams:
            for r in rulesets[t]:
                if ur.match_urgency_rules([r], a['title'], text):
                    if rng.random() < 0.7:
                        kind = rng.choices(kinds, weights)[0]
                        rows.extend(_verdict_rows(a['id'], r, kind, rng))
                        stat[kind] += 1
                elif rng.random() < 0.03:
                    rows.extend(_verdict_rows(a['id'], r, 'true', rng))
                    stat['안 걸린 규칙'] += 1
    for t in sent_teams[:1]:
        rows.extend(_verdict_rows('ghost_news', rulesets[t][0], 'true', rng))
        stat['창 밖 기사'] += 1
    return rows, stat


def _synthetic_rows(arts, rules_all, rulesets, team_ids, off_ids, rng, sample, vmaps=None):
    rows, stat = {}, Counter()
    # ① 판정 → rule 행(수집 때·규칙 저장 즉시 재적용과 같은 흐름 — 문장 판정 반영). 15%는 낡은 저장값 — 화면은 무시해야 한다
    dec_teams = [t for t in team_ids if str(t) in rulesets]
    for a in arts:
        text = ur.rule_input_text(a['screen_text'], a['summary'])
        vm = (vmaps or {}).get(a['id'], {})
        for t in dec_teams:
            d = ur.team_rule_decision_judged(rulesets[str(t)], a['title'], text, a['common'], vm)
            if d:
                lv = d['level'] if rng.random() >= 0.15 else rng.choice(ur.LEVELS)
                rows[(a['id'], t)] = {'news_id': a['id'], 'team_id': t, 'urgency': lv,
                                      'source': 'rule', 'rule_id': d['rule_id']}
                stat['rule(판정)'] += 1
    # ② 표본 기사에 여러 모양의 행을 덮는다(PK news_id·team_id — 사람 수정이 규칙 행을 대신하는 것과 같다)
    own = {t: [r['id'] for r in rules_all if r.get('team_id') == t] for t in team_ids}
    kinds, weights = zip(*ROW_KINDS)
    for a in rng.sample(arts, min(sample, len(arts))):
        for t in rng.sample(team_ids, rng.randint(1, min(4, len(team_ids)))):
            kind = rng.choices(kinds, weights)[0]
            row = {'news_id': a['id'], 'team_id': t, 'urgency': rng.choice(ur.LEVELS), 'source': 'rule', 'rule_id': None}
            if kind in ('human', 'ai'):
                row['source'] = kind
            elif kind in ('human_bad', 'ai_bad'):
                row['source'], row['urgency'] = kind[:-4], rng.choice(EXTRA_LEVELS)
            elif kind == 'rule_off':
                row['rule_id'] = rng.choice(off_ids) if off_ids else 'gone_rule'
            elif kind == 'rule_missing':
                row['rule_id'] = rng.choice(ODD_RULE_IDS)
            elif kind == 'rule_other':
                others = [r['id'] for r in rules_all if r.get('team_id') != t]
                row['rule_id'] = rng.choice(others) if others else 'gone_rule'
            elif kind == 'rule_own':
                row['rule_id'] = rng.choice(own[t]) if own[t] else 'gone_rule'
            elif kind == 'odd_source':
                row['source'] = 'xyz'
            rows[(a['id'], t)] = row                    # kind == 'rule_null' → rule_id None 그대로
            stat[kind] += 1
    return list(rows.values()), stat


def build_synthetic(news, teams, rules, seed=20260927, sample=1500):
    """합성 대조 입력 → (dataset, info). 실제 기사 글 + 합성 팀 규칙·행. 공통 규칙(꺼진 것 포함)은 그대로 둔다."""
    rng = random.Random(seed)
    team_ids = ordered_team_ids(teams)
    divisions = build_divisions(teams)
    base = _base_common_rules(rules)
    syn_rules, variant_of, off_ids = _synthetic_rules(base, team_ids, rng)
    commons = [rule_view(r) for r in rules if r.get('team_id') is None] or base
    rules_all = commons + syn_rules
    rulesets = build_rulesets(syn_rules)
    arts, art_stat = _synthetic_articles([article_view(n) for n in news], base + syn_rules, rng)
    verdicts, v_stat = _synthetic_verdicts(arts, rulesets, rng)
    vmaps = {nid: ur.verdict_map(vs) for nid, vs in group_verdicts(verdicts).items()}
    rows, row_stat = _synthetic_rows(arts, rules_all, rulesets, team_ids, off_ids, rng, sample, vmaps)
    lv = list(ur.LEVELS) + list(EXTRA_LEVELS)
    queries = _queries(len(arts), team_ids, divisions, rulesets) + [['max', x, y] for x in lv for y in lv]
    ds = {'articles': arts, 'rules': rules_all, 'rulesets': rulesets, 'rows': rows, 'verdicts': verdicts,
          'divisions': divisions, 'queries': queries}
    return ds, {'variants': variant_of, 'rules': len(syn_rules), 'off': off_ids,
                'articles': art_stat, 'rows': row_stat, 'n_rows': len(rows),
                'verdicts': v_stat, 'n_verdicts': len(verdicts)}


def build_probe():
    """경계 탐침 — 공백류 문자 하나(·셋)짜리 검색 요약. 실패로 치지 않는다."""
    chars = sorted({chr(c) for c in range(0x10000)
                    if not 0xD800 <= c <= 0xDFFF and (chr(c).isspace() or unicodedata.category(chr(c)) == 'Zs')}
                   | set('﻿​᠎⁠'))
    arts = []
    for i, c in enumerate(chars):
        arts.append({'id': f'probe{i}', 'title': '탐침', 'summary': '저장 요약', 'screen_text': c, 'common': '참고'})
    return {'articles': arts, 'rules': [], 'rulesets': {}, 'rows': [], 'divisions': {},
            'queries': [['txt', i] for i in range(len(arts))]}


# ── 계산·대조 ────────────────────────────────────────────────────────────────────────────────
def compute_python(ds):
    """node 쪽(tests/urgency_audit_node.js)과 같은 배선으로 Python 함수를 부른다."""
    by_id = {}
    for r in ds.get('rules') or []:
        by_id[r['id']] = r
    rows_by_news = {}
    for row in ds.get('rows') or []:
        rows_by_news.setdefault(row['news_id'], {})[row['team_id']] = row
    verdicts_by_news = group_verdicts(ds.get('verdicts'))
    rulesets = ds.get('rulesets') or {}
    divisions = ds.get('divisions') or {}
    arts = ds.get('articles') or []
    vmaps = {}                                  # 기사 인덱스 → verdict_map(그 기사 기록 전부) — 기사마다 한 번

    def vmap(i):
        if i not in vmaps:
            vmaps[i] = ur.verdict_map(verdicts_by_news.get(arts[i]['id'], []))
        return vmaps[i]

    out = []
    for q in ds.get('queries') or []:
        kind = q[0]
        if kind == 'max':
            out.append(ur.max_level(q[1], q[2]))
            continue
        a = arts[q[1]]
        if kind == 'txt':
            out.append(ur.rule_input_text(a['screen_text'], a['summary']))
        elif kind == 'dec':
            out.append(ur.team_rule_decision_judged(rulesets.get(str(q[2]), []), a['title'],
                                                    ur.rule_input_text(a['screen_text'], a['summary']),
                                                    a['common'], vmap(q[1])))
        elif kind == 'cand':
            out.append(ur.sentence_candidates(rulesets.get(str(q[2]), []), a['title'],
                                              ur.rule_input_text(a['screen_text'], a['summary']), vmap(q[1])))
        elif kind == 'eff':
            out.append(ur.effective_team_urgency(a['common'], rows_by_news.get(a['id'], {}).get(q[2]), by_id))
        elif kind == 'div':
            out.append(ur.division_urgency(a['common'], rows_by_news.get(a['id'], {}), by_id,
                                           divisions.get(q[2], [])))
        else:
            raise ValueError(f'모르는 질의 종류: {kind}')
    return out


def run_node(payload_text, node='node', keep=False):
    """payload_text(JSON)를 임시 파일로 node에 넘긴다 → (node 출력 dict, 임시 폴더|None)."""
    tmp = tempfile.mkdtemp(prefix='urgency_audit_')
    in_path, out_path = os.path.join(tmp, 'in.json'), os.path.join(tmp, 'out.json')
    try:
        with open(in_path, 'w', encoding='utf-8') as f:
            f.write(payload_text)
        p = subprocess.run([node, NODE_SCRIPT, in_path, out_path], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=900)
        if p.returncode != 0:
            raise RuntimeError(f'node 실패(코드 {p.returncode}): {(p.stderr or p.stdout)[-800:]}')
        with open(out_path, encoding='utf-8') as f:
            return json.load(f), (tmp if keep else None)
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


def compare(ds, py, js):
    """→ (종류별 질의 수 Counter, 불일치 목록[(질의 인덱스, 질의, py, js)])."""
    counts = Counter(q[0] for q in ds['queries'])
    bad = []
    if len(py) != len(ds['queries']) or len(js) != len(ds['queries']):
        bad.append((-1, ['len'], len(py), len(js)))
    for i, (q, p, j) in enumerate(zip(ds['queries'], py, js)):
        if p != j:
            bad.append((i, q, p, j))
    return counts, bad


def audit(datasets, node='node', keep=False):
    """datasets {이름: dataset} → 보고 dict. 두 쪽 모두 **같은 JSON 글**을 읽어 계산한다."""
    text = json.dumps({'datasets': datasets}, ensure_ascii=False)
    decoded = json.loads(text)['datasets']
    t0 = time.time()
    py = {name: compute_python(ds) for name, ds in decoded.items()}
    t_py = time.time() - t0
    t0 = time.time()
    out, tmp = run_node(text, node=node, keep=keep)
    t_node = time.time() - t0
    rep = {'node': out.get('node'), 'unicode': out.get('unicode'), 'node_ms': out.get('ms'),
           'python_s': t_py, 'node_s': t_node, 'payload_mb': len(text.encode('utf-8')) / 1e6,
           'tmp': tmp, 'datasets': {}}
    for name, ds in decoded.items():
        counts, bad = compare(ds, py[name], (out.get('results') or {}).get(name) or [])
        rep['datasets'][name] = {'counts': counts, 'mismatches': bad, 'py': py[name], 'ds': ds}
    return rep


def gated_mismatches(rep):
    return sum(len(rep['datasets'][n]['mismatches']) for n in GATED if n in rep['datasets'])


def _short(s, n=120):
    return repr(s if s is None or len(s) <= n else s[:n] + '…')


def describe(ds, q, py, js):
    """불일치 한 건 — 재현에 필요한 입력 그대로."""
    j = lambda v: json.dumps(v, ensure_ascii=False)
    if q[0] == 'len':
        return f'결과 길이 다름: py {py} / js {js}'
    if q[0] == 'max':
        return f'max_level({q[1]!r}, {q[2]!r}) → py {j(py)} / js {j(js)}'
    a = ds['articles'][q[1]]
    head = f"[{KIND_LABEL[q[0]]}] 기사 {a['id']} 공통 {a['common']}"
    if q[0] in ('dec', 'cand', 'eff'):
        head += f' 팀 {q[2]}'
    if q[0] == 'div':
        head += f" 실 {q[2]} 팀 {ds['divisions'].get(q[2])}"
    lines = [head, f'      py {j(py)}', f'      js {j(js)}',
             f"      title={_short(a['title'])}", f"      screen_text={_short(a['screen_text'])}",
             f"      summary={_short(a['summary'])}"]
    if q[0] in ('dec', 'cand'):
        # 규칙 [id, 문장, 문장 판] — 문장 칸이 없으면 id만. 판정 기록은 그 기사 것 전부(verdict_map 입력 그대로)
        lines.append('      규칙 ' + j([[r['id'], r['sentence'], r.get('sentence_rev')] if 'sentence' in r else r['id']
                                       for r in ds['rulesets'].get(str(q[2]), [])]))
        lines.append('      판정 기록 ' + j([v for v in ds.get('verdicts') or [] if v.get('news_id') == a['id']]))
    if q[0] in ('eff', 'div'):
        rows = [r for r in ds['rows'] if r['news_id'] == a['id']]
        lines.append('      행 ' + j(rows))
    return '\n'.join(lines)


def drift_report(ds):
    """저장된 rule 행 ↔ 지금 규칙 재판정(문장 판정 반영 — team_rule_decision_judged). 참고용(실패 아님)
    → (이유 Counter, 예시, 저장≠화면 수, 예시). 문장 규칙 행인데 그 기사의 지금 판 판정이 참이 아니면(대기·거짓·
    문장을 고쳐 판이 바뀜) 따로 센다 — 크롤러가 다음 실행에 다시 판정해 팀 행을 고쳐 쓰는 중간 상태다."""
    by_id = {r['id']: r for r in ds['rules']}
    arts = {a['id']: a for a in ds['articles']}
    vrows = group_verdicts(ds.get('verdicts'))
    why_c, ex, ne, ex2 = Counter(), [], 0, []
    for row in ds['rows']:
        a = arts.get(row['news_id'])
        if not a:
            continue
        eff = ur.effective_team_urgency(a['common'], row, by_id)
        if eff['level'] != row.get('urgency'):
            ne += 1
            if len(ex2) < 5:
                ex2.append(f"{row['news_id']} 팀 {row['team_id']} {row.get('source')} 저장 {row.get('urgency')} "
                           f"→ 화면 {eff['level']}({eff['source']})")
        if row.get('source') != 'rule':
            continue
        r, t = by_id.get(row.get('rule_id')), row['team_id']
        if not r:
            why = '규칙 없음'
        elif not r.get('enabled'):
            why = '규칙 꺼짐'
        elif r.get('team_id') != t:
            why = '다른 팀 규칙'
        elif ur.has_sentence(r) and \
                ur.sentence_verdict(ur.verdict_map(vrows.get(a['id'], [])), r) is not True:
            why = '문장 판정 참 아님(대기·거짓·판 바뀜)'
        else:
            d = ur.team_rule_decision_judged(ds['rulesets'].get(str(t), []), a['title'],
                                             ur.rule_input_text(a['screen_text'], a['summary']), a['common'],
                                             ur.verdict_map(vrows.get(a['id'], [])))
            if d is None:
                why = '지금은 미적중'
            elif d['rule_id'] != row.get('rule_id'):
                why = '다른 규칙이 먼저 적중'
            elif d['level'] != row.get('urgency'):
                why = '등급 차이'
            else:
                why = None
        if why:
            why_c[why] += 1
            if len(ex) < 5:
                ex.append(f"{row['news_id']} 팀 {t} 규칙 {row.get('rule_id')} 저장 {row.get('urgency')} — {why}")
    return why_c, ex, ne, ex2


def probe_divergence(rep):
    """경계 탐침 불일치 → ['U+FEFF(py 글자/js 공백)', …]."""
    d = rep['datasets'].get('probe')
    if not d:
        return []
    out = []
    for _, q, p, _j in d['mismatches']:
        c = d['ds']['articles'][q[1]]['screen_text']
        side = 'py 글자로 봄·js 공백' if p == c else 'py 공백·js 글자로 봄'
        out.append(f"U+{ord(c[0]):04X}({side})")
    return out


# ── DB 적재(읽기 전용) ─────────────────────────────────────────────────────────────────────────
def _fetch_paged(make_query):
    """make_query() = 새 쿼리(유일 정렬 포함). 1,000행씩(#233)."""
    out, start = [], 0
    while True:
        rows = make_query().range(start, start + PAGE - 1).execute().data or []
        out.extend(rows)
        if len(rows) < PAGE:
            return out
        start += PAGE


def load_all(sb, days):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    # 상한(now)을 고정해 도중에 들어온 기사로 페이지가 밀리지 않게 하고, 그래도 id로 한 번 더 거른다
    # origin is null — 이슈맵 보강 옛 기사(created_at = 넣은 시각, 선별 흔적 없음)는 실데이터 표본이 아니다(#236)
    raw = _fetch_paged(lambda: sb.table('news_feed').select(NEWS_COLS)
                       .gte('created_at', since.isoformat()).lte('created_at', now.isoformat())
                       .is_('origin', 'null')
                       .order('created_at', desc=True).order('id'))
    seen, news = set(), []
    for n in raw:
        if n['id'] not in seen:
            seen.add(n['id'])
            news.append(n)
    teams = _fetch_paged(lambda: sb.table('teams').select('id,division,sort_order').order('sort_order').order('id'))
    rules = _fetch_paged(lambda: sb.table('urgency_rules').select(','.join(RULE_FIELDS))
                         .order('position').order('id'))
    rows = _fetch_paged(lambda: sb.table('team_urgency').select(','.join(ROW_FIELDS))
                        .order('news_id').order('team_id'))
    # 문장 판정 기록(#251) — 기록은 기사가 들어온 뒤에 생기므로(FK) created_at ≥ 창 시작이면 창 안 기사 것은 다 온다.
    # 정렬은 PK(rule_id, sentence_rev, news_id)로 페이지가 밀리지 않게. 창 밖 기사 것은 build_live가 거른다.
    verdicts = _fetch_paged(lambda: sb.table('urgency_rule_verdicts').select(','.join(VERDICT_FIELDS))
                            .gte('created_at', since.isoformat())
                            .order('news_id').order('rule_id').order('sentence_rev'))
    return {'news': news, 'dup': len(raw) - len(news), 'teams': teams, 'rules': rules, 'rows': rows,
            'verdicts': verdicts, 'since': since, 'now': now}


# ── 실행 ─────────────────────────────────────────────────────────────────────────────────────
def _ds_line(rep, name, extra=''):
    d = rep['datasets'][name]
    parts = [f"{KIND_LABEL[k]} {d['counts'][k]:,}" for k in KINDS if d['counts'].get(k)]
    return f"[{DS_LABEL[name]}] " + ' · '.join(parts) + extra + f" — 불일치 {len(d['mismatches'])}"


def _result_stats(rep, name):
    d = rep['datasets'][name]
    src, dec_hit, div_multi = Counter(), 0, 0
    for q, p in zip(d['ds']['queries'], d['py']):
        if q[0] == 'eff':
            src[p['source']] += 1
        elif q[0] == 'dec' and p:
            dec_hit += 1
        elif q[0] == 'div' and len(p['teams']) > 1:
            div_multi += 1
    return src, dec_hit, div_multi


def _sentence_stats(rep, name):
    """문장 조건이 대조에 실제로 들어갔는지(#251) → (후보가 있는 질의 수, 문장 규칙이 정한 판정 수,
    판정 기록 때문에 결과가 달라진 판정 수 — 기록을 무시한 team_rule_decision과 비교, Python 쪽만)."""
    d = rep['datasets'][name]
    ds = d['ds']
    by_id = {r['id']: r for r in ds.get('rules') or [] if isinstance(r.get('id'), str)}
    arts = ds.get('articles') or []
    cand_n, by_sentence, changed = 0, 0, 0
    for q, p in zip(ds['queries'], d['py']):
        if q[0] == 'cand' and p:
            cand_n += 1
        elif q[0] == 'dec':
            if p and ur.has_sentence(by_id.get(p['rule_id']) or {}):
                by_sentence += 1
            a = arts[q[1]]
            plain = ur.team_rule_decision(ds['rulesets'].get(str(q[2]), []), a['title'],
                                          ur.rule_input_text(a['screen_text'], a['summary']), a['common'])
            changed += plain != p
    return cand_n, by_sentence, changed


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='긴급도 팀 층 Python↔JS 전체 대조(#250·#251 문장 조건) — 읽기 전용, AI 0회')
    ap.add_argument('--days', type=int, default=30, help='최근 N일 기사(created_at, 기본 30)')
    ap.add_argument('--seed', type=int, default=20260927, help='합성 난수 seed')
    ap.add_argument('--sample', type=int, default=1500, help='합성 human·ai·이상 행을 얹을 기사 수')
    ap.add_argument('--node', default='node', help='node 실행 파일')
    ap.add_argument('--examples', type=int, default=10, help='불일치 상세 출력 건수')
    ap.add_argument('--keep', action='store_true', help='임시 입력·출력 JSON을 지우지 않는다')
    a = ap.parse_args()

    node = shutil.which(a.node)
    if not node:
        print(f'[중단] node를 찾지 못함({a.node}) — JS 쪽을 계산할 수 없다')
        sys.exit(2)

    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, '.env'))
    from sb_client import make_client

    t_all = time.time()
    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    t0 = time.time()
    data = load_all(sb, a.days)
    t_load = time.time() - t0
    news, teams, rules, rows, verdicts = data['news'], data['teams'], data['rules'], data['rows'], data['verdicts']

    print(f"[긴급도 팀 층 대조 #250·#251] 최근 {a.days}일 — {data['since'].astimezone(KST):%Y-%m-%d %H:%M} ~ "
          f"{data['now'].astimezone(KST):%Y-%m-%d %H:%M} KST (읽기 전용, AI 0회)")
    divisions = build_divisions(teams)
    n_team_rules = sum(1 for r in rules if r.get('team_id') is not None)
    ids = {n['id'] for n in news}
    in_rows = sum(1 for r in rows if r.get('news_id') in ids)
    print(f"[적재] 기사 {len(news):,}건(페이지 중복 제거 {data['dup']}) · 팀 {len(teams)}개(실 {len(divisions)}개, "
          f"실 없음 {sum(1 for t in teams if not t.get('division'))}) · 규칙 {len(rules)}개(공통 {len(rules) - n_team_rules}"
          f"·팀 {n_team_rules}, 꺼짐 {sum(1 for r in rules if not r.get('enabled'))}) · 팀 등급 행 {len(rows):,}건"
          f"(창 안 {in_rows:,}·창 밖 {len(rows) - in_rows:,}; 출처 " +
          (', '.join(f'{k} {v}' for k, v in sorted(Counter(r.get('source') for r in rows).items())) or '없음') +
          f") — {t_load:.1f}초")
    st_non = sum(1 for n in news if (n.get('screen_text') or '').strip())
    print(f"[검색 요약] screen_text 있음 {st_non:,}건 / 없음 {len(news) - st_non:,}건")
    n_sent = sum(1 for r in rules if ur.has_sentence(r))
    in_v = sum(1 for v in verdicts if v.get('news_id') in ids)
    print(f"[문장 조건] 문장 규칙 {n_sent}개(켜짐 {sum(1 for r in rules if ur.has_sentence(r) and r.get('enabled'))}) · "
          f"판정 기록 {len(verdicts):,}건(창 안 {in_v:,}; 상태 " +
          (', '.join(f'{k} {v}' for k, v in sorted(Counter(str(v.get('status')) for v in verdicts).items())) or '없음') +
          '; 판정 ' + (', '.join(f'{k} {v}' for k, v in sorted(Counter(str(v.get('verdict')) for v in verdicts).items()))
                     or '없음') + ')')

    t0 = time.time()
    live = build_live(news, teams, rules, rows, verdicts)
    syn, info = build_synthetic(news, teams, rules, seed=a.seed, sample=a.sample)
    t_build = time.time() - t0
    rep = audit({'live': live, 'synthetic': syn, 'probe': build_probe()}, node=node, keep=a.keep)

    src, hit, multi = _result_stats(rep, 'live')
    cn, bs, ch = _sentence_stats(rep, 'live')
    print(_ds_line(rep, 'live', f" (판정 적중 {hit:,}, 팀 등급 출처 {dict(src)}, 실장 여러 팀 {multi:,}; "
                                f"문장 후보 있음 {cn:,}, 문장 규칙이 정함 {bs:,}, 판정 기록이 바꾼 판정 {ch:,})"))
    print(f"[합성] seed {a.seed} · 팀 규칙 {info['rules']}개 — " +
          ', '.join(f'팀 {t} {v}' for t, v in info['variants'].items()) +
          f" (꺼진 규칙 {len(info['off'])}) · 팀 등급 행 {info['n_rows']:,}건 {dict(info['rows'])}")
    print(f"[합성] 기사 변형 {dict(info['articles'])}")
    print(f"[합성] 문장 판정 기록 {info['n_verdicts']:,}건 {dict(info['verdicts'])}")
    src, hit, multi = _result_stats(rep, 'synthetic')
    cn, bs, ch = _sentence_stats(rep, 'synthetic')
    print(_ds_line(rep, 'synthetic', f" (판정 적중 {hit:,}, 팀 등급 출처 {dict(src)}, 실장 여러 팀 {multi:,}; "
                                     f"문장 후보 있음 {cn:,}, 문장 규칙이 정함 {bs:,}, 판정 기록이 바꾼 판정 {ch:,})"))

    div = probe_divergence(rep)
    pc = rep['datasets']['probe']['counts']['txt']
    print(f"[경계 탐침] 공백류 문자 {pc}개 중 Python strip ↔ JS trim 다름 {len(div)}개: "
          f"{', '.join(div) or '없음'} (실패로 치지 않음 — 실데이터에 생기면 [실데이터] 입력글 대조가 잡는다)")

    why, ex, ne, ex2 = drift_report(live)
    n_rule_rows = sum(1 for r in live['rows'] if r.get('source') == 'rule')
    print(f"[표류·참고] 창 안 rule 행 {n_rule_rows:,}건 중 지금 재판정과 다름 {sum(why.values()):,}건 {dict(why)} · "
          f"저장 등급 ≠ 화면 등급 {ne:,}건(공통값·규칙이 바뀌면 정상)")
    for s in ex + ex2:
        print('    ' + s)

    print(f"[시간] 적재 {t_load:.1f}초 · 구성 {t_build:.1f}초 · Python {rep['python_s']:.1f}초 · "
          f"node {rep['node_s']:.1f}초(계산 {(rep['node_ms'] or 0) / 1000:.1f}초, {rep['node']}, Unicode {rep['unicode']}) · "
          f"입력 {rep['payload_mb']:.1f}MB · 합계 {time.time() - t_all:.1f}초")
    if rep['tmp']:
        print(f"[임시 파일] {rep['tmp']}")

    total = gated_mismatches(rep)
    if total:
        print(f'\n결과: 불일치 {total}건 — 실패. 앞 {a.examples}건:')
        shown = 0
        for name in GATED:
            d = rep['datasets'][name]
            for _, q, p, j in d['mismatches']:
                if shown >= a.examples:
                    break
                print(f'  ({DS_LABEL[name]}) ' + describe(d['ds'], q, p, j))
                shown += 1
        sys.exit(1)
    print('\n결과: 불일치 0 — 통과')


if __name__ == '__main__':
    main()
