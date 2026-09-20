# -*- coding: utf-8 -*-
"""
콘솔 창 없는 스케줄러 실행 래퍼 (2026-08-03 신설)

배경: 회사 보안 에이전트가 작업 스케줄러(InteractiveToken)가 띄우는 '보이는 콘솔 창'에
WM_CLOSE(CTRL_CLOSE)를 보내 시작 ~2초 만에 종료시킴 → 결과코드 3221225786(0xC000013A).
스크립트 내용과 무관하게 창이 보이면 죽고, 창이 없으면 완주함이 실측으로 확인됨.

사용(작업 스케줄러 액션):
  프로그램:  <Python 3.12 설치 폴더>\\pythonw.exe
             (경로 확인: py -3.12 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))")
  인수:      run_hidden.py <대상스크립트.py> [로그파일]
  시작 위치: 이 파일이 있는 저장소 폴더 (래퍼가 스스로 자기 폴더로 chdir 하므로 비워 둬도 됨)

- 2026-09-20(#178) 회사 PC 경로 하드코딩 제거 — lampmanH-pc(사용자명·설치 경로가 다름)에서도 그대로 돌게
  python.exe는 이 래퍼를 띄운 pythonw.exe 옆에서 찾고, 작업 폴더는 이 파일의 폴더로 맞춘다.

- pythonw.exe(GUI 서브시스템)라 래퍼 자신도 창이 전혀 없음
- 자식 python.exe는 CREATE_NO_WINDOW로 실행 → 콘솔은 있으나 창이 없어 표적이 안 됨
- 자식의 stdout/stderr는 로그파일에 append (기본: <대상스크립트이름>_sched.log)
- 자식의 종료 코드를 그대로 반환 → 스케줄러 '마지막 실행 결과'에 실제 결과가 남음
"""
import subprocess, sys, os, datetime

# 래퍼를 띄운 인터프리터(pythonw.exe) 옆의 python.exe — 설치 경로를 박지 않아 어느 PC에서나 같은 파일이 돈다(#178).
# 스케줄러 액션의 "프로그램"이 Python 3.12의 pythonw.exe여야 패키지가 있는 3.12로 자식이 뜬다(3.13 함정, 배경역사 #22).
PY = os.path.join(os.path.dirname(sys.executable), "python.exe")
HERE = os.path.dirname(os.path.abspath(__file__))
CREATE_NO_WINDOW = 0x08000000
MAX_LOG_BYTES = 5 * 1024 * 1024  # 5MB 넘으면 새로 시작

def main():
    if len(sys.argv) < 2:
        sys.exit(2)
    script = sys.argv[1]
    os.chdir(HERE)  # 스케줄러 '시작 위치'와 무관하게 저장소 폴더에서 실행(.env·로그 경로 기준, #178)
    logpath = sys.argv[2] if len(sys.argv) > 2 else (
        os.path.splitext(os.path.basename(script))[0] + "_sched.log")
    mode = "a"
    try:
        if os.path.getsize(logpath) > MAX_LOG_BYTES:
            mode = "w"
    except OSError:
        pass
    with open(logpath, mode, encoding="utf-8") as lf:
        lf.write("=== %s launch %s\n" % (datetime.datetime.now().isoformat(), script))
        lf.flush()
        # -u(무버퍼): 중간에 강제 종료돼도 그때까지의 출력이 파일에 남는다.
        # (2026-08-03 크롤러가 7~11분 돌다 외부 종료됐는데 버퍼가 통째로 날아가
        #  어디서 멈췄는지 알 수 없었다 — 진단 불가 상태를 만들지 말 것.)
        r = subprocess.run([PY, "-u", script] + sys.argv[3:],
                           stdout=lf, stderr=subprocess.STDOUT,
                           creationflags=CREATE_NO_WINDOW)
        lf.write("=== exit %s at %s\n" % (r.returncode, datetime.datetime.now().isoformat()))
    sys.exit(r.returncode)

if __name__ == "__main__":
    main()
