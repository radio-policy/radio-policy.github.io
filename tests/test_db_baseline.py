# -*- coding: utf-8 -*-
"""tools_db_baseline 마스킹·fail-closed 시험 (#227, 네트워크 없음).

docs/db_baseline/은 공개 저장소·GitHub Pages로 나간다. 마스킹이 빠지면 운영자 봇 토큰 같은 값이
누구나 여는 웹에 올라가므로, 규칙이 실제로 가리는지와 가리지 못한 값을 잡아 멈추는지를 고정한다.
값은 모두 가짜다.
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import tools_db_baseline as tdb  # noqa: E402

FAKE_TOKEN = '123456789:AAFakeFakeFakeFakeFakeFakeFakeFake_x'


class TestDbBaselineRedact(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        os.environ['TELEGRAM_CHAT_ID'] = '987654321'
        tdb._ENV_VALUES.clear()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        tdb._ENV_VALUES.clear()

    def _redact(self, text, chat_ids=()):
        counts = {}
        return tdb.redact(text, counts, list(chat_ids)), counts

    def test_bot_token_in_url(self):
        # 'bot<숫자>:'는 t와 숫자 사이에 단어 경계가 없다 — \b 규칙이면 놓친다(초안에서 실측)
        out, c = self._redact("url := 'https://api.telegram.org/bot%s/sendMessage';" % FAKE_TOKEN)
        self.assertNotIn(FAKE_TOKEN, out)
        self.assertEqual(c.get('telegram_bot_token'), 1)
        self.assertEqual(tdb.leftovers(out), [])

    def test_vault_literal_and_digest(self):
        out, c = self._redact("select vault.create_secret('s3cr3t-value-xyz', 'admin_report_cron_secret');\n"
                              "if encode(digest(p,'sha256'),'hex') is distinct from '%s' then" % ('ab' * 32))
        self.assertNotIn('s3cr3t-value-xyz', out)
        self.assertNotIn('ab' * 32, out)
        self.assertIn("'admin_report_cron_secret'", out)   # 이름은 남긴다
        self.assertEqual(tdb.leftovers(out), [])

    def test_chat_ids_operator_and_subscriber(self):
        out, c = self._redact("jsonb_build_object('chat_id', '987654321') -- 1122334455", ['1122334455'])
        self.assertIn('<OPERATOR_CHAT_ID>', out)
        self.assertIn('<CHAT_ID>', out)
        self.assertNotIn('987654321', out)
        self.assertNotIn('1122334455', out)
        # 더 긴 숫자의 일부는 건드리지 않는다
        out2, _ = self._redact("select 19876543210;")
        self.assertIn('19876543210', out2)

    def test_email_and_keys(self):
        out, _ = self._redact("-- owner someone@example.com key sk-ant-api03-%s ghp_%s"
                              % ('A' * 30, 'B' * 30))
        for s in ('someone@example.com', 'sk-ant-api03', 'ghp_BBBB'):
            self.assertNotIn(s, out)

    def test_leftovers_catch_unmasked_env_value(self):
        # 어느 정규식에도 안 걸리는 모양의 비밀도 .env 값과 같으면 멈춘다(fail-closed)
        tdb._ENV_VALUES['SOME_API_KEY'] = 'plainlookingsecretvalue'
        self.assertIn('env:SOME_API_KEY', tdb.leftovers("x := 'plainlookingsecretvalue';"))
        tdb._ENV_VALUES['SUPABASE_URL'] = 'https://zwkjedumfuhodckmtxxn.supabase.co'
        self.assertEqual(tdb.leftovers("'https://zwkjedumfuhodckmtxxn.supabase.co/functions/v1/x'"), [])

    def test_leftovers_random_string_and_allow(self):
        self.assertIn('random_40', tdb.leftovers("v := '%s';" % ('Zx9_' * 12)))
        self.assertEqual(tdb.leftovers("'daily_briefings_backup_id_seq_and_more_words'"), [])
        self.assertEqual(tdb.leftovers("'123e4567-e89b-12d3-a456-426614174000'"), [])

    def test_readme_passes_detector(self):
        # README 문구가 탐지기에 걸리면 매번 중단된다(첫 실행에서 실측)
        self.assertEqual(tdb.leftovers(tdb.README % {'ref': tdb.PROJECT_REF}), [])

    def test_queries_are_select_only(self):
        import re
        for key, sql in tdb.Q.items():
            self.assertRegex(sql, re.compile(r'^\s*(select|with)\b', re.I), key)
            self.assertNotRegex(sql.lower(), r'\bdecrypted_secret\b', key)   # Vault 값은 절대 읽지 않는다


if __name__ == '__main__':
    unittest.main()
