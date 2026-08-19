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
- ➡️ **2026-08-02 보강: 내부 감시를 `watchdog_scan()`으로 확장(§62 참조).** 위 내부 워치독(check_news_health)이 뉴스·브리핑 2종만 보던 사각을 system_health 10키 전수 감시로 메움 — GitHub 계정 정지로 외부 워치독이 감시대상과 함께 죽어 뉴스 크롤러 15시간 무알림이 실제로 발생한 사고가 계기.

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

## 41. kb 레이어가 출처 배지에 한 번도 뜨지 않았다 — #35와 같은 무음 실패 (2026-07-31)

#40으로 CRMS 38문서를 넣은 뒤, 운영자에게 **"자문 답변 하단 `참조 문서` 배지에 CRMS 문서가 뜨는지 보라"**고 검증 방법을 안내했다. 그런데 운영자가 실제로 질문해 보니 배지에 CRMS가 없었다. 적재는 정상이었다 — **배지 쪽이 처음부터 kb를 표시하지 않고 있었다.**

`buildKbContext()`가 kb 청크를 프롬프트에는 넣으면서 `lastRagSources`에는 **아무것도 기록하지 않았다.** 그래서 CRMS 38건뿐 아니라 **그 전부터 있던 법령요약 165건까지, kb 레이어 전체가 배지에 한 번도 나타난 적이 없었다.** 조문(document_chunks)과 뉴스만 배지에 떴으므로 화면은 늘 정상으로 보였다.

**#35와 정확히 같은 부류다** — 기능은 돌아가는데 반영 여부를 확인할 창구가 없어, 틀린 답도 믿을 만하게 보인다. *"기능이 구현돼 있다"와 "이번 답변에 반영됐다"는 다른 명제*라는 #35의 교훈이 곧바로 재발했다.

**조치**: 출처 접두사를 3종으로 정리했다 — 접두 없음=조문 원문 / `[뉴스] ` / `[요약] `(kb). `splitSources()`가 셋으로 갈라 배지를 `참조 법령`·`참조 뉴스`·`참조 요약·실무`로 나눠 그린다. `chat_logs.sources`가 단일 text 배열이라 접두사로 구분하는 방식을 그대로 확장했다.

**교훈**: **검증 방법을 안내하기 전에 그 검증 창구 자체가 동작하는지 먼저 확인한다.** 내가 안내한 검증 절차가 틀려서, 운영자가 "적재가 실패했다"고 오해할 뻔했다.

---

## 42. 실무 안내 메뉴 신설 + 두 지식 목록에 이름 검색 (2026-07-31)

#41로 배지에 `참조 요약·실무`가 뜨기 시작하자 곧바로 다음 문제가 드러났다 — **배지에 뜬 그 문서를 열어 볼 화면이 없었다.** kb_documents 203건(CRMS 38 / 법령요약 163 / 기타 2)은 자문에는 쓰이는데 대시보드 어디에도 목록이 없었다. `국내 법령·고시` 탭은 조문 원문(document_chunks) 전용이라 kb는 한 건도 안 보인다.

**`실무 안내` 탭 신설**(지식 베이스 그룹, `국내 법령·고시` 아래). **접히는 계층 목록** —
- **중앙전파관리소 업무안내 · 2단**: 분야(10) › 문서
- **법령 요약 · 3단**: 계열(18) › 하위 묶음(6종) › 문서 — 예: `전파법 계열 76` › `무선설비·무선국 고시 29` › 문서
- 필터 칩(전체 / 중앙전파관리소 38 / 법령 요약 163) + `모두 펼치기` + 이름 검색

**첫 시도를 평면 나열로 냈다가 운영자에게 되돌려받았다.** 계획 단계에서 계층 목록 시안을 보여 놓고 실제로는 42개 그룹을 전부 펼쳐 203건을 한 화면에 쏟았다 — 분야·계열 구조가 그대로 사라졌다. **기본은 접힘**, 구획마다 맨 위 묶음 하나만 펼쳐 "눌러서 펴는 목록"임을 드러내는 방식으로 다시 만들었다. 초기 펼침은 **정렬(건수 내림차순) 뒤에** 정해야 화면 맨 위 묶음과 펼쳐진 묶음이 일치한다(처음엔 경로 순서로 골라 엉뚱한 묶음이 열렸다).

