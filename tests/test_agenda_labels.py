# -*- coding: utf-8 -*-
"""과방위 발언 블록별 안건(#310, assembly_minutes.agenda_labels) 시험 — 네트워크·DB 없음.
  py -3.12 -m unittest tests.test_agenda_labels
실제 회의록 문장을 줄여 옮겼다(2025-12-09 공청회, 2024-06-25 현안질의 중 고발의 건, 2026-03-24 회부 뒤 절차 안건 등).
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import assembly_minutes as am  # noqa: E402


def B(name, pos, text):
    return {'name': name, 'pos': pos, 'text': text}


CHAIR = ('최민희', '위원장')


def C(text):
    return B(CHAIR[0], CHAIR[1], text)


def M(text, name='이정헌'):
    return B(name, '위원', text)


class TestItems(unittest.TestCase):
    def test_items_and_subparts(self):
        items, parts = am.agenda_items([
            '9. 인공지능(AI) 제정법 관련 입법 공청회', '- 1부`$`(데이터센터법)`$`', '- 2부`$`(산업·인재육성법)`$`',
            '1. 청원심사기간 연장 요구의 건', 'o 의사일정 변경의 건'])
        self.assertEqual(sorted(items), [1, 9])
        self.assertEqual(parts[9], [(1, '1부(데이터센터법)'), (2, '2부(산업·인재육성법)')])

    def test_labels(self):
        items = {2: '방송법 일부개정법률안(정청래 의원 대표발의)(의안번호 2200060)', 3: '방송법 일부개정법률안(이훈기 의원 대표발의)'}
        self.assertEqual(am.agenda_label([2], items), items[2])
        self.assertEqual(am.agenda_label([3, 2], items), '방송법 일부개정법률안 외 1건')

    def test_single_item_meeting_is_none(self):
        self.assertIsNone(am.agenda_labels({'agenda': ['1. 2024년도 국정감사(과학기술정보통신부)']}, [C('상정합니다')]))

    def test_meeting_label_fallback(self):
        m = {'agenda': ['3. 다', '1. 가', '2. 나']}
        self.assertEqual(am.meeting_agenda_label(m), '가 외 2건')
        self.assertEqual(am.meeting_agenda_label({'agenda': ['o 간사 인사', '1. 간사 선임의 건']}), '간사 선임의 건')


class TestRefs(unittest.TestCase):
    items = {n: '안건%d' % n for n in range(1, 47)}

    def test_range_and_list(self):
        r = am._agenda_refs('의사일정 제2항 정청래 의원 대표발의 방송법 일부개정법률안부터 의사일정 제5항까지 일괄 상정합니다', self.items)
        self.assertEqual(r, [2, 3, 4, 5])
        self.assertEqual(am._agenda_refs('의사일정 제15항․제16항, 이상 2건', self.items), [15, 16])
        self.assertEqual(am._agenda_refs('29․30․31항에 대해서', self.items, need_ref=False), [29, 30, 31])
        self.assertEqual(am._agenda_refs('16항～21항의 인가제 관련 논의', self.items, need_ref=False), [16, 17, 18, 19, 20, 21])

    def test_range_without_start_number(self):
        # 「…법률안부터 시작해서 … 42항 …까지」 — 앞 번호를 말하지 않으면 첫 안건부터
        r = am._agenda_refs('방송법 일부개정법률안부터 시작해서 42항 방송통신발전 기본법 일부개정법률안까지 일괄해서 상정',
                            self.items, need_ref=False)
        self.assertEqual(r, list(range(1, 43)))
        # 「18부터 26항까지」 — 「항」 없이 말한 시작 번호
        self.assertEqual(am._agenda_refs('18부터 26항까지를 같이 보도록', self.items, need_ref=False), list(range(18, 27)))

    def test_article_paragraph_not_item(self):
        self.assertEqual(am._agenda_refs('국회법 제57조 7항에 따른 번안의결', self.items, need_ref=False), [])
        self.assertEqual(am._agenda_refs('제27조(청렴 및 비밀유지의무) 1항에 사무처의 직원은', self.items, need_ref=False), [])


class TestSegment(unittest.TestCase):
    def test_hearing_procedures_then_public_hearing(self):
        """2025-12-09: 제1~8항 절차 안건 뒤 제9항 공청회(1부·2부) — 공청회 발언이 첫 안건으로 적히던 사고."""
        m = {'agenda': ['4. 위원장후보자(김종철) 인사청문회 자료제출 요구의 건', '9. 인공지능(AI) 제정법 관련 입법 공청회',
                        '- 1부`$`(데이터센터법)`$`', '- 2부`$`(산업·인재육성법)`$`', '1. 청원심사기간 연장 요구의 건']}
        bl = [C('성원이 되었으므로 개의하겠습니다.'),
              C('의사일정 제1항 청원심사기간 연장 요구의 건을 상정합니다. 이의 없으십니까? 가결되었음을 선포합니다.'),
              C('의사일정 제4항 위원장후보자 인사청문회 자료제출 요구의 건을 상정합니다. 가결되었음을 선포합니다.'),
              C('의사일정 제9항 인공지능(AI) 제정법 관련 입법 공청회를 상정합니다.'),
              C('1부에는 데이터센터와 관련한 법률, 이어서 2부에서는 산업과 인재 육성 관련 법률에 대한 공청회를 실시하겠습니다. '
                '우선 1부에 참석하신 진술인을 소개해 드리겠습니다.'),
              B('나연묵', '진술인', '데이터센터 특별법의 인허가 의제 조항에 대해 말씀드리겠습니다.'),
              M('AIDC 전환 시 교통·환경영향평가는 어떻게 됩니까?'),
              C('회의를 속개합니다. 2부에 참석하신 진술인을 소개해 드리겠습니다.'),
              M('인재 육성 법안의 재원은요?', name='황정아')]
        lab = am.agenda_labels(m, bl)
        self.assertEqual(lab[2], '위원장후보자(김종철) 인사청문회 자료제출 요구의 건')
        self.assertEqual(lab[6], '인공지능(AI) 제정법 관련 입법 공청회 1부(데이터센터법)')
        self.assertEqual(lab[8], '인공지능(AI) 제정법 관련 입법 공청회 2부(산업·인재육성법)')

    def test_procedural_interjection_reverts(self):
        """2024-06-25: 현안질의 도중 고발의 건을 처리하고 말없이 질의로 돌아간다."""
        m = {'agenda': ['1. 과학기술정보통신부 등에 대한 현안질의', '4. 현안질의 불출석 증인 고발의 건']}
        bl = [C('의사일정 제1항 과학기술정보통신부 등에 대한 현안질의를 상정합니다.'),
              M('장관님께 묻겠습니다.'),
              C('간사와의 협의에 따라 현안질의 불출석 증인 고발의 건을 상정합니다.'),
              M('반대합니다. 안건조정위원회에 회부해 주십시오.', name='최형두'),
              C('안건조정위원회로 회부하겠습니다.'),
              M('R&D 예산은 왜 삭감됐습니까?', name='박민규')]
        lab = am.agenda_labels(m, bl)
        self.assertEqual(lab[3], '현안질의 불출석 증인 고발의 건')
        self.assertEqual(lab[5], '과학기술정보통신부 등에 대한 현안질의')

    def test_no_revert_after_bills_referred(self):
        """2026-03-24: 법안 묶음을 소위원회로 회부한 뒤의 절차 안건은 되돌릴 곳이 없다."""
        m = {'agenda': ['4. 인사청문회 증인등 출석요구의 건', '13. 과학기술기본법 일부개정법률안', '14. 전파법 일부개정법률안']}
        bl = [C('의사일정 제13항 과학기술기본법 일부개정법률안부터 의사일정 제14항까지 일괄 상정합니다.'),
              C('대체토론을 마치고 2건의 법안은 소관 법안심사소위원회로 회부하도록 하겠습니다.'),
              C('다음으로 의사일정 제4항 인사청문회 증인등 출석요구의 건을 상정합니다. 이의 없으십니까? 가결되었음을 선포합니다.'),
              M('다음 주 인사청문회와 관련해 한말씀드리겠습니다.')]
        lab = am.agenda_labels(m, bl)
        self.assertEqual(lab[3], '인사청문회 증인등 출석요구의 건')

    def test_vote_on_off_list_motion_does_not_close(self):
        """청문회 도중 목록 밖 동의안 표결(「표결 결과 … 가결」)로는 본안건을 닫지 않는다."""
        m = {'agenda': ['1. 위원장후보자 인사청문요청안', '2. 위원장후보자 인사청문회', '3. 인사청문회 참고인 추가 출석요구의 건']}
        bl = [C('의사일정 제1항 인사청문요청안, 의사일정 제2항 인사청문회를 일괄하여 상정합니다.'),
              C('표결 결과 찬성 열세 분, 반대 여섯 명으로 가결되었음을 선포합니다.'),
              C('인사청문회 참고인 추가 출석요구의 건을 상정합니다. 가결되었음을 선포합니다.'),
              M('후보자께 묻겠습니다.')]
        lab = am.agenda_labels(m, bl)
        self.assertEqual(lab[3], '위원장후보자 인사청문요청안 외 1건')

    def test_subcommittee_moves(self):
        m = {'agenda': ['%d. 법안%d 일부개정법률안' % (n, n) for n in range(1, 21)]}
        bl = [C('의사일정 제1항부터 제20항까지 일괄 상정합니다. 먼저 의사일정 제14항부터 제16항까지 수석전문위원께서 보고해 주시기 바랍니다.'),
              M('14항 관련 질문입니다.'),
              C('제18항부터 제20항까지는 소위원회에서 계속 심사하도록 하겠습니다.'),
              M('이어서 말씀드리면'),
              C('다음, 제9항에 대해 수석전문위원께서 보고해 주시기 바랍니다.'),
              B('김건오', '수석전문위원', '의사일정 제9항 법안9에 대해 보고드리겠습니다.'),
              C('의사일정 제11항에 대해서 수석전문위원께서 보고해 주시기 바랍니다. 아, 제13항입니다.'),
              M('13항 관련 질문'),
              C('그다음에 3항부터 7항까지도 지금 논의하는 게 적절하지는 않은 거지요?'),
              M('그렇습니다')]
        lab = am.agenda_labels(m, bl)
        self.assertEqual(lab[1], '법안14 일부개정법률안 외 2건')
        self.assertEqual(lab[3], '법안14 일부개정법률안 외 2건')     # 보류 문장은 넘어가기가 아니다
        self.assertEqual(lab[5], '법안9 일부개정법률안')
        self.assertEqual(lab[7], '법안13 일부개정법률안')             # 짧은 정정
        self.assertEqual(lab[9], '법안13 일부개정법률안')             # 물음은 넘어가기가 아니다

    def test_convene_preview_is_not_open(self):
        """2025-08-20: 개의 블록의 「이어서 … 결산 … 을 상정하도록 하겠습니다」는 순서 예고다."""
        m = {'agenda': ['1. 소위원장 선출 및 소위 위원 개선의 건', '2. 청원 심사기간 연장 요구의 건', '3. 2024회계연도 결산']}
        bl = [C('성원이 되었으므로 개의하겠습니다. 먼저 소위원장 선출의 건을 처리하고, 이어서 2024회계연도 결산을 상정하도록 하겠습니다.'),
              C('의사일정 제1항 소위원장 선출 및 소위 위원 개선의 건을 상정합니다. 가결되었음을 선포합니다.'),
              C('다음은 의사일정 제2항 청원 심사기간 연장 요구의 건을 상정합니다. 가결되었음을 선포합니다.'),
              M('의사진행발언 하겠습니다.')]
        lab = am.agenda_labels(m, bl)
        self.assertEqual(lab[3], '청원 심사기간 연장 요구의 건')

    def test_range_across_sentences_and_beon(self):
        """2024-09-03 소위: 범위가 두 문장에 걸치고, 넘어가기는 「3번 전파법 일부개정법률안」."""
        m = {'agenda': ['%d. 법안%d 일부개정법률안' % (n, n) for n in range(1, 6)]}
        bl = [C('의사일정 제1항 법안1 일부개정법률안부터 시작하겠습니다. 의사일정 제5항 법안5 일부개정법률안까지 5건을 일괄하여 상정합니다.'),
              M('첫 질문입니다'),
              C('가결되었음을 선포합니다. 3번 법안3 일부개정법률안에 대해서 보고해 주시기 바랍니다.'),
              M('3번 질문입니다')]
        lab = am.agenda_labels(m, bl)
        self.assertEqual(lab[1], '법안1 일부개정법률안 외 4건')
        self.assertEqual(lab[3], '법안3 일부개정법률안')

    def test_resume_by_title_word(self):
        """2019-04-17: 「증인 채택의 건」 뒤 「청문회를 계속하도록 하겠습니다」."""
        m = {'agenda': ['1. KT 화재원인 규명 및 방지대책에 대한 청문회', '2. 증인 채택의 건']}
        bl = [C('의사일정 제1항 KT 화재원인 규명 및 방지대책에 대한 청문회 실시의 건을 상정합니다.'),
              C('그래서 의사일정 제2항 증인 채택의 건을 상정합니다.'),
              M('증인을 더 부르자는 겁니다'),
              C('청문회를 계속하도록 하겠습니다.'),
              M('화재 예방 대책을 묻겠습니다', name='송희경')]
        lab = am.agenda_labels(m, bl)
        self.assertEqual(lab[2], '증인 채택의 건')
        self.assertEqual(lab[4], 'KT 화재원인 규명 및 방지대책에 대한 청문회')

    def test_report_bare_numbers(self):
        """전문위원의 「법안 소위자료 4항～9항」(2026-04-14)·「10항입니다.」(2019-07-25)는 넘어가기, 조문 항(2019-12-04)은 아니다."""
        m = {'agenda': ['%d. 법안%d' % (n, n) for n in range(1, 11)]}
        rep = lambda t: B('이복우', '수석전문위원', t)
        bl = [C('의사일정 제1항부터 제10항까지 일괄 상정합니다.'),
              rep('수석전문위원입니다. 법안 소위자료 4항～9항 스포츠 경기행사에 대한 보편적 시청권을 다룬 내용입니다.'),
              M('보편적 시청권 질문'),
              rep('10항입니다. 자구를 고쳤습니다.'),
              M('10항 질문'),
              rep('맞습니다. 2항·3항·4항은 그대로 둡니다.'),
              M('이어서 질문')]
        lab = am.agenda_labels(m, bl)
        self.assertEqual(lab[2], '법안4 외 5건')
        self.assertEqual(lab[4], '법안10')
        self.assertEqual(lab[6], '법안10')

    def test_missing_head_uses_meeting_label(self):
        """2017-11-21: PDF 원문이 제1·2항 공청회 중간부터 시작 — 첫 상정(제3항) 앞 블록은 회의 전체 꼬리표."""
        m = {'agenda': ['1. 가법안 공청회', '2. 나법안 공청회', '3. 다법안 공청회']}
        bl = [B('최경진', '진술인', '가법안에 대해 진술하겠습니다.'), M('진술인께 묻겠습니다.'),
              C('그러면 의사일정 제3항 다법안 공청회를 상정합니다.'), M('다법안 질문')]
        lab = am.agenda_labels(m, bl)
        self.assertEqual(lab[1], '가법안 공청회 외 2건')
        self.assertEqual(lab[3], '다법안 공청회')

    def test_build_speech_rows_uses_block_label(self):
        m = {'agenda': ['1. 가의 건', '9. 공청회'], 'conf_date': '2025-12-09', 'confer_num': '55942', 'title': 't'}
        bl = [C('의사일정 제1항 가의 건을 상정합니다.'), M('가의 건에 대한 충분히 긴 발언입니다. 계속 말씀드립니다.'),
              C('의사일정 제9항 공청회를 상정합니다.'), M('공청회에서 묻는 충분히 긴 발언입니다. 계속 말씀드립니다.')]
        rows = am.build_speech_rows(m, bl, [1, 3], [], 'u', dry=True)
        self.assertEqual({r['chunk_seq']: r['agenda'] for r in rows}, {1: '가의 건', 3: '공청회'})


if __name__ == '__main__':
    unittest.main()
