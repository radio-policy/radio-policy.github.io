# -*- coding: utf-8 -*-
"""
긴급 억제 ①-2 「재보도 대조」(#263, 2026-09-30) — news_dedup.match_prior_reports · crawler._suppress_core의 새 단계.
표준 unittest, **네트워크 0**(Anthropic 클라이언트는 가짜).

  - 지시문·도구·온도 0은 실측(tools_dedup_probe.py, tests/fixtures/dedup_match_cases.json)에 쓴 글자 그대로 — 고치면 실측부터.
  - 입력 글(이미 알린 기사 = 기호, 새 기사 = 번호), 도구 출력 읽기(기사별 — 흠 있는 줄만 '대조 없음'), 나눠 부르기, fail-open.
  - _suppress_core: 견줄 대상은 알림으로 나간 기사만 · 낱말 공유 수 → 최신 순 · 의미 판정으로 억제된 기사(와 거기 매달린
    기사)는 ① 키워드 비교군에서 빠짐 · ①이 넘긴 기사(T18 — 키워드 일치, 대표 18시간 초과)도 같은 규칙으로 억제·🔁·알림 ·
    기록은 한 줄. T18의 세부(18시간 경계·후보 맨 앞의 대표·대조를 못 쓰는 실행·신호 낱말)는 tests/test_kw_trust.py.
  - 고정 자료(dedup_match_cases.json)의 모양.
"""
import inspect
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import crawler  # noqa: E402
import news_dedup  # noqa: E402
from news_dedup import extract_keywords  # noqa: E402

KST = timezone(timedelta(hours=9))


def _ago(hours: float) -> str:
    return (datetime.now(KST) - timedelta(hours=hours)).isoformat()


# ══════════════════════════════════════════════════════════════════════════════════════════════
#  실측에 쓴 지시문·도구 — 글자 그대로(2026-09-30, 5판). news_dedup._MATCH_SYSTEM / _MATCH_TOOL과 같아야 한다.
# ══════════════════════════════════════════════════════════════════════════════════════════════
RUBRIC = (
    '너는 통신·전파 정책 뉴스 알림의 중복 거름 판정기다. [새 기사]마다 [이미 알린 기사] 가운데 같은 소식이 있는지 가린다.\n'
    '같다고 하면 그 새 기사는 알림에서 빠진다. 확실할 때만 같다고 하고, 애매하면 다르다고 한다.\n'
    '새 기사끼리는 견주지 않는다 — 이미 알린 기사하고만 견준다.\n'
    '\n'
    '기사마다 「계기」를 본다. 계기 = 그 기사가 나오게 된 일: 어느 기관·회사·의원이 무엇을 발표·공개·결정·발언했는지, 어떤 사고·판결·회의가 있었는지. 계기 없이 기자가 '
    '스스로 정리·해설·전망한 글이면 「자체 정리: 무엇에 관한」이라고 적는다.\n'
    '\n'
    '새 기사마다 네 칸을 차례로 채운다\n'
    '1) peg — 새 기사의 계기 한 줄.\n'
    '2) closest — 이미 알린 기사 가운데 계기가 가장 가까운 것의 기호. 없으면 "0".\n'
    '3) closest_peg — 그 기사의 계기 한 줄(closest가 "0"이면 빈 칸).\n'
    '4) same — 두 계기가 같은 일이면 true, 아니면 false.\n'
    '\n'
    'same = true\n'
    '- 계기가 같다: 같은 발표·자료 공개·발언·처분·판결·사고·회의·통계에서 나온 기사다. 매체가 다르거나 제목이 뽑은 대목·각도가 달라도 같다(한 발표의 다른 항목을 앞세운 '
    '기사, 같은 자료를 해설한 기사 포함).\n'
    '- 둘 다 같은 대상을 새 계기 없이 정리·전망한 글이다(같은 국정감사의 일정·증인·전망, 같은 제도 시행 안내).\n'
    '\n'
    'same = false — 하나라도 해당하면 false\n'
    '- 새 기사의 계기가 이미 알린 기사보다 뒤에 새로 생긴 일이다: 새 발표·새 발언, 의원·기관이 새로 내놓은 자료·수치, [단독]으로 처음 밝힌 사실, 소송 제기·법안 발의, '
    '증인 채택·철회, 시행 연기, 새 제재·처분·조사 착수. 같은 사건·같은 회사를 다루더라도 계기가 새로우면 false다(예: 과징금 부과 기사 뒤에 나온 취소 소송 제기 기사, '
    '해킹 사고 해설 뒤에 나온 의원의 새 폭로 기사).\n'
    '- 주제·분야·시기만 같다(둘 다 개인정보 유출, 둘 다 과징금, 둘 다 AI, 둘 다 국정감사 철 기사).\n'
    '- 같은 회사·기관·의원·위원회의 다른 사안이다(같은 의원이 낸 다른 자료, 같은 기관의 다른 결정).\n'
    '- 다른 회사·기관에서 일어난 비슷한 일이다.\n'
    '- 연속 기획의 다른 회차(상·중·하)이고 다루는 내용이 다르다.\n'
    '- 제목 머리말([단독]·[기획]·[국감])이나 낱말 몇 개만 같다.\n'
    '\n'
    '「요지」는 자동으로 붙인 참고 줄이라 틀릴 수 있다 — 제목과 내용을 앞세운다.'
)

