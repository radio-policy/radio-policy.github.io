# -*- coding: utf-8 -*-
"""긴급도 내림 전파 — 그림자(#327, 2026-10-28) — 네트워크 0.

판정 local_docs/긴급도_재보정_준비_261028/판정_재보정_261028.md §4, 측정 결과_재보정_261030.md §4(미통과 → 그림자).
  · prior 고르기는 ①-2(_suppress_core)의 「이미 알린 기사」 고르기와 같은 목록이어야 한다(측정 재연과 같은 규칙).
  · 풀: 72시간 안 운영자 내림 중 지금도 보통·참고인 것만, 전파로 걸린·복원된 기사와 둘째 행은 뺀다.
  · grade_urgency: 후보 = 최종 긴급인 AI 판정 기사(set 규칙·낱말 하한 긴급·2차가 내린 기사 제외), 두 칸만 채우고 **등급 불변**,
    모든 행에 키, 실패는 삼킨다.
  · 판정기: 사람 즉시대응 유사 사례는 건너뜀, 묶음 실패 PROPAGATE_MAX_FAIL번이면 나머지 안 부름, api_usage 라벨 분리.
  · 운영자 줄·importance_feedback 쓰기 없음. 재보도 대조 지시문·도구는 tests/test_dedup_match.py가 그대로 잠근다.
"""
import contextlib
import io
import os
import re
import sys
import inspect
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import api_usage  # noqa: E402
import crawler  # noqa: E402
import news_dedup  # noqa: E402
from news_dedup import extract_keywords  # noqa: E402

KEYS = ('urgency_propagate_shadow_from', 'urgency_propagate_shadow_at')


def _quiet(fn, *a, **k):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        r = fn(*a, **k)
    return r, out.getvalue()


def _entry(i, title, event=''):
    return {'id': f'p{i}', 'title': title, 'event': event, 'snip': f'요약{i}', 'at': f'2026-10-28T0{i % 10}:00:00+00:00'}


# ── prior 고르기 = ①-2 ────────────────────────────────────────────────────────────────────────────
class TestPickPriorEqualsSuppressCore(unittest.TestCase):
    NEW = [{'title': '알뜰폰 도매대가 인하 논의', 'url': 'n1', 'event': '알뜰폰 도매대가 협상'},
           {'title': '기지국 전력 절감 실증', 'url': 'n2', 'event': '기지국 전력 실증 사업'}]
    POOL = [_entry(0, '위성 통신 사업자 선정 발표', '위성 사업자 선정'),
            _entry(1, '알뜰폰 업계 반발 성명', '알뜰폰 도매대가 반발'),
            _entry(2, '도매대가 협상 결렬', '알뜰폰 도매대가 협상'),
            _entry(3, '기지국 장애 복구', '기지국 장애'),
            _entry(4, '전력 절감 기술', '기지국 전력 절감'),
            _entry(5, '주파수 경매 일정 공개'),
            _entry(6, '주파수 경매 일정 공개', '같은 제목 둘째'),
            _entry(7, '요금제 개편 발표'),
            _entry(8, '해킹 사고 조사 착수'),
            _entry(9, '국감 증인 채택 의결'),
            _entry(10, '위약금 면제 논란'),
            _entry(11, '단말기 지원금 공시'),
            _entry(12, '로밍 요금 인하'),
            _entry(13, '와이파이 구축 완료')]

    def test_same_list_as_suppress_core(self):
        # ① 키워드 억제(제목 낱말 3개 공유)에 걸리면 ①-2 후보 맨 앞 규칙이 끼므로, 이 자료는 제목 공유가 2개 이하다
        for n in self.NEW:
            for p in self.POOL:
                self.assertLess(len(extract_keywords(n['title']) & extract_keywords(p['title'])), 3, p['title'])
        prior = [{'title': p['title'], 'kw': extract_keywords(p['title']), 'event': p['event'], 'snip': p['snip']}
                 for p in self.POOL]
        seen = []

        def match(new, old):
            seen.append(old)
            return [None] * len(new)
        crawler._suppress_core([dict(n) for n in self.NEW], prior, {}, {}, None, log=None, match_fn=match)
        self.assertEqual(len(seen), 1)
        mine = crawler.propagate_pick_prior(self.NEW, self.POOL)
        self.assertEqual([p['title'] for p in mine], [o['title'] for o in seen[0]])
        self.assertEqual(len(mine), news_dedup.MATCH_MAX_PRIOR)
        self.assertEqual([p['id'] for p in mine[:2]], ['p2', 'p4'], '공유 3 둘 — 같으면 최신(풀 앞)부터')
        self.assertNotIn('p6', [p['id'] for p in mine], '같은 제목은 처음 하나')

    def test_empty(self):
        self.assertEqual(crawler.propagate_pick_prior([], self.POOL), [])
        self.assertEqual(crawler.propagate_pick_prior(self.NEW, []), [])


