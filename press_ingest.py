#!/usr/bin/env python3
"""
정부 보도자료 공용 수집 모듈 (PC 실행 — 한국 IP)
대상 6개 기관: 과기정통부 / 전파연구원 / 방통위 / 전파관리소 / ETRI / KISDI
결과: Supabase document_chunks (doc_category='보도자료', doc_name='{기관}_보도자료_{YYYY}.md')

gov_notice_crawler.py(매일 17시)가 run_daily()를, press_backfill.py(일회성)가
run_backfill()을 호출한다. 청크 형식은 기존 수동 업로드분과 동일:
  - 문서 첫 청크는 '# {기관} 보도자료 {YYYY}년' 프리앰블로 시작
  - 섹션 헤더 '## YYMMDD 제목' (대시보드 loadPressJSON이 이 패턴으로 분리)
  - 약 700자, 겹침 없음 (대시보드가 청크를 이어붙여 원문 복원하므로 overlap 금지)
수집 키워드는 app_config.press_keywords(JSON 배열)가 원본 — 실패 시 폴백 상수.
"""

import io
import os
import re
import sys
import json
import html as html_mod
import time
import shutil
import zipfile
import tempfile
import subprocess
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from curl_cffi import requests
    USE_CURL_CFFI = True
except ImportError:
    import requests
    USE_CURL_CFFI = False

from bs4 import BeautifulSoup

try:
    import trafilatura
except ImportError:
    trafilatura = None

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract = None
    Image = None

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

MAX_RETRY = 3
RETRY_DELAY = 5
CHUNK_SIZE = 700          # 기존 수동 업로드분과 동일 (실측)
BODY_MAX = 15000          # 항목당 본문 상한 (비정상 거대 문서 방어)
BODY_MIN = 120            # 이보다 짧으면 추출 실패로 간주
OCR_TRIGGER = 500         # PDF 텍스트층이 이보다 짧으면 이미지-전용 의심 → OCR 시도
OCR_ACCEPT = 1000         # OCR 결과가 이 이상일 때만 본문으로 채택
OCR_MAX_PAGES = 8         # OCR 대상 최대 페이지 (150dpi 이미지화)

# app_config 조회 실패 시 폴백 (gov_notice_crawler.RADIO_KEYWORDS + 'AI')
FALLBACK_KEYWORDS = [
    '전파', '주파수', '5G', '6G', '전자파', '무선', '적합성평가', '기자재',
    'WRC', 'ITU', 'IMT', '스펙트럼', '전기통신', '통신사업', '단말',
    '정보통신망', '사이버', '이동통신', '기지국', '무선국', 'AI',
]


# AI 관련성 판정 기준문 폴백 (원본은 app_config.press_relevance_criteria)
RELEVANCE_CRITERIA_FALLBACK = (
    '다음 보도자료가 통신사 전파·통신 정책 업무와 관련 있는지 판정한다. '
    '관련 있음: 이동통신(5G·6G·주파수·기지국·단말·로밍·위성통신), 전파(전자파·무선국·적합성평가), '
    '통신사업 정책·규제(전기통신사업·요금·이용자보호·알뜰폰·스팸·번호이동), '
    '네트워크·통신 인프라, 사이버보안, AI 정책(인공지능 산업·규제·인프라). '
    '관련 없음: 과학 전시·행사·공모전 홍보, 채용, 신약·바이오, 우주발사체, '
    '콘텐츠 진흥 등 통신·AI 정책과 무관한 것.'
)


def load_press_criteria(sb) -> str:
    try:
        rows = sb.table('app_config').select('value') \
            .eq('key', 'press_relevance_criteria').limit(1).execute().data
        if rows and (rows[0]['value'] or '').strip():
            return rows[0]['value'].strip()
    except Exception as e:
        print('[판정기준 조회 실패 — 폴백 사용] %s' % e)
    return RELEVANCE_CRITERIA_FALLBACK


