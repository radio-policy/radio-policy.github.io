# 전파정책 AI 프로젝트 — Claude Project 지침 (운영 핵심)

## 지침 관리 규칙

- **지침 변경 시 변경분 요약이 아니라, 변경이 반영된 전체 지침 텍스트를 제공할 것** (사용자가 그대로 복사해 Project 설정에 붙여넣을 수 있도록).
- **이 프로젝트는 문서를 둘로 운용한다:**
  - ① **이 지침** = 운영 핵심 (시스템 구조·DB 스키마·"하지 말아야 할 것" 가드레일 + 각 규칙의 한 줄 이유·작업 패턴). 매 작업마다 항상 적용.
  - ② **배경·역사 지식 문서** = `전파정책AI_배경역사.md` (repo 폴더 보관, Cowork에서 직접 참조). 각 결정의 상세 배경·과거 사고 경위·날짜·커밋 해시 등 긴 서술.
- **지침을 업데이트할 때는 반드시 `전파정책AI_배경역사.md`도 함께 갱신하고, 두 문서의 전체 텍스트를 모두 제공할 것.**
  - 새 규칙/가드레일 → 지침엔 "규칙 + 한 줄 이유", 배경역사 문서엔 상세 경위.
  - 지침의 한 줄 이유와 배경역사 문서의 상세 설명이 같은 사건을 가리키도록 어긋남 없이 유지.

## 프로젝트 개요

SKT Comm센터 기술정책팀의 전파·통신 정책 모니터링 자동화 시스템.
- 대시보드: https://youjinwoong.github.io/radio-policy-ai/
- GitHub: https://github.com/youjinwoong/radio-policy-ai
- 담당자: 유진웅 (you.jinwoong@gmail.com)

## 로컬 파일 위치

```
C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai\
├── sb_client.py                # Supabase 클라이언트 공용 생성기 — HTTP/2 끄고 HTTP/1.1+재시도(make_client). 모든 스크립트가 create_client 대신 사용(RemoteProtocolError 끊김 회피)
├── requirements.txt            # 의존성 버전 고정(lock, 61개). 모든 워크플로가 `pip install -r requirements.txt`로 설치 — 자동 최신화 사고 방지(배경역사 #15)
├── crawler.py                  # 메인 크롤러(GitHub Actions 매시간) — 네이버 검색 OpenAPI(키 없으면 Google RSS 폴백), Haiku 긴급도 분류(피드백 학습), fetch_article_body 본문 수집, 긴급 재알림 억제(suppress_repeat_alerts, #44)
├── morning_briefing.py         # 모닝 브리핑 생성·발송(06:00 KST) — 🔴=DB 긴급도, 같은 사건 클러스터링(대표 1건+관련 N건, #44), SKT 영향 분석, 신규 입법예고 📢 섹션, 본문 0건 시 요약→제목 폴백(빈 브리핑 방지), 기사 0건 시 시각무관 1일1회 '🕊️무뉴스' 통지+placeholder(_handle_no_news)
├── news_dedup.py               # 같은 사건 재보도 판정 공용 유틸(제목 키워드, API 비용 0) — crawler·morning_briefing 공유. 임계 3·별-형 클러스터링 근거는 파일 주석 (#44)
├── regenerate_briefings.py     # 과거 브리핑을 클러스터링 적용본으로 재생성(수동). morning_briefing 함수 재사용, 입법예고 섹션 보존. **실행 전 daily_briefings_backup에 원본 백업 필수** (#46)
├── refetch_content.py          # 본문 재수집·요약·60일 초과 정리(Windows 스케줄러, 한국 IP) · heartbeat(last_refetch_run)
├── gov_notice_crawler.py       # 정부·기관 고시→news_feed + 입법예고(opinion.lawmaking.go.kr)→law_amendments(lsAnc) (17:00, 한국 IP) · heartbeat(last_gov_notice_run)
│                               #   RRA(국립전파연구원)·MSIT(과기정통부)·KMCC(중앙전파관리소)·KCC(방통위)·ETRI·KISDI
│                               #   ※ crawl_kcc()는 방통위(kcc.go.kr), crawl_kmcc()는 중앙전파관리소(kmcc.go.kr) — 도메인 한 글자 차이라 혼동 주의
├── law_crawler.py              # 법제처 DRF API 법령·고시 모니터링(11:00 KST). 엔드포인트 www.law.go.kr/DRF/lawSearch.do, OC=radiopolicyai
├── assembly_crawler.py         # 국회 법안 모니터링(열린국회정보 API, 22대)
├── upload_law_pdf.py           # PDF/MD/PPTX→document_chunks RAG 업로드(조문 헤더 청킹)
├── import_regulatory_kb.py     # regulatory-kb OKF 번들(법령 요약 104건)→kb_documents/kb_chunks 1회 적재. manifest.json 정본 순회, voyage-law-2 임베딩(stdlib만). (배경역사 #21)
├── add_law.py                  # 법령 추가 통합(Ⓑ): PDF 1개→①조문 document_chunks ②Haiku 요약 OKF→regulatory-kb+manifest+kb_* 동시. MAINTENANCE.md dedup 규칙 적용
├── regulatory-kb/              # OKF 법령 요약 번들(manifest.json 정본 + laws/·procedures/·glossary/). kb_* 적재 원천
├── backfill_embeddings.py      # Voyage 임베딩 백필(document_chunks NULL만)
├── backfill_report_embeddings.py # 보고서 샘플 임베딩 백필(report_samples NULL만) — 신규 보고서 등록·채택본 승격 후 실행
├── resend_briefing.py / send_briefing.py  # 브리핑 재발송·발송 단독
├── health_watchdog.py          # 외부 헬스 워치독(GitHub Actions, Supabase 독립) — 크롤러 성공여부 인지(고장 vs 뉴스없음 구분)
├── system_prompt.js            # 대시보드 AI 자문 시스템 프롬프트(위임 관계 검증·핵심 조문 참조)
├── index.html / app.js         # 대시보드 프론트엔드(GitHub Pages). AI 자문·보고서 초안 모두 SSE 스트리밍(stream:true) — 비스트리밍 복귀 금지. AI 자문은 RAG+뉴스+법령동향 컨텍스트 조합
├── crms_guide_sync.py          # 중앙전파관리소 업무안내 38p → regulatory-kb 적재(월 1회, 한국 IP). 본문 sha256 비교로 변경분만
├── run_gov_crawler.bat / run_briefing_backup.bat / run_crms_sync.bat / setup_*.ps1  # 배치·스케줄러 등록
└── .github/workflows/          # daily_crawl·morning_briefing·law_crawl·assembly_crawl·backfill·cleanup·health_watchdog
```

## Supabase DB

- **Project ID**: zwkjedumfuhodckmtxxn / **URL**: https://zwkjedumfuhodckmtxxn.supabase.co / **Region**: ap-northeast-1(도쿄)

### 주요 테이블

