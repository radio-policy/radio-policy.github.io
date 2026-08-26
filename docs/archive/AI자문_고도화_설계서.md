# AI 자문 고도화 설계서
> 작성일: 2026-05-26 | 대상 파일: `app.js`, `crawler.py`, Supabase SQL

---

## 개요

| 기능 | 현재 상태 | 목표 상태 |
|---|---|---|
| **뉴스 참조** | 제목·날짜 40건 일괄 주입 | 질문과 관련된 기사 **본문 발췌** 주입 |
| **Q&A 누적** | 없음 | 검증된 Q&A를 DB에 축적 → AI 자동 참조 |

---

## FEATURE 1. 뉴스 본문 RAG

### 1-1. 문제 진단

현재 `fetchRecentNewsContext()`는 60일치 뉴스 **제목·출처·날짜만** 가져와서 AI에 전달합니다.
AI는 기사 내용을 알 수 없으므로 "최근 동향"을 언급할 수 없습니다.

### 1-2. 변경 계획 (3단계)

```
① Supabase news_feed 테이블에 content 컬럼 추가
② crawler.py: 기사 URL 접속 → 본문 추출 → content에 저장
③ app.js: fetchRecentNewsContext()를 키워드 매칭 방식으로 교체
```

---

### 1-3. SQL — news_feed 테이블 컬럼 추가

Supabase SQL Editor에서 실행:

```sql
-- news_feed 테이블에 본문 컬럼 추가
ALTER TABLE news_feed ADD COLUMN IF NOT EXISTS content TEXT;
ALTER TABLE news_feed ADD COLUMN IF NOT EXISTS content_fetched_at TIMESTAMPTZ;

-- 인덱스: 본문 키워드 검색 성능 향상
CREATE INDEX IF NOT EXISTS idx_news_feed_content ON news_feed USING GIN (to_tsvector('simple', COALESCE(content, '')));
```

---

### 1-4. crawler.py — 본문 수집 함수 추가

`save_new_items()` 함수 **앞에** 아래 함수를 추가합니다:

```python
import time

def fetch_article_body(url: str, source: str) -> str:
    """기사 URL에서 본문 텍스트 추출 (최대 1500자)"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 소스별 본문 셀렉터
        selectors = {
            '전자신문': ['div.article_body', 'div#articleBody', 'div.news_view'],
            '연합뉴스': ['div.article-txt', 'article.story-news'],
            '디지털데일리': ['div#articleBody', 'div.article_txt'],
            '지디넷코리아': ['div#article_content', 'div.article_view'],
            '블로터': ['div.article_content'],
        }
        candidates = selectors.get(source, []) + [
            'article', 'div.article', 'div.news-content',
            'div.view_cont', 'div.view-content', 'div#content'
        ]
        for sel in candidates:
            tag = soup.select_one(sel)
            if tag:
                text = tag.get_text(separator=' ', strip=True)
                if len(text) > 100:
                    return text[:1500]
        return ''
    except Exception as e:
        print(f'  [본문 수집 실패] {url}: {e}')
        return ''
```

그리고 `save_new_items()` 함수를 아래와 같이 수정합니다:

```python
def save_new_items(items: list, existing_urls: set) -> list:
    """기존에 없는 항목만 필터링 후 본문 수집 → 저장"""
    seen_urls = set(existing_urls)
    unique_new = []
    for item in items:
        url = item.get('url', '')
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_new.append(item)

    if unique_new:
        # 본문 수집 (항목당 1초 간격으로 요청)
        print(f'[본문 수집] {len(unique_new)}건 시작...')
        for item in unique_new:
            if item.get('url'):
                body = fetch_article_body(item['url'], item.get('source', ''))
                item['content'] = body
                item['content_fetched_at'] = datetime.now(KST).isoformat()
                time.sleep(1)  # 서버 부하 방지

        sb.table('news_feed').insert(unique_new).execute()
        print(f'[저장] {len(unique_new)}건 본문 포함 저장 완료')
    else:
        print('[저장] 신규 항목 없음')
    return unique_new
```

---

### 1-5. app.js — fetchRecentNewsContext() 교체

기존 함수를 **아래 코드로 전체 교체**합니다:

```javascript
// ════════════════════════════════════════════
//  뉴스 컨텍스트 — 키워드 매칭 + 본문 발췌 (AI 자문 참조용)
// ════════════════════════════════════════════
async function fetchRecentNewsContext(query) {
  if (!sb) return '';
  try {
    var cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 60); // 최근 60일
    var cutoffStr = cutoff.toISOString().split('T')[0];

    // 1) 최근 뉴스 전체 제목 목록 (동향 파악용, 최대 30건)
    var listResp = await sb
      .from('news_feed')
      .select('title, source, published_at')
      .gte('published_at', cutoffStr)
      .not('title', 'ilike', '[업데이트]%')
      .order('published_at', { ascending: false })
      .limit(30);

    var allTitles = (listResp.data || []);

    // 2) 질문 키워드로 본문 매칭 검색 (최대 3건)
    var keywords = extractKeywords(query || '');
    var bodyResults = [];
    if (keywords.length > 0 && query) {
      var seen = new Set();
      for (var ki = 0; ki < Math.min(keywords.length, 3); ki++) {
        var kw = keywords[ki];
        if (kw.length < 2) continue;
        try {
          var bodyResp = await sb
            .from('news_feed')
            .select('title, source, published_at, content')
            .gte('published_at', cutoffStr)
            .ilike('content', '%' + kw + '%')
            .not('content', 'is', null)
            .order('published_at', { ascending: false })
            .limit(2);
          (bodyResp.data || []).forEach(function(n) {
            if (!seen.has(n.title) && n.content) {
              seen.add(n.title);
              bodyResults.push(n);
            }
          });
        } catch(e) {}
      }
    }

    var lines = [];

    // 관련 기사 본문 발췌 (있을 경우 우선 표시)
    if (bodyResults.length > 0) {
      lines.push('[질문 관련 최신 기사]');
      bodyResults.slice(0, 3).forEach(function(n) {
        var excerpt = (n.content || '').slice(0, 600).trim();
        lines.push('■ [' + (n.published_at || '').slice(0, 10) + '] ' + n.title + ' (' + (n.source || '') + ')');
        if (excerpt) lines.push('  → ' + excerpt + (n.content.length > 600 ? '...' : ''));
      });
    }

    // 최근 뉴스 제목 목록 (동향 파악용)
    if (allTitles.length > 0) {
      lines.push('\n[최근 수집 뉴스 목록]');
      allTitles.forEach(function(n) {
        lines.push('  · [' + (n.published_at || '').slice(0, 10) + '] ' + n.title + ' (' + (n.source || '') + ')');
      });
    }

    if (lines.length === 0) return '';
    return '\n\n' + lines.join('\n') +
      '\n(위 뉴스를 참고하여, 질문과 관련된 최신 동향이 있으면 출처와 날짜를 포함해 언급하세요.)';
  } catch(e) {
    console.warn('뉴스 컨텍스트 로드 실패:', e);
    return '';
  }
}
```

그리고 `callClaude()` 함수 내 호출부도 **query를 넘기도록** 수정:

```javascript
// 기존 (line 434)
const newsContext = await fetchRecentNewsContext();

// 변경 후
const newsContext = await fetchRecentNewsContext(userText);
```

---

## FEATURE 3. Q&A 지식 누적 구조

### 3-1. 개념

AI가 좋은 답변을 할 때 "저장" 버튼을 누르면 Supabase `qa_knowledge` 테이블에 Q&A가 저장됩니다.
다음에 비슷한 질문이 들어오면 이 Q&A가 자동으로 시스템 프롬프트에 주입되어
AI가 **과거 검증된 답변 스타일**을 참고해 더 정확하게 답변합니다.

```
사용자 질문 → 키워드로 qa_knowledge 검색 → 유사 Q&A 발견 → 시스템 프롬프트에 주입 → AI 답변
                                                                    ↑
                                              이전 답변 저장 버튼으로 누적
```

---

### 3-2. SQL — qa_knowledge 테이블 생성

Supabase SQL Editor에서 실행:

```sql
CREATE TABLE IF NOT EXISTS qa_knowledge (
  id           BIGSERIAL PRIMARY KEY,
  question     TEXT NOT NULL,           -- 질문 원문
  answer       TEXT NOT NULL,           -- 검증된 답변
  category     TEXT DEFAULT '일반',     -- 주파수 / 전자파 / 적합성평가 / ITU-R / 기술기준 / 일반
  tags         TEXT[] DEFAULT '{}',     -- 검색 키워드 태그 배열
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  used_count   INTEGER DEFAULT 0,       -- 참조된 횟수 (통계용)
  is_active    BOOLEAN DEFAULT TRUE     -- FALSE면 참조에서 제외
);

-- 키워드 검색 인덱스
CREATE INDEX IF NOT EXISTS idx_qa_question ON qa_knowledge USING GIN (to_tsvector('simple', question));
CREATE INDEX IF NOT EXISTS idx_qa_answer   ON qa_knowledge USING GIN (to_tsvector('simple', answer));
CREATE INDEX IF NOT EXISTS idx_qa_category ON qa_knowledge (category);
```

---

### 3-3. app.js — Q&A 검색 및 주입 함수 추가

`buildRagContext()` 함수 **아래에** 추가:

```javascript
// ════════════════════════════════════════════
//  Q&A 지식 베이스 — 누적된 검증 답변 참조
// ════════════════════════════════════════════
async function searchQAKnowledge(query) {
  if (!sb) return '';
  try {
    var keywords = extractKeywords(query);
    if (keywords.length === 0) return '';

    var seen = new Set();
    var results = [];

    for (var ki = 0; ki < Math.min(keywords.length, 3); ki++) {
      var kw = keywords[ki];
      if (kw.length < 2) continue;
      try {
        var resp = await sb
          .from('qa_knowledge')
          .select('question, answer, category, used_count')
          .eq('is_active', true)
          .or('question.ilike.%' + kw + '%,answer.ilike.%' + kw + '%')
          .order('used_count', { ascending: false })
          .limit(3);

        (resp.data || []).forEach(function(row) {
          if (!seen.has(row.question)) {
            seen.add(row.question);
            results.push(row);
          }
        });
      } catch(e) {}
    }

    if (results.length === 0) return '';

    var lines = ['\n\n[팀 검증 Q&A — 유사 질문 참고]'];
    results.slice(0, 3).forEach(function(r, i) {
      lines.push('Q' + (i+1) + ': ' + r.question);
      lines.push('A' + (i+1) + ': ' + r.answer.slice(0, 800) + (r.answer.length > 800 ? '...' : ''));
    });
    lines.push('(위 검증된 Q&A를 참고하여 일관된 답변 기조를 유지하세요.)');
    return lines.join('\n');
  } catch(e) {
    console.warn('Q&A 지식 검색 실패:', e);
    return '';
  }
}

async function saveQAKnowledge(question, answer) {
  if (!sb) throw new Error('Supabase 연결 없음');
  var category = detectCategory(question);
  var keywords = extractKeywords(question);
  await sb.from('qa_knowledge').insert({
    question: question,
    answer: answer,
    category: category,
    tags: keywords
  });
}
```

---

### 3-4. app.js — callClaude()에 Q&A 주입 추가

`callClaude()` 함수 내 시스템 프롬프트 조합 부분을 수정:

```javascript
// 기존 (line 432~435)
const ragContext = buildRagContext(ragChunks);
const newsContext = await fetchRecentNewsContext();
const systemWithRag = SYSTEM_PROMPT + ragContext + newsContext;

// 변경 후
const ragContext = buildRagContext(ragChunks);
const newsContext = await fetchRecentNewsContext(userText);      // ← query 인수 추가
const qaContext = await searchQAKnowledge(userText);             // ← Q&A 주입 추가
const systemWithRag = SYSTEM_PROMPT + ragContext + qaContext + newsContext;
```

---

### 3-5. index.html — AI 답변 저장 버튼 추가

채팅 메시지 렌더링 함수 (`appendMsg`) 내 AI 답변 버블에 저장 버튼 추가:

```javascript
// app.js appendMsg() 함수, role === 'ai' 분기 수정
if (role === 'ai') {
  div.innerHTML =
    `<div class="msg-name">전파정책 전문가 AI</div>` +
    renderMd(text) +
    `<div style="text-align:right;margin-top:8px">
       <button onclick="onSaveQA(this)" data-answer="${encodeURIComponent(text)}"
         style="font-size:11px;padding:3px 10px;border:1px solid #ccc;border-radius:12px;
                background:#f9f9f9;color:#555;cursor:pointer">
         💾 이 답변 저장
       </button>
     </div>`;
}
```

그리고 저장 핸들러 함수 추가:

```javascript
async function onSaveQA(btn) {
  // 저장할 Q: 직전 사용자 메시지
  var lastUserMsg = chatHistory.filter(function(m) { return m.role === 'user'; }).slice(-1)[0];
  if (!lastUserMsg) return alert('저장할 질문을 찾을 수 없습니다.');
  var answer = decodeURIComponent(btn.getAttribute('data-answer'));
  btn.disabled = true;
  btn.textContent = '저장 중...';
  try {
    await saveQAKnowledge(lastUserMsg.content, answer);
    btn.textContent = '✅ 저장됨';
    btn.style.background = '#e8f5e9';
    btn.style.color = '#388e3c';
  } catch(e) {
    btn.textContent = '❌ 저장 실패';
    btn.disabled = false;
    console.error('Q&A 저장 오류:', e);
  }
}
```

---

## 구현 순서 (권장)

| 단계 | 작업 | 소요 시간 |
|---|---|---|
| **Step 1** | Supabase SQL 실행 (컬럼 추가 + 테이블 생성) | 5분 |
| **Step 2** | crawler.py 수정 후 GitHub Push | 10분 |
| **Step 3** | app.js `fetchRecentNewsContext()` 전체 교체 | 10분 |
| **Step 4** | app.js `callClaude()` 3줄 수정 | 2분 |
| **Step 5** | app.js Q&A 함수 2개 추가 + appendMsg 수정 | 10분 |
| **Step 6** | GitHub Push → 테스트 | 5분 |

**"직접 구현해달라"고 하시면 각 파일을 수정해드립니다.**

---

## 완성 후 AI가 참조하는 컨텍스트 구조

```
SYSTEM_PROMPT
  + [법령·고시 RAG]         ← Supabase document_chunks (키워드 매칭, 최대 5청크)
  + [팀 검증 Q&A]           ← qa_knowledge (유사 질문 최대 3건) ★ NEW
  + [질문 관련 최신 기사]    ← news_feed.content (본문 발췌 최대 3건) ★ NEW
  + [최근 뉴스 목록]         ← news_feed 제목 30건
```
