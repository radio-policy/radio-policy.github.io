# -*- coding: utf-8 -*-
"""
tools_urgency_audit(#250, 설계안 §5 원칙 8 — 긴급도 팀 층 Python↔JS 대조) 오프라인 테스트.
표준 unittest, 네트워크·DB 없음. node가 PATH에 없으면 대조 테스트는 건너뛴다.

  - 케이스 파일 팀 규칙 + 비상 사본 공통 규칙 + 가짜 기사(NFD 제목·NFD 검색 요약·빈 값 포함)로
    실데이터·합성 대조 → 불일치 0
  - 대조가 의미 있었는지(판정 적중·human/rule/ai 출처·여러 팀 실장 줄이 실제로 나옴)
  - 대조기가 차이를 실제로 잡는지(결과 하나를 바꾸면 불일치 1)
  - 표류 보고가 꺼짐·다른 팀·등급 차이를 구분하는지
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
    rules = commons + T['rules']
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
    ]
    return news, teams, rules, rows


@unittest.skipUnless(NODE, 'node 없음 — JS 쪽 대조 건너뜀')
class TestUrgencyAuditParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        news, teams, rules, rows = _fixture()
        cls.live = tua.build_live(news, teams, rules, rows)
        many = [dict(n, id=f"{n['id']}_{k}") for k in range(6) for n in news]
        cls.syn, cls.info = tua.build_synthetic(many, teams, rules, seed=11, sample=len(many))
        cls.rep = tua.audit({'live': cls.live, 'synthetic': cls.syn, 'probe': tua.build_probe()}, node=NODE)

    def test_zero_mismatch(self):
        for name in tua.GATED:
            d = self.rep['datasets'][name]
            msg = '\n'.join(tua.describe(d['ds'], q, p, j) for _, q, p, j in d['mismatches'][:5])
            self.assertEqual(d['mismatches'], [], f'{name} 불일치:\n{msg}')
        self.assertEqual(tua.gated_mismatches(self.rep), 0)

    def test_live_counts_and_coverage(self):
        c = self.rep['datasets']['live']['counts']
        self.assertEqual((c['txt'], c['dec'], c['eff'], c['div']), (8, 16, 32, 16))   # 규칙 있는 팀 1·2, 실 둘
        src, hit, multi = tua._result_stats(self.rep, 'live')
        self.assertGreaterEqual(hit, 3)
        self.assertTrue({'common', 'human', 'rule', 'ai'} <= set(src), src)
        self.assertGreater(multi, 0)
        d = self.rep['datasets']['live']
        got = {tuple(q): p for q, p in zip(d['ds']['queries'], d['py'])}
        self.assertEqual(got[('dec', 0, 1)], {'level': '긴급', 'rule_id': 't1_min_up'})   # NFD 제목도 적중
        self.assertEqual(got[('eff', 1, 1)], {'level': '참고', 'source': 'rule'})         # 낡은 저장값 무시
        self.assertEqual(got[('eff', 4, 2)], {'level': '긴급', 'source': 'common'})       # 다른 팀 규칙 행

    def test_synthetic_coverage(self):
        c = self.rep['datasets']['synthetic']['counts']
        self.assertEqual(c['max'], 36)
        self.assertGreater(c['dec'], 0)
        src, hit, _ = tua._result_stats(self.rep, 'synthetic')
        self.assertGreater(hit, 0)
        self.assertTrue({'common', 'human', 'rule', 'ai'} <= set(src), src)
        self.assertEqual(len(self.info['variants']), 4)          # 팀이 넷이면 변형 넷
        self.assertTrue(self.info['off'])

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

    def test_drift_report(self):
        why, _, ne, _ = tua.drift_report(self.live)
        self.assertEqual(dict(why), {'등급 차이': 1, '규칙 꺼짐': 1, '다른 팀 규칙': 1})
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
