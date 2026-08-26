"""법제처 DRF API 조문 원문 → .txt 내보내기 (add_law.py 요약 레이어 입력용).

add_law.py는 PDF/txt 파일 1개를 입력으로 받아 ① 조문→document_chunks ② OKF 요약→kb_*를
수행한다. 그런데 법제처 API로 이미 조문을 받을 수 있는 법령은 PDF를 따로 구할 이유가 없다.
이 스크립트는 API 조문을 .txt로 떨어뜨려, 다음 조합으로 요약 레이어만 태울 수 있게 한다:

  python export_law_text.py "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법" --out ai.txt
  python add_law.py ai.txt --no-article --title ... --law-type ... --family ai-framework-act

  (--no-article: 조문 레이어는 add_laws_batch.py가 이미 API로 적재하므로 중복 금지)

검색·조문취득은 law_watch/law_sync/add_laws_batch의 기존 함수를 그대로 재사용한다.
"""
import os
import sys
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from law_watch import row_fields
from law_sync import fetch_law_articles, fetch_admrul_articles
from add_laws_batch import search_with_fallback


def export(law_name, target_hint=None, out_path=None):
    target, hit = search_with_fallback(law_name, target_hint)
    if not hit:
        raise SystemExit(f"법제처 검색 결과 없음: {law_name}")

    mst, law_no, enf = row_fields(hit, target)
    if target == 'law':
        articles, basic = fetch_law_articles(mst)
        law_type = basic.get('법령구분명') or hit.get('법령구분명') or ''
        authority = basic.get('소관부처명') or hit.get('소관부처명') or ''
    else:
        articles, basic = fetch_admrul_articles(mst)
        law_type = basic.get('행정규칙종류') or hit.get('행정규칙종류') or '고시'
        authority = basic.get('소관부처명') or hit.get('소관부처명') or ''

    if not articles:
        raise SystemExit(f"조문 취득 결과가 비어 있음(첨부파일 전용 등): {law_name}")

    lines = [law_name, ""]
    for no, txt in articles:
        if no:
            lines.append(f"제{no}" if not str(no).startswith('제') else str(no))
        lines.append(txt)
        lines.append("")
    text = "\n".join(lines)

    out = out_path or f"{law_name.replace(' ', '_')}.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"✅ {out}  ({len(articles)}조문, {len(text):,}자)")
    print(f"   target={target}  law_type={law_type}  law_number=제{law_no}호  "
          f"enforcement_date={enf}  authority={authority}")
    print("\n   add_law.py 예시:")
    enf_fmt = f"{enf[:4]}-{enf[4:6]}-{enf[6:]}" if enf and len(enf) == 8 else (enf or "")
    print(f'   python add_law.py "{out}" --no-article --title "{law_name}" '
          f'--law-type "{law_type}" --law-number "제{law_no}호" --enf-date {enf_fmt} '
          f'--authority "{authority}" --concept-type <Law|Regulation|Notice> --family <family>')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("law_name")
    ap.add_argument("--target", default=None, choices=["law", "admrul"],
                    help="미지정 시 law → admrul 순으로 자동 판별")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    export(a.law_name, a.target, a.out)


if __name__ == "__main__":
    main()
