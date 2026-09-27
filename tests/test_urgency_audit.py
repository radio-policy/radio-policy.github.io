# -*- coding: utf-8 -*-
"""
tools_urgency_audit(#250, 설계안 §5 원칙 8 — 긴급도 팀 층 Python↔JS 대조; 문장 조건 #251 §10-2) 오프라인 테스트.
표준 unittest, 네트워크·DB 없음. node가 PATH에 없으면 대조 테스트는 건너뛴다.

  - 케이스 파일 팀 규칙·문장 규칙 + 비상 사본 공통 규칙 + 가짜 기사(NFD 제목·NFD 검색 요약·빈 값 포함) +
    판정 기록(참·거짓·대기·옛 판·'__proto__'·글자 판)으로 실데이터·합성 대조 → 불일치 0
  - 대조가 의미 있었는지(판정 적중·human/rule/ai 출처·여러 팀 실장 줄·문장 후보·문장 규칙이 정한 판정·
    판정 기록이 바꾼 판정이 실제로 나옴), 팀 규칙 판정이 판정 기록을 반영하는지(team_rule_decision_judged)
  - 대조기가 차이를 실제로 잡는지(결과 하나를 바꾸면 불일치 1)
  - 표류 보고가 꺼짐·다른 팀·등급 차이·문장 판정 참 아님을 구분하는지
  - 경계 탐침의 strip↔trim 차이가 알려진 문자 밖으로 늘지 않았는지
  - import만으로 DB·dotenv를 끌어오지 않는지
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import unicodedata
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import urgency_rules as ur  # noqa: E402
import tools_urgency_audit as tua  # noqa: E402

NODE = shutil.which('node')
# Python str.strip()과 JS String.trim()의 공백 정의 차이(2026-09-27 실측, node 24 / Python 3.12).
# 검색 요약이 이 문자로만 되어 있으면 rule_input_text ↔ ruleInputText가 갈린다 — 늘어나면 새 차이다.
KNOWN_WS_DIVERGENCE = {'﻿', '\x1c', '\x1d', '\x1e', '\x1f', '\x85'}


def _fixture():
    with open(os.path.join(_ROOT, 'tests', 'fixtures', 'urgency_team_cases.json'), encoding='utf-8') as f:
        T = json.load(f)
    commons = [dict(r, team_id=None, enabled=True) for r in ur.URGENCY_RULES_FALLBACK]
    commons.append({'id': 'common_off', 'team_id': None, 'position': 99, 'mode': 'set', 'level': '긴급',
                    'any_words': ['통신'], 'and_any': [], 'none_words': [], 'enabled': False})
    # 문장 조건 규칙(#251) — 케이스 파일 것을 팀 3(나실, 혼자) 규칙으로. s_off는 꺼져 목록에서 빠진다
    rules = commons + T['rules'] + [dict(r, team_id=3) for r in T['sentence_rules']]
    teams = [{'id': 1, 'division': '가실', 'sort_order': 11}, {'id': 2, 'division': '가실', 'sort_order': 12},
             {'id': 3, 'division': '나실', 'sort_order': 21}, {'id': 4, 'division': None, 'sort_order': 31}]
    nfd = lambda s: unicodedata.normalize('NFD', s)
    news = [
        {'id': 'n1', 'title': nfd('3.7GHz 주파수 경매 일정 확정'), 'summary': '과기정통부 발표',
         'screen_text': None, 'importance': '보통', 'urgency': '보통'},
        {'id': 'n2', 'title': '프로야구 중계권 협상 난항', 'summary': '', 'screen_text': '',
         'importance': None, 'urgency': '긴급'},
        {'id': 'n3', 'title': '정부, 이달 중 발표', 'summary': 'AI 요약 문장',
         'screen_text': '주파수 할당 대가 산정 방식 공개', 'importance': '참고', 'urgency': '참고'},
        {'id': 'n4', 'title': 'AI 기본법 시행령 입법예고', 'summary': None, 'screen_text': '   ',
         'importance': None, 'urgency': None},
        {'id': 'n5', 'title': 'SKT 국정감사 증인 채택', 'summary': '과방위 국감',
         'screen_text': 'SK텔레콤 대표 국감 증인 출석', 'importance': '긴급', 'urgency': '보통'},
        {'id': 'n6', 'title': '해외 주파수 경매 동향', 'summary': '알뜰폰 점유율 급증',
         'screen_text': None, 'importance': '보통', 'urgency': '보통'},
        {'id': 'n7', 'title': '과기정통부 차관 인사 발령', 'summary': '인사말 하는 장관',
         'screen_text': nfd('과기정통부 인사 이동통신 담당'), 'importance': '참고', 'urgency': '참고'},
        {'id': 'n8', 'title': None, 'summary': None, 'screen_text': None, 'importance': None, 'urgency': None},
        # ↓ 문장 조건(#251) — 팀 3 규칙: s_wifi(문장, 판 1) · w_wifi(빈 문장) · s_spec(문장) · s_sat(문장) · s_blank(공백 문장)
        {'id': 'n9', 'title': '서울 공공와이파이 장애 복구 지연', 'summary': '', 'screen_text': None,
         'importance': None, 'urgency': '참고'},                                       # s_wifi 판 1 참
        {'id': 'n10', 'title': nfd('지하철 와이파이 먹통에 승객 불편'), 'summary': None, 'screen_text': None,
         'importance': '참고', 'urgency': '참고'},                                      # s_wifi 판 1 거짓
        {'id': 'n11', 'title': '주파수 재할당 대가와 저궤도 위성 규제', 'summary': '업계 반발', 'screen_text': '',
         'importance': '보통', 'urgency': '보통'},                                      # 대기·글자 판 → 둘 다 후보
        {'id': 'n12', 'title': '주파수 재할당 대가 산정 논란', 'summary': None, 'screen_text': None,
         'importance': '보통', 'urgency': '보통'},                                      # s_spec 거짓, 저장 행은 s_spec
    ]
    rows = [
        {'news_id': 'n1', 'team_id': 1, 'urgency': '긴급', 'source': 'rule', 'rule_id': 't1_min_up'},
        {'news_id': 'n2', 'team_id': 1, 'urgency': '보통', 'source': 'rule', 'rule_id': 't1_set_down'},  # 낡은 저장값
        {'news_id': 'n2', 'team_id': 2, 'urgency': '참고', 'source': 'human', 'rule_id': None},
        {'news_id': 'n3', 'team_id': 3, 'urgency': '긴급', 'source': 'ai', 'rule_id': None},
        {'news_id': 'n5', 'team_id': 1, 'urgency': '긴급', 'source': 'rule', 'rule_id': 't1_off'},
        {'news_id': 'n5', 'team_id': 2, 'urgency': '보통', 'source': 'rule', 'rule_id': 't1_min_up'},  # 다른 팀 규칙
        {'news_id': 'n6', 'team_id': 4, 'urgency': '긴급', 'source': 'human', 'rule_id': None},
        {'news_id': 'old', 'team_id': 1, 'urgency': '긴급', 'source': 'human', 'rule_id': None},       # 창 밖
        {'news_id': 'n10', 'team_id': 3, 'urgency': '보통', 'source': 'rule', 'rule_id': 'w_wifi'},    # 판정 반영 → 표류 아님
        {'news_id': 'n12', 'team_id': 3, 'urgency': '긴급', 'source': 'rule', 'rule_id': 's_spec'},    # 판정 거짓인데 남은 행
    ]
    verdicts = [
        {'news_id': 'n9', 'rule_id': 's_wifi', 'sentence_rev': 1, 'verdict': True, 'status': 'done'},
        {'news_id': 'n9', 'rule_id': 's_wifi', 'sentence_rev': 0, 'verdict': False, 'status': 'stale'},   # 옛 판
        {'news_id': 'n10', 'rule_id': 's_wifi', 'sentence_rev': 1, 'verdict': False, 'status': 'done'},
        {'news_id': 'n10', 'rule_id': '__proto__', 'sentence_rev': 1, 'verdict': True, 'status': 'done'},
        {'news_id': 'n11', 'rule_id': 's_spec', 'sentence_rev': 0, 'verdict': None, 'status': 'pending'},
        {'news_id': 'n11', 'rule_id': 's_sat', 'sentence_rev': '0', 'verdict': True, 'status': 'done'},   # 판이 글자 → 무시
        {'news_id': 'n12', 'rule_id': 's_spec', 'sentence_rev': 0, 'verdict': False, 'status': 'done'},
        {'news_id': 'old', 'rule_id': 's_wifi', 'sentence_rev': 1, 'verdict': True, 'status': 'done'},    # 창 밖
    ]
    return news, teams, rules, rows, verdicts


@unittest.skipUnless(NODE, 'node 없음 — JS 쪽 대조 건너뜀')
class TestUrgencyAuditParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        news, teams, rules, rows, verdicts = _fixture()
        cls.live = tua.build_live(news, teams, rules, rows, verdicts)
        many = [dict(n, id=f"{n['id']}_{k}") for k in range(6) for n in news]
        # 합성 변형이 여섯(문장 조건 포함)이라 팀도 여섯 — 실데이터 대조는 팀 넷 그대로
        teams6 = teams + [{'id': 5, 'division': '다실', 'sort_order': 41}, {'id': 6, 'division': '가실', 'sort_order': 13}]
        cls.syn, cls.info = tua.build_synthetic(many, teams6, rules, seed=11, sample=len(many))
        cls.rep = tua.audit({'live': cls.live, 'synthetic': cls.syn, 'probe': tua.build_probe()}, node=NODE)

    def test_zero_mismatch(self):
        for name in tua.GATED:
            d = self.rep['datasets'][name]
            msg = '\n'.join(tua.describe(d['ds'], q, p, j) for _, q, p, j in d['mismatches'][:5])
            self.assertEqual(d['mismatches'], [], f'{name} 불일치:\n{msg}')
        self.assertEqual(tua.gated_mismatches(self.rep), 0)

    def test_live_counts_and_coverage(self):
        c = self.rep['datasets']['live']['counts']
        # 기사 12 · 규칙 있는 팀 1·2·3(판정·문장 후보) · 팀 4 · 실 둘
        self.assertEqual((c['txt'], c['dec'], c['cand'], c['eff'], c['div']), (12, 36, 36, 48, 24))
        src, hit, multi = tua._result_stats(self.rep, 'live')
        self.assertGreaterEqual(hit, 3)
        self.assertTrue({'common', 'human', 'rule', 'ai'} <= set(src), src)
        self.assertGreater(multi, 0)
        d = self.rep['datasets']['live']
        got = {tuple(q): p for q, p in zip(d['ds']['queries'], d['py'])}
        self.assertEqual(got[('dec', 0, 1)], {'level': '긴급', 'rule_id': 't1_min_up'})   # NFD 제목도 적중
        self.assertEqual(got[('eff', 1, 1)], {'level': '참고', 'source': 'rule'})         # 낡은 저장값 무시
        self.assertEqual(got[('eff', 4, 2)], {'level': '긴급', 'source': 'common'})       # 다른 팀 규칙 행
        self.assertEqual(len(d['ds']['verdicts']), 7)                                      # 창 밖 기사 기록은 뺀다

    def test_live_sentence_results(self):
        """팀 규칙 판정이 그 기사의 판정 기록을 반영한다(team_rule_decision_judged) — 케이스 파일과 같은 결론."""
        d = self.rep['datasets']['live']
        got = {tuple(q): p for q, p in zip(d['ds']['queries'], d['py'])}
        self.assertEqual(got[('dec', 8, 3)], {'level': '긴급', 'rule_id': 's_wifi'})     # 판 1 참 → 문장 규칙이 정함
        self.assertEqual(got[('cand', 8, 3)], [])
        self.assertEqual(got[('dec', 9, 3)], {'level': '보통', 'rule_id': 'w_wifi'})     # 거짓 → 뒤 낱말 규칙(NFD 제목)
        self.assertEqual(got[('cand', 9, 3)], [])
        self.assertEqual(got[('cand', 10, 3)], ['s_spec', 's_sat'])                        # 대기·글자 판 = 판정 없음
        self.assertEqual(got[('dec', 10, 3)], {'level': '긴급', 'rule_id': 's_blank'})    # 공백 문장 = 낱말 규칙
        self.assertEqual(got[('dec', 10, 1)], {'level': '긴급', 'rule_id': 't1_min_up'})
        self.assertIsNone(got[('dec', 11, 3)])                                              # 거짓 → 팀 행 없음
        self.assertEqual(got[('cand', 11, 3)], [])
        self.assertEqual(got[('cand', 8, 1)], [])                                           # 문장 규칙 없는 팀
        cn, bs, ch = tua._sentence_stats(self.rep, 'live')
        self.assertEqual((cn, bs), (1, 1))            # 후보 있는 것 n11 하나, 문장 규칙이 정한 것 n9 하나
        self.assertEqual(ch, 3)                       # 기록을 무시하면 n10(s_wifi)·n11(s_spec)·n12(s_spec)가 달라진다

    def test_synthetic_coverage(self):
        c = self.rep['datasets']['synthetic']['counts']
        self.assertEqual(c['max'], 36)
        self.assertGreater(c['dec'], 0)
        self.assertEqual(c['cand'], c['dec'])
        src, hit, _ = tua._result_stats(self.rep, 'synthetic')
        self.assertGreater(hit, 0)
        self.assertTrue({'common', 'human', 'rule', 'ai'} <= set(src), src)
        self.assertEqual(len(self.info['variants']), 6)          # 팀이 여섯이면 변형 여섯
        self.assertIn('sentence', self.info['variants'].values())
        self.assertTrue(self.info['off'])
        self.assertGreater(self.info['n_verdicts'], 0)
        self.assertTrue({'true', 'false', 'pending'} <= set(self.info['verdicts']), self.info['verdicts'])
        cn, bs, ch = tua._sentence_stats(self.rep, 'synthetic')
        self.assertGreater(cn, 0)                                 # 문장 후보가 실제로 나왔고
        self.assertGreater(bs, 0)                                 # 문장 규칙이 정한 판정도 있고
        self.assertGreater(ch, 0)                                 # 판정 기록이 결과를 바꾼 판정도 있다
        shapes = {r.get('sentence') for r in self.syn['rules'] if r.get('team_id') is not None}
        self.assertIn(tua.INVISIBLE_SENTENCE, shapes)                       # 폭 없는 공백 = 문장
        self.assertTrue(set(tua.ODD_BLANK_SENTENCES) & shapes, shapes)      # U+0085·U+FEFF만 = 빈 문장
        self.assertTrue(any(isinstance(s, str) and s != unicodedata.normalize('NFC', s) for s in shapes))   # NFD 문장

    def test_comparator_detects_difference(self):
        d = self.rep['datasets']['live']
        js = copy.deepcopy(d['py'])
        i = next(k for k, q in enumerate(d['ds']['queries']) if q[0] == 'eff')
        js[i] = {'level': '긴급' if js[i]['level'] != '긴급' else '참고', 'source': js[i]['source']}
        _, bad = tua.compare(d['ds'], d['py'], js)
        self.assertEqual([b[0] for b in bad], [i])
        self.assertIn('팀 등급', tua.describe(d['ds'], bad[0][1], bad[0][2], bad[0][3]))
        _, bad = tua.compare(d['ds'], d['py'], js[:-1])
        self.assertEqual(bad[0][0], -1)
        # 문장 후보 결과 하나를 바꾸면 그 하나만 잡고, 설명에 규칙 문장·판정 기록이 나온다
        js = copy.deepcopy(d['py'])
        k = next(k for k, q in enumerate(d['ds']['queries']) if q == ['cand', 10, 3])
        js[k] = ['s_sat']
        _, bad = tua.compare(d['ds'], d['py'], js)
        self.assertEqual([b[0] for b in bad], [k])
        text = tua.describe(d['ds'], bad[0][1], bad[0][2], bad[0][3])
        self.assertIn('문장 후보', text)
        self.assertIn('판정 기록', text)
        self.assertIn('s_spec', text)

    def test_drift_report(self):
        why, _, ne, _ = tua.drift_report(self.live)
        # n10 팀3 w_wifi 행은 판정 기록(s_wifi 거짓)을 반영하면 표류가 아니다 — 기록을 무시하면 '다른 규칙이 먼저 적중'
        self.assertEqual(dict(why), {'등급 차이': 1, '규칙 꺼짐': 1, '다른 팀 규칙': 1,
                                     '문장 판정 참 아님(대기·거짓·판 바뀜)': 1})
        self.assertEqual(ne, 2)          # n2 팀1(낡은 저장값 보통 → 화면 참고), n5 팀2(다른 팀 규칙 → 공통 긴급)

    def test_probe_divergence_known_only(self):
        d = self.rep['datasets']['probe']
        chars = {d['ds']['articles'][q[1]]['screen_text'] for _, q, _, _ in d['mismatches']}
        self.assertTrue(chars <= KNOWN_WS_DIVERGENCE, sorted(f'U+{ord(c):04X}' for c in chars - KNOWN_WS_DIVERGENCE))


class TestImportIsOffline(unittest.TestCase):
    def test_import_does_not_touch_db(self):
        code = ('import sys; sys.path.insert(0, %r); import tools_urgency_audit; '
                'print(sorted(m for m in ("supabase", "sb_client", "dotenv", "httpx") if m in sys.modules))' % _ROOT)
        p = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=_ROOT)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), '[]')


if __name__ == '__main__':
    unittest.main()