폴더명이 영문(`radio-act`/`wireless-notices`)이라 **한글 이름표 매핑**을 넣고(계열 18 + 하위 6), 폴더 실제 이름을 회색으로 병기했다 — 운영자가 `telecom-facility-standards`를 알 이유는 없지만, 파일을 찾아야 할 때 대조는 돼야 한다. 배지는 둘: **`청크 없음`**(등재만 되고 자문 검색엔 안 잡히는 상태 — #41과 같은 무음 실패를 미리 막는 장치, 현재 0건)과 **`표 포함`**(수수료표·산정식이 있는 문서 77건).

**`list_kb_guide_docs` RPC 신설.** 처음엔 `kb_documents`를 직접 select하고 `kb_chunks` 2,108행을 따로 긁어 청크 수를 셌는데, `표 포함` 판정을 하려니 `body_md`가 필요했다 — **203건 합계 681kB**라 내려받을 수 없다. 표 포함 여부·청크 수를 서버에서 계산해 돌려주는 RPC 하나로 바꿔 요청 3~4회가 1회가 됐고, 본문은 클릭한 1건만 조회한다.

본문 열람은 조문 모달(`kb-doc-modal`)을 함께 쓰되 **조문 검색줄은 감춘다** — 요약본은 조문 단위가 아니라서 `제37조` 검색이 의미가 없다. 대신 `renderMd()`로 표까지 렌더한다(CRMS 수수료표·산정식이 표다). 조문 문서를 다시 열 때 검색줄을 되살리는 복원 처리를 `openKbDoc()`에 넣었다 — 안 넣으면 한 번 실무 안내를 본 뒤로는 조문 검색이 영영 사라진다.

**이름 검색창** — 운영자 요청으로 `국내 법령·고시`(169건)와 `실무 안내`(203건) 목록 위에 같은 컴포넌트로 배치. 부분 일치·입력 즉시 필터, 공백 다중 단어는 AND, 일치 글자 강조, 결과 건수, `×` 초기화. **결과 0건인 묶음은 통째로 숨기고, 실무 안내에서는 일치한 묶음을 자동으로 펼친다**(접힌 채면 결과가 안 보인다).

구현에서 걸린 것 두 가지:
- **검색 대상은 표시용 정리 이름**(`_kbParseName().clean` / `_guideDisplayName()`)이어야 한다. 원본 `doc_name`에는 `_중복_` 접두와 `.pdf` 확장자가, kb `title`에는 `중앙전파관리소 업무안내 — {분야} > ` 접두가 붙어 있어 그걸로 매칭하면 결과가 어긋난다.
- **타자마다 DB를 치면 안 된다.** 검색은 `oninput`으로 목록 함수를 다시 부르는 구조라, 원본 행을 `_kbDocsRows`/`_guideRows`에 캐시하고 재렌더만 한다. 캐시가 없었으면 한 단어 치는 동안 RPC가 5~6회 나간다.
- 강조는 `<mark>`을 바로 끼워 넣으면 다음 단어가 태그 문자열(`mark`, `class`) 안쪽에 걸려 HTML이 깨진다. **제어문자 자리표시자로 감싼 뒤 마지막에 한 번에 태그로 치환**한다. 자리표시자는 원시 제어바이트가 아니라 `\u0001` 이스케이프로 적는다(소스에 보이지 않는 바이트가 남으면 편집 도구가 삼킬 수 있다).

**표가 읽히지 않던 문제 — 원인이 둘이었다.** 운영자가 등록요건 표를 열어 보고 "읽기 힘들다"고 했다.
- ① 표 스타일이 `.msg-ai`(자문 답변)에만 걸려 있어 **모달에는 테두리·여백이 하나도 없었다.** 글자만 흩어져 표로 보이지 않았다. 같은 규칙을 `#kb-doc-body`에도 주고, 한글이 단어 중간에서 갈라지지 않게 `word-break: keep-all`을 넣었다(없으면 `재판매하 / 는 사업`처럼 끊긴다).
- ② 더 큰 문제는 **열이 어긋나 있었다는 것**이다. 웹 표를 긁으면 원본의 rowspan이 풀리면서 `| 나. … | ||` 꼴의 행이 남는데, 내용이 **`구분` 열 아래로 들어간다.** 등록요건 본문이 분류명 자리에 놓이니 규정을 잘못 읽게 된다. 단순히 보기 나쁜 게 아니라 **틀린 표시**였다.
- 조치: `renderMd()`에서 ⓐ **어느 행에서도 안 쓰는 빈 열을 버리고**(정보 손실 없음) ⓑ **첫 칸에만 내용이 있는 행은 통칸(colspan)으로** 깐다 — 없는 열 구분을 지어내지 않고 "앞 행에서 이어지는 내용"으로만 표시한다. 실측: 등록요건 표의 빈 칸 30/54 → 4/28, CRMS 25개 문서·56개 표 전체에서 빈 칸 비율 12.7%로 내려갔다. 법령 요약 표(AI 작성분)와 자문 답변 표는 이 패턴이 없어 그대로다(회귀 확인).

**교훈 둘.** ① 자문이 근거로 쓰는 지식은 **사람이 눈으로 열어 볼 수 있어야 한다** — 배지에 이름만 뜨고 내용을 못 보면 검증이 반쪽이다. #41(배지)과 #42(열람)는 같은 문제의 앞뒤다. ② **시안을 보여 승인받았으면 시안대로 만든다.** 계층 목록을 그려 놓고 평면 나열을 내놓는 건 구현이 아니라 축소다. 완성 보고 전에 시안과 화면을 나란히 놓고 대조할 것.

---

## 43. 조문은 잡히는데 별표가 안 따라온다 — 별표 동반 인출 (2026-07-31)

운영자가 자문에 "무선국 변경신고 금액은 얼마야?"를 물었더니 답 끝에 **"별표12의 구체적 금액은 이번 RAG 검색 결과에 포함되지 않았습니다. 시행령 별표12 원문을 별도 확인하시기 바랍니다"** 가 붙었다. 운영자가 되물었다 — "별표까지 들어가 있는 거 아니었나?"

**들어가 있었다.** 전파법 시행령 청크 323~326에 별표12 전문(수수료표 전체)이 `article_no='별표 12(무선국 및 전파응용설비 허가 등의 신청수수료(제95조제1항 관련))'` 로 온전히 있다. **DB에 있는 자료를 두고 사용자를 밖으로 내보낸 것**이다.

**문장 자체는 거짓이 아니었다** — 실제로 그 검색에 별표12는 없었고, 모델은 금액을 지어내지 않았다(그랬으면 훨씬 큰 사고). 잘못은 검색이 못 꺼내 준 쪽, 즉 이 시스템에 있다.

**원인 — 어휘가 아니라 제도가 다르다.** 실측했다:

| 질문 | 별표12 시맨틱 유사도 | 임계값 0.45 | 실검색 포함 |
|---|---|---|---|
| 무선국 **변경신고** 금액은? | **0.408** | 미달 | ✗ |
| 무선국 **변경허가** 수수료? | 0.523 | 통과 | ✓ |
| 무선국 **허가 신청수수료**? | 0.530 | 통과 | ✓ |

별표 검색 자체는 잘 되고 있었다. 못 잡는 건 질문이 다른 말을 쓸 때뿐이다. 「변경신고」(법 제22조의2)와 「변경허가」(제21조)는 **다른 제도**라 의미공간에서 가까워질 이유가 없다.

**그래서 B안(별표 청크에 제목 머리말을 붙여 재적재)을 접었다.** 머리말을 붙여 재임베딩한 값을 직접 재봤더니 첫 청크 0.408 → **0.406**(변화 없음), 둘째 청크 0.342 → 0.404. 둘 다 임계값 미달이다. 5,010청크를 재임베딩해도 이 질문은 여전히 실패한다. 첫 청크에는 이미 `■ 전파법 시행령 [별표 12] … 신청수수료(제95조제1항 관련)`이 원문에 들어 있어 머리말이 중복이었던 것도 한몫했다. — **추측으로 기각하지 않고 임베딩을 직접 재서 확인한 것이 이 결정의 근거다.**

**채택 — A안: 인용 관계를 규칙으로 따라간다.** 검색 확률을 올리는 대신, 이미 잡힌 조문이 가리키는 별표를 결정적으로 붙인다. 제95조("변경허가를 신청하는 자는 **별표 12**에 따른 수수료를 내야 한다")는 그 검색에서 이미 0.482로 잡혀 있었다. 다리는 건너왔는데 표를 안 집어온 것이다.

`buildAnnexContext()` — 기존 `buildPendingContext()`(시행예정 개정본 동반 인출)와 같은 자리·같은 패턴.

- **상한이 필수다**: 별표 419개 중 평균 12청크, **최대 812청크**(항행안전무선시설 별표1). 통째로 넣으면 65만 자가 프롬프트에 들어간다. → 질문당 별표 2개, 별표당 6청크.
- **첫 청크는 무조건 포함**: 표의 열 이름이 첫 청크에만 있다. 별표12 둘째 청크는 `│1만원 │― │―│`로 시작해, 단독으로는 무슨 숫자인지 알 수 없다.
- **「다른 법령」 별표 N은 건너뛴다**: 인용 978건 중 90건이 타 법령 인용인데, 같은 문서의 같은 번호 별표를 붙이면 엉뚱한 표가 들어간다.
- **표 머리 보충**: 검색으로 별표 조각이 직접 잡혔는데 첫 조각이 빠진 경우(실측: 별표 27) 그 조각만 채운다.
- 출처 배지에 `[별표] ` 접두 4번째 종류를 추가 — 반영 여부를 눈으로 확인할 창구부터 만든다(#41 교훈).

**구현 중 실측으로 잡은 사고 둘:**
- 인용이 없으면 곧바로 `return ''` 했는데, **표 머리 보충이 필요한 경우가 바로 그 경우였다**(별표 조각만 검색되고 조문은 안 잡힌 질문). 조기 반환이 정작 필요한 보완을 건너뛰고 있었다.
- 머리 보충 대상을 "검색에 걸린 모든 별표"로 잡았더니 무관한 표(적합성평가 시험수수료, 한-인니/한-베트남 상호인정협정)까지 붙었다. **상위 5위 이내**로 좁혔다. 또 개수 상한을 먼저 걸어서 이미 충족된 별표가 자리를 차지하고 정작 필요한 별표27이 잘렸다 — **"빠진 것만 추린 뒤 상한"** 순서로 바로잡았다.

**결과**(실측): "변경신고 금액" 질문에 별표12 4청크(3,344자)가 붙고 `그 밖의 무선국 … 8천원`이 들어간다. 전파사용료 질문엔 별표8·9, 항행안전 질문엔 812청크 별표가 상한에 걸려 10,027자로 끊긴다(그냥 넣었으면 65만 자). 뉴스 질문·별표 인용 없는 질문은 0자. 인출 자체는 0~815ms.

**교훈**: RAG가 조각 단위로 자르는 순간 **"이 조각이 가리키는 다른 조각"이라는 관계가 끊긴다.** 검색 점수를 올리는 것으로는 이 관계를 복원할 수 없다 — 인용은 확률이 아니라 규칙이기 때문이다. 그리고 *기각할 때도 재보고 기각한다* — B안을 "안 될 것 같다"로 접었으면 근거 없는 판단이 될 뻔했다.

---

## 44. 같은 뉴스가 텔레그램 수십 통·브리핑 6건 중복 — 사건 단위 중복 제거 (2026-08-01)

**증상(운영자 보고)**: KT 540억 과징금 하나로 ①Daily Briefing에 같은 내용이 긴급 6건으로 따로따로 실리고 ②며칠간 텔레그램 알림이 수십 통 왔다.

**실측**: 「KT 과징금」 긴급 분류가 7/30 하루 261건, 8일간 339건. 게다가 두 사건(개인정보위 해킹 540억 / 공정위 5G 과장광고 139억 소송)이 섞여 있었다.

**원인 — 세 경로 모두 '기사 단위'로만 동작했다.**
- 텔레그램: 매시 크롤에서 "새로 수집된 긴급 기사"면 무조건 알림. 이미 알린 사건인지 안 봄 → 언론사별 재보도가 매시간 새 알림.
- 브리핑: 24h 기사 60건을 Haiku에 주며 "같은 주제 1건만"을 **프롬프트로만** 지시 → 261건 폭증일에는 조회 60건 중 55건(91%)이 한 사건이라 지시가 무력화. **다른 뉴스가 브리핑에서 통째로 밀려난 것**이 더 큰 손해였다.
- 대시보드 뉴스 탭만 `_groupNews()` 클러스터링이 있었다(그래서 화면에선 묶여 보였고, 운영자도 "뉴스 탭처럼 되어야 하지 않나"로 발견).

**설계 — API 비용 0, 제목 키워드 기반, 공용 유틸 `news_dedup.py`.**

핵심 파라미터는 전부 8일치 긴급 381건 리플레이로 정했다:
- **공유 키워드 임계 3**: 2로 낮추면 두 KT 사건이 'KT+과징금' 2개 공유로 한 사건 취급 → 두 번째 사건 첫 알림이 삼켜짐(실측 확인). 3이면 사건은 갈라지고 재보도는 잡힘.
- **별-형 클러스터링(전이 없음)**: 전이 연결은 "540억 이어 5G 소송도 패소" 같은 **다리 기사**가 두 사건을 한 묶음(실측 261건)으로 이어버려 브리핑에서 사건 하나가 사라진다. 별-형은 과소 병합(사건이 국면별 ~8묶음)이지만, 30개 대표 목록이면 기존 프롬프트 지시가 감당한다 — **입력에 없는 걸 프롬프트로 복구할 수는 없으니 과소 병합 쪽이 안전**.
- **국면 신호 단어**(소송·고발·상고·행정처분…): 새 제목에 처음 등장(비교 상대 제목엔 없음)하면 억제 해제. "제목은 같고 본문에만 새 내용" 한계의 안전판. 그 국면 2일차부터는 상대 제목에도 있으니 다시 조용해진다. 리플레이에서 [속보]고발·행정소송·소송패소 10건이 이 규칙으로 살아남았다 — 전부 진짜 새 국면이었다.
- **키워드 확장**: 대시보드 `_extractKeywords()`는 한글만 추출해 **KT·5G 같은 영문 토큰을 아예 못 봤다**. 이식하며 영문 토큰과 금액 정규화(539억원→539억)를 추가.

**적용.**
- `crawler.py suppress_repeat_alerts()`: 최근 3일 내 DB에 있던 긴급 기사와 유사 → 알림만 생략(수집·브리핑·대시보드·자문은 그대로). 같은 실행분 안에서도 대표 1건+`(관련 보도 N건)`. 억제 내역은 `alert_suppress_log`에 저장 — **1~2주 실측 후 "본문에만 새 내용" 놓침이 실제 있으면 그때 Haiku 판정 층(월 2~6$)을 얹는다**(추측으로 미리 만들지 않음).
- `morning_briefing.py cluster_briefing_items()`: 조회 60→300건으로 늘리고 별-형 대표 1건+관련 건수로 압축해 Haiku에 입력. 전일(24~72h) 기사와 유사한 묶음엔 `〔전일 기보도 이어짐〕` 꼬리표 — 빼버리면 "왜 브리핑에 없지?"가 되므로 표시 방식 채택(운영자 승인).
- 둘 다 **fail-open**: 판정 코드가 죽으면 전부 알림/원본 그대로. 억제 기능 장애가 알림 장애로 번지면 안 된다.
- 긴급도 분류 데이터는 손대지 않았다 — 후속 보도 자동 강등은 "행정소송 제기" 같은 진짜 새 국면을 놓칠 위험이 있어 표시·알림 층에서만 억제.

**리플레이 결과(8일 381건)**: 알림 381→33건, 텔레그램 66→23통. KT 사건은 국면당 1통(예고→심의→결정·고발→행정소송→5G소송 별건). 브리핑 입력은 278건→30묶음, 대표에 "관련 보도 180건" 병기.

**교훈**: ①알림·요약·화면이 같은 데이터를 쓰면 **중복 제거도 같은 정의를 써야 한다** — 한 곳(대시보드)에만 있던 로직이 결국 공용 유틸로 갔다. ②LLM 프롬프트 지시("중복 제외")는 입력이 오염되면 무력하다 — **결정적 전처리가 프롬프트 지시보다 앞서야 한다**. ③임계값·방식은 감이 아니라 실데이터 리플레이로 정한다 — 임계 2였으면 사건이 삼켜졌고, 전이 연결이었으면 브리핑에서 사건이 사라졌다.

---

## 45. 야구 기사가 `3G`로 계속 들어오던 문제 — 단어 목록에서 패턴으로 (2026-08-01)

운영자가 "야구 뉴스인데 `3G`라는 단어가 들어가니 계속 뜬다"고 알려 왔다. 삭제 이력을 보니 7/26~31 사이에 손으로 지운 것이 25건, 대부분 KBO·축구 기사였다.

**원인 — 제외 목록이 엉뚱한 것을 쫓고 있었다.** `crawler.py`에는 이미 야구 제외어가 40개 넘게 있었다(`득점`·`이닝`·`타석`·`무실점`·선수 이름…). 그런데 실제로 빠져나온 제목들을 보면 **그 단어가 하나도 없다**:

> `3G 연속포`, `3G 연속 대타`, `3G 연속 QS`, `3G 8타점`, `3G 무패`, `3G 연속골`, `3G 모두 QS`

스포츠 기사가 `3G`를 쓰는 방식은 `3G + 기록어`로 정해져 있는데, 목록은 선수 이름과 일반 야구 용어만 나열해 왔다. **새 선수·새 표현이 나올 때마다 뚫리는 구조**였다. `LTE`도 같은 문제로, 지역 MBC가 실시간 리포트 코너명으로 `[LTE]`를 쓴다.

**조치 — `is_sports_noise(title, url)` 신설.** 단어를 더 쌓는 대신 세 가지 패턴으로 판정한다:
- **`3G`/`6G` 바로 뒤에 기록어**(연속·무패·타점·골·QS·보살…) — 통신 기사에는 이 조합이 없다.
- **`[LTE…]` 대괄호 코너 표기** — 방송 코너명.
- **`sports.naver.com` / `entertain.naver.com` 도메인** — 가장 확실하다. 삭제 이력 25건 중 12건이 이 두 곳이었다.

**운영자가 먼저 물은 것이 검증의 핵심이었다.** "이렇게 했을 때 지금 뉴스에 잡힌 것 중 빠지는 기사는 없나?" — 그래서 넣기 전에 DB 전체로 대조했다. `3G`/`LTE`가 든 기사 14건 중 스포츠 2건만 걸리고 **통신 기사 12건은 전원 통과**, 특히 진행 중인 **`3G 종료` 이슈 7건이 모두 통과**했다(`3G 종료`·`LTE 20배`·`LTE-R`은 패턴에 안 걸린다). 전체 721건으로 넓혀도 걸리는 것은 그 야구 2건뿐이었다.

**테스트가 구멍 두 개를 잡았다** — 첫 구현을 삭제 이력 60건에 걸어 보니 `[LTE/리포트]`(대괄호 안 변형)와 `홍명보호 3G 2골`(숫자가 끼는 표기)이 빠져나갔다. 정규식을 `\[\s*LTE\b[^\]]*\]`와 `\b[36]G\b\s*\d*\s*(기록어)`로 넓혀 둘 다 막았다. `2G/3G 종료`는 숫자 뒤가 `G`라 기록어에 안 걸려 여전히 안전하다.

**결과**: 삭제 이력 60건 중 25건이 앞으로 자동 차단, 현재 뉴스 721건 중 오탐 0건. 남아 있던 야구 2건은 대시보드와 같은 순서(`deleted_news` 기록 → `news_feed` 삭제)로 정리했다.

**교훈**: **오탐 목록이 길어지고 있다면 목록이 틀린 게 아니라 접근이 틀린 것이다.** 단어를 쫓으면 새 표현마다 뚫리고, 표기 패턴과 출처 도메인을 보면 한 번에 막힌다. 그리고 필터를 넣기 전에 **"지금 통과하고 있는 것 중 빠지는 게 있나"를 실데이터로 대조**해야 한다 — 잡아내는 능력보다 잘못 거르지 않는 것이 중요하고, 그 확인은 운영자가 먼저 요구했다.

---

## 46. 과거 브리핑 재생성 + 기술 용어 상세 자동 생성 (2026-08-01)

**둘 다 "이미 만든 것을 나중에 고치는" 작업이라 묶어 기록한다.**

### ① 과거 Daily Briefing 재생성

#44로 클러스터링이 들어갔지만 **이미 저장된 과거 브리핑은 그대로**였다. 7/31 브리핑을 열어 보면 같은 KT 과징금이 3건 연속으로, 각각 SKT 영향 분석까지 붙어 있었다.

**재생성 가능 범위는 뉴스 보관기간이 정한다.** 브리핑은 59건(6/1~7/31) 있지만, 뉴스는 7/31에 60일로 늘리기 전까지 15일 보관이라 **7/15 이전 기사는 이미 삭제**됐다. 재생성 가능한 것은 7/16~7/31 16일치뿐이고, 그중 실제로 중복이 있어 다시 만든 것은 11일이다(나머지는 기사가 1~8건이라 클러스터링해도 그대로).

`regenerate_briefings.py` 신설. `morning_briefing`의 `cluster_briefing_items`·`generate_briefing`·`add_urgent_analyses`를 그대로 import해 쓴다 — 로직을 복제하면 본편과 갈라진다. **원본은 `daily_briefings_backup`에 먼저 넣고 덮어썼다**(운영자 선택). 원본 앞머리의 📢 입법예고 섹션은 `law_amendments`를 다시 조회하지 않고 **원본에서 잘라내 새 본문 앞에 다시 붙인다** — 재조회하면 당시 시점과 달라진다.

**첫 실행에서 날짜 버그가 드러났다.** 재생성한 7/31 브리핑 머리에 **`2026년 08월 01일`**이 찍혔다. `generate_briefing()`이 `datetime.now(KST)`로 날짜를 만들기 때문. 같은 이유로 `cluster_briefing_items()`의 전일 꼬리표 창(24~72h 전)도 '오늘' 기준이라 엉뚱한 날과 비교하고 있었다. 두 함수에 `for_date` 인자를 추가하고(미지정 시 오늘 — 운영 경로는 그대로), 백업에서 복원한 뒤 다시 돌렸다.

**같은 사건이 2~3건씩 선택되는 것도 남아 있었다** — 별-형 클러스터링의 과소 병합(#44) 때문에 `KT 540억`·`KT 539억`이 다른 묶음으로 들어가고 Haiku가 둘 다 골랐다. 프롬프트에 *"(관련 보도 N건)이 가장 큰 1건만 넣고 나머지는 버릴 것"*을 추가해 해결했다. 이 지시는 운영 경로에도 함께 적용된다.

**결과**: 11일 재생성. 7/31은 기사 278건 → 30묶음, 과징금 항목 3건 → 1건(`관련 보도 180건` 병기), 4,137자 → 3,687자. 날짜도 정상.

### ② 기술 용어 상세 자동 생성

용어는 뉴스에서 자동 추출되지만 **상세 설명·개념도는 운영자가 항목을 클릭해야** 생성됐다(`openTermsModal` → `generateTermDetail`). 열 때마다 수십 초를 기다려야 했다.

`generateTermDetail()`에서 DOM을 만지지 않는 순수부 `_fetchTermDetail(term, key)`를 뽑고, `autoExtractTermsIfNeeded()`가 신규 용어를 저장한 직후 `backfillTermDetails()`로 곧바로 채우게 했다. 삽입 시 `.select()`를 붙여 id를 받아 와야 이어서 생성을 걸 수 있다.

- **순차 실행** — 동시에 던지면 레이트리밋에 걸리고, 백그라운드라 빠를 이유가 없다. 한 건 실패해도 나머지는 계속(부분 성공 허용).
- **빈 응답이면 덮어쓰지 않는다** — 기존 값을 지우는 사고 방지.
- 과거에 실패했거나 자동화 이전에 들어온 빈 용어도 **하루 5건씩** 보충한다(한 번에 몰면 비용·시간이 튄다).

**결과**: 244개 용어 중 비어 있던 `EMI 저감`이 설명 998자·개념도 SVG 2,589자로 채워졌고, 이후 자동 추출된 신규 용어도 같은 경로로 처리된다.

**교훈**: **날짜를 쓰는 함수를 과거 데이터에 재사용할 때는 `now()`가 어디에 숨어 있는지부터 본다.** 재생성 첫 판이 통째로 틀린 날짜를 달고 나왔고, 화면으로 확인하지 않았으면 그대로 남았을 것이다. 그리고 *생성 로직은 화면에서 분리해 둬야 자동화가 붙는다* — `generateTermDetail`이 DOM과 얽혀 있어 그대로는 배치로 못 돌렸다.

---

## 47. ITU-R 영문 원문이 한국어 질문에 안 잡히던 문제 — 한국어 요약 등재 (2026-08-01)

운영자가 "지식 베이스의 ITU-R 문서 역할이 무엇인가"를 물었고, 답하면서 사용 실적을 세어 보니 **자문 28건 중 ITU-R을 인용한 것은 1건**뿐이었다. 원인을 추정만 하고 넘길 뻔했으나 운영자가 *"네가 한번 재봐"* 라고 해 실측했다.

**실측 1 — 실제 검색 6개 질문.** 영문 약어가 질문에 들어가면 잘 잡혔다(`IMT-2030 유스케이스` 2~8위, `5G 무선 인터페이스 국제 규격` 3~8위). 반면 **순수 한국어 기술용어는 0건**이었다 — `불요발사 허용 기준은?`, `스퓨리어스 발사 한계값`.

**실측 2 — 유사도 직접 측정**(SM.329 본문 청크, 임계값 0.45):

| 질의 | 유사도 | 통과 |
|---|---|---|
| `spurious emission limits` (영문) | 0.563 | ✓ |
| `unwanted emissions in the spurious domain` (영문) | 0.503 | ✓ |
| `스퓨리어스 발사 한계값` (한글) | 0.375 | ✗ |
| `불요발사 허용 기준은?` (한글) | 0.286 | ✗ |

**측정 중 한 번 헛짚었다** — 처음에 뽑은 청크가 본문이 아니라 표지·머리말(`Radiocommunication Sector are performed by World and Regional…`)이어서 영문 질의마저 0.34로 떨어졌다. 청크 내용을 눈으로 확인하고 Scope 청크로 다시 잡아 재측정했다. **샘플이 대표성 있는지부터 볼 것.**

**한글 머리말 방안은 실측으로 기각.** #43에서 배운 대로 먼저 재봤다: 머리말을 붙여 재임베딩해도 `스퓨리어스 발사 한계값` 0.375→0.384, `불요발사 허용 기준은?` 0.286→0.304로 **둘 다 0.45 미달**. 한 줄로는 언어 간 거리를 못 좁힌다.

**추천을 한 번 정정했다.** 처음에 "질의 확장에 한↔영 용어쌍 추가"(비용 0)를 추천했으나, 운영자가 *"8개 문서 요약보다 1번을 추천하는 이유는?"* 이라고 되물었고 답을 쓰다 보니 근거가 약했다 — 용어쌍은 **등록한 단어만 통하고 새 표현마다 뚫린다.** 같은 날 아침 야구 필터(#45)에서 *"목록이 길어지면 접근이 틀린 것"* 이라고 써 놓고 같은 구조를 추천한 셈이었다. 싸고 빠른 것을 효과가 확실한 것처럼 제시한 것이 잘못이었다.

**채택 — 한국어 요약을 kb 레이어에 등재.** `regulatory-kb/references/itu-r/` 6건(M.2160·M.1036·M.2150·SM.329·SM.1541·M.1544), 35청크. **요약은 API를 쓰지 않고 세션에서 직접 작성**했다(일회성 생성은 세션으로 — 운영자 선호). 각 문서의 Scope·약어표·본문 청크를 실제로 읽고 썼으며, 한↔영 용어 대응표(불요발사=unwanted emission, 스퓨리어스=spurious 등)를 본문에 넣어 어느 표현으로 물어도 걸리게 했다.

**설계 원칙**: 요약은 *찾아가는 다리*이고 **인용은 영문 원문에서** 한다. 각 요약 앞머리와 말미에 "수치·표는 영문 원문 참조"를 명시했다 — 별표 동반 인출(#43)과 같은 구조다.

**결과**(실측):

| 질문 | 개선 전 | 개선 후 |
|---|---|---|
| 불요발사 허용 기준은? | 0건 | **1·2위** |
| 스퓨리어스 발사 한계값 | 0건 | **1~5위** |
| 6G 성능 요구사항은 무엇인가 | 11위 1건 | **1~5위** |
| IMT 주파수 대역 국제 배치 현황 | 10~12위 | **1~3위** |
| 대역외 발사 마스크 국제 기준 | — | **1~4위** |

**회귀 없음**: 국내 실무 질문 3종(무선국 검사 수수료·기간통신 등록요건·전파사용료 감면)에서 ITU-R 요약이 **한 건도 섞이지 않았고**, kb 상위는 그대로 국내 문서였다. `IMT-2030 유스케이스`에서 영문 조문 원문 6건도 여전히 잡힌다 — 요약이 원문을 밀어내지 않았다.

**교훈**: ① *추천에는 "싸다"와 "효과 있다"를 구분해 적을 것* — 운영자가 되묻지 않았으면 약한 안이 그대로 갔다. ② 유사도를 잴 때는 **대표성 있는 청크인지 먼저 눈으로 볼 것**(표지 청크로 재면 결론이 뒤집힌다). ③ 언어가 다른 문서는 어휘 매핑이 아니라 **그 언어로 된 요약을 나란히 두는 것**이 답이다.

---

## 48. 대시보드 삭제 버튼이 아무 일도 하지 않던 문제 — RLS + PostgREST 무성 실패 (2026-08-01)

운영자가 `추가 지식 입력` 탭에서 김호영 박사논문(247청크, 임베딩 완료)의 삭제 버튼을 눌렀는데 **아무 일도 일어나지 않았다.** 오류 메시지도 없었다.

**원인 — 두 층이 겹쳐 실패를 숨겼다.**
1. `document_chunks`는 RLS가 켜져 있는데 정책이 `SELECT`·`INSERT` 둘뿐이고 **`DELETE` 정책이 없다.** RLS는 정책이 없는 명령을 "대상 0행"으로 처리한다.
2. **PostgREST는 이를 오류가 아니라 성공(0건 삭제)으로 응답한다.**

그래서 `onDeleteCustomFile()`의 `if (error) throw` 가드를 그대로 통과하고, 목록만 다시 그려져 "안 지워졌다"로만 보였다. **동작은 실패했는데 실패라고 말해 주는 창구가 없다** — #35(뉴스 반영)·#41(kb 배지)과 같은 부류이며, 이번 세션에서만 세 번째다.

**같은 상태가 `chat_logs`(자문 이력 삭제)에도 있었다.** 전수 점검 결과: RLS 켜짐+DELETE 정책 없음은 `document_chunks`·`chat_logs` 둘, `news_feed`·`custom_knowledge`는 RLS 자체가 꺼져 있어 정상, `report_samples`·`report_directives`는 DELETE 정책이 있어 정상.

**조치 — 관리자 RPC 2종 신설.** `admin_delete_kb_document`와 같은 패턴(`security definer` + sha256 비밀번호 검증):
- `admin_delete_custom_file(p_doc_name, p_pwd)` — **카테고리 조건 필수**(`doc_category='추가지식'`). 기존 `admin_delete_kb_document`는 `doc_name`만 보고 지우므로 다른 카테고리의 동명 문서를 함께 날릴 수 있다.
- `admin_delete_chat_log(p_id uuid, p_pwd)`

**anon DELETE 정책은 만들지 않았다** — 대시보드가 공개 URL이라 누구나 청크를 지울 수 있게 된다.

**핵심은 반환값이다.** 두 함수 모두 `GET DIAGNOSTICS … ROW_COUNT`로 **삭제 행수를 반환**하고, 프런트가 `if (!res.data)` 로 0을 실패 처리한다. RPC로 바꾸기만 하고 이 가드를 안 넣으면 같은 무성 실패가 다른 이유로 재발한다.

**세 번째 자리도 함께 고쳤다.** `app.js`의 파일 재업로드 경로에 `document_chunks` 직접 delete가 하나 더 있었다("기존 동일 문서명 청크 삭제"). 이것도 조용히 실패하고 있었으므로 **같은 이름으로 재업로드하면 옛 청크가 남아 중복 누적된다.** 실측으로 피해 여부를 확인했더니 `chunk_index` 중복은 0건이었다 — 아직 같은 이름으로 재업로드한 적이 없어 터지지 않았을 뿐이다. `admin_delete_kb_document` 호출로 교체했다.

**교훈**: **"오류가 없었다"는 "성공했다"가 아니다.** ORM·API 계층이 권한 실패를 빈 결과로 바꿔 놓는 조합이 있고, 그때는 **영향 행 수를 확인하는 것만이 유일한 검증**이다. 삭제·갱신처럼 부수효과가 목적인 호출은 반환된 행 수를 반드시 확인할 것.

---

## 49. ITU-R 라벨 오류 정정 + 문서 3건 추가 + 개정 감시 (2026-08-01)

운영자가 `ITU-R 문서` 탭을 보고 *"6개로 충분한가, 주기적으로 개정 확인은 안 되나"* 를 물으면서 시작됐다.

**① 화면과 시스템 프롬프트가 틀린 정보를 주고 있었다.** `M.1544-1`이 **"IMT 최소 성능 요구사항"** 으로 표기돼 있었는데, ITU 공식 목록 확인 결과 실제로는 *Minimum qualifications of radio amateurs*(아마추어무선 종사자 자격기준)다. 진짜 "IMT 최소 성능 요구사항"은 **Report ITU-R M.2410-0**이며, 번호를 착각해 엉뚱한 문서가 올라온 것으로 보인다.

`index.html` 라벨보다 **`system_prompt.js`가 더 심각했다** — 자문 모델에게 직접 `M.1544-1(IMT성능)`이라고 가르치고 있었다. 화면은 사람이 의심할 수 있지만 프롬프트는 모델이 그대로 믿는다.

**② 보유 6건은 전부 현행판이었다.** M.1036-8·M.2160-0·SM.329-13을 ITU "In force" 판과 대조 — 구판 인용 위험은 없었다.

**③ 자동 갱신은 법령과 조건이 다르다.** ITU-R PDF 원문에 *"All rights reserved. No part of this publication may be reproduced, by any means whatsoever, without written permission of ITU"* 가 박혀 있다(M.1036·M.2150·M.2160에서 확인). 법령이 자동 갱신되는 건 기술이 좋아서가 아니라 **공공누리가 허용해서**다. 따라서 **감지는 자동, 수집은 사람**. 처음엔 근거 없이 "권하지 않는다"고만 했다가 운영자가 확인을 요구해 조사한 결과다 — *판단이 맞아도 근거 없이 말하면 안 된다.*

### 추가한 3건과 뺀 후보

| 문서 | 용량 | 청크 | 이유 |
|---|---|---|---|
| Report M.2410-0 | 644 KB | 33 | 5G 최소 성능(하향 20 Gbit/s, URLLC 1 ms). 화면 라벨이 이미 이걸 가리켰는데 정작 없었다 |
| M.2083-0 | 903 KB | 76 | IMT Vision(5G 프레임워크). M.2160(6G)의 짝 — 비교 설명에 필수 |
| M.2101-0 | 1.27 MB | 97 | 공유·양립성 모델링. WRC 대역 논의의 방법론 근거 |

**뺀 후보**: M.1457(3G 규격, 52MB·약 9,000청크 — 3GPP 참조 목록이 대부분이고 "3G 종료"는 전기통신사업법 제19조 문제라 안 걸린다), Report M.2292(M.2101과 주제 중복·2013년판).

**삭제는 하지 않았다.** 운영자가 *"필요 없어서 삭제할 것은 없나"* 를 물어 실측 검토했으나 근거가 없었다 — M.2150은 2,210청크(70%가 URL·3GPP TS 참조 목록)지만 국내 질문 3종에서 **0건** 잡혀 검색을 오염시키지 않는다. M.1544는 관련성이 낮지만 9청크뿐이라 지워도 얻는 게 없다. **사용 실적(28건 중 1건 인용)을 삭제 근거로 쓰지 않은 이유**는 그 낮은 실적이 #47에서 방금 고친 언어 불일치 탓이었기 때문이다 — 고치기 전 데이터로 판단하면 틀린다.

### 한국어 요약도 함께 (일관성)

#47에서 기존 6건에 한국어 요약을 붙였으므로 추가 3건도 같은 처리를 했다. 안 하면 새 문서가 한국어로는 안 잡힌다. 요약은 **API 없이 세션에서 원문(Scope·약어표·본문 청크)을 읽고 직접 작성**했고, 한↔영 용어 대응표를 본문에 넣었다(공유 연구=sharing study, 양립성=compatibility 등).

**검증**(kb 검색 순위):

| 질문 | 결과 |
|---|---|
| 5G 최소 성능 요구사항은? | M.2410 **1~5위** |
| IMT 비전 5G 목표 성능 | M.2410·M.2083 **1~5위** |
| 양립성 연구 시뮬레이션 방법론 | M.2101 **1~5위** |
| 5G 최대 전송속도 국제 기준 | M.2410 **1~5위** |
| 주파수 공유 간섭 분석 방법 | ITU 0건 — **정상**. `주파수 공유`가 국내 「주파수 공동사용」과 겹치는 말이라 국내 고시가 잡혔고 그게 맞는 답 |

**회귀 없음**: 국내 실무 질문 3종에 ITU 요약 **0건** 혼입, kb 상위는 국내 문서 유지. 조문 RAG도 신규 영문 원문(M.2410 5건)·기존(M.2160 9건) 모두 정상.

### 개정 감시 — `itu_rec_watch.py`

ITU 권고 페이지가 `In force (Main)` / `Superseded`로 현행판을 표시하므로 이걸 파싱해 보유 판과 대조한다. 월 1회 GitHub Actions(매월 1일 12시 KST) — itu.int는 해외 IP 차단이 없어 PC가 꺼져 있어도 된다.

**조사에서 나온 결정적 함정 — ITU WAF는 실패를 두 가지 방식으로 숨긴다**(실측):

| User-Agent | 결과 |
|---|---|
| `python-requests` 기본 / `curl` / 정직한 식별 UA | ✅ 정상 200, 1.1초 |
| `Mozilla/5.0` (짧은 봇 시그니처) | ❌ **HTTP 200인데 본문이 `Request Rejected`** |
| 완전한 Chrome UA 문자열 | ❌ **연결 블랙홀 — 25초 타임아웃, 재시도 전부 실패** |

**위장할수록 막힌다.** 그리고 **`status_code`를 믿으면 안 된다** — WAF 거부가 200으로 온다. 이 검사가 없으면 차단당한 실행이 *"8건 조회 성공 / 개정 0건"* 으로 멀쩡해 보인다. 이 프로젝트에서 반복된 무성 실패(#35·#41·#48)와 같은 함정이라, 스크립트에 세 겹의 방어를 넣었다:
1. 본문에 `Request Rejected`가 있으면 실패로 집계
2. 로그에 `감시 대상 N건 / 조회 성공 M건 / 개정 K건 (조회 실패 L건)` 필수 출력
3. **조회 전량 실패 시 텔레그램 경고 발송** — "개정 0건"과 "감시가 죽음"을 절대 같게 취급하지 않는다

**dry-run 실측**(감시 대상 8건 전부 정상):
```
[제외 합계] 3건 (Report 1 / 형식불일치 2)
[감시 대상] 8건
  [최신] M.1036 -8 = -8   [최신] M.1544 -1 = -1
  [최신] M.2083 -0 = -0   [최신] M.2101 -0 = -0
  [최신] M.2150 -3 = -3   [최신] M.2160 -0 = -0
  [최신] SM.1541 -7 = -7  [최신] SM.329 -13 = -13
[요약] 감시 대상 8건 / 조회 성공 8건 / 개정 0건 (조회 실패 0건)
```

감시 대상은 **DB에서 읽어 하드코딩하지 않는다** — 이번에 추가한 M.2083·M.2101이 자동으로 목록에 들어온 것이 그 증거다. Report(R-REP)는 URL 체계가 달라 제외하고, 제외 건수를 로그에 남긴다. `.range()` 페이지네이션도 넣었다(ITU 청크가 1000을 넘으면 감시 목록이 조용히 잘린다).

**남은 위험**: GitHub Actions 러너(해외 데이터센터 IP)를 ITU WAF가 PC와 같게 대할지는 로컬에서 검증할 수 없다. 그래서 위 3번 방어가 필수다 — 러너가 차단되면 조회 성공 M이 0으로 떨어지고 경고가 오므로, 실패가 "개정 없음"으로 위장되지 않는다.

**교훈**: **화면 라벨과 시스템 프롬프트에 든 사실은 데이터만큼 검증 대상이다.** 하드코딩된 설명은 아무도 다시 안 보므로 틀린 채로 오래 남고, 프롬프트에 있으면 모델이 그걸 사실로 답한다. 그리고 *삭제 판단은 최근에 고친 문제의 영향을 받은 데이터로 하지 않는다.*

---

## 50. `국내 법령·고시` 목록에 논문·보도자료가 섞여 있던 문제 (2026-08-01)

운영자가 *"국내 법령/고시에 왜 추가 지식에 입력한 논문 등의 내용이 들어가 있나"* 를 물었다.

**원인 — 제외 목록 방식이었다.** `loadKbDocs()`의 필터가 두 줄뿐이었다:

```js
if (r.doc_category === 'ITU-R') return false;
if (/^\d{6}/.test(r.doc_name)) return false;   // 날짜 파일명 = 보도자료
return true;                                    // 나머지 전부 통과
```

즉 목록이 "법령·고시만"이 아니라 **"ITU-R과 날짜파일 빼고 전부"** 였다. `추가지식`·`보도자료` 카테고리를 안 걸러 **9건이 섞였다**:
- 추가지식 5건 — 논문 2편, 근거메모, 김호영 박사논문, 세미나 자료
- 보도자료 4건 — `과기정통부_보도자료_2023~2026.md`. 날짜 규칙(`^\d{6}`)이 `240717` 형태만 잡아 접두가 다른 이 4건은 통과했다.

제목으로 그룹을 나누다 보니 **제목에 `전자파`가 든 논문 2편이 `전자파 행정규칙` 그룹에 끼어** 보였다. 앞선 검색 실측에서 이미 눈에 띄었는데 그때는 지나쳤다.

**조치**: 카테고리 기준으로 `추가지식`·`보도자료`를 명시적으로 제외. 각자 전용 탭이 이미 있다.

**중요 — 화면에서만 뺐고 자문 RAG는 그대로 둔다.** 논문·메모는 실제로 유용한 근거이고(`5G 기지국 성능` 질문에서 상위 1~3위로 잡힌다), 목록 표시와 검색 대상은 별개 문제다.

**결과**: 목록 174 → 165건, 섞임 0건. `전자파` 검색 결과 9건이 전부 고시로만 채워졌다(이전엔 논문 2편 포함).

**반대로 손대지 않은 것**: `기타` 카테고리 32건은 이름과 달리 대부분 진짜 고시·훈령·예규다(무선국 운용 규정, 주파수 공동사용 기준, 전파관리 처리 세칙 등). 업로드 시 카테고리를 세분하지 않아 `기타`로 들어갔을 뿐이므로 목록에 있는 게 맞다.

**교훈**: **"무엇을 뺄까"가 아니라 "무엇을 넣을까"로 짠 필터가 안전하다.** 제외 목록 방식은 새 카테고리가 생길 때마다 조용히 새는데, 아무도 목록을 다시 세어 보지 않아 오래 남는다. 같은 날 야구 필터(#45)에서 배운 "목록을 쫓지 말라"와 같은 이야기다.

---

## 51. 텔레그램 구독 봇 신설 — 정시 발송·조문 조회·AI 자문 (2026-08-01)

운영자가 pr-agent.net을 보고 *"이런 식으로 텔레그램에 구현할 수 있게 계획해줘"* 라고 요청했다.
`/start`를 치면 인라인 키보드가 뜨고 원하는 시각에 리포트가 오는 UX였다.

### 왜 두 번째 봇인가

기존 봇(`TELEGRAM_BOT_TOKEN`)은 운영자 1명에게 **일방적으로 밀어 넣는** 용도다. 구독 봇은
아무나 `/start`를 칠 수 있어야 하므로 **수신(webhook)** 이 필요하고, 잘못 건드리면 운영자
알림 경로가 함께 망가진다. BotFather로 `정책AI 도우미`(@radio_policy_law_ai_bot)를 새로 만들어
완전히 분리했다. 기존 봇 코드는 한 줄도 손대지 않았다.

### 구조 — 왜 큐인가

처음엔 긴급 뉴스를 **즉시** 보내려 했다. 그런데 운영자가 *"긴급 뉴스는 24시간 운영되니
끝나는 시간을 정해야 하지 않나"* 라고 물었고, 이어서 *"브리핑/긴급뉴스/법안동향 받는 시간"*
으로 **3종 공통 수신 시각**을 요구했다. 즉시 발송이 사라지자 설계가 오히려 단순해졌다.

- 크롤러(Python)는 **발송하지 않고 `subscriber_queue`에 적재만** 한다.
- 매시 도는 `send-subscriber-briefing`이 수신 시각이 된 구독자에게 브리핑+큐를 **한 번에** 보낸다.

큐를 둔 이유는 성능이 아니라 **판정 로직 중복을 피하기 위해서다.** 긴급 재알림 억제·클러스터링(#44)과
법안 상태변경 판정은 이미 Python에 있다. 발송 시점만 늦추려고 그 판정을 TS로 옮기면 두 벌이 되어
언젠가 어긋난다. 판정 결과(HTML)만 큐에 넣고 **발송 시점만** Edge Function이 정한다.

부수 효과로 '야간 무음' 토글이 불필요해졌다(밤에는 애초에 아무것도 안 나간다). 잠깐 만들었다가
같은 날 제거했다. **구독 해지 버튼도 없앴다** — 항목 3개를 다 끄면 결과가 같은데 상태만 둘이 되어
"어느 쪽으로 껐는지" 헷갈렸기 때문이다.

### `briefing_hour <= 현재시` — 등호가 아닌 이유

브리핑은 06:05에 하루 한 번 생성된다. 수신 시각을 정확히 비교하면, 브리핑이 06:20 재시도나
PC 백업으로 늦게 만들어진 날 06시 구독자는 **영영 못 받는다**. 부등호로 두면 다음 정각에 자동으로
따라잡는다. 대신 12시 수신자는 06~12시 뉴스가 빠져 보이므로 **브리핑 하단에 기준 시각을 표기**했다
("오늘 06:05 기준 — 이후 소식은 내일 브리핑에").

### 겪은 사고와 교훈

**① 시크릿에 줄바꿈이 딸려 들어가 401만 반복** — Supabase 콘솔에 값을 붙여넣을 때 메모장에서
줄 단위로 복사하면 끝에 `\n`이 붙는다. 콘솔에는 **등록돼 보이는데** 비교만 조용히 실패한다.
원인은 콘솔의 SHA256 다이제스트와 로컬 해시를 대조해 찾았다. 조치는 두 가지 — 값을 다시 넣게
하는 대신 **Edge Function의 env를 전부 `.trim()`** 했고(사람이 또 실수해도 통과), 이후 시크릿
생성은 `init_subscriber_secrets.py`가 파일로 뽑아 주도록 만들었다.

**② 자문이 통째로 실패** — `app_config.system_prompt`가 비어 있었다. `sync_system_prompt.py`를
만들어 놓고 **실행하지 않은 채** 배포했다. 대시보드는 `system_prompt.js`를 직접 읽으므로 멀쩡했고,
봇만 죽어 원인이 안 보였다. 프롬프트를 고칠 때마다 이 스크립트를 돌려야 한다는 것을 지침 do-not에 넣었다.

**③ `index.ts`를 0바이트로 날림** — Python으로 파일을 통째로 다시 쓰다가 `open(w)`가 truncate한
직후 인코딩 예외가 났다. 이 파일들은 아직 git에 없어서(untracked) 복구 수단이 **배포본뿐**이었다.
Management API의 `/functions/{slug}/body`(eszip)에서 소스를 긁어냈지만 그건 **트랜스파일된 JS**라
타입이 날아가 있어, 결국 MCP `get_edge_function`이 돌려준 원본 TS로 다시 썼다. 이후 편집은
**임시 파일에 쓰고 교체**하는 방식으로 바꿨고, 같은 날 로컬 커밋(`e6cf7fc` — #52 분리 재작성 후 해시)을 해서 git 밖에 있는
상태를 끝냈다. **교훈: 배포는 백업이 아니다.**

### `/law` 키워드 검색을 결국 들어낸 이야기

운영자가 `/law 3G 종료를 하는 방법`을 던졌을 때 개인정보·위치정보 시행령만 5건 나왔다.
네 차례 고쳤다.

1. 흔한 단어 **'방법'** 에 trgm이 끌렸다 → 불용어 추가
2. 질문 어휘("3G 종료")와 법령 어휘("휴업·폐업")가 아예 다르다 → Haiku 키워드 확장
3. 확장해도 못 맞혔다. **Sonnet 5로 바꿔도 마찬가지**였다(실측: 둘 다 '휴폐지'까지만) →
   `LAW_SYNONYMS` 대응표를 코드에 명시(`종료 → 휴업·폐업·폐지·휴지`)
4. 이번엔 「실행계획(안).pdf」가 상위를 채웠다. 그 PDF도 `article_no`("6조")를 갖고 있어
   조문번호 필터를 통과했다 → `.pdf`·`.md` 제외 + 조문 제목 가중치 ×5

그러고도 `기간통신사업폐지`에서 전기통신사업법 19조가 안 나왔다. 원인은 **정렬 없는 `limit 6`** —
PostgREST가 임의의 6건을 돌려주는데 거기 안 들어 있었다(limit 40이면 포함). 이걸 고치자 이번엔
'폐업'이 든 위치정보법·지방세법이 끼어들어, 행위(폐업)와 주제(기간통신사업)를 분리해 채점하는
구조까지 갔다.

여기서 운영자가 *"`/law` 기능을 없애고 `/ask`로 몰아 버릴까?"* 라고 물었고, 그게 맞았다.
같은 질문에 `/ask`는 이미 전기통신사업법 19조·전파법 16조·이용자보호계획·IoT 전환까지 정확히
답하고 있었다. **키워드 검색은 조문 조회의 열등한 사본이었을 뿐이다.**

- `/law` = **"OO법 N조" 원문 즉답**만 담당 (2~3초·비용 0·원문 그대로 — 이건 자문이 대체 못 한다)
- 자연어 질문 = `/ask` 안내로 전환
- 검색 로직은 버리지 않고 **`/ask`의 조문 보강**으로 남겼다. 거기서는 RAG·뉴스와 함께 쓰이므로
  한 갈래가 약해도 다른 갈래가 메운다.

**교훈: 고치는 횟수가 늘어나면 그 기능이 필요한지부터 다시 물어야 한다.** 네 번째 수정에서
이 질문을 먼저 했어야 했다.

### 자문에 뉴스를 넣은 이유

운영자가 *"최근 뉴스에 이용자 보호 때문에 정부가 신중하다는 뉴스가 있지 않았나?"* 라고 물었다.
DB를 뒤지니 관련 기사가 10건 있었다(SKT·KT 공식 건의, 과기정통부 "이용자 보호 최우선",
IoT 회선 34.6만이 변수). **그 기사들은 자문에 전혀 들어가지 않았다** — v1에서 뉴스 컨텍스트를
뺐기 때문이다. "3G 종료를 하는 방법"은 절차(법령)와 현실(정책 동향) 둘 다 필요한 질문인데
절반만 답하고 있었다. `app.js`의 `fetchRecentNewsContext`를 이식하고, 답변 지침에
"제도와 추진 상황이 둘 다 관련되면 반드시 함께 답하라"를 넣었다.

### 함께 고친 것

**방통위·ETRI·KISDI 수집 추가.** 대시보드 안내에는 이 세 기관이 적혀 있었는데 **실제로는 수집하지
않고 있었다**(`crawler.py`에 함수만 있고 `main()`에서 호출 안 함). 확인 과정에서 안내문의 다른
오류도 드러났다 — "매일 오전 8시"(실제 매시간), 매체 목록이 수집 대상인 것처럼 표기(실제로는
키워드 검색이라 제한 없음. 화면에 이미 목록 밖 매체가 4곳 떠 있었다).

**중앙전파관리소를 '방통위'로 표기하던 버그.** 기존 `crawl_kcc()`가 긁던 곳은 `kmcc.go.kr`
(중앙전파관리소)인데 출처를 '방통위'로 적고 있었다. 방통위는 `kcc.go.kr`로 따로 있다. 도메인
한 글자 차이라 오래 안 드러났다. `crawl_kmcc()`로 분리하고 출처를 정정했다.

방통위 보도자료는 재허가·이사 임명 등 **방송 거버넌스가 대부분**이라 전파 키워드로는 매칭이
0건이었다. 기술정책팀에 의미 있는 축(단말기·지원금·스팸·이용자보호)으로 `KCC_KEYWORDS`를 따로 뒀다.

**브리핑 제목 하이퍼링크화.** 운영자가 *"별도로 링크를 보여주지 말고 제목 자체가 하이퍼링크가
되도록"* 요청했다. 운영자 봇도 평문에서 HTML로 바꿨다(400 시 평문 폴백). 기사당 한 줄씩 줄어
4000자 제한에 여유가 생겼다. 이때 JS 정규식에서 `[🔴🟡🟢]` 문자클래스가 `u` 플래그 없이
서로게이트 페어를 쪼개 이모지가 깨지는 것을 발견해 교대(`|`)로 바꿨다.

### 배포 방식 전환

MCP로 파일 내용을 통째로 전송하는 방식은 **56KB에서 실패**했다. Supabase CLI + 액세스 토큰으로
바꿔 디스크에서 직접 올리도록 했다. 크기 제한이 사라졌고 배포가 수 초로 줄었다.

### 결과

- 봇 운영 중: 구독 설정(항목·요일·시각), `/law` 조문 조회, `/ask` 자문(승인제·일일 20회)
- `/ask` 이력은 대시보드 자문 이력에 `category='텔레그램'`으로 함께 쌓인다
- 정부기관 수집 3곳 추가 — 첫 실행에서 방통위 2건·KISDI 1건 저장 확인
  (ETRI 3건은 발행 15일 초과라 규칙대로 건너뜀 — 정상 동작)

---

## 52. 법령·고시 탭의 업로드 버튼 제거 — API가 더 정확하다 (2026-08-01)

운영자가 *"국내 법령/고시, ITU-R 문서는 자동 업데이트 되게 했으니 업로드 메뉴가 필요 없지 않나"* 라고 물었다. 조사해 보니 **두 탭의 답이 정반대**였다.

**ITU-R은 업로드가 유일한 수단이다.** 저작권상 PDF 자동 수집이 불가해(#49) 감지만 자동이고, 개정 알림을 받으면 사람이 받아 올리는 것 말고는 갱신할 방법이 없다. 버튼을 지우면 감시는 도는데 대응 수단이 사라진다.

**법령·고시는 반대다.** `law_sync.py` 첫 줄이 이유를 말한다 — *"PDF 다운로드·업로드가 필요 없다. API가 조문 구조(조문번호·제목·항·호)를 그대로 주므로 PDF 텍스트 추출보다 청킹·조문번호가 정확하다."* 즉 **PDF로 넣으면 오히려 `article_no`가 부정확해진다.** 실측으로도 현재 등재된 165건 전부가 스크립트 적재이고 **대시보드 업로드로 들어온 것은 0건**이었다 — 버튼은 있는데 한 번도 쓰이지 않았다.

**조치**: 법령 탭의 업로드 버튼을 안내 문구(`개정 감지 시 law_sync.py로 자동 현행화 · 업로드 불필요`)로 바꾸고, `law-upload-list`와 `app.js`의 `'law'` 컨텍스트 분기 3곳(`openPdfUpload` else절, 업로드 목록 추가, OKF 안내 문구)을 정리했다. 법제처 API에 없는 예외 문서(상호인정협정·정책자료)는 PC에서 `upload_law_pdf.py`로 넣는다 — 스크립트는 그대로 남아 있다.

**자동 현행화(`law_sync.py --all-outdated`)는 자동화하지 않았다.** 운영자가 검토를 요청해 코드를 읽고 세 가지 위험을 제시했다: ①보존 상한 초과분 **삭제가 무인으로 돈다**(오늘 RLS 삭제 무성 실패를 고친 직후라 더 조심스럽다) ②법제처 API가 동명이법을 집어오면 그대로 현행본이 된다 ③**OKF 요약이 자동으로 따라오지 않아** 조문만 새 판이고 요약은 옛 판을 설명하는 상태가 된다. ③이 결정적이라 보류했다. 하려면 `--dry-run` 보고 → 관찰 → OKF 자동화 → 실적용 순서를 밟아야 한다.

### 동시 세션 사고 — 커밋 오염과 번호 충돌 (푸시 전에 분리로 수습)

작업 중 **다른 세션(텔레그램 구독 봇)이 동시에 커밋**하면서, 아직 커밋하지 않은 이 변경의 `index.html` 부분(업로드 버튼 제거·안내 문구·`law-upload-list` 제거)이 봇 커밋에 함께 담겼다. 커밋 메시지는 "텔레그램 구독 봇"인데 diff에는 법령 업로드 버튼 제거가 들어 있는 상태 — 이력만 보면 왜 바뀌었는지 찾을 수 없다.

**푸시 전이었기에 이력을 재작성해 분리했다**(운영자 승인, 봇 세션 종료 확인 후). 봇 커밋에서 이 변경분을 떼어내 원상복구하고, 이 작업(#52)의 index.html + app.js + 문서를 한 커밋으로 합쳤다. 최종 이력에서는 각 커밋이 제 작업만 담는다. 재작성 전 상태는 `backup-before-split` 브랜치에 남겼다.

**교훈**: ①지침의 *"`git add <명시적 파일명>`만 쓰고 `git add -A`를 쓰지 말 것"* 은 **다른 세션의 미커밋 작업까지 쓸어 담는 것**을 막기 위한 규칙이기도 하다. ②**여러 세션이 동시에 작업하면 배경역사 번호가 충돌한다** — 이번에도 양쪽이 `#51`을 잡아 코드 주석 3곳을 `#52`로 정정해야 했다. 번호를 쓰기 전에 `grep -c "^## NN\." 배경역사.md` 로 선점 여부를 확인할 것. ③이런 수습(이력 재작성)은 **푸시 전에만 안전하다** — 푸시 후였다면 섞인 채로 문서에만 기록하는 것이 맞다.

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

## 53. 정부 보도자료 자동 수집 구축 — 6개 기관 백필·AI 판정·프루닝 (2026-08-02)

**배경.** 지식베이스 '정부 보도자료' 탭(수동 업로드 136건)은 5월 24일 이후 멈춰 있었다. 운영자
지시: 모니터링 탭은 60일 롤링 유지, 지식베이스는 영구 누적, 두 화면 모두 기관 탭, 2024년부터
6개 기관(과기정통부·전파연구원·방통위·전파관리소·ETRI·KISDI) 자동 재수집, **기존 수동분 전량
삭제 후 재구축**, 수집 키워드는 대시보드에서 편집 가능하게 + `AI` 추가.

**구축.** 공용 모듈 `press_ingest.py`(기관 어댑터·본문 추출기 3종·등재·dedupe) +
`press_backfill.py`(일회성). 청크 형식은 기존 수동분과 동일(700자 무겹침, `## YYMMDD 제목` 섹션,
문서 프리앰블)로 맞춰 대시보드 파서를 그대로 살렸고, 섹션 끝에 `(원문: URL)`을 남겨 상세 모달의
'원문 보기' 버튼이 됐다. gov_notice_crawler(매일 17시) 말미에 `run_daily()` + 임베딩 자동 백필을 연결.

**결과 수치.** 2024-01~2026-08 백필 + 세션 검토 프루닝 후 **1,027건 / 5,962청크, 임베딩 누락 0**.
기관별(프루닝 전 수집): 과기정통부 902(백필 787+델타 115), 방통위 100, ETRI 92, KISDI 56,
전파연구원 41, 전파관리소 20. 실패는 이미지-전용 첨부 2건뿐.

**수집 방식의 진화(운영자 결정 순서).** ① 처음엔 제목 키워드 매칭(21→33개로 확장: 통신정책 축
7개 + 위성통신·통신품질·알뜰폰 + 인공지능 + 통신이용자). ② "제목은 무관해 보여도 본문은 관련"
사례(정보통신전략위 기본계획)를 계기로 **매일 수집을 전수+AI 판정으로 전환** — 최근 15일분을
전부 내려받아 Haiku가 제목+본문으로 판정(기준문은 app_config.press_relevance_criteria, 실측 4/4
정확). 키워드는 백필·AI장애 폴백으로 역할 변경. ③ 백필분은 비용 0인 **세션 검토**로 정리:
에이전트 21개가 1,249건 전건을 제목+본문 발췌로 판정 → 메인 세션 2차 검증(오판 의심 자동 점검
1건뿐, 그마저 정당) → 운영자 승인 → 222건 삭제. 경계선 기준(방송 거버넌스 삭제 / 유료방송·OTT
유지 / AI 교육·행사 삭제 / AI 정책·인프라 유지 / 동정은 내용 기준)은 운영자가 확정.

**프루닝 방법이 중요했다.** 섹션과 청크 경계가 어긋나므로 청크 delete로는 안 되고, 문서 전문
백업 → 삭제 섹션 제외 재조립 → 재청킹 → 문서 단위 교체 → 재임베딩 → REINDEX 순서로 처리했다.
제목 공백 차이로 1건이 매칭에서 빠져 개별 처리 — 자동 매칭 후 미매칭 검출·보고가 있었기에 잡혔다.

**이 과정에서 잡은 사고·함정 6건.**
1. **kmcc.go.kr 오정정의 재정정** — #50 무렵 "kmcc=중앙전파관리소"로 고쳤으나, 실측(목록 상위
   5건 완전 일치) 결과 kmcc.go.kr은 **방송미디어통신위원회(방통위 개편 후 새 도메인)**이고
   kcc.go.kr의 미러였다. 진짜 전파관리소는 crms.go.kr(cpage 페이지네이션, javascript:view 링크).
   gov_notice_crawler의 crawl_kmcc를 crms로 재지정. 교훈: "정정"도 실측 없이 하면 오정정이 된다.
2. **MSIT 첨부 구조** — 상세 페이지는 스텁("첨부 참고"). fn_download('번호','순번','확장자')
   3-인자 파싱 → POST fileDown.do(atchFileNo·fileOrd·fileBtn=A) + Referer 필수. HWPX는 ZIP의
   Contents/section*.xml 태그 제거로 전문 추출(그림 대체텍스트 "그림입니다/원본 그림의…"는 제거).
3. **방통위 페이지네이션은 cp** — 표준 후보(pageIndex 등) 10개 중 cp만 동작. 이걸 못 찾은 첫
   실행은 1페이지에서 멈춰 100건 중 2건만 수집됐다(재실행으로 회복 — dedupe 덕에 안전).
4. **KISDI "JS 렌더" 오진** — 목록은 처음부터 HTML에 있었는데 행 링크가 href가 아니라
   onclick="goView('bbsSn')"이라 파서가 못 봤던 것. goView 파싱 + POST pageIndex로 해결(4건→56건).
5. **ETRI 목록 순환** — 마지막 페이지를 넘겨도 같은 내용을 반환하는데 URL에 페이지 번호가 박혀
   'URL 신규' 판정을 통과, 600페이지 상한까지 헛돌 뻔했다. 페이지 제목 조합 fingerprint 재등장
   시 종료하는 방어를 추가.
6. **PostgREST 1,000행 컷** — `.limit(2000)`도 서버가 1,000에서 자르고, 무정렬이라 임의의
   1,000건이 와서 대시보드에서 "최근 두 달만 안 보이는" 증상이 났다(목록 loadPressJSON·상세
   openPressDetail 두 곳). order+range 페이징으로 수리. 상세는 겸사겸사 "같은 날짜 여러 건이면
   첫 건만 열리는" 잠재 버그도 수리(날짜+제목 동시 매칭).

**RAM 관리(운영자가 직접 제기).** 과거 무료 시절 대량 적재→삭제 후 검색·사이트가 급락한 경험이
있어 백필 전 실측: shared_buffers 512MB(컴퓨트 Small 2GB), HNSW 223MB. halfvec·선별 임베딩·컴퓨트
업그레이드는 모두 운영자 불채택 — **전량 임베딩 유지 + 백필 후 REINDEX**로 대응. 결과: HNSW
259MB(+36MB에 그침, 프루닝·REINDEX 효과), trgm 41→38MB, 검색 7.9ms(콜드)/백필 전 79.5ms 대비
저하 없음. 이때 **Supabase가 Pro(유료)임을 운영자가 확인** — 지침의 "무료 500MB×2" 기술을 정정.

**부수 개선.** 대시보드: 기관 탭 2곳·수집 키워드 관리 카드·"원본 파일 136개" 하드코딩 제거·
searchPressReleases 스키마 불일치 버그(자문 TypeError 유발 가능) 수리·보도자료 탭 업로드 진입점
제거(수동 등재는 '추가 지식 입력'으로 일원화). refetch_content는 msit.go.kr URL이면 첨부 추출기를
먼저 시도하게 연결 — 입법예고·고시도 아침 브리핑에 전문 요약이 실리게 됐다. 개선 로드맵 5건은
docs/개선로드맵_260802.md.

## 54. 개선 3건 병렬 구축 — 법령 DIFF 자동화·해외 규제기관 모니터링·과방위 회의록 (2026-08-02)

**배경.** 보도자료 자동 수집(#53) 완결 직후, 운영자가 로드맵 5건 중 3건의 동시 구현을 지시.
③ 법령 DIFF는 UX까지 확정(리스트 → 클릭 → 총괄+SKT 영향 → 조문 전/후 비교표), ⑥맞춤 알림·⑦봇
보고서는 보류(추후 결정). '보고서 초안 제안' 메뉴는 미사용으로 숨김(주석 처리 — 코드·데이터 보존,
복원은 index.html 주석 해제 2곳).

**병렬 실행 방식.** 에이전트 4개 동시(③④⑤ 백엔드 각 1 + 대시보드 전담 1) + 메인 오케스트레이션.
같은 파일 동시 수정 금지 원칙에 따라 파일 소유권을 겹치지 않게 배정(app.js·index.html은 대시보드
전담만). 설계 단계에서 탐색 에이전트 3개가 기존 코드 재사용 지점을 먼저 확정 — 특히 "신구 조문
비교 데이터(current/pending/superseded + fetch_pending_articles RPC)가 이미 DB에 있다"는 발견이
③의 구현을 크게 줄였다.

**③ 법령 DIFF 자동화** — 신규 law_diffs 테이블 + law_diff_gen.py.
- law_pending의 loaded(현행↔시행예정)·promoted(구현행↔신현행) 쌍에서 조문 단위 diff(3분류:
  변경/신설/삭제, norm_article_key 파이썬 포팅) → Sonnet 1콜/법령(tools JSON 강제:
  총괄 summary·SKT impact·urgency·조문별 impact) → upsert(law_name,new_doc,diff_kind) →
  운영자 텔레그램 + heartbeat last_law_diff_run.
- 핵심 설계: **전/후 원문을 jsonb에 복사 보존**(KEEP_VERSIONS 정리와 무관하게 상세 생존),
  **pending→promoted 전환 시 AI 재호출 없이 kind만 갱신**(이중 과금 차단), 변경비율>70%는
  전부개정 판정(조문 표 생략). PDF 수기 등재본(law_id 없음)은 대상 제외.
- 첫 백필: 시행예정 13건 생성(전파법 20261022본 변경 27조문, 정보통신망법 20261001본 변경16+신설8
  등), 실패 0, 제외 1(충전 기술기준 — 조번호 미파싱 등재본, 재적재 검토 대상).
- 대시보드 DIFF 탭 개편: 상단 자동 감지 리스트+상세(총괄 카드+조문 표, _tokenDiff 하이라이트
  재사용), 기존 수동 파일 비교는 하단 유지. QA에서 지방세법 분석이 "장·절 편제 정비일 뿐 실체
  개정 없음"을 정확히 짚어냄.
- 스케줄: 별도 작업 신설 없이 run_gov_crawler.bat 17시 체인에 부착(스케줄러 사고 표면 최소화).

**④ 해외 규제기관 모니터링** — 신규 foreign_press.py. FCC·Ofcom·BEREC·日총무성·ITU.
- 실측으로 확정한 소스 경로가 핵심 자산: **FCC는 fcc.gov의 /rss 경로들이 전부 가짜(HTML 반환)이고
  진짜는 EDOCS API RSS**(api2.fcc.gov .../rss/docTypes/News_Release — Daily Digest 아님).
  **Ofcom은 전 경로 Cloudflare 차단**(impersonate 5종 실측 전패) → 구글 뉴스 site: RSS 우회.
  日총무성은 Shift_JIS HTML 파싱(월초엔 전월 페이지 보충), BEREC·ITU는 공식 RSS.
- Haiku 1콜로 관련성 판정+한글 제목 번역+3문장 요약(기준문 app_config.foreign_relevance_criteria —
  무선국 제도 '변경'은 포함하되 개별 인허가 처분 공고는 제외). **API 키 없으면 fail-closed**
  (외국어 원문이라 키워드 폴백이 성립 안 함 — heartbeat에 사유 기록).
- 첫 수집: 스캔 150 → 신규 51 → 관련 16건 등재(무관 35 — ITU 'AI for Good' 행사류가 정확히 걸러짐).
  news_feed category='해외', 60일 롤링. 모니터링 탭 '해외' 통합 칩. 아침 브리핑 [해외 동향] 섹션은
  파이썬 결정적 조립(입법예고 섹션 패턴, briefing 뒤쪽 배치 — 참고 등급이 국내 헤드라인을 밀지 않게).
- 스케줄: 매일 05:30 radio_TEMP_foreign(임시 — 해외 사이트는 한국 IP 불요라 계정 복구 후
  GitHub Actions 이관 대상).

**⑤ 과방위 회의록** — 신규 assembly_minutes.py + register_kb_section 일반화.
- API 실측이 관건이었다: 열린국회 위원회 회의록 목록 API는 **ncwgseseafwbuheph**(DAE_NUM·CONF_DATE·
  COMM_NAME, 응답 row는 회의가 아니라 '안건' 단위 — CONFER_NUM으로 회의 그룹핑 필요).
  **PDF_LINK_URL의 PDF는 pdftotext에서 중반부 글리프가 깨진다(폰트 문제, 실측)** — 대신
  record.assembly.go.kr 뷰어 xml.do가 div.speaker[data-name][data-pos]>div.talk 구조로 발언자
  단위 클린 텍스트를 줌(뷰어 1순위, PDF 폴백). 정당 정보는 미제공이라 직위(data-pos)로 표기.
- 발언 선별 2단계(press_keywords 1차 + Haiku 2차, 회의당 40블록 상한) → 채택 발언+전후 1블록
  (블록당 1,500자, 30개 상한) → 과방위_회의록_{YYYY}.md, doc_category='회의록',
  섹션 '## YYMMDD 제N차 (안건)'. press_ingest.register_press는 register_kb_section을 호출하는
  래퍼로 일반화(가짜 클라이언트 회귀 테스트로 기존 포맷 바이트 동일 확인).
- 대시보드: 국회 법안 탭 하단 #assembly-minutes 목록(법안 렌더와 분리 — 필터 재렌더에 안 쓸리게),
  상세는 openPressDetail 재사용. KB 문서 목록 블랙리스트에 '회의록' 추가(#50 유형 예방).
- 운영자 지시로 22대 개원(2024)부터 전량 백필(2024→2025→2026 순차).

**교훈.**
- "이미 있는 데이터로 풀 수 있는가"를 먼저 묻는 것이 이번에도 이겼다 — ③은 법제처 연혁 API 없이
  기존 status 3종 조문으로 완성.
- 해외 사이트는 공식 RSS 경로부터가 실측 대상이다(fcc.gov의 가짜 RSS 경로, Ofcom 차단).
- 국회 회의록 PDF는 신뢰하지 말 것 — 뷰어가 정본이다.

**(#54 보강) 입법예고 단계 DIFF와 단계 우선 정렬.** 운영자가 "확정된 법은 따라야만 하고, 예고
단계가 의견제출로 개입 가능한 유일한 구간"이라는 논리로 두 가지를 추가 지시했다: ① 입법예고
개정안도 DIFF 분석(diff_kind='proposed' — 과기정통부 예고 첨부를 msit_extract로 뽑아 현행 조문과
대비, 의견마감일 표시, 개정안 기준 경고문, 공포 시 확정본 DIFF로 자동 대체) ② 목록 정렬을
입법예고→시행예정→시행완료 순으로(그 안에서 전파법·전기통신사업법·방발법 계열 우선 —
DIFF_TIER). "시행 임박 확정 개정이 더 급할 수 있다"는 반론은 정렬이 아니라 알림(D-day·urgency)의
몫으로 정리. 첫 실측: 전파법 시행령(변경6·신설7, high)·시행규칙(변경3) 예고 2건이 목록 최상단에
생성됐고, 시행령 요약이 무선국자기적합확인 절차 신설(제42조의3)을 정확히 짚었다. 구현 중 잡은
버그: 정렬된 목록과 상세 캐시의 인덱스 불일치(정렬 후 캐시 재대입으로 수리), fetch_articles 반환
구조 오해(dict를 튜플로 언팩 — 프롬프트에 키 이름이 들어가는 무음 오염이 될 뻔, KeyError로 발견).

**(#54 보강 2) 해외 주요 정책 KB 승격·회의록 완결.** ① 운영자 지시로 해외 규제동향 중 "주요
정책"(규제 제·개정, 공식 협의, 인허가 제도 변경, 국가 전략)을 지식베이스에 영구 승격하는 경로를
추가 — foreign_press의 Haiku 판정에 major 필드를 더해 매일 자동 승격(`해외규제동향_{YYYY}.md`,
doc_category='해외동향'), 기존 12건은 세션 심사로 7건 승격(BEREC 5건·Ofcom·日총무성).
ITU의 'AI for Good' 행사류 4건이 관련으로 오판돼 있던 것은 삭제하고 기준문에 ITU 특칙(WRC·표준·
주파수만 관련, 학술·시상·행사는 무관)을 추가. ② 과방위 회의록 22대 백필 완결: 146개 회의
(2024:59/2025:57+4실패/2026:27+초기3), 1,036청크, 회의별 Haiku 요약 줄(목록 부제) 41건 소급 +
'# 요약' 접두 버그 정리, 임베딩 완전. 첫 백필 시도가 실행 명령 인용 오류로 시작조차 안 됐던 것을
로그 부재로 발견 — 다중 명령 백그라운드 실행은 .cmd 스크립트 파일로 할 것. ③ UI: 해외·회의록
독립 메뉴 승격, 모바일 하단 네비에 '법안 동향' 그룹 분리(기술용어는 모니터링 서브로), 지식베이스
메뉴 순서 통일, 60일/영구 보관 표기, smartRefresh가 항상 뉴스만 갱신하던 버그 수리(.active 클래스
인식 — 패널별 중복 새로고침 버튼 7개의 근본 원인), 아침 브리핑 생성만 Sonnet 5 전환(운영자 결정).

## #55 (2026-08-02) 아침 브리핑 미생성 — 원인은 GitHub이 아니라 노트북 전원

8/2 06:00 브리핑이 안 왔다. 1차 추정은 GitHub 계정 flag(8/1 발생, Actions까지 "Actions has been
disabled for this user" 422로 계정 단위 차단 — pg_cron 트리거 기록으로 실측)였으나, PC 임시 스케줄
5종(radio_TEMP_*)은 이미 8/1 밤에 등록돼 있었다. 진짜 원인은 **노트북 전원**: 커널 로그에 05:38~
12:04 AC↔배터리 전환(이벤트 105)과 Modern Standby 진입·해제가 반복 기록됐고, schtasks 기본값
"배터리 전환 시 작업 중지"가 켜져 있어 06:05 브리핑 작업이 시작 3초 만에 Ctrl+C(0xC000013A)로
죽었다(로그에 `^C`만 남음). 06:39~12:04에는 PC가 절전으로 잠들어 오전 작업 전체가 밀렸고, 깨어난
직후 기존 RadioPolicy-* 작업들까지 일제히 같은 코드로 죽은 흔적. **조치**: 저장소를 실행하는 작업
10종 전부에 AllowStartIfOnBatteries·DontStopIfGoingOnBatteries·StartWhenAvailable 적용, 브리핑
작업엔 WakeToRun(절전 깨우기) 추가. 8/2분 브리핑·뉴스 공백은 수동 실행으로 복구(크롤러 신규 7건·
긴급 1건, Sonnet 5 첫 실전 브리핑 2,053자 + [해외 동향] 3건 발송). **교훈**: ①PC 기반 스케줄은
등록만으로 끝이 아니다 — 전원 조건(배터리·절전)까지 명시적으로 풀어야 한다. ②작업이 "실행됨"인데
산출물이 없으면 Last Result 코드(0xC000013A=전원/강제종료)와 Kernel-Power 이벤트를 먼저 본다.
③밤사이 무인 실행이 필요한 노트북은 전원 케이블 상시 연결이 근본 예방.

## #56 (2026-08-02) 국회 입법예고 추적 + 예고 단계 조문 분석 + 메뉴 개편 17→9

**배경.** 운영자 논리("확정된 법은 따라야만 하고, 예고 단계가 유일한 개입 구간")를 국회 쪽에 적용하면
행정부 입법예고만 추적하던 것이 공백이었다 — 국회 입법예고(국회법 82조의2, 10~15일)는 법안 의견
제출의 유일한 공식 창구인데 기간이 짧아 놓치기 쉽다. 운영자가 ⑩⑪⑫보다 우선 지시, 에이전트 4개
병렬(수집 A/분석 B/브리핑 C/프런트 D) + 메인 오케스트레이션으로 구현.

**실측 확정 사실.** ①전용 OpenAPI `nknalejkafmvgzmpt`(진행중 입법예고)가 존재 — 기존 ASSEMBLY_API_KEY로
동작, pSize=1000 1콜에 전량(379건), NOTI_ED_DT(마감일)·CURR_COMMITTEE·LINK_URL 포함, pal 사이트와
레코드 완전 일치(차집합 0). 진행중 API 결과 = 그 자체로 "의견등록 가능" 목록(마감일 당일 포함).
②매칭 키는 BILL_ID(assembly_bills.bill_id와 바이트 일치, 98.2% 검증). ③함정: 진행중 API는 AGE
파라미터 무시 / pal HTML은 GET 페이징을 조용히 무시(POST+_csrf 필요 — 스크래핑 전환 금지, API가
동등) / 국회 파일서버 FileGate는 302가 아니라 "moved" HTML을 줘서 href 추적 1~2회 필요 / 신구조문
대비표 표제의 가운뎃점은 U+318D(ㆍ)라 일반 `·` 정규식으로 미검출.

**설계 결정.** ①관련성은 키워드가 아니라 **의미 판정**(운영자 지적 "요약할 때 내용을 읽지 않나") —
보도자료(#53)와 동일하게 Haiku 배치 판정 + app_config 기준문(assembly_notice_criteria) + 실패 시
키워드 폴백. 기각 캐시(assembly_notice_rejected)로 재판정 방지. 실측에서 산자위 소관 "산업 디지털
전환·AI 활용 촉진법"을 잡아내 위원회 필터 방식의 누락 위험을 증명. ②경계선 법안의 판정 흔들림
(지역방송발전지원법이 dry-run 관련→실전 기각) 발견 → **과방위 소관은 AI 판정 없이 자동 관련** 규칙
추가(회의록 전량 수집 방침과 일관). ③예고 단계 조문 분석(③′): 계류 전체(162건) 소급은 과하지만
"의견등록 가능 + 관련" 한정(월 ~12건)이면 비용 무시 가능 — 의안 원문 PDF의 신구조문대비표를
pdftotext로 추출해 Sonnet 1콜 분석, law_diffs diff_kind='proposed'+origin='assembly'(신설 컬럼)로
등재, 가결(공포 후 pending DIFF가 대체)·폐기·철회 시 자동 삭제. ④알림은 운영자 전용(시작 1회+D-3
1회, stage 컬럼 dedupe — 발송 성공 시에만 stage 갱신해 실패 시 재시도), 구독자 확대는 ⑥에서.
⑤브리핑에 [국회 법안 동향] 섹션(신규 발의·처리 변경·마감 임박, 항목 없으면 생략).

**첫 실전.** 379건 중 관련 6건 등재(과방위 3+개인정보보호법+전기통신금융사기법+산업디지털AI법),
조문 분석 6/6(개인정보 보호법이 urgency high·조문 7개 — 지급정지 개정), 알림 7건, 대시보드에서
"의견등록 배지 → 조문 DIFF 상세" 크로스 링크 end-to-end 실측 통과. AI기본법 1건이 파싱 실패했다가
재실행에 성공(재시도 멱등 확인).

**(선반영) 메뉴 개편(동시 구현).** 좌측 네비 17→9: 통합 모니터링(탭: 뉴스|정부|해외)·법령 개정 추적(탭:
입법예고·개정 현황|조문 DIFF — 기존 화면 무수정 재사용, 시행예정·최근1년 카드 유지)·지식베이스
(탭 5, 추가지식 접근 유지). 설정은 상단 톱니, 운영 상태는 상단 상태등(🟢/🔴 — 하트비트 지연 종합,
클릭 시 패널)으로 이동해 "무음 실패 감시"가 오히려 상시화. 모바일 하단 5버튼 유지, 375px 가로밀림
0 실측. 국회 법안 화면은 6카드(의견등록 가능 신설)+최상단 정렬. heartbeat last_assembly_run 신설.

## #57 (2026-08-02) 개선⑩ 보안 — 로그인 없이 "화면이 하는 일"만 열어두기

**배경.** 프로젝트 품질 점검에서 나온 최대 약점이 보안이었다. 공개 GitHub Pages + anon 키 구조라
**anon에 열린 권한 = 전 세계에 열린 권한**인데, 실측(대시보드 쓰기 경로 44건 전수 지도)에서
①`news_feed` RLS 자체가 꺼져 있어 외부에서 뉴스 전량 삭제 가능 ②`document_chunks`가 anon INSERT
허용이라 승인 게이트를 우회한 RAG 코퍼스 주입 가능 ③`app_config`가 무방비라 **텔레그램 봇의
system_prompt를 대시보드 키로 교체하는 크로스 채널 프롬프트 인젝션** 성립 ④`chat_logs`가
"Allow all(ALL)" ⑤보고서 4테이블 전정책 개방 — 위험 5건이 확인됐다.

**운영자 방침(전환점).** 초안은 2단계(Supabase Auth 로그인 도입)까지였으나 운영자가
**"현재는 로그인 없이 다 쓸 수 있게 해주고, 다만 아무나 DB를 못 건드리게만"** 으로 정리.
그래서 설계 원칙이 "사람을 식별한다"가 아니라 **"대시보드 화면이 실제로 하는 연산만 열고
나머지는 전부 잠근다"** 가 됐다. 팀원 접근성(추가지식 입력·긴급도 피드백·용어 추출)은 그대로 유지.

**조치.** 전 테이블 RLS 재정비(상세 표는 지침 'RLS' 절): 읽기 전용 9종 / 화면 기능 테이블은
필요한 연산만(news_feed는 update·delete만, insert 없음 / chat_logs·deleted_news는 append-only) /
레거시 3종(changes·documents·system_status)은 정책 0개로 잠금 / 보고서 4종은 메뉴 숨김 상태라
쓰기 회수. 조건부 2건이 핵심: **app_config는 `key in ('claude_key','press_keywords')` 행만** 쓰기
허용(system_prompt 봉쇄), **document_chunks INSERT는 `is_approved=false` 강제**(승인 우회 차단).

**검증.** 잠금 후 대시보드 실화면에서 쓰기 경로 회귀 0 실측(뉴스 잠금·수집 키워드 저장·자문 기록·
용어 갱신·KB 품질 뷰 모두 정상). 차단 쪽은 승인완료 문서 삽입·보고서 지시 삽입이 42501로 거부되고
DB에 실제로 등재되지 않음을 확인. **함정 하나**: 정책에 걸린 UPDATE는 401이 아니라 "0행 수정"
**204**로 돌아온다 — 응답 코드만 보면 성공으로 오해하기 쉬우므로 실제 값 변화로 확인해야 한다.

**남긴 것.** Storage `uploads` 버킷은 화면 업로드·삭제가 직접 쓰므로 anon 유지(로그인 미도입 방침의
귀결). `admin_*` RPC의 비밀번호 검증도 그대로 — Auth 도입(2단계)은 운영자 판단으로 보류.

## #58 (2026-08-02) 개선⑪ 코드 품질 — 텔레그램 11벌·Voyage 3벌을 공용 유틸로

**배경.** 같은 기능이 파일마다 복사돼 있었다: 텔레그램 전송 함수 11벌(assembly_crawler 2·crawler 2·
itu_rec_watch·law_crawler·law_diff_gen·morning_briefing·send_briefing·gov_notice_crawler·law_watch·
resend_briefing), Voyage 임베딩 호출 3벌. 재시도·429 처리·4096자 분할 규칙이 제각각이라, 한 곳을
고치면 나머지가 뒤처지는 구조였다(실제로 재시도 없는 사본이 섞여 있었다).

**방식 — 래퍼 전환(회귀 0 원칙).** `notify.send_telegram(text, *, chat_id, parse_mode,
disable_web_page_preview) -> bool`(3800자 개행 경계 분할·재시도 3회·429 Retry-After 우선·
**429 제외 4xx는 즉시 False**로 HTML 400 평문 폴백 지원)과 `embed_util.get_embeddings(texts, *,
input_type, model, dim, api_key, timeout)`(429 Retry-After·재시도 5회·입력 검증을 네트워크 전에)만
신설하고, **기존 함수의 이름·시그니처·호출부는 한 글자도 바꾸지 않은 채 내부 전송부만 위임**했다.
각 파일의 고유 동작(로그 접두 '[텔레그램 모닝]', 파스모드, 길이 절단·말줄임, 대시보드 링크 부착,
env 미설정 시 출력 유무, assembly_crawler의 구독자 큐 적재)은 전부 원위치에 남겼다.
`health_watchdog.py`는 **의도적으로 독립**(Supabase·공용 유틸에 의존하지 않는 외부 감시자)이라 제외.
함정 하나: `law_watch.py`에는 동명 함수 `notify()`가 있어 그냥 `import notify` 하면 함수 정의가
모듈을 덮어써 AttributeError — `import notify as tg_notify` 별칭이 필요했다.

**스모크 테스트(신설 `tests/test_smoke.py`, 표준 unittest·네트워크 0).** 17케이스/10항목:
norm_name 정규화, 조문 diff 3분류, 청킹 700자 무겹침 왕복 복원, 키워드 매칭('전파간섭' O·'이혼신고' X),
notify 분할 무손실, 브리핑 국회 섹션 포맷, proposed 법령명 추출, 마감 D-day 계산, embed_util 입력 검증,
**sb_client가 HTTP/1.1을 강제하는지**(#12 사고 재발 감시). `python -m unittest discover -s tests`로 실행.

## #59 (2026-08-02) 구독봇 '긴급은 즉시 받기(야간 포함)' 옵션

**배경.** 운영자가 구독봇 설정 화면을 보고 "야간에 받고·안 받고 선택 메뉴가 없어졌네?"라고 물었다.
확인 결과 없어진 게 아니라 처음부터 두지 않은 것이었다 — 구독봇은 브리핑·긴급·법안을 **각자 고른
시각 한 번에만** 보내므로 야간 발송 자체가 없어 '야간 무음' 토글이 무의미했다(소스 주석에도 그렇게
적혀 있었다). 그러자 운영자가 반대 방향을 요청했다: **"긴급 뉴스는 밤에라도 즉시 받고 싶을 때
받게 해 주는 옵션을 추가"** (운영자 개인 봇은 이미 즉시 수신 중).

**한 번 만들었다가 되돌렸다 — 그 과정에서 실동작을 정정.** `urgent_now` 컬럼 + 즉시 발송 +
설정 체크박스를 구현·배포했으나, 운영자가 곧 **"야간 즉시는 끄고, 대신 발송 시간대를 표시하자"**
로 방향을 바꿔 전부 되돌렸다(컬럼 drop, 버튼·코드 제거, 재배포). 되돌리며 확인한 결과 **문서와
내 설명이 모두 부정확**했다는 것이 드러났다:

- 문서·주석은 "긴급도 선택 시각에 한 번만"이라고 적고 있었지만, 실제 `send-subscriber-briefing`은
  매시 :25에 돌며 `briefing_hour <= 현재시(KST)`인 구독자에게 **그 사이 큐에 새로 들어온 긴급을
  즉시 배달**한다. 즉 낮에는 하루 한 번이 아니라 **매시 배달**이다.
- 자정이 지나면 `briefing_hour(6) <= 0`이 거짓이 되어 발송이 멈추고 선택 시각부터 재개된다 →
  **실제 발송 가능 시간대는 '선택 시각 ~ 23:25'**. 운영자가 감으로 짚은 "밤 11시까지"가 정확했다.
- 지연 실측: 기사 발행 → 크롤러 수집(:50) → 배달(:25) = **40분 ~ 1시간 35분**.

**최종 반영 (현행 유지 + 지연 단축).** ① 설정·시작 안내에 발송 시간대 명시("23시가 지나면 다음 날
선택 시각까지 발송하지 않습니다"), 시각 버튼 라벨도 '받는 시각'→**'받기 시작 시각 (심야 무발송)'**
로 교정. ② `subscriber_notify._trigger_delivery()` 신설 — 긴급을 큐에 넣은 직후
send-subscriber-briefing을 1회 호출해 다음 :25를 기다리지 않게 했다. **발송 함수 자체가 수신 시각을
검사하므로 심야에 호출돼도 아무도 받지 않는다**(무발송 원칙 유지). 정시 :25 실행은 그대로 둬서 이
호출이 실패해도 배달이 누락되지 않는다(fail-open). 지연 **0~60분(평균 30분)** 으로 단축.
크롤러 주기를 30분으로 줄이는 안은 반려 — 평균 15분을 얻자고 API·부하를 2배로 만들고, 계정 복구 시
기존 트리거(:47·:17)가 살아나 원복 부채가 생긴다.

**배포.** telegram-webhook 재배포 2회(npx supabase@latest, --no-verify-jwt). Docker 미실행 경고는
무시해도 되는 정상 출력(에셋 업로드 방식). 파이썬 측은 py_compile·스모크 테스트 17건 통과.

## #60 (2026-08-02) 개선⑫ 데이터 품질 — 선별 OCR·KB 품질 카드, 그리고 "OCR 반려" 판단

**실측이 계획을 바꾼 지점 1 — 규모.** 원안은 "본문 추출 실패분 대량 OCR"이었으나 SQL 실측 결과
current 문서 중 본문 500자 미만은 **7건뿐**이었다. OCR은 소품 작업이 되고, 실질 가치는 저품질 등재를
**상시 노출**하는 쪽(운영 상태 탭 'KB 품질' 카드)으로 옮겨갔다.

**실측이 계획을 바꾼 지점 2 — 실패했던 MSIT 2건의 진짜 원인.** "이미지-전용 첨부라 OCR이 필요하다"고
믿었던 두 건은, 확인해 보니 **msit.go.kr 원 페이지에 첨부파일 자체가 없는 스텁**이었다(본문은
"자세한 내용은 첨부파일 참고" 안내문뿐). OCR 대상이 아예 없었던 것. 정책브리핑(korea.kr)에서 원문을
확보해 등재했다 — 가상융합 기금 건 8청크·4,697자, 도시안전 AI반도체 건은 korea.kr에도 첨부가 소실돼
공식 요약 317자만(원문 링크도 korea.kr로 저장 — MSIT 링크는 빈 껍데기). 후자는 게시일이 2025-06-23로
'2026년 자료'라는 기억과 달랐다. **교훈: "추출 실패"의 원인을 추정하지 말고 원 페이지를 직접 볼 것.**

**OCR 폴백(press_ingest).** PDF 텍스트층 <500자면 pdftoppm(150dpi·최대 8쪽)→tesseract kor+eng,
**1,000자 이상일 때만 채택**하는 훅을 첨부 처리 경로에 넣었다(도구 부재·실패 시 fail-soft). 과기정통부
첨부 선택도 "120자 넘으면 첫 첨부 채택"→"500자 확보까지 계속"으로 보강(잡음 첨부에 만족해버리는 문제).
합성 이미지-전용 PDF로 end-to-end 실증(텍스트층 0자 → OCR 2,313자, 표본 재현율 98%).

**그리고 "반려" 판단.** 저품질 7건 감정 결과 (a)OCR 가능 2건 (b)원래 짧은 정상 4건 (c)파싱 실패 1건.
(a) 2건은 기술적으로 OCR이 되는데도 **등재를 반려**했다 — 전력선통신 고시의 주파수 표는 원본이
567×378 저해상 BMP라 **수치를 오독**했고, 하이퍼네트워크 발표자료는 도형·장식을 글자로 잡았다.
자문이 틀린 주파수 수치를 근거로 답하는 것은 본문이 짧은 것보다 훨씬 해롭다. 지침 do-not에 추가.

**KB 품질 카드.** `kb_quality_low_docs`·`kb_quality_article_parse` 뷰(anon select) + 운영 상태 탭
카드: 본문 부실 하위 목록(500자 미만 빨강)·조문 인식률 하위(50% 미만 빨강)·임베딩 누락 수.
하트비트 표시를 지연시키지 않도록 fire-and-forget 로드. 실데이터 렌더 확인(임베딩 누락 0건).

---

## #61 (2026-08-02) check_briefing_health 봇 토큰 평문 → Vault 이전

**문제.** 브리핑 실패 감시 함수 `check_briefing_health`(pg_cron jobid 1) 본문에 텔레그램 봇
토큰·chat_id가 **평문 하드코딩**돼 있었다. 곧 봇 토큰을 재발급할 예정인데(노출 이력), 이 함수만
코드가 안 고쳐지면 **"브리핑이 안 나갔다"를 알려줄 감시 알림 자체가 조용히 죽는다**(감시자가
감시를 못 하는 상태). 바로 옆 `check_news_health`는 이미 Vault를 쓰는 올바른 방식이라, 그 패턴을 복제.

**조치.** Vault에 이미 있는 시크릿 `telegram_bot_token`을 `vault.decrypted_secrets`에서 조회하도록
교체(값이 없으면 return 가드). 브리핑 존재 판정·경고 문구·chat_id는 무변경, 토큰 획득부만 평문→Vault.
Vault 토큰의 봇 ID 프리픽스가 기존 하드코딩값과 일치함을 확인(무단 스왑 아님). `select
check_briefing_health();` 1회 실행 → 예외 없이 완료(오늘 브리핑 존재라 발송 분기 미진입, 안전).
**이후 봇 토큰 재발급 시 Vault `telegram_bot_token` 하나만 갱신하면 두 헬스체크 + watchdog_scan(#62)이
모두 자동 반영된다.** (남은 평문 토큰: 없음 — check_briefing/news/watchdog 3함수 전수 확인.)

## #62 (2026-08-02) 워치독 이원화 완성 — 감시자가 감시대상과 함께 죽는 사각 제거 + heartbeat 전수 감시

**계기(실제 사고).** 이날 GitHub 계정이 정지되면서, GitHub Actions에서 돌던 **외부 워치독
`health_watchdog.py`가 감시대상 플랫폼(GitHub)과 함께 죽었다.** 뉴스 크롤러가 약 15시간 멈췄는데도
아무 알림이 오지 않았다 — "감시자가 감시대상과 같은 배를 탄" 단일 장애. 게다가 살아있는 내부 감시
(§3의 `check_news_health`)는 **뉴스·브리핑 2종만** 봤다. 그 사이 파이프라인은 10종으로 늘어(뉴스·
정부고시·보도자료·법령DIFF·국회·회의록·해외·ITU·본문재수집·구독발송) system_health에 10개
heartbeat 키가 쌓이는데, 대부분이 무감시 상태였다.

**설계 — Supabase 내부 `watchdog_scan()` 신설(§3의 이원화를 실질 완성).** GitHub과 무관하게
Supabase pg_cron만으로 도는 순수 DB 함수. system_health 10키를 **키마다 다른 임계값**으로 훑는다
(주기가 제각각이라 단일 임계는 오탐·누락 양쪽을 낳음):

| key | 정상 주기 | 임계 | 근거 |
|---|---|---|---|
| last_crawl_run | 매시(뉴스) | 3h | check_news_health의 crawler_ok<3h 관례 재사용 |
| last_gov_notice_run | 매일 17:00 KST(PC) | 26h | 하루 1회+여유(외부 워치독 26h 관례) |
| last_press_ingest | 17시 체인 | 26h | gov 크롤러 말미 run_daily 체인 |
| last_law_diff_run | 17시 체인 | 26h | 동일 체인 |
| last_assembly_run | 매일 10:30 | 26h | 하루 1회 |
| last_minutes_run | 17시 체인 | 26h | 동일 체인 |
| last_foreign_press_run | 매일 05:30 | 30h | 단일 트리거/일 + 변동 여유 |
| last_itu_watch_run | 매월 1일 | 960h(40일) | 월 1회, 한 달 건너뜀 일부 허용 |
| last_refetch_run | 매시(본문, PC) | 26h | PC 변동 커 보수적. 코어 생사 신호는 last_crawl_run이 이미 커버 |
| last_subscriber_briefing_run | 매시 :25 | 3h | 매시 |

임계는 **실측 나이 + 실제 주기 + 여유**로 잡았다. 신설 시점 최대가 last_crawl_run 62%·foreign 61%
로 어느 키도 임계 근처가 아니어서(gov 22%·itu 3%) 오탐 0을 dry-run으로 확인했다.

**무음 의미실패 탐지.** "돌긴 돌았는데 실패"를 잡으려 note를 정규식으로 본다. 단 **`new=0`은 정책
크롤러에선 정상**(신규 없음이 대부분)이라 신호에서 제외 — `fail=N`/`failed=N`/`실패 N`이 **N>0일
때만** 경고(`fail=0`·`failed=0`·`실패 0`은 매칭 안 되게 `[1-9]` 앵커). 10키 현재 note 전수에
오탐 없음 확인. (예: foreign가 API 키 부재로 fail-closed면 note에 fail>0로 남아 잡힌다.)

**재알림 억제.** 하루 3회 스캔이라 같은 이상을 매번 쏘면 소음이 된다. 이상 키+유형(`key:late`/
`key:missing`/`key:fail`)을 정렬·md5로 시그니처화해 system_health의 `watchdog_alert_state` 키
note에 저장. **직전 시그니처와 다를 때만 1건 요약 발송**, 동일하면 억제, 정상 복귀 시 `ok`로 리셋
(다음 재발은 다시 알림). 트랜잭션 롤백 테스트로 3단계(발송→억제→복귀 리셋) 검증.

**발송 경로.** A 담당이 정리 중인 `check_news_health`와 동일하게 Vault `telegram_bot_token` →
`net.http_post` → chat 344506450, **1건 요약**. A와의 충돌 방지를 위해 `watchdog_scan`은 **신규
함수**로만 만들고 check_news_health/check_briefing_health 정의는 건드리지 않았다.

**pg_cron.** jobid 16 `watchdog-scan-3x`, `10 0,6,12 * * *`(UTC) = **09:10·15:10·21:10 KST**.
기존 잡의 :00/:35와 겹치지 않게 :10로 오프셋(net.http_post 몰림 방지). 프로덕션은 실발송
`watchdog_scan(false)`, 함수 기본값은 `p_dry_run=true`라 수동 점검 `select watchdog_scan();`은
발송 없이 이상 목록만 반환한다.

**검증.** ① dry-run 실측 → "이상 없음"(오탐 0). ② 롤백 트랜잭션에서 last_crawl_run 10h 백데이트 +
foreign note `fail=4` 주입 → 지연·실패 둘 다 정확히 포착, 실발송 없이 롤백. ③ 억제 3단계 통과.
정규식 회귀(`fail=3`✓ `failed=0`✗ `fail=0`✗ `실패 2`✓ `실패 0`✗).

**남은 한계(후속).** 두 워치독 모두 감시자와 감시대상이 **다른** 플랫폼이 되어 이번 사고 유형은 막았지만,
**Supabase 자체가 통째로 다운되면 watchdog_scan도 함께 죽어** 감시 불가다(외부 health_watchdog.py가
"Supabase 접속 불가"로 일부 커버하나, 그것도 GitHub이 살아있을 때만). 완전한 3중화는 **Supabase·
GitHub 어디에도 의존하지 않는 외부 제3지점(예: 무료 cron·별도 호스트에서 두 heartbeat를 폴링)**이
필요 — 후속 과제로 남긴다.

## #63 (2026-08-02) 법령 조문 매칭을 법제처 신구법대비표 API 정본으로 (difflib 폴백)

**배경.** law_diff_gen의 조문 매칭이 difflib로 "어느 조문이 어느 조문으로 바뀌었나"를 **추측**해,
조문 번호 재편·중간판·공백 노이즈로 오탐이 났다. 벤치마킹(#종합평가)에서 법제처 오픈API에
신구법대비표(oldAndNew)·행정규칙 대비표(admrulOldAndNew)가 있고 기존 LAW_OC_KEY로 접근됨을 실측.
운영자 방향: **"조문 매칭(구↔신 짝짓기)만 API 정본, SKT 영향분석·요약은 기존 유지, API 공백 시 difflib 폴백."**

**구현.** `fetch_oldnew_articles(mst, target)` 신설 — oldAndNew(법령 MST)/admrulOldAndNew(고시 ID)
본문을 호출해 diff_articles와 **동형**의 changes 배열 반환, `신구법존재여부:N`이면 None(폴백 신호).
분기는 generate_one 한 곳(**pending/promoted 경로만** — proposed·assembly는 API에 없어 무변경).
영향분석·요약·articles jsonb 스키마는 전부 그대로 — **매칭 소스만 교체**.

**실측 개선(전파법).** difflib는 28개 조문을 변경으로 봤으나 정본 대비표는 **12개로 특정**(나머지 16개는
중간판·공백 오탐). 정본 12개는 difflib의 부분집합(API-only=0)이라 "이 개정이 실제 바꾼 조문"만 정확히
골라냈다. dry-run 15건 중 정본 12(전파법·전기통신사업법·정보통신망법·지방세법·적합성평가 고시)·폴백 3
(국가재정법 등 타법개정 존재여부 N). added 9건도 진짜 통째 신설 확인.

**함정·한계.** ① 대비표 구본은 "직전 버전" 고정이라 등재본과 다를 수 있음 — 응답 신본 MST가 요청과
다르면 폴백하는 안전장치. ② 등재본↔시행예정본 사이 **여러 개정 누적** 시 마지막 hop만 보임(운영자
방향 "이번 개정 무엇이 바뀌나"엔 부합, 전체 델타는 아님). ③ 조문별 변경이력 API(lsJoHstInf)는 0건 불가.

## #64 (2026-08-02) 국회 입법예고 판정 안정화 + 검색 키워드 보완 + MSIT 공고 수집

**계기.** 오늘 국회 입법예고 추적을 만들며, 같은 법안(지역방송발전지원법)이 dry-run에선 관련→실전
실행에선 무관으로 **판정이 실행마다 뒤집히는** 것을 실측. 원인 4가지: ①판정 재료가 법안명+위원회뿐
②379건 1콜 몰이 ③결정성 미확보 ④기준문에 경계 사례 없음.

**입법예고 판정 안정화(4종 세트).** ①배치 40건 분할(배치 실패는 그 배치만 키워드 폴백) ②제안이유
(BPMBILLSUMMARY 400자)를 candidates만 조회해 판정 입력에 추가 ③결정성 — tool_choice 강제 유지 +
"각 법안 독립 판정·기준문 문자적용·추측 금지·애매하면 관련" 프롬프트(temperature류 파라미터는 지침
do-not이라 안 씀) ④경계 재투표 — '무관' 중 통신 인접 상임위(정무·행안·산자·문체)나 경계 어휘(통신·
데이터·플랫폼·개인정보·전파·주파수·방송·정보통신·디지털·인공지능) 포함 건만 1회 재판정, 관련이면 채택.
**재현성 2회 일치 실측(PASS).** 일 비용 정상운영 Haiku 1~2콜(센트 미만), 콜드스타트 11~13콜 일회성.
기준문에 경계 사례 5종 추가(방송통신 거버넌스 얽힌 방송법=관련/개인정보·플랫폼=소관위 불문/전기통신
범죄=관련/디지털·AI는 통신직결이면 관련·특정산업 내부면 무관/순수 보건·교육·농림=무관). 오늘 흔들린
판정의 기각 캐시 373건은 **초기화**해 다음 실행에서 새 로직으로 재심사.

**검색 키워드 보완.** 법안 검색이 법령명 위주 13개라 "법 이름에 없는" 통신 인접 법안(개인정보 보호법·
AI 기본법·플랫폼법)을 놓쳤다. 22대 실측 건수로 선별 추가: 개인정보 85·인공지능 77·플랫폼 22·데이터 22·
클라우드 1·메타버스 1. '정보통신'(203건 과다)·'디지털'(38건 중 헬스케어 등 무관 다수)·'이용자보호'
(0건)는 제외. 검색으로 폭넓게 가져오고 위 의미 판정으로 거르는 2단 구조.

**MSIT 공고 수집.** gov_notice_crawler crawl_msit에 공지사항 게시판(mPid=121&mId=310) 추가 — 주파수
할당·재할당 공고 원문이 실리는 곳(실측: 제2023-729호 IMT용 주파수할당 공고 등). 기존 파서 재사용(+4줄),
label='공고', RADIO_KEYWORDS 필터 자동 적용. 사업공고(311)는 R&D 모집 잡음이라 제외. 별도 메뉴 없이
"정부 보도자료·공지" 탭에 과기정통부 자료로 표시.

## #65 (2026-08-02) 법령 관계도 위임 엣지를 법제처 3단비교 정본으로 (옵션 B)

**배경.** 관계도의 위임(하위법령) 엣지는 문서명 추측("X → X 시행령 → X 시행규칙", source='family')이라
이름이 다른 위임(

## #65 (2026-08-02) 관계도 위임 엣지를 법제처 3단비교 정본으로 (옵션 B)

**배경.** 위임(하위법령) 엣지가 문서명 추측(source='family')이라, 이름이 다른 위임 관계를 원리상
못 잡았다. #63에서 확인한 3단비교 API로 정본화.

**구현.** thdCmp knd=2(위임조문삼단비교) 호출 → 법률→시행령 / 시행령→시행규칙 / 법률→시행규칙 쌍 추출
→ source='thdcmp', weight=4(family 3보다 우선), description에 조문 근거 기재. 멱등은 thdcmp만 별도
삭제·재구축(citation/family 멱등과 분리). 노드 삭제·인용 엣지 무변경(가드레일 #28·#36).

**옵션 B 채택(운영자).** dry-run에서 위임 쌍 54건이 나왔으나, 정부조직법이 각 부처 직제 15건을
끌고 와 관계도가 지저분해질 우려 → **양끝 노드가 이미 존재하는 쌍만 엣지 생성(신규 노드 무생성)**.
결과: 엣지 27건(기존 family 정본화 19 + 신규 교차위임 8), 스킵 27건, 신규 노드 0.

**새로 얻은 교차 위임(이름만으론 불가했던 것).** 전기통신사업법 → 방송통신설비의 기술기준에 관한
규정(제68조→제25조, 제69조→제17~20조 등 9건), 전파법 → 무선설비규칙(16건), 방송통신발전 기본법 →
방송통신설비 기술기준(제44조→제32조), 전기통신사업법 → 회계정리 규정, 그리고 법률→시행규칙 직접
위임(전파법·재난기본법·정보통신망법·정보통신산업진흥법).

**사고(적재 실패 후 복구).** 첫 실행에서 `law_graph_edges_source_check` CHECK 제약이
source를 family/citation/seed/ai로만 허용해 thdcmp 삽입이 23514로 실패. 그런데 그 시점에 이미
family 억제 로직이 돌아 **family가 20→1건으로 줄어든 채 thdcmp가 0건**인 공백 상태가 됐다.
제약에 thdcmp를 추가하고 재실행해 27건 적재로 복구. **교훈: 새 source 태그를 도입할 때 CHECK 제약
확장을 함께 해야 하며, "기존 것을 억제하고 새 것을 넣는" 교체형 작업은 실패 시 공백이 생기므로
적재 성공을 확인할 때까지 억제를 미루거나 트랜잭션으로 묶는 것이 안전하다.**

**한계.** 3단비교는 법-령-규칙 3단만 다뤄 **고시로의 위임은 API에 없다** — 시행령→고시 연결은 기존
방식이 계속 담당. 검증: 적재 후 대시보드 anon 조회로 27건 정상 확인.

## #66 (2026-08-03) 뉴스 수집을 "넓게 수집 → Haiku 선별 → 통과분만 처리"로 전환

**배경.** 뉴스 키워드 27개는 정부 보도자료 키워드(33개)보다 좁아, 표현이 다른 정책 기사를 놓쳤다.
운영자 질문("보도자료 키워드를 뉴스에 더하고 Haiku로 거르면 비용이 얼마인가")에서 출발 — 실측 결과
월 몇 달러 수준이라 전환 결정. 보도자료 파이프라인(#53)이 이미 같은 구조라 패턴을 재사용했다.

**구현.** ①키워드 27→54개(문자 중복 0, 포함관계 ~10개는 네이버 API의 키워드당 100건 창 때문에
의도적으로 유지 — 넓은 키워드에서 밀려나는 니치 기사의 안전망). 단독으로 쓰면 소음이 큰 후보는
좁혀서 채택(AI→AI 기본법·AI 규제, 요금→통신요금, 무선→무선설비, 사이버→사이버보안, 전파→전파법·
전파사용료). ②수집 직후 본문 수집 전에 Haiku 배치 판정(35건/콜, 구조화 출력 강제) — 기준문은
app_config.news_relevance_criteria(코드 폴백 내장). 무관 판정은 저장하지 않음(모집단 오염 방지).
③fail-open 3단: 키 없음/클라이언트 실패→전량 키워드 폴백, 배치 실패→그 배치만 폴백. ④부처 인사
뉴스는 판정 없이 무조건 통과(지침 do-not). ⑤판정 재료(네이버 description)는 _screen_text 임시 키에
담고 판정 직후 제거 — content에 넣으면 refetch_content의 "100자 미만 재수집" 조건이 막혀 본문이
영영 안 채워진다(실측 확인).

**실측·비용.** 54키워드 1회 전량 1088건, 24h 내 383건, 선별 통과율 39% → 저장 일 42→~150건(3.5배).
비용 월 $1.9→$10(+$8). 선별 없이 넓게만 수집하면 긴급도 콜만 월 $17.5라, 선별이 확대를 감당 가능하게
만드는 구조. 판정 품질: 통합요금제·위성통신·알뜰폰 통과, 물가상승률·스마트워치 판촉·타분야 R&D 제외.
경계 오탐 1건(AI 반도체 기사) — 기준문 조정으로 개선 여지.

**운영 메모.** 브리핑 분량이 늘면 기준문(app_config)만 조여도 조절된다(코드 무변경). 배포 직후 첫
실행은 15일 백로그(~350건)를 한 번에 저장하나 긴급 알림은 24h 컷+#44 억제로 폭주 없음.

## #67 (2026-08-03) 과방위 발언자별 입장 추적 (assembly_speeches)

**배경.** 회의록이 KB에 있어도(#54) 발언이 회의별로만 저장돼 "○○ 의원이 그동안 뭐라고 했나"를 못
답했다. AI 자문의 동향 참고용으로 발언자·날짜·안건·요지를 구조화.

**구현.** ①신규 테이블 assembly_speeches — speaker(정규화: 괄호 정당·직위·존칭 제거, 2자 미만이면
원본 유지)·position·meeting_date·confer_num·chunk_seq·agenda·topic·summary·source_url.
unique(confer_num, speaker, chunk_seq), RLS anon select만. ②assembly_minutes.py 확장 —
select_relevant가 (include, confirmed) 튜플을 반환하게 바꿔 판정 통과 본 발언만(전후 문맥 제외)
요지 생성·적재(Haiku 중복콜 방지). document_chunks 등재와 독립 dedupe: 둘 다 있으면 skip, 한쪽만
있으면 없는 쪽만 채움 → 기존 회의에 발언 소급 적재 가능. --limit 의미를 "실제 적재한 회의 수"로
조정(소급 시 전 회의 순회 방지). ③화면 — 회의록 패널에 "회의별/발언자별 보기" 토글, 발언자
드롭다운(발언 많은 순) → 시계열 발언 카드(날짜·안건·요지·원문 링크). escHtml·safeUrl 재사용.

**요지 가드(중요).** 발언 내용 요약만 허용, 성향·정파성 단정 평가어(친기업/강경/옹호/편향 등) 금지.
촉구·질의·지적·제안 같은 발언 행위 동사는 허용. 정치인 발언을 다루므로 시스템이 평가자가 되면 안
된다는 원칙 — 실측 요지 전부 가드 준수 확인.

**연결 가능성.** assembly_bills.proposer와 발언자명 LIKE 매칭이 실증됨("김현"↔"김현의원 등 10인") —
"이 법안 발의 의원의 과거 발언" 화면 연결은 차기 과제.

**백필.** 22대(2024~) 전 회의 소급 적재(발언·요지 Haiku 수백 콜, 1~2천원 수준). 이후 일일 17시
체인에서 신규 회의만 처리(보통 0~2건/일).

## #68 (2026-08-03) AI 자문에 [국회 동향] 참고 블록

**의도(운영자).** "조문처럼 정밀 인용하는 층이 아니라, 참고용으로 국회에서 이런 논의도 진행되고
있다 정도의 정보." 이 한 줄이 설계를 갈랐다 — 검색 엔진을 손대는 대신 #67이 만든 구조화 발언을
그대로 쓰는 길이 열려, 예상 1일이 20분으로 줄었다.

**구현.** assembly_speeches·assembly_bills를 ilike 텍스트 검색만으로 조회(임베딩·LLM 추가 호출 0).
컨텍스트 맨 뒤에 배치 — 조문·요약·기사보다 뒤가 곧 보조 계층이라는 뜻이다. 출처 배지에는 넣지
않는다(근거가 아니라 배경, 뉴스 제목 목록과 같은 원칙).

**정확도 장치 3종(전부 실측으로 값 결정).** ①topic 역방향 매칭 가점 — topic은 요약 시 붙인 통제
어휘라 질문 문장에 그대로 있으면 강한 신호. ②희소 topic 앵커 — 적중 키워드가 1개뿐이면 그것이
전체 4%(40건) 이하일 때만 통과(알뜰폰 17건 통과, AI 582건 탈락). ③법안 strong→fallback.
**의견등록 가능 여부는 순위 가점만** — 통과 기준에 넣었더니 무관 법안이 마감일만으로 올라왔다.

**프롬프트 규정.** 발언은 발언자·일자 명시("OOO 위원이 2026.4.28. ~라고 발언"), 법안은 처리단계
병기 + 확정 법령이 아님을 명시, **의원 성향·여야 구도 서술 금지**, 현행 조문과 다르면 조문 우선,
관련 약하면 언급하지 않음. sync_system_prompt.py 반영(7,893자).

**회의록 원문 청크는 건드리지 않았다.** .md 감점·제외를 풀면 회의록 1,036청크가 조문과 같은 근거
계층에서 경쟁해 운영자 의도와 정반대가 되고 조문 RAG 품질 회귀 위험이 크다. 구조화 데이터만으로
대표 질의 4개 전부 타당한 결과가 나와 필요도 없었다.

**실측.** "주파수 재할당 대가"→이정헌 위원 질의·재할당 연구반·한국 300MHz 대 미국 674MHz 비교 발언
+ 대가 산정기준 법률 명시 개정안. "단말기 유통 규제"→김현 소위원장의 단통법 폐지·전기통신사업법
통합 의결. 무관 질의(아마추어무선 자격, ITU-R SM.329)는 블록 생략 확인.

## #69 (2026-08-03) AI·데이터·클라우드 법령 14건 등재 — 그리고 REINDEX 디스크 풀 사고

**배경.** 평가에서 "AI 기본법 원문이 KB에 0건"이 드러났다. 운영자 질문("전에 법률 찾아달라고 했는데
왜 뺐나")으로 재점검한 결과, **누락이 아니라 2026-07-30 보고서에서 우선순위 [중]으로 강등돼 "2차"로
미뤄졌고 2차가 통째로 실행되지 않은 것**이었다. 1차 18개는 100% 적재, 2차는 0%.

**구조적 원인 3가지(재점검 조사).** ①우선순위 기준이 사실상 "위반하면 과징금·인가가 걸리는가"라,
벌칙 유예 상태였던 AI 기본법이 밀렸다 — 이 기준은 **이미 규제받는 사업을 자동 우대**하고 신흥
도메인을 구조적으로 후순위로 만든다. ②"2차 목록"이 문서 속 한 줄일 뿐 시스템 추적 대상이 아니었다
— law_watch는 **등재된 것이 낡았는지만 감시하고, 등재 안 한 것은 감시하지 않는다**. ③후보를
소관부처 축(과기정통부·방미통위)으로 뽑아 **공정위 소관이 0건** — 단말 온라인 판매(전자상거래법),
"5G 최고속도" 광고(표시광고법), 약관 심사(약관규제법)처럼 같은 행위를 다른 부처가 규제하는 축이
통째로 안 보였다.

**등재.** AI 기본법·시행령·확인절차 고시 / 지능정보화 기본법 3종 / 데이터산업 기본법 3종 /
클라우드법 3종+CSAP+품질성능 = 14문서, 조문 916청크 + 요약 237청크, 임베딩 NULL 0.
관계도 노드 +14, thdcmp 위임 28→35. AI 기본법 시행규칙은 **존재하지 않음**(DRF 재확인).

**정정할 사실.** 확인절차 고시(제2026-50호)는 "고영향 AI 판정 절차"가 아니다 — 법 제16조③·영
제15조④1 근거의 **국가기관 우선구매용 AI 제품 확인**(확인기관 한국인공지능진흥협회, 심사 TTA,
15일)이다. 고영향 판정은 법 제33조·영 제25조로 별개이며 **위임 고시는 아직 미제정**.

**사고: REINDEX가 디스크를 터뜨려 인스턴스가 읽기전용으로 전환.** 255MB HNSW 재구축이 원본+사본+
temp를 동시에 요구해 No space left on device → 전체 읽기전용(크롤러·브리핑 중단 위험). 실패가 남긴
무효 인덱스 _ccnew 8개(약 299MB)를 정리해 해제, 917MB→617MB, 무효 인덱스 0 복구. 원본 인덱스는
스왑 전 실패라 손상 없었다. **교훈: "대량 적재 후 REINDEX" 가드레일에 예외가 필요하다 —
document_chunks의 벡터 인덱스는 현재 디스크 여유로 재구축 불가. 디스크 증설 전까지 재시도 금지.**
kb_chunks REINDEX는 성공.

**속도 실측(등재 후).** 키워드 검색 2.34초(종전 2.1~2.6초, 변화 없음), 의미 검색 0.21초(종전 0.08초
— 2.6배이나 절대값은 여전히 미미). 총 검색은 4~6초대 유지. 다만 **의미 인덱스 재구축이 불가능한
상태라 추가 적재는 되돌릴 수단 없이 인덱스를 더 열화**시킨다 → 공정거래 계열 등재는 보류하고
운영자 판단 대기.

**남은 것.** 요약 문서 11건은 Haiku 초안이라 운영자 검토 필요(AI 기본법 3건만 원문 기반 작성).
build_law_citation_graph.py의 fetch_chunks가 `.order()` 없이 `.range()` 페이징을 써서 인용 엣지가
비결정적으로 누락된다(확인절차 고시→AI 기본법 엣지 2회 모두 실패, 인용 없는 notice 노드 7건).

## #70 (2026-08-03) 스케줄 작업이 콘솔 창과 함께 죽던 문제 — 창없음 실행으로 전환

**증상.** 8/1 밤부터 작업 스케줄러가 띄운 작업들이 시작 2~6초 만에 0xC000013A(3221225786)로
종료. 매시 뉴스·본문 재수집이 하루 15회 이상 실패했는데 heartbeat는 간헐 성공이라 "가끔 되는" 상태로
보였다. 8/2 12:04에는 6개 작업이 한꺼번에 몰살.

**오진 2회.** ①처음엔 회사 보안정책 갱신(20:55 PolicyConfiguration) 탓으로 봤으나 그건 Windows
Recall 정책 작업으로 무관. ②"bat→python 직접 실행으로 바꿔 고쳤다"고 판단했으나 그 시각에 우연히
살아남은 것이었고 이후 같은 방식으로도 계속 죽었다.

**실제 원인(운영자 증언).** 스케줄러가 띄운 검은 콘솔 창을 **운영자가 뭔지 모르고 닫고 있었다.**
창이 닫히면 CTRL_CLOSE가 전달돼 프로세스가 이 코드로 죽는다. 진단 프로브가 CTRL_CLOSE 수신을
직접 기록했고, 창을 숨긴 프로브는 완주했다. 죽는 시각이 불규칙했던 것도 "자리에 있었는지" 여부로
설명된다. 수동 실행이 항상 멀쩡했던 이유도 같다 — 그 창은 닫지 않으니까.

**조치.** `run_hidden.py` 신설(pythonw + 자식 CREATE_NO_WINDOW, stdout/stderr는 <스크립트>_sched.log에
append, 5MB 캡, 자식 종료코드 그대로 반환). 스케줄 작업 10종 전부 이 래퍼 경유로 전환.
실측: refetch 3분 완주 rc=0, crawler new=23 정상.

**부수 효과(권고 이유).** 하루 48회 뜨던 콘솔 팝업이 사라지고, 창을 닫아 사라지던 출력이 파일로
남는다. 팀원이 이 PC를 쓰게 되면 그들도 같은 실수를 하므로 사람 주의력에 의존하지 않는 편이 낫다.

**함정.** PowerShell에서 `function W($args)`처럼 **$args를 파라미터명으로 쓰면 자동 변수와 충돌**해
인수가 빈 문자열이 된다. 이 때문에 1차 적용 때 "run_hidden.py"만 전달돼 종료코드 2(파일 없음)가
났다. 스케줄 액션 변경 후에는 반드시 등록된 Arguments를 눈으로 확인할 것.

## #71 (2026-08-03) 정보통신망법 하위 보안 고시 3건 등재 — 그리고 관계도가 매번 달랐던 이유

**작업.** 운영자 지시로 정보통신망법 계열 보안 고시 3건을 KB에 등재했다. 셋 다 법제처 `target=admrul`:
ISMS-P 고시(개보위·과기정통부 공동, 제2024-8,2024-30호, 299청크), 정보보호 공시에 관한 고시
(제2024-1호, 44청크), 집적정보 통신시설 보호지침(제2024-19호, 41청크). 경로는 #69와 동일하게
`add_laws_batch.py` TARGETS → `export_law_text.py` → `add_law.py --no-article`를 재사용했고,
family는 기존 `network-act`(본법·시행령·시행규칙 3건)에 붙였다. 조문 384청크 + 요약 72청크,
임베딩 NULL 0. **#69의 교훈대로 REINDEX는 하지 않았다.**

**법령명 함정.** 3번째 고시의 법제처 정식명은 "집적정보**통신시설**"이 아니라
"**집적정보 통신시설** 보호지침"(가운데 공백)이다. `_key()`가 공백을 제거해 검색·매칭은 통과하지만,
`build_doc_name()`은 **넘긴 문자열을 그대로 doc_name에 박으므로** TARGETS에는 정식명을 써야 한다.

**본론 — 관계도가 실행할 때마다 달랐다.** 적재 후 `build_law_citation_graph.py`를 돌렸는데 새 문서
3건의 인용 엣지가 0건이었다. 조문에 「정보통신망 이용촉진 및 정보보호 등에 관한 법률」이 분명히
있는데도 그랬다. 재실행하니 이번엔 2건은 엣지가 생기고 **다른 1건이 0건**이 됐다. 즉 특정 문서의
문제가 아니라 **매 실행 임의의 문서가 통째로 빠지는** 상태였다.

**원인.** `.range()` 페이지네이션에 `.order()`가 없었다. 정렬 없는 LIMIT/OFFSET은 Postgres가 페이지마다
다른 순서로 행을 돌려줄 수 있어 행이 누락·중복된다. 이건 **이미 #66에서 세운 규칙인데**
`build_law_citation_graph.py`만 4곳에서 어기고 있었다(`fetch_all_doc_rows`, `fetch_chunks`,
노드 전량 조회, 엣지 전량 조회).

**피해가 새 문서에 그치지 않았다.** `.order('id')` 4곳을 채우고 재실행하니
인용 엣지(원시) 2,184 → **2,541건**, 적재 엣지 2,082 → **2,419건**. 즉 관계도는 새 고시와 무관하게
**평소에도 엣지 337건을 조용히 빠뜨린 채** 돌고 있었다. 더 나쁜 건 고아 노드 정리 로직이다 —
엣지 전량 조회가 행을 놓치면 **멀쩡한 노드가 '어떤 엣지에도 안 쓰임'으로 오판돼 삭제된다.**
수정 전 두 번의 실행이 각각 6건·16건을 지웠고, 수정 후에는 **0건**이 됐다. 그동안의 노드 삭제
상당수가 실제로는 오삭제였다는 뜻이다. 수정 후 연속 2회 실행이 완전히 같은 수치를 내 멱등성도 확인했다.

**교훈.** 규칙이 문서에 있다고 코드가 지키는 건 아니다. #66은 "새로 짤 때 `.order()`를 붙여라"였는데,
**이미 있던 스크립트를 감사하지 않아** 위반이 남아 있었다. 그리고 이 버그는 오류를 내지 않는다 —
결과가 조금씩 다를 뿐이라 "관계도가 원래 그런가 보다"로 넘어가기 쉽다. 비결정적 결과를 보면
페이징 정렬부터 의심할 것.

**남은 이슈 2건(미조치, 운영자 판단 필요).**
- ISMS-P 별표는 표 괘선(│)이 본문에 섞여 들어와 `「개인정보 보 │ │호법」`처럼 **깨진 이름의 인용
  노드**가 생긴다. 관계도에 잡티로 남는다. 인용 추출 단계에서 괘선·개행 제거가 필요하나
  기존 노드에 영향이 커 손대지 않았다.
- "데이터센터 보호조치"로 검색하면 집적정보 통신시설 보호지침이 semantic 38위다(법령 용어인
  "집적정보통신시설"로 검색하면 1위). 조문에 "데이터센터"라는 말이 한 번도 안 나오기 때문.
  용어 동의어 보강 대상.

## #72 (2026-08-03) 디스크 자동확장으로 인덱스 정비 재개 — 그리고 Supabase 디스크의 실체

**#69 사고의 후일담.** 새벽 REINDEX가 디스크를 터뜨린 직후(02:25), Supabase가 **디스크를 2GB→8GB로
자동 확장**하고 메일을 보냈다. Pro 요금제는 사용량 90% 도달 시 자동 확장하며, 이번 확장은
**무료·영구**다(Usage 화면 "quota 미초과", Billing에 디스크 항목 없음).

**여기서 드러난 사실 3가지.**
1. **"Pro 8GB 포함"은 권리이고 실제 할당 디스크는 2GB로 시작**한다. DB가 619MB밖에 안 되는데도
   정비 작업이 공간을 못 얻은 이유다. 문서에 "8GB 포함"만 적어두면 오판한다.
2. **WAL이 진짜 공간 포식자였다** — 사고 시점 DISK 내역이 DATABASE 618.7MB / **WAL 864MB** /
   SYSTEM 168.6MB = 1.65GB로 2GB의 83%. `max_wal_size=4096MB`라 **WAL 혼자 4GB까지 자랄 수 있다.**
   대량 적재·임베딩 백필이 WAL을 폭증시킨 것이 직접 원인. (복제 슬롯 지연은 없음 — 정상 재활용)
3. **Spend cap이 켜져 있다** — 한도 초과 시 과금이 아니라 **읽기전용 전환**으로 막는다.
   즉 돈이 아니라 서비스 중단으로 대가를 치르는 설정. 이번 읽기전용도 성격이 같다.

**정비 수행(11:20경).** 8GB 확보 후 `REINDEX INDEX`로 하나씩: content_trgm(47→42MB),
embedding_hnsw(258MB), kb_chunks, news_feed. 무사고, 무효 인덱스 0, 읽기전용 off 유지.

**효과 실측(5개 대표 질의 평균).** 키워드 검색 **2.34초 → 1.75초**(-25%), 의미 검색
**0.209초 → 0.078초**(원래 값 회복). #69에서 "인덱스 정비 불가라 추가 적재는 되돌릴 수단 없이
열화된다"고 판단해 공정거래 등재를 보류했던 제약이 이로써 해소됐다.

**교훈.** MCP execute_sql은 트랜잭션 블록 안에서 돌아 `REINDEX ... CONCURRENTLY`·
`DROP INDEX CONCURRENTLY`가 실패한다(25001). 비-CONCURRENTLY `REINDEX INDEX`는 가능하나 인덱스에
배타 잠금을 잡으므로 해당 인덱스를 쓰는 검색이 잠시 멈춘다 — 사용량 적은 시간대에 할 것.

## #75 (2026-08-03) 해외 규제동향이 수집 즉시 삭제되던 구조 충돌

**증상.** 해외 수집 로그는 "저장 N건"인데 DB에는 없다. 8/1 로그 16건 → DB 8건(FCC·ITU 0건),
8/3 05:30 수집 4건 → 06:05 브리핑에는 실렸는데 낮에 보니 0건. 종합평가에서 "신설 기능이 조용히
반쯤 죽어 있다"고 지적된 그것이다.

**원인.** `refetch_content.py`가 본문을 확보한 뒤 **실제 발행일을 확인해 60일 초과면 삭제**한다
(111행 일괄 purge, 201행 개별 삭제). 해외 규제기관은 문서를 뒤늦게 공개하거나 발행일이 오래된
자료를 올리는 게 정상이라(BEREC 6월 초~7월 초 = 54~59일) 이 규칙에 계속 걸린다.
즉 **foreign_press는 "발행일이 오래돼도 우리에게 새로우면 수집", refetch는 "발행일 60일 지나면
삭제" — 두 모듈이 정반대로 동작**했다. 국내 뉴스는 대부분 당일치라 이 충돌이 드러나지 않았다.

**추적 경로(기록해 둘 만한 것).** cron 삭제 잡은 60일 초과만 지우고(00:00 KST), 정리 스크립트는
01:26 실행이라 05:30 수집분과 시각이 안 맞고, deleted_news에도 기록이 없었다. 남은 후보가
매시 :22 refetch뿐이었고 코드를 보니 발행일 기반 삭제가 있었다.

**조치.** 두 삭제 지점 모두 `category=해외` 제외. **함정: `select` 목록에 category가 없어서** 그대로
뒀으면 `article.get("category")`가 항상 None이라 예외가 조용히 안 먹었다 — 조회 목록에도 추가했다.

**왜 회의록은 멀쩡했나.** 회의록은 대시보드가 지식베이스(document_chunks)를 직접 읽어(app.js:7136)
뉴스 테이블을 거치지 않는다. 해외만 news_feed 경유라 이 규칙에 노출됐다. 같은 기능인데 저장 위치가
달라 한쪽만 죽은 사례.

**피해 범위 정정.** 승격분(주요 정책)은 `해외규제동향_{YYYY}.md`(doc_category=해외동향, 36청크)에
남아 있어 **AI 자문 품질에는 영향이 없었다.** 사라진 것은 미승격 일반 동향 = 대시보드 목록과
브리핑 항목. "아침에 본 기사를 낮에 찾으면 없다"가 실제 증상이었다.

**미해결.** 가장 오래된 해외 기사가 59일차라 오늘은 삭제 대상이 없었다 — 예외가 실제로 작동하는지는
내일 그 기사가 60일을 넘길 때 확인된다.

## #76 (2026-08-03) 구독자 관심분야 태그 — 뉴스 분야 판정 + 구독 필터

**배경.** 키워드를 27→54개로 넓히고 Haiku 선별(#66)을 넣으면서 수집 범위가 주파수·전파를 넘어
요금·규제·보안·AI까지 확장됐다. 알림 제목은 "긴급 전파정책 뉴스"인데 실제로는 번호이동·안테나
공급·광고 위법이 오고, 팀원 5명이 전원 같은 것을 받게 된다.

**태그 6종.** spectrum(주파수·네트워크) / market(요금·시장) / regulation(규제·제재) /
security(보안·개인정보) / ai(AI 정책) / legislation(국회·입법). slug은 ASCII(토큰 절약),
라벨은 한글. `_shared/news_tags.ts`가 Edge 2개의 단일 원본, Python은 사본.
`assembly`가 아니라 `legislation`을 쓴 것은 기존 topic_assembly와 이름이 겹치면 섞이기 때문.

**설계 판단 — 경계 논의에서 나온 것들.**
- **주파수·전파와 통신 인프라를 합쳤다.** 와이파이(비면허 주파수이자 인프라)·기지국(무선국이자
  망 설비)에서 경계가 연달아 무너졌다. 그 선이 이 팀에게 자연스럽지 않다는 신호로 봤다.
  3일 429건 표본에서 합친 태그는 62건으로 요금·시장(98건)보다 작아 쏠림도 없었다.
- **키워드 대응표를 만들지 않았다.** 같은 "기지국"이라도 개설허가·투자 축소는 spectrum 하나,
  공용화 법안이면 +legislation, 구축 미달 과징금이면 +regulation이 붙는다.
- **데이터센터는 "규제받는 통신시설이냐 그냥 건물이냐"로 가른다.** 집적정보 통신시설 보호조치
  대상·IDC 장애 → spectrum, AI DC 정책·제도 → ai, 개별 기업 투자·건설 발표 → 수집 제외.
- **브리핑에는 적용하지 않는다.** [주목 포인트]는 그날 뉴스를 전부 본 AI의 종합 분석이라
  태그로 자르면 "과징금·광고 패소·소송전이 동시에 진행되며 규제 리스크가 커지는 국면" 같은
  통찰이 성립하지 않는다. 브리핑은 팀이 같은 그림을 보는 자리이기도 하다.

**태그가 2차 필터이기도 하다는 발견.** 제안 태그로 최근 30건을 판정해 보니 10건(33%)에 태그가
하나도 안 붙었는데, 그 10건이 경계 기사가 아니라 폭염 지자체 행정·수출 통계 같은 **애초에
들어오지 말았어야 할 기사**였다. 기준문에 "재난문자"가 관련으로 적혀 있어 지자체 폭염 기사가
대량 통과한 것. AI가 틀린 게 아니라 우리가 준 기준이 넓었다. **"어느 분야냐"가 "관련 있냐"보다
답하기 쉬운 질문**이라 판정이 더 정확했다. 기준문의 "관련 없음"을 보강해 대응(지자체 재난 행정·
거시 경제 통계·사회공헌 협약 — 단 제도·규제 쟁점이 있으면 포함).

**구현 — 추가 API 콜 0.** 이미 기사마다 제목+요약 300자를 읽는 Haiku 선별 호출의 도구 스키마에
태그를 얹었다(`relevant_ids:int[]` → `relevant:[{id, tags?}]`). **tags를 item required에서 뺀 것이
핵심** — 모델이 빼먹어도 관련성 판정은 살아남아야 한다(거기서 떨어지면 저장 자체가 안 되고
url UNIQUE라 복구가 어렵다). max_tokens 1500→3000(초과하면 tool_use 절단 → 배치 전체 폴백 =
조용한 리콜 손실). **setdefault(tags,[])를 _screen_text pop 루프 단일 지점에** 둔 것은 PostgREST
벌크 upsert가 키 집합 동질성을 요구하기 때문 — 일부 기사에만 붙으면 upsert 전체가 터져 수집이
전면 중단된다.

**검증.** 선별 회귀 없음(배포 전 4회 평균 9.1% vs 후 10.3%, 자연 변동폭 5.0~11.2% 내).
미판정 0%. 경계 사례가 의도대로: 지하철 와이파이 속도→spectrum / 와이파이 로밍 혜택→market /
공짜 와이파이 해킹→security / KT 기지국 과징금→security+regulation / AI DC 국가전략→ai /
바다 위 데이터센터→무관. 「5G 속도 기만」은 regulation — 기사가 다루는 건 5G 기술이 아니라
표시광고법 위반이라 원칙이 그대로 작동했다.

**워터마크 버그 2건(태그와 별개, 이번에 발견).**
① `if(!msgs.length) continue`가 patch 앞에 있어 발송 0건이면 워터마크가 72h 고정 → 구독자가
태그를 켜는 순간 백로그 폭발(#44 재발). 0건이어도 전진하도록 수정.
② `nowIso` → `max(created_at of eligible)`. 큐를 읽고 워터마크를 쓰는 사이에 크롤러가
`_trigger_delivery()`로 넣은 행이 nowIso보다 과거라 **영구 소실**되던 실제 버그. 크롤러 :47 /
발송 :25 + 즉시 트리거 구조상 실제로 열리는 창이었다.

**UI 판단.** 주요 뉴스를 끄면 태그 버튼을 감춘다 — 눌러도 효과 없는 죽은 버튼을 남기면 "껐는데
왜 켜져 보이나"로 혼동된다(운영자 지적). 선택값은 DB에 남아 다시 켜면 복귀. 옛 화면에서 누르는
경우까지 서버에서 거부. 6개 전부 선택은 `[]`로 정규화(캐논 하나 — 나중에 7번째 태그가 생겨도
"전체" 구독자가 자동 수신). 0개는 거부(토픽 OFF와 같은 결과를 두 상태로 표현하지 않는다).

**구독 큐 중복 적재 방지.** 크롤러 수동 실행이 정기 실행 :50과 겹쳐 두 인스턴스가 동시에 돌았다.
각자 시작 시점에 기존 URL 목록을 읽었는데 둘 다 저장 전이라 같은 기사를 서로 새 것으로 판단 →
24초 간격 동일 내용 2행 → 각자 발송 호출 → 중복 알림. 발송 측 병합은 "한 번의 발송 안"만
처리하므로 못 막는다. 10분 내 동일 내용이면 적재 생략(확인 실패 시에는 그대로 적재 — 확인이
적재를 막으면 안 된다). **동시 실행 잠금은 도입하지 않았다** — 크롤러가 죽으면 잠금이 남아
수집이 조용히 멈추는 실패 모드가 생기고, 이 프로젝트가 반복해서 당한 게 정확히 그 유형이다.

**남은 것.** 큐를 기사 단위로 바꾸는 S3b는 태그 24시간 관찰 후(내일). 그때 오전에 넣은 병합
로직 95줄이 불필요해진다. 관찰 대상: ai 태그 62%(70% 게이트 근접, 국가 AI 컴퓨팅센터 착공
사이클로 보임), legislation 소폭 과태깅(정부-업계 간담회를 입법으로).

**후속(같은 날 저녁) — 태그 칩은 운영자 알림 전용으로.** 구독자 메시지의 🏷 칩을 제거하고
(send-subscriber-briefing 재배포), 대신 운영자 긴급 알림(crawler.send_telegram_alert)에 태그를
표시(`tag_labels()`, HTML·평문 폴백 양쪽). 이유: 판정이 틀렸을 때 팀원은 고칠 방법이 없어
신뢰만 깎이고, 품질 감시는 운영자 몫이다. 운영자용은 개수 제한 없이 전부 표시(과다 부착도
품질 신호)하고 태그 0개는 `미판정`으로 명시(빈 줄이면 알아챌 수 없다). 태그의 필터 역할
(누구에게 보낼지)은 구독자 쪽에 그대로 남아 있다.

**후속 2 — 받기 시각 변경 시 브리핑 재발송 사고.** 운영자가 저녁에 06→07시로 바꾸자 19:25에
오늘 브리핑이 또 왔다. 원인은 h: 핸들러가 last_briefing_sent_date를 null로 초기화한 것 —
"이미 받은 날 + 새 시각이 이미 지난 시각" 조합이면 다음 :25 정시분이 오늘을 "안 보낸 날"로
보고 재발송한다. 따져보면 이 초기화는 이득인 경우가 없다(안 받았으면 기록이 원래 오늘이
아니어서 무의미, 받았으면 중복 유발) → 초기화 삭제. 이제 시각 변경은 "오늘 미수신자는 오늘
새 시각부터, 수신자는 내일부터"로 동작한다.

**후속(2026-08-05).** 브리핑 제목도 같은 이유로 바꿨다 — `📡 전파정책 모닝 브리핑` →
**`📡 통신·전파 정책 모닝 브리핑`**. 그날 브리핑 실물이 개인정보위 과징금(KT 539억)·
공정위 5G 과장광고 소송·국회 법안이었는데 제목만 옛 범위였다. 긴급 알림을
`📡 통신·전파 정책 주요 뉴스 N건`으로 바꾼 것과 이름 계열을 맞춘 것이다.
· 고친 곳: `morning_briefing.py`(프롬프트 출력형식·무뉴스 placeholder), `crawler.py`(죽은 사본).
· **`regenerate_briefings.py`의 `split_law_section` 마커가 문자열 고정 매칭이었다** —
  그대로 뒀으면 과거 저장분(옛 제목)에서 📢 입법예고 분리가 통째로 실패했다.
  `re.search(r'📡[^
]*모닝 브리핑')` 패턴으로 바꿔 옛·새 제목 양쪽을 받는다.
· Edge 렌더러는 `/^📡/`로만 헤더를 판별하므로(`telegram_format.ts:57`) **이모지만 지키면 안전**.
· 이메일 제목의 `[전파정책 AI]`는 시스템 브랜드명이라 그대로 뒀다.

---

## #77 (2026-08-03) 뉴스 클러스터링을 AI 사건 라벨 기준으로

**배경.** 대시보드 뉴스 묶음이 제목 단어 겹침 + 단일연결 연쇄(A~B, B~C면 A·C도 한 그룹)로
91건이 한 덩어리가 됐다(번호이동·자급제 요금제·안테나 공급·5G 광고 위법 혼재). 1차 수정
(대표 기사 기준 + 태그 교집합, 커밋 a31686b)으로 1,358건→145그룹이 됐지만, 같은 사건인데
언론사마다 제목 표현이 다르면("15.7만명 순증…이통3사 1위" vs "순증 1위는 SK텔레콤") 단어
세기가 못 잡는 한계는 남았다.

**구현 — 추가 API 콜 0.** 이미 전 기사를 읽는 Haiku 선별 호출에 `event`(사건 한 줄, 12~25자,
주체+행위+수치 순, 뚜렷하지 않으면 빈 값) 필드를 얹었다. #76의 tags와 같은 원칙 —
**required에 넣지 않는다**(모델이 빼먹어도 관련성 판정은 살아야 함). `news_feed.event` 컬럼은
코드보다 먼저 DDL(키 동질성 사고 방지). max_tokens 3000→5000(라벨 35건 ≈ +1,400tok).
`MAX_EVENT_LEN=40` 절단. setdefault('event','')는 tags와 같은 단일 지점.

**유사도 척도 — Dice가 아니라 겹침 계수.** 글자 2-gram Dice로는 정답 쌍(0.41)과 오답 쌍(0.42)이
겹쳐 임계가 존재하지 않았다. 원인: 같은 사건인데 한 라벨만 수치를 담으면 길이가 2배 벌어지고
Dice는 그 길이 차를 유사도 하락으로 계산한다. **교집합/짧은 쪽(겹침 계수)**으로 바꾸니
0.43~0.47 골짜기가 생겨 0.45로 확정. 실제 붙는 쌍을 전수 확인 — 오병합(「KT 개인정보 유출」↔
「KT 5G 과장광고」 0.42)은 임계 아래에서만 발생. 양쪽 다 event가 있을 때만 이 척도, 없으면
제목 유사도 폴백, 태그 교집합 조건 유지. `_groupTitle`은 최빈 event를 그룹 이름으로.

**결과.** 1,438건 기준 147그룹, 그룹 이름이 「요금제 출시 우리은행 관련」→「토스모바일,
페이스페이 제휴 알뜰폰 요금제 출시」로. 최대 그룹 222건은 커졌지만 전수 확인 결과 100%
KT 펨토셀 해킹 단일 사건이라 의도대로(이질 병합 0). 선별 회귀 없음 — 동일 기사 280건 A/B에서
구 38.2% vs 신 37.1%(실행 편차 범위). 기존 845건 라벨 백필(~$0.3, 일회성).

**알려진 한계.** ①배치(35건)가 갈리면 같은 사건의 라벨 표현이 어긋난다 — 그래서 완전 일치가
아니라 유사도 비교여야 한다(실측: 같은 배치 안에서는 28건이 한 글자도 안 다름, 배치가 갈리면
8가지 변형). ②모델이 드물게 두 사건을 한 라벨로 합친다(「유출 은폐 및 과장광고로 과징금」) —
잦아지면 규칙 5에 "사건이 둘이면 주된 하나만" 추가.

## #78 (2026-08-03) 선별 무관 판정 캐시 — 상시 비용 절반 절감

**발단.** 운영자가 콘솔 비용 이상을 발견: 7월 한 달 $24.49인데 8월은 3일 만에 $22.84.
조사(로그 전수 + count_tokens 실측) 결과 두 갈래였다 — ①8/1~8/2 스파이크는 회의록·발언 백필
**일회성**(~$12, 종료됨) ②8/3부터 뉴스 확대(#66)로 **상시가 7월의 11배**($0.8→$8.7/일).
주의: **Anthropic 콘솔 날짜는 UTC** — "8/2 급증"의 실체는 KST 8/3 새벽 백필이었다. KST로
읽으면 원인 추적이 안 된다.

**상시 비용의 절반($4.4/일)이 재판정 낭비였다.** 무관 판정 기사는 저장되지 않아 다음 실행의
'기존 URL' 대조에 안 걸리고, 네이버 검색에 ~15일 남아 **매시간 다시 판정**됐다(실측: 03:50
438건 판정 4건 통과 → 04:50 443건 판정 — 434건이 그대로 재등장). 기사 1건당 최대 360회.

**수정.** `news_screen_cache`(url PK, title_hash, criteria_hash, judged_at) 신설, 선별 전에
대조해 일치분은 건너뛴다. 설계 판단:
- **제목 지문** — 언론사가 제목을 고치면([속보]→[종합]) 재판정. 운영자 지적으로 추가됐다.
  네이버 검색어 강조 태그는 수집 시 이미 제거돼(_strip_html_tags) 지문이 안 흔들린다.
  **요약문은 지문에 안 넣는다** — 네이버 요약은 검색어 주변 발췌라 검색어마다 달라진다.
- **기준문 지문** — news_relevance_criteria가 바뀌면 자동 무효(옛 기준의 판정이 새 기준을
  가리면 안 됨). 기준문 수정 시 수동 조치 불필요.
- **AI 판정분만 캐시.** 키워드 폴백 탈락은 임시 판정이라 AI가 살아나면 재판정받아야 한다.
- **전 단계 fail-open** — 캐시 로드·기록·청소 실패는 전량 판정으로 돌아갈 뿐(돈만 더 쓰고
  기사는 안 놓침). TTL 20일(노출 15일+여유), 크롤러가 매 실행 청소.
- **경보** — 캐시 300행+ 인데 판정 150건+ 이면 운영자 텔레그램(캐시가 조용히 깨져 비용이
  원상복귀하는 걸 청구서가 아니라 당일에 알기 위함). 첫 실행(캐시 0)은 안 울린다.
- 로그가 `[선별] 수집 N → 캐시 건너뜀 K → 판정 J → 관련 M`으로 바뀌었다 — 로그를 눈으로
  비교하던 종전 형식과 다르니 참고.

**실측 검증.** 1회차(캐시 냉) 수집 462 → 판정 462 → 관련 6 / 2회차(온) 수집 456 → **캐시
건너뜀 455 → 판정 1** → 관련 1. 예상 절감 월 $132($260→$128). GitHub Actions 쪽도 같은 DB
캐시를 보므로 Actions 크롤러가 복구되면 이중 판정도 자동 방지된다.

**함께 확인된 것(별건).** ①보도자료 백필은 Anthropic 비용 0(press_backfill은 AI 판정 없이
키워드 모드) — 운영자가 의심했으나 무죄. ②GitHub Actions 크롤러(daily_crawl.yml)가 현재
아무것도 저장하지 않음(PC 런의 '기존' 건수가 통과분만큼만 증가) — 복구는 캐시 이후에 해야
비용이 2배가 안 된다. ③남은 절감 후보: 긴급도+요약 콜 통합($0.9/일)·긴급도 피드백 블록
배치화($0.6/일)·참고 등급 온디맨드 요약($0.9/일) — 태그·라벨 안정화 후 별도 판단.

## #79 (2026-08-03) /ask 웹 출처 표기 + /law 자연어 법령 검색

**/ask 출처 사고.** "일본 28GHz 활용현황 보고서" 질문에 총무성 수치·라쿠텐 발언이 담긴 답이
왔는데 📚 참조가 전부 국내 법령이었다(운영자 지적: "수치나 현황에 대한 근거는 표시되지 않는다").
원인 2중: ①footer가 "검색돼 프롬프트에 들어간 내부 자료"를 전부 나열할 뿐 실제 사용 여부를
안 따짐 ②웹 검색 인용은 스트림 수신부가 text_delta만 담고 citations_delta를 버려서 어디에도
안 남음. 수정: 스트림에서 citation(url·title)을 수집해 `🌐 웹 출처`로 별도 표기(모델이 본문에
실제 인용한 문서만 citation으로 오므로 "진짜 근거" 목록으로 신뢰 가능), 내부 자료는
`📚 검색된 내부 자료(전부 반영된 것은 아님)`로 라벨 정직화. chat_logs에는 `[웹] 제목 (url)`
접두사로 기록(splitSources 접두사 관례). 재검증: 같은 질문에 총무성 공식 PDF(soumu.go.jp)가
웹 출처 1번으로 표기됨. 대시보드(app.js 사본)는 봇 안정 확인 후 동일 적용 예정.

**/law 개편 — 조문 즉답에서 "관련 법령 찾기"로.** 운영자: "몇조가 뭐냐고 물어볼 만큼 조항을
외우는 게 아니라, 궁금한 사항이 어떤 법과 관련돼 있는지 알고 싶은 게 대부분." 종전 /law는
자연어를 넣으면 "/ask를 쓰세요" 안내만 했다. 개편: 자연어 질의 → searchLawArticles(조문 검색,
"3G 종료"류 질의로 이미 실전 조정된 것) + kb 요약 → **Haiku** 법령 한정 답변(관련 조항 3~6개
+ 각각 왜 관련인지). /ask와의 경계를 프롬프트에 명시 — 뉴스·동향·시사점 금지, 법령 내용만.
조문번호 패턴("OO법 N조")은 종전 즉답 경로 그대로(비용 0). 모델을 Sonnet이 아닌 Haiku로 한
이유: 조문은 검색이 찾고 모델은 관련 이유만 설명하는 좁은 일이라 3배 비쌀 이유가 없다.
승인 불필요(팀 조회 기능), 일일 상한 10회(운영자 지정, law_count/law_count_date — ai_count와
동일 패턴). 검색 0건이면 미등재 안내 + 법령센터 링크. /ask처럼 백그라운드 실행(webhook 200
선반환, typing 표시 유지). 실측: "3G 종료 관련된 법안" 13.5초 완료.

**후속 — /law가 의미 검색을 안 써서 등재 고시를 통째로 놓친 건.** 운영자 질의 "전기통신사업법에서
5G 커버리지 맵 공개와 관련된 항목"에 "직접 관련 조문을 찾지 못했습니다"가 나왔다. 실제로는
「전기통신역무 선택에 필요한 정보 제공 기준」(과기정통부고시 2019-27호)이 **10개 조문 전부
정상 등재**돼 있었고(is_approved/current/article_no 모두 정상), 제5·6조가 정확히 그 내용이다
(75m×75m 격자 산출, 지도 형태로 홈페이지 게시).

원인은 **어휘 간극**이다 — 이 고시는 '커버리지'라는 말을 한 번도 쓰지 않는다. 법령 용어는
'이용가능 지역'·'지도 등의 형태'다. answerLawQuery가 searchLawArticles(키워드 ilike)만 쓰고
있어서 글자가 안 맞으면 못 찾았다. 같은 질문에서 요약층(kb, 임베딩 검색)은 제대로 찾아
답변에 75m 격자가 등장했다 — **자료가 아니라 검색 방식이 문제**였다는 결정적 증거.

수정: answerLawQuery가 searchChunks(키워드+trgm+임베딩 3중 하이브리드)를 함께 돌리고,
그 결과 중 **article_no가 있는 것(=조문)만** 골라 키워드 검색분에 보강한다(보도자료·논문·
계획서류는 /law의 답이 아니므로 searchLawArticles와 같은 기준으로 배제). 두 갈래를 병렬로
돌려 지연은 늘지 않는다.

**교훈:** 실무 용어와 법령 용어는 자주 어긋난다(커버리지↔이용가능 지역, 3G 종료↔휴지·폐지).
키워드 검색만으로 법령을 찾는 경로를 새로 만들지 말 것 — 반드시 의미 검색을 함께 태운다.

**후속 2 — 의미 검색을 태워도 안 됐던 진짜 이유(실측).** 위 수정 후에도 같은 질문이 실패했다.
match_chunks_semantic을 직접 돌려 원인을 확정: 정답인 고시 제5조의 유사도가 **0.418**인데
상위권(무선국 박사논문·별표·부칙류)이 0.50~0.54였다. 즉 **정답이 40위 밖**이라 임계·건수를
올려도 못 올라온다(게다가 HNSW ef_search 기본값 탓에 300건을 요청해도 ~33건만 훑는다 —
threshold 0.0에서도 33행만 반환되는 것으로 확인). 조문 원문 임베딩은 voyage-4-lite인데
한국어 법령에서 변별력이 약해 전 코퍼스가 0.4~0.55의 좁은 띠에 뭉쳐 있다. 반면 요약층은
법률 특화 **voyage-law-2**라 같은 질문에 이 고시를 정확히 지목했다(운영자: "AI 자문으로 하면
법 내용을 바로 잘 찾는다" — 자문이 요약층을 함께 보기 때문).

**최종 수정 — 요약층 다리.** 요약층(kb)이 짚은 법령의 **실제 조문을 doc_name으로 직접 조회**해
프롬프트에 넣는다. 검색 순위 운에 기대지 않는 확정 경로. 여기서 한 번 더 걸렸다: 질문어 겹침
상위 4개만 고르니 정작 핵심인 제6조(지도 형태로 홈페이지 게시)가 5순위로 잘렸다 — '목적'·'정의'
같은 상투 조문이 전기통신·정보·제공 같은 흔한 단어로 점수를 먼저 가져간다. → **조문 10개 이하
법령은 고르지 말고 통째로** 넣고(부칙·별표·서식 제외), 큰 법령만 점수 상위 5개, 전체 14개 상한.
검증: 수정된 프롬프트를 그대로 재현해 Haiku를 호출한 결과 제6조·제5조·제4조가 정확히 나왔다.

**남은 한계.** 이 다리는 요약층이 그 법령을 짚었을 때만 작동한다. 근본 해결은 document_chunks
전체를 voyage-law-2로 재임베딩하는 것(4만+ 청크, 비용·시간·전체 검색 품질 영향) — 며칠 실사용
후 놓친 사례가 더 나오면 판단.

**후속 3 — 진짜 원인은 모델이 아니라 검색 대상이었다(A/B 실측).** 운영자 질문: "질문마다
세팅값을 바꿀 순 없을 텐데 근본적으로 바꾸는 방법은 없나." 맞는 지적이라 재임베딩을 결정하기
전에 **실험부터** 했다.

*실험 1 — 모델 교체가 답인가?* 정답 조문 2건 + 앞서 상위를 먹은 노이즈 12건을 놓고 두 모델로
각각 임베딩해 순위를 비교했다.
  voyage-4-lite : 정답 최고 13위/14    voyage-law-2 : 정답 최고 7위/14
법률 특화 모델로 바꿔도 여전히 부칙·별표 아래였다. **34,000건 재임베딩은 답이 아니다** —
비용($2~3, 생각보다 쌈)보다 "고쳐지지 않는다"가 기각 사유다.

*실험 2 — 그럼 뭐가 상위를 먹는가?* 색인된 청크의 구성을 셌다:
  조문번호 없음 40.6%(보도자료·회의록·논문·PDF) / **실제 조문 33.1%** / 별표 17.9% /
  부칙 5.5% / 서식 2.9%
"몇 조냐"를 묻는 /law인데 **검색 공간의 2/3가 조문이 아니었다.** 부칙(시행일 한 줄)·서식·별표가
상위를 독식한 이유는 문서 길이 편향 — 긴 표가 여러 어휘를 조금씩 품어 아무 질문에나 약하게 걸린다.

**수정 — `match_law_articles_semantic` 신설(조문 전용 의미 검색).** article_no가 있고
`^(부칙|서식|별표|별지)`가 아니며 파일 문서(.pdf/.md/.docx/.hwp)가 아닌 것만 대상.
별표를 뺀 것은 2차 실측 후 결정 — 부칙·서식만 뺐더니 "기지국 개설 허가 절차"에서
「별지 8(공용화 및 환경친화형 기지국)」이 1~3위를 먹고 전파법 21조가 5위로 밀렸다.
키워드 검색(searchLawArticles)은 별표를 그대로 보므로 "별표 N"을 명시하면 여전히 나온다.

**HNSW를 일부러 쓰지 않는다(`+ 0.0` 트릭).** HNSW는 ef_search 기본값 탓에 후보를 ~40개만
훑어서 필터를 걸면 남는 게 거의 없다(실측: match_count=300에도 33행). ef_search 상향은
슈퍼유저 권한이 필요해 Supabase 관리형에서 불가(`permission denied to set parameter`).
조문 대상이 ~1.5만 건뿐이라 전수 정확 검색이 220~620ms로 충분하고, 근사 검색의 누락이 사라진다.

**효과(실측 5개 질의).** 기지국 개설 허가 절차 → 전파법 21조(무선국 개설허가 등의 절차) **5위→1위** /
개인정보 유출 신고 → 개인정보 보호법 시행령 40조·법 34조 **1·2위** / 무선국 면허세 → 전파법 19조 1위 /
3G 종료 → 전기통신사업법 21조 1위. 5G 커버리지 건만 여전히 의미 검색으로는 안 잡히는데,
그 사각지대는 요약층 다리(③)가 덮는다.

**교훈.** 검색이 안 맞을 때 모델·임계값부터 손대지 말 것. **무엇을 검색 대상에 넣었는지**를 먼저
세어 볼 것 — 이번 건은 색인의 2/3가 답이 될 수 없는 것들이었고, 그게 모든 튜닝을 무력화했다.

**후속 4 — /law가 시행령만 인용하고 상위 법률을 빠뜨린 건.** "개인정보 유출되면 언제까지
신고해야 하나" 답변이 시행령 제40조·제39조(72시간)만 들고 **개인정보 보호법 제34조를 생략**했다.
검색에서는 법 34조가 2위로 잡혔는데도 답변에서 빠졌다. 보고서에 「시행령 제40조」만 인용하면
근거가 반쪽이다 — 정확한 인용은 「법 제34조제3항 및 같은 법 시행령 제40조」다.

**원인 2중.** ①프롬프트에 위임 관계 규칙이 없었다 ②프롬프트에 조문을 **검색 점수 순**으로
넣어 시행령이 앞서고 법률이 뒤로 밀렸다(모델은 앞쪽을 중요하게 본다).

**수정.** ①규칙 4개 추가 — 위임 관계 명시(법률은 「지체 없이」, 시행령이 72시간으로 구체화 식으로
관계를 한 줄 설명) / 검색된 상위 법률 조문 생략 금지 / 기관명 임의 병합 금지("보호위원회 또는
전문기관(KISA)"을 "보호위원회(KISA)"로 적으면 같은 기관으로 읽힌다) / 법 위계 순 제시.
②프롬프트 주입 순서를 `lawRank` 기준 **법 위계 순**으로 정렬(법률>대통령령>부령>고시).

**한국 법령 구조상 반복될 패턴이다** — 기한·금액·요건은 대개 하위법령 위임이라, 이 규칙이 없으면
어떤 질문에서든 같은 누락이 난다. 참고로 침해사고(정보통신망법 48조의3 「즉시」→시행령 58조의2
「24시간」)도 정확히 같은 구조이고, 2026.10.1부터 24시간이 법률 본문으로 올라온다.

## #80 (2026-08-03) 법령 위임 대응표(3단비교 정본) — /law가 상·하위 조문을 함께 답하게

**발단.** #79 후속에서 /law가 "개인정보 유출 신고 기한"에 시행령 제40조(72시간)만 답하고 상위
법률 제34조를 빠뜨렸다. 프롬프트 규칙(위임 관계 명시)과 주입 순서 정렬(법 위계 순)로 1차 대응했으나,
운영자가 정곡을 짚었다 — **"법령의 3단비교가 있으니, 그 법안에 있는 시행령과 고시까지 가져와서
설명하게 하면 되지 않나."** 검색·프롬프트로 "잘 되기를 기대"하는 대신, 법제처가 확정한 대응표를
그대로 따라가면 된다.

**기존 데이터의 한계.** #65에서 이미 3단비교를 썼지만 `law_graph_edges.description`에 법령쌍당
**앞 5개 샘플만** 문자열로 남기고 나머지를 버렸다(개인정보 보호법 → 시행령 엣지에 제34조 대응이
없는 이유). 그래프 시각화에는 충분했지만 조문 조회에는 못 쓴다.

**API 실측 (thdCmp knd=2).** 응답 경로는
`LspttnThdCmpLawXService.위임조문삼단비교.법률조문` (법률 조문 배열). 각 행에 위임이 있으면
`시행령조문`/`시행규칙조문` 키가 붙고, **같은 법률 조문이 여러 하위 조문에 위임되면 행이 나뉘어
온다**(법 제34조 행이 2개 → 각각 시행령 39조·40조). 자식 dict의 `법령명`은 **타계열도 나온다**.

  전파법 248조 중 171조 대응(시행령 147 / 시행규칙 8 / **무선설비규칙 16**)
  전기통신사업법 236조 중 149조(시행령 139 / **방송통신설비의 기술기준에 관한 규정 9** / 회계규정 1)
  정보통신망법 217조 중 103조 · 개인정보 보호법 201조 중 114조

타계열 위임은 문서명 추측(family)으로는 절대 못 찾는 것이라 값이 크다.

**한계 — 고시는 안 들어온다.** 3단비교는 이름 그대로 법률-시행령-시행규칙 3단이라 행정규칙(고시)은
범위 밖이다. 운영자 질문의 "고시(규칙)까지"는 이 API로 안 되고, 고시 본문의 "법 제N조에 따라"를
역추출하는 별건이 필요하다.

**구현.** `law_delegations` 테이블(parent_law/parent_article/child_law/child_article + 조제목·종류,
unique 4키) + `sync_law_delegations.py`(등재 법률을 DB에서 뽑아 API 적재, upsert 재실행 안전,
--dry-run/--only). /law는 찾은 조문의 위·아래 대응 조문을 이 표로 확정 조회해 함께 제시한다.
검색이 무엇을 찾아오든 위임 관계는 항상 붙는다.

## #81 (2026-08-03) 고시 위임 역추출 — 관계도의 고시 고립 해소 (0.9% → 48.6%)

**발단.** 위임 대응표(#80)를 만들고 보니 3단비교는 법률-시행령-시행규칙 3단까지만 커버하고
**고시(행정규칙)는 범위 밖**이었다. 그런데 이 KB는 고시가 가장 많다(고시 113 + 훈령·예규 14 vs
법률 23). 관계도 실측: notice 노드 220개 중 위임 엣지가 있는 것이 **단 2개(0.9%)** — 고시가
사실상 떠 있었다. 운영자 질문("법령-시행령-규칙-고시가 다 연결되는 것 아닌가, 관계도 개선을
기대할 수 있나")이 이 작업의 직접 계기.

**다행히 고시 제1조(목적)에 위임 근거가 규칙적으로 박혀 있다** — 「전파법」 제25조제2항,
「전기통신사업법」제56조의2제2항 식. 실측 127문서 중 95개(75%)에 이 패턴 존재.

**구현 — `sync_notice_delegations.py` (AI 미사용, 비용 0).** 정규식 추출 4단계 우선순위:
①「법령명」제N조 ②괄호 없는 명시형(KB 실재 법령명일 때만) ③같은 법/동법 시행령(직전 앵커 유도)
④법 제N조/영 제N조(약칭 정의나 유일 법률명으로 확정될 때만 — **확정 못 하면 버린다. 틀린 연결은
없는 것보다 나쁘다**). `child_article='전체'` 고정 — 제1조 근거는 문서 단위 수권이지 조문 대응이
아니므로 '1조'를 넣으면 없는 사실이 생긴다. 가운뎃점은 **대조할 때만** 통일(저장은 DB 정본 표기) —
여기는 사람이 쓴 본문이라 ·/ㆍ가 실제로 엇갈렸다(#80의 API 경로와 다른 점).

**정확도 반복 개선.** 무작위 15문서 표본 검사를 3회 반복: 92.6% → 95.8% → **100%**.
잡은 오답 3건: ①제1조 청크가 없어 첫 청크로 폴백했더니 적용제외 서술을 근거로 오인(→ 폴백에
목적 조문 시작 문구 검증 강제) ②약칭 정의 괄호가 끼면 '시행령' 앵커를 놓침(→ lookahead에 괄호
허용) ③원문 오타 '제15조12'를 15조로 오독(→ 공백 없이 붙은 숫자만 조가지로 해석).

**적재.** 대상 136문서 → 105문서/230행, 상위 법령 조인 90%. law_delegations 1,586 → 1,816행.

**관계도 반영.** `law_graph_edges`에 source='delegation'(weight=5) 신설 — **CHECK 제약을 먼저
확장하고 적재**(#65 사고 순서 준수: 제약 확장 → 적재 → 실제 적재분을 다시 읽어 그것만 억제 근거로
사용 → citation/family/thdcmp). 우선순위 delegation > thdcmp > family. 3단비교가 뱉는 무관 법령
(부처 직제 등) 23건은 스킵해 그래프 오염 방지.

  notice 노드 위임 연결: 2/220 (0.9%) → **107/220 (48.6%)**
  delegation 엣지 198 신설, thdcmp 40→8(대체), 총 엣지 2,829 → 3,004

**한계.** 조문 범위 표기(제18조의5부터 제18조의9까지)는 양 끝만 담긴다. 미추출 31건은 대부분
목적 조문에 근거가 실제로 없는 문서(주파수 분배표, 상호인정협정 등).

---

## #82 (2026-08-04) 뉴스 상시비용 절반 절감 + OKF 전수 재작성(246건) + 고시 위임 수기 확정

세 갈래가 하룻밤에 겹쳤다. 공통 뿌리는 **"조용히 잘못돼 있는 것을 어떻게 알아내는가"** 다.

### 1) 뉴스 상시비용 — 월 $128 → 약 $54

**발단.** 7월 한 달 $24.49였던 API 비용이 8월 3일 만에 $22.84가 됐다. 딥리서치로 코드 전량·실DB·
무료 `count_tokens` 실측을 돌려 두 갈래를 분리했다 — 일회성(회의록 백필 ~$12, 종료됨)과
**상시(뉴스 확대로 7월의 11배)**. 상시분에서 두 가지 낭비를 찾았다.

**㉮ 같은 기사를 두 번 읽고 있었다.** 선별 AI가 이미 모든 후보의 제목·요약을 읽는데, 통과분을
**긴급도 AI가 처음부터 다시 읽었다**(하루 ~600콜). 선별 도구 스키마에 `urgency` 필드 하나를 더해
한 콜로 합쳤다. → **월 $33 절감.**

**㉯ 아무도 안 읽는 요약을 만들고 있었다.** 기사의 75%가 '참고' 등급인데 대시보드 읽힘률은
**0.8%**(7일 1,219건 중 10건). 게다가 **06시 브리핑은 요약을 안 쓴다** — `content`를 400자씩 직접
읽는다(`morning_briefing.py:59,216`). 구독자·긴급 알림도 요약 미사용(grep 전수 0건). 즉 '참고'
요약은 만들어 놓고 99%가 버려지는데 브리핑·알림 품질과는 무관했다. 온디맨드로 돌렸다
(대시보드는 원래 클릭 시 생성해 DB에 되쓰는 경로가 있었다 — `app.js:3374~3448`).
→ **월 $41 절감.**

**기각한 것들(실측 근거).** 프롬프트 캐싱은 프리픽스가 **1,014토큰 < Haiku 4.5 최소 4,096토큰**이라
`cache_control`을 걸어도 조용히 캐시가 안 생긴다(오류 없이 `cache_creation_input_tokens: 0`).
Batch API 야간 이연은 **비용이 기사당 과금이라 시점을 미뤄도 총량이 안 준다**. 요약 입력 다이어트는
본문이 이미 p90 1,500자라 줄일 게 없다. 야간 수집 빈도 축소도 같은 이유로 절감 0.

**안전장치 3겹.** ①`urgency`를 `required`에서 뺐다 — 모델이 빼먹어도 관련성 판정은 살아야 한다
(태그·사건 라벨과 같은 원칙, #76). ②빠진 기사는 기존 `classify_urgency`가 개별 판정한다(폴백 존치).
③**백필 쿼리에도 같은 `.neq('urgency','참고')`를 걸었다** — 이걸 빠뜨리면 생략한 요약을 백필이
시간당 30건씩 도로 만들어 절감이 0이 된다.

**밤새 실측(12회 수집).** 개별 긴급도 호출 **0건**, 선별 배치 실패 0건, 캐시 적중률 93%,
'참고' 비율 73%(배포 전 75%). `generate_summary()`가 '참고'에 호출된 횟수 0.
**남은 관찰 항목**: 긴급 등급이 밤새 0%였다(배포 전 10%). 표본 22건·야간이라 판단 보류 —
낮 데이터에서도 안 나오면 판정 재료가 본문 600자 → 수집요약 300자로 줄어든 영향이므로 되돌린다.

**오탐 하나.** 배포 후 '참고' 16건 중 11건에 요약이 있어 실패로 보였으나, 추적해 보니
①배포 전 저장분 5건 ②**06시 브리핑 역저장**(`crawler.py:2203` — 브리핑에 이미 쓴 문장을 되돌려
저장) 2건 ③**해외 규제동향**(`foreign_press.py:486` — 번역 판정의 부산물) 4건이었다.
**셋 다 추가 API 호출이 0인 경로**다. 요약이 있다는 사실만 보고 실패로 판정할 뻔했다.

**미리보기 저하 보완.** '참고'에 요약이 없으면 목록 미리보기가 빈칸이 된다(전체의 75%). 어제 넣은
**사건 라벨(`event`)로 폴백**하게 했다(`app.js` `newsPreviewHtml`). `content`로 폴백하지 않은 이유는
목록 쿼리에 본문을 넣으면 페이지당 수백 KB가 더 실리기 때문.

**부수 버그.** `screen_news_items` 끝의 주파수 안전망 루프가 **탈락 기사까지 돌아**
「폭격에 흩어진 화폐 역사의 파편」 같은 무관 기사에 "전자파→spectrum 추가" 로그를 남기고 있었다.
저장이 안 되니 실해는 없으나, 함수 주석이 "보정 로그가 잦아지면 프롬프트를 고치라는 신호"라고
정해 둔 모니터링이 오염된다. 루프 대상을 `items` → `passed`로 좁혔다(`_screen_text` 제거는
반환 규약대로 전체 대상 유지).

### 2) OKF 전수 재작성 246건 — 잘림 25건이 드러낸 더 큰 문제

**발단.** 적재 게이트(#81 직후 신설)로 전수 점검하니 **248건 중 25건이 문장 중간에서 잘려**
있었다. 「재난 및 안전관리 기본법 시행령」이 `…공무원이 업무 관련 출` 에서 끝나는 식.
실무 체크리스트·Citations가 통째로 없었다. 원인은 **한 세션이 대량 생산하며 출력 한도에 몰린 것**
이라, max_tokens 상향으로는 안 고쳐진다(최근 배치는 Haiku 산출물이 아니라 세션 작성물이었다).

**잘린 25건을 고치다 더 나쁜 것을 발견했다.** 재작성하며 원문과 대조하니 **잘림과 무관한 실질
오류**가 쏟아졌다:
- 표시광고법 시행령: 실증자료 제출 기한 **「60일」 → 법정은 15일**(60일은 자율규약 심사 통보 기한)
- 데이터산업기본법: 과태료 요건이 **정반대**(「인증 표시 미사용」 → 원문은 「인증 없이 표시」)
- CSAP 보안인증고시: **유효기간 「3년」이 사실무근**(고시에 연수 규정 자체가 없고 시행령은 5년)
- 클라우드법 시행령: 디지털서비스 심사위원회를 **보안인증 심의기구로 오배치**(별개 기구)
- 약관규제법: 약관 **정의를 제30조로 표기**(정의는 제2조, 제30조는 적용제외)

**그래서 비잘림 문서 8건을 표본 감사했다.** 결과: 심각 0.375건/문서. 수치는 20여 개 대조에서
전부 정확했고, **잘린 배치의 수치 창작·왜곡이 재현되지 않았다**. 대신 다른 약점이 드러났다 —
①**원문 후반 조항(별표·부칙·재검토기한) 통째 누락**(4건 중 3건) ②**주체 뒤집힘**(「사업자가 요청하면
장관이 확인」 → 「장관이 확인을 요청」) ③조·항·호 번호 오배정.

감사관 둘 다 "전수 재생성은 비용 대비 정당화되지 않는다"고 판단했으나, **0.375건/문서를 246건에
적용하면 약 90건의 심각 오류**다. 법령 자문의 근거층으로는 무시할 수 없어 운영자가 전수를 지시했다.

**감사가 짚은 3가지 약점을 재작성 지시문에 그대로 넣은 것이 이번 작업의 핵심**이다. "별표에 실제
수치가 있으면 표로 옮겨 적어라, 「별표와 같다」로 넘어가지 마라", "조문마다 주어를 확인하라" 같은
구체 지시가 결과를 갈랐다.

**실행.** 워크플로 엔진으로 82배치 × 3개 병렬 × 배치당 3건. 7시간 48분, 1,400만 토큰,
**실패 0건**. 문서당 2단계 쓰기(Write→Edit)를 강제해 잘림을 원천 차단했다.

**"원문 없으면 손대지 마라"가 가장 중요한 지시였다.** 업무안내·ITU-R 권고·용어집 46건은
`document_chunks`에 조문이 없다. 이걸 재작성하게 두면 **상상으로 채운다**. 46건이 그대로 보존됐다.

**결과.** 게이트 거부 25 → **0건**. 청크 3,394 → **5,528개(+63%)** — 이 증가분이 곧 복원된
후반 조항이다. 임베딩 NULL 0. 재작성 후 12건을 다시 원문 대조해 **심각 오류 0건** 확인.
두 검증관이 공통으로 짚은 것: 원문이 이미지이거나 깨진 구간에서 **수치를 지어내지 않고
"원문 확인 필요"로 남긴 절제**가 일관됐다.

### 3) 고시 위임 수기 확정 14건 — 관계도 55.5%

**발단.** OKF 재작성 후 관계도 3종을 돌렸더니 **수치가 하나도 안 변했다**(엣지 3,004 → 3,004).
당연했다 — 관계도는 `document_chunks`(조문 원문)와 3단비교 API를 읽는데, 바꾼 건 `kb_documents`
(요약층)다. **재실행 안전성만 확인된 셈.**

대신 #81에서 남은 **미추출 31건**을 팠다. 정규식은 고시 제1조에 박힌 위임 문구만 뽑는데,
제1조가 아예 없거나(협정문·분배표·공고) 제1조에 근거를 안 쓰는 문서들이다.

**역방향 확인이 열쇠였다.** 고시 쪽이 아니라 **상위 법령 조문에서** "…을 정하여 고시한다" 문구를
찾는 것. 예: 전기통신사업법 제62조제2항이 「중요한 전기통신설비」를, 전파법 제9조제3항이
「주파수 분배표」를 직접 지목한다. 조사 결과 **확정 15 / 추정 12 / 없음 4**.

**확정만 채택했다(14건).** 판단 근거:
- 추정 12건은 「법·영에서 위임한 사항」식 **포괄 위임이라 조문을 특정할 수 없다**.
  잘못된 조문에 엣지를 걸면 없는 관계보다 나쁘다.
- 「무선통신보조설비 화재안전기술기준(NFTC 505)」은 근거가 확정(소방시설법)이나 **상위 법령이
  이 KB에 없어** 제외. 소방시설법을 적재하면 되살릴 것.
- 「이용약관 인가대상 기간통신서비스와 기간통신사업자」는 **2020년 유보신고제 전환으로
  전기통신사업법에 '이용약관 인가' 조문이 사라졌는데 고시는 인가 문언을 유지**하고 있다.
  조문 대응 불명 → 의도적으로 비워 뒀다. **운영자 확인 대상.**

**`MANUAL_BASIS` 표를 스크립트에 넣었다**(DB 직접 삽입이 아니라). 이유: 17시 자동 실행의
`prune_stale`이 수기 행을 지운다. 그리고 **정규식이 성공하면 그쪽이 이기도록** 했다 —
원문이 개정돼 제1조에 근거가 생기면 수기 표가 자동으로 비켜선다.

**결과.** 위임 엣지 198 → **212**, 엣지 총계 3,004 → **3,018**,
**고시 위임 연결 48.6% → 55.5%**. 새로 연결된 것에 「중요한 전기통신설비」·「전기통신설비
의무제공대상 기간통신사업자」·「주파수 분배표」 등 SKT 실무 상용 고시가 포함된다.

### 이번 밤에서 남길 교훈

- **"요약이 있다"만 보고 실패로 판정할 뻔했다.** 어느 경로가 만들었는지 추적해야 한다.
- **잘림 게이트가 잡은 것은 잘림뿐이고, 그 옆에 더 큰 오류가 있었다.** 형식 검사와 내용 검사는 다르다.
- **감사의 가치는 "재생성해야 하나"라는 답이 아니라 "무엇이 틀리는가"라는 목록에 있었다.**
  감사관 둘 다 전수를 반대했지만, 그들이 찾은 약점 3가지가 재작성 지시문의 뼈대가 됐다.
- **원문이 없으면 손대지 않는 것이 최고의 품질 장치다.**

---

## #83 (2026-08-04) 텔레그램 봇 두 사고 — 답변 5중 발송 + /law가 실무 용어를 못 찾음

같은 날 오전에 둘이 겹쳤다. 둘 다 **"기능은 멀쩡한데 입구가 틀렸다"** 는 성격이다.

### 1) `/law` 답변이 5번 발송 — 웹훅 재전송

**발단.** 운영자가 `/law 리파밍 관련 법 조항이 어떤게 있지?` 를 **한 번** 보냈는데 답변이 연달아
5번 생성됐다. 진행 중이라는 보고를 받고 즉시 차단부터 했다 — 해당 chat_id의 일일 한도를 999로
채워 추가 생성을 끊었다(코드 배포보다 빠르고, 한도는 날마다 리셋되므로 되돌리기도 쉽다).

**진단의 결정적 단서는 `law_count = 1`이었다.** 답변이 5번 나갔는데 카운터는 1이다. 즉
**웹훅이 `/law`를 한 번만 처리했다**는 뜻이고, 답변 분할 발송은 `splitByLines`가 최대 3개로
제한하므로 5회를 설명하지 못한다. 남는 설명은 하나 — **텔레그램의 재전송**이다.

**실행 로그가 이를 뒷받침했다.** telegram-webhook 실행 시간이 상시로
`53,294ms / 45,751ms / 56,224ms / 54,716ms / 51,253ms / 56,381ms` 를 찍고 있었다.
**텔레그램 웹훅 타임아웃은 60초** — 문턱 바로 아래에서 돌고 있었던 것이다. 그날 아침
OKF 5,528청크 적재 + 관계도 재구축 + 561건 크롤이 겹쳐 DB가 느려지자 60초를 넘겼고,
텔레그램이 같은 업데이트를 재전송했다. 재전송분은 `getSub`이 실패해 카운터를 못 올리고
그냥 통과했기 때문에 `law_count`가 1로 남았다.

**해결 — `update_id` 중복 차단(`telegram_updates` 테이블).** 텔레그램은 재전송 시
**같은 `update_id`** 를 쓰고 새 질문은 다른 번호를 받는다. 최초 1건만 통과시키면
**중복은 막히고 새 질문은 그대로 지나간다**(운영자 요구: "중복이 안되게, 그렇다고 새로운
질문이 안 넘어가게도"). 웹훅 진입 즉시 upsert(ignoreDuplicates)로 선점하고, 0행이면 조용히 200.

**설계 판단 3가지**
- **fail-open**: dedup 조회가 실패하면 통과시킨다. 중복 몇 건이 무응답보다 낫다.
- **청소는 1% 확률로만**(`update_id % 100 === 0`) — 매 요청에 DELETE를 붙이면 그게 또 지연 요인이다.
- **RLS 켜고 정책 0개** = service 전용.

**이 조치가 새로 만든 위험을 기록해 둔다.** 전에는 재전송이 *의도치 않은 안전망*이었다 —
원 처리가 죽어도 재전송이 대신 답했다. 이제 그 경로를 막았으므로, **원 처리가 실패하면
답변이 아예 안 온다.** 그래서 근본 대책은 여전히 **200 즉시 반환**(현재 웹훅은 DB 조회·기록·
안내 메시지를 세 번 기다린 뒤에야 200을 돌려준다)이며, 이건 라우팅 전체를 감싸는 구조 변경이라
같은 날 함께 배포하지 않고 분리했다(#82 OKF 작업에서 단계를 나눈 것과 같은 이유 — 섞으면
문제 원인이 갈린다).

### 2) `/law`가 「리파밍」을 못 찾음 — 실무 용어와 법령 용어의 간극

**증상.** 중복이 잡힌 뒤 다시 물으니 이번엔 답변이 이상했다. AI가 「리파밍」을
**「리팜밍(reperfecting·resurfacing·relapping)」** 이라고 엉뚱하게 풀고, 약관규제법·전자상거래법을
근거로 들며 "리파밍을 규율하는 상위 법률 조항은 검색 범위에 없다"고 답했다.

**운영자 지적: "시멘틱검색(의미기반)이 되도록 해 달라 하지 않았나?"**
→ **의미 검색은 정상 작동하고 있었다.** 실측으로 확인했다:

| 질의 | 1위 결과 | 유사도 |
|---|---|---|
| `리파밍 관련 법 조항이 어떤게 있지?` | 약관규제법 제30조 | **0.441** (잡음) |
| `주파수 회수 또는 주파수 재배치` | **전파법 제6조의2** | **0.543** (정답) |

같은 엔진에 법령 용어로 물으면 정답이 1위다. **문제는 검색기가 아니라 질문의 어휘**였다.
「리파밍(refarming)」은 업계에서만 쓰는 말이고 **법령에는 단 한 번도 안 나온다** — 우리 법은
「주파수회수」·「주파수재배치」라고만 쓴다. 임베딩 모델은 한국어 법령으로 학습돼 이 음차 외래어를
어디에도 연결하지 못한다. 검색이 아무것도 못 물어오니 **모델이 단어 뜻을 추측한 것**이 「리팜밍」이다.

**#79와 같은 계열이다.** 「5G 커버리지 맵」이 안 잡히던 사건 — 그 고시는 '커버리지'를 한 번도
안 쓰고 '이용가능 지역'이라고 쓴다. 그때는 의미 검색 추가·임베딩 모델 교체·조문 전용 RPC로
세 번 고쳤는데, **어휘 간극 자체는 그 어느 것으로도 못 넘었다.**

**해결 — 검색 *전에* 질의를 법령 용어로 보강(`PRACTICE_TERMS` + `expandQueryForSemantic`).**
```
"리파밍 관련 법 조항이 어떤게 있지?"
  → "리파밍 관련 법 조항이 어떤게 있지? 주파수회수 주파수재배치 주파수 회수 주파수 재배치"
```
- **원 질의를 지우지 않고 뒤에 덧붙인다** — 원 표현이 맞는 경우를 잃지 않기 위해.
- **확신하는 대응만 넣는다**(5개: 리파밍/refarming, 커버리지, 주파수 경매, 알뜰폰/MVNO, 재할당).
  틀린 대응은 엉뚱한 조문을 1위로 올려 **없느니만 못하다.**
- 같은 표를 키워드 검색(`lawSynonymKeywords`)에도 먹인다.
- 기존 `LAW_SYNONYMS`는 키워드 검색 전용이었다 — **의미 검색은 원문 질의를 그대로 쓰고 있었던
  것이 구멍**이었다.

**배포 전 실측 (3건 전부 정답 상위)**
```
리파밍 관련 법 조항      → 전파법 16조(재할당) 0.570 / 6조의2(회수·재배치) 0.541
5G 커버리지 맵 공개 의무  → 전기통신역무 선택에 필요한 정보 제공 기준 5조 0.552   ← #79의 그 건
알뜰폰 도매대가 규정      → 도매제공의무 고시 4조 0.574
```
운영자 실사용 확인: 전파법 제6조의2·제7조(손실보상)·시행령 제5조(공고·의견서 30일)·
기자재 지원 고시를 **법 위계 순으로** 정확히 제시. 손실보상 제외 사유(국제기준 변경·2순위 업무)와
신규이용자 보상액 징수까지 짚었다.

**남은 흠.** 모델이 영문을 「Repurposing」으로 적었다(정확히는 Refarming). 답변 내용은 전부
맞고 표기만 틀렸다.

### 곁들여 처리한 것

- **국회 입법예고 오탐 1건 제거.** 「국가연구개발사업 등의 성과평가 및 성과관리에 관한 법률
  일부개정법률안」이 구독자 큐에 들어갔다. `matched_keywords`가 **빈 배열** — 키워드가 아니라
  Haiku 의미 판정(`assembly_notice_criteria`)이 통과시킨 것이다. 소관위가 과방위이고 본문에
  과기정통부장관 권한 변경이 있어 "과기정통부 소관 제도 변경"으로 읽힌 것으로 보인다.
  내용은 국가 R&D 평가체계라 전파·통신 접점이 없다. **발송 전이라 큐에서 해당 줄만 제거**
  (같은 큐 행에 정보통신망법 예고가 함께 있어 행 삭제가 아니라 html 편집).
  **기준문은 아직 안 고쳤다** — 표본 1건으로 기준을 바꾸는 것은 이르고, 며칠 모아
  같은 유형이 반복되는지 보고 판단한다(#82 뉴스 선별에서 성급히 판단할 뻔한 경험).
- **선별 캐시 경보 오경보 확인.** 09시대에 「판정 209건 — 정상(~70건)의 2배」 경보가 왔으나,
  캐시 적중 352건·기준문 해시 단일·관련 기사 0→31건 동반 증가로 **아침 뉴스 피크**임을 확인.
  임계값(판정 150건 초과)이 야간 기준이라 평일 아침마다 울린다. **적중률(<30%)과 판정 건수
  (>350) 두 신호로 분리**하는 안을 세웠으나, **하루치로 결정하지 않고 다음 날 재확인 후 적용**
  하기로 보류. `news_screen_cache`에 `created_at`이 없어 "신규 기사 증가"와 "제목 변경 재판정"을
  구분할 수 없다는 것도 이때 드러났다. **→ 같은 날 컬럼을 추가해 해소**(기존 1,230행은 NULL로
  남겨 "계측 이전"임을 보존 — DEFAULT를 붙인 채 추가했다면 전 행이 ALTER 시각으로 채워져
  거짓 이력이 됐을 것이다. crawler가 upsert에 이 컬럼을 담지 않아 코드 변경 없이 끝났다).
  **경보 임계 조정은 운영자 판단으로 보류** — 알림이 오는 것 자체는 감수하고, 다음 아침 피크에서
  `created_at` 데이터로 원인을 확정한 뒤 결정한다.

### 남길 교훈

- **카운터가 진실을 말한다.** `law_count = 1`이 "웹훅은 한 번만 돌았다"를 확정했고, 거기서
  재전송이라는 답이 나왔다. 증상(5번 발송)만 봤으면 코드 루프를 찾다 헤맸을 것이다.
- **"검색이 안 된다"는 신고에서 검색기를 먼저 의심하지 말 것.** 같은 엔진에 다른 어휘를 넣어
  보는 30초짜리 실측이 원인을 갈랐다.
- **차단이 진단보다 먼저다.** 5번째 발송이 진행 중일 때 코드를 고치는 대신 DB 한 줄로 끊었다.
- **한 사고를 고치면서 새로 만든 위험은 그 자리에서 기록해 둔다**(dedup → 무응답 위험).

---

## #84 (2026-08-04) 긴급도 선별 콜 통합 되돌림 — 긴급률 9.9% → 0.7%

**#82에서 월 $33을 아끼려고 긴급도 판정을 선별 콜에 합쳤는데, 하루 만에 되돌렸다.**

**발단은 운영자의 화면 지적.** 대시보드에서 「SKT 5G 과장광고 과징금, 대법원 간다」가 **보통**으로
떠 있는 것을 보고 *"예전에는 과징금이면 긴급이었는데 왜 보통인가"* 물었다. 기준문에는
「과징금·허가취소·영업정지 등 통신사에 직접 피해를 주는 기사」가 즉시대응(긴급)으로 명시돼 있다.

**같은 기사가 A/B가 되어 있었다.**

| 저장 시각 | 제목 | 등급 |
|---|---|---|
| 8/3 09:53 (개별 판정) | [단독] SKT 5G 과장광고 과징금, 대법원 간다 | **긴급** |
| 8/4 03:51 (선별 통합) | SKT 5G 과장광고 과징금, 대법원 간다 | **보통** |

**구간 전체 수치**: 배포 전 758건 중 긴급 75건(**9.9%**) → 배포 후 148건 중 **1건(0.7%)**.
14배 차이는 우연이 아니다.

### 원인 — 글자 수가 아니라 파이프라인 순서였다

운영자 질문("300자에서 600자로 돌리는데 $33이 더 든다는 것인가")이 원인을 정확히 갈랐다.
**$33은 글자 수 값이 아니다** — 별도 호출 600회/일에서 긴급도 기준문+피드백 블록(약 1,100토큰)을
매번 다시 보내는 비용이다. 글자만 300→600으로 늘리는 것은 월 $3 수준.

그래서 "통합을 유지한 채 재료만 늘린다"는 세 번째 안을 검토했으나 **불가능**했다:

```
① 수집(네이버 요약 300자) → ② 선별+긴급도 ← 여기선 300자가 전부
                          → ③ 본문 수집(중앙값 1,329자) → ④ 저장
```

`_screen_text`는 수집 단계에서 네이버 `description`을 300자로 자른 것이다(`crawler.py:474`).
**본문은 선별을 통과한 뒤에야 수집한다** — 선별에 본문을 주려면 무관 기사 500건의 본문까지
매시간 긁어야 하고, 그러면 선별 캐시(#78)로 아낀 것이 통째로 무너진다.

두 번째 원인은 **개인화 상실**이다. 개별 판정은 `get_feedback_examples(title)`로 제목과 겹치는
담당자 수정 사례 5건을 골라 넣지만, 배치 판정은 한 콜에 35건을 보므로 공통 사례만 쓴다.

### 판단 — 월 $33에 걸 수 있는 것이 아니었다

긴급 알림은 이 시스템의 **존재 이유**다. 놓친 과징금 기사 하나가 월 $33보다 비싸다.
키워드 안전망(과징금·시정명령 등이 제목에 있으면 긴급 승격)도 검토했으나, 「과징금 취소 판결」
(SKT에 유리)을 긴급으로 올리는 오탐이 뻔해 채택하지 않았다 — 그걸 피하려고 LLM 판정을 쓴다.

**'참고' 요약 온디맨드(월 $41)는 그대로 유지했다.** 품질 영향이 확인되지 않았고, 브리핑·알림이
요약을 안 쓴다는 것은 실측으로 확정됐다. 결과: 월 $128 → **약 $87**(#82 절감의 절반은 지켰다).

### 되돌린 뒤 한 일

- **선별 도구 스키마의 `urgency` 필드는 남겼다** — 프롬프트 보강으로 통합을 되살릴 실험 여지.
  다만 `save_new_items`는 그 값을 **쓰지 않는다**(무조건 `classify_urgency` 호출).
  되살릴 때는 **반드시 긴급률을 9.9%와 대조**할 것.
- **잘못 매겨진 155건 재판정**(`requade_urgency.py`) — 38건 변경, **7건이 긴급으로 승격**:
  5G 과장광고 소송 2건, 개인정보 유출 후속, 요금제 불만 2건, 물가/요금 기저효과, LGU+ 보안 인수.
  전부 SKT 직접 영향 사안인데 '참고'로 묻혀 있었다.
- **알림은 보내지 않았다**(운영자 지시: "지난 뉴스를 이제 와서 몰아 보내지 마라").
  구조적으로도 불가능하다 — 구독자 발송은 `subscriber_queue`를 읽는데, 큐 적재는 크롤러가
  **새 기사를 수집하는 순간에만** 일어난다. 저장된 기사의 등급을 바꿔도 큐가 생기지 않는다.
  실측으로도 확인: 배포 후 큐 2건은 둘 다 국회 법안이고 긴급 뉴스 큐 행은 0건이었다.

### 교훈

- **"야간 특성일 수 있다"며 판단을 미룬 것이 반나절을 잃게 했다.** 배포 첫날 밤 긴급 0%를 보고
  표본이 작다는 이유로 보류했는데, 낮 데이터에서 그대로 재현됐다. **핵심 기능의 지표가 배포 직후
  이상하면 표본이 작아도 일단 되돌리고 확인하는 편이 싸다.**
- **비용 절감의 대가는 "품질이 조금 나빠짐"이 아니라 "기능이 꺼짐"일 수 있다.**
  긴급률 0.7%는 사실상 긴급 알림이 없는 상태였다.
- **운영자의 화면 한 줄 지적이 지표보다 빨랐다.** 자동 감시는 긴급률 급락을 잡지 못했다 —
  등급 분포 이상을 경보로 만들 것인지는 별도 검토 대상.

---

## #85 (2026-08-05) 텔레그램 운영 정비 4건 — 한도 면제·대화 미유지 고지·브리핑 제외

하루 동안 운영자 사용 중 나온 요청들을 처리했다. 각각은 작지만 두 가지 규칙이 반복됐다 —
**컬럼 추가로 될 것은 컬럼으로, 스키마를 못 건드릴 때만 `app_config`로**.

### 개인별 일일 한도 면제 (`telegram_subscribers.unlimited`)

`/ask` 20회·`/law` 10회는 **과금 폭주 방지용 전원 공통 상한**인데, 특정 인원에게만 풀 수단이
없었다. 구독자 속성이므로 `app_config`가 아니라 **구독자 행에 컬럼**으로 뒀다 —
`getSub`이 `select('*')`라 코드가 자동으로 읽는다(인터페이스에 필드만 추가).
**카운터는 면제자도 계속 올린다** — 상한만 건너뛰고 사용량은 관찰 가능해야 한다.
⚠️ true면 그 사람의 비용 상한이 사라진다.

### `/ask` 대화 미유지 고지 (2곳)

봇은 질문 1건만 모델에 보낸다(`rag.ts`의 `messages: [{role:'user'}]`). 반면 **대시보드 자문은
`chatHistory`를 누적해 대화가 이어진다**(`app.js:1914`). 웹을 써 본 사람일수록
"그건 언제 시행되나?" 식 후속 질문을 던지고 엉뚱한 답을 받는다.
**답변 하단**(읽은 직후 = 후속 질문을 쓰기 직전)과 **`/start` 안내**(가입 시점) 양쪽에 넣었다.
`/law`에는 붙이지 않았다 — 애초에 한 건씩 찾는 용도라 대화를 기대하지 않는다.

### 모닝브리핑 제외 목록 (`app_config.briefing_excluded_urls`)

오탐 기사를 브리핑에서만 빼는 수단이 없었다. 발단은 「여수 죽림터널 라디오 중계기 고장」 —
도로터널 FM 방송 설비(관리 지자체, 근거 국토부 예규)라 통신 접점이 없는데 긴급으로 잡혔다.
AI 판정은 기준문상 틀리지 않았다(「기지국·장애」, 본문에 「공용 주파수」·「통신」 등장).

대안을 다 버린 이유: **삭제**는 대시보드·자문 검색에서도 사라져 과하고, **`published_at` 조작**은
사실 왜곡이며, **등급 하향**만으로는 브리핑이 24h 전체를 보므로 그대로 들어간다.
컬럼을 추가하려 했으나 **Anthropic 서비스 장애로 DDL이 403을 반복**해 `app_config`로 선회했고,
결과적으로 목록을 눈으로 보고 고칠 수 있어 더 나았다. 조회 실패는 빈 집합(fail-open) —
제외가 안 되는 것이 브리핑이 안 나가는 것보다 낫다.

### 선별 캐시 경보 — 원인 확정, 임계는 운영자 판단으로 보류

전날 추가한 `created_at`이 답을 냈다. **8/4 4회 + 8/5 10회 = 14회 연속 「제목 변경 재판정 0건」** —
판정된 기사가 전부 그 시각에 처음 들어온 신규였다. 캐시는 정상이고, 업무 시간에 시간당
100~190건의 새 기사가 실제로 들어오는 것뿐이다. 경보 기준(판정 150건 초과)이 새벽 정상치(~10건)
기준이라 **평일 낮마다 4~5회 울린다**. 제안(적중률<40% 또는 판정>350)이면 이틀간 경보 0회였으나
운영자가 보류를 택했다.

---

## #86 (2026-08-05) 국회 DIFF 대상을 KB 등재 법령으로 한정 — 17건 → 7건

**발단.** 운영자가 「대·중소기업 상생협력 촉진에 관한 법률」 입법예고 알림을 보고 물었다 —
*"이 법안은 왜 들어왔나? 과방위 것도 아니고 SKT랑 관련도 없어 보이는데."* 실제로 소관이
산업통상자원중소벤처기업위원회였다.

**조사해 보니 AI 판정 실패가 아니었다.** `assembly_notice_criteria`가 명시적으로
「플랫폼·온라인서비스 규제」를 관련으로 두고 **"개인정보·데이터·플랫폼 규제는 소관위원회 불문 관련"**
이라고 못 박아 놨다. 이 법안은 온라인 플랫폼 중개사업자 규제이므로 **지시대로 통과한 것**이다.
「애매하면 채택(과소 누락 방지)」도 명시돼 있다. 즉 **넓게 받고 운영자가 걸러내는 설계**였다.

**문제는 그 설계가 DIFF까지 끌고 간다는 것.** DIFF는 건당 Sonnet 호출(입력 2만 자)로 이 시스템에서
가장 비싼 단계인데, 실측 17건 중 11건이 대부업·스토킹방지·헬스케어·이러닝·성과평가처럼
통신과 무관한 법안이었다. 알림은 넓게 받아도 되지만 **비싼 분석까지 넓게 할 이유는 없다.**

**해결 — 판단이 아니라 대조.** 운영자 제안: *"지금 올라온 법안들이 바뀔 때만 하면 되지 않나"*
→ **"이 법안이 우리 KB에 등재된 법을 고치는가"** 로 거른다. AI 판정보다 정확하고 비용이 0이며,
운영자가 KB에 넣고 빼는 것으로 대상을 직접 통제한다.

**정규화가 없으면 실패한다.** 첫 시험에서 6건 중 **전자상거래법·방송미디어통신위원회 설치법이
잘못 제외**됐다. 원인 둘 — ①KB 법령 목록을 `limit` 때문에 29종만 읽었다(전량 페이지네이션 필요)
②「대·중소기업」의 가운뎃점이 DB는 `ㆍ`, 국회는 `·`이고 띄어쓰기도 흔들린다.
`[ㆍ·・.\s]` 제거 후 비교로 해결. **시행령·시행규칙만 등재된 경우도 모법 개정안을 받도록**
접미사를 떼어 키에 함께 넣는다.

**KB 조회 실패 시 필터를 걸지 않는다(fail-open)** — 대조를 못 한다고 분석을 멈추면 놓치는 쪽이
더 비싸다. **제외분은 반드시 로그에 이름을 남긴다** — 필요한 법이 빠졌으면 KB에 등재해 되살릴 수
있어야 한다.

**"KB에 없으면 안 본다"를 규칙으로 확정.** 예외 목록을 만들지 않은 이유: KB와 DIFF 대상이
어긋나기 시작한다. 정말 필요하면 KB에 넣으면 되고, 그러면 `/law`·자문 검색에서도 함께 잡힌다.

**즉시 검증된 사례.** 제외 목록에 있던 「전기통신금융사기 피해 방지 및 피해금 환급에 관한 특별법」은
**전기통신사업자가 직접 수범자**(전화번호 이용중지·사기정보제공기관 의무)라 빠지면 안 되는 법이었다.
KB에 등재(법률 50청크 + 시행령 87청크, OKF 2건, 임베딩 NULL 0)하자 **다음 실행에서 자동으로
대상에 편입**됐다 — 키 320→322개, 대상 6→7건, 제외 11→10건. 설계가 의도대로 도는 것을 확인.

**효과**: 분석 대상 17 → 7건(−59%), 월 약 $7 → $2.5. 금액은 작지만 정기국회로 발의가 수십 건이
되면 차이가 커진다. **알림은 그대로 넓게 받는다** — 좁힌 것은 비싼 분석뿐이다.

**남긴 것**: 시행규칙은 이 법에 존재하지 않아(법제처 `totalCnt=0`) 2건만 등재. 하위 고시 4건은
금융위·금감원·경찰청 소관이라 제외했고 근거를 OKF 체크리스트에 남겼다.

---

## #87 (2026-08-05) /law 조문 검색 — 배제에서 가중치로

**발단은 운영자의 원칙 제시.** *"부칙·서식·별표·별지는 본문에서 필요한 경우에만 불러오면 되지 않나?"*
맞는 원칙이었고, 이어진 질문들이 내 판단을 **세 번 뒤집었다.**

### 뒤집힌 판단 셋

| 내가 처음 말한 것 | 실측 |
|---|---|
| "별표가 조문 이미지 표의 유일한 텍스트본" | ❌ 이미지가 사실상 전부인 조문 21개 중 **별표 인용 0개** |
| "별표를 분석해 조문과 매칭하는 작업이 필요" | ❌ **불필요** — 별표 5,538개 중 66%가 「(제N조 관련)」을 이미 보유 |
| "문서당 상한(PERDOC)을 조정해 균형을 잡자" | ❌ 자문 검색 실측에서 **후보가 15자리 중 1~3개** — 상한이 걸리지도 않는다 |

특히 세 번째는 내가 "개인정보보호법 3 + 시행령 3 + 보도자료 3 + 회의록 3…" 식으로 **고루 배분되는 것처럼
예시를 들었는데, 그런 배분 규칙은 존재하지 않는다.** 점수 순으로 담다가 문서당 3개를 넘으면 건너뛸 뿐이다.

### 결정적 실측 — 하드 필터가 애초에 불필요했다

필터를 걷고 원본 유사도를 재보니 **조문이 이미 위에 있었다.**

| 질의 | 조문 최고 | 별표·붙임 최고 | 차이 |
|---|---|---|---|
| 주파수 회수 또는 재배치 절차 | **0.570** | 0.531 | +0.039 |
| 과징금 산정 기준 | **0.591** | 0.558 | +0.033 |

내가 그동안 근거로 삼던 **"정답 조문 0.418 vs 무관 별표 0.50~0.54"는 「5G 커버리지 맵」 특정 사례**였는데
일반 경향인 것처럼 인용해 왔다. 표본 하나로 구조를 단정한 것이다.

### 그래서 배제를 걷고 가중치로 바꿨다

```
종전: article_no !~ '^(부칙|서식|별표|별지)'   ← 완전 배제
      · 「붙임」이 목록에서 빠져 1,191개가 통과 → 「주파수 분배표」가 리파밍 검색 2~6위 독식
      · 배제된 것은 영영 도달 불가 → 「전파법 시행일은?」의 답(부칙)을 못 찾았다

현행: 정렬 가중치 (거리 기준이므로 가점은 빼고 감점은 더한다)
      조문(^N조)          −0.08 (거리)  = 우대
      별표·붙임              0
      부칙·서식·별지        +0.05        ← 운영자: "law는 부칙이나 서식이 우선순위는 아니야"
      파일 문서(pdf/md/…)   +0.10        ← 보도자료·회의록은 /law의 답이 아니다
```

**운영자가 A(감점)와 B(배제) 중 A를 명시적으로 택했다.** 이 선택이 바로 증명됐다 —
배포 직후 `/law 전파법 시행일은 언제인가` 실사용에서 **부칙 제20067호 제1조를 1위로 찾아
「공포 후 6개월」 → 2024.1.23 + 6개월 = 2024.7.23 을 정확히 답했다.** 감점(+0.05)이 있어도
유사도가 0.591 대 0.448로 압도적이라 위로 올라온 것이다. **"우선순위는 아니되 필요하면 나온다"가
설계대로 동작한 실측 증거.**

### 구현에서 지킨 것

- **`similarity` 반환값에는 가중치를 섞지 않는다.** 호출부가 이 값을 표시·비교에 쓰므로
  "왜 0.531이 0.481로 보이지" 같은 혼선을 막는다. 정렬에만 반영.
- **`ORDER BY ... + 0.0` 유지.** HNSW를 무력화해 전수 정밀 스캔을 강제하는 장치다(#79).
  없으면 `ef_search` 기본값 탓에 상위 40건만 훑어 **가중치 자체가 무의미해진다.**
- `match_threshold`는 가중치 적용 **전** 원본 유사도로 판정(호출부는 0.0).

### 이 한 변경이 정리한 것

- 붙임 독식 → 가점에 밀려 하위로. **배제 아님**
- 조문이 안 가리키는 별표 65개 → 검색에 남으므로 **애초에 사라질 일이 없다**
- 문서당 상한 → **불필요**

### 남은 것 (별건)

- **조문 이미지 21개 OCR** — 단말장치 기술기준 제5·16·17·18·27조, 경고문구 제2조,
  이동전화망번호 제4조 등. 수치가 이미지에만 있고 **별표로 커버되지 않는다(0개 확인)**.
  이미지 취득은 확인됨(`www.law.go.kr/LSW/flDownload.do?flSeq=<id>` → 200 GIF).
  **id는 연속 번호가 아니므로** 각 조문 `content`의 `<img id="…">`에서 실제 값을 읽어야 한다.
  받아본 제17조 표에 「별표 10의 그림 1」 인용이 있어 **OCR하면 별표 연결도 함께 복원**된다.
  ⚠️ 수치 오독이 최대 위험(`120 Ω→12O Ω`, `㎃→mA`) — 하이퍼네트워크 자료 OCR 오독으로
  등재를 포기한 전례가 있다. 21개는 전수 검증 가능한 양이니 원본 대조 필수.
- **자문 검색 후보 부족** — `match_chunks_semantic`의 `match_threshold: 0.45`가 병목으로 의심된다.
  실측: 「개인정보 유출+규제 동향」 후보 1개, 「과방위 단말기 유통」 3개(15자리 중).
- **대시보드에 조문 갈래 없음** — `app.js`에 `match_law_articles_semantic` 호출 0건.
  봇은 3갈래인데 대시보드는 키워드 1갈래라 같은 질문에 다른 답이 나온다.

**#87 후속 — 배제를 풀자 「자신 있게 틀린 답」이 나왔다 (같은 날).**

가중치 배포 직후 `/law 전파법 시행일은 언제인가` 실사용에서 **부칙 제20067호(2024.1.23 공포)를
집어 "2024.7.23 시행"이라 답했다.** 현행 시행일은 **2026.1.2**다. 운영자가 국가법령정보센터
화면(`[시행 2026. 1. 2.] [법률 제21065호]`)으로 지적해 발견됐다.

**부칙을 배제하던 때는 이 질문에 "못 찾음"이라 답했다.** 열어 주자 답은 하는데 틀렸다 —
이 사례만 놓고 보면 **전보다 나빠진 것**이다. 검색 범위를 넓히면 프롬프트도 함께 좁혀 줘야 한다.

**원인은 두 겹이었다.**
- 전파법 문서 하나에 **부칙 청크가 19개**(역대 개정 이력). 그중 하나의 시행일을 법 전체의 것으로 착각.
- 더 근본적으로, **`/law` 컨텍스트에 시행일 항목이 아예 없었다.** 자문 경로(`buildRagContext`)는
  「시행일: …」을 별도 메타로 뽑고 있었는데 `answerLawQuery`만 자체 포맷을 써서 빠져 있었다.
  모델이 본 것은 `전파법(법률)(제21065호)(20260102) 부칙 제20067호(20240123)` 한 줄 —
  **괄호 숫자 넷이 나란히 있어 어느 것이 시행일인지 구분할 근거가 없었다.**

**조치 두 가지.**
```
① 컨텍스트 분리 표기 (근본)
   전: [조문 N] 전파법(법률)(제21065호)(20260102) 부칙 제20067호(20240123)
   후: [조문 N] 전파법 [법률 | 제21065호 | 시행일 2026-01-02]
       조항: 부칙 제20067호(20240123)
   → doc_name을 파싱해 법령명·법종·호수·시행일로 분해. 372개 문서 전수 검증(법령 전부 성공,
     실패분은 보도자료·세미나 자료라 원문 표기가 맞다).
② 프롬프트 규칙 — 「시행일」 질문은 메타의 시행일로 답하고, 부칙은 **개정 하나하나의 이력**이며
   부칙 시행일을 법의 시행일로 제시하지 말 것. 특정 개정을 물은 경우에만 부칙 근거 + 어느 개정인지 명시.
```

**결과(실사용 재확인).** 「전파법 시행일: 2026-01-02」로 정확히 답하면서, 부칙을 버리지 않고
제 위치에 놓았다 — *"법률 제21065호에 포함된 개정 중 일부는… 부칙 제20067호는 해당 **개정분**이
2024.7.23부터… **현재 전파법 전체의 현행 시행일은 2026년 1월 2일**"*.

**이 답변이 부칙 삭제를 하지 않은 판단을 증명한다.** 운영자가 *"부칙은 주로 개정 히스토리인데
아예 DB에서 빼는 건 어떤가"* 물었을 때 실측으로 답한 내용:
- 부칙 1,704개 중 **경과조치 184·적용례 125·특례 38·유효기간 63** — 절반이 실무 직결이다.
  「종전 규정에 따라 허가받은 무선국은 이 법에 따라 허가받은 것으로 본다」 같은 답은 **부칙에만** 있다.
- 용량은 근거가 못 된다: 부칙 전체 삭제 **−31MB**(DB 704MB의 4%), 짧은 부칙만이면 **−3.6MB(0.5%)**.
  Supabase Pro 8GB 중 9%만 쓰고 있고 지침대로 **병목은 RAM**이지 디스크가 아니다.
- 길이로 자르면 **「짧지만 실무 내용 있는」 33개가 함께 사라진다.**
- 검색에서 안 보이게 하는 것이 목적이면 **가중치가 삭제와 같은 효과를 내면서 아무것도 잃지 않는다.**

**교훈.** ①**배제한 것은 영영 도달할 수 없다** — 「시행일」의 답은 부칙에 있었다.
②**검색을 열면 프롬프트도 고쳐야 한다** — 안 그러면 "못 찾음"이 "틀린 답"으로 바뀐다.
③**같은 일을 하는 코드가 두 벌이면 한쪽만 개선된다** — 자문에는 시행일 표기가 있었는데
`/law`에는 없었고 아무도 몰랐다. (대시보드에 조문 갈래가 없는 것과 같은 성격의 문제)

---

**#89 자문에 조문 「의미」 검색이 없었다 — 키워드는 어휘 간극을 못 넘는다 (2026-08-05).**

#88 후속으로 「자문 후보 부족(match_threshold 0.45 병목)」을 조사하러 갔다가 **전제가 틀렸음을
확인하고 다른 병목을 찾았다.** 조사 자체가 성과였던 건이라 측정값을 그대로 남긴다.

**① 임계값은 병목이 아니었다.** `match_chunks_semantic`을 0.45/0.35/0.25/0.0으로 재보니
8자리 중 7~8을 이미 채운다. 최종 근거도 **5개 질의 전부 15/15로 꽉 찬다.**
계획서에 적혀 있던 「15자리 중 1~3개만 채움」은 재현되지 않았다. 임계를 낮춰 새로 들어오는 것은
해외규제동향·논문 조각이라 **낮출 이유가 없다 — 0.45 유지.**

| 질의 | 0.45 | 0.35 | 0.25 | 0.0 |
|---|---|---|---|---|
| 개인정보 유출 + 규제 동향 | 7 | 8 | 8 | 8 |
| 5G 커버리지 맵 | 5 | 8 | 8 | 8 |
| 기지국 개설 허가 | 3 | 8 | 8 | 8 |

**② 대신 「15자리가 꽉 찬 것」이 나쁜 소식이었다.** RRF 정렬까지 재현해 무엇이 뽑히는지 보니
무관한 별표가 자리를 먹고 있었다 — 「주파수 재할당 대가」에 **전자파적합성 기준 별표 5(가정용
전기기기)**, 「기지국 개설 허가」에 **지방세법 시행령 별표 1(등록면허세)이 3자리**(문서당 상한을
꽉 채움), 「개인정보 유출」은 1·2·3위가 같은 고시의 별표 7 계열이고 6·8위가 부칙.
원인은 `rag.ts:174`·`app.js:486`의 **평평한 가점** — `article_no`만 있으면 종류 불문 `+0.5/(K+1)`인데,
실DB에서 `article_no` 보유 18,349개 중 **조문은 41%(7,587)뿐**이고 나머지 59%(별표 5,538·부칙 1,704·
별지 1,421·붙임 1,191·서식 908)가 조문과 동급 가점을 받고 있었다. #88에서 `/law`만 등급을 나눴고
자문은 그대로였다.

**③ 그런데 가중치만으로는 안 고쳐졌다.** 등급화(조문 +1단위 / 별표·붙임 0 / 부칙·서식·별지 −1단위)를
가정해 A/B를 돌리니 75자리 중 9자리가 교체되고 악화 사례는 없었지만, **「기지국 개설 허가」는 한 칸도
안 움직였다** — 그 질의의 **조문 후보가 1개뿐**이라 별표를 밀어낼 조문이 아예 없었다.
**가중치는 후보 안에서 순서만 바꾼다. 후보에 없으면 무력하다.**

**④ 진짜 원인 — 자문에는 조문 의미검색 갈래가 없었다.** 경로별로 비교하니:

| 경로 | 키워드 조문검색 | 조문 **의미**검색 |
|---|---|---|
| 봇 `/law` | ✅ `searchLawArticles` | ✅ `match_law_articles_semantic` |
| 봇 자문 | ✅ | **❌** |
| 대시보드 자문 | ✅ | **❌** |

계획서의 「대시보드에만 `match_law_articles_semantic` 호출이 0건」도 부정확했다 — 대시보드에도
키워드 조문검색은 있었고(`app.js:512`), **양쪽 자문 모두 의미 갈래가 없던 것**이 사실이다.

키워드 갈래가 실제로 무엇을 주는지 그대로 옮겨 재보니(하한 — Haiku 확장 제외):

```
「기지국 개설 허가 절차」
  키워드 5개: 전파관리 세칙 27조(민원) · 해상무선통신망 12조(기지국 관리) · 별지 8 · 별표 3 · 전파법 20조의2
  의미 갈래:  전파법 21조(무선국 개설허가 등의 절차) ★ · 전파법 시행령 31조(허가의 신청) ★
  → 「기지국」이라는 낱말에 끌려 해상무선통신망으로 샌다.

「주파수 재할당 대가 산정 기준」
  키워드 5개: 전파법 10·11·12·13·15조 — 전부 「주파수할당」이지 「대가 산정」이 아니다.
              (정렬 동점 처리가 문서명·조문번호 순이라 연번이 줄줄이 자리를 채운다)
  의미 갈래:  세부사항 9조(실제매출액 기준 할당대가의 산정) ★ · 시행령 14조(산정기준 및 부과절차) ★ · 전파법 16조(재할당) ★
```

**조치.** `answerAdvisory`(rag.ts)와 대시보드 자문(app.js)에 조문 의미검색을 **키워드 갈래와 나란히**
추가하고, 기존 「조문 정밀검색 결과」 섹션에 이어 붙였다(**키워드 5 + 의미 5, 상한 10**).
필터는 `/law`의 `semExtra`와 같게 — **조문만**(`^\d+조`), 파일 문서 제외, RAG·키워드분과 중복 제거.
**RAG 15자리는 손대지 않았다** — 보도자료·회의록 근거가 밀려나지 않게 하려는 것이고, 이 약속대로
조문은 별도 섹션에서만 늘어난다.

덤으로 **#83의 실무 용어 보강(`PRACTICE_TERMS`/`expandQueryForSemantic`)이 `app.js`에 통째로 빠져
있던 것**을 발견해 함께 이식했다. 대시보드에서는 「리파밍」이 아직 법령 용어로 안 바뀌고 있었다.

**검증(로컬 대시보드 콘솔, 실DB).** `expandQueryForSemantic('리파밍 관련 규정')` →
「…주파수회수 주파수재배치…」 보강 확인. anon 키로 `match_law_articles_semantic` 호출 성공
(전파법 21조 0.403 1위). 병합 결과 조문 섹션이 5개 → **10개**가 되고 전파법 19조·**21조**·
시행령 31조가 함께 들어왔다. `content`는 RPC가 이미 800자로 잘라 오므로 별도 절단이 필요 없다.

**비용.** 자문 1회당 임베딩 1회 + 조문 5개(각 800자) ≈ 2,000토큰 추가 = **약 8원**.

**교훈.** ①**전제는 재보고 쓴다** — 계획서에 적힌 「후보 1~3개」는 재현되지 않았고, 그대로 믿었으면
임계값을 낮춰 잡음만 늘렸을 것이다. ②**가중치와 후보 생성은 다른 문제다** — 순위 조정은 후보에
정답이 있을 때만 듣는다. ③**같은 일을 하는 코드가 세 벌이면 두 벌이 낡는다** — `/law`·봇 자문·
대시보드 자문이 각자 달랐고, #83도 한쪽에만 들어가 있었다. #88 후속에서 얻은 교훈이 그대로 반복됐다.

**#89 실사용 검증 — 근거는 맞는데 출처에 안 보였다.** 배포 후 운영자가 `/ask 기지국 개설 허가 절차`를
실행했다. 답변은 **전파법 제21조제2항을 「[원문 확인됨]」으로 인용**했다 — 새 갈래가 실제로 붙었다는
증거다(종전 키워드 갈래에는 21조가 없었다). 함께 시행령 제24조제2항 자기적합확인 신설(2026.10.22 시행)과
입법예고(~8.31) 동향까지 답해, 제도와 최신 상황을 같이 내는 자문 본래 목적도 지켰다.

**그런데 출처 목록에 전파법이 없었다.** 표시된 6건은 지방세법 시행령·KCA 박사논문·세미나 자료·
주파수 분배표·국정 브리핑 — **잡음만 보이고 정작 인용한 조문이 안 보였다.** 원인은 절단 순서다:

```
telegram-webhook/index.ts:323   sources.slice(0, 6)          ← 앞 6개만 표시
rag.ts (종전)                    chunks(RAG 15) 먼저 → extra(조문) 나중
app.js (종전)                    sourceTagsHtml(_advSrc.laws, 6), 같은 순서
```

RAG 15개가 앞자리를 다 채워 조문이 잘려 나갔다. **근거 누락이 아니라 표시 문제**였지만, 운영자가
「이 조문 어디서 나왔지」를 확인할 수 없으니 실질적으로 근거가 없는 것과 같다. 조문 갈래를 추가해
근거를 좋게 만들어 놓고 **그 성과가 화면에서 안 보이는** 상태였다.

**조치.** 두 경로 모두 `sources` 조립에서 **조문 정밀검색분(extra)을 먼저** 놓았다. 잘린 목록에서는
가장 직접적인 근거가 앞에 와야 한다.

**교훈.** **출력 절단은 검색 개선을 무효화할 수 있다.** 컨텍스트에 잘 넣는 것과 사용자가 확인할 수
있는 것은 다른 문제다 — 상위 N만 보여주는 자리가 있으면 그 N의 **순서**까지 함께 설계해야 한다.

---

**#90 봇에 별표 경로가 아예 없었다 + `article_no` 가점 등급화 (2026-08-05).**

#89에 이어 「별표 역참조 인덱스」를 만들려다 **측정으로 계획을 접고 더 큰 것을 찾았다.**

**① 역참조는 만들 값어치가 없었다.** 계획서는 「별표 5,538개 중 66%가 「(제N조 관련)」 보유,
조문이 안 가리키는 별표 65개」였는데 실측은 달랐다:

```
고유 별표 479개 (5,538은 청크 수 — 같은 별표가 여러 청크로 쪼개진 것)
├ 제목에 「(…제N조 … 관련)」 있음  351
│  ├ 그 조문이 이미 별표를 인용함   315   ← 정참조(buildAnnexContext)로 이미 닿는다
│  └ 조문이 인용 안 함              23   ← 역참조만이 닿는 것
└ 참조 없음                        128
```

**23개 중 16개는 해당 조문 본문에 `<img>`가 있다** — 조문이 별표를 안 가리키는 게 아니라
**가리키는 문장이 이미지 안에 있어 텍스트로 안 남은 것**이다(단말장치 기술기준 9건,
항공업무용 무선설비 기술기준 5건 등). 역참조는 OCR 문제의 증상 치료였다. 순수 이득은 **7개**.

파싱에도 함정이 있었다. 첫 「제N조」를 소속으로 보면 **다른 법의 조문에 속는다** —
`별표 6(선박안전법 제29조제2항 및 어선법 제5조에 따라…(제9조제1항 관련))`의 소속은 제9조인데
제29조로 잡힌다(26건 중 3건 오탐). 제목 **끝 괄호**만 봐야 한다.

**② 대신 훨씬 큰 격차를 찾았다 — 봇에 `buildAnnexContext`가 0건이었다.**
법령 조문은 실제 숫자를 안 담고 별표로 넘긴다(전파법 시행령 제14조 = "별표 3에 따라 산정한다",
산식은 별표 3에). 대시보드는 그 별표를 끌어오는데(**315개**가 이 경로) **봇에는 없었고**,
오히려 검색에서 별표를 걸러내고 있었다(`rag.ts:539`). 텔레그램에서 금액·요율·기준을 물으면
「별표 3에 따라 산정합니다」로 끝났다. **역참조 23개 대 봇 이식 315개 — 13배.**

**조치.** `app.js:903 buildAnnexContext`를 `rag.ts`로 이식(`answerAdvisory`에만).
로직은 그대로 옮겼다 — 타 법령 인용 건너뛰기(978건 중 90건), 첫 청크(표 머리) 무조건 포함,
`ANNEX_MAX_UNITS=2`/`ANNEX_MAX_CHUNKS=6`, 잘리면 「일부만 실었습니다」 고지, 표 머리 보충.
**`/law`에는 넣지 않았다**(조문 원문 즉답·20초 성격).

옮기면서 **양쪽 모두 입력을 바꿨다**: 종전 `ragChunks`만 → **RAG + 조문 정밀검색분**.
조문 섹션(#89)에만 있는 조문의 별표 인용을 놓치고 있었다. 실측 개선:

| 질의 | 종전 | 지금 |
|---|---|---|
| 전파사용료 산정 | **(없음)** | **전파법 시행령 별표 8·9**(산정 정본) |
| 기지국 개설 허가 절차 | **(없음)** | 해상무선통신망 별표 3 외 |
| 무선국 검사 수수료 / 적합성평가 수수료 | 별표 13 / 14의3 | 동일 |

**텔레그램 형식 지침 한 줄을 함께 넣었다.** 별표는 괘선 문자(`┌─┬─┐`)로 그린 표이고
(실측 괘선 비율 39.4%/44.2%/10.1%) 텔레그램은 고정폭 폰트가 아니라 그대로 옮기면 정렬이
무너진다. 기존 「마크다운 표·코드블록 금지」로는 안 걸린다 — **같은 코드를 옮기면 나타나는
새 문제**라 이식 시점에 함께 막았다. 출처 목록에서도 별표는 조문 다음·RAG 앞이다(#89 교훈).

**③ `article_no` 가점 등급화 적용.** #89에서 미결로 남긴 것을 조문 갈래가 들어온 상태에서
재측정했다. 종전에는 `article_no`가 있으면 종류 불문 `+0.5/(K+1)`였는데, 실DB에서 보유
18,349개 중 **조문은 41%(7,587)뿐**이고 별표 5,538·부칙 1,704·별지 1,421·붙임 1,191·서식 908이
동급 가점을 받고 있었다. 등급화(조문 유지 / 별표·붙임 0 / 부칙·서식·별지 −1단위) 실측:

| 질의 | 전 | 후 |
|---|---|---|
| 주파수 재할당 대가 | **별표 7**·조문 3 | **조문 6**·별표 4 |
| 5G 커버리지 맵 | 별표 4·서식 2 | 별표 2·서식 1 |
| 개인정보 유출 | 부칙 2·조문 3 | 부칙 1·조문 4 |

**75자리 중 8자리 교체, 악화 0건.** 그리고 새로 올라온 조문 8건 중 **조문 섹션(#89)과 중복은
0건** — 두 경로가 대체가 아니라 보완임이 확인됐다. 다만 「5G 커버리지 맵」은 빠진 자리를
조문이 아니라 보도자료가 채웠고, 「기지국 개설 허가」는 0자리 변화다(조문 섹션이 따로 주므로 무방).
별표·붙임은 **배제가 아니라 가점만 뗐다**(#88 원칙) — 정본인 별표는 시맨틱·키워드로 여전히 올라온다.

**교훈.** ①**계획서 수치의 단위를 확인한다** — 「별표 5,538개」는 청크 수였고 실제 별표는 479개였다.
②**만들기 전에 값어치를 잰다** — 역참조는 23개(순수 7개)였고, 같은 시간에 315개짜리 격차가
바로 옆에 있었다. ③**코드를 옮길 때는 옮기는 쪽의 제약을 함께 본다** — 대시보드에서 멀쩡하던
괘선 표가 텔레그램에서는 깨진다.

---

**#91 조문 이미지 OCR — 「이미지가 본문인 조문」 1군 7건 복원 (2026-08-05).**

기술기준 수치가 **이미지에만 있고 별표로도 커버되지 않는** 조문들을 텍스트로 되살렸다.
무선종사자 자격 제12조는 DB에 **「제12조(교육과목 및 시간)」 42자가 전부**였다 —
교육과목·시간이 이 시스템 어디에도 없었다.

**대상 실측이 계획서와 달랐다.** 계획서는 「21개 조문 / 문서 7건」이었으나 실제로는
**52개 조문 / 15개 문서 / 이미지 81개**(본문이 400자 미만이면서 `<img>`가 있는 조문 기준).
2.5배라 전수 대조가 형식적으로 흐를 위험이 있어 **1군만** 했다:

| 군 | 대상 | 조문 | 이미지 | 판단 |
|---|---|---|---|---|
| **1군** | 단말장치 기술기준·경고문구·이동전화망번호·무선종사자 자격 | 7 | 8 | **처리함** — 본문이 42~137자로 사실상 조 제목뿐 |
| 2군 | 신고면제 무선국용 무선기기 고시 | 9 | 26 | 미처리 — 특정소출력·RFID·UWB 스펙표 |
| 3군 | 항공·해상·간이무선국·전기통신번호세칙·지방세법 등 | 34 | 43 | 미처리 — 본문이 150~380자로 이미 충분, 이미지는 보조 |

단말장치 제24·26조도 제외했다(이미지 20개) — 본문이 758~800자로 충분하고 이미지가
「아이 패턴」·「스펙트럼 폭」 **파형 그래프**라 텍스트화 이득이 작다.

**취득 경로.** 법제처 `<img id="…">`에는 URL이 없다. `https://www.law.go.kr/LSW/flDownload.do?flSeq=<id>`로
받으며 **id는 연속 번호가 아니라 본문에서 읽어야 한다**. 받은 파일은 **확장자가 gif여도 실제
형식은 BMP인 경우가 있어**(Pillow가 `format=BMP`로 인식) PNG 변환 후에야 읽힌다.

**⚠️ 축소본으로 읽으면 틀린다 — 실제로 2건 틀렸다.**
제5조 주석을 처음 읽었을 때 「**특수**유닛」·「**외무**노출」로 옮겼는데, 3배 확대하니
「**복수**유닛」·「**외부**노출」이었다. 수식 `(10N+0.13L) mA(첨둣값)`는 확대에서도 동일했다.
**모든 이미지를 3배 확대해 다시 읽는 것을 절차로 고정한다.** 배경역사에 하이퍼네트워크 자료
OCR 오독으로 등재를 포기한 전례가 있는데, 그 위험이 실측으로 재확인된 셈이다.

**법제처 원문 오타는 고치지 않는다.** 제16조 표의 `AMI(Alternate mArk Inversion)`은
표준 용어가 `Mark`지만 원문이 그렇다. 우리가 고치면 원문 대조가 불가능해진다.

**임베딩을 반드시 함께 NULL로 만들 것.** `backfill_embeddings.py`는 `"embedding": "is.null"`만
채운다(62행). 본문만 고치면 임베딩이 옛 텍스트로 남아 **「고쳤는데 검색은 그대로」**가 된다.
`tools_ocr_apply.py`는 `update({'content': …, 'embedding': None})`로 한 번에 처리한다.
실행 후 백필이 정확히 7개만 잡은 것으로 다른 청크 무영향을 확인했다.

**원본 보존.** `<img>` 태그는 지우지 않고 마크다운 뒤에 주석으로 남긴다 —
`<!-- 원본 이미지: <img id="…"></img> (법제처 flDownload.do?flSeq=…) -->`. 되돌릴 수 있다.

**검증(실DB 시맨틱 검색, 4개 질의 전부 1위).**

| 질의 | 결과 |
|---|---|
| 무선종사자 교육과목과 교육시간 | 제12조 **1위**(0.537) |
| 이동통신단말장치 경고문구 표기 내용 | 제2조 **1위**(0.707) |
| 2048kbps 회선 단말장치 임피던스와 반사감쇠량 | 제17조 **1위**(0.571) |
| 이동전화망번호 국가번호 사업자망번호 자리수 | 제4조 **1위**(0.753) |

복원된 내용의 예 — 경고문구 제2조는 문구 자체가 없었다:
> 「이동 중 이동통신단말장치의 사용은 사고의 위험성이 있음」

제17조는 계획서의 검증 기준(2,048 kbps±50 ppm / HDB3 / 120 Ω·75 Ω / 12·18·14 dB)과
정확히 일치했고, **「별표 10의 그림 1」 인용**도 함께 복원됐다 — 예고했던 부수 효과(이미지
속 별표 연결 복원)가 확인된 것이다.

**교훈.** ①**대상 목록은 세어 보고 시작한다** — 21개인 줄 알았던 것이 52개였다.
②**전수 대조는 개수를 줄여서라도 지킨다** — 81개를 형식적으로 훑는 것은 안 하느니만 못하다.
「검증했다」는 기록만 남고 오독은 그대로 들어간다. ③**축소본 판독은 신뢰하지 않는다.**

**#91 후속 — 「파형 그래프일 것」이라던 24·26조가 전부 수치표였다.**

1군 처리 시 단말장치 제24·26조를 **조문 제목만 보고**(「아이 패턴」·「스펙트럼 폭」) 파형 그래프로
단정해 제외했다. 운영자가 *"남긴 결정은 모두 안 하는 게 좋다는 거지?"*라고 되물어 실제로
열어 보니 **20개 전부 수치표**였다. 「아이 패턴」은 표 안의 한 행일 뿐이고 그것만 별표 그림으로 넘긴다.

- **제24조(광동축혼합설비, HFC/DOCSIS 상향)** — 동작 주파수 5.75~65 ㎒, 신호출력 +23~+61 dBmV,
  변조방식 TDMA QPSK·16QAM·64QAM / SCDMA 64QAM·128QAM, OFDMA 최대 4096QAM,
  심볼속도별 인접채널 기준값(−38~−53 dBc), 주파수 대역별 버스트 기준
- **제26조(수동형 광선로설비, GPON/XG-PON)** — 1,480~1,500 nm 하향·1,260~1,360 nm 상향,
  2.488/1.244 Gbps, **광분배망 A·B·B+·C·C+별 수신감도 −21~−30 dBm**, 과부하, 소광비

**추정으로 채우지 않은 것이 두 곳 있다.** 159366933·159366939의 주5
`N_UGHU = [0.2 + 10^((−44 − F_?)/10)]`에서 F의 아래첨자가 **5배 확대에도 판독되지 않았다.**
주3에 `F_SF`가 정의돼 있어 SF일 가능성이 높지만 **추정이다.** 그 자리에
`F_[원문 이미지 확인 필요]`로 명시해 두었다 — **추정으로 채우면 그것이 곧 조용히 틀린 답**이다.
「모르는 것을 모른다고 표시한다」는 이 시스템의 원칙을 데이터 층에도 적용한 것이다.

**검증(실DB 시맨틱).** 「GPON 광분배망 수신감도와 과부하 기준」 → 제26조 **1위**(0.549),
「광동축혼합설비 상향 신호출력 범위와 변조방식」 → 제24조 **1위**(0.484).

**부수 확인 — 청크 경계에서 잘린 `<img` 조각이 원래부터 있다.** 34397 끝에 `<img id="159`가
잘린 채 남아 있는데 이는 적재 시 청크 분할이 태그 중간에서 일어난 결과이며 OCR 작업과 무관하다.
`<img` 문자열 수와 완전 태그 수가 어긋나는 청크가 있어도 사고가 아니다.

**2군(신고면제 무선기기 고시 9개 조문 / 이미지 26개)은 하지 않았다.** 24·26조까지 20개를
추가로 대조한 뒤라, 여기서 26개를 더 하면 **전수 대조가 형식적으로 흐를 위험**이 있다고 판단했다.
「전수 대조는 개수를 줄여서라도 지킨다」는 #91의 교훈을 스스로에게도 적용한 것이다.

**교훈.** **제목만 보고 내용을 단정하지 않는다.** 「아이 패턴」이라는 낱말 하나로 20개 표를
버릴 뻔했다. 운영자의 되물음이 없었으면 그대로 넘어갔을 것이다 — 이번 세션에서 계획서 전제가
틀렸던 세 번(자문 후보 수·조문 갈래 위치·별표 개수 단위)과 같은 종류의 실수다.

---

**#92 `/law` 번호 조회가 처음부터 깨져 있었다 + 뉴스 클러스터링이 관점 차이를 못 넘었다 (2026-08-06).**

운영자가 두 가지를 실사용에서 잡아냈다. 둘 다 **「된다고 적어 놓고 확인하지 않은 것」**이다.

### ① `/law 법령명 N조` — 한 번도 동작한 적이 없다

`/law 무선종사자 자격 12조` → 「DB에 등재되지 않았습니다」. 그런데 이 조문은 바로 전날
OCR로 복원해 시맨틱 검색 1위(0.537)를 확인한 것이었다. 원인은 **표기 형식 불일치**:

```
DB의 article_no:   12조(교육과목 및 시간)      ← 실측: 「제N조」 형식 0건 / 「N조」 형식 7,587건
handleArticleLookup: .ilike('article_no', `제${artNo}조%`)   ← 절대 안 맞는다
```

전기통신사업열 제19조로 확인해도 **0건 매치**였다. **번호 직접 조회 기능 전체가 죽어 있었다.**
들키지 않은 이유는 `/law 전파법 시행일은 언제인가` 같은 **자연어 질의가 AI 검색 경로**라 멀쩡했기
때문이다 — 전날 시행일 오답을 고친 것도 그쪽 경로였다. 그리고 **운영자용 안내문
(`docs/텔레그램봇_사용안내.md`)에는 「조문 원문이 바로 나옵니다」라고 적혀 있었다.**

조치: `wantedDb`(DB 형식 `12조`)와 `wanted`(표시용 `제12조`)를 분리하고, 조회는
`.or('article_no.ilike.12조%,article_no.ilike.제12조%')`로 **두 형식 모두** 받는다.
비교 전에 앞의 `제`를 벗겨 같은 자리에서 다룬다(향후 적재 형식이 바뀌어도 견디게).

**교훈: 문서에 「된다」고 쓰기 전에 그 경로로 한 번 돌려 본다.** 인접 경로(자연어)가 잘 되면
전체가 되는 줄 알기 쉽다 — 어제 「자문과 `/law`가 코드 두 벌이라 한쪽만 개선됐다」(#88 후속)와
같은 구조의 실수다.

### ② 같은 사건 4건이 한 통에 — 클러스터링이 관점 차이를 못 넘는다

공정위 통신3사 불공정약관 시정 기사 4건이 **12:55:07에 동시 적재**됐다(배치가 쌓인 게 아니라
한 실행분에서 못 묶인 것). 제목을 재보니 어휘가 겹치지 않는다:

```
공정위 발표 관점:   "이용자 개인정보 보호 등 권리 강화"
약관 조항 인용:     "비암호화 와이파이 정보유출에 책임 없다"…통신 3사 불공정약관 시정
약관 내용:          이통 3사 불공정 약관 자진시정…개인정보 침해사고에 대한 면책 조항
제재 결과:          공정위, SK텔레콤·SK·LG유플러스의 불공정 약관에 '철퇴'

쌍별 공유 키워드: 최대 1개 (임계값은 3)
```

**A. 조사 제거(버그 수정).** `extract_keywords`가 숫자+한글(금액)에만 조사를 떼고 한글 토큰에는
안 뗐다 — 「약관」과 「약관에」, 「유플러스」와 「유플러스의」가 다른 키워드였다. 고쳤다.
**다만 이 사례는 A로 안 고쳐진다**(3-4가 2개로 오를 뿐 임계 3 미달). 다른 사례를 위한 정비다.

**B. 임계값 3→2는 하지 않았다.** #44의 실측대로 「KT 해킹 과징금」과 「KT 5G 과장광고 소송」이
한 사건이 되어 두 번째 사건의 첫 알림이 삼켜진다. 회귀 확인도 해 뒀다(여전히 분리).

**C. 2차 묶기 — 키워드로 못 묶은 대표들만 Haiku에 의미로 묻는다.** `group_same_event()`.
프롬프트의 **「하나의 처분·발표를 매체가 서로 다른 각도에서 쓴 것은 같은 사건이다」 한 문장이
결정적**이었다:

| 입력 | 이 문장 없이 | 넣은 뒤 |
|---|---|---|
| 공정위 4건만 | 2묶음(발표 관점 / 약관 내용) | 2묶음 |
| **+ 다른 사건 2건 섞음(6건)** | — | **4건이 정확히 한 묶음** + KT 소송·LGU+ 인증 각각 분리 |

**대조군이 있을 때 더 정확하다** — 「무엇이 다른 사건인지」 기준이 생기기 때문이다. 실제 크롤링은
항상 여러 사건이 섞여 들어오므로 이쪽이 현실 조건이다. **오묶음(false merge)은 실측 0건.**

⚠️ **이 판정은 클러스터링에만 쓰고 억제(`is_followup`)에는 쓰지 않는다.** 비대칭이 중요하다 —
묶기가 틀리면 대표 + 「(관련 보도 N건)」으로 남지만, **억제가 틀리면 알림 자체가 사라져 되돌릴 수 없다.**
실패 시 1차 결과를 그대로 쓰는 fail-open이며, 응답 번호가 1~N과 정확히 일치하지 않으면
**부분 신뢰 없이 통째로 버린다.**

비용: 크롤링 실행당 최대 1회(대표가 2개 이상일 때만), 제목 몇 줄 = Haiku 수백 토큰.

**#92 후속 — `/law`를 고치자 이번엔 표시가 깨졌다.**

번호 조회를 고친 직후 운영자가 `/law 무선종사자 자격 12조`를 다시 실행했다. 조회는 성공했는데
화면에 **마크다운 표 구분선(`|---|---|`), `<br>` 태그, 원본 이미지 보존 주석까지 날것으로** 찍혔다.

원인은 **경로별 소비 방식 차이**다. 어제 OCR(#91)로 넣은 것은 마크다운 표인데,

| 경로 | 결과 |
|---|---|
| `/ask` 자문 | ✅ 모델이 읽고 **문장으로 풀어 준다**(전파사용료 답변에서 별표 산식이 문장으로 나온 그대로) |
| `/law` 원문 표시 | ❌ 원문을 **그대로** `escapeHtml`해 보여주므로 마크다운이 노출된다 |

**잘 되는 경로가 있으면 다른 경로도 되는 줄 알기 쉽다** — #92의 ①과 정확히 같은 실수를,
같은 날 같은 기능에서 반복했다.

조치: `plainifyArticle()`로 **표시할 때만** 다듬는다(DB 원문은 그대로 둔다).
주석 제거 → 굵게 표시 제거 → 표 구분선 삭제 → 표 행을 `·`로 연결 → `<br>` 풀기.
**치환 순서가 중요하다** — `<br>`을 먼저 개행으로 바꾸면 한 행이 여러 줄로 쪼개져
표 행 정규식이 더는 맞지 않는다(첫 구현에서 실제로 그랬다).
항목 셀이 여러 줄짜리면 값을 끝에 매달지 않고 `→`로 아래 줄에 붙인다.

텔레그램은 고정폭 폰트가 아니라 **표를 표로 보여줄 방법이 없다.** 목표는 「표처럼 보이게」가
아니라 「노이즈 없이 읽히게」다. 표 없는 일반 조문은 아무것도 바꾸지 않는 것으로 확인했다.

---

**#93 주제 관계도가 헤어볼이었다 — 계열 1단 확장이 직접 3개를 52노드로 부풀렸다 (2026-08-07).**

운영자가 「주파수 재할당」 주제 화면을 보고 지적했다 — 주제에 직접 연결된 법령만이 아니라
연결된 법령의 계열 전체(고시 수십 개)까지 그려져 조망이 불가능했다.

**데이터는 멀쩡했다.** 실측:

| 주제 | 직접 연결 | 계열로 딸려옴 |
|---|---|---|
| 주파수 재할당 | 3 | +49 |
| 3G 종료 | 4 | +80 |
| 재난로밍 | 6 | +76 |

원인은 `app.js` `lawmapNeighborhood`의 **계열(하위법령) 1단 확장** — 주제의 직접 이웃에
전파법이 들어오는 순간 전파법 계열(시행령→고시 수십 개)이 통째로 딸려왔고, 엣지 필터가
keep 내부 엣지를 전부 살리므로 고시끼리의 인용선까지 그려져 거미줄이 됐다.

**조치: 주제(topic) 포커스일 때만 계열 확장을 끈다.** 근거 엣지로 직접 연결된 것만 그린다.
- 직접 이웃끼리의 계열 선은 그대로 보인다 — 「주파수 재할당」은 전파법(법률)—전파법 시행령—
  주파수할당 신청 절차 고시가 모두 직접 이웃이라 **법률→시행령→고시 3단이 선으로 이어진 채**
  4노드로 그려진다. 운영자가 물은 "3단 연결 + 고시 역연결 구조 덕에 잘 나오는가"가 맞았다 —
  데이터 구조가 좋아서 직접 연결만 보여도 계열 골격이 살아 있다.
- **법령 노드 클릭 시의 계열 확장은 유지**(전파법 클릭 → 137노드 계열 보기). 용도가 다르다.
- 「전부 다시 작성」은 불필요했다 — 그리는 코드 한 곳을 고치면 59개 주제 전체에 일괄 적용된다.

검증(로컬, 실데이터): 59개 주제 전부 **3~17노드**(종전 52+), 최대는 「통신 상품 표시·광고·약관」 17노드.

주의: 주제 포커스 중 계열로 딸려온 노드의 조문 검색 로직(지침 §관계도, '계열 간접 노드' 피드백)은
이제 주제 화면에서 대상이 없지만, 법령 노드 포커스에서는 여전히 쓰인다 — 제거하지 말 것.

---

**#94 계정 정지 중에도 GitHub을 매시간 두드리고 있었다 — 디스패치 잡 4개 일시 중지 (2026-08-10).**

GitHub 계정 정지(티켓 #4621561) 1주차 점검에서 발견 — pg_cron의 `dispatch_github_workflow`
잡 4개(crawl-trigger-hourly·assembly·law·watchdog)가 **여전히 매시간 GitHub API를 호출**하고
있었고 전부 422("Actions has been disabled for this user")로 거부되고 있었다.

문제는 두 겹: ①**심사 중인 계정에 자동화 트래픽이 계속 찍힌다** — 정지 사유가 자동화 오인일
가능성이 높은 상황에서 최악의 신호다. ②어차피 전부 실패라 아무 일도 안 한다. 수집은 이미
PC 스케줄러(`radio_TEMP_*`)로 이관돼 있어 기능 손실도 없다.

`cron.alter_job(active := false)`로 4개만 껐다. 발송(subscriber-briefing-hourly)·내부
워치독(watchdog-scan-3x, GitHub 독립)·브리핑 트리거 등 GitHub 무관 잡 7개는 그대로다.
재활성 SQL은 지침 pg_cron 절에 기록. **후속 댓글에 "GitHub을 건드리는 자동화는 전부
중단했다"고 쓸 수 있게 된 것이 부수 효과** — 사실이 된 뒤에 쓴다.

교훈: **외부 서비스가 우리를 차단하면, 우리 쪽 자동 호출부터 끈다.** 실패 호출은 로그에서
무해해 보여도 상대 쪽 기록에는 '차단 후에도 계속 시도한 자동화'로 남는다.

---

**#95 보도자료 기준문이 뉴스 기준문과 어긋나 있었다 — 부처 인사·국가 AI 사업 누락 (2026-08-12).**

운영자가 과기정통부 홈페이지를 직접 보고 「8/11자 두 건이 왜 안 들어왔나」를 물어 발견했다.
누락 사유가 서로 달랐다.

**① 과기정통부 인사(과장급) — 기준문 불일치.** 뉴스 경로는 부처 인사를 **무조건 통과**시킨다
(`news_relevance_criteria`에 「부처 인사는 관련」 명시 + `crawler.py`의 `is_ministry_personnel_news()`가
코드로 한 번 더 보장). 그런데 **보도자료 기준문(`press_relevance_criteria`)에는 인사 항목이 아예 없었다.**
같은 성격의 자료를 한쪽 경로는 반드시 받고 다른 쪽은 판단조차 못 하는 상태였다.
「채용 공고」 제외 항목이 있어 Haiku가 인사 발표를 거기에 붙였을 가능성이 크다.

**② 독자 AI 파운데이션 모델 4개 정예팀 Epoch AI 등재 — 도메인 지식 부재.**
기준문의 「통신과 무관한 순수 과학 R&D 성과 홍보」에 걸려 제외됐고, 기준문만 보면 타당한 판정이었다.
**그러나 SK텔레콤이 그 4개 정예팀 중 하나다** — 운영자가 알려주기 전까지 시스템도 나도 몰랐던 사실이다.
자사가 참여한 국가 AI 사업의 진척·평가는 명백히 업무 관련이다.

**조치.** `app_config.press_relevance_criteria`의 「관련 있음」에 두 항목을 추가했다(코드 배포 불필요):
- **국가 인공지능 사업의 추진 경과·성과**(독자 AI 파운데이션 모델 정예팀 등 — SK텔레콤이 참여사이므로
  사업 진척·평가·모델 등재 소식도 관련)
- **소관 부처(과기정통부·방송미디어통신위원회·국립전파연구원·중앙전파관리소)의 인사·조직개편 발표**

「관련 없음」의 `채용 공고`는 `일반 직원 채용 공고(부처 인사 발표는 제외 대상이 아니다)`로 명확히 했다.

**백필.** 전량 재수집(2024~)은 과해서 — 실제로 돌려 보니 7분이 지나도 안 끝났다 — **제목으로 두 건만
찾아 `press_ingest._collect_one()`에 넘기는 표적 스크립트**를 썼다. 기준문을 **먼저 고치고** 백필해야
한다(순서를 바꾸면 갱신 전 기준으로 다시 걸러진다). 갱신된 기준문으로 판정을 태운 결과
**무관제외 0건 · 신규 2건**으로, 수정이 실제로 듣는지까지 함께 검증됐다.
등재 후 `backfill_embeddings.py`로 청크 4개 임베딩 생성, 시맨틱 검색 1·2위 확인.

**교훈.** ①**같은 종류의 자료를 두 경로가 다르게 취급하고 있지 않은지 주기적으로 대조할 것** —
뉴스/보도자료 기준문은 각자 진화하다 어긋난다. #88·#92에서 반복된 「코드가 두 벌이라 한쪽만 낡는다」의
데이터 판본이다. ②**기준문은 도메인 지식을 담아야 한다** — 「SKT가 그 사업의 참여사」 같은 사실은
일반 상식으로 유추되지 않으므로 명시해야 한다. 운영자만 아는 사실은 물어보거나 기준문에 박아야 한다.

---

**#96 보도자료 관련성 판정을 Batch API로 — 토큰 50% (2026-08-13).**

운영자의 비용 절감 요구에서 시작해 **가능한 수단을 전부 실측으로 기각한 끝에 남은 하나**다.
기각 근거를 함께 남긴다 — 같은 조사를 반복하지 않기 위해.

| 후보 | 실측 결과 | 판정 |
|---|---|---|
| 프롬프트 캐싱 | 실제 API로 2회 연속 호출 → **캐시 저장 0·읽기 0**. 크롤러 시스템 프롬프트가 1,130토큰이라 Haiku 최소 캐시 길이(2,048) 미달로 API가 조용히 무시 | ❌ **이득 0** |
| 야간 수집 중단 | 야간 8회는 하루 26건(전체 11%)뿐이고, 끊어도 05:50이 몰아서 판정하므로 기사당 비용은 그대로. 실행 고정비만 절감 | ❌ 월 ~500원 |
| 긴급도 배치화 | 절감 월 ~6천 원이나 배치는 계약상 **24시간까지** 걸릴 수 있어 긴급 알림에 꼬리 발생 | ❌ 약속 훼손 |
| 긴급도를 선별콜에 통합 | #84에서 이미 시도 → 긴급률 9.9%→0.7% 회귀로 원복 | ❌ 재시도 금지 |
| **보도자료 배치화** | 지식베이스행이라 즉시성 불필요. 17시 체인이라 수십 분 지연 무해 | ✅ **채택** |

**착각 정정 두 가지.** ①「월 17만 원 페이스」로 놀랐던 것은 오독이었다 — 8/2~3 스파이크는
보도자료 백필(6,012청크 판정)이라는 **일회성**이었고, 평상시는 **월 ~8만 원**이다.
②「태그 판정이 기사마다 따로 돈다」고 분해했으나 실제로는 **선별 배치콜에 이미 통합**돼 있었다.
파이프라인은 이미 세 번 최적화된 상태(선별 캐시·배치 선별·용어 배치)이고 토큰 볼륨 ▼60%가 그 결과다.

**설계.** `batch_judge_all()`을 추가하고 `run_daily`가 신규 후보를 모아 한 번에 제출한다.
- **자료 손실 경로가 없다**: 배치에 태우는 것은 원문이 아니라 **「이거 관련 있어?」라는 질문**이고,
  제목·본문·URL은 제출 전에 확보돼 있다. 만료·실패분은 결과 dict에서 빠지고 **그 건만 개별 판정**으로
  넘어간다(만료분은 과금되지 않아 이중 지불도 아니다).
- **프롬프트를 `_judge_prompt()` 한 함수로 통일** — 배치/개별이 다른 문구를 쓰면 같은 기사가
  실행 방식에 따라 다르게 판정된다. #88·#92의 「코드가 두 벌」을 미리 막은 것.
- `BATCH_MIN_ITEMS=5` — 신규 1~2건뿐인 날이 흔한데, 그런 날은 제출·폴링 왕복이 절감액보다 비싸다.
- 10분 안에 안 끝나면 개별 판정으로 폴백(그날 할인만 포기).
- 배치 선판정 때 뽑은 본문을 `item['_body']`로 넘겨 **정부 사이트에 같은 첨부를 두 번 받지 않는다.**

**검증(실제 Batch API).** 관련/무관이 섞인 6건을 개별·배치 두 경로로 돌려 대조:
**수신 6/6 · 판정 6/6 일치.** 소요는 개별 5.4초 / 배치 141.2초 — 17시 체인이라 무해하다.
표본에는 이번 주 실제 사건(재할당 제도개선·부처 인사·AI 정예팀·공정위 약관)을 넣어
#95에서 고친 기준문이 배치 경로에서도 같게 동작하는지 함께 확인했다.

**절감.** 보도자료 판정 월 ~1만 원 → ~5천 원. 나머지 파이프라인(해외규제·국회·회의록·법령DIFF)은
**판정 물량이 하루 0~35건뿐**이라 전부 배치화해도 추가 절감이 월 2~3천 원인 반면, 해외규제는
06:05 브리핑까지 35분 여유뿐이고 국회는 당일 알림이 있어 꼬리 위험이 있다 — 하지 않는다.

**결론: 이 시스템의 적정 운영비는 월 8만 원이고, 그것이 품질을 유지하는 최저가다.**

---

**#97 회의록에 국정감사가 통째로 빠져 있었다 — 2년치가 조용히 (2026-08-14).**

운영자의 질문 하나에서 드러났다. "2019년 국정감사에서 김성수 의원이 무선국 관련해 발언한 내용을 찾아 달라."
`assembly_speeches`를 뒤지니 2024~2026년만 있고 김성수 0건. 국회 시스템에 직접 붙어 찾아냈고
(2019-10-02 과방위 국감, 5G 기지국 비용 질의 중 **"무선국 검사 수수료는 3년마다 타당성 검사하게 돼 있는데
10년째 똑같다"** — 과기정통부가 검사표본 20%→10% 인하, 무선국 면허세는 행안부와 협의 답변),
그 과정에서 **연도 문제가 아니라 구조 문제**가 드러났다.

**진단.** `assembly_minutes.py`가 쓰는 열린국회 `ncwgseseafwbuheph`는 **`CLASS_NAME='상임위원회'인 회의록만**
반환한다. 2019년 과방위 41건을 전수 조회해도 국감은 0건이고, `CLASS_NAME='국정감사'`로 질의해도 0건이다.
10월에 잡히는 10-02·10-11·10-14는 "국정감사 증인 출석요구의 건"을 처리한 **짧은 전체회의**(발언 2~23블록)일 뿐
감사 본체가 아니다. 즉 **매년 10월, 전파정책 관점에서 밀도가 가장 높은 자료가 처음부터 수집 대상 밖**이었다.
징후는 있었다 — 2024·2025년 10월 발언이 각각 0건·3건뿐이었는데 "그날 회의가 없었나 보다"로 넘어갈 만한 모습이었다.

**국감 회의록이 있는 곳.** record.assembly.go.kr 검색 API(`/assembly/mnts/search/search.do`)뿐이다.
브라우저로 실제 검색을 태워 폼이 만드는 `form_data`를 그대로 확보해 재현했다. 함정이 넷이었다:

| 함정 | 증상 | 해법 |
|---|---|---|
| `collection='record'`(상임위 기본값) | HTTP 200 + **빈 `{}`** — '결과 없음'과 구분 불가 | `collection='record5'` + `CLASS_CD='5'` |
| `CMIT_CD` 하드코딩 | 대(代)마다 코드 재배정(20대 과방위 국감=20-5-AB-0, 22대=**22-5-AG**, 20대의 20-5-AF-0은 문체위) | 검색폼 `#com5List`에서 자동 탐지, 상수는 폴백 |
| 대수 코드 | 폼은 **24=제22대**, Open API는 `DAE_NUM='22'` — 같은 뜻 다른 값 | 상수 주석에 못박음 |
| 날짜 범위 생략 | 22대 전체 1,541히트를 최신순으로만 훑어 **2024년 국감 10건 전량이 페이지 상한 밖으로 밀려 0건** | `startDate`/`endDate`에 연도 범위 필수 |

열거 질의어는 `'국정감사'` 전수 페이징으로 정했다. 히트가 연 730~811건(73~82페이지)이라 `'산회'`로 줄여봤는데
**2024년 10건 중 2건·2025년 9건 중 0건**만 잡혔다 — 산회 선포가 발언 블록으로 남지 않는 회의가 많다.
싸게 끝내려다 조용히 빠뜨리는 쪽이 훨씬 비싸므로 전수 페이징을 택했다.

**뷰어 id 체계가 다르다.** 국감은 `MNTS_ID`(2019 국감 41178), 상임위는 `CONFER_NUM`(44269·52648 계열).
값이 겹칠 수 있어 `assembly_speeches.confer_num`은 **`audit-{MNTS_ID}`**로 네임스페이스했다.
원문 파싱부터는 같은 뷰어 구조라 기존 함수를 그대로 쓴다 — 새 파서를 만들지 않았다.

**자사 언급은 주제 불문 수록(운영자 지시).** 키워드·Haiku 판정을 건너뛰고 확정한다. 여기서 한 번 더 걸릴 뻔했다 —
확정 블록이 상한을 넘으면 `[:50]`으로 앞에서 자르는데, 2024-10-08 국감은 확정 93개에 자사 언급이 13개였고
그중 9개가 인덱스 1179 이후였다. **"무조건 포함"이 상한에서 조용히 무효가 되는 구조**라 `cap_indices()`로
자사 블록을 먼저 채우고 나머지를 채우게 고쳤다(발언자 14명→16명으로 실측 확인).

**검증(DB 무변경).** 2024년 10건·2025년 9건 목록 확인(날짜·피감기관 일치), 2024-10-08 회의 1,691블록에서
확정 93·발췌 208·섹션 11.9KB·발언행 50건 구성 확인, 자사 블록 13개 전부 확정 포함. 상임위 경로는
2026년 33건 전량 dup(신규 0)으로 회귀 없음 확인.

**교훈.** ①**"수집기가 도는데 그 카테고리가 0건"은 API 스키마를 의심할 신호다** — 이번엔 CLASS_NAME 한 칸이
2년치를 갈랐고, 아무도 에러를 보지 못했다. ②**한도(top-N)를 두는 곳마다 "반드시 넣어야 하는 것"이
그 한도에 잘리는지 확인할 것** — 우선순위 없는 상한은 강제 규칙을 조용히 무효화한다.

---

**#98 국회 발언 검색 — 축적하지 않고 답하는 길 (2026-08-14).**

#97 직후 운영자가 물었다. "아까 김성수 의원 발언처럼 찾아보려면 **어떤 데이터를 축적해 놔야 하나?**"
정직한 답은 **"축적 안 해도 된다"**였다. 그 발언을 찾은 건 DB가 아니라 국회 시스템 실시간 검색이었고,
그 경로는 #97에서 이미 코드가 됐다. 그래서 축적(수집기)과 조회(검색)를 **분리**하기로 했다.

**왜 축적으로는 못 푸나.** `assembly_speeches`의 구조적 한계 셋이다 — ①22대(2024~)뿐,
②**키워드·판정 통과분만** 저장(그때 관심 없던 주제는 영영 안 들어온다), ③원문 없이 **요지(summary)만**.
④거기에 위원회 필터가 현행 명칭 하나라 **20대 전반기 미래창조과학방송통신위원회(2016~2018)가 통째로** 빠진다
(실측: 20대 미방위 2016년 17건·2017년 11건이 따로 잡힌다). 소급 백필로 ①~④를 다 메우려면 400여 회의인데,
그렇게 해도 "관심 밖이었던 주제"는 여전히 못 답한다. 반면 국회 검색은 **제헌국회부터 전량**을 이미 갖고 있다.

**그래서 만든 것.** `_shared/assembly_search.ts` 하나에 검색 + 자연어 파서를 두고
**텔레그램(`assem`)과 대시보드(`assembly-search` 함수)가 공유**한다. 두 벌로 갈라지면 같은 질문에
경로마다 다른 답이 나온다 — #88·#92에서 두 번 겪은 실패라 처음부터 한 파일로 시작했다.

**범위는 좁혔다(운영자 지시).** 과방위 상임위 + 국정감사뿐이다. 전 위원회 검색도 실측으로 되는 걸
확인했지만(본회의·예결위 포함 33건), 전파·통신 문맥 밖이고 **동명이인 발언이 섞여 오답**이 된다.
대신 20대 전반기 미방위는 **반드시** 포함했다 — 이 한 줄이 2016~2018년의 존재 여부를 가른다.

**파라미터 함정 넷**(#97과 공통): `collection`은 `record2`(상임위)/`record5`(국감)이며 `record`로 보내면
200 + 빈 `{}`, `CMIT_CD`는 대마다 재배정(20대 AB·미방위 RN / 21대 AF / 22대 AG)되지만 **콤마 다중 지정이 되어**
20~22대·상임위·국감을 한 번에 조회할 수 있다, `S_TH/E_TH`는 폼 대수코드(22=20대), 쿠키는 불필요하다.

**자연어 파싱은 규칙 우선.** 운영자가 지정한 입력 형태가
`assem 2019년 국정감사에서 김성수 의원이 무선국 관련해서 발언한 내용을 찾아줘`라 파싱이 필요했다.
정규식 파서로 먼저 처리하고(의원명·연도·회의구분·핵심어), **핵심어를 못 뽑을 때만** Haiku 1콜을 보조로 쓴다.
실측 6개 문장이 전부 규칙만으로 통과했다 — 즉 **평소 비용은 0**이다. 파서를 만들며 두 번 미끄러졌다:
①"주파수 재할당에 대해 어떤 얘기가 있었나"의 **'주파수'가 의원명으로 승격**돼 0건이 됐다.
→ 첫 낱말 승격은 **군더더기 없는 두 낱말 입력**("김성수 무선국")에서만 허용하도록 좁혔다.
②"뭐라고 했는지"의 **'했는지'가 검색어에 남았다** → 불용어 목록으로는 끝이 없어 **어미 정규식**으로 걸렀다.
검색어는 2개까지만 넘긴다 — 원문 AND 검색이라 낱말이 늘수록 0건이 된다.

**해석 결과를 화면에 먼저 보여준다.** 자연어 파싱은 반드시 빗나가는 날이 오는데, 무엇으로 해석했는지를
숨기면 사용자는 "국회에 그런 발언이 없나 보다"로 오해한다. 텔레그램·대시보드 모두 상단에
`김성수 의원 · "무선국" · 2019년 · 국정감사` 조건 칩을 먼저 찍는다.

**검증.** 파서 6/6, 실검색으로 2019-10-02 김성수 의원 무선국 발언 1건 재현, 발언자 무관 질의 32건,
대시보드 렌더링(강조 마커→`<mark>` 2곳·원문 링크·피감기관) 확인.

**교훈. 축적은 목적이 아니라 수단이다.** "어떤 데이터를 쌓아야 답할 수 있나"라는 질문에 늘 "쌓자"로 답하면
안 된다 — 원본이 공개 검색으로 열려 있으면 **쌓지 않고 그때 가서 묻는 편이 더 넓고 더 싸다.**
DB는 매일 보는 것(브리핑·요지·RAG)에, 실시간 검색은 가끔 깊게 파는 것에 쓴다.

---

**#99 적재는 됐는데 읽을 수가 없었다 — 국감 회의록 전면 재작성 (2026-08-14).**

#97 백필로 97회의·2,880발언·98섹션이 들어왔다. 숫자는 완벽했다(실패 0). 그런데 운영자가 화면을 열고
말했다. "국정감사 요약이 잘 안 되어 있는 것 같고, 요약을 보고 상세를 누르면 **질의/응답한 내용이 보여야
되는데** 그것도 잘 안 되어 있는 것 같다." 그리고 곧이어 "**발언자별도 이상하게 잡히는 것 같다**."
**적재 성공률과 읽을 수 있는 상태는 다른 문제였다.**

**원인 넷.**
1. **요지가 요약이 아니었다.** 백필을 운영자 지시대로 무료(키워드) 모드로 돌렸는데, 그 폴백이
   `원문[:120]`이었다. 2,877/2,880건이 문장 중간에서 잘렸고 말줄임표도 없었다 — "…무선국 개설 절차를
   보면 지금 현재는 신고를 하게 되어 있는데 이게 실제로는" 에서 끝나는 식이다. **폴백은 동작했지만
   읽히지는 않았다.**
2. **섹션 본문이 평면 나열이었다.** `관련 발언:` 밑에 발언을 순서대로 붙였을 뿐이라 **질의와 답변이
   짝지어지지 않았다.** 국감의 값어치는 "의원이 묻고 부처가 뭐라 답했나"인데 그게 안 보였다.
3. **절차성 발언이 본문을 잡아먹었다.** 개회 선포·증인 선서·인사말·산회가 그대로 실렸다
   (2019-10-02 회의는 2,146블록 중 **1,439블록**이 절차성이었다).
4. **발언자 이름이 80건 깨져 있었다.** 뷰어 PDF 폴백 경로에서 라벨이 문장째로 들어와,
   발언자별 보기의 드롭다운에 사람 이름 대신 문장이 섞였다.

**고친 방식.** ①`is_procedural()` 정규식으로 절차성 블록 제거, ②`_qa_lines()`로 `▶ 의원` / `　↳ 답변`
짝 구성 — **답변은 선별 여부와 무관하게 원문 블록에서 끌어온다**(답변자가 차관이라 발언자 필터에 안
걸리는 문제를 #98에서 겪었다), ③`extract_gist()`로 **키워드가 든 첫 완결 문장**을 뽑고 앞머리
`(무대지시)` 괄호를 떼어냄(2,775행 갱신, 평균 80자), ④`normalize_speaker()`에 `이름+직위` 추출 폴백을
넣고 실패 시 '미상'(깨짐 80 → **0**). **여기서도 유료 AI 호출은 0이다** — 운영자 방침("일회성이니 세션에서
처리하라")대로 전부 규칙 기반으로 풀었다.

**작업 중 자초한 사고 하나 — 그리고 그 수습이 더 비쌌다.** 재작성 프로세스를 **두 개 동시에** 띄우는
바람에 섹션 5건이 중복 등재됐다. 정리는 했는데(`dedupe_sections.py`), **중복분만 지운 게 아니라 이웃 섹션의
꼬리 청크까지 함께 지웠다** — 2017년 2개·2020년 1개 섹션이 본문 한가운데서 끊겼고 유실량이 각각
28,000자·7,700자·9,100자였다. 무서운 건 **섹션 개수를 세면 98/98로 완벽해 보였다**는 점이다.
드러난 건 `chunk_index` 결번을 센 다중 에이전트 검증에서였고, 결번 구간의 길이가 앞 섹션의 청크 수와
**정확히 일치**한 것이 범인을 지목했다. 교훈은 둘 — 장시간 배치는 **띄우기 전에 같은 작업이 도는지 확인**할 것
(로그만 보면 둘 다 정상이다), 그리고 **정리용 DELETE는 범위를 명시하고 지울 행 수를 먼저 출력해 볼 것.**

**주제어 오탐도 같은 검증에서 나왔다.** 한국어·약어는 단어 경계가 없어 단순 `in` 매칭이 오탐을 쌓는다 —
`AI`가 **KAIST·KAIT·KAI**에 걸려 오탐 199건, topic 1위(1,399회)를 이게 상당 부분 밀어올렸다. `무선`은
`실무선에서`에, `6G`는 `35.6GW`에 걸렸다. **오탐은 태깅만 망치는 게 아니라 `relevance_score()`의 우선순위를
왜곡해 무관한 블록을 수록 상한 안으로 밀어 넣는다.** 앞뒤 글자 검사로 164행을 걷어냈고, 운영자 예시였던
`요금소`·`전파상`은 **말뭉치에 0회여서 넣지 않았다** — 지침의 "실측된 것만" 원칙이다.

**뒤늦게 드러난 뿌리 하나 — 뷰어가 페이지를 덜 보낸다.** 복구 작업 중에 같은 id(51996)가 어떤 때는
3,449블록, 어떤 때는 432/363블록으로 오는 것을 봤다. `fetch_speech_blocks()`가 **한 번만 받고 있었으므로**,
부분 응답 시점에 걸린 회의는 잘린 채 등재되고 `section_exists()`가 헤더만 보고 dup 처리해 **영구히
갱신되지 않는다.** 위 삭제 사고와 **증상이 똑같은 두 번째 경로**였던 셈이다. best-of-N(최소 2회, 90% 근접 시 중단)
으로 막았다. 함께 드러난 것이 **빈 껍데기 섹션** — 판정이 전부 탈락하면 `(키워드 관련 발언 없음 …)`만 남는데
그것도 dup이라, `## 241021` 국감은 **발언 12건이 있는데 섹션은 껍데기**인 상태로 굳어 있었다.

**질의·응답이 31%밖에 안 짝지어졌던 이유.** `_qa_lines()`가 절차성 판정의 `MIN_SUBSTANTIVE_LEN=60`을
**답변에도** 적용해 "예, 그렇습니다"·"검토하겠습니다"·"행안부와 협의하겠습니다" 같은 **짧은 확답을 전부
버렸다.** 원문 실측상 의원 블록 바로 뒤 비의원 블록의 58~79%가 답변인데 그중 60자 이상은 13~24%뿐이다.
길이 조건만 빼자 부착률 30.4% → **77.4%**, 같은 의원 `▶` 연속은 31.0% → **9.5%**가 됐다.
**국감의 값어치는 대개 짧은 확답에 있다** — "무선국 면허세는 행안부와 협의해 낮추겠다"가 그날의 성과다.

**교훈.** ①**"실패 0"은 품질 지표가 아니다.** 파이프라인 성공률과 산출물 가독성은 별개이고, 후자는
화면을 열어 사람이 읽어봐야만 드러난다. ②**폴백을 설계할 때 폴백 결과물의 품질도 설계해야 한다** —
`[:120]` 절단은 "AI 없이도 돌아감"을 만족시켰을 뿐 "AI 없이도 쓸 만함"은 아니었다.

---

**#100 구독자가 늘 것을 대비한 권한·이력·리포트 (2026-08-14).**

`assem`이 붙으면서 운영자가 물었다. "비용이 안 들면 좀 더 많은 사람이 사용하게 하고 싶다."
셋을 재보니 **assem 0원**(국회 검색은 무료, 규칙 파서라 AI 0콜), **/law 약 25원**, **/ask 약 80원**
(Sonnet 5 도입가 기준. 2026-08-31 이후 정가로 오르면 /ask는 약 120원). 그래서 결론은
"**assem은 열고, 돈 드는 둘은 조인다**"였고 운영자가 확정했다 — "law와 ask 모두 한도제를 유지하고,
**기존 가입자 말고 구독 가입하는 사람은 law도 허용을 받고** 사용할 수 있도록 해 달라."

**권한을 둘로 쪼갰다.** `telegram_subscribers.law_allowed`(기본 false)를 신설하고 **기존 5명은 마이그레이션
UPDATE로 소급 true** — 잘 쓰던 사람이 어느 날 갑자기 막히면 그게 장애로 보고된다. 승인은 `/ask`와 같은
방식(운영자에게 인라인 버튼 → `law:ok:` / `law:no:` / 회수 `law:rv:`)이되 **콜백 접두를 분리**해
기존 `ai:` 흐름과 섞이지 않게 했다. **조문번호 직답(`/law 전기통신사업법 19조`)은 게이트를 우회한다** —
DB 조회만 하고 AI를 안 쓰므로 조일 이유가 없다. 조이는 기준은 "기능"이 아니라 **"돈이 드는 경로"**다.

**누가 무엇을 썼는지 몰랐다.** 그동안 남은 건 `ai_count`/`law_count` 카운터뿐이라 "무엇을 물었나"가
없었다. `telegram_usage`(chat_id·command·query·ok·note·created_at)를 신설하고 assem·law·law_article·ask·start
지점에 `logUsage()`를 넣었다. **fail-open이다** — 로깅 실패가 본 기능을 막으면 본말전도다.
기존 카운터로 과거분을 백필해 첫날부터 통계가 비어 보이지 않게 했다.

**매일 아침 관리자 리포트.** 운영자 요청으로 Edge Function `admin-daily-report`를 만들어 pg_cron
`0 0 * * *`(UTC) = **09:00 KST**에 운영자 봇으로 보낸다. 구독자 목록·권한(자문/법령)·수신 설정·관심분야·
명령 사용 통계가 들어간다. 인증은 Vault `admin_report_cron_secret`를 `x-cron-secret` 헤더로 받고
**`--no-verify-jwt`로 배포**한다(#83과 같은 방식). 초안에는 '최근 발송 브리핑'을 넣었는데 운영자가 뺐다 —
**매일 같은 날짜가 찍혀 신호가 되지 못한다.** 리포트는 "변하는 것"만 실어야 읽힌다.

**같은 날 나온 사용성 결함 둘.** ①결과가 5건에서 잘려 "이게 전부"로 읽혔다 → 5건씩 끊고 **'더 보기'
콜백 페이징**을 붙였다. ②운영자가 `22대 국회에서 무선국 관련 발언`을 넣자 **'22대'가 사람 이름으로
승격**돼 193건이 쏟아졌다(#98에서 '주파수'로 한 번 겪은 실패의 재발이다). 대수 표기를 별도 필드(`dae`)로
파싱하고, 폴백 검색어를 '첫 낱말'이 아니라 **'가장 긴 낱말'**로 바꿨다 — 조사·수식어는 짧고 핵심어는 길다.

**다중 에이전트 재검증에서 나온 것(운영자 지시).** 네 갈래(데이터 무결성 / assem 정확도 / 대시보드 / 텔레그램)로
동시에 돌렸고, **혼자서는 못 봤을 결함 둘**이 나왔다. ①`/law` 게이트를 `if (sub && !sub.law_allowed)`로 써서
**구독 행이 없는 계정**(=`/start`를 거치지 않고 곧장 명령을 보낸 경우)에 게이트·한도·로깅이 통째로 열려 있었다.
`/ask`는 `if (!sub?.ai_allowed)`로 fail-closed였는데 새로 쓴 쪽만 반대로 나갔다. ②`telegram_usage` 생성
마이그레이션에 **RLS가 빠져** 공개 anon 키로 chat_id와 질의 원문이 열려 있었다. 둘 다 **"동작한다"로는 절대
드러나지 않는 결함**이고, 실제로 정상 동작 확인은 전부 통과한 상태였다.

**assem 정확도는 47.5% → 77.1%**(신규 35질의). 재측정에서 새 실패 유형이 드러났다 — 1차의 최악은 **0건**이었는데
지금은 **0건을 피하려다 그럴듯한 대량 오답**을 내는 것이 최악이다. `의원님들이 언급한 전파 정책`이
검색어 `의원님들이`로 나가 무관한 409건을 냈다. 조사 절단 목록에 `이`를 넣으면 `어린이`→`어린` 같은 새 사고가
나므로 **인칭어 전용 패턴**으로 걸었고(→ 88건), 범위 밖 대수(`제19대` 192건)도 값과 무관하게 걷어내되
"범위 밖"임을 화면에 알리게 했다. 그리고 **재시도로 조건을 푼 결과에는 그 사실을 반드시 표시**하도록 했다 —
건수가 크면 사용자는 그것을 신뢰의 근거로 읽는다.

**교훈.** ①**권한은 기능 단위가 아니라 비용 단위로 나눈다** — 같은 `/law`이라도 AI를 태우는 경로만 조이면
사용자 체감 제약은 최소가 된다. ②**기존 사용자에게는 반드시 소급 허용을 걸어라.** 새 제약을 도입할 때
가장 흔한 사고는 신규 정책이 기존 사용자를 조용히 끊는 것이다. ③**같은 판단을 두 곳에 쓸 때 한쪽만
반대로 나가는 일이 실제로 일어난다** — `/ask`는 fail-closed, `/law`는 fail-open이었다. 기존 코드의 형태를
베끼는 것이 새로 쓰는 것보다 안전하다.

---

**#101 학습 시점의 '예정'이 그대로 나갔다 — 일본 3G 종료 오답 (2026-08-19).**

동료가 텔레그램으로 물었다. "일본 도코모·KDDI·소뱅이 기존 이동통신 주파수를 5G로 리파밍했다는데
상세 조사." 답변은 그럴듯했지만 운영자가 PDF를 보고 짚었다. "3G 종료 시점 등 일부 내용이 잘못된 것 같다."

맞았다. 답변은 도코모 3G(FOMA)를 **"2026년 3월 31일 종료 예정"**이라고 썼다. 날짜는 정확한데
**답변 작성일이 8월 18일**이었다. 이미 5개월 전에 끝난 일을 미래형으로 쓰고, 심지어
"플래티넘밴드 재편의 법적·기술적 트리거로 **작동합니다**"라고 현재진행형 서술까지 붙였다.
KDDI(2022년 3월)·소프트뱅크(2024년 4월)의 종료는 아예 빠졌다 — 일본은 이미 3G가 완전히 끝난 상태다.
밴드 번호도 섞였다. 도코모에 소프트뱅크의 900MHz(B8)를, KDDI에 도코모의 B19를 붙였다(KDDI는 B18/26).

**원인은 4겹이었고, 그중 하나만 진짜 원인이다.**
①**모델 학습 시점에는 그 사건이 미래였다.** 이게 뿌리다. 모델의 기억 속에서 2026-03-31은 아직 안 온 날이라
자연스럽게 "예정"이라고 썼다. ②**웹검색이 교정하지 못했다.** 출처를 세어 보니 일본 관련 웹 문서가
**3건뿐**이었고 — 취미 블로그(2023년 9월 기지국 통계), MVNO FAQ, **2021년** 전자신문 — 3G 종료나
리파밍 정책을 다룬 문서는 **한 건도 없었다**. 교정 재료가 없으니 모델 기억이 그대로 통과했다.
한국어·영어로만 검색했기 때문이다(검증 때 일본어로 치니 도코모 공식 공지가 즉시 나왔다).
③KB가 국내 특화라 나머지 20여 개 출처(전파법·고시·국내 뉴스)가 무관한데 상위를 채웠다.
④밴드 혼입은 4개사 전 대역을 한 표에 담은 블로그를 산문으로 풀다가 행을 잘못 재조립한 것이다.

**조치(A+B).** `system_prompt.js` [세부 지침]에 두 줄을 넣었다 — 대시보드·봇 공통 원본이라 한 곳만 고치면
양쪽에 걸린다(봇은 `sync_system_prompt.py` 실행 필요).
**A 시제 가드**: 과거 날짜를 '예정·계획·전망'으로 쓰기 전에 web_search로 확인하고, 확인 안 되면
`[학습 시점 기준 예정 — 현재 상태 확인 필요]`로 표시. 순차로 일어나는 사안이면 나머지 주체도 함께 확인.
**B 현지어 검색**: 해외 주제는 해당 국가 언어로도 검색해 규제기관·사업자 공식 발표를 우선 확보.
밴드·대역은 사업자별로 근거를 따로 확인(한 표에서 옮길 때 섞지 말 것). 블로그만 남으면 그 사실을 밝힐 것.

**하지 않은 것.** C(경고 문구를 답변 앞머리로 전진 배치)는 코드 수정이라 보류. D(일본·미국·유럽 기초사실
큐레이션 문서를 KB에 등재)는 어느 주제를 넣을지 운영자 판단이 필요해 보류.

**교훈.** ①**모델에게 "오늘"과 "학습 시점"은 다른 시간이다.** 모델은 오늘 날짜를 알면서도 자기 기억의
시제를 자동으로 보정하지 않는다. 날짜 비교를 **명시적으로 지시**해야 한다. ②**웹검색을 붙였다고 최신성이
보장되지 않는다.** 검색어의 언어가 출처 품질을 결정한다 — 해외 주제를 한국어로만 검색하면 공식 자료가
아니라 블로그가 걸린다. ③**답변 스스로 "총무성 원문 미확인, 재확인 권장"이라고 경고했는데도 오류가
그대로 전달됐다.** 경고가 맨 끝에 있으면 읽히지 않는다 — 자기 고지는 설계대로 작동해도 배치가 틀리면
무용지물이다. ④`/ask`는 국내 전파정책 특화 도구다. 해외 심층 조사는 구조적 한계가 있으므로
이용자에게 "해외 조사는 참고용, 수치·연도는 원문 확인"을 안내하는 편이 프롬프트 수정보다 실효적일 수 있다.