TOOL = {
    'name': 'record_matches',
    'description': '새 기사마다 계기가 가장 가까운 이미 알린 기사와, 두 기사의 계기가 같은 일인지를 기록한다. 입력된 모든 새 기사에 대해 한 줄씩.',
    'input_schema': {'type': 'object', 'properties': {'results': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {
            'id': {'type': 'integer', 'description': '새 기사 번호'},
            'peg': {'type': 'string', 'description': '새 기사의 계기 한 줄(40자 이내)'},
            'closest': {'type': 'string', 'description': '계기가 가장 가까운 이미 알린 기사의 기호 하나(A, B, C …). 없으면 "0". 새 기사 번호는 적지 않는다.'},
            'closest_peg': {'type': 'string', 'description': '그 기사의 계기 한 줄(40자 이내). closest가 "0"이면 빈 문자열.'},
            'same': {'type': 'boolean', 'description': '두 계기가 같은 일이면 true. 회사·주제·시기만 같으면 false.'},
        },
        'required': ['id', 'peg', 'closest', 'closest_peg', 'same']}}}, 'required': ['results']},
}


class TestRubricLock(unittest.TestCase):

    def test_rubric_and_tool_verbatim(self):
        """재보도 대조 지시문·도구는 실측에 쓴 글자 그대로 — 고치려면 tools_dedup_probe.py로 173회 세트를 다시 재고 함께 고친다."""
        self.assertEqual(news_dedup._MATCH_SYSTEM, RUBRIC)
        self.assertEqual(news_dedup._MATCH_TOOL, TOOL)
        self.assertEqual(news_dedup.MATCH_MODEL, 'claude-haiku-4-5-20251001')
        self.assertEqual((news_dedup.MATCH_MAX_NEW, news_dedup.MATCH_MAX_PRIOR, news_dedup.MATCH_SNIP), (12, 10, 120))

    def test_temperature_zero_only_in_match_call(self):
        """온도 0은 온도류 금지 규칙의 둘째 예외 — news_dedup에서는 재보도 대조 한 곳뿐(첫째는 crawler.classify_urgency)."""
        self.assertEqual(inspect.getsource(news_dedup).count('temperature='), 1)
        self.assertIn('temperature=0', inspect.getsource(news_dedup.match_prior_reports))
        self.assertNotIn('temperature', inspect.getsource(news_dedup.group_same_event))
        self.assertEqual(inspect.getsource(crawler).count('temperature='), 1, '크롤러는 긴급도 콜 한 곳 그대로')

    def test_group_classifier_not_used_for_suppression(self):
        """묶기 분류기(group_same_event)는 같은 실행분 2차 묶기에만 — _suppress_core에서 group_fn 호출은 한 곳."""
        src = inspect.getsource(crawler._suppress_core)
        self.assertEqual(src.count('group_fn('), 1)
        self.assertEqual(src.count('match_fn('), 1)


class TestPrompt(unittest.TestCase):

    def test_lines_and_order(self):
        new = [{'title': ' 새 기사 하나 ', 'event': '요지 하나', 'snip': '내용  두 칸\n줄바꿈'},
               {'title': '새 기사 둘', 'event': '', 'snip': ''}]
        old = [{'title': '옛 기사 가', 'event': '옛 요지', 'snip': '옛 내용'}, {'title': '옛 기사 나'}]
        self.assertEqual(news_dedup.build_match_prompt(new, old),
                         '[이미 알린 기사 2건]\n'
                         'A. 옛 기사 가 | 요지: 옛 요지 | 내용: 옛 내용\n'
                         'B. 옛 기사 나\n'
                         '\n'
                         '[새 기사 2건]\n'
                         '1. 새 기사 하나 | 요지: 요지 하나 | 내용: 내용 두 칸 줄바꿈\n'
                         '2. 새 기사 둘')

    def test_snippet_cut(self):
        line = news_dedup._match_line('A', {'title': 't', 'snip': '가' * 500})
        self.assertEqual(line, 'A. t | 내용: ' + '가' * 120)


class TestParse(unittest.TestCase):

    def p(self, rows, n_new=3, n_prior=4):
        return news_dedup._parse_match(rows, n_new, n_prior)

    def test_same_true_with_valid_letter(self):
        rows = [{'id': 1, 'peg': 'x', 'closest': 'C', 'closest_peg': 'y', 'same': True},
                {'id': 2, 'peg': 'x', 'closest': 'b', 'closest_peg': 'y', 'same': True},
                {'id': 3, 'peg': 'x', 'closest': '0', 'closest_peg': '', 'same': False}]
        self.assertEqual(self.p(rows), [2, 1, None])

    def test_not_same_or_bad_letter_is_none(self):
        rows = [{'id': 1, 'closest': 'A', 'same': False},          # 가장 가까운 것은 있으나 다른 일
                {'id': 2, 'closest': 'E', 'same': True},           # 기호가 목록 밖
                {'id': 3, 'closest': '1', 'same': True}]           # 새 기사 번호를 적음(새 기사끼리 견줌)
        self.assertEqual(self.p(rows), [None, None, None])

    def test_only_strict_true_counts(self):
        self.assertEqual(self.p([{'id': 1, 'closest': 'A', 'same': 'true'}, {'id': 2, 'closest': 'A', 'same': 1}]),
                         [None, None, None])

    def test_flawed_rows_do_not_spoil_others(self):
        rows = ['줄이 아님', {'id': 'x', 'closest': 'A', 'same': True}, {'id': 9, 'closest': 'A', 'same': True},
                {'closest': 'A', 'same': True}, {'id': 2, 'closest': 'D', 'same': True}]
        self.assertEqual(self.p(rows), [None, 3, None])

    def test_conflicting_duplicate_id_is_none(self):
        rows = [{'id': 1, 'closest': 'A', 'same': True}, {'id': 1, 'closest': 'B', 'same': True},
                {'id': 2, 'closest': 'A', 'same': True}, {'id': 2, 'closest': 'A', 'same': True}]
        self.assertEqual(self.p(rows), [None, 0, None])


