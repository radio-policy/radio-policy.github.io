# -*- coding: utf-8 -*-
"""
세션 작업물 PC 백업 (#320, 2026-10-18, 운영자 결정 「이해했어, 진행해 줘」)

회사 PC에만 있는 「클로드 세션에서 작업한 내용」 — 세션 전사본·메모리·local_docs(git 무시: 설계·판정·준비자료·
인계문)·앱 세션 목록·과방위 발언 원문·예약 작업 정의 — 를 매일 %USERPROFILE%\\PC백업\\ 아래로 복사한다.
그 폴더를 구글 드라이브 데스크톱 앱의 「내 컴퓨터」 백업이 올린다(앱 설치·로그인·폴더 지정은 운영자 몫).
코드·커밋된 문서는 GitLab/GitHub에 있으니 대상이 아니다. 복구 절차: docs/PC백업_복구절차.md

  백업 폴더                           원본
  claude-projects\\<프로젝트 폴더>    %USERPROFILE%\\.claude\\projects\\<프로젝트 폴더> (전사본·하위 폴더·memory)
  claude\\                            %USERPROFILE%\\.claude\\CLAUDE.md·settings.json
  local_docs\\                        이 저장소\\local_docs
  claude-code-sessions\\              Claude 앱 세션 목록 — 스토어 앱이면 %LOCALAPPDATA%\\Packages\\Claude_<id>\\LocalCache\\
                                      Roaming\\Claude\\claude-code-sessions(앱 안에서는 %APPDATA%\\Claude로 보임), 아니면 %APPDATA%
  과방위_발언원문\\                    이 저장소의 상위 폴더\\과방위_발언원문 (SPEECH_RAW_DIR)
  예약작업\\                          전파정책_*·RadioPolicy-*·radio_TEMP_* 작업 XML + _tasks.csv(상태표)
  _log\\ · _state\\ · 마지막_백업.txt  월별 실행 로그 · 비밀값 훑기 캐시(경로·항목 이름만) · 마지막 실행 요약

<프로젝트 폴더> = 이 저장소 경로에서 영숫자가 아닌 글자를 모두 '-'로 바꾼 이름(Claude Code 규칙 —
C:\\Users\\SKTelecom\\Desktop\\frequence\\radio-policy-ai → C--Users-SKTelecom-Desktop-frequence-radio-policy-ai).
경로는 환경 변수와 이 파일 위치로만 계산한다 — 회사 PC 경로를 박지 않는다(#178).

- **삭제 없는 복사**: robocopy /E 만 쓴다(/MIR·/PURGE 금지) — 앱이 지운 옛 전사본도 백업엔 남는다. 바뀐 파일은
  새 판으로 덮인다(옛 판은 드라이브의 판 기록에).
- **비밀값 가림**: 전사본에는 세션이 읽은 토큰이 섞여 있다(10-18 실측 — 봇 토큰·GitLab·GitHub 토큰 등 20여 개 파일).
  robocopy 전에 원본을 훑어(바뀐 파일만 — _state 캐시) 비밀값이 든 파일은 **같은 길이의 '*'로 가린 사본**을 먼저 쓰고
  원본과 같은 수정 시각을 붙인다 → robocopy는 크기·시각이 같은 파일로 보고 건너뛴다(이름으로 /XF에도 넣는다).
  그래서 원문이 백업 폴더에 놓이지 않는다. 훑기와 robocopy 사이에 바뀐 파일은 robocopy 뒤에 백업 쪽을 다시 훑어 가린다.
  비밀값은 실행 때마다 .env(이름에 KEY·TOKEN·SECRET·PASSWORD·CLIENT_ID)·~/.gitlab-credentials·~/.git-credentials·
  ~/.confluence_pat·~/.claude/.credentials.json에서 읽어 메모리에만 두고(공개 문서에 이미 실린 값은 뺀다), 토큰 꼴
  (sk-ant-·github_pat_·ghp_ 등·glpat-·sbp_·sb_secret_·service_role JWT)도 가린다. 로그·캐시에는 항목 이름만 남는다.
- **안 가져가는 것**: 비밀 파일(.env*·.credentials.json·.gitlab-credentials·.confluence_pat·*.pem)·__pycache__·.git·
  사내판 전사본(C--claude-rp-internal-*)·사내판 폴더·frequence\\confluence·docs\\사내공유_* — 개인 드라이브에
  사내 자료를 두지 않는다(뒤의 넷은 원본 목록에 아예 없다).
- 끝에 원본과 백업의 파일 수·용량을 대조한다(실행 중 바뀐 파일은 빠짐으로 세지 않는다). 빠짐·robocopy 실패(코드 8 이상)·
  원본 없음·예약 작업 내보내기 실패면 종료 코드 1 + 운영자 텔레그램 한 줄.

사용:
  작업 스케줄러(setup_pc_backup.ps1 — RadioPolicy-PCBackup, 매일 23:30, 창 없음):
      pythonw.exe run_hidden.py pc_backup.py pc_backup_sched.log
  손 실행:  py -3.12 pc_backup.py          대조만(복사 없음):  py -3.12 pc_backup.py --verify
"""
import base64
import datetime
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
APPDATA = os.environ.get("APPDATA") or os.path.join(HOME, "AppData", "Roaming")
LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local")
DEST = os.path.join(HOME, "PC백업")
PROJECT_DIR = re.sub(r"[^A-Za-z0-9]", "-", HERE)
CREATE_NO_WINDOW = 0x08000000


