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
import re
import sys
import unittest

SKT_CHIP_TXT = 'SK텔레콤 언급'
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

    def test_derive_chunk_dates(self):
        """③-2 발표일 유도(#155-보론2) — 헤더는 첫 조각에만, 뒤 조각은 이어받고, 프리앰블은 비움"""
        from press_ingest import derive_chunk_dates, ymd6_to_ymd8
        self.assertEqual(ymd6_to_ymd8('260324'), '20260324')
        self.assertEqual(ymd6_to_ymd8('2603'), '')
        chunks = [
            (0, '# 과기정통부 보도자료 2026\n프리앰블'),
            (1, '## 260310 첫 자료\n본문 1'),
            (2, '본문 1 이어짐\n\n(원문: http://a)\n\n## 260324 둘째 자료\n\n본문 2'),
            (3, '본문 2 이어짐'),
            (4, '본문 2 끝 (원문: http://b)'),
        ]
        self.assertEqual(derive_chunk_dates(chunks),
                         {1: '20260310', 2: '20260324', 3: '20260324', 4: '20260324'})
        # 순서가 섞여 들어와도 chunk_index 순으로 판단
        self.assertEqual(derive_chunk_dates(list(reversed(chunks)))[3], '20260324')


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
    _RE_NAME_ONLY = re.compile(r'^· <b>[^<>]+</b>$')      # 직위 없는 발언자 줄

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
        """발언자 줄(2026-09-22 개편: 발언자 줄과 요지 줄이 분리됐다)."""
        return [ln for ln in out.split('\n') if ln.startswith('· ')]

    @staticmethod
    def _bodies(out):
        lines = out.split('\n')
        return [lines[i + 1] for i, ln in enumerate(lines) if ln.startswith('· ')]

    @staticmethod
    def _headings(out):
        return [ln for ln in out.split('\n') if ln.startswith('🔹 ')]

    def test_header_and_escaping(self):
        out = self._digest()
        lines = out.split('\n')
        # 회의명과 안건은 서로 다른 줄 — 굵은 첫 줄이 길어지지 않게(2026-09-22)
        self.assertEqual(lines[0], '🏛️ <b>과방위 회의록 · 4/28 제3차</b>')
        self.assertEqual(lines[1], '<i>전기통신사업법 &lt;개정&gt; &amp; 방송법</i>')
        self.assertNotIn('<개정>', out)
        self.assertEqual(lines[2],
                         '<blockquote>주파수 공급 &amp; 요금 인하를 놓고 여야 질의 집중</blockquote>')

    def test_line_allocation_and_groups(self):
        from subscriber_notify import DASHBOARD_URL
        out = self._digest()
        bullets = self._bullets(out)
        self.assertEqual(len(bullets), 10)               # 기본 max_lines
        self.assertIn('… 외 2건', out)                    # 유효 12건 − 표시 10건
        heads = self._headings(out)
        # 최다 그룹이 먼저. 소제목에 그룹 전체 건수를 단다. 'AI'는 '인공지능'으로 합친다(_GROUP_ALIAS)
        self.assertEqual(heads, ['🔹 <b>주파수</b> <i>6건</i>', '🔹 <b>요금</b> <i>4건</i>',
                                 '🔹 <b>인공지능</b> <i>2건</i>'])
        # 그룹 안 정렬은 chunk_seq 순
        seqs = [int(ln.rsplit('요지 ', 1)[1].split(' ')[0]) for ln in self._bodies(out)[:6]]
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
        chip_lines = [ln for ln in self._bullets(out) if '칩위원' in ln]
        self.assertEqual(len(chip_lines), 1)
        self.assertTrue(chip_lines[0].startswith('· 🔶 <b>칩위원</b>'))   # 표식이 줄머리에
        self.assertIn(SKT_CHIP_TXT, chip_lines[0])
        # 다른 줄엔 칩이 붙지 않는다
        others = [ln for ln in self._bullets(out) if '칩위원' not in ln]
        self.assertTrue(all(SKT_CHIP_TXT not in ln and '🔶' not in ln for ln in others))
        # 직위 None인 행은 이름만
        self.assertTrue(any(self._RE_NAME_ONLY.match(ln) for ln in others))

        flagged = self._digest(skt_flag=True)
        line3 = flagged.split('\n')[2]
        self.assertTrue(line3.endswith(f' ({SKT_CHIP_TXT})</blockquote>'))
        self.assertEqual(line3.count(SKT_CHIP_TXT), 1)
        # 요약이 이미 칩을 달고 있으면 중복 부착 없음
        already = self._digest(skt_flag=True, summary=self.SUMMARY + f' ({SKT_CHIP_TXT})')
        self.assertEqual(already.split('\n')[2].count(SKT_CHIP_TXT), 1)

    def test_max_lines_three(self):
        out = self._digest(max_lines=3)
        self.assertEqual(len(self._bullets(out)), 3)          # 그룹당 1줄씩
        self.assertIn('… 외 9건', out)
        self.assertEqual(self._headings(out), ['🔹 <b>주파수</b> <i>6건</i>',
                                               '🔹 <b>요금</b> <i>4건</i>',
                                               '🔹 <b>인공지능</b> <i>2건</i>'])

    def test_tiny_budget_keeps_footer_and_tags_intact(self):
        out = self._digest(budget=300)
        self.assertIsInstance(out, str)
        self.assertTrue(out.endswith('">대시보드</a>'))
        self.assertEqual(out.count('<a '), out.count('</a>'))
        self.assertEqual(out.count('<b>'), out.count('</b>'))
        self.assertIn('… 외 ', out)
        self.assertLess(len(self._bullets(out)), 10)
        # 빈 그룹 제목이 남아 있으면 안 된다 — 소제목 바로 다음 줄은 발언자 줄이어야 한다
        lines = out.split('\n')
        for i, ln in enumerate(lines):
            if ln.startswith('🔹 '):
                self.assertTrue(lines[i + 1].startswith('· '), f'빈 그룹 제목: {ln}')

    def test_long_summary_trimmed(self):
        from subscriber_notify import MINUTES_LINE_CHARS
        rows = [{'speaker': '장문', 'position': None, 'topic': '주파수',
                 'summary': '가' * (MINUTES_LINE_CHARS + 50), 'chunk_seq': 1}]
        out = self._digest(sp_rows=rows)
        self.assertEqual(self._bullets(out)[0], '· <b>장문</b>')
        self.assertEqual(self._bodies(out)[0],
                         '<blockquote>' + '가' * MINUTES_LINE_CHARS + '…</blockquote>')
        self.assertNotIn('… 외', out)                         # 전부 표시 → 외 N건 없음

    def test_date_fallback_and_no_topic(self):
        rows = [{'speaker': '무주제', 'position': '', 'topic': None,
                 'summary': '주제 없는 발언', 'chunk_seq': None}]
        out = self._digest(meeting_date='4월말', sp_rows=rows)
        self.assertTrue(out.startswith('🏛️ <b>과방위 회의록 · 4월말 '))
        self.assertIn('🔹 <b>기타</b> <i>1건</i>', out)
        self.assertIn('· <b>무주제</b>\n<blockquote>주제 없는 발언</blockquote>', out)

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


