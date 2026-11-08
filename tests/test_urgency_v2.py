# -*- coding: utf-8 -*-
"""긴급도 1차 판정 v2(2026-11-09 재설계 — local_docs/긴급도_내림원인_261109/설계_1차판정_재설계_261109.md) — 네트워크 없이.

  · v2 글·스키마·블록 머리말은 지문으로 잠근다 — 고치면 측정(tools_urgency_probe V2)부터 다시(설계 §5-3).
  · 운영과 측정이 같은 요청을 만든다(crawler.urgency_v2_request·urgency_v2_block2 = 탐침 V2) — 잰 것 = 돌리는 것.
  · 해석: 성공·거부·잘림·해석 실패·schema 밖·모순(즉시대응 ∧ 없음, 또는 그 반대), reason 40자.
  · 다수결: 표 1개 / 중앙값 / 1:1:1 = 보통 / 유효 2표는 같을 때만 / scope는 최종 등급 표 중 다수.
  · grade_urgency: v1(기본·지금 운영) = 종전 그대로 + 새 칸 키 / shadow = 운영 v1, v2는 기록 칸에만 / v2 = 영역 상한 min(등급, 보통)
    (올리지 않음) → 낱말 하한, check 칸은 v2 긴급 행에만, 실패는 v1 경로(라벨 classify_urgency_fallback), 차단기·예산.
  · 전파 on(꺼져 있음): prior 등급으로 내림 → min 하한, lowered_by·event_of, 합본 제외 ⓐⓑ, 복원 조회·마크·문구, 원인 prior 풀 제외.
  · A2 사건 연결 칸: 억제 결과의 대표 id(사슬 끝), 자기 자신 제외, 빈 칸만 쓴다.
"""
import contextlib
import hashlib
import inspect
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import api_usage                    # noqa: E402
import crawler                      # noqa: E402
import tools_urgency_probe as P     # noqa: E402

CHECK_KEYS = ('urgency_check_scope', 'urgency_check_grade', 'urgency_check_basis', 'urgency_check_capped')
NEW_KEYS = ('urgency_grader', 'urgency_v2_scope', 'urgency_v2_grade', 'urgency_v2_basis', 'urgency_reason',
            'urgency_lowered_by', 'urgency_event_of')


def _quiet(fn, *a, **k):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        r = fn(*a, **k)
    return r, out.getvalue()


def _resp(obj=None, text=None, stop='end_turn'):
    t = text if text is not None else json.dumps(obj, ensure_ascii=False)
    return SimpleNamespace(content=[SimpleNamespace(type='text', text=t)], stop_reason=stop, usage=None)


def _lock_text() -> str:
    return json.dumps({'schema': crawler.URGENCY_V2_SCHEMA, 'arms': crawler.URGENCY_V2_ARMS,
                       'heads': [crawler._URGENCY_V2_SEARCH_HEAD, crawler._URGENCY_V2_LOWERED_HEAD,
                                 crawler._URGENCY_V2_SIMILAR_HEAD],
                       'limits': [crawler.URGENCY_V2_SEARCH_MAX, crawler.URGENCY_V2_SEARCH_MIN, crawler.URGENCY_V2_LOWERED_MAX,
                                  crawler.URGENCY_V2_LOWERED_DAYS, crawler.URGENCY_V2_REASON_MAX]},
                      ensure_ascii=False, sort_keys=True)


# 스키마 + 팔 + 블록 머리말 + 상한의 지문 — 바꾸면 이 값도 바뀐다(tools_urgency_probe V2로 다시 잰 뒤에만 고칠 것)
LOCK_V2 = '7b60b70fe7ae400f2185b196363e455b4b278da55a7ffe24fd315f1202bb637a'


# ── 잠금 ───────────────────────────────────────────────────────────────────────────────────────
class TestLocks(unittest.TestCase):
    def test_schema_is_appendix_b(self):
        """설계 부록 B 그대로 — 칸 순서 scope → grade → basis → reason, basis enum에 「기관장 발언」, reason 40자."""
        s = crawler.URGENCY_V2_SCHEMA
        self.assertEqual(list(s['properties']), ['scope', 'grade', 'basis', 'reason'])
        self.assertEqual(s['required'], ['scope', 'grade', 'basis', 'reason'])
        self.assertIs(s['additionalProperties'], False)
        self.assertEqual(s['properties']['scope']['enum'], ['통신', '언저리', '타영역'])
        self.assertEqual(s['properties']['grade']['enum'], ['즉시대응', '금주검토', '동향파악'])
        self.assertEqual(s['properties']['basis']['enum'],
                         ['통신사·통신망 사고', '대규모 유출', '국감 증인', '제도', '주파수', '정부·통신3사 공동', 'SKT 당사자',
                          '플랫폼 개인정보', '경쟁사 공통 규제', '기관장 발언', '없음'])
        self.assertEqual(s['properties']['reason'], {'type': 'string', 'maxLength': 40})
        self.assertEqual(crawler.URGENCY_V2_REASON_MAX, 40)

    def test_lock(self):
        h = hashlib.sha256(_lock_text().encode('utf-8')).hexdigest()
        self.assertEqual(h, LOCK_V2, 'v2 스키마·팔·블록 머리말·상한이 바뀌었다 — tools_urgency_probe V2로 다시 잰 뒤에만 지문을 고친다')

    def test_criteria_lock(self):
        self.assertEqual(len(crawler.URGENCY_V2_CRITERIA_SHA256), 64)
        if crawler.URGENCY_V2_CRITERIA_TEXT is not None:
            self.assertEqual(hashlib.sha256(crawler.URGENCY_V2_CRITERIA_TEXT.encode('utf-8')).hexdigest(),
                             crawler.URGENCY_V2_CRITERIA_SHA256, '상수로 옮긴 글자가 잠금과 다르다')

    @unittest.skipUnless(os.path.exists(crawler.URGENCY_V2_CRITERIA_FILE), '저장소 밖 기준문 파일 없음(이 PC만)')
    def test_criteria_file_matches_lock(self):
        with open(crawler.URGENCY_V2_CRITERIA_FILE, encoding='utf-8') as f:
            txt = f.read()
        self.assertEqual(hashlib.sha256(txt.encode('utf-8')).hexdigest(), crawler.URGENCY_V2_CRITERIA_SHA256,
                         'criteria_v2.txt를 손질했다면 잠금 상수를 그 지문으로(측정 표와 함께 기록)')
        self.assertIn('[출력] JSON 한 개', txt)
        self.assertNotIn('실측:', txt, '「실측:」 각주는 v2에서 지운다(설계 §2-3 5)')

    def test_v1_untouched(self):
        """v1 글자·인자는 그대로(#264·#267·#268) — 2차 확인 잠금(test_urgency_check)과 별도로 v2가 v1 상수를 쓰지 않는지."""
        self.assertNotIn(crawler._URGENCY_CRITERIA, crawler.URGENCY_V2_CRITERIA_TEXT or '')
        self.assertEqual(crawler._urgency_call_kw()['model'], 'claude-haiku-4-5-20251001')

    def test_no_sampling_param_in_v2(self):
        """5.5 계열은 온도류 비기본값이 400 — v2 함수에 그 인자·글자가 없어야 한다(크롤러의 그 인자는 _urgency_call_kw 한 곳뿐)."""
        for fn in (crawler.urgency_v2_request, crawler.classify_urgency_v2, crawler.urgency_v2_judge, crawler.parse_urgency_v2,
                   crawler.urgency_v2_block2, crawler.combine_v2_votes, crawler._v2_run_start, crawler._v2_run_collect):
            self.assertNotIn('temperature', inspect.getsource(fn), fn.__name__)
        with open(crawler.__file__, encoding='utf-8') as f:
            self.assertEqual(f.read().count('temperature='), 1)
        for arm in crawler.URGENCY_V2_ARMS:
            req = crawler.urgency_v2_request('u', 'C', '', arm)
            self.assertNotIn('temperature', req)
            self.assertNotIn('top_p', req)

    def test_site_labels(self):
        self.assertEqual(crawler.URGENCY_V2_SITE, f'crawler.py:{crawler.classify_urgency_v2.__name__}')
        self.assertIn('client.messages.create(', inspect.getsource(crawler.classify_urgency_v2),
                      'create는 classify_urgency_v2 안에서 직접(api_usage 라벨)')
        import health_watchdog_sites
        self.assertIn(crawler.URGENCY_V2_SITE, health_watchdog_sites.CACHED_SITES)
        self.assertNotIn(crawler.URGENCY_V2_FALLBACK_SITE, health_watchdog_sites.CACHED_SITES)
        self.assertIn('crawler.py:classify_urgency', health_watchdog_sites.CACHED_SITES)