def app_sessions_dir():
    """Claude 앱 세션 목록 폴더. 앱이 Microsoft Store(MSIX) 패키지면 %APPDATA%\\Claude는 앱 안에서만 보이는 가상 경로이고
    실제 파일은 %LOCALAPPDATA%\\Packages\\Claude_<id>\\LocalCache\\Roaming\\Claude\\ 에 있다 — 작업 스케줄러에서는
    %APPDATA%\\Claude가 없다(10-18 실측: 세션 안 실행 749개, 예약 작업 실행 「원본 없음」). 패키지 쪽을 먼저 본다."""
    pk = os.path.join(LOCALAPPDATA, "Packages")
    try:
        cands = sorted(os.path.join(pk, d, "LocalCache", "Roaming", "Claude", "claude-code-sessions")
                       for d in os.listdir(pk) if d.startswith("Claude_"))
    except OSError:
        cands = []
    for c in cands:
        if os.path.isdir(c):
            return c
    return os.path.join(APPDATA, "Claude", "claude-code-sessions")


# (백업 폴더, 원본 폴더, 파일 이름 목록 — None이면 폴더 통째)
ITEMS = [
    (os.path.join("claude-projects", PROJECT_DIR), os.path.join(HOME, ".claude", "projects", PROJECT_DIR), None),
    ("claude", os.path.join(HOME, ".claude"), ["CLAUDE.md", "settings.json"]),
    ("local_docs", os.path.join(HERE, "local_docs"), None),
    ("claude-code-sessions", app_sessions_dir(), None),
    ("과방위_발언원문", os.path.join(os.path.dirname(HERE), "과방위_발언원문"), None),
]
TASK_PATTERNS = ["전파정책_*", "RadioPolicy-*", "radio_TEMP_*"]
EXCLUDE_FILES = [".env", ".env.*", "*.env", ".credentials.json", ".gitlab-credentials", ".git-credentials",
                 ".confluence_pat", "*.pem"]
EXCLUDE_DIRS = ["__pycache__", ".git", "node_modules"]

