# -*- coding: utf-8 -*-
"""
방송미디어통신위원회(방미통위) 위원회 회의 **의사일정** + **보도자료 전건**('제N차 위원회 결과' 포함) 수집
(무인 반복 — GitHub Actions daily_crawl.yml 매시 :17, crawler.py 뒤 단계. 2026-09-11 신설, 배경역사 #154)

⚠ 이름 주의: kmcc.go.kr 은 방송미디어통신위원회(2026 개편 후 새 도메인)로 kcc.go.kr 과 동일 CMS 미러다.
  gov_notice_crawler.crawl_kmcc() 는 이름과 달리 **중앙전파관리소(crms.go.kr)** 를 긁는 함수다(#53).
  이 파일의 'kmcc' 는 방미통위를 뜻한다.

무엇을
  ① 위원회 회의 게시판(boardId=1003) — 글 제목 '2026년 제N차 방송미디어통신위원회 회의(MMDD) 의사일정',
     첨부 '의사일정' PDF 하나만 읽는다(회의 전날 15:50~17:30 게시 실측). 같은 글에 2~3주 뒤 붙는
     회의록·속기록 첨부는 무시한다(운영자 결정 2026-09-11).
  ② 보도자료 게시판(boardId=1113) **전건** (운영자 지시 2026-09-11 — 공지사항 게시판이 아니라 보도자료).
     HTML 본문(td.table_con)만 읽는다 — 첨부(hwp/pdf/hwpx)는 본문과 같은 내용이라 읽지 않는다(운영자 확인).
     · 제목 '2026년 제N차 위원회 결과'(kind='result', 회의 당일 15:00~18:45 게시) → **무조건** 저장, Haiku 안건별 요지 ≤10줄
     · 그 밖의 보도자료(kind='press') → **관련성 필터**(운영자 결정 2026-09-11 "전건은 쓰레기가 많다"): 보도자료 KB 적재와
       같은 기준 — app_config.press_keywords + Haiku 판정(press_relevance_criteria, press_ingest.make_ai_judge 재사용),
       API 불가 시 제목 키워드. 통과분만 저장·발송. 텔레그램은 제목·담당부서·본문 앞부분·링크(요약 없음).
       판정 결과는 **kmcc_press_verdict(url PK)** 에 1회 기록·영구 재사용 — Haiku 판정이 실행마다 뒤집혀 지운 글이
       매시 되살아난 실측(드라마 AI 제작 사례, 2026-09-11 01:49) 때문. 운영자가 relevant 를 고치면 다음 실행에 반영.
  의사일정·위원회 결과는 키워드 필터 없이 무조건 news_feed 에 저장하고(source 2종), 구독자 큐 topic='kmcc' 에
  한 통씩 적재한다(수집 직후 즉시 배달 — subscriber_notify 가 urgent 와 같이 트리거).
  ※ gov_notice_crawler.crawl_kcc() 의 방미통위 보도자료 키워드 수집(17시)은 이것과 중복이라 비활성화했다(#154).

어떻게
  - 의사일정 PDF 는 pdftotext -layout 으로 뽑아도 표 셀이 줄 단위로 교차된다 → Haiku 가 **요약 없이**
    표를 복원(회의명/일시/장소 + 구분|의안명|주요내용|담당과|공개여부). 실패하면 원문 폴백.
  - 위원회 결과는 Haiku 가 안건별 의결 요지 ≤10줄로 요약.
  - news_feed.url 은 상세 글 URL(jsessionid·cp·nop 제거). **fileSeq 를 url 에 넣지 않는다** — 같은 글에
    첨부가 늘어도 행이 늘면 안 된다. 의사일정 수정본(새 fileSeq)은 content 첫 줄의 fileSeq 로 감지해 update.
  - 신규 여부는 upsert(ignore_duplicates) **반환값**으로 판단 — 두 인스턴스가 겹쳐 돌아도 한쪽만 큐 적재.
  - content(원문)·summary(Haiku) 를 여기서 직접 쓴다(refetch_content 는 content ≥100자 행을 건드리지 않음).
heartbeat: system_health key 'last_kmcc_meeting_run', note 'agenda=N result=M press=P skip=S new=K queued=Q fail=F'
필요 env: SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY(없으면 원문 폴백),
         --operator-test 는 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID(운영자 봇)

실행
  python kmcc_meeting.py                       # 수집 + 큐 적재 (Actions)
  python kmcc_meeting.py --dry-run             # 파싱·큐 여부만 출력 (DB·Haiku 무접촉)
  python kmcc_meeting.py --dry-run --ai        # Haiku 까지 호출해 메시지 미리보기 (DB 무접촉)
  python kmcc_meeting.py --operator-test       # 최근 의사일정·위원회 결과·일반 보도자료 1건씩 운영자 봇으로 발송 (DB·큐 무접촉)
  python kmcc_meeting.py --pages 2 --no-notify # 초기 적재 (큐 미적재)
"""
import os
import re
import sys
import time
import argparse
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta, date

