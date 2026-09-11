# -*- coding: utf-8 -*-
"""
law_terms_sync 순수 함수 테스트 (#156) — 표준 unittest, 네트워크·DB 없음.
픽스처는 2026-09-11 실DB document_chunks에서 그대로 옮긴 조문 형식들이다.

실행: C:\\Users\\SKTelecom\\AppData\\Local\\Programs\\Python\\Python312\\python.exe -m unittest discover -s tests -v
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import law_terms_sync as lt


RADIO_ACT = (
    '제2조(정의)\n①이 법에서 사용하는 용어의 뜻은 다음과 같다. <개정 2008.6.13, 2020.6.9>\n'
    '1.  "전파"란 인공적인 유도(誘導) 없이 공간에 퍼져 나가는 전자파로서 국제전기통신연합이 정한 범위의 주파수를 가진 것을 말한다.\n'
    '2.  "주파수분배"란 특정한 주파수의 용도를 정하는 것을 말한다.\n'
    '4.  "주파수지정"이란 허가나 신고로 개설하는 무선국에서 이용할 특정한 주파수를 지정하는 것을 말한다.\n'
    '4의2.  "주파수 사용승인"이란 안보ㆍ외교적 목적 또는 국제적ㆍ국가적 행사 등을 위하여 특정한 주파수의 사용을 허용하는 것을 말한다.\n'
    '6.  "무선국(無線局)"이란 무선설비와 무선설비를 조작하는 자의 총체를 말한다. 다만, 방송수신만을 목적으로 하는 것은 제외한다.\n'
    '7.  "무선종사자"란 무선설비를 조작하거나 설치공사를 하는 사람으로서 제70조제2항에 따라 기술자격증을 발급받은 사람을 말한다.\n'
    '② 이 법에서 사용하는 용어의 뜻은 제1항에서 정하는 것 외에는 「방송통신발전 기본법」에서 정하는 바에 따른다. <신설 2010.7.23>'
)


class TestMergeChunks(unittest.TestCase):
    def test_overlap_stripped(self):
        a = 'X' * 300 + '5의2.  "무선통신"이란 전파를 이용하여 모든 종류의 기호ㆍ신호ㆍ문언ㆍ영상ㆍ음향 등의 정보를 보내거나 받는 것을 말한다.\n6.  "무선국(無線局)"이란 무선설비와 무선설비를 조작하는 자의 총체를 말한다. 다만, 방송수신만을 목적으로'
        b = '기호ㆍ신호ㆍ문언ㆍ영상ㆍ음향 등의 정보를 보내거나 받는 것을 말한다.\n6.  "무선국(無線局)"이란 무선설비와 무선설비를 조작하는 자의 총체를 말한다. 다만, 방송수신만을 목적으로 하는 것은 제외한다.\n7.  "무선종사자"란'
        merged = lt.merge_chunks([a, b])
        self.assertEqual(merged.count('"무선국(無線局)"이란'), 1)
        self.assertTrue(merged.endswith('7.  "무선종사자"란'))
        self.assertEqual(merged, a + ' 하는 것은 제외한다.\n7.  "무선종사자"란')

    def test_no_overlap_joined_with_newline(self):
        self.assertEqual(lt.merge_chunks(['가나다라마바사', '아자차카타파하']), '가나다라마바사\n아자차카타파하')

    def test_short_common_tail_not_treated_as_overlap(self):
        a = 'A' * 50 + '을 말한다.\n'
        b = '을 말한다.\n' + 'B' * 50
        self.assertEqual(lt.merge_chunks([a, b]), a + '\n' + b)

    def test_single_and_empty(self):
        self.assertEqual(lt.merge_chunks(['abc']), 'abc')
        self.assertEqual(lt.merge_chunks([]), '')


class TestParseDefinitions(unittest.TestCase):
    def test_law_newline_style(self):
        rows, unparsed = lt.parse_definitions(RADIO_ACT, '2조(정의)')
        self.assertEqual(unparsed, [])
        self.assertEqual([r['item_no'] for r in rows], ['1', '2', '4', '4의2', '6', '7'])
        self.assertEqual(rows[0]['term'], '전파')
        self.assertTrue(rows[0]['definition'].startswith('"전파"란 인공적인'))
        r6 = rows[4]
        self.assertEqual((r6['term'], r6['term_alias']), ('무선국', '無線局'))
        self.assertIn('방송수신만을 목적으로 하는 것은 제외한다.', r6['definition'])
        # ② 항(참조만)은 행이 되지 않고, <개정…> 꼬리도 남지 않는다
        self.assertFalse(any('②' in r['definition'] or '<개정' in r['definition'] for r in rows))
        # 제70조제2항 은 호 경계로 오인되지 않는다
        self.assertIn('제70조제2항에 따라', rows[5]['definition'])

    def test_deleted_item_skipped(self):
        body = ('제2조(정의) 이 영에서 사용하는 용어의 뜻은 다음과 같다. <개정 2013.3.23>\n'
                '1.  삭제 <2008.6.20>\n2.  "송신설비"란 전파를 보내는 설비로서 송신장치와 송신안테나계로 구성되는 설비를 말한다.')
        rows, unparsed = lt.parse_definitions(body)
        self.assertEqual([r['item_no'] for r in rows], ['2'])
        self.assertEqual(rows[0]['term'], '송신설비')

    def test_notice_without_newlines_and_nested_quotes(self):
        body = ('제2조(정의) 이 고시에서 사용하는 용어의 정의는 다음과 같다.'
                '1. "번호이동"이라 함은 가입자가 전기통신사업자의 변경에도 불구하고 종전의 전기통신번호를 유지하는 것을 말한다.'
                '2. "소프트웨어프로세스"라 함은 「소프트웨어 진흥법」(이하 "법"이라 한다) 제2조제5호에 따라 정의된 것을 말한다.'
                '8. "번호이동관리기관(이하 "관리기관"이라 한다)"이란 과학기술정보통신부장관이 지정한 전문기관을 말한다.')
        rows, unparsed = lt.parse_definitions(body)
        self.assertEqual(unparsed, [])
        self.assertEqual([r['item_no'] for r in rows], ['1', '2', '8'])
        self.assertEqual(rows[1]['term'], '소프트웨어프로세스')
        self.assertIn('제2조제5호에 따라', rows[1]['definition'])
        self.assertEqual(rows[2]['term'], '번호이동관리기관')
        self.assertIsNone(rows[2]['term_alias'])

    def test_alias_after_quote_and_curly_quotes_with_page_marks(self):
        body = ('제2조(정의)\n① 이 규칙에서 사용하는 용어의 뜻은 다음과 같다.\n'
                '1. "발사"(發射)란 송신설비가 전파를 공간으로 송신하는 것을 말한다.\n'
                '9. "스퓨리어스 발사"(Spurious 發射)란 필요주파수대역폭 바깥쪽에서 발생하는 발사를 말한다.\n')
        rows, _ = lt.parse_definitions(body)
        self.assertEqual([(r['term'], r['term_alias']) for r in rows],
                         [('발사', '發射'), ('스퓨리어스 발사', 'Spurious 發射')])
        body2 = ('제2조(정의) 이 고시에서 사용하는 용어의 정의는 다음과 같다.\n'
                 '1. “일괄처리”라 함은 여러 건을 한꺼번에\n처리하는 것을 말한다.\n- 1 -\n\n2. “안전인증기관”이라 함은 지정받은 기관을 말한다.')
        rows2, unparsed2 = lt.parse_definitions(body2)
        self.assertEqual(unparsed2, [])
        self.assertEqual([r['term'] for r in rows2], ['일괄처리', '안전인증기관'])
        self.assertNotIn('- 1 -', rows2[0]['definition'])
        self.assertIn('한꺼번에 처리하는', rows2[0]['definition'])

    def test_sub_items_kept_in_parent(self):
        body = ('제2조(정의)\n28. "장려금"이란 다음 각 목의 어느 하나에 해당하는 경제적 이익을 말한다.\n'
                '가. 이동통신사업자가 대리점에 지급하는 금전\n나. 대리점이 판매점에 지급하는 금전\n'
                '29. "이용자"란 전기통신역무를 제공받는 자를 말한다.')
        rows, _ = lt.parse_definitions(body)
        self.assertEqual([r['item_no'] for r in rows], ['28', '29'])
        self.assertIn('\n가. 이동통신사업자', rows[0]['definition'])
        self.assertIn('\n나. 대리점이', rows[0]['definition'])

    def test_hang_numbered_and_single_unnumbered(self):
        body = ('제2조(정의) ① "기본징수율"이란 방송통신발전기금 분담금 산정의 기준 비율을 말한다. '
                '② "최종징수율"이란 기본징수율에 조정계수를 곱한 비율을 말한다.')
        rows, unparsed = lt.parse_definitions(body)
        self.assertEqual(unparsed, [])
        self.assertEqual([(r['item_no'], r['term']) for r in rows], [('1항', '기본징수율'), ('2항', '최종징수율')])
        body2 = '제2조(정의) 이 고시에서 사용하는 "등록신청법인"이라 함은 등록을 신청하는 법인을 말한다.'
        rows2, _ = lt.parse_definitions(body2)
        self.assertEqual([(r['item_no'], r['term']) for r in rows2], [('본문', '등록신청법인')])
        self.assertTrue(rows2[0]['definition'].startswith('"등록신청법인"'))

    def test_colon_style(self):
        body = ('제2조(용어의 정의) 이 고시에서 사용하는 용어의 정의는 다음과 같다.'
                '1. 협정료(accounting rate) : 국제전화역무 제공사업자 간에 합의한 요율을 말한다.'
                '2. 정산료(settlement rate) : 협정료를 기준으로 상대 사업자에게 지급하는 요율을 말한다.')
        rows, unparsed = lt.parse_definitions(body)
        self.assertEqual(unparsed, [])
        self.assertEqual([(r['term'], r['term_alias']) for r in rows],
                         [('협정료', 'accounting rate'), ('정산료', 'settlement rate')])

    def test_reference_only_yields_nothing(self):
        body = '제2조(정의) 이 기준에서 사용하는 용어의 뜻은 무선설비규칙 및 관련 법령이 정하는 바에 따른다.'
        rows, unparsed = lt.parse_definitions(body)
        self.assertEqual(rows, [])
        self.assertEqual(unparsed, [])

    def test_duplicate_item_no_gets_suffix(self):
        body = '제2조(정의)\n1. "가"란 첫째를 말한다.\n1. "가"란 첫째를 말한다.'
        rows, _ = lt.parse_definitions(body)
        self.assertEqual([r['item_no'] for r in rows], ['1', '1-2'])


class TestTitleAndLawType(unittest.TestCase):
    def test_title_regex_exact(self):
        for ok in ['2조(정의)', '19조의2(정의)', '2조(용어의 정의)', '2조(용어정의)', '3조(용어의 뜻)']:
            self.assertIsNotNone(lt.DEF_TITLE_RE.match(ok), ok)
        for bad in ['28조의2(분쟁조정의 특례)', '15조(우수 정보보호기업 지정의 방법 등)', '17조(기금계정의 설치 및 회계기관)', '2조(정의 등)']:
            self.assertIsNone(lt.DEF_TITLE_RE.match(bad), bad)

    def test_law_type_of(self):
        cases = {
            '전파법(법률)(제21065호)(20260102)': ('전파법', '법률', '제21065호', '20260102'),
            '전파법 시행령(대통령령)(제35801호)(20251001)': ('전파법 시행령', '대통령령', '제35801호', '20251001'),
            '무선설비규칙(과학기술정보통신부령)(제00086호)(20220104)': ('무선설비규칙', '부령', '제00086호', '20220104'),
            '결합판매의 금지행위 세부 유형 및 심사기준(방송미디어통신위원회고시)(제2026-11호)(20260518)':
                ('결합판매의 금지행위 세부 유형 및 심사기준', '고시', '제2026-11호', '20260518'),
            '전파응용설비 기준(국립전파연구원공고)(제2025-1호)(20250101)': ('전파응용설비 기준', '공고', '제2025-1호', '20250101'),
        }
        for doc, (name, typ, no, enf) in cases.items():
            law_name, _full, law_type, law_no, e = lt.law_type_of(doc)
            self.assertEqual((law_name, law_type, law_no, e), (name, typ, no, enf), doc)
        self.assertEqual(lt.law_type_of('전기통신사업법 시행령.pdf')[2], '대통령령')
        self.assertEqual(lt.law_type_of('어떤 지침.pdf')[2], '기타')

    def test_term_key(self):
        self.assertEqual(lt.term_key('주파수 사용승인'), '주파수사용승인')
        self.assertEqual(lt.term_key('무선국(無線局)'), '무선국')
        self.assertEqual(lt.term_key('Spurious 발사'), 'spurious발사')


if __name__ == '__main__':
    unittest.main()
