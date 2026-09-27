# -*- coding: utf-8 -*-
"""
refetch_content 실패 기사 미루기(#251 C5 — 10분마다 돌되 같은 기사 실패는 1시간에 1번만 재시도) 오프라인 테스트.
표준 unittest, 네트워크·DB 없음.

  - 순수 함수: 1시간 안 건너뜀·지나면 재시도, 7일 지난 기록 정리, 깨진·없는 파일 = 빈 기록,
    원자적 저장(도중 실패해도 옛 파일 그대로·임시 파일 안 남음), 바뀐 게 없으면 안 씀, 저장 실패는 멈추지 않음
  - main() 배선(가짜 DB·가짜 본문 수집): 미룬 기사는 긁지 않음, 실패 기록·성공 삭제, heartbeat note의 wait=N,
    할 일 없는 실행도 정리 저장, --all은 본문을 미루지 않음
  - 정부 공고 요약 미루기(열쇠 sum:<id>): 요약 백필·본문 저장 직후 요약 모두 한 시간 안 실패는 부르지 않음·지나면 다시·
    성공하면 삭제, 본문 기록과 열쇠가 겹치지 않음, 같은 실행 뒤쪽 백필이 방금 실패한 공고를 다시 부르지 않음,
    백필이 도는 때(할 일 없음이면 안 돎·대상이 모두 미뤄져도 돎)
  - 기록 파일이 .gitignore에 있는지(저장소가 공개 — Pages가 모든 파일을 내보낸다)

import 방식: refetch_content는 import 때 crawler.py를 exec한다(Supabase 클라이언트 '생성'·anthropic 등 import,
네트워크 호출 없음 — 2026-09-27 소켓 차단 상태로 확인, 처음 import ≈7초). tests/test_smoke.py와 같은 방식으로
더미 자격증명을 먼저 넣고 import한다(각 모듈의 load_dotenv는 이미 있는 값을 덮지 않는다).
"""
import contextlib
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 실 DB·API 자격증명 없이도 import 가능하도록 더미 선점 (클라이언트 생성만 되고 접속 없음) — test_smoke와 같다
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import refetch_content as rc  # noqa: E402

T0 = datetime(2026, 9, 27, 3, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.isoformat()


class _TmpDir(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='refetch_backoff_test_')
        self.path = os.path.join(self.dir, 'refetch_failures.json')

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, data, mode='w'):
        with open(self.path, mode, **({} if 'b' in mode else {'encoding': 'utf-8'})) as f:
            f.write(data)

    def _files(self):
        return sorted(os.listdir(self.dir))


