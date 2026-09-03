#!/usr/bin/env python3
"""
국회 과방위(과학기술정보방송통신위원회) 회의록 수집기
열린국회정보 Open API '위원회 회의록'(ncwgseseafwbuheph)으로 회의 목록을 조회하고,
국회회의록시스템(record.assembly.go.kr) 뷰어 HTML에서 발언자 단위 원문을 추출해
통신·전파·AI 정책 관련 발언만 골라 Supabase document_chunks(doc_category='회의록',
doc_name='과방위_회의록_{YYYY}.md')에 섹션으로 등재한다.

원문 확보 경로 (2026-08-02 실측):
  1순위 — 뷰어 HTML: https://record.assembly.go.kr/assembly/viewer/minutes/xml.do?id={CONFER_NUM}&type=view
          div.speaker[data-name][data-pos] > div.talk 구조로 발언 블록이 깨끗하게 분리됨.
  2순위 — PDF_LINK_URL + pdftotext(press_ingest._pdf_to_text): 국회 PDF는 폰트 문제로
          중반부 글리프가 깨지는 사례가 있어(실측) 뷰어 실패 시 폴백으로만 사용.
  교차 검증(2026-09-03) — 뷰어가 **다른 회의의 본문**을 돌려주는 id 가 있다(2017/41948·42378, 2018/43150
          실측; PDF 는 정상). 상임위 회의는 looks_foreign_committee + verify_blocks_against_pdf 로
          뷰어 블록을 PDF 와 대조해 불일치면 PDF 블록으로 갈아탄다(src='PDF(뷰어 불일치)').

국정감사 회의록은 별도 경로다 (2026-08-13 추가, 22대만).
  위 Open API 는 CLASS_NAME='상임위원회' 인 회의록만 돌려준다(실측 — 2019년 과방위 41건을
  전수 조회해도 국감 0건, CLASS_NAME='국정감사' 질의도 0건). 10월에 잡히는 건 "국정감사
  증인 출석요구의 건"을 처리한 짧은 전체회의일 뿐 감사 본체가 아니다.
  국감 회의록은 국회회의록시스템 검색(collection='record5')에만 있고 뷰어 id 체계도 달라
  (API CONFER_NUM 52648 계열 ≠ 국감 MNTS_ID) 목록 조회를 따로 만들었다. 원문 파싱부터는
  같은 뷰어 구조라 기존 함수를 그대로 재사용한다.

관련 발언 추출: 1차 키워드(app_config.press_keywords) 매칭 블록 →
2차 Haiku 판정(app_config.press_relevance_criteria 재사용)으로 확정 →
확정 블록 + 전후 1블록을 발췌(블록당 1,500자 절단)로 섹션에 수록.

임베딩은 여기서 만들지 않는다(기존 backfill_embeddings 체인이 처리).
텔레그램 발송 없음. PC 실행 전제(스케줄러 등록은 별도).
"""

import os
import re
import sys
import time
import argparse
from datetime import datetime, timezone, timedelta

# Windows 스케줄러/cp949 콘솔에서 이모지·특수문자 print 크래시 방지 (배경역사 #19)
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

import requests
from bs4 import BeautifulSoup

from sb_client import make_client
from press_ingest import (
    load_press_keywords, make_ai_judge, register_kb_section, section_exists,
    _pdf_to_text, _like_escape, _doc_max_index,
)

KST = timezone(timedelta(hours=9))

# ── 실측 확정 상수 (2026-08-02, 배경역사 참고) ──────────────────
# 열린국회정보 '위원회 회의록' API. 필수: KEY, DAE_NUM, CONF_DATE(연도 검색어).
# 응답 row 는 회의 1건이 아니라 "안건 1건" — CONFER_NUM 으로 회의 단위 그룹핑 필요.
API_MINUTES = 'https://open.assembly.go.kr/portal/openapi/ncwgseseafwbuheph'
# 회의록별 상세정보(일시·장소·시각) — CONF_ID 필수. 실패해도 치명적이지 않음.
API_DETAIL = 'https://open.assembly.go.kr/portal/openapi/VCONFDETAIL'
VIEWER_URL = ('https://record.assembly.go.kr/assembly/viewer/minutes/xml.do'
              '?id=%s&type=view')

DAE_NUM = '22'                       # 22대 국회 (현행 기본값 — 소급 조회는 아래 표)
COMM_NAME = '과학기술정보방송통신위원회'
DOC_CATEGORY = '회의록'

# 연도 → (Open API DAE_NUM, 위원회명 후보). 상임위 회의록 API는 DAE_NUM·COMM_NAME이 필수라
# 20·21대 소급(2026-09-03 운영자 지시)은 표로 고정한다(국감 AUDIT_DAE_TABLE과 같은 이유).
# **20대 전반기(~2017-07-26)는 '미래창조과학방송통신위원회'** — 실측: 2016년은 미방위 명칭으로만
# 17건, 2017년은 두 명칭에 각각 11건·16건이 잡힌다. 임기 교체연도(2020·2024, 5/30)는 두 대를
# 모두 질의하고 CONFER_NUM으로 합친다. 23대 개원 시 한 줄 추가할 것.
COMMITTEE_DAE_TABLE = [
    (2016, 2020, '20', ['미래창조과학방송통신위원회', '과학기술정보방송통신위원회']),
    (2020, 2024, '21', ['과학기술정보방송통신위원회']),
    (2024, 2099, '22', ['과학기술정보방송통신위원회']),
]


def committee_queries_for(year: int) -> list:
    """해당 연도에 던질 (DAE_NUM, COMM_NAME) 쌍 목록. 표에 없으면 현행 상수 1쌍."""
    out = []
    for lo, hi, dae, comms in COMMITTEE_DAE_TABLE:
        if lo <= year <= hi:
            out.extend((dae, c) for c in comms)
    return out or [(DAE_NUM, COMM_NAME)]


# 일일 경로(17시 체인)의 AI 모델 — 2026-09-03 Haiku → Sonnet 5 (운영자 결정).
# Haiku는 영문 거절문이 요지로 저장된 사고(#99)와 무내용 요약이 실측됐다. 월 7회 남짓이라
# 비용 차이는 월 $1 수준. **비스트리밍 호출은 thinking을 꺼야 한다** — Sonnet 5는 적응형
# 추론이 기본 ON이라 사고 토큰이 과금되고 content[0]이 text가 아니게 된다(메모리 함정).
MINUTES_MODEL = 'claude-sonnet-5'
MINUTES_THINKING = {'type': 'disabled'}

BLOCK_TRUNC = 1500                   # 발언 블록당 발췌 상한(자)
MAX_JUDGE_BLOCKS = 40                # 회의당 AI 판정 상한 (비용·시간 방어)
MAX_EXCERPTS = 30                    # 회의당 수록 발췌 상한
MAX_AGENDA_LINES = 15                # 개요의 안건 나열 상한

# 구독자 다이제스트(텔레그램 '국회·법률 동향', 2026-09-03) 가드.
# 백필·재요약 경로에서 큐가 폭주하지 않도록 **신규 섹션 + 최근 60일 + 실질 회의**만 적재한다.
DIGEST_MAX_AGE_DAYS = 60
DIGEST_MIN_SPEECHES = 3

# 자사 언급 표시 — AI 판정이 아니라 **원문 블록에 ALWAYS_KEEP_TERMS가 있는지**로 결정한다(규칙).
# 회의 요약 줄 끝에는 SKT_SUFFIX, 발언 topic에는 SKT_CHIP(대시보드가 콤마 분리 칩으로 렌더).
SKT_CHIP = 'SK텔레콤 언급'
SKT_SUFFIX = ' (SK텔레콤 언급)'
OVERVIEW_MARK = '개요:'              # 섹션 본문의 회의 개요 블록 머리(대시보드 상세가 파싱)

# ── 국정감사 회의록 (2026-08-13 추가, 22대 전용) ────────────────
# 검색 폼 실측: collection='record5' + CLASS_CD='5' 여야 국감 컬렉션이 조회된다.
# collection='record'(상임위)로 보내면 200 + 빈 JSON({})이 와서 '결과 없음'과 구분되지 않는다.
AUDIT_SEARCH_PAGE = 'https://record.assembly.go.kr/assembly/mnts/minutes/search.do'
AUDIT_SEARCH_API = 'https://record.assembly.go.kr/assembly/mnts/search/search.do'
AUDIT_TH = '24'                      # 검색 폼의 대수 코드(24=제22대). Open API 의 DAE_NUM='22' 과 별개 체계 — 혼동 주의.
AUDIT_CMIT_CD = '22-5-AG'            # 22대 과방위 국정감사(폼 기본값). 소급 조회는 아래 표를 쓴다.

# 연도 → (검색폼 대수코드, 과방위 국정감사 CMIT_CD 목록). 2026-08-14 검색폼에서 직접 추출.
# 위원회 코드는 대(代)마다 재배정되고 폼은 '선택된 대'의 목록만 노출하므로, 소급 조회에서는
# 자동 탐지가 불가능하다 — 표로 고정한다. 23대 개원 시 한 줄 추가할 것.
# **20대는 전반기 명칭이 미래창조과학방송통신위원회(RN)**라 두 코드를 함께 넣어야
# 2016~2018년이 빠지지 않는다(실측: 단일 코드로는 그 3년이 통째로 누락).
AUDIT_DAE_TABLE = [
    (2016, 2019, '22', ['20-5-AB-0', '20-5-RN-0']),   # 제20대 (과방위 + 미방위)
    (2020, 2023, '23', ['21-5-AK-0']),                # 제21대
    (2024, 2027, '24', ['22-5-AG-0']),                # 제22대
]


def audit_dae_for(year: int):
    """해당 연도의 (대수코드, CMIT_CD CSV). 표에 없으면 (None, None).
    국감은 10월에 열려 임기 교체월(5월)과 겹치지 않으므로 연도만으로 안전하게 가른다."""
    for lo, hi, th, cmits in AUDIT_DAE_TABLE:
        if lo <= year <= hi:
            return th, ','.join(cmits)
    return None, None
# 열거용 질의어. 회의록 본문 검색이라 '모든 국감 회의에 반드시 나오는 낱말'이어야 한다.
# '산회'로 줄여보려 했으나 2024년 10건 중 2건, 2025년 9건 중 0건만 잡혔다(실측) — 산회 선포가
# 발언 블록이 아니라 회의록 표기로만 남는 경우가 많다. 히트가 많아도 '국정감사'를 쓴다.
AUDIT_ENUM_QUERY = '국정감사'
AUDIT_PAGE_SIZE = 10                 # 검색 응답 고정 페이지 크기(서버 고정, 조절 불가)
AUDIT_MAX_PAGES = 200                # 연 800히트=80페이지 실측 → 여유 상한
AUDIT_PDF_URL = ('https://record.assembly.go.kr/assembly/viewer/minutes/'
                 'download/pdf.do?id=%s')
AUDIT_CONFER_PREFIX = 'audit-'       # assembly_speeches.confer_num 네임스페이스(상임위 번호와 값 충돌 방지)
AUDIT_MIN_YEAR = 2016                # 20대 개원(2016-05-30) — 소급 하한 (운영자 지시 2026-08-14)
# 국감은 회의 1건이 2,000블록을 넘어(2019년 실측 2,146) 상임위 상한이면 앞부분만 보고 잘린다.
AUDIT_MAX_JUDGE_BLOCKS = 80
AUDIT_MAX_EXCERPTS = 50

# 주제 무관 무조건 수록 대상 (운영자 지시 2026-08-13).
# 자사 언급은 키워드·AI 판정으로 거르지 않는다 — 판정이 '통신정책 아님'으로 봐도 우리에겐 자료다.
ALWAYS_KEEP_TERMS = ['SK텔레콤', 'SK 텔레콤', '에스케이텔레콤', 'SKT', 'sk텔레콤']

HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/124.0.0.0 Safari/537.36'),
    'Accept-Language': 'ko-KR,ko;q=0.9',
}


# ═══════════════════════════════════════════════════════════
#  API 조회
# ═══════════════════════════════════════════════════════════

def _api_get(url: str, params: dict, retries: int = 3) -> dict:
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt < retries:
                print('  [재시도 %d/%d] %s' % (attempt, retries, str(e)[:80]))
                time.sleep(5)
            else:
                raise


def _rows_of(data: dict, api_id: str) -> list:
    """{api_id: [{head:[...]},{row:[...]}]} 구조에서 row 목록 추출."""
    for item in data.get(api_id, []):
        if 'row' in item:
            return item['row']
    return []


