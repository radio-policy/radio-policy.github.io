#!/usr/bin/env python3
"""
정부 기관 고시·예규·입법예고 전용 크롤러 (PC 실행 — 한국 IP)
대상: 국립전파연구원 / 과기정통부 / 방통위
결과: Supabase news_feed 저장
"""

import os
import re
import sys
import json
import hashlib
import time

# Windows 스케줄러/cp949 콘솔에서 이모지 print 크래시 방지 (UnicodeEncodeError)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from curl_cffi import requests
    USE_CURL_CFFI = True
    print('[curl_cffi] TLS 지문 위장 모드 활성화')
except ImportError:
    import requests
    USE_CURL_CFFI = False
    print('[curl_cffi] 미설치 — 일반 requests 사용')

from bs4 import BeautifulSoup
from supabase import Client
from sb_client import make_client
import notify   # 텔레그램 전송 공용 유틸 (개선⑪) — 전송부만 위임

try:
    import anthropic
except ImportError:
    anthropic = None

SUPABASE_URL       = os.environ['SUPABASE_URL']
SUPABASE_KEY       = os.environ['SUPABASE_SERVICE_KEY']
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID', '')
RESEND_API_KEY     = os.environ.get('RESEND_API_KEY', '')
ANTHROPIC_API_KEY  = os.environ.get('ANTHROPIC_API_KEY', '')

KST = timezone(timedelta(hours=9))
sb: Client = make_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'ko-KR,ko;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

MAX_RETRY = 3
RETRY_DELAY = 5


def fetch_with_retry(url: str, timeout: int = 20):
    for attempt in range(1, MAX_RETRY + 1):
        try:
            if USE_CURL_CFFI:
                res = requests.get(url, impersonate='chrome110', timeout=timeout)
            else:
                res = requests.get(url, headers=HEADERS, timeout=timeout)
            res.raise_for_status()
            return res
        except Exception as e:
            if attempt < MAX_RETRY:
                print('  [재시도 %d/%d] %s... (%s)' % (attempt, MAX_RETRY, url[:50], e))
                time.sleep(RETRY_DELAY)
            else:
                raise


def parse_date(s: str) -> str:
    """다양한 날짜 형식 → ISO 8601 변환. 파싱 실패 시 빈 문자열 반환.
    (crawler.py의 다중 형식 해석기와 동일 — 날짜만 있는 기존 입력은 결과 불변,
     시각 포함·ISO·상대 날짜 등 기존에 빈 값이 되던 형식이 추가로 파싱됨. 배경역사 #23)"""
    if not s:
        return ''
    s = s.strip()
    now = datetime.now(KST)

    # 1) ISO 8601 / RFC 3339
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?', s)
    if m:
        y, mo, d, h, mi, sec = m.group(1, 2, 3, 4, 5, 6)
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
            if dt > now:
                dt = dt.replace(year=now.year - 1)
            return dt.isoformat()
        except Exception:
            pass

    return ''  # 파싱 실패 — 호출자가 fallback 처리


def get_existing_urls() -> tuple:
    res = sb.table('news_feed').select('url,title').execute()
    urls   = {r['url']   for r in (res.data or []) if r.get('url')}
    titles = {r['title'] for r in (res.data or []) if r.get('title')}
    return urls, titles


def detect_category(title: str) -> str:
    if any(k in title for k in ['주파수', '할당', '경매', '분배', '재배치']): return '주파수'
    if any(k in title for k in ['전자파', 'SAR', 'EMC', '인체보호']):         return '전자파'
    if any(k in title for k in ['적합성평가', '기자재', '시험기관', '인증']): return '기술기준'
    if any(k in title for k in ['ITU', 'WRC', 'IMT', '6G', '5G']):           return 'ITU·WRC'
    if any(k in title for k in ['기술기준', '무선설비', '무선국', '단말']):   return '기술기준'
    if any(k in title for k in ['전기통신사업', '통신사업', '망중립']):       return '전기통신사업'
    return '기타'


def crawl_rra() -> list:
    items = []
    targets = [
        ('https://www.rra.go.kr/ko/reference/lawList.do', '고시·공고', '기술기준'),
        ('https://www.rra.go.kr/ko/notice/atnList.do',    '행정예고',  '기술기준'),
        ('https://www.rra.go.kr/ko/notice/noticeList.do', '공지사항',  '기타'),
        ('https://www.rra.go.kr/ko/notice/newsList.do',   '보도자료',  '기타'),
    ]
    for url, label, category in targets:
        # 상대경로 href 해석을 위한 페이지 기준 디렉토리 (예: .../ko/notice/)
        base_dir = url.rsplit('/', 1)[0] + '/'
        try:
            res = fetch_with_retry(url, timeout=20)
            res.encoding = 'euc-kr'
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.select('table.board_list tbody tr, table tbody tr')[:20]
            for row in rows:
                title_tag = row.find('a')
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                if not title or title.isdigit() or len(title) < 5:
                    continue
                href = title_tag.get('href', '')
                if href.startswith('/'):
                    href = 'https://www.rra.go.kr' + href
                elif href and not href.startswith('http'):
                    href = base_dir + href
                tds = row.find_all('td')
                # td를 역순으로 순회해 날짜 패턴 매칭 (위치 의존 제거)
                date_str = ''
                for td in reversed(tds):
                    t = td.get_text(strip=True)
                    if re.match(r'\d{4}[.\-]\d{1,2}[.\-]\d{1,2}', t):
                        date_str = t
                        break
                items.append({
                    'title':        title,
                    'source':       '국립전파연구원 ' + label,
                    'category':     category,
                    'url':          href,
                    'is_read':      False,
                    'published_at': parse_date(date_str),
                    'urgency':      '보통',
                    'importance':   '보통',
                })
            print('[RRA] %s: %d행' % (label, len(rows)))
        except Exception as e:
            print('[RRA 오류] %s: %s' % (label, e))
        time.sleep(1)
    return items


