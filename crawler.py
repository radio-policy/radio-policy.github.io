#!/usr/bin/env python3
"""
전파정책 전문가 AI — 자동 크롤러
매시간 GitHub Actions에서 실행
크롤링 대상: 국립전파연구원 · 과기정통부 · 전자신문 외 다수
결과: Supabase news_feed 저장 + 이메일 발송 + 긴급 시 텔레그램 알림
"""

import os
import re
import json
import time
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# .env 파일 자동 로딩 (PC 로컬 실행 시)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # GitHub Actions에서는 환경변수 직접 주입, dotenv 불필요

import requests
import ssl
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
from supabase import Client
from sb_client import make_client
import notify   # 텔레그램 전송 공용 유틸 (개선⑪) — 전송부만 위임
import anthropic

# ── 환경변수 ────────────────────────────────────────────
SUPABASE_URL       = os.environ['SUPABASE_URL']
SUPABASE_KEY       = os.environ['SUPABASE_SERVICE_KEY']
# GitHub Actions 환경 감지 (본문 수집 스킵용)
IS_GITHUB_ACTIONS  = os.environ.get('GITHUB_ACTIONS', '').lower() == 'true'
EMAIL_FROM         = os.environ.get('EMAIL_FROM', '')
EMAIL_PASS         = os.environ.get('EMAIL_PASSWORD', '')
EMAIL_TO           = os.environ.get('EMAIL_TO', '')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID', '')
ANTHROPIC_API_KEY  = os.environ.get('ANTHROPIC_API_KEY', '')
RESEND_API_KEY     = os.environ.get('RESEND_API_KEY', '')
NAVER_CLIENT_ID    = os.environ.get('NAVER_CLIENT_ID', '')
NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET', '')

# ── 초기화 ─────────────────────────────────────────────
sb: Client = make_client(SUPABASE_URL, SUPABASE_KEY)
KST = timezone(timedelta(hours=9))
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'ko-KR,ko;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


# ═══════════════════════════════════════════════════════
#  긴급 분류 — Claude Haiku AI 판단
# ═══════════════════════════════════════════════════════

_URGENCY_SYSTEM = """당신은 SK텔레콤 Comm센터 기술정책팀의 전파정책 모니터링 AI입니다.
기사 제목과 본문을 읽고 SKT 관점에서 대응 우선순위를 판단합니다.

아래 기준으로 셋 중 하나만 출력하세요 (다른 말 없이 단어만):

즉시대응 (반드시 부정적·문제적 논조인 기사만):
- 이동통신 품질·기지국·공공 와이파이 관련 불만/민원/장애/사고/비판 기사
- 전파·전자파·주파수 관련 불만·규제강화·위반·행정처분 기사
- 과징금·허가취소·영업정지 등 통신사에 직접 피해를 주는 기사
⚠️ 주의: 성과 홍보·절감 효과·구축 완료 등 긍정적 내용은 즉시대응 제외

금주검토:
- 이동통신·전파·주파수 관련 정책 동향·기술 소개·통계 기사
- 입법예고·개정안·정책 발표 등 향후 영향을 줄 수 있는 기사
- 공공 와이파이 구축·확대·성과 관련 정보성 기사

동향파악:
- 위 두 기준에 해당하지 않는 해외 동향·업계 트렌드·참고용 기사"""

_AI_PRIORITY_MAP = {'즉시대응': '긴급', '금주검토': '보통', '동향파악': '참고'}
_REVERSE_PRIORITY = {'긴급': '즉시대응', '보통': '금주검토', '참고': '동향파악'}
_FALLBACK_MOBILE = ['이동통신', '기지국', '공공와이파이', '와이파이', '전파', '전자파', '무선국', '주파수']

_feedback_rows_cache = None
_distilled_rules_cache = None

def _load_feedback_rows() -> list:
    """importance_feedback 전체 로드 (실행당 1회, 최신순 최대 500건)"""
    global _feedback_rows_cache
    if _feedback_rows_cache is None:
        try:
            res = sb.table('importance_feedback').select('title,user_importance') \
                .order('updated_at', desc=True).limit(500).execute()
            _feedback_rows_cache = [r for r in (res.data or []) if r.get('title') and r.get('user_importance')]
            if _feedback_rows_cache:
                print(f'[피드백] 누적 사례 {len(_feedback_rows_cache)}건 로드')
        except Exception as e:
            print(f'[피드백] importance_feedback 조회 실패(무시): {e}')
            _feedback_rows_cache = []
    return _feedback_rows_cache


def _fb_tokens(s: str) -> set:
    return set(re.findall(r'[가-힣A-Za-z0-9]{2,}', (s or '').lower()))


def _get_distilled_rules() -> str:
    """피드백 20건 이상이면 Haiku로 일반화 규칙 증류 → feedback_rules 테이블 캐시.
    마지막 증류 이후 10건 이상 추가됐을 때만 재생성 (실행당 최대 1회 API 호출)."""
    global _distilled_rules_cache
    if _distilled_rules_cache is not None:
        return _distilled_rules_cache
    rows = _load_feedback_rows()
    if len(rows) < 20 or not ANTHROPIC_API_KEY:
        _distilled_rules_cache = ''
        return ''
    saved = None
    try:
        cur = sb.table('feedback_rules').select('rules,feedback_count').eq('id', 1).execute()
        saved = cur.data[0] if cur.data else None
        if saved and len(rows) < (saved.get('feedback_count') or 0) + 10:
            _distilled_rules_cache = saved.get('rules') or ''
            return _distilled_rules_cache
        sample = "\n".join(
            f"- \"{r['title'][:70]}\" → {_REVERSE_PRIORITY.get(r['user_importance'], r['user_importance'])}"
            for r in rows[:200]
        )
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001', max_tokens=600,
            system='다음은 뉴스 긴급도 분류(즉시대응/금주검토/동향파악)에 대한 담당자 수정 사례입니다. '
                   '사례들을 일반화한 분류 규칙 5~10개를 불릿(-)으로 간결히 요약하세요. 규칙 외 다른 말 금지.',
            messages=[{'role': 'user', 'content': sample}],
        )
        rules = resp.content[0].text.strip()
        sb.table('feedback_rules').upsert({
            'id': 1, 'rules': rules, 'feedback_count': len(rows),
            'updated_at': datetime.now(KST).isoformat(),
        }).execute()
        print(f'[피드백] 분류 규칙 재증류 완료 ({len(rows)}건 기반)')
        _distilled_rules_cache = rules
    except Exception as e:
        print(f'[피드백] 규칙 증류 실패(무시): {e}')
        _distilled_rules_cache = (saved.get('rules') or '') if saved else ''
    return _distilled_rules_cache


def get_feedback_examples(title: str = '') -> str:
    """분류 대상 기사에 맞춘 피드백 블록 생성:
    ① 증류 규칙 (20건 이상 누적 시) ② 제목 키워드가 겹치는 유사 사례 최대 5건
    ③ 등급별 균형 최신 사례 (등급당 최대 4건). 전부 메모리 연산 — 기사당 추가 비용 없음."""
    rows = _load_feedback_rows()
    if not rows:
        return ''
    tt = _fb_tokens(title)
    similar = []
    if tt:
        scored = [(len(tt & _fb_tokens(r['title'])), r) for r in rows]
        similar = [r for sc, r in sorted(scored, key=lambda x: -x[0]) if sc >= 2][:5]
    picked = list(similar)
    seen = {r['title'] for r in similar}
    per_class = {}
    for r in rows:
        c = r['user_importance']
        if r['title'] in seen or per_class.get(c, 0) >= 4:
            continue
        picked.append(r)
        seen.add(r['title'])
        per_class[c] = per_class.get(c, 0) + 1
    lines = [
        f"- \"{r['title'][:70]}\" → {_REVERSE_PRIORITY.get(r['user_importance'], r['user_importance'])}"
        for r in picked[:17]
    ]
    block = ''
    rules = _get_distilled_rules()
    if rules:
        block += "\n\n[담당자 분류 규칙 — 누적 피드백에서 추출. 최우선 적용]\n" + rules
    block += ("\n\n[담당자 분류 피드백 — 실제 담당자가 직접 수정한 사례. 유사한 기사는 반드시 이 기준을 우선 적용]\n"
              + "\n".join(lines))
    return block


def classify_urgency(title: str, content: str = '') -> str:
    """
    Claude Haiku로 기사 긴급도 AI 판단.
    API 키 없거나 오류 시 키워드 기반 폴백.
    반환값: '긴급' | '보통' | '참고'
    """
    if not ANTHROPIC_API_KEY:
        # API 키 없을 때 간단 폴백
        text = title + ' ' + (content or '')[:300]
        return '보통' if any(k in text for k in _FALLBACK_MOBILE) else '참고'

    snippet = re.sub(r'\s+', ' ', content or '').strip()[:600]
    user_msg = f"제목: {title}\n본문: {snippet}" if snippet else f"제목: {title}"

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=10,
            system=_URGENCY_SYSTEM + get_feedback_examples(title),
            messages=[{'role': 'user', 'content': user_msg}],
        )
        answer = resp.content[0].text.strip()
        # 응답에서 키워드 추출 (앞뒤 공백·줄바꿈 제거)
        for key in _AI_PRIORITY_MAP:
            if key in answer:
                return _AI_PRIORITY_MAP[key]
        return '참고'
    except Exception as e:
        print(f'  [AI 분류 오류] {title[:30]}... → 폴백 사용: {e}')
        text = title + ' ' + (content or '')[:300]
        return '보통' if any(k in text for k in _FALLBACK_MOBILE) else '참고'


# ═══════════════════════════════════════════════════════
#  유틸 함수
# ═══════════════════════════════════════════════════════

def _fetch_all_rows(table: str, columns: str) -> list:
    """PostgREST는 무제한 select도 최대 1,000행만 돌려준다 — 반드시 페이지네이션.
    (2026-08-03 사고: news_feed가 1,086건이 되자 최신 86건이 잘려 '기존' 판정에서
    빠졌고, 이미 알림한 긴급 기사를 신규로 착각해 재발송. 총량이 상한을 넘는 첫날
    조용히 터지는 유형이라 전량 조회는 이 헬퍼만 쓸 것.)"""
    rows, page, step = [], 0, 1000
    while True:
        res = sb.table(table).select(columns).range(page * step, (page + 1) * step - 1).execute()
        chunk = res.data or []
        rows.extend(chunk)
        if len(chunk) < step:
            return rows
        page += 1


def get_existing_urls() -> set:
    """Supabase에 이미 저장된 URL + 제목 목록 조회 (Google RSS 중복 방지)
    + 사용자가 대시보드에서 삭제한 기사(deleted_news)도 포함해 재수집 방지"""
    data = _fetch_all_rows('news_feed', 'url,title')
    urls   = {row['url']   for row in data if row.get('url')}
    titles = {row['title'] for row in data if row.get('title')}
    try:
        ddata = _fetch_all_rows('deleted_news', 'url,title')
        urls   |= {row['url']   for row in ddata if row.get('url')}
        titles |= {row['title'] for row in ddata if row.get('title')}
    except Exception as e:
        print(f'[삭제목록] deleted_news 조회 실패(무시): {e}')
    return urls, titles


def detect_category(title: str) -> str:
    if any(k in title for k in ['주파수', '할당', '경매', '분배', '재배치']): return '주파수'
    if any(k in title for k in ['전자파', 'SAR', 'EMC', '인체보호']): return '전자파'
    if any(k in title for k in ['적합성평가', '기자재', '시험기관', '인증']): return '기술기준'
    if any(k in title for k in ['ITU', 'WRC', 'IMT', '6G', '5G', 'AI']): return 'ITU·WRC'
    if any(k in title for k in ['기술기준', '무선설비', '무선국', '단말']): return '기술기준'
    if any(k in title for k in ['전기통신사업', '통신사업', '망중립', '번호이동']): return '전기통신사업'
    if any(k in title for k in ['정보통신망', '정보보호', '사이버', '개인정보']): return '정보통신망'
    return '기타'


