# -*- coding: utf-8 -*-
"""pc_backup.py 순수 함수 시험(#320) — 가짜 값만 쓴다. 네트워크·실제 비밀 파일 0."""
import base64
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pc_backup as pb  # noqa: E402


def _jwt(role):
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=")
    return b"eyJ" + b({"alg": "HS256"})[3:] + b"." + b({"role": role, "iss": "supabase"}) + b".sigSIGsig123456"


class TestMask(unittest.TestCase):
    SECRETS = {b"FAKE-env-secret-0123456789": ".env:FAKE_KEY", b"short-but-8+": ".env:X_TOKEN"}

    def test_same_length_and_hidden(self):
        data = ('{"a":"FAKE-env-secret-0123456789 그리고 short-but-8+ 끝"}\n'
                'ghp_' + 'A' * 36 + ' glpat-' + 'b' * 20 + ' sk-ant-api03-' + 'c' * 30 + '\n').encode("utf-8")
        out = pb.mask(data, self.SECRETS)
        self.assertEqual(len(out), len(data))
        for s in (b"FAKE-env-secret", b"short-but-8+", b"ghp_A", b"glpat-b", b"sk-ant-api03"):
            self.assertNotIn(s, out)
        self.assertIn("그리고".encode("utf-8"), out)
        self.assertEqual(pb.find_labels(out, self.SECRETS), set())
        self.assertEqual(pb.find_labels(data, self.SECRETS),
                         {".env:FAKE_KEY", ".env:X_TOKEN", "token:gh", "token:glpat", "token:sk-ant"})

    def test_jwt_only_service_role(self):
        anon, svc = _jwt("anon"), _jwt("service_role")
        data = b"anon=" + anon + b" svc=" + svc
        out = pb.mask(data, {})
        self.assertIn(anon, out)
        self.assertNotIn(svc, out)
        self.assertEqual(len(out), len(data))
        self.assertEqual(pb.find_labels(b"x " + anon, {}), set())

    def test_word_boundary_gh(self):
        self.assertEqual(pb.find_labels(b"xghp_" + b"A" * 36, {}), set())


class TestNamesAndPaths(unittest.TestCase):
    def test_project_dir_rule(self):
        self.assertEqual(pb.re.sub(r"[^A-Za-z0-9]", "-", r"C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai"),
                         "C--Users-SKTelecom-Desktop-frequence-radio-policy-ai")

    def test_excludes(self):
        for n in (".env", ".env.local", "prod.env", ".credentials.json", ".gitlab-credentials", ".confluence_pat",
                  "key.PEM"):
            self.assertTrue(pb._matches(n, pb.EXCLUDE_FILES), n)
        for n in ("a.jsonl", "MEMORY.md", "environment.md", "settings.json"):
            self.assertFalse(pb._matches(n, pb.EXCLUDE_FILES), n)

    def test_app_sessions_dir_order(self):
        with tempfile.TemporaryDirectory() as t:
            local, roaming = os.path.join(t, "Local"), os.path.join(t, "Roaming")
            self.assertEqual(pb.app_sessions_dir(local, roaming),
                             os.path.join(roaming, "Claude", "claude-code-sessions"))
            old = os.path.join(local, "Packages", "Claude_x1", "LocalCache", "Roaming", "Claude", "claude-code-sessions")
            os.makedirs(old)
            self.assertEqual(pb.app_sessions_dir(local, roaming), old)
            # 10-20 앱 업데이트 뒤 위치가 옛 패키지 폴더보다 먼저
            new = os.path.join(local, "Claude-Data", "claude_x1", "claude-code-sessions")
            os.makedirs(new)
            self.assertEqual(pb.app_sessions_dir(local, roaming), new)

    def test_no_mirror_flags(self):
        with open(pb.__file__, encoding="utf-8") as f:
            src = f.read()
        code = src.split('"""', 2)[2]          # 머리말 설명 밖(코드)에서만
        for flag in ("/MIR", "/PURGE", "/MOV"):
            self.assertNotIn('"%s' % flag, code)


