"""
법령 현행화 수집·적재 (Phase 2) — 법제처 DRF API에서 조문을 직접 받아 지식베이스에 등재.

PDF 다운로드·업로드가 필요 없다. API가 조문 구조(조문번호·제목·항·호)를 그대로 주므로
PDF 텍스트 추출보다 청킹·조문번호(article_no)가 정확하다.

동작:
  ① law_watch에서 대상 선정(--doc-name 지정 또는 --all-outdated)
  ② DRF lawService.do로 조문 취득 (법령=MST / 행정규칙=ID)
  ③ 조문 단위 청킹 → document_chunks 삽입 (status='current', law_id·law_mst 기록)
  ④ 같은 law_id의 기존 버전을 status='superseded'로 내리고, 보존 상한(기본 3버전) 초과분 삭제
  ⑤ law_watch 갱신 → 임베딩 백필(backfill_embeddings.py) 호출

OKF 요약은 만들지 않는다(--with-okf 미지원). 초기 일괄 정비는 세션에서 무료로 작성하고,
이후 개정분만 대시보드 승인 훅이 API로 자동 생성하는 운영 방침(지침 §법령·규제 요약 레이어).

사용법:
  python law_sync.py --list                          # 현행화 대상 목록만
  python law_sync.py --doc-name "<등재 문서명>"        # 1건 현행화
  python law_sync.py --doc-name "<문서명>" --keep-old # 구버전을 superseded로만(삭제 안 함)
  python law_sync.py --all-outdated                  # outdated 전체
  python law_sync.py --doc-name "<문서명>" --dry-run  # 취득·청킹만, DB 미변경

필요 .env: SUPABASE_URL, SUPABASE_SERVICE_KEY, LAW_OC_KEY, VOYAGE_API_KEY(백필용)
"""

import os
import re
import sys
import time
import json
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone

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
from law_watch import (norm_name, parse_doc_name, api_target_of,
                       drf_law_search, pick_exact, row_fields)

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SERVICE_KEY")
OC_KEY = os.getenv("LAW_OC_KEY")
DRF_SERVICE = "https://www.law.go.kr/DRF/lawService.do"

CHUNK_SIZE = 800          # upload_law_pdf.py와 동일
CHUNK_OVERLAP = 100
KEEP_VERSIONS = 3         # 현행 포함 보존 버전 수 (지침: 최근 2~3개)
ROOT = Path(__file__).parent


# ── 조문 취득 ─────────────────────────────────────────────

def _txt(v):
    """법제처 API는 같은 필드를 문자열/리스트 어느 쪽으로도 반환한다(조문·항·호 모두).
    한쪽만 가정하면 일부 법령에서 'list' object has no attribute 'strip'로 죽는다."""
    if v is None:
        return ''
    if isinstance(v, (list, tuple)):
        return "\n".join(x for x in (_txt(i) for i in v) if x)
    return str(v).strip()


def fetch_law_articles(mst: str):
    """법령(target=law) → [(article_no, text)] + 기본정보"""
    r = requests.get(DRF_SERVICE, params={'OC': OC_KEY, 'target': 'law',
                                          'type': 'JSON', 'MST': mst}, timeout=60)
    r.raise_for_status()
    d = r.json()['법령']
    basic = d.get('기본정보', {})
    out = []
    for a in d['조문']['조문단위']:
        no = _txt(a.get('조문번호'))
        br = _txt(a.get('조문가지번호'))
        title = _txt(a.get('조문제목'))
        if not no:
            continue
        label = f"{no}조" + (f"의{br}" if br else "")
        art_no = f"{label}({title})" if title else label
        parts = [_txt(a.get('조문내용'))]
        hangs = a.get('항') or []
        if isinstance(hangs, dict):
            hangs = [hangs]
        for h in hangs:
            if not isinstance(h, dict):
                parts.append(_txt(h))
                continue
            parts.append(_txt(h.get('항내용')))
            hos = h.get('호') or []
            if isinstance(hos, dict):
                hos = [hos]
            for ho in hos:
                if not isinstance(ho, dict):
                    parts.append(_txt(ho))
                    continue
                parts.append(_txt(ho.get('호내용')))
                mos = ho.get('목') or []
                if isinstance(mos, dict):
                    mos = [mos]
                for mo in mos:
                    parts.append(_txt(mo.get('목내용') if isinstance(mo, dict) else mo))
        text = "\n".join(p for p in parts if p)
        if len(text.strip()) > 10:
            out.append((art_no, text))
    return out, basic


