# -*- coding: utf-8 -*-
"""긴급도 2차 확인(2단 구조, #268) — 네트워크 없이.

  · 2차 호출은 실측 도구 tools_urgency_probe의 G1 호출과 **인자 단위로 같아야 한다**(잰 것 = 돌리는 것, 판정 2절).
    도구 정의·지시 줄은 지문으로도 잠근다 — 둘을 함께 고쳐도 이 시험이 멈춘다. 고칠 때는 G1부터 다시 잰다(#267).
  · 1차 호출(classify_urgency)의 요청은 #268 전과 같다(인자 묶음만 공통 함수로 옮김).
  · grade_urgency: 그림자 = 세 칸 저장·등급 불변 / on = 타영역이면 보통 → 낱말 하한 / 건너뜀(낱말 하한 긴급·사람 사례) /
    실패는 긴급 그대로 / 모든 행의 키 집합이 같다(벌크 upsert, #82·#222).
"""
import hashlib
import io
import contextlib
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import crawler                      # noqa: E402
import tools_urgency_probe as P     # noqa: E402

LOCK = 'f195948babcbc0fe2d0274b0fa40bf33a7b44f214565c2ce18d3ba450524f077'
CHECK_KEYS = ('urgency_check_scope', 'urgency_check_grade', 'urgency_check_basis', 'urgency_check_capped')


class _FakeClient:
    """anthropic.Anthropic 자리 — messages.create 인자를 기록하고 정해 둔 응답(또는 예외)을 돌려준다."""
    calls = []

    def __init__(self, resp=None, exc=None):
        self._resp, self._exc = resp, exc
        self.messages = SimpleNamespace(create=self._create)
        self.init_kw = None

    def _create(self, **kw):
        _FakeClient.calls.append(kw)
        if self._exc:
            raise self._exc
        return self._resp


def _tool_resp(scope='통신', grade='즉시대응', basis='제도', stop='tool_use'):
    return SimpleNamespace(content=[SimpleNamespace(type='tool_use', input={'scope': scope, 'grade': grade, 'basis': basis})],
                           stop_reason=stop, usage=None)


def _quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


class TestCheckPromptIsProbeG1(unittest.TestCase):
    def test_tool_and_lines_equal_probe(self):
        self.assertEqual(crawler._URGENCY_CHECK_TOOL, P.urgency_tool('sgb'))
        self.assertEqual(json.dumps(crawler._URGENCY_CHECK_TOOL, ensure_ascii=False),
                         json.dumps(P.urgency_tool('sgb'), ensure_ascii=False), '칸 순서까지 같아야 한다(생성 순서)')
        self.assertEqual(crawler._URGENCY_CHECK_LINE, P.TOOL_LINE)
        self.assertEqual(crawler._URGENCY_WORD_LINE, P.WORD_LINE)
        self.assertEqual(crawler._URGENCY_CHECK_SCOPES, tuple(P.SCOPES))
        self.assertEqual(crawler._URGENCY_CHECK_BASES, tuple(P.BASES))
        intro = crawler._URGENCY_SYSTEM[:len(crawler._URGENCY_SYSTEM) - len(crawler._URGENCY_CRITERIA)]
        self.assertEqual(crawler._URGENCY_CHECK_SYSTEM, P.intro_of(intro, 'cur', 'sgb') + crawler._URGENCY_CRITERIA)

    def test_lock(self):
        s = json.dumps(crawler._URGENCY_CHECK_TOOL, ensure_ascii=False, sort_keys=True) + '\n' + crawler._URGENCY_CHECK_LINE
        self.assertEqual(hashlib.sha256(s.encode('utf-8')).hexdigest(), LOCK,
                         '2차 확인 도구·지시 줄이 바뀌었다 — tools_urgency_probe G1로 다시 잰 뒤에만 지문을 고친다(#267·#268)')

    def test_request_equals_probe_judge(self):
        """같은 기사·같은 블록이면 운영 2차 호출과 실측 도구 G1 호출의 인자가 같다."""
        fixed, sim = '\n\n[담당자 분류 피드백 — 고정]\n- "가" → 금주검토', '\n\n[이 기사와 제목이 거의 같은 …]\n- "나" → 동향파악'
        title, body, summ = '정부, 5G 주파수 재할당 대가 확정', '과기정통부가 … 본문 ' * 40, '요약'
        _FakeClient.calls = []
        with mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'), \
                mock.patch.object(crawler, '_feedback_fixed_block', lambda: fixed), \
                mock.patch.object(crawler, '_feedback_similar_block', lambda t: sim), \
                mock.patch.object(crawler.anthropic, 'Anthropic', lambda **kw: _FakeClient(_tool_resp())):
            got = _quiet(crawler.urgency_second_check, title, body, summ)
        self.assertEqual(got, {'scope': '통신', 'grade': '긴급', 'basis': '제도'})
        prod = _FakeClient.calls[-1]
        intro = crawler._URGENCY_SYSTEM[:len(crawler._URGENCY_SYSTEM) - len(crawler._URGENCY_CRITERIA)]
        item = {'sys': P.intro_of(intro, 'cur', 'sgb') + crawler._URGENCY_CRITERIA + fixed, 'sim': sim,
                'tool': P.urgency_tool('sgb'), 'user': P.user_msg({'title': title, 'content': body, 'screen_text': summ}),
                'max_tokens': 150}
        _FakeClient.calls = []
        _quiet(P.judge, _FakeClient(_tool_resp()), item)
        self.assertEqual(prod, _FakeClient.calls[-1])


