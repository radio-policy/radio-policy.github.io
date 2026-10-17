# -*- coding: utf-8 -*-
"""
관련성 선별 Haiku 5.5 그림자 1주(#318, 설계 local_docs/선별그림자_설계_261017.md) — 표준 unittest, **네트워크 0**.

  - 운영(_screen_batch_haiku)·그림자(_screen_shadow_batch) 요청이 model 칸 빼고 같다 — system·도구·tool_choice·메시지·
    max_tokens·1h 캐시 표시. 그림자에 thinking·온도류 인자 없음. 운영 모델은 4.5 그대로, create는 각 함수 안에서 직접
  - 그림자 상태: ok / refusal / max_tokens / no_tool / error
  - 기록 행: 모든 행 키 집합 동일(벌크 insert), 관련 갈림·태그 갈림, 운영 실패·그림자 실패면 batch 행만, 범위 밖 id 무시
  - 스위치(app_config.screen_shadow): 없음·형식 오류·시각대 없음·지난 시각·조회 실패 = 꺼짐, 미래 = 켜짐
  - screen_news_items: 그림자가 켜져도·오류여도·시간을 넘겨도 운영 결과(통과 기사·태그·사건)가 꺼졌을 때와 같다

Anthropic: crawler.anthropic.Anthropic을 가짜 생성자로 막는다(tests는 .env의 실제 키를 읽을 수 있다).
Supabase: crawler.sb를 메모리 가짜로 바꾼다.
"""
import contextlib
import inspect
import io
import json
import os
import sys
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 실 DB 자격증명 없이 import (클라이언트 생성만, 접속 없음) — test_smoke.py와 같은 방식
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import crawler  # noqa: E402

BATCH = [
    {'title': '과기정통부, 3.7GHz 주파수 추가 할당 공고', 'url': 'u1', '_screen_text': '요약  첫째   줄'},
    {'title': '김하성 안타', 'url': 'u2', 'content': '본문 ' * 200},
    {'title': ' 앞뒤 공백 제목 ', 'url': 'u3'},
]


class _Blk:
    def __init__(self, type_, input_=None):
        self.type = type_
        self.input = input_


class _Resp:
    def __init__(self, content, stop='tool_use'):
        self.content = content
        self.stop_reason = stop


def _tool(rows, stop='tool_use'):
    return _Resp([_Blk('tool_use', {'relevant': rows})], stop)


class _FakeClient:
    """messages.create(**kw)를 받아 fn(kw)를 돌려준다. 받은 인자는 calls에 쌓는다."""

    def __init__(self, fn):
        self.calls = []
        self._fn = fn
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return self._fn(kw)


class _FakeSb:
    """crawler.sb 대역 — app_config 조회 한 줄과 news_screen_shadow insert만."""

    def __init__(self, cfg_rows=None, exc=None):
        self.cfg_rows = cfg_rows or []
        self.exc = exc
        self.inserted = []
        self._table = None
        self._rows = None

    def table(self, name):
        self._table = name
        self._rows = None
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def insert(self, rows):
        self._rows = rows
        return self

    def execute(self):
        if self.exc is not None:
            raise self.exc
        if self._rows is not None:
            self.inserted.extend(self._rows)
            return types.SimpleNamespace(data=self._rows)
        return types.SimpleNamespace(data=self.cfg_rows)


@contextlib.contextmanager
def _fixed_system():
    """_screen_system이 DB(피드백)를 타지 않게 — 모듈 캐시를 비웠다가 되돌린다."""
    saved = dict(crawler._screen_system_cache)
    crawler._screen_system_cache.clear()
    try:
        with mock.patch.object(crawler, 'get_feedback_examples', lambda t: '\n\n[피드백 고정]\n'):
            yield
    finally:
        crawler._screen_system_cache.clear()
        crawler._screen_system_cache.update(saved)


