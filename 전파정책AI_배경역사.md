# 전파정책 AI — 배경·역사 지식 문서

> 운영 핵심 지침(`전파정책AI_지침_운영핵심.md`)의 각 규칙·설계가 **왜·언제·어떤 사고로** 그렇게 됐는지의 상세 기록.
> 지침의 가드레일(한 줄 이유)과 어긋나지 않게 유지할 것. 지침을 갱신할 때 이 문서도 함께 갱신한다.

---

## 1. GitHub cron 드롭과 Supabase pg_cron 전환 (2026-06-15 ~ 06-17)

**문제**: GitHub Actions 예약(cron)은 best-effort라 부하 시 지연되거나 통째로 누락됨. 특히 UTC 자정 부근(22~00 UTC = 07~09시 KST)이 최악이고, UTC 00~11시 낮 블록이 통째 드롭된 사례도 있음(2026-06-15). 이로 인해 크롤·법령·국회·브리핑이 며칠씩 누락/지연됨.

**대응**: Supabase pg_cron을 **안정적 주 트리거**로 전환하고 GitHub cron은 백업으로만 둠.
- 뉴스 크롤: pg_cron `crawl-trigger-hourly`(jobid 9)가 매시 :47에 24시간 `daily_crawl.yml` dispatch. GitHub cron은 `17 * * * *`(매시 :17) 백업. 둘 다 떠도 크롤러가 deleted_news·중복 스킵으로 중복 저장 안 함.
- 국회·법령: GitHub 정시(UTC 01:00/02:00) 30분 뒤 pg_cron(jobid 10·11)이 KST 10:30/11:30 백업 dispatch. upsert+변경시 알림이라 겹쳐도 중복 없음.
- 공용 함수 `dispatch_github_workflow(p_workflow)`가 Vault `github_pat`으로 pg_net dispatch. PAT은 fine-grained(repo: radio-policy-ai, Actions: Read+Write). 의존 확장: pg_cron, pg_net, supabase_vault.
- ⚠️ PAT 만료/회수 시 모든 트리거가 조용히 멈춤 → Vault `github_pat` 갱신. 잡 조회 `select * from cron.job`, 삭제 `select cron.unschedule('잡이름')`.

**백업 슬롯을 :17에 둔 이유**: 정시(:00)·15분 단위(:15/:30/:45)는 전 세계 cron 혼잡대라 드롭 확률↑. 한산한 :17 유지(2026-06-15).

**분 튜닝 한계**: 분(minute) 튜닝은 단발 누락 확률만 낮출 뿐 블록 단위 드롭은 못 막음 → 미축적 시 "Run workflow" 수동 실행 또는 PC 로컬 보완이 정답.

---

## 2. 모닝 브리핑 트리거 설계 (06:05/06:20 오프셋 이유) (2026-06-15 ~ 06-17)

**cron 이동**: 23~00 UTC(=08~09시 KST)는 GitHub cron 최혼잡 구간이라 드롭 잦음 → 한산한 21 UTC대(=06:00/06:30 KST)로 이동(2026-06-15). 유튜브 요약(04~05시)이 정시에 잘 뜨는 것과 같은 이유.

**왜 06:00이 아니라 06:05에 조건부 트리거하나** (briefing-trigger-0605, jobid 8): 함수 `trigger_briefing_if_missing()`가 오늘자(KST) `daily_briefings` 행이 없으면 `morning_briefing.yml`을 dispatch.
- 06:00 정각에 Supabase와 GitHub cron이 동시에 쏘면 둘 다 행 생성 전이라 GitHub 성공/드롭 구분이 안 되고 중복 run이 돔.
- 06:05 오프셋이면 GitHub 06:00 run이 살아있을 때 그 사이 행이 생겨 Supabase는 건너뜀(중복 run 없음 + "GitHub 정상" 신호). 드롭됐을 때만 Supabase가 발송(~06:07)하고 그게 곧 "GitHub 드롭" 신호가 됨.
- 발송은 사실상 정시(≤06:07). GitHub cron도 그대로 두며 `already_sent_today`가 이중 발송 차단.
- briefing-trigger-0620(jobid 7)은 여전히 없으면 06:20 재시도. 09:40 로컬 백업(RadioPolicy-BriefingBackup)도 유지.
- 08:05 Actions 백업('5 23' 슬롯)은 2026-06-17 제거 — Supabase 06:05가 대체.

---

## 3. 무음 실패 감시 (watchdog) 설계 (2026-06-17)

파이프라인이 **에러 없이 조용히 멈추는 것**(GitHub 드롭·Supabase 다운·PAT 회수·크롤러 크래시)을 잡는 이중 안전망. 정상이면 무음, 이상 시에만 텔레그램(chat 344506450).

- **내부 워치독 `check_news_health()`** (pg_cron jobid 12, KST 21:00): Supabase 안에서 news_feed 최신 입력 확인 → 14시간+ 멈추면 텔레그램. 직접 DB 쿼리라 가볍고 확실.
- **외부 워치독 `health_watchdog.py` + health_watchdog.yml** (KST 21:30 GitHub cron + jobid 13이 21:35 백업 dispatch): GitHub Actions에서 도므로 Supabase와 독립.
  - Supabase REST로 뉴스 신선도·오늘자 브리핑 확인(접속 실패 시 "Supabase 접속 불가").
  - GitHub Actions API로 각 워크플로우의 마지막 성공 실행 확인(heartbeat 대용). 임계: daily_crawl 14h, 나머지 26h.
  - 인증: GitHub Secrets + Actions 자동 GITHUB_TOKEN(actions:read). stdlib만(pip 불필요).
- **상호 보완**: 내부(Supabase)·외부(GitHub) 독립이라 한쪽 인프라가 죽어도 다른 쪽이 감지. 둘 다 죽으면 사각.
- ⚠️ 텔레그램 토큰은 Vault `telegram_bot_token` 한 곳에서 관리(회수·교체 시 Vault만 갱신). 기존 `check_briefing_health`만 아직 토큰 하드코딩 — 추후 Vault 이관 권장.

---

## 4. 뉴스 수집 — 네이버 OpenAPI 전환 (2026-06-16)

**사고**: `crawl_naver_news`의 구 HTML 스크래핑(search.naver.com, ul.list_news li.bx / a.news_tit)이 검색 구조 변경/해외 IP 차단으로 **0건 회귀(에러 없이)** → 며칠간 뉴스 미축적.

**해결**: 공식 검색 OpenAPI(openapi.naver.com/v1/search/news.json, sort=date)로 교체. NAVER_CLIENT_ID/SECRET 필요(.env·GitHub Secrets). 키 미설정·오류 시 빈 결과 → Google RSS 폴백.

**점검 포인트**: 로그 "[네이버 뉴스] N건 수집". N=0이면 키 누락·만료 또는 폴백만 도는 상태(이 사고 패턴). Google RSS만으론 신규가 거의 안 쌓일 수 있음.

---

## 5. 입법예고 수집 방식 전환 (2026-06-16)

**배경**: 기존 lsNm(제명) 키워드 검색은 "법령 제명에 키워드가 그대로 든 경우"만 잡혀, "방송법 시행령 일부개정"(방송미디어통신위) 같은 관련 예고를 통째로 놓쳤고, 마침 제명 일치 건이 없으면 0건이 돼 lsAnc가 장기간 비어 있었음.

**전환**: 진행 중 입법예고 전체 목록을 pageIndex 단위로 끝까지 스캔(빈 페이지 종료, 상한 OPINION_MAX_PAGES=20) 후 `_opinion_match()`로 선별.
- 직제·소속기관·정원·청사는 제명에 있으면 우선 제외(조직 개편).
- 제명 앞 "○○부/처/청/위원회 소관" 접두사 제거 후 키워드 판정 — **소관 부처명 '과학기술정보통신부'의 '정보통신' 글자가 비상대비법 등 무관 법령을 오탐하던 문제 차단**.
- 제명 키워드: 전파·주파수·전기통신·방송통신·무선·전자파·적합성평가·정보통신·이동통신·기간통신·위성·단말장치·기지국·스펙트럼.
- 소관부처 보강: 방송미디어통신위·방송통신위 소관은 키워드 없어도 포함 / 과기정통부는 통신계열 힌트가 제명에 있을 때만.

**요약 자동 생성**: backfill_opinion_summaries()가 상세 페이지(개정이유+주요내용) → Haiku 1~2문장 요약 → law_amendments.summary. law.go.kr DRF는 입법예고 미지원이라 summarize_law_amendments.py가 lsAnc를 건너뜀 → gov_notice_crawler가 요약까지 단독 담당. 대시보드 카드·브리핑 📢 섹션이 이 summary 표시.

**로컬 유지 이유**: 정부 사이트 해외 IP 차단 위험 + 한국 IP 안정성 → 17:00 Windows 스케줄러. PC 꺼지면 그날 미수집(GitHub Actions로 대체 불가).

---

## 6. 본문 수집 (fetch_article_body) 우회 장치 (2026-06-14)

- **rra.go.kr 등 정부 게시판 trafilatura 우선**: 본문이 table 구조라 일반 'article' 셀렉터가 페이지 전체 네비게이션을 오탐하던 문제 회피(include_tables=True).
- **SSL 약점 우회 _http_get**: DH_KEY_TOO_SMALL 발생 시 SECLEVEL=1 어댑터(_WeakDHAdapter)로 **도메인 무관** 자동 재시도. rra.go.kr는 _KNOWN_WEAK_DH 등록 → 처음부터 어댑터+EUC-KR. (rra.go.kr 전용으로 되돌리지 말 것.)
- 별개 원인(우회 대상 아님): 403 Forbidden(investing.com 등 봇 차단), SSLV3_ALERT_HANDSHAKE_FAILURE(kbench.com), CERTIFICATE_VERIFY_FAILED(andongmbc.co.kr) — 미수집은 정상 baseline.
- trafilatura는 로컬 필수 의존성. PC 교체·파이썬 재설치 시 `pip install trafilatura`. crawler.py는 미설치 시 셀렉터 폴백(에러 없이 품질만 저하). GitHub Actions는 본문 수집 스킵하므로 영향 없음.

---

## 7. RAG 인용 정확성 장치 (2026-06-12)

- document_chunks 중복 1,565청크 정리 완료(2026-06-12).
- article_no에 조문 제목 포함("45조의2(준공검사의 면제 등)" 형식) → 조문 성격 즉시 인지.
- system_prompt.js "위임 관계·제도 구분 검증" 규칙 + 핵심 조문 직접 참조(전파법 제24조② 무선국 자기적합확인 — 2026.10.22 시행, 시행령 위임 미반영 주의).
- 2026-06-12 이전 업로드분은 청크 경계가 조문 단위와 어긋날 수 있음(article_no는 정확). 재업로드 시 해소.

---

## 8. AI 자문 스트리밍 전환 (2026-06-15)

**문제**: 웹검색+긴 답변(max_tokens 16384)은 응답이 2분 이상 걸려, 비스트리밍 시 ~120초 idle 구간에 브라우저·사내망 프록시가 연결을 끊어 "Failed to fetch" 발생.

**해결**: callClaude를 stream:true(SSE)로. content_block_delta의 text_delta 누적 + citations_delta 인용 수집. 실측: 동일 질문이 비스트리밍 127초에 끊기던 것이 스트리밍에서 135.7초·7,202자까지 완주.

**"Failed to fetch" 진단**: 대시보드 메시지가 아니라 브라우저 네이티브 fetch 실패. 키 누락이면 "Claude API 키가...", 서버 오류면 "API 오류(HTTP xxx)". 둘 다 아니면 연결 단계 실패 → 사내망 프록시(api.anthropic.com 차단), 확장프로그램, F12 네트워크 확인. 임의 키로 401이면 서버 도달은 정상.

---

## 9. 지식 베이스 파일 업로드·다운로드 (2026-06-15)

- 브라우저 파싱(pdf.js·mammoth·JSZip)으로 PDF(텍스트 기반)·MD·docx·PPTX → document_chunks. 카테고리: 법령·고시=선택값 / ITU-R / 보도자료 / 추가지식.
- **추가 지식 "파일 업로드"는 document_chunks(doc_category='추가지식')로** 감 — 텍스트 폼 저장(custom_knowledge)과 별개 경로. (파일을 custom_knowledge로 보내면 조문 청킹·시맨틱 검색 안 됨.)
- **저장된 목록 병합 표시(loadCustomFileList)**: 업로드 파일이 custom_knowledge에 안 떠 "어떤 파일 올렸는지" 확인 안 되던 문제 해결 → 📎 배지·청크 수·임베딩 배지·삭제 버튼으로 병합.
- **원본 Storage 보관(uploads 버킷)+file_path 기록**: 저장된 목록 클릭 다운로드 근거. createSignedUrl(60초). private 유지(public화 시 경로 아는 누구나 접근). 2026-06-15 이전 업로드분은 원본 없어 다운로드 불가.

---

## 10. Daily Briefing 렌더링 (2026-06-16)

- "오늘" 배지: KST(+9h) 기준. UTC(`new Date().toISOString()`)로 하면 KST 자정~09시에 어제로 오판하던 버그.
- Haiku가 가끔 #/##/** 마크다운을 덧붙임 → parseBriefingContent가 #/## 헤더 기호 제거, **굵게**→<strong>(mdBold).
- 📢 입법예고 블록 스타일링: 📢=헤더, 🔴=굵은 제목, →=보조텍스트, 🔗=클릭 가능한 "원문 보기" 링크(이전엔 생 URL이 클릭 안 됨).
- 긴급 박스는 원문 🔴 기준으로만(이메일과 항상 일치). 🔴는 news_feed 긴급도 단일 기준 — Haiku 자체 판정 금지. 영향도 분석이 긴급도를 덮어쓰던 코드는 2026-06-12 제거(담당자 수정 되돌리던 버그).

---

## 11. 키워드·오탐 관리

- 법령/국회 키워드에서 '혼신' 제거(2026-06-14) — '이혼신고' 부분문자열 오탐. '전파간섭'은 유지.
- 뉴스 그룹핑: 같은 날짜 + 제목 공유 키워드 2개 이상일 때만 묶음('기지국' 단일 흔한 단어로 이질 주제 병합되던 버그 수정, 지명 정규화에 광장 포함).
- 스포츠 기사 오탐: EXCLUDE_KEYWORDS(crawler.py 477줄 부근) + 중요도 피드백으로 관리.

---

## 12. 보안·운영 사고 기록

- **2026-06-12 Voyage 키 유출·재발급**: 공개 repo에 키 하드코딩 → 유출. 이후 모든 키는 .env·GitHub Secrets·Supabase Secrets에만.
- **2026-06-12 f37fd0b 사고**: 여러 세션이 같은 repo에 동시 커밋 → 샌드박스 마운트가 stale하면 다른 세션 작업을 통째로 되돌려 푸시. repo 커밋은 한 번에 한 세션만.
- **Cowork 샌드박스 마운트 절단**: bash 마운트가 stale/절단된 채 보일 수 있음(파일별 제각각 — 예: 2026-06-17 보고서 초안 제안 작업 시 app.js는 stale, index.html은 일부만, 새 파일은 보이는 식). 이때 샌드박스 커밋 금지. 파일은 Edit/Write로 실제 디스크 반영됨(Read로 확인). 변경 함수는 outputs에 떼어 node --check로 문법 검증 후 PC 터미널에서 커밋·푸시.
- law_crawler 엔드포인트: 정식 www.law.go.kr/DRF/lawSearch.do (구 open.law.go.kr/LSO/...는 404).

---

## 13. 대시보드 변경 이력

- 대시보드(홈) 메뉴 제거(2026-06-12) — 기본 화면은 보도자료·뉴스, 사이드바 맨 아래 설정만.
- 아이콘은 Tabler Icons webfont(ti ti-*) — 존재하지 않는 이름은 빈칸 렌더(ti-git-diff 없음 → ti-arrows-diff, 2026-06-14).
- 캐시 버스터(app.js?v=) 갱신 필수. 푸시 직후 `git show HEAD:index.html | findstr "app.js?v="`로 후퇴 여부 검증(다른 세션 stale 커밋이 덮었는지).

---

## 14. 보고서 초안 제안 — 설계 결정 (2026-06-17)

**기능 목적**: 내 기존 보고서의 형식·톤 + 법령·자료(RAG) 내용 근거로 보고서 초안 생성. 내용은 RAG에서, 형식·톤은 내 보고서에서.

**설계 결정**:
- **보고서 전문 통째 보관(청킹 안 함)**: 형식 학습엔 전체 흐름이 필요. 법령 RAG는 청킹, 보고서 양식은 반대. match_report_samples는 전문 임베딩(title+summary 또는 content 앞부분).
- **형식 학습 이중 구조**: ① 유사 샘플 few-shot(match_report_samples 1~2편) + ② 증류 스타일 가이드(report_style_rules). 적은 샘플로 시작, 쌓일수록 정교.
- **생성 모델 sonnet stream:true**: callClaude와 동일 이유(2분+ 응답 idle 끊김 "Failed to fetch" 방지). 비스트리밍 복귀 금지.
- **증류 모델 Haiku**: feedback_rules 증류와 동일 패턴.

**개인화 학습 채널 3종 — 강한 순서**:
1. **말로 지시(가장 강한 신호 — 의도 명시)**: 편집-diff는 사용자가 한 것을 보고 의도를 추측하지만, 말로 하는 지시는 의도를 직접 말해줌. `이번만`(다회 대화식 재생성, priorDraft를 assistant 턴으로 + 지시를 user 턴으로 3턴 대화) / `항상 적용`(report_directives 영구 저장 → callReportDraft가 매 생성 시 시스템 프롬프트에 최우선 주입). 일회성 지시("이번만 영어로")가 영구 규칙이 되는 걸 막으려고 범위(이번만/항상)로 분리.
2. **빨간펜(편집-diff)**: 말로 표현 안 되는 무의식적 습관(어미·문단 길이)을 잡음. saveReportFinal이 draft+final을 report_feedback에 저장 → 증류 시 Haiku가 초안↔최종본 차이를 "반드시 반영"으로 일반화. 채택본은 report_samples로 승격(선택).
3. **👍/👎(약한 신호)**: rating 저장. 👎는 "피하라" 패턴으로 증류.

**자동 재증류 임계(+2)**: report_style_rules의 sample_count·feedback_count로 마지막 증류 시점 추적. 샘플 +2편 또는 피드백 +2건이면 채택·평가 직후 자동 재증류. 매 1건마다 하면 Haiku 비용·시간↑ + 우연한 피드백에 스타일이 휙휙 흔들림 → "바구니 차면 돌리기". 낮추면 빠르지만 흔들림↑, 높이면 안정적이나 수렴 느림. 구조 학습엔 샘플 2편 이상 필요.

**임베딩 PC 의존**: 신규 보고서 등록·채택본 승격 후 PC에서 backfill_report_embeddings.py(NULL만). 그 전엔 유형/최신순 폴백("임베딩 대기"). 스타일 증류·말로 지시·빨간펜은 브라우저에서 즉시 동작(PC 불필요).

**파일 등록 drag&drop**: report-drop-zone(점선 박스). 클릭/드롭 공용 _processReportFile. PDF·docx·pptx·md·txt.

**DB/RLS**: report_samples·report_style_rules·report_feedback·report_directives 모두 RLS 활성 + anon 4종 정책. match_report_samples RPC(anon execute). report_style_rules에 feedback_count 컬럼(자동 재증류 임계 추적).

**보안**: 원문은 Supabase(private)에만. 생성 시 예시·스타일·지시가 Anthropic API로 전송됨(학습엔 미사용이나 전송은 됨). 민감 수치는 마스킹·형식 위주 등록 권장.

**캐시 버스터 이력**: 20260617e(최초 v1) → f(v3 빨간펜 학습) → g(drag&drop) → h(말로 지시 고치기).

---

## 15. Supabase 파이썬 클라이언트 HTTP/2 끊김 사고 — sb_client 도입 (2026-06-20)

**증상**: 2026-06-19 저녁(KST)부터 `daily_crawl.yml`이 ~20초 만에 전 잡 실패. 같은 시기 `morning_briefing.yml`은 초록(성공)이지만 빈 채로 끝나 06-19·20일 모닝 브리핑 미생성. news_feed는 06-19 18:47 KST 이후 미축적. (실패 메일에 찍힌 커밋 de7f14c는 문서만 수정 — 무관한 red herring.)