def make_ai_judge(sb, keywords: list):
    """제목+본문 기반 관련성 판정기(Haiku). API 불가 시 None(호출자가 키워드 방식 유지).
    개별 호출 실패 시엔 키워드 매칭으로 폴백(fail-open) — 무음 누락 방지(#39)."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key or anthropic is None:
        return None
    criteria = load_press_criteria(sb)
    client = anthropic.Anthropic(api_key=api_key)

    def judge(title: str, body: str):
        try:
            resp = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=60,
                messages=[{
                    'role': 'user',
                    'content': (
                        criteria
                        + '\n\n제목: ' + title
                        + '\n본문 발췌: ' + (body or '')[:1500]
                        + '\n\n첫 단어를 "관련" 또는 "무관"으로 시작하고, '
                          '이어서 | 뒤에 15자 이내 사유를 붙여라. 예: 관련|주파수 할당 정책'
                    ),
                }],
            )
            txt = ''
            for blk in resp.content:   # 적응형 추론 대비 — text 블록만 취함
                if getattr(blk, 'type', '') == 'text':
                    txt = (blk.text or '').strip()
                    break
            if txt.startswith('관련'):
                return True, txt[:40]
            if txt.startswith('무관'):
                return False, txt[:40]
            # 형식 이탈 → 키워드 폴백
            ok = any(k in title or k in (body or '') for k in keywords)
            return ok, '형식이탈-키워드폴백'
        except Exception as e:
            ok = any(k in title or k in (body or '') for k in keywords)
            return ok, 'AI실패-키워드폴백:%s' % str(e)[:30]

    return judge


def load_press_keywords(sb) -> list:
    """app_config.press_keywords(JSON 배열) 로드. 실패 시 폴백(fail-open)."""
    try:
        rows = sb.table('app_config').select('value').eq('key', 'press_keywords') \
            .limit(1).execute().data
        if rows:
            kw = json.loads(rows[0]['value'])
            if isinstance(kw, list) and kw:
                return [str(k) for k in kw if str(k).strip()]
    except Exception as e:
        print('[press_keywords 조회 실패 — 폴백 사용] %s' % e)
    return list(FALLBACK_KEYWORDS)


# ═══════════════════════════════════════════════════════
#  HTTP
# ═══════════════════════════════════════════════════════

def _get(url: str, timeout: int = 25, encoding: str = None):
    for attempt in range(1, MAX_RETRY + 1):
        try:
            if USE_CURL_CFFI:
                res = requests.get(url, impersonate='chrome110', timeout=timeout)
            else:
                res = requests.get(url, headers=HEADERS, timeout=timeout)
            res.raise_for_status()
            if encoding:
                res.encoding = encoding
            else:
                res.encoding = getattr(res, 'apparent_encoding', None) or 'utf-8'
            return res
        except Exception as e:
            if attempt < MAX_RETRY:
                time.sleep(RETRY_DELAY)
            else:
                raise


def _post_download(url: str, data: dict, referer: str, timeout: int = 60) -> bytes:
    """첨부파일 POST 다운로드 (MSIT fileDown.do — Referer 필수, 배경역사 #53)."""
    headers = dict(HEADERS)
    headers['Referer'] = referer
    for attempt in range(1, MAX_RETRY + 1):
        try:
            if USE_CURL_CFFI:
                res = requests.post(url, data=data, headers={'Referer': referer},
                                    impersonate='chrome110', timeout=timeout)
            else:
                res = requests.post(url, data=data, headers=headers, timeout=timeout)
            res.raise_for_status()
            return res.content
        except Exception as e:
            if attempt < MAX_RETRY:
                time.sleep(RETRY_DELAY)
            else:
                raise


def _get_download(url: str, referer: str, timeout: int = 60) -> bytes:
    headers = dict(HEADERS)
    headers['Referer'] = referer
    for attempt in range(1, MAX_RETRY + 1):
        try:
            if USE_CURL_CFFI:
                res = requests.get(url, headers={'Referer': referer},
                                   impersonate='chrome110', timeout=timeout)
            else:
                res = requests.get(url, headers=headers, timeout=timeout)
            res.raise_for_status()
            return res.content
        except Exception:
            if attempt < MAX_RETRY:
                time.sleep(RETRY_DELAY)
            else:
                raise


# ═══════════════════════════════════════════════════════
#  텍스트 추출 (PDF / HWPX / HTML)
# ═══════════════════════════════════════════════════════

def _find_pdftotext() -> str:
    p = shutil.which('pdftotext')
    if p:
        return p
    for cand in (
        os.environ.get('PDFTOTEXT', ''),
        r'C:\Program Files\poppler\Library\bin\pdftotext.exe',
        r'C:\Program Files\poppler-24.08.0\Library\bin\pdftotext.exe',
        r'C:\tools\poppler\Library\bin\pdftotext.exe',
    ):
        if cand and os.path.exists(cand):
            return cand
    return ''


PDFTOTEXT = _find_pdftotext()


def _find_pdftoppm() -> str:
    """PDF→이미지 변환기(Poppler). pdftotext 와 같은 폴더에 있는 게 보통."""
    p = shutil.which('pdftoppm')
    if p:
        return p
    if PDFTOTEXT:
        cand = os.path.join(os.path.dirname(PDFTOTEXT), 'pdftoppm.exe')
        if os.path.exists(cand):
            return cand
    return ''


def _find_tesseract() -> str:
    p = shutil.which('tesseract')
    if p:
        return p
    for cand in (
        os.environ.get('TESSERACT_EXE', ''),
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    ):
        if cand and os.path.exists(cand):
            return cand
    return ''


PDFTOPPM = _find_pdftoppm()
TESSERACT = _find_tesseract()


def _pdf_ocr_text(data: bytes, max_pages: int = OCR_MAX_PAGES, dpi: int = 150) -> str:
    """이미지-전용 PDF의 OCR 폴백 (2026-08-02 개선⑫).
    pdftoppm 으로 앞 max_pages 페이지를 150dpi PNG 로 변환 후 tesseract(kor+eng).
    tesseract/pytesseract/pdftoppm 부재 또는 실패 시 '' 반환 — fail-soft."""
    if pytesseract is None or not TESSERACT or not PDFTOPPM:
        return ''
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix='press_ocr_')
        pdf_path = os.path.join(tmpdir, 'in.pdf')
        with open(pdf_path, 'wb') as f:
            f.write(data)
        out = subprocess.run(
            [PDFTOPPM, '-png', '-r', str(dpi), '-l', str(max_pages),
             pdf_path, os.path.join(tmpdir, 'pg')],
            capture_output=True, timeout=180,
        )
        if out.returncode != 0:
            return ''
        pytesseract.pytesseract.tesseract_cmd = TESSERACT
        parts = []
        for name in sorted(os.listdir(tmpdir)):
            if not name.lower().endswith('.png'):
                continue
            try:
                with Image.open(os.path.join(tmpdir, name)) as img:
                    txt = pytesseract.image_to_string(img, lang='kor+eng')
                if txt and txt.strip():
                    parts.append(txt.replace('\x0c', '').strip())
            except Exception:
                continue
        return '\n\n'.join(parts).strip()
    except Exception:
        return ''
    finally:
        if tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)