def fetch_meetings(api_key: str, year: int) -> list:
    """해당 연도 과방위 회의 목록. 안건 단위 row 를 CONFER_NUM 으로 회의 단위 그룹핑.
    반환: [{'confer_num','title','conf_date','sess','dgr','agenda',
            'pdf_url','conf_id'}] (최신 회의 먼저)."""
    by_conf: dict = {}
    for dae, comm in committee_queries_for(year):
        page, psize = 1, 300
        while True:
            data = _api_get(API_MINUTES, {
                'KEY': api_key, 'Type': 'json', 'pIndex': page, 'pSize': psize,
                'DAE_NUM': dae, 'CONF_DATE': str(year), 'COMM_NAME': comm,
            })
            rows = _rows_of(data, 'ncwgseseafwbuheph')
            for r in rows:
                num = r.get('CONFER_NUM')
                if not num:
                    continue
                m = by_conf.get(num)
                if m is None:
                    title = (r.get('TITLE') or '').strip()
                    sm = re.search(r'제(\d+)회\s*제(\d+)차', title)
                    m = by_conf[num] = {
                        'confer_num': num,
                        'title':      title,
                        'conf_date':  (r.get('CONF_DATE') or '').strip(),
                        'sess':       sm.group(1) if sm else '',
                        'dgr':        sm.group(2) if sm else '',
                        'agenda':     [],
                        'pdf_url':    (r.get('PDF_LINK_URL') or '').strip(),
                        'conf_id':    (r.get('CONF_ID') or '').strip(),
                        'dae_num':    dae,
                        'comm_name':  comm,
                    }
                sub = (r.get('SUB_NAME') or '').strip()
                if sub and sub not in m['agenda']:
                    m['agenda'].append(sub)
            if len(rows) < psize:
                break
            page += 1
            time.sleep(0.3)
    meetings = list(by_conf.values())
    meetings.sort(key=lambda m: (m['conf_date'], int(m['dgr'] or 0)), reverse=True)
    return meetings


def fetch_detail(api_key: str, conf_id: str) -> dict:
    """VCONFDETAIL 로 일시·장소·시각 보강. 실패 시 빈 dict (개요는 목록 정보로 대체)."""
    if not conf_id:
        return {}
    try:
        data = _api_get(API_DETAIL, {'KEY': api_key, 'Type': 'json',
                                     'pIndex': 1, 'pSize': 5, 'CONF_ID': conf_id},
                        retries=1)
        rows = _rows_of(data, 'VCONFDETAIL')
        return rows[0] if rows else {}
    except Exception as e:
        print('  [상세정보 실패(무시)] %s: %s' % (conf_id, str(e)[:60]))
        return {}


# ═══════════════════════════════════════════════════════════
#  국정감사 회의록 목록 (국회회의록시스템 검색)
# ═══════════════════════════════════════════════════════════

def _audit_session():
    """검색 폼을 1회 로드해 세션 쿠키 + 과방위 국감 CMIT_CD + 회기 범위를 얻는다.
    코드는 대(代)마다 재배정되므로(20대 과방위 국감=20-5-AB-0, 22대=22-5-AG) 하드코딩하지
    않고 폼에서 읽는다. 파싱 실패 시에만 상수로 폴백.
    반환: (session, cmit_cd, s_sess, e_sess)"""
    sess = requests.Session()
    cmit, s_sess, e_sess = AUDIT_CMIT_CD, '', ''
    try:
        html = sess.get(AUDIT_SEARCH_PAGE, headers=HEADERS, timeout=30).text
        soup = BeautifulSoup(html, 'html.parser')
        ul = soup.find(id='com5List')          # com5 = 국정감사 그룹
        for lab in (ul.find_all('label') if ul else []):
            if COMM_NAME not in lab.get_text():
                continue
            inp = soup.find(id=lab.get('for'))
            if inp is not None and inp.get('value'):
                cmit = inp['value']
            break
        opts = [o.get('value') for o in
                (soup.find(id='ssess_sch').find_all('option')
                 if soup.find(id='ssess_sch') else []) if o.get('value')]
        if opts:
            s_sess, e_sess = opts[0], opts[-1]
    except Exception as e:
        print('  [검색폼 파싱 실패 — 상수 폴백] %s' % str(e)[:70])
    return sess, cmit, s_sess, e_sess