# health_watchdog.py는 가져오면 바로 돈다 — CACHED_SITES 줄만 읽는다
def _watchdog_sites():
    import ast
    src = open(os.path.join(ROOT, 'health_watchdog.py'), encoding='utf-8').read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'CACHED_SITES' for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('CACHED_SITES 없음')


sys.modules['health_watchdog_sites'] = SimpleNamespace(CACHED_SITES=_watchdog_sites())


# ── 기준문 로더·스위치 ────────────────────────────────────────────────────────────────────────────
class TestCriteriaAndMode(unittest.TestCase):
    def setUp(self):
        crawler._URGENCY_V2_CRIT_CACHE[0] = None
        crawler._URGENCY_GRADER_LAST[0] = None

    def tearDown(self):
        crawler._URGENCY_V2_CRIT_CACHE[0] = None
        crawler._URGENCY_GRADER_LAST[0] = None

    def _with_file(self, text):
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'c.txt')
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        return p

    def test_loader_file_lock_and_missing(self):
        txt = '기준문 시험\n'
        p = self._with_file(txt)
        h = hashlib.sha256(txt.encode('utf-8')).hexdigest()
        with mock.patch.object(crawler, 'URGENCY_V2_CRITERIA_FILE', p), mock.patch.object(crawler, 'URGENCY_V2_CRITERIA_SHA256', h):
            self.assertEqual(_quiet(crawler.urgency_v2_criteria)[0], txt)
        crawler._URGENCY_V2_CRIT_CACHE[0] = None
        with mock.patch.object(crawler, 'URGENCY_V2_CRITERIA_FILE', p):
            got, log = _quiet(crawler.urgency_v2_criteria)
            self.assertIsNone(got, '지문이 잠금과 다르면 쓰지 않는다')
            self.assertIn('지문', log)
        crawler._URGENCY_V2_CRIT_CACHE[0] = None
        with mock.patch.object(crawler, 'URGENCY_V2_CRITERIA_FILE', p + '.none'):
            self.assertIsNone(_quiet(crawler.urgency_v2_criteria)[0], 'Actions(파일 없음) = v2 못 씀 → v1')
        crawler._URGENCY_V2_CRIT_CACHE[0] = None
        with mock.patch.object(crawler, 'URGENCY_V2_CRITERIA_FILE', p + '.none'), \
                mock.patch.object(crawler, 'URGENCY_V2_CRITERIA_TEXT', txt), mock.patch.object(crawler, 'URGENCY_V2_CRITERIA_SHA256', h):
            self.assertEqual(_quiet(crawler.urgency_v2_criteria)[0], txt, '배포 창이 상수로 옮기면 파일 없이도')

    def _mode(self, data=None, exc=None):
        q = mock.MagicMock()
        for m in ('table', 'select', 'eq', 'limit'):
            getattr(q, m).return_value = q
        if exc:
            q.execute.side_effect = exc
        else:
            q.execute.return_value = SimpleNamespace(data=data)
        with mock.patch.object(crawler, 'sb', q):
            return _quiet(crawler.urgency_grader_mode)[0]

    def test_mode_switch(self):
        self.assertEqual(crawler.URGENCY_GRADER_DEFAULT, 'v1', '운영은 v1 그대로 — on 때 배포 창이 올린다')
        self.assertEqual(self._mode(data=[]), 'v1', '키 없음 = 코드 상수')
        self.assertEqual(self._mode(data=[{'value': '{"mode": "shadow"}'}]), 'shadow')
        self.assertEqual(self._mode(exc=RuntimeError('db down')), 'shadow', '읽기 실패 = 이 프로세스의 마지막 값')
        self.assertEqual(self._mode(data=[{'value': '{"mode": "켜"}'}]), 'shadow', '값 이상도 마지막 값')
        crawler._URGENCY_GRADER_LAST[0] = None
        self.assertEqual(self._mode(exc=RuntimeError('db down')), 'v1', '마지막 값도 없으면 코드 상수')
        self.assertEqual(self._mode(data=[{'value': {'mode': 'v2'}}]), 'v2', 'json 칸이 dict로 와도')

    def test_save_new_items_passes_mode(self):
        src = inspect.getsource(crawler.save_new_items)
        self.assertIn('grader=urgency_grader_mode()', src)


