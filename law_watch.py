"""
지식베이스 법령 현행화 감시 (Phase 1) — 등재본 vs 법제처 현행본 대조.

동작(멱등, 읽기 위주):
  ① document_chunks의 법령·고시 문서명을 매 실행마다 새로 스캔 → 감시 대상 자동 발견
     (대시보드 업로드/add_law.py/세션 어느 경로로 추가하든 다음 실행부터 자동 편입)
  ② 문서명에서 법령명·법종·법령번호·시행일 파싱 → 법제처 DRF API로 현행본 조회
  ③ 등재본 ≠ 현행본이면 law_watch.sync_status='outdated' + 텔레그램 알림
  ④ eflaw(시행일법령)로 시행예정본도 기록(Phase 3 대비 — 저장만, 자문 노출 안 함)

법제처에 없는 문서(ITU-R·보도자료·사내자료)는 watch_status='unmatched'로 1회만 알리고,
운영자가 'excluded'로 표시하면 이후 조용히 건너뛴다(알림 노이즈 방지).

사용법:
  python law_watch.py                 # 전체 점검 + 알림
  python law_watch.py --dry-run       # DB 기록·알림 없이 결과만 출력
  python law_watch.py --no-notify     # DB는 갱신하되 알림 생략(초기 전수 점검용)
  python law_watch.py --limit 20      # 앞 N건만(디버깅)

필요 .env: SUPABASE_URL, SUPABASE_SERVICE_KEY, LAW_OC_KEY, (알림 시) TELEGRAM_BOT_TOKEN/CHAT_ID
"""

import os
import re
import sys
import time
import argparse
from datetime import datetime, timezone, timedelta

# cp949 콘솔·파이프에서 이모지 print 크래시 방지 (지침 가드레일 #19)
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

import sb_client

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SERVICE_KEY")
OC_KEY = os.getenv("LAW_OC_KEY")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID")

DRF_SEARCH = "https://www.law.go.kr/DRF/lawSearch.do"
KST = timezone(timedelta(hours=9))

# 문서명 관례: "전파법(법률)(제21065호)(20260102).pdf"
TYPE_PAREN_RE = re.compile(r'\(([^()]*?(법률|대통령령|총리령|부령|고시|훈령|공고|예규|위원회규칙|연구원규칙))\)')
NO_PAREN_RE = re.compile(r'\((제[^()]*?호)\)')
DATE_PAREN_RE = re.compile(r'\((\d{8})\)')

# 법제처에 없는(감시 불가) 카테고리 — 애초에 스캔 대상에서 제외
SKIP_CATEGORIES = {"ITU-R", "보도자료", "추가지식"}


def norm_name(name: str) -> str:
    """가운뎃점 이형 통일 + 공백 정리 (build_law_citation_graph와 동일 규칙)"""
    name = name.replace('ㆍ', '·').replace('‧', '·').replace('•', '·')
    return re.sub(r'\s+', ' ', name).strip()


def parse_doc_name(doc_name: str):
    """doc_name → dict(law_name, full_name, law_type_token, law_no, enf_date) 또는 None

    법제처 행정규칙명은 '(과학기술정보통신부) 방송통신발전기금 운용·관리규정'처럼
    소관부처 접두를 포함하므로, 접두를 뗀 law_name과 붙인 full_name을 모두 보존한다.
    (같은 규정이 부처 이관으로 2건 존재하는 경우 접두까지 맞춰야 올바른 쪽과 대조됨)
    """
    name = re.sub(r'\.(pdf|md|txt|docx)$', '', norm_name(doc_name), flags=re.I)
    m = TYPE_PAREN_RE.search(name)
    if not m:
        return None
    head = name[:m.start()].strip()
    head = re.sub(r'^\[[^\]]*\]\s*', '', head).strip()   # 선두 [별첨 N] 제거
    base = re.sub(r'^\([^)]*\)\s*', '', head).strip()    # 선두 소관부처 괄호 제거
    if len(base) < 2:
        return None
    tail = name[m.end():]
    no_m = NO_PAREN_RE.search(tail)
    dt_m = DATE_PAREN_RE.search(tail)
    return {
        "law_name": base,        # 접두 제거본 (검색어)
        "full_name": head,       # 접두 포함본 (정밀 매칭용)
        "law_type_token": m.group(2),
        "law_no": no_m.group(1) if no_m else None,
        "enf_date": dt_m.group(1) if dt_m else None,
    }


