# 전파정책 AI 프로젝트 — Claude Project 지침

## 지침 관리 규칙

- **지침을 변경해야 할 때는 변경분 요약이 아니라, 변경이 반영된 전체 지침 텍스트를 제공할 것** (사용자가 그대로 복사해 Project 설정에 붙여넣을 수 있도록)

## 프로젝트 개요

SKT Comm센터 기술정책팀의 전파·통신 정책 모니터링 자동화 시스템입니다.
- 대시보드: https://radio-policy.gitlab.io/
- GitHub: https://github.com/youjinwoong/radio-policy-ai
- 담당자: 유진웅 (you.jinwoong@gmail.com)

## 로컬 파일 위치

```
C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai\
├── crawler.py              # 메인 크롤러 (GitHub Actions 매시간) — 긴급도 분류에 담당자 피드백 학습(유사 사례+증류 규칙)
│                           #   crawl_naver_news: 네이버 검색 OpenAPI(JSON) — 구 HTML 스크래핑 폐지, 키 없으면 Google RSS 폴백
│                           #   fetch_article_body(본문 수집): 정부 게시판(rra.go.kr 등)은 trafilatura 우선 추출
│                           #     (일반 'article' 셀렉터가 페이지 전체 네비게이션을 오탐하는 문제 회피)
│                           #   _http_get: DH_KEY_TOO_SMALL SSL 약점 사이트는 SECLEVEL=1 어댑터로 도메인 무관 자동 재시도
│                           #     (rra.go.kr는 _KNOWN_WEAK_DH로 처음부터 어댑터 사용 + EUC-KR 인코딩)
├── morning_briefing.py     # 모닝 브리핑 생성·발송 (GitHub Actions 06:00 KST)
│                           #   🔴=DB 긴급도, SKT 영향 분석 생성·저장
│                           #   신규 입법예고(lsAnc, 24h) → 브리핑 앞에 📢 섹션 삽입 (주요 내용 summary 줄 포함)
├── refetch_content.py      # 본문 재수집 + 뉴스 요약 자동 생성 + 15일 초과 기사 일괄 정리 (Windows 작업 스케줄러, 한국 IP 필수)
├── gov_notice_crawler.py   # 정부 고시·예규 크롤링 (Windows 작업 스케줄러 17:00, 한국 IP 필수)
│                           #   RRA·MSIT·KCC → news_feed 저장
│                           #   입법예고(opinion.lawmaking.go.kr) → law_amendments 저장 + 신규 시 텔레그램·이메일 즉시 알림
│                           #     진행 중 입법예고 전체 목록을 페이지 단위(pageIndex) 스캔 → 제명 키워드 + 소관부처 보강 매칭
│                           #     (방송미디어통신위·방송통신위 소관 전체, 과기정통부는 통신 힌트 / "○○부 소관" 접두사 제거로 부처명 오탐 차단 / 직제·정원 제외)
│                           #     backfill_opinion_summaries: 상세 본문 → Haiku 요약 → law_amendments.summary (주요 내용)
│                           #   ※ 입법예고(lsAnc) 수집·요약은 이 크롤러가 단독 담당 (law.go.kr DRF는 입법예고 미지원)
├── law_crawler.py          # 법제처 국가법령정보 DRF Open API 법령·고시 변경 모니터링 (GitHub Actions 11:00 KST)
│                           #   엔드포인트: http://www.law.go.kr/DRF/lawSearch.do (OC=radiopolicyai)
│                           #   target=law(현행)+eflaw(시행예정)+admrul(고시) → law_amendments 저장 + 텔레그램 알림
│                           #   법령구분명으로 law_type 판정(법률→law / 대통령령→bylaw / 총리령·부령→rules / 고시→admrul)
│                           #   첫 실행(테이블 비어있음)은 알림 생략하고 베이스라인만 저장
│                           #   timeout-minutes: 25, 요청 timeout: 10s
├── assembly_crawler.py     # 국회 법안 모니터링 (GitHub Actions — assembly_crawl.yml)
│                           #   열린국회정보 API, 22대 국회, 전파·통신 키워드 법안 → assembly_bills 저장
├── upload_law_pdf.py       # PDF/MD/PPTX → document_chunks RAG 업로드 (조문 헤더 단위 청킹, article_no=조항번호+제목)
├── backfill_embeddings.py  # Voyage 임베딩 백필 (신규 문서 업로드 후 실행, NULL 청크만 처리)
├── resend_briefing.py      # 특정 날짜 브리핑 즉시 재발송 (수동 실행용)
├── send_briefing.py        # 브리핑 발송 단독 스크립트
├── health_watchdog.py      # 외부 헬스 워치독 (GitHub Actions 실행, Supabase 독립) — 파이프라인 무음 정지 감지 → 텔레그램
├── run_gov_crawler.bat     # gov_notice_crawler.py 배치 실행 파일
├── run_briefing_backup.bat # 모닝 브리핑 로컬 백업 배치 실행 파일
├── setup_scheduler.ps1     # Windows 작업 스케줄러 등록 스크립트
├── setup_briefing_backup.ps1 # 브리핑 로컬 백업 작업 스케줄러 등록 스크립트
├── system_prompt.js        # 대시보드 AI 자문 시스템 프롬프트 (위임 관계 검증 규칙·핵심 조문 직접 참조 포함)
├── index.html / app.js     # 대시보드 프론트엔드 (GitHub Pages)
│                           #   ※ AI 자문(callClaude)은 SSE 스트리밍 수신(stream:true) — 비스트리밍 복귀 금지
└── .github/workflows/
    ├── daily_crawl.yml     # 매시간 크롤링 워크플로우
    ├── morning_briefing.yml # 매일 06:00 KST 브리핑 워크플로우
    ├── law_crawl.yml       # 매일 11:00 KST 법령 모니터링 (timeout-minutes: 25)
    ├── assembly_crawl.yml  # 국회 법안 모니터링 워크플로우 (매일 10:00 KST)
    ├── backfill.yml        # 1달치 백필 (수동 1회용)
    ├── cleanup.yml         # 뉴스 데이터 정리 (수동 1회용)
    └── health_watchdog.yml # 외부 헬스 워치독 (매일 KST 21:30 + pg_cron 21:35 백업 dispatch)
```

## Supabase DB

- **프로젝트명**: radio-policy-ai / **Region**: ap-northeast-1 (도쿄)
- **Project ID**: zwkjedumfuhodckmtxxn / **URL**: https://zwkjedumfuhodckmtxxn.supabase.co

### 주요 테이블

| 테이블 | 설명 |
|---|---|
| news_feed | 뉴스 기사 본문·요약·긴급도 (15일치 유지). locked=true면 자동 삭제 제외 + AI 자문 상시 참조. importance/urgency=크롤러 분류값(내부값: 긴급/보통/참고), 대시보드에서 수동 수정 가능 |
| deleted_news | 대시보드에서 삭제한 기사의 url·title 블록리스트 — 크롤러 재수집 방지. 영구 보존 |
| importance_feedback | 긴급도 수동 수정 내역 (news_id당 1행, ai_importance=최초 AI 판정, user_importance=담당자 수정) — 분류 학습 데이터. 영구 보존 |
| feedback_rules | 피드백 증류 규칙 캐시 (단일 행 id=1) — 피드백 20건↑ 시 Haiku가 일반화 규칙 생성, 10건 추가마다 재증류 |
| daily_briefings | 일일 브리핑 원문 — 긴급 기사 "⚠️ SKT 영향 분석:" 줄 포함. 긴급도 수정 시 당일 브리핑 🔴 자동 동기화 |
| law_amendments | 법령·고시·입법예고 변경 모니터링. law_type: law(법률)/bylaw(시행령)/rules(시행규칙)/admrul(고시)/lsAnc(입법예고). law_crawler.py(법령·고시) + gov_notice_crawler.py(입법예고 lsAnc). opinion.lawmaking.go.kr 수집 항목은 law_id가 `lsAnc_op_{md5}` 형식. law_type은 text(제약 없음) |
| assembly_bills | 국회 법안 (assembly_crawler.py). bill_id(UNIQUE), 법안명, 단계, 소관위, 제안일, 링크 |
| document_chunks | 법령·고시·보도자료 RAG 청크 (2026-06-12 중복 1,565청크 정리 완료) — embedding(vector 1024, HNSW), article_no는 "45조의2(준공검사의 면제 등)" 형식(조항번호+제목, 줄 시작 조문 헤더 기준). file_path: 추가지식 업로드 원본 파일 Storage 경로(uploads 버킷, 2026-06-15) — 있으면 저장된 목록에서 클릭 다운로드 |
| custom_knowledge | 팀 추가 지식 (수동 입력) — AI 자문 키워드 매칭 참조. 법령 해석 정정 항목 포함 |
| chat_logs | AI 자문 이력 — 대시보드에서 항목 삭제 가능 |

