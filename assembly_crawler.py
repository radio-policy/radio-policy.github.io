#!/usr/bin/env python3
"""
국회 법안 모니터링 크롤러
열린국회정보 Open API로 전파·통신 관련 법안을 매일 추적.
신규 법안 발의 또는 처리 상태 변경 시 텔레그램 알림 발송.

GitHub Actions에서 매일 10:00 KST 실행 (assembly_crawl.yml)
API 키: https://open.assembly.go.kr/portal/openApi/selectManualList.do 에서 발급
"""

import os
import re
import sys
import json
import time
import argparse
import bill_stage   # 진행단계 파생(#122) — PROC_RESULT가 비면 회부·상정·법사위·위원회 의결을 구분
import requests
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

try:
    import anthropic
except ImportError:
    anthropic = None

from supabase import Client
from sb_client import make_client
import notify   # 텔레그램 전송 공용 유틸 (개선⑪) — 전송부만 위임

# ── 환경변수 ─────────────────────────────────────────────────
SUPABASE_URL        = os.environ['SUPABASE_URL']
SUPABASE_KEY        = os.environ['SUPABASE_SERVICE_KEY']
ASSEMBLY_API_KEY    = os.environ.get('ASSEMBLY_API_KEY', '')
TELEGRAM_BOT_TOKEN  = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID    = os.environ.get('TELEGRAM_CHAT_ID', '')
ANTHROPIC_API_KEY   = os.environ.get('ANTHROPIC_API_KEY', '')

sb: Client = make_client(SUPABASE_URL, SUPABASE_KEY)
KST = timezone(timedelta(hours=9))

# ── 모니터링 설정 ─────────────────────────────────────────────
ASSEMBLY_AGE = 22  # 22대 국회 (2024~)

# 검색 키워드 — API가 법안명 기준 검색이므로 핵심 법령명 위주
KEYWORDS = [
    '전파법',
    '전기통신사업법',
    '방송통신발전',
    '정보통신망',
    '주파수',
    '전자파',
    '무선국',
    '방송통신설비',
    '적합성평가',
    '이동통신단말',
    '위성통신',
    '기간통신',
    '전파간섭',
    # 통신 인접 법안 보완 (2026-08-02, #64) — 법령명 위주 검색이라 법 이름에 없으면 누락되던 것.
    # 실측 22대 건수: 개인정보 85·인공지능 77·플랫폼 22·데이터 22·클라우드 1·메타버스 1.
    # '정보통신'(203건)·'디지털'(38건 중 헬스케어 등 무관 다수)·'이용자보호'(0건)는 제외 — 소음/무효.
    '개인정보',
    '인공지능',
    '플랫폼',
    '데이터',
    '클라우드',
    '메타버스',
]

# 상태 변경 시 알림을 보낼 중요 단계
NOTABLE_STATUS = {
    '소관위 심사중', '위원회 의결', '법사위 회부', '법사위 심사중', '본회의 심의',
    '본회의 통과', '대안반영폐기', '부결', '철회',
    '정부이송', '공포',
}

API_BASE = 'https://open.assembly.go.kr/portal/openapi/nzmimeepazxkubdpn'

# ── 입법예고 추적 설정 (2026-08-02 신설) ──────────────────────
# 진행중 입법예고 목록 API — AGE 파라미터 무시됨, pSize 최대 1000으로 전량 1콜
NOTICE_API   = 'https://open.assembly.go.kr/portal/openapi/nknalejkafmvgzmpt'
# 제안이유·주요내용 보조 API (BILL_NO로 조회)
SUMMARY_API  = 'https://open.assembly.go.kr/portal/openapi/BPMBILLSUMMARY'
HAIKU_MODEL  = 'claude-haiku-4-5-20251001'  # crawler.py와 동일 모델
# (미사용) 과거 의견등록 마감 D-3 재알림 임계값.
# 운영자 지시(2026-08-03)로 입법예고 알림은 최초 감지 1회만 — 재알림 경로 삭제. 이력용으로만 남김.
NOTICE_DEADLINE_DAYS = 3


# ═══════════════════════════════════════════════════════════
#  API 조회
# ═══════════════════════════════════════════════════════════

# ── 페이징 (2026-09-04 실측 교정) ──────────────────────────────
#  종전 fetch_bills()는 pIndex=1 한 페이지(pSize=100)만 받고 끝났다. 호출부도 page 인자를
#  넘긴 적이 없어, 22대에서 100건을 넘는 키워드(정보통신망·개인정보·인공지능·데이터)는
#  101건째부터 **조용히** 누락됐다(오류 없음 → heartbeat 정상 → 아무도 모름).
#  같은 API가 COMMITTEE=과학기술정보방송통신위원회 조건도 받는데(22대 802건), DB에는
#  그중 311건만 있었다(전체 466건). 키워드 검색은 법안명에 그 말이 있어야만 잡히므로
#  「정보통신공사업법」「위치정보법」「소프트웨어 진흥법」처럼 이름에 키워드가 없는
#  과방위 소관 법안은 구조적으로 못 본다. → ① 페이지를 끝까지 넘긴다(한 페이지가 pSize
#  미만이면 마지막) ② 과방위 소관 전수 스윕(fetch_committee_bills)을 키워드 루프 뒤에 더한다.
#  페이지당 재시도 3회·페이지 간 0.3s 대기는 종전 규칙 그대로.