class TestBackoffPure(_TmpDir):
    def test_skip_within_hour_then_retry(self):
        f = {}
        rc.record_failure(f, 'a1', T0)
        self.assertTrue(rc.should_skip(f, 'a1', T0))
        self.assertTrue(rc.should_skip(f, 'a1', T0 + timedelta(minutes=59, seconds=59)))
        self.assertFalse(rc.should_skip(f, 'a1', T0 + timedelta(minutes=60)))     # 60분이 지나면 다시
        self.assertFalse(rc.should_skip(f, 'a1', T0 + timedelta(hours=5)))
        self.assertFalse(rc.should_skip(f, 'other', T0))                          # 기록 없음

    def test_ids_are_strings(self):
        f = {}
        rc.record_failure(f, 123, T0)                    # 정수 id도 JSON 열쇠(문자열)로
        self.assertEqual(list(f), ['123'])
        self.assertTrue(rc.should_skip(f, '123', T0 + timedelta(minutes=1)))
        rc.clear_failure(f, 123)
        self.assertEqual(f, {})
        rc.clear_failure(f, 'none')                      # 없는 기록 지우기 = 조용히 넘어감

    def test_record_is_aware_utc_and_overwrites(self):
        f = {}
        rc.record_failure(f, 'a', T0)
        rc.record_failure(f, 'a', T0 + timedelta(hours=2))
        t = datetime.fromisoformat(f['a'])
        self.assertEqual(t, T0 + timedelta(hours=2))
        self.assertEqual(t.utcoffset(), timedelta(0))
        with mock.patch.object(rc, '_utcnow', return_value=T0):   # 시각을 안 주면 지금(UTC)
            rc.record_failure(f, 'b')
        self.assertEqual(f['b'], _iso(T0))

    def test_bad_or_future_timestamps_do_not_block(self):
        f = {'future': _iso(T0 + timedelta(minutes=5)),     # PC 시계가 되돌려진 경우 — 막지 않고 다시 시도
             'garbage': '어제쯤', 'num': 5,
             'naive': '2026-09-27T02:30:00'}                  # 시간대 없음 = UTC
        self.assertFalse(rc.should_skip(f, 'future', T0))
        self.assertFalse(rc.should_skip(f, 'garbage', T0))
        self.assertFalse(rc.should_skip(f, 'num', T0))
        self.assertTrue(rc.should_skip(f, 'naive', T0))       # 30분 전

    def test_prune_after_seven_days(self):
        f = {'old': _iso(T0 - timedelta(days=7, seconds=1)),
             'edge': _iso(T0 - timedelta(days=7)),
             'recent': _iso(T0 - timedelta(days=6)),
             'fresh': _iso(T0 - timedelta(minutes=5)),
             'soon': _iso(T0 + timedelta(minutes=5)),          # 조금 앞선 시각은 둔다(다음 시도가 덮어쓴다)
             'far_future': _iso(T0 + timedelta(days=2)),       # 시계 오류 — 영영 안 지워지므로 지운다
             'garbage': 'x'}
        self.assertEqual(rc.prune_failures(f, T0), 3)
        self.assertEqual(sorted(f), ['edge', 'fresh', 'recent', 'soon'])
        self.assertEqual(rc.prune_failures(f, T0), 0)

    def test_missing_and_corrupt_files_start_empty(self):
        self.assertEqual(rc.load_failures(self.path), {})                       # 없음
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self._write('{"a": "2026-09-27T03:00:00+00:00", ')                  # 쓰다 만 JSON
            self.assertEqual(rc.load_failures(self.path), {})
            self._write('[1, 2]')                                                # 사전이 아님
            self.assertEqual(rc.load_failures(self.path), {})
            self._write(b'\xff\xfe{}', mode='wb')                                # UTF-8 아님
            self.assertEqual(rc.load_failures(self.path), {})
        self.assertIn('빈 기록으로 시작', out.getvalue())
        self._write(json.dumps({'a': _iso(T0), 'b': 5, 'c': None, 'd': [1]}))   # 글 아닌 값은 버림
        self.assertEqual(rc.load_failures(self.path), {'a': _iso(T0)})

    def test_save_roundtrip_leaves_only_valid_json(self):
        f = {'b': _iso(T0), 'a': _iso(T0 - timedelta(hours=1))}
        rc.save_failures(f, self.path)
        self.assertEqual(self._files(), ['refetch_failures.json'])              # 임시 파일 안 남음
        with open(self.path, encoding='utf-8') as fh:
            self.assertEqual(json.load(fh), f)
        f2 = {'c': _iso(T0)}
        rc.save_failures(f2, self.path)                                          # 덮어쓰기
        self.assertEqual(rc.load_failures(self.path), f2)
        self.assertEqual(self._files(), ['refetch_failures.json'])

    def test_failed_save_keeps_old_file(self):
        rc.save_failures({'a': _iso(T0)}, self.path)
        with mock.patch.object(rc.os, 'replace', side_effect=OSError('파일 잠김')):   # 바꿔 끼우기 실패
            with self.assertRaises(OSError):
                rc.save_failures({'b': _iso(T0)}, self.path)
        with self.assertRaises(TypeError):                                       # 쓰는 도중 실패(직렬화 불가)
            rc.save_failures({'b': object()}, self.path)
        self.assertEqual(rc.load_failures(self.path), {'a': _iso(T0)})          # 옛 파일 그대로, 반쪽 JSON 없음
        self.assertEqual(self._files(), ['refetch_failures.json'])              # 임시 파일 정리됨

    def test_persist_only_when_changed_and_never_raises(self):
        f = {'a': _iso(T0)}
        rc._persist_failures(f, dict(f), self.path)
        self.assertEqual(self._files(), [])                                      # 바뀐 게 없으면 안 씀
        rc._persist_failures(f, {}, self.path)
        self.assertEqual(rc.load_failures(self.path), f)
        out = io.StringIO()
        with mock.patch.object(rc, 'save_failures', side_effect=OSError('디스크 가득')), \
                contextlib.redirect_stdout(out):
            rc._persist_failures({'b': _iso(T0)}, {}, self.path)                # 올리지 않고 알리기만
        self.assertIn('실패 기록 저장 오류', out.getvalue())

    def test_summary_key_namespace(self):
        """요약 실패(sum:<id>)와 본문 실패(<id>)는 같은 파일에서 서로를 막거나 지우지 않는다. 정리는 둘 다에 적용."""
        f = {}
        rc.record_failure(f, rc.summary_key('a1'), T0)
        self.assertEqual(list(f), ['sum:a1'])
        later = T0 + timedelta(minutes=1)
        self.assertFalse(rc.should_skip(f, 'a1', later))                           # 요약 실패가 본문을 막지 않는다
        self.assertTrue(rc.should_skip(f, rc.summary_key('a1'), later))
        rc.record_failure(f, 'a1', T0)
        rc.clear_failure(f, 'a1')                                                    # 본문 성공이 요약 기록을 지우지 않는다
        self.assertEqual(list(f), ['sum:a1'])
        self.assertFalse(rc.should_skip(f, rc.summary_key('a1'), T0 + timedelta(minutes=60)))   # 60분 지나면 다시
        rc.clear_failure(f, rc.summary_key('a1'))
        self.assertEqual(f, {})
        f = {'a1': _iso(T0 - timedelta(days=8)), 'sum:a1': _iso(T0 - timedelta(days=8)),
             'sum:a2': _iso(T0 + timedelta(days=2)), 'sum:a3': _iso(T0)}
        self.assertEqual(rc.prune_failures(f, T0), 3)
        self.assertEqual(list(f), ['sum:a3'])

    def test_default_file_is_next_to_script_and_gitignored(self):
        norm = lambda p: os.path.normcase(os.path.realpath(p))
        self.assertEqual(norm(os.path.dirname(rc.FAIL_FILE)), norm(_ROOT))
        with open(os.path.join(_ROOT, '.gitignore'), encoding='utf-8') as fh:
            lines = {ln.strip() for ln in fh}
        self.assertIn(os.path.basename(rc.FAIL_FILE), lines)
        self.assertIn('temp_*', lines)                   # 강제 종료로 남은 임시 파일(temp_refetch_failures_*.tmp)


