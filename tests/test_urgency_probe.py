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


Q2_LOCK = '731c934f0ed45926ceac1d4a9356ca3bd90bc8db0c73b16b38810bc3d13d028f'


class TestPrivacyQ2(unittest.TestCase):
    """개인정보 좁은 질문 Q2(판정 local_docs/긴급도_개인정보원칙_실측_261006/판정_좁은질문_261006.md §3) — 글자 그대로 잠근다."""
    ARTS = [{'title': '제목', 'content': '', 'screen_text': ''},
            {'title': '제목', 'content': '  본문  가 ', 'screen_text': ''},
            {'title': '제목', 'content': '', 'screen_text': ' 요약 '},
            {'title': '제목', 'content': '나' * 700, 'screen_text': '다' * 400}]

    def test_lock(self):
        s = (P.Q2_SYSTEM + '\n' + json.dumps(P.Q2_TOOL, ensure_ascii=False) + '\n' + str(P.Q2_MAX_TOKENS) + '\n'
             + '\n\x00'.join(P.q2_user_msg(a) for a in self.ARTS))
        self.assertEqual(hashlib.sha256(s.encode('utf-8')).hexdigest(), Q2_LOCK,
                         'Q2 system·tool·user·max_tokens가 바뀌었다 — 새 표본으로 다시 잰 뒤에만 지문을 고친다(판정 §5, 같은 표본에 두 번째 판 없음)')

    def test_tool_shape(self):
        t = P.Q2_TOOL
        self.assertEqual(list(t), ['name', 'description', 'strict', 'input_schema'])
        self.assertTrue(t['strict'])
        self.assertEqual(list(t['input_schema']['properties']), ['parties', 'topic', 'stage', 'scale', 'why'])
        self.assertEqual(t['input_schema']['required'], ['parties', 'topic', 'stage', 'scale', 'why'])
        self.assertNotIn('원칙', P.Q2_SYSTEM)              # 원칙 글은 프롬프트에서 뺐다 — 정책은 코드에
        self.assertEqual(P.PRIV_VARIANTS['Q2']['max_tokens'], 300)

    def test_user_msg(self):
        self.assertEqual([P.q2_user_msg(a) for a in self.ARTS[:3]],
                         ['제목: 제목', '제목: 제목\n본문: 본문 가', '제목: 제목\n검색 요약: 요약'])
        both = P.q2_user_msg(self.ARTS[3])
        self.assertEqual(both, '제목: 제목\n검색 요약: ' + '다' * 300 + '\n본문: ' + '나' * 600)
        short = {'title': '제목', 'content': '짧은 본문', 'screen_text': '요약 글'}   # 등급 호출과 달리 짧은 본문도 넣는다
        self.assertEqual(P.q2_user_msg(short), '제목: 제목\n검색 요약: 요약 글\n본문: 짧은 본문')
        self.assertEqual(P.user_msg(short), '제목: 제목\n요약: 요약 글')             # 등급 호출 입력은 그대로

    def test_telco_name(self):
        hit = ['SK텔레콤 유심', 'SKT 해킹', 'KT는 이날', 'KT 소액결제', '케이티', 'LG유플러스', 'LG 유플러스', 'LGU+', 'LG U+',
               '유플러스', '이통3사', '이통 3사', '통신3사', '통신 3사', '이동통신 3사', '에스케이텔레콤']
        miss = ['KTX 운행', 'KT&G 인삼', 'KTOA', '통신사 보안', '이통사', '알뜰폰', '유심 교체', '통신망 장애']
        for s in hit:
            self.assertTrue(P.TELCO_NAME.search(s), s)
        for s in miss:
            self.assertFalse(P.TELCO_NAME.search(s), s)

    def test_lower_rules(self):
        art = {'title': '티빙 보상 접수', 'screen_text': '요약'}
        tel_art = {'title': '티빙 보상', 'screen_text': '이동통신 3사 CISO도 증인'}
        o = lambda topic='특정 유출·해킹 사건', stage='뒷이야기', scale='규모 안 적힘', parties=('티빙',): \
            {'topic': topic, 'stage': stage, 'scale': scale, 'parties': list(parties), 'why': ''}
        self.assertTrue(P.privacy_lower(o(), art))
        self.assertFalse(P.privacy_lower(o(topic='법·제도·정책 일반'), art))
        self.assertFalse(P.privacy_lower(o(parties=('티빙', 'SK텔레콤')), art))      # parties에 통신사
        self.assertFalse(P.privacy_lower(o(), tel_art))                                # 안전장치: 요약에 이름
        self.assertTrue(P.privacy_lower(o(stage='사고 첫 보도', scale='그 미만'), art))
        self.assertFalse(P.privacy_lower(o(stage='사고 첫 보도', scale='수백만 명·계정 이상'), art))
        self.assertFalse(P.privacy_lower(o(stage='사고 첫 보도', scale='규모 안 적힘'), art))   # R-a: 규모 안 적힘은 유지
        self.assertFalse(P.privacy_lower(o(stage='처분 첫 보도', scale='그 미만'), art))        # 처분 첫 보도는 규모 무관 유지
        cases =[o(), o(topic='그 밖'), o(stage='사고 첫 보도', scale='규모 안 적힘'), o(parties=('KT',))]
        for c in cases:
            for ar in (art, tel_art):
                self.assertEqual(P.privacy_lower_rule(c, ar, 'R-a'), P.privacy_lower(c, ar))
        self.assertTrue(P.privacy_lower_rule(o(stage='사고 첫 보도', scale='규모 안 적힘'), art, 'R-b'))
        self.assertTrue(P.privacy_lower_rule(o(topic='그 밖'), art, 'R-c'))              # topic 관문 없음
        self.assertTrue(P.privacy_lower_rule(o(), tel_art, 'R-d'))                       # 안전장치 없음(parties만)
        self.assertFalse(P.privacy_lower_rule(o(parties=('통신 3사',)), art, 'R-d'))

    def test_parse_and_l1_unchanged(self):
        good = {'parties': ['티빙'], 'topic': '그 밖', 'stage': '해당 없음', 'scale': '해당 없음', 'why': 'x'}
        self.assertEqual(P._parse_q2(good)['parties'], ['티빙'])
        for k, v in (('parties', '티빙'), ('topic', '개인정보·해킹 사건'), ('stage', '후속'), ('scale', '대규모'), ('why', None)):
            self.assertIsNone(P._parse_q2({**good, k: v}), k)
        l1 = {'topic': '개인정보·해킹 사건', 'telecom': '통신 무관', 'stage': '후속'}
        self.assertTrue(P.privacy_lower_l1(l1))
        self.assertFalse(P.privacy_lower_l1({**l1, 'telecom': '통신 연결'}))
        self.assertEqual(P.parse_runs('Q2:ABCX, Q2:W ,L1:W'), [('Q2', 'ABCX'), ('Q2', 'W'), ('L1', 'W')])
        self.assertEqual(P.parse_runs(''), [('L1', 'ABCX')])


import hashlib       # noqa: E402
import unittest.mock  # noqa: E402

if __name__ == '__main__':
    unittest.main()
