#!/usr/bin/env python3
"""보도자료 전 섹션(제목+본문 발췌)을 검토용 배치 JSON으로 추출 (읽기 전용).
사용: python export_press_sections.py <출력디렉터리> [--batch 60] [--excerpt 600]
출력: batch_001.json ... (각 원소: agency/year/ymd/title/excerpt/doc_name)
"""
import os
import re
import sys
import json
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
from sb_client import make_client

SECTION_RE = re.compile(r'(?m)^## (\d{6}) (.+)$')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('outdir')
    ap.add_argument('--batch', type=int, default=60)
    ap.add_argument('--excerpt', type=int, default=600)
    args = ap.parse_args()

    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    # PostgREST 는 무정렬 조회를 1,000행에서 자르므로 반드시 페이징 (배경역사 #50 유형)
    names, page = set(), 0
    while True:
        rows = (sb.table('document_chunks').select('doc_name')
                .eq('doc_category', '보도자료').order('id')
                .range(page * 1000, page * 1000 + 999).execute().data)
        names.update(r['doc_name'] for r in rows)
        if len(rows) < 1000:
            break
        page += 1
    docs = sorted(names)
    sections = []
    for doc in docs:
        # 문서 전체를 청크 순서로 이어붙여 섹션 단위로 분해
        chunks, page = [], 0
        while True:
            rows = (sb.table('document_chunks').select('chunk_index,content')
                    .eq('doc_name', doc).order('chunk_index')
                    .range(page * 500, page * 500 + 499).execute().data)
            if not rows:
                break
            chunks.extend(rows)
            if len(rows) < 500:
                break
            page += 1
        full = ''.join(c['content'] for c in chunks)
        agency = doc.split('_')[0]
        year = doc.rsplit('_', 1)[1].replace('.md', '')
        matches = list(SECTION_RE.finditer(full))
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
            body = full[start:end].strip()
            sections.append({
                'doc_name': doc, 'agency': agency, 'year': year,
                'ymd': m.group(1), 'title': m.group(2).strip(),
                'excerpt': body[:args.excerpt],
            })
        print('%s: %d섹션' % (doc, len(matches)))

    os.makedirs(args.outdir, exist_ok=True)
    total = 0
    for bi in range(0, len(sections), args.batch):
        batch = sections[bi:bi + args.batch]
        path = os.path.join(args.outdir, 'batch_%03d.json' % (bi // args.batch + 1))
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)   # 원자적 쓰기
        total += len(batch)
    print('합계 %d섹션 → 배치 %d개 (%s)' % (
        total, (len(sections) + args.batch - 1) // args.batch, args.outdir))


if __name__ == '__main__':
    main()