### Edge Function · RPC

| 이름 | 역할 |
|---|---|
| voyage-embed (Edge) | 질의 임베딩 생성 (voyage-4-lite). VOYAGE_API_KEY는 Supabase Secrets — 브라우저 노출 금지 |
| list_kb_documents (RPC) | 지식 베이스 문서 목록 (doc_name 기준 그룹핑, 보도자료 제외, 청크·임베딩 수) — 국내 법령·고시 탭 |
| search_chunks_trgm / match_chunks_semantic (RPC) | trgm 유사도 / pgvector 시맨틱 검색 |

### Storage

| 버킷 | 역할 |
|---|---|
| uploads (private) | 추가지식 업로드 원본 파일 보관 (2026-06-15). 경로 `custom/{ts}_{ascii파일명}.{ext}`. anon 역할 insert/select/delete 정책. 저장된 목록에서 파일명 클릭 시 createSignedUrl(60초)로 다운로드. document_chunks.file_path에 경로 저장 |

### pg_cron 스케줄 잡 (DB 내부 스케줄러 — GitHub cron과 별개)

DB에서 직접 도는 pg_cron 잡. `select * from cron.job`로 조회. 스케줄은 **UTC 기준**(KST = UTC+9).

| jobid | jobname | schedule(UTC) | KST | 역할 |
|---|---|---|---|---|
| 1 | briefing-health-check | `0 1 * * *` | 10:00 | 브리핑 상태 점검 (기존 잡) |
| 2 | news-feed-cleanup | `0 15 * * *` | 00:00 | 뉴스 정리 (기존 잡) |
| 9 | crawl-trigger-hourly | `47 * * * *` | 매시 :47 (24h) | **뉴스 크롤러 트리거** — daily_crawl.yml dispatch (2026-06-17) |
| 10 | assembly-crawl-trigger | `30 1 * * *` | 10:30 | **국회 법안 크롤러 트리거** — assembly_crawl.yml dispatch (2026-06-17) |
| 11 | law-crawl-trigger | `30 2 * * *` | 11:30 | **법령·입법예고 크롤러 트리거** — law_crawl.yml dispatch (2026-06-17) |
| 8 | briefing-trigger-0605 | `5 21 * * *` | 06:05 | **모닝 브리핑 자동 트리거** — 오늘자 없으면 dispatch (GitHub 06:00 직후 오프셋) (2026-06-17) |
| 7 | briefing-trigger-0620 | `20 21 * * *` | 06:20 | 위 백업 재시도(여전히 없으면 dispatch) (2026-06-17) |
| 12 | news-health-check | `0 12 * * *` | 21:00 | **무음 실패 알람(내부)** — `check_news_health()`, 뉴스 14h+ 멈춤 시 텔레그램 (2026-06-17) |
| 13 | watchdog-trigger | `35 12 * * *` | 21:35 | 외부 워치독(`health_watchdog.yml`) 백업 dispatch — GitHub cron :30 드롭 대비 (2026-06-17) |

- **공용 디스패치 함수 `dispatch_github_workflow(p_workflow)`**: Vault `github_pat`으로 임의 워크플로우를 pg_net dispatch. 아래 트리거 잡들이 공통으로 사용.
- **crawl-trigger-hourly (jobid 9)**: 뉴스 크롤 GitHub 스케줄(예전 :17/:47 낮+밤)이 매일 드롭되던 문제 보완책. **매시 :47에 24시간** `daily_crawl.yml`을 dispatch — Supabase가 안정적 주 트리거. GitHub cron은 `17 * * * *`(매시 :17) 백업으로 남김(둘 다 떠도 크롤러가 `deleted_news`·중복 스킵으로 중복 저장 없음).
- **assembly-crawl-trigger (jobid 10) / law-crawl-trigger (jobid 11)**: 국회·법령 모니터링 GitHub 정시(UTC 01:00/02:00 = KST 10:00/11:00)도 같은 드롭 구간이라 누락되던 문제 보완. GitHub 정시 30분 뒤 **KST 10:30 / 11:30**에 Supabase가 백업 dispatch(하루 1회). 두 크롤러는 upsert + 변경시에만 알림이라 GitHub와 겹쳐 돌아도 중복 알림·저장 없음.
- **공통 인증**: GitHub fine-grained PAT(repo: radio-policy-ai, Actions: Read+Write)를 **Supabase Vault `github_pat`**에 저장 → 함수가 `vault.decrypted_secrets`에서 참조(노출 없음). 의존 확장: pg_cron, pg_net, supabase_vault.
  - ⚠️ PAT 만료/회수 시 모든 트리거가 조용히 멈춤 → Vault `github_pat` 갱신. 잡 조회 `select * from cron.job`, 삭제 `select cron.unschedule('잡이름')`.
- **briefing-trigger-0605 / briefing-trigger-0620 (jobid 8·7)**: 모닝 브리핑 06:00/06:30 KST GitHub 스케줄이 매일 드롭(심하면 수십 시간 지연)돼 브리핑이 늦게/엉뚱한 시각에/수동 생성되던 문제 보완책. 함수 `trigger_briefing_if_missing()`가 오늘자(KST) `daily_briefings` 행이 없으면 `morning_briefing.yml`을 pg_net으로 dispatch. **06:00이 아니라 06:05에 조건부로 트리거하는 이유**: 06:00 정각에 Supabase와 GitHub cron이 동시에 쏘면 둘 다 행 생성 전이라 GitHub 성공/드롭 구분이 안 되고 중복 run이 돔. 06:05 오프셋이면 GitHub 06:00 run이 살아있을 때 그 사이 행이 생겨 Supabase는 건너뜀(중복 run 없음 + "GitHub 정상" 신호), 드롭됐을 때만 Supabase가 발송(~06:07)하고 그게 곧 "GitHub 드롭" 신호가 됨. 발송은 사실상 정시(≤06:07). GitHub cron도 그대로 두며 `already_sent_today`가 이중 발송 차단(드물게 GitHub 지연으로 겹쳐도 1회 발송). 같은 Vault `github_pat` 사용. 기존 `briefing-health-check`(10:00, 경고 전용)는 그대로 유지.

## 무음 실패 감시 (watchdog — 2026-06-17)

파이프라인이 **에러 없이 조용히 멈추는 것**(GitHub 드롭·Supabase 다운·PAT 회수·크롤러 크래시)을 잡는 이중 안전망. 정상이면 무음, 이상 시에만 텔레그램(chat 344506450) 경고. 토큰은 Vault `telegram_bot_token`에서 읽음(하드코딩 없음).

