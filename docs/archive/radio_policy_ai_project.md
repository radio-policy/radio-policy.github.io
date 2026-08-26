# 전파정책 전문가 AI 프로젝트

> SK텔레콤 Comm센터 기술정책팀 | 작성일: 2026.05.23

---

## 1. 프로젝트 목표

- **목적**: 팀 업무를 지원하는 전파정책 전문가 AI 구축
- **특성**: 회사 기밀 자료 없이, 공개 법령·고시·ITU-R 문서 기반으로 제3자 입장의 객관적 자문
- **플랫폼**: Claude Projects (지식 베이스) + 웹 대시보드 (UI) + Supabase (DB) + GitHub Pages (배포)

---

## 2. 전체 시스템 아키텍처

```
사용자 브라우저
    │
    ▼
GitHub Pages (정적 HTML/JS)  ←──── GitHub Actions (자동 배포)
    │                                       ▲
    ├──── Claude API ────────────────────────┤
    │     (claude-sonnet-4-6)               │
    │                                  Claude Code
    └──── Supabase 백엔드 ──────────────────┘
          ├── chat_logs       (실시간)
          ├── documents       (실시간)
          ├── news_feed       (실시간)
          ├── changes         (실시간)
          ├── Storage/PDF     (정적)
          ├── settings        (정적)
          └── users           (정적)
```

---

## 3. 지식 베이스 구성

### 3-1. Claude Projects 설정

- **위치**: claude.ai → Projects → New Project
- **파일 업로드**: 개수 무제한, 파일당 최대 30MB
- **컨텍스트**: 200,000 토큰 (초과 시 RAG 자동 전환)

### 3-2. 시스템 프롬프트 (초안)

```
당신은 한국 전파법령 및 ITU-R 권고에 정통한 전파정책 전문가입니다.

[역할]
- 공개된 법령, 고시, 국제 표준에 근거하여 제3자 시각으로 객관적인 자문을 제공합니다.
- SK텔레콤 Comm센터 기술정책팀의 업무를 지원하되, 회사 기밀 자료는 다루지 않습니다.

[답변 방식]
- 근거 조항(전파법 제X조, ITU-R M.XXXX 등)을 반드시 명시합니다.
- 불확실한 사항은 "추가 확인 필요"로 표시합니다.
- 본 자문은 법적 효력이 있는 공식 해석이 아님을 명시합니다.
```

---

## 4. 수집해야 할 문서 목록

### 4-1. 국내 법령 (출처: law.go.kr)

| 문서명 | 종류 | 비고 |
|--------|------|------|
| 전파법 | 법률 | 법률 제20349호, 2024.02.20 시행 |
| 전파법 시행령 | 대통령령 | 제35408호, 2025.04.23 시행 |
| 전파법 시행규칙 | 부령 | 최신 버전 확인 필요 |

### 4-2. 주요 고시 (출처: law.go.kr / rra.go.kr)

| 고시명 | 발령기관 | 비고 |
|--------|----------|------|
| 전기통신사업용 무선설비의 기술기준 | 국립전파연구원 | 2026.04.27 개정예고 중 |
| 방송통신기자재등의 적합성평가에 관한 고시 | 국립전파연구원 | 제2024-12호 |
| 전자파 인체보호기준 | 과기정통부 | - |
| 주파수 분배 및 이용에 관한 고시 | 과기정통부 | 업로드 필요 |
| 간이무선국·우주국 무선설비 기술기준 | 국립전파연구원 | 제2025-4호 |
| 방송통신기자재등 시험기관 지정 및 관리 고시 | 국립전파연구원 | 2026.05.04 개정예고 중 |

### 4-3. ITU-R 문서 (출처: itu.int/rec/R-REC/en)

#### 직접 다운로드 URL 패턴
```
https://www.itu.int/dms_pubrec/itu-r/rec/[시리즈]/R-REC-[문서번호]!!PDF-E.pdf
```

#### 시리즈별 목록 페이지
```
https://www.itu.int/rec/R-REC-[시리즈]/en
```

