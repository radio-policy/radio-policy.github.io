#!/usr/bin/env python3
"""
법령 관계도: 조문 인용망 자동 추출 → law_graph_nodes / law_graph_edges 적재

- 입력: document_chunks 중 법령·고시 원문 (문서명에 (법률)/(대통령령)/(○○부령)/(○○고시)/(훈령)/(공고)/(예규)/(위원회규칙) 표기가 있는 문서만.
  '기타' 카테고리의 보도자료(.md)와 ITU-R·보도자료·추가지식 카테고리는 자동 제외됨)
- 인용 추출: ① 「법령명」(제N조) 괄호 인용 ② 시행령/시행규칙 본문의 "법 제N조"/"영 제N조" 자기계열 참조
- 계열 엣지: 문서명 구조에서 유도 (X → X 시행령 → X 시행규칙), relation_type='하위법령', source='family'
- 멱등: source in ('citation','family') 엣지만 삭제 후 재구축. 노드는 삭제하지 않음
  (⚠️ 노드를 지우면 cascade로 seed/ai 엣지까지 소실되므로 절대 삭제 금지)

실행(PC, Python 3.12 전체 경로):
  C:\\Users\\SKTelecom\\AppData\\Local\\Programs\\Python\\Python312\\python.exe build_law_citation_graph.py
"""

import os
import re
import sys
from collections import defaultdict

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

from sb_client import make_client

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
sb = make_client(SUPABASE_URL, SUPABASE_KEY)

EXCLUDE_CATEGORIES = ('ITU-R', '보도자료', '추가지식')

# 문서명에서 법종 괄호 표기 탐지: (법률)/(대통령령)/(과학기술정보통신부령)/(○○고시)/(○○훈령)/(○○공고)/(○○예규)/(방송통신위원회규칙)
TYPE_PAREN_RE = re.compile(r'\(([^()]*?(법률|대통령령|총리령|부령|고시|훈령|공고|예규|위원회규칙|연구원규칙))\)')

# 「법령명」 (선택: 제N조) — 조문 속 타 법령 인용의 표준 표기
BRACKET_CITE_RE = re.compile(r'「([^」]{2,45})」(?:\s*(제\d+조(?:의\d+)?))?')

# 시행령·시행규칙 본문의 자기계열 참조
SELF_LAW_RE = re.compile(r'(?<![가-힣])법\s*제(\d+)조(?:의(\d+))?')
SELF_DECREE_RE = re.compile(r'(?<![가-힣])영\s*제(\d+)조(?:의(\d+))?')

# 인용 대상으로 인정하는 명칭 어미 (「」 안의 비법령 인용어 걸러냄 — 예: 「마을 간이무선국」)
CITABLE_SUFFIX_RE = re.compile(r'(법|법률|시행령|시행규칙|규칙|규정|고시|기준|세칙|분배표|협정)$')

# 부칙·개정문 상용구가 기계적으로 인용하는 절차 규정 — 관계도 가치 없음
CITE_BLOCKLIST = {
    '훈령·예규 등의 발령 및 관리에 관한 규정',
}


def norm_name(name: str) -> str:
    """가운뎃점 이형(ㆍ‧•) 통일 + 공백 정리 — 같은 법령의 중복 노드 방지"""
    name = name.replace('ㆍ', '·').replace('‧', '·').replace('•', '·')
    return re.sub(r'\s+', ' ', name).strip()


def node_type_of(base_name: str, type_token: str) -> str:
    if type_token == '법률':
        return 'law'
    if type_token == '대통령령':
        return 'decree'
    if type_token in ('총리령',) or type_token.endswith('부령') or type_token.endswith('위원회규칙') or type_token.endswith('연구원규칙'):
        return 'rules'
    if type_token in ('고시', '공고', '훈령', '예규') or type_token.endswith(('고시', '공고', '훈령', '예규')):
        return 'notice'
    return guess_type_by_name(base_name)


