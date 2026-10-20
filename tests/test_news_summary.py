# -*- coding: utf-8 -*-
"""텔레그램 주요 뉴스 2문장 요약 줄(#298, 2026-10-13 운영자 결정 6개) — 네트워크 없이.

  · 지시문·요청 모양은 지문으로 잠근다 — 고칠 때는 tools_news_summary_probe.py로 실제 기사 10건을 다시 재고 운영자 대조 뒤에.
    실측 도구는 운영과 같은 요청(news_summary.request_kwargs)을 보낸다(잰 것 = 돌리는 것). 샘플링 인자는 없다(지침 do-not).
  · SK텔레콤 언급 줄(규칙 7, #324, 2026-10-20 운영자 제안 → 실측 D′): 두 문장 요약 요청은 **모든 기사가** 10-13 고정본과 바이트 단위로
    같다(LOCK_1013). 제목+입력 글에 SK텔레콤·SKT·에스케이텔레콤이 있는 기사만 요약 뒤 **두 번째 호출**(news_skt_line — 요약을 보여 주고
    「거기 없는 SK텔레콤만의 내용 한 문장, 없으면 「없음」」)로 줄을 받아 tg_text가 「요약\nSKT 언급: …」으로 잇는다. 줄 호출의
    실패·잘림·「없음」은 줄만 빠지고 요약은 그대로(fail-open, 결과 skt 칸). format_news_item은 줄바꿈마다 인용구 한 줄, 둘째 줄부터 「— 」.
  · 받는 응답: 끝까지 씀(end_turn) + 「다.」로 끝남 + 메타 응답·「없음」·한글 적은 응답 아님 — 아니면 제목만(fail-open).
  · format_news_item: _summary가 없으면 종전과 바이트 단위로 같고, 있으면 출처 줄 아래 인용구 한 줄(이스케이프).
  · fetch_article_body는 전문을 돌려주고 저장(content)은 호출부가 1,500자로 자른다 — 전문 앞 8,000자는 메모리(_FULL_BODIES)만.
  · attach_tg_summaries: 원본 dict 불변(복사본에만), 기사당 한 번(메모), 전문 없으면 생략(reuse_db면 저장본), 키 없음·실패 누적 중단.
"""
import contextlib
import hashlib
import io
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import crawler                          # noqa: E402
import news_summary as ns               # noqa: E402
import subscriber_notify as sn          # noqa: E402
import tools_news_summary_probe as P    # noqa: E402

# 지시문·길이 재확인 줄·모델·상한의 지문 — 10-13 실측 2차(10건 모두 붙음, 114~183자)로 정한 값. 운영자 대조 뒤 고정.
# LOCK_1013 = 두 문장 요약 요청의 구성(10-13 값 그대로 — 모든 기사가 이 요청을 받는다), LOCK = SK텔레콤 줄 호출까지(#324, 10-20 실측 D′ 뒤 고정).
LOCK_1013 = 'b8cd9d90ae65904c4cee7377c3799ade81e50dcb5272fa86468ad9d7344c817d'
LOCK = 'c9c14b37d4aa51a4c9f0422bf7d7cc87119fab0f84614c6db8b6314fc8ccba79'
BODY = '과학기술정보통신부는 13일 주파수 재할당 대가 산정 방안을 발표했다. ' * 40       # 1,500자를 넘는 본문
SKT_BODY = '과학기술정보통신부는 13일 SK텔레콤과 KT에 시정명령을 내렸다고 밝혔다. ' * 30    # SK텔레콤 언급 본문
TWO = '가는 이렇다. 나는 저렇다.'
LINE = 'SK텔레콤은 시정명령을 받았다.'