def _fetch_bill_rows(extra_params: dict, label: str, page_size: int = 100) -> list[dict]:
    """nzmimeepazxkubdpn 공통 페이징 조회. 마지막 페이지(행수 < page_size)까지 전량 반환.
    페이지 하나가 3회 재시도 후에도 실패하면 그때까지 모은 행만 반환(부분 결과·로그)."""
    if not ASSEMBLY_API_KEY:
        print('[경고] ASSEMBLY_API_KEY 없음 — 건너뜀')
        return []

    rows_all: list[dict] = []
    page = 1
    while True:
        params = {
            'KEY': ASSEMBLY_API_KEY,
            'Type': 'json',
            'pIndex': page,
            'pSize': page_size,
            'AGE': ASSEMBLY_AGE,
        }
        params.update(extra_params)
        try:
            # 하루 1회 잡 — 일시 오류 1회가 하루치 누락으로 직결되지 않도록 3회 재시도 (배경역사 #23)
            resp = None
            for attempt in range(1, 4):
                try:
                    resp = requests.get(API_BASE, params=params, timeout=15)
                    resp.raise_for_status()
                    break
                except Exception as e:
                    if attempt < 3:
                        print(f'  [재시도 {attempt}/3] {label} p{page}: {e}')
                        time.sleep(5)
                    else:
                        raise
            data = resp.json()
            rows: list[dict] = []
            # 응답 구조: [{head: [...]}, {row: [...]}] — 결과 없음(INFO-200)이면 키 자체가 없다
            for item in data.get('nzmimeepazxkubdpn', []):
                if 'row' in item:
                    rows = item['row'] or []
                    break
        except Exception as e:
            print(f'  [API 오류] {label} p{page}: {e}' + (f' (앞 {len(rows_all)}건은 유지)' if rows_all else ''))
            return rows_all
        rows_all.extend(rows)
        if len(rows) < page_size:
            break
        page += 1
        time.sleep(0.3)  # API rate limit (페이지 간)
    return rows_all


def fetch_bills(keyword: str, page_size: int = 100) -> list[dict]:
    """열린국회정보 API로 법안명 검색 — 모든 페이지를 합쳐 반환 (종전: 1페이지만)"""
    return _fetch_bill_rows({'BILL_NAME': keyword}, keyword, page_size)


# ── 과방위 소관 전수 스윕 (2026-09-04 신설) ─────────────────────
COMMITTEE_NAME = '과학기술정보방송통신위원회'
COMMITTEE_SWEEP_KEYWORD = '과방위소관'   # 스윕으로 들어온 법안의 matched_keywords 표식
# 법안명에 이 문자열이 있으면 판정 없이 관련(통신·전파·정보통신·데이터·AI·플랫폼 계열 법령군).
# 과방위 소관이라도 원자력·우주·과기 출연연·KAIST·우정·KBS/EBS/MBC 거버넌스 등은 팀 업무 밖이라
# 이 목록에 없는 이름은 건너뛴다. 「방송법…」만은 통신·플랫폼 규제가 섞여 Haiku 판정으로 넘긴다.
COMMITTEE_FAMILIES = [
    '정보통신망 이용촉진', '방송통신위원회의 설치', '방송미디어통신위원회의 설치',
    '정보통신공사업법', '지능정보화 기본법', '위치정보의 보호', '소프트웨어 진흥법',
    '정보보호산업', '디지털포용', '인터넷 멀티미디어 방송', '정보통신 진흥 및 융합',
    '이동통신보안', '디지털 재난', '사이버재해보험', '딥페이크', '시청각미디어',
    '양자과학기술', '장애인 차별조항', '전기통신', '전파법', '방송통신발전', '단말',
    '주파수', '데이터', '클라우드', '인공지능', '개인정보', '플랫폼',
]


def fetch_committee_bills(committee: str = COMMITTEE_NAME) -> list[dict]:
    """소관위 기준 법안 전량 조회(페이징). 행의 COMMITTEE 키를 CURR_COMMITTEE로도 복사해
    upsert_bill·알림·판정 입력(_notice_judge_items)이 키워드 검색 행과 같은 모양으로 쓰게 한다."""
    rows = _fetch_bill_rows({'COMMITTEE': committee}, f'소관위={committee}')
    for b in rows:
        if not b.get('CURR_COMMITTEE') and b.get('COMMITTEE'):
            b['CURR_COMMITTEE'] = b['COMMITTEE']
    return rows


def is_committee_bill_relevant(bill: dict):
    """과방위 소관 법안의 관련성 1차 판정.
    True  = 법안명이 COMMITTEE_FAMILIES 중 하나를 포함 → 관련
    None  = 「방송법…」 → Haiku 판정 필요(호출부가 judge_notices_haiku로 넘김)
    False = 그 외(원자력·우주·출연연 등) → 건너뜀"""
    name = (bill.get('BILL_NAME') or '').strip()
    if not name:
        return False
    if any(f in name for f in COMMITTEE_FAMILIES):
        return True
    if name.startswith('방송법'):
        return None
    return False