# Windows 스케줄러/cp949 콘솔 이모지 크래시 방지 (배경역사 #19)
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

from bs4 import BeautifulSoup

import press_ingest as pi                     # _get/_get_download/_sniff_and_extract/_clean_body 재사용
import api_usage; api_usage.install()         # Anthropic usage 기록(#152) — fail-open
from subscriber_notify import esc, DASHBOARD_URL

try:
    import anthropic
except ImportError:
    anthropic = None

KST = timezone(timedelta(hours=9))
HOST = 'https://www.kmcc.go.kr'
MEETING_LIST = HOST + '/user.do?boardId=1003&page=A02010100&dc=K02010100'
PRESS_LIST   = HOST + '/user.do?boardId=1113&page=A05030000&dc=K05030000'
PAGE_PARAM   = '&cp=%d'                       # kcc 계열 CMS 페이지 파라미터 (press_ingest 실측)

SRC_AGENDA = '방송미디어통신위원회 위원회 회의'
SRC_PRESS  = '방송미디어통신위원회 보도자료'   # 위원회 결과(result)·일반 보도자료(press) 공통
SRC_BY_KIND = {'agenda': SRC_AGENDA, 'result': SRC_PRESS, 'press': SRC_PRESS}
PRESS_SNIPPET = 400        # 일반 보도자료 텔레그램 본문 앞부분 길이
TOPIC = 'kmcc'
HAIKU = 'claude-haiku-4-5-20251001'
HB_KEY = 'last_kmcc_meeting_run'

QUEUE_WINDOW_DAYS = 2      # 게시 후 이틀 안 건만 큐 적재 (백필은 자동 제외)
KEEP_DAYS = 45             # 이보다 오래된 게시글은 저장하지 않음 (news_feed 60일 보존과 정합)
HTML_BUDGET = 2500         # queue_for_subscribers 3500 절단에 닿지 않게 (format_minutes_digest 와 동일)
MAX_AI_PER_RUN = 6         # 실행당 Haiku 상한 (자연 발생 ≤2/시간; --allow-api 로 해제)
RESULT_MAX_LINES = 10
RESULT_LINE_CHARS = 120

AGENDA_RE = re.compile(r'^(\d{4})년\s*제(\d+)차\s*방송미디어통신위원회\s*(서면회의|회의)'
                       r'(?:\s*\((\d{2})(\d{2})\))?\s*의사일정')
RESULT_RE = re.compile(r'^(\d{4})년\s*제(\d+)차\s*위원회\s*결과')
FILESEQ_LINE_RE = re.compile(r'^의사일정 PDF: .* \(fileSeq (\d+)\)', re.M)


# ═══════════════════════════════════════════════════════
#  순수 함수 — 파싱 (tests/test_smoke.py 가 검증)
# ═══════════════════════════════════════════════════════

def canonical_url(href: str) -> str:
    """jsessionid·cp·nop 제거 + 절대 URL. news_feed.url UNIQUE 키라 표기가 흔들리면 안 된다."""
    href = pi._strip_jsession(href or '')
    href = re.sub(r'&(cp|nop)=\d+', '', href)
    href = href.replace('&amp;', '&')
    return href if href.startswith('http') else HOST + href


def parse_agenda_title(title: str):
    m = AGENDA_RE.match((title or '').strip())
    if not m:
        return None
    y, nth, kind, mm, dd = m.groups()
    mdate = None
    if mm:
        try:
            mdate = date(int(y), int(mm), int(dd))
        except ValueError:
            mdate = None
    return {'year': int(y), 'nth': int(nth), 'kind': kind, 'meeting_date': mdate}


def parse_result_title(title: str):
    m = RESULT_RE.match((title or '').strip())
    return {'year': int(m.group(1)), 'nth': int(m.group(2))} if m else None


def _row_common(row, a):
    url = canonical_url(a.get('href', ''))
    bs = re.search(r'boardSeq=(\d+)', url)
    return url, (bs.group(1) if bs else ''), pi._parse_dt(pi._date_from_tds(row))


def parse_meeting_rows(html_text: str) -> list:
    """회의 게시판 행 → 항목. 첨부 칸에서 라벨 '의사일정' 앵커 하나만 고른다(회의록·속기록 무시)."""
    out = []
    for row in BeautifulSoup(html_text, 'html.parser').select('table tbody tr'):
        tds = row.find_all('td')
        if len(tds) < 3:
            continue
        a = tds[1].find('a')
        if not a:
            continue
        title = a.get_text(' ', strip=True)
        meta = parse_agenda_title(title)
        if not meta:
            continue
        agenda = None
        for f in tds[2].find_all('a', href=True):
            label = f.get_text(' ', strip=True)
            img = f.find('img')
            alt = (img.get('alt', '') if img else '') or ''
            if 'download.do' in f['href'] and ('의사일정' in label or '의사일정' in alt):
                fs = re.search(r'fileSeq=(\d+)', f['href'])
                agenda = {'file_seq': fs.group(1) if fs else '', 'filename': alt or label,
                          'url': HOST + pi._strip_jsession(f['href'])}
                break
        url, board_seq, post_date = _row_common(row, a)
        out.append({'kind': 'agenda', 'title': title, 'url': url, 'board_seq': board_seq,
                    'post_date': post_date, 'meta': meta, 'agenda': agenda})
    return out