class TestFirstCallUnchanged(unittest.TestCase):
    def test_classify_request(self):
        _FakeClient.calls = []
        resp = SimpleNamespace(content=[SimpleNamespace(type='text', text='즉시대응')], usage=None)
        with mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'), \
                mock.patch.object(crawler, '_feedback_fixed_block', lambda: 'F'), \
                mock.patch.object(crawler, '_feedback_similar_block', lambda t: ''), \
                mock.patch.object(crawler.anthropic, 'Anthropic', lambda **kw: _FakeClient(resp)):
            self.assertEqual(crawler.classify_urgency('제목', '본문 ' * 100, ''), '긴급')
        kw = _FakeClient.calls[-1]
        self.assertEqual(set(kw), {'model', 'max_tokens', 'temperature', 'system', 'messages'}, '1차는 도구 없이 한 낱말')
        self.assertEqual((kw['model'], kw['max_tokens'], kw['temperature']), ('claude-haiku-4-5-20251001', 10, 0))
        self.assertEqual(kw['system'], [{'type': 'text', 'text': crawler._URGENCY_SYSTEM + 'F',
                                         'cache_control': {'type': 'ephemeral', 'ttl': '1h'}}])
        self.assertIn(crawler._URGENCY_WORD_LINE, kw['system'][0]['text'])