# ── 풀 ──────────────────────────────────────────────────────────────────────────────────────────
class TestPoolEntries(unittest.TestCase):
    def test_filters_and_order(self):
        fb = [{'news_id': 'a', 'created_at': 't5'}, {'news_id': 'b', 'created_at': 't4'},
              {'news_id': 'a', 'created_at': 't3'}, {'news_id': 'c', 'created_at': 't2'},
              {'news_id': 'd', 'created_at': 't2'}, {'news_id': 'e', 'created_at': 't1'},
              {'news_id': 'zz', 'created_at': 't0'}]
        news = [{'id': 'a', 'title': 'A', 'event': 'ev', 'screen_text': '요약A', 'content': '본문A', 'urgency': '보통'},
                {'id': 'b', 'title': 'B', 'event': None, 'screen_text': None, 'content': '본문B', 'urgency': '참고'},
                {'id': 'c', 'title': 'C', 'urgency': '긴급'},                                        # 운영자가 다시 올림
                {'id': 'd', 'title': 'D', 'urgency': '보통', 'urgency_propagate_shadow_from': 'x'},  # 전파 기사 — 연쇄 금지
                {'id': 'e', 'title': 'E', 'urgency': '보통', 'urgency_check_restored_at': '2026-10-27'}]  # 복원 기사
        got = crawler.propagate_pool_entries(fb, news)
        self.assertEqual(got, [{'id': 'a', 'title': 'A', 'event': 'ev', 'snip': '요약A', 'at': 't5'},
                               {'id': 'b', 'title': 'B', 'event': '', 'snip': '본문B', 'at': 't4'}])

    def test_pool_query_columns(self):
        for col in ('urgency', 'urgency_check_restored_at', 'urgency_propagate_shadow_from', 'event', 'screen_text'):
            self.assertIn(col, crawler._PROPAGATE_NEWS_COLS.split(','))
        src = inspect.getsource(crawler._propagate_pool)
        for frag in ("is_('team_id', 'null')", "eq('ai_importance', '긴급')", "in_('user_importance', ['보통', '참고'])",
                     "order('created_at', desc=True)", 'PROPAGATE_WINDOW_H'):
            self.assertIn(frag, src)
        self.assertEqual(crawler.PROPAGATE_WINDOW_H, 72, '측정 창과 같은 값 — 바꾸려면 다시 잰다')


