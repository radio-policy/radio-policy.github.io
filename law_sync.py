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
  python law_sync.py --pending                       # 시행예정본 전부 status=pending으로 등재
  python law_sync.py --pending --pending-law 정보통신망 # 특정 법령만
  python law_sync.py --promote                       # 시행일 도래분 → current 승격(매일 자동)

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
                       drf_law_search, pick_exact, row_fields,
                       norm_law_no, alias_variants)

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SERVICE_KEY")
OC_KEY = os.getenv("LAW_OC_KEY")
DRF_SERVICE = "https://www.law.go.kr/DRF/lawService.do"

CHUNK_SIZE = 800          # upload_law_pdf.py와 동일
CHUNK_OVERLAP = 100
KEEP_VERSIONS = 3         # 현행 포함 보존 버전 수 (지침: 최근 2~3개)
ADDENDA_KEEP = 15         # 담을 부칙 개수(최근순). 정부조직법처럼 개정이 잦은 법은 부칙이 조문보다 많아진다
ADDENDA_MAX_CHARS = 6000  # 부칙 1건 텍스트 상한 — '다른 법률의 개정' 나열이 수만 자에 이른다
ROOT = Path(__file__).parent
# PDF 추출본 판별 — 단어 중간에 줄바꿈이 들어간 청크.
#
# 단순히 '한글\n한글'로 잡으면 API 적재본도 30~40%가 걸린다. API 본문에도 줄바꿈이
# 있지만 그것은 항·호·조문 사이의 구조 경계이기 때문이다
# (예: "1. 기획예산처차관\n제9조제3항제2호 중 …" — '관\n제'가 매칭된다).
# 개행 뒤가 구조 표지(제N조/①~⑮/1./가./부칙/별표/별지/서식/괄호)로 시작하면 정상으로 본다.
# 이 규칙으로 API본 0~16% / PDF본 94%로 갈린다(전파법·전파법 시행령·부담금관리 기본법 실측).
BROKEN_RE = re.compile(
    r'[가-힣]\n'
    r'(?!제\s*\d)'          # 제N조·제N항
    r'(?![①-⑮])'           # 항 기호
    r'(?!\d+\s*\.)'         # 1.
    r'(?![가-하]\s*\.)'      # 가.
    r'(?!부칙|별표|별지|서식)'
    r'(?![<\[(])'
    r'[가-힣]'
)


# ── 조문 취득 ─────────────────────────────────────────────

def _txt(v):
    """법제처 API는 같은 필드를 문자열/리스트 어느 쪽으로도 반환한다(조문·항·호 모두).
    한쪽만 가정하면 일부 법령에서 'list' object has no attribute 'strip'로 죽는다."""
    if v is None:
        return ''
    if isinstance(v, (list, tuple)):
        return "\n".join(x for x in (_txt(i) for i in v) if x)
    return str(v).strip()


def fetch_law_articles(mst: str, ef_date: str = None):
    """법령 → [(article_no, text)] + 기본정보.

    ef_date를 주면 시행일법령(target=eflaw)의 해당 시행일 통합본을 받는다.
    같은 MST가 시행일별로 다른 통합본을 갖는 경우가 있어(정보통신망법 MST 285199 →
    20261001 179조 / 20270401 180조) MST만으로는 특정되지 않는다. eflaw는 efYd가
    없으면 빈 응답을 주므로 반드시 함께 넘겨야 한다.
    """
    params = {'OC': OC_KEY, 'type': 'JSON', 'MST': mst}
    params.update({'target': 'eflaw', 'efYd': ef_date} if ef_date else {'target': 'law'})
    r = requests.get(DRF_SERVICE, params=params, timeout=60)
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
    return out + _addenda(d) + _tables(d), basic


