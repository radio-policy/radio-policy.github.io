# -*- coding: utf-8 -*-
"""
법적 용어 정의 동기화 — 현행 법령·고시의 정의 조문(제N조(정의) 등)에서 용어 정의를 **원문 그대로** 뽑아
law_terms 테이블을 전량 재생성한다 (#156, 2026-09-11). Anthropic API 호출 0회 — Supabase만 읽고 쓴다.

흐름:
  document_chunks(status=current, is_approved, article_no 제목이 정확히 (정의)|(용어의 정의)|(용어정의)|(용어의 뜻))
  → (doc_name, 조번호)로 묶어 청크 겹침(~100자)을 제거하며 이어붙임(merge_chunks)
  → 호(1. 4의2. …)·항(①②)·콜론형 항목을 파싱(parse_definitions)
  → law_terms upsert(doc_name, article_no, item_no) → 이번 실행에 안 걸린 행(구버전 판·사라진 호) 삭제
  → system_health 'last_law_terms_sync' heartbeat

실행: 매일 11:00 KST law_crawl.yml 마지막 단계(law_sync --promote·law_watch 뒤). PC에서 law_sync.py로 법령을
교체한 날은 수동 1회.  옵션: --dry-run(파싱 결과만, DB 무변경) / --doc <문서명 조각>(부분 실행, 삭제 없음) / --limit N

주의(지침 do-not):
  - 정의 조문 제목 필터는 **정확 일치 4종만**. '정의' 부분일치로 느슨하게 바꾸면 '분쟁조정의 특례'·'지정의 방법'
    같은 조문 25건이 걸려 본문이 용어로 들어온다(실측).
  - law_terms를 SQL로 손보지 말 것 — 다음 실행이 전량 덮어쓴다. 정의 문안이 틀리면 원인은 청크(현행화)나 이 파서다.
필요 env: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
import os
import re
import sys
import argparse
from collections import OrderedDict
from datetime import datetime, timezone

# Windows 스케줄러/cp949 콘솔 이모지 크래시 방지 (배경역사 #19)
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

import law_watch   # parse_doc_name · norm_name · TYPE_PAREN_RE (문서명 관례의 원본)

HEARTBEAT_KEY = 'last_law_terms_sync'
BATCH = 200

# ── 정규식 ────────────────────────────────────────────────────────────────
# 정의 조문 제목 — 정확 일치만 (부분일치 금지, 모듈 docstring 참조)
DEF_TITLE_RE = re.compile(r'^\d+조(?:의\d+)?\((정의|용어의\s?정의|용어정의|용어의\s?뜻)\)$')
DEF_TITLE_PG = r'^[0-9]+조(의[0-9]+)?\((정의|용어의 ?정의|용어정의|용어의 ?뜻)\)$'   # PostgREST match(~)용
# law_diff_gen.py:72 ART_KEY_RE 와 동일 — 변경 시 함께 (law_diff_gen은 anthropic을 import하므로 여기서 안 끌어옴)
ART_KEY_RE = re.compile(r'^제?\s*([0-9]+조(?:의[0-9]+)?)')
HEADER_RE = re.compile(r'^\s*제\s*\d+조(?:의\d+)?\s*\([^)]*\)\s*')            # 첫 청크 머리 '제2조(정의)'
HANG_RE = re.compile(r'[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]')
HANG_NUM = {c: i + 1 for i, c in enumerate('①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳')}
AMEND_TAIL_RE = re.compile(r'\s*<(?:개정|신설|전문개정|삭제)[^>]*>\s*$')
PAGE_MARK_RE = re.compile(r'\n\s*-\s*\d+\s*-\s*\n')                            # PDF 유래 '- 1 -'
# 호(item) 시작: 앞이 숫자(2008.6.20)나 '숫자.'(0.5)가 아니어야 하고 — '…같다.1. "번호이동"' 처럼 문장 끝 마침표 뒤는 허용 —
# 번호 뒤에 따옴표 / 삭제 / 콜론형 용어가 온다.
ITEM_START_RE = re.compile(
    r'(?<!\d)(?<!\d\.)(\d{1,3}(?:의\d{1,2})?)\.\s*'
    r'(?=["“]|삭제|[가-힣A-Za-z][^:\n"“]{0,40}\s?:)')
# 항목 머리의 용어: "용어"(별칭)? (이)란 | (이)라 함은 | (이)라고 함은. 비탐욕 → "A(이하 "B"라 한다)"이란 같은 중첩 따옴표 통과.
# '이라 한다'는 마커에 넣지 않는다 — 넣으면 안쪽 "B"이라 한다 에 먼저 걸린다.
# 마커 뒤는 한글이 아니어야 한다("란"이 단어 일부인 경우 배제) — 공백·「·괄호는 허용('"보조사업자"란「보조금 …」' 실측).
_MARK = r'(?:이?란|이?라\s*함은|이?라고\s*함은|은|는)(?![가-힣])'
TERM_QUOTED_RE = re.compile(r'^["“](.{1,120}?)["”]\s*(?:\(([^()]{1,60})\))?\s*' + _MARK)
TERM_QUOTED_SEARCH_RE = re.compile(r'["“](.{1,120}?)["”]\s*(?:\(([^()]{1,60})\))?\s*' + _MARK)
# 콜론형: '협정료(accounting rate) : …' / '신호영역/통신망번호 : …' / '이동전화(셀룰러 또는 개인휴대통신) 서비스 : …'
TERM_COLON_RE = re.compile(r'^([^:\n"“]{1,60}?)\s*:\s*')
HTML_TAG_RE = re.compile(r'</?[a-zA-Z][^<>]*>')                                 # 청크에 섞인 <img …> 등
INNER_ALIAS_RE = re.compile(r'^(.*?)\s*[\(（]([^()（）]{1,60})[\)）]\s*$')     # "무선국(無線局)" → 무선국 / 無線局
SUB_ITEM_BREAK_RE = re.compile(r'\n(?!\s*[가-힣][.)]\s)')                       # 가. 나. 목 앞 줄바꿈만 보존
DELETED_RE = re.compile(r'^삭제')

LAW_TYPE_MAP = {'법률': '법률', '대통령령': '대통령령', '총리령': '부령', '부령': '부령', '고시': '고시',
                '훈령': '훈령', '예규': '예규', '공고': '공고', '위원회규칙': '규칙', '연구원규칙': '규칙'}


# ── 순수 함수 (tests/test_law_terms.py) ───────────────────────────────────
def norm_key(article_no):
    m = ART_KEY_RE.match(article_no or '')
    return m.group(1) if m else None


def merge_chunks(parts):
    """chunk_index 순 청크 목록 → 한 본문. 인접 청크의 접미사=접두사 최장 일치(400…20자)를 겹침으로 보고 잘라낸다.
    (law_sync 청크는 ~100자 겹침 — 정의 조문 107쌍 실측 전부 ≥60자. 하한 20자로 '말한다.\\n' 같은 흔한 꼬리 오탐 방지)
    겹침을 못 찾으면 줄바꿈으로 잇는다."""
    out = ''
    for p in parts:
        p = p or ''
        if not out:
            out = p
            continue
        k = 0
        for n in range(min(len(out), len(p), 400), 19, -1):
            if out.endswith(p[:n]):
                k = n
                break
        out += p[k:] if k else ('\n' + p)
    return out


def _split_term_alias(term, alias):
    """따옴표 안 괄호 병기 분리. '무선국(無線局)' → ('무선국', '無線局'). '(이하 …)'는 병기가 아니므로 떼기만 한다."""
    term = term.strip()
    if alias and alias.strip().startswith('이하'):    # "국제표준화 국내간사기관"(이하 "간사기관"이라 한다)은 — 병기 아님
        alias = None
    # '번호이동DB(이하"NPDB(Number Portability DataBase)"라 한다)' — 괄호가 중첩된 (이하 …) 꼬리는 통째로 뗀다
    term = re.sub(r'\s*[\(（]\s*이하.*$', '', term).strip() or term
    m = INNER_ALIAS_RE.match(term)
    if m:
        inner = m.group(2).strip()
        term = m.group(1).strip() or term
        if not alias and not inner.startswith('이하'):
            alias = inner
    return term, (alias.strip() if alias else None)


def term_key(term):
    t = re.sub(r'[\(（].*?[\)）]', '', law_watch.norm_name(term or ''))
    return re.sub(r'\s+', '', t).lower()


def _clean_item(text):
    text = HTML_TAG_RE.sub('', text)
    text = AMEND_TAIL_RE.sub('', text.strip())
    text = SUB_ITEM_BREAK_RE.sub(' ', text)          # 목(가. 나.) 앞 줄바꿈만 남긴다
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def parse_definitions(body, article_no=''):
    """정의 조문 본문 → (rows, unparsed). rows=[{item_no, term, term_alias, definition}], unparsed=[(item_no, 머리 80자)]."""
    rows, unparsed = [], []
    body = PAGE_MARK_RE.sub('\n', body or '')
    body = HEADER_RE.sub('', body, count=1)

    # 항(①②…) 구간 분할 — 없으면 전체가 한 구간
    segs = []
    marks = list(HANG_RE.finditer(body))
    if not marks:
        segs.append((None, body))
    else:
        if body[:marks[0].start()].strip():
            segs.append((None, body[:marks[0].start()]))
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
            segs.append((HANG_NUM.get(m.group(0)), body[m.end():end]))

    seen = {}
    for hang, seg in segs:
        starts = list(ITEM_START_RE.finditer(seg))
        items = []
        if starts:
            for i, m in enumerate(starts):
                end = starts[i + 1].start() if i + 1 < len(starts) else len(seg)
                items.append((m.group(1), seg[m.end():end]))
        else:
            # 번호 없는 정의: '① "기본징수율"이란 …' / '이 고시에서 사용하는 "등록신청법인"이라 함은 …'
            m = TERM_QUOTED_SEARCH_RE.search(seg)
            if m:
                items.append(('%d항' % hang if hang else '본문', seg[m.start():]))
        for item_no, raw in items:
            text = _clean_item(raw)
            if not text or DELETED_RE.match(text):
                continue
            q = TERM_QUOTED_RE.match(text)
            if q:
                term, alias = _split_term_alias(q.group(1), q.group(2))
            else:
                c = TERM_COLON_RE.match(text)
                if not c:
                    unparsed.append((item_no, text[:80]))
                    continue
                term, alias = _split_term_alias(c.group(1), None)
            if not term:
                unparsed.append((item_no, text[:80]))
                continue
            if item_no in seen:                     # 겹침 제거 실패 신호 — 번호 중복
                seen[item_no] += 1
                item_no = '%s-%d' % (item_no, seen[item_no])
            else:
                seen[item_no] = 1
            rows.append({'item_no': item_no, 'term': term, 'term_alias': alias, 'definition': text})
    return rows, unparsed


def law_type_of(doc_name):
    """doc_name → (law_name, full_name, law_type, law_no, enf_date). 관례 밖 문서명은 이름에서 추정."""
    p = law_watch.parse_doc_name(doc_name)
    if p:
        return (p['law_name'], p['full_name'], LAW_TYPE_MAP.get(p['law_type_token'], '기타'),
                p.get('law_no'), p.get('enf_date'))
    name = re.sub(r'\.(pdf|md|txt|docx)$', '', law_watch.norm_name(doc_name), flags=re.I)
    if '시행규칙' in name:
        lt = '부령'
    elif '시행령' in name:
        lt = '대통령령'
    elif name.endswith('법'):
        lt = '법률'
    elif '고시' in name:
        lt = '고시'
    else:
        lt = '기타'
    return name, name, lt, None, None


# ── DB ────────────────────────────────────────────────────────────────────
def fetch_def_chunks(sb, doc_filter=None):
    """정의 조문 청크 전량 (PostgREST 1,000행 상한 → order+range 페이징)."""
    rows, start, page = [], 0, 1000
    while True:
        q = (sb.table('document_chunks')
             .select('id,doc_name,doc_category,chunk_index,article_no,content')
             .eq('status', 'current').eq('is_approved', True)
             .filter('article_no', 'match', DEF_TITLE_PG))
        if doc_filter:
            q = q.ilike('doc_name', '%%%s%%' % doc_filter)
        batch = q.order('id').range(start, start + page - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        start += page
    return [r for r in rows if DEF_TITLE_RE.match(r.get('article_no') or '')]   # 파이썬 재검사


def build_rows(chunks, run_ts):
    """청크 → law_terms 행. 반환 (rows, stats)."""
    groups = OrderedDict()
    for r in sorted(chunks, key=lambda x: (x['doc_name'], x.get('chunk_index') or 0)):
        key = (r['doc_name'], norm_key(r['article_no']))
        g = groups.setdefault(key, {'doc_category': r.get('doc_category'), 'article_no': r['article_no'], 'parts': []})
        g['parts'].append(r.get('content') or '')
    rows, stats = [], {'docs': set(), 'articles': 0, 'unparsed': [], 'dup': 0, 'by_type': {}, 'by_doc': OrderedDict()}
    for (doc_name, akey), g in groups.items():
        body = merge_chunks(g['parts'])
        defs, unparsed = parse_definitions(body, g['article_no'])
        stats['articles'] += 1
        stats['unparsed'].extend((doc_name, i, t) for i, t in unparsed)
        law_name, full_name, law_type, law_no, enf = law_type_of(doc_name)
        for d in defs:
            if '-' in d['item_no']:
                stats['dup'] += 1
            rows.append({
                'term': d['term'], 'term_key': term_key(d['term']), 'term_alias': d['term_alias'],
                'law_name': law_name, 'full_name': full_name, 'law_type': law_type,
                'doc_name': doc_name, 'doc_category': g['doc_category'],
                'article_no': g['article_no'], 'article_key': akey, 'item_no': d['item_no'],
                'definition': d['definition'], 'law_no': law_no, 'effective_date': enf,
                'synced_at': run_ts,
            })
        if defs:
            stats['docs'].add(doc_name)
            stats['by_type'][law_type] = stats['by_type'].get(law_type, 0) + len(defs)
            stats['by_doc'][(doc_name, g['article_no'])] = defs
    return rows, stats


def heartbeat(sb, note):
    try:
        sb.table('system_health').upsert(
            {'key': HEARTBEAT_KEY, 'updated_at': datetime.now(timezone.utc).isoformat(), 'note': note},
            on_conflict='key').execute()
    except Exception as e:
        print('[heartbeat 오류] %s' % e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='파싱 결과만 출력, DB 무변경')
    ap.add_argument('--doc', help='문서명 조각 — 해당 문서만 처리(삭제 단계 없음)')
    ap.add_argument('--limit', type=int, default=0, help='처리할 (문서,조문) 수 상한 (0=전부)')
    args = ap.parse_args()

    from sb_client import make_client
    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    run_ts = datetime.now(timezone.utc).isoformat()

    chunks = fetch_def_chunks(sb, args.doc)
    print('[법적 용어] 정의 조문 청크 %d건 (문서 %d)' % (len(chunks), len({c['doc_name'] for c in chunks})))
    rows, st = build_rows(chunks, run_ts)
    if args.limit > 0:
        keep = list(st['by_doc'].keys())[:args.limit]
        rows = [r for r in rows if (r['doc_name'], r['article_no']) in set(keep)]

    for (doc, art), defs in st['by_doc'].items():
        print('  %-70s %-14s %3d정의' % (doc[:70], art[:14], len(defs)))
        if args.dry_run:
            for d in defs[:3]:
                print('      [%s] %s%s — %s' % (d['item_no'], d['term'],
                                                 '(' + d['term_alias'] + ')' if d['term_alias'] else '',
                                                 d['definition'][:70]))
    print('[법적 용어] 문서 %d · 조문 %d · 정의 %d · 미파싱 %d · 번호중복 %d' %
          (len(st['docs']), st['articles'], len(rows), len(st['unparsed']), st['dup']))
    print('  법종별: ' + ', '.join('%s %d' % kv for kv in sorted(st['by_type'].items(), key=lambda x: -x[1])))
    if st['unparsed']:
        print('  미파싱 항목:')
        for doc, i, t in st['unparsed'][:40]:
            print('    - %s [%s] %s' % (doc[:50], i, t))
    if args.dry_run:
        print('[dry-run] DB 무변경')
        return

    existing = sb.table('law_terms').select('id', count='exact').limit(1).execute().count or 0
    for i in range(0, len(rows), BATCH):
        sb.table('law_terms').upsert(rows[i:i + BATCH], on_conflict='doc_name,article_no,item_no').execute()
    print('[법적 용어] upsert %d행 (기존 %d행)' % (len(rows), existing))

    deleted, fail = 0, 0
    if args.doc or args.limit:
        print('  부분 실행 — 구버전 정리 생략')
    elif not rows or (existing and len(rows) < existing * 0.5):
        fail = 1
        print('[중단] 추출 건수 급감(%d → %d) — 삭제 생략. 청크 현행화 상태나 파서를 확인할 것' % (existing, len(rows)))
    else:
        r = sb.table('law_terms').delete().lt('synced_at', run_ts).execute()
        deleted = len(r.data or [])
        print('  구버전·소멸 항목 삭제 %d행' % deleted)

    note = 'docs=%d terms=%d deleted=%d unparsed=%d dup=%d fail=%d' % (
        len(st['docs']), len(rows), deleted, len(st['unparsed']), st['dup'], fail)
    print('[법적 용어] 완료 - ' + note)
    heartbeat(sb, note)


if __name__ == '__main__':
    main()
