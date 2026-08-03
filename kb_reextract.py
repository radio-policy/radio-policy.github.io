"""
KB 원문 재추출·복구 (2026-08-03 신설)

지식베이스(document_chunks)에 등재됐지만 **본문이 거의 안 뽑힌 문서**를 원본에서 다시
추출해 교체한다. 대표 사례: 발표자료 PDF가 슬라이드 전체를 JPEG로 래스터화해 텍스트층이
219자밖에 없던 건(251218 하이퍼 네트워크 전략 스터디 발표자료).

추출 사다리 (앞 단계가 충분하면 뒤 단계는 건너뛴다)
  ① pdftotext -layout   ② pdfplumber   ③ OCR(pdftoppm → tesseract kor+eng)
  · HWPX(ZIP+XML)는 press_ingest와 같은 방식으로 태그 제거 추출
  · 구형 HWP(OLE)는 이 PC에 파서가 없다 → 추출 불가로 보고 (설치 금지 방침)

교체는 문서 1건씩. 교체 전 기존 청크를 JSON으로 백업하므로 --restore 로 되돌릴 수 있다.
청킹 규약(800자/100자 겹침·조문 헤더 우선·50자 미만 폐기)은 upload_law_pdf.py와 동일하다.

사용법:
  # 후보 진단 — status='current' 문서의 본문 총량·원본형식·추출실패 징후
  python kb_reextract.py --scan [--max-chars 3200]

  # 원본이 로컬 파일인 경우 (PDF/HWPX)
  python kb_reextract.py --doc-name "251218 (별첨) 하이퍼 네트워크 전략 스터디 발표자료.pdf" \
      --source "D:/path/발표자료.pdf" --dry-run
  python kb_reextract.py --doc-name "..." --source "D:/path/발표자료.pdf" --force-ocr

  # 원본이 법제처 첨부파일인 경우 (행정규칙명으로 검색 → 첨부 PDF/HWPX 중 최장본 채택)
  python kb_reextract.py --doc-name "재난안전무선통신망 주요 요구기능(행정안전부공고)(제2011-76호)(20110310)" \
      --from-law --dry-run

  # 되돌리기
  python kb_reextract.py --restore <백업JSON경로>

필요 .env: SUPABASE_URL, SUPABASE_SERVICE_KEY, (법제처 경로) LAW_OC_KEY, VOYAGE_API_KEY(백필)

주의
  · 교체 후 반드시 임베딩 백필이 돌아야 한다(기본 자동 실행, --no-backfill로 생략 가능).
  · 웹 요청 전에 세션이 주입한 HTTP(S)_PROXY를 제거한다(지침 가드레일 — 프록시가 SSL을 깬다).
  · 표·수식이 많은 자료의 OCR은 수치 오독 위험이 있다. OCR 본문에는 머리말로 그 사실을 남긴다.
"""

import argparse
import html as html_mod
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

# cp949 콘솔에서 한글/이모지 print 크래시 방지 (지침 가드레일 #19)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 세션 주입 프록시 제거 — 정부·법제처 사이트 SSL 검증이 깨진다
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_k, None)

import requests  # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import sb_client  # noqa: E402

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SERVICE_KEY")
OC_KEY = os.getenv("LAW_OC_KEY")

CHUNK_SIZE = 800          # upload_law_pdf.py와 동일 — 규약 일치 필수
CHUNK_OVERLAP = 100
MIN_CHUNK = 50

DRF_SEARCH = "https://www.law.go.kr/DRF/lawSearch.do"
DRF_SERVICE = "https://www.law.go.kr/DRF/lawService.do"
UA = {"User-Agent": "Mozilla/5.0"}

BACKUP_DIR = Path(os.getenv(
    "KB_REEXTRACT_BACKUP",
    r"C:\Users\SKTELE~1\AppData\Local\Temp\claude\C--Users-SKTelecom-Desktop-frequence-radio-policy-ai"
    r"\f3a8282f-cc88-4ad3-b536-2766d14aa171\scratchpad\kb_backup",
))