class TestShadowRequest(unittest.TestCase):

    def test_requests_identical_except_model(self):
        with _fixed_system():
            prod = _FakeClient(lambda kw: _tool([{'id': 1}]))
            sh = _FakeClient(lambda kw: _tool([{'id': 1}]))
            self.assertEqual(set(crawler._screen_batch_haiku(prod, '기준', BATCH)), {1})
            res = crawler._screen_shadow_batch(sh, crawler._screen_request('기준', BATCH))
        self.assertEqual(res['status'], 'ok')
        p, s = dict(prod.calls[0]), dict(sh.calls[0])
        self.assertEqual(p.pop('model'), 'claude-haiku-4-5-20251001')
        self.assertEqual(p.pop('model', None), None)
        self.assertEqual(s.pop('model'), 'claude-haiku-5-5')
        self.assertEqual(json.dumps(p, ensure_ascii=False, sort_keys=True),
                         json.dumps(s, ensure_ascii=False, sort_keys=True))
        for k in ('temperature', 'top_p', 'top_k', 'thinking', 'output_config'):
            self.assertNotIn(k, s)
        self.assertEqual(s['system'][0]['cache_control'], {'type': 'ephemeral', 'ttl': '1h'})
        self.assertEqual(s['tool_choice'], {'type': 'tool', 'name': 'record_relevant_news'})
        self.assertEqual(s['max_tokens'], 5000)

    def test_models_and_direct_create(self):
        self.assertEqual(crawler.SCREEN_MODEL, 'claude-haiku-4-5-20251001')
        self.assertEqual(crawler.SCREEN_SHADOW_MODEL, 'claude-haiku-5-5')
        # api_usage는 create를 부른 함수 이름으로 라벨을 붙인다 — 두 함수가 각자 직접 불러야 라벨이 갈린다
        self.assertIn('client.messages.create(model=SCREEN_MODEL', inspect.getsource(crawler._screen_batch_haiku))
        self.assertIn('client.messages.create(model=SCREEN_SHADOW_MODEL',
                      inspect.getsource(crawler._screen_shadow_batch))

    def test_shadow_statuses(self):
        req = {'max_tokens': 10, 'messages': []}
        cases = [
            (lambda kw: _tool([{'id': 2, 'tags': ['market']}]), 'ok'),
            (lambda kw: _Resp([], 'refusal'), 'refusal'),
            (lambda kw: _tool([{'id': 1}], 'max_tokens'), 'max_tokens'),
            (lambda kw: _Resp([_Blk('text')]), 'no_tool'),
        ]
        for fn, want in cases:
            res = crawler._screen_shadow_batch(_FakeClient(fn), req)
            self.assertEqual(res['status'], want)
            self.assertIsInstance(res['ms'], int)
            if want == 'ok':
                self.assertEqual(res['verdict'], {2: {'tags': ['market'], 'event': '', 'urgency': ''}})
            else:
                self.assertIsNone(res['verdict'])

        def boom(kw):
            raise RuntimeError('400 bad request')
        res = crawler._screen_shadow_batch(_FakeClient(boom), req)
        self.assertEqual(res['status'], 'error')
        self.assertIn('400 bad request', res['detail'])