def parse_press_rows(html_text: str) -> list:
    """보도자료 게시판 행 → 전건. 열: 번호/제목/담당부서/공공누리/첨부/작성일/조회수 (2026-09-11 실측).
    '제N차 위원회 결과' 는 kind='result'(Haiku 요약), 나머지는 kind='press'(AI 없음)."""
    out = []
    for row in BeautifulSoup(html_text, 'html.parser').select('table tbody tr'):
        tds = row.find_all('td')
        if len(tds) < 3:
            continue
        a = tds[1].find('a')
        if not a:
            continue
        title = a.get_text(' ', strip=True)
        if not title or len(title) < 4:
            continue
        dept = tds[2].get_text(' ', strip=True)
        url, board_seq, post_date = _row_common(row, a)
        meta = parse_result_title(title)
        if meta:
            meta['dept'] = dept
            kind = 'result'
        else:
            meta, kind = {'dept': dept}, 'press'
        out.append({'kind': kind, 'title': title, 'url': url, 'board_seq': board_seq,
                    'post_date': post_date, 'meta': meta})
    return out


def parse_agenda_out(txt: str) -> dict:
    """Haiku 복원 텍스트 → {'head': {...}, 'sections': [(절이름, [(구분, 의안명, 주요내용, 담당과, 공개)])]}.
    항목이 하나도 없으면 {} (호출측 원문 폴백 신호)."""
    head, sections, cur = {}, [], None
    for raw in (txt or '').splitlines():
        line = raw.strip().strip('`')
        if not line:
            continue
        m = re.match(r'^\[(.+?)\s*(\d+)건\]$', line)
        if m:
            cur = (m.group(1).strip(), [])
            sections.append(cur)
            continue
        m = re.match(r'^(회의명|일시|장소)\s*[:：]\s*(.+)$', line)
        if m and cur is None:
            v = m.group(2).strip()
            # PDF 머리글 '회 의 명 : 년 2026 제34차 회의' — pdftotext 가 '년'을 앞으로 보낸다(실측). 순서만 되돌린다.
            v = re.sub(r'^년\s*(\d{4})\s*', r'\1년 ', v)
            head[m.group(1)] = v
            continue
        if '|' in line and cur is not None:
            cells = [c.strip() for c in line.split('|')]
            if len(cells) >= 2 and cells[0] and cells[1]:
                while len(cells) < 5:
                    cells.append('')
                cur[1].append(tuple(cells[:5]))
    if not any(items for _, items in sections):
        return {}
    return {'head': head, 'sections': [(n, items) for n, items in sections if items]}


def parse_result_lines(txt: str) -> list:
    """Haiku 요약 → 줄 목록(접두 [의결]/[보고]/[의견청취]/[기타] 보정, 길이 절단)."""
    lines = []
    for raw in (txt or '').splitlines():
        s = re.sub(r'^[\s\-•·*\d.)]+', '', raw.strip()).strip()
        if not s:
            continue
        if not s.startswith('['):
            s = '[기타] ' + s
        if len(s) > RESULT_LINE_CHARS:
            s = s[:RESULT_LINE_CHARS].rstrip() + '…'
        lines.append(s)
    return lines[:RESULT_MAX_LINES]


def should_queue(post_date, now=None) -> bool:
    if not post_date:
        return False
    today = (now or datetime.now(KST)).date()
    return (today - post_date.date()).days <= QUEUE_WINDOW_DAYS


def _md(d) -> str:
    return f'{d.month}/{d.day}' if d else ''


# ═══════════════════════════════════════════════════════
#  순수 함수 — 텔레그램 HTML (format_minutes_digest 규칙: '· ' 불릿, 'N. ' 줄 금지, ≤budget, esc)
# ═══════════════════════════════════════════════════════

def _footer(rest: int, url: str, pdf_url: str = '') -> str:
    bits = [f'… 외 {rest}건'] if rest > 0 else []
    if url:
        bits.append(f'<a href="{esc(url)}">원문</a>')
    if pdf_url:
        bits.append(f'<a href="{esc(pdf_url)}">PDF</a>')
    bits.append(f'<a href="{DASHBOARD_URL}">대시보드</a>')
    return ' · '.join(bits)