def guess_type_by_name(name: str) -> str:
    if name.endswith('시행령'):
        return 'decree'
    if name.endswith(('시행규칙', '규칙', '세칙')):
        return 'rules'
    if re.search(r'(고시|공고|훈령|예규|지침|기준|규정|분배표|협정)', name):
        return 'notice'
    if name.endswith(('법', '법률')):
        return 'law'
    return 'etc'


def parse_doc_name(doc_name: str):
    """doc_name → (base_name, node_type) 또는 None(법령·고시 원문 아님)"""
    name = re.sub(r'\.(pdf|md)$', '', norm_name(doc_name))
    m = TYPE_PAREN_RE.search(name)
    if not m:
        return None
    base = name[:m.start()].strip()
    # 선두 소관부처 괄호 제거: "(과학기술정보통신부) 방송통신발전기금 운용·관리규정"
    base = re.sub(r'^\([^)]*\)\s*', '', base).strip()
    # 선두 [별첨 N] 등 제거
    base = re.sub(r'^\[[^\]]*\]\s*', '', base).strip()
    if len(base) < 2:
        return None
    return base, node_type_of(base, m.group(2))


def fetch_all_doc_rows():
    """전체 (doc_name, doc_category) 페이지네이션 조회 — PostgREST 기본 1000행 제한 회피"""
    rows = []
    page = 1000
    offset = 0
    while True:
        r = (sb.table('document_chunks')
             .select('doc_name, doc_category')
             .range(offset, offset + page - 1)
             .execute())
        batch = r.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return rows


def fetch_target_docs(all_rows):
    """법령·고시 원문 문서 목록: base_name → {'doc_name': 대표 문서명(최신), 'type': node_type}"""
    seen = {}
    for row in all_rows:
        if row['doc_category'] in EXCLUDE_CATEGORIES:
            continue
        parsed = parse_doc_name(row['doc_name'])
        if not parsed:
            continue
        base, ntype = parsed
        prev = seen.get(base)
        # 같은 base가 여러 버전이면 문서명 사전순 최대(시행일 최신) 채택
        if prev is None or row['doc_name'] > prev['doc_name']:
            seen[base] = {'doc_name': row['doc_name'], 'type': ntype}
    return seen


def fetch_chunks(doc_names):
    """대상 문서들의 청크 본문 (페이지네이션)"""
    chunks = []
    page = 1000
    offset = 0
    names = list(doc_names)
    # in_ 필터는 URL 길이 제한이 있어 이름 50개 단위로 나눠 조회
    for i in range(0, len(names), 50):
        batch = names[i:i + 50]
        offset = 0
        while True:
            r = (sb.table('document_chunks')
                 .select('doc_name, content')
                 .in_('doc_name', batch)
                 .range(offset, offset + page - 1)
                 .execute())
            rows = r.data or []
            chunks.extend(rows)
            if len(rows) < page:
                break
            offset += page
    return chunks


