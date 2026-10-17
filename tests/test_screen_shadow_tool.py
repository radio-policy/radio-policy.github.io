# -*- coding: utf-8 -*-
"""선별 그림자 읽기 도구 tools_screen_shadow.py(#318)의 순수 함수 — 표준 unittest, 네트워크 0.

  - 판정 규칙 1~3이 crawler._SCREEN_RULES와 글자까지 같고, 기준문 지문 식이 crawler._screen_hash와 같다
  - 층화 표본: 전체 ≤ 상한이면 전부(가중 1), 넘으면 방향마다 절반·남는 자리 넘김, 가중 = 모집단 ÷ 표본, 씨앗 고정이면 같은 결과
  - 합치기: 합의·갈림, bid가 다르거나 값이 관련/무관 밖이면 오류
  - 채점: 방향 × 정답 → 놓침·과잉(가중), 통과 기준 Ⓐ~Ⓓ
  - 요약: 비교 배치만 분모, 둘 다 관련 수, 같은 기사 중복 제거
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import crawler  # noqa: E402
import tools_screen_shadow as T  # noqa: E402


def _rel(i, prod):
    return {'id': i, 'url': f'u{i}', 'title': f't{i}', 'summary': 's', 'prod_relevant': prod, 'shadow_relevant': not prod}


class TestToolMatchesCrawler(unittest.TestCase):

    def test_rules_and_hash(self):
        for line in T.JUDGE_RULES.strip('\n').split('\n'):
            self.assertIn(line + '\n', crawler._SCREEN_RULES)
        for s in ('', '기준문  둘째\n줄 ', 'abc'):
            self.assertEqual(T.screen_hash(s), crawler._screen_hash(s))

    def test_prompt_has_criteria_and_rules(self):
        p = T.judge_prompt(' 기준 본문 ')
        self.assertIn('기준 본문', p)
        self.assertIn(T.JUDGE_RULES, p)


class TestSample(unittest.TestCase):

    def test_all_when_small(self):
        rel = [_rel(i, i % 3 == 0) for i in range(10)]
        got = T.sample(rel, 1, 400)
        self.assertEqual(len(got), 10)
        self.assertEqual({w for _, _, w in got}, {1.0})

    def test_stratified_and_seeded(self):
        rel = [_rel(i, True) for i in range(300)] + [_rel(1000 + i, False) for i in range(50)]
        got = T.sample(rel, 7, 200)
        n = {d: sum(1 for _, dd, _ in got if dd == d) for d in 'AB'}
        self.assertEqual(n, {'A': 150, 'B': 50})            # B가 50뿐이라 남는 50자리가 A로
        w = {d: next(w for _, dd, w in got if dd == d) for d in 'AB'}
        self.assertAlmostEqual(w['A'], 300 / 150)
        self.assertAlmostEqual(w['B'], 1.0)
        self.assertEqual([r['id'] for r, _, _ in got], [r['id'] for r, _, _ in T.sample(rel, 7, 200)])
        self.assertNotEqual([r['id'] for r, _, _ in got], [r['id'] for r, _, _ in T.sample(rel, 8, 200)])

    def test_dedupe(self):
        rows = [_rel(1, True), dict(_rel(2, True), url='u1'), {'id': 3, 'url': None, 'title': 'x', 'prod_relevant': False},
                {'id': 4, 'url': None, 'title': 'x', 'prod_relevant': False}]
        self.assertEqual([r['id'] for r in T.dedupe(rows)], [1, 3])


class TestMergeScore(unittest.TestCase):

    def test_merge(self):
        agree, split = T.merge({'s1': '관련', 's2': {'v': '무관', 'why': 'x'}}, {'s1': {'v': '관련'}, 's2': '관련'})
        self.assertEqual((agree, split), ({'s1': '관련'}, ['s2']))
        with self.assertRaises(ValueError):
            T.merge({'s1': '관련'}, {'s2': '관련'})
        with self.assertRaises(ValueError):
            T.merge({'s1': '애매'}, {'s1': '관련'})

    def test_score(self):
        items = {'a1': {'dir': 'A', 'w': 2.0}, 'a2': {'dir': 'A', 'w': 2.0},
                 'b1': {'dir': 'B', 'w': 1.0}, 'b2': {'dir': 'B', 'w': 1.0}, 'b3': {'dir': 'B', 'w': 1.0}}
        gold = {'a1': '관련', 'a2': '무관', 'b1': '관련', 'b2': '관련', 'b3': '무관'}
        s = {'n_prod': 100, 'refusal_rate': 0.01, 'shadow_fail_rate': 0.02, 'prod_fail_rate': 0.015}
        r = T.score(items, gold, s)
        self.assertEqual(r['est'], {'miss55': 2.0, 'over45': 2.0, 'miss45': 2.0, 'over55': 1.0})
        self.assertEqual(r['crit'], {'A_miss': True, 'B_over': True, 'C_refusal': True, 'D_fail': True})
        self.assertTrue(r['pass'])
        r = T.score(items, dict(gold, a2='관련'), dict(s, refusal_rate=0.03))   # 5.5 놓침 4 > 4.5 놓침 2
        self.assertEqual(r['crit']['A_miss'], False)
        self.assertEqual(r['crit']['C_refusal'], False)
        self.assertFalse(r['pass'])
        r = T.score(items, gold, dict(s, n_prod=10))                          # 과잉 증가 −1 ≤ 0.5 → 통과
        self.assertTrue(r['crit']['B_over'])
        r = T.score({'b1': {'dir': 'B', 'w': 30.0}}, {'b1': '무관'}, s)          # 과잉 증가 30 > 5
        self.assertFalse(r['crit']['B_over'])
        with self.assertRaises(ValueError):
            T.score(items, {'a1': '관련'}, s)


class TestStats(unittest.TestCase):

    def test_stats(self):
        heads = [
            {'id': 1, 'created_at': '2026-10-17T03:00:00+00:00', 'status': 'ok', 'prod_ok': True, 'ms': 1000,
             'n_items': 10, 'n_prod': 4, 'n_shadow': 5, 'n_diff': 3, 'criteria_hash': 'h'},
            {'id': 2, 'created_at': '2026-10-17T03:10:00+00:00', 'status': 'refusal', 'prod_ok': True, 'ms': 500,
             'n_items': 8, 'n_prod': 2, 'n_shadow': None, 'n_diff': None, 'criteria_hash': 'h'},
            {'id': 3, 'created_at': '2026-10-17T03:20:00+00:00', 'status': 'ok', 'prod_ok': False, 'ms': 900,
             'n_items': 5, 'n_prod': None, 'n_shadow': 2, 'n_diff': None, 'criteria_hash': 'h'},
            {'id': 4, 'created_at': '2026-10-17T03:30:00+00:00', 'status': 'timeout', 'prod_ok': True, 'ms': None,
             'n_items': 5, 'n_prod': 1, 'n_shadow': None, 'n_diff': None, 'criteria_hash': 'h'},
        ]
        rel = [_rel(1, True), _rel(2, False), dict(_rel(3, False), url='u2')]
        tags = [{'prod_tags': ['spectrum'], 'shadow_tags': ['spectrum', 'ai']}]
        s = T.stats(heads, rel, tags)
        self.assertEqual((s['compared'], s['n_items'], s['n_prod'], s['n_diff']), (1, 10, 4, 3))
        self.assertAlmostEqual(s['agree'], 0.7)
        self.assertEqual(s['both_relevant'], 3)                 # (4 + 5 − 3) / 2
        self.assertEqual(s['dir'], {'A': 1, 'B': 1})            # u2 중복 하나 빠짐
        self.assertEqual((s['refusal_rate'], s['shadow_fail_rate'], s['prod_fail_rate']), (0.25, 0.25, 0.25))
        self.assertEqual(s['tag_moves'], {'ai 5.5만': 1})
        self.assertEqual(s['criteria_hashes'], ['h'])


if __name__ == '__main__':
    unittest.main()