def _lock() -> str:
    blob = '\x1f'.join([ns.SUMMARY_MODEL, str(ns.SUMMARY_MAX_TOKENS), ns.SUMMARY_SYSTEM, ns.SUMMARY_TAIL])
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def _lock_skt() -> str:
    blob = '\x1f'.join([_lock(), ns.SKT_RE.pattern, str(ns.SKT_LINE_MAX_TOKENS), ns.SKT_LINE_SYSTEM, ns.SKT_LINE_TAIL, ns.SKT_LINE_LABEL])
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def _resp(text, stop='end_turn'):
    return SimpleNamespace(content=[SimpleNamespace(type='text', text=text)], stop_reason=stop, usage=None)


class _Client:
    """resp = 응답 하나(모든 호출에 같은 것) 또는 호출 순서대로의 목록(응답 대신 예외 객체를 넣으면 그 호출이 던진다)."""
    def __init__(self, resp=None, exc=None):
        self.calls, self._resp, self._exc = [], resp, exc
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        if self._exc:
            raise self._exc
        r = self._resp[len(self.calls) - 1] if isinstance(self._resp, list) else self._resp
        if isinstance(r, Exception):
            raise r
        return r


class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.ops = db, name, []

    def __getattr__(self, op):
        def rec(*a, **k):
            self.ops.append((op, a, k))
            return self
        return rec

    def execute(self):
        self.db.log.append((self.name, self.ops))
        if self.name in self.db.fail:
            raise RuntimeError(f'{self.name} down')
        if any(o[0] == 'upsert' for o in self.ops):
            rows = next(o[1][0] for o in self.ops if o[0] == 'upsert')
            return SimpleNamespace(data=[dict(r, id='id-' + r['url']) for r in rows])
        return SimpleNamespace(data=list(self.db.rows.get(self.name, [])))


class _Db:
    def __init__(self, rows=None, fail=()):
        self.rows, self.fail, self.log = rows or {}, set(fail), []

    def table(self, name):
        return _Q(self, name)

    def ops(self, name, op):
        return [ops for t, ops in self.log if t == name and any(o[0] == op for o in ops)]


def _quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return fn(*a, **k), buf.getvalue()


class TestPromptLocked(unittest.TestCase):
    def test_fingerprint(self):
        self.assertEqual(_lock(), LOCK_1013, '두 문장 요약의 지시문·상한은 10-13 고정본 그대로 — 고치려면 10건 재실측·운영자 대조')
        self.assertEqual(_lock_skt(), LOCK, 'SK텔레콤 줄 지시문을 고쳤으면 tools_news_summary_probe.py --grep로 언급 기사를 다시 재고 운영자 대조 뒤 지문을 바꾼다')

    def test_request_shape(self):
        kw = ns.request_kwargs('제목', '전자신문', BODY * 6)
        self.assertEqual(set(kw), {'model', 'max_tokens', 'system', 'messages', 'thinking'}, '샘플링 인자·도구·캐시 없음')
        self.assertEqual((kw['model'], kw['max_tokens']), ('claude-sonnet-5', ns.SUMMARY_MAX_TOKENS))
        self.assertEqual(kw['thinking'], {'type': 'disabled'}, 'Sonnet 5 비스트리밍은 추론을 끈다(지침 #120)')
        h = ns.request_kwargs('제목', '전자신문', BODY, model='claude-haiku-4-5-20251001')
        self.assertNotIn('thinking', h, '비교 실측용 Haiku 요청엔 추론 인자 없음')
        user = kw['messages'][0]['content']
        self.assertTrue(user.startswith('제목: 제목\n출처: 전자신문\n\n기사 원문:\n'))
        self.assertTrue(user.endswith('\n\n' + ns.SUMMARY_TAIL))
        body = user.split('기사 원문:\n', 1)[1][:-len('\n\n' + ns.SUMMARY_TAIL)]
        self.assertEqual(len(body), ns.SUMMARY_INPUT_MAX, '입력은 전문 앞 8,000자(공백 정리 뒤)')

    def test_no_sampling_params_in_sources(self):
        for mod in (ns, P):
            src = open(mod.__file__, encoding='utf-8').read()
            self.assertNotIn('temperature=', src)
        self.assertEqual(open(crawler.__file__, encoding='utf-8').read().count('temperature='), 1, '크롤러는 긴급도 콜 한 곳 그대로')

    def test_probe_sends_production_request(self):
        for body in (BODY, SKT_BODY):
            c1, c2 = _Client([_resp(TWO), _resp(LINE)]), _Client([_resp(TWO), _resp(LINE)])
            a = {'title': '제목', 'source': '출처', 'full': body}
            r1 = ns.news_tg_summary(c1, a['title'], a['source'], a['full'])
            r2 = P.probe_summary_call(c2, a)
            self.assertEqual(c1.calls, c2.calls, '실측 도구 = 운영 요청(언급 기사는 줄 호출까지)')
            self.assertEqual(len(c1.calls), 2 if body is SKT_BODY else 1)
            self.assertEqual((r1['text'], r1['skt']), (r2['text'], r2['skt']))


