# -*- coding: utf-8 -*-
"""법령 관계도 주제 엣지 점검 — "설명에 적힌 근거 조문이 대상 문서 원문에 실제로 있는가" (2026-09-05, 배경역사 #123)

배경: 2026-09-05 전수 검증에서 주제 엣지 356건 중 214건이 조문 오류·자리표시 설명이었다.
AI 즉석 생성(app.js saveLawmapData)이 조문을 검증 없이 저장한 것이 주원인이라 저장 전 관문을
넣었고, 이 스크립트는 그 두 번째 층(야간 전수 점검)이다. 17시 run_gov_crawler.bat 체인의
마지막 단계로 돌며, DB는 읽기만 한다(정정은 운영자·세션이 한다) — 예외 하나: 시행일이 지난 시행 표기 자동 정리(#275, 아래).

판정(엣지 1건당 하나):
  ERR placeholder   설명이 '관련 조문'·'제N조'·'(관련)' 같은 자리표시
  ERR art_missing   대상 문서는 KB에 있는데 설명의 자기 조문이 하나도 원문에 없음
  ERR no_article    조문 번호 없음 (대상 문서가 조문 체계를 갖췄고 미보유 꼬리표도 없을 때)
  WARN art_partial  자기 조문 일부만 원문에 있음
  WARN doc_missing  대상 문서가 KB에 없는데 '[원문 KB 미보유/미등재…]' 꼬리표가 없음
  OK                그 외
시행 전 조문 표기(#273, 2026-10-03) — 설명의 「YYYY.M.D 시행」을 읽어 덧씌운다:
  OK   pending_cited       시행일이 오늘 이후이고 KB에 그 시행일 판(문서명 끝 날짜)이 있다 — 요약에 「시행 전 조문 인용 N건」
  WARN pending_unverified  시행일이 오늘 이후인데 KB에 그 시행일 판이 없다
  WARN pending_expired     시행일이 지났다 — 표기를 떼고(또는 연·월만 남기고) 현행판과 대조. 주제 설명도 본다
  조 단위만 본다 — 시행예정판에서 항·호 번호가 바뀐 것(자기적합확인 제72조②4의3)은 사람·세션이 확인한다.
시행 표기 자동 정리(#275, 2026-10-04) — pending_expired인 선은 셋이 맞을 때만 설명을 고쳐 쓴다(OK pending_cleaned):
  ① clean_expired_marks가 정리됨(「YYYY.M.D 시행」→「YYYY.M 시행」, 맨 앞 「[시행예정 — … 시행]」·「※ 시행예정판(제N호) 기준, …」 절 삭제,
     정리 뒤 「시행예정·시행 전까지·현행판」이 안 남음) ② 대상의 현행본 중 시행일이 그 날 이상인 판이 있음(승격됨)
  ③ 정리한 설명이 judge OK이고 자기 조문이 모두 현행판에 있음. 주제 설명은 ①만 본다. 고친 전·후 전문을 운영자 봇에 보낸다(되돌리기 자료).
  예약 실행(알림 켬)에서만 쓴다 — --no-notify면 「자동 정리 예정」만 출력, --fix로 강제, --no-fix로 끔. 문장 뜻이 바뀌어야 하는 것
  (예: 「현행 시행령에 미반영」)은 날짜 표기가 없어 잡히지 않는다 — 사람·세션 몫.

타 법령 조문 인용("전파법 제15조의2에 적용", "법 제41조 위임")은 자기 조문으로 세지 않는다 —
바로 앞 낱말이 법령명(…법·령·규칙·고시·규정·기준·지침)이고 대상 노드명이 아니면 교차 인용.

실행: python lawmap_edge_check.py            # 전체 점검 출력 + 최근 30시간 생성 엣지의 문제만 운영자 텔레그램(무음)
      python lawmap_edge_check.py --no-notify --since-hours 0
      python lawmap_edge_check.py --notify-all  # 전체 문제를 텔레그램으로(전수 정정 직후 확인용)
종료 코드는 항상 0 — 체인의 다음 단계를 막지 않는다.
"""
import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")  # 스케줄러 cp949 캡처에서 이모지 print 사망 방지 (#19)

