# -*- coding: utf-8 -*-
"""
팀 규칙 「문장 조건」 판정(#251, 설계안 §10-2) — crawler.py 쪽 테스트. 표준 unittest, **네트워크 0**.

  - 수집(save_new_items): AI 0회 — 낱말이 걸린 기사의 판정 대기 행만(본문 있으면 pending, 없으면 wait_body), 팀 결정은
    '판정 없음' 그대로, 문장 규칙이 없으면 종전과 같다 / 판정 기록은 새로 저장된 기사만·팀 행보다 먼저·fail-open
  - 대기 처리(같은 실행, 긴급 알림 뒤): 새것부터 / 판 바뀜·꺼짐 stale / 낱말 안 걸림 stale / 시도·기한 초과 failed /
    규칙을 읽은 뒤 생긴 행은 stale로 만들지 않음 / 젊은 본문 대기는 그대로 / 3시간 지난 본문 대기는 snippet·title로 /
    호출 통째 실패 = 시도 수 불변 + 이번 실행 판정 중단 / 20건 묶음·실행당 상한·시간 예산 / human 행 불가침 /
    rule 행은 그 자리에서 고침·새 결정은 넣기·결정 없음은 지움 / FK 오류 행만 빠지는 한 행씩 쓰기
  - stale 되살림: 지금 판 + 지금 낱말 → pending(created_at 지금) 뒤 판정 / 옛 판·낱말 안 걸림·failed는 그대로 /
    본문은 낱말이 걸린 것만 읽음 / 새것부터
  - 월 비용 알림: 팀·달마다 한 번(app_config 표시, 보낸 뒤에만 기록), 보내기 실패는 다음 실행에서 다시, 새 달은 다시
  - 실제 규칙 로더 배선(_TEAM_RULES_ENABLED·_RULES_LOADED_AT), _judge_sentence_batch 요청 모양·api_usage 라벨

Anthropic: crawler._judge_sentence_batch를 가짜로 바꾸고, crawler.anthropic.Anthropic도 가짜 생성자로 막는다
(tests는 .env를 읽으므로 실제 키가 있을 수 있다 — 실제 클라이언트가 만들어지는 길이 없어야 한다).
텔레그램: crawler.notify.send_telegram을 가짜로 바꾼다. Supabase: 아래 메모리 가짜 _MemDb.
"""
import contextlib
import inspect
import io
import json
import os
import re
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 실 DB 자격증명 없이 import (클라이언트 생성만, 접속 없음) — test_smoke.py와 같은 방식
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import crawler  # noqa: E402
import urgency_rules  # noqa: E402

_REAL_JUDGE = crawler._judge_sentence_batch
KST = timezone(timedelta(hours=9))

KEYS = {'rule_id', 'sentence_rev', 'team_id', 'status', 'verdict', 'reason', 'input_kind', 'model', 'cost_usd',
        'attempts', 'judged_at'}

COMMON = [{'id': 'c_witness', 'mode': 'min', 'level': '긴급', 'any_words': ['SKT'], 'and_any': [['국감'], ['증인']]}]
S_WIFI = {'id': 's_wifi', 'team_id': 7, 'position': 10, 'mode': 'set', 'level': '긴급',
          'any_words': ['공공와이파이', '지하철 와이파이'], 'and_any': [], 'none_words': ['홍보'], 'enabled': True,
          'sentence': '공공·지하철 와이파이 관련 문제를 제기하는 기사', 'sentence_rev': 1}
W_WIFI = {'id': 'w_wifi', 'team_id': 7, 'position': 20, 'mode': 'min', 'level': '보통',
          'any_words': ['와이파이'], 'and_any': [], 'none_words': [], 'enabled': True, 'sentence': '', 'sentence_rev': 0}
S_SPEC = {'id': 's_spec', 'team_id': 7, 'position': 30, 'mode': 'set', 'level': '긴급',
          'any_words': ['주파수'], 'and_any': [['재할당'], ['대가']], 'none_words': [], 'enabled': True,
          'sentence': '주파수 재할당 대가 산정이 통신사에 불리하다는 기사', 'sentence_rev': 0}
PLAIN = {5: [{'id': 't5_down', 'team_id': 5, 'mode': 'set', 'level': '참고', 'any_words': ['증인']},
             {'id': 't5_floor', 'team_id': 5, 'mode': 'min', 'level': '보통', 'any_words': ['로밍']}],
         8: [{'id': 't8_wifi', 'team_id': 8, 'mode': 'min', 'level': '긴급', 'any_words': ['와이파이'],
              'sentence': '', 'sentence_rev': 0}]}
BODY = '서울 지하철 공공와이파이가 잦은 끊김으로   이용자 불만이 커지고 있다.\n' * 12        # 공백 정리 전 ≈ 500자


def _ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ── 메모리 가짜 Supabase ─────────────────────────────────────────────────────────────────────────
class _MemDb:
    """표별 행을 들고 select(eq·in_·gte·or_·order·limit·range)·upsert(PK 병합 / ignore_duplicates면 무시)·update·delete를
    흉내 낸다. 모든 호출을 log에 남긴다. fail = 표 이름 또는 (표, 동작), fail_when = 쿼리 → bool(조건부 장애)."""
    PK = {'urgency_rule_verdicts': ('rule_id', 'sentence_rev', 'news_id'), 'team_urgency': ('news_id', 'team_id'),
          'app_config': ('key',)}

    def __init__(self, tables=None, fail=(), inserted_urls=None):
        self.tables = {k: [dict(r) for r in v] for k, v in (tables or {}).items()}
        self.fail = set(fail)
        self.fail_when = None
        self.inserted_urls = inserted_urls          # news_feed upsert 응답에 돌려줄 url(None = 전부 새 행)
        self.log = []

    def table(self, name):
        return _MemQ(self, name)

    def calls(self, name, op):
        return [e for e in self.log if e['table'] == name and e['op'] == op]

    def row(self, name, **key):
        return next((r for r in self.tables.get(name, []) if all(r.get(k) == v for k, v in key.items())), None)


class _MemQ:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self.op, self.payload, self.kw, self.cols = 'select', None, {}, '*'
        self.filters, self.orders, self.lim, self.rng = [], [], None, None

    def select(self, cols='*', **_k):
        self.cols = cols
        return self

    def eq(self, c, v):
        self.filters.append(('eq', c, v))
        return self

    def in_(self, c, vs):
        self.filters.append(('in', c, list(vs)))
        return self

    def gte(self, c, v):
        self.filters.append(('gte', c, v))
        return self

    def or_(self, expr):
        """PostgREST or 묶음 중 크롤러가 쓰는 꼴만 — 'and(col.eq.v,col.eq.v),and(…)' (값은 글자로 비교)."""
        groups = []
        for m in re.finditer(r'and\(([^()]*)\)', expr):
            conds = {}
            for part in m.group(1).split(','):
                col, op, val = part.split('.', 2)
                assert op == 'eq', part
                conds[col] = val
            groups.append(conds)
        self.filters.append(('or', groups, expr))
        return self

    def order(self, c, desc=False):
        self.orders.append((c, desc))
        return self

    def limit(self, n):
        self.lim = n
        return self

    def range(self, lo, hi):
        self.rng = (lo, hi)
        return self

    def upsert(self, rows, **kw):
        rows = rows if isinstance(rows, list) else [rows]
        self.op, self.payload, self.kw = 'upsert', [dict(r) for r in rows], dict(kw)
        return self

    def update(self, vals):
        self.op, self.payload = 'update', dict(vals)
        return self

    def delete(self):
        self.op = 'delete'
        return self

    def _ok(self, r):
        for kind, c, v in self.filters:
            x = None if kind == 'or' else r.get(c)
            if kind == 'eq' and x != v:
                return False
            if kind == 'in' and x not in v:
                return False
            if kind == 'gte' and (x is None or str(x) < str(v)):
                return False
            if kind == 'or' and not any(all(str(r.get(col)) == val for col, val in g.items()) for g in c):
                return False
        return True

    def execute(self):
        db = self.db
        db.log.append({'table': self.name, 'op': self.op, 'rows': self.payload, 'kw': self.kw,
                       'filters': list(self.filters), 'cols': self.cols, 'range': self.rng, 'orders': list(self.orders)})
        if self.name in db.fail or (self.name, self.op) in db.fail or (db.fail_when and db.fail_when(self)):
            raise RuntimeError(f'{self.name} {self.op} down')
        rows = db.tables.setdefault(self.name, [])
        if self.op == 'upsert':
            if self.name == 'news_feed':             # ON CONFLICT DO NOTHING + representation = 새 행만
                keep = db.inserted_urls
                out = [dict(r, id='id-' + r['url']) for r in self.payload if keep is None or r['url'] in keep]
                rows.extend(dict(r) for r in out)
                return mock.Mock(data=out)
            pk = _MemDb.PK[self.name]
            out = []
            for r in self.payload:
                cur = next((x for x in rows if all(x.get(k) == r.get(k) for k in pk)), None)
                if cur is None:
                    new = dict(r)
                    if self.name == 'urgency_rule_verdicts':
                        new.setdefault('created_at', datetime.now(timezone.utc).isoformat())   # 표 기본값 now()
                    rows.append(new)
                    out.append(dict(new))
                elif not self.kw.get('ignore_duplicates'):
                    cur.update(r)                    # 보낸 칸만 바뀐다(PostgREST merge-duplicates)
                    out.append(dict(cur))
            return mock.Mock(data=out)
        if self.op == 'update':
            hit = [r for r in rows if self._ok(r)]
            for r in hit:
                r.update(self.payload)
            return mock.Mock(data=[dict(r) for r in hit])
        if self.op == 'delete':
            gone = [r for r in rows if self._ok(r)]
            db.tables[self.name] = [r for r in rows if not self._ok(r)]
            return mock.Mock(data=gone)
        got = [dict(r) for r in rows if self._ok(r)]
        for c, desc in reversed(self.orders):
            got.sort(key=lambda r: (r.get(c) is None, str(r.get(c))), reverse=desc)
        if self.rng:
            got = got[self.rng[0]:self.rng[1] + 1]
        if self.lim is not None:
            got = got[:self.lim]
        return mock.Mock(data=got)