def sweep_committee_bills(collected: dict, existing_bills: dict, dry_run: bool = False) -> None:
    """과방위 소관 전수 스윕 — 관련 법안을 collected(bill_id → (row, keywords))에 합친다.
    · 이미 collected에 있으면 키워드 '과방위소관'만 덧붙인다(merge).
    · 「방송법…」은 입법예고 패스와 같은 Haiku 배치 판정(judge_notices_haiku, app_config
      assembly_notice_criteria + 키워드 폴백)을 재사용한다. 이미 추적 중(existing_bills)이면
      판정 없이 관련, 기각 이력(app_config.assembly_committee_rejected)이 있으면 재판정하지 않는다
      — 매일 같은 방송법 수십 건을 다시 판정하는 낭비·판정 흔들림 방지(입법예고 기각 캐시와 같은 원리).
      입법예고 캐시(assembly_notice_rejected)는 진행중 목록 기준으로 매일 정리되므로 키를 분리한다."""
    bills = fetch_committee_bills()
    print(f'  과방위 소관 법안: {len(bills)}건')
    if not bills:
        return

    relevant: list[dict] = []
    pending: list[dict] = []          # 방송법 계열 — Haiku 판정 대상
    auto_pending = 0
    for b in bills:
        bill_id = b.get('BILL_ID', '')
        if not bill_id:
            continue
        verdict = is_committee_bill_relevant(b)
        if verdict is True:
            relevant.append(b)
        elif verdict is None:
            if bill_id in collected or bill_id in existing_bills:
                relevant.append(b)        # 이미 관련으로 잡혀 있는 방송법 → 판정 생략
                auto_pending += 1
            else:
                pending.append(b)

    rejected = load_rejected_cache(COMMITTEE_REJECT_KEY) if pending else {}
    to_judge = [b for b in pending if b['BILL_ID'] not in rejected]
    print(f'  1차 관련(법령군): {len(relevant) - auto_pending}건 | 방송법 계열: {len(pending)}건'
          f' (기존 추적 {auto_pending}건, 기각 캐시 스킵 {len(pending) - len(to_judge)}건, 판정 {len(to_judge)}건)')
    if to_judge:
        nos = judge_notices_haiku(to_judge)
        if nos is None:
            print('  [경고] Haiku 판정 불가 — 키워드 폴백(fail-open)')
            nos = keyword_match_notices(to_judge)
        newly_rejected = 0
        today_tag = datetime.now(KST).strftime('%y%m%d')
        for b in to_judge:
            if (b.get('BILL_NO') or '').strip() in nos:
                relevant.append(b)
                print(f'    ✅ 방송법 관련 판정: [{b.get("BILL_NO", "")}] {(b.get("BILL_NAME") or "")[:50]}')
            else:
                rejected[b['BILL_ID']] = today_tag
                newly_rejected += 1
        if newly_rejected:
            # 22대 안에서는 법안이 목록에서 사라지지 않으므로 현재 목록에 있는 id만 남긴다
            active = {b.get('BILL_ID') for b in bills}
            rejected = {k: v for k, v in rejected.items() if k in active}
            if dry_run:
                print(f'  (dry-run) 과방위 기각 캐시 갱신 생략: +{newly_rejected}건')
            else:
                save_rejected_cache(rejected, COMMITTEE_REJECT_KEY)

    added = merged = 0
    for b in relevant:
        bill_id = b['BILL_ID']
        if bill_id in collected:
            if COMMITTEE_SWEEP_KEYWORD not in collected[bill_id][1]:
                collected[bill_id][1].append(COMMITTEE_SWEEP_KEYWORD)
            merged += 1
        else:
            collected[bill_id] = (b, [COMMITTEE_SWEEP_KEYWORD])
            added += 1
    print(f'  과방위 스윕 결과: 관련 {len(relevant)}건 → 신규 편입 {added}건, 기존 병합 {merged}건')


# ═══════════════════════════════════════════════════════════
#  DB 처리
# ═══════════════════════════════════════════════════════════

def load_existing_bills() -> dict[str, dict]:
    """DB의 기존 법안 목록 로드 (bill_id → row)"""
    # supabase-py 기본 1,000행 상한 — 665건(2026-09-04)이라 아직 한 페이지지만, 넘는 순간 기존 법안이
    # '신규'로 재알림되는 사고가 나므로 처음부터 페이징한다(#122).
    rows: list[dict] = []
    start = 0
    while True:
        page = sb.table('assembly_bills').select('*').order('id').range(start, start + 999).execute().data or []
        rows.extend(page)
        if len(page) < 1000:
            break
        start += 1000
    return {r['bill_id']: r for r in rows}


def bill_link(bill: dict) -> str:
    """의안 상세 URL. API(nzmimeepazxkubdpn)는 LINK_URL을 반환하지 않으므로
    DETAIL_LINK → bill_id 기반 의안정보시스템 URL 순으로 폴백."""
    link = bill.get('LINK_URL', '') or bill.get('DETAIL_LINK', '')
    if not link and bill.get('BILL_ID'):
        link = f'https://likms.assembly.go.kr/bill/billDetail.do?billId={bill["BILL_ID"]}'
    return link


def upsert_bill(bill: dict, matched_keywords: list[str], existing: dict | None) -> str:
    """법안 저장/갱신. 반환값: 'new' | 'status_changed' | 'unchanged'"""
    bill_id      = bill.get('BILL_ID', '')
    bill_name    = bill.get('BILL_NAME', '').strip()
    proc_result  = bill_stage.derive_stage(bill)   # PROC_RESULT 비면 단계 파생(#122)
    propose_dt   = bill.get('PROPOSE_DT', '')
    link_url     = bill_link(bill)

    if not bill_id or not bill_name:
        return 'unchanged'

    row = {
        'bill_id':          bill_id,
        'bill_no':          bill.get('BILL_NO', ''),
        'bill_name':        bill_name,
        'proposer':         bill.get('PROPOSER', ''),
        'committee':        bill.get('CURR_COMMITTEE', ''),
        'proc_result':      proc_result,
        'propose_dt':       propose_dt,
        'proc_dt':          bill.get('PROC_DT', ''),
        'age':              ASSEMBLY_AGE,
        'matched_keywords': matched_keywords,
        'link_url':         link_url,
        'updated_at':       datetime.now(KST).isoformat(),
    }
    stage_cols = bill_stage.stage_columns(bill)      # 회부·상정·위원회 처리·법사위 일자(#122)
    row.update(stage_cols)

    if existing is None:
        # 신규 법안
        row['prev_proc_result'] = proc_result
        sb.table('assembly_bills').insert(row).execute()
        return 'new'

    # 기존 법안 — 상태 변경 확인
    if existing['proc_result'] != proc_result:
        row['prev_proc_result'] = existing['proc_result']
        sb.table('assembly_bills').update(row).eq('bill_id', bill_id).execute()
        return 'status_changed'

    # 키워드 추가·단계 컬럼 변화(라벨은 같아도 처리일 등이 채워진 경우)만 있으면 조용히 업데이트
    existing_kw = set(existing.get('matched_keywords') or [])
    new_kw      = set(matched_keywords)
    upd = {k: v for k, v in stage_cols.items() if existing.get(k) != v}
    if not new_kw.issubset(existing_kw):
        upd['matched_keywords'] = list(existing_kw | new_kw)
    if upd:
        upd['updated_at'] = datetime.now(KST).isoformat()
        sb.table('assembly_bills').update(upd).eq('bill_id', bill_id).execute()

    return 'unchanged'


# ═══════════════════════════════════════════════════════════
#  텔레그램 알림
# ═══════════════════════════════════════════════════════════

def format_date(dt_str: str) -> str:
    """YYYYMMDD → YYYY.MM.DD"""
    if dt_str and len(dt_str) == 8:
        return f'{dt_str[:4]}.{dt_str[4:6]}.{dt_str[6:]}'
    return dt_str or '—'


