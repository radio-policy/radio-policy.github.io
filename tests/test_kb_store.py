# -*- coding: utf-8 -*-
"""
kb_store 공용화(#218 — 개선안 §4-2-12 단계 B) 테스트. 표준 unittest, 네트워크·DB 없음.

  - 구조 가드: document_chunks 일괄 삽입·law_watch 현행 등록을 kb_store 밖에서 다시 쓰지 못하게
  - 조각 규칙: 옛 사용처 이름(upload_law_pdf.chunk_text 등)이 공용 함수 그 자체인지 + 규칙 고정값
  - insert_chunks 검증 / register_watch / list_docs 페이지 — 가짜 클라이언트로
"""
import os
import re
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import kb_store  # noqa: E402


def _py_files():
    for name in sorted(os.listdir(_ROOT)):
        if name.endswith('.py'):
            with open(os.path.join(_ROOT, name), encoding='utf-8', errors='replace') as f:
                yield name, f.read()


class TestNoCopies(unittest.TestCase):
    def test_chunk_insert_only_in_kb_store(self):
        pat = re.compile(r"""table\(\s*['"]document_chunks['"]\s*\)\s*\.\s*insert\(""")
        # minutes_offline._swap_doc 은 임시 사본 → 내용 대조 → 교체라는 자체 검증이 있어 예외
        allowed = {'kb_store.py', 'minutes_offline.py'}
        bad = [n for n, s in _py_files() if n not in allowed and pat.search(s)]
        self.assertEqual(bad, [], 'document_chunks 삽입은 kb_store.insert_chunks로 (검증 포함, #218)')

    def test_watch_register_only_in_kb_store(self):
        pat = re.compile(r"""table\(\s*['"]law_watch['"]\s*\)\s*\.\s*upsert\(""")
        # law_watch.py 는 감시 결과(제외·outdated·pending 요약) 기록이라 뜻이 달라 예외
        allowed = {'kb_store.py', 'law_watch.py'}
        bad = [n for n, s in _py_files() if n not in allowed and pat.search(s)]
        self.assertEqual(bad, [], "law_watch '현행본 등록'은 kb_store.register_watch로 (#218)")

    def test_chunkers_are_the_shared_functions(self):
        import upload_law_pdf, kb_reextract, press_ingest, issue_case_ingest
        self.assertIs(upload_law_pdf.chunk_text, kb_store.chunk_pdf_text)
        self.assertIs(kb_reextract.chunk_text, kb_store.chunk_pdf_text)
        self.assertIs(press_ingest._chunk_text, kb_store.chunk_by_newline)
        self.assertIs(issue_case_ingest.chunk_text, kb_store.chunk_by_newline)
        self.assertEqual(press_ingest.CHUNK_SIZE, 700)


class TestChunkRules(unittest.TestCase):
    def test_pdf_article_split(self):
        body = ''.join('제%d조(항목%d) %s\n' % (i, i, '가' * 60) for i in range(1, 7))
        ch = kb_store.chunk_pdf_text(body)
        self.assertEqual([c['article_no'] for c in ch], ['%d조(항목%d)' % (i, i) for i in range(1, 7)])

    def test_pdf_few_headers_means_size_split(self):
        text = '제1조(목적) ' + '나' * 2000          # 조문 헤더 5개 미만 → 통째로 800/100 크기 분할
        ch = kb_store.chunk_pdf_text(text)
        self.assertEqual([len(c['content']) for c in ch][:2], [800, 800])
        self.assertEqual(ch[1]['content'][:100], text[700:800])   # 100자 겹침
        self.assertTrue(all(c['article_no'] == '1조(목적)' for c in ch))

    def test_pdf_drops_tiny_chunks(self):
        self.assertEqual(kb_store.chunk_pdf_text('짧다'), [])

    def test_newline_round_trip(self):
        text = ''.join('줄%d %s\n' % (i, '다' * (i * 37 % 300)) for i in range(200))
        ch = kb_store.chunk_by_newline(text)
        self.assertEqual(''.join(ch), text)
        self.assertTrue(all(len(c) <= 700 for c in ch))


