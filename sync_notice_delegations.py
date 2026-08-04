#!/usr/bin/env python3
"""
고시·훈령·예규 본문에서 **위임 근거를 역추출** → law_delegations 적재 (AI 미사용, 정규식만)

무엇을 푸는가
--------------
`sync_law_delegations.py`(법제처 3단비교)는 이름 그대로 **법률-시행령-시행규칙 3단**이라
**고시·훈령은 범위 밖**이다. 그런데 이 KB에서 가장 많은 게 고시다(고시 113 / 훈령·예규 14 /
시행령 24 / 법률 23 / 시행규칙 9). 그 결과 관계도에서 notice 노드 220개 중 위임 엣지를 가진
것이 단 2개(0.9%)뿐이라 고시가 사실상 떠 있었다.

다행히 **고시 본문 제1조(목적)에 근거가 규칙적으로 박혀 있다.**
  "이 고시는 「전파법」 제25조제2항 및 같은 법 시행령 제50조제2항에 따라 …"
  "이 기준은「전기통신사업법」제56조의2제2항에 따라 …"
  "이 고시는 「방송통신설비의 기술기준에 관한 규정」 제14조제2항의 규정에 의하여 …"
이걸 파싱해 `law_delegations`에 넣으면 3단비교가 못 덮는 행정규칙 계층이 이어진다.

추출 규칙 (신뢰도 순 / 확정 못 하면 버린다)
------------------------------------------------
① `「법령명」 제N조[의M]` — 법령명이 명시된 형태. **가장 신뢰도 높음.**
② 괄호 없는 명시 형태 `전파법 제71조`, `전파법시행령 제99조` — 단, **KB에 실재하는 법령명**과
   일치할 때만 인정한다(임의 문자열을 법령명으로 넘겨짚지 않기 위함).
③ `같은 법 / 같은 법 시행령 / 동법 시행령` — 직전 법령 앵커에서 유도.
④ `법 제N조` / `영 제N조` / `시행령 제N조` — **법령명이 생략된 형태**. 이건 무엇을 가리키는지
   확정해야 쓴다. 확정 경로는 두 가지뿐이다.
     (a) 같은 조문에 약칭 정의가 있음:  「전파법」(이하 "법"이라 한다) … 법 제45조
     (b) 근거 문맥에 등장하는 **법률급 법령명이 정확히 하나**일 때 그것으로 유도
   둘 다 안 되면 **버린다.**

⚠️ **틀린 연결은 없는 것보다 나쁘다.** 이 표는 `/law`·관계도가 "이 고시의 근거 법률"이라고
   단정해 보여주는 자리다. 근거가 애매하면 행을 만들지 않는 쪽이 항상 옳다. 그래서
   - 법령명을 확정 못 한 `법 제N조`/`영 제N조` → 버림
   - 「」 안이 법령 어미(법·법률·시행령·규칙·규정·고시·기준·세칙·분배표·협정)로 끝나지 않으면 → 버림
   - `부칙 제4조` 인용 → 버림(부칙은 위임 근거가 아니다)
   - 제1조(목적)에서 **위임 표지**("…에 따라/에 의하여/에서 정하는 바에 따라/…위임한") **앞부분**만
     본다. 표지 뒤는 근거가 아니라 규율 대상 서술이라 인용이 섞여 있어도 근거가 아니다.

조문 단위 대응이 아니라 **문서 단위 연결**이다 — child_article = '전체'
------------------------------------------------------------------------
3단비교는 "법률 제34조 ↔ 시행령 제40조"처럼 조문 대 조문이 맞물리지만, 고시 제1조(목적)의
근거는 **고시 전체의 수권 근거**일 뿐 고시 조문별 매핑 정보가 아니다. 그래서
`child_article`에 그 고시의 `1조`를 넣으면 "상위 법 제25조가 이 고시 제1조에 위임했다"는
**없는 사실**이 만들어진다. 문서 단위임이 드러나도록 **`child_article = '전체'`** 고정값을 쓴다.
(이 값은 재적재 시 삭제 범위의 안전한 경계 역할도 한다 — 3단비교가 넣은 행은 child_article이
 항상 `N조` 형태라 '전체'와 절대 겹치지 않는다.)

법령명 정규화
--------------
`sync_law_delegations.py`와 같은 원칙: **저장 값은 DB(document_chunks.doc_name) 표기를 따른다.**
조인 상대가 DB이기 때문이다(`doc_name LIKE parent_law || '(%'`).
- 가운뎃점은 **대조(lookup)할 때만** ㆍ→· 로 통일한다. 본문이 `표시·광고`, DB가 `표시ㆍ광고`처럼
  엇갈리는 경우가 있어서다. 저장은 매칭된 **DB 정본 표기(ㆍ 유지)** 를 쓴다.
  → 형제 스크립트가 "가운뎃점 정규화를 안 했다"고 한 것과 어긋나지 않는다. 그쪽은 API 표기와
    DB 표기가 이미 같아서 변환이 필요 없었고, 이쪽은 사람이 쓴 본문이라 표기가 흔들린다.
- 공백도 대조할 때만 무시한다(`방송통신발전 기본법` = 본문의 `방송통신발전기본법`).
- 약칭(정보통신망법 등)은 `supabase/functions/telegram-webhook/index.ts`의 `LAW_ALIASES`를
  옮겨 왔다. **원본은 그 파일이다** — 거기서 약칭이 늘면 여기도 같이 늘려야 한다.

실행 (PC, Python 3.12 전체 경로 / 수동 실행 시 프록시 제거 필수)
------------------------------------------------------------------
  $env:HTTP_PROXY=''; $env:HTTPS_PROXY=''
  C:\\Users\\SKTelecom\\AppData\\Local\\Programs\\Python\\Python312\\python.exe sync_notice_delegations.py --dry-run
  ... sync_notice_delegations.py --only "무선설비의 접속사용 범위"
  ... sync_notice_delegations.py                    # 전체 재적재(멱등)
네트워크 호출은 Supabase 뿐 — **AI·외부 API를 쓰지 않으므로 실행 비용 0.**
"""