**원인**: 워크플로가 `pip install supabase`를 **버전 고정 없이** 실행하는데, 최신 `supabase 2.31.0` / `postgrest 2.31.0`이 `httpx[http2]`(h2 패키지)를 끌어와 Supabase REST 통신이 HTTP/2로 협상됨. Supabase 엔드포인트가 HTTP/2 연결을 끊어, 첫 쿼리(`get_existing_urls()`의 `sb.table('news_feed').select('url,title').execute()`)에서 `httpx.RemoteProtocolError: Server disconnected`로 크래시. supabase-py #1064로 보고된 HTTP/2 keepalive 버그(간헐적이라 국회 크롤러는 한 번 통과하기도 함).
- 라이브러리 자동 업그레이드가 방아쇠 → 코드 변경이 없는데 어느 날 갑자기 깨짐.
- `create_client`를 쓰는 모든 스크립트(crawler·morning_briefing·law_crawler·assembly_crawler·gov_notice_crawler·refetch_content·resend_briefing·send_briefing·summarize_assembly_bills·summarize_law_amendments·upload_law_pdf — 11개) 동시 영향.
- 특히 `refetch_content.py`(PC 본문 수집)도 같이 깨져 본문(content)이 안 채워짐 → 브리핑이 "본문 확인 기사 0건"으로 빈 채 종료(브리핑은 24h 내 **본문 있는** 기사만 요약). 즉 19·20일 브리핑 미생성의 직접 원인.

**해결(2026-06-20, 커밋 ca70add)**: 공용 헬퍼 `sb_client.py`의 `make_client(url, key)` 신설. `httpx.HTTPTransport(retries=3, limits=max_keepalive_connections=1)`로 **HTTP/1.1 강제**(http2 미사용)한 `httpx.Client`를 `ClientOptions(httpx_client=...)`로 주입(supabase-py 2.16.0+ 지원). 11개 스크립트의 `create_client(...)`를 `make_client(...)`로 일괄 교체.
- HTTP/2를 **코드에서** 끄므로 라이브러리가 또 올라가도 재발 안 함(버전 핀과 달리 시간이 지나도 안 풀림 = 영구 해법).
- 검증: 새 코드로 crawl #201 성공(41초 풀 실행, `[기존] Supabase 저장 항목 549건` 읽기 정상, `[네이버 뉴스] 107건 수집`), briefing #43 성공(Supabase 호출 정상). 둘 다 RemoteProtocolError 사라짐.

**복구 절차**: 코드 배포 후에도 브리핑 내용이 차려면 본문 있는 기사가 필요 → PC에서 `python refetch_content.py`(한국 IP·trafilatura)로 본문 채운 뒤 morning_briefing 재실행.

**교훈**: pip 무고정의 양날(자동 최신은 편하지만 깜깜이 회귀 위험). 근본은 HTTP/2 비활성(sb_client).

**후속 보강(2026-06-20) — 의존성 버전 고정**: `requirements.txt`에 크롤 #201에서 검증된 버전 세트(61개)를 `==`로 박고, 6개 워크플로(daily_crawl·morning_briefing·law_crawl·assembly_crawl·backfill·cleanup) 모두 `pip install -r requirements.txt`로 통일. 이제 sb_client가 못 막는 "다른 라이브러리의 자동 최신화 회귀"까지 차단. 버전 올릴 땐 하나씩 바꿔 Run으로 검증(Dependabot 권장). 가벼운 워크플로도 전체 lock을 설치하지만(통일·일관성 우선) 무해. sb_client(HTTP/2 한 버그)와 requirements.txt(전체 자동 업데이트)는 상호보완.

---

## 16. 안정성·가시성 보강 3종 (2026-06-20, 커밋 998044c)

HTTP/2 사고에서 직접 겪은 불편(빈 브리핑·주말 오경보·점검 번거로움)을 근본 해결하기 위해 추가.

**① 빈 브리핑 방지 (morning_briefing.py)**: 본문(content) 확인 기사 0건이면 종료하던 것을 **요약(summary) → 제목(title) 순 폴백**(`fetch_items_fallback`)으로 변경. 폴백본은 맨 앞에 `⚠️ (본문 미확보 …` 접두사를 붙이고, `already_sent_today`가 이 접두사를 발견하면 '교체 허용'(False)을 반환 → PC가 나중에 본문을 채우면 **정식 본문본으로 자동 교체**(중복 발송 방지는 유지). 폴백 모드에선 SKT 영향분석(`add_urgent_analyses`) 생략(본문 빈약). 19·20일처럼 PC 꺼져 본문 미수집이어도 빈 브리핑이 안 나옴.
  - ※ 네이버 OpenAPI 기사는 크롤 시 `content=None`이라 PC refetch 전엔 summary도 없을 수 있음 → 그땐 제목 기반 간이 브리핑.

**② 워치독 '크롤러 인지'로 개선 (health_watchdog.py + check_news_health + system_health)**: 둘 다 "뉴스 DB 신선도"만 보고 경고하던 것을, **"크롤러가 실제로 성공했는지"까지 보고** '고장' vs '뉴스 없음(주말 등)'을 구분하도록 변경.
  - `crawler.py`가 매 실행 끝에 `system_health(key='last_crawl_run')` heartbeat를 upsert(신규 0건이어도 기록, 실패해도 무시).
  - 외부(health_watchdog.py): daily_crawl 최근 성공 <14h면 `crawl_running=true` → 뉴스 stale여도 30h 전까진 침묵(30h+면 'NAVER 키·필터 점검' 경고). daily_crawl은 ①에서 판정하므로 ② 루프에서 제외(중복 경고 방지).
  - 내부(check_news_health): heartbeat <3h면 `crawler_ok` → 뉴스 stale 14h라도 침묵, 30h+면 경고. heartbeat 없거나 stale면 14h에서 경고(예전 동작=안전 폴백, 크롤러 미배포/미실행 시).
  - 효과: 토요일 "26시간 멈춤" 같은 주말 오경보 제거, 진짜 고장(크롤러 미실행)일 때만 울림.

**③ 운영 상태 대시보드 (설정 밑 탭, app.js `loadOpsStatus` + index.html `panel-opsstatus`)**: 사이드바 설정 바로 밑 "운영 상태"(`go('opsstatus')`). 크롤러 heartbeat·뉴스 마지막 입력·오늘 브리핑·입법예고·국회 법안·보관 건수를 ✅/⚠️로 표시. "뉴스 마지막 입력"은 `crawler_ok`면 stale여도 ✅(새 뉴스 없음=정상). 경고 받았을 때 1차 점검 화면. 캐시버스터 `app.js?v=20260620a`.

**DB 변경(이미 적용)**: `system_health(key text pk, updated_at timestamptz, note text)` 테이블 + RLS·anon select 정책. `check_news_health()`를 heartbeat 인지 버전으로 교체. (마이그레이션: `create_system_health_table`, `smarter_check_news_health_heartbeat`)

**검증**: 크롤 #210에서 heartbeat 기록 확인(`note=new=0 total=107`), 운영 상태 탭 라이브 렌더링 확인("뉴스 마지막 입력"이 1일+ stale여도 크롤러 정상이라 ✅).

**사이드바 스크롤 수정(커밋 fe59bd8)**: 운영 상태 메뉴 추가로 항목이 늘면서, 화면(창)이 짧을 때 사이드바 하단의 설정·운영 상태가 잘려 보임(`.sidebar`가 flex column인데 `overflow` 미설정이라 넘침이 스크롤 안 됨). → `.sidebar`에 `overflow-y:auto; min-height:0` 추가. 이때 styles.css는 캐시버스터가 없어 `styles.css?v=20260620a` 신설(이후 CSS 수정 시 갱신 필요).

**PC 크롤러 heartbeat 확장(커밋 0e9c9d6, app.js?v=20260620b)**: "입법예고 최근 수집 4일 전 = 정상인가?" 질문에서 출발. 그 표시는 '마지막 새 항목'이지 '크롤러 실행 시각'이 아니라 모호 → 뉴스 크롤러처럼 PC 크롤러에도 heartbeat 추가.
  - `gov_notice_crawler.py` 끝에 `last_gov_notice_run`, `refetch_content.py` 끝(할 일 없음 조기 return 포함)에 `last_refetch_run` upsert(실패 무시).
  - 운영 상태 탭: '입법예고·정부고시 크롤러(heartbeat)'(✅ <25h, 매일 17:00) + '└ 입법예고 최근 새 항목'(마지막 lsAnc) + '본문 수집(refetch heartbeat)' 행으로 분리 → "PC 꺼져 안 돎" vs "새 예고 드물어 없음"을 구분.
  - 참고: lsAnc는 전체 1~2건 수준으로 드묾(전파·통신 입법예고 자체가 드뭄) → '최근 새 항목' 간격이 큰 건 정상. 검증 시 gov_notice 실행에서 신규 입법예고 1건(전기통신사업법 시행령) 수집 + heartbeat 정상 기록 확인.

---

## 17. 무뉴스 날 무음 누락 방지 — 시각무관 1일1회 통지 + placeholder (2026-06-21)

**계기**: 2026-06-21(일) "모닝 브리핑이 생성되지 않았다" 신고. 점검 결과 트리거 체인은 전부 정상이었음 — pg_cron briefing-trigger-0605/0620 succeeded, GitHub이 morning_briefing.yml dispatch를 204로 수락(PAT 유효, 같은 PAT로 도는 크롤 트리거도 당일 정상), 크롤러도 당일 08:47 KST 정상 heartbeat. 그런데도 06-21·06-19 브리핑이 없고 06-20은 17:13 KST에 늦게 생성됨.

**원인(고장 아님 — 진짜 '뉴스 없음')**: news_feed 신규 입력이 2026-06-19 18:47 KST(=09:47 UTC) 이후 끊김(평소 하루 11~94건 → 06-20·21 0건). daily_crawl #224 로그 확인 결과 `[네이버 뉴스] 106건 수집 (실패 키워드 0개)` → **NAVER 키 정상**, 가져온 106건이 전부 기존/15일 초과라 `[필터] 24건 15일 초과 — 제외` → `[신규] 0건`. 즉 금요일 저녁+주말 뉴스 가뭄(크롤러·키 이상 아님).
- morning_briefing.py가 24h 내 기사 0건이면 `fetch_items_fallback`(요약→제목)도 빈 결과 → "[종료] 최근 24시간 내 수집된 기사 자체가 없음"으로 **저장 없이** 종료. #16①의 빈-브리핑 폴백은 "기사는 있는데 본문 없음"만 막을 뿐 **기사 0건**은 못 막음(폴백도 24h 내 기사가 있어야 동작).
- 게다가 옛 코드는 그 생략 통지를 `datetime.now(KST).hour >= 9`일 때만 보냄. 트리거가 06:00~06:30대(hour<9)라 **통지조차 없이 조용히 종료** → "왜 브리핑이 안 왔지?" 무음 누락으로 오인.