# ── main() 배선 — 가짜 DB·본문 수집 ────────────────────────────────────────────────────────────
class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    """supabase 쿼리 사슬 흉내 — 거르기는 기록만 하고, 본문 재수집 대상 조회(url 칸 포함)만 기사를 돌려준다."""

    def __init__(self, db):
        self.db, self.op, self.cols, self.payload, self.filters = db, None, '', None, []

    def select(self, cols, *a, **k):
        self.op, self.cols = 'select', cols
        return self

    def delete(self, *a, **k):
        self.op = 'delete'
        return self

    def update(self, data, *a, **k):
        self.op, self.payload = 'update', data
        return self

    @property
    def not_(self):
        return self

    def __getattr__(self, name):                 # eq·lt·neq·is_·or_·order·limit
        if name.startswith('__'):
            raise AttributeError(name)

        def f(*a, **k):
            self.filters.append((name,) + a)
            return self
        return f

    def execute(self):
        self.db.calls.append((self.op, self.cols, self.payload, list(self.filters)))
        if self.op == 'select':                  # url 칸 = 본문 재수집 대상 조회, 아니면 정부 공고 요약 백필 조회
            return _Res([dict(a) for a in (self.db.articles if 'url' in self.cols else self.db.backfill)])
        return _Res([])


class _DB:
    def __init__(self, articles, backfill=None):
        self.articles, self.backfill, self.calls = articles, backfill or [], []

    def table(self, name):
        return _Q(self)


