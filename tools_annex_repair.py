# -*- coding: utf-8 -*-
"""
별표 조각 정리 — 한 번 쓰는 도구 (#257, 2026-09-29). AI 0회, 법제처 API·별표 PDF만 받는다.

  ① 번호 없는 별표 이름표 「별표 ?(제목)」 → 「별표(제목)」 (별지·서식·붙임·별첨도 같다, 운영자 결정 나)
  ② 별표 본문의 잃은 글자 '?' → 같은 별표 PDF에서 되찾은 글자 (annex_textfix — 법제처 API가 KS X 1001에 없는 글자를 '?'로 준다)

안전장치: 문서마다 법제처에서 **그 판(law_mst·시행일)** 을 다시 받아 옛 적재 규칙(옛 이름표·복구 없음)으로 조각을 다시 만들고,
DB 조각과 **글자 하나까지 같을 때만** 그 별표를 고친다(다르면 건너뛰고 알린다). '?'를 한 글자로 바꾸므로 조각 경계·개수는 그대로다.
임베딩은 다시 만들지 않는다(글머리 기호 한 글자 차이). --apply 전에 바꿀 행 전부를 local_docs/에 백업한다.

  py -3.12 tools_annex_repair.py                       # 미리보기(DB 무변경) — 문서별 이름표·'?' 되찾음/남김·불일치
  py -3.12 tools_annex_repair.py --doc 집적정보          # 문서명에 이 낱말이 든 것만
  py -3.12 tools_annex_repair.py --apply [--doc …]      # 백업 → 씀
  py -3.12 tools_annex_repair.py --labels-only --apply  # 이름표만(글자 복구 없이)
"""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):   # 세션 프록시는 법제처 SSL을 깨뜨린다
    os.environ.pop(_k, None)

import requests
from dotenv import load_dotenv

load_dotenv()

import sb_client
import annex_textfix
import law_sync
from law_watch import parse_doc_name, api_target_of

ROOT = Path(__file__).parent
TABLE_RE = '^(별표|별지|붙임|서식|별첨)'
CACHE_DIR = ROOT / 'local_docs' / 'annex_pdf_cache'


def _paged(q, page=500):
    rows, off = [], 0
    while True:
        b = q.order('id').range(off, off + page - 1).execute().data or []
        rows.extend(b)
        if len(b) < page:
            return rows
        off += page


def target_docs(sb, word):
    """별표류 조각 중 이름표에 ' ?'가 있거나 본문에 '?'가 든 API 적재 문서 → {(doc_name, law_mst, status)}"""
    q = (sb.table('document_chunks').select('id,doc_name,law_mst,status')
         .filter('article_no', 'match', TABLE_RE).not_.is_('law_mst', 'null')
         .or_('article_no.like.* ?*,content.like.*?*'))
    if word:
        q = q.ilike('doc_name', f'%{word}%')
    return sorted({(r['doc_name'], r['law_mst'], r['status']) for r in _paged(q)})


def fetch_body(doc_name, mst):
    meta = parse_doc_name(doc_name)
    if not meta:
        raise RuntimeError('문서명 파싱 실패')
    target = api_target_of(meta['law_type_token'])
    params = {'OC': law_sync.OC_KEY, 'type': 'JSON'}
    if target == 'law':
        enf = meta.get('enf_date')
        params.update({'MST': mst}, **({'target': 'eflaw', 'efYd': enf} if enf else {'target': 'law'}))
    else:
        params.update({'target': 'admrul', 'ID': mst})
    r = requests.get(law_sync.DRF_SERVICE, params=params, timeout=90)
    r.raise_for_status()
    d = r.json()
    return d['법령'] if target == 'law' else d[list(d)[0]]


def pdf_text_cached(link, session):
    if not link:
        return ''
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / (hashlib.sha1(link.encode()).hexdigest()[:16] + '.txt')
    if f.exists():
        return f.read_text(encoding='utf-8')
    t = annex_textfix.fetch_pdf_text(link, session=session)
    if t:
        f.write_text(t, encoding='utf-8')
    time.sleep(0.5)
    return t


