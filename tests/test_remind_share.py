# -*- coding: utf-8 -*-
"""#256 (2026-09-29) — 리마인드 문턱(REMIND_MIN_SHARE)·사건 비율 함수·유사 사례 낱말 조사 떼기. 표준 unittest, 네트워크 0."""
import inspect
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import crawler  # noqa: E402

KST = timezone(timedelta(hours=9))


def _rows(n_urg, n_other, title='하나금융, SKT·삼성전자와 5G 특화망 오피스 구축'):
    rows = [{'title': title, 'url': f'u{i}', 'urgency': '긴급'} for i in range(n_urg)]
    rows += [{'title': title, 'url': f'n{i}', 'urgency': '보통'} for i in range(n_other)]
    rows.append({'title': '방미통위, 불법 위치추적 사업자 수사 의뢰', 'url': 'x', 'urgency': '긴급'})   # 다른 사건
    return rows


class EventShare(unittest.TestCase):
    def test_counts_same_event_only(self):
        share = crawler._event_share_fn(_rows(2, 8), lambda r: r['urgency'] == '긴급')
        self.assertEqual(share('하나금융, SKT·삼성전자와 5G 특화망 오피스 구축', "하나금융, 금융권 첫 '5G 스마트 오피스' 구축"), (2, 10))

    def test_matched_prior_title_also_defines_event(self):
        rows = [{'title': '티빙 3954만 계정 유출…보안투자 4배 확대·고객 보상', 'url': 'a', 'urgency': '긴급'},
                {'title': '티빙 3954만 계정 유출…문제는 내부 통제였다', 'url': 'b', 'urgency': '긴급'}]
        share = crawler._event_share_fn(rows, lambda r: r['urgency'] == '긴급')
        # 후보 제목은 겹침이 적어도 걸린 기보도 제목과 3개 이상 겹치면 같은 사건으로 센다
        self.assertEqual(share('최주희 대표 사과', '티빙 3954만 계정 유출…보안투자 4배 확대'), (2, 2))

    def test_empty_rows_zero(self):
        self.assertEqual(crawler._event_share_fn([], lambda r: True)('a b c', 'd'), (0, 0))


def _core(items, prior_title, age_h, remind_share, group_fn=None):
    """키워드 경로 리마인드 상황 — 기보도 1건이 age_h시간 전 대표."""
    from news_dedup import extract_keywords
    prior = [{'title': prior_title, 'kw': extract_keywords(prior_title)}]
    prior_at = {prior_title: (datetime.now(KST) - timedelta(hours=age_h)).isoformat()}
    return crawler._suppress_core(items, prior, prior_at, {}, group_fn, log=None, remind_share=remind_share)