ADM_ART_RE = re.compile(r'^제(\d+)조(?:의(\d+))?\s*(?:\(([^)]*)\))?')


def fetch_admrul_articles(rule_id: str):
    """행정규칙(target=admrul) → [(article_no, text)] + 기본정보.
    본문이 '제1조(목적) …' 형태의 문자열 리스트로 오므로 앞부분에서 조문번호를 파싱."""
    r = requests.get(DRF_SERVICE, params={'OC': OC_KEY, 'target': 'admrul',
                                          'type': 'JSON', 'ID': rule_id}, timeout=60)
    r.raise_for_status()
    d = r.json()
    top = list(d.keys())[0]
    basic = d[top].get('행정규칙기본정보', {})
    body = d[top].get('조문내용') or []
    if isinstance(body, str):
        body = [body]
    out = []
    for item in body:
        text = str(item).strip()
        if len(text) < 10:
            continue
        m = ADM_ART_RE.match(text)
        if m:
            label = f"{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
            art_no = f"{label}({m.group(3)})" if m.group(3) else label
        else:
            art_no = None          # 장 제목 등
        out.append((art_no, text))
    return out, basic


# ── 청킹 ──────────────────────────────────────────────────

def chunk_articles(articles):
    """조문 단위 청킹. 조문이 길면 분할하되 article_no는 유지."""
    chunks = []
    for art_no, text in articles:
        text = text.strip()
        if not text:
            continue
        if len(text) <= CHUNK_SIZE:
            chunks.append({'article_no': art_no, 'content': text})
            continue
        start = 0
        while start < len(text):
            piece = text[start:start + CHUNK_SIZE].strip()
            if len(piece) > 50:
                chunks.append({'article_no': art_no, 'content': piece})
            start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ── 문서명 ────────────────────────────────────────────────

def build_doc_name(law_name, type_token, law_no, enf_date, org=None, target='law'):
    """기존 관례 유지: '전파법(법률)(제21065호)(20260102)'
    행정규칙은 '(과학기술정보통신부고시)'처럼 소관부처+종류."""
    if target == 'law':
        paren = type_token
    else:
        paren = f"{org or ''}{type_token}"
    no = str(law_no or '').strip()
    if no and not no.startswith('제'):
        no = f"제{no}호"
    return f"{law_name}({paren})({no})({enf_date})"


def fetch_existing(sb, law_name, prev_doc_name=None):
    """같은 법령의 기존 등재본들 (doc_name, status, law_mst, doc_category).

    기관명 변경(방송통신위원회→방송미디어통신위원회 등)으로 법령명 자체가 바뀐 경우
    이름만으로는 구버전을 찾지 못하므로, 감시가 지목한 등재 문서명(prev_doc_name)을
    항상 후보에 포함한다. 이게 없으면 구버전이 current로 남아 자문이 옛 규정을 답한다.
    """
    # 전체 스캔은 청크가 수만 건이 되면 statement timeout(57014)이 난다.
    # 법령명 앞부분으로 ilike 선필터 + 감시가 지목한 문서명을 별도 조회해 병합.
    core = norm_name(law_name)[:20].replace('%', '').replace('_', '')
    rows, start, page = [], 0, 1000
    while True:
        r = (sb.table('document_chunks')
             .select('doc_name, doc_category, status, law_mst, law_id')
             .ilike('doc_name', f'%{core}%')
             .order('id').range(start, start + page - 1).execute())
        batch = r.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        start += page
    if prev_doc_name and not any(x['doc_name'] == prev_doc_name for x in rows):
        extra = (sb.table('document_chunks')
                 .select('doc_name, doc_category, status, law_mst, law_id')
                 .eq('doc_name', prev_doc_name).limit(1000).execute()).data or []
        rows.extend(extra)
    agg = {}
    key = norm_name(law_name).replace(' ', '')
    for row in rows:
        meta = parse_doc_name(row['doc_name'])
        if not meta:
            continue
        same_name = norm_name(meta['law_name']).replace(' ', '') == key
        is_prev = prev_doc_name and row['doc_name'] == prev_doc_name
        if not (same_name or is_prev):
            continue
        d = agg.setdefault(row['doc_name'], {
            'doc_category': row.get('doc_category'), 'status': row.get('status'),
            'law_mst': row.get('law_mst'), 'enf': meta.get('enf_date') or '',
            'law_no': meta.get('law_no') or '', 'count': 0})
        d['count'] += 1
    return agg