def plan_doc(sb, doc_name, mst, session, labels_only, audit=None):
    """→ (바꿀 행 [(id, old_row, new_label, new_content)], 문서 요약 dict)"""
    rows = _paged(sb.table('document_chunks').select('id,doc_name,article_no,chunk_index,content')
                  .eq('doc_name', doc_name).filter('article_no', 'match', TABLE_RE))
    rows.sort(key=lambda r: r['chunk_index'])
    by_label = {}
    for r in rows:
        by_label.setdefault(r['article_no'], []).append(r)
    used = {}
    body = fetch_body(doc_name, mst)
    summ = {'units': 0, 'relabel': 0, 'q_before': 0, 'q_fixed': 0, 'q_left': 0, 'mismatch': [], 'no_pdf': 0}
    changes = []
    for u in law_sync._table_units(body):
        old_label, new_label = law_sync.table_label(u, legacy=True), law_sync.table_label(u)
        need_q = '?' in u['text'] and not labels_only
        if old_label == new_label and not need_q:
            continue
        old_chunks = law_sync.chunk_articles([(old_label, u['text'])])
        pool = by_label.get(old_label, [])
        start = used.get(old_label, 0)
        db = pool[start:start + len(old_chunks)]
        if not db:
            continue   # 이 판에는 이 별표가 DB에 없다(이미 고쳤거나 다른 판) — 조용히 넘긴다
        used[old_label] = start + len(old_chunks)
        if len(db) != len(old_chunks) or any(a['content'] != b['content'] for a, b in zip(db, old_chunks)):
            summ['mismatch'].append(old_label[:40])
            continue
        summ['units'] += 1
        text = u['text']
        if need_q:
            q0 = text.count('?')
            pdf = pdf_text_cached(u['raw'].get('별표서식PDF파일링크'), session)
            if not pdf:
                summ['no_pdf'] += 1
            else:
                text, n, left, _g = annex_textfix.fix_lost_chars(text, pdf)
                if audit is not None:   # 바뀐 글자마다 (문서, 별표, 새 글자, 앞뒤 문맥) — 한글·숫자로 바뀐 것은 사람이 본다
                    src = u['text']
                    for k, (a0, b0) in enumerate(zip(src, text)):
                        if a0 != b0:
                            audit.append({'doc': doc_name, 'label': new_label[:50], 'ch': b0, 'alnum': b0.isalnum(),
                                          'ctx': src[max(0, k - 20):k] + '[' + b0 + ']' + src[k + 1:k + 21]})
                summ['q_before'] += q0
                summ['q_fixed'] += n
                summ['q_left'] += left
        new_chunks = law_sync.chunk_articles([(new_label, text)])
        if len(new_chunks) != len(db) or any(len(a['content']) != len(b['content']) for a, b in zip(db, new_chunks)):
            summ['mismatch'].append(old_label[:40] + ' (복구 뒤 조각 경계 달라짐)')
            continue
        if old_label != new_label:
            summ['relabel'] += len(db)
        for a, b in zip(db, new_chunks):
            if a['article_no'] != new_label or a['content'] != b['content']:
                changes.append((a['id'], a, new_label, b['content']))
    return changes, summ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--doc', default='', help='문서명에 이 낱말이 든 것만')
    ap.add_argument('--apply', action='store_true', help='백업 뒤 DB에 쓴다(없으면 미리보기)')
    ap.add_argument('--labels-only', action='store_true', help='이름표만 고치고 글자 복구는 하지 않는다')
    ap.add_argument('--audit', default='', help='바뀐 글자 목록을 이 JSONL 파일로(글자별 문맥)')
    args = ap.parse_args()
    if not annex_textfix._find_pdftotext() and not args.labels_only:
        print('! pdftotext 없음 — 글자 복구 불가(--labels-only로만 실행 가능)')
        return 1
    sb = sb_client.make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    docs = target_docs(sb, args.doc)
    print(f"대상 문서(판) {len(docs)}개{' — ' + args.doc if args.doc else ''}")
    session = requests.Session()
    all_changes, tot = [], {'units': 0, 'relabel': 0, 'q_before': 0, 'q_fixed': 0, 'q_left': 0, 'mismatch': 0, 'no_pdf': 0, 'fail': 0}
    audit = [] if args.audit else None
    for doc_name, mst, status in docs:
        try:
            ch, s = plan_doc(sb, doc_name, mst, session, args.labels_only, audit)
        except Exception as e:
            tot['fail'] += 1
            print(f"✖ {doc_name[:60]} [{status}] 법제처 조회 실패: {str(e)[:80]}")
            continue
        all_changes.extend(ch)
        for k in ('units', 'relabel', 'q_before', 'q_fixed', 'q_left', 'no_pdf'):
            tot[k] += s[k]
        tot['mismatch'] += len(s['mismatch'])
        print(f"· {doc_name[:60]} [{status}] 별표 {s['units']} · 이름표 {s['relabel']}조각 · '?' {s['q_before']}→되찾음 {s['q_fixed']}/남김 {s['q_left']}"
              + (f" · PDF 없음 {s['no_pdf']}" if s['no_pdf'] else '')
              + (f" · 불일치(건너뜀) {s['mismatch']}" if s['mismatch'] else '') + f" → 바꿀 행 {len(ch)}")
    print(f"\n합계: 문서(판) {len(docs)} · 별표 {tot['units']} · 이름표 {tot['relabel']}조각 · '?' {tot['q_before']} 중 되찾음 {tot['q_fixed']}·남김 {tot['q_left']}"
          f" · PDF 없음 {tot['no_pdf']} · 불일치 {tot['mismatch']} · 조회 실패 {tot['fail']} → 바꿀 행 {len(all_changes)}")
    if audit is not None:
        with open(args.audit, 'w', encoding='utf-8') as f:
            for a in audit:
                f.write(json.dumps(a, ensure_ascii=False) + '\n')
        from collections import Counter
        print('바뀐 글자:', Counter(a['ch'] for a in audit).most_common(20), '· 한글·숫자로 바뀐 것', sum(a['alnum'] for a in audit))
    if not args.apply:
        print('[미리보기] DB 변경 없음 — --apply로 씀')
        return 0
    if not all_changes:
        return 0
    bdir = ROOT / 'local_docs'
    bdir.mkdir(exist_ok=True)
    bfile = bdir / f"annex_repair_backup_{datetime.now():%Y%m%d_%H%M%S}.json"
    bfile.write_text(json.dumps([{'id': i, 'doc_name': a['doc_name'], 'article_no': a['article_no'], 'content': a['content']}
                                 for i, a, _, _ in all_changes], ensure_ascii=False), encoding='utf-8')
    print(f"백업: {bfile} ({len(all_changes)}행)")
    done = 0
    for i, a, lab, content in all_changes:
        patch = {}
        if a['article_no'] != lab:
            patch['article_no'] = lab
        if a['content'] != content:
            patch['content'] = content
        law_sync_retry(lambda: sb.table('document_chunks').update(patch).eq('id', i).execute())
        done += 1
        if done % 200 == 0:
            print(f"  … {done}/{len(all_changes)}")
    print(f"완료: {done}행 갱신")
    return 0


def law_sync_retry(fn):
    import retry_util
    return retry_util.with_retry(fn, retries=3, delay=2, label='annex_repair update')


if __name__ == '__main__':
    sys.exit(main())
