#!/usr/bin/env python3
"""
법제처 3단비교(thdCmp knd=2) → law_delegations 위임 대응표 적재

무엇을 푸는가
--------------
`/law`(텔레그램 봇 법령 검색)가 "개인정보 유출 신고 기한"에 **시행령 제40조**(72시간)만
답하고 상위 **법률 제34조**를 빠뜨렸다. 검색어·프롬프트 튜닝은 검색 운에 기대는 대증요법이라,
법제처가 정본으로 제공하는 **조문 단위 위임 대응표**를 테이블로 고정한다.
조문 하나를 찾으면 그 짝(상위 근거 / 하위 위임)을 조회 한 번으로 붙일 수 있다.

무엇이 들어오나 / 안 들어오나
------------------------------
- 들어옴: **법률 조문 → 시행령 조문**, **법률 조문 → 시행규칙 조문**(시행령을 거치지 않는 직접
  위임 포함). 자식 법령명은 API가 준 정본을 쓰므로 **타계열 위임**도 잡힌다
  (실측: 전파법 → `무선설비규칙`, 전기통신사업법 → `방송통신설비의 기술기준에 관한 규정`).
- **안 들어옴: 고시·훈령·예규 등 행정규칙.** 3단비교는 이름 그대로 **법률-시행령-시행규칙 3단**
  이라 행정규칙 위임(예: 법 → 시행령 → 과기정통부 고시)은 API가 아예 반환하지 않는다.
  억지로 채우지 말 것 — 고시 계열 연결이 필요하면 별도 경로(조문 인용 파싱)를 써야 한다.
- **안 들어옴: 시행령 → 시행규칙 재위임.** 이 표의 parent는 항상 **법률**이다(그래야 재적재 시
  삭제 범위가 `parent_law = 그 법률`로 딱 떨어진다). 법령 단위의 시행령→시행규칙 관계는
  이미 `build_law_citation_graph.py`가 law_graph_edges(source='thdcmp')로 만든다.

조번호 정규형 (document_chunks 조인 전제)
------------------------------------------
API의 `조번호`(4자리 zero-pad) + `조가지번호`를 합쳐 **`34조`, `34조의2`** 형태로 저장한다.
`제` 접두사를 붙이지 않는 이유는 조인 상대인 `document_chunks.article_no`가 그 형태이기 때문:
  실측값 → `"34조(개인정보 유출 등의 통지ㆍ신고)"`, `"7조의9(보호위원회의 심의ㆍ의결 사항 등)"`,
           제목 없이 `"7조"`만 있는 청크도 존재
따라서 조문 원문을 찾을 때의 대조식은 다음 둘의 OR 이다:
  `article_no = child_article`  OR  `article_no LIKE child_article || '(%'`
⚠️ `LIKE child_article || '%'` 단독은 쓰지 말 것 — `'34조%'`가 `34조의2(...)`까지 물어
   본조와 조의N을 뒤섞는다. 위 두 갈래는 그 오염을 막는다.

법령명 표기: API 응답과 `document_chunks.doc_name`이 **둘 다 가운뎃점 `ㆍ`**를 쓴다
(실측: API `표시ㆍ광고의 공정화에 관한 법률` = DB `표시ㆍ광고의 공정화에 관한 법률(법률)(...)`).
그래서 여기서는 `build_law_citation_graph.norm_name()`(ㆍ→·)을 **적용하지 않고** 공백만
정리해 원문 표기를 보존한다. 조인 상대가 DB이지 law_graph_nodes가 아니기 때문이다.
법령 문서 조인: `doc_name LIKE child_law || '(%'`.

실행 (PC, Python 3.12 전체 경로 / 수동 실행 시 프록시 제거 필수)
------------------------------------------------------------------
  $env:HTTP_PROXY=''; $env:HTTPS_PROXY=''
  C:\\Users\\SKTelecom\\AppData\\Local\\Programs\\Python\\Python312\\python.exe sync_law_delegations.py --dry-run
  ... sync_law_delegations.py --only "개인정보 보호법"
  ... sync_law_delegations.py                     # 전체 법률 재적재(멱등)
"""

import os
import re
import sys
import time
import argparse
from datetime import datetime, timezone

# Windows 스케줄러가 출력을 cp949로 캡처해 이모지 print가 UnicodeEncodeError로 죽는 문제 (배경역사 #19)
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

from sb_client import make_client
# DRF 호출부는 재구현하지 않고 그래프 스크립트의 검증된 헬퍼를 그대로 재사용한다.
from build_law_citation_graph import (
    resolve_law_id, _drf_get, LAW_OC_KEY, LAW_SERVICE_URL,
)

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
sb = make_client(SUPABASE_URL, SUPABASE_KEY)

TABLE = 'law_delegations'
CONFLICT_COLS = 'parent_law,parent_article,child_law,child_article'
UPSERT_BATCH = 200
API_SLEEP = 1.0          # 법제처 DRF 스로틀