# ── grade_urgency ───────────────────────────────────────────────────────────────────────────────
class TestGradeUrgencyPropagate(unittest.TestCase):
    RULES = [{'id': 'r_min_urgent', 'mode': 'min', 'level': '긴급', 'any_words': ['국감증인']},
             {'id': 'r_min_normal', 'mode': 'min', 'level': '보통', 'any_words': ['SKT']},
             {'id': 'r_set_ref', 'mode': 'set', 'level': '참고', 'any_words': ['부고']},
             {'id': 'r_set_urgent', 'mode': 'set', 'level': '긴급', 'any_words': ['재난문자']}]
    PRIOR = {'id': 'p-uuid', 'title': '운영자가 내린 기사', 'event': '', 'snip': '', 'at': 't'}

    def setUp(self):
        self._p = mock.patch.dict(crawler._URGENCY_SUMMARY, {}, clear=True)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def _items(self):
        return [{'title': 'A 해킹 후속', 'url': 'u1'},          # AI 긴급 → 후보
                {'title': 'SKT 장애 후속', 'url': 'u2'},        # AI 긴급 + min 보통 → 후보
                {'title': '국감증인 채택', 'url': 'u3'},        # min 긴급 → 건너뜀
                {'title': '[부고] 누구', 'url': 'u4'},          # set 참고
                {'title': '재난문자 오발송', 'url': 'u5'},      # set 긴급 — AI 없음 → 후보 아님
                {'title': '보통 기사', 'url': 'u6'},            # AI 보통
                {'title': '드론 배송', 'url': 'u7'}]            # 2차 타영역 → 보통(on)

    def _grade(self, items, propagate):
        ai = lambda t, c, s: '보통' if t == '보통 기사' else '긴급'
        chk = lambda t, c, s: {'scope': '타영역' if t == '드론 배송' else '통신', 'grade': '보통', 'basis': '없음'}
        with mock.patch.object(crawler, 'URGENCY_CHECK_MODE', 'on'):
            return _quiet(crawler.grade_urgency, items, self.RULES, classify=ai, check=chk, propagate=propagate)

    def test_candidates_fields_and_grade_unchanged(self):
        seen = []

        def prop(cands):
            seen.append([c['title'] for c in cands])
            return [self.PRIOR, False]
        items = self._items()
        _, log = self._grade(items, prop)
        self.assertEqual(seen, [['A 해킹 후속', 'SKT 장애 후속']], '한 번에, 최종 긴급인 AI 판정 기사만')
        self.assertEqual([i['urgency'] for i in items], ['긴급', '긴급', '긴급', '참고', '긴급', '보통', '보통'],
                         '그림자 — 같은 계기여도 등급은 그대로')
        self.assertEqual([i['importance'] for i in items], [i['urgency'] for i in items])
        self.assertEqual(items[0]['urgency_propagate_shadow_from'], 'p-uuid')
        self.assertIsNotNone(items[0]['urgency_propagate_shadow_at'])
        self.assertIsNone(items[1]['urgency_propagate_shadow_from'])
        self.assertIsNotNone(items[1]['urgency_propagate_shadow_at'], '대조했고 다름 — 시각만')
        for it in items[2:]:
            self.assertEqual([it[k] for k in KEYS], [None, None])
        self.assertEqual(len({frozenset(i) for i in items}), 1, '벌크 upsert — 모든 행의 키 집합이 같다')
        self.assertEqual(items[6]['urgency_check_capped'], True, '2차 확인 칸은 그대로')
        self.assertEqual(crawler._PROPAGATE_HITS, {'u1': '운영자가 내린 기사'})
        self.assertEqual([k for i in items for k in i if k.startswith('_')], [], 'item(= upsert 행)에 표시 키를 넣지 않는다')
        self.assertIn('[내림 전파·그림자] 후보 2건(사람 사례 건너뜀 0, 낱말 하한 긴급 건너뜀 1)', log)
        self.assertIn('같은 계기 1 · 다름 1', log)
        self.assertIn('등급·알림 불변', log)

    def test_not_judged_and_errors_leave_none(self):
        for prop in (lambda c: [None] * len(c), lambda c: None, mock.Mock(side_effect=RuntimeError('죽음'))):
            items = self._items()
            _, log = self._grade(items, prop)
            for it in items:
                self.assertEqual([it[k] for k in KEYS], [None, None])
            self.assertEqual(items[0]['urgency'], '긴급')
        self.assertIn('오류(무시 — 등급 그대로)', log)

    def test_injected_classify_without_propagate_never_calls_default(self):
        items = [{'title': '드론', 'url': 'u1'}]
        with mock.patch.object(crawler, 'propagate_shadow_judge', side_effect=AssertionError('불리면 안 됨')):
            _quiet(crawler.grade_urgency, items, [], classify=lambda t, c, s: '긴급')
        self.assertEqual([items[0][k] for k in KEYS], [None, None])

    def test_default_follows_mode(self):
        seen = []
        with mock.patch.object(crawler, 'classify_urgency', lambda t, c='', s='': '긴급'), \
                mock.patch.object(crawler, 'urgency_second_check', lambda t, c='', s='': None), \
                mock.patch.object(crawler, 'propagate_shadow_judge', lambda cands: seen.append(len(cands)) or [None]):
            _quiet(crawler.grade_urgency, [{'title': '드론', 'url': 'u1'}], [])
            self.assertEqual(seen, [1])
            with mock.patch.object(crawler, 'PROPAGATE_MODE', 'off'):
                _quiet(crawler.grade_urgency, [{'title': '드론', 'url': 'u1'}], [])
            self.assertEqual(seen, [1], "'off'면 부르지 않는다")

    def test_mode_is_shadow(self):
        self.assertEqual(crawler.PROPAGATE_MODE, 'shadow', '측정 미통과(잘못 내림 15 > 3) — 한 주 그림자 뒤 재판정(결과 §4)')

    def test_shadow_step_never_touches_grade(self):
        src = inspect.getsource(crawler._grade_propagate_shadow)
        self.assertNotIn("['urgency']", src)
        self.assertNotIn("['importance']", src)


