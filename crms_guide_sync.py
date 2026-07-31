#!/usr/bin/env python3
"""
중앙전파관리소(crms.go.kr) '업무안내' 해설 페이지 → regulatory-kb(kb_documents·kb_chunks) 적재

법령 원문(document_chunks)이 아니라 실무 절차 해설이므로 kb 레이어에 넣는다.
조문 헤더 청킹(upload_law_pdf)은 해설 문서에서 800자 무맥락 슬라이딩으로 폴백하므로 부적합하고,
import_regulatory_kb.chunk_body()의 마크다운 헤더 청킹이 섹션 의미를 보존한다. (배경역사 #40)

- 대상: 좌측 '업무안내' 메뉴 하위 contents.do 페이지 (분야 10개 / 약 38페이지)
- 출처: 공공누리 제1유형(출처표시) — 재배포·변형 허용
- 갱신: 본문 sha256 비교로 변경분만 재적재 (월 1회 스케줄러)

사용:
  python crms_guide_sync.py --dry-run   # 수집·추출만, DB 미변경
  python crms_guide_sync.py             # 변경분 적재
"""

import os
import re
import sys
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

# Windows 스케줄러 cp949 콘솔에서 이모지·한글 print 크래시 방지 (배경역사 #19)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from bs4 import BeautifulSoup

import add_law
import import_regulatory_kb as ikb
from gov_notice_crawler import fetch_with_retry

try:
    import trafilatura
except ImportError:
    sys.exit("ERROR: trafilatura 미설치 — pip install trafilatura")

KST = timezone(timedelta(hours=9))
BASE = "https://www.crms.go.kr"
SEED = BASE + "/lay1/S1T41C42/contents.do"   # 업무안내 첫 페이지(무선국개설) — nav 파싱용
ROOT_MENU = "업무안내"
OUT_DIR = "procedures/crms"                  # regulatory-kb 기준 상대경로
MIN_BODY = 150                               # 이보다 짧으면 추출 실패로 간주


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def slug_for(text):
    """add_law.slugify는 norm_title(법령명 정규화)을 거치므로 여기선 직접 만든다."""
    base = re.sub(r"[^0-9a-zA-Z가-힣]+", "_", norm(text)).strip("_").lower()
    return base[:60] or "page"


def collect_menu():
    """'업무안내' nav 블록에서 (분야, 제목, URL) 목록을 수집.
    ※ 링크를 하드코딩하지 않는다 — 사이트 메뉴 개편 시 자동 추종하고,
       0건이면 개편 신호로 즉시 드러난다. (배경역사 #39 교훈)"""
    res = fetch_with_retry(SEED, timeout=20)
    res.encoding = getattr(res, "apparent_encoding", None) or "utf-8"
    soup = BeautifulSoup(res.text, "html.parser")

    block = None
    for li in soup.find_all(["li", "div"]):
        a = li.find("a")
        if a and norm(a.get_text()) == ROOT_MENU and len(li.select("a")) > 5:
            block = li
            break
    if block is None:
        return []

    # 역할 분담: nav 링크 텍스트 = 페이지 고유 제목, <title> breadcrumb = 분야.
    #  · nav 순서로 분야를 추정하면 틀린다(예: '방송업무'가 조사단속 하위로 붙음).
    #  · 반대로 <title> 끝 조각을 제목으로 쓰면 '개요'가 3개 나와 파일명이 충돌한다.
    # 같은 URL에 여러 텍스트가 달리면(대분류명 + 첫 하위항목) 뒤쪽이 더 구체적이라 모두 모아둔다.
    urls, titles = [], {}
    for a in block.select("a"):
        href = norm(a.get("href") or "")
        text = norm(a.get_text())
        if not href or "contents.do" not in href or not text:
            continue
        url = urljoin(BASE, href)
        if url not in titles:
            titles[url] = []
            urls.append(url)
        if text not in titles[url]:
            titles[url].append(text)
    return [(u, titles[u]) for u in urls]


def pick_title(cands, group):
    """nav 텍스트 후보 중 페이지 고유 제목을 고른다.
    대분류명(=분야)과 최상위 메뉴명은 제외하고, 남으면 가장 구체적인(뒤쪽) 것."""
    rest = [t for t in cands if t not in (group, ROOT_MENU)]
    return (rest[-1] if rest else (cands[-1] if cands else group))


def parse_breadcrumb(html):
    """<title>이 '홈 >업무안내>무선국검사>검사개요' 형태로 계층을 그대로 담고 있다.
    nav 순서 추정보다 정확하므로 분야·제목은 여기서 확정한다. (배경역사 #40)
    반환: (분야, 제목) — 2단이 아니면 (제목, 제목)"""
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if not m:
        return None, None
    parts = [norm(p) for p in m.group(1).split(">")]
    parts = [p for p in parts if p and p != "홈"]
    if not parts or parts[0] != ROOT_MENU:
        return None, None
    parts = parts[1:]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], parts[-1]