def _pdf_to_text(data: bytes) -> str:
    if not PDFTOTEXT:
        return ''
    tmp = None
    try:
        # 원자적 쓰기 불필요(임시파일) — 다만 삭제는 finally 에서 보장
        fd, tmp = tempfile.mkstemp(suffix='.pdf')
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        out = subprocess.run(
            [PDFTOTEXT, '-enc', 'UTF-8', tmp, '-'],
            capture_output=True, timeout=60,
        )
        return out.stdout.decode('utf-8', errors='replace') if out.returncode == 0 else ''
    except Exception:
        return ''
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def _hwpx_to_text(data: bytes) -> str:
    """HWPX = ZIP+XML. Contents/section*.xml 태그 제거로 전문 추출 (실측 검증 #53)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        sections = sorted(n for n in zf.namelist()
                          if n.startswith('Contents/section') and n.endswith('.xml'))
        parts = []
        for name in sections:
            xml = zf.read(name).decode('utf-8', errors='replace')
            # 문단 경계를 개행으로 보존한 뒤 태그 제거
            xml = re.sub(r'</hp:p>', '\n', xml)
            txt = re.sub(r'<[^>]+>', '', xml)
            parts.append(html_mod.unescape(txt))
        return '\n'.join(parts)
    except Exception:
        return ''


def _html_main_text(page_html: str, url: str = '') -> str:
    if trafilatura is not None:
        try:
            out = trafilatura.extract(page_html, url=url or None,
                                      include_comments=False, include_tables=True)
            if out and len(out) >= BODY_MIN:
                return out
        except Exception:
            pass
    # 폴백: 태그 제거
    try:
        soup = BeautifulSoup(page_html, 'html.parser')
        for t in soup(['script', 'style', 'nav', 'header', 'footer']):
            t.decompose()
        return soup.get_text('\n', strip=True)
    except Exception:
        return ''


def _clean_body(text: str) -> str:
    if not text:
        return ''
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # HWPX 그림 대체텍스트 잡음 제거 ("그림입니다. / 원본 그림의 이름: ..." — 실측)
    text = re.sub(r'(?m)^\s*(그림입니다\.?|원본 그림의 이름\s*:.*|원본 그림의 크기\s*:.*)\s*$\n?', '', text)
    # 문서 내 '## YYMMDD ' 형태가 우연히 있으면 섹션 파서가 오인 — 이스케이프
    text = re.sub(r'(?m)^## (\d{6}) ', r'ㆍ## \1 ', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text[:BODY_MAX]


def _sniff_and_extract(data: bytes, filename: str = '') -> str:
    """바이트 시그니처로 PDF/HWPX 판별 후 추출. 구형 HWP(OLE)는 스킵('').
    PDF 텍스트층이 OCR_TRIGGER 미만이면 이미지-전용으로 보고 OCR 폴백(개선⑫)."""
    if not data or len(data) < 8:
        return ''
    if data[:4] == b'%PDF':
        txt = _pdf_to_text(data)
        if len((txt or '').strip()) < OCR_TRIGGER:
            ocr = _pdf_ocr_text(data)
            if len(ocr) >= OCR_ACCEPT:
                print('  [OCR 추출] 텍스트층 %d자 → OCR %d자 채택 (%s)'
                      % (len((txt or '').strip()), len(ocr), filename or 'pdf'))
                return ocr
        return txt
    if data[:2] == b'PK':
        return _hwpx_to_text(data)
    if data[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        return ''  # 구형 HWP(OLE) — 추출 불가, 호출자가 스킵 로그
    return ''


# ═══════════════════════════════════════════════════════
#  기관 어댑터
#  각 어댑터: list_pages(page) -> [item], extract(item) -> body(str)
#  item = {'title', 'url', 'date': datetime|None, ...어댑터 자유필드}
# ═══════════════════════════════════════════════════════

def _strip_jsession(href: str) -> str:
    return re.sub(r';jsessionid=[^?]*', '', href or '')


def _date_from_tds(row) -> str:
    for td in reversed(row.find_all('td')):
        t = td.get_text(strip=True)
        if re.fullmatch(r'\d{4}[-.]\d{1,2}[-.]\d{1,2}\.?', t):
            return t.rstrip('.')
    return ''


def _parse_dt(s: str):
    m = re.match(r'(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})', s or '')
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=KST)
    except ValueError:
        return None


# ── 과기정통부 (MSIT) ─────────────────────────────────

MSIT_LIST = 'https://www.msit.go.kr/bbs/list.do?sCode=user&mPid=208&mId=307&pageIndex=%d'
MSIT_DOWN = 'https://www.msit.go.kr/ssm/file/fileDown.do'


def msit_list(page: int) -> list:
    from urllib.parse import unquote
    res = _get(MSIT_LIST % page)
    h = res.text
    ids    = re.findall(r'onclick="fn_detail\((\d+)\);"', h)
    titles = re.findall(r"sHtml\+= unescape\('(.*?)'\);\s*sHtml\+= newHtml;", h, re.S)
    date_map = dict(re.findall(r"REG_DT'\+'_(\d+)'\)\.html\('(\d{4}-\d{2}-\d{2})'\)", h))
    m_bbs = re.search(r'name="bbsSeqNo"[^>]*value="(\d+)"', h)
    bbs_seq = m_bbs.group(1) if m_bbs else '94'
    items = []
    for i, (seq, raw_title) in enumerate(zip(ids, titles)):
        title = unquote(raw_title).strip()
        if not title:
            continue
        items.append({
            'title': title,
            'url': ('https://www.msit.go.kr/bbs/view.do?sCode=user&mId=307&mPid=208'
                    '&bbsSeqNo=%s&nttSeqNo=%s' % (bbs_seq, seq)),
            'date': _parse_dt(date_map.get(str(i), '')),
        })
    return items


def msit_extract(item: dict) -> str:
    """MSIT 상세는 본문 스텁 → 첨부(HWPX 우선, PDF 차선)에서 전문 추출."""
    res = _get(item['url'])
    soup = BeautifulSoup(res.text, 'html.parser')
    cands = []  # (우선순위, atchFileNo, fileOrd, 파일명/확장자)
    # 실측(2026-08-02): 첨부는 fn_download('atchFileNo','fileOrd','확장자') 3-인자 호출
    for m in re.finditer(r"fn_download\('(\d+)'\s*,\s*'(\d+)'\s*,\s*'(\w+)'\)", res.text):
        ext = m.group(3).lower()
        pri = {'hwpx': 0, 'pdf': 1, 'hwp': 3}.get(ext, 2)   # 구형 HWP는 마지막 수단
        cands.append((pri, m.group(1), m.group(2), ext))
    # 구버전 fn_download2 폴백 (파일명은 앵커 텍스트에서)
    for a in soup.find_all('a', onclick=re.compile(r'fn_download2')):
        m = re.search(r"fn_download2\('(\d+)'\s*,\s*'(\d+)'\)", a.get('onclick', ''))
        if not m:
            continue
        fname = a.get_text(' ', strip=True)
        low = fname.lower()
        if '.hwpx' in low:
            pri = 0
        elif '.pdf' in low:
            pri = 1
        elif '.hwp' in low:
            pri = 3
        else:
            pri = 2
        cands.append((pri, m.group(1), m.group(2), fname))
    best = ''
    for pri, no, ordn, fname in sorted(cands):
        data = _post_download(MSIT_DOWN, {'atchFileNo': no, 'fileOrd': ordn, 'fileBtn': 'A'},
                              referer=item['url'])
        body = _sniff_and_extract(data, fname)
        if body and len(body) > len(best):
            best = body
        if len(best) >= OCR_TRIGGER:   # 충분한 본문 확보 — 다음 첨부 불필요
            return best
    return best if len(best) >= BODY_MIN else ''


# ── 전파연구원 (RRA) — euc-kr ────────────────────────

RRA_LIST_BASE = 'https://www.rra.go.kr/ko/notice/newsList.do'
RRA_PAGE_PARAMS = ['?nowPage=%d', '?pageIndex=%d', '?cpage=%d']
_rra_param = [None]  # 실측으로 확정된 페이지 파라미터 캐시


def _rra_parse(html_text: str) -> list:
    soup = BeautifulSoup(html_text, 'html.parser')
    items = []
    for row in soup.select('table.board_list tbody tr, table tbody tr'):
        a = row.find('a')
        if not a:
            continue
        title = a.get_text(' ', strip=True)
        # 목록 앵커에 분류 라벨이 섞여 "보도 [보도] 제목" 형태가 됨(실측) — 접두 제거
        title = re.sub(r'^(?:보도\s*)?(?:\[보도\]\s*)?', '', title).strip()
        if not title or title.isdigit() or len(title) < 5:
            continue
        href = _strip_jsession(a.get('href', ''))
        if href.startswith('/'):
            href = 'https://www.rra.go.kr' + href
        elif href and not href.startswith('http'):
            href = RRA_LIST_BASE.rsplit('/', 1)[0] + '/' + href
        items.append({'title': title, 'url': href,
                      'date': _parse_dt(_date_from_tds(row))})
    return items


def rra_list(page: int) -> list:
    if page == 1:
        return _rra_parse(_get(RRA_LIST_BASE, encoding='euc-kr').text)
    if _rra_param[0] is None:
        page1_first = ([i['url'] for i in _rra_parse(_get(RRA_LIST_BASE, encoding='euc-kr').text)] or [''])[0]
        for p in RRA_PAGE_PARAMS:
            try:
                items = _rra_parse(_get(RRA_LIST_BASE + p % 2, encoding='euc-kr').text)
                if items and items[0]['url'] != page1_first:
                    _rra_param[0] = p
                    break
            except Exception:
                continue
        if _rra_param[0] is None:
            return []
    return _rra_parse(_get(RRA_LIST_BASE + _rra_param[0] % page, encoding='euc-kr').text)


def rra_extract(item: dict) -> str:
    res = _get(item['url'], encoding='euc-kr')
    return _html_main_text(res.text, item['url'])


# ── 방통위(kcc.go.kr) / 전파관리소(kmcc.go.kr) — 동일 CMS ──

# kcc.go.kr 페이지 파라미터는 cp (2026-08-02 후보 10개 실측 — cp만 목록이 바뀜)
KCC_LIKE_PAGE_PARAMS = ['&cp=%d', '&movePage=%d', '&pageIndex=%d', '&currentPage=%d']


def _kcc_like_parse(html_text: str, domain: str) -> list:
    soup = BeautifulSoup(html_text, 'html.parser')
    items = []
    for row in soup.select('table tbody tr'):
        a = row.find('a')
        if not a:
            continue
        title = a.get_text(' ', strip=True)
        if not title or title.isdigit() or len(title) < 5:
            continue
        href = _strip_jsession(a.get('href', ''))
        if href.startswith('/'):
            href = domain + href
        items.append({'title': title, 'url': href,
                      'date': _parse_dt(_date_from_tds(row))})
    return items


def _make_kcc_like(domain: str, list_url: str):
    param_cache = [None]

    def list_fn(page: int) -> list:
        if page == 1:
            return _kcc_like_parse(_get(list_url).text, domain)
        if param_cache[0] is None:
            first = ([i['url'] for i in _kcc_like_parse(_get(list_url).text, domain)] or [''])[0]
            for p in KCC_LIKE_PAGE_PARAMS:
                try:
                    items = _kcc_like_parse(_get(list_url + p % 2).text, domain)
                    if items and items[0]['url'] != first:
                        param_cache[0] = p
                        break
                except Exception:
                    continue
            if param_cache[0] is None:
                return []
        return _kcc_like_parse(_get(list_url + param_cache[0] % page).text, domain)

    def extract_fn(item: dict) -> str:
        res = _get(item['url'])
        soup = BeautifulSoup(res.text, 'html.parser')
        body = _html_main_text(res.text, item['url'])
        # 첨부 PDF 병합 (본문이 요약 수준인 경우가 많음 — 실측)
        pdf_text = ''
        for a in soup.find_all('a', href=True):
            href = a['href']
            label = a.get_text(' ', strip=True).lower()
            if '.pdf' not in label and 'pdf' not in href.lower():
                continue
            if not any(k in href for k in ('own', 'file', 'attach', 'Down')):
                # 다운로드성 링크가 아니면 스킵 (외부 pdf 링크 오탐 방지)
                if not href.lower().endswith('.pdf'):
                    continue
            full = href if href.startswith('http') else domain + href
            try:
                data = _get_download(full, referer=item['url'])
                pdf_text = _sniff_and_extract(data)
            except Exception:
                pdf_text = ''
            if pdf_text:
                break
        merged = (body or '') + ('\n\n' + pdf_text if pdf_text else '')
        return merged.strip()

    return list_fn, extract_fn


kcc_list, kcc_extract = _make_kcc_like(
    'https://www.kcc.go.kr',
    'https://www.kcc.go.kr/user.do?boardId=1113&page=A05030000&dc=K05030000')


# ── 전파관리소 (crms.go.kr) ──────────────────────────
# 주의: kmcc.go.kr 은 중앙전파관리소가 아니라 방송미디어통신위원회(방통위 개편 후 새 도메인)로,
# kcc.go.kr 과 동일 게시판 미러다(2026-08-02 목록 상위 5건 완전 일치 실측 — 배경역사 #53).
# 진짜 중앙전파관리소는 www.crms.go.kr — 보도자료 목록은 cpage 페이지네이션,
# 행 링크는 javascript:view('view.do','{article_seq}',...) 형태.

CRMS_LIST = 'https://www.crms.go.kr/lay1/bbs/S1T30C34/A/77/list.do?cpage=%d'
CRMS_VIEW = 'https://www.crms.go.kr/lay1/bbs/S1T30C34/A/77/view.do?article_seq=%s'


def crms_list(page: int) -> list:
    res = _get(CRMS_LIST % page)
    soup = BeautifulSoup(res.text, 'html.parser')
    items = []
    for row in soup.select('table tbody tr'):
        a = row.find('a')
        if not a:
            continue
        title = a.get_text(' ', strip=True)
        if not title or title.isdigit() or len(title) < 5:
            continue
        m = re.search(r"view\('view\.do'\s*,\s*'(\d+)'", a.get('href', ''))
        if not m:
            continue
        date = None
        for td in row.find_all('td'):
            dm = re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})', td.get_text(strip=True))
            if dm:
                date = _parse_dt(dm.group(0))
                break
        items.append({'title': title, 'url': CRMS_VIEW % m.group(1), 'date': date})
    return items


def crms_extract(item: dict) -> str:
    res = _get(item['url'])
    soup = BeautifulSoup(res.text, 'html.parser')
    body = _html_main_text(res.text, item['url'])
    pdf_text = ''
    for a in soup.find_all('a', href=True):
        href = a['href']
        label = a.get_text(' ', strip=True).lower()
        if 'download' not in href.lower() and '.pdf' not in label:
            continue
        full = href if href.startswith('http') else 'https://www.crms.go.kr' + href
        try:
            data = _get_download(full, referer=item['url'])
            pdf_text = _sniff_and_extract(data)
        except Exception:
            pdf_text = ''
        if pdf_text:
            break
    return ((body or '') + ('\n\n' + pdf_text if pdf_text else '')).strip()


# ── ETRI ──────────────────────────────────────────────

ETRI_LIST = 'https://www.etri.re.kr/kor/bbs/list.etri?b_board_id=ETRI06&nowPage=%d'


def etri_list(page: int) -> list:
    res = _get(ETRI_LIST % page)
    soup = BeautifulSoup(res.text, 'html.parser')
    items = []
    for row in soup.select('table tbody tr'):
        a = row.find('a')
        if not a:
            continue
        title = a.get_text(' ', strip=True)
        if not title or title.isdigit() or len(title) < 5:
            continue
        href = _strip_jsession(a.get('href', ''))
        if href.startswith('/'):
            href = 'https://www.etri.re.kr' + href
        elif href and not href.startswith('http'):
            href = 'https://www.etri.re.kr/kor/bbs/' + href
        items.append({'title': title, 'url': href,
                      'date': _parse_dt(_date_from_tds(row))})
    return items


def etri_extract(item: dict) -> str:
    res = _get(item['url'])
    return _html_main_text(res.text, item['url'])


# ── KISDI (kisdi.re.kr) ──────────────────────────────
# 목록은 서버렌더지만 행 링크가 href 가 아니라 onclick="goView('bbsSn','')" 이다
# (2026-08-02 실측 — 초기 "JS 렌더" 진단은 view.do href만 찾던 파서의 오진).
# 페이지네이션은 eGov 표준 fn_egov_link_page → POST list.do (pageIndex).

KISDI_BOARD_KEY = 'm2101113055776'   # 보도자료
KISDI_LIST_URL = 'https://www.kisdi.re.kr/bbs/list.do?key=' + KISDI_BOARD_KEY
KISDI_VIEW_URL = ('https://www.kisdi.re.kr/bbs/view.do?key=' + KISDI_BOARD_KEY
                  + '&bbsSn=%s')


def _kisdi_parse(html_text: str) -> list:
    soup = BeautifulSoup(html_text, 'html.parser')
    items, seen = [], set()
    for a in soup.find_all('a', onclick=re.compile(r"goView\('")):
        m = re.search(r"goView\('(\d+)'", a.get('onclick', ''))
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        strong = a.find('strong')
        title = (strong.get_text(' ', strip=True) if strong
                 else a.get_text(' ', strip=True))
        title = re.sub(r'^(공지|보도자료)\s*', '', title).strip()
        if not title or len(title) < 5:
            continue
        dm = re.search(r'등록일\s*(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})',
                       a.get_text(' ', strip=True))
        date = _parse_dt('%s-%s-%s' % dm.group(1, 2, 3)) if dm else None
        items.append({'title': title, 'url': KISDI_VIEW_URL % m.group(1), 'date': date})
    return items


def kisdi_list(page: int) -> list:
    if page == 1:
        return _kisdi_parse(_get(KISDI_LIST_URL).text)
    data = {'key': KISDI_BOARD_KEY, 'pageIndex': str(page), 'bbsSn': '', 'sc': '', 'sw': ''}
    for attempt in range(1, MAX_RETRY + 1):
        try:
            if USE_CURL_CFFI:
                res = requests.post(KISDI_LIST_URL, data=data,
                                    impersonate='chrome110', timeout=25)
            else:
                res = requests.post(KISDI_LIST_URL, data=data, headers=HEADERS, timeout=25)
            res.raise_for_status()
            res.encoding = 'utf-8'
            return _kisdi_parse(res.text)
        except Exception:
            if attempt < MAX_RETRY:
                time.sleep(RETRY_DELAY)
            else:
                raise


def kisdi_extract(item: dict) -> str:
    res = _get(item['url'])
    # 메인 폴백 경로는 목록에 날짜가 없음 — 상세 HTML의 첫 날짜 패턴으로 보완(실측 best-effort)
    if not item.get('date'):
        m = re.search(r'(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})', res.text)
        if m:
            item['date'] = _parse_dt('%s-%s-%s' % m.group(1, 2, 3))
    return _html_main_text(res.text, item['url'])


AGENCIES = {
    # slug: (표시명, list_fn, extract_fn)  — slug 가 doc_name 접두(기관 탭 기준)
    '과기정통부':  ('과학기술정보통신부', msit_list, msit_extract),
    '전파연구원':  ('국립전파연구원',     rra_list,  rra_extract),
    '방통위':      ('방송통신위원회',     kcc_list,  kcc_extract),
    '전파관리소':  ('중앙전파관리소',     crms_list, crms_extract),
    'ETRI':        ('한국전자통신연구원', etri_list, etri_extract),
    'KISDI':       ('정보통신정책연구원', kisdi_list, kisdi_extract),
}


# ═══════════════════════════════════════════════════════
#  등재 (document_chunks)
# ═══════════════════════════════════════════════════════

def _like_escape(s: str) -> str:
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _chunk_text(text: str, size: int = CHUNK_SIZE) -> list:
    """size 근처의 개행에서 끊는 무겹침 분할 (기존 수동분과 동일한 이어붙임 복원 전제)."""
    chunks = []
    pos = 0
    n = len(text)
    while pos < n:
        end = min(pos + size, n)
        if end < n:
            nl = text.rfind('\n', pos + int(size * 0.7), end)
            if nl > pos:
                end = nl + 1
        chunks.append(text[pos:end])
        pos = end
    return [c for c in chunks if c.strip()]


def section_exists(sb, doc_name: str, ymd6: str, title: str) -> bool:
    pat = '%%## %s %s%%' % (ymd6, _like_escape(title[:25]))
    try:
        rows = sb.table('document_chunks').select('id').eq('doc_name', doc_name) \
            .like('content', pat).limit(1).execute().data
        return bool(rows)
    except Exception as e:
        print('  [dedupe 조회 오류 — 중복 방지 위해 스킵 처리] %s' % e)
        return True   # 조회 실패 시 등재하지 않음(중복 유입 방지 우선)


def _doc_max_index(sb, doc_name: str) -> int:
    """문서의 최대 chunk_index. 문서 없으면 -1. (정렬 명시 — 무정렬 limit 함정 회피)"""
    rows = sb.table('document_chunks').select('chunk_index').eq('doc_name', doc_name) \
        .order('chunk_index', desc=True).limit(1).execute().data
    return rows[0]['chunk_index'] if rows else -1


def register_kb_section(sb, doc_name: str, doc_category: str, ymd6: str, title: str,
                        body: str, url: str, doc_header: str = '') -> bool:
    """본문 1건을 doc_name 문서에 '## YYMMDD 제목' 섹션으로 추가. 신규 등재 시 True.
    body 정제(절단·이스케이프)는 호출자 책임 — 여기서는 그대로 등재한다.
    doc_header 는 문서가 처음 생성될 때만 앞에 붙는 프리앰블('# ...' 시작)."""
    if section_exists(sb, doc_name, ymd6, title):
        return False
    max_idx = _doc_max_index(sb, doc_name)
    section = '## %s %s\n\n%s\n\n(원문: %s)\n\n' % (ymd6, title, body, url)
    if max_idx < 0 and doc_header:
        section = doc_header + section
    rows = []
    for i, chunk in enumerate(_chunk_text(section)):
        rows.append({
            'doc_name':     doc_name,
            'doc_category': doc_category,
            'chunk_index':  max_idx + 1 + i,
            'content':      chunk,
            'is_approved':  True,
            'status':       'current',
        })
    sb.table('document_chunks').insert(rows).execute()
    return True


def register_press(sb, agency: str, dt: datetime, title: str, body: str, url: str) -> bool:
    """보도자료 1건을 연도별 MD 문서에 섹션으로 추가. 신규 등재 시 True."""
    doc_name = '%s_보도자료_%d.md' % (agency, dt.year)
    display = AGENCIES.get(agency, (agency,))[0]
    doc_header = ('# %s 보도자료 %d년\n\n> 출처: %s 보도자료 자동 수집\n\n---\n\n'
                  % (agency, dt.year, display))
    return register_kb_section(sb, doc_name, '보도자료', dt.strftime('%y%m%d'),
                               title, _clean_body(body), url, doc_header)


# ═══════════════════════════════════════════════════════
#  실행 루틴
# ═══════════════════════════════════════════════════════

def _heartbeat(sb, note: str):
    try:
        sb.table('system_health').upsert(
            {'key': 'last_press_ingest',
             'updated_at': datetime.now(timezone.utc).isoformat(),
             'note': note},
            on_conflict='key').execute()
    except Exception as e:
        print('[heartbeat 오류] %s' % e)


def _collect_one(sb, slug: str, item: dict, extract_fn, stats: dict, dry: bool = False,
                 judge=None) -> bool:
    body = None
    # 목록에 날짜가 없는 기관(KISDI 메인 폴백)은 상세 추출이 날짜를 채우므로 추출을 먼저
    if not item.get('date'):
        try:
            body = extract_fn(item)
        except Exception as e:
            print('  [추출 오류] %s: %s' % (item['title'][:40], str(e)[:80]))
            stats['fail'] += 1
            return False
    dt = item.get('date') or datetime.now(KST)
    ymd6 = dt.strftime('%y%m%d')
    doc_name = '%s_보도자료_%d.md' % (slug, dt.year)
    if section_exists(sb, doc_name, ymd6, item['title']):
        stats['dup'] += 1
        return False
    try:
        if body is None:
            body = extract_fn(item)
    except Exception as e:
        print('  [추출 오류] %s: %s' % (item['title'][:40], str(e)[:80]))
        stats['fail'] += 1
        return False
    if not body or len(body) < BODY_MIN:
        print('  [추출 실패·스킵] %s (%d자)' % (item['title'][:40], len(body or '')))
        stats['fail'] += 1
        return False
    if judge is not None:
        ok, reason = judge(item['title'], body)
        if not ok:
            stats['skip'] = stats.get('skip', 0) + 1
            print('  [무관 스킵] %s — %s' % (item['title'][:40], reason))
            return False
    if dry:
        print('  [dry-run] %s | %s | %d자' % (ymd6, item['title'][:50], len(body)))
        stats['new'] += 1
        return True
    if register_press(sb, slug, dt, item['title'], body, item['url']):
        print('  [등재] %s %s (%d자)' % (ymd6, item['title'][:50], len(body)))
        stats['new'] += 1
        return True
    stats['dup'] += 1
    return False


def run_daily(sb, keywords: list = None, max_per_agency: int = 15, dry: bool = False) -> int:
    """매일 17시: 각 기관 목록 1~2페이지의 최근 15일분을 **전수** 수집·추출 후
    Haiku 관련성 판정으로 등재 여부 결정 (운영자 결정 2026-08-02).
    API 사용 불가 시 기존 제목 키워드 방식으로 폴백(fail-open)."""
    kw = keywords or load_press_keywords(sb)
    judge = make_ai_judge(sb, kw)
    mode = '전수+AI판정' if judge else '키워드(AI 불가 폴백)'
    print('[보도자료 수집] 모드=%s, 키워드 %d개' % (mode, len(kw)))
    total_stats = {'new': 0, 'dup': 0, 'fail': 0, 'skip': 0}
    for slug, (display, list_fn, extract_fn) in AGENCIES.items():
        stats = {'new': 0, 'dup': 0, 'fail': 0, 'skip': 0}
        items, seen = [], set()
        for page in (1, 2):   # 게시가 많은 날 1페이지(10건)를 넘길 수 있어 2페이지까지
            try:
                for it in list_fn(page):
                    if it['url'] not in seen:
                        seen.add(it['url'])
                        items.append(it)
            except Exception as e:
                print('[보도자료][%s] %d페이지 목록 오류: %s' % (slug, page, str(e)[:80]))
                break
        recent = []
        for it in items:
            if it['date'] and (datetime.now(KST) - it['date']).days > 15:
                continue
            recent.append(it)
        # AI 판정 모드면 전수, 폴백 모드면 제목 키워드 매칭분만
        candidates = recent if judge else [it for it in recent
                                           if any(k in it['title'] for k in kw)]
        for it in candidates[:max_per_agency]:
            _collect_one(sb, slug, it, extract_fn, stats, dry=dry, judge=judge)
            time.sleep(1)
        print('[보도자료][%s] 스캔 %d, 최근 %d, 신규 %d, 중복 %d, 무관 %d, 실패 %d'
              % (slug, len(items), len(recent), stats['new'], stats['dup'],
                 stats['skip'], stats['fail']))
        for k in total_stats:
            total_stats[k] += stats[k]
        time.sleep(1)
    note = 'mode=%s new=%d dup=%d skip=%d fail=%d' % (
        'ai' if judge else 'kw', total_stats['new'], total_stats['dup'],
        total_stats['skip'], total_stats['fail'])
    print('[보도자료 수집 완료] ' + note)
    if not dry:
        _heartbeat(sb, note)
    return total_stats['new']


def run_backfill(sb, since: datetime, agencies: list = None, keywords: list = None,
                 max_pages: int = 600, dry: bool = False) -> dict:
    """since 이후 전 기간 백필. 재실행 안전(섹션 dedupe). 기관별 페이지 순회."""
    kw = keywords or load_press_keywords(sb)
    targets = agencies or list(AGENCIES.keys())
    print('[백필] 기관 %s, 기준일 %s, 키워드 %d개'
          % (','.join(targets), since.strftime('%Y-%m-%d'), len(kw)))
    grand = {}
    for slug in targets:
        display, list_fn, extract_fn = AGENCIES[slug]
        stats = {'new': 0, 'dup': 0, 'fail': 0, 'scanned': 0, 'pages': 0}
        seen_urls = set()
        seen_sigs = set()
        stop = False
        for page in range(1, max_pages + 1):
            try:
                items = list_fn(page)
            except Exception as e:
                print('[백필][%s] %d페이지 오류: %s' % (slug, page, str(e)[:80]))
                break
            if not items:
                break
            # 마지막 페이지 초과 시 같은 내용을 반복 반환하는 게시판(ETRI 실측) 방어:
            # URL에 페이지 번호가 붙어 '새 URL'로 보여도 제목 조합이 같으면 순환으로 판정
            sig = tuple(it['title'] for it in items)
            if sig in seen_sigs:
                print('[백필][%s] %d페이지: 목록 반복 감지 — 종료' % (slug, page))
                break
            seen_sigs.add(sig)
            fresh = [it for it in items if it['url'] not in seen_urls]
            if not fresh:
                break   # 페이지 파라미터가 안 먹혀 같은 페이지 반복 → 종료
            seen_urls.update(it['url'] for it in fresh)
            stats['pages'] = page
            stats['scanned'] += len(fresh)
            dated = [it for it in fresh if it['date']]
            # 페이지 전체가 기준일 이전이면 다음 페이지는 더 오래됨 → 종료
            if dated and all(it['date'] < since for it in dated):
                stop = True
            for it in fresh:
                if it['date'] and it['date'] < since:
                    continue
                if not any(k in it['title'] for k in kw):
                    continue
                _collect_one(sb, slug, it, extract_fn, stats, dry=dry)
                time.sleep(0.8)
            print('[백필][%s] %d페이지: 누적 신규 %d, 중복 %d, 실패 %d'
                  % (slug, page, stats['new'], stats['dup'], stats['fail']))
            if stop:
                break
            time.sleep(1)
        grand[slug] = stats
        print('[백필][%s] 완료 — 페이지 %d, 스캔 %d, 신규 %d, 중복 %d, 실패 %d'
              % (slug, stats['pages'], stats['scanned'],
                 stats['new'], stats['dup'], stats['fail']))
    return grand


if __name__ == '__main__':
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    from sb_client import make_client

    ap = argparse.ArgumentParser()
    ap.add_argument('--backfill', action='store_true')
    ap.add_argument('--since', default='2024-01-01')
    ap.add_argument('--agency', default='', help='기관 slug 쉼표 구분 (기본 전체)')
    ap.add_argument('--max-per-agency', type=int, default=10)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    if args.backfill:
        since = datetime.strptime(args.since, '%Y-%m-%d').replace(tzinfo=KST)
        agencies = [a for a in args.agency.split(',') if a] or None
        run_backfill(sb, since, agencies=agencies, dry=args.dry_run)
    else:
        run_daily(sb, max_per_agency=args.max_per_agency, dry=args.dry_run)