def _art(i, content=None):
    return {'id': f'a{i}', 'title': f'기사 {i}', 'source': '전자신문', 'url': f'https://example.com/n/{i}',
            'content': content, 'published_at': '2026-09-27T09:00:00+09:00', 'summary': None,
            'locked': False, 'category': '', 'urgency': '보통'}


def _gov(i, content='공고 본문 ' * 30, summary=None):
    """정부 공고(요약을 미리 만드는 유일한 대상, #153) — id g<i>, 제목 '공고 <i>'."""
    return {'id': f'g{i}', 'title': f'공고 {i}', 'source': '과학기술정보통신부 보도자료',
            'url': f'https://example.com/g/{i}', 'content': content, 'published_at': '2026-09-27T09:00:00+09:00',
            'summary': summary, 'locked': False, 'category': '', 'urgency': '참고'}


class TestMainWiring(_TmpDir):
    def _run(self, articles, fetch, now, argv=('refetch_content.py',), backfill=None, summarize=None,
             title_fixed=False):
        """main()을 가짜 DB로 한 번 돌린다. self.summaries = generate_summary가 불린 제목(순서대로)."""
        db, beats, fetched, net = _DB(articles, backfill), [], [], []
        self.summaries = []

        def fake_fetch(url, source):
            fetched.append(url.rsplit('/', 1)[-1])
            return fetch(url)

        def fake_summary(title, source, published_at, content):
            self.summaries.append(title)
            return summarize(title) if summarize else ''

        def no_net(*a, **k):
            net.append(a)
            raise OSError('시험 중 네트워크 금지')

        out = io.StringIO()
        with mock.patch.object(rc, 'FAIL_FILE', self.path), \
                mock.patch.object(rc, '_utcnow', return_value=now), \
                mock.patch.object(rc, 'make_client', return_value=db), \
                mock.patch.object(rc, 'sb_heartbeat', side_effect=lambda sb, k, n: beats.append((k, n))), \
                mock.patch.object(rc, '_fix_title_only', return_value=title_fixed), \
                mock.patch.object(rc.crawler, 'fetch_article_body', side_effect=fake_fetch), \
                mock.patch.object(rc.crawler, 'generate_summary', side_effect=fake_summary), \
                mock.patch.object(rc, 'DELAY_BETWEEN', 0), \
                mock.patch.object(rc.time, 'sleep'), \
                mock.patch.object(sys, 'argv', list(argv)), \
                mock.patch.object(socket.socket, 'connect', no_net), \
                contextlib.redirect_stdout(out):
            rc.main()
        self.assertEqual(net, [], '네트워크 시도가 있었다')
        return db, beats, fetched, out.getvalue()

    def test_backoff_flow(self):
        body = 'x' * 300

        def fetch(url):
            n = url.rsplit('/', 1)[-1]
            if n == '4':
                raise RuntimeError('일부러 낸 오류')
            return (body, '') if n in ('2', '5') else ('', '')

        rc.save_failures({'a1': _iso(T0 - timedelta(minutes=10)),     # 한 시간 안 → 이번엔 건너뜀
                          'a2': _iso(T0 - timedelta(hours=2)),        # 지남 → 재시도·성공 → 기록 삭제
                          'a5': _iso(T0 - timedelta(days=8)),         # 7일 지남 → 정리
                          'gone': _iso(T0 - timedelta(days=9))}, self.path)
        arts = [_art(1), _art(2), _art(3), _art(4), _art(5), _art(6, content='y' * 200)]
        db, beats, fetched, out = self._run(arts, fetch, T0)

        self.assertEqual(fetched, ['2', '3', '4', '5'])                  # a1은 긁지 않음, a6은 본문 있음
        self.assertEqual(rc.load_failures(self.path),
                         {'a1': _iso(T0 - timedelta(minutes=10)),        # 미룬 기록은 그대로(시각 갱신 안 함)
                          'a3': _iso(T0),                                # 본문 없음 → 기록
                          'a4': _iso(T0)})                               # 예외(❌ 실패) → 기록
        self.assertEqual(beats, [('last_refetch_run', 'ok=2 fail=1 skip=1 wait=1')])
        self.assertIn('⏳ 한 시간 안에 실패한 기사 1건 건너뜀', out)
        updated = sorted(c[3][0][2] for c in db.calls if c[0] == 'update')
        self.assertEqual(updated, ['a2', 'a5'])

        # 30분 뒤: a1·a3·a4 모두 한 시간 안 → 아무것도 긁지 않고 wait=3(할 일 없음이 아니다)
        fetched_before = len(fetched)
        db, beats, fetched, out = self._run([_art(1), _art(3), _art(4)], fetch, T0 + timedelta(minutes=30))
        self.assertEqual(fetched, [])
        self.assertEqual(beats, [('last_refetch_run', 'ok=0 fail=0 skip=0 wait=3')])
        self.assertIn('⏳ 한 시간 안에 실패한 기사 3건 건너뜀', out)
        self.assertGreater(fetched_before, 0)

        # 61분 뒤: a3·a4 다시 시도(a1은 71분 전 실패라 역시 재시도)
        db, beats, fetched, out = self._run([_art(1), _art(3), _art(4)], fetch, T0 + timedelta(minutes=61))
        self.assertEqual(fetched, ['1', '3', '4'])
        self.assertNotIn('⏳', out)
        self.assertEqual(beats, [('last_refetch_run', 'ok=0 fail=1 skip=2 wait=0')])

    def test_nothing_to_do_still_prunes(self):
        rc.save_failures({'old': _iso(T0 - timedelta(days=8)), 'new': _iso(T0 - timedelta(minutes=5))}, self.path)
        db, beats, fetched, out = self._run([_art(1, content='y' * 200)], lambda u: ('', ''), T0)
        self.assertEqual(beats, [('last_refetch_run', '할 일 없음')])
        self.assertEqual(fetched, [])
        self.assertEqual(rc.load_failures(self.path), {'new': _iso(T0 - timedelta(minutes=5))})

    def test_all_mode_does_not_wait(self):
        rc.save_failures({'a1': _iso(T0 - timedelta(minutes=10))}, self.path)
        db, beats, fetched, out = self._run([_art(1, content='y' * 200)], lambda u: ('z' * 300, ''), T0,
                                            argv=('refetch_content.py', '--all'))
        self.assertEqual(fetched, ['1'])                                     # 손 실행 --all은 미루지 않는다
        self.assertEqual(rc.load_failures(self.path), {})                   # 성공 → 기록 삭제
        self.assertEqual(beats, [('last_refetch_run', 'ok=1 fail=0 skip=0 wait=0')])

    def test_corrupt_file_does_not_stop_run(self):
        self._write('{깨진')
        db, beats, fetched, out = self._run([_art(3)], lambda u: ('', ''), T0)
        self.assertEqual(fetched, ['3'])
        self.assertEqual(beats, [('last_refetch_run', 'ok=0 fail=0 skip=1 wait=0')])
        self.assertEqual(rc.load_failures(self.path), {'a3': _iso(T0)})    # 깨진 파일은 새 기록으로 교체

    # ── 정부 공고 요약 미루기(sum:<id>) ──
    def test_summary_backfill_backoff(self):
        # 재수집 대상 a9는 한 시간 안 실패로 미뤄진다 — 대상이 모두 미뤄진 실행도 요약 백필까지는 간다
        rc.save_failures({'a9': _iso(T0 - timedelta(minutes=5)),
                          rc.summary_key('g3'): _iso(T0 - timedelta(minutes=10)),     # 한 시간 안 → 부르지 않음
                          rc.summary_key('g2'): _iso(T0 - timedelta(hours=2))},       # 지남 → 다시, 성공 → 삭제
                         self.path)
        backfill = [_gov(1), _gov(2), _gov(3), _gov(4, content='짧은 본문')]          # g4는 100자 미만 — 원래대로 대상 아님
        db, beats, fetched, out = self._run([_art(9)], lambda u: ('', ''), T0, backfill=backfill,
                                            summarize=lambda t: '요약' if t == '공고 2' else '')
        self.assertEqual(fetched, [])
        self.assertEqual(self.summaries, ['공고 1', '공고 2'])                         # g3 미룸
        self.assertIn('⏳ 한 시간 안에 요약 실패한 정부 공고 1건 건너뜀', out)
        self.assertEqual(rc.load_failures(self.path),
                         {'a9': _iso(T0 - timedelta(minutes=5)),
                          rc.summary_key('g1'): _iso(T0),                              # 빈 요약 → 기록
                          rc.summary_key('g3'): _iso(T0 - timedelta(minutes=10))})     # g2 성공 → 삭제
        self.assertEqual([(c[2], c[3][0][2]) for c in db.calls if c[0] == 'update'], [({'summary': '요약'}, 'g2')])
        self.assertEqual(beats, [('last_refetch_run', 'ok=0 fail=0 skip=0 wait=1')])  # 요약 미룸은 wait에 안 센다

        # 30분 뒤: g1(30분 전)·g3(40분 전) 모두 미룸 → 요약 호출 0, '모든 기사에 summary 있음'이라고 하지 않는다
        db, beats, fetched, out = self._run([_art(9)], lambda u: ('', ''), T0 + timedelta(minutes=30),
                                            backfill=[_gov(1), _gov(3)], summarize=lambda t: '요약')
        self.assertEqual(self.summaries, [])
        self.assertIn('⏳ 한 시간 안에 요약 실패한 정부 공고 2건 건너뜀', out)
        self.assertNotIn('모든 기사에 summary 있음', out)

        # 61분 뒤: 둘 다 다시 부른다 — g1 성공 → 삭제, g3 또 실패 → 시각 갱신
        db, beats, fetched, out = self._run([_art(9)], lambda u: ('', ''), T0 + timedelta(minutes=61),
                                            backfill=[_gov(1), _gov(3)],
                                            summarize=lambda t: '요약' if t == '공고 1' else '')
        self.assertEqual(self.summaries, ['공고 1', '공고 3'])
        f = rc.load_failures(self.path)
        self.assertNotIn(rc.summary_key('g1'), f)
        self.assertEqual(f[rc.summary_key('g3')], _iso(T0 + timedelta(minutes=61)))

    def test_backfill_not_run_when_nothing_to_refetch(self):
        """재수집 대상이 없으면 '할 일 없음'으로 끝나 요약 백필 조회 자체가 없다(기존 흐름 그대로)."""
        db, beats, fetched, out = self._run([_art(1, content='y' * 200)], lambda u: ('', ''), T0,
                                            backfill=[_gov(1)], summarize=lambda t: '요약')
        self.assertEqual(beats, [('last_refetch_run', '할 일 없음')])
        self.assertEqual(self.summaries, [])
        self.assertEqual([c for c in db.calls if c[0] == 'select' and 'url' not in c[1]], [])

    def test_summary_after_body_fetch_backoff(self):
        body = 'z' * 300
        rc.save_failures({rc.summary_key('g8'): _iso(T0 - timedelta(minutes=10))}, self.path)
        # 백필 조회가 방금 본문을 저장한(요약은 실패한) g7을 돌려준다 — 같은 실행에서 다시 부르면 안 된다
        db, beats, fetched, out = self._run([_gov(7, content=None), _gov(8, content=None)], lambda u: (body, ''), T0,
                                            backfill=[_gov(7, content=body)], summarize=lambda t: '')
        self.assertEqual(fetched, ['7', '8'])                                     # 본문은 둘 다 긁는다
        self.assertEqual(self.summaries, ['공고 7'])                               # g8 요약 미룸, g7 백필에서 안 부름
        self.assertIn('⏳ 요약 미룸', out)
        self.assertIn('⏳ 한 시간 안에 요약 실패한 정부 공고 1건 건너뜀', out)
        self.assertEqual(rc.load_failures(self.path),
                         {rc.summary_key('g7'): _iso(T0),                          # 본문은 성공 → 본문 기록(g7) 없음
                          rc.summary_key('g8'): _iso(T0 - timedelta(minutes=10))})
        updates = [c[2] for c in db.calls if c[0] == 'update']
        self.assertEqual(len(updates), 2)
        self.assertTrue(all('summary' not in u and u['content'] == body for u in updates))   # 본문만 저장
        self.assertEqual(beats, [('last_refetch_run', 'ok=2 fail=0 skip=0 wait=0')])

        # 61분 뒤 요약이 되면 본문과 함께 저장하고 기록을 지운다(g8은 71분 전 실패라 역시 다시)
        db, beats, fetched, out = self._run([_gov(7, content=None), _gov(8, content=None)], lambda u: (body, ''),
                                            T0 + timedelta(minutes=61), summarize=lambda t: '요약')
        self.assertEqual(self.summaries, ['공고 7', '공고 8'])
        self.assertEqual([c[2].get('summary') for c in db.calls if c[0] == 'update'], ['요약', '요약'])
        self.assertEqual(rc.load_failures(self.path), {})

    def test_summary_kept_when_body_unchanged(self):
        """요약이 있고 새 본문이 저장된 본문과 같으면(앞뒤 공백 무시) 요약을 다시 만들지 않는다 — 100자 미만 본문은
        성공해도 매 실행 다시 오므로(국립전파연구원 51~99자). 본문이 바뀌었거나 요약이 없거나 빈 글이면 종전대로 부른다."""
        short = '전파 공고 본문 ' * 7                                     # 63자 — 저장돼도 다음 실행에 또 대상
        bodies = {'1': short, '2': short, '3': 'B' * 60, '4': short, '5': short}
        arts = [_gov(1, content=short, summary='기존 요약'),                 # 같은 본문 + 요약 → 안 부름
                _gov(2, content=' ' + short + '\n', summary='기존 요약'),    # 앞뒤 공백만 다름 → 안 부름
                _gov(3, content='A' * 60, summary='기존 요약'),              # 본문 바뀜 → 부름
                _gov(4, content=short, summary=None),                        # 요약 없음 → 부름
                _gov(5, content=short, summary='  ')]                        # 빈 요약 → 부름
        db, beats, fetched, out = self._run(arts, lambda u: (bodies[u.rsplit('/', 1)[-1]], ''), T0,
                                            summarize=lambda t: '새 요약')
        self.assertEqual(fetched, ['1', '2', '3', '4', '5'])                 # 본문 재수집 자체는 그대로
        self.assertEqual(self.summaries, ['공고 3', '공고 4', '공고 5'])
        self.assertEqual(out.count(' (요약 유지 — 본문 같음)'), 2)
        ups = {c[3][0][2]: c[2] for c in db.calls if c[0] == 'update'}
        self.assertNotIn('summary', ups['g1'])                                # 기존 요약을 건드리지 않는다
        self.assertNotIn('summary', ups['g2'])
        self.assertEqual([ups[k]['summary'] for k in ('g3', 'g4', 'g5')], ['새 요약'] * 3)
        # 본문이 모두 100자 미만이라 저장은 했어도 실패처럼 기록된다(다음 실행에 또 대상 — 한 시간 뒤에 다시)
        self.assertEqual(rc.load_failures(self.path), {f'g{i}': _iso(T0) for i in range(1, 6)})
        self.assertEqual(beats, [('last_refetch_run', 'ok=5 fail=0 skip=0 wait=0')])

    def test_short_body_saved_then_backed_off(self):
        """100자 미만 본문은 저장하되 실패처럼 기록 → 60분 안에는 다시 긁지 않고, 지나면 다시 긁는다.
        기록을 지우는 것은 100자 이상 본문 저장뿐이다(제목만 고친 경우도 기록)."""
        short, long_ = 'S' * 70, 'L' * 150
        rc.save_failures({'a8': _iso(T0 - timedelta(hours=2))}, self.path)
        db, beats, fetched, out = self._run([_art(7), _art(8)], lambda u: (short if u.endswith('/7') else long_, ''), T0)
        self.assertEqual(fetched, ['7', '8'])
        self.assertEqual([(c[3][0][2], c[2]['content']) for c in db.calls if c[0] == 'update'],
                         [('a7', short), ('a8', long_)])                         # 짧은 본문도 종전대로 저장
        self.assertEqual(rc.load_failures(self.path), {'a7': _iso(T0)})        # a7 기록, a8(150자) 기록 삭제
        self.assertEqual(beats, [('last_refetch_run', 'ok=2 fail=0 skip=0 wait=0')])

        # 30분 뒤: DB에는 짧은 본문이 저장돼 있어 여전히 대상 — 그러나 한 시간 안이라 긁지 않는다
        db, beats, fetched, out = self._run([_art(7, content=short)], lambda u: (short, ''), T0 + timedelta(minutes=30))
        self.assertEqual(fetched, [])
        self.assertEqual([c for c in db.calls if c[0] == 'update'], [])
        self.assertIn('⏳ 한 시간 안에 실패한 기사 1건 건너뜀', out)
        self.assertEqual(beats, [('last_refetch_run', 'ok=0 fail=0 skip=0 wait=1')])

        # 61분 뒤: 다시 긁고(여전히 짧음) 기록 시각을 새로 적는다
        db, beats, fetched, out = self._run([_art(7, content=short)], lambda u: (short, ''), T0 + timedelta(minutes=61))
        self.assertEqual(fetched, ['7'])
        self.assertEqual(rc.load_failures(self.path), {'a7': _iso(T0 + timedelta(minutes=61))})

        # 그다음 100자 이상이 들어오면 기록을 지운다
        db, beats, fetched, out = self._run([_art(7, content=short)], lambda u: (long_, ''), T0 + timedelta(minutes=125))
        self.assertEqual(fetched, ['7'])
        self.assertEqual(rc.load_failures(self.path), {})

    def test_title_only_fix_is_recorded(self):
        """본문은 못 받고 제목만 고친 기사도 다음 실행에 또 대상이라 기록한다(ok로 세는 것은 종전 그대로)."""
        rc.save_failures({'a3': _iso(T0 - timedelta(hours=2))}, self.path)
        db, beats, fetched, out = self._run([_art(3)], lambda u: ('', ''), T0, title_fixed=True)
        self.assertIn('📝 제목만 보정', out)
        self.assertEqual(rc.load_failures(self.path), {'a3': _iso(T0)})
        self.assertEqual(beats, [('last_refetch_run', 'ok=1 fail=0 skip=0 wait=0')])

    def test_summary_exception_is_recorded_and_flow_unchanged(self):
        def boom(title):
            raise RuntimeError('요약 API 오류')
        db, beats, fetched, out = self._run([_gov(5, content=None)], lambda u: ('z' * 300, ''), T0,
                                            backfill=[_gov(6)], summarize=boom)
        self.assertIn('❌ 실패: 요약 API 오류', out)                                # 저장 전 예외 → 종전대로 ❌ 실패
        self.assertIn('[요약 백필 오류] 요약 API 오류', out)                        # 백필 예외 → 종전대로 중단
        self.assertEqual(rc.load_failures(self.path),
                         {'g5': _iso(T0), rc.summary_key('g5'): _iso(T0), rc.summary_key('g6'): _iso(T0)})
        self.assertEqual(beats, [('last_refetch_run', 'ok=0 fail=1 skip=0 wait=0')])


if __name__ == '__main__':
    unittest.main()