class TestRestoreGuide(unittest.TestCase):
    """#320-보론 — 복구 안내가 백업 맨 위에 복사되고, 안내 자체에 비밀값 꼴이 없다(공개 저장소 문서)."""

    def test_copy_then_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(pb.copy_restore_guide(d))
            self.assertFalse(pb.copy_restore_guide(d))      # 같으면 다시 안 씀(드라이브 재업로드 없음)
            with open(os.path.join(d, pb.RESTORE_GUIDE_NAME), "rb") as f, open(pb.RESTORE_GUIDE, "rb") as g:
                self.assertEqual(f.read(), g.read())

    def test_guide_is_claude_runbook_without_secrets(self):
        with open(pb.RESTORE_GUIDE, "rb") as f:
            data = f.read()
        text = data.decode("utf-8")
        self.assertIn("이 파일을 받은 Claude에게", text)
        self.assertIn("/XC /XN /XO", text)                 # 복구는 없는 파일만 채운다
        for flag in ("/MIR", "/PURGE"):
            self.assertNotIn("robocopy \"<원본>\" \"<대상>\" %s" % flag, text)
        self.assertEqual(pb.find_labels(data, {}), set())


class TestSecretFiles(unittest.TestCase):
    """#320-보론2 — .env·.gitlab-credentials만 비밀파일\\로 원본 그대로, 같으면 다시 안 씀, 없으면 이름만 알림."""

    def test_list_is_env_and_gitlab_only(self):
        self.assertEqual([n for n, _ in pb.SECRET_FILES], [".env", ".gitlab-credentials"])
        self.assertNotIn(".confluence_pat", " ".join(p for _, p in pb.SECRET_FILES))

    def test_copy_unchanged_missing(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.env")
            with open(a, "wb") as f:
                f.write(b"FAKE_KEY=fake-value-123\n")
            files = [(".env", a), (".gitlab-credentials", os.path.join(d, "none"))]
            dest = os.path.join(d, "bak")
            self.assertEqual(pb.copy_secret_files(dest, files), (1, 1, [".gitlab-credentials"]))
            with open(os.path.join(dest, pb.SECRET_DIR, ".env"), "rb") as f:
                self.assertEqual(f.read(), b"FAKE_KEY=fake-value-123\n")
            self.assertEqual(pb.copy_secret_files(dest, files), (1, 0, [".gitlab-credentials"]))   # 같으면 다시 안 씀
            with open(a, "wb") as f:
                f.write(b"FAKE_KEY=changed\n")
            self.assertEqual(pb.copy_secret_files(dest, files)[1], 1)


class TestPrepassFlow(unittest.TestCase):
    """비밀값이 든 파일: 가린 사본이 원본과 같은 크기·시각으로 먼저 놓인다(robocopy가 건너뛰는 조건)."""

    def test_masked_copy_matches_size_and_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "src"), os.path.join(d, "dst")
            os.makedirs(os.path.join(src, "sub"))
            with open(os.path.join(src, "sub", "t.jsonl"), "wb") as f:
                f.write(b'{"x":"FAKE-env-secret-0123456789"}\n')
            with open(os.path.join(src, "clean.md"), "wb") as f:
                f.write(b"nothing here\n")
            cache = {"fp": "x", "items": {}}
            st = {"scanned": 0, "scanned_bytes": 0, "unstable": 0, "masked_written": 0, "post_masked": 0,
                  "labels": {}}
            hits = pb.prepass("k", src, dst, None, TestMask.SECRETS, cache, st)
            self.assertEqual(hits, ["t.jsonl"])
            s, t = os.stat(os.path.join(src, "sub", "t.jsonl")), os.stat(os.path.join(dst, "sub", "t.jsonl"))
            self.assertEqual((s.st_size, s.st_mtime_ns), (t.st_size, t.st_mtime_ns))
            with open(os.path.join(dst, "sub", "t.jsonl"), "rb") as f:
                self.assertNotIn(b"FAKE", f.read())
            self.assertFalse(os.path.exists(os.path.join(dst, "clean.md")))   # 깨끗한 파일은 robocopy 몫
            st2 = dict(st, masked_written=0, scanned=0)
            pb.prepass("k", src, dst, None, TestMask.SECRETS, cache, st2)   # 두 번째: 다시 안 씀
            self.assertEqual((st2["scanned"], st2["masked_written"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