class _Resp:
    def __init__(self, rows=None, stop='tool_use', blocks=None):
        self.stop_reason = stop
        if blocks is not None:
            self.content = blocks
        else:
            self.content = [mock.Mock(type='tool_use', input={'results': rows})]


class _FakeAnthropic:
    """anthropic.Anthropic 가짜 — 만든 인자(made)·create 인자(sent)를 남기고, script의 응답(또는 예외)을 차례로 돌려준다."""
    made, sent, script = [], [], []

    def __init__(self, **kw):
        type(self).made.append(kw)
        self.messages = mock.Mock(create=self._create)

    def _create(self, **kw):
        type(self).sent.append(kw)
        r = type(self).script.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _call(script, new, old, key='key', **kw):
    import anthropic
    _FakeAnthropic.made, _FakeAnthropic.sent, _FakeAnthropic.script = [], [], list(script)
    with mock.patch.object(anthropic, 'Anthropic', _FakeAnthropic), mock.patch('builtins.print'):
        got = news_dedup.match_prior_reports(new, old, key, **kw)
    return got, _FakeAnthropic.made, _FakeAnthropic.sent


def _art(title, event='', snip=''):
    return {'title': title, 'event': event, 'snip': snip}


class TestMatchCall(unittest.TestCase):
    NEW = [_art('새 하나', '요지'), _art('새 둘')]
    OLD = [_art('옛 가'), _art('옛 나'), _art('옛 다')]

    def test_request_shape(self):
        rows = [{'id': 1, 'closest': 'B', 'same': True}, {'id': 2, 'closest': '0', 'same': False}]
        got, made, sent = _call([_Resp(rows)], self.NEW, self.OLD)
        self.assertEqual(got, [1, None])
        self.assertEqual(made, [{'api_key': 'key'}], '기본값이면 SDK 기본 제한')
        self.assertEqual(len(sent), 1)
        s = sent[0]
        self.assertEqual(s['model'], 'claude-haiku-4-5-20251001')
        self.assertEqual(s['temperature'], 0)
        self.assertEqual(s['system'], RUBRIC)
        self.assertEqual(s['tools'], [TOOL])
        self.assertEqual(s['tool_choice'], {'type': 'tool', 'name': 'record_matches'})
        self.assertEqual(s['max_tokens'], 300 + 260 * 2)
        self.assertEqual(s['messages'], [{'role': 'user', 'content': news_dedup.build_match_prompt(self.NEW, self.OLD)}])
        self.assertNotIn('thinking', s)

    def test_limits_passed(self):
        _, made, _ = _call([_Resp([])], self.NEW, self.OLD, timeout=20, max_retries=1)
        self.assertEqual(made, [{'api_key': 'key', 'timeout': 20, 'max_retries': 1}])

    def test_nothing_to_do_makes_no_client(self):
        for new, old, key in (([], self.OLD, 'k'), (self.NEW, [], 'k'), (self.NEW, self.OLD, '')):
            got, made, sent = _call([], new, old, key=key)
            self.assertEqual((got, made, sent), (None, [], []))

    def test_split_calls_over_max_new(self):
        new = [_art(f'새 {k}') for k in range(14)]
        first = [{'id': k, 'closest': 'A', 'same': k == 12} for k in range(1, 13)]        # 12번째만 같음
        second = [{'id': 1, 'closest': 'C', 'same': True}, {'id': 2, 'closest': '0', 'same': False}]
        got, _, sent = _call([_Resp(first), _Resp(second)], new, self.OLD)
        self.assertEqual(len(sent), 2)
        self.assertEqual(got, [None] * 11 + [0, 2, None])
        self.assertIn('[새 기사 12건]', sent[0]['messages'][0]['content'])
        self.assertIn('[새 기사 2건]\n1. 새 12\n2. 새 13', sent[1]['messages'][0]['content'])
        self.assertTrue(all('[이미 알린 기사 3건]' in s['messages'][0]['content'] for s in sent), '기보도 목록은 같다')
        self.assertEqual([s['max_tokens'] for s in sent], [300 + 260 * 12, 300 + 260 * 2])

    def test_one_part_failing_leaves_its_items_unmatched(self):
        new = [_art(f'새 {k}') for k in range(13)]
        first = [{'id': 1, 'closest': 'A', 'same': True}]
        got, _, sent = _call([_Resp(first), RuntimeError('timeout')], new, self.OLD)
        self.assertEqual(got, [0] + [None] * 12)

    def test_total_failure_is_none(self):
        self.assertIsNone(_call([RuntimeError('x')], self.NEW, self.OLD)[0])
        self.assertIsNone(_call([_Resp([], stop='max_tokens')], self.NEW, self.OLD)[0], '잘린 응답은 믿지 않는다')
        self.assertIsNone(_call([_Resp(blocks=[mock.Mock(type='text', text='{}')])], self.NEW, self.OLD)[0], '도구 출력 없음')
        self.assertIsNone(_call([_Resp(rows='줄이 아님')], self.NEW, self.OLD)[0])

    def test_empty_results_means_no_match_not_failure(self):
        self.assertEqual(_call([_Resp([])], self.NEW, self.OLD)[0], [None, None])

    def test_trace_collects_rows(self):
        rows = [{'id': 1, 'peg': '계기', 'closest': 'A', 'closest_peg': '옛 계기', 'same': True}]
        trace = []
        _call([_Resp(rows)], self.NEW, self.OLD, trace=trace)
        self.assertEqual(trace, [(0, rows)])

    def test_prior_list_capped_at_letters(self):
        old = [_art(f'옛 {k}') for k in range(30)]
        _, _, sent = _call([_Resp([])], self.NEW, old)
        self.assertIn('[이미 알린 기사 26건]', sent[0]['messages'][0]['content'])