class TestLawmapEdgeCheck(unittest.TestCase):
    """lawmap_edge_check — 주제 엣지 설명의 근거 조문 판정(순수 함수, 네트워크 없음). 배경역사 #123"""

    def test_art_key_and_names(self):
        import lawmap_edge_check as m
        self.assertEqual(m.art_key('제19조(신고를 통한 무선국 개설 등)'), '19조')
        self.assertEqual(m.art_key('19조의2(무선국)'), '19조의2')
        self.assertEqual(m.base_of('전파법(법률)(제21553호)(20260421).pdf'), '전파법')
        self.assertEqual(m.base_of('(과학기술정보통신부) 방송통신발전기금 운용·관리규정(과학기술정보통신부고시)(제2022-2호).pdf'),
                         '방송통신발전기금운용관리규정')
        self.assertEqual(m.nrm('표시ㆍ광고의 공정화에 관한 법률'), m.nrm('표시·광고의 공정화에 관한 법률'))

    def test_own_articles_vs_cross_reference(self):
        import lawmap_edge_check as m
        own, cross = m.own_articles('청문(제22조①3호가)·사전 통지(제21조) — 선정취소(전파법 제15조의2)에 적용', '행정절차법')
        self.assertEqual(own, ['22조', '21조']); self.assertEqual(cross, 1)
        self.assertEqual(m.own_articles('전파법 제9조 주파수분배', '전파법'), (['9조'], 0))
        self.assertEqual(m.own_articles('법 제41조제2항 위임', '전기통신설비의 공동사용 등의 기준'), ([], 1))
        # 나열·범위 표기, 연결부호 상속, '위임' 후행
        self.assertEqual(m.own_articles('등록·양수합병 인가 (제6·18조)', '전기통신사업법'), (['6조', '18조'], 0))
        self.assertEqual(m.own_articles('전파사용료 부과 (제67~68조)', '전파법'), (['67조', '68조'], 0))
        self.assertEqual(m.own_articles('전파법 제37조·제45조·제47조 위임, 제1조', '무선설비규칙'), (['1조'], 3))
        self.assertEqual(m.own_articles('2년 주기 확인 등 제50조 위임 세부 (제61조~제62조의3)', '정보통신망법 시행령'),
                         (['61조', '62조의3'], 1))

    def test_judge_levels(self):
        import lawmap_edge_check as m
        self.assertEqual(m.judge('관련 조문', '전파법', True, {'9조'})[1], 'placeholder')
        self.assertEqual(m.judge('설명', '협정', False, None)[:2], ('WARN', 'doc_missing'))
        self.assertEqual(m.judge('설명 [원문 KB 미보유 — 법제처 미공개]', '협정', False, None)[0], 'OK')
        self.assertEqual(m.judge('주파수분배(제9조)', '전파법', True, {'9조', '10조'})[1], 'verified')
        self.assertEqual(m.judge('할당(제99조)', '전파법', True, {'9조'})[:2], ('ERR', 'art_missing'))
        self.assertEqual(m.judge('할당(제9조·제99조)', '전파법', True, {'9조'})[:2], ('WARN', 'art_partial'))
        self.assertEqual(m.judge('협정 전문', '협정', True, set())[1], 'no_article_scheme')
        self.assertEqual(m.judge('면허 종류 (제39조)', '지방세법 시행령', True, set())[0], 'OK')   # 조문 체계 없는 문서는 대조 불가
        self.assertEqual(m.judge('할당대금 기재 (서식 5의2)', '전파법 시행규칙', True, {'1조'})[1], 'annex_ref')
        self.assertEqual(m.judge('설명만 있음', '전파법', True, {'9조'})[:2], ('ERR', 'no_article'))


class TestAssemblyAlertBatch(unittest.TestCase):
    """assembly_crawler 알림 묶음(#140·#193) — 실행당 한 통, 구독자는 위원회 통과 이후만, 폐기류는 양쪽 제외, 그룹당 10건 + 외 N건"""

    def _bill(self, i, name='전기통신사업법 일부개정법률안'):
        return {'BILL_ID': f'PRC_{i}', 'BILL_NO': f'22{i:05d}', 'BILL_NAME': name, 'PROPOSER': '홍길동의원 등 10인',
                'CURR_COMMITTEE': '과학기술정보방송통신위원회', 'PROPOSE_DT': '2026-09-01'}

    def test_subscriber_filter_and_grouping(self):
        import assembly_crawler as ac
        changes = [(self._bill(i), '소관위 회부', '소관위 심사중', []) for i in range(57)]
        changes += [(self._bill(100), '소관위 심사중', '위원회 의결', []), (self._bill(101, '전파법 일부개정법률안'), '소관위 심사중', '대안반영폐기', []),
                    (self._bill(102), '법사위 심사중', '수정가결', [])]
        sub = ac.format_status_batch(changes, ac.SUBSCRIBER_STATUS)
        self.assertIn('[법안 상태 변경 2건]', sub)
        self.assertNotIn('소관위 심사중</b>', sub)          # 상정 전이는 구독자에게 안 감
        self.assertIn('소관위 심사중 → 위원회 의결</b> (1건)', sub)
        self.assertNotIn('대안반영폐기', sub)                # 폐기류는 구독자 제외(#193)
        self.assertLess(sub.index('수정가결</b>'), sub.index('위원회 의결</b>'))   # 의미 큰 순: 가결 먼저
        op = ac.format_status_batch(changes, ac.NOTABLE_STATUS)
        self.assertIn('[법안 상태 변경 59건]', op)
        self.assertIn('법사위 심사중 → 수정가결</b> (1건)', op)   # 본회의 가결이 운영자에게 간다(#193)
        self.assertNotIn('대안반영폐기', op)                 # 폐기류는 운영자도 제외
        self.assertIn('소관위 회부 → 소관위 심사중</b> (57건)', op)
        self.assertIn('… 외 47건', op)
        self.assertEqual(op.count('• <a href='), 12)         # 10 + 1 + 1
        self.assertLess(len(op), 3500)
        self.assertEqual(ac.format_status_batch(changes[:57], ac.SUBSCRIBER_STATUS), '')

    def test_new_bills_batch(self):
        import assembly_crawler as ac
        items = [(self._bill(i), ['전파']) for i in range(13)]
        m = ac.format_new_bills_batch(items)
        self.assertIn('[국회 신규 법안 13건]', m)
        self.assertEqual(m.count('• <a href='), 10)
        self.assertIn('… 외 3건', m)
        self.assertIn('대시보드', m)
        self.assertEqual(ac.format_new_bills_batch([]), '')

    def test_status_batch_char_cap(self):
        import assembly_crawler as ac
        changes = []
        for g in range(12):
            for i in range(10):
                changes.append((self._bill(g * 100 + i, '아주 긴 이름의 법률 제%d호 일부개정법률안' % g), f'단계{g}', '위원회 의결', []))
        m = ac.format_status_batch(changes, ac.SUBSCRIBER_STATUS, max_chars=1500)
        self.assertLess(len(m), 2200)
        self.assertIn('(대시보드에서 확인)', m)


class TestBillStageAlertTargets(unittest.TestCase):
    """#193: 실DB proc_result 8종 + 미지 코드의 알림 대상 판정."""

    def test_targets(self):
        import bill_stage as bs
        op = {'소관위 심사중': True, '위원회 의결': True, '수정가결': True, '원안가결': True, '공포': True,
              '대안반영폐기': False, '철회': False, '부결': False, '임기만료폐기': False,
              '소관위 회부': False, '접수': False, '': False, '새로운코드': True}
        for k, v in op.items():
            self.assertEqual(bs.notify_operator_stage(k), v, k)
        self.assertFalse(bs.notify_subscriber_stage('소관위 심사중'))
        self.assertTrue(bs.notify_subscriber_stage('원안가결'))
        self.assertTrue(bs.notify_subscriber_stage('위원회 의결'))
        self.assertFalse(bs.notify_subscriber_stage('대안반영폐기'))