def _audit_search(sess, payload: dict, page: int) -> dict:
    """검색 API 1페이지. startCount 가 1-base 페이지 번호(페이지당 10건)."""
    body = dict(payload)
    body['startCount'] = page
    hdr = dict(HEADERS)
    hdr['X-Requested-With'] = 'XMLHttpRequest'
    hdr['Referer'] = AUDIT_SEARCH_PAGE
    r = sess.post(AUDIT_SEARCH_API, data=body, headers=hdr, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_audit_meetings(year: int) -> list:
    """해당 연도 과방위 국정감사 회의 목록.
    검색 결과는 '발언' 단위라 MNTS_ID(=뷰어 id)로 회의 단위로 접는다.
    반환 dict 는 상임위 경로와 같은 모양 + is_audit/viewer_id/audit_nm."""
    th, cmit = audit_dae_for(year)
    if not th:
        print('  [국감 스킵] %d년은 대수 표에 없음 (AUDIT_DAE_TABLE 확인)' % year)
        return []
    sess, _auto_cmit, _s, _e = _audit_session()   # 세션 쿠키 확보용(코드는 표를 쓴다)
    # 회기(S_SESS/E_SESS)는 대수(S_TH/E_TH) + 날짜 범위로 이미 좁혀지므로 전 구간을 연다.
    # 폼에서 읽은 회기값은 '현재 선택된 대'의 것이라 소급 조회에 그대로 쓰면 어긋난다.
    payload = {
        'query': AUDIT_ENUM_QUERY, 'searchField': 'SPK_CNTS',
        'collection': 'record5', 'CLASS_CD': '5', 'CMIT_CD': cmit,
        'S_TH': th, 'E_TH': th, 'S_SESS': '1', 'E_SESS': '9999',
        # 날짜 범위를 안 주면 22대 전체(1,500+ 히트)에서 최신순으로만 훑게 돼
        # 재작년 국감이 페이지 상한 밖으로 밀려 조용히 0건이 된다(실측 — 2024년 누락).
        'startDate': '%d-01-01' % year, 'endDate': '%d-12-31' % year,
        'SPK_NM': '', 'SPKSAME': 'N', 'BILL_NO': '', 'sort': 'DATE/DESC',
    }
    by_id: dict = {}
    total = None
    for page in range(1, AUDIT_MAX_PAGES + 1):
        try:
            data = _audit_search(sess, payload, page)
        except Exception as e:
            print('  [국감 목록 조회 실패 p%d] %s' % (page, str(e)[:70]))
            break
        rec = (data or {}).get('record5') or {}
        rows = rec.get('resultList') or []
        if total is None:
            total = int(rec.get('totalCount') or 0)
            print('  [국감 검색] CMIT_CD=%s, 발언 히트 %d건' % (cmit, total))
        for r in rows:
            mid = str(r.get('MNTS_ID') or '').strip()
            rdate = str(r.get('RDATE') or '').strip()
            if not mid or len(rdate) != 8 or rdate[:4] != str(year) or mid in by_id:
                continue
            conf_date = '%s-%s-%s' % (rdate[:4], rdate[4:6], rdate[6:])
            audit_nm = (r.get('AUDIT_NM') or '').strip()
            sess_no = (r.get('SESS') or '').strip()
            cmit_nm = (r.get('CMIT_NM') or COMM_NAME).strip()
            title = '%s 제%s회 %s 국정감사 (%s년 %s월 %s일)' % (
                (r.get('TH_TEXT') or '제22대').strip(), sess_no, cmit_nm,
                rdate[:4], rdate[4:6], rdate[6:])
            by_id[mid] = {
                'confer_num': AUDIT_CONFER_PREFIX + mid,   # 저장·dedupe 키
                'viewer_id':  mid,                          # 원문·링크용
                'is_audit':   True,
                'audit_nm':   audit_nm,
                'title':      title,
                'conf_date':  conf_date,
                'sess':       sess_no,
                'dgr':        '',
                'agenda':     ['1. %s년도 국정감사%s'
                               % (rdate[:4], (' (%s)' % audit_nm[:300]) if audit_nm else '')],
                'pdf_url':    AUDIT_PDF_URL % mid,
                'conf_id':    '',
            }
        if len(rows) < AUDIT_PAGE_SIZE or (total and page * AUDIT_PAGE_SIZE >= total):
            break
        time.sleep(0.15)
    meetings = list(by_id.values())
    meetings.sort(key=lambda m: m['conf_date'], reverse=True)
    return meetings


# ═══════════════════════════════════════════════════════════
#  원문(발언 블록) 확보
# ═══════════════════════════════════════════════════════════

VIEWER_RETRIES = 3       # 부분 응답 방어. 3회 중 가장 많이 받은 것을 쓴다.
VIEWER_SHORT_RATIO = 0.9  # 직전 최대치의 이 비율 미만이면 '덜 받았다'로 보고 한 번 더


def fetch_speech_blocks(confer_num) -> list:
    """뷰어 HTML에서 발언자 단위 블록 추출.
    반환: [{'name','pos','text'}] — 실패·빈 결과 시 [].

    ⚠️ 뷰어는 **간헐적으로 페이지를 덜 보낸다**(실측: 같은 id 51996이 3,449블록 ↔ 432/363블록).
    한 번만 받으면 그 시점에 걸린 회의가 **잘린 채 등재**되고, section_exists 가 헤더만 보고
    dup 처리해 **영구히 갱신되지 않는다**(2026-08-14 실제 사고). 그래서 best-of-N 으로 받는다."""
    best: list = []
    for i in range(VIEWER_RETRIES):
        try:
            got = _fetch_speech_blocks_once(confer_num)
        except Exception as e:                      # 네트워크 흔들림은 재시도로 흡수
            print(f'  [뷰어 {i + 1}회차 실패] {e}')
            continue
        if len(got) > len(best):
            best = got
        # 두 번째 이후로 직전 최대치에 근접한 응답이 다시 나오면 그 크기를 신뢰한다.
        # (1회차만으로는 그게 전부인지 잘린 것인지 알 방법이 없어 최소 2회는 받는다.)
        if i >= 1 and best and len(got) >= len(best) * VIEWER_SHORT_RATIO:
            break
    return best


def _fetch_speech_blocks_once(confer_num) -> list:
    url = VIEWER_URL % confer_num
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    blocks = []
    for sp in soup.select('div.speaker'):
        name = (sp.get('data-name') or '').strip()
        pos = (sp.get('data-pos') or '').strip()
        talk = sp.select_one('div.talk')
        if not name or talk is None:
            continue
        txt = talk.get_text('\n', strip=True).replace('\xa0', ' ')
        txt = re.sub(r'\n{2,}', '\n', txt).strip()
        if txt:
            blocks.append({'name': name, 'pos': pos, 'text': txt})
    return blocks


def fetch_pdf_text(pdf_url: str):
    """회의록 PDF 내려받기 + pdftotext. 반환 (텍스트, 실패 사유) — 성공이면 사유 ''.
    검증(verify_blocks_against_pdf)과 폴백(pdf_fallback_blocks)이 같은 PDF 를 두 번 받지 않도록 분리."""
    if not pdf_url:
        return '', 'pdf_url 없음'
    try:
        data = requests.get(pdf_url, headers=HEADERS, timeout=120).content
    except Exception as e:
        return '', 'PDF 다운로드 실패: %s' % str(e)[:60]
    if data[:4] != b'%PDF':
        return '', 'PDF 아님(%d바이트, %r)' % (len(data), data[:8])
    txt = _pdf_to_text(data)
    if not txt:
        return '', 'pdftotext 추출 실패(0자)'
    return txt, ''


def pdf_fallback_blocks(pdf_url: str, pdf_text: str = None) -> list:
    """폴백: 회의록 PDF를 pdftotext 로 추출해 '◯발언자' 단위로 분리.
    국회 PDF는 일부 폰트 글리프가 깨질 수 있음(실측) — 최후 수단.
    pdf_text 를 주면(검증 단계에서 이미 받은 텍스트) 다시 내려받지 않는다."""
    if pdf_text is None:
        if not pdf_url:
            return []
        data = requests.get(pdf_url, headers=HEADERS, timeout=120).content
        if data[:4] != b'%PDF':
            return []
        pdf_text = _pdf_to_text(data)
    txt = pdf_text
    if not txt:
        return []
    blocks = []
    for part in re.split(r'\n(?=◯)', txt):
        if not part.startswith('◯'):
            continue
        label, _, rest = part[1:].partition('\n')
        name, pos, lead = _split_pdf_label(label.strip())
        rest = (lead + '\n' + rest) if lead else rest
        rest = re.sub(r'\n{2,}', '\n', rest).strip()
        if name and rest:
            blocks.append({'name': name, 'pos': pos, 'text': rest})
    return blocks


# PDF의 '◯' 줄은 "직위 이름 첫문장…" 또는 "이름 위원 첫문장…"이 한 줄에 붙어 온다(실측 2026-09-03:
# "◯위원장 최민희 의석을 정돈하여 주시기 바랍니다.", "◯과학기술정보통신부장관 이종호 예, 그렇게 하겠…",
# "◯문미옥 위원 저는 8페이지에…"). 줄 전체를 이름으로 저장하면 normalize_speaker 가 '미상'을 돌려주고
# 첫 문장이 발언 본문에서 빠진다(뷰어 불일치 교정분 18회의에서 실측). 여기서 이름·직위·첫 문장을 가른다.
_PDF_TITLE_END = ('소위원장', '부위원장', '위원장대리', '위원장', '간사', '진술인', '증인', '참고인', '공술인',
                  '장관', '차관', '청장', '처장', '원장', '사장', '대표', '이사장', '본부장', '단장', '실장',
                  '국장', '과장', '부단장', '부사장', '부원장', '부의장', '대변인', '직무대리', '권한대행',
                  '부문장', '부장', '팀장', '정책관', '조정관', '기획관', '심의관', '담당관')
_PDF_ROLE_AFTER = ('위원', '의원', '간사', '진술인', '증인', '참고인', '공술인')
_PDF_NAME_RE = re.compile(r'[가-힣一-龥]{2,5}')


def _split_pdf_label(label: str):
    """'◯' 줄 → (이름, 직위, 첫 문장). 못 가르면 (줄 전체, '', '') — 종전 동작."""
    toks = label.split()
    if len(toks) >= 2:
        t0, t1 = toks[0], toks[1]
        lead2 = ' '.join(toks[2:]).strip()
        if t0.endswith(_PDF_TITLE_END) and _PDF_NAME_RE.fullmatch(t1):
            return t1, t0, lead2                       # "위원장 최민희 …", "과기정통부장관 이종호 …"
        if _PDF_NAME_RE.fullmatch(t0) and t1 in _PDF_ROLE_AFTER:
            return t0, t1, lead2                       # "문미옥 위원 …"
        if _PDF_NAME_RE.fullmatch(t0):
            return t0, '', ' '.join(toks[1:]).strip()  # "홍길동 …"
    return label, '', ''


# ── 뷰어 본문 교차 검증 (2026-09-03 실측: id → 본문 불일치) ──────────────
# 뷰어(xml.do?id=CONFER_NUM)가 **다른 회의의 본문**을 돌려주는 사례가 있다 — 제목·HTML 머리는 맞는데
# 발언 블록이 엉뚱한 상임위다(2017/41948 미방위 법안소위 → 2025 국방위 1,059블록, 2017/42378 과방위
# → 기재위·국세청, 2018/43150 → 기재위 예산소위). 같은 CONFER_NUM 의 Open API PDF_LINK_URL 은
# 올바른 회의록이었다(실측). 그래서 뷰어 블록은 (1) 발언자 직함으로 타 상임위 냄새를 싸게 걸러내고
# (2) PDF 원문과 표본 대조해 통과한 것만 쓴다. 불일치면 PDF 폴백 블록으로 갈아탄다.
# 자기 위원회 표지는 **소관 기관명만** 쓴다 — '위원장'·'전문위원' 같은 일반 직위는 어느 위원회에나
# 있어 넣으면 판정이 절대 안 걸린다(실측: 국방위 본문 41948·국세청 본문 42378이 통과됨, 2026-09-03).
OWN_COMMITTEE_POS_MARKS = [
    '미래창조과학부', '과학기술정보통신부', '방송통신위원회', '방송미디어통신위원회',
    '원자력안전위원회', '우주항공청', '한국방송공사', '한국교육방송공사',
]
FOREIGN_AGENCY_POS_MARKS = [
    '국방부', '국세청', '관세청', '조달청', '기획재정부', '법무부', '보건복지부', '국토교통부',
    '고용노동부', '행정안전부', '교육부', '외교부', '통일부', '환경부', '농림축산식품부',
    '해양수산부', '산업통상자원부', '금융위원회', '공정거래위원회',
]
VERIFY_MIN_PDF_CHARS = 2000      # PDF 텍스트가 이보다 짧으면(글리프 깨짐·빈 PDF) 판정 불가
VERIFY_PROBE_CHARS = 30          # 블록 앞부분(공백 제거) 표본 길이
VERIFY_PROBE_MIN_CHARS = 10      # 이보다 짧은 블록은 표본으로 쓰지 않음
VERIFY_OK_RATIO = 0.6            # 표본 적중률이 이 이상이면 일치


def looks_foreign_committee(blocks: list):
    """발언자 직함(pos)만으로 타 상임위 회의록인지 싼 값에 가늠한다.
    과방위 소관 부처·위원회 직함이 하나도 없고 타 부처 직함이 있으면 그 부처명, 아니면 None.
    (뷰어 블록의 pos 전용 — PDF 폴백 블록은 pos 가 비어 있어 항상 None.)"""
    poss = [(b.get('pos') or '') for b in (blocks or [])]
    if any(any(k in p for k in OWN_COMMITTEE_POS_MARKS) for p in poss):
        return None
    for p in poss:
        for a in FOREIGN_AGENCY_POS_MARKS:
            if a in p:
                return a
    return None


def _squash(s: str) -> str:
    return re.sub(r'\s+', '', s or '')


def verify_blocks_against_pdf(blocks: list, pdf_url: str, sample: int = 6, pdf=None):
    """뷰어 블록이 같은 회의의 PDF 원문과 같은 내용인지 표본 대조.
    반환 (ok, detail): ok=True 일치 / False 불일치 / None 판정 불가(PDF 없음·다운로드 실패·너무 짧음).
    방법: 가장 긴 블록 sample 개의 앞 VERIFY_PROBE_CHARS 자(공백 제거)를 PDF 텍스트(공백 제거)에서 찾아
    적중률 VERIFY_OK_RATIO 이상이면 일치. pdf=(텍스트, 오류) 를 주면(fetch_pdf_text 결과) 재다운로드 없음."""
    if not blocks:
        return None, '블록 없음'
    if pdf is None:
        pdf = fetch_pdf_text(pdf_url)
    txt, err = pdf
    if err:
        return None, err
    hay = _squash(txt)
    if len(hay) < VERIFY_MIN_PDF_CHARS:
        return None, 'PDF 텍스트 %d자 < %d' % (len(hay), VERIFY_MIN_PDF_CHARS)
    longest = sorted(blocks, key=lambda b: len(b.get('text') or ''), reverse=True)[:sample]
    probes = []
    for b in longest:
        p = _squash(b.get('text') or '')[:VERIFY_PROBE_CHARS]
        if len(p) >= VERIFY_PROBE_MIN_CHARS:
            probes.append(p)
    if not probes:
        return None, '표본으로 쓸 만큼 긴 블록 없음'
    hits = sum(1 for p in probes if p in hay)
    ok = hits / len(probes) >= VERIFY_OK_RATIO
    return ok, '표본 %d/%d 적중, PDF %d자' % (hits, len(probes), len(hay))


# ═══════════════════════════════════════════════════════════
#  관련 발언 선별 (1차 키워드 → 2차 Haiku)
# ═══════════════════════════════════════════════════════════

def is_always_keep(text: str) -> bool:
    """자사(SK텔레콤) 언급 발언인지 — 주제와 무관하게 무조건 수록한다."""
    return any(t in text for t in ALWAYS_KEEP_TERMS)


def skt_mentioned(blocks: list, indices) -> bool:
    """수록 블록(indices) 중 자사 언급이 하나라도 있는가 — 회의 요약 줄의 표시 근거(규칙)."""
    return any(is_always_keep(blocks[i]['text']) for i in indices
               if 0 <= i < len(blocks))


def with_skt_suffix(summary: str, flag: bool) -> str:
    """요약 줄 끝에 ' (SK텔레콤 언급)'을 한 번만 붙인다. 요약이 비었으면 그대로."""
    s = (summary or '').strip()
    if not s or not flag or SKT_CHIP in s:
        return s
    return s + SKT_SUFFIX


def format_overview(items) -> str:
    """회의 개요 블록 문자열. items = [{'topic','text'}, …] 또는 이미 만들어진 문자열.
    검증(is_valid_summary)을 통과한 문단만 남기고, 하나도 없으면 '' (블록 생략).
    형식: '개요:\\n[주제] 문단\\n[주제] 문단' — 문단은 한 줄, 빈 줄로 블록이 끝난다(대시보드 파서 계약)."""
    if not items:
        return ''
    if isinstance(items, str):
        lines = [ln.strip() for ln in items.replace('\r', '').split('\n') if ln.strip()]
        if lines and lines[0].startswith(OVERVIEW_MARK):
            lines = lines[1:]
        paras = lines
    else:
        paras = []
        for it in items:
            if not isinstance(it, dict):
                continue
            topic = re.sub(r'\s+', ' ', str(it.get('topic') or '')).strip(' []')
            text = re.sub(r'\s+', ' ', str(it.get('text') or '')).strip()
            if not text:
                continue
            paras.append(('[%s] ' % topic if topic else '') + text)
    good = [p for p in paras if is_valid_summary(re.sub(r'^\[[^\]]*\]\s*', '', p), 20)]
    return (OVERVIEW_MARK + '\n' + '\n'.join(good)) if good else ''


# ── 주제어 오탐 방지 (2026-08-14) ───────────────────────────────
# 한국어에는 단어 경계가 없어 단순 `in` 매칭이 **다른 낱말 속의 키워드**를 잡는다.
# 실측(축적된 회의록 섹션 본문 230만자)에서 확인된 것만 막는다 — 지침의 '혼신→이혼신고'
# 교훈대로 정규식을 넓히면 정상 발언을 잃는다. 아래 괄호 안이 실측 횟수다.
#   무선 앞 '실'  : 실무선(5) — "실무선에서 결정된 사항". '업'(업무선)은 실측 0이나 운영자 지시로 함께 차단.
#   전파 뒤 하/되/력: 전파하는·전파하고(18), 전파되는·전파되고(5), 전파력(3) — '퍼뜨리다' 뜻.
#                    전파사용(22)·전파차단(20)은 정상이라 건드리지 않는다.
#   단말 뒤 '마'  : 단말마(1).
# 실측 0이라 넣지 않은 것: 요금소·전파상(운영자 예시였으나 말뭉치에 한 번도 없음).
KW_PREV_BLOCK = {'무선': ('실', '업')}
KW_NEXT_BLOCK = {'전파': ('하', '되', '력'), '단말': ('마',)}


def kw_hit(text: str, kw: str) -> bool:
    """키워드가 '낱말로서' 나오는가. 오탐 문맥은 **앞뒤 한 글자만** 본다.

    영문 키워드(AI·5G·6G·ITU…)는 영문 낱말 속에 통째로 들어가는 것이 더 큰 문제다 —
    KAIST·KAIT 안의 'AI' 199회, 6GB·5GB·6GW 안의 '6G/5G' 17회(실측). 다만 'AIDC'
    (AI 데이터센터)처럼 뒤에 영문이 붙는 정상 조어가 있어 'AI'는 **앞 글자만** 보고,
    숫자로 시작하는 '5G/6G'는 앞 숫자와 뒤 영숫자를 함께 본다."""
    prev_bad = KW_PREV_BLOCK.get(kw)
    next_bad = KW_NEXT_BLOCK.get(kw)
    is_ascii = kw.isascii()
    pos = 0
    while True:
        i = text.find(kw, pos)
        if i < 0:
            return False
        pos = i + 1
        p = text[i - 1] if i else ''
        q = text[i + len(kw)] if i + len(kw) < len(text) else ''
        if prev_bad and p in prev_bad:
            continue
        if next_bad and q in next_bad:
            continue
        if is_ascii:
            if p.isalnum() and p.isascii():        # KAIST·KAIT 속의 AI
                continue
            if kw[0].isdigit() and q.isalnum() and q.isascii():   # 6GB·5GB·6GW
                continue
        return True


def matched_keywords(text: str, keywords: list) -> list:
    """텍스트에 실제로 등장한 키워드 목록(입력 순서 유지)."""
    return [k for k in keywords if kw_hit(text, k)]


# 절차성 발언 — 개의 선언·증인 선서·인사말·간부 소개·산회. 정책 내용이 없는데도
# 스쳐 지나가는 낱말('인공지능', '정보통신')로 키워드에 걸리고, **회의 맨 앞에 몰려 있어**
# 인덱스 순 상한을 그대로 먹어치운다. 2019-10-02 국감 섹션이 개회사·선서·장관 인사말로
# 시작해 정작 질의가 밀린 것이 이 때문이다(2026-08-14 운영자 지적).
PROCEDURAL_RE = re.compile(
    r'의석을\s*정[돈리]|성원이\s*되었으므로|개의를?\s*선포|산회를?\s*선포|회의를\s*마치겠|'
    r'감사를\s*실시할\s*것을\s*선언|국정감사를\s*실시할\s*것을\s*선언|'
    r'선서, 본인은|증인\s*선서|선서문|위증의\s*벌을\s*받기로|'
    r'인사말씀|간부를?\s*소개|자리에\s*앉아\s*주시기|양해해\s*주신다면|'
    # 장관·기관장 모두발언(인사말)은 "존경하는 …위원장님, 그리고 위원님 여러분!" 으로 시작한다.
    # 정책 낱말이 잔뜩 들어 있어 키워드에 반드시 걸리지만 질의·응답이 아니다.
    r'존경하는[^\n]{0,20}위원장님|바쁘신\s*(가운데|와중|일정)|깊은\s*감사의\s*말씀|'
    r'성실하게\s*(감사를\s*받|임할\s*것)|보고를?\s*드리겠습니다\s*$|'
    r'유인물로\s*대체|의사일정\s*제\d|출석요구의\s*건|정회를?\s*선포'
)
MIN_SUBSTANTIVE_LEN = 60          # 이보다 짧으면 "예.", "알겠습니다" 류 맞장구

# ── 답변 후보 전용 잡음 필터 (2026-08-14) ───────────────────────
# **답변에는 길이 문턱을 쓰지 않는다.** MIN_SUBSTANTIVE_LEN 을 답변에도 적용했더니
# "예, 그렇습니다"·"검토하겠습니다"·"행안부와 협의해 낮추겠습니다" 같은 **그날의 실질 성과**가
# 통째로 절차성으로 분류돼 버려졌다 — ▶ 2,609건 중 ↳ 가 붙은 것이 31%뿐이었고, 같은 의원의
# ▶ 가 연속으로 나오는 경우가 580건(22%)이나 됐다(사이 답변이 빠진 흔적).
# 실측(뷰어 4개 국감 회의, 의원 직후 비의원 블록 3,865건): 60자 이상은 16~26%뿐인데
# PROCEDURAL_RE 에 걸리는 것은 11건(0.3%)에 불과하다 — 길이 문턱만 빼면 된다.
# 대신 알맹이가 없는 맞장구("예.", "예?")와 사회 진행 멘트만 여기서 걷어낸다.
ANSWER_NOISE_RE = re.compile(
    r'^(?:예|네|응|어|음)?\s*[.?!,…·\s]*$|'            # "예.", "예?", "……"
    r'^(?:다음\s*질의|질의(?:해|하십시오)|수고하셨)'    # 위원장 진행 멘트
)


def is_answer_noise(text: str) -> bool:
    """답변으로 실을 가치가 없는 blank 발언인가. **짧다는 이유만으로는 걸리지 않는다.**"""
    t = (text or '').strip()
    return (not t) or bool(ANSWER_NOISE_RE.match(t))


def is_procedural(block: dict, min_len: int = MIN_SUBSTANTIVE_LEN) -> bool:
    """절차·의례 발언인가. 발언자 직위가 아니라 **문면**으로만 판정한다 —
    위원장도 실질 질의를 하고, 장관도 답변을 한다.
    min_len=0 으로 부르면 길이 문턱을 끄고 절차성 정규식만 본다(답변 후보용)."""
    text = (block.get('text') or '').strip()
    if len(text) < min_len:
        return True
    return bool(PROCEDURAL_RE.search(text[:400]))


def relevance_score(text: str, keywords: list) -> int:
    """발췌 우선순위. 상한이 있을 때 **인덱스 순으로 앞에서 자르면 개회사만 남는다** —
    관련도가 높은 발언부터 남기고, 표시할 때만 다시 시간순으로 되돌린다."""
    if is_always_keep(text):
        return 10_000                       # 자사 언급은 무조건 최우선
    uniq = set(matched_keywords(text, keywords))
    if not uniq:
        return 0
    return len(uniq) * 100 + min(len(text) // 200, 5)


def cap_indices(indices: list, blocks: list, cap: int, keywords: list = None) -> list:
    """수록 상한을 **관련도 순**으로 적용하고, 표시 순서는 다시 시간순으로 되돌린다.
    앞에서 자르면(indices[:cap]) 회의 앞부분의 의례성 발언만 남고 정작 질의가 밀린다
    (2026-08-14 운영자 지적: "상세를 눌러도 질의·응답이 안 보인다")."""
    if len(indices) <= cap:
        return list(indices)
    kw = keywords or []
    ranked = sorted(indices, key=lambda i: (-relevance_score(blocks[i]['text'], kw), i))
    return sorted(ranked[:cap])


def select_relevant(blocks: list, keywords: list, judge, meeting_title: str,
                    max_judge: int = MAX_JUDGE_BLOCKS):
    """키워드 매칭 블록을 Haiku 로 확정.
    단 자사 언급 블록은 판정을 건너뛰고 무조건 확정한다(운영자 지시 2026-08-13) —
    판정 상한(max_judge)에도 걸리지 않게 별도로 모은다.
    반환: (include, confirmed)
      include   — 섹션 발췌용(확정 블록 + 전후 1블록) 인덱스 정렬 목록
      confirmed — 판정 통과 '본' 발언 블록 인덱스(전후 문맥 제외).
                  발언자별 적재(assembly_speeches)는 confirmed 만 사용해 중복 Haiku 콜을 피한다."""
    always, matched = candidate_blocks(blocks, keywords, max_judge)
    confirmed = list(always)
    for i in matched:
        b = blocks[i]
        if judge is None:
            confirmed.append(i)
            continue
        ok, reason = judge('%s %s(%s) 발언' % (meeting_title, b['name'], b['pos']),
                           b['text'])
        if ok:
            confirmed.append(i)
    confirmed.sort()
    return with_context(confirmed, blocks), confirmed


def candidate_blocks(blocks: list, keywords: list, max_cand: int = MAX_JUDGE_BLOCKS):
    """판정 후보 추출(select_relevant에서 분리, 2026-09-03 — 오프라인 파이프라인이 같은 후보를 쓴다).
    반환: (always, matched)
      always  — 자사 언급 블록(절차성 제외). 판정 없이 확정.
      matched — 키워드 매칭 블록(절차성·always 제외)을 **관련도 순**으로 세워 max_cand까지."""
    always = [i for i, b in enumerate(blocks)
              if is_always_keep(b['text']) and not is_procedural(b)]
    always_set = set(always)
    # 절차성 발언(개의·선서·인사말)을 먼저 걷어내고, 남은 후보를 **관련도 순**으로 세운다.
    # 판정·수록 상한이 있는데 인덱스 순으로 주면 회의 앞부분(의례)만 남는다.
    matched = [i for i, b in enumerate(blocks)
               if i not in always_set and not is_procedural(b)
               and any(kw_hit(b['text'], k) for k in keywords)]
    matched.sort(key=lambda i: (-relevance_score(blocks[i]['text'], keywords), i))
    return always, matched[:max_cand]


def with_context(confirmed: list, blocks: list) -> list:
    """확정 블록 + 전후 1블록(문맥) 인덱스 정렬 목록(섹션 발췌용)."""
    include = set()
    for i in confirmed:
        include.add(i)                       # 확정 블록은 이미 검증됨
        # 전후 1블록(문맥)에도 절차성 필터를 건다 — 안 걸었더니 확정 블록이 회의 앞머리에
        # 붙은 경우 **기관장 인사말이 문맥으로 딸려 왔다**(실측 발췌 4,185개 중 7건).
        for j in (i - 1, i + 1):
            if 0 <= j < len(blocks) and not is_procedural(blocks[j]):
                include.add(j)
    return sorted(include)


# ═══════════════════════════════════════════════════════════
#  섹션 구성·등재
# ═══════════════════════════════════════════════════════════

def _clean_text(text: str) -> str:
    """섹션 파서('## YYMMDD ') 오인 방지 이스케이프 + 공백 정리 (press_ingest._clean_body 준용)."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'(?m)^## (\d{6}) ', r'ㆍ## \1 ', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _audit_section_title(meeting: dict) -> str:
    """'국정감사 (첫 피감기관 외 N개 기관)' — 회의일+'국정감사'가 dedupe 키.
    기관 목록이 길어도 접두는 '국정감사'로 고정돼 재실행 dedupe 가 흔들리지 않는다."""
    orgs = [o.strip() for o in re.split(r'[·,]', meeting.get('audit_nm') or '') if o.strip()]
    if not orgs:
        return '국정감사'
    label = orgs[0][:30]
    if len(orgs) > 1:
        label += ' 외 %d개 기관' % (len(orgs) - 1)
    return '국정감사 (%s)' % label


def _section_title(meeting: dict) -> str:
    """'제N차 (주요안건 축약 40자)' — 회의일+회차가 dedupe 키."""
    if meeting.get('is_audit'):
        return _audit_section_title(meeting)
    agenda = meeting['agenda']
    first = ''
    for a in agenda:
        m = re.match(r'\d+\.\s*(.+)', a)
        if m:
            first = m.group(1)
            break
    if not first and agenda:
        first = re.sub(r'^[o○◦\s]+', '', agenda[0])
    first = first.strip()[:40]
    if len(agenda) > 1:
        first += ' 외 %d건' % (len(agenda) - 1)
    return '제%s차 (%s)' % (meeting['dgr'] or '?', first or '안건 미상')


# ── LLM 응답 검증 (2026-08-14) ─────────────────────────────────
# 모델이 요약 대신 **영문 메타응답**을 돌려주는 일이 있다. 예전에는 그대로 저장돼
# 화면에 영문 거절문이 노출됐다(실측 1건 — 2024-12-27 최민희 발언 요지가
# "I appreciate you sharing this task, but I notice the provided text is incomplete…").
# 무엇을 뱉든 저장하지 말고, 아래를 통과한 응답만 채택한다.
REFUSAL_RE = re.compile(
    r"I appreciate|I notice|I'm sorry|I am sorry|I cannot|I can't|I apologize|"
    r"Unfortunately|provided text|As an AI|I'd be happy|I would need",
    re.I)
MIN_HANGUL_RATIO = 0.4      # 정상 요약은 실측 전량 0.5 이상, 거절문은 0.0 — 여유를 둔 경계

# 한국어 메타응답 — 요약이 아니라 **모델이 사용자에게 말을 거는** 응답이다. 영어 거절문만
# 막고 있어 "제공하신 회의록에서 SK텔레콤을 직접 언급하는 부분이 없습니다…"가 그대로 저장돼
# 화면에 노출됐다(운영자 지적 2026-09-01). 요약할 내용이 없으면 규칙 폴백이 정답이다.
META_KO_RE = re.compile(
    r'제공(하신|해\s*주신)|주신\s*(회의록|자료|내용)|요약을?\s*(드리|하기|작성하기)\s*(어렵|힘들|곤란)|'
    r'요약할?\s*(내용|수)\s*(이|가)?\s*없|찾을\s*수\s*없습니다|포함되어\s*있지\s*않(아|습니다)|'
    r'죄송(하지만|합니다)|말씀해\s*주시')


def clip_sentence(txt: str, limit: int) -> str:
    """상한을 넘으면 **문장 경계**에서 자른다 — 하드 슬라이스는 "…요약을 "처럼 말이 끊긴다.
    경계를 못 찾으면 그때만 말줄임표를 붙인다(잘렸음을 화면에서 알 수 있게)."""
    t = (txt or '').strip()
    if len(t) <= limit:
        return t
    head = t[:limit]
    for m in re.finditer(r'[.?!](?:\s|$)|(?:다|요|까)\.', head):
        end = m.end()
    try:
        return head[:end].strip()
    except NameError:
        return head.rstrip() + '…'


def is_valid_summary(txt: str, min_len: int = 8) -> bool:
    """요약으로 채택해도 되는 응답인가 — 거절·메타응답이 아니고 한글이 실질적으로 있을 것."""
    t = (txt or '').strip()
    if len(t) < min_len or REFUSAL_RE.search(t) or META_KO_RE.search(t):
        return False
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return False
    ko = sum(1 for c in letters if '가' <= c <= '힣')
    return ko / len(letters) >= MIN_HANGUL_RATIO


# ── 규칙 기반 회의 요약 (2026-08-14) ────────────────────────────
# 국감 백필을 '유료 AI 없이' 돌린 탓에 국정감사 섹션에는 '요약:' 줄이 통째로 없었다
# (실측 국감 97건 전부 없음 / 상임위는 111건 있음) — 화면 목록에서 국감만 요약 배지가
# 비어 보인다. AI 없이도 **셀 수 있는 사실만**으로 정직한 한 줄은 만들 수 있다.
# 없는 내용을 지어내지 않는 것이 이 함수의 유일한 규칙이다.

def rule_summary_line(head: str, topics: list, n_q: int, n_member: int) -> str:
    """'…국정감사 (기관) — 주요 쟁점: A, B, C (질의 23건 · 의원 11명)' 형태 한 줄."""
    s = ' — '.join([p for p in (head, ('주요 쟁점: ' + ', '.join(topics)) if topics else '') if p])
    tail = []
    if n_q:
        tail.append('질의 %d건' % n_q)
    if n_member:
        tail.append('의원 %d명' % n_member)
    if tail:
        s += (' ' if s else '') + '(%s)' % ' · '.join(tail)
    return s.strip()


def rule_topics(texts: list, keywords: list, top: int = 3) -> list:
    """발췌 묶음에서 가장 자주 등장한 주제어 top개 (kw_hit 로 오탐 제외)."""
    cnt = {}
    for t in texts:
        for k in keywords:
            if kw_hit(t, k):
                cnt[k] = cnt.get(k, 0) + 1
    return [k for k, _ in sorted(cnt.items(),
                                 key=lambda x: (-x[1], keywords.index(x[0])))[:top]]


def rule_summary(meeting: dict, blocks: list, picked: list, keywords: list) -> str:
    """유료 AI 없이 만드는 회의 요약 폴백. 발췌에서 센 숫자와 주제어만 담는다."""
    if not picked:
        return ''
    texts = [blocks[i]['text'] for i in picked]
    members = {normalize_speaker(blocks[i]['name']) for i in picked
               if _is_member(blocks[i].get('pos'))}
    n_q = sum(1 for i in picked if _is_member(blocks[i].get('pos')))
    head = ''
    if meeting.get('is_audit'):
        head = '%s년도 %s' % ((meeting.get('conf_date') or '')[:4],
                             _audit_section_title(meeting))
    return rule_summary_line(head, rule_topics(texts, keywords), n_q, len(members))


def summarize_meeting(meeting_title: str, picked_texts: list, fallback: str = '') -> str:
    """관련 발언 1~2문장 요약(Haiku) — 목록 화면의 부제로 쓰인다 (운영자 지시 2026-08-02).
    실패·키 없음·발언 없음·응답 부적합이면 규칙 폴백(fallback)."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key or not picked_texts:
        return fallback
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        joined = '\n'.join(picked_texts)[:6000]
        # 2026-09-03 프롬프트 교체: 종전 "통신사(SK텔레콤) 관점에서"는 언급이 없는 회의에서
        # "SK텔레콤이 직접 언급되지 않았습니다" 류 **무내용 요약**을 만들었다(7/6·7/30·8/19 실측).
        # 관점 지시를 빼고 회의 전체 쟁점을 쓰게 한다. 자사 언급 표시는 규칙(with_skt_suffix)이 맡는다.
        resp = client.messages.create(
            model=MINUTES_MODEL,
            max_tokens=200,
            thinking=MINUTES_THINKING,
            messages=[{'role': 'user', 'content': (
                '아래는 국회 과방위 회의 「%s」에서 발췌한 통신·전파·AI 관련 발언들이다. '
                '이 회의에서 통신·전파·AI 관련해 무엇이 논의됐는지 1~2문장(130자 이내)으로 요약하라. '
                '특정 기업의 관점을 취하지 말고 논의된 주제·쟁점·정부 답변 요지를 사실대로 쓴다. '
                '머리기호·따옴표 없이 문장만 출력.\n\n%s' % (meeting_title, joined)
            )}],
        )
        txt = ''
        for blk in resp.content:
            if getattr(blk, 'type', '') == 'text':
                txt = (blk.text or '').strip()
                break
        # 모델이 "# 요약 ..." 머리글을 붙여오는 경우가 있어 접두를 걷어낸다 (실측 #54)
        txt = re.sub(r'^[#\-•*"\s]*(요약\s*[::]?\s*)?', '', txt).replace('\n', ' ').strip()
        if not is_valid_summary(txt, 10):
            if txt:
                print('  [요약 부적합 — 규칙 폴백] %s' % txt[:60])
            return fallback
        return clip_sentence(txt, 250)
    except Exception as e:
        print('  [요약 실패 — 규칙 폴백] %s' % str(e)[:60])
        return fallback


def summarize_overview(meeting_title: str, picked_texts: list, topics: list = None) -> str:
    """대시보드 상세용 **회의 개요**(주제별 문단 2~5개, 300~600자) — 2026-09-03 신설(운영자 결정:
    텔레그램·목록은 한 줄 요약, 대시보드는 읽기 좋은 긴 문단을 따로). 실패·부적합이면 ''(블록 생략).
    형식 계약은 format_overview()와 같다: '[주제] 문단' 한 줄씩."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key or not picked_texts:
        return ''
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        joined = '\n'.join(picked_texts)[:9000]
        hint = ('주제명은 가급적 다음 키워드에서 고른다: %s.\n' % ', '.join(topics[:8])) if topics else ''
        resp = client.messages.create(
            model=MINUTES_MODEL,
            max_tokens=1200,
            thinking=MINUTES_THINKING,
            messages=[{'role': 'user', 'content': (
                '아래는 국회 과방위 회의 「%s」에서 발췌한 통신·전파·AI 관련 발언들이다. '
                '이 회의의 개요를 주제별 문단 2~5개, 합계 300~600자로 작성하라.\n'
                '규칙:\n'
                '- 각 문단은 한 줄로, "[주제] 문단내용" 형식(예: "[주파수·5G] 이정헌 위원은 … 답했다.").\n'
                '- 누가 무엇을 지적·질의했고 정부(장관·차관·실장 등)가 무엇이라 답했는지 사실만 쓴다.\n'
                '- 발언자의 성향·정파성·의도를 단정하는 평가어(친기업/반기업/강경/옹호/편향 등)를 쓰지 않는다.\n'
                '- 특정 기업의 관점을 취하지 않는다. 다만 SK텔레콤이 언급된 발언이 있으면 그 문단에 '
                '"(SK텔레콤 언급)"을 붙인다.\n'
                '- 머리기호·번호·따옴표·제목 없이 문단 줄만 출력한다.\n'
                '%s\n%s' % (meeting_title, hint, joined)
            )}],
        )
        txt = ''
        for blk in resp.content:            # 적응형 추론 대비 — text 블록만
            if getattr(blk, 'type', '') == 'text':
                txt = (blk.text or '').strip()
                break
        txt = re.sub(r'^[#\-•*"\s]*(개요\s*[::]?\s*)?', '', txt)
        overview = format_overview(txt)
        if not overview:
            print('  [개요 부적합 — 생략] %s' % txt[:60])
        return overview
    except Exception as e:
        print('  [개요 실패 — 생략] %s' % str(e)[:60])
        return ''


# ═══════════════════════════════════════════════════════════
#  발언자별 입장 추적 (assembly_speeches)
# ═══════════════════════════════════════════════════════════

# 발언자명 정규화 시 걷어낼 직위·존칭 토큰 (긴 것 우선 매칭)
_TITLE_TOKENS = sorted([
    '부위원장', '위원장', '소위원장', '위원장님', '간사', '위원', '의원',
    '부총리', '장관', '차관', '청장', '국장', '실장', '과장', '본부장',
    '단장', '원장', 'ㆍ원장', '이사장', '대표이사', '사장', '대표',
    '참고인', '증인', '진술인', '공술인', '님',
], key=len, reverse=True)


def normalize_speaker(name: str) -> str:
    """발언자명에서 직위·존칭·괄호부가정보를 제거해 매칭 가능한 이름만 남긴다.
    예) '최민희 위원장'→'최민희', '위원장 최민희'→'최민희',
        '홍길동(더불어민주당)'→'홍길동'.
    정부측처럼 개인명이 없고 직위만 있는 경우(예 '과학기술정보통신부장관')는
    정규화 결과가 비거나 너무 짧으면 원본을 그대로 둔다."""
    raw = (name or '').strip()
    n = re.sub(r'\s+', ' ', raw)
    n = re.sub(r'\s*[\(（][^)）]*[\)）]', '', n).strip()   # 괄호 정당/부가정보 제거
    # 앞쪽 직위 제거: "위원장 최민희", "장관 유상임"
    for _ in range(2):
        for t in _TITLE_TOKENS:
            if n.startswith(t + ' '):
                n = n[len(t) + 1:].strip()
                break
    # 뒤쪽 직위·존칭 제거: 공백 있는 형태 + 이름에 바로 붙은 형태 모두
    for _ in range(2):
        changed = False
        for t in _TITLE_TOKENS:
            if n.endswith(' ' + t):
                n = n[:-(len(t) + 1)].strip()
                changed = True
                break
            if n.endswith(t) and len(n) > len(t):
                cand = n[:-len(t)].strip()
                if 2 <= len(cand) <= 4:      # 한국인 성명 길이일 때만 붙은 직위로 간주
                    n = cand
                    changed = True
                    break
        if not changed:
            break
    if 2 <= len(n) <= 5:
        return n
    # 여기 오면 정규화 실패다. PDF 폴백 경로에서 '◯발언자' 분리가 어긋나면 **발언 본문 전체가
    # 이름 칸에 들어온다** — 실측 80행, 대시보드 발언자 드롭다운이 문장으로 뒤덮였다.
    # 앞쪽에서 '이름+직위' 형태를 한 번 더 건져 보고, 그마저 실패하면 '미상'으로 둔다.
    m2 = re.match(r'[◯○\s]*([가-힣]{2,4})\s*(?:위원장|부위원장|소위원장|위원|의원|간사|'
                  r'장관|차관|청장|처장|원장|소장|본부장|단장|실장|국장|이사장|사장|대표)', raw)
    if m2:
        return m2.group(1)
    # **잘라서 만든 4자는 이름이 아니다.** 예전 폴백은 raw[:4] 를 그대로 돌려줘
    # '위원장노'('위원장 노웅래 다음은…' 의 앞토막)·'한국항공'·'원자력안'·'한국식품'·
    # '국가과학' 같은 기관·직위의 앞토막을 발언자명으로 저장했다(실측 12행).
    # 잘라내지 **않은** 온전한 한글만 이름으로 인정하고, 아니면 '미상'으로 둔다.
    # 상한을 6자로 두는 이유: 음역된 외국인 증인명('해럴드로저스' 6자, 실측 6행)이
    # 4자 상한에서는 통째로 '미상'이 돼 버린다.
    # (한자 이름 '金成泰' 등은 위 `2 <= len(n) <= 5` 에서 이미 원문 그대로 반환된다.)
    head = re.sub(r'[◯○\s]+', '', raw)
    return head if 2 <= len(head) <= 6 and re.fullmatch(r'[가-힣]+', head) else '미상'


def extract_gist(text: str, keywords: list, limit: int = 150) -> str:
    """AI 없이 만드는 요지 — **키워드가 들어 있는 첫 완결 문장**을 뽑는다.

    앞에서 120자를 그냥 자르면 "비용 PPT 한번 볼까요? (영상자료를 보며) 이 기지국 하나 하는" 처럼
    도입부만 남고 문장이 중간에 끊긴다(운영자 지적). 발언의 핵심은 키워드가 나오는 문장에 있으므로
    그 문장을 통째로 쓰는 편이 훨씬 읽힌다. 유료 API 없이 쓸 수 있는 최선의 폴백이다."""
    t = re.sub(r'\s+', ' ', text or '').strip()
    if not t:
        return ''
    # 한국어 종결(…다./…요./…까?/…죠.)과 마침표 기준으로 자른다.
    sents = [s.strip() for s in re.split(r'(?<=[.?!])\s+', t) if s.strip()]
    # 무대지시 괄호는 문장 종결부호가 없어 다음 문장에 붙어 온다 —
    # "(영상자료를 보며) 이 기지국 하나 하는 데도…" 처럼 요지 앞머리를 잡아먹으므로 걷어낸다.
    sents = [re.sub(r'^(?:\([^)]*\)\s*)+', '', s).strip() for s in sents]
    sents = [s for s in sents if s]
    for s in sents:
        if len(s) >= 15 and any(kw_hit(s, k) for k in keywords):
            return _ellipsis(s, limit)
    for s in sents:
        if len(s) >= 20:
            return _ellipsis(s, limit)
    # 최종 폴백도 **괄호를 걷어낸** 문장들로 만든다. 원문 t 를 그대로 돌려주면
    # 두 루프를 다 빠져나온 짧은 발언에서 무대지시가 살아남는다 —
    # extract_gist('(영상자료를 보며) 화면에 요금제 보이시지요? 다음 장 봅시다.', ['요금'])
    # 이 괄호째 저장된 사고(실측 2건: audit-44874, audit-55552).
    return _ellipsis(' '.join(sents) or t, limit)


def summarize_speech(meeting_title: str, agenda: str, name: str,
                     pos: str, text: str, keywords: list = None) -> str:
    """발언 1건의 '내용'을 1~2문장으로 요약(Haiku 1콜). 정치적 입장 단정 금지.
    실패·키 없음이면 원문 앞부분을 축약해 폴백(요지 완전 누락 방지)."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    fallback = extract_gist(text, keywords or [], 150)
    if not api_key:
        return fallback
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            '아래는 국회 과방위 회의에서 나온 한 발언이다. 이 발언의 "내용"만 '
            '1~2문장(120자 이내)으로 요약하라.\n'
            '규칙:\n'
            '- 발언에서 실제로 말한 내용·요구·질의만 기술한다.\n'
            '- 발언자의 성향·정파성·의도를 단정하는 평가어(친기업/반기업/강경/'
            '옹호/편향 등)를 절대 쓰지 말라.\n'
            '- "촉구/질의/지적/요청/제안/우려 표명/반대/찬성 입장 표명" 같은 '
            '발언 행위를 기술하는 것은 허용한다.\n'
            '- 머리기호·따옴표·발언자명 없이 요지 문장만 출력한다.\n\n'
            '회의: %s\n안건: %s\n발언자: %s(%s)\n발언 원문: %s'
            % (meeting_title, agenda or '(미상)', name, pos or '', text[:2000])
        )
        resp = client.messages.create(
            model=MINUTES_MODEL,
            max_tokens=160,
            thinking=MINUTES_THINKING,
            messages=[{'role': 'user', 'content': prompt}],
        )
        txt = ''
        for blk in resp.content:            # 적응형 추론 대비 — text 블록만
            if getattr(blk, 'type', '') == 'text':
                txt = (blk.text or '').strip()
                break
        txt = re.sub(r'^[#\-•*"\s]*(요약|요지\s*[::]?\s*)?', '', txt)
        txt = txt.replace('\n', ' ').strip()
        # 영문 거절문("I appreciate … the provided text is incomplete")이 그대로 저장돼
        # 화면에 노출된 사고가 있었다(2026-08-14). 검증을 통과한 응답만 채택한다.
        if not is_valid_summary(txt):
            if txt:
                print('  [요지 부적합 — 규칙 폴백] %s' % txt[:60])
            return fallback
        return clip_sentence(txt, 250)
    except Exception as e:
        print('  [발언 요지 실패 — 폴백] %s' % str(e)[:50])
        return fallback