def _addenda(body):
    """부칙(附則) → [(article_no, text)].

    시행일·경과조치·적용례·다른 법률의 개정이 전부 부칙에 있다. 조문만 담고 부칙을
    빠뜨리면 "언제부터 누구에게 적용되나"를 답할 근거가 사라진다(재적재 1차에서
    9건 중 8건의 부칙이 통째로 누락됐던 사고). 오래된 부칙의 경과조치도 여전히
    유효한 경우가 있으므로 전부 담는다.

    응답 모양이 두 가지다 — 법령은 부칙단위[{내용,번호,일자}], 행정규칙은
    {부칙내용:[...], 부칙공포번호:[...], 부칙공포일자:[...]} 병렬 배열.
    """
    bu = body.get('부칙') or {}
    if not isinstance(bu, dict):
        return []
    units = bu.get('부칙단위')
    rows = []
    if units:
        if isinstance(units, dict):
            units = [units]
        for u in units:
            if isinstance(u, dict):
                rows.append((_txt(u.get('부칙내용')), _txt(u.get('부칙공포번호')),
                             _txt(u.get('부칙공포일자'))))
    else:
        conts = bu.get('부칙내용') or []
        if isinstance(conts, str):
            conts = [conts]
        nos = bu.get('부칙공포번호') or []
        dts = bu.get('부칙공포일자') or []
        if isinstance(nos, str):
            nos = [nos]
        if isinstance(dts, str):
            dts = [dts]
        for i, c in enumerate(conts):
            rows.append((_txt(c), _txt(nos[i]) if i < len(nos) else '',
                         _txt(dts[i]) if i < len(dts) else ''))

    out = []
    for idx, (text, no, dt) in enumerate(rows):
        text = text.strip()
        if len(text) < 10:
            continue
        # '다른 법률의 개정' 부칙은 수백 개 법률을 나열해 한 건이 수만 자에 이른다
        # (정부조직법을 전부 담았더니 부칙만 1,131청크가 됐다). 자문 가치가 낮은
        # 뒷부분을 잘라낸다 — 시행일·경과조치·적용례는 부칙 앞머리에 있다.
        if len(text) > ADDENDA_MAX_CHARS:
            text = text[:ADDENDA_MAX_CHARS] + '\n…(이하 「다른 법률의 개정」 등 생략 — 원문은 국가법령정보센터 참조)'
        label = '부칙' + (f' 제{no}호' if no else '') + (f'({dt})' if dt else '')
        if not no and not dt:
            label = f'부칙 #{idx + 1}'          # 번호·날짜가 모두 없으면 순번으로 구분
        out.append((label, text, dt, idx))

    # 최근 부칙 우선. 오래된 개편 부칙까지 전부 담으면 조문보다 부칙이 많아져
    # 검색이 옛 경과조치로 오염된다. 필요하면 구 PDF본(superseded)이나 원문을 본다.
    # 공포일자가 없는 행은 API 원순서상 '뒤쪽 = 최신'이므로 원래 인덱스를 보조키로 쓴다
    # — 빈 문자열 키로 두면 항상 맨 뒤로 밀려 최신 부칙(현행 시행일 포함)이 먼저 잘린다.
    out.sort(key=lambda x: (x[2] or '', x[3]), reverse=True)
    return [(lbl, txt) for lbl, txt, _, _ in out[:ADDENDA_KEEP]]


def _tables(body):
    """별표·별지·서식 → [(article_no, text)].

    법제처 API는 별표를 준다 — 법령·행정규칙 모두 응답의 '별표.별표단위'에 표 본문까지
    들어 있다(전파법 시행령 43건, 적합성평가 고시 30건). 처음에 이걸 읽지 않아
    "API는 별표를 주지 않는다"고 잘못 판단했고, 그 전제로 고시·시행령의 재적재를
    포기했었다. 별표가 실질인 문서(적합성평가 고시·행정처분기준 등)에서는
    이 부분이 본문보다 중요하다.
    """
    byl = body.get('별표') or {}
    if not isinstance(byl, dict):
        return []
    units = byl.get('별표단위') or []
    if isinstance(units, dict):
        units = [units]
    out = []
    for u in units:
        if not isinstance(u, dict):
            continue
        text = _txt(u.get('별표내용'))
        if len(text.strip()) < 10:
            continue
        kind = _txt(u.get('별표구분')) or '별표'
        no = (_txt(u.get('별표번호')) or '').lstrip('0') or '?'
        br = (_txt(u.get('별표가지번호')) or '').lstrip('0')
        title = _txt(u.get('별표제목'))
        label = f"{kind} {no}" + (f"의{br}" if br else "") + (f"({title})" if title else "")
        out.append((label, text))
    return out


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
    return out + _addenda(d[top]) + _tables(d[top]), basic


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


