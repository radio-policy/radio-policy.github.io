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
    _pdf_to_text,
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

DAE_NUM = '22'                       # 22대 국회
COMM_NAME = '과학기술정보방송통신위원회'
DOC_CATEGORY = '회의록'

BLOCK_TRUNC = 1500                   # 발언 블록당 발췌 상한(자)
MAX_JUDGE_BLOCKS = 40                # 회의당 Haiku 판정 상한 (비용·시간 방어)
MAX_EXCERPTS = 30                    # 회의당 수록 발췌 상한
MAX_AGENDA_LINES = 15                # 개요의 안건 나열 상한

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
    page, psize = 1, 300
    while True:
        data = _api_get(API_MINUTES, {
            'KEY': api_key, 'Type': 'json', 'pIndex': page, 'pSize': psize,
            'DAE_NUM': DAE_NUM, 'CONF_DATE': str(year), 'COMM_NAME': COMM_NAME,
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
#  원문(발언 블록) 확보
# ═══════════════════════════════════════════════════════════

def fetch_speech_blocks(confer_num) -> list:
    """뷰어 HTML에서 발언자 단위 블록 추출.
    반환: [{'name','pos','text'}] — 실패·빈 결과 시 []."""
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


def pdf_fallback_blocks(pdf_url: str) -> list:
    """폴백: 회의록 PDF를 pdftotext 로 추출해 '◯발언자' 단위로 분리.
    국회 PDF는 일부 폰트 글리프가 깨질 수 있음(실측) — 최후 수단."""
    if not pdf_url:
        return []
    data = requests.get(pdf_url, headers=HEADERS, timeout=120).content
    if data[:4] != b'%PDF':
        return []
    txt = _pdf_to_text(data)
    if not txt:
        return []
    blocks = []
    for part in re.split(r'\n(?=◯)', txt):
        if not part.startswith('◯'):
            continue
        label, _, rest = part[1:].partition('\n')
        rest = re.sub(r'\n{2,}', '\n', rest).strip()
        if label.strip() and rest:
            blocks.append({'name': label.strip(), 'pos': '', 'text': rest})
    return blocks


# ═══════════════════════════════════════════════════════════
#  관련 발언 선별 (1차 키워드 → 2차 Haiku)
# ═══════════════════════════════════════════════════════════

def select_relevant(blocks: list, keywords: list, judge, meeting_title: str):
    """키워드 매칭 블록을 Haiku 로 확정.
    반환: (include, confirmed)
      include   — 섹션 발췌용(확정 블록 + 전후 1블록) 인덱스 정렬 목록
      confirmed — 판정 통과 '본' 발언 블록 인덱스(전후 문맥 제외).
                  발언자별 적재(assembly_speeches)는 confirmed 만 사용해 중복 Haiku 콜을 피한다."""
    matched = [i for i, b in enumerate(blocks)
               if any(k in b['text'] for k in keywords)]
    confirmed = []
    for i in matched[:MAX_JUDGE_BLOCKS]:
        b = blocks[i]
        if judge is None:
            confirmed.append(i)
            continue
        ok, reason = judge('%s %s(%s) 발언' % (meeting_title, b['name'], b['pos']),
                           b['text'])
        if ok:
            confirmed.append(i)
    include = set()
    for i in confirmed:
        include.update(j for j in (i - 1, i, i + 1) if 0 <= j < len(blocks))
    return sorted(include), confirmed


# ═══════════════════════════════════════════════════════════
#  섹션 구성·등재
# ═══════════════════════════════════════════════════════════

def _clean_text(text: str) -> str:
    """섹션 파서('## YYMMDD ') 오인 방지 이스케이프 + 공백 정리 (press_ingest._clean_body 준용)."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'(?m)^## (\d{6}) ', r'ㆍ## \1 ', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _section_title(meeting: dict) -> str:
    """'제N차 (주요안건 축약 40자)' — 회의일+회차가 dedupe 키."""
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


def summarize_meeting(meeting_title: str, picked_texts: list) -> str:
    """관련 발언 1~2문장 요약(Haiku) — 목록 화면의 부제로 쓰인다 (운영자 지시 2026-08-02).
    실패·키 없음·발언 없음이면 '' (요약 줄 생략)."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key or not picked_texts:
        return ''
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        joined = '\n'.join(picked_texts)[:6000]
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=200,
            messages=[{'role': 'user', 'content': (
                '아래는 국회 과방위 회의 「%s」에서 발췌한 통신·전파·AI 관련 발언들이다. '
                '통신사(SK텔레콤) 관점에서 어떤 논의가 있었는지 1~2문장(130자 이내)으로 요약하라. '
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
        return txt[:250] if len(txt) >= 10 else ''
    except Exception as e:
        print('  [요약 실패 — 생략] %s' % str(e)[:60])
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
    return n if len(n) >= 2 else raw


def summarize_speech(meeting_title: str, agenda: str, name: str,
                     pos: str, text: str) -> str:
    """발언 1건의 '내용'을 1~2문장으로 요약(Haiku 1콜). 정치적 입장 단정 금지.
    실패·키 없음이면 원문 앞부분을 축약해 폴백(요지 완전 누락 방지)."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    fallback = re.sub(r'\s+', ' ', text).strip()[:120]
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
            model='claude-haiku-4-5-20251001',
            max_tokens=160,
            messages=[{'role': 'user', 'content': prompt}],
        )
        txt = ''
        for blk in resp.content:            # 적응형 추론 대비 — text 블록만
            if getattr(blk, 'type', '') == 'text':
                txt = (blk.text or '').strip()
                break
        txt = re.sub(r'^[#\-•*"\s]*(요약|요지\s*[::]?\s*)?', '', txt)
        txt = txt.replace('\n', ' ').strip()
        return txt[:250] if len(txt) >= 8 else fallback
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


def _primary_agenda(meeting: dict) -> str:
    """회의의 대표 안건 1건(번호 접두 제거)."""
    for a in meeting['agenda']:
        mm = re.match(r'\d+\.\s*(.+)', a)
        if mm:
            return mm.group(1).strip()[:120]
    if meeting['agenda']:
        return re.sub(r'^[o○◦\s]+', '', meeting['agenda'][0]).strip()[:120]
    return ''


def build_speech_rows(meeting: dict, blocks: list, confirmed: list,
                      keywords: list, source_url: str, dry: bool = False) -> list:
    """confirmed 발언 블록을 발언자별 assembly_speeches 행으로 구성.
    요지는 dry-run 이 아닐 때만 Haiku 로 생성(비용 방어)."""
    agenda = _primary_agenda(meeting)
    mdate = (meeting['conf_date'] or '').strip() or None
    rows = []
    seen = set()                    # (speaker, chunk_seq) 중복 방어
    for i in confirmed[:MAX_EXCERPTS]:
        b = blocks[i]
        speaker = normalize_speaker(b['name'])
        key = (speaker, i)
        if key in seen:
            continue
        seen.add(key)
        topic = ', '.join([k for k in keywords if k in b['text']][:5])
        summary = '' if dry else summarize_speech(
            meeting['title'], agenda, speaker, b['pos'], b['text'])
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


def build_section_body(meeting: dict, detail: dict, blocks: list, picked: list,
                       summary: str = '') -> str:
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
    if picked:
        lines.append('관련 발언:')
        lines.append('')
        for i in picked[:MAX_EXCERPTS]:
            b = blocks[i]
            txt = b['text'].replace('\n', ' ').strip()
            if len(txt) > BLOCK_TRUNC:
                txt = txt[:BLOCK_TRUNC] + '…'
            who = '%s(%s)' % (b['name'], b['pos']) if b['pos'] else b['name']
            lines.append('◾ %s: %s' % (who, txt))
            lines.append('')
    else:
        lines.append('(키워드 관련 발언 없음 — 회의 개요만 기록)')
    return _clean_text('\n'.join(lines))


# ═══════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════

def _heartbeat(sb, note: str):
    try:
        sb.table('system_health').upsert(
            {'key': 'last_minutes_run',
             'updated_at': datetime.now(timezone.utc).isoformat(),
             'note': note},
            on_conflict='key').execute()
    except Exception as e:
        print('[heartbeat 오류] %s' % e)


def run(sb, api_key: str, year: int, limit: int = 0, dry: bool = False) -> dict:
    keywords = load_press_keywords(sb)
    judge = make_ai_judge(sb, keywords)
    mode = '키워드+AI판정' if judge else '키워드만(AI 불가 폴백)'
    print('[과방위 회의록] %d년, 모드=%s, 키워드 %d개' % (year, mode, len(keywords)))

    meetings = fetch_meetings(api_key, year)
    print('  회의 %d건 (안건 단위 그룹핑 완료)' % len(meetings))

    doc_name = '과방위_회의록_%d.md' % year
    doc_header = ('# 과방위 회의록 %d년\n\n'
                  '> 출처: 국회 과학기술정보방송통신위원회 회의록 자동 수집 '
                  '(열린국회정보 Open API + 국회회의록시스템)\n\n---\n\n' % year)

    stats = {'new': 0, 'dup': 0, 'fail': 0, 'sp': 0, 'proc': 0}
    for m in meetings:
        # limit 은 '실제로 무언가 적재한(섹션 신규 or 발언 신규) 회의' 수를 센다.
        # 발언 소급 적재 시 섹션은 이미 있어 stats['new'] 가 0이라도 한도가 걸리도록.
        if limit and stats['proc'] >= limit:
            break
        if not m['conf_date'] or not m['dgr']:
            continue
        ymd6 = m['conf_date'].replace('-', '')[2:]
        # dedupe: 섹션(회의록 청크)과 발언(assembly_speeches)을 독립 확인.
        # 섹션은 회의일+회차 접두로 선확인(안건 축약이 바뀌어도 중복 등재 방지).
        # 둘 다 이미 있으면 스킵. 한쪽만 있으면 없는 쪽만 채운다(발언 소급 적재 가능).
        sec_exists = section_exists(sb, doc_name, ymd6, '제%s차 ' % m['dgr'])
        sp_exists = (not dry) and speeches_exist(sb, m['confer_num'])
        if sec_exists and (dry or sp_exists):
            stats['dup'] += 1
            continue
        # 뷰어가 '빈 결과'가 아니라 '예외'로 실패해도 PDF 폴백까지 가야 한다.
        # (2026-08-03: 2024-10-25 국정감사 회의록이 뷰어에서 400을 뱉는데, 예외가 폴백 앞에서
        #  가로채는 바람에 PDF가 멀쩡한데도 영구 실패로 남았다.)
        blocks, src, viewer_err = [], '뷰어', None
        try:
            blocks = fetch_speech_blocks(m['confer_num'])
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
        picked, confirmed = select_relevant(blocks, keywords, judge, m['title'])
        detail = fetch_detail(api_key, m['conf_id'])
        title = _section_title(m)
        picked_texts = ['%s: %s' % (blocks[i]['name'], blocks[i]['text'][:800])
                        for i in picked[:MAX_EXCERPTS]]
        summary = '' if dry else summarize_meeting(m['title'], picked_texts)
        body = build_section_body(m, detail, blocks, picked, summary)
        url = VIEWER_URL % m['confer_num']
        if dry:
            sp_rows = build_speech_rows(m, blocks, confirmed, keywords, url, dry=True)
            speakers = sorted({r['speaker'] for r in sp_rows})
            print('  [dry-run] ## %s %s | 원문=%s 블록 %d, 발췌 %d, %d자'
                  % (ymd6, title, src, len(blocks), len(picked), len(body)))
            print('  발언자별 후보 %d건 / 발언자 %d명: %s'
                  % (len(sp_rows), len(speakers), ', '.join(speakers)[:120]))
            print('  ----- 섹션 미리보기 -----')
            print('\n'.join('  | ' + ln for ln in body.split('\n')[:40]))
            print('  -------------------------')
            stats['new'] += 1
            continue
        did_work = False
        # ① 기존 회의록 섹션(document_chunks) — 없을 때만 등재 (경로 무변경)
        if not sec_exists:
            if register_kb_section(sb, doc_name, DOC_CATEGORY, ymd6, title, body, url,
                                   doc_header):
                print('  [등재] %s %s (%s, 발췌 %d)' % (ymd6, title, src, len(picked)))
                stats['new'] += 1
                did_work = True
            else:
                stats['dup'] += 1
        # ② 발언자별 입장(assembly_speeches) — 없을 때만 적재 (추가 경로)
        if not sp_exists:
            n_sp = upsert_speeches(
                sb, build_speech_rows(m, blocks, confirmed, keywords, url, dry=False))
            if n_sp:
                print('  [발언 적재] %s 발언 %d건' % (ymd6, n_sp))
                stats['sp'] += n_sp
                did_work = True
        if did_work:
            stats['proc'] += 1
        time.sleep(1)

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
    args = ap.parse_args()

    api_key = os.environ.get('ASSEMBLY_API_KEY', '')
    if not api_key:
        print('[오류] ASSEMBLY_API_KEY 환경변수가 없습니다.')
        return
    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    year = args.year or datetime.now(KST).year
    run(sb, api_key, year, limit=args.limit, dry=args.dry_run)


if __name__ == '__main__':
    main()