RADIO_KEYWORDS = [
    '전파', '주파수', '5G', '6G', '전자파', '무선', '적합성평가', '기자재',
    'WRC', 'ITU', 'IMT', '스펙트럼', '전기통신', '통신사업', '단말',
    '정보통신망', '사이버', '이동통신', '기지국', '무선국',
]

# 보도자료 수집 키워드는 app_config.press_keywords 가 원본(대시보드 '수집 키워드 관리'에서 편집).
# main() 시작 시 DB에서 읽어 이 리스트를 제자리 갱신한다. 조회 실패 시 이 폴백 그대로(fail-open).
# 적용 범위는 보도자료(목록 필터+본문 수집)뿐 — 입법예고·고시는 RADIO_KEYWORDS 유지.
PRESS_KEYWORDS = RADIO_KEYWORDS + ['AI']

def crawl_msit() -> list:
    items = []
    targets = [
        ('https://www.msit.go.kr/bbs/list.do?sCode=user&mPid=208&mId=307', '보도자료'),
        ('https://www.msit.go.kr/bbs/list.do?sCode=user&mPid=103&mId=109', '입법행정예고'),
        ('https://www.msit.go.kr/bbs/list.do?sCode=user&mPid=103&mId=108', '훈령예규고시'),
    ]
    from urllib.parse import unquote, urlparse, parse_qs
    for url, label in targets:
        try:
            res = fetch_with_retry(url, timeout=20)
            res.encoding = getattr(res, 'apparent_encoding', None) or 'utf-8'
            html = res.text
            # 2026-07 사이트 개편: 목록 DOM은 빈 껍데기이고 제목·날짜를 인라인 스크립트가
            # $('#td_NTT_SJ_N').html(unescape('제목')) 식으로 채운다 → 스크립트에서 직접 추출.
            # 상세 링크는 bbsSeqNo(폼 hidden)까지 붙여야 열림 — 없으면 '시스템 점검 안내'로 소프트 차단. (배경역사 #39)
            ids    = re.findall(r'onclick="fn_detail\((\d+)\);"', html)
            titles = re.findall(r"sHtml\+= unescape\('(.*?)'\);\s*sHtml\+= newHtml;", html, re.S)
            date_map = dict(re.findall(r"REG_DT'\+'_(\d+)'\)\.html\('(\d{4}-\d{2}-\d{2})'\)", html))
            m_bbs = re.search(r'name="bbsSeqNo"[^>]*value="(\d+)"', html)
            bbs_seq = m_bbs.group(1) if m_bbs else ''
            q = parse_qs(urlparse(url).query)
            m_id, m_pid = q.get('mId', [''])[0], q.get('mPid', [''])[0]
            kw_set = PRESS_KEYWORDS if label == '보도자료' else RADIO_KEYWORDS
            found = 0
            for i, (seq, raw_title) in enumerate(zip(ids, titles)):
                title = unquote(raw_title).strip()
                if not title or not any(k in title for k in kw_set):
                    continue
                items.append({
                    'title':        title,
                    'source':       '과기정통부 ' + label,
                    'category':     detect_category(title),
                    'url':          'https://www.msit.go.kr/bbs/view.do?sCode=user&mId=%s&mPid=%s&bbsSeqNo=%s&nttSeqNo=%s' % (m_id, m_pid, bbs_seq, seq),
                    'is_read':      False,
                    'published_at': parse_date(date_map.get(str(i), '')),
                    'urgency':      '보통',
                    'importance':   '보통',
                })
                found += 1
            # 구(舊) DOM 구조 폴백 — 사이트가 되돌아갈 경우 대비
            if not ids:
                soup = BeautifulSoup(html, 'html.parser')
                for row in soup.select('table tbody tr, ul.bbs_list li')[:20]:
                    title_tag = row.find('a')
                    if not title_tag:
                        continue
                    title = title_tag.get_text(strip=True)
                    if not title or not any(k in title for k in RADIO_KEYWORDS):
                        continue
                    href = title_tag.get('href', '')
                    if href.startswith('/'):
                        href = 'https://www.msit.go.kr' + href
                    date_tag = row.find(class_=re.compile(r'date|day|time'))
                    items.append({
                        'title': title, 'source': '과기정통부 ' + label,
                        'category': detect_category(title), 'url': href, 'is_read': False,
                        'published_at': parse_date(date_tag.get_text(strip=True) if date_tag else ''),
                        'urgency': '보통', 'importance': '보통',
                    })
                    found += 1
            print('[MSIT] %s: 행 %d개 스캔, 키워드 매칭 %d건' % (label, len(ids), found))
        except Exception as e:
            print('[MSIT 오류] %s: %s' % (label, e))
        time.sleep(1)
    return items