import os
import re
import sys
import argparse
from datetime import datetime, timezone

# Windows 스케줄러가 출력을 cp949로 캡처해 이모지 print가 UnicodeEncodeError로 죽는 문제 (배경역사 #19)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from sb_client import make_client

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
sb = make_client(SUPABASE_URL, SUPABASE_KEY)

TABLE = 'law_delegations'
CONFLICT_COLS = 'parent_law,parent_article,child_law,child_article'
UPSERT_BATCH = 200
DOC_ARTICLE = '전체'      # child_article 고정값 — 문서 단위 연결(docstring 참조)

# ── 수기 확정 위임 근거 (2026-08-04, #82) ─────────────────────────────────────
#  정규식은 고시 **제1조에 박힌** 위임 문구만 뽑는다. 그런데 제1조가 아예 없거나(협정문·분배표·
#  공고), 제1조에 근거를 안 쓰는 문서가 31건 있었고 그만큼 관계도에서 고립돼 있었다.
#  이 표는 그중 **상위 법령 조문에서 역방향으로 확인된 것만** 담는다 — 상위 조문이
#  "…을 정하여 고시한다" 형태로 이 문서를 직접 지목하는 경우다(예: 전기통신사업법 제62조제2항이
#  「중요한 전기통신설비」를 지목). 조사 결과 확정 15 / 추정 12 / 없음 4 중 **확정만** 채택했다.
#  · 추정(포괄 위임 "법·영에서 위임한 사항"류)은 넣지 않는다 — 조문을 특정할 수 없어
#    잘못된 조문에 엣지가 걸리면 없는 관계보다 나쁘다.
#  · 「무선통신보조설비의 화재안전기술기준(NFTC 505)」은 근거가 확정(소방시설법 제2조)이나
#    상위 법령이 이 KB에 없어 제외했다. 소방시설법을 적재하면 되살릴 것.
#  · 「이용약관 인가대상 기간통신서비스와 기간통신사업자」는 2020년 유보신고제 전환으로
#    전기통신사업법에 '이용약관 인가' 조문이 사라졌는데 고시는 인가 문언을 유지하고 있다.
#    조문 대응이 불명이라 **의도적으로 비워 둔다** — 운영자 확인 대상.
#  정규식이 근거를 뽑아내면 그쪽이 이긴다(아래 적용부 참조). 원문이 개정돼 제1조에 근거가
#  생기면 이 표는 자동으로 비켜선다.
MANUAL_BASIS = {
    '기만적인 표시·광고 심사지침':
        [('표시ㆍ광고의 공정화에 관한 법률', '3조')],
    '긴급구조를 위한 소방기관의 위치정보 이용ㆍ관리 지침':
        [('위치정보의 보호 및 이용 등에 관한 법률', '29조')],
    '대한민국 과학기술정보통신부와 인도네시아 통신디지털부 (舊 통신정보부) 간의 방송통신기자재등의 적합성평가에 대한 상호인정협정':
        [('전파법', '58조의8')],
    '대한민국 방송통신위원회와 베트남 정보통신부간의 방송통신기자재등에 대한 상호인정협정':
        [('전파법', '58조의8')],
    '대한민국 주파수 분배표':
        [('전파법', '9조')],
    '전기안전 및 전자파적합성 시험·인증 통합 처리지침':
        [('전파법', '58조의2')],
    '전기통신사업 회계분리기준':
        [('전기통신사업 회계정리 및 보고에 관한 규정', '17조')],
    '전기통신설비 의무제공대상 기간통신사업자':
        [('전기통신사업법 시행령', '39조')],
    '전기통신설비의 상호접속ㆍ공동사용 및 정보제공 협정의 인가대상 기간통신사업자':
        [('전기통신사업법 시행령', '39조')],
    '전력선통신설비가 다른 통신에 방해를 주지 아니하도록 그 운용을 금지하는 주파수대역':
        [('전파법', '58조')],
    '주요정보통신기반시설 취약점 분석ㆍ평가 기준':
        [('정보통신기반 보호법', '9조')],
    '중요한 전기통신설비':
        [('전기통신사업법', '62조')],
    '특별재난지역 전파사용료 감면대상 무선국 기준':
        [('전파법', '67조')],
    '한국방송통신전파진흥원이 검사업무를 하는 무선국':
        [('전파법 시행령', '123조')],
}

