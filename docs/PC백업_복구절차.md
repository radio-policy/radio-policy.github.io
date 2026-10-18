# 회사 PC 세션 작업물 백업·복구 절차 (#320, 2026-10-18)

코드와 커밋된 문서는 GitLab(주)·GitHub(미러)에 있다. 이 문서는 **회사 PC에만 있는 것** — 클로드 세션 전사본·메모리·
`local_docs/`(git 무시: 설계·판정·준비자료·인계문·측정 결과)·앱 세션 목록·과방위 발언 원문·예약 작업 정의 — 를
매일 한 폴더로 모으고, 구글 드라이브가 그 폴더를 올리고, PC가 망가졌을 때 되살리는 순서다. 비밀값은 이 문서에도
백업에도 없다.

## 1. 무엇이 어디로 가나

예약 작업 `RadioPolicy-PCBackup`(매일 23:30, 사용자 계정·로그온할 때만, 창 없음)이 `pc_backup.py`를 돌려
`%USERPROFILE%\PC백업\` 아래로 **삭제 없이** 복사한다(robocopy `/E` — `/MIR`·`/PURGE` 안 씀). 앱이 지운 옛
전사본도 백업에는 남는다. 23:30에 PC가 꺼져 있었거나 로그인 전이면 다음 로그인 때 한 번 돈다.

| 백업 폴더 | 원본 | 내용 |
|---|---|---|
| `claude-projects\<프로젝트 폴더>\` | `%USERPROFILE%\.claude\projects\<프로젝트 폴더>\` | 세션 전사본(`*.jsonl`)·하위 에이전트·도구 결과·`memory\` |
| `claude\` | `%USERPROFILE%\.claude\CLAUDE.md`·`settings.json` | 전역 지침·설정 |
| `local_docs\` | `<저장소>\local_docs\` | git 무시 작업 문서 |
| `claude-code-sessions\` | Claude 앱 세션 목록(아래 주) | 앱 사이드바 목록 |
| `과방위_발언원문\` | `<저장소 상위 폴더>\과방위_발언원문\` | 회의록 발언 원문(`SPEECH_RAW_DIR`) |
| `예약작업\` | 작업 스케줄러 | `전파정책_*`·`RadioPolicy-*`·`radio_TEMP_*` 작업 XML + `_tasks.csv`(상태·동작 표) |
| `_log\`·`_state\`·`마지막_백업.txt` | — | 월별 실행 로그·비밀값 훑기 캐시(경로·항목 이름만)·마지막 실행 요약 |

- **프로젝트 폴더 이름 규칙**: 저장소 경로에서 영숫자가 아닌 글자를 모두 `-`로 바꾼 것(Claude Code 규칙).
  `C:\Users\<사용자>\Desktop\frequence\radio-policy-ai` → `C--Users-<사용자>-Desktop-frequence-radio-policy-ai`.
  저장소 폴더에서 `py -3.12 -c "import os,re;print(re.sub(r'[^A-Za-z0-9]','-',os.getcwd()))"`로 확인한다.
- **앱 세션 목록 위치**: Claude 앱이 Microsoft Store(MSIX) 앱이면 실제 파일은
  `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Roaming\Claude\claude-code-sessions\`다. 앱 안(세션 셸)에서는
  `%APPDATA%\Claude\...`로 보이지만 작업 스케줄러에서는 그 경로가 없다(10-18 실측). 스토어 앱이 아니면 `%APPDATA%\Claude\`.
- **안 가져가는 것**: 비밀 파일(`.env*`·`.credentials.json`·`.gitlab-credentials`·`.confluence_pat`·`*.pem`)·
  `__pycache__`·`.git`·사내판 전사본·사내판 폴더·`frequence\confluence`·`docs\사내공유_*` — 사내 자료는 개인 드라이브에
  두지 않는다. 사내판은 사내 저장소·사내 절차로 복구한다.
- **비밀값 가림**: 세션 전사본에는 세션이 읽은 토큰이 섞여 있다(10-18 실측 21개 파일). 백업 사본에서는 그 값이
  **같은 길이의 `*`**로 바뀌어 있다 — 되살린 전사본의 `*****`는 정상이다. 가리는 값은 실행 때마다 `.env`(이름에
  KEY·TOKEN·SECRET·PASSWORD·CLIENT_ID)·`~/.gitlab-credentials`·`~/.git-credentials`·`~/.confluence_pat`·
  `~/.claude/.credentials.json`에서 읽고, 흔한 토큰 꼴(`sk-ant-`·`github_pat_`·`ghp_` 등·`glpat-`·`sbp_`·`sb_secret_`·
  service_role JWT)도 가린다. 공개 문서(CLAUDE.md·지침·배경역사)에 이미 실린 값은 가리지 않는다.

## 2. 처음 한 번 — 구글 드라이브 설정 (운영자)

세션은 구글 계정에 로그인할 수 없으므로 이 단계는 운영자가 한다.

1. https://www.google.com/drive/download/ 에서 **Google Drive 데스크톱**을 받아 설치한다(설치가 회사 보안 정책에 막히면
   멈추고 알린다 — 대안은 rclone).
2. 백업을 둘 구글 계정으로 로그인한다(개인 계정인지 회사 계정인지 먼저 정한다).
3. 작업 표시줄 드라이브 아이콘 → 톱니 → **환경설정** → 왼쪽 **내 컴퓨터** → **폴더 추가** →
   `C:\Users\<사용자>\PC백업` 선택 → **Google Drive와 동기화** 선택(「Google 포토에 백업」 아님) → 완료 → 저장.
   **저장소 폴더(`radio-policy-ai`)나 `frequence` 통째를 추가하지 말 것** — git과 충돌하고 `.env`가 평문으로 올라간다.
4. 확인: https://drive.google.com → 왼쪽 **컴퓨터** → 이 PC 이름 → `PC백업` → `마지막_백업.txt`의 시각이 오늘인지.
5. 용량: 10-18 기준 약 4.2GB, 전사본이 한 달에 약 1.5GB씩 는다(삭제 없는 복사라 줄지 않는다). 무료 15GB(지메일·포토와
   공유)는 반년 남짓이면 찬다 — 드라이브 저장용량을 가끔 본다.

## 3. 평소 확인

- 실패하면(빠진 파일·robocopy 오류·원본 없음·작업 내보내기 실패) 운영자 봇으로 「⚠️ PC 백업(…) 이상: …」 한 줄이 온다.
- `PC백업\마지막_백업.txt` — 항목별 원본·백업 파일 수와 용량, 빠짐 0이면 「결과: 이상 없음」.
- 로그: `PC백업\_log\pc_backup_YYYY-MM.log`, 저장소의 `pc_backup_sched.log`(git 무시).
- 손 실행: `py -3.12 pc_backup.py` · 복사 없이 대조만: `py -3.12 pc_backup.py --verify` ·
  예약 작업으로: `Start-ScheduledTask -TaskName RadioPolicy-PCBackup`.
- 다시 등록: 저장소 폴더에서 `powershell -ExecutionPolicy Bypass -File .\setup_pc_backup.ps1`.

## 4. 복구 — 새 PC 또는 초기화 뒤

순서가 중요하다. 3번(복사)은 **Claude 앱을 끈 상태**에서 한다.

1. **준비**: Python 3.12(`py -3.12 --version`), Git, Claude 앱 설치·로그인 → 한 번 켰다가 끈다(앱 폴더가 생기게).
   `pip install -r requirements.txt`는 `py -3.12 -m pip`로.
2. **저장소를 같은 경로에 clone** — `C:\Users\<사용자>\Desktop\frequence\radio-policy-ai`. 경로가 같아야 프로젝트 폴더
   이름이 같고, 사내판 스냅샷이 이 경로와 원격 이름 `gitlab`을 읽는다(바꾸면 사내판에 먼저 알린다).
   ```
   git clone https://gitlab.com/radio-policy/radio-policy.gitlab.io.git radio-policy-ai
   cd radio-policy-ai
   git remote rename origin gitlab
   git remote set-url --add --push gitlab https://gitlab.com/radio-policy/radio-policy.gitlab.io.git
   git remote set-url --add --push gitlab https://github.com/radio-policy/radio-policy.github.io.git
   git remote add origin https://github.com/radio-policy/radio-policy.github.io.git
   ```
   (`git push gitlab main` 한 번에 GitLab → GitHub 둘 다 간다.)
3. **비밀 파일 되살리기 — 백업에 없다**: 저장소의 `.env`, `%USERPROFILE%\.gitlab-credentials`, `%USERPROFILE%\.confluence_pat`
   (둘 다 ASCII로, BOM 없이). 사본은 백업에 없으므로 보관처나 각 발급처에서 다시 받는다(토큰 소재는 HANDOFF.md).
4. **드라이브에서 받기**: drive.google.com → 컴퓨터 → 옛 PC → `PC백업` 다운로드(또는 새 PC 드라이브 앱에서 오프라인 사용).
   받은 폴더를 `<받은곳>`이라 하면, Claude 앱을 끈 뒤 아래 순서로 복사한다(전부 `robocopy <원본> <대상> /E` — `/MIR` 금지):
   1. `<받은곳>\local_docs` → `<저장소>\local_docs`
   2. `<받은곳>\과방위_발언원문` → `<저장소 상위 폴더>\과방위_발언원문`
   3. `<받은곳>\claude\CLAUDE.md`·`settings.json` → `%USERPROFILE%\.claude\`
   4. `<받은곳>\claude-projects\<옛 프로젝트 폴더>` → `%USERPROFILE%\.claude\projects\<새 프로젝트 폴더>`
      (경로가 같으면 이름도 같다. 다르면 1절의 규칙으로 새 이름을 만든다 — 메모리 폴더도 이 안에 있다)
   5. `<받은곳>\claude-code-sessions` → 앱 세션 목록 폴더(1절 주 — 스토어 앱이면 `%LOCALAPPDATA%\Packages\Claude_<id>\
      LocalCache\Roaming\Claude\claude-code-sessions`). **이 단계는 실측 못 했다** — 앱이 이상하거나 목록이 안 맞으면
      이 폴더만 비우고 앱을 다시 켠다(전사본은 4번에 있으니 기록 검색은 된다).
5. **예약 작업 다시 등록**: 경로를 새 PC에 맞게 계산하는 스크립트가 있는 것은 스크립트로 —
   `setup_briefing_backup.ps1`(브리핑 예비)·`setup_assembly_summary_scheduler.ps1`(법안 요약)·`setup_pc_backup.ps1`(이 백업).
   스크립트가 없는 것(`전파정책_정부크롤러` 동작 8개·`RadioPolicy-RefetchContent`·`전파정책_CRMS동기화`·꺼 둔 예비
   `radio_TEMP_*`)은 `<받은곳>\예약작업\<이름>.xml`로 되살린다 — 사용자·경로가 옛 PC와 같을 때:
   `schtasks /Create /TN "<이름>" /XML "<받은곳>\예약작업\<이름>.xml"`(SYSTEM 작업은 관리자 PowerShell에서).
   다르면 XML의 `<UserId>`·`<Command>`·`<WorkingDirectory>`를 고친 뒤 넣는다. `radio_TEMP_*`는 **꺼 둔 채로** 둔다
   (GitHub 정지 때만 켠다). `RadioPolicy-News`·`RadioPolicy-Snapshot`·`RadioPolicy-PeopleSKT`는 사내판 작업이다 —
   XML은 참고용이고 등록은 사내판 절차로.
6. **확인 문구**:
   - `git -C <저장소> status -sb` → `## main...gitlab/main`(앞섬·뒤처짐 없음)
   - `py -3.12 -m unittest discover -s tests` → 마지막 줄 `OK`
   - `Get-ScheduledTask | ? { $_.TaskName -like 'RadioPolicy-*' -or $_.TaskName -like '전파정책_*' } | ft TaskName,State`
     → 옛 `_tasks.csv`와 같은 이름·상태
   - `py -3.12 standby_run.py refetch --check` → 판정 한 줄(가드 조회가 되면 Supabase·.env가 붙은 것)
   - 저장소 폴더에서 새 Claude 세션을 열고 **「시작하자」** → 대기 작업 목록이 나오면 메모리가 붙은 것
   - 다음 근무시간에 대시보드 운영 상태 탭의 PC heartbeat 줄(정부 공고 체인·본문 재수집)이 초록인지
   - `Start-ScheduledTask -TaskName RadioPolicy-PCBackup` 뒤 `PC백업\마지막_백업.txt`가 「결과: 이상 없음」인지
