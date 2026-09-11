# -*- coding: utf-8 -*-
"""
보도자료 청크 발표일 백필 (#155-보론2, 2026-09-11)

document_chunks(doc_category='보도자료')의 effective_date를 섹션 헤더 '## YYMMDD 제목'에서
유도해 채운다. content·embedding은 건드리지 않는다(메타만) — 재임베딩 불필요.

배경: 9/11 텔레그램 자문이 3/24 국무회의 의결 보도자료 조각(날짜 없음)을 근거로 이미 현행법
(제20조①5호의2, 2026.3.31 개정)에 들어간 내용을 "개정 추진 중"이라 답했다. 헤더는 섹션의 첫
조각에만 있어 뒤 조각은 발표일을 알 수 없었다.

사용:
  python press_date_backfill.py --dry-run      # 문서별 채울 건수만
  python press_date_backfill.py                # 실제 갱신 (idempotent — 이미 같은 값이면 건너뜀)
  python press_date_backfill.py --doc 과기정통부_보도자료_2026.md
"""
import os
import sys
import argparse
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')   # Windows 스케줄러 cp949 캡처 대비(#19) — 수동 실행에도 무해

from dotenv import load_dotenv
load_dotenv()
from sb_client import make_client
from press_ingest import derive_chunk_dates

PAGE = 1000


def fetch_doc_chunks(sb, doc_name: str) -> list:
    rows, start = [], 0
    while True:
        r = sb.table('document_chunks').select('id, chunk_index, content, effective_date') \
            .eq('doc_name', doc_name).order('chunk_index').range(start, start + PAGE - 1).execute()
        batch = r.data or []
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        start += PAGE
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--doc', help='특정 문서만')
    args = ap.parse_args()

    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    if args.doc:
        docs = [args.doc]
    else:
        # PostgREST 기본 상한 1,000행 — 한 번에 select하면 앞 1,000행에 든 문서만 잡힌다(실측: 18문서 중 12개).
        # 문서명 순으로 페이지를 넘기며 전부 모은다.
        names, start = set(), 0
        while True:
            r = sb.table('document_chunks').select('doc_name').eq('doc_category', '보도자료') \
                .order('doc_name').range(start, start + PAGE - 1).execute()
            batch = r.data or []
            names.update(x['doc_name'] for x in batch)
            if len(batch) < PAGE:
                break
            start += PAGE
        docs = sorted(names)
    print('[대상 문서] %d건' % len(docs))

    total_set = total_skip = total_nodate = 0
    for doc in docs:
        rows = fetch_doc_chunks(sb, doc)
        dates = derive_chunk_dates([(x['chunk_index'], x['content']) for x in rows])
        by_date = defaultdict(list)
        skip = nodate = 0
        for x in rows:
            d = dates.get(x['chunk_index'])
            if not d:
                nodate += 1
                continue
            if x.get('effective_date') == d:
                skip += 1
                continue
            by_date[d].append(x['id'])
        n_set = sum(len(v) for v in by_date.values())
        print('  %-32s 조각 %5d | 채움 %5d | 이미 같음 %5d | 날짜 없음(프리앰블) %3d' % (doc, len(rows), n_set, skip, nodate))
        if not args.dry_run:
            for d, ids in by_date.items():
                for i in range(0, len(ids), 200):
                    sb.table('document_chunks').update({'effective_date': d}).in_('id', ids[i:i + 200]).execute()
        total_set += n_set; total_skip += skip; total_nodate += nodate
    print('[완료%s] 채움 %d · 이미 같음 %d · 날짜 없음 %d' % (' (dry-run)' if args.dry_run else '', total_set, total_skip, total_nodate))
    return 0


if __name__ == '__main__':
    sys.exit(main())