# ── 요청·해석 ────────────────────────────────────────────────────────────────────────────────────
class TestRequestAndParse(unittest.TestCase):
    def test_request_shape_per_arm(self):
        for arm, a in crawler.URGENCY_V2_ARMS.items():
            req = crawler.urgency_v2_request('제목: x', 'CRIT', 'BLOCK2', arm)
            self.assertEqual(set(req), {'model', 'max_tokens', 'thinking', 'output_config', 'system', 'messages'}, arm)
            self.assertEqual(req['model'], a['model'])
            self.assertEqual(req['thinking'], a['thinking'])
            self.assertEqual(req['output_config']['format'], {'type': 'json_schema', 'schema': crawler.URGENCY_V2_SCHEMA})
            self.assertEqual(req['output_config'].get('effort'), a['effort'])
            self.assertEqual(req['system'], [{'type': 'text', 'text': 'CRIT', 'cache_control': {'type': 'ephemeral', 'ttl': '1h'}},
                                             {'type': 'text', 'text': 'BLOCK2'}])
            self.assertEqual(req['messages'], [{'role': 'user', 'content': '제목: x'}])
        self.assertEqual(len(crawler.urgency_v2_request('u', 'C', '', 'H1')['system']), 1, '블록 ②가 비면 하나')
        a = crawler.URGENCY_V2_ARMS
        self.assertEqual((a['H1']['max_tokens'], a['H2']['max_tokens'], a['H3']['max_tokens']), (400, 2048, 2048))
        self.assertEqual(a['S1']['thinking'], {'type': 'between_tools'}, 'Sonnet 5.5는 disabled가 400')
        self.assertEqual((a['O1']['thinking'], a['O1']['effort']), ({'type': 'adaptive'}, 'low'), 'Opus 5.5는 끌 수 없다')
        self.assertEqual(crawler.URGENCY_V2_ARM, 'H1')

    def test_parse(self):
        f = crawler.parse_urgency_v2
        ok = f(_resp({'scope': '통신', 'grade': '즉시대응', 'basis': '제도', 'reason': '가' * 60}))
        self.assertEqual(ok, {'ok': True, 'scope': '통신', 'grade': '긴급', 'basis': '제도', 'reason': '가' * 40})
        self.assertEqual(f(_resp({'scope': '언저리', 'grade': '금주검토', 'basis': '없음', 'reason': ' 해설\n기사 '}))['reason'],
                         '해설 기사')
        self.assertEqual(f(_resp(text='', stop='refusal'))['why'], 'refusal')
        self.assertEqual(f(_resp(text='{"scope":', stop='max_tokens'))['why'], 'max_tokens')
        self.assertEqual(f(_resp(text='즉시대응'))['why'], 'parse')
        self.assertEqual(f(_resp(text='[1]'))['why'], 'parse')
        self.assertEqual(f(_resp({'scope': '통신', 'grade': '긴급', 'basis': '제도', 'reason': ''}))['why'], 'schema')
        self.assertEqual(f(_resp({'scope': '통신', 'grade': '즉시대응', 'basis': '제도'}))['why'], 'schema', 'reason 빠짐')
        c1 = f(_resp({'scope': '통신', 'grade': '즉시대응', 'basis': '없음', 'reason': 'r'}))
        c2 = f(_resp({'scope': '통신', 'grade': '동향파악', 'basis': '제도', 'reason': 'r'}))
        self.assertEqual((c1['ok'], c1['why'], c1['grade']), (False, 'contradict', '긴급'))
        self.assertEqual((c2['ok'], c2['why'], c2['grade']), (False, 'contradict', '참고'), '그 반대도 모순')
        thinking_first = SimpleNamespace(content=[SimpleNamespace(type='thinking', thinking=''),
                                                  SimpleNamespace(type='text', text=json.dumps(
                                                      {'scope': '타영역', 'grade': '동향파악', 'basis': '없음', 'reason': 'x'}))],
                                         stop_reason='end_turn')
        self.assertTrue(f(thinking_first)['ok'], '글 블록만 읽는다(앞에 thinking 블록)')

    def test_classify_v2_request_equals_builder_and_probe(self):
        """운영 classify_urgency_v2의 요청 = urgency_v2_request(_urgency_user_msg, 기준문, block2) = 탐침 V2의 요청."""
        calls = []

        class C:
            def __init__(self, **kw):
                self.kw = kw
                self.messages = SimpleNamespace(create=lambda **k: calls.append(k) or _resp(
                    {'scope': '통신', 'grade': '즉시대응', 'basis': '제도', 'reason': '고시 개정'}))
        rows = [{'id': 1, 'news_id': 'n0', 'title': '정부 5G 주파수 재할당 대가 산정 방식 확정', 'user_importance': '보통',
                 'ai_importance': '긴급', 'created_at': '2026-11-05T01:00:00+00:00', 'updated_at': '2026-11-05T01:00:00+00:00',
                 'reason': '정부안 전 단계'}]
        title, body, summ = '정부 5G 주파수 재할당 대가 산정 방식 확정 발표', '과기정통부가 … ' * 30, '요약 글'
        with mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'), \
                mock.patch.object(crawler, 'urgency_v2_criteria', lambda: 'CRIT'), \
                mock.patch.object(crawler, '_load_feedback_rows_v2', lambda: rows), \
                mock.patch.object(crawler.anthropic, 'Anthropic', C):
            got = crawler.classify_urgency_v2(title, body, summ)
        self.assertTrue(got['ok'])
        self.assertEqual(got['grade'], '긴급')
        self.assertIn('ms', got)
        block2 = crawler.urgency_v2_block2(title, summ, rows)
        self.assertEqual(calls[-1], crawler.urgency_v2_request(crawler._urgency_user_msg(title, body, summ), 'CRIT', block2))
        self.assertIn('정부안 전 단계', block2)
        # 탐침 V2 — 같은 기사·같은 행·기사 시각 now면 같은 요청
        snap = {'articles': {'a1': {'title': title, 'content': body, 'screen_text': summ}},
                'feedback_v2': rows, 'art_created': {'a1': datetime.now(timezone.utc).isoformat()}}
        b = P.Builder.__new__(P.Builder)
        b.snap, b.fx, b.synth = snap, {'synth': []}, {}
        with mock.patch.dict(P.V2_CTX, {'criteria': 'CRIT', 'crit_sha': 'x' * 64, 'asof': 'created'}), \
                mock.patch.object(P, 'V2_ARM', 'H1'):
            it = b.call_v2('V2', 'a1')
        self.assertEqual(it['req'], crawler.urgency_v2_request(P.user_msg(snap['articles']['a1']), 'CRIT', it['sim'], 'H1'))
        self.assertEqual(P.user_msg(snap['articles']['a1']), crawler._urgency_user_msg(title, body, summ))
        self.assertEqual(it['sim'], block2, '기사 시각 now(최근) — 운영 블록과 같은 글자')

    def test_classify_v2_failures(self):
        with mock.patch.object(crawler, 'ANTHROPIC_API_KEY', ''):
            self.assertEqual(crawler.classify_urgency_v2('t')['why'], 'nokey')
        with mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'), mock.patch.object(crawler, 'urgency_v2_criteria', lambda: None):
            self.assertEqual(crawler.classify_urgency_v2('t')['why'], 'unavailable')

        class Boom:
            def __init__(self, **kw):
                self.messages = SimpleNamespace(create=mock.Mock(side_effect=RuntimeError('529')))
        with mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'), mock.patch.object(crawler, 'urgency_v2_criteria', lambda: 'C'), \
                mock.patch.object(crawler, '_load_feedback_rows_v2', lambda: []), mock.patch.object(crawler.anthropic, 'Anthropic', Boom):
            self.assertEqual(crawler.classify_urgency_v2('t')['why'], 'error')