| 테이블 | 설명 |
|---|---|
| news_feed | 뉴스 본문·요약·긴급도(**60일 유지** — 2026-07-31 확대, 자문 뉴스 검색 60일 창과 정합). locked=true면 자동삭제 제외+AI 자문 상시 참조. 내부값 긴급/보통/참고. **url UNIQUE**(idx_news_feed_url_unique) — 저장은 반드시 `upsert(on_conflict='url', ignore_duplicates=True)`로 (plain insert는 중복 1건에 배치 전체 실패, #23) |
| deleted_news | 삭제 기사 url·title 블록리스트(재수집 방지). 영구 |
| importance_feedback | 긴급도 수동 수정 내역(news_id당 1행). 분류 학습 데이터. 영구 |
| feedback_rules | 피드백 증류 규칙 캐시(단일 행 id=1). 20건↑ 증류, 10건마다 재증류 |
| daily_briefings(삭제 없음·전량 보관, 목록도 무제한 표시) | 일일 브리핑 원문("⚠️ SKT 영향 분석:" 포함). 긴급도 수정 시 🔴 자동 동기화 |
| law_amendments | 법령·고시·입법예고. law_type: law/bylaw/rules/admrul/lsAnc. lsAnc는 law_id=`lsAnc_op_{md5}` |
| assembly_bills | 국회 법안. bill_id(UNIQUE)·법안명·단계·소관위·제안일·링크 |
| document_chunks | 법령·고시·보도자료 RAG 청크. embedding(vector 1024, HNSW), article_no=조항번호+제목. file_path=업로드 원본 Storage 경로. **보도자료는 2026-08-02부터 자동 수집**: doc_name=`{기관}_보도자료_{YYYY}.md`(기관: 과기정통부/전파연구원/방통위/전파관리소/ETRI/KISDI), 섹션 헤더 `## YYMMDD 제목`, 마지막 줄 `(원문: URL)`, **700자 무겹침 청킹**(대시보드가 청크를 이어붙여 원문 복원하므로 overlap 금지) |
| app_config | 키-값 설정. `system_prompt`(봇 자문 프롬프트), `press_keywords`(보도자료 수집 키워드 JSON 배열 — 대시보드 '수집 키워드 관리' 카드가 편집), `press_relevance_criteria`(매일 수집 AI 관련성 판정 기준문) 등. **claude_key는 anon 노출되는 브라우저용 — 서버측 재사용 금지** |
| custom_knowledge | 팀 추가 지식(수동 입력). AI 자문 키워드 매칭 참조 |
| chat_logs | AI 자문 이력. 삭제 가능. `sources`(text)는 **두 종류를 접두사로 구분해** 담는다 — 법령·문서명은 그대로, 수집 뉴스는 `[뉴스] 제목 (매체, 날짜)`. 화면·내보내기에서 `splitSources()`로 갈라 별도 표기(법령은 6개 초과분 `… 등 N개`). **뉴스는 본문 발췌로 실제 반영된 건만** 기록(제목 목록 30건은 근거 아님). 스키마 변경 없이 반영 여부를 사후 검증하려는 구조. (배경역사 #35) |
| report_samples | 보고서 초안 제안 — 내 보고서 전문(형식·톤 학습용, 청킹 안 함). embedding(vector 1024, HNSW). report_type=정책검토/규제영향/동향보고/기타 |
| report_style_rules | 보고서 스타일 가이드 캐시(단일 행 id=1). sample_count·feedback_count로 자동 재증류 임계(+2) 추적 |
| report_feedback | 보고서 피드백 — request·draft·final(채택·교정본)·rating(1/-1). 편집-diff 학습 데이터. 영구 |
| report_directives | "항상 적용" 영구 지시 — 모든 초안 시스템 프롬프트에 최우선 주입. 관리 탭에서 삭제 가능 |
| alert_suppress_log | 긴급 재알림 억제 내역(어떤 기존 기사와 유사해 막았는지, 공유 키워드). **1~2주 실측 후 "본문에만 새 내용" 놓침이 있으면 Haiku 판정 층(월 2~6$) 추가 판단**용. service만 접근(정책 없음) (#44) |
| system_health | 운영 heartbeat(key별 1행). last_crawl_run=뉴스크롤러 / last_gov_notice_run=입법예고·정부고시 / last_refetch_run=본문수집. 워치독 '고장 vs 없음' 구분 + 운영상태 탭. RLS+anon select |
| kb_documents | 법령·규제 **요약/실무 문서**(regulatory-kb OKF 번들, 문서당 1행). concept_type·law_type·law_number·enforcement_date·status(current/superseded)·body_md 컬럼. path 유니크(정체 키). **document_chunks(조문 원문)와 별개 레이어** — 조문 인용은 그쪽, 요약·적용범위·실무는 이쪽. RLS+anon select |
| kb_chunks | kb_documents 본문 청크 + embedding(**voyage-law-2** 1024, HNSW). doc_id FK(cascade). 자문이 시맨틱+trgm으로 조회 |
| law_graph_nodes | 법령 관계도 노드(name UNIQUE). node_type: topic(주제)/law/decree/rules/notice/etc. source: seed(세션 시드)/citation(인용망 스크립트)/ai(자문·즉석 생성). doc_name=document_chunks 연결(원문 보기). RLS+anon select/insert/update(delete는 service 전용) |
| law_graph_edges | 법령 관계도 엣지(source_id→target_id, on delete cascade). relation_type: 근거(주제→법령)/인용(조문 인용)/하위법령(계열). source: seed/citation/family/ai. weight=인용·재확인 횟수(엣지 굵기). unique(source,target,relation_type). RLS 동일 |
| telegram_subscribers | 구독자 봇 가입자(chat_id PK). topic_briefing/urgent/assembly(각각 on·off), days(daily/weekday), briefing_hour(6~12, **3종 공통 수신 시각**), last_briefing_sent_date·last_urgent_sent_at·last_assembly_sent_at(중복 발송 방지), ai_allowed(**기본 false** — AI 자문 승인 플래그), ai_count_date·ai_count(일일 20회 상한). active는 봇 차단(403) 자동 처리 전용이며 화면에 버튼은 없다. **RLS 켜고 정책 0개 = service_role 전용**(chat_id는 개인정보, 프런트 노출 금지 — 의도된 설계) |
| subscriber_queue | 긴급·법안 알림 큐(topic: urgent/assembly, html, created_at). 크롤러가 **발송 대신 적재**하고 send-subscriber-briefing이 각 구독자 수신 시각에 꺼내 보낸다. 억제·클러스터링(#44)·법안 상태변경 판정을 TS로 재구현하지 않으려는 구조. RLS 정책 0개 |

### Edge Function · RPC

| 이름 | 역할 |
|---|---|
| voyage-embed (Edge) | 질의 임베딩. VOYAGE_API_KEY는 Supabase Secrets(브라우저 노출 금지). **body.model로 모델 선택(하위호환)**: 미지정=voyage-4-lite(document_chunks 조문), `voyage-law-2`(kb_chunks 법령요약). 저장·질의 모델 반드시 일치 |
| match_kb_chunks_semantic / search_kb_chunks_trgm (RPC) | 법령요약(kb_chunks) 시맨틱/trgm 검색. 기본 `only_current=true`(구버전 제외). insert_kb_chunks(RPC)는 적재 시 청크 일괄 삽입(text→vector) |
| list_kb_documents (RPC) | 지식 베이스 문서 목록(doc_name 그룹핑) |
| admin_delete_custom_file / admin_delete_chat_log (RPC) | 대시보드 삭제용(비밀번호 검증, security definer). **삭제된 행 수를 반환**하며 프런트는 0이면 실패로 처리한다. `document_chunks`·`chat_logs`는 RLS가 켜져 있고 DELETE 정책이 없어 프런트 직접 `delete()`가 오류 없이 0건으로 끝났다(#48) |
| list_kb_guide_docs (RPC) | `실무 안내` 탭 목록(현행본 203건). **body_md는 안 돌려준다** — 203건 합계 681kB라 브라우저로 내려받으면 안 되고, `has_table`(표 포함 여부)·`chunks`(청크 수)만 서버에서 계산해 준다. 본문은 클릭 시 그 문서 1건만 조회 |
| search_chunks_trgm / match_chunks_semantic (RPC) | trgm / pgvector 시맨틱 검색 |
| match_report_samples (RPC) | 보고서 샘플 시맨틱 검색(코사인). filter_type으로 유형 한정 |
| telegram-webhook (Edge) | 구독자 봇 수신부. `/start`·`/settings` 인라인 키보드, `/law "OO법 N조"` 조문 원문 즉답, `/ask` AI 자문(승인제), `/admin`(운영자). **verify_jwt off** 대신 `X-Telegram-Bot-Api-Secret-Token` 검증. 오류가 나도 200을 반환한다 — 비200이면 텔레그램이 같은 업데이트를 무한 재전송한다 |
| send-subscriber-briefing (Edge) | 구독자 정시 발송. pg_cron이 매시 호출 → 브리핑(daily_briefings)+긴급·법안(subscriber_queue)을 **수신 시각이 도래한 구독자에게 한 번에** 보낸다. `briefing_hour <= 현재KST시` catch-up이라 브리핑이 늦게 생성돼도 다음 정각에 따라잡는다. `x-cron-secret` 검증 |
| supabase/functions/_shared/ | 두 함수 공용 모듈. `telegram_format.ts`(HTML 이스케이프·분할·발송, 400시 plain 폴백), `rag.ts`(자문 RAG — 조문+법령요약+조문정밀검색+수집뉴스 → Sonnet) |

### Storage

- **uploads (private)**: 추가지식·보고서 원본 보관. anon insert/select/delete. 다운로드는 createSignedUrl(60초). public화 금지.

### RLS

- document_chunks·report_samples·report_style_rules·report_feedback·report_directives: RLS 활성 + anon select/insert/update/delete 정책. custom_knowledge·feedback_rules·news_feed: RLS 비활성.
- law_graph_nodes·law_graph_edges: RLS 활성 + anon select/insert/update (**delete는 service_role 전용** — 대시보드는 병합만 하고 삭제는 스크립트·세션만).

### pg_cron 스케줄 잡 (DB 내부 스케줄러, UTC 기준 / KST=UTC+9). `select * from cron.job`로 조회.

| jobid | jobname | UTC | KST | 역할 |
|---|---|---|---|---|
| 1 | briefing-health-check | `0 1 * * *` | 10:00 | 브리핑 상태 점검(경고 전용) |
| 2 | news-feed-cleanup | `0 15 * * *` | 00:00 | 60일 초과 뉴스 자동 삭제(created_at>60d AND locked=false) — PC 불필요 |
| 9 | crawl-trigger-hourly | `47 * * * *` | 매시 :47 | 뉴스 크롤러 트리거(주 트리거) → daily_crawl.yml dispatch |
| 10 | assembly-crawl-trigger | `30 1 * * *` | 10:30 | 국회 크롤러 백업 트리거 |
| 11 | law-crawl-trigger | `30 2 * * *` | 11:30 | 법령·입법예고 크롤러 백업 트리거 |
| 8 | briefing-trigger-0605 | `5 21 * * *` | 06:05 | 모닝 브리핑 자동 트리거(없으면 dispatch) |
| 7 | briefing-trigger-0620 | `20 21 * * *` | 06:20 | 위 백업 재시도 |
| 12 | news-health-check | `0 12 * * *` | 21:00 | 무음 실패 알람(내부) check_news_health() |
| 13 | watchdog-trigger | `35 12 * * *` | 21:35 | 외부 워치독 백업 dispatch |
| — | subscriber-briefing-hourly | `25 * * * *` | 매시 :25 | 구독자 정시 발송 → send-subscriber-briefing. `:25`는 06:05~06:20 브리핑 생성 창을 피한 값. 대상이 없으면 no-op이라 매시 돌아도 부담 없음. Vault `subscriber_cron_secret` 사용 |

- 공용 디스패치 함수 `dispatch_github_workflow(p_workflow)` + `trigger_briefing_if_missing()`. 인증: GitHub PAT을 Supabase Vault `github_pat`에 저장. 텔레그램 토큰은 Vault `telegram_bot_token`.
- ⚠️ PAT 만료/회수 시 모든 트리거가 조용히 멈춤 → Vault `github_pat` 갱신. **PAT 재생성 시 권한 3종(Contents R/W·Metadata·Actions R/W) 반드시 확인 — Actions 누락 시 workflow_dispatch가 403인데 pg_cron은 'succeeded'로 찍혀 무음 실패. 교체 검증은 cron 잡 상태가 아니라 `net._http_response.status_code`(204=성공)로 한다.** (설계 배경·드롭 경위·#18 사고는 배경역사 문서 참조)

## 보고서 초안 제안 (자문 메뉴)

내 보고서 **형식·톤** + 법령·자료(RAG) **내용 근거**로 보고서 초안 생성. 핵심: 내용은 RAG에서, 형식·톤은 내 보고서에서.

- 메뉴: [자문] › 보고서 초안 제안 (탭2 — 초안 생성 / 내 보고서 관리)
- 생성: claude-sonnet-5, stream:true, web_search 3회 (callReportDraft). 증류: claude-haiku-4-5 (distillReportStyle).
- **상위 모델(Sonnet 계열)은 자문·보고서·DIFF·용어상세 4곳 + 백필 스크립트에서만 사용** — 모델 교체 시 app.js 6곳과 backfill_term_details.py를 함께 바꿔야 생성물 형식·품질 일치. Haiku 경로는 비용 구조상 그대로 둘 것. (배경역사 #27)
- **개인화 학습 채널 3종** (쓸수록 내 톤 수렴):
  1. **말로 지시(onReviseDraft)** — `이번만`(다회 대화식 즉석 수정, 기억 안 함) / `항상 적용`(report_directives 영구 저장→모든 초안 최우선 주입, 관리 탭에서 삭제)
  2. **빨간펜(편집-diff)** — "고쳐서 최종본 채택"(saveReportFinal→report_feedback.final). 초안↔최종본 차이를 증류에 "반드시 반영". 채택본은 "예시 보고서로 추가"로 승격(선택)
  3. **👍/👎(submitReportFeedback)** — 약한 신호. 👎는 "피하라" 패턴으로 증류 반영
- **자동 재증류**: sample_count·feedback_count로 추적, 임계(샘플+2 또는 피드백+2) 도달 시 자동. 수동은 "스타일 재학습" 버튼. 구조 학습엔 샘플 2편 이상 필요.
- **파일 등록**: drag&drop / 클릭 (PDF·docx·pptx·md·txt, 브라우저 파서). **임베딩**: 등록·승격 후 PC에서 `python backfill_report_embeddings.py`(NULL만). 그 전엔 유형/최신순 폴백("임베딩 대기").
- **내보내기**: exportReportDraftDoc(마크다운→HTML→.doc).
- 보안: 원문은 Supabase(private)에만. 생성 시 예시·스타일·지시가 Anthropic API로 전송됨(학습엔 미사용). 민감 수치는 마스킹·형식 위주 등록 권장.

## 법령·규제 요약 레이어 (regulatory-kb → kb_*)

- **조문 원문(document_chunks)과 별개의 상호보완 레이어.** kb_documents/kb_chunks에는 법령별 **요약·적용범위·실무 체크리스트·소관부처**(현행본 위주)를 담고, 자문(app.js `searchKbSummaries`→`buildKbContext`)이 `[법령요약]` 컨텍스트로 주입. **조문 번호·문구 인용은 document_chunks 원문 우선**, 요약은 실무 맥락 보강용.
- 임베딩은 **voyage-law-2**(법률 특화, 1024). 질의도 voyage-embed의 `model:'voyage-law-2'`로 임베딩(모델 일치 필수). 시맨틱+trgm 병행, 기본 **현행본(status=current)만**(구버전은 명시 요청 시).
- 적재: `python import_regulatory_kb.py`(manifest 정본 순회, path별 idempotent). 신규/갱신은 `add_law.py`(dedup·최신본 superseded 처리는 regulatory-kb/MAINTENANCE.md).
- **대시보드 승인 훅 OKF 자동 생성(2026-07-29)**: 웹 업로드(법령·고시 카테고리) 승인 시 임베딩에 이어 **OKF 요약까지 자동 적재** — 브라우저가 Haiku로 초안 작성(add_law.py와 동일 프롬프트) → voyage-law-2 임베딩(voyage-embed Edge) → `admin_upsert_kb_document`/`admin_insert_kb_chunks` RPC(비밀번호 검증, 동일 path 덮어쓰기·구버전 supersede는 RPC가 처리). 실패해도 승인·조문 임베딩은 유지(자문은 조문 기반으로 동작, add_law.py로 보완). path는 `laws/web-upload/…`, family=`web-upload`.
- **화면은 `실무 안내` 탭(2026-07-31 신설)** — kb_documents 203건(중앙전파관리소 실무 38 / 법령요약 163 / 기타 2)을 **접히는 계층 목록**으로 열람. 중앙전파관리소는 2단(분야 › 문서), 법령 요약은 3단(계열 › 하위 묶음 › 문서). 필터 칩(전체·중앙전파관리소·법령 요약) + `모두 펼치기` + 이름 검색(검색 중에는 일치 묶음 자동 펼침). `국내 법령·고시` 탭은 조문 원문(document_chunks) 전용이라 kb는 한 건도 안 보인다.
- **폴더명이 영문이라 app.js `_GUIDE_FAMILY_KO`/`_GUIDE_SUB_KO`로 한글 이름표를 매핑**한다(계열 18 + 하위 6). **계열 폴더를 새로 만들면 이 표에도 넣을 것** — 안 넣으면 영문 폴더명이 그대로 이름표가 된다(폴더 실제 이름은 회색으로 병기하므로 대조 가능).
- 목록 배지: **`청크 없음` = 등재됐으나 자문 검색엔 안 잡히는 상태**(즉시 재적재 대상) / `표 포함` = 수수료표·산정식 등 표가 있는 문서(현재 77건). (배경역사 #42)
- **자문 답변 하단 출처 배지는 4종**: 접두 없음=`참조 법령`(조문 원문) / `[별표] `=`참조 별표`(금액·요율의 정본) / `[요약] `=`참조 요약·실무`(kb) / `[뉴스] `=`참조 뉴스`. **`참조 요약·실무`가 안 뜨면 kb 레이어가 반영 안 된 것**이고, **금액을 묻는 질문에 `참조 별표`가 안 뜨면 표 없이 조문만 보고 답한 것**이다 — 적재·반영 검증은 반드시 이 배지로 한다. (배경역사 #41, #43)
- **번들 역동기화(필수 주기 작업)**: 웹 생성 OKF는 DB에만 존재(브라우저는 번들 파일을 못 씀) → PC에서 `python sync_kb_to_bundle.py`가 manifest에 없는 path를 md 파일+manifest 항목으로 저장하고 status 불일치(supersede)도 manifest에 반영. **`import_regulatory_kb.py` 전체 재적재 전에 반드시 먼저 실행**(안 하면 웹 생성 OKF가 재적재에서 유실). 번들=요약의 유일한 백업(무료 플랜은 DB 백업 없음)이므로 월 1회 실행+커밋 권장.

## RAG 3중 하이브리드 검색

```
질문 → ① expandQueryKeywords(Haiku 용어 확장) → ② 키워드 ilike + search_chunks_trgm
     → ③ voyage-embed → match_chunks_semantic → 하이브리드 랭킹 → 상위 청크 투입
응답: callClaude가 stream:true(SSE)로 토큰 실시간 수신 (비스트리밍 시 ~120초 idle 끊김 "Failed to fetch")
인용: buildRagContext()가 조항(번호+제목)·고시번호·시행일 표시. article_no에 조문 제목 포함.
임베딩 백필: 신규 업로드 후 PC에서 python backfill_embeddings.py (NULL만). 그 전엔 "임베딩 대기" 배지.
```

## 자문 뉴스 컨텍스트 (news_feed → 프롬프트)

법령 RAG와 별개 경로다. `fetchRecentNewsContext()`(app.js)가 두 블록을 만들어 시스템 프롬프트에 붙인다.

```
[질문 관련 최신 기사]  ← 최대 3건. extractNewsKeywords(뉴스 전용) 6개로 조회,
                         제목 일치 가중 3 + 본문 일치 가중 1 → 관련도 순(최신순 아님).
                         2점 미만은 배제(0건일 때만 상위 2건 완화).
                         발췌 예산 차등: 1위 1,800자 / 2·3위 700자.
[최근 수집 뉴스 동향]  ← 최근 60일 제목 30건(최신순). 동향 참고용이며 근거가 아니다.
발췌 직후 지시: 질문이 수치·순위 비교면 웹검색·학습지식 대신 발췌 수치를 매체·날짜와 함께 인용.
출처 표기: 본문 발췌분만 chat_logs.sources에 [뉴스] 접두사로 기록 → 답변 아래 🗞️ 참조 뉴스 배지.
```

- 대상은 최근 60일 + `locked=true`(잠금 기사는 기간 무관 상시 참조).
- 반영 여부는 답변 아래 `🗞️ 참조 뉴스` 배지로 확인한다. **배지가 없으면 그 답변에는 뉴스가 안 들어간 것** — 사후 판별 수단이 없어 오답을 신뢰했던 사고의 재발 방지 장치다. (배경역사 #35)

## 법령 관계도 (lawmap 메뉴, 2026-07-23 신설)

주제↔법령 네트워크 그래프(vis-network). 데이터는 law_graph_nodes/edges, 성장 경로 4개:

```
① 자문 자동 축적(주 경로, 추가 호출 0회): callClaude가 시스템 프롬프트에 lawmapGuide 주입 →
   법령 질문이면 답변 말미에 <lawmap>{topic, relations[]}</lawmap> 블록 → sendChat이 파싱해
   화면에서 제거·DB upsert(재확인 엣지 weight+1)·답변 밑 미니 SVG 표시. 기존 주제명 목록을
   프롬프트에 넣어 주제명 분열 방지.
② 관계도 탭 질문: 로컬 매칭(비용 0) 우선 → 없으면 "AI로 생성"(1회 과금, 결과 저장 → 재질문 무료).
③ 주제 "AI로 보강" 버튼: 기존 그래프를 통째로 주고 빠진 관계만 증분 추가(기존 삭제 없음).
④ build_law_citation_graph.py(PC): 법령·고시 원문 조문의 「법령명」 인용 + 계열(시행령/규칙)을
   추출해 citation/family 엣지 재구축(멱등). 새 법령 업로드(add_law.py) 후 재실행 권장.
   노드 매칭은 공백 무시(nrm) — PDF 추출이 단어 중간에 공백을 끼워("전 파법") 변형 노드를
   양산하던 문제의 재발 방지. 기존 변형 183개는 2026-07-29 정본 병합 완료(배경역사 #30).
   **`ensure_node`는 nrm매칭으로 재사용한 노드의 `name`도 doc_name 쪽 정본으로 갱신한다**
   (2026-07-30 수정 — 예전엔 doc_name만 채우고 name의 손상된 표기는 영구히 남았다. 배경역사 #33).
```

- 세션에서 주제 수동 추가 패턴: 노드 `insert ... on conflict (name) do nothing` → 엣지 `insert ... select` name 조인 + `on conflict do nothing` (source='seed'). 2026-07-23 시드 30주제가 예시.
- vis-network는 CDN(unpkg, 9.1.9 고정) **지연 로드** — lawmap 탭 첫 진입 시에만. 다른 탭 성능 무관.
- 전체 뷰는 **'전파정책 관련 법'만**: 코어 = 주제 + 주제·시드에 연결된 법 + 그 법의 계열(하위법령). 엣지 = 시드·주제 엣지 + (코어 내부의 계열·인용). 실측 ~176 노드/523 엣지(2026-07-30, 주제 51개 — 이동통신사업 계열 18주제·전파사용료 포함 일괄 시드 후. 배경역사 #34). **지방세법처럼 세금 감면 조항에서 농지법·축산법·의료법 등 타 분야 법을 대량 인용하는 허브의 바깥 인용은 코어 밖이라 제외** — 그 허브의 전체 인용은 노드를 클릭해 드릴다운할 때만 표시(운영자 피드백: 전체 뷰에 무관한 법이 들어옴). **인용망 전체를 무필터로 펼치지 말 것**(농지법 등 노이즈 재유입). **안정화(stabilizationIterationsDone) 후 physics를 꺼서 노드가 계속 흔들리는 현상 방지 — 끄지 말 것**. 라벨은 배경색 strokeWidth 외곽선(제거 금지). 주제 포커스 뷰는 직접 이웃+계열(하위법령) 1단계만 확장(허브 법령 경유 폭발 방지).
- 노드 상세 카드는 **주제 맥락 인식형**: 주제 포커스 중 법령 클릭 → ① 🎯 이 주제에서의 역할(엣지 설명) ② 📌 근거 조문 원문 발췌(엣지의 "제N조"를 document_chunks에서 조회 — article_no가 문서마다 '제19조(...)'/'19조(...)' 두 형태라 양쪽 매칭 필수) ③ 연결 관계는 현재 그래프 범위만. 법령 전체 요약(OKF)은 역할·근거 조문 아래에 **펼쳐서** 표시(주제 맥락이 위에 오므로 전체 요약도 함께 보이는 게 유용 — 운영자 피드백). 📌 조문 발췌는 **추측이 아니라 법령 구조로** 정확히 집는다(운영자 피드백: 가점 땜질 말고 근본 해결). 우선순위 3단계:
① **명시 조문** — 관계 설명의 "제N조"(제24~25조 범위·제N조의M 포함) → "근거 조문".
② **위임 연결(delegation)** — 노드가 시행령·시행규칙이면, 그 상위법에 대한 주제 엣지의 근거 조문 N을 찾아 하위법령 본문에서 **"법 제N조"를 인용하는(=위임받는) 조문**을 집음(인용 횟수순). 한국 시행령·시행규칙은 자기가 구체화하는 상위법 조문을 본문에 명시하므로 결정론적. 예: 주파수 분배(전파법 §9) → 전파법 시행령에서 "법 제9조"를 인용하는 §10-2(주파수분배 변경 지원). "관련 조문(위임 근거)" 라벨.
위임 후보군이 있으면 그 안에서 키워드+시맨틱 관련성으로 순위("위임 근거+관련성" 라벨). "권한의 위임·위탁" 등 여러 조문 나열하는 집계성 조문은 배제(LAWMAP_ART_BOILER).
③ **최후 폴백 — 키워드+시맨틱 하이브리드** — 위 둘로 안 잡히면(위임 후보 없음 등). 키워드(조문 단위 1회 집계·제목 ×5·본문 ×1·총칙/부칙 배제)와 문서 한정 시맨틱(`match_chunks_semantic_in_doc` RPC, voyage-4-lite)을 0.45:0.55 결합. **키워드는 청크마다 더하지 말 것**(긴 조문 편향으로 정확한 짧은 조문이 밀림). 임베딩 실패 시 키워드만("키워드 매칭" 라벨). ※ 초기에 넣었던 '제목 구절 +15 가점'은 위임 후보군 도입으로 불필요해져 제거함(가점 땜질 대신 구조로 해결 — 운영자 피드백). **주제 포커스 중이면 직접 관계 엣지가 없는(계열로 딸려온) 노드도 주제명 키워드로 조문 검색** — 예: 주파수 분배 주제에서 전파법 시행령 클릭 시 '주파수 분배' 관련 조문. (직접 엣지 있을 때만 검색하면 계열 간접 노드는 전체 요약만 떠서 '해당 내용 아닌 전체가 나온다'는 피드백.) 원문 보기(모달)·AI 자문 프리필 버튼.
- **전체 인용망 모드의 클릭은 드릴다운**: 법령 노드 클릭 → 그 법령 중심의 실제 인용·계열 관계 서브그래프로 전환(약한 엣지 포함 전부) + **법령 전체 요약은 펼쳐서** 표시, 상태바에 "← 전체 인용망으로" 복귀 링크. 주제 노드 클릭 → 주제 포커스로 전환(셀렉트 동기화). 즉 요약의 접힘/펼침은 모드 따라 반대: 주제 맥락=접힘, 전체망 드릴다운=펼침. (운영자 피드백 2건 반영)
- **질문 로컬 매칭(askLawMap)은 주제 노드에만·양방향으로**: 주제명을 단어로 분해해 그 단어가 질문에 실제로 들어있어야 후보로 인정(nameHits≥1, 점수≥3), 질문 키워드가 설명에 있으면 동점 해소용 가점. '관련·법령·규정·무선·전파·주기' 등 도메인 흔한 단어는 LAWMAP_MATCH_STOP으로 제외. 확실한 매칭이 없으면 **엉뚱한 그래프를 그리지 말고** 현재 화면 유지 + "AI로 생성" 제안. (초기엔 전체 노드 단일 키워드 부분일치라 '무선국'·'허가' 한 단어에 무관한 고시가 매칭돼 주제 불명 그래프가 떴음 — 운영자 피드백 3)

## 대시보드 (GitHub Pages)

- URL: https://youjinwoong.github.io/radio-policy-ai/
- **수정 배포 시 index.html 캐시 버스터 `app.js?v=`·`styles.css?v=` 갱신 필수 (현재 `app.js?v=20260729a` / `styles.css?v=20260723b`)** — CSS 고칠 때 styles.css 버스터도 갱신해야 사용자 브라우저가 새로 받음
- 아이콘은 Tabler Icons webfont(ti ti-*) — 존재하는 이름만(없으면 빈칸 렌더).
- 메뉴: [모니터링] 보도자료·뉴스 / Daily Briefing / 기술 용어 · [자문] AI 자문 / 보고서 초안 제안 / **법령 관계도(lawmap)** · [법안 동향] 국회 법안 / 행정부 입법예고·법령 개정 / 법령 DIFF 분석 · [지식 베이스] 국내 법령·고시(조문 원문) / **실무 안내(kb 요약·실무 203건)** / ITU-R / 정부 보도자료 / 추가 지식 입력 / 설정 / 운영 상태(크롤·브리핑·heartbeat 한눈 점검) — ※ lawmap은 질문·AI 생성 성격이라 자문 그룹에 배치(데스크톱). 모바일은 자문 서브메뉴가 없어 지식베이스 서브메뉴(law-sub)로 접근(pageTobn=bn-law).
- 뉴스 중요도: 화면 라벨 "🔴 중요/🟡 보통/🟢 참고", 내부값·DB·코드는 '긴급/보통/참고'. 수정 시 news_feed 갱신+importance_feedback 기록+당일 브리핑 🔴 동기화. 잠금=60일 삭제 제외, 삭제=영구+deleted_news 기록.

## 알림 채널

**① 운영자 채널** (기존, `TELEGRAM_BOT_TOKEN` / TG 344506450)

```
매일 06:00 KST     | 텔레그램(분석 제외)·이메일(분석 포함) | you.jinwoong@gmail.com / TG 344506450
기사 0건인 날      | 텔레그램(🕊️ 신규 뉴스 없음 — 시각무관 1일1회, 크롤러 정상 안내)
긴급 기사 즉시     | 텔레그램·이메일
신규 입법예고 즉시 | 텔레그램(건별)·이메일(Resend 묶음)  (gov_notice_crawler 17:00)
법령·고시 신규/개정| 텔레그램  (첫 실행 베이스라인은 생략)
국회 법안 단계변경 | 텔레그램
```

**② 구독자 봇 채널** (2026-08-01 신설 — `정책AI 도우미` @radio_policy_law_ai_bot, `SUBSCRIBER_BOT_TOKEN`)

```
브리핑·긴급·법안   | 구독자가 고른 시각(6~12시)에 3종을 한 번에 발송 — 즉시 발송 없음
                   | 요일 선택(매일/평일만), 항목별 on·off. 항목 전부 끄면 수신 없음
조문 조회 /law     | "OO법 N조" 원문 즉답 (LLM 없음, 비용 0)
AI 자문 /ask       | 운영자 승인(chat_id별 1회) + 일일 20회 상한. 건당 100~400원
```

- **운영자 채널과 완전히 별개**다. 운영자는 종전대로 즉시 알림을 받고, 구독자만 정시 수신.
- 긴급·법안은 크롤러가 `subscriber_queue`에 적재만 하고 정시에 묶여 나간다 — 즉시 발송이 없으므로
  '야간 무음' 같은 토글이 필요 없고, 알림 개수도 하루 1회로 고정된다(#44 취지 유지).
- 브리핑 하단에 **기준 시각**을 표기한다("오늘 06:05 기준"). 12시 수신자가 06~12시 뉴스가
  빠진 것을 누락으로 오해하지 않도록(그 건은 다음날 브리핑에 포함).

## 표준 작업 패턴

```bash
# 본문 수집 의존성(PC 최초 1회): pip install trafilatura

# 코드 수정 후 배포 (캐시 버스터 갱신 필수). git add는 항상 파일명 지정 (-A/. 금지)
git add [파일명] && git commit -m "설명" && git push origin main
# 원격 검증: git show HEAD:index.html | findstr "app.js?v="

# 세션 커밋: 3단계 검증을 붙이면 허용 (2026-07-31 완화 — 배경역사 #37).
#   ① 커밋 전 대상 파일 끝(tail) 온전 확인  ② git add는 명시 파일명만  ③ 푸시 후 원격-로컬 대조
#      (git fetch → rev-parse 일치 + git diff origin/main -- <파일> 0줄 + 원격 파일 끝줄 확인)
#   ③에서 불일치가 나오면 절대 재푸시하지 말고 원인 규명 먼저(과거 사고: 마운트 절단 파일이 그대로 푸시됨).
#   구형 Cowork 샌드박스(마운트 stale/절단 이력)에서는 여전히 커밋 금지 — 검증 ①③이 통과할 수 없는 환경이었음.
#   여러 세션이 같은 repo 동시 커밋 금지는 그대로 유지(stale 되돌림 위험).

# 크롤러 수동 실행
python crawler.py            # 뉴스("[네이버 뉴스] N건 수집" N>0 확인). NAVER_CLIENT_ID/SECRET 필요
python law_crawler.py        # 법령·고시(LAW_OC_KEY)
python assembly_crawler.py   # 국회 법안(ASSEMBLY_API_KEY)
python gov_notice_crawler.py # 정부 고시·입법예고(한국 IP). "[입법예고] N페이지:M행 스캔, 누적 매칭 K건"
python refetch_content.py    # 본문 재수집(한국 IP, trafilatura)
python resend_briefing.py [날짜]              # 브리핑 재발송
python upload_law_pdf.py 파일 "문서명" 고시    # 법령/고시/ITU-R 업로드 (업로드 시 PDF 편집흔적 자동 정리 — clean_pdf_artifacts)
python backfill_embeddings.py                 # 임베딩 백필(document_chunks)
python backfill_report_embeddings.py          # 보고서 샘플 임베딩 백필(report_samples)
python backfill_term_details.py               # 기술용어 상세 백필(tech_terms 설명·개념도·관련용어, 빈 것만. 모델은 app.js와 동일하게 유지)
python build_law_citation_graph.py            # 법령 관계도 인용망 재구축(citation·family 엣지만 — 멱등. 새 법령 업로드 후 실행)
python clean_pdf_artifacts.py [--apply]       # 기존 document_chunks PDF 편집흔적 일괄 청소(dry-run 기본. content만, embedding 유지)
python sync_kb_to_bundle.py [--dry-run]       # 웹 생성 OKF(DB) → regulatory-kb 번들 역동기화(월 1회 권장, import_regulatory_kb 전 필수)
python law_watch.py [--dry-run|--no-notify]   # 법령 현행화 감시(등재본 vs 법제처 현행본 대조 + 시행예정본 발견 → 알림). GitHub Actions 매일 11시
python itu_rec_watch.py [--dry-run]           # ITU-R 권고 개정 감시(보유 판 vs ITU "In force" 판 대조 → 알림만, PDF 자동 수집 없음). GitHub Actions 매월 1일 12시. 감시 대상은 DB에서 읽어 하드코딩 없음 (#49)
python law_sync.py --list                     # 현행화 대상 목록
python law_sync.py --all-outdated             # 개정 감지분 일괄 현행화(조문 API 취득→청킹→등재→구버전 정리→임베딩 백필)
python law_sync.py --pending                  # 시행예정본 전건을 status='pending'으로 적재(자문 검색 제외 상태로 보관)
python law_sync.py --promote                  # 시행일 도래분을 current로 승격(GitHub Actions 매일 자동 — 수동 실행 불필요)
python import_regulatory_kb.py --only <path조각> [...]   # OKF 요약 일부만 재적재(전량 재임베딩 방지). --dry-run으로 대상 확인 후 실행
```

## 법령 자동 현행화 (law_watch / law_sync, 2026-07-29 신설)

수동 업로드로만 유지되던 지식베이스를 **법제처 DRF API 기준으로 자동 추적**한다. 조문을 API로 직접 받으므로 **PDF 다운로드·업로드가 불필요**하고, 조문 단위 청킹이라 article_no가 PDF 추출본보다 정확하다.

```
[매일 11시] law_sync.py --promote   시행일 도래한 pending → current 승격(+직전 current → superseded)
            law_watch.py            지식베이스 스캔(동적 발견) → 법제처 현행본 대조
                                    + 시행예정 통합본 전건을 law_pending에 기록 → 텔레그램 알림
[개정 감지] 대시보드 설정 탭 '법령 현행화 상태'에서 확인
[현행화]   PC에서 law_sync.py --all-outdated  → 조문 취득·등재·구버전 정리·임베딩 백필
[예정본]   PC에서 law_sync.py --pending       → 시행예정본을 status='pending'으로 적재
[후속]     build_law_citation_graph.py (인용망) / OKF는 초기=세션, 이후 개정분=승인 훅 API 자동
```

- **감시 대상은 고정 목록이 아니라 매 실행 자동 발견** — 대시보드 업로드/add_law.py/세션 어느 경로로 추가하든 다음 실행부터 자동 편입. 등록 누락으로 인한 무음 미감시를 원천 차단(가드레일 #18·#22 계열).
- **감시 대상은 `status='current'`만.** 구버전·시행예정본까지 긁으면 그것들이 법제처 현행본과 달라 매번 '개정 감지'로 오탐하고, `--all-outdated`가 이미 최신인 법령을 다시 받아온다.
- **버전 상태**: `document_chunks.status` = `current`(자문 검색 대상) / `pending`(시행예정본, 검색 제외·보존) / `superseded`(구버전, 최근 3버전만 보존). 검색 함수 `match_chunks_semantic`·`search_chunks_trgm`에 `only_current` 파라미터(기본 true) — kb_chunks의 동일 패턴.
- **⚠ 검색 함수에 인자를 추가할 때 반드시 구 시그니처를 DROP할 것.** 인자 개수가 달라지면 `CREATE OR REPLACE`는 교체가 아니라 **새 오버로드 생성**이다. 호출부가 옛 인자 수로 부르고 있으면 필터 없는 구 오버로드가 조용히 계속 쓰인다(#31 후속 사고 — 구버전 조문이 자문 근거로 유입됐다). 호출부에서도 `only_current: true`를 **명시적으로** 넘긴다.
- **자문 RAG 3경로 전부에 필터가 걸려 있어야 한다** — 시맨틱·trgm은 RPC 인자로, 키워드 `ilike`는 `.eq('status','current')`로. 한 경로만 빠져도 구버전이 유입된다.

### 시행예정본(law_pending) — 다단 시행 수용

법령 하나에 시행일이 여러 개 걸리는 일이 흔하다(정보통신망법: 2026.9.11 / 2026.10.1 / 2027.4.1). `law_watch`의 `pending_*` 3칼럼은 법령당 1건만 담으므로 **`law_pending` 테이블(1:N)이 정본**이고, `pending_*`는 대시보드 배지용 요약(가장 이른 1건)일 뿐이다.

- **식별자는 (MST, 시행일)** — 같은 MST가 시행일별로 다른 통합본을 갖는다(정보통신망법 MST 285199 → 20261001 179조 / 20270401 180조). 조문 취득은 `target=eflaw` + `MST` + **`efYd` 필수**(efYd 없이 부르면 빈 응답).
- **같은 시행일에 개정법률이 여러 건이면 통합본 본문은 동일하다** — 국가재정법 20260811의 MST 285521/283171은 조문 137개·본문 해시가 일치했다. 시행일로 묶고 일련번호가 가장 큰 1건만 남긴다.
- **행정규칙은 eflaw가 없다.** admrul 검색이 현행본과 시행예정본을 **함께** 돌려주므로 결과에서 시행일 > 오늘 인 행을 고른다. 현행 선택도 `현행연혁코드`가 비어 있는 경우가 많아 **목록 순서가 아니라 시행일로 판정**해야 한다(순서에 기대다 미래본을 현행으로 등재한 적합성평가 고시 사고).
- **이미 등재된 예정본은 재적재하지 않는다.** 운영자가 PDF로 올려둔 시행예정본은 doc_name 끝에 `.pdf`가 붙는다 — 중복 생성 대신 기존 문서에 연결한다.
- **승격은 자동**(`--promote`, 매일 11시). 없으면 시행일이 지나도 자문이 옛 조문을 현행으로 답한다.
- `sync_state` = `detected`(발견, 미적재) / `loaded`(조문 등재됨) / `promoted`(시행 도래·승격) / `obsolete`(법제처 목록에서 사라짐).

### 자문 답변의 시행예정 반영 (Phase 3)

자문 RAG는 현행 조문만 검색한다(`only_current=true`). 여기에 **인용된 조문의 시행예정 개정본**을 별도 컨텍스트 블록으로 덧붙여 "현행은 A, 언제부터 B" 답변이 가능하게 한다. `buildPendingContext()`(app.js) → RPC `pending_versions_for_docs`(법령별 시행 일정) + `fetch_pending_articles`(조문 원문).

- **매칭은 반드시 (문서, 조번호) 쌍으로.** 문서 목록과 조번호 목록을 따로 넘기면 교차곱이 되어 시행령 제58조의2를 인용했는데 본법 제58조의2가 딸려 오고, 보도자료 청크의 제6조가 정보통신망법 본법 제6조를 끌어온다.
- **조문 매칭 키는 조번호만.** `article_no`에는 조문 제목이 붙어 있어("48조의3(침해사고의 신고 등)") 제목이 개정되면 매칭이 깨진다(정보통신망법 제47조의7 "특례"→"차등적용 등"). 번호만 쓰면 현행 조문의 100%가 대응본을 찾는다.
- **짝짓기 축은 `law_pending.watch_doc_name ↔ doc_name` 문자열 조인.** `law_id` 조인은 못 쓴다 — current 문서의 **97%(256/263)가 PDF 업로드본이라 law_id가 NULL**이고 성립하는 쌍이 3쌍뿐이다.
- **현행 ↔ 시행예정의 문자열 diff는 하지 말 것.** 현행 등재본 15쌍 중 12쌍이 PDF 추출본이라 줄바꿈·따옴표·날짜 표기(`2015. 1. 20.` vs `2015.1.20`)가 API본과 달라 **위양성이 100%** 난다(전파법은 130개 조문 전부가 '변경'으로 나온다). 양쪽 원문을 나란히 주고 판단은 모델에 맡기며, 프롬프트에 "표기 차이뿐이면 개정이 아니다"를 명시한다. **시행예정본끼리의 비교는 전부 API 적재본이라 신뢰 가능** — 같은 조문이 여러 시행일에 걸쳐 본문이 같으면 중복 제거에 쓴다.
- **총량 상한 24,000자.** 과태료 조문처럼 긴 조문 2건만으로 17KB가 된다. **조문 중간에서 자르지 말 것**(모델이 잘린 문구를 인용한다) — 조문 경계에서 끊고 생략 건수를 프롬프트에 남긴다.
- 페일소프트: 조회 실패 시 빈 문자열 반환, 자문은 현행 기준으로 정상 동작.
- 답변 하단에 '시행 예정 반영' 배지를 띄워 답변이 현행 기준임을 가시화한다.
- **보고서 초안 생성 경로에도 동일 적용.** 보고서는 임원 보고로 나가므로 "현행은 X"만 쓰면 시행 임박 개정을 빠뜨린 문서가 된다. 참고 출처 목록에 `시행예정: <법령> <시행일>`이 함께 남는다.
### PDF 등재본의 API 재적재 (`law_sync.py --reingest`)

PDF에서 추출해 올린 등재본은 **단어 중간에 줄바꿈이 들어가 키워드 검색이 깨진다.** 전파법은 197청크 중 188청크(95%)가 그 상태였고, `가격경쟁`이 `가격\n경쟁`으로 잘려 `ilike` 검색에 걸리지 않았다. 조문 단위가 아닌 800자 단위 청킹이라 `article_no`도 부정확하고 `law_id`도 비어 있다.

```bash
python law_sync.py --reingest-laws --dry-run   # 법률 계열 후보 점검
python law_sync.py --reingest-laws             # 실행. --force로 이미 API본인 문서도 재취득(부칙·별표 보완)
python law_sync.py --reingest --doc-name "<문서명>"   # 1건만
```

- **재적재로 잃는 것은 없다.** API 응답에는 조문뿐 아니라 **부칙과 별표가 모두 들어 있다**(§조문 취득 범위 참조). 반대로 PDF본은 표가 열 단위로 뒤섞여 사실상 판독 불가다.
- 시행령·시행규칙·고시도 같은 방식으로 재적재할 수 있다(별표가 함께 들어온다). 다만 문서 수가 많으니 손상률이 높은 것부터 단계적으로 할 것.
- **안전장치 2종이 스크립트에 내장돼 있다**: ①`위반횟수별|행정처분기준|과태료의 부과기준|1차 위반`이 검출되면 거부(`--force`로만 강행) ②손상률 30% 미만이면 이미 API본으로 보고 건너뜀(API본도 항·호 줄바꿈으로 몇 %는 잡힌다 — 정보통신망법 211청크 중 9).
### superseded 정리 기준 — 두 종류를 구분할 것

`superseded`에는 성격이 다른 두 가지가 섞인다. 뭉뚱그려 "이력 보존"으로 두면 읽히지도 않는 데이터가 계속 쌓인다.

| 유형 | 판별 | 처리 |
|---|---|---|
| **같은 판의 PDF 중복본** | 법령번호·시행일이 현행본과 **동일** | **삭제.** 법령이 개정된 게 아니라 추출 방식만 다르다 — 이력이 아니다 |
| **법령번호가 다른 구버전** | 현행본과 법령번호가 다름 | **유지**(최근 2~3버전 보존 정책) |

**글자수 비교만으로 판단하지 말 것.** PDF본이 더 커 보이는 이유는 대개 내용이 아니라 잡음이다 — ①**머리말**(`[시행 2016. 10. 21.] [국립전파연구원공고 제2016-62호…] 국립전파연구원(전파시험인증센터), 031-644-7492`, 100~150자) ②**추출 중복**(같은 구절이 두세 번 반복) ③쪽번호·`[전문개정 …]` 주석. 실제로 "API가 더 작은" 22건을 실물 대조했더니 **전부 머리말+중복이었고 조문 본문 누락은 0건**이었다. 공백만 제거하고 비교하면 이 잡음이 그대로 남으니, 차이가 나면 **실물을 열어 확인할 것**.

**문서명 표기 차이로 매칭이 새는 것도 주의.** 소관부처 접두(`(과학기술정보통신부) 방송통신발전기금…`), 기관명 개명(`산업통상자원부고시` → `산업통상부고시`), 공백 유무(`규정 (과기정통부훈령)`)로 같은 판이 다른 문서처럼 보인다. **법령명 핵심어(공백 제거) + 법령번호 + 시행일**로 대조해야 3건이 더 잡힌다.

삭제 전 반드시 **공백 제거 기준으로 API본 ≥ PDF본**임을 확인한다. PDF본이 더 큰 경우가 있는데 원인은 두 가지다 — ①국가법령정보센터 인쇄본이 현행 조문과 **시행예정 조문을 중복 수록**(전파법·전기통신사업법 등 대형 법률. 지금은 시행예정본이 `pending`으로 분리돼 있으므로 삭제해도 무방) ②조건표·붙임이 **API에서 이미지로만 와서 실제로 빠진 경우**(전력선통신 붙임, 신고면제 무선기기 조건표 등 — 이건 남길 것).

```sql
-- 같은 판의 PDF 중복본 중 삭제해도 안전한 것(API가 상위집합)
with s as (select regexp_replace(regexp_replace(doc_name,' \[PDF원본\]$',''),'\.pdf$','') base,
                  doc_name pdf_doc, count(*) n,
                  sum(length(regexp_replace(content,'\s','','g'))) pdf_chars
           from document_chunks where status='superseded' group by 1,2),
     c as (select doc_name, sum(length(regexp_replace(content,'\s','','g'))) api_chars
           from document_chunks where status='current' group by 1)
select s.pdf_doc, s.n from s join c on c.doc_name=s.base where c.api_chars >= s.pdf_chars;
```

**삭제는 배치로**(5,939행을 한 번에 지우면 timeout), **삭제 전 `law_watch`·`law_pending` 참조가 없는지 확인**할 것. 2026-07-30 정리 실적: 총 **97건 6,064청크 제거**(약 24MB). superseded가 8,588 → **2,461청크 / 7문서**로 감소했고, 남은 것은 전부 법령번호가 다른 진짜 구버전이다.

> **PDF본은 되돌릴 수 없다**(운영자 원본 파일이 있어야 재생성). API본은 언제든 재취득 가능하다 — 이 비대칭 때문에 삭제 전 상위집합 여부를 반드시 실측할 것.

- **구본은 삭제하지 않는다.** 문서명이 같으면 뒤에 ` [PDF원본]`을 붙여 `superseded`로 내린다(되돌릴 수 있게). 이미 API본을 다시 받는 경우(부칙·별표 보완 등)는 버전이 바뀐 게 아니므로 사본을 만들지 않고 같은 문서명 안에서 내용만 교체한다.
- **⚠ 재적재는 순차로 실행할 것. 병렬 금지.** 6개 프로세스로 나눠 돌렸더니 Supabase가 `statement timeout(57014)`을 다발로 냈고, 그 결과 **구본만 강등되고 신본 등재가 실패해 현행 청크가 0이 된 문서가 3건** 생겼다(자문에서 그 법령이 통째로 사라진 상태). `--shard i/n`은 남았을 때 나눠 쓰라고 만든 것이지 동시 실행용이 아니다 — 게다가 대상 목록을 매 실행 재계산하므로 회차마다 샤드 구성이 바뀌어 재시도 추적도 안 된다.
- **처리 순서: 신본 등재 → 그 다음 구본 강등.** 반대로 하면 삽입이 중간에 실패했을 때 검색 공백이 생긴다. 문서명이 같아 충돌하는 경우에도 구본을 `[PDF원본]`/`[교체중]`으로 **옮기기만 하고 status는 current로 둔 채** 신본을 넣고, 성공한 뒤에 강등·삭제한다.
- **사고 후 점검 쿼리** — `law_watch`가 가리키는 문서에 현행 청크가 없는 건이 있는지 반드시 확인:
  ```sql
  select w.doc_name from law_watch w
  where w.watch_status='watching'
    and not exists (select 1 from document_chunks c
                    where c.doc_name=w.doc_name and c.status='current');
  ```
- **대량 문서는 삭제·갱신을 배치로.** 800청크가 넘으면 한 번에 처리 시 `statement timeout(57014)`이 난다. 페이지네이션은 반드시 **id 커서**로 — limit만 걸고 처리한 id를 메모리에서 제외하면 같은 200행이 계속 조회되다 빈 목록이 되어 **조용히 절반만 갱신된다**(지방세법 860청크 중 317건만 강등된 사고).
- 재적재 후 `law_pending.watch_doc_name`이 새 문서명으로 자동 이관된다(시행예정 연결 유지). **인용망 재구축(`build_law_citation_graph.py`)은 수동으로 한 번 돌릴 것.**
- **문서명 관례가 매칭의 전제**: `법령명(법종)(제N호)(YYYYMMDD)`. 관례를 벗어나면 `unmatched`로 뜨고 수동 확인 필요. 법종 괄호가 아예 없는 문서(보도자료 등)는 자동 `excluded`.
- **기관명 변경 대응**: `ORG_ALIASES`(방송통신위원회→방송미디어통신위원회 등)로 1차 검색 실패 시 재검색. 이 경우 법령명 자체가 바뀌므로 구버전 정리는 감시가 지목한 문서명(prev_doc_name)으로 처리한다 — 빠뜨리면 구버전이 current로 남아 자문이 옛 규정을 답한다.
- **타법개정 헤더 번호 함정 — "같은 번호의 두 문서"는 오류가 아닐 수 있다.** 현행본 헤더의 발령번호는 마지막 **개정 수단**의 번호다. 제2026-10호는 '신고면제 무선설비 기술기준' 고시이면서, 그 부칙이 타법개정한 '적합성평가 고시' 현행본의 헤더 번호이기도 하다. 또 법제처 현행 목록에서 **[예] 배지 행은 시행예정본 정보를 표시하므로 현행본 번호가 숨는다** — "검색 목록에 없음 = 유령"으로 단정하지 말고 연혁 탭·운영자 보유 PDF·타 문서의 부칙 기록으로 삼각 확인할 것(실제로 이 단정 때문에 정상 OKF를 삭제 직전까지 갔다).
- **시행예정본 OKF는 [시행예정 YYYY.M.D.] 표기로 남긴다.** 같은 계보에 현행본과 시행예정본이 공존하면(적합성평가 제2026-10호본 ↔ 제2025-56호본) 시행예정본을 지우거나 superseded로 내리지 말고, title 접미 `[시행예정 …]` + 요약 첫머리 ⚠️ 배너("시행일까지는 현행판 ○○를 근거로 답할 것")로 표시한다. 시행일이 지나면 배너를 떼고 구판을 superseded로 내린다.
- **재적재 후 반드시 정합성 점검.** 실행이 끝났다고 끝난 게 아니다 — 아래 4종을 확인한다.
  ```sql
  -- ① law_watch가 가리키는 문서에 현행 청크가 없는가(구본만 강등된 공백)
  select w.doc_name from law_watch w where w.watch_status='watching'
    and not exists (select 1 from document_chunks c where c.doc_name=w.doc_name and c.status='current');
  -- ② chunk_index 중복(재시도가 만든 중복 삽입) — status 구분 없이 전수로 볼 것
  select status, doc_name from document_chunks group by 1,2
   having count(*) > count(distinct chunk_index);
  -- ③ 임시 접미가 current로 남았는가
  select distinct doc_name from document_chunks where status='current'
    and (doc_name like '%[교체중]' or doc_name like '%[PDF원본]');
  -- ④ 부분 삽입(배치 경계에서 끊긴 문서). 삽입 배치가 50이므로 청크 수가 50의 배수면 의심
  select doc_name, count(*) from document_chunks where status='current' and law_id is not null
   group by 1 having count(*) % 50 = 0;
  -- ⑤ 감시 사각지대 — 현행 문서인데 law_watch에 행이 없는 것
  select distinct c.doc_name from document_chunks c
   where c.status='current' and c.doc_category not in ('ITU-R','보도자료','추가지식','기타')
     and not exists (select 1 from law_watch w where w.doc_name = c.doc_name);
  -- ⑥ 임베딩 누락 (재적재를 --no-backfill로 돌린 뒤 백필을 안 하면 남는다)
  select doc_name, count(*) from document_chunks where embedding is null group by 1;
  -- ⑦ 부칙·별표 기능 추가 전에 적재된 문서가 남았는가
  select doc_name from document_chunks where status='current' and law_id is not null
   group by 1 having count(*) filter (where article_no like '부칙%') = 0;
  ```
  ②는 `current`만 보면 놓친다(`superseded`에서 2건이 뒤늦게 나왔다). ⑦은 도중에 기능을 추가하면 그 전에 처리된 문서가 구버전 상태로 남기 때문이다(실제로 6건이 그랬다).

  **④가 가장 위험하다.** 대한민국 주파수 분배표는 API가 750,112자(1,089청크)를 정상적으로 주는데도 DB에는 **150청크(배치 3개)만** 들어간 채 방치돼 있었다. 삽입 도중 timeout이 났고, 이미 `law_id`가 붙어 있어 이후 재적재 대상에서도 빠져 아무도 몰랐다 — 이동통신 대역과 K주석 전체가 자문에서 빠져 있었다. 지금은 `reingest_one`이 **삽입 후 저장 건수를 검증**해 다르면 예외를 던진다.

  **⑤는 stale 정리의 부작용이다.** "신본이 있으니 구 `law_watch` 행은 stale"이라고 판단해 지웠는데, 실은 신본 등재가 실패해 새 행이 만들어지지 않은 상태였다. 그 문서는 감시 대상에서 통째로 사라진다 — **law_watch 행을 지우기 전에 새 doc_name의 행이 실제로 있는지 확인할 것.**

- **큰 문서에 `--force` 재시도를 반복하지 말 것.** 1회차가 성공해도 2회차가 같은 문서를 다시 처리하다 timeout이 나면, 온전한 데이터가 `[교체중]` 이름에 남고 정식 이름에는 부분 삽입분만 남는다(주파수 분배표에서 실제 발생). 성공 로그(`검증 완료`)를 확인하고 멈출 것.
- **중간 실패는 재실행으로 자동 복구된다(2026-07-30 자가감사 후 보강).** ①`reingest_one`은 `[교체중]`/`[PDF원본]` 잔재를 감지하면 "손상률 30% 미만 스킵"을 무시하고 복구 경로로 진입한다(예전엔 API본으로 오인·스킵되어 수동 SQL로만 풀렸다). ②`sync_one`은 신본이 이미 등재된 상태로 재진입하면 그냥 건너뛰지 않고 **앞선 실행이 남긴 current 구본을 마저 강등하고 law_watch를 정리**한다 — 방송통신발전기금 규정(제2026-25호) 적재에서 1회차가 강등 단계 timeout으로 끊겼을 때 이 경로로 복구됐다. ③승격(`promote_due`)은 **신본 current 먼저, 구본 강등은 그 다음**(중간 실패 시 검색 공백 대신 이중 current — 안전한 쪽으로 실패).
- **임베딩 백필용 부분 인덱스 3개를 지우지 말 것** — `document_chunks`/`kb_chunks`/`report_samples`의 `(id) WHERE embedding IS NULL`. 없으면 백필 대상 조회가 Seq Scan(전수 스캔, 5초+)이라 잦은 `57014`/500의 원인이 된다(EXPLAIN 실측 5,137ms → 0.061ms). 대량 삭제·갱신 뒤에는 `VACUUM ANALYZE document_chunks`를 한 번 돌릴 것(단독 문장으로 — 트랜잭션 안에서는 실패한다).
- **재적재 불가 사례가 있다.** 법제처에 등록돼 있어도 `조문내용`·`부칙`이 빈 문자열이고 **첨부파일만** 있는 경우가 있다(2012년 '공고' 계열). 이때는 `조문 취득 결과가 비어 있음 — 중단`으로 끝나며 재시도로 해결되지 않는다 — PDF 등재본을 그대로 두는 것이 맞다.
- **조문 취득 범위**: `law_sync.py`는 **조문 + 부칙 + 별표**를 모두 가져온다. 응답의 `조문.조문단위`, `부칙`, `별표.별표단위` 세 곳을 읽어야 한다 — 처음에 조문만 읽어 부칙이 통째로 빠졌고(9건 중 8건), 그 상태로 "API는 별표를 주지 않는다"고 잘못 단정했다.
  - **부칙**은 응답 모양이 두 가지다. 법령은 `부칙단위[{내용,번호,일자}]`, 행정규칙은 `{부칙내용:[...], 부칙공포번호:[...], 부칙공포일자:[...]}` 병렬 배열.
  - **부칙은 최근 15건, 1건당 6,000자 상한.** 정부조직법처럼 개편이 잦은 법은 '다른 법률의 개정'이 수백 개 법률을 나열해 부칙만 1,131청크가 된다(조문의 20배). 시행일·경과조치·적용례는 부칙 앞머리에 있다.
  - **별표**는 `별표.별표단위`에 표 본문까지 온다(전파법 시행령 43건, 적합성평가 고시 30건).
- **OKF 방침**: 초기 일괄 정비는 세션에서 무료 작성, 이후 개정분만 대시보드 승인 훅이 API 자동 생성(배경역사 #29·#31).

### 법령 개정 시 OKF 요약 갱신 절차(조문 현행화 이후)

조문(`document_chunks`)이 현행화돼도 **OKF 요약(`kb_documents`)은 자동으로 따라오지 않는다.** 요약이 옛 판을 설명하면 자문이 폐지된 조문을 근거로 답한다 — 조문 현행화와 반드시 짝으로 처리할 것.

1. `document_chunks`에서 신판 조문을 읽고 **번들 md 파일**(`regulatory-kb/…`)을 갱신한다. DB를 직접 UPDATE하지 말 것 — 번들이 정본이고, 다음 `import_regulatory_kb.py` 실행이 DB를 덮어쓴다.
2. `regulatory-kb/manifest.json`의 `law_number`·`enforcement_date`(및 기관명 개명 시 `title`·`dedup_key`·`law_type`)를 함께 고친다. 파일만 고치면 DB 메타는 옛 값 그대로다.
3. 제목에 호수가 들어간 고시(적합성평가·시험기관 계열)는 **버전당 파일**이 관례다 — 신판 파일을 추가하고 구판 항목을 `status: superseded` + `superseded_by`로 내린다. 제목에 호수가 없는 법령은 같은 파일에 덮어쓴다.
4. `python import_regulatory_kb.py --dry-run --only <path조각> …` 로 대상·청크 수를 확인한 뒤 `--only` 없이 재실행하지 말고 **같은 `--only`로 실제 적재**한다(전량 재적재는 100여 건을 다시 임베딩하고 그 사이 삭제-삽입 공백이 생긴다).
5. `kb_chunks`의 `embedding is null` 0건, 문서 수 = manifest `entry_count`인지 확인한다.
6. **조문 본문이 직전판과 같은데 호수만 오른 고시는 십중팔구 별표 개정이다.** 별표는 API로 받을 수 있으므로(`별표.별표단위`) 재적재된 문서라면 별표까지 대조할 것. 아직 PDF본인 문서는 옛 별표 수치를 새 판 것인 양 옮겨 적지 말 것.

### 법령 대량 신규 추가 (`add_laws_batch.py`, 2026-07-30 신설)

기존에 KB에 아예 없던 법령을 여러 건 한 번에 추가할 때 쓴다. `law_sync.py`/`law_watch.py`의 검색·조문취득·청킹·문서명 함수를 그대로 재사용하고, `sync_one`과 달리 "구버전 정리"가 없는 순수 신규 추가 전용이다. 스크립트 안에 `(검색명, doc_category, target힌트)` 목록을 하드코딩하고 `--dry-run` → 실적재 → `--only` 재실행(누락분) 순으로 쓴다.

- **검색명은 반드시 법제처 공식 명칭 그대로.** 딥리서치가 준 설명형 이름("수출 중고단말 확인방법 고시")으로 검색하면 `pick_exact`가 정확일치 필터에서 걸러내 **"검색 결과 없음"으로 오탐**한다(64건 전수조회에서 실제 발생) — 반드시 법제처 원문 제목으로 교체할 것.
- **첨부파일 전용 문서 가드 필수.** 법제처가 조문 대신 "자세한 내용은 상단 메뉴 버튼을 이용하십시오" 안내만 주는 문서가 있다(무선통신매뉴얼과 동일 유형 — §PDF 등재본 참조). 이 안내문이 유일한 조문이면 그대로 삽입하지 말고 명시적으로 실패 처리할 것 — 안 그러면 본문 없는 유령 청크가 들어간다.
- **"이미 보유" 판정은 반드시 정확 일치로.** 법령명 앞 N자 부분일치로 스킵을 판단하면 "법"과 "법 시행령", "설비 상호접속기준"과 "상호접속·공동사용 및 정보제공 협정 인가대상 기간통신사업자"처럼 접두어만 같은 별개 문서를 같다고 오판해 통째로 건너뛴다(53건 중 5건 실제 발생, 그중 하나가 재난로밍 딥리서치의 미확인 사항을 해소해준 문서였다). 완전일치(법령명 전체 + 다음 글자가 `(`)로만 스킵 판정할 것.
- 신규 법령은 OKF 요약도 함께 작성하는 것이 원칙이다(지침 §OKF 방침 — "초기 일괄 정비는 세션에서 무료 작성"). 조문 적재 → 정합성 점검 → OKF 작성(에이전트 분담 가능) → manifest 갱신 → `import_regulatory_kb.py --only` → **`build_law_citation_graph.py` 재구축**까지 한 세트로 처리한다(관계도 재구축을 빼먹으면 새 법령이 전체 인용망에 안 나타난다).

## 정부 보도자료 자동 수집 (press_ingest, 2026-08-02 신설)

6개 기관(과기정통부·전파연구원·방통위·전파관리소·ETRI·KISDI) 보도자료를 지식베이스에 영구 누적.
2024-01~ 백필 완료(1,027건·5,962청크 — 세션 검토로 무관 222건 프루닝 후 수치). 상세 경위는 배경역사 #53.

- **파일**: `press_ingest.py`(공용 모듈 — 기관 어댑터·추출기·등재·AI판정), `press_backfill.py`(일회성 백필),
  `export_press_sections.py`(검토용 섹션 추출). gov_notice_crawler.py 말미가 매일 17시 `run_daily()` 호출
  → 신규 있으면 `backfill_embeddings.py` 자동 실행.
- **매일 수집 = 전수 + AI 판정**: 각 기관 목록 1~2페이지의 최근 15일분을 키워드 없이 전부 내려받아
  Haiku가 제목+본문으로 관련성 판정(기준문=app_config.press_relevance_criteria). API 불가 시
  키워드(app_config.press_keywords) 매칭으로 폴백(fail-open).
- **백필/폴백 키워드는 제목 매칭**: press_keywords(2026-08-02 기준 33개, 대시보드에서 편집).
- **본문 추출 경로(기관별 실측)**: 과기정통부=상세가 스텁이라 **첨부에서 추출**(fn_download 3-인자 파싱 →
  `POST /ssm/file/fileDown.do` atchFileNo·fileOrd·fileBtn=A + **Referer 필수**; HWPX=ZIP의 Contents/section*.xml
  태그 제거, PDF=pdftotext) / 방통위·전파관리소=본문+첨부 PDF 병합 / ETRI·KISDI·전파연구원=HTML(trafilatura).
- **재실행 안전**: 섹션 헤더 dedupe(`## YYMMDD 제목` ilike) — 백필·델타를 몇 번 돌려도 중복 없음.
- **대시보드**: KB '정부 보도자료' 탭(기관 탭 + 수집 키워드 카드 + 원문 보기 버튼), 모니터링 탭 기관 필터.
  업로드 진입점은 제거(자동 수집 전환) — 수동 등재는 '추가 지식 입력'으로.
- **프루닝 방식**: 무관 자료 삭제는 섹션-청크 경계가 어긋나므로 **문서 전문 백업 → 섹션 제외 재조립 →
  재청킹 → 문서 단위 교체 → 재임베딩 → REINDEX** 순서로만 할 것(청크 직접 delete 금지).

## 점검 체크리스트 (요약 — 상세 경위는 배경역사 문서)

- **이상 의심 시 1차 점검**: 대시보드 설정 밑 **"운영 상태"** 탭 — 크롤러 heartbeat·뉴스 입력·오늘 브리핑·입법예고·국회 한눈. (배경역사 #16)
- **브리핑 미수신**: Actions(morning_briefing.yml) 확인→실패 시 "Run workflow" / 성공인데 미수신→`resend_briefing.py` / 09:40 후도 미수신→`briefing_backup_log.txt`. 본문 0건이어도 요약/제목 폴백으로 빈 브리핑은 안 나옴(배경역사 #16). **트리거·PAT·크롤러 heartbeat 다 정상인데 미생성이면 24h 내 신규 기사 0건을 의심** — 그날은 '🕊️ 신규 뉴스 없음' 통지+placeholder가 정상 동작(고장 아님). daily_crawl 로그 `[네이버 뉴스] N건`으로 'NAVER 키 만료(폴백만)' vs '진짜 뉴스 없음'(N>0·실패0) 가름. (배경역사 #17)
- **트리거 전부 무음 정지(크롤·브리핑·국회·법령 동시 미동작)인데 cron 잡은 다 succeeded**: PAT 권한/만료 의심. cron 잡 상태(net.http_post 비동기라 항상 succeeded)가 아니라 `net._http_response.status_code`로 dispatch 응답 확인 — 403=Actions 권한 부족, 401=토큰 무효, 204=성공. PAT 재생성했다면 Actions(R/W) 권한 누락 여부 확인. (배경역사 #18)
- **heartbeat(운영상태)는 멈췄는데 스케줄러 작업은 '준비/실행됨'이면 PC 꺼짐이 아니라 스크립트 크래시/오류**: 작업 스케줄러에서 *마지막 실행 결과* 확인(0x0 정상 / 0xC000013A 강제종료=크래시 / 0x1 일반오류) + 스크립트 로그(`refetch_log.txt`·`gov_crawler_log.txt`). 흔한 원인=cp949 이모지 print 크래시 또는 작업 동작 경로가 옛 폴더. 본문수집/입법예고가 같이 멈췄으면 1순위 의심. (배경역사 #19)
- **뉴스 미축적**: daily_crawl.yml 로그 "[네이버 뉴스] N건". N=0→NAVER 키 누락·만료(폴백만 돔) / N>0인데 신규0→cron 드롭, "Run workflow".
- **크롤·브리핑이 ~20초 만에 동시 실패(`RemoteProtocolError: Server disconnected`)**: supabase-py HTTP/2 끊김 → `sb_client.make_client`(HTTP/1.1)로 해결됨. 재발 시 `create_client` 직접 호출 파일 없는지 확인. 크롤은 성공인데 news 0·브리핑 빔이면 본문 미수집 → PC `python refetch_content.py` 실행 후 브리핑 재실행. (배경역사 #15)
- **입법예고 미수집**: DB law_type='lsAnc' 건수·MAX(created_at) 확인. `gov_notice_crawler.py` 로그. PC 의존(17:00).
- **AI 자문 "Failed to fetch"**: 무거운 질문 2분+ idle 끊김 → stream:true로 해결됨. 사내망 프록시·확장프로그램·F12 네트워크 확인.
- **보고서 초안 미생성·학습**: Claude 키 / report_samples 2편↑·"스타일 재학습" / embedding NULL→`backfill_report_embeddings.py` / report_directives 행 / 임계 +2건.

## 하지 말아야 할 것 (규칙 + 한 줄 이유 / 상세는 배경역사 문서)

- **API 키 하드코딩 금지(공개 repo)** — .env·GitHub/Supabase Secrets에만. (Voyage 키 유출 사례)
- **구독자 봇 토큰과 운영자 봇 토큰을 섞어 쓰지 말 것** — `SUBSCRIBER_BOT_TOKEN`(구독자용)과 `TELEGRAM_BOT_TOKEN`(운영자용)은 다른 봇이다. 바꿔 넣으면 구독자에게 운영자 알림이 가거나 그 반대가 된다. (배경역사 #51)
- **Supabase 콘솔에 시크릿을 붙여넣을 때 줄바꿈 혼입 주의 / Edge Function의 env는 반드시 `.trim()`** — 메모장에서 줄 단위로 복사하면 값 끝에 `\n`이 딸려 들어가고, 그러면 시크릿 비교가 조용히 어긋나 401만 반복된다(등록은 돼 있어 원인 파악이 어렵다). 값 검증은 콘솔의 SHA256 다이제스트와 로컬 해시를 대조. (배경역사 #51)
- **서버측 Anthropic 키로 `app_config.claude_key`를 재사용하지 말 것** — 그 값은 anon도 읽을 수 있어 브라우저에 노출되는 키다. Edge Function은 Edge Secrets의 `ANTHROPIC_API_KEY`만 쓴다.
- **`system_prompt.js`를 고친 뒤 `sync_system_prompt.py` 실행을 빠뜨리지 말 것** — 대시보드는 파일을 직접 읽지만 텔레그램 봇은 `app_config.system_prompt`를 읽는다. 안 돌리면 봇만 옛 프롬프트로 답하거나(미등록 시) 자문이 통째로 실패한다. (배경역사 #51)
- **긴급 fan-out을 억제·클러스터링 이전 목록에 걸지 말 것** — `crawler.py`의 큐 적재는 `suppress_repeat_alerts()`+클러스터링을 **거친 뒤** 호출해야 한다. 앞에 걸면 구독자에게 중복 알림이 쏟아진다. (배경역사 #44)
- **텔레그램 webhook은 어떤 오류에도 200을 반환할 것** — 비200이면 텔레그램이 같은 업데이트를 재전송해 무한 반복된다. 오류는 `console.error`로만 남긴다.
- **`X-Telegram-Bot-Api-Secret-Token` 검증을 제거하지 말 것** — webhook은 verify_jwt off라 이 검증이 유일한 관문이다.
- **조문 검색에서 `.pdf`·`.md` 문서를 제외하는 필터를 빼지 말 것** — 「실행계획(안).pdf」 같은 자료도 `article_no`("6조")를 갖고 있어 조문번호 유무만으로는 안 걸러진다. `doc_category`로도 불가(‘기타’에 고시와 박사논문이 섞여 있음). (배경역사 #51)
- **PostgREST 조회에 `limit`을 작게 주면서 정렬을 생략하지 말 것** — 정렬 없는 limit은 임의의 N건을 돌려준다. '폐업'으로 6건만 받았더니 위치정보법·지방세법이 자리를 채우고 정작 전기통신사업법 19조가 빠졌다. 넉넉히 받아 점수로 거를 것. (배경역사 #51)
- **파일을 통째로 다시 쓸 때 원자적 쓰기(임시 파일 → 교체)를 쓸 것** — 여는 순간 truncate되므로 쓰기 중 예외가 나면 0바이트가 된다. 실제로 `telegram-webhook/index.ts`가 그렇게 날아갔다(배포본에서 복구). (배경역사 #51)
- **kmcc.go.kr을 중앙전파관리소로 표기하지 말 것** — kmcc.go.kr은 방송미디어통신위원회(방통위 개편 후 새 도메인)로 kcc.go.kr과 동일 게시판 미러다(목록 상위 5건 완전 일치 실측). 진짜 중앙전파관리소는 **www.crms.go.kr**. 2026-08-01의 "kmcc=전파관리소" 정정 자체가 오정정이었다. (배경역사 #53)
- **MSIT 첨부 다운로드는 fn_download('atchFileNo','fileOrd','확장자') 3-인자 파싱 + POST fileDown.do + Referer 헤더 필수** — 셋 중 하나만 빠져도 0바이트/빈 응답이 조용히 온다. 상세 페이지 본문은 스텁이므로 첨부 추출 없이는 보도자료·입법예고 전문을 얻을 수 없다. (배경역사 #53)
- **보도자료 수집 키워드·AI 판정 기준문은 코드 상수가 아니라 DB(app_config)가 원본** — 코드의 FALLBACK은 조회 실패 시 비상용일 뿐이다. 기준을 바꿀 때 코드만 고치면 대시보드 편집분과 어긋난다. (배경역사 #53)
- **PostgREST는 요청당 최대 1,000행에서 자른다 — `.limit(2000)`도 1,000에서 잘린다** — 무정렬이면 어떤 1,000건이 올지도 임의라 "최근 것만 사라지는" 형태로 증상이 난다(보도자료 목록·상세가 실제로 그랬다). 대량 조회는 반드시 `order + range` 페이징. (배경역사 #53)
- **게시판 목록을 페이지 순회할 때 순환 방어를 넣을 것** — 마지막 페이지를 넘겨도 같은 내용을 반복 반환하는 게시판(ETRI)이 있고, URL에 페이지 번호가 박혀 'URL 신규' 판정으로는 못 거른다. 페이지의 제목 조합(fingerprint)이 재등장하면 종료. (배경역사 #53)
- **Supabase 파이썬 클라이언트는 `sb_client.make_client` 사용, `create_client` 직접 호출 금지** — supabase-py 2.31 httpx HTTP/2 keepalive 끊김(RemoteProtocolError: Server disconnected) 회피(HTTP/1.1 강제+재시도). 신규 스크립트도 동일 적용. (배경역사 #15)
- **워크플로 pip를 버전 무고정으로 되돌리지 말 것(`requirements.txt` 유지)** — 무고정 자동 최신화가 어느 날 갑자기 깨뜨림(HTTP/2 사고). 버전 올릴 땐 한 번에 하나씩 바꿔 Run으로 검증. (배경역사 #15)
- **GitHub PAT 재생성·교체 시 Actions(R/W) 권한 확인 누락 금지 / pg_cron 'succeeded'를 트리거 성공으로 믿지 말 것** — fine-grained PAT 필수권한은 Contents(R/W)+Metadata(자동)+Actions(R/W). Actions가 빠지면 git push는 되지만 workflow_dispatch는 403, 그런데 net.http_post가 비동기라 cron 잡은 succeeded로 찍혀 모든 트리거가 무음으로 멈춤. 교체 검증은 `net._http_response.status_code`(204=성공)로. (배경역사 #18)
- **모닝 브리핑 빈-브리핑 폴백(요약→제목)·`already_sent_today` 폴백 교체 허용 로직 제거 금지** — PC 꺼진 날 빈 브리핑 방지 + 본문 채워지면 정식본 자동 교체 핵심. (배경역사 #16)
- **기사 0건 무뉴스 통지(`_handle_no_news`)·`_NONEWS_PREFIX` placeholder·시각무관 1일1회 발송을 '09시 이전 무음 종료'로 되돌리지 말 것** — 무음 누락 오인 방지. placeholder는 기사 들어오면 정식본 자동 교체(폴백과 동일 패턴), 중복은 placeholder 존재로 1일1회 차단. `already_sent_today`의 `_NONEWS_PREFIX` 교체 허용도 유지. (배경역사 #17)
- **워치독을 'DB 신선도만' 보던 방식으로 되돌리지 말 것 / 크롤러 heartbeat(`system_health` 3종: last_crawl_run·last_gov_notice_run·last_refetch_run) 쓰기·`system_health` 테이블 삭제 금지** — '고장 vs 없음(주말·드문 입법예고)' 구분·오경보 방지·운영상태 탭 핵심. (배경역사 #16)
- **운영 상태 탭(`panel-opsstatus`·`loadOpsStatus`)·system_health anon select 정책 제거 금지** — 이상 시 1차 점검 화면. (배경역사 #16)
- **사이드바 `.sidebar { overflow-y:auto }` 제거 금지** — 메뉴가 많아 화면보다 길어지면 설정·운영 상태 등 하단 항목이 잘림. (배경역사 #16)
- **PC 로컬 스크립트(refetch_content.py·gov_notice_crawler.py 등)의 stdout/stderr UTF-8 강제(`sys.stdout.reconfigure(encoding="utf-8")`) 제거 금지** — 스케줄러는 출력이 cp949로 잡혀 이모지 print가 `UnicodeEncodeError`로 무음 크래시(heartbeat 못 씀→간이 브리핑). 수동 터미널(UTF-8)은 멀쩡해 오진 유발. 신규 PC 스크립트도 동일 적용. (배경역사 #19)
- **Windows 작업 스케줄러 작업의 동작 경로를 옛 폴더(`…\frequence\전파정책전문가`)로 두지 말 것 — `radio-policy-ai`로 유지** — 폴더 이전 후 경로 미갱신 시 구 bat·없는 스크립트(gov_playwright_crawler.py) 호출로 0x1 실패. (배경역사 #19)
- **전파정책_정부크롤러 작업의 StartWhenAvailable(놓친 실행 보충)·배터리 허용을 끄지 말 것** — 매일 17:00 1회 실행이라 PC가 그 시각에 꺼져 있으면(금요일 조기 퇴근·주말·연휴) 그날 수집이 통째로 빠지고 보충도 안 됨 → 다음 부팅 직후 자동 보충이 유일한 안전망. 2026-07-04~06 주말 공백으로 heartbeat 3일 경고 재발한 사고의 재발 방지책. (배경역사 #22 후속)
- **`.bat`은 ASCII+CRLF만 — 편집했으면 반드시 바이트로 검증(비ASCII=0·bareLF=0), git status를 믿지 말 것** — 한국어 로케일 cmd가 UTF-8 한국어+LF 배치를 오파싱해 `echo [%date% %time%]` 줄을 `time` 명령으로 실행→대화형 프롬프트 무한 대기→heartbeat 무음 중단. `.gitattributes`의 eol 정규화 때문에 working tree가 LF로 훼손돼도 git status는 clean으로 보여 git으로는 탐지 불가. (배경역사 #22)
- **PC 스케줄러 작업·배치에서 bare `python` 호출 금지 — Python312 전체 경로(`C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe`) 고정** — 공유 PC에 다른 Python(3.13)이 설치되면 PATH를 가려 bs4 등 ModuleNotFoundError로 매일 무음 실패. 패키지는 3.12에만 설치돼 있음. (배경역사 #22)
- **gov_notice_crawler.py를 GitHub Actions로 옮기지 말 것** — 정부 사이트 해외 IP 차단·입법예고 한국 IP 필요.
- **방통위 수집에 RADIO_KEYWORDS만 쓰지 말 것(`KCC_KEYWORDS` 유지)** — 방통위 보도자료는 재허가·이사 임명·위원회 결과 등 방송 거버넌스가 대부분이라 전파 키워드로 거르면 매칭 0건이 된다. 기술정책팀에 의미 있는 축은 단말기·지원금·스팸·이용자보호다. (배경역사 #51)
- **게시판 링크의 `;jsessionid=...` 제거를 빼지 말 것** — 안 떼면 실행할 때마다 URL이 달라져 같은 기사가 매번 신규로 저장된다.
- **입법예고 수집을 lsNm(제명) 키워드 검색으로 되돌리지 말 것** — 관련 예고 통째 누락. 전체목록 스캔+소관부처 보강이 정답.
- **입법예고 매칭의 "○○부 소관" 접두사 제거를 빼지 말 것** — 부처명 '정보통신' 글자 오탐 차단.
- **입법예고 요약 생성(backfill_opinion_summaries)·브리핑 summary 표시 제거 금지** — lsAnc는 gov_notice_crawler가 요약 단독 담당.
- **Daily Briefing "오늘" 배지를 UTC로 되돌리지 말 것** — KST 자정~09시 오판. KST(+9h) 유지.
- **parseBriefingContent 마크다운 처리·📢 블록 스타일링·🔗 링크화 제거 금지** — 기호 노출·링크 미클릭 문제 해결책.
- **crawl_naver_news를 HTML 스크래핑으로 되돌리지 말 것** — 0건 회귀(에러 없이) 사고. 공식 OpenAPI가 정답.
- **지식 수집에 `crawler.fetch_article_body()`를 쓰지 말 것 — 반환 본문이 `[:1500]`으로 하드 절단된다** — 뉴스 발췌용 함수라 상한이 박혀 있다. 웹 문서를 RAG 지식으로 넣을 땐 `trafilatura.extract(include_tables=True)`를 직접 호출할 것(전파사용료 페이지 3,255자가 잘린다). (배경역사 #40)
- **crms_guide_sync의 메뉴 링크를 하드코딩하지 말 것 / 분야는 `<title>` breadcrumb, 제목은 nav 링크 텍스트에서 각각 뽑을 것** — nav 순서로 분야를 추정하면 '방송업무'가 조사단속 하위로 붙고, 반대로 `<title>` 끝 조각을 제목으로 쓰면 '개요'가 3개 나와 파일명이 충돌한다. 링크 0건이면 사이트 개편 신호. (배경역사 #40)
- **crawl_msit(과기정통부)를 DOM 셀렉터 파싱으로 되돌리지 말 것 — 인라인 스크립트 정규식 추출 유지, 상세 URL에 `bbsSeqNo` 필수** — 2026-07 사이트 개편으로 목록 DOM이 빈 껍데기가 되어 수 주간 무음 0건이었다(파서는 죽어도 heartbeat는 정상). bbsSeqNo 없는 상세 링크는 200인데 본문이 "시스템 점검 안내"(소프트 차단). 로그의 `행 N개 스캔`이 0이면 개편 재발 신호다. 방통위 0건은 고장이 아니라 키워드 필터의 정상 동작(방송 안건 위주). (배경역사 #39)
- **Supabase 신규 프로젝트 생성 제안 금지** — 무료 슬롯 2개 모두 사용 중.
- **Sonnet으로 긴급도 분류 업그레이드 제안 금지** — Haiku+피드백 학습으로 충분.
- **Cowork 예약 태스크로 크롤러 재등록 금지** — 중복 실행.
- **news_feed 수동 정리 시 `AND locked=false` 필수.**
- **뉴스 목록(loadNews)은 전량 페이지네이션 조회(range 루프, PostgREST 서버 상한 1000행/요청) + 잠금 기사 별도 병합 유지 — limit 단건 조회로 되돌리지 말 것** — 한때 최신순 limit(500)이라 오래된 잠금 기사가 순위 밖으로 밀려 "지워진 것처럼" 보였다(실DB엔 생존 — 삭제 오인 신고의 실제 원인). (배경역사 #38)
- **news_feed 저장을 plain `insert`로 되돌리지 말 것 — `upsert(on_conflict='url', ignore_duplicates=True)` 유지(crawler.py·gov_notice_crawler.py 동일)** — url은 실DB UNIQUE라 plain insert는 중복 1건에 배치 전체가 실패해 그 회차 신규 기사 통째 유실. (배경역사 #23)
- **AI 자문 검색 병렬 실행(searchKeywords Promise.all·callClaude 보조 컨텍스트 5종 동시 시작)을 순차 await로 되돌리지 말 것** — 검색 6종 릴레이로 답변 시작 2~4초 지연 회귀. 프롬프트 조립 순서는 코드가 고정하므로 결과 동일. (배경역사 #23)
- **자문 뉴스 본문 매칭을 최신순 상위 N건(`order published_at desc limit 2`)으로 되돌리지 말 것 — 제목 가중 3·본문 가중 1 관련도 스코어링 유지** — 특정 이슈가 폭주한 날(예: KT 과징금 제재일) 발췌 3칸이 무관 기사로 잠식돼, 질문이 그대로 인용한 기사조차 프롬프트에 못 들어간다. 제목 목록(`limit 30`)도 최신순이라 그날 신규 49건에 밀려 함께 탈락했다. (배경역사 #35)
- **`extractNewsKeywords`(뉴스)와 `extractKeywords`(법령)를 합치거나 서로의 불용어를 섞지 말 것** — 뉴스 불용어(`통신사`·`영향`·`분석해줘`)를 법령용에 넣으면 법령 RAG 검색이 깨지고, 반대로 법령용을 뉴스에 쓰면 `같은/지하철인데/통신사`가 뽑혀 이번 누락이 재발한다(`인데`가 조사 목록에 없어 본문 매칭 0건). 도메인어 절단 보호(`와이파이`의 끝 `이`를 조사로 오인) 분기도 유지. (배경역사 #35)
- **자문 뉴스 발췌를 일괄 600자로 되돌리지 말 것(1위 1,800자·2·3위 700자 차등 유지) / 출처에 제목 목록 30건을 넣지 말 것(본문 발췌분만)** — 600자는 기사 앞부분 수치는 살리고 뒷부분 최신 상황만 잘라내 답변을 옛 시점으로 후퇴시킨다(실측: `28㎓` 627자, `시범 운영` 1252자 지점). 근거로 쓰이지 않은 제목 목록을 출처로 표기하면 거짓 표기가 된다. (배경역사 #35)
- **자문 뉴스 발췌 뒤의 "수치 인용 우선" 지시를 제거하지 말 것** — 기사 본문이 프롬프트에 들어가 있어도 모델이 웹검색 쪽 옛 수치를 골라 쓴 사례가 있다(검색이 아니라 생성 단계 문제). 질문이 수치·순위 비교를 묻고 발췌에 그 수치가 있으면 매체·날짜와 함께 인용하게 강제한다. (배경역사 #35)
- **deleted_news·importance_feedback·feedback_rules 비우지 말 것** — 재수집 방지·학습용 영구.
- **report_samples·report_feedback·report_directives·report_style_rules 비우지 말 것** — 보고서 형식·개인화 학습 데이터(비우면 초기화).
- **보고서 개인화 채널(말로 지시·빨간펜·👍/👎·자동 재증류)을 단일 채널로 축소 금지** — "쓸수록 내 톤" 핵심.
- **callReportDraft·callClaude를 비스트리밍으로 되돌리지 말 것** — 2분+ 응답 idle 끊김 "Failed to fetch". stream:true 유지.
- **비스트리밍 Claude 호출에서 `data.content[0].text` 가정 금지 — Sonnet 5는 `thinking` 미지정 시 적응형 추론 기본 ON** — 응답 첫 블록이 빈 thinking 블록이 되어 `content[0].text`가 undefined(`reading 'trim'` 크래시) + 숨은 thinking 토큰이 max_tokens 잠식으로 출력 잘림. 기계적 추출(용어추출·법령DIFF 등)은 `thinking:{type:'disabled'}` 추가하고, 응답은 반드시 `content.find(b=>b.type==='text')`로 읽을 것. 스트리밍(자문·보고서)은 text_delta만 누적하므로 무관, Haiku는 적응형 기본 OFF이라 무관. Sonnet 4.6→5 전환(#27) 후 발생. (2026-07-23 용어추출 크래시·법령DIFF 무음 사고)
- **보고서 등록을 청킹하지 말 것** — 형식 학습용이라 전문 통째 보관(법령은 청킹, 보고서는 반대).
- **브리핑 Haiku에 긴급(🔴) 판정 재위임 금지** — 🔴는 news_feed 긴급도 단일 기준.
- **영향도 분석이 긴급도를 덮어쓰게 하지 말 것** — 담당자 수정 되돌리던 버그 원인.
- **같은 법령·고시 구버전을 지식 베이스에 남기지 말 것** — 구버전 조문 인용 위험.
- **kb_chunks 임베딩과 자문 질의 임베딩의 모델을 어긋나게 하지 말 것(둘 다 voyage-law-2)** — 서로 다른 모델 벡터는 코사인 비교가 무의미해 검색이 깨짐. document_chunks는 voyage-4-lite로 유지(혼용 금지). (배경역사 #21)
- **regulatory-kb 요약(kb_*)을 document_chunks(조문 원문)와 합치거나 서로 대체하지 말 것** — 요약↔원문은 상호보완 레이어. 조문 인용은 원문 우선, 요약은 맥락 보강. 합치면 조문 인용 회귀. (배경역사 #21)
- **kb 자문 조회 기본을 `only_current=true`로 유지(구버전 기본 노출 금지)** — status=superseded는 명시 요청 시만. (배경역사 #21)
- **kb_* 적재는 manifest.json을 정본으로 순회할 것(파일 스캔·개별 손삽입 금지)** — dedup·버전 판정이 manifest 기준. 신규/갱신은 add_law.py(MAINTENANCE.md 규칙). (배경역사 #21)
- **스포츠 오인 차단은 `is_sports_noise()` 패턴으로 유지할 것(EXCLUDE_KEYWORDS에 선수 이름·야구 용어를 더 쌓지 말 것)** — 실제로 빠져나온 제목엔 그 단어가 하나도 없었다(`3G 연속포`·`3G 8타점`). `3G+기록어` 조합 / `[LTE…]` 코너 표기 / `sports·entertain.naver.com` 도메인 3종으로 판정한다. **필터를 손보면 넣기 전에 DB 전체로 오탐을 대조할 것** — `3G 종료`·`LTE 20배`·`LTE-R`이 통과하는지가 기준(현재 통신 기사 오탐 0건). (배경역사 #45)
- **뉴스 중복 판정 임계(공유 키워드 3)를 2로 낮추지 말 것** — 「KT 해킹 540억」과 「KT 5G 과장광고 139억 소송」이 'KT+과징금' 2개 공유로 한 사건이 되어 **두 번째 사건의 첫 알림이 삼켜진다**(실측). 반대로 4로 올리면 재보도 억제율이 급락. (배경역사 #44)
- **브리핑 클러스터링을 전이 연결 방식으로 바꾸지 말 것** — "540억 이어 5G 소송도 패소" 같은 다리 기사가 서로 다른 사건을 한 묶음(실측 261건)으로 이어 브리핑에서 사건 하나가 통째로 사라진다. 별-형(씨앗 비교, news_dedup.cluster_star)만 사용. (배경역사 #44)
- **재알림 억제·클러스터링의 fail-open을 없애지 말 것** — 판정 코드가 죽으면 전부 알림/원본 그대로가 정상 동작. 억제 기능의 장애가 알림 장애로 번지면 안 된다. (배경역사 #44)
- **별표 동반 인출(`buildAnnexContext`)의 상한 3종을 풀지 말 것** — 질문당 별표 2개 / 별표당 6청크 / 첫 청크 필수. 별표 하나가 최대 **812청크**(항행안전무선시설 별표1)라 상한을 풀면 프롬프트가 65만 자로 터진다. 첫 청크에만 표의 열 이름이 있어, 빼면 `│1만원 │― │―│`처럼 무슨 숫자인지 모르는 조각만 들어간다. (배경역사 #43)
- **`「다른 법령」 별표 N` 인용은 따라가지 말 것** — 같은 문서의 같은 번호 별표를 붙이면 엉뚱한 표가 들어간다(인용 978건 중 90건이 타 법령). (배경역사 #43)
- **별표 검색이 안 될 때 "제목 머리말 붙여 재적재"로 해결하려 하지 말 것** — 실측으로 기각됐다. 머리말 추가 후 유사도 0.408→0.406(변화 없음), 임계값 0.45 미달 그대로. 첫 청크엔 이미 제목이 원문에 있고, 「변경신고」↔「변경허가」처럼 **제도가 다르면 어휘로 못 좁힌다.** 인용 관계를 규칙으로 따라가는 쪽이 답. (배경역사 #43)
- **ITU-R PDF를 자동 다운로드·재적재하지 말 것** — 원문에 *"All rights reserved. No part of this publication may be reproduced… without written permission of ITU"* 가 명시돼 있다(법령의 공공누리와 다름). `itu_rec_watch.py`는 **개정 감지·알림만** 하고 PDF는 사람이 받아 업로드한다. (배경역사 #49)
- **법령·고시를 대시보드 업로드(PDF)로 넣지 말 것 — 탭에서 버튼을 없앤 이유** — `law_sync.py`가 법제처 API로 조문 구조(조문번호·항·호)를 그대로 받으므로 **PDF 추출보다 정확하다**(PDF로 넣으면 `article_no`가 어긋난다). API에 없는 예외 문서(상호인정협정·정책자료)만 PC에서 `python upload_law_pdf.py <파일> "<이름>" 고시`로 넣는다. **ITU-R은 반대로 업로드가 유일한 갱신 수단**이니 그 버튼은 지우지 말 것. (배경역사 #52)
- **`law_sync.py --all-outdated`를 무인 자동화하기 전에 OKF 자동 갱신을 먼저 붙일 것** — 조문만 자동 교체되면 OKF 요약이 옛 판을 설명해 *자문이 폐지된 조문을 근거로 답한다*. 그 밖에 ①보존 상한 초과분 삭제가 무인으로 도는 위험 ②API가 동명이법을 집어올 위험이 있다. 순서: `--dry-run` 보고 자동화 → 관찰 → OKF 자동화 → 실적용. (배경역사 #52)
- **`국내 법령·고시` 목록 필터를 '제외 목록' 방식으로 되돌리지 말 것** — 카테고리로 `ITU-R`·`추가지식`·`보도자료`를 제외한다. 예전엔 "ITU-R과 날짜파일 빼고 전부"라 논문·메모·보도자료 9건이 섞여 있었고, 제목에 `전자파`가 든 논문이 `전자파 행정규칙` 그룹에 끼어 보였다. **화면에서만 빼는 것이고 자문 RAG에서는 계속 검색돼야 한다.** (배경역사 #50)
- **`index.html`·`system_prompt.js`의 하드코딩된 문서 설명을 사실 검증 없이 두지 말 것** — `M.1544-1`이 "IMT 최소 성능 요구사항"으로 1년 넘게 잘못 적혀 있었다(실제는 아마추어무선 자격기준, 진짜는 Report M.2410). **프롬프트에 든 오류는 모델이 사실로 답한다.** 문서를 올릴 때 두 파일의 설명을 함께 갱신할 것. (배경역사 #49)
- **영문 원문(ITU-R 등)은 한국어 요약을 kb 레이어에 짝으로 둘 것 — 어휘 매핑으로 때우지 말 것** — 영문 문서는 한국어 질문에 임계값(0.45)을 못 넘는다(실측: `스퓨리어스 발사 한계값` 0.375, `spurious emission limits` 0.563). 제목에 한글 머리말을 붙여도 0.384로 미달이라 기각됐다. `regulatory-kb/references/itu-r/` 6건이 그 짝이며, **요약은 찾아가는 다리이고 수치·표 인용은 반드시 영문 원문에서** 한다. 새 ITU-R 문서를 올리면 한국어 요약도 함께 만들 것. (배경역사 #47)
- **RLS 켜진 테이블에 프런트에서 직접 `delete()` 하지 말 것** — DELETE 정책이 없으면 PostgREST가 **오류 없이 '0건 삭제 성공'으로 응답**해 조용히 실패한다(운영자가 삭제 버튼을 눌러도 아무 일도 안 일어났다). 관리자 RPC(`admin_delete_*`)를 쓰고 **반환된 행 수가 0이면 실패로 처리**할 것. 현재 RLS 켜짐+DELETE 정책 없음: `document_chunks`·`chat_logs`. (배경역사 #48)
- **자문 컨텍스트에 넣은 지식은 반드시 출처 배지에도 기록할 것** — kb는 프롬프트에만 들어가고 `lastRagSources`에 안 쌓여, 165+38건 전체가 배지에 한 번도 안 떴다. **반영 여부를 볼 창구가 없으면 틀린 답도 믿을 만해 보인다.** 검증 방법을 안내하기 전에 그 창구부터 확인할 것. (배경역사 #41, #35와 동일 부류)
- **목록 검색은 표시용 정리 이름으로 매칭하고, 타자마다 DB를 치지 말 것** — 원본 `doc_name`엔 `_중복_`·`.pdf`가, kb `title`엔 `중앙전파관리소 업무안내 — {분야} > ` 접두가 붙어 결과가 어긋난다. `oninput` 재렌더는 `_kbDocsRows`/`_guideRows` 캐시로 처리(force=true일 때만 재조회). (배경역사 #42)
- **`실무 안내` 목록에서 `body_md`를 통째로 내려받지 말 것** — 203건 합계 681kB다. 표 포함 여부·청크 수는 `list_kb_guide_docs` RPC가 서버에서 계산하고, 본문은 클릭한 1건만 조회한다. (배경역사 #42)
- **마크다운 표 스타일을 `.msg-ai`에만 두지 말 것** — 자문 답변 밖(실무 안내 모달 등)에서 테두리 없이 글자만 흩어진다. 새 화면에 `renderMd()`를 쓰면 표·목록 스타일도 그 컨테이너에 함께 줄 것. 한글은 `word-break: keep-all`(없으면 단어 중간에서 끊김). (배경역사 #42)
- **웹에서 긁은 표를 그대로 렌더하지 말 것** — 원본 rowspan이 풀려 `| 나. … | ||` 꼴이 되면 내용이 **`구분` 열 아래로 들어가 규정을 잘못 읽게 된다.** `renderMd()`가 ①전부 빈 열 제거 ②첫 칸에만 있는 행은 통칸 처리로 막고 있으니 이 두 처리를 지우지 말 것. (배경역사 #42)
- **계층 목록을 평면 나열로 되돌리지 말 것** — 203건을 한 화면에 펴면 분야·계열 구조가 사라져 못 쓴다. 기본은 접힘, 구획마다 맨 위 묶음 하나만 펼침. (배경역사 #42)
- **`실무 안내`에서 조문 모달을 재사용할 때 조문 검색줄 복원을 빠뜨리지 말 것** — `openGuideDoc()`이 `kb-doc-searchrow`를 감추므로 `openKbDoc()`이 되살리지 않으면 이후 조문 검색이 영영 사라진다. (배경역사 #42)
- **여러 세션이 같은 repo 동시 커밋 금지** — stale 마운트로 작업 되돌림 사고(f37fd0b).
- **pg_cron 트리거 잡·`dispatch_github_workflow`·`trigger_briefing_if_missing`·Vault `github_pat` 삭제 금지** — GitHub cron 드롭 보완 핵심(Supabase가 주 트리거).
- **같은 문서를 다른 카테고리로 중복 업로드 금지** — 청크 중복→검색 노이즈.
- **fetch_article_body의 rra.go.kr trafilatura 우선 분기 제거 금지** — 'article' 셀렉터 네비 오탐.
- **DH_KEY_TOO_SMALL 자동 재시도(_http_get)를 rra.go.kr 전용으로 되돌리지 말 것** — 도메인 무관 우회.
- **law_crawler 엔드포인트를 open.law.go.kr/LSO/...로 되돌리지 말 것** — 정식은 www.law.go.kr/DRF/lawSearch.do.
- **법령/국회 키워드에 '혼신' 재추가 금지** — '이혼신고' 오탐. '전파간섭'으로 유지.
- **daily_crawl.yml 스케줄을 예전 다중 슬롯으로 되돌리지 말 것** — `17 * * * *`(백업)+Supabase :47(주 트리거)로 단순화.
- **GitHub 크롤 백업 슬롯(:17)을 정시·15분 단위로 옮기지 말 것** — 혼잡대 드롭↑.
- **모닝 브리핑 cron을 23~00 UTC(08~09 KST)로 되돌리지 말 것** — 최혼잡 드롭. 21 UTC대(06시 KST) 유지.
- **추가 지식 "파일 업로드"를 custom_knowledge로 보내지 말 것** — 파일은 document_chunks(추가지식)로.
- **추가 지식 "저장된 목록" 파일 병합 표시(loadCustomFileList) 제거 금지.**
- **추가지식 원본 Storage 보관·file_path 기록 제거 금지** — 다운로드 근거.
- **uploads 버킷 public 전환 금지** — private+createSignedUrl.
- **대시보드 업로드 모달 DOCX·드래그앤드롭·전포맷 분기 제거 금지** — 공용.
- **국회 법안 링크의 billId 기반 URL 폴백 제거 금지** — 열린국회정보 API(nzmimeepazxkubdpn)는 LINK_URL 필드를 실제로 반환하지 않아(222건 전부 공백이었음) `assembly_crawler.py`의 `bill_link()`와 `app.js` `renderAssemblyBills()`가 `likms.assembly.go.kr/bill/billDetail.do?billId=<bill_id>`로 링크를 직접 구성. API 필드만 믿고 이 폴백을 걷어내면 의안 링크가 다시 전부 사라짐. (배경역사 #24)
- **PC용 파이썬 패키지를 `pip install --user`로 설치 금지** — 정부크롤러 예약작업(전파정책_정부크롤러)은 **SYSTEM 계정**으로 실행되어 사용자 프로필(`AppData\Roaming\...\site-packages`)의 --user 설치 패키지를 못 봄. anthropic이 --user로만 있어 입법예고 요약이 한 달간 무음 생략됨. 설치는 `python.exe -s -m pip install <pkg>`(전역 site-packages), 검증은 `python.exe -s -c "import <pkg>"`(-s = SYSTEM 상황 시뮬레이션). (배경역사 #25)
- **입법예고 개정이유 추출 정규식의 공백 허용(`개\s*정\s*이\s*유`) 제거 금지** — 부처마다 공고문에 "개정 이유"처럼 띄어 쓰는 경우가 있어, 붙여 쓴 `개정이유`만 찾으면 요약이 "내용없음"('')으로 잠겨 재시도도 안 됨. (배경역사 #25)
- **PDF 편집 흔적 정리(clean_pdf_artifacts / lawmapCleanText) 제거 금지** — 국가법령정보센터 PDF는 페이지마다 `[N페이지]`·`법제처 N 국가법령정보센터` footer·법령명 반복 머리글을 본문에 넣어, 제거 안 하면 조문·자문 RAG에 노이즈로 섞임. 업로드 시 자동 정리(upload_law_pdf) + 대시보드 표시 시 정리(app.js) + 기존 데이터는 clean_pdf_artifacts.py로 일괄 청소함(2026-07-24, 4,513청크). 규칙 3곳(upload_law_pdf.clean_pdf_artifacts·app.js lawmapCleanText·clean_pdf_artifacts.py)이 동일해야 함. footer는 청킹 경계에서 '법제처'가 잘려 'N 국가법령정보센터'만 남기도 하므로 `(?:법제처\s*)?\d*\s*국가법령정보센터`로 매칭. (배경역사 #28)
- **law_graph_nodes를 일괄 삭제·재생성하지 말 것 — 인용망 재구축은 엣지(source in citation/family)만** — 노드를 지우면 FK cascade로 seed(시드 주제)·ai(자문 축적) 엣지까지 통째 소실. build_law_citation_graph.py도 노드는 재사용·추가만 하고, 엣지 0개인 citation 고아 노드만 정리. (배경역사 #28)
- **law_graph 조회의 1000행 페이지네이션(fetchAllRows·range 루프) 제거 금지 — `.limit(2000)`을 믿지 말 것** — PostgREST 서버 max-rows가 1000이라 limit을 크게 줘도 1000행에서 잘림. 노드 1,018건 중 주제 18개가 조용히 누락됐던 원인. 파이썬 스크립트도 동일(.execute() 기본 1000행). (배경역사 #28)
- **`import_regulatory_kb.py` 전체 재적재 전 `sync_kb_to_bundle.py` 먼저 실행할 것** — 웹 승인 훅이 만든 OKF는 DB에만 있고(브라우저는 번들 파일을 못 씀) 재적재는 manifest 정본 기준이라, 동기화 없이 재적재하면 웹 생성 OKF가 통째로 유실됨. (배경역사 #29)
- **자문 <lawmap> 블록 지침(lawmapGuide)·파싱·기존 주제명 주입 제거 금지** — 관계도의 주 성장 경로(추가 API 호출 0회). 주제명 목록 주입을 빼면 "3G 종료"/"3G 서비스 종료" 식으로 주제가 분열됨. 블록은 화면·chatHistory에서 제거되므로 사용자에게 안 보이는 게 정상. (배경역사 #28)
- **관계도 전체 뷰 적응형 임계 필터·주제 포커스 계열 한정 확장(lawmapNeighborhood) 제거 금지** — 인용 이웃으로 2촌 확장하면 허브 법령(전파법)을 거쳐 600+노드로 폭발해 렌더 불능. 직접 이웃+하위법령 1단계가 정답. (배경역사 #28)
- **관계도 AI 생성·보강의 병합 원칙(기존 노드·엣지 삭제 없음, 신규만 upsert, 재확인 weight+1) 훼손 금지** — "한 번 생성=초안, 계속 보강" 구조의 핵심. 덮어쓰기로 바꾸면 검수된 관계가 유실됨. (배경역사 #28)
- **관계도 전체 뷰의 고시 접기(`_lawMapShowNotice=false` 기본)를 '항상 전부 표시'로 되돌리지 말 것 / 접을 때 고아 주제 구제 로직을 빼지 말 것** — 법령이 늘며 전체 뷰 노드의 과반(96/178)이 고시가 돼 중앙이 뭉갰다(겹침 50쌍·최소간격 3px). 고시는 '법률→시행령→고시' 말단이라 조망에선 잔가지이고 주제·법령 클릭 시 그대로 다 보인다. **단 근거가 고시뿐인 주제(충전단자 표준화·MRA·인빌딩 무선통신보조설비)는 통째로 숨기면 엣지 없는 단독 버블이 되므로**(#28에서 이미 고친 회귀), 그런 주제의 직결 고시 8개는 예외로 남긴다. 접힌 사실은 `고시 N개 펼치기` 토글로 화면에 드러낼 것(정보 삭제가 아니라 접기임을 알려야 오해가 없다). 결과 90노드·256엣지·겹침 8쌍. (배경역사 #36)

## 알려진 제약사항

1. 이메일 수신: Resend 도메인 미인증 → you.jinwoong@gmail.com만.
2. 본문 수집: PC 꺼지면 RSS 요약만 → refetch_content.py 보완. trafilatura 로컬 필수(`pip install trafilatura`).
3. Supabase는 **Pro(유료) 플랜**(2026-08-02 운영자 확인 — DB 8GB·Storage 100GB 포함, 실측 DB ~600MB). 과거 "무료 500MB×2" 기술은 폐기. 신규 프로젝트는 여전히 불요(하나로 충분) — 다만 금지 사유가 '슬롯 부족'이 아니라 '분산 관리 비용'으로 바뀜. **실제 병목은 RAM(컴퓨트 2GB — shared_buffers 512MB)**: 벡터 인덱스가 캐시를 넘으면 검색이 급락한 전력(무료 시절)이 있으니 대량 적재 후엔 REINDEX로 인덱스를 컴팩트하게 유지할 것.
4. 스포츠 기사 오탐: EXCLUDE_KEYWORDS+피드백 관리.
5. 신규 업로드 문서·보고서: backfill 전까지 시맨틱 미적용("임베딩 대기"). 보고서는 backfill_report_embeddings.py(PC 의존).
6. 60일 초과 삭제는 Supabase pg_cron(jobid 2, 매일 00:00 KST, created_at 기준 `DELETE ... AND locked=false`)이 PC 없이 자동 수행. refetch_content.py는 published_at 기준 보조 정리(PC 의존). 입법예고 수집만 PC 의존(17:00 로컬).
7. 무선국 자기적합확인(전파법 제24조②, 2026.10.22 시행): 시행령 위임 미반영 — 개정 공포 시 PDF 업로드.
8. 일부 고시는 시행 전 개정본만 보유(적합성평가 2025-56호 등).
9. ITU-R 탭은 정적 목록.
10. 일부 사이트 SSL/봇 차단으로 본문 수집 불가(403·SSLV3·CERTIFICATE) — 정상 baseline.
11. GitHub cron 드롭·지연(best-effort) — Supabase pg_cron이 주 트리거, 그래도 누락 시 "Run workflow"·PC 보완.
12. 대시보드 업로드는 텍스트 기반 PDF만(스캔본 불가).
13. AI 자문·보고서 초안 무거운 질문은 2분+ 소요(스트리밍이라 정상).

## 외부 서비스·키

| 항목 | 용도 | 비고 |
|---|---|---|
| GitHub Actions+Pages | 자동화+호스팅 | 무료 |
| Supabase | DB+Edge(voyage-embed)+Storage | **Pro(유료)** — DB 8GB·Storage 100GB 포함(2026-08-02 정정). 컴퓨트 Small(RAM 2GB)이 실제 병목 |
| Voyage AI | 임베딩(voyage-4-lite, 1024) | 무료 2억 토큰 |
| Anthropic API | AI 자문·보고서 초안(sonnet stream)+긴급도/요약/스타일증류(Haiku) | 키는 app_config(claude_key) |
| Resend | 이메일 | 100/일 |
| Telegram Bot | 알림 | 무제한. **봇 2개** — 운영자용(`TELEGRAM_BOT_TOKEN`)·구독자용 `정책AI 도우미`(`SUBSCRIBER_BOT_TOKEN`, @radio_policy_law_ai_bot) |
| trafilatura(pip) | 본문 추출 | 로컬 설치 |
| pdf.js·mammoth·JSZip(CDN) | 브라우저 파일 파싱 | 보고서 등록·지식 업로드 공용 |
| 법제처 DRF | 법령·고시 | LAW_OC_KEY=radiopolicyai |
| opinion.lawmaking.go.kr | 입법예고 | 로컬 수집, 키 불필요 |
| 열린국회정보 API | 국회 법안 | ASSEMBLY_API_KEY |
| 네이버 검색 OpenAPI | 뉴스 1순위 | NAVER_CLIENT_ID·SECRET, 일 25,000회 |
| crms.go.kr (중앙전파관리소) | 업무안내 해설 38p → regulatory-kb | 키 불필요. 공공누리 **제1유형**(출처표시)이라 재배포·변형 허용. robots.txt 전면 허용 |

### GitHub Secrets
```
SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY,
EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO, RESEND_API_KEY,
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, LAW_OC_KEY(=radiopolicyai),
ASSEMBLY_API_KEY, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, SUBSCRIBER_BOT_TOKEN
※ 로컬은 동일 키를 .env에(.gitignore 등록). backfill_report_embeddings.py는 SUPABASE_URL·SERVICE_KEY·VOYAGE_API_KEY만.
※ Vault github_pat(fine-grained PAT, radio-policy-commit) 필수권한: Repository — Contents(R/W)·Metadata(자동)·Actions(R/W). 재생성 시 Actions 누락 주의(배경역사 #18).
```

### Supabase Edge Function Secrets
(GitHub 아님 — Project Settings → Edge Functions → Secrets)
```
VOYAGE_API_KEY           voyage-embed + rag.ts 임베딩
SUBSCRIBER_BOT_TOKEN     구독자 봇 (운영자 봇 토큰과 다름)
TELEGRAM_WEBHOOK_SECRET  webhook 진위 검증 (Telegram이 헤더로 보냄)
CRON_SECRET              pg_cron → send-subscriber-briefing 인증
ANTHROPIC_API_KEY        자문·키워드확장 (app_config.claude_key 재사용 금지)
OPERATOR_CHAT_ID         344506450 — 자문 승인 버튼 수신자
※ Vault subscriber_cron_secret = CRON_SECRET 과 같은 값(트리거 함수가 여기서 읽음).
※ 값 붙여넣기 시 줄바꿈 혼입 주의 — 콘솔의 SHA256 다이제스트로 대조 검증할 것.
```

### 구독자 봇 설치·운영 (`SUBSCRIBER_BOT_TOKEN`)
```
python init_subscriber_secrets.py --out <경로>   # 랜덤 시크릿 생성 → .env 기록 + 등록 안내 파일
python setup_subscriber_bot.py                   # setWebhook + 명령 메뉴 + 표시명·소개문
python sync_system_prompt.py                     # system_prompt.js → app_config (프롬프트 수정 시마다)
npx supabase@latest functions deploy telegram-webhook --project-ref zwkjedumfuhodckmtxxn --no-verify-jwt
npx supabase@latest functions deploy send-subscriber-briefing --project-ref zwkjedumfuhodckmtxxn --no-verify-jwt
※ CLI 배포는 .env의 SUPABASE_ACCESS_TOKEN(sbp_...) 필요. MCP 전송 방식은 파일 50KB 넘으면 실패한다.
```

---

※ 이 지침은 운영 핵심만 담는다. 각 결정의 상세 배경·과거 사고 경위·날짜·커밋 해시는 `전파정책AI_배경역사.md` 참조.
