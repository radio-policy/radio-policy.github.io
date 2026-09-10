# -*- coding: utf-8 -*-
"""
assembly_bills.summary 채우기 — 열린국회정보 BPMBILLSUMMARY(법률안 제안이유 및 주요내용)에서
SUMMARY를 받아 Haiku로 1~2문장 요약.

이중화 설계(자동 복구):
- summary NULL만 처리(멱등). 어느 실행기(로컬 스케줄러/Actions)가 돌든 NULL 대기열을 줄여감.
- 호출 실패(연결 거부·인증 오류 등) → summary는 NULL 그대로 둠 → 다음 실행이 재시도.
- 응답은 정상인데 제안이유 내용이 없음 → ''로 표시(재처리 방지).
- Haiku 요약 실패 → NULL 유지(재시도).
- SUMMARIZE_MAX 환경변수로 1회 처리량 제한(Actions 안전; 기본 1000=로컬 전체).

필요 env: SUPABASE_URL, SUPABASE_SERVICE_KEY, ASSEMBLY_API_KEY, ANTHROPIC_API_KEY
"""
import os
import re
import time

import requests
import anthropic
from supabase import Client
from sb_client import make_client
import api_usage; api_usage.install()   # Anthropic usage 기록(#152) — 호출부 무변경, fail-open

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SUPABASE_URL      = os.environ['SUPABASE_URL']
SUPABASE_KEY      = os.environ['SUPABASE_SERVICE_KEY']
ASSEMBLY_API_KEY  = os.environ.get('ASSEMBLY_API_KEY', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
MAX_ROWS          = int(os.environ.get('SUMMARIZE_MAX', '1000'))

sb: Client = make_client(SUPABASE_URL, SUPABASE_KEY)
API = 'https://open.assembly.go.kr/portal/openapi/BPMBILLSUMMARY'


def fetch_summary(bill_no: str):
    """반환: 본문(str) / '' (정상응답·내용없음) / None (호출실패 → NULL 유지·재시도)."""
    if not (ASSEMBLY_API_KEY and bill_no):
        return None
    params = {'KEY': ASSEMBLY_API_KEY, 'Type': 'json', 'pIndex': 1, 'pSize': 5, 'BILL_NO': bill_no}
    try:
        resp = requests.get(API, params=params, timeout=8)
        data = resp.json()
    except Exception as e:
        print(f'  [API 오류] {bill_no}: {str(e)[:80]}')
        return None
    wrap = data.get('BPMBILLSUMMARY')
    if not isinstance(wrap, list):
        # 인증·서비스 오류 응답(RESULT 등) → 호출 실패로 간주
        print(f'  [응답 오류] {bill_no}: {str(data)[:80]}')
        return None
    rows = []
    for it in wrap:
        if isinstance(it, dict) and 'row' in it:
            rows = it['row']
            break
    if not rows:
        return ''  # 정상 응답인데 내용 없음
    s = (rows[0].get('SUMMARY') or '').strip()
    return re.sub(r'\s+', ' ', s).strip()


def _clean(s: str) -> str:
    s = re.sub(r'^[#\-*◇\s]+', '', s or '').strip()
    return s


def summarize(bill_name: str, text: str) -> str:
    if not ANTHROPIC_API_KEY:
        print('  [경고] ANTHROPIC_API_KEY 없음 — 요약 생략')
        return ''
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=200,
            messages=[{
                'role': 'user',
                'content': (
                    f'다음은 「{bill_name}」의 제안이유·주요내용입니다. '
                    '무엇을 바꾸려는지 핵심만 1~2문장(100자 이내) 한국어 평서문으로 요약하세요. '
                    '제목·머리기호 없이 문장만 출력.\n\n'
                    + text[:2500]
                ),
            }],
        )
        out = _clean(resp.content[0].text)
        return out if len(out) >= 6 else ''
    except Exception as e:
        print(f'  [요약 오류] {e}')
        return ''


def main():
    rows = (sb.table('assembly_bills')
            .select('id,bill_no,bill_name,summary')
            .is_('summary', 'null')
            .limit(MAX_ROWS)
            .execute().data) or []
    print(f'[국회요약] summary NULL 대상: {len(rows)}건 (MAX={MAX_ROWS})')

    done = 0
    empty = 0
    failed = 0
    for r in rows:
        txt = fetch_summary(r.get('bill_no') or '')
        if txt is None:
            failed += 1   # NULL 유지 → 다음 실행이 재시도
            time.sleep(0.3)
            continue
        if txt == '':
            sb.table('assembly_bills').update({'summary': ''}).eq('id', r['id']).execute()
            empty += 1
            time.sleep(0.1)
            continue
        s = summarize(r.get('bill_name', ''), txt)
        if not s:
            failed += 1   # 요약 실패 → NULL 유지(재시도)
            time.sleep(0.2)
            continue
        sb.table('assembly_bills').update({'summary': s}).eq('id', r['id']).execute()
        done += 1
        print(f'  ok {(r.get("bill_name") or "")[:30]} -> {s[:50]}')
        time.sleep(0.15)

    print(f'[국회요약] 완료 - 요약 {done} / 내용없음 {empty} / 실패(NULL유지) {failed}')


if __name__ == '__main__':
    main()
