#!/usr/bin/env python3
"""
법제처 국가법령정보 DRF Open API 기반 법령·고시 변경 모니터링
- 현행 법령(법률·시행령·시행규칙) 개정 감지 → 텔레그램 알림
- 시행예정 법령(eflaw) 감지 → 시행 예정 추적
- 행정규칙(고시) 개정 감지 → 텔레그램 알림
※ 입법예고는 gov_notice_crawler.py(opinion.lawmaking.go.kr)가 담당
  (law.go.kr DRF는 lsAnc 미지원)

GitHub Actions에서 매일 11:00 KST 실행 (law_crawl.yml)
법제처 OC키: https://open.law.go.kr → 마이페이지 → API인증키관리
"""

import os
import sys
import time
import requests
from urllib.parse import quote
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
import notify   # 텔레그램 전송 공용 유틸 (개선⑪) — 전송부만 위임

# ── 환경변수 ──────────────────────────────────────────────
SUPABASE_URL       = os.environ['SUPABASE_URL']
SUPABASE_KEY       = os.environ['SUPABASE_SERVICE_KEY']
LAW_OC_KEY         = os.environ.get('LAW_OC_KEY', '')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID', '')

sb: Client = make_client(SUPABASE_URL, SUPABASE_KEY)
KST = timezone(timedelta(hours=9))

# ── API 설정 ──────────────────────────────────────────────
LAW_API_BASE = 'http://www.law.go.kr/DRF/lawSearch.do'

# 내부 law_type → 화면 라벨 (대시보드 lawTrackTypeLabel과 일치)
TYPE_LABEL = {
    'law':    '법률',
    'bylaw':  '시행령',
    'rules':  '시행규칙',
    'admrul': '고시',
}

# 법령 조회 target: 현행(law) + 시행예정(eflaw)
LAW_SEARCH_TARGETS = ['law', 'eflaw']

# 모니터링 키워드
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
    '이동통신',
    '위성통신',
    '기간통신',
    '전파관리',
    '전파간섭',
]


def law_type_from_gubun(gubun: str) -> str:
    """법령구분명 → 내부 law_type"""
    g = (gubun or '').strip()
    if '대통령령' in g:
        return 'bylaw'        # 시행령
    if '총리령' in g or '부령' in g:
        return 'rules'        # 시행규칙
    if '법률' in g:
        return 'law'          # 법률 본법
    return 'law'              # 기타(국회규칙 등)는 법률로 분류


# ══════════════════════════════════════════════════════════
#  API 조회
# ══════════════════════════════════════════════════════════