PLACEHOLDER_RE = re.compile(r"관련\s*조문|제N조|해당\s*조문|\(관련\)|^\s*관련\s*$")
MISSING_TAG_RE = re.compile(r"KB\s*미(보유|등재)")
# "제6조", "제19조의2", "제6·18조", "제67~68조", "제7·8·16조", "제18조의5~제18조의7"(뒤 항은 별도 매치)
ART_RE = re.compile(r"제\s*(\d+(?:\s*[·ㆍ,~∼\-]\s*\d+)*)\s*조(?:\s*의\s*(\d+))?")
ANNEX_RE = re.compile(r"(별표|별지|별첨|붙임|서식)\s*제?\s*\d+")
# 번호 없는 별표(별표가 하나뿐인 고시 — 원문 「[별 표]」, 이름표 「별표(제목)」, 옛 적재 「별표 ?(제목)」, #257 2026-09-29).
# 설명에 「별표」만 있으면 대상 문서에 번호 없는 그 종류 별표가 **실제로 있을 때만** 근거로 본다(없는 문서에서 통과시키지 않게)
BARE_ANNEX_RE = re.compile(r"(별표|별지|별첨|붙임|서식)(?!\s*제?\s*\d)")
BARE_LABEL_RE = re.compile(r"^(별표|별지|별첨|붙임|서식)\s*\??\s*(?:\(|$)")
# 교차 인용 판별: 조문 앞 낱말이 법령명으로 끝나는가
LAWWORD_RE = re.compile(r"([가-힣A-Za-z0-9·ㆍ]*(?:법|법률|령|영|규칙|고시|규정|기준|지침|조례|헌장|협정))\s*$")
LAW_ONLY_SUFFIX = ("법", "법률", "령", "규칙")           # 고시·지침이 '…법 제N조'를 자기 조문으로 가질 수는 없다
GENERIC_LAWWORDS = ("법", "령", "영", "규칙", "고시", "규정", "기준", "지침")   # "법 제N조"·"영 제N조" 식 약칭 → 항상 교차 인용
# 직전 조문에 연결부호(·, ~)로 이어진 조문은 앞 조문의 판정(자기/교차)을 그대로 따른다 (','는 새 문맥)
CONNECT_RE = re.compile(r"[·ㆍ~∼\-]\s*$")
DELEG_AFTER_RE = re.compile(r"^\s*(?:제\d+항|제\d+호|[①-⑳])*\s*(?:의\s*)?(?:위임|에\s*따른|에\s*의한|근거)")
EFFECTIVE_RE = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})\s*시행")   # 시행 전 조문 표기 「(2026.10.22 시행)」 (#273)
# 시행 표기 자동 정리(#275) — 맨 앞 「[시행예정 — 2027.3.10 시행] 」, 「 ※ 시행예정판(제N호) 기준, …」(그 절 끝까지 — 괄호·가운뎃점 앞에서 멈춤)
PENDING_PREFIX_RE = re.compile(r"^\s*\[시행예정\s*[—–\-]\s*\d{4}\.\d{1,2}\.\d{1,2}\s*시행\]\s*")
PENDING_NOTE_RE = re.compile(r"\s*※\s*시행예정판(?:\(제\d+호\))?\s*기준(?:[^()·]*[^()·\s])?")
PENDING_STALE_RE = re.compile(r"시행예정|시행\s*전까지|현행판")   # 정리 뒤에도 남으면 사람 몫(문장 뜻이 바뀌어야 하는 경우)
KST = timezone(timedelta(hours=9))


def nrm(s: str) -> str:
    """이름 대조용 정규화 — 공백·가운뎃점(·/ㆍ) 제거, .pdf/.md 꼬리 제거 (지침: 노드명↔문서명 대조는 정규화 후)."""
    s = re.sub(r"\.(pdf|md)$", "", str(s or ""), flags=re.I)
    return re.sub(r"[\s·ㆍ]", "", s)


def base_of(doc_name: str) -> str:
    """'전파법(법률)(제21553호)(20260421).pdf' → '전파법' ; '(과학기술정보통신부) X(고시)…' → 'X'"""
    name = re.sub(r"\.(pdf|md)$", "", str(doc_name or ""), flags=re.I).strip()
    name = re.sub(r"^\([^)]*\)\s*", "", name)
    name = re.sub(r"^\[[^\]]*\]\s*", "", name)
    i = name.find("(")
    return nrm(name[:i] if i > 0 else name)


