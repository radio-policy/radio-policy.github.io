# -*- coding: utf-8 -*-
"""
law_amendments.summary 채우기 — 법제처 DRF 상세(본문 JSON)에서 개정이유/주요내용을 받아 Haiku로 1~2문장 요약.

- DRF 본문 API는 계정에 'JSON'으로 신청돼 있으므로 type=JSON 사용. (type=XML은 "미신청" 오류)
- law/bylaw/rules → target=law&MST={일련번호}, admrul → target=admrul&ID={일련번호}
- lsAnc(입법예고)는 DRF 미지원 → 건너뜀(추후 gov_notice_crawler에서 처리)
- 멱등: summary NULL만 처리.
  · 호출 실패(연결·인증·서비스 오류) → summary NULL 그대로 둠 → 다음 실행이 재시도(잘못된 '' 저장 방지)
  · 정상 응답인데 제개정이유 내용 없음 → ''로 표시(재처리 방지)
  · Haiku 요약 실패/너무 짧음 → NULL 유지(재시도)
- 필요 env: SUPABASE_URL, SUPABASE_SERVICE_KEY, LAW_OC_KEY, ANTHROPIC_API_KEY
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
LAW_OC_KEY        = os.environ.get('LAW_OC_KEY', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
MAX_ROWS          = int(os.environ.get('SUMMARIZE_MAX', '1000'))

sb: Client = make_client(SUPABASE_URL, SUPABASE_KEY)
DRF_SERVICE = 'http://www.law.go.kr/DRF/lawService.do'


def detail_params(law_id: str):
    if not law_id or '_' not in law_id:
        return None
    typ = law_id.split('_', 1)[0]
    seq = law_id.split('_', 1)[1]
    if typ == 'admrul':
        return {'target': 'admrul', 'ID': seq}
    if typ in ('law', 'bylaw', 'rules'):
        return {'target': 'law', 'MST': seq}
    return None  # lsAnc 등


def _find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _find_key(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_key(v, key)
            if r is not None:
                return r
    return None


def _flatten(x):
    if x is None:
        return []
    if isinstance(x, str):
        return [x]
    if isinstance(x, list):
        out = []
        for i in x:
            out += _flatten(i)
        return out
    return [str(x)]


def fetch_reason(params: dict):
    """반환: 본문(str) / '' (정상응답·내용없음) / None (호출실패 → NULL 유지·재시도)."""
    q = {'OC': LAW_OC_KEY, 'type': 'JSON'}
    q.update(params)
    try:
        resp = requests.get(DRF_SERVICE, params=q, timeout=8)
        data = resp.json()
    except Exception as e:
        print(f'  [DRF 오류] {params}: {str(e)[:80]}')
        return None
    # 정상 응답인지 확인(법령/행정규칙 객체). 아니면 인증·오류 응답 → 실패로 간주
    if not (isinstance(data.get('법령'), dict) or isinstance(data.get('AdmRulService'), dict)):
        print(f'  [응답 오류] {params}: {str(data)[:80]}')
        return None
    content = _find_key(data, '제개정이유내용')
    parts = _flatten(content)
    text = ' '.join(p.strip() for p in parts if p and p.strip())
    text = re.sub(r'\[\s*(제정|일부개정|전부개정|타법개정|폐지|타법폐지)\s*\]', ' ', text)
    text = text.replace('◇', ' ').replace('<법제처 제공>', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text  # '' 가능(정상응답·내용없음)


def _clean(s: str) -> str:
    return re.sub(r'^[#\-*◇\s]+', '', s or '').strip()


def summarize(law_nm: str, reason: str) -> str:
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
                    f'다음은 「{law_nm}」의 개정이유·주요내용입니다. '
                    '무엇을 바꾸려는지 핵심만 1~2문장(100자 이내) 한국어 평서문으로 요약하세요. '
                    '제목·머리기호 없이 문장만 출력.\n\n'
                    + reason[:2000]
                ),
            }],
        )
        out = _clean(resp.content[0].text)
        return out if len(out) >= 6 else ''
    except Exception as e:
        print(f'  [요약 오류] {e}')
        return ''


def main():
    rows = (sb.table('law_amendments')
            .select('id,law_id,law_nm,summary')
            .is_('summary', 'null')
            .limit(MAX_ROWS)
            .execute().data) or []
    print(f'[요약] summary NULL 대상: {len(rows)}건 (MAX={MAX_ROWS})')

    done = 0
    empty = 0
    failed = 0
    skipped = 0
    for r in rows:
        params = detail_params(r.get('law_id') or '')
        if not params:
            skipped += 1   # lsAnc 등 — NULL 유지
            continue
        reason = fetch_reason(params)
        if reason is None:
            failed += 1    # 호출 실패 → NULL 유지(재시도)
            time.sleep(0.3)
            continue
        if reason == '':
            sb.table('law_amendments').update({'summary': ''}).eq('id', r['id']).execute()
            empty += 1
            time.sleep(0.1)
            continue
        s = summarize(r.get('law_nm', ''), reason)
        if not s:
            failed += 1    # 요약 실패 → NULL 유지(재시도)
            time.sleep(0.2)
            continue
        sb.table('law_amendments').update({'summary': s}).eq('id', r['id']).execute()
        done += 1
        print(f'  ok {(r.get("law_nm") or "")[:30]} -> {s[:50]}')
        time.sleep(0.15)

    print(f'[요약] 완료 - 요약 {done} / 내용없음 {empty} / 실패(NULL유지) {failed} / 건너뜀 {skipped}')


if __name__ == '__main__':
    main()