class TestApiUsage(unittest.TestCase):
    """api_usage(#152): usage 기록 헬퍼 — 응답 반환 규약·fail-open·site 라벨 (네트워크 없음)."""

    def _resp(self):
        class U:  # anthropic Usage 흉내
            input_tokens = 1200; output_tokens = 15
            cache_read_input_tokens = 0; cache_creation_input_tokens = 0
        class R:
            usage = U(); model = 'claude-haiku-4-5-20251001'; content = []
        return R()

    def test_record_returns_response_and_never_raises(self):
        import api_usage
        captured = []
        api_usage._client = lambda: (_ for _ in ()).throw(RuntimeError('no db'))   # DB 없음 → 삼켜야 한다
        api_usage._fail_count = 0
        r = self._resp()
        self.assertIs(api_usage.record('t.py:f', r), r)
        api_usage.record_usage = lambda site, usage, model=None: captured.append((site, usage, model))
        api_usage.record('crawler.py:classify_urgency', r)
        self.assertEqual(captured[0][0], 'crawler.py:classify_urgency')
        self.assertEqual(captured[0][1].input_tokens, 1200)

    def test_usage_row_shape(self):
        import api_usage
        row = api_usage._usage_row('x.py:y', self._resp().usage, 'm')
        self.assertEqual(set(row), {'host', 'site', 'model', 'input_tokens', 'cache_read', 'cache_write', 'output_tokens', 'ts'})
        self.assertEqual(row['input_tokens'], 1200); self.assertEqual(row['cache_read'], 0)
        self.assertIsNone(api_usage._usage_row('x', None, 'm'))
        d = api_usage._usage_row('x', {'input_tokens': 3, 'cache_read_input_tokens': 2}, None)
        self.assertEqual((d['input_tokens'], d['cache_read'], d['output_tokens']), (3, 2, 0))

    def test_install_is_idempotent_and_wraps_create(self):
        import api_usage
        from anthropic.resources.messages import Messages
        api_usage._installed = False
        api_usage.install(); first = Messages.create
        api_usage.install(); self.assertIs(Messages.create, first)
        self.assertTrue(getattr(Messages, '_api_usage_wrapped', False))


class TestRefetchSummaryGate(unittest.TestCase):
    """#153: 요약 미리 생성은 정부 공고만 — 신규분 게이트와 백필 접두 목록이 같은 상수를 쓴다."""

    def test_gov_source_prefixes(self):
        import refetch_content as rc
        self.assertTrue(rc._is_gov_source('과학기술정보통신부 보도자료'))
        self.assertTrue(rc._is_gov_source('방송통신위원회 공지'))
        self.assertTrue(rc._is_gov_source('KISDI 보고서'))
        self.assertFalse(rc._is_gov_source('yna.co.kr'))
        self.assertFalse(rc._is_gov_source(''))
        self.assertFalse(rc._is_gov_source(None))
        for p in rc.GOV_SOURCE_PREFIXES:
            self.assertTrue(rc._is_gov_source(p + ' x'))

    def test_issue_suggest_hours(self):
        import crawler
        self.assertEqual(crawler.ISSUE_SUGGEST_HOURS, {5, 11, 15, 20})