def speeches_exist(sb, confer_num: str) -> bool:
    """해당 회의의 발언 행이 이미 적재됐는지(재실행 dedupe·section과 독립)."""
    try:
        rows = sb.table('assembly_speeches').select('id') \
            .eq('confer_num', str(confer_num)).limit(1).execute().data
        return bool(rows)
    except Exception as e:
        print('  [speeches_exist 조회 실패(무시)] %s' % str(e)[:50])
        return False


def _ellipsis(s: str, limit: int) -> str:
    """상한에서 자를 때 말줄임표를 붙인다. 없으면 문장이 단어 중간에서 끊긴 채로 화면에 나가
    "요약이 잘못 생성됐다"로 오해받는다(2026-08-14 검증에서 2,109건 확인)."""
    s = (s or '').strip()
    return s if len(s) <= limit else s[:limit].rstrip() + '…'


def _primary_agenda(meeting: dict) -> str:
    """회의의 대표 안건 1건(번호 접두 제거)."""
    for a in meeting['agenda']:
        mm = re.match(r'\d+\.\s*(.+)', a)
        if mm:
            return _ellipsis(mm.group(1), 120)
    if meeting['agenda']:
        return _ellipsis(re.sub(r'^[o○◦\s]+', '', meeting['agenda'][0]), 120)
    return ''