# 대상: 문서명 법종 괄호가 이 어미로 끝나는 것 (실측 표기: (국립전파연구원고시)/(과학기술정보통신부훈령)/(공정거래위원회예규))
TARGET_KINDS = ('고시', '훈령', '예규', '지침', '공고')

# 문서명 법종 괄호 (build_law_citation_graph.TYPE_PAREN_RE 와 같은 규칙 + '지침' 추가)
TYPE_PAREN_RE = re.compile(
    r'\(([^()]*?(법률|대통령령|총리령|부령|고시|훈령|공고|예규|지침|위원회규칙|연구원규칙))\)')

# 인용 대상으로 인정하는 명칭 어미 (「」 안의 비법령 문구 걸러냄 — 예: 「마을 간이무선국」)
CITABLE_SUFFIX_RE = re.compile(r'(법|법률|시행령|시행규칙|규칙|규정|고시|기준|세칙|분배표|협정)$')

# ── 약칭 표 ──────────────────────────────────────────────────
# 원본은 supabase/functions/telegram-webhook/index.ts 의 LAW_ALIASES (2026-08-03 기준 사본).
# 그 파일이 정본이므로, 약칭이 추가되면 여기도 같이 갱신할 것.
LAW_ALIASES = {
    '정보통신망법': '정보통신망 이용촉진 및 정보보호 등에 관한 법률',
    '망법': '정보통신망 이용촉진 및 정보보호 등에 관한 법률',
    '전기통신법': '전기통신사업법',
    '개인정보보호법': '개인정보 보호법',
    '위치정보법': '위치정보의 보호 및 이용 등에 관한 법률',
    '단통법': '이동통신단말장치 유통구조 개선에 관한 법률',
    '단말기유통법': '이동통신단말장치 유통구조 개선에 관한 법률',
    '방발법': '방송통신발전 기본법',
    '방송통신발전법': '방송통신발전 기본법',
    '정보통신기반보호법': '정보통신기반 보호법',
    '통비법': '통신비밀보호법',
    '방통위설치법': '방송통신위원회의 설치 및 운영에 관한 법률',
    '방통위법': '방송통신위원회의 설치 및 운영에 관한 법률',
    'ICT특별법': '정보통신 진흥 및 융합 활성화 등에 관한 특별법',
    '정보통신융합법': '정보통신 진흥 및 융합 활성화 등에 관한 특별법',
    '지능정보화법': '지능정보화 기본법',
    'IPTV법': '인터넷 멀티미디어 방송사업법',
    '클라우드법': '클라우드컴퓨팅 발전 및 이용자 보호에 관한 법률',
}