def _agenda_header(meta: dict, head: dict, revised: bool = False) -> str:
    kind = '서면회의' if meta.get('kind') == '서면회의' else '회의'
    when = _md(meta.get('meeting_date'))
    tm = re.search(r'(\d{1,2}:\d{2})', head.get('일시', '') or '')
    if tm:
        when = (when + ' ' + tm.group(1)).strip()
    tail = f' · {esc(when)}' if when else ''
    rev = ' (수정)' if revised else ''
    return f'📋 <b>방미통위 제{meta["nth"]}차 {kind} 의사일정{rev}{tail}</b>'


def format_agenda_html(meta: dict, head: dict, sections: list, url: str, pdf_url: str = '',
                       revised: bool = False, budget: int = HTML_BUDGET) -> str:
    parts = [_agenda_header(meta, head, revised)]
    counts = ' · '.join(f'{esc(n)} {len(items)}건' for n, items in sections if items)
    if counts:
        parts.append(f'<i>{counts}</i>')
    parts.append('')
    total = sum(len(items) for _, items in sections)
    shown, stop = 0, False
    for name, items in sections:
        tag = '의결' if '의결' in name else ('보고' if '보고' in name else name[:2])
        for gu, subj, body, dept, open_ in items:
            block = [f'<b>[{esc(tag)}] {esc(gu)}. {esc(subj)}</b>']
            if body:
                block.append(f'· {esc(body)}')
            meta_line = ' · '.join(x for x in (esc(dept), esc(open_)) if x)
            if meta_line:
                block.append(f'· {meta_line}')
            projected = len('\n'.join(parts + block)) + 2 + len(_footer(total - shown - 1, url, pdf_url))
            if projected > budget:
                stop = True
                break
            parts.extend(block)
            shown += 1
        if stop:
            break
    if parts[-1] != '':
        parts.append('')
    parts.append(_footer(total - shown, url, pdf_url))
    return '\n'.join(parts)


def format_agenda_fallback_html(meta: dict, raw_text: str, url: str, pdf_url: str = '',
                                revised: bool = False, budget: int = HTML_BUDGET) -> str:
    """Haiku 실패 시 — 원문 텍스트 앞부분 + 'PDF 원문 확인' 안내."""
    head = _agenda_header(meta, {}, revised)
    foot = _footer(0, url, pdf_url)
    note = '<i>표 복원에 실패해 원문 텍스트를 그대로 싣습니다 — PDF 원문을 확인하세요.</i>'
    room = budget - len(head) - len(foot) - len(note) - 8
    body = esc(re.sub(r'\n{2,}', '\n', (raw_text or '').strip()))[:max(200, room)].rstrip()
    return '\n'.join([head, note, '', body, '', foot])


def format_result_html(meta: dict, post_date, lines: list, url: str, budget: int = HTML_BUDGET) -> str:
    when = _md(post_date) if post_date else ''
    parts = [f'🏛️ <b>방미통위 제{meta["nth"]}차 위원회 결과{(" · " + esc(when)) if when else ""}</b>', '']
    total, shown = len(lines), 0
    for s in lines:
        cand = f'· {esc(s)}'
        if len('\n'.join(parts + [cand])) + 2 + len(_footer(total - shown - 1, url)) > budget:
            break
        parts.append(cand)
        shown += 1
    if parts[-1] != '':
        parts.append('')
    parts.append(_footer(total - shown, url))
    return '\n'.join(parts)


def format_result_fallback_html(meta: dict, post_date, body: str, url: str, budget: int = HTML_BUDGET) -> str:
    when = _md(post_date) if post_date else ''
    head = f'🏛️ <b>방미통위 제{meta["nth"]}차 위원회 결과{(" · " + esc(when)) if when else ""}</b>'
    foot = _footer(0, url)
    room = budget - len(head) - len(foot) - 6
    text = esc(re.sub(r'\n{2,}', '\n', (body or '').strip()))[:max(200, room)].rstrip()
    return '\n'.join([head, '', text, '', foot])


def format_press_html(item: dict, body: str, budget: int = HTML_BUDGET) -> str:
    """일반 보도자료 1건 — 제목·담당부서·본문 앞부분·링크. AI 없음."""
    when = _md(item.get('post_date')) if item.get('post_date') else ''
    dept = (item.get('meta') or {}).get('dept', '')
    head = f'📰 <b>방미통위 보도자료 · {esc(when)}</b>' if when else '📰 <b>방미통위 보도자료</b>'
    parts = [head, '', f'<b>{esc(item["title"])}</b>']
    if dept:
        parts.append(f'· {esc(dept)}')
    text = re.sub(r'\s+', ' ', (body or '').strip())
    if text.startswith(item['title'].strip()):
        text = text[len(item['title'].strip()):].strip()   # 본문 첫 줄이 제목 반복인 경우(실측)
    if text:
        if len(text) > PRESS_SNIPPET:
            text = text[:PRESS_SNIPPET].rstrip() + '…'
        parts.append(f'· {esc(text)}')
    parts.append('')
    parts.append(_footer(0, item['url']))
    out = '\n'.join(parts)
    return out if len(out) <= budget else '\n'.join(parts[:4] + ['', _footer(0, item['url'])])