class TestSktLine(unittest.TestCase):
    """규칙 7(#324, 실측 D′) — 요약 요청은 모든 기사가 같고, 언급 기사만 요약 뒤 줄 호출 하나 더."""

    def test_summary_request_same_for_all(self):
        a, b = ns.request_kwargs('제목', '전자신문', BODY), ns.request_kwargs('SK텔레콤, 5G SA', '전자신문', SKT_BODY)
        self.assertEqual((a['system'], a['max_tokens']), (b['system'], b['max_tokens']))
        self.assertEqual(a['system'], ns.SUMMARY_SYSTEM)
        for kw in (a, b):
            self.assertTrue(kw['messages'][0]['content'].endswith('\n\n' + ns.SUMMARY_TAIL))
        self.assertNotIn('SK텔레콤', a['system'] + ns.SUMMARY_TAIL)

    def test_mentioned(self):
        for title, body in (('제목', SKT_BODY), ('SK텔레콤, 5G SA 상용화', BODY), ('SKT·KT 3G 종료', BODY),
                            ('제목', BODY + ' SK 텔레콤은 반대했다.'), ('제목', BODY + ' 에스케이텔레콤은 반대했다.'),
                            ('제목', BODY + ' SK Telecom said.')):
            self.assertTrue(ns.skt_mentioned(title, ns.input_text(body)), (title, body[-30:]))
        for body in (BODY + ' SK브로드밴드가 참여했다.', BODY + ' SK하이닉스·SK텔링크가 참여했다.', BODY + ' SK그룹 최태원 회장'):
            self.assertFalse(ns.skt_mentioned('제목', ns.input_text(body)), body[-30:])
        far = BODY * 6 + ' SK텔레콤도 참여했다.'                        # 8,000자 밖의 언급 — 모델이 못 보는 글
        self.assertGreater(len(far), ns.SUMMARY_INPUT_MAX)
        self.assertFalse(ns.skt_mentioned('제목', ns.input_text(far)), '언급 검사는 입력 앞 8,000자(모델이 보는 글)로만')

    def test_line_request_shape(self):
        kw = ns.skt_line_kwargs('제목', '전자신문', SKT_BODY, TWO)
        self.assertEqual(set(kw), {'model', 'max_tokens', 'system', 'messages', 'thinking'}, '샘플링 인자·도구·캐시 없음')
        self.assertEqual((kw['model'], kw['max_tokens'], kw['system'], kw['thinking']),
                         ('claude-sonnet-5', ns.SKT_LINE_MAX_TOKENS, ns.SKT_LINE_SYSTEM, {'type': 'disabled'}))
        user = kw['messages'][0]['content']
        self.assertTrue(user.startswith('제목: 제목\n출처: 전자신문\n\n이미 보낸 요약:\n' + TWO + '\n\n기사 원문:\n'))
        self.assertTrue(user.endswith('\n\n' + ns.SKT_LINE_TAIL))
        self.assertEqual(user.split('기사 원문:\n', 1)[1][:-len('\n\n' + ns.SKT_LINE_TAIL)], ns.input_text(SKT_BODY), '원문은 요약과 같은 입력 글')

    def test_accept_line(self):
        self.assertEqual(ns.accept_line(' SK텔레콤은  시정명령을\n받았다. ', 'end_turn'), ('SK텔레콤은 시정명령을 받았다.', ''))
        self.assertEqual(ns.accept_line('없음', 'end_turn'), ('', '없음'))
        self.assertEqual(ns.accept_line('없음.', 'end_turn'), ('', '없음'))
        self.assertEqual(ns.accept_line('SK텔레콤은 시정명령을', 'max_tokens'), ('', '잘림'))
        self.assertEqual(ns.accept_line('SK텔레콤은 시정명령을', 'end_turn'), ('', '버림'))
        self.assertEqual(ns.accept_line('제공된 원문에는 SK텔레콤 내용이 없습니다.', 'end_turn'), ('', '버림'))
        self.assertEqual(ns.accept_line('SKT received an order 다.', 'end_turn'), ('', '버림'))

    def test_tg_text_and_format(self):
        self.assertEqual(ns.tg_text(TWO, ''), TWO)
        self.assertEqual(ns.tg_text(TWO, LINE), TWO + '\nSKT 언급: ' + LINE)
        self.assertEqual(ns.tg_text('', LINE), '', '요약이 없으면 줄도 없다')
        item = {'title': 'SKT <단독> 주파수', 'url': 'https://n/1', 'source': '전자신문'}
        base = sn.format_news_item(item)
        got = sn.format_news_item(dict(item, _summary=ns.tg_text(TWO, LINE)))
        self.assertEqual(got, base + f'\n<blockquote>{TWO}</blockquote>\n<blockquote>— SKT 언급: {LINE}</blockquote>')
        self.assertTrue(all(l.count('<blockquote>') == l.count('</blockquote>') for l in got.split('\n')))

    def test_two_calls_and_text(self):
        seen = []
        c = _Client([_resp(TWO), _resp(LINE)])
        r = ns.news_tg_summary(c, '제목', '출처', SKT_BODY, on_summary=seen.append)
        self.assertEqual((r['summary'], r['skt_line'], r['skt'], r['why']), (TWO, LINE, 'ok', ''))
        self.assertEqual(r['text'], TWO + '\nSKT 언급: ' + LINE)
        self.assertEqual(len(c.calls), 2)
        self.assertEqual(c.calls[1], ns.skt_line_kwargs('제목', '출처', SKT_BODY, TWO), '줄 요청은 방금 만든 요약을 담는다')
        self.assertEqual(seen, [TWO], '줄 호출 전에 요약만 먼저 넘긴다(예산 초과 대비)')
        c = _Client(_resp(TWO))
        r = ns.news_tg_summary(c, '제목', '출처', BODY)
        self.assertEqual((len(c.calls), r['text'], r['skt'], r['skt_line']), (1, TWO, '', ''), '언급 없는 기사는 호출 하나')

    def test_line_fail_open(self):
        for second, skt in ((_resp('없음'), '없음'), (_resp('SK텔레콤은 시정명령을', 'max_tokens'), '잘림'),
                            (_resp('통신사가 받았다'), '버림'), (RuntimeError('overloaded'), '실패: overloaded')):
            r = ns.news_tg_summary(_Client([_resp(TWO), second]), '제목', '출처', SKT_BODY)
            self.assertEqual((r['summary'], r['text'], r['skt_line'], r['why']), (TWO, TWO, '', ''), skt)
            self.assertEqual(r['skt'], skt)
        r = ns.news_tg_summary(_Client([_resp('없음'), _resp(LINE)]), '제목', '출처', SKT_BODY)
        self.assertEqual((r['summary'], r['text'], r['skt'], r['why']), ('', '', '', '본문 아님'), '요약이 없으면 줄 호출도 없다')


