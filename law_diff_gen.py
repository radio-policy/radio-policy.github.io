"""
법령 개정 DIFF 생성기 — 시행예정본(pending) vs 현행 등재본의 조문 단위 비교 + AI 영향 분석.

law_pending이 가리키는 (현행 watch_doc_name, 시행예정 doc_name) 쌍의 document_chunks를
조문번호(article_no) 정규화 키로 조인해 3분류(modified/added/deleted)하고,
변경 조문 전/후를 Claude Sonnet에 1콜/법령으로 넘겨 요약·영향·긴급도를 받아
law_diffs에 upsert한다. 시행일이 도래해 promote_due가 승격한 건은
기존 'pending' 분석 행을 diff_kind='promoted'로 전환만 한다(AI 재호출 없음).

국회 입법예고(origin='assembly')도 같은 테이블에 담는다 — assembly_bills 중
의견제출이 진행 중(notice_end_dt >= 오늘)인 의안의 원문 PDF에서 신·구조문대비표를
추출해 분석하고, 가결·폐기·철회된 의안의 행은 같은 패스에서 삭제한다.

사용법:
  python law_diff_gen.py                     # loaded 신규분 + 최근 3일 promoted 처리
  python law_diff_gen.py --dry-run           # 수집·diff까지만(AI·DB·텔레그램 없음), 3분류 수치 출력
  python law_diff_gen.py --law "정보통신망"    # 특정 법령만
  python law_diff_gen.py --backfill          # 기존 law_diffs 행 무시하고 loaded 전건 재생성
  python law_diff_gen.py --days 7            # promoted 소급 기간(기본 3일)
  python law_diff_gen.py --assembly-only     # 국회 입법예고(assembly) 패스만 단독 실행

필요 .env: SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY,
          TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID(알림, 없으면 생략)
"""

import os
import re
import sys
import json
import shutil
import argparse
import tempfile
import subprocess
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta

# Windows 스케줄러/cp949 콘솔에서 이모지 print 크래시 방지 (배경역사 #19)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from sb_client import make_client   # create_client 직접 사용 금지 — HTTP/1.1 강제 (지침)
import notify   # 텔레그램 전송 공용 유틸 (개선⑪) — 전송부만 위임

SB_URL = os.getenv('SUPABASE_URL')
SB_KEY = os.getenv('SUPABASE_SERVICE_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
# 법제처 DRF OC키 — 조문 매칭 정본(신구법대비표) 조회용. law_crawler와 동일 키.
LAW_OC_KEY = os.getenv('LAW_OC_KEY', '')
DRF_SERVICE = 'http://www.law.go.kr/DRF/lawService.do'

MODEL = 'claude-sonnet-5'
ARTICLE_CHARS = 3000        # 조문당 입력 절단
TOTAL_CHARS = 30000         # 프롬프트 본문 총 절단
FULL_REVISION_RATIO = 0.7   # 변경조문/전체조문이 이 비율 초과면 전부개정으로 간주
DASHBOARD_URL = 'https://youjinwoong.github.io/radio-policy-ai/'
KST = timezone(timedelta(hours=9))

# docs/schema.sql:451 norm_article_key의 파이썬 포팅 — "제48조의3(침해사고 대응)" → "48조의3"
ART_KEY_RE = re.compile(r'^제?\s*([0-9]+조(?:의[0-9]+)?)')
# 새 판에서 "제n조 삭제" 형태로 남는 조문은 deleted 취급 (fetch_pending_articles와 동일 취지)
DELETED_RE = re.compile(r'^제\s*[0-9]+조(?:의[0-9]+)?(?:\([^)]*\))?\s*삭제')

# 신구법대비표(oldAndNew) 파싱용 — 조문 헤더('제N조(제목)…')로 그룹 경계를 잡는다.
_OLDNEW_HEAD_RE = re.compile(r'^제\s*[0-9]+조(?:의[0-9]+)?')
_OLDNEW_ARTNO_RE = re.compile(r'(제\s*[0-9]+조(?:의[0-9]+)?\s*(?:\([^)]*\))?)')
_P_TAG_RE = re.compile(r'</?P>')   # 변경부 마킹 <P>…</P> — 태그만 제거, 내용은 보존

ANALYSIS_TOOL = {
    'name': 'report_law_diff',
    'description': '법령 개정 조문 비교 결과에 대한 요약·영향·긴급도 보고',
    'input_schema': {
        'type': 'object',
        'properties': {
            'summary': {'type': 'string',
                        'description': '이번 개정의 핵심 내용 요약(한국어 3~5문장)'},
            'impact': {'type': 'string',
                       'description': '통신사(SK텔레콤) 전파·통신 정책 관점의 영향 분석(한국어)'},
            'urgency': {'type': 'string', 'enum': ['high', 'medium', 'low'],
                        'description': 'high=즉시 대응 필요, medium=모니터링 필요, low=참고'},
            'articles': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'article_no': {'type': 'string',
                                       'description': '입력에 표기된 조번호 그대로(예: 48조의3)'},
                        'impact': {'type': 'string', 'description': '해당 조문 변경의 영향 한두 문장'},
                    },
                    'required': ['article_no', 'impact'],
                },
            },
        },
        'required': ['summary', 'impact', 'urgency', 'articles'],
    },
}


# (c) 입법예고(proposed) 분석용 — after(개정 후 문안)를 개정안 원문에서 인용시킨다
PROPOSED_TOOL = {
    'name': 'report_proposed_diff',
    'description': '입법예고 개정안과 현행 조문의 대비 분석 결과 보고',
    'input_schema': {
        'type': 'object',
        'properties': {
            'summary': {'type': 'string', 'description': '개정안 핵심 3~5문장'},
            'impact': {'type': 'string', 'description': 'SK텔레콤 전파·통신 정책 관점 영향과 의견제출 검토 포인트'},
            'urgency': {'type': 'string', 'enum': ['high', 'medium', 'low']},
            'articles': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'article_no': {'type': 'string', 'description': '조번호 (예: 24조의2)'},
                        'change': {'type': 'string', 'enum': ['modified', 'added', 'deleted']},
                        'after': {'type': 'string', 'description': '개정안 문안 원문 인용(요약 금지, 1500자 내). 삭제면 빈 문자열'},
                        'impact': {'type': 'string', 'description': '해당 조문 변경의 영향 한두 문장'},
                    },
                    'required': ['article_no', 'change', 'after'],
                },
            },
        },
        'required': ['summary', 'impact', 'urgency', 'articles'],
    },
}

_PROPOSED_NAME_RE = re.compile(
    r'([가-힣0-9·\s]+?(?:법률|시행령|시행규칙|규정|규칙|고시|법))\s*일부\s*개정(?:령|법률|규칙)?\s*안')


def _proposed_law_name(title):
    """예고 제목에서 법령명 추출: '(과기정통부 공고 제2026-780호) 전파법 시행규칙 일부개정령안 입법예고'
    → '전파법 시행규칙'. 실패 시 None."""
    t = re.sub(r'[\[(（][^)\]）]{0,60}[\])）]\s*', '', title or '')
    m = _PROPOSED_NAME_RE.search(t)
    return re.sub(r'\s+', ' ', m.group(1)).strip() if m else None