def send_telegram(msg: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print('[텔레그램] 환경변수 미설정 — 건너뜀')
        return
    # 전송부는 notify 위임 (개선⑪) — 실패 로그는 notify가 출력
    notify.send_telegram(msg, chat_id=TELEGRAM_CHAT_ID, parse_mode='HTML')
    # 구독자 봇: 큐에 적재 → 각자 고른 수신 시각에 모아서 발송 (메시지가 이미 HTML이라 그대로 재사용)
    try:
        from subscriber_notify import queue_for_subscribers
        queue_for_subscribers(sb, 'assembly', msg)
    except Exception as e:
        print(f'[구독자 큐 적재 실패(무시)] {e}')


def notify_new(bill: dict, keywords: list[str]):
    kw_str = ', '.join(keywords)
    dt_str = format_date(bill.get('PROPOSE_DT', ''))
    link   = bill_link(bill)
    msg = (
        f'📋 <b>[국회 신규 법안]</b>\n'
        f'{bill.get("BILL_NAME", "")}\n\n'
        f'• 제안자: {bill.get("PROPOSER", "—")}\n'
        f'• 소관위: {bill.get("CURR_COMMITTEE", "—")}\n'
        f'• 제안일: {dt_str}\n'
        f'• 상태: {bill_stage.derive_stage(bill)}\n'
        f'• 키워드: {kw_str}'
    )
    if link:
        msg += f'\n🔗 <a href="{link}">의안 바로가기</a>'
    send_telegram(msg)


def notify_status_change(bill: dict, prev_status: str, keywords: list[str]):
    new_status = bill_stage.derive_stage(bill)
    link       = bill_link(bill)
    msg = (
        f'🔄 <b>[법안 상태 변경]</b>\n'
        f'{bill.get("BILL_NAME", "")}\n\n'
        f'• {prev_status} → <b>{new_status}</b>\n'
        f'• 소관위: {bill.get("CURR_COMMITTEE", "—")}\n'
        f'• 키워드: {", ".join(keywords)}'
    )
    if link:
        msg += f'\n🔗 <a href="{link}">의안 바로가기</a>'
    send_telegram(msg)


# ═══════════════════════════════════════════════════════════
#  입법예고 추적 패스 (2026-08-02 신설)
#  진행중 입법예고 전량 조회 → 관련성 판정(기존 추적분 자동 관련,
#  신규분 Haiku 배치 판정 + 키워드 폴백) → DB 반영 → 운영자 전용 알림
# ═══════════════════════════════════════════════════════════

def fetch_notices() -> list[dict]:
    """진행중 입법예고 전량 조회 (1콜, pSize 최대 1000, 재시도 3회)"""
    if not ASSEMBLY_API_KEY:
        print('[경고] ASSEMBLY_API_KEY 없음 — 입법예고 건너뜀')
        return []
    params = {
        'KEY': ASSEMBLY_API_KEY,
        'Type': 'json',
        'pIndex': 1,
        'pSize': 1000,
    }
    try:
        resp = None
        for attempt in range(1, 4):
            try:
                resp = requests.get(NOTICE_API, params=params, timeout=15)
                resp.raise_for_status()
                break
            except Exception as e:
                if attempt < 3:
                    print(f'  [재시도 {attempt}/3] 입법예고 목록: {e}')
                    time.sleep(5)
                else:
                    raise
        data = resp.json()
        # 응답 구조: [{head: [...]}, {row: [...]}]
        for item in data.get('nknalejkafmvgzmpt', []):
            if 'row' in item:
                rows = item['row']
                if len(rows) >= 1000:
                    print('  [주의] 입법예고 1000건 도달 — pSize 상한으로 절단 가능성')
                return rows
        return []
    except Exception as e:
        print(f'  [API 오류] 입법예고 목록: {e}')
        return []


def fetch_bill_summary(bill_no: str) -> str:
    """BPMBILLSUMMARY로 제안이유·주요내용 조회. 실패 시 빈 문자열(후속 summarize 잡이 보충)."""
    if not bill_no or not ASSEMBLY_API_KEY:
        return ''
    params = {'KEY': ASSEMBLY_API_KEY, 'Type': 'json', 'BILL_NO': bill_no}
    try:
        resp = requests.get(SUMMARY_API, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        rows = []
        for item in data.get('BPMBILLSUMMARY', []):
            if 'row' in item:
                rows = item['row']
                break
        if not rows:
            return ''
        row = rows[0]
        # 필드명이 문서화돼 있지 않아 방어적으로 탐색: 메타성 키 제외 후
        # SUMMARY/REASON/CONTENT/MAIN 유사 키 우선, 없으면 가장 긴 텍스트 값
        meta_keys = ('BILL_NO', 'BILL_ID', 'BILL_NAME', 'PROPOSER', 'COMMITTEE',
                     'LINK', 'URL', '_DT', 'AGE', 'KIND')
        preferred, others = [], []
        for k, v in row.items():
            if not isinstance(v, str):
                continue
            text = v.strip()
            if len(text) < 30:
                continue
            ku = str(k).upper()
            if any(m in ku for m in meta_keys):
                continue
            if any(s in ku for s in ('SUMMARY', 'REASON', 'CONTENT', 'MAIN')):
                preferred.append(text)
            else:
                others.append(text)
        text = '\n\n'.join(preferred) if preferred else (max(others, key=len) if others else '')
        return text[:4000]
    except Exception as e:
        print(f'  [요약 API 오류(무시)] {bill_no}: {str(e)[:80]}')
        return ''


# ── 관련성 판정 (Haiku 배치, 실패 시 키워드 폴백) ──────────────
# 판정 안정화 (2026-08-02): 같은 법안이 실행마다 관련↔무관으로 뒤집힌 사고 후속.
# ① 40건 단위 배치 분할(주의 분산 방지) ② 제안이유 포함(판정 재료 보강)
# ③ 프롬프트에 결정성 지시(기준문 문자 그대로, 추측 금지, 애매하면 관련)
# ④ 무관 판정 중 경계 후보만 1회 재투표(놓침 방지).
# temperature류 파라미터는 지침 do-not — 넣지 말 것.

JUDGE_BATCH_SIZE = 40          # 배치당 법안 수 (40~50 권장 — 1콜 전량 투입 금지)
SUMMARY_JUDGE_CHARS = 400      # 판정 입력에 넣는 제안이유 절단 길이

# 경계 재투표 선별: 통신 인접 상임위(과방위는 판정 전 자동 관련이라 제외됨)
BORDERLINE_COMMITTEES = ('정무', '행정안전', '산업통상', '문화체육')
# 경계 재투표 선별: 법안명·제안이유에 이 어휘가 있으면 재투표 대상
BORDERLINE_TERMS = ('통신', '데이터', '플랫폼', '개인정보', '전파', '주파수',
                    '방송', '정보통신', '디지털', '인공지능')

NOTICE_JUDGE_TOOL = {
    'name': 'record_notice_relevance',
    'description': '입법예고 법안 목록 중 기준문에 따라 관련으로 판정된 법안의 bill_no 목록을 기록한다.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'relevant_bill_nos': {
                'type': 'array',
                'items': {'type': 'string'},
                'description': '관련 법안의 bill_no 목록. 관련이 하나도 없으면 빈 배열.',
            },
        },
        'required': ['relevant_bill_nos'],
    },
}