def extract_body(html):
    text = trafilatura.extract(html, include_tables=True, include_links=False,
                               include_comments=False, favor_recall=True)
    return norm_body(text or "")


def norm_body(t):
    t = t.replace("\r\n", "\n")
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def build_md(group, title, url, body, today):
    full_title = f"중앙전파관리소 업무안내 — {group} > {title}" if group != title else \
                 f"중앙전파관리소 업무안내 — {title}"
    desc = f"{group} 분야 '{title}' 실무 절차 안내 (기관 안내 문서이며 법령 원문 아님)"
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    fm = (
        "---\n"
        "type: Procedure\n"
        f"title: {full_title}\n"
        f"description: {desc}\n"
        f"resource: 중앙전파관리소 {url} (공공누리 제1유형 출처표시, {today} 수집)\n"
        "competent_authority: 중앙전파관리소\n"
        f"timestamp: {today}T00:00:00Z\n"
        f"content_sha256: {sha}\n"
        "---\n\n"
    )
    return full_title, sha, fm + body + "\n"


def existing_sha(fp):
    if not fp.exists():
        return None
    m = re.search(r"^content_sha256:\s*([0-9a-f]{64})\s*$",
                  fp.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def main():
    dry = "--dry-run" in sys.argv
    today = datetime.now(KST).strftime("%Y-%m-%d")
    print("=" * 60)
    print(f"[중앙전파관리소 업무안내 동기화] {datetime.now(KST):%Y-%m-%d %H:%M} "
          f"{'(드라이런)' if dry else ''}")

    menu = collect_menu()
    urls = [u for u, _ in menu]
    print(f"[메뉴] '업무안내' 하위 링크 {len(urls)}개 스캔")
    if not urls:
        print("[경고] 링크 0개 — 사이트 메뉴 구조가 바뀌었을 수 있습니다(파서 점검 필요)")
        return

    if not dry:
        ikb.load_env()

    n_fetch = n_change = n_ingest = n_fail = 0
    groups = {}
    rows = []
    for url, cands in menu:
        try:
            res = fetch_with_retry(url, timeout=20)
            res.encoding = getattr(res, "apparent_encoding", None) or "utf-8"
            html = res.text
            group, _ = parse_breadcrumb(html)
            if not group:
                n_fail += 1
                print(f"  [건너뜀] {url}: 업무안내 하위가 아니거나 제목 파싱 실패")
                continue
            title = pick_title(cands, group)
            body = extract_body(html)
            n_fetch += 1
        except Exception as e:
            n_fail += 1
            print(f"  [실패] {url}: {e}")
            continue

        if len(body) < MIN_BODY:
            n_fail += 1
            print(f"  [건너뜀] {group} > {title}: 본문 {len(body)}자 (추출 실패 의심)")
            continue
        groups.setdefault(group, []).append(title)
        rows.append((group, title, url, body))

    print("[분야] " + " · ".join(f"{g} {len(v)}" for g, v in groups.items()))

    for group, title, url, body in rows:
        rel = f"{OUT_DIR}/{slug_for(group)}/{slug_for(title)}.md"
        fp = add_law.BUNDLE / rel
        full_title, sha, md = build_md(group, title, url, body, today)

        if existing_sha(fp) == sha:
            print(f"  [변경없음] {group} > {title} ({len(body)}자)")
            continue
        n_change += 1
        print(f"  [변경] {group} > {title} ({len(body)}자)")
        if dry:
            continue

        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(md, encoding="utf-8", newline="\n")
        add_law.update_manifest({
            "dedup_key": f"{full_title}|Procedure",
            "title": full_title,
            "law_type": "",
            "law_number": today,          # 버전 식별자 = 수집일 (법령번호가 없는 문서)
            "enforcement_date": today,
            "concept_type": "Procedure",
            "path": rel,
            "status": "current",
        })
        try:
            n = add_law.ingest_one(rel)
            n_ingest += 1
            print(f"           → kb 적재 {n}청크")
        except Exception as e:
            n_fail += 1
            print(f"           → [적재 실패] {e}")
        time.sleep(0.5)

    print("-" * 60)
    print(f"[완료] 스캔 {len(urls)} / 수집 {n_fetch} / 변경 {n_change} / 적재 {n_ingest} / 실패 {n_fail}")
    if dry:
        print("       (드라이런 — 파일·DB 변경 없음)")


if __name__ == "__main__":
    main()