#### 우선 수집 대상

| 문서번호 | 내용 | 직접 URL |
|----------|------|----------|
| M.2150-2 | 5G(IMT-2020) 무선인터페이스 | `itu.int/rec/R-REC-M.2150/en` |
| M.2160-0 | 6G(IMT-2030) Framework | `itu.int/rec/R-REC-M.2160/en` |
| M.1036 | IMT 주파수 배열 | `itu.int/rec/R-REC-M.1036/en` |
| M.1544 | IMT 최소 성능 요구사항 | `itu.int/rec/R-REC-M.1544/en` |
| SM.329 | 불요발사 허용 기준 | `itu.int/rec/R-REC-SM.329/en` |
| SM.1541 | 대역외 영역 불요발사 | `itu.int/rec/R-REC-SM.1541/en` |

> **TIES 계정**: SKT는 ITU-R 섹터 멤버이므로 회사 내 ITU 담당자(Focal Point)를 통해 TIES 계정 신청 가능 → 회의 작업문서(WD), 기고서(Contribution) 등 비공개 문서 접근 가능

---

## 5. Supabase DB 설계

### 실시간 저장 테이블 (4개)

```sql
-- 자문 이력
CREATE TABLE chat_logs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  category TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 문서 목록
CREATE TABLE documents (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT CHECK (type IN ('법령', '고시', 'ITU-R')),
  version TEXT,
  file_url TEXT,
  status TEXT CHECK (status IN ('최신', '업로드필요', '개정예고')),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 뉴스·보도자료
CREATE TABLE news_feed (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  title TEXT NOT NULL,
  source TEXT,
  category TEXT,
  url TEXT,
  is_read BOOLEAN DEFAULT false,
  published_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 고시 변경 이력
CREATE TABLE changes (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  doc_name TEXT NOT NULL,
  change_type TEXT CHECK (change_type IN ('개정', '폐지', '제정', '예고')),
  description TEXT,
  source_url TEXT,
  detected_at TIMESTAMPTZ DEFAULT now()
);
```

### 정적 저장 (파일 + 설정)

```sql
-- 사용자
CREATE TABLE users (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  name TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 시스템 설정
CREATE TABLE settings (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TIMESTAMPTZ DEFAULT now()
);
-- 예: key='system_prompt', value='당신은 전파정책 전문가입니다...'
-- 예: key='alert_slack_webhook', value='https://hooks.slack.com/...'
```

- **Supabase Storage**: `documents` 버킷에 PDF 파일 저장
- **Row Level Security(RLS)**: 반드시 활성화 → 로그인 사용자만 접근

---

## 6. 프론트엔드 (대시보드)

- **파일**: `index.html` (단일 파일, 다운로드 완료)
- **메뉴 구성**: 대시보드 / AI 자문 / 국내 법령·고시 / ITU-R 문서 / 보도자료·뉴스 / 설정
- **Supabase 연동**: JS 클라이언트 라이브러리 추가 필요

```html
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script>
const supabase = window.supabase.createClient(
  'YOUR_SUPABASE_URL',
  'YOUR_SUPABASE_ANON_KEY'
)
</script>
```

---

## 7. GitHub Pages 배포

### 저장소 구조

```
radio-policy-ai/
├── index.html          ← 대시보드 메인 파일
├── README.md           ← 프로젝트 설명
└── .github/
    └── workflows/
        └── deploy.yml  ← 자동 배포 설정
```

### GitHub Actions 자동 배포 설정

```yaml
# .github/workflows/deploy.yml
name: Deploy to GitHub Pages

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Deploy
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./
```

### 접속 URL
```
https://[GitHub계정명].github.io/radio-policy-ai
```

---

## 8. Claude Code 자동화

### 역할 및 효과