# ── 위임 표지: 여기까지가 "근거", 그 뒤는 규율 대상 서술 ──────────────
# 가장 왼쪽에서 끝나는 표지까지만 남긴다. 대안 순서 중요 — 같은 위치에서 시작하면 앞 대안이 이긴다
# (예: "에서 정하는 바에 따라"가 "에서 정하는"보다 먼저 와야 문장이 덜 잘린다).
CUT_RE = re.compile(
    r'에서\s*정하는\s*바에\s*따라'
    r'|에서\s*정한\s*바에\s*따라'
    r'|의?\s*규정에\s*(?:따라|따른|의하여|의한)'
    r'|에서\s*정하는\s*바에\s*의하여'
    r'|에서\s*[^,·ㆍ]{0,25}?위임한'
    r'|에\s*따라'
    r'|에\s*따른'
    r'|에\s*의하여'
    r'|에\s*의한'
    r'|에\s*근거하여'
    r'|에서\s*정하는'
    r'|에서\s*정한'
    r'|에서\s*규정'
)
CUT_FALLBACK_CHARS = 400   # 표지를 못 찾으면 앞 400자만 (긴 목적 조문의 뒤쪽 잡음 차단)

# 목적 조문의 시작 문구. 제1조 청크가 없는 문서(조문 분해가 안 된 고시·공고)에서는
# **이 문구가 없으면 근거 추출을 포기한다.** 첫 청크가 목적 조문이라는 보장이 없기 때문이다.
# (실측 오답: 「특별재난지역 전파사용료 감면대상 무선국 기준」의 첫 청크는 "1. 감면대상 무선국 : …
#  「전기통신사업법」제5조제2항의 규정에 따라 …"라는 **적용 제외 서술**이라, 이걸 근거로 읽으면
#  고시가 전기통신사업법 제5조의 위임을 받았다는 거짓 연결이 생긴다.)
PURPOSE_OPENER_RE = re.compile(
    r'이\s*(?:고시|기준|규정|지침|훈령|예규|요령|세칙|시험방법|방법|규칙|기술기준|공고|협정|절차|요령)\s*[은는]')

# 약칭 정의: (이하 "법"이라 한다) / (이하 ‘영’이라 한다)
ALIAS_DEF_RE = re.compile(
    r'이하\s*[\'"‘’“”]?\s*([가-힣A-Za-z]{1,10})\s*[\'"‘’“”]?\s*(?:이라|라)\s*한다')


def mid_dot(s: str) -> str:
    """가운뎃점 이형 통일 — **대조용 키에만** 쓴다(저장 값은 DB 정본 표기 유지)."""
    return (s or '').replace('ㆍ', '·').replace('‧', '·').replace('•', '·')


def lookup_key(s: str) -> str:
    """법령명 대조 키: 가운뎃점 통일 + 공백 전부 제거."""
    return re.sub(r'\s+', '', mid_dot(s or ''))


def clean_name(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '')).strip()


def parse_doc_name(doc_name: str):
    """doc_name → (base_name, kind_token) 또는 None(법령·행정규칙 원문 아님).
    build_law_citation_graph.parse_doc_name과 같은 전처리(선두 부처 괄호·[별첨] 제거)."""
    name = re.sub(r'\.(pdf|md)$', '', clean_name(doc_name))
    m = TYPE_PAREN_RE.search(name)
    if not m:
        return None
    base = name[:m.start()].strip()
    base = re.sub(r'^\([^)]*\)\s*', '', base).strip()     # 선두 소관부처 괄호
    base = re.sub(r'^\[[^\]]*\]\s*', '', base).strip()    # 선두 [별첨 N]
    if len(base) < 2:
        return None
    return base, m.group(2)


# ── DB 조회 ────────────────────────────────────────────────

def fetch_doc_index():
    """status='current' & is_approved 문서의 base_name → {'kind':…, 'docs':[doc_name…]}

    ⚠️ .order('id') 필수 — 정렬 없는 range() 페이지네이션은 페이지마다 순서가 달라져
       문서가 통째로 누락된다(build_law_citation_graph.fetch_all_doc_rows와 같은 이유)."""
    index = {}
    page, offset = 1000, 0
    while True:
        r = (sb.table('document_chunks')
             .select('doc_name')
             .eq('status', 'current')
             .eq('is_approved', True)
             .order('id')
             .range(offset, offset + page - 1)
             .execute())
        rows = r.data or []
        for row in rows:
            dn = row.get('doc_name') or ''
            parsed = parse_doc_name(dn)
            if not parsed:
                continue
            base, kind = parsed
            e = index.setdefault(base, {'kind': kind, 'docs': set()})
            e['docs'].add(dn)
        if len(rows) < page:
            break
        offset += page
    for e in index.values():
        e['docs'] = sorted(e['docs'])
    return index