# 중앙전파관리소는 www.crms.go.kr 이다 (2026-08-02 재정정 — 배경역사 #53).
# 2026-08-01의 "kmcc.go.kr=중앙전파관리소" 정정은 오류였다: kmcc.go.kr 은
# 방송미디어통신위원회(방통위 개편 후 새 도메인)로 kcc.go.kr 과 동일 게시판 미러다
# (목록 상위 5건 완전 일치 실측). kmcc.go.kr 수집은 crawl_kcc()와 중복이라 제거하고
# 이 함수는 진짜 전파관리소(crms.go.kr)를 긁는다. 행 링크는 javascript:view('view.do','seq',...).
def crawl_kmcc() -> list:
    items = []
    targets = [
        ('https://www.crms.go.kr/lay1/bbs/S1T30C34/A/77/list.do', '보도자료', 'S1T30C34/A/77'),
        ('https://www.crms.go.kr/lay1/bbs/S1T30C31/A/10/list.do', '공지사항', 'S1T30C31/A/10'),
    ]
    for url, label, board in targets:
        try:
            res = fetch_with_retry(url, timeout=20)
            res.encoding = getattr(res, 'apparent_encoding', None) or 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.select('table tbody tr')[:15]
            found = 0
            for row in rows:
                a = row.find('a')
                if not a:
                    continue
                title = a.get_text(' ', strip=True)
                if not title or not any(k in title for k in RADIO_KEYWORDS):
                    continue
                m = re.search(r"view\('view\.do'\s*,\s*'(\d+)'", a.get('href', ''))
                if not m:
                    continue
                date_str = ''
                for td in row.find_all('td'):
                    dm = re.match(r'\d{4}-\d{1,2}-\d{1,2}', td.get_text(strip=True))
                    if dm:
                        date_str = dm.group(0)
                        break
                items.append({
                    'title':        title,
                    'source':       '중앙전파관리소 ' + label,
                    'category':     detect_category(title),
                    'url':          ('https://www.crms.go.kr/lay1/bbs/%s/view.do?article_seq=%s'
                                     % (board, m.group(1))),
                    'is_read':      False,
                    'published_at': parse_date(date_str),
                    'urgency':      '보통',
                    'importance':   '보통',
                })
                found += 1
            print('[중앙전파관리소] %s: 행 %d개 스캔, 매칭 %d건' % (label, len(rows), found))
        except Exception as e:
            print('[중앙전파관리소 오류] %s: %s' % (label, e))
        time.sleep(1)
    return items


# ═══════════════════════════════════════════════════════
#  크롤러 — 방송통신위원회 (kcc.go.kr)
#
#  주의: 위 crawl_kmcc()가 긁는 kmcc.go.kr 은 '중앙전파관리소'다. 두 사이트가 같은 CMS라
#  boardId 체계까지 비슷해 오랫동안 방통위로 잘못 표기돼 있었다(2026-08-01 정정).
#  방통위 본체는 www.kcc.go.kr 이며 목록은 mode 없이 boardId 를 줘야 표가 나온다
#  (mode=view 를 주면 안내 페이지만 반환됨 — 실측 확인).
# ═══════════════════════════════════════════════════════

# 방통위 보도자료는 방송 거버넌스(재허가·이사 임명·위원회 결과)가 대부분이라
# RADIO_KEYWORDS로만 거르면 매칭이 0건이 된다(실측). 기술정책팀에 의미 있는 축은
# 단말기 유통·이용자보호·스팸·요금 쪽이라 그 축을 더한다. 방송 거버넌스는 일부러 안 넣는다.
KCC_KEYWORDS = RADIO_KEYWORDS + [
    '단말기', '지원금', '스팸', '이용자', '요금', '결합판매', '번호이동',
    '위치정보', '재난문자', '과장광고', '유통', '개인정보',
]


