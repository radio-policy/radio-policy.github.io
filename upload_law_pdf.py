"""
PDF/TXT 법령·고시 업로드 스크립트
사용법: python upload_law_pdf.py <파일경로> [문서명] [카테고리]

입력 파일: .pdf 또는 .txt (법령 본문 텍스트)
카테고리 선택: 법령 / 고시 / ITU-R / 전파법 / 전파법_시행령 / 전파법_시행규칙 등

예시:
  python upload_law_pdf.py 전파법.pdf "전파법(법률)(제21065호)(20260102)" 전파법
  python upload_law_pdf.py 전파법_텍스트.txt "전파법(법률)(제21065호)(20260102)" 전파법
  python upload_law_pdf.py 고시2024-10.pdf "전파연구원 고시 2024-10호" 고시
"""

import sys
import os
import re
from pathlib import Path
from dotenv import load_dotenv

# cp949 콘솔·파이프에서 이모지/한글 print 크래시 방지 (지침 가드레일 #19 —
# 이 크래시가 마지막 임베딩 백필 단계를 조용히 건너뛰게 만든 사고가 있었음)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def law_title_from_doc_name(doc_name: str) -> str:
    """doc_name → 반복 머리글 제거용 법령명. '전파법(법률)(...)' → '전파법'"""
    base = re.sub(r'\.(pdf|txt|md)$', '', (doc_name or '').strip())
    return base.split('(')[0].strip()


def clean_pdf_artifacts(text: str, law_title: str = "") -> str:
    """국가법령정보센터 PDF 추출 시 본문에 섞이는 편집 흔적 제거 (대시보드 lawmapCleanText와 동일 규칙).
      · [N페이지] 페이지 구분 표시  · '법제처 N 국가법령정보센터' 쪽 하단 footer
      · 페이지마다 반복되는 법령명 머리글(줄 전체가 법령명)  · 과다 공백/개행
    """
    if not text:
        return text
    text = re.sub(r'\[\s*\d+\s*페이지\s*\]', '', text)
    # footer는 '법제처 N 국가법령정보센터'가 표준이나 청킹 경계에서 'N 국가법령정보센터'/'국가법령정보센터'로 잘리기도 함
    text = re.sub(r'(?:법제처\s*)?\d*\s*국가법령정보센터', '', text)
    title = (law_title or '').strip()
    if title:
        text = '\n'.join(ln for ln in text.split('\n') if ln.strip() != title)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_text_from_pdf(pdf_path: str) -> str:
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if text:
                    text_parts.append(text.strip())
                print(f"  페이지 {i}/{total} 처리 중...", end="\r")
        print()
        return "\n\n".join(text_parts)
    except ImportError:
        print("pdfplumber 미설치. 설치 중...")
        os.system(f"{sys.executable} -m pip install pdfplumber --quiet")
        return extract_text_from_pdf(pdf_path)


def chunk_text(text: str) -> list:
    """텍스트를 청크로 분할 (조문 헤더 경계 우선, 없으면 크기 기준)
    조문 헤더는 줄 시작의 제N조(제목) 형식만 인식 — 인용 번호 오태깅 방지 (2026-06-12).
    """
    header_pattern = re.compile(r'(?=^제\d+조(?:의\d+)?\()', re.MULTILINE)
    splits = header_pattern.split(text)
    if len(splits) < 5:
        splits = [text]

    chunks = []
    for block in splits:
        block = block.strip()
        if not block:
            continue
        m = re.match(r'제(\d+조(?:의\d+)?\([^)]*\))', block)
        article_no = m.group(1) if m else None
        if len(block) <= CHUNK_SIZE:
            chunks.append({'content': block, 'article_no': article_no})
        else:
            start = 0
            while start < len(block):
                end = start + CHUNK_SIZE
                chunks.append({'content': block[start:end], 'article_no': article_no})
                start += CHUNK_SIZE - CHUNK_OVERLAP

    return [c for c in chunks if len(c['content'].strip()) > 50]


