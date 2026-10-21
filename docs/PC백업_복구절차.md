# PC백업 복구 안내 — Claude가 순서대로 진행 (#320, 2026-10-18)

> **운영자께:** 새 PC(또는 초기화한 PC)에서 Claude 앱을 설치·로그인한 뒤, **저장소가 아닌 폴더**(예: 다운로드)에서
> 세션을 열고 이 파일을 주며 「이대로 복구해줘」라고 하세요. 이 파일은 백업 폴더 맨 위에도
> `00_복구_시작하기.md`로 매일 복사됩니다(구글 드라이브 → 컴퓨터 → 옛 노트북 → PC백업). 원본은 저장소의
> `docs/PC백업_복구절차.md`이고 공개 저장소에 있으므로 비밀값은 적혀 있지 않습니다.
> 파일 몇 개만 꺼내려면 맨 아래 부록 D만 보면 됩니다.

## 0. 이 파일을 받은 Claude에게 — 진행 규칙

- 운영자에게는 **한국어로**, 단계 번호를 붙여 하나씩 알린다. 한 단계가 끝날 때마다 무엇을 했고 다음이 무엇인지 한 줄.
- 각 단계는 **확인 → (안 돼 있을 때만) 실행 → 확인 문구** 순서다. 이미 돼 있으면 건너뛰고 그렇다고 말한다(같은 PC의
  일부 복구도 이 문서로 한다).
