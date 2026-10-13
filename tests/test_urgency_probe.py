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


Q3_LOCK = '41d892ee54e29a84dbce3a0d145739acde09ede262c29004a59d4aaac7a13303'


class TestPrivacyQ3(unittest.TestCase):
    """개인정보 좁은 질문 Q3(판정 local_docs/긴급도_개인정보원칙_실측_261006/판정_좁은질문_261006.md §10 v2 + 운영자 결정 ③④⑥) —
    문안·입력·질문 낱말·알뜰폰 목록을 글자 그대로 잠그고, 도구·parties 설명이 Q2와 바이트 같은지, 내림 규칙 표와 깨진 본문 두 비율을 본다."""
    LONG = '가나다라마' * 260                       # 1,300자
    ARTS = [{'title': '제목', 'content': '', 'screen_text': ''},
            {'title': '제목', 'content': '  본문  가 ', 'screen_text': ''},
            {'title': '제목', 'content': '', 'screen_text': ' 요약 '},
            {'title': '제목', 'content': LONG, 'screen_text': '다' * 400},
            {'title': '제목', 'content': 'Ã¬Â¹Â´Ã¬ÂÂ¸ ' * 40, 'screen_text': '요약 글'}]     # 깨진 본문

    def test_lock(self):
        s = (P.Q3_SYSTEM + '\n' + json.dumps(P.PRIV_VARIANTS['Q3']['tool'], ensure_ascii=False) + '\n'
             + str(P.PRIV_VARIANTS['Q3']['max_tokens']) + '\n' + '\n\x00'.join(P.q3_user_msg(a) for a in self.ARTS)
             + '\n' + P.PRIV_WORDS_Q3.pattern + '\n' + P.MVNO_NAME.pattern)
        self.assertEqual(hashlib.sha256(s.encode('utf-8')).hexdigest(), Q3_LOCK,
                         'Q3 system·tool·user·max_tokens·질문 낱말·알뜰폰 목록이 바뀌었다 — 판정 §10-2 글자 그대로여야 하고, '
                         '세 번째 표본(W3)을 연 뒤에 고친 판은 네 번째 표본으로만 잰다(§10-4)')

    def test_tool_and_parties_same_as_q2(self):
        self.assertIs(P.PRIV_VARIANTS['Q3']['tool'], P.Q2_TOOL)                   # 도구는 바이트 동일(출력 형식은 눈금, #267)
        self.assertIs(P.PRIV_VARIANTS['Q2w']['tool'], P.Q2_TOOL)
        self.assertEqual(P.PRIV_VARIANTS['Q3']['max_tokens'], P.Q2_MAX_TOKENS)
        self.assertEqual(P.PRIV_VARIANTS['Q2w']['system'], P.Q2_SYSTEM)           # 분리 팔 = Q2 글 + Q3 입력
        self.assertIs(P.PRIV_VARIANTS['Q2w']['user'], P.q3_user_msg)
        q2, q3 = P.Q2_SYSTEM.split('\n'), P.Q3_SYSTEM.split('\n')
        self.assertEqual(q2[:8], q3[:8])                                         # 첫 세 줄 · [칸 채우는 기준] · parties 세 줄
        self.assertTrue(q3[5].startswith('· parties(당사자)'))
        self.assertEqual(q2[-2:], q3[-2:])                                       # why 줄 + 끝 줄바꿈
        self.assertTrue(P.Q3_SYSTEM.endswith('· why: 근거 한 줄(40자 안).\n'))
        flat = P.Q3_SYSTEM.replace('\n  ', '')                               # 운영자 결정 ④·⑥과 stage 설명이 문안에 있다
        for s in ('제재·과징금·조사 권한을 강화하겠다고 밝힌 방침', '경찰·검찰의 수사 착수·입건·압수수색·기소는 처분이 아니다', '100만 명·계정 이상'):
            self.assertIn(s, flat)
        self.assertNotIn('원칙', P.Q3_SYSTEM)

    def test_user_msg_and_input_text(self):
        self.assertEqual([P.q3_user_msg(a) for a in self.ARTS[:3]],
                         ['제목: 제목', '제목: 제목\n본문: 본문 가', '제목: 제목\n검색 요약: 요약'])
        self.assertEqual(P.q3_user_msg(self.ARTS[3]), '제목: 제목\n검색 요약: ' + '다' * 300 + '\n본문: ' + self.LONG[:1200])
        self.assertEqual(P.q3_user_msg(self.ARTS[4]), '제목: 제목\n검색 요약: 요약 글')       # 깨진 본문은 없는 것으로
        short = {'title': '제목', 'content': '짧은 본문', 'screen_text': '요약 글'}            # 짧은 본문도 넣는다
        self.assertEqual(P.q3_user_msg(short), P.q2_user_msg(short))
        self.assertEqual(P.priv_key('Q2w', P.q3_user_msg(short)), P.priv_key('Q2', P.q2_user_msg(short)))   # 같은 글 = 같은 호출
        for art in self.ARTS + [short]:                                          # S가 보는 글 = 모델이 본 글(머리말 빼고)
            self.assertEqual(P.ws(P.q3_input_text(art)),
                             P.ws(P.q3_user_msg(art).replace('제목: ', '').replace('검색 요약: ', '').replace('본문: ', '')))
        self.assertEqual(P.user_msg(short), '제목: 제목\n요약: 요약 글')                     # 등급 호출 입력은 그대로

    def test_broken_body(self):
        self.assertFalse(P.broken_body(''))
        self.assertFalse(P.broken_body('과기정통부·KISA는 이날 해킹 사고 조사 결과를 발표했다'))
        self.assertTrue(P.broken_body('Ã¬Â¹Â´Ã¬ÂÂ¸ Ã«Â³Â´Ã¬ÂÂ'))
        self.assertTrue(P.broken_body('Login Sign up Copyright All rights reserved'))      # 한글 음절 0
        self.assertTrue(P.broken_body('ÿ�' + '가' * 2))                               # 대체 문자·Latin-1
        # 경계: 깨진 글자 비율은 0.3을 「넘으면」, 한글 비율은 0.2에 「못 미치면」
        self.assertFalse(P.broken_body('é' * 3 + '가' * 7))                                # 0.3 → 아님
        self.assertTrue(P.broken_body('é' * 4 + '가' * 6))                                 # 0.4
        self.assertFalse(P.broken_body('가' * 2 + 'a' * 8))                                # 한글 0.2 → 아님
        self.assertTrue(P.broken_body('가' + 'a' * 9))                                     # 0.1
        self.assertTrue(P.broken_body('Ｓ' * 4 + '가' * 6))                                # 전각 꼴
        art = {'title': '제목', 'content': '가' * 1200 + 'é' * 2000, 'screen_text': ''}       # 앞 1,200자만 잰다
        self.assertEqual(P.q3_body(art), '가' * 1200)

    def test_words_and_mvno(self):
        only_fine = {'title': '인앱결제 과징금 부과 의결 전망', 'screen_text': ''}
        self.assertTrue(P.privacy_hit(only_fine))
        self.assertFalse(P.privacy_hit_q3(only_fine))                            # 「과징금」만은 질문 밖
        self.assertTrue(P.privacy_hit_q3({'title': '티빙 개인정보 유출', 'screen_text': ''}))
        self.assertTrue(P.privacy_hit_q3({'title': '제목', 'screen_text': '금융권 해킹 수사'}))   # 검색 요약도 본다
        self.assertEqual(P.PRIV_WORDS.pattern.replace('|과징금', ''), P.PRIV_WORDS_Q3.pattern)
        for s in ('알뜰폰', '퍼스트모바일', 'KT M모바일', 'KT엠모바일', 'SK텔링크', '세븐모바일', '미디어로그', 'LG헬로비전', '헬로모바일',
                  'U+유모바일', 'KB리브모바일', '리브엠', '토스모바일', '프리텔레콤', '이야기모바일', '스마텔'):
            self.assertTrue(P.MVNO_NAME.search(s), s)
        for s in ('SK텔레콤', '모바일 뱅킹', '티빙', '이동통신사'):
            self.assertFalse(P.MVNO_NAME.search(s), s)
        for s in ('통신사', '이동통신사', '이통사', '통신업계', '한국통신사업자연합회', 'KTOA'):
            self.assertTrue(P.TELCO_BROAD.search(s), s)

    def test_rule_table(self):
        far = '가' * 700 + ' SK텔레콤 증인 ' + '나' * 100                    # 통신사 이름이 본문 600~1,200자 사이
        base = {'title': '금융권 해킹 국감', 'content': '가' * 300, 'screen_text': '요약'}
        arts = {'plain': base, 'far': {**base, 'content': far}, 'summ': {**base, 'screen_text': 'KT 소액결제'},
                'beyond': {**base, 'content': '가' * 1250 + ' KT '}}           # 1,200자 밖 — 입력 글이 아니다
        o = lambda topic='특정 유출·해킹 사건', stage='뒷이야기', scale='규모 안 적힘', parties=('신한은행',): \
            {'topic': topic, 'stage': stage, 'scale': scale, 'parties': list(parties), 'why': ''}
        rules = ('Q3', 'N0', 'R-a3', 'M0', 'M+', 'Q2w')
        table = [  # (출력, 기사) → Q3 · N0 · R-a3 · M0 · M+ · Q2w(=Q2 코드 R-b)
            (o(topic='법·제도·정책 일반'), 'plain', (0, 0, 0, 0, 0, 0)),
            (o(topic='그 밖'), 'plain', (0, 0, 0, 0, 0, 0)),
            (o(), 'plain', (1, 1, 1, 1, 1, 1)),
            (o(), 'far', (0, 1, 0, 0, 0, 1)),                                   # S가 막음 — Q2식 안전장치(N0·Q2w)는 못 봄
            (o(), 'summ', (0, 0, 0, 0, 0, 0)),
            (o(), 'beyond', (1, 1, 1, 1, 1, 1)),
            (o(parties=('퍼스트모바일',)), 'plain', (0, 0, 0, 1, 0, 1)),           # A3: 알뜰폰 사업자는 parties로
            (o(parties=('이동통신사',)), 'plain', (1, 1, 1, 1, 0, 1)),             # M+만 넓은 낱말
            (o(parties=('SKT',)), 'plain', (1, 0, 1, 1, 1, 0)),                    # 입력 글에 없는 이름 — S는 입력 글만 본다(§10-2-4)
            (o(stage='사고 첫 보도', scale='규모 안 적힘'), 'plain', (1, 1, 0, 1, 1, 1)),   # R-b · R-a3만 유지
            (o(stage='사고 첫 보도', scale='그 미만'), 'plain', (1, 1, 1, 1, 1, 1)),
            (o(stage='사고 첫 보도', scale='수백만 명·계정 이상'), 'plain', (0, 0, 0, 0, 0, 0)),
            (o(stage='처분 첫 보도', scale='그 미만'), 'plain', (0, 0, 0, 0, 0, 0)),   # 처분 첫 보도는 규모 무관 유지
            (o(stage='해당 없음', scale='해당 없음'), 'plain', (0, 0, 0, 0, 0, 0)),
        ]
        for out, ak, want in table:
            art = arts[ak]
            got = tuple(int(P.PRIV_VARIANTS['Q2w']['lower'](out, art) if r == 'Q2w' else P.privacy_lower_q3_rule(out, art, r))
                        for r in rules)
            self.assertEqual(got, want, (out['topic'], out['stage'], out['scale'], out['parties'], ak))
            self.assertEqual(P.privacy_lower_q3(out, art), P.privacy_lower_q3_rule(out, art, 'Q3'))
            self.assertEqual(P.PRIV_VARIANTS['Q3']['lower'](out, art), bool(want[0]))
        broken = {**base, 'content': 'Ã¬Â¹Â´ SK텔레콤 ' * 30}                    # 깨진 본문은 입력 글이 아니다 — S도 못 본다
        self.assertTrue(P.privacy_lower_q3(o(), broken))

    def test_runs_and_sets(self):
        self.assertEqual(P.set_tokens('ABCX'), ['A', 'B', 'C', 'X'])
        self.assertEqual(P.set_tokens('W3'), ['W3'])
        self.assertEqual(P.set_tokens('W'), ['W'])
        self.assertEqual(P.parse_runs('Q3:W3,Q2:W3,Q2w:W3,Q3:W,Q3:ABCX'),
                         [('Q3', 'W3'), ('Q2', 'W3'), ('Q2w', 'W3'), ('Q3', 'W'), ('Q3', 'ABCX')])
        self.assertEqual(P.SAMPLE_WINDOWS['W3'], ('2026-10-13T00:00', '2026-10-20T00:00'))
        self.assertEqual(set(P.P4_EXPECTED) & set(P.P4W_NAMED), set())


import hashlib       # noqa: E402
import unittest.mock  # noqa: E402

if __name__ == '__main__':
    unittest.main()
