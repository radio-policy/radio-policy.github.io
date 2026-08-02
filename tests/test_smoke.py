# -*- coding: utf-8 -*-
"""
스모크 테스트 (개선⑪) — 표준 라이브러리 unittest만 사용, 네트워크·DB 접근 없음.

실행:
  C:\\Users\\SKTelecom\\AppData\\Local\\Programs\\Python\\Python312\\python.exe -m unittest discover -s tests -v

순수 로직만 검증한다. 무거운 모듈(crawler·morning_briefing·assembly_crawler 등)은
import 시 Supabase 클라이언트를 '생성'하지만 네트워크 호출은 없다 — 그래도 실 자격증명에
의존하지 않도록 아래에서 더미 환경변수를 선점한다(각 모듈의 load_dotenv는 기존 env를
덮어쓰지 않으므로 더미가 유지된다).
"""

import os
import sys
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

# 저장소 루트를 import 경로에 추가 (tests/ 하위에서 discover 실행 대비)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 실 DB·API 자격증명 없이도 import 가능하도록 더미 선점 (클라이언트 생성만 되고 접속 없음)
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')


class TestLawWatchNormName(unittest.TestCase):
    """① law_watch.norm_name — 가운뎃점 이형 통일 + 공백 정리"""

    def test_norm_name(self):
        import law_watch
        self.assertEqual(law_watch.norm_name('방송통신발전기금 운용ㆍ관리규정'),
                         '방송통신발전기금 운용·관리규정')
        self.assertEqual(law_watch.norm_name('전파법  시행령\t별표'), '전파법 시행령 별표')
        self.assertEqual(law_watch.norm_name('  운용‧관리•규정  '), '운용·관리·규정')


class TestLawDiffArticles(unittest.TestCase):
    """② law_diff_gen.diff_articles — 조문 3분류(modified/added/deleted)"""

    def test_three_way_classification(self):
        import law_diff_gen
        base = {
            '1조': {'article_no': '제1조(목적)', 'text': '제1조(목적) 이 법은 전파의 이용을 정한다.'},
            '2조': {'article_no': '제2조(정의)', 'text': '제2조(정의) 기존 정의 문안.'},
            '3조': {'article_no': '제3조(적용)', 'text': '제3조(적용) 삭제될 조문.'},
            '4조': {'article_no': '제4조', 'text': '제4조 공백만  다른 조문.'},
        }
        new = {
            '1조': {'article_no': '제1조(목적)', 'text': '제1조(목적) 이 법은 전파의 이용을 정한다.'},
            '2조': {'article_no': '제2조(정의)', 'text': '제2조(정의) 개정된 정의 문안.'},
            '4조': {'article_no': '제4조', 'text': '제4조 공백만 다른  조문.'},   # 공백 차이 → 무변경
            '5조': {'article_no': '제5조(신설)', 'text': '제5조(신설) 새로 들어온 조문.'},
            '6조': {'article_no': '제6조', 'text': '제6조 삭제'},               # 새 판의 삭제 표식
        }
        changes = law_diff_gen.diff_articles(base, new)
        by_key = {c['key']: c for c in changes}
        self.assertEqual(set(by_key), {'2조', '3조', '5조', '6조'})
        self.assertEqual(by_key['2조']['change'], 'modified')
        self.assertEqual(by_key['3조']['change'], 'deleted')
        self.assertEqual(by_key['3조']['after'], '')
        self.assertEqual(by_key['5조']['change'], 'added')
        self.assertEqual(by_key['5조']['before'], '')
        self.assertEqual(by_key['6조']['change'], 'deleted')
        # 정렬(_key_sort)이 조번호 숫자순인지
        self.assertEqual([c['key'] for c in changes], ['2조', '3조', '5조', '6조'])


