"""
이슈맵 — 과거 사례 문서 적재 (2026-08-26 신설).

내부 뉴스는 60일 롤링이라 오래된 사건(예: 2G 종료, 5G 과장광고 제재)의 경과가 DB에 없다.
Claude 세션에서 웹 리서치로 작성한 사례 문서(마크다운)를 지식베이스에 넣어
① 이슈 상세의 '과거 유사 사례' ② AI 자문 RAG 양쪽에서 검색되게 한다.

사용:
    python issue_case_ingest.py 사례.md --title "2G 종료" [--issue 3] [--dry-run]

동작:
    document_chunks(doc_category='이슈사례', doc_name='이슈사례_{제목}.md')에 700자 무겹침 청킹 적재
    → Voyage 임베딩 즉시 생성 → --issue 지정 시 issue_links(item_type='kb_case')로 이슈에 연결.

주의:
    - 같은 doc_name이 이미 있으면 기본 거부(--replace로 교체).
    - 청킹·임베딩 규약은 press_ingest.py / backfill_embeddings.py와 동일해야 한다
      (다른 규약으로 넣으면 하이브리드 검색에서 이 문서만 밀린다).
"""

import argparse
import os
import re
import sys

# cp949 콘솔에서 이모지 print 크래시 방지 (지침 가드레일 #19)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv

from sb_client import make_client
from embed_util import get_embeddings

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")

CHUNK_SIZE = 700          # press_ingest.CHUNK_SIZE와 동일 — 어긋나면 검색 품질이 갈린다
DOC_CATEGORY = "이슈사례"
EMBED_BATCH = 64
INSERT_BATCH = 3          # HNSW 인덱스 갱신 부하 — 크게 잡으면 statement timeout(57014)


def chunk_text(text: str, size: int = CHUNK_SIZE) -> list:
    """size 근처의 개행에서 끊는 무겹침 분할 (press_ingest._chunk_text와 동일 규약)."""
    chunks, pos, n = [], 0, len(text)
    while pos < n:
        end = min(pos + size, n)
        if end < n:
            nl = text.rfind("\n", pos + int(size * 0.7), end)
            if nl > pos:
                end = nl + 1
        chunks.append(text[pos:end])
        pos = end
    return [c for c in chunks if c.strip()]


def slugify_title(s: str) -> str:
    """doc_name에 쓸 수 있게 경로 구분자·공백만 정리 (한글은 그대로 둔다)."""
    s = re.sub(r"[\\/:*?\"<>|]", "", s).strip()
    return re.sub(r"\s+", "_", s)[:60]


def parse_title(md: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", md, re.M)
    return m.group(1).strip() if m else fallback


def main() -> int:
    ap = argparse.ArgumentParser(description="이슈맵 과거 사례 문서를 지식베이스에 적재")
    ap.add_argument("path", help="사례 문서(.md) 경로")
    ap.add_argument("--title", help="사례 제목 (없으면 문서의 첫 '# 제목' 사용)")
    ap.add_argument("--issue", type=int, help="연결할 이슈 id (issue_links에 kb_case로 추가)")
    ap.add_argument("--replace", action="store_true", help="같은 doc_name이 있으면 교체")
    ap.add_argument("--dry-run", action="store_true", help="DB 무변경 — 청킹 결과만 출력")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print("[오류] 파일 없음: %s" % args.path)
        return 1
    with open(args.path, encoding="utf-8") as f:
        md = f.read().strip()
    if not md:
        print("[오류] 빈 문서")
        return 1

    title = (args.title or parse_title(md, os.path.basename(args.path))).strip()
    doc_name = "이슈사례_%s.md" % slugify_title(title)
    chunks = chunk_text(md)
    print("[사례] %s" % title)
    print("  doc_name : %s" % doc_name)
    print("  청크     : %d개 (%d자)" % (len(chunks), len(md)))

    if args.dry_run:
        for i, c in enumerate(chunks[:3]):
            print("  --- chunk %d ---\n%s" % (i, c[:200]))
        print("[dry-run] DB 변경 없음")
        return 0

    if not (SUPABASE_URL and SUPABASE_SERVICE_KEY):
        print("[오류] SUPABASE_URL / SUPABASE_SERVICE_KEY 미설정")
        return 1
    sb = make_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    exists = sb.table("document_chunks").select("id").eq("doc_name", doc_name).limit(1).execute().data
    if exists:
        if not args.replace:
            print("[중단] 이미 등재된 문서입니다. 교체하려면 --replace")
            return 1
        sb.table("document_chunks").delete().eq("doc_name", doc_name).execute()
        print("  기존 청크 삭제 후 재등재")

    # 임베딩을 먼저 만들고 한 번에 넣는다 — 중간 실패 시 임베딩 없는 청크가 남지 않게.
    vectors = []
    for i in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[i:i + EMBED_BATCH]
        vectors.extend(get_embeddings(batch, input_type="document", api_key=VOYAGE_API_KEY))
        print("  임베딩 %d/%d" % (min(i + EMBED_BATCH, len(chunks)), len(chunks)))

    rows = [{
        "doc_name":     doc_name,
        "doc_category": DOC_CATEGORY,
        "chunk_index":  i,
        "content":      c,
        "embedding":    vectors[i],
        "is_approved":  True,
        "status":       "current",
    } for i, c in enumerate(chunks)]
    # document_chunks는 4만 행 + HNSW 인덱스라 벡터를 한 번에 많이 넣으면 statement timeout이 난다
    # (컴퓨트 RAM 2GB). 작게 나눠 넣는다.
    for i in range(0, len(rows), INSERT_BATCH):
        sb.table("document_chunks").insert(rows[i:i + INSERT_BATCH]).execute()
        print("  등재 %d/%d" % (min(i + INSERT_BATCH, len(rows)), len(rows)))
    print("  등재 완료: %d청크" % len(rows))

    if args.issue:
        iss = sb.table("issues").select("id,title").eq("id", args.issue).maybe_single().execute().data
        if not iss:
            print("[경고] 이슈 %d 없음 — 연결 생략" % args.issue)
        else:
            sb.table("issue_links").upsert({
                "issue_id":  args.issue,
                "item_type": "kb_case",
                "item_id":   doc_name,
                "title":     title,
                "added_by":  "operator",
            }, on_conflict="issue_id,item_type,item_id").execute()
            print("  이슈 연결: [%d] %s" % (iss["id"], iss["title"]))

    return 0


if __name__ == "__main__":
    sys.exit(main())