def crawl_kcc() -> list:
    items = []
    targets = [
        ('https://www.kcc.go.kr/user.do?boardId=1113&page=A05030000&dc=K05030000', '보도자료'),
    ]
    for url, label in targets:
        try:
            res = fetch_with_retry(url, timeout=20)
            res.encoding = getattr(res, 'apparent_encoding', None) or 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            rows = soup.select('table tbody tr')[:20]
            found = 0
            for row in rows:
                title_tag = row.find('a')
                if not title_tag:
                    continue
                title = title_tag.get_text(' ', strip=True)
                if not title or not any(k in title for k in KCC_KEYWORDS):
                    continue
                href = title_tag.get('href', '')
                # /user.do;jsessionid=... 형태 — 세션 조각은 떼야 URL 중복판정이 안정된다
                href = re.sub(r';jsessionid=[^?]*', '', href)
                if href.startswith('/'):
                    href = 'https://www.kcc.go.kr' + href
                # 날짜는 td 중 YYYY-MM-DD 패턴을 찾는다(칼럼 순서 변경에 견디도록)
                date_str = ''
                for td in row.find_all('td'):
                    t = td.get_text(strip=True)
                    if re.fullmatch(r'\d{4}[-.]\d{1,2}[-.]\d{1,2}', t):
                        date_str = t
                        break
                items.append({
                    'title':        title,
                    'source':       '방송통신위원회 ' + label,
                    'category':     detect_category(title),
                    'url':          href,
                    'is_read':      False,
                    'published_at': parse_date(date_str),
                    'urgency':      '보통',
                    'importance':   '보통',
                })
                found += 1
            print('[방통위] %s: 행 %d개 스캔, 키워드 매칭 %d건' % (label, len(rows), found))
        except Exception as e:
            print('[방통위 오류] %s: %s' % (label, e))
        time.sleep(1)
    return items


# ═══════════════════════════════════════════════════════
#  크롤러 — ETRI (etri.re.kr) 보도자료
#  연구원 보도자료라 RADIO_KEYWORDS만으론 6G·표준화 소식을 놓쳐 키워드를 넓혔다.
# ═══════════════════════════════════════════════════════

ETRI_KEYWORDS = RADIO_KEYWORDS + ['6G', '5G', 'IMT', '표준화', '위성', '안테나', '네트워크', '테라헤르츠']


def crawl_etri() -> list:
    items = []
    url = 'https://www.etri.re.kr/kor/bbs/list.etri?b_board_id=ETRI06'   # 보도자료
    try:
        res = fetch_with_retry(url, timeout=20)
        res.encoding = getattr(res, 'apparent_encoding', None) or 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.select('table tbody tr')[:20]
        found = 0
        for row in rows:
            title_tag = row.find('a')
            if not title_tag:
                continue
            title = title_tag.get_text(' ', strip=True)
            if not title or not any(k in title for k in ETRI_KEYWORDS):
                continue
            href = re.sub(r';jsessionid=[^?]*', '', title_tag.get('href', ''))
            if href.startswith('/'):
                href = 'https://www.etri.re.kr' + href
            date_str = ''
            for td in row.find_all('td'):
                t = td.get_text(strip=True)
                if re.fullmatch(r'\d{4}[-.]\d{1,2}[-.]\d{1,2}', t):
                    date_str = t
                    break
            items.append({
                'title':        title,
                'source':       'ETRI 보도자료',
                'category':     detect_category(title),
                'url':          href,
                'is_read':      False,
                'published_at': parse_date(date_str),
                'urgency':      '참고',      # 연구원 보도자료는 정책 결정이 아니라 동향 참고
                'importance':   '참고',
            })
            found += 1
        print('[ETRI] 행 %d개 스캔, 키워드 매칭 %d건' % (len(rows), found))
    except Exception as e:
        print('[ETRI 오류] %s' % e)
    time.sleep(1)
    return items


# ═══════════════════════════════════════════════════════
#  크롤러 — KISDI (kisdi.re.kr) 보도자료·공지사항
#
#  주의: /bbs/list.do 목록은 JS로 그려져 HTML에 항목이 없다(실측). 대신 메인(index.do)이
#  최신 항목을 서버렌더링으로 뿌리므로 거기서 view.do 링크를 골라낸다.
#  게시판 구분은 URL의 key 값으로 한다.
# ═══════════════════════════════════════════════════════

KISDI_BOARDS = {
    'm2101113055776': '보도자료',
    'm2101113055944': '공지사항',
}


def crawl_kisdi() -> list:
    items = []
    try:
        res = fetch_with_retry('https://www.kisdi.re.kr/index.do', timeout=20)
        res.encoding = getattr(res, 'apparent_encoding', None) or 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        seen_href = set()
        scanned = found = 0
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/bbs/view.do' not in href:
                continue
            m = re.search(r'key=(m\d+)', href)
            if not m or m.group(1) not in KISDI_BOARDS:
                continue
            if href in seen_href:
                continue
            seen_href.add(href)
            scanned += 1
            label = KISDI_BOARDS[m.group(1)]
            # 메인 카드에는 "보도자료 제목…" 처럼 분류명이 앞에 붙어 나온다 — 제거
            title = a.get_text(' ', strip=True)
            title = re.sub(r'^(보도자료|공지사항|채용공고)\s*', '', title).strip()
            if not title or not any(k in title for k in RADIO_KEYWORDS):
                continue
            items.append({
                'title':        title,
                'source':       'KISDI ' + label,
                'category':     detect_category(title),
                'url':          'https://www.kisdi.re.kr' + href if href.startswith('/') else href,
                'is_read':      False,
                # 메인 카드에는 날짜가 없는 경우가 많다 → 빈 값이면 save_items가 오늘로 채운다
                'published_at': '',
                'urgency':      '참고',
                'importance':   '참고',
            })
            found += 1
        print('[KISDI] 링크 %d개 스캔, 키워드 매칭 %d건' % (scanned, found))
    except Exception as e:
        print('[KISDI 오류] %s' % e)
    time.sleep(1)
    return items


