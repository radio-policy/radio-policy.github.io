# 전파정책 AI — 작업 인수인계 (HANDOFF)

> 같은 PC·같은 Windows 계정에서, **Claude for Windows만 다른 계정**으로 로그인해 작업을 이어받는 동료를 위한 문서.
> 이 파일은 공유 폴더 안에 있으므로 동료 Claude가 폴더를 열면 바로 읽습니다. (공개 repo에 push 불필요)
> 최초 작성: 2026-06-16

---

## 0. 한눈에 — 이어받기 위해 할 일 4가지

1. **Project 지침 붙여넣기** (개인 플랜이라 직접 공유 불가 → 수동 복사)
2. **커넥터(MCP) 재연결** — Supabase, 파일 커넥터 등
3. **작업 폴더 접근 허용** — 같은 경로 그대로 선택
4. **아래 "누적 주의사항" 숙지** — 메모리는 계정 간 안 넘어옴

이미 같은 Windows 계정이라 **로컬 폴더·`.env`·GitHub 인증·Python/trafilatura·작업 스케줄러는 손댈 필요 없이 그대로 공유**됩니다.

---

## 0-1. Claude Code로 이어받는 경우 — 순서대로 7단계 (2026-07-15 추가)

위 §0의 4가지는 **Claude for Windows(Cowork)** 기준. **Claude Code**(CLI/데스크톱 앱)로 이어받으면 아래 순서대로만 하면 됨. 실질적으로 손이 가는 건 ⑤ 커넥터 연결 하나.

### ① (넘기는 사람) 마무리 기록
- 미완 작업이 있으면 §6 작업 로그에 한 줄 남기기.

### ② (넘기는 사람) 세션 완전 종료
- 기존 계정의 Claude Code 창/세션·앱을 **모두 닫기**. 두 계정이 같은 폴더에서 동시에 돌면 stale 커밋 사고(§4-3) 재발 — §5 절대 규칙.

### ③ 로그아웃 → 새 계정 로그인
- 데스크톱 앱: 프로필/설정 → Sign out → 새 계정으로 Sign in.
- 터미널 CLI: `claude` 실행 → `/logout` → `/login` → 브라우저에서 새 계정 인증.

### ④ 같은 폴더 열기
- `C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai`
- 첫 실행 시 "폴더 신뢰" 확인이 뜨면 승인. 이 시점에 **지침(CLAUDE.md)·메모리는 자동 로드** — 별도 작업 불필요 (아래 "자동으로 따라오는 것" 참조).

### ⑤ 커넥터(MCP) 재연결 — 새 계정에서 처음 한 번만
커넥터는 Claude 계정에 붙어 있어 새 계정에는 비어 있음:
1. 브라우저에서 **claude.ai** 접속 → 새 계정(Claude Code와 같은 계정)으로 로그인
2. **Settings → Connectors** 이동
3. **Supabase** 연결 → Supabase 계정 인증 → 프로젝트 `zwkjedumfuhodckmtxxn`(radio-policy-ai) 선택
   - ⚠️ 다른 사람이라 본인 Supabase 계정에 이 프로젝트가 안 보이면 → 기존 담당자가 Supabase 콘솔에서 Organization 멤버로 초대
4. Gmail·Calendar 등은 이 프로젝트 필수 아님 — 필요할 때만 연결. **당장은 Supabase 하나면 충분**
5. 연결 후 Claude Code 재시작(또는 새 세션)하면 커넥터가 잡힘

### ⑥ 새 세션 첫 메시지 — 인수인계 프롬프트
```
작업 인수인계 받았어. 다음을 읽고 현재 상태를 요약해줘:
1. HANDOFF.md (작업 로그와 누적 주의사항)
2. 전파정책AI_지침_운영핵심.md의 "하지 말아야 할 것" 목록
3. git log 최근 커밋 10개 + git status로 미커밋/미추적 파일 현황
그다음 진행 중이던 작업과 주의할 것을 정리해줘.
```
- 작업 중 도구 권한 프롬프트(파일 읽기·git 등)가 처음 몇 번 뜸 → 승인하며 진행.

### ⑦ 이어받기 검증 (1분)
- "Supabase에서 news_feed 최근 1건 조회해줘" → 나오면 커넥터 정상.
- ⑥의 요약 응답에 최근 커밋과 §6 작업 로그 최신 줄이 언급되는지 → 나오면 문서·repo 인계 정상.