# 발언 이력용 잡음 배제 (2026-09-01, 운영자 지적) — "잠깐만 기다려 주십시오, ○○○ 위원님"
# 같은 사회·호명 발언이 인물 프로필에 "무슨 내용인지 알 수 없는" 행으로 남았다. 원문(raw)을
# 저장하지 않아 사후 재요약이 불가능하므로(#99) 적재 시점에 거른다. 길이만으로는 못 거른다 —
# 20~55자에도 실질 발언이 많다(실측). 진행 문구 + 짧음의 교집합만 뺀다.
# (기존 is_procedural/PROCEDURAL_RE는 개회·선서 등 '의례' 판정용이라 목적이 다르다 — 별도 함수)
CHAIR_NOISE_RE = re.compile(
    r'(잠깐만|잠시만|기다려\s*주|수고하셨|나와\s*계세요|나오세요|말씀하십시오|'
    r'다음은\s*\S+\s*위원님|이상입니다)')


def is_noise_speech(text: str) -> bool:
    """발언 이력에 남길 가치가 없는 사회·호명 발언인가."""
    t = re.sub(r'\s+', ' ', text or '').strip()
    if not t:
        return True
    if len(t) < 18:
        return True
    return bool(CHAIR_NOISE_RE.search(t)) and len(t) < 60


