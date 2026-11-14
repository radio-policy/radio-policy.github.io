# -*- coding: utf-8 -*-
"""
okf_refresh 실패 기억·긴 요약 보류·세션 문서 적재 (#341, 2026-11-15) — 네트워크·DB 접근 없음.

배경: 실패한 대상을 기억하지 않아 같은 법령이 매일 다시 호출되고 매일 같은 실패에 과금됐다
(재난 및 안전관리 기본법 시행령, 4회 ≈ $3). 여기서 잠그는 것:
  · 기억에 있는 대상은 호출 대상에서 빠지고 실행당 상한을 차지하지 않는다
  · 더 새 판이 오면(호수가 바뀌면) 열쇠가 달라져 다시 시도한다
  · 어긋남이 풀린 건·이번에 끝난 건은 기억에서 지워진다
  · 대기 알림은 매일이 아니라 HELD_REMIND_DAYS마다(#197 「같은 목록을 매일 반복 알림하지 말 것」)
  · 긴 구판 요약은 모델 호출 전에 보류된다(코드 순서 잠금)
"""

import inspect
import json
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import okf_refresh as orf


def _d(path, no, title='법령'):
    return {'path': path, 'cur_no': no, 'title': title}


class TestHeldMemo(unittest.TestCase):

    def test_held_key_is_path_and_new_number(self):
        self.assertEqual(orf.held_key(_d('laws/a/x.md', '제36826호')), 'laws/a/x.md>제36826호')
        # 더 새 판이 오면 열쇠가 달라진다 → 그 판은 한 번 다시 시도
        self.assertNotEqual(orf.held_key(_d('laws/a/x.md', '제36826호')), orf.held_key(_d('laws/a/x.md', '제36900호')))

    def test_parse_held_tolerates_garbage(self):
        self.assertEqual(orf.parse_held(None), {})
        self.assertEqual(orf.parse_held(''), {})
        self.assertEqual(orf.parse_held('targets=1 done=0'), {})        # 옛 heartbeat 글자가 들어 있어도
        self.assertEqual(orf.parse_held('[1, 2]'), {})
        self.assertEqual(orf.parse_held('{"k": "글자"}'), {})            # 값이 dict가 아니면 버린다
        note = json.dumps({'laws/a/x.md>제1호': {'t': '가', 'why': '잘림', 'since': '2026-11-12', 'last': '2026-11-12'}},
                          ensure_ascii=False)
        self.assertEqual(orf.parse_held(note)['laws/a/x.md>제1호']['since'], '2026-11-12')

    def test_plan_targets_skips_held_and_limit_applies_to_rest(self):
        drift = [_d('a.md', '제1호'), _d('b.md', '제2호'), _d('c.md', '제3호'), _d('d.md', '제4호')]
        held = {'a.md>제1호': {'t': 'a', 'why': 'x', 'since': '2026-11-12'}}
        targets, deferred, waiting = orf.plan_targets(drift, held, 2)
        self.assertEqual([d['path'] for d in waiting], ['a.md'])
        self.assertEqual([d['path'] for d in targets], ['b.md', 'c.md'])   # 대기 건이 상한 자리를 먹지 않는다
        self.assertEqual([d['path'] for d in deferred], ['d.md'])
        # 기억이 없으면 예전과 같다
        t2, d2, w2 = orf.plan_targets(drift, {}, 5)
        self.assertEqual((len(t2), len(d2), len(w2)), (4, 0, 0))

    def test_next_held_prunes_resolved_and_keeps_first_failure_date(self):
        stored = {'a.md>제1호': {'t': 'a', 'why': '잘림', 'since': '2026-11-12', 'last': '2026-11-12'},
                  'gone.md>제9호': {'t': 'g', 'why': 'x', 'since': '2026-11-01', 'last': '2026-11-01'},
                  'done.md>제5호': {'t': 'd', 'why': 'x', 'since': '2026-11-10', 'last': '2026-11-10'}}
        drift_keys = {'a.md>제1호', 'done.md>제5호', 'b.md>제2호'}
        out = orf.next_held(stored, drift_keys, {'done.md>제5호'},
                            [(_d('b.md', '제2호', '나'), '분량 급변', False), (_d('a.md', '제1호', 'a'), '또 잘림', False)],
                            '2026-11-15')
        self.assertNotIn('gone.md>제9호', out)                 # 어긋남이 풀렸다(세션이 처리했거나 새 판이 왔다)
        self.assertNotIn('done.md>제5호', out)                 # 이번에 끝났다
        self.assertEqual(out['b.md>제2호'],
                         {'t': '나', 'why': '분량 급변', 'since': '2026-11-15', 'last': '2026-11-15', 'n': 1})
        self.assertEqual(out['a.md>제1호']['since'], '2026-11-12')     # 다시 실패해도 처음 실패한 날을 지킨다
        self.assertEqual(out['a.md>제1호']['why'], '또 잘림')
        self.assertEqual(stored['a.md>제1호']['why'], '잘림')          # 입력을 바꾸지 않는다

    def test_soft_errors_get_one_more_try(self):
        """연결·임베딩·적재 오류(우리 기각이 아닌 예외)는 일시 장애일 수 있다 — 한 번 더 시도하고, 연속 두 번이면 대기."""
        self.assertEqual(orf.HELD_SOFT_TRIES, 2)
        self.assertTrue(issubclass(orf.RefreshRejected, ValueError))
        d = _d('a.md', '제1호', '가법')
        h1 = orf.next_held({}, {'a.md>제1호'}, set(), [(d, 'ConnectError', True)], '2026-11-15')
        self.assertEqual(h1['a.md>제1호'], {'t': '가법', 'why': 'ConnectError', 'since': '2026-11-15',
                                           'last': '2026-11-15', 'n': 1, 'soft': True})
        self.assertFalse(orf.held_blocks(h1['a.md>제1호']))
        self.assertEqual(orf.plan_targets([d], h1, 5), ([d], [], []))            # 다음 날 다시 대상
        h2 = orf.next_held(h1, {'a.md>제1호'}, set(), [(d, 'ConnectError', True)], '2026-11-16')
        self.assertEqual(h2['a.md>제1호']['n'], 2)
        self.assertTrue(orf.held_blocks(h2['a.md>제1호']))
        self.assertEqual(orf.plan_targets([d], h2, 5), ([], [], [d]))            # 두 번 연속이면 대기
        # 두 번째가 우리 기각이면 그 자리에서 대기
        h3 = orf.next_held(h1, {'a.md>제1호'}, set(), [(d, '출력이 max_tokens에서 잘림', False)], '2026-11-16')
        self.assertTrue(orf.held_blocks(h3['a.md>제1호']))
        self.assertNotIn('soft', h3['a.md>제1호'])
        # 우리 기각은 한 번이면 막는다 · 깨진 기억은 막지 않는다
        self.assertTrue(orf.held_blocks({'t': 'x', 'why': '잘림', 'n': 1}))
        self.assertTrue(orf.held_blocks({'t': 'x'}))
        self.assertFalse(orf.held_blocks(None))

    def test_own_rejections_use_refresh_rejected(self):
        """이 파일이 스스로 내리는 기각은 모두 RefreshRejected — 그 밖의 ValueError(JSON 해석 오류 등)와 섞이지 않게."""
        src = inspect.getsource(orf)
        self.assertNotIn('raise ValueError(', src)
        self.assertGreaterEqual(src.count('raise RefreshRejected('), 8)
        with self.assertRaises(orf.RefreshRejected):
            orf.validate_output('frontmatter 없는 글', '', 'laws/x/y.md', {'new_no': '제1호'})

    def test_due_reminders_only_every_n_days(self):
        self.assertEqual(orf.HELD_REMIND_DAYS, 7)
        d = _d('a.md', '제1호', '가법')
        held = {'a.md>제1호': {'t': '가법', 'why': '잘림', 'since': '2026-11-12', 'last': '2026-11-12'}}
        self.assertEqual(orf.due_reminders(held, [d], '2026-11-13'), [])           # 다음 날은 조용
        self.assertEqual(orf.due_reminders(held, [d], '2026-11-18'), [])           # 6일째도 조용
        r = orf.due_reminders(held, [d], '2026-11-19')                              # 7일 지남
        self.assertEqual(r, [('a.md>제1호', '가법', '잘림', '2026-11-12', 8)])
        held['a.md>제1호']['last'] = '2026-11-19'                                   # 알린 날을 적으면 다시 7일
        self.assertEqual(orf.due_reminders(held, [d], '2026-11-25'), [])
        self.assertEqual(len(orf.due_reminders(held, [d], '2026-11-26')), 1)
        # 날짜가 깨져 있으면 조용히 잊히지 않게 알린다
        self.assertEqual(len(orf.due_reminders({'a.md>제1호': {'t': '가법'}}, [d], '2026-11-13')), 1)

    def test_report_shows_waiting_and_no_retry_note(self):
        msg = orf.format_refresh_report([], [('재난안전법 시행령', '출력이 max_tokens에서 잘림')], [], now='11/15 11:40')
        self.assertIn('자동 갱신 실패 1건', msg)
        self.assertIn('자동으로 다시 시도하지 않습니다', msg)
        self.assertIn('한 번 더', msg)
        w = [('a.md>제1호', '가법', '구판 요약 47,339자 > 자동 상한 — 세션 처리', '2026-11-12', 8)]
        msg2 = orf.format_refresh_report([], [], [], now='11/19 11:40', waiting=w)
        self.assertIn('세션 처리 대기 1건', msg2)
        self.assertIn('(11/19 11:40)', msg2)
        self.assertIn('2026-11-12부터 8일째', msg2)
        self.assertNotIn('자동 갱신 실패', msg2)
        # 대기가 없으면 예전 글자 그대로(대기 줄 없음)
        self.assertNotIn('세션 처리 대기', orf.format_refresh_report([], [('가', '나')], [], now='x'))


