"""
kb_documents(DB) → regulatory-kb 번들(파일) 역동기화.

대시보드 승인 훅이 자동 생성하는 OKF 요약(family='web-upload' 등)은 브라우저가 번들
파일을 쓸 수 없어 DB에만 존재한다. 이 스크립트가 그 간극을 메운다(번들=요약의 유일한
백업·수정이력이므로 주기 실행 권장 — 지침 §표준 작업 패턴):

  ① manifest에 없는 path의 kb_documents 행 → 번들 md 파일 생성 + manifest 항목 추가
  ② manifest에 있는 항목의 status/superseded_by가 DB와 다르면 → manifest를 DB 기준으로 갱신
     (브라우저 supersede 처리 반영. import_regulatory_kb는 manifest status를 정본으로 쓴다)

멱등: 재실행해도 같은 결과. 파일을 삭제하지는 않는다(번들→DB 방향은 import_regulatory_kb.py).

사용법:
  python sync_kb_to_bundle.py --dry-run   # 변경 예정 목록만 출력
  python sync_kb_to_bundle.py             # 실제 파일·manifest 갱신 (이후 git add/commit은 수동)

필요 .env: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import sys
import json
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).parent
BUNDLE = ROOT / "regulatory-kb"
MANIFEST = BUNDLE / "manifest.json"


def load_env():
    env = {}
    envp = ROOT / ".env"
    if envp.exists():
        for line in envp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def fetch_all_kb_documents(sb):
    """kb_documents 전행 — PostgREST max-rows 1000 절단 대비 range 페이지네이션(지침 가드레일)."""
    rows, page, start = [], 1000, 0
    while True:
        r = (sb.table("kb_documents")
             .select("dedup_key,title,concept_type,family,law_type,law_number,"
                     "enforcement_date,competent_authority,status,superseded_by,"
                     "path,description,body_md")
             .order("id").range(start, start + page - 1).execute())
        batch = r.data or []
        rows.extend(batch)
        if len(batch) < page:
            return rows
        start += page


def is_bill_row(row):
    """concept_type='Bill'(국회 계류 법안 요약, 2026-09-04). path는 bills/<year>/<의안번호>.md 규약."""
    return (row.get("concept_type") or "") == "Bill" or (row.get("path") or "").startswith("bills/")


def bill_dedup_key(row):
    """법안 dedup_key 규칙 = `제목|의안#의안번호` (import_regulatory_kb.bill_dedup_key와 동일 —
    같은 이름의 개정안이 제안자만 다르게 여럿이라 법령 규칙 `제목|law_type`로는 뭉친다)."""
    title = (row.get("title") or "").strip()
    return f"{title}|의안#{(row.get('law_number') or '').strip()}"


def build_md(row):
    """행 컬럼으로 frontmatter를 재구성해 번들 md 파일 내용 생성 (본문은 body_md 그대로).
    Bill 행도 같은 frontmatter 형식으로 왕복한다(type: Bill / law_type: 의안 / law_number: 의안번호 /
    enforcement_date: 발의일) — import_regulatory_kb.build_doc_row가 manifest 값이 비면 이 frontmatter를 읽는다."""
    fm = ["---"]
    fm.append(f"type: {row.get('concept_type') or ('Bill' if is_bill_row(row) else 'Notice')}")
    fm.append(f"title: {row.get('title') or ''}")
    if row.get("description"):
        fm.append(f"description: {row['description']}")
    for k in ("law_type", "law_number", "enforcement_date", "competent_authority"):
        if row.get(k):
            fm.append(f"{k}: {row[k]}")
    fm.append(f"status: {row.get('status') or 'current'}")
    if row.get("superseded_by"):
        fm.append(f"superseded_by: {row['superseded_by']}")
    fm.append("---")
    return "\n".join(fm) + "\n\n" + (row.get("body_md") or "")


def manifest_entry(row):
    bill = is_bill_row(row)
    dedup_key = row.get("dedup_key")
    if bill and (not dedup_key or "#" not in dedup_key):
        dedup_key = bill_dedup_key(row)          # 의안번호 규칙으로 보정(DB 행이 규칙 이전에 들어온 경우)
    if bill and not (row.get("path") or "").startswith("bills/"):
        print(f"  ⚠️ Bill 행의 path가 bills/ 밖: {row.get('path')} — 재적재 시 family가 'bills'로 잡히지 않는다")
    e = {
        "dedup_key": dedup_key,
        "title": row.get("title"),
        "law_type": row.get("law_type") or ("의안" if bill else None),
        "law_number": row.get("law_number"),
        "enforcement_date": row.get("enforcement_date"),
        "concept_type": row.get("concept_type") or ("Bill" if bill else None),
        "path": row["path"],
        "status": row.get("status") or "current",
    }
    if row.get("superseded_by"):
        e["superseded_by"] = row["superseded_by"]
    return e


def main():
    dry = "--dry-run" in sys.argv
    env = load_env()
    url, key = env.get("SUPABASE_URL", ""), env.get("SUPABASE_SERVICE_KEY", "")
    if not (url and key):
        print("오류: .env에 SUPABASE_URL, SUPABASE_SERVICE_KEY 필요")
        sys.exit(1)
    if not MANIFEST.exists():
        print(f"오류: manifest 없음 → {MANIFEST}")
        sys.exit(1)

    import sb_client
    sb = sb_client.make_client(url, key)

    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = m["entries"]
    by_path = {e["path"]: e for e in entries}

    rows = fetch_all_kb_documents(sb)
    print(f"kb_documents {len(rows)}행 / manifest {len(entries)}항목  (dry-run={dry})")

    new_files, status_fixes = [], []
    for row in rows:
        path = row.get("path")
        if not path:
            continue
        if path not in by_path:
            new_files.append(row)
        else:
            e = by_path[path]
            if (e.get("status") != row.get("status")
                    or e.get("superseded_by") != row.get("superseded_by")):
                status_fixes.append((e, row))

    if not new_files and not status_fixes:
        print("✅ 이미 동기화 상태 — 변경 없음")
        return

    for row in new_files:
        print(f"  + 신규 파일: {row['path']}  ({row.get('title','')[:40]})")
    for e, row in status_fixes:
        print(f"  ~ status 갱신: {e['path']}  {e.get('status')} → {row.get('status')}"
              + (f" (superseded_by {row.get('superseded_by')})" if row.get("superseded_by") else ""))

    if dry:
        print("[dry-run] 실제 변경 없음.")
        return

    for row in new_files:
        fp = BUNDLE / row["path"]
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(build_md(row), encoding="utf-8")
        entries.append(manifest_entry(row))
    for e, row in status_fixes:
        e["status"] = row.get("status") or e.get("status")
        if row.get("superseded_by"):
            e["superseded_by"] = row["superseded_by"]

    m["entry_count"] = len(entries)
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 완료: 신규 파일 {len(new_files)}건, status 갱신 {len(status_fixes)}건")
    print("   변경분 커밋: git add regulatory-kb && git commit (PC 터미널)")


if __name__ == "__main__":
    main()
