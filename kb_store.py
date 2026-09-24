"""
KB(document_chunks · law_watch) 적재 공용 (2026-09-25, #218 — 개선안 §4-2-12 단계 B).

복사본으로 흩어져 있던 네 가지를 한 곳에 둔다. 새 적재 코드는 반드시 여기를 쓴다.
  ① insert_chunks  — 조각 일괄 삽입 + 삽입 건수 검증. 8개 파일 10곳 중 검증은 3곳뿐이었다.
     검증이 없으면 배치 중간의 statement timeout이 '부분 적재'를 완료로 위장한다 — 대한민국
     주파수 분배표가 1,089조각 중 150조각만 들어간 채 방치된 실사고(law_sync reingest 주석).
  ② register_watch — law_watch '현행본 등록' 한 행(12칸). 모양이 같은 upsert가 5곳에 있었다.
  ③ 조각 규칙 두 가지 — chunk_pdf_text(800/100, 조문 경계 우선: upload_law_pdf·kb_reextract)와
     chunk_by_newline(700 무겹침: press_ingest·issue_case_ingest). 같은 규칙이 각각 두 벌이었다.
     API 조문 단위 law_sync.chunk_articles·마크다운 헤더 단위 import_regulatory_kb.chunk_body는 단독이라 제외.
  ④ list_docs      — 문서명 목록. DB 함수 kb_doc_names 1회(페이지 단위) — 종전엔 조각 5만 행을
     1,000행씩 수십 번 훑었고(현행 42번 4.6초) 두 곳은 순서 없이 나눠 읽어 누락·중복 위험이 있었다.

minutes_offline._swap_doc은 임시 사본 → 내용 대조 → 교체라는 자체 검증이 있어 그대로 둔다.
"""
import re
from datetime import datetime, timezone

INSERT_BATCH = 50

# ③-a PDF·원문 파일 조각 규칙 (upload_law_pdf·kb_reextract 공용 — 두 경로의 결과가 같아야 재추출이 원본과 맞는다)
PDF_CHUNK_SIZE = 800
PDF_CHUNK_OVERLAP = 100
PDF_MIN_CHUNK = 50
_ARTICLE_HEAD_RE = re.compile(r'(?=^제\d+조(?:의\d+)?\()', re.MULTILINE)
_ARTICLE_NO_RE = re.compile(r'제(\d+조(?:의\d+)?\([^)]*\))')

# ③-b 줄바꿈 무겹침 조각 규칙 (보도자료·이슈 사례 공용 — 기존 수동 업로드분과 같은 700자, 이어붙이면 원문 복원)
NEWLINE_CHUNK_SIZE = 700


def chunk_pdf_text(text: str, size: int = PDF_CHUNK_SIZE, overlap: int = PDF_CHUNK_OVERLAP,
                   min_chunk: int = PDF_MIN_CHUNK) -> list:
    """조문 헤더(줄 시작의 '제N조(제목)') 경계 우선, 없으면 크기 기준으로 자른다.
    헤더가 5조각 미만으로만 나뉘면 조문 문서로 보지 않고 통째로 크기 분할한다.
    반환: [{'content': str, 'article_no': '3조(정의)' | None}] — min_chunk자 이하 조각은 버린다."""
    splits = _ARTICLE_HEAD_RE.split(text)
    if len(splits) < 5:
        splits = [text]
    chunks = []
    for block in splits:
        block = block.strip()
        if not block:
            continue
        m = _ARTICLE_NO_RE.match(block)
        article_no = m.group(1) if m else None
        if len(block) <= size:
            chunks.append({'content': block, 'article_no': article_no})
        else:
            start = 0
            while start < len(block):
                chunks.append({'content': block[start:start + size], 'article_no': article_no})
                start += size - overlap
    return [c for c in chunks if len(c['content'].strip()) > min_chunk]


