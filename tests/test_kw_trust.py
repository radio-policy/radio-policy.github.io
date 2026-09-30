# -*- coding: utf-8 -*-
"""
긴급 억제 ① 「T18 + D」(2026-09-30 구현, 판정 local_docs/키워드억제_오걸림_판정_260930.md 6·7절) — crawler._suppress_core ·
news_dedup.SIGNAL_WORDS. 표준 unittest, **네트워크 0**(재보도 대조는 가짜).

  T18 — ① 키워드 일치(공유 3개 이상, 국면 신호 없음)로 바로 억제하는 것은 **사건 대표(마지막으로 알림이 나간 기사)가
        KW_TRUST_H(18시간) 안일 때만**. 넘었거나 모르면 '넘김' — 억제·🔁를 정하지 않고 ①-2(재보도 대조)가 정한다:
        같음 + 대표 24시간 안 → '[의미판정]' 억제 · 같음 + 24시간 넘음 → 🔁(보류 문턱 #256) · 같음 없음 → 표시 없는 알림.
        걸린 사건의 대표는 ①-2 후보 맨 앞. ①-2를 못 쓰는 실행이면 넘긴 기사는 대조 없이 알림(운영자 결정 2026-09-30).
  D   — 국면 신호 낱말에 '채택'·'[단독]'(괄호 없는 '단독'은 아님 — 5G 단독모드).
"""
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
import news_dedup  # noqa: E402
from news_dedup import extract_keywords  # noqa: E402

KST = timezone(timedelta(hours=9))

OLD = '티빙 3954만 계정 유출 보안 투자 확대 발표'
NEW = '티빙 3954만 계정 유출 보안인력 4명 불과'          # OLD와 낱말 4개(티빙·3954·계정·유출 — '만'은 조사로 떼진다) — ①이 건다
OTHER = '알뜰폰 도매대가 협상 타결'
HANDED = '[긴급 억제] 키워드 일치 {n}건을 재보도 대조에 넘김(대표 18시간 초과)'
UNJUDGED = '[긴급 억제] 재보도 대조를 못 써 {n}건은 대조 없이 알림'


def _ago(hours: float) -> str:
    return (datetime.now(KST) - timedelta(hours=hours)).isoformat()


def _prior(*rows):
    """rows = (제목, 몇 시간 전) — 최신순으로 (prior, prior_at)."""
    rows = sorted(rows, key=lambda r: r[1])
    return ([{'title': t, 'kw': extract_keywords(t), 'event': '', 'snip': ''} for t, _h in rows],
            {t: _ago(h) for t, h in rows})


class _Match:
    """재보도 대조 가짜 — pick {새 제목: 기보도 제목}. fail=True면 None(호출 실패). 호출(새 제목들, 후보 제목들)을 calls에."""

    def __init__(self, pick=None, fail=False):
        self.pick, self.fail, self.calls = pick or {}, fail, []

    def __call__(self, new, old):
        self.calls.append(([n['title'] for n in new], [o['title'] for o in old]))
        if self.fail:
            return None
        titles = [o['title'] for o in old]
        return [titles.index(self.pick[n['title']]) if self.pick.get(n['title']) in titles else None for n in new]


def _core(items, prior, prior_at, chain=None, match=None, share=None, sem=None):
    lines = []
    out = crawler._suppress_core([dict(i) for i in items], prior, prior_at, chain or {}, None, log=lines.append,
                                 remind_share=share, match_fn=match, sem_titles=sem)
    return out + (lines,)


def _kinds(sup, rem):
    """기록 행 → [(기사 제목, 접두 종류, matched_title)] — 키워드 행은 'kw'."""
    out = []
    for r in sup + rem:
        k = r['shared_keywords']
        kind = next((p for p in ('[리마인드보류]', '[리마인드]', '[의미판정]', '[실행내묶음]') if k.startswith(p)), 'kw')
        out.append((r['article_title'], kind, r['matched_title']))
    return out


class TestConstants(unittest.TestCase):

    def test_values_and_wiring(self):
        self.assertEqual((crawler.KW_TRUST_H, crawler.REMIND_AFTER_H), (18, 24))
        src = inspect.getsource(crawler._suppress_core)
        self.assertIn('age_h is not None and age_h < KW_TRUST_H', src)
        self.assertNotIn('first_remind', src, '①이 스스로 리마인드를 정하던 갈래는 없다')
        self.assertEqual(src.count('ok, ratio = _remind_ok('), 1, '🔁·보류 문턱은 ①-2의 같음 한 곳에서만')


