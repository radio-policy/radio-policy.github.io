"""
법령 추가 통합 스크립트 (Ⓑ) — 새 법령 PDF 1개로 두 레이어를 한 번에 갱신.

  ① 조문 원문 → document_chunks (기존 upload_law_pdf.py, voyage-4-lite)
  ② 요약·실무 문서 → Haiku가 OKF concept 초안 작성 → regulatory-kb/ 저장 + manifest.json 갱신
     → kb_documents/kb_chunks 적재 (voyage-law-2)

중복/버전 처리는 regulatory-kb/MAINTENANCE.md·manifest 규칙을 따른다:
  동일 law_number → 기존 path 덮어쓰기 / 최신본 → 기존 status='superseded'(+superseded_by) 후 신규 current / dedup_key 없음 → 신규.

사용법:
  python add_law.py <pdf> --title "전파법 시행규칙" --law-type 과학기술정보통신부령 \\
     --law-number 제157호 --enf-date 2026-07-01 --concept-type Regulation --family radio-act
  옵션: --category 고시(조문 업로드 카테고리) / --no-article(조문 생략) / --no-summary(요약 생략) / --dry-run

필요 .env: SUPABASE_URL, SUPABASE_SERVICE_KEY, VOYAGE_API_KEY, ANTHROPIC_API_KEY
"""

import sys
import os
import re
import json
import argparse
import subprocess
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# import_regulatory_kb의 적재 헬퍼 재사용(단일 문서 적재에 그대로 사용)
import import_regulatory_kb as ikb

ROOT = Path(__file__).parent
BUNDLE = ROOT / "regulatory-kb"
MANIFEST = BUNDLE / "manifest.json"
# OKF 요약은 Haiku가 아니라 Sonnet 5로 뽑는다 (2026-08-03).
#  · 법령 요약은 「~할 수 있다/하여야 한다」, 위임 범위, 예외 단서처럼 한 글자 차이로 뜻이 뒤집히는
#    작업이라 모델 체급이 실제 품질로 이어진다. 가장 싼 체급으로 돌리고 있던 게 오히려 이상했다.
#  · 비용은 문서당 약 $0.03 → $0.07. 법령 등재는 주 몇 건이라 총액이 무의미한 수준이다.
#  · Fable 5는 기각 — 장시간 자율 에이전트용이고 사고를 끌 수 없어 문서당 $0.33~0.58,
#    게다가 30일 데이터 보존이 강제된다. 요약이라는 좁은 일에 맞지 않는다.
ANTHROPIC_MODEL = "claude-sonnet-5"
# Sonnet 5는 사고(thinking)가 기본으로 켜져 있고 max_tokens가 **사고+본문 합계**를 제한한다.
# 종전 4096을 그대로 두면 요약이 중간에 잘린다 — 실측 본문이 3,600~4,300자라 여유가 없다.
ANTHROPIC_MAX_TOKENS = 16000

# OKF concept_type → upload_law_pdf.py 조문 카테고리(VALID_CATEGORIES) 매핑
_CAT_MAP = {"Law": "법령", "Regulation": "법령", "Notice": "고시",
           "Guideline": "고시", "Procedure": "고시", "Glossary": "고시"}


def norm_title(t):
    return re.sub(r"\s*\((구버전|현행)\)\s*", "", t or "").strip()


def dedup_key(title, law_type):
    return norm_title(title) + "|" + (law_type or "")


def slugify(title):
    base = re.sub(r"[^0-9a-zA-Z가-힣]+", "_", norm_title(title)).strip("_").lower()
    return (base[:60] or "law")