SECRET_ENV_KEY = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CLIENT_ID")
SECRET_MIN_LEN = 8
# 공개 문서에 이미 실린 값은 비밀이 아니다(예: 법제처 OC) — 가리면 전사본 글만 상한다.
PUBLIC_DOCS = ["CLAUDE.md", "전파정책AI_지침_운영핵심.md", "전파정책AI_배경역사.md"]
# (항목 이름, 먼저 볼 접두어들, 정규식) — .env에 없는 토큰(예: 다른 PC·Vault의 PAT)도 꼴로 가린다
TOKEN_PATTERNS = [
    ("token:sk-ant", (b"sk-ant-",), re.compile(rb"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("token:github_pat", (b"github_pat_",), re.compile(rb"github_pat_[A-Za-z0-9_]{20,}")),
    ("token:gh", (b"ghp_", b"gho_", b"ghu_", b"ghs_", b"ghr_"),
     re.compile(rb"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}")),
    ("token:glpat", (b"glpat-",), re.compile(rb"glpat-[A-Za-z0-9_\-]{20,}")),
    ("token:sbp", (b"sbp_",), re.compile(rb"sbp_[0-9a-f]{40}")),
    ("token:sb_secret", (b"sb_secret_",), re.compile(rb"sb_secret_[A-Za-z0-9_\-]{16,}")),
]
JWT_RE = re.compile(rb"eyJ[A-Za-z0-9_\-]{8,}\.(eyJ[A-Za-z0-9_\-]{8,})\.[A-Za-z0-9_\-]{8,}")
MASK_VERSION = "1"          # 가림 규칙을 바꾸면 올린다 → 캐시를 버리고 전부 다시 훑는다
XF_MAX_CHARS = 20000        # /XF 이름 목록이 이보다 길면 빼고 robocopy 뒤 다시 훑기에만 맡긴다(명령줄 32K 한도)

_LINES = []


def log(msg):
    line = "%s %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    _LINES.append(line)


def _matches(name, patterns):
    n = name.lower()
    return any(fnmatch.fnmatchcase(n, p.lower()) for p in patterns)


def iter_files(root, names=None):
    """(백업 기준 상대 경로, 전체 경로). 제외 이름·접합점(junction)은 robocopy(/XF·/XD·/XJ)와 같게 뺀다."""
    if names is not None:
        for n in names:
            p = os.path.join(root, n)
            if os.path.isfile(p):
                yield n, p
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not _matches(d, EXCLUDE_DIRS) and not os.path.isjunction(os.path.join(dirpath, d))]
        for fn in filenames:
            if _matches(fn, EXCLUDE_FILES):
                continue
            full = os.path.join(dirpath, fn)
            yield os.path.relpath(full, root), full


# ---------------------------------------------------------------- 비밀값

def _read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def load_secrets():
    """비밀값(bytes) → 항목 이름. 값은 이 프로세스 메모리에만 둔다 — 출력·캐시·로그에 쓰지 않는다."""
    vals = {}

    def add(label, v):
        v = (v or "").strip().strip('"').strip("'")
        if len(v) >= SECRET_MIN_LEN:
            vals.setdefault(v.encode("utf-8"), label)

    for line in _read_text(os.path.join(HERE, ".env")).splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Za-z0-9_]+)\s*=\s*(.*)", line)
        if m and SECRET_ENV_KEY.search(m.group(1).upper()):
            add(".env:" + m.group(1), m.group(2))
    for name in (".gitlab-credentials", ".git-credentials"):
        for m in re.finditer(r"://[^:/@\s]+:([^@\s]+)@", _read_text(os.path.join(HOME, name))):
            add(name, m.group(1))
    add(".confluence_pat", _read_text(os.path.join(HOME, ".confluence_pat")))
    raw = _read_text(os.path.join(HOME, ".claude", ".credentials.json"))
    if raw:
        try:
            def walk(o, key=""):
                if isinstance(o, dict):
                    for k, v in o.items():
                        walk(v, k)
                elif isinstance(o, list):
                    for v in o:
                        walk(v, key)
                elif isinstance(o, str) and re.search(r"token|secret", key, re.I):
                    add(".credentials.json:" + key, o)
            walk(json.loads(raw))
        except ValueError:
            pass
    public = "".join(_read_text(os.path.join(HERE, d)) for d in PUBLIC_DOCS).encode("utf-8")
    dropped = sorted(lbl for v, lbl in vals.items() if v in public)
    vals = {v: lbl for v, lbl in vals.items() if v not in public}
    return vals, dropped


def secrets_fingerprint(secrets):
    h = hashlib.sha256(MASK_VERSION.encode())
    for v in sorted(secrets):
        h.update(v + b"\0")
    return h.hexdigest()[:16]


def _is_service_jwt(payload):
    try:
        return b'"service_role"' in base64.urlsafe_b64decode(payload + b"=" * (-len(payload) % 4))
    except Exception:
        return False


def find_labels(data, secrets):
    labels = set()
    for v, label in secrets.items():
        if v in data:
            labels.add(label)
    for label, prefixes, rx in TOKEN_PATTERNS:
        if any(p in data for p in prefixes) and rx.search(data):
            labels.add(label)
    if b"eyJ" in data:
        for m in JWT_RE.finditer(data):
            if _is_service_jwt(m.group(1)):
                labels.add("token:jwt_service_role")
                break
    return labels