class RemindGate(unittest.TestCase):
    NEW = '하나금융, SKT·삼성전자와 5G 특화망 오피스 구축'
    OLD = "하나금융, 금융권 첫 '5G 특화망 스마트 오피스' 구축"

    def test_low_share_holds(self):
        reps, sup, rem, merged = _core([{'title': self.NEW, 'url': 'n'}], self.OLD, 30, lambda a, b: (30, 170))
        self.assertEqual(reps, [])
        self.assertEqual(rem, [])
        self.assertEqual(len(sup), 1)
        self.assertEqual(sup[0]['shared_keywords'], '[리마인드보류] 30/170')
        self.assertEqual(sup[0]['matched_title'], self.OLD)
        self.assertFalse(sup[0]['shared_keywords'].startswith('[리마인드]'))   # 사슬·사내 다리가 '미발송'으로 읽는 접두

    def test_high_share_passes_as_before(self):
        reps, sup, rem, merged = _core([{'title': self.NEW, 'url': 'n'}], self.OLD, 30, lambda a, b: (8, 10))
        self.assertEqual(len(reps), 1)
        self.assertEqual(reps[0].get('_remind'), '2일째')
        self.assertEqual(rem[0]['shared_keywords'], '[리마인드] 2일째')
        self.assertEqual(sup, [])

    def test_exactly_half_passes(self):
        reps, _s, rem, _m = _core([{'title': self.NEW, 'url': 'n'}], self.OLD, 30, lambda a, b: (1, 2))
        self.assertEqual(len(reps), 1)

    def test_no_share_fn_unchanged(self):
        reps, sup, rem, _m = _core([{'title': self.NEW, 'url': 'n'}], self.OLD, 30, None)
        self.assertEqual(len(reps), 1)
        self.assertEqual(rem[0]['shared_keywords'], '[리마인드] 2일째')

    def test_share_error_or_empty_event_passes(self):
        def boom(a, b):
            raise RuntimeError('x')
        self.assertEqual(len(_core([{'title': self.NEW, 'url': 'n'}], self.OLD, 30, boom)[0]), 1)
        self.assertEqual(len(_core([{'title': self.NEW, 'url': 'n'}], self.OLD, 30, lambda a, b: (0, 0))[0]), 1)

    def test_fresh_followup_still_suppressed_not_reminded(self):
        # 대표가 24시간 안이면 문턱과 무관하게 종전대로 억제
        reps, sup, rem, _m = _core([{'title': self.NEW, 'url': 'n'}], self.OLD, 5, lambda a, b: (9, 10))
        self.assertEqual(reps, [])
        self.assertEqual(rem, [])
        self.assertFalse(sup[0]['shared_keywords'].startswith('['))

    def test_semantic_path_gate(self):
        # 키워드 3개 미만이라 ①은 못 잡고 ①-2 의미 판정이 기보도와 묶는 경우에도 문턱이 걸린다
        new = {'title': '금융권 오피스 무선화…청라 사옥 사례', 'url': 'n'}
        old = "하나금융, 금융권 첫 '5G 특화망 스마트 오피스' 구축"
        from news_dedup import extract_keywords
        prior = [{'title': old, 'kw': extract_keywords(old)}]
        prior_at = {old: (datetime.now(KST) - timedelta(hours=30)).isoformat()}
        self.assertLess(len(extract_keywords(new['title']) & prior[0]['kw']), 3)
        # #263부터 ①-2는 재보도 대조(match_fn — 새 기사마다 '이미 알린 기사' 번호)로 돈다. 사슬이 비었으니 기보도는 알림 대표다.
        reps, sup, rem, _m = crawler._suppress_core([new], prior, prior_at, {}, None, log=None,
                                                    remind_share=lambda a, b: (30, 170), match_fn=lambda n, o: [0])
        self.assertEqual(reps, [])
        self.assertEqual(sup[0]['shared_keywords'], '[리마인드보류] 30/170')
        reps2, _s, rem2, _m = crawler._suppress_core([dict(new)], prior, prior_at, {}, None, log=None,
                                                     remind_share=lambda a, b: (9, 10), match_fn=lambda n, o: [0])
        self.assertEqual(len(reps2), 1)
        self.assertEqual(rem2[0]['shared_keywords'], '[리마인드] 2일째')

    def test_wiring(self):
        self.assertEqual(crawler.REMIND_MIN_SHARE, 0.5)
        self.assertEqual(crawler.REMIND_HOLD_MARK, '[리마인드보류]')
        self.assertIn('remind_share=remind_share', inspect.getsource(crawler.suppress_repeat_alerts))
        self.assertIn("_event_share_fn(_all, lambda r: r.get('urgency') == '긴급')", inspect.getsource(crawler.suppress_repeat_alerts))
        self.assertIn('remind_share=remind_share', inspect.getsource(crawler._aud_compute))
        self.assertIn('_event_share_fn(window', inspect.getsource(crawler._aud_compute))