def sync_one(sb, watch_row, args):
    doc_name = watch_row['doc_name']
    meta = parse_doc_name(doc_name)
    if not meta:
        print(f"  ! 문서명 파싱 실패: {doc_name}")
        return False

    law_name = watch_row.get('law_name') or meta['law_name']
    target = watch_row.get('api_target') or api_target_of(meta['law_type_token'])

    # 최신 현행본 재조회(감시 이후 또 바뀌었을 수 있음)
    rows = drf_law_search(law_name, target)
    hit = pick_exact(rows, law_name, meta.get('full_name'))
    if not hit:
        print(f"  ! 법제처에서 현행본을 찾지 못함: {law_name}")
        return False
    mst, law_no, enf = row_fields(hit, target)

    print(f"\n■ {law_name}")
    print(f"  등재본: {meta['law_no']} ({meta['enf_date']})  →  현행본: {law_no} ({enf})")

    # 조문 취득
    if target == 'law':
        articles, basic = fetch_law_articles(mst)
        type_token = basic.get('법령구분명') or meta['law_type_token']
        org = None
        law_id = str(hit.get('법령ID') or '')
    else:
        articles, basic = fetch_admrul_articles(mst)
        type_token = basic.get('행정규칙종류') or hit.get('행정규칙종류') or '고시'
        org = basic.get('소관부처명') or hit.get('소관부처명') or ''
        law_id = str(hit.get('행정규칙ID') or '')

    chunks = chunk_articles(articles)
    if not chunks:
        print("  ! 조문 취득 결과가 비어 있음 — 중단")
        return False

    new_doc = build_doc_name(law_name, type_token, law_no, enf, org, target)
    existing = fetch_existing(sb, law_name, prev_doc_name=doc_name)
    category = next((v['doc_category'] for v in existing.values() if v.get('doc_category')), None)
    category = category or ('법령' if target == 'law' else '고시')

    print(f"  신규 문서명: {new_doc}")
    print(f"  조문 {len(articles)}개 → 청크 {len(chunks)}개 · 카테고리 '{category}'")
    if existing:
        print(f"  기존 버전 {len(existing)}건: " +
              ", ".join(f"{k.split('(')[-2] if '(' in k else k}" for k in list(existing)[:3]))

    if new_doc in existing:
        print("  → 이미 등재된 버전입니다. 건너뜀")
        return False

    if args.dry_run:
        print("  [dry-run] DB 변경 없음")
        return True

    # ① 신규 버전 삽입
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
    print(f"  ✓ 신규 등재 {len(payload)}청크")

    # ② 기존 버전 상태 정리 — 시행일이 미래면 pending(시행예정본), 과거면 superseded
    today = datetime.now().strftime('%Y%m%d')
    pend, sup = [], []
    for old_doc, info in existing.items():
        st = 'pending' if (info['enf'] or '') > today else 'superseded'
        sb.table('document_chunks').update({'status': st}).eq('doc_name', old_doc).execute()
        (pend if st == 'pending' else sup).append(old_doc)
    if sup:
        print(f"  ✓ 구버전 {len(sup)}건 → superseded")
    if pend:
        print(f"  ✓ 시행예정본 {len(pend)}건 → pending (보존, 시행일 도래 시 현행 승격)")

    # ③ 보존 상한 초과분 삭제 — superseded만 대상(pending=미래 시행본은 항상 보존)
    if not args.keep_old:
        olds = sorted(((k, v) for k, v in existing.items() if k in sup),
                      key=lambda kv: kv[1]['enf'], reverse=True)
        for old_doc, info in olds[KEEP_VERSIONS - 1:]:
            sb.table('document_chunks').delete().eq('doc_name', old_doc).execute()
            print(f"  ✓ 보존 상한 초과 삭제: {old_doc[:60]} ({info['count']}청크)")

    # ④ law_watch 갱신 — 기존 행은 새 문서명으로 이관
    sb.table('law_watch').upsert({
        'doc_name': new_doc, 'law_name': law_name,
        'law_type_token': meta['law_type_token'], 'api_target': target,
        'law_id': law_id, 'registered_mst': mst,
        'registered_law_no': law_no, 'registered_enf': enf,
        'latest_mst': mst, 'latest_law_no': law_no, 'latest_enf': enf,
        'watch_status': 'watching', 'sync_status': 'current',
        'last_checked_at': now, 'updated_at': now,
        'note': f'law_sync 자동 현행화 ({datetime.now():%Y-%m-%d})',
    }, on_conflict='doc_name').execute()
    if doc_name != new_doc:
        sb.table('law_watch').delete().eq('doc_name', doc_name).execute()
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--doc-name', help='현행화할 등재 문서명(부분 일치 허용)')
    ap.add_argument('--all-outdated', action='store_true', help='outdated 전체 처리')
    ap.add_argument('--list', action='store_true', help='대상 목록만 출력')
    ap.add_argument('--keep-old', action='store_true', help='구버전 삭제 없이 superseded로만')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-backfill', action='store_true', help='임베딩 백필 생략')
    a = ap.parse_args()

    if not (SB_URL and SB_KEY and OC_KEY):
        print("오류: .env에 SUPABASE_URL, SUPABASE_SERVICE_KEY, LAW_OC_KEY 필요")
        sys.exit(1)
    sb = sb_client.make_client(SB_URL, SB_KEY)

    outdated = (sb.table('law_watch').select('*')
                .eq('sync_status', 'outdated').order('law_name').execute().data) or []

    if a.list or not (a.doc_name or a.all_outdated):
        print(f"현행화 대상 {len(outdated)}건:")
        for r in outdated:
            print(f"  - {r['law_name']}")
            print(f"      등재 {r['registered_law_no']}({r['registered_enf']}) "
                  f"→ 현행 {r['latest_law_no']}({r['latest_enf']})")
            print(f"      doc_name: {r['doc_name'][:78]}")
        if not (a.doc_name or a.all_outdated):
            print("\n처리하려면 --doc-name \"<문서명>\" 또는 --all-outdated")
        return

    if a.doc_name:
        targets = [r for r in outdated if a.doc_name in r['doc_name']]
        if not targets:                      # outdated 외 문서도 강제 지정 가능
            allrows = (sb.table('law_watch').select('*').execute().data) or []
            targets = [r for r in allrows if a.doc_name in r['doc_name']]
        if not targets:
            print(f"대상을 찾지 못함: {a.doc_name}")
            sys.exit(1)
    else:
        targets = outdated

    print(f"=== 현행화 시작: {len(targets)}건 (dry-run={a.dry_run}) ===")
    done = 0
    for r in targets:
        try:
            if sync_one(sb, r, a):
                done += 1
        except Exception as e:
            print(f"  ! 실패({r.get('law_name')}): {str(e)[:140]}")
        time.sleep(0.3)

    print(f"\n=== 완료: {done}/{len(targets)}건 등재 ===")

    if done and not a.dry_run and not a.no_backfill:
        print("\n[임베딩 백필]")
        subprocess.run([sys.executable, str(ROOT / 'backfill_embeddings.py')], check=False)
        print("\n※ 관계도 인용망 재구축 권장: python build_law_citation_graph.py")
        print("※ OKF 요약은 세션에서 작성(초기 정비 방침) — 지침 §법령·규제 요약 레이어")


if __name__ == '__main__':
    main()