class TestUnder18(unittest.TestCase):
    """대표가 18시간 안 — 키워드 억제는 오늘과 같다(대조기가 무엇을 답하든, 불리지도 않는다)."""

    def test_keyword_suppression_unchanged(self):
        for h in (0.5, 6, 17.9):
            prior, at = _prior((OLD, h))
            for match in (None, _Match(), _Match({NEW: OLD}), _Match(fail=True)):
                reps, sup, rem, _m, lines = _core([{'title': NEW, 'url': 'n'}], prior, at, match=match)
                self.assertEqual((reps, rem), ([], []), h)
                self.assertEqual(sup, [{'article_title': NEW, 'article_url': 'n', 'matched_title': OLD,
                                        'shared_keywords': '3954,계정,유출,티빙'}])
                self.assertEqual(lines, [])
                if match is not None:
                    self.assertEqual(match.calls, [], '넘긴 것도 통과한 것도 없으면 대조를 부르지 않는다')

    def test_age_follows_chain_to_the_representative(self):
        """걸린 기사가 억제된 기사면 사슬 끝의 대표 나이로 잰다 — 걸린 기사는 2시간 전이어도 대표가 20시간 전이면 넘김."""
        mid = '티빙 3954만 계정 유출 보안 투자 재보도'
        prior, at = _prior((mid, 2), (OLD, 20))
        m = _Match({NEW: OLD})
        reps, sup, rem, _m, lines = _core([{'title': NEW, 'url': 'n'}], prior, at, chain={mid: OLD}, match=m)
        self.assertEqual(m.calls[0][1], [OLD], '후보 = 알림 나간 대표(억제된 mid는 견줄 대상이 아니다)')
        self.assertEqual(_kinds(sup, rem), [(NEW, '[의미판정]', OLD)])
        self.assertEqual(lines[0], HANDED.format(n=1))


class Test18To24(unittest.TestCase):
    """대표가 18~24시간 — 종전에는 키워드로 조용히 억제(재연 16건 중 8건이 새 소식). 이제 ①-2가 정한다."""

    def setUp(self):
        self.prior, self.at = _prior((OTHER, 3), (OLD, 20))

    def test_same_is_semantic_suppression(self):
        m = _Match({NEW: OLD})
        reps, sup, rem, _m, lines = _core([{'title': NEW, 'url': 'n'}], self.prior, self.at, match=m)
        self.assertEqual((reps, rem), ([], []))
        self.assertEqual(sup, [{'article_title': NEW, 'article_url': 'n', 'matched_title': OLD,
                                'shared_keywords': '[의미판정] 3954,계정,유출,티빙'}])
        self.assertEqual(lines, [HANDED.format(n=1), '[긴급 억제] 의미 판정으로 실행 간 재보도 1건 판정(리마인드 포함)'])

    def test_different_is_plain_alert_without_record(self):
        reps, sup, rem, _m, lines = _core([{'title': NEW, 'url': 'n'}], self.prior, self.at, match=_Match())
        self.assertEqual(([r['title'] for r in reps], sup, rem), ([NEW], [], []))
        self.assertNotIn('_remind', reps[0])
        self.assertEqual(lines, [HANDED.format(n=1)])

    def test_unusable_match_alerts(self):
        """키 없음·사슬 못 읽음·예산 초과(None) · 호출 실패 — 넘긴 기사는 대조 없이 알림."""
        for match in (None, _Match(fail=True)):
            reps, sup, rem, _m, lines = _core([{'title': NEW, 'url': 'n'}], self.prior, self.at, match=match)
            self.assertEqual(([r['title'] for r in reps], sup, rem), ([NEW], [], []))
            self.assertEqual(lines, [HANDED.format(n=1), UNJUDGED.format(n=1)])


