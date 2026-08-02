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
]

# 상태 변경 시 알림을 보낼 중요 단계
NOTABLE_STATUS = {
    '소관위 심사중', '법사위 심사중', '본회의 심의',
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
NOTICE_DEADLINE_DAYS = 3  # 의견등록 마감 D-3 이내 알림


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


def judge_notices_haiku(candidates: list[dict]):
    """신규 입법예고 후보를 Haiku 1콜 배치 판정. 관련 BILL_NO 집합(set) 반환.
    호출 불가/실패 시 None → 호출부에서 키워드 폴백(fail-open)."""
    if anthropic is None or not ANTHROPIC_API_KEY:
        print('  [경고] anthropic 미설치 또는 ANTHROPIC_API_KEY 없음')
        return None
    criteria = load_notice_criteria()
    if not criteria:
        print('  [경고] app_config.assembly_notice_criteria 없음 — Haiku 판정 생략')
        return None
    items = [{
        'bill_no':   (n.get('BILL_NO') or ''),
        'bill_name': (n.get('BILL_NAME') or '').strip(),
        'committee': (n.get('CURR_COMMITTEE') or '').strip(),
    } for n in candidates]
    prompt = (
        '아래는 국회 입법예고(의견등록 진행중) 법안 목록이다. 시스템 지시의 기준문에 따라 '
        '관련된 법안의 bill_no만 골라 record_notice_relevance 도구로 기록하라. '
        '관련이 하나도 없으면 빈 배열을 기록하라.\n\n'
        + json.dumps(items, ensure_ascii=False)
    )
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
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


def keyword_match_notices(candidates: list[dict]) -> set:
    """키워드 폴백: bill_name에 KEYWORDS 포함 여부로 관련 BILL_NO 집합 산출"""
    return {
        (n.get('BILL_NO') or '')
        for n in candidates
        if any(kw in (n.get('BILL_NAME') or '') for kw in KEYWORDS)
    }


# ── 기각 캐시 (app_config.assembly_notice_rejected — {bill_id: 'YYMMDD'}) ──

def load_rejected_cache() -> dict:
    try:
        rows = sb.table('app_config').select('value') \
            .eq('key', 'assembly_notice_rejected').limit(1).execute().data
        if rows and (rows[0]['value'] or '').strip():
            cache = json.loads(rows[0]['value'])
            if isinstance(cache, dict):
                return cache
    except Exception as e:
        print(f'  [기각 캐시 조회 실패(빈 캐시로 진행)] {e}')
    return {}


def save_rejected_cache(cache: dict):
    try:
        sb.table('app_config').upsert(
            {'key': 'assembly_notice_rejected',
             'value': json.dumps(cache, ensure_ascii=False)},
            on_conflict='key').execute()
        print(f'  기각 캐시 저장: {len(cache)}건')
    except Exception as e:
        print(f'  [기각 캐시 저장 실패] {e}')


# ── 운영자 전용 알림 (send_telegram 사용 금지 — 구독자 큐 적재 없음) ──

def send_operator_alert(lines: list[str]) -> bool:
    """운영자 봇으로만 발송. 여러 건은 한 메시지로 묶고 4096자 한도 전에 분할.

    분할(3800자)·전송·재시도는 notify 위임 (개선⑪). 구독자 큐 적재 없음 — 유지."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print('[텔레그램] 환경변수 미설정 — 입법예고 알림 건너뜀')
        return False
    return notify.send_telegram('\n\n'.join(lines), chat_id=TELEGRAM_CHAT_ID)


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
    d3_count       = 0

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

        # 알림 스테이지: 0 → 시작 알림(stage 1) → 마감 D-3 이내 알림(stage 2)
        if stage == 0:
            line = f'🗳️ 국회 입법예고 시작: {name} (~{end_dt or "?"}, {committee or "—"})'
            if url:
                line += f'\n{url}'
            alert_lines.append(line)
            stage = 1
        days_left = _days_to_deadline(end_dt, today)
        if stage < 2 and days_left is not None and 0 <= days_left <= NOTICE_DEADLINE_DAYS:
            alert_lines.append(f'⏰ 의견등록 마감 D-{days_left}: {name}')
            stage = 2
            d3_count += 1
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

    note = f'notices active={len(notices)} rel={len(relevant)} new={new_rows} d3={d3_count}'
    if dry_run:
        print(f'  (dry-run) heartbeat 생략: {note}')
    else:
        notice_heartbeat(note)
    print(f'[입법예고 추적] 완료 — {note}')


# ═══════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════

def main(dry_run: bool = False):
    print(f'[국회 법안 모니터링] 시작 — {datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")}'
          + (' [DRY-RUN — DB 쓰기·알림 없음]' if dry_run else ''))

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

        if dry_run:
            # DB 무변경 — 결과만 판정해서 출력
            proc = (bill.get('PROC_RESULT') or '접수').strip()
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
            new  = bill.get('PROC_RESULT', '')
            print(f'  🔄 상태변경: {bill.get("BILL_NAME", "")[:30]} ({prev} → {new})')
            # 중요 상태 변경만 알림 (접수→접수 같은 무의미한 변경 제외)
            if not dry_run and new in NOTABLE_STATUS:
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
    args = parser.parse_args()
    main(dry_run=args.dry_run)
