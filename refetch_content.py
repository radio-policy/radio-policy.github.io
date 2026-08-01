"""
본문 미수집 기사 재수집 스크립트 (PC 전용 — 한국 IP)
- news_feed에서 content=NULL인 기사를 재수집
- v.daum.net URL → og:url로 원본 기사 URL 추출 후 수집
- 상대경로 URL(http 없음) → 건너뜀
- 실행: python refetch_content.py
- 옵션: python refetch_content.py --all   (content 있어도 전부 재수집)
"""

import os, sys, time, requests

# Windows 스케줄러/cp949 콘솔에서 이모지 print 크래시 방지 (UnicodeEncodeError)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from sb_client import make_client

# .env 파일 자동 로딩 (로컬 실행 시)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# crawler.py의 fetch_article_body, HEADERS 재사용
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "crawler",
    pathlib.Path(__file__).parent / "crawler.py"
)
crawler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crawler)

# ── 설정 ──────────────────────────────────────────────────────
SUPABASE_URL  = os.environ['SUPABASE_URL']
SUPABASE_KEY  = os.environ.get('SUPABASE_SERVICE_KEY') or os.environ['SUPABASE_KEY']
DELAY_BETWEEN = 1.5
KST           = timezone(timedelta(hours=9))
# ─────────────────────────────────────────────────────────────


def resolve_url(url: str) -> str:
    """
    Google News / v.daum.net URL → 원본 기사 URL로 변환.
    상대경로(http 없음) → None 반환 (처리 불가).
    """
    if not url:
        return None
    # 상대경로 URL 처리 불가
    if not url.startswith('http'):
        return None
    # news.google.com → 원본 URL 추출
    if 'news.google.com' in url:
        # 1순위: googlenewsdecoder 라이브러리
        try:
            from googlenewsdecoder import new_decoderv1
            result = new_decoderv1(url)
            if result.get('status') and result.get('decoded_url'):
                print(f'  [Google→원본] {result["decoded_url"][:70]}')
                return result['decoded_url']
        except Exception:
            pass
        # 2순위: 리다이렉트 따라가기
        try:
            r = requests.get(url, headers=crawler.HEADERS, timeout=8, allow_redirects=True)
            if r.url and 'news.google.com' not in r.url:
                print(f'  [Google→원본] {r.url[:70]}')
                return r.url
        except Exception:
            pass
    # v.daum.net → 원본 URL 추출
    if 'daum.net' in url:
        try:
            resp = requests.get(url, headers=crawler.HEADERS, timeout=8, allow_redirects=True)
            soup = BeautifulSoup(resp.text, 'html.parser')
            og = soup.find('meta', property='og:url')
            if og and og.get('content') and 'daum.net' not in og['content']:
                print(f'  [Daum→원본] {og["content"][:70]}')
                return og['content']
        except Exception:
            pass
    return url


def _refetch_heartbeat(sb, note=''):
    """운영 상태 탭 '본문 수집(refetch) 마지막 실행' 기록. 실패해도 무시."""
    try:
        sb.table('system_health').upsert(
            {'key': 'last_refetch_run',
             'updated_at': datetime.now(timezone.utc).isoformat(),
             'note': note},
            on_conflict='key'
        ).execute()
        print('[heartbeat] system_health.last_refetch_run 갱신')
    except Exception as e:
        print(f'[heartbeat 오류] {e}')