def agenda_summary_text(head: dict, sections: list) -> str:
    """대시보드 summary 용 — 복원 표를 줄글로."""
    out = [f'{k}: {v}' for k, v in head.items() if v]
    for name, items in sections:
        out.append(f'[{name} {len(items)}건]')
        for gu, subj, body, dept, open_ in items:
            extra = ' · '.join(x for x in (dept, open_) if x)
            out.append(f'{gu}. {subj}' + (f' — {body}' if body else '') + (f' ({extra})' if extra else ''))
    return '\n'.join(out)


# ═══════════════════════════════════════════════════════
#  네트워크 — 본문 추출
# ═══════════════════════════════════════════════════════

def pdf_layout_text(data: bytes) -> str:
    """pdftotext -layout (표 셀 배치 보존). press_ingest._pdf_to_text 는 -layout 없이 호출한다."""
    if not pi.PDFTOTEXT or not data or data[:4] != b'%PDF':
        return ''
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix='.pdf')
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        out = subprocess.run([pi.PDFTOTEXT, '-layout', '-enc', 'UTF-8', tmp, '-'],
                             capture_output=True, timeout=60)
        return out.stdout.decode('utf-8', errors='replace') if out.returncode == 0 else ''
    except Exception:
        return ''
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def fetch_agenda_text(item: dict) -> str:
    """의사일정 PDF → 텍스트. 비면 ''(호출측이 제목·링크로 대체)."""
    ag = item.get('agenda')
    if not ag:
        return ''
    data = pi._get_download(ag['url'], referer=item['url'])
    txt = pdf_layout_text(data)
    if len((txt or '').strip()) < 50:
        txt = pi._sniff_and_extract(data, ag.get('filename', ''))
    return (txt or '').strip()


def fetch_press_body(item: dict) -> str:
    """보도자료 상세 → HTML 본문만(td.table_con → trafilatura 폴백). 첨부는 본문과 같은 내용이라 읽지 않는다(운영자 확인)."""
    res = pi._get(item['url'])
    soup = BeautifulSoup(res.text, 'html.parser')
    td = soup.select_one('table.table_style01 td.table_con')
    body = td.get_text('\n', strip=True) if td else ''
    if len(body) < pi.BODY_MIN:
        body = pi._html_main_text(res.text, item['url']) or ''
    return pi._clean_body(body)


# ═══════════════════════════════════════════════════════
#  Haiku
# ═══════════════════════════════════════════════════════

AGENDA_SYS = ('너는 PDF 표에서 뽑힌 텍스트를 원래 표 구조로 복원하는 도구다. 요약·의역·생략·추가·순서 변경을 '
              '하지 않는다. 셀 안에서 줄바꿈으로 끊긴 어절은 이어 붙이되 단어를 바꾸지 않는다. '
              '확신이 없는 셀은 원문 그대로 둔다. 설명 문장 없이 지정 형식만 출력한다.')
AGENDA_USER = ('아래는 방송미디어통신위원회 의사일정 PDF의 pdftotext -layout 출력이다. '
               '표 열은 구분/의안명/주요내용/담당과/공개여부다. 다음 형식만 출력하라(마크다운·불릿·번호 금지):\n'
               '회의명: …\n일시: …\n장소: …\n[의결사항 N건]\n가|의안명|주요내용|담당과|공개여부\n'
               '[보고사항 N건]\n가|의안명|주요내용|담당과|공개여부\n'
               '(항목이 없는 절은 [절이름 0건] 한 줄만. 표 아래 ※ 비고는 해당 안건의 주요내용 끝에 붙인다.)\n\n---\n{text}')
RESULT_SYS = ('전파·통신·방송 정책 담당자를 위해 위원회 의결 결과를 정확히 요약하는 전문가. '
              '사실만 쓰고 법령명·회사명·수치·시행일은 원문 그대로 옮긴다. 설명 문장 없이 지정 형식만 출력한다.')
RESULT_USER = ('다음 위원회 결과 보도자료를 안건별 의결 요지로 요약하라. 최대 %d줄, 각 줄 %d자 이내, 한 줄에 안건 하나. '
               '줄 앞에 [의결]/[보고]/[의견청취]/[기타] 접두만 붙이고 불릿·번호·마크다운은 쓰지 마라. '
               '의결이 아니라 의견 청취·질의응답만 한 안건은 [의견청취]로 표시한다.\n\n제목: {title}\n\n{body}'
               % (RESULT_MAX_LINES, RESULT_LINE_CHARS))


def haiku(system: str, user: str, max_tokens: int) -> str:
    """실패·키 없음 → ''(호출측 폴백). api_usage.install() 이 usage 를 기록한다."""
    if anthropic is None or not os.environ.get('ANTHROPIC_API_KEY'):
        return ''
    try:
        r = anthropic.Anthropic().messages.create(
            model=HAIKU, max_tokens=max_tokens, temperature=0,
            system=system, messages=[{'role': 'user', 'content': user}])
        return next((b.text for b in r.content if getattr(b, 'type', '') == 'text'), '').strip()
    except Exception as e:
        print('  [Haiku 실패 → 원문 폴백] %s' % str(e)[:100])
        return ''


