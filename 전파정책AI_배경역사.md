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

## 20. 팀 컨플루언스(Atlassian Cloud) 실시간 검색 연동 (2026-07-01)

**요구**: AI 자문이 법령·고시·뉴스뿐 아니라 **우리 팀 내부 문서(컨플루언스)**도 근거로 삼게 하고 싶다. 방식은 "질문 시 실시간 조회"(RAG 사전 수집이 아님).

**환경 확인 결과(설계 좌우)**: 처음엔 Atlassian Cloud를 가정했으나, 실제로는 **사내 호스팅 Confluence(Server/Data Center), 회사 도메인**이었다. 두 갈래를 갈랐다:
- 인증: Cloud는 이메일+API토큰(Basic)이지만 Server/DC는 **PAT(Personal Access Token) Bearer**. `id.atlassian.com`의 API 토큰은 Cloud 전용이라 사내엔 안 통함. PAT는 Confluence 프로필→Settings→Personal Access Tokens에서 발급하며 SSO(SAML)가 걸려도 REST API에서 통한다.
- 접근성: **외부 인터넷에서도 열리는 것을 확인** → Supabase Edge Function(도쿄, 공용 클라우드)이 도달 가능 → Edge 경유 구조 유지 확정. (만약 사내망 전용이었다면 gov_notice_crawler처럼 PC 로컬 실행으로 구조를 갈아엎어야 했음.)
- Edge Function은 두 방식을 모두 지원하도록 **인증 자동 분기**: `CONFLUENCE_EMAIL`이 있으면 Basic(Cloud), 없으면 Bearer(Server/DC PAT). 페이지 링크는 응답 `_links.base`(context path 포함 정식 절대경로) 우선.

**핵심 결정 — 왜 브라우저 직접 호출이 아니라 Edge Function인가**:
- 대시보드(`app.js`)는 GitHub Pages 정적 파일이라 공개 repo·브라우저에 그대로 노출된다. Confluence API 토큰을 여기 넣으면 유출(과거 Voyage 키 유출 사고와 동일 위험). 또한 Confluence Cloud API는 브라우저에서 부르면 CORS로 막힌다.
- 그래서 기존 `voyage-embed`와 **똑같은 패턴**으로 신규 Edge Function `confluence-search`를 두고, 토큰을 Supabase Edge Secret에 보관하여 서버 측에서만 Confluence를 호출한다. 대시보드는 anon으로 Edge Function만 부른다.