def build_speech_rows(meeting: dict, blocks: list, confirmed: list,
                      keywords: list, source_url: str, dry: bool = False,
                      max_excerpts: int = MAX_EXCERPTS, presummarized: dict = None) -> list:
    """confirmed 발언 블록을 발언자별 assembly_speeches 행으로 구성.
    요지는 dry-run 이 아닐 때만 AI 로 생성(비용 방어).
    presummarized={블록idx: 요지} 를 주면(오프라인 파이프라인 — 세션이 작성) API를 부르지 않고
    그 요지를 쓰되, is_valid_summary 를 통과한 것만 적재한다(부적합은 **미적재**, #113)."""
    # 키가 없으면 요지가 규칙 폴백(원문 앞 문장 절단)으로 저장된다 — 그게 2026-09-01
    # 전량 재수집(#113)을 부른 원인이다. **원문을 저장하지 않는 테이블이라 사후 수리가
    # 불가능**하므로, 폴백을 쌓느니 이번 회차 발언 적재를 건너뛴다(섹션은 정상 적재되고,
    # 키가 돌아온 뒤 실행에서 speeches_exist가 비어 있어 소급 적재된다).
    if not dry and presummarized is None \
            and not os.environ.get('ANTHROPIC_API_KEY', '').strip():
        print('  [발언 적재 건너뜀] ANTHROPIC_API_KEY 없음 — 폴백 요지를 저장하지 않는다(#113)')
        return []
    agenda = _primary_agenda(meeting)
    mdate = (meeting['conf_date'] or '').strip() or None
    rows = []
    seen = set()                    # (speaker, chunk_seq) 중복 방어
    for i in cap_indices(confirmed, blocks, max_excerpts, keywords):
        b = blocks[i]
        speaker = normalize_speaker(b['name'])
        key = (speaker, i)
        if key in seen:
            continue
        seen.add(key)
        if is_noise_speech(b['text']):    # 사회·호명 등 내용 없는 발언은 적재하지 않는다
            continue
        # 자사 언급 칩은 키워드 유무와 무관하게 **항상** 붙인다(2026-09-03 — 종전엔 키워드가
        # 없을 때만 붙어 4/28 '이훈기 위원: SKT 영업정지…' 같은 발언이 칩 없이 저장됐다).
        kws = matched_keywords(b['text'], keywords)[:5]
        if is_always_keep(b['text']) and SKT_CHIP not in kws:
            kws.append(SKT_CHIP)
        topic = ', '.join(kws)
        if presummarized is not None:
            s = (presummarized.get(i) or presummarized.get(str(i)) or '').strip()
            if not is_valid_summary(s):
                print('  [요지 부적합 — 미적재] idx=%d %s' % (i, s[:40]))
                continue
            summary = clip_sentence(s, 250)
        else:
            summary = '' if dry else summarize_speech(
                meeting['title'], agenda, speaker, b['pos'], b['text'], keywords)
        rows.append({
            'speaker':      speaker,
            'speaker_raw':  b['name'],
            'position':     b['pos'] or None,
            'party':        None,
            'meeting_date': mdate,
            'confer_num':   str(meeting['confer_num']),
            'chunk_seq':    i,
            'agenda':       agenda or None,
            'topic':        topic or None,
            'summary':      summary or None,
            'source_url':   source_url,
        })
    return rows


def upsert_speeches(sb, rows: list) -> int:
    """assembly_speeches 적재(유니크 (confer_num,speaker,chunk_seq)로 재실행 안전)."""
    if not rows:
        return 0
    try:
        sb.table('assembly_speeches').upsert(
            rows, on_conflict='confer_num,speaker,chunk_seq').execute()
        return len(rows)
    except Exception as e:
        print('  [발언 적재 실패] %s' % str(e)[:120])
        return 0


# 국회의원 직위(data-pos). 그 외(장관·차관·원장·증인·전문위원 등)는 전부 답변자 쪽으로 본다.
_MEMBER_POS = {'위원', '의원', '위원장', '부위원장', '소위원장', '간사'}


def _is_member(pos: str) -> bool:
    return (pos or '').strip() in _MEMBER_POS


def _qa_lines(blocks: list, picked: list) -> list:
    """발췌를 '질의 → 답변' 쌍으로 묶어 낸다.

    이전에는 채택된 블록만 평평하게 나열해서, 발언자 필터·상한에 걸려 **정부측 답변이 빠지는**
    일이 잦았다(운영자 지적: "상세를 눌러도 질의·응답이 안 보인다"). 이제 의원 질의를 찾으면
    바로 뒤따르는 답변 블록을 **채택 여부와 무관하게** 원문에서 끌어와 붙인다 —
    "무선국 면허세는 행안부와 협의하겠다" 같은 그날의 실질 성과가 답변 쪽에 있기 때문이다."""
    out, used = [], set()
    for i in picked:
        if i in used:
            continue
        b = blocks[i]
        used.add(i)
        who = '%s(%s)' % (b['name'], b['pos']) if b['pos'] else b['name']
        txt = _trunc(b['text'])
        if _is_member(b['pos']):
            out.append('▶ %s' % who)
            out.append('   %s' % txt)
            # 뒤따르는 답변 최대 2블록 (중간에 다른 의원이 끼면 중단)
            for j in range(i + 1, min(i + 4, len(blocks))):
                nb = blocks[j]
                if _is_member(nb['pos']):
                    break
                # 답변에는 길이 문턱을 적용하지 않는다(min_len=0) — 짧은 확답이
                # 그날의 실질 성과인 경우가 많다. 절차성 정규식·맞장구만 걷어낸다.
                if j in used or is_procedural(nb, min_len=0) or is_answer_noise(nb['text']):
                    continue
                nwho = '%s(%s)' % (nb['name'], nb['pos']) if nb['pos'] else nb['name']
                out.append('   ↳ %s: %s' % (nwho, _trunc(nb['text'])))
                used.add(j)
        else:
            out.append('▪ %s: %s' % (who, txt))
        out.append('')
    return out


def _trunc(text: str) -> str:
    t = (text or '').replace('\n', ' ').strip()
    return t if len(t) <= BLOCK_TRUNC else t[:BLOCK_TRUNC] + '…'