def load_notice_criteria() -> str:
    """app_config.assembly_notice_criteria 판정 기준문 조회 (없으면 빈 문자열)"""
    try:
        rows = sb.table('app_config').select('value') \
            .eq('key', 'assembly_notice_criteria').limit(1).execute().data
        if rows and (rows[0]['value'] or '').strip():
            return rows[0]['value'].strip()
    except Exception as e:
        print(f'  [판정기준 조회 실패] {e}')
    return ''


def fetch_candidate_summaries(candidates: list[dict]) -> dict[str, str]:
    """신규 판정 대상(candidates)만 제안이유·주요내용 조회 → {bill_no: 절단 텍스트}.
    기존 추적분·기각 캐시분은 candidates에 없으므로 호출 수는 신규분만큼만 늘어난다.
    개별 실패는 그 법안만 제목 판정으로 폴백(빈 값)."""
    summaries: dict[str, str] = {}
    for n in candidates:
        bill_no = (n.get('BILL_NO') or '').strip()
        if not bill_no:
            continue
        text = fetch_bill_summary(bill_no)   # 실패 시 '' (내부에서 로그)
        if text:
            summaries[bill_no] = ' '.join(text.split())[:SUMMARY_JUDGE_CHARS]
        time.sleep(0.2)  # API rate limit (본 법안 루프 0.3s와 동일 취지)
    return summaries


def _notice_judge_items(batch: list[dict], summaries: dict[str, str]) -> list[dict]:
    """판정 입력 항목 구성 — 제목+위원회+제안이유(있으면)."""
    items = []
    for n in batch:
        bill_no = (n.get('BILL_NO') or '').strip()
        item = {
            'bill_no':   bill_no,
            'bill_name': (n.get('BILL_NAME') or '').strip(),
            'committee': (n.get('CURR_COMMITTEE') or '').strip(),
        }
        summary = summaries.get(bill_no, '')
        if summary:
            item['summary'] = summary
        items.append(item)
    return items


def _judge_batch_haiku(client, criteria: str, batch: list[dict],
                       summaries: dict[str, str]):
    """배치 1개(≤JUDGE_BATCH_SIZE건)를 Haiku 1콜로 판정. 관련 BILL_NO set, 실패 시 None.
    결정성: tool_choice로 판정 강제 + 기준문 문자 적용·추측 금지·애매하면 관련·건별 독립 판정.
    (temperature류 파라미터 사용 금지 — 지침 do-not)"""
    items = _notice_judge_items(batch, summaries)
    prompt = (
        '아래는 국회 입법예고(의견등록 진행중) 법안 목록이다.\n'
        '판정 규칙:\n'
        '1. 각 법안을 목록 내 다른 법안·순서와 무관하게 한 건씩 독립적으로 판정하라.\n'
        '2. 시스템 지시의 기준문을 문자 그대로 적용하라. 기준문에 없는 근거로 추측하지 말라.\n'
        '3. 관련/무관이 애매하면 관련으로 판정하라(놓침보다 과잉 포함이 낫다).\n'
        '관련으로 판정된 법안의 bill_no만 record_notice_relevance 도구로 기록하라. '
        '관련이 하나도 없으면 빈 배열을 기록하라.\n\n'
        + json.dumps(items, ensure_ascii=False, indent=1)
    )
    try:
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=4000,
            system=criteria,
            tools=[NOTICE_JUDGE_TOOL],
            tool_choice={'type': 'tool', 'name': 'record_notice_relevance'},
            messages=[{'role': 'user', 'content': prompt}],
        )
        for blk in resp.content:
            if getattr(blk, 'type', '') == 'tool_use':
                nos = (blk.input or {}).get('relevant_bill_nos') or []
                return {str(x).strip() for x in nos if str(x).strip()}
        return None
    except Exception as e:
        print(f'  [Haiku 판정 실패] {str(e)[:120]}')
        return None


def _is_borderline(n: dict, summaries: dict[str, str]) -> bool:
    """1차 무관 판정 후보 중 재투표 대상인지 — 통신 인접 상임위 또는 경계 어휘 포함."""
    committee = (n.get('CURR_COMMITTEE') or '')
    if any(c in committee for c in BORDERLINE_COMMITTEES):
        return True
    text = (n.get('BILL_NAME') or '') + ' ' + summaries.get((n.get('BILL_NO') or '').strip(), '')
    return any(t in text for t in BORDERLINE_TERMS)


