#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""1군 조문 이미지 수집 — 원본을 받아 PNG로 변환만 한다(DB 변경 없음).

법제처 이미지는 <img id="…">에 URL이 없고, flDownload.do?flSeq=<id>로 받아야 한다.
id는 연속 번호가 아니므로 반드시 본문에서 읽는다. 받은 파일은 확장자가 gif지만
실제 형식은 BMP라 그대로는 못 읽는다 — PNG로 변환해 둔다.
"""
import os
import re
import sys
import json

sys.path.insert(0, r'C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai')
os.chdir(r'C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai')
sys.stdout.reconfigure(encoding='utf-8')

for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
    os.environ.pop(k, None)

from dotenv import load_dotenv
load_dotenv(r'C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai\.env')

import requests
from PIL import Image
from sb_client import make_client

sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
OUT = r'C:\Users\SKTELE~1\AppData\Local\Temp\claude\C--Users-SKTelecom-Desktop-frequence-radio-policy-ai\f3a8282f-cc88-4ad3-b536-2766d14aa171\scratchpad\ocr'
os.makedirs(OUT, exist_ok=True)

# 1군 — 본문이 사실상 조 제목뿐이라 이미지가 유일한 내용인 조문
TARGETS = [
    ('단말장치 기술기준%',      ['5조%', '16조%', '17조%', '18조%', '24조%', '26조%']),
    ('경고문구의 표기 내용%',   ['2조%']),
    ('이동전화망번호관리기준%', ['4조%']),
    ('무선종사자 자격%',        ['12조%']),
]

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}


def main():
    manifest = []
    for doc_like, arts in TARGETS:
        for art_like in arts:
            r = sb.table('document_chunks') \
                .select('id, doc_name, article_no, content, chunk_index') \
                .eq('is_approved', True).eq('status', 'current') \
                .like('doc_name', doc_like).like('article_no', art_like).execute()
            for row in (r.data or []):
                ids = re.findall(r'<img[^>]*id="(\d+)"', row['content'] or '')
                if not ids:
                    continue
                print(f"\n■ {row['doc_name'].split('(')[0][:26]} {row['article_no'][:38]}")
                print(f"   chunk id={row['id']}  본문 {len(row['content'])}자  이미지 {len(ids)}개")
                files = []
                for fid in ids:
                    raw_p = os.path.join(OUT, f'{fid}.bin')
                    png_p = os.path.join(OUT, f'{fid}.png')
                    if not os.path.exists(png_p):
                        try:
                            resp = requests.get(
                                f'https://www.law.go.kr/LSW/flDownload.do?flSeq={fid}',
                                headers=UA, timeout=30)
                            if resp.status_code != 200 or len(resp.content) < 500:
                                print(f'     ✗ {fid}: HTTP {resp.status_code} {len(resp.content)}B')
                                continue
                            open(raw_p, 'wb').write(resp.content)
                            im = Image.open(raw_p)
                            fmt, size = im.format, im.size
                            im.convert('RGB').save(png_p)
                            print(f'     ✓ {fid}: {fmt} {size[0]}x{size[1]} → png')
                        except Exception as e:
                            print(f'     ✗ {fid}: {e}')
                            continue
                    else:
                        print(f'     · {fid}: 이미 있음')
                    files.append(fid)
                manifest.append({
                    'chunk_id': row['id'], 'doc_name': row['doc_name'],
                    'article_no': row['article_no'], 'img_ids': files,
                    'content': row['content'],
                })
    p = os.path.join(OUT, 'manifest.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f'\n대상 조문 {len(manifest)}개 · 이미지 {sum(len(m["img_ids"]) for m in manifest)}개')
    print(f'manifest: {p}')


if __name__ == '__main__':
    main()