def clean_name(name: str) -> str:
    """공백만 정리. 가운뎃점(ㆍ)은 document_chunks 표기와 같으므로 변환하지 않는다(docstring 참조)."""
    return re.sub(r'\s+', ' ', (name or '')).strip()


def art_no(cho_beonho, cho_gaji) -> str:
    """조번호('0034')+조가지번호('02') → '34조' / '34조의2'.
    zero-pad 제거·'제' 접두사 없음 = document_chunks.article_no 형식."""
    try:
        n = int(str(cho_beonho or '').lstrip('0') or '0')
    except ValueError:
        return ''
    if n <= 0:
        return ''
    label = f'{n}조'
    try:
        g = int(str(cho_gaji or '0'))
    except ValueError:
        g = 0
    if g > 0:
        label += f'의{g}'
    return label


def art_title(cho_jemok: str) -> str:
    """'제34조(개인정보 유출 등의 통지ㆍ신고)' → '개인정보 유출 등의 통지ㆍ신고'.
    괄호가 없으면(제목 없는 조문) 원문을 그대로 둔다."""
    s = clean_name(cho_jemok)
    m = re.search(r'\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*$', s)
    return m.group(1).strip() if m else s


def as_list(v):
    """자식 조문 값은 dict 또는 list — 같은 법률 조문이 여러 하위 조문에 위임되면 API가
    행을 나눠 주기도 하고(실측: 법 제34조 → 시행령 39조·40조가 별개 행) 한 행 안에서
    list로 주기도 한다. 두 경우를 모두 흡수한다."""
    if v is None:
        return []
    if isinstance(v, dict):
        return [v]
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    return []


# ── 대상 법률: DB에서 뽑는다(하드코딩 금지) ──────────────────────────

def fetch_target_laws():
    """document_chunks의 `…(법률)(제N호)(날짜)` 문서 중 status='current' & is_approved → 법령명 집합.
    ⚠️ .order('id') 필수 — 정렬 없는 range() 페이지네이션은 페이지마다 순서가 달라져
       일부 문서가 통째로 누락된다(build_law_citation_graph.fetch_all_doc_rows와 같은 이유)."""
    names = set()
    page, offset = 1000, 0
    while True:
        r = (sb.table('document_chunks')
             .select('doc_name')
             .like('doc_name', '%(법률)%')
             .eq('status', 'current')
             .eq('is_approved', True)
             .order('id')
             .range(offset, offset + page - 1)
             .execute())
        rows = r.data or []
        for row in rows:
            dn = row.get('doc_name') or ''
            base = clean_name(dn.split('(법률)')[0])
            if len(base) >= 2:
                names.add(base)
        if len(rows) < page:
            break
        offset += page
    return sorted(names)


# ── 3단비교 파싱 ────────────────────────────────────────────────

def fetch_delegations(law_name: str, law_id: str, synced_at: str):
    """thdCmp knd=2 → 위임 행 목록(중복 제거됨).
    반환: (rows, n_articles) — rows는 law_delegations 컬럼과 1:1인 dict."""
    params = {'OC': LAW_OC_KEY, 'target': 'thdCmp', 'type': 'JSON',
              'ID': law_id, 'knd': '2'}
    data = _drf_get(LAW_SERVICE_URL, params, timeout=60).json()
    root = data.get('LspttnThdCmpLawXService') or {}
    arts = root.get('위임조문삼단비교', {}).get('법률조문', [])
    if isinstance(arts, dict):
        arts = [arts]

    # (parent_article, child_law, child_article) 로 중복 제거.
    # ⚠️ 필수 — 같은 대응이 여러 행으로 오는데, PostgREST 벌크 upsert는 한 payload 안에
    #    동일 conflict 키가 두 번 들어오면 "ON CONFLICT DO UPDATE cannot affect row a
    #    second time"으로 **전체가** 실패한다.
    out = {}
    for a in arts:
        if not isinstance(a, dict):
            continue
        p_art = art_no(a.get('조번호'), a.get('조가지번호'))
        if not p_art:
            continue
        p_title = art_title(a.get('조제목'))
        for key, kind in (('시행령조문', '시행령'), ('시행규칙조문', '시행규칙')):
            for c in as_list(a.get(key)):
                c_law = clean_name(c.get('법령명'))
                c_art = art_no(c.get('조번호'), c.get('조가지번호'))
                if not c_law or not c_art:
                    continue
                k = (p_art, c_law, c_art)
                if k in out:
                    continue
                out[k] = {
                    'parent_law': law_name,
                    'parent_article': p_art,
                    'parent_title': p_title or None,
                    'child_law': c_law,
                    'child_article': c_art,
                    'child_title': art_title(c.get('조제목')) or None,
                    'child_kind': kind,
                    'synced_at': synced_at,
                }
    return list(out.values()), len(arts)


def upsert_rows(rows):
    for i in range(0, len(rows), UPSERT_BATCH):
        (sb.table(TABLE)
         .upsert(rows[i:i + UPSERT_BATCH], on_conflict=CONFLICT_COLS)
         .execute())