- **내부 워치독 — `check_news_health()` (pg_cron jobid 12, KST 21:00)**: Supabase 안에서 `news_feed` 최신 입력을 확인 → 14시간 넘게 멈췄으면 텔레그램. 직접 DB 쿼리라 가볍고 확실. (브리핑은 `briefing-health-check` 10:00이 담당.)
- **외부 워치독 — `health_watchdog.py` + `.github/workflows/health_watchdog.yml` (KST 21:30 GitHub cron + jobid 13이 21:35 백업 dispatch)**: GitHub Actions에서 도므로 **Supabase와 독립**. 점검 항목:
  - Supabase REST로 뉴스 신선도·오늘자 브리핑 존재 (접속 실패 시 "Supabase 접속 불가" 경고 → 전체 다운 감지)
  - GitHub Actions API로 각 워크플로우(daily_crawl·morning_briefing·law_crawl·assembly_crawl)의 **마지막 성공 실행** 확인 → 데이터 변동이 드문 법령·국회도 "돌았는지" 정확히 판정(heartbeat 대용). 임계: daily_crawl 14h, 나머지 26h.
  - 인증: GitHub Secrets의 SUPABASE_URL/SERVICE_KEY·TELEGRAM_BOT_TOKEN/CHAT_ID + Actions 자동 `GITHUB_TOKEN`(actions:read). 새 시크릿 불필요. stdlib만 사용(pip 불필요).
- **사각지대 상호 보완**: 내부(Supabase)·외부(GitHub)가 서로 독립이라, 한쪽 인프라가 죽어도 다른 쪽이 감지. (단 GitHub·Supabase가 동시에 죽으면 둘 다 못 돎 — 그 경우만 사각.)
- ⚠️ 텔레그램 토큰은 Vault `telegram_bot_token` 한 곳에서 관리. 회수·교체 시 Vault만 갱신하면 양쪽 워치독에 반영(기존 `check_briefing_health`만 아직 토큰 하드코딩 — 추후 Vault로 이관 권장).

## RAG 3중 하이브리드 검색

```
질문 → ① expandQueryKeywords(): Haiku 동의어·법령 용어 확장 (실패 시 기본 키워드 폴백)
     → ② 키워드 ilike + search_chunks_trgm → ③ voyage-embed → match_chunks_semantic
     → 하이브리드 점수 랭킹 → 상위 청크 투입
답변 인용: buildRagContext()가 조항(번호+제목)·고시번호·시행일 표시
응답 수신: callClaude가 Anthropic API를 stream:true(SSE)로 호출 — 토큰 실시간 수신·표시
  (웹검색+긴 답변이 2분 넘겨도 연결이 idle로 끊기지 않음. 비스트리밍 복귀 시 "Failed to fetch" 재발)

임베딩 백필: 신규 업로드 후 PC에서 python backfill_embeddings.py (NULL 청크만, 수십 초)
  - 백필 전 문서는 법령 목록에 "임베딩 대기" 배지 표시 (키워드·trgm으로는 즉시 검색됨)

인용 정확성 장치 (2026-06-12):
  - article_no에 조문 제목 포함 → 조문 성격 즉시 인지
  - system_prompt.js "위임 관계·제도 구분 검증" 규칙 + 핵심 조문 직접 참조
    (전파법 제24조② 무선국 자기적합확인 — 2026.10.22 시행, 시행령 위임 미반영 주의 포함)
```

## 뉴스 본문 수집 (fetch_article_body)

```
crawler.py의 fetch_article_body가 기사·고시 URL에서 본문·발행일을 추출.
  refetch_content.py(매시간)·gov_notice_crawler.py(17:00)가 로컬에서 호출 — 한국 IP 필수.
  GitHub Actions 크롤러는 본문 수집 스킵(저장만).

추출 우선순위:
  ① 정부 게시판(rra.go.kr 등): trafilatura 우선 (include_tables=True)
     — 본문이 table 구조라 일반 'article' 셀렉터가 페이지 전체 네비게이션을 오탐하던 문제 회피.
  ② naver_selectors → 소스별 selectors_map → 공통 셀렉터
     — 소스 라벨이 '국립전파연구원 공지사항'처럼 접미사를 가져도 부분 매칭으로 셀렉터 적용.
  ③ trafilatura 폴백 (셀렉터 미매칭 시)

SSL 약점 사이트 우회 (_http_get):
  - DH_KEY_TOO_SMALL 발생 시 SECLEVEL=1 어댑터(_WeakDHAdapter)로 도메인 무관 자동 재시도.
  - rra.go.kr는 _KNOWN_WEAK_DH 등록 → 처음부터 어댑터 사용 + EUC-KR 인코딩 강제.
  ※ 403 Forbidden(봇 차단)·SSLV3_ALERT·CERTIFICATE_VERIFY_FAILED는 별개 원인 — 위 우회 대상 아님.

trafilatura는 본문 수집의 필수 로컬 의존성 (아래 '알려진 제약사항' 참조).
```

## 입법예고 수집 (gov_notice_crawler.py · crawl_opinion_lawmaking)

```
국민참여입법센터(opinion.lawmaking.go.kr) (부처)입법예고 목록을 수집해 law_amendments(lsAnc)에 저장.
  Windows 작업 스케줄러 17:00 로컬 실행 — 한국 IP 필수 (해외 IP 차단 아님이 확인됐으나 안정성 위해 로컬 유지).
  ※ 입법예고(lsAnc)는 law.go.kr DRF 미지원 → 이 크롤러가 단독 담당.

수집 방식 (2026-06-16 변경 — 기존 lsNm 제명 키워드 검색에서 전환):
  엔드포인트: /gcom/ogLmPp?isOgYn=Y&opYn=Y&pageIndex=N
  ① 진행 중 입법예고 전체 목록을 pageIndex 단위로 끝까지 스캔(빈 페이지면 종료, 상한 OPINION_MAX_PAGES=20).
  ② 각 건을 _opinion_match()로 전파·통신 관련만 선별:
     - 직제·소속기관·정원·청사가 제명에 있으면 우선 제외 (조직 개편).
     - 제명 앞 "○○부/처/청/위원회 소관" 접두사 제거 후 키워드 판정
       (소관 부처명 '과학기술정보통신부'의 '정보통신' 글자가 무관 법령을 오탐하던 문제 차단).
     - 제명 키워드: 전파·주파수·전기통신·방송통신·무선·전자파·적합성평가·정보통신·이동통신·기간통신·위성·단말장치·기지국·스펙트럼
     - 소관부처 보강: 방송미디어통신위·방송통신위 소관은 제명 키워드 없어도 포함 / 과기정통부는 통신계열 힌트(통신·방송·전파·무선·주파수·전자파·단말·기지국·네트워크·인터넷·클라우드·데이터센터·스펙트럼)가 제명에 있을 때만.
  ③ 신규 건 → law_amendments(lsAnc_op_{md5}) insert + 텔레그램(건별)·이메일(Resend 묶음) 즉시 발송.
     첫 실행(lsAnc 0건)은 알림 폭주 방지로 베이스라인만 저장(알림 생략) — law_crawler와 동일 관례.

배경: 기존 lsNm(제명) 검색은 "법령 제명에 키워드가 그대로 든 경우"만 잡혀
  "방송법 시행령 일부개정"(방송미디어통신위) 같은 관련 예고를 통째로 놓쳤고,
  마침 제명 일치 건이 없으면 0건이 돼 lsAnc가 장기간 비어 있었음 → 전체목록 스캔 + 소관부처 보강으로 보완.

요약(주요 내용) 자동 생성 (2026-06-16):
  수집 끝에 backfill_opinion_summaries()가 summary가 비어 있는 lsAnc 행을 채움.
    _fetch_opinion_reason(): 상세 페이지(opinion.lawmaking.go.kr/gcom/ogLmPp/{id})에서
      "개정이유 + 주요내용" 추출(의견제출 직전까지). 호출 실패→None(재시도), 본문 마커 없음→''(재시도 방지).
    _summarize_opinion(): Haiku(claude-haiku-4-5)로 1~2문장(100자) 요약 → law_amendments.summary 저장.
  멱등(summary NULL만 처리, 실패 시 NULL 유지). ANTHROPIC_API_KEY 필요(.env). law_crawler 요약(summarize_law_amendments.py)과 동일 방식.
  ※ law.go.kr DRF는 입법예고 미지원이라 summarize_law_amendments.py가 lsAnc를 건너뜀 → 이 크롤러가 요약까지 단독 담당.
  대시보드 입법예고 카드(law_amendments.summary)·모닝 브리핑 📢 섹션이 이 summary를 표시.
```