# ── crawler._suppress_core — ①-2 ────────────────────────────────────────────────────────────────
def _prior(*rows):
    """rows = (제목, 몇 시간 전[, 요지[, 요약]]) — 최신순으로 정렬해 (prior, prior_at)."""
    rows = sorted(rows, key=lambda r: r[1])
    prior = [{'title': r[0], 'kw': extract_keywords(r[0]), 'event': r[2] if len(r) > 2 else '',
              'snip': r[3] if len(r) > 3 else ''} for r in rows]
    return prior, {r[0]: _ago(r[1]) for r in rows}


class _Match:
    """match_fn 가짜 — pick(새 제목, 기보도 제목들) → 기보도 제목 | None. 호출을 calls에."""

    def __init__(self, pick=None, fail=False):
        self.pick, self.fail, self.calls = pick or {}, fail, []

    def __call__(self, new, old):
        self.calls.append((new, old))
        if self.fail:
            return None
        titles = [o['title'] for o in old]
        return [titles.index(self.pick[n['title']]) if self.pick.get(n['title']) in titles else None for n in new]


def _core(items, prior, prior_at, chain=None, match=None, sem=None, share=None, group_fn=None):
    return crawler._suppress_core(items, prior, prior_at, chain or {}, group_fn, log=None, remind_share=share,
                                  match_fn=match, sem_titles=sem)


