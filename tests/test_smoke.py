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
        self.assertIn('• [의견등록 ~%s (D-3)] 정보통신망법 일부개정법률안' % nd[5:], lines)
        self.assertIn('  🔗 https://pal.assembly.go.kr/x', lines)

    def test_changed_cap_and_noise_filter(self):
        # 2026-09-04 06:00 브리핑에 백필 442건이 쏟아진 사고(#122-보론): '소관위 회부' 전이는 빼고, 상한을 넘으면 접는다
        import morning_briefing as mb
        changed = [{'bill_name': f'법안{i}', 'prev_proc_result': '접수', 'proc_result': '소관위 심사중'} for i in range(30)]
        changed += [{'bill_name': '잡음', 'prev_proc_result': '접수', 'proc_result': '소관위 회부'}]
        out = mb._format_assembly_section({'new': [], 'changed': changed, 'deadline': []})
        lines = out.split('\n')
        shown = [l for l in lines if l.startswith('• [처리 변경]')]
        self.assertEqual(len(shown), mb.CHANGED_MAX_LINES)
        self.assertNotIn('• [처리 변경] 잡음: 접수 → 소관위 회부', lines)
        self.assertIn(f'  … 처리 변경 외 {30 - mb.CHANGED_MAX_LINES}건 (대시보드 국회 법안 탭)', lines)


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