## 뉴스 중요도·잠금·삭제 (대시보드)

```
중요도 표시: 화면 라벨은 "🔴 중요/🟡 보통/🟢 참고" — 내부값·DB·크롤러·알림은 '긴급/보통/참고' 유지
  ※ 라벨만 변경된 것이므로 코드·SQL에서는 항상 '긴급' 값 사용

중요도 수정: 상세 패널 배지 아래 [중요][보통][참고] 버튼 (별도 행)
  - news_feed 즉시 갱신(성공 검증, 실패 시 알림) + importance_feedback 기록
  - 당일 브리핑에 포함된 기사면 브리핑 원문 🔴도 자동 동기화 (syncBriefingUrgency)
  - 크롤러가 다음 실행부터 학습: ① 증류 규칙(20건↑) ② 기사별 유사 사례 ③ 등급 균형 사례
  ⚠️ 영향도 분석(SKT 영향도)이 긴급도를 자동 덮어쓰던 코드는 제거됨 —
     긴급도 단일 기준 = 크롤러 분류 + 담당자 수정. 재도입 금지

잠금: 자물쇠 아이콘 — locked=true면 15일 삭제 제외 + AI 자문 상시 참조
삭제: 휴지통 아이콘/모달 버튼 — news_feed 영구 삭제 + deleted_news 기록(재수집 방지)
자문 이력 삭제: 이력 목록·상세에서 chat_logs 영구 삭제

뉴스 그룹핑: 같은 날짜 + 제목 공유 키워드 2개 이상일 때만 묶음
  ('기지국' 같은 단일 흔한 단어로 이질 주제가 병합되던 버그 수정, 지명 정규화에 광장 포함)
```

## 시스템 구조 — 전체 흐름

### ① GitHub Actions 크롤러 (매시간, 자동 · PC 불필요)

```
스케줄 (2026-06-17 개편 — GitHub cron 상습 드롭 → Supabase 주 트리거로 전환):
  Supabase pg_cron(crawl-trigger-hourly, jobid 9): 매시 :47 (24h) — 안정적 주 트리거, daily_crawl.yml dispatch
  GitHub cron `17 * * * *`: 매시 :17 (24h) — 무료 백업
실행: crawler.py (daily_crawl.yml). daily_crawl은 이제 크롤 전용 — 08:05 모닝 브리핑 백업 스텝은 제거됨(Supabase briefing-trigger 06:05/06:20이 대체).
※ GitHub 예약(cron)은 best-effort라 지연·드롭이 잦아(심하면 수십 시간 지연) Supabase pg_cron이 안정적 주 트리거를 맡고 GitHub는 백업으로만 둠. 둘 다 떠도 크롤러가 `deleted_news`·중복 스킵으로 중복 저장 안 함.

흐름:
  네이버 검색 OpenAPI(1순위) → 부진 시 Google RSS 폴백 / 20개 언론사 수집
    ※ 네이버는 구 HTML 스크래핑(ul.list_news li.bx)이 검색 구조 변경/해외 IP 차단으로 0건 회귀 →
      공식 검색 OpenAPI(openapi.naver.com/v1/search/news.json, sort=date)로 교체 (2026-06-16).
      NAVER_CLIENT_ID/SECRET 필요(.env·GitHub Secrets). 키 미설정·오류 시 빈 결과 → Google RSS 폴백.
  → deleted_news의 url·title 제외 (삭제 기사 재수집 방지)
  → Haiku 긴급도 분류 (즉시대응→긴급/금주검토→보통/동향파악→참고)
    ※ importance_feedback 학습: 증류 규칙 + 기사별 유사 사례 + 등급 균형 사례 주입
  → 기술 용어 추출 → 즉시 설명·다이어그램 생성
  → 15일 이내 신규 기사만 저장 (Actions에서는 본문 수집 스킵)
긴급 감지 시: 텔레그램 + Resend 이메일 즉시 발송
```

### ② GitHub Actions 법령·고시 모니터링 (매일 11:00 KST, 자동 · PC 불필요)

```
실행: law_crawler.py (law_crawl.yml, timeout-minutes: 25)
엔드포인트: http://www.law.go.kr/DRF/lawSearch.do  (법제처 국가법령정보 DRF Open API)
  OC키: LAW_OC_KEY=radiopolicyai (GitHub Secrets)

흐름:
  키워드 × target 조합 조회
    - target=law   : 현행 법령 (법률·시행령·시행규칙) — 법령구분명으로 유형 판정
    - target=eflaw : 시행예정 법령 (현행연혁코드=시행예정) → 대시보드 "시행 예정" 필터
    - target=admrul: 행정규칙(고시·훈령·예규) — AdmRulSearch.admrul
  → law_amendments upsert (신규: insert + 텔레그램, 개정: 공포일 변경 감지 + 텔레그램)
  → 첫 실행(기존 0건)은 알림 생략, 베이스라인만 저장 (알림 폭주 방지)
  ※ 입법예고(lsAnc)는 law.go.kr DRF 미지원 → gov_notice_crawler.py가 단독 담당
  ※ 응답 필드: 법령명한글·법령일련번호·법령구분명·공포일자·시행일자·공포번호·제개정구분명
              (고시: 행정규칙명·행정규칙일련번호·발령일자·시행일자·발령번호)
```

### ③ GitHub Actions 국회 법안 모니터링 (매일 10:00 KST, 자동 · PC 불필요)

```
실행: assembly_crawler.py (assembly_crawl.yml)
API키: ASSEMBLY_API_KEY (열린국회정보 인증키, GitHub Secrets)
흐름:
  열린국회정보 API → 22대 국회 전파·통신 관련 법안 → assembly_bills upsert
  단계 변경 감지 → 텔레그램 알림
```

### ④ Windows 작업 스케줄러 (PC 켜져 있을 때만, 한국 IP 필요)

```
RadioPolicy-RefetchContent (매시간): 15일 초과 삭제(locked 보존)·본문 재수집·요약 생성·날짜 보정·배치 백필
전파정책_정부크롤러 (17:00): gov_notice_crawler.py
  - RRA·MSIT·KCC 고시 → news_feed
  - 입법예고(opinion.lawmaking.go.kr) → law_amendments (lsAnc_op_{md5})
    진행 중 입법예고 전체 목록을 페이지 단위(pageIndex)로 스캔 후 전파·통신 관련만 매칭:
      ① 제명 키워드(전파·주파수·전기통신·방송통신·무선·전자파·적합성평가·정보통신·이동통신·기간통신·위성·단말장치·기지국·스펙트럼)
      ② 소관부처 보강 — 방송미디어통신위·방송통신위 소관은 제명 키워드 없어도 포함, 과기정통부는 통신계열 힌트가 제명에 있을 때만
      ※ "○○부/처/청/위원회 소관" 접두사 제거 후 키워드 판정(부처명 '정보통신' 오탐 차단), 직제·소속기관·정원·청사는 제외
    신규 감지 시 텔레그램(건별) + 이메일(Resend 묶음) 즉시 발송 (첫 실행 lsAnc 0건이면 베이스라인만 저장, 알림 생략)
RadioPolicy-BriefingBackup (09:40): GitHub Actions 전체 누락 대비 (already_sent_today가 중복 차단)
⚠️ Cowork 예약 태스크는 모두 비활성화 — Windows 스케줄러로 전환 완료
※ 본문 수집(refetch_content.py·gov_notice_crawler.py)은 trafilatura 필수 — PC에 설치돼 있어야 함
```

### ⑤ GitHub Actions 모닝 브리핑 (매일 06:00 KST)

