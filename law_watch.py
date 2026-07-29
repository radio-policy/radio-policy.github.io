"""
지식베이스 법령 현행화 감시 (Phase 1) — 등재본 vs 법제처 현행본 대조.

동작(멱등, 읽기 위주):
  ① document_chunks의 법령·고시 문서명을 매 실행마다 새로 스캔 → 감시 대상 자동 발견
     (대시보드 업로드/add_law.py/세션 어느 경로로 추가하든 다음 실행부터 자동 편입)
  ② 문서명에서 법령명·법종·법령번호·시행일 파싱 → 법제처 DRF API로 현행본 조회
  ③ 등재본 ≠ 현행본이면 law_watch.sync_status='outdated' + 텔레그램 알림
  ④ 시행예정 통합본을 '전부' law_pending에 기록(다단 시행 수용 — 정보통신망법처럼
     2026.9.11 / 2026.10.1 / 2027.4.1 세 시점이 걸린 경우도 3건 모두 남는다).
     조문 취득·적재는 law_sync.py --pending 이 담당한다(감시는 발견만).

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
        # 괄호 안 전체("과학기술정보통신부령"). 재적재 시 문서명을 다시 만들 때 이걸 써야
        # 소관부처 접두가 보존된다 — 법제처 '법령구분명'은 "부령"만 주기 때문에
        # 그대로 쓰면 '전파법 시행규칙(과학기술정보통신부령)'이 '(부령)'이 되어
        # 같은 법령이 두 문서로 갈라진다.
        "law_type_full": m.group(1).strip(),
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
    """감시 대상 (doc_name, doc_category) — status='current'만.

    구버전(superseded)·시행예정본(pending)까지 긁으면 그것들이 법제처 현행본과 달라
    매번 '개정 감지'로 잘못 잡히고, --all-outdated가 이미 최신인 법령을 다시 받아온다.
    PostgREST 1000행 절단 회피를 위한 range 페이지네이션(지침 가드레일).
    """
    seen, start, page = {}, 0, 1000
    while True:
        r = (sb.table('document_chunks')
             .select('doc_name, doc_category')
             .eq('status', 'current')
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


def name_of(r):
    return r.get('법령명한글') or r.get('행정규칙명') or ''


def match_rows(rows, law_name: str, full_name: str = None):
    """검색 결과 중 해당 법령에 해당하는 행 전체.
    ① 접두(소관부처) 포함 완전일치 → 없으면 ② 접두 제거 후 일치
    """
    if not rows:
        return []
    if full_name:
        exact = [r for r in rows if _key(name_of(r)) == _key(full_name)]
        if exact:
            return exact
    return [r for r in rows if _key(_strip_org(name_of(r))) == _key(law_name)]


def pick_exact(rows, law_name: str, full_name: str = None, today: str = None):
    """검색 결과 중 '현재 시행 중인' 행 선택.

    행정규칙(admrul) 검색은 현행본과 시행예정본을 구분 없이 함께 돌려주고
    현행연혁코드도 비어 있는 경우가 많다. 목록 순서에 기대면 미래 시행본을
    현행으로 착각해 등재한다(적합성평가 고시 오적재 사고). 시행일자로 판정한다:
      ① 시행일 ≤ 오늘 인 것 중 시행일이 가장 늦은 행
      ② 그런 행이 없으면(전부 미래) 시행일이 가장 이른 행
    """
    cands = match_rows(rows, law_name, full_name)
    if not cands:
        return None
    today = today or datetime.now(KST).strftime('%Y%m%d')

    def enf(r):
        return str(r.get('시행일자') or '')

    in_force = [r for r in cands if enf(r) and enf(r) <= today]
    if in_force:
        return sorted(in_force, key=enf)[-1]
    dated = [r for r in cands if enf(r)]
    if dated:
        return sorted(dated, key=enf)[0]
    return cands[0]


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


# ── 시행예정본(다건) ───────────────────────────────────────

def _mst_key(mst):
    """일련번호 비교키 — 클수록 나중에 생성된 통합본. 숫자가 아니면 문자열로 폴백."""
    s = str(mst or '')
    return (1, int(s)) if s.isdigit() else (0, 0)


def find_pending_rows(meta, target: str, current_hit, today: str):
    """해당 법령의 시행예정 통합본 '전부'를 시행일 오름차순으로 반환.

    법령(law)  : 일반 검색(target=law)은 현행본만 주므로 eflaw(시행일법령)로 조회한다.
                 같은 MST가 서로 다른 시행일 통합본을 갖는 경우가 실제로 있어
                 (정보통신망법 MST 285199 → 20261001 / 20270401) 식별자는 (MST, 시행일).
    행정규칙   : admrul 검색이 현행본과 시행예정본을 함께 돌려주므로 추가 조회 없이
                 결과에서 시행일 > 오늘 인 행을 고른다.
    """
    # 대조 기준 이름을 검색어와 함께 추적한다 — 별칭으로 재검색해 놓고 원래 이름과
    # 대조하면, 기관명이 이름 중간에 박힌 규칙('…방송통신위원회 규칙'류)은 결과가
    # 와도 매칭 0건이 되어 시행예정이 조용히 누락된다.
    match_name, match_full = meta['law_name'], meta.get('full_name')
    if target == 'law':
        rows = drf_law_search(meta['law_name'], 'law', ef=True) or []
    else:
        rows = drf_law_search(meta['law_name'], 'admrul') or []
        if not match_rows(rows, match_name, match_full):
            for alt in alias_variants(meta['law_name']):
                rows = drf_law_search(alt, 'admrul') or []
                if match_rows(rows, alt, None):
                    match_name, match_full = alt, None
                    break

    cands = match_rows(rows, match_name, match_full)

    # 시행일 1개 = 통합본 1개. 같은 날 시행되는 개정법률이 여러 건이면 법제처가 공포번호마다
    # 행을 주지만 그 시행일의 통합본 본문은 동일하다(국가재정법 20260811: MST 285521/283171
    # → 조문 137개·본문 해시 일치 확인). 시행일로 묶고 가장 나중 공포건만 남긴다.
    best = {}
    for r in cands:
        mst, law_no, enf = row_fields(r, target)
        if not enf or enf <= today:
            continue
        prev = best.get(enf)
        if prev is None or _mst_key(mst) > _mst_key(prev['fields'][0]):
            best[enf] = {'fields': (mst, law_no, enf), 'enf': enf}
    return [best[k] for k in sorted(best)]


def save_pending(sb, meta, target: str, watch_doc_name: str, law_id: str, futures, today: str):
    """law_pending upsert + 이번에 안 잡힌 미적재 예정본 정리."""
    now = datetime.now(timezone.utc).isoformat()
    keep = set()
    for f in futures:
        mst, law_no, enf = f['fields']
        keep.add((mst, enf))
        sb.table('law_pending').upsert({
            'law_name': meta['law_name'], 'law_id': law_id or None,
            'law_type_token': meta['law_type_token'], 'api_target': target,
            'watch_doc_name': watch_doc_name,
            'mst': mst, 'law_no': law_no, 'enf_date': enf,
            'updated_at': now,
        }, on_conflict='law_name,mst,enf_date', ignore_duplicates=False).execute()
    retire_pending(sb, meta['law_name'], keep, today)


def retire_pending(sb, law_name: str, keep, today: str):
    """법제처 목록에서 사라진 예정본을 obsolete 처리.

    이미 적재(loaded)·승격(promoted)된 행은 건드리지 않는다 — 조문이 DB에 실재하므로
    상태를 지우면 추적을 잃는다. 시행일이 도래한 detected 행도 남긴다(승격 대상).
    """
    rows = (sb.table('law_pending').select('id, mst, enf_date, sync_state')
            .eq('law_name', law_name).eq('sync_state', 'detected').execute().data) or []
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        if (r['mst'], r['enf_date']) in keep or r['enf_date'] <= today:
            continue
        sb.table('law_pending').update({
            'sync_state': 'obsolete', 'updated_at': now,
            'note': f'법제처 시행예정 목록에서 사라짐({today})',
        }).eq('id', r['id']).execute()


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
    today = datetime.now(KST).strftime('%Y%m%d')

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

            # 시행예정본 — 있는 대로 전부 law_pending에 기록(다단 시행 수용)
            futures = find_pending_rows(meta, target, hit, today)
            if futures:
                if not a.dry_run:
                    save_pending(sb, meta, target, doc_name, rec['law_id'], futures, today)
                # law_watch의 pending_* 3칼럼은 '가장 이른 1건' 요약(대시보드 배지용).
                # 전체 목록은 law_pending을 본다.
                p_mst, p_no, p_enf = futures[0]['fields']
                rec.update({'pending_mst': p_mst, 'pending_law_no': p_no, 'pending_enf': p_enf})
                upcoming.append((meta['law_name'], futures))
            elif not a.dry_run:
                # 예정본이 사라졌으면(개정 철회·이미 시행) 미적재분 정리
                retire_pending(sb, meta['law_name'], keep=set(), today=today)

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
    pending_total = sum(len(f) for _, f in upcoming)
    print(f"  시행예정본: {pending_total}건 / 법령 {len(upcoming)}건")

    if outdated:
        print("\n[구버전 목록]")
        for d, nm, r_no, r_enf, l_no, l_enf in outdated:
            print(f"  - {nm}: 등재 {r_no}({r_enf}) → 현행 {l_no}({l_enf})")
    if upcoming:
        print("\n[시행예정]")
        for nm, futs in upcoming:
            steps = ", ".join(f"{f['fields'][1]}({f['enf']})" for f in futs)
            print(f"  - {nm}: {len(futs)}단계 → {steps}")
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
            lines.append(f"📅 <b>시행예정 {pending_total}건</b> (법령 {len(upcoming)}건)")
            for nm, futs in upcoming[:5]:
                lines.append(f"· {nm}: " + " / ".join(f"{f['enf']}" for f in futs))
            if len(upcoming) > 5:
                lines.append(f"  … 외 {len(upcoming) - 5}개 법령")
        notify(lines)

    print("\n=== 완료 ===")


if __name__ == '__main__':
    main()