def main():
    print('=== 법령 인용망 추출 시작 ===')
    all_rows = fetch_all_doc_rows()
    print(f'document_chunks 전체 행: {len(all_rows)}건')
    docs = fetch_target_docs(all_rows)
    print(f'법령·고시 원문 문서(정규화 기준): {len(docs)}건')

    base_of_doc = {}   # 실제 doc_name → base
    for base, info in docs.items():
        base_of_doc[info['doc_name']] = base
    # 같은 base의 구버전 doc_name도 매핑 (본문 청크는 버전 무관 전부 파싱)
    all_doc_names = set()
    for row in all_rows:
        if row['doc_category'] in EXCLUDE_CATEGORIES:
            continue
        parsed = parse_doc_name(row['doc_name'])
        if parsed and parsed[0] in docs:
            base_of_doc[row['doc_name']] = parsed[0]
            all_doc_names.add(row['doc_name'])

    chunks = fetch_chunks(all_doc_names)
    print(f'파싱 대상 청크: {len(chunks)}건')

    # ── 인용 추출 ────────────────────────────────────────
    # edge_key = (src_base, dst_name) → {'count': n, 'samples': [조문...]}
    cites = defaultdict(lambda: {'count': 0, 'samples': []})
    cited_names = set()

    for ch in chunks:
        src = base_of_doc.get(ch['doc_name'])
        content = ch.get('content') or ''
        if not src or not content:
            continue

        # ① 「법령명」 인용
        for m in BRACKET_CITE_RE.finditer(content):
            name = norm_name(m.group(1))
            art = m.group(2) or ''
            if not CITABLE_SUFFIX_RE.search(name):
                continue
            if name in CITE_BLOCKLIST:
                continue  # 부칙 상용구 인용 제외
            if name == src:
                continue  # 자기 자신 인용(개정문 등) 제외
            e = cites[(src, name)]
            e['count'] += 1
            if art and art not in e['samples'] and len(e['samples']) < 3:
                e['samples'].append(art)
            cited_names.add(name)

        # ② 자기계열 참조: 시행령/시행규칙 → 본법, 시행규칙 → 시행령
        src_type = docs[src]['type']
        if src.endswith('시행령') or src.endswith('시행규칙'):
            parent_law = re.sub(r'\s*시행(령|규칙)$', '', src).strip()
            n_self = len(SELF_LAW_RE.findall(content))
            if n_self and parent_law and parent_law != src:
                e = cites[(src, parent_law)]
                e['count'] += n_self
                cited_names.add(parent_law)
        if src.endswith('시행규칙'):
            parent_decree = re.sub(r'\s*시행규칙$', ' 시행령', src).strip()
            n_self = len(SELF_DECREE_RE.findall(content))
            if n_self:
                e = cites[(src, parent_decree)]
                e['count'] += n_self
                cited_names.add(parent_decree)

    print(f'인용 엣지(원시): {len(cites)}건, 피인용 명칭: {len(cited_names)}건')

    # ── 계열(상하위법) 엣지: 이름 구조에서 유도 ─────────────
    family_edges = []  # (parent_base, child_base)
    all_bases = set(docs.keys())
    for base in all_bases:
        if base.endswith('시행령'):
            parent = re.sub(r'\s*시행령$', '', base).strip()
            if parent in all_bases:
                family_edges.append((parent, base))
        elif base.endswith('시행규칙'):
            parent_decree = re.sub(r'\s*시행규칙$', ' 시행령', base).strip()
            parent_law = re.sub(r'\s*시행규칙$', '', base).strip()
            if parent_decree in all_bases:
                family_edges.append((parent_decree, base))
            elif parent_law in all_bases:
                family_edges.append((parent_law, base))
    print(f'계열 엣지: {len(family_edges)}건')

    # ── 노드 확보 (기존 노드 재사용, 없으면 생성 — 삭제는 절대 안 함) ──
    existing = {}
    offset = 0
    while True:
        r = sb.table('law_graph_nodes').select('id, name, doc_name').range(offset, offset + 999).execute()
        rows = r.data or []
        for row in rows:
            existing[row['name']] = row
        if len(rows) < 1000:
            break
        offset += 1000

    # 공백 무시 색인 — PDF 추출이 단어 중간에 공백을 끼워 넣어("전 파법") 변형 노드가
    # 양산되는 것을 방지. 같은 nrm이면 doc_name 보유 노드를 정본으로 재사용.
    existing_nrm = {}
    for _nm, _row in existing.items():
        _key = _nm.replace(' ', '')
        _prev = existing_nrm.get(_key)
        if _prev is None or (_row.get('doc_name') and not _prev.get('doc_name')):
            existing_nrm[_key] = _row

    def ensure_node(name, ntype, doc_name=None):
        row = existing.get(name) or existing_nrm.get(name.replace(' ', ''))
        if row:
            patch = {}
            if doc_name and not row.get('doc_name'):
                patch['doc_name'] = doc_name
            # 공백무시로 재사용된 노드가 과거 인용 스텁의 손상된 이름을 그대로 물고 있을 수 있다
            # ("정보통신기반 보호법 시행령"의 인용 스텁이 "정보통신기 반 보호법 시행령"으로 잘못
            # 생성된 뒤, 실제 문서가 들어와도 doc_name만 채워지고 name은 안 고쳐져 영구 오타가 됨).
            # doc_name을 갖고 들어온 쪽(=실제 원문 파싱 결과)이 항상 정본이므로 name도 맞춘다.
            if doc_name and row.get('name') != name:
                patch['name'] = name
            if patch:
                try:
                    sb.table('law_graph_nodes').update(patch).eq('id', row['id']).execute()
                    row.update(patch)
                except Exception:
                    pass
            return row['id']
        ins = sb.table('law_graph_nodes').insert({
            'name': name, 'node_type': ntype, 'doc_name': doc_name, 'source': 'citation'
        }).execute()
        row = ins.data[0]
        existing[name] = row
        existing_nrm[name.replace(' ', '')] = row
        return row['id']

    node_ids = {}
    for base, info in docs.items():
        node_ids[base] = ensure_node(base, info['type'], info['doc_name'])
    for name in cited_names:
        if name not in node_ids:
            node_ids[name] = ensure_node(name, guess_type_by_name(name))
    print(f'노드 확보: {len(node_ids)}건 (전체 노드 {len(existing)}건)')

    # ── 기존 citation/family 엣지 삭제 후 재구축 (멱등) ──
    sb.table('law_graph_edges').delete().in_('source', ['citation', 'family']).execute()

    inserted = 0
    batch = []

    def flush():
        nonlocal inserted, batch
        if batch:
            sb.table('law_graph_edges').insert(batch).execute()
            inserted += len(batch)
            batch = []

    seen_pairs = set()
    for (src, dst), info in cites.items():
        if src not in node_ids or dst not in node_ids:
            continue
        sid, did = node_ids[src], node_ids[dst]
        if sid == did or (sid, did, '인용') in seen_pairs:
            continue
        seen_pairs.add((sid, did, '인용'))
        desc = f"조문 인용 {info['count']}회"
        if info['samples']:
            desc += ' — 예: ' + ', '.join(info['samples'])
        batch.append({'source_id': sid, 'target_id': did, 'relation_type': '인용',
                      'description': desc, 'source': 'citation',
                      'weight': min(info['count'], 60)})
        if len(batch) >= 200:
            flush()
    flush()

    for parent, child in family_edges:
        sid, did = node_ids.get(parent), node_ids.get(child)
        if not sid or not did or (sid, did, '하위법령') in seen_pairs:
            continue
        seen_pairs.add((sid, did, '하위법령'))
        batch.append({'source_id': sid, 'target_id': did, 'relation_type': '하위법령',
                      'description': '위임 하위법령', 'source': 'family', 'weight': 3})
        if len(batch) >= 200:
            flush()
    flush()

    print(f'엣지 적재: {inserted}건 (citation+family 재구축 완료)')

    # ── 고아 노드 정리: source='citation'이고 어떤 엣지에도 안 쓰이는 노드만 삭제 ──
    # (seed/ai 노드는 절대 건드리지 않음. 엣지 0개인 노드라 cascade 영향도 없음)
    used_ids = set()
    offset = 0
    while True:
        er = sb.table('law_graph_edges').select('source_id, target_id').range(offset, offset + 999).execute()
        rows = er.data or []
        for row in rows:
            used_ids.add(row['source_id'])
            used_ids.add(row['target_id'])
        if len(rows) < 1000:
            break
        offset += 1000
    orphans = [row['id'] for name, row in existing.items()
               if row['id'] not in used_ids and name not in docs]
    # citation 출처 노드만 삭제 대상으로 재확인
    deleted = 0
    for i in range(0, len(orphans), 100):
        batch_ids = orphans[i:i + 100]
        dr = (sb.table('law_graph_nodes').delete()
              .in_('id', batch_ids).eq('source', 'citation').execute())
        deleted += len(dr.data or [])
    print(f'고아 citation 노드 정리: {deleted}건 삭제')
    print('=== 완료 ===')


if __name__ == '__main__':
    main()
