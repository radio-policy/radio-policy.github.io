# -*- coding: utf-8 -*-
"""커밋 전후 점검 — 손으로 챙기던 릴리스 항목을 한 번에 본다 (§4-2-11, #212, 2026-09-25).

점검·제안만 한다(운영자 결정): 파일을 고치거나 배포하지 않는다. 출력된 명령을 보고 직접 실행할 것.

  py -3.12 tools_release.py            # 커밋 전: gitlab/main 대비 바뀐 파일(작업 트리 포함) 기준 점검
  py -3.12 tools_release.py --verify   # push 뒤: 두 원격을 fetch해 HEAD 일치 + 최근 커밋 파일 원격 대조

점검 항목
  ① 캐시 번호 — 바뀐 정적 파일(app.js 등)의 index.html ?v=가 원격 대비 그대로면 새 번호 제안
  ② Edge 재배포 — 바뀐 파일을 (import를 따라) 쓰는 함수 목록 + verify_jwt 설정을 살린 배포 명령
  ③ 봇 지침서 — system_prompt.js 추출값과 app_config.system_prompt SHA-256 대조(#210과 같은 규칙)
  ④ GitLab Pages — index.html이 부르는 로컬 파일이 .gitlab-ci.yml 복사 목록에 있는지(#125)
  ⑤ .bat — 바뀐 .bat의 bareLF·비ASCII 바이트(#22; git status는 LF로 깨진 .bat을 깨끗하다고 보여 준다)
"""
import os
import re
import sys
import json
import hashlib
import argparse
import subprocess
import urllib.request
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding='utf-8')
for _p in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
    os.environ.pop(_p, None)
ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_REF = 'zwkjedumfuhodckmtxxn'
FN_DIR = 'supabase/functions'
STATIC = ('app.js', 'styles.css', 'system_prompt.js', 'lawmap_articles.js',
          'supabase/functions/_shared/cite_verify.js')
KST = timezone(timedelta(hours=9))


def git(*args, check=False):
    r = subprocess.run(['git', '-C', ROOT] + list(args), capture_output=True, text=True, encoding='utf-8')
    if check and r.returncode != 0:
        raise SystemExit('git %s 실패: %s' % (' '.join(args), r.stderr.strip()))
    return r.returncode, (r.stdout or '').strip()


def load_env():
    try:
        for line in open(os.path.join(ROOT, '.env'), encoding='utf-8'):
            m = re.match(r'\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)', line)
            if m:
                os.environ.setdefault(m.group(1), m.group(2).strip().strip('"').strip("'"))
    except OSError:
        pass


def http_json(url, headers):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
        return json.loads(r.read().decode('utf-8'))


def changed_files(base):
    _, out = git('diff', '--name-only', base)
    return sorted(set(f for f in out.splitlines() if f))


# ── ① 캐시 번호 ──
def check_busters(changed, base):
    todo = []
    html_now = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    _, html_base = git('show', '%s:index.html' % base)
    today = datetime.now(KST).strftime('%Y%m%d')
    for f in STATIC:
        if f not in changed:
            continue
        pat = re.escape(f) + r'\?v=([0-9A-Za-z]+)'
        now, old = re.search(pat, html_now), re.search(pat, html_base)
        if not now:
            todo.append('① %s: index.html에 %s?v= 가 없음' % (f, f))
            continue
        if old and now.group(1) != old.group(1):
            print('  ① %s ?v=%s → %s (올림 확인)' % (f, old.group(1), now.group(1)))
            continue
        cur = now.group(1)
        nxt = (today + chr(ord(cur[8]) + 1)) if cur.startswith(today) and len(cur) == 9 and cur[8] < 'z' else today + 'a'
        todo.append('① %s 가 바뀌었는데 캐시 번호가 그대로(?v=%s) → index.html에서 ?v=%s 로' % (f, cur, nxt))
    return todo


# ── ② Edge 재배포 대상 ──
_IMP = re.compile(r"""(?:^|\n)\s*import\s+(?:[^'"]*?\sfrom\s+)?['"](\.{1,2}/[^'"]+)['"]""")