def parse_date(date_str: str) -> str:
    """다양한 날짜 형식 → ISO 8601 변환. 파싱 실패 시 빈 문자열 반환."""
    if not date_str:
        return ''
    s = date_str.strip()
    now = datetime.now(KST)

    # 1) ISO 8601 / RFC 3339 (meta 태그에서 추출한 날짜)
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?', s)
    if m:
        y, mo, d, h, mi, sec = m.group(1,2,3,4,5,6)
        sec = sec or '00'
        try:
            dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec), tzinfo=KST)
            return dt.isoformat()
        except Exception:
            pass

    # 2) YYYY.MM.DD HH:MM:SS  /  YYYY.MM.DD HH:MM  /  YYYY.MM.DD
    m = re.match(r'(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?', s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        h  = int(m.group(4)) if m.group(4) else 0
        mi = int(m.group(5)) if m.group(5) else 0
        sec = int(m.group(6)) if m.group(6) else 0
        try:
            dt = datetime(y, mo, d, h, mi, sec, tzinfo=KST)
            return dt.isoformat()
        except Exception:
            pass

    # 3) 한국어 형식: 2024년 05월 28일 14:30
    m = re.match(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일(?:\s*(\d{1,2}):(\d{2})(?::(\d{2}))?)?', s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        h  = int(m.group(4)) if m.group(4) else 0
        mi = int(m.group(5)) if m.group(5) else 0
        sec = int(m.group(6)) if m.group(6) else 0
        try:
            dt = datetime(y, mo, d, h, mi, sec, tzinfo=KST)
            return dt.isoformat()
        except Exception:
            pass

    # 4) 상대 날짜: N분 전, N시간 전, N일 전
    m = re.search(r'(\d+)\s*(분|시간|일)\s*전', s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit == '분':
            dt = now - timedelta(minutes=n)
        elif unit == '시간':
            dt = now - timedelta(hours=n)
        else:
            dt = now - timedelta(days=n)
        return dt.isoformat()

    # 5) 어제
    if '어제' in s:
        dt = now - timedelta(days=1)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    # 6) MM.DD 형식 (연도 없음) → 현재 연도로 보정
    m = re.match(r'^(\d{1,2})[./](\d{1,2})$', s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        try:
            dt = datetime(now.year, mo, d, tzinfo=KST)
            # 미래 날짜라면 전년도로
            if dt > now:
                dt = dt.replace(year=now.year - 1)
            return dt.isoformat()
        except Exception:
            pass

    return ''  # 파싱 실패 — 호출자가 fallback 처리


# ═══════════════════════════════════════════════════════
#  크롤러 — 네이버 뉴스 검색 (1순위)
# ═══════════════════════════════════════════════════════

_NAVER_PRESS_DOMAINS = {
    'yna.co.kr': '연합뉴스', 'newsis.com': '뉴시스', 'etnews.com': '전자신문',
    'dt.co.kr': '디지털타임스', 'ddaily.co.kr': '디지털데일리', 'zdnet.co.kr': 'ZDNet Korea',
    'inews24.com': '아이뉴스24', 'bloter.net': '블로터', 'mk.co.kr': '매일경제',
    'mt.co.kr': '머니투데이', 'hankyung.com': '한국경제', 'sedaily.com': '서울경제',
    'chosun.com': '조선일보', 'joongang.co.kr': '중앙일보', 'donga.com': '동아일보',
    'hani.co.kr': '한겨레', 'khan.co.kr': '경향신문',
}


def _strip_html_tags(s: str) -> str:
    import html as _html
    s = re.sub(r'<[^>]+>', '', s or '')
    return _html.unescape(s).strip()


def _naver_pubdate_to_iso(pubdate: str) -> str:
    """네이버 API pubDate(RFC 2822, '... +0900') → KST ISO 8601."""
    if not pubdate:
        return ''
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(pubdate).astimezone(KST).isoformat()
    except Exception:
        return ''


def _domain_source(url: str) -> str:
    """원문 URL 도메인 → 언론사명(매핑) 또는 도메인 본체."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or '').lower()
        if host.startswith('www.'):
            host = host[4:]
        for dom, name in _NAVER_PRESS_DOMAINS.items():
            if host == dom or host.endswith('.' + dom):
                return name
        parts = host.split('.')
        # 한국형 2단계 TLD(co.kr·go.kr·or.kr 등)는 본체가 parts[-3]
        if len(parts) >= 3 and parts[-1] == 'kr' and parts[-2] in ('co', 'go', 'or', 'ne', 're', 'pe'):
            return parts[-3]
        return parts[-2] if len(parts) >= 2 else (host or '네이버뉴스')
    except Exception:
        return '네이버뉴스'


def crawl_naver_news() -> tuple:
    """네이버 뉴스 검색 OpenAPI로 키워드별 기사 수집.
    구 HTML 스크래핑(ul.list_news li.bx / a.news_tit)은 네이버 검색 구조 변경/해외 IP 차단으로
    0건 회귀해 폐지 → 공식 OpenAPI(JSON, IP·HTML 변경에 안전)로 전환.
    NAVER_CLIENT_ID/SECRET 미설정·오류 시 빈 결과 반환 → 호출부가 Google RSS로 폴백.
    반환: (items: list, fail_count: int)
    """
    if not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET):
        print('[네이버 뉴스] NAVER_CLIENT_ID/SECRET 미설정 — 건너뜀 (Google RSS 폴백)')
        return [], 0

    items = []
    seen_urls: set = set()
    seen_titles: set = set()
    fail_count = 0
    api_headers = {
        'X-Naver-Client-Id': NAVER_CLIENT_ID,
        'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
    }

    for kw in NEWS_SEARCH_KEYWORDS:
        try:
            res = requests.get(
                'https://openapi.naver.com/v1/search/news.json',
                headers=api_headers,
                params={'query': kw, 'display': 30, 'sort': 'date'},
                timeout=10,
            )
            res.raise_for_status()
            articles = (res.json() or {}).get('items', [])

            for art in articles:
                title = _strip_html_tags(art.get('title', ''))
                if not title or len(title) < 8:
                    continue
                is_personnel = is_ministry_personnel_news(title)
                # 제목 RADIO_KEYWORDS 포함 여부로 걸러내던 게이트는 폐지(2026-08-03).
                # 넓게 담고 관련성은 screen_news_items()의 Haiku 1차 선별이 판정한다.
                # EXCLUDE_KEYWORDS(스포츠·선거·부동산 오탐)는 값싼 사전 차단이라 그대로 둔다.
                if not is_personnel and any(k in title for k in EXCLUDE_KEYWORDS):
                    continue
                if title in seen_titles:
                    continue
                seen_titles.add(title)

                # n.news.naver.com(link) 우선 — 본문 수집률↑, 없으면 원문
                naver_link = art.get('link', '') or ''
                origin = art.get('originallink', '') or ''
                href = naver_link if 'naver.com' in naver_link else (origin or naver_link)
                if not href or href in seen_urls:
                    continue
                # 스포츠·연예 오인 차단 — 도메인까지 봐야 하므로 URL 확정 후에 판정 (배경역사 #45)
                if not is_personnel and is_sports_noise(title, href):
                    continue
                seen_urls.add(href)

                items.append({
                    'title':        title,
                    'source':       _domain_source(origin or naver_link),
                    'category':     detect_category(title),
                    'url':          href,
                    'is_read':      False,
                    'published_at': _naver_pubdate_to_iso(art.get('pubDate', '')),
                    'content':      None,
                    # 선별 전용 임시 필드 — 네이버 API description(요약)을 판정 재료로만 쓴다.
                    # content에 넣지 않는 이유: refetch_content.py가 'content 100자 미만'을
                    # 본문 재수집 대상으로 삼는데 요약이 들어가면 재수집이 막힌다.
                    # screen_news_items()가 판정 직후 이 키를 제거하므로 DB로는 흘러가지 않는다.
                    '_screen_text': _strip_html_tags(art.get('description', ''))[:300],
                })
        except Exception as e:
            print(f'[네이버 뉴스 오류] {kw}: {str(e)[:80]}')
            fail_count += 1
        time.sleep(0.3)

    print(f'[네이버 뉴스] {len(items)}건 수집 (실패 키워드 {fail_count}개)')
    return items, fail_count


# ═══════════════════════════════════════════════════════
#  크롤러 — Google News RSS (네이버 차단 시 폴백)
# ═══════════════════════════════════════════════════════

def crawl_google_news_rss() -> list:
    """Google News RSS로 키워드 기반 뉴스 수집.
    - GitHub Actions(미국 IP)에서도 차단 없음
    - 발행일 100% 포함 (RFC 2822 → KST 자동 변환)
    - 제목 기반 중복 제거 (save_new_items에서 URL·제목 이중 체크)
    """
    try:
        import feedparser
        import calendar as _cal
    except ImportError:
        print('[Google RSS] feedparser 미설치 — pip install feedparser')
        return []

    items = []
    seen_titles: set = set()

    for kw in NEWS_SEARCH_KEYWORDS:
        rss_url = (
            'https://news.google.com/rss/search'
            f'?q={requests.utils.quote(kw)}&hl=ko&gl=KR&ceid=KR:ko'
        )
        try:
            feed = feedparser.parse(rss_url)
            for entry in (feed.entries or []):
                # 제목에서 "기사 제목 - 언론사명" 분리
                raw_title = (entry.get('title') or '').strip()
                if ' - ' in raw_title:
                    title  = raw_title.rsplit(' - ', 1)[0].strip()
                    source = raw_title.rsplit(' - ', 1)[1].strip()
                else:
                    title  = raw_title
                    source = (entry.get('source') or {}).get('title', '알수없음')

                if not title or len(title) < 8:
                    continue
                is_personnel = is_ministry_personnel_news(title)
                # 네이버 경로와 동일 — RADIO_KEYWORDS 포함 게이트 폐지, EXCLUDE는 유지 (2026-08-03)
                if not is_personnel and any(k in title for k in EXCLUDE_KEYWORDS):
                    continue
                if title in seen_titles:
                    continue
                seen_titles.add(title)

                link = entry.get('link', '')
                if not link:
                    continue

                # Google News 리다이렉트 URL → 실제 기사 URL로 변환
                if 'news.google.com' in link:
                    decoded = False
                    try:
                        from googlenewsdecoder import new_decoderv1
                        result = new_decoderv1(link)
                        if result.get('status') is True and result.get('decoded_url'):
                            link = result['decoded_url']
                            decoded = True
                    except Exception:
                        pass
                    if not decoded:
                        try:
                            r = requests.get(link, headers=HEADERS, timeout=8, allow_redirects=True)
                            if r.url and 'news.google.com' not in r.url:
                                link = r.url
                        except Exception:
                            pass  # 실패 시 원본 URL 유지

                # 스포츠·연예 오인 차단 — 리다이렉트 해제 후의 실제 URL로 판정 (배경역사 #45)
                if not is_personnel and is_sports_noise(title, link):
                    continue

                # 발행일: published_parsed(UTC struct_time) → KST ISO
                pub_struct = entry.get('published_parsed')
                if pub_struct:
                    from datetime import datetime as _dt
                    pub_utc = _dt.fromtimestamp(_cal.timegm(pub_struct), tz=timezone.utc)
                    date_str = pub_utc.astimezone(KST).isoformat()
                else:
                    date_str = ''

                # RSS 요약(summary)을 content로 저장 → 대시보드 즉시 표시
                import re as _re
                raw_summary = entry.get('summary', '') or ''
                # HTML 태그 제거
                clean_summary = _re.sub(r'<[^>]+>', '', raw_summary).strip()
                # 출처 표기 제거 (예: " - 전자신문" 등)
                if ' - ' in clean_summary:
                    clean_summary = clean_summary.rsplit(' - ', 1)[0].strip()
                content_text = clean_summary[:500] if clean_summary else None

                items.append({
                    'title':        title,
                    'source':       source,
                    'category':     detect_category(title),
                    'url':          link,
                    'is_read':      False,
                    'published_at': date_str,
                    'content':      content_text,
                    '_screen_text': (content_text or '')[:300],   # 선별 재료 (판정 후 제거)
                })
        except Exception as e:
            print(f'[Google RSS 오류] {kw}: {e}')
        time.sleep(0.3)

    print(f'[Google RSS] {len(items)}건 수집')
    return items


# ═══════════════════════════════════════════════════════
#  크롤러 — 국립전파연구원 (rra.go.kr)
# ═══════════════════════════════════════════════════════

def crawl_rra() -> list:
    items = []
    targets = [
        ('https://www.rra.go.kr/ko/notice/noticeList.do',  '공지사항', '국립전파연구원'),
        ('https://www.rra.go.kr/ko/rule/ruleList.do',      '고시·예규', '국립전파연구원'),
        ('https://www.rra.go.kr/ko/rule/prioRuleList.do',  '예고',     '국립전파연구원'),
    ]
    for url, label, source in targets:
        try:
            res = requests.get(url, headers=HEADERS, timeout=20)
            res.raise_for_status()
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')

            rows = soup.select('table.board_list tbody tr, table tbody tr')[:15]
            for row in rows:
                tds = row.find_all('td')
                if len(tds) < 2:
                    continue
                title_tag = row.find('a')
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                if not title or title.isdigit():
                    continue
                href = title_tag.get('href', '')
                if not href:
                    continue
                if href.startswith('/'):
                    href = 'https://www.rra.go.kr' + href
                date_str = tds[-2].get_text(strip=True) if len(tds) >= 3 else ''
                items.append({
                    'title': title,
                    'source': source,
                    'category': '기술기준' if '고시' in label else '기타',
                    'url': href,
                    'is_read': False,
                    'published_at': parse_date(date_str),
                })
            print(f'[RRA] {label}: {len(rows)}행 수집')
        except Exception as e:
            print(f'[RRA 오류] {label}: {e}')
    return items


# ═══════════════════════════════════════════════════════
#  크롤러 — 과기정통부 (msit.go.kr)
# ═══════════════════════════════════════════════════════

RADIO_KEYWORDS = [
    # 전파법 계열
    '전파', '주파수', 'ITU', 'IMT', '5G', '6G', '전자파',
    '무선', '적합성평가', '기자재', 'WRC', '스펙트럼',
    # 전기통신사업법 계열
    '전기통신사업', '통신사업', '망중립', '번호이동', '이용자보호',
    '단말장치', '통신서비스', '과징금',
    # 정보통신망법 계열
    '정보통신망', '정보보호', '사이버', '불법정보', '개인정보',
    # NEWS_SEARCH_KEYWORDS 통합 (와이파이·이동통신·기지국 등)
    '전파정책', '이동통신', '6GHz', '와이파이', '공공와이파이',
    '공공 와이파이', '지하철 와이파이', '기지국', 'LTE', '3G',
    '이동통신 품질', '5G 기지국', 'LTE 기지국', '기지국 장애', '이동통신 장비',
    '무선국', '5G주파수', '6G주파수',
]

# 비관련 기사 제외 키워드 — 스포츠·연예·부동산 등
EXCLUDE_KEYWORDS = [
    # 스포츠
    '안타', '홈런', '타율', '경기장', '야구', '축구', '농구', '골프', '테니스',
    'MLB', 'NBA', 'KBO', 'EPL', '올림픽', '월드컵', '선수', '감독', '코치',
    '우익수', '좌익수', '투수', '포수', '타자', '세리머니', '연속경기',
    # 모터스포츠 (WRC 랠리 오인 방지)
    '랠리', '레이싱', '모터스포츠', '자동차경주', 'F1', '포뮬러', 'FIA',
    'WRC 7', 'WRC 6', 'WRC 5', 'WRC 4', 'WRC 3', 'WRC 2', 'WRC 1',
    'WRC 재팬', 'WRC 저팬', 'WRC 핀란드', 'WRC 포르투갈', '타이어',
    # 야구·구기 스포츠 (3G 오인 방지)
    '득점', '이닝', '타석', '삼진', '볼넷', '스윕', '선발 라인업',
    '나성범', '김하성', '이정후', '플레이오프', '시리즈전', '연속 침묵',
    '무실점', '연속 무실점', '선발 등판', '완투', '병살', '도루', '번트',
    '1승', '2승', '3승', '연승', '연패', '경기 결과', '프로야구', '프로축구',
    '원정팀', '홈팀', '원정 승리', '연속 원정',
    '파이어볼러', '자책점', '평균자책점', '지명타자', '선발투수', '마무리투수',
    '1차 지명', '2차 지명', '신인 드래프트', '트레이드', '외야수', '내야수',
    'km/h 직구', '구속', '방어율',
    '리드오프', '햄스트링', '1라운더', '2라운더', '연속 선발', '연속 등판',
    '강백호', '이승엽', '류현진', '오재원', '박세웅',  # KBO 선수명
    '경기 후반 준비', '선발에서 사라', '불펜',
    # 선거 (LTE·3G 오인 방지)
    '선거', '선관위', '투표소', '투표용지', '지방선거', '국회의원', '대통령', '후보', '당선',
    '개표', '사전투표', '선거구', '선거운동', '출마', '지방선거일',
    # 연예·방송
    '아이돌', '드라마', '영화', '콘서트', '팬미팅', '데뷔', '컴백',
    # 부동산·금융
    '아파트', '분양', '재건축', '청약', '주식', '코스피', '나스닥',
    # 기타
    '레시피', '맛집', '여행', '날씨',
]

# ───────────────────────────────────────────────────────
#  스포츠·방송코너 오인 차단 — 단어 목록이 아니라 '패턴'으로 (배경역사 #45)
#
#  EXCLUDE_KEYWORDS에 야구 용어를 40개 넘게 쌓아 왔지만, 정작 새 나가는 제목들에는
#  그 단어가 하나도 없었다 — '3G 연속포', '3G 8타점', '3G 무패', '3G 연속골'.
#  스포츠 기사가 3G를 쓰는 방식은 정해져 있는데(3G+기록어) 목록은 선수 이름만 쫓아
#  다녔던 것. 새 선수·새 표현이 나올 때마다 뚫린다. 그래서 조합을 본다.
#
#  실측 검증(2026-08-01): DB의 3G/LTE 기사 14건에 걸어 스포츠 2건만 걸리고
#  통신 기사 12건은 전원 통과 — 특히 진행 중인 '3G 종료' 이슈 7건 모두 통과.
#   \d* 는 '3G 2골'처럼 숫자가 끼는 표기 대응(테스트로 발견). '2G/3G 종료'는
#   숫자 뒤가 'G'라 기록어에 걸리지 않아 안전하다.
_SPORTS_NUM_RE = re.compile(
    r'\b[36]G\b\s*\d*\s*(연속|무패|무실점|타점|타수|안타|홈런|골|승|패|세이브|QS|경기|보살)')
# 지역 MBC 등이 실시간 리포트 코너명으로 [LTE]를 쓴다.
# '[LTE/리포트]' 같은 변형이 있어 대괄호 안 뒷부분을 열어 둔다(테스트로 발견).
_LTE_CORNER_RE = re.compile(r'\[\s*LTE\b[^\]]*\]|^LTE\)')
# 도메인이 가장 확실하다 — 삭제 이력 25건 중 12건이 이 두 곳이었다
_SPORTS_DOMAINS = ('sports.naver.com', 'entertain.naver.com')


def is_sports_noise(title: str, url: str = '') -> bool:
    """스포츠·연예 오인 기사인가. 제목 패턴 + 출처 도메인 조합으로 판정.
    '3G 종료', 'LTE 20배', 'LTE-R'처럼 통신 맥락은 걸리지 않는다(실측 확인)."""
    t = title or ''
    if _SPORTS_NUM_RE.search(t):
        return True
    if _LTE_CORNER_RE.search(t):
        return True
    u = (url or '').lower()
    if any(d in u for d in _SPORTS_DOMAINS):
        return True
    return False


# ───────────────────────────────────────────────────────
# 과기정통부·방통위 등 소관 부처 인사이동 뉴스 — 항상 포함
# (RADIO_KEYWORDS 미포함이어도 수집, EXCLUDE_KEYWORDS보다 우선)
# ───────────────────────────────────────────────────────
MINISTRY_NAMES = [
    '과기정통부', '과학기술정보통신부', '과기부',
    '방통위', '방송통신위원회', '국립전파연구원', '중앙전파관리소',
]
PERSONNEL_WORDS = [
    '인사', '임명', '취임', '내정', '발탁', '승진', '경질', '교체',
    '인사이동', '인사발령', '이동', '전보', '보직', '차관', '장관', '실장', '국장',
]

def is_ministry_personnel_news(title: str) -> bool:
    """소관 부처 인사 관련 기사 여부 (부처명 + 인사 용어 동시 포함)"""
    return (any(m in title for m in MINISTRY_NAMES)
            and any(p in title for p in PERSONNEL_WORDS))

def crawl_msit() -> list:
    items = []
    targets = [
        ('https://www.msit.go.kr/bbs/list.do?sCode=user&mId=129&mPid=128', '보도자료'),
        ('https://www.msit.go.kr/bbs/list.do?sCode=user&mId=99&mPid=74',   '공지사항'),
    ]
    for url, label in targets:
        try:
            res = requests.get(url, headers=HEADERS, timeout=20)
            res.raise_for_status()
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')

            rows = soup.select('table tbody tr, ul.bbs_list li')[:20]
            for row in rows:
                title_tag = row.find('a')
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                if not title:
                    continue
                if not any(kw in title for kw in RADIO_KEYWORDS) and not is_ministry_personnel_news(title):
                    continue
                href = title_tag.get('href', '')
                if href.startswith('/'):
                    href = 'https://www.msit.go.kr' + href
                date_tag = row.find(class_=re.compile(r'date|day|time'))
                date_str = date_tag.get_text(strip=True) if date_tag else ''
                items.append({
                    'title': title,
                    'source': '과기정통부',
                    'category': detect_category(title),
                    'url': href,
                    'is_read': False,
                    'published_at': parse_date(date_str),
                })
            print(f'[MSIT] {label}: 관련 {len([i for i in items if i["source"]=="과기정통부"])}건')
        except Exception as e:
            print(f'[MSIT 오류] {label}: {e}')
    return items


# ═══════════════════════════════════════════════════════
#  크롤러 — 전자신문 (etnews.com)
# ═══════════════════════════════════════════════════════

def crawl_etnews() -> list:
    items = []
    search_keywords = ['전파정책', '주파수할당', 'WRC-27', '6GHz IMT', '5G주파수']
    for kw in search_keywords:
        url = f'https://www.etnews.com/news/search.html?kwd={requests.utils.quote(kw)}'
        try:
            res = requests.get(url, headers=HEADERS, timeout=20)
            res.raise_for_status()
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')

            articles = soup.select('ul.c_list_article li, div.news_list article')[:5]
            for article in articles:
                title_tag = article.find('a')
                if not title_tag:
                    title_tag = article.select_one('h4 a, h3 a, .title a')
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                href = title_tag.get('href', '')
                if not title or not href:
                    continue
                if href.startswith('/'):
                    href = 'https://www.etnews.com' + href
                date_tag = article.find(class_=re.compile(r'date|time|day'))
                date_str = date_tag.get_text(strip=True) if date_tag else ''
                items.append({
                    'title': title,
                    'source': '전자신문',
                    'category': detect_category(title),
                    'url': href,
                    'is_read': False,
                    'published_at': parse_date(date_str),
                })
        except Exception as e:
            print(f'[전자신문 오류] {kw}: {e}')
    print(f'[전자신문] {len(items)}건 수집')
    return items


# ═══════════════════════════════════════════════════════
#  크롤러 — 방송통신위원회 (kcc.go.kr)
# ═══════════════════════════════════════════════════════

def crawl_kcc() -> list:
    items = []
    targets = [
        ('https://kcc.go.kr/user.do?mode=view&page=A05030000&dc=K05030000', '보도자료', '방송통신위원회'),
        ('https://kcc.go.kr/user.do?mode=view&page=A05010000&dc=K05010000', '공지사항', '방송통신위원회'),
    ]
    for url, label, source in targets:
        try:
            res = requests.get(url, headers=HEADERS, timeout=20)
            res.raise_for_status()
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.select('table tbody tr, ul.bbs_list li')[:15]
            for row in rows:
                title_tag = row.find('a')
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                if not title or not any(k in title for k in RADIO_KEYWORDS):
                    continue
                href = title_tag.get('href', '')
                if href.startswith('/'):
                    href = 'https://kcc.go.kr' + href
                date_tag = row.find(class_=re.compile(r'date|day|time'))
                date_str = date_tag.get_text(strip=True) if date_tag else ''
                items.append({
                    'title': title,
                    'source': source,
                    'category': detect_category(title),
                    'url': href,
                    'is_read': False,
                    'published_at': parse_date(date_str),
                })
        except Exception as e:
            print(f'[방통위 오류] {label}: {e}')
    print(f'[방통위] {len(items)}건 수집')
    return items


# ═══════════════════════════════════════════════════════
#  크롤러 — ETRI (etri.re.kr)
# ═══════════════════════════════════════════════════════

def crawl_etri() -> list:
    items = []
    targets = [
        ('https://www.etri.re.kr/kor/bbs/list.do?bbsId=1001', '보도자료', 'ETRI'),
        ('https://www.etri.re.kr/kor/bbs/list.do?bbsId=1003', '공지사항', 'ETRI'),
    ]
    for url, label, source in targets:
        try:
            res = requests.get(url, headers=HEADERS, timeout=20)
            res.raise_for_status()
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.select('table tbody tr')[:15]
            for row in rows:
                title_tag = row.find('a')
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                if not title or not any(k in title for k in RADIO_KEYWORDS + ['6G', '5G', 'IMT', 'AI', '표준', '연구']):
                    continue
                href = title_tag.get('href', '')
                if href.startswith('/'):
                    href = 'https://www.etri.re.kr' + href
                date_tag = row.find(class_=re.compile(r'date|day|time'))
                date_str = date_tag.get_text(strip=True) if date_tag else ''
                items.append({
                    'title': title,
                    'source': source,
                    'category': detect_category(title),
                    'url': href,
                    'is_read': False,
                    'published_at': parse_date(date_str),
                })
        except Exception as e:
            print(f'[ETRI 오류] {label}: {e}')
    print(f'[ETRI] {len(items)}건 수집')
    return items


# ═══════════════════════════════════════════════════════
#  크롤러 — KISDI (kisdi.re.kr)
# ═══════════════════════════════════════════════════════

def crawl_kisdi() -> list:
    items = []
    targets = [
        ('https://www.kisdi.re.kr/bbs/list.do?bbsId=BBSMSTR_000000000017', '연구보고서', 'KISDI'),
        ('https://www.kisdi.re.kr/bbs/list.do?bbsId=BBSMSTR_000000000018', '정책자료', 'KISDI'),
    ]
    for url, label, source in targets:
        try:
            res = requests.get(url, headers=HEADERS, timeout=20)
            res.raise_for_status()
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.select('table tbody tr, ul.bbs_list li')[:15]
            for row in rows:
                title_tag = row.find('a')
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                if not title or not any(k in title for k in RADIO_KEYWORDS + ['6G', '5G', 'IMT', '방송', '통신', '인터넷']):
                    continue
                href = title_tag.get('href', '')
                if href.startswith('/'):
                    href = 'https://www.kisdi.re.kr' + href
                date_tag = row.find(class_=re.compile(r'date|day|time'))
                date_str = date_tag.get_text(strip=True) if date_tag else ''
                items.append({
                    'title': title,
                    'source': source,
                    'category': detect_category(title),
                    'url': href,
                    'is_read': False,
                    'published_at': parse_date(date_str),
                })
        except Exception as e:
            print(f'[KISDI 오류] {label}: {e}')
    print(f'[KISDI] {len(items)}건 수집')
    return items


# ═══════════════════════════════════════════════════════
#  크롤러 — 범용 키워드 검색 (IT전문지·경제지·종합일간지)
# ═══════════════════════════════════════════════════════

# ───────────────────────────────────────────────────────
#  뉴스 검색어 — "넓게 수집 → Haiku 선별" 구조로 확대 (2026-08-03)
#  기존 27개는 좁은 검색어라 '통신요금 인하', 'AI 기본법' 등 소관 이슈인데도
#  제목에 전파 계열 단어가 없으면 아예 검색되지 않았다. 보도자료 쪽에서 이미 쓰는
#  app_config.press_keywords(33개) 중 '뉴스 검색어로서 유효한 것'만 골라 병합한다.
#  - 단독으로 쓰면 소음만 늘어나는 일반어(AI·요금·무선·사이버·단말·스펙트럼·기자재)는
#    복합어로 좁혀 넣거나 제외했다. 예: AI → 'AI 기본법'·'AI 규제', 요금 → '통신요금'
#  - 'WRC' 단독은 모터스포츠 랠리 오탐이라 기존 'WRC-27'만 유지.
#  - '전파' 단독은 '감염 전파' 등 동사 용법이 많아 '전파법'·'전파사용료'로 대체.
#  넓힌 만큼 관련성 판정은 제목 키워드가 아니라 screen_news_items()의 Haiku가 맡는다.
# ───────────────────────────────────────────────────────
NEWS_SEARCH_KEYWORDS = [
    # ── 기존 27개 (유지) ──
    '전파정책', '주파수', '5G주파수', '5G 주파수', '6G주파수', '6G 주파수',
    '전자파', '무선국', '이동통신', 'WRC-27', '6GHz',
    '공공와이파이', '공공 와이파이', '지하철 와이파이',
    '기지국', 'LTE', '3G', '이동통신 품질', '5G 기지국', 'LTE 기지국',
    '기지국 장애', '이동통신 장비',
    '과기정통부 인사', '과학기술정보통신부 인사', '과기정통부 승진',
    '과기정통부 인사이동', '방통위 인사',
    # ── 확대분 (press_keywords 병합) ──
    '5G', '6G', '주파수 할당', '전파법', '전파사용료',
    '무선설비', '적합성평가', '방송통신기자재', 'ITU',
    '전기통신사업법', '정보통신망법', '위치정보법', '통신정책',
    '통신요금', '통신품질', '통신장애', '알뜰폰', '번호이동',
    '단말기유통', '이용자보호', '스팸문자', '재난문자',
    '위성통신', '사이버보안', 'AI 기본법', 'AI 규제',
    '과기정통부',
]

# 언론사별 검색 설정 ─ (source, search_url, article_sel, date_sel, base_url)
NEWS_SITE_CONFIGS = [
    # ── IT·통신 전문지 ─────────────────────────────────
    {
        'source': '디지털타임스',
        'search_url': 'https://www.dt.co.kr/search.php?q={kw}',
        'article_sel': ['div.article_title a', 'h4.tit a', 'ul.article_list li a'],
        'date_sel':    ['span.date', 'em.date', 'span.regdate'],
        'base_url':    'https://www.dt.co.kr',
    },
    {
        'source': '디지털데일리',
        'search_url': 'https://www.ddaily.co.kr/search?keyword={kw}',
        'article_sel': ['ul.article_list li a', 'div.article_title a', 'h4.tit a'],
        'date_sel':    ['span.date', 'em.date', 'span.regdate'],
        'base_url':    'https://www.ddaily.co.kr',
    },
    {
        'source': 'ZDNet Korea',
        'search_url': 'https://zdnet.co.kr/news/?t=&q={kw}&l=&c=',
        'article_sel': ['article h4 a', 'div.article_title a', 'ul.news_list li a'],
        'date_sel':    ['span.date', 'em.date', 'time'],
        'base_url':    'https://zdnet.co.kr',
    },
    {
        'source': '아이뉴스24',
        'search_url': 'https://search.inews24.com/search/news?q={kw}',
        'article_sel': ['div.result_news ul li a.tit', 'ul.article_list li a', 'div.news_list a'],
        'date_sel':    ['span.date', 'span.regdate', 'em.date'],
        'base_url':    'https://www.inews24.com',
    },
    {
        'source': '블로터',
        'search_url': 'https://www.bloter.net/?s={kw}',
        'article_sel': ['h2.entry-title a', 'h3.entry-title a', 'article a.entry-title'],
        'date_sel':    ['time.entry-date', 'span.date', 'span.post-date'],
        'base_url':    'https://www.bloter.net',
    },
    {
        'source': '정보통신신문',
        'search_url': 'https://www.koit.co.kr/news/articleList.html?sc_word={kw}',
        'article_sel': ['ul.type2 li a', 'div.list-titles a', 'h4.titles a'],
        'date_sel':    ['em.info', 'span.date', 'em.date'],
        'base_url':    'https://www.koit.co.kr',
    },
    # ── 경제지 ────────────────────────────────────────
    {
        'source': '매일경제',
        'search_url': 'https://search.mk.co.kr/search.php?q={kw}',
        'article_sel': ['ul.search_news_list li a', 'div.con_tit a', 'h3.news_tit a'],
        'date_sel':    ['span.date', 'em.date', 'span.lasttime'],
        'base_url':    'https://www.mk.co.kr',
    },
    {
        'source': '머니투데이',
        'search_url': 'https://search.mt.co.kr/mtSearchMain.php?q={kw}',
        'article_sel': ['ul.newslist01 li dt a', 'div.news_list li a', 'a.news_tit'],
        'date_sel':    ['span.date', 'em.date', 'li.date'],
        'base_url':    'https://news.mt.co.kr',
    },
    {
        'source': '한국경제',
        'search_url': 'https://search.hankyung.com/search/news?query={kw}',
        'article_sel': ['ul.article__list li a', 'div.article_title a', 'h3.tit a',
                        'div.news-list a', 'li.news-item a', 'a.news-tit'],
        'date_sel':    ['span.date', 'em.date', 'span.txt-date', 'span.txt_date',
                        'span.article-date', 'p.date', 'div.date', 'span.info',
                        'span.byline', 'p.byline', 'span.writer'],
        'base_url':    'https://www.hankyung.com',
    },
    {
        'source': '서울경제',
        'search_url': 'https://www.sedaily.com/Search/News?Keyword={kw}',
        'article_sel': ['ul.article_list li a', 'div.article_title a', 'h3.tit a'],
        'date_sel':    ['span.date', 'em.date', 'span.txt_date'],
        'base_url':    'https://www.sedaily.com',
    },
    # ── 종합일간지·통신 ──────────────────────────────
    {
        'source': '연합뉴스',
        'search_url': 'https://www.yna.co.kr/search/index?query={kw}&lang=KOR',
        'article_sel': ['div.cts-title a', 'ul.list01 li a.tit', 'div.result-basic a.tit'],
        'date_sel':    ['p.cts-date', 'span.date', 'span.cts-date'],
        'base_url':    'https://www.yna.co.kr',
    },
    {
        'source': '뉴시스',
        'search_url': 'https://www.newsis.com/search/?q={kw}',
        'article_sel': ['ul.list_news li a', 'div.tit_news a', 'a.txt_tit'],
        'date_sel':    ['span.date', 'em.date', 'li.date'],
        'base_url':    'https://www.newsis.com',
    },
    {
        'source': '조선일보',
        'search_url': 'https://www.chosun.com/search/?query={kw}',
        'article_sel': ['a.story-card__headline', 'div.news_tit a', 'h3.tit a'],
        'date_sel':    ['time', 'span.date', 'em.date'],
        'base_url':    'https://www.chosun.com',
    },
    {
        'source': '중앙일보',
        'search_url': 'https://www.joongang.co.kr/search/news?keyword={kw}',
        'article_sel': ['a.card-title', 'h2.headline a', 'div.article_title a'],
        'date_sel':    ['time', 'span.date', 'em.date'],
        'base_url':    'https://www.joongang.co.kr',
    },
    {
        'source': '동아일보',
        'search_url': 'https://www.donga.com/news/search?query={kw}',
        'article_sel': ['div.tit a', 'h3.tit a', 'ul.news_list li a'],
        'date_sel':    ['span.date', 'em.date', 'span.txt_date'],
        'base_url':    'https://www.donga.com',
    },
    {
        'source': '한겨레',
        'search_url': 'https://www.hani.co.kr/arti/SEARCH/search.html?query={kw}',
        'article_sel': ['div.article-title a', 'ul.search_list li a', 'h4.title a'],
        'date_sel':    ['span.date', 'em.date', 'time'],
        'base_url':    'https://www.hani.co.kr',
    },
    {
        'source': '경향신문',
        'search_url': 'https://www.khan.co.kr/search?query={kw}',
        'article_sel': ['a.news_title', 'div.tit a', 'h3.tit a'],
        'date_sel':    ['span.date', 'em.date', 'span.txt_date'],
        'base_url':    'https://www.khan.co.kr',
    },
]


def crawl_news_site(cfg: dict) -> list:
    """키워드 검색 기반 범용 뉴스 크롤러"""
    items = []
    source = cfg['source']
    seen_urls: set = set()
    for kw in NEWS_SEARCH_KEYWORDS:  # 키워드 전체
        url = cfg['search_url'].format(kw=requests.utils.quote(kw))
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'html.parser')

            # 기사 링크 탐색 (복수 셀렉터 시도)
            links = []
            for sel in cfg['article_sel']:
                links = soup.select(sel)
                if links:
                    break
            if not links:
                # fallback: 모든 <a>에서 전파 키워드 포함 제목 탐색
                links = [a for a in soup.find_all('a', href=True)
                         if any(k in a.get_text() for k in ['전파', '주파수', '5G', '6G', '이동통신', '무선'])]

            for link in links[:8]:
                title = link.get_text(strip=True)
                if not title or len(title) < 8:
                    continue
                if not any(k in title for k in RADIO_KEYWORDS) and not is_ministry_personnel_news(title):
                    continue
                href = link.get('href', '')
                if not href:
                    continue
                if href.startswith('/'):
                    href = cfg['base_url'] + href
                if not href.startswith('http'):
                    continue
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                # 날짜 추출 (부모 컨테이너에서 탐색)
                date_str = ''
                parent = link.parent
                for _ in range(4):  # 최대 4단계 부모까지
                    if parent is None:
                        break
                    for dsel in cfg['date_sel']:
                        dtag = parent.select_one(dsel)
                        if dtag:
                            date_str = dtag.get_text(strip=True)
                            break
                    if date_str:
                        break
                    parent = parent.parent

                items.append({
                    'title': title,
                    'source': source,
                    'category': detect_category(title),
                    'url': href,
                    'is_read': False,
                    'published_at': parse_date(date_str),
                })
        except Exception as e:
            print(f'[{source} 오류] {kw}: {e}')
        time.sleep(0.5)
    print(f'[{source}] {len(items)}건 수집')
    return items


# ═══════════════════════════════════════════════════════
#  기사 본문 수집
# ═══════════════════════════════════════════════════════

class _WeakDHAdapter(HTTPAdapter):
    """DH_KEY_TOO_SMALL 오류 우회용 SSL 어댑터 (SECLEVEL=1)"""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
        kwargs['ssl_context'] = ctx
        super().init_poolmanager(*args, **kwargs)

_KNOWN_WEAK_DH = ('rra.go.kr',)

def _http_get(url: str, timeout: int = 8):
    """일반 GET → DH_KEY_TOO_SMALL SSL 약점 사이트면 SECLEVEL=1 어댑터로 자동 재시도."""
    # 알려진 약 DH 사이트는 처음부터 어댑터 사용 (불필요한 1차 실패 회피)
    if any(d in url for d in _KNOWN_WEAK_DH):
        s = requests.Session()
        s.mount('https://', _WeakDHAdapter())
        return s.get(url, headers=HEADERS, timeout=timeout)
    try:
        return requests.get(url, headers=HEADERS, timeout=timeout)
    except requests.exceptions.SSLError as e:
        if 'dh key too small' in str(e).lower() or 'DH_KEY_TOO_SMALL' in str(e):
            s = requests.Session()
            s.mount('https://', _WeakDHAdapter())
            return s.get(url, headers=HEADERS, timeout=timeout)
        raise

def fetch_article_body(url: str, source: str) -> tuple:
    """기사 URL에서 본문 텍스트와 발행일 추출. 반환: (body: str, published_at: str)"""
    try:
        resp = _http_get(url, timeout=8)
        resp.raise_for_status()
        # RRA(국립전파연구원) 사이트는 EUC-KR 인코딩
        if 'rra.go.kr' in url:
            resp.encoding = 'euc-kr'
        soup = BeautifulSoup(resp.text, 'html.parser')

        # ── 발행일 추출 (meta 태그 우선) ───────────────────
        pub_date = ''

        # 1순위: Open Graph / schema.org meta 태그
        for attr_name, attr_val in [
            ('property', 'article:published_time'),
            ('property', 'og:article:published_time'),
            ('itemprop', 'datePublished'),
            ('name', 'article:published_time'),
            ('name', 'publishdate'),
            ('name', 'date'),
        ]:
            tag = soup.find('meta', attrs={attr_name: attr_val})
            if tag and tag.get('content'):
                parsed = parse_date(tag['content'])
                if parsed:
                    pub_date = parsed
                    break

        # 2순위: <time datetime="..."> 태그
        if not pub_date:
            for time_tag in soup.find_all('time', datetime=True):
                parsed = parse_date(time_tag['datetime'])
                if parsed:
                    pub_date = parsed
                    break

        # ── RRA 등 정부 게시판: 본문이 table 구조 → trafilatura 우선 ──
        #    (일반 'article' 셀렉터가 페이지 전체 네비게이션을 잡는 문제 회피)
        if 'rra.go.kr' in url:
            try:
                import trafilatura
                _ex = trafilatura.extract(resp.text, include_comments=False, include_tables=True)
                if _ex and len(_ex.strip()) > 50:
                    return _ex.strip()[:1500], pub_date
            except Exception:
                pass

        # ── 본문 추출 ───────────────────────────────────────
        # 네이버 뉴스 URL 감지 → 전용 셀렉터 우선 적용
        naver_selectors = []
        if 'naver.com' in url:
            naver_selectors = [
                'div#dic_area',
                'div.newsct_article',
                'div#articleBodyContents',
                'div._article_body_contents',
                'div.article_body',
            ]

        selectors_map = {
            '국립전파연구원': ['div.bbs_view_cont', 'td.cont', 'div.memo', 'div.bbs_cont',
                              'div.board_view_txt', 'div.view_area', 'table.bbs_view td:last-child',
                              'div.board_view', 'div.view_content', 'td.view_cont'],
            '전자신문':    ['div.article_body', 'div#articleBody', 'div.news_view', 'div#articleView'],
            '연합뉴스':    ['div.article-txt', 'article.story-news', 'div#articleWrap'],
            '디지털타임스': ['div#article_txt', 'div.article_content', 'div#articleBody'],
            'ZDNet Korea': ['div#article_body', 'div.article_view', 'div#articleContent',
                            'div.article_content', 'div.view_txt', 'div#article-view-content-div'],
            '아이뉴스24':  ['div#news_body_area', 'div.article_txt', 'div#articleBody'],
            '매일경제':    ['div#article_body', 'div.art_txt', 'div#newsDetailBody',
                            'div.article_wrap', 'div#article-body'],
            '머니투데이':  ['div#textBody', 'div.news_text', 'div#content_text'],
            '디지털데일리': ['div#articleBody', 'div.article_txt'],
            '지디넷코리아': ['div#article_content', 'div.article_view'],
            '블로터':      ['div.article_content'],
            '한국경제':    ['div#articalbody', 'div.article-body', 'div#articleBody',
                            'div.article_body', 'div#newsView', 'div.news-contents'],
            '파이낸셜뉴스': ['div#article_content', 'div.article_view', 'div#articleBody'],
            '뉴스1':       ['div.article-body', 'div#articleBody', 'div.news_body_area'],
            '정보통신신문': ['div#article_body', 'div.article-content', 'div.view_cont'],
            'Telecom Reseller': ['div.entry-content', 'article', 'div.post-content'],
        }
        # 소스 라벨이 '국립전파연구원 공지사항'처럼 접미사를 가질 수 있어 부분 매칭
        src_selectors = selectors_map.get(source, [])
        if not src_selectors and source:
            for _key, _sels in selectors_map.items():
                if _key in source:
                    src_selectors = _sels
                    break
        candidates = naver_selectors + src_selectors + [
            'article', 'div.article', 'div.news-content',
            'div.view_cont', 'div.view-content', 'div#content',
            'div.article-body', 'div.news_body', 'div.article_txt'
        ]
        # 정부 사이트 nav 텍스트 판별 (주메뉴 등으로 시작하면 nav 영역)
        NAV_STARTS = ('주메뉴', '메뉴건너뛰기', 'Skip Navigation', '본문 바로가기')
        def _is_nav(text: str) -> bool:
            return any(text.startswith(s) for s in NAV_STARTS)

        body = ''
        for sel in candidates:
            tag = soup.select_one(sel)
            if tag:
                text = tag.get_text(separator=' ', strip=True)
                if len(text) > 100 and not _is_nav(text):
                    body = text[:1500]
                    break

        # 셀렉터 미매칭 시 trafilatura 폴백
        if not body:
            try:
                import trafilatura
                extracted = trafilatura.extract(resp.text, include_comments=False, include_tables=False)
                if extracted and len(extracted.strip()) > 100 and not _is_nav(extracted.strip()):
                    body = extracted.strip()[:1500]
            except Exception:
                pass

        return body, pub_date
    except Exception as e:
        print(f'  [본문 수집 실패] {url}: {e}')
        return '', ''


# ═══════════════════════════════════════════════════════
#  관련성 1차 선별 — Claude Haiku (2026-08-03)
#
#  검색어를 넓히면서 제목 키워드 게이트를 없앴으므로, 무관 기사가 그대로 들어와
#  본문 수집(건당 1초 대기 + HTTP)과 긴급도 분류(건당 Haiku 1콜)를 낭비하게 된다.
#  그래서 신규 기사만 모아 제목+요약으로 배치 판정하고, 통과분만 뒤 단계로 보낸다.
#  보도자료(press_ingest)·국회 입법예고(assembly_crawler)가 쓰는 것과 같은 패턴이다.
#
#  fail-open 원칙: 키 없음·판정 실패 시 기존 RADIO_KEYWORDS 키워드 필터로 되돌아간다
#  (선별이 죽었다고 수집 자체가 멈추면 무음 누락이 된다 — 배경역사 #39).
# ═══════════════════════════════════════════════════════

SCREEN_BATCH_SIZE = 35          # 1콜당 판정 기사 수 (제목+요약 300자 기준 ≈ 3~4K 입력토큰)
SCREEN_MODEL = 'claude-haiku-4-5-20251001'

# 판정 기준문 폴백 — 원본은 app_config.news_relevance_criteria
NEWS_RELEVANCE_CRITERIA_FALLBACK = (
    '다음 뉴스 기사가 SK텔레콤 Comm센터 기술정책팀(전파·통신 정책 모니터링) 업무와 '
    '관련 있는지 판정한다.\n'
    '관련 있음: 이동통신(5G·6G·주파수·기지국·단말·로밍·위성통신·통신장비), '
    '전파(전자파·무선국·무선설비·적합성평가·전파사용료·전파간섭), '
    '통신사업 정책·규제(전기통신사업법·통신요금·이용자보호·알뜰폰·스팸·번호이동·단말기유통), '
    '통신품질·통신장애·통신재난·재난문자, 네트워크 인프라(데이터센터·클라우드 포함), '
    '통신망 사이버보안·개인정보·위치정보, ITU·WRC 등 국제 전파·표준 동향, '
    '유료방송·OTT·망 사용료 정책, AI 정책(AI 기본법·규제·국가전략·AI 데이터센터·AI 반도체), '
    '과기정통부·방송미디어통신위원회·국립전파연구원·중앙전파관리소 등 소관 부처의 '
    '통신·전파 정책 발표와 인사.\n'
    '관련 없음: 스포츠·연예·부동산·주식 등 타 분야, 통신과 무관한 기업 실적·마케팅·제휴 홍보, '
    '단말기 신제품 리뷰·개통 이벤트 등 소비자 판촉, 과학관 전시·공모전·행사 홍보, 채용 공고, '
    '신약·바이오, 우주발사체·천문, 통신과 무관한 순수 과학 R&D 성과 홍보.\n'
    '애매하면 관련으로 판정한다(놓침보다 과잉 포함이 낫다).'
)

# 분야 태그 6종 — ASCII slug(토큰 절약). 한글 라벨 매핑은 Edge 쪽이 담당하며
# 원본은 supabase/functions/_shared/news_tags.ts 다. 여기는 사본이므로 같이 고칠 것.
# 태그 목록을 app_config로 빼지 않는 이유: Haiku 프롬프트·Edge 칩·웹훅 버튼 3곳이
# 동시에 바뀌어야 유효한데, 한 곳만 DB로 튜닝 가능하게 하면 드리프트만 생긴다.
NEWS_TAGS = ('spectrum', 'market', 'regulation', 'security', 'ai')
MAX_TAGS_PER_ITEM = 3           # 경계 기사도 3개면 충분 — 그 이상은 사실상 미판정

NEWS_SCREEN_TOOL = {
    'name': 'record_relevant_news',
    'description': '기사 목록 중 기준문에 따라 관련으로 판정된 기사의 id와 분야 태그를 기록한다.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'relevant': {
                'type': 'array',
                'description': '관련 기사 목록. 관련이 하나도 없으면 빈 배열.',
                'items': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer', 'description': '관련 기사의 id.'},
                        'tags': {
                            'type': 'array',
                            'description': '분야 태그 0~3개. 확실하지 않으면 빈 배열.',
                            'items': {'type': 'string', 'enum': list(NEWS_TAGS)},
                        },
                    },
                    # tags는 일부러 required에서 뺀다 — 모델이 빼먹어도 관련성 판정은 살아야 한다.
                    'required': ['id'],
                },
            },
        },
        'required': ['relevant'],
    },
}


def load_news_criteria() -> str:
    """app_config.news_relevance_criteria 판정 기준문 조회. 없거나 실패면 코드 폴백."""
    try:
        rows = sb.table('app_config').select('value') \
            .eq('key', 'news_relevance_criteria').limit(1).execute().data
        if rows and (rows[0].get('value') or '').strip():
            return rows[0]['value'].strip()
    except Exception as e:
        print(f'[선별] 판정기준 조회 실패 — 코드 폴백 사용: {str(e)[:80]}')
    return NEWS_RELEVANCE_CRITERIA_FALLBACK


def _screen_text_of(item: dict) -> str:
    """판정 재료 — 수집 시 담아 둔 요약(_screen_text), 없으면 content 앞부분."""
    txt = (item.get('_screen_text') or item.get('content') or '')
    return re.sub(r'\s+', ' ', txt).strip()[:300]


def _keyword_relevant(item: dict) -> bool:
    """폴백 판정 — 종전 수집 기준(제목에 RADIO_KEYWORDS 포함)과 동일."""
    return any(k in (item.get('title') or '') for k in RADIO_KEYWORDS)


def _screen_batch_haiku(client, criteria: str, batch: list):
    """배치 1개(≤SCREEN_BATCH_SIZE건)를 Haiku 1콜로 판정.
    반환: {관련 id(1-based): 분야 태그 list}. 실패 시 None.
    None은 '판정 실패' 신호이고 호출부의 키워드 폴백이 여기 물려 있다 — 의미를 바꾸지 말 것.
    태그는 NEWS_TAGS 화이트리스트 교집합·최대 MAX_TAGS_PER_ITEM개로 자른다
    (모델이 없는 slug를 지어내도 DB·Edge로 새어 나가지 않게).
    결정성: tool_choice로 도구 호출 강제 + 기준문 문자 적용·건별 독립 판정 지시.
    (temperature류 파라미터 사용 금지 — 지침 do-not)"""
    payload = []
    for idx, it in enumerate(batch, 1):
        row = {'id': idx, 'title': (it.get('title') or '').strip()}
        summary = _screen_text_of(it)
        if summary:
            row['summary'] = summary
        payload.append(row)
    prompt = (
        '아래는 방금 수집한 뉴스 기사 목록이다.\n'
        '판정 규칙:\n'
        '1. 각 기사를 목록 내 다른 기사·순서와 무관하게 한 건씩 독립적으로 판정하라.\n'
        '2. 시스템 지시의 기준문을 문자 그대로 적용하라. 기준문에 없는 근거로 추측하지 말라.\n'
        '3. 관련/무관이 애매하면 관련으로 판정하라(놓침보다 과잉 포함이 낫다).\n'
        '4. 관련으로 판정한 기사에는 분야 태그를 붙여라. 태그는 아래 6종뿐이다.\n'
        '   - spectrum: 주파수 할당·재할당, 무선국·기지국, 전자파, 비면허 대역, '
        '통신망 구축·투자·품질·장애, 해저케이블, 규제 대상 통신시설(집적정보통신시설 보호조치·IDC 장애)\n'
        '   - market: 요금제, 알뜰폰·도매대가, 번호이동, 단말 유통·보조금, 결합상품\n'
        '   - regulation: 과징금·시정명령, 인허가·심사, 표시·광고, 약관, 이용자보호\n'
        '   - security: 해킹·유출, ISMS, 개인정보위 처분, 위치정보, 통신시설 보호조치\n'
        '   - ai: AI 기본법·규제, 국가 AI 전략, AI 데이터센터 정책(전력 특례·입지 규제 등)\n'
        '   태그는 기사 제목에 나온 단어가 아니라 기사가 다루는 사안을 기준으로 고른다. '
        '한 기사가 여러 사안을 다루면 해당 태그를 모두 붙인다(최대 3개). '
        '5종 중 어느 것도 확실하지 않으면 tags를 비워 둔다 — 억지로 채우지 말라.\n'
        '관련으로 판정된 기사만 record_relevant_news 도구의 relevant 배열에 '
        '{id, tags} 형태로 기록하라. 관련이 하나도 없으면 빈 배열을 기록하라.\n\n'
        + json.dumps(payload, ensure_ascii=False)
    )
    try:
        resp = client.messages.create(
            model=SCREEN_MODEL,
            # 3000: 35건 전건 태그 시 출력 ≈1,000토큰. 여유 1.5배로는 부족하다 —
            # 초과하면 tool_use가 미완성으로 잘려 None(판정 실패) → 배치 전체 키워드 폴백,
            # 즉 조용한 리콜 손실이 된다. 입력이 아니라 출력 한도라 비용 영향도 없다.
            max_tokens=3000,
            system=criteria,
            tools=[NEWS_SCREEN_TOOL],
            tool_choice={'type': 'tool', 'name': 'record_relevant_news'},
            messages=[{'role': 'user', 'content': prompt}],
        )
        for blk in resp.content:      # 적응형 추론 대비 — tool_use 블록만 취함
            if getattr(blk, 'type', '') == 'tool_use':
                rows = (blk.input or {}).get('relevant') or []
                out = {}
                for row in rows:
                    # 모델이 {id, tags} 대신 정수만 뱉어도 관련성 판정은 살린다(태그만 비움).
                    if isinstance(row, dict):
                        raw_id, raw_tags = row.get('id'), row.get('tags')
                    else:
                        raw_id, raw_tags = row, None
                    try:
                        rid = int(raw_id)
                    except (TypeError, ValueError):
                        continue
                    tags = []
                    for t in (raw_tags or []):
                        if t in NEWS_TAGS and t not in tags:
                            tags.append(t)
                        if len(tags) >= MAX_TAGS_PER_ITEM:
                            break
                    out[rid] = tags
                return out
        return None                   # 도구 호출 없음 → 실패 취급(호출부가 키워드 폴백)
    except Exception as e:
        print(f'  [선별 판정 오류] {str(e)[:120]}')
        return None


# 주파수 안전망 — 이 네 단어가 제목·요약에 있으면 spectrum을 '추가'한다.
# 태그 판정은 여전히 Haiku가 하고, 이건 바닥(안전망)이지 대체가 아니다:
#   · 추가만 한다. Haiku가 붙인 태그는 절대 지우지 않는다.
#   · 네 단어로만 좁힌다. 늘리면 결국 키워드 대응표가 되고, 그러면 "기지국 개설허가"와
#     "기지국 투자 축소"가 같은 태그를 받는 문제로 되돌아간다(그걸 피하려고 LLM 판정을 쓴다).
# 도입 근거(2026-08-03 실측): 「과기정통부, 이동통신 무선국 검사 간소화한다」가 3회 연속 태그 0개로
# 나왔다. 요약에 무선국·기지국·안테나·전파법이 다 있는데도 AI가 '행정절차 개정'으로 읽어
# "확실하지 않으면 비워 둬라" 지시에 따라 비운 것. 같은 사안의 다른 기사들은 정상 판정돼서
# 프롬프트 문제라기보다 경계 사례로 보이나, 전파법은 이 팀의 핵심 법이라 놓치면 손해가 크다.
_SPECTRUM_ANCHORS = ('전파법', '무선국', '주파수 할당', '주파수 재할당', '전자파')


def _spectrum_safety_net(item: dict) -> None:
    """앵커 단어가 있는데 spectrum이 빠졌으면 추가한다(추가 전용). 발동 시 로그를 남긴다 —
    로그가 잦아지면 안전망이 아니라 프롬프트를 고쳐야 한다는 신호다."""
    tags = item.get('tags')
    if not isinstance(tags, list) or 'spectrum' in tags:
        return
    text = f"{item.get('title', '')} {item.get('_screen_text', '')}"
    hit = next((a for a in _SPECTRUM_ANCHORS if a in text), None)
    if hit:
        tags.append('spectrum')
        print(f"  [태그 보정] '{hit}' → spectrum 추가: {str(item.get('title'))[:44]}")


def screen_news_items(items: list) -> list:
    """수집분에서 SKT 관련 기사만 남긴다. 반환 목록은 입력 순서를 유지한다.

    - 소관 부처 인사 뉴스(is_ministry_personnel_news)는 판정 없이 무조건 통과 (지침 do-not).
    - ANTHROPIC_API_KEY 없음/클라이언트 생성 실패 → 전량 키워드 폴백.
    - 배치 단위 실패 → 그 배치만 키워드 폴백 (다른 배치 판정은 유지).
    - 판정에만 쓰는 '_screen_text' 키는 여기서 전부 제거한다 (DB 컬럼이 아님).
    - 분야 태그(news_feed.tags)를 같이 매긴다. 판정을 못 받은 경로(인사 자동통과·키워드
      폴백·모델이 tags 생략)는 빈 배열 []이며, 그 보장은 함수 끝의 setdefault 한 곳에 건다.
    """
    if not items:
        return []

    keep = [False] * len(items)
    personnel = 0
    cand_idx = []
    for n, it in enumerate(items):
        if is_ministry_personnel_news(it.get('title', '')):
            keep[n] = True            # 부처 인사 뉴스 — 항상 수집
            personnel += 1
        else:
            cand_idx.append(n)

    client = None
    criteria = ''
    if cand_idx and ANTHROPIC_API_KEY:
        try:
            criteria = load_news_criteria()
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        except Exception as e:
            print(f'[선별] Haiku 초기화 실패: {str(e)[:80]}')
            client = None
    if cand_idx and client is None:
        print(f'[선별] AI 판정 불가 — RADIO_KEYWORDS 키워드 폴백 ({len(cand_idx)}건)')

    n_batches = (len(cand_idx) + SCREEN_BATCH_SIZE - 1) // SCREEN_BATCH_SIZE
    for i in range(0, len(cand_idx), SCREEN_BATCH_SIZE):
        chunk = cand_idx[i:i + SCREEN_BATCH_SIZE]
        batch = [items[n] for n in chunk]
        verdict = _screen_batch_haiku(client, criteria, batch) if client else None
        if verdict is None:
            if client:
                print(f'  [선별 배치 {i // SCREEN_BATCH_SIZE + 1}/{n_batches} 실패] '
                      f'키워드 폴백({len(batch)}건)')
            for n, it in zip(chunk, batch):
                keep[n] = _keyword_relevant(it)
        else:
            for pos, n in enumerate(chunk, 1):
                tags = verdict.get(pos)     # None = 이 배치에서 무관 판정
                if tags is not None:
                    keep[n] = True
                    items[n]['tags'] = tags

    passed  = [it for n, it in enumerate(items) if keep[n]]
    dropped = [it for n, it in enumerate(items) if not keep[n]]
    print(f'[선별] 수집 {len(items)}건 → 관련 {len(passed)}건 '
          f'(제외 {len(dropped)}건, 인사 자동통과 {personnel}건)')
    for it in dropped[:5]:            # 기준문 조정용 표본 — 제외 사유 감시
        print(f'  [제외] {(it.get("title") or "")[:50]}')

    # 임시 키 제거(_screen_text는 DB 컬럼이 아니다) + tags 기본값 보장.
    # ★ tags setdefault는 반드시 이 한 지점에만 둘 것 ★
    #   PostgREST 벌크 upsert는 리스트 안 모든 객체의 키 집합이 같아야 한다. save_new_items가
    #   valid 리스트를 통째로 넘기므로, 태그 없는 경로(키워드 폴백 / 부처 인사 자동통과 /
    #   모델이 tags 생략) 중 하나라도 키가 빠지면 upsert 전체가 터져 뉴스 수집이 전면 중단된다.
    #   통과 기사는 전부 이 루프를 지나므로 여기가 유일한 방어선이다.
    #   '기타' 태그를 만들지 말 것 — 구독자가 그것을 끌 수 있게 되어 판정 실패 기사가 조용히 사라진다.
    for it in items:
        it.setdefault('tags', [])         # 반드시 안전망보다 먼저 — 태그가 없는 기사가 바로 보정 대상이다
        _spectrum_safety_net(it)          # 판정 누락 보정 — 아래 함수 주석 참조
        it.pop('_screen_text', None)      # 보정이 _screen_text를 읽으므로 제거는 마지막
    return passed


# ═══════════════════════════════════════════════════════
#  Supabase 저장
# ═══════════════════════════════════════════════════════

def save_new_items(items: list, existing_data: tuple) -> list:
    """규칙1: 15일 이내 & 날짜 확인된 신규 기사만 저장
    existing_data: (existing_urls: set, existing_titles: set)
    URL + 제목 이중 중복 체크 (Google RSS 리다이렉트 URL 대응)

    순서(2026-08-03 재배치): 중복 제거 → ①조기 날짜 필터 → ②Haiku 관련성 선별
    → ③본문 수집 → ④날짜 필터 → ⑤긴급도 분류 → 저장.
    본문 수집·긴급도 분류는 선별 통과분에만 돈다(둘 다 건당 비용이 큰 단계).
    """
    existing_urls, existing_titles = existing_data
    now_kst = datetime.now(KST)
    cutoff_72h = now_kst - timedelta(days=15)   # 저장 기준: 15일 이내
    seen_urls   = set(existing_urls)
    seen_titles = set(existing_titles)
    unique_new = []
    for item in items:
        url   = item.get('url', '')
        title = item.get('title', '')
        # URL 중복 체크
        if url and url in seen_urls:
            continue
        # 제목 중복 체크 (Google RSS ↔ 직접 크롤링 간 같은 기사 방지)
        if title and title in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title)
        # # 으로 시작하는 제목(태그/토픽 페이지) 제외
        if title.startswith('#'):
            continue
        unique_new.append(item)

    if not unique_new:
        print('[저장] 신규 항목 없음')
        return []

    # ① 조기 날짜 필터 — 발행일이 이미 확정된 오래된 기사는 선별·본문 수집 전에 뺀다.
    #    (뒤의 ④ 필터와 기준은 같다. 판정·본문 토큰을 어차피 버릴 기사에 쓰지 않으려는 것)
    #    발행일 불명분은 본문 수집이 날짜를 채울 수 있으므로 여기서 버리지 않는다.
    fresh, stale_old = [], 0
    for item in unique_new:
        pub = item.get('published_at', '')
        if pub:
            try:
                from dateutil import parser as _dtp0
                pub_dt0 = _dtp0.parse(pub)
                if pub_dt0.tzinfo is None:
                    pub_dt0 = pub_dt0.replace(tzinfo=KST)
                if pub_dt0 < cutoff_72h:
                    stale_old += 1
                    continue
            except Exception:
                pass      # 파싱 실패는 통과 — 뒤의 정식 필터가 처리
        fresh.append(item)
    if stale_old:
        print(f'[필터] {stale_old}건 15일 초과 — 선별 전 제외')
    unique_new = fresh
    if not unique_new:
        print('[저장] 유효한 신규 항목 없음')
        return []

    # ② 관련성 1차 선별 (Haiku) — 통과분만 본문 수집·긴급도 분류로 넘긴다.
    #    제외분은 저장하지 않는다. 저장해 두면 대시보드·RAG·브리핑 모집단이 그대로 오염되고,
    #    url UNIQUE 때문에 나중에 되살리기도 어렵다. 놓침이 걱정되면 기준문(app_config)을
    #    고치는 쪽이 맞다 — 제외 표본은 위 로그에 남는다.
    unique_new = screen_news_items(unique_new)
    if not unique_new:
        print('[저장] 선별 통과 항목 없음')
        return []

    # ③ 본문 수집 및 발행일 확정
    # GitHub Actions(미국 IP)에서는 한국 뉴스 사이트 차단 → RSS 요약만 저장
    # PC에서 실행 시 fetch_article_body로 전체 본문 수집
    if IS_GITHUB_ACTIONS:
        print(f'[본문 수집] GitHub Actions 환경 — RSS 요약 저장 후 PC refetch 위임')
        for item in unique_new:
            item['content_fetched_at'] = now_kst.isoformat()
            if not item.get('published_at'):
                item['published_at'] = ''
    else:
        print(f'[본문 수집] PC 환경 — {len(unique_new)}건 본문 직접 수집 시작...')
        for item in unique_new:
            if item.get('url'):
                body, article_date = fetch_article_body(item['url'], item.get('source', ''))
                item['content'] = body if body else item.get('content')
                item['content_fetched_at'] = now_kst.isoformat()
                current_pub = item.get('published_at', '')
                if not current_pub and article_date:
                    item['published_at'] = article_date
                    print(f'  [날짜보정] {item.get("title","")[:30]}... → {article_date}')
                elif not current_pub:
                    item['published_at'] = ''
                time.sleep(1)

    # ④ 72시간 초과 또는 발행일 불명 제외 (규칙1)
    valid, skipped_unknown, skipped_old = [], 0, 0
    for item in unique_new:
        pub = item.get('published_at', '')
        if not pub:
            skipped_unknown += 1
            continue
        try:
            from dateutil import parser as _dtp
            pub_dt = _dtp.parse(pub)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=KST)
            if pub_dt < cutoff_72h:
                skipped_old += 1
                continue
        except Exception:
            skipped_unknown += 1
            continue
        valid.append(item)

    if skipped_unknown:
        print(f'[필터] {skipped_unknown}건 발행일 불명 — 제외')
    if skipped_old:
        print(f'[필터] {skipped_old}건 15일 초과 — 제외')
    if not valid:
        print('[저장] 유효한 신규 항목 없음')
        return []

    # ⑤ 긴급도 분류 — 선별 통과분에만 돈다 (건당 Haiku 1콜)
    for item in valid:
        val = classify_urgency(item.get('title', ''), item.get('content', '') or '')
        item['urgency'] = val
        item['importance'] = val

    try:
        # upsert(on_conflict=url, ignore_duplicates): 크롤러 동시 실행 시
        # 같은 기사 중복 저장 방지 (idx_news_feed_url_unique와 한 쌍)
        sb.table('news_feed').upsert(
            valid, on_conflict='url', ignore_duplicates=True
        ).execute()
    except Exception as e:
        print(f'[저장 오류] Supabase upsert 실패: {e}')
        return []
    urgent_count = sum(1 for i in valid if i.get('urgency') == '긴급')
    print(f'[저장] {len(valid)}건 저장 완료 (긴급 {urgent_count}건)')
    return valid


# ═══════════════════════════════════════════════════════
#  기술 용어 추출 — Claude API (매일 08:00)
# ═══════════════════════════════════════════════════════

_TERM_SYSTEM = """당신은 이동통신·전파 분야 기술 용어 추출 전문가입니다.
아래 뉴스 목록에서 신규 전문 기술 용어를 추출하여 JSON 배열로만 반환하세요.

추출 기준 (반드시 준수):
✅ 포함: 국제 표준 번호(IEEE 802.11be), 프로토콜명(NR-U), 기술 약어(NTN, HAPS, RIS), 주파수 대역명(FR3, sub-THz)
❌ 제외: 기술 약어 뒤에 시장/동향/경쟁/산업/전략/분야/서비스/플랫폼이 붙은 복합어
❌ 제외: 요금제·상품명(5G-LTE 통합요금제, AI 토큰요금제 등)
❌ 제외: 정책·제도·전략명(최적요금제 고지 제도, 하이퍼 AI네트워크 전략 등)
❌ 제외: 흔한 용어(5G, LTE, Wi-Fi, AI, IoT 등)
❌ 제외: 이미 알려진 기술의 동의어·변형(Wi-Fi 7 있으면 와이파이7 제외)
❌ 제외: 스포츠·연예·부동산 등 이동통신·전파와 무관한 분야의 용어 (예: 연속 선발, 홈런, 득점 등)

출력 형식 (JSON 배열, 다른 말 없이):
[{"term":"용어","term_en":"English Name","category":"주파수|네트워크|위성|단말|규제|기타","definition":"50자 이내 정의","source":"출처 언론사"}]
신규 용어가 없으면 빈 배열 [] 반환."""


def extract_tech_terms(items: list) -> list:
    """뉴스 기사 목록에서 신규 기술 용어 추출 후 tech_terms 테이블에 저장."""
    if not ANTHROPIC_API_KEY or not items:
        return []

    # 기존 용어 목록 조회 (정규화 중복 방지: 공백 제거 + 소문자)
    def _norm(s: str) -> str:
        return re.sub(r'\s+', '', s).lower()

    try:
        existing = sb.table('tech_terms').select('term').execute()
        existing_terms = {_norm(r['term']) for r in (existing.data or [])}
    except Exception as e:
        print(f'[용어] 기존 목록 조회 실패: {e}')
        existing_terms = set()

    # 기사 목록 텍스트 구성 (제목 + 출처)
    news_text = '\n'.join(
        f"- {it.get('title','')} ({it.get('source','')})"
        for it in items[:60]
    )
    existing_text = ', '.join(sorted(existing_terms)[:80]) if existing_terms else '없음'
    user_msg = f"이미 등록된 용어(제외 대상):\n{existing_text}\n\n뉴스 목록:\n{news_text}"

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=1000,
            system=_TERM_SYSTEM,
            messages=[{'role': 'user', 'content': user_msg}],
        )
        raw = resp.content[0].text.strip()
        import json
        # JSON 배열 추출
        start = raw.find('[')
        end = raw.rfind(']') + 1
        if start == -1 or end == 0:
            return []
        terms = json.loads(raw[start:end])
        if not terms:
            print('[용어] 신규 용어 없음')
            return []

        # 중복 제거 후 저장 (정규화 비교: 공백 제거 + 소문자)
        new_terms = [
            t for t in terms
            if isinstance(t, dict) and t.get('term')
            and _norm(t['term']) not in existing_terms
        ]
        if new_terms:
            rows = [{
                'term': t.get('term', ''),
                'term_en': t.get('term_en', ''),
                'category': t.get('category', '기타'),
                'definition': t.get('definition', '')[:100],
                'source': t.get('source', '자동 추출'),
                'is_reviewed': False,
            } for t in new_terms]
            sb.table('tech_terms').insert(rows).execute()
            print(f'[용어] 신규 {len(new_terms)}건 저장: {[t["term"] for t in new_terms]}')
            # 저장 즉시 상세 설명·다이어그램 자동 생성 (대시보드 첫 클릭 대기 제거)
            generate_term_descriptions(new_terms)
        return new_terms
    except Exception as e:
        print(f'[용어 추출 오류] {e}')
        return []


def generate_summary(title: str, source: str, published_at: str, content: str) -> str:
    """기사 본문을 Claude Haiku로 요약해 반환. 실패 시 빈 문자열."""
    if not ANTHROPIC_API_KEY or not content:
        return ''
    body_snippet = content.replace('\n', ' ').strip()[:3000]
    user_msg = (
        '다음 뉴스를 핵심 포인트 3~5개로 요약하세요.\n'
        '- 각 포인트를 줄바꿈으로 구분하세요.\n'
        '- 각 포인트는 1~2문장, 육하원칙(누가/무엇을/왜/어떻게) 포함.\n'
        '- 불릿 기호(•, -, * 등)는 붙이지 마세요. 순수 텍스트만.\n\n'
        f'제목: {title}\n출처: {source}\n날짜: {str(published_at)[:10]}\n\n본문:\n{body_snippet}'
    )
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=500,
            system='당신은 전파·통신 정책 뉴스를 간결하게 요약하는 전문가입니다. 사실만 기반으로 핵심 포인트를 줄바꿈으로 구분하여 작성하세요. 불릿 기호 없이 텍스트만 출력하세요.',
            messages=[{'role': 'user', 'content': user_msg}]
        )
        return (resp.content[0].text or '').strip() if resp.content else ''
    except Exception as e:
        print(f'[요약 오류] {title[:30]}: {e}')
        return ''


def generate_term_descriptions(new_terms: list):
    """신규 기술 용어의 상세 설명·SVG 다이어그램·관련 용어를 Claude로 생성 후 DB 저장."""
    if not new_terms or not ANTHROPIC_API_KEY:
        return
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    for t in new_terms:
        term      = t.get('term', '')
        term_en   = t.get('term_en', '')
        category  = t.get('category', '기타')
        definition = t.get('definition', '')
        if not term:
            continue
        term_label = term + (f' ({term_en})' if term_en else '')
        system_msg = '당신은 이동통신·전파 정책 전문가입니다. 반드시 지정된 XML 태그 형식으로만 답변하세요.'
        user_msg = (
            f'기술 용어 [{term_label}] 에 대해 아래 형식으로 정확히 답변하세요.\n'
            f'분야: {category}. 현재 정의: {definition or "없음"}.\n\n'
            '<description>\n'
            '3~5문단 상세 설명. **굵은글씨**로 핵심 개념 강조. 단락 구분은 빈 줄로.\n'
            '내용: 개념 배경/기술 원리/국내외 현황/관련 표준 순서로 서술.\n'
            '</description>\n\n'
            '<diagram>\n'
            '아래 조건을 모두 지킨 SVG를 생성하라:\n'
            '- viewBox="0 0 680 320" xmlns="http://www.w3.org/2000/svg"\n'
            '- 배경: rect fill="#f8fafc" 전체 채움\n'
            '- 한국어 레이블 사용, font-family="sans-serif"\n'
            '- 주요 구성요소를 박스/원/화살표로 시각화 (최소 4개 요소)\n'
            '- 색상: 주요 박스 #6366f1(보라), 보조 #10b981(초록), 강조 #f59e0b(노랑), 배경박스 #e0e7ff\n'
            '- 화살표는 marker-end 사용하여 방향 표시\n'
            '- 개념 흐름이나 계층 구조를 한눈에 파악할 수 있게\n'
            '</diagram>\n\n'
            '<related>관련용어1,관련용어2,관련용어3</related>'
        )
        try:
            resp = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=4000,
                system=system_msg,
                messages=[{'role': 'user', 'content': user_msg}]
            )
            text = resp.content[0].text if resp.content else ''
            desc_match  = re.search(r'<description>([\s\S]*?)</description>', text)
            diag_match  = re.search(r'<diagram>([\s\S]*?)</diagram>', text)
            rel_match   = re.search(r'<related>([\s\S]*?)</related>', text)
            update_data: dict = {}
            if desc_match:
                update_data['description'] = desc_match.group(1).strip()
            if diag_match:
                update_data['diagram_html'] = diag_match.group(1).strip()
            if rel_match:
                update_data['related_terms'] = [
                    s.strip() for s in rel_match.group(1).split(',') if s.strip()
                ]
            if update_data:
                sb.table('tech_terms').update(update_data).eq('term', term).execute()
                print(f'[용어 설명] {term} 자동 생성 완료')
        except Exception as e:
            print(f'[용어 설명 오류] {term}: {e}')


# ═══════════════════════════════════════════════════════
#  브리핑 생성 — Claude API + Supabase 저장 (매일 08:00)
# ═══════════════════════════════════════════════════════

_BRIEFING_SYSTEM = """당신은 SK텔레콤 Comm센터 기술정책팀의 전파정책 모닝 브리핑 작성 AI입니다.
제공된 뉴스 목록과 신규 기술 용어를 바탕으로 간결하고 실용적인 브리핑을 작성하세요.

작성 규칙:
- [주요 뉴스]는 제공된 기사에서만 선별 (최대 8건, 긴급·중요 기사 우선)
- 같은 사건·주제를 다룬 기사가 여러 건일 경우 가장 중요한 1건만 선별 (중복 주제 제외)
- [주목 포인트]는 SKT Comm센터 정책·기술 관점에서 핵심 이슈 1~3개 도출
- 반드시 제공된 본문 내용에 근거해서만 요약 작성 — 추측·외부 지식 금지
- 각 뉴스에 본문 기반 한 줄 요약 포함

출력 형식 (아래 형식 그대로, ID 필드 반드시 포함):
📡 전파정책 모닝 브리핑 — {날짜}

[주요 뉴스]
• 제목 — 출처 [ID:기사id]
  → 한 줄 요약 (본문 근거)
  🔗 URL

[주목 포인트]
• 핵심 이슈 1
• 핵심 이슈 2

[새로 추가된 기술 용어]
• 용어: 정의

[저장 결과]
뉴스 N건 / 기술 용어 N건"""


def generate_daily_briefing(items: list, new_terms: list) -> str:
    """Claude API로 브리핑 텍스트 생성 후 daily_briefings 테이블에 저장.
    - 본문(content) 없는 기사는 브리핑에서 제외
    - 브리핑에 포함된 기사의 한 줄 요약을 news_feed.summary에 역저장
    """
    # ① 본문 있는 기사만 브리핑 대상
    valid_items = [it for it in items if it.get('content') and len(it['content'].strip()) > 50]
    if not valid_items:
        print('[브리핑] 본문 확인된 기사 없음 — 건너뜀')
        return ''

    print(f'[브리핑] 본문 확인 기사 {len(valid_items)}건 / 전체 {len(items)}건')
    today_str = datetime.now(KST).strftime('%Y년 %m월 %d일')

    # ② 기사 목록 구성 (본문 포함, ID 포함)
    news_lines = []
    for it in valid_items[:50]:
        urgency_icon = {'긴급': '🔴', '보통': '🟡', '참고': '🟢'}.get(it.get('urgency', '참고'), '🟢')
        body_snippet = (it.get('content') or '').replace('\n', ' ').strip()[:400]
        news_lines.append(
            f"{urgency_icon} {it.get('title','')} — {it.get('source','')} [ID:{it.get('id','')}]\n"
            f"   URL: {it.get('url','')}\n"
            f"   발행: {str(it.get('published_at',''))[:10]}\n"
            f"   본문: {body_snippet}"
        )

    # ③ 신규 용어 목록
    term_lines = '\n'.join(
        f"- {t.get('term','')}: {t.get('definition','')}"
        for t in new_terms
    ) if new_terms else '신규 용어 없음'

    user_msg = (
        f"날짜: {today_str}\n\n"
        f"[브리핑 대상 뉴스 {len(valid_items)}건 — 본문 확인된 기사만]\n"
        + '\n'.join(news_lines)
        + f"\n\n[오늘 신규 추출된 기술 용어]\n{term_lines}"
    )

    briefing_text = ''
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=2500,
            system=_BRIEFING_SYSTEM,
            messages=[{'role': 'user', 'content': user_msg}],
        )
        briefing_text = resp.content[0].text.strip()
        print(f'[브리핑] 텍스트 생성 완료 ({len(briefing_text)}자)')
    except Exception as e:
        print(f'[브리핑 생성 오류] {e}')
        return ''

    # ④ daily_briefings 저장 (날짜 충돌 시 덮어쓰기)
    try:
        today_date = datetime.now(KST).strftime('%Y-%m-%d')
        sb.table('daily_briefings').upsert({
            'briefing_date': today_date,
            'content': briefing_text,
            'news_count': len(valid_items),
            'terms_count': len(new_terms),
        }, on_conflict='briefing_date').execute()
        print(f'[브리핑] daily_briefings 저장 완료 (뉴스 {len(valid_items)}건, 용어 {len(new_terms)}건)')
    except Exception as e:
        print(f'[브리핑 DB 저장 오류] {e}')

    # ⑤ 브리핑에 포함된 기사 한 줄 요약 → news_feed.summary 역저장
    try:
        import re as _re
        # "[ID:xxx] ... → 한 줄 요약" 패턴 파싱
        pattern = r'\[ID:([^\]]+)\].*?\n\s*→\s*(.+)'
        matches = _re.findall(pattern, briefing_text)
        backfill_count = 0
        for article_id, summary_line in matches:
            article_id = article_id.strip()
            summary_line = summary_line.strip()
            if not article_id or not summary_line:
                continue
            try:
                sb.table('news_feed').update({'summary': summary_line}).eq('id', article_id).execute()
                backfill_count += 1
            except Exception:
                pass
        if backfill_count:
            print(f'[브리핑] news_feed.summary 역저장 {backfill_count}건')
    except Exception as e:
        print(f'[브리핑 역저장 오류] {e}')

    return briefing_text


# ═══════════════════════════════════════════════════════
#  텔레그램 알림 (긴급 기사 전용)
# ═══════════════════════════════════════════════════════

def send_morning_telegram(items: list, briefing_text: str = ''):
    """아침 8시 일일 브리핑 Telegram 발송 — briefing_text 있으면 AI 브리핑 전송"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print('[텔레그램 모닝] 환경변수 미설정 — 건너뜀')
        return
    if not items and not briefing_text:
        print('[텔레그램 모닝] 신규 기사 없음 — 건너뜀')
        return

    # AI 브리핑 텍스트가 있으면 그대로 발송 (4096자 텔레그램 제한 고려)
    if briefing_text:
        text = briefing_text[:4000]
        if len(briefing_text) > 4000:
            text += '\n\n...(전문은 대시보드 참조)'
        text += '\n\n📊 https://youjinwoong.github.io/radio-policy-ai/'
    else:
        # 폴백: 원시 목록 발송
        now_str = datetime.now(KST).strftime('%Y.%m.%d')
        urgent = [i for i in items if i.get('urgency') == '긴급']
        normal = [i for i in items if i.get('urgency') == '보통']
        ref    = [i for i in items if i.get('urgency') == '참고']
        lines = [f'☀️ *[전파정책 AI] {now_str} 아침 브리핑* — {len(items)}건\n']
        for label, icon, group in [('긴급', '🔴', urgent), ('보통', '🟡', normal), ('참고', '🟢', ref)]:
            if group:
                lines.append(f'{icon} *{label} {len(group)}건*')
                for item in group[:5]:
                    lines.append(f'  · {item.get("title", "")} ({item.get("source", "")})')
                lines.append('')
        lines.append('📊 https://youjinwoong.github.io/radio-policy-ai/')
        text = '\n'.join(lines)

    # 전송부는 notify 위임 (개선⑪) — 실패 로그는 notify가 출력
    if notify.send_telegram(text, chat_id=TELEGRAM_CHAT_ID, parse_mode='Markdown',
                            disable_web_page_preview=True):
        print(f'[텔레그램 모닝] {len(items)}건 발송 완료')


def suppress_repeat_alerts(urgent_items: list) -> list:
    """같은 사건 재보도의 재알림 억제 (배경역사 #44).

    ① 최근 3일 내 이미 DB에 있던 긴급 기사와 제목 유사(공유 키워드 3+) → 억제.
       단, 국면 신호 단어(소송·고발·상고…)가 새로 등장한 제목은 통과(새 전개).
    ② 이번 실행분 안에서도 유사 기사는 대표 1건으로 묶고 '(관련 보도 N건)' 병기.
    억제 내역은 alert_suppress_log에 남긴다 — 1~2주 실측 후 Haiku 판정 층 추가 여부 결정.
    어떤 오류든 나면 원본 그대로 반환(fail-open) — 판정이 죽어서 알림까지 죽으면 안 된다."""
    if not urgent_items:
        return urgent_items
    try:
        from news_dedup import extract_keywords, is_followup, cluster_star

        # 이번 실행에서 방금 저장한 기사는 비교 대상에서 빼야 한다 (자기 자신과 비교 방지)
        batch_urls = {i.get('url') for i in urgent_items}
        cutoff_3d = (datetime.now(KST) - timedelta(days=3)).isoformat()
        prior = []
        resp = sb.table('news_feed').select('title,url') \
            .eq('urgency', '긴급').gte('created_at', cutoff_3d) \
            .order('created_at', desc=True).limit(1000).execute()
        for r in (resp.data or []):
            if r.get('url') not in batch_urls:
                prior.append({'title': r.get('title') or '', 'kw': extract_keywords(r.get('title') or '')})

        passed, sup_rows = [], []
        for it in urgent_items:
            kw = extract_keywords(it.get('title') or '')
            matched = None
            for pv in prior:
                if is_followup(kw, pv['kw'], it.get('title') or '', pv['title']):
                    matched = pv
                    break
            if matched:
                sup_rows.append({
                    'article_title': it.get('title') or '',
                    'article_url': it.get('url') or '',
                    'matched_title': matched['title'],
                    'shared_keywords': ','.join(sorted(kw & matched['kw'])),
                })
            else:
                passed.append(it)

        # 같은 실행분 내 유사 기사 묶기 — 사건 첫날 첫 실행에 재보도 수십 건이
        # 한꺼번에 들어오면 한 통에 수십 줄이 되는 것을 대표 1건으로 줄인다
        reps = []
        for rep, members in cluster_star(passed):
            rep['_related'] = len(members)
            reps.append(rep)

        if sup_rows:
            print(f'[긴급 억제] 재보도 {len(sup_rows)}건 알림 생략 (3일 내 기보도 사건과 유사)')
            try:
                sb.table('alert_suppress_log').insert(sup_rows).execute()
            except Exception as e:
                print(f'[긴급 억제] 로그 저장 실패(무시): {e}')
        merged = len(passed) - len(reps)
        if merged:
            print(f'[긴급 억제] 실행분 내 유사 {merged}건 대표에 병합')
        return reps
    except Exception as e:
        print(f'[긴급 억제] 판정 오류 → 전부 알림(fail-open): {e}')
        return urgent_items


def send_telegram(urgent_items: list):
    """긴급 기사를 Telegram Bot으로 즉시 알림"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print('[텔레그램] 환경변수 미설정 (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID) — 건너뜀')
        return
    if not urgent_items:
        return

    now_str = datetime.now(KST).strftime('%Y.%m.%d %H:%M KST')
    # HTML 조립 — 기사 원제목의 * _ [ ] ( 등이 Markdown 파싱을 깨서 400으로
    # 통째 소실되던 것을 이스케이프된 HTML로 방지 (morning_briefing.py와 동일 방식)
    import html as _html

    def _esc(s: str) -> str:
        return _html.escape(str(s), quote=False)

    lines = [f'🚨 <b>[전파정책 AI] 긴급 기사 {len(urgent_items)}건</b> — {now_str}\n']
    for i, item in enumerate(urgent_items, 1):
        title = item.get('title', '')
        source = item.get('source', '')
        url = item.get('url', '')
        rel = item.get('_related', 0)
        rel_txt = f' (관련 보도 {rel}건)' if rel else ''
        lines.append(f'<b>{i}. {_esc(title)}</b>{_esc(rel_txt)}')
        lines.append(f'   출처: {_esc(source)}')
        if url:
            # href 속성값: & → &amp;, " → &quot; (quote=True)
            lines.append(f'   🔗 <a href="{_html.escape(str(url), quote=True)}">기사 보기</a>\n')
        else:
            lines.append('')

    lines.append('📊 <a href="https://youjinwoong.github.io/radio-policy-ai/">대시보드</a>')
    text = '\n'.join(lines)

    # 전송부는 notify 위임 (개선⑪) — 실패 로그는 notify가 출력
    ok = notify.send_telegram(text, chat_id=TELEGRAM_CHAT_ID, parse_mode='HTML',
                              disable_web_page_preview=True)
    if not ok:
        # HTML 파싱 실패(400 등) 시 평문으로 재시도 — 포맷 때문에 긴급 알림 자체를
        # 잃지 않도록(fail-open, morning_briefing.py send_telegram과 동일 패턴)
        print('[텔레그램] 긴급 HTML 발송 실패 → 평문 재시도')
        plain_lines = [f'🚨 [전파정책 AI] 긴급 기사 {len(urgent_items)}건 — {now_str}\n']
        for i, item in enumerate(urgent_items, 1):
            rel = item.get('_related', 0)
            rel_txt = f' (관련 보도 {rel}건)' if rel else ''
            plain_lines.append(f"{i}. {item.get('title', '')}{rel_txt}")
            plain_lines.append(f"   출처: {item.get('source', '')}")
            plain_lines.append(f"   🔗 {item.get('url', '')}\n")
        plain_lines.append('📊 대시보드: https://youjinwoong.github.io/radio-policy-ai/')
        ok = notify.send_telegram('\n'.join(plain_lines), chat_id=TELEGRAM_CHAT_ID,
                                  disable_web_page_preview=True)
    if ok:
        print(f'[텔레그램] 긴급 {len(urgent_items)}건 발송 완료')
    else:
        print(f'[텔레그램] 긴급 {len(urgent_items)}건 발송 실패 (HTML·평문 모두)')


# ═══════════════════════════════════════════════════════
#  긴급 전용 이메일 알림
# ═══════════════════════════════════════════════════════

def send_urgent_email(urgent_items: list):
    """긴급 기사 발생 시 즉시 이메일 발송 — Resend API 우선, Gmail SMTP 폴백"""
    if not urgent_items:
        return

    now_str = datetime.now(KST).strftime('%Y.%m.%d %H:%M KST')
    subject = f'🚨 [전파정책 AI 긴급] {now_str} — 즉시 대응 기사 {len(urgent_items)}건'

    rows_html = ''
    for item in urgent_items:
        rows_html += f'''
  <li style="margin-bottom:14px;padding:10px;background:#fff5f5;border-left:4px solid #e53e3e;border-radius:4px">
    <a href="{item['url']}" style="color:#c53030;font-weight:700;font-size:14px">{item['title']}</a><br>
    <small style="color:#666">{item['source']}</small>
  </li>'''

    body_html = f'''
<html><body style="font-family:sans-serif;max-width:600px;margin:auto;padding:20px">
<h2 style="color:#c53030">🚨 전파정책 AI — 긴급 대응 알림</h2>
<p style="color:#666">{now_str} | 즉시 대응이 필요한 기사 <strong>{len(urgent_items)}건</strong>이 감지되었습니다.</p>
<hr style="border-color:#fed7d7">
<ul style="padding-left:20px;list-style:none">
{rows_html}
</ul>
<hr>
<p style="color:#999;font-size:12px">
이 메일은 긴급 기사 감지 시 자동 발송됩니다. SKT Comm센터 기술정책팀<br>
대시보드: <a href="https://youjinwoong.github.io/radio-policy-ai/">https://youjinwoong.github.io/radio-policy-ai/</a>
</p>
</body></html>'''

    # Resend 우선 (GitHub Actions 미국 IP에서도 동작)
    if RESEND_API_KEY:
        import json as _json
        try:
            resp = requests.post(
                'https://api.resend.com/emails',
                headers={'Authorization': f'Bearer {RESEND_API_KEY}', 'Content-Type': 'application/json'},
                data=_json.dumps({
                    'from': '전파정책 AI <onboarding@resend.dev>',
                    'to': ['you.jinwoong@gmail.com'],
                    'subject': subject,
                    'html': body_html,
                }),
                timeout=30,
            )
            if resp.status_code in (200, 201):
                print(f'[긴급 이메일/Resend] you.jinwoong@gmail.com 발송 완료')
            else:
                print(f'[긴급 이메일/Resend 오류] HTTP {resp.status_code}: {resp.text[:200]}')
        except Exception as e:
            print(f'[긴급 이메일/Resend 오류] {e}')
    elif all([EMAIL_FROM, EMAIL_PASS, EMAIL_TO]):
        # 폴백: Gmail SMTP (PC 로컬 실행 시)
        extra_to = 'lampman@sktelecom.com'
        all_to = list({addr.strip() for addr in (EMAIL_TO + ',' + extra_to).split(',') if addr.strip()})
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f'전파정책 AI <{EMAIL_FROM}>'
        msg['To']      = ', '.join(all_to)
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))
        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30) as smtp:
                smtp.login(EMAIL_FROM, EMAIL_PASS)
                smtp.sendmail(EMAIL_FROM, all_to, msg.as_string())
            print(f'[긴급 이메일/Gmail] {", ".join(all_to)} 발송 완료')
        except Exception as e:
            print(f'[긴급 이메일/Gmail 오류] {e}')
    else:
        print('[긴급 이메일] RESEND_API_KEY 또는 Gmail 환경변수 미설정 — 건너뜀')


# ═══════════════════════════════════════════════════════
#  이메일 발송
# ═══════════════════════════════════════════════════════

def send_email(new_items: list, briefing_text: str = ''):
    if not all([EMAIL_FROM, EMAIL_PASS, EMAIL_TO]):
        print('[이메일] 환경변수 미설정 — 건너뜀')
        return

    today = datetime.now(KST).strftime('%Y.%m.%d')

    if not new_items:
        subject = f'[전파정책 AI] {today} — 신규 고시·뉴스 없음'
        body_html = f'''
<html><body style="font-family:sans-serif;max-width:600px;margin:auto;padding:20px">
<h2 style="color:#534AB7">전파정책 전문가 AI — 모닝 브리핑</h2>
<p style="color:#666">{today} | 오늘은 새로운 항목이 없습니다.</p>
<hr>
<p style="color:#999;font-size:12px">
대시보드: <a href="https://youjinwoong.github.io/radio-policy-ai/">바로가기</a>
</p>
</body></html>'''
    elif briefing_text:
        # AI 브리핑 텍스트를 HTML로 변환하여 발송
        subject = f'☀️ [전파정책 AI] {today} 모닝 브리핑 — {len(new_items)}건'
        import html as html_lib

        def text_to_html(text: str) -> str:
            """규칙3: 브리핑 HTML 변환. 🔴 긴급 항목은 빨간 네모 박스."""
            lines = text.split('\n')
            html_lines = []
            in_box = False
            for line in lines:
                escaped = html_lib.escape(line)
                is_urgent = '🔴' in line
                # 긴급 박스 닫기 조건
                if in_box and not is_urgent and (escaped.startswith('[') or escaped.startswith('📡') or escaped == ''):
                    html_lines.append('</div>')
                    in_box = False
                # 긴급 항목 → 박스 열기
                if is_urgent:
                    if not in_box:
                        html_lines.append('<div style="border:2px solid #c53030;border-radius:6px;background:#fff5f5;padding:10px 14px;margin:10px 0;">')
                        in_box = True
                    html_lines.append(f'<p style="margin:3px 0">{escaped}</p>')
                elif escaped.startswith('📡'):
                    html_lines.append(f'<h2 style="color:#534AB7;margin-bottom:4px">{escaped}</h2>')
                elif escaped.startswith('[') and escaped.endswith(']'):
                    html_lines.append(f'<h3 style="color:#1a1a1a;margin:20px 0 6px;border-bottom:1px solid #eee;padding-bottom:4px">{escaped}</h3>')
                elif escaped.startswith('•') or escaped.startswith('·') or '🟡' in line or '🟢' in line:
                    html_lines.append(f'<p style="margin:4px 0 4px 12px">{escaped}</p>')
                elif escaped.startswith('  →'):
                    html_lines.append(f'<p style="margin:2px 0 2px 24px;color:#555;font-size:13px">{escaped}</p>')
                elif escaped.startswith('  🔗'):
                    url_part = line.strip()[2:].strip()
                    html_lines.append(f'<p style="margin:2px 0 8px 24px;font-size:12px"><a href="{url_part}" style="color:#534AB7">{url_part}</a></p>')
                elif escaped == '':
                    html_lines.append('<br>')
                else:
                    html_lines.append(f'<p style="margin:4px 0">{escaped}</p>')
            if in_box:
                html_lines.append('</div>')
            return '\n'.join(html_lines)

        briefing_html = text_to_html(briefing_text)
        body_html = f'''
<html><body style="font-family:sans-serif;max-width:640px;margin:auto;padding:20px">
{briefing_html}
<hr style="margin-top:24px">
<p style="color:#999;font-size:11px">
이 메일은 자동 발송됩니다. SKT Comm센터 기술정책팀<br>
대시보드: <a href="https://youjinwoong.github.io/radio-policy-ai/">https://youjinwoong.github.io/radio-policy-ai/</a>
</p>
</body></html>'''
    else:
        subject = f'[전파정책 AI] {today} 신규 {len(new_items)}건 — 확인 필요'

        by_cat: dict = {}
        for item in new_items:
            cat = item.get('category', '기타')
            by_cat.setdefault(cat, []).append(item)

        cat_icons = {
            '주파수': '📶', '전자파': '⚡', '기술기준': '📋',
            'ITU·WRC': '🌐', '전기통신사업': '📡', '정보통신망': '🔒', '기타': '📌'
        }

        rows_html = ''
        for cat, cat_items in by_cat.items():
            icon = cat_icons.get(cat, '📌')
            rows_html += f'''
<h3 style="color:#1a1a1a;margin:20px 0 8px">{icon} {cat} ({len(cat_items)}건)</h3>
<ul style="padding-left:20px">'''
            for item in cat_items:
                rows_html += f'''
  <li style="margin-bottom:10px">
    <a href="{item['url']}" style="color:#534AB7;font-weight:500">{item['title']}</a><br>
    <small style="color:#999">{item['source']}</small>
  </li>'''
            rows_html += '</ul>'

        body_html = f'''
<html><body style="font-family:sans-serif;max-width:600px;margin:auto;padding:20px">
<h2 style="color:#534AB7">전파정책 전문가 AI — 일일 모니터링 리포트</h2>
<p style="color:#666">{today} | 신규 항목 <strong>{len(new_items)}건</strong></p>
<hr>
{rows_html}
<hr>
<p style="color:#999;font-size:12px">
이 메일은 자동 발송됩니다. 문의: SKT Comm센터 기술정책팀<br>
대시보드: <a href="https://youjinwoong.github.io/radio-policy-ai/">https://youjinwoong.github.io/radio-policy-ai/</a>
</p>
</body></html>'''

    # 기본 수신자 + 추가 고정 수신자 합산
    extra_to = 'lampman@sktelecom.com'
    all_to = list({addr.strip() for addr in (EMAIL_TO + ',' + extra_to).split(',') if addr.strip()})

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = f'전파정책 AI <{EMAIL_FROM}>'
    msg['To']      = ', '.join(all_to)
    msg.attach(MIMEText(body_html, 'html', 'utf-8'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30) as smtp:
            smtp.login(EMAIL_FROM, EMAIL_PASS)
            smtp.sendmail(EMAIL_FROM, all_to, msg.as_string())
        print(f'[이메일] {", ".join(all_to)}로 발송 완료')
    except Exception as e:
        print(f'[이메일 오류] {e}')


# ═══════════════════════════════════════════════════════
#  하트비트 — PC ↔ GitHub 동기화
# ═══════════════════════════════════════════════════════

def check_pc_heartbeat() -> bool:
    """PC가 최근 2시간 이내 실행됐는지 확인. True=PC 활성(크롤링 스킵)"""
    try:
        resp = sb.table('system_status').select('value').eq('key', 'last_pc_crawl').execute()
        if not resp.data:
            return False
        from dateutil import parser as _dtp
        last_dt = _dtp.parse(resp.data[0]['value'])
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=KST)
        elapsed = (datetime.now(KST) - last_dt).total_seconds()
        active = elapsed < 7200  # 2시간 기준
        print(f'[하트비트] 마지막 PC 실행: {str(resp.data[0]["value"])[:16]} ({int(elapsed//60)}분 전) — {"활성" if active else "비활성"}')
        return active
    except Exception as e:
        print(f'[하트비트 확인 오류] {e}')
        return False  # 확인 실패 시 크롤링 진행 (안전 기본값)


# ═══════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════

def main():
    now_str = datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')
    print(f'{"="*50}')
    print(f'[시작] {now_str}')
    print(f'{"="*50}')

    # ── 크롤링 (GitHub Actions 매시간 실행) ────────────
    existing_urls, existing_titles = get_existing_urls()
    print(f'[기존] Supabase 저장 항목 {len(existing_urls)}건')

    all_items: list = []

    # 1순위: 네이버 뉴스 검색
    naver_items, naver_fail = crawl_naver_news()
    all_items += naver_items

    # 네이버 차단 감지 → Google RSS 폴백
    # (전체 키워드 50% 이상 실패 또는 수집 5건 미만)
    if naver_fail > len(NEWS_SEARCH_KEYWORDS) * 0.5 or len(naver_items) < 5:
        print(f'[폴백] 네이버 부진({len(naver_items)}건, 실패{naver_fail}개) → Google RSS 전환')
        all_items += crawl_google_news_rss()

    # 정부기관은 PC Cowork gov_notice_crawler.py(매일 17:00)가 담당
    print(f'[수집] 총 {len(all_items)}건')

    new_items = save_new_items(all_items, (existing_urls, existing_titles))
    print(f'[신규] {len(new_items)}건')

    # ── 긴급 기사 즉시 알림 (발행 24시간 이내만) ────────
    now_kst = datetime.now(KST)
    cutoff_24h = now_kst - timedelta(hours=24)

    def is_within_24h(item):
        pub = item.get('published_at', '')
        if not pub:
            return False
        try:
            from dateutil import parser as _dtp2
            pub_dt = _dtp2.parse(pub)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=KST)
            return pub_dt >= cutoff_24h
        except Exception:
            return False

    urgent_items = [i for i in new_items if i.get('urgency') == '긴급' and is_within_24h(i)]
    skipped = [i for i in new_items if i.get('urgency') == '긴급' and not is_within_24h(i)]
    if skipped:
        print(f'[긴급] {len(skipped)}건 발행 24시간 초과 — 알림 제외')

    # ── 재알림 억제 (배경역사 #44) ──────────────────────
    # 같은 사건 재보도가 매시간 새 긴급 기사로 들어와 텔레그램이 며칠간 수십 통
    # (KT 과징금: 8일 339건 알림). 최근 3일 내 이미 DB에 있던 긴급 기사와 제목이
    # 유사하면 후속 보도로 보고 알림만 생략한다 — 수집·브리핑·대시보드에는 그대로 반영.
    # 실패 시에는 전부 알림(fail-open): 억제가 목적이므로 판정이 죽으면 시끄러운 쪽이 안전.
    urgent_items = suppress_repeat_alerts(urgent_items)

    if urgent_items:
        print(f'[긴급] {len(urgent_items)}건 — 알림 발송')
        send_telegram(urgent_items)
        send_urgent_email(urgent_items)
        # 구독자 봇: 즉시 발송이 아니라 큐에 적재 → 각자 고른 수신 시각에 모아서 발송된다.
        # 반드시 억제·클러스터링을 거친 urgent_items로만 호출할 것(#44).
        # 기사당 1행으로 적재한다(2026-08-03) — 태그를 데이터로 넘겨야 구독자 관심분야 필터가
        # 성립하고, 헤더·번호·칩은 구독자마다 달라 발송 측(Edge)이 조립한다.
        # 운영자 알림(send_telegram/send_urgent_email)보다 **뒤에** 두고 try/except로 격리하는
        # 현재 순서를 유지할 것 — 큐 장애가 유일한 감시 채널인 운영자 수신을 끊으면 안 된다.
        try:
            from subscriber_notify import queue_news_items
            queue_news_items(sb, urgent_items)
        except Exception as e:
            print(f'[구독자 큐 적재 실패(무시)] {e}')
    else:
        print('[긴급] 해당 없음')

    print('[모닝 브리핑] morning_briefing.yml GitHub Actions 담당 — 건너뜀')

    # ── 크롤러 heartbeat ── (check_news_health가 '크롤러 정상 vs 고장' 구분에 사용)
    # 신규 0건이어도 '크롤러는 돌았다'를 기록 → 주말 등 '뉴스 없음' 오경보 방지. 실패해도 무시.
    try:
        sb.table('system_health').upsert(
            {'key': 'last_crawl_run',
             'updated_at': datetime.now(timezone.utc).isoformat(),
             'note': f'new={len(new_items)} total={len(all_items)}'},
            on_conflict='key'
        ).execute()
        print('[heartbeat] system_health.last_crawl_run 갱신')
    except Exception as e:
        print(f'[heartbeat 오류] {e}')

    print(f'{"="*50}')
    print('[완료]')


if __name__ == '__main__':
    main()