```
cron: 06:00 / 06:30(2차) — morning_briefing.py
  ※ 23~00 UTC(=08~09시 KST)는 GitHub cron 최혼잡 구간이라 드롭 잦음 →
     한산한 21 UTC대(=06시 KST)로 이동 (2026-06-15). 유튜브 요약(04~05시)이 정시에 잘 뜨는 것과 같은 이유.
흐름:
  law_amendments에서 최근 24h 신규 lsAnc 조회 (gov_notice_crawler 수집분)
  최근 24h 본문 확인 기사 → Haiku 브리핑 생성
    ※ 🔴 = 입력 뉴스 목록에서 🔴(news_feed 긴급도)에만 사용, Haiku 자체 판정 금지
  → 신규 입법예고 있으면 브리핑 앞에 📢 섹션 삽입 (🔴 마커 → 이메일 빨간 박스)
    _format_law_anc_section(): law_nm·예고기간·🔗링크 + 주요 내용(law_amendments.summary)을 "  → {요약}" 줄로 표시 (2026-06-16)
    헤더 문구는 "📢 [신규 입법예고] N건 — 확인 필요" ('즉시' 제거, 2026-06-16)
  → add_urgent_analyses(): 긴급 기사 SKT 영향 분석 생성 → "⚠️ SKT 영향 분석:" 줄로 삽입(최대 3건)
  → daily_briefings 저장(분석 포함) + summary 역저장
  → 발송: 이메일(분석 포함) / 텔레그램(4000자 제한 — 분석 줄 제외)
⚠️ Actions cron 지연·누락 잦음 → 최종 안전망은 **Supabase pg_cron briefing-trigger 06:05/06:20**(jobid 8·7, GitHub 드롭 시 morning_briefing.yml 자동 dispatch) + 09:40 로컬 백업
   (중복은 already_sent_today가 차단. 08:05 Actions 백업('5 23' 슬롯)은 2026-06-17 제거 — Supabase 06:05가 대체)
```

### ⑥ 대시보드 (GitHub Pages)

```
URL: https://radio-policy.gitlab.io/
※ app.js/system_prompt.js/index.html 수정 배포 시 index.html 캐시 버스터(?v=) 갱신 필수
   (현재 app.js?v=20260616e)
※ 대시보드(홈) 메뉴는 2026-06-12 제거됨 — 기본 화면은 보도자료·뉴스, 사이드바 맨 아래 설정만
※ 사이드바 메뉴 아이콘은 Tabler Icons webfont (ti ti-*) — 존재하지 않는 아이콘명은 빈칸 렌더
   (예: ti-git-diff 없음 → ti-arrows-diff로 교체, 2026-06-14)

메뉴 (사이드바 순서):
  [모니터링]
  - 보도자료·뉴스: 목록·그룹핑·모달, 중요도 수정/잠금/삭제 (위 섹션 참조)
  - Daily Briefing: 원문 + 저장된 SKT 영향 분석 표시. 긴급 박스 배지는 "중요"
    (액션 문구·제목 🔴 이모지 표시 안 함). 원문 🔴 기준으로만 박스 표시 — 이메일과 항상 일치
    렌더링(parseBriefingContent, 2026-06-16):
      · "오늘" 배지는 KST(+9h) 기준 판정 — UTC로 하면 KST 자정~09시에 어제로 오판하던 버그 수정
      · Haiku가 덧붙이는 마크다운 처리: 줄 앞 #/## 헤더 기호 제거, **굵게**→<strong> 변환(mdBold)
      · 📢 입법예고 블록(•불릿 아님)도 스타일링: 📢=강조 헤더, 🔴=굵은 제목, →=보조텍스트, 🔗=클릭 가능한 "원문 보기" 링크
        (이전엔 일반 텍스트라 #/##/** 기호 노출 + 🔗 생 URL이 클릭 안 됨)
      · "전파정책 모닝 브리핑" 제목 위 여백·구분선으로 입법예고 블록과 분리
  - 기술 용어: 자동 수집 위키

  [자문]
  - AI 자문: 3중 하이브리드 RAG + 뉴스(60일+locked) 기반 (claude-sonnet-4-6)
    응답은 SSE 스트리밍 수신(callClaude stream:true) — 웹검색+긴 답변이 2분 넘겨도 연결이 끊기지 않고
    답변이 실시간 표시됨. (2026-06-15, 비스트리밍 시 ~120초에 "Failed to fetch" 나던 문제 해결)
    자주 묻는 질문 칩: 실제 자문 이력 기반 8개 (등록면허세·준공검사 면제·자기적합확인 등)

  [법안 동향 모니터링]
  - 국회 법안: assembly_bills DB, 단계별 필터(전체/접수/소관위 심사/법사위 심사/본회의/통과·공포)
  - 행정부 입법예고·법령 개정: law_amendments 타임라인 카드
    필터: 입법예고 중(lsAnc) / 시행 예정(enf_dt≥오늘) / 신규·개정(30일) / 전체
  - 법령 DIFF 분석: PDF 추출 시 hasEOL 줄바꿈 보존 + 조문 헤더 앞 줄바꿈 보강 (2026-06-12 수정)
    조문 짝매칭·단어 하이라이트·AI 분석

  [지식 베이스]
  - 국내 법령·고시: DB 실시간 목록 (list_kb_documents RPC) — 계열별 그룹 카드, 법령번호·시행일
    자동 파싱, 임베딩 대기 배지. 날짜 파일명(보도자료)·ITU-R은 제외. 정적 목록 폐지
  - ITU-R 문서 / 정부 보도자료 / 추가 지식 입력 / 설정
  - 파일 업로드(브라우저 파싱, 2026-06-15): 법령·고시 / ITU-R / 정부 보도자료 / 추가 지식 입력 탭의
    "업로드" 버튼 → PDF(텍스트 기반만, 스캔본 불가)·MD·Word(docx)·PPTX를 브라우저에서 추출
    (pdf.js · mammoth · JSZip) → document_chunks 저장.
    카테고리: 법령·고시=선택값 / ITU-R='ITU-R' / 보도자료='보도자료' / 추가 지식 입력='추가지식'.
    ※ 추가 지식 입력 탭의 "파일 업로드"는 document_chunks(RAG)로 감 — 텍스트 폼 저장(custom_knowledge)과 별개 경로.
    ※ 추가 지식 입력 탭의 "저장된 목록"은 업로드 파일도 함께 표시 (2026-06-15):
      document_chunks(doc_category='추가지식')를 doc_name 기준으로 묶어
      "📎 파일" 배지 + 청크 수 + 임베딩 상태 배지(임베딩 대기/완료) + 삭제 버튼으로 노출.
      텍스트 지식(custom_knowledge)은 수정·삭제, 파일은 삭제만(수정 불가). created_at 최신순 병합 정렬.
      (loadCustomFileList + renderCustomKnowledgeList 병합, onDeleteCustomFile은 doc_name 기준 청크 일괄 삭제 + Storage 객체 삭제)
    ※ 원본 파일 클릭 다운로드 (2026-06-15): 추가지식 업로드 시 원본 파일을 Storage(uploads 버킷)에 보관하고
      file_path를 청크에 기록 → 저장된 목록에서 파일명(📎)에 ⬇ 아이콘이 붙고 클릭 시 createSignedUrl(60초)로 다운로드.
      ※ document_chunks엔 추출 텍스트만 저장되므로 Storage 보관 이전(2026-06-15 이전) 업로드분은 원본이 없어 다운로드 불가(파일명 비링크).
      ※ 다운로드 파일명은 Storage 키(ASCII)와 별개로 createSignedUrl download 옵션으로 원래 이름 지정. 비ASCII 파일명은 키에서 제거되고 ts 접두사로 유일화.
    ※ 업로드 후 PC에서 backfill_embeddings.py 실행해야 시맨틱 검색 적용(그 전엔 키워드·trgm만, "임베딩 대기" 배지).
```

### 알림 채널

```
매일 06:00 KST     | 텔레그램(분석 제외)·이메일(분석 포함) | you.jinwoong@gmail.com / TG 344506450
긴급 기사 즉시     | 텔레그램·이메일                        | 동일
신규 입법예고 즉시 | 텔레그램(건별)·이메일(Resend 묶음)     | 동일 (gov_notice_crawler.py 17:00 실행 시)
법령·고시 신규/개정| 텔레그램                               | law_crawler.py (첫 실행 베이스라인은 알림 생략)
국회 법안 단계변경 | 텔레그램                               | assembly_crawler.py
```