OCR_HEADER = ("[본 문서는 원본이 이미지(그림)로만 되어 있어 OCR로 추출했습니다. "
              "수치·표 값은 원본 확인이 필요합니다.]")


# ── 외부 실행파일 탐색 ────────────────────────────────────────────────
def _which(name, prefer=()):
    """알려진 경로를 PATH보다 먼저 본다.

    Git for Windows가 딸려 보내는 mingw64\\bin\\pdftotext는 구버전이라 한글 임베드 PDF에서
    본문을 거의 못 뽑는다(재난안전무선통신망 공고 실측: winget Poppler 3,569자 vs Git판 354자).
    PATH를 먼저 뒤지면 Git판이 잡히므로 순서를 뒤집었다.
    """
    for c in prefer:
        if c and os.path.exists(c):
            return c
    return shutil.which(name) or ""


_POPPLER = (r"C:\Users\SKTelecom\AppData\Local\Microsoft\WinGet\Packages"
            r"\oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe"
            r"\poppler-25.07.0\Library\bin")
PDFTOTEXT = _which("pdftotext", [os.path.join(_POPPLER, "pdftotext.exe")])
PDFTOPPM = _which("pdftoppm", [os.path.join(_POPPLER, "pdftoppm.exe")])
PDFINFO = _which("pdfinfo", [os.path.join(_POPPLER, "pdfinfo.exe")])
TESSERACT = _which("tesseract", [r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                                 r"C:\Users\SKTelecom\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"])


# ── 텍스트 추출 ──────────────────────────────────────────────────────
def _nonspace(t: str) -> int:
    return len(re.sub(r"\s+", "", t or ""))


def pdf_text_layer(path: str) -> str:
    """① pdftotext -layout → ② pdfplumber.

    같은 분량이면 -layout 을 쓴다. 표가 있는 공고문에서 pdfplumber는 셀을 읽는 순서가
    뒤섞여(열 머리글이 본문 사이에 끼어든다) 사람이 읽기 어려운 본문이 나온다.
    실측(재난안전무선통신망 주요 요구기능 (전문).pdf): 글자 수는 비슷한데 -layout 만
    '구분 / 주요 요구기능 / 설명' 3열 순서를 유지했다.
    """
    layout = ""
    if PDFTOTEXT:
        try:
            o = subprocess.run([PDFTOTEXT, "-layout", path, "-"],
                               capture_output=True, timeout=300)
            layout = o.stdout.decode("utf-8", "replace")
        except Exception:
            pass
    plumber = ""
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            plumber = "\n\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception:
        pass
    # 실질 글자 수가 20% 이상 많을 때만 pdfplumber 채택
    if _nonspace(plumber) > _nonspace(layout) * 1.2:
        return plumber
    return layout or plumber