- **「운영자에게 부탁」** 표시가 붙은 일은 직접 하지 않는다 — 무엇을 해 달라고 말하고 끝났다는 답을 기다린다.
  로그인, 관리자 권한이 필요한 설치·등록, 백업에 없는 비밀값(토큰) 새로 넣기가 여기 해당한다. 백업의 `비밀파일\`을 제자리로
  복사하는 것(5단계)은 세션이 한다. **비밀값을 대신 입력하거나 화면에 출력하지 않는다** — `.env`는 키 이름만 본다.
- **지우지 않는다.** `robocopy /MIR`·`/PURGE`·`Remove-Item`을 쓰지 않는다. 복사는 아래 꼴만 쓴다 — 대상에 **없는 파일만**
  채운다(`/XC /XN /XO`: 이미 있는 파일은 크기·시각이 달라도 건드리지 않는다). robocopy 종료 코드 0~7은 정상, 8 이상은 멈추고 보고.
  ```
  robocopy "<원본>" "<대상>" /E /XC /XN /XO /R:2 /W:5 /NP /NFL /NDL
  ```
- 셸 변수는 호출 사이에 남지 않는다. PowerShell 명령마다 앞에 아래 줄을 붙인다(`$B`는 3단계에서 정한 값으로 바꿔 넣는다):
  ```powershell
  $R = "$env:USERPROFILE\Desktop\frequence\radio-policy-ai"; $F = Split-Path $R; $B = '<PC백업 폴더>'; $slug = $R -replace '[^A-Za-z0-9]','-'
  ```
  `$R` 저장소 · `$F` frequence 폴더 · `$B` 백업 · `$slug` 이 저장소의 Claude 프로젝트 폴더 이름(경로에서 영숫자가 아닌 글자를
  모두 `-`로 — Claude Code 규칙).
- 세션 셸에 회사 프록시 변수(`HTTP_PROXY`·`HTTPS_PROXY`)가 들어 있으면 크롤러·테스트를 손으로 돌리기 전에 그 명령에서만 비운다.
- 막히면(권한 거부, 파일 없음, 예상과 다른 출력) 추측해서 우회하지 말고 출력 그대로 보여 주며 운영자에게 묻는다.

## 1. 지금 상태 보기

- **확인:** `whoami`, `$env:USERPROFILE`, `Test-Path $R\.git`, `Test-Path "$env:USERPROFILE\.claude\projects\$slug"`,
  `py -3.12 --version`, `git --version`.
- 결과를 표로 보여 주고 아래 단계 중 무엇이 필요한지 말한다.
- **옛 회사 PC가 아직 켜져서 예약 작업을 돌리고 있는지 운영자에게 묻는다.** 두 PC가 같은 작업을 돌리면 정부 공고가 두 번
  저장되고 알림이 두 번 간다 — 그렇다면 8단계 전에 옛 PC 작업을 먼저 꺼 달라고 부탁한다.

## 2. 기본 프로그램 — 운영자에게 부탁

- **확인 문구:** `py -3.12 --version` → `Python 3.12.x`, `git --version` → `git version …`.
- 없으면 **운영자에게 부탁:** Python 3.12(python.org Windows 설치본 — 「py launcher」 포함, 사용자 설치)와 Git for Windows 설치.
  **주의:** `python`·`py -3`는 다른 판(3.13)을 부를 수 있다 — 이 시스템은 언제나 `py -3.12`로 부른다.

## 3. 백업 폴더 찾기

- **운영자에게 묻는다:** PC백업이 어디 있나요?
  - 새 PC에 구글 드라이브 앱을 같은 계정으로 깔았다면: 드라이브 문자(보통 `G:\`) 아래의 다른 컴퓨터 폴더(이름은 판마다 다르다
    — `Get-ChildItem G:\`로 찾는다) → 옛 노트북 이름 → `PC백업`. 거기서 바로 복사하면 파일을 받으면서 복사한다(4GB 넘음 —
    시간이 걸린다).
  - 웹에서 내려받았다면: 압축을 푼 폴더 경로(여러 zip으로 나뉘면 모두 같은 폴더에 푼다).
- **확인 문구:** `$B` 안에 `마지막_백업.txt`·`claude-projects`·`local_docs`·`claude`·`예약작업`·`비밀파일`이 있다
  (`비밀파일`이 없으면 10-18 밤 이전 백업이다 — 5단계에서 운영자에게 부탁).
  `마지막_백업.txt`를 보여 주고 그 날짜가 맞는지 운영자에게 확인받는다.

## 4. 저장소 받기 — 같은 경로에

- **확인:** `git -C $R status -sb`가 `## main...gitlab/main`이면 건너뛴다.
- **실행:** (`$F` 폴더가 없으면 만든다 — 새로 만드는 것은 지우기가 아니다)
  ```powershell
  New-Item -ItemType Directory -Force $F | Out-Null
  git clone https://gitlab.com/radio-policy/radio-policy.gitlab.io.git $R
  git -C $R remote rename origin gitlab
  git -C $R remote set-url --add --push gitlab https://gitlab.com/radio-policy/radio-policy.gitlab.io.git
  git -C $R remote set-url --add --push gitlab https://github.com/radio-policy/radio-policy.github.io.git
  git -C $R remote add origin https://github.com/radio-policy/radio-policy.github.io.git
  git -C $R config credential.https://gitlab.com.username oauth2
  git -C $R config --add credential.https://gitlab.com.helper ""
  git -C $R config --add credential.https://gitlab.com.helper "store --file=$($env:USERPROFILE -replace '\\','/')/.gitlab-credentials"
  ```
  커밋 작성자 이름·메일은 옛 PC와 같게: `git -C $R log -1 --format='%an %ae'`로 보이는 값을 운영자에게 확인받아
  `git -C $R config user.name …` / `user.email …`.
- 경로가 옛 PC와 다르면(사용자 폴더 이름이 바뀐 경우 등) 운영자에게 알린다 — 사내판 스냅샷이 이 경로와 원격 이름 `gitlab`을
  읽으므로 **사내판에 먼저 알려야 한다**.
- **확인 문구:** `git -C $R status -sb` → `## main...gitlab/main`, `git -C $R remote -v`에 gitlab push 주소 두 줄.

## 5. 비밀 파일 되살리기