class TestSecondCheckFunction(unittest.TestCase):
    def _run(self, client=None, similar='', key='k'):
        made = []

        def factory(**kw):
            made.append(kw)
            return client
        with mock.patch.object(crawler, 'ANTHROPIC_API_KEY', key), \
                mock.patch.object(crawler, '_feedback_fixed_block', lambda: ''), \
                mock.patch.object(crawler, '_feedback_similar_block', lambda t: similar), \
                mock.patch.object(crawler.anthropic, 'Anthropic', factory):
            return _quiet(crawler.urgency_second_check, '제목', '본문', ''), made

    def test_no_key_no_call(self):
        got, made = self._run(key='')
        self.assertIsNone(got)
        self.assertEqual(made, [])

    def test_human_urgent_similar_skips_without_call(self):
        sim = '\n\n[이 기사와 제목이 거의 같은 담당자 수정 사례 — 같은 사건의 기사면 이 등급을 따른다]\n- "SKT 해킹 후속" → 즉시대응'
        got, made = self._run(similar=sim)
        self.assertEqual(got, {'skip': 'human'})
        self.assertEqual(made, [])
        sim2 = sim.replace('즉시대응', '금주검토')
        got, made = self._run(client=_FakeClient(_tool_resp('타영역', '동향파악', '없음')), similar=sim2)
        self.assertEqual(got, {'scope': '타영역', 'grade': '참고', 'basis': '없음'})
        self.assertEqual(made[0].get('timeout'), crawler.URGENCY_CHECK_TIMEOUT_S)

    def test_bad_value_no_tool_and_error_are_none(self):
        self.assertIsNone(self._run(client=_FakeClient(_tool_resp(scope='모름')))[0])
        self.assertIsNone(self._run(client=_FakeClient(_tool_resp(grade='긴급')))[0])
        text_only = SimpleNamespace(content=[SimpleNamespace(type='text', text='즉시대응')], stop_reason='end_turn')
        self.assertIsNone(self._run(client=_FakeClient(text_only))[0])
        self.assertIsNone(self._run(client=_FakeClient(exc=RuntimeError('529')))[0])

    def test_similar_has_human_urgent(self):
        f = crawler._similar_has_human_urgent
        self.assertFalse(f(''))
        self.assertTrue(f('\n\n[머리]\n- "가" → 금주검토\n- "나" → 즉시대응'))
        self.assertFalse(f('\n\n[머리 → 즉시대응]\n- "가" → 동향파악'), '머리말 글자는 사례 줄이 아니다')