# ── 다수결 ──────────────────────────────────────────────────────────────────────────────────────
def V(g, s='통신', b=None, r='이유', ok=True, why=None):
    b = b if b is not None else ('제도' if g == '긴급' else '없음')
    return {'ok': ok, 'grade': g, 'scope': s, 'basis': b, 'reason': r, **({'why': why} if why else {})}


class TestCombine(unittest.TestCase):
    def test_single(self):
        c = crawler.combine_v2_votes
        self.assertEqual(c([V('긴급')])['grade'], '긴급')
        bad = c([{'ok': False, 'why': 'error'}])
        self.assertEqual((bad['ok'], bad['why'], bad['breaker']), (False, 'error', True))
        ref = c([{'ok': False, 'why': 'refusal'}])
        self.assertEqual((ref['why'], ref['breaker']), ('refusal', False), '거부는 기사 탓 — 차단기에 안 센다')
        con = c([{'ok': False, 'why': 'contradict', 'grade': '긴급', 'scope': '통신', 'basis': '없음', 'reason': 'r'}])
        self.assertEqual((con['ok'], con['contradict'], con['breaker']), (False, True, False))

    def test_three_votes(self):
        c = crawler.combine_v2_votes
        self.assertEqual(c([V('긴급'), V('참고'), V('긴급')])['grade'], '긴급', '중앙값')
        self.assertEqual(c([V('긴급'), V('참고'), V('참고')])['grade'], '참고')
        mix = c([V('긴급', r='a'), V('보통', s='언저리', r='b'), V('참고', r='c')])
        self.assertEqual((mix['grade'], mix['scope'], mix['reason']), ('보통', '언저리', 'b'), '1:1:1 = 보통, 그 표의 칸')
        sc = c([V('긴급', s='언저리', r='1'), V('긴급', s='통신', r='2'), V('긴급', s='통신', r='3')])
        self.assertEqual((sc['scope'], sc['reason'], sc['basis']), ('통신', '1', '제도'), 'scope 다수, basis·reason은 첫 표')
        tie = c([V('긴급', s='언저리'), V('긴급', s='통신'), V('참고')])
        self.assertEqual(tie['scope'], '언저리', '동점이면 첫 표')

    def test_two_valid(self):
        c = crawler.combine_v2_votes
        err = {'ok': False, 'why': 'error'}
        self.assertEqual(c([V('보통'), err, V('보통')])['grade'], '보통', '유효 2표가 같으면 채택')
        split = c([V('보통'), err, V('긴급')])
        self.assertEqual((split['ok'], split['why'], split['breaker']), (False, 'split', True))
        self.assertFalse(c([V('긴급'), err, {'ok': False, 'why': 'refusal'}])['ok'], '유효 1표면 실패')

    def test_contradict_normal_mode(self):
        con = {'ok': False, 'why': 'contradict', 'grade': '긴급', 'scope': '통신', 'basis': '없음', 'reason': 'r'}
        with mock.patch.object(crawler, 'URGENCY_V2_CONTRADICT', 'normal'):
            got = crawler.combine_v2_votes([con])
        self.assertEqual((got['ok'], got['grade'], got['basis'], got['contradict']), (True, '보통', '없음', True))


# ── 피드백 블록 ② ─────────────────────────────────────────────────────────────────────────────────
def FB(i, title, ui='보통', ai='긴급', days_ago=1.0, reason=None, news=None, upd_days=None):
    now = datetime(2026, 11, 9, 3, 0, tzinfo=timezone.utc)
    c = now - timedelta(days=days_ago)
    u = now - timedelta(days=upd_days if upd_days is not None else days_ago)
    return {'id': i, 'news_id': news or f'n{i}', 'title': title, 'user_importance': ui, 'ai_importance': ai,
            'created_at': c.isoformat(), 'updated_at': u.isoformat(), 'reason': reason}


NOW = datetime(2026, 11, 9, 3, 0, tzinfo=timezone.utc)


