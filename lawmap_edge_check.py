# -*- coding: utf-8 -*-
"""법령 관계도 주제 엣지 점검 — "설명에 적힌 근거 조문이 대상 문서 원문에 실제로 있는가" (2026-09-05, 배경역사 #123)

배경: 2026-09-05 전수 검증에서 주제 엣지 356건 중 214건이 조문 오류·자리표시 설명이었다.
AI 즉석 생성(app.js saveLawmapData)이 조문을 검증 없이 저장한 것이 주원인이라 저장 전 관문을
넣었고, 이 스크립트는 그 두 번째 층(야간 전수 점검)이다. 17시 run_gov_crawler.bat 체인의
마지막 단계로 돌며, DB는 읽기만 한다(정정은 운영자·세션이 한다).

판정(엣지 1건당 하나):
  ERR placeholder   설명이 '관련 조문'·'제N조'·'(관련)' 같은 자리표시
  ERR art_missing   대상 문서는 KB에 있는데 설명의 자기 조문이 하나도 원문에 없음
  ERR no_article    조문 번호 없음 (대상 문서가 조문 체계를 갖췄고 미보유 꼬리표도 없을 때)
  WARN art_partial  자기 조문 일부만 원문에 있음
  WARN doc_missing  대상 문서가 KB에 없는데 '[원문 KB 미보유/미등재…]' 꼬리표가 없음
  OK                그 외

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
# 교차 인용 판별: 조문 앞 낱말이 법령명으로 끝나는가
LAWWORD_RE = re.compile(r"([가-힣A-Za-z0-9·ㆍ]*(?:법|법률|령|영|규칙|고시|규정|기준|지침|조례|헌장|협정))\s*$")
LAW_ONLY_SUFFIX = ("법", "법률", "령", "규칙")           # 고시·지침이 '…법 제N조'를 자기 조문으로 가질 수는 없다
GENERIC_LAWWORDS = ("법", "령", "영", "규칙", "고시", "규정", "기준", "지침")   # "법 제N조"·"영 제N조" 식 약칭 → 항상 교차 인용
# 직전 조문에 연결부호(·, ~)로 이어진 조문은 앞 조문의 판정(자기/교차)을 그대로 따른다 (','는 새 문맥)
CONNECT_RE = re.compile(r"[·ㆍ~∼\-]\s*$")
DELEG_AFTER_RE = re.compile(r"^\s*(?:제\d+항|제\d+호|[①-⑳])*\s*(?:의\s*)?(?:위임|에\s*따른|에\s*의한|근거)")


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


def judge(description: str, target_name: str, doc_found: bool, doc_articles) -> tuple:
    """(level, code, detail). doc_articles: 원문 조문 키 집합(None=문서 미보유)."""
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


def fetch_kb_docs(sb):
    """document_chunks 전체 doc_name 집합 (builder와 같은 순회 — 1000행 페이지, order id 필수)."""
    return {r["doc_name"] for r in _paged(sb.table("document_chunks").select("id,doc_name"))}


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
    """여러 판의 조문 키 합집합. 부칙·별표·별지는 '조문 체계'로 세지 않는다(부칙만 있는 공정위 예규·고시가
    조문 있는 문서로 오판돼 no_article이 쏟아졌음)."""
    keys = set()
    for d in doc_names:
        rows = _paged(sb.table("document_chunks").select("id,article_no").eq("doc_name", d))
        for r in rows:
            a = (r.get("article_no") or "").strip()
            if not a or a.startswith(("부칙", "별표", "별지", "별첨", "붙임")):
                continue
            keys.add(art_key(a))
    return keys


def run(since_hours: float, notify: bool, notify_all: bool):
    sb = _client()
    edges = fetch_topic_edges(sb)
    kb_docs = fetch_kb_docs(sb)
    base_index = {}
    for d in kb_docs:
        base_index.setdefault(base_of(d), set()).add(d)
    print(f"주제 엣지 {len(edges)}건 · KB 문서 {len(kb_docs)}종 점검")

    art_cache = {}
    results = []
    for e in edges:
        docs = resolve_docs(e["target"], e.get("target_doc"), kb_docs, base_index)
        arts = None
        if docs:
            if docs not in art_cache:
                art_cache[docs] = fetch_articles(sb, docs)
            arts = art_cache[docs]
        level, code, detail = judge(e.get("description"), e["target"], bool(docs), arts)
        results.append((level, code, detail, e))

    counts = {}
    for level, code, _, _ in results:
        counts[code] = counts.get(code, 0) + 1
    print("판정 분포:", ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])))

    problems = [r for r in results if r[0] != "OK"]
    for level, code, detail, e in sorted(problems, key=lambda r: (r[0] != "ERR", r[3]["topic"])):
        print(f"[{level}:{code}] {e['topic']} → {e['target']} ({e['source']}) : {detail}\n"
              f"      설명: {(e.get('description') or '')[:110]}")
    print(f"문제 {len(problems)}건 (ERR {sum(r[0]=='ERR' for r in problems)} · WARN {sum(r[0]=='WARN' for r in problems)})")

    if not notify:
        return
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    def is_new(e):
        try:
            return datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")) >= since
        except Exception:
            return False
    to_send = problems if notify_all else [r for r in problems if since_hours > 0 and is_new(r[3])]
    if not to_send:
        print("텔레그램: 보낼 신규 문제 없음")
        return
    from notify import send_telegram
    lines = [f"🔎 관계도 주제 엣지 점검 — 문제 {len(to_send)}건" + ("" if notify_all else f" (최근 {since_hours:g}시간 생성분)")]
    for level, code, detail, e in to_send[:25]:
        lines.append(f"• [{level}] {e['topic']} → {e['target']}: {detail or code}")
    if len(to_send) > 25:
        lines.append(f"… 외 {len(to_send) - 25}건 (build_law_citation_graph_sched.log 옆 lawmap_edge_check_sched.log 참조)")
    lines.append("→ 관계도 탭에서 설명을 정정하거나 엣지를 삭제하세요. AI 즉석 생성은 저장 전 검증을 거치지만 검증은 '조문 존재'까지만 봅니다.")
    ok = send_telegram("\n".join(lines), disable_notification=True)
    print("텔레그램 발송:", "성공" if ok else "실패/미설정")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="법령 관계도 주제 엣지 — 근거 조문 존재 점검(읽기 전용)")
    ap.add_argument("--since-hours", type=float, default=30, help="이 시간 내 생성 엣지의 문제만 텔레그램(기본 30, 0=미발송)")
    ap.add_argument("--no-notify", action="store_true", help="텔레그램 미발송(출력만)")
    ap.add_argument("--notify-all", action="store_true", help="신규 여부 무관 전체 문제를 텔레그램으로")
    a = ap.parse_args()
    try:
        run(a.since_hours, notify=not a.no_notify, notify_all=a.notify_all)
    except Exception as ex:  # 체인을 막지 않는다
        print(f"[lawmap_edge_check] 실패: {ex!r}")
    sys.exit(0)