def _api_get_with_retry(params: dict, timeout: int = 10,
                        max_retry: int = 3, delay: int = 5):
    """법제처 API 호출 + 일시 오류 재시도 — 하루 1회 잡이라 1회 실패가
    하루치 누락으로 직결되는 것을 방지 (gov_notice_crawler와 동일 정책, 배경역사 #23)"""
    for attempt in range(1, max_retry + 1):
        try:
            resp = requests.get(LAW_API_BASE, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt < max_retry:
                print(f'  [재시도 {attempt}/{max_retry}] {e}')
                time.sleep(delay)
            else:
                raise


def fetch_laws(keyword: str, target: str, display: int = 20) -> list:
    """법제처 DRF API로 법령 목록 조회 (target=law 현행 / eflaw 시행예정)"""
    if not LAW_OC_KEY:
        return []
    params = {
        'OC': LAW_OC_KEY, 'target': target, 'type': 'JSON',
        'query': keyword, 'display': display, 'page': 1, 'sort': 'ddes',
    }
    try:
        resp = _api_get_with_retry(params, timeout=10)
        data = resp.json()
        items = data.get('LawSearch', {}).get('law', [])
        if isinstance(items, dict):
            items = [items]
        return items if isinstance(items, list) else []
    except Exception as e:
        print(f'  [API 오류] {target}/{keyword}: {e}')
        return []


def fetch_admrul(keyword: str, display: int = 20) -> list:
    """행정규칙(고시·훈령·예규) 목록 조회"""
    if not LAW_OC_KEY:
        return []
    params = {
        'OC': LAW_OC_KEY, 'target': 'admrul', 'type': 'JSON',
        'query': keyword, 'display': display, 'page': 1,
    }
    try:
        resp = _api_get_with_retry(params, timeout=10)
        data = resp.json()
        items = data.get('AdmRulSearch', {}).get('admrul', [])
        if isinstance(items, dict):
            items = [items]
        return items if isinstance(items, list) else []
    except Exception as e:
        print(f'  [고시 API 오류] {keyword}: {e}')
        return []


# ══════════════════════════════════════════════════════════
#  DB 처리
# ══════════════════════════════════════════════════════════

def load_existing() -> dict:
    """DB의 기존 법령 목록 로드 (law_id → row)"""
    rows = sb.table('law_amendments').select('*').execute().data
    return {r['law_id']: r for r in rows}


def item_name(item: dict) -> str:
    return (item.get('법령명한글') or item.get('행정규칙명') or '').strip()


def item_mst(item: dict) -> str:
    return str(item.get('법령일련번호') or item.get('행정규칙일련번호') or '').strip()


def make_law_id(item: dict, law_type: str) -> str:
    """법령 고유 ID 생성 (유형 + 일련번호)"""
    return f"{law_type}_{item_mst(item)}"


def build_link(item: dict, law_type: str) -> str:
    """사용자용 법령/고시 검색 링크 (OC키 노출 방지로 이름 검색 링크 사용)"""
    nm = item_name(item)
    if not nm:
        return ''
    if law_type == 'admrul':
        return f'https://www.law.go.kr/admRulSc.do?menuId=1&query={quote(nm)}'
    return f'https://www.law.go.kr/lsSc.do?menuId=1&query={quote(nm)}'


def upsert_law(item: dict, law_type: str, keywords: list,
               existing: dict) -> str:
    """법령 저장/갱신. 반환값: 'new' | 'updated' | 'unchanged'"""
    law_id = make_law_id(item, law_type)
    law_nm = item_name(item)
    public_dt = str(item.get('공포일자') or item.get('발령일자') or '').replace('-', '').strip()
    enf_dt    = str(item.get('시행일자') or '').replace('-', '').strip()
    public_no = str(item.get('공포번호') or item.get('발령번호') or '').strip()
    ann_type  = str(item.get('제개정구분명') or '').strip()
    link_url  = build_link(item, law_type)

    if not item_mst(item) or not law_nm:
        return 'unchanged'

    row = {
        'law_id':           law_id,
        'law_nm':           law_nm,
        'law_type':         law_type,
        'ann_type':         ann_type,
        'public_dt':        public_dt,
        'enf_dt':           enf_dt,
        'public_no':        public_no,
        'matched_keywords': keywords,
        'link_url':         link_url,
        'updated_at':       datetime.now(KST).isoformat(),
    }

    if existing is None:
        row['prev_public_dt'] = public_dt
        sb.table('law_amendments').insert(row).execute()
        return 'new'

    # 공포일 변경 감지 (재개정)
    if existing.get('public_dt') != public_dt and public_dt:
        row['prev_public_dt'] = existing.get('public_dt', '')
        sb.table('law_amendments').update(row).eq('law_id', law_id).execute()
        return 'updated'

    # 키워드 병합만
    existing_kw = set(existing.get('matched_keywords') or [])
    new_kw = set(keywords)
    if not new_kw.issubset(existing_kw):
        sb.table('law_amendments').update({
            'matched_keywords': list(existing_kw | new_kw),
            'updated_at': datetime.now(KST).isoformat(),
        }).eq('law_id', law_id).execute()

    return 'unchanged'


# ══════════════════════════════════════════════════════════
#  텔레그램 알림
# ══════════════════════════════════════════════════════════

def fmt_date(dt: str) -> str:
    if dt and len(dt) == 8:
        return f'{dt[:4]}.{dt[4:6]}.{dt[6:]}'
    return dt or '—'


def send_telegram(msg: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    # 전송부는 notify 위임 (개선⑪) — 실패 로그는 notify가 출력
    notify.send_telegram(msg, chat_id=TELEGRAM_CHAT_ID, parse_mode='HTML')


def notify_new(item: dict, law_type: str, keywords: list):
    label = TYPE_LABEL.get(law_type, law_type)
    law_nm = item_name(item)
    public_dt = str(item.get('공포일자') or item.get('발령일자') or '').replace('-', '')
    enf_dt = str(item.get('시행일자') or '').replace('-', '')
    ann_type = item.get('제개정구분명') or ''
    msg = (
        f'⚖️ <b>[{label} 신규]</b>\n'
        f'{law_nm}\n\n'
        f'• 구분: {ann_type or "—"}\n'
        f'• 공포일: {fmt_date(public_dt)}\n'
        f'• 시행일: {fmt_date(enf_dt)}\n'
        f'• 키워드: {", ".join(keywords)}'
    )
    send_telegram(msg)


def notify_updated(item: dict, law_type: str, prev_dt: str, keywords: list):
    label = TYPE_LABEL.get(law_type, law_type)
    law_nm = item_name(item)
    public_dt = str(item.get('공포일자') or item.get('발령일자') or '').replace('-', '')
    msg = (
        f'🔄 <b>[{label} 재개정]</b>\n'
        f'{law_nm}\n\n'
        f'• {fmt_date(prev_dt)} → <b>{fmt_date(public_dt)}</b>\n'
        f'• 키워드: {", ".join(keywords)}'
    )
    send_telegram(msg)


# ══════════════════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════════════════

def main():
    print(f'[법령 모니터링] 시작 — {datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")}')

    if not LAW_OC_KEY:
        print('[오류] LAW_OC_KEY 환경변수 없음')
        return

    existing = load_existing()
    is_baseline = len(existing) == 0   # 첫 실행이면 알림 폭주 방지(저장만)
    print(f'  기존 추적 법령: {len(existing)}건' + ('  (첫 실행 — 알림 생략, 베이스라인 저장)' if is_baseline else ''))

    collected = {}   # law_id → [item, law_type, keywords]

    # ① 법령 (현행 law + 시행예정 eflaw) — law_type은 법령구분명으로 판정
    for target in LAW_SEARCH_TARGETS:
        print(f'\n  [법령:{target}] 검색 중...')
        for kw in KEYWORDS:
            for item in fetch_laws(kw, target, display=20):
                lt = law_type_from_gubun(item.get('법령구분명'))
                lid = make_law_id(item, lt)
                if not item_mst(item):
                    continue
                if lid in collected:
                    if kw not in collected[lid][2]:
                        collected[lid][2].append(kw)
                else:
                    collected[lid] = [item, lt, [kw]]
            time.sleep(0.15)

    # ② 고시·행정규칙
    print(f'\n  [고시·행정규칙] 검색 중...')
    for kw in KEYWORDS:
        for item in fetch_admrul(kw, display=20):
            lid = make_law_id(item, 'admrul')
            if not item_mst(item):
                continue
            if lid in collected:
                if kw not in collected[lid][2]:
                    collected[lid][2].append(kw)
            else:
                collected[lid] = [item, 'admrul', [kw]]
        time.sleep(0.15)

    print(f'\n  총 고유 법령·고시: {len(collected)}건')

    new_count = 0
    updated_count = 0

    for lid, (item, law_type, keywords) in collected.items():
        ex = existing.get(lid)
        result = upsert_law(item, law_type, keywords, ex)

        if result == 'new':
            new_count += 1
            label = TYPE_LABEL.get(law_type, law_type)
            print(f'  🆕 신규 {label}: {item_name(item)[:40]}')
            if not is_baseline:
                notify_new(item, law_type, keywords)

        elif result == 'updated':
            updated_count += 1
            prev_dt = ex.get('public_dt', '') if ex else ''
            new_dt = str(item.get('공포일자') or item.get('발령일자') or '').replace('-', '')
            print(f'  🔄 개정: {item_name(item)[:30]} ({fmt_date(prev_dt)} → {fmt_date(new_dt)})')
            if not is_baseline:
                notify_updated(item, law_type, prev_dt, keywords)

    print(f'\n[완료] 신규 {new_count}건 | 개정 {updated_count}건 | 총 추적 {len(collected)}건'
          + ('  (첫 실행 — 텔레그램 생략)' if is_baseline else ''))


if __name__ == '__main__':
    main()