# ═══════════════════════════════════════════════════════
#  항목 → (content, summary, html)
# ═══════════════════════════════════════════════════════

def build_agenda(item: dict, use_ai: bool, revised: bool = False) -> tuple:
    ag = item.get('agenda') or {}
    raw = fetch_agenda_text(item) if ag else ''
    first = '의사일정 PDF: %s (fileSeq %s)' % (ag.get('filename', '-'), ag.get('file_seq', '-'))
    pdf_url = ag.get('url', '')
    if not raw:
        content = first + '\n' + item['title'] + '\n(PDF 텍스트를 읽지 못했습니다 — 원문·PDF 링크 참조)\n' + item['url']
        return content, '', format_agenda_fallback_html(item['meta'], item['title'], item['url'], pdf_url, revised)
    content = first + '\n\n' + pi._clean_body(raw)
    parsed = parse_agenda_out(haiku(AGENDA_SYS, AGENDA_USER.format(text=raw[:12000]), 3000)) if use_ai else {}
    if not parsed:
        if use_ai:
            print('  [표 복원 실패 → 원문] %s' % item['title'][:50])
        return content, '', format_agenda_fallback_html(item['meta'], raw, item['url'], pdf_url, revised)
    summary = agenda_summary_text(parsed['head'], parsed['sections'])
    html = format_agenda_html(item['meta'], parsed['head'], parsed['sections'], item['url'], pdf_url, revised)
    return content, summary, html


def press_relevant(judge, keywords: list, title: str, body: str) -> tuple:
    """일반 보도자료 관련성 — ① **제목**에 보도자료 키워드가 있으면 AI 없이 통과(안전망: Haiku 가 '갤럭시Z8 지원금
    과장광고'를 무관으로 답한 실측 2026-09-11) ② 없으면 Haiku 판정기(press_ingest.make_ai_judge) ③ 판정기도 없으면 탈락.
    (본문 키워드는 '통신'류가 흔해 너무 느슨하다 — press_ingest 의 무-API 후보 선정도 제목 기준이다.)"""
    hit = next((k for k in keywords if k in (title or '')), None)
    if hit:
        return True, '제목키워드:' + hit
    if judge is not None:
        return judge(title, body)
    return False, '제목 키워드 불일치'


def build_press(item: dict) -> tuple:
    body = fetch_press_body(item)
    content = body if len(body) >= 100 else (body + '\n' + item['url'] + '\n(본문 텍스트 없음 — 원문 링크 참조)')
    return content, '', format_press_html(item, body)


def build_result(item: dict, use_ai: bool) -> tuple:
    body = fetch_press_body(item)
    if len(body) < pi.BODY_MIN:
        raise RuntimeError('본문 추출 실패 (%d자)' % len(body))
    lines = parse_result_lines(haiku(RESULT_SYS, RESULT_USER.format(title=item['title'], body=body[:6000]), 700)) \
        if use_ai else []
    if not lines:
        return body, '', format_result_fallback_html(item['meta'], item['post_date'], body, item['url'])
    return body, '\n'.join(lines), format_result_html(item['meta'], item['post_date'], lines, item['url'])


# ═══════════════════════════════════════════════════════
#  DB
# ═══════════════════════════════════════════════════════

def load_existing(sb) -> dict:
    out = {}
    for src in (SRC_AGENDA, SRC_PRESS):
        try:
            rows = (sb.table('news_feed').select('id,url,content').eq('source', src)
                    .order('created_at', desc=True).limit(200).execute().data) or []
        except Exception as e:
            print('[기존 행 조회 실패] %s: %s' % (src, str(e)[:80]))
            rows = []
        for r in rows:
            if r.get('url'):
                out[r['url']] = r
    return out


def load_verdicts(sb) -> dict:
    """kmcc_press_verdict → {url: relevant}. 실패 시 빈 dict(그 실행만 재판정)."""
    try:
        rows = sb.table('kmcc_press_verdict').select('url,relevant').limit(2000).execute().data or []
        return {r['url']: bool(r['relevant']) for r in rows if r.get('url')}
    except Exception as e:
        print('[판정 캐시 조회 실패 — 재판정] %s' % str(e)[:80])
        return {}


def save_verdict(sb, url: str, title: str, relevant: bool, reason: str) -> None:
    try:
        sb.table('kmcc_press_verdict').upsert(
            {'url': url, 'title': title[:200], 'relevant': relevant, 'reason': (reason or '')[:200]},
            on_conflict='url').execute()
    except Exception as e:
        print('[판정 캐시 저장 실패(무시)] %s' % str(e)[:80])