class TestAccept(unittest.TestCase):
    def test_accepts_two_sentences(self):
        self.assertEqual(ns.accept('  과기정통부는 방안을 발표했다.\n 의견수렴을 거쳐 확정할 예정이다. ', 'end_turn'),
                         '과기정통부는 방안을 발표했다. 의견수렴을 거쳐 확정할 예정이다.')

    def test_rejects(self):
        for text, stop in (('과기정통부는 방안을 발표했다. 의견수렴을 거쳐', 'max_tokens'),   # 잘림
                           ('과기정통부는 방안을 발표했다. 의견수렴을 거쳐', 'end_turn'),      # 「다.」로 안 끝남
                           ('과기정통부는 방안을 발표했다.', 'max_tokens'),
                           ('없음', 'end_turn'),
                           ('제공된 원문에는 기사 내용이 포함되어 있지 않습니다.', 'end_turn'),   # 메타 응답(#99 꼴)
                           ('이 기사를 요약하면 다음과 같다.', 'end_turn'),
                           ('I cannot summarize this article because 다.', 'end_turn'),
                           ('', 'end_turn'), (None, 'refusal')):
            self.assertEqual(ns.accept(text, stop), '', (text, stop))


class TestCall(unittest.TestCase):
    def test_short_body_no_call(self):
        c = _Client(_resp('x다.'))
        r = ns.news_tg_summary(c, '제목', '출처', '짧은 본문')
        self.assertEqual((r['summary'], r['why'], c.calls), ('', '본문 없음', []))

    def test_failure_and_none(self):
        r = ns.news_tg_summary(_Client(exc=RuntimeError('overloaded')), '제목', '출처', BODY)
        self.assertEqual(r['summary'], '')
        self.assertTrue(r['why'].startswith('실패'))
        r = ns.news_tg_summary(_Client(_resp('없음')), '제목', '출처', BODY)
        self.assertEqual((r['summary'], r['why']), ('', '본문 아님'))
        r = ns.news_tg_summary(_Client(_resp('가는 이렇다. 나는', 'max_tokens')), '제목', '출처', BODY)
        self.assertEqual((r['summary'], r['why']), ('', '버림'))

    def test_ok(self):
        r = ns.news_tg_summary(_Client(_resp('가는 이렇다. 나는 저렇다.')), '제목', '출처', BODY)
        self.assertEqual((r['summary'], r['why']), ('가는 이렇다. 나는 저렇다.', ''))