# ── KB 등재 법령 대조 (#87) ────────────────────────────────────────────────
#  국회 입법예고는 전 상임위 법안이 들어온다. 관련성 판정은 크롤러의 AI(assembly_notice_criteria)가
#  하는데 기준이 넓어("플랫폼 규제는 소관위원회 불문 관련", "애매하면 채택") 대부업·스토킹방지·
#  헬스케어·이러닝 같은 법안까지 통과한다. DIFF는 건당 Sonnet 호출(2만 자 입력)이라 가장 비싼
#  단계인데 그 절반 이상이 무관 법안에 쓰이고 있었다(실측 17건 중 11건).
#
#  **판단이 아니라 대조로 거른다** — "이 법안이 우리 KB에 등재된 법을 고치는가".
#  AI 판정보다 정확하고 비용이 0이며, 운영자가 KB에 넣고 빼는 것으로 대상을 직접 통제한다.
#  KB에 없으면 안 본다 — 필요하면 그 법을 KB에 등재하면 다음 실행부터 자동 포함된다
#  (그러면 /law·자문 검색에서도 함께 잡히므로 예외 목록보다 이쪽이 일관된다).
#
#  ⚠️ 정규화 없이 문자열 비교하면 실패한다. 「대·중소기업」의 가운뎃점이 DB는 'ㆍ', 국회는 '·'로
#     오고 띄어쓰기도 흔들린다. 실측: 정규화 전 6건 중 전자상거래법·방미통위설치법이 잘못 제외됐다.
_KB_LAW_KEYS = None


def _norm_law_name(s):
    """법령명 대조 키 — 가운뎃점 3종·공백·마침표를 지운다."""
    return re.sub(r'[ㆍ·・.\s]', '', s or '')


def _kb_law_keys(sb):
    """KB(document_chunks 현행본)에 있는 법령명 키 집합. 실행당 1회 조회 후 캐시.

    시행령·시행규칙만 등재된 경우도 모법 개정안을 받도록 접미사를 떼어 함께 넣는다.
    조회 실패 시 None을 돌려주고, 호출부는 **필터를 걸지 않는다**(fail-open) —
    대조를 못 한다고 분석을 통째로 멈추면 놓치는 쪽이 더 비싸다."""
    global _KB_LAW_KEYS
    if _KB_LAW_KEYS is not None:
        return _KB_LAW_KEYS
    try:
        keys, off = set(), 0
        while True:
            rows = (sb.table('document_chunks').select('doc_name')
                    .eq('status', 'current').range(off, off + 999).execute().data) or []
            for r in rows:
                m = re.match(r'^(.+?)\(', r.get('doc_name') or '')
                if not m:
                    continue
                nm = m.group(1).strip()
                keys.add(_norm_law_name(nm))
                base = re.sub(r'\s*(시행령|시행규칙|시행에 관한.*)$', '', nm).strip()
                if base:
                    keys.add(_norm_law_name(base))
            off += 1000
            if len(rows) < 1000 or off > 40000:
                break
        _KB_LAW_KEYS = keys
        print(f'  [KB 대조] 등재 법령 키 {len(keys)}개 로드')
    except Exception as e:
        print(f'  [KB 대조] 조회 실패 — 필터 미적용으로 진행: {str(e)[:80]}')
        _KB_LAW_KEYS = None
    return _KB_LAW_KEYS


def _bill_target_law(bill_name):
    """의안명에서 대상 법령명 추출: '전파법 일부개정법률안' → '전파법'."""
    nm = re.sub(r'\s*(일부개정법률안|전부개정법률안|폐지법률안|법률안|개정안)\s*$', '', bill_name or '').strip()
    return re.sub(r'\([^)]*\)\s*$', '', nm).strip()


def _proposed_deadline(text):
    """첨부 본문에서 의견제출 마감일(YYYYMMDD) 추출 — best effort."""
    m = re.search(r'의견\s*제출[\s\S]{0,300}?(\d{4})\s*[.년]\s*(\d{1,2})\s*[.월]\s*(\d{1,2})',
                  text or '')
    if m:
        try:
            return '%04d%02d%02d' % (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


# (d) 국회 입법예고(origin='assembly') 분석용 — 신·구조문대비표가 전/후를 모두
#     담고 있어 before도 모델 인용으로 받는다 (프런트 articles 계약: before/after).
ASSEMBLY_TOOL = {
    'name': 'report_assembly_diff',
    'description': '국회 발의 개정안(신·구조문대비표)의 대비 분석 결과 보고',
    'input_schema': {
        'type': 'object',
        'properties': {
            'summary': {'type': 'string', 'description': '개정안 핵심 3~5문장'},
            'impact': {'type': 'string',
                       'description': 'SK텔레콤 전파·통신 정책 관점 영향과 의견제출 검토 포인트'},
            'urgency': {'type': 'string', 'enum': ['high', 'medium', 'low']},
            'articles': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'article_no': {'type': 'string', 'description': '조번호 (예: 24조의2)'},
                        'change': {'type': 'string', 'enum': ['modified', 'added', 'deleted']},
                        'before': {'type': 'string',
                                   'description': '대비표 현행 문안 원문 인용(1500자 내). 신설이면 빈 문자열'},
                        'after': {'type': 'string',
                                  'description': '대비표 개정안 문안 인용(1500자 내). 삭제면 빈 문자열'},
                        'impact': {'type': 'string', 'description': '해당 조문 변경의 영향 한두 문장'},
                    },
                    'required': ['article_no', 'change', 'after'],
                },
            },
        },
        'required': ['summary', 'impact', 'urgency', 'articles'],
    },
}

# 국회 입법예고 시스템(pal) 상세 — lgsltPaId는 열린국회정보 BILL_ID(PRC_…)와 동일 (2026-08-02 실측)
PAL_VIEW_URL = ('https://pal.assembly.go.kr/napal/lgsltpa/lgsltpaOngoing/view.do'
                '?lgsltPaId=%s')
BILL_SUMMARY_API = 'https://open.assembly.go.kr/portal/openapi/BPMBILLSUMMARY'
PAL_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/124.0.0.0 Safari/537.36'),
    'Accept-Language': 'ko-KR,ko;q=0.9',
}
# pal 상세 HTML의 의안 원문 PDF 링크: likms FileGate?bookId={UUID}&type=1 (type=0은 HWP) — 실측
_BOOKID_RE = re.compile(r'FileGate\?bookId=([0-9A-Fa-f\-]{16,})&(?:amp;)?type=1')
# 의안 PDF의 대비표 표제는 '신ㆍ구조문대비표'(가운뎃점 U+318D) — ·/./공백 변형 허용 (실측)
_COMPARE_TABLE_RE = re.compile(r'신\s*[·ㆍ.]?\s*구\s*조문\s*대비표')
_BILL_DONE_KEYWORDS = ('가결', '폐기', '철회')   # proc_result에 포함되면 수명 종료


def _find_pdftotext():
    """press_ingest._find_pdftotext 패턴 복제 (import 시 무거운 모듈 연쇄 로드 회피)."""
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


_PDFTOTEXT = _find_pdftotext()