OPINION_BASE = 'https://opinion.lawmaking.go.kr'
OPINION_LIST = OPINION_BASE + '/gcom/ogLmPp'

OPINION_KEYWORDS = [
    '전파', '주파수', '전기통신', '방송통신', '무선', '전자파',
    '적합성평가', '정보통신', '이동통신', '기간통신', '위성',
    '단말장치', '기지국', '스펙트럼',
]

# 소관부처 기반 보강: 제명에 키워드가 없어도 통신·방송 규제기관 소관이면 포함
OPINION_DEPTS = ['방송미디어통신위원회', '방송통신위원회']
# 과기정통부는 과학·우주·우정 잡음이 섞이므로 통신계열 힌트가 있을 때만 포함
OPINION_DEPT_HINT = [
    '통신', '방송', '전파', '무선', '주파수', '전자파',
    '단말', '기지국', '네트워크', '인터넷', '클라우드', '데이터센터', '스펙트럼',
]
# 부처 기반 매칭에서 제외할 잡음(직제·정원 등 조직 개편)
OPINION_DEPT_EXCLUDE = ['직제', '소속기관', '정원', '청사']
OPINION_MAX_PAGES = 20


def _parse_opinion_date(s: str) -> str:
    s = s.strip().rstrip('.')
    parts = [p.strip() for p in s.split('.') if p.strip()]
    if len(parts) >= 3:
        try:
            return '%04d%02d%02d' % (int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            pass
    return ''


def _opinion_law_id(title: str) -> str:
    h = hashlib.md5(title.encode('utf-8')).hexdigest()[:10]
    return 'lsAnc_op_' + h


def _save_opinion_to_law_amendments(collected: dict) -> list:
    try:
        existing_rows = sb.table('law_amendments').select('law_id,matched_keywords') \
            .like('law_id', 'lsAnc_op_%').execute().data
        existing = {r['law_id']: r for r in existing_rows}
    except Exception as e:
        print('[입법예고 DB 조회 오류] %s' % e)
        existing = {}

    new_items = []
    now_str = datetime.now(KST).isoformat()

    for href, info in collected.items():
        title = info['title']
        dept = info['dept']
        period = info['period']
        keywords = list(info['keywords'])

        parts = period.split('~')
        public_dt = _parse_opinion_date(parts[0]) if parts else ''
        enf_dt = _parse_opinion_date(parts[1]) if len(parts) > 1 else ''

        law_id = _opinion_law_id(title)
        row = {
            'law_id':           law_id,
            'law_nm':           title,
            'law_type':         'lsAnc',
            'ann_type':         ('입법예고 (%s)' % dept) if dept else '입법예고',
            'public_dt':        public_dt,
            'enf_dt':           enf_dt,
            'matched_keywords': keywords,
            'link_url':         href,
            'updated_at':       now_str,
        }

        if law_id not in existing:
            try:
                sb.table('law_amendments').insert(row).execute()
                new_items.append({
                    'title':    title,
                    'law_nm':   title,
                    'dept':     dept,
                    'period':   period,
                    'link_url': href,
                    'ann_type': row['ann_type'],
                    'public_dt': public_dt,
                    'enf_dt':   enf_dt,
                })
                print('  신규 입법예고: %s' % title[:40])
            except Exception as e:
                print('  [입법예고 저장 오류] %s: %s' % (title[:30], e))
        else:
            existing_kw = set(existing[law_id].get('matched_keywords') or [])
            new_kw = set(keywords)
            if not new_kw.issubset(existing_kw):
                try:
                    sb.table('law_amendments').update({
                        'matched_keywords': list(existing_kw | new_kw),
                        'updated_at': now_str,
                    }).eq('law_id', law_id).execute()
                except Exception as e:
                    print('  [키워드 업데이트 오류] %s: %s' % (title[:30], e))

    print('[입법예고] 신규 %d건 law_amendments 저장' % len(new_items))
    return new_items


def _notify_opinion_items(new_items: list):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        for it in new_items:
            msg = (
                '\U0001f4e2 <b>[신규 입법예고]</b>\n'
                + it['title'] + '\n\n'
                '• 담당: ' + (it['dept'] or '—') + '\n'
                '• 예고기간: ' + (it['period'] or '—') + '\n'
                '• 링크: ' + it['link_url']
            )
            # 전송부는 notify 위임 (개선⑪) — 실패 로그는 notify가 출력
            if notify.send_telegram(msg, chat_id=TELEGRAM_CHAT_ID, parse_mode='HTML'):
                print('  [텔레그램] "%s" 발송' % it['title'][:30])
            time.sleep(0.5)

    if RESEND_API_KEY and new_items:
        items_html = ''
        for it in new_items:
            items_html += (
                '<div style="border:2px solid #c53030;border-radius:6px;'
                'background:#fff5f5;padding:10px 14px;margin:10px 0">'
                '<b>\U0001f4e2 [신규 입법예고]</b> ' + it['title'] + '<br>'
                '• 담당: ' + (it['dept'] or '—') + '<br>'
                '• 예고기간: ' + (it['period'] or '—') + '<br>'
                '• <a href="' + it['link_url'] + '">상세 보기</a>'
                '</div>'
            )
        body_html = (
            '<html><body style="font-family:sans-serif;max-width:640px;margin:auto;padding:20px">'
            '<h2 style="color:#c53030">\U0001f534 신규 입법예고 %d건 감지</h2>' % len(new_items)
            + items_html
            + '<hr style="margin-top:24px">'
            '<p style="color:#999;font-size:11px">SKT Comm센터 기술정책팀 전파정책 AI<br>'
            '<a href="https://youjinwoong.github.io/radio-policy-ai/">대시보드</a></p>'
            '</body></html>'
        )
        payload = json.dumps({
            'from': '전파정책 AI <onboarding@resend.dev>',
            'to': ['you.jinwoong@gmail.com'],
            'subject': '\U0001f534 [전파정책 AI] 신규 입법예고 %d건' % len(new_items),
            'html': body_html,
        }, ensure_ascii=False)
        try:
            resp = requests.post(
                'https://api.resend.com/emails',
                headers={
                    'Authorization': 'Bearer ' + RESEND_API_KEY,
                    'Content-Type': 'application/json',
                },
                data=payload,
                timeout=30,
            )
            if resp.status_code in (200, 201):
                print('  [이메일] 입법예고 알림 발송 완료')
            else:
                print('  [이메일 오류] HTTP %d: %s' % (resp.status_code, resp.text[:100]))
        except Exception as e:
            print('  [이메일 오류] %s' % e)


def _opinion_match(title: str, dept: str) -> list:
    """입법예고 1건이 전파·통신 관심사인지 판정. 매칭 근거 리스트 반환(없으면 빈 리스트)."""
    d = dept or ''
    raw = title or ''
    # 직제·소속기관·정원 등 조직 개편은 제명 키워드와 무관하게 우선 제외
    # (예: "과학기술정보통신부와 그 소속기관 직제" — 부처명의 '정보통신' 오탐 차단)
    if any(x in raw for x in OPINION_DEPT_EXCLUDE):
        return []
    # 제명 앞 "○○부/처/청/위원회 소관" 접두사 제거 — 소관 부처명(과학기술정보'통신'부 등)이
    # 제명에 섞여 키워드를 오탐하는 것 방지 (예: "과기정통부 소관 비상대비에 관한 법률")
    t = re.sub(r'^[가-힣·]+(?:부|처|청|위원회|위)\s*소관\s*', '', raw)
    # ① 제명 키워드 직접 매칭
    matched = [k for k in OPINION_KEYWORDS if k in t]
    if matched:
        return matched
    # ② 방송·통신 규제기관 소관은 제명 키워드가 없어도 포함
    if any(dep in d for dep in OPINION_DEPTS):
        return ['소관:방송통신위']
    # ③ 과기정통부는 통신계열 힌트가 있을 때만(과학·우주·우정 잡음 배제)
    if '과학기술정보통신부' in d and any(h in t for h in OPINION_DEPT_HINT):
        return ['소관:과기정통부']
    return []


def _fetch_opinion_reason(href: str):
    """입법예고 상세에서 개정이유+주요내용 텍스트 추출.
    반환: 본문(str) / '' (정상응답·본문 마커 없음) / None (호출 실패 → NULL 유지·재시도)."""
    if not href:
        return None
    try:
        res = fetch_with_retry(href, timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
    except Exception as e:
        print('  [입법예고 상세 오류] %s' % str(e)[:80])
        return None
    full = soup.get_text('\n', strip=True)
    # "개정이유/제정이유" 헤더부터 "의견제출/그 밖의 사항" 직전까지가 핵심 본문
    # 부처마다 "개정 이유"처럼 띄어 쓰기도 하므로 공백 허용 (배경역사 #25)
    m = re.search(r'(?:제\s*·?\s*)?(?:개\s*정|제\s*정)\s*이\s*유', full)
    if not m:
        return ''  # 본문 마커 없음 — 추출 불가(재시도 방지로 '' 저장)
    body = full[m.start():]
    for end_kw in ('의견제출', '의견 제출', '그 밖의 사항', '그밖의 사항'):
        idx = body.find(end_kw)
        if idx > 0:
            body = body[:idx]
            break
    body = re.sub(r'\s+', ' ', body).strip()
    return body[:2000]


def _summarize_opinion(law_nm: str, reason: str) -> str:
    """개정이유·주요내용을 Haiku로 1~2문장 요약. 실패·키없음 시 '' 반환."""
    if not ANTHROPIC_API_KEY or anthropic is None:
        return ''
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=200,
            messages=[{
                'role': 'user',
                'content': (
                    '다음은 「%s」 입법예고의 개정이유·주요내용입니다. '
                    '무엇을 바꾸려는지 핵심만 1~2문장(100자 이내) 한국어 평서문으로 요약하세요. '
                    '제목·머리기호 없이 문장만 출력.\n\n%s' % (law_nm, reason[:2000])
                ),
            }],
        )
        out = re.sub(r'^[#\-*◇\s]+', '', resp.content[0].text or '').strip()
        return out if len(out) >= 6 else ''
    except Exception as e:
        print('  [입법예고 요약 오류] %s' % e)
        return ''


def backfill_opinion_summaries(limit: int = 30):
    """summary가 비어 있는 입법예고(lsAnc) 행을 상세 본문 → Haiku 요약으로 채움.
    멱등: 호출/요약 실패 시 NULL 유지(다음 실행 재시도), 본문 없으면 ''로 표시(재시도 방지)."""
    if anthropic is None:
        # SYSTEM 계정 실행 시 --user 설치 패키지는 안 보임 — 전역 site-packages 설치 필요 (배경역사 #25)
        print('[입법예고 요약] anthropic 모듈 import 실패(전역 site-packages 설치 확인) — 요약 생략')
        return
    if not ANTHROPIC_API_KEY:
        print('[입법예고 요약] ANTHROPIC_API_KEY 미설정 — 요약 생략')
        return
    try:
        rows = (sb.table('law_amendments')
                .select('id,law_nm,link_url,summary')
                .like('law_id', 'lsAnc_op_%')
                .is_('summary', 'null')
                .limit(limit)
                .execute().data) or []
    except Exception as e:
        print('[입법예고 요약] 대상 조회 오류: %s' % e)
        return
    if not rows:
        return
    print('[입법예고 요약] summary NULL 대상 %d건' % len(rows))
    done = empty = failed = 0
    for r in rows:
        reason = _fetch_opinion_reason(r.get('link_url') or '')
        if reason is None:
            failed += 1            # 호출 실패 → NULL 유지(재시도)
            time.sleep(0.3)
            continue
        if reason == '':
            sb.table('law_amendments').update({'summary': ''}).eq('id', r['id']).execute()
            empty += 1
            time.sleep(0.1)
            continue
        s = _summarize_opinion(r.get('law_nm', ''), reason)
        if not s:
            failed += 1            # 요약 실패 → NULL 유지(재시도)
            time.sleep(0.2)
            continue
        sb.table('law_amendments').update({'summary': s}).eq('id', r['id']).execute()
        done += 1
        print('  ok %s -> %s' % ((r.get('law_nm') or '')[:30], s[:50]))
        time.sleep(0.15)
    print('[입법예고 요약] 완료 - 요약 %d / 내용없음 %d / 실패(NULL유지) %d' % (done, empty, failed))


def crawl_opinion_lawmaking() -> list:
    """진행 중 입법예고 전체 목록을 페이지 단위로 훑어 전파·통신 관련만 수집.
    (기존 lsNm 제명 검색은 제명에 키워드가 그대로 든 경우만 잡혀 누락이 많아 폐지)"""
    collected = {}

    page = 1
    while page <= OPINION_MAX_PAGES:
        try:
            res = fetch_with_retry(
                OPINION_LIST + '?isOgYn=Y&opYn=Y&pageIndex=%d' % page,
                timeout=20,
            )
        except Exception as e:
            print('[입법예고 오류] %d페이지: %s' % (page, e))
            break

        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.select('table tbody tr')
        page_rows = 0

        for row in rows:
            tds = row.find_all('td')
            if len(tds) < 5:
                continue
            a_tag = tds[1].find('a')
            if not a_tag:
                continue
            title = a_tag.get_text(strip=True)
            if not title:
                continue
            page_rows += 1

            href = a_tag.get('href', '')
            if href.startswith('/'):
                href = OPINION_BASE + href
            elif not href.startswith('http'):
                href = OPINION_BASE + '/gcom/' + href
            if not href:
                continue

            dept = tds[2].get_text(strip=True)
            period = tds[4].get_text(strip=True)

            matched = _opinion_match(title, dept)
            if not matched:
                continue

            if href in collected:
                collected[href]['keywords'].update(matched)
            else:
                collected[href] = {
                    'title': title, 'dept': dept,
                    'period': period, 'keywords': set(matched),
                }

        print('[입법예고] %d페이지: %d행 스캔, 누적 매칭 %d건' % (page, page_rows, len(collected)))
        if page_rows == 0:
            break
        page += 1
        time.sleep(1)

    print('[입법예고 합계] %d건 수집' % len(collected))
    if collected:
        try:
            base_rows = sb.table('law_amendments').select('law_id') \
                .like('law_id', 'lsAnc_op_%').limit(1).execute().data
            is_baseline = len(base_rows) == 0   # 첫 실행이면 알림 폭주 방지(저장만)
        except Exception:
            is_baseline = False  # 알 수 없으면 보수적으로 알림 진행
        new_items = _save_opinion_to_law_amendments(collected)
        if new_items and not is_baseline:
            _notify_opinion_items(new_items)
        elif new_items:
            print('[입법예고] 첫 실행 베이스라인 %d건 저장(알림 생략)' % len(new_items))

    # 신규 저장분 + 이전에 못 채운 행의 요약(주요내용) 채우기
    backfill_opinion_summaries()

    return []


def save_items(items: list, existing_urls: set, existing_titles: set) -> int:
    seen_urls   = set(existing_urls)
    seen_titles = set(existing_titles)
    new_items = []
    for item in items:
        url   = item.get('url', '')
        title = item.get('title', '')
        if url and url in seen_urls:
            continue
        if title and title in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title)
        # 발행일 없으면 오늘로
        if not item.get('published_at'):
            item['published_at'] = datetime.now(KST).isoformat()
        # 발행일이 파싱된 경우 15일 초과 기사는 수집 건너뜀
        else:
            try:
                pub_dt = datetime.fromisoformat(item['published_at'])
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=KST)
                if (datetime.now(KST) - pub_dt).days > 15:
                    continue
            except Exception:
                pass
        new_items.append(item)

    if not new_items:
        print('[저장] 신규 항목 없음')
        return 0

    # upsert(on_conflict=url, ignore_duplicates): 중복 URL 1건 때문에 배치 전체가
    # 실패하지 않도록 crawler.py와 동일 패턴 사용 (idx_news_feed_url_unique와 한 쌍)
    sb.table('news_feed').upsert(
        new_items, on_conflict='url', ignore_duplicates=True
    ).execute()
    print('[저장] %d건 완료' % len(new_items))
    return len(new_items)