class FeedbackTokens(unittest.TestCase):
    def test_josa_stripped(self):
        t = crawler._fb_tokens("복지위 국감도 '플랫폼' 이슈…강남언니·구글·닥터나우 등 증인 신청")
        self.assertIn('국감', t)
        self.assertNotIn('국감도', t)
        self.assertIn('강남언니', t)
        t2 = crawler._fb_tokens('하나금융, SKT·삼성전자와 5G 특화망 오피스 구축')
        self.assertIn('삼성전자', t2)
        self.assertIn('skt', t2)
        self.assertIn('5g', t2)

    def test_short_remainder_keeps_original(self):
        self.assertIn('나는', crawler._fb_tokens('나는'))          # '나' 1자 → 원형 유지

    def _similar(self, rows, title):
        saved = (crawler._feedback_rows_cache, crawler._feedback_fixed_cache)
        try:
            crawler._feedback_rows_cache = rows
            crawler._feedback_fixed_cache = '(고정 블록 없음)'
            return crawler._feedback_similar_block(title)
        finally:
            crawler._feedback_rows_cache, crawler._feedback_fixed_cache = saved

    def test_similar_block_attaches_near_duplicate_title(self):
        # #264: 같은 사건의 후속 보도(제목이 거의 같음)에는 예전 수정이 따라붙는다 — 조사 떼기(#256)도 그대로 쓴다
        rows = [{'title': "창원소방본부, 복합건축물 화재 대비 '3분기 긴급구조통제단 불시훈련'...", 'user_importance': '보통'},
                {'title': 'SKT-하나금융-삼성전자, 청라 사옥에 \'5G 특화망\' 구축', 'user_importance': '보통'}]
        block = self._similar(rows, '창원소방본부, 복합건축물 화재 불시훈련')
        self.assertIn('창원소방본부', block)
        self.assertIn('금주검토', block)
        self.assertIn('제목이 거의 같은', block)
        self.assertNotIn('반드시 우선 적용', block)
        block2 = self._similar(rows, '하나금융, SKT·삼성전자와 청라 사옥 5G 특화망 구축')   # '삼성전자와' → '삼성전자'
        self.assertIn('하나금융', block2)

    def test_similar_block_ignores_common_word_overlap(self):
        # #264 실측 오판 두 부류: 흔한 낱말 두 개(1위·석권 / KT·통신사)만 겹친 6월 사례가 「즉시대응」으로 붙었다
        rows = [{'title': 'LG유플러스, 고객혁신 결실…이용자보호·만족도 1위 석권', 'user_importance': '긴급'},
                {'title': "통신사 ‘이용자보호 평가’ LG유플러스 ‘최고 등급’···SKT·KT ‘우수’", 'user_importance': '긴급'},
                {'title': '통신 네트워크에도 AI, 주파수 효율·데이터 처리량 높여', 'user_importance': '긴급'}]
        for title in ('사이버 침해 악재 극복..SKT, 韓 3대 고객만족도 1위 석권',
                      'KT, 국내 통신사 최초 NATO 국방통신 표준화 논의 참여',
                      '[위클리오늘] 이동통신 소식_LG유플러스, SK텔레콤, KT(9.28)',
                      "[AI 인프라 투자 패러다임 전환]〈상〉통신 투자, '망 구축'에서 'AI 인프라'로"):
            self.assertEqual(self._similar(rows, title), '', title)

    def test_similar_block_needs_three_words_and_half_of_shorter_title(self):
        rows = [{'title': "연휴 끝나면 식품·유통업계 ‘국감 모드’···쿠팡·홈플러스·배달앱 증인 채택", 'user_importance': '참고'}]
        # 국감·증인 두 낱말만 겹침 → 붙지 않는다(종류가 같은 기사는 고정 블록과 기준문이 맡는다)
        self.assertEqual(self._similar(rows, "복지위 국감도 '플랫폼' 이슈…강남언니·구글·닥터나우 등 증인 신청"), '')
        self.assertEqual(crawler.FB_SIMILAR_MIN, 3)
        self.assertEqual(crawler.FB_SIMILAR_RATIO, 0.5)
        for w in ('skt', 'kt', 'ai', '통신', '통신사'):
            self.assertIn(w, crawler._FB_COMMON)

    def test_temperature_zero_only_in_urgency_call(self):
        # #256-보론3: 긴급도 판정 콜 한 곳만 temperature 0 — 다른 콜엔 온도류 금지(지침 do-not)
        self.assertIn('temperature=0', inspect.getsource(crawler.classify_urgency))
        self.assertEqual(inspect.getsource(crawler).count('temperature='), 1, '긴급도 콜 한 곳만')

    def test_criteria_lines_present(self):
        s = crawler._URGENCY_CRITERIA
        for key in ('민간 기업 고객의 망 구축·5G 특화망', '자기 특화망(이음5G)용으로 전용 주파수', '해외 기관·표준화 회의 참여', '타 상임위(복지위·정무위·산자위·환노위 등) 국감',
                    '통신과 무관한 기관·플랫폼·기업의 유출은 규모가 수백만 계정 미만이면'):
            self.assertIn(key, s)


if __name__ == '__main__':
    unittest.main()