def own_articles(description: str, target_name: str):
    """설명에서 대상 문서 자기 조문 키('19조의2' 형태)만 추출. (자기 조문 리스트, 교차 인용 수)"""
    own, cross = [], 0
    tname = nrm(target_name)
    prev_end, prev_own = None, None
    for m in ART_RE.finditer(description or ""):
        before = description[: m.start()]
        after = description[m.end():]
        keys = _expand_keys(m.group(1), m.group(2))
        if prev_end is not None and CONNECT_RE.search(description[prev_end:m.start()]) and prev_own is not None:
            is_own = prev_own                      # "전파법 제37조·제45조" — 뒤 조문도 전파법 것
        elif DELEG_AFTER_RE.search(after):
            is_own = False                         # "제50조 위임", "제9조에 따른" — 상위법 조문
        else:
            lw = LAWWORD_RE.search(before)
            if lw:
                word = nrm(lw.group(1))
                if not word or word in GENERIC_LAWWORDS:
                    is_own = False                 # "법 제N조", "영 제N조" — 상위법 약칭
                elif word.endswith(LAW_ONLY_SUFFIX) and not tname.endswith(LAW_ONLY_SUFFIX):
                    is_own = False                 # 대상이 고시·지침인데 '…법/령 제N조' → 상위법 조문 (노드명에 법명이 들어 있어도)
                else:
                    is_own = word in tname or tname in word   # 대상 노드명 자체(또는 그 일부)면 자기 조문
            else:
                is_own = True
        if is_own:
            own.extend(keys)
        else:
            cross += 1
        prev_end, prev_own = m.end(), is_own
    return list(dict.fromkeys(own)), cross


def _expand_keys(nums: str, ui):
    """'6·18' → ['6조','18조'] ; '67~68' → ['67조','68조'] ; ('19','2') → ['19조의2']"""
    out = []
    for part in re.split(r"[·ㆍ,]", nums):
        part = part.strip()
        rng = re.split(r"[~∼\-]", part)
        if len(rng) == 2 and rng[0].strip().isdigit() and rng[1].strip().isdigit():
            a, b = int(rng[0]), int(rng[1])
            if a <= b <= a + 10:
                out.extend(f"{n}조" for n in range(a, b + 1))
                continue
        if part.isdigit():
            out.append(f"{part}조")
    if ui and len(out) == 1:
        out[0] = out[0] + f"의{ui}"
    return out


def art_key(article_no: str) -> str:
    """document_chunks.article_no('제19조(…)' / '19조(…)') → '19조' / '19조의2'"""
    a = re.sub(r"^제", "", (article_no or "").strip())
    a = a.split("(")[0]
    return re.sub(r"\s", "", a)


def judge(description: str, target_name: str, doc_found: bool, doc_articles, doc_bare_annexes=()) -> tuple:
    """(level, code, detail). doc_articles: 원문 조문 키 집합(None=문서 미보유).
    doc_bare_annexes: 대상 문서에 있는 번호 없는 별표 종류('별표' 등, #257)."""
    d = description or ""
    if PLACEHOLDER_RE.search(d):
        return ("ERR", "placeholder", "자리표시 설명")
    if not doc_found:
        if MISSING_TAG_RE.search(d):
            return ("OK", "doc_missing_tagged", "")
        return ("WARN", "doc_missing", "대상 문서 KB 미보유 · 꼬리표 없음")
    own, cross = own_articles(d, target_name)
    if not doc_articles:
        # 공고·협정·NFTC·'제1호'식 고시처럼 article_no가 없는 문서 — 조문 대조 불가(설명은 있는 그대로 둔다)
        return ("OK", "no_article_scheme", "")
    if not own:
        if MISSING_TAG_RE.search(d):
            return ("OK", "tagged", "")
        if ANNEX_RE.search(d):
            return ("OK", "annex_ref", "")       # 별표·별지·서식 번호로 특정
        if any(k in (doc_bare_annexes or ()) for k in BARE_ANNEX_RE.findall(d)):
            return ("OK", "annex_ref", "")       # 번호 없는 별표 — 대상 문서에 그 별표가 있다(#257)
        if cross:
            return ("WARN", "cross_only", "타 법령 조문만 인용, 자기 조문 없음")
        return ("ERR", "no_article", "근거 조문 번호 없음")
    hit = [k for k in own if k in doc_articles]
    if not hit:
        return ("ERR", "art_missing", "원문에 없는 조문: " + "·".join("제" + k for k in own))
    if len(hit) < len(own):
        miss = [k for k in own if k not in doc_articles]
        return ("WARN", "art_partial", "일부 조문 원문에 없음: " + "·".join("제" + k for k in miss))
    return ("OK", "verified", "")