def _pdf_to_text(data):
    """press_ingest._pdf_to_text 패턴 복제 — pdftotext 임시파일 경유, 실패 시 ''."""
    if not _PDFTOTEXT or not data:
        return ''
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix='.pdf')
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        out = subprocess.run(
            [_PDFTOTEXT, '-enc', 'UTF-8', tmp, '-'],
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


def _fetch_bill_pdf_text(bill_id):
    """pal 상세 → likms FileGate PDF 다운로드 → pdftotext. 실패 시 '' (fail-soft).

    FileGate는 302가 아니라 'The document has been moved' HTML(sender49 등 href)을
    돌려주므로(2026-08-02 실측) bookId가 든 href를 최대 2회 추적한다.
    """
    if not bill_id or not _PDFTOTEXT:
        return ''
    try:
        r = requests.get(PAL_VIEW_URL % bill_id, headers=PAL_HEADERS, timeout=30)
        r.raise_for_status()
        m = _BOOKID_RE.search(r.text)
        if not m:
            return ''
        url = ('https://likms.assembly.go.kr/filegate/servlet/FileGate'
               '?bookId=%s&type=1' % m.group(1))
        for _ in range(2):
            resp = requests.get(url, headers=PAL_HEADERS, timeout=60)
            data = resp.content
            if data[:4] == b'%PDF':
                return _pdf_to_text(data)
            hop = re.search(r'href="([^"]*bookId=[^"]*)"',
                            data.decode('utf-8', errors='replace'))
            if not hop:
                return ''
            url = urljoin(url, hop.group(1).replace('&amp;', '&'))
        return ''
    except Exception as e:
        print(f'  ! 의안 PDF 취득 실패: {str(e)[:80]}')
        return ''


def _extract_compare_table(text):
    """PDF 전문에서 신·구조문대비표 구간(표제부터 끝까지) 추출. 없으면 ''."""
    m = _COMPARE_TABLE_RE.search(text or '')
    return text[m.start():].strip() if m else ''


def _fetch_bill_summary(bill_no):
    """폴백: 열린국회정보 BPMBILLSUMMARY(제안이유·주요내용).
    summarize_assembly_bills.fetch_summary 패턴 복제. 실패·내용없음 시 ''."""
    key = os.getenv('ASSEMBLY_API_KEY', '')
    if not (key and bill_no):
        return ''
    try:
        resp = requests.get(BILL_SUMMARY_API,
                            params={'KEY': key, 'Type': 'json', 'pIndex': 1,
                                    'pSize': 5, 'BILL_NO': bill_no}, timeout=15)
        wrap = resp.json().get('BPMBILLSUMMARY')
        if not isinstance(wrap, list):
            return ''
        for it in wrap:
            if isinstance(it, dict) and 'row' in it:
                rows = it['row']
                return (rows[0].get('SUMMARY') or '').strip() if rows else ''
        return ''
    except Exception as e:
        print(f'  ! 제안이유 API 실패: {str(e)[:80]}')
        return ''


def norm_key(article_no):
    """조번호 정규화 — 제목·괄호를 떼고 'N조' / 'N조의M'만. 부칙·별표는 None."""
    m = ART_KEY_RE.match(article_no or '')
    return m.group(1) if m else None


def send_telegram(msg: str):
    """운영자 봇, HTML — 전송부는 notify 위임 (개선⑪, 실패 로그는 notify가 출력)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    notify.send_telegram(msg, chat_id=TELEGRAM_CHAT_ID, parse_mode='HTML')


def _parse_ts(s):
    """timestamptz 문자열 → datetime. 파싱 실패 시 None."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except Exception:
        return None


# ── 조문 매칭 정본: 법제처 신구법대비표(oldAndNew) ──────────
#
# 운영자 승인 방향(2026-08-02): "조문 매칭(구↔신 짝짓기)만 API 정본을 쓰고, SKT
# 영향 분석·요약은 기존 유지, API가 비면 기존 difflib(청크 키 조인)로 폴백."
# 즉 아래 함수는 diff_articles와 '동형'의 changes 리스트를 돌려주는 드롭인 대체다.
# generate_one의 downstream(build_prompt·analyze_with_sonnet·merge_article_impacts·
# upsert)과 articles jsonb 스키마(article_no·change·before·after·impact)는 무변경.

_law_session = None


def _drf_session():
    """DRF 전용 requests 세션 — trust_env=False로 세션 주입 프록시를 무시한다.
    (Claude 세션 수동실행 시 사내 프록시가 SSL을 깨는 문제 회피; 정부망은 프록시 불요)"""
    global _law_session
    if _law_session is None:
        s = requests.Session()
        s.trust_env = False
        s.headers['User-Agent'] = 'Mozilla/5.0 (radio-policy-ai law_diff)'
        _law_session = s
    return _law_session


def _clean_oldnew(text):
    """대비표 조문줄 정리 — <P>…</P> 변경마킹 태그만 제거(내용 보존) + 공백 정돈."""
    return _P_TAG_RE.sub('', text or '').strip()


def _oldnew_list(node):
    """구/신조문목록 노드 → 조문줄 리스트. 단건이면 dict라 [dict]로 정규화, 없으면 []."""
    if not isinstance(node, dict):
        return []
    arts = node.get('조문')
    if isinstance(arts, dict):
        return [arts]
    return arts if isinstance(arts, list) else []


def _article_no_from_head(head):
    """헤더 줄에서 '제N조(제목)'만 추출. 실패 시 앞 40자."""
    m = _OLDNEW_ARTNO_RE.match(head or '')
    return (m.group(1).strip() if m else (head or '')[:40]).strip()


def _parse_oldnew(gu_list, sin_list):
    """구/신 병렬 조문줄(같은 인덱스=같은 위치)을 '제N조' 헤더로 그룹핑해 조문 단위로
    묶고, diff_articles와 동형의 changes 리스트로 반환.

    반환: [{key, article_no, change, before, after}]
      - modified: 구/신 양쪽에 헤더가 있고 문안이 다름
      - added   : 구쪽 헤더가 '<신 설>'(헤더 아님) → 통째 신설 조문
      - deleted : 신쪽이 헤더 아님(<삭 제>) 또는 '제N조 … 삭제' 표식
    대비표는 '변경된 조문만' 싣기 때문에 그룹 = 변경 조문. 미변경 문단은
    '(생  략)'/'(현행과 같음)'으로 축약돼 그대로 인용에 남는다(AI가 이해)."""
    groups, cur = [], None
    for g, s in zip(gu_list, sin_list):
        gt = _clean_oldnew(g.get('content') if isinstance(g, dict) else g)
        st = _clean_oldnew(s.get('content') if isinstance(s, dict) else s)
        if _OLDNEW_HEAD_RE.match(gt) or _OLDNEW_HEAD_RE.match(st):
            cur = {'gu': [], 'sin': []}
            groups.append(cur)
        if cur is None:      # 헤더 이전 잔여줄은 조문 단위 대상 아님 — 버림
            continue
        cur['gu'].append(gt)
        cur['sin'].append(st)
    changes = []
    for grp in groups:
        gu_head = grp['gu'][0] if grp['gu'] else ''
        sin_head = grp['sin'][0] if grp['sin'] else ''
        gu_is_head = bool(_OLDNEW_HEAD_RE.match(gu_head))
        sin_is_head = bool(_OLDNEW_HEAD_RE.match(sin_head))
        head_for_key = sin_head if sin_is_head else gu_head
        key = norm_key(head_for_key)
        if not key:
            continue
        gu_txt = '\n'.join(x for x in grp['gu'] if x)
        sin_txt = '\n'.join(x for x in grp['sin'] if x)
        article_no = _article_no_from_head(head_for_key)
        if not gu_is_head and sin_is_head:
            change, before, after = 'added', '', sin_txt
        elif gu_is_head and not sin_is_head:
            change, before, after = 'deleted', gu_txt, ''
        elif DELETED_RE.match(re.sub(r'\s+', ' ', sin_txt).strip()):
            change, before, after = 'deleted', gu_txt, sin_txt
        else:
            change, before, after = 'modified', gu_txt, sin_txt
        changes.append({'key': key, 'article_no': article_no,
                        'change': change, 'before': before, 'after': after})
    return changes


def fetch_oldnew_articles(mst, api_target):
    """법제처 신구법대비표(oldAndNew/admrulOldAndNew)를 '조문 매칭 정본'으로 조회.

    유효한 대비표가 있으면 diff_articles 동형의 changes 리스트, 아니면 None(→difflib 폴백).
    폴백(None) 신호:
      · OC키 없음 / mst 없음 / 요청·JSON 실패
      · 신구법존재여부='N'(대비표 없음, 예: 타법개정 다수)
      · 구/신조문목록 부재·불균형
      · 신조문 MST가 요청 mst와 불일치(엉뚱한 개정본 응답 방지 — trap #2)
      · 파싱 결과 0건
    """
    if not (LAW_OC_KEY and mst):
        return None
    is_admrul = (api_target == 'admrul')
    target = 'admrulOldAndNew' if is_admrul else 'oldAndNew'
    param_key = 'ID' if is_admrul else 'MST'
    try:
        r = _drf_session().get(DRF_SERVICE, params={
            'OC': LAW_OC_KEY, 'target': target, 'type': 'JSON', param_key: str(mst),
        }, timeout=20)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        print(f'    (신구법 API 실패 → difflib 폴백) {str(e)[:100]}')
        return None
    root = d.get('OldAndNewService') or d.get('AdmRulOldAndNewService')
    if not isinstance(root, dict) or not root:
        print('    (신구법 응답 형식 이상[대비표 없음] → difflib 폴백)')
        return None
    if str(root.get('신구법존재여부', '')).upper() == 'N':
        print('    (신구법존재여부=N[대비표 없음] → difflib 폴백)')
        return None
    gu_list = _oldnew_list(root.get('구조문목록'))
    sin_list = _oldnew_list(root.get('신조문목록'))
    if not gu_list or not sin_list or len(gu_list) != len(sin_list):
        print(f'    (신구법 조문목록 부재/불균형 구{len(gu_list)}/신{len(sin_list)} '
              f'→ difflib 폴백)')
        return None
    ninfo = root.get('신조문_기본정보') or {}
    oinfo = root.get('구조문_기본정보') or {}
    new_mst = str(ninfo.get('법령일련번호') or ninfo.get('행정규칙일련번호') or '')
    old_mst = str(oinfo.get('법령일련번호') or oinfo.get('행정규칙일련번호') or '')
    if new_mst and new_mst != str(mst):
        print(f'    (신구법 신본 MST {new_mst} ≠ 요청 {mst} → difflib 폴백)')
        return None
    changes = _parse_oldnew(gu_list, sin_list)
    if not changes:
        print('    (신구법 대비표 파싱 0건 → difflib 폴백)')
        return None
    st = count_stats(changes)
    print(f'    ✓ 신구법대비표 정본 매칭 {len(changes)}건 '
          f'(변경{st["modified"]}·신설{st["added"]}·삭제{st["deleted"]}) '
          f'· 대비표 구본 MST={old_mst or "?"} → 신본 {new_mst or mst}')
    return changes


# ── 조문 취득·DIFF ────────────────────────────────────────

def fetch_articles(sb, doc_name):
    """doc의 청크를 chunk_index 순으로 페이징 페치 → {정규화키: {'article_no', 'text'}}.

    PostgREST는 요청당 1,000행에서 잘리므로 반드시 .order().range() 페이징(지침).
    같은 조문이 여러 청크로 쪼개져 있으면 chunk_index 순으로 이어붙인다.
    조번호가 정규화되지 않는 행(부칙·별표·장 제목)은 조문 diff 대상이 아니므로 제외.
    """
    rows, start, page = [], 0, 1000
    while True:
        r = (sb.table('document_chunks')
             .select('chunk_index, content, article_no')
             .eq('doc_name', doc_name)
             .order('chunk_index').range(start, start + page - 1).execute())
        batch = r.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        start += page
    arts = {}
    for row in rows:
        key = norm_key(row.get('article_no'))
        if not key:
            continue
        d = arts.setdefault(key, {'article_no': row['article_no'], 'parts': []})
        if row.get('content'):
            d['parts'].append(row['content'])
    return {k: {'article_no': v['article_no'], 'text': '\n'.join(v['parts'])}
            for k, v in arts.items()}


def diff_articles(base, new):
    """조번호 정규화 키 조인 → 3분류. 반환: [{key, article_no, change, before, after}]"""
    changes = []
    base_keys, new_keys = set(base), set(new)
    for key in sorted(base_keys | new_keys, key=_key_sort):
        b = base.get(key)
        n = new.get(key)
        if b and not n:
            changes.append({'key': key, 'article_no': b['article_no'],
                            'change': 'deleted', 'before': b['text'], 'after': ''})
        elif n and not b:
            # 새 판 본문이 "제n조 삭제"면 신설이 아니라 삭제 조문의 표식
            if DELETED_RE.match(n['text'].strip()):
                changes.append({'key': key, 'article_no': n['article_no'],
                                'change': 'deleted', 'before': '', 'after': n['text']})
            else:
                changes.append({'key': key, 'article_no': n['article_no'],
                                'change': 'added', 'before': '', 'after': n['text']})
        else:
            if DELETED_RE.match(n['text'].strip()) and not DELETED_RE.match(b['text'].strip()):
                changes.append({'key': key, 'article_no': b['article_no'],
                                'change': 'deleted', 'before': b['text'], 'after': n['text']})
            elif re.sub(r'\s+', '', b['text']) != re.sub(r'\s+', '', n['text']):
                changes.append({'key': key, 'article_no': n['article_no'],
                                'change': 'modified', 'before': b['text'], 'after': n['text']})
    return changes


def _key_sort(key):
    """'48조의3' → (48, 3) 숫자 정렬."""
    m = re.match(r'([0-9]+)조(?:의([0-9]+))?', key)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (10**9, 0)


def count_stats(changes):
    return {
        'modified': sum(1 for c in changes if c['change'] == 'modified'),
        'added': sum(1 for c in changes if c['change'] == 'added'),
        'deleted': sum(1 for c in changes if c['change'] == 'deleted'),
    }


# ── Sonnet 분석 ───────────────────────────────────────────

def build_prompt(law_name, enf_date, changes):
    """변경 조문 전/후 텍스트 — 조문당 3,000자, 총 30,000자 절단.
    added는 후만, deleted는 전만 싣는다(스펙)."""
    label = {'modified': '변경', 'added': '신설', 'deleted': '삭제'}
    head = (
        f'당신은 대한민국 전파·통신 법령 분석 전문가다.\n'
        f'「{law_name}」 개정(시행일 {enf_date})의 조문 단위 비교 결과가 아래에 있다.\n'
        f'이를 바탕으로 report_law_diff 도구로 결과를 보고하라.\n'
        f'- summary: 개정 핵심 3~5문장\n'
        f'- impact: 통신사(SK텔레콤) 전파·통신 정책 관점 영향\n'
        f'- urgency: high(즉시 대응)/medium(모니터링)/low(참고)\n'
        f'- articles: 조문별 영향 한두 문장. article_no는 입력의 조번호(예: 48조의3) 그대로.\n\n'
    )
    parts, total = [], 0
    for c in changes:
        seg = f'### 제{c["key"]} [{label[c["change"]]}] — {c["article_no"]}\n'
        if c['change'] == 'added':
            seg += f'[개정 후]\n{c["after"][:ARTICLE_CHARS]}\n'
        elif c['change'] == 'deleted':
            seg += f'[개정 전]\n{(c["before"] or c["after"])[:ARTICLE_CHARS]}\n'
        else:
            seg += (f'[개정 전]\n{c["before"][:ARTICLE_CHARS]}\n'
                    f'[개정 후]\n{c["after"][:ARTICLE_CHARS]}\n')
        if total + len(seg) > TOTAL_CHARS:
            parts.append('…(이하 분량 초과로 생략)')
            break
        parts.append(seg)
        total += len(seg)
    return head + '\n'.join(parts)


def analyze_with_sonnet(client, law_name, enf_date, changes):
    """Sonnet 1콜/법령 — tools로 JSON 스키마 강제. 파싱 실패 시 1회 재시도 후 None.

    temperature 등 샘플링 파라미터는 넣지 않는다(Sonnet 5에서 400).
    thinking을 명시적으로 끈다 — 적응형 추론 기본 ON이라 비스트리밍 응답의
    첫 블록이 thinking일 수 있어, 끄고 tool_use 블록을 type으로 찾는다.
    """
    prompt = build_prompt(law_name, enf_date, changes)
    for attempt in (1, 2):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=8000,
                thinking={'type': 'disabled'},
                tools=[ANALYSIS_TOOL],
                tool_choice={'type': 'tool', 'name': 'report_law_diff'},
                messages=[{'role': 'user', 'content': prompt}],
            )
            block = next((b for b in resp.content if b.type == 'tool_use'), None)
            data = dict(block.input) if block else None
            if data and all(k in data for k in ('summary', 'impact', 'urgency')):
                if data['urgency'] not in ('high', 'medium', 'low'):
                    data['urgency'] = 'medium'
                if not isinstance(data.get('articles'), list):
                    data['articles'] = []
                return data
            print(f'  ! AI 응답 파싱 실패(시도 {attempt}) — tool_use 블록/필수 키 없음')
        except Exception as e:
            print(f'  ! AI 호출 실패(시도 {attempt}): {str(e)[:140]}')
    return None