def _law_type_label(meta, basic):
    """문서명 괄호에 넣을 법종 표기.

    법제처 '법령구분명'은 부령을 그냥 "부령"으로 준다. 그대로 쓰면
    '전파법 시행규칙(과학기술정보통신부령)' 이 '(부령)' 으로 바뀌어 같은 법령이
    두 문서로 갈라진다(실제로 4건 발생). 기존 문서명의 괄호 전체가 API 표기로
    끝나면(= 소관부처 접두만 더 있는 형태) 기존 표기를 유지한다.
    """
    api = (basic.get('법령구분명') or '').strip()
    full = (meta.get('law_type_full') or '').strip()
    if full and api and full.endswith(api) and len(full) > len(api):
        return full
    return api or full or meta.get('law_type_token')


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
        type_token = _law_type_label(meta, basic)
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
        # 신본이 이미 있어도 그냥 건너뛰면 안 된다 — 앞선 실행이 '삽입 성공 → 강등 실패'로
        # 죽었을 수 있고, 그때 구본이 current로 영영 남는다(재진입 구멍). 상태만 정리한다.
        stale = [d for d, v in existing.items()
                 if d != new_doc and v.get('status') == 'current']
        if not stale:
            print("  → 이미 등재된 버전입니다. 건너뜀")
            return False
        print(f"  → 신본은 이미 등재됨. 앞선 실행이 남긴 current 구본 {len(stale)}건만 정리")
        if args.dry_run:
            print("  [dry-run] DB 변경 없음")
            return True
        today0 = datetime.now().strftime('%Y%m%d')
        for old_doc in stale:
            st = 'pending' if (existing[old_doc].get('enf') or '') > today0 else 'superseded'
            _update_doc_chunks(sb, old_doc, {'status': st})
            print(f"  ✓ {st}: {old_doc[:64]}")
        now0 = datetime.now(timezone.utc).isoformat()
        sb.table('law_watch').upsert({
            'doc_name': new_doc, 'law_name': law_name,
            'law_type_token': meta['law_type_token'], 'api_target': target,
            'law_id': law_id, 'registered_mst': mst,
            'registered_law_no': law_no, 'registered_enf': enf,
            'latest_mst': mst, 'latest_law_no': law_no, 'latest_enf': enf,
            'watch_status': 'watching', 'sync_status': 'current',
            'last_checked_at': now0, 'updated_at': now0,
            'note': f'재진입 상태 정리 ({datetime.now():%Y-%m-%d})',
        }, on_conflict='doc_name').execute()
        if doc_name != new_doc:
            sb.table('law_watch').delete().eq('doc_name', doc_name).execute()
        return True

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
    # 삽입 검증 — 부분 삽입이 '완료'로 위장되는 것을 막는다(reingest_one과 동일 가드)
    got = ((sb.table('document_chunks').select('id', count='exact')
            .eq('doc_name', new_doc).limit(1).execute()).count) or 0
    if got != len(payload):
        raise RuntimeError(f"삽입 검증 실패: {len(payload)}청크 중 {got}청크만 확인 — 재실행 필요")
    print(f"  ✓ 신규 등재 {len(payload)}청크 (검증 완료)")

    # ② 기존 버전 상태 정리 — 시행일이 미래면 pending(시행예정본), 과거면 superseded
    #    대형 문서 단문 UPDATE는 timeout(57014)이 나므로 배치 헬퍼 사용
    today = datetime.now().strftime('%Y%m%d')
    pend, sup = [], []
    for old_doc, info in existing.items():
        st = 'pending' if (info['enf'] or '') > today else 'superseded'
        _update_doc_chunks(sb, old_doc, {'status': st})
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
            _delete_doc_chunks(sb, old_doc)
            print(f"  ✓ 보존 상한 초과 삭제: {old_doc[:60]} ({info['count']}청크)")

    # ③-b 교체 이력 기록 — law_diff_gen이 (구본 → 신본) 조문 DIFF를 만들 근거 (2026-09-01)
    #  왜 필요한가: doc_name에 법령번호·시행일이 박혀 있어 교체 후엔 구·신 문서명이 서로 다르고,
    #  law_watch 행은 새 문서명으로 이관되며 구 행은 지워진다(아래 ④). 즉 이 함수를 벗어나면
    #  "무엇이 무엇으로 바뀌었는지"를 아는 곳이 어디에도 남지 않는다.
    #  law_pending을 그대로 쓰는 이유: (watch_doc_name=기준본, doc_name=새 판) 짝이 이미
    #  이 표의 구조이고, law_diff_gen의 시행예정 경로가 같은 컬럼을 읽는다 — 표를 새로 만들면
    #  같은 일을 두 벌로 하게 된다. sync_state에 CHECK 제약은 없음(2026-09-01 확인, #65 계열 점검).
    if sup:
        base_doc = max(sup, key=lambda d: (existing[d].get('enf') or ''))   # 가장 최근 구본
        sb.table('law_pending').upsert({
            'law_name': law_name, 'law_id': law_id or None,
            'law_type_token': meta['law_type_token'], 'api_target': target,
            'watch_doc_name': base_doc, 'doc_name': new_doc,
            'mst': mst, 'law_no': law_no, 'enf_date': enf,
            'sync_state': 'replaced', 'loaded_at': now, 'updated_at': now,
            'note': f'--all-outdated 자동 교체 ({datetime.now():%Y-%m-%d})',
        }, on_conflict='law_name,mst,enf_date', ignore_duplicates=False).execute()
        print(f"  ✓ 교체 이력 기록 (DIFF 대상): {base_doc[:48]} → {new_doc[:48]}")

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


# ── 시행예정본 적재·승격 ──────────────────────────────────