def not_current_articles(description: str, target_name: str, current_articles) -> list:
    """설명의 자기 조문 중 현행 판에 없는 것(#271). judge()는 모든 판의 합집합으로 존재를 보므로(구판 PDF 오탐 방지)
    개정으로 조문이 삭제·이동돼도 통과한다 — 그 구멍을 현행 판만 따로 대조해 메운다.
    current_articles가 비어 있으면(현행 판이 조문 체계 없음·미보유) 판정하지 않는다."""
    if not current_articles:
        return []
    own, _ = own_articles(description or "", target_name)
    return [k for k in own if k not in current_articles]


def effective_dates(description: str) -> list:
    """설명 안 「YYYY.M.D 시행」의 날짜들(#273). 「2026.1 시행」처럼 일이 없는 표기는 읽지 않는다 — 시행 뒤 남기는 꼴."""
    out = []
    for m in EFFECTIVE_RE.finditer(description or ""):
        try:
            out.append(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date())
        except ValueError:
            continue
    return out


def pending_mark(description: str, today, doc_dates) -> tuple:
    """시행 전 조문 표기 판정(#273). doc_dates: 대상 문서 판들의 시행일(doc_date) 집합 — None이면 대조하지 않는다(주제 설명).
    반환 None(표기 없음) 또는 (level, code, detail). 시행일 당일은 아직 '지남'으로 보지 않는다(승격 다음 날 알림)."""
    ds = effective_dates(description)
    if not ds:
        return None
    past = sorted(d for d in ds if d < today)
    if past:
        return ("WARN", "pending_expired",
                "시행일 지남 — 표기 떼고 현행판 대조: " + "·".join(d.isoformat() for d in past))
    if doc_dates is not None:
        miss = sorted(d for d in ds if d not in doc_dates)
        if miss:
            return ("WARN", "pending_unverified",
                    "시행 전 표기인데 KB에 그 시행일 판 없음: " + "·".join(d.isoformat() for d in miss))
    return ("OK", "pending_cited", "")