class TestLongSummaryAndSessionFile(unittest.TestCase):

    def test_too_long_for_auto_threshold(self):
        self.assertIsNone(orf.too_long_for_auto('가' * orf.OLD_BODY_AUTO_MAX))
        why = orf.too_long_for_auto('가' * (orf.OLD_BODY_AUTO_MAX + 1))
        self.assertIn('세션 처리', why)                 # 이 글자가 있어야 '실패'가 아니라 '보류'로 분류된다
        self.assertIsNone(orf.too_long_for_auto(''))
        self.assertIsNone(orf.too_long_for_auto(None))
        # 출력 상한 3.2만 토큰이 담는 분량(실측 ≈0.96토큰/자)보다 문턱이 낮아야 한다
        self.assertLess(orf.OLD_BODY_AUTO_MAX, orf.MAX_OUTPUT_TOKENS)

    def test_refresh_one_checks_length_before_model_call_and_file_skips_model(self):
        src = inspect.getsource(orf.refresh_one)
        i_file, i_long, i_call = src.index("getattr(args, 'from_file'"), src.index('too_long_for_auto('), src.index('call_model(')
        self.assertLess(i_file, i_long)
        self.assertLess(i_long, i_call)                 # 길이 보류가 모델 호출보다 앞
        # 세션 문서도 같은 검증·적재를 탄다(모델 호출만 건너뜀)
        self.assertLess(i_call, src.index('validate_output('))
        self.assertLess(src.index('validate_output('), src.index('write_kb('))
        self.assertEqual(src.count('validate_output('), 1)
        self.assertEqual(src.count('write_kb('), 1)

    def test_main_guards(self):
        src = inspect.getsource(orf.main)
        self.assertIn('a.retry_failed and not a.allow_api', src)        # 다시 호출은 비용 확인 뒤에만
        self.assertIn('a.from_file and len(drift) != 1', src)           # 세션 문서는 대상 1건에만
        self.assertIn("sb_client.heartbeat(sb, HELD_KEY", src)           # 기억 쓰기는 공용 heartbeat로만(#217)
        self.assertNotIn("table('system_health').upsert", inspect.getsource(orf))


if __name__ == '__main__':
    unittest.main()
