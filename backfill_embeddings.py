"""
Voyage AI 임베딩 백필 스크립트
사용법: python backfill_embeddings.py

- voyage-4-lite 모델로 document_chunks 전체 임베딩 생성
- 100개씩 배치로 Voyage API 호출 → batch_update_embeddings RPC로 저장
- 완료 후 HNSW 인덱스 자동 생성
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
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")  # .env에 보관 (공개 repo에 하드코딩 금지!)

VOYAGE_MODEL    = "voyage-4-lite"
EMBED_DIM       = 1024

# ── 결제수단 등록 여부에 따라 한도가 완전히 다름 ──
#   Tier 1 (Voyage 대시보드에 카드 등록, 무료 2억 토큰은 그대로 유지):
#     voyage-4-lite = 2000 RPM / 16M TPM → 아래 기본값으로 ~5분 내 완료
#   카드 미등록 (약 3 RPM / 10K TPM):
#     VOYAGE_BATCH=4, SLEEP_SEC=21 로 변경 필요 → 전체 ~22시간 소요
VOYAGE_BATCH    = 100   # Voyage API 배치 크기
FETCH_BATCH     = 500   # Supabase에서 한 번에 가져올 청크 수
SLEEP_SEC       = 0.5   # 배치 간 대기


# ── Supabase REST helpers ─────────────────────────────────

def _sb_headers(extra=None):
    h = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def count_null_embeddings():
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/document_chunks",
        headers=_sb_headers({"Prefer": "count=exact"}),
        params={"embedding": "is.null", "status": "neq.superseded", "select": "id"},
    )
    resp.raise_for_status()
    cr = resp.headers.get("content-range", "0/0")
    return int(cr.split("/")[1]) if "/" in cr else 0


def fetch_chunks(offset, limit=FETCH_BATCH):
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/document_chunks",
        headers=_sb_headers(),
        params={
            "select": "id,content",
            "embedding": "is.null",
            # 구본(superseded)은 검색 결과에서 걸러지므로 임베딩하지 않는다 — RAM 최적화 (2026-08-02, #54)
            "status": "neq.superseded",
            "order": "id.asc",
            "offset": offset,
            "limit": limit,
        },
    )
    resp.raise_for_status()
    return resp.json()


def batch_update_rpc(ids, embeddings):
    """batch_update_embeddings RPC 호출 (한 번에 최대 100행)"""
    p_embeddings = [
        "[" + ",".join(f"{v:.8f}" for v in emb) + "]"
        for emb in embeddings
    ]
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/batch_update_embeddings",
        headers=_sb_headers(),
        json={"p_ids": ids, "p_embeddings": p_embeddings},
    )
    resp.raise_for_status()


# ── Voyage AI helper ──────────────────────────────────────

def get_voyage_embeddings(texts):
    resp = requests.post(
        "https://api.voyageai.com/v1/embeddings",
        headers={
            "Authorization": f"Bearer {VOYAGE_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": VOYAGE_MODEL,
            "input": texts,
            "input_type": "document",  # 청크는 'document'
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return [item["embedding"] for item in data["data"]]


# ── HNSW 인덱스 생성 ─────────────────────────────────────

def create_hnsw_index():
    print("\n[최종] HNSW 인덱스 생성 중 (embedding <=> 코사인)...")
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/batch_update_embeddings",  # dummy call to warm connection
        headers=_sb_headers(),
        json={"p_ids": [], "p_embeddings": []},
    )
    # 인덱스는 SQL로만 가능 — 안내만 출력
    print("  ※ HNSW 인덱스는 Supabase SQL Editor에서 아래 쿼리 실행 필요:")
    print()
    print("  CREATE INDEX IF NOT EXISTS document_chunks_embedding_hnsw_idx")
    print("    ON document_chunks USING hnsw (embedding vector_cosine_ops)")
    print("    WITH (m = 16, ef_construction = 64);")
    print()


# ── 메인 ────────────────────────────────────────────────

def main():
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("오류: .env에 SUPABASE_URL, SUPABASE_SERVICE_KEY가 없습니다.")
        return
    if not VOYAGE_API_KEY:
        print("오류: .env에 VOYAGE_API_KEY가 없습니다. (VOYAGE_API_KEY=pa-... 형식으로 추가)")
        return

    total = count_null_embeddings()
    print(f"임베딩 없는 청크: {total:,}개 (모델: {VOYAGE_MODEL}, {EMBED_DIM}차원)")
    if total == 0:
        print("모든 청크에 임베딩이 있습니다. 완료!")
        return

    processed = 0
    errors = 0
    perm_failed = 0  # 재시도 소진으로 건너뛴 청크 수
    # 주의: is.null 필터라서 성공한 행은 다음 조회에서 빠짐
    #       → offset은 '영구 실패 수'만큼만 줘야 행 누락이 없음 (기존 offset 페이징은 버그)

    while True:
        chunks = fetch_chunks(perm_failed, FETCH_BATCH)
        if not chunks:
            break

        for i in range(0, len(chunks), VOYAGE_BATCH):
            batch = chunks[i : i + VOYAGE_BATCH]
            texts = [c["content"] for c in batch]
            ids   = [c["id"]      for c in batch]

            retry = 0
            ok = False
            while retry < 5:
                try:
                    embeddings = get_voyage_embeddings(texts)
                    batch_update_rpc(ids, embeddings)
                    processed += len(batch)
                    pct = processed / total * 100
                    print(f"  {processed:>6,}/{total:,} ({pct:5.1f}%)  "
                          f"id {ids[0]}~{ids[-1]}      ", end="\r")
                    ok = True
                    break
                except requests.HTTPError as e:
                    retry += 1
                    errors += 1
                    # 429: Retry-After 헤더 우선, 없으면 지수 대기
                    if e.response is not None and e.response.status_code == 429:
                        ra = e.response.headers.get("Retry-After")
                        wait = int(ra) + 1 if ra else min(30 * retry, 120)
                    else:
                        wait = 5 * retry
                    print(f"\n  HTTP 오류 (재시도 {retry}/5, {wait}s 대기): {e}")
                    time.sleep(wait)
                except Exception as e:
                    retry += 1
                    errors += 1
                    print(f"\n  오류 (재시도 {retry}/5): {e}")
                    time.sleep(3)

            if not ok:
                perm_failed += len(batch)
                print(f"\n  ⚠️ {len(batch)}개 청크 건너뜀 (id {ids[0]}~{ids[-1]})")

            time.sleep(SLEEP_SEC)

    if perm_failed:
        print(f"\n⚠️ 영구 실패 {perm_failed}개 — 스크립트를 다시 실행하면 재시도됩니다.")

    print(f"\n\n✅ 완료! {processed:,}개 임베딩 저장 (오류: {errors}개)")
    create_hnsw_index()


if __name__ == "__main__":
    main()