class TestKmccMeeting(unittest.TestCase):
    """방미통위 회의 의사일정·위원회 결과·공지 수집기 (#154) — 순수 함수만, 네트워크 0."""

    def setUp(self):
        import kmcc_meeting as km
        self.km = km

    def test_agenda_title(self):
        km = self.km
        m = km.parse_agenda_title('2026년 제34차 방송미디어통신위원회 회의(0909) 의사일정')
        self.assertEqual((m['year'], m['nth'], m['kind']), (2026, 34, '회의'))
        self.assertEqual(m['meeting_date'], date(2026, 9, 9))
        m = km.parse_agenda_title('2026년 제33차 방송미디어통신위원회 서면회의(0904) 의사일정')
        self.assertEqual(m['kind'], '서면회의')
        m = km.parse_agenda_title('2026년 제1차 방송미디어통신위원회 회의 의사일정')
        self.assertEqual(m['nth'], 1)
        self.assertIsNone(m['meeting_date'])
        self.assertIsNone(km.parse_agenda_title('2026년 제34차 위원회 결과'))
        r = km.parse_result_title('2026년 제34차 위원회 결과')
        self.assertEqual((r['year'], r['nth']), (2026, 34))
        self.assertIsNone(km.parse_result_title('12개 홈쇼핑 사업자 재승인 의결'))

    def test_canonical_url(self):
        km = self.km
        u = km.canonical_url('/user.do;jsessionid=ABC.servlet-x?mode=view&page=A02010100&dc=K02010100&boardId=1003&cp=1&nop=10&boardSeq=69432')
        self.assertEqual(u, 'https://www.kmcc.go.kr/user.do?mode=view&page=A02010100&dc=K02010100&boardId=1003&boardSeq=69432')

    def test_meeting_rows_pick_agenda_only(self):
        km = self.km
        html = '''<table><tbody>
        <tr><td>1061</td><td><a href="/user.do;jsessionid=X?mode=view&amp;page=A02010100&amp;dc=K02010100&amp;boardId=1003&amp;cp=1&amp;boardSeq=69300">2026년 제29차 방송미디어통신위원회 회의(0821) 의사일정</a></td>
        <td><a href="/download.do?fileSeq=71683"><img alt="제2026-29차 회의 의사일정(8.21.).pdf"> 의사일정</a>
            <a href="/download.do?fileSeq=71790"><img alt="회의록.md"> 회의록</a>
            <a href="/download.do?fileSeq=71791"><img alt="속기록.md"> 속기록</a></td>
        <td>1유형</td><td>2026-08-20</td><td>446</td></tr>
        <tr><td>1060</td><td><a href="/user.do?boardId=1003&amp;boardSeq=1">2026년 제28차 방송미디어통신위원회 회의(0814) 회의록만</a></td><td></td><td></td><td>2026-08-13</td><td>1</td></tr>
        </tbody></table>'''
        rows = km.parse_meeting_rows(html)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r['board_seq'], '69300')
        self.assertEqual(r['agenda']['file_seq'], '71683')
        self.assertIn('의사일정', r['agenda']['filename'])
        self.assertEqual(r['post_date'].date(), date(2026, 8, 20))
        self.assertNotIn('cp=', r['url'])

    def test_press_rows_split_result_and_press(self):
        km = self.km
        html = '''<table><tbody>
        <tr><td>5665</td><td><a href="/user.do?boardId=1113&amp;cp=1&amp;boardSeq=69437">2026년 제34차 위원회 결과</a></td>
        <td>정책홍보팀</td><td>1유형</td><td></td><td>2026-09-09</td><td>421</td></tr>
        <tr><td>5666</td><td><a href="/user.do?boardId=1113&amp;boardSeq=69440">불법스팸 ‘최대 6% 과징금’, 10월 시행</a></td>
        <td>디지털이용자기반과</td><td>1유형</td><td></td><td>2026-09-09</td><td>446</td></tr></tbody></table>'''
        rows = km.parse_press_rows(html)
        self.assertEqual([r['kind'] for r in rows], ['result', 'press'])
        self.assertEqual(rows[0]['meta']['nth'], 34)
        self.assertEqual(rows[0]['meta']['dept'], '정책홍보팀')
        self.assertEqual(rows[1]['meta']['dept'], '디지털이용자기반과')
        self.assertNotIn('cp=', rows[0]['url'])

    def test_parse_agenda_out(self):
        km = self.km
        p = km.parse_agenda_out('회의명: 2026년 제34차 회의\n일시: 2026. 9. 9.(수) 14:30\n장소: 4층\n'
                                '[의결사항 2건]\n가|A안|내용A|과A|공개\n나|B안|내용B|과B|비공개\n[보고사항 0건]')
        self.assertEqual(p['head']['일시'], '2026. 9. 9.(수) 14:30')
        self.assertEqual(len(p['sections']), 1)
        self.assertEqual(p['sections'][0][1][1][0], '나')
        self.assertEqual(km.parse_agenda_out('그냥 문장'), {})
        self.assertEqual(km.parse_agenda_out(''), {})

    def test_agenda_html_budget_and_rules(self):
        km = self.km
        meta = {'nth': 34, 'kind': '회의', 'meeting_date': date(2026, 9, 9)}
        items = [(chr(0xAC00 + i), '안건 & 제목 %d' % i, '주요내용 ' * 30, '담당과', '공개') for i in range(20)]
        html = km.format_agenda_html(meta, {'일시': '2026. 9. 9.(수) 14:30'}, [('의결사항', items)],
                                     'https://www.kmcc.go.kr/x?a=1&b=2', 'https://www.kmcc.go.kr/download.do?fileSeq=1')
        self.assertLessEqual(len(html), km.HTML_BUDGET)
        # 제목 줄은 회의명만, 날짜·시각·건수는 다음 줄(2026-09-22 개편)
        self.assertTrue(html.startswith('📋 <b>방미통위 제34차 회의 의사일정</b>\n'
                                        '<i>9/9(수) 14:30 · 의결사항 20건</i>'))
        self.assertIn('⚖️ <b>의결사항</b>', html)
        self.assertIn('<b>① 안건 &amp; 제목 0</b>', html)      # 원문자 번호 — 'N. '가 아니어야 한다
        self.assertNotRegex(html, r'(?m)^\d+\. ')
        self.assertEqual(html.count('<blockquote>'), html.count('</blockquote>'))
        self.assertIn('&amp; 제목', html)
        self.assertIn('… 외 ', html)
        self.assertIn('>원문</a>', html)
        self.assertIn('>PDF</a>', html)
        self.assertIn('>대시보드</a>', html)
        self.assertNotRegex(html.splitlines()[0], r'\d+건')

    def test_result_html(self):
        km = self.km
        lines = km.parse_result_lines('1. [의결] 첫째\n- 둘째 접두 없음\n\n[의견청취] 셋째 ' + 'x' * 200)
        self.assertEqual(lines[0], '[의결] 첫째')
        self.assertTrue(lines[1].startswith('[기타] 둘째'))
        self.assertLessEqual(len(lines[2]), km.RESULT_LINE_CHARS + 1)
        html = km.format_result_html({'nth': 34}, datetime(2026, 9, 9, tzinfo=km.KST), lines, 'https://www.kmcc.go.kr/y')
        self.assertTrue(html.startswith('🏛️ <b>방미통위 제34차 위원회 결과</b>\n<i>9/9</i>'))
        self.assertIn('\n\n<b>[의결]</b> 첫째', html)      # 말머리는 굵게, 줄 사이는 빈 줄
        self.assertIn('\n\n<b>[기타]</b> 둘째', html)
        self.assertLessEqual(len(html), km.HTML_BUDGET)

    def test_press_html(self):
        km = self.km
        it = {'title': '공고 & 안내', 'url': 'https://www.kmcc.go.kr/n', 'post_date': datetime(2026, 9, 11, tzinfo=km.KST),
              'meta': {'dept': '대전분소'}}
        html = km.format_press_html(it, '공고 & 안내\n' + '본문 ' * 300)
        self.assertLessEqual(len(html), km.HTML_BUDGET)
        # 날짜·담당부서는 머리줄 밑 기울임 한 줄로 묶는다(2026-09-23 개편)
        self.assertTrue(html.startswith('📰 <b>방미통위 보도자료</b>\n<i>9/11 · 대전분소</i>'))
        self.assertIn('<b>공고 &amp; 안내</b>', html)
        self.assertIn('<blockquote>본문 본문', html)      # 본문은 인용구로
        self.assertIn('…', html)
        self.assertEqual(html.count('<blockquote>'), html.count('</blockquote>'))

    def test_press_html_subtitle_and_sentence_cut(self):
        """부제('- … -')는 제목 밑 제 줄로, 본문은 문장 끝에서 자른다 (#184-보론3)."""
        km = self.km
        it = {'title': '제목', 'url': 'https://www.kmcc.go.kr/n', 'post_date': None, 'meta': {}}
        body = '제목\n- 부제 한 줄 -\n' + '이어지는 문장이다. ' * 120 + '여기는 잘린다'
        html = km.format_press_html(it, body)
        self.assertIn('<i>부제 한 줄</i>', html)
        self.assertNotIn('- 부제 한 줄 -', html)
        self.assertNotIn('여기는 잘린다', html)
        body_line = [ln for ln in html.split('\n') if ln.startswith('<blockquote>')][0]
        self.assertTrue(body_line.endswith('다. …</blockquote>'), body_line[-40:])
        # 문장 끝이 너무 앞에만 있으면 종전처럼 글자 수로 자른다
        long1 = km._snip('가' * 50 + '다.' + '나' * 400, 200)
        self.assertTrue(long1.endswith('…') and not long1.endswith('다. …'))

    def test_should_queue_window(self):
        km = self.km
        now = datetime(2026, 9, 11, 18, 0, tzinfo=km.KST)
        self.assertTrue(km.should_queue(datetime(2026, 9, 9, tzinfo=km.KST), now))
        self.assertFalse(km.should_queue(datetime(2026, 9, 8, tzinfo=km.KST), now))
        self.assertFalse(km.should_queue(None, now))

    def test_press_always_ingest(self):
        import press_ingest as pi
        self.assertTrue(pi.ALWAYS_INGEST_RE.search('2026년 제34차 위원회 결과'))
        self.assertFalse(pi.ALWAYS_INGEST_RE.search('불법스팸 최대 6% 과징금'))

    def test_subscriber_topics(self):
        import subscriber_notify as sn
        self.assertIn('kmcc', sn._VALID_TOPICS)
        self.assertIn('kmcc', sn._IMMEDIATE_TOPICS)
        self.assertNotIn('assembly', sn._IMMEDIATE_TOPICS)

    def test_gov_prefix_new_names(self):
        import refetch_content as rc
        self.assertTrue(rc._is_gov_source('방송미디어통신위원회 위원회 회의'))
        self.assertTrue(rc._is_gov_source('방미통위 공지'))

    def test_press_relevant_fallback(self):
        km = self.km
        kw = ['주파수', '5G']
        self.assertTrue(km.press_relevant(None, kw, '5G 특화망 주파수 공급', '')[0])
        self.assertFalse(km.press_relevant(None, kw, '드라마 제작 사례 공유', '주파수라는 낱말이 본문에만')[0])
        self.assertEqual(km.press_relevant(lambda t, b: (True, 'ai'), kw, 'x', 'y'), (True, 'ai'))
        # 제목 키워드 일치는 AI 판정보다 우선(안전망)
        self.assertTrue(km.press_relevant(lambda t, b: (False, 'ai-무관'), kw, '5G 지원금 안내', '')[0])


class TestUrgencyShadow(unittest.TestCase):
    """#162: 선별 등급 그림자 기록 — 통과분 전건에 urgency_screen 키가 있어야 벌크 upsert가 산다."""

    def test_setdefault_covers_every_passed_item(self):
        import crawler
        # 판정 경로를 안 탄 항목(인사 자동통과·키워드 폴백)에도 키가 생기는지 — 안전망 한 줄의 계약
        passed = [{'title': 'a'}, {'title': 'b', 'urgency_screen': '긴급'}]
        for it in passed:
            it.setdefault('tags', [])
            it.setdefault('event', '')
            it.setdefault('urgency_screen', '')
        keys = [set(i) for i in passed]
        self.assertEqual(keys[0], keys[1], 'PostgREST 벌크 upsert는 모든 행의 키 집합이 같아야 한다')
        self.assertEqual(passed[0]['urgency_screen'], '')
        self.assertEqual(passed[1]['urgency_screen'], '긴급')

    def test_screen_urgency_vocabulary_maps_to_db_values(self):
        import crawler
        self.assertEqual(crawler._AI_PRIORITY_MAP['즉시대응'], '긴급')
        self.assertEqual(crawler._AI_PRIORITY_MAP['금주검토'], '보통')
        self.assertEqual(crawler._AI_PRIORITY_MAP['동향파악'], '참고')
        self.assertEqual(crawler._AI_PRIORITY_MAP.get('알수없는값', ''), '')