class TestBlock2(unittest.TestCase):
    def test_search_min_max_and_line(self):
        rows = [FB(1, '알뜰폰 도매대가 협상 결렬 정부 중재', reason='비통신 후속 아님'),
                FB(2, '알뜰폰 도매대가 인하 협상 시작', ui='긴급', ai='보통', days_ago=20),
                FB(3, '알뜰폰 도매대가 논란', days_ago=30),                       # 겹침 2 — 안 씀
                FB(4, '전혀 다른 기사 제목입니다', days_ago=2)]
        # 제목 겹침은 적고(유사 블록 아님) 요약까지 합치면 3 이상 — 검색 예시는 제목 + 요약 낱말로 찾는다
        b = crawler.urgency_v2_block2('도매대가 재개 소식', '알뜰폰 도매대가 협상이 정부 중재로 다시', rows, now=NOW)
        self.assertNotIn(crawler._URGENCY_V2_SIMILAR_HEAD, b)
        self.assertTrue(b.startswith(crawler._URGENCY_V2_SEARCH_HEAD))
        sec = b.split(crawler._URGENCY_V2_LOWERED_HEAD)[0]
        self.assertIn('- "알뜰폰 도매대가 협상 결렬 정부 중재" → 금주검토 (11-08, 비통신 후속 아님)', sec)
        self.assertIn('- "알뜰폰 도매대가 인하 협상 시작" → 즉시대응 (10-20)', sec)
        self.assertNotIn('도매대가 논란', sec, '겹침 3 미만은 안 쓴다(#264 눈금)')
        self.assertLess(sec.index('협상 결렬'), sec.index('인하 협상'), '겹침 많은 순')
        many = [FB(i, f'국감 증인 채택 통신 3사 대표 출석 {i}', days_ago=10 + i) for i in range(10)]
        b2 = crawler.urgency_v2_block2('국감 증인 채택 대표 출석 요구', '', many, now=NOW)
        search2, similar2 = b2.split(crawler._URGENCY_V2_SIMILAR_HEAD)
        self.assertEqual(search2.count('\n- '), crawler.URGENCY_V2_SEARCH_MAX, '유사 3건을 뺀 나머지 7건 중 상위 6')
        self.assertEqual(similar2.count('- "'), crawler.FB_SIMILAR_MAX)

    def test_lowered_window_and_cap(self):
        rows = [FB(i, f'내린 기사 {i}', days_ago=i * 0.4) for i in range(1, 25)]   # 0.4~9.6일 전
        rows.append(FB(99, '올린 기사', ui='긴급', ai='보통', days_ago=1))
        rows.append(FB(98, '미래 기사', days_ago=-1))                                 # now 뒤 — 안 씀
        b = crawler.urgency_v2_block2('관계 없는 제목', '', rows, now=NOW)
        low = b.split(crawler._URGENCY_V2_LOWERED_HEAD)[1]
        lines = [x for x in low.split('\n') if x.startswith('- ')]
        self.assertEqual(len(lines), crawler.URGENCY_V2_LOWERED_MAX)
        self.assertTrue(lines[0].startswith('- "내린 기사 1"'), '최신순')
        self.assertNotIn('올린 기사', low)
        self.assertNotIn('미래 기사', low)
        b7 = crawler.urgency_v2_block2('관계 없는 제목', '', [FB(1, '오래된 내림', days_ago=8)], now=NOW)
        self.assertEqual(b7, '', '7일 밖')

    def test_similar_only_in_similar_and_own_row(self):
        rows = [FB(1, 'SKT 스페이스X 저궤도 위성통신 이동통신시장 영향 제한적', days_ago=30, news='own'),
                FB(2, 'SKT 스페이스X 저궤도 위성통신 이동통신시장 영향 제한적 분석', days_ago=31)]
        title = 'SKT 스페이스X 저궤도 위성통신 이동통신시장 영향 제한적 전망'
        b = crawler.urgency_v2_block2(title, '', rows, now=NOW)
        self.assertNotIn(crawler._URGENCY_V2_SEARCH_HEAD, b, '유사 블록에 실린 행은 검색 예시에 다시 안 쓴다')
        self.assertEqual(b.split(crawler._URGENCY_V2_SIMILAR_HEAD)[1].count('- "'), 2)
        self.assertNotIn('(', b.split(crawler._URGENCY_V2_SIMILAR_HEAD)[1], '유사 블록 줄은 #264 꼴 그대로(날짜 없음)')
        b_own = crawler.urgency_v2_block2(title, '', rows, now=NOW, exclude_news_id='own')
        self.assertEqual(b_own.split(crawler._URGENCY_V2_SIMILAR_HEAD)[1].count('- "'), 1, '측정 — 그 기사 자신의 행은 뺀다')
        self.assertEqual(crawler.urgency_v2_block2(title, '', [], now=NOW), '')

    def test_probe_asof(self):
        rows = [FB(1, 'a', days_ago=3), FB(2, 'b', days_ago=1, upd_days=0.1)]
        art_at = (NOW - timedelta(days=0.5)).isoformat()
        self.assertEqual([r['id'] for r in P.v2_rows_asof(rows, art_at, 'created')], [1, 2])
        self.assertEqual([r['id'] for r in P.v2_rows_asof(rows, art_at, 'updated')], [1], '기사 뒤에 고친 행까지 뺀다')
        self.assertEqual(len(P.v2_rows_asof(rows, art_at, '')), 2)
        self.assertEqual(len(P.v2_rows_asof(rows, (NOW - timedelta(days=2)).isoformat(), 'created')), 1)