## 표준 작업 패턴

```bash
# 본문 수집 의존성 (PC 최초 1회 / PC 교체·파이썬 재설치 시): pip install trafilatura

# 코드 수정 후 배포 (app.js/index.html/system_prompt.js 수정 시 캐시 버스터 갱신 필수)
# ⚠️ 커밋 전 git diff --stat HEAD로 의도한 파일만 변경됐는지 확인.
#    의도하지 않은 파일이 변경으로 보이면 stale 마운트 신호 — 절대 add하지 말 것.
#    git add는 항상 파일명 지정 (git add -A / git add . 금지)
git add [파일명] && git commit -m "설명" && git push origin main
# 푸시 직후 원격 검증: git show HEAD:index.html | findstr "app.js?v="
#    (캐시 버스터가 직전보다 후퇴했으면 다른 세션의 stale 커밋이 덮은 것 — 즉시 복구)

# git lock 오류
del .git\HEAD.lock
del .git\index.lock                       ← "Another git process / index.lock File exists" 오류 시 (스테일 락이면 삭제 후 재시도)
del .git\refs\remotes\origin\main.lock    ← push 후 로컬 ref 오류 시

# git index 손상(bad signature 0x00000000) — Cowork 샌드박스에서 발생
rm -f .git/index .git/index.lock
GIT_INDEX_FILE=/tmp/gidx git read-tree HEAD && GIT_INDEX_FILE=/tmp/gidx git add [파일] \
  && GIT_INDEX_FILE=/tmp/gidx git commit -m "..." && git push origin main
# ⚠️ Cowork 샌드박스 마운트가 git lock 파일 생성·삭제를 차단하면(.lock Operation not permitted)
#    커밋이 되기도 하나(경고만 출력) 안 될 수도 있음 — 푸시 후 'git show HEAD'로 원격 반영 검증.
#    반영 안 됐으면 파일만 패치 후 PC 터미널에서 커밋·푸시할 것

# 샌드박스 마운트 절단 주의 — 커밋 전 줄수·파일 끝(node --check / ast.parse) 검증 필수.
#   절단 시(working 파일이 HEAD보다 짧음) HEAD 완전본에서 패치 후 마운트에 다시 쓸 것.
#   ※ Cowork 세션에서 bash 마운트가 stale/절단된 채 보일 수 있음(예: 2026-06-15·16 gov_notice_crawler.py·app.js를
#     HEAD보다 짧게 표시) — 이때는 샌드박스에서 커밋 금지. 파일은 Edit로 실제 디스크에 반영됐으므로
#     PC 터미널에서 커밋·푸시할 것. (단, 변경 대상 파일이 절단되지 않았고 HEAD가 origin과
#     동기라면, 해당 파일만 명시적으로 add해 커밋·푸시하는 것은 안전 — 푸시 후 git diff --stat로
#     해당 파일만 바뀐 것 원격 검증. 2026-06-15 cron 분 변경은 이 방식으로 안전 처리)
#   ※ 마운트 절단 시 HEAD 블롭은 신뢰 가능(git show HEAD:파일) — working(실제 디스크)은 Read 도구로 확인 후 대조.

# 크롤러 수동 실행·테스트
python crawler.py              # 뉴스 (네이버 OpenAPI+Google RSS). "[네이버 뉴스] N건 수집" N>0 확인. NAVER_CLIENT_ID/SECRET 필요(미설정 시 폴백)
python law_crawler.py          # 법령·고시 (LAW_OC_KEY 필요)
python assembly_crawler.py     # 국회 법안 (ASSEMBLY_API_KEY 필요)
python gov_notice_crawler.py   # 정부 고시·입법예고 (한국 IP). 입법예고는 "[입법예고] N페이지: M행 스캔, 누적 매칭 K건" 로그로 진단
python refetch_content.py      # 본문 재수집·정리 (한국 IP, trafilatura)
python resend_briefing.py [2026-06-07]   # 브리핑 재발송
python upload_law_pdf.py 파일.pdf "문서명" 고시   # 법령/고시/ITU-R 업로드
python backfill_embeddings.py  # 임베딩 백필
```

## 브리핑 미수신 시 체크리스트

1. Actions 확인: …/actions/workflows/morning_briefing.yml → 실패 시 "Run workflow" 수동 실행
2. 로그에서 `[텔레그램]`, `[Resend]` 라인 확인
3. 성공했는데 미수신 → `python resend_briefing.py`
4. 09:40 이후에도 미수신 → `briefing_backup_log.txt` 확인
※ 06:00/06:30 예약이 둘 다 드롭됐고 PC도 09:40 전에 안 켜졌으면 그날은 미발송 → "Run workflow" 수동 실행이 가장 빠름

## 크롤링(뉴스 미축적) 점검 체크리스트

1. Actions 확인: …/actions/workflows/daily_crawl.yml → 실행 자체가 드문지(스케줄 드롭) / 실패(빨강)인지 구분
2. 실행은 초록인데 뉴스가 안 쌓이면 → 로그의 "[네이버 뉴스] N건 수집" 확인.
   N=0이면 NAVER_CLIENT_ID/SECRET 누락·만료 또는 폴백만 도는 상태(구 HTML 스크래핑 회귀 사고 패턴, 2026-06-16). Google RSS만으론 신규가 거의 안 쌓일 수 있음
   N>0인데도 신규 0이면 → GitHub cron 드롭 가능성. "Run workflow" 수동 실행해 누락분 보충
3. 실행이 빨강(실패)이면 → 로그 확인 + crawler.py 문법(py_compile) 점검
4. DB 최신 입력 시각 확인: news_feed의 created_at(KST) 최댓값
※ cron은 :17/:47 이중화돼 있으나 GitHub best-effort 특성상 간헐 지연·드롭은 여전히 발생 가능.
  특히 UTC 00시 부근(=KST 낮 09~12시) 슬롯이 블록 단위로 통째 드롭될 수 있음(2026-06-15 발생) —
  이때는 분 튜닝으로 못 막으니 "Run workflow" 수동 실행 또는 PC 로컬 보완이 정답

## 입법예고 미수집 점검 체크리스트

1. DB 확인이 가장 확실: `law_amendments`에서 `law_type='lsAnc'`(또는 `law_id LIKE 'lsAnc_op_%'`)의 건수·`MAX(created_at)`
   — 대시보드 "입법예고 중" 카운트는 의견제출 기한 살아있는 건만 세므로 0이어도 수집 중단인지 진행 중 건이 없는지 구분 불가
2. PC에서 `python gov_notice_crawler.py` 실행 → `[입법예고] N페이지: M행 스캔, 누적 매칭 K건` 로그 확인
   - 전 페이지가 0행이면 → 사이트 접속·파싱(셀렉터 `table tbody tr`) 문제
   - M행(>0)인데 누적 매칭 0이면 → 현재 진행 중 전파·통신 입법예고가 없거나 매칭 기준이 좁은 것 (정상일 수 있음)
3. PC 의존(17:00 스케줄러). PC 꺼져 있으면 그날 미수집 — law.go.kr DRF 미지원이라 GitHub Actions로 대체 불가
※ 키워드 없이 전체 목록(`?isOgYn=Y&opYn=Y`)을 받아 "전체 N건"이 정상 파싱되는지 보는 게 사이트 정상 여부 판별의 빠른 방법

## AI 자문 "Failed to fetch" 점검 체크리스트

1. 화면의 "Failed to fetch"는 대시보드 메시지가 아니라 브라우저가 fetch 연결에 실패했을 때 내는 네이티브 오류
2. 키 누락이면 "Claude API 키가 설정되지 않았습니다", 서버 오류면 "API 오류 (HTTP xxx)"로 표시됨 — 둘 다 아니면 연결 단계 실패
3. 가장 흔한 원인: 무거운 질문(웹검색+긴 답변)이 2분 넘어가며 연결이 idle로 끊김 → callClaude의 stream:true(SSE)로 해결됨
4. 그래도 나면: ① 사내망/프록시·방화벽이 api.anthropic.com 차단 여부(핫스팟 등 다른 망에서 비교) ② 확장프로그램/백신 차단 ③ F12 네트워크 탭에서 해당 요청 상태 확인
※ API 키 자체 유효성은 임의 키로 호출 시 401(인증오류)이 나오면 서버 도달은 정상이라는 의미