def fetch_first_articles(doc_names):
    """대상 문서들의 **제1조 본조** 청크(article_no가 '1조…', '1조의N'은 제외).
    반환: doc_name → 본문(여러 청크면 이어붙임)"""
    out = {}
    names = list(doc_names)
    for i in range(0, len(names), 50):          # in_ 필터 URL 길이 제한
        batch = names[i:i + 50]
        offset = 0
        while True:
            r = (sb.table('document_chunks')
                 .select('doc_name, article_no, content')
                 .in_('doc_name', batch)
                 .eq('status', 'current')
                 .eq('is_approved', True)
                 .like('article_no', '1조%')
                 .order('id')
                 .range(offset, offset + 999)
                 .execute())
            rows = r.data or []
            for row in rows:
                art = row.get('article_no') or ''
                if not re.match(r'^1조(\(|$)', art):     # '1조의2'는 목적 조문이 아니다
                    continue
                out[row['doc_name']] = (out.get(row['doc_name'], '') + ' ' + (row.get('content') or '')).strip()
            if len(rows) < 1000:
                break
            offset += 1000
    return out


def fetch_head_chunk(doc_name: str) -> str:
    """제1조 청크가 없는 문서(조문 분해가 안 된 PDF 등)의 폴백 — 첫 청크 앞부분."""
    r = (sb.table('document_chunks')
         .select('content')
         .eq('doc_name', doc_name)
         .eq('status', 'current')
         .eq('is_approved', True)
         .order('id')
         .limit(1)
         .execute())
    rows = r.data or []
    return (rows[0].get('content') or '') if rows else ''


# ── 근거 문맥 추출 ────────────────────────────────────────────

def basis_context(text: str, strict: bool = False) -> str:
    """제1조(목적) 본문 → **위임 표지까지의 근거 부분**만.
    표지 뒤는 규율 대상 서술이라 「」 인용이 있어도 근거가 아니다(docstring 참조).
    strict=True(제1조 청크가 없는 폴백 경로)면 목적 조문 시작 문구가 없을 때 빈 문자열을 돌려준다."""
    t = clean_name(text)
    # 청크 선두의 조문 머리 '제1조(목적)' 제거 — 안 지우면 그 '제1조'가 상위 조문으로 오인된다
    t = re.sub(r'^제\s*\d+\s*조(?:\s*의\s*\d+)?\s*(\([^)]*\))?\s*', '', t)
    # 「「방송통신발전 기본법」 시행령」 처럼 중첩된 괄호 표기를 평탄화
    t = re.sub(r'「「([^」]+)」\s*(시행령|시행규칙)」', r'「\1 \2」', t)
    # 'Ⅰ. 목 적이 고시는 …'처럼 머리말이 붙은 경우 목적 문장부터 시작
    op = PURPOSE_OPENER_RE.search(t[:CUT_FALLBACK_CHARS])
    if op:
        t = t[op.start():]
    elif strict:
        return ''
    m = CUT_RE.search(t)
    return t[:m.end()] if m else t[:CUT_FALLBACK_CHARS]


class NameResolver:
    """본문 법령명 → DB 정본 base_name. 못 맞추면 (원문표기, resolved=False)."""

    def __init__(self, doc_index):
        self.canon = {}          # lookup_key → DB base_name
        for base in doc_index:
            self.canon.setdefault(lookup_key(base), base)
        self.alias = {lookup_key(k): v for k, v in LAW_ALIASES.items()}
        # 괄호 없는 명시 형태(②)를 인정할 후보 = KB에 실재하는 법령명뿐.
        # 긴 이름 우선(‘전파법 시행령’이 ‘전파법’보다 먼저 매칭돼야 한다).
        pats = []
        for base in sorted(doc_index, key=lambda s: -len(s)):
            pats.append(r'\s*'.join(re.escape(tok) for tok in mid_dot(base).split()))
        self.known_alt = '(?:' + '|'.join(pats) + ')' if pats else r'(?!x)x'

    def resolve(self, raw: str):
        """→ (name, resolved). resolved=True면 DB 문서와 조인 가능한 정본 표기."""
        name = clean_name(raw).strip('「」 ')
        name = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()     # 꼬리 (이하 …) 제거
        if len(name) < 2:
            return None, False
        key = lookup_key(name)
        if key in self.canon:
            return self.canon[key], True
        official = self.alias.get(key)
        if official:
            k2 = lookup_key(official)
            if k2 in self.canon:
                return self.canon[k2], True
            return official, False
        # KB에 없는 법령 — 본문에 명시돼 있으니 사실로는 옳다. 다만 법령 어미 검사는 통과해야 한다.
        if CITABLE_SUFFIX_RE.search(mid_dot(name)):
            return name, False
        return None, False