# ── grade_urgency ───────────────────────────────────────────────────────────────────────────────
class TestGradeUrgencyV2(unittest.TestCase):
    RULES = [{'id': 'r_min_urgent', 'mode': 'min', 'level': '긴급', 'any_words': ['국감증인']},
             {'id': 'r_min_normal', 'mode': 'min', 'level': '보통', 'any_words': ['SKT']},
             {'id': 'r_set', 'mode': 'set', 'level': '참고', 'any_words': ['부고']}]

    def setUp(self):
        self._p = mock.patch.dict(crawler._URGENCY_SUMMARY, {}, clear=True)
        self._p.start()
        self._w = mock.patch.object(crawler, 'URGENCY_V2_WORKERS', 1)     # 차단기 순서를 정해 두려고 직렬
        self._w.start()

    def tearDown(self):
        self._p.stop()
        self._w.stop()

    def _grade(self, items, grader, v2fn, v1='긴급', check=None):
        seen = {'v1': [], 'labels': []}

        def classify(t, c, s):
            seen['v1'].append(t)
            seen['labels'].append(getattr(api_usage._label, 'site', None))
            return v1(t) if callable(v1) else v1
        chk = check or (lambda t, c, s: {'scope': '통신', 'grade': '긴급', 'basis': '제도'})
        with mock.patch.object(crawler, 'URGENCY_CHECK_MODE', 'on'):
            _r, log = _quiet(crawler.grade_urgency, items, self.RULES, classify=classify, check=chk,
                             v2=v2fn, grader=grader)
        return seen, log

    def test_v1_default_is_old_path_with_new_keys(self):
        items = [{'title': '드론', 'url': 'u1'}, {'title': '[부고] 누구', 'url': 'u2'}]
        v2 = mock.Mock(side_effect=AssertionError('v1이면 부르면 안 됨'))
        seen, _ = self._grade(items, None, v2, check=lambda t, c, s: {'scope': '타영역', 'grade': '참고', 'basis': '없음'})
        self.assertEqual(seen['v1'], ['드론'])
        self.assertEqual([i['urgency'] for i in items], ['보통', '참고'])
        self.assertEqual([i['urgency_grader'] for i in items], ['v1', 'rule'])
        self.assertEqual(items[0]['urgency_lowered_by'], 'check', '2차 확인이 내림 = check')
        self.assertIsNone(items[1]['urgency_lowered_by'])
        for k in ('urgency_v2_scope', 'urgency_v2_grade', 'urgency_v2_basis', 'urgency_reason', 'urgency_event_of'):
            self.assertEqual([i[k] for i in items], [None, None])
        self.assertEqual(len({frozenset(i) for i in items}), 1)

    def test_v2_mode(self):
        items = [{'title': '고시 개정', 'url': 'u1'},           # v2 긴급
                 {'title': '드론 배송', 'url': 'u2'},           # v2 긴급 + 타영역 → 보통, capped
                 {'title': '공장 화재', 'url': 'u3'},           # v2 참고 + 타영역 → 참고 그대로(올리지 않음), check 칸 없음
                 {'title': 'SKT 실적 해설', 'url': 'u4'},       # v2 참고 + min 보통 하한 → 보통
                 {'title': '해킹 기사', 'url': 'u5'},           # v2 거부 → v1 폴백(긴급) + 2차 확인
                 {'title': '[부고] 누구', 'url': 'u6'}]         # set → AI 없음
        res = {'고시 개정': V('긴급', r='제도 확정'), '드론 배송': V('긴급', s='타영역'),
               '공장 화재': V('참고', s='타영역'), 'SKT 실적 해설': V('참고'),
               '해킹 기사': {'ok': False, 'why': 'refusal'}}
        calls = []

        def v2(t, c, s):
            calls.append(t)
            return res[t]
        seen, log = self._grade(items, 'v2', v2)
        self.assertEqual(sorted(calls), sorted(res), 'set 규칙 기사는 v2도 안 부른다')
        self.assertEqual(seen['v1'], ['해킹 기사'], 'v1은 실패한 기사만')
        self.assertEqual(seen['labels'], [crawler.URGENCY_V2_FALLBACK_SITE], '폴백 1차 호출은 폴백 라벨')
        self.assertIsNone(getattr(api_usage._label, 'site', None))
        self.assertEqual([i['urgency'] for i in items], ['긴급', '보통', '참고', '보통', '긴급', '참고'])
        self.assertEqual([i['urgency_grader'] for i in items], ['v2', 'v2', 'v2', 'v2', 'v1-fallback', 'rule'])
        self.assertEqual([i['urgency_check_capped'] for i in items], [False, True, None, None, False, None])
        self.assertEqual([i['urgency_check_scope'] for i in items], ['통신', '타영역', None, None, '통신', None],
                         'check 칸 = v2 긴급 행(+ v1 폴백의 2차 확인)만')
        self.assertEqual(items[1]['urgency_check_grade'], '긴급')
        self.assertEqual([i['urgency_lowered_by'] for i in items], [None, 'check', None, None, None, None])
        self.assertEqual([i['urgency_v2_grade'] for i in items], ['긴급', '긴급', '참고', '참고', None, None],
                         'v2 칸 = 영역 상한 전 v2 등급(판정한 행만)')
        self.assertEqual(items[0]['urgency_reason'], '제도 확정')
        self.assertEqual(len({frozenset(i) for i in items}), 1, '벌크 upsert — 모든 행의 키 집합이 같다')
        for k in NEW_KEYS + CHECK_KEYS:
            self.assertIn(k, items[0])
        self.assertIn('[v2 판정기·v2] 대상 5 · 성공 4 · 실패 1(refusal 1)', log)
        self.assertEqual(crawler._URGENCY_V2_RUN['v2_urgent'], 2)

    def test_v2_floor_and_human_independent(self):
        items = [{'title': '국감증인 기사', 'url': 'u1'}]
        self._grade(items, 'v2', lambda t, c, s: V('참고', s='타영역'))
        self.assertEqual(items[0]['urgency'], '긴급', '낱말 min 긴급 하한은 v2 상한 뒤에')

    def test_shadow_keeps_v1(self):
        items = [{'title': 'A', 'url': 'u1'}, {'title': 'B', 'url': 'u2'}]
        res = {'A': V('참고', s='타영역', r='무관'), 'B': {'ok': False, 'why': 'schema'}}
        seen, log = self._grade(items, 'shadow', lambda t, c, s: res[t])
        self.assertEqual(seen['v1'], ['A', 'B'], '그림자 — 운영은 v1 전부')
        self.assertEqual(seen['labels'], [None, None], '그림자의 v1은 운영 라벨 그대로')
        self.assertEqual([i['urgency'] for i in items], ['긴급', '긴급'])
        self.assertEqual([i['urgency_grader'] for i in items], ['v1', 'v1'])
        self.assertEqual([i['urgency_check_scope'] for i in items], ['통신', '통신'], 'check 칸은 v1 2차 확인 그대로')
        self.assertEqual([(i['urgency_v2_grade'], i['urgency_v2_scope'], i['urgency_reason']) for i in items],
                         [('참고', '타영역', '무관'), (None, None, None)])
        self.assertIn('그림자: 운영 등급은 v1', log)
        self.assertEqual(len({frozenset(i) for i in items}), 1)

    def test_breaker_and_budget(self):
        items = [{'title': f'T{i}', 'url': f'u{i}'} for i in range(5)]
        calls = []
        seen, log = self._grade(items, 'v2', lambda t, c, s: calls.append(t) or {'ok': False, 'why': 'error', 'breaker': True})
        self.assertEqual(len(calls), crawler.URGENCY_V2_MAX_FAIL, '장치 실패가 쌓이면 나머지 기사는 v2를 안 부른다')
        self.assertEqual([i['urgency_grader'] for i in items], ['v1-fallback'] * 5)
        self.assertIn('breaker 3', log)
        calls.clear()
        items = [{'title': f'T{i}', 'url': f'u{i}'} for i in range(3)]
        with mock.patch.object(crawler, 'URGENCY_V2_BUDGET_S', -1):
            seen, log = self._grade(items, 'v2', lambda t, c, s: calls.append(t) or V('참고'))
        self.assertEqual(calls, [], '예산을 넘겨 시작하는 기사는 부르지 않는다')
        self.assertEqual([i['urgency_grader'] for i in items], ['v1-fallback'] * 3)
        self.assertIn('budget 3', log)

    def test_injected_classify_without_v2_is_v1(self):
        items = [{'title': 'A', 'url': 'u1'}]
        with mock.patch.object(crawler, 'urgency_v2_judge', side_effect=AssertionError('불리면 안 됨')):
            _quiet(crawler.grade_urgency, items, [], classify=lambda t, c, s: '긴급', grader='v2')
        self.assertEqual(items[0]['urgency_grader'], 'v1', 'classify를 넘긴 호출은 v2도 넘겨야 v2')

    def test_run_collect_timeout(self):
        import threading
        ev = threading.Event()
        with mock.patch.object(crawler, 'URGENCY_V2_BUDGET_S', 0.2):
            h = crawler._v2_run_start([(0, 't', '', '')], lambda t, c, s: ev.wait(2) or V('긴급'))
            got = crawler._v2_run_collect(h)
        ev.set()
        self.assertEqual(got[0]['why'], 'budget')