def judge_notices_haiku(candidates: list[dict]):
    """신규 입법예고 후보를 Haiku로 배치 판정(JUDGE_BATCH_SIZE건씩 독립 콜). 관련 BILL_NO set 반환.
    판정 자체가 불가(키·기준문 없음)하면 None → 호출부에서 전체 키워드 폴백(fail-open).
    개별 배치 실패는 그 배치만 키워드 폴백. 1차 무관 중 경계 후보는 1회 재투표(관련이면 채택)."""
    if anthropic is None or not ANTHROPIC_API_KEY:
        print('  [경고] anthropic 미설치 또는 ANTHROPIC_API_KEY 없음')
        return None
    criteria = load_notice_criteria()
    if not criteria:
        print('  [경고] app_config.assembly_notice_criteria 없음 — Haiku 판정 생략')
        return None

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # ② 판정 재료 보강 — 신규 판정 대상만 제안이유 조회 (실패 건은 제목만으로 판정)
    summaries = fetch_candidate_summaries(candidates)
    print(f'  제안이유 확보: {len(summaries)}/{len(candidates)}건')

    # ① 배치 분할 — 배치별 독립 판정, 실패 배치만 키워드 폴백
    relevant: set = set()
    n_batches = (len(candidates) + JUDGE_BATCH_SIZE - 1) // JUDGE_BATCH_SIZE
    for i in range(0, len(candidates), JUDGE_BATCH_SIZE):
        batch = candidates[i:i + JUDGE_BATCH_SIZE]
        nos = _judge_batch_haiku(client, criteria, batch, summaries)
        if nos is None:
            print(f'  [배치 {i // JUDGE_BATCH_SIZE + 1}/{n_batches} 실패] 키워드 폴백({len(batch)}건)')
            nos = keyword_match_notices(batch)
        relevant |= nos

    # ④ 경계 재투표 — 1차 무관 중 경계 후보만 1회 재판정, 관련이면 채택(놓침 방지)
    borderline = [n for n in candidates
                  if (n.get('BILL_NO') or '').strip() not in relevant
                  and _is_borderline(n, summaries)]
    if borderline:
        print(f'  경계 재투표 대상: {len(borderline)}건')
        rescued: set = set()
        for i in range(0, len(borderline), JUDGE_BATCH_SIZE):
            batch = borderline[i:i + JUDGE_BATCH_SIZE]
            nos = _judge_batch_haiku(client, criteria, batch, summaries)
            if nos:                       # 실패(None)면 1차 무관 유지 — 추가 폴백 없음
                rescued |= nos
        if rescued:
            print(f'  경계 재투표 구제: {len(rescued)}건')
        relevant |= rescued

    return relevant


def keyword_match_notices(candidates: list[dict]) -> set:
    """키워드 폴백: bill_name에 KEYWORDS 포함 여부로 관련 BILL_NO 집합 산출"""
    return {
        (n.get('BILL_NO') or '')
        for n in candidates
        if any(kw in (n.get('BILL_NAME') or '') for kw in KEYWORDS)
    }


# ── 기각 캐시 (app_config.assembly_notice_rejected — {bill_id: 'YYMMDD'}) ──
# 같은 형식의 두 번째 키 assembly_committee_rejected(과방위 스윕 방송법 판정 기각분)는 key 인자로 구분.
NOTICE_REJECT_KEY    = 'assembly_notice_rejected'
COMMITTEE_REJECT_KEY = 'assembly_committee_rejected'


def load_rejected_cache(key: str = NOTICE_REJECT_KEY) -> dict:
    try:
        rows = sb.table('app_config').select('value') \
            .eq('key', key).limit(1).execute().data
        if rows and (rows[0]['value'] or '').strip():
            cache = json.loads(rows[0]['value'])
            if isinstance(cache, dict):
                return cache
    except Exception as e:
        print(f'  [기각 캐시 조회 실패(빈 캐시로 진행)] {e}')
    return {}


def save_rejected_cache(cache: dict, key: str = NOTICE_REJECT_KEY):
    try:
        sb.table('app_config').upsert(
            {'key': key,
             'value': json.dumps(cache, ensure_ascii=False)},
            on_conflict='key').execute()
        print(f'  기각 캐시 저장: {len(cache)}건')
    except Exception as e:
        print(f'  [기각 캐시 저장 실패] {e}')


# ── 입법예고 알림 (운영자 + 구독자 '법안 동향' 토픽) ──