def load_pending_one(sb, row, args):
    """law_pending 1건 → 조문 취득 후 status='pending'으로 등재.

    현행본을 건드리지 않는다(자문은 only_current=true라 pending은 검색에서 제외된다).
    시행일이 도래하면 promote_due()가 current로 올린다.
    """
    law_name, target = row['law_name'], row.get('api_target') or 'law'
    mst, enf, law_no = row['mst'], row['enf_date'], row.get('law_no')
    print(f"\n▶ [시행예정] {law_name}  {law_no}({enf} 시행) mst={mst}")

    if target == 'law':
        articles, basic = fetch_law_articles(mst, ef_date=enf)
        type_token = basic.get('법령구분명') or row.get('law_type_token') or '법률'
        org, law_id = None, str(basic.get('법령ID') or row.get('law_id') or '')
    else:
        articles, basic = fetch_admrul_articles(mst)
        type_token = basic.get('행정규칙종류') or row.get('law_type_token') or '고시'
        org = basic.get('소관부처명') or ''
        law_id = str(basic.get('행정규칙ID') or row.get('law_id') or '')

    chunks = chunk_articles(articles)
    if not chunks:
        print("  ! 조문 취득 결과가 비어 있음 — 건너뜀")
        return False

    new_doc = build_doc_name(law_name, type_token, law_no, enf, org, target)
    print(f"  문서명: {new_doc}\n  조문 {len(articles)}개 → 청크 {len(chunks)}개")

    # 같은 판이 이미 등재돼 있으면(대부분 운영자가 PDF로 미리 올려둔 시행예정본) 새로 넣지 않는다.
    # PDF 경로로 올린 문서는 doc_name 끝에 '.pdf'가 붙고 별표까지 포함돼 API본보다 내용이 많다.
    dup = (sb.table('document_chunks').select('doc_name')
           .in_('doc_name', [new_doc, new_doc + '.pdf']).limit(1).execute().data) or []
    if dup:
        existing_doc = dup[0]['doc_name']
        print(f"  → 이미 등재됨({existing_doc[:64]}). 상태만 연결")
        if not args.dry_run:
            sb.table('law_pending').update({
                'doc_name': existing_doc, 'sync_state': 'loaded',
                'loaded_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', row['id']).execute()
        return False
    if args.dry_run:
        print("  [dry-run] DB 변경 없음")
        return True

    category = '법령' if target == 'law' else '고시'
    payload = [{
        'doc_name': new_doc, 'doc_category': category, 'chunk_index': i,
        'content': c['content'], 'article_no': c['article_no'],
        'effective_date': enf, 'notice_no': (law_no if target != 'law' else None),
        'law_id': law_id, 'law_mst': mst, 'status': 'pending',
        'is_approved': True,
    } for i, c in enumerate(chunks)]
    for i in range(0, len(payload), 50):
        sb.table('document_chunks').insert(payload[i:i + 50]).execute()
    print(f"  ✓ 시행예정본 등재 {len(payload)}청크 (status=pending — 자문 검색 제외)")

    now = datetime.now(timezone.utc).isoformat()
    sb.table('law_pending').update({
        'doc_name': new_doc, 'law_id': law_id or None, 'sync_state': 'loaded',
        'loaded_at': now, 'updated_at': now,
    }).eq('id', row['id']).execute()
    return True


def promote_due(sb, dry_run=False):
    """시행일이 도래한 pending을 current로 승격하고 직전 current를 superseded로 내린다.

    이게 없으면 시행일이 지나도 자문은 옛 조문을 계속 현행으로 답한다.
    같은 법령에 여러 건이 걸려 있으면 시행일 순으로 올려 마지막 것만 current로 남긴다.
    """
    today = datetime.now().strftime('%Y%m%d')
    rows = (sb.table('law_pending').select('*')
            .eq('sync_state', 'loaded').lte('enf_date', today)
            .order('enf_date').execute().data) or []
    if not rows:
        print("승격 대상 없음(시행일 도래한 시행예정본 없음)")
        return 0

    print(f"=== 시행일 도래 {len(rows)}건 승격 (dry-run={dry_run}) ===")
    done = 0
    for r in rows:
        doc, law_name = r.get('doc_name'), r['law_name']
        if not doc:
            print(f"  ! {law_name}: doc_name 없음(미적재) — 건너뜀")
            continue
        print(f"  ▶ {law_name}: {r.get('law_no')} ({r['enf_date']} 시행) → current")
        if dry_run:
            done += 1
            continue
        now = datetime.now(timezone.utc).isoformat()
        # ① 승격을 먼저 한다. 강등을 먼저 하면 승격 UPDATE가 timeout으로 죽었을 때
        #    그 법령의 current 청크가 0이 된다(reingest에서 실제 발생한 사고와 동일 모드).
        #    잠깐 current가 두 벌 공존하는 쪽이 0벌보다 낫다. 대형 문서 대비 배치 UPDATE.
        existing = fetch_existing(sb, law_name)
        _update_doc_chunks(sb, doc, {'status': 'current'})
        # ② 직전 current를 superseded로 (승격본 자신은 제외)
        for old_doc, info in existing.items():
            if old_doc == doc or info.get('status') != 'current':
                continue
            _update_doc_chunks(sb, old_doc, {'status': 'superseded'})
            sb.table('law_watch').delete().eq('doc_name', old_doc).execute()
            print(f"      구버전 → superseded: {old_doc[:64]}")
        sb.table('law_pending').update({
            'sync_state': 'promoted', 'promoted_at': now, 'updated_at': now,
        }).eq('id', r['id']).execute()
        # ③ law_watch에 현행본으로 등록 — 다음 감시부터 이 문서가 기준이 된다
        sb.table('law_watch').upsert({
            'doc_name': doc, 'law_name': law_name,
            'law_type_token': r.get('law_type_token'), 'api_target': r.get('api_target') or 'law',
            'law_id': r.get('law_id'), 'registered_mst': r['mst'],
            'registered_law_no': r.get('law_no'), 'registered_enf': r['enf_date'],
            'latest_mst': r['mst'], 'latest_law_no': r.get('law_no'), 'latest_enf': r['enf_date'],
            'watch_status': 'watching', 'sync_status': 'current',
            'last_checked_at': now, 'updated_at': now,
            'note': f'시행일 도래 자동 승격 ({datetime.now():%Y-%m-%d})',
        }, on_conflict='doc_name').execute()
        done += 1
    print(f"=== 승격 완료: {done}건 ===")
    return done


# ── PDF 등재본의 API 재적재 ────────────────────────────────

def _delete_doc_chunks(sb, doc_name):
    """청크 삭제를 배치로. 800청크가 넘는 문서를 한 번에 지우면 statement timeout(57014)이
    나고, 그 경우 삭제는 롤백되지만 스크립트는 실패로 끝난다(지방세법 860청크에서 발생)."""
    while True:
        ids = [r['id'] for r in ((sb.table('document_chunks').select('id')
                                  .eq('doc_name', doc_name).limit(100).execute().data) or [])]
        if not ids:
            return
        sb.table('document_chunks').delete().in_('id', ids).execute()


def _damaged_docs(sb, min_broken=30):
    """손상률(단어 중간 줄바꿈 비율)이 기준 이상인 현행 등재본 — 재적재 대상.
    문서명 정렬로 고정 순서를 보장해 --shard 분할이 프로세스 간 겹치지 않게 한다."""
    watch = {r['doc_name'] for r in ((sb.table('law_watch')
             .select('doc_name, watch_status, sync_status').execute().data) or [])
             if r.get('watch_status') == 'watching' and r.get('sync_status') == 'current'}
    stats, start = {}, 0
    while True:
        rows = (sb.table('document_chunks').select('doc_name, content')
                .eq('status', 'current').order('id').range(start, start + 999).execute().data) or []
        for r in rows:
            if r['doc_name'] not in watch:
                continue
            t, b = stats.get(r['doc_name'], (0, 0))
            stats[r['doc_name']] = (t + 1, b + (1 if BROKEN_RE.search(r['content'] or '') else 0))
        if len(rows) < 1000:
            break
        start += 1000
    return sorted(d for d, (t, b) in stats.items() if t and b * 100 >= t * min_broken)


def _update_doc_chunks(sb, doc_name, patch):
    """대량 UPDATE도 배치로. 지방세법(860청크)을 한 번에 갱신하면 statement timeout(57014).

    id 커서로 페이지네이션한다. 커서 없이 limit만 걸고 '이미 처리한 id'를 메모리에서
    제외하면, 같은 200행이 계속 조회되다 빈 목록이 되어 조용히 절반만 갱신된다.
    """
    last = 0
    while True:
        rows = (sb.table('document_chunks').select('id')
                .eq('doc_name', doc_name).gt('id', last)
                .order('id').limit(100).execute().data) or []
        if not rows:
            return
        ids = [r['id'] for r in rows]
        sb.table('document_chunks').update(patch).in_('id', ids).execute()
        # doc_name을 바꾸면 갱신된 행은 필터에서 빠지므로 커서를 되감아도 무한루프가 없다
        last = 0 if 'doc_name' in patch else ids[-1]


DAMAGE_SAMPLE = 300


def _pdf_damage(sb, doc_name):
    """(전체 청크, 단어중간 줄바꿈 청크 추정, 별표 표로 보이는 청크) — 재적재 판단 근거.

    손상률은 판정용 휴리스틱이라 전량을 읽을 필요가 없다. 1,230청크짜리 문서의 본문을
    통째로 끌어오다 statement timeout(57014)이 반복해서 났다 — 앞 300청크만 표본으로
    보고 비율을 전체로 환산한다.
    """
    rows = (sb.table('document_chunks').select('content')
            .eq('doc_name', doc_name).eq('status', 'current')
            .order('chunk_index').limit(DAMAGE_SAMPLE).execute().data) or []
    total = ((sb.table('document_chunks').select('id', count='exact')
              .eq('doc_name', doc_name).eq('status', 'current')
              .limit(1).execute()).count) or len(rows)
    n = len(rows) or 1
    broken = round(sum(1 for x in rows if BROKEN_RE.search(x['content'] or '')) * total / n)
    table = sum(1 for x in rows if re.search(r'위반횟수별|행정처분기준|과태료의 부과기준|1차 위반', x['content'] or ''))  # 참고용 지표(판정에는 미사용)
    return total, broken, table


def reingest_one(sb, doc_name, args):
    """PDF에서 추출해 등재한 현행본을 법제처 API 조문으로 교체.

    왜: PDF 추출본은 단어 중간에 줄바꿈이 들어가 키워드 검색이 깨진다(전파법은 197청크
    중 188청크가 그 상태라 '가격경쟁'이 '가격\\n경쟁'으로 잘려 검색에 안 걸린다).
    조문 단위 청킹이 아니라 800자 단위라 article_no도 부정확하고 law_id도 비어 있다.

    API가 조문+부칙+별표를 모두 주므로(응답 '별표.별표단위'에 표 본문 포함) 재적재로
    잃는 내용은 없다. 구본은 삭제하지 않고 superseded로 보존해 되돌릴 수 있게 한다.
    """
    meta = parse_doc_name(doc_name)
    if not meta:
        print(f"  ! 문서명 파싱 실패: {doc_name[:60]}")
        return False
    target = api_target_of(meta['law_type_token'])
    total, broken, table = _pdf_damage(sb, doc_name)
    print(f"\n▶ [재적재] {meta['law_name']}  ({total}청크, 손상 {broken}, 별표표 {table})")

    # 앞선 시도가 '개명 → 삽입 → 검증 실패'로 죽으면 접미 붙은 구본이 current로 남는다.
    # 그 상태에서 손상률만 보면 부분 삽입된 API 청크 때문에 "이미 API본"으로 오판하고
    # 건너뛰어 사고가 고착된다 — 접미 잔존을 먼저 탐지해 무조건 재처리 경로로 태운다.
    leftover = []
    for suf in (' [교체중]', ' [PDF원본]'):
        n = ((sb.table('document_chunks').select('id', count='exact')
              .eq('doc_name', doc_name + suf).eq('status', 'current')
              .limit(1).execute()).count) or 0
        if n:
            leftover.append((doc_name + suf, n))
    if leftover:
        print(f"  ⚠ 이전 실패의 잔존 감지: " +
              ", ".join(f"{d[-20:]}({n}청크)" for d, n in leftover) + " — 복구 재처리")

    # API 적재본도 항·호 줄바꿈 때문에 손상 검출기가 몇 %는 잡는다(정보통신망법 211청크 중 9).
    # 기준은 --min-broken(기본 30%). 잔존 복구 중이면 이 스킵을 타지 않는다.
    min_broken = getattr(args, 'min_broken', 30) or 30
    if total and broken * 100 < total * min_broken and not args.force and not leftover:
        print(f"  → 손상률 {round(broken*100/total)}% — 이미 API 적재본으로 판단. 건너뜀(--force로 재취득)")
        return False

    rows = drf_law_search(meta['law_name'], target) or []
    hit = pick_exact(rows, meta['law_name'], meta.get('full_name'))
    if not hit:
        for alt in (alias_variants(meta['law_name']) or []):
            rows = drf_law_search(alt, target) or []
            hit = pick_exact(rows, meta['law_name'], meta.get('full_name'))
            if hit:
                break
    if not hit:
        print("  ! 법제처에서 현행본을 찾지 못함 — 건너뜀")
        return False

    mst, law_no, enf = row_fields(hit, target)
    if norm_law_no(law_no) != norm_law_no(meta['law_no']):
        print(f"  ! 등재본({meta['law_no']})과 법제처 현행({law_no})이 다름 — 재적재가 아니라 "
              f"--all-outdated 대상. 건너뜀")
        return False

    if target == 'law':
        articles, basic = fetch_law_articles(mst)
        type_token = _law_type_label(meta, basic)
        org, law_id = None, str(hit.get('법령ID') or '')
    else:
        articles, basic = fetch_admrul_articles(mst)
        type_token = basic.get('행정규칙종류') or meta['law_type_token']
        org = basic.get('소관부처명') or hit.get('소관부처명') or ''
        law_id = str(hit.get('행정규칙ID') or '')

    chunks = chunk_articles(articles)
    if not chunks:
        print("  ! 조문 취득 결과가 비어 있음 — 중단")
        return False

    new_doc = build_doc_name(meta['law_name'], type_token, law_no, enf, org, target)
    print(f"  조문 {len(articles)}개 → 청크 {len(chunks)}개 (PDF본 {total}청크 대체)")
    print(f"  신규 문서명: {new_doc}")
    if args.dry_run:
        print("  [dry-run] DB 변경 없음")
        return True

    now = datetime.now(timezone.utc).isoformat()
    prev = ((sb.table('document_chunks').select('doc_category, law_id')
             .eq('doc_name', doc_name).limit(1).execute().data) or [{}])[0]
    category = prev.get('doc_category') or ('법령' if target == 'law' else '고시')
    already_api = bool(prev.get('law_id'))

    # ⚠ 순서가 중요하다. 구본을 먼저 내리고 신본을 넣으면, 삽입이 중간에 실패했을 때
    # (statement timeout 등) 그 법령의 현행 청크가 0이 되어 자문에서 통째로 사라진다.
    # 실제로 병렬 재적재 중 3건이 그 상태가 됐다. 신본을 먼저 넣고 성공한 뒤에 구본을 내린다.
    old_doc = doc_name
    if leftover:
        # 앞선 시도가 이미 구본을 접미로 옮겨뒀다. 지금 doc_name 아래 남은 것은 그때
        # 부분 삽입된 API 잔해이므로 지우고, 접미본을 구본으로 삼는다. already_api도
        # doc_name의 잔해가 아니라 접미로 판정해야 한다 — 잔해 기준으로 True가 되면
        # 마지막 단계에서 [PDF원본]을 삭제해 버린다.
        _delete_doc_chunks(sb, doc_name)
        pdfs = [d for d, _ in leftover if d.endswith(' [PDF원본]')]
        for d, _ in leftover:
            if pdfs and d.endswith(' [교체중]'):     # PDF원본이 있으면 교체중은 그 자체가 잔해
                _delete_doc_chunks(sb, d)
        old_doc = pdfs[0] if pdfs else leftover[0][0]
        already_api = old_doc.endswith(' [교체중]')
        print(f"  ✓ 부분 삽입 잔해 제거 — 구본: …{old_doc[-24:]}")
    elif new_doc == doc_name:
        # 문서명이 같으면 이름이 충돌하므로 구본을 먼저 옮겨야 한다. 다만 status는
        # 그대로 current로 두어, 삽입이 실패해도 검색 공백이 생기지 않게 한다.
        # (already_api면 어차피 뒤에서 지울 것이라 접미는 임시 표식일 뿐이다)
        old_doc = doc_name + (' [교체중]' if already_api else ' [PDF원본]')
        _update_doc_chunks(sb, doc_name, {'doc_name': old_doc})

    # 멱등성 — 앞선 시도가 삽입까지는 성공하고 뒤 단계에서 죽었을 수 있다. 그대로 다시
    # 넣으면 같은 chunk_index가 여러 벌 쌓인다(재시도 3회에 5배 중복이 생겼다).
    dup = ((sb.table('document_chunks').select('id', count='exact')
            .eq('doc_name', new_doc).limit(1).execute()).count) or 0
    if dup:
        print(f"  · 이전 시도의 잔여 {dup}청크 발견 → 삭제 후 재삽입")
        _delete_doc_chunks(sb, new_doc)

    payload = [{
        'doc_name': new_doc, 'doc_category': category, 'chunk_index': i,
        'content': c['content'], 'article_no': c['article_no'],
        'effective_date': enf, 'notice_no': (law_no if target != 'law' else None),
        'law_id': law_id, 'law_mst': mst, 'status': 'current', 'is_approved': True,
    } for i, c in enumerate(chunks)]
    for i in range(0, len(payload), 50):
        sb.table('document_chunks').insert(payload[i:i + 50]).execute()

    # 삽입 검증 — 배치 중간에 statement timeout이 나면 앞부분만 들어가고 예외가 나는데,
    # 예외를 삼키는 상위 루프가 있으면 "부분 삽재"가 완료로 위장된다. 실제로 대한민국
    # 주파수 분배표가 1,089청크 중 150청크(배치 3개)만 들어간 채 방치돼 있었고,
    # 이미 law_id가 있어 이후 재적재 대상에서도 빠져 아무도 알아채지 못했다.
    got = ((sb.table('document_chunks').select('id', count='exact')
            .eq('doc_name', new_doc).limit(1).execute()).count) or 0
    if got != len(payload):
        raise RuntimeError(f"삽입 검증 실패: {len(payload)}청크를 넣었는데 {got}청크만 확인됨 "
                           f"— 부분 삽입 상태이므로 재실행 필요 ({new_doc[:50]})")
    print(f"  ✓ API본 등재 {len(payload)}청크 (검증 완료)")

    # 신본 등재가 끝난 뒤에야 구본을 내린다(위 주석의 순서 이유).
    if already_api:
        _delete_doc_chunks(sb, old_doc)
        print(f"  ✓ 기존 API본 {total}청크 삭제(내용 교체)")
    else:
        _update_doc_chunks(sb, old_doc, {'status': 'superseded'})
        print(f"  ✓ 구 PDF본 → superseded: {old_doc[:66]}")

    sb.table('law_watch').upsert({
        'doc_name': new_doc, 'law_name': meta['law_name'],
        'law_type_token': meta['law_type_token'], 'api_target': target,
        'law_id': law_id, 'registered_mst': mst,
        'registered_law_no': law_no, 'registered_enf': enf,
        'latest_mst': mst, 'latest_law_no': law_no, 'latest_enf': enf,
        'watch_status': 'watching', 'sync_status': 'current',
        'last_checked_at': now, 'updated_at': now,
        'note': f'PDF본 → API 재적재 ({datetime.now():%Y-%m-%d})',
    }, on_conflict='doc_name').execute()
    if doc_name != new_doc:
        sb.table('law_watch').delete().eq('doc_name', doc_name).execute()
    # 시행예정본이 이 문서를 가리키고 있으면 새 문서명으로 이관
    sb.table('law_pending').update({'watch_doc_name': new_doc, 'updated_at': now}) \
        .eq('watch_doc_name', doc_name).execute()
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--doc-name', help='현행화할 등재 문서명(부분 일치 허용)')
    ap.add_argument('--all-outdated', action='store_true', help='outdated 전체 처리')
    ap.add_argument('--list', action='store_true', help='대상 목록만 출력')
    ap.add_argument('--keep-old', action='store_true', help='구버전 삭제 없이 superseded로만')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-backfill', action='store_true', help='임베딩 백필 생략')
    ap.add_argument('--pending', action='store_true',
                    help='law_pending의 미적재 시행예정본을 status=pending으로 등재')
    ap.add_argument('--pending-law', help='--pending 대상을 특정 법령명으로 한정')
    ap.add_argument('--promote', action='store_true',
                    help='시행일이 도래한 시행예정본을 current로 승격(매일 자동 실행 대상)')
    ap.add_argument('--reingest', action='store_true',
                    help='PDF 등재본을 법제처 API 조문으로 교체(--doc-name 또는 --reingest-laws)')
    ap.add_argument('--reingest-laws', action='store_true',
                    help='법률(법률 계열) 중 PDF 손상본 전체를 재적재(조문+부칙+별표 취득)')
    ap.add_argument('--force', action='store_true', help='재적재 시 손상률 검사 무시(이미 API본도 재취득)')
    ap.add_argument('--reingest-all', action='store_true',
                    help='법률·시행령·부령·고시 통틀어 PDF 손상본 전체를 재적재')
    ap.add_argument('--shard', help='병렬 분할 실행: "1/6" 형식(1-base). 여러 프로세스로 나눠 돌릴 때')
    ap.add_argument('--min-broken', type=int, default=30, help='재적재 대상 최소 손상률(%%)')
    a = ap.parse_args()

    if not (SB_URL and SB_KEY and OC_KEY):
        print("오류: .env에 SUPABASE_URL, SUPABASE_SERVICE_KEY, LAW_OC_KEY 필요")
        sys.exit(1)
    sb = sb_client.make_client(SB_URL, SB_KEY)

    if a.promote:
        promote_due(sb, a.dry_run)
        return

    if a.reingest or a.reingest_laws or a.reingest_all:
        if a.reingest_all:
            targets = _damaged_docs(sb, a.min_broken)
        elif a.reingest_laws:
            w = (sb.table('law_watch').select('doc_name, law_type_token')
                 .eq('api_target', 'law').eq('watch_status', 'watching')
                 .eq('sync_status', 'current').order('doc_name').execute().data) or []
            targets = [r['doc_name'] for r in w if r.get('law_type_token') == '법률']
        elif a.doc_name:
            w = (sb.table('law_watch').select('doc_name').execute().data) or []
            targets = [r['doc_name'] for r in w if a.doc_name in r['doc_name']]
        else:
            print("오류: --reingest 는 --doc-name 과 함께, 또는 --reingest-laws 를 쓰세요")
            sys.exit(1)
        if a.shard:
            i, n = (int(x) for x in a.shard.split('/'))
            targets = [d for k, d in enumerate(targets) if k % n == (i - 1) % n]
            print(f"샤드 {i}/{n} → {len(targets)}건")
        if not targets:
            print("대상 없음")
            return
        print(f"=== PDF본 → API 재적재: 후보 {len(targets)}건 (dry-run={a.dry_run}) ===")
        done = 0
        for d in targets:
            try:
                if reingest_one(sb, d, a):
                    done += 1
            except Exception as e:
                print(f"  ! 실패({d[:50]}): {str(e)[:140]}")
            time.sleep(0.3)
        print(f"\n=== 완료: {done}/{len(targets)}건 재적재 ===")
        if done and not a.dry_run and not a.no_backfill:
            print("\n[임베딩 백필]")
            subprocess.run([sys.executable, str(ROOT / 'backfill_embeddings.py')], check=False)
            print("\n※ 관계도 인용망 재구축 권장: python build_law_citation_graph.py")
        return

    if a.pending:
        today = datetime.now().strftime('%Y%m%d')
        q = (sb.table('law_pending').select('*')
             .eq('sync_state', 'detected').gt('enf_date', today))
        if a.pending_law:
            q = q.ilike('law_name', f'%{a.pending_law}%')
        rows = (q.order('law_name').order('enf_date').execute().data) or []
        if not rows:
            print("적재할 시행예정본 없음 (law_watch.py를 먼저 실행하세요)")
            return
        print(f"=== 시행예정본 적재: {len(rows)}건 (dry-run={a.dry_run}) ===")
        done = 0
        for r in rows:
            try:
                if load_pending_one(sb, r, a):
                    done += 1
            except Exception as e:
                print(f"  ! 실패({r.get('law_name')} {r.get('enf_date')}): {str(e)[:140]}")
            time.sleep(0.3)
        print(f"\n=== 완료: {done}/{len(rows)}건 등재 ===")
        if done and not a.dry_run and not a.no_backfill:
            print("\n[임베딩 백필]")
            subprocess.run([sys.executable, str(ROOT / 'backfill_embeddings.py')], check=False)
        return

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