class TestOver24(unittest.TestCase):
    """대표가 24시간 넘음 — 종전에는 ①이 🔁로 정했다(재연 37건 중 13건이 새 소식의 첫 알림). 이제 ①-2가 '같음'일 때만 🔁."""

    def setUp(self):
        self.prior, self.at = _prior((OTHER, 3), (OLD, 30))

    def test_same_is_reminder_with_gate(self):
        reps, sup, rem, _m, _l = _core([{'title': NEW, 'url': 'n'}], self.prior, self.at, match=_Match({NEW: OLD}))
        self.assertEqual(([r.get('_remind') for r in reps], sup), (['2일째'], []))
        self.assertEqual(rem, [{'article_title': NEW, 'article_url': 'n', 'matched_title': OLD,
                                'shared_keywords': '[리마인드] 2일째'}])
        reps, sup, rem, _m, lines = _core([{'title': NEW, 'url': 'n'}], self.prior, self.at, match=_Match({NEW: OLD}),
                                          share=lambda a, b: (2, 10))
        self.assertEqual((reps, rem), ([], []))
        self.assertEqual(_kinds(sup, rem), [(NEW, '[리마인드보류]', OLD)])
        self.assertTrue(any('리마인드 보류 1건' in ln for ln in lines))

    def test_different_is_plain_alert(self):
        reps, sup, rem, _m, _l = _core([{'title': NEW, 'url': 'n'}], self.prior, self.at, match=_Match(),
                                       share=lambda a, b: (2, 10))
        self.assertEqual(([r['title'] for r in reps], sup, rem), ([NEW], [], []), '보류 문턱은 같음에만 — 다름은 알림')
        self.assertNotIn('_remind', reps[0])

    def test_unusable_match_is_plain_alert(self):
        for match in (None, _Match(fail=True)):
            reps, sup, rem, _m, lines = _core([{'title': NEW, 'url': 'n'}], self.prior, self.at, match=match,
                                              share=lambda a, b: (2, 10))
            self.assertEqual(([r.get('_remind') for r in reps], sup, rem), ([None], [], []))
            self.assertIn(UNJUDGED.format(n=1), lines)

    def test_same_as_fresh_other_rep_is_suppressed(self):
        """넘긴 기사를 ①-2가 24시간 안의 다른 대표와 같은 소식으로 보면 억제 — 결과 규칙은 다른 기사와 같다."""
        reps, sup, rem, _m, _l = _core([{'title': NEW, 'url': 'n'}], self.prior, self.at, match=_Match({NEW: OTHER}))
        self.assertEqual(_kinds(sup, rem), [(NEW, '[의미판정]', OTHER)])


class TestUnknownRepresentative(unittest.TestCase):

    def test_rep_outside_window_is_handed(self):
        """걸린 기사(억제됨)의 사슬 끝 대표가 3일 창 밖(prior_at에 없음) → 나이 모름 → 넘김. 종전 🔁[이어지는 사건] 대신 ①-2가
        창 안의 알림 나간 기사와 견준다(없으면 표시 없는 알림)."""
        mid = '티빙 3954만 계정 유출 보안 투자 재보도'
        prior, at = _prior((mid, 2), (OTHER, 5))
        chain = {mid: '4일 전 첫 보도'}
        m = _Match()
        reps, sup, rem, _m, lines = _core([{'title': NEW, 'url': 'n'}], prior, at, chain=chain, match=m)
        self.assertEqual(([r['title'] for r in reps], sup, rem), ([NEW], [], []))
        self.assertEqual(m.calls[0][1], [OTHER], '창 밖 대표는 넣을 수 없다 — 알림 나간 기사만')
        self.assertEqual(lines, [HANDED.format(n=1)])

    def test_no_alerted_candidate_alerts(self):
        """알림 나간 후보가 0(모두 사슬에 있음) → 대조를 부르지 않고 넘긴 기사는 알림."""
        mid = '티빙 3954만 계정 유출 보안 투자 재보도'
        prior, at = _prior((mid, 2))
        m = _Match({NEW: mid})
        reps, sup, rem, _m, lines = _core([{'title': NEW, 'url': 'n'}], prior, at, chain={mid: '4일 전 첫 보도'}, match=m)
        self.assertEqual(([r['title'] for r in reps], sup, rem, m.calls), ([NEW], [], [], []))
        self.assertEqual(lines, [HANDED.format(n=1), UNJUDGED.format(n=1)])