def make_row(item: dict, content: str, summary: str, now: datetime) -> dict:
    pd = item.get('post_date')
    if pd and pd.date() == now.date():
        published = now
    else:
        published = pd or now
    return {
        'title': item['title'],
        'source': SRC_BY_KIND[item['kind']],
        'category': '기타',
        'url': item['url'],
        'is_read': False,
        'published_at': published.isoformat(),
        'urgency': '보통',
        'importance': '보통',
        'content': content,
        'summary': summary or None,
        'content_fetched_at': now.isoformat(),
    }


def save_row(sb, row: dict) -> bool:
    """upsert(ignore_duplicates) 반환값 = 실제 삽입된 행. 이미 있으면 [] → False."""
    res = sb.table('news_feed').upsert([row], on_conflict='url', ignore_duplicates=True).execute()
    return bool(res.data)


def update_row(sb, row_id, content: str, summary: str, now: datetime) -> bool:
    sb.table('news_feed').update({'content': content, 'summary': summary or None,
                                  'content_fetched_at': now.isoformat(),
                                  'published_at': now.isoformat()}).eq('id', row_id).execute()
    return True


def heartbeat(sb, note: str) -> None:
    try:
        sb.table('system_health').upsert(
            {'key': HB_KEY, 'updated_at': datetime.now(timezone.utc).isoformat(), 'note': note},
            on_conflict='key').execute()
        print('[heartbeat] system_health.%s 갱신 — %s' % (HB_KEY, note))
    except Exception as e:
        print('[heartbeat 오류] %s' % e)


# ═══════════════════════════════════════════════════════
#  수집 루프
# ═══════════════════════════════════════════════════════

KIND_LABEL = {'agenda': '의사일정', 'result': '위원회 결과', 'press': '보도자료'}
# 목록은 2개(회의 게시판·보도자료 게시판). 보도자료 목록에서 kind 가 result/press 로 갈린다.
_LISTS = {'agenda': (MEETING_LIST, parse_meeting_rows),
          'press': (PRESS_LIST, parse_press_rows)}


def list_items(board: str, pages: int) -> list:
    list_url, parse = _LISTS[board]
    items = []
    for p in range(1, pages + 1):
        url = list_url + (PAGE_PARAM % p if p > 1 else '')
        items += parse(pi._get(url).text)
        if p < pages:
            time.sleep(1)
    return items


def run(sb, pages: int = 1, dry: bool = False, notify_q: bool = True, since=None,
        allow_api: bool = False, ai_preview: bool = False) -> dict:
    now = datetime.now(KST)
    st = {'agenda': 0, 'result': 0, 'press': 0, 'skip': 0, 'new': 0, 'queued': 0, 'fail': 0}
    existing = {} if dry else load_existing(sb)
    ai_left = 10 ** 9 if allow_api else MAX_AI_PER_RUN
    use_ai_dry = ai_preview
    from subscriber_notify import queue_for_subscribers
    # 일반 보도자료 관련성 판정기 — KB 보도자료 적재와 같은 기준·같은 함수(press_ingest). dry-run 은 --ai 일 때만 Haiku.
    keywords = pi.load_press_keywords(sb) if sb is not None else list(pi.FALLBACK_KEYWORDS)
    judge = pi.make_ai_judge(sb, keywords) if (ai_preview or not dry) else None
    verdicts = load_verdicts(sb) if sb is not None else {}

    for board in ('agenda', 'press'):
        try:
            items = list_items(board, pages)
        except Exception as e:
            print('[목록 오류] %s: %s' % (board, str(e)[:120]))
            st['fail'] += 1
            continue
        print('[%s 게시판] 목록 %d건' % (KIND_LABEL[board], len(items)))
        for it in items:
            kind = it['kind']
            st[kind] += 1
            pd = it.get('post_date')
            if not pd or (now.date() - pd.date()).days > KEEP_DAYS:
                continue
            if since and pd.date() < since:
                continue
            old = existing.get(it['url'])
            revised = False
            if old and kind == 'agenda' and it.get('agenda'):
                m = FILESEQ_LINE_RE.search(old.get('content') or '')
                revised = bool(m and it['agenda']['file_seq'] and m.group(1) != it['agenda']['file_seq'])
            if old and not revised:
                continue
            if kind == 'press' and verdicts.get(it['url']) is False:
                st['skip'] += 1          # 이미 무관 판정된 글 — 재판정하지 않는다(뒤집힘 방지)
                continue
            use_ai = (ai_left > 0) and (use_ai_dry if dry else True)
            try:
                if kind == 'agenda':
                    content, summary, html = build_agenda(it, use_ai, revised)
                elif kind == 'result':
                    content, summary, html = build_result(it, use_ai)
                else:
                    content, summary, html = build_press(it)
                    if it['url'] in verdicts:
                        ok, reason = verdicts[it['url']], '캐시'
                    else:
                        ok, reason = press_relevant(judge, keywords, it['title'], content)
                        if not dry:
                            save_verdict(sb, it['url'], it['title'], ok, reason)
                    if not ok:
                        st['skip'] += 1
                        print('  [무관 스킵] %s — %s' % (it['title'][:50], reason))
                        continue
            except Exception as e:
                print('  [추출 실패] %s: %s' % (it['title'][:40], str(e)[:100]))
                st['fail'] += 1
                continue
            if summary and use_ai:
                ai_left -= 1
            q = should_queue(pd, now)
            if dry:
                print('  [dry-run] %s | %s | 게시 %s | 본문 %d자 | 요약 %s | 큐=%s%s'
                      % (kind, it['title'][:50], pd.date(), len(content), 'O' if summary else 'X',
                         'O' if q else 'X', ' | 수정본' if revised else ''))
                if ai_preview:
                    print('  ---- 메시지 미리보기 (%d자) ----\n%s\n  ----' % (len(html), html))
                continue
            try:
                if revised:
                    inserted = update_row(sb, old['id'], content, summary, now)
                else:
                    inserted = save_row(sb, make_row(it, content, summary, now))
            except Exception as e:
                print('  [저장 실패] %s: %s' % (it['title'][:40], str(e)[:100]))
                st['fail'] += 1
                continue
            if not inserted:
                print('  [중복] %s — 다른 실행이 먼저 저장' % it['title'][:50])
                continue
            st['new'] += 1
            print('  + %s (%s%s)' % (it['title'][:60], '요약 O' if summary else '요약 X', ', 수정본' if revised else ''))
            if notify_q and q and html:
                try:
                    if queue_for_subscribers(sb, TOPIC, html):
                        st['queued'] += 1
                except Exception as e:
                    print('  [구독자 큐 적재 실패(무시)] %s' % e)
            time.sleep(1)
    return st


