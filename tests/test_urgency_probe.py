# -*- coding: utf-8 -*-
"""긴급도 판정 실측 도구(tools_urgency_probe.py, 순서표 4-2·4-3) — 네트워크 없이 고정 자료·문안 앵커·도구 정의를 본다.

  · 고정 자료는 측정 전에 고정한 정답표 그대로다(설계 local_docs/긴급도_판정구조_설계_261002.md 9-1 수치와 같아야 한다).
  · 문안 v0.1(V01_EDITS)·세 줄(R3_TEXTS)은 운영 기준문(crawler._URGENCY_CRITERIA)에서 한 곳씩만 맞아야 한다 — 기준문을 고치면
    이 시험이 멈춘다. 그때는 도구의 앵커를 새 글자에 맞추고 실측을 다시 한다(재지 않은 글자를 배포하지 않게).
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import crawler                      # noqa: E402
import tools_urgency_probe as P     # noqa: E402


class TestFixture(unittest.TestCase):
    def setUp(self):
        self.fx = P.load_fixture()

    def test_counts_match_frozen_gold(self):
        s = self.fx['sets']
        cnt = lambda rows, k: {v: sum(1 for r in rows if r[k] == v) for v in {r[k] for r in rows}}
        self.assertEqual(len(s['A']), 173)
        self.assertEqual(cnt(s['A'], 'gold'), {'U': 66, 'N': 95, 'B': 12})
        self.assertEqual(len(s['B']), 60)
        self.assertEqual(cnt(s['C'], 'gold'), {'U': 37, 'N': 31, 'B': 7})
        self.assertEqual(sum(r['lowered'] for r in s['C']), 9)
        self.assertEqual(cnt(s['D'], 'common'), {'U': 7, 'N': 84, 'B': 4})
        self.assertEqual(cnt(s['D'], 'team'), {'U': 18, 'N': 68, 'B': 9})
        self.assertEqual(cnt(s['D'], 'sent'), {'Y': 12, 'N': 75, 'B': 8})
        self.assertEqual(len(self.fx['synth']), 8)
        self.assertEqual(self.fx['feedback_moves']['T1'], [49, 50, 51, 52, 53])

    def test_no_article_bodies(self):
        # 본문은 실행 때 DB에서 — 고정 자료에는 id·제목·정답만(합성 사례만 본문을 갖는다)
        for k in ('A', 'B', 'C', 'D'):
            for r in self.fx['sets'][k]:
                self.assertNotIn('body', r)
                self.assertNotIn('content', r)


class TestRubricAnchors(unittest.TestCase):
    def test_r3_texts_each_once(self):
        cur = crawler._URGENCY_CRITERIA
        for t in P.R3_TEXTS:
            self.assertEqual(cur.count(t), 1)
        self.assertEqual(len(P.criteria_of(cur, 'R3')), len(cur) - sum(len(t) for t in P.R3_TEXTS))

    def test_v01_edits_each_once(self):
        cur = crawler._URGENCY_CRITERIA
        for old, _ in P.V01_EDITS:
            self.assertEqual(cur.count(old), 1, old[:40])
        v = P.criteria_of(cur, 'V01')
        self.assertIn('국내 이동통신 주파수 제도를 정부가 정한 기사', v)
        self.assertNotIn('단계라도 즉시대응이다', v)
        for t in P.R3_TEXTS:                       # 잠긴 줄(#264-보론)은 v0.1에서도 글자 그대로
            self.assertIn(t, v)

    def test_intro_lines(self):
        intro = crawler._URGENCY_SYSTEM[:len(crawler._URGENCY_SYSTEM) - len(crawler._URGENCY_CRITERIA)]
        self.assertIn(P.WORD_LINE, intro)
        self.assertIn(P.HEAD_OLD, intro)
        self.assertIn(P.TOOL_LINE, P.intro_of(intro, 'cur', 'sgb'))
        self.assertIn(P.HEAD_V01, P.intro_of(intro, 'V01', 'sgb'))


class TestToolAndCaps(unittest.TestCase):
    def test_tool_orders(self):
        self.assertEqual(list(P.urgency_tool('sgb')['input_schema']['properties']), ['scope', 'grade', 'basis'])
        self.assertEqual(list(P.urgency_tool('gsb')['input_schema']['properties']), ['grade', 'scope', 'basis'])
        t = P.urgency_tool('sgb')
        self.assertTrue(t['strict'])
        self.assertFalse(t['input_schema']['additionalProperties'])
        self.assertEqual(t['input_schema']['properties']['basis']['enum'][-1], '없음')

    def test_no_strict_variant_and_w2_line(self):
        self.assertNotIn('strict', P.urgency_tool('sgb-ns'))
        self.assertEqual(list(P.urgency_tool('sgb-ns')['input_schema']['properties']), ['scope', 'grade', 'basis'])
        intro = crawler._URGENCY_SYSTEM[:len(crawler._URGENCY_SYSTEM) - len(crawler._URGENCY_CRITERIA)]
        self.assertIn(P.W2_LINE, P.intro_of(intro, 'cur', None, 'w2'))
        self.assertNotIn(P.WORD_LINE, P.intro_of(intro, 'cur', None, 'w2'))

    def test_w2_parse(self):
        class B:
            def __init__(self, t):
                self.type, self.text = 'text', t

        class Resp:
            def __init__(self, t):
                self.content = [B(t)]
        ok = P.parse_response(Resp('즉시대응\n타영역'), None, 'w2')
        self.assertEqual((ok['grade'], ok['scope'], ok['parse']), ('긴급', '타영역', 'ok'))
        bad = P.parse_response(Resp('금주검토\n주파수'), None, 'w2')    # 둘째 줄이 영역 낱말이 아니면 해석 실패로 센다
        self.assertEqual((bad['grade'], bad['scope'], bad['parse']), ('보통', None, 'fail'))

    def test_user_msg_matches_crawler(self):
        # 실측 입력 = 운영 입력(#267-보론 짧은 본문 규칙 포함). legacy는 보완 전 기준선 전용
        self.assertEqual(P.SHORT_BODY, crawler.URGENCY_SHORT_BODY)
        menu = '최종편집 2026-09-28 16:49 (월) 로그인 회원가입 전체보기 산업 ICT·AI'
        long_body = '가' * 700
        for content, snip in ((menu, '요약 글'), (menu, ''), (long_body, '요약 글'), ('', '요약 글'), ('', ''), ('  짧은  본문 ', '요약')):
            art = {'title': '제목', 'content': content, 'screen_text': snip}
            self.assertEqual(P.user_msg(art), crawler._urgency_user_msg('제목', content, snip), (content[:10], snip))
        self.assertEqual(crawler._urgency_user_msg('제목', menu, '요약 글'), '제목: 제목\n요약: 요약 글')
        self.assertEqual(crawler._urgency_user_msg('제목', menu, ''), f'제목: 제목\n본문: {menu}')   # 요약이 없으면 짧은 본문이라도 쓴다
        self.assertIn('본문:', P.user_msg({'title': '제목', 'content': menu, 'screen_text': '요약 글'}, 'legacy'))

    def test_caps(self):
        r = lambda s, g, b='없음': {'scope': s, 'grade': g, 'basis': b}
        self.assertEqual(P.cap(r('타영역', '긴급'), 'raw'), '긴급')
        self.assertEqual(P.cap(r('타영역', '긴급'), 'R1'), '보통')
        self.assertEqual(P.cap(r('타영역', '참고'), 'R1'), '참고')       # 긴급만 막는다
        self.assertEqual(P.cap(r('언저리', '긴급', 'SKT 당사자'), 'R1'), '긴급')
        self.assertEqual(P.cap(r('언저리', '긴급', 'SKT 당사자'), 'R2'), '보통')
        self.assertEqual(P.cap(r('언저리', '긴급', '대규모 유출'), 'R2'), '긴급')
        self.assertEqual(P.cap(r('통신', '긴급', '없음'), 'R2'), '긴급')

    def test_fixed_block_matches_crawler_shape(self):
        rows = [{'id': i, 'title': f'기사 {i}', 'user_importance': g, 'news_id': f'n{i}'}
                for i, g in enumerate(['긴급'] * 14 + ['보통'] * 3)]
        block, nids = P.fixed_block(rows)
        self.assertEqual(block.count('→ 즉시대응'), 12)
        self.assertEqual(len(nids), 15)
        with unittest.mock.patch.object(crawler, '_load_feedback_rows', lambda: rows), \
                unittest.mock.patch.object(crawler, '_get_distilled_rules', lambda: ''), \
                unittest.mock.patch.object(crawler, '_feedback_fixed_cache', None):
            self.assertEqual(crawler._feedback_fixed_block(), block)


import unittest.mock  # noqa: E402

if __name__ == '__main__':
    unittest.main()
