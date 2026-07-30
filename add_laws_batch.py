"""
법령 일괄 신규 적재 — 딥리서치+전수점검으로 확정된 목록을 순차 등재.

law_sync.py / law_watch.py의 기존 함수를 그대로 재사용한다(중복 구현 금지).
sync_one과 다른 점은 "기존 문서의 갱신"이 아니라 "KB에 전혀 없던 법령의 신규 추가"라는 것뿐 —
검색·조문취득·청킹·문서명·삽입검증·law_watch 등록 로직은 동일하게 따른다.

사용법:
  python add_laws_batch.py --dry-run   # 검색·조문취득까지만, DB 미변경
  python add_laws_batch.py             # 실제 적재(순차, 병렬 금지)
  python add_laws_batch.py --only "위치정보"   # 이름에 해당 문자열 포함된 항목만
"""
import os
import sys
import time
import argparse
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import sb_client
from law_watch import drf_law_search, pick_exact, row_fields, alias_variants, norm_name
from law_sync import (fetch_law_articles, fetch_admrul_articles, chunk_articles,
                       build_doc_name, _law_type_label)

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# (검색명, doc_category, target 힌트 or None=자동판별)
# target 힌트: 'law'(법률/시행령/시행규칙) / 'admrul'(고시/훈령/예규/공고) / None(law 먼저 시도 후 admrul)
TARGETS = [
    # ── A. 위치정보/개인정보/통신비밀/기반보호/방미통위설치법 (법률·시행령·시행규칙) ──
    ("위치정보의 보호 및 이용 등에 관한 법률", "위치정보보호법", "law"),
    ("위치정보의 보호 및 이용 등에 관한 법률 시행령", "위치정보보호법_시행령", "law"),
    ("통신비밀보호법", "통신비밀보호법", "law"),
    ("통신비밀보호법 시행령", "통신비밀보호법_시행령", "law"),
    ("개인정보 보호법", "개인정보보호법", "law"),
    ("개인정보 보호법 시행령", "개인정보보호법_시행령", "law"),
    ("정보통신기반 보호법", "정보통신기반보호법", "law"),
    ("정보통신기반 보호법 시행령", "정보통신기반보호법_시행령", "law"),
    ("정보통신기반 보호법 시행규칙", "정보통신기반보호법_시행규칙", "law"),
    ("방송미디어통신위원회의 설치 및 운영에 관한 법률", "방미통위설치법", "law"),
    ("방송미디어통신위원회의 설치 및 운영에 관한 법률 시행령", "방미통위설치법_시행령", "law"),
    ("전기통신사업 회계정리 및 보고에 관한 규정", "전기통신사업법_시행령", "law"),

    # ── A. 고시·행정규칙 18건 ──
    ("위치정보의 관리적ㆍ기술적 보호조치 기준", "위치정보보호법", "admrul"),
    ("개인정보의 안전성 확보조치 기준", "개인정보보호법", "admrul"),
    ("주요정보통신기반시설 취약점 분석ㆍ평가 기준", "정보통신기반보호법", "admrul"),
    ("전기통신설비의 상호접속기준", "전기통신사업법", "admrul"),
    ("설비등의 제공조건 및 대가산정기준", "전기통신사업법", "admrul"),
    ("전기통신번호관리세칙", "전기통신사업법", "admrul"),
    ("이동전화망번호관리기준", "전기통신사업법", "admrul"),
    ("이동전화서비스 번호이동성 시행 등에 관한 기준", "전기통신사업법", "admrul"),
    ("전기통신사업 회계분리기준", "전기통신사업법", "admrul"),
    ("보편적역무손실보전금 산정방법 등에 관한 기준", "전기통신사업법", "admrul"),
    ("도매제공의무사업자의 도매제공의무서비스 대상과 도매제공의 조건ㆍ절차ㆍ방법 및 대가의 산정에 관한 기준", "전기통신사업법", "admrul"),
    ("방송통신사업 금지행위 등에 대한 업무처리규정", "전기통신사업법", "admrul"),
    ("금지행위 위반에 대한 과징금 부과 세부기준", "전기통신사업법", "admrul"),
    ("결합판매의 금지행위 세부 유형 및 심사기준", "전기통신사업법", "admrul"),
    ("이용약관 인가대상 기간통신서비스와 기간통신사업자", "전기통신사업법", "admrul"),
    ("전기통신사업용 무선설비의 기술기준", "기술기준", "admrul"),
    ("정보통신망을 이용한 이동통신단말장치의 지원금 제시행위 시 사전승낙서 게시 기준", "전기통신사업법", "admrul"),
    ("이동통신사업자 등의 자료제출 방법 등에 대한 고시", "전기통신사업법", "admrul"),
    ("본인확인기관 지정 등에 관한 기준", "전기통신사업법", "admrul"),

    # ── B. 운영자 지시 승격 ──
    ("재난문자방송 기준 및 운영규정", "재난통신", "admrul"),

    # ── C. 상향식 전수 점검 발견 16건 ──
    ("방송통신발전기금 분담금 산정 및 부과에 관한 세부사항", "방송통신발전기본법", "admrul"),
    ("방송통신발전기금 분담금 징수 및 부과 등에 관한 사항", "방송통신발전기본법", "admrul"),
    ("전기통신설비의 상호접속ㆍ공동사용 및 정보제공 협정의 인가대상 기간통신사업자", "전기통신사업법", "admrul"),
    ("전기통신설비 의무제공대상 기간통신사업자", "전기통신사업법", "admrul"),
    ("전기통신설비의 공동사용 등의 기준", "전기통신사업법", "admrul"),
    ("중요한 전기통신설비", "전기통신사업법", "admrul"),
    ("주요통신사업자의 통신시설 등급 지정 및 관리 기준", "전기통신사업법", "admrul"),
    ("전기통신설비의 정보제공기준", "전기통신사업법", "admrul"),
    ("전기통신사업자간 불합리하거나 차별적인 조건ㆍ제한 부과의 부당한 행위 세부기준", "전기통신사업법", "admrul"),
    ("위치정보보호 법규 위반에 대한 과징금 부과기준", "위치정보보호법", "admrul"),
    ("긴급구조를 위한 소방기관의 위치정보 이용ㆍ관리 지침", "재난통신", "admrul"),
    ("재난피해자등의 개인 및 위치정보 요청ㆍ제공ㆍ이용지침", "재난통신", "admrul"),
    ("기간통신사업의 양수ㆍ합병 인가 등의 심사기준 및 절차", "전기통신사업법", "admrul"),
    ("공익성심사의 대상이 되는 기간통신사업자의 범위", "전기통신사업법", "admrul"),
    ("기반시설에 해당하는 전기통신설비", "전기통신사업법", "admrul"),
    ("경고문구의 표기 내용 및 방법", "전기통신사업법", "admrul"),

    # ── D. Fable 재검증 추가 3건 ──
    ("요금한도 초과 등의 고지에 관한 기준", "전기통신사업법", "admrul"),
    ("거짓으로 표시된 전화번호로 인한 이용자의 피해 예방 등에 관한 고시", "전기통신사업법", "admrul"),
    ("방송통신위원회 재정 및 알선 등에 관한 규정", "전기통신사업법", "admrul"),

    # ── E. 경계선 3건 ──
    ("국제전화요금 정산계약에 관한 신고방식 및 절차", "전기통신사업법", "admrul"),
    ("재난안전통신망 표준운영절차의 관리와 활용에 관한 규정", "재난통신", "admrul"),
    ("재난방송 및 민방위경보방송의 실시에 관한 기준", "재난통신", "admrul"),
]