def main():
    regen_all = "--all" in sys.argv
    sb = make_client(SUPABASE_URL, SUPABASE_KEY)

    # ── 60일 초과 기사 일괄 정리 (locked=true 기사는 보존) ──────────
    try:
        cutoff = (datetime.now(KST) - timedelta(days=60)).isoformat()
        purged = sb.table("news_feed").delete() \
            .lt("published_at", cutoff) \
            .eq("locked", False) \
            .execute()
        n_purged = len(purged.data or [])
        if n_purged:
            print(f"🗑  60일 초과 기사 {n_purged}건 삭제 (잠금 기사 제외)")
    except Exception as e:
        print(f"[오래된 기사 정리 오류] {e}")

    # content=NULL 또는 100자 미만(제목만 저장된 경우) 기사 재수집
    resp = sb.table("news_feed").select("id,title,source,url,content,published_at,summary,locked") \
        .order("published_at", desc=True).limit(500).execute()
    all_articles = resp.data or []

    if regen_all:
        todo = [a for a in all_articles if a.get("url")]
        mode = "전체 재수집"
    else:
        todo = [
            a for a in all_articles
            if a.get("url") and (
                not a.get("content") or
                len((a.get("content") or "").strip()) < 100
            )
        ]
        mode = "본문 없거나 100자 미만 기사"

    if not todo:
        print("✅ 재수집할 기사가 없습니다.")
        _refetch_heartbeat(sb, '할 일 없음')
        return

    print(f"📋 {mode}: {len(todo)}건\n")

    ok, fail, skip, invalid = 0, 0, 0, 0
    for i, article in enumerate(todo, 1):
        title  = (article.get("title") or "")[:50]
        source = article.get("source") or ""
        url    = article.get("url") or ""
        print(f"[{i:3d}/{len(todo)}] [{source}] {title}... ", end="", flush=True)

        # URL 유효성 확인 및 변환
        resolved = resolve_url(url)
        if not resolved:
            print("⏭  상대경로 URL — 건너뜀")
            invalid += 1
            continue

        try:
            # 과기정통부 게시물(보도자료·입법예고·고시)은 상세 페이지가 스텁("첨부 참고")이라
            # 첨부(HWPX/PDF)에서 전문을 추출한다 — press_ingest 추출기 재사용 (#53).
            # 실패하면 기존 페이지 텍스트 경로로 폴백.
            body, actual_date = None, None
            if 'msit.go.kr/bbs/view.do' in resolved:
                try:
                    import press_ingest
                    raw = press_ingest.msit_extract({'url': resolved})
                    if raw and len(raw) >= 120:
                        body = press_ingest._clean_body(raw)[:8000]
                        print("📎 첨부 추출 ", end="")
                except Exception:
                    body = None
            if not body:
                body, actual_date = crawler.fetch_article_body(resolved, source)
            if not body:
                print("⏭  본문 없음 (셀렉터 미매칭 또는 접근 차단)")
                skip += 1
                continue

            # 실제 기사 날짜로 published_at 업데이트
            update_data = {
                "content": body,
                "url": resolved,
                "content_fetched_at": datetime.now(KST).isoformat()
            }

            # 실제 날짜 확인 → 60일 초과 시 삭제
            if actual_date:
                try:
                    from dateutil import parser as _dtp
                    pub_dt = _dtp.parse(actual_date)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=KST)
                    age_days = (datetime.now(KST) - pub_dt).days
                    if age_days > 60 and not article.get("locked"):
                        sb.table("news_feed").delete().eq("id", article["id"]).execute()
                        print(f"🗑  실제 발행일 {actual_date[:10]} ({age_days}일 전) — 60일 초과 삭제")
                        ok += 1
                        continue
                    elif age_days > 15:
                        update_data["published_at"] = actual_date
                        print(f"🔒 60일 초과지만 잠금 기사 — 보존 ({actual_date[:10]})", end="")
                    else:
                        update_data["published_at"] = actual_date
                        print(f"✅ ({len(body)}자, 날짜보정 {actual_date[:10]})", end="")
                except Exception:
                    pass
            else:
                print(f"✅ ({len(body)}자)", end="")

            # 본문 수집 직후 요약 자동 생성
            summary = crawler.generate_summary(
                article.get("title", ""),
                article.get("source", ""),
                article.get("published_at", ""),
                body
            )
            if summary:
                update_data["summary"] = summary

            sb.table("news_feed").update(update_data).eq("id", article["id"]).execute()
            print()
            ok += 1

        except Exception as e:
            print(f"❌ 실패: {e}")
            fail += 1

        time.sleep(DELAY_BETWEEN)

    print(f"\n완료! 성공 {ok}건 · 실패 {fail}건 · 미매칭 {skip}건 · 상대경로 {invalid}건")

    # ── 뉴스 요약 백필 ───────────────────────────────────
    # 본문은 있지만 요약이 없는 기사를 자동으로 채워 대시보드 첫 클릭 대기 제거
    try:
        sum_resp = sb.table("news_feed") \
            .select("id,title,source,published_at,content") \
            .is_("summary", "null") \
            .not_.is_("content", "null") \
            .order("published_at", desc=True) \
            .limit(30).execute()
        no_summary = [a for a in (sum_resp.data or []) if len((a.get("content") or "").strip()) >= 100]
        if no_summary:
            print(f"\n[요약 백필] summary 없는 기사 {len(no_summary)}건 생성 시작")
            for a in no_summary:
                s = crawler.generate_summary(
                    a.get("title", ""), a.get("source", ""),
                    a.get("published_at", ""), a.get("content", "")
                )
                if s:
                    sb.table("news_feed").update({"summary": s}).eq("id", a["id"]).execute()
                    print(f"  ✅ {a.get('title','')[:40]}")
                time.sleep(0.5)
        else:
            print("\n[요약 백필] 모든 기사에 summary 있음 — 건너뜀")
    except Exception as e:
        print(f"\n[요약 백필 오류] {e}")

    # ── 기술 용어 설명 백필 ──────────────────────────────
    # description이 비어 있는 용어를 자동으로 채워 대시보드 첫 클릭 대기 제거
    try:
        resp = sb.table("tech_terms").select("id,term,term_en,category,definition") \
            .is_("description", "null").limit(20).execute()
        missing = resp.data or []
        if missing:
            print(f"\n[용어 설명 백필] description 없는 용어 {len(missing)}건 생성 시작")
            crawler.generate_term_descriptions(missing)
        else:
            print("\n[용어 설명 백필] 모든 용어에 description 있음 — 건너뜀")
    except Exception as e:
        print(f"\n[용어 설명 백필 오류] {e}")

    # ── heartbeat ── (운영 상태 탭 '본문 수집(refetch) 마지막 실행')
    _refetch_heartbeat(sb, f'ok={ok} fail={fail} skip={skip}')


if __name__ == "__main__":
    main()