class TestGradeUrgencyCheck(unittest.TestCase):
    RULES = [{'id': 'r_min_urgent', 'mode': 'min', 'level': '긴급', 'any_words': ['국감증인']},
             {'id': 'r_min_normal', 'mode': 'min', 'level': '보통', 'any_words': ['SKT']},
             {'id': 'r_set', 'mode': 'set', 'level': '참고', 'any_words': ['부고']}]

    def setUp(self):
        self._p = mock.patch.dict(crawler._URGENCY_SUMMARY, {}, clear=True)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def _grade(self, items, ai, check, mode='shadow'):
        calls = []

        def chk(t, c, s):
            calls.append(t)
            return check(t) if callable(check) else check
        with mock.patch.object(crawler, 'URGENCY_CHECK_MODE', mode):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                crawler.grade_urgency(items, self.RULES, classify=lambda t, c, s: ai(t) if callable(ai) else ai, check=chk)
        return calls, out.getvalue()

    def test_shadow_stores_and_keeps_grade(self):
        items = [{'title': '드론 배송 실증', 'url': 'u1'}, {'title': '기지국 장애', 'url': 'u2'}]
        res = {'드론 배송 실증': {'scope': '타영역', 'grade': '참고', 'basis': '없음'},
               '기지국 장애': {'scope': '통신', 'grade': '긴급', 'basis': '통신사·통신망 사고'}}
        calls, log = self._grade(items, '긴급', lambda t: res[t])
        self.assertEqual(calls, ['드론 배송 실증', '기지국 장애'])
        self.assertEqual([i['urgency'] for i in items], ['긴급', '긴급'], '그림자는 등급을 안 바꾼다')
        self.assertEqual([(i['urgency_check_scope'], i['urgency_check_grade'], i['urgency_check_basis'],
                           i['urgency_check_capped']) for i in items],
                         [('타영역', '참고', '없음', False), ('통신', '긴급', '통신사·통신망 사고', False)])
        self.assertIn('[2차 확인] AI 긴급 2건 · 확인 2 · 타영역 1(그림자 — 등급 불변)', log)
        self.assertEqual(crawler._URGENCY_CHECK_RUN.get('called'), 2)

    def test_on_caps_then_floor(self):
        items = [{'title': '드론 배송 실증', 'url': 'u1'},
                 {'title': 'SKT 드론 배송', 'url': 'u2'},           # 타영역 → 보통 → min 보통 하한(그대로 보통)
                 {'title': '기지국 장애', 'url': 'u3'}]
        calls, log = self._grade(items, '긴급', lambda t: {'scope': '통신' if '기지국' in t else '타영역',
                                                         'grade': '참고', 'basis': '없음'}, mode='on')
        self.assertEqual([i['urgency'] for i in items], ['보통', '보통', '긴급'])
        self.assertEqual([i['importance'] for i in items], ['보통', '보통', '긴급'])
        self.assertEqual([i['urgency_check_capped'] for i in items], [True, True, False])
        self.assertIn('(보통으로 내림)', log)

    def test_skips_and_non_urgent(self):
        items = [{'title': '국감증인 채택', 'url': 'u1'},      # 낱말 하한 긴급 → 건너뜀
                 {'title': '사람 사례 붙음', 'url': 'u2'},     # check가 skip 반환
                 {'title': '보통 기사', 'url': 'u3'},           # 1차가 긴급 아님 → 안 부름
                 {'title': '[부고] 누구', 'url': 'u4'}]         # set 규칙 → AI 없음
        ai = lambda t: '보통' if t == '보통 기사' else '긴급'
        calls, log = self._grade(items, ai, lambda t: {'skip': 'human'}, mode='on')
        self.assertEqual(calls, ['사람 사례 붙음'])
        self.assertEqual([i['urgency'] for i in items], ['긴급', '긴급', '보통', '참고'])
        for i in items:
            self.assertEqual([i[k] for k in CHECK_KEYS], [None] * 4)
        self.assertIn('건너뜀 규칙 1·사람 사례 1 · 실패 0', log)

    def test_failure_keeps_urgent(self):
        items = [{'title': 'A', 'url': 'u1'}, {'title': 'B', 'url': 'u2'}]
        calls, log = self._grade(items, '긴급', lambda t: None if t == 'A' else {'scope': '이상'}, mode='on')
        self.assertEqual([i['urgency'] for i in items], ['긴급', '긴급'])
        self.assertEqual([i['urgency_check_scope'] for i in items], [None, None])
        self.assertIn('실패 2', log)

    def test_breaker_stops_after_failures(self):
        items = [{'title': f'T{i}', 'url': f'u{i}'} for i in range(5)]
        calls, log = self._grade(items, '긴급', None, mode='on')
        self.assertEqual(len(calls), crawler.URGENCY_CHECK_MAX_FAIL, '실패가 쌓이면 그 실행의 나머지는 부르지 않는다')
        self.assertEqual([i['urgency'] for i in items], ['긴급'] * 5)
        self.assertIn('실패 5', log)

    def test_same_keys_every_row(self):
        items = [{'title': '드론', 'url': 'u1'}, {'title': '보통 기사', 'url': 'u2'}, {'title': '[부고] 누구', 'url': 'u3'}]
        self._grade(items, lambda t: '보통' if t == '보통 기사' else '긴급',
                    {'scope': '타영역', 'grade': '참고', 'basis': '없음'})
        self.assertEqual(len({frozenset(i) for i in items}), 1, '벌크 upsert는 모든 행의 키 집합이 같아야 한다')
        for k in CHECK_KEYS:
            self.assertIn(k, items[0])

    def test_injected_classify_without_check_never_calls_default(self):
        items = [{'title': '드론', 'url': 'u1'}]
        with mock.patch.object(crawler, 'urgency_second_check', side_effect=AssertionError('불리면 안 됨')):
            _quiet(crawler.grade_urgency, items, [], classify=lambda t, c, s: '긴급')
        self.assertEqual(items[0]['urgency'], '긴급')
        self.assertIsNone(items[0]['urgency_check_scope'])

    def test_default_check_follows_mode(self):
        items = [{'title': '드론', 'url': 'u1'}]
        seen = []
        with mock.patch.object(crawler, 'classify_urgency', lambda t, c='', s='': '긴급'), \
                mock.patch.object(crawler, 'urgency_second_check', lambda t, c='', s='': seen.append(t) or None):
            _quiet(crawler.grade_urgency, items, [])
            self.assertEqual(seen, ['드론'])
            with mock.patch.object(crawler, 'URGENCY_CHECK_MODE', 'off'):
                _quiet(crawler.grade_urgency, [dict(items[0])], [])
            self.assertEqual(seen, ['드론'], "'off'면 2차 호출 없음")

    def test_mode_is_on(self):
        self.assertEqual(crawler.URGENCY_CHECK_MODE, 'on', '운영자 결정 10-02 — 그림자 없이 켬(안전장치 ①②와 함께)')


