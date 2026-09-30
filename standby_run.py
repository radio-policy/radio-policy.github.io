# -*- coding: utf-8 -*-
"""
lampmanH-pc 자동 대체 실행기 (#265-보론2, 2026-10-01, 운영자 결정 「회사 PC 우선, 안 돌면 lampmanH-pc가 자동으로」)

PC 예약작업의 주(主)는 회사 PC다(#265 — 평일 09:30~18:00에만 켜짐). lampmanH-pc는 같은 작업을 **조금 늦은
시각에 이 실행기로** 돌리고, 회사 PC가 이미 돌았으면(heartbeat가 최근이면) 건너뛴다 — 그래서 실제로 도는 것은
회사 PC가 꺼진 밤·주말·결근일뿐이다. 시각만 어긋내고 가드를 빼면 두 PC가 같은 공고를 둘 다 '새 글'로 저장하고
(알림 2통·KB 조각 중복·회의록 이중 적재) 같은 기사를 두 번 긁는다 — 그래서 가드 없이 두 PC를 함께 켜지 않는다.

  작업       회사 PC(주)             lampmanH-pc(이 실행기)            건너뜀 조건
  refetch    10분마다 (:02)          10분마다 (:07)                    last_refetch_run 15분 안
  chain      16:30 (작업 동작 8개)   매일 17:15 (run_gov_crawler.bat)  last_gov_notice_run 20시간 안
  briefing   09:50                   09:35                             없음 — morning_briefing.already_sent_today
  summary    10:30                   11:00                             없음 — summary NULL만 처리(멱등)
  (CRMS 월 1회는 회사 PC만 — 놓치면 다음 부팅 때 StartWhenAvailable로 한 번 돈다)

- 브리핑 예비만 lampmanH-pc가 **먼저**다: 두 실행이 겹치면 둘 다 '안 보냄'을 보고 두 번 보낸다. 회사 PC는 09:50이나
  그보다 늦은 부팅 때 도므로 09:35에 먼저 끝내 두면 겹치지 않는다(어느 PC가 보내든 같은 코드·같은 내용).
- 정부 체인의 첫 heartbeat(last_gov_notice_run)는 시작 1~2분 뒤에 찍힌다(09-30 실측 16:30 → 16:31) — 45분 차이면
  회사 PC 실행 중에 lampmanH-pc가 들어가는 일은 회사 PC가 17:14쯤 부팅한 날 정도다(받아들임).
- lampmanH-pc 재수집은 자기가 10분 전에 찍은 heartbeat에도 한 번 쉰다 → 밤에는 사실상 20분 간격(받아들임).
- chain은 판정 **전에** `git pull --ff-only origin main`을 한다(건너뛰는 날에도) — 사내 다리가 lampmanH-pc를 떠나면
  그 폴더를 당겨 주는 곳이 없다. pull 실패는 기록만 하고 계속 간다(옛 코드로라도 수집은 한다).
- 회사 PC(원격 `gitlab`이 있는 폴더 — push 주소를 가진 유일한 PC, #212)에서는 --check 말고는 돌지 않는다:
  개발 중인 작업 폴더를 pull하지 않고, 같은 작업이 한 PC에서 두 번 돌지 않게.
- 가드 조회 실패는 실행(fail-open) — 가드 때문에 수집이 통째로 빠지면 안 된다(sb_client.ran_recently와 같은 원칙).
- 결과는 system_health.last_standby_<job> 에 남긴다(무엇을 건너뛰었나/대신 돌렸나 — 워치독 대상 아님, 운영 상태 한 줄).

사용(작업 스케줄러 — setup_standby_tasks.ps1이 lampmanH-pc에 등록):
  pythonw.exe run_hidden.py standby_run.py standby_<job>_sched.log <job>
손 확인(어느 PC에서나, 판정만 — 실행·pull·heartbeat 없음):
  py -3.12 standby_run.py <job> --check
"""
import os
import re
import sys
import subprocess

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
CREATE_NO_WINDOW = 0x08000000

# job → guard (heartbeat 키, 건너뜀 시간 h) / 실행 명령 / 판정 전 git pull 여부
JOBS = {
    'refetch':  {'guard': ('last_refetch_run', 0.25),   'run': ('py', 'refetch_content.py')},
    'chain':    {'guard': ('last_gov_notice_run', 20),  'run': ('bat', 'run_gov_crawler.bat'), 'pull': True},
    'briefing': {'guard': None,                         'run': ('py', 'morning_briefing.py')},
    'summary':  {'guard': None,                         'run': ('py', 'summarize_assembly_bills.py')},
}