class TestMinutesConferDedupe(unittest.TestCase):
    """#187: 국감 confer_num('audit-N')도 본문 링크의 'id=N'으로 중복 판정해야 한다."""

    @staticmethod
    def _fake_sb(hit_pattern):
        seen = []
        class _Q:
            def __init__(self): self.pat = None
            def select(self, *a): return self
            def eq(self, *a): return self
            def like(self, col, pat): self.pat = pat; seen.append(pat); return self
            def limit(self, *a): return self
            def execute(self):
                return mock.Mock(data=[{'id': 1}] if self.pat == hit_pattern else [])
        sb = mock.Mock()
        sb.table.side_effect = lambda name: _Q()
        return sb, seen

    def test_audit_prefix_stripped(self):
        import assembly_minutes as am
        sb, seen = self._fake_sb('%id=51996&%')
        self.assertTrue(am.section_exists_by_confer(sb, '과방위_회의록_2024.md', 'audit-51996'))
        self.assertFalse(any('audit-' in p for p in seen))

    def test_committee_number_unchanged(self):
        import assembly_minutes as am
        sb, seen = self._fake_sb('%id=43150)%')
        self.assertTrue(am.section_exists_by_confer(sb, '과방위_회의록_2025.md', '43150'))
        sb2, _ = self._fake_sb('%id=99999)%')
        self.assertFalse(am.section_exists_by_confer(sb2, '과방위_회의록_2025.md', '43150'))


class TestMinutesYearRollover(unittest.TestCase):
    """#189: 1~2월엔 전년도 회의록도 조회, --year 지정 시 그 해만."""

    def test_rollover(self):
        import assembly_minutes as am
        self.assertEqual(am.years_to_run(None, datetime(2027, 1, 5)), [2026, 2027])
        self.assertEqual(am.years_to_run(None, datetime(2027, 2, 28)), [2026, 2027])
        self.assertEqual(am.years_to_run(None, datetime(2027, 3, 1)), [2027])
        self.assertEqual(am.years_to_run(2019, datetime(2027, 1, 5)), [2019])


class TestKmccSubjectSplit(unittest.TestCase):
    """안건명 ' - 대상 -' 꼬리 분리 — 제목 안의 붙은 하이픈(2026-2027, SK-브로드밴드)은 자르지 않는다."""

    def test_split(self):
        import kmcc_meeting as km
        self.assertEqual(km._split_subject('2026-2027 방송평가 기본계획 수립에 관한 건 - 지상파방송사 -'),
                         ('2026-2027 방송평가 기본계획 수립에 관한 건', '지상파방송사'))
        self.assertEqual(km._split_subject('시정조치에 관한 건 - ㈜케이티, ㈜엘지유플러스 -'),
                         ('시정조치에 관한 건', '㈜케이티, ㈜엘지유플러스'))
        self.assertEqual(km._split_subject('시정조치에 관한 건 - SK-브로드밴드 -'), ('시정조치에 관한 건', 'SK-브로드밴드'))
        self.assertEqual(km._split_subject('2026-2027 방송평가 기본계획'), ('2026-2027 방송평가 기본계획', ''))


class TestPressWindow(unittest.TestCase):
    """#195: 보도자료 매일 수집 창 = 마지막 정상 완료 경과일(올림) + 3일, 최소 3·최대 15, 기록 없음·오류는 15."""

    @staticmethod
    def _sb(ts):
        sb = mock.Mock()
        q = sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value
        q.execute.return_value = None if ts is None else mock.Mock(data={'updated_at': ts})
        return sb

    def test_window(self):
        import press_ingest as pi
        from datetime import timezone as tz
        now = datetime.now(tz.utc)
        self.assertEqual(pi._press_window_days(self._sb(None)), 15)
        self.assertEqual(pi._press_window_days(self._sb((now - timedelta(hours=23)).isoformat())), 4)
        self.assertEqual(pi._press_window_days(self._sb((now - timedelta(days=5, hours=2)).isoformat())), 9)
        self.assertEqual(pi._press_window_days(self._sb((now - timedelta(days=30)).isoformat())), 15)
        bad = mock.Mock(); bad.table.side_effect = RuntimeError('down')
        self.assertEqual(pi._press_window_days(bad), 15)


class TestDashboardCacheBuster(unittest.TestCase):
    """index.html 캐시 번호(?v=YYYYMMDD…)가 각 정적 파일의 마지막 수정일보다 이르면 실패 (2026-09-24).
    system_prompt.js 번호가 09-11에 멈춘 채 파일이 세 번 바뀌어, 캐시가 남은 브라우저는 옛 자문 지시문을 썼다.
    커밋 전 수정분(작업 트리·스테이징)은 번호가 오늘(KST)이어야 한다. git이 없거나 기록이 없으면 건너뛴다."""

    FILES = ('app.js', 'styles.css', 'system_prompt.js', 'supabase/functions/_shared/cite_verify.js')

    def _git(self, *args):
        import subprocess
        r = subprocess.run(['git', '-C', _ROOT] + list(args), capture_output=True, text=True, encoding='utf-8')
        return r.returncode, (r.stdout or '').strip()

    def test_buster_not_older_than_file(self):
        from datetime import timezone as tz
        try:
            rc, _ = self._git('rev-parse', '--git-dir')
        except Exception:
            self.skipTest('git 없음')
        if rc != 0:
            self.skipTest('git 저장소 아님')
        html = open(os.path.join(_ROOT, 'index.html'), encoding='utf-8').read()
        kst = tz(timedelta(hours=9))
        today = datetime.now(kst).strftime('%Y%m%d')
        for f in self.FILES:
            m = re.search(re.escape(f) + r'\?v=(\d{8})', html)
            self.assertIsNotNone(m, f'index.html에 {f}?v= 없음')
            buster = m.group(1)
            dirty = self._git('diff', '--quiet', 'HEAD', '--', f)[0] != 0
            if dirty:
                self.assertEqual(buster, today, f'{f}: 커밋 전 수정이 있는데 캐시 번호가 {buster} — 오늘({today})로 올릴 것')
                continue
            rc, ct = self._git('log', '-1', '--format=%ct', '--', f)
            if rc != 0 or not ct:
                continue
            last = datetime.fromtimestamp(int(ct), kst).strftime('%Y%m%d')
            self.assertGreaterEqual(buster, last, f'{f}: 마지막 수정 {last} > 캐시 번호 {buster} — index.html의 ?v=를 올릴 것')


class TestSpeakerNormalize(unittest.TestCase):
    """#164: 호환 한자(U+F900~) 발언자명이 표준 한자로 모여야 인물 명부가 갈라지지 않는다."""

    def test_compat_hanja_collapses(self):
        import assembly_minutes as am
        self.assertEqual(am.normalize_speaker('\uf90a\u6210\u6cf0'), '\u91d1\u6210\u6cf0')  # 金成泰
        self.assertEqual(am.normalize_speaker('\uf9c9\u69ae\u590f'), '\u67f3\u69ae\u590f')  # 柳榮夏

    def test_title_strip_still_works(self):
        import assembly_minutes as am
        self.assertEqual(am.normalize_speaker('최민희 위원장'), '최민희')
        self.assertEqual(am.normalize_speaker('위원장 최민희'), '최민희')


