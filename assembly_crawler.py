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
import time
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

from supabase import Client
from sb_client import make_client

# ── 환경변수 ─────────────────────────────────────────────────
SUPABASE_URL        = os.environ['SUPABASE_URL']
SUPABASE_KEY        = os.environ['SUPABASE_SERVICE_KEY']
ASSEMBLY_API_KEY    = os.environ.get('ASSEMBLY_API_KEY', '')
TELEGRAM_BOT_TOKEN  = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID    = os.environ.get('TELEGRAM_CHAT_ID', '')

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
]

# 상태 변경 시 알림을 보낼 중요 단계
NOTABLE_STATUS = {
    '소관위 심사중', '법사위 심사중', '본회의 심의',
    '본회의 통과', '대안반영폐기', '부결', '철회',
    '정부이송', '공포',
}

API_BASE = 'https://open.assembly.go.kr/portal/openapi/nzmimeepazxkubdpn'


# ═══════════════════════════════════════════════════════════
#  API 조회
# ═══════════════════════════════════════════════════════════

def fetch_bills(keyword: str, page: int = 1, page_size: int = 100) -> list[dict]:
    """열린국회정보 API로 법안 검색"""
    if not ASSEMBLY_API_KEY:
        print('[경고] ASSEMBLY_API_KEY 없음 — 건너뜀')
        return []

    params = {
        'KEY': ASSEMBLY_API_KEY,
        'Type': 'json',
        'pIndex': page,
        'pSize': page_size,
        'AGE': ASSEMBLY_AGE,
        'BILL_NAME': keyword,
    }
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
                    print(f'  [재시도 {attempt}/3] {keyword}: {e}')
                    time.sleep(5)
                else:
                    raise
        data = resp.json()
        rows_wrapper = data.get('nzmimeepazxkubdpn', [])
        # 응답 구조: [{head: [...]}, {row: [...]}]
        for item in rows_wrapper:
            if 'row' in item:
                return item['row']
        return []
    except Exception as e:
        print(f'  [API 오류] {keyword}: {e}')
        return []


# ═══════════════════════════════════════════════════════════
#  DB 처리
# ═══════════════════════════════════════════════════════════

def load_existing_bills() -> dict[str, dict]:
    """DB의 기존 법안 목록 로드 (bill_id → row)"""
    rows = sb.table('assembly_bills').select('*').execute().data
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
    proc_result  = (bill.get('PROC_RESULT') or '접수').strip()
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

    # 키워드 추가만 있으면 업데이트
    existing_kw = set(existing.get('matched_keywords') or [])
    new_kw      = set(matched_keywords)
    if not new_kw.issubset(existing_kw):
        merged = list(existing_kw | new_kw)
        sb.table('assembly_bills').update({
            'matched_keywords': merged,
            'updated_at': datetime.now(KST).isoformat(),
        }).eq('bill_id', bill_id).execute()

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
    url  = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    resp = requests.post(url, json={
        'chat_id': TELEGRAM_CHAT_ID,
        'text': msg,
        'parse_mode': 'HTML',
    }, timeout=10)
    if resp.status_code != 200:
        print(f'[텔레그램 오류] {resp.status_code}: {resp.text[:100]}')
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
        f'• 상태: {bill.get("PROC_RESULT", "접수")}\n'
        f'• 키워드: {kw_str}'
    )
    if link:
        msg += f'\n🔗 <a href="{link}">의안 바로가기</a>'
    send_telegram(msg)


def notify_status_change(bill: dict, prev_status: str, keywords: list[str]):
    new_status = bill.get('PROC_RESULT', '')
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
#  메인
# ═══════════════════════════════════════════════════════════

def main():
    print(f'[국회 법안 모니터링] 시작 — {datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")}')

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

    print(f'\n  총 고유 법안: {len(collected)}건')

    # DB 저장 및 알림
    new_count     = 0
    changed_count = 0

    for bill_id, (bill, keywords) in collected.items():
        existing = existing_bills.get(bill_id)
        result   = upsert_bill(bill, keywords, existing)

        if result == 'new':
            new_count += 1
            print(f'  🆕 신규: {bill.get("BILL_NAME", "")[:40]}')
            notify_new(bill, keywords)

        elif result == 'status_changed':
            changed_count += 1
            prev = existing['proc_result']
            new  = bill.get('PROC_RESULT', '')
            print(f'  🔄 상태변경: {bill.get("BILL_NAME", "")[:30]} ({prev} → {new})')
            # 중요 상태 변경만 알림 (접수→접수 같은 무의미한 변경 제외)
            if new in NOTABLE_STATUS:
                notify_status_change(bill, prev, keywords)

    print(f'\n[완료] 신규 {new_count}건 | 상태변경 {changed_count}건 | 총 추적 {len(collected)}건')

    if new_count == 0 and changed_count == 0:
        print('  변동 없음')


if __name__ == '__main__':
    main()