# 정부조직 개편 등으로 기관명이 바뀌면 법령·규칙 명칭 자체가 바뀐다.
# 예: '전파법 시행에 관한 방송통신위원회 규칙' → '… 방송미디어통신위원회 규칙' (2025.10 개편)
# 1차 검색이 실패하면 아래 별칭으로 치환해 재검색한다.
ORG_ALIASES = {
    '방송통신위원회': '방송미디어통신위원회',
    '미래창조과학부': '과학기술정보통신부',
    '산업통상자원부': '산업통상부',
    '기획재정부': '재정경제부',
}


def alias_variants(name: str):
    """기관명 별칭을 적용한 검색어 후보(원본 제외)"""
    out = []
    for old, new in ORG_ALIASES.items():
        if old in name:
            out.append(name.replace(old, new))
    return out


def api_target_of(type_token: str) -> str:
    """법종 → 법제처 DRF target (법률/대통령령/부령=law, 고시·훈령·예규·공고=admrul)"""
    if type_token in ('법률', '대통령령', '총리령') or type_token.endswith('부령'):
        return 'law'
    return 'admrul'


def fetch_all_doc_rows(sb):
    """document_chunks의 (doc_name, doc_category) 전체 — PostgREST 1000행 절단 회피(지침 가드레일)"""
    seen, start, page = {}, 0, 1000
    while True:
        r = (sb.table('document_chunks')
             .select('doc_name, doc_category')
             .order('id').range(start, start + page - 1).execute())
        rows = r.data or []
        for row in rows:
            seen.setdefault(row['doc_name'], row.get('doc_category'))
        if len(rows) < page:
            return seen
        start += page


def drf_law_search(query: str, target: str, ef: bool = False):
    """법제처 검색 → 결과 리스트(dict). ef=True면 시행일법령(eflaw)."""
    params = {'OC': OC_KEY, 'target': 'eflaw' if ef else target,
              'type': 'JSON', 'query': query, 'display': 20}
    for attempt in range(3):
        try:
            r = requests.get(DRF_SEARCH, params=params, timeout=30)
            r.raise_for_status()
            d = r.json()
            key = 'LawSearch' if 'LawSearch' in d else list(d.keys())[0]
            rows = d.get(key, {}).get('law') or d.get(key, {}).get('admrul') or []
            if isinstance(rows, dict):
                rows = [rows]
            return rows
        except Exception as e:
            if attempt == 2:
                print(f"    ! API 조회 실패({query}/{target}): {str(e)[:80]}")
                return None
            time.sleep(2 * (attempt + 1))
    return None


def _key(s: str) -> str:
    """비교용 정규화: 가운뎃점 통일 + 공백 제거"""
    return norm_name(s or '').replace(' ', '')


def _strip_org(s: str) -> str:
    """선두 소관부처 괄호 제거: '(과기정통부) 규정' → '규정'"""
    return re.sub(r'^\([^)]*\)\s*', '', norm_name(s or '')).strip()


def pick_exact(rows, law_name: str, full_name: str = None):
    """검색 결과 중 해당 법령 행 선택.
    ① 접두(소관부처) 포함 완전일치 → ② 접두 제거 후 일치 (현행 우선)
    """
    if not rows:
        return None

    def name_of(r):
        return r.get('법령명한글') or r.get('행정규칙명') or ''

    def is_current(r):
        return (r.get('현행연혁코드') or r.get('현행연혁구분') or '') == '현행'

    if full_name:
        exact = [r for r in rows if _key(name_of(r)) == _key(full_name)]
        if exact:
            return next((r for r in exact if is_current(r)), exact[0])
    loose = [r for r in rows if _key(_strip_org(name_of(r))) == _key(law_name)]
    if loose:
        return next((r for r in loose if is_current(r)), loose[0])
    return None


def row_fields(row, target: str):
    """검색 결과 행 → (mst, law_no, enf_date). 법령=공포번호, 행정규칙=발령번호"""
    if target == 'law':
        return (str(row.get('법령일련번호') or ''),
                str(row.get('공포번호') or ''),
                str(row.get('시행일자') or ''))
    return (str(row.get('행정규칙일련번호') or ''),
            str(row.get('발령번호') or ''),
            str(row.get('시행일자') or ''))