def main():
    now_str = datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')
    print('=' * 50)
    print('[정부 고시·예규 크롤러 시작] ' + now_str)
    print('=' * 50)

    existing_urls, existing_titles = get_existing_urls()
    print('[기존] %d건' % len(existing_urls))

    # 보도자료 수집 키워드 갱신 (app_config 원본 — 실패 시 폴백 유지)
    try:
        import press_ingest
        PRESS_KEYWORDS[:] = press_ingest.load_press_keywords(sb)
        print('[press_keywords] %d개 로드' % len(PRESS_KEYWORDS))
    except Exception as e:
        print('[press_keywords 로드 실패 — 폴백 유지] %s' % e)

    all_items = []
    all_items += crawl_rra()
    all_items += crawl_msit()
    all_items += crawl_kmcc()     # 중앙전파관리소 (crms.go.kr — kmcc.go.kr 아님, #53)
    all_items += crawl_kcc()      # 방송통신위원회 (신규)
    all_items += crawl_etri()     # ETRI 보도자료 (신규)
    all_items += crawl_kisdi()    # KISDI 보도자료·공지 (신규)
    all_items += crawl_opinion_lawmaking()
    print('[수집] 총 %d건' % len(all_items))

    saved = save_items(all_items, existing_urls, existing_titles)
    print('[완료] 신규 %d건 저장' % saved)

    # ── heartbeat ── (운영 상태 탭 '입법예고/정부고시 크롤러 마지막 실행'). 신규 0건이어도 기록, 실패해도 무시.
    try:
        sb.table('system_health').upsert(
            {'key': 'last_gov_notice_run',
             'updated_at': datetime.now(timezone.utc).isoformat(),
             'note': 'saved=%d total=%d' % (saved, len(all_items))},
            on_conflict='key'
        ).execute()
        print('[heartbeat] system_health.last_gov_notice_run 갱신')
    except Exception as e:
        print('[heartbeat 오류] %s' % e)

    # ── 보도자료 본문 수집 (6개 기관 → document_chunks, 배경역사 #53) ──
    # news_feed 수집과 독립: 여기서 실패해도 위 고시·입법예고 결과에는 영향 없음.
    try:
        import press_ingest
        new_press = press_ingest.run_daily(sb, keywords=PRESS_KEYWORDS)
        if new_press > 0:
            # 신규 청크의 NULL 임베딩 채움 (기존 스크립트 재사용, NULL만 대상이라 멱등)
            import subprocess
            r = subprocess.run(
                [sys.executable, 'backfill_embeddings.py'],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                capture_output=True, encoding='utf-8', errors='replace',
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                timeout=1800,
            )
            print('[임베딩 백필] rc=%d %s' % (r.returncode, (r.stdout or '').strip()[-300:]))
    except Exception as e:
        print('[보도자료 수집 오류] %s' % e)

    print('=' * 50)


if __name__ == '__main__':
    main()