# ── 공통 바탕 ───────────────────────────────────────────────────────────────────────────────────
class _Base(unittest.TestCase):
    def setUp(self):
        self.db = _MemDb()
        self.judge_calls, self.clients, self.sent = [], [], []
        self.verdicts = {}            # 제목 → (해당 여부, 근거). 표에 없는 제목은 답에서 뺀다(= 호출은 됐는데 빠짐)
        self.cost_per_call = 0.004
        self.judge_none = False       # True = 호출 통째 실패(None)
        self.send_ok = True
        patches = [
            mock.patch.object(crawler, 'sb', self.db),
            mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'test-key'),
            mock.patch.object(crawler, 'TELEGRAM_CHAT_ID', 'chat-x'),
            mock.patch.object(crawler, 'SENTENCE_DB_RETRY_DELAY_S', 0),
            mock.patch.object(crawler.anthropic, 'Anthropic', self._fake_client),
            mock.patch.object(crawler, '_judge_sentence_batch', self._fake_judge),
            mock.patch.object(crawler.notify, 'send_telegram', self._fake_send),
            mock.patch.dict(crawler._TEAM_RULE_HITS, {}, clear=True),
            mock.patch.dict(crawler._URGENCY_SUMMARY, {}, clear=True),
            mock.patch.dict(crawler._SENTENCE_CANDS, {}, clear=True),
            mock.patch.dict(crawler._SENTENCE_ROWS, {}, clear=True),
            mock.patch.dict(crawler._SENTENCE_RUN_COST, {}, clear=True),
            mock.patch.dict(crawler._SENTENCE_RUN, {'judged': 0, 'nokey_logged': False, 'broken': False}, clear=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    # 가짜들 ------------------------------------------------------------------------------------
    def _fake_client(self, **kw):
        self.clients.append(kw)
        return 'fake-client'           # 실제 클라이언트는 절대 만들지 않는다(판정 함수도 가짜)

    def _fake_judge(self, client, sentence, rows):
        self.judge_calls.append({'client': client, 'sentence': sentence,
                                 'rows': [{k: r.get(k) for k in ('title', 'snippet', 'body')} for r in rows]})
        if self.judge_none:
            return None, 0.0
        out = {}
        for k, r in enumerate(rows, 1):
            v = self.verdicts.get(r.get('title'))
            if v is not None:
                out[k] = v
        return out, self.cost_per_call

    def _fake_send(self, text, **kw):
        self.sent.append({'text': text, 'kw': kw, 'db_log_len': len(self.db.log)})
        return self.send_ok

    # 도우미 ------------------------------------------------------------------------------------
    def quiet(self, fn, *a, **k):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = fn(*a, **k)
        return out, buf.getvalue()

    def grade(self, items, team, ai='참고', summaries=None):
        crawler._URGENCY_SUMMARY.update(summaries or {})
        return self.quiet(crawler.grade_urgency, items, COMMON, classify=lambda t, c, s: ai, team_rules=team)

    def grade_and_queue(self, items, team, ai='참고', summaries=None):
        self.grade(items, team, ai, summaries)
        return self.quiet(crawler.queue_new_sentence_candidates, items, team)


# ── 수집: AI 없이 판정 대기 행만 ───────────────────────────────────────────────────────────────────
class TestCollectionQueue(_Base):

    def test_no_sentence_rules_same_hits_and_zero_calls(self):
        """문장 규칙이 없으면 팀 적중이 옛 team_rule_decision과 같고, 대기 행 단계는 조회·호출·로그 0."""
        items = [{'title': 'SKT 국감 증인 채택', 'url': 'u1'},
                 {'title': '로밍 요금 인하', 'url': 'u2'},
                 {'title': '서울 공공와이파이 장애', 'url': 'u3'},
                 {'title': '기지국 소식', 'url': 'u4'}]
        stat, log = self.grade(items, PLAIN, ai='보통', summaries={'u4': '와이파이 요약'})
        want = {}
        for it in items:
            text = urgency_rules.rule_input_text(it['screen_text'], '')
            got = []
            for tid, rules in PLAIN.items():
                d = urgency_rules.team_rule_decision(rules, it['title'], text, it['urgency'])
                if d:
                    got.append({'team_id': tid, 'urgency': d['level'], 'rule_id': d['rule_id']})
            if got:
                want[it['url']] = got
        self.assertEqual(crawler._TEAM_RULE_HITS, want)
        self.assertEqual(set(stat), {'hits', 'changed', 'skipped_ai', 'team_hits'}, 'grade_urgency 반환 키 불변')
        self.assertIn('[팀 규칙] 적중 ', log)
        self.assertEqual(crawler._SENTENCE_CANDS, {})
        st, qlog = self.quiet(crawler.queue_new_sentence_candidates, items, PLAIN)
        self.assertEqual((st, qlog), ({}, ''))
        self.assertEqual((self.judge_calls, self.clients, self.db.log, crawler._SENTENCE_ROWS), ([], [], [], {}))
        self.assertEqual(len({frozenset(i) for i in items}), 1, '벌크 upsert 행 키 집합 동일')

    def test_candidates_collected_sentence_rule_not_hit_before_judging(self):
        items = [{'title': '서울 공공와이파이 장애 복구 지연', 'url': 'u1', 'content': BODY}]
        stat, _ = self.grade(items, {7: [S_WIFI, W_WIFI]}, ai='참고', summaries={'u1': '검색 요약'})
        self.assertEqual(crawler._TEAM_RULE_HITS['u1'], [{'team_id': 7, 'urgency': '보통', 'rule_id': 'w_wifi'}],
                         '판정 전 문장 규칙은 안 걸림 → 뒤 낱말 규칙')
        self.assertEqual(crawler._SENTENCE_CANDS['u1'],
                         [{'team_id': 7, 'rule_ids': ['s_wifi'], 'common': '참고', 'text': '검색 요약'}])
        self.assertFalse([k for k in items[0] if 'sentence' in k or 'team' in k], '후보는 item 키가 아니라 옆 dict(#82)')
        self.assertEqual(stat['team_hits'], {7: 1})

    def test_queue_makes_no_ai_calls_pending_or_wait_body(self):
        """수집 경로는 AI 0회 — 본문(100자 이상) 있으면 pending, 없으면 wait_body. 팀 결정은 '판정 없음' 그대로."""
        items = [{'title': '서울 공공와이파이 장애 복구 지연', 'url': 'u1', 'content': BODY},
                 {'title': '지하철 와이파이 먹통', 'url': 'u2', 'content': '짧은 글'},
                 {'title': '공공와이파이 끊김 불만', 'url': 'u3', 'content': '가' * 150}]      # 100~199자도 본문
        st, log = self.grade_and_queue(items, {7: [S_WIFI, W_WIFI]})
        self.assertEqual((self.judge_calls, self.clients, self.db.log), ([], [], []))
        self.assertEqual({u: [(r['rule_id'], r['status']) for r in rows] for u, rows in crawler._SENTENCE_ROWS.items()},
                         {'u1': [('s_wifi', 'pending')], 'u2': [('s_wifi', 'wait_body')], 'u3': [('s_wifi', 'pending')]})
        for rows in crawler._SENTENCE_ROWS.values():
            self.assertEqual(set(rows[0]), KEYS)
            self.assertEqual((rows[0]['verdict'], rows[0]['attempts'], rows[0]['sentence_rev']), (None, 0, 1))
        for u in ('u1', 'u2', 'u3'):
            self.assertEqual(crawler._TEAM_RULE_HITS[u], [{'team_id': 7, 'urgency': '보통', 'rule_id': 'w_wifi'}])
        self.assertEqual(st, {'cands': 3, 'pending': 2, 'wait': 1})
        self.assertIn('[문장 판정] 새 기사 후보 3건 → 대기 2건 · 본문 대기 1건 (판정은 긴급 알림 뒤 대기 처리에서)', log)
        self.assertEqual(crawler._SENTENCE_CANDS, {}, '처리한 후보는 비운다')

    def test_body_threshold_100(self):
        self.assertEqual(crawler.SENTENCE_BODY_MIN, 100, '수집 저장(③)·refetch_content 재수집 기준과 같다')
        self.assertEqual(crawler._sentence_body('가' * 99), '')
        self.assertEqual(crawler._sentence_body('  ' + '가' * 99 + '\n\n  '), '', '앞뒤 공백은 길이에 안 친다')
        self.assertEqual(crawler._sentence_body('가' * 100), '가' * 100)
        self.assertEqual(len(crawler._sentence_body('가 ' * 1000)), crawler.SENTENCE_BODY_CHARS)
        self.assertEqual(crawler._sentence_body(None), '')


# ── 판정 기록 저장 + save_new_items → 같은 실행의 대기 처리 ───────────────────────────────────────────
class TestSaveVerdictRows(_Base):

    def _row(self, status='pending'):
        return crawler._verdict_row('s_wifi', 1, 7, status)

    def test_rows_only_for_inserted_urls_uniform_keys(self):
        crawler._SENTENCE_ROWS.update({'u1': [self._row(), crawler._verdict_row('s_spec', 0, 7, 'wait_body')],
                                       'u2': [self._row()]})           # u2 = 이미 있던 기사(응답에 없음)
        n, log = self.quiet(crawler.save_sentence_verdict_rows, [{'id': 'n1', 'url': 'u1'}, {'id': 'n3', 'url': 'u3'}])
        self.assertEqual(n, 2)
        ups = self.db.calls('urgency_rule_verdicts', 'upsert')
        self.assertEqual(len(ups), 1)
        self.assertEqual(ups[0]['kw'], {'on_conflict': 'rule_id,sentence_rev,news_id', 'ignore_duplicates': True})
        self.assertEqual({frozenset(r) for r in ups[0]['rows']}, {frozenset(KEYS | {'news_id'})})
        self.assertEqual([r['news_id'] for r in ups[0]['rows']], ['n1', 'n1'])
        self.assertEqual(crawler._SENTENCE_RUN_COST, {}, '대기 행에는 비용이 없다')
        self.assertIn('[문장 판정] 기록 2건 저장(pending 1, wait_body 1)', log)
        self.assertEqual(crawler.sentence_verdict_rows(None), [])

    def test_save_chunks(self):
        crawler._SENTENCE_ROWS.update({f'u{i}': [self._row()] for i in range(3)})
        with mock.patch.object(crawler, 'SENTENCE_CHUNK', 2):
            n, _ = self.quiet(crawler.save_sentence_verdict_rows, [{'id': f'n{i}', 'url': f'u{i}'} for i in range(3)])
        self.assertEqual(n, 3)
        self.assertEqual([len(e['rows']) for e in self.db.calls('urgency_rule_verdicts', 'upsert')], [2, 1])

    def test_chunk_failure_falls_back_to_rows(self):
        """묶음이 실패하면 한 행씩 — 도중에 지워진 기사(FK 오류) 행만 빠진다."""
        crawler._SENTENCE_ROWS.update({f'u{i}': [self._row()] for i in range(3)})
        self.db.fail_when = lambda q: q.op == 'upsert' and any(r.get('news_id') == 'n1' for r in q.payload)
        n, log = self.quiet(crawler.save_sentence_verdict_rows, [{'id': f'n{i}', 'url': f'u{i}'} for i in range(3)])
        self.assertEqual(n, 2)
        self.assertEqual(sorted(r['news_id'] for r in self.db.tables['urgency_rule_verdicts']), ['n0', 'n2'])
        self.assertIn('일부 실패(무시)', log)

    def test_fail_open_and_empty(self):
        self.assertEqual(self.quiet(crawler.save_sentence_verdict_rows, [{'id': 'n1', 'url': 'u1'}])[0], 0)
        self.assertEqual(self.db.log, [], '판정 기록이 없으면 조회 0')
        crawler._SENTENCE_ROWS['u1'] = [self._row()]
        self.db.fail.add('urgency_rule_verdicts')
        n, log = self.quiet(crawler.save_sentence_verdict_rows, [{'id': 'n1', 'url': 'u1'}])
        self.assertEqual(n, 0)
        self.assertIn('[문장 판정] 저장 실패(무시)', log)
        self.assertEqual(len(self.db.calls('urgency_rule_verdicts', 'upsert')), crawler.SENTENCE_DB_RETRIES,
                         '쓰기는 재시도한다')
        n, log = self.quiet(crawler.save_sentence_verdict_rows, [])
        self.assertIn('[문장 판정] 기록 저장 0건', log)

    def _save_new_items(self, items, team, bodies):
        with mock.patch.object(crawler, 'screen_news_items', lambda xs: xs), \
                mock.patch.object(crawler, 'fetch_article_body', lambda url, src='': (bodies.get(url, ''), '')), \
                mock.patch.object(crawler.time, 'sleep', lambda s: None), \
                mock.patch.object(crawler, 'classify_urgency', lambda t, c='', s='': '참고'), \
                mock.patch.object(crawler, 'load_urgency_rules', lambda: COMMON), \
                mock.patch.object(crawler, 'load_team_urgency_rules', lambda: team):
            return self.quiet(crawler.save_new_items, [dict(i) for i in items], (set(), set()))

    def test_save_new_items_queues_then_open_pass_judges_same_run(self):
        pub = datetime.now(KST).isoformat()
        items = [{'title': '서울 공공와이파이 장애 복구 지연', 'url': 'u1', 'published_at': pub, 'content': None},
                 {'title': '지하철 와이파이 먹통 불만 폭주', 'url': 'u2', 'published_at': pub, 'content': None},
                 {'title': '기지국 소식', 'url': 'u3', 'published_at': pub, 'content': None}]
        self.verdicts = {items[0]['title']: (True, '문제 제기')}
        team = {7: [S_WIFI, W_WIFI]}
        crawler._URGENCY_SUMMARY.update({'u2': '지하철 와이파이 먹통 요약'})
        loaded_at = datetime.now(timezone.utc)
        (out, log) = self._save_new_items(items, team, {'u1': BODY})
        # ① 수집: AI 0회, 공통값 불변, 대기 행 → 팀 행 순서, 팀 결정은 '판정 없음'(w_wifi)
        self.assertEqual((self.judge_calls, self.clients), ([], []), '수집·알림 경로에서 AI를 부르지 않는다')
        self.assertEqual([i['urgency'] for i in out], ['참고', '참고', '참고'])
        nf = self.db.calls('news_feed', 'upsert')
        self.assertEqual(len({frozenset(r) for r in nf[0]['rows']}), 1, 'news_feed 벌크 upsert 키 집합 동일')
        self.assertFalse([k for r in nf[0]['rows'] for k in r if 'sentence' in k or 'team' in k or k.startswith('_')])
        self.assertEqual([(e['table'], e['op']) for e in self.db.log if e['op'] == 'upsert'],
                         [('news_feed', 'upsert'), ('urgency_rule_verdicts', 'upsert'), ('team_urgency', 'upsert')])
        vr = self.db.calls('urgency_rule_verdicts', 'upsert')[0]['rows']
        self.assertEqual([(r['news_id'], r['rule_id'], r['status']) for r in vr],
                         [('id-u1', 's_wifi', 'pending'), ('id-u2', 's_wifi', 'wait_body')])
        self.assertEqual(self.db.calls('team_urgency', 'upsert')[0]['rows'],
                         [{'news_id': 'id-u1', 'team_id': 7, 'urgency': '보통', 'source': 'rule', 'rule_id': 'w_wifi'},
                          {'news_id': 'id-u2', 'team_id': 7, 'urgency': '보통', 'source': 'rule', 'rule_id': 'w_wifi'}])
        self.assertIn('[문장 판정] 새 기사 후보 2건 → 대기 1건 · 본문 대기 1건', log)
        # ② 같은 실행의 대기 처리(알림 뒤): 규칙을 읽은 뒤 생긴 행이지만 사본과 맞으므로 판정 → 팀 행을 그 자리에서 고침
        with mock.patch.object(crawler, 'load_team_urgency_rules', lambda: team), \
                mock.patch.object(crawler, '_TEAM_RULES_ENABLED', {'s_wifi': S_WIFI, 'w_wifi': W_WIFI}), \
                mock.patch.object(crawler, '_RULES_LOADED_AT', loaded_at):
            _, log2 = self.quiet(crawler.process_open_sentence_verdicts)
        self.assertEqual([[r['title'] for r in c['rows']] for c in self.judge_calls], [[items[0]['title']]])
        v1 = self.db.row('urgency_rule_verdicts', news_id='id-u1')
        self.assertEqual((v1['status'], v1['verdict'], v1['input_kind']), ('done', True, 'body'))
        self.assertEqual(self.db.row('urgency_rule_verdicts', news_id='id-u2')['status'], 'wait_body')
        upd = self.db.calls('team_urgency', 'update')
        self.assertEqual(len(upd), 1)
        self.assertEqual(upd[0]['rows'], {'urgency': '긴급', 'rule_id': 's_wifi'})
        self.assertEqual(set(upd[0]['filters']), {('eq', 'news_id', 'id-u1'), ('eq', 'team_id', 7), ('eq', 'source', 'rule')})
        self.assertEqual(self.db.calls('team_urgency', 'delete'), [], '지웠다 넣지 않는다')
        self.assertEqual(self.db.row('team_urgency', news_id='id-u1')['rule_id'], 's_wifi')
        self.assertIn('[문장 판정] 대기 처리 — 대기 2건 → 판정 1건(해당 1) · 본문 대기 유지 1건', log2)
        self.assertIn('팀 행 +0/~1/-0', log2)
        self.assertEqual(self.sent, [], '월 기준 아래 — 알림 없음')

    def test_save_new_items_only_inserted_articles_get_rows(self):
        pub = datetime.now(KST).isoformat()
        items = [{'title': '서울 공공와이파이 장애 복구 지연', 'url': 'u1', 'published_at': pub, 'content': None},
                 {'title': '공공와이파이 끊김 불만', 'url': 'u2', 'published_at': pub, 'content': None}]
        self.db.inserted_urls = {'u2'}                         # u1은 동시 실행이 먼저 넣었다
        self._save_new_items(items, {7: [S_WIFI, W_WIFI]}, {'u1': BODY, 'u2': BODY})
        vr = self.db.calls('urgency_rule_verdicts', 'upsert')[0]['rows']
        self.assertEqual([r['news_id'] for r in vr], ['id-u2'])
        self.assertEqual(self.judge_calls, [])


# ── 매 실행 대기 처리 ─────────────────────────────────────────────────────────────────────────────
def _vrow(nid, rid, rev, status, created, attempts=0):
    return {'rule_id': rid, 'sentence_rev': rev, 'news_id': nid, 'team_id': 7, 'status': status, 'verdict': None,
            'reason': '', 'input_kind': '', 'model': '', 'cost_usd': 0, 'attempts': attempts,
            'requested_by': 'user-1', 'created_at': created, 'judged_at': None}


def _news(nid, title, content=None, screen_text=None, summary=None, urgency='참고'):
    return {'id': nid, 'url': 'https://x/' + nid, 'title': title, 'content': content, 'screen_text': screen_text,
            'summary': summary, 'urgency': urgency}


class TestOpenPass(_Base):
    ENABLED = {'s_wifi': S_WIFI, 'w_wifi': W_WIFI, 's_spec': S_SPEC}
    TEAM = {7: [S_WIFI, W_WIFI, S_SPEC]}

    def setUp(self):
        super().setUp()
        self.load_calls = []
        for p in (mock.patch.object(crawler, '_TEAM_RULES_ENABLED', dict(self.ENABLED)),
                  mock.patch.object(crawler, '_RULES_LOADED_AT', datetime.now(timezone.utc)),
                  mock.patch.object(crawler, 'load_team_urgency_rules', self._load_team)):
            p.start()
            self.addCleanup(p.stop)

    def _load_team(self):
        self.load_calls.append(1)
        return self.TEAM

    def run_pass(self):
        return self.quiet(crawler._process_open_sentence_rows)

    def v(self, nid):
        return self.db.row('urgency_rule_verdicts', news_id=nid)

    def _stale_queries(self):
        return [e for e in self.db.log if e['table'] == 'urgency_rule_verdicts' and e['op'] == 'select'
                and ('eq', 'status', 'stale') in e['filters']]

    def _news_selects(self):
        return [e for e in self.db.log if e['table'] == 'news_feed' and e['op'] == 'select']

    def test_full_pass(self):
        self.db.tables.update({
            'urgency_rule_verdicts': [
                _vrow('n1', 's_wifi', 1, 'pending', _ago(1)),                 # 본문 있음 → body
                _vrow('n2', 's_wifi', 1, 'wait_body', _ago(4)),               # 3시간 지남·본문 없음 → snippet
                _vrow('n3', 's_wifi', 1, 'wait_body', _ago(1)),               # 아직 본문 대기 → 그대로
                _vrow('n4', 's_wifi', 0, 'pending', _ago(1)),                 # 옛 판 → stale
                _vrow('n5', 's_wifi', 1, 'pending', _ago(1), attempts=3),     # 시도 초과 → failed
                _vrow('n6', 's_wifi', 1, 'pending', _ago(24 * 4)),            # 3일 초과 → failed
                _vrow('n7', 's_gone', 0, 'pending', _ago(1)),                 # 규칙 꺼짐·없음 → stale
                _vrow('n8', 's_wifi', 1, 'wait_body', _ago(5)),               # 요약도 없음 → title
                _vrow('n9', 's_wifi', 1, 'pending', _ago(1)),                 # 낱말이 이제 안 걸림 → stale
                _vrow('n10', 's_spec', 0, 'pending', _ago(1)),                # 거짓 → rule 행 삭제
            ],
            'news_feed': [
                _news('n1', '서울 공공와이파이 장애 복구 지연', content=BODY),
                _news('n2', '지하철 와이파이 먹통 불만', screen_text='지하철 와이파이가 또 끊겼다는 민원'),
                _news('n3', '공공와이파이 확충 발표', content='짧다'),
                _news('n4', '공공와이파이 장애'), _news('n5', '공공와이파이 장애'), _news('n6', '공공와이파이 장애'),
                _news('n7', '공공와이파이 장애'),
                _news('n8', '공공와이파이 요금 논란'),
                _news('n9', '와이파이 소식'),
                _news('n10', '주파수 재할당 대가 산정 논란', content=BODY, urgency='보통'),
            ],
            'team_urgency': [
                {'news_id': 'n1', 'team_id': 7, 'urgency': '보통', 'source': 'rule', 'rule_id': 'w_wifi'},
                {'news_id': 'n2', 'team_id': 7, 'urgency': '참고', 'source': 'human', 'rule_id': None},
                {'news_id': 'n8', 'team_id': 7, 'urgency': '보통', 'source': 'rule', 'rule_id': 'w_wifi'},
                {'news_id': 'n10', 'team_id': 7, 'urgency': '긴급', 'source': 'rule', 'rule_id': 's_spec'},
            ],
        })
        self.verdicts = {'서울 공공와이파이 장애 복구 지연': (True, '장애 문제 제기'),
                         '지하철 와이파이 먹통 불만': (True, '먹통 불만'),
                         '공공와이파이 요금 논란': (False, '요금 이야기'),
                         '주파수 재할당 대가 산정 논란': (False, '')}
        st, log = self.run_pass()
        v = self.v
        self.assertEqual((v('n1')['status'], v('n1')['verdict'], v('n1')['input_kind'], v('n1')['attempts']),
                         ('done', True, 'body', 1))
        self.assertEqual(v('n1')['requested_by'], 'user-1', '갱신이 요청자 기록을 지우지 않는다')
        self.assertEqual((v('n2')['status'], v('n2')['input_kind']), ('done', 'snippet'))
        self.assertEqual((v('n8')['status'], v('n8')['verdict'], v('n8')['input_kind']), ('done', False, 'title'))
        self.assertEqual((v('n10')['status'], v('n10')['verdict']), ('done', False))
        self.assertEqual(v('n3')['status'], 'wait_body')
        self.assertEqual([v(n)['status'] for n in ('n4', 'n5', 'n6', 'n7', 'n9')],
                         ['stale', 'failed', 'failed', 'stale', 'stale'])
        self.assertEqual(v('n5')['attempts'], 3)
        ups = self.db.calls('urgency_rule_verdicts', 'upsert')
        self.assertEqual(len(ups), 1)
        self.assertEqual(ups[0]['kw'], {'on_conflict': 'rule_id,sentence_rev,news_id'}, '전체 행 갱신(무시 아님)')
        self.assertEqual({frozenset(r) for r in ups[0]['rows']}, {frozenset(KEYS | {'news_id'})})
        self.assertNotIn('n3', [r['news_id'] for r in ups[0]['rows']], '젊은 본문 대기 행은 건드리지 않는다')
        judged = {r['title']: r for c in self.judge_calls for r in c['rows']}
        self.assertEqual(judged['지하철 와이파이 먹통 불만']['snippet'], '지하철 와이파이가 또 끊겼다는 민원')
        self.assertEqual((judged['지하철 와이파이 먹통 불만']['body'], judged['공공와이파이 요금 논란']['snippet']), ('', ''))
        self.assertEqual(sorted(c['sentence'] for c in self.judge_calls), sorted([S_SPEC['sentence'], S_WIFI['sentence']]))
        # 팀 행: n1 rule 행을 그 자리에서 고침(w_wifi → s_wifi 긴급), n2 human 불가침, n8 이미 맞음, n10 결정 없음 → 삭제
        tu = {r['news_id']: r for r in self.db.tables['team_urgency']}
        self.assertEqual(tu['n1'], {'news_id': 'n1', 'team_id': 7, 'urgency': '긴급', 'source': 'rule', 'rule_id': 's_wifi'})
        self.assertEqual((tu['n2']['source'], tu['n2']['urgency']), ('human', '참고'))
        self.assertEqual(tu['n8']['rule_id'], 'w_wifi')
        self.assertNotIn('n10', tu)
        upd = self.db.calls('team_urgency', 'update')
        self.assertEqual([(u['rows'], sorted(u['filters'])) for u in upd],
                         [({'urgency': '긴급', 'rule_id': 's_wifi'},
                           sorted([('eq', 'news_id', 'n1'), ('eq', 'team_id', 7), ('eq', 'source', 'rule')]))])
        dels = self.db.calls('team_urgency', 'delete')
        self.assertEqual(len(dels), 1)
        self.assertIn(('eq', 'source', 'rule'), dels[0]['filters'])
        self.assertIn(('in', 'news_id', ['n10']), dels[0]['filters'])
        self.assertEqual(self.db.calls('team_urgency', 'upsert'), [], '새 결정이 없으면 넣기도 없다')
        self.assertIn('[문장 판정] 대기 처리 — 대기 10건 → 판정 4건(해당 2) · 본문 대기 유지 1건 · 판 바뀜·꺼짐 2건'
                      ' · 낱말 안 걸림 1건 · 실패 확정 2건 · 재시도 0건 · 다음 실행 0건 · 팀 행 +0/~1/-1', log)
        self.assertGreater(crawler._SENTENCE_RUN_COST.get(7, 0), 0)
        self.assertTrue(all(e['cols'] == 'id,title,screen_text,summary,content,urgency' for e in self._news_selects()))

    def test_open_rows_newest_first(self):
        """대기 행은 새것부터 — 지난 기사 요청이 밀려 있어도 이번 실행 새 기사의 대기 행이 창 안에서 먼저 판정된다."""
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('old', 's_wifi', 1, 'pending', _ago(20)),
                                      _vrow('new', 's_wifi', 1, 'pending', _ago(0.5))],
            'news_feed': [_news('old', '공공와이파이 장애 옛 기사', content=BODY),
                          _news('new', '공공와이파이 장애 새 기사', content=BODY)]})
        self.verdicts = {'공공와이파이 장애 옛 기사': (True, ''), '공공와이파이 장애 새 기사': (True, '')}
        with mock.patch.object(crawler, 'SENTENCE_OPEN_LIMIT', 1):
            self.run_pass()
        q = self.db.log[0]
        self.assertIn(('created_at', True), q['orders'])
        self.assertEqual((self.v('new')['status'], self.v('old')['status']), ('done', 'pending'))

    def test_collection_rows_judged_before_dashboard_backlog(self):
        """판정 순서(Fable 재검토 #251): 수집 경로 대기 행(requested_by null)이 대시보드 요청 밀림보다 먼저 — 새것부터라도 지난 기사
        요청이 더 새로우면 그 규칙 묶음이 실행당 상한을 다 써 다른 팀 새 기사(늦은 팀 알림)가 밀렸다."""
        dash = [_vrow(f'd{i}', 's_spec', 0, 'pending', _ago(0.1)) for i in range(3)]          # 대시보드 요청(더 새것)
        col = dict(_vrow('c1', 's_wifi', 1, 'pending', _ago(0.5)), requested_by=None)         # 수집 경로(더 옛것)
        self.db.tables.update({
            'urgency_rule_verdicts': dash + [col],
            'news_feed': [_news(f'd{i}', f'주파수 재할당 대가 논란 {i}', content=BODY) for i in range(3)]
                         + [_news('c1', '공공와이파이 장애 새 기사', content=BODY)]})
        self.verdicts = {f'주파수 재할당 대가 논란 {i}': (True, '') for i in range(3)}
        self.verdicts['공공와이파이 장애 새 기사'] = (True, '')
        with mock.patch.object(crawler, 'SENTENCE_PER_RUN_MAX', 2), \
                mock.patch.dict(crawler._LATE_ALERT_PAIRS, {}, clear=True):
            _, log = self.run_pass()
            self.assertEqual(list(crawler._LATE_ALERT_PAIRS.get(7, {})), ['c1'], '수집 경로 참 판정만 늦은 알림 후보')
        titles = [[r['title'] for r in c['rows']] for c in self.judge_calls]
        self.assertEqual((titles[0], len(titles), len(titles[1])), (['공공와이파이 장애 새 기사'], 2, 1))
        self.assertTrue(titles[1][0].startswith('주파수 재할당 대가 논란'))
        self.assertEqual(self.v('c1')['status'], 'done')
        self.assertEqual(sorted(self.v(f'd{i}')['status'] for i in range(3)), ['done', 'pending', 'pending'])
        self.assertIn('다음 실행 2건', log)

    # ── 판 올림 재요청(Fable 재검토 #251) — 문장을 고쳐 판이 오른 규칙: 옛 판 기사 중 지금 판 행이 없고 지금 낱말이 걸리는 기사에
    #    지금 판 대기 행(requested_by 표식)을 넣고 같은 실행에서 판정한다(브라우저 재적용이 못 본 기사: 페이지 연 뒤 수집·규칙 사본 경쟁)
    def _edited(self, hours_ago, base=S_WIFI):
        r = dict(base, updated_at=_ago(hours_ago))
        crawler._TEAM_RULES_ENABLED[r['id']] = r
        self.TEAM = {7: [r if x['id'] == r['id'] else x for x in self.TEAM[7]]}
        return r

    @staticmethod
    def _done(nid, rev, hours_ago, verdict=True, rid='s_wifi'):
        return dict(_vrow(nid, rid, rev, 'done', _ago(hours_ago)), verdict=verdict, requested_by=None)

    def _catchup_queries(self, rid):
        return [e for e in self.db.log if e['table'] == 'urgency_rule_verdicts' and e['op'] == 'select'
                and ('eq', 'rule_id', rid) in e['filters'] and any(f[0] == 'gte' for f in e['filters'])]

    def test_old_rev_articles_requeued_and_judged_no_late_alert(self):
        self._edited(1)
        self.db.tables.update({
            'urgency_rule_verdicts': [
                self._done('n1', 0, 2),                                        # 옛 판만 → 재요청
                self._done('n2', 0, 2), self._done('n2', 1, 1),                # 지금 판 있음 → 없음
                self._done('n3', 0, 24 * 5),                                   # 기간 밖 → 없음
                self._done('n4', 0, 2),                                        # 낱말 이제 안 걸림 → 없음
                dict(_vrow('n5', 's_wifi', 0, 'stale', _ago(2)), requested_by=None),   # 옛 판 stale도 대상
            ],
            'news_feed': [_news('n1', '공공와이파이 장애 A', content=BODY), _news('n2', '공공와이파이 장애 B', content=BODY),
                          _news('n3', '공공와이파이 장애 C', content=BODY), _news('n4', '와이파이 소식', content=BODY),
                          _news('n5', '지하철 와이파이 먹통', content=BODY)]})
        self.verdicts = {'공공와이파이 장애 A': (True, '장애'), '지하철 와이파이 먹통': (False, '안내')}
        with mock.patch.dict(crawler._LATE_ALERT_PAIRS, {}, clear=True):
            _, log = self.run_pass()
            self.assertEqual(crawler._LATE_ALERT_PAIRS, {}, '재요청 판정은 늦은 팀 알림 후보가 아니다(requested_by 표식)')
        new = {v['news_id']: v for v in self.db.tables['urgency_rule_verdicts'] if v['sentence_rev'] == 1}
        self.assertEqual(sorted(new), ['n1', 'n2', 'n5'])
        self.assertEqual((new['n1']['status'], new['n1']['verdict'], new['n1']['input_kind'], new['n1']['requested_by']),
                         ('done', True, 'body', crawler.SENTENCE_REQUEUE_BY))
        self.assertEqual((new['n5']['status'], new['n5']['verdict']), ('done', False))
        self.assertEqual(new['n2']['requested_by'], None, '이미 있던 지금 판 행은 그대로')
        ins = self.db.calls('urgency_rule_verdicts', 'upsert')[0]
        self.assertEqual(ins['kw'], {'on_conflict': 'rule_id,sentence_rev,news_id', 'ignore_duplicates': True})
        self.assertEqual(len({frozenset(r) for r in ins['rows']}), 1, '재요청 행 키 집합 동일')
        light = self._news_selects()[0]
        self.assertEqual((light['cols'], ('in', 'id', ['n1', 'n4', 'n5']) in light['filters']),
                         ('id,title,screen_text,summary', True), '본문 없이 지금 판 행이 없는 옛 판 기사만 읽는다')
        self.assertEqual([[r['title'] for r in c['rows']] for c in self.judge_calls],
                         [['공공와이파이 장애 A', '지하철 와이파이 먹통']])
        tu = {r['news_id']: r for r in self.db.tables['team_urgency']}
        self.assertEqual((tu['n1']['rule_id'], tu['n1']['urgency']), ('s_wifi', '긴급'))
        self.assertIn('[문장 판정] 판 올림 재요청 2건(1규칙)', log)
        self.assertIn('판 올림 재요청 2건', log.split('대기 처리 —')[1])

    def test_no_catchup_unless_recently_edited_sentence_rule_with_rev(self):
        self._edited(24 * 5)                                   # 문장 고친 지 5일 — 대상 아님
        self._edited(1, base=S_SPEC)                           # 판 0 — 대상 아님
        self.db.tables.update({'urgency_rule_verdicts': [self._done('n1', 0, 2), self._done('n2', 0, 2, rid='s_spec')],
                               'news_feed': [_news('n1', '공공와이파이 장애 A', content=BODY),
                                             _news('n2', '주파수 재할당 대가 논란', content=BODY)]})
        self.run_pass()
        self.assertEqual((self._catchup_queries('s_wifi'), self._catchup_queries('s_spec')), ([], []))
        self.assertEqual([v['sentence_rev'] for v in self.db.tables['urgency_rule_verdicts']], [0, 0])
        self.assertEqual(self.judge_calls, [])

    def test_catchup_skips_article_already_open_and_query_failure_is_ignored(self):
        self._edited(1)
        self.db.tables.update({
            'urgency_rule_verdicts': [self._done('n1', 0, 2),
                                      dict(_vrow('n1', 's_wifi', 1, 'pending', _ago(0.1)), requested_by=None)],   # 브라우저·수집이 이미 넣음
            'news_feed': [_news('n1', '공공와이파이 장애 A', content=BODY)]})
        self.verdicts = {'공공와이파이 장애 A': (True, '')}
        _, log = self.run_pass()
        self.assertEqual(len(self._catchup_queries('s_wifi')), 1)
        self.assertEqual(self.db.calls('urgency_rule_verdicts', 'upsert')[0]['kw'].get('ignore_duplicates'), None,
                         '재요청 넣기 없음 — 첫 upsert가 판정 갱신')
        self.assertEqual([[r['title'] for r in c['rows']] for c in self.judge_calls], [['공공와이파이 장애 A']])
        self.assertNotIn('판 올림 재요청', log)
        # 조회 장애: 재요청만 건너뛰고(로그) 대기 행 처리는 계속
        self.db.tables['urgency_rule_verdicts'] = [self._done('n7', 0, 2),
                                                   dict(_vrow('n8', 's_wifi', 1, 'pending', _ago(0.1)), requested_by=None)]
        self.db.tables['news_feed'] = [_news('n7', '공공와이파이 장애 A', content=BODY), _news('n8', '공공와이파이 장애 A', content=BODY)]
        self.db.log, self.judge_calls = [], []
        self.db.fail_when = lambda q: q.name == 'urgency_rule_verdicts' and q.op == 'select' \
            and ('eq', 'rule_id', 's_wifi') in q.filters and any(f[0] == 'gte' for f in q.filters)
        _, log = self.run_pass()
        self.assertIn('[문장 판정] 판 올림 재요청 조회 실패(무시', log)
        self.assertEqual(self.v('n8')['status'], 'done')

    def test_sentence_only_rule_true_inserts_team_row(self):
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('n1', 's_spec', 0, 'pending', _ago(1))],
            'news_feed': [_news('n1', '주파수 재할당 대가 산정 논란', content=BODY, urgency='보통')]})
        self.verdicts = {'주파수 재할당 대가 산정 논란': (True, '대가 부담 비판')}
        _, log = self.run_pass()
        ins = self.db.calls('team_urgency', 'upsert')
        self.assertEqual(ins[0]['kw'], {'on_conflict': 'news_id,team_id', 'ignore_duplicates': True})
        self.assertEqual(self.db.tables['team_urgency'],
                         [{'news_id': 'n1', 'team_id': 7, 'urgency': '긴급', 'source': 'rule', 'rule_id': 's_spec'}])
        self.assertIn('팀 행 +1/~0/-0', log)

    def test_outage_circuit_breaker(self):
        """호출이 통째로 실패하면 시도 수를 올리지 않고 이번 실행의 남은 호출을 모두 멈춘다(로그 1줄)."""
        self.judge_none = True
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('n1', 's_wifi', 1, 'pending', _ago(1)),
                                      _vrow('n2', 's_spec', 0, 'pending', _ago(1), attempts=2)],
            'news_feed': [_news('n1', '서울 공공와이파이 장애 복구 지연', content=BODY),
                          _news('n2', '주파수 재할당 대가 산정 논란', content=BODY)]})
        _, log = self.run_pass()
        self.assertEqual(len(self.judge_calls), 1, '첫 호출 실패 뒤 다른 규칙 호출도 멈춘다')
        self.assertEqual(log.count('[문장 판정] AI 호출 실패 — 이번 실행 판정 중단(다음 실행에서 다시)'), 1)
        self.assertEqual([(self.v(n)['status'], self.v(n)['attempts']) for n in ('n1', 'n2')],
                         [('pending', 0), ('pending', 2)], '장애는 시도 수로 세지 않는다')
        self.assertEqual(self.db.calls('urgency_rule_verdicts', 'upsert'), [])
        self.assertIn('다음 실행 2건', log)
        self.assertTrue(crawler._SENTENCE_RUN['broken'])
        self.run_pass()                                           # 같은 실행 안 — 다시 부르지 않는다
        self.assertEqual(len(self.judge_calls), 1)

    def test_missing_id_counts_attempt_then_fails(self):
        """호출은 됐는데 답에 그 기사가 빠진 것만 시도로 센다 — 3번째면 failed."""
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('n1', 's_wifi', 1, 'pending', _ago(1), attempts=0),
                                      _vrow('n2', 's_wifi', 1, 'pending', _ago(1), attempts=2)],
            'news_feed': [_news('n1', '공공와이파이 장애 1', content=BODY), _news('n2', '공공와이파이 장애 2', content=BODY)]})
        _, log = self.run_pass()                                  # verdicts 비어 있음 = 답에서 둘 다 빠짐
        self.assertEqual((self.v('n1')['status'], self.v('n1')['attempts'], self.v('n1')['verdict']), ('pending', 1, None))
        self.assertEqual((self.v('n2')['status'], self.v('n2')['attempts']), ('failed', 3))
        self.assertEqual(self.db.calls('team_urgency', 'delete') + self.db.calls('team_urgency', 'upsert'), [])
        self.assertIn('재시도 1건', log)
        self.assertFalse(crawler._SENTENCE_RUN['broken'])

    def test_batches_of_twenty_and_cost_share(self):
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow(f'n{i:02d}', 's_spec', 0, 'pending', _ago(1)) for i in range(45)],
            'news_feed': [_news(f'n{i:02d}', f'주파수 재할당 대가 논란 {i}', content=BODY) for i in range(45)]})
        self.verdicts = {f'주파수 재할당 대가 논란 {i}': (True, '') for i in range(45)}
        self.run_pass()
        self.assertEqual([len(c['rows']) for c in self.judge_calls], [20, 20, 5])
        self.assertEqual(crawler._SENTENCE_RUN['judged'], 45)
        costs = sorted({r['cost_usd'] for r in self.db.tables['urgency_rule_verdicts']})
        self.assertEqual(costs, [0.0002, 0.0008], '호출 요금 / 그 호출의 기사 수')
        self.assertEqual(len(self.clients), 1)

    def test_per_run_cap(self):
        crawler._SENTENCE_RUN['judged'] = crawler.SENTENCE_PER_RUN_MAX - 1
        self.db.tables['urgency_rule_verdicts'] = [_vrow(f'n{i}', 's_wifi', 1, 'pending', _ago(1)) for i in range(3)]
        self.db.tables['news_feed'] = [_news(f'n{i}', f'공공와이파이 장애 {i}', content=BODY) for i in range(3)]
        self.verdicts = {f'공공와이파이 장애 {i}': (False, '') for i in range(3)}
        _, log = self.run_pass()
        self.assertEqual([len(c['rows']) for c in self.judge_calls], [1])
        self.assertIn('판정 1건', log)
        self.assertIn('다음 실행 2건', log)

    def test_time_budget_leaves_rows(self):
        self.db.tables['urgency_rule_verdicts'] = [_vrow('n1', 's_wifi', 1, 'pending', _ago(1))]
        self.db.tables['news_feed'] = [_news('n1', '공공와이파이 장애', content=BODY)]
        with mock.patch.object(crawler, 'SENTENCE_TIME_BUDGET_S', -1):
            _, log = self.run_pass()
        self.assertEqual(self.judge_calls, [])
        self.assertEqual((self.v('n1')['status'], self.v('n1')['attempts']), ('pending', 0))
        self.assertIn('다음 실행 1건', log)

    def test_no_key_leaves_rows(self):
        self.db.tables['urgency_rule_verdicts'] = [_vrow('n1', 's_wifi', 1, 'pending', _ago(1))]
        self.db.tables['news_feed'] = [_news('n1', '공공와이파이 장애', content=BODY)]
        with mock.patch.object(crawler, 'ANTHROPIC_API_KEY', ''):
            _, log = self.run_pass()
        self.assertEqual((self.judge_calls, self.clients), ([], []))
        self.assertEqual(self.db.calls('urgency_rule_verdicts', 'upsert'), [])
        self.assertIn('다음 실행 1건', log)
        self.assertIn('ANTHROPIC_API_KEY 없음', log)

    def test_no_open_rows_single_query(self):
        """새 기사 없던 실행(규칙을 아직 안 읽음) + 대기 행 없음 = 조회 1번, 규칙도 되살림 조회도 없다."""
        with mock.patch.object(crawler, '_TEAM_RULES_ENABLED', None):
            st, log = self.run_pass()
        self.assertEqual((st, log), ({}, ''))
        self.assertEqual(len(self.db.log), 1)
        q = self.db.log[0]
        self.assertEqual((q['table'], q['op']), ('urgency_rule_verdicts', 'select'))
        self.assertIn(('in', 'status', ['pending', 'wait_body']), q['filters'])
        self.assertEqual(self.load_calls, [], '대기 행이 없으면 규칙도 읽지 않는다')

    def test_rules_loaded_no_open_rows_one_stale_query(self):
        """규칙을 이미 읽은 실행 + 켜진 문장 규칙 있음 = 되살림 조회 1번 더(지금 판 쌍·새것부터), 후보 없으면 조용히 끝."""
        st, log = self.run_pass()
        self.assertEqual((st, log), ({}, ''))
        self.assertEqual(len(self.db.log), 2)
        q = self._stale_queries()
        self.assertEqual(len(q), 1)
        self.assertIn(('or', [{'rule_id': 's_spec', 'sentence_rev': '0'}, {'rule_id': 's_wifi', 'sentence_rev': '1'}],
                       'and(rule_id.eq.s_spec,sentence_rev.eq.0),and(rule_id.eq.s_wifi,sentence_rev.eq.1)'),
                      q[0]['filters'], '낱말 규칙(w_wifi)은 빼고, 규칙마다 지금 판만')
        self.assertIn(('created_at', True), q[0]['orders'], '새것부터')

    def test_no_enabled_sentence_rules_no_stale_query(self):
        self.TEAM = {7: [W_WIFI]}
        with mock.patch.object(crawler, '_TEAM_RULES_ENABLED', {'w_wifi': W_WIFI}):
            st, _ = self.run_pass()
            self.assertEqual((st, len(self.db.log)), ({}, 1))
            self.db.tables['urgency_rule_verdicts'] = [_vrow('n1', 's_wifi', 1, 'pending', _ago(1))]  # 꺼진 규칙
            self.run_pass()
        self.assertEqual(self._stale_queries(), [])
        self.assertEqual(self.v('n1')['status'], 'stale')

    def test_rules_load_failure_leaves_rows(self):
        self.db.tables['urgency_rule_verdicts'] = [_vrow('n1', 's_wifi', 1, 'pending', _ago(1)),
                                                   _vrow('n2', 's_wifi', 1, 'stale', _ago(1))]
        with mock.patch.object(crawler, '_TEAM_RULES_ENABLED', None):
            _, log = self.run_pass()
        self.assertEqual(self.db.calls('urgency_rule_verdicts', 'upsert'), [], '일시 장애로 stale을 만들지 않는다')
        self.assertEqual(self._stale_queries(), [], '규칙 표 조회 실패면 되살림 조회도 없다')
        self.assertIn('처리 건너뜀', log)

    def test_team_format_error_rows_untouched(self):
        self.db.tables['urgency_rule_verdicts'] = [_vrow('n1', 's_wifi', 1, 'pending', _ago(1))]
        self.db.tables['news_feed'] = [_news('n1', '서울 공공와이파이 장애 복구 지연', content=BODY)]
        self.TEAM = {}                                          # 그 팀 규칙이 이번 실행에서 빠졌다(형식 오류)
        _, log = self.run_pass()
        self.assertEqual(self.db.calls('urgency_rule_verdicts', 'upsert'), [])
        self.assertEqual(self.judge_calls, [])
        self.assertIn('건너뜀 1건', log)

    def test_snapshot_race_rows_after_rule_load_never_staled(self):
        """이 실행이 규칙을 읽은 뒤에 생긴 요청은 사본이 '안 맞다'고 해도 stale로 만들지 않는다(다음 실행에서 본다).
        사본과 맞으면 그대로 판정한다(이번 실행 새 기사의 대기 행)."""
        loaded = datetime.now(timezone.utc) - timedelta(minutes=10)
        self.db.tables.update({
            'urgency_rule_verdicts': [
                _vrow('a', 's_wifi', 2, 'pending', _ago(1 / 60)),       # 사본 뒤 · 새 판(사본은 1) → 그대로
                _vrow('b', 's_wifi', 2, 'pending', _ago(1)),            # 사본 앞 · 판 다름 → stale
                _vrow('c', 's_wifi', 1, 'pending', _ago(1 / 60)),       # 사본 뒤 · 사본과 맞음 → 판정
                _vrow('d', 's_wifi', 1, 'pending', _ago(1 / 60)),       # 사본 뒤 · 낱말 안 걸림 → 그대로
                _vrow('e', 's_new', 0, 'pending', _ago(1 / 60)),        # 사본 뒤 · 사본에 없는 규칙 → 그대로
            ],
            'news_feed': [_news('a', '공공와이파이 장애'), _news('b', '공공와이파이 장애'),
                          _news('c', '공공와이파이 장애 새 기사', content=BODY), _news('d', '와이파이 소식', content=BODY),
                          _news('e', '공공와이파이 장애')]})
        self.verdicts = {'공공와이파이 장애 새 기사': (True, '')}
        with mock.patch.object(crawler, '_RULES_LOADED_AT', loaded):
            _, log = self.run_pass()
        self.assertEqual([self.v(n)['status'] for n in 'abcde'], ['pending', 'stale', 'done', 'pending', 'pending'])
        self.assertIn('건너뜀 3건', log)

    def test_process_runs_budget_even_if_pass_fails(self):
        calls = []
        with mock.patch.object(crawler, '_process_open_sentence_rows', lambda: 1 / 0), \
                mock.patch.object(crawler, '_sentence_budget_alert', lambda: calls.append(1)):
            _, log = self.quiet(crawler.process_open_sentence_verdicts)
        self.assertEqual(calls, [1])
        self.assertIn('[문장 판정] 대기 처리 실패(무시', log)

    # ── 쓰기 장애: FK(도중에 지워진 기사) 행만 빠진다 ──────────────────────────────────────────────
    def test_verdict_update_fk_row_skipped_others_saved(self):
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('n1', 's_wifi', 1, 'pending', _ago(1)),
                                      _vrow('gone', 's_wifi', 1, 'pending', _ago(1)),
                                      _vrow('n3', 's_wifi', 1, 'pending', _ago(1))],
            'news_feed': [_news('n1', '공공와이파이 장애 1', content=BODY), _news('gone', '공공와이파이 장애 2', content=BODY),
                          _news('n3', '공공와이파이 장애 3', content=BODY)]})
        self.verdicts = {f'공공와이파이 장애 {i}': (True, '') for i in (1, 2, 3)}
        self.db.fail_when = lambda q: (q.name == 'urgency_rule_verdicts' and q.op == 'upsert'
                                       and any(r.get('news_id') == 'gone' for r in q.payload))
        _, log = self.run_pass()
        self.assertEqual([self.v(n)['status'] for n in ('n1', 'gone', 'n3')], ['done', 'pending', 'done'])
        self.assertEqual(sorted(r['news_id'] for r in self.db.tables.get('team_urgency', [])), ['n1', 'n3'])
        self.assertIn('[문장 판정] 대기 행 갱신 일부 실패', log)

    def test_rewrite_team_rows_fk_per_row_and_retry(self):
        news = {n: _news(n, '주파수 재할당 대가 산정 논란', content=BODY) for n in ('n1', 'gone', 'n3')}
        self.db.tables['urgency_rule_verdicts'] = [
            dict(_vrow(n, 's_spec', 0, 'done', _ago(1)), verdict=True) for n in ('n1', 'gone', 'n3')]
        self.db.fail_when = lambda q: (q.name == 'team_urgency' and q.op == 'upsert'
                                       and any(r.get('news_id') == 'gone' for r in q.payload))
        (res, log) = self.quiet(crawler._rewrite_team_rows, {7: {'n1', 'gone', 'n3'}}, news, self.TEAM)
        self.assertEqual(res, (2, 0, 0))
        self.assertEqual(sorted(r['news_id'] for r in self.db.tables['team_urgency']), ['n1', 'n3'])
        ups = self.db.calls('team_urgency', 'upsert')
        self.assertEqual([len(u['rows']) for u in ups], [3, 3, 1, 1, 1, 1], '묶음 2번 시도 → 한 행씩(실패 행만 2번)')
        self.assertIn('[문장 판정] 팀 행 쓰기 일부 실패', log)

    # ── stale 되살림 ─────────────────────────────────────────────────────────────────────────────
    def test_stale_current_rev_words_match_revived_and_judged(self):
        old = _ago(24 * 10)                                   # 10일 전 요청 — 되살린 뒤 3일 기한에 걸리면 안 된다
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('n1', 's_wifi', 1, 'stale', old, attempts=1)],
            'news_feed': [_news('n1', '서울 공공와이파이 장애 복구 지연', content=BODY)],
            'team_urgency': [{'news_id': 'n1', 'team_id': 7, 'urgency': '보통', 'source': 'rule', 'rule_id': 'w_wifi'}]})
        self.verdicts = {'서울 공공와이파이 장애 복구 지연': (True, '문제 제기')}
        st, log = self.run_pass()
        row = self.v('n1')
        self.assertEqual((row['status'], row['verdict'], row['attempts'], row['input_kind']), ('done', True, 2, 'body'))
        self.assertEqual(row['requested_by'], 'user-1')
        self.assertGreater(row['created_at'], old, '되살린 때부터 3일을 센다')
        ups = self.db.calls('urgency_rule_verdicts', 'upsert')
        self.assertEqual([u['rows'][0]['status'] for u in ups], ['pending', 'done'], '되살림을 먼저 저장하고 판정')
        self.assertEqual(set(ups[0]['rows'][0]), KEYS | {'news_id', 'created_at'})
        self.assertEqual(ups[0]['rows'][0]['attempts'], 1, '시도 수 유지')
        self.assertEqual(self.db.tables['team_urgency'],
                         [{'news_id': 'n1', 'team_id': 7, 'urgency': '긴급', 'source': 'rule', 'rule_id': 's_wifi'}])
        self.assertIn('대기 0건 → 판정 1건(해당 1)', log)
        self.assertIn(' · 되살림 1건', log)
        self.assertEqual(st['revived'], 1)

    def test_revival_reads_content_only_for_word_matches(self):
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('hit', 's_wifi', 1, 'stale', _ago(2)),
                                      _vrow('miss', 's_wifi', 1, 'stale', _ago(1))],
            'news_feed': [_news('hit', '서울 공공와이파이 장애', content=BODY), _news('miss', '와이파이 소식', content=BODY)]})
        self.verdicts = {'서울 공공와이파이 장애': (True, '')}
        self.run_pass()
        sels = self._news_selects()
        self.assertEqual([(e['cols'], [f for f in e['filters'] if f[0] == 'in']) for e in sels],
                         [('id,title,screen_text,summary', [('in', 'id', ['hit', 'miss'])]),
                          ('id,title,screen_text,summary,content,urgency', [('in', 'id', ['hit'])])],
                         '본문은 낱말이 걸린 후보만 읽는다')
        self.assertEqual((self.v('hit')['status'], self.v('miss')['status']), ('done', 'stale'))

    def test_revival_newest_first_under_limit(self):
        """낱말이 끝내 안 걸리는 옛 stale 행이 한도를 채워 새 후보를 밀어내지 않는다(새것부터)."""
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('old_miss', 's_wifi', 1, 'stale', _ago(30)),
                                      _vrow('new_hit', 's_wifi', 1, 'stale', _ago(1))],
            'news_feed': [_news('old_miss', '와이파이 소식'), _news('new_hit', '서울 공공와이파이 장애', content=BODY)]})
        self.verdicts = {'서울 공공와이파이 장애': (True, '')}
        with mock.patch.object(crawler, 'SENTENCE_OPEN_LIMIT', 1):
            self.run_pass()
        self.assertEqual(self.v('new_hit')['status'], 'done')

    def test_stale_old_rev_untouched(self):
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('n1', 's_wifi', 0, 'stale', _ago(1))],       # 지금 판은 1
            'news_feed': [_news('n1', '서울 공공와이파이 장애 복구 지연', content=BODY)]})
        st, log = self.run_pass()
        self.assertEqual((st, log), ({}, ''))
        self.assertEqual(self.v('n1')['status'], 'stale')
        self.assertEqual([(e['table'], e['op']) for e in self.db.log],
                         [('urgency_rule_verdicts', 'select')] * 2, '옛 판은 조회에서 빠져 기사도 안 읽는다')
        self.assertEqual(self.judge_calls, [])

    def test_stale_words_no_longer_match_stays_stale(self):
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('n1', 's_wifi', 1, 'stale', _ago(1))],
            'news_feed': [_news('n1', '와이파이 소식', content=BODY)]})
        st, log = self.run_pass()
        self.assertEqual(log, '', '후보만 있고 하나도 안 걸리면 매 실행 같은 줄을 찍지 않는다')
        self.assertEqual(self.v('n1')['status'], 'stale')
        self.assertEqual((self.db.calls('urgency_rule_verdicts', 'upsert'), self.judge_calls), ([], []))
        self.assertEqual([e['cols'] for e in self._news_selects()], ['id,title,screen_text,summary'], '본문은 안 읽는다')

    def test_failed_rows_not_revived(self):
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('n1', 's_wifi', 1, 'failed', _ago(1), attempts=3)],
            'news_feed': [_news('n1', '서울 공공와이파이 장애 복구 지연', content=BODY)]})
        st, log = self.run_pass()
        self.assertEqual((st, log), ({}, ''))
        self.assertEqual(self.v('n1')['status'], 'failed')

    def test_stale_with_exhausted_attempts_becomes_failed(self):
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('n1', 's_wifi', 1, 'stale', _ago(1), attempts=3)],
            'news_feed': [_news('n1', '서울 공공와이파이 장애 복구 지연', content=BODY)]})
        _, log = self.run_pass()
        self.assertEqual((self.v('n1')['status'], self.v('n1')['attempts']), ('failed', 3))
        self.assertEqual(self.judge_calls, [])
        self.assertIn('실패 확정 1건', log)
        self.assertNotIn('되살림', log)

    def test_revived_rows_count_toward_cap_after_open_rows(self):
        crawler._SENTENCE_RUN['judged'] = crawler.SENTENCE_PER_RUN_MAX - 1
        old = _ago(24 * 10)
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('n1', 's_wifi', 1, 'pending', _ago(1)),
                                      _vrow('n2', 's_wifi', 1, 'stale', old)],
            'news_feed': [_news('n1', '공공와이파이 장애 1', content=BODY), _news('n2', '공공와이파이 장애 2', content=BODY)]})
        self.verdicts = {'공공와이파이 장애 1': (False, ''), '공공와이파이 장애 2': (True, '')}
        _, log = self.run_pass()
        self.assertEqual([[r['title'] for r in c['rows']] for c in self.judge_calls], [['공공와이파이 장애 1']],
                         '상한 1건은 대기 행이 먼저 쓴다')
        r2 = self.v('n2')
        self.assertEqual((r2['status'], r2['attempts']), ('pending', 0), '되살린 행은 대기로 남아 다음 실행에서 판정')
        self.assertGreater(r2['created_at'], old)
        self.assertIn('다음 실행 1건', log)
        self.assertIn(' · 되살림 1건', log)
        crawler._SENTENCE_RUN['judged'] = 0                        # 다음 실행: 옛 요청 시각 때문에 failed가 되지 않는다
        self.run_pass()
        self.assertEqual((self.v('n2')['status'], self.v('n2')['verdict']), ('done', True))

    def test_revival_save_failure_skips_judging(self):
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('n1', 's_wifi', 1, 'stale', _ago(1))],
            'news_feed': [_news('n1', '서울 공공와이파이 장애 복구 지연', content=BODY)]})
        self.db.fail_when = lambda q: q.op == 'upsert' and bool(q.payload) and 'created_at' in q.payload[0]
        self.verdicts = {'서울 공공와이파이 장애 복구 지연': (True, '')}
        _, log = self.run_pass()
        self.assertEqual(self.judge_calls, [], '되살림을 저장 못 하면 판정하지 않는다')
        self.assertEqual(self.v('n1')['status'], 'stale')
        self.assertIn('[문장 판정] 되살림 저장 실패', log)

    def test_stale_query_failure_does_not_block_open_rows(self):
        self.db.tables.update({
            'urgency_rule_verdicts': [_vrow('n1', 's_wifi', 1, 'pending', _ago(1))],
            'news_feed': [_news('n1', '서울 공공와이파이 장애 복구 지연', content=BODY)]})
        self.db.fail_when = lambda q: q.op == 'select' and ('eq', 'status', 'stale') in q.filters
        self.verdicts = {'서울 공공와이파이 장애 복구 지연': (True, '')}
        _, log = self.run_pass()
        self.assertIn('[문장 판정] 되살림 조회 실패', log)
        self.assertEqual(self.v('n1')['status'], 'done')