# ── 판정기 ─────────────────────────────────────────────────────────────────────────────────────
class TestJudge(unittest.TestCase):
    POOL = [_entry(1, '운영자 내림 하나', '요지 하나'), _entry(2, '운영자 내림 둘')]

    def setUp(self):
        crawler._PROPAGATE_RUN.clear()
        self._sim = mock.patch.object(crawler, '_feedback_similar_block',
                                      lambda t: '\n\n[머리]\n- "옛 기사" → 즉시대응' if t.startswith('H') else '')
        self._sim.start()

    def tearDown(self):
        self._sim.stop()

    def test_human_skip_inputs_and_mapping(self):
        calls = []

        def match(new, old):
            calls.append((new, old))
            return [1]
        cands = [{'title': 'H 사람 사례', 'event': 'e'},
                 {'title': 'X 새 기사', 'event': '요지', 'screen_text': None, 'content': '본문X'}]
        out, _ = _quiet(crawler.propagate_shadow_judge, cands, pool_fn=lambda: list(self.POOL), match_fn=match)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], [{'title': 'X 새 기사', 'event': '요지', 'snip': '본문X'}])
        self.assertTrue(all(set(o) == {'title', 'event', 'snip'} for o in calls[0][1]), 'prior는 세 칸만 넘긴다')
        picked = crawler.propagate_pick_prior(calls[0][0], self.POOL)
        self.assertEqual(out, [None, picked[1]])
        self.assertEqual(crawler._PROPAGATE_RUN['skip_human'], 1)

    def test_empty_pool_no_call(self):
        m = mock.Mock()
        out, _ = _quiet(crawler.propagate_shadow_judge, [{'title': 'X'}], pool_fn=lambda: [], match_fn=m)
        self.assertEqual(out, [None])
        m.assert_not_called()
        self.assertEqual(crawler._PROPAGATE_RUN['pool'], 0)

    def test_fail_cap(self):
        calls = []
        cands = [{'title': f'X{i}'} for i in range(30)]
        out, _ = _quiet(crawler.propagate_shadow_judge, cands, pool_fn=lambda: list(self.POOL),
                        match_fn=lambda n, o: calls.append(len(n)) or None)
        self.assertEqual(calls, [news_dedup.MATCH_MAX_NEW] * crawler.PROPAGATE_MAX_FAIL)
        self.assertEqual(out, [None] * 30)
        self.assertEqual(crawler._PROPAGATE_RUN['capped'], 30 - news_dedup.MATCH_MAX_NEW * crawler.PROPAGATE_MAX_FAIL)

    def test_chunks_and_bad_answers(self):
        cands = [{'title': f'X{i}'} for i in range(14)]
        answers = iter([[0, None, 9, 'A'] + [None] * 8, [0]])     # 둘째 묶음은 2건 중 1건만 답
        out, _ = _quiet(crawler.propagate_shadow_judge, cands, pool_fn=lambda: list(self.POOL),
                        match_fn=lambda n, o: next(answers))
        self.assertEqual(out[0]['id'], self.POOL[0]['id'])
        self.assertEqual(out[1:12], [False] * 11, '대조했고 다름(범위 밖·이상한 값 포함)')
        self.assertEqual(out[12]['id'], self.POOL[0]['id'])
        self.assertIsNone(out[13], '답이 빠진 기사는 대조 안 함')

    def test_pool_error_is_open(self):
        def boom():
            raise RuntimeError('db down')
        out, log = _quiet(crawler.propagate_shadow_judge, [{'title': 'X'}], pool_fn=boom, match_fn=mock.Mock())
        self.assertEqual(out, [None])
        self.assertIn('오류(무시', log)

    def test_matcher_call_is_the_dedup_function_with_own_label(self):
        seen = {}

        def fake(new, old, key, **kw):
            seen.update(new=new, old=old, key=key, kw=kw, label=getattr(api_usage._label, 'site', None),
                        site=api_usage._caller_site(1))
            return [None]
        with mock.patch.object(news_dedup, 'match_prior_reports', fake), mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'):
            crawler._propagate_match([{'title': 'n'}], [{'title': 'o'}])
        self.assertEqual(seen['key'], 'k')
        self.assertEqual(seen['kw'], {'timeout': crawler.PROPAGATE_TIMEOUT_S, 'max_retries': 1})
        self.assertEqual((seen['label'], seen['site']), (crawler.PROPAGATE_SITE,) * 2)
        self.assertIsNone(getattr(api_usage._label, 'site', None), '블록을 나가면 라벨이 돌아간다')
        self.assertNotEqual(crawler.PROPAGATE_SITE, 'news_dedup.py:match_prior_reports')