def pdf_page_count(path: str) -> int:
    if not PDFINFO:
        return 0
    try:
        o = subprocess.run([PDFINFO, path], capture_output=True, timeout=60)
        m = re.search(r"Pages:\s+(\d+)", o.stdout.decode("utf-8", "replace"))
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def pdf_ocr(path: str, dpi: int = 400, page_marker: str = "슬라이드") -> str:
    """이미지-전용 PDF를 페이지별로 렌더링해 OCR. 페이지 표지를 남겨 청크 경계를 읽기 쉽게 한다.

    dpi 400은 실측 선택 — 원본 슬라이드가 200ppi JPEG라 200dpi에서는 한글 오독이 심했고,
    400dpi 업스케일에서 문장 단위로 읽히기 시작했다(가로쓰기 본문 기준).
    """
    if not (PDFTOPPM and TESSERACT):
        print("  ! OCR 도구 없음 (pdftoppm/tesseract) — 건너뜀")
        return ""
    n = pdf_page_count(path) or 0
    tmp = tempfile.mkdtemp(prefix="kb_ocr_")
    parts = []
    try:
        for pg in range(1, (n or 1) + 1):
            stem = os.path.join(tmp, "pg")
            r = subprocess.run([PDFTOPPM, "-png", "-r", str(dpi), "-f", str(pg), "-l", str(pg),
                                path, stem], capture_output=True, timeout=300)
            if r.returncode != 0:
                continue
            pngs = [f for f in sorted(os.listdir(tmp)) if f.lower().endswith(".png")]
            if not pngs:
                continue
            img = os.path.join(tmp, pngs[0])
            o = subprocess.run([TESSERACT, img, "stdout", "-l", "kor+eng", "--psm", "3"],
                               capture_output=True, timeout=300)
            txt = o.stdout.decode("utf-8", "replace").replace("\x0c", "").strip()
            os.remove(img)
            txt = _tidy_ocr(txt)
            if len(txt) >= 20:
                parts.append(f"[{page_marker} {pg}]\n{txt}")
            print(f"    OCR {pg}/{n} … {len(txt)}자", end="\r")
        print()
        return "\n\n".join(parts)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _tidy_ocr(t: str) -> str:
    """OCR 잡음 정리 — 의미 없는 기호 줄, 과다 공백."""
    if not t:
        return ""
    lines = []
    for ln in t.split("\n"):
        s = ln.strip()
        if not s:
            continue
        # 한글·영문·숫자가 하나도 없는 줄(테두리·아이콘 잔상)은 버린다
        if not re.search(r"[가-힣A-Za-z0-9]", s):
            continue
        # 글자 대비 기호 비율이 지나치게 높은 줄도 잡음
        letters = len(re.findall(r"[가-힣A-Za-z0-9]", s))
        if letters < 2 or letters / len(s) < 0.34:
            continue
        s = re.sub(r"[ \t]{2,}", " ", s)
        lines.append(s)
    out = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def hwpx_text(data: bytes) -> str:
    """HWPX = ZIP+XML (press_ingest._hwpx_to_text와 동일 규칙)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        parts = []
        for n in sorted(x for x in zf.namelist()
                        if x.startswith("Contents/section") and x.endswith(".xml")):
            xml = zf.read(n).decode("utf-8", "replace")
            xml = re.sub(r"</hp:p>", "\n", xml)
            parts.append(html_mod.unescape(re.sub(r"<[^>]+>", "", xml)))
        return "\n".join(parts)
    except Exception:
        return ""


def clean_text(t: str) -> str:
    if not t:
        return ""
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    # HWPX 그림 대체텍스트 / 한글 필드 제어문자열
    t = re.sub(r"(?m)^\s*(그림입니다\.?|원본 그림의 이름\s*:.*|원본 그림의 크기\s*:.*)\s*$\n?", "", t)
    t = re.sub(r"\d*Clickhere:set:\d+:[^\n]*?HelpState:wstring:\d+:[^\n]*", " ", t)
    t = re.sub(r"(?m)^\s*-\s*\d+\s*-\s*$\n?", "", t)          # 쪽번호 - 1 -
    # -layout 정렬 여백은 열 구분 단서만 남기고 줄인다 (청크 800자를 공백이 잠식하지 않도록)
    t = re.sub(r"[ ]{4,}", "   ", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def extract_any(path: str, force_ocr: bool = False, ocr_trigger: int = 500,
                page_marker: str = "슬라이드") -> tuple:
    """(본문, 사용한 방법) 반환."""
    data = open(path, "rb").read(8)
    if data[:4] == b"%PDF":
        layer = clean_text(pdf_text_layer(path))
        if force_ocr or len(re.sub(r"\s+", "", layer)) < ocr_trigger:
            print(f"  텍스트층 {len(layer):,}자 → OCR 시도")
            ocr = clean_text(pdf_ocr(path, page_marker=page_marker))
            if len(ocr) > len(layer) * 1.5:
                return (OCR_HEADER + "\n\n" + ocr, "OCR")
            return (layer, "텍스트층(OCR 개선 없음)")
        return (layer, "재추출(pdftotext/pdfplumber)")
    if data[:2] == b"PK":
        return (clean_text(hwpx_text(open(path, "rb").read())), "재추출(HWPX)")
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return ("", "구형 HWP(OLE) — 이 PC에 파서 없음")
    # 평문
    try:
        return (clean_text(open(path, encoding="utf-8").read()), "재추출(텍스트)")
    except Exception:
        return ("", "알 수 없는 형식")


# ── 법제처 첨부파일 경로 ──────────────────────────────────────────────
def law_attachment_best(doc_name: str, api_target: str = "admrul") -> tuple:
    """행정규칙/법령의 첨부파일 중 본문으로 쓸 만한 PDF/HWPX를 골라 (bytes, 파일명) 반환.
    개정이유서·신구조문대비표는 본문이 아니므로 제외한다."""
    if not OC_KEY:
        raise SystemExit("오류: .env에 LAW_OC_KEY 필요")
    base = re.sub(r"\(.*$", "", doc_name).strip()
    key_s = "AdmRulSearch" if api_target == "admrul" else "LawSearch"
    key_r = "admrul" if api_target == "admrul" else "law"
    r = requests.get(DRF_SEARCH, params={"OC": OC_KEY, "target": api_target, "type": "JSON",
                                         "query": base, "display": "20"}, timeout=40, headers=UA)
    rows = json.loads(r.text).get(key_s, {}).get(key_r) or []
    if isinstance(rows, dict):
        rows = [rows]
    hit = next((x for x in rows
                if (x.get("행정규칙명") or x.get("법령명한글") or "").strip() == base), None) \
        or (rows[0] if rows else None)
    if not hit:
        return (b"", "")
    sid = hit.get("행정규칙일련번호") or hit.get("법령일련번호")
    d = json.loads(requests.get(DRF_SERVICE,
                                params={"OC": OC_KEY, "target": api_target, "ID": sid, "type": "JSON"},
                                timeout=60, headers=UA).text)
    body = d.get("AdmRulService") or d.get("LawService") or {}
    att = body.get("첨부파일") or {}
    links = att.get("첨부파일링크")
    names = att.get("첨부파일명")
    links = [links] if isinstance(links, str) else (links or [])
    names = [names] if isinstance(names, str) else (names or [])
    best, bestname = b"", ""
    for l, n in zip(links, names):
        if re.search(r"개정이유|개정안|신구|이유서", n or ""):
            continue
        low = (n or "").lower()
        if not (low.endswith(".pdf") or low.endswith(".hwpx")):
            continue
        try:
            c = requests.get(l, timeout=90, headers=UA).content
        except Exception:
            continue
        if len(c) > len(best):
            best, bestname = c, n
    return (best, bestname)


# ── 청킹 (upload_law_pdf.py 규약과 동일) ──────────────────────────────
def chunk_text(text: str) -> list:
    header = re.compile(r"(?=^제\d+조(?:의\d+)?\()", re.MULTILINE)
    splits = header.split(text)
    if len(splits) < 5:
        splits = [text]
    chunks = []
    for block in splits:
        block = block.strip()
        if not block:
            continue
        m = re.match(r"제(\d+조(?:의\d+)?\([^)]*\))", block)
        article_no = m.group(1) if m else None
        if len(block) <= CHUNK_SIZE:
            chunks.append({"content": block, "article_no": article_no})
        else:
            start = 0
            while start < len(block):
                chunks.append({"content": block[start:start + CHUNK_SIZE], "article_no": article_no})
                start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c for c in chunks if len(c["content"].strip()) > MIN_CHUNK]


# ── DB ───────────────────────────────────────────────────────────────
def make_sb():
    if not (SB_URL and SB_KEY):
        raise SystemExit("오류: .env에 SUPABASE_URL, SUPABASE_SERVICE_KEY 필요")
    return sb_client.make_client(SB_URL, SB_KEY)


def fetch_chunks(sb, doc_name):
    out, off = [], 0
    while True:
        d = (sb.table("document_chunks").select("*")
             .eq("doc_name", doc_name).eq("status", "current")
             .order("chunk_index").range(off, off + 999).execute().data) or []
        out += d
        if len(d) < 1000:
            break
        off += 1000
    return out


def backup_chunks(doc_name, rows):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^0-9A-Za-z가-힣]+", "_", doc_name)[:60]
    p = BACKUP_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{safe}.json"
    slim = [{k: v for k, v in r.items() if k != "embedding"} for r in rows]
    p.write_text(json.dumps({"doc_name": doc_name, "rows": slim}, ensure_ascii=False, indent=1),
                 encoding="utf-8")
    return p


def replace_doc(sb, doc_name, chunks, doc_category, keep_meta):
    sb.table("document_chunks").delete().eq("doc_name", doc_name).eq("status", "current").execute()
    rows = []
    for i, c in enumerate(chunks):
        row = {"doc_name": doc_name, "doc_category": doc_category,
               "chunk_index": i, "content": c["content"], "status": "current"}
        if c.get("article_no"):
            row["article_no"] = c["article_no"]
        for k in ("notice_no", "effective_date", "law_id", "law_mst", "file_path", "is_approved"):
            if keep_meta.get(k) is not None:
                row[k] = keep_meta[k]
        rows.append(row)
    for i in range(0, len(rows), 50):
        sb.table("document_chunks").insert(rows[i:i + 50]).execute()
    return len(rows)


# ── 명령 ─────────────────────────────────────────────────────────────
def cmd_scan(sb, max_chars):
    docs = {}
    off = 0
    while True:
        d = (sb.table("document_chunks").select("doc_name, doc_category, content")
             .eq("status", "current").range(off, off + 999).execute().data) or []
        if not d:
            break
        for r in d:
            k = r["doc_name"]
            e = docs.setdefault(k, {"cat": r.get("doc_category"), "n": 0, "len": 0, "img": 0, "byeol": 0})
            e["n"] += 1
            c = r.get("content") or ""
            e["len"] += len(c)
            e["img"] += ('<img id=' in c)
            e["byeol"] += ("별표와 같다" in c)
        off += 1000
    rows = [(k, v) for k, v in docs.items() if v["len"] < max_chars]
    rows.sort(key=lambda x: x[1]["len"])
    print(f"=== 본문 {max_chars}자 미만 문서 {len(rows)}건 (전체 {len(docs)}건) ===")
    print(f"{'글자':>7} {'청크':>4} {'img':>3} {'별표':>4}  형식  문서명")
    for k, v in rows:
        ext = (re.search(r"\.(pdf|md|hwpx?|txt)$", k, re.I) or [None, "api"])[1]
        print(f"{v['len']:7d} {v['n']:4d} {v['img']:3d} {v['byeol']:4d}  {ext:5s} {k[:80]}")
    print("\n※ 짧다고 모두 실패는 아니다 — 조문+부칙이 온전한 짧은 고시·공고가 다수다.")
    print("  실패 징후: 원본이 PDF/발표자료인데 수백 자, 본문이 <img>·'별표와 같다'로만 지시됨.")


def cmd_restore(sb, path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    doc_name, rows = d["doc_name"], d["rows"]
    sb.table("document_chunks").delete().eq("doc_name", doc_name).eq("status", "current").execute()
    payload = [{k: v for k, v in r.items() if k != "id"} for r in rows]
    for i in range(0, len(payload), 50):
        sb.table("document_chunks").insert(payload[i:i + 50]).execute()
    print(f"복원 완료: {doc_name} — {len(payload)}청크 (임베딩은 백필 필요)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="복구 후보 진단만")
    ap.add_argument("--max-chars", type=int, default=3200, help="--scan 임계 글자수")
    ap.add_argument("--doc-name", help="교체할 등재 문서명(정확히 일치)")
    ap.add_argument("--source", help="원본 파일 경로(PDF/HWPX/TXT)")
    ap.add_argument("--from-law", action="store_true", help="법제처 첨부파일에서 원본 확보")
    ap.add_argument("--api-target", default="admrul", choices=["admrul", "law"])
    ap.add_argument("--force-ocr", action="store_true", help="텍스트층이 있어도 OCR 수행")
    ap.add_argument("--page-marker", default="슬라이드", help="OCR 페이지 표지 낱말")
    ap.add_argument("--dry-run", action="store_true", help="추출·비교만, DB 미변경")
    ap.add_argument("--no-backfill", action="store_true")
    ap.add_argument("--restore", help="백업 JSON으로 되돌리기")
    a = ap.parse_args()

    sb = make_sb()

    if a.restore:
        cmd_restore(sb, a.restore)
        return
    if a.scan or not a.doc_name:
        cmd_scan(sb, a.max_chars)
        return

    old = fetch_chunks(sb, a.doc_name)
    if not old:
        raise SystemExit(f"오류: 등재 문서를 찾지 못했습니다 → {a.doc_name}")
    old_len = sum(len(r["content"] or "") for r in old)
    cat = old[0].get("doc_category")
    keep = {k: old[0].get(k) for k in ("notice_no", "effective_date", "law_id", "law_mst",
                                      "file_path", "is_approved")}
    print(f"▶ {a.doc_name}")
    print(f"  현재: {len(old)}청크 / {old_len:,}자 (category={cat})")

    tmp_path = None
    if a.from_law:
        data, fname = law_attachment_best(a.doc_name, a.api_target)
        if not data:
            print("  ! 법제처 첨부파일에서 본문 후보를 찾지 못함 (구형 HWP만 있거나 첨부 없음)")
            return
        suffix = ".pdf" if data[:4] == b"%PDF" else (".hwpx" if data[:2] == b"PK" else ".bin")
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        os.write(fd, data)
        os.close(fd)
        print(f"  원본: 법제처 첨부 '{fname}' ({len(data):,}바이트)")
        src = tmp_path
    else:
        if not a.source:
            raise SystemExit("오류: --source 또는 --from-law 가 필요합니다")
        src = a.source
        if not os.path.exists(src):
            raise SystemExit(f"오류: 원본 파일 없음 → {src}")
        print(f"  원본: {src}")

    try:
        text, how = extract_any(src, force_ocr=a.force_ocr, page_marker=a.page_marker)
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    print(f"  추출 방법: {how}")
    print(f"  추출 본문: {len(text):,}자")
    if len(text) < 200:
        print("  ! 추출 실패 — 교체하지 않습니다")
        return
    chunks = chunk_text(text)
    new_len = sum(len(c["content"]) for c in chunks)
    print(f"  청킹: {len(chunks)}청크 / {new_len:,}자  (기존 대비 {new_len / max(old_len,1):.1f}배)")
    for c in chunks[:3]:
        print("  ── 샘플 ──")
        print("   " + c["content"][:300].replace("\n", "\n   "))
    if new_len <= old_len * 1.2:
        print("  ! 증가폭이 작아 교체 실익이 없습니다 (1.2배 이하) — 중단")
        return
    if a.dry_run:
        print("  (dry-run) DB 변경 없음")
        return

    bpath = backup_chunks(a.doc_name, old)
    print(f"  백업: {bpath}")
    n = replace_doc(sb, a.doc_name, chunks, cat, keep)
    print(f"  교체 완료: {n}청크")

    if not a.no_backfill:
        print("\n[임베딩 백필]")
        subprocess.run([sys.executable, str(ROOT / "backfill_embeddings.py")], check=False)


if __name__ == "__main__":
    main()
