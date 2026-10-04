# -*- coding: utf-8 -*-
"""
팀 채점(#277, 설계 local_docs/팀채점_설계_261004.md §3·§7·§14) — team_grading.py(순수)·crawler.py(세트·시험·적용 복사) 시험.
표준 unittest, **네트워크 0**. 가짜 DB는 test_crawler_sentence의 _MemDb에 is_·insert를 더해 쓴다.

  ① 시험 payload = 운영 payload — 같은 기사·같은 문장이면 _judge_sentence_batch가 client.messages.create에 넘기는
     model·max_tokens·system·tools·tool_choice·messages가 대기 처리 경로와 **바이트 동일**(설계 §11-7)
  ② 적용 복사 뒤 판 올림 재요청(_rev_bump_catchup)·대기 처리가 그 열쇠를 다시 묻지 않는다(§11-4), 브라우저 대기 행을 덮는다,
     비용 0·requested_by = GRADING_BY·judged_at = 복사 시각, 규칙 사본보다 뒤에 적용된 시험은 미룬다, 판·문장이 다르면 복사 안 함
  ③ 세트 고르기: 갈래·반반 나누기·seed 재현·같은 사건 1건·공통 긴급 ≥3·판정 대기 제외·사람 수정·too_small·풀 얇음
  ④ 시험 판정: 후보 하나 = 한 묶음 한 호출, 문장 같은 후보는 운영 판정 재사용(호출 0), 상한이 묶음보다 작으면 다음 실행,
     답에 빠진 기사 = 시도 1회, noise 흔들림 대조
  ⑤ 큐 행 모양(topic team), 월 비용에 시험 비용 합산
RLS·GRANT·트리거는 실DB에서 역할을 바꿔 가며 잰다(local_docs/팀채점_S1S2_구현기록_261004.md — 저장소에 계정 id를 남기지 않는다).
"""
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for p in (_ROOT, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import crawler  # noqa: E402
import team_grading  # noqa: E402
import urgency_rules  # noqa: E402
import subscriber_notify  # noqa: E402
from test_crawler_sentence import _MemDb, _MemQ, S_WIFI, W_WIFI, BODY  # noqa: E402

_MemDb.PK.update({'team_grading_trial_verdicts': ('trial_id', 'cand_idx', 'news_id')})


class _Q(_MemQ):
    def is_(self, c, v):
        assert v == 'null', v
        self.filters.append(('eq', c, None))
        return self

    def insert(self, rows):
        self.op, self.payload = 'insert', [dict(r) for r in (rows if isinstance(rows, list) else [rows])]
        return self

    def execute(self):
        if self.op == 'insert':
            db = self.db
            db.log.append({'table': self.name, 'op': 'insert', 'rows': self.payload, 'kw': {}, 'filters': [],
                           'cols': '*', 'range': None, 'orders': []})
            if self.name in db.fail or (self.name, 'insert') in db.fail:
                raise RuntimeError(f'{self.name} insert down')
            rows = db.tables.setdefault(self.name, [])
            out = []
            for r in self.payload:
                new = dict(r)
                if self.name in ('team_grading_trials', 'team_grading_sets') and 'id' not in new:
                    new['id'] = 100 + len(rows)
                rows.append(new)
                out.append(dict(new))
            return mock.Mock(data=out)
        return super().execute()


class _Db(_MemDb):
    def table(self, name):
        return _Q(self, name)


def _ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _news(nid, title, urgency='참고', content=BODY, screen_text=None, summary=None, created=None):
    return {'id': nid, 'url': 'https://x/' + nid, 'title': title, 'content': content, 'screen_text': screen_text,
            'summary': summary, 'urgency': urgency, 'origin': None, 'created_at': created or _ago(24)}


class _Resp:
    """가짜 Anthropic 응답 — 도구 호출 하나, 입력 기사 전부 match=True."""
    def __init__(self, n):
        blk = types.SimpleNamespace(type='tool_use', input={'verdicts': [{'id': k, 'why': '근거', 'match': True}
                                                                         for k in range(1, n + 1)]})
        self.content = [blk]
        self.usage = {'input_tokens': 1000, 'output_tokens': 100}


class _Client:
    def __init__(self, calls):
        self.calls = calls
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        n = kw['messages'][0]['content'].count('"id":')
        return _Resp(n)


class _Base(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        self.create_calls = []
        self.sent = []
        patches = [
            mock.patch.object(crawler, 'sb', self.db),
            mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'test-key'),
            mock.patch.object(crawler, 'TELEGRAM_CHAT_ID', 'chat-x'),
            mock.patch.object(crawler, 'SENTENCE_DB_RETRY_DELAY_S', 0),
            mock.patch.object(crawler.anthropic, 'Anthropic', lambda **kw: _Client(self.create_calls)),
            mock.patch.object(crawler.notify, 'send_telegram', lambda text, **kw: self.sent.append(text) or True),
            mock.patch.dict(crawler._SENTENCE_RUN_COST, {}, clear=True),
            mock.patch.dict(crawler._SENTENCE_RUN, {'judged': 0, 'nokey_logged': False, 'broken': False}, clear=True),
            mock.patch.dict(crawler._LATE_ALERT_PAIRS, {}, clear=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def rules(self, team_rules, enabled=..., loaded_at=None):
        enabled = enabled if enabled is not ... else {r['id']: r for rs in team_rules.values() for r in rs}
        for p in (mock.patch.object(crawler, 'load_team_urgency_rules', lambda: team_rules),
                  mock.patch.object(crawler, '_TEAM_RULES_ENABLED', enabled),
                  mock.patch.object(crawler, '_RULES_LOADED_AT', loaded_at or datetime.now(timezone.utc))):
            p.start()
            self.addCleanup(p.stop)

    def quiet(self, fn, *a, **k):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = fn(*a, **k)
        return out, buf.getvalue()


# ── ① 시험 payload = 운영 payload ──────────────────────────────────────────────────────────────
class TestPayloadLock(_Base):
    def test_trial_payload_bytes_equal_operational(self):
        n = _news('n1', '서울 지하철 공공와이파이 끊김 불만', content=BODY, screen_text='  공공와이파이  끊김   요약 ')
        rule = dict(S_WIFI, team_id=7)
        self.rules({7: [rule]})
        # 운영: 대기 행 하나를 대기 처리가 판정
        self.db.tables.update({
            'news_feed': [n],
            'urgency_rule_verdicts': [{'rule_id': 's_wifi', 'sentence_rev': 1, 'news_id': 'n1', 'team_id': 7,
                                       'status': 'pending', 'verdict': None, 'reason': '', 'input_kind': '', 'model': '',
                                       'cost_usd': 0, 'attempts': 0, 'requested_by': None, 'created_at': _ago(1),
                                       'judged_at': None}],
            'team_urgency': []})
        self.quiet(crawler._process_open_sentence_rows)
        self.assertEqual(len(self.create_calls), 1)
        op = self.create_calls[0]
        # 시험: 같은 기사·같은 문장의 후보(새 규칙 — 운영 판정 재사용 없음)
        self.create_calls.clear()
        crawler._SENTENCE_RUN.update(judged=0, broken=False)
        cand = {k: rule[k] for k in ('position', 'mode', 'level', 'any_words', 'and_any', 'none_words', 'sentence')}
        cand['rule_id'] = None
        self.db.tables.update({
            'team_grading_items': [{'set_id': 1, 'news_id': 'n1'}],
            'team_grading_trials': [], 'team_grading_trial_verdicts': []})
        trial = {'id': 9, 'set_id': 1, 'team_id': 7, 'kind': 'trial', 'status': 'pending', 'candidates': [cand],
                 'attempts': 0, 'created_at': _ago(0.1)}
        self.db.tables['team_grading_trials'].append(dict(trial))
        st, _ = self.quiet(crawler.judge_grading_trials, [trial])
        self.assertEqual(len(self.create_calls), 1)
        tr = self.create_calls[0]
        for k in ('model', 'max_tokens', 'system', 'tools', 'tool_choice', 'messages'):
            self.assertEqual(repr(op[k]), repr(tr[k]), k)
        self.assertNotIn('temperature', tr)
        self.assertEqual(st['judged'], 1)
        tv = self.db.tables['team_grading_trial_verdicts']
        self.assertEqual([(r['cand_idx'], r['news_id'], r['verdict'], r['input_kind'], r['reused']) for r in tv],
                         [(0, 'n1', True, 'body', False)])

    def test_sentence_input_is_the_only_builder(self):
        """대기 처리·되살림·시험이 판정 입력을 _sentence_input 하나로 만든다(따로 조립하면 payload가 갈라진다)."""
        import inspect
        src = inspect.getsource(crawler._process_open_sentence_rows)
        self.assertEqual(src.count('_sentence_input('), 2)
        self.assertNotIn("kind = 'body' if body", src)
        self.assertIn('_sentence_input(', inspect.getsource(crawler.judge_grading_trials))


# ── ② 적용 복사 ─────────────────────────────────────────────────────────────────────────────────
class TestApplyCopy(_Base):
    def setUp(self):
        super().setUp()
        self.rule = dict(S_WIFI, team_id=7, sentence_rev=2, updated_at=_ago(1))
        self.cand = {'rule_id': 's_wifi', 'position': 10, 'mode': 'set', 'level': '긴급',
                     'any_words': S_WIFI['any_words'], 'and_any': [], 'none_words': ['홍보'],
                     'sentence': self.rule['sentence']}
        self.db.tables.update({
            'news_feed': [_news('n1', '공공와이파이 끊김', urgency='보통'), _news('n2', '공공와이파이 확대', urgency='참고')],
            'team_urgency': [],
            'team_grading_trial_verdicts': [
                {'trial_id': 5, 'cand_idx': 0, 'news_id': 'n1', 'verdict': True, 'reason': '문제 제기', 'input_kind': 'body',
                 'model': 'm', 'cost_usd': 0.004, 'reused': False},
                {'trial_id': 5, 'cand_idx': 0, 'news_id': 'n2', 'verdict': False, 'reason': '확대 소식', 'input_kind': 'body',
                 'model': 'm', 'cost_usd': 0.004, 'reused': False}],
            # 브라우저 재적용이 넣은 같은 열쇠의 대기 행(요청자 = 팀원)
            'urgency_rule_verdicts': [{'rule_id': 's_wifi', 'sentence_rev': 2, 'news_id': 'n1', 'team_id': 7,
                                       'status': 'pending', 'verdict': None, 'reason': '', 'input_kind': '', 'model': '',
                                       'cost_usd': 0, 'attempts': 0, 'requested_by': 'user-1', 'created_at': _ago(0.5),
                                       'judged_at': None}]})

    def trial(self, applied_h=1.0, rev=2):
        return {'id': 5, 'set_id': 1, 'team_id': 7, 'kind': 'trial', 'status': 'applied', 'candidates': [self.cand],
                'applied_rev': {'0': {'rule_id': 's_wifi', 'rev': rev}}, 'applied_at': _ago(applied_h),
                'attempts': 0, 'created_at': _ago(2)}

    def test_copy_overwrites_pending_and_catchup_skips(self):
        self.rules({7: [self.rule]})
        self.db.tables['team_grading_trials'] = [self.trial()]
        n, log = self.quiet(crawler.copy_applied_grading_trials)
        self.assertEqual(n, 2)
        rows = sorted(self.db.tables['urgency_rule_verdicts'], key=lambda r: r['news_id'])
        self.assertEqual([(r['news_id'], r['status'], r['verdict'], r['cost_usd'], r['requested_by'], r['sentence_rev'])
                          for r in rows],
                         [('n1', 'done', True, 0.0, crawler.GRADING_BY, 2), ('n2', 'done', False, 0.0, crawler.GRADING_BY, 2)])
        self.assertTrue(all(r['judged_at'] for r in rows))
        self.assertTrue(self.db.tables['team_grading_trials'][0]['copied_at'])
        # 팀 행: 참 판정 기사만 rule 행(set 긴급)
        self.assertEqual([(r['news_id'], r['urgency'], r['source']) for r in self.db.tables['team_urgency']],
                         [('n1', '긴급', 'rule')])
        # 판 올림 재요청: 지금 판 행이 이미 있으므로 넣을 것이 없다
        now = datetime.now(timezone.utc)
        self.db.tables['urgency_rule_verdicts'].append(
            {'rule_id': 's_wifi', 'sentence_rev': 1, 'news_id': 'n1', 'team_id': 7, 'status': 'done', 'verdict': False,
             'created_at': _ago(5)})
        out, _ = self.quiet(crawler._rev_bump_catchup, {'s_wifi': self.rule}, {7: [self.rule]}, now, now.isoformat())
        self.assertEqual(out, [])
        # 대기 처리: done 행은 다시 묻지 않는다
        self.create_calls.clear()
        self.quiet(crawler._process_open_sentence_rows)
        self.assertEqual(self.create_calls, [])

    def test_applied_after_snapshot_is_deferred(self):
        self.rules({7: [self.rule]}, loaded_at=datetime.now(timezone.utc) - timedelta(minutes=5))
        self.db.tables['team_grading_trials'] = [self.trial(applied_h=0.01)]
        n, _ = self.quiet(crawler.copy_applied_grading_trials)
        self.assertEqual(n, 0)
        self.assertIsNone(self.db.tables['team_grading_trials'][0].get('copied_at'))
        self.assertEqual(self.db.tables['urgency_rule_verdicts'][0]['status'], 'pending')

    def test_rev_moved_on_not_copied(self):
        self.rules({7: [dict(self.rule, sentence_rev=3, sentence='다른 문장')]})
        self.db.tables['team_grading_trials'] = [self.trial()]
        n, log = self.quiet(crawler.copy_applied_grading_trials)
        self.assertEqual(n, 0)
        self.assertTrue(self.db.tables['team_grading_trials'][0]['copied_at'], '닫는다(다시 집지 않게)')
        self.assertIn('지금 규칙과 다름', self.db.tables['team_grading_trials'][0]['note'])
        self.assertEqual(self.db.tables['urgency_rule_verdicts'][0]['status'], 'pending')

    def test_old_snapshot_waits(self):
        """사본이 아직 옛 판(드묾) — 복사하지 않고 다음 실행(기한 안)."""
        self.rules({7: [dict(self.rule, sentence_rev=1)]})
        self.db.tables['team_grading_trials'] = [self.trial()]
        n, _ = self.quiet(crawler.copy_applied_grading_trials)
        self.assertEqual(n, 0)
        self.assertIsNone(self.db.tables['team_grading_trials'][0].get('copied_at'))

    def test_word_only_candidate_copies_nothing(self):
        self.rules({7: [self.rule]})
        t = self.trial()
        t['candidates'] = [dict(self.cand, sentence='')]
        self.db.tables['team_grading_trials'] = [t]
        n, _ = self.quiet(crawler.copy_applied_grading_trials)
        self.assertEqual(n, 0)
        self.assertTrue(self.db.tables['team_grading_trials'][0]['copied_at'])


# ── ③ 세트 고르기(순수) ─────────────────────────────────────────────────────────────────────────
def _mk(i, kind, common='보통', title=None):
    return {'id': f'{kind}-{i:03d}', 'waiting': False, 'kind': kind, 'common': common, 'team_level': common,
            'team_source': 'common', 'rule_id': None, 'rule_sentence': False, 'title': title or f'{kind} 기사 {i}'}


def _kw_unique(c):
    return {c['id']}        # 같은 사건 없음(제목 키워드가 서로 안 겹침)


class TestPick(unittest.TestCase):
    def classified(self, a=20, b=20, s=5, c=30, d=60):
        out = [_mk(i, 'rule_changed', '참고') for i in range(a)] + [_mk(i, 'word_hit_false') for i in range(b)]
        out += [_mk(i, 'rule_same') for i in range(s)] + [_mk(i, 'near') for i in range(c)]
        levels = ('긴급', '보통', '참고')
        out += [_mk(i, 'unrelated', levels[i % 3]) for i in range(d)]
        return out

    def pick(self, cl, seed=7, body_ok=None):
        b = team_grading.bucket_lists(cl, seed)
        ok = body_ok if body_ok is not None else {c['id'] for c in cl if c}
        return team_grading.pick_set(b, seed, ok, _kw_unique)

    def test_full_set_split_and_reproducible(self):
        cl = self.classified()
        p1, p2 = self.pick(cl), self.pick(list(reversed(cl)))
        self.assertEqual([(c['id'], c['slot'], c['seq']) for c in p1['items']],
                         [(c['id'], c['slot'], c['seq']) for c in p2['items']], '같은 seed·같은 재료 = 같은 세트(입력 순서 무관)')
        self.assertEqual(p1['counts'], {'A': 6, 'B': 4, 'S': 0, 'C': 6, 'D': 4})
        self.assertEqual(len(p1['items']), 20)
        self.assertFalse(p1['pool_thin'] or p1['too_small'])
        for kind in ('rule_changed', 'word_hit_false', 'near', 'unrelated'):
            slots = [c['slot'] for c in p1['items'] if c['kind'] == kind]
            self.assertEqual(slots.count('tune'), slots.count('check'), kind)
        self.assertEqual(sorted(c['seq'] for c in p1['items']), list(range(1, 21)))
        self.assertNotEqual([c['seq'] for c in p1['items']], list(range(1, 21)), '화면 순서는 갈래 순서가 아니다')
        self.assertNotEqual([c['id'] for c in self.pick(cl, seed=8)['items']], [c['id'] for c in p1['items']])
        self.assertGreaterEqual(p1['common_urgent'], team_grading.MIN_COMMON_URGENT)

    def test_b_short_fills_a_then_same_then_c(self):
        p = self.pick(self.classified(a=20, b=1, s=0))
        self.assertEqual((p['counts']['A'], p['counts']['B']), (9, 1))
        p = self.pick(self.classified(a=3, b=2, s=2, c=30))
        self.assertEqual(p['counts'], {'A': 3, 'B': 2, 'S': 2, 'C': 9, 'D': 4})
        self.assertTrue(p['pool_thin'])
        self.assertEqual(len(p['items']), 20)

    def test_too_small(self):
        p = self.pick(self.classified(a=1, b=1, s=0, c=3, d=6))
        self.assertTrue(p['too_small'])
        self.assertLess(len(p['items']), team_grading.MIN_SET)

    def test_common_urgent_floor_raises_d_urgent(self):
        cl = [_mk(i, 'rule_changed', '참고') for i in range(10)] + [_mk(i, 'near', '참고') for i in range(10)]
        cl += [_mk(i, 'unrelated', lv) for i in range(10) for lv in ('긴급',)]
        cl += [_mk(100 + i, 'unrelated', '보통') for i in range(10)] + [_mk(200 + i, 'unrelated', '참고') for i in range(10)]
        p = self.pick(cl)
        self.assertEqual(p['common_urgent'], 3)
        self.assertEqual(p['counts']['D'], 4)

    def test_same_event_once_and_body_required(self):
        cl = [_mk(i, 'rule_changed', '참고', title='SKT 유심 해킹 과징금 부과 결정') for i in range(10)]
        cl += [_mk(i, 'near') for i in range(20)] + [_mk(i, 'unrelated', '긴급') for i in range(10)]
        from news_dedup import extract_keywords
        b = team_grading.bucket_lists(cl, 3)
        ok = {c['id'] for c in cl} - {'near-000', 'near-001'}
        p = team_grading.pick_set(b, 3, ok, lambda c: extract_keywords(c['title']) if c['kind'] == 'rule_changed'
                                  else {c['id']})
        self.assertEqual(p['counts']['A'], 1, '같은 사건은 한 건')
        self.assertFalse({'near-000', 'near-001'} & {c['id'] for c in p['items']}, '본문 없는 기사는 뽑지 않음')

    def test_rule_branch_event_and_cap(self):
        """R2(10-04): A·B는 규칙 낱말을 뺀 키워드 2개 공유 = 같은 사건, 그리고 한 규칙은 갈래마다 2건까지."""
        from news_dedup import extract_keywords
        ttl = ['경기도 ‘유령 공공와이파이’ 429곳… 전국서 미사용 비율 가장 높아',
               "'유령 와이파이' 경기 429곳 최다…전남광주도 236곳",        # 규칙 낱말 빼고 429곳·경기·유령 → 같은 사건
               '세금 들인 공공와이파이 1600곳 이용 無…낮은 활용도 도마',
               '경남 유령 공공와이파이 전국 최고…127곳 접속 한 건도 없어',
               '청주시, 버스 공공와이파이 5G 전환 추진']
        cl = [dict(_mk(i, 'rule_changed', '참고', title=t), rule_id='wifi') for i, t in enumerate(ttl)]
        cl += [dict(_mk(10 + i, 'rule_changed', '참고', title=t), rule_id='spec')
               for i, t in enumerate(['주파수 재할당 대가 산정 기준 발표', '6G 주파수 로드맵 공개', '재할당 심사위원회 구성 완료'])]
        cl += [_mk(i, 'near') for i in range(20)] + [_mk(i, 'unrelated', '긴급') for i in range(10)]
        self.assertEqual(team_grading.strip_rule_words(extract_keywords(ttl[0]), ['공공와이파이', '공공 와이파이']),
                         {'429곳', '가장', '경기', '높아', '미사용', '비율', '유령', '전국서'}, '「공공와이파」도 뺀다')
        words = {'wifi': ['공공와이파이', '공공 와이파이', '와이파이'], 'spec': ['주파수', '재할당']}
        b = {'A': [c for c in cl if c['kind'] == 'rule_changed'], 'B': [], 'S': [], 'C': [c for c in cl if c['kind'] == 'near'],
             'D긴급': [c for c in cl if c['kind'] == 'unrelated'], 'D보통': [], 'D참고': []}
        p = team_grading.pick_set(b, 1, {c['id'] for c in cl}, lambda c: extract_keywords(c['title']),
                                  lambda c: words.get(c['rule_id']))
        got = [c['title'] for c in p['items'] if c['kind'] == 'rule_changed']
        self.assertEqual(sum(1 for c in p['items'] if c.get('rule_id') == 'wifi'), 2, '한 규칙은 A에 2건까지')
        self.assertNotIn(ttl[1], got, '규칙 낱말 빼고 2개 공유 = 같은 사건')
        self.assertEqual(sum(1 for c in p['items'] if c.get('rule_id') == 'spec'), 2)
        # rule_words_of 없이(옛 호출)도 규칙당 상한은 rule_id로 걸린다
        p2 = team_grading.pick_set(b, 1, {c['id'] for c in cl}, _kw_unique)
        self.assertEqual(sum(1 for c in p2['items'] if c.get('rule_id') == 'wifi'), 2)

    def test_waiting_and_bad_level_excluded(self):
        cl = self.classified() + [{'id': 'w', 'waiting': True}, None]
        b = team_grading.bucket_lists(cl, 1)
        self.assertNotIn('w', {c['id'] for lst in b.values() for c in lst})


class TestClassify(unittest.TestCase):
    RULES = [dict(S_WIFI, team_id=7), dict(W_WIFI, team_id=7)]

    def c(self, title, urgency='보통', row=None, vrows=None, words=None, text=''):
        n = {'id': 'x', 'title': title, 'screen_text': text, 'summary': '', 'urgency': urgency}
        return team_grading.classify_article(n, self.RULES, row, vrows, words or [])

    def test_kinds(self):
        v_true = [{'rule_id': 's_wifi', 'sentence_rev': 1, 'verdict': True}]
        v_false = [{'rule_id': 's_wifi', 'sentence_rev': 1, 'verdict': False}]
        self.assertEqual(self.c('공공와이파이 끊김')['waiting'], True, '문장 판정 없음 = 대기')
        r = self.c('공공와이파이 끊김', vrows=v_true)
        self.assertEqual((r['kind'], r['team_level'], r['team_source'], r['rule_id'], r['rule_sentence']),
                         ('rule_changed', '긴급', 'rule', 's_wifi', True))
        r = self.c('공공와이파이 확대', vrows=v_false)       # 문장 거짓 → 뒤 낱말 규칙(min 보통)이 정함, 공통 보통 = 같음
        self.assertEqual((r['kind'], r['rule_id'], r['rule_sentence'], r['team_level']), ('rule_same', 'w_wifi', False, '보통'))
        r = self.c('공공와이파이 확대', urgency='참고', vrows=v_false)
        self.assertEqual((r['kind'], r['team_level']), ('rule_changed', '보통'))
        rules = [dict(S_WIFI, team_id=7)]
        n = {'id': 'x', 'title': '공공와이파이 확대', 'screen_text': '', 'summary': '', 'urgency': '보통'}
        r = team_grading.classify_article(n, rules, None, v_false, [])
        self.assertEqual((r['kind'], r['rule_id'], r['team_level']), ('word_hit_false', 's_wifi', '보통'))
        words = team_grading.near_words(rules, ['로밍'])
        self.assertEqual(team_grading.classify_article(
            {'id': 'y', 'title': '해외 로밍 요금', 'urgency': '참고'}, rules, None, None, words)['kind'], 'near')
        self.assertEqual(team_grading.classify_article(
            {'id': 'y', 'title': '반도체 수출', 'urgency': '참고'}, rules, None, None, words)['kind'], 'unrelated')
        self.assertIsNone(team_grading.classify_article({'id': 'z', 'title': 'a', 'urgency': 'importance'}, rules, None, None, []))

    def test_human_row_wins(self):
        row = {'news_id': 'x', 'team_id': 7, 'source': 'human', 'urgency': '참고'}
        r = self.c('반도체 수출', urgency='긴급', row=row)
        self.assertEqual((r['team_level'], r['team_source'], r['kind']), ('참고', 'human', 'unrelated'))

    def test_candidate_rule(self):
        rule, err = team_grading.candidate_rule({'rule_id': None, 'mode': 'set', 'level': '긴급', 'any_words': ['a'],
                                                 'sentence': 's'}, 2, 7)
        self.assertEqual((rule['id'], err), ('cand_2', ''))
        self.assertEqual(team_grading.candidate_rule({'mode': 'set', 'level': '긴급', 'any_words': []}, 0, 7)[0], None)
        self.assertEqual(team_grading.candidate_rule('x', 0, 7)[0], None)
        self.assertTrue(team_grading.same_sentence(' 공공  와이파이\n문제 ', '공공 와이파이 문제'))


# ── ④ 시험 판정 ────────────────────────────────────────────────────────────────────────────────
class TestTrialJudging(_Base):
    def setUp(self):
        super().setUp()
        self.rule = dict(S_WIFI, team_id=7)
        self.rules({7: [self.rule]})
        news = [_news(f'n{i}', f'공공와이파이 기사 {i}') for i in range(5)] + [_news('m1', '반도체')]
        self.db.tables.update({
            'news_feed': news, 'team_grading_items': [{'set_id': 1, 'news_id': n['id']} for n in news],
            'team_grading_trial_verdicts': [], 'urgency_rule_verdicts': [], 'team_grading_sets': [{'id': 1}]})

    def trial(self, kind='trial', sentence=None, rule_id=None):
        cand = {'rule_id': rule_id, 'position': 10, 'mode': 'set', 'level': '긴급', 'any_words': ['공공와이파이'],
                'and_any': [], 'none_words': [], 'sentence': sentence if sentence is not None else '공공와이파이 문제 기사',
                'sentence_rev': 1}
        t = {'id': 3, 'set_id': 1, 'team_id': 7, 'kind': kind, 'status': 'pending', 'candidates': [cand], 'attempts': 0,
             'created_at': _ago(0.1)}
        self.db.tables['team_grading_trials'] = [dict(t)]
        return t

    def tstate(self):
        return self.db.tables['team_grading_trials'][0]

    def test_one_batch_one_call_cost(self):
        st, _ = self.quiet(crawler.judge_grading_trials, [self.trial()])
        self.assertEqual((st['calls'], st['judged'], len(self.create_calls)), (1, 1, 1))
        self.assertIn('기사 5건', self.create_calls[0]['messages'][0]['content'])
        self.assertEqual(self.tstate()['status'], 'judged')
        self.assertAlmostEqual(self.tstate()['cost_usd'], 0.0015, places=4)
        self.assertAlmostEqual(crawler._SENTENCE_RUN_COST[7], 0.0015, places=4)

    def test_same_sentence_reuses_operational_verdicts(self):
        self.db.tables['urgency_rule_verdicts'] = [
            {'rule_id': 's_wifi', 'sentence_rev': 1, 'news_id': f'n{i}', 'team_id': 7, 'status': 'done',
             'verdict': i % 2 == 0, 'reason': 'r', 'input_kind': 'body', 'model': 'm'} for i in range(4)]
        st, _ = self.quiet(crawler.judge_grading_trials, [self.trial(sentence=S_WIFI['sentence'], rule_id='s_wifi')])
        self.assertEqual((st['reused'], st['calls']), (4, 1), '운영 판정 4건 재사용, 남은 1건만 호출')
        self.assertIn('기사 1건', self.create_calls[0]['messages'][0]['content'])
        tv = {r['news_id']: r for r in self.db.tables['team_grading_trial_verdicts']}
        self.assertEqual((tv['n1']['verdict'], tv['n1']['reused'], tv['n1']['cost_usd']), (False, True, 0.0))

    def test_noise_does_not_reuse_and_compares(self):
        self.db.tables['urgency_rule_verdicts'] = [
            {'rule_id': 's_wifi', 'sentence_rev': 1, 'news_id': f'n{i}', 'team_id': 7, 'status': 'done',
             'verdict': i < 3} for i in range(5)]
        st, log = self.quiet(crawler.judge_grading_trials, [self.trial(kind='noise', sentence=S_WIFI['sentence'],
                                                                       rule_id='s_wifi')])
        self.assertEqual((st['reused'], st['calls']), (0, 1))
        s = self.db.tables['team_grading_sets'][0]
        self.assertEqual((s['noise_mismatch'], s['noise_compared']), (2, 5), '가짜 응답은 전부 참 — 저장 거짓 2건이 어긋남')
        self.assertIn('AI 흔들림 2/5건', log)

    def test_room_smaller_than_batch_waits(self):
        crawler._SENTENCE_RUN['judged'] = crawler.SENTENCE_PER_RUN_MAX - 3
        st, _ = self.quiet(crawler.judge_grading_trials, [self.trial()])
        self.assertEqual((st['calls'], st['left'], self.create_calls), (0, 1, []), '묶음을 쪼개지 않는다')
        self.assertEqual(self.tstate()['status'], 'pending')

    def test_missing_answer_counts_attempt(self):
        with mock.patch.object(crawler, '_judge_sentence_batch', lambda c, s, rows: ({1: (True, 'x')}, 0.01)):
            st, _ = self.quiet(crawler.judge_grading_trials, [self.trial()])
        self.assertEqual((self.tstate()['status'], self.tstate()['attempts']), ('pending', 1))
        self.assertEqual(len(self.db.tables['team_grading_trial_verdicts']), 1, '받은 1건은 저장 — 다음엔 나머지만')

    def test_whole_call_failure_keeps_attempts(self):
        with mock.patch.object(crawler, '_judge_sentence_batch', lambda c, s, rows: (None, 0.0)):
            st, _ = self.quiet(crawler.judge_grading_trials, [self.trial()])
        self.assertEqual((self.tstate()['status'], self.tstate().get('attempts', 0), st['left']), ('pending', 0, 1))
        self.assertTrue(crawler._SENTENCE_RUN['broken'])

    def test_bad_candidate_fails(self):
        t = self.trial()
        t['candidates'] = [{'mode': 'set', 'level': '긴급', 'any_words': []}]
        self.db.tables['team_grading_trials'] = [dict(t)]
        st, _ = self.quiet(crawler.judge_grading_trials, [t])
        self.assertEqual((st['failed'], self.tstate()['status']), (1, 'failed'))

    def test_expired_fails(self):
        t = self.trial()
        t['created_at'] = _ago(30)
        st, _ = self.quiet(crawler.judge_grading_trials, [t])
        self.assertEqual((st['failed'], self.create_calls), (1, []))


# ── 세트 만들기(DB 배선) ─────────────────────────────────────────────────────────────────────────
class TestBuild(_Base):
    def test_build_open_set_noise_and_queue(self):
        rule = dict(S_WIFI, team_id=7)
        self.rules({7: [rule]})
        w = ['가람', '나래', '다솜', '라온', '마루', '바다', '사랑', '아라', '자람', '차오', '카라', '타래', '파랑', '하늘']
        news = [_news(f'a{i}', f'공공와이파이 {w[i]}역 끊김', urgency='보통') for i in range(8)]
        news += [_news(f'b{i}', f'공공와이파이 {w[i]}구 확대', urgency='참고') for i in range(6)]
        news += [_news(f'd{i}', f'{w[i]} {w[13 - i]} 수출', urgency=('긴급', '보통', '참고')[i % 3]) for i in range(12)]
        news += [_news(f'c{i}', f'{w[i]} 통신 요금', urgency='보통') for i in range(14)]     # 팀 키워드 「요금」 = 주제 근처
        vr = [{'rule_id': 's_wifi', 'sentence_rev': 1, 'news_id': f'a{i}', 'verdict': True, 'status': 'done'} for i in range(8)]
        vr += [{'rule_id': 's_wifi', 'sentence_rev': 1, 'news_id': f'b{i}', 'verdict': False, 'status': 'done'} for i in range(6)]
        self.db.tables.update({'news_feed': news, 'urgency_rule_verdicts': vr, 'team_urgency': [],
                               'team_criteria': [{'team_id': 7, 'keywords': ['요금']}],
                               'team_grading_items': [], 'team_grading_trials': [], 'subscriber_queue': [],
                               'team_grading_sets': [{'id': 1, 'team_id': 7, 'status': 'requested', 'build_attempts': 0}],
                               'teams': [{'id': 7, 'name': '시험팀'}]})
        n, log = self.quiet(crawler.build_grading_sets)
        self.assertEqual(n, 1, log)
        s = self.db.tables['team_grading_sets'][0]
        self.assertEqual(s['status'], 'open', log)
        items = self.db.tables['team_grading_items']
        self.assertEqual(len(items), 20)            # 규칙 하나 → A2 B2(규칙당 상한, R2) · C12(근처로 채움) · D4
        kinds = [i['hit_kind_at_build'] for i in items]
        self.assertEqual({k: kinds.count(k) for k in set(kinds)},
                         {'rule_changed': 2, 'word_hit_false': 2, 'near': 12, 'unrelated': 4})
        self.assertTrue(s['pool_thin'])
        self.assertTrue(all(i['set_id'] == 1 for i in items))
        tr = self.db.tables['team_grading_trials']
        self.assertEqual([(t['kind'], [c['rule_id'] for c in t['candidates']]) for t in tr], [('noise', ['s_wifi'])])
        q = self.db.tables['subscriber_queue']
        self.assertEqual([(r['topic'], r['audience']) for r in q], [('team', 't:7')])
        self.assertIn('?p=grading&amp;set=1', q[0]['html'])
        self.assertNotIn('level', q[0])

    def test_no_rules_and_retry(self):
        self.rules({}, enabled={})
        self.db.tables.update({'team_grading_sets': [{'id': 2, 'team_id': 9, 'status': 'requested', 'build_attempts': 0}],
                               'teams': [{'id': 9, 'name': '빈팀'}]})
        self.quiet(crawler.build_grading_sets)
        self.assertEqual(self.db.tables['team_grading_sets'][0]['status'], 'no_rules')
        self.assertEqual(len(self.sent), 1)
        # 규칙 표 조회 실패 = 다음 실행에서 다시(requested로 되돌림)
        self.rules({}, enabled=None)
        self.db.tables['team_grading_sets'] = [{'id': 3, 'team_id': 9, 'status': 'requested', 'build_attempts': 0}]
        self.quiet(crawler.build_grading_sets)
        self.assertEqual((self.db.tables['team_grading_sets'][0]['status'],
                          self.db.tables['team_grading_sets'][0]['build_attempts']), ('requested', 1))


# ── ⑤ 큐·비용 ────────────────────────────────────────────────────────────────────────────────
class TestQueueAndCost(_Base):
    def test_queue_for_subscribers_refuses_team(self):
        out, _ = self.quiet(subscriber_notify.queue_for_subscribers, self.db, 'team', '<b>x</b>')
        self.assertFalse(out)
        self.assertEqual(self.db.log, [])
        self.assertTrue(self.quiet(subscriber_notify.queue_team_notice, self.db, 4, '<b>x</b>')[0])
        self.assertEqual(self.db.tables['subscriber_queue'], [{'topic': 'team', 'html': '<b>x</b>', 'audience': 't:4'}])

    def test_month_cost_includes_trials(self):
        since = _ago(24)
        self.db.tables.update({
            'urgency_rule_verdicts': [{'rule_id': 'r', 'sentence_rev': 0, 'news_id': 'a', 'team_id': 7,
                                       'cost_usd': 0.5, 'judged_at': _ago(1)},
                                      {'rule_id': 'r', 'sentence_rev': 1, 'news_id': 'a', 'team_id': 7,
                                       'cost_usd': 0.0, 'judged_at': _ago(1)}],      # 적용 복사 행(비용 0)
            'team_grading_trials': [{'id': 1, 'team_id': 7, 'cost_usd': 0.25, 'judged_at': _ago(2)},
                                    {'id': 2, 'team_id': 7, 'cost_usd': 9.0, 'judged_at': _ago(48)},
                                    {'id': 3, 'team_id': 8, 'cost_usd': 9.0, 'judged_at': _ago(2)}]})
        self.assertAlmostEqual(crawler._team_month_cost(7, since), 0.75)

    def test_process_order_copy_first(self):
        order = []
        with mock.patch.object(crawler, 'copy_applied_grading_trials', lambda: order.append('copy')), \
                mock.patch.object(crawler, '_process_open_sentence_rows', lambda: order.append('open')), \
                mock.patch.object(crawler, 'run_team_grading', lambda: order.append('grading')), \
                mock.patch.object(crawler, '_sentence_budget_alert', lambda: order.append('budget')):
            crawler.process_open_sentence_verdicts()
        self.assertEqual(order, ['copy', 'open', 'grading', 'budget'])

    def test_grading_marker_differs(self):
        self.assertNotEqual(crawler.GRADING_BY, crawler.SENTENCE_REQUEUE_BY)
        self.assertIsNotNone(crawler.GRADING_BY)


if __name__ == '__main__':
    unittest.main()
