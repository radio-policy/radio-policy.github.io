"""
보고서 샘플 임베딩 백필 스크립트
사용법: python backfill_report_embeddings.py

- report_samples 중 embedding이 NULL인 행만 처리 (멱등)
- 임베딩 대상 텍스트: title + "\n" + (summary 있으면 summary, 없으면 content 앞 1500자)
- voyage-4-lite(1024차원)로 임베딩 → report_samples.embedding PATCH 저장
- 신규 보고서 등록(대시보드) 후 PC에서 1회 실행하면 의미(시맨틱) 검색 적용
  (실행 전에도 키워드·유형 필터로는 즉시 검색됨 — "임베딩 대기" 배지)
"""

import sys

# cp949 콘솔·파이프에서 이모지 print 크래시 방지 (지침 가드레일 #19)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")  # .env에만 — 공개 repo 하드코딩 금지

VOYAGE_MODEL = "voyage-4-lite"
EMBED_DIM = 1024


def _sb_headers(extra=None):
    h = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def fetch_pending(limit=200):
    """embedding이 NULL인 보고서 샘플 조회"""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/report_samples",
        headers=_sb_headers(),
        params={
            "select": "id,title,summary,content",
            "embedding": "is.null",
            "order": "id.asc",
            "limit": limit,
        },
    )
    resp.raise_for_status()
    return resp.json()


def get_voyage_embeddings(texts):
    resp = requests.post(
        "https://api.voyageai.com/v1/embeddings",
        headers={
            "Authorization": f"Bearer {VOYAGE_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": VOYAGE_MODEL, "input": texts, "input_type": "document"},
        timeout=60,
    )
    resp.raise_for_status()
    return [item["embedding"] for item in resp.json()["data"]]


def update_embedding(row_id, embedding):
    vec = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/report_samples",
        headers=_sb_headers({"Prefer": "return=minimal"}),
        params={"id": f"eq.{row_id}"},
        json={"embedding": vec},
    )
    resp.raise_for_status()


def build_text(row):
    title = (row.get("title") or "").strip()
    summary = (row.get("summary") or "").strip()
    body = summary if summary else (row.get("content") or "")[:1500]
    return (title + "\n" + body).strip()


def main():
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("오류: .env에 SUPABASE_URL, SUPABASE_SERVICE_KEY가 없습니다.")
        return
    if not VOYAGE_API_KEY:
        print("오류: .env에 VOYAGE_API_KEY가 없습니다. (VOYAGE_API_KEY=pa-... 형식)")
        return

    rows = fetch_pending()
    if not rows:
        print("임베딩 대기 중인 보고서가 없습니다. 완료!")
        return

    print(f"임베딩 대상 보고서: {len(rows)}건 (모델: {VOYAGE_MODEL}, {EMBED_DIM}차원)")
    processed, errors = 0, 0

    for row in rows:
        text = build_text(row)
        if len(text.replace(" ", "")) < 5:
            print(f"  - id {row['id']}: 텍스트가 비어 건너뜀")
            continue
        retry, ok = 0, False
        while retry < 5 and not ok:
            try:
                emb = get_voyage_embeddings([text])[0]
                update_embedding(row["id"], emb)
                processed += 1
                print(f"  ✓ id {row['id']}  {row.get('title','')[:40]}")
                ok = True
            except requests.HTTPError as e:
                retry += 1
                errors += 1
                wait = 5 * retry
                if e.response is not None and e.response.status_code == 429:
                    ra = e.response.headers.get("Retry-After")
                    wait = int(ra) + 1 if ra else min(30 * retry, 120)
                print(f"\n  HTTP 오류 (재시도 {retry}/5, {wait}s 대기): {e}")
                time.sleep(wait)
            except Exception as e:
                retry += 1
                errors += 1
                print(f"\n  오류 (재시도 {retry}/5): {e}")
                time.sleep(3)
        time.sleep(0.3)

    print(f"\n✅ 완료! {processed}건 임베딩 저장 (오류: {errors}건)")
    if processed and processed < len(rows):
        print("일부 미처리 — 다시 실행하면 남은 행만 재시도됩니다.")


if __name__ == "__main__":
    main()
