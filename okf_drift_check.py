# -*- coding: utf-8 -*-
"""
OKF 요약(kb_documents) ↔ 조문(document_chunks 현행본) 판 어긋남 점검 (2026-09-24 신설, #197).

왜 있나: 11:00 체인의 `law_sync.py --all-outdated`·`--promote`가 조문을 새 판으로 바꿔도
OKF 요약은 따라오지 않는다(요약은 세션이 쓴다 — 지침 §법령 개정 시 OKF 요약 갱신 절차).
그 사이 자문은 새 조문 + 옛 요약을 함께 근거로 쓴다. 이 어긋남은 아무 표에도 기록되지 않아
2026-09-01(#116)·2026-09-22(#183) 두 번 다 사람이 며칠 뒤에야 발견했다. 이 스크립트가
매일 체인 끝에서 대조해 **새로 생긴 어긋남만** 운영자에게 알린다(같은 목록 반복 알림 금지 —
#183 ⑤의 '끝나지 않는 항목' 교훈).

판정: kb_documents(status='current', law_number·enforcement_date 있음)를 law_watch(현행 감시 행)와
법령명 + 소관(문서명 괄호 토큰)으로 짝지어, 시행일 또는 호수가 다르면 어긋남.
  - 시행일이 오늘보다 뒤인 요약(시행예정본 OKF)은 제외 — 구본과 나란히 두는 관례.
  - 같은 제목이 기관별로 따로 있는 고시(적합성평가 고시: 과기정통부·전파연구원)는 소관이 같은
    행과만 짝짓는다. 소관이 다른 행뿐이면 '대조 불가'로 두고 알리지 않는다.
  - 호수는 '제00156호'='제156호'처럼 앞자리 0을 무시한다(kb는 사람이 적은 번호, law_watch는 API 번호).

사용:
  python okf_drift_check.py --dry-run     # 목록만 출력(DB 무변경·알림 없음)
  python okf_drift_check.py --notify      # 어긋남 집합이 지난 알림과 다를 때만 텔레그램(운영자 봇)
  python okf_drift_check.py --json        # 세션 작업용 JSON 출력
필요 .env: SUPABASE_URL, SUPABASE_SERVICE_KEY (+ 알림 시 TELEGRAM_BOT_TOKEN/CHAT_ID). AI 0회.
"""

import os
import re
import sys
import json
import hashlib
import argparse
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

KST = timezone(timedelta(hours=9))
HEALTH_KEY = 'okf_drift'          # system_health: note='drift=N sig=XXXXXXXX' (알림 중복 억제용)

# 기관 개편으로 이름이 바뀐 소관 — kb(사람이 적음)와 law_watch(API 문서명)가 다른 이름을 쓸 수 있다
_AGENCY_ALIAS = {
    '방송통신위원회': '방송미디어통신위원회',
    '과기정통부': '과학기술정보통신부',
}

_DOC_RE = re.compile(r'^(?P<name>.+?)\((?P<agency>[^()]+)\)\((?P<no>제[^()]*호)\)\((?P<enf>\d{8})\)\s*$')


def norm_title(title: str) -> str:
    """kb 제목 → 대조 키. 꼬리의 '[시행예정 …]'·'(… 제N호)'를 떼고 공백·가운뎃점 이형을 지운다."""
    t = title or ''
    t = re.sub(r'\s*\[시행예정[^\]]*\]\s*$', '', t)
    t = re.sub(r'\s*\([^()]*호\)\s*$', '', t)
    t = t.replace('ㆍ', '·').replace('‧', '·').replace('•', '·')
    return re.sub(r'\s+', '', t).strip()


def norm_agency(agency: str) -> str:
    a = re.sub(r'\s+', '', agency or '')
    for k, v in _AGENCY_ALIAS.items():
        a = a.replace(k, v)
    return a


def norm_no(no: str) -> str:
    """'제00156호'·'제156호' → '156', '제2026-4호' → '2026-4'. 비교 전용."""
    s = re.sub(r'[^0-9\-]', '', no or '')
    return '-'.join(p.lstrip('0') or '0' for p in s.split('-') if p != '')


def norm_date(d: str) -> str:
    return re.sub(r'[^0-9]', '', d or '')[:8]


def parse_watch_doc(doc_name: str):
    m = _DOC_RE.match(doc_name or '')
    if not m:
        return None
    return {'name': norm_title(m.group('name')), 'agency': norm_agency(m.group('agency')),
            'no': m.group('no'), 'enf': m.group('enf')}