def _local_deps(path, seen):
    if path in seen or not os.path.isfile(os.path.join(ROOT, path)):
        return seen
    seen.add(path)
    src = open(os.path.join(ROOT, path), encoding='utf-8').read()
    for rel in _IMP.findall(src):
        dep = os.path.normpath(os.path.join(os.path.dirname(path), rel)).replace('\\', '/')
        _local_deps(dep, seen)
    return seen


def check_edge(changed):
    fns = {}
    for d in sorted(os.listdir(os.path.join(ROOT, FN_DIR))):
        entry = '%s/%s/index.ts' % (FN_DIR, d)
        if not d.startswith('_') and os.path.isfile(os.path.join(ROOT, entry)):
            fns[d] = _local_deps(entry, set())
    hit = {}
    for fn, deps in fns.items():
        why = sorted(f for f in changed if f in deps or f.startswith('%s/%s/' % (FN_DIR, fn)))
        if why:
            hit[fn] = why
    if not hit:
        return []
    jwt = {}
    tok = os.environ.get('SUPABASE_ACCESS_TOKEN', '').strip()
    if tok:
        try:
            for f in http_json('https://api.supabase.com/v1/projects/%s/functions' % PROJECT_REF,
                               {'Authorization': 'Bearer ' + tok, 'User-Agent': 'tools_release'}):
                jwt[f['slug']] = f.get('verify_jwt')
        except Exception as e:  # noqa: BLE001
            print('  ② verify_jwt 조회 실패(명령에 직접 확인 표시): %s' % str(e)[:80])
    todo = []
    for fn, why in hit.items():
        flag = {False: ' --no-verify-jwt', True: ''}.get(jwt.get(fn), ' <verify_jwt 확인 필요>')
        todo.append('② Edge 재배포 %s (바뀐 파일: %s)\n     npx supabase@latest functions deploy %s --project-ref %s%s'
                    % (fn, ', '.join(os.path.basename(w) for w in why), fn, PROJECT_REF, flag))
    if 'supabase/functions/_shared/cite_verify.js' in changed:
        todo.append('② cite_verify.js 변경 — node tests/cite_verify.test.js 도 돌릴 것')
    return todo


# ── ③ 봇 지침서 동기화 ──
def check_prompt():
    url, key = os.environ.get('SUPABASE_URL', '').rstrip('/'), os.environ.get('SUPABASE_SERVICE_KEY', '')
    if not (url and key):
        return ['③ SUPABASE_URL/SERVICE_KEY 없음 — 봇 지침서 대조 건너뜀']
    js = open(os.path.join(ROOT, 'system_prompt.js'), encoding='utf-8').read()
    file_p = json.loads(js[js.index('"'):js.rindex('"') + 1])
    try:
        rows = http_json(url + '/rest/v1/app_config?select=value&key=eq.system_prompt',
                         {'apikey': key, 'Authorization': 'Bearer ' + key})
    except Exception as e:  # noqa: BLE001
        return ['③ 봇 지침서 조회 실패: %s' % str(e)[:80]]
    db_p = rows[0].get('value') if rows else None
    if db_p and hashlib.sha256(db_p.encode()).digest() == hashlib.sha256(file_p.encode()).digest():
        print('  ③ 봇 지침서 동기화 정상 (%d자)' % len(file_p))
        return []
    return ['③ 봇 지침서가 system_prompt.js와 다름 → py -3.12 sync_system_prompt.py (커밋·푸시 뒤)']


# ── ④ GitLab Pages 복사 목록 ──
def check_gitlab_ci():
    html = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    ci = open(os.path.join(ROOT, '.gitlab-ci.yml'), encoding='utf-8').read()
    todo = []
    for ref in sorted(set(re.findall(r'''(?:src|href)=["']([^"'?#]+\.(?:js|css))''', html))):
        if re.match(r'(https?:)?//', ref):
            continue
        if not re.search(r'(^|[\s/])' + re.escape(os.path.basename(ref)) + r'(\s|$)', ci):
            todo.append('④ index.html이 부르는 %s 가 .gitlab-ci.yml 복사 목록에 없음 → GitLab Pages에서 404' % ref)
    return todo