class _Sb:
    """가짜 Supabase — 표·동작별 응답, 호출 기록. news_feed는 select·update 모두 rows를 돌려준다(선점 성공)."""

    def __init__(self, rows, subs=(), trows=(), fail=()):
        self.rows, self.subs, self.trows, self.fail, self.ops = rows, list(subs), list(trows), set(fail), []

    def table(self, name):
        return _Q(self, name)


class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.kind, self.payload = db, name, 'select', None

    def select(self, *a, **k):
        return self

    def update(self, p):
        self.kind, self.payload = 'update', p
        return self

    def insert(self, p):
        self.kind, self.payload = 'insert', p
        return self

    def upsert(self, p, **k):
        self.kind, self.payload = 'upsert', p
        return self

    def __getattr__(self, n):                    # eq·is_·gte·order·limit·in_
        return lambda *a, **k: self

    def execute(self):
        if (self.name, self.kind) in self.db.fail:
            raise RuntimeError(f'{self.name} {self.kind} down')
        self.db.ops.append((self.name, self.kind, self.payload))
        if self.name == 'news_feed':
            return SimpleNamespace(data=[dict(r) for r in self.db.rows])
        if self.name == 'telegram_subscribers':
            return SimpleNamespace(data=self.db.subs)
        if self.name == 'team_urgency':
            return SimpleNamespace(data=self.db.trows)
        if self.name == 'subscriber_alert_log' and self.kind == 'upsert':
            return SimpleNamespace(data=list(self.payload))
        return SimpleNamespace(data=[])