def build_section_body(meeting: dict, detail: dict, blocks: list, picked: list,
                       summary: str = '', max_excerpts: int = MAX_EXCERPTS,
                       keywords: list = None, overview: str = '') -> str:
    """섹션 본문. overview(format_overview 결과)가 있으면 안건 다음·질의응답 앞에 '개요:' 블록을
    넣는다(빈 값이면 종전 포맷과 바이트 동일). '요약:' 줄은 대시보드가 섹션 앞 900자 안에서
    파싱하므로 개요 블록은 반드시 그 **뒤**에 둔다."""
    lines = ['**%s**' % meeting['title']]
    if summary:
        lines.append('요약: %s' % summary)
    when = detail.get('CONF_DT') or meeting['conf_date']
    bg = (detail.get('BG_PTM') or '').strip()
    ed = (detail.get('ED_PTM') or '').strip()
    if bg or ed:
        when += ' %s~%s' % (bg, ed)
    plc = (detail.get('CONF_PLC') or '').strip()
    lines.append('- 일시: %s%s' % (when, (' | 장소: ' + plc) if plc else ''))
    if meeting['agenda']:
        lines.append('- 안건:')
        for a in meeting['agenda'][:MAX_AGENDA_LINES]:
            lines.append('  %s' % a)
        rest = len(meeting['agenda']) - MAX_AGENDA_LINES
        if rest > 0:
            lines.append('  외 %d건' % rest)
    lines.append('')
    if overview:
        lines.append(overview.strip())
        lines.append('')
    if picked:
        lines.append('질의·응답:')
        lines.append('')
        lines.extend(_qa_lines(blocks, cap_indices(picked, blocks, max_excerpts, keywords)))
    else:
        lines.append(SHELL_BODY_MARK + ' — 회의 개요만 기록)')
    return _clean_text('\n'.join(lines))


# ── 빈 껍데기 섹션 자동 복구 (2026-08-14) ───────────────────────
# 첫 실행에서 판정이 전부 탈락하면 '(키워드 관련 발언 없음…)' 껍데기 섹션이 등재된다.
# 그런데 section_exists() 는 **헤더만** 보고 dup 판정하므로, 이후 실행은 이 회의를 통째로
# 건너뛰어 껍데기가 **영구히 갱신되지 않는다**(실측: 241021 국정감사 audit-51996 —
# 같은 회의 assembly_speeches 에는 발언이 12행 있는데 섹션 본문은 껍데기 한 줄뿐).
# 껍데기는 dup 으로 보지 않고 지운 뒤 다시 만든다.
SHELL_BODY_MARK = '(키워드 관련 발언 없음'


def _fetch_all(q, page: int = 1000) -> list:
    """PostgREST 기본 max-rows(1000) 절단 방어 — 범위를 넘겨 가며 전량 수집."""
    out, off = [], 0
    while True:
        rows = q.range(off, off + page - 1).execute().data or []
        out.extend(rows)
        if len(rows) < page:
            return out
        off += page


def section_range(sb, doc_name: str, ymd6: str, title: str):
    """'## YYMMDD title…' 섹션이 차지한 (시작, 끝) chunk_index. 없으면 None.

    register_kb_section 이 섹션을 통째로 넣으므로 한 섹션의 청크는 연속하고, 다음 섹션의
    헤더는 반드시 청크 맨 앞('## ')에 온다 — 그 직전까지가 이 섹션의 범위다."""
    pat = '%%## %s %s%%' % (ymd6, _like_escape(title[:25]))
    rows = sb.table('document_chunks').select('chunk_index,content').eq('doc_name', doc_name) \
        .like('content', pat).order('chunk_index').limit(1).execute().data or []
    if not rows:
        return None
    start = rows[0]['chunk_index']
    # ⚠️ 전제 검증(2026-09-03 실측): 2024·2025 문서는 섹션 250개 중 105개의 헤더가 **청크 중간**에
    # 있다(어느 시점의 재청킹 흔적). 그 상태에서 위 전제로 범위를 잡으면 이웃 섹션 2~3개가 함께
    # 지워진다(2026-08-14 사고 유형). 시작 청크가 헤더(또는 프리앰블+헤더)로 시작하고 범위 안에
    # 헤더가 하나뿐일 때만 범위를 돌려주고, 아니면 None(호출자는 교체를 건너뛴다).
    head = rows[0]['content'] or ''
    hdr_re = re.compile(r'(?m)^## \d{6} ')
    first_hdr = hdr_re.search(head)
    if not first_hdr or (first_hdr.start() > 0 and not head.lstrip().startswith('# ')):
        print('  [섹션 범위 보류] %s %s — 헤더가 청크 중간(idx %d)이라 범위를 잡지 않는다'
              % (ymd6, title[:20], start))
        return None
    if len(hdr_re.findall(head)) > 1:
        print('  [섹션 범위 보류] %s %s — 한 청크에 헤더 %d개(idx %d)'
              % (ymd6, title[:20], len(hdr_re.findall(head)), start))
        return None
    nxt = sb.table('document_chunks').select('chunk_index').eq('doc_name', doc_name) \
        .gt('chunk_index', start).like('content', '## %') \
        .order('chunk_index').limit(1).execute().data or []
    end = (nxt[0]['chunk_index'] - 1) if nxt else _doc_max_index(sb, doc_name)
    mid = sb.table('document_chunks').select('content').eq('doc_name', doc_name) \
        .gt('chunk_index', start).lte('chunk_index', end).execute().data or []
    if any(hdr_re.search(r['content'] or '') for r in mid):
        print('  [섹션 범위 보류] %s %s — 범위 %d~%d 안에 다른 섹션 헤더가 청크 중간에 있다'
              % (ymd6, title[:20], start, end))
        return None
    return start, end


def shell_section_range(sb, doc_name: str, ymd6: str, title: str):
    """껍데기 섹션이면 그 (시작, 끝) chunk_index, 아니면 None."""
    rng = section_range(sb, doc_name, ymd6, title)
    if not rng:
        return None
    start, end = rng
    rows = sb.table('document_chunks').select('content').eq('doc_name', doc_name) \
        .gte('chunk_index', start).lte('chunk_index', end).execute().data or []
    return rng if SHELL_BODY_MARK in ''.join(r['content'] for r in rows) else None


def drop_section(sb, doc_name: str, start: int, end: int) -> int:
    """섹션 청크 [start, end] 삭제. **삭제 범위를 chunk_index 로 정확히 한정**한다 —
    2026-08-14 사고(중복 정리 중 이웃 섹션 꼬리까지 지워 3개 섹션 4만여 자 유실)의 재발 방지."""
    if start is None or end is None or end < start:
        return 0
    sb.table('document_chunks').delete().eq('doc_name', doc_name) \
        .gte('chunk_index', start).lte('chunk_index', end).execute()
    return end - start + 1


def renumber_doc(sb, doc_name: str) -> int:
    """문서의 chunk_index 를 순서 그대로 0..n-1 로 다시 매긴다(결번 제거).
    섹션을 지우고 다시 넣으면 결번이 남는데, 결번은 감사 쿼리에서 '청크 유실'과
    구분되지 않는다. id 기준 갱신이라 기존 embedding 은 보존된다.
    (document_chunks 에는 (doc_name, chunk_index) 유니크 제약이 없어 중간 충돌 걱정이 없다.)"""
    rows = _fetch_all(sb.table('document_chunks').select('id,chunk_index')
                      .eq('doc_name', doc_name).order('chunk_index'))
    fixed = 0
    for new_idx, r in enumerate(rows):
        if r['chunk_index'] != new_idx:
            sb.table('document_chunks').update({'chunk_index': new_idx}) \
                .eq('id', r['id']).execute()
            fixed += 1
    return fixed


# ═══════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════

def _digest_skip_reason(m: dict, sp_rows: list, notify: bool, body: str):
    """다이제스트를 적재하지 않는 이유(없으면 None). 조용한 실패 금지 — 사유를 항상 찍는다."""
    if not notify:
        return '--no-notify'
    if SHELL_BODY_MARK in (body or ''):
        return '껍데기 섹션(관련 발언 없음)'
    if len(sp_rows) < DIGEST_MIN_SPEECHES:
        return '발언 요지 %d건 < %d (절차성 회의)' % (len(sp_rows), DIGEST_MIN_SPEECHES)
    if not _is_recent(m.get('conf_date'), DIGEST_MAX_AGE_DAYS):
        return '회의일 %s — %d일 초과(백필)' % (m.get('conf_date'), DIGEST_MAX_AGE_DAYS)
    return None


def _build_digest(m: dict, title: str, summary: str, sp_rows: list, url: str,
                  skt_flag: bool) -> str:
    from subscriber_notify import format_minutes_digest
    return format_minutes_digest(m.get('conf_date') or '', title, summary, sp_rows, url,
                                 skt_flag=skt_flag)


def _print_digest_preview(m, title, summary, sp_rows, url, skt_flag, notify, body):
    """dry-run 전용 — 큐에 넣지 않고 다이제스트를 화면에 보여준다."""
    why = _digest_skip_reason(m, sp_rows, notify, body)
    if why:
        print('  [다이제스트 생략: %s]' % why)
        return
    try:
        html = _build_digest(m, title, summary or '(요약 생략 — dry-run)', sp_rows, url, skt_flag)
    except Exception as e:
        print('  [다이제스트 미리보기 실패] %s' % str(e)[:80])
        return
    print('  ----- 다이제스트 미리보기 (%d자) -----' % len(html))
    print('\n'.join('  | ' + ln for ln in html.split('\n')))
    print('  ----------------------------------')


def _enqueue_digest(sb, m, title, summary, sp_rows, url, skt_flag, notify, body):
    why = _digest_skip_reason(m, sp_rows, notify, body)
    if why:
        print('  [다이제스트 생략: %s]' % why)
        return False
    try:
        from subscriber_notify import queue_for_subscribers
        html = _build_digest(m, title, summary, sp_rows, url, skt_flag)
        if not html:
            print('  [다이제스트 생략: 내용 없음]')
            return False
        ok = queue_for_subscribers(sb, 'assembly', html)
        print('  [다이제스트 %s] %s %s (%d자)'
              % ('적재' if ok else '적재 실패(무시)', m.get('conf_date'), title, len(html)))
        return ok
    except Exception as e:
        print('  [다이제스트 적재 실패(무시)] %s' % str(e)[:80])
        return False


def _heartbeat(sb, note: str):
    try:
        sb.table('system_health').upsert(
            {'key': 'last_minutes_run',
             'updated_at': datetime.now(timezone.utc).isoformat(),
             'note': note},
            on_conflict='key').execute()
    except Exception as e:
        print('[heartbeat 오류] %s' % e)


def _is_recent(conf_date: str, days: int) -> bool:
    """회의일이 오늘(KST)로부터 days일 이내인가. 파싱 실패는 False(큐 적재 쪽은 fail-closed)."""
    try:
        d = datetime.strptime((conf_date or '').replace('-', '')[:8], '%Y%m%d').date()
    except ValueError:
        return False
    return (datetime.now(KST).date() - d).days <= days