# ── 전파 on(꺼져 있음 — 꼴만) ──────────────────────────────────────────────────────────────────────
class TestPropagateOn(unittest.TestCase):
    RULES = [{'id': 'r_min_normal', 'mode': 'min', 'level': '보통', 'any_words': ['SKT']}]

    def setUp(self):
        self._p = mock.patch.dict(crawler._URGENCY_SUMMARY, {}, clear=True)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        crawler._PROPAGATE_PRIOR_GRADE.clear()

    def test_mode_default_still_shadow(self):
        self.assertEqual(crawler.PROPAGATE_MODE, 'shadow')
        self.assertFalse(crawler.PROPAGATE_OMNIBUS_IN_SHADOW, '그림자 기록은 10-28 측정 규칙 그대로')
        self.assertEqual(crawler._propagate_site(), crawler.PROPAGATE_SITE)

    def test_on_lowers_to_prior_grade_then_floor(self):
        items = [{'title': 'A 재보도', 'url': 'u1'},                 # 같은 계기 — prior 참고 → 참고
                 {'title': 'SKT 재보도', 'url': 'u2'},               # 같은 계기 — prior 참고 → min 보통 하한 → 보통
                 {'title': 'C 다른 기사', 'url': 'u3'},              # 다름
                 {'title': '국감 종합감사 이모저모', 'url': 'u4'}]    # ⓑ 합본 — 후보 아님
        crawler._PROPAGATE_PRIOR_GRADE.update({'p1': '참고'})
        prior = {'id': 'p1', 'title': '운영자가 내린 기사'}
        seen = []

        def prop(c):
            seen.append([x['title'] for x in c])
            return [prior, prior, False]
        with mock.patch.object(crawler, 'PROPAGATE_MODE', 'on'), mock.patch.object(crawler, 'URGENCY_CHECK_MODE', 'off'):
            _r, log = _quiet(crawler.grade_urgency, items, self.RULES, classify=lambda t, c, s: '긴급', propagate=prop)
            self.assertEqual(crawler._propagate_site(), crawler.PROPAGATE_SITE_ON)
        self.assertEqual(seen, [['A 재보도', 'SKT 재보도', 'C 다른 기사']])
        self.assertEqual([i['urgency'] for i in items], ['참고', '보통', '긴급', '긴급'])
        self.assertEqual([i['importance'] for i in items], [i['urgency'] for i in items])
        self.assertEqual([i['urgency_lowered_by'] for i in items], ['propagate', 'propagate', None, None])
        self.assertEqual([i['urgency_event_of'] for i in items], ['p1', 'p1', None, None])
        self.assertEqual([i['urgency_propagate_shadow_from'] for i in items], ['p1', 'p1', None, None])
        self.assertIsNotNone(items[2]['urgency_propagate_shadow_at'])
        self.assertIn('합본 건너뜀 1', log)
        self.assertEqual(len({frozenset(i) for i in items}), 1)

    def test_shadow_unchanged_by_omnibus_rule(self):
        items = [{'title': '국감 종합감사 이모저모', 'url': 'u4'}]
        seen = []
        with mock.patch.object(crawler, 'URGENCY_CHECK_MODE', 'off'):
            _quiet(crawler.grade_urgency, items, [], classify=lambda t, c, s: '긴급',
                   propagate=lambda c: seen.append(len(c)) or [None] * len(c))
        self.assertEqual(seen, [1], '그림자는 합본 제외 없이(측정 규칙 그대로)')
        self.assertEqual(items[0]['urgency'], '긴급')

    def test_omnibus_words(self):
        for t in ('과방위 종합감사 총정리', '국감 종감 하이라이트', '[이번 주 통신] 요약', '국감 이모저모', '한눈에 보는 국감',
                  '통신업계 주간 동향', '3분기 결산', '13일부터 15일까지 국감 쟁점'):
            self.assertTrue(crawler.is_omnibus_title(t), t)
        for t in ('SKT 해킹 후속(종합)', '배경훈 장관 답변 (종합2보)', '최종감사 결과 발표', 'IPO 주간사 선정', '2주간 점검 결과',
                  'KT 장애 원인 조사'):
            self.assertFalse(crawler.is_omnibus_title(t), t)

    def test_pool_entries_omnibus_and_banned(self):
        fb = [{'news_id': 'a', 'created_at': 't3'}, {'news_id': 'b', 'created_at': 't2'}, {'news_id': 'c', 'created_at': 't1'}]
        news = [{'id': 'a', 'title': '여야 8개 상임위 종합감사 이모저모', 'urgency': '보통'},
                {'id': 'b', 'title': 'B 사건', 'urgency': '보통'},
                {'id': 'c', 'title': 'C 사건(종합)', 'urgency': '참고'}]
        self.assertEqual([p['id'] for p in crawler.propagate_pool_entries(fb, news)], ['a', 'b', 'c'], '기본(그림자) = 종전')
        self.assertEqual([p['id'] for p in crawler.propagate_pool_entries(fb, news, exclude_omnibus=True)], ['b', 'c'],
                         'ⓐ 합본 prior 제외, 괄호 (종합)은 남김')
        self.assertEqual([p['id'] for p in crawler.propagate_pool_entries(fb, news, banned={'b'})], ['a', 'c'],
                         '복원된 전파의 원인 prior 제외')

    def test_restore_query_by_mode(self):
        class Q:
            def __init__(self):
                self.ops = []

            def table(self, n):
                self.ops.append(('table', n))
                return self

            def __getattr__(self, n):
                def f(*a, **k):
                    self.ops.append((n,) + a)
                    return self
                return f
        q = Q()
        with mock.patch.object(crawler, 'sb', q):
            crawler._restore_lowered_query('t')
        self.assertIn(('select', crawler._RESTORE_COLS), q.ops)
        self.assertIn(('eq', 'urgency_check_capped', True), q.ops, '그림자 = #268 조회 그대로')
        q = Q()
        with mock.patch.object(crawler, 'sb', q), mock.patch.object(crawler, 'PROPAGATE_MODE', 'on'):
            crawler._restore_lowered_query('t')
        self.assertIn(('select', crawler._RESTORE_COLS + ',urgency_lowered_by'), q.ops)
        self.assertIn(('or_', 'urgency_check_capped.eq.true,urgency_lowered_by.eq.propagate'), q.ops,
                      'on = 전파로 내린 기사도(운영자 operator-event는 아님)')
        self.assertEqual(crawler._restore_mark_of({'urgency_lowered_by': 'propagate'}), '[복원] 내림 전파 되돌림')
        self.assertEqual(crawler._restore_mark_of({}), crawler._RESTORE_MARK)
        self.assertIn('내림 전파 되돌림', crawler._restore_line({'urgency_lowered_by': 'propagate', 'title': 'x'}))
        self.assertEqual(crawler._restore_line({'title': 'x'}), '🔼 다시 긴급 — 구독자에게 보냄: x')

    def test_notices_exclusive(self):
        items = [{'title': 'x', 'url': 'u', 'urgency': '보통', 'urgency_propagate_shadow_from': 'p', 'urgency_lowered_by': 'propagate'}]
        sent = []
        with mock.patch.object(crawler, 'TELEGRAM_BOT_TOKEN', 't'), mock.patch.object(crawler, 'TELEGRAM_CHAT_ID', 'c'), \
                mock.patch.object(crawler.notify, 'send_telegram', lambda text, **kw: sent.append(text) or True):
            self.assertFalse(_quiet(crawler.send_propagate_on_notice, items)[0], '그림자면 on 줄 없음')
            with mock.patch.object(crawler, 'PROPAGATE_MODE', 'on'):
                self.assertFalse(_quiet(crawler.send_propagate_shadow_notice, items)[0], 'on이면 그림자 줄 없음')
                self.assertTrue(_quiet(crawler.send_propagate_on_notice, items)[0])
        self.assertEqual(len(sent), 1)
        self.assertIn('🔽 내림 전파(보통)', sent[0])

    def test_restore_alert_only_on(self):
        with mock.patch.object(crawler, 'sb', mock.Mock(side_effect=AssertionError('조회하면 안 됨'))):
            self.assertFalse(crawler.propagate_restore_alert())