class TestShadowRows(unittest.TestCase):
    VIEW = [{'url': f'u{i}', 'title': f'제목{i}', 'summary': f'요약{i}'} for i in range(1, 5)]

    @staticmethod
    def _v(d):
        return {i: {'tags': t, 'event': '', 'urgency': ''} for i, t in d.items()}

    def test_diffs_and_uniform_keys(self):
        prod = self._v({1: ['spectrum'], 2: ['market', 'regulation'], 4: ['ai']})
        shadow = self._v({2: ['regulation', 'market'], 3: ['security'], 4: [], 9: ['ai']})
        rows = crawler._screen_shadow_rows(self.VIEW, prod, {'status': 'ok', 'verdict': shadow, 'ms': 5}, 'ch')
        for r in rows:
            self.assertEqual(set(r), set(crawler._SHADOW_COLS))
            self.assertEqual(r['batch_key'], rows[0]['batch_key'])
            self.assertEqual(r['model'], 'claude-haiku-5-5')
            self.assertEqual(r['criteria_hash'], 'ch')
        head = rows[0]
        self.assertEqual((head['kind'], head['status'], head['prod_ok'], head['n_items']), ('batch', 'ok', True, 4))
        self.assertEqual((head['n_prod'], head['n_shadow'], head['n_diff'], head['n_tag_diff']), (3, 3, 2, 1))
        rel = {r['url']: r for r in rows if r['kind'] == 'relevance'}
        self.assertEqual(set(rel), {'u1', 'u3'})
        self.assertEqual((rel['u1']['prod_relevant'], rel['u1']['shadow_relevant']), (True, False))
        self.assertEqual((rel['u1']['prod_tags'], rel['u1']['shadow_tags']), (['spectrum'], None))
        self.assertEqual((rel['u3']['prod_relevant'], rel['u3']['shadow_relevant']), (False, True))
        self.assertEqual((rel['u3']['title'], rel['u3']['summary']), ('제목3', '요약3'))
        tags = [r for r in rows if r['kind'] == 'tags']
        self.assertEqual([(r['url'], r['prod_tags'], r['shadow_tags']) for r in tags], [('u4', ['ai'], [])])

    def test_prod_fail_or_shadow_fail_gives_batch_row_only(self):
        shadow = self._v({1: []})
        rows = crawler._screen_shadow_rows(self.VIEW, None, {'status': 'ok', 'verdict': shadow, 'ms': 3}, 'ch')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['prod_ok'], rows[0]['n_prod'], rows[0]['n_shadow'], rows[0]['n_diff']),
                         (False, None, 1, None))
        rows = crawler._screen_shadow_rows(self.VIEW, self._v({1: []}),
                                           {'status': 'refusal', 'verdict': None, 'ms': 3}, 'ch')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['status'], rows[0]['n_prod'], rows[0]['n_shadow']), ('refusal', 1, None))