운영자 결정(10-18 밤): 구글 드라이브가 털리지 않는다는 가정에서 `.env`와 `.gitlab-credentials`는 **암호 없이 원본 그대로**
매일 `PC백업\비밀파일\`에 복사된다. 그대로 제자리에 되돌리면 된다.

- **확인:** `Test-Path "$R\.env"`, `Test-Path "$env:USERPROFILE\.gitlab-credentials"` — 이미 있는 파일은 건너뛴다(덮지 않는다).
- **실행(없는 것만, 값은 출력하지 않는다 — 4단계로 `$R`이 있어야 한다):**
  ```powershell
  if (-not (Test-Path "$R\.env")) { Copy-Item -LiteralPath "$B\비밀파일\.env" -Destination "$R\.env" }
  if (-not (Test-Path "$env:USERPROFILE\.gitlab-credentials")) { Copy-Item -LiteralPath "$B\비밀파일\.gitlab-credentials" -Destination "$env:USERPROFILE\.gitlab-credentials" }
  ```
- `$B\비밀파일\`이 없거나 그 안에 파일이 없으면 **운영자에게 부탁:** 각 발급처에서 다시 받아 아래 표 형식으로 넣는다
  (토큰 소재는 저장소 `HANDOFF.md`).
- **백업에 없는 것 — 운영자에게 부탁:** `.confluence_pat`(사내 컨플루언스 열쇠라 개인 드라이브에 두지 않는다 — 컨플루언스
  프로필의 개인 액세스 토큰에서 다시 발급해 아래 형식으로), GitHub 로그인(첫 `git push` 때 뜨는 창).

| 파일 | 위치 | 형식 |
|---|---|---|
| `.env` | `$R\.env` | `이름=값` 줄. 필요한 키 이름: SUPABASE_URL · SUPABASE_SERVICE_KEY · ANTHROPIC_API_KEY · EMAIL_FROM · EMAIL_PASSWORD · EMAIL_TO · TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID · RESEND_API_KEY · VOYAGE_API_KEY · LAW_OC_KEY · ASSEMBLY_API_KEY · NAVER_CLIENT_ID · NAVER_CLIENT_SECRET · SUBSCRIBER_BOT_TOKEN · TELEGRAM_WEBHOOK_SECRET · CRON_SECRET · SUPABASE_ACCESS_TOKEN |
| `.gitlab-credentials` | `%USERPROFILE%\.gitlab-credentials` | 한 줄 `https://oauth2:<GitLab 토큰>@gitlab.com` — **ASCII, BOM 없이** |
| `.confluence_pat` | `%USERPROFILE%\.confluence_pat` | 토큰 한 줄 — **ASCII, BOM 없이**(UTF-8로 저장하면 BOM이 붙어 401) |

- GitHub push 인증은 Windows 자격 증명 관리자다 — 첫 `git push` 때 뜨는 로그인 창에서 운영자가 로그인한다.
- **확인(값은 출력하지 않는다):**
  ```powershell
  (Get-Content "$R\.env" | Where-Object { $_ -match '^\s*[A-Z0-9_]+\s*=' } | ForEach-Object { ($_ -split '=')[0].Trim() }) -join ', '
  ```
  위 표의 키 이름이 다 있는지 보고, 빠진 이름만 운영자에게 알린다. 두 자격 파일은 `Test-Path`와 첫 바이트(BOM 아님)만 본다.

## 6. 파이썬 패키지

- **확인:** `py -3.12 -c "import supabase, anthropic, trafilatura"`가 오류 없이 끝나면 건너뛴다.
- **실행:** `py -3.12 -m pip install -r $R\requirements.txt` (`requirements.txt`의 고정 판을 풀지 않는다).

## 7. 작업물 되살리기

0단계의 robocopy 꼴(없는 파일만 채움)로, 이 순서대로:

1. `$B\local_docs` → `$R\local_docs`
2. `$B\과방위_발언원문` → `$F\과방위_발언원문`
3. `$B\claude-projects\<그 안의 폴더 하나>` → `$env:USERPROFILE\.claude\projects\$slug`
   — 백업 안 폴더 이름은 옛 경로로 만든 이름이라 새 이름과 다를 수 있다. 다르면 새 이름(`$slug`)으로 넣는다.
   세션 전사본과 메모리(`memory\`)가 여기 들어 있다. 이 복구 세션은 저장소가 아닌 폴더에서 열었으므로 자기 기록과 섞이지 않는다.
4. `$B\claude\CLAUDE.md` → `$env:USERPROFILE\.claude\CLAUDE.md` (없을 때만).
   `$B\claude\settings.json`은 대상에 파일이 없으면 넣고, **이미 있으면 덮지 말고** 옆에 `settings.백업본.json`으로 넣은 뒤
   운영자에게 두 파일이 다르다고 알린다.
5. **앱 세션 목록 — 운영자에게 부탁(선택, 실측 안 됨).** Claude 앱이 켜진 동안에는 앱이 이 폴더를 다시 쓰므로 세션이 할 수 없다.
   아래 한 줄에 `$B` 값을 채워 건네고, 운영자가 **Claude 앱을 한 번 켜서 로그인한 다음 완전히 끈 뒤** PowerShell에서 실행하게 한다.
   대상은 지금 앱이 쓰는 폴더다 — `%LOCALAPPDATA%\Claude-Data\claude_<id>\`(2026-10-20 이후 앱) → 없으면 스토어 앱의
   `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Roaming\Claude\` → 없으면 `%APPDATA%\Claude\` 순으로 처음 있는 것(한 줄이 고른다):
   ```powershell
   $d = Get-ChildItem "$env:LOCALAPPDATA\Claude-Data" -Directory -Filter 'claude_*' -ErrorAction SilentlyContinue | Select-Object -First 1; $p = Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -Filter 'Claude_*' -ErrorAction SilentlyContinue | Select-Object -First 1; if ($d) { $t = "$($d.FullName)\claude-code-sessions" } elseif ($p) { $t = "$($p.FullName)\LocalCache\Roaming\Claude\claude-code-sessions" } else { $t = "$env:APPDATA\Claude\claude-code-sessions" }; $t; robocopy "<B>\claude-code-sessions" $t /E /XC /XN /XO
   ```
   앱이 이상해지면 그 대상 폴더만 비우고 앱을 다시 켜면 된다 — 전사본은 3번에 이미 있어 기록 검색은 된다.

- **확인 문구:** 항목마다 `(Get-ChildItem <대상> -Recurse -File).Count`가 `$B` 쪽 수 이상.
- 백업 사본의 전사본에서 토큰 자리가 `*****`로 보이는 것은 정상이다(백업이 같은 길이로 가렸다).
- 사내 자료(`frequence\confluence`·`docs\사내공유_*`·사내판 폴더·사내판 전사본)는 이 백업에 없다 — 사내 절차로 복구한다.

## 8. 예약 작업 다시 등록

옛 PC의 목록은 `$B\예약작업\_tasks.csv`(이름·상태·사용자·동작), 정의는 같은 폴더의 `<이름>.xml`이다. 1단계에서 옛 PC가
아직 돌고 있다고 했으면 **옛 PC 작업을 먼저 끈 뒤에** 한다.

| 작업 | 옛 상태 | 되살리는 법 |
|---|---|---|
| `RadioPolicy-BriefingBackup` | 켜짐 | `powershell -ExecutionPolicy Bypass -File $R\setup_briefing_backup.ps1` |
| `RadioPolicy-PCBackup` | 켜짐 | `powershell -ExecutionPolicy Bypass -File $R\setup_pc_backup.ps1` |
| `RadioPolicy-AssemblySummary` | 켜짐 | `setup_assembly_summary_scheduler.ps1` — 높은 권한 작업이라 **운영자에게 부탁**(관리자 PowerShell에서) |
| `RadioPolicy-RefetchContent` | 켜짐 | XML(사용자 작업) |
| `전파정책_정부크롤러`(동작 8개)·`전파정책_CRMS동기화` | 켜짐 | XML(SYSTEM 작업) — **운영자에게 부탁**(관리자 PowerShell에서) |
| `radio_TEMP_*` 9개 | **꺼짐** | XML — 꺼진 채로 넣는다(GitHub 정지 때만 켜는 예비) |
| `전파정책_로컬미리보기` | 꺼짐 | 넣지 않아도 된다 |
| `RadioPolicy-News`·`RadioPolicy-Snapshot`·`RadioPolicy-PeopleSKT` | — | **사내판 작업 — 넣지 않는다**(사내판 절차) |

XML로 넣는 법: 같은 도메인 계정이면 XML의 사용자(SID)는 그대로 맞는다. 바꿔야 하는 것은 경로뿐이다 — XML 안의
`<Command>`(pythonw.exe 경로)와 `<WorkingDirectory>`가 새 PC에 있는지 `Test-Path`로 보고, 다르면 새 값으로 바꿔 넣는다.
새 pythonw 경로: `py -3.12 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"`.
```powershell
$x = Get-Content -Raw -Encoding Unicode "$B\예약작업\<이름>.xml"
$x = $x.Replace('<옛 pythonw 경로>', '<새 pythonw 경로>').Replace('<옛 저장소 경로>', $R)
Register-ScheduledTask -TaskName '<이름>' -Xml $x
```
SYSTEM 작업은 같은 세 줄을 운영자가 관리자 PowerShell에서 실행한다(세션이 값을 채운 명령을 건넨다).

- **확인 문구:** 아래 출력이 `_tasks.csv`의 이름·상태와 같다(사내판 셋 제외).
  ```powershell
  Get-ScheduledTask | Where-Object { $_.TaskName -like 'RadioPolicy-*' -or $_.TaskName -like '전파정책_*' -or $_.TaskName -like 'radio_TEMP_*' } | Format-Table TaskName, State
  ```
  등록한 작업마다 `(Get-ScheduledTask <이름>).Actions | Format-List Execute, Arguments, WorkingDirectory`로 동작 줄이 비지
  않았는지 본다.

## 9. 구글 드라이브 다시 연결 — 운영자에게 부탁

부록 B 순서대로 새 PC의 `%USERPROFILE%\PC백업`을 「내 컴퓨터」에 지정한다(드라이브에는 새 컴퓨터로 따로 쌓인다).
**바탕화면·문서·다운로드는 켜지 않는다** — 바탕화면 아래 `frequence`에 저장소(git과 충돌)와 사내 자료(`frequence\confluence`)가 있다.

## 10. 마지막 확인

| 확인 | 기대 결과 |
|---|---|
| `git -C $R status -sb` | `## main...gitlab/main` |
| `cd $R; py -3.12 -m unittest discover -s tests` | 마지막 줄 `OK` |
| `cd $R; py -3.12 standby_run.py refetch --check` | 판정 한 줄(Supabase 조회가 되면 `.env`가 붙은 것) |
| `Start-ScheduledTask RadioPolicy-PCBackup` 뒤 `%USERPROFILE%\PC백업\마지막_백업.txt` | 마지막 줄 「결과: 이상 없음」 |
| 저장소 폴더에서 새 Claude 세션을 열고 **「시작하자」** | 대기 작업 목록이 나오면 메모리가 붙은 것 |
| 다음 근무시간에 대시보드 운영 상태 탭의 PC 줄(정부 공고 체인·본문 재수집) | 초록 |

끝나면 운영자에게 표로 보고한다: 되살린 것(항목별 파일 수), 운영자에게 남은 일(못 끝낸 부탁 단계), 경로가 바뀌었으면
「사내판에 알릴 것」. 이 복구 세션 창은 운영자가 보관한다.

---

## 부록 A. 백업이 무엇을 어디에 두나

예약 작업 `RadioPolicy-PCBackup`(매일 23:30, 사용자 계정·로그온할 때만, 창 없음)이 `pc_backup.py`를 돌려
`%USERPROFILE%\PC백업\` 아래로 **삭제 없이** 복사한다(robocopy `/E` — `/MIR`·`/PURGE` 안 씀). 앱이 지운 옛 전사본도
백업에는 남는다. 23:30에 PC가 꺼져 있었거나 로그인 전이면 다음 로그인 때 한 번 돈다.

| 백업 폴더 | 원본 | 내용 |
|---|---|---|
| `00_복구_시작하기.md` | 저장소 `docs/PC백업_복구절차.md` | 이 안내(매 실행 최신으로) |
| `claude-projects\<프로젝트 폴더>\` | `%USERPROFILE%\.claude\projects\<프로젝트 폴더>\` | 세션 전사본(`*.jsonl`)·하위 에이전트·도구 결과·`memory\` |
| `claude\` | `%USERPROFILE%\.claude\CLAUDE.md`·`settings.json` | 전역 지침·설정 |
| `local_docs\` | `<저장소>\local_docs\` | git 무시 작업 문서(설계·판정·준비자료·인계문·측정 결과) |
| `claude-code-sessions\` | Claude 앱 세션 목록(아래 주) | 앱 사이드바 목록 |
| `과방위_발언원문\` | `<저장소 상위 폴더>\과방위_발언원문\` | 회의록 발언 원문(`SPEECH_RAW_DIR`) |
| `예약작업\` | 작업 스케줄러 | `전파정책_*`·`RadioPolicy-*`·`radio_TEMP_*` 작업 XML + `_tasks.csv` |
| `비밀파일\` | `<저장소>\.env`·`%USERPROFILE%\.gitlab-credentials` | 원본 그대로(암호 없음 — 운영자 결정 10-18 밤) |
| `_log\`·`_state\`·`마지막_백업.txt` | — | 월별 실행 로그·비밀값 훑기 캐시(경로·항목 이름만)·마지막 실행 요약 |

- **프로젝트 폴더 이름**: 저장소 경로에서 영숫자가 아닌 글자를 모두 `-`로 바꾼 것.
  `C:\Users\<사용자>\Desktop\frequence\radio-policy-ai` → `C--Users-<사용자>-Desktop-frequence-radio-policy-ai`.
- **앱 세션 목록 위치**: 2026-10-20 18:15 앱 업데이트 뒤 실제 파일은
  `%LOCALAPPDATA%\Claude-Data\claude_<id>\claude-code-sessions\`다(같은 폴더에 계정별 앱 예약 등록 `scheduled-tasks.json`도 있다).
  그 전 Microsoft Store(MSIX) 앱은 `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Roaming\Claude\claude-code-sessions\`에
  두었다 — 앱 안(세션 셸)에서는 `%APPDATA%\Claude\...`로 보였지만 작업 스케줄러에서는 그 경로가 없었고(10-18 실측), 업데이트 뒤
  옛 폴더에는 표지 파일(`.user-data-left.*`)만 남는다. 백업은 새 위치 → 옛 패키지 위치 → `%APPDATA%\Claude\` 순으로 처음 있는 것을 쓴다.
- **안 가져가는 것**: 위 폴더들 안의 비밀 파일 사본(`.env*`·`.credentials.json`·`.gitlab-credentials`·`.confluence_pat`·`*.pem`
  — `.env`·`.gitlab-credentials` 원본 둘만 `비밀파일\`로 따로)·`__pycache__`·`.git`·사내판 전사본·사내판 폴더·
  `frequence\confluence`·`docs\사내공유_*`·사내 컨플루언스 열쇠(`.confluence_pat`) — 사내 자료는 개인 드라이브에 두지 않는다.
- **드라이브 계정 보호**: `비밀파일\`에 키가 그대로 있으므로 구글 계정에 2단계 인증을 켜 두고, `PC백업` 폴더를 다른 사람과
  공유하지 않는다. 계정이 털렸다고 의심되면 `.env`의 키와 GitLab 토큰을 모두 다시 발급한다(HANDOFF.md 토큰 소재).
- **비밀값 가림**: 세션 전사본에는 세션이 읽은 토큰이 섞여 있다(10-18 실측 21개 파일). 백업 사본에서는 그 값이 **같은 길이의
  `*`**로 바뀌어 있다. 가리는 값은 실행 때마다 `.env`(이름에 KEY·TOKEN·SECRET·PASSWORD·CLIENT_ID)·`~/.gitlab-credentials`·
  `~/.git-credentials`·`~/.confluence_pat`·`~/.claude/.credentials.json`에서 읽고, 흔한 토큰 꼴(`sk-ant-`·`github_pat_`·
  `ghp_` 등·`glpat-`·`sbp_`·`sb_secret_`·service_role JWT)도 가린다. 공개 문서(CLAUDE.md·지침·배경역사)에 이미 실린 값은
  가리지 않는다.

## 부록 B. 구글 드라이브 설정 (운영자)

세션은 구글 계정에 로그인할 수 없으므로 운영자가 한다.

1. https://www.google.com/drive/download/ 에서 **Google Drive 데스크톱**을 설치한다(회사 보안 정책에 막히면 알린다 — 대안은 rclone).
2. 백업을 둘 구글 계정으로 로그인한다.
3. 첫 화면(또는 작업 표시줄 드라이브 아이콘 → 톱니 → **환경설정** → **내 컴퓨터**)에서 **폴더 추가** →
   `C:\Users\<사용자>\PC백업` → **Google Drive와 동기화**(「Google 포토에 백업」 아님) → 다음/저장.
   추천 폴더(Documents·Desktop·Downloads)는 **체크하지 않는다**. 저장소 폴더나 `frequence` 통째도 넣지 않는다 — git과
   충돌하고 사내 자료(`frequence\confluence`)까지 올라간다. 「File Explorer에서 Drive 파일 보기」는 스트리밍(기본값) 그대로.
4. 확인: https://drive.google.com → 왼쪽 **컴퓨터** → 이 PC 이름 → `PC백업` → `마지막_백업.txt`의 시각.
5. 용량: 10-18 기준 약 4.2GB, 전사본이 한 달에 약 1.5GB씩 는다(삭제 없는 복사라 줄지 않는다). 무료 15GB(지메일·포토와
   공유)는 반년 남짓이면 찬다.

## 부록 C. 평소 확인

- 실패하면(빠진 파일·robocopy 오류·원본 없음·작업 내보내기·복구 안내·비밀 파일 복사 실패) 운영자 봇으로 「⚠️ PC 백업(…) 이상: …」 한 줄이 온다.
- **구글 드라이브 앱은 평소 꺼 둬도 된다**(메모리 확보, 10-21). 매일 백업이 끝나면 꺼져 있을 때만 앱을 켜서, PC백업
  전체가 올라가면(보통 몇 분) 다시 끈다. 45분 안에 안 끝나거나 켜지·끄지 못하면 앱을 켜 둔 채 「⚠️ PC 백업(…) 드라이브: …」
  한 줄이 온다 — 그때는 앱이 끝까지 올리게 두었다가 직접 끄면 된다. 운영자가 켜 둔 앱은 백업이 끄지 않는다.
  로그 줄 `드라이브: synced_closed (… 초)`가 정상이다. 수동 실행에서 이 단계를 빼려면 `--no-drive`.
- `PC백업\마지막_백업.txt` — 항목별 원본·백업 파일 수와 용량, 빠짐 0이면 「결과: 이상 없음」.
- 로그: `PC백업\_log\pc_backup_YYYY-MM.log`, 저장소의 `pc_backup_sched.log`(git 무시).
- 손 실행: `py -3.12 pc_backup.py` · 복사 없이 대조만: `py -3.12 pc_backup.py --verify` ·
  예약 작업으로: `Start-ScheduledTask -TaskName RadioPolicy-PCBackup`.
- 다시 등록: 저장소 폴더에서 `powershell -ExecutionPolicy Bypass -File .\setup_pc_backup.ps1`.

## 부록 D. 파일 몇 개만 꺼낼 때 (PC는 멀쩡함)

- 같은 PC의 `%USERPROFILE%\PC백업\`에서 바로 꺼낸다 — 백업은 지우지 않고 쌓기만 하니 원본에서 사라진 파일(앱이 지운 옛 전사본,
  실수로 지운 local_docs 문서)도 남아 있다.
- 백업 폴더까지 없어졌으면 drive.google.com → **컴퓨터** → 이 노트북 → **PC백업**에서 그 파일만 내려받는다.
- 바로 전 판이 필요하면 드라이브에서 파일 오른쪽 클릭 → **파일 정보 → 버전 관리**(드라이브가 보관하는 기간 안에서만).