class TestPressChunking(unittest.TestCase):
    """③ press_ingest._chunk_text — 700자 무겹침 분할·이어붙임 복원 왕복"""

    def test_round_trip_no_overlap(self):
        from press_ingest import _chunk_text, CHUNK_SIZE
        self.assertEqual(CHUNK_SIZE, 700)
        lines = ['%03d번째 줄 — 보도자료 본문 테스트 %s' % (i, '가' * (i % 40)) for i in range(120)]
        text = '\n'.join(lines)
        chunks = _chunk_text(text)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c), CHUNK_SIZE)
        # 무겹침·무손실: 이어붙이면 원문 복원 (대시보드가 청크를 이어붙여 원문 복원하는 전제)
        self.assertEqual(''.join(chunks), text)

    def test_short_text_single_chunk(self):
        from press_ingest import _chunk_text
        self.assertEqual(_chunk_text('짧은 본문'), ['짧은 본문'])


class TestCrawlerKeywordMatching(unittest.TestCase):
    """④ crawler 키워드 매칭 — '전파간섭' 매치, '이혼신고' 비매치 (지침: '혼신' 금지)"""

    def test_keyword_match(self):
        import crawler
        matched = any(k in '해상 전파간섭 신고 급증' for k in crawler.RADIO_KEYWORDS)
        self.assertTrue(matched)
        false_positive = any(k in '이혼신고 절차 간소화 추진' for k in crawler.RADIO_KEYWORDS)
        self.assertFalse(false_positive)
        # '이혼신고' 오탐의 원인이던 '혼신'은 키워드로 두지 않는다 (지침 가드레일)
        self.assertNotIn('혼신', crawler.RADIO_KEYWORDS)
        self.assertNotIn('혼신', crawler.NEWS_SEARCH_KEYWORDS)


class TestNotifySplit(unittest.TestCase):
    """⑤ notify 분할 로직 — 4096 초과 텍스트의 조각 수·무손실 + env 미설정 False"""

    def test_split_long_text(self):
        import notify
        text = '\n'.join('line %03d ' % i + 'x' * 90 for i in range(60))  # 약 6,000자
        self.assertGreater(len(text), 4096)
        chunks = notify.split_message(text)
        self.assertGreaterEqual(len(chunks), 2)
        for c in chunks:
            self.assertLessEqual(len(c), notify.SPLIT_LIMIT)
        self.assertEqual('\n'.join(chunks), text)   # 개행 경계 분할 → 무손실

    def test_split_short_and_empty(self):
        import notify
        self.assertEqual(notify.split_message('짧은 알림'), ['짧은 알림'])
        self.assertEqual(notify.split_message(''), [])

    def test_send_without_env_returns_false(self):
        import notify
        with mock.patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '', 'TELEGRAM_CHAT_ID': ''}):
            self.assertFalse(notify.send_telegram('테스트'))   # 네트워크 접근 전에 False


class TestMorningBriefingAssemblySection(unittest.TestCase):
    """⑥ morning_briefing._format_assembly_section — 국회 법안 동향 섹션 포맷"""

    def test_format(self):
        import morning_briefing as mb
        today = datetime.now(mb.KST).date()
        nd = (today + timedelta(days=3)).strftime('%Y-%m-%d')
        items = {
            'new': [{'bill_name': '전파법 일부개정법률안', 'proposer': '홍길동의원 등 10인'}],
            'changed': [{'bill_name': '전기통신사업법 일부개정법률안',
                         'prev_proc_result': '접수', 'proc_result': '소관위 심사중'}],
            'deadline': [{'bill_name': '정보통신망법 일부개정법률안',
                          'notice_end_dt': nd, 'notice_url': 'https://pal.assembly.go.kr/x'}],
        }
        out = mb._format_assembly_section(items)
        lines = out.split('\n')
        self.assertEqual(lines[0], '🏛️ [국회 법안 동향]')
        self.assertIn('• [신규 발의] 전파법 일부개정법률안 — 홍길동의원 등 10인', lines)
        self.assertIn('• [처리 변경] 전기통신사업법 일부개정법률안: 접수 → 소관위 심사중', lines)
        self.assertIn('• [의견등록 마감 임박] 정보통신망법 일부개정법률안 ~%s (D-3)' % nd[5:], lines)
        self.assertIn('  🔗 https://pal.assembly.go.kr/x', lines)