def mask(data, secrets):
    """비밀값을 같은 길이의 '*'로 바꾼다 — 길이가 같아야 robocopy가 「같은 파일」로 보고 건너뛴다."""
    out = data
    for v in sorted(secrets, key=len, reverse=True):
        if v in out:
            out = out.replace(v, b"*" * len(v))
    for _label, prefixes, rx in TOKEN_PATTERNS:
        if any(p in out for p in prefixes):
            out = rx.sub(lambda m: b"*" * len(m.group(0)), out)
    if b"eyJ" in out:
        out = JWT_RE.sub(lambda m: b"*" * len(m.group(0)) if _is_service_jwt(m.group(1)) else m.group(0), out)
    if len(out) != len(data):
        raise RuntimeError("가림 뒤 길이가 달라짐")
    return out


def read_stable(path, tries=3):
    """읽는 동안 안 바뀐 내용과 그 stat. 쓰는 중인 전사본이 계속 바뀌면 (None, None)."""
    for _ in range(tries):
        try:
            s1 = os.stat(path)
            with open(path, "rb") as f:
                data = f.read()
            s2 = os.stat(path)
        except OSError:
            return None, None
        if (s1.st_size, s1.st_mtime_ns) == (s2.st_size, s2.st_mtime_ns) == (len(data), s2.st_mtime_ns):
            return data, s2
        time.sleep(0.5)
    return None, None


def write_masked(path, data, atime_ns, mtime_ns):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".pcbak~"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    os.utime(path, ns=(atime_ns, mtime_ns))


# ---------------------------------------------------------------- 캐시

def cache_path():
    return os.path.join(DEST, "_state", "redact_cache.json")


def load_cache(fp):
    try:
        with open(cache_path(), encoding="utf-8") as f:
            c = json.load(f)
        if c.get("fp") == fp:
            return c
        log("비밀값 목록·가림 규칙이 바뀜 — 전부 다시 훑는다")
    except (OSError, ValueError):
        pass
    return {"fp": fp, "items": {}}


def save_cache(cache):
    p = cache_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, p)


# ---------------------------------------------------------------- 단계

def prepass(key, src, dst, names, secrets, cache, st):
    """바뀐 원본만 훑고, 비밀값이 든 파일은 가린 사본을 원본 시각으로 먼저 쓴다. 그런 파일의 이름 목록을 돌려준다."""
    files = cache["items"].setdefault(key, {})
    hit_names = []
    for rel, full in iter_files(src, names):
        try:
            s = os.stat(full)
        except OSError:
            continue
        sig = [s.st_size, s.st_mtime_ns]
        ent = files.get(rel)
        data = None
        if ent is None or ent[:2] != sig:
            data, s = read_stable(full)
            if data is None:
                st["unstable"] += 1          # 계속 바뀌는 중 — 캐시에 안 넣어 robocopy 뒤 다시 훑기가 백업 쪽을 본다
                files.pop(rel, None)
                continue
            sig = [s.st_size, s.st_mtime_ns]
            ent = files[rel] = sig + [sorted(find_labels(data, secrets)), False]
            st["scanned"] += 1
            st["scanned_bytes"] += len(data)
        if not ent[2]:
            continue
        hit_names.append(os.path.basename(rel))
        for lbl in ent[2]:
            st["labels"][lbl] = st["labels"].get(lbl, 0) + 1
        dp = os.path.join(dst, rel)
        try:
            d = os.stat(dp)
            same = [d.st_size, d.st_mtime_ns] == ent[:2]
        except OSError:
            same = False
        if same and ent[3]:
            continue
        if data is None:
            data, s = read_stable(full)
            if data is None or [s.st_size, s.st_mtime_ns] != ent[:2]:
                files.pop(rel, None)
                st["unstable"] += 1
                continue
        write_masked(dp, mask(data, secrets), s.st_atime_ns, s.st_mtime_ns)
        ent[3] = True
        st["masked_written"] += 1
    return hit_names


