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
    # embed_util 위임 (개선⑪): 429 Retry-After 우선 대기·재시도 5회, 소진 시 RuntimeError(기존과 동일).
    # api_key를 명시 전달 — 이 스크립트는 .env를 수동 파싱하므로 os.environ에 없을 수 있다.
    import embed_util
    return embed_util.get_embeddings(
        texts, input_type="document", model=VOYAGE_MODEL,
        dim=1024, api_key=VOYAGE_KEY, timeout=90,
    )


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
    if parts[0] == "bills":
        # bills/<year>/<bill_no>.md — 국회 계류 법안(concept_type='Bill'). 연도 하위 폴더는
        # 정리용일 뿐 family는 하나('bills')로 묶는다(자문 검색은 family를 안 보고 concept_type을 본다).
        return "bills"
    return parts[0]


# ── 법안(Bill) 문서 규칙 (2026-09-04) ─────────────────────────
#  국회 계류 법안 요약을 kb_documents에 넣되(concept_type='Bill', family='bills',
#  law_type='의안', law_number=의안번호, enforcement_date=발의일), 자문이 **확정 법령으로
#  오인하지 않도록** rag.ts/app.js buildKbContext가 concept_type='Bill'이면 라벨을
#  「법안요약 · 국회 계류 — 확정 법령 아님」으로 바꾼다.
#  dedup_key: 법령은 `제목|law_type`(add_law.dedup_key)이지만 법안은 **같은 이름의 개정안이
#  제안자만 다르게 여러 건** 공존하므로(전파법 일부개정법률안 ×N) 의안번호를 붙인다.
#    bills → `제목|의안#<의안번호>`  예) 전파법 일부개정법률안|의안#2215722
BILL_LAW_TYPE = "의안"
BILL_REQUIRED_SECTIONS = ("# 제안이유", "# 주요내용", "# 통신사업자 영향")
BILL_MIN_CHARS = 150


def bill_dedup_key(title, bill_no):
    t = re.sub(r"\s*\((구버전|현행)\)\s*", "", title or "").strip()
    return f"{t}|{BILL_LAW_TYPE}#{(bill_no or '').strip()}"


def is_bill_entry(entry, fm=None):
    ct = (entry.get("concept_type") or (fm or {}).get("type") or "")
    return ct == "Bill" or (entry.get("path") or "").replace("\\", "/").startswith("bills/")


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


# ── 적재 게이트 ────────────────────────────────────────────
#  OKF 본문이 **문장 중간에서 끊긴 채** 적재되는 사고가 반복됐다 (2026-08-03 표본점검에서
#  248건 중 24건 발견, 그중 23건이 8/2~8/3 배치에 집중). 원인은 모델 max_tokens가 아니라
#  "잘린 파일을 아무도 안 막는다"는 것 — 여기에 검증이 전혀 없어서 잘린 문서가 임베딩까지
#  그대로 통과했다. 내용은 정확한데 실무 체크리스트·Citations가 통째로 없는 문서가 자문 근거로
#  쓰이고 있었다.
#  ★ 문서 종류마다 정상적인 '끝나는 모양'이 다르다 ★ — 이걸 무시하고 '# Citations' 하나로
#  판정하면 멀쩡한 문서가 무더기로 거부된다(실측: 업무안내 38건 + ITU-R 9건 = 47건 오탐).
#    laws/…       OKF 법령 요약 → '# Citations' 섹션으로 끝난다
#    procedures/… 중앙전파관리소 업무안내 → 공공누리 고지 문구로 끝난다(크롤 산출물)
#    references/… ITU-R 권고 → '관련: ITU-R M.xxxx' 나열로 끝난다
#  그래서 종류를 먼저 가리고, 종류별 종료 표지를 본다. 어느 쪽이든 **말미 완결성**은 공통으로 본다.
#  닫는 괄호 ) ] 는 **완결 신호**다 — 처음에 이걸 '미완결'로 넣었다가 정상 문서 6건을 오탐했다
#  (`[1] 전기통신사업법 시행령(대통령령)(제36281호)(20260428).pdf` 같은 Citations 줄).
#  글자·숫자로 끝나는 것만 잘린 것으로 본다.
_INCOMPLETE_TAIL = re.compile(r'[가-힣A-Za-z0-9]$')