# ── 실제 규칙 로더 배선 ─────────────────────────────────────────────────────────────────────────
class TestLoaderWiring(_Base):
    """실제 _load_all_urgency_rules가 _TEAM_RULES_ENABLED(형식 검사 전 켜진 팀 규칙)와 _RULES_LOADED_AT을 채우고,
    형식 오류 팀의 대기 행은 stale이 되지 않는다(그 팀만 이번 실행에서 빠짐)."""

    def setUp(self):
        super().setUp()
        for name in ('_URGENCY_RULES', '_TEAM_URGENCY_RULES', '_TEAM_RULES_ENABLED', '_RULES_LOADED_AT'):
            p = mock.patch.object(crawler, name, None)
            p.start()
            self.addCleanup(p.stop)

    def test_loader_fills_enabled_and_timestamp_and_bad_team_rows_untouched(self):
        bad = {'id': 's9_bad', 'team_id': 9, 'position': 10, 'mode': 'max', 'level': '보통', 'any_words': ['와이파이'],
               'and_any': [], 'none_words': [], 'enabled': True, 'sentence': '와이파이 문제 기사', 'sentence_rev': 0}
        self.db.tables['urgency_rules'] = [dict(COMMON[0], team_id=None, position=10, enabled=True),
                                           dict(S_WIFI), dict(W_WIFI), bad]
        before = datetime.now(timezone.utc)
        _, log = self.quiet(crawler.load_team_urgency_rules)
        self.assertEqual(set(crawler._TEAM_RULES_ENABLED), {'s_wifi', 'w_wifi', 's9_bad'}, '형식 검사 전 켜진 팀 규칙 전부')
        self.assertEqual(set(crawler._TEAM_URGENCY_RULES), {7}, '형식 오류 팀 9는 이번 실행 판정에서 빠진다')
        self.assertTrue(before <= crawler._RULES_LOADED_AT <= datetime.now(timezone.utc))
        self.assertIn('[규칙] 팀 9 규칙 형식 오류', log)
        self.db.tables['urgency_rule_verdicts'] = [dict(_vrow('n1', 's9_bad', 0, 'pending', _ago(1)), team_id=9)]
        self.db.tables['news_feed'] = [_news('n1', '와이파이 먹통', content=BODY)]
        _, log2 = self.quiet(crawler._process_open_sentence_rows)
        self.assertEqual(self.db.row('urgency_rule_verdicts', news_id='n1')['status'], 'pending', 'stale로 굳히지 않는다')
        self.assertEqual(self.judge_calls, [])
        self.assertIn('건너뜀 1건', log2)
        self.assertEqual(len([e for e in self.db.log if e['table'] == 'urgency_rules']), 1, '규칙은 실행당 한 번 읽는다')