def find_drift(kb_rows, watch_rows, today: str = None):
    """kb_rows: [{title, law_type, law_number, enforcement_date, path}], watch_rows: [{doc_name, law_name}]
    → 어긋남 목록(제목 순). 짝을 못 찾은 kb 문서는 결과에 넣지 않는다(대조 불가 ≠ 어긋남)."""
    today = today or datetime.now(KST).strftime('%Y%m%d')
    by_name = {}
    for w in watch_rows or []:
        p = parse_watch_doc(w.get('doc_name') or '')
        if not p:
            continue
        p['doc_name'] = w['doc_name']
        by_name.setdefault(p['name'], []).append(p)

    out = []
    for k in kb_rows or []:
        if not (k.get('law_number') and k.get('enforcement_date')):
            continue
        kb_enf = norm_date(k['enforcement_date'])
        if not kb_enf or kb_enf > today:
            continue                       # 시행예정본 요약 — 구본과 나란히 두는 관례
        cands = by_name.get(norm_title(k.get('title')))
        if not cands:
            continue
        ag = norm_agency(k.get('law_type') or '')
        same = [c for c in cands if not ag or c['agency'] == ag]
        if not same:
            continue                       # 같은 제목·다른 소관(적합성평가 고시류) — 대조 불가
        cur = max(same, key=lambda c: c['enf'])
        if cur['enf'] == kb_enf and norm_no(cur['no']) == norm_no(k['law_number']):
            continue
        out.append({
            'title': re.sub(r'\s*\[시행예정[^\]]*\]\s*$', '', k.get('title') or ''),
            'kb_no': k['law_number'], 'kb_enf': kb_enf,
            'cur_no': cur['no'], 'cur_enf': cur['enf'],
            'path': k.get('path'), 'doc_name': cur['doc_name'],
        })
    out.sort(key=lambda r: (r['cur_enf'], r['title']), reverse=True)
    return out


def drift_signature(drift) -> str:
    key = '|'.join(f"{r['path']}>{r['cur_no']}" for r in drift)
    return hashlib.sha1(key.encode('utf-8')).hexdigest()[:8]


def format_drift_lines(drift, limit=12):
    lines = []
    for r in drift[:limit]:
        lines.append(f"· {r['title']}: 요약 {r['kb_no']}({r['kb_enf']}) → 조문 <b>{r['cur_no']}</b>({r['cur_enf']})")
    if len(drift) > limit:
        lines.append(f"  … 외 {len(drift) - limit}건")
    return lines


def format_message(drift) -> str:
    now = datetime.now(KST).strftime('%m/%d %H:%M')
    if not drift:
        return f"✅ <b>OKF 요약 어긋남 해소</b> ({now}) — 요약과 조문 판이 모두 일치"
    lines = [f"📝 <b>OKF 요약 갱신 필요 {len(drift)}건</b> ({now}) — 조문은 새 판, 요약은 옛 판", ""]
    lines += format_drift_lines(drift)
    lines += ["", "<i>처리: 세션에서 새 판 조문 기준으로 요약 재작성 → manifest → import_regulatory_kb.py --only "
              "(지침 §법령 개정 시 OKF 요약 갱신 절차). API로 만들지 않는다.</i>"]
    return "\n".join(lines)


# ── DB 접근 ────────────────────────────────────────────────

def fetch_rows(sb):
    kb, start = [], 0
    while True:
        r = (sb.table('kb_documents').select('title, law_type, law_number, enforcement_date, path')
             .eq('status', 'current').order('id').range(start, start + 999).execute())
        kb.extend(r.data or [])
        if len(r.data or []) < 1000:
            break
        start += 1000
    watch = (sb.table('law_watch').select('doc_name, law_name')
             .eq('sync_status', 'current').eq('watch_status', 'watching').execute().data) or []
    return kb, watch


def run_check(sb):
    """(drift, kb_count, watch_count) — law_sync 완료 알림이 같은 결과를 붙여 쓴다. 조회 실패는 예외 그대로."""
    kb, watch = fetch_rows(sb)
    return find_drift(kb, watch), len(kb), len(watch)


def _last_signature(sb):
    try:
        r = sb.table('system_health').select('note').eq('key', HEALTH_KEY).maybe_single().execute()
        note = (getattr(r, 'data', None) or {}).get('note') or ''
        m = re.search(r'sig=([0-9a-f]{8})', note)
        return m.group(1) if m else None
    except Exception as e:
        print(f"  (이전 서명 조회 실패 — 알림 진행) {e}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='목록만 출력(DB 무변경·알림 없음)')
    ap.add_argument('--notify', action='store_true', help='어긋남 집합이 바뀌었을 때만 운영자 텔레그램')
    ap.add_argument('--json', action='store_true', help='JSON으로 출력')
    a = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    import sb_client
    url, key = os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_KEY')
    if not (url and key):
        print("오류: .env에 SUPABASE_URL, SUPABASE_SERVICE_KEY 필요")
        sys.exit(1)
    sb = sb_client.make_client(url, key)

    drift, n_kb, n_watch = run_check(sb)
    if a.json:
        print(json.dumps(drift, ensure_ascii=False, indent=1))
    else:
        print(f"kb 현행 문서 {n_kb}건 · law_watch 현행 감시 {n_watch}건 → 어긋남 {len(drift)}건")
        for r in drift:
            print(f"  - {r['title']}: 요약 {r['kb_no']}({r['kb_enf']}) → 조문 {r['cur_no']}({r['cur_enf']})")
            print(f"      {r['path']}")
    if a.dry_run or not a.notify:
        return

    sig = drift_signature(drift)
    prev = _last_signature(sb)
    if prev == sig:
        print(f"  집합 변화 없음(sig={sig}) — 알림 생략")
    elif prev is None and not drift:
        print("  첫 실행·어긋남 없음 — 알림 생략")
    else:
        import notify as tg_notify
        ok = tg_notify.send_telegram(format_message(drift), parse_mode='HTML',
                                     disable_web_page_preview=True)
        print("  알림 발송" if ok else "  ! 알림 실패(다음 실행에 재시도)")
        if not ok:
            return                          # 서명을 남기지 않아 다음 실행이 다시 보낸다
    sb_client.heartbeat(sb, HEALTH_KEY, f'drift={len(drift)} sig={sig}')


if __name__ == '__main__':
    main()
