"""
regulatory-kb (OKF 법령 요약 번들) → Supabase kb_documents / kb_chunks 1회 적재.

- manifest.json(정본)을 순회해 각 concept 문서를 적재.
- 문서 메타(dedup_key/title/law_*/status 등)는 manifest, description/competent_authority/본문은 파일에서.
- 본문을 마크다운 섹션 단위로 청킹 → voyage-law-2(1024차원, input_type=document)로 임베딩 → kb_chunks.
- document_chunks(조문 원문)와 별개 레이어. 조문 인용은 그쪽, 요약·실무는 이쪽.

사용법:
  python import_regulatory_kb.py --dry-run    # 파싱·청크 수만 출력(적재 안 함)
  python import_regulatory_kb.py              # 실제 적재(경로별 idempotent: 재실행 시 덮어씀)

필요 .env: SUPABASE_URL, SUPABASE_SERVICE_KEY, VOYAGE_API_KEY
"""

import sys
import os
import re
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

# cp949 콘솔(스케줄러·파이프)에서 이모지/한글 print 크래시 방지 (지침 가드레일)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BUNDLE_DIR = Path(__file__).parent / "regulatory-kb"
MANIFEST = BUNDLE_DIR / "manifest.json"

VOYAGE_MODEL = "voyage-law-2"   # 법률 특화, 1024차원
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
VOYAGE_BATCH = 100
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100
SLEEP_SEC = 0.4


def load_env():
    """.env를 수동 파싱(외부 의존성 없이)."""
    env = {}
    envp = Path(__file__).parent / ".env"
    if envp.exists():
        for line in envp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "VOYAGE_API_KEY"):
        env.setdefault(k, os.getenv(k, ""))
    return env


ENV = load_env()
SB_URL = ENV.get("SUPABASE_URL", "").rstrip("/")
SB_KEY = ENV.get("SUPABASE_SERVICE_KEY", "")
VOYAGE_KEY = ENV.get("VOYAGE_API_KEY", "")


# ── HTTP helpers (stdlib) ─────────────────────────────────

def _req(method, url, headers, body=None, timeout=60):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
        return r.status, (json.loads(raw) if raw else None)


def _sb_headers(extra=None):
    h = {
        "apikey": SB_KEY,
        "Authorization": f"Bearer {SB_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def sb_delete_doc(path):
    url = f"{SB_URL}/rest/v1/kb_documents?path=eq.{urllib.parse.quote(path)}"
    _req("DELETE", url, _sb_headers())


def sb_insert_doc(row):
    url = f"{SB_URL}/rest/v1/kb_documents"
    status, data = _req("POST", url, _sb_headers({"Prefer": "return=representation"}), [row])
    return data[0]["id"]


def sb_insert_chunks(doc_id, contents, embeddings):
    url = f"{SB_URL}/rest/v1/rpc/insert_kb_chunks"
    p_emb = ["[" + ",".join(f"{v:.8f}" for v in e) + "]" for e in embeddings]
    _req("POST", url, _sb_headers(), {"p_doc_id": doc_id, "p_contents": contents, "p_embeddings": p_emb})


def voyage_embed(texts):
    body = {"model": VOYAGE_MODEL, "input": texts, "input_type": "document"}
    headers = {"Authorization": f"Bearer {VOYAGE_KEY}", "Content-Type": "application/json"}
    for attempt in range(5):
        try:
            _, data = _req("POST", VOYAGE_URL, headers, body, timeout=90)
            return [d["embedding"] for d in data["data"]]
        except urllib.error.HTTPError as e:
            wait = 30 if e.code == 429 else 5 * (attempt + 1)
            print(f"\n  Voyage HTTP {e.code} (재시도 {attempt+1}/5, {wait}s)")
            time.sleep(wait)
        except Exception as e:
            print(f"\n  Voyage 오류 (재시도 {attempt+1}/5): {e}")
            time.sleep(5)
    raise RuntimeError("Voyage 임베딩 실패(재시도 소진)")


# ── 파싱 ──────────────────────────────────────────────────

def split_frontmatter(text):
    """--- ... --- 프론트매터와 본문 분리. (키:값 스칼라만 파싱)"""
    fm = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end]
            body = text[end + 4:].lstrip("\n")
            for line in block.splitlines():
                if ":" in line and not line.lstrip().startswith("-"):
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip()
    return fm, body