class TestFormat(unittest.TestCase):
    ITEM = {'title': 'SKT <단독> 주파수', 'url': 'https://n/1?a=1&b=2', 'source': '전자신문', '_related': 2}

    def test_without_summary_unchanged(self):
        base = sn.format_news_item(self.ITEM)
        self.assertEqual(base, '<a href="https://n/1?a=1&amp;b=2">SKT &lt;단독&gt; 주파수</a> <i>(관련 보도 2건)</i>\n   <i>전자신문</i>')
        for s in ('', '   ', None):
            self.assertEqual(sn.format_news_item(dict(self.ITEM, _summary=s)), base)

    def test_with_summary_blockquote_line(self):
        base = sn.format_news_item(self.ITEM)
        got = sn.format_news_item(dict(self.ITEM, _summary='A&B는 <발표>했다.   다음 달 시행한다.'))
        self.assertEqual(got, base + '\n<blockquote>A&amp;B는 &lt;발표&gt;했다. 다음 달 시행한다.</blockquote>')
        self.assertTrue(all(l.count('<blockquote>') == l.count('</blockquote>') for l in got.split('\n')),
                        '줄 단위 분할(splitByLines)이 태그를 자르지 않게 한 줄 안에서 열고 닫는다')

    def test_queue_rows_carry_summary(self):
        it = dict(self.ITEM, _summary='가는 이렇다. 나는 저렇다.')
        row = sn.news_row('t:1', '긴급', it)
        self.assertIn('<blockquote>가는 이렇다. 나는 저렇다.</blockquote>', row['html'])
        self.assertEqual(set(row), {'topic', 'audience', 'level', 'news_url', 'tags', 'html'}, '행 키 집합 그대로')


