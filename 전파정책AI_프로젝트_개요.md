# 전파정책 AI — 프로젝트 개요 · 스펙 · 작동원리

> SKT Comm센터 기술정책팀의 전파·통신 정책 모니터링 자동화 시스템.
> 이 문서는 프로젝트를 처음 접하는 사람이 전체 그림을 이해하도록 쓴 소개서다.
> 운영 규칙·가드레일은 [`전파정책AI_지침_운영핵심.md`](전파정책AI_지침_운영핵심.md), 결정 배경·사고 이력은 [`전파정책AI_배경역사.md`](전파정책AI_배경역사.md) 참조.

---

## 1. 개요

### 무엇인가
정부·국회·언론에 흩어져 있는 **전파·통신 정책 정보를 자동으로 수집·요약·전달**하고, 축적된 법령·자료를 근거로 **AI 자문과 보고서 초안까지 생성**하는 1인 운영 자동화 시스템이다.

### 왜 만들었나
전파·통신 정책은 과기정통부·방통위·법제처·국회·행안부 등 여러 기관에서 수시로 쏟아진다. 이를 사람이 매일 손으로 모니터링하면 누락·지연이 생긴다. 이 시스템은 **수집→분류→요약→통지→검색·자문**의 흐름을 자동화해, 담당자가 "봐야 할 것"만 아침에 받아보고 필요할 때 근거와 함께 찾아볼 수 있게 한다.

### 누가 쓰나
- **주 사용자**: 기술정책팀 담당자 (유진웅, you.jinwoong@gmail.com)
- **운영 형태**: 개인 계정·무료 티어 위주의 1인 운영 (교대 시 [`HANDOFF.md`](HANDOFF.md)로 인수인계)

### 핵심 링크
| 구분 | 주소 |
|---|---|
| 대시보드 | https://radio-policy.gitlab.io/ |
| 소스 | GitLab(주) https://gitlab.com/radio-policy/radio-policy.gitlab.io · GitHub(미러) https://github.com/radio-policy/radio-policy.github.io |
| DB | https://zwkjedumfuhodckmtxxn.supabase.co |

---

## 2. 시스템 아키텍처

```
 ┌──────────────────────────── 수집(Collect) ────────────────────────────┐
 │  crawler.py(뉴스)   law_crawler(법령)   assembly_crawler(국회)         │
 │  gov_notice_crawler(정부고시·입법예고)  refetch_content(본문재수집)    │
 └───────────────┬───────────────────────────────────────────────────────┘
                 │  저장 + heartbeat
                 ▼
 ┌──────────────────────── Supabase (중앙 저장·연산) ─────────────────────┐
 │  Postgres 테이블(news_feed·law_amendments·document_chunks·report_* …)  │
 │  Edge Functions(voyage-embed 임베딩)                                   │
 │  RPC(시맨틱·trgm 검색)   Storage(원본파일)   Vault(PAT·토큰)           │
 └───────┬───────────────────────────────────────────────┬───────────────┘
         │ 조회·검색                                       │ 트리거(pg_cron)
         ▼                                                 ▼
 ┌───────────────── 전달·활용 ─────────────┐     ┌──────── 스케줄 ────────┐
 │ 대시보드(GitHub Pages)                   │     │ Supabase pg_cron(주)   │
 │  - 모니터링/브리핑                       │     │ GitHub Actions cron(백업)│
 │  - AI 자문(RAG+뉴스+법령+사내문서)       │     │ 외부 워치독(무음실패감시)│
 │  - 보고서 초안 제안                      │     └────────────────────────┘
 │ 알림: 텔레그램·이메일(모닝 브리핑 등)    │
 └──────────────────────────────────────────┘
```

**설계 철학**: Supabase가 데이터·연산·스케줄의 중심(single source)이고, 수집은 파이썬, 표현은 정적 대시보드, 통지는 텔레그램/이메일로 분리된 느슨한 결합 구조. 무료 인프라(GitHub·Supabase·Voyage·Resend·Telegram) 위에서 돌아간다.

---

## 3. 프로젝트 스펙

### 3.1 기술 스택 · 외부 서비스
| 계층 | 사용 기술 | 비고 |
|---|---|---|
| 수집 | Python (requests·trafilatura) | 크롤러·본문추출 |
| 저장/연산 | Supabase (Postgres + pgvector, Edge Functions=Deno, Storage, Vault) | 무료 500MB×2 |
| 임베딩 | Voyage AI (voyage-4-lite, 1024차원) | 무료 2억 토큰 |
| 생성 AI | Anthropic API (Sonnet=자문·보고서 / Haiku=분류·요약·증류) | 스트리밍 |
| 자동화/호스팅 | GitHub Actions + GitHub Pages | 무료 |
| 알림 | Telegram Bot(무제한) · Resend(이메일 100/일) | |
| 데이터 소스 | 네이버 검색 OpenAPI, 법제처 DRF, 열린국회정보, opinion.lawmaking.go.kr | |