### 자동으로 따라오는 것 (같은 Windows 계정이므로 손댈 필요 없음)
- **지침** — repo 안 `CLAUDE.md`가 폴더 열면 자동 로드되고, 정본 지침(`전파정책AI_지침_운영핵심.md`·`전파정책AI_배경역사.md`)도 그 안에서 링크됨. §1의 Project 붙여넣기 **불필요**.
- **메모리** — Claude Code 메모리는 로컬 디스크(`C:\Users\SKTelecom\.claude\projects\...\memory\`)에 저장되므로 같은 Windows 계정이면 다른 Claude 계정에서도 그대로 승계됨. §4 도입부의 "메모리는 계정 간 안 넘어옴"은 **Cowork(클라우드 메모리) 얘기** — 단, §4의 누적 주의사항 자체는 여전히 숙지할 것.
- **세션 기록** — 로컬 `~\.claude\projects\`에 있어 계정 전환 후에도 기존 세션을 열어 이어갈 수 있음.
- `.env`·GitHub 인증·Python 3.12·작업 스케줄러 — 전부 Windows 계정 소속이라 그대로.

---

## 1. Project 지침 (Cowork로 이어받을 때만 필수 — Claude Code는 §0-1 참조)

개인 Claude 플랜끼리는 Project 직접 공유가 안 됩니다(Team/Enterprise 전용 기능). 따라서:

- 동료 Claude 계정에서 **"전파정책AI" Project를 새로 생성**
- 기존 계정의 **Project Instructions 전체 텍스트를 그대로 복사 → 붙여넣기**
- ⚠️ **복사 원본은 repo의 `전파정책AI_지침_운영핵심.md`(정본)를 쓸 것.** `docs/claude_project_instructions.md`는 Cowork Project용 사본인데 **2026-06-17 이후 미갱신 상태**(#19~#23 사고 교훈 누락)라, 그걸 복사하면 낡은 지침으로 시작하게 됨.

> 지침을 바꿀 때는 변경분 요약이 아니라 **변경 반영된 전체 지침 텍스트**를 주고받을 것.

---

## 2. 커넥터(MCP) 재연결 (필수)

커넥터 연결은 Claude 계정별로 따로입니다. 동료 Claude에서 **Settings → Connectors**에서 다시 연결:

- **Supabase** — DB(`radio-policy-ai`, 프로젝트 ID `zwkjedumfuhodckmtxxn`) 직접 조회·수정에 필요
- **파일/문서 커넥터** (Box·Google Drive 등 기존에 쓰던 것)
- 기타 작업에 쓰던 커넥터

DB 멤버 권한이 필요하면 Supabase 콘솔에서 동료를 Organization 멤버로 초대.

---

## 3. 작업 폴더 접근 허용

동료 Claude의 Cowork에서 같은 폴더를 한 번 선택(접근 허용):

```
C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai
```

경로가 동일하므로 그대로 작동합니다.

---

## 4. 누적 주의사항 (메모리 이전 — 중요)

지금까지 작업하며 쌓인 교훈은 기존 계정의 Claude 메모리에만 있고 **동료 Claude는 빈 상태로 시작**합니다. 아래 내용을 동료 Claude의 메모리나 Project 지침에 반영해 두면 같은 실수를 피할 수 있습니다.

### 4-1. 샌드박스 마운트 절단 (가장 자주 사고남)
- Edit/Write 변경이 샌드박스 마운트(`/sessions/.../mnt/`)에 **파일 끝부분이 잘린 채** 반영될 수 있음. 이를 모르고 commit하면 잘린 파일이 push됨.
- `tail`+`wc -l`만으론 못 잡음(잘린 끝도 그럴듯해 보임).
- **확실한 검증:** 커밋 직후 `git show HEAD --stat`의 삭제 줄 수가 의도보다 크면 절단 의심 → `git diff HEAD~1 HEAD | grep '^@@'`로 파일 끝 hunk 확인.
- 복원: `git show HEAD~1:<파일>` 원본에 의도한 편집만 다시 적용 후 재커밋.
- 마운트 절단이 의심되면 **샌드박스에서 커밋하지 말고**, Edit로 실제 디스크에 반영한 뒤 **PC 터미널에서 커밋·푸시**.

### 4-2. git index 손상 (`bad signature 0x00000000`)
- 샌드박스 bash로 add/commit 시 `.git/index`가 깨질 수 있음.
- `.git` 파일 삭제가 막히면 `mcp__cowork__allow_cowork_file_delete` 호출 후:
```bash
rm -f .git/index.lock .git/index
export GIT_INDEX_FILE=/tmp/gidx
git read-tree HEAD && git add <파일> && git commit -m "..." && git push origin main
```

### 4-3. 동시 세션 stale 커밋
- 마운트가 stale하면 `git add -A`/여러 파일 add 시 **다른 작업을 옛 버전으로 되돌려** push할 수 있음(6/12 프론트 되돌림 사고).
- 커밋 전 `git diff --stat HEAD`로 **의도한 파일만** 포함됐는지 확인. `git add -A`/`git add .` 금지, 항상 파일명 지정.
- 푸시 직후 `git show HEAD:index.html | findstr "app.js?v="` 로 원격 반영·캐시버스터 검증.

### 4-4. Windows .bat 인코딩
- `.bat`은 **영문 ASCII + CRLF**로만 작성. UTF-8 한글+LF면 한국어 cmd가 줄을 잘못 파싱해 임의 명령 실행(6/12 백업 실패 원인).
- `.gitattributes`에 `*.bat text eol=crlf` 등록돼 있음.

### 4-5. 부처 인사 뉴스 항상 수집
- 과기정통부·방통위 인사이동 뉴스는 항상 수집 대상. `crawler.py`의 `is_ministry_personnel_news()`가 처리 — 제거 금지.

### 4-7. 구독자 봇 토큰·시크릿 (2026-08-01 신설)
- 텔레그램 봇이 **둘**입니다. 운영자용 `TELEGRAM_BOT_TOKEN`(기존, 나에게만 알림)과 구독자용
  `SUBSCRIBER_BOT_TOKEN`(`정책AI 도우미` @radio_policy_law_ai_bot). **바꿔 넣으면 안 됩니다.**
- 토큰 소재: BotFather(발급·재발급 `/revoke`) → `.env` + GitHub Secrets + **Supabase Edge Function Secrets**.
- Edge Secrets 5종: `SUBSCRIBER_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `CRON_SECRET`,
  `ANTHROPIC_API_KEY`, `OPERATOR_CHAT_ID`. Vault에 `subscriber_cron_secret`(=CRON_SECRET 동일값).
- **콘솔에 값 붙여넣을 때 줄바꿈이 딸려 들어가면 401만 반복**되고 등록은 돼 보입니다. 콘솔의
  SHA256 다이제스트와 로컬 해시를 대조해 확인하세요. (코드는 `.trim()`으로 방어 중)
- 토큰을 새로 발급하면 위 3곳(.env·GitHub·Edge Secrets)을 **모두** 갱신하고
  `python setup_subscriber_bot.py`로 webhook을 다시 걸어야 합니다.
- 시크릿 재생성 도우미: `python init_subscriber_secrets.py --out <경로>` (값을 화면에 안 남기고 파일로 뽑음).
- Supabase CLI 배포용 `SUPABASE_ACCESS_TOKEN`(sbp_…)도 `.env`에 있습니다 — 계정 전체 권한이니 취급 주의.

### 4-8. 코드 파일을 통째로 다시 쓸 때
- `open(w)`는 여는 순간 파일을 비웁니다. 쓰기 중 예외가 나면 **0바이트**가 됩니다.
  실제로 `supabase/functions/telegram-webhook/index.ts`가 그렇게 날아갔습니다(2026-08-01).
- **임시 파일에 쓴 뒤 `os.replace()`로 교체**하세요.
- 새로 만든 파일은 **바로 커밋**해 두세요. git에 한 번도 안 들어간 파일은 되돌릴 방법이 없습니다.

### 4-6. 지침 업데이트 규칙
- 새 크롤러·스크립트·워크플로우 추가, 스케줄/실행 방식 변경, Supabase 테이블 변경, 알림 채널 변경, 시스템 흐름 변경, "하지 말아야 할 것/제약사항" 추가 사실 발견 시 → **Project 지침 업데이트 필요**.
- 단순 버그픽스(동작 변화 없음)는 해당 없음.

---

## 5. 절대 규칙 — 두 Claude를 동시에 띄우지 말 것

같은 폴더·같은 repo를 두 Claude 계정이 **동시에** 작업하면 4-3(stale 커밋 되돌림) 사고가 재발합니다.
**순차로만** 작업하세요 — 한 번에 한 사람.

커밋 작성자는 둘 다 같은 git 설정으로 동일하게 찍히니, 구분이 필요하면 커밋 메시지에 이니셜을 넣으세요.

---

## 6. 작업 인계 절차 (담당자 교대 시 — 양방향)

작업을 **넘기는 사람**은 끝낼 때 아래 "작업 로그"에 한 줄 남기기:
- 바꾼 것 / 진행 중인 것(미완) / 다음 사람이 주의할 것
- 시스템 구조·스케줄·테이블·흐름을 바꿨으면 `docs/claude_project_instructions.md`도 갱신했는지 확인

작업을 **이어받는 사람**은 시작할 때:
1. 상대방 Claude 세션이 닫혀 있는지 확인 (동시 작업 금지 — 4-3 사고 방지)
2. 자기 Claude에게: "git log로 내 마지막 작업 이후 변경 정리 + HANDOFF.md 작업 로그 + docs/claude_project_instructions.md 변경점 알려줘"
3. 지침이 바뀌었으면 **자기 Claude 계정 Project Instructions에 갱신된 전체 지침 다시 붙여넣기**

### 작업 로그 (최신이 위로)

| 날짜 | 작업자 | 바꾼 것 / 진행 중 / 주의할 것 |
|---|---|---|
| 2026-07-15 | 진웅(lampman) | HANDOFF 최신화 — Claude Code 인수 절차(§0-1) 추가, §1 낡은 사본 경고, 로그 공백 보충. **6/20~7/6 작업 요약**(상세는 배경역사 #15~#23): supabase-py HTTP/2 끊김→`sb_client.make_client` 도입(#15) / 운영상태 탭·heartbeat 3종·빈 브리핑 폴백(#16) / 무뉴스 날 🕊️ 통지+placeholder(#17) / PAT 재생성 시 Actions 권한 누락 무음실패 가드(#18) / 스케줄러 cp949 이모지 크래시·옛 폴더 경로 교정(#19) / 법령요약 레이어 regulatory-kb→kb_*, voyage-law-2(#21) / 정부크롤러 7일 무음 중단 복구 — .bat ASCII+CRLF·Python312 전체 경로 고정·StartWhenAvailable(#22) / 자문 검색 병렬화·news_feed upsert 견고화(#23) |
| 2026-06-17 | 진웅(lampman) | 낮시간(KST 09~20시) 크롤이 GitHub cron 블록 드롭으로 며칠째 누락되던 문제 보완 — Supabase pg_cron 잡 `github-daily-crawl-daytime`(KST 09:25~20:25 매시간 workflow_dispatch) 추가. Vault에 `github_pat` 저장. 지침에 pg_cron 섹션·주의사항 반영. (기존 미문서화 cron 잡 briefing-health-check·news-feed-cleanup도 함께 문서화) + 모닝 브리핑 06:00/06:30 정시 스케줄도 매일 드롭돼 늦게/수동 생성되던 문제 보완 — `trigger_briefing_if_missing()` 함수 + pg_cron 잡 8·7(KST 06:05·06:20, 오늘자 없으면 morning_briefing.yml dispatch — GitHub 06:00 직후 오프셋: 동시 발사로 인한 중복 run·드롭 감지 불가 회피) 추가. health-check(10시 경고)는 유지. + 크롤·법령·국회 트리거도 Supabase로 일원화(crawl-trigger-hourly :47 24h / law 11:30 / assembly 10:30, 공용 함수 `dispatch_github_workflow`). daily_crawl.yml은 매시 :17 GitHub 백업으로 단순화 + 08:05 브리핑 백업 스텝 제거. + **무음 실패 감시** 추가: 내부 `check_news_health`(pg_cron 12, 21:00) + 외부 `health_watchdog.py`/`.yml`(GitHub Actions, Supabase 독립, 21:30 + pg_cron 13이 21:35 백업). 텔레그램 토큰은 Vault `telegram_bot_token`. → health_watchdog.py·.yml·daily_crawl.yml·지침 PC에서 push 필요 |
| 2026-06-16 | 유진웅 | HANDOFF.md·지침 최신화. 인수인계 체계 구축 |
| | | |

---

## 7. 참고 링크

- 대시보드: https://radio-policy.gitlab.io/
- GitHub: https://github.com/youjinwoong/radio-policy-ai
- Supabase: https://zwkjedumfuhodckmtxxn.supabase.co
- 담당: 유진웅 (you.jinwoong@gmail.com)