class TestCandidateFront(unittest.TestCase):

    def test_representative_first_even_when_outranked(self):
        """대표보다 낱말을 많이 공유하는 최근 알림이 10건 넘어도 걸린 사건의 대표는 후보 맨 앞 — 넣지 않으면 밀려 재보도가 샌다."""
        # 억제된 재보도 12건(대표 OLD 30시간 전에 사슬로 매달림) — ①은 가장 최신인 이것에 걸리고, 대표 나이 30시간 → 넘김
        near = [(f'티빙 3954만 계정 유출 보안인력 후속 {k}호', 1 + k * 0.1) for k in range(12)]
        chain = {t: OLD for t, _h in near}
        # 알림 나간 다른 기사 12건 — NEW와 낱말 6개 공유(OLD는 4개)라 낱말 순위만으로는 OLD가 10건 밖으로 밀린다
        rivals = [(f'티빙 계정 유출 보안인력 4명 불과 분석 {k}', 2 + k * 0.1) for k in range(12)]
        new_kw = extract_keywords(NEW)
        ranked = sorted([t for t, _h in rivals] + [OLD], key=lambda t: -len(new_kw & extract_keywords(t)))
        self.assertGreater(ranked.index(OLD), news_dedup.MATCH_MAX_PRIOR - 1, '시험 전제: 넣지 않으면 후보 밖')
        prior, at = _prior(*near, *rivals, (OLD, 30))
        m = _Match({NEW: OLD})
        reps, sup, rem, _m, _l = _core([{'title': NEW, 'url': 'n'}], prior, at, chain=chain, match=m)
        olds = m.calls[0][1]
        self.assertEqual(olds[0], OLD)
        self.assertEqual(len(olds), news_dedup.MATCH_MAX_PRIOR)
        self.assertEqual(_kinds(sup, rem), [(NEW, '[리마인드]', OLD)])

    def test_several_handed_reps_newest_first_then_rest(self):
        a_old, b_old = '위성 통신 신규 사업자 선정 결과 발표', '5G 주파수 경매 일정 연기 발표'
        a_new, b_new = '위성 통신 신규 사업자 선정 후폭풍', '5G 주파수 경매 일정 연기 여파'
        prior, at = _prior((OTHER, 1), (a_old, 40), (b_old, 20))
        m = _Match()
        _core([{'title': a_new, 'url': 'a'}, {'title': b_new, 'url': 'b'}], prior, at, match=m)
        self.assertEqual(m.calls[0][1][:2], [b_old, a_old], '넘긴 기사들의 대표 — 최신순')
        self.assertEqual(m.calls[0][1][2:], [OTHER])


class TestFloodStops(unittest.TestCase):

    def test_next_run_is_keyword_suppressed_against_the_new_alert(self):
        """①-2를 못 쓰는 동안 넘긴 기사가 알림으로 나가면 그 기사가 새 대표가 된다 — 다음 실행의 같은 사건 기사는 다시 18시간 안
        키워드 억제(장애 동안 전날 사건의 아침 기사가 사건당 한두 통 나가고 멈춘다)."""
        prior, at = _prior((OLD, 20))
        reps, sup, rem, _m, _l = _core([{'title': NEW, 'url': 'n1'}], prior, at, match=None)
        self.assertEqual([r['title'] for r in reps], [NEW])                   # 1회차: 대조 없이 알림(기록 없음)
        later = '티빙 3954만 계정 유출 보안인력 4명 불과 재조명'
        prior, at = _prior((NEW, 0.2), (OLD, 20.2))                            # NEW는 기록이 없으니 사슬 밖 = 알림 나간 대표
        reps, sup, rem, _m, lines = _core([{'title': later, 'url': 'n2'}], prior, at, match=None)
        self.assertEqual((reps, rem), ([], []))
        self.assertEqual(_kinds(sup, rem), [(later, 'kw', NEW)])
        self.assertEqual(lines, [])


class TestSignalWords(unittest.TestCase):

    def test_adopted_and_exclusive_are_new_signals(self):
        self.assertIn('채택', news_dedup.SIGNAL_WORDS)
        self.assertIn('[단독]', news_dedup.SIGNAL_WORDS)
        self.assertNotIn('단독', news_dedup.SIGNAL_WORDS)
        cases = [
            ('과방위 통신 3사 대표 증인 요구 검토', '과방위 통신 3사 대표 증인 채택 의결', False),
            ('통신 3사 최적요금제 고지 의무화 추진', '[단독] 통신 3사 최적요금제 공식 표기 의무화', False),
            ('통신 3사 5G 단독모드 전환 계획', '통신 3사 5G 단독모드 전환 연기 검토', True),     # 괄호 없는 단독은 신호 아님
            ('[단독] 통신 3사 최적요금제 고지 의무화', '[단독] 통신 3사 최적요금제 고지 의무화 반응', True),  # 둘 다 있으면 조용
            ('과방위 통신 3사 대표 증인 채택', '과방위 통신 3사 대표 증인 채택 뒷말', True),
        ]
        for prior_t, new_t, follow in cases:
            kw_p, kw_n = extract_keywords(prior_t), extract_keywords(new_t)
            self.assertGreaterEqual(len(kw_p & kw_n), 3, new_t)
            self.assertEqual(news_dedup.is_followup(kw_n, kw_p, new_t, prior_t), follow, new_t)

    def test_signal_passes_first_stage_even_when_fresh(self):
        prior, at = _prior(('과방위 통신 3사 대표 증인 요구 검토', 2))
        new = '과방위 통신 3사 대표 증인 채택 의결'
        reps, sup, rem, _m, lines = _core([{'title': new, 'url': 'n'}], prior, at, match=_Match())
        self.assertEqual(([r['title'] for r in reps], sup, rem), ([new], [], []))
        self.assertEqual(lines, [], '신호 낱말은 넘김이 아니라 ① 통과(일치 없음)')


if __name__ == '__main__':
    unittest.main()