def postpass(key, src, dst, names, secrets, cache, st):
    """훑은 뒤 바뀐(또는 못 읽은) 파일은 robocopy가 원문을 가져왔을 수 있다 — 백업 쪽을 훑어 제자리에서 가린다."""
    files = cache["items"].setdefault(key, {})
    for rel, full in iter_files(src, names):
        try:
            s = os.stat(full)
        except OSError:
            continue
        ent = files.get(rel)
        if ent is not None and ent[:2] == [s.st_size, s.st_mtime_ns]:
            continue
        files.pop(rel, None)                  # 다음 실행에서 원본을 다시 훑는다
        dp = os.path.join(dst, rel)
        try:
            d = os.stat(dp)
            with open(dp, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if find_labels(data, secrets):
            write_masked(dp, mask(data, secrets), d.st_atime_ns, d.st_mtime_ns)
            st["post_masked"] += 1


def robocopy(src, dst, names, extra_xf):
    cmd = ["robocopy", src, dst] + (names or []) + [
        "/COPY:DAT", "/R:2", "/W:5", "/XJ", "/NP", "/NFL", "/NDL", "/NJH", "/NJS"]
    if names is None:
        cmd += ["/E", "/DCOPY:T", "/MT:8"]
    xf = list(EXCLUDE_FILES)
    if extra_xf and sum(len(x) + 1 for x in extra_xf) <= XF_MAX_CHARS:
        xf += sorted(set(extra_xf))
    elif extra_xf:
        log("  가린 파일 이름 목록이 길어 /XF에서 뺌 — robocopy 뒤 다시 훑기로 가린다(%d개)" % len(extra_xf))
    cmd += ["/XF"] + xf + ["/XD"] + EXCLUDE_DIRS
    r = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
    out = (r.stdout or b"").decode("oem", errors="replace").strip().splitlines()
    return r.returncode, out[-15:]


_TASK_PS = r"""
$ErrorActionPreference = 'Stop'
$out = '__OUT__'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$tasks = @(Get-ScheduledTask | Where-Object { __COND__ })
$rows = foreach ($t in $tasks) {
  $err = ''
  try {
    $x = Export-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath
    [IO.File]::WriteAllText((Join-Path $out ($t.TaskName + '.xml')), $x, [Text.Encoding]::Unicode)
  } catch { $err = $_.Exception.Message }
  $i = $null
  try { $i = Get-ScheduledTaskInfo -TaskName $t.TaskName -TaskPath $t.TaskPath } catch {}
  [pscustomobject]@{
    Name = $t.TaskName; State = [string]$t.State; User = $t.Principal.UserId; Logon = [string]$t.Principal.LogonType
    LastRun = $(if ($i -and $i.LastRunTime) { $i.LastRunTime.ToString('s') }); LastResult = $(if ($i) { $i.LastTaskResult })
    NextRun = $(if ($i -and $i.NextRunTime) { $i.NextRunTime.ToString('s') })
    Actions = (($t.Actions | ForEach-Object { ($_.Execute + ' ' + $_.Arguments).Trim() }) -join ' || ')
    ExportError = $err
  }
}
$rows | Export-Csv -Path (Join-Path $out '_tasks.csv') -NoTypeInformation -Encoding UTF8
Write-Output ('{0} {1}' -f $tasks.Count, @($rows | Where-Object { -not $_.ExportError }).Count)
"""


def export_tasks(out_dir):
    """예약 작업 XML(UTF-16, schtasks /Create /XML·Register-ScheduledTask -Xml로 되살림)과 상태표. (전체, 성공) 수."""
    cond = " -or ".join("$_.TaskName -like '%s'" % p for p in TASK_PATTERNS)
    ps = _TASK_PS.replace("__OUT__", out_dir.replace("'", "''")).replace("__COND__", cond)
    enc = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-EncodedCommand", enc], capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=300)
    m = re.search(r"(\d+) (\d+)", (r.stdout or b"").decode("oem", errors="replace"))
    if r.returncode != 0 or not m:
        err = (r.stderr or b"").decode("oem", errors="replace").strip().splitlines()
        return None, None, err[-5:]
    return int(m.group(1)), int(m.group(2)), []


def tally(src, dst, names, run_start_ns):
    s_files = {}
    for rel, full in iter_files(src, names):
        try:
            s = os.stat(full)
            s_files[rel] = (s.st_size, s.st_mtime_ns)
        except OSError:
            pass
    d_files = {}
    if os.path.isdir(dst):
        for rel, full in iter_files(dst, names):
            try:
                d_files[rel] = os.stat(full).st_size
            except OSError:
                pass
    missing, changed = [], 0
    for rel, (size, mt) in s_files.items():
        if d_files.get(rel) != size:
            if mt >= run_start_ns:
                changed += 1                  # 백업하는 동안 바뀐 파일(쓰는 중인 전사본) — 다음 실행에 간다
            else:
                missing.append(rel)
    return {
        "src_n": len(s_files), "src_mb": sum(v[0] for v in s_files.values()) / 1048576,
        "dst_n": len(d_files), "dst_mb": sum(d_files.values()) / 1048576,
        "missing": missing, "changed": changed, "extra": len(set(d_files) - set(s_files)),
    }


def alert(text):
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(HERE, ".env"))
        import notify
        if not notify.send_telegram(text):
            log("운영자 텔레그램 못 보냄")
    except Exception as e:  # 알림 실패가 백업 결과를 가리면 안 된다
        log("운영자 텔레그램 못 보냄: %s" % type(e).__name__)