**해결(2026-06-21, morning_briefing.py)**: 0건 분기를 `_handle_no_news()`로 교체.
- 시각 무관하게 **'🕊️ 오늘 모닝 브리핑 — 최근 24시간 내 신규 수집 기사 없음(크롤러 정상 작동, 시스템 이상 아님)' 텔레그램 1회** 발송.
- 대시보드 공백 방지용 **placeholder 브리핑**을 daily_briefings에 upsert. 맨 앞에 `🕊️ (신규 뉴스 없음 …` = `_NONEWS_PREFIX` 마커.
- **중복 차단(1일1회)**: 아침에 워크플로가 최대 4회(06:00 GitHub cron · 06:05 pg_cron · 06:20 pg_cron · 06:30 GitHub cron) 실행될 수 있음. pg_cron 2종은 `trigger_briefing_if_missing`이 placeholder를 "오늘 행 있음"으로 보고 dispatch 생략, 06:30 GitHub run은 무조건 돌지만 placeholder(_NONEWS_PREFIX) 감지 시 텔레그램 생략. 결과 **하루 1회만** 통지.
- **정식본 자동 교체**: `already_sent_today`가 `_NONEWS_PREFIX`도 `_FALLBACK_PREFIX`처럼 '교체 허용'(False)으로 처리 → 나중에 기사가 들어오면(예: 06:30 run에서 신규 확인) placeholder가 정식 브리핑으로 대체됨(#16① 폴백과 동일 패턴). 정식본엔 마커가 없으므로 이후 실행은 `already_sent_today`가 True 반환(추가 발송 없음).

**발송 시각**: 정상 흐름에선 ~06:00 KST 1회(그날 처음 성공한 실행에서 발송 + placeholder 저장). GitHub cron 06:00 슬롯이 드롭·지연되면 첫 통지가 06:05→06:20→06:30 순으로 늦춰질 수 있으나 어느 경우든 1회만.

**진단 메모(재발 시)**: 브리핑 미생성인데 트리거·PAT·크롤러 heartbeat가 다 정상이면 news_feed 24h 신규 0건을 의심. ① 대시보드 운영 상태 탭의 `last_crawl_run` heartbeat가 fresh + 신규0이면 고장 아님. ② daily_crawl 최신 Actions 로그 `[네이버 뉴스] N건`으로 'NAVER 키 만료(N=0·미설정·폴백만)' vs '진짜 뉴스 없음'(N>0·실패 키워드 0개) 가름. 06-21 건은 후자였음.

**검증**: 패치 후 `python3 -m py_compile morning_briefing.py` 통과. 당일(06-21) 공백은 수동 placeholder 브리핑으로 메움(이후 코드 배포로 자동화). PC 터미널에서 `git add morning_briefing.py` 커밋·푸시해야 다음 아침부터 적용(GitHub Actions는 main 기준).

---

## 18. PAT 재생성 시 Actions 권한 누락 — workflow_dispatch 403 무음 실패 (2026-06-22)

**계기**: 2026-06-21(일) 16:10 KST GitHub 메일 "[GitHub] Your fine-grained personal access token is about to expire" — Vault `github_pat`에 저장된 fine-grained PAT `radio-policy-commit`(token id 15192949)이 7일 뒤 만료 예고. 이 PAT는 pg_cron의 `dispatch_github_workflow`·`trigger_briefing_if_missing`이 GitHub Actions를 깨우는 유일한 인증 수단이라, 만료되면 모든 주 트리거(뉴스 :47·브리핑 06:05/06:20·국회·법령 백업·워치독)가 조용히 멈춤.

**1차 검증(맞는 토큰 확인)**: Vault `github_pat`이 `github_pat_`로 시작하는 fine-grained PAT(길이 93)임을 확인. 교체 직전까지 디스패치 응답(`net._http_response`)이 전부 204(성공)였고 마지막 :47 트리거(01:47 UTC)도 204 → 예전 토큰은 정상 동작 중. 즉 메일의 토큰 = Vault 토큰.

**교체 절차**: GitHub에서 Regenerate(만료일 없음=no expiration으로 생성됨) → 새 토큰 값을 `vault.update_secret`으로 Vault `github_pat` 교체. 값 일치·길이 93 확인.

**함정(핵심 사고)**: 재생성된 토큰을 Vault에 넣고 `workflow_dispatch` 엔드포인트로 테스트하니 **403 "Resource not accessible by personal access token"**. 원인은 재생성본의 권한이 예전 토큰보다 부족 — 화면에 **Contents(code) Read/Write + Metadata(Required)만 있고 Actions 권한이 누락**됐음. `POST /repos/{owner}/{repo}/actions/workflows/{wf}/dispatches`(= `dispatch_github_workflow`가 쓰는 바로 그 엔드포인트)는 토큰에 **Actions: Read and write**를 요구하기 때문.
- **왜 안 들켰을 뻔했나(무음 실패)**: `dispatch_github_workflow`는 `net.http_post`를 `PERFORM`만 하고 응답을 안 본다. pg_net은 비동기(fire-and-forget)라 GitHub가 403을 줘도 **SQL 문 자체는 성공** → `cron.job_run_details.status='succeeded' / return_message='1 row'`로 찍힘. 즉 운영상태 탭·cron 잡 상태로는 정상처럼 보이는데 실제 워크플로는 하나도 안 돈다. #3 워치독이 'GitHub Actions 마지막 성공 실행'을 보긴 하지만, 며칠 누적돼야 임계(14h/26h)에 걸려 한참 뒤에야 울림.
- **진짜 status 확인법**: `cron.job_run_details`(항상 succeeded)가 아니라 `net._http_response.status_code`를 봐야 함. workflow_dispatch 성공=204, 권한부족=403, 토큰무효=401. 교체 후엔 반드시 이걸로 검증.

**해결(2026-06-22)**: GitHub 토큰 Edit → Repository permissions에 **Actions = Read and write** 추가 → Update(권한만 변경이라 토큰 값 불변 → Vault 재교체 불필요). 재검증 결과 같은 `workflow_dispatch` 호출이 **204(성공)**로 정상화. 이 테스트 호출이 실제 `daily_crawl`을 한 번 트리거함(부작용 없음, 정상 크롤 1회).

**교훈**:
1. **PAT를 재생성/재발급할 때 권한이 그대로 따라오지 않을 수 있다.** 이 PAT의 필수 권한은 **Repository: Contents(Read/Write) + Metadata(Read, 자동) + Actions(Read/Write)** 3종. Actions가 빠지면 git push(commit)는 되지만 workflow_dispatch는 403.
2. **pg_cron "succeeded"는 GitHub가 받았다는 뜻이 아니다**(net.http_post 비동기). 트리거 교체·점검은 `net._http_response.status_code`로 확인.
3. 무해 검증법: `net.http_get`로 `https://api.github.com/repos/youjinwoong/radio-policy-ai`(200+push 확인)은 토큰 유효성만, **workflow_dispatch 204**는 Actions 권한까지 확인 — 후자가 진짜 동작 보증.
4. 이번 재생성본은 만료일 없음 → 7일 만료 경고 재발 없음(보안상 무기한이 부담이면 만료기간 재설정 가능하나 그러면 만료마다 이 절차 반복).

---

## 19. 스케줄러 cp949 이모지 크래시 + gov 작업이 옛 폴더를 가리킴 (2026-06-25, 커밋 fea7855)

**계기**: 운영상태 탭에서 "입법예고·정부고시 크롤러"와 "본문 수집(refetch)" heartbeat가 4일 14시간째(마지막 6/20 14:05) 멈춰 빨갛게 표시. 동시에 06/25 모닝 브리핑이 하루 3통(06:05/07:47/이후), 매번 다른 건수(14→8→7)에 "⚠️ 본문 미확보 간이 브리핑"으로 옴. 뉴스 크롤러(클라우드)·브리핑 생성·09:40 브리핑백업·10:30 국회요약 PC 작업은 정상.

**오진 주의(첫 가설 기각)**: heartbeat 2종이 같은 날 멈춰 처음엔 "PC 꺼짐"으로 추정했으나, 작업 스케줄러 점검 결과 4개 RadioPolicy 작업이 모두 "준비"(사용 설정)·정상 트리거됨(오늘도 실행됨). 즉 PC는 켜져 있고 작업도 매시간/매일 떴다. 멈춘 건 heartbeat뿐 = **작업은 실행되나 스크립트가 끝까지 못 감**. (작업 마지막 실행 결과: refetch=0xC000013A 강제종료, gov=0x1 오류.)

**원인 ① refetch (간이 브리핑의 직접 원인)**: `refetch_log.txt`에 매 실행 `UnicodeEncodeError: 'cp949' codec can't encode character '\U0001f4cb'` — `refetch_content.py` 136행 `print(f"📋 {mode}: {len(todo)}건")`. 스케줄러로 돌면 stdout이 콘솔TTY에 안 붙어 인코딩이 cp949(윈도우 한국어 기본)로 잡히는데, 이모지(📋)는 cp949에 없어 **첫 이모지 print에서 즉시 크래시**. main() 초반에서 죽으니 본문 한 건도 못 가져오고 끝의 `_refetch_heartbeat`도 못 씀 → heartbeat 6/20 고정, news_feed content 계속 NULL → morning_briefing이 본문 폴백(요약→제목)으로 간이 브리핑 발송. 결과코드 0xC000013A=STATUS_CONTROL_C_EXIT(프로세스 강제종료). 진웅님이 수동으로 돌리던 Windows Terminal은 UTF-8이라 정상 동작 → "수동은 되는데 자동은 안 됨"으로 혼동 가중.

**원인 ② 입법예고(gov_notice)**: 스케줄러 작업 "전파정책_정부크롤러"(매일 17:00, 계정 SYSTEM, 로그온 무관 실행)의 동작이 **옛 프로젝트 폴더** `C:\Users\SKTelecom\Desktop\frequence\전파정책전문가\run_gov_crawler.bat`를 가리킴(현재 프로젝트는 `radio-policy-ai`). 그 옛 bat은 (a) 같은 옛 폴더로 cd, (b) `gov_notice_crawler.py` 실행, (c) **현재 존재하지 않는** `gov_playwright_crawler.py`까지 호출. 옛 폴더 스크립트가 낡아(또는 동일 cp949 이모지 문제) 0x1로 끝 → heartbeat 6/20 고정. (이 작업은 SYSTEM·로그온 무관 실행이라 PC 로그인 여부와 무관하게 트리거됨.)

**해결**:
1. `refetch_content.py`·`gov_notice_crawler.py` 상단(임포트 직후)에 `try: sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8") except Exception: pass` 추가 — cp949 콘솔에서도 이모지/한글 print 안전. (gov는 `import sys`도 함께 추가.)
2. `run_gov_crawler.bat`: cd 경로를 `radio-policy-ai`로 교정, 없는 `gov_playwright_crawler.py` 호출 제거, `set PYTHONUTF8=1` 추가.
3. 작업 스케줄러 "전파정책_정부크롤러" → 동작의 프로그램을 `…\radio-policy-ai\run_gov_crawler.bat`, 시작 위치를 `…\radio-policy-ai`로 재지정(작업 스케줄러 GUI 편집. SYSTEM 실행이라 자격증명 재입력 없음).

**검증**: 운영상태 탭에서 본문수집 heartbeat `ok=119 fail=0 skip=9`(이전 ok=0), 입법예고 heartbeat 1분 전으로 갱신 — 둘 다 빨강→초록. 단, `resend_briefing.py`로 재발송하면 여전히 간이본이 오는데 이는 **resend가 daily_briefings 저장본(아침에 만든 간이 텍스트)을 그대로 재전송**하기 때문(재생성 아님). 정식본은 `python morning_briefing.py`로 재생성해야 함 — `already_sent_today()`가 저장본의 `_FALLBACK_PREFIX`(⚠️ 본문 미확보)를 감지하면 '교체 허용'(False)으로 정식본 재생성·발송.

**교훈**:
1. **PC 로컬 실행 파이썬 스크립트는 이모지/유니코드 print 때문에 stdout/stderr UTF-8 강제가 필수.** cp949 콘솔(스케줄러·파이프 리다이렉트)에서 무음 크래시 방지. 제거 금지, 신규 스크립트도 적용.
2. **폴더를 옮기면 Windows 작업 스케줄러 작업의 동작 경로도 같이 갱신해야 함.** 옛 `전파정책전문가` 폴더를 가리키게 두지 말 것.
3. **heartbeat가 멈췄는데 스케줄러 작업이 '준비/실행됨'이면 PC 꺼짐이 아니라 스크립트 크래시/오류.** 1차 점검은 작업의 *마지막 실행 결과*(0x0 정상 / 0xC000013A 강제종료 / 0x1 일반오류)와 스크립트 로그(`refetch_log.txt`·`gov_crawler_log.txt`). #18의 "cron succeeded ≠ 트리거 성공"과 같은 '실행됨 ≠ 완료' 함정 계열.
4. resend는 저장본 재전송, 재생성은 morning_briefing.py — 본문 채워진 뒤 정식본은 후자로.

**재발 (2026-07-29)**: 재난안전법 계열 3건 업로드 중 `upload_law_pdf.py`·`backfill_embeddings.py`에도 같은 가드 누락 발견 — 파이프 실행 시 마지막 ✅ print에서 크래시. upload_law_pdf는 **크래시 지점이 임베딩 백필 호출보다 앞이라 백필이 조용히 생략**되는 실질 피해(작업 자체는 성공으로 보임). 두 스크립트+`backfill_report_embeddings.py`에 가드 보강. 크롤러·브리핑류 등 나머지 미적용 스크립트는 수개월 정상 가동 중이라 미변경(신규·수정 시 적용 원칙 유지).

---

## 21. 타 프로젝트 OKF 법령 번들(regulatory-kb) 적재 — 요약 레이어 신설 (2026-07-03)

**요구**: 다른 프로젝트에서 만든 **OKF(Open Knowledge Format) 법령 번들**(`regulatory-kb/`, 104 concept = 법령/고시/훈령/예규/절차 103 + 용어집 1)을 이 프로젝트로 가져와 자문에 쓰고 싶다. 기존 지식베이스(document_chunks)와 상당수 겹침. 1회 적재, 원본 동기화 불필요.

**핵심 발견(설계 좌우)**: 이 OKF는 **조문 원문이 아니라 법령별 구조화 요약·실무 문서**였다(본문 `# 요약 / # 적용 범위 / # 주요 내용 / # 실무 체크리스트 / # Citations`). 반면 document_chunks는 `제N조` 원문을 조문 단위로 청킹한 것(자문 조문 인용이 여기 의존). 즉 **다루는 법은 겹치나 형태가 다른 상호보완 레이어**다. 그래서 초기 가정 "겹침=교체(조문 청크 대체)"는 폐기 — 조문 원문을 요약으로 갈아끼우면 인용 회귀. 올바른 방향 = **요약 레이어를 원문 레이어 옆에 추가.**

**설계 결정**:
- **별도 스토어 `kb_documents`/`kb_chunks` 신설**(document_chunks 무변경). manifest.json(정본, 104 entries)을 순회해 적재. concept_type·law_type·law_number·enforcement_date·status·body_md를 컬럼 보존. path 유니크(문서 정체 키), dedup_key로 버전 그룹.
- **임베딩 voyage-law-2(법률 특화, 1024)**: document_chunks의 voyage-4-lite와 **분리**. 서로 다른 모델 벡터는 같은 공간 비교가 무의미하므로, kb 질의도 반드시 voyage-law-2로 임베딩해야 함 → `voyage-embed` Edge에 `model` 파라미터 추가(미지정 시 기존 voyage-4-lite로 하위호환). 두 모델 다 1024차원이라 컬럼은 호환되나 **혼용은 금지**.
- **자문 연동은 병행 조회(대체 아님)**: app.js `searchKbSummaries`(시맨틱 voyage-law-2 + trgm 병행) → `buildKbContext`가 `[법령요약]` 컨텍스트 주입. 시스템 프롬프트에 조문 인용은 document_chunks 원문 우선, 요약은 맥락 보강이라 명시.
- **구버전(superseded) 처리**: manifest의 status를 컬럼 보존해 전부 적재하되(이력 유지), 자문 검색 RPC 기본 `only_current=true`로 **현행본만 노출**(구버전은 명시 요청 시). "구버전 인용 금지" 가드레일(#7 계열)과 이력 보존을 동시 충족. 최초 적재분: current 101 / superseded 3(단말장치 기술기준 2022-16호, 시험기관 지정 2025-4호, 전자파적합성 2023-13호).
- **적재 스크립트 `import_regulatory_kb.py`**: 외부 의존성 없이 stdlib(urllib)만 사용, .env·프론트매터 수동 파싱, `insert_kb_chunks` RPC로 청크+임베딩 일괄 삽입(text→vector 캐스팅, batch_update_embeddings와 동일 패턴). PC 스크립트라 stdout UTF-8 강제(#19). 최초 적재 검증: 문서 104, 청크 1241, 임베딩 누락 0, 1024차원.

**앞으로의 "법령 추가"(Ⓑ) `add_law.py`**: 새 법 PDF 1개로 ①조문→document_chunks(기존 upload_law_pdf.py 재사용, voyage-4-lite) ②Haiku가 OKF 요약 초안 작성→regulatory-kb 저장+manifest 갱신→kb_*(voyage-law-2)까지 한 커맨드. dedup·최신본 superseded 처리는 번들의 `MAINTENANCE.md`/manifest `on_readd_rule` 규칙을 따름(동일 law_number 덮어쓰기 / 최신본은 기존 current를 superseded로 내리고 신규 current 추가). Haiku 초안은 사람이 검토·보정 후 확정(MVP).

**교훈**: "겹친다"가 곧 "같은 표현"은 아니다 — 같은 법이라도 요약과 원문은 형태가 달라 대체가 아니라 병행이 맞다. 임베딩은 저장·질의 모델 일치가 절대 원칙(모델 섞으면 검색이 소리 없이 망가짐).

---

## 22. 정부고시 크롤러 7일 무음 중단 — .bat LF 훼손 + Python 3.13 PATH 셰도잉 이중 사고 (2026-06-25 ~ 07-03 발견·복구)

**증상**: 운영 상태 탭에서 `입법예고·정부고시 크롤러 (heartbeat)`가 **7일 18시간 전**(마지막 2026-06-25 17:00 직전)으로 빨간 경고. 작업 스케줄러 "전파정책_정부크롤러"는 매일 17:00 "실행"으로 기록되나 결과 코드 2147943467(0x8007042B=1067, 프로세스 예기치 종료).

**원인 ① — .bat LF+UTF-8 훼손 (6/25~)**: #19 수리 당일(6/25 15:52) `run_gov_crawler.bat`이 **LF 줄바꿈 + UTF-8 한국어 echo 텍스트**로 재작성됨(세션 편집 도구가 LF로 저장). 한국어 로케일 cmd가 이 조합을 오파싱해 `echo [%date% %time%] === 크롤링 시작 ===` 줄이 **`time ===` 명령으로 실행** → "새로운 시간을 입력하십시오:" 대화형 프롬프트에서 무한 대기(로그에 이 프롬프트만 반복) → python은 아예 실행 안 됨 → heartbeat 무음 중단, 이후 스케줄러가 강제 종료(1067). **치명 포인트: git이 탐지 못 함** — `.gitattributes`의 `*.bat eol=crlf` 정규화 때문에 working tree가 LF여도 `git status`는 clean. 탐지는 바이트 검사(비ASCII=0·bareLF=0)로만 가능.

**원인 ② — Python 3.13 설치로 PATH 셰도잉 (6/30~)**: 6/30 09:58 공유 PC에 Python 3.13이 설치되며 PATH 최상단을 차지. 패키지(bs4·supabase·trafilatura 등)는 전부 기존 **3.12에만** 있어, bare `python`을 쓰는 작업이 전부 `ModuleNotFoundError: No module named 'bs4'`로 즉사:
- `RadioPolicy-RefetchContent`(작업 동작에 inline `python`) — 6/30부터 매일 실패(refetch_log.txt에 Traceback 반복, last_refetch_run 6/29에 멈춤).
- `run_briefing_backup.bat`(bare `python`) — 백업 경로 깨짐(pg_cron 주 트리거가 살아 있어 브리핑은 정상 발송 → 무음).
- `RadioPolicy-AssemblySummary`만 **Python312 전체 경로**를 써서 무사 — 이게 정답 패턴.

**복구 (07-03)**:
1. `run_gov_crawler.bat`·`run_briefing_backup.bat`을 **ASCII+CRLF**로 재작성(echo 텍스트 영문화), python을 `C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe` 전체 경로로 고정, `set PYTHONUTF8=1` 유지(#19). 바이트 검증: CRLF=6·bareLF=0·비ASCII=0.
2. 고친 배치 수동 실행으로 7일 밀린 정부고시·입법예고 수집 및 heartbeat 복구, refetch_content.py도 3.12로 수동 1회 실행.
3. `RadioPolicy-RefetchContent`는 작업 **동작 자체에** inline `python`이 박혀 있어 작업 수정 필요(운영자 직접): 동작의 명령을 `"C:\Users\SKTelecom\AppData\Local\Programs\Python\Python312\python.exe" refetch_content.py …`로 교체.

**교훈**: ① .bat을 편집한 세션이 곧 .bat을 깨뜨린 세션 — 편집 후 바이트 검증이 유일한 안전망(git status 무용). ② 공유 PC는 누가 언제 다른 Python을 깔지 모른다 — 스케줄러가 부르는 인터프리터는 반드시 전체 경로로 고정. ③ "스케줄러는 실행됐다"와 "스크립트가 돌았다"는 다르다 — 판정은 heartbeat(system_health)와 각 작업의 LastTaskResult로.

**후속 (2026-07-06) — 주말 전원 공백으로 heartbeat 경고 재발 → StartWhenAvailable 도입**: 7/3(금) 17:00 실행 시각과 주말(7/4~7/5) 내내 PC가 꺼져 있어 정부고시 heartbeat가 다시 "3일 전" 경고. 월요일 부팅(08:59) 시 스케줄러가 누락을 감지했지만(이벤트 153) 당시 StartWhenAvailable=false라 보충 실행 없이 0x800710E0(거부)만 기록. 수동 따라잡기(신규 2건 수집) 후, 운영자가 관리자 PowerShell로 `New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries` + `Set-ScheduledTask`를 적용 → **놓친 17:00 실행이 다음 부팅 직후 자동 보충**되도록 변경(트리거·동작·시작 위치는 무변경, XML 검증 완료). 매일 1회 실행 작업의 구조적 공백(조기 퇴근·연휴)에 대한 항구 대책. RefetchContent는 매시 실행이라 부팅 후 최대 1시간 내 자가 회복되므로 불필요.

---

## 23. 구조 최적화 1차 — AI 자문 검색 병렬화 + news_feed 저장 견고화 (2026-07-03)

**배경**: 전체 구조 최적화 점검(프론트/크롤러/DB·RAG 3영역)을 수행. "결과 불변 효율 개선 → 에러 감소 → 결과 개선" 순서로 항목별 검토·적용.

**적용 ① — AI 자문 검색 병렬화 (커밋 7aa1d44)**: `searchKeywords()`의 키워드별 검색이 for 루프 안 순차 `await`(최대 10회 직렬 DB 왕복)였던 것을 `Promise.all` 동시 조회로 전환. 또 `callClaude()`의 보조 컨텍스트(추가지식·뉴스·법령동향·법령요약 KB)가 조문 RAG까지 릴레이로 순차 실행되던 것을, 함수 시작 시 동시에 출발시키고 결과만 기존 순서로 조립하도록 변경. 병합 순서·중복제거·랭킹·프롬프트 조립 순서는 코드가 고정하므로 **AI에 들어가는 최종 프롬프트는 동일**, 답변 시작 대기만 단축. 각 병렬 호출에 개별 catch를 둬 기존 fail-soft(개별 검색 실패에도 자문 동작) 성질 유지.

**적용 ② — news_feed 저장 견고화**: 실DB의 `idx_news_feed_url_unique`는 **이미 UNIQUE**였으나(중복 0건 확인), 문서 사본 docs/schema.sql이 일반 인덱스로 잘못 기록돼 있어 교정. gov_notice_crawler.py의 저장이 plain `insert` 배치라 **중복 URL 1건에 그 회차 배치 전체가 실패**할 수 있어, crawler.py와 동일한 `upsert(on_conflict='url', ignore_duplicates=True)` 패턴으로 통일.

**적용 ③ — 크롤러 견고화 2종 + cp949 가드 보강**: (1) gov_notice_crawler.py의 `parse_date`를 crawler.py의 다중 형식 해석기로 교체 — 날짜만 있는 기존 입력은 결과 불변(테스트로 확인), 시각 포함·ISO·상대날짜 등 기존에 빈 값이 되던 형식이 추가로 파싱됨. (2) law_crawler.py·assembly_crawler.py API 호출에 3회/5초 재시도 부여 — 하루 1회 잡이라 일시 오류 1회가 하루치 누락으로 직결되던 것을 방지(gov와 동일 정책). (3) 검증 중 law_crawler.py가 cp949 콘솔에서 `—`(em dash) print로 즉사하는 것을 발견 — #19 가드(`sys.stdout.reconfigure(encoding="utf-8")`)가 law·assembly에는 없었음(평소 GitHub Actions에서만 돌아 잠복). 두 파일에 가드 추가. 세 크롤러 수동 실행으로 정상 완주 확인.

**적용 ④ — 무음 실패 가시화 (app.js)**: 오류를 흔적 없이 삼키던 빈 `catch(e){}` 7곳(chat_logs 저장·deleted_news 기록·읽음표시·custom_knowledge 조회·Storage 정리·스타일 재증류)에 `console.warn` 추가 — 화면 동작 불변, F12 콘솔에만 흔적.

**적용 ⑤ — 하이브리드 검색 점수 정규화 (③단계, 결과가 바뀌는 변경)**: 기존 채점은 키워드 매칭(무제한 누적, 20점+) + trgm×5 + 시맨틱×10으로 척도가 어긋나 흔한 단어 물량이 의미 유사도를 압도할 수 있었음. 키워드 점수를 결과 내 최대값으로 0~1 정규화하고, trgm·시맨틱(원래 0~1 절대 척도)은 그대로 두되 시맨틱에 2배 가중으로 변경. **상위 12개 청크 구성이 실제로 달라질 수 있는 변경** — 운영자 체감 비교로 검증하고, 회귀 시 해당 커밋 revert 1번으로 원복.

**적용 ⑥ — 승인 시 임베딩 자동 생성 + 키워드 검색 승인 필터 구멍 수리**: 업로드 문서 승인 게이트(is_approved, admin_set_kb_approval RPC, 설정 탭 승인 UI)는 이미 구현돼 있었으나 두 가지가 빠져 있었음. (1) **키워드(ilike) 검색이 승인 필터 없이 document_chunks를 조회** — trgm·시맨틱 RPC는 `where is_approved`로 거르는데 키워드 경로만 승인 전 문서를 AI 자문에 노출하는 구멍 → `.eq('is_approved', true)` 추가로 봉합. (2) 승인해도 임베딩은 PC 백필 전까지 비어 시맨틱 검색 제외 → 승인 버튼 클릭 시 브라우저가 voyage-embed(문서 모드, voyage-4-lite)로 임베딩을 만들어 신규 RPC `admin_update_chunk_embeddings`(승인 RPC와 동일한 SHA-256 비밀번호 검증, anon 직접 UPDATE는 여전히 차단)로 저장. 실패 시 승인은 유지되고 "임베딩 대기"로 남아 기존 PC 백필로 보완 가능(fail-soft).

**검토 후 기각한 항목 (이유 기록 — 재제안 방지)**:
- **crawler.py Haiku 프롬프트 캐싱**: Haiku 4.5 캐시 최소 프리픽스 4,096토큰인데 분류 프롬프트는 ~2,000자로 미달 → cache_control 붙여도 조용히 무시(절감 0). 게다가 시스템 프롬프트가 기사 제목별 유사 피드백 사례를 포함해 기사마다 달라 캐시 부적합. 대시보드(app.js) 고정 프롬프트 ~10KB는 조건 충족 — 원하면 그쪽만 적용 가능(단발 질문 위주면 캐시쓰기 +25% 할증으로 미세 손해, 연속 질문 위주면 이득).
- **Haiku 분류 배치화**: 기사별 맞춤 피드백 사례(get_feedback_examples)가 핵심 개인화 기능이라 배치 시 포기/재설계 필요 → 분류 품질 리스크 대비 절감액(월 2~3만원)이 작아 기각.
- **보고서 임베딩 배치화**: 회당 1~2건 처리라 실익 없음.
- **크롤러 공통 유틸 통합**: parse_date·detect_category·get_existing_urls가 crawler.py와 gov_notice_crawler.py에서 이름만 같고 **로직이 분화**(뉴스 쪽이 상위 호환: 시각 파싱·AI 키워드·deleted_news 반영). 위치만 옮기면 두 벌씩 담겨 단순화 효과 없고, 한 벌로 통일하면 동작 변경 → "상위 호환 버전으로 통일(날짜 파싱 실패 감소 등)"로 별도 검토 과제로 이월.

---

## 24. 국회 법안 의안 링크 전건 공백 — API LINK_URL 미반환 발견, billId URL 구성으로 교정 (2026-07-21)

**증상**: 대시보드 국회 법안 탭에서 법안을 클릭해도 의안정보시스템으로 이동하지 않음. 운영자 신고.

**원인**: `assembly_crawler.py`는 열린국회정보 API(nzmimeepazxkubdpn) 응답의 `LINK_URL` 필드를 그대로 `assembly_bills.link_url`에 저장하는데, **이 API는 LINK_URL을 실제로 반환하지 않음** — DB 확인 결과 222건 전부 link_url 공백. 대시보드 `renderAssemblyBills()`는 link_url이 있을 때만 "의안보기" 앵커를 그리므로 링크가 아예 렌더되지 않았고, 카드 자체도 클릭 불가 영역이었음. 크롤러 최초 작성 시 API 명세의 필드명만 믿고 실데이터 검증을 안 한 것이 근인 (실DB 검증 원칙의 재확인 사례).

**교정 (3단)**:
1. **크롤러**: `bill_link()` 헬퍼 신설 — `LINK_URL` → `DETAIL_LINK` → `https://likms.assembly.go.kr/bill/billDetail.do?billId=<BILL_ID>` 순 폴백. upsert·텔레그램 신규/상태변경 알림 3곳 모두 이 헬퍼 사용 (알림의 "의안 바로가기"도 같은 이유로 그동안 누락되고 있었음).
2. **DB 백필**: 기존 222건 `UPDATE ... SET link_url = 'https://likms.assembly.go.kr/bill/billDetail.do?billId=' || bill_id WHERE link_url IS NULL OR link_url = ''`.
3. **대시보드**: 카드 전체를 클릭 가능(`cursor:pointer` + `window.open(..., '_blank', 'noopener')`)하게 하고, link_url이 비어도 bill_id로 같은 URL을 프론트에서도 구성(이중 안전망). 하단 "의안보기" 앵커는 유지하되 `event.stopPropagation()`으로 카드 클릭과 중복 열림 방지. 캐시버스터 20260721a.

**검증**: billId 조합 URL(`billDetail.do?billId=PRC_C2B6...`)이 해당 법안(2220039 전기통신사업법 일부개정법률안) 상세 페이지를 정확히 여는 것을 브라우저로 사전 확인 후 적용. billId는 의안 고유 식별자(PRC_...)라 전 건 동일 패턴 적용 가능.

**교훈**: 외부 API 필드는 명세가 아니라 **실제 응답/실DB 값으로 검증**해야 함. "필드를 읽어서 저장한다"는 코드가 있어도 값이 항상 비어 있으면 기능은 처음부터 죽어 있던 것 — 이런 유형은 에러가 안 나므로 화면에서 실제 클릭해보기 전에는 발견되지 않음.

---

## 25. 입법예고 주요내용 요약 무음 생략 — SYSTEM 계정 + pip --user 설치 충돌, 개정이유 띄어쓰기 미대응 (2026-07-21)

**증상**: 행정부 입법예고·법령 개정 탭에서 6월 수집분은 주요 내용(AI 요약)이 보이는데 7월 수집분(7/9 이후 6건)은 전부 비어 있음. 운영자 신고.

**원인 2중**:
1. **SYSTEM 계정 + pip --user 설치 충돌**: 정부크롤러 예약작업(전파정책_정부크롤러)은 SYSTEM 계정으로 실행되는데, `anthropic` 패키지만 `pip install --user`로 사용자 프로필(`AppData\Roaming\Python\Python312\site-packages`)에 설치돼 있었음. SYSTEM의 사용자 site는 systemprofile이라 import 실패 → `anthropic = None` → 요약 단계 통째 생략. supabase·bs4 등 나머지는 전역 site-packages에 있어 **수집은 정상 동작**했기 때문에 요약만 조용히 빠짐. 게다가 생략 메시지가 "ANTHROPIC_API_KEY 미설정"으로 뭉뚱그려져 있어(.env에 키는 멀쩡히 있음) 로그만 봐서는 오진 유도. 로그 확인 결과 예약 실행에서 요약이 성공한 적은 한 번도 없었고, 6월분 요약은 구축 당시 세션에서 수동으로 채워진 것.
2. **개정이유 띄어쓰기 미대응**: 전역 설치 후 백필을 돌리자 6건 중 5건이 "내용없음"('') 처리. 과기정통부 최근 공고문이 "1. 개정 이유"처럼 **띄어 쓰는데** 추출 정규식은 붙여 쓴 `개정이유`만 찾았음. ''는 재시도 방지 표식이라 그대로 두면 영구 누락.

**교정**:
1. `python.exe -s -m pip install anthropic==0.104.1`로 전역 site-packages에 설치(-s 없이는 pip이 사용자 site의 기존 설치를 보고 건너뜀). 검증도 `-s`(사용자 site 차단 = SYSTEM 상황 시뮬레이션)로 import 확인.
2. gov_notice_crawler.py 생략 메시지를 "anthropic 모듈 import 실패"와 "API_KEY 미설정" 두 경우로 분리 — 같은 오진 재발 방지.
3. 추출 정규식을 `(?:제\s*·?\s*)?(?:개\s*정|제\s*정)\s*이\s*유`로 공백 허용, 종료 마커에 '의견 제출' 추가. ''로 잠긴 5건을 NULL로 되돌려 재백필 → 6건 전부 요약 생성 확인.

**다른 예약작업 점검**: AssemblySummary·BriefingBackup·RefetchContent는 사용자 계정(Interactive)으로 실행되어 --user 패키지가 보임 — 영향 없음. SYSTEM으로 도는 것은 정부크롤러뿐.

**교훈**: 예약작업의 **실행 계정**이 패키지 가시성을 가른다(SYSTEM ↔ 사용자 site). "키 미설정" 류의 뭉뚱그린 생략 메시지는 원인 분기별로 쪼개 놓아야 로그가 진단 가치를 가짐. 재시도 방지용 '' 저장은 편하지만, 추출 로직 버그와 결합하면 영구 누락 장치가 된다.

---

## 26. 기술용어 상세 일괄 백필 스크립트 신설 (2026-07-21)

**배경**: 기술 용어 탭의 상세(설명·개념도 SVG·관련용어)는 모달을 열 때 브라우저에서 개별 생성(app.js `generateTermDetail`, claude-sonnet-4-6)되는 구조라, 자동 추출된 신규 용어는 누군가 클릭하기 전까지 비어 있고 클릭하면 "생성 중..." 로딩을 기다려야 했음. 운영자 요청("상세내역 일괄 업데이트")으로 197개 중 빈 항목 12건을 확인.

**조치**: `backfill_term_details.py` 신설 — 대시보드와 **동일한 프롬프트·동일한 모델(claude-sonnet-4-6)·동일한 XML 태그 파싱**으로 빈 필드만 일괄 생성. 이미 채워진 필드(운영자 검수분 포함)는 절대 덮어쓰지 않음(멱등). 실행 결과 197건 전부 상세 완성. 1회 응답 형식 오류(태그 누락)는 재실행으로 해소 — 실패 시 NULL 유지라 재실행이 곧 재시도.

**메모**: 모델을 바꿀 때는 app.js `generateTermDetail`과 이 스크립트를 함께 바꿔야 생성물 품질·형식이 일치함. 신규 용어는 계속 자동 추출되므로, 용어 탭에서 로딩이 자주 보이면 이 스크립트를 한 번 돌리면 됨(PC, .env의 ANTHROPIC_API_KEY 사용).

---

## 27. 대시보드 상위 모델 Sonnet 4.6 → Sonnet 5 전면 교체 (2026-07-21)

**배경**: 운영자가 AI 자문 효용 향상을 목적으로 상위 모델 업그레이드 옵션 검토를 요청. Sonnet 5(코딩·분석에서 이전 Opus급, 지시 이행 정밀), Opus 4.8(단가 1.67배), Fable 5(단가 3.33배, 응답 수 분·거부 처리 필요) 중 **Sonnet 5 전면 교체**로 운영자가 결정. 단가는 4.6과 동일($3/$15, 2026-08-31까지 프로모션 $2/$10)이나 새 토크나이저로 같은 텍스트가 약 +30% 토큰 → 실효 비용 약 1.3배(월 +$1 안팎).

**변경 내용**:
1. app.js 6곳 `claude-sonnet-4-6` → `claude-sonnet-5`: AI 자문(1118)·보고서 초안(5168)·법령 DIFF(2747)·용어 상세(685)·용어 수동추출(473)·연결테스트(3443).
2. **max_tokens 상향** — 토크나이저 +30% + 적응형 추론(기본 켜짐)이 출력 예산을 같이 쓰므로, 기존 값이면 답변이 잘릴 수 있음: 자문·보고서 16384→24000(스트리밍), 용어 4000→6000, DIFF 2500→4000, 추출 1000→1500. ping(10)은 유지.
3. backfill_term_details.py 동기화(모델·max_tokens) — 대시보드 클릭 생성과 형식·품질 일치 유지.
4. Haiku 경로(뉴스 분류·요약·영향도·브리핑·법안 요약 등)는 전부 유지 — 호출량 최다 구간이라 비용 구조의 핵심이고 상위 모델 이득이 적음.

**Sonnet 5 특성 메모** (프롬프트 재점검 관점):
- 지시를 더 문자 그대로 따름 — system_prompt.js는 조건-행동 규칙 위주라 궁합이 좋고, 태그·기한 표시 누락은 오히려 감소 기대. 단, 4.6 기준으로 튜닝된 문구가 과하게 적용될 수 있어 교체 후 실사용 질문 2~3개로 톤·태그·구조 확인 권장.
- 적응형 추론이 기본 켜짐 → 첫 토큰까지 지연이 다소 늘 수 있음(스트리밍 UI에는 빈 구간으로 보임).
- `temperature` 등 샘플링 파라미터를 넣으면 400 — 현 코드는 안 쓰므로 무관하나, 추가 금지.
- 모델 ID `claude-sonnet-5`는 계정에서 유효함을 `/v1/models` 조회(무과금)로 확인 후 배포.

**롤백**: 결과물이 마음에 안 들면 모델 문자열만 4.6으로 되돌리면 됨(max_tokens는 상향분 유지해도 무해).

---

## 28. 법령 관계도(lawmap) 메뉴 신설 — 주제↔법령 네트워크 그래프 (2026-07-23)

**배경**: 운영자가 "무선국 비용 → 전파법·시행령·**지방세법**(면허세)", "3G 종료 → 전기통신사업법(폐지)·전파법(주파수 반납)"처럼 하나의 업무 주제가 여러 계열 법령에 걸치는 관계를 네트워크 그래프로 보고 싶다고 요청(참고 이미지 제시). 설계 논의에서 운영자가 요구를 단계적으로 확장: ① 주제 시드만 → ② 보유 법령 조문 인용망 자동 추출 병행 + 즉석 AI 생성 → ③ "질문하면 관계도가 나오는" 구조 → ④ AI 자문을 쓸 때마다 관계도가 자동 갱신 → ⑤ 자문 답변에도 미니 관계도 표시 → ⑥ 버블 클릭 시 법령 주요 내용 표시. 시뮬레이션 목업 2회 확인 후 승인.

**핵심 설계 결정**:
1. **"질문 시 생성"이 아니라 "사전 구축 관계망에서 잘라 보여주기"** — 비용(재질문 무료)·일관성(같은 질문=같은 그림)·검수 가능성(DB 행 수정) 때문. AI 즉석 생성은 관계망에 없는 주제일 때의 폴백이며 결과는 저장되어 재사용.
2. **성장 경로 4개 병행**: 자문 자동 축적(<lawmap> 블록, 주 경로·추가 호출 0회) / 탭 즉석 생성(1회 과금 후 캐시) / 주제별 "AI로 보강"(증분 병합) / 인용망 스크립트 재실행. "한 번 생성=확정 아님"이 운영자의 명시 요구였음.
3. **엣지·노드에 source 컬럼**(seed/citation/family/ai)을 둬서 인용망 재구축이 시드·AI 축적분을 건드리지 않게 함. 재구축은 엣지만 삭제(노드 삭제는 FK cascade로 다른 출처 엣지까지 소실되므로 금지).
4. lawmap 지시문은 system_prompt.js가 아니라 **app.js callClaude의 lawmapGuide**로 주입(webSearchGuide와 같은 패턴) — 한 줄짜리 거대 문자열 파일을 안 건드리고 기존 주제명 목록(주제 분열 방지)을 호출 시점에 동적으로 넣기 위함.
5. 지방세법 관련: 운영자 지적으로 확인 결과 **지방세법(860청크)·지방세법 시행령(1,072청크) 원문이 이미 document_chunks에 있음** — "원문 미보유 법령" 가정은 오류였고, 인용망 추출 대상에 포함되어 등록면허세 관계가 원문 근거로 연결됨.

**구현 내역** (2026-07-23):
- DB: law_graph_nodes(name UNIQUE, node_type, source, doc_name) / law_graph_edges(unique(source,target,relation_type), weight, source). RLS: anon select/insert/update, delete는 service 전용. 마이그레이션 `create_law_graph_tables`.
- `build_law_citation_graph.py`: 법령·고시 원문 105문서(8,229청크)에서 「법령명」(제N조) 인용 + "법 제N조"/"영 제N조" 자기계열 참조 파싱 → 노드 988·인용 엣지 1,565·계열 엣지 12. 가운뎃점 이형(ㆍ·‧) 정규화, 부칙 상용구('훈령·예규 등의 발령 및 관리에 관한 규정') 블록리스트, 엣지 0개 citation 고아 노드만 정리.
- 시드: 주제 30개(운영자가 12개 초안에 18개 추가 요청)·근거 엣지 102개. 세션에서 노드명 실DB 검증 후 SQL 투입.
- app.js: lawmap 탭(go 연결·vis-network 9.1.9 CDN 지연 로드·전체/주제 뷰·질문 로컬매칭→AI 생성·AI 보강·상세 카드[OKF 요약 지연 조회+원문 모달+자문 프리필]) + callClaude lawmapGuide·<lawmap> 파싱(스트리밍 중 노출 차단·미완성 블록 제거) + sendChat 미니 SVG·저장. index.html 패널·모바일 서브메뉴·원문 모달, styles.css lawmap 스타일.

**개발 중 잡은 함정 3건** (do-not 등재):
1. **PostgREST 1000행 절단**: `.limit(2000)`을 줘도 서버 max-rows=1000에서 잘림 — 파이썬 스크립트가 문서 5건만 인식(첫 실행), 대시보드가 주제 30개 중 12개만 로드. 양쪽 다 range 페이지네이션으로 수정.
2. **허브 폭발**: 주제 포커스를 "2촌 이웃 전부"로 잡으면 전파법(피인용 수백)을 거쳐 628노드로 폭발 — 직접 이웃+하위법령(계열) 1단계 확장으로 축소(무선국 비용=7노드). 전체 뷰는 노드 300 이하까지 인용 임계 자동 상향(2→12).
3. **로컬 매칭 오탐**: '기지' 같은 2글자 부분일치로 무관한 질문도 매칭됨 — 매칭 시에도 "찾던 주제가 아니면 AI로 새로 생성" 버튼을 병기해 탈출구 제공.

**검증**: 로컬 브라우저에서 그래프 렌더(전체 236노드/주제 포커스 7노드)·상세 카드 OKF 요약·원문 모달(전파법 조문)·anon 키 저장 경로(RLS)·<lawmap> 파싱/제거/미완성 블록 회귀 테스트 통과. 테스트 주제는 삭제.

**배포 직후 운영자 피드백 — 상세 카드 주제 맥락 인식형으로 개편** (2026-07-23, 2차 커밋): "3G 종료에서 전기통신사업법을 클릭하면 관련 내용만 보여야 하는데 법 전체(요약)가 보인다." 수정: ① 🎯 "주제에서의 역할"(주제↔법령 엣지 설명)을 최상단 강조 ② 📌 근거 조문 원문 발췌 신설 — 엣지 설명의 "제N조"를 document_chunks에서 찾아 해당 조문만 표시 ③ 연결 관계 목록을 현재 그래프(포커스 서브그래프) 범위로 한정(이전엔 그 법령의 전체 인용 관계까지 노출) ④ 법령 전체 요약(OKF)은 기본 접힘. **함정**: document_chunks의 article_no가 문서마다 '제19조(...)'와 '19조(...)'(제 없음) 두 형태로 저장돼 있어 '제N조'만 매칭하면 빈 결과 — 양쪽 or 매칭 + '제19조의2' 혼입 방지 필터 필요.

**운영자 피드백 2 — 전체 인용망 클릭은 드릴다운으로** (2026-07-23, 3차 커밋): 전체 인용망 모드에서는 반대로 "노드를 클릭하면 그 법령의 실제 관계와 전체 요약이 보여야 한다"는 요청. 수정: 전체망에서 법령 클릭 → 그 법령 중심 서브그래프(약한 엣지 포함, 허브는 강한 순 80개 제한)로 전환 + OKF 전체 요약 펼침 + "← 전체 인용망으로" 복귀 링크 / 주제 노드 클릭 → 주제 포커스로 전환. 결과적으로 요약 접힘/펼침이 모드별로 반대가 되는 것이 의도된 동작: **주제 맥락에서는 역할·근거 조문만(요약 접힘), 전체망 탐색에서는 법령 자체가 관심사이므로 요약 펼침.**

---

## 29. 대시보드 승인 훅 OKF 자동 생성 + 번들 역동기화 (2026-07-29)

**배경**: 재난로밍 정책 조사 중 "재난 및 안전관리 기본법"이 관계도에 이름만 있고 원문·요약이 없음을 발견 → 웹 업로드 경로의 한계 논의로 이어짐. 웹 업로드는 청킹 + (배경 #23의) 승인 시 임베딩까지는 자동이지만 **OKF 요약(kb_documents) 생성은 PC add_law.py에서만 가능**했다. 운영자가 "①(웹 업로드)도 PC와 같게 할 수 없나" 요청 → 선택지 검토(A: 웹에서 OKF까지+주기 역동기화 / B: Edge Function이 GitHub API로 번들 커밋까지 / C: 현행 유지) 후 **A안 채택**. B안 기각 사유: add_law.py의 dedup·supersede 로직을 JS로 이중 유지보수 + 실패 지점 증가 대비, 법령 추가 빈도(월 수 건)가 낮음.

**구현** (커밋 참조):
1. **admin RPC 2종 신설**(migration `admin_kb_okf_rpcs`): `admin_upsert_kb_document`(동일 path 덮어쓰기 + 같은 dedup_key의 기존 current를 superseded 처리 — add_law.py on_readd_rule의 SQL판), `admin_insert_kb_chunks`. 기존 admin_* 패턴 동일(SECURITY DEFINER + 비밀번호 sha256 검증).
2. **app.js `generateOkfForDoc`**: 승인 훅(approveDoc)에서 법령·고시 카테고리만 실행 — 조문 청크 앞 18,000자 발췌 → Haiku(add_law.py와 동일 프롬프트, 브라우저 직접 호출) → frontmatter 파싱(JS판 split_frontmatter) → 헤더 경계 청킹(1000/100/최소30, [제목] 접두 — import_regulatory_kb.chunk_body 동일 규칙) → voyage-embed Edge(`voyage-law-2`) 5개 동시 → RPC 적재. 파일명 관례 "제목(법률)(제N호)(YYYYMMDD)"에서 메타 자동 추출, 없으면 Haiku frontmatter로 보완. **실패 시에도 승인·조문 임베딩은 유지**(자문은 조문 기반 동작, add_law.py로 보완) — 기존 임베딩 실패 처리와 같은 fail-soft 원칙.
3. **sync_kb_to_bundle.py 신설**: 웹 생성 OKF(path `laws/web-upload/…`)는 DB에만 존재 → manifest에 없는 path를 번들 md(컬럼으로 frontmatter 재구성)+manifest 항목으로 저장, status 불일치(웹 supersede)도 manifest에 반영. 멱등·range 페이지네이션(#28 교훈)·sb_client 경유(#15).

**왜 번들을 유지하나(운영자 문답)**: "①②도 로컬에 없는데 ③(요약)만 왜 로컬에?"에 대한 결론 — 원문(Storage)·조문 청크(DB)는 법제처에서 언제든 재취득·재생성 가능하지만, **요약은 이 시스템의 창작물이라 DB가 유일 사본이고 무료 플랜은 DB 백업이 없다.** git 번들이 요약의 유일한 백업+수정이력이므로 유지. 그 대가로 생기는 웹 생성분의 번들 공백을 sync 스크립트가 메운다.

**신규 가드레일**: `import_regulatory_kb.py` 전체 재적재 전 `sync_kb_to_bundle.py` 필수(안 하면 웹 생성 OKF 유실 — manifest 정본 원칙의 이면). 지침 do-not에 등재.

---

## 30. 법령 관계도 공백 변형 노드 183건 병합 + 인용망 공백무시 매칭 (2026-07-29)

**계기**: 재난 및 안전관리 기본법 계열 3건 업로드 후 관계도 전체 업데이트 요청 → 점검 중 그래프 전반에 **공백 변형 중복 노드**("전 파법"/"전파 법", "방송통신발전 기 본법", "재난 및 안전관리기본법" 등 30+ 클러스터) 발견. 원인: pdfjs/pypdf 텍스트 추출이 단어 중간에 공백을 끼워 넣고, build_law_citation_graph.py의 `norm_name`은 연속 공백 축약만 할 뿐 **중간 삽입 공백은 못 잡음** → 「법령명」 인용 파싱이 같은 법을 다른 이름으로 노드화, 인용망이 갈라짐.

**조치**:
1. **일회성 병합**(SQL DO 블록): 공백 제거 시 동일해지는 노드끼리 정본(doc_name 보유 > 연결수 > 이름 길이 순) 선정 → 변형의 모든 엣지를 정본으로 재연결(unique 충돌 시 weight 합산) → doc_name 이관 → 빈 변형 삭제 → self-loop 제거. **노드 1,136→953(변형 183개 흡수), seed/ai 엣지 107건 전량 보존** — "노드 일괄 삭제 금지" 가드레일(#28)은 엣지 재연결 후 빈 노드만 지우는 방식이라 저촉 없음.
2. **재발 방지**: build_law_citation_graph.py `ensure_node`에 공백 무시(nrm) 색인 추가 — 기존 노드를 정확명 → nrm 순으로 조회해 변형 생성을 차단(nrm 충돌 시 doc_name 보유 노드 우선). 패치 후 재구축 검증: 논리 명칭 1,104건이 노드 953건으로 수렴, 변형 클러스터 0, 신규 변형 재생성 없음.

**교훈**: PDF 파생 텍스트에서 이름 키를 만들 때는 **공백 무시 정규화가 기본**이어야 한다(#28의 article_no '제N조/N조' 이중 표기와 같은 계열 함정). 청소는 반드시 "엣지 재연결 → 빈 노드 삭제" 순서 — 노드부터 지우면 cascade로 seed/ai 관계가 유실된다.

---

## 31. 법령 자동 현행화 체계 신설 — 감시(law_watch) + 수집·적재(law_sync) (2026-07-29)

**계기**: 재난로밍 건의 작업 중 "지식베이스 법령은 내가 올린 시점에 고정되는데, 법령은 바뀐다. 자동 현행화가 가능한가?" 질문. 조사 결과 세 가지가 드러남 — ①`law_crawler.py`가 이미 매일 개정을 감지해 `law_amendments`에 쌓고 있으나 **지식베이스와 연결이 전혀 없었고**(알림은 오지만 조문은 그대로), ②법제처 DRF `lawService.do`로 **조문 전문을 JSON으로 받을 수 있어 PDF 업로드 고리 자체가 불필요**하며, ③`eflaw` 타깃으로 **시행예정본까지 취득 가능**. 실제로 전파법은 2026.10.22 시행 개정본이 이미 공포돼 있었는데 지식베이스는 모르는 상태였다.

**운영자 결정(항목별)**: 교체는 **승인 게이트**(무인 자동 교체는 오적재 발견이 늦음), 감시 범위는 **등재 전체**, 구버전은 **최근 2~3버전 보존**, OKF는 **초기 일괄=세션(무료)·이후 개정분=API 자동**(메모리 원칙 "일회성은 세션, 무인 반복만 API"의 적용).

**구현**:
1. **DB**(migration `law_version_tracking`): `document_chunks`에 `law_id`·`law_mst`·`status` 추가(기존 14,764청크 전량 `current` → 회귀 없음), `law_watch` 레지스트리 신설, 검색 함수 2종에 `only_current`(기본 true) 추가 — kb_chunks의 기존 패턴을 조문 레이어에 이식.
2. **law_watch.py**: 감시 대상을 **매 실행 동적 발견**(고정 목록 금지 — 등록 누락 무음 미감시 방지). 법령/행정규칙 타깃 분기, 기관명 별칭 재검색, 법령 아닌 문서 자동 excluded, 시행예정본 기록.
3. **law_sync.py**: DRF API 조문 → **조문 단위 청킹**(article_no 정확) → 등재 → 구버전 정리 → 임베딩 백필. 시행일이 미래면 `pending`으로 보존, 과거면 `superseded`.
4. **대시보드**: 설정 탭 '법령 현행화 상태'(개정·시행예정·미매칭). 감시는 자동, 현행화 실행은 PC(조문 취득·임베딩이 무거워 브라우저 부적합).

**전수 점검 결과(초기)**: 법령 108건 중 **최신 100건 / 구버전 6건 / 미매칭 2건**, 시행예정본 8건. 수동 관리가 상당히 잘 되어 있었다. 구버전 6건은 전량 현행화 완료.

**구현 중 발견·수정한 실제 결함 5건** (모두 재발 방지까지 반영):
- **행정규칙 매칭 실패** — 법제처 행정규칙명은 `(과학기술정보통신부) 규정`처럼 소관부처 접두를 포함. 접두 포함/제거 2단계 매칭으로 해결(부처 이관으로 같은 규정이 2건 존재하는 경우도 올바른 쪽 선택).
- **기관명 변경 시 구버전이 current로 잔존** — `전파법 시행에 관한 방송통신위원회 규칙`이 `…방송미디어통신위원회 규칙`으로 개명(2026-18호). 이름이 달라 자동 매칭이 안 돼 **2019년판이 현행으로 남아 있었다**. 별칭 재검색 + 구버전 정리 시 prev_doc_name 강제 포함으로 해결.
- **시행예정본을 superseded로 잘못 내림** — 적합성평가 고시는 시행예정본(2026.11.6)만 등재돼 있어 **현행 조문이 KB에 없는 상태**였다. 현행본을 추가 등재하고 기존 예정본은 `pending`으로 보존(시행일 도래 시 승격)하도록 수정.
- **법제처 API가 같은 필드를 문자열/리스트 양쪽으로 반환** — 시행령 2건이 `'list' object has no attribute 'strip'`로 실패. 재귀 `_txt()` 방어.
- **전체 테이블 스캔 타임아웃(57014)** — `fetch_existing`이 document_chunks 전량을 훑어 1건이 실패(신규는 삽입됐으나 구버전 정리가 누락되는 **부분 성공** 형태라 더 위험). 법령명 ilike 선필터로 수정.

**후속(2026-07-29, 같은 날) — OKF 요약 갱신**: 조문만 현행화하고 끝내면 **자문은 여전히 옛 판 요약을 근거로 답한다.** 갱신 대상 6건(전파법 시행 규칙, 간이무선국 기술기준, 정보통신망법, 같은 법 시행령, 시험기관 지정 고시, 적합성평가 고시(NIRA))을 세션에서 무료로 재작성했다. 그 과정에서 조문을 실제로 읽고서야 드러난 것들:

- **정보통신망법이 사실상 새 법이 됐다** — 종전 요약이 "2026.7.7. 시행 예정"으로만 적어 둔 2026.1.6. 개정이 전면 시행됐다. 허위조작정보 유통금지(§44조의7②), 대규모 정보통신서비스 제공자(일평균 이용자 100만 명 이상)의 신고·이의신청·반기 투명성 보고(§44조의12~17), 게재자에 대한 5배 가중 손해배상(§44조의10③)과 SLAPP 방지 특칙(§44조의11), 10억원 이하 과징금(§44조의24)이 통째로 들어왔다.
- **반대로, 종전 요약이 "있다"고 서술한 조문이 현행본에 없었다** — §45조의4·45조의5·48조의8~10·77조는 2026.10.1./2027.4.1. 시행분이라 2026.7.7. 통합본에 존재하지 않는다. 법제처 통합본은 시행일 기준으로 끊기므로 "시행예정 조문을 미리 써 둔 요약"은 시간이 지나면 **없는 조문을 현행 의무로 단정하는 문서**가 된다.
- **시행령 별표 번호가 한 칸씩 밀렸다** — 별표 1이 신설(대규모 사업자 대상 서비스)되면서 본인확인 기준 1→1의2, 불법촬영물 대상 1의2→1의3, 연결기기 1의3→1의5. 옛 번호를 인용한 사내 문서는 전부 다른 별표를 가리키게 된다.
- **조문은 그대로인데 호수만 오른 고시 2건** — 시험기관 지정 고시와 적합성평가 고시(NIRA)는 제1~27조/제1~32조가 직전판과 실질 동일했다. 실질 개정은 별표(시험항목·대상기자재)에 있는데 **별표는 법제처 조문 API 응답에 없다.** 요약에 "변경은 별표에 있으니 원본 대조 필요"를 명시하고 옛 별표 수치를 새 판 것처럼 옮기지 않았다.
- **`import_regulatory_kb.py`에 `--only` 추가** — 종전에는 6건을 고쳐도 manifest 109건 전량을 삭제-재삽입·재임베딩했다. 낭비이자, 삭제와 삽입 사이에 자문이 그 문서를 못 찾는 공백이 생긴다.

결과: kb_documents 109건(현행 104 / superseded 5), kb_chunks 1,381건, 임베딩 NULL 0건, 고아 청크 0건. 자문 검색 함수(`match_kb_chunks_semantic`·`search_kb_chunks_trgm`)는 `only_current` 기본 true라 구판 요약은 자동 제외된다.

**후속 2 (2026-07-29) — 필터가 실은 안 걸려 있었다 + 시행예정본 다단 시행 수용**

운영자가 Phase 3 착수 전에 세 가지를 물었다. ①다음 주에 전파법 2027년 시행예정본이 뜨면 자동으로 pending에 들어오나 ②시행예정이 2개 이상이면 그것도 되나 ③자문이 현행 기준으로 답하면서 시행예정을 덧붙여 주나. 코드와 실DB로 확인한 답은 ①감지만 되고 적재는 안 됨 ②안 됨 ③안 됨이었고, 확인 과정에서 **더 나쁜 사실**이 드러났다.

- **`only_current` 필터가 애초에 동작한 적이 없었다.** `law_version_tracking` 마이그레이션에서 `match_chunks_semantic`·`search_chunks_trgm`에 `only_current` 인자를 추가하며 `CREATE OR REPLACE`를 썼는데, **인자 개수가 달라지면 그것은 교체가 아니라 새 오버로드 생성**이다. 구 3인자 함수가 그대로 남았고 app.js는 인자 3개로 호출하므로 PostgREST가 **필터 없는 쪽으로 해석**했다. 게다가 RAG 3경로 중 키워드 `ilike` 경로는 처음부터 status를 보지 않았다. 결과적으로 superseded 1,608청크(정보통신망법 옛 판 220청크 포함)가 현행과 구분 없이 자문 근거로 쓰이고 있었다. 검증: `search_chunks_trgm('허위조작정보 유통금지', …)` 20건 중 `only_current=false`면 11건이 시행예정본. 구 오버로드 DROP + 호출부에 `only_current: true` 명시 + ilike 경로에 `.eq('status','current')`로 복구했다.
- **감시가 구버전까지 긁고 있었다.** `fetch_all_doc_rows`가 status 무관하게 doc_name을 전부 스캔해, 방금 강등한 superseded 6건을 **다음날 아침 '개정 감지 6건'으로 오탐**할 예정이었다. `status='current'`로 한정.
- **`pick_exact`가 목록 순서에 기대고 있었다.** 행정규칙 검색은 현행본과 시행예정본을 섞어 주는데 `현행연혁코드`가 비어 있는 경우가 많다. 적합성평가 고시가 제2025-56호(시행 2026.11.6, 미래)와 제2026-4호(현행) 둘 다 나오는데 첫 행을 골라 **미래본을 현행으로 등재**했던 것이 이 사고의 원인이었다. 시행일 기준 판정(시행 중인 것 중 가장 늦은 것)으로 교체.

시행예정본은 `law_pending` 테이블(1:N)을 신설해 전건을 담게 했다. 설계에서 실측으로 확인한 것들:
- **식별자는 (MST, 시행일)이다.** 정보통신망법 MST 285199 하나가 20261001(179조)과 20270401(180조) 두 통합본을 갖는다. MST만으로는 특정되지 않고, `target=eflaw`는 `efYd` 없이 부르면 **빈 응답**을 준다.
- **같은 시행일의 복수 개정법률은 통합본이 하나다.** 국가재정법 20260811에 MST 285521(공포 21546)·283171(공포 21341) 두 행이 뜨지만 조문 137개·본문 해시가 일치했다. 시행일로 dedupe하지 않으면 동일 문서를 두 번 적재한다(첫 수집에서 21건 → dedupe 후 15건).
- **행정규칙에는 eflaw가 없다.** admrul 검색 결과에서 시행일이 미래인 행을 고르는 방식으로 처리.
- **이미 PDF로 올려둔 예정본이 있으면 재적재하지 않는다.** API본은 별표가 빠져 있어(적합성평가 고시 PDF 166청크 vs API 48청크) 오히려 빈약하다. 실제로 이번에 중복 1건이 생겨 제거하고 PDF본에 연결했다.
- **승격(`--promote`)을 매일 자동 실행에 넣었다.** 없으면 시행일이 지나도 자문이 옛 조문을 현행으로 답한다. 승격 시 직전 current를 superseded로 내리고 law_watch 기준본도 새 문서로 옮긴다.

결과: law_pending 15건 / 10개 법령(정보통신망법 3단계, 국가재정법 3단계, 전기통신사업법 2단계), pending 청크 2,719, 임베딩 NULL 0.

**후속 3 (2026-07-29) — Phase 3: 자문 답변에 시행예정 반영**

데이터가 갖춰지자 마지막 단계를 붙였다. 인용된 현행 조문에 대응하는 시행예정 조문 원문을 system 컨텍스트에 덧붙여 "현행은 A, 언제부터 B"까지 답하게 하는 것. 착수 전 조사에서 **설계를 뒤집는 사실 두 가지**가 나왔다.

- **law_id로 조인할 수 없다.** current 문서 263건 중 **256건(97%)의 law_id가 NULL**이다 — 대부분 PDF 업로드본이라 law_sync를 거친 적이 없다. law_id로 만들어지는 current↔pending 쌍은 정보통신망법 3쌍이 전부. 짝짓기 축을 `law_pending.watch_doc_name ↔ doc_name` 문자열 조인으로 잡았다(15/15 완전일치).
- **현행↔시행예정의 문자열 diff는 쓸 수 없다.** 현행 등재본 15쌍 중 **12쌍이 PDF 추출본**이고 시행예정본은 전부 법제처 API본이라, 줄바꿈·곡선따옴표·날짜 표기(`2015. 1. 20.` vs `2015.1.20`)·`[전문개정]` 주석이 전 조문에서 어긋난다. 전파법은 130개 조문 **전부**가 '변경'으로 판정됐다(실제 개정은 훨씬 적다). 기계 diff를 포기하고 **양쪽 원문을 나란히 모델에 주고 판단시키는** 방식으로 바꿨다 — 프롬프트에 "표기 차이뿐이면 개정이 아니다"를 명시. 반면 시행예정본끼리는 전부 API본이라 문자열 비교가 신뢰 가능해, 같은 조문의 여러 시행일 판이 동일할 때 중복 제거에 썼다.

구현 중 실측으로 잡은 결함:
- **문서 배열 × 조번호 배열 = 교차곱.** 첫 구현은 두 배열을 따로 RPC에 넘겼는데, 실제 질의('침해사고 신고 의무 기한')에서 **시행령 제58조의2(침해사고 신고 절차)를 인용했더니 본법 제58조의2(구매자정보 제공 요청)의 시행예정본이 딸려 왔고**, 보도자료 청크의 제6조·제10조가 정보통신망법 본법 조문을 끌어왔다. `(문서, 조번호)` jsonb 쌍 배열로 교체.
- **조문 제목이 매칭을 깬다.** `article_no`가 `48조의3(침해사고의 신고 등)` 형태라 제목이 개정되면 대응이 끊긴다(정보통신망법 제47조의7 "특례"→"차등적용 등"). 조번호만 잘라 쓰니 현행 조문의 100%가 대응본을 찾았다.
- **컨텍스트가 순식간에 커진다.** 과태료 조문처럼 긴 조문 2건만으로 17KB. 24,000자 상한을 두되 **조문 중간을 자르지 않고**(모델이 잘린 문구를 인용한다) 조문 경계에서 끊고 생략 건수를 프롬프트에 남겼다.

검증(실제 RAG 경로 통과): '침해사고 신고 의무 기한' → 정보통신망법 제48조의3의 **"즉시"(현행) vs "발생 사실을 알게 된 때부터 24시간 이내"(2026.10.1)** 가 컨텍스트에 함께 들어옴. '재난 시 이동통신 로밍 근거' → 방송통신발전 기본법 제35조의3·제37조 시행예정본(2026.8.20). '주파수 재할당 절차' → 전파법 제16조·제16조의2·제17조(2026.10.22).

**후속 4 (2026-07-29) — PDF 등재본을 API로 재적재. 운영자의 반문이 옳았다**

Phase 3를 마치며 "현행본 PDF 12건의 API 재적재는 하지 말자, 별표를 잃는다"고 권고했다. 운영자가 되물었다 — *"그럼 그냥 API로 현행 법령 가져와서 overwrite 하면 되는 거 아닌가?"* 실측해보니 **권고가 틀렸다.**

- **별표는 법률에 거의 없다.** 별표가 실질인 것은 시행령·시행규칙·고시다. 재적재 후보 법률 10건을 정밀 측정하니 **전부 별표 표 본문 0건**이었다. 앞서 "별표 손실"을 근거로 든 것은 적합성평가 **고시**(166→48청크) 사례를 법률에까지 일반화한 것이었다. 문서 종류를 나누지 않고 하나의 사례로 전체를 판단했다.
- **오히려 PDF본이 검색을 망가뜨리고 있었다.** PDF 추출본은 단어 중간에 줄바꿈이 들어간다. 전파법은 197청크 중 **188청크(95%)** 가 그 상태였고, `가격경쟁`이 `가격\n경쟁`으로 잘려 키워드 `ilike` 검색에 걸리지 않았다(현행 2건 hit vs API본 3건 hit). 조문 단위가 아닌 800자 청킹이라 `article_no`도 부정확했다.
- 즉 **"현행성 확인이 안 된다"는 문제는 애초에 없었다.** law_watch는 law_id가 아니라 문서명(법령명·법령번호·시행일) 파싱으로 대조하므로 108건 전부 정상 감시 중이었다. 내가 "law_id로 **조인**할 수 없다"고 쓴 것이 "현행 확인이 안 된다"로 읽힐 만했다.

`law_sync.py --reingest` / `--reingest-laws`를 만들어 법률 9건을 교체했다(정보통신망법·지방세법은 이미 API본이라 자동 제외). 안전장치 2종을 내장했다 — ①`행정처분기준·과태료의 부과기준·위반횟수별·1차 위반`이 검출되면 거부(별표 표가 있다는 뜻) ②손상률 30% 미만이면 이미 API본으로 보고 건너뜀(API본도 항·호 줄바꿈으로 4%쯤은 잡힌다). **구본은 삭제하지 않고** 문서명 뒤에 ` [PDF원본]`을 붙여 `superseded`로 보존해 되돌릴 수 있게 했다.

시행령·시행규칙·고시는 그대로 뒀다. 전파법 시행령·시행규칙에는 행정처분기준 별표가 실제로 들어 있다 — 다만 PDF 표 추출이 열을 뒤섞어(`"7. 법 제28조제4항을 위반하여 법 제76조 업무종사 업무종사 기술자격 / 항공기국이 항공국과 연락을 하제1항제7호 정지 정지 취소"`) 사실상 판독 불가 상태라, 남겨두는 것이 옳은지는 별도 판단이 필요하다.

**후속 5 (2026-07-29) — 재적재 검증에서 부칙 누락이 드러나고, 그 추적 끝에 "API는 별표를 안 준다"는 전제가 무너졌다**

재적재 결과를 검증 에이전트에 맡겼더니 **부칙이 9건 중 8건에서 통째로 사라졌다**고 나왔다. 부담금관리 기본법은 본문 길이가 −52%였는데 감소분이 거의 전부 부칙이었다. 시행일·경과조치·적용례가 부칙에 있으므로 "언제부터 누구에게 적용되나"를 답할 근거가 사라진 셈이다. 원인은 단순했다 — `fetch_law_articles`가 응답의 `조문.조문단위`만 읽고 `부칙`을 읽지 않았다.

부칙을 붙이려고 응답 구조를 다시 열어보다 **`별표` 키를 발견했다.** 전파법 시행령 43건, 적합성평가 고시 30건이 표 본문(괘선 문자 포함)까지 들어 있었다. 즉 **"법제처 조문 API는 별표를 주지 않는다"는 전제가 처음부터 틀렸다.** 그 전제 위에서 내렸던 판단이 줄줄이 잘못돼 있었다 — 적합성평가 고시 OKF에 "실질 변경은 별표이며 원본 대조 필요"라고 적었고, 시행령·고시의 재적재를 포기했고, 재적재 스크립트에 "별표 표가 검출되면 거부"하는 안전장치까지 넣었다. 전부 되돌렸다.

수정 후 실측: 전파법 조문 158 + 부칙 52 + 별표 0, 전파법 시행령 조문 185 + 부칙 61 + 별표 43, 적합성평가 고시 조문 34 + 부칙 43 + 별표 30.

그 과정에서 새로 만난 결함 3건:
- **부칙을 전부 담으면 조문보다 많아진다.** 정부조직법이 54청크 → **1,185청크**가 됐고 그중 1,131이 부칙이었다. 정부 개편 부칙의 '다른 법률의 개정'이 수백 개 법률을 나열하기 때문이다. **최근 15건 / 1건당 6,000자** 상한을 두어 124청크로 정상화했다(시행일·경과조치·적용례는 부칙 앞머리에 있다).
- **800청크가 넘는 문서는 일괄 DELETE/UPDATE가 `statement timeout(57014)`으로 죽는다**(지방세법 860청크). 배치 처리로 바꿨다.
- **그 배치 처리에 조용한 버그를 넣었다.** id 커서 없이 `limit(200)`만 걸고 처리한 id를 메모리에서 제외했더니, 같은 200행이 계속 조회되다 빈 목록이 되어 **860건 중 317건만 갱신**하고 정상 종료했다. 지방세법이 current 2건이 되어서야 발견했다. id 커서 페이지네이션으로 수정.

**후속 6 (2026-07-30) — 병렬 재적재가 자문에 구멍을 냈다**

시행령·시행규칙·고시까지 94건을 재적재하기로 하고, 운영자 요청에 따라 `--shard i/n`을 만들어 **6개 프로세스로 동시 실행**했다. 결과는 나빴다.

- **Supabase가 `statement timeout(57014)`을 다발로 냈다.** 법제처 404는 한 건도 없었고 실패는 전부 DB 쪽이었다. 회차가 갈수록 성공률이 떨어졌고(8→2→0), 마지막에는 대상 목록을 뽑는 조회 쿼리조차 타임아웃했다. `_damaged_docs`가 현행 청크 13,000여 건의 **본문까지** 읽어 손상률을 계산하는데, 그걸 6개 프로세스가 매 실행 반복한 것이 결정타였다.
- **그 타임아웃이 데이터를 깨뜨렸다.** 당시 코드는 구본을 먼저 `superseded`로 내리고 신본을 넣었다. 삽입이 중간에 죽으면 그 법령의 현행 청크가 0이 된다 — 실제로 **3건이 자문에서 통째로 사라진 상태**가 됐다(방송표준방식 기술기준, 적합성평가 부정행위 운용요령, 항공주파수 이용·관리 규정). 1건은 이름만 `[PDF원본]`으로 바뀐 채 남았다.
- **샤딩 자체도 재시도에 부적합했다.** 대상 목록을 매 실행 재계산하므로 회차마다 샤드 구성원이 바뀐다. 에이전트들이 "1회차에 실패한 문서가 2회차 목록에서 사라졌다"고 보고했는데, 그게 처리된 것인지 다른 샤드로 간 것인지 각자는 알 수 없었다.

복구와 수정:
- `law_watch`가 가리키는 문서에 현행 청크가 없는 건을 찾는 쿼리로 피해를 특정하고, 구본을 `current`로 원복해 즉시 공백을 없앴다. 처음 쓴 탐지 쿼리는 버전 교체분(구 법령번호)까지 잡아 15건으로 부풀었다 — `law_watch` 기준으로 다시 짜서 실제 6건, 그중 진짜 공백 3건 + 이름 이상 1건으로 좁혔다.
- **처리 순서를 뒤집었다**: 신본 등재 → 성공 후 구본 강등. 문서명이 충돌하면 구본을 `[PDF원본]`/`[교체중]`으로 **옮기기만 하고 status는 current로 둔다.** 이제 삽입이 실패해도 검색 공백이 없다.
- 남은 27건은 **순차로** 재실행. 병렬 금지를 지침에 명시했다.

**후속 7 (2026-07-30) — 재적재 마무리와 OKF 요약 전면 점검**

남은 94건(시행령·시행규칙·고시)을 순차로 재적재해 **93건을 마쳤다.** 그 과정에서 나온 것들:

- **중복 삽입** — 삽입은 성공하고 뒤 단계(구본 강등)가 타임아웃하니, 재시도할 때마다 같은 청크가 다시 쌓였다. 항행안전무선시설 1,284 → **6,420청크**, 재난안전법 시행령 373 → **1,865청크**. 11개 문서에서 발생. 삽입 전 잔여 청크를 지우는 멱등성 가드를 넣고 정리했다.
- **`superseded`에도 중복이 있었다** — 처음엔 `current`만 점검했는데 운영자가 "같은 건 다 지워야 하지 않나"라고 물어 전 상태를 다시 보니 2건이 더 나왔다(전파법 시행에 관한 방송통신위원회 규칙 2019판, 주파수분배 변경 고시). id 간격상 **이번 작업 이전부터 있던 중복**이었다. 내용 해시까지 같은 것만 골라 제거.
- **손상 탐지기가 API본을 오탐하고 있었다** — '한글\n한글'만 보면 API본도 30~40%가 걸린다. API 줄바꿈은 항·호·조문 사이의 구조 경계이기 때문이다("1. 기획예산처차관\n제9조제3항제2호 중 …"에서 '관\n제'). 처음엔 `law_id` 있는 문서를 대상에서 빼는 식으로 우회했는데 그건 증상만 가린 것이었다. 개행 뒤가 구조 표지(제N조/①~⑮/1./가./부칙/별표/괄호)로 시작하면 정상으로 보도록 **규칙 자체를 고치고 특례를 걷어냈다**. 결과: API본 0~16% / PDF본 94%로 분리. 잔여 10~16%는 전부 **별표**에서 나오는데, 법제처가 별표를 원문의 고정폭 레이아웃 그대로 주기 때문이다("제21조에 따\n른 개발제한구역 보전부담금"). **조문·부칙은 전 문서 0%** — 자문이 인용하는 부분은 완전하다.
- **재적재 불가 1건** — 전기안전 및 전자파적합성 시험·인증 통합 처리지침(제2012-23호). 법제처에 등록은 돼 있으나 `조문내용`·`부칙`이 빈 문자열이고 첨부파일만 있다. 2012년 '공고'라 조문 단위로 정리되지 않은 것. PDF 등재본 5청크를 그대로 `current`로 유지.

이어 **OKF 요약 97건을 8개 에이전트로 나눠 점검**했다. 이번엔 **에이전트가 파일만 수정하고 DB는 SELECT만** 하게 했다(지난 사고의 교훈). 재적재는 법령 *버전*을 바꾼 게 아니므로 요약의 법령 내용 서술은 대체로 유효했고, 실제로 고칠 것은 ①"별표는 API에 없어 원본 대조 필요" 류의 이제 틀린 서술 ②비어 있던 별표·부칙 내용이었다. 에이전트들이 잡아낸 실질 오류가 여럿 나왔다 — 정부조직법 시행일 서술이 실제 부칙과 달랐던 것, 국가재정법 별표 1 "24개 법률"이 실제로는 제1~26호였던 것, 정보통신망법 시행령 별표 2·6의 표제가 틀렸던 것, 전파법 시행규칙 서식이 "60종 이상"이 아니라 **91종**이고 매핑 3건이 잘못돼 있던 것 등.

**부칙·별표 기능 추가 전에 재적재된 6건**이 그 상태로 남아 있던 것도 이때 드러났다(간이무선국 기술기준, 적합성평가 고시, 시험기관 지정 고시, 전파법 시행에 관한 규칙, 정보통신망법 시행령, 지방세법 시행령). 다시 받아 채웠고 — 적합성평가 고시는 별표만 458청크가 들어왔다 — 그 사이 에이전트가 "미적재"로 적어둔 서술 5건은 별도 작업으로 정정했다.

**후속 8 (2026-07-30) — "같은 법령이 2개"라는 지적에서 두 가지가 나왔다**

운영자가 지식베이스 화면을 보고 "똑같은 법령이 2개씩 들어와 있다, 내가 PDF로 올린 것과 API로 받아온 것으로 추정된다"고 지적했다. 확인해보니 **DB는 정상**이었다 — 현행/구버전/시행예정이 `status`로 올바르게 구분돼 있었고 자문 검색에서도 제외되고 있었다. 문제는 다른 데 있었다.

- **목록 화면이 상태를 구분하지 않았다.** `list_kb_documents` RPC에 `status` 필터가 없어 전파법 하나가 5줄(현행·시행예정·PDF구본·시행규칙 신구본·개명 전 규칙)로 보였다. RPC가 `status`를 반환하게 하고, 목록은 현행본만 표시하되 "구버전 N건·시행예정 N건 감춤 / 모두 보기" 토글을 뒀다. 감춘 사실 자체를 숨기지는 않았다.
- **진짜 중복이 4건 있었다.** `build_doc_name`이 법제처 `법령구분명`을 쓰는데 부령은 그냥 `"부령"`으로 온다. `전파법 시행규칙(과학기술정보통신부령)` 이 `(부령)` 으로 바뀌어 구본과 이름이 갈리면서 실제로 두 문서가 됐다. `parse_doc_name`에 `law_type_full`(괄호 전체)을 추가하고, API 표기로 끝나는 더 긴 기존 표기가 있으면 유지하도록 고쳤다.

이어 운영자가 **"동일 법령번호의 구버전을 굳이 가지고 있을 필요가 있나, IO·공간만 차지하는 것 아닌가"** 라고 물었다. 맞는 지적이었고, `superseded`가 성격이 다른 둘로 섞여 있다는 것을 그제서야 구분했다.

- **같은 판의 PDF 중복본 94건 / 6,064청크(약 24MB)** — 법령번호·시행일이 현행본과 동일하다. 개정된 게 아니라 추출 방식만 다른 것이므로 **이력이 아니다.** 읽히지도 않으면서 벡터 공간만 쓴다.
- **법령번호가 다른 진짜 구버전 10건 / 2,524청크** — 이건 보존 정책 대상.

공백 제거 기준으로 API본과 대조해 **A. API가 상위집합 68건 / B. 대형 법률 4건**(PDF가 더 큰 원인이 "현행+시행예정 중복 수록"임을 규명) / **C. 소형 22건**으로 나눴고, 운영자 승인을 받아 A+B 72건 5,939청크를 먼저 삭제했다.

C는 "API에 없는 내용이 있어 보존"이라고 판단했는데, 운영자가 **"차이나는 용량이 별로 없다는 이야긴 띄어쓰기나 줄바꿈 이런 거 아닌가"** 라고 되물었다. 실물을 열어보니 그 말이 맞았다 — 22건 **전부** PDF본에 머리말(`[시행 2016. 10. 21.] [국립전파연구원공고 제2016-62호…] 국립전파연구원(전파시험인증센터), 031-644-7492`)이 있었고 17건은 전화번호까지 있었다. 「무선국이 하는 업무」는 같은 구절이 **세 번 반복**돼 있었다. **조문 본문 누락은 0건.** 공백만 제거하고 글자수를 비교한 내 판단 근거가 부실했던 것이다. 22건도 삭제했다.

정리 후 남은 목록을 확인하다 **문서명 표기 차이로 매칭이 새던 3건**을 더 발견했다 — 소관부처 접두(`(과학기술정보통신부) 방송통신발전기금…`), 기관명 개명(`산업통상자원부고시`→`산업통상부고시`), 공백 유무(`규정 (과기정통부훈령)`). 셋 다 같은 판인데 이름만 달랐고 API본이 오히려 컸다(26→64, 10→15, 27→59청크). 법령명 핵심어+법령번호+시행일로 대조해 잡아냈다.

최종: **97건 6,064청크 삭제(약 24MB)**, superseded 8,588 → **2,461청크 / 7문서**. 남은 것은 전부 법령번호가 다른 진짜 구버전이다.

삭제 전에 ①대상이 전부 `superseded`인지 ②`law_watch`·`law_pending`이 참조하지 않는지를 확인했고, 배치로 지웠다(5,939행 일괄 삭제는 timeout).

**교훈**: ①"알림 인프라가 있다"와 "지식이 최신이다"는 별개 — 두 레이어를 연결하지 않으면 알림만 쌓인다. ②감시 대상 목록을 정적으로 두면 등록 누락이 무음 실패가 된다(#18·#22와 동일 계열) — 매 실행 자동 발견이 정답. ③기관명 변경은 법령명 자체를 바꾸므로 이름 기반 매칭의 사각지대다. ④부분 성공(신규 등재 O, 구버전 정리 X)이 완전 실패보다 위험하다 — 구버전이 current로 남아 조용히 오답을 만든다. ⑤**조문 현행화와 요약 갱신은 한 세트다** — 조문만 갈면 자문은 옛 요약을 근거로 답한다. ⑥요약에 "시행 예정" 조문을 미리 써 두면 유통기한이 생긴다. 시행일이 지나면 "예정"이 거짓이 되고, 아직 안 지났는데 현행본에서 사라진 조문은 없는 의무를 만들어 낸다. ⑦**마이그레이션을 적용했다고 필터가 걸린 것이 아니다.** 인자를 추가한 함수는 오버로드가 되어 옛 것이 남고, 호출부가 옛 시그니처를 쓰면 아무 일도 일어나지 않는다 — 적용 후 반드시 "필터 켠 결과 vs 끈 결과"를 실제 쿼리로 대조할 것. ⑧한 기능에 경로가 여럿이면(RAG 3경로) 필터는 **전 경로**에 걸어야 한다. 한 군데만 빠져도 방어가 없는 것과 같다. ⑨**두 목록을 따로 넘기면 교차곱이 된다.** (문서, 조문) 같은 복합 조건은 반드시 쌍으로 전달할 것 — 결과가 그럴듯해서 눈으로는 안 잡힌다. ⑩적재 소스가 섞인 데이터(PDF 추출본 + API본)에 문자열 비교를 걸면 안 된다. 비교 가능성은 **같은 파이프라인으로 들어온 것끼리만** 성립한다. ⑪**한 사례로 전체를 판단하지 말 것.** "별표 손실"은 고시에서는 맞고 법률에서는 틀렸는데, 문서 종류를 나누지 않고 하나로 권고했다가 운영자 반문에 뒤집혔다. 권고 전에 **대상별로 실측**할 것. ⑫이미 들어와 있는 데이터의 품질도 주기적으로 의심할 것 — 전파법 조문의 95%가 검색이 깨진 채로 오래 방치돼 있었고, 아무도 오류를 보지 못했다(검색이 조용히 덜 걸릴 뿐이라서). ⑬**"API가 X를 안 준다"고 단정하기 전에 응답 키를 전부 찍어볼 것.** 별표는 처음부터 오고 있었는데 안 읽었을 뿐이고, 그 틀린 전제 위에서 내린 판단이 문서·코드·OKF 요약 여러 곳에 박혀 있었다. ⑭**대량 처리 루프는 "정상 종료"가 곧 "전량 처리"가 아니다.** 커서 없는 페이지네이션이 860건 중 317건만 처리하고 조용히 끝났다 — 처리 후 건수를 반드시 대조할 것. ⑮**병렬화가 항상 빠른 것은 아니다.** 6중 동시 실행이 DB를 타임아웃시켜 순차보다 느렸고, 게다가 데이터를 깨뜨렸다. 병목이 DB·외부 API면 동시성을 올릴수록 전체 처리량이 떨어진다. ⑰**점검 범위를 임의로 좁히지 말 것.** 중복을 `current`에서만 찾았다가 `superseded`의 2건을 놓쳤다 — 운영자가 되물어서야 발견했다. ⑱**오탐을 특례로 우회하지 말고 규칙을 고칠 것.** "API본은 대상에서 제외"는 증상만 가렸고, 탐지 규칙 자체를 바로잡으니 특례가 필요 없어졌다. ⑳**"보존"과 "중복"을 구분할 것.** superseded를 뭉뚱그려 이력으로 두면 읽히지도 않는 데이터가 쌓인다 — 법령번호가 같으면 이력이 아니라 중복이다. ㉑**화면이 이상하면 데이터부터 의심하지 말 것.** "같은 법령이 2개"는 DB가 아니라 목록 쿼리에 필터가 없어서였다. 다만 그 지적을 따라가다 진짜 중복 4건도 같이 나왔다 — **사용자가 보는 이상 징후는 대체로 무언가를 가리킨다.** ⑲**대량 작업 뒤에는 그 작업이 만든 새 불일치를 다시 찾아야 한다.** 재적재 → 중복·공백, 중간에 기능을 추가 → 그 전에 처리된 것들이 구버전 상태로 남음. "끝났다"의 기준은 실행 완료가 아니라 정합성 점검 통과다. ⑯**파괴적 작업은 "새것을 만든 뒤 옛것을 치우는" 순서로.** 옛것을 먼저 치우면 중간 실패가 곧 데이터 공백이 된다 — 재시도로 복구되지도 않는다(그 문서는 이미 대상 목록에서 빠져 있으므로).

---

## 32. 무인 자가감사 세션 — 코드 리뷰 11건 반영 + 백필 인덱스 84,000배 + 기금 규정 실전 개정 처리 (2026-07-30)

운영자가 "오늘 한 작업을 리뷰하고, 최적화하고, 잘못한 게 있으면 고쳐 두라"고 지시하고 자리를 비웠다(승인 일괄 허용). 읽기 전용 에이전트 2개로 그날 작성·수정한 코드와 번들 정합성을 감사시켰고, 다음이 나왔다.

**코드 결함 11건(H2·M4·L5) — 전부 수정·단위검증.** 굵직한 것만:
- **H1 재진입 고착**: `reingest_one`이 timeout으로 끊긴 문서를 재실행하면, 정식 이름에 남은 부분 삽입분(손상률 낮음)을 보고 "이미 API본"으로 스킵했다. `[교체중]`/`[PDF원본]` 잔재를 먼저 감지해 복구 경로로 진입하도록 수정.
- **H2 승격 순서**: `promote_due`가 구본 강등 → 신본 승격 순서라, 중간 실패 시 current 0건(검색 공백)이 됐다. 신본 승격 먼저로 뒤집고 배치 갱신 적용.
- **M3 sync_one 재진입**: 신본이 이미 등재돼 있으면 그냥 스킵해, 앞선 실행이 강등 못 한 구본이 영구히 current로 남았다. 잔여 구본을 마저 강등하고 law_watch를 정리하는 화해(reconcile) 분기를 추가.
- 그 외: min_broken 인자 무시(M1), 부칙 무일자 정렬 뒤섞임(M2), 목록 파일명 XSS(escHtml 누락, M4), 죽은 정규식·낡은 도움말(L계열) 등.

**최적화 — 백필 쿼리 84,000배.** 재적재·삭제 반복 중 잦았던 `57014`/500의 뿌리가 `embedding IS NULL` 조회의 Seq Scan이었다(EXPLAIN 5,137ms). `(id) WHERE embedding IS NULL` 부분 인덱스 3개(document_chunks·kb_chunks·report_samples)를 만들어 0.061ms로 줄였고, 대량 churn 후 `VACUUM ANALYZE`를 절차에 넣었다.

**감시가 실전 개정을 잡았다.** 부령 개명 검증차 돌린 `law_watch` dry-run이 **방송통신발전기금 운용·관리규정**의 진짜 개정을 발견 — 과기정통부고시 제2022-2호 → **방송미디어통신위원회고시 제2026-25호**(2026.7.9. 시행, 정부조직개편 이관). 고친 파이프라인으로 적재했는데 1회차가 "신규 등재 67청크(검증 완료)" 후 강등 단계에서 timeout — **설계대로 이중 current라는 안전한 상태**로 멈췄고, 재실행이 M3의 화해 분기로 구본을 마저 정리했다. H1~M3 수정이 당일 실전 검증된 셈이다. OKF 요약도 신판 기준으로 전면 재작성하고 manifest(제2026-25호·소관 이관)를 갱신했다.

**번들 정합성 7건**: 부령 개명 여파 참조 4건, PDF 경로를 가리키던 resource 2건, 산업통상자원부→산업통상부 기관명 3파일, 그리고 조문은 DB에 있는데 OKF가 없던 4건(NFTC 505·NFPC 505·2011 IMT 경매 공고·470~806㎒ 재배치 변경 공고)을 신규 작성해 manifest 109→113건, `import_regulatory_kb.py --only`로 13건 164청크 재적재(임베딩 NULL 0 확인).

**보류했던 '유령 OKF' 의혹은 내가 틀렸다.** 법제처 검색에 "적합성평가 고시 제2026-10호"가 없어 kb id75를 유령으로 의심했는데, 운영자가 법제처 검색 화면을 직접 보여줘 재검증한 결과 — ①현행본 헤더의 발령번호는 마지막 **개정 수단의 번호**라서, 제2026-10호(신고면제 기술기준 고시)의 부칙이 적합성평가 고시를 타법개정하면 적합성평가 고시 현행본 헤더에도 제2026-10호가 달린다 ②현행 목록의 [예] 배지 행은 시행예정본(제2025-56호 관련, 2026.11.6.) 정보를 표시하므로 현행본 번호가 숨는다 ③운영자 폴더에 해당 PDF 실물(2.1MB, 법제처 다운로드본)이 있었다. 세 증거로 id75는 정상 현행본으로 확정. 대신 진짜 문제는 **id74(제2025-56호본)와 id138(USB-C 고시)이 시행 전(2026.11.6.)인데 current로 보이던 것** — title `[시행예정 2026.11.6.]` 접미 + 요약 ⚠️ 배너("시행일까지는 제2026-10호본·NIRA 제2026-4호를 근거로 답할 것")로 표기해 재적재했다. 지침에 '타법개정 헤더 번호 함정'과 '시행예정본 표기 규칙'으로 남겼다.

이어 운영자가 복귀해 **"OKF 없는 건 전부 만들어라, 무선국 비용 관련이 지방세법에 있다"**고 지시했다. 전수 대조(법령형 문서명 ↔ kb_documents 제목 정규화 매칭)로 남은 누락 3건을 확인해 전부 작성했다 — ①**지방세법**·②**시행령**(신규 폴더 `laws/local-tax-act/`): 운영자 말대로 **무선국 개설 허가·신고가 등록면허세 제3종 면허**(별표 1 제128호, 인구 50만 이상 시 40,500원)로 **매년 부과**되고(법 제35조②), 미납 시 면허 취소·정지 요구 사유(제39조)이며, **기지국용 철탑은 취득세·재산세 과세대상 시설**(영 제5조②, 법 제104조 준용)이라는 통신사 비용 구조를 요약했다. 적합성평가(별표 1 제127호)는 영 제51조의 "건축허가 유사 면허"라 1회만 부과 — 같은 제3종 안에서도 부과 주기가 갈린다. ③**무선통신매뉴얼**(국토교통부고시 제2021-1140호)은 법제처가 본문을 첨부파일로만 제공하는 유형이라 "본문 미보유" 명시형 OKF로 작성했다. manifest 113→**116건**. 전수 대조에서 MRA 3건·SAR 측정기준은 OKF 제목이 공식 법령명과 달라(한-베트남 MRA 등 요약형 제목) 누락처럼 보였다 — **제목 정규화 매칭의 오탐 유형**으로 기록해 둔다.

**교훈**: ①자기 코드도 감사 대상이다 — 당일 작성분에서 H급이 2건 나왔다. ②"안전한 실패"는 설계 시점에 정해진다 — 승격 순서를 뒤집어 둔 덕에 실전 timeout이 공백 대신 이중 current로 멈췄다. ③재실행 가능(idempotent)하려면 "이미 됐음" 분기가 **잔재 정리까지** 해야 한다 — 스킵은 재진입이 아니다. ④느린 쿼리는 코드가 아니라 실행계획을 볼 것 — 원인은 로직이 아니라 인덱스 부재였다.

---

## 33. 법령 54건 대량 신규 추가 — 딥리서치+상향식 전수점검+Fable 재검증 3단 교차, OKF·관계도까지 한 세트 (2026-07-30)

운영자가 "재난로밍 딥리서치 보고서를 인쇄용 워드로, 법령 관계도의 고립 버블 문제를, SKT 이동통신 관련 추가 법령을 딥리서치로"라는 3개 작업을 에이전트 병렬 실행으로 지시했다(Word 변환·관계도 버그 수정은 각각 별도 기록). 세 번째 딥리서치가 하향식(실무 영역 체크리스트) 방식으로 법령 31건을 제안했는데, 운영자가 "'재난문자방송 기준 및 운영규정'이 안 보인다"고 지적했다 — 실제로는 2차 목록에 있었지만 1차 18건에서 빠져 있었다.

**이중 검증 구조를 도입했다.** ①상향식 전수점검: 법제처 DRF로 과기정통부 계열(국립전파연구원·중앙전파관리소 포함) 현행 행정규칙을 조직코드(org=1721000)로 **전량(1,018건)** 받고, 방미통위는 전용 코드가 없어 통신 키워드 20종으로 폭넓게 스윕, 부처 필터+정밀 키워드로 64건까지 좁혀 16건의 신규 발견(방발기금 분담금 산정·징수 2건, 상호접속·공동사용 인가대상 지정 고시 등)을 얻었다. 특히 **"인가 대상 기간통신사업자 지정 고시"의 존재 자체**를 확인했는데, 이는 재난로밍 딥리서치 보고서(전 세션)에 【미확인】으로 남겨뒀던 항목을 해소한 것이었다.

②운영자가 "Sonnet으로 검색했는데 Fable로 하면 차이가 없었을까?"라고 재검증을 요청했다. Sonnet이 제외 키워드 필터로 걸러낸 259건을 Fable이 재검토해 **누락 3건**을 찾아냈다 — 그중 하나("요금한도 초과 등의 고지에 관한 기준")는 Sonnet 자신이 "고시명 확인 필요"라고 써 놓고, 정작 자기가 수집한 데이터 안에 그 답이 있는데 재확인을 안 한 것이었다. 필터 설계 판단과 "확인 필요"를 끝까지 추적하는 집요함에서 모델 차이가 실측됐다 — **기계적 API 호출·코드 실행은 모델 무관, 최종 선별·검증 게이트는 상위 모델**이라는 운용 원칙을 얻었다.

최종 54건(하향식 31 + 운영자 승격 1 + 상향식 16 + Fable 3 + 경계선 3)을 확정하고 신규 스크립트 `add_laws_batch.py`를 작성했다 — `law_sync.py`/`law_watch.py`의 검색·조문취득·문서명 함수를 재사용하되 "구버전 정리"가 없는 순수 신규 추가 전용. 드라이런에서 실패 2건을 잡았다: ①"주요정보통신기반시설 취약점의 분석·평가기준"(딥리서치가 붙인 조사 "의"가 실제 공식명과 달라 검색 실패 — 공식명으로 교체) ②"전기통신사업용 무선설비의 기술기준"(가장 우선순위 높다고 봤던 기지국 기술기준인데, 법제처에 **첨부파일 전용**으로 등록돼 API로 조문을 못 받음 — 무선통신매뉴얼과 동일 유형, PDF 수동 업로드가 필요한 항목으로 별도 표시).

실적재 53건 중 **5건이 "이미 보유"로 오탐 스킵됐다** — `already_have()`가 법령명 앞 12자 부분일치로 스킵을 판단해 "법"과 "법 시행령", "상호접속기준"과 "상호접속·공동사용 및 정보제공 협정의 인가대상 기간통신사업자"처럼 접두어만 같은 별개 문서를 같다고 오판했다. 그중 하나가 바로 위에서 발견한, 재난로밍 보고서 미확인을 풀어준 그 문서였다 — 하마터면 되찾은 걸 다시 놓칠 뻔했다. 판정을 완전일치로 고치고 5건을 재실행해 전부 회복했다. 최종 53건/449청크, 정합성 7종 전부 통과, 임베딩 NULL 0.

**OKF 요약도 함께 지어야 하는가**를 두고 한 번 멈췄다 — 처음엔 분량 부담으로 "조문만 넣고 요약은 나중에"로 플랜을 세웠는데, 운영자가 "OKF가 중요하지 않나?"라고 되물었다. 맞는 지적이었다(지침의 "초기 일괄은 세션에서 무료 작성" 원칙과도 배치). 5개 에이전트에 계열별로 분담(위치정보/개인정보/통신비밀, 정보통신기반보호법/방미통위설치법, 사업법 하위고시 A·B, 재난통신/기금/경계선)해 정확히 53건 OKF를 병렬 작성했다 — 적재 문서 수와 정확히 1:1 대응. manifest 116→169건, kb_documents 169건 일치, kb 임베딩 NULL 0.

**법령 관계도 재구축에서 실제 버그를 하나 더 잡았다.** 신규 계열(위치정보법·개인정보법 등)의 하위법령 family 엣지는 전부 정상 연결됐지만, "정보통신기반 보호법 시행령" 노드의 표시명에 공백이 끼어("정보통신기 반") 있었다. 원인 추적 결과 `ensure_node()`의 구조적 결함이었다 — 과거 어느 문서가 이 법령명을 인용했을 때 원문 공백 손상으로 깨진 이름의 "인용 스텁 노드"가 이미 존재했고, 오늘 진짜 문서가 들어오면서 공백무시(nrm) 매칭으로 그 스텁을 재사용했는데, 코드가 `doc_name`만 채우고 `name`은 그대로 둔 것이다 — **한 번 생긴 오타 이름은 이후 진짜 문서가 들어와도 영원히 안 고쳐지는 구조**였다. `ensure_node`가 nrm 매칭으로 노드를 재사용할 때 `name`도 doc_name 쪽 정본으로 갱신하도록 고쳤고(자가 치유), 재실행으로 같은 문제가 다른 곳에 더 있는지 전수 재검사해 0건임을 확인했다.

**교훈**: ①하향식 제안은 체크리스트 밖을 못 본다 — 상향식 전수(법제처 조직코드 조회)로 교차해야 진짜 빠짐을 잡는다. ②"고시명 확인 필요"라고 써 놓고 자기 데이터에서 재확인을 안 하면 손 안의 답을 놓친다 — 검증 게이트는 별도 모델로 한 번 더 돌리는 게 값어치가 있다. ③문자열 매칭으로 "이미 있음"을 판정하는 코드는 항상 완전일치로 — 부분일치·앞자리일치는 접두어가 같은 별개 문서를 삼킨다(5건 실증, 그중 하나는 이전 세션의 미해결 질문을 풀어준 문서였다 — 자동화 버그가 하마터면 그 발견 자체를 지울 뻔했다). ④"공백 무시 매칭으로 노드를 재사용한다"는 방어 로직이 반쪽만 구현되면(`doc_name`만 갱신, `name`은 방치) 방어가 오히려 오염을 고착시킨다 — 재사용 시에는 정본 필드 전체를 동기화할 것. ⑤OKF를 "나중에"로 미루는 판단은 매번 다시 검토할 것 — 지침에 이미 원칙이 있는데도 분량을 이유로 어겼다가 운영자 반문에 바로잡았다.

**후속(같은 날)**: 위 54건 중 유일하게 실패했던 「전기통신사업용 무선설비의 기술기준」(첨부파일 전용이라 API 재적재 불가) — 운영자가 국가법령정보센터에서 직접 받은 현행 PDF(제2026-4호, 2026.7.24. 일부개정)를 제공해 `upload_law_pdf.py`로 등재(121청크), OKF 작성, manifest 반영(170건), 관계도 재구축까지 마무리했다. 무선통신매뉴얼과 같은 유형(법제처 첨부파일 전용)이라 향후 개정 시에도 API 자동 현행화는 안 되고 PDF 수동 재적재가 필요함을 OKF에 명시해 뒀다.

---

## 34. 법령 관계도 주제 레이어 일괄 확장 — 신규 18주제·81엣지 시드 (전파사용료 포함, 2026-07-30)

법령 54건 신규 적재(#33) 직후 운영자가 "기존 법령 관계도를 모두 업데이트하고 전파사용료 항목도 추가하라, 여러 에이전트로 빠르게"라고 지시했다. 신규 법령들은 인용망(citation/family)에는 반영됐지만 **주제(topic) 레이어가 기존 전파 계열 33개뿐**이라, 위치정보·개인정보·상호접속·도매대가 같은 새 영역이 주제 없이 계열로만 떠 있던 상태였다.

**분담·검증 구조**: 4개 에이전트(위치정보·개인정보·통신비밀 / 접속·설비·번호·도매·회계 / 금지행위·이용자보호·인허가 / 전파사용료·기반보호·재난·기술기준)가 병렬로 조사하되, **DB 쓰기는 금지하고 JSON 제안만 반환** — 각 연결의 근거 조문을 document_chunks 실조회로 확인한 것만 제출하게 했다. 메인 세션이 법령명을 law_graph_nodes와 대조 검증한 뒤 일괄 삽입. #33의 이름 매칭 사고 교훈을 그대로 적용한 구조다.

실제로 그 검증에서 걸린 것: ①에이전트 제안의 법령명이 'ㆍ'(U+318D)를 쓰는데 그래프 노드명은 norm_name이 '·'로 정규화해 둔 상태 — 그대로 삽입했으면 **62개 법령명 중 ㆍ 포함 9건의 엣지가 이름 조인 실패로 조용히 누락**될 뻔했다(정규화 후 62건 전원 매칭 확인). ②에이전트 4가 지시문의 잘못된 조문 추정(통신시설 등급 근거를 §36의2로 줬는데 실조회로 **§35조의3**임을 확인해 정정) — "지시문보다 실DB"가 작동한 사례.

**결과**: 신규 주제 18개(긴급구조 위치정보, 위치정보사업 규제, 통신 개인정보 보호, 통신자료·감청 협조, 상호접속·접속료, 필수설비 제공·공동사용, 전기통신번호 관리, 알뜰폰 도매제공, 통신사업 회계분리, 보편적 역무, 금지행위 규제, 이용약관·요금 규제, 통신분쟁 재정·알선, 통신사기·번호도용 방지, **전파사용료**(운영자 특별 요청 — 전파법 §67·68, 시행령 §89~93, 시행규칙 서식, 특별재난지역 감면 고시), 주요정보통신기반시설 보호, 이동통신 무선설비 기술기준, 통신시설 등급·관리) + 기존 주제 5개 보강(기간통신사업 등록·인수합병 +2, 단말기 인증·유통 +3, 재난문자 +2, 재난안전통신망 +1, 방송통신발전기금 +2). 시드 엣지 81건 제안 중 80건 삽입(1건은 기존 ai 엣지와 같은 쌍이라 자동 중복 차단 — 정상).

주제 33→**51개**, 전체 뷰 100→**176노드/523엣지**. 배포 화면에서 전파사용료 등 신규 주제가 엣지와 함께 렌더됨을 실측 확인(코드 변경 없음 — 데이터만이라 배포 불필요, 어제 고친 주제-인접 엣지 필터가 그대로 적용됨).

**교훈**: ①에이전트 분업에서 "조사(병렬)와 쓰기(단일 검증 게이트)"를 분리하면 속도와 안전을 다 잡는다. ②이름 기반 조인은 항상 정규화 계층(가운뎃점·공백)을 통과시켜야 한다 — 이번이 세 번째 가운뎃점 사고 직전이었다. ③`where not exists` 이중 방어 덕에 기존 ai 엣지와의 충돌이 소음 없이 처리됐다.

---

## 35. 자문이 "수집 뉴스를 반영한다"는 게 사실이 아니었던 사고 — 법령용 키워드 재사용·최신순 정렬·600자 절단 3중 원인 (2026-07-30, 커밋 248c863·5a9ab8e)

운영자가 자문 답변 하나를 보며 **"내가 AI 자문에 수집한 뉴스도 반영하라고 했는데 실제로 반영하고 있는지? 그리고 그것이 반영된 결과인가?"** 라고 물었다. 코드상 뉴스 주입은 구현돼 있었다(`fetchRecentNewsContext()` → `callClaude`가 보조 컨텍스트 5종과 병렬 호출 → `systemWithRag`에 합성). 그런데 **그 답변에는 질문이 그대로 인용한 기사가 프롬프트에 들어가 있지 않았다.** 답변이 기사와 겹쳐 보였던 것은 웹검색(`web_search`, max_uses 3)이 같은 사건 보도를 따로 찾아온 결과였다.

대상 기사는 `smarttoday`, 2026-07-30 14:02 KST 수집, 본문 1,688자, 운영자가 잠금(locked)해 둔 상태다. 자문 시각은 15:39 KST로 시간상 문제가 전혀 없었다.

**3중 원인 — 전부 실DB 재현 쿼리로 확증했다.**

① **키워드** — 뉴스 검색이 법령용 `extractKeywords()`를 그대로 쓰고 있었다. 질문 "같은 지하철인데 통신사 와이파이 속도 최대 2배 차이나는 이유는 SKT 영향 분석해줘"에서 뽑힌 상위 3개는 `같은 / 지하철인데 / 통신사`였다. 조사 목록에 `인데`가 없어 `content ilike '%지하철인데%'`는 0건, 정작 유효한 `와이파이`·`속도`는 "앞 3개만 사용" 제한에 밀려 **검색조차 되지 않았다**.

② **정렬** — 본문 매칭이 `order published_at desc limit 2`(최신순). 그날 KT 과징금 제재 보도가 폭주해 **발췌 3칸이 전부 KT 과징금 기사**로 채워졌다.

③ **제목 목록** — `limit 30` 최신순인데, 대상 기사보다 나중에 들어온 기사가 **49건**이라 제목조차 30위 밖으로 밀렸다. 결과적으로 본문도 제목도 프롬프트에 없었다.

**여기에 절단이 겹쳤다.** 발췌가 일괄 600자였는데 이 기사에서 `28㎓`는 627자, `시범 운영`은 **1252자** 지점이다. 검색만 고쳐도 최신 시점은 여전히 잘려나갈 구조였다.

**산출물 오류** — 웹검색이 공백을 메우면서 답변이 이렇게 어긋났다.

| 답변이 쓴 값 | 기사의 실제 값 | 판정 |
|---|---|---|
| 지하철 상용 WiFi `67.0Mbps` | LGU+ **73.39** / SKT **64.48** / KT **63.12**Mbps (2025 품질평가) | 옛 수치(웹검색) |
| 5G 백홀 `150~200Mbps`·LTE 대비 약 3배 | 4호선 LGU+ **185.90** vs 3사 평균 **79.09**Mbps(2배 이상) | 옛 수치(웹검색) |
| "SKT·KT는 **아직 LTE 백홀**" / AP 개발 착수(2026.4) | SKT는 장비 개발·성능 검증 및 **시범 운영 중**, 검증 결과로 과기정통부와 협의해 전환 결정 | 시점 후퇴 |
| 이용불가 국소 41개(SKT 19·LGU+ 17·KT 5), 경영계획 미반영·수백억원 | 기사에 없음 (DB 전체에도 없음) | 웹검색 출처 |
| (누락) | 28㎓ 사업 좌초 → 3.5㎓ 백홀 선회, 부산 라우터 와이파이6 동시접속 100→200명 | 기사 핵심 누락 |

**출처 특정** — `67.0Mbps`·`41개 국소`·`수백억원`이 `news_feed`·`document_chunks`·`custom_knowledge`·`kb_chunks` 어디에도 없음을 전수 검색으로 확인해 웹검색에서 온 옛 보도임을 특정했다. 한편 자문 이력 `chat_logs.sources`에는 재난문자방송·지방세법·전자파 측정 등 **무관한 법령 청크 12건만** 찍혀 있었다 — 뉴스는 애초에 기록 대상이 아니어서, **이력만으로는 "뉴스가 반영됐나"를 사후 판별할 수 없는 구조**였다. 이번 조사에 재현 쿼리를 따로 짜야 했던 이유다.

**교정 5건**

1. **`extractNewsKeywords()` 신설** — 뉴스 전용. 저변별력 단어(`같은`·`통신사`·`영향`·`분석해줘`) 불용어화, 어미 `인데/인가/라는데` 추가, 도메인어(와이파이·백홀·주파수…) 우선. **법령용 `extractKeywords()`는 한 줄도 건드리지 않았다** — 여기 불용어를 법령용에 넣으면 법령 RAG가 함께 망가진다.
2. **관련도 정렬로 교체** — 제목 일치 가중 3 + 본문 일치 가중 1로 점수를 매겨 정렬. 키워드 6개 전량 사용(기존 3개), 2점 미만은 "질문 관련"으로 보지 않음(0건일 때만 상위 2건으로 완화).
3. **발췌 예산 차등** — 1위 1,800자 / 2·3위 700자. 질문이 가리키는 기사는 거의 전문을 넣는다.
4. **출처 표기 신설** — 본문 발췌로 실제 들어간 기사만 `[뉴스] 제목 (매체, 날짜)` 접두사로 `chat_logs.sources`에 담아(**스키마 변경 없음**) 화면에서는 `🗞️ 참조 뉴스` 별도 배지로 분리. 제목 목록 30건은 근거가 아니므로 제외 — 넣으면 거짓 표기가 된다. 같이 법령 출처는 6개 초과분을 `… 등 N개`로 접었다(무관 청크 12건이 화면을 뒤덮던 문제).
5. **수치 인용 우선 지시** — 발췌 바로 뒤에 "질문이 수치·순위 비교를 묻고 발췌에 그 수치가 있으면 웹검색·학습지식 수치를 쓰지 말고 그것을 매체·날짜와 함께 인용" 지시. 1~4를 적용한 1차 재실행에서 시점·근거는 다 고쳐졌는데도 **정작 "2배 차이"의 근거 수치를 인용하지 않아** 추가한 것이다(검색이 아니라 생성 단계 문제였다).

**검증** — 실 Supabase 조회(AI 호출 없음)와 배포 후 실제 자문 재실행으로 확인했다.

| 항목 | 교정 전 | 교정 후 |
|---|---|---|
| 추출 키워드 | `같은 / 지하철인데 / 통신사` | `지하철 / 와이파이 / SKT / 속도 / 2배` |
| 대상 기사 순위 | 발췌 3칸 밖(KT 과징금 기사 점유) | **16점 1위** (2위 7점) |
| 프롬프트 포함 | 없음 | 73.39·185.90·28㎓·시범 운영 전부 ✓ |
| 답변 수치 | 67.0Mbps·150~200Mbps | **73.39·64.48·63.12·185.90·79.09** (매체·날짜 명시) |
| 사후 검증 | 불가 | `🗞️ 참조 뉴스` 배지 3건 + `sources` 기록 |

**교훈**

① **"기능이 구현돼 있다"와 "이번 답변에 반영됐다"는 완전히 다른 명제다.** 출처 표기가 없으면 후자를 확인할 방법이 없어 오답을 그대로 신뢰하게 된다. 반영 여부는 반드시 화면에 드러나야 한다.
② **검색 정렬을 최신순으로 두면 뉴스는 그날 물량에 따라 조용히 무관해진다.** 특정 이슈가 폭주하는 날일수록 정확히 그 이슈 아닌 질문이 망가진다.
③ **법령용 키워드 함수를 뉴스에 재사용한 것이 근본 원인이다.** 도메인이 다르면 불용어도 다르다 — `통신사`는 법령 검색에선 유효어, 뉴스에선 거의 모든 기사에 있는 잡음이다.
④ **일괄 절단 길이는 조용한 실패 지점이다.** 600자는 기사 앞부분 수치는 살리고 뒷부분 최신 상황만 정확히 잘라내, "옛 시점으로 후퇴한 답변"을 만들었다.
⑤ **작업 중 자체 실수** — 신규 주석의 사고 번호를 일괄치환(`replace_all`)하다 기존 `(배경역사 #23)` 참조 2곳을 덮었고 즉시 원복했다. 번호·식별자 일괄치환 전에는 기존 참조 존재를 먼저 확인할 것.

---

## 36. 법령 관계도 전체 뷰 고시 접기 — 데이터 3배 증가로 조망 불능이 된 화면 정리 (2026-07-31, 커밋 365ee61)

운영자가 관계도 전체 인용망 화면을 보며 "너무 복잡해 보인다"고 했다. #33(법령 54건 추가)·#34(주제 18개 확장) 이후 데이터가 3배로 늘면서, #28에서 만든 적응형 임계 필터로도 감당이 안 되는 상태가 된 것이다.

**진단 — 필터 기준이 '종류'가 아니라 '연결 여부'였던 것이 원인.** 전체 뷰는 DB 1,117노드·2,431엣지를 178노드·537엣지로 이미 줄이고 있었지만, 그 178개의 구성이 문제였다.

| 종류 | 개수 | 비중 |
|---|---|---|
| **고시·행정규칙** | **96** | **54%** |
| 주제 | 52 | 29% |
| 법률 | 14 | 8% |
| 시행령·규칙 | 16 | 9% |

즉 뼈대(주제 52 + 법률 14 = 66)를 고시 96개가 덮고 있었다. 여기에 허브(전파법 74연결·전기통신사업법 73연결)의 방사형 스포크가 겹쳐 중앙이 뭉갰다. **실측: 45px 이내로 겹치는 노드 쌍 50개, 최소 간격 3px.** 법을 추가할수록 고시가 딸려 들어오는 구조라, 데이터가 늘면 반드시 재발할 문제였다.

**교정 — 고시 접기 + 고아 주제 구제.** 고시는 '법률→시행령→고시'의 말단이라 전체 조망에선 잔가지이고, 주제·법령을 클릭하면 지금도 그대로 다 보인다. 그래서 **정보를 없애는 게 아니라 한 단계 뒤로 미루는** 방식을 택했다.

**중요한 함정을 배포 전에 잡았다.** 고시를 전부 숨기면 **주제 3개(충전단자 표준화(USB-C)·적합성평가 국제상호인정(MRA)·인빌딩 무선통신보조설비)가 엣지 없는 단독 버블이 된다** — 근거가 고시뿐인 주제들이다. 이는 #28에서 이미 겪고 고쳤던 문제(코드 주석에도 "엣지 없는 단독 버블 방지"로 남아 있었다)의 회귀였다. 브라우저에서 실데이터로 계측하지 않았다면 그대로 배포됐을 것이다. 그래서 **그런 주제의 직결 고시 8개는 예외로 남기는 구제 로직**을 넣었다(단말장치 기술기준, 방송통신설비 기술기준, 적합성평가 고시, MRA 2건, 무선통신보조설비 화재안전기준 2건, USB-C 충전단자 기술기준 — 모두 해당 주제의 대표 근거라 남는 게 자연스럽다).

**검증** — 수정한 app.js를 실제로 로드해 실데이터로 계측했다(배포 전).

| 항목 | 현행 | 개선 후 |
|---|---|---|
| 노드 | 178 | **90** (−49%) |
| 엣지 | 537 | **256** (−52%) |
| 겹침 쌍(45px 이내) | 50 | **8** (−84%) |
| 최소 노드 간격 | 3px | **34px** |
| 외톨이 주제 | 0 | **0** (구제 로직 작동) |
| 주제 노드 | 52 | 52 (전량 유지) |

토글 순환(접힘 90 → 펼침 178 → 접힘 90) 정상, 주제 포커스 진입 시 고시 정상 표시·토글 자동 숨김까지 확인했다.

**교훈**

① **필터는 '연결 여부'가 아니라 '역할'로도 걸어야 한다.** 연결 기준 필터는 데이터가 늘면 말단 노드를 계속 빨아들여, 조망 화면이 서서히 무너진다. 종류별 계층 개념이 있어야 데이터 증가에 견딘다.
② **숨기는 기능은 숨긴 사실을 화면에 드러내야 한다.** `고시 88개 펼치기` 토글이 없으면 "관계도에 고시가 없다"는 오해를 부른다 — #35에서 얻은 "반영 여부는 화면에 드러나야 한다"는 교훈과 같은 원리다.
③ **같은 회귀를 두 번 겪을 뻔했다.** 단독 버블 문제는 #28에 기록돼 있었고 코드 주석에도 있었는데, 새 필터를 얹으며 재발시킬 뻔했다. 필터를 추가할 때는 기존 필터가 방어하던 조건을 먼저 확인할 것.
④ **화면 문제는 계측할 수 있다.** "복잡해 보인다"는 주관적 표현을 노드·엣지 수와 겹침 쌍·최소 간격으로 수치화하니, 개선안 비교와 사전 검증이 모두 가능했다.

---

## 37. 세션 커밋 금지 규칙 완화 — 3단계 검증 조건부 허용 (2026-07-31)

**기존 규칙과 그 이유.** "커밋·푸시는 PC 터미널에서, 세션에서 커밋 금지"는 구형 Cowork 샌드박스에서 나온 규칙이다. 그 환경은 마운트가 stale하거나 **파일 끝을 절단**한 채로 보였고, 그대로 커밋해 **깨진 파일이 푸시된 사고**가 있었다(handoff §4-1, 되돌림 사고 f37fd0b). 파일별로 제각각이라 예측도 불가능했다.

**완화 계기.** 운영자가 "커밋을 내가 해야 하나"라고 물었고, 이 세션의 환경이 그때와 다르다는 정황이 누적돼 있었다 — 세션에서 실행한 `git fetch`·`git log`·`git diff`가 원격과 계속 일치했고, 세션이 편집한 파일을 운영자가 터미널에서 커밋할 때마다 변경량이 정확히 맞았으며(예: 54줄 삽입), 배포 후 원격 파일 내용 검증도 전부 통과했다.

**검증 방식으로 전환.** "환경을 신뢰한다"가 아니라 **"매 커밋마다 절단·불일치가 없음을 증명한다"**로 규칙을 바꿨다. 과거 사고의 실패 모드(파일 끝 절단, 원격에 다른 내용 푸시)를 직접 겨냥한 3단계다.

| 단계 | 확인 | 막는 사고 |
|---|---|---|
| ① 커밋 전 | 대상 파일 `tail` 온전 | 마운트 절단분 커밋 |
| ② add | 명시 파일명만(`-A`/`.` 금지) | stale 파일 동반 되돌림 |
| ③ 푸시 후 | `rev-parse` 일치 + `git diff origin/main -- <파일>` 0줄 + 원격 파일 끝줄 확인 | 로컬과 다른 내용이 원격에 올라감 |

**첫 적용 결과(#36 문서 커밋, e76bfad)** — 3단계 전부 통과. 원격 HEAD=로컬 HEAD, 원격-로컬 diff 0줄, 양 문서 끝줄 온전, 미커밋 잔여 0.

**유지되는 제약**: ③에서 불일치가 나오면 **재푸시 금지, 원인 규명 먼저**. 구형 Cowork 샌드박스는 여전히 커밋 금지(①③을 통과할 수 없는 환경이었다). 여러 세션 동시 커밋 금지도 그대로.

**교훈** — 사고에서 나온 가드레일은 시간이 지나면 **원인이 사라졌는데도 비용만 남을 수 있다**. 다만 푸는 방식이 "이제 괜찮아 보인다"여서는 안 되고, 사고의 실패 모드를 매번 기계적으로 확인하는 절차로 대체해야 한다. 규칙을 없앤 게 아니라 조건을 붙인 것이다.

---

## 38. 뉴스 보존 15일 → 60일 확대 + "잠금 기사 실종" 오인 사고 (2026-07-31)

운영자가 "잠금 기사가 시간이 지나면 지워지는 것 같다"고 신고했다. 실DB 점검 결과 **삭제는 없었다** — 6월 13일 잠근 기사 4건(최고 94일 경과)이 전부 생존해 있었고, pg_cron·refetch 정리 3경로 모두 `locked=false` 조건을 정확히 지키고 있었다.

**실제 원인은 화면 조회 한도.** `loadNews()`가 최신순 `limit(500)`으로만 조회하는데 당시 행수가 656건이라, 발행일이 오래된 잠금 기사 4건이 653~656위로 밀려 **DB엔 있는데 목록엔 안 보였다**. "지워졌다"는 오인의 전형적 패턴 — DB 상태와 화면 상태를 분리해 점검해야 한다(#35의 출처 배지와 같은 교훈).

**교정 2건**:
① 보존 기간 15일 → **60일** (운영자 지시). 삭제 경로가 **3곳**이라 전부 통일해야 한다 — pg_cron `news-feed-cleanup`(created_at 기준), refetch_content.py 일괄 정리(published_at 기준), refetch_content.py 실제발행일 확인 후 개별 삭제. 하나라도 빠뜨리면 짧은 쪽이 이긴다. 자문 뉴스 검색 창(60일)과 정합이 맞아져 잠금 없이도 60일간 자문에 반영된다.
② `loadNews()`를 **전량 페이지네이션 조회**(range 1000행 루프, 상한 10,000) + 잠금 기사 별도 병합으로 — 운영자 지시("목록 500건 제한 제거")에 따라 limit 자체를 없앴다. PostgREST 서버 상한이 1000행/요청이라 limit 확대가 아니라 range 루프여야 한다(#28과 동일 함정). UI 문구(잠금 툴팁·운영 상태)도 60일로 갱신. 같은 지시로 Daily Briefing 목록의 limit(30)도 제거 — 브리핑은 애초에 삭제 로직이 없어 DB 전량 보관 중이었고(6/1 첫 회차부터 58건 전존), "안 보인다"의 원인은 역시 화면 limit이었다.

**교훈**: "지워졌다"는 신고는 ①DB에 있나 ②화면 조회가 그걸 가져오나를 분리해서 봐야 한다. 보존·정리 정책을 바꿀 때는 같은 정책이 구현된 곳이 몇 곳인지 먼저 세어라(이번엔 3곳 + UI 문구 4곳).

---

## 39. 과기정통부 수집 무음 0건 — 사이트 개편으로 파서 사망 (2026-07-31 발견·복구)

운영자가 "정부 보도자료 탭이 거의 전파연구원뿐이고 과기정통부·방통위 최근 것이 없다, 알고리듬 문제 아니냐"고 지적했다. 점검 결과 **맞는 지적**이었다 — DB에 과기정통부 소스가 0건, 크롤러 로그는 매일 `[MSIT] 보도자료: 0건 / 입법행정예고: 0건 / 훈령예규고시: 0건`을 찍으면서도 heartbeat는 정상 갱신(0건은 에러가 아니라서 무음).

**원인 3갈래 판별**:
① **과기정통부 = 진짜 버그.** msit.go.kr이 개편되어 목록 DOM(`table tbody tr, ul.bbs_list li`)이 빈 껍데기가 됐다. 제목·날짜는 인라인 스크립트가 `$('#td_NTT_SJ_N').html(unescape('제목'))` 식으로 채우는 구조로 바뀌어, DOM 파서가 매일 0행을 보고도 예외 없이 지나갔다.
② **방통위(방미통위) = 정상 동작.** 파싱은 되나(10행) 개편 후 게시글이 방송·스팸·재허가 위주라 통신 키워드 필터를 통과하지 못하는 것(7/20 2건 수집 이력 존재). 필터 완화는 잡음 유입이라 하지 않음.
③ **전파관리소 = 애초에 수집 대상 아님**(크롤러는 전파연구원·과기정통부·방통위 3곳). 추가 여부는 운영자 결정 대기.

**교정(crawl_msit 재작성)**: 인라인 스크립트에서 정규식으로 직접 추출 — `fn_detail(ID)`(글번호)·`unescape('제목')`·`REG_DT` 날짜 맵. 상세 링크는 **`bbsSeqNo`(폼 hidden, 게시판번호)를 붙여야** 열린다(없으면 GET이 200인데 본문은 "시스템 점검 안내" — 소프트 차단이라 상태코드로는 감지 불가). 구 DOM 구조 폴백 유지, 로그를 `행 N개 스캔, 키워드 매칭 M건` 형식으로 바꿔 **N=0이면 개편 재발 신호**로 즉시 보이게 함. 복구 직후 실행에서 신규 4건 적재 — 전파법 시행령·시행규칙 입법예고 공고(7/21) 포함.

**교훈**: "0건 수집"은 정상(뉴스 없음)과 고장(파서 사망)이 같은 얼굴을 한다 — 로그에 결과 건수만이 아니라 **스캔한 행 수**를 남겨야 구분된다(무뉴스 통지 #17, PAT 무음 실패 #18과 같은 계열의 무음 실패). 정부 사이트는 예고 없이 개편되므로 소스별 마지막 수집일이 몇 주씩 비면 파서부터 의심할 것.

---

## 40. 중앙전파관리소 업무안내 38페이지를 자문 지식으로 적재 (2026-07-31)

운영자가 전파관리소 수집 필요성을 확인하러 crms.go.kr에 들어갔다가 **좌측 '업무안내' 메뉴 하위가 전부 실무상 중요한 해설**임을 발견했다 — 무선국허가·검사·전파사용료·등록관리·전파감시·조사단속·방송업무 등.

**성격 판별이 먼저였다.** DB에는 이미 중앙전파관리소 **고시·훈령·예규 원문**이 있었다(무선국 운용규정 762청크 등). 이번 것은 그 원문이 아니라 **절차 해설**이라 중복이 아니라 보완이다. 원문에 없는 것들이 들어 있다 — 검사 수수료표, **전파사용료 산정식(시행령 제90조 별표8: 가입자수×단가×감면계수)**, 불법무선국 벌칙 구분(전파법 제84조 3년 이하 / 제87조 100만원 이하).

**레이어 선택 — 조문 RAG가 아니라 kb(regulatory-kb).** 결정적 이유는 청킹이다. `upload_law_pdf.chunk_text()`는 `제N조(` 헤더가 5개 미만이면 **800자 무맥락 슬라이딩**으로 폴백하고 `article_no`도 못 뽑는다. 해설 문서가 정확히 그 경우다. 반면 `import_regulatory_kb.chunk_body()`는 마크다운 헤더 경계로 자르고 `[제목] ` 접두를 붙여 섹션 의미를 보존한다. `Procedure` concept_type과 `procedures/` 폴더도 이미 있었고, `searchKbSummaries()`가 kb_chunks를 자동 조회하므로 **app.js 수정이 0줄**이었다.

**분야 계층을 제목에 넣은 이유**: 청크마다 `[제목] `이 앞에 붙으므로 제목이 `중앙전파관리소 업무안내 — 무선국검사 > 수수료`여야 **"수수료"가 검사수수료인지 전파사용료인지 AI가 구분**한다. 단순 나열이면 이 구분이 사라진다(운영자가 "단순 나열인가"라고 물어 잡아낸 설계 허점).

**파싱에서 걸린 함정 2개** — 둘 다 실행해 보고서야 드러났다:
- nav 순서로 분야를 추정했더니 **'방송업무'가 조사단속업무 하위로** 붙었다(그룹명과 첫 하위항목의 URL이 같을 때만 통하는 휴리스틱이었다).
- 그래서 `<title>`(`홈 >업무안내>무선국검사>검사개요`)로 바꿨더니 이번엔 **끝 조각이 '개요'인 페이지가 3개**라 파일명이 충돌했다.
- 결론: **분야는 `<title>` breadcrumb, 제목은 nav 링크 텍스트**로 출처를 분리.

**라이선스**: 업무안내 페이지는 **공공누리 제1유형(출처표시)** 로 4개 샘플 전수 확인 — 재배포·변형 허용이라 공개 repo 커밋에 제약이 없다. (게시판의 홍보 리플릿만 제4유형이며 수집 대상 아님.)

**또 하나의 함정**: `crawler.fetch_article_body()`는 반환 본문이 `[:1500]`으로 하드 절단된다(뉴스 발췌용). 그대로 썼으면 전파사용료 페이지(3,255자)가 잘렸을 것이라 `trafilatura.extract(include_tables=True)`를 직접 호출했다.

**결과**: 38문서·92청크 적재, 실패 0, 임베딩 누락 0. kb 현행 문서 165 → **203**. 재실행 시 `변경 0`(본문 sha256 비교로 멱등). 자문 검증에서 세 질문 모두 CRMS 문서가 **1순위**로 잡히고 전파법 원문도 함께 나와 회귀 없음 확인. 월 1회 자동(`전파정책_CRMS동기화`, 매월 1일 16:30, StartWhenAvailable ON).

**교훈**: 웹 문서를 지식으로 넣을 때는 ①이미 있는 원문과 중복인지 ②어느 레이어의 청킹이 맞는지 ③기존 유틸에 숨은 상한(1500자)이 없는지를 먼저 본다. 그리고 계층 구조는 화면 편의가 아니라 **검색 정확도** 때문에 필요하다.

---

## 부록 — 보고서 초안 제안 데이터 흐름

```
[등록] 내 보고서(docx/pdf/pptx/md/txt) → 브라우저 파싱 → report_samples(전문) → (PC) backfill_report_embeddings.py
                                                       └→ Haiku 증류 → report_style_rules(내 스타일)
[생성] "~~보고서 만들어줘"
   ├─ 형식: match_report_samples(유사 1~2편) + report_style_rules(스타일) + report_directives(항상 적용 지시)
   ├─ 내용: searchKeywords → buildRagContext (법령·뉴스 RAG)
   └─ sonnet(stream:true) → 내 형식의 초안
[학습] 말로 지시(이번만/항상) · 빨간펜(고쳐서 채택→편집-diff) · 👍/👎 → 임계 +2건 시 자동 재증류
```