class TestBodyCut(unittest.TestCase):
    def _fetch(self, html, url='https://example.com/a'):
        class _R:
            text = html
            encoding = 'utf-8'

            def raise_for_status(self):
                pass
        with mock.patch.object(crawler, '_http_get', lambda u, timeout=8: _R()):
            return crawler.fetch_article_body(url, 'example')[0]

    def test_returns_full_text(self):
        body = self._fetch('<html><body><div class="article-body">' + BODY + '</div></body></html>')
        self.assertGreater(len(body), crawler.BODY_STORE_MAX)
        self.assertTrue(body.startswith('과학기술정보통신부는'))

    def test_refetch_cuts_at_store_max(self):
        src = open(os.path.join(ROOT, 'refetch_content.py'), encoding='utf-8').read()
        self.assertIn("body = (body or '')[:crawler.BODY_STORE_MAX]", src)

    def test_save_new_items_stores_1500_keeps_full_in_memory(self):
        pub = datetime.now(timezone(timedelta(hours=9))).isoformat()
        items = [{'title': '주파수 재할당', 'url': 'u1', 'published_at': pub, 'content': None},
                 {'title': '실패 기사', 'url': 'u2', 'published_at': pub, 'content': None}]
        full = BODY * 5                                                   # 8,000자를 넘는 전문
        db = _Db()
        crawler._FULL_BODIES['old'] = 'x' * 200                           # 지난 호출분은 비워진다
        with mock.patch.object(crawler, 'sb', db), \
                mock.patch.object(crawler, 'screen_news_items', lambda xs: xs), \
                mock.patch.object(crawler, 'fetch_article_body', lambda url, src='': ((full, '') if url == 'u1' else ('', ''))), \
                mock.patch.object(crawler.time, 'sleep', lambda s: None), \
                mock.patch.object(crawler, 'classify_urgency', lambda t, c='', s='': '보통'), \
                mock.patch.object(crawler, 'load_urgency_rules', lambda: []), \
                mock.patch.object(crawler, 'load_team_urgency_rules', lambda: []):
            out, _log = _quiet(crawler.save_new_items, [dict(i) for i in items], (set(), set()))
        up = db.ops('news_feed', 'upsert')[0]
        rows = next(o[1][0] for o in up if o[0] == 'upsert')
        self.assertEqual(len(rows[0]['content']), crawler.BODY_STORE_MAX, '저장 길이는 종전 1,500자')
        self.assertEqual(rows[0]['content'], full[:crawler.BODY_STORE_MAX])
        self.assertFalse(any(k.startswith('_') for r in rows for k in r), '메모리 전용 키는 upsert 행에 없다')
        self.assertEqual(crawler._FULL_BODIES, {'u1': full[:ns.SUMMARY_INPUT_MAX]})
        self.assertEqual([i['url'] for i in out], ['u1', 'u2'])
        crawler._FULL_BODIES.clear()