# ── ⑤ .bat 바이트 ──
def check_bat(changed):
    todo = []
    for f in changed:
        if not f.lower().endswith('.bat') or not os.path.isfile(os.path.join(ROOT, f)):
            continue
        b = open(os.path.join(ROOT, f), 'rb').read()
        bare = sum(1 for i, c in enumerate(b) if c == 10 and (i == 0 or b[i - 1] != 13))
        nona = sum(1 for c in b if c > 127)
        if bare or nona:
            todo.append('⑤ %s: bareLF=%d nonASCII=%d → ASCII+CRLF로 다시 쓸 것(#22)' % (f, bare, nona))
        else:
            print('  ⑤ %s ASCII+CRLF 정상' % f)
    return todo


# ── push 뒤 원격 대조 ──
def verify(since):
    for r in ('gitlab', 'origin'):
        git('fetch', '-q', r, check=True)
    _, head = git('rev-parse', 'HEAD')
    ok = True
    for r in ('gitlab', 'origin'):
        _, rh = git('rev-parse', '%s/main' % r)
        same = rh == head
        ok &= same
        print('  %s/main %s %s' % (r, rh[:7], '= HEAD' if same else '≠ HEAD %s ✗' % head[:7]))
    _, out = git('diff', '--name-only', since, 'HEAD')
    for f in [x for x in out.splitlines() if x]:
        path = os.path.join(ROOT, f)
        local = open(path, 'rb').read()[-200:] if os.path.isfile(path) else None
        for r in ('gitlab', 'origin'):
            rc, _ = git('diff', '--quiet', '%s/main' % r, '--', f)
            rr = subprocess.run(['git', '-C', ROOT, 'show', '%s/main:%s' % (r, f)], capture_output=True)
            remote = rr.stdout[-200:] if rr.returncode == 0 else None
            tail_ok = (local == remote) if local is not None else (remote is None)
            if rc != 0 or not tail_ok:
                ok = False
                print('  ✗ %s: %s/main와 다름(diff=%s, 끝부분=%s)' % (f, r, 'O' if rc == 0 else 'X', 'O' if tail_ok else 'X'))
    print('[원격 대조] %s' % ('두 원격 모두 HEAD와 일치 — 파일 끝부분까지 동일' if ok else '불일치 — 다시 push하지 말고 원인부터 볼 것(CLAUDE.md ③)'))
    return ok


def main():
    ap = argparse.ArgumentParser(description='커밋 전후 점검(점검·제안만)')
    ap.add_argument('--verify', action='store_true', help='push 뒤 원격 대조')
    ap.add_argument('--base', default='gitlab/main', help='비교 기준(기본 gitlab/main — 마지막 fetch 시점)')
    ap.add_argument('--since', default='HEAD~1', help='--verify에서 대조할 커밋 범위의 시작(기본 HEAD~1)')
    a = ap.parse_args()
    load_env()
    if a.verify:
        sys.exit(0 if verify(a.since) else 1)
    changed = changed_files(a.base)
    print('[점검] %s 대비 바뀐 파일 %d개' % (a.base, len(changed)))
    todo = []
    todo += check_busters(changed, a.base)
    todo += check_edge(changed)
    todo += check_prompt()   # 파일이 안 바뀌어도 DB 쪽이 어긋나 있을 수 있어 늘 본다
    todo += check_gitlab_ci()
    todo += check_bat(changed)
    print()
    if todo:
        print('할 일 %d건:' % len(todo))
        for t in todo:
            print(' - ' + t)
    else:
        print('할 일 없음.')
    print('\n커밋은 git add <파일명>으로 명시 → git push gitlab main (두 원격 동시, #212) → py -3.12 tools_release.py --verify')


if __name__ == '__main__':
    main()
