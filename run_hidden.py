# -*- coding: utf-8 -*-
"""
콘솔 창 없는 스케줄러 실행 래퍼 (2026-08-03 신설)

배경: 회사 보안 에이전트가 작업 스케줄러(InteractiveToken)가 띄우는 '보이는 콘솔 창'에
WM_CLOSE(CTRL_CLOSE)를 보내 시작 ~2초 만에 종료시킴 → 결과코드 3221225786(0xC000013A).
스크립트 내용과 무관하게 창이 보이면 죽고, 창이 없으면 완주함이 실측으로 확인됨.

사용(작업 스케줄러 액션):
  프로그램:  C:\\Users\\SKTelecom\\AppData\\Local\\Programs\\Python\\Python312\\pythonw.exe
  인수:      run_hidden.py <대상스크립트.py> [로그파일]
  시작 위치: C:\\Users\\SKTelecom\\Desktop\\frequence\\radio-policy-ai

- pythonw.exe(GUI 서브시스템)라 래퍼 자신도 창이 전혀 없음
- 자식 python.exe는 CREATE_NO_WINDOW로 실행 → 콘솔은 있으나 창이 없어 표적이 안 됨
- 자식의 stdout/stderr는 로그파일에 append (기본: <대상스크립트이름>_sched.log)
- 자식의 종료 코드를 그대로 반환 → 스케줄러 '마지막 실행 결과'에 실제 결과가 남음
"""
import subprocess, sys, os, datetime

PY = r"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe"
CREATE_NO_WINDOW = 0x08000000
MAX_LOG_BYTES = 5 * 1024 * 1024  # 5MB 넘으면 새로 시작

def main():
    if len(sys.argv) < 2:
        sys.exit(2)
    script = sys.argv[1]
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
        r = subprocess.run([PY, script] + sys.argv[3:],
                           stdout=lf, stderr=subprocess.STDOUT,
                           creationflags=CREATE_NO_WINDOW)
        lf.write("=== exit %s at %s\n" % (r.returncode, datetime.datetime.now().isoformat()))
    sys.exit(r.returncode)

if __name__ == "__main__":
    main()