def family_of(path):
    parts = path.replace("\\", "/").split("/")
    if parts[0] == "laws" and len(parts) > 2:
        return parts[1]
    return parts[0]


def chunk_body(body, title):
    """마크다운 헤더(#/##/###) 경계 우선 분할 후 크기 상한. 각 청크에 문서 제목 접두."""
    parts = re.split(r'(?=^#{1,3}\s)', body, flags=re.M)
    raw = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= CHUNK_SIZE:
            raw.append(p)
        else:
            start = 0
            while start < len(p):
                raw.append(p[start:start + CHUNK_SIZE])
                start += CHUNK_SIZE - CHUNK_OVERLAP
    out = []
    for c in raw:
        if len(c.strip()) < 30:
            continue
        out.append(f"[{title}] {c}")
    return out


# ── 메인 ──────────────────────────────────────────────────

def build_doc_row(entry, fm, body):
    ed = entry.get("enforcement_date") or None
    return {
        "dedup_key": entry.get("dedup_key") or None,
        "title": entry.get("title") or fm.get("title") or "",
        "concept_type": entry.get("concept_type") or fm.get("type") or None,
        "family": family_of(entry["path"]),
        "law_type": entry.get("law_type") or None,
        "law_number": entry.get("law_number") or None,
        "enforcement_date": ed,
        "competent_authority": fm.get("competent_authority") or None,
        "status": entry.get("status") or "current",
        "superseded_by": entry.get("superseded_by") or None,
        "path": entry["path"],
        "description": fm.get("description") or None,
        "body_md": body,
    }


def main():
    dry = "--dry-run" in sys.argv
    if not (SB_URL and SB_KEY and VOYAGE_KEY):
        print("오류: .env에 SUPABASE_URL, SUPABASE_SERVICE_KEY, VOYAGE_API_KEY 필요")
        sys.exit(1)
    if not MANIFEST.exists():
        print(f"오류: manifest 없음 → {MANIFEST}")
        sys.exit(1)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = manifest["entries"]

    # --only <부분문자열> [...] : 해당 path만 재적재. 개정 1~2건 반영에 전체 100여 건을
    # 다시 임베딩하는 낭비(및 그 사이 삭제-삽입 공백)를 피한다.
    if "--only" in sys.argv:
        pats = [a for a in sys.argv[sys.argv.index("--only") + 1:] if not a.startswith("--")]
        if not pats:
            print("오류: --only 뒤에 path(부분문자열)를 1개 이상 지정")
            sys.exit(1)
        entries = [e for e in entries if any(p in e["path"] for p in pats)]
        if not entries:
            print(f"오류: --only 패턴과 일치하는 manifest 항목 없음 → {pats}")
            sys.exit(1)
        print(f"--only 필터: {len(entries)}건 선택")

    print(f"manifest entries: {len(entries)}  (모델: {VOYAGE_MODEL}, dry-run={dry})")

    missing, total_chunks, done = [], 0, 0
    status_count = {}
    for entry in entries:
        fp = BUNDLE_DIR / entry["path"]
        if not fp.exists():
            missing.append(entry["path"])
            continue
        fm, body = split_frontmatter(fp.read_text(encoding="utf-8"))
        row = build_doc_row(entry, fm, body)
        chunks = chunk_body(body, row["title"])
        total_chunks += len(chunks)
        status_count[row["status"]] = status_count.get(row["status"], 0) + 1

        if dry:
            print(f"  · {row['status']:10s} {len(chunks):2d}청크  {entry['path']}")
            continue

        sb_delete_doc(row["path"])
        doc_id = sb_insert_doc(row)
        # 임베딩(배치)
        embs = []
        for i in range(0, len(chunks), VOYAGE_BATCH):
            embs.extend(voyage_embed(chunks[i:i + VOYAGE_BATCH]))
            time.sleep(SLEEP_SEC)
        sb_insert_chunks(doc_id, chunks, embs)
        done += 1
        print(f"  [{done}/{len(entries)}] {row['title'][:40]:40s} {len(chunks):2d}청크", end="\r")

    print()
    if missing:
        print(f"⚠️ manifest에 있으나 파일 없음 {len(missing)}건: " + ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else ""))
    print(f"status 분포: {status_count}")
    print(f"총 청크: {total_chunks}")
    if not dry:
        print(f"✅ 적재 완료: 문서 {done}건")


if __name__ == "__main__":
    main()