def clean_expired_marks(description: str, today):
    """시행일이 지난 시행 표기를 떼어 낸 설명(#275) — 정리할 수 없으면 None.
    「YYYY.M.D 시행」 → 「YYYY.M 시행」(지침이 허용한 연·월 꼴 — effective_dates가 읽지 않는다), 맨 앞 「[시행예정 — … 시행]」과
    「※ 시행예정판(제N호) 기준, …」 절은 지운다. 시행일이 하나라도 아직 안 지났거나, 정리 뒤에도 「시행예정·시행 전까지·현행판」이
    남으면 None — 문장 뜻을 바꿔야 하는 것은 사람·세션이 고친다."""
    ds = effective_dates(description)
    if not ds or any(d >= today for d in ds):
        return None
    s = PENDING_PREFIX_RE.sub("", description)
    s = PENDING_NOTE_RE.sub("", s)
    s = EFFECTIVE_RE.sub(lambda m: f"{m.group(1)}.{int(m.group(2))} 시행", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    if effective_dates(s) or PENDING_STALE_RE.search(s) or s == description:
        return None
    return s


DOC_DATE_RE = re.compile(r"\((\d{8})\)(?:\.(?:pdf|md))?$", re.I)


def doc_date(doc_name: str):
    """문서명 끝 '(YYYYMMDD)' = 시행일 → date, 없으면 None"""
    m = DOC_DATE_RE.search(str(doc_name or "").strip())
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


# ─────────────────────────── DB 접근 (여기서부터 네트워크) ───────────────────────────

def _client():
    from dotenv import load_dotenv
    load_dotenv()
    from sb_client import make_client
    return make_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def _paged(q, page=1000):
    rows, off = [], 0
    while True:
        r = q.order("id").range(off, off + page - 1).execute()
        b = r.data or []
        rows.extend(b)
        if len(b) < page:
            return rows
        off += page


def fetch_topic_edges(sb):
    nodes = {n["id"]: n for n in _paged(sb.table("law_graph_nodes").select("id,name,node_type,doc_name"))}
    edges = _paged(sb.table("law_graph_edges").select("id,source_id,target_id,description,source,created_at"))
    out = []
    for e in edges:
        s, t = nodes.get(e["source_id"]), nodes.get(e["target_id"])
        if not s or not t or s["node_type"] != "topic":
            continue
        e["topic"], e["target"], e["target_doc"] = s["name"], t["name"], t.get("doc_name")
        out.append(e)
    return out


def fetch_topic_nodes(sb):
    """주제 노드(이름·설명) — 주제 설명의 시행 표기 만료 점검용(#273)"""
    return _paged(sb.table("law_graph_nodes").select("id,name,description").eq("node_type", "topic"))


def fetch_kb_docs(sb):
    """document_chunks 전체 doc_name 집합 (builder와 같은 순회 — 1000행 페이지, order id 필수)."""
    return {r["doc_name"] for r in _paged(sb.table("document_chunks").select("id,doc_name"))}


def fetch_current_docs(sb):
    """현행본 문서명 집합(document_chunks.status='current', RPC kb_doc_names). 실패하면 None — 현행 판 대조만 건너뛴다."""
    try:
        import kb_store
        return set(kb_store.list_docs(sb, status="current"))
    except Exception as e:
        print("현행본 목록 조회 실패 — 현행 판 대조 건너뜀:", e)
        return None


def fetch_doc_loaded(sb, doc_name):
    """문서 적재일(첫 청크 created_at) → date, 실패 None"""
    try:
        r = sb.table("document_chunks").select("created_at").eq("doc_name", doc_name).order("created_at").limit(1).execute().data
        return datetime.fromisoformat(r[0]["created_at"].replace("Z", "+00:00")).date() if r else None
    except Exception:
        return None


def resolve_docs(target_name, target_doc, kb_docs, base_index):
    """대상 노드의 KB 문서 '판(版)' 전부 — 같은 base의 현행·시행예정·구판을 모두 돌려준다(조문은 어느 판에든
    있으면 존재로 본다: 노드 doc_name이 구판 PDF를 가리켜 조문 파싱이 빈 경우가 실측됨 — 지방세법 시행령).
    순서: 이름 정규화 base 일치 → 노드 doc_name(그대로/.pdf 제거) base 일치 → 없으면 빈 튜플."""
    cands = base_index.get(nrm(target_name))
    if not cands and target_doc:
        cands = base_index.get(base_of(target_doc))
    if not cands and target_doc:
        stripped = re.sub(r"\.(pdf|md)$", "", target_doc, flags=re.I)
        cands = {d for d in (target_doc, stripped) if d in kb_docs}
    return tuple(sorted(cands or ()))


def fetch_articles(sb, doc_names):
    """여러 판의 조문 키 합집합 + 번호 없는 별표 종류. 부칙·별표·별지는 '조문 체계'로 세지 않는다(부칙만 있는
    공정위 예규·고시가 조문 있는 문서로 오판돼 no_article이 쏟아졌음) — 번호 없는 별표는 따로 모은다(#257)."""
    keys, bare = set(), set()
    for d in doc_names:
        rows = _paged(sb.table("document_chunks").select("id,article_no").eq("doc_name", d))
        for r in rows:
            a = (r.get("article_no") or "").strip()
            bm = BARE_LABEL_RE.match(a)
            if bm:
                bare.add(bm.group(1))
            if not a or a.startswith(("부칙", "별표", "별지", "별첨", "붙임")):
                continue
            keys.add(art_key(a))
    return keys, frozenset(bare)


def _write_clean(sb, table, row_id, old, new):
    """시행 표기 정리 쓰기(#275) — 읽은 뒤 누가 설명을 바꿨으면(eq description) 쓰지 않는다. 성공 여부."""
    try:
        r = sb.table(table).update({"description": new}).eq("id", row_id).eq("description", old).execute()
        return bool(r.data)
    except Exception as ex:
        print(f"시행 표기 정리 쓰기 실패({table} {row_id}):", ex)
        return False


def expired_fix_block(new, cur_docs, expired_on, judged, gone):
    """시행 표기 자동 정리를 막는 사유(#275) — 없으면 None. 순수 함수(네트워크 없음).
    new: clean_expired_marks 결과 · cur_docs: 대상의 현행본 문서명들(None=목록 조회 실패) · expired_on: 지난 시행일 중 가장 늦은 날
    judged: 정리한 설명의 judge 결과 · gone: 정리한 설명의 자기 조문 중 현행판에 없는 것"""
    if new is None:
        return "문장 뜻을 바꿔야 함 — 사람이 정리"
    if cur_docs is None:
        return "현행본 목록 조회 실패"
    if not any((doc_date(d) or datetime.min.date()) >= expired_on for d in cur_docs):
        return "현행판이 아직 그 시행일 판이 아님(승격 전·실패)"
    if judged is None:
        return "정리한 설명 대조 못 함"
    if judged[0] != "OK":
        return "정리한 설명 대조 실패: " + (judged[2] or judged[1])
    if gone:
        return "현행판에 없는 조문: " + "·".join("제" + k for k in gone)
    return None


def run(since_hours: float, notify: bool, notify_all: bool, gone_days: float = 4, fix: bool = False):
    sb = _client()
    edges = fetch_topic_edges(sb)
    kb_docs = fetch_kb_docs(sb)
    current_docs = fetch_current_docs(sb)
    recent_change = {}   # 현행 판 문서명 → 시행일·적재일 중 늦은 날(알림 창 판정용)
    base_index = {}
    for d in kb_docs:
        base_index.setdefault(base_of(d), set()).add(d)
    print(f"주제 엣지 {len(edges)}건 · KB 문서 {len(kb_docs)}종 점검")

    today = datetime.now(KST).date()
    art_cache = {}
    results = []
    cleaned = []   # 시행 표기 자동 정리(#275) — (주제, 대상, 전, 후)
    for e in edges:
        docs = resolve_docs(e["target"], e.get("target_doc"), kb_docs, base_index)
        arts, bare = None, ()
        if docs:
            if docs not in art_cache:
                art_cache[docs] = fetch_articles(sb, docs)
            arts, bare = art_cache[docs]
        level, code, detail = judge(e.get("description"), e["target"], bool(docs), arts, bare)
        # 현행 판 대조(#271) — 모든 판 합집합으로는 있지만 현행 판에는 없는 자기 조문(개정으로 삭제·이동)
        if code in ("verified", "art_partial") and current_docs:
            cur = tuple(d for d in docs if d in current_docs)
            if cur:
                if cur not in art_cache:
                    art_cache[cur] = fetch_articles(sb, cur)
                gone = not_current_articles(e.get("description"), e["target"], art_cache[cur][0])
                if gone:
                    level, code = "WARN", "art_not_current"
                    detail = ("현행 판에 없는 조문(구판·시행예정판에만): " + "·".join("제" + k for k in gone)
                              + (" / " + detail if detail else ""))
                    e["current_doc"] = cur[-1]
                    for d in cur:
                        if d not in recent_change:
                            dates = [x for x in (doc_date(d), fetch_doc_loaded(sb, d)) if x]
                            recent_change[d] = max(dates) if dates else None
                    e["current_changed"] = max((recent_change[d] for d in cur if recent_change[d]), default=None)
        # 시행 전 조문 표기(#273) — 미래 시행일은 그 시행일 판이 KB에 있으면 OK(pending_cited, 신설 조라 현행 판에 없는
        # art_not_current도 이것으로 낮춘다), 없으면 WARN; 지난 시행일은 WARN. 다른 ERR·WARN은 그대로 두고 사유만 붙인다.
        pm = pending_mark(e.get("description"), today, {doc_date(d) for d in docs} - {None})
        if pm:
            if level == "OK" or code == "art_not_current":
                level, code, detail = pm
            elif pm[2]:
                detail = f"{detail} / {pm[2]}" if detail else pm[2]
            if pm[1] == "pending_expired":
                expired_on = max(d for d in effective_dates(e.get("description")) if d < today)
                e["expired_days"] = (today - expired_on).days
                # 시행 표기 자동 정리(#275): 시행일이 지났고, 현행판이 그 시행일 판으로 바뀌었고, 정리한 설명이 대조를 통과할 때만 쓴다
                old = e.get("description") or ""
                new = clean_expired_marks(old, today)
                cur = tuple(d for d in docs if d in current_docs) if current_docs is not None else None
                judged, gone = None, []
                if new is not None and cur:
                    if cur not in art_cache:
                        art_cache[cur] = fetch_articles(sb, cur)
                    judged = judge(new, e["target"], bool(docs), arts, bare)
                    gone = not_current_articles(new, e["target"], art_cache[cur][0])
                block = expired_fix_block(new, cur, expired_on, judged, gone)
                if block:
                    detail = f"{detail} / 자동 정리 안 함: {block}"
                elif fix and _write_clean(sb, "law_graph_edges", e["id"], old, new):
                    level, code, detail = "OK", "pending_cleaned", ""
                    cleaned.append((e["topic"], e["target"], old, new))
                else:
                    detail = f"{detail} / " + ("자동 정리 쓰기 실패" if fix else "자동 정리 예정(이번 실행은 쓰기 꺼짐): " + new)
        # AI 즉석 생성이 'KB 미보유' 꼬리표로 남긴 엣지는 등재 후보이거나 지어낸 문서명이다(2026-09-05 '전파사용료 징수에 관한 고시' — 법제처에 없음).
        # 생성 후 3일 안에는 WARN으로 올려 운영자가 법제처 검색으로 존재를 확인하고 등재/삭제를 결정하게 한다.
        if code == "doc_missing_tagged" and e.get("source") == "ai":
            try:
                age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))).total_seconds() / 3600
            except Exception:
                age_h = 0
            if age_h <= 72:
                level, code, detail = "WARN", "doc_missing_ai_new", "AI가 붙인 KB 미보유 문서 — 법제처 존재 확인 후 등재/삭제 결정"
        results.append((level, code, detail, e))

    # 주제 설명의 시행 표기(#273 R5-2) — 대상 문서가 없으니 만료만 본다
    try:
        for t in fetch_topic_nodes(sb):
            pm = pending_mark(t.get("description"), today, None)
            if pm and pm[1] == "pending_expired":
                # 주제 설명은 대상 문서가 없어 날짜 꼴만 정리한다(#275) — 문장 뜻을 바꿔야 하는 것은 사람 몫으로 남긴다
                old = t.get("description") or ""
                new = clean_expired_marks(old, today)
                if new is not None and fix and _write_clean(sb, "law_graph_nodes", t["id"], old, new):
                    cleaned.append((t["name"], "(주제 설명)", old, new))
                    continue
                if new is not None:
                    pm = (pm[0], pm[1], pm[2] + (" / 자동 정리 쓰기 실패" if fix else " / 자동 정리 예정(이번 실행은 쓰기 꺼짐): " + new))
                else:
                    pm = (pm[0], pm[1], pm[2] + " / 자동 정리 안 함: 문장 뜻을 바꿔야 함 — 사람이 정리")
                te = {"topic": t["name"], "target": "(주제 설명)", "source": "topic", "created_at": None,
                      "description": t.get("description"),
                      "expired_days": (today - max(d for d in effective_dates(t.get("description")) if d < today)).days}
                results.append((pm[0], pm[1], pm[2], te))
    except Exception as ex:
        print("주제 설명 시행 표기 점검 실패(무시):", ex)

    counts = {}
    for level, code, _, _ in results:
        counts[code] = counts.get(code, 0) + 1
    print("판정 분포:", ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])))
    n_pending = counts.get("pending_cited", 0)
    print(f"시행 전 조문 인용 {n_pending}건 (시행일 판이 KB에 있음 — 시행 뒤 표기를 떼야 함)")

    problems = [r for r in results if r[0] != "OK"]
    for level, code, detail, e in sorted(problems, key=lambda r: (r[0] != "ERR", r[3]["topic"])):
        print(f"[{level}:{code}] {e['topic']} → {e['target']} ({e['source']}) : {detail}\n"
              f"      설명: {(e.get('description') or '')[:110]}")
    print(f"문제 {len(problems)}건 (ERR {sum(r[0]=='ERR' for r in problems)} · WARN {sum(r[0]=='WARN' for r in problems)})")

    # 시행 표기 자동 정리 기록(#275) — 운영자 봇 메시지가 되돌리기 자료다(전·후 전문). 쓴 것이 있으면 알림 설정과 무관하게 보낸다
    if cleaned:
        lines = [f"🧹 관계도 시행 표기 자동 정리 {len(cleaned)}건 (시행일 지남·현행판 대조 통과)"]
        for topic, target, old, new in cleaned:
            lines.append(f"• {topic} → {target}\n  전: {old}\n  후: {new}")
        print("\n".join(lines))
        try:
            from notify import send_telegram
            print("텔레그램(정리 기록):", "성공" if send_telegram("\n".join(lines), disable_notification=True) else "실패/미설정")
        except Exception as ex:
            print("텔레그램(정리 기록) 실패:", ex)

    if not notify:
        return
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    def is_new(e):
        try:
            return datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")) >= since
        except Exception:
            return False
    def is_amended(r):
        # 현행 판이 최근(gone_days 안에) 시행·적재됐으면 그 개정이 만든 문제다 — 엣지는 오래돼도 알린다(#271).
        # 주말·휴일을 건너 다음 평일 실행이 잡도록 기본 4일 — 그 사이 매 실행 반복될 수 있다.
        ch = r[3].get("current_changed")
        if r[1] == "art_not_current" and ch is not None and (today - ch).days <= gone_days:
            return True
        # 시행 표기(#273): 시행일이 막 지난 것(승격 다음 날부터 gone_days 동안)과 KB에 그 시행일 판이 없는 것은 엣지가 오래돼도 알린다
        if r[1] == "pending_expired" and r[3].get("expired_days", 99) <= gone_days:
            return True
        return r[1] == "pending_unverified"
    to_send = problems if notify_all else [r for r in problems if (since_hours > 0 and is_new(r[3])) or is_amended(r)]
    # 검토 대기 제안(lawmap_proposals, #147) — 승인이 밀리면 관계도가 자라지 않으므로 건수·최고 대기일을 함께 알린다
    pending_n, pending_days = 0, 0
    try:
        pend = sb.table("lawmap_proposals").select("created_at").eq("status", "pending").execute().data or []
        pending_n = len(pend)
        if pend:
            oldest = min(datetime.fromisoformat(p["created_at"].replace("Z", "+00:00")) for p in pend)
            pending_days = (datetime.now(timezone.utc) - oldest).days
    except Exception as e:
        print("검토 대기 조회 실패(무시):", e)
    if not to_send and not pending_n:
        print("텔레그램: 보낼 신규 문제·검토 대기 없음")
        return
    from notify import send_telegram
    lines = [f"🔎 관계도 주제 엣지 점검 — 문제 {len(to_send)}건" + ("" if notify_all else f" (최근 {since_hours:g}시간 생성분·최근 {gone_days:g}일 개정분)")]
    if n_pending:
        lines.append(f"⏳ 시행 전 조문 인용 {n_pending}건 — 시행일 다음 날 점검이 현행판 대조 뒤 표기를 자동 정리(#275), 못 하면 사유와 함께 알림")
    if pending_n:
        lines.append(f"📝 AI 연결 제안 검토 대기 {pending_n}건" + (f" (가장 오래된 것 {pending_days}일)" if pending_days else "") + " → 관계도 탭 '검토 대기' 카드에서 승인/기각")
    for level, code, detail, e in to_send[:25]:
        lines.append(f"• [{level}] {e['topic']} → {e['target']}: {detail or code}")
    if len(to_send) > 25:
        lines.append(f"… 외 {len(to_send) - 25}건 (build_law_citation_graph_sched.log 옆 lawmap_edge_check_sched.log 참조)")
    lines.append("→ 관계도 탭에서 설명을 정정하거나 엣지를 삭제하세요. AI 즉석 생성은 저장 전 검증을 거치지만 검증은 '조문 존재'까지만 봅니다.")
    ok = send_telegram("\n".join(lines), disable_notification=True)
    print("텔레그램 발송:", "성공" if ok else "실패/미설정")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="법령 관계도 주제 엣지 — 근거 조문 존재 점검(쓰기는 시행 표기 자동 정리뿐, #275)")
    ap.add_argument("--since-hours", type=float, default=30, help="이 시간 내 생성 엣지의 문제만 텔레그램(기본 30, 0=미발송)")
    ap.add_argument("--no-notify", action="store_true", help="텔레그램 미발송(출력만)")
    ap.add_argument("--notify-all", action="store_true", help="신규 여부 무관 전체 문제를 텔레그램으로")
    ap.add_argument("--gone-days", type=float, default=4,
                    help="현행 판이 이 날수 안에 시행·적재됐으면 '현행 판에 없는 조문' 문제를 엣지 생성일과 무관하게 알림(기본 4, #271)")
    ap.add_argument("--no-fix", action="store_true", help="시행 표기 자동 정리를 쓰지 않음(예정만 출력, #275)")
    ap.add_argument("--fix", action="store_true", help="--no-notify여도 시행 표기 자동 정리를 씀(#275)")
    a = ap.parse_args()
    # 자동 정리는 예약 실행(알림 켬)에서만 쓴다 — 세션이 --no-notify로 점검하다가 DB를 바꾸지 않게
    fix = a.fix or (not a.no_notify and not a.no_fix)
    try:
        run(a.since_hours, notify=not a.no_notify, notify_all=a.notify_all, gone_days=a.gone_days, fix=fix)
    except Exception as ex:  # 체인을 막지 않는다
        print(f"[lawmap_edge_check] 실패: {ex!r}")
    sys.exit(0)