# ── 월 비용 알림(팀·달마다 한 번, app_config 표시) ─────────────────────────────────────────────────
class TestBudgetAlert(_Base):

    def setUp(self):
        super().setUp()
        self.db.tables['teams'] = [{'id': 7, 'name': '기술정책팀'}, {'id': 8, 'name': '경쟁제도팀'}]
        self.month = datetime.now(KST).strftime('%Y-%m')

    def _spend(self, *costs, team=7, judged_at=None):
        rows = self.db.tables.setdefault('urgency_rule_verdicts', [])
        for c in costs:
            rows.append({'rule_id': 's_wifi', 'sentence_rev': 1, 'news_id': f'n{len(rows)}', 'team_id': team,
                         'status': 'done', 'verdict': True, 'cost_usd': c,
                         'judged_at': judged_at or datetime.now(timezone.utc).isoformat()})

    def _marks(self):
        row = self.db.row('app_config', key='sentence_rule_budget_alerted')
        return json.loads(row['value']) if row else None

    def test_send_once_marker_after_success(self):
        self._spend(1.0, 0.95, 0.10)
        self._spend(5.0, judged_at=(datetime.now(timezone.utc) - timedelta(days=40)).isoformat())   # 지난달 — 빼고 센다
        crawler._SENTENCE_RUN_COST[7] = 0.10
        n, log = self.quiet(crawler._sentence_budget_alert)
        self.assertEqual(n, 1)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]['kw'], {'chat_id': 'chat-x'})
        self.assertEqual(self.sent[0]['text'],
                         '⚠️ 팀 AI 문장 판정 비용\n기술정책팀: 이번 달 $2.05 — 기준 $2.00를 넘었습니다(판정은 계속합니다).\n'
                         '낱말이 너무 넓은 규칙이 없는지 「긴급도 설정 → 우리 팀」에서 확인해 주세요.')
        self.assertEqual(self._marks(), {'7': self.month})
        mark_write = next(i for i, e in enumerate(self.db.log) if e['table'] == 'app_config' and e['op'] == 'upsert')
        self.assertGreater(mark_write, self.sent[0]['db_log_len'] - 1, '표시는 보낸 **뒤에** 쓴다')
        self.assertEqual(self.db.log[mark_write]['kw'], {'on_conflict': 'key'})
        self.assertIn('[문장 판정] 비용 기준 넘김', log)
        # 다음 실행: 이번 달 표시가 있으면 합계도 읽지 않고 보내지 않는다(판정은 계속)
        self._spend(0.5)
        crawler._SENTENCE_RUN_COST[7] = 0.5
        mark = len(self.db.log)
        n, _ = self.quiet(crawler._sentence_budget_alert)
        self.assertEqual((n, len(self.sent)), (0, 1))
        self.assertFalse([e for e in self.db.log[mark:] if e['table'] == 'urgency_rule_verdicts'])

    def test_send_failure_no_marker_then_retry_next_run(self):
        self._spend(2.5)
        crawler._SENTENCE_RUN_COST[7] = 0.1
        self.send_ok = False
        n, log = self.quiet(crawler._sentence_budget_alert)
        self.assertEqual((n, self._marks()), (0, None), '보내기 실패면 표시를 남기지 않는다')
        self.assertIn('실패(표시 없이 다음 실행에서 다시)', log)
        self.send_ok = True
        n, _ = self.quiet(crawler._sentence_budget_alert)
        self.assertEqual((n, len(self.sent), self._marks()), (1, 2, {'7': self.month}))

    def test_new_month_sends_again_per_team(self):
        self.db.tables['app_config'] = [{'key': 'sentence_rule_budget_alerted',
                                         'value': json.dumps({'7': '2000-01', '8': self.month})}]
        self._spend(2.5, team=7)
        self._spend(3.0, team=8)
        crawler._SENTENCE_RUN_COST.update({7: 0.1, 8: 0.1})
        n, _ = self.quiet(crawler._sentence_budget_alert)
        self.assertEqual(n, 1)
        self.assertIn('기술정책팀', self.sent[0]['text'])
        self.assertEqual(self._marks(), {'7': self.month, '8': self.month})

    def test_under_cap_no_send_no_marker(self):
        self._spend(1.0, 0.5)
        crawler._SENTENCE_RUN_COST[7] = 0.5
        self.assertEqual(self.quiet(crawler._sentence_budget_alert)[0], 0)
        self.assertEqual((self.sent, self._marks()), ([], None))

    def test_no_run_cost_no_queries(self):
        self._spend(3.0)
        self.assertEqual(self.quiet(crawler._sentence_budget_alert)[0], 0)
        self.assertEqual(self.db.log, [])

    def test_cap_from_app_config_and_invalid_marker(self):
        self.db.tables['app_config'] = [{'key': 'sentence_rule_budget_usd', 'value': ' 1 '},
                                        {'key': 'sentence_rule_budget_alerted', 'value': '표시 아님'}]
        self._spend(0.95, 0.10)
        crawler._SENTENCE_RUN_COST[7] = 0.10
        n, _ = self.quiet(crawler._sentence_budget_alert)
        self.assertEqual(n, 1)
        self.assertIn('기준 $1.00를 넘었습니다', self.sent[0]['text'])
        self.assertEqual(self._marks(), {'7': self.month})
        cfg_reads = [e for e in self.db.log if e['table'] == 'app_config' and e['op'] == 'select']
        self.assertEqual(len(cfg_reads), 1, '기준·표시를 한 번에 읽는다')
        self.db.tables['app_config'] = [{'key': 'sentence_rule_budget_usd', 'value': '없음'}]
        self.assertEqual(self.quiet(crawler._sentence_budget_config)[0], (crawler.SENTENCE_BUDGET_USD, {}))

    def test_config_read_failure_skips_this_run(self):
        self._spend(3.0)
        crawler._SENTENCE_RUN_COST[7] = 0.1
        self.db.fail.add(('app_config', 'select'))
        n, log = self.quiet(crawler._sentence_budget_alert)
        self.assertEqual((n, self.sent), (0, []), '표시를 못 읽은 채 보내면 같은 달에 두 번 갈 수 있다')
        self.assertIn('비용 알림 점검을 건너뜀', log)

    def test_month_sum_pages_past_1000_rows(self):
        self._spend(*([0.001] * 1500))
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        total = crawler._team_month_cost(7, since)
        self.assertAlmostEqual(total, 1.5, places=6)
        sel = self.db.calls('urgency_rule_verdicts', 'select')
        self.assertEqual([e['range'] for e in sel], [(0, 999), (1000, 1999)])