def send_operator_alert(lines: list[str]) -> bool:
    """운영자 봇 발송 + 구독자 큐('assembly') 적재. 반환=운영자 발송 성공 여부.

    2026-08-03 변경: 원래 운영자 전용이었으나, 「법안 동향」을 켠 구독자가 정작 **의견을 낼 수 있는
    유일한 시점**(입법예고, 10~25일)을 못 받는 상태였다. 구독봇을 만들 때(8/1) 법안 발의·처리 변경만
    연결했고 입법예고는 나중에 만든 기능이라 빠진 것 — 의도된 설계가 아니라 누락이었다.
    별도 토픽을 만들지 않고 'assembly'에 합친다(운영자 판단: 토픽 수를 늘리지 않는다).

    분할(3800자)·전송·재시도는 notify 위임 (개선⑪).
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print('[텔레그램] 환경변수 미설정 — 입법예고 알림 건너뜀')
        return False
    msg = '\n\n'.join(lines)
    ok = notify.send_telegram(msg, chat_id=TELEGRAM_CHAT_ID)
    # 구독자 큐는 fail-open — 적재가 실패해도 운영자 발송 결과(=stage 갱신 판단)에 영향 주지 않는다
    try:
        from subscriber_notify import queue_for_subscribers
        queue_for_subscribers(sb, 'assembly', msg)
    except Exception as e:
        print(f'[구독자 큐 적재 실패(무시)] {e}')
    return ok


def notice_heartbeat(note: str):
    try:
        sb.table('system_health').upsert(
            {'key': 'last_assembly_run',
             'updated_at': datetime.now(timezone.utc).isoformat(),
             'note': note},
            on_conflict='key').execute()
    except Exception as e:
        print(f'[heartbeat 오류] {e}')


def _days_to_deadline(end_dt: str, today) -> int | None:
    """'YYYY-MM-DD' → 오늘(KST) 기준 잔여 일수. 파싱 실패 시 None."""
    try:
        return (datetime.strptime(end_dt, '%Y-%m-%d').date() - today).days
    except Exception:
        return None


def run_notice_pass(dry_run: bool = False):
    """입법예고 추적 패스 — main() 기존 법안 루프 뒤에 호출"""
    print(f'\n[입법예고 추적] 시작{" (DRY-RUN — DB 쓰기·알림 없음)" if dry_run else ""}')

    notices = fetch_notices()
    if not notices:
        print('  진행중 입법예고 0건(또는 API 오류) — 패스 종료')
        if not dry_run:
            notice_heartbeat('notices active=0 (skip)')
        return

    active_ids = {n.get('BILL_ID', '') for n in notices if n.get('BILL_ID')}
    print(f'  진행중 입법예고: {len(notices)}건')

    existing = load_existing_bills()  # 본 패스 직전 재로드 (앞 루프의 신규 insert 포함)
    rejected = load_rejected_cache()

    # ── 관련성 분류: 기존 추적분 자동 관련 / 기각 캐시 스킵 / 나머지 Haiku 판정 ──
    auto_relevant, candidates, skipped_cached = [], [], 0
    for n in notices:
        bill_id = n.get('BILL_ID', '')
        if not bill_id or not (n.get('BILL_NAME') or '').strip():
            continue
        if bill_id in existing:
            auto_relevant.append(n)
        # 과방위 소관은 AI 판정 없이 자동 관련 — 경계선 판정 흔들림 방어 (회의록 전량 수집 방침과 일관)
        elif '과학기술정보방송통신' in (n.get('CURR_COMMITTEE') or ''):
            auto_relevant.append(n)
        elif bill_id in rejected:
            skipped_cached += 1
        else:
            candidates.append(n)
    print(f'  자동 관련(기존 추적): {len(auto_relevant)}건 | 기각 캐시 스킵: {skipped_cached}건 | 신규 판정 대상: {len(candidates)}건')

    rel_new, rejected_new = [], []
    if candidates:
        rel_nos = judge_notices_haiku(candidates)
        if rel_nos is None:
            print('  [경고] Haiku 판정 불가 — 키워드 폴백(fail-open)')
            rel_nos = keyword_match_notices(candidates)
        for n in candidates:
            if (n.get('BILL_NO') or '') in rel_nos:
                rel_new.append(n)
            else:
                rejected_new.append(n)

    relevant = auto_relevant + rel_new
    print(f'  관련 판정: 총 {len(relevant)}건 (신규 {len(rel_new)}건) | 신규 기각: {len(rejected_new)}건')
    for n in rel_new:
        print(f'    ✅ 관련 신규: [{n.get("BILL_NO", "")}] {(n.get("BILL_NAME") or "")[:50]}')

    # ── 기각 캐시 갱신: 신규 기각 추가 + 진행 목록에서 사라진 id 제거 ──
    today_tag = datetime.now(KST).strftime('%y%m%d')
    new_cache = {bid: d for bid, d in rejected.items() if bid in active_ids}
    for n in rejected_new:
        new_cache[n['BILL_ID']] = today_tag
    if new_cache != rejected:
        if dry_run:
            print(f'  (dry-run) 기각 캐시 갱신 생략: {len(rejected)} → {len(new_cache)}건')
        else:
            save_rejected_cache(new_cache)

    # ── DB 반영 + 알림 스테이지 판단 ──
    today          = datetime.now(KST).date()
    alert_lines    = []   # 운영자 메시지(여러 건 한 메시지로 묶음)
    stage_updates  = {}   # bill_id → 새 notice_alert_stage (발송 성공 시에만 반영)
    new_rows       = 0

    for n in relevant:
        bill_id   = n['BILL_ID']
        name      = (n.get('BILL_NAME') or '').strip()
        end_dt    = (n.get('NOTI_ED_DT') or '').strip()[:10]
        url       = (n.get('LINK_URL') or '').strip()
        committee = (n.get('CURR_COMMITTEE') or '').strip()
        ex        = existing.get(bill_id)
        prev_stage = int((ex.get('notice_alert_stage') if ex else 0) or 0)
        stage      = prev_stage

        if ex:
            updates = {}
            if end_dt and ex.get('notice_end_dt') != end_dt:
                updates['notice_end_dt'] = end_dt
            if url and ex.get('notice_url') != url:
                updates['notice_url'] = url
            if committee and not (ex.get('committee') or '').strip():
                updates['committee'] = committee
            if updates:
                updates['updated_at'] = datetime.now(KST).isoformat()
                if dry_run:
                    print(f'  (dry-run) 기존 행 갱신: {name[:40]} → {sorted(updates)}')
                else:
                    sb.table('assembly_bills').update(updates).eq('bill_id', bill_id).execute()
        else:
            row = {
                'bill_id':            bill_id,
                'bill_no':            n.get('BILL_NO', ''),
                'bill_name':          name,
                'proposer':           n.get('PROPOSER', ''),
                'committee':          committee,
                'proc_result':        '접수',
                'prev_proc_result':   '접수',
                'age':                ASSEMBLY_AGE,
                'matched_keywords':   [],
                'link_url':           bill_link(n),
                'notice_end_dt':      end_dt,
                'notice_url':         url,
                'notice_alert_stage': 0,
                'updated_at':         datetime.now(KST).isoformat(),
            }
            if dry_run:
                print(f'  (dry-run) 신규 행 insert: [{row["bill_no"]}] {name[:40]} (~{end_dt})')
            else:
                summary = fetch_bill_summary(row['bill_no'])  # 실패 시 생략 — summarize 잡이 후속
                if summary:
                    row['summary'] = summary
                sb.table('assembly_bills').insert(row).execute()
            new_rows += 1

        # 알림 스테이지: 0 → 최초 감지 알림(stage 1). 여기서 끝.
        # 운영자 지시(2026-08-03): 입법예고 알림은 최초 1회만.
        #   기존 stage 1→2(마감 D-3 재알림)는 같은 법안을 두 번 울려 제거했다.
        #   컬럼 notice_alert_stage 와 기존 값 2는 이력으로 남기고, 2로 올리는 경로만 삭제.
        #   마감일 정보는 최초 알림의 '(~end_dt)'와 브리핑 태그 '[의견등록 ~08-06 (D-3)]'로 전달된다.
        if stage == 0:
            days_left = _days_to_deadline(end_dt, today)
            dday = f', D-{days_left}' if days_left is not None else ''
            line = f'🗳️ 국회 입법예고 시작: {name} (~{end_dt or "?"}{dday}, {committee or "—"})'
            if url:
                line += f'\n{url}'
            alert_lines.append(line)
            stage = 1
        if stage != prev_stage:
            stage_updates[bill_id] = stage

    # ── 알림 발송 (운영자 전용) + 발송 성공 시에만 stage 반영 ──
    if alert_lines:
        if dry_run:
            print(f'  (dry-run) 알림 {len(alert_lines)}건 미발송 — 내용:')
            for line in alert_lines:
                print('    ' + line.replace('\n', ' | '))
        else:
            if send_operator_alert(alert_lines):
                for bill_id, stage in stage_updates.items():
                    sb.table('assembly_bills').update(
                        {'notice_alert_stage': stage}).eq('bill_id', bill_id).execute()
                print(f'  알림 발송 완료: {len(alert_lines)}건 (stage 갱신 {len(stage_updates)}건)')
            else:
                print('  [경고] 운영자 알림 실패 — stage 미변경(다음 실행에서 재시도)')
    else:
        print('  알림 대상 없음')

    # d3= 항목 제거 — D-3 재알림 폐지(운영자 지시 2026-08-03). alerts=최초 감지 알림 건수
    note = f'notices active={len(notices)} rel={len(relevant)} new={new_rows} alerts={len(alert_lines)}'
    if dry_run:
        print(f'  (dry-run) heartbeat 생략: {note}')
    else:
        notice_heartbeat(note)
    print(f'[입법예고 추적] 완료 — {note}')


# ═══════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════

def main(dry_run: bool = False, suppress_status_alerts: bool = False):
    print(f'[국회 법안 모니터링] 시작 — {datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")}'
          + (' [DRY-RUN — DB 쓰기·알림 없음]' if dry_run else '')
          + (' [상태변경 알림 억제]' if suppress_status_alerts else ''))

    if not ASSEMBLY_API_KEY:
        print('[오류] ASSEMBLY_API_KEY 환경변수가 없습니다.')
        print('  → https://open.assembly.go.kr/portal/openApi/selectManualList.do 에서 API 키 발급 후')
        print('  → GitHub Secrets에 ASSEMBLY_API_KEY로 등록하세요.')
        return

    # 기존 DB 법안 로드
    existing_bills = load_existing_bills()
    print(f'  기존 추적 법안: {len(existing_bills)}건')

    # 키워드별 수집 (bill_id 기준 중복 제거)
    collected: dict[str, tuple[dict, list[str]]] = {}  # bill_id → (bill_row, keywords)

    for keyword in KEYWORDS:
        print(f'  검색: "{keyword}"', end=' ')
        bills = fetch_bills(keyword)
        print(f'→ {len(bills)}건')

        for b in bills:
            bill_id = b.get('BILL_ID', '')
            if not bill_id:
                continue
            if bill_id in collected:
                collected[bill_id][1].append(keyword)
            else:
                collected[bill_id] = (b, [keyword])

        time.sleep(0.3)  # API rate limit

    # ── 과방위 소관 전수 스윕 (2026-09-04) — 키워드 루프와 독립: 오류가 나도 키워드 수집분은 저장 ──
    try:
        sweep_committee_bills(collected, existing_bills, dry_run=dry_run)
    except Exception as e:
        print(f'  [과방위 스윕 오류(무시)] {e}')

    print(f'\n  총 고유 법안: {len(collected)}건')

    # DB 저장 및 알림
    new_count     = 0
    changed_count = 0

    for bill_id, (bill, keywords) in collected.items():
        existing = existing_bills.get(bill_id)

        if dry_run:
            # DB 무변경 — 결과만 판정해서 출력
            proc = bill_stage.derive_stage(bill)
            if existing is None:
                result = 'new'
            elif existing['proc_result'] != proc:
                result = 'status_changed'
            else:
                result = 'unchanged'
        else:
            result = upsert_bill(bill, keywords, existing)

        if result == 'new':
            new_count += 1
            print(f'  🆕 신규: {bill.get("BILL_NAME", "")[:40]}')
            if not dry_run:
                notify_new(bill, keywords)

        elif result == 'status_changed':
            changed_count += 1
            prev = existing['proc_result']
            new  = bill_stage.derive_stage(bill)
            print(f'  🔄 상태변경: {bill.get("BILL_NAME", "")[:30]} ({prev} → {new})')
            # 중요 상태 변경만 알림 (접수→소관위 회부 같은 사소한 변경 제외).
            # --suppress-status-alerts: 단계 파생 규칙 배포 직후 1회 백필용 — 수백 건이 한꺼번에
            # '접수'→상정 이후 라벨로 바뀌는 것은 실제 변동이 아니므로 알림을 내지 않는다(#122).
            if not dry_run and not suppress_status_alerts and new in NOTABLE_STATUS:
                notify_status_change(bill, prev, keywords)

    print(f'\n[완료] 신규 {new_count}건 | 상태변경 {changed_count}건 | 총 추적 {len(collected)}건')

    if new_count == 0 and changed_count == 0:
        print('  변동 없음')

    # ── 입법예고 추적 패스 (기존 법안 루프와 독립 — 오류가 전체를 죽이지 않게) ──
    try:
        run_notice_pass(dry_run=dry_run)
    except Exception as e:
        print(f'[입법예고 패스 오류] {e}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='국회 법안·입법예고 모니터링 크롤러')
    parser.add_argument('--dry-run', action='store_true',
                        help='DB 쓰기·텔레그램 알림 없이 수집/판정 결과만 출력')
    parser.add_argument('--suppress-status-alerts', action='store_true',
                        help='DB는 갱신하되 상태변경 알림만 건너뜀 — 단계 라벨 규칙 변경 직후 1회 백필 전용(신규 법안 알림은 그대로)')
    args = parser.parse_args()
    main(dry_run=args.dry_run, suppress_status_alerts=args.suppress_status_alerts)