def merge_article_impacts(changes, ai_articles):
    """AI의 조문별 impact를 정규화 키로 우리 diff 배열에 병합."""
    impacts = {}
    for a in ai_articles or []:
        key = norm_key(str(a.get('article_no', '')))
        if key and a.get('impact'):
            impacts[key] = a['impact']
    return [{
        'article_no': c['article_no'],
        'change': c['change'],
        'before': c['before'],
        'after': c['after'],
        'impact': impacts.get(c['key'], ''),
    } for c in changes]


# ── 후보 수집·저장 ─────────────────────────────────────────

def existing_diff(sb, law_name, new_doc, kind):
    rows = (sb.table('law_diffs').select('id, analyzed_at, diff_kind')
            .eq('law_name', law_name).eq('new_doc', new_doc).eq('diff_kind', kind)
            .limit(1).execute().data) or []
    return rows[0] if rows else None


def process_loaded(sb, ai_client, args, results):
    """(a) sync_state='loaded' — (base=watch_doc_name, new=doc_name, kind='pending')."""
    q = (sb.table('law_pending').select('*')
         .eq('sync_state', 'loaded').not_.is_('doc_name', 'null'))
    if args.law:
        q = q.ilike('law_name', f'%{args.law}%')
    rows = (q.order('law_name').order('enf_date').execute().data) or []
    print(f'=== 시행예정(loaded) 후보 {len(rows)}건 ===')
    for r in rows:
        base_doc, new_doc = r.get('watch_doc_name'), r['doc_name']
        name = r['law_name']
        # 제외: PDF 등재 기준본(800자 청킹이라 article_no 부정확) 또는 law_id 없음
        if not base_doc or base_doc.endswith('.pdf') or not r.get('law_id'):
            why = 'base=PDF본' if (base_doc or '').endswith('.pdf') else 'law_id/기준본 없음'
            print(f'  - 제외: {name} ({why})')
            results['excluded'].append(f'{name}({why})')
            continue
        if not args.backfill:
            ex = existing_diff(sb, name, new_doc, 'pending')
            loaded_at = _parse_ts(r.get('loaded_at'))
            analyzed_at = _parse_ts(ex.get('analyzed_at')) if ex else None
            if ex and analyzed_at and (not loaded_at or analyzed_at >= loaded_at):
                print(f'  - 기분석: {name} (analyzed {analyzed_at:%m-%d %H:%M})')
                results['skipped'] += 1
                continue
        generate_one(sb, ai_client, args, r, base_doc, new_doc, 'pending', results)