| 작업 | 지금 (수동) | Claude Code 도입 후 |
|------|------------|---------------------|
| 고시 변경 확인 | 매일 사이트 직접 접속 | 매일 오전 8시 자동 크롤링 |
| PDF 다운로드 | 하나씩 수동 다운로드 | 변경 감지 시 자동 저장 |
| DB 업데이트 | 직접 입력 | Supabase 자동 INSERT |
| 팀 알림 | 이메일 수동 발송 | Slack 자동 발송 |
| 기능 추가 | 개발자 요청 | 자연어 명령 한 마디 |
| 사이트 배포 | 수동 push | 코드 변경 시 자동 배포 |

### 하루 자동화 타임라인

```
08:00  ── Claude Code 자동 크롤링 시작 (rra.go.kr, 과기정통부, 전자신문)
08:05  ── 변경 감지 → Supabase DB 자동 저장
08:10  ── Slack 알림 발송 (팀원 전체)
08:12  ── 신규 PDF 자동 다운로드 → Storage 저장
08:15  ── GitHub 자동 commit + push → Pages 갱신
08:20  ── 완료 (팀원은 Slack 확인만 하면 끝)
```

### 자동화 스크립트 실행 방법 (Claude Code)

```bash
# 터미널에서 자연어로 명령
claude "매일 오전 8시에 rra.go.kr을 크롤링해서 새 고시를 감지하고 
        Supabase의 news_feed 테이블에 저장한 뒤 Slack으로 알림 보내는 
        Python 스크립트 만들어줘"
```

---

## 9. 진행 단계 체크리스트

### Phase 1 — 지식 베이스 구축
- [ ] law.go.kr에서 전파법·시행령·시행규칙 PDF 다운로드
- [ ] rra.go.kr에서 주요 고시 6개 PDF 다운로드
- [ ] itu.int에서 M·SM 시리즈 핵심 문서 PDF 다운로드
- [ ] Claude Projects 생성 및 문서 업로드
- [ ] 시스템 프롬프트 작성 및 테스트

### Phase 2 — Supabase 백엔드
- [ ] Supabase 프로젝트 생성 (supabase.com)
- [ ] 위 SQL로 4개 테이블 생성
- [ ] Storage 버킷(`documents`) 생성
- [ ] RLS 정책 설정
- [ ] API Key 확인 (anon key, service role key)

### Phase 3 — 프론트엔드 연동
- [ ] `index.html`에 Supabase 클라이언트 연결
- [ ] Claude API 연동 (자문 기능)
- [ ] 각 메뉴 실제 데이터 연결 (mock → 실제)
- [ ] 로그인 기능 (Supabase Auth)

### Phase 4 — GitHub 배포
- [ ] GitHub 저장소 생성 (`radio-policy-ai`)
- [ ] `index.html` push
- [ ] Pages 설정 (Settings → Pages → main 브랜치)
- [ ] GitHub Actions 자동 배포 설정
- [ ] 접속 URL 팀원 공유

### Phase 5 — Claude Code 자동화
- [ ] Claude Code 설치 (`npm install -g @anthropic-ai/claude-code`)
- [ ] 크롤링 스크립트 생성 (자연어 명령)
- [ ] GitHub Actions 스케줄 등록 (cron: `0 8 * * *`)
- [ ] Slack Webhook 설정
- [ ] 전체 파이프라인 테스트

---

## 10. 참고 링크

| 용도 | URL |
|------|-----|
| 국가법령정보센터 | https://www.law.go.kr |
| 국립전파연구원 | https://www.rra.go.kr |
| 과기정통부 | https://www.msit.go.kr |
| ITU-R 권고 목록 | https://www.itu.int/rec/R-REC/en |
| Supabase | https://supabase.com |
| GitHub Pages | https://pages.github.com |
| Claude Code 문서 | https://docs.anthropic.com/claude-code |
| 스펙트럼포털 | https://www.spectrum.or.kr |

---

*본 문서는 Claude와의 대화를 바탕으로 작성된 프로젝트 기획서입니다.*
*다음 세션에서 이 파일을 Claude Project에 업로드하면 이전 맥락을 이어서 진행할 수 있습니다.*