class TestCoreMatching(unittest.TestCase):

    def test_only_alerted_priors_offered_ranked_by_overlap_then_recency(self):
        prior, at = _prior(('알뜰폰 도매대가 협상 타결', 2), ('기지국 전력 절감 기술 공개', 3),
                           ('알뜰폰 도매대가 인하 요구 성명', 5), ('위성 통신 사업자 선정', 8),
                           ('억제됐던 알뜰폰 도매대가 기사', 1), ('실행내 묶였던 알뜰폰 기사', 4))
        chain = {'억제됐던 알뜰폰 도매대가 기사': '알뜰폰 도매대가 협상 타결',
                 '실행내 묶였던 알뜰폰 기사': '알뜰폰 도매대가 인하 요구 성명'}
        m = _Match()
        # 제목만으로는 어느 기보도와도 낱말 공유 2개(알뜰폰·도매대가) — ① 문턱(3) 미달이라 ①-2로 온다
        new = {'title': '도매대가 놓고 알뜰폰 업계 반발', 'url': 'n1', 'event': '알뜰폰 업계 인하 요구 성명'}
        reps, sup, rem, _ = _core([new], prior, at, chain, m)
        self.assertEqual(len(m.calls), 1)
        sent_new, sent_old = m.calls[0]
        self.assertEqual([o['title'] for o in sent_old],
                         ['알뜰폰 도매대가 인하 요구 성명',      # 제목+요지 낱말 공유 5(알뜰폰·도매대가·인하·요구·성명)
                          '알뜰폰 도매대가 협상 타결',           # 공유 2
                          '기지국 전력 절감 기술 공개',          # 공유 0 — 최신순으로 채운다
                          '위성 통신 사업자 선정'])             # 억제·실행내 묶음 기사(사슬에 있는 제목)는 없다
        self.assertEqual(sent_new, [{'title': new['title'], 'event': '알뜰폰 업계 인하 요구 성명', 'snip': ''}])
        self.assertEqual(([r['title'] for r in reps], sup, rem), ([new['title']], [], []))

    def test_candidate_cap_and_title_dedup(self):
        rows = [(f'기사 제목 {k}번', k + 1) for k in range(15)] + [('기사 제목 0번', 20)]      # 같은 제목은 한 번
        prior, at = _prior(*rows)
        m = _Match()
        _core([{'title': '전혀 다른 새 기사', 'url': 'n'}], prior, at, {}, m)
        olds = [o['title'] for o in m.calls[0][1]]
        self.assertEqual(len(olds), news_dedup.MATCH_MAX_PRIOR)
        self.assertEqual(olds, [f'기사 제목 {k}번' for k in range(10)], '공유가 같으면 최신순')

    def test_text_fields_forwarded(self):
        prior, at = _prior(('옛 기사', 2, '옛 요지', '옛 요약'))
        m = _Match()
        _core([{'title': '새 기사', 'url': 'n', 'event': '새 요지', 'screen_text': '검색 요약', 'content': '본문'},
               {'title': '새 기사 둘', 'url': 'n2', 'content': '본문만'}], prior, at, {}, m)
        self.assertEqual(m.calls[0][0], [{'title': '새 기사', 'event': '새 요지', 'snip': '검색 요약'},
                                         {'title': '새 기사 둘', 'event': '', 'snip': '본문만'}])
        self.assertEqual(m.calls[0][1], [{'title': '옛 기사', 'event': '옛 요지', 'snip': '옛 요약'}])

    def test_fresh_match_suppresses_with_semantic_row(self):
        prior, at = _prior(('통신업계, 네팔 홍수 복구 지원…구호인력 로밍 무료', 1))
        new = {'title': '이통3사, 네팔 구호인력 로밍요금 전액면제', 'url': 'n'}
        reps, sup, rem, _ = _core([new], prior, at, {}, _Match({new['title']: prior[0]['title']}))
        self.assertEqual((reps, rem), ([], []))
        self.assertEqual(sup, [{'article_title': new['title'], 'article_url': 'n', 'matched_title': prior[0]['title'],
                                'shared_keywords': '[의미판정] 구호인력,네팔'}])
        self.assertNotIn('_remind', new)

    def test_stale_match_is_reminder_and_gate_applies(self):
        prior, at = _prior(('통신업계, 네팔 홍수 복구 지원…구호인력 로밍 무료', 30))
        new = {'title': '이통3사, 네팔 구호인력 로밍요금 전액면제', 'url': 'n'}
        m = _Match({new['title']: prior[0]['title']})
        reps, sup, rem, _ = _core([new], prior, at, {}, m)
        self.assertEqual(([r.get('_remind') for r in reps], sup), (['2일째'], []))
        self.assertEqual(rem, [{'article_title': new['title'], 'article_url': 'n', 'matched_title': prior[0]['title'],
                                'shared_keywords': '[리마인드] 2일째'}])
        new2 = dict(new, url='n2')
        new2.pop('_remind', None)
        reps, sup, rem, _ = _core([new2], prior, at, {}, m, share=lambda a, b: (1, 10))
        self.assertEqual((reps, rem), ([], []))
        self.assertEqual(sup[0]['shared_keywords'], '[리마인드보류] 1/10')

    def test_handed_keyword_match_is_decided_by_the_match(self):
        """T18: ①이 대표 40시간 전 기사에 키워드로 건 기사 — ①은 🔁를 정하지 않고 ①-2에 넘긴다. 그 대표는 후보 맨 앞.
        같은 소식 + 24시간 안 대표 → '[의미판정]' 억제 한 줄 · 같은 소식 + 넘은 대표 → 🔁 한 줄(matched_title = 그 대표) ·
        대조가 없으면 표시 없는 알림(기록 없음). 종전에는 ①이 먼저 🔁로 정하고 ①-2가 그것을 거두거나 두었다."""
        prior, at = _prior(('KT 펨토셀 과징금 행정소송 검토…의결서 수령', 2),
                           ('통신사 과징금 법정 공방 본격화 전망', 40), ('다른 매체의 같은 소식 첫 보도', 50))
        new = {'title': '통신사 과징금 법정 공방 본격화…쟁점은 관련매출', 'url': 'n'}
        self.assertGreaterEqual(len(extract_keywords(new['title']) & prior[1]['kw']), 3, '①이 옛 기사(40시간)에 건다')
        reps, sup, rem, _ = _core([dict(new)], prior, at, {}, None)
        self.assertEqual(([r.get('_remind') for r in reps], sup, rem), ([None], [], []), '대조가 없으면 표시 없는 알림')
        it = dict(new)
        m = _Match({new['title']: prior[0]['title']})
        reps, sup, rem, _ = _core([it], prior, at, {}, m)
        self.assertEqual([o['title'] for o in m.calls[0][1]][0], prior[1]['title'], '걸린 사건의 대표가 후보 맨 앞')
        self.assertEqual((reps, rem), ([], []))
        self.assertEqual([r['shared_keywords'][:6] for r in sup], ['[의미판정]'])
        self.assertEqual(sup[0]['matched_title'], prior[0]['title'])
        self.assertNotIn('_remind', it)
        for pick, label in ((prior[1]['title'], '2일째'), (prior[2]['title'], '3일째')):
            reps, sup, rem, _ = _core([dict(new)], prior, at, {}, _Match({new['title']: pick}))
            self.assertEqual(([r.get('_remind') for r in reps], sup), ([label], []))
            self.assertEqual([(r['matched_title'], r['shared_keywords']) for r in rem], [(pick, f'[리마인드] {label}')],
                             '리마인드 기록은 한 줄, matched_title = ①-2가 고른 알림 나간 대표')

    def test_failure_none_fn_or_no_priors_pass_everything(self):
        prior, at = _prior(('통신업계, 네팔 홍수 복구 지원…구호인력 로밍 무료', 1))
        new = {'title': '이통3사, 네팔 구호인력 로밍요금 전액면제', 'url': 'n'}
        for match in (None, _Match(fail=True), _Match()):
            reps, sup, rem, _ = _core([dict(new)], prior, at, {}, match)
            self.assertEqual(([r['title'] for r in reps], sup, rem), ([new['title']], [], []))
        m = _Match({new['title']: prior[0]['title']})
        _core([dict(new)], prior, at, {prior[0]['title']: '더 옛 기사'}, m)
        self.assertEqual(m.calls, [], '알림으로 나간 기사가 하나도 없으면 부르지 않는다')

    def test_out_of_range_answers_ignored(self):
        prior, at = _prior(('옛 기사 하나', 1))
        for bad in ([5], [-1], ['A'], [None, 0], []):
            reps, sup, rem, _ = _core([{'title': '새 기사', 'url': 'n'}], prior, at, {}, lambda n, o, b=bad: b)
            self.assertEqual((len(reps), sup), (1, []), bad)

    def test_group_fn_is_only_the_in_run_second_pass(self):
        """group_fn(묶기 분류기)은 기보도와의 대조에 쓰이지 않는다 — 같은 실행분 대표들의 제목만 받는다."""
        prior, at = _prior(('위성 통신 신규 사업자 선정', 5))
        seen = []

        def group_fn(titles):
            seen.append(list(titles))
            return [[0, 1]]
        items = [{'title': '위성통신 새 사업자 뽑았다', 'url': 'a'}, {'title': '알뜰폰 요금제 전면 개편', 'url': 'b'}]
        reps, sup, rem, merged = _core(items, prior, at, {}, None, group_fn=group_fn)
        self.assertEqual(seen, [['위성통신 새 사업자 뽑았다', '알뜰폰 요금제 전면 개편']])
        self.assertEqual(([r['title'] for r in reps], merged), (['위성통신 새 사업자 뽑았다'], 1))
        self.assertEqual([r['shared_keywords'] for r in sup], ['[실행내묶음]'])

    def test_inherited_reminder_row_is_written_on_the_representative(self):
        """리마인드 기사가 같은 실행의 다른 대표에 묶이면 🔁는 대표가 이어받고, '[리마인드]' 기록도 대표(실제로 나가는 기사)에
        남는다(#263-보론). 묶인 기사에는 '[실행내묶음]' 한 줄만 — 종전에는 묶인 기사에 두 줄이 찍혀 사내 다리가 대표에 🔁를 못 달았다."""
        prior, at = _prior(('주파수 경매 일정 연기 발표', 30))
        rep = {'title': '정부, 5G 추가 할당 계획 다시 짠다', 'url': 'r'}
        mem = {'title': '주파수 경매 일정 연기 발표 이후 업계 반응', 'url': 'm'}        # ①이 30시간 전 기사에 건다 → 넘김
        same = _Match({mem['title']: prior[0]['title']})                              # → ①-2가 같은 소식 → 리마인드
        reps, sup, rem, merged = _core([rep, mem], prior, at, {}, same, group_fn=lambda titles: [[0, 1]])
        self.assertEqual(([r['title'] for r in reps], merged), ([rep['title']], 1))
        self.assertEqual(rep.get('_remind'), '2일째')
        self.assertEqual(rem, [{'article_title': rep['title'], 'article_url': 'r', 'matched_title': prior[0]['title'],
                                'shared_keywords': '[리마인드] 2일째'}])
        self.assertEqual(sup, [{'article_title': mem['title'], 'article_url': 'm', 'matched_title': rep['title'],
                                'shared_keywords': '[실행내묶음]'}])
        # 받는 단위 기록(subscriber_alert_log)도 대표 행에 '어느 옛 기사의 리마인드인지'가 채워진다
        rows, _ = crawler._alert_log_rows('t:1', '긴급', reps, sup, rem, {'r': 'id-r', 'm': 'id-m'})
        got = {r['article_title']: (r['outcome'], r['matched_title'], r['shared_keywords']) for r in rows}
        self.assertEqual(got, {rep['title']: ('remind', prior[0]['title'], '[리마인드] 2일째'),
                               mem['title']: ('merged', rep['title'], '[실행내묶음]')})

    def test_merged_reminders_leave_one_reminder_row(self):
        """대표도 리마인드이고 묶인 기사도 리마인드면 '[리마인드]' 기록은 대표의 한 줄만 남는다(나간 것은 한 통)."""
        prior, at = _prior(('주파수 경매 일정 연기 발표', 30))
        a = {'title': '주파수 경매 일정 연기 발표 이후 업계 반응', 'url': 'a'}
        b = {'title': '주파수 경매 일정 연기 발표에 통신사 촉각', 'url': 'b'}
        c = {'title': '주파수 경매 일정 연기 발표 배경은', 'url': 'c'}
        same = _Match({x['title']: prior[0]['title'] for x in (a, b, c)})
        reps, sup, rem, merged = _core([a, b, c], prior, at, {}, same)
        self.assertEqual((len(reps), merged), (1, 2), '셋 다 넘김 → ①-2 리마인드 → 실행내 묶음으로 대표 하나')
        self.assertEqual(reps[0].get('_remind'), '2일째')
        self.assertEqual([(r['article_title'], r['shared_keywords']) for r in rem],
                         [(reps[0]['title'], '[리마인드] 2일째')])
        self.assertEqual(sorted(r['shared_keywords'] for r in sup), ['[실행내묶음]', '[실행내묶음]'])
        self.assertEqual({r['matched_title'] for r in sup}, {reps[0]['title']})
        self.assertNotIn(reps[0]['title'], {r['article_title'] for r in sup})