### 3.2 저장소 구성 (주요 파일)
| 파일 | 역할 |
|---|---|
| `sb_client.py` | Supabase 클라이언트 공용 생성기 (HTTP/1.1 강제 — 끊김 회피). **모든 스크립트가 이걸 사용** |
| `crawler.py` | 메인 뉴스 크롤러 (네이버 OpenAPI→Google RSS 폴백, Haiku 긴급도 분류) |
| `morning_briefing.py` | 06:00 KST 브리핑 생성·발송 (SKT 영향 분석·무뉴스 통지 포함) |
| `gov_notice_crawler.py` | 정부 고시 + 입법예고 (한국 IP 필요, PC 로컬) |
| `law_crawler.py` / `assembly_crawler.py` | 법령·고시 / 국회 법안 모니터링 |
| `refetch_content.py` | 본문 재수집·정리 (trafilatura) |
| `health_watchdog.py` | 외부 헬스 워치독 (Supabase 독립) |
| `index.html` / `app.js` / `styles.css` | 대시보드 프론트엔드 |
| `system_prompt.js` | 대시보드 AI 자문 시스템 프롬프트 |
| `docs/voyage-embed.ts` | Edge Function 소스(템플릿) |
| `backfill_embeddings.py` / `backfill_report_embeddings.py` | 임베딩 백필 |
| `.github/workflows/` | daily_crawl·morning_briefing·law_crawl·assembly_crawl·backfill·cleanup·health_watchdog |

### 3.3 데이터 모델 (Supabase 주요 테이블)
| 테이블 | 설명 |
|---|---|
| `news_feed` | 뉴스 본문·요약·긴급도(15일 유지). `locked=true`면 자동삭제 제외 |
| `deleted_news` | 삭제 기사 블록리스트(재수집 방지, 영구) |
| `importance_feedback` / `feedback_rules` | 긴급도 수동 수정 이력 · 분류 학습 규칙 캐시 |
| `daily_briefings` | 일일 브리핑 원문 |
| `law_amendments` | 법령·고시·입법예고 (`law_type`: law/bylaw/rules/admrul/lsAnc) |
| `assembly_bills` | 국회 법안 (단계·소관위·제안일) |
| `document_chunks` | 법령·고시·보도자료 RAG 청크 (`embedding` vector 1024, HNSW) |
| `report_samples` / `report_style_rules` / `report_feedback` / `report_directives` | 보고서 형식·개인화 학습 데이터 |
| `custom_knowledge` | 팀 추가 지식 (수동 입력) |
| `system_health` | 운영 heartbeat (last_crawl_run·last_gov_notice_run·last_refetch_run) |

### 3.4 Edge Function · RPC
| 이름 | 역할 |
|---|---|
| `voyage-embed` (Edge) | 질의 임베딩 생성 (키는 서버 측 Secret) |
| `search_chunks_trgm` / `match_chunks_semantic` (RPC) | trgm / pgvector 시맨틱 검색 |
| `match_report_samples` (RPC) | 보고서 샘플 시맨틱 검색 |
| `dispatch_github_workflow` / `trigger_briefing_if_missing` | pg_cron→GitHub 워크플로 디스패치 |

### 3.5 스케줄 (이중화)
- **주 트리거 = Supabase pg_cron** (UTC 기준). 뉴스 매시 :47, 브리핑 06:05/06:20 KST, 법령 11:30, 국회 10:30, 무음실패 점검 21:00 등.
- **백업 = GitHub Actions cron** (:17 등). GitHub cron이 종종 드롭되므로 pg_cron이 주(主).
- **PC 로컬(한국 IP)** = 입법예고·정부고시 수집(17:00), 본문 재수집.

### 3.6 알림 채널
| 시점 | 채널 |
|---|---|
| 매일 06:00 KST | 텔레그램(분석 제외)·이메일(분석 포함) |
| 기사 0건인 날 | 텔레그램 "🕊️ 신규 뉴스 없음" (시각무관 1일1회) |
| 긴급 기사·신규 입법예고·법령 개정·국회 단계변경 | 텔레그램(즉시), 일부 이메일 |

---

## 4. 작동 원리 (데이터 흐름)

### 4.1 뉴스 수집 → 모닝 브리핑
```
crawler.py(매시) → 네이버 검색 OpenAPI로 기사 수집(키 없으면 Google RSS 폴백)
   → Haiku가 긴급/보통/참고 분류(피드백으로 학습) → news_feed 저장 + heartbeat
   → fetch_article_body가 본문 수집(실패 시 refetch_content.py가 PC에서 보강)
morning_briefing.py(06:00) → 당일 news_feed 집계 → 🔴긴급 + SKT 영향 분석 + 신규 입법예고 📢
   → 이메일·텔레그램 발송. 본문 0건이면 요약→제목 폴백(빈 브리핑 방지),
     기사 0건이면 '무뉴스' placeholder 통지(무음 누락 오인 방지)
```