def anthropic_summarize(law_text, meta):
    """Haiku가 번들 형식의 OKF concept 마크다운(프론트매터+본문)을 초안 작성."""
    key = ikb.ENV.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError(".env에 ANTHROPIC_API_KEY 없음(--no-summary로 건너뛰거나 키 추가)")
    sys_prompt = (
        "너는 대한민국 전파·통신 규제 전문가다. 주어진 법령/고시 원문을 바탕으로 "
        "OKF 지식베이스용 마크다운 문서를 작성한다. 반드시 아래 형식만 출력(설명 문장 금지):\n"
        "--- 로 감싼 YAML frontmatter: type, title, description(한 문장), tags(목록), "
        "law_type, law_number, enforcement_date, competent_authority, status: current\n"
        "그 다음 본문 섹션: '# 요약' '# 적용 범위' '# 주요 내용(구조화)' '# 실무 체크리스트' '# Citations'.\n"
        "요약은 실무자가 이해하기 쉽게, 조문 번호는 본문에 인용하되 과장 없이 사실만."
    )
    user = (f"[메타] title={meta['title']} / law_type={meta['law_type']} / "
            f"law_number={meta['law_number']} / enforcement_date={meta['enf']} / "
            f"concept_type={meta['concept_type']} / competent_authority={meta.get('authority','')}\n\n"
            f"[원문 발췌]\n{law_text[:18000]}")
    body = {
        "model": ANTHROPIC_MODEL, "max_tokens": ANTHROPIC_MAX_TOKENS,
        "system": sys_prompt,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()


def update_manifest(entry):
    """on_readd_rule 적용: 동일 law_number 덮어쓰기 / 최신본 → 기존 superseded / 신규 추가.
    반환: (mode, superseded_path or None)"""
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = m["entries"]
    dk = entry["dedup_key"]
    same = [e for e in entries if e.get("dedup_key") == dk]
    superseded_path = None
    mode = "new"
    exact = next((e for e in same if e.get("law_number") == entry["law_number"]), None)
    if exact:
        exact.update(entry)  # 덮어쓰기(idempotent)
        mode = "overwrite"
    else:
        # 최신본으로 간주: 기존 current를 superseded 처리
        for e in same:
            if e.get("status") == "current":
                e["status"] = "superseded"
                e["superseded_by"] = entry["law_number"]
                superseded_path = e["path"]
        entries.append(entry)
        mode = "supersede" if same else "new"
    m["entry_count"] = len(entries)
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return mode, superseded_path


def ingest_one(path, status_override=None):
    """import_regulatory_kb 헬퍼로 단일 문서를 kb_*에 적재(idempotent)."""
    fp = BUNDLE / path
    fm, body = ikb.split_frontmatter(fp.read_text(encoding="utf-8"))
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = next((e for e in m["entries"] if e["path"] == path), None)
    if entry is None:
        raise RuntimeError(f"manifest에 {path} 없음")
    if status_override:
        entry = dict(entry, status=status_override)
    row = ikb.build_doc_row(entry, fm, body)
    chunks = ikb.chunk_body(body, row["title"])
    ikb.sb_delete_doc(path)
    doc_id = ikb.sb_insert_doc(row)
    embs = []
    for i in range(0, len(chunks), ikb.VOYAGE_BATCH):
        embs.extend(ikb.voyage_embed(chunks[i:i + ikb.VOYAGE_BATCH]))
    ikb.sb_insert_chunks(doc_id, chunks, embs)
    return len(chunks)


def set_status(path, status, superseded_by=None):
    """기존 kb_documents 행의 status만 갱신(구버전 처리 — 재임베딩 불필요)."""
    url = f"{ikb.SB_URL}/rest/v1/kb_documents?path=eq.{urllib.parse.quote(path)}"
    patch = {"status": status}
    if superseded_by:
        patch["superseded_by"] = superseded_by
    req = urllib.request.Request(url, data=json.dumps(patch).encode(),
        headers=ikb._sb_headers({"Prefer": "return=minimal"}), method="PATCH")
    urllib.request.urlopen(req, timeout=30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--title", required=True)
    ap.add_argument("--law-type", required=True)
    ap.add_argument("--law-number", required=True)
    ap.add_argument("--enf-date", default="")
    ap.add_argument("--concept-type", default="Notice")
    ap.add_argument("--family", default="radio-act")
    ap.add_argument("--authority", default="")
    ap.add_argument("--category", default=None, help="조문 업로드 카테고리(미지정 시 concept-type로 매핑)")
    ap.add_argument("--no-article", action="store_true")
    ap.add_argument("--no-summary", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    pdf = Path(a.pdf)
    if not pdf.exists():
        print(f"오류: 파일 없음 → {pdf}"); sys.exit(1)

    dk = dedup_key(a.title, a.law_type)
    folder = "procedures" if a.concept_type == "Procedure" else f"laws/{a.family}"
    rel_path = f"{folder}/{slugify(a.title)}.md"
    category = a.category or _CAT_MAP.get(a.concept_type, "고시")
    print(f"dedup_key: {dk}\n대상 path: {rel_path}\n조문 카테고리: {category}")

    if a.dry_run:
        print("[dry-run] 실제 변경 없음."); return

    # ① 조문 원문 → document_chunks (기존 스크립트 재사용, 임베딩 백필 자동)
    if not a.no_article:
        print("\n[①] 조문 원문 → document_chunks")
        subprocess.run([sys.executable, str(ROOT / "upload_law_pdf.py"), str(pdf), a.title, category], check=False)

    # ② 요약 → OKF 문서 + manifest + kb_*
    if not a.no_summary:
        print("\n[②] 요약 초안(Haiku) → regulatory-kb + kb_*")
        law_text = pdf.read_text(encoding="utf-8") if pdf.suffix.lower() == ".txt" else ikb_extract(pdf)
        # 조문 청킹과 동일하게 PDF 편집 흔적 제거 후 요약 입력 (footer/페이지표시/반복 머리글 — 토큰 절약·유출 방지)
        import upload_law_pdf as _ulp
        law_text = _ulp.clean_pdf_artifacts(law_text, _ulp.law_title_from_doc_name(a.title))
        meta = {"title": a.title, "law_type": a.law_type, "law_number": a.law_number,
                "enf": a.enf_date, "concept_type": a.concept_type, "authority": a.authority}
        md = anthropic_summarize(law_text, meta)
        (BUNDLE / rel_path).parent.mkdir(parents=True, exist_ok=True)
        (BUNDLE / rel_path).write_text(md, encoding="utf-8")
        entry = {"dedup_key": dk, "title": a.title, "law_type": a.law_type,
                 "law_number": a.law_number, "enforcement_date": a.enf_date,
                 "concept_type": a.concept_type, "path": rel_path, "status": "current"}
        mode, sup_path = update_manifest(entry)
        print(f"  manifest: {mode}" + (f" (구버전 superseded: {sup_path})" if sup_path else ""))
        if sup_path:
            set_status(sup_path, "superseded", a.law_number)   # 구버전 kb 행 상태만 갱신
        n = ingest_one(rel_path)
        print(f"  kb 적재: {rel_path} → {n}청크")
        print("  ⚠️ Haiku 초안입니다 — regulatory-kb의 해당 파일을 검토·보정하세요. 수정 후 재적재: python add_law.py 없이 import 헬퍼 재실행 가능.")

    print("\n✅ 완료. 커밋·푸시는 PC 터미널에서(app.js·index.html·regulatory-kb·manifest).")


def ikb_extract(pdf):
    """upload_law_pdf.extract_text_from_pdf 재사용."""
    import upload_law_pdf
    return upload_law_pdf.extract_text_from_pdf(str(pdf))


if __name__ == "__main__":
    main()