class TestSemanticLinksAreNotKeywordEvidence(unittest.TestCase):
    """의미 판정으로 억제된 기사와 그 뒤에 매달려 억제된 기사는 ① 키워드 비교군에서 빠진다 — AI가 한 번 틀려도 같은 사건의
    다음 기사가 다시 심사받아 나간다(09-21 LGU+ 서버 폐기: 첫 기사가 잘못 묶이자 뒤 14건이 전부 그 기사에 걸려 알림 0통)."""
    FIRST = 'LG유플러스 해킹 정황에도 서버 폐기…경찰 수사 장기화'
    SECOND = 'LG유플러스 해킹 의혹 서버 폐기·OS 재설치…경찰 수사 10개월째'
    OTHER = '해킹 은폐 주시하는 국회…통신사는 좌불안석'
    NEW = {'title': 'LG유플러스 해킹 은폐 의혹 경찰 수사 10개월째…서버 폐기 경위 조사', 'url': 'n'}

    def setUp(self):
        # OTHER(5시간 전, 알림으로 나감) ← FIRST(의미 판정으로 묶여 억제) ← SECOND(FIRST에 키워드로 걸려 억제)
        self.prior, self.at = _prior((self.SECOND, 1), (self.FIRST, 2), (self.OTHER, 5))
        self.chain = {self.FIRST: self.OTHER, self.SECOND: self.FIRST}

    def test_without_marks_the_whole_event_is_swallowed(self):
        """표식을 모르면(옛 동작) 새 기사는 억제된 SECOND에 키워드로 걸리고, 사슬 뿌리(OTHER)가 24시간 안이라 억제된다."""
        reps, sup, rem, _ = _core([dict(self.NEW)], self.prior, self.at, self.chain, _Match())
        self.assertEqual((reps, rem), ([], []))
        self.assertEqual([(r['matched_title'], r['shared_keywords'].startswith('[')) for r in sup], [(self.SECOND, False)])

    def test_semantic_mark_removes_article_and_its_followers_from_keyword_pool(self):
        m = _Match()
        reps, sup, rem, _ = _core([dict(self.NEW)], self.prior, self.at, self.chain, m, sem={self.FIRST})
        self.assertEqual(([r['title'] for r in reps], sup, rem), ([self.NEW['title']], [], []),
                         '의미 판정 고리에 매달린 두 기사는 키워드 근거가 아니다 → 새 기사는 알림으로')
        self.assertEqual([o['title'] for o in m.calls[0][1]], [self.OTHER], '대조는 알림으로 나간 기사하고만')

    def test_keyword_only_chain_still_suppresses(self):
        chain = {self.SECOND: self.FIRST}                       # FIRST는 알림으로 나갔고 SECOND는 키워드로 억제
        reps, sup, rem, _ = _core([dict(self.NEW)], self.prior, self.at, chain, _Match(), sem=set())
        self.assertEqual(reps, [])
        self.assertFalse(sup[0]['shared_keywords'].startswith('['), '키워드 억제 그대로')

    def test_cycle_in_chain_terminates(self):
        """사슬이 서로를 가리켜도 멈춘다(같은 제목의 기사가 다시 수집된 경우) — 고리에 의미 판정이 없으면 키워드 근거 그대로."""
        chain = {self.FIRST: self.SECOND, self.SECOND: self.FIRST}
        reps, sup, rem, _ = _core([dict(self.NEW)], self.prior, self.at, chain, _Match(), sem={'없는 제목'})
        self.assertEqual(len(reps) + len(sup), 1)
        chain = {self.FIRST: self.SECOND, self.SECOND: self.FIRST}
        reps, sup, rem, _ = _core([dict(self.NEW)], self.prior, self.at, chain, _Match(), sem={self.SECOND})
        self.assertEqual(([r['title'] for r in reps], sup), ([self.NEW['title']], []), '고리 안에 의미 판정이 있으면 둘 다 빠진다')