class TestAttach(unittest.TestCase):
    def setUp(self):
        crawler._FULL_BODIES.clear()
        crawler._SUMMARY_MEMO.clear()
        crawler._SUMMARY_FAILS[0] = 0

    tearDown = setUp

    def _items(self):
        return [{'title': 'A 기사', 'url': 'ua', 'source': '전자신문'}, {'title': 'B 기사', 'url': 'ub', 'source': '연합'}]

    def test_no_full_body_no_ai_no_db(self):
        items, db = self._items(), _Db()
        calls = []
        with mock.patch.object(crawler, 'sb', db), mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'), \
                mock.patch.object(ns, 'news_tg_summary', lambda *a: calls.append(a)):
            out, _ = _quiet(crawler.attach_tg_summaries, items)
        self.assertEqual(out, items, '요약 없으면 키도 없다(바이트 동일)')
        self.assertEqual((calls, db.log), ([], []))

    def test_generate_once_and_save(self):
        items, db = self._items(), _Db()
        crawler._FULL_BODIES['ua'] = BODY
        calls = []

        def fake(client, title, source, body, on_summary=None):
            calls.append(title)
            return {'summary': '가는 이렇다. 나는 저렇다.', 'why': ''}
        with mock.patch.object(crawler, 'sb', db), mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'), \
                mock.patch.object(ns, 'news_tg_summary', fake):
            out, log = _quiet(crawler.attach_tg_summaries, items)
            out2, _ = _quiet(crawler.attach_tg_summaries, [dict(items[0], _label='우리 팀 기준')])
        self.assertEqual(out[0]['_summary'], '가는 이렇다. 나는 저렇다.')
        self.assertNotIn('_summary', out[1], '전문 없는 기사는 생략(결정 2)')
        self.assertNotIn('_summary', items[0], '원본 dict 불변 — 보통 채널에 새지 않게')
        self.assertEqual(out2[0]['_summary'], out[0]['_summary'], '팀 경로도 같은 글')
        self.assertEqual(calls, ['A 기사'], '기사당 한 번')
        upd = db.ops('news_feed', 'update')
        self.assertEqual(len(upd), 1)
        self.assertIn(('update', ({'ai_summary': '가는 이렇다. 나는 저렇다.'},), {}), upd[0])
        self.assertIn(('eq', ('url', 'ua'), {}), upd[0])
        self.assertIn('[요약] 주요 뉴스 1건 — 요약 1건(저장 1)', log)

    def test_generate_stores_text_with_skt_line(self):
        items, db = self._items(), _Db()
        crawler._FULL_BODIES['ua'] = SKT_BODY

        def fake(client, title, source, body, on_summary=None):
            on_summary(TWO)
            return {'summary': TWO, 'text': ns.tg_text(TWO, LINE), 'why': '', 'skt': 'ok', 'skt_line': LINE}
        with mock.patch.object(crawler, 'sb', db), mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'), \
                mock.patch.object(ns, 'news_tg_summary', fake):
            out, log = _quiet(crawler.attach_tg_summaries, items)
        self.assertEqual(out[0]['_summary'], TWO + '\nSKT 언급: ' + LINE, '큐 글 = 요약 + 줄')
        upd = db.ops('news_feed', 'update')[0]
        self.assertIn(('update', ({'ai_summary': TWO + '\nSKT 언급: ' + LINE},), {}), upd, 'ai_summary도 줄까지(대시보드 둘째 글머리)')
        self.assertIn('SKT 줄 ok 1', log)

    def test_late_job_keeps_summary_only(self):
        """줄 호출이 예산을 넘겨도 on_summary로 먼저 넘긴 요약은 나간다(#324 partial)."""
        items = self._items()
        crawler._FULL_BODIES['ua'] = SKT_BODY
        import threading
        gate = threading.Event()

        def fake(client, title, source, body, on_summary=None):
            on_summary(TWO)
            gate.wait(5)                                   # 줄 호출이 오래 걸리는 꼴
            return {'summary': TWO, 'text': ns.tg_text(TWO, LINE), 'why': ''}
        try:
            with mock.patch.object(crawler, 'sb', _Db()), mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'), \
                    mock.patch.object(crawler, 'SUMMARY_BUDGET_S', 0.2), mock.patch.object(ns, 'news_tg_summary', fake):
                out, log = _quiet(crawler.attach_tg_summaries, items)
        finally:
            gate.set()
        self.assertEqual(out[0]['_summary'], TWO, '시간 초과여도 요약 두 문장은 붙는다')
        self.assertIn('요약 1건(저장 1) · SKT 줄 시간 초과 1', log)

    def test_reuse_db_for_rows_without_full_body(self):
        db = _Db({'news_feed': [{'url': 'ua', 'ai_summary': '저장된 요약이다. 둘째 문장이다.'}, {'url': 'ub', 'ai_summary': None}]})
        with mock.patch.object(crawler, 'sb', db), mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'):
            out, log = _quiet(crawler.attach_tg_summaries, self._items(), reuse_db=True)
        self.assertEqual(out[0]['_summary'], '저장된 요약이다. 둘째 문장이다.')
        self.assertNotIn('_summary', out[1])
        self.assertIn('저장된 요약 1건 다시 씀', log)
        self.assertEqual(db.ops('news_feed', 'update'), [], '저장본을 다시 쓰지 않는다')

    def test_lookup_failure_and_no_key_fail_open(self):
        db = _Db(fail={'news_feed'})
        with mock.patch.object(crawler, 'sb', db):
            out, log = _quiet(crawler.attach_tg_summaries, self._items(), reuse_db=True)
        self.assertEqual(out, self._items())
        self.assertIn('[요약] 저장된 요약 조회 실패', log)
        crawler._SUMMARY_MEMO.clear()
        crawler._FULL_BODIES.update({'ua': BODY, 'ub': BODY})
        with mock.patch.object(crawler, 'sb', _Db()), mock.patch.object(crawler, 'ANTHROPIC_API_KEY', ''):
            out, log = _quiet(crawler.attach_tg_summaries, self._items())
        self.assertEqual(out, self._items())
        self.assertIn('ANTHROPIC_API_KEY 없음 — 2건 제목만', log)

    def test_failures_stop_the_rest(self):
        items = [{'title': f'기사{i}', 'url': f'u{i}', 'source': 's'} for i in range(6)]
        for it in items:
            crawler._FULL_BODIES[it['url']] = BODY
        calls = []

        def fake(client, title, source, body, on_summary=None):
            calls.append(title)
            return {'summary': '', 'why': '실패: overloaded'}
        with mock.patch.object(crawler, 'sb', _Db()), mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'), \
                mock.patch.object(crawler, 'SUMMARY_WORKERS', 1), mock.patch.object(ns, 'news_tg_summary', fake):
            out, log = _quiet(crawler.attach_tg_summaries, items)
        self.assertEqual(len(calls), crawler.SUMMARY_FAIL_STOP, '실패 누적이면 남은 기사는 부르지 않는다')
        self.assertFalse(any('_summary' in o for o in out))
        self.assertIn('실패 누적 중단 4', log)

    def test_exception_inside_is_swallowed(self):
        crawler._FULL_BODIES['ua'] = BODY
        with mock.patch.object(crawler, '_fill_summary_memo', mock.Mock(side_effect=ValueError('뜻밖'))):
            out, log = _quiet(crawler.attach_tg_summaries, self._items())
        self.assertEqual(out, self._items())
        self.assertIn('[요약] 붙이기 실패(무시 — 제목만 보냄): 뜻밖', log)


