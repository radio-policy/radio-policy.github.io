# -*- coding: utf-8 -*-
"""이슈맵 뉴스 관련 판정 실측 도구(tools_issue_judge_probe.py, 10-12 판정 §3)의 V0가 운영 요청과 같은지 — 네트워크 0.
운영 issue_suggest._haiku_relate_batch(kind='news')가 실제로 보내는 요청(가짜 Anthropic이 받는 kwargs)과
도구가 V0로 만드는 요청을 픽스처의 모든 호출에서 대조한다. 운영 지시문·입력 모양을 바꾸면 이 테스트가 깨진다 —
도구로 다시 재고(판정 §3 통과 기준 P1~P6) 둘을 함께 고친다."""
import json
import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


class TestIssueJudgeProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tools_issue_judge_probe as P
        cls.P = P
        with open(P.FIXTURE, encoding='utf-8') as f:
            cls.fx = json.load(f)

    def _production_request(self, call):
        import issue_suggest as isg
        sent = {}

        class _Msgs:
            def create(self, **kw):
                sent.update(kw)
                raise RuntimeError('stop')     # 요청만 받고 끝 — 호출 실패는 보류(None, #296-보론3)

        class _Client:
            def __init__(self, *a, **k):
                self.messages = _Msgs()

        groups = [[{'id': r['id'], 'title': r['title']} for r in g['members']] for g in call['groups']]
        pairs = [(ci, g['members'][0]['title'], {'id': g['issue'], **self.fx['issues'][str(g['issue'])]})
                 for ci, g in enumerate(call['groups'])]
        import anthropic
        with mock.patch.object(isg, 'ANTHROPIC_API_KEY', 'test'), mock.patch.object(anthropic, 'Anthropic', _Client):
            got = isg._haiku_relate_batch(pairs, groups)
        self.assertIsNone(got)
        return sent

    def test_v0_equals_production_request(self):
        for call in self.fx['calls']:
            prod = self._production_request(call)
            kw, slots = self.P.build_request('V0', call, self.fx['issues'])
            self.assertEqual(kw, prod, call['run'])
            self.assertEqual(len(slots), len(call['groups']))

    def test_fixture_gold_covers_scored_pairs(self):
        """점수 대상(새 기사)마다 정답이 있다 — 정답이 빠지면 조용히 점수 밖으로 새므로 막는다."""
        gold = self.fx['gold']
        for call in self.fx['calls']:
            for g in call['groups']:
                for r in g['members']:
                    if r['fresh']:
                        self.assertIn(r['id'], gold.get(str(g['issue']), {}), (call['run'], g['gid']))
                        self.assertIn(gold[str(g['issue'])][r['id']], ('해당', '해당 없음', '경계'))

    def test_variants_number_every_scored_article_once(self):
        """B·B2는 새 기사마다 번호 하나, V0·A1은 묶음마다 번호 하나 — 답 번호가 채점 단위로 정확히 풀린다."""
        for call in self.fx['calls']:
            fresh = {(g['issue'], r['id']) for g in call['groups'] for r in g['members'] if r['fresh']}
            for v in ('B', 'B2'):
                kw, slots = self.P.build_request(v, call, self.fx['issues'])
                flat = [p for s in slots for p in s]
                self.assertEqual(len(flat), len(set(flat)))
                self.assertEqual(set(flat), fresh)
                text = kw['messages'][0]['content']
                for k in range(1, len(slots) + 1):
                    self.assertIn(f'  {k}. 기사: "', text)
            kw, slots = self.P.build_request('A1', call, self.fx['issues'])
            self.assertEqual({p for s in slots for p in s}, fresh)
            self.assertEqual(kw['messages'], self.P.build_request('V0', call, self.fx['issues'])[0]['messages'])

    def test_news_truncation_is_hold(self):
        """뉴스 판정 응답이 max_tokens에서 잘리면 로그를 찍고 None(보류) — '소속 아님'(빈 집합)이 아니다(#296-보론3, 10-12 운영자 승인;
        그 전 #296-보론2는 로그만 넣고 빈 집합을 유지했다). 요청(지시문·max_tokens)은 그대로 — test_v0_equals_production_request."""
        import io
        import contextlib
        import issue_suggest as isg
        import anthropic

        class _Block:
            text = '각 항목을 판정합니다.\n1. … → 해당\n2. …'

        class _Resp:
            content = [_Block()]
            stop_reason = 'max_tokens'

        class _Client:
            def __init__(self, *a, **k):
                self.messages = self

            def create(self, **kw):
                return _Resp()

        call = self.fx['calls'][0]
        groups = [[{'id': r['id'], 'title': r['title']} for r in g['members']] for g in call['groups']]
        pairs = [(ci, g['members'][0]['title'], {'id': g['issue'], **self.fx['issues'][str(g['issue'])]})
                 for ci, g in enumerate(call['groups'])]
        buf = io.StringIO()
        with mock.patch.object(isg, 'ANTHROPIC_API_KEY', 'test'), mock.patch.object(anthropic, 'Anthropic', _Client), \
                contextlib.redirect_stdout(buf):
            got = isg._haiku_relate_batch(pairs, groups)
        self.assertIsNone(got)
        self.assertIn('[관련 판정 응답 잘림(보류)]', buf.getvalue())

    def test_parse_belong_like_production(self):
        pb = self.P.parse_belong
        self.assertEqual(pb('{"belong": [3, 1, 9]}', 5), [1, 3])
        self.assertEqual(pb('설명 {"belong": []}', 5), [])
        self.assertIsNone(pb('번호 없음', 5))


if __name__ == '__main__':
    unittest.main()