def already_have(sb, law_name):
    """이미 정확히 같은 법령명(괄호 앞부분 완전일치)의 현행 문서가 있으면 반환.

    앞 N자 부분일치는 쓰지 않는다 — "법"과 "법 시행령", "상호접속기준"과
    "상호접속·공동사용 및 정보제공 협정의 인가대상 기간통신사업자"처럼 접두어가 같은
    별개 문서를 같다고 오판해 5건을 잘못 건너뛴 사고가 실제로 있었다.
    """
    key = norm_name(law_name).replace(' ', '')
    r = (sb.table('document_chunks').select('doc_name')
         .eq('status', 'current').ilike('doc_name', f'{law_name}(%').limit(5).execute())
    for row in (r.data or []):
        head = row['doc_name'].split('(')[0]
        if norm_name(head).replace(' ', '') == key:
            return row['doc_name']
    return None


def search_with_fallback(law_name, target_hint):
    targets = [target_hint] if target_hint else ['law', 'admrul']
    for target in targets:
        rows = drf_law_search(law_name, target)
        hit = pick_exact(rows, law_name)
        if hit:
            return target, hit
        for alt in alias_variants(law_name):
            rows = drf_law_search(alt, target)
            hit = pick_exact(rows, alt)
            if hit:
                return target, hit
    return None, None


