#!/usr/bin/env python3
"""
기존 document_chunks의 PDF 편집 흔적 일괄 청소 (일회성).
  · [N페이지] 페이지 구분 표시  · '법제처 N 국가법령정보센터' 쪽 하단 footer
  · 페이지마다 반복되는 법령명 머리글(줄 전체가 법령명)  · 과다 공백/개행

규칙은 upload_law_pdf.clean_pdf_artifacts / 대시보드 app.js lawmapCleanText와 동일.
content만 UPDATE하고 embedding은 건드리지 않음 — 흔적은 거의 모든 청크에 공통으로 들어간
보일러플레이트라 임베딩에 미치는 영향이 미미하고, NULL로 비우면 재임베딩 전까지 시맨틱 검색에서
빠지는 공백이 생기기 때문. (재임베딩을 원하면 --reembed로 해당 청크 embedding을 NULL 처리 후
python backfill_embeddings.py 실행)

실행(PC, Python 3.12 전체 경로):
  C:\\Users\\SKTelecom\\AppData\\Local\\Programs\\Python\\Python312\\python.exe clean_pdf_artifacts.py [--apply] [--reembed]
  · 인자 없음 = 미리보기(dry-run, 변경 건수만 집계, 쓰지 않음)
  · --apply  = 실제 UPDATE
  · --reembed = --apply와 함께, 변경된 청크의 embedding을 NULL로 (이후 backfill_embeddings.py 필요)
"""

import os
import sys

# Windows 스케줄러/cp949 콘솔 이모지 print 크래시 방지 (배경역사 #19)
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
from upload_law_pdf import clean_pdf_artifacts, law_title_from_doc_name

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
sb = make_client(SUPABASE_URL, SUPABASE_KEY)


def fetch_all_chunks():
    rows = []
    offset = 0
    page = 1000
    while True:
        r = (sb.table("document_chunks")
             .select("id, doc_name, content")
             .order("id")
             .range(offset, offset + page - 1)
             .execute())
        batch = r.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return rows


def main():
    apply = "--apply" in sys.argv
    reembed = "--reembed" in sys.argv
    mode = "실제 적용" if apply else "미리보기(dry-run)"
    print(f"=== PDF 편집 흔적 청소 — {mode} ===")

    all_rows = fetch_all_chunks()
    print(f"전체 청크: {len(all_rows):,}개")

    # doc_name별 법령명 캐시
    title_cache = {}
    changed = []
    for row in all_rows:
        dn = row["doc_name"]
        if dn not in title_cache:
            title_cache[dn] = law_title_from_doc_name(dn)
        cleaned = clean_pdf_artifacts(row.get("content") or "", title_cache[dn])
        if cleaned != (row.get("content") or ""):
            changed.append({"id": row["id"], "content": cleaned})

    docs_changed = len({r["doc_name"] for r in all_rows
                        for c in changed if c["id"] == r["id"]}) if changed else 0
    print(f"변경 대상 청크: {len(changed):,}개")

    if not changed:
        print("정리할 흔적이 없습니다.")
        return

    if not apply:
        # 샘플 3개 미리보기
        sample_ids = {c["id"] for c in changed[:3]}
        for row in all_rows:
            if row["id"] in sample_ids:
                print("\n--- 예시 (변경 후 앞 200자) ---")
                nc = next(c["content"] for c in changed if c["id"] == row["id"])
                print(nc[:200])
        print(f"\n※ 미리보기입니다. 실제 반영하려면: python clean_pdf_artifacts.py --apply")
        return

    # 실제 UPDATE (건별 — content만; --reembed면 embedding도 NULL)
    done = 0
    for c in changed:
        payload = {"content": c["content"]}
        if reembed:
            payload["embedding"] = None
        sb.table("document_chunks").update(payload).eq("id", c["id"]).execute()
        done += 1
        if done % 100 == 0:
            print(f"  적용: {done}/{len(changed)}", end="\r")
    print(f"\n완료: {done:,}개 청크 정리" + ("  · embedding NULL 처리(재임베딩 필요)" if reembed else "  · embedding 유지"))
    if reembed:
        print("  → python backfill_embeddings.py 로 재임베딩 필요")


if __name__ == "__main__":
    main()
