# -*- coding: utf-8 -*-
"""
news_known(#234 — 개선안 §2-13 2단계, 뉴스 중복 대조 공용) 테스트. 표준 unittest, 네트워크·DB 없음.

  - DB 함수 대조 결과가 그대로 쓰이는지, 청크로 나눠 부르는지
  - DB 함수 실패·이상 결과(후보 다수인데 기존 0건) → 전량 조회로 되돌아가는지
  - 전량 조회까지 실패하면 예외 — 빈 명단으로 진행하지 않는지(재알림 방지)
  - 선별 캐시: 실패 → 전량 조회 → 그것도 실패하면 빈 dict(fail-open)
  - 구조 가드: news_feed 전량을 url·제목으로 내려받는 중복 대조가 news_known 밖에 다시 생기지 않게
"""
import os
import re
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import news_known  # noqa: E402


class _Res:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.lo, self.hi = db, table, 0, 10 ** 9

    def select(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, lo, hi):
        self.lo, self.hi = lo, hi
        return self

    def execute(self):
        if self.db.table_error:
            raise RuntimeError('table down')
        return _Res(self.db.tables.get(self.table, [])[self.lo:self.hi + 1])


class _Rpc:
    def __init__(self, db, name, params):
        self.db, self.name, self.params = db, name, params

    def execute(self):
        self.db.rpc_calls.append((self.name, self.params))
        if self.db.rpc_error:
            raise RuntimeError('rpc down')
        nf, dn = self.db.tables['news_feed'], self.db.tables['deleted_news']
        if self.name == 'news_known_items':
            src = nf + (dn if self.params['p_include_deleted'] else [])
            if self.db.rpc_empty:
                return _Res({'urls': [], 'titles': []})
            urls = {r['url'] for r in src} & set(self.params['p_urls'])
            titles = {r['title'] for r in src} & set(self.params['p_titles'])
            return _Res({'urls': sorted(urls), 'titles': sorted(titles)})
        cache = self.db.tables['news_screen_cache']
        return _Res({r['url']: r['title_hash'] for r in cache
                     if r['url'] in self.params['p_urls'] and r['criteria_hash'] == self.params['p_criteria_hash']})


class _FakeSb:
    def __init__(self, n=2500):
        self.tables = {
            'news_feed': [{'url': f'u{i}', 'title': f't{i}'} for i in range(n)],
            'deleted_news': [{'url': 'del1', 'title': 'deltitle'}],
            'news_screen_cache': [{'url': f'u{i}', 'title_hash': f'h{i}', 'criteria_hash': 'C' if i % 2 else 'D'}
                                  for i in range(n)],
        }
        self.rpc_calls, self.rpc_error, self.rpc_empty, self.table_error = [], False, False, False

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, params):
        return _Rpc(self, name, params)


def _items(urls):
    return [{'url': u, 'title': 't' + u[1:] if u.startswith('u') else 'x' + u} for u in urls]


class TestKnownOrFull(unittest.TestCase):
    def run_q(self, fn, *a, **k):
        with redirect_stdout(StringIO()) as out:
            r = fn(*a, **k)
        return r, out.getvalue()

    def test_rpc_result_used_and_chunked(self):
        sb = _FakeSb()
        cand = _items([f'u{i}' for i in range(0, 2400, 2)] + ['new1', 'del1'])   # 1,202 후보 → 2왕복
        (ku, kt), log = self.run_q(news_known.known_or_full, sb, cand, include_deleted=True)
        self.assertEqual(ku, {f'u{i}' for i in range(0, 2400, 2)} | {'del1'})
        self.assertIn('t0', kt)
        self.assertEqual(len(sb.rpc_calls), 2)
        self.assertIn('DB 대조', log)

    def test_include_deleted_false(self):
        sb = _FakeSb()
        (ku, _), _ = self.run_q(news_known.known_or_full, sb, _items(['u1', 'del1']), include_deleted=False)
        self.assertEqual(ku, {'u1'})

    def test_rpc_failure_falls_back_to_full(self):
        sb = _FakeSb()
        sb.rpc_error = True
        (ku, kt), log = self.run_q(news_known.known_or_full, sb, _items(['u1', 'new1']), include_deleted=True)
        self.assertIn('u1', ku)
        self.assertIn('del1', ku)            # 전량 집합 — 후보 포함 여부 판정은 같다
        self.assertNotIn('new1', ku)
        self.assertIn('전량 조회로 진행', log)

    def test_suspicious_empty_result_falls_back(self):
        sb = _FakeSb()
        sb.rpc_empty = True
        cand = _items([f'u{i}' for i in range(news_known.SUSPECT_MIN)])
        (ku, _), log = self.run_q(news_known.known_or_full, sb, cand, include_deleted=True)
        self.assertIn('u0', ku)
        self.assertIn('결과 이상', log)

    def test_small_empty_result_is_trusted(self):
        sb = _FakeSb()
        sb.rpc_empty = True
        (ku, _), _ = self.run_q(news_known.known_or_full, sb, _items(['new1', 'new2']), include_deleted=True)
        self.assertEqual(ku, set())

    def test_total_failure_raises(self):
        sb = _FakeSb()
        sb.rpc_error = True
        sb.table_error = True
        with redirect_stdout(StringIO()):
            with self.assertRaises(RuntimeError):
                news_known.known_or_full(sb, _items(['u1']), include_deleted=True)


class TestScreenCache(unittest.TestCase):
    def test_rpc_and_fallbacks(self):
        sb = _FakeSb()
        want = {'u1': 'h1', 'u3': 'h3'}
        self.assertEqual(news_known.screen_cache(sb, ['u1', 'u2', 'u3', 'zz'], 'C'), want)
        sb.rpc_error = True
        with redirect_stdout(StringIO()):
            got = news_known.screen_cache(sb, ['u1'], 'C')
        self.assertEqual({k: got[k] for k in ('u1', 'u3')}, want)   # 전량 dict — 후보 조회 결과는 같다
        sb.table_error = True
        with redirect_stdout(StringIO()):
            self.assertEqual(news_known.screen_cache(sb, ['u1'], 'C'), {})

    def test_full_paging_orders_unique(self):
        sb = _FakeSb(n=2500)
        rows = news_known.fetch_all_rows(sb, 'news_feed', 'url,title')
        self.assertEqual(len(rows), 2500)


class TestNoCopies(unittest.TestCase):
    """news_feed를 url·제목으로 통째로 받아 중복 대조하는 코드가 news_known 밖에 다시 생기지 않게(#234)."""
    PAT = re.compile(r"""table\(\s*['"]news_feed['"]\s*\)\s*\.select\(\s*['"]url\s*,\s*title['"]""")

    def test_no_full_dedupe_outside_news_known(self):
        bad = []
        for name in sorted(os.listdir(_ROOT)):
            if not name.endswith('.py') or name == 'news_known.py':
                continue
            with open(os.path.join(_ROOT, name), encoding='utf-8', errors='replace') as f:
                if self.PAT.search(f.read()):
                    bad.append(name)
        self.assertEqual(bad, [], 'news_feed url·title 전량 조회는 news_known.known_or_full을 쓸 것(#234)')


if __name__ == '__main__':
    unittest.main()