class _Q:
    """document_chunks count 조회를 흉내 내는 가짜 쿼리 — 필터를 기록하고 정해진 count를 돌려준다."""
    def __init__(self, fake, table):
        self.fake, self.table, self.filters, self.payload = fake, table, [], None

    def insert(self, rows):
        self.fake.inserted.append(list(rows)); return self

    def upsert(self, row, on_conflict=None):
        self.fake.upserts.append((self.table, row, on_conflict)); return self

    def delete(self):
        self.filters.append(('delete',)); return self

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self.filters.append(('eq', k, v)); return self

    def gte(self, k, v):
        self.filters.append(('gte', k, v)); return self

    def lte(self, k, v):
        self.filters.append(('lte', k, v)); return self

    def limit(self, _n):
        return self

    def range(self, a, b):
        self.filters.append(('range', a, b)); return self

    def execute(self):
        if ('delete',) in self.filters:
            self.fake.deletes.append((self.table, self.filters))
        self.fake.queries.append(self.filters)

        class R: pass
        r = R()
        r.count = self.fake.count_fn(self.filters)
        r.data = self.fake.rpc_pages.pop(0) if self.table == 'rpc' and self.fake.rpc_pages else []
        return r


class _FakeSb:
    def __init__(self, count_fn=lambda f: 0, rpc_pages=None):
        self.count_fn, self.rpc_pages = count_fn, list(rpc_pages or [])
        self.inserted, self.upserts, self.deletes, self.queries, self.rpc_calls = [], [], [], [], []

    def table(self, name):
        return _Q(self, name)

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return _Q(self, 'rpc')


class TestInsertChunks(unittest.TestCase):
    def _rows(self, doc, start, n, status='current'):
        return [{'doc_name': doc, 'chunk_index': start + i, 'content': 'x', 'status': status} for i in range(n)]

    def test_batches_and_verifies_per_doc_range(self):
        rows = self._rows('A', 0, 120) + self._rows('B', 7, 3)
        want = {'A': 120, 'B': 3}
        fake = _FakeSb(count_fn=lambda f: next((want[x[2]] for x in f if x[:2] == ('eq', 'doc_name')), 0))
        self.assertEqual(kb_store.insert_chunks(fake, rows), 123)
        self.assertEqual([len(b) for b in fake.inserted], [50, 50, 23])
        b_query = [q for q in fake.queries if ('eq', 'doc_name', 'B') in q][0]
        self.assertIn(('gte', 'chunk_index', 7), b_query)   # 이어붙임은 범위로 센다
        self.assertIn(('lte', 'chunk_index', 9), b_query)
        self.assertIn(('eq', 'status', 'current'), b_query)

    def test_partial_insert_raises(self):
        fake = _FakeSb(count_fn=lambda f: 49)
        with self.assertRaises(RuntimeError):
            kb_store.insert_chunks(fake, self._rows('A', 0, 50))

    def test_mixed_or_missing_status_not_filtered(self):
        rows = [{'doc_name': 'A', 'chunk_index': 0, 'content': 'x'}]
        fake = _FakeSb(count_fn=lambda f: 1)
        kb_store.insert_chunks(fake, rows)
        self.assertFalse(any(x[:2] == ('eq', 'status') for x in fake.queries[-1]))


class TestRegisterWatchAndListDocs(unittest.TestCase):
    def test_register_watch_row_and_replace(self):
        fake = _FakeSb()
        kb_store.register_watch(fake, doc_name='새(법률)', law_name='법', law_type_token='법률',
                                api_target='law', law_id='1', mst='9', law_no='21000', enf='20260101',
                                note='n', now='T', replaces='옛(법률)')
        table, row, conflict = fake.upserts[0]
        self.assertEqual((table, conflict), ('law_watch', 'doc_name'))
        self.assertEqual(row['registered_mst'], '9'); self.assertEqual(row['latest_enf'], '20260101')
        self.assertEqual((row['watch_status'], row['sync_status']), ('watching', 'current'))
        self.assertEqual(len(row), 16)
        self.assertEqual(fake.deletes[0][1][-1], ('eq', 'doc_name', '옛(법률)'))

    def test_register_watch_same_name_no_delete(self):
        fake = _FakeSb()
        kb_store.register_watch(fake, doc_name='A', law_name='법', law_type_token=None, api_target='law',
                                law_id=None, mst='1', law_no=None, enf='2', note='n', replaces='A')
        self.assertEqual(fake.deletes, [])

    def test_list_docs_pages_until_short_page(self):
        p1 = [{'doc_name': 'd%04d' % i, 'doc_category': '법령'} for i in range(3)]
        p2 = [{'doc_name': 'e', 'doc_category': None}]
        fake = _FakeSb(rpc_pages=[p1, p2])
        out = kb_store.list_docs(fake, category='법령', page=3)
        self.assertEqual(list(out), ['d0000', 'd0001', 'd0002', 'e'])
        self.assertEqual(fake.rpc_calls[0], ('kb_doc_names', {'p_status': None, 'p_category': '법령'}))


if __name__ == '__main__':
    unittest.main()