def chunk_by_newline(text: str, size: int = NEWLINE_CHUNK_SIZE) -> list:
    """size 근처(뒤 30% 안)의 개행에서 끊는 무겹침 분할 — 이어붙이면 원문이 복원된다.
    공백뿐인 조각은 버린다(글자 손실 0이 필요한 곳은 minutes_offline._chunk_exact)."""
    chunks, pos, n = [], 0, len(text)
    while pos < n:
        end = min(pos + size, n)
        if end < n:
            nl = text.rfind('\n', pos + int(size * 0.7), end)
            if nl > pos:
                end = nl + 1
        chunks.append(text[pos:end])
        pos = end
    return [c for c in chunks if c.strip()]


def insert_chunks(sb, rows: list, *, batch: int = INSERT_BATCH, verify: bool = True,
                  progress: bool = False) -> int:
    """document_chunks에 rows를 batch개씩 넣고, 문서별로 들어간 건수를 확인한다.

    검증: 문서(doc_name)마다 넣은 chunk_index 범위(·status가 한 가지면 그 status)의 행 수가
    넣은 행 수와 같아야 한다. 기존 문서 뒤에 이어 붙이는 경우(보도자료)도 범위로 세므로 맞다.
    어긋나면 RuntimeError — 부분 적재를 완료로 넘기지 않는다. 반환: 넣은 행 수.
    """
    total = len(rows)
    for i in range(0, total, batch):
        sb.table('document_chunks').insert(rows[i:i + batch]).execute()
        if progress:
            print('  업로드: %d/%d' % (min(i + batch, total), total), end='\r')
    if progress and total:
        print()
    if not verify or not total:
        return total
    groups = {}
    for r in rows:
        groups.setdefault(r['doc_name'], []).append(r)
    for doc, rs in groups.items():
        idx = [r['chunk_index'] for r in rs]
        q = (sb.table('document_chunks').select('id', count='exact')
             .eq('doc_name', doc).gte('chunk_index', min(idx)).lte('chunk_index', max(idx)))
        statuses = {r.get('status') for r in rs}
        if len(statuses) == 1 and None not in statuses:
            q = q.eq('status', statuses.pop())
        got = q.limit(1).execute().count or 0
        if got != len(rs):
            raise RuntimeError('삽입 검증 실패: %s — %d조각을 넣었는데 같은 범위에서 %d조각 확인됨 '
                               '(%s — 확인 후 재실행)' % (doc[:60], len(rs), got,
                                                    '부분 적재' if got < len(rs) else '같은 번호 중복'))
    return total


def register_watch(sb, *, doc_name: str, law_name: str, law_type_token, api_target: str,
                   law_id, mst, law_no, enf, note: str, now: str = None,
                   replaces: str = None) -> None:
    """law_watch에 '이 문서가 현행본 — 다음 감시부터 기준'으로 등록(doc_name 기준 upsert).
    replaces: 이 등록이 대신하는 옛 문서명 — 다르면 그 행을 지운다(행이 새 문서명으로 옮겨감)."""
    now = now or datetime.now(timezone.utc).isoformat()
    sb.table('law_watch').upsert({
        'doc_name': doc_name, 'law_name': law_name,
        'law_type_token': law_type_token, 'api_target': api_target,
        'law_id': law_id, 'registered_mst': mst,
        'registered_law_no': law_no, 'registered_enf': enf,
        'latest_mst': mst, 'latest_law_no': law_no, 'latest_enf': enf,
        'watch_status': 'watching', 'sync_status': 'current',
        'last_checked_at': now, 'updated_at': now,
        'note': note,
    }, on_conflict='doc_name').execute()
    if replaces and replaces != doc_name:
        sb.table('law_watch').delete().eq('doc_name', replaces).execute()


def list_docs(sb, *, status: str = None, category: str = None, page: int = 1000) -> dict:
    """KB 문서명 → doc_category (문서명 순). DB 함수 kb_doc_names(서버 전용)를 페이지 단위로 부른다
    — 결과(문서 수백 개)도 PostgREST 1,000행 상한을 받으므로 range로 끝까지 읽는다."""
    out, start = {}, 0
    params = {'p_status': status, 'p_category': category}
    while True:
        rows = sb.rpc('kb_doc_names', params).range(start, start + page - 1).execute().data or []
        for r in rows:
            out[r['doc_name']] = r.get('doc_category')
        if len(rows) < page:
            return out
        start += page
