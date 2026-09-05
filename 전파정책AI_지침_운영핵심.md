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
- 대시보드: https://radio-policy.gitlab.io/ (GitLab Pages, 정본) · 미러 https://radio-policy.github.io/ (GitHub Pages)
- 저장소: 주 GitLab `gitlab.com/radio-policy/radio-policy.gitlab.io` · 미러 GitHub `github.com/radio-policy/radio-policy.github.io` (조직 `radio-policy` 소유, 2026-09-03 개인 계정에서 이전 — 배경역사 #116)
- 담당자: 유진웅 (you.jinwoong@gmail.com)

## 로컬 파일 위치

```
C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai\
├── sb_client.py                # Supabase 클라이언트 공용 생성기 — HTTP/2 끄고 HTTP/1.1+재시도(make_client). 모든 스크립트가 create_client 대신 사용(RemoteProtocolError 끊김 회피)
├── requirements.txt            # 의존성 버전 고정(lock, 61개). 모든 워크플로가 `pip install -r requirements.txt`로 설치 — 자동 최신화 사고 방지(배경역사 #15)
├── crawler.py                  # 메인 크롤러(GitHub Actions 매시간) — 네이버 검색 OpenAPI(키 없으면 Google RSS 폴백), **키워드 54개 확대수집 → 무관 판정 캐시 대조(news_screen_cache, #78) → Haiku 1차 관련성 선별(app_config.news_relevance_criteria, 무관은 저장 안 함+캐시 기록, fail-open 키워드 폴백, 부처 인사는 무조건 통과, #66)** — 선별이 분야 태그(#76)·사건 라벨(event, #77)도 함께 매김 → 통과분만 본문 수집·**Haiku 긴급도 개별 분류**(피드백 학습), 긴급 재알림 억제 — ⚠️ **선별 콜 통합(#82)은 2026-08-04 되돌렸다(#84).** 긴급률이 9.9%→0.7%로 무너졌고, 「SKT 5G 과장광고 과징금, 대법원 간다」가 8/3 긴급 → 8/4 보통으로 갈린 A/B가 근거다. 원인은 ①선별이 **본문 수집 전**이라 네이버 요약 300자만 본다(본문 중앙값 1,329자) ②배치 판정이라 제목별 유사 피드백 5건을 못 쓴다. **재통합하려면 긴급률을 9.9%와 반드시 대조할 것**(suppress_repeat_alerts, #44). 운영자 긴급 알림에 태그 표시(구독자에겐 비표시)
├── morning_briefing.py         # 모닝 브리핑 생성·발송(06:00 KST). **app_config.briefing_excluded_urls(JSON 배열)의 URL은 제외(#85)** — 오탐 기사를 브리핑에서만 빼는 수단. 삭제(대시보드·자문에서도 사라짐)·published_at 조작(사실 왜곡)·등급 하향(24h 전체를 보므로 무효)을 다 버리고 택한 방식. 조회 실패는 빈 집합(fail-open) — 🔴=DB 긴급도, 같은 사건 클러스터링(대표 1건+관련 N건, #44), SKT 영향 분석, 신규 입법예고 📢 섹션, 본문 0건 시 요약→제목 폴백(빈 브리핑 방지), 기사 0건 시 시각무관 1일1회 '🕊️무뉴스' 통지+placeholder(_handle_no_news)
├── news_dedup.py               # 같은 사건 재보도 판정 공용 유틸(제목 키워드, API 비용 0) — crawler·morning_briefing 공유. 임계 3·별-형 클러스터링 근거는 파일 주석 (#44)
├── regenerate_briefings.py     # 과거 브리핑을 클러스터링 적용본으로 재생성(수동). morning_briefing 함수 재사용, 입법예고 섹션 보존. **실행 전 daily_briefings_backup에 원본 백업 필수** (#46)
├── refetch_content.py          # 본문 재수집·요약(**'참고' 등급은 생략 — 온디맨드, #82**)·60일 초과 정리(Windows 스케줄러, 한국 IP) · heartbeat(last_refetch_run)
├── gov_notice_crawler.py       # 정부·기관 고시→news_feed + 입법예고(opinion.lawmaking.go.kr)→law_amendments(lsAnc) (17:00, 한국 IP) · heartbeat(last_gov_notice_run)
│                               #   RRA(국립전파연구원)·MSIT(과기정통부)·KMCC(중앙전파관리소)·KCC(방통위)·ETRI·KISDI
│                               #   ※ MSIT는 보도자료·입법행정예고·훈령예규고시 + **공고(공지사항 mPid=121&mId=310)**: 주파수 할당·재할당 공고 원문이 실리는 게시판(2026-08-02 추가). 사업공고(311)는 R&D 모집 잡음이라 제외
│                               #   ※ crawl_kcc()는 방통위(kcc.go.kr), crawl_kmcc()는 중앙전파관리소(kmcc.go.kr) — 도메인 한 글자 차이라 혼동 주의
├── law_crawler.py              # 법제처 DRF API 법령·고시 모니터링(11:00 KST). 엔드포인트 www.law.go.kr/DRF/lawSearch.do, OC=radiopolicyai
├── assembly_crawler.py         # 국회 법안 모니터링(열린국회정보 API, 22대) + 국회 입법예고 추적 패스(#56). **키워드 검색은 페이지 끝까지 순회**(`_fetch_bill_rows`, #121 — pIndex=1 한 페이지만 읽으면 100건 넘는 키워드가 조용히 잘림) + `fetch_committee_bills`(COMMITTEE=과학기술정보방송통신위원회 전수 스윕)로 이름에 키워드가 없는 과방위 소관 법안까지 포착(#121)
├── law_diff_gen.py             # 법령 조문 DIFF 생성(행정부 예고/시행예정/시행 + 국회 예고 --assembly-only) (#54·#56). **국회분은 KB 등재 법령만 분석(#86)** — 「이 법안이 KB에 있는 법을 고치는가」 대조. AI 판정이 아니라 문자열 대조라 비용 0이고, 운영자가 KB 등재로 대상을 직접 통제한다. 법령명 정규화 필수(`[ㆍ·・.\s]` 제거 — 「대·중소기업」 표기가 DB/국회가 다르다). **KB 조회 실패 시 필터 미적용(fail-open), 제외분은 로그에 이름을 남긴다**(빠진 법을 KB 등재로 되살릴 수 있게). **조문 매칭은 법제처 신구법대비표 API(oldAndNew/admrulOldAndNew) 정본 우선, 없으면(존재여부 N) difflib 폴백 — 영향분석·요약은 무변경. pending/promoted 경로만 (#63)**
├── foreign_press.py / assembly_minutes.py  # 해외 규제기관(05:30) / 과방위 회의록(17시 체인) (#54). 회의록 일일 경로는 Sonnet 5(`MINUTES_MODEL`, thinking disabled) + 신규 회의 다이제스트를 구독자 큐(assembly)에 적재 (#120)
├── minutes_offline.py          # 회의록 **API 0** 파이프라인(#120): 후보·재요약 JSON 내보내기 → 세션(서브에이전트)이 판정·요약 JSON 작성 → 가져오기. 재요약·20·21대 소급 전용, 큐 적재 없음
├── notify.py / embed_util.py   # 공용 유틸 — 텔레그램 전송(분할·재시도·429) / Voyage 임베딩. 새 코드는 반드시 재사용 (#58)
├── tests/test_smoke.py         # 스모크 테스트(표준 unittest·네트워크 0, 17케이스). `python -m unittest discover -s tests` (#58)
├── upload_law_pdf.py           # PDF/MD/PPTX→document_chunks RAG 업로드(조문 헤더 청킹)
├── import_regulatory_kb.py     # regulatory-kb OKF 번들(법령 요약 **248문서·5,528청크**)→kb_documents/kb_chunks 적재. manifest.json 정본 순회, voyage-law-2 임베딩(stdlib만). (배경역사 #21)
├── add_law.py                  # 법령 추가 통합(Ⓑ): PDF 1개→①조문 document_chunks ②Haiku 요약 OKF→regulatory-kb+manifest+kb_* 동시. MAINTENANCE.md dedup 규칙 적용
├── regulatory-kb/              # OKF 법령 요약 번들(manifest.json 정본 + laws/·procedures/·glossary/). kb_* 적재 원천
├── backfill_embeddings.py      # Voyage 임베딩 백필(document_chunks NULL만)
├── backfill_report_embeddings.py # 보고서 샘플 임베딩 백필(report_samples NULL만) — 신규 보고서 등록·채택본 승격 후 실행
├── resend_briefing.py / send_briefing.py  # 브리핑 재발송·발송 단독
├── health_watchdog.py          # 외부 헬스 워치독(GitHub Actions, Supabase 독립) — 크롤러 성공여부 인지(고장 vs 뉴스없음 구분)
├── system_prompt.js            # 대시보드 AI 자문 시스템 프롬프트(위임 관계 검증·핵심 조문 참조)
├── index.html / app.js         # 대시보드 프론트엔드(GitHub Pages). AI 자문·보고서 초안 모두 SSE 스트리밍(stream:true) — 비스트리밍 복귀 금지. AI 자문은 RAG+뉴스+법령동향 컨텍스트 조합
├── crms_guide_sync.py          # 중앙전파관리소 업무안내 38p → regulatory-kb 적재(월 1회, 한국 IP). 본문 sha256 비교로 변경분만
├── lawmap_edge_check.py        # 관계도 주제 엣지 점검(읽기 전용) — 설명의 근거 조문이 KB 원문에 있는지 대조, 17시 체인 마지막 단계, 신규 문제만 운영자 무음 알림 (#123)
├── run_gov_crawler.bat / run_briefing_backup.bat / run_crms_sync.bat / setup_*.ps1  # 배치·스케줄러 등록
└── .github/workflows/          # daily_crawl·morning_briefing·law_crawl·assembly_crawl·backfill·cleanup·health_watchdog
```

## Supabase DB

- **Project ID**: zwkjedumfuhodckmtxxn / **URL**: https://zwkjedumfuhodckmtxxn.supabase.co / **Region**: ap-northeast-1(도쿄)

### 주요 테이블

| 테이블 | 설명 |
|---|---|
| news_feed | 뉴스 본문·요약·긴급도(**60일 유지** — 2026-07-31 확대, 자문 뉴스 검색 60일 창과 정합. **해외 category는 예외** #75). locked=true면 자동삭제 제외+AI 자문 상시 참조. 내부값 긴급/보통/참고. **tags text[]**(분야 태그 5종, #76)·**event text**(사건 라벨 — 대시보드 클러스터링 기준, #77). **url UNIQUE**(idx_news_feed_url_unique) — 저장은 반드시 `upsert(on_conflict='url', ignore_duplicates=True)`로 (plain insert는 중복 1건에 배치 전체 실패, #23) |
| deleted_news | 삭제 기사 url·title 블록리스트(재수집 방지). 영구 |
| news_screen_cache | **선별 무관 판정 캐시**(#78): url PK·title_hash·criteria_hash·judged_at·**created_at(#83)**. `created_at == judged_at`이면 신규 기사, 더 이르면 **제목 변경 재판정** — 판정 건수가 튈 때 "기사가 는 것"과 "같은 기사를 다시 본 것"을 가른다(NULL은 계측 이전 행). 기본값 없이 추가한 뒤 DEFAULT를 지정할 것 — DEFAULT를 붙인 채 추가하면 기존 행이 전부 ALTER 시각으로 채워져 거짓 사실이 된다. crawler는 이 컬럼을 upsert에 담지 않으므로 코드 변경 불요. 무관 기사는 저장이 안 돼 매시간 재판정됐다(시간당 ~470건 중 신규 ~70건 = 선별 비용 85% 낭비). 제목이 바뀌거나 기준문(news_relevance_criteria)이 바뀌면 지문 불일치로 자동 재판정. **AI 판정분만 캐시**(키워드 폴백 탈락은 안 함), 20일 TTL 크롤러가 청소, 전 단계 fail-open. RLS 켜고 정책 0 = service 전용 |
| telegram_updates | **텔레그램 웹훅 재전송 차단**(#83): update_id PK·chat_id·received_at. 텔레그램은 웹훅이 60초 안에 200을 못 받으면 **같은 update_id로 재전송**한다 — /law·/ask는 답변 생성이 1~2분이라 재전송이 겹치면 같은 질문에 답이 여러 번 나간다(2026-08-04 실측: 웹훅 실행 45~56초 상시). 최초 1건만 통과 → **중복은 막고 새 질문(다른 update_id)은 통과**. dedup 조회 실패 시 통과(fail-open — 중복이 무응답보다 낫다). 청소는 1% 확률(update_id % 100)로만. RLS 켜고 정책 0 = service 전용 |
| importance_feedback | 긴급도 수동 수정 내역(news_id당 1행). 분류 학습 데이터. 영구 |
| feedback_rules | 피드백 증류 규칙 캐시(단일 행 id=1). 20건↑ 증류, 10건마다 재증류 |
| daily_briefings(삭제 없음·전량 보관, 목록도 무제한 표시) | 일일 브리핑 원문("⚠️ SKT 영향 분석:" 포함). 긴급도 수정 시 🔴 자동 동기화 |
| issues | **이슈맵 본체**(#110): state(proposed/active/rejected/archived)·stage(발생/현안/해소)·dormant·stage_log·resolution_kind·norm_key·embedding(voyage-4-lite)·impact_summary/history. 영구 보관, 삭제 없음. RLS: 조회 공개·쓰기 authenticated |
| issue_links | 이슈-항목 다형 연결(#110): item_type(news/law/bill/diff/press_chunk/minutes/briefing/kb_case/stakeholder)+item_id+title 캐시+item_date. **연결된 news는 자동 locked** — 이슈가 뉴스 보존 기준. unique(issue,type,id) |
| news_embeddings | 뉴스 임베딩(#110): news_id FK **on delete cascade**(60일 삭제와 자동 연동)+vector(1024) HNSW. RPC match_news_semantic. 백필 스크립트는 후속 |
| law_amendments | 법령·고시·입법예고. law_type: law/bylaw/rules/admrul/lsAnc. lsAnc는 law_id=`lsAnc_op_{md5}` |
| assembly_bills | 국회 법안. bill_id(UNIQUE)·법안명·단계·소관위·제안일·링크. **+국회 입법예고**(2026-08-02): notice_end_dt(의견마감 'YYYY-MM-DD')·notice_url(pal 상세)·notice_alert_stage(0미알림/1시작알림/2 D-3알림 — 발송 성공 시에만 갱신) **+진행단계 원본**(2026-09-04, #122): committee_dt(소관위 회부)·cmt_present_dt(상정)·cmt_proc_dt/cmt_proc_result(위원회 처리)·law_submit_dt/law_present_dt/law_proc_dt(법사위). proc_result는 API PROC_RESULT가 비면 `bill_stage.derive_stage()`가 '소관위 회부/심사중·위원회 의결·법사위 회부/심사중'을 파생(종전엔 전부 '접수') |
| assembly_speeches | 과방위 발언자별 발언(#67). speaker(정규화명)·speaker_raw·position·meeting_date·confer_num·chunk_seq·agenda·topic·summary(Haiku 요지, 성향 단정어 금지 가드)·source_url. unique(confer_num,speaker,chunk_seq). RLS anon select만. assembly_minutes.py가 document_chunks와 독립 dedupe로 적재 |
| people | **인물 프로필**(#112): speaker_key(assembly_speeches.speaker 일치 키)·name(표시명)·kind(의원/정부·참고인)·party(활동 당시)·position·terms·is_22(현역 판정=22대 발언 존재)·speech_count·stance_summary(AI 쟁점별 입장 요약 캐시)·stance_updated_at. 발언 4건 이상만 시드. RLS: select/update 공개(issues 관례) |
| document_chunks | 법령·고시·보도자료 RAG 청크. embedding(vector 1024, HNSW), article_no=조항번호+제목. file_path=업로드 원본 Storage 경로. **보도자료는 2026-08-02부터 자동 수집**: doc_name=`{기관}_보도자료_{YYYY}.md`(기관: 과기정통부/전파연구원/방통위/전파관리소/ETRI/KISDI), 섹션 헤더 `## YYMMDD 제목`, 마지막 줄 `(원문: URL)`, **700자 무겹침 청킹**(대시보드가 청크를 이어붙여 원문 복원하므로 overlap 금지) |
| app_config | 키-값 설정. `system_prompt`(봇 자문 프롬프트), `press_keywords`(보도자료 수집 키워드 JSON 배열 — 대시보드 '수집 키워드 관리' 카드가 편집), `press_relevance_criteria`(매일 수집 AI 관련성 판정 기준문), `assembly_notice_criteria`(국회 입법예고 Haiku 판정 기준문)·`assembly_notice_rejected`(기각 캐시 JSON — 자동 관리) 등. **claude_key는 anon 노출되는 브라우저용 — 서버측 재사용 금지** |
| custom_knowledge | 팀 추가 지식(수동 입력). AI 자문 키워드 매칭 참조 |
| chat_logs | AI 자문 이력. **2026-08-20(#103)부터 네 경로 공통 정본 답변 로그** — 대시보드 자문·텔레그램 /ask·/law 자연어·/law 조문 직조회. `channel`(만족도 집계 축)·`chat_id`(텔레그램 이용자)·`chunk_ids`(jsonb, 그때 실제로 프롬프트에 들어간 근거 청크 id — 불만족 분석 재료) 컬럼 추가. 자문 이력 목록은 `category='텔레그램-조문조회'`만 제외(기계적 원문 출력이라 성격이 다름 — 피드백 탭에서는 보인다). 삭제 가능. `sources`(text)는 **두 종류를 접두사로 구분해** 담는다 — 법령·문서명은 그대로, 수집 뉴스는 `[뉴스] 제목 (매체, 날짜)`. 화면·내보내기에서 `splitSources()`로 갈라 별도 표기(법령은 6개 초과분 `… 등 N개`). **뉴스는 본문 발췌로 실제 반영된 건만** 기록(제목 목록 30건은 근거 아님). 스키마 변경 없이 반영 여부를 사후 검증하려는 구조. (배경역사 #35) |
| teams / profiles / advisory_usage | 대시보드 계정 체계(#104). `teams`=3팀(경쟁제도팀·기술정책팀·AI정책팀, 팀 합산 일일 한도). `profiles`=auth.users 1:1(이름·팀·role(admin/leader/member)·개인 한도·unlimited·**approved**(관리자 승인 전 AI 잠김)·active). 가입 시 트리거가 승인대기 프로필 자동 생성. `advisory_usage`=(user_id, day, kind) 일일 사용량, kind는 advisory(한도 대상)/general(백스톱 300). 쓰기는 service_role RPC 전용 |
| answer_feedback | 답변 만족도 👍👎(#103). **세 경로 공통 한 테이블** — `channel`(telegram_ask/telegram_law/dashboard)로 구분해 경로별 불만족률 비교. `log_id` 유니크 FK→chat_logs(재투표는 upsert로 갱신, 로그 삭제 시 set null이라 평점·경로는 보존). `rating` 1/-1, `reason`은 대시보드 👎 사유(텔레그램은 버튼만 → null). **RLS 켜짐 + anon 정책 없음** — 쓰기는 `submit_answer_feedback` RPC, 읽기는 `admin_list_answer_feedback`(관리자 비밀번호). 화면: AI 자문 > '답변 피드백' 탭 |
| report_samples | 보고서 초안 제안 — 내 보고서 전문(형식·톤 학습용, 청킹 안 함). embedding(vector 1024, HNSW). report_type=정책검토/규제영향/동향보고/기타 |
| report_style_rules | 보고서 스타일 가이드 캐시(단일 행 id=1). sample_count·feedback_count로 자동 재증류 임계(+2) 추적 |
| report_feedback | 보고서 피드백 — request·draft·final(채택·교정본)·rating(1/-1). 편집-diff 학습 데이터. 영구 |
| report_directives | "항상 적용" 영구 지시 — 모든 초안 시스템 프롬프트에 최우선 주입. 관리 탭에서 삭제 가능 |
| alert_suppress_log | 긴급 재알림 억제 내역(어떤 기존 기사와 유사해 막았는지, 공유 키워드). **1~2주 실측 후 "본문에만 새 내용" 놓침이 있으면 Haiku 판정 층(월 2~6$) 추가 판단**용. service만 접근(정책 없음) (#44) |
| system_health | 운영 heartbeat(key별 1행). last_crawl_run=뉴스크롤러 / last_gov_notice_run=입법예고·정부고시 / last_refetch_run=본문수집. 워치독 '고장 vs 없음' 구분 + 운영상태 탭. RLS+anon select |
| kb_documents | 법령·규제 **요약/실무 문서**(regulatory-kb OKF 번들, 문서당 1행). concept_type·law_type·law_number·enforcement_date·status(current/superseded)·body_md 컬럼. path 유니크(정체 키). **document_chunks(조문 원문)와 별개 레이어** — 조문 인용은 그쪽, 요약·적용범위·실무는 이쪽. RLS+anon select. **법안 요약은 넣지 않는다**(2026-09-04 #122 — #121에서 넣었던 concept_type='Bill' 109건은 같은 날 삭제): 자문 근거는 확정 법령(시행예정본 포함)만, 국회 법안은 동향 전용. |
| kb_chunks | kb_documents 본문 청크 + embedding(**voyage-law-2** 1024, HNSW). doc_id FK(cascade). 자문이 시맨틱+trgm으로 조회 |
| law_graph_nodes | 법령 관계도 노드(name UNIQUE). node_type: topic(주제)/law/decree/rules/notice/etc. source: seed(세션 시드)/citation(인용망 스크립트)/ai(자문·즉석 생성). doc_name=document_chunks 연결(원문 보기). RLS+anon select/insert/update(delete는 service 전용) |
| law_graph_edges | 법령 관계도 엣지(source_id→target_id, on delete cascade). relation_type: 근거(주제→법령)/인용(조문 인용)/하위법령(계열). source: seed/citation/family/**thdcmp**/**delegation**/ai. weight=인용·재확인 횟수(엣지 굵기). unique(source,target,relation_type). RLS 동일. **delegation(2026-08-03, #81)** = `law_delegations` 표 기반 위임 엣지(weight=5, 최우선) — 조문 근거 원본은 표에 있으므로 description은 요약만. 우선순위 delegation > thdcmp(4) > family(3), 상위 출처가 정본화한 노드쌍은 하위 출처 억제(**적재 성공을 DB에서 재확인한 뒤** 억제 — #65 공백 사고 순서). **thdcmp(2026-08-02, #65)** = 법제처 3단비교 API(`lawService.do?target=thdCmp&knd=2`) 정본 위임 — weight=4. **CHECK 제약에 source 값을 추가해야 적재됨**(신규 source 태그 도입 시 `law_graph_edges_source_check` 확장 필수 — #65에서 누락으로 적재 실패 후 수정) |
| law_delegations | **법령 위임 대응표**(#80·#81): parent_law·parent_article ↔ child_law·child_article, unique 4키. 출처 2계열 — ①법제처 3단비교 정본(`sync_law_delegations.py`, 법률↔시행령·시행규칙 조문 단위 1,586행) ②고시 제1조 역추출(`sync_notice_delegations.py`, 정규식·AI 미사용, child_article='전체' 230행). /law가 상·하위 조문 동시 제시에, 관계도가 delegation 엣지 생성에 사용. 재적재 안전(upsert + 성공 확인 후 stale 정리). 고시→상위 연결은 3단비교 범위 밖이라 역추출이 유일 경로. **③수기 확정표 `MANUAL_BASIS`(#82, 14건)** — 제1조가 없거나 근거를 안 쓰는 문서(협정문·분배표·공고)를 **상위 법령 조문에서 역방향 확인**(「…을 정하여 고시한다」가 그 문서를 지목)해 채움. **확정만 넣고 포괄 위임('법·영에서 위임한 사항'류)은 제외** — 잘못된 조문 엣지는 없는 관계보다 나쁘다. 정규식이 성공하면 그쪽이 이기므로 원문 개정 시 자동으로 비켜선다. DB 직접 삽입 금지(17시 prune_stale이 지움) |
| telegram_subscribers | 구독자 봇 가입자(chat_id PK). topic_briefing/urgent/assembly(각각 on·off), days(daily/weekday), briefing_hour(6~12, **'받기 시작 시각'** — 브리핑은 이 시각 1회, 긴급·법안은 이후 매시 :25 배달), last_briefing_sent_date·last_urgent_sent_at·last_assembly_sent_at(중복 발송 방지), ai_allowed(**기본 false** — AI 자문 승인 플래그), ai_count_date·ai_count(일일 20회 상한), **law_allowed(#100, 기본 false — `/law` 자연어 승인 플래그)**, law_count_date·law_count(일일 10회 상한). active는 봇 차단(403) 자동 처리 전용이며 화면에 버튼은 없다. **RLS 켜고 정책 0개 = service_role 전용**(chat_id는 개인정보, 프런트 노출 금지 — 의도된 설계) **unlimited boolean(#85)** — true면 /ask·/law 일일 상한 면제(카운터는 계속 올려 사용량 관찰). 구독자 속성이라 app_config가 아니라 이 행에 둔다. getSub이 select('*')라 컬럼만 추가하면 코드가 자동으로 읽는다. ⚠️ 비용 상한이 사라지므로 신뢰 인원에게만 |
| subscriber_queue | 긴급·법안 알림 큐(topic: urgent/assembly, html, created_at). 크롤러가 **발송 대신 적재**하고 send-subscriber-briefing이 각 구독자 수신 시각에 꺼내 보낸다. 억제·클러스터링(#44)·법안 상태변경 판정을 TS로 재구현하지 않으려는 구조. RLS 정책 0개. **topic=assembly 적재원 3곳(#120)**: assembly_crawler(국회 법안 단계변경·국회 입법예고) + gov_notice_crawler(부처 입법예고) + **assembly_minutes(과방위 회의록 다이제스트 — 신규 섹션·60일 이내·발언 3건↑일 때만, `subscriber_notify.format_minutes_digest()`, 2,500자 예산)**. 오프라인 임포트(minutes_offline)는 절대 적재하지 않는다 |
| telegram_usage (#100) | 봇 사용 이력(chat_id·command·query 200자·ok·result_note·created_at, 180일 보관). 종전엔 `ai_count`/`law_count` 숫자뿐이라 **무엇을 물었는지가 없었다.** `logUsage()`가 assem·law·law_article·ask·start에서 기록하며 **fail-open**(로깅 실패가 본 기능을 막으면 본말전도). 실패 경로도 `ok=false`+사유로 남긴다 — "검색했는데 안 나왔다"가 통계에서 빠지면 기준문 손볼 근거가 사라진다. **RLS 켜고 정책 0개 = service_role 전용** ⚠️ 생성 마이그레이션에서 RLS를 빠뜨려 공개 anon 키로 chat_id·질의 원문이 열려 있었다 — **텔레그램 계열 테이블을 새로 만들 때 RLS를 같은 마이그레이션에 반드시 넣을 것** |
| assembly_speeches (#99) | 회의록 발언자별 행(confer_num·speaker·topic·summary). 국감분은 `confer_num='audit-{MNTS_ID}'` 네임스페이스(상임위 `CONFER_NUM`과 값이 겹칠 수 있다). **원문(raw)은 저장하지 않는다** — summary가 잘못 생성되면 재요약이 불가능하니 **생성 시점의 검증이 유일한 방어선**이다(실제로 LLM 영문 거절문이 그대로 저장돼 화면에 노출된 적이 있다). **`topic`의 `SK텔레콤 언급` 칩은 규칙 기반·상시 부착(#120)** — 원문 블록이 `ALWAYS_KEEP_TERMS`에 걸리면 키워드 주제가 있어도 콤마로 **항상 덧붙인다**(종전엔 키워드가 없을 때만 → 4/28 이훈기 'SKT 영업정지' 행에 칩이 없었다). 대시보드는 topic을 콤마 분리해 칩으로 그린다 |

### Edge Function · RPC

| 이름 | 역할 |
|---|---|
| **claude-proxy (Edge)** | 대시보드의 **모든** Anthropic 호출(14곳)을 대신 수행(#104). ①`auth.getUser()`로 로그인 검증(**verify_jwt는 anon 키도 통과시켜 관문이 못 됨**) ②`profiles.approved` 확인 ③`charge_ai_usage`로 한도 차감(`body.stream===true`면 자문, 아니면 일반) ④모델 화이트리스트·max_tokens 상한 검사 후 **body를 그대로 전달**(cache_control·tools·thinking 보존) ⑤스트리밍은 `TransformStream`+`waitUntil(pipeTo)`로 통과. 키는 Edge Secret `ANTHROPIC_API_KEY`에만 존재 |
| charge_ai_usage / refund_ai_usage / get_my_quota (RPC) | 자문 한도(#104). 앞 둘은 **service_role 전용**(클라이언트 조작 방지) — 원자적 증가 + 팀 합산 advisory lock, 선차감 후 초과면 롤백. `get_my_quota`는 화면 표시용 본인 조회 |
| voyage-embed (Edge) | 질의 임베딩. VOYAGE_API_KEY는 Supabase Secrets(브라우저 노출 금지). **body.model로 모델 선택(하위호환)**: 미지정=voyage-4-lite(document_chunks 조문), `voyage-law-2`(kb_chunks 법령요약). 저장·질의 모델 반드시 일치 |
| match_kb_chunks_semantic / search_kb_chunks_trgm (RPC) | 법령요약(kb_chunks) 시맨틱/trgm 검색. 기본 `only_current=true`(구버전 제외). insert_kb_chunks(RPC)는 적재 시 청크 일괄 삽입(text→vector) |
| list_kb_documents (RPC) | 지식 베이스 문서 목록(doc_name 그룹핑) |
| submit_answer_feedback / admin_list_answer_feedback (RPC) | 답변 만족도(#103). 전자는 anon 실행 가능한 투표 제출(security definer) — `channel`은 프런트 값을 믿지 않고 서버가 chat_logs에서 읽고, `log_id` 충돌 시 upsert(사유는 coalesce로 보존). 후자는 기존 admin RPC와 같은 sha256 비밀번호 검증 후 피드백+원본 질문·답변·근거를 조인해 최근 500건 반환 |
| admin_delete_custom_file / admin_delete_chat_log (RPC) | 대시보드 삭제용(비밀번호 검증, security definer). **삭제된 행 수를 반환**하며 프런트는 0이면 실패로 처리한다. `document_chunks`·`chat_logs`는 RLS가 켜져 있고 DELETE 정책이 없어 프런트 직접 `delete()`가 오류 없이 0건으로 끝났다(#48) |
| list_kb_guide_docs (RPC) | `실무 안내` 탭 목록(현행본 203건). **body_md는 안 돌려준다** — 203건 합계 681kB라 브라우저로 내려받으면 안 되고, `has_table`(표 포함 여부)·`chunks`(청크 수)만 서버에서 계산해 준다. 본문은 클릭 시 그 문서 1건만 조회 |
| search_chunks_trgm / match_chunks_semantic (RPC) | trgm / pgvector 시맨틱 검색 |
| match_report_samples (RPC) | 보고서 샘플 시맨틱 검색(코사인). filter_type으로 유형 한정 |
| **`/law` 번호 조회는 DB 표기가 「N조」다(#92)** | `document_chunks.article_no`는 **`12조(교육과목 및 시간)`처럼 '제'가 없다** — 실측 「제N조」 0건 / 「N조」 7,587건. `handleArticleLookup`이 `제${artNo}조`로 조회해 **번호 직접 조회가 한 번도 동작하지 않았다.** 자연어 질의는 AI 검색 경로라 멀쩡해서 안 들켰고, 안내문에는 「조문 원문이 바로 나옵니다」라고 적혀 있었다. 지금은 `.or('article_no.ilike.N조%,article_no.ilike.제N조%')`로 두 형식을 모두 받고 비교 전에 앞의 '제'를 벗긴다. ⚠️ **문서에 「된다」고 쓰기 전에 그 경로로 한 번 돌려 볼 것** — 인접 경로가 되면 전체가 되는 줄 알기 쉽다 |
| **뉴스 2차 묶기 = Haiku 의미 판정(#92)** | 키워드 클러스터링(`cluster_star`, 공유 3개)으로 못 묶인 **대표들만** `news_dedup.group_same_event()`로 다시 묶는다. 매체마다 관점이 달라 제목 어휘가 안 겹치는 사건이 있다(공정위 불공정약관 4건: 쌍별 공유 **최대 1개**). 프롬프트의 **「하나의 처분·발표를 여러 각도에서 쓴 것은 같은 사건」 문장이 결정적** — 이 문장 없이는 2묶음, 넣으면 실전 조건(다른 사건 혼재)에서 정확히 1묶음. **오묶음 실측 0건.** ⚠️ **클러스터링에만 쓰고 억제(`is_followup`)에는 쓰지 말 것** — 묶기가 틀리면 「(관련 보도 N건)」으로 남지만 **억제가 틀리면 알림이 사라져 되돌릴 수 없다.** ⚠️ **임계값 3→2 금지**(#44: KT 해킹 과징금과 5G 과장광고가 한 사건이 된다). 응답 번호가 1~N과 불일치하면 **부분 신뢰 없이 통째로 버린다**(fail-open). 비용은 실행당 최대 1회·수백 토큰. `extract_keywords`는 한글 토큰에도 **조사를 뗀다**(종전엔 금액에만 떼서 「약관」≠「약관에」였다) |
| telegram-webhook (Edge) | 구독자 봇 수신부. `/start`·`/settings` 인라인 키보드(수신 토글 버튼 **'🏛️ 국회·법률 동향'** — 2026-09-03 '법안 동향'에서 개명, callback `t:assembly`·컬럼 `topic_assembly`·큐 topic `assembly`는 그대로. 국회 법안+국회·부처 입법예고+과방위 회의록 다이제스트를 한 토글로 받는다, #120), `/law "OO법 N조"` 조문 원문 즉답, `/ask` AI 자문(승인제), `/admin`(운영자), **주요 뉴스 '더 보기' `mn\|` 콜백(#105 — `news_feed` 읽기 전용, 큐·워터마크 무접촉)**. **verify_jwt off** 대신 `X-Telegram-Bot-Api-Secret-Token` 검증. 오류가 나도 200을 반환한다 — 비200이면 텔레그램이 같은 업데이트를 무한 재전송한다 |
| assembly-search (Edge, #98) | 대시보드 "원문 검색" 탭용 CORS JSON 엔드포인트. 국회회의록시스템을 **실시간 검색**한다(DB 무관). `telegram-webhook`과 **`_shared/assembly_search.ts`를 공유**하되 두 함수가 **각각 번들**하므로 그 파일을 고치면 **반드시 둘 다 배포**할 것 — 한쪽만 하면 텔레그램과 웹이 같은 질문에 다르게 답한다 |
| admin-daily-report (Edge, #100) | 매일 **09:00 KST**(pg_cron `0 0 * * *` UTC) 운영자에게 구독자 목록·권한(자문/법령)·수신 설정·관심분야·명령 사용 통계를 텔레그램으로 보낸다. Vault `admin_report_cron_secret` → `x-cron-secret`, **`--no-verify-jwt` 배포 필수**. 180일 초과 `telegram_usage` 정리도 같은 잡이 겸한다. ⚠️ **'최근 발송 브리핑'은 일부러 뺐다** — 매일 같은 날짜가 찍혀 신호가 되지 못한다(운영자 지시). 리포트에는 **변하는 것만** 싣는다 |
| send-subscriber-briefing (Edge) | 구독자 정시 발송. pg_cron이 매시 호출 → 브리핑(daily_briefings)+긴급·법안(subscriber_queue)을 **수신 시각이 도래한 구독자에게 한 번에** 보낸다. `briefing_hour <= 현재KST시` catch-up이라 브리핑이 늦게 생성돼도 다음 정각에 따라잡는다. `x-cron-secret` 검증. **주요 뉴스 마지막 조각에 '더 보기' 버튼을 굽는다(#105)** — 구간은 `last_urgent_sent_at`(없으면 당일 00:00) ~ `maxCreatedAt(urgentEligible)`, 즉 **워터마크 전진값과 같은 값**이라 앞뒤 버튼이 빈틈없이 맞물린다. 브리핑·법안 메시지에는 붙이지 않는다 |
| **'더 보기' 인코딩/디코딩은 한 파일에(#105)** | `_shared/news_more.ts`가 굽기(발송 함수)와 읽기(웹훅)를 **둘 다** 들고 있다. 두 함수에 흩어 두면 한쪽만 고쳤을 때 **에러 없이 '만료된 버튼'만 응답**해 원인을 찾기 어렵다. `callback_data` 64B 상한은 `TextEncoder` 길이 검사로 지키고, 초과하면 버튼을 생략한다(assemCallbackData와 같은 방식) |
| supabase/functions/_shared/ | 두 함수 공용 모듈. `telegram_format.ts`(HTML 이스케이프·분할·발송, 400시 plain 폴백), **`/law` 조문 검색은 배제가 아니라 가중치(#88)** — `match_law_articles_semantic`이 종전 `article_no !~ '^(부칙|서식|별표|별지)'` 로 완전 배제하던 것을 정렬 가중치로 바꿨다. 조문 +0.08 / 별표·붙임 0 / 부칙·서식·별지 −0.05 / 파일문서 −0.10. **배제하면 영영 도달할 수 없다** — 「전파법 시행일은?」의 답은 부칙에 있고, 조문이 안 가리키는 별표가 463개 중 65개다. 실측상 조문이 이미 별표보다 유사도가 높아(0.570 vs 0.531) 하드 필터가 불필요했다. `similarity` 반환값은 원본(가중치 미반영) — 정렬에만 적용. **ORDER BY의 `+ 0.0` 제거 금지**(HNSW 무력화 = 전수 정밀 스캔. 없으면 상위 40건만 훑어 가중치가 무의미). **가중치로 부칙을 열었으면 프롬프트도 함께 고칠 것(#88 후속)** — 열어만 두면 「못 찾음」이 **「자신 있게 틀린 답」**으로 바뀐다(실제로 전파법 시행일을 부칙 제20067호를 근거로 2024.7.23이라 답했다. 현행은 2026.1.2). 조치 ①**`/law` 컨텍스트에 시행일을 분리 표기** — `answerLawQuery`는 `buildRagContext`를 쓰지 않고 자체 포맷을 써서 시행일 항목이 통째로 없었다. `doc_name`을 파싱해 `전파법 [법률 | 제21065호 | 시행일 2026-01-02]` + 조항 별행으로 나눈다(종전엔 괄호 숫자 넷이 나란히 붙어 어느 게 시행일인지 구분할 근거가 없었다). ②프롬프트 규칙 — 시행일은 **메타 기준**으로 답하고 부칙은 **개정 하나하나의 이력**이라 법 전체의 시행일이 아님을 명시(전파법 부칙만 19개). **자문과 `/law`가 같은 일을 다른 코드로 하고 있어 한쪽만 개선돼 있던 것이 원인** — 한쪽을 고치면 반드시 다른 쪽을 확인할 것. `rag.ts`(자문 RAG — 조문+법령요약+조문정밀검색+수집뉴스 → Sonnet). **실무 용어 → 법령 용어 보강 `PRACTICE_TERMS`/`expandQueryForSemantic`(#83)** — 「리파밍」·「커버리지」처럼 **법령에 한 번도 안 나오는 업계 용어**는 원문 그대로 임베딩하면 유사도가 잡음 수준에 묻힌다(실측: 리파밍 1위가 약관규제법 0.441 → 보강 후 전파법 제6조의2 0.541). 원 질의는 지우지 않고 **뒤에 덧붙이며**, 확신하는 대응만 넣는다(틀린 대응은 엉뚱한 조문을 1위로 올려 없느니만 못함). 키워드 검색(`lawSynonymKeywords`)에도 같이 먹인다. **`app.js`에도 같은 표를 둔다(#89)** — 봇에만 있어 대시보드에서는 「리파밍」이 보강되지 않고 있었다 | 
| **자문 조문 갈래는 키워드+의미 2벌(#89)** | `answerAdvisory`(rag.ts)·대시보드 자문(app.js) 모두 **키워드(`searchLawArticles` 5개) + 의미(`match_law_articles_semantic` 5개, 상한 10)**를 「조문 정밀검색 결과」 한 섹션에 이어 붙인다. 필터는 `/law`의 `semExtra`와 동일 — **조문만(`^\d+조`)**, 파일 문서 제외, RAG·키워드분 중복 제거. **RAG 15자리(`TOTAL_CHUNK_CUT`)는 건드리지 않는다** — 보도자료·회의록 근거가 밀려나지 않게 하는 약속이다. **키워드만으로는 어휘 간극을 못 넘는다**: 「기지국 개설 허가 절차」는 낱말 「기지국」에 끌려 해상무선통신망 규정으로 새고 정답 전파법 21조를 못 찾았고, 「주파수 재할당 대가 산정 기준」은 전파법 10·11·12·13·15조가 연번으로 자리를 채워 「대가 산정」 조문이 하나도 없었다(정렬 동점이 문서명·조문번호 순이라 생기는 현상). 비용은 자문 1회당 ≈8원. ⚠️ **`match_threshold` 0.45는 병목이 아니다 — 낮추지 말 것**(0.45/0.35/0.25/0.0 실측에서 8자리 중 7~8을 이미 채웠고, 낮추면 해외규제동향·논문 조각만 들어온다). ⚠️ **`article_no` 가점은 아직 평평하다**(`rag.ts`·`app.js` 각 1줄, 종류 불문 `+0.5/(K+1)`) — 조문은 `article_no` 보유분의 41%뿐이라 별표·부칙이 동급 가점을 받는다. 등급화는 이 갈래 추가 뒤 **재측정하고 정할 것**(가중치는 후보 안의 순서만 바꿔, 후보에 조문이 없으면 무력하다). ⚠️ **출처 목록은 조문(extra)을 맨 앞에 놓을 것** — 텔레그램 footer(`sources.slice(0,6)`)도 대시보드 배지(`sourceTagsHtml(..., 6)`)도 **앞 6개만 보여준다.** RAG 15개를 먼저 채우면 답변이 인용한 조문이 잘려 나간다(실제로 전파법 제21조제2항을 [원문 확인됨]으로 인용해 놓고 출처에는 지방세법 시행령·논문·세미나 자료만 보였다). **컨텍스트에 잘 넣는 것과 사용자가 확인할 수 있는 것은 다른 문제** — 상위 N만 보여주는 자리는 그 N의 순서까지 함께 설계한다 |
| **별표 동반 인출은 봇·대시보드 공통(#90)** | 법령 조문은 실제 숫자를 안 담고 별표로 넘긴다(전파법 시행령 제14조 = "별표 3에 따라 산정한다"). `buildAnnexContext`가 그 별표를 함께 싣는다 — `app.js:903`과 `rag.ts` 양쪽에 **동일 로직**(한쪽만 고치지 말 것). 종전에는 **봇에 아예 없어** 텔레그램에서 금액·요율을 물으면 「별표 3에 따라 산정합니다」로 끝났다(대시보드는 315개 별표가 이 경로로 닿고 있었다). 상한 `ANNEX_MAX_UNITS=2`·`ANNEX_MAX_CHUNKS=6`(별표 하나가 최대 812청크라 필수), **첫 청크(표 머리=열 이름)는 무조건 포함**(가운데만 넣으면 「│1만원│―│―│」이 무슨 항목인지 모른다), 잘리면 「일부만 실었습니다」를 모델에 고지, 타 법령 인용(`「전기통신사업법」 별표 3`)은 건너뜀(978건 중 90건). **입력은 RAG + 조문 정밀검색분** — RAG만 넘기면 조문 섹션에만 있는 조문의 별표 인용을 놓친다(실측: 「전파사용료 산정」이 별표 없음 → 전파법 시행령 별표 8·9). ⚠️ **`/law`에는 넣지 않는다**(조문 원문 즉답·20초 성격). ⚠️ **텔레그램 지침에 「별표의 표를 그대로 옮기지 말고 해당 항목의 값만 문장으로 인용」이 있어야 한다** — 별표는 괘선 문자(`┌─┬─┐`) 표라(괘선 비율 39~44%) 고정폭이 아닌 텔레그램에서 정렬이 무너진다. 「마크다운 표 금지」로는 안 걸린다. ⚠️ **별표 역참조 인덱스는 만들지 않았다** — 조문이 안 가리키는 별표는 479개 중 23개뿐이고 그중 16개는 **조문 본문이 이미지라 인용이 텍스트로 안 남은 것**(OCR로 해결). 순수 이득 7개 |
| **RAG `article_no` 가점은 종류별 등급(#90)** | `rag.ts`·`app.js`의 `articleBonus()` — 조문 `+0.5/(K+1)` · 별표·붙임 `0` · 부칙·서식·별지 `−0.5/(K+1)` · 파일문서 `−0.5/(K+1)`(별도). 종전 「`article_no`가 있으면 종류 불문 가점」은 실DB에서 보유 18,349개 중 **조문이 41%뿐**이라 별표·부칙이 동급 가점을 받았다(「주파수 재할당 대가」 15자리를 별표 7개가 먹고, 「개인정보 유출」은 부칙이 2자리). 실측 75자리 중 8자리 교체·**악화 0건**이며, 새로 오른 조문 8건은 조문 섹션(#89)과 **중복 0** — 두 경로는 보완 관계다. 별표·붙임은 **배제가 아니라 가점만 뗀다**(#88 원칙) |
| **조문 이미지 OCR(#91)** | 기술기준 수치가 이미지에만 있는 조문을 텍스트로 되살린다. 도구는 `tools_ocr_fetch.py`(수집·PNG 변환)와 `tools_ocr_apply.py`(치환·임베딩 NULL). 취득은 `https://www.law.go.kr/LSW/flDownload.do?flSeq=<id>` — **id는 연속 번호가 아니라 본문 `<img id="…">`에서 읽는다.** 받은 파일은 **확장자가 gif여도 실제 BMP인 경우가 있어** PNG 변환 후에야 읽힌다. ⚠️ **반드시 3배 확대해 읽을 것** — 축소본에서 「특수유닛→복수유닛」·「외무노출→외부노출」 2건을 실제로 잘못 읽었다. ⚠️ **`content`를 고치면 `embedding`을 같은 update에서 NULL로 만들 것** — `backfill_embeddings.py`는 NULL만 채우므로(62행) 안 그러면 「고쳤는데 검색은 그대로」가 된다. ⚠️ **원본 `<img>` 태그는 주석으로 보존**(되돌리기 근거). ⚠️ **법제처 원문 오타는 고치지 않는다**(제16조 `AMI(Alternate mArk Inversion)` — 표준은 Mark). ⚠️ **판독이 불확실하면 추정으로 채우지 말고 `[원문 이미지 확인 필요]`로 표시할 것** — 제24조 주5의 `F` 아래첨자는 5배 확대에도 안 읽혔다. 추정으로 채우면 그것이 곧 조용히 틀린 답이다. ⚠️ **조문 제목만 보고 이미지 성격을 단정하지 말 것** — 제24·26조를 「아이 패턴·스펙트럼 폭 = 파형 그래프」로 단정해 제외했다가, 열어 보니 20개 **전부 수치표**였다(「아이 패턴」은 표 안의 한 행). **처리 완료**: 1군 7개 조문(단말장치 5·16·17·18조, 경고문구 2조, 이동전화망번호 4조, 무선종사자 12조) + 단말장치 24·26조 6청크. **미처리**: 2군 신고면제 무선기기 고시 9개 조문/26개 이미지, 3군 항공·해상·간이무선국·전기통신번호세칙·지방세법 등 34개 조문/43개 이미지(본문 150~380자로 이미 충분). 전체 대상은 **52개 조문/15개 문서/이미지 81개**이며 **전수 대조가 가능한 만큼만 한다** — 형식적 대조는 「검증했다」는 기록만 남기고 오독을 통과시킨다. 참고: 청크 경계에서 잘린 `<img` 조각이 **원래부터** 있어 `<img` 문자열 수와 완전 태그 수가 어긋나는 청크가 있다(적재 시 분할 아티팩트, 사고 아님) |

### Storage

- **uploads (private)**: 추가지식·보고서 원본 보관. anon insert/select/delete(화면 업로드·삭제가 직접 쓰므로 유지 — 로그인 미도입 방침). 다운로드는 createSignedUrl(60초). public화 금지.

### RLS (2026-08-02 전면 재정비 — 개선⑩ 1단계, 배경역사 #57)

**원칙: 로그인은 도입하지 않는다(운영자 방침 — 팀원 누구나 로그인 없이 전 기능 사용). 대신
"대시보드 화면이 실제로 하는 연산"만 anon에 허용하고 나머지는 전부 service_role 전용으로 잠근다.**
공개 GitHub Pages + anon 키 구조라 **anon에 열린 권한 = 전 세계에 열린 권한**임을 전제로 설계.

| 분류 | 테이블 | anon 허용 |
|---|---|---|
| 읽기 전용 | law_amendments·assembly_bills·law_diffs·law_watch·law_pending·feedback_rules·system_health·kb_documents·kb_chunks | select만 |
| 화면 기능 | news_feed | select·update·**delete**(기사 삭제 버튼) — insert 없음 |
| | daily_briefings | select·update(긴급도 수정 시 본문 동기화) |
| | deleted_news | select·insert (**append-only**) |
| | **chat_logs** | anon은 **insert만**. 읽기는 **로그인 계정의 RLS 스코프**(#104) — 본인 / 팀장=자기 팀 / admin=전체(텔레그램 행은 user_id가 없어 admin만). 건수는 `chat_logs_month_count()` |
| 로그인 필요 | **profiles·teams·advisory_usage·answer_feedback** | anon 정책 없음. authenticated에 역할별 SELECT(본인/팀/admin), profiles·teams UPDATE는 admin만. AI 호출은 `claude-proxy`가 JWT를 검증한다 (#104) |
| | importance_feedback·tech_terms | select·insert·update |
| | custom_knowledge | select·insert·update·delete (팀원 기여 창구) |
| | law_graph_nodes·law_graph_edges | select·insert·update (delete는 service 전용 — 병합만) |
| 조건부 | **app_config** | select 전체 / insert·update는 **`key in ('claude_key','press_keywords')` 행만** |
| | **document_chunks** | select / insert는 **`is_approved=false` 강제**(승인 대기로만 들어옴) |
| service 전용 | telegram_subscribers·subscriber_queue·alert_suppress_log·changes·documents·system_status | 정책 0개 |
| | **answer_feedback** | 정책 0개 — 쓰기는 `submit_answer_feedback` RPC(anon 실행 가능, 조회 불가), 읽기는 `admin_list_answer_feedback`(비밀번호). 공개 페이지에 남의 평점·불만 사유를 노출하지 않으려는 구조 (#103) |
| 쓰기 회수 | report_samples·report_style_rules·report_feedback·report_directives | select만 (보고서 메뉴 숨김 상태 — ⑦ 부활 시 재개방) |

- **app_config 행 제한의 이유**: `system_prompt`는 telegram-webhook Edge Function이 봇 자문
  시스템 프롬프트로 그대로 읽어간다. anon이 이 행을 바꿀 수 있으면 대시보드 키 하나로 봇의 지시문을
  교체하는 **크로스 채널 프롬프트 인젝션**이 성립한다. 화면이 쓰는 2개 키만 남기고 봉쇄.
- **document_chunks `is_approved=false` 강제의 이유**: 화면 업로드는 원래 승인 대기로 저장되지만
  그건 app.js의 규칙일 뿐이라, API 직접 호출로 `is_approved=true` 문서를 꽂으면 승인 대기줄에
  나타나지도 않고 자문 근거로 즉시 쓰인다(RAG 코퍼스 주입). DB 차원에서 차단.
- **PostgREST 응답 주의**: 정책에 걸린 UPDATE는 401이 아니라 **"0행 수정" 204**로 돌아온다.
  차단 여부는 응답 코드가 아니라 **실제 값이 바뀌었는지**로 확인할 것.
- 신규 테이블을 만들면 **RLS를 켜고 정책 0개(=service 전용)로 시작**해, 화면이 실제로 필요로 하는
  연산만 하나씩 여는 순서를 지킨다.
- 2단계(Supabase Auth 로그인 도입, 운영 기능을 authenticated로 이관)는 **운영자 판단으로 보류**.

### pg_cron 스케줄 잡 (DB 내부 스케줄러, UTC 기준 / KST=UTC+9). `select * from cron.job`로 조회.

✅ **GitHub 계정 복구 완료(2026-08-25) — 디스패치 잡 전부 재활성.** 8/1 정지로 비활성했던 4개(`crawl-trigger-hourly`·`assembly-crawl-trigger`·`law-crawl-trigger`·`watchdog-trigger`)를 되살렸고, `foreign-press-trigger`(jobid 19)를 신설했다.

**[트리거 3층 구조 — 2026-09-01 실측으로 확정]** 이 표가 장애 대응의 출발점이다.

| 층 | 경로 | 정확도 | 고장 영역 |
|---|---|---|---|
| **주** | pg_cron → `dispatch_github_workflow()` → GitHub Actions | **초 단위 정시** | Supabase + **GitHub** |
| 보조 | 워크플로의 `schedule:` (GitHub 자체 cron) | **2~7시간 지각** | **GitHub** |
| 독립 | PC Windows 작업 스케줄러 | 정시 | PC |

- **주·보조는 같은 고장 영역이다 — 서로의 백업이 아니다.** 둘 다 종착지가 GitHub Actions라, GitHub이 죽으면 함께 죽는다. 2026-08-01 계정 스팸 플래그 때 실제로 그랬다(pg_cron은 멀쩡히 발화했지만 디스패치가 막혔고, GitHub cron도 함께 정지). 그때 시스템을 살린 것은 **PC**였다. "GitHub cron이 있으니 백업은 된다"고 착각하지 말 것.
- **GitHub 자체 cron은 복구 후 되살아났으나 심하게 밀린다**(2026-09-01 실측: 해외동향 pg_cron 05:30 정각 대 GitHub 09:01, 브리핑 06:05 대 09:10). GitHub cron은 원래부터 혼잡 시 지연·드롭이 잦다(2026-06-15에 23~00 UTC 최혼잡 구간을 피해 21 UTC로 옮긴 이력). **따라서 하루 2회 실행되는 로그는 정상이다** — 정시 쪽이 pg_cron, 늦은 쪽이 GitHub cron이다. 중복 발송은 `already_sent_today()`가, 중복 판정은 캐시 건너뜀이 막고, 저장소가 public이라 Actions 사용료는 0원이다.
- **`schedule:` 줄을 지우지 말 것.** 로그 이중화가 거슬려 제거를 검토했으나(2026-08-25 메모) **유지가 결론이다.** GitHub은 멀쩡한데 pg_cron 경로만 끊기는 무음 실패(배경역사 #18 — PAT에서 Actions 권한이 빠져 디스패치 403인데 pg_cron은 `succeeded`로 보고)에서 늦게라도 도는 유일한 장치가 이것이다.
- **독립 백업은 PC뿐이며, 지금은 브리핑에만 있다.** `RadioPolicy-BriefingBackup`(매일 09:40)이 `morning_briefing.py`를 한 번 더 돌려 미발송이면 그때 보낸다(이미 나갔으면 건너뜀 — 실측 확인). **수집 계열(뉴스·법안·법령·해외동향)에는 독립 층이 없다** — `radio_TEMP_*` 5개는 비활성 상태다. GitHub이 또 정지되면 `schtasks /change /tn <이름> /enable`로 즉시 되살릴 것.

**PC 임시작업 5개는 2026-08-26 전부 비활성화**(`radio_TEMP_crawl_hourly`·`briefing_0605`·`assembly_1000`·`law_1130`·`foreign`) — GitHub 단독 야간 운전을 하루 성공(8/25~26, 시간대별 수집 연속·해외동향 `fail=0`·감시견 `ok`)한 뒤 정리했다. **삭제가 아니라 비활성이므로 GitHub이 다시 죽으면 즉시 되살린다.** PC에 남는 것은 한국 IP 필수 작업과 브리핑 백업뿐: 정부공고 체인(17:00)·본문 재수집(매시 :22)·회의록 요약(10:30)·CRMS(월1회)·브리핑 백업(09:40)·로컬 미리보기. **밤·주말 PC 종료 가능.** (배경역사 #115)

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
| 19 | foreign-press-trigger | `30 20 * * *` | 05:30 | **해외 규제동향 트리거(2026-08-25 신설)** → foreign_press.yml dispatch. FCC·Ofcom·BEREC·日총무성·ITU는 한국 IP가 불필요해 Actions에서 돈다 — 그전까지 PC 임시작업만 담당해 PC가 꺼지면 그날치가 통째로 빠졌다. 06:05 브리핑보다 앞서야 그날치가 실린다 |
| 16 | watchdog-scan-3x | `10 */3 * * *` | 3시간마다 :10 (00:10·03:10·…·21:10) | **내부 워치독 전수 감시** `watchdog_scan(false)` — system_health 10키 키별 임계+note 실패신호, 재알림 억제, 이상 시 1건 요약(Vault `telegram_bot_token`). :10은 :00/:35 잡과 겹치지 않게 오프셋 |
| 18 | admin-daily-report | `0 0 * * *` | 09:00 | **운영자 일일 리포트**(#100) — 구독자 목록·권한·수신 설정·명령 사용 통계. `trigger_admin_report()` → Vault `admin_report_cron_secret` |
| — | subscriber-briefing-hourly | `25 * * * *` | 매시 :25 | 구독자 정시 발송 → send-subscriber-briefing. `:25`는 06:05~06:20 브리핑 생성 창을 피한 값. 대상이 없으면 no-op이라 매시 돌아도 부담 없음. Vault `subscriber_cron_secret` 사용 |

- 공용 디스패치 함수 `dispatch_github_workflow(p_workflow)` + `trigger_briefing_if_missing()`. 인증: GitHub PAT을 Supabase Vault `github_pat`에 저장. 텔레그램 토큰은 Vault `telegram_bot_token`.
- ⚠️ PAT 만료/회수 시 모든 트리거가 조용히 멈춤 → Vault `github_pat` 갱신. **PAT 재생성 시 권한 3종(Contents R/W·Metadata·Actions R/W) 반드시 확인 — Actions 누락 시 workflow_dispatch가 403인데 pg_cron은 'succeeded'로 찍혀 무음 실패. 교체 검증은 cron 잡 상태가 아니라 `net._http_response.status_code`(204=성공)로 한다.** (설계 배경·드롭 경위·#18 사고는 배경역사 문서 참조)

### 워치독 이원화 (GitHub health_watchdog + Supabase watchdog_scan) — 배경역사 #62

감시자가 감시대상 플랫폼과 함께 죽는 사각을 없애기 위해 워치독을 **다른 두 플랫폼**에 둔다. 2026-08-02 GitHub 계정 정지로 외부 워치독이 GitHub과 함께 죽어 뉴스 크롤러가 15시간 무알림이던 사고가 계기.

- **외부** `health_watchdog.py`(GitHub Actions, Supabase 독립) — 뉴스·브리핑 신선도 + daily_crawl·morning_briefing·law_crawl·assembly_crawl 4종 워크플로우 성공 이력 + "Supabase 접속 불가" 자체 감지.
- **내부** `watchdog_scan(p_dry_run boolean default true)`(pg_cron jobid 16, 하루 3회, GitHub 독립) — `system_health` **10키 전수** 감시. 키마다 다른 임계(매시류 3h / 하루1회류 26h / foreign 30h / itu 40일). note에 `fail=N`·`failed=N`·`실패 N`이 N>0면 "돌았지만 실패"로 별도 경고(**`new=0`은 정책 크롤러 정상값이라 신호 아님**). 이상 키+유형을 md5 시그니처화해 `system_health.watchdog_alert_state`에 저장 → 직전과 다를 때만 1건 요약 발송(재알림 억제), 정상 복귀 시 `ok`로 리셋. 발송은 Vault `telegram_bot_token`→`net.http_post`→chat 344506450. 기본 인자가 dry라 **수동 점검 `select watchdog_scan();`은 발송 없이 이상 목록만 반환**(실발송은 cron의 `watchdog_scan(false)`).
- ⚠️ **남은 사각**: 둘 다 감시자↔감시대상이 다른 플랫폼이 됐지만, **Supabase 자체가 다운되면 watchdog_scan도 함께 죽는다**(외부가 "접속 불가"로 일부만 커버, 그것도 GitHub 생존 시). 완전 3중화(Supabase·GitHub 무의존 외부 제3지점 폴링)는 후속 과제.

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
- **주제 엣지 품질 규칙 (2026-09-05 신설 — 배경역사 #123).** 주제→법령 엣지(seed·ai)의 `description`은 전문가가 보는 문장이자 노드 카드 📌 조문 발췌의 열쇠다. 2026-09-05 전수 검증에서 356건 중 214건이 조문 오류·자리표시였고(ai 엣지가 주범, seed도 다수), 정정 후 두 겹의 방어를 두었다:
  ① **저장 전 검증 관문(app.js `lawmapVerifyRelation` → `saveLawmapData`)** — 자문 축적·탭 즉석 생성·AI 보강 세 경로 모두 통과. 대상 문서를 `document_chunks`에서 찾고(가운뎃점 `·`/`ㆍ` 양쪽·공백 무시·"(부처) 고시명" 접두 허용, 이름 바로 뒤가 `(`인 문서만 — '전파법'이 '전파법 시행령'에 붙지 않게), `basis`의 조문이 `article_no`에 있는지 대조('제19조(…)'/'19조(…)' 두 형태). **문서 있음+조문 있음 → 저장 / 문서 있음+조문 없음(또는 basis 자체 없음) → 저장 안 함 / 문서가 KB에 없음 → `[원문 KB 미보유 — 미검증]` 꼬리표를 달아 저장**(등재 후보로 남김). 조문 체계가 없는 문서(공고·협정·NFTC)는 basis 없어도 통과. 검증 자체가 실패하면 저장하지 않는다(fail-closed). 검증 통과 관계가 없고 주제도 없으면 **빈 주제 노드를 만들지 않는다**. 결과는 상태줄·답변 밑 미니 관계도에 "조문 미확인으로 제외 N건: 법령(사유)"로 표시 — 조용히 버리지 않는다.
  ② **야간 전수 점검 `lawmap_edge_check.py`**(17시 체인 마지막 단계, 읽기 전용) — 판정 규칙: 자리표시(`관련 조문`·`제N조`·`(관련)`) ERR / 자기 조문이 원문에 하나도 없음 ERR / 조문 번호 없음 ERR(단 `[원문 KB 미보유/미등재…]` 꼬리표·별표/별지/붙임/서식 번호·조문 체계 없는 문서는 OK) / 일부 조문 미존재·타 법령 조문만 인용·미보유 무표기 WARN. **타 법령 조문 판별**: 조문 앞 낱말이 `…법/령/규칙/고시/규정/기준/지침`이고 대상 노드명이 아니면 교차 인용; `법 제N조`·`영 제N조` 약칭은 항상 교차; 대상이 고시·지침이면 `…법 제N조`는 노드명에 그 법명이 들어 있어도 교차(단말 유통 과징금 세부기준 ↔ 사업법 제52조의3); 연결부호(`·`, `~`)로 이어진 뒤 조문은 앞 조문 판정을 상속, `,` 뒤는 새 문맥; `제N조 위임/에 따른`은 교차. 조문 존재는 **같은 base의 모든 판(현행·시행예정·구판) 합집합**으로 본다(노드 doc_name이 조문 파싱 빈 구판 PDF를 가리켜 오탐 — 지방세법 시행령). `부칙`·`별표`·`별지`·`붙임`만 있는 문서는 조문 체계 없음으로 취급(공정위 예규·고시 10여 종이 no_article로 쏟아진 오탐의 원인). 2026-09-05 정정 완료 시점 기준선: 347건 중 ERR 0·WARN 0.
  ③ **설명 작성 규칙(세션·운영자 공통)**: 근거 조문 번호 필수(`제N조`, `제N조의M`, 나열 `제6·18조`, 범위 `제67~68조` 허용) — 고시 전체가 주제이면 목적·핵심 조문(`제1조·제3조`)으로 특정; 타 법령 조문은 반드시 법령명을 앞에 붙여 쓴다(`사업법 제28조④`, `영 제14조`); 원문이 KB에 없으면 `[원문 KB 미보유 — 사유]`를 붙인다; 자리표시·일반어(`관련`, `관련 조문`, `해당 조문`) 금지.
- **노드명↔문서명 대조는 정규화 후에만** — 문서명은 `ㆍ`(U+318D)와 `·`(U+00B7)가 섞여 있고(표시ㆍ광고의 공정화에 관한 법률), 노드 doc_name에는 `.pdf` 꼬리가 남은 것이 74건 있었다(청크는 `.pdf` 없음 → 노드 카드 조문 발췌·원문 보기가 `eq(doc_name)`로 조용히 비었음, 2026-09-05 교정; 청크가 아예 없는 4건은 그대로 — 캐나다 MRA·방발기금 운용관리규정·재난안전 무선국 업무처리규정·적합성평가 부정행위 운용요령). LIKE 한 번으로 "미보유" 판정하지 말 것 — 검증 에이전트가 표시광고법을 미보유로 오판한 사례. `lawmap_edge_check.nrm()`·app.js `lmNormName()`이 정규화 정본.
- vis-network는 CDN(unpkg, 9.1.9 고정) **지연 로드** — lawmap 탭 첫 진입 시에만. 다른 탭 성능 무관.
- 전체 뷰는 **'전파정책 관련 법'만**: 코어 = 주제 + 주제·시드에 연결된 법 + 그 법의 계열(하위법령). 엣지 = 시드·주제 엣지 + (코어 내부의 계열·인용). 실측 ~176 노드/523 엣지(2026-07-30, 주제 51개 — 이동통신사업 계열 18주제·전파사용료 포함 일괄 시드 후. 배경역사 #34). **지방세법처럼 세금 감면 조항에서 농지법·축산법·의료법 등 타 분야 법을 대량 인용하는 허브의 바깥 인용은 코어 밖이라 제외** — 그 허브의 전체 인용은 노드를 클릭해 드릴다운할 때만 표시(운영자 피드백: 전체 뷰에 무관한 법이 들어옴). **인용망 전체를 무필터로 펼치지 말 것**(농지법 등 노이즈 재유입). **안정화(stabilizationIterationsDone) 후 physics를 꺼서 노드가 계속 흔들리는 현상 방지 — 끄지 말 것**. 라벨은 배경색 strokeWidth 외곽선(제거 금지). 주제 포커스 뷰는 직접 이웃+계열(하위법령) 1단계만 확장(허브 법령 경유 폭발 방지).
- 노드 상세 카드는 **주제 맥락 인식형**: 주제 포커스 중 법령 클릭 → ① 🎯 이 주제에서의 역할(엣지 설명) ② 📌 근거 조문 원문 발췌(엣지의 "제N조"를 document_chunks에서 조회 — article_no가 문서마다 '제19조(...)'/'19조(...)' 두 형태라 양쪽 매칭 필수) ③ 연결 관계는 현재 그래프 범위만. 법령 전체 요약(OKF)은 역할·근거 조문 아래에 **펼쳐서** 표시(주제 맥락이 위에 오므로 전체 요약도 함께 보이는 게 유용 — 운영자 피드백). 📌 조문 발췌는 **추측이 아니라 법령 구조로** 정확히 집는다(운영자 피드백: 가점 땜질 말고 근본 해결). 우선순위 3단계:
① **명시 조문** — 관계 설명의 "제N조"(제24~25조 범위·제N조의M 포함) → "근거 조문".
② **위임 연결(delegation)** — 노드가 시행령·시행규칙이면, 그 상위법에 대한 주제 엣지의 근거 조문 N을 찾아 하위법령 본문에서 **"법 제N조"를 인용하는(=위임받는) 조문**을 집음(인용 횟수순). 한국 시행령·시행규칙은 자기가 구체화하는 상위법 조문을 본문에 명시하므로 결정론적. 예: 주파수 분배(전파법 §9) → 전파법 시행령에서 "법 제9조"를 인용하는 §10-2(주파수분배 변경 지원). "관련 조문(위임 근거)" 라벨.
위임 후보군이 있으면 그 안에서 키워드+시맨틱 관련성으로 순위("위임 근거+관련성" 라벨). "권한의 위임·위탁" 등 여러 조문 나열하는 집계성 조문은 배제(LAWMAP_ART_BOILER).
**주제 포커스는 직접 연결만 그린다(#93)** — `lawmapNeighborhood`가 topic 중심일 때는 계열(하위법령) 확장을 하지 않는다. 종전에는 계열 1단 확장으로 직접 3개짜리 주제가 52노드 헤어볼이 됐다(전파법이 이웃에 들어오면 그 아래 고시 49개가 딸려옴). 직접 이웃끼리의 계열 선(법률—시행령—고시)은 엣지 필터가 살리므로 3단 골격은 그대로 보인다. **법령 노드 포커스의 계열 확장은 유지** — 전파법 클릭 → 계열 137노드 보기는 다른 용도다. 주제 포커스 중 계열 간접 노드의 조문 검색 로직도 법령 포커스에서 쓰이니 제거 금지.
③ **최후 폴백 — 키워드+시맨틱 하이브리드** — 위 둘로 안 잡히면(위임 후보 없음 등). 키워드(조문 단위 1회 집계·제목 ×5·본문 ×1·총칙/부칙 배제)와 문서 한정 시맨틱(`match_chunks_semantic_in_doc` RPC, voyage-4-lite)을 0.45:0.55 결합. **키워드는 청크마다 더하지 말 것**(긴 조문 편향으로 정확한 짧은 조문이 밀림). 임베딩 실패 시 키워드만("키워드 매칭" 라벨). ※ 초기에 넣었던 '제목 구절 +15 가점'은 위임 후보군 도입으로 불필요해져 제거함(가점 땜질 대신 구조로 해결 — 운영자 피드백). **주제 포커스 중이면 직접 관계 엣지가 없는(계열로 딸려온) 노드도 주제명 키워드로 조문 검색** — 예: 주파수 분배 주제에서 전파법 시행령 클릭 시 '주파수 분배' 관련 조문. (직접 엣지 있을 때만 검색하면 계열 간접 노드는 전체 요약만 떠서 '해당 내용 아닌 전체가 나온다'는 피드백.) 원문 보기(모달)·AI 자문 프리필 버튼.
- **전체 인용망 모드의 클릭은 드릴다운**: 법령 노드 클릭 → 그 법령 중심의 실제 인용·계열 관계 서브그래프로 전환(약한 엣지 포함 전부) + **법령 전체 요약은 펼쳐서** 표시, 상태바에 "← 전체 인용망으로" 복귀 링크. 주제 노드 클릭 → 주제 포커스로 전환(셀렉트 동기화). 즉 요약의 접힘/펼침은 모드 따라 반대: 주제 맥락=접힘, 전체망 드릴다운=펼침. (운영자 피드백 2건 반영)
- **질문 로컬 매칭(askLawMap)은 주제 노드에만·양방향으로**: 주제명을 단어로 분해해 그 단어가 질문에 실제로 들어있어야 후보로 인정(nameHits≥1, 점수≥3), 질문 키워드가 설명에 있으면 동점 해소용 가점. '관련·법령·규정·무선·전파·주기' 등 도메인 흔한 단어는 LAWMAP_MATCH_STOP으로 제외. 확실한 매칭이 없으면 **엉뚱한 그래프를 그리지 말고** 현재 화면 유지 + "AI로 생성" 제안. (초기엔 전체 노드 단일 키워드 부분일치라 '무선국'·'허가' 한 단어에 무관한 고시가 매칭돼 주제 불명 그래프가 떴음 — 운영자 피드백 3)

## 대시보드 (GitHub Pages)

- URL: https://radio-policy.gitlab.io/
- **수정 배포 시 index.html 캐시 버스터 `app.js?v=`·`styles.css?v=` 갱신 필수 (현재 `app.js?v=20260729a` / `styles.css?v=20260723b`)** — CSS 고칠 때 styles.css 버스터도 갱신해야 사용자 브라우저가 새로 받음
- 아이콘은 Tabler Icons webfont(ti ti-*) — 존재하는 이름만(없으면 빈칸 렌더).
- 메뉴 (2026-08-02 개편, 17→9 — 배경역사 #56): [모니터링] **통합 모니터링**(패널 상단 탭: 뉴스|정부 보도자료·공지|해외 규제동향) / Daily Briefing / 기술 용어 · [AI 도우미] AI 자문 / 법령 관계도 · [법안 동향] 국회 법안 / 과방위 회의록 / **법령 개정 추적**(탭: 입법예고·개정 현황|조문 DIFF — 기존 lawtrack·diff 패널 무수정 재사용) · [지식베이스] **지식베이스**(탭: 법령·고시|보도자료|실무 안내|ITU-R|추가지식). **설정=상단 톱니 아이콘, 운영 상태=상단 상태등**(🟢/🔴 하트비트 종합, 클릭 시 패널 — refreshOpsLight). 탭 바는 기존 go() 라우팅을 호출하는 상위 컴포넌트(renderGroupTabs)라 패널·로드 함수는 무수정. 모바일 하단 5버튼 유지, 딥링크(pageTobn) 기존 값 유효. 보고서 초안 메뉴는 계속 주석 숨김.
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
국회 입법예고 시작/D-3 | 텔레그램 운영자 + **구독자 큐(topic=assembly)에도 적재**(2026-08-25 문서 정정 — 종전 "운영자 전용·큐 미적재"는 사실과 달랐다). assembly_crawler 입법예고 패스, stage 컬럼 dedupe. 운영자 방침: **주요 법안의 입법예고는 구독자에게 필요하다** — 발송을 끊지 말고 `app_config.assembly_notice_criteria`로 선별을 조인다
과방위 회의록 신규 | 구독자 큐(topic=assembly) 다이제스트 (17:00 체인, 신규 섹션·60일 이내·발언 3건↑에서만 — #120). 운영자 즉시 알림 없음, 즉시 발송 트리거 없음(다음 :25 정시 배달). 백필·오프라인 임포트 경로는 적재 안 함
```

**② 구독자 봇 채널** (2026-08-01 신설 — `정책AI 도우미` @radio_policy_law_ai_bot, `SUBSCRIBER_BOT_TOKEN`)

```
브리핑·긴급·법안   | 구독자가 고른 시각(6~12시)에 3종을 한 번에 발송 — 즉시 발송 없음
                   | ※ 실동작 정정(2026-08-02, 배경역사 #59): 브리핑은 선택 시각에 1회지만
                   |   **긴급·법안은 그 시각 이후 큐에 새로 들어오는 대로 매시 :25에 배달**된다
                   |   (하루 한 번이 아님). 자정~선택 시각에는 발송 없음 → **발송 가능 시간대는
                   |   '선택 시각 ~ 23:25'**. 설정·시작 안내에 이 사실을 명시했다.
                   |   긴급 적재 시 subscriber_notify._trigger_delivery()가 발송 함수를 1회 호출해
                   |   다음 :25를 기다리지 않는다(발송 함수가 수신 시각을 검사하므로 심야엔 무발송).
                   | 요일 선택(매일/평일만), 항목별 on·off. 항목 전부 끄면 수신 없음
                   | ※ 토글 명칭(2026-09-03, #120): 🗞️ 브리핑 / 🔴 주요 뉴스 / **🏛️ 국회·법률 동향**(구 '법안 동향').
                   |   assembly 토글 하나가 **국회 법안 단계변경 + 국회 입법예고 + 부처 입법예고 + 과방위 회의록
                   |   다이제스트**를 받는다. '국회 동향'이 아닌 이유: 부처 입법예고(gov_notice_crawler)가 이미
                   |   같은 토글로 나가고 있었다. 회의록 별도 토글은 두지 않았다(월 1~15회로 드물고 DB 변경·
                   |   구독자 6명 재설정 부담 > 이득). 라벨은 telegram-webhook·admin-daily-report·
                   |   setup_subscriber_bot.py BOT_DESC 세 곳 — 바꿀 땐 셋 다.
조문 조회 /law     | "OO법 N조" 원문 즉답 (LLM 없음, 비용 0)
AI 자문 /ask       | 운영자 승인(chat_id별 1회) + 일일 20회 상한. 건당 100~400원
```

- **운영자 채널과 완전히 별개**다. 운영자는 종전대로 즉시 알림을 받고, 구독자만 정시 수신.
- 긴급·법안은 크롤러가 `subscriber_queue`에 적재만 하고 정시에 묶여 나간다 — 즉시 발송이 없으므로
  '야간 무음' 같은 토글이 필요 없고, 알림 개수도 하루 1회로 고정된다(#44 취지 유지).
- 브리핑 하단에 **기준 시각**을 표기한다("오늘 06:05 기준"). 12시 수신자가 06~12시 뉴스가
  빠진 것을 누락으로 오해하지 않도록(그 건은 다음날 브리핑에 포함).
- **주요 뉴스 '더 보기'** (2026-08-21 신설, 배경역사 #105) — 주요 뉴스 메시지 마지막 조각에
  인라인 버튼 1개(`🟡 12:54~13:53 뉴스 더 보기`). 누르면 그 발송이 커버한 `(from, to]` 구간의
  **`urgency='보통'`** 기사를 사건별로 묶어 보여준다(8묶음/페이지, `▼ 다음 N건`으로 페이지 넘김).
  - **큐를 쓰지 않고 `news_feed`를 직접 읽는다** — 보통 등급을 `subscriber_queue`에 넣으면
    워터마크(`last_urgent_sent_at`) 전진에 섞여 #44 재알림 경로를 다시 만든다. 순수 조회라
    상태를 만들지 않고, 롤백도 버튼 제거뿐이다. **이 원칙을 깨지 말 것.**
  - 구간은 `callback_data`에 epoch 분으로 각인된다(`mn|from|to|offset`, 64B 상한). 버튼은
    **눌린 시각이 아니라 각인된 구간**을 보여주므로 2시간 전 버튼은 그때 구간을 낸다 —
    그래서 버튼 문구·결과 헤더 양쪽에 실제 시각(KST)을 적는다. 연속된 두 버튼은 같은 워터마크
    값을 양쪽에서 내림하므로 이음새에 빈틈·중복이 없다.
  - 사건 묶음은 `_shared/news_group.ts`(app.js `_eventSimilarity` 이식, 2-gram 겹침 계수
    임계 0.45). ⚠️ **임계를 한쪽에서만 바꾸지 말 것** — 대시보드와 텔레그램의 묶음이 어긋난다.
    알려진 한계: 「KT …」 라벨이 「SKT …」 라벨에 흡수되는 오병합(0.692~0.900, 라틴 `skt`가
    bigram `kt`를 포함 + 분모가 짧은 쪽). 대시보드도 같은 한계를 안고 있으며, 통신사 가드는
    별도 후속 작업(양쪽 동시 수정 조건).
  - 태그 구독자의 발송분이 태그 필터로 0건이어도 **워터마크는 전진**한다(긴급 경로와 동형).
    그 구간은 어떤 버튼도 가리키지 않으므로 그 시간대 보통 뉴스는 열람 경로가 없다 — 의도된
    동작이다.

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
python assembly_crawler.py   # 국회 법안(ASSEMBLY_API_KEY) + 입법예고 패스(--dry-run 지원)
python law_diff_gen.py --assembly-only  # 국회 입법예고 조문 분석만 단독 실행
python gov_notice_crawler.py # 정부 고시·입법예고(한국 IP). "[입법예고] N페이지:M행 스캔, 누적 매칭 K건"
python refetch_content.py    # 본문 재수집(한국 IP, trafilatura)
python resend_briefing.py [날짜]              # 브리핑 재발송
python upload_law_pdf.py 파일 "문서명" 고시    # 법령/고시/ITU-R 업로드 (업로드 시 PDF 편집흔적 자동 정리 — clean_pdf_artifacts)
python backfill_embeddings.py                 # 임베딩 백필(document_chunks)
python backfill_report_embeddings.py          # 보고서 샘플 임베딩 백필(report_samples)
python backfill_term_details.py               # 기술용어 상세 백필(tech_terms 설명·개념도·관련용어, 빈 것만. 모델은 app.js와 동일하게 유지)
python build_law_citation_graph.py            # 법령 관계도 인용망 재구축(citation·family 엣지만 — 멱등. 새 법령 업로드 후 실행)
#  ⚠️ 단독 예약이 아니다 — run_gov_crawler.bat 체인의 6번째 단계로 **매일 17시 자동 실행**된다(#106).
#     그래서 관계도의 citation 노드·엣지를 SQL로 손보면 그날 17시에 원복된다. "결과물(DB)이 아니라
#     결과물을 만드는 빌더를 고칠 것." 표기 차이로 갈라진 노드는 별칭표(CITE_ALIAS)가 근본 해결이다.
python lawmap_edge_check.py [--no-notify|--notify-all] [--since-hours 30]   # 관계도 주제 엣지 점검(읽기 전용, #123) — 17시 체인 7번째(마지막) 단계.
#     설명의 자기 조문이 대상 문서 원문(document_chunks.article_no, 모든 판 합집합)에 있는지 대조. ERR(자리표시·조문 없음·조문 미존재)/WARN(일부 미존재·타 법령 조문만·미보유 무표기).
#     기본은 최근 30시간 생성 엣지의 문제만 운영자 봇 무음 알림, 전체 결과는 lawmap_edge_check_sched.log. 정정은 사람이 한다(스크립트는 DB를 쓰지 않음).
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
- ⚠️ **보도자료 기준문과 뉴스 기준문(news_relevance_criteria)을 주기적으로 대조할 것(#95).** 각자 진화하다
  어긋난다 — 실제로 **뉴스는 「부처 인사」를 무조건 통과**시키는데(코드의 `is_ministry_personnel_news()`까지
  이중 보장) **보도자료 기준문에는 인사 항목이 아예 없어** 과기정통부 인사 발표가 조용히 누락됐다.
  「코드가 두 벌이라 한쪽만 낡는다」(#88·#92)의 **데이터 판본**이다.
- ⚠️ **기준문에는 도메인 지식을 명시할 것(#95).** 「독자 AI 파운데이션 모델 4개 정예팀」 성과 보도가
  「순수 R&D 성과 홍보」로 걸러졌는데, **SK텔레콤이 그 정예팀 중 하나**라 실제로는 업무 직결이었다.
  이런 사실은 일반 상식으로 유추되지 않으므로 기준문에 박아야 한다 — 운영자만 아는 것은 물어볼 것.
- **누락분 표적 백필**: 전량 재수집(`press_backfill.py --agency …`)은 2024년부터 순회라 매우 느리다(7분+
  미완). 몇 건만 되살릴 때는 목록에서 제목으로 찾아 `press_ingest._collect_one()`에 직접 넘긴다.
  ★ **기준문을 먼저 고치고 백필할 것** — 순서를 바꾸면 갱신 전 기준으로 다시 걸러진다.
- **관련성 판정은 Batch API로 — 토큰 50%(#96)**: `batch_judge_all()`이 신규 후보를 모아 한 번에
  제출한다(`BATCH_MIN_ITEMS=5` 미만이면 왕복이 더 비싸 개별 판정). 10분 내 미완료·만료·실패분은
  **그 건만 개별 판정으로 폴백** — 배치에 태우는 건 원문이 아니라 「관련 있나」라는 질문이고
  제목·본문·URL은 제출 전에 확보돼 있으므로 **자료 손실 경로가 없다**(만료분은 과금도 안 된다).
  ⚠️ **프롬프트는 `_judge_prompt()` 한 함수만 쓸 것** — 배치/개별이 다른 문구를 쓰면 같은 기사가
  실행 방식에 따라 다르게 판정된다. ⚠️ **뉴스 긴급도 판정에는 배치를 쓰지 말 것** — 배치는 계약상
  24시간까지 걸릴 수 있어(대개 1시간 내) 긴급 알림에 꼬리가 생긴다. 절감 월 6천 원과 바꾸지 않는다.
  ⚠️ **해외규제·국회·회의록·법령DIFF도 배치화하지 말 것** — 판정 물량이 하루 0~35건뿐이라 추가 절감이
  월 2~3천 원인데, 해외규제는 06:05 브리핑까지 35분뿐이고 국회는 당일 알림이 있다.
- **비용 구조(2026-08-13 실측)**: 평상시 **월 ~8만 원**(Haiku 판정이 대부분, 자문 Sonnet은 월 ~1.5만 원).
  ⚠️ **프롬프트 캐싱은 이 시스템에서 무효** — 크롤러 시스템 프롬프트가 1,130토큰이라 Haiku 최소
  캐시 길이(2,048) 미달로 실측상 캐시 저장·읽기 모두 0이었다. 콘솔의 「캐싱 적중률 0%」가 그것이다.
  ⚠️ **야간 수집 중단도 무의미** — 야간 8회는 하루 26건뿐이고 끊어도 05:50이 몰아서 판정한다(월 ~500원).
  ⚠️ **8/2~3 비용 스파이크는 보도자료 백필(6,012청크)이라는 일회성** — 이걸 평상시로 오독하지 말 것.
- **백필/폴백 키워드는 제목 매칭**: press_keywords(2026-08-02 기준 33개, 대시보드에서 편집).
- **본문 추출 경로(기관별 실측)**: 과기정통부=상세가 스텁이라 **첨부에서 추출**(fn_download 3-인자 파싱 →
  `POST /ssm/file/fileDown.do` atchFileNo·fileOrd·fileBtn=A + **Referer 필수**; HWPX=ZIP의 Contents/section*.xml
  태그 제거, PDF=pdftotext) / 방통위·전파관리소=본문+첨부 PDF 병합 / ETRI·KISDI·전파연구원=HTML(trafilatura).
- **OCR 폴백(2026-08-02, 개선⑫ — 배경역사 #60)**: PDF 첨부의 텍스트층이 **500자 미만**이면
  pdftoppm(150dpi, 최대 8쪽) → tesseract `kor+eng` OCR을 시도하고 **1,000자 이상 나올 때만 채택**
  (로그에 `[OCR 추출]` 표기, 본문에는 표기 없음). 도구 부재·실패 시 조용히 기존 동작(fail-soft).
  과기정통부 첨부 선택도 "120자만 넘으면 첫 첨부 채택" → "500자 확보까지 다음 첨부 계속"으로 보강.
  설치본: Tesseract 5.4.0(`C:\Program Files\Tesseract-OCR`) + kor.traineddata 수동 배치, pytesseract.
- **재실행 안전**: 섹션 헤더 dedupe(`## YYMMDD 제목` ilike) — 백필·델타를 몇 번 돌려도 중복 없음.
- **대시보드**: KB '정부 보도자료' 탭(기관 탭 + 수집 키워드 카드 + 원문 보기 버튼), 모니터링 탭 기관 필터.
  업로드 진입점은 제거(자동 수집 전환) — 수동 등재는 '추가 지식 입력'으로.
- **프루닝 방식**: 무관 자료 삭제는 섹션-청크 경계가 어긋나므로 **문서 전문 백업 → 섹션 제외 재조립 →
  재청킹 → 문서 단위 교체 → 재임베딩 → REINDEX** 순서로만 할 것(청크 직접 delete 금지).

## 법령 DIFF 자동화 (law_diff_gen, 2026-08-02 신설 — 배경역사 #54)

- 신규 테이블 **law_diffs**: 개정 1건=1행, diff_kind('pending'현행↔시행예정|'promoted'구현행↔신현행),
  summary(총괄)·impact(SKT 영향)·urgency·articles jsonb[{article_no,change,before,after,impact}].
  **전/후 원문을 jsonb에 보존**(KEEP_VERSIONS 정리와 무관). unique(law_name,new_doc,diff_kind).
- `law_diff_gen.py`(17시 run_gov_crawler.bat 체인): law_pending loaded/promoted 쌍 → 조문 3분류
  diff → Sonnet 1콜(JSON 강제, 변경 조문만 투입) → upsert → 운영자 텔레그램 + heartbeat
  last_law_diff_run. **pending→promoted 전환은 AI 재호출 없이 kind만 갱신**. PDF 수기 등재본 제외,
  변경비율>70%는 전부개정 판정(조문 표 생략).
- 대시보드 DIFF 탭: 자동 감지 리스트(관련도 정렬 — 전파법·전기통신사업법·방발법 계열 우선) →
  상세(총괄+조문 표). 수동 파일 비교는 하단 유지.
- **입법예고 단계도 DIFF 생성**(diff_kind='proposed', 2026-08-02 확장 — 운영자 지시): 과기정통부
  입법행정예고 게시물의 개정안 첨부(msit_extract 재사용)를 현행 조문(law_watch 등재본)과 대비.
  enf_date에는 **의견제출 마감일**이 들어가고 화면 라벨도 '의견마감'. articles의 after는 개정안
  문안 인용(확정본 아님 — 상세에 경고문 표시). **정렬 최상위**(의견제출로 개입 가능한 유일한
  단계라는 운영자 판단 — 시행예정→시행완료 순). 공포되어 pending DIFF가 생기면 같은 법령의
  proposed 행은 자동 삭제(대체).

## 해외 규제기관 모니터링 (foreign_press, 2026-08-02 신설 — 배경역사 #54)

- FCC·Ofcom·BEREC·日총무성·ITU → Haiku 1콜(관련성+한글 제목 번역+3문장 요약, 기준문
  app_config.**foreign_relevance_criteria**) → news_feed(category='해외', 60일 롤링).
- 소스 경로는 실측 확정본만 사용: FCC=**EDOCS API RSS**(fcc.gov 내 /rss 경로들은 HTML 반환하는
  가짜), Ofcom=**전 경로 Cloudflare 차단 → 구글 뉴스 site: RSS 우회**, 日총무성=Shift_JIS HTML,
  BEREC·ITU=공식 RSS. **API 키 없으면 fail-closed**(외국어라 키워드 폴백 불성립 — heartbeat에 기록).
- 스케줄: 매일 05:30 radio_TEMP_foreign(임시) — 한국 IP 불요라 **계정 복구 후 GitHub Actions 이관 대상**.
- 브리핑 [해외 동향] 섹션: 파이썬 결정적 조립, briefing 뒤쪽 배치.

## 과방위 회의록 수집 (assembly_minutes, 2026-08-02 신설 — 배경역사 #54)

- 열린국회 API **ncwgseseafwbuheph**(row=안건 단위 → CONFER_NUM으로 회의 그룹핑) →
  **원문은 record.assembly.go.kr 뷰어 xml.do가 정본**(PDF는 pdftotext에서 글리프 깨짐 — 폴백만).
- 발언 선별: press_keywords 1차 + Haiku 2차(press_relevance_criteria) → 채택+전후 1블록 →
  `과방위_회의록_{YYYY}.md`(doc_category='회의록', 섹션 '## YYMMDD 제N차 (안건)') —
  press_ingest.**register_kb_section**(register_press의 일반화) 사용. 22대 개원(2024)부터 백필 → **2026-09-03 세션 파이프라인(minutes_offline.py)으로 20대 개원(2016)까지 소급 완료**(상임위 257회의·발언 1,975건, #120).
- 대시보드: 국회 법안 탭 하단 목록 + openPressDetail 재사용. KB 목록 블랙리스트에 '회의록' 포함.
- 17시 run_gov_crawler.bat 체인에서 매일 신규분 수집. heartbeat last_minutes_run.
- **발언자별 입장 추적(2026-08-03, #67)**: 판정 통과 본 발언(전후 문맥 제외)을 `assembly_speeches`
  테이블에 발언자별 적재 — speaker(정규화명)·position·meeting_date·agenda·summary(Haiku 요지)·
  source_url. unique(confer_num, speaker, chunk_seq)로 재실행 안전. document_chunks 등재와 독립
  dedupe(한쪽만 있으면 없는 쪽만 채움 → 소급 적재 가능). 대시보드 회의록 패널 "발언자별 보기" 토글.
  **요지 프롬프트 가드: 발언 내용 요약만, 성향·정파성 단정 평가어 금지**(친기업/강경/편향 등) —
  촉구·질의·지적 같은 발언 행위 동사만 허용. 22대 전 회의 백필 완료.
- **국정감사 회의록 (2026-08-14 추가, 배경역사 #97 — 22대 전용)**: 위 Open API는 **CLASS_NAME='상임위원회'만**
  돌려줘 국감이 통째로 빠져 있었다(2019년 과방위 41건 전수 조회에도 국감 0건, `CLASS_NAME=국정감사` 질의도 0건).
  10월에 잡히는 건 "국정감사 증인 출석요구의 건"을 처리한 짧은 전체회의일 뿐 감사 본체가 아니다.
  국감은 **국회회의록시스템 검색 API로만** 잡힌다 — POST `record.assembly.go.kr/assembly/mnts/search/search.do`:
  - **`collection='record5'` + `CLASS_CD='5'` 필수.** `collection='record'`(상임위)로 보내면 200 + 빈 `{}`가 와서
    '결과 없음'과 구분되지 않는다(파라미터 오류 실측 시 첫 함정).
  - **`CMIT_CD`는 검색폼 `#com5List`에서 자동 탐지** — 22대 과방위=**22-5-AG**, 20대는 20-5-AB-0. 코드가
    대(代)마다 재배정되므로 하드코딩 금지(상수는 폴백용).
  - `S_TH`/`E_TH`='24' — **검색폼 대수코드(24=제22대)는 Open API `DAE_NUM`='22'와 별개 체계**. 혼동 주의.
  - **`startDate`/`endDate`에 연도 범위를 반드시 넣을 것**('YYYY-MM-DD'). 안 주면 22대 전체(1,500+ 히트)를
    최신순으로만 훑어 재작년 국감이 페이지 상한 밖으로 밀려 **조용히 0건**이 된다(실측 — 2024년 전량 누락).
  - 열거 질의어는 `'국정감사'` 전수 페이징(`startCount`=1-base, 페이지당 10건 고정). '산회'로 히트를 줄이려 했으나
    2024년 10건 중 2건·2025년 9건 중 0건만 잡혔다 — 산회 선포가 발언 블록으로 안 남는 회의가 많다.
  - **뷰어 id는 `MNTS_ID`** (Open API CONFER_NUM과 다른 체계 — 2019 국감 41178 vs 상임위 44269).
    값 충돌을 막으려 `assembly_speeches.confer_num`은 **`audit-{MNTS_ID}`**로 네임스페이스.
  - 섹션 제목 `국정감사 (첫 기관 외 N개 기관)`, **dedupe 접두는 '국정감사' 고정**(기관 목록이 바뀌어도 안 흔들림).
  - 국감 회의록은 1,700~2,100블록이라 판정 상한 80·수록 상한 50(상임위는 40·30).
  - CLI: `--audit-only`(소급 백필) / `--no-audit`. 2016년(20대 개원) 이전 연도는 자동 스킵.
- **뷰어는 간헐적으로 페이지를 덜 보낸다 — `fetch_speech_blocks()`는 best-of-N (2026-08-14, #99)**:
  같은 id 51996이 어떤 때는 3,449블록, 어떤 때는 432/363블록으로 왔다. 한 번만 받으면 그 시점에 걸린 회의가
  **잘린 채 등재**되고 `section_exists()`가 헤더만 보고 dup 처리해 **영구히 갱신되지 않는다**(실제로 이 모양의
  사고가 났다). 최소 2회 받아 큰 쪽을 쓰고, 직전 최대치의 90% 이상이 다시 나오면 신뢰하고 멈춘다
  (`VIEWER_RETRIES`·`VIEWER_SHORT_RATIO`). ⚠️ **이 재시도를 빼지 말 것.**
- **빈 껍데기 섹션은 dup으로 보지 않는다 (#99)**: 판정이 전부 탈락하면 `(키워드 관련 발언 없음 …)`만 있는
  섹션이 등재되는데, 종전엔 그것도 dup이라 **발언은 12건 있는데 섹션은 영영 껍데기**로 남았다.
  `shell_section_range()`가 껍데기를 찾아 다음 실행에서 자동 복구한다. ⚠️ 단 **새로 만든 본문도 껍데기면
  그대로 둔다** — 안 그러면 매 실행마다 delete+insert 로 chunk_index 를 갈아엎고 재임베딩을 유발한다.
- **답변 판정에는 길이 문턱을 적용하지 않는다 (#99)**: `_qa_lines()`가 `MIN_SUBSTANTIVE_LEN=60`을 답변에도
  적용해 "예, 협의하겠습니다" 급 **짧은 확답이 전부 절차성으로 버려졌다**(↳ 부착률 30.4%, 같은 의원 ▶ 연속 31%).
  길이 조건만 빼고 절차성 정규식은 유지 → **77.4% / 9.5%**. **짧은 확답이 그날의 실질 성과인 경우가 많다**
  ("무선국 면허세는 행안부와 협의해 낮추겠다").
- **국회 발언 원문 검색 (2026-08-14, 배경역사 #98 — 축적 데이터와 무관한 실시간 경로)**:
  DB(`assembly_speeches`)는 22대·판정 통과분·**요지만** 담아 "2019년 김성수 의원 무선국" 류 질의에
  답하지 못한다. 그래서 국회회의록시스템을 **실시간 검색**하는 경로를 따로 뒀다. AI 요약을 하지 않아
  **비용 0**(자연어 파싱만 규칙 실패 시 Haiku 1콜).
  - **로직은 `supabase/functions/_shared/assembly_search.ts` 한 곳에만** 둔다. 텔레그램(`assem`)과
    대시보드(`assembly-search` 함수)가 이 파일을 공유 — 두 벌이 되면 같은 질문에 다른 답이 난다(#88·#92).
  - **범위 = 과방위 상임위 + 국정감사뿐**(운영자 지시). 본회의·타 상임위는 넣지 않는다(문맥 밖 + 동명이인 오답).
    **20대 전반기 명칭 미래창조과학방송통신위원회를 반드시 포함**(빼면 2016~2018년 통째 누락).
  - 검색 파라미터 함정은 위 국감 항목과 동일(`collection=record2/record5`, `CMIT_CD` 대별 재배정,
    `S_TH/E_TH`는 폼 대수코드). `CMIT_CD`는 **콤마 다중 지정 가능**이라 20~22대·상임위·국감을 한 번에 조회한다.
    페이징 `startCount`(1-base, 10건/페이지), 쿠키 불필요.
  - **텔레그램**: 슬래시 없이 `assem 2019년 국정감사에서 김성수 의원이 무선국 관련 발언 찾아줘`.
    평문 catch-all(/ask)보다 **먼저** 분기해야 자문 경로로 새지 않는다. 승인·한도 없음(비용이 없으므로).
  - **대시보드**: 과방위 회의록 → **원문 검색(20대~)** 탭. 브라우저에서 국회 사이트를 직접 부르면
    **CORS로 막히므로** `assembly-search` Edge Function 경유가 필수다.
  - 형태소 분석이 없는 **원문 문자열 검색**이다 — 회의록에 나온 낱말 그대로여야 잡힌다. 파서가 검색어를
    2개까지만 넘기는 이유(AND 검색이라 낱말이 늘수록 0건).
- **자사(SK텔레콤) 언급은 주제 불문 무조건 수록 (2026-08-14, #97)**: 키워드·Haiku 판정을 건너뛰고 확정하며
  **수록 상한에서도 우선권**을 준다(`cap_indices`) — 상한을 앞에서 자르면 회의 후반의 자사 발언이 통째로
  날아간다(실측: 2024-10-08 확정 93개 > 상한 50). 인식어 SK텔레콤/SK 텔레콤/에스케이텔레콤/SKT.
  상임위·국감 두 경로에 공통 적용. `topic`은 키워드가 없으면 'SK텔레콤 언급'.
  → **2026-09-03(#120)부터 칩은 상시 부착**: 원문이 인식어에 걸리면 키워드 주제가 있어도 `SK텔레콤 언급`을
  콤마로 덧붙인다(`build_speech_rows`). 요약 줄에도 `with_skt_suffix()`가 ` (SK텔레콤 언급)`을 1회 붙인다.
  **AI 판정이 아니라 `skt_mentioned(blocks, picked)` 규칙**(원문 문자열 매칭)이다 — 요약문에 SK가 언급됐는지
  AI에게 묻지 말 것(요약이 언급을 빠뜨리면 표시도 사라진다).
- **텔레그램 다이제스트 (2026-09-03, #120)**: 17시 체인에서 **신규 등록된 회의 1건당** `subscriber_notify.
  format_minutes_digest()` → `queue_for_subscribers(sb,'assembly',html)`. 적재 조건 **넷 모두** 충족 시에만:
  ①`register_kb_section`이 True(신규 섹션 — dup·껍데기 복구는 제외) ②`--no-notify` 아님 ③껍데기 섹션 아님
  ④발언 요지 **3건↑**(`DIGEST_MIN_SPEECHES`) ⑤회의일 **60일 이내**(`DIGEST_MAX_AGE_DAYS`, 날짜 파싱 실패 =
  fail-closed로 적재 안 함). 스킵 사유는 전부 print(조용한 실패 금지). 즉시 발송 트리거 없음 — 다음 :25에
  send-subscriber-briefing이 각 구독자 시각에 묶어 보낸다. 형식: 헤더 `🏛️ <b>과방위 회의록 · M/D 제N차 (안건)</b>`
  + 한 줄 요약 + 주제별 발언 요지(≤10줄·140자/줄) + 푸터 `… 외 N건 · 원문 · 대시보드`. **예산 2,500자** —
  `queue_for_subscribers`가 3,500자에서 맹목 절단하므로 `<a>` 태그 중간이 잘려 텔레그램 400이 나지 않게
  여유를 둔다. 불릿은 `· `만, **`N. ` 번호줄 금지** — 발송 함수 `mergeQueueBlocks`가 번호줄을 재조립한다.
- **요약 프롬프트·두 층 요약 (2026-09-03, #120)**: 종전 프롬프트 "통신사(SK텔레콤) 관점에서 어떤 논의가
  있었는지"는 **"SK텔레콤이 직접 언급되지 않았습니다" / "정책 논의는 없었다" 같은 무내용 메타응답**을
  요약으로 저장했다(실측 2026-07-06·07-30·08-19 섹션). 현행: "이 회의에서 통신·전파·AI 관련해 무엇이
  논의됐는지 1~2문장(130자 이내)… 특정 기업의 관점을 취하지 말고…". ⚠️ **요약 프롬프트에 관점 지시를
  넣지 말 것.** 요약은 두 층 — ①**한 줄 요약**(130자, 250자 절단): 목록·텔레그램용, `요약:` 줄은 본문
  **첫 900자 안**에 있어야 한다(app.js가 거기서 파싱) ②**회의 개요**(`summarize_overview()`, 주제별 문단
  2~5개·300~600자·각 줄 `[주제] 문단`): 대시보드 상세용, 섹션 본문에 `개요:` 블록으로 **`- 안건:` 뒤·
  `질의·응답:` 앞**에 둔다. `build_section_body(..., overview='')` — 빈 값이면 옛 형식과 바이트 동일.
  `format_overview()`가 문단마다 `is_valid_summary`를 통과시키고 하나도 없으면 블록을 **생략**한다(폴백
  저장 없음, #113 규칙). 발언 요지는 120자 유지.
- **모델 (2026-09-03, #120)**: 일일 경로의 판정·회의 요약·개요·발언 요지 전부 **Sonnet 5**
  (`MINUTES_MODEL='claude-sonnet-5'`, `MINUTES_THINKING={'type':'disabled'}`; `make_ai_judge(sb, keywords,
  model=, thinking=)` 신설 kwargs — press_ingest 기본은 Haiku 그대로라 보도자료 판정 무변경). ⚠️ **비스트리밍
  호출은 thinking disabled 필수** — Sonnet 5는 적응형 추론이 기본 ON이라 thinking 토큰이 과금되고
  `content[0]`이 텍스트가 아니다. 비용 ≈ $0.26/회의, 월 7회 ≈ $1.8. Haiku를 버린 이유: 영문 거절문을
  요지로 저장(#99) + 무내용 요약. CLI: `--no-notify`(큐 미적재), **`--year`로 작년 이전 연도를 돌리려면
  `--allow-api` 필수**(없으면 안내문과 함께 거부) — 과거 연도는 아래 오프라인 파이프라인으로.
- **20·21대 소급 + 오프라인(세션) 파이프라인 (2026-09-03, #120 — Anthropic API 0회)**:
  - 운영자 규칙: **일회성 AI 작업(재요약·소급 백필)은 Claude 세션(서브에이전트, Sonnet 5)이 하고 API를
    쓰지 않는다.** API는 무인 반복(17시 체인)에만. Sonnet 5 API로 640회의를 돌리면 ≈ $110.
  - `COMMITTEE_DAE_TABLE`(assembly_minutes.py): (2016~2020, '20', [미래창조과학방송통신위원회,
    과학기술정보방송통신위원회]) / (2020~2024, '21', [과기정통위]) / (2024~, '22', [과기정통위]).
    `committee_queries_for(year)` → `fetch_meetings`가 (dae, comm) 쌍 전부를 질의해 CONFER_NUM으로 합치고
    `dae_num`·`comm_name`을 기록. 실측(페이지1/300행): 2016 미방위 17 / 2017 미방위 11 + 과방위 16 /
    2019 10 / 2021 18 / 2023 19. **20대 전반기(~2017-07-26) 명칭이 다르다 — 빼면 2016~2017 통째 누락.**
    23대 개원 시 한 줄 추가.
  - `minutes_offline.py` 명령(파이썬 안에 AI 호출 0):
    `--export-candidates --year Y --out DIR` → 회의 목록 + 뷰어 블록(best-of-N) + 키워드 후보를
    `DIR/{year}/{confer_num}.blocks.json`·`.cand.json` + `_index.json`·`_criteria.txt`·`_rules.md`로.
    세션이 `{confer_num}.judged.json` = `{schema:'minutes-judged/1', confer_num, meeting_summary,
    meeting_overview:[{topic,text}], kept:[{idx,summary}], rejected:[…], judged_by}` 작성.
    `--import-judged --in DIR [--year] [--limit] [--dry-run]` → run()과 같은 dedupe(section_exists → 껍데기 →
    register_kb_section) + `build_speech_rows(presummarized=…)`(검증 실패 요지는 저장 안 함).
    `--export-resummary --out DIR`(DB만 읽음) → 기존 섹션을 `DIR/resum/{year}/{ymd6}_{confer_num}.json`
    (발췌 ≤8,000자·skt_flag·viewer_id)으로. 세션이 `…judged.json` = `{meeting_summary, meeting_overview}`.
    `--import-resummary --in DIR [--no-refetch] [--force] [--limit] [--dry-run]` → 요약 줄 교체 + 개요 블록
    삽입 후 섹션을 **통째로 재등록**(drop_section + register_kb_section + renumber_doc — 개요 삽입으로
    첫 청크가 700자를 넘어 부분 갱신이 불가) → 뷰어 블록을 다시 받아 **정렬 검사 통과 시에만**
    `assembly_speeches.topic`에 SK 칩 소급(모든 `chunk_seq < len(blocks)` + `normalize_speaker(blocks[cs].name)
    == speaker`; 불일치는 스킵+로그). `_done.json`으로 재개 가능. subscriber_notify 미임포트·큐 적재 없음.
    끝나면 `backfill_embeddings.py`로 재등록 청크(~700) 재임베딩.
  - ⚠️ **17:00~17:30에는 오프라인 임포트 금지**(gov 크롤러 체인과 겹쳐 섹션 중복 사고). 내보내기(뷰어 fetch)
    병렬은 **3~4 프로세스 이하**(#99 잘린 응답). **임포트는 단일 프로세스·순차**(chunk_index 재번호).
  - 세션 배치: 재요약 ~238회의 → 서브에이전트 ~25개(8~10건씩, 동시) / 20·21대 ~300~330회의 → ~40개를
    20개씩 2파(wave).
- **대시보드 회의록 상세 (2026-09-03, #120, `app.js?v=20260904a`)**: `openAssemblyMinute` → `openMinuteDetail(mt)`.
  일시·안건 → 요약 배지 → 회의 개요 문단(`[주제]` 굵게) → **주요 발언 N건**(주제별 묶음, `assembly_speeches`를
  섹션의 `(원문: URL)` == `source_url`로 조인) → SK텔레콤 언급 칩 → 푸터 `국회 원문 보기` + `발췌 원문 보기`
  토글(원문 질의·응답은 `pressTextToHtml` 유지). 발언 행 0건이면 발췌 원문을 바로 보인다.
  `fetchPressSection()`을 `openPressDetail`에서 분리해 공용(보도자료 출력 무변경). `loadAssemblyMinutes`가
  `src_url`도 보관.
- **뷰어 본문 교차 검증 — 뷰어 id가 다른 위원회 회의록을 돌려준다 (2026-09-03, #120-보론)**: 20·21대 소급
  export 281회의 중 **8회의**가 HTML 제목은 맞는데 발언 블록이 엉뚱한 상임위였다(2017/41948 미방위 법안소위 →
  2025 국방위 1,059블록, 2017/42378 과방위 → 기재위·국세청, 2018/43150 기재위 예산소위, 2019/43754·2017/42374
  국세청·관세청·조달청, 2021/45634·2022/46840·2023/47682 국토교통부·행정안전부). **같은 id의 Open API
  `PDF_LINK_URL`은 전부 정상**이라 PDF가 대조 근거다. 22대에도 흔적(2026 문서 260129/56204와 260311/56351
  섹션 발췌가 같은 발언으로 시작 — 둘 중 하나가 오응답, **별도 재수집 미조치**).
  - `assembly_minutes.py`: `fetch_pdf_text()`(1회 다운로드를 검증·폴백이 공유) / `looks_foreign_committee(blocks)`
    (pos에 소관 기관명 — 미래창조과학부·과기정통부·방통위·방미통위·원안위·우주항공청·KBS·EBS — 이 하나도 없고
    타 부처명(국방부·국세청·관세청·조달청·기획재정부·법무부·국토교통부·행정안전부 …)이 있으면 그 기관명 반환.
    ⚠️ **'위원장'·'전문위원' 같은 일반 직위를 소관 표지에 넣으면 절대 안 걸린다**(실측 — 41948·42378이 통과됨)) /
    `verify_blocks_against_pdf(blocks, pdf_url)`(가장 긴 블록 6개의 앞 30자를 공백 제거 후 PDF 텍스트에서 찾아
    **60%↑ 적중이면 ok**; PDF 2,000자 미만·다운로드 실패는 판정불가 None → 뷰어 그대로 사용+로그).
    일일 `run()`은 뷰어 블록 확보 직후 **상임위 회의(pdf_url 있음)에만** 두 검사를 걸어 불일치면
    `[뷰어 불일치→PDF 폴백]` 로그 후 `pdf_fallback_blocks`로 교체(`src='PDF(뷰어 불일치)'`), PDF도 없으면 fail
    스킵 — **오응답 본문은 절대 등재하지 않는다.** 국감 경로는 PDF URL이 같은 뷰어 id로 만들어져 독립 근거가
    아니라 검증하지 않는다. 실측 분리가 뚜렷: 정상 회의 표본 5~6/6 적중, 오응답 회의 0/6.
  - `minutes_offline.py`: `--export-candidates`가 같은 검사(불일치 → PDF 블록, blocks.json
    `meeting.verify={foreign,pdf_ok,detail}`), 새 모드 **`--verify-exported --in DIR [--year Y] [--fix]`**(기존
    export를 PDF와 재대조해 표 출력 + `{year}/_verify.json`; `--fix`면 PDF 블록으로 재생성하고 해당
    `.judged.json` 삭제 → 재판정 필요), `--import-judged`는 verify 불일치인데 src가 PDF가 아닌 회의를 **거부**.

## 국회 입법예고 추적 (assembly_crawler 입법예고 패스 + law_diff_gen 국회 분석, 2026-08-02 신설 — 배경역사 #56)

- **PDF 폴백 발언자 라벨은 `_split_pdf_label()`로 가른다 (2026-09-03)**: PDF의 `◯` 줄은 "직위 이름 첫문장"이 한 줄이라 줄 전체를 이름으로 두면 발언자가 '미상'이 되고 첫 문장이 유실된다(교정 18회의 실측). 직위 토큰(장관·차관·위원장·소위원장·…부단장·과장 등)으로 끝나는 첫 토큰 + 이름 / 이름 + 위원·의원·진술인 순서를 모두 처리한다. ⚠️ PDF 폴백으로 만든 발언 행에 '미상'이 많으면 이 함수부터 의심할 것.
- **(SK텔레콤 언급) 표시의 근거는 발췌 원문뿐 (2026-09-03)**: 요약 줄·개요 블록까지 보면 옛 요약문 "SK텔레콤이 직접 언급되지 않았습니다"가 표시를 켠다(실측 29건, 운영자 지적으로 발견). `minutes_offline._skt_in_body()`·`assembly_minutes.skt_mentioned(blocks, picked)`처럼 **원문 블록만** 본다. 대시보드 상세는 발췌 원문 안의 SK텔레콤·SKT를 **굵게** 표시하고 "SK텔레콤 N곳" 버튼으로 건너뛰게 한다(별도 패널 아님 — 운영자 지시: 대화 흐름 속에서 찾아 읽을 수 있어야 한다). 텔레그램 다이제스트는 자사 언급 행이 든 주제 그룹을 맨 앞에 둔다.
- **수집**: 열린국회 API `nknalejkafmvgzmpt`(진행중 입법예고) 1콜(pSize=1000) — 결과가 곧
  "의견등록 가능" 목록(마감일 NOTI_ED_DT 당일 포함). AGE 파라미터는 **무시됨**(넣지 말 것).
  국회 법안 크롤러(10:00) 본 루프 뒤에 패스로 부착. `--dry-run` 지원.
- **관련성 = 의미 판정 (2026-08-02 안정화, #64)**: 기존 추적분·**과방위 소관은 자동 관련**, 나머지는
  Haiku **배치(40건)** 판정 — ①제목+위원회+**제안이유(BPMBILLSUMMARY 400자)** ②tool_choice 강제+
  "독립 판정·기준문 문자적용·애매하면 관련" 프롬프트로 **결정성 확보**(temperature류 금지) ③'무관'
  중 통신 인접 상임위/경계 어휘 건만 **1회 재투표**(관련이면 채택). 판정 흔들림(같은 법안 dry-run
  관련→실전 무관) 해소 — 재현성 2회 일치 실측. 기준문 app_config `assembly_notice_criteria`(경계 사례
  6종 포함, 운영자 수정 가능) + 실패 시 키워드 폴백(fail-open). **경계 6종째(2026-08-20, #102): 타 분야 법안에 정보통신망·AI가 '범행 수단'으로만 등장하면 무관** — 독립유공자 온라인 조롱 처벌 법안(제안이유에 정보통신망·생성형 AI 언급)이 관련 판정돼 구독자 큐까지 탄 사고. 통신·ICT 법령 개정 또는 사업자·플랫폼 의무 신설일 때만 관련. 기각 캐시 `assembly_notice_rejected`
  (진행 목록에서 빠지면 자동 정리 — 판정 로직/기준문 변경 시 캐시 비우면 전건 재심사).
- **검색 키워드(#64)**: 법령명 위주 13개 + 통신 인접 6개(개인정보·인공지능·플랫폼·데이터·클라우드·
  메타버스). '정보통신'(203건)·'디지털'(헬스케어 등 무관 다수)·'이용자보호'(0건)는 제외.
- **DB**: assembly_bills에 notice_end_dt('YYYY-MM-DD')·notice_url·notice_alert_stage(0/1/2).
  알림은 운영자 전용(시작 1회→stage1, D-3 1회→stage2 — **발송 성공 시에만 stage 갱신**해 실패 재시도).
  heartbeat `last_assembly_run`.
- **예고 단계 조문 분석(③′)**: law_diff_gen `--assembly-only`/기본 체인 — 의견등록 가능+관련 법안의
  의안 원문 PDF(pal 상세→FileGate)에서 **신구조문대비표** 추출 → Sonnet 1콜 → law_diffs에
  diff_kind='proposed'+**origin='assembly'**·new_doc=의안번호·enf_date=의견마감일로 등재.
  가결(공포 후 pending DIFF가 대체)·폐기·철회 시 자동 삭제. PDF 실패 시 BPMBILLSUMMARY 텍스트로
  총괄·영향만(articles=[]) — 무리한 우회 금지.
- **함정 (하지 말 것)**: ①pal HTML 스크래핑으로 전환 금지 — API와 레코드 완전 일치 실측(379=379),
  HTML은 GET 페이징을 조용히 무시(POST+_csrf 필요)라 유지보수 함정. ②FileGate는 302가 아니라
  "moved" HTML을 반환 — href 추적 1~2회 필요(sender 번호 하드코딩 금지). ③신구조문대비표 표제의
  가운뎃점은 **U+318D(ㆍ)** — `[·ㆍ.]` 클래스로 매칭할 것. ④위원회 서버 필터로 좁히지 말 것
  (정보통신망법이 정무위 배정 사례 — 전량 수신 후 로컬 판정).

## 과기정통부 소관 법령·고시·법안 전수 확충 (2026-09-04 신설 — 배경역사 #121)

운영자 질문("과기정통부 소관 법안 중 SK텔레콤 관련 법안이 모두 들어가 있나?" → "법령·시행령·시행규칙·고시 전부 포함")에서 시작한 딥리서치·세션 작업. 세 갈래를 한 세트로 처리했다.

- **국회 법안 전수 스윕**: 기존 `fetch_bills()`는 키워드별 pIndex=1 한 페이지(100건)만 읽어 100건 넘는 키워드(정보통신망·개인정보·인공지능·데이터)의 101건째부터 조용히 누락됐고(오류 없음·heartbeat 정상), 법안명 키워드 검색이라 이름에 키워드가 없는 과방위 소관 법안(정보통신공사업법·위치정보법·소프트웨어 진흥법·방통위 설치법·지능정보화 기본법·디지털포용법 개정안 등)은 구조적으로 못 봤다. 실측: 열린국회 API를 `COMMITTEE=과학기술정보방송통신위원회`로 전수 조회하면 22대 802건인데 DB엔 311건뿐(전체 466건 중). `_fetch_bill_rows()`가 마지막 페이지까지 순회하도록 고치고, `fetch_committee_bills()`+`is_committee_bill_relevant()`+`sweep_committee_bills()`를 신설해 과방위 소관 법안을 전수 스윕한다 — 법령군 이름이 일치하면 판정 없이 관련 처리하고, 「방송법…」류는 국회 입법예고 패스의 Haiku 배치 판정을 재사용하며 기각 캐시는 `app_config.assembly_committee_rejected`(입법예고 기각 캐시와 키 분리, `COMMITTEE_REJECT_KEY`)에 쌓는다. 원자력·우주·출연연·KBS 거버넌스 등 무관 법안은 스킵. 결과: 통신 관련 법령군 185건 + 방송법 60건 중 유료방송·통신 관련 13건(세션 판정) = 198건 등재(`matched_keywords=['과방위소관']`, 방송법은 `'방송법-유료방송'` 추가). 89건은 BPMBILLSUMMARY에 요약이 없어 summary NULL이며 일일 `summarize_assembly_bills.py`(Haiku)가 채운다.
- **법령·고시 KB 확충**: 법제처 DRF `lawSearch.do?target=law&org=1721000`(과기정통부) 현행 205건(법률 72·대통령령 80·부령 50) 중 통신 관련 61건, KB엔 31건뿐 → 빠진 30건 중 직제·비영리법인·비상대비·청장지휘 4건 제외 26건 등재(전기통신기본법·정보통신공사업법·정보통신융합특별법·정보보호산업법·전자서명법·전자문서법·소프트웨어진흥법·디지털포용법·인터넷주소자원법 각 법률+시행령+시행규칙, 무선설비규칙). 고시는 `target=admrul&org=1721000` 1,021건 중 소관 5기관(과기정통부·방미통위·방통위·국립전파연구원·중앙전파관리소) 현행 315건 → 통신 관련 150건 → KB 80건 → 빠진 70건 중 우편·SW품질·시설물·비영리법인 등 24건 제외 46건 등재(4건은 기존 문서와 같은 고시라 OKF 생략). ⚠️ **방미통위(방송미디어통신위원회)는 별도 org 코드가 없다** — 1721000 안에 과기정통부와 함께 나오므로 소관부처명 문자열로 가른다. KB 적재는 `add_laws_batch.py`(TARGETS C절 71건 → 성공 66·스킵 92·실패 1) → `backfill_embeddings.py`(3,980청크). OKF는 세션 서브에이전트가 작성(법령 25·고시 42 신규) → manifest 433 entries → `import_regulatory_kb.py --only <경로목록>`으로 적재.
- **법안 요약(Bill) — 당일 철회(#122)**: #121에서 `regulatory-kb/bills/<year>/<의안번호>.md`·`concept_type='Bill'` 109건을 자문 근거 층에 넣었으나, 운영자 결정(자문 근거는 확정 법령만, 법안은 동향)으로 같은 날 DB(109문서·545청크)·번들·코드(`import_regulatory_kb`/`sync_kb_to_bundle`의 bills 경로, `rag.ts`·`app.js`의 `isBillRow` 라벨, 시스템 프롬프트 ⑥)를 모두 걷어냈다. 국회 법안 198건 편입·크롤러 페이징·과방위 스윕은 유지. 아래 「국회 법안 진행단계·자문 근거 원칙」 참조.
- **관계도 재구축**: `sync_law_delegations.py`(법제처 3단비교, 33법률 1,968행) → `sync_notice_delegations.py`(고시 제1조 목적→상위법 역추출, 306행) → `build_law_citation_graph.py`(엣지 3,370 재구축) → 결과 노드 1,286·엣지 3,686. 새로 들어간 법령(정보통신공사업법 34엣지, 정보보호산업법 45엣지 등)과 고시가 노드로 편입됐다.
- **함정**: DRF admrul 본문은 `lawService.do?target=admrul&LID=<행정규칙ID>`로 조회한다 — ID·MST 파라미터로 부르면 "일치하는 행정규칙이 없습니다"만 돌아온다. `import_regulatory_kb.py --only`에 넘길 경로 목록 파일을 Windows에서 만들면 각 줄에 CR(`\r`)이 붙어 부분 문자열 비교가 실패한다(`tr -d '\r'` 필수) — 이 때문에 67건 중 1건만 선택된 실측 사고가 있었다.

## 국회 법안 진행단계·자문 근거 원칙 (2026-09-04 신설 — 배경역사 #122)

- **원칙(운영자 결정)**: AI 자문 근거는 **확정 법령**(법률·시행령·시행규칙·고시, 공포된 시행예정본 포함)만. 국회 법안은 단계와 무관하게 **'법안 동향'**(국회 법안 탭·상태변경 알림·브리핑·자문의 [국회 동향 — 참고용 배경] 각주)으로만 다룬다. 의견 개진 시점 판단은 동향에서, "현재는 이렇고 향후 이렇게 바뀐다"는 시행예정본(`law_pending`·조문 DIFF·"[시행예정 개정본]" 블록)에서 한다.
- **실제 순서**: 발의·접수 → 소관위 회부 → 국회 입법예고(회부 직후, 거의 모든 법안·5~10일) → 소관위 상정(대체토론) → 소위 심사 → 위원회 의결(대안·가결) → 법사위 회부·심사 → 본회의 → 공포. 입법예고는 초입이지 성숙 단계가 아니고, 상정도 과방위 802건 중 686건(85%)이라 걸러내지 못한다. 통과 확률이 갈리는 지점은 위원회 의결(이후 90%+).
- **단계 파생 `bill_stage.py`**: API PROC_RESULT(본회의 결과)가 있으면 그대로(종결). 비면 CMT_PROC_RESULT_CD가 대안반영폐기·부결·철회면 그 값, 가결·수정가결이면 '위원회 의결'; 아니면 LAW_PRESENT_DT→'법사위 심사중', LAW_SUBMIT_DT→'법사위 회부', CMT_PRESENT_DT→'소관위 심사중', COMMITTEE_DT→'소관위 회부', 그 외 '접수'. API에 소위 필드는 없어 상정일이 심사 착수의 대리 지표. `ALIVE_LABELS` 화이트리스트 밖은 종결로 본다(미지 코드 안전). 원본 일자는 assembly_bills 단계 컬럼에 저장(DB 표 참조).
- **알림**: `NOTABLE_STATUS`에 '위원회 의결'·'법사위 회부' 추가('소관위 회부'는 잡음이라 제외). `notify_new`/`notify_status_change`/dry-run 분기 모두 `derive_stage()`를 읽는다(raw PROC_RESULT를 읽으면 새 라벨 알림이 영영 안 나감).
- **대시보드**: `_billIsActive/_billIsPassed/_billIsDiscarded`로 계류·통과·폐기를 판정(문자열 '접수' 비교 금지). '위원회 의결'은 청록, '소관위 회부'는 연회색 라벨.
- **2026-09-04 백필 결과**: 상태변경 442건(접수→소관위 심사중 304, →소관위 회부 120, →대안반영폐기 18) 알림 0건. 분포: 소관위 심사중 304·대안반영폐기 199·소관위 회부 120·접수 31·가결 8·철회 4.
- **방송법 판정 캐시**: 과방위 스윕의 방송법 계열은 세션이 판정한 기각 47건을 `app_config.assembly_committee_rejected`에 심어 두었다(Haiku가 47건 전부를 관련으로 되돌려 신규 알림 47건이 날 뻔함). 캐시를 비우면 같은 일이 재발한다.

## 이슈맵 (2026-08-26 신설 — 배경역사 #110, 상세는 docs/이슈맵_구현스펙_260826.md)

중요 이슈의 경과·관련 법령·이해관계자·SKT 영향을 한 화면에 모으는 사이드바 메뉴. **이슈가 뉴스 보존의 기준** — 이슈에 연결된 기사는 자동 `locked=true`(60일 삭제 제외). 60일 밖의 과거는 `news-archive-search`(네이버+구글 재수집, Haiku 판정 자동 연결)와 세션 웹 리서치(`issue_case_ingest.py` → doc_category='이슈사례')로 복원한다.

- **단계 3개(발생→현안→해소) + 배지(🔥 7일 기사 수 / 💤 휴면)**. 전환은 자동(현안 신호: 법안·DIFF 연결/제재·처분/침해·장애/소송·판결), **해소만 수동**(사례화 부수효과·결론 해석은 사람 몫). 운영자 개입은 승인/기각·해소 두 번뿐.
- **자동 제안**: `issue_suggest.py`가 crawler.py 말미에서 매시 실행(fail-open 격리). 뉴스 클러스터(기사≥5&2일 or 긴급≥3&3일) + 무보도 규제(law_diffs high·핵심 입법예고) 2계열. 중복 억제: norm_key / 임베딩 ≥0.80 자동 연결 / proposed·rejected와 ≥0.72면 skip — **기각 재제안 문턱도 0.72**(0.80은 클러스터 벡터 특성상 0.72~0.79 쌍둥이가 전부 샘 — 기각 3건이 하루 만에 재제안된 실측, #119). 임베딩이 못 잡는 표현 변형(이슈끼리 0.63 수준)은 아침 진단에서 수동으로 거른다. 1회 상한 5건(초과 이월). 제안·현안 전환·종결 제안은 **운영자봇** 텔레그램(구독자봇 금지).
- **승인·기각·해소 파이프는 Edge `operator-webhook` 한 벌** — 텔레그램 인라인 버튼(`iss|action|id`)과 대시보드가 같은 함수를 호출한다. **승인 시 자동 보강 2단**(2026-09-01, "승인하면 3G·5G 이슈처럼"): ①과거 뉴스 재수집(news-archive-search) ②Sonnet 3콜로 영향 요약·이해관계자 초안·기존 법령 주제 매칭(`enrichIssue`, 승인당 ~40원). 자동 생성물은 "(자동 생성 초안)"·model='claude-sonnet-5-auto' 표시가 붙고 **기존값은 절대 덮지 않는다**. 신규 법령 주제 생성·과거 사례 문서·기점 소급은 조문·사실 검증이 필요해 세션 몫. `action:'enrich'`(관리자 JWT 또는 service-role Bearer)로 빈 항목만 수동 재보강 가능. 기각 시 다른 이슈에 안 걸린 기사만 잠금 해제.
- 이슈·연결·잠금 기사는 **영구 보관, 삭제 기능 없음**(잘못 만든 이슈는 기각/보관). 해소 시 종결유형(resolution_kind) 기록, 휴면 90일이면 "자연 소멸 종결?" 제안.

이슈맵 관련 하지-말-것:
- **`operator-webhook`은 `--no-verify-jwt`로 배포할 것** — 텔레그램은 Authorization 헤더가 없어 verify_jwt가 켜지면 게이트웨이에서 전부 차단된다(버튼 무반응인데 함수 로그에 아무것도 없으면 이것부터 의심). 관문은 `X-Telegram-Bot-Api-Secret-Token`+chat_id 검증이다.
- **화면 로드 시 자동으로 도는 AI 호출에 "0건이면 전체를 훑는" fallback을 두지 말 것** — Daily Briefing이 최신 브리핑에 미분석 긴급 항목이 0건이면 목록 전체(93일치 긴급 146개)에 Haiku 영향도 분석을 걸어, 로그인 사용자가 화면을 열 때마다 146회 호출·하루 452회가 됐다. 브라우저의 호스트당 동시연결 6개가 그 큐에 묶여 **로그인 상태에서만** 다른 화면이 몇십 초 멈췄고(비로그인은 AI 호출이 없어 정상), 증상이 "장애"처럼 보였다. 자동 AI 호출은 **대상을 좁게(최신·미저장) 고정**하고, 급증 판별은 `advisory_usage`의 general 카운트(전날 대비)와 `function_edge_logs`의 분당 POST 수로 한다. (배경역사 #118)
- **CORS 허용 목록은 `claude-proxy`·`news-archive-search`·`operator-webhook` 세 함수를 함께 고칠 것** — 한쪽만 고치면 그 주소에서 해당 기능만 조용히 죽는다. GitHub Pages 주소 누락으로 AI 기능 전체가 "Failed to fetch"였던 사고(#110)의 재발 방지. 증상 판별: Edge 로그에 OPTIONS 204만 있고 POST가 없으면 브라우저가 CORS로 본요청을 차단한 것.
- **document_chunks에 벡터를 일괄 insert하지 말 것** — 4만 행+HNSW에서 12행 일괄도 statement timeout(57014). `issue_case_ingest.py`처럼 3건씩 분할.
- **news_feed의 `event` 라벨로 사건을 묶지 말 것** — 같은 사건이 유사 라벨 6~7개로 갈라지고(펨토셀 실측), 본문에 스친 주제가 라벨로 붙는다(2분기 실적 기사 수십 건에 "통합요금제 출시" 라벨). 묶음은 `news_dedup.cluster_star`(제목 키워드, 임계 3)로.
- **이슈 휴면 판정은 `issue_links.created_at`(링크가 추가된 시각) 기준** — `last_activity_at`(콘텐츠 날짜)로 하면 과거 기사를 보강한 당일 이슈가 "N일 무활동"으로 오판된다(실측).
- **요약을 `txt[:250]` 같은 하드 슬라이스로 자르지 말 것 — `clip_sentence()`(문장 경계 절단)를 쓸 것** — 화면에 "…SK텔레콤 관점의 요약을 "처럼 말이 끊긴 채 노출된다(운영자 지적 2026-09-01). **한국어 메타응답도 거절문과 같이 막을 것**(`META_KO_RE`) — 영어 거절문(REFUSAL_RE)만 막고 있어 "제공하신 회의록에서 SK텔레콤을 직접 언급하는 부분이 없습니다…" 류가 20건 저장돼 있었다. 요약할 내용이 없으면 규칙 폴백이 정답이고, 이미 저장된 20건은 세션에서 직접 서술형으로 교체했다. (#113 후속)
- **`ANTHROPIC_API_KEY`가 없으면 발언 적재를 건너뛰도록 한 가드(`build_speech_rows` 선두)를 제거하지 말 것** — 폴백 요지를 쌓느니 안 쌓는 편이 낫다. 섹션(회의록 본문)은 그대로 적재되고, 키가 돌아온 뒤 실행에서 `speeches_exist`가 비어 있어 **자동 소급 적재**된다. (#113)
- **발언 요지를 API 키 없이 생성해 저장하지 말 것 — 규칙 폴백은 '원문 앞 문장 절단'이라 요지가 아니다** — 2026-09-01 실측 4,749건 중 1,420건(30%)이 그 상태였다(40자 미만 551·문장 끊김 340·중간 토막 674). `chunk_seq`는 파서 개선으로 옛 값과 어긋나고 요지↔원문 매칭률이 0%라 **행 단위 수리가 불가능**하며, 유일한 복구 수단은 국회 API 전량 재수집(무료)+재요약이다. 재수집 도구 3종: `tools_speech_dump.py`(백업+원문 덤프, AI 0회) → 세션 서브에이전트 요약 → `tools_speech_load.py`(회의 단위 교체, 검증 실패분 제외).
- **회의록 발언 적재에서 사회·호명 발언 배제(`is_noise_speech`)를 빼지 말 것** — "잠깐만 기다려 주십시오, ○○○ 위원님" 같은 진행 발언이 인물 프로필 발언 이력에 남아 "무슨 내용인지 알 수 없는" 행이 된다(운영자 지적 2026-09-01). **원문(raw)을 저장하지 않아 사후 재요약이 불가능하므로 적재 시점이 유일한 방어선**(#99). 길이만으로 자르지 말 것 — 20~55자에도 실질 발언이 많다(실측). 진행 문구+짧음의 교집합만 뺀다. 기존 `is_procedural`(개회·선서 등 의례 판정)과 목적이 달라 별도 함수이며, 이미 적재된 과거분은 화면에서 `_isProceduralSpeech`로 접어 보여준다(삭제 아님).
- **이슈맵 링크 조회(`loadIssueMap`)의 전량 페이징을 제거하지 말 것** — `issue_links`가 1,000행을 넘은 순간(2026-08-27 실측 1,478행) PostgREST가 잘라 **오래된 연결이 통째로 사라지고 화면은 "아직 연결된 항목이 없습니다"**로 보인다(에러 없음 — 조용한 실패). 5G 이슈(85건, 2021년부터)·3G 이슈(155건)가 동시에 빈 것처럼 보였다. `.order('id')+range` 루프로 받고이슈별 최신순 정렬은 JS에서 한다. **연결이 늘어나는 화면은 모두 같은 위험** — 새 목록 조회를 만들 때 총행수부터 확인할 것. (#66·#71 계열)
- **이슈 정의문(definition)에는 배제 기준까지 쓸 것 — 매시간 관련 판정이 정의문을 근거로 쓴다** — 이슈 9·10의 정의가 느슨해 'SKT+AI' 낌새만 있으면 통과, 에이닷 로그·에어 프로모션·주가 리포트까지 붙어 230건을 세션 전수 판정으로 해제했다(2026-09-01). 정의에 "~절차 보도만 해당, 제품 출시·실적·주가 기사는 해당 없음" 형식으로 경계를 명시할 것. **과반 겹침 가드는 오염된 이슈를 증폭시킨다**(오염 이슈 기준으로 홍보 클러스터를 계속 흡수) — 이슈가 비대해지면(300건+) 연결 기사 감사부터.
- **이슈 제안의 과반 겹침 가드·생성 제목 재검사를 제거하지 말 것** — 클러스터 멤버 과반(최소 2건)이 이미 같은 active 이슈에 연결돼 있으면 제안 대신 그 이슈로 연결(임베딩은 짧은 제목 탓에 0.6대로 낮게 나와 문턱을 못 넘고, Sonnet 판정도 대표 제목이 지저분하면 놓친다 — 무임승차 거품 하루 4건 실측: 제안 25·29·32·33). `_propose`의 생성 제목 재검사(≥0.80 병합)는 그 보완. 2건짜리 클러스터의 1건 겹침(1/2)은 과확장이라 최소 2건 조건 유지. (2026-08-27)
- **주간 모음·브리핑류 기사(`위클리`·`소식_`·`[통신 브리핑]` 등)를 이슈 제안 클러스터에 넣지 말 것** — 통신 3사 이름이 늘 나열돼 회사명만으로 공유 키워드 임계(3)를 채우는 오염원. 다이제스트가 별(대표)이 되면 Sonnet 관련 판정은 "특정 이슈 소속 아님"을 정당하게 내리고, 제안 제목만 그럴듯하게 생성돼 중복 제안이 된다(이슈 29 "3G 종료" 재발, 2026-08-27). `issue_suggest._is_digest`로 입력에서 제외 — 뉴스 목록·브리핑에는 그대로 남는다.
- **이슈의 관련 법령은 law_topic 주제 큐레이션이 정본** (2026-08-26 운영자 지시 "통짜 파생 말고 관련된 것만") — `issue_links(item_type='law_topic', item_id=주제 노드명)`이 있으면 상세 화면이 관계도 주제 노드의 엣지(조문 단위 역할 설명)를 보여주고, 통짜 하위법령 파생은 주제가 없을 때만 폴백. 주제 노드·엣지는 `source='ai'`로 넣으면 매일 17시 관계도 재구축에도 보존된다(빌더는 자기 소스 유형만 재생성). 승인/기각 버튼은 화면(isAdminUser)·서버(webhook JWT→role='admin') 모두 관리자 전용.

## 인물 프로필 (people, 2026-08-27 신설 — 배경역사 #112)

과방위 **의원 + 정부·참고인**(장차관·기관장·기업 증인)의 발언 이력을 인물 축으로 재집계한 사이드바 메뉴(법안 동향 그룹). 딥리서치(Quorum 의원 프로필·코딧 의원 페이지·국회도서관 아르고스 패턴)에서 채택, 일문일답 5건으로 범위 확정.

- **원천**: `people`(명부·AI 요약 캐시) + `assembly_speeches`(발언, speaker_key 정확 일치) + `assembly_bills`(대표발의, `proposer ilike '이름의원%'` — '김현의원*'은 '김현정의원'과 매칭되지 않음) + `news_feed`(뉴스 언급).
- **뉴스 언급은 "이름+직함" 정확 구문 매칭만**("김현 의원", "류제명 차관") — 동명이인 오염 방지. 운영자 원칙: "명확히 알 수 있으면 넣고, 복잡하면 제외". 직함 단어를 못 뽑는 인물은 뉴스 섹션 생략.
- **현역 판정은 명단 시드가 아니라 "22대(2024-06~) 발언 존재"(is_22)** — 후반기 과방위 개편(2026-06-30, 국힘 사임계 등)처럼 명단이 유동적이어서, 신규 위원은 발언이 쌓이면 자동 등장하는 구조로 설계. 정당(party)은 활동 당시 소속을 시드로만 기록(현재 소속 아님).
- **AI 쟁점별 입장 요약**: 최초 전원(22대 활동 31명)은 세션에서 생성(비용 0), 이후 갱신은 프로필의 [요약 갱신] 버튼(로그인 → claude-proxy, 쿼터 차감, people에 캐시). 질의는 비판조가 관행이므로 요약은 단정을 피하고 발언 날짜를 근거로 붙인다.
- 명부 대상: 발언 4건 이상(140명). 한자 표기 발언자는 name(표시명)/speaker_key(원문 키) 분리(金炳旭→김병욱).

## 점검 체크리스트 (요약 — 상세 경위는 배경역사 문서)

- **이상 의심 시 1차 점검**: 대시보드 설정 밑 **"운영 상태"** 탭 — 크롤러 heartbeat·뉴스 입력·오늘 브리핑·입법예고·국회 한눈. (배경역사 #16)
- **브리핑 미수신**: Actions(morning_briefing.yml) 확인→실패 시 "Run workflow" / 성공인데 미수신→`resend_briefing.py` / 09:40 후도 미수신→`briefing_backup_log.txt`. 본문 0건이어도 요약/제목 폴백으로 빈 브리핑은 안 나옴(배경역사 #16). **트리거·PAT·크롤러 heartbeat 다 정상인데 미생성이면 24h 내 신규 기사 0건을 의심** — 그날은 '🕊️ 신규 뉴스 없음' 통지+placeholder가 정상 동작(고장 아님). daily_crawl 로그 `[네이버 뉴스] N건`으로 'NAVER 키 만료(폴백만)' vs '진짜 뉴스 없음'(N>0·실패0) 가름. (배경역사 #17)
- **트리거 전부 무음 정지(크롤·브리핑·국회·법령 동시 미동작)인데 cron 잡은 다 succeeded**: PAT 권한/만료 의심. cron 잡 상태(net.http_post 비동기라 항상 succeeded)가 아니라 `net._http_response.status_code`로 dispatch 응답 확인 — 403=Actions 권한 부족, 401=토큰 무효, 204=성공. PAT 재생성했다면 Actions(R/W) 권한 누락 여부 확인. (배경역사 #18)
- **heartbeat(운영상태)는 멈췄는데 스케줄러 작업은 '준비/실행됨'이면 PC 꺼짐이 아니라 스크립트 크래시/오류**: 작업 스케줄러에서 *마지막 실행 결과* 확인(0x0 정상 / 0xC000013A 강제종료=크래시 / 0x1 일반오류) + 스크립트 로그(`refetch_log.txt`·`gov_crawler_log.txt`). 흔한 원인=cp949 이모지 print 크래시 또는 작업 동작 경로가 옛 폴더. 본문수집/입법예고가 같이 멈췄으면 1순위 의심. (배경역사 #19) **0xC000013A가 시작 직후(수 초 내)면 스크립트가 아니라 전원을 의심** — 노트북 AC↔배터리 전환 시 schtasks 기본값 "배터리 전환 시 중지"가 작업을 Ctrl+C로 죽인다(로그에 `^C`만 남음). Kernel-Power 이벤트 105·506/507 확인. 저장소 실행 작업은 전부 AllowStartIfOnBatteries·DontStopIfGoingOnBatteries·StartWhenAvailable 적용 완료(브리핑은 WakeToRun 추가) — **새 스케줄 작업을 만들 때도 이 3종 설정 필수**. (배경역사 #55)
- **뉴스 미축적**: daily_crawl.yml 로그 "[네이버 뉴스] N건". N=0→NAVER 키 누락·만료(폴백만 돔) / N>0인데 신규0→cron 드롭, "Run workflow".
- **크롤·브리핑이 ~20초 만에 동시 실패(`RemoteProtocolError: Server disconnected`)**: supabase-py HTTP/2 끊김 → `sb_client.make_client`(HTTP/1.1)로 해결됨. 재발 시 `create_client` 직접 호출 파일 없는지 확인. 크롤은 성공인데 news 0·브리핑 빔이면 본문 미수집 → PC `python refetch_content.py` 실행 후 브리핑 재실행. (배경역사 #15)
- **입법예고 미수집**: DB law_type='lsAnc' 건수·MAX(created_at) 확인. `gov_notice_crawler.py` 로그. PC 의존(17:00).
- **AI 자문 "Failed to fetch"**: 무거운 질문 2분+ idle 끊김 → stream:true로 해결됨. 사내망 프록시·확장프로그램·F12 네트워크 확인.
- **보고서 초안 미생성·학습**: Claude 키 / report_samples 2편↑·"스타일 재학습" / embedding NULL→`backfill_report_embeddings.py` / report_directives 행 / 임계 +2건.

## 하지 말아야 할 것 (규칙 + 한 줄 이유 / 상세는 배경역사 문서)

- **세션 주도의 일회성 AI 대량 작업을 Edge Function 수동 호출로 돌리지 말 것** — 함수 내부가 Anthropic API를 불러 별도 과금된다. 이슈맵 과거뉴스 백필을 `news-archive-search` 반복 호출로 처리했다가 크레딧 재결제 주기가 3~5일→1일로 줄어 운영자 재지적(2026-08-26, #111). 세션 백필은 세션이 직접 검색·판정·INSERT(비용 0), Edge 경로는 무인 자동화(승인 훅·대시보드 버튼) 전용.
- **회의록 다이제스트는 신규 섹션 + 60일 이내 + 발언 3건↑에서만 큐에 넣을 것 — 백필·오프라인 임포트 경로에서는 절대 적재 금지(#120)** — `register_kb_section`이 True를 돌려준 새 회의만, `DIGEST_MAX_AGE_DAYS`·`DIGEST_MIN_SPEECHES` 가드를 통과해야 `queue_for_subscribers('assembly')`. 20·21대 소급(300건↑)이나 재요약이 큐로 새면 구독자 6명이 옛 회의록 수백 통을 받는다. `minutes_offline.py`는 subscriber_notify를 임포트조차 하지 않는다. 날짜 파싱 실패는 fail-closed(적재 안 함).
- **요약 프롬프트에 '통신사 관점'·'SK텔레콤 관점' 같은 관점 지시를 넣지 말 것(#120)** — 모델이 관점을 못 찾으면 "SK텔레콤이 직접 언급되지 않았습니다"·"정책 논의는 없었다" 같은 **언급 없음 메타응답**을 내고 그것이 요약으로 저장된다(실측 3건). 요약은 "무엇이 논의됐는지"만 묻고, 자사 언급 표시는 규칙(`skt_mentioned`)으로 따로 붙인다.
- **일회성 AI 작업(재요약·과거 대수 소급)은 세션이 하고 Anthropic API를 쓰지 말 것(#120)** — Sonnet 5 API로 640회의 ≈ $110, 세션이면 0. `minutes_offline.py`의 export → 세션 판정 JSON → import 파이프라인을 쓴다. `assembly_minutes.py --year <작년 이전>`은 `--allow-api` 없이는 거부되도록 잠가 뒀다 — 이 잠금을 풀지 말 것. API는 무인 반복(17시 체인)에만.
- **Sonnet 5 비스트리밍 호출에는 `thinking={'type':'disabled'}` 필수(#120)** — 적응형 추론이 기본 ON이라 thinking 토큰이 과금되고 `content[0]`이 텍스트 블록이 아니어서 `content[0].text` 읽기가 깨진다. `assembly_minutes.py`의 `MINUTES_THINKING`이 모든 호출·`make_ai_judge(thinking=)`에 전달된다. 새 Sonnet 5 호출을 만들면 같은 값을 넘길 것.
- **국회회의록 뷰어 본문을 검증 없이 믿지 말 것(#120-보론)** — 뷰어(`xml.do?id=`)가 id에 따라 **다른 위원회 회의록 본문**을 돌려주는 일이 있다(실측 8/281 — 미방위 법안소위 id에 2025 국방위 1,059블록, 과방위 id에 국세청 본문). 제목·HTML 머리는 맞아서 눈으로는 모른다. 상임위 회의는 Open API PDF와 대조(`verify_blocks_against_pdf` + `looks_foreign_committee`)하고 불일치면 PDF 폴백, PDF도 없으면 등재하지 않는다. 소관 표지에 '위원장'·'전문위원' 같은 일반 직위를 넣으면 검사가 무력화된다. 검증 없이 등재된 과거 섹션은 `minutes_offline.py --verify-exported --fix`로 교정한다.

- **"조용한 실패"를 만들지 말 것 — 2026-08-03에만 4건, 이후로도 계속 나온다.** 에러 없이 결과만 틀리는 코드는 며칠씩 발견되지 않는다. 실측 사례: ①뉴스 1,000건 초과 시 조회가 잘려 이미 알림한 기사를 재발송 ②`.range()` 페이징에 `.order()`가 없어 관계도 노드가 매 실행 오삭제 ③refetch가 해외 기사를 수집 즉시 삭제 ④뉴스 클러스터가 연쇄 병합으로 91건 한 덩어리 ⑤**RLS 정책에 `authenticated`가 빠져 로그인 사용자에게만 10개 테이블이 0행**(#108 — 관계도 빈 화면, AI 자문 법령요약 갈래 소실). **판정·필터·삭제 로직을 만들면 "틀렸을 때 무엇이 보이는가"를 먼저 정하고, 안 보이면 로그를 남길 것.**
- **조회 컬럼 목록(`select(...)`)에서 조건에 쓰는 컬럼을 빠뜨리지 말 것** — 값이 `undefined`/`None`이 되어 **조건이 조용히 무력화**된다(에러도 안 난다). 2026-08-03 하루에 세 번 발생: 구독자 `tags`(전원 전체수신으로 퇴화), refetch `category`(해외 예외 미작동), 뉴스 목록 `tags`(클러스터 태그 조건 무력화). `select('*')`가 아닌 **명시 목록**을 쓰는 곳은 조건 추가 시 반드시 함께 갱신.
- **뉴스 클러스터링은 대표 기사 기준으로만 묶을 것(연쇄 금지)** — "그룹 안 어느 하나와라도 유사하면"으로 하면 A~B, B~C로 이어붙어 무관한 기사가 한 덩어리가 된다. 통신 뉴스는 '통신3사·요금제·출시' 같은 흔한 단어를 공유해 특히 잘 번진다(실측 91건). `_groupNews`(app.js)는 `group[0]`과의 유사도 + 분야 태그 교집합으로 판단한다. (2026-08-03)
- **뉴스 보관 규칙(60일 삭제)에 `category='해외'`를 넣지 말 것** — 해외 규제기관은 발행일이 오래된 문서를 뒤늦게 공개하는 게 정상이라, 발행일 기준으로 지우면 **수집 즉시 삭제**된다(2026-08-03 실측: 05:30 수집 4건이 06:05 브리핑에 실린 뒤 refetch(:22)에 삭제). `refetch_content.py` 두 지점 모두 예외. 예외 조건에 쓰는 컬럼은 **select 목록에도 반드시 추가**할 것 — 빠지면 None이 되어 조용히 안 먹는다. (배경역사 #75)
- **지식베이스 그룹(`_KB_GROUPS`, app.js)은 문서명 문자열 매칭이다** — 새 계열을 등재하면 그룹을 함께 추가하고 **화면에서 실제 소속을 확인**할 것. 안 하면 전부 '기타 법령·고시'에 뭉친다. 오분류가 쉽게 생긴다: 「이용약관 인가대상 **기간**통신서비스」가 `/전기통신사업/`에 안 걸려 공정거래 그룹의 `/약관/`에 잘못 묶였다(기간≠전기). (2026-08-03)
- **REINDEX 전에 디스크 여유부터 확인할 것** — 인덱스 재구축은 원본+사본을 동시에 요구한다. 2026-08-03 새벽 258MB HNSW 재구축이 **2GB 디스크**를 터뜨려 인스턴스가 통째로 읽기전용이 됐다(크롤러·브리핑 동반 중단). **디스크가 8GB로 자동 확장된 뒤 정상 수행 완료**(키워드 2.34→1.75초, 의미 0.209→0.078초). 앞으로도 `REINDEX INDEX`로 하나씩, 여유 확인 후. (배경역사 #69·#72)
- **Supabase 디스크는 "포함 한도"와 "실제 할당량"이 다르다** — Pro 포함은 8GB이나 **실제 디스크는 2GB로 시작해 90% 도달 시 자동 확장**된다(2026-08-03 02:25 2GB→8GB, 무료·영구). 게다가 `max_wal_size=4GB`라 **WAL 혼자서도 작은 디스크를 채울 수 있다**(사고 시점 WAL 864MB > DB 619MB). 대량 적재·재구축 전에는 Settings→Infrastructure의 DISK 내역(DATABASE/WAL/SYSTEM)을 볼 것. **Spend cap이 켜져 있어 한도 초과 시 과금이 아니라 읽기전용으로 전환**된다. (배경역사 #72)
- **스케줄 작업을 콘솔 창이 보이는 형태로 등록하지 말 것** — 창이 닫히면 CTRL_CLOSE로 프로세스가 죽는다(0xC000013A). 반드시 `pythonw run_hidden.py <script.py>` 경유. 액션 변경 후에는 등록된 Arguments를 눈으로 확인(PowerShell에서 `$args`를 파라미터명으로 쓰면 자동 변수와 충돌해 인수가 빈다). (배경역사 #70)
- **전량 페이지 조회는 순차 `await` 루프로 짜지 말 것 — 행이 늘면 대기가 그대로 누적된다(#117).**
  `for (off=0; off<N; off+=1000) { await ... }` 구조는 앞 페이지 응답을 기다려야 다음 요청이
  나가므로, 행 수에 **비례해 왕복 시간이 늘어난다.** 실측: 뉴스 목록이 5,401행(6회) →
  9,031행(11회)이 되며 누적 4,692ms까지 늘었고, `Promise.all` 병렬 전환으로 **1,648ms**가 됐다
  (화면·기능·정렬 무변경 — `Promise.all`은 입력 순서를 보존한다). 페이지 수는 `count`
  (`{ count:'exact', head:true }`) 1회로 계산한다.
- **자라는 테이블에 하드코딩 상한을 두지 말 것 — 넘는 날 조용히 잘린다(#117).**
  뉴스 로드에 `off < 10000`이 박혀 있었고, 9,031행·하루 300행 증가 시점에서 **3일 뒤 도달**
  예정이었다. `published_at` 내림차순이라 넘으면 오래된 기사가 **에러 없이** 사라진다.
  세어서 계산하고, 부득이 상한을 두면 초과 시 `console.warn`/로그로 **소리를 낼 것**.
- **정렬 컬럼에 인덱스가 있는지 확인할 것(#117).** `news_feed`는 `published_at` 인덱스가 없어
  페이지마다 `Seq Scan` + 전체 정렬을 했고 `Sort Method: external merge Disk: 6528kB`로
  디스크에 흘러넘쳤다(RAM 2GB 인스턴스라 work_mem이 작다). 인덱스 추가로 Index Scan +
  25.7ms→13.3ms. **제안 전 `explain (analyze, buffers)`로 실제 계획을 볼 것** — `external merge`
  가 보이면 정렬 인덱스가 없다는 신호다.
- **"느리다"는 증상은 층을 나눠 재고 나서 고칠 것(#117).** 서버 쿼리 / 네트워크 왕복 /
  클라이언트 연산 / 렌더는 원인도 처방도 다르다. 이번엔 겹루프라는 **모양만 보고**
  `_groupNews`를 범인으로 의심했으나, 함수만 뽑아 node로 벤치하니 9,031행 116ms로 준선형이었다
  (같은 날짜만 비교하는 가드 덕분). 고쳤다면 멀쩡한 코드를 건드리고 원인은 남았을 것이다.
  브라우저 실측은 `performance.getEntriesByType('resource')`로 요청별 시작·종료를 보면 된다 —
  계단식이면 순차, 겹쳐 있으면 병렬이다.
- **PostgREST 전량 조회에 페이지네이션 없이 `select()`만 쓰지 말 것** — 1,000행에서 잘린다. 총량이 상한을 넘는 첫날 조용히 터지며, 실제로 뉴스 1,086건 시점에 최신 86건이 누락돼 **이미 알림한 긴급 기사를 재발송**했다. `crawler._fetch_all_rows()` 패턴 사용. `.range()` 페이징에는 **반드시 `.order()`** — 정렬 없는 페이징은 행 누락이 비결정적이다. (배경역사 #66) **`build_law_citation_graph.py`가 이 규칙을 4곳에서 어기고 있었고(2026-08-03 발견), 관계도가 매 실행 다른 결과를 내며 인용 엣지 337건이 조용히 누락돼 있었다 — 새 스크립트 작성 시 `.range()`를 쓰면 `.order('id')`가 붙었는지 반드시 확인.** (배경역사 #71)
- **자문의 [국회 동향] 블록을 조문·요약·기사보다 앞에 두지 말 것** — 근거가 아니라 배경이다. 출처 배지에도 넣지 않는다. 의견등록 가능 여부를 통과 기준에 넣지 말 것(무관 법안이 마감일만으로 올라온다 — 순위 가점만). (배경역사 #68)
- **API 키 하드코딩 금지(공개 repo)** — .env·GitHub/Supabase Secrets에만. (Voyage 키 유출 사례)
- **"통신이 사건의 수단·배경으로만 등장하면 무관" 규칙은 뉴스·입법예고 양쪽에 둘 것(2026-08-25).**
  입법예고 기준문에는 #102(독립유공자법) 이후 이 규칙이 있었는데 **뉴스 기준문에는 없었다.**
  같은 원리인데 한쪽만 막혀 있어, 제주 실종자 사건 기사가 「기지국 위치 추적」·「정보통신망법
  인용」이라는 배경 서술만으로 긴급까지 올라갔다. 기준문을 고칠 때는 **다른 기준문에도 같은
  구멍이 있는지** 함께 확인한다(뉴스 `news_relevance_criteria` ↔ 입법예고 `assembly_notice_criteria`
  ↔ 보도자료 `press_relevance_criteria`).
- **뉴스 판정 기준을 "피드백이 알아서 배우겠지"로 미루지 말 것(#107)** — `importance_feedback`은
  **제목과 등급만** 저장하고 **이유는 남기지 않는다.** 운영자가 등급을 고친 이유(분야 무관/주체가 SKT 등)는
  20건 사례에서 Haiku가 추론해 낼지 알 수 없다. 확실한 기준은 기준문에 직접 쓴다 — 관련성은
  `app_config.news_relevance_criteria`(DB, 즉시 적용), 긴급도는 `crawler.py`의 `_URGENCY_CRITERIA`
  (코드). ⚠️ **적용 시점은 실행 경로를 확인하고 말할 것** — GitHub 계정 정지 이후 크롤러는
  이 PC의 작업 스케줄러 `radio_TEMP_crawl_hourly`(매시 :50, 작업폴더가 저장소)로 돌고 있어
  **파일을 저장하면 다음 실행부터 바로 적용**된다(push 대기 불요). 긴급도 항목은 **순서가 의미를 갖는다**:
  뒤에 붙이면 "긍정적 내용은 즉시대응 제외" 단서에 먹히므로 우선 규칙은 맨 앞에 둔다.
  **[제1원칙 — 주체와 파급]이 개별 기준보다 먼저 적용된다**(#107): SKT 당사자 → 즉시대응(단
  일상 영업 활동은 금주검토, 요금 인상·약관 변경은 즉시대응) / 경쟁 통신사 → 기본 등급 유지하되
  "우리도 같은 지적을 받을 수 있는가"면 승격 / 통신장비사·타 업종·공공기관 → 한 단계 하향.
  ⚠️ **포괄 규칙을 쓸 때는 "포함되지 않는 것"을 함께 적을 것** — "SKT면 즉시대응"에 부정·재무만
  예시로 달았더니 상품 출시까지 긴급이 됐다(같은 날 교정).
- **낱말이 같아도 분야가 다르면 무관 — 실례와 함께 기준문에 남길 것.** `혼신`/`이혼신고`와 같은 함정이
  '중계기'에도 있었다(라디오 방송 중계기 ≠ 이동통신 중계기, #107). 경계 사례는 문장으로 박아 둬야 재발하지 않는다.
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
- **fcc.gov 안의 /rss 경로를 RSS로 믿지 말 것** — HTML을 반환하는 가짜 경로다. 진짜 피드는 EDOCS API(api2.fcc.gov)에 있다. Ofcom은 전 경로 Cloudflare 차단이라 직접 수집 시도 금지(구글 뉴스 site: RSS 우회 유지). (배경역사 #54)
- **국회 회의록은 PDF가 아니라 뷰어(xml.do)가 정본** — PDF_LINK_URL의 PDF는 pdftotext에서 중반부 글리프가 깨진다(폰트 문제). 뷰어의 발언자 단위 구조를 쓰고 PDF는 폴백으로만. (배경역사 #54) 단 **뷰어 본문이 다른 위원회 회의록인지는 PDF로 검증**한다 — 정본이라도 id 오응답이 있다(#120-보론).
- **'보고서 초안 제안' 메뉴는 숨김 상태(삭제 아님)** — index.html 주석 2곳을 해제하면 복원된다. 패널·함수·report_* 테이블은 보존 중(봇 보고서 기능이 재사용 예정). (배경역사 #54)
- **구본(superseded) 청크는 임베딩을 두지 말 것** — 검색이 결과에서 걸러내는데 HNSW RAM만 차지한다(2,635개 제거로 작업세트가 캐시 안으로 들어옴). backfill_embeddings.py에 status neq.superseded 필터가 있으니 제거하지 말 것. promote_due가 새로 강등한 구본은 임베딩이 남는데, 작업세트가 다시 캐시에 근접하면 `update document_chunks set embedding=null where status='superseded'` + REINDEX로 정리. (배경역사 #54)
- **Supabase 파이썬 클라이언트는 `sb_client.make_client` 사용, `create_client` 직접 호출 금지** — supabase-py 2.31 httpx HTTP/2 keepalive 끊김(RemoteProtocolError: Server disconnected) 회피(HTTP/1.1 강제+재시도). 신규 스크립트도 동일 적용. (배경역사 #15)
- **워크플로 pip를 버전 무고정으로 되돌리지 말 것(`requirements.txt` 유지)** — 무고정 자동 최신화가 어느 날 갑자기 깨뜨림(HTTP/2 사고). 버전 올릴 땐 한 번에 하나씩 바꿔 Run으로 검증. (배경역사 #15)
- **GitHub PAT 재생성·교체 시 Actions(R/W) 권한 확인 누락 금지 / pg_cron 'succeeded'를 트리거 성공으로 믿지 말 것** — fine-grained PAT 필수권한은 Contents(R/W)+Metadata(자동)+Actions(R/W). Actions가 빠지면 git push는 되지만 workflow_dispatch는 403, 그런데 net.http_post가 비동기라 cron 잡은 succeeded로 찍혀 모든 트리거가 무음으로 멈춤. 교체 검증은 `net._http_response.status_code`(204=성공)로. (배경역사 #18) **저장소를 다른 계정·조직으로 옮기면 fine-grained PAT은 즉시 무효** — 토큰은 resource owner(계정/조직) 단위라 옛 소유자 토큰은 새 소유자 저장소에 403. 이전 직후 조직 소유 토큰을 재발급해 Vault를 갱신하고, `dispatch_github_workflow`·`trigger_briefing_if_missing`의 저장소 경로도 함께 바꿀 것(GitHub 리다이렉트에 기대지 말 것). (배경역사 #116)
- **모닝 브리핑 빈-브리핑 폴백(요약→제목)·`already_sent_today` 폴백 교체 허용 로직 제거 금지** — PC 꺼진 날 빈 브리핑 방지 + 본문 채워지면 정식본 자동 교체 핵심. (배경역사 #16)
- **기사 0건 무뉴스 통지(`_handle_no_news`)·`_NONEWS_PREFIX` placeholder·시각무관 1일1회 발송을 '09시 이전 무음 종료'로 되돌리지 말 것** — 무음 누락 오인 방지. placeholder는 기사 들어오면 정식본 자동 교체(폴백과 동일 패턴), 중복은 placeholder 존재로 1일1회 차단. `already_sent_today`의 `_NONEWS_PREFIX` 교체 허용도 유지. (배경역사 #17)
- **워치독을 'DB 신선도만' 보던 방식으로 되돌리지 말 것 / 크롤러 heartbeat(`system_health` 3종: last_crawl_run·last_gov_notice_run·last_refetch_run) 쓰기·`system_health` 테이블 삭제 금지** — '고장 vs 없음(주말·드문 입법예고)' 구분·오경보 방지·운영상태 탭 핵심. (배경역사 #16)
- **권한 게이트를 `if (sub && !sub.권한)` 형태로 쓰지 말 것 — 반드시 `if (!sub?.권한)`(fail-closed)** — 구독 행이 없는 계정(=`/start`를 거치지 않고 곧장 명령을 보낸 경우)이 게이트·일일 한도·사용 로깅을 **전부 우회**한다. `/law` 승인제를 넣을 때 실제로 이 형태로 나갔다. (#100)
- **새 제약(승인제·한도)을 도입할 때 기존 사용자 소급 허용을 빠뜨리지 말 것** — 잘 쓰던 사람이 어느 날 막히면 그게 곧 장애 신고다. `law_allowed`는 마이그레이션에서 기존 5명을 `true`로 소급했다. 그리고 **조이는 기준은 "기능"이 아니라 "돈이 드는 경로"**다 — 같은 `/law`이라도 조문번호 직답(DB 조회만)은 승인 없이 연다. (#100)
- **LLM 응답을 검증 없이 DB에 저장하지 말 것** — `assembly_speeches.summary`에 영문 거절문("I appreciate you sharing this task…")이 그대로 들어가 화면에 노출됐다. **원문(raw)을 저장하지 않는 테이블은 재요약이 불가능해 생성 시점 검증이 유일한 방어선**이다. 한글 비율·거절 패턴을 확인하고 실패면 규칙 폴백을 쓴다. (#99)
- **폴백을 만들 때 폴백 결과물의 품질까지 설계할 것** — 무료 모드 폴백이 `원문[:120]`이라 2,877건이 문장 중간에서 잘렸다. "AI 없이도 돌아감"은 만족했지만 "AI 없이도 쓸 만함"은 아니었다. **적재 실패율 0은 품질 지표가 아니다 — 화면을 열어 사람이 읽어봐야 드러난다.** (#99)
- **자연어 파싱 결과를 화면에 안 보여주고 검색 범위만 조용히 좁히지 말 것** — assem의 대수(`22대`) 필터가 실제로 동작하는데 조건 칩에 안 찍혀 **먹혔는지 무시됐는지 알 수 없었다.** 규칙→AI 보조 파서를 이어 붙일 때 **AI 경로에서 규칙이 뽑은 필드를 떨어뜨리는지** 반드시 확인할 것(`dae`가 실제로 유실됐다). (#100)
- **장시간 배치를 백그라운드로 띄우기 전에 같은 작업이 이미 도는지 확인할 것** — 회의록 재작성 프로세스를 두 개 동시에 띄워 섹션 5건이 중복 등재됐다. **로그만 보면 둘 다 정상으로 보인다.** 더 비싼 건 그 뒤였다 — **중복을 지우면서 이웃 섹션 꼬리 청크까지 함께 지워** 3개 섹션이 본문 한가운데서 잘렸다(28,000자·7,700자·9,100자 유실). **중복 정리 DELETE는 반드시 `chunk_index` 범위를 명시하고, 지울 행 수·범위를 먼저 출력해 확인한 뒤 실행할 것.** 섹션 개수만 세면 98/98로 멀쩡해 보여 드러나지 않는다 — 검증은 `(max(chunk_index)-min(chunk_index)+1)-count(*) <> 0`(결번)으로 한다. (#99)
- **한국어 키워드를 단순 `in` 매칭으로 판정하지 말 것 — 앞뒤 글자를 함께 볼 것** — 한국어·약어는 단어 경계가 없어 오탐이 쌓인다. 실측: `AI`가 **KAIST·KAIT·KAI**에 걸려 topic 1위(1,399회)를 부풀렸고(오탐 199건), `무선`이 `실무선에서`에, `6G`가 `35.6GW`에 걸렸다. 오탐은 태깅만 망치는 게 아니라 **`relevance_score()`의 우선순위까지 왜곡해** 무관한 블록을 수록 상한 안으로 밀어 넣는다. 다만 **실측으로 확인된 오탐만 막을 것** — `요금소`·`전파상`은 말뭉치에 0회였고, `유무선`·`전파사용`·`AIDC`는 정상이라 살렸다. (기존 사례: `혼신`은 `이혼신고`에 걸려 아예 `전파간섭`으로 바꿨다) (#99)
- **내부 워치독을 뉴스·브리핑만 보던 방식으로 되돌리지 말 것 / `watchdog_scan()`·pg_cron jobid 16·`system_health.watchdog_alert_state` 키 삭제 금지** — 감시자(GitHub)가 감시대상과 함께 죽어 뉴스 15시간 무알림이던 사고(#62)의 재발 방지책. system_health 10키를 GitHub 독립적으로 전수 감시한다. 임계·note 실패신호(`fail=N>0`) 로직 수정 시 `new=0`을 실패로 오탐하지 말 것(정책 크롤러는 신규 없음이 정상). (배경역사 #62)
- **`watchdog_scan`에서 `check_news_health`·`check_briefing_health`를 병합·수정하지 말 것** — 세 함수는 의도적으로 분리(A 담당이 check_* Vault화 진행). watchdog_scan은 신규 함수로만 유지. (배경역사 #62)
- **운영 상태 탭(`panel-opsstatus`·`loadOpsStatus`)·system_health anon select 정책 제거 금지** — 이상 시 1차 점검 화면. (배경역사 #16)
- **사이드바 `.sidebar { overflow-y:auto }` 제거 금지** — 메뉴가 많아 화면보다 길어지면 설정·운영 상태 등 하단 항목이 잘림. (배경역사 #16)
- **PC 로컬 스크립트(refetch_content.py·gov_notice_crawler.py 등)의 stdout/stderr UTF-8 강제(`sys.stdout.reconfigure(encoding="utf-8")`) 제거 금지** — 스케줄러는 출력이 cp949로 잡혀 이모지 print가 `UnicodeEncodeError`로 무음 크래시(heartbeat 못 씀→간이 브리핑). 수동 터미널(UTF-8)은 멀쩡해 오진 유발. 신규 PC 스크립트도 동일 적용. (배경역사 #19)
- **Windows 작업 스케줄러 작업의 동작 경로를 옛 폴더(`…\frequence\전파정책전문가`)로 두지 말 것 — `radio-policy-ai`로 유지** — 폴더 이전 후 경로 미갱신 시 구 bat·없는 스크립트(gov_playwright_crawler.py) 호출로 0x1 실패. (배경역사 #19)
- **전파정책_정부크롤러 작업의 StartWhenAvailable(놓친 실행 보충)·배터리 허용을 끄지 말 것** — 매일 17:00 1회 실행이라 PC가 그 시각에 꺼져 있으면(금요일 조기 퇴근·주말·연휴) 그날 수집이 통째로 빠지고 보충도 안 됨 → 다음 부팅 직후 자동 보충이 유일한 안전망. 2026-07-04~06 주말 공백으로 heartbeat 3일 경고 재발한 사고의 재발 방지책. (배경역사 #22 후속)
- **`.bat`은 ASCII+CRLF만 — 편집했으면 반드시 바이트로 검증(비ASCII=0·bareLF=0), git status를 믿지 말 것** — 한국어 로케일 cmd가 UTF-8 한국어+LF 배치를 오파싱해 `echo [%date% %time%]` 줄을 `time` 명령으로 실행→대화형 프롬프트 무한 대기→heartbeat 무음 중단. `.gitattributes`의 eol 정규화 때문에 working tree가 LF로 훼손돼도 git status는 clean으로 보여 git으로는 탐지 불가. (배경역사 #22)
- **PC 스케줄러 작업·배치에서 bare `python` 호출 금지 — Python312 전체 경로(`C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe`) 고정** — 공유 PC에 다른 Python(3.13)이 설치되면 PATH를 가려 bs4 등 ModuleNotFoundError로 매일 무음 실패. 패키지는 3.12에만 설치돼 있음. (배경역사 #22)
- **gov_notice_crawler.py를 통째로 GitHub Actions로 옮기지 말 것 — 다만 이유는 '정부 사이트 해외 IP 차단'이 아니라 `opinion.lawmaking.go.kr` 한 곳 때문이다(2026-09-01 실측으로 정정)** — 12개 대상 페이지를 같은 방식(curl_cffi `impersonate='chrome110'`)으로 한국 PC와 GitHub Actions 러너에서 각각 재 봤더니, RRA 4곳·과기정통부 2곳·전파관리소 2곳·방통위·ETRI·KISDI **11곳은 Actions에서도 전부 정상**이었다. 실패한 것은 **입법예고(opinion.lawmaking.go.kr) 1곳뿐**이고, 그 실패도 오류가 아니라 **HTTP 200에 본문 4,464바이트·0행**(한국 PC는 95,569바이트·20행)이라는 **조용한 빈 껍데기 응답** — 데이터센터 IP 거부의 전형이며 2회 연속 재현됐다. 차단 축은 '해외냐'가 아니라 **'데이터센터 대역이냐'**다: 2026-08-28~31 운영자가 PC를 필리핀에 두고 돌렸을 때 나흘 내내 정상 수집됐다(총 68~71건, VPN 없음). 따라서 **해외 일반 ISP IP는 무해**하다. 이관하려면 크롤러를 쪼개 입법예고만 PC에 남겨야 하는데, 한 파일 안에서 수집·저장·알림·요약 백필이 엮여 있어 분리 비용이 이득보다 크다 — **현행 유지가 결론**이다. 재측정은 `python tools_gov_reachability.py`(읽기 전용, DB·알림 무변경), 원격은 `gov_reachability_test.yml`을 workflow_dispatch로 돌린 뒤 **check-run 주석**(`/check-runs/{job_id}/annotations`)에서 결과를 읽는다 — 잡 로그 API는 302 리다이렉트라 `net.http_get`으로 못 읽는다. (배경역사 #113)
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
- **`law_sync.py --all-outdated`를 무인 자동화하기 전에 OKF 자동 갱신을 먼저 붙일 것** — 조문만 자동 교체되면 OKF 요약이 옛 판을 설명해 *자문이 폐지된 조문을 근거로 답한다*. 그 밖에 ①보존 상한 초과분 삭제가 무인으로 도는 위험 ②API가 동명이법을 집어올 위험이 있다. 순서: `--dry-run` 보고 자동화 → 관찰 → OKF 자동화 → 실적용. (배경역사 #52) **2026-09-01 한 세션이 이 규칙을 알고도 승인 게이트를 없애고 6건을 무인 교체해 요약 6건이 옛 판을 설명하는 상태가 됐고, 세션 6개 병렬로 새 판 요약을 다시 썼다(#116). 워크플로에 `--all-outdated` 스텝을 넣는 변경은 커밋하지 말 것.**
- **`law_diff_gen.py`의 조문 DIFF는 별표·별지를 보지 않는다 — 고시 개정의 OKF 갱신은 신구 `document_chunks`를 직접 대조할 것.** 항공주파수 규정 제2026-446호에서 DIFF는 본문 5개 조만 잡았는데 별표 1이 실질 개정(청크 73→83, 4,200~4,400㎒ WAIC·RPAS C2링크 제5장 신설 등)돼 있었다. 고시는 분량 대부분이 별표라 DIFF만 믿으면 요약이 틀린다. (배경역사 #116)
- **`국내 법령·고시` 목록 필터를 '제외 목록' 방식으로 되돌리지 말 것** — 카테고리로 `ITU-R`·`추가지식`·`보도자료`를 제외한다. 예전엔 "ITU-R과 날짜파일 빼고 전부"라 논문·메모·보도자료 9건이 섞여 있었고, 제목에 `전자파`가 든 논문이 `전자파 행정규칙` 그룹에 끼어 보였다. **화면에서만 빼는 것이고 자문 RAG에서는 계속 검색돼야 한다.** (배경역사 #50)
- **`index.html`·`system_prompt.js`의 하드코딩된 문서 설명을 사실 검증 없이 두지 말 것** — `M.1544-1`이 "IMT 최소 성능 요구사항"으로 1년 넘게 잘못 적혀 있었다(실제는 아마추어무선 자격기준, 진짜는 Report M.2410). **프롬프트에 든 오류는 모델이 사실로 답한다.** 문서를 올릴 때 두 파일의 설명을 함께 갱신할 것. (배경역사 #49)
- **영문 원문(ITU-R 등)은 한국어 요약을 kb 레이어에 짝으로 둘 것 — 어휘 매핑으로 때우지 말 것** — 영문 문서는 한국어 질문에 임계값(0.45)을 못 넘는다(실측: `스퓨리어스 발사 한계값` 0.375, `spurious emission limits` 0.563). 제목에 한글 머리말을 붙여도 0.384로 미달이라 기각됐다. `regulatory-kb/references/itu-r/` 6건이 그 짝이며, **요약은 찾아가는 다리이고 수치·표 인용은 반드시 영문 원문에서** 한다. 새 ITU-R 문서를 올리면 한국어 요약도 함께 만들 것. (배경역사 #47)
- **RLS 정책에 `anon`만 적지 말 것 — 로그인 사용자에게만 0행이 된다(#108).** 로그인 도입(#104)
  이후 대시보드는 로그인하면 역할이 `anon` → `authenticated`로 바뀐다. SELECT 정책이 `{anon}`뿐이면
  **로그인한 사람만 아무것도 못 보고, 에러는 안 난다**(RLS는 예외가 아니라 0행을 준다).
  실제로 10개 테이블이 동시에 이 상태였다 — 관계도는 "데이터가 없습니다"라는 정상 화면처럼 떴고,
  AI 자문은 `kb_chunks`가 0건이라 **법령요약 갈래가 통째로 빠진 채 답변만 부실**해지고 있었다.
  대시보드가 읽는 테이블은 반드시 `to anon, authenticated`. 점검 쿼리:
  ```sql
  select tablename, policyname, cmd from pg_policies
  where schemaname='public' and roles::text like '%anon%'
    and roles::text not like '%authenticated%';   -- 0행이어야 정상
  ```
  ⚠️ service_role 전용 테이블(telegram_subscribers·subscriber_queue 등 정책 0개)은 해당 없음 — 의도된 설계다.
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

- **Windows 스케줄 작업을 만들 때 배터리 보호설정 해제 없이 등록 금지** — schtasks 기본값(배터리 전환 시 중지·배터리 시 시작 안 함)이 노트북 전원 흔들림에 작업을 시작 3초 만에 Ctrl+C로 죽인다(06:05 브리핑이 이렇게 무음 실패). AllowStartIfOnBatteries·DontStopIfGoingOnBatteries·StartWhenAvailable 3종 필수, 무인 새벽 작업은 WakeToRun 검토. (배경역사 #55)
- **저해상도 이미지의 OCR 결과를 검수 없이 KB에 등재하지 말 것** — 실측에서 전력선통신 고시의 주파수 표(567×378 BMP)는 OCR이 **수치를 오독**했고, 발표자료 PDF는 도형·장식을 글자로 잡았다. 자문이 틀린 수치를 근거로 답하는 것이 본문이 짧은 것보다 훨씬 해롭다 — 품질이 의심되면 **등재 반려하고 원인만 기록**한다. (배경역사 #60)
- **텔레그램 전송·Voyage 임베딩 호출을 새로 복사해 쓰지 말 것** — 공용 유틸 `notify.send_telegram()`·`embed_util.get_embeddings()`를 쓴다(분할·재시도·429 처리가 한 곳에 있음). 예외는 `health_watchdog.py`뿐(Supabase·공용 유틸에 의존하지 않는 독립 감시자라 의도적 중복). 공용 로직을 건드리면 `python -m unittest discover -s tests` 통과 확인. (배경역사 #58)
- **anon(브라우저 키)에 새 쓰기 권한을 열 때는 "화면이 실제로 하는 연산"인지 먼저 확인할 것** — 공개 Pages라 anon 권한은 전 세계 공개다. 특히 ①`app_config`의 `system_prompt` 행(봇 프롬프트 인젝션 경로), ②`document_chunks`의 `is_approved=true` 삽입(승인 게이트 우회 RAG 주입)은 다시 열지 말 것. 화면의 승인·비밀번호 절차는 app.js의 규칙일 뿐 DB의 규칙이 아니다. (배경역사 #57)
- **Supabase 조직은 둘이며, 각 조직의 소유자 2명을 절대 1명으로 줄이지 말 것** — 2026-09-01 조직을 분리했다. **`radio-policy`(slug `yxsyokhvfwwokbscxivy`, Pro, 회사 카드·SKT 사업자 등록)** 에 **radio-policy-ai** 프로젝트가 있고, **`youjinwoong's`(slug `vufjijnnmzgkijptbrgv`, Free)** 에는 개인 프로젝트 wine-cellar-mgmt만 남았다. **두 조직 모두 소유자가 2명**이다: `lampman@sktelecom.com`(이메일+비밀번호 로그인)과 `you.jinwoong@gmail.com`(GitHub OAuth 로그인). GitHub 계정이 정지되면 OAuth가 막혀 Supabase 대시보드까지 함께 잠긴다(2026-08-12~24 실제 3주 잠금, 티켓 SU-444210). Supabase는 **계정에 이메일 로그인을 추가하는 기능이 아직 없고**(SU-454072 회신: "in the pipeline, no ETA"), 공식 권고가 바로 이 **소유자 이중화**다. ⚠️ 두 소유자의 이메일은 서로 **다른 계열**이어야 한다(같으면 함께 잠긴다). 역할은 반드시 **Owner** — Administrator는 조직 설정·소유자 관리가 막혀 비상시 무용지물. 회사 메일 계정의 비밀번호를 분실하면 안전망이 사라지므로 별도 보관할 것. **조직 이전 직후 새 조직의 소유자가 1명뿐인 구간이 실제로 생기므로, 이전과 백업 소유자 초대는 같은 날 반드시 함께 끝낼 것.** (2026-08-26 최초, 2026-09-01 조직 분리 반영 — 배경역사 #114)
- **[GitHub 계정 복구 시 체크리스트 — 순서대로]** 복구되면 **워크플로 6개의 cron이 자동으로 되살아난다**(daily_crawl 매시:17, morning_briefing 06:00, assembly_crawl 10:00, law_crawl 11:00, health_watchdog 21:30, itu_watch 월1회). 지금 같은 일을 PC 임시작업 `radio_TEMP_*` 5개가 하고 있어 **방치하면 전부 2배로 돈다**. 브리핑은 `already_sent_today()`가 중복 발송을 막지만 **뉴스 수집은 Haiku 선별 비용이 그대로 2배**가 된다(데이터는 dedupe되어 무해, 돈만 샘). 그래서:
  ① **수집 주체를 하나로 정한다** — VM(과제 #38)이 이미 돌고 있으면 GitHub Actions 워크플로를 비활성화(Actions 탭에서 disable), 아직 PC로 돌리고 있으면 **PC의 `radio_TEMP_*` 5개를 비활성화**하고 GitHub Actions에 넘긴다. **둘 다 켜두지 말 것.**
  ② `temp_gh_law.bat`의 promote·watch 2줄 삭제(아래 항목).
  ③ **pg_cron 디스패치 잡 4개는 재개하지 않는다**(#94에서 중지) — Actions cron이 이미 주 트리거이므로 재개하면 3중 실행이 된다. GitHub Actions는 `workflow_dispatch` 수동 백업으로만 남긴다.
  ④ 대시보드는 **GitLab(radio-policy.gitlab.io) 유지** — GitHub으로 되돌리면 주소 치환 31곳을 다시 해야 한다. GitHub Pages는 꺼두거나 방치(알림 링크가 전부 GitLab을 가리키므로 무해).
  ⑤ `git push origin main`으로 GitHub도 미러로 되살린다(2중 백업). GitLab remote는 그대로 유지.
  ⑥ origin remote URL에 PAT이 평문으로 박혀 있으니 이 참에 토큰 재발급·URL 정리.
  ⑦ **Supabase 대시보드 로그인이 자동 복구된다** — GitHub OAuth 전용 계정이라 정지와 함께 잠겼던 것(티켓 SU-444210). 로그인이 돌아오면 보류 중이던 계정 분리(개인→회사 조직 이관)를 재개할 수 있다. (2026-08-20)
- **[계정 복구 시 되돌릴 것] temp_gh_law.bat의 promote·watch 2줄 제거** — GitHub 정지 동안 `law_sync.py --promote`·`law_watch.py`가 안 돌아 시행 도래분(예: 8/11 국가재정법·8/20 방발법)이 승격 안 되고 자문이 옛 조문을 현행이라 답하는 무음 위험 → 임시로 PC 배치(temp_gh_law.bat)에 두 줄 추가(2026-08-02). **계정 복구 후 GitHub Actions(law_crawl.yml)가 되살아나면 이 두 줄을 삭제**해야 중복 실행이 안 생긴다(과제 #10). 멱등이라 피해는 작으나 로그 오염. (배경역사 #55 계열)
- **자문 프롬프트의 시제 가드·현지어 검색 지시를 지우지 말 것** — 모델은 오늘 날짜를 알면서도 **학습 시점 기준의 '예정'을 자동 보정하지 않는다**. 일본 도코모 3G 종료(2026-03-31, 이미 5개월 전)를 8월 답변에서 "종료 예정"이라 쓰고 KDDI(2022)·소프트뱅크(2024) 종료는 누락했다. 또 해외 주제를 한국어·영어로만 검색하면 공식 자료가 아니라 블로그가 걸린다(일본 관련 출처 3건이 전부 취미 블로그·MVNO FAQ·2021년 기사였고, 일본어로 치니 도코모 공식 공지가 즉시 나왔다). `system_prompt.js` [세부 지침]의 두 줄(시제 검증 / 해외 주제 검색)이 그 방어다. **프롬프트는 `system_prompt.js`가 단일 원본이며 대시보드·봇 공통이다 — 수정 후 반드시 `python sync_system_prompt.py` 실행**(안 하면 봇만 옛 프롬프트) **+ `index.html`의 `system_prompt.js?v=` 캐시버스터 갱신**(안 하면 대시보드만 옛 프롬프트). (배경역사 #101)
- **국회 입법예고를 pal HTML 스크래핑으로 전환 금지** — OpenAPI `nknalejkafmvgzmpt`와 레코드 완전 일치 실측(379=379), HTML은 GET 페이징을 조용히 무시(POST+_csrf)라 유지보수 함정. 상세 함정 목록은 "국회 입법예고 추적" 절. (배경역사 #56)
- **열린국회 API 전수 조회는 반드시 페이지 끝까지 읽을 것 — pIndex=1 한 페이지만 읽고 끝내지 말 것** — 100건 넘는 키워드는 101건째부터 조용히 잘린다(오류 없음·heartbeat 정상). 실측 2026-09-04: 과방위 소관 802건 중 DB엔 311건뿐이었다. (배경역사 #121)
- **국회 법안 수집을 법안명 키워드 검색에만 의존하지 말 것** — 이름에 키워드가 없는 과방위 소관 법안(정보통신공사업법·위치정보법·소프트웨어 진흥법 개정안 등)은 구조적으로 못 본다. `fetch_committee_bills()`(COMMITTEE=과학기술정보방송통신위원회 전수 스윕)를 키워드 검색과 병행할 것. (배경역사 #121)
- **국회 법안(계류·상정·소위·위원회 의결 등 어떤 단계든)을 kb_documents 자문 근거 층에 넣지 말 것** — 자문 근거는 확정 법령(법률·시행령·시행규칙·고시, 공포된 시행예정본 포함)만이다. 발의안 과반은 그대로 사라지고, 통과분은 공포 후 `law_pending`·조문 DIFF·"[시행예정 개정본]" 블록이 이어받는다. 법안은 목록·알림·브리핑·자문의 [국회 동향 — 참고용 배경] 각주로만 다룬다. #121의 Bill 109건은 당일 삭제. (배경역사 #122)
- **법안 단계 라벨 규칙을 바꿔 배포할 때는 `assembly_crawler.py --suppress-status-alerts`로 1회 백필부터 — 그리고 이 플래그는 크롤러 알림뿐 아니라 prev_proc_result까지 새 값으로 맞춘다는 점을 잊지 말 것** — 파생 규칙만 바뀌어도 수백 건이 '상태변경'으로 판정된다(실측 442건). 처음 구현은 크롤러 알림만 막아, 06:00 아침 브리핑·구독자 다이제스트의 [처리 변경](updated_at 24h & prev≠now)으로 442건이 그대로 쏟아졌다. 이후 브리핑 섹션은 '소관위 회부' 전이를 싣지 않고 12건 상한 + '외 N건'으로 접는다(`morning_briefing.CHANGED_MAX_LINES`). (배경역사 #122-보론)
- **`load_existing_bills()` 등 전체 행 로드는 1,000행 페이징 유지** — supabase-py 기본 상한을 넘는 순간 기존 법안이 '신규'로 재알림된다(2026-09-04 665건, 아직 한 페이지). (배경역사 #122)
- **법제처 DRF 행정규칙(admrul) 본문 조회에 ID·MST 파라미터를 쓰지 말 것 — `lawService.do?target=admrul&LID=<행정규칙ID>`(LID)만 유효** — ID·MST로 부르면 "일치하는 행정규칙이 없습니다"만 돌아온다. (배경역사 #121)
- **`import_regulatory_kb.py --only`에 넘길 경로 목록 파일을 Windows에서 그대로 만들지 말 것** — 줄마다 CR(`\r`)이 붙어 부분 문자열 비교가 실패해 대상이 거의 안 걸린다(67건 중 1건만 선택된 실측 사고) — `tr -d '\r'`로 CR을 제거하고 넘길 것. (배경역사 #121)
- **`answer_feedback`에 anon 정책을 주지 말 것** — 대시보드는 공개 페이지라 정책을 열면 남의 질문·평점·불만 사유가 그대로 노출된다. 쓰기는 `submit_answer_feedback` RPC(누구나 실행, 조회 불가), 읽기는 `admin_list_answer_feedback`(관리자 비밀번호) 전용. 텔레그램 Edge Function은 service role이라 정책과 무관. (배경역사 #103)
- **`app_config`에 `claude_key` 행을 다시 만들지 말 것 — 브라우저는 더 이상 Anthropic 키를 갖지 않는다** (#104). 그 행은 anon SELECT가 열려 있어 **인터넷 누구나 PostgREST 한 번으로 키를 꺼내 갈 수 있었다**. 모든 AI 호출은 `claudeFetch()` → `claude-proxy` Edge Function을 거치고 키는 Edge Secret에만 있다. 설정 탭의 키 입력란도 되살리지 말 것. (배경역사 #104)
- **`claude-proxy`의 `auth.getUser(token)` 검사를 제거하지 말 것 — `verify_jwt`는 관문이 아니다.** 대시보드 `verify_jwt`를 켜도 **anon 키를 유효한 JWT로 통과**시킨다(실측). 실제 관문은 함수 안의 `getUser()`이며, 이것이 anon 키 호출을 401로 막는다. (배경역사 #104)
- **자문 한도 판별을 `body.stream` 대신 클라이언트 헤더로 바꾸지 말 것** — 헤더는 위조할 수 있어 한도를 우회하는 길이 된다. 스트리밍 여부는 서버가 요청 본문에서 직접 관찰하는 값이고, 스트리밍을 쓰는 것이 정확히 자문·보고서초안(비용 큰 둘)이다. 경량 호출은 한도 없이 백스톱 300회/일만. (배경역사 #104)
- **프록시의 스트리밍 응답을 `new Response(upstream.body)`로 바로 반환하지 말 것** — 런타임이 응답 완료 시점에 함수를 정리해 긴 답변이 중간에 끊긴다(EarlyDrop). `TransformStream` + `EdgeRuntime.waitUntil(upstream.body.pipeTo(writable))`로 붙잡아야 한다. Edge 실행 한도는 유료 400초(자문 실측 45초~2분). (배경역사 #104)
- **한도 카운터를 텔레그램식 read-modify-write로 만들지 말 것** — 대시보드는 탭 여러 개가 동시에 요청한다. `charge_ai_usage`처럼 `insert … on conflict do update … returning`(원자적 증가) + 팀 합산은 `pg_advisory_xact_lock`으로 직렬화할 것. 차감·환불 RPC의 EXECUTE는 **service_role 전용**(클라이언트가 한도를 조작하지 못하게). (배경역사 #104)
- **GoTrue "Confirm email"을 켜지 말 것** — 이 시스템은 메일을 보낼 수 없다(Resend 도메인 미인증). 켜면 가입이 확인 메일 대기로 막다른길이 되고 발송 한도(429)로 실패한다. 현재 `mailer_autoconfirm=true`(확인 없이 즉시 가입). 가입 자체는 열어 두되 **승인 전에는 AI 기능이 잠긴다**(profiles.approved). (배경역사 #104)
- **관리자 비밀번호 체계를 되살리지 말 것 — 관문은 admin 계정 하나다** (#104 5단계 완료, 2026-08-20). 관리 RPC 10종에서 `p_pwd` 인자를 **완전히 제거**했고 관문은 `is_admin()`뿐이다. 비밀번호 해시는 DB·프런트 어디에도 없다. 설정 화면 잠금도 `isAdminUser()` 하나로 판단하며, 화면의 해시 비교(`ADMIN_PWD_HASH`)·실패 카운터·잠금 타이머는 삭제했다. 제거 전에 브라우저 외 호출자(파이썬·워크플로·.bat)가 이 RPC들을 쓰지 않음을 확인했다 — 새 스크립트에서 필요해지면 service_role로 부르거나 별도 RPC를 만들 것(비밀번호 인자를 되살리지 말 것). (배경역사 #104)
- **가입 신청 텔레그램 알림은 `handle_new_user` 트리거 안에 있다** (2026-08-21). 가입 시 승인대기 프로필 생성 직후 운영자 봇으로 즉시 알림(Vault `telegram_bot_token` + `net.http_post`, 워치독과 동일 패턴). **알림 블록은 예외를 삼킨다** — 텔레그램 장애가 가입 자체를 막으면 안 되기 때문. `timeout_milliseconds:=10000` 유지(기본 5초는 TLS 핸드셰이크만으로 초과해 유실된 실측 있음). (배경역사 #104)
- **승인 가능한 admin 계정이 없는 공백을 만들지 말 것** — 승인은 admin만 할 수 있으므로, admin이 0명이면 아무도 승인받을 수 없다. 계정 체계를 손볼 때는 항상 admin 1명 이상을 먼저 확보할 것. (배경역사 #104)
- **`chat_logs`에 anon SELECT 정책을 되살리지 말 것 — 자문 이력도 운영자 전용이다** (2026-08-20 운영자 지시). 질문·답변 전문이 남는 테이블이라 화면만 가려서는 anon 키로 그대로 읽힌다. 읽기는 `admin_list_chat_logs`/`admin_get_chat_log`(비밀번호) 전용이고, 건수만 필요한 곳은 내용을 반환하지 않는 `chat_logs_month_count()`를 쓴다. **SELECT 정책이 없으므로 대시보드의 insert에 `.select()`(RETURNING)를 붙이면 실패한다** — 👍👎용 id는 `crypto.randomUUID()`로 클라이언트에서 만들어 넣는다. INSERT 정책은 유지(자문 기록이 남아야 함). (배경역사 #103)
- **만족도 👍👎를 의무로 만들지 말 것** — 안 눌러도 답변·쿼터에 영향이 없어야 하고 재촉 문구도 넣지 않는다. 불만족률은 **투표된 건만 분모**로 센다(무투표는 행 자체가 없음). (배경역사 #103)
- **피드백 버튼은 분할 답변의 마지막 조각에만 붙일 것** — `splitByLines`로 1~3개 메시지가 되는데 전 조각에 달면 한 답변에 투표창이 여러 개 생긴다. `sendAnswerWithFeedback()` 사용. `callback_data`는 64바이트 상한이라 질문을 실을 수 없으므로 `fb:<rating>:<log_id>` 형태를 유지할 것. (배경역사 #103)
- **답변을 기록하는 insert에서 `.select('id')`를 빼지 말 것** — 👍👎가 그 id로 평점을 매단다. `handleAsk`는 이 때문에 **기록이 전송보다 앞에 있고**, 실패 경로의 `[자문 실패]` 기록은 `logged` 가드로 이중 기록을 막는다 — 순서를 되돌리면 버튼이 사라지고 가드를 빼면 행이 겹친다. (배경역사 #103)
- **`chat_logs`에 새 경로를 적재할 때 `channel`을 빠뜨리지 말 것** — 경로별 불만족률 비교가 이 컬럼 하나에 달려 있다. 값은 `telegram_ask`/`telegram_law`/`dashboard` 셋뿐이고, /law 두 하위경로는 `category`('텔레그램-법령검색'·'텔레그램-조문조회')로 구분한다. 자문 이력 목록(`openChatHistory`)은 조문 직조회만 제외하므로 새 category를 만들면 노출 여부를 함께 결정할 것. (배경역사 #103)
- **`report_feedback`에 anon INSERT 정책을 열지 말 것 — 공개 대시보드에서는 보고서 기능을 쓰지 않는다** (2026-08-20 운영자 방침: 보고서 초안 제안은 **사내 시스템 전용**, `docs/사내이식_계획.md`). 현재 정책은 SELECT만 있어 프런트 insert(app.js:8419·8456)가 조용히 실패하는 상태이고 행 수도 0인데, 메뉴 자체가 숨김이라 실사용 영향이 없다. 안 쓰는 기능을 위해 공개 페이지에 쓰기 구멍을 내는 쪽이 더 나쁘다. **사내 이식 시 그쪽 인증 체계에서 정식 처리**할 것 — 그때 `.error` 확인(선례 app.js:7920)도 함께 넣어야 같은 조용한 실패가 재발하지 않는다. #48 계열. (배경역사 #103)

- **관계도 주제 엣지를 조문 번호 없이·검증 없이 저장하지 말 것 — AI가 준 `basis`는 원문 대조 후에만 DB에 쓴다** (2026-09-05, #123). `saveLawmapData`의 검증 관문(`lawmapVerifyRelation`)을 우회하는 저장 경로를 만들지 말고, 세션이 시드 엣지를 넣을 때도 설명에 `제N조`를 적고 그 조문이 `document_chunks.article_no`에 있는지 확인한다. "관련 조문"·"(관련)" 같은 자리표시는 금지. 전수 검증에서 356건 중 214건이 틀려 있었고 그 다수가 검증 없이 저장된 ai 엣지였다 — 관계도는 전문가가 보는 화면이라 한 줄의 틀린 조문이 시스템 전체의 신뢰를 깎는다.
- **노드명·문서명 대조를 정규화 없이 LIKE 한 번으로 끝내지 말 것** (2026-09-05, #123) — 가운뎃점 `·`/`ㆍ` 두 표기, 공백, `.pdf` 꼬리, `(소관부처)` 접두가 섞여 있어 그대로 비교하면 있는 문서를 "미보유"로 오판한다(표시광고법 사례, 노드 doc_name `.pdf` 74건). `nrm()`/`lmNormName()`을 거친 뒤 비교하고, 문서 존재 여부로 결론을 내리기 전에 두 표기를 모두 시도한다.
- **Supabase MCP `execute_sql`을 병렬 에이전트 다수가 동시에 두드리게 하지 말 것 — 동시 4개 이하, 조회는 묶어서** (2026-09-05, #123) — 12개 에이전트가 각자 조회하자 rate-limit으로 배치가 중단됐다. 검증·탐색을 병렬로 돌릴 때는 에이전트 수를 줄이거나 한 에이전트가 여러 건을 한 쿼리로 묶어 조회하게 지시한다. MCP는 읽기 전용(UPDATE는 25006)이므로 쓰기는 `sb_client` 스크립트로.

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
※ Vault github_pat(fine-grained PAT, `radio-policy-commit-org`, resource owner = 조직 `radio-policy`, 만료 2027-09-04) 필수권한: Repository — Contents(R/W)·Metadata(자동)·Actions(R/W). 재생성 시 Actions 누락 주의(배경역사 #18), 저장소 소유자와 토큰 소유자가 같아야 함(#116).
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
※ 토글 라벨(국회·법률 동향 등)을 바꾸면 telegram-webhook + admin-daily-report 둘 다 재배포 + setup_subscriber_bot.py 재실행(BOT_DESC).
```

### 과방위 회의록 오프라인(세션) 파이프라인 (`minutes_offline.py`, #120 — Anthropic API 0회)
```
python minutes_offline.py --export-candidates --year 2019 --out DIR   # 소급: 회의 목록+뷰어 블록+키워드 후보 → DIR/2019/{confer_num}.blocks.json·.cand.json
#   → 세션 서브에이전트가 {confer_num}.judged.json(minutes-judged/1) 작성
python minutes_offline.py --verify-exported --in DIR [--year 2017] [--fix]   # 뷰어 오응답(타 위원회 본문) PDF 대조 → _verify.json; --fix = PDF 블록으로 재생성 + .judged.json 삭제(재판정)
python minutes_offline.py --import-judged --in DIR [--year 2019] [--limit N] [--dry-run]   # 섹션+발언 등록(run()과 같은 dedupe). verify 불일치인데 src≠PDF면 거부
python minutes_offline.py --export-resummary --out DIR                 # 재요약: 기존 섹션 → DIR/resum/{year}/{ymd6}_{confer_num}.json (DB 무변경)
#   → 세션이 …judged.json({meeting_summary, meeting_overview}) 작성
python minutes_offline.py --import-resummary --in DIR [--no-refetch] [--force] [--limit N] [--dry-run]   # 섹션 통째 재등록 + SK 칩 소급(정렬 검사 통과분만), _done.json 재개
python backfill_embeddings.py                                          # 재등록 청크 재임베딩(마지막에 1회)
※ 17:00~17:30 실행 금지(gov 체인 충돌). export 병렬 ≤3~4, import는 단일·순차. 큐 적재 없음.
```

---

※ 이 지침은 운영 핵심만 담는다. 각 결정의 상세 배경·과거 사고 경위·날짜·커밋 해시는 `전파정책AI_배경역사.md` 참조.