class TestPeopleRegisterThreshold(unittest.TestCase):
    """#164: 의원·위원장은 1건, 통신사 임원은 무조건, 그 외 정부·참고인만 4건 이상."""

    def _decide(self, poss, n, name):
        import tools_people_refresh as tp
        is_member = bool(set(poss) & tp.MEMBER_POS)
        is_telco = (any(tp.TELCO_ORG.search(p) for p in poss)
                    or (name in tp.TELCO_NAMES
                        and any(w in p for p in poss for w in tp.WITNESS_POS)))
        return (is_member or is_telco or n >= 4), is_member

    def test_member_one_speech_registers(self):
        self.assertEqual(self._decide(['위원'], 1, '최혁진'), (True, True))
        self.assertEqual(self._decide(['의원'], 1, '이언주'), (True, True))

    def test_telco_ceo_registers_even_as_witness(self):
        # 회의록 직함이 '증인' 하나뿐인 실제 사례 — 이름 명단이 없으면 못 걸러진다
        self.assertEqual(self._decide(['증인'], 2, '김영섭'), (True, False))
        self.assertEqual(self._decide(['증인'], 1, '하현회'), (True, False))
        # 소속이 드러난 직함은 이름 명단 없이도 통과
        self.assertEqual(self._decide(['㈜LG유플러스부사장'], 3, '박형일'), (True, False))

    def test_other_witness_still_needs_four(self):
        self.assertEqual(self._decide(['증인'], 3, '홍길동'), (False, False))
        self.assertEqual(self._decide(['증인'], 4, '홍길동'), (True, False))

    def test_telco_name_alone_is_not_enough(self):
        # 동명이인 방어 — 증인·참고인 자격이 아니면 이름만으로는 등록하지 않는다
        self.assertEqual(self._decide(['한국인터넷진흥원장직무대행'], 1, '박정호'), (False, False))


class TestPersonRoleKind(unittest.TestCase):
    """#166: 자격이 바뀐 인물 — kind는 현재 자격(최신 발언 직함)으로 매번 다시 계산한다."""

    def _kind(self, latest_pos):
        import tools_people_refresh as tp
        return '의원' if latest_pos in tp.MEMBER_POS else '정부·참고인'

    def test_kind_follows_latest_position(self):
        # 이진숙: 방통위원장(15건) → 과방위원(1건). 현재 자격이 위원이므로 '의원'
        self.assertEqual(self._kind('위원'), '의원')
        # 김민석: 위원 → 국무총리. 현재 자격이 정부이므로 '정부·참고인'
        self.assertEqual(self._kind('국무총리'), '정부·참고인')

    def test_member_pos_covers_deputy_chair_titles(self):
        import tools_people_refresh as tp
        # 2026-09-13까지 빠져 있던 의원석 직함들
        for pos in ('소위원장대리', '소위원장직무대리', '위원장직무대리', '반장'):
            self.assertIn(pos, tp.MEMBER_POS, pos + ' 이 의원석 직함에 없다')


class TestPruneOrphanTerms(unittest.TestCase):
    """morning_briefing._prune_orphan_terms — 본문과 연결되지 않는 기술 용어 제거 (#161-보론13)

    독립 채점에서 세 날 연속 지적: '솔트 타이푼'이 용어로 올라 있는데 그 사건은 두 섹션 어디에도
    없었고, '저궤도 맨팩 안테나'는 출처 기사 자체가 실리지 않았다. 프롬프트로도 막지만
    모델이 어기는 날이 있어 코드에서 한 번 더 거른다.
    """

    def _sample(self, terms):
        body = ('[주요 뉴스]' + chr(10)
                + '- 솔트 타이푼 침해 정황 확인 [ID:x]' + chr(10)
                + '  -> AI-RAN 적용 사례도 함께 공개됐다' + chr(10) + chr(10))
        seg = chr(10).join('* ' + t for t in terms)
        return (body + '[새로 추가된 기술 용어]' + chr(10) + seg + chr(10) + chr(10)
                + '[저장 결과]' + chr(10) + '뉴스 21건 / 기술 용어 ' + str(len(terms)) + '건')

    def test_drops_terms_absent_from_body(self):
        import morning_briefing as mb
        t = self._sample(['솔트 타이푼: 중국 연계 해킹 조직',
                          '저궤도 맨팩 안테나: 이동식 위성 안테나',
                          'AI-RAN: 무선 접속망에 AI를 적용하는 구조'])
        out = mb._prune_orphan_terms(t.replace('* ', '\u2022' + ' '))
        self.assertIn('솔트 타이푼', out)
        self.assertIn('AI-RAN', out)
        self.assertNotIn('맨팩', out)

    def test_fixes_saved_count(self):
        import morning_briefing as mb
        t = self._sample(['솔트 타이푼: 중국 연계 해킹 조직',
                          '저궤도 맨팩 안테나: 이동식 위성 안테나'])
        out = mb._prune_orphan_terms(t.replace('* ', '\u2022' + ' '))
        self.assertIn('기술 용어 1건', out)

    def test_no_section_is_passthrough(self):
        import morning_briefing as mb
        t = '[주요 뉴스]' + chr(10) + '- 아무 기사 [ID:x]'
        self.assertEqual(mb._prune_orphan_terms(t), t)


class TestBriefingBodyAndTitleGuards(unittest.TestCase):
    """morning_briefing — 본문 미확보 판정·제목 복원·매체명 정규화 (#161-보론14)

    셋 다 독립 채점에서 반복 지적된 것을 코드로 막는 장치다.
    프롬프트로만 막으면 하루 3~4건씩 남는다는 것이 회차마다 확인됐다.
    """

    def test_menu_only_body_is_not_real(self):
        import morning_briefing as mb
        menu = ('최종편집 2026-09-13 16:38 (일) 로그인 회원가입 전체보기 산업 ICT·AI '
                '소재에너지 모빌리티 식품유통 게임콘텐츠 바이오헬스 경제 금융 증시 부동산 정치 국제 사회')
        self.assertFalse(mb._has_real_body({'content': menu}))

    def test_real_article_passes(self):
        import morning_briefing as mb
        art = ('과학기술정보통신부는 13일 이동통신 3사에 대한 실태점검 결과를 발표했다. '
               '점검 대상은 전년도 매출 1조원 이상 사업자이며 10월 1일부터 적용된다.')
        self.assertTrue(mb._has_real_body({'content': art}))

    def test_short_body_is_not_real(self):
        import morning_briefing as mb
        self.assertFalse(mb._has_real_body({'content': '짧은 안내문'}))

    def test_truncated_title_is_restored(self):
        import morning_briefing as mb
        full = '류신환 위원 "일률적 규제나 정부 개입은 지양해야"'
        uid = '11111111-2222-3333-4444-555555555555'
        line = ('•' + ' ' + '🟡' + ' 류신환 위원 "일률적 규제나... (관련 보도 3건) '
                + '— sbs [ID:' + uid + ']')
        out = mb._restore_titles(line, [{'id': uid, 'title': full}])
        self.assertIn(full, out)
        self.assertIn('(관련 보도 3건)', out)
        self.assertIn('[ID:' + uid + ']', out)

    def test_intact_title_is_untouched(self):
        import morning_briefing as mb
        uid = '11111111-2222-3333-4444-555555555555'
        line = '•' + ' ' + '🟡' + ' 멀쩡한 제목 — sbs [ID:' + uid + ']'
        self.assertEqual(mb._restore_titles(line, [{'id': uid, 'title': '다른 제목'}]), line)

    def test_source_slug_becomes_korean_name(self):
        import morning_briefing as mb
        self.assertEqual(mb._pretty_source('hellot'), '헬로티')
        self.assertEqual(mb._pretty_source('ggilbo'), '금강일보')
        # 매핑에 없으면 원래 값을 그대로 둔다(fail-soft)
        self.assertEqual(mb._pretty_source('연합뉴스'), '연합뉴스')
        self.assertEqual(mb._pretty_source('알수없는매체'), '알수없는매체')