class TestPlumbing(unittest.TestCase):

    def test_sem_titles_from_log(self):
        rows = [{'article_title': '가', 'shared_keywords': '[의미판정] AI'},
                {'article_title': '나', 'shared_keywords': 'a,b,c'},
                {'article_title': '다', 'shared_keywords': '[실행내묶음]'},
                {'article_title': '라', 'shared_keywords': '[리마인드] 2일째'},
                {'article_title': '마', 'shared_keywords': '[대체] [의미판정] x'},
                {'article_title': '', 'shared_keywords': '[의미판정] y'},
                {'article_title': '바', 'shared_keywords': None}]
        self.assertEqual(crawler._sem_titles_from_log(rows), {'가', '마'})
        self.assertEqual(crawler._sem_titles_from_log(None), set())

    def test_prior_entries_carry_event_and_snippet(self):
        rows = [{'title': '제목', 'url': 'u1', 'created_at': _ago(1), 'event': '요지', 'screen_text': '요약'},
                {'title': '옛 조회 모양', 'url': 'u2', 'created_at': _ago(2)},
                {'title': '자기 자신', 'url': 'me', 'created_at': _ago(0)}]
        prior, at = crawler._prior_entries(rows, {'me'})
        self.assertEqual([(p['title'], p['event'], p['snip']) for p in prior], [('제목', '요지', '요약'), ('옛 조회 모양', '', '')])
        self.assertEqual(set(at), {'제목', '옛 조회 모양'})

    def test_memo_reuses_by_titles_and_counts_real_calls(self):
        calls = []

        def fake(new, old, key, **kw):
            calls.append(kw)
            return [0] * len(new)
        n, o = [_art('새')], [_art('옛')]
        with mock.patch.object(news_dedup, 'match_prior_reports', fake), mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'), \
                mock.patch.dict(crawler._MATCH_MEMO, {}, clear=True):
            a = crawler._match_prior_memo(n, o)
            a.append(99)                                                # 돌려준 값을 고쳐도 메모는 그대로
            counter = [0]
            b = crawler._match_prior_memo([dict(n[0], snip='다른 요약')], o, timeout=20, max_retries=1, counter=counter)
            c = crawler._match_prior_memo(n, [_art('옛 둘')], timeout=20, max_retries=1, counter=counter)
        self.assertEqual((b, c), ([0], [0]))
        self.assertEqual(calls, [{}, {'timeout': 20, 'max_retries': 1}], '제목 목록이 같으면 호출 0')
        self.assertEqual(counter, [1])

    def test_memo_keeps_failure(self):
        calls = []
        with mock.patch.object(news_dedup, 'match_prior_reports', lambda *a, **k: calls.append(1)), \
                mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'), mock.patch.dict(crawler._MATCH_MEMO, {}, clear=True):
            self.assertIsNone(crawler._match_prior_memo([_art('새')], [_art('옛')]))
            self.assertIsNone(crawler._match_prior_memo([_art('새')], [_art('옛')]))
        self.assertEqual(len(calls), 1)

    def test_wiring(self):
        src = inspect.getsource(crawler.suppress_repeat_alerts)
        self.assertIn("select('title,url,created_at,event,screen_text')", src)
        self.assertIn('_sem_titles_from_log(_lg)', src)
        self.assertIn('match_fn = _match_prior_memo if (ANTHROPIC_API_KEY and chain_ok) else None', src)
        self.assertIn('match_fn=match_fn, sem_titles=sem_titles', src)
        unit = inspect.getsource(crawler._aud_compute)
        self.assertIn('chain, sem_titles, chain_ok = _audience_chain(aud, ch)', unit)
        self.assertIn('match_fn=match_fn if chain_ok else None, sem_titles=sem_titles', unit)
        self.assertIn('event,screen_text', crawler._ALERT_WINDOW_COLS)
        self.assertIn('event,screen_text', crawler._ALERT_LATE_COLS)
        self.assertIn('_MATCH_MEMO.clear()', inspect.getsource(crawler._reset_audience_state))

    def test_audience_chain_returns_links_marks_and_ok(self):
        rows = [{'article_title': '가', 'matched_title': '나', 'shared_keywords': '[의미판정] x'},
                {'article_title': '다', 'matched_title': '라', 'shared_keywords': '[실행내묶음]'}]
        with mock.patch.object(crawler, '_fetch_pages', lambda q: rows):
            self.assertEqual(crawler._audience_chain('t:2', '긴급'), ({'가': '나', '다': '라'}, {'가'}, True))

        def boom(q):
            raise RuntimeError('db down')
        with mock.patch.object(crawler, '_fetch_pages', boom), mock.patch('builtins.print'):
            self.assertEqual(crawler._audience_chain('t:2', '긴급'), ({}, set(), False))