class TestMinutesDigest(unittest.TestCase):
    """⑪ subscriber_notify.format_minutes_digest — 과방위 회의록 다이제스트 순수 포맷터

    검증 축: 이스케이프, 그룹 순서·줄 배분(10줄 상한), SKT 칩, 예산(3500 절단 회피·태그 무손상),
    발송 측 mergeQueueBlocks 오병합 방지(`N. ` 줄 금지).
    """

    URL = 'https://record.assembly.go.kr/assembly/viewer/minutes/xml.do?id=56569&type=view'
    TITLE = '제3차 (전기통신사업법 <개정> & 방송법)'
    SUMMARY = '주파수 공급 & 요금 인하를 놓고 여야 질의 집중'

    @staticmethod
    def _rows():
        rows = []
        seq = 0
        # 주파수 6건 (그중 1건은 SKT 칩 동반), 요금 4건, AI 2건 — chunk_seq는 서로 섞어 넣는다
        spec = [('주파수', 6), ('요금', 4), ('AI', 2)]
        pools = {t: n for t, n in spec}
        while any(pools.values()):
            for t, _ in spec:
                if pools[t] <= 0:
                    continue
                seq += 1
                pools[t] -= 1
                topic = t
                speaker = f'{t}위원{seq}'
                if t == '주파수' and pools[t] == 3:      # 주파수 3번째 행에 칩 부착
                    topic = '주파수, SK텔레콤 언급'
                    speaker = '칩위원'
                rows.append({'speaker': speaker,
                             'position': '위원' if seq % 2 else None,
                             'topic': topic,
                             'summary': f'{t} 관련 발언 요지 {seq} & 근거 설명',
                             'chunk_seq': seq})
        # 요지 없는 행은 무시되어야 한다
        rows.append({'speaker': '무요지', 'position': None, 'topic': '주파수',
                     'summary': None, 'chunk_seq': 99})
        return rows

    def _digest(self, **kw):
        from subscriber_notify import format_minutes_digest
        args = dict(meeting_date='2026-04-28', title=self.TITLE, summary=self.SUMMARY,
                    sp_rows=self._rows(), url=self.URL)
        args.update(kw)
        return format_minutes_digest(**args)

    @staticmethod
    def _bullets(out):
        return [ln for ln in out.split('\n') if ln.startswith('· ')]

    @staticmethod
    def _headings(out):
        return [ln for ln in out.split('\n')[1:] if ln.startswith('<b>')]

    def test_header_and_escaping(self):
        out = self._digest()
        self.assertTrue(out.startswith('🏛️ <b>과방위 회의록 · 4/28 '))
        first = out.split('\n')[0]
        self.assertIn('&amp; 방송법', first)
        self.assertIn('&lt;개정&gt;', first)
        self.assertNotIn('<개정>', first)
        self.assertIn('주파수 공급 &amp; 요금 인하를 놓고 여야 질의 집중', out.split('\n')[1])

    def test_line_allocation_and_groups(self):
        from subscriber_notify import DASHBOARD_URL
        out = self._digest()
        bullets = self._bullets(out)
        self.assertEqual(len(bullets), 10)               # 기본 max_lines
        self.assertIn('… 외 2건', out)                    # 유효 12건 − 표시 10건
        heads = self._headings(out)
        self.assertEqual(heads[0], '<b>주파수</b>')       # 최다 그룹이 먼저
        self.assertEqual(heads, ['<b>주파수</b>', '<b>요금</b>', '<b>AI</b>'])
        for h in heads:
            self.assertRegex(h, r'^<b>[^<>]+</b>$')
        # 그룹 안 정렬은 chunk_seq 순
        seqs = [int(ln.rsplit('요지 ', 1)[1].split(' ')[0]) for ln in bullets[:6]]
        self.assertEqual(seqs, sorted(seqs))
        # 링크
        self.assertIn(f'<a href="{self.URL.replace("&", "&amp;")}">원문</a>', out)
        self.assertIn('&amp;type=view', out)
        self.assertIn(DASHBOARD_URL, out)
        # 발송 측 병합 규칙에 걸리는 `N. ` 줄이 없어야 한다
        for ln in out.split('\n'):
            self.assertNotRegex(ln, r'^\d+\.\s')
        self.assertLess(len(out), 2600)

    def test_skt_chip_row_and_flag(self):
        out = self._digest()
        chip_lines = [ln for ln in self._bullets(out) if ln.startswith('· 칩위원')]
        self.assertEqual(len(chip_lines), 1)
        self.assertTrue(chip_lines[0].endswith(' (SK텔레콤 언급)'))
        # 다른 줄엔 칩이 붙지 않는다
        others = [ln for ln in self._bullets(out) if not ln.startswith('· 칩위원')]
        self.assertTrue(all(not ln.endswith(' (SK텔레콤 언급)') for ln in others))
        # 직위 None인 행은 이름 뒤에 공백 없이 콜론
        self.assertTrue(any(': ' in ln and ' 위원:' not in ln for ln in others))

        flagged = self._digest(skt_flag=True)
        line2 = flagged.split('\n')[1]
        self.assertTrue(line2.endswith(' (SK텔레콤 언급)'))
        self.assertEqual(line2.count('SK텔레콤 언급'), 1)
        # 요약이 이미 칩을 달고 있으면 중복 부착 없음
        already = self._digest(skt_flag=True, summary=self.SUMMARY + ' (SK텔레콤 언급)')
        self.assertEqual(already.split('\n')[1].count('SK텔레콤 언급'), 1)

    def test_max_lines_three(self):
        out = self._digest(max_lines=3)
        self.assertEqual(len(self._bullets(out)), 3)          # 그룹당 1줄씩
        self.assertIn('… 외 9건', out)
        self.assertEqual(self._headings(out), ['<b>주파수</b>', '<b>요금</b>', '<b>AI</b>'])

    def test_tiny_budget_keeps_footer_and_tags_intact(self):
        out = self._digest(budget=300)
        self.assertIsInstance(out, str)
        self.assertTrue(out.endswith('">대시보드</a>'))
        self.assertEqual(out.count('<a '), out.count('</a>'))
        self.assertEqual(out.count('<b>'), out.count('</b>'))
        self.assertIn('… 외 ', out)
        self.assertLess(len(self._bullets(out)), 10)
        # 빈 그룹 제목이 남아 있으면 안 된다
        lines = out.split('\n')
        for i, ln in enumerate(lines):
            if ln.startswith('<b>') and i > 0:
                self.assertTrue(lines[i + 1].startswith('· '), f'빈 그룹 제목: {ln}')

    def test_long_summary_trimmed(self):
        from subscriber_notify import MINUTES_LINE_CHARS
        rows = [{'speaker': '장문', 'position': None, 'topic': '주파수',
                 'summary': '가' * (MINUTES_LINE_CHARS + 50), 'chunk_seq': 1}]
        out = self._digest(sp_rows=rows)
        ln = self._bullets(out)[0]
        self.assertTrue(ln.endswith('…'))
        self.assertEqual(ln, '· 장문: ' + '가' * MINUTES_LINE_CHARS + '…')
        self.assertNotIn('… 외', out)                         # 전부 표시 → 외 N건 없음

    def test_date_fallback_and_no_topic(self):
        rows = [{'speaker': '무주제', 'position': '', 'topic': None,
                 'summary': '주제 없는 발언', 'chunk_seq': None}]
        out = self._digest(meeting_date='4월말', sp_rows=rows)
        self.assertTrue(out.startswith('🏛️ <b>과방위 회의록 · 4월말 '))
        self.assertIn('<b>기타</b>', out)
        self.assertIn('· 무주제: 주제 없는 발언', out)

    def test_empty_returns_blank(self):
        self.assertEqual(self._digest(summary='', sp_rows=[]), '')
        self.assertEqual(self._digest(summary=None, sp_rows=None), '')
        # 요지 없는 행뿐이면 역시 ''
        self.assertEqual(self._digest(summary='', sp_rows=[{'speaker': 'x', 'summary': ''}]), '')