def process_promoted(sb, ai_client, args, results):
    """(b) sync_state='promoted' & promoted_at >= now-N일 — kind='promoted'.

    같은 (law_name,new_doc)의 'pending' 분석이 이미 있으면 Sonnet 재호출 없이
    그 행을 diff_kind='promoted'로 UPDATE만 한다(내용은 동일 판이므로 유효).
    """
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    q = (sb.table('law_pending').select('*')
         .eq('sync_state', 'promoted').gte('promoted_at', since)
         .not_.is_('doc_name', 'null'))
    if args.law:
        q = q.ilike('law_name', f'%{args.law}%')
    rows = (q.order('law_name').order('enf_date').execute().data) or []
    print(f'=== 승격(promoted, 최근 {args.days}일) 후보 {len(rows)}건 ===')
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        base_doc, new_doc = r.get('watch_doc_name'), r['doc_name']
        name = r['law_name']
        if existing_diff(sb, name, new_doc, 'promoted'):
            print(f'  - 기전환: {name}')
            results['skipped'] += 1
            continue
        if existing_diff(sb, name, new_doc, 'pending'):
            print(f'  ▶ {name}: pending 분석 재사용 → diff_kind=promoted 전환')
            if not args.dry_run:
                (sb.table('law_diffs')
                 .update({'diff_kind': 'promoted', 'updated_at': now})
                 .eq('law_name', name).eq('new_doc', new_doc)
                 .eq('diff_kind', 'pending').execute())
            results['converted'] += 1
            continue
        if not base_doc or base_doc.endswith('.pdf') or not r.get('law_id'):
            why = 'base=PDF본' if (base_doc or '').endswith('.pdf') else 'law_id/기준본 없음'
            print(f'  - 제외: {name} ({why})')
            results['excluded'].append(f'{name}({why})')
            continue
        generate_one(sb, ai_client, args, r, base_doc, new_doc, 'promoted', results)


def analyze_proposed(client, law_name, deadline, body, cur_arts):
    """입법예고 개정안 1콜 분석. cur_arts={정규화키: (article_no, 본문)}."""
    cur_parts, total = [], 0
    for key, v in cur_arts.items():
        seg = f'### 현행 제{key} — {v["article_no"]}\n{v["text"][:3000]}\n'
        if total + len(seg) > 15000:
            break
        cur_parts.append(seg)
        total += len(seg)
    prompt = (
        f'당신은 대한민국 전파·통신 법령 분석 전문가다.\n'
        f'「{law_name}」 일부개정안이 입법예고되었다(의견제출 마감 {deadline or "미상"}).\n'
        f'아래 [현행 조문]과 [개정안 전문]을 대조해 report_proposed_diff 도구로 보고하라.\n'
        f'- articles의 after는 개정안 문안에서 해당 조문의 개정 후 내용을 원문 그대로 인용(요약 금지).\n'
        f'- 개정안에 없는 조문을 만들어내지 말 것. 현행에 없는 신설 조문은 change=added.\n'
        f'- impact에는 의견제출로 다퉈볼 지점이 있으면 명시.\n\n'
        f'[현행 조문]\n' + '\n'.join(cur_parts) +
        f'\n\n[개정안 전문(첨부 추출)]\n{body[:20000]}'
    )
    for attempt in (1, 2):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=8000,
                thinking={'type': 'disabled'},
                tools=[PROPOSED_TOOL],
                tool_choice={'type': 'tool', 'name': 'report_proposed_diff'},
                messages=[{'role': 'user', 'content': prompt}],
            )
            block = next((b for b in resp.content if b.type == 'tool_use'), None)
            data = dict(block.input) if block else None
            if data and all(k in data for k in ('summary', 'impact', 'urgency')):
                if data['urgency'] not in ('high', 'medium', 'low'):
                    data['urgency'] = 'medium'
                if not isinstance(data.get('articles'), list):
                    data['articles'] = []
                return data
            print(f'  ! AI 응답 파싱 실패(시도 {attempt})')
        except Exception as e:
            print(f'  ! AI 호출 실패(시도 {attempt}): {str(e)[:140]}')
    return None


