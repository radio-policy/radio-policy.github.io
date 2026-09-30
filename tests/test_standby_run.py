# -*- coding: utf-8 -*-
"""lampmanH-pc 자동 대체 실행기(standby_run.py, #265-보론2) — 네트워크 없는 시험."""
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import standby_run as sr  # noqa: E402


class TestDecide(unittest.TestCase):
    def test_no_guard_always_runs(self):
        self.assertEqual(sr.decide(None, None)[0], 'run')
        self.assertEqual(sr.decide(None, 0.01)[0], 'run')

    def test_recent_skips(self):
        self.assertEqual(sr.decide(('last_refetch_run', 0.25), 0.07)[0], 'skip')
        self.assertEqual(sr.decide(('last_gov_notice_run', 20), 0.75)[0], 'skip')

    def test_stale_runs(self):
        self.assertEqual(sr.decide(('last_refetch_run', 0.25), 0.3)[0], 'run')
        # 어제 16:31 회사 PC 실행 → 오늘 17:15 = 24.7h → 대신 실행
        self.assertEqual(sr.decide(('last_gov_notice_run', 20), 24.7)[0], 'run')

    def test_lookup_failure_is_fail_open(self):
        verdict, why = sr.decide(('last_gov_notice_run', 20), None)
        self.assertEqual(verdict, 'run')
        self.assertIn('fail-open', why)


class TestCompanyPcDetection(unittest.TestCase):
    COMPANY = '[core]\n\tbare = false\n[remote "gitlab"]\n\turl = https://gitlab.com/x.git\n[remote "origin"]\n'
    STANDBY = '[core]\n\tbare = false\n[remote "origin"]\n\turl = https://gitlab.com/x.git\n'

    def test_detect(self):
        self.assertTrue(sr.has_gitlab_remote(self.COMPANY))
        self.assertFalse(sr.has_gitlab_remote(self.STANDBY))
        self.assertFalse(sr.has_gitlab_remote(''))

    def test_main_refuses_on_company_pc_before_touching_db(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, '.git'))
            with open(os.path.join(d, '.git', 'config'), 'w', encoding='utf-8') as f:
                f.write(self.COMPANY)
            old = sr.HERE
            cwd = os.getcwd()
            sr.HERE = d
            try:
                self.assertEqual(sr.main(['chain']), 3)    # pull·DB·실행 전에 멈춘다
            finally:
                sr.HERE = old
                os.chdir(cwd)

    def test_bad_args(self):
        self.assertEqual(sr.main([]), 2)
        self.assertEqual(sr.main(['nope']), 2)


class TestJobsTable(unittest.TestCase):
    def test_jobs_and_targets_exist(self):
        self.assertEqual(set(sr.JOBS), {'refetch', 'chain', 'briefing', 'summary'})
        for job, spec in sr.JOBS.items():
            self.assertTrue(os.path.exists(os.path.join(ROOT, spec['run'][1])), job)

    def test_only_chain_pulls(self):
        self.assertEqual([j for j, s in sr.JOBS.items() if s.get('pull')], ['chain'])

    def test_guards(self):
        self.assertEqual(sr.JOBS['refetch']['guard'], ('last_refetch_run', 0.25))
        self.assertEqual(sr.JOBS['chain']['guard'], ('last_gov_notice_run', 20))
        self.assertIsNone(sr.JOBS['briefing']['guard'])   # already_sent_today가 막는다
        self.assertIsNone(sr.JOBS['summary']['guard'])    # summary NULL만 — 멱등

    def test_build_cmd(self):
        self.assertEqual(sr.build_cmd(('bat', 'run_gov_crawler.bat')), ['cmd', '/c', 'run_gov_crawler.bat'])
        self.assertEqual(sr.build_cmd(('py', 'refetch_content.py')), [sys.executable, '-u', 'refetch_content.py'])


class TestSetupScript(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, 'setup_standby_tasks.ps1'), 'rb') as f:
            self.raw = f.read()
        self.text = self.raw.decode('ascii')   # 비ASCII면 여기서 실패 — PS 5.1은 BOM 없는 .ps1을 ANSI로 읽는다

    def test_registers_every_job_through_the_runner(self):
        jobs = set(re.findall(r"^Register-Standby '[^']+' .*?'(\w+)' \d+ \$(?:true|false)", self.text, re.M | re.S))
        self.assertEqual(jobs, set(sr.JOBS))
        self.assertIn('run_hidden.py standby_run.py standby_${job}_sched.log $job', self.text)

    def test_refuses_company_pc_and_enabled_old_tasks(self):
        self.assertIn(r'\[remote "gitlab"\]', self.text)
        self.assertIn('Old unguarded task', self.text)

    def test_briefing_runs_before_company_pc(self):
        # 회사 PC 09:50보다 먼저 — 겹치면 둘 다 '안 보냄'을 보고 두 번 보낸다
        m = re.search(r"'RadioPolicy-Standby-Briefing' \(New-ScheduledTaskTrigger -Daily -At '(\d\d):(\d\d)'\)", self.text)
        self.assertIsNotNone(m)
        self.assertLess((int(m.group(1)), int(m.group(2))), (9, 50))


if __name__ == '__main__':
    unittest.main()