class TestApiUsageLabel(unittest.TestCase):
    def test_nesting(self):
        self.assertNotEqual(api_usage._caller_site(1), 'x')
        with api_usage.site_label('x'):
            self.assertEqual(api_usage._caller_site(1), 'x')
            with api_usage.site_label('y'):
                self.assertEqual(api_usage._caller_site(1), 'y')
            self.assertEqual(api_usage._caller_site(1), 'x')
        self.assertIsNone(getattr(api_usage._label, 'site', None))


# ── 운영자 줄 · 학습 행 금지 ─────────────────────────────────────────────────────────────────────
class TestNoticeAndGuards(unittest.TestCase):
    def test_notice(self):
        sent = []
        items = [{'title': '새 <기사>', 'url': 'https://a/1', 'urgency_propagate_shadow_from': 'p1'},
                 {'title': '다른 기사', 'url': 'https://a/2', 'urgency_propagate_shadow_from': None}]
        with mock.patch.object(crawler, 'TELEGRAM_BOT_TOKEN', 't'), mock.patch.object(crawler, 'TELEGRAM_CHAT_ID', 'c'), \
                mock.patch.dict(crawler._PROPAGATE_HITS, {'https://a/1': '운영자 내림 & 기사'}, clear=True), \
                mock.patch.object(crawler.notify, 'send_telegram', lambda text, **kw: sent.append((text, kw)) or True):
            ok, _ = _quiet(crawler.send_propagate_shadow_notice, items)
        self.assertTrue(ok)
        self.assertEqual(len(sent), 1)
        text, kw = sent[0]
        self.assertTrue(text.startswith('🔽(그림자) 내림 전파 후보 1건 — 등급·알림은 그대로입니다'))
        self.assertIn('「<a href="https://a/1">새 &lt;기사&gt;</a>」 ← 운영자 내림 「운영자 내림 &amp; 기사」', text)
        self.assertNotIn('다른 기사', text)
        self.assertEqual(kw.get('parse_mode'), 'HTML')

    def test_notice_none(self):
        with mock.patch.object(crawler, 'TELEGRAM_BOT_TOKEN', 't'), mock.patch.object(crawler, 'TELEGRAM_CHAT_ID', 'c'), \
                mock.patch.object(crawler.notify, 'send_telegram', side_effect=AssertionError('보내면 안 됨')):
            self.assertFalse(crawler.send_propagate_shadow_notice([{'title': 'x', 'urgency_propagate_shadow_from': None}]))

    def test_never_writes_importance_feedback(self):
        """전파·기계 경로는 학습 행을 남기지 않는다(지침 금지 항목, #327) — 크롤러의 importance_feedback 접근은 읽기뿐."""
        with open(crawler.__file__, encoding='utf-8') as f:
            src = f.read()
        for m in re.finditer(r"table\('importance_feedback'\)", src):
            stmt = src[m.end():src.find('.execute()', m.end())]
            self.assertNotRegex(stmt, r'\.(insert|upsert|update|delete)\(', stmt[:80])

    def test_restore_path_untouched(self):
        src = inspect.getsource(crawler.restore_raised_checks)
        self.assertNotIn('propagate', src, '그림자 동안 복원 경로를 타지 않는다')


if __name__ == '__main__':
    unittest.main()
