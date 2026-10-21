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
  claude-code-sessions\\              Claude 앱 세션 목록 — 10-20 앱 업데이트 뒤 %LOCALAPPDATA%\\Claude-Data\\claude_<id>\\
                                      claude-code-sessions, 그 전 스토어 앱은 %LOCALAPPDATA%\\Packages\\Claude_<id>\\LocalCache\\
                                      Roaming\\Claude\\claude-code-sessions(앱 안에서는 %APPDATA%\\Claude로 보임), 아니면 %APPDATA%
  과방위_발언원문\\                    이 저장소의 상위 폴더\\과방위_발언원문 (SPEECH_RAW_DIR)
  예약작업\\                          전파정책_*·RadioPolicy-*·radio_TEMP_* 작업 XML + _tasks.csv(상태표)
  _log\\ · _state\\ · 마지막_백업.txt  월별 실행 로그 · 비밀값 훑기 캐시(경로·항목 이름만) · 마지막 실행 요약
  00_복구_시작하기.md                docs/PC백업_복구절차.md 사본(#320-보론) — 새 PC에서 Claude에게 주면 순서대로 복구한다
  비밀파일\\                          이 저장소\\.env · %USERPROFILE%\\.gitlab-credentials 원본 그대로(#320-보론2, 암호 없음 —
                                      운영자 결정 「드라이브가 해킹 당하지 않는다는 가정하에」). .confluence_pat은 넣지 않는다

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
- **안 가져가는 것**: 위 항목 폴더들 안의 비밀 파일(.env*·.credentials.json·.gitlab-credentials·.confluence_pat·*.pem —
  .env·.gitlab-credentials 원본 둘만 비밀파일\\로 따로)·__pycache__·.git·사내판 전사본(C--claude-rp-internal-*)·
  사내판 폴더·frequence\\confluence·docs\\사내공유_*·사내 컨플루언스 열쇠 — 개인 드라이브에 사내 자료를 두지 않는다
  (사내 넷은 원본 목록에 아예 없다).
- 비밀 파일을 그대로 올리더라도 **전사본 속 비밀값 가림은 그대로 둔다** — .env에 없는 토큰(GitHub PAT 등)도 섞여 있고,
  대화 기록은 비밀 파일보다 넓게 읽힌다(공유·검색).
- 끝에 원본과 백업의 파일 수·용량을 대조한다(실행 중 바뀐 파일은 빠짐으로 세지 않는다). 빠짐·robocopy 실패(코드 8 이상)·
  원본 없음·예약 작업 내보내기·복구 안내·비밀 파일 복사 실패면 종료 코드 1 + 운영자 텔레그램 한 줄.
- **드라이브 올리기(#320-보론4)**: 운영자는 메모리 때문에 드라이브 앱을 평소 꺼 둔다. 백업이 끝나면 앱이 꺼져 있을 때
  켜서(탐색기로 시작 메뉴 바로가기) PC백업 전체가 올라갈 때까지 기다렸다가(앱 기록과 경로·크기·시각·체크섬 대조,
  남은 것 0이 연달아 두 번) 다시 끈다. 45분 안에 안 끝나거나 켜지·판단하지·끄지 못하면 켜 둔 채 운영자 봇에 한 줄.
  이미 켜져 있던 앱은 끄지 않는다. 성공은 로그에만 남긴다.

사용:
  작업 스케줄러(setup_pc_backup.ps1 — RadioPolicy-PCBackup, 매일 23:30, 창 없음):
      pythonw.exe run_hidden.py pc_backup.py pc_backup_sched.log
  손 실행:  py -3.12 pc_backup.py          대조만(복사 없음):  py -3.12 pc_backup.py --verify
  드라이브 단계 빼고:  py -3.12 pc_backup.py --no-drive
"""
import base64
import datetime
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
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


def _sub_dirs(parent, prefix, *tail):
    try:
        return sorted(os.path.join(parent, d, *tail) for d in os.listdir(parent) if d.startswith(prefix))
    except OSError:
        return []


def app_sessions_dir(local=None, roaming=None):
    """Claude 앱 세션 목록 폴더. 앱이 Microsoft Store(MSIX) 패키지면 %APPDATA%\\Claude는 앱 안에서만 보이는 가상 경로이고
    실제 파일은 %LOCALAPPDATA%\\Packages\\Claude_<id>\\LocalCache\\Roaming\\Claude\\ 에 있었다 — 작업 스케줄러에서는
    %APPDATA%\\Claude가 없다(10-18 실측: 세션 안 실행 749개, 예약 작업 실행 「원본 없음」).
    2026-10-20 18:15 앱 업데이트가 데이터를 %LOCALAPPDATA%\\Claude-Data\\claude_<id>\\ 로 옮겼다 — 옛 패키지 폴더에는
    표지 파일(.user-data-left.*)만 남아 그날 23:30 백업이 「원본 없음」이었다. 새 위치 → 패키지 → %APPDATA% 순으로 본다."""
    local = local or LOCALAPPDATA
    roaming = roaming or APPDATA
    cands = (_sub_dirs(os.path.join(local, "Claude-Data"), "claude_", "claude-code-sessions")
             + _sub_dirs(os.path.join(local, "Packages"), "Claude_", "LocalCache", "Roaming", "Claude",
                         "claude-code-sessions"))
    for c in cands:
        if os.path.isdir(c):
            return c
    return os.path.join(roaming, "Claude", "claude-code-sessions")


# (백업 폴더, 원본 폴더, 파일 이름 목록 — None이면 폴더 통째)
ITEMS = [
    (os.path.join("claude-projects", PROJECT_DIR), os.path.join(HOME, ".claude", "projects", PROJECT_DIR), None),
    ("claude", os.path.join(HOME, ".claude"), ["CLAUDE.md", "settings.json"]),
    ("local_docs", os.path.join(HERE, "local_docs"), None),
    ("claude-code-sessions", app_sessions_dir(), None),
    ("과방위_발언원문", os.path.join(os.path.dirname(HERE), "과방위_발언원문"), None),
]
TASK_PATTERNS = ["전파정책_*", "RadioPolicy-*", "radio_TEMP_*"]
# 복구 안내(Claude가 순서대로 진행하는 꼴)를 백업 맨 위에 둔다 — 새 PC에는 저장소·메모리·전역 CLAUDE.md가 아직 없어서
# 백업 옆에 있는 이 파일 하나로 시작해야 한다(#320-보론). 원본은 저장소 문서 하나, 사본은 매 실행 새로 맞춘다.
RESTORE_GUIDE = os.path.join(HERE, "docs", "PC백업_복구절차.md")
RESTORE_GUIDE_NAME = "00_복구_시작하기.md"
# 비밀 파일 — 운영자 결정 10-18 밤 「구글 드라이브가 해킹 당하지 않는다는 가정하에, 암호화 없이 쉽게」(#320-보론2):
# PC백업\비밀파일\에 원본 그대로 두고 복구 때 제자리로 되돌린다. 사내 컨플루언스 열쇠(.confluence_pat)는 사내 시스템
# 자격이라 넣지 않는다(재발급 몇 분). robocopy 항목이 아니라 여기서만 복사한다 — 다른 항목의 /XF(.env* 등)는 그대로
# 둬서 local_docs 같은 곳에 섞인 사본은 따라가지 않는다.
SECRET_DIR = "비밀파일"
SECRET_FILES = [
    (".env", os.path.join(HERE, ".env")),
    (".gitlab-credentials", os.path.join(HOME, ".gitlab-credentials")),
]
# 구글 드라이브 앱 — 운영자는 메모리 때문에 평소 꺼 둔다(10-21, Claude 앱이 메모리 부족으로 자꾸 꺼져서). 백업 끝에
# 꺼져 있으면 켜서 PC백업이 다 올라갈 때까지 기다렸다가 다시 끄고, 시간 안에 안 끝나면 켜 둔 채 운영자 봇에 알린다
# (#320-보론4, 운영자 결정 「①로 해줘」). 백업이 켜지 않은 앱(운영자가 켜 둔 것)은 끄지 않는다.
DRIVE_PROC = "GoogleDriveFS.exe"
DRIVE_SHORTCUT = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                              "Microsoft", "Windows", "Start Menu", "Programs", "Google Drive.lnk")
DRIVE_WAIT_S = 45 * 60      # 이 안에 다 안 올라가면 켜 둔 채 알림(하루 바뀌는 양은 보통 수십 MB — 몇 분)
DRIVE_POLL_S = 30
DRIVE_SETTLE_S = 60         # 켠 뒤 폴더를 훑을 시간 — 그 전의 「남은 것 0」은 믿지 않는다
DRIVE_STABLE_POLLS = 2      # 남은 것 0이 연달아 이만큼 나와야 다 올라간 것으로 본다
DRIVE_IGNORE = ["desktop.ini", "*.tmp", "*.pcbak~"]   # 잠깐 생겼다 사라지는 파일(10-21 대조 중 1개 실측)
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


def copy_restore_guide(dest=None):
    """복구 안내를 백업 폴더 맨 위에 복사한다. 내용이 같으면 그대로 둔다(드라이브가 다시 올리지 않게). 바꿨으면 True."""
    dst = os.path.join(dest or DEST, RESTORE_GUIDE_NAME)
    with open(RESTORE_GUIDE, "rb") as f:
        data = f.read()
    try:
        with open(dst, "rb") as f:
            if f.read() == data:
                return False
    except OSError:
        pass
    tmp = dst + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dst)
    return True


def copy_secret_files(dest=None, files=None):
    """비밀 파일을 PC백업\\비밀파일\\로 복사(내용이 같으면 그대로). (있는 수, 새로 쓴 수, 없는 이름들) — 값은 기록하지 않는다."""
    out = os.path.join(dest or DEST, SECRET_DIR)
    os.makedirs(out, exist_ok=True)
    present, changed, missing = 0, 0, []
    for name, src in (files or SECRET_FILES):
        try:
            with open(src, "rb") as f:
                data = f.read()
        except OSError:
            missing.append(name)
            continue
        present += 1
        dst = os.path.join(out, name)
        try:
            with open(dst, "rb") as f:
                if f.read() == data:
                    continue
        except OSError:
            pass
        tmp = dst + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dst)
        changed += 1
    return present, changed, missing


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


def drive_running():
    """구글 드라이브 앱이 떠 있나 — True/False, 확인 자체가 실패하면 None."""
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + DRIVE_PROC, "/FO", "CSV", "/NH"],
                           capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return DRIVE_PROC.lower() in (r.stdout or b"").decode("oem", errors="replace").lower()


def _drive_exe():
    root = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Google", "Drive File Stream")
    try:
        vers = [d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, DRIVE_PROC))]
    except OSError:
        return None
    if not vers:
        return None
    best = max(vers, key=lambda v: [int(x) if x.isdigit() else 0 for x in v.split(".")])
    return os.path.join(root, best, DRIVE_PROC)


def launch_drive():
    """탐색기를 거쳐 띄운다 — 운영자가 시작 메뉴에서 누른 것과 같다(10-21: Claude 앱 안의 세션 셸에서 exe를 바로
    띄우면 곧바로 꺼졌고, 탐색기에 바로가기를 넘기면 떴다). 띄울 대상이 없으면 False."""
    target = DRIVE_SHORTCUT if os.path.isfile(DRIVE_SHORTCUT) else _drive_exe()
    if not target:
        return False
    subprocess.Popen(["explorer.exe", target], creationflags=CREATE_NO_WINDOW)
    return True


def quit_drive():
    """드라이브 앱 끄기 — 정상 종료 요청(taskkill)은 창만 닫고 본체가 남아(10-21 실측) 강제 종료한다.
    다 올라간 것을 확인한 뒤에만 부른다. 꺼졌으면 True."""
    try:
        subprocess.run(["taskkill", "/F", "/IM", DRIVE_PROC], capture_output=True,
                       creationflags=CREATE_NO_WINDOW, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    for _ in range(15):
        if drive_running() is False:
            return True
        time.sleep(1)
    return False


def drive_pending(base=None, drivefs=None):
    """PC백업 안 파일 중 드라이브에 아직 안 올라간 수. 판단을 못 하면 None.
    드라이브 앱의 내부 기록(계정 폴더의 mirror_sqlite.db)을 임시 폴더로 복사해 읽기만 하고, 파일마다 경로·크기·
    수정 시각(밀리초)이 앱 기록과 같고 로컬·클라우드 체크섬이 같아야 올라간 것으로 센다(10-21 실측: 9,422개 시각 모두 일치).
    앱 판이 바뀌어 기록 꼴이 달라지거나 PC백업이 동기화 폴더로 지정돼 있지 않으면 None."""
    base = base or DEST
    drivefs = drivefs or os.path.join(LOCALAPPDATA, "Google", "DriveFS")
    rootname = os.path.basename(os.path.normpath(base))
    try:
        accts = [os.path.join(drivefs, d) for d in os.listdir(drivefs)
                 if d.isdigit() and os.path.isfile(os.path.join(drivefs, d, "mirror_sqlite.db"))]
    except OSError:
        return None
    cloud = {}
    with tempfile.TemporaryDirectory() as tmp:
        for a in accts:
            src, dst = os.path.join(a, "mirror_sqlite.db"), os.path.join(tmp, os.path.basename(a) + ".db")
            try:
                for ext in ("", "-wal", "-shm"):
                    if os.path.exists(src + ext):
                        shutil.copy2(src + ext, dst + ext)
                con = sqlite3.connect(dst)
                try:
                    rows = con.execute("select local_stable_id, parent_local_stable_id, local_filename, local_size, "
                                       "local_mtime_ms, local_md5_checksum, cloud_md5_checksum from mirror_item").fetchall()
                finally:
                    con.close()
            except (OSError, sqlite3.Error):
                return None
            byid = {r[0]: r for r in rows}
            roots = {r[0] for r in rows if r[1] == -1 and r[2] == rootname}
            for r in rows:
                parts, i = [], r[0]
                for _ in range(64):
                    if i in roots:
                        break
                    row = byid.get(i)
                    if row is None:
                        parts = None
                        break
                    parts.append(row[2])
                    i = row[1]
                else:
                    parts = None
                if parts:
                    cloud[os.path.join(*reversed(parts)).lower()] = r
    if not cloud:
        return None
    left = 0
    for dirpath, _dirnames, filenames in os.walk(base):   # 백업 폴더 전체(비밀파일\ 포함) — iter_files의 제외 이름은 안 씀
        for fn in filenames:
            if _matches(fn, DRIVE_IGNORE):
                continue
            full = os.path.join(dirpath, fn)
            try:
                s = os.stat(full)
            except OSError:
                continue
            r = cloud.get(os.path.relpath(full, base).lower())
            if (r is None or r[3] != s.st_size or r[4] != s.st_mtime_ns // 1_000_000
                    or not r[6] or r[5] != r[6]):
                left += 1
    return left


def sync_to_drive(is_running=drive_running, launch=launch_drive, quit_=quit_drive, pending=drive_pending,
                  sleep=time.sleep, clock=time.monotonic, wait_s=None, poll_s=None, settle_s=None, stable=None):
    """백업 끝 드라이브 올리기. (상태, 남은 수, 걸린 초) — 상태:
    synced_closed(켜서 다 올리고 끔) · synced_open(이미 켜져 있었고 다 올라감 — 끄지 않음) · timeout(시간 안에 안 끝남, 켜 둠) ·
    launch_failed(못 켬) · no_judge(다 올라갔는지 판단 못 함, 켜 둠) · quit_failed(다 올라갔는데 못 끔) · unknown(앱 상태 확인 실패)."""
    wait_s = DRIVE_WAIT_S if wait_s is None else wait_s
    poll_s = DRIVE_POLL_S if poll_s is None else poll_s
    settle_s = DRIVE_SETTLE_S if settle_s is None else settle_s
    stable = DRIVE_STABLE_POLLS if stable is None else stable
    t0 = clock()
    was = is_running()
    if was is None:
        return "unknown", None, 0
    started = False
    if not was:
        if not launch():
            return "launch_failed", None, 0
        started = True
        for _ in range(30):
            sleep(2)
            if is_running():
                break
        else:
            return "launch_failed", None, clock() - t0
        sleep(settle_s)
    zeros = 0
    while True:
        left = pending()
        if left is None:
            return "no_judge", None, clock() - t0
        zeros = zeros + 1 if left == 0 else 0
        if zeros >= stable:
            if not started:
                return "synced_open", 0, clock() - t0
            return ("synced_closed" if quit_() else "quit_failed"), 0, clock() - t0
        if clock() - t0 >= wait_s:
            return "timeout", left, clock() - t0
        sleep(poll_s)


DRIVE_PROBLEM = {
    "timeout": "드라이브 업로드가 %d분 안에 안 끝남(남은 %s개) — 드라이브 앱을 켜 둠",
    "launch_failed": "드라이브 앱을 켜지 못함 — 오늘 백업은 드라이브에 안 올라감(시작 메뉴에서 Google Drive 실행)",
    "no_judge": "드라이브에 다 올라갔는지 확인 못 함(앱 기록 읽기 실패 또는 PC백업 미지정) — 드라이브 앱을 켜 둠",
    "quit_failed": "드라이브에 다 올라갔지만 드라이브 앱을 끄지 못함(메모리 확보하려면 직접 끌 것)",
    "unknown": "드라이브 앱 상태 확인 실패 — 오늘 백업이 드라이브에 올라갔는지 모름",
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
        try:
            log("복구 안내 %s: %s" % ("새로 씀" if copy_restore_guide() else "같음", RESTORE_GUIDE_NAME))
        except OSError as e:
            problems.append("복구 안내 복사 실패")
            log("복구 안내 복사 실패: %s" % e)
        try:
            n_sec, n_new, miss = copy_secret_files()
            log("비밀 파일 %d개 → %s\\ (새로 씀 %d)%s" % (n_sec, SECRET_DIR, n_new,
                                                     "; 원본 없음: " + ", ".join(miss) if miss else ""))
            if miss:
                problems.append("비밀 파일 원본 없음: " + ", ".join(miss))
        except OSError as e:
            problems.append("비밀 파일 복사 실패")
            log("비밀 파일 복사 실패: %s" % type(e).__name__)

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
    drive_problem = None
    if not verify_only and "--no-drive" not in argv:
        # 백업 결과(마지막_백업.txt·월별 로그)를 다 쓴 뒤에 올린다 — 기다리는 동안 PC백업 안을 바꾸면 끝을 못 낸다.
        # 이 단계의 기록은 끝난 뒤 월별 로그에 덧붙이고, 그 변경은 다음 날 올라간다.
        n0 = len(_LINES)
        state, left, secs = sync_to_drive()
        log("드라이브: %s%s (%.0f초)" % (state, "" if left is None else " — 남은 %d개" % left, secs))
        if state in DRIVE_PROBLEM:
            drive_problem = DRIVE_PROBLEM[state]
            if state == "timeout":
                drive_problem = drive_problem % (DRIVE_WAIT_S // 60, left)
            log("드라이브 이상: " + drive_problem)
        try:
            month = datetime.date.today().strftime("%Y-%m")
            with open(os.path.join(DEST, "_log", "pc_backup_%s.log" % month), "a", encoding="utf-8") as f:
                f.write("\n".join(_LINES[n0:]) + "\n\n")
        except OSError as e:
            log("로그 못 씀: %s" % e)
        if drive_problem:
            alert("⚠️ PC 백업(%s) 드라이브: %s" % (os.environ.get("COMPUTERNAME", "?"), drive_problem))
    return 1 if (problems or drive_problem) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