class TestBillStage(unittest.TestCase):
    """bill_stage — 진행단계 파생(2026-09-04, #122). PROC_RESULT가 빈 계류 법안을 회부·상정·
    위원회 의결·법사위로 구분한다. 자문 근거와는 무관(법안은 동향 전용)."""

    def test_ladder(self):
        import bill_stage as bs
        self.assertEqual(bs.derive_stage({}), '접수')
        self.assertEqual(bs.derive_stage({'COMMITTEE_DT': '2026-01-01'}), '소관위 회부')
        self.assertEqual(bs.derive_stage({'COMMITTEE_DT': '2026-01-01', 'CMT_PRESENT_DT': '2026-01-10'}), '소관위 심사중')
        self.assertEqual(bs.derive_stage({'CMT_PRESENT_DT': '2026-01-10', 'LAW_SUBMIT_DT': '2026-02-01'}), '법사위 회부')
        self.assertEqual(bs.derive_stage({'LAW_SUBMIT_DT': '2026-02-01', 'LAW_PRESENT_DT': '2026-02-10'}), '법사위 심사중')

    def test_committee_result_branches(self):
        import bill_stage as bs
        # 위원회 가결은 종결이 아니라 본회의 대기 — '위원회 의결'
        self.assertEqual(bs.derive_stage({'CMT_PRESENT_DT': '2026-01-10', 'CMT_PROC_RESULT_CD': '수정가결'}), '위원회 의결')
        # 위원회 단계 폐기는 그 값으로 종결
        self.assertEqual(bs.derive_stage({'CMT_PRESENT_DT': '2026-01-10', 'CMT_PROC_RESULT_CD': '대안반영폐기'}), '대안반영폐기')
        # 본회의 처리결과(PROC_RESULT)가 있으면 항상 우선
        self.assertEqual(bs.derive_stage({'PROC_RESULT': '원안가결', 'CMT_PROC_RESULT_CD': '수정가결'}), '원안가결')
        self.assertEqual(bs.derive_stage({'PROC_RESULT': ' 철회 ', 'LAW_PRESENT_DT': '2026-02-10'}), '철회')

    def test_terminal_whitelist_and_columns(self):
        import bill_stage as bs
        for alive in ('접수', '소관위 회부', '소관위 심사중', '위원회 의결', '법사위 회부', '법사위 심사중'):
            self.assertFalse(bs.is_terminal_label(alive), alive)
        for dead in ('수정가결', '원안가결', '대안반영폐기', '철회', '부결', '', None, '미래의결과코드'):
            self.assertTrue(bs.is_terminal_label(dead), dead)
        cols = bs.stage_columns({'COMMITTEE_DT': '2026-01-01', 'CMT_PRESENT_DT': '', 'LAW_SUBMIT_DT': None})
        self.assertEqual(cols['committee_dt'], '2026-01-01')
        self.assertIsNone(cols['cmt_present_dt']); self.assertIsNone(cols['law_submit_dt'])
        self.assertEqual(set(cols), set(bs.STAGE_FIELDS))


if __name__ == '__main__':
    unittest.main()