### 4.2 법령·입법예고·국회
```
law_crawler.py    → 법제처 DRF API → law_amendments (신규/개정 시 텔레그램)
gov_notice_crawler.py → 정부고시(RRA·MSIT·KCC) + 입법예고 전체목록 스캔 → 요약 생성 → 통지
assembly_crawler.py → 열린국회정보 API(22대) → assembly_bills (단계변경 시 통지)
```

### 4.3 AI 자문 — RAG 3중 하이브리드 검색
대시보드 자문의 핵심. 질문이 들어오면 세 갈래로 검색해 근거를 모아 Claude에 투입한다.
```
질문 → ① Haiku 용어확장(법령 공식용어) → ② 키워드 ilike + trgm(search_chunks_trgm)
     → ③ voyage-embed 임베딩 → match_chunks_semantic(pgvector 코사인)
     → 하이브리드 랭킹(상위 청크) → 여기에 뉴스·법령동향 컨텍스트를 더함
     → Claude Sonnet이 SSE 스트리밍으로 답변(조문·고시번호·시행일 인용)
```
- **스트리밍 필수**: 무거운 답변은 2분+ 걸려, 비스트리밍이면 idle 끊김("Failed to fetch")이 남.
- **인용 원칙**: 국내 법령 조문은 RAG 원문 최우선, 웹검색·팀문서는 보조.

### 4.4 보고서 초안 제안 — 개인화 학습
"**내용은 RAG(법령·자료)에서, 형식·톤은 내 보고서에서**"가 원칙.
```
[내 보고서 등록] → report_samples(전문 통째 보관, 청킹 안 함) + Haiku 증류 → report_style_rules
[초안 생성] Sonnet(stream) + web_search → 내 형식·톤 + RAG 근거로 초안
[학습 3채널] ①말로 지시(이번만/항상적용) ②빨간펜(최종본 diff) ③👍/👎
   → 임계(+2) 도달 시 자동 재증류 → 쓸수록 내 톤에 수렴
```

### 4.6 스케줄 이중화 & 무음 실패 감시
```
Supabase pg_cron(주 트리거) ──▶ dispatch_github_workflow ──▶ GitHub Actions 실행
GitHub Actions cron(백업 슬롯) ──▶ 같은 워크플로 실행
크롤러가 성공 시 system_health에 heartbeat 기록
   ├ 내부 감시: check_news_health(21:00) — 신선도 이상 시 텔레그램 경보
   └ 외부 감시: health_watchdog(Supabase 독립) — '고장 vs 뉴스없음' 구분
```
운영 이상은 대시보드 **"운영 상태" 탭**에서 heartbeat·뉴스입력·브리핑·입법예고를 한눈에 점검.

---

## 5. 신뢰성 설계 원칙 (요약)
이 프로젝트는 다수의 실제 사고를 겪으며 **"조용히 실패하지 않게"** 하는 장치들이 쌓였다. 대표 원칙:
- **무음 실패 금지**: 트리거·크롤러·브리핑 각 단계에 heartbeat와 워치독을 두어, "안 오는 것"이 고장인지 정상(뉴스 없음)인지 구분한다.
- **폴백으로 무중단**: 본문 없으면 요약→제목, 기사 0건이면 placeholder, 임베딩 없으면 키워드 검색 — 핵심 기능은 살린다.
- **버전·연결 고정**: `requirements.txt`로 의존성 잠금, `sb_client`로 HTTP/1.1 강제(끊김 회피).
- **비밀은 서버 측에만**: API 키·PAT은 .env·GitHub Secrets·Supabase Secrets/Vault에만. 브라우저·공개 repo 노출 금지.

> 각 원칙의 상세 사고 경위(#15~#20)는 [`전파정책AI_배경역사.md`](전파정책AI_배경역사.md)에 있다.

---

## 6. 주요 제약사항
- 이메일은 you.jinwoong@gmail.com만 수신 (Resend 도메인 미인증).
- 입법예고·정부고시·본문재수집은 **PC 로컬(한국 IP) 의존** — 정부 사이트 해외 IP 차단 때문.
- Supabase 무료 슬롯 2개 모두 사용 중 — 신규 프로젝트 생성 불가.
- GitHub cron은 best-effort(드롭·지연) — Supabase pg_cron이 주 트리거로 보완.
- 신규 업로드 문서·보고서는 임베딩 백필 전까지 시맨틱 검색 미적용("임베딩 대기").

---

## 참고 문서
- [`전파정책AI_지침_운영핵심.md`](전파정책AI_지침_운영핵심.md) — 운영 핵심·DB 스키마·가드레일(매 작업 적용)
- [`전파정책AI_배경역사.md`](전파정책AI_배경역사.md) — 각 결정의 배경·사고 이력
- [`HANDOFF.md`](HANDOFF.md) — 담당자 교대 인수인계
- [`CLAUDE.md`](CLAUDE.md) — Claude Code 작업용 가이드