**데이터 흐름**:
```
질문 → callClaude → searchConfluence(질문) → Edge:confluence-search (토큰 보관)
     → CQL: type=page AND text ~ "질문" [AND space in (…)] ORDER BY lastmodified DESC
     → Confluence Cloud REST v1 /rest/api/content/search (expand=space,version,body.view)
     → 상위 5건 제목·링크·본문발췌(HTML→평문 900자) → buildConfluenceContext → system 프롬프트 주입
```
- 발췌 컨텍스트는 "법령 조문은 RAG 원문 우선, 팀 문서는 내부 맥락 보강용"이라고 명시해 조문 인용이 팀 문서로 오염되지 않게 함(#7 RAG 인용 정확성 장치와 같은 취지).

**폴백 설계(자문 무중단)**: `searchConfluence`는 미배포·Secret 미설정·403/401·네트워크 오류 어느 경우든 `[]`를 반환하고 `buildConfluenceContext`는 `''`를 반환. 따라서 **배포 전에도 자문은 기존과 동일하게 동작**하고, 배포·Secret 설정이 끝나면 자동으로 팀 문서가 붙는다. (voyage-embed 실패 시 시맨틱만 빠지고 자문이 사는 것과 같은 무중단 철학.)

**검색 space를 코드가 아니라 Secret(`CONFLUENCE_SPACES`)으로 둔 이유**: 대상 space가 바뀌어도 app.js 재배포·캐시버스터 갱신 없이 Secret만 바꾸면 됨. 비우면 토큰 계정이 열람 가능한 전체 space 검색. 검색 범위는 결국 **토큰 발급 계정의 Confluence 권한**에 종속(권한 밖 문서는 애초에 안 나옴).

**CQL 안전화**: 사용자 질문의 `"`·`\`를 공백으로 치환하고 200자로 잘라 CQL 문법 깨짐/인젝션 방지.

**배포 절차(수동, PC/콘솔)**:
1. Supabase → Edge Functions → `confluence-search` 생성, `docs/confluence-search.ts` 전체 붙여넣고 Deploy(verify_jwt off).
2. Edge Secrets 등록(사내 Server/DC=PAT): `CONFLUENCE_BASE_URL`(사이트 루트, /wiki·끝슬래시 없이), `CONFLUENCE_API_TOKEN`(Confluence 프로필→Personal Access Tokens), 선택 `CONFLUENCE_SPACES`. `CONFLUENCE_EMAIL`은 비움(Bearer 인증).
3. `app.js`·`index.html`(캐시버스터 `app.js?v=20260701a`) PC 터미널에서 커밋·푸시.

**관련 커밋**: app.js(searchConfluence·buildConfluenceContext·callClaude 주입), index.html(캐시버스터), docs/confluence-search.ts(신규 Edge 템플릿). — 배포·Secret 등록 후 자문 탭에서 팀 문서 관련 질문으로 `[팀문서 N]` 컨텍스트가 붙는지 확인.

---

## 21. 타 프로젝트 OKF 법령 번들(regulatory-kb) 적재 — 요약 레이어 신설 (2026-07-03)

**요구**: 다른 프로젝트에서 만든 **OKF(Open Knowledge Format) 법령 번들**(`regulatory-kb/`, 104 concept = 법령/고시/훈령/예규/절차 103 + 용어집 1)을 이 프로젝트로 가져와 자문에 쓰고 싶다. 기존 지식베이스(document_chunks)와 상당수 겹침. 1회 적재, 원본 동기화 불필요.

**핵심 발견(설계 좌우)**: 이 OKF는 **조문 원문이 아니라 법령별 구조화 요약·실무 문서**였다(본문 `# 요약 / # 적용 범위 / # 주요 내용 / # 실무 체크리스트 / # Citations`). 반면 document_chunks는 `제N조` 원문을 조문 단위로 청킹한 것(자문 조문 인용이 여기 의존). 즉 **다루는 법은 겹치나 형태가 다른 상호보완 레이어**다. 그래서 초기 가정 "겹침=교체(조문 청크 대체)"는 폐기 — 조문 원문을 요약으로 갈아끼우면 인용 회귀. 올바른 방향 = **요약 레이어를 원문 레이어 옆에 추가.**

**설계 결정**:
- **별도 스토어 `kb_documents`/`kb_chunks` 신설**(document_chunks 무변경). manifest.json(정본, 104 entries)을 순회해 적재. concept_type·law_type·law_number·enforcement_date·status·body_md를 컬럼 보존. path 유니크(문서 정체 키), dedup_key로 버전 그룹.
- **임베딩 voyage-law-2(법률 특화, 1024)**: document_chunks의 voyage-4-lite와 **분리**. 서로 다른 모델 벡터는 같은 공간 비교가 무의미하므로, kb 질의도 반드시 voyage-law-2로 임베딩해야 함 → `voyage-embed` Edge에 `model` 파라미터 추가(미지정 시 기존 voyage-4-lite로 하위호환). 두 모델 다 1024차원이라 컬럼은 호환되나 **혼용은 금지**.
- **자문 연동은 병행 조회(대체 아님)**: app.js `searchKbSummaries`(시맨틱 voyage-law-2 + trgm 병행) → `buildKbContext`가 `[법령요약]` 컨텍스트 주입(컨플루언스 `[팀문서]`와 같은 패턴). 시스템 프롬프트에 조문 인용은 document_chunks 원문 우선, 요약은 맥락 보강이라 명시.
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

**적용 ① — AI 자문 검색 병렬화 (커밋 7aa1d44)**: `searchKeywords()`의 키워드별 검색이 for 루프 안 순차 `await`(최대 10회 직렬 DB 왕복)였던 것을 `Promise.all` 동시 조회로 전환. 또 `callClaude()`의 보조 컨텍스트 5종(추가지식·뉴스·법령동향·컨플루언스·법령요약 KB)이 조문 RAG까지 6종 릴레이로 순차 실행되던 것을, 함수 시작 시 5종을 동시에 출발시키고 결과만 기존 순서로 조립하도록 변경. 병합 순서·중복제거·랭킹·프롬프트 조립 순서는 코드가 고정하므로 **AI에 들어가는 최종 프롬프트는 동일**, 답변 시작 대기만 단축. 각 병렬 호출에 개별 catch를 둬 기존 fail-soft(컨플루언스 다운에도 자문 동작) 성질 유지.

**적용 ② — news_feed 저장 견고화**: 실DB의 `idx_news_feed_url_unique`는 **이미 UNIQUE**였으나(중복 0건 확인), 문서 사본 docs/schema.sql이 일반 인덱스로 잘못 기록돼 있어 교정. gov_notice_crawler.py의 저장이 plain `insert` 배치라 **중복 URL 1건에 그 회차 배치 전체가 실패**할 수 있어, crawler.py와 동일한 `upsert(on_conflict='url', ignore_duplicates=True)` 패턴으로 통일.

**적용 ③ — 크롤러 견고화 2종 + cp949 가드 보강**: (1) gov_notice_crawler.py의 `parse_date`를 crawler.py의 다중 형식 해석기로 교체 — 날짜만 있는 기존 입력은 결과 불변(테스트로 확인), 시각 포함·ISO·상대날짜 등 기존에 빈 값이 되던 형식이 추가로 파싱됨. (2) law_crawler.py·assembly_crawler.py API 호출에 3회/5초 재시도 부여 — 하루 1회 잡이라 일시 오류 1회가 하루치 누락으로 직결되던 것을 방지(gov와 동일 정책). (3) 검증 중 law_crawler.py가 cp949 콘솔에서 `—`(em dash) print로 즉사하는 것을 발견 — #19 가드(`sys.stdout.reconfigure(encoding="utf-8")`)가 law·assembly에는 없었음(평소 GitHub Actions에서만 돌아 잠복). 두 파일에 가드 추가. 세 크롤러 수동 실행으로 정상 완주 확인.

**적용 ④ — 무음 실패 가시화 (app.js)**: 오류를 흔적 없이 삼키던 빈 `catch(e){}` 7곳(chat_logs 저장·deleted_news 기록·읽음표시·custom_knowledge 조회·Storage 정리·스타일 재증류)에 `console.warn` 추가 — 화면 동작 불변, F12 콘솔에만 흔적. 컨플루언스 검색 실패 시엔 자문 답변 하단에 "팀 컨플루언스 검색 실패 — 팀 문서 미반영" 표시 추가(`lastConfluenceFailed` 플래그) — **fail-soft(자문 무중단)는 그대로 유지**(#20 규칙 준수), PAT 만료 등으로 몇 주씩 조용히 생략되던 것을 보이게만 함.

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

**교훈**: ①"알림 인프라가 있다"와 "지식이 최신이다"는 별개 — 두 레이어를 연결하지 않으면 알림만 쌓인다. ②감시 대상 목록을 정적으로 두면 등록 누락이 무음 실패가 된다(#18·#22와 동일 계열) — 매 실행 자동 발견이 정답. ③기관명 변경은 법령명 자체를 바꾸므로 이름 기반 매칭의 사각지대다. ④부분 성공(신규 등재 O, 구버전 정리 X)이 완전 실패보다 위험하다 — 구버전이 current로 남아 조용히 오답을 만든다. ⑤**조문 현행화와 요약 갱신은 한 세트다** — 조문만 갈면 자문은 옛 요약을 근거로 답한다. ⑥요약에 "시행 예정" 조문을 미리 써 두면 유통기한이 생긴다. 시행일이 지나면 "예정"이 거짓이 되고, 아직 안 지났는데 현행본에서 사라진 조문은 없는 의무를 만들어 낸다. ⑦**마이그레이션을 적용했다고 필터가 걸린 것이 아니다.** 인자를 추가한 함수는 오버로드가 되어 옛 것이 남고, 호출부가 옛 시그니처를 쓰면 아무 일도 일어나지 않는다 — 적용 후 반드시 "필터 켠 결과 vs 끈 결과"를 실제 쿼리로 대조할 것. ⑧한 기능에 경로가 여럿이면(RAG 3경로) 필터는 **전 경로**에 걸어야 한다. 한 군데만 빠져도 방어가 없는 것과 같다. ⑨**두 목록을 따로 넘기면 교차곱이 된다.** (문서, 조문) 같은 복합 조건은 반드시 쌍으로 전달할 것 — 결과가 그럴듯해서 눈으로는 안 잡힌다. ⑩적재 소스가 섞인 데이터(PDF 추출본 + API본)에 문자열 비교를 걸면 안 된다. 비교 가능성은 **같은 파이프라인으로 들어온 것끼리만** 성립한다. ⑪**한 사례로 전체를 판단하지 말 것.** "별표 손실"은 고시에서는 맞고 법률에서는 틀렸는데, 문서 종류를 나누지 않고 하나로 권고했다가 운영자 반문에 뒤집혔다. 권고 전에 **대상별로 실측**할 것. ⑫이미 들어와 있는 데이터의 품질도 주기적으로 의심할 것 — 전파법 조문의 95%가 검색이 깨진 채로 오래 방치돼 있었고, 아무도 오류를 보지 못했다(검색이 조용히 덜 걸릴 뿐이라서). ⑬**"API가 X를 안 준다"고 단정하기 전에 응답 키를 전부 찍어볼 것.** 별표는 처음부터 오고 있었는데 안 읽었을 뿐이고, 그 틀린 전제 위에서 내린 판단이 문서·코드·OKF 요약 여러 곳에 박혀 있었다. ⑭**대량 처리 루프는 "정상 종료"가 곧 "전량 처리"가 아니다.** 커서 없는 페이지네이션이 860건 중 317건만 처리하고 조용히 끝났다 — 처리 후 건수를 반드시 대조할 것.

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