def run(sb, api_key: str, year: int, limit: int = 0, dry: bool = False,
        audit: bool = True, audit_only: bool = False, notify: bool = True) -> dict:
    keywords = load_press_keywords(sb)
    # 회의록 판정만 Sonnet 5 — make_ai_judge는 보도자료 판정과 공용이라 기본값(Haiku)은 그대로 둔다.
    judge = make_ai_judge(sb, keywords, model=MINUTES_MODEL, thinking=MINUTES_THINKING)
    mode = '키워드+AI판정(%s)' % MINUTES_MODEL if judge else '키워드만(AI 불가 폴백)'
    print('[과방위 회의록] %d년, 모드=%s, 키워드 %d개 (자사 언급은 판정 없이 무조건 수록)'
          % (year, mode, len(keywords)))

    meetings = []
    if not audit_only:
        meetings = fetch_meetings(api_key, year)
        for m in meetings:                       # 두 경로가 같은 dict 모양을 쓰도록 보강
            m.setdefault('viewer_id', m['confer_num'])
            m.setdefault('is_audit', False)
        print('  상임위 회의 %d건 (안건 단위 그룹핑 완료)' % len(meetings))
    if audit or audit_only:
        if year < AUDIT_MIN_YEAR:
            print('  [국감 스킵] %d년은 22대(%d년~) 이전 — 국감 경로는 22대만 수집'
                  % (year, AUDIT_MIN_YEAR))
        else:
            audits = fetch_audit_meetings(year)
            print('  국정감사 회의 %d건' % len(audits))
            meetings = meetings + audits

    doc_name = '과방위_회의록_%d.md' % year
    doc_header = ('# 과방위 회의록 %d년\n\n'
                  '> 출처: 국회 과학기술정보방송통신위원회 회의록 자동 수집 '
                  '(열린국회정보 Open API + 국회회의록시스템)\n\n---\n\n' % year)

    stats = {'new': 0, 'dup': 0, 'fail': 0, 'sp': 0, 'proc': 0}
    renum_docs = set()               # 껍데기 섹션을 갈아끼운 문서 — 끝나고 결번 정리
    for m in meetings:
        # limit 은 '실제로 무언가 적재한(섹션 신규 or 발언 신규) 회의' 수를 센다.
        # 발언 소급 적재 시 섹션은 이미 있어 stats['new'] 가 0이라도 한도가 걸리도록.
        if limit and stats['proc'] >= limit:
            break
        if not m['conf_date'] or (not m['dgr'] and not m.get('is_audit')):
            continue
        is_audit = bool(m.get('is_audit'))
        viewer_id = m.get('viewer_id') or m['confer_num']
        max_judge = AUDIT_MAX_JUDGE_BLOCKS if is_audit else MAX_JUDGE_BLOCKS
        max_exc = AUDIT_MAX_EXCERPTS if is_audit else MAX_EXCERPTS
        ymd6 = m['conf_date'].replace('-', '')[2:]
        # dedupe: 섹션(회의록 청크)과 발언(assembly_speeches)을 독립 확인.
        # 섹션은 회의일+회차 접두로 선확인(안건 축약이 바뀌어도 중복 등재 방지).
        # 둘 다 이미 있으면 스킵. 한쪽만 있으면 없는 쪽만 채운다(발언 소급 적재 가능).
        # 국감은 **하루에 두 건이 열리는 날이 있다**(예: 2024-10-10 원안위 계열 / SW정책연구소 계열).
        # 접두를 '국정감사'로만 잡으면 그날 두 번째 회의가 중복으로 걸러져 섹션이 통째로 누락된다
        # (실측: 2016·2017·2021·2024에서 4건 누락). 피감기관까지 포함한 제목을 키로 쓴다.
        sec_prefix = _section_title(m) if is_audit else '제%s차 ' % m['dgr']
        sec_exists = section_exists(sb, doc_name, ymd6, sec_prefix)
        # 껍데기 섹션은 dup 으로 보지 않는다 — 그래야 이번 실행에서 지우고 다시 만든다.
        shell = shell_section_range(sb, doc_name, ymd6, sec_prefix) if sec_exists else None
        if shell:
            sec_exists = False
        sp_exists = (not dry) and speeches_exist(sb, m['confer_num'])
        if sec_exists and (dry or sp_exists):
            stats['dup'] += 1
            continue
        # 뷰어가 '빈 결과'가 아니라 '예외'로 실패해도 PDF 폴백까지 가야 한다.
        # (2026-08-03: 2024-10-25 국정감사 회의록이 뷰어에서 400을 뱉는데, 예외가 폴백 앞에서
        #  가로채는 바람에 PDF가 멀쩡한데도 영구 실패로 남았다.)
        blocks, src, viewer_err = [], '뷰어', None
        try:
            blocks = fetch_speech_blocks(viewer_id)
        except Exception as e:
            viewer_err = str(e)[:80]
        if not blocks:
            try:
                blocks = pdf_fallback_blocks(m['pdf_url'])
                src = 'PDF폴백'
            except Exception as e:
                print('  [원문 실패] %s: 뷰어=%s / PDF=%s'
                      % (m['title'][:50], viewer_err or '빈결과', str(e)[:60]))
                stats['fail'] += 1
                continue
            if blocks and viewer_err:
                print('  [뷰어 실패→PDF 폴백] %s (%s)' % (m['title'][:44], viewer_err[:40]))
        if not blocks:
            print('  [원문 없음·스킵] %s' % m['title'][:60])
            stats['fail'] += 1
            continue
        # 뷰어 본문 교차 검증(2026-09-03) — 뷰어가 다른 회의의 본문을 돌려준 실측(41948·42378·43150).
        # 상임위 회의만: Open API 의 PDF_LINK_URL 이 뷰어와 독립된 사본이라 대조 근거가 된다.
        # 국감은 검증하지 않는다 — 국감 PDF 는 뷰어 id(MNTS_ID)로 만든 URL(AUDIT_PDF_URL)이라
        # 뷰어와 같은 id 체계를 공유해 독립 사본이 아니다(경로 무변경, 운영자 결정 전까지).
        if src == '뷰어' and not is_audit and m.get('pdf_url'):
            foreign = looks_foreign_committee(blocks)
            pdf = fetch_pdf_text(m['pdf_url'])
            ok, detail = verify_blocks_against_pdf(blocks, m['pdf_url'], pdf=pdf)
            if foreign or ok is False:
                why = ('타 상임위 직함 %s' % foreign) if foreign else detail
                try:
                    fixed = pdf_fallback_blocks(m['pdf_url'], pdf_text=pdf[0])
                except Exception as e:
                    fixed = []
                    why += ' / PDF 폴백 예외 %s' % str(e)[:50]
                if not fixed:
                    print('  [뷰어 불일치·PDF 폴백 없음→스킵] %s (%s) — 잘못된 본문은 등재하지 않는다'
                          % (m['title'][:50], why))
                    stats['fail'] += 1
                    continue
                print('  [뷰어 불일치→PDF 폴백] %s (%s) 뷰어 %d블록 → PDF %d블록'
                      % (m['title'][:44], why, len(blocks), len(fixed)))
                blocks, src = fixed, 'PDF(뷰어 불일치)'
            elif ok is None:
                print('  [뷰어 검증 불가·뷰어 사용] %s (%s)' % (m['title'][:44], detail))
        picked, confirmed = select_relevant(blocks, keywords, judge, m['title'],
                                            max_judge=max_judge)
        detail = fetch_detail(api_key, m['conf_id'])
        title = _section_title(m)
        capped = cap_indices(picked, blocks, max_exc, keywords)
        picked_texts = ['%s: %s' % (blocks[i]['name'], blocks[i]['text'][:800])
                        for i in capped]
        # 요약 줄은 화면 목록의 부제라 비면 눈에 띈다. AI 요약이 불가·부적합이면
        # 규칙 요약으로라도 채운다 (국감 백필이 무료 모드라 통째로 비었던 사고, 2026-08-14).
        summary = '' if dry else summarize_meeting(
            m['title'], picked_texts, fallback=rule_summary(m, blocks, capped, keywords))
        # 자사 언급 표시는 규칙 — 수록 발췌(picked) 원문에 SK텔레콤이 있으면 붙인다(2026-09-03).
        skt_flag = skt_mentioned(blocks, picked)
        summary = with_skt_suffix(summary, skt_flag)
        # 대시보드 상세용 회의 개요(주제별 문단) — 텔레그램·목록은 위 한 줄 요약만 쓴다.
        overview = '' if dry else summarize_overview(
            m['title'], picked_texts, rule_topics(picked_texts, keywords, top=8))
        body = build_section_body(m, detail, blocks, picked, summary,
                                  max_excerpts=max_exc, keywords=keywords, overview=overview)
        url = VIEWER_URL % viewer_id
        if dry:
            sp_rows = build_speech_rows(m, blocks, confirmed, keywords, url, dry=True,
                                        max_excerpts=max_exc)
            speakers = sorted({r['speaker'] for r in sp_rows})
            print('  [dry-run] ## %s %s | 원문=%s 블록 %d, 발췌 %d, %d자, SK텔레콤 언급=%s'
                  % (ymd6, title, src, len(blocks), len(picked), len(body), skt_flag))
            print('  발언자별 후보 %d건 / 발언자 %d명: %s'
                  % (len(sp_rows), len(speakers), ', '.join(speakers)[:120]))
            print('  ----- 섹션 미리보기 -----')
            print('\n'.join('  | ' + ln for ln in body.split('\n')[:40]))
            print('  -------------------------')
            _print_digest_preview(m, title, summary, sp_rows, url, skt_flag, notify, body)
            stats['new'] += 1
            continue
        did_work = False
        registered = False
        # ① 기존 회의록 섹션(document_chunks) — 없을 때만 등재 (경로 무변경)
        if sec_exists:
            pass
        elif shell and SHELL_BODY_MARK in body:
            # 다시 만들어도 여전히 껍데기 = 정말로 관련 발언이 없는 회의다.
            # 여기서 지웠다 넣으면 **매 실행마다 같은 내용으로 청크를 갈아엎어**
            # chunk_index 만 흔들린다(재임베딩까지 유발). 그대로 둔다.
            stats['dup'] += 1
        else:
            if shell:
                n_del = drop_section(sb, doc_name, shell[0], shell[1])
                renum_docs.add(doc_name)     # 지운 자리에 결번이 남으므로 끝나고 재번호
                print('  [껍데기 섹션 제거] %s %s (청크 %d개, %d~%d) — 재등재'
                      % (ymd6, title, n_del, shell[0], shell[1]))
            if register_kb_section(sb, doc_name, DOC_CATEGORY, ymd6, title, body, url,
                                   doc_header):
                print('  [등재] %s %s (%s, 발췌 %d)' % (ymd6, title, src, len(picked)))
                stats['new'] += 1
                did_work = True
                registered = True
            else:
                stats['dup'] += 1
        # ② 발언자별 입장(assembly_speeches) — 없을 때만 적재 (추가 경로)
        sp_rows = []
        if not sp_exists:
            sp_rows = build_speech_rows(m, blocks, confirmed, keywords, url, dry=False,
                                        max_excerpts=max_exc)
            n_sp = upsert_speeches(sb, sp_rows)
            if n_sp:
                print('  [발언 적재] %s 발언 %d건' % (ymd6, n_sp))
                stats['sp'] += n_sp
                did_work = True
        # ③ 구독자 다이제스트(텔레그램 '국회·법률 동향', 2026-09-03) — **신규 섹션**이고 최근
        #    60일 이내이며 실질 발언이 3건 이상일 때만 큐에 적재한다. 백필(--year 과거)·재등재·
        #    껍데기 회의는 절대 적재하지 않는다(6명에게 30건이 쏟아지는 #118 유형 사고 방지).
        #    발송은 send-subscriber-briefing이 각자의 수신 시각에 묶어 보낸다(즉시 트리거 없음).
        if registered:
            _enqueue_digest(sb, m, title, summary, sp_rows, url, skt_flag, notify, body)
        if did_work:
            stats['proc'] += 1
        time.sleep(1)

    for dn in sorted(renum_docs):
        n_fix = renumber_doc(sb, dn)
        if n_fix:
            print('  [결번 정리] %s 청크 %d개 재번호' % (dn, n_fix))

    note = 'year=%d new=%d dup=%d fail=%d sp=%d' % (
        year, stats['new'], stats['dup'], stats['fail'], stats['sp'])
    print('[과방위 회의록 완료] ' + note)
    if not dry:
        _heartbeat(sb, note)
    return stats


def main():
    ap = argparse.ArgumentParser(description='국회 과방위 회의록 수집기')
    ap.add_argument('--dry-run', action='store_true', help='DB 쓰기 없이 실측만')
    ap.add_argument('--limit', type=int, default=0, help='신규 처리 회의 수 상한 (0=무제한)')
    ap.add_argument('--year', type=int, default=0, help='대상 연도 (기본: 올해)')
    ap.add_argument('--no-audit', action='store_true', help='국정감사 회의록 수집 제외')
    ap.add_argument('--audit-only', action='store_true',
                    help='국정감사 회의록만 수집 (소급 백필용)')
    ap.add_argument('--no-notify', action='store_true',
                    help='구독자 큐(회의록 다이제스트) 적재 안 함')
    ap.add_argument('--allow-api', action='store_true',
                    help='재작년 이전 연도에도 API(AI) 경로 허용 — 기본 거부(소급은 minutes_offline.py)')
    args = ap.parse_args()

    api_key = os.environ.get('ASSEMBLY_API_KEY', '')
    if not api_key:
        print('[오류] ASSEMBLY_API_KEY 환경변수가 없습니다.')
        return
    year = args.year or datetime.now(KST).year
    # 과거 연도 소급은 세션 파이프라인(minutes_offline.py)이 맡는다 — 운영자 규칙(2026-09-03):
    # 일회성 AI 작업에 API를 쓰지 않는다. 실수로 --year 2019 를 돌려 수백 회의를 과금하지 않게 막는다.
    if year < datetime.now(KST).year - 1 and not args.dry_run and not args.allow_api:
        print('[거부] %d년은 API 경로로 돌리지 않습니다 — minutes_offline.py(세션 파이프라인)를 쓰거나 '
              '--allow-api 를 명시하세요.' % year)
        return
    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    run(sb, api_key, year, limit=args.limit, dry=args.dry_run,
        audit=not args.no_audit, audit_only=args.audit_only, notify=not args.no_notify)


if __name__ == '__main__':
    main()