def make_token_re(known_alt: str):
    """근거 문맥 스캐너. 대안 순서 = 우선순위(같은 위치면 앞 대안이 이긴다)."""
    return re.compile(
        r'(?P<br>「[^」]{2,60}」)'
        r'|(?P<hide>\([^()]{0,80}?이하[^()]{0,80}?\))'
        r'|(?P<same>같은\s*법\s*시행규칙|같은\s*법\s*시행령|같은\s*법|동\s*법\s*시행규칙'
        r'|동\s*법\s*시행령|동법시행령|동\s*법)'
        r'|(?<![가-힣])(?P<known>' + known_alt + r')'
        r'(?=\s*(?:\([^()]{0,60}\)\s*)?제\s*\d+\s*조)'
        # 뒤에 (이하 "…"라 한다)가 끼어도 앵커로 인정 — 「약관의 규제에 관한 법률」(이하 "법"이라 한다)
        # **시행령**(이하 "시행령"이라 한다) 제13조 처럼 약칭 정의가 사이에 들어오는 실측 사례가 있다.
        r'|(?<![가-힣])(?P<abbr>시행규칙|시행령|법률|규정|규칙|기준|고시|법|영)'
        r'(?=\s*(?:\([^()]{0,80}\)\s*)?제\s*\d+\s*조)'
        # 조가지번호: '제15조의12'가 정상. 원문 오타로 '의'가 빠진 '제15조12'도 같이 받는다
        # (공백 없이 숫자가 바로 붙는 경우만 — 그러지 않으면 '제15조'로 읽혀 없는 근거가 생긴다.
        #  실측: 클라우드컴퓨팅서비스 보안인증 고시의 "제15조의6부터 제15조12까지").
        r'|(?P<art>제\s*(?P<n>\d+)\s*조(?:\s*의\s*(?P<g>\d+)|(?P<g2>\d+))?)'
    )


def strip_sub(name: str) -> str:
    """'전파법 시행령' → '전파법' (같은 법/동법이 가리키는 법률급 이름)"""
    return re.sub(r'\s*시행(령|규칙)$', '', name).strip()


def extract_basis(ctx: str, resolver: NameResolver, token_re):
    """근거 문맥 → [(parent_name, parent_article, resolved)] + 버린 사유 목록"""
    # 1차 스캔: 이 문맥에 등장하는 **법률급 명시 법령명**이 정확히 하나인지 확인(④(b) 유도용)
    law_level = []
    for m in re.finditer(r'「([^」]{2,60})」', ctx):
        nm, _ = resolver.resolve(m.group(1))
        if nm and not re.search(r'시행(령|규칙)$', nm):
            if nm not in law_level:
                law_level.append(nm)
    implicit_law = law_level[0] if len(law_level) == 1 else None

    aliases = {}          # '법' → 법령명
    current = None        # 직전 법령 앵커
    last_law = None       # 직전 **법률급** 앵커(같은 법/동법 해석용)
    found, dropped = [], []

    for m in token_re.finditer(ctx):
        if m.group('br'):
            nm, _ok = resolver.resolve(m.group('br'))
            if nm:
                current = nm
                if not re.search(r'시행(령|규칙)$', nm):
                    last_law = nm
            else:
                current = None
                dropped.append(f'「{clean_name(m.group("br"))[:20]}」(법령 어미 아님)')
            continue
        if m.group('hide'):
            a = ALIAS_DEF_RE.search(m.group('hide'))
            if a and current:
                aliases[a.group(1)] = current
            continue
        if m.group('same'):
            tok = re.sub(r'\s+', '', m.group('same'))
            base = last_law or (strip_sub(current) if current else None)
            if not base:
                current = None
                continue
            if tok.endswith('시행령'):
                current = base + ' 시행령'
            elif tok.endswith('시행규칙'):
                current = base + ' 시행규칙'
            else:
                current = base
            continue
        if m.group('known'):
            nm, ok = resolver.resolve(m.group('known'))
            if nm:
                current = nm
                if not re.search(r'시행(령|규칙)$', nm):
                    last_law = nm
            continue
        if m.group('abbr'):
            tok = m.group('abbr')
            target = aliases.get(tok)
            if not target and tok in ('법', '법률'):
                target = implicit_law
            if not target and tok in ('영', '시행령'):
                base = strip_sub(aliases.get('법') or implicit_law or last_law or '')
                target = (base + ' 시행령') if base else None
            if not target and tok == '시행규칙':
                base = strip_sub(aliases.get('법') or implicit_law or last_law or '')
                target = (base + ' 시행규칙') if base else None
            if not target:
                # ④ 확정 실패 — **버린다**. 틀린 연결은 없는 것보다 나쁘다.
                dropped.append(f'"{tok} 제N조"(가리키는 법령 미확정)')
                current = None
                continue
            nm, _ = resolver.resolve(target)
            current = nm or target
            continue
        if m.group('art'):
            if not current:
                dropped.append(f'{clean_name(m.group("art"))}(앞선 법령명 없음)')
                continue
            if '부칙' in ctx[max(0, m.start() - 6):m.start()]:
                dropped.append(f'부칙 {clean_name(m.group("art"))}')
                continue
            art = f'{int(m.group("n"))}조'
            gaji = m.group('g') or m.group('g2')
            if gaji:
                art += f'의{int(gaji)}'
            _, ok = resolver.resolve(current)
            pair = (current, art, ok)
            if pair not in found:
                found.append(pair)
    return found, dropped


