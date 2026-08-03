#!/usr/bin/env python3
"""
법령 관계도: 조문 인용망 자동 추출 → law_graph_nodes / law_graph_edges 적재

- 입력: document_chunks 중 법령·고시 원문 (문서명에 (법률)/(대통령령)/(○○부령)/(○○고시)/(훈령)/(공고)/(예규)/(위원회규칙) 표기가 있는 문서만.
  '기타' 카테고리의 보도자료(.md)와 ITU-R·보도자료·추가지식 카테고리는 자동 제외됨)
- 인용 추출: ① 「법령명」(제N조) 괄호 인용 ② 시행령/시행규칙 본문의 "법 제N조"/"영 제N조" 자기계열 참조
- 계열 엣지: 문서명 구조에서 유도 (X → X 시행령 → X 시행규칙), relation_type='하위법령', source='family'
- 위임 엣지(정본): 법제처 3단비교 API(thdCmp knd=2, 위임조문삼단비교)로 "법률→시행령",
  "시행령→시행규칙", "법률→시행규칙" 위임 관계를 조문 근거와 함께 확정. relation_type='하위법령',
  source='thdcmp', weight=4(정본 우선). 문서명 추측(family)과 달리 타계열 위임(전파법→무선설비규칙 등)도 포착.
  thdcmp가 정본화한 노드쌍은 family에서 억제(중복 방지), family는 thdcmp 미커버 폴백으로만 유지.
- 멱등: source in ('citation','family') 엣지는 함께 삭제 후 재구축, source='thdcmp'는 별도로 삭제 후 재구축.
  노드는 삭제하지 않음 (⚠️ 노드를 지우면 cascade로 seed/ai 엣지까지 소실되므로 절대 삭제 금지)

실행(PC, Python 3.12 전체 경로):
  C:\\Users\\SKTelecom\\AppData\\Local\\Programs\\Python\\Python312\\python.exe build_law_citation_graph.py
  # 위임 추출만 미리보기(DB 무변경):  ... build_law_citation_graph.py --dry-run
  # (웹요청 전 프록시 제거 필요:  $env:HTTP_PROXY=''; $env:HTTPS_PROXY='')
"""

import os
import re
import sys
import time
import argparse
from collections import defaultdict

import requests

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

# ── 법제처 DRF (3단비교로 위임 관계 정본화) ──────────────────
# law_crawler.py와 동일한 OC 키(OC=radiopolicyai). thdCmp knd=2 = "위임조문삼단비교"
# (법률조문 ↔ 그 위임을 받은 시행령·시행규칙 조문 대응). knd=1은 인용3단비교라 사용 안 함.
LAW_OC_KEY      = os.environ.get('LAW_OC_KEY', '')
LAW_SEARCH_URL  = 'http://www.law.go.kr/DRF/lawSearch.do'
LAW_SERVICE_URL = 'http://www.law.go.kr/DRF/lawService.do'

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
    """전체 (doc_name, doc_category) 페이지네이션 조회 — PostgREST 기본 1000행 제한 회피

    ⚠️ .order('id') 필수. 정렬 없이 range() 페이지네이션을 하면 Postgres가 페이지마다
    다른 순서로 행을 돌려줄 수 있어 일부 문서가 통째로 누락된다(중복 수신도 발생).
    실제로 정보통신망법 하위 고시 3건 적재 후, 같은 스크립트를 두 번 돌렸는데 매번
    다른 문서의 인용 엣지가 0건으로 빠졌다(2026-08-03). law_watch.fetch_all_doc_rows는
    이미 같은 이유로 .order('id')를 쓴다.
    """
    rows = []
    page = 1000
    offset = 0
    while True:
        r = (sb.table('document_chunks')
             .select('doc_name, doc_category')
             .order('id')
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
    """대상 문서들의 청크 본문 (페이지네이션)

    ⚠️ fetch_all_doc_rows와 같은 이유로 .order('id') 필수 — 정렬 없는 range()는
    페이지 경계에서 청크를 누락시켜 해당 문서의 인용 엣지가 통째로 사라진다.
    """
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
                 .order('id')
                 .range(offset, offset + page - 1)
                 .execute())
            rows = r.data or []
            chunks.extend(rows)
            if len(rows) < page:
                break
            offset += page
    return chunks