def process_proposed(sb, ai_client, args, results):
    """(c) 입법예고(proposed) — 공포 전 의견제출 가능 단계 (운영자 지시 2026-08-02).

    과기정통부 입법행정예고 게시물의 개정안 첨부(HWPX/PDF — press_ingest.msit_extract 재사용)를
    추출해 현행 조문(law_watch 등재본)과 대비한다. 확정 전이라 대응 가치가 가장 높아
    대시보드에서 최상위로 정렬된다. 공포되어 pending DIFF가 생기면 같은 법령의 proposed 행은
    generate_one이 삭제(대체)한다.
    """
    import press_ingest
    since = (datetime.now(timezone.utc) - timedelta(days=args.proposed_days)).isoformat()
    q = (sb.table('news_feed').select('title,url,published_at')
         .eq('source', '과기정통부 입법행정예고')
         .gte('published_at', since).order('published_at', desc=True).limit(40))
    rows = (q.execute().data) or []
    print(f'=== 입법예고(proposed, 최근 {args.proposed_days}일) 후보 {len(rows)}건 ===')
    for r in rows:
        name = _proposed_law_name(r.get('title'))
        if not name:
            continue
        if args.law and args.law not in name:
            continue
        url = r['url']
        if not args.backfill and existing_diff(sb, name, url, 'proposed'):
            results['skipped'] += 1
            continue
        print(f'\n▶ {name} [proposed]')
        # 현행 등재본 조회 (law_watch)
        w = (sb.table('law_watch').select('doc_name').eq('law_name', name)
             .limit(1).execute().data) or []
        if not w or not w[0].get('doc_name') or w[0]['doc_name'].endswith('.pdf'):
            print(f'  - 제외: 현행 등재본 없음/PDF본 ({name})')
            results['excluded'].append(f'{name}(현행 미등재)')
            continue
        base_doc = w[0]['doc_name']
        try:
            raw = press_ingest.msit_extract({'url': url})
            body = press_ingest._clean_body(raw) if raw else ''
        except Exception as e:
            print(f'  ! 첨부 추출 오류: {str(e)[:80]}')
            body = ''
        if len(body) < 500:
            print(f'  - 제외: 개정안 첨부 추출 실패({len(body)}자)')
            results['excluded'].append(f'{name}(첨부 추출 실패)')
            continue
        deadline = _proposed_deadline(body)
        keys = list(dict.fromkeys(re.findall(r'제\s*(\d+조(?:의\d+)?)', body)))[:40]
        base = fetch_articles(sb, base_doc)
        cur_arts = {k: base[k] for k in keys if k in base}
        print(f'  첨부 {len(body):,}자 · 언급 조문 {len(keys)}개(현행 매칭 {len(cur_arts)}) '
              f'· 의견마감 {deadline or "미상"}')
        if args.dry_run:
            results['dry'].append((name, 'proposed',
                                   {'modified': len(cur_arts), 'added': 0, 'deleted': 0},
                                   f'첨부 {len(body)}자'))
            continue
        ai = analyze_proposed(ai_client, name, deadline, body, cur_arts)
        if ai is None:
            results['failed'] += 1
            continue
        articles, stats = [], {'modified': 0, 'added': 0, 'deleted': 0}
        for a in ai.get('articles', []):
            key = norm_key(str(a.get('article_no', '')))
            change = a.get('change') if a.get('change') in ('modified', 'added', 'deleted') else 'modified'
            before = cur_arts[key]['text'] if key in cur_arts else ''
            if not before and change == 'modified':
                change = 'added'
            stats[change] += 1
            articles.append({
                'article_no': a.get('article_no', ''),
                'change': change,
                'before': before,
                'after': (a.get('after') or '')[:3000],
                'impact': a.get('impact', ''),
            })
        now = datetime.now(timezone.utc).isoformat()
        sb.table('law_diffs').upsert({
            'law_name': name,
            'enf_date': deadline,          # proposed는 의견마감일을 담는다(화면 라벨 구분)
            'diff_kind': 'proposed',
            'base_doc': base_doc,
            'new_doc': url,
            'summary': ai['summary'],
            'impact': ai['impact'],
            'urgency': ai['urgency'],
            'articles': articles,
            'stats': stats,
            'model': MODEL,
            'analyzed_at': now,
            'updated_at': now,
        }, on_conflict='law_name,new_doc,diff_kind').execute()
        print(f'  ✓ 저장 (urgency={ai["urgency"]}, 조문 {len(articles)}개)')
        results['created'].append((name, stats, ai['urgency']))


def analyze_assembly(client, bill_name, deadline, body, has_table):
    """국회 발의안 1콜 분석. has_table=True면 신·구조문대비표 기반 조문 분석,
    False면 제안이유·주요내용 기반 총괄(articles 빈 배열)만."""
    if has_table:
        prompt = (
            f'당신은 대한민국 전파·통신 법령 분석 전문가다.\n'
            f'국회에 발의된 「{bill_name}」이 입법예고 중이다(의견제출 마감 {deadline or "미상"}).\n'
            f'아래는 의안 원문의 신·구조문대비표(왼쪽 현행 / 오른쪽 개정안)다. '
            f'report_assembly_diff 도구로 보고하라.\n'
            f'- articles: 대비표에 나온 조문만. before/after는 대비표의 현행/개정안 문안을 인용하되, '
            f'개정안 칸의 줄표(-----)는 "현행과 같음" 표기이므로 현행 문안으로 채워 완전한 문장으로 구성.\n'
            f'- 신설 조문은 change=added·before 빈 문자열, 삭제 조문은 change=deleted·after 빈 문자열.\n'
            f'- 대비표에 없는 조문을 만들어내지 말 것.\n'
            f'- impact에는 의견제출로 다퉈볼 지점이 있으면 명시.\n\n'
            f'[신·구조문대비표]\n{body[:20000]}'
        )
    else:
        prompt = (
            f'당신은 대한민국 전파·통신 법령 분석 전문가다.\n'
            f'국회에 발의된 「{bill_name}」이 입법예고 중이다(의견제출 마감 {deadline or "미상"}).\n'
            f'조문 대비표는 확보하지 못했고 아래 제안이유·주요내용만 있다. '
            f'report_assembly_diff 도구로 보고하되 articles는 빈 배열로 두고 '
            f'summary·impact·urgency만 채워라.\n'
            f'- impact에는 의견제출로 다퉈볼 지점이 있으면 명시.\n\n'
            f'[제안이유·주요내용]\n{body[:20000]}'
        )
    for attempt in (1, 2):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=8000,
                thinking={'type': 'disabled'},
                tools=[ASSEMBLY_TOOL],
                tool_choice={'type': 'tool', 'name': 'report_assembly_diff'},
                messages=[{'role': 'user', 'content': prompt}],
            )
            block = next((b for b in resp.content if b.type == 'tool_use'), None)
            data = dict(block.input) if block else None
            if data and all(k in data for k in ('summary', 'impact', 'urgency')):
                if data['urgency'] not in ('high', 'medium', 'low'):
                    data['urgency'] = 'medium'
                if not isinstance(data.get('articles'), list):
                    data['articles'] = []
                return data
            print(f'  ! AI 응답 파싱 실패(시도 {attempt})')
        except Exception as e:
            print(f'  ! AI 호출 실패(시도 {attempt}): {str(e)[:140]}')
    return None