def parse_chunk_metadata(content: str, doc_name: str) -> dict:
    meta = {}
    m = re.search(r'(\d{4}-\d+)', doc_name)
    if not m:
        m = re.search(r'제(\d{4}-\d+)호', content[:300])
    if m:
        meta['notice_no'] = m.group(1)
    m = re.search(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일[^.]{0,30}시행', content)
    if m:
        meta['effective_date'] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return meta


def upload_to_supabase(doc_name: str, doc_category: str, chunks: list) -> bool:
    try:
        from supabase import create_client
    except ImportError:
        print("supabase 미설치. 설치 중...")
        os.system(f"{sys.executable} -m pip install supabase --quiet")
        from supabase import create_client

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("오류: .env 파일에 SUPABASE_URL, SUPABASE_SERVICE_KEY가 없습니다.")
        return False

    from sb_client import make_client
    client = make_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    existing = client.table("document_chunks").select("id").eq("doc_name", doc_name).execute()
    if existing.data:
        print(f"  기존 '{doc_name}' 청크 {len(existing.data)}개 삭제 중...")
        client.table("document_chunks").delete().eq("doc_name", doc_name).execute()

    rows = []
    for i, chunk in enumerate(chunks):
        row = {"doc_name": doc_name, "doc_category": doc_category, "chunk_index": i, "content": chunk['content']}
        if chunk.get('article_no'):
            row['article_no'] = chunk['article_no']
        row.update(parse_chunk_metadata(chunk['content'], doc_name))
        rows.append(row)

    batch_size = 50
    total = len(rows)
    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        client.table("document_chunks").insert(batch).execute()
        print(f"  업로드: {min(i + batch_size, total)}/{total}", end="\r")
    print()

    existing_doc = client.table("documents").select("id").eq("name", doc_name).execute()
    doc_meta = {"name": doc_name, "type": doc_category, "status": "최신"}
    if existing_doc.data:
        client.table("documents").update(doc_meta).eq("name", doc_name).execute()
    else:
        client.table("documents").insert(doc_meta).execute()

    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"오류: 파일을 찾을 수 없습니다 → {pdf_path}")
        sys.exit(1)

    doc_name = sys.argv[2] if len(sys.argv) >= 3 else Path(pdf_path).stem
    doc_category = sys.argv[3] if len(sys.argv) >= 4 else "고시"

    VALID_CATEGORIES = (
        "법령", "고시", "ITU-R",
        "전파법", "전파법_시행령", "전파법_시행규칙",
        "전기통신사업법", "전기통신사업법_시행령",
        "방송통신발전기본법", "방송통신발전기본법_시행령",
        "기술기준", "적합성평가", "주파수할당", "주파수분배표",
        "전자파", "정보통신망법", "정보통신기반시설", "방송통신설비",
    )
    if doc_category not in VALID_CATEGORIES:
        print(f"오류: 지원하지 않는 카테고리입니다 (입력값: {doc_category})")
        print(f"  허용값: {', '.join(VALID_CATEGORIES)}")
        sys.exit(1)

    suffix = Path(pdf_path).suffix.lower()
    print(f"\n[1/4] 텍스트 추출: {pdf_path}")
    if suffix == ".txt":
        with open(pdf_path, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = extract_text_from_pdf(pdf_path)
    print(f"  추출된 텍스트: {len(text):,}자")

    # PDF 편집 흔적(페이지 표시·법제처 footer·반복 머리글) 제거 — 저장 전 정리 (배경역사 #28)
    before = len(text)
    text = clean_pdf_artifacts(text, law_title_from_doc_name(doc_name))
    if before != len(text):
        print(f"  PDF 편집 흔적 정리: {before:,} → {len(text):,}자")

    if len(text) < 100:
        print("오류: 텍스트가 너무 짧습니다.")
        sys.exit(1)

    print(f"[2/4] 텍스트 청킹")
    chunks = chunk_text(text)
    print(f"  생성된 청크: {len(chunks)}개 (평균 {sum(len(c['content']) for c in chunks)//len(chunks)}자)")

    print(f"[3/4] Supabase 업로드: doc_name='{doc_name}', category='{doc_category}'")
    success = upload_to_supabase(doc_name, doc_category, chunks)

    if success:
        print(f"\n✅ 완료! '{doc_name}' → document_chunks {len(chunks)}개 저장됨")
        print(f"   대시보드 AI 자문에서 바로 검색 가능합니다.")
        print(f"\n[4/4] 임베딩 백필 실행 중...")
        import subprocess
        backfill_script = Path(__file__).parent / "backfill_embeddings.py"
        result = subprocess.run([sys.executable, str(backfill_script)])
        if result.returncode != 0:
            print("⚠️  임베딩 백필 실패 — 수동으로 python backfill_embeddings.py 실행 필요")
    else:
        print("\n❌ 업로드 실패")
        sys.exit(1)


if __name__ == "__main__":
    main()