def add_one(sb, law_name, category, target_hint, dry_run=False):
    existing = already_have(sb, law_name)
    if existing:
        return 'skip', f"이미 보유: {existing}"

    target, hit = search_with_fallback(law_name, target_hint)
    if not hit:
        return 'fail', "법제처 검색 결과 없음"

    mst, law_no, enf = row_fields(hit, target)
    try:
        if target == 'law':
            articles, basic = fetch_law_articles(mst)
            type_token = basic.get('법령구분명') or hit.get('법령구분명')
            org = None
            law_id = str(hit.get('법령ID') or '')
        else:
            articles, basic = fetch_admrul_articles(mst)
            type_token = basic.get('행정규칙종류') or hit.get('행정규칙종류') or '고시'
            org = basic.get('소관부처명') or hit.get('소관부처명') or ''
            law_id = str(hit.get('행정규칙ID') or '')
    except Exception as e:
        return 'fail', f"조문 취득 실패: {str(e)[:120]}"

    # 첨부파일 전용 문서 — 법제처가 조문 대신 "자세한 내용은 상단 메뉴 버튼을 이용" 안내만 준다
    # (지침 §재적재 불가 사례와 동일 유형 — 무선통신매뉴얼·전기안전 통합처리지침에서도 발생).
    # 그대로 넣으면 안내문 1청크가 유일 본문인 빈 문서가 생기므로 여기서 걸러낸다.
    if len(articles) == 1 and articles[0][0] is None and '상단 메뉴' in articles[0][1] and '버튼을 이용' in articles[0][1]:
        return 'fail', "첨부파일 전용 문서(조문 미제공) — 법제처 원문 첨부파일만 존재, API 재적재 불가"

    chunks = chunk_articles(articles)
    if not chunks:
        return 'fail', "조문 취득 결과가 비어 있음(첨부파일 전용 등)"

    new_doc = build_doc_name(law_name, type_token, law_no, enf, org, target)

    # 다른 검색어로 이미 들어간 경우 재확인(정확 문서명 기준)
    dup = (sb.table('document_chunks').select('id', count='exact')
           .eq('doc_name', new_doc).eq('status', 'current').limit(1).execute()).count or 0
    if dup:
        return 'skip', f"이미 보유(정확명): {new_doc}"

    print(f"    → {new_doc}  [{len(chunks)}청크, target={target}]")
    if dry_run:
        return 'ok', f"{new_doc} ({len(chunks)}청크, dry-run)"

    now = datetime.now(timezone.utc).isoformat()
    payload = [{
        'doc_name': new_doc, 'doc_category': category, 'chunk_index': i,
        'content': c['content'], 'article_no': c['article_no'],
        'effective_date': enf, 'notice_no': (law_no if target != 'law' else None),
        'law_id': law_id, 'law_mst': mst, 'status': 'current',
        'is_approved': True,
    } for i, c in enumerate(chunks)]
    for i in range(0, len(payload), 50):
        sb.table('document_chunks').insert(payload[i:i + 50]).execute()

    got = ((sb.table('document_chunks').select('id', count='exact')
            .eq('doc_name', new_doc).limit(1).execute()).count) or 0
    if got != len(payload):
        return 'fail', f"삽입 검증 실패: {len(payload)}청크 중 {got}청크만 확인"

    sb.table('law_watch').upsert({
        'doc_name': new_doc, 'law_name': law_name,
        'law_type_token': type_token, 'api_target': target,
        'law_id': law_id, 'registered_mst': mst,
        'registered_law_no': law_no, 'registered_enf': enf,
        'latest_mst': mst, 'latest_law_no': law_no, 'latest_enf': enf,
        'watch_status': 'watching', 'sync_status': 'current',
        'last_checked_at': now, 'updated_at': now,
        'note': f'add_laws_batch 신규 적재 ({datetime.now():%Y-%m-%d})',
    }, on_conflict='doc_name').execute()

    return 'ok', f"{new_doc} ({len(payload)}청크)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--only', default=None, help='검색명에 이 문자열이 포함된 항목만')
    args = ap.parse_args()

    sb = sb_client.make_client(SB_URL, SB_KEY)
    targets = TARGETS
    if args.only:
        targets = [t for t in targets if args.only in t[0]]
        print(f"--only 필터: {len(targets)}건")

    results = {'ok': [], 'skip': [], 'fail': []}
    for idx, (law_name, category, target_hint) in enumerate(targets, 1):
        print(f"\n[{idx}/{len(targets)}] {law_name}")
        try:
            status, msg = add_one(sb, law_name, category, target_hint, dry_run=args.dry_run)
        except Exception as e:
            status, msg = 'fail', f"예외: {str(e)[:150]}"
        results[status].append((law_name, msg))
        print(f"  [{status}] {msg}")
        time.sleep(0.5)

    print("\n" + "=" * 60)
    print(f"완료: 성공 {len(results['ok'])} / 스킵 {len(results['skip'])} / 실패 {len(results['fail'])}")
    if results['fail']:
        print("\n실패 목록:")
        for name, msg in results['fail']:
            print(f"  - {name}: {msg}")
    if results['skip']:
        print("\n스킵 목록:")
        for name, msg in results['skip']:
            print(f"  - {name}: {msg}")


if __name__ == '__main__':
    main()