def _existing_assembly_diff(sb, bill_no):
    rows = (sb.table('law_diffs').select('id')
            .eq('origin', 'assembly').eq('new_doc', bill_no)
            .eq('diff_kind', 'proposed').limit(1).execute().data) or []
    return rows[0] if rows else None


def _cleanup_assembly_diffs(sb, dry):
    """수명 관리: origin='assembly' 전 행을 assembly_bills와 bill_no로 대조 —
    proc_result에 가결/폐기/철회가 포함되면 삭제(대안반영폐기 포함). 반환: 삭제 수."""
    rows = (sb.table('law_diffs').select('id, law_name, new_doc')
            .eq('origin', 'assembly').execute().data) or []
    if not rows:
        return 0
    bill_nos = sorted({r['new_doc'] for r in rows if r.get('new_doc')})
    bills = (sb.table('assembly_bills').select('bill_no, proc_result')
             .in_('bill_no', bill_nos).execute().data) or []
    proc = {str(b.get('bill_no')): (b.get('proc_result') or '') for b in bills}
    removed = 0
    for r in rows:
        pr = proc.get(str(r.get('new_doc')), '')
        if not any(k in pr for k in _BILL_DONE_KEYWORDS):
            continue
        if dry:
            print(f'  [dry-run] 수명종료 삭제 대상: {r["law_name"]} '
                  f'의안 {r["new_doc"]} ({pr})')
        else:
            sb.table('law_diffs').delete().eq('id', r['id']).execute()
            print(f'  수명종료 삭제: {r["law_name"]} 의안 {r["new_doc"]} ({pr})')
        removed += 1
    return removed


def process_assembly(sb, ai_client, args, results):
    """(d) 국회 입법예고(origin='assembly') — 의견제출 진행 중 의안의 조문 분석.

    원문 취득 fail-soft 체인: pal 상세의 PDF(신·구조문대비표 구간) →
    PDF는 있으나 대비표 미검출이면 PDF 전문 → BPMBILLSUMMARY 제안이유·주요내용.
    대비표가 아니면 articles 없이 총괄·영향만 담는다. 저장 자리는 gov proposed와
    완전히 동일: enf_date=의견마감일(YYYYMMDD, 화면 _lawDiffDateLabel 계약),
    diff_kind='proposed', new_doc=bill_no, base_doc='국회의안 '+bill_no.
    """
    today = datetime.now(KST).strftime('%Y%m%d')
    rows = (sb.table('assembly_bills')
            .select('bill_id, bill_no, bill_name, notice_end_dt, proc_result')
            .not_.is_('notice_end_dt', 'null').execute().data) or []
    active = []
    for r in rows:
        d8 = re.sub(r'\D', '', r.get('notice_end_dt') or '')[:8]
        if len(d8) == 8 and d8 >= today and r.get('bill_no'):
            r['_deadline'] = d8
            active.append(r)
    # KB 등재 법령만 남긴다(#87) — 대조 실패(None)면 필터 미적용
    kb_keys = _kb_law_keys(sb)
    if kb_keys:
        kept, skipped_kb = [], []
        for r in active:
            tgt = _bill_target_law(r.get('bill_name') or '')
            if _norm_law_name(tgt) in kb_keys:
                kept.append(r)
            else:
                skipped_kb.append(tgt or (r.get('bill_name') or '?'))
        active = kept
        if skipped_kb:
            # 제외분을 반드시 남긴다 — 필요한 법이 빠졌으면 KB에 등재해 되살릴 수 있어야 한다
            print(f'  [KB 대조] 미등재로 제외 {len(skipped_kb)}건: ' +
                  ', '.join(str(x)[:26] for x in skipped_kb[:8]) +
                  (' …' if len(skipped_kb) > 8 else ''))
    print(f'=== 국회 입법예고(assembly) 후보 {len(active)}건 ===')
    for r in active:
        bill_no = str(r['bill_no'])
        bill_name = (r.get('bill_name') or '').strip()
        # 일부개정안은 _proposed_law_name 재사용, 그 외(제정·전부개정)는 발의자 괄호만 제거
        name = _proposed_law_name(bill_name) or \
            re.sub(r'\([^)]*\)\s*$', '', bill_name).strip()
        if not name:
            continue
        if args.law and args.law not in name:
            continue
        if not args.backfill and _existing_assembly_diff(sb, bill_no):
            results['skipped'] += 1
            continue
        print(f'\n▶ {name} [assembly] 의안 {bill_no} · 의견마감 {r["_deadline"]}')
        text = _fetch_bill_pdf_text(r.get('bill_id') or '')
        table = _extract_compare_table(text)
        if table:
            body, mode = table, '대비표'
        elif text:
            body, mode = text, 'PDF전문(대비표 미검출)'
        else:
            body, mode = _fetch_bill_summary(bill_no), '제안이유(API)'
        if len(body) < 100:
            print(f'  - 제외: 원문 취득 실패({mode}, {len(body)}자)')
            results['excluded'].append(f'{name}(의안 원문 취득 실패)')
            continue
        print(f'  원문={mode} {len(body):,}자')
        if args.dry_run:
            results['dry'].append((name, 'assembly',
                                   {'modified': 0, 'added': 0, 'deleted': 0},
                                   f'{mode} {len(body)}자'))
            continue
        ai = analyze_assembly(ai_client, bill_name, r['_deadline'], body,
                              has_table=(mode == '대비표'))
        if ai is None:
            results['failed'] += 1
            continue
        articles, stats = [], {'modified': 0, 'added': 0, 'deleted': 0}
        if mode == '대비표':
            for a in ai.get('articles', []):
                change = a.get('change') if a.get('change') in \
                    ('modified', 'added', 'deleted') else 'modified'
                stats[change] += 1
                articles.append({
                    'article_no': a.get('article_no', ''),
                    'change': change,
                    'before': (a.get('before') or '')[:3000],
                    'after': (a.get('after') or '')[:3000],
                    'impact': a.get('impact', ''),
                })
        now = datetime.now(timezone.utc).isoformat()
        sb.table('law_diffs').upsert({
            'law_name': name,
            'enf_date': r['_deadline'],    # proposed는 의견마감일을 담는다(gov와 동일 자리)
            'diff_kind': 'proposed',
            'origin': 'assembly',
            'base_doc': '국회의안 ' + bill_no,
            'new_doc': bill_no,
            'summary': ai['summary'],
            'impact': ai['impact'],
            'urgency': ai['urgency'],
            'articles': articles,
            'stats': stats,
            'model': MODEL,
            'analyzed_at': now,
            'updated_at': now,
        }, on_conflict='law_name,new_doc,diff_kind').execute()
        print(f'  ✓ 저장 (urgency={ai["urgency"]}, 조문 {len(articles)}개)')
        results['created'].append((name, stats, ai['urgency']))
        results['assembly'] += 1
    # 수명 관리 — 가결·폐기·철회된 의안의 분석 행 정리 (dry면 print만)
    removed = _cleanup_assembly_diffs(sb, args.dry_run)
    if removed:
        print(f'  국회 예고 분석 수명종료 정리 {removed}건')