class TestOkfDriftCheck(unittest.TestCase):
    """㉑ okf_drift_check — OKF 요약(kb_documents) ↔ 조문 현행본(law_watch) 판 대조 (#197)"""

    KB = [
        {'title': '개인정보 보호법 시행령', 'law_type': '대통령령', 'law_number': '제36121호',
         'enforcement_date': '2026-08-20', 'path': 'laws/privacy-act/enforcement_decree_36121.md'},
        {'title': '전파법 시행규칙', 'law_type': '과학기술정보통신부령', 'law_number': '제156호',
         'enforcement_date': '2025-10-01', 'path': 'laws/radio-act/enforcement_rule.md'},
        {'title': '방송통신기자재등의 적합성평가에 관한 고시 (과기정통부고시 제2026-10호)',
         'law_type': '과학기술정보통신부고시', 'law_number': '제2026-10호',
         'enforcement_date': '2026-02-10', 'path': 'laws/radio-act/ca/msit_2026_10.md'},
        {'title': '방송통신기자재등의 적합성평가에 관한 고시 (국립전파연구원고시 제2026-4호)',
         'law_type': '국립전파연구원고시', 'law_number': '제2026-4호',
         'enforcement_date': '2026-07-24', 'path': 'laws/radio-act/ca/rra_2026_4.md'},
        {'title': '방송통신기자재등의 적합성평가에 관한 고시 (과기정통부고시 제2025-56호) [시행예정 2026.11.6.]',
         'law_type': '과학기술정보통신부고시', 'law_number': '제2025-56호',
         'enforcement_date': '2026-11-06', 'path': 'laws/radio-act/ca/msit_2025_56.md'},
        {'title': '금지행위 위반에 대한 과징금 부과 세부기준', 'law_type': '방송통신위원회고시',
         'law_number': '제2026-11호', 'enforcement_date': '2026-05-18', 'path': 'laws/tba/penalty.md'},
        {'title': 'ITU-R 권고 M.1036', 'law_type': 'ITU-R 권고', 'law_number': 'M.1036-6',
         'enforcement_date': None, 'path': 'itu/m1036.md'},
    ]
    WATCH = [
        {'doc_name': '개인정보 보호법 시행령(대통령령)(제36671호)(20260911)'},
        {'doc_name': '전파법 시행규칙(과학기술정보통신부령)(제00156호)(20251001)'},
        {'doc_name': '방송통신기자재등의 적합성평가에 관한 고시(국립전파연구원고시)(제2026-4호)(20260724)'},
        {'doc_name': '금지행위 위반에 대한 과징금 부과 세부기준(방송미디어통신위원회고시)(제2026-11호)(20260518)'},
    ]

    def test_norm_no_ignores_leading_zeros_and_labels(self):
        import okf_drift_check as od
        self.assertEqual(od.norm_no('제00156호'), od.norm_no('제156호'))
        self.assertEqual(od.norm_no('제2026-4호'), '2026-4')
        self.assertNotEqual(od.norm_no('제2026-4호'), od.norm_no('제2026-10호'))

    def test_drift_only_for_real_version_mismatch(self):
        import okf_drift_check as od
        drift = od.find_drift(self.KB, self.WATCH, today='20260924')
        titles = [d['title'] for d in drift]
        # 진짜 어긋남: 요약 36121(8/20) vs 조문 36671(9/11)
        self.assertEqual(titles, ['개인정보 보호법 시행령'])
        self.assertEqual(drift[0]['cur_no'], '제36671호')
        self.assertEqual(drift[0]['kb_enf'], '20260820')

    def test_zero_padded_number_is_not_drift(self):
        import okf_drift_check as od
        self.assertEqual(od.find_drift([self.KB[1]], self.WATCH, today='20260924'), [])

    def test_same_title_other_agency_is_not_compared(self):
        """적합성평가 고시: kb 과기정통부판은 law_watch 전파연구원 행과 짝짓지 않는다(대조 불가 ≠ 어긋남)"""
        import okf_drift_check as od
        self.assertEqual(od.find_drift([self.KB[2], self.KB[3]], self.WATCH, today='20260924'), [])

    def test_future_enforcement_summary_is_skipped(self):
        import okf_drift_check as od
        watch = self.WATCH + [{'doc_name': '방송통신기자재등의 적합성평가에 관한 고시(과학기술정보통신부고시)(제2026-10호)(20260210)'}]
        self.assertEqual(od.find_drift([self.KB[4]], watch, today='20260924'), [])
        # 시행일이 도래하면 그때부터 대조 대상 — 같은 소관의 조문(2026-10호)과 다르므로 어긋남
        self.assertEqual(len(od.find_drift([self.KB[4]], watch, today='20261110')), 1)

    def test_agency_rename_alias_matches(self):
        """방송통신위원회 → 방송미디어통신위원회 개명: kb 옛 이름과 law_watch 새 이름을 같은 소관으로 본다"""
        import okf_drift_check as od
        self.assertEqual(od.find_drift([self.KB[5]], self.WATCH, today='20260924'), [])

    def test_rows_without_number_are_ignored(self):
        import okf_drift_check as od
        self.assertEqual(od.find_drift([self.KB[6]], self.WATCH, today='20260924'), [])

    def test_signature_changes_with_set(self):
        import okf_drift_check as od
        a = od.find_drift(self.KB, self.WATCH, today='20260924')
        self.assertNotEqual(od.drift_signature(a), od.drift_signature([]))
        self.assertEqual(od.drift_signature(a), od.drift_signature(list(a)))

    def test_message_has_resolution_and_instruction(self):
        import okf_drift_check as od
        drift = od.find_drift(self.KB, self.WATCH, today='20260924')
        msg = od.format_message(drift)
        self.assertIn('OKF 요약 갱신 필요 1건', msg)
        self.assertIn('제36671호', msg)
        self.assertIn('세션에서', msg)
        self.assertIn('해소', od.format_message([]))


class TestLawSyncReport(unittest.TestCase):
    """㉒ law_sync 교체 완료 통지 서식 (#197) — 청크 급변 경고·실패·OKF 어긋남"""

    def _report(self, old_count, new_count):
        return [{'law_name': '항공안전법', 'old_no': '제21268호', 'old_enf': '20260701',
                 'new_no': '제21822호', 'new_enf': '20260917',
                 'old_count': old_count, 'new_count': new_count, 'deleted': [], 'note': ''}]

    def test_normal_change_has_no_warning(self):
        import law_sync
        msg = law_sync.format_sync_report(self._report(73, 83), [], drift=[], keep_old=True, now='09/24 11:40')
        self.assertIn('법령 자동 현행화 완료 1건', msg)
        self.assertIn('제21268호(20260701) → <b>제21822호</b>(20260917) · 청크 73→83', msg)
        self.assertIn('구판 보존(--keep-old)', msg)
        self.assertNotIn('급변', msg)
        self.assertIn('OKF 요약은 모두 조문 판과 일치', msg)

    def test_chunk_jump_is_flagged(self):
        """청크 300→12: 동명이법·취득 누락 의심 — 무인 교체가 조용히 지나가지 않게 표시"""
        import law_sync
        msg = law_sync.format_sync_report(self._report(300, 12), [], drift=[], now='09/24 11:40')
        self.assertIn('청크 수 급변', msg)
        msg2 = law_sync.format_sync_report(self._report(50, 120), [], drift=[], now='09/24 11:40')
        self.assertIn('청크 수 급변', msg2)

    def test_failures_and_drift_are_listed(self):
        import law_sync
        drift = [{'title': '항공안전법', 'kb_no': '제21268호', 'kb_enf': '20260701',
                  'cur_no': '제21822호', 'cur_enf': '20260917', 'path': 'x.md', 'doc_name': 'd'}]
        msg = law_sync.format_sync_report(self._report(73, 83), [('전파법', '법제처 미매칭')],
                                          drift=drift, now='09/24 11:40')
        self.assertIn('현행화 실패 1건', msg)
        self.assertIn('전파법: 법제처 미매칭', msg)
        self.assertIn('OKF 요약 갱신 필요 1건', msg)
        self.assertIn('세션에서', msg)

    def test_drift_check_failure_is_visible(self):
        import law_sync
        msg = law_sync.format_sync_report(self._report(73, 83), [], drift=None, now='09/24 11:40')
        self.assertIn('OKF 요약 대조 실패', msg)

    def test_reentry_note_is_shown(self):
        import law_sync
        rep = self._report(73, 83)
        rep[0]['note'] = '재진입 정리(current 구본 1건 강등)'
        msg = law_sync.format_sync_report(rep, [], drift=[], now='09/24 11:40')
        self.assertIn('재진입 정리', msg)