# ── A2 사건 연결 칸 ───────────────────────────────────────────────────────────────────────────────
class TestEventLinks(unittest.TestCase):
    def test_links_from_core_result(self):
        reps = [{'title': '대표 이번 실행', 'url': 'r1'}]
        sup = [{'article_title': '묶인 기사', 'article_url': 'm1', 'matched_title': '대표 이번 실행', 'shared_keywords': '[실행내묶음]'},
               {'article_title': '키워드 억제', 'article_url': 'k1', 'matched_title': '억제된 옛 기사', 'shared_keywords': 'a,b,c'},
               {'article_title': '의미 억제', 'article_url': 's1', 'matched_title': '알림 나간 옛 대표', 'shared_keywords': '[의미판정] a'},
               {'article_title': '보류', 'article_url': 'h1', 'matched_title': '알림 나간 옛 대표', 'shared_keywords': '[리마인드보류] 1/3'},
               {'article_title': '자기', 'article_url': 'r1', 'matched_title': '대표 이번 실행', 'shared_keywords': '[실행내묶음]'}]
        rem = [{'article_title': '대표 이번 실행', 'article_url': 'r1', 'matched_title': '알림 나간 옛 대표', 'shared_keywords': '[리마인드] 2일째'}]
        chain = {'억제된 옛 기사': '더 옛 억제', '더 옛 억제': '알림 나간 옛 대표'}
        got = crawler.event_links_from(reps, sup, rem, chain, {'알림 나간 옛 대표': 'old'})
        self.assertEqual(got, [{'url': 'm1', 'rep_title': '대표 이번 실행', 'rep_url': 'r1'},
                               {'url': 'k1', 'rep_title': '알림 나간 옛 대표', 'rep_url': 'old'},
                               {'url': 's1', 'rep_title': '알림 나간 옛 대표', 'rep_url': 'old'},
                               {'url': 'h1', 'rep_title': '알림 나간 옛 대표', 'rep_url': 'old'},
                               {'url': 'r1', 'rep_title': '알림 나간 옛 대표', 'rep_url': 'old'}],
                         '사슬 끝 대표 · 자기 자신은 빼고 · 🔁 리마인드 기사는 옛 대표에')
        self.assertEqual(crawler._chain_rep('a', {'a': 'b', 'b': 'a'}), 'a', '고리면 멈춘 자리')

    def test_save_resolves_ids_and_writes_empty_only(self):
        ops = []

        class Q:
            def __init__(self, name):
                self.name, self.kind, self.payload, self.filters = name, 'select', None, []

            def select(self, *a):
                return self

            def update(self, p):
                self.kind, self.payload = 'update', p
                return self

            def in_(self, col, vals):
                self.filters.append(('in', col, list(vals)))
                return self

            def is_(self, col, v):
                self.filters.append(('is', col, v))
                return self

            def __getattr__(self, n):
                return lambda *a, **k: self

            def execute(self):
                ops.append((self.name, self.kind, self.payload, self.filters))
                col = next((f[1] for f in self.filters if f[0] == 'in'), None)
                if self.kind == 'select' and col == 'url':
                    return SimpleNamespace(data=[{'id': 'id-' + u, 'url': u} for u in self.filters[0][2]])
                if self.kind == 'select' and col == 'title':
                    return SimpleNamespace(data=[{'id': 'id-old', 'title': '옛 대표', 'created_at': 'x'}])
                if self.kind == 'update':
                    return SimpleNamespace(data=[{'id': 1}] * len(self.filters[0][2]))
                return SimpleNamespace(data=[])
        sb = SimpleNamespace(table=lambda n: Q(n))
        links = [{'url': 'a', 'rep_title': '대표', 'rep_url': 'r'}, {'url': 'b', 'rep_title': '옛 대표', 'rep_url': None},
                 {'url': 'c', 'rep_title': '"따옴표" 대표', 'rep_url': None}]
        with mock.patch.object(crawler, 'sb', sb), mock.patch.object(crawler, '_EVENT_LINKS', links), \
                mock.patch.dict(crawler._INSERTED_IDS, {'a': 'id-a'}, clear=True):
            n, log = _quiet(crawler.save_event_links)
        ups = [(p, f) for t, k, p, f in ops if k == 'update']
        self.assertEqual(sorted((p['urgency_event_of'], f[0][2][0]) for p, f in ups), [('id-old', 'b'), ('id-r', 'a')])
        for _p, f in ups:
            self.assertIn(('is', 'urgency_event_of', 'null'), f, '빈 칸만 — 전파가 적은 원인 id를 덮지 않는다')
        self.assertEqual(n, 2)
        self.assertIn('못 이음 1', log, '따옴표 든 제목은 찾지 않는다(PostgREST in_ 인용)')
        with mock.patch.object(crawler, 'sb', mock.Mock(side_effect=AssertionError('쓰면 안 됨'))), \
                mock.patch.object(crawler, '_EVENT_LINKS', links), mock.patch.object(crawler, 'EVENT_LINKS_ON', False):
            self.assertEqual(crawler.save_event_links(), 0)

    def test_save_failure_is_open(self):
        with mock.patch.object(crawler, 'sb', SimpleNamespace(table=mock.Mock(side_effect=RuntimeError('db')))), \
                mock.patch.object(crawler, '_EVENT_LINKS', [{'url': 'a', 'rep_title': 't', 'rep_url': 'r'}]):
            n, log = _quiet(crawler.save_event_links)
        self.assertEqual(n, 0)
        self.assertIn('실패(무시', log)


if __name__ == '__main__':
    unittest.main()