class TestShadowSwitch(unittest.TestCase):

    def _until(self, sb):
        with mock.patch.object(crawler, 'sb', sb), contextlib.redirect_stdout(io.StringIO()):
            return crawler._screen_shadow_until()

    def test_off_cases(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        for rows in ([], [{'value': 'not json'}], [{'value': '{}'}], [{'value': '{"until": "2099-01-01T00:00:00"}'}],
                     [{'value': json.dumps({'until': past})}], [{'value': '"2099-01-01T00:00:00+09:00"'}]):
            self.assertIsNone(self._until(_FakeSb(rows)), rows)
        self.assertIsNone(self._until(_FakeSb(exc=RuntimeError('down'))))

    def test_on(self):
        got = self._until(_FakeSb([{'value': '{"until": "2099-01-01T00:00:00+09:00"}'}]))
        self.assertEqual(got, datetime(2099, 1, 1, tzinfo=timezone(timedelta(hours=9))))


class TestScreenWithShadow(unittest.TestCase):
    ITEMS = [{'title': f'통신 기사 {i}', 'url': f'n{i}', '_screen_text': f'요약 {i}'} for i in range(1, 41)]

    @staticmethod
    def _prod(client, criteria, batch):
        # 홀수 번째만 관련, 태그 spectrum
        return {i: {'tags': ['spectrum'], 'event': f'사건{i}', 'urgency': ''} for i in range(1, len(batch) + 1, 2)}

    def _run(self, shadow_fn, until=True, wait_s=None):
        sb = _FakeSb()
        made = []

        def fake_anthropic(**kw):
            cli = _FakeClient(shadow_fn)
            made.append((kw, cli))
            return cli
        patches = [
            mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'x'),
            mock.patch.object(crawler, 'load_news_criteria', lambda: '기준'),
            mock.patch.object(crawler.anthropic, 'Anthropic', fake_anthropic),
            mock.patch.object(crawler, '_load_screen_cache', lambda h, urls: {}),
            mock.patch.object(crawler, '_save_screen_cache', lambda rows: None),
            mock.patch.object(crawler, '_screen_batch_haiku', self._prod),
            mock.patch.object(crawler, '_screen_shadow_until',
                              (lambda: datetime(2099, 1, 1, tzinfo=timezone.utc)) if until else (lambda: None)),
            mock.patch.object(crawler, 'sb', sb),
        ]
        if wait_s is not None:
            patches.append(mock.patch.object(crawler, 'SCREEN_SHADOW_WAIT_S', wait_s))
        buf = io.StringIO()
        with _fixed_system(), contextlib.ExitStack() as st:
            for p in patches:
                st.enter_context(p)
            st.enter_context(contextlib.redirect_stdout(buf))
            passed = crawler.screen_news_items([dict(i) for i in self.ITEMS])
        view = [(p['title'], p['tags'], p['event']) for p in passed]
        shadow_made = [m for m in made if 'timeout' in m[0]]   # 운영 클라이언트는 api_key만 받는다
        return view, sb.inserted, shadow_made, buf.getvalue()

    def test_prod_result_unchanged(self):
        base, rows0, made0, _ = self._run(None, until=False)
        self.assertEqual((rows0, made0), ([], []))           # 꺼짐 = 그림자 클라이언트도 안 만든다
        self.assertEqual(len(base), 21)                      # 35건 배치 홀수 18 + 5건 배치 홀수 3

        def shadow_all(kw):                                   # 5.5는 전건 관련
            n = len(json.loads(kw['messages'][0]['content'].split('\n\n', 1)[1]))
            return _tool([{'id': i, 'tags': ['market']} for i in range(1, n + 1)])
        view, rows, made, log = self._run(shadow_all)
        self.assertEqual(view, base)
        self.assertEqual(made[0][0].get('timeout'), crawler.SCREEN_SHADOW_TIMEOUT_S)
        self.assertEqual(made[0][0].get('max_retries'), 1)
        self.assertEqual([c['model'] for c in made[0][1].calls], ['claude-haiku-5-5'] * 2)   # 35 + 5건 두 배치
        heads = [r for r in rows if r['kind'] == 'batch']
        self.assertEqual([(h['n_items'], h['status'], h['n_diff']) for h in heads], [(35, 'ok', 17), (5, 'ok', 2)])
        self.assertEqual(sum(1 for r in rows if r['kind'] == 'relevance'), 19)
        self.assertEqual(sum(1 for r in rows if r['kind'] == 'tags'), 21)
        self.assertIn('[선별 그림자] claude-haiku-5-5 배치 2개(ok 2)', log)

        def boom(kw):
            raise RuntimeError('400')
        view, rows, _, _ = self._run(boom)
        self.assertEqual(view, base)
        self.assertEqual([r['status'] for r in rows], ['error', 'error'])

        def refuse(kw):
            return _Resp([], 'refusal')
        view, rows, _, _ = self._run(refuse)
        self.assertEqual(view, base)
        self.assertEqual([r['status'] for r in rows], ['refusal', 'refusal'])

    def test_timeout_does_not_block(self):
        base, _, _, _ = self._run(None, until=False)

        def slow(kw):
            time.sleep(0.6)
            return _tool([])
        t0 = time.monotonic()
        view, rows, _, _ = self._run(slow, wait_s=0.05)
        self.assertLess(time.monotonic() - t0, 0.6)
        self.assertEqual(view, base)
        self.assertEqual({r['status'] for r in rows}, {'timeout'})

    def test_insert_failure_is_swallowed(self):
        base, _, _, _ = self._run(None, until=False)
        with mock.patch.object(crawler, '_save_shadow_rows', side_effect=RuntimeError('db down')):
            view, _, _, log = self._run(lambda kw: _tool([]))
        self.assertEqual(view, base)
        self.assertIn('[선별 그림자] 마무리 실패(무시)', log)


if __name__ == '__main__':
    unittest.main()
