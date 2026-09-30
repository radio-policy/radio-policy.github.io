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
        # 통신사 이름은 내용어가 있는 블록에서는 세지 않는다(v4) — 'KT 소액결제 해킹, 대표 사퇴 요구'는 보안
        s = sf.score_text('KT 해킹 사고에 대해 대표 사퇴를 요구합니다')
        self.assertNotIn('통신·전파', s)
        self.assertEqual(sf.decide(s), {'보안·개인정보': 1.0})
        # 이름 0.5점이 '이동통신 1 : 해킹 1' 접전을 통신으로 기울이지 않는다(반분)
        self.assertEqual(sf.decide(sf.score_text('이동통신 이용자들이 SKT 해킹으로 불안해합니다')),
                         {'통신·전파': 0.5, '보안·개인정보': 0.5})
        self.assertEqual(sf.score_text('KT KT KT SKT 요금제 이야기'), {'통신·전파': 1.0})
        # 약신호만 있는 블록은 WEAK_ALONE(=True, 정답 대조로 정함)이면 0.5점, 블록당 분야별 상한 1
        self.assertEqual(sf.score_text('SK텔레콤 대표이사 증인 나와 계십니다'),
                         {'통신·전파': 0.5} if sf.WEAK_ALONE else {})
        self.assertEqual(sf.score_text('KBS MBC EBS 사장님들 나와 계십니까'), {'방송·미디어': 1.0})
        # 방송사·기관 이름은 내용어가 있어도 그대로 센다(통신사 이름만 뺀다)
        self.assertEqual(sf.score_text('KBS 수신료 문제입니다'), {'방송·미디어': 1.5})

    def test_usim_is_security_weak(self):
        # '유심'은 보안 약신호(v4) — 22대 적중의 90%가 유심 해킹 회의였다
        self.assertEqual(sf.score_text('유심 교체 물량이 부족합니다'), {'보안·개인정보': 0.5})
        self.assertEqual(sf.score_text('유심히 살펴보겠습니다'), {})
        self.assertEqual(sf.decide(sf.score_text('SK텔레콤 유심보호서비스 가입자')), {'통신·전파': 0.5, '보안·개인정보': 0.5})

    def test_keyword_holes_v4(self):
        self.assertEqual(sf.score_text('디지털배움터 사업 성과를 말씀해 주시지요'), {'AI·디지털': 1.0})
        self.assertIn('보안·개인정보', sf.score_text('국민 1953만 명의 개인정보가 유출됐다고 확인이 됐고요'))
        self.assertIn('보안·개인정보', sf.score_text('유출된 정보가 얼마나 됩니까'))
        self.assertEqual(sf.score_text('천문학적인 금액으로 중계권을 샀습니다'), {})
        self.assertEqual(sf.score_text('현장 엔지니어의 도메인 지식이 중요합니다'), {})
        self.assertEqual(sf.score_text('불법 도박에 쓰이는 도메인 차단을 강화해야'), {'통신·전파': 1.0})

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

    def test_hearing_item_anywhere_in_agenda(self):
        # v4: 청문회·공청회 자체인 안건이 목록 어디에 있든 잡는다 — 열린국회정보의 안건 순서는 진행 순서가 아니다
        T = '제22대 제416회 제2차 과학기술정보방송통신위원회 (2024년 07월 24일)'
        info = sf.meeting_info({'title': T, 'agenda': ['방송통신위원회 위원장후보자(이진숙) 인사청문요청안',
                                                       '방송통신위원회 위원장후보자(이진숙) 인사청문회', 'o 의사일정 변경의 건']})
        self.assertEqual((info['kind'], info['default'], info['default_weak']), ('인사청문', '방송·미디어', False))
        info = sf.meeting_info({'title': T, 'agenda': ['o 의사일정 변경의 건', '청문회 증인 출석요구 추가의 건',
                                                       '대규모 해킹사고(통신·금융) 관련 청문회']})
        self.assertEqual((info['kind'], info['default'], info['default_weak']), ('청문회', '보안·개인정보', True))
        # '…의 건'으로 끝나는 청문 관련 안건만 있는 날은 일반 회의(v1의 오판을 되살리지 않는다)
        info = sf.meeting_info({'title': T, 'agenda': ['청문회 증인 출석요구의 건', '인사청문회 실시계획서 채택의 건',
                                                       '방송통신위원회 위원장후보자(이진숙) 인사청문요청안', '공청회 개최의 건']})
        self.assertEqual((info['kind'], info['default']), ('전체회의', None))
        # 소위는 공청회 안건이 있어도 소위(안건 흐름을 쓴다)
        info = sf.meeting_info({'title': '제22대 제424회 제1차 과학기술정보방송통신위원회 정보통신방송법안심사소위원회',
                                'agenda': ['공청회 개최의 건', '방송 4법 법률안에 대한 공청회']})
        self.assertEqual(info['kind'], '2소위')

    def test_hearing_default_guards(self):
        T = '제22대 제418회 제16차 과학기술정보방송통신위원회 (2024년 11월 20일)'
        # 법안을 많이 처리한 날은 섞인 날 — 종류는 인사청문, 기본 분야는 없음
        bills = ['방송법 일부개정법률안(의안번호 %d)' % i for i in range(sf.MIXED_DAY_BILLS)]
        info = sf.meeting_info({'title': T, 'agenda': bills + ['한국방송공사 사장후보자(박장범) 인사청문회']})
        self.assertEqual((info['kind'], info['default']), ('인사청문', None))
        # 청문회 제목의 분야가 그날 실제 발언의 절반에 못 미치면 기본 분야를 주지 않는다(2025-04-30 'YTN 등 방송통신 분야 청문회')
        m = {'title': T, 'agenda': ['청문회 증인 출석요구 추가의 건', 'YTN 등 방송통신 분야 청문회']}
        self.assertEqual(sf.meeting_info(m)['default'], '방송·미디어')              # 블록을 안 주면 제목대로
        hack = [B('갑', '위원', '유심 해킹 사고로 가입자 정보가 유출됐습니다. 침해사고 신고는 언제 했습니까?')] * 3
        ytn = [B('을', '위원', 'YTN 민영화 과정에서 방송의 공정성이 훼손됐습니다.')] * 1
        self.assertIsNone(sf.meeting_info(m, hack + ytn)['default'])
        self.assertEqual(sf.meeting_info(m, ytn * 3 + hack[:1])['default'], '방송·미디어')

    def test_chair_formula_out_of_bar(self):
        # v4: 위원장의 진행 공식 블록은 안건 이름의 낱말이 걸려도 막대 밖
        info = {'default': None}
        b1 = B('장', '위원장', '의석을 정돈하여 주시기 바랍니다. 성원이 되었으므로 회의를 개회하겠습니다. 오늘은 인공지능 현안 공청회를 실시하겠습니다.')
        b2 = B('장', '소위원장', '의사일정 제6항 원자력안전위원회의 설치 및 운영에 관한 법률 일부개정법률안을 상정합니다.')
        b3 = B('장', '위원장', '다음으로 한국연구재단 이사장님 나오셔서 인사말씀해 주시기 바랍니다.')
        res = sf.classify_blocks([b1, b2, b3], info)
        self.assertEqual([x['kind'] for x in res], ['chair', 'chair', 'chair'])
        self.assertEqual(res[1]['aw'], {'원자력·우주': 1.0})
        # 위원장의 실질 발언은 종전대로 낱말 판정
        b4 = B('장', '위원장', '방통위 직원들의 답변을 보고 속이 터집니다. 공영방송 이사 선임에 참여했지요? 예, 아니요로 답하십시오.')
        self.assertEqual(sf.classify_blocks([b4], info)[0]['kind'], 'direct')
        # 긴 실질 발언 끝에 발언권 부여 한 번 붙은 것은 빼지 않는다
        long_txt = ('KBS 수신료 분리징수가 공영방송 재원을 흔들고 있고 지상파 재허가 심사도 멈춰 있습니다. ' * 5) + '이주희 위원님 질의하십시오.'
        self.assertEqual(sf.classify_blocks([B('장', '위원장', long_txt)], info)[0]['kind'], 'direct')
        # 위원(의원석)의 같은 말은 공식으로 보지 않는다
        b5 = B('갑', '위원', '의사일정 제6항 원자력안전위원회 설치법 개정안에 대해서 말씀드리겠습니다.')
        self.assertEqual(sf.classify_blocks([b5], info)[0]['kind'], 'direct')

    def test_chair_formula_feeds_subcommittee_agenda(self):
        # 진행 공식 블록은 막대 밖이지만 소위의 '현재 안건 분야'로는 쓴다
        info = sf.meeting_info({'title': '제22대 제418회 제2차 과학기술정보방송통신위원회 과학기술원자력법안심사소위원회', 'agenda': []})
        blocks = [B('장', '소위원장', '의사일정 제6항 원자력안전위원회의 설치 및 운영에 관한 법률 일부개정법률안을 상정합니다.'),
                  B('갑', '위원', '22조 3항은 삭제하는 것이 맞다고 봅니다. 나머지는 수정안대로 가시지요.')]
        res = sf.classify_blocks(blocks, info)
        self.assertEqual([x['kind'] for x in res], ['chair', 'agenda'])
        self.assertEqual(res[1]['w'], {'원자력·우주': 1.0})

    def test_telco_name_only_follows_turn(self):
        info = {'default': None}
        # 같은 턴에 내용어 판정이 있으면 그 분야를 따른다(앞쪽)
        blocks = [B('갑', '위원', '침해사고 신고가 왜 이렇게 늦었습니까? 해킹 사실을 언제 알았습니까?'),
                  B('갑', '위원', '우리나라 기업인 SK텔레콤이나 KT도 똑같은 법의 잣대로 적용한 거지요?'),
                  B('을', '과학기술정보통신부제2차관', '예, KT에도 같은 기준을 적용했습니다. 그렇게 보고드렸습니다.')]
        res = sf.classify_blocks(blocks, info)
        self.assertEqual([x['kind'] for x in res], ['direct', 'inherit', 'inherit'])
        self.assertEqual(res[1]['w'], {'보안·개인정보': 1.0})
        self.assertEqual(res[2]['w'], {'보안·개인정보': 1.0})
        # 뒤쪽에만 있으면 당겨 쓴다
        blocks = [B('갑', '위원', 'KT 김영섭 대표님, 앞으로 나와 주시겠습니까? 몇 가지 확인하겠습니다.'),
                  B('갑', '위원', '유료방송 채널 송출을 중단한 이유가 무엇입니까? 시청자 피해는 어떻게 합니까?')]
        res = sf.classify_blocks(blocks, info)
        self.assertEqual((res[0]['kind'], res[0]['w']), ('inherit', {'방송·미디어': 1.0}))
        # 턴에 내용어 판정이 없으면 종전대로 통신 0.5점
        blocks = [B('갑', '위원', 'SK텔레콤 유영상 대표님께 묻겠습니다. 그날 보고를 받으셨습니까?')]
        res = sf.classify_blocks(blocks, info)
        self.assertEqual((res[0]['kind'], res[0]['w']), ('direct', {'통신·전파': 1.0}))
        # 방송사·기관 이름만 있는 블록은 양보하지 않는다
        blocks = [B('갑', '위원', '단통법 폐지 뒤에 지원금 공시는 어떻게 됩니까? 알뜰폰은요?'),
                  B('갑', '위원', '방통위는 그동안 무엇을 했습니까? 방통위가 답해 보십시오.')]
        res = sf.classify_blocks(blocks, info)
        self.assertEqual((res[1]['kind'], res[1]['w']), ('direct', {'방송·미디어': 1.0}))

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

    def test_member_positions_match(self):
        # 의원석 직위 목록이 세 곳에 있다(분야 집계·대시보드·명부) — 한 곳만 고치면 같은 사람이 곳마다 다르게 갈린다
        # (09-27 '조정위원장직무대행'이 대시보드·분야 집계에만 들어가고 명부 갱신에는 빠져 있었다).
        want = sf.MEMBER_POS | sf.CHAIR_POS
        with open(os.path.join(ROOT, 'app.js'), encoding='utf-8') as fp:
            js = fp.read()
        m = re.search(r"var _MEMBER_POS_SET = \[([^\]]+)\]", js)
        self.assertIsNotNone(m)
        self.assertEqual(set(re.findall(r"'([^']+)'", re.sub(r'//[^\n]*', '', m.group(1)))), want)
        with open(os.path.join(ROOT, 'tools_people_refresh.py'), encoding='utf-8') as fp:
            py = fp.read()
        m = re.search(r"^MEMBER_POS = \{([^}]+)\}", py, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(set(re.findall(r"'([^']+)'", m.group(1))), want)


if __name__ == '__main__':
    unittest.main()