# ══════════════════════════════════════════════════════════
#  법제처 3단비교(thdCmp) — 위임(하위법령) 관계 정본화
# ══════════════════════════════════════════════════════════

def _drf_get(url, params, timeout=30, max_retry=3, delay=2):
    """DRF 호출 재시도 (law_crawler와 동일 정책 — 일시 오류로 누락 방지)"""
    for attempt in range(1, max_retry + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt < max_retry:
                time.sleep(delay)
            else:
                raise


def _mid_dot(s: str) -> str:
    """가운뎃점 이형 통일 — law_watch.norm_name과 같은 규칙."""
    return (s or '').replace('ㆍ', '·').replace('‧', '·').replace('•', '·')


def resolve_law_id(name: str, _cache={}):
    """법령명 → 법제처 법령ID. lawSearch(target=law) 정확 매칭(공백 무시), 없으면 None.
    thdCmp는 ID(법령ID, 예: 전파법 001732)를 요구하므로 노드 이름으로 ID를 확보한다."""
    if not LAW_OC_KEY:
        return None
    # 가운뎃점 이형(ㆍ‧•)까지 통일해야 한다 — 노드 이름은 norm_name()이 '·'로 바꿔 저장하는데
    # 법제처 응답은 'ㆍ'를 쓰는 법령이 있어, 공백만 지워 비교하면 그런 법률은 영구히 'ID없음'이 된다
    # (실측: 표시ㆍ광고의 공정화에 관한 법률 → thdcmp 정본 대신 family 추측으로 남았다). 2026-08-03
    key = _mid_dot(name).replace(' ', '')
    if key in _cache:
        return _cache[key]
    params = {'OC': LAW_OC_KEY, 'target': 'law', 'type': 'JSON',
              'query': name, 'display': 20, 'page': 1}
    try:
        data = _drf_get(LAW_SEARCH_URL, params, timeout=15).json()
        items = data.get('LawSearch', {}).get('law', [])
        if isinstance(items, dict):
            items = [items]
    except Exception as e:
        print(f'  [lawSearch 오류] {name}: {e}')
        _cache[key] = None
        return None
    law_id = None
    for it in items:
        nm = (it.get('법령명한글') or '').strip()
        # 법률만 대상(시행령/시행규칙이 substring 매칭으로 끼는 것 방지)
        if _mid_dot(nm).replace(' ', '') == key and (it.get('법령구분명') or '') == '법률':
            law_id = str(it.get('법령ID') or '').strip()
            break
    _cache[key] = law_id or None
    return law_id or None


def _art_label(cho_beonho, cho_gaji) -> str:
    """조번호('0005')+조가지번호('02') → '제5조' / '제6조의2'"""
    try:
        n = int(str(cho_beonho).lstrip('0') or '0')
    except ValueError:
        return ''
    if n <= 0:
        return ''
    label = f'제{n}조'
    try:
        g = int(str(cho_gaji or '0'))
    except ValueError:
        g = 0
    if g > 0:
        label += f'의{g}'
    return label


def fetch_thdcmp_delegations(law_name: str, law_id: str):
    """thdCmp knd=2 위임3단비교 파싱 → 위임 쌍 목록.
    반환: {(src_name, dst_name): {'count': n, 'samples': ['제5조 → 제3조', ...]}}
      - 법률 → 시행령 (시행령조문)
      - 시행령 → 시행규칙 (행에 시행령·시행규칙 조문이 함께 있을 때)
      - 법률 → 시행규칙 (시행규칙조문만 있을 때, 시행령을 거치지 않는 직접 위임)
    src/dst 이름은 각 자식 조문의 '법령명' 정본을 사용(전파법→무선설비규칙 등 타계열 위임도 포착)."""
    params = {'OC': LAW_OC_KEY, 'target': 'thdCmp', 'type': 'JSON',
              'ID': law_id, 'knd': '2'}
    resp = _drf_get(LAW_SERVICE_URL, params, timeout=45)
    data = resp.json()
    root = data.get('LspttnThdCmpLawXService')
    if not root:
        return {}, resp.status_code, len(resp.content)
    arts = root.get('위임조문삼단비교', {}).get('법률조문', [])
    if isinstance(arts, dict):
        arts = [arts]

    pairs = defaultdict(lambda: {'count': 0, 'samples': []})

    def _add(src, dst, sample):
        src = norm_name(src or '')
        dst = norm_name(dst or '')
        if not src or not dst or src == dst:
            return
        e = pairs[(src, dst)]
        e['count'] += 1
        if sample and sample not in e['samples'] and len(e['samples']) < 5:
            e['samples'].append(sample)

    for a in arts:
        law_art = _art_label(a.get('조번호'), a.get('조가지번호'))
        od = a.get('시행령조문') if isinstance(a.get('시행령조문'), dict) else None
        rd = a.get('시행규칙조문') if isinstance(a.get('시행규칙조문'), dict) else None
        od_name = od.get('법령명') if od else None
        od_art = _art_label(od.get('조번호'), od.get('조가지번호')) if od else ''
        rd_name = rd.get('법령명') if rd else None
        rd_art = _art_label(rd.get('조번호'), rd.get('조가지번호')) if rd else ''

        if od_name:
            _add(law_name, od_name, f'{law_art} → {od_art}'.strip(' →'))
        if rd_name:
            if od_name:
                # 법-령-규칙이 한 행에 정렬 → 시행령이 시행규칙에 재위임
                _add(od_name, rd_name, f'{od_art} → {rd_art}'.strip(' →'))
            else:
                _add(law_name, rd_name, f'{law_art} → {rd_art}'.strip(' →'))

    return pairs, resp.status_code, len(resp.content)


def build_thdcmp_delegations(law_bases):
    """추적 법률들에 대해 thdCmp 호출 → 위임 쌍 통합.
    반환: (delegations {(src,dst):info}, report {law: (status,len,pairs)|('실패',사유)})"""
    delegations = defaultdict(lambda: {'count': 0, 'samples': [], 'laws': set()})
    report = {}
    for law in sorted(law_bases):
        law_id = resolve_law_id(law)
        if not law_id:
            report[law] = ('ID없음', None, 0)
            continue
        try:
            pairs, status, size = fetch_thdcmp_delegations(law, law_id)
        except Exception as e:
            report[law] = ('호출실패', str(e), 0)
            continue
        for (src, dst), info in pairs.items():
            d = delegations[(src, dst)]
            d['count'] += info['count']
            d['laws'].add(law)
            for s in info['samples']:
                if s and s not in d['samples'] and len(d['samples']) < 5:
                    d['samples'].append(s)
        report[law] = (f'ID={law_id}', f'{status}/{size}B', len(pairs))
        time.sleep(0.15)
    return delegations, report


def main(dry_run=False):
    print('=== 법령 인용망 추출 시작 ===' + ('  [DRY-RUN — DB 무변경]' if dry_run else ''))
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
        # .order('id') 필수 — 누락되면 기존 노드를 못 찾아 중복 노드를 새로 만든다
        r = sb.table('law_graph_nodes').select('id, name, doc_name').order('id').range(offset, offset + 999).execute()
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

    def lookup_id(name):
        """읽기전용 노드 조회(생성 안 함) — dry-run·family 억제 비교용"""
        row = existing.get(name) or existing_nrm.get(name.replace(' ', ''))
        return row['id'] if row else None

    def node_known(name):
        """thdcmp 위임 대상으로 인정할 수 있는 노드인가?
        = 이미 DB에 있는 노드이거나, 이번 실행에서 원문·인용 경로가 어차피 만드는 노드.
        thdcmp 자신은 노드를 만들지 않으므로(옵션 B), 이 판정이 dry-run과 실제 실행에서 동일하다."""
        return bool(lookup_id(name)) or name in docs or name in cited_names

    # ── 3단비교(thdCmp)로 위임(하위법령) 관계 정본화 ───────────
    # 추적 법률(노드로 존재하는 법률)에 대해 knd=2 위임3단비교 호출 →
    # "법률 → 시행령", "시행령 → 시행규칙", "법률 → 시행규칙" 위임 쌍 확정.
    # family(문서명 추측)와 달리 타계열 위임(전파법→무선설비규칙 등)도 잡는다.
    law_bases = [b for b, info in docs.items() if info['type'] == 'law']
    if LAW_OC_KEY:
        print(f'\n[thdCmp] 추적 법률 {len(law_bases)}개에 3단비교 위임 조회...')
        delegations, thd_report = build_thdcmp_delegations(law_bases)
    else:
        print('\n[thdCmp] LAW_OC_KEY 없음 — 위임 정본화 건너뜀(family 폴백만)')
        delegations, thd_report = {}, {}

    # family(문서명 추측)를 노드ID 쌍으로 환산 — thdcmp가 덮는 쌍은 family에서 억제
    family_pair_ids = set()
    for parent, child in family_edges:
        pid, cid = lookup_id(parent), lookup_id(child)
        if pid and cid:
            family_pair_ids.add((pid, cid))
    # 양끝 노드가 모두 인정되는 쌍만 채택(옵션 B 가드) — 나머지는 스킵
    thd_ok_pairs, thd_skip_pairs = [], []
    for (src, dst) in delegations:
        if node_known(src) and node_known(dst) and src != dst:
            thd_ok_pairs.append((src, dst))
        else:
            missing = ', '.join(n for n in (src, dst) if not node_known(n))
            thd_skip_pairs.append((src, dst, missing or '동일 노드'))
    thd_pair_ids = {(lookup_id(s), lookup_id(d)) for s, d in thd_ok_pairs
                    if lookup_id(s) and lookup_id(d)}

    ok_laws = [l for l, r in thd_report.items() if r[0].startswith('ID=')]
    fail_laws = [(l, r) for l, r in thd_report.items() if not r[0].startswith('ID=')]
    covered = thd_pair_ids & family_pair_ids           # thdcmp가 정본화하는 기존 family 쌍
    new_conn = thd_pair_ids - family_pair_ids          # family가 못 잡던 새 위임 연결

    print('\n── thdCmp 결과 요약 ──────────────────────────────')
    print(f'  호출 성공 법률: {len(ok_laws)}/{len(law_bases)}')
    for l in sorted(ok_laws):
        st = thd_report[l]
        print(f'    · {l}: {st[0]} {st[1]} 위임쌍 {st[2]}건')
    if fail_laws:
        print(f'  실패/건너뜀 법률: {len(fail_laws)}')
        for l, r in fail_laws:
            print(f'    · {l}: {r[0]} {r[1] or ""}')
    print(f'  통합 위임 쌍(정규화): {len(delegations)}건'
          f' → 채택 {len(thd_ok_pairs)}건 / 노드 미존재 스킵 {len(thd_skip_pairs)}건'
          f'  (thdcmp가 만드는 신규 노드: 0건)')
    print(f'  기존 family 쌍: {len(family_pair_ids)}건 중 thdcmp가 정본화(우선) {len(covered)}건')
    print(f'  family가 못 잡던 새 위임 연결(정본): {len(new_conn)}건')
    print('  ── 채택 위임 엣지 ──')
    for (src, dst) in sorted(thd_ok_pairs):
        info = delegations[(src, dst)]
        sid, did = lookup_id(src), lookup_id(dst)
        tag = '기존family 정본화' if (sid, did) in family_pair_ids else '신규 교차위임'
        sample = (' — 예: ' + ', '.join(info['samples'])) if info['samples'] else ''
        print(f'    [{tag}] {src} → {dst}  (위임 {info["count"]}건{sample})')
    print('  ── 스킵(노드 미존재, 생성 안 함) ──')
    for src, dst, missing in sorted(thd_skip_pairs):
        print(f'    [스킵] {src} → {dst}  (노드 없음: {missing})')

    if dry_run:
        print('\n[DRY-RUN] DB 무변경 — 노드/엣지 쓰기 없이 종료 (신규 노드 0건)')
        print('=== 완료(dry-run) ===')
        return

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

    # ── thdcmp 위임 쌍 → 노드ID 확정 ───────────────────────────
    # ⚠️ thdcmp 경로는 노드를 절대 새로 만들지 않는다(운영자 결정, 옵션 B).
    #    3단비교는 우리 관심 밖 법령(각 부처 직제, 법원·헌재 개인정보 규칙, 관세법 시행규칙 등)까지
    #    위임 상대로 뱉어내므로, 노드를 생성하면 관계도가 무관한 노드로 오염된다.
    #    → 양끝이 "이미 존재하는 노드"인 쌍만 엣지로 만들고, 나머지는 건너뛰며 로그만 남긴다.
    thd_edges = []   # (sid, did, desc)
    thd_pair_ids = set()
    thd_no_id = 0
    for (src, dst) in thd_ok_pairs:
        # 위 요약 단계에서 이미 "양끝 인정" 판정된 쌍만 들어온다. 여기서도 조회만 한다.
        sid, did = node_ids.get(src) or lookup_id(src), node_ids.get(dst) or lookup_id(dst)
        if not sid or not did or sid == did or (sid, did) in thd_pair_ids:
            if not sid or not did:
                thd_no_id += 1
            continue
        thd_pair_ids.add((sid, did))
        info = delegations[(src, dst)]
        basis = (' — ' + ', '.join(info['samples'])) if info['samples'] else ''
        via = '·'.join(sorted(info['laws'])) if info.get('laws') else ''
        desc = f'위임 정본(3단비교){basis}'
        if via and via not in (src, dst):
            desc += f' [기준: {via}]'
        thd_edges.append((sid, did, desc))

    print(f'thdcmp 위임 엣지 대상: {len(thd_edges)}건 / 노드 미존재 스킵 {len(thd_skip_pairs)}건'
          + (f' / ID 미확보 {thd_no_id}건' if thd_no_id else '')
          + '  (thdcmp가 생성한 신규 노드: 0건)')

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

    family_kept = 0
    for parent, child in family_edges:
        sid, did = node_ids.get(parent), node_ids.get(child)
        if not sid or not did or (sid, did, '하위법령') in seen_pairs:
            continue
        # thdcmp가 정본화한 쌍은 family를 억제(정본 우선). family는 미커버 폴백만.
        if (sid, did) in thd_pair_ids:
            continue
        seen_pairs.add((sid, did, '하위법령'))
        family_kept += 1
        batch.append({'source_id': sid, 'target_id': did, 'relation_type': '하위법령',
                      'description': '위임 하위법령(문서명 유도)', 'source': 'family', 'weight': 3})
        if len(batch) >= 200:
            flush()
    flush()

    print(f'엣지 적재: {inserted}건 (citation + family {family_kept}건 재구축 완료)')

    # ── thdCmp 위임 엣지: source='thdcmp'만 삭제 후 재구축 (family·citation과 멱등 분리) ──
    sb.table('law_graph_edges').delete().eq('source', 'thdcmp').execute()
    batch = []
    for sid, did, desc in thd_edges:
        batch.append({'source_id': sid, 'target_id': did, 'relation_type': '하위법령',
                      'description': desc, 'source': 'thdcmp', 'weight': 4})
        if len(batch) >= 200:
            flush()
    flush()
    print(f'thdcmp 위임 엣지 적재: {len(thd_edges)}건 (source=thdcmp, family {len(thd_pair_ids)}쌍 정본화)')

    # ── 고아 노드 정리: source='citation'이고 어떤 엣지에도 안 쓰이는 노드만 삭제 ──
    # (seed/ai 노드는 절대 건드리지 않음. 엣지 0개인 노드라 cascade 영향도 없음)
    used_ids = set()
    offset = 0
    while True:
        # .order('id') 필수 — 엣지를 하나라도 놓치면 멀쩡한 노드가 '고아'로 오판돼 삭제된다
        er = sb.table('law_graph_edges').select('source_id, target_id').order('id').range(offset, offset + 999).execute()
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
    ap = argparse.ArgumentParser(description='법령 인용망 + thdCmp 위임 정본화 적재')
    ap.add_argument('--dry-run', action='store_true',
                    help='DB 무변경. thdCmp 위임 추출 결과·기존 family 대비 차이만 출력')
    args = ap.parse_args()
    main(dry_run=args.dry_run)