# ── _judge_sentence_batch 자체(가짜 클라이언트) ─────────────────────────────────────────────────────
class _FakeMessages:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.kw = resp, exc, None

    def create(self, **kw):
        self.kw = kw
        if self.exc:
            raise self.exc
        return self.resp


class _FakeClient:
    def __init__(self, **k):
        self.messages = _FakeMessages(**k)


def _resp(verdicts, in_tok=1000, out_tok=200, with_tool=True):
    blocks = [types.SimpleNamespace(type='text', text='')]
    if with_tool:
        blocks.append(types.SimpleNamespace(type='tool_use', input={'verdicts': verdicts}))
    return types.SimpleNamespace(content=blocks, usage=types.SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok))


class TestJudgeBatchCall(unittest.TestCase):

    def test_calls_messages_create_directly(self):
        """api_usage.install()은 messages.create를 **직접** 부른 함수 이름으로 비용 라벨을 만든다."""
        src = inspect.getsource(_REAL_JUDGE)
        code = src.split('"""')[-1]                               # 독스트링 뒤 코드만
        self.assertIn('client.messages.create(', code)
        self.assertNotIn('temperature', code)
        self.assertNotIn('cache_control', src)
        self.assertNotIn('with_retry', code, 'Anthropic 호출은 재시도로 감싸지 않는다(라벨·비용 두 배)')
        self.assertNotIn('with_retry', inspect.getsource(crawler._judge_jobs).split('"""')[-1])

    def test_request_shape_and_parse(self):
        client = _FakeClient(resp=_resp([{'id': 1, 'why': '  끊김   문제 제기 ', 'match': True},
                                         {'id': 2, 'why': 'x', 'match': 'true'},       # 참·거짓 아님 → 판정 못 함
                                         {'id': 9, 'why': 'x', 'match': False},        # 없는 번호
                                         {'id': 1, 'why': '중복', 'match': False}]))    # 같은 번호 두 번 → 처음 것
        rows = [{'title': ' 서울  공공와이파이 장애 ', 'snippet': '요약\n 한 줄', 'body': '본문 ' * 500},
                {'title': '제목 둘', 'snippet': '   ', 'body': ''}]
        with contextlib.redirect_stdout(io.StringIO()):
            out, cost = _REAL_JUDGE(client, '조건 문장 예', rows)
        self.assertEqual(out, {1: (True, '끊김 문제 제기')})
        self.assertAlmostEqual(cost, 1000 * 1e-6 + 200 * 5e-6)
        kw = client.messages.kw
        self.assertEqual(set(kw), {'model', 'max_tokens', 'system', 'tools', 'tool_choice', 'messages'},
                         'temperature류·캐시 없음(지침 do-not)')
        self.assertEqual((kw['model'], kw['max_tokens'], kw['system']), (crawler.SCREEN_MODEL, 4000, crawler.SENTENCE_RUBRIC))
        self.assertEqual(kw['tools'], [crawler.SENTENCE_TOOL])
        self.assertEqual(kw['tool_choice'], {'type': 'tool', 'name': 'record_condition_verdicts'})
        content = kw['messages'][0]['content']
        head = '조건 문장: «조건 문장 예»\n\n아래 기사 2건을 모두 판정해 record_condition_verdicts 도구로 기록하라.\n'
        self.assertTrue(content.startswith(head), content[:80])
        payload = json.loads(content[len(head):])
        self.assertEqual(payload[0]['title'], '서울 공공와이파이 장애')
        self.assertEqual(payload[0]['summary'], '요약 한 줄')
        self.assertEqual(payload[0]['body'], ' '.join(('본문 ' * 500).split())[:800])
        self.assertEqual(payload[1], {'id': 2, 'title': '제목 둘'}, '빈 요약·본문은 뺀다')

    def test_exception_and_no_tool(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(_REAL_JUDGE(_FakeClient(exc=RuntimeError('boom')), 's', [{'title': 't'}]), (None, 0.0))
            out, cost = _REAL_JUDGE(_FakeClient(resp=_resp([], with_tool=False)), 's', [{'title': 't'}])
        self.assertIsNone(out)
        self.assertGreater(cost, 0, '도구 없는 응답도 요금은 셈')
        self.assertIn('[문장 판정 오류] boom', buf.getvalue())
        self.assertIn('[문장 판정 오류] 도구 호출 없음', buf.getvalue())

    def test_rubric_and_tool_verbatim(self):
        """판정 지시문·도구는 실측(58건 정답·흔들림 0, 설계안 §10-2)에 쓴 글자 그대로 — 고치면 실측부터 다시."""
        rubric = (
            "너는 뉴스 기사 분류기다. 팀이 정한 「조건 문장」에 각 기사가 해당하는지 판정한다.\n\n"
            "판정 규칙\n"
            "1. 기사의 중심 내용이 조건 문장에 해당할 때만 match=true. 조건의 주제어가 나와도 지나가는 언급"
            "(시설·서비스 목록의 한 항목, 다른 사안의 배경 설명)이면 false.\n"
            "2. 조건 문장이 기사의 성격(문제 제기·비판, 긍정 평가, 발표·결정 등)을 정했으면 그 성격이어야 true. "
            "주제가 같아도 성격이 다르면(조건은 문제 제기인데 기사는 개선·확대·도입 소식) false.\n"
            "3. 주어진 제목·요약·본문 앞부분만 보고 판단한다(본문은 앞부분만 잘려 있다). 요약·본문이 없으면 제목만으로 "
            "판단하고, 해당하는지 분명하지 않으면 false.\n"
            "4. 기사가 회사에 중요한지, 뉴스 가치가 큰지는 판단하지 않는다. 조건 문장에 해당하는지만 본다.\n"
            "5. 기사마다 따로 판정한다(같은 사건의 다른 기사도 각자). why에는 판정 근거를 한 줄(40자 이내)로 쓴다."
        )
        tool = {'name': 'record_condition_verdicts',
                'description': '기사마다 조건 문장 해당 여부를 기록한다. 입력된 모든 기사에 대해 한 줄씩.',
                'input_schema': {'type': 'object', 'properties': {'verdicts': {'type': 'array', 'items': {
                    'type': 'object',
                    'properties': {'id': {'type': 'integer', 'description': '기사 번호'},
                                   'why': {'type': 'string', 'description': '판정 근거 한 줄(40자 이내)'},
                                   'match': {'type': 'boolean', 'description': '조건 문장에 해당하면 true'}},
                    'required': ['id', 'why', 'match']}}}, 'required': ['verdicts']}}
        self.assertEqual(crawler.SENTENCE_RUBRIC, rubric)
        self.assertEqual(crawler.SENTENCE_TOOL, tool)
        self.assertEqual(crawler.SENTENCE_BATCH, 20)


if __name__ == '__main__':
    unittest.main()