class TestProposedLawName(unittest.TestCase):
    """⑦ law_diff_gen._proposed_law_name — 예고 제목에서 법령명 추출"""

    def test_extract(self):
        import law_diff_gen
        self.assertEqual(
            law_diff_gen._proposed_law_name(
                '(과기정통부 공고 제2026-780호) 전파법 시행규칙 일부개정령안 입법예고'),
            '전파법 시행규칙')
        self.assertEqual(
            law_diff_gen._proposed_law_name('전기통신사업법 일부개정법률안 입법예고'),
            '전기통신사업법')

    def test_no_match(self):
        import law_diff_gen
        self.assertIsNone(law_diff_gen._proposed_law_name('2026년 주파수 공급 계획 발표'))
        self.assertIsNone(law_diff_gen._proposed_law_name(''))
        self.assertIsNone(law_diff_gen._proposed_law_name(None))


class TestDaysToDeadline(unittest.TestCase):
    """⑧ assembly_crawler._days_to_deadline — 잔여 일수 계산·실패 시 None"""

    def test_days(self):
        from assembly_crawler import _days_to_deadline
        today = date(2026, 8, 2)
        self.assertEqual(_days_to_deadline('2026-08-05', today), 3)
        self.assertEqual(_days_to_deadline('2026-08-02', today), 0)
        self.assertEqual(_days_to_deadline('2026-07-30', today), -3)

    def test_invalid(self):
        from assembly_crawler import _days_to_deadline
        today = date(2026, 8, 2)
        self.assertIsNone(_days_to_deadline('20260805', today))
        self.assertIsNone(_days_to_deadline('', today))
        self.assertIsNone(_days_to_deadline(None, today))


class TestEmbedUtilValidation(unittest.TestCase):
    """⑨ embed_util 입력 검증 — 네트워크 없이 도달 가능한 부분만"""

    def test_empty_list_returns_empty(self):
        import embed_util
        self.assertEqual(embed_util.get_embeddings([]), [])   # 키 검사·네트워크 전에 반환

    def test_invalid_inputs_raise(self):
        import embed_util
        with self.assertRaises(ValueError):
            embed_util.get_embeddings('문자열 하나')            # 리스트가 아님
        with self.assertRaises(ValueError):
            embed_util.get_embeddings(None)
        with self.assertRaises(ValueError):
            embed_util.get_embeddings(['정상', 123])           # 비문자열 원소

    def test_missing_api_key_raises(self):
        import embed_util
        with mock.patch.dict(os.environ, {'VOYAGE_API_KEY': ''}):
            with self.assertRaises(RuntimeError):
                embed_util.get_embeddings(['텍스트'])          # 네트워크 접근 전에 실패


class TestSbClientHttp11(unittest.TestCase):
    """⑩ sb_client.make_client — HTTP/1.1 강제(HTTP/2 미사용) + 재시도 transport 확인"""

    def test_transport_forces_http11(self):
        import httpx
        import sb_client
        captured = {}

        def fake_create_client(url, key, options=None):
            captured['options'] = options
            return object()

        with mock.patch.object(sb_client, 'create_client', fake_create_client):
            sb_client.make_client('http://localhost', 'test-key')

        http_client = captured['options'].httpx_client
        self.assertIsInstance(http_client, httpx.Client)
        transport = http_client._transport
        # HTTPTransport 기본 http2=False → HTTP/1.1 (Server disconnected 버그 회피의 핵심)
        self.assertIsInstance(transport, httpx.HTTPTransport)
        pool = getattr(transport, '_pool', None)
        self.assertIsNotNone(pool)
        self.assertFalse(getattr(pool, '_http2', False))      # HTTP/2 미사용
        self.assertEqual(getattr(pool, '_retries', 3), 3)     # 재시도 3회


if __name__ == '__main__':
    unittest.main()