def prune_stale(law_name: str, synced_at: str) -> int:
    """이번 실행에서 갱신되지 않은 같은 법률의 행 삭제(개정으로 사라진 위임 정리).
    ⚠️ 반드시 upsert 성공을 확인한 뒤에 호출한다 — 먼저 지우고 적재가 실패하면
       대응표에 공백이 생긴다(배경역사 #65: 선삭제 후 적재 실패 사고)."""
    r = (sb.table(TABLE).delete()
         .eq('parent_law', law_name)
         .lt('synced_at', synced_at)
         .execute())
    return len(r.data or [])


def main():
    ap = argparse.ArgumentParser(description='법제처 3단비교 위임 대응표 → law_delegations 적재')
    ap.add_argument('--dry-run', action='store_true', help='DB 무변경. 건수·표본만 출력')
    ap.add_argument('--only', metavar='법령명', help='해당 법률 하나만 처리')
    args = ap.parse_args()

    if not LAW_OC_KEY:
        print('[중단] LAW_OC_KEY 없음 — .env 확인')
        return 1

    synced_at = datetime.now(timezone.utc).isoformat()
    print('=== 3단비교 위임 대응표 동기화 ===' + ('  [DRY-RUN — DB 무변경]' if args.dry_run else ''))

    if args.only:
        laws = [clean_name(args.only)]
    else:
        laws = fetch_target_laws()
    print(f'대상 법률: {len(laws)}건')

    total_rows = 0
    total_pruned = 0
    failures = []   # (법령명, 사유)

    for idx, law in enumerate(laws, 1):
        try:
            law_id = resolve_law_id(law)
        except Exception as e:
            failures.append((law, f'lawSearch 오류: {e}'))
            print(f'[{idx}/{len(laws)}] {law} — 실패(lawSearch): {e}')
            continue
        if not law_id:
            failures.append((law, '법령ID 미확인(법제처 정확매칭 실패)'))
            print(f'[{idx}/{len(laws)}] {law} — 건너뜀(법령ID 없음)')
            continue

        try:
            rows, n_arts = fetch_delegations(law, law_id, synced_at)
        except Exception as e:
            # 한 법령 실패가 전체를 죽이면 안 된다 — 기록만 하고 계속.
            failures.append((law, f'thdCmp 오류: {e}'))
            print(f'[{idx}/{len(laws)}] {law} — 실패(thdCmp): {e}')
            time.sleep(API_SLEEP)
            continue

        kinds = {}
        childs = {}
        for r in rows:
            kinds[r['child_kind']] = kinds.get(r['child_kind'], 0) + 1
            childs[r['child_law']] = childs.get(r['child_law'], 0) + 1
        summary = ', '.join(f'{k} {v}건' for k, v in sorted(childs.items(), key=lambda x: -x[1]))
        print(f'[{idx}/{len(laws)}] {law} (ID={law_id}) 법률조문 {n_arts}행 → 위임 {len(rows)}건'
              + (f'  [{summary}]' if summary else ''))

        if args.dry_run:
            for r in rows[:5]:
                print(f'      · {r["parent_article"]}({r["parent_title"]}) → '
                      f'{r["child_law"]} {r["child_article"]}({r["child_title"]}) [{r["child_kind"]}]')
            total_rows += len(rows)
            time.sleep(API_SLEEP)
            continue

        if rows:
            try:
                upsert_rows(rows)
            except Exception as e:
                # 적재 실패 시 prune 하지 않는다(공백 방지).
                failures.append((law, f'upsert 실패(삭제 생략): {e}'))
                print(f'      ! upsert 실패 — 기존 행 보존: {e}')
                time.sleep(API_SLEEP)
                continue
            try:
                pruned = prune_stale(law, synced_at)
            except Exception as e:
                failures.append((law, f'stale 삭제 실패(적재는 성공): {e}'))
                pruned = 0
            if pruned:
                print(f'      - 사라진 위임 {pruned}건 정리')
            total_pruned += pruned
        else:
            # 위임 0건 = 정상일 수 있으나(예: 하위법령 없는 법률) 전량 삭제는 위험하므로
            # 적재된 것이 없으면 기존 행에 손대지 않는다.
            print('      (위임 0건 — 기존 행 보존, 삭제 생략)')
        total_rows += len(rows)
        time.sleep(API_SLEEP)

    print('\n── 요약 ─────────────────────────────────')
    print(f'  처리 법률: {len(laws)}건 / 성공 {len(laws) - len(failures)}건')
    print(f'  위임 행: {total_rows}건' + ('' if args.dry_run else f' upsert, {total_pruned}건 정리'))
    if failures:
        print(f'  실패·건너뜀 {len(failures)}건:')
        for law, why in failures:
            print(f'    · {law}: {why}')
    else:
        print('  실패 없음')
    print('=== 완료' + ('(dry-run)' if args.dry_run else '') + ' ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