def has_gitlab_remote(git_config_text: str) -> bool:
    """.git/config에 [remote "gitlab"]가 있으면 True — 회사 PC 작업 폴더의 표지(lampmanH-pc는 origin 하나)."""
    return bool(re.search(r'^\s*\[remote "gitlab"\]', git_config_text or '', re.M))


def decide(guard, age_h):
    """('run'|'skip', 사유). guard=None이면 늘 run. age_h=None(기록 없음·조회 실패)이면 run(fail-open)."""
    if not guard:
        return 'run', '가드 없음(스크립트가 스스로 중복을 막음)'
    key, hours = guard
    if age_h is None:
        return 'run', '%s 조회 불가 — 실행(fail-open)' % key
    if age_h < hours:
        return 'skip', '%s %.2fh 전 실행됨(< %sh)' % (key, age_h, hours)
    return 'run', '%s %.2fh 전(>= %sh) — 대신 실행' % (key, age_h, hours)


def build_cmd(run):
    kind, target = run
    if kind == 'bat':
        return ['cmd', '/c', target]
    return [sys.executable, '-u', target]


def _git(*args, timeout=180):
    r = subprocess.run(['git'] + list(args), cwd=HERE, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=timeout, creationflags=CREATE_NO_WINDOW)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def git_pull() -> str:
    """`git pull --ff-only origin main` — 결과 한 줄(heartbeat note용). 실패해도 예외를 올리지 않는다."""
    try:
        _, before = _git('rev-parse', '--short', 'HEAD', timeout=30)
        rc, out = _git('pull', '--ff-only', 'origin', 'main')
        _, after = _git('rev-parse', '--short', 'HEAD', timeout=30)
        before, after = before.strip(), after.strip()
        print('[pull] rc=%s\n%s' % (rc, out.strip()[:1500]))
        if rc != 0:
            return 'pull 실패 rc=%s (%s 그대로)' % (rc, before)
        return ('pull %s→%s' % (before, after)) if before != after else ('pull 그대로 %s' % after)
    except Exception as e:
        print('[pull 오류 — 계속] %s' % e)
        return 'pull 오류(%s)' % type(e).__name__


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    check = '--check' in argv
    argv = [a for a in argv if a != '--check']
    if len(argv) != 1 or argv[0] not in JOBS:
        print('사용: standby_run.py {%s} [--check]' % '|'.join(JOBS))
        return 2
    job = argv[0]
    spec = JOBS[job]
    os.chdir(HERE)

    try:
        with open(os.path.join(HERE, '.git', 'config'), encoding='utf-8', errors='replace') as f:
            company = has_gitlab_remote(f.read())
    except OSError:
        company = False
    if company and not check:
        print('[대체] 이 폴더에는 원격 gitlab이 있다 = 회사 PC 작업 폴더 — 대체 실행기는 lampmanH-pc 전용이라 멈춘다.')
        return 3

    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(HERE, '.env'))
    except ImportError:
        pass
    from sb_client import make_client, heartbeat, heartbeat_age_hours
    sb = make_client(os.environ['SUPABASE_URL'],
                     os.environ.get('SUPABASE_SERVICE_KEY') or os.environ['SUPABASE_KEY'])

    pull_note = ''
    if spec.get('pull') and not check:
        pull_note = ' · ' + git_pull()

    guard = spec['guard']
    age = heartbeat_age_hours(sb, guard[0]) if guard else None
    verdict, why = decide(guard, age)
    print('[대체] %s → %s — %s%s' % (job, verdict, why, ' (--check: 판정만)' if check else ''))
    if check:
        return 0

    hb_key = 'last_standby_%s' % job
    if verdict == 'skip':
        heartbeat(sb, hb_key, '건너뜀 — %s%s' % (why, pull_note))
        return 0

    cmd = build_cmd(spec['run'])
    print('[대체] 실행: %s' % ' '.join(cmd))
    sys.stdout.flush()
    rc = subprocess.run(cmd, cwd=HERE, creationflags=CREATE_NO_WINDOW).returncode
    heartbeat(sb, hb_key, '대신 실행 exit=%s — %s%s' % (rc, why, pull_note))
    return rc


if __name__ == '__main__':
    sys.exit(main())