def check_body_complete(path: str, body: str):
    """반환: (ok, 사유). 잘린 본문을 적재 전에 잡는다 — 통과 못 하면 그 문서만 건너뛴다."""
    b = (body or "").strip()
    p = (path or "").replace("\\", "/")

    if p.startswith("bills/"):
        # 법안 요약(2026-09-04): Citations 대신 제안이유·주요내용·통신사업자 영향 3개 섹션이
        # 있어야 하고(마지막 섹션이 없으면 생성이 중간에 끊긴 것), 말미 완결성을 본다.
        if len(b) < BILL_MIN_CHARS:
            return False, f"본문이 너무 짧음({len(b)}자)"
        missing = [s for s in BILL_REQUIRED_SECTIONS if not re.search(r"^" + re.escape(s) + r"\s*$", b, re.M)]
        if missing:
            return False, "법안 필수 섹션 없음: " + ", ".join(missing)
        lines = b.rstrip().splitlines()
        tail = lines[-1].strip() if lines else ""
        if tail and not tail.startswith(("|", "-", "*", "#", ">")) and _INCOMPLETE_TAIL.search(tail):
            return False, f"마지막 줄이 문장 중간에서 끊김: …{tail[-40:]!r}"
        return True, ""

    if len(b) < 200:
        return False, f"본문이 너무 짧음({len(b)}자)"

    if "# Citations" in b:
        # 종료 표지에 도달했으면 완결이다. 말미 검사를 더 하면 안 된다 —
        # Citations 줄은 `…(제36281호)(20260428).pdf`, `…document_chunks) 기준`처럼
        # 파일명·명사로 끝나는 게 정상이라 어떤 말미 규칙을 써도 오탐이 난다(실측 6건).
        return True, ""
    if p.startswith("laws/"):
        # OKF 법령 요약은 Citations로 끝나는 게 규약이다. 없으면 끝까지 생성되지 않은 것.
        return False, "'# Citations' 섹션 없음 — 문서가 끝까지 생성되지 않았을 가능성"

    # Citations를 쓰지 않는 계열(procedures/ 업무안내, references/ ITU-R, glossary/)은
    # 말미 완결성만 본다.
    lines = b.rstrip().splitlines()
    tail = lines[-1].strip() if lines else ""
    # 표(|)·목록(-, *)·헤더(#)·인용(>)으로 끝나는 건 정상 형식이므로 말미 검사에서 제외.
    # 체크리스트('- [ ] …')로 끝나는 문서가 실제로 있어 목록 기호를 반드시 포함해야 한다.
    if tail and not tail.startswith(("|", "-", "*", "#", ">")) and _INCOMPLETE_TAIL.search(tail):
        return False, f"마지막 줄이 문장 중간에서 끊김: …{tail[-40:]!r}"
    return True, ""


# ── 메인 ──────────────────────────────────────────────────

def build_doc_row(entry, fm, body):
    ed = entry.get("enforcement_date") or fm.get("enforcement_date") or None
    title = entry.get("title") or fm.get("title") or ""
    law_type = entry.get("law_type") or fm.get("law_type") or None
    law_number = entry.get("law_number") or fm.get("law_number") or None
    dedup_key = entry.get("dedup_key") or None
    if is_bill_entry(entry, fm):
        # 법안: law_type '의안', law_number=의안번호, enforcement_date=발의일(YYYY-MM-DD).
        # dedup_key는 manifest 값이 있어도 의안번호 규칙(`제목|의안#번호`)을 강제한다 —
        # 같은 이름의 개정안(제안자만 다름)이 한 키로 뭉쳐 supersede되는 사고 방지.
        law_type = law_type or BILL_LAW_TYPE
        if law_number:
            dedup_key = bill_dedup_key(title, law_number)
        elif dedup_key and "#" not in dedup_key:
            print(f"  ⚠️ 법안 의안번호(law_number) 없음 — dedup_key에 '#'가 없음: {entry.get('path')}")
    return {
        "dedup_key": dedup_key,
        "title": title,
        "concept_type": entry.get("concept_type") or fm.get("type") or None,
        "family": family_of(entry["path"]),
        "law_type": law_type,
        "law_number": law_number,
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
            # dry-run은 "오늘 해당 항목이 0건"이 정상 답이 될 수 있다(예: --only bills/ 가 아직 비어 있을 때).
            # 실제 적재에서는 오타로 아무것도 안 적재되는 것을 잡기 위해 종전대로 오류.
            if dry:
                print(f"--only 필터: 0건 (일치 항목 없음 → {pats}) — dry-run 종료")
                return
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