class TestSafeguards(unittest.TestCase):
    """운영자 결정(10-02) 안전장치 ① 내린 기사 운영자 봇 한 줄씩 ② 관리자가 다시 긴급으로 올리면 구독자 큐."""
    ROWS = [{'id': 'n1', 'title': '독파모 통합 계획', 'url': 'https://x/1', 'source': '甲', 'tags': ['ai'], 'urgency': '긴급',
             'published_at': None, 'origin': None, 'created_at': '2026-10-02T05:00:00+00:00'}]

    def _run(self, sb, sent=None):
        sent = [] if sent is None else sent
        with mock.patch.object(crawler, 'sb', sb), \
                mock.patch.object(crawler, 'TELEGRAM_CHAT_ID', 'op'), \
                mock.patch.object(crawler, '_URGENCY_RULES', [{'id': 'x'}]), \
                mock.patch.object(crawler, '_TEAM_RULES_ENABLED', {}), \
                mock.patch.object(crawler, '_TEAM_URGENCY_RULES', {}), \
                mock.patch.object(crawler.notify, 'send_telegram', lambda t, **k: sent.append(t) or True):
            return _quiet(crawler.restore_raised_checks), sent

    def test_capped_notice_one_line_each(self):
        sent = []
        items = [{'title': 'A <b>', 'url': 'https://a', 'urgency_check_capped': True},
                 {'title': 'B', 'url': 'https://b', 'urgency_check_capped': False},
                 {'title': 'C', 'url': '', 'urgency_check_capped': True}]
        with mock.patch.object(crawler, 'TELEGRAM_BOT_TOKEN', 't'), mock.patch.object(crawler, 'TELEGRAM_CHAT_ID', 'op'), \
                mock.patch.object(crawler.notify, 'send_telegram', lambda t, **k: sent.append((t, k)) or True):
            self.assertTrue(_quiet(crawler.send_check_capped_notice, items))
            self.assertFalse(_quiet(crawler.send_check_capped_notice, [items[1]]), '내린 기사가 없으면 안 보낸다')
        self.assertEqual(len(sent), 1)
        text, kw = sent[0]
        lines = [x for x in text.split('\n') if x.startswith('🔽')]
        self.assertEqual(lines, ['🔽 2차 확인에서 내림: <a href="https://a">A &lt;b&gt;</a>', '🔽 2차 확인에서 내림: C'])
        self.assertEqual(kw.get('parse_mode'), 'HTML')

    def test_restore_queues_common_and_units(self):
        subs = [{'team_id': 2, 'division': None, 'news_level': 'urgent'},
                {'team_id': 5, 'division': None, 'news_level': 'urgent'},
                {'team_id': None, 'division': None, 'news_level': 'urgent'}]
        trows = [{'news_id': 'n1', 'team_id': 5, 'urgency': '보통', 'source': 'human', 'rule_id': None}]   # 팀5는 내려 둠
        sb = _Sb(self.ROWS, subs, trows)
        n, sent = self._run(sb)
        claim = [p for t, k, p in sb.ops if t == 'news_feed' and k == 'update']
        self.assertEqual(len(claim), 1)
        self.assertIn('urgency_check_restored_at', claim[0])
        q = [p for t, k, p in sb.ops if t == 'subscriber_queue' and k == 'insert']
        self.assertEqual([[r['topic'] for r in part] for part in q], [['urgent'], ['news']])
        self.assertEqual((q[1][0]['audience'], q[1][0]['level'], q[1][0]['news_url']), ('t:2', '긴급', 'https://x/1'))
        logs = [p for t, k, p in sb.ops if t == 'subscriber_alert_log' and k == 'upsert']
        self.assertEqual([(r['audience'], r['outcome'], r['shared_keywords']) for part in logs for r in part],
                         [('t:2', 'sent', crawler._RESTORE_MARK)], '팀원이 내려 둔 팀(5)은 받지 않는다')
        self.assertEqual(n, 2)
        self.assertEqual(sent, ['🔼 다시 긴급 — 구독자에게 보냄: 독파모 통합 계획'])

    def test_restore_nothing_to_do(self):
        sb = _Sb([])
        n, sent = self._run(sb)
        self.assertEqual((n, sent), (0, []))
        self.assertEqual([k for t, k, p in sb.ops], ['select'], '대상이 없으면 조회 한 번')

    def test_restore_common_fail_reverts_claim(self):
        sb = _Sb(self.ROWS, fail={('subscriber_queue', 'insert')})
        n, sent = self._run(sb)
        self.assertEqual(n, 0)
        ups = [p for t, k, p in sb.ops if t == 'news_feed' and k == 'update']
        self.assertEqual(ups[-1], {'urgency_check_restored_at': None}, '공통 적재 실패면 선점을 되돌린다(다음 실행에서 다시)')

    def test_restore_query_fail_is_quiet(self):
        sb = _Sb(self.ROWS, fail={('news_feed', 'select')})
        self.assertEqual(self._run(sb), (0, []))