class TestOkfRefresh(unittest.TestCase):
    """㉓ okf_refresh — OKF 요약 자동 갱신의 순수 부품 (#198): path·호수·조문 차이·출력 검증·통지"""

    def test_kb_law_number_normalizes_api_style(self):
        import okf_refresh as orf
        self.assertEqual(orf.kb_law_number('제00160호'), '제160호')
        self.assertEqual(orf.kb_law_number('제2026-26호'), '제2026-26호')
        self.assertEqual(orf.ymd_dash('20260910'), '2026-09-10')

    def test_new_doc_path_replaces_version_tag(self):
        import okf_refresh as orf
        self.assertEqual(orf.new_doc_path('laws/privacy-act/enforcement_decree_36121.md', '제36671호'),
                         'laws/privacy-act/enforcement_decree_36671.md')
        self.assertEqual(orf.new_doc_path('laws/tba/notices/prohibited_conduct_handling.md', '제2026-26호'),
                         'laws/tba/notices/prohibited_conduct_handling_2026_26.md')
        self.assertEqual(orf.new_doc_path('laws/radio-act/ca/msit_2026_10.md', '제2026-12호'),
                         'laws/radio-act/ca/msit_2026_12.md')
        # 같은 호수로 다시 돌면 이름이 겹치지 않게
        self.assertNotEqual(orf.new_doc_path('laws/x/a_36671.md', '제36671호'), 'laws/x/a_36671.md')

    def test_retitle_only_when_number_in_title(self):
        import okf_refresh as orf
        self.assertEqual(orf.retitle('개인정보 보호법 시행령', '제36121호', '제36671호'), '개인정보 보호법 시행령')
        self.assertEqual(orf.retitle('적합성평가 고시 (과기정통부고시 제2026-10호)', '제2026-10호', '제2026-12호'),
                         '적합성평가 고시 (과기정통부고시 제2026-12호)')

    def test_article_diff_classifies_changes(self):
        import okf_refresh as orf
        old = [('제1조', '목적'), ('제2조', '정의 가'), ('제3조', '삭제될 조문'), ('', '부칙')]
        new = [('제1조', '목적'), ('제2조', '정의 나'), ('제4조', '신설'), ('', '부칙')]
        d = orf.article_diff(old, new)
        self.assertEqual(d['added'], ['제4조'])
        self.assertEqual(d['removed'], ['제3조'])
        self.assertEqual(d['changed'], ['제2조'])
        self.assertIn('개정된 제2조', d['text'])
        self.assertIn('정의 가', d['text'])          # 구판 원문이 실린다
        self.assertNotIn('정의 나', d['text'])       # 새 판은 전문 블록에 있으므로 중복 안 함

    def test_article_diff_ignores_whitespace_only(self):
        import okf_refresh as orf
        d = orf.article_diff([('제1조', '목적  이다')], [('제1조', '목적 이다')])
        self.assertEqual(d['changed'], [])

    def _md(self, body_len=1200, with_citations=True, fence=False, no=' 제2026-26호'):
        body = ('# 요약\n\n**제2026-26호(2026-09-10 시행) 개정 요지**: 제5조 개정.\n\n' + ('가' * body_len)
                + '\n\n# 실무 체크리스트\n\n- [ ] 확인\n' + ('\n# Citations\n\n[1] 문서\n' if with_citations else ''))
        md = ('---\ntype: Notice\ntitle: 규정\nlaw_number:' + no + '\nenforcement_date: 2026-09-10\nstatus: current\n---\n\n' + body)
        return ('```markdown\n' + md + '\n```') if fence else md

    def test_validate_output_accepts_normal_document(self):
        import okf_refresh as orf
        meta = {'new_no': '제2026-26호'}
        fm, body = orf.validate_output(self._md(), '나' * 1000, 'laws/x/y_2026_26.md', meta)
        self.assertEqual(fm.get('law_number'), '제2026-26호')
        self.assertTrue(body.startswith('# 요약'))
        # 코드펜스로 감싸 와도 벗겨서 통과
        fm2, _ = orf.validate_output(self._md(fence=True), '나' * 1000, 'laws/x/y.md', meta)
        self.assertEqual(fm2.get('status'), 'current')

    def test_validate_output_rejects_truncated_and_bloated(self):
        import okf_refresh as orf
        meta = {'new_no': '제2026-26호'}
        with self.assertRaises(ValueError):          # Citations 없음 = 끝까지 생성 안 됨
            orf.validate_output(self._md(with_citations=False), '나' * 1000, 'laws/x/y.md', meta)
        with self.assertRaises(ValueError):          # 분량 급변(구판 1만 자 → 1천 자)
            orf.validate_output(self._md(), '나' * 10000, 'laws/x/y.md', meta)
        with self.assertRaises(ValueError):          # 새 호수가 어디에도 없음
            orf.validate_output(self._md(no=' 제2026-11호').replace('제2026-26호', '제2026-11호'),
                                '나' * 1000, 'laws/x/y.md', meta)
        with self.assertRaises(ValueError):          # frontmatter 없음
            orf.validate_output('# 요약\n' + '가' * 1200 + '\n# Citations\n', '나' * 1000, 'laws/x/y.md', meta)

    def test_validate_output_fills_placeholder_number(self):
        """시험 실행 실측: 규칙문의 '제N호'를 제목에 그대로 베낀 문서 → 실제 호수로 바꿔 통과"""
        import okf_refresh as orf
        md = self._md().replace('**제2026-26호(2026-09-10 시행) 개정 요지**', '**제N호(2026-09-10 시행) 개정 요지**')
        _, body = orf.validate_output(md, '나' * 1000, 'laws/x/y.md', {'new_no': '제2026-26호'})
        self.assertIn('**제2026-26호(2026-09-10 시행) 개정 요지**', body)
        self.assertNotIn('제N호', body)

    def test_validate_output_rewrites_block_labels_but_rejects_whole_block(self):
        """첫 체인 실행 실측: '[새 판 전문]에 따르면' 같은 언급만으로 기각돼 $0.38이 버려짐 → 언급은 풀어 쓰고 통째 혼입만 기각"""
        import okf_refresh as orf
        meta = {'new_no': '제2026-26호'}
        md = self._md().replace('제5조 개정.', '제5조 개정([새 판 전문]에 따르면, [직전 판과의 조문 차이] 참조).')
        _, body = orf.validate_output(md, '나' * 1000, 'laws/x/y.md', meta)
        self.assertIn('새 판 조문에 따르면', body)
        self.assertNotIn('[새 판 전문]', body)
        self.assertNotIn('[직전 판과의 조문 차이]', body)
        md2 = self._md().replace('제5조 개정.', '제5조 개정.\n[메타]\ntitle=규정 / law_type=고시\n')
        with self.assertRaises(ValueError):
            orf.validate_output(md2, '나' * 1000, 'laws/x/y.md', meta)

    def test_report_lists_cost_diff_and_failures(self):
        import okf_refresh as orf
        done = [{'title': '업무처리규정', 'old_no': '제2026-11호', 'new_no': '제2026-26호', 'new_enf': '2026-09-10',
                 'old_len': 11910, 'new_len': 12300, 'chunks': 17, 'cost': 0.21,
                 'diff': {'added': ['제9조의2'], 'removed': [], 'changed': ['제5조']}}]
        msg = orf.format_refresh_report(done, [('전파법', '분량 급변')], [('지방세법 시행령', '입력 초과 — 세션 처리')],
                                        now='09/24 11:45')
        self.assertIn('OKF 요약 자동 갱신 1건', msg)
        self.assertIn('$0.21', msg)
        self.assertIn('신설 1·삭제 0·개정 1', msg)
        self.assertIn('자동 갱신 실패 1건', msg)
        self.assertIn('보류 1건', msg)
        self.assertIn('superseded로 보존', msg)