def write_reports(summary_lines):
    os.makedirs(os.path.join(DEST, "_log"), exist_ok=True)
    month = datetime.date.today().strftime("%Y-%m")
    with open(os.path.join(DEST, "_log", "pc_backup_%s.log" % month), "a", encoding="utf-8") as f:
        f.write("\n".join(_LINES) + "\n\n")
    with open(os.path.join(DEST, "마지막_백업.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines) + "\n")


def main(argv):
    verify_only = "--verify" in argv
    run_start_ns = time.time_ns()
    t0 = time.time()
    log("=== PC 백업 %s → %s" % ("대조만" if verify_only else "시작", DEST))
    os.makedirs(DEST, exist_ok=True)
    problems = []
    st = {"scanned": 0, "scanned_bytes": 0, "unstable": 0, "masked_written": 0, "post_masked": 0, "labels": {}}

    if not verify_only:
        secrets, dropped = load_secrets()
        log("비밀값 %d개 읽음(값은 기록하지 않음)%s" % (
            len(secrets), "; 공개 문서에 있어 뺀 것: " + ", ".join(dropped) if dropped else ""))
        cache = load_cache(secrets_fingerprint(secrets))
        for key, src, names in ITEMS:
            if not os.path.isdir(src):
                problems.append("원본 없음: %s" % src)
                log("원본 없음: %s" % src)
                continue
            dst = os.path.join(DEST, key)
            os.makedirs(dst, exist_ok=True)
            hits = prepass(key, src, dst, names, secrets, cache, st)
            save_cache(cache)
            rc, tail = robocopy(src, dst, names, hits)
            log("%s: robocopy 코드 %d%s" % (key, rc, " (가린 파일 %d개)" % len(hits) if hits else ""))
            if rc >= 8:
                problems.append("robocopy 실패 %s (코드 %d)" % (key, rc))
                for line in tail:
                    log("    " + line)
            postpass(key, src, dst, names, secrets, cache, st)
            save_cache(cache)
        log("훑음 %d개 %.1fMB · 가린 사본 씀 %d · 뒤 다시 가림 %d · 쓰는 중이라 건넘 %d · 비밀 항목별 파일 수 %s" % (
            st["scanned"], st["scanned_bytes"] / 1048576, st["masked_written"], st["post_masked"], st["unstable"],
            json.dumps(st["labels"], ensure_ascii=False, sort_keys=True)))
        n_all, n_ok, err = export_tasks(os.path.join(DEST, "예약작업"))
        if n_all is None or n_ok != n_all:
            problems.append("예약 작업 내보내기 실패")
            log("예약 작업 내보내기 실패 %s/%s %s" % (n_ok, n_all, " | ".join(err)))
        else:
            log("예약 작업 %d개 내보냄" % n_all)

    summary = ["PC 백업 %s — %s (%.0f초)" % ("대조" if verify_only else "실행",
                                          datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), time.time() - t0),
               "항목 | 원본 파일·MB | 백업 파일·MB | 빠짐 | 실행 중 바뀜 | 백업에만"]
    for key, src, names in ITEMS:
        if not os.path.isdir(src):
            summary.append("%s | 원본 없음" % key)
            continue
        t = tally(src, os.path.join(DEST, key), names, run_start_ns)
        summary.append("%s | %d · %.1f | %d · %.1f | %d | %d | %d" % (
            key.split(os.sep)[0], t["src_n"], t["src_mb"], t["dst_n"], t["dst_mb"],
            len(t["missing"]), t["changed"], t["extra"]))
        if t["missing"]:
            problems.append("빠짐 %s %d개" % (key.split(os.sep)[0], len(t["missing"])))
            for rel in t["missing"][:5]:
                log("    빠짐: %s\\%s" % (key, rel))
    summary.append("결과: " + ("이상 없음" if not problems else " / ".join(problems)))
    for line in summary:
        log(line)
    try:
        write_reports(summary)
    except OSError as e:
        log("로그 못 씀: %s" % e)
    if problems and not verify_only:
        alert("⚠️ PC 백업(%s) 이상: %s — %s\\_log 확인" % (os.environ.get("COMPUTERNAME", "?"),
                                                    " / ".join(problems)[:600], DEST))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