def generate_one(sb, ai_client, args, row, base_doc, new_doc, kind, results):
    """1개 쌍 처리: 청크 페치 → 조문 diff → (전부개정 판정) → Sonnet → upsert."""
    name = row['law_name']
    print(f'\n▶ {name} [{kind}]')
    print(f'  기준: {base_doc[:70]}')
    print(f'  신본: {new_doc[:70]}')
    base = fetch_articles(sb, base_doc)
    new = fetch_articles(sb, new_doc)
    if not base or not new:
        print(f'  ! 청크 없음(기준 {len(base)}조 / 신본 {len(new)}조) — 건너뜀')
        results['excluded'].append(f'{name}(청크 없음)')
        return
    # 조문 매칭(구↔신 짝짓기)만 법제처 신구법대비표를 정본으로 쓴다. 대비표가 없거나
    # (신구법존재여부=N 등) 실패하면 기존 difflib(청크 article_no 키 조인)로 폴백.
    # 아래 SKT 영향 분석·요약(analyze_with_sonnet)·urgency·articles 스키마는 무변경.
    changes = fetch_oldnew_articles(row.get('mst'), row.get('api_target'))
    match_src = '신구법대비표(정본)' if changes is not None else 'difflib(청크)'
    if changes is None:
        changes = diff_articles(base, new)
    stats = count_stats(changes)
    total = len(set(base) | set(new))
    print(f'  조문 매칭소스={match_src}')
    print(f'  조문 {len(base)}→{len(new)}개 · 변경 {stats["modified"]}'
          f'·신설 {stats["added"]}·삭제 {stats["deleted"]} (전체 {total}조)')

    if not changes:
        print('  → 변경 조문 0건 — 행 미생성')
        results['nochange'] += 1
        return

    full_revision = total and len(changes) / total > FULL_REVISION_RATIO
    if full_revision:
        print(f'  → 변경비율 {len(changes)/total:.0%} — 전부개정으로 판정(AI 생략)')

    if args.dry_run:
        print('  [dry-run] AI·DB 변경 없음')
        results['dry'].append((name, kind, stats, '전부개정' if full_revision else ''))
        return

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        'law_name': name,
        'law_id': row.get('law_id'),
        'mst': row.get('mst'),
        'law_no': row.get('law_no'),
        'enf_date': row.get('enf_date'),
        'diff_kind': kind,
        'base_doc': base_doc,
        'new_doc': new_doc,
        'stats': stats,
        'model': MODEL,
        'analyzed_at': now,
        'updated_at': now,
    }
    if full_revision:
        payload.update({
            'summary': f'전부개정 — 조문 {total}개 중 {len(changes)}개가 바뀌어 조문 단위 '
                       f'비교의 실익이 낮습니다. 원문 수동 비교를 권장합니다.',
            'impact': '전부개정은 편제·조번호가 재구성되므로 국가법령정보센터 원문 대조가 필요합니다.',
            'urgency': 'high',
            'articles': [],
        })
    else:
        ai = analyze_with_sonnet(ai_client, name, row.get('enf_date'), changes)
        if ai is None:
            print(f'  ! AI 분석 실패 — {name} 건너뜀')
            results['failed'] += 1
            return
        payload.update({
            'summary': ai['summary'],
            'impact': ai['impact'],
            'urgency': ai['urgency'],
            'articles': merge_article_impacts(changes, ai.get('articles')),
        })
    sb.table('law_diffs').upsert(payload, on_conflict='law_name,new_doc,diff_kind').execute()
    print(f'  ✓ 저장 (urgency={payload["urgency"]})')
    results['created'].append((name, stats, payload['urgency']))
    # 공포·적재되어 확정본(pending) DIFF가 생기면 같은 법령의 입법예고(proposed) 행은 대체 삭제
    if kind == 'pending':
        try:
            sb.table('law_diffs').delete().eq('diff_kind', 'proposed') \
                .eq('law_name', name).execute()
        except Exception as e:
            print(f'  (proposed 대체 삭제 실패 — 무시) {e}')


# ── 메인 ──────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true',
                    help='수집·diff까지만 수행(AI·DB·텔레그램 없음), 3분류 수치 출력')
    ap.add_argument('--law', help='특정 법령명(부분 일치)만 처리')
    ap.add_argument('--backfill', action='store_true',
                    help='기존 law_diffs 행 무시하고 loaded 전건 재생성')
    ap.add_argument('--days', type=int, default=3, help='promoted 소급 기간(일, 기본 3)')
    ap.add_argument('--proposed-days', type=int, default=60,
                    help='입법예고(proposed) 소급 기간(일, 기본 60)')
    ap.add_argument('--assembly-only', action='store_true',
                    help='국회 입법예고(assembly) 패스만 단독 실행')
    args = ap.parse_args()

    if not (SB_URL and SB_KEY):
        print('오류: .env에 SUPABASE_URL, SUPABASE_SERVICE_KEY 필요')
        sys.exit(1)
    sb = make_client(SB_URL, SB_KEY)

    ai_client = None
    if not args.dry_run:
        if not os.getenv('ANTHROPIC_API_KEY'):
            print('오류: .env에 ANTHROPIC_API_KEY 필요 (--dry-run은 불필요)')
            sys.exit(1)
        import anthropic
        ai_client = anthropic.Anthropic()

    results = {'created': [], 'converted': 0, 'skipped': 0, 'nochange': 0,
               'failed': 0, 'excluded': [], 'dry': [], 'assembly': 0}

    if args.assembly_only:
        process_assembly(sb, ai_client, args, results)
    else:
        process_proposed(sb, ai_client, args, results)   # 의견제출 가능 단계 — 최우선
        process_assembly(sb, ai_client, args, results)   # 국회 입법예고 — 같은 단계
        process_loaded(sb, ai_client, args, results)
        process_promoted(sb, ai_client, args, results)

    print(f'\n=== 완료: 생성 {len(results["created"])} · 전환 {results["converted"]} · '
          f'기존 {results["skipped"]} · 변경없음 {results["nochange"]} · '
          f'실패 {results["failed"]} · 제외 {len(results["excluded"])} ===')
    if results['excluded']:
        print('제외 목록: ' + ', '.join(results['excluded']))
    if args.dry_run and results['dry']:
        print('\n[dry-run 3분류 수치]')
        for name, kind, st, note in results['dry']:
            extra = f' ({note})' if note else ''
            print(f'  - {name} [{kind}]: 변경 {st["modified"]} · 신설 {st["added"]} · '
                  f'삭제 {st["deleted"]}{extra}')

    # 텔레그램 — 신규 생성 1건 이상일 때 1건 발송 (dry-run 제외)
    if not args.dry_run and results['created']:
        lines = [f'📋 <b>법령 DIFF {len(results["created"])}건</b>']
        for name, st, urgency in results['created']:
            lines.append(f'• {name} (변경{st["modified"]}·신설{st["added"]}'
                         f'·삭제{st["deleted"]}, {urgency})')
        if results['assembly']:
            lines.append(f'🏛 국회 예고 분석 {results["assembly"]}건')
        if results['excluded']:
            lines.append(f'※ 제외 {len(results["excluded"])}건')
        lines.append(DASHBOARD_URL)
        send_telegram('\n'.join(lines))

    # heartbeat — 운영 상태 탭 추적용. 신규 0건이어도 기록, 실패해도 무시. (dry-run 제외)
    if not args.dry_run:
        try:
            sb.table('system_health').upsert(
                {'key': 'last_law_diff_run',
                 'updated_at': datetime.now(timezone.utc).isoformat(),
                 'note': 'created=%d converted=%d skipped=%d nochange=%d failed=%d '
                         'excluded=%d assembly=%d'
                         % (len(results['created']), results['converted'], results['skipped'],
                            results['nochange'], results['failed'], len(results['excluded']),
                            results['assembly'])},
                on_conflict='key').execute()
            print('[heartbeat] system_health.last_law_diff_run 갱신')
        except Exception as e:
            print(f'[heartbeat 오류] {e}')


if __name__ == '__main__':
    main()