def operator_test(pages: int = 1) -> None:
    """최근 의사일정 1건 + 위원회 결과 1건을 실제 형식으로 **운영자 봇**에만 발송. DB·큐 무접촉."""
    import notify
    sent = 0
    agenda_items = [i for i in list_items('agenda', pages) if i.get('post_date')]
    press_items = [i for i in list_items('press', pages) if i.get('post_date')]
    picks = [('agenda', agenda_items[:1]),
             ('result', [i for i in press_items if i['kind'] == 'result'][:1]),
             ('press', [i for i in press_items if i['kind'] == 'press'][:1])]
    for kind, items in picks:
        if not items:
            print('[시험 발송] %s 항목 없음' % kind)
            continue
        it = items[0]
        if kind == 'agenda':
            content, summary, html = build_agenda(it, True)
        elif kind == 'result':
            content, summary, html = build_result(it, True)
        else:
            content, summary, html = build_press(it)
        msg = '🧪 <i>시험 발송 — 구독자에게는 가지 않았습니다</i>\n\n' + html
        print('---- %s (%d자) ----\n%s\n----' % (it['title'], len(msg), msg))
        ok = notify.send_telegram(msg, parse_mode='HTML', disable_web_page_preview=True)
        print('[시험 발송] %s → %s' % (it['title'][:50], '성공' if ok else '실패'))
        sent += 1 if ok else 0
    print('[시험 발송 완료] %d건' % sent)


def main():
    ap = argparse.ArgumentParser(description='방미통위 회의 의사일정·위원회 결과 수집')
    ap.add_argument('--dry-run', action='store_true', help='DB·큐 무접촉, 파싱 결과만 출력')
    ap.add_argument('--ai', action='store_true', help='--dry-run 에서 Haiku 까지 호출해 메시지 미리보기')
    ap.add_argument('--operator-test', action='store_true', help='의사일정·위원회 결과·일반 보도자료 최근 1건씩 운영자 봇으로 시험 발송 (DB 무접촉)')
    ap.add_argument('--no-notify', action='store_true', help='구독자 큐 미적재 (초기 적재용)')
    ap.add_argument('--pages', type=int, default=1, help='목록 페이지 수 (기본 1)')
    ap.add_argument('--since', type=str, default=None, help='YYYY-MM-DD 이후 게시분만')
    ap.add_argument('--allow-api', action='store_true', help='실행당 Haiku 상한(%d) 해제' % MAX_AI_PER_RUN)
    args = ap.parse_args()

    if args.operator_test:
        operator_test(args.pages)
        return

    since = datetime.strptime(args.since, '%Y-%m-%d').date() if args.since else None
    sb = None
    if not args.dry_run:
        from sb_client import make_client
        sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    st = run(sb, pages=args.pages, dry=args.dry_run, notify_q=not args.no_notify,
             since=since, allow_api=args.allow_api, ai_preview=args.ai)
    note = 'agenda=%d result=%d press=%d skip=%d new=%d queued=%d fail=%d' % (
        st['agenda'], st['result'], st['press'], st['skip'], st['new'], st['queued'], st['fail'])
    print('[방미통위 수집 완료] ' + note)
    if not args.dry_run and sb is not None:
        heartbeat(sb, note)


if __name__ == '__main__':
    main()