class TestFixture(unittest.TestCase):
    """실측 고정 자료(tools_dedup_probe.py가 읽는다)의 모양 — 손으로 고치다 깨지는 것을 막는다."""

    def test_shape(self):
        with open(os.path.join(_ROOT, 'tests', 'fixtures', 'dedup_match_cases.json'), encoding='utf-8') as f:
            fx = json.load(f)
        self.assertEqual(fx['schema'], 'dedup-match/1')
        arts, runs = fx['articles'], fx['runs']
        self.assertEqual((len(runs), sum(len(r['new']) for r in runs)), (173, 267))
        nos = [n['no'] for r in runs for n in r['new']]
        self.assertEqual(len(nos), len(set(nos)))
        for r in runs:
            self.assertLessEqual(len(r['cand']), news_dedup.MATCH_MAX_PRIOR)
            for c in r['cand']:
                self.assertLess(arts[c]['at'], r['t'], '후보는 그 실행보다 앞선 기사')
            for n in r['new']:
                self.assertIn(n['id'], arts)
                self.assertIn(n['gtype'], ('hard', 'soft', 'zero', 'zero+'))
                self.assertTrue(set(n['targets']) <= set(r['cand']))
                self.assertEqual(bool(n['targets']), n['gtype'] != 'zero')
        for a in arts.values():
            self.assertTrue(a['title'])
            self.assertLessEqual(len(a['snip']), news_dedup.MATCH_SNIP)


if __name__ == '__main__':
    unittest.main()