def norm_law_no(v):
    """'제21065호' / '21065' / '2023-31' → 비교용 정규화(숫자·하이픈만)"""
    if not v:
        return ''
    return re.sub(r'[^0-9\-]', '', str(v))


def notify(lines):
    if not (TG_TOKEN and TG_CHAT):
        print("  (텔레그램 미설정 — 알림 생략)")
        return
    text = "\n".join(lines)[:3900]
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      json={'chat_id': TG_CHAT, 'text': text,
                            'parse_mode': 'HTML', 'disable_web_page_preview': True},
                      timeout=20)
    except Exception as e:
        print(f"  ! 알림 실패: {str(e)[:80]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='DB 기록·알림 없이 결과만 출력')
    ap.add_argument('--no-notify', action='store_true', help='DB는 갱신하되 알림 생략')
    ap.add_argument('--limit', type=int, default=0, help='앞 N건만 점검(디버깅)')
    a = ap.parse_args()

    if not (SB_URL and SB_KEY and OC_KEY):
        print("오류: .env에 SUPABASE_URL, SUPABASE_SERVICE_KEY, LAW_OC_KEY 필요")
        sys.exit(1)

    sb = sb_client.make_client(SB_URL, SB_KEY)

    # 기존 감시 상태(제외 표시 등) 로드
    prev = {r['doc_name']: r for r in (sb.table('law_watch').select('*').execute().data or [])}

    docs = fetch_all_doc_rows(sb)
    targets = []
    for doc_name, cat in sorted(docs.items()):
        if cat in SKIP_CATEGORIES:
            continue
        if prev.get(doc_name, {}).get('watch_status') == 'excluded':
            continue                      # 운영자가 감시 제외한 문서는 조용히 건너뜀
        targets.append((doc_name, cat))
    if a.limit:
        targets = targets[:a.limit]

    print(f"=== 법령 현행화 감시 시작 ({datetime.now(KST):%Y-%m-%d %H:%M}) ===")
    print(f"지식베이스 문서 {len(docs)}건 → 감시 대상 {len(targets)}건 "
          f"(제외 카테고리·excluded 제외)\n")

    outdated, unmatched, upcoming, auto_excluded, ok = [], [], [], [], 0

    for i, (doc_name, cat) in enumerate(targets, 1):
        meta = parse_doc_name(doc_name)
        if not meta:
            # 법종 괄호가 아예 없음 = 법령 문서가 아님(보도자료·사내자료 등)
            # → 자동 제외 처리해 다음 실행부터 조용히 건너뜀 (알림 노이즈 방지)
            auto_excluded.append(doc_name)
            if not a.dry_run:
                sb.table('law_watch').upsert({
                    'doc_name': doc_name, 'watch_status': 'excluded',
                    'sync_status': 'unknown', 'note': '법령 문서명 관례 아님 — 자동 제외',
                    'last_checked_at': datetime.now(timezone.utc).isoformat(),
                    'updated_at': datetime.now(timezone.utc).isoformat(),
                }, on_conflict='doc_name').execute()
            continue

        target = api_target_of(meta['law_type_token'])
        rows = drf_law_search(meta['law_name'], target)
        hit = pick_exact(rows, meta['law_name'], meta.get('full_name'))
        # 1차 실패 시 기관명 별칭으로 재검색 (정부조직 개편으로 규칙명이 바뀐 경우)
        if not hit:
            for alt in alias_variants(meta['law_name']):
                rows = drf_law_search(alt, target)
                hit = pick_exact(rows, alt)
                if hit:
                    meta['law_name'] = alt          # 이후 단계(현행화)도 새 명칭 기준
                    meta['full_name'] = None
                    print(f"      (기관명 변경 반영 → {alt})")
                    break

        rec = {
            'doc_name': doc_name,
            'law_name': meta['law_name'],
            'law_type_token': meta['law_type_token'],
            'api_target': target,
            'registered_law_no': meta['law_no'],
            'registered_enf': meta['enf_date'],
            'last_checked_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }

        if not hit:
            unmatched.append((doc_name, f"법제처 미검색({meta['law_name']})"))
            rec.update({'watch_status': 'unmatched', 'sync_status': 'unknown',
                        'note': '법제처에서 동일 명칭 법령을 찾지 못함'})
        else:
            mst, law_no, enf = row_fields(hit, target)
            rec.update({
                'watch_status': 'watching',
                'law_id': str(hit.get('법령ID') or hit.get('행정규칙ID') or ''),
                'latest_mst': mst, 'latest_law_no': law_no, 'latest_enf': enf,
            })
            same = norm_law_no(meta['law_no']) and norm_law_no(meta['law_no']) == norm_law_no(law_no)
            if same:
                rec['sync_status'] = 'current'
                ok += 1
            else:
                rec['sync_status'] = 'outdated'
                outdated.append((doc_name, meta['law_name'], meta['law_no'], meta['enf_date'], law_no, enf))

            # 시행예정본(eflaw) — 저장만, 자문 노출은 Phase 3
            if target == 'law':
                efs = drf_law_search(meta['law_name'], 'law', ef=True) or []
                today = datetime.now(KST).strftime('%Y%m%d')
                future = [r for r in efs
                          if pick_exact([r], meta['law_name'], meta.get('full_name'))
                          and str(r.get('시행일자') or '') > today]
                if future:
                    nxt = sorted(future, key=lambda r: str(r.get('시행일자')))[0]
                    p_mst, p_no, p_enf = row_fields(nxt, 'law')
                    rec.update({'pending_mst': p_mst, 'pending_law_no': p_no, 'pending_enf': p_enf})
                    upcoming.append((meta['law_name'], p_no, p_enf))

        if not a.dry_run:
            sb.table('law_watch').upsert(rec, on_conflict='doc_name').execute()

        tag = rec.get('sync_status', '?')
        mark = {'current': 'OK', 'outdated': '구버전', 'unknown': '미매칭'}.get(tag, tag)
        print(f"  [{i}/{len(targets)}] {mark:6s} {meta['law_name'][:38]}")
        time.sleep(0.15)   # 법제처 API 예의

    # ── 요약 ──
    print(f"\n=== 결과 ===")
    print(f"  최신 상태 : {ok}건")
    print(f"  구버전    : {len(outdated)}건")
    print(f"  미매칭    : {len(unmatched)}건  (법령명은 파싱됐으나 법제처 검색 실패 — 수동 확인)")
    print(f"  자동 제외 : {len(auto_excluded)}건  (법령 문서가 아님 — 보도자료 등)")
    print(f"  시행예정본 존재: {len(upcoming)}건")

    if outdated:
        print("\n[구버전 목록]")
        for d, nm, r_no, r_enf, l_no, l_enf in outdated:
            print(f"  - {nm}: 등재 {r_no}({r_enf}) → 현행 {l_no}({l_enf})")
    if upcoming:
        print("\n[시행예정]")
        for nm, p_no, p_enf in upcoming:
            print(f"  - {nm}: {p_no} ({p_enf} 시행 예정)")
    if unmatched:
        print("\n[미매칭 — 수동 확인 필요]")
        for d, why in unmatched:
            print(f"  - {d[:60]} ({why})")

    if not a.dry_run and not a.no_notify and (outdated or upcoming):
        lines = [f"📋 <b>법령 현행화 점검</b> ({datetime.now(KST):%m/%d %H:%M})", ""]
        if outdated:
            lines.append(f"🔄 <b>개정 감지 {len(outdated)}건</b> — 대시보드에서 현행화 승인 필요")
            for d, nm, r_no, r_enf, l_no, l_enf in outdated[:10]:
                lines.append(f"· {nm}: {r_no} → <b>{l_no}</b> ({l_enf} 시행)")
            if len(outdated) > 10:
                lines.append(f"  … 외 {len(outdated) - 10}건")
            lines.append("")
        if upcoming:
            lines.append(f"📅 <b>시행예정 {len(upcoming)}건</b>")
            for nm, p_no, p_enf in upcoming[:5]:
                lines.append(f"· {nm}: {p_enf} 시행 예정")
        notify(lines)

    print("\n=== 완료 ===")


if __name__ == '__main__':
    main()