class TestWiring(unittest.TestCase):
    """연결 자리 — 공통 큐는 억제 뒤·운영자 알림 뒤, 받는 단위는 긴급 채널만, 복원은 저장본만."""

    def test_call_sites(self):
        src = open(crawler.__file__, encoding='utf-8').read()
        main = src[src.index('def main():'):]
        self.assertLess(main.index('urgent_items = suppress_repeat_alerts(urgent_items)'),
                        main.index('send_telegram(urgent_items)'))
        self.assertLess(main.index('send_telegram(urgent_items)'),
                        main.index('queue_news_items(sb, attach_tg_summaries(urgent_items), trigger=False)'))
        ch = src[src.index('def _audience_channels('):src.index('def _deliver_now(')]
        self.assertIn("if ch == '긴급' and qitems:", ch)
        self.assertIn("attach_tg_summaries(qitems, reuse_db=(stage == 'late'))", ch)
        rs = src[src.index('def restore_raised_checks('):src.index('def run_audience_alerts(')]
        self.assertIn('items = attach_tg_summaries(items, reuse_db=True)', rs)
        self.assertNotIn('attach_tg_summaries', src[src.index('def send_telegram('):src.index('def send_urgent_email(')],
                         '운영자 봇 알림엔 붙이지 않는다(결정 4)')


if __name__ == '__main__':
    unittest.main()