class TestDriftAndGuard(unittest.TestCase):
    def test_drift_due(self):
        f = crawler._check_drift_due
        self.assertFalse(f(9, 9, '', '2026-10-06'), '10건 미만은 안 본다')
        self.assertFalse(f(10, 4, '', '2026-10-06'), '40%는 넘어야')
        self.assertTrue(f(10, 5, '', '2026-10-06'))
        self.assertFalse(f(10, 5, '2026-10-06', '2026-10-06'), '하루 한 번')
        self.assertTrue(f(20, 9, '2026-10-05', '2026-10-06'))

    def test_drift_alert_needs_check_this_run(self):
        with mock.patch.dict(crawler._URGENCY_CHECK_RUN, {}, clear=True), \
                mock.patch.object(crawler, 'sb', None):
            self.assertFalse(crawler.urgency_check_drift_alert())

    def test_guarded_problems(self):
        f = crawler.guarded_rule_problems
        enabled = {'spectrum_policy': {'id': 'spectrum_policy', 'sentence_rev': 0}, 'other': {'id': 'other'}}
        self.assertEqual(f({'spectrum_policy': 0}, enabled), {})
        self.assertEqual(f({'spectrum_policy': 0}, {}), {'spectrum_policy': 'off'})
        self.assertEqual(f({'spectrum_policy': 0}, {'spectrum_policy': {'sentence_rev': 2}}), {'spectrum_policy': 'rev:2'})
        self.assertEqual(f({}, enabled), {})

    def _guard_run(self, cfg, enabled, send_ok=True):
        class Q:
            def __init__(s, db):
                s.db, s.up = db, None

            def select(s, *a):
                return s

            def in_(s, *a):
                return s

            def upsert(s, row, **k):
                s.up = row
                return s

            def execute(s):
                if s.up is not None:
                    s.db.writes.append(s.up)
                    return SimpleNamespace(data=[s.up])
                return SimpleNamespace(data=[{'key': k, 'value': v} for k, v in cfg.items()])

        class DB:
            writes = []

            def table(s, name):
                assert name == 'app_config'
                return Q(s)
        db, sent = DB(), []
        DB.writes = []
        with mock.patch.object(crawler, 'sb', db), \
                mock.patch.object(crawler, '_URGENCY_RULES', [{'id': 'x'}]), \
                mock.patch.object(crawler, '_TEAM_RULES_ENABLED', enabled), \
                mock.patch.object(crawler.notify, 'send_telegram', lambda t, **k: sent.append(t) or send_ok):
            n = _quiet(crawler.check_guarded_team_rules)
        return n, sent, DB.writes

    def test_guard_alerts_once_and_clears(self):
        cfg = {'guarded_team_rules': '{"spectrum_policy": 0}'}
        n, sent, writes = self._guard_run(cfg, {})
        self.assertEqual(n, 1)
        self.assertIn('「spectrum_policy」 규칙이 꺼졌거나 지워졌습니다', sent[0])
        self.assertEqual(json.loads(writes[-1]['value']), {'spectrum_policy': 'off'})
        cfg['guarded_team_rules_alerted'] = '{"spectrum_policy": "off"}'
        n, sent, writes = self._guard_run(cfg, {})
        self.assertEqual((n, sent, writes), (0, [], []), '같은 상태는 한 번만')
        n, sent, writes = self._guard_run(cfg, {'spectrum_policy': {'sentence_rev': 1}})
        self.assertIn('지킴 판 0 → 지금 판 1', sent[0])
        n, sent, writes = self._guard_run(cfg, {'spectrum_policy': {'sentence_rev': 0}})
        self.assertEqual((n, sent), (0, []))
        self.assertEqual(json.loads(writes[-1]['value']), {}, '고쳐지면 표시를 지운다')

    def test_guard_send_fail_no_mark_and_table_fail_skips(self):
        n, sent, writes = self._guard_run({'guarded_team_rules': '{"spectrum_policy": 0}'}, {}, send_ok=False)
        self.assertEqual((n, len(sent), writes), (0, 1, []))
        n, sent, writes = self._guard_run({'guarded_team_rules': '{"spectrum_policy": 0}'}, None)
        self.assertEqual((n, sent), (0, []), '표 조회 실패 실행은 판단하지 않는다')
        n, sent, writes = self._guard_run({'guarded_team_rules': '{"spectrum_policy": "0"}'}, {})
        self.assertEqual((n, sent), (0, []), '형식 오류는 건너뜀')


if __name__ == '__main__':
    unittest.main()