# ── 적재 ──────────────────────────────────────────────────

def upsert_rows(rows):
    for i in range(0, len(rows), UPSERT_BATCH):
        (sb.table(TABLE)
         .upsert(rows[i:i + UPSERT_BATCH], on_conflict=CONFLICT_COLS)
         .execute())


def prune_stale(child_law: str, synced_at: str) -> int:
    """이 고시의 이전 실행분 중 이번에 갱신되지 않은 행 삭제.
    범위를 `child_article='전체'`로 못 박아 3단비교가 넣은 조문 단위 행(항상 'N조')은 건드리지 않는다.
    ⚠️ 반드시 upsert 성공 후에만 호출 — 선삭제 후 적재 실패는 공백 사고다(배경역사 #65)."""
    r = (sb.table(TABLE).delete()
         .eq('child_law', child_law)
         .eq('child_article', DOC_ARTICLE)
         .lt('synced_at', synced_at)
         .execute())
    return len(r.data or [])


def main():
    ap = argparse.ArgumentParser(
        description='고시·훈령·예규 본문의 위임 근거 역추출 → law_delegations 적재(AI 미사용)')
    ap.add_argument('--dry-run', action='store_true', help='DB 무변경. 추출 표본·건수만 출력')
    ap.add_argument('--only', metavar='고시명', help='해당 고시(부분일치) 하나만 처리')
    ap.add_argument('--sample', type=int, default=20, help='dry-run 표본 출력 건수(기본 20)')
    args = ap.parse_args()

    synced_at = datetime.now(timezone.utc).isoformat()
    print('=== 고시 위임 근거 역추출 ===' + ('  [DRY-RUN — DB 무변경]' if args.dry_run else ''))

    doc_index = fetch_doc_index()
    print(f'승인·현행 문서(정규화 base 기준): {len(doc_index)}건')

    targets = {b: e for b, e in doc_index.items() if e['kind'].endswith(TARGET_KINDS)}
    if args.only:
        key = lookup_key(args.only)
        targets = {b: e for b, e in targets.items() if key in lookup_key(b)}
    print(f'대상 고시·훈령·예규: {len(targets)}건')
    if not targets:
        print('대상 없음 — 종료')
        return 0

    resolver = NameResolver(doc_index)
    token_re = make_token_re(resolver.known_alt)

    # 제1조 본문 일괄 조회 (대표 문서명 = 문서명 사전순 최대 = 시행일 최신)
    rep_doc = {b: e['docs'][-1] for b, e in targets.items()}
    first_arts = fetch_first_articles(rep_doc.values())

    rows_by_child = {}
    no_basis, fallback_used, dropped_all, manual_used = [], [], [], []
    for base in sorted(targets):
        dn = rep_doc[base]
        text = first_arts.get(dn) or ''
        strict = False
        if not text:
            # 제1조 청크가 없는 문서 — 첫 청크로 폴백하되 목적 조문 확인을 강제한다(strict)
            text = fetch_head_chunk(dn)
            strict = True
            if text:
                fallback_used.append(base)
        ctx, found, why = '', [], ''
        if not text:
            why = '본문 없음'
        else:
            ctx = basis_context(text, strict=strict)
            if not ctx:
                why = '제1조 없음·목적 문구 미확인(폴백 포기)'
            else:
                found, dropped = extract_basis(ctx, resolver, token_re)
                for d in dropped:
                    dropped_all.append((base, d))
                if not found:
                    why = '근거 문구 없음'
        # 정규식이 실패했을 때만 수기 확정표를 쓴다 — 원문이 개정돼 제1조에 근거가 생기면
        # 위 추출이 이기고 이 표는 자동으로 비켜선다(수기 값이 원문을 가리지 않게).
        if not found and base in MANUAL_BASIS:
            found = [(pname, part, True) for pname, part in MANUAL_BASIS[base]]
            ctx = ctx or '(수기 확정 — MANUAL_BASIS, 상위 조문 역방향 확인)'
            manual_used.append(base)
            why = ''
        if not found:
            no_basis.append((base, why))
            continue
        kind = targets[base]['kind']
        kind_tok = next((k for k in TARGET_KINDS if kind.endswith(k)), '고시')
        seen = set()
        out = []
        for pname, part, ok in found:
            k = (pname, part)
            if k in seen:
                continue      # ⚠️ 한 payload 안에 conflict 키 중복이 있으면 upsert가 **전체** 실패한다
            seen.add(k)
            out.append({
                'parent_law': pname,
                'parent_article': part,
                'parent_title': None,     # 상위 조문 제목은 document_chunks.article_no가 정본이라 중복 저장 안 함
                'child_law': base,
                'child_article': DOC_ARTICLE,
                'child_title': None,
                'child_kind': kind_tok,
                'synced_at': synced_at,
                '_resolved': ok,
                '_ctx': ctx,
            })
        rows_by_child[base] = out

    total = sum(len(v) for v in rows_by_child.values())
    resolved = sum(1 for v in rows_by_child.values() for r in v if r['_resolved'])
    print(f'근거 추출: {len(rows_by_child)}개 문서 / {total}행'
          f' (상위 법령 DB 조인 가능 {resolved}행, {resolved * 100 // max(total, 1)}%)')
    if fallback_used:
        print(f'  · 제1조 청크 없어 첫 청크 폴백: {len(fallback_used)}건')

    # ── 상위 법령별 분포 ──
    dist = {}
    for v in rows_by_child.values():
        for r in v:
            dist[r['parent_law']] = dist.get(r['parent_law'], 0) + 1
    print('  ── 상위 법령별 분포(상위 15) ──')
    for nm, c in sorted(dist.items(), key=lambda x: (-x[1], x[0]))[:15]:
        mark = '' if lookup_key(nm) in resolver.canon else '  [KB 미보유]'
        print(f'    {c:4d}  {nm}{mark}')

    if args.dry_run:
        print(f'\n  ── 추출 표본 {args.sample}건 (고시명 → 상위 법령·조문) ──')
        for base in sorted(rows_by_child)[:args.sample]:
            arts = ', '.join(f'{r["parent_law"]} 제{r["parent_article"]}' for r in rows_by_child[base])
            print(f'    · {base}\n        → {arts}')
        if manual_used:
            print(f'\n  ── 수기 확정표 적용 {len(manual_used)}건 (MANUAL_BASIS) ──')
            for b in manual_used:
                print(f'    · {b}')
        if no_basis:
            print(f'\n  ── 근거 미추출 {len(no_basis)}건 ──')
            for b, why in no_basis[:40]:
                print(f'    · {b} ({why})')
        if dropped_all:
            print(f'\n  ── 버린 인용 {len(dropped_all)}건(확정 실패·부칙 등) ──')
            for b, why in dropped_all[:40]:
                print(f'    · {b}: {why}')
        print('=== 완료(dry-run) ===')
        return 0

    inserted, pruned_total, failures = 0, 0, []
    for base, rows in sorted(rows_by_child.items()):
        payload = [{k: v for k, v in r.items() if not k.startswith('_')} for r in rows]
        try:
            upsert_rows(payload)
        except Exception as e:
            failures.append((base, f'upsert 실패(삭제 생략): {e}'))
            print(f'  ! {base}: upsert 실패 — 기존 행 보존: {e}')
            continue
        inserted += len(payload)
        try:
            pruned_total += prune_stale(base, synced_at)
        except Exception as e:
            failures.append((base, f'stale 삭제 실패(적재는 성공): {e}'))

    print('\n── 요약 ─────────────────────────────────')
    print(f'  적재: {inserted}행 upsert / {pruned_total}행 정리')
    print(f'  근거 미추출 문서: {len(no_basis)}건')
    if failures:
        print(f'  실패 {len(failures)}건:')
        for b, why in failures:
            print(f'    · {b}: {why}')
    else:
        print('  실패 없음')
    print('=== 완료 ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
