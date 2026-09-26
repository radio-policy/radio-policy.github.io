# -*- coding: utf-8 -*-
"""speech_fields(#248 과방위 발언 분야 낱말 규칙) 시험 — 네트워크·DB 없음.
  py -3.12 -m unittest tests.test_speech_fields
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import speech_fields as sf  # noqa: E402


def B(name, pos, text):
    return {'name': name, 'pos': pos, 'text': text}


class TestScore(unittest.TestCase):
    def test_strip_false_positives(self):
        # 개회사 '단말기 자료', 퍼뜨린다는 '전파', 예산 '편성', 법안 '심의', 인용 '보도'는 분야 낱말이 아니다
        self.assertEqual(sf.score_text('오늘 보고사항은 단말기 자료를 참고하시기 바랍니다. 그런 이야기가 전파되고 있습니다.'), {})
        self.assertEqual(sf.score_text('예산 편성이 안 됐고 법안 심의도 늦어졌다는 언론 보도가 있습니다'), {})

    def test_self_intro_slogan_stripped(self):
        s = sf.score_text('인공지능 AI 수도 광주 국회의원 정진욱입니다. 우체국 택배 노동자 처우를 묻겠습니다.')
        self.assertNotIn('AI·디지털', s)
        self.assertIn('우정·기타', s)

    def test_compound_first(self):
        s = sf.score_text('해저 케이블 매설 현황을 봅시다')
        self.assertIn('통신·전파', s)
        self.assertNotIn('방송·미디어', s)          # '케이블' 단독은 방송이 아니다
        s = sf.score_text('위성통신 주파수 확보')
        self.assertNotIn('원자력·우주', s)          # 위성통신은 통신(복합어 먼저)

    def test_weak_company_names(self):
        # 사업자명은 0.5점 — 'KT 소액결제 해킹, 대표 사퇴 요구'는 보안(1점이면 동점이 된다, 정본 §2)
        s = sf.score_text('KT 해킹 사고에 대해 대표 사퇴를 요구합니다')
        self.assertEqual(s['통신·전파'], 0.5)
        self.assertEqual(sf.decide(s), {'보안·개인정보': 1.0})
        # 블록당 분야별 상한 1. 약신호만 있는 블록은 WEAK_ALONE(=True, 정답 대조로 정함)이면 0.5점
        self.assertEqual(sf.score_text('KT KT KT SKT 요금제 이야기'), {'통신·전파': 2.0})
        self.assertEqual(sf.score_text('SK텔레콤 대표이사 증인 나와 계십니다'),
                         {'통신·전파': 0.5} if sf.WEAK_ALONE else {})

    def test_partial_match_false_positives(self):
        self.assertEqual(sf.score_text('정보통신망에서 벌어지는 일을 묻겠습니다'), {})     # '통신망' ⊄ '정보통신망'
        self.assertEqual(sf.score_text('유심히 살펴보시기 바랍니다 우위성을 확보해야'), {})     # 유심히·우위성
        self.assertEqual(sf.score_text('보안 프로그램으로 직원들을 들여다봤다는 겁니다'), {})    # 단독 '보안'
        self.assertIn('보안·개인정보', sf.score_text('KT 불법 기지국 펨토셀 문제'))

    def test_ministry_and_committee_names_neutral(self):
        self.assertEqual(sf.score_text('과학기술정보통신부 장관님과 과학기술정보방송통신위원회 위원님들'), {})

    def test_decide_split_and_default(self):
        self.assertEqual(sf.decide({'통신·전파': 2, '보안·개인정보': 2}), {'통신·전파': 0.5, '보안·개인정보': 0.5})
        self.assertEqual(sf.decide({'통신·전파': 2, '보안·개인정보': 2}, default='보안·개인정보'), {'보안·개인정보': 1.0})
        self.assertEqual(sf.decide({'통신·전파': 5, '보안·개인정보': 2}), {'통신·전파': 1.0})


class TestClassify(unittest.TestCase):
    def test_answer_inherits_question(self):
        blocks = [B('갑', '위원', '장관님, 5G 주파수 재할당 대가 산정 기준을 설명해 주십시오.'),
                  B('을', '과학기술정보통신부장관', '예, 연말까지 기준을 정리해서 보고드리겠습니다. 검토 중입니다.')]
        res = sf.classify_blocks(blocks, {'default': None})
        self.assertEqual(res[0]['kind'], 'direct')
        self.assertEqual(res[1]['kind'], 'inherit')
        self.assertEqual(res[1]['w'], {'통신·전파': 1.0})

    def test_long_wordless_block_breaks_chain(self):
        long_txt = '그 문제는 통상 협상에서 다뤄야 할 사안이라고 봅니다. ' * 6        # 150자 이상, 분야 낱말 없음
        blocks = [B('갑', '위원', '알뜰폰 도매대가 인하는 언제 합니까?'),
                  B('갑', '위원', long_txt),
                  B('을', '부총리', '그 부분은 관계부처와 협의하고 있습니다. 조만간 말씀드리겠습니다.')]
        res = sf.classify_blocks(blocks, {'default': None})
        self.assertEqual([x['kind'] for x in res], ['direct', 'unclassified', 'unclassified'])

    def test_long_wordless_sandwich_inherits(self):
        long_txt = '그 부분은 관리가 전혀 안 됐다는 얘기입니다. 퇴사자 관리를 어떻게 했는지 묻고 있습니다. ' * 3
        blocks = [B('갑', '위원', '쿠팡 개인정보 유출 사고 경위를 설명하십시오.'),
                  B('갑', '위원', long_txt),
                  B('갑', '위원', '그러면 해킹 사실을 당국에 신고한 것은 정확히 언제입니까?')]
        res = sf.classify_blocks(blocks, {'default': None})
        self.assertEqual(res[1]['kind'], 'inherit')      # 앞뒤가 같은 분야 → 이어진 주제
        self.assertEqual(res[1]['w'], {'보안·개인정보': 1.0})

    def test_hearing_weak_default(self):
        info = sf.meeting_info({'title': '제22대 제425회 제1차 과학기술정보방송통신위원회', 'agenda': ['1. SK텔레콤 해킹 관련 청문회']})
        self.assertEqual((info['kind'], info['default'], info['default_weak']), ('청문회', '보안·개인정보', True))
        # 약한 기본값은 분야 낱말이 하나도 없는 공방 턴을 흡수하지 않는다
        blocks = [B('갑', '위원', '위원장님, 지금 제 질의 시간인데 왜 끊으십니까? 이게 말이 됩니까?')]
        self.assertIn(sf.classify_blocks(blocks, info)[0]['kind'], ('offtopic', 'proc'))

    def test_offtopic_turn_out_of_bar(self):
        blocks = [B('갑', '위원', '위원장님, 지금 제 질의 시간인데 왜 끊으십니까? 이게 말이 됩니까?'),
                  B('을', '위원', '지금 뭐 하시는 겁니까, 자리로 돌아가세요. 이렇게 하면 안 됩니다.')]
        res = sf.classify_blocks(blocks, {'default': None})
        self.assertTrue(all(x['kind'] in ('offtopic', 'proc') for x in res))

    def test_chair_only_by_words(self):
        blocks = [B('장', '위원장', '다음은 이어서 질의하실 위원님 순서입니다. 모두 준비해 주시기 바랍니다.')]
        res = sf.classify_blocks(blocks, {'default': '방송·미디어'})
        self.assertEqual(res[0]['kind'], 'chair')     # 기본 분야가 있어도 위원장 무낱말 발언은 막대 밖

    def test_meeting_default(self):
        info = sf.meeting_info({'is_audit': True, 'title': 'x', 'audit_nm': '원자력안전위원회·한국원자력안전기술원·한국원자력통제기술원'})
        self.assertEqual(info['default'], '원자력·우주')
        info = sf.meeting_info({'is_audit': True, 'title': 'x', 'audit_nm': '과학기술정보통신부·우주항공청'})
        self.assertIsNone(info['default'])
        info = sf.meeting_info({'is_audit': True, 'title': 'x', 'audit_nm': '한국방송공사·한국교육방송공사·방송문화진흥회'})
        self.assertEqual(info['default'], '방송·미디어')

    def test_aggregate_rows(self):
        m = {'confer_num': 'x1', 'conf_date': '2025-01-01', 'title': 't', 'agenda': []}
        blocks = [B('홍길동 위원', '위원', '해킹 사고 재발 방지책을 내놓으십시오. 정보보호 투자는 얼마입니까?'),
                  B('김철수', '과학기술정보통신부장관', '예, 투자 계획을 따로 보고드리겠습니다. 준비 중입니다.')]
        rows = sf.build_rows(m, blocks, '뷰어')
        self.assertEqual({r['speaker'] for r in rows}, {'홍길동', '김철수'})   # normalize_speaker(#164) 경유
        self.assertEqual({r['speaker']: r['fields'] for r in rows}['김철수'], {'보안·개인정보': 1.0})
        self.assertTrue(all(r['rules_version'] == sf.RULES_VERSION for r in rows))
        self.assertEqual(len({tuple(sorted(r)) for r in rows}), 1)   # 칸 구성이 같아야 한 번에 insert(#222)


class TestDashboardSync(unittest.TestCase):
    def test_fields_match_app_js(self):
        with open(os.path.join(ROOT, 'app.js'), encoding='utf-8') as fp:
            js = fp.read()
        m = re.search(r"var SPEECH_FIELDS = \[([^\]]+)\]", js)
        self.assertIsNotNone(m)
        self.assertEqual(re.findall(r"'([^']+)'", m.group(1)), sf.FIELDS)
        with open(os.path.join(ROOT, 'styles.css'), encoding='utf-8') as fp:
            css = fp.read()
        for i in range(1, len(sf.FIELDS) + 1):
            self.assertIn('--sf-%d:' % i, css)


if __name__ == '__main__':
    unittest.main()
