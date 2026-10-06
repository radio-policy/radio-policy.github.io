# -*- coding: utf-8 -*-
"""무선국 등록면허세 근거 조문 감시(tax_clause_watch, #287) — 순수 함수만. 네트워크·DB 없음."""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import tax_clause_watch as W  # noqa: E402


def _annex():
    rows = lambda lo, hi, w: ''.join(f'{i}. 「어떤법」 제{i}조에 따른 {w} 허가 줄 {i}\n' for i in range(lo, hi))
    return ('■ 지방세법 시행령 [별표 1] <개정 2026. 6. 23.>\n면허의 종류와 종별 구분(제39조 관련)\n<제1종>\n' + rows(1, 40, '영업')
            + '<제2종>\n' + rows(1, 40, '영업') + '<제3종>\n' + rows(1, 30, '영업')
            + '128. 「전파법」 제19조 및 제19조의2에 따른 무선국의 개설 허가 및 신고.\n다만, 아마추어 무선국은 제외한다.\n'
            + rows(129, 160, '영업') + '<제4종>\n' + rows(1, 30, '영업')).strip()


class TestNormAndMerge(unittest.TestCase):
    def test_fingerprint_ignores_img_and_spaces(self):
        a = '①세율 <img src="http://x/flDownload.do?flSeq=1" alt="img1" >│제3종 │40,500원│</img>'
        b = '①세율<img src="http://x/flDownload.do?flSeq=99" alt="img99">│제3종│40,500원│'
        self.assertEqual(W.fingerprint(a), W.fingerprint(b))
        self.assertNotEqual(W.fingerprint(a), W.fingerprint(a.replace('40,500', '45,000')))

    def test_merge_restores_annex_through_law_sync_chunks(self):
        import law_sync
        text = _annex()
        chunks = law_sync.chunk_articles([('별표 1(면허의 종류)', text)])
        self.assertTrue(any(c['content'].startswith('〔제3종〕\n') for c in chunks))   # 머리 접두가 붙은 조각을
        self.assertEqual(W.merge_chunks([c['content'] for c in chunks]), text)         # 떼고 겹침을 지우면 원문 그대로


class TestAnnexItems(unittest.TestCase):
    def test_section_and_number_key(self):
        got = W.annex_items(_annex())
        self.assertEqual([k for k, _, _ in got], ['제3종|128'])           # 번호는 구간마다 다시 1부터 — 열쇠에 구간
        key, label, body = got[0]
        self.assertEqual(label, '제3종 제128호')
        self.assertTrue(body.startswith('〔제3종〕 128. 「전파법」'))
        self.assertIn('아마추어 무선국은 제외한다.', body)                  # 다음 줄로 이어진 단서까지 한 항목
        self.assertNotIn('129.', body)


class TestCompare(unittest.TestCase):
    def _item(self, g, h, src='제1호(20260101)', label='항목'):
        return {'group': g, 'label': label, 'src': src, 'hash': h, 'text': 'x' + h}

    def test_first_run_stores_only(self):
        st, lines = W.compare(None, {'a|34조': self._item('a', 'h1')}, {'a', 'b', 'c'}, '2026-10-07')
        self.assertEqual(lines, [])
        self.assertIn('a|34조', st['items'])

    def test_change_new_gone(self):
        old, _ = W.compare(None, {'a|34조': self._item('a', 'h1'), 'c|49조의2': self._item('c', 'c1', label='감면')},
                           {'a', 'b', 'c'}, 'd1')
        same, lines = W.compare(old, {'a|34조': self._item('a', 'h1', src='제2호(20270101)'),
                                      'c|49조의2': self._item('c', 'c1', label='감면')}, {'a', 'b', 'c'}, 'd2')
        self.assertEqual(lines, [])                                          # 판만 바뀌고 글이 같으면 조용히
        _, lines = W.compare(same, {'a|34조': self._item('a', 'h2', label='세율'), 'c|64조의2': self._item('c', 'c2', label='해상')},
                             {'a', 'b', 'c'}, 'd3')
        self.assertEqual(len(lines), 3, lines)
        self.assertTrue(any(l.startswith('✏️ 세율') for l in lines))
        self.assertTrue(any(l.startswith('🆕 해상') for l in lines))
        self.assertTrue(any(l.startswith('🗑 감면') for l in lines))

    def test_failed_group_keeps_old_and_alerts_once(self):
        st, _ = W.compare(None, {'c|49조의2': self._item('c', 'c1', label='감면')}, {'a', 'b', 'c'}, 'd1')
        alerts = []
        for day in range(1, 6):
            st, lines = W.compare(st, {}, {'a', 'b'}, f'f{day}')            # c 갈래 조회 실패 — 사라짐으로 읽지 않는다
            self.assertIn('c|49조의2', st['items'])
            alerts += lines
        self.assertEqual(len(alerts), 1)
        self.assertIn('감시 못 함', alerts[0])
        self.assertEqual(st['fails']['c'], 5)
        st, lines = W.compare(st, {'c|49조의2': self._item('c', 'c1', label='감면')}, {'a', 'b', 'c'}, 'ok')
        self.assertEqual((lines, st['fails']['c']), ([], 0))


if __name__ == '__main__':
    unittest.main()