## 하지 말아야 할 것

- **API 키 하드코딩 금지 (공개 repo!)** — .env·GitHub Secrets·Supabase Secrets에만. 2026-06-12 Voyage 키 유출·재발급 사례
- **gov_notice_crawler.py를 GitHub Actions로 옮기지 말 것** — 정부 사이트 해외 IP 차단 위험 + 입법예고는 한국 IP 안정성 위해 로컬 유지
- **입법예고 수집을 lsNm(제명) 키워드 검색으로 되돌리지 말 것** — 제명에 키워드가 그대로 든 경우만 잡혀 "방송법 시행령"(방송미디어통신위) 같은 관련 예고를 통째로 놓침. 진행 중 전체목록 스캔(pageIndex) + 소관부처 보강이 정답 (2026-06-16)
- **입법예고 매칭의 "○○부/처/청/위원회 소관" 접두사 제거를 빼지 말 것** — 소관 부처명(과학기술정보'통신'부)의 '정보통신' 글자가 제명에 섞여 비상대비법 등 무관 예고를 오탐하던 문제 해결책. 직제·소속기관·정원·청사 우선 제외와 함께 유지 (2026-06-16)
- **입법예고 요약 생성(backfill_opinion_summaries)·morning_briefing의 summary 표시를 제거하지 말 것** — lsAnc는 DRF 미지원이라 summarize_law_amendments가 건너뜀 → gov_notice_crawler가 요약까지 단독 담당. 대시보드 카드·브리핑 📢 섹션의 주요 내용 근거 (2026-06-16)
- **Daily Briefing "오늘" 배지를 UTC(`new Date().toISOString()`)로 되돌리지 말 것** — KST 자정~09시에 어제로 오판. KST(+9h) 기준 유지 (2026-06-16)
- **parseBriefingContent의 마크다운 처리(#/## 제거·mdBold)·📢 입법예고 블록 스타일링·🔗 링크화를 제거하지 말 것** — Haiku가 가끔 #/##/** 마크다운을 덧붙여 기호가 노출되고 입법예고 🔗가 생 URL로 클릭 안 되던 문제 해결책 (2026-06-16)
- **crawl_naver_news를 네이버 HTML 스크래핑(search.naver.com, ul.list_news li.bx/a.news_tit)으로 되돌리지 말 것** — 검색 구조 변경/해외 IP 차단으로 0건 회귀(에러 없이) → 며칠간 뉴스 미축적 사고. 공식 검색 OpenAPI(openapi.naver.com)가 정답 (2026-06-16). 키 없으면 Google RSS 폴백
- **Supabase 신규 프로젝트 생성 제안 금지** — 무료 슬롯 2개 모두 사용 중
- **Sonnet으로 긴급도 분류 업그레이드 제안 금지** — Haiku + 피드백 학습으로 충분
- **Cowork 예약 태스크로 크롤러 재등록 금지** — 중복 실행 위험
- **news_feed 수동 정리 시 locked=true 제외 필수** (`AND locked = false`)
- **deleted_news·importance_feedback·feedback_rules 비우지 말 것** — 재수집 방지·학습용 영구 데이터
- **브리핑 Haiku에게 긴급(🔴) 판정을 다시 맡기지 말 것** — 🔴는 news_feed 긴급도가 단일 기준
- **영향도 분석이 긴급도를 덮어쓰게 하지 말 것** — 담당자 수정을 AI가 되돌리던 버그의 원인 (2026-06-12 제거)
- **같은 법령·고시의 구버전을 지식 베이스에 남기지 말 것** — 구버전 조문 인용 위험. 최신판 업로드 시 구버전 삭제
- **여러 세션이 같은 repo에 동시에 커밋하지 말 것** — 샌드박스 마운트가 stale하면 다른 세션 작업을 통째로 되돌려 푸시할 수 있음 (2026-06-12 f37fd0b 사고). repo 커밋은 한 번에 한 세션만
- **pg_cron 트리거 잡(crawl-trigger-hourly·law-crawl-trigger·assembly-crawl-trigger·briefing-trigger-0605/0620)·함수 `dispatch_github_workflow`·`trigger_briefing_if_missing`·Vault `github_pat`을 지우지 말 것** — GitHub cron 상습 드롭으로 크롤·법령·국회·브리핑이 며칠째 누락/지연되던 문제의 핵심 보완책(Supabase가 주 트리거). 삭제 시 해당 수집이 GitHub 드롭에 다시 노출됨 (2026-06-17)
- **같은 문서를 다른 카테고리로 중복 업로드하지 말 것** — 목록은 doc_name 기준 1행이지만 청크는 중복 저장되어 검색 노이즈 발생
- **fetch_article_body의 rra.go.kr trafilatura 우선 분기를 제거하지 말 것** — 'article' 셀렉터 네비게이션 오탐 해결책 (2026-06-14)
- **DH_KEY_TOO_SMALL 자동 재시도(_http_get)를 rra.go.kr 전용으로 되돌리지 말 것** — 도메인 무관 우회 (2026-06-14)
- **law_crawler 엔드포인트를 open.law.go.kr/LSO/... 로 되돌리지 말 것** — 정식은 www.law.go.kr/DRF/lawSearch.do (구 주소는 404)
- **법령/국회 키워드에 '혼신' 재추가 금지** — '이혼신고' 부분문자열 오탐 유발 (2026-06-14 제거). 전파간섭은 '전파간섭'으로 유지
- **daily_crawl.yml 크롤 스케줄을 예전 다중 슬롯(`17,47 0-11`+`13,18,22`+`5 23`)으로 되돌리지 말 것** — 2026-06-17 `17 * * * *`(매시 :17 백업) 단일로 단순화하고 Supabase pg_cron(:47)을 주 트리거로 전환함. '5 23' 브리핑 백업 스텝도 함께 제거(Supabase briefing-trigger가 대체)
- **GitHub 크롤 백업 슬롯(:17)을 정시(:00)·15분 단위(:15/:30/:45)로 옮기지 말 것** — 전 세계 cron 혼잡대라 드롭 확률↑. 한산한 :17 유지 (2026-06-15)
- **모닝 브리핑 cron을 23~00 UTC(=08~09시 KST)로 되돌리지 말 것** — GitHub cron 최혼잡 구간이라 드롭 잦음. 06:00/06:30 KST(=21 UTC대)로 이동함 (2026-06-15)
- **추가 지식 입력 탭의 "파일 업로드"를 custom_knowledge로 보내지 말 것** — 파일은 document_chunks(RAG, doc_category='추가지식')로 가야 조문 청킹·시맨틱 검색 적용. 텍스트 폼만 custom_knowledge (2026-06-15)
- **추가 지식 "저장된 목록"의 파일 병합 표시(loadCustomFileList)를 제거하지 말 것** — 업로드 파일은 custom_knowledge가 아니라 document_chunks(추가지식)에 저장돼 목록에 안 떠 "어떤 파일을 올렸는지" 확인이 안 되던 문제 해결책. 파일은 📎 배지·삭제 버튼으로 병합 표시 (2026-06-15)
- **추가지식 업로드의 원본 파일 Storage 보관(uploads 버킷)·file_path 기록을 제거하지 말 것** — 저장된 목록 클릭 다운로드의 근거. file_path 없으면 다운로드 링크가 사라짐 (2026-06-15)
- **uploads 버킷을 public으로 바꾸지 말 것** — private + anon createSignedUrl(60초)로 다운로드. public화 시 경로 아는 누구나 접근 가능
- **대시보드 업로드 모달의 DOCX(mammoth)·드래그앤드롭 다중·전포맷 분기를 제거하지 말 것** — 법령·고시/ITU-R/보도자료/추가 지식 입력 공용 (2026-06-15)
- **AI 자문 callClaude를 비스트리밍 fetch로 되돌리지 말 것** — 웹검색+긴 답변(max_tokens 16384)은 응답이 2분 이상 걸려, 비스트리밍 시 ~120초 idle 구간에 브라우저·사내망 프록시가 연결을 끊어 "Failed to fetch"가 발생함. stream:true SSE 수신(content_block_delta의 text_delta 누적 + citations_delta 인용 수집)으로 해결 — 실측 동일 질문이 비스트리밍 127초에 끊기던 것이 스트리밍에서 135.7초·7,202자까지 완주 (2026-06-15)

## 현재 알려진 제약사항

1. **이메일 수신**: Resend 도메인 미인증 → you.jinwoong@gmail.com만 수신 가능
2. **본문 수집**: PC 꺼져 있으면 RSS 요약만 저장 → refetch_content.py가 보완
3. **Supabase 슬롯**: 무료 2개 모두 사용 중 / **Wine Cellar**: 7일 미접속 시 정지 위험
4. **스포츠 기사 오탐**: EXCLUDE_KEYWORDS(crawler.py 477줄 부근) + 중요도 피드백으로 관리
5. **신규 업로드 문서**: backfill_embeddings.py 전까지 시맨틱 검색 미적용 ("임베딩 대기" 배지)
6. **15일 초과 삭제는 PC 의존** (refetch_content.py 로컬 실행)
7. **2026-06-12 이전 업로드분 청크 경계**: 조문 단위와 어긋날 수 있음 (article_no는 정확). 재업로드 시 해소
8. **무선국 자기적합확인 (전파법 제24조②, 2026.10.22 시행)**: 대상 무선국 시행령 위임 미반영 — 개정 시행령 공포 시 PDF 업로드 필요. custom_knowledge 정정 지식 + system_prompt 핵심 조문에 반영됨
9. **일부 고시는 시행 전 개정본만 보유**: 적합성평가 고시(2025-56호, 2026.11.6 시행), 시험기관·전자파적합성 고시(2025-22호, 2026.7.1 시행) — 현행 시행본 기준 자문 필요 시 해당 버전 재업로드
10. **ITU-R 탭은 정적 목록** (DB 실시간 아님)
11. **입법예고 알림은 PC 의존** — gov_notice_crawler.py는 17:00 Windows 스케줄러 실행. PC 꺼져 있으면 입법예고(lsAnc) 미수집 (law.go.kr DRF는 입법예고 미지원이므로 GitHub Actions law_crawler로는 대체 불가). 수집은 진행 중 입법예고 전체목록 스캔 + 소관부처 보강 방식 (2026-06-16)
12. **trafilatura 로컬 본문 수집 필수 의존성** — 정부 게시판(rra.go.kr 등) 본문이 table 구조라 trafilatura로 추출. PC 교체·파이썬 재설치 시 `pip install trafilatura` 재실행 필요. crawler.py는 미설치 시 셀렉터 폴백(에러 없이 본문 품질만 저하). GitHub Actions는 본문 수집 스킵하므로 영향 없음
13. **일부 사이트는 SSL/봇 차단으로 본문 수집 불가** — 403 Forbidden(investing.com 등), SSLV3_ALERT_HANDSHAKE_FAILURE(kbench.com), CERTIFICATE_VERIFY_FAILED(andongmbc.co.kr). DH_KEY_TOO_SMALL은 _http_get이 자동 우회하지만 이들은 별개 원인 — 미수집은 정상 baseline
14. **GitHub Actions 액션 버전 경고** — actions/checkout@v4·setup-python@v5가 Node.js 20 기반이라 deprecated 경고 발생(2026-06-16 이후 Node 24 강제). 작동엔 지장 없으나 추후 액션 버전 상향 권장
15. **GitHub 예약(cron) 드롭·지연** — 예약 워크플로우는 best-effort라 부하 시 지연되거나 통째로 누락됨(특히 UTC 자정 부근 22~00 UTC = 07~09시 KST가 최악, UTC 00~11시 낮 블록도 통째 드롭 사례 있음 2026-06-15). daily_crawl은 :17/:47 이중화(정시·15분 단위 혼잡대 회피), 모닝 브리핑은 한산한 21 UTC대(06:00/06:30 KST)로 이동해 누락 확률을 낮췄으나 완전 방지는 불가 → 뉴스·브리핑 미축적 시 "Run workflow" 수동 실행 또는 PC 로컬 보완 (2026-06-15 확인). 분(minute) 튜닝은 단발 누락 확률만 낮출 뿐 블록 단위 드롭은 못 막음
16. **대시보드 파일 업로드는 텍스트 기반 PDF만** — 스캔 이미지 PDF는 본문이 비어 업로드 안 됨(브라우저 OCR 미지원). Word(docx)·MD·PPTX는 텍스트 추출됨. 업로드 직후엔 키워드·trgm 검색만 적용되고, 시맨틱 검색은 PC에서 backfill_embeddings.py 실행 후 적용 (2026-06-15)
17. **AI 자문 무거운 질문은 응답에 2분+ 소요** — 웹검색+긴 법령 답변은 100초 이상 걸릴 수 있음. 스트리밍이라 연결은 안 끊기고 답변이 점진적으로 표시됨. 비정상 종료가 아니라 정상 동작 (2026-06-15)

## 사용 중인 외부 서비스·라이브러리·키

| 항목 | 용도 | 비고 |
|---|---|---|
| GitHub Actions + Pages | 크롤링·브리핑 자동화 + 대시보드 호스팅 | 무료 Public 무제한 |
| Supabase | DB + Edge Function(voyage-embed) + Storage(uploads 버킷) | 무료 500MB/프로젝트(+ Storage 1GB), 최대 2개 |
| Voyage AI | 임베딩 (voyage-4-lite, 1024차원) | 무료 2억 토큰(1회성), Tier 1: 2000 RPM/16M TPM |
| Anthropic API | AI 자문 (claude-sonnet-4-6, 브라우저 직접 호출·stream:true) + 긴급도/요약(Haiku) | anthropic-dangerous-direct-browser-access. 키는 Supabase app_config(claude_key)에서 로드 |
| Resend | 이메일 발송 | 100통/일, 3,000통/월 |
| Telegram Bot | 알림 | 무제한 |
| trafilatura (pip) | 본문 추출 (정부 게시판 등 table 구조) | 로컬 PC 설치 필요 — 본문 수집 환경에 상주 |
| pdf.js · mammoth · JSZip (CDN) | 대시보드 브라우저 파일 파싱 (PDF·Word·PPTX 텍스트 추출) | index.html에서 CDN 로드, 설치 불필요 |
| 법제처 국가법령정보 DRF | 법령·고시 모니터링 | LAW_OC_KEY=radiopolicyai (GitHub Secrets) |
| 국민참여입법센터 (opinion.lawmaking.go.kr) | 입법예고(lsAnc) 모니터링 | gov_notice_crawler.py 로컬 수집, 키 불필요 |
| 열린국회정보 Open API | 국회 법안 모니터링 | ASSEMBLY_API_KEY (GitHub Secrets, open.assembly.go.kr 발급) |
| 네이버 검색 OpenAPI | 뉴스 수집 1순위 (crawl_naver_news) | NAVER_CLIENT_ID·NAVER_CLIENT_SECRET (developers.naver.com 앱 등록, 검색 API). 일 25,000회 무료. 미설정 시 Google RSS 폴백 |

### GitHub Secrets (Actions 자동화에 필수 — repo Settings → Secrets and variables → Actions)
```
SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY,
EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO, RESEND_API_KEY,
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
LAW_OC_KEY(=radiopolicyai), ASSEMBLY_API_KEY,
NAVER_CLIENT_ID, NAVER_CLIENT_SECRET   (네이버 검색 OpenAPI — daily_crawl.yml 크롤러 스텝 env에 주입)
※ 로컬 실행 시에는 동일 키들을 .env에 (.env는 .gitignore 등록됨 — 공개 repo 유출 없음)
```
