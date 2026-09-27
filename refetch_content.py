"""
본문 미수집 기사 재수집 스크립트 (PC 전용 — 한국 IP)
- news_feed에서 content=NULL인 기사를 재수집
- v.daum.net URL → og:url로 원본 기사 URL 추출 후 수집
- 상대경로 URL(http 없음) → 건너뜀
- 실행: python refetch_content.py
- 옵션: python refetch_content.py --all   (content 있어도 전부 재수집)
- 주기: lampmanH-pc 작업 스케줄러 **10분마다**(#251, 2026-09-27 — 종전 매시 22분). 본문이 없는 기사는 팀 규칙
  문장 조건 판정(crawler.py)이 본문을 기다리므로(wait_body) 이 간격이 곧 판정 지연이다(≤1시간 → ≤20분).
- 실패 기사 미루기(#251 C5): 같은 기사는 마지막 실패에서 1시간이 지나야 다시 긁는다 — 끝내 못 긁는 기사(접속 차단·
  셀렉터 미매칭)를 하루 144번 두드리지 않게. 기록은 스크립트 옆 로컬 파일 refetch_failures.json
  ({기사 id: 마지막 실패 시각 ISO UTC}, git 무시)이고 7일 지난 기록은 매 실행 지운다. 파일이 없거나 깨지면 빈 기록으로
  시작하고, 기록 읽기·쓰기 실패는 재수집을 멈추지 않는다. --all(손 실행 전부 재수집)은 본문을 미루지 않고 결과만 기록한다.
  고친 셀렉터로 바로 다시 긁으려면 이 파일을 지우고 돌린다. 본문이 100자 미만으로 저장됐거나 제목만 고친 기사도 다음
  실행에 또 대상이라 실패처럼 기록한다 — 기록을 지우는 것은 100자 이상 본문을 저장했거나 기사를 지웠을 때뿐이다.
- 정부 공고 요약 실패도 같은 방식으로 1시간에 1번만(#251) — 같은 파일, 열쇠 'sum:<기사 id>'(본문 기록과 따로).
  본문 저장 직후 요약·요약 백필 둘 다 적용하고 --all이어도 미룬다(Haiku 비용 — 10분 주기에 빈 요약이 시간당 6번 불리지 않게).
  본문 저장 직후 요약은 요약이 이미 있고 새 본문이 저장된 본문과 같으면(앞뒤 공백 무시) 부르지 않는다(--all도).
- 요약 백필은 재수집 대상(최근 500건 중 본문 없거나 100자 미만)이 하나라도 있는 실행에서만 돈다(대상이 없으면 '할 일
  없음'으로 끝남). 대상이 모두 본문 미루기로 빠진 실행도 백필까지는 간다.
"""

import os, re, sys, time, json, tempfile, requests

# Windows 스케줄러/cp949 콘솔에서 이모지 print 크래시 방지 (UnicodeEncodeError)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from sb_client import make_client, heartbeat as sb_heartbeat

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

# 정부 공고 source 접두(#153) — app.js GOV_SOURCE_PREFIXES와 같은 목록에 정식 명칭을 더한 것.
# 요약을 **미리** 만드는 유일한 대상이다: 정부 공고는 event 라벨도 네이버 요약도 없어 대시보드
# 미리보기 대체 텍스트가 전혀 없다. 나머지 등급(참고·보통·긴급)은 첫 열람 때 생성(app.js).
GOV_SOURCE_PREFIXES = ['국립전파연구원', '과기정통부', '과학기술정보통신부', '방통위', '방송통신위원회',
                       '방송미디어통신위원회', '방미통위', '중앙전파관리소', 'ETRI', 'KISDI']


def _is_gov_source(source: str) -> bool:
    s = (source or '').strip()
    return any(s.startswith(p) for p in GOV_SOURCE_PREFIXES)
# ─────────────────────────────────────────────────────────────


# ── 실패 기사 미루기(#251 C5, 2026-09-27) ──────────────────────
# 10분마다 돌면 끝내 못 긁는 기사를 매번(하루 144번) 두드린다 → 같은 기사는 마지막 실패에서 FAIL_RETRY_MIN분이
# 지나야 다시 시도한다. 이 스크립트는 lampmanH-pc 한 대에서만 돌므로 DB 칸을 늘리지 않고 스크립트 옆 로컬 파일에 둔다.
# 아래 함수는 경로·시각을 인자로 받는 순수 함수다(tests/test_refetch_backoff.py). 기록은 미루기용일 뿐이라
# 읽기·쓰기가 실패해도 재수집·heartbeat는 그대로 간다(fail-open).
FAIL_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'refetch_failures.json')
FAIL_RETRY_MIN = 60    # 같은 기사 재시도 간격(분)
FAIL_KEEP_DAYS = 7     # 이보다 오래된 기록은 지운다(재수집 대상에서 빠졌거나 60일 정리로 지워진 기사)
SUM_PREFIX     = 'sum:'   # 정부 공고 요약 실패 기록의 열쇠 접두 — 본문 실패(기사 id 그대로)와 같은 파일에서 겹치지 않게


def summary_key(article_id):
    """요약 실패 기록 열쇠 'sum:<기사 id>' — 본문은 됐는데 요약만 실패하는 경우를 본문 미루기와 따로 센다."""
    return f'{SUM_PREFIX}{article_id}'


def _utcnow():
    return datetime.now(timezone.utc)


def _parse_utc(s):
    """ISO 시각 글 → 시간대 있는 datetime(시간대가 없으면 UTC로 본다). 읽을 수 없으면 None."""
    if not isinstance(s, str):
        return None
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def load_failures(path=None):
    """{기사 id(문자열): 마지막 실패 시각 ISO UTC}. 파일이 없거나 깨졌거나 모양이 다르면 빈 기록으로 시작한다."""
    path = path or FAIL_FILE
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:            # JSON 깨짐·UTF-8 아님(UnicodeDecodeError)·권한
        print(f"[실패 기록] {os.path.basename(path)} 읽기 실패 — 빈 기록으로 시작 ({e})")
        return {}
    if not isinstance(data, dict):
        print(f"[실패 기록] {os.path.basename(path)} 모양이 사전이 아님 — 빈 기록으로 시작")
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, str)}


def save_failures(failures, path=None):
    """같은 폴더의 임시 파일에 다 쓴 뒤 os.replace로 바꿔 끼운다 — 도중에 죽어도 파일은 옛것 아니면 새것(반쪽 JSON 없음).
    임시 파일 이름은 temp_ 로 시작한다(.gitignore temp_* — 강제 종료로 남아도 커밋되지 않게)."""
    path = path or FAIL_FILE
    fd, tmp = tempfile.mkstemp(prefix='temp_refetch_failures_', suffix='.tmp',
                               dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(failures, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def should_skip(failures, article_id, now=None):
    """마지막 실패가 FAIL_RETRY_MIN분 안이면 True(이번 실행은 건너뜀). 기록 없음·읽을 수 없는 시각·미래 시각
    (PC 시계가 되돌려진 경우)은 False — 다시 시도하고, 또 실패하면 지금 시각으로 다시 적힌다."""
    t = _parse_utc(failures.get(str(article_id)))
    if t is None:
        return False
    age = (now or _utcnow()) - t
    return timedelta(0) <= age < timedelta(minutes=FAIL_RETRY_MIN)


def record_failure(failures, article_id, now=None):
    failures[str(article_id)] = (now or _utcnow()).isoformat()


def clear_failure(failures, article_id):
    failures.pop(str(article_id), None)


def prune_failures(failures, now=None):
    """FAIL_KEEP_DAYS일보다 오래된 기록·읽을 수 없는 시각·하루 넘게 앞선 시각(시계 오류 — 영영 안 지워지므로)을
    지운다 → 지운 수."""
    now = now or _utcnow()
    old = []
    for k, v in failures.items():
        t = _parse_utc(v)
        if t is None or now - t > timedelta(days=FAIL_KEEP_DAYS) or t - now > timedelta(days=1):
            old.append(k)
    for k in old:
        del failures[k]
    return len(old)


def _persist_failures(failures, before, path=None):
    """바뀐 게 있을 때만 저장한다. 저장 실패는 알리기만 한다(다음 실행이 조금 일찍 다시 시도할 뿐)."""
    if failures == before:
        return
    try:
        save_failures(failures, path)
    except Exception as e:
        print(f"[실패 기록 저장 오류] {e}")


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


_TITLE_CUT_RE = re.compile('(' + chr(0x2026) + r'|\.\.\.)\s*$')



def _fix_title_only(sb, article: dict, url: str) -> bool:
    """본문 추출이 실패한 기사의 제목만 고친다(#161-보론15). 성공하면 True."""
    try:
        import title_backfill as tbf
        import crawler as _cr
        resp = _cr._http_get(url, timeout=8)
        resp.raise_for_status()
        if 'rra.go.kr' in url:
            resp.encoding = 'euc-kr'
        old = (article.get("title") or "").strip()
        new = tbf.extract_title(resp.text)
        if tbf.better(old, new):
            sb.table("news_feed").update({"title": new}).eq("id", article["id"]).execute()
            return True
    except Exception:
        pass
    return False


def main():
    regen_all = "--all" in sys.argv
    sb = make_client(SUPABASE_URL, SUPABASE_KEY)

    # ── 60일 초과 기사 일괄 정리 (locked=true 기사는 보존) ──────────
    # 해외(category='해외')는 제외한다 — 해외 규제기관은 발행일이 오래된 문서를 뒤늦게 공개하는 게
    # 정상이라(BEREC 6~7월 문서가 8월에 신규 수집됨) 발행일 기준으로 지우면 수집 즉시 삭제된다.
    # 실제로 2026-08-03 05:30 수집분 4건이 06:05 브리핑에 실린 뒤 이 규칙에 지워졌다.
    # foreign_press는 "발행일이 오래돼도 우리에게 새로우면 수집"인데 여기는 정반대로 동작했다. (#75)
    try:
        cutoff = (datetime.now(KST) - timedelta(days=60)).isoformat()
        purged = sb.table("news_feed").delete() \
            .lt("published_at", cutoff) \
            .eq("locked", False) \
            .neq("category", "해외") \
            .execute()
        n_purged = len(purged.data or [])
        if n_purged:
            print(f"🗑  60일 초과 기사 {n_purged}건 삭제 (잠금 기사 제외)")
    except Exception as e:
        print(f"[오래된 기사 정리 오류] {e}")

    # content=NULL 또는 100자 미만(제목만 저장된 경우) 기사 재수집
    # category는 60일 삭제 예외 판정(해외 제외, #75)에 쓰인다 — 빼면 조용히 None이 돼 예외가 안 먹는다
    # urgency는 '참고' 등급 요약 생략 판정(#82)에 쓴다 — 빼면 조용히 None이 돼 전건 요약으로 되돌아간다
    resp = sb.table("news_feed").select("id,title,source,url,content,published_at,summary,locked,category,urgency") \
        .order("published_at", desc=True).limit(500).execute()
    all_articles = resp.data or []

    if regen_all:
        # 방미통위 회의 의사일정 행은 kmcc_meeting.py 가 PDF 에서 복원한 content 를 이미 갖고 있다 —
        # 상세 페이지를 다시 긁으면 게시판 껍데기 텍스트로 덮이므로 --all 에서도 제외한다(#154)
        todo = [a for a in all_articles if a.get("url")
                and not (a.get("source") or "").startswith("방송미디어통신위원회 위원회 회의")]
        mode = "전체 재수집"
    else:
        # 제목이 '…'로 끝나는 기사도 대상에 넣는다(#161-보론15) — 언론사가 목록용으로
        # 축약해 준 제목을 그대로 받아 저장한 것이 전체의 17.9%였다. 브리핑은 제목에
        # 링크를 거는 구조라, 인용부호가 열린 채 끊긴 제목이 그대로 클릭 대상이 된다.
        # ⚠️ '제목 잘림' 단독 조건은 두지 않는다(#196) — 잘린 제목 보정은 아래 본문 재수집 경로에서
        # 본문 성공·실패와 무관하게 한 번 시도된다(새 기사는 Actions가 본문 없이 저장하므로 반드시 이 경로를 탄다).
        # 단독 조건이 있으면 원문도 잘려 고칠 수 없는 기사(09-24 실측 54건)를 매시간 2회씩 다시 긁었다.
        todo = [
            a for a in all_articles
            if a.get("url") and (
                not a.get("content") or
                len((a.get("content") or "").strip()) < 100
            )
        ]
        mode = "본문 없거나 100자 미만"

    # 실패 기사 미루기(#251) — 7일 지난 기록은 매 실행 지운다(할 일이 없는 실행도)
    failures = load_failures()
    failures_before = dict(failures)
    prune_failures(failures)

    if not todo:
        _persist_failures(failures, failures_before)
        print("✅ 재수집할 기사가 없습니다.")
        sb_heartbeat(sb, 'last_refetch_run', '할 일 없음')
        return

    print(f"📋 {mode}: {len(todo)}건\n")

    # 한 시간 안에 실패한 기사는 이번엔 긁지 않는다. --all(손 실행)은 미루지 않는다.
    wait = 0
    if not regen_all:
        now = _utcnow()
        ready = [a for a in todo if not should_skip(failures, a["id"], now)]
        wait = len(todo) - len(ready)
        todo = ready
        if wait:
            print(f"⏳ 한 시간 안에 실패한 기사 {wait}건 건너뜀\n")

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
            # 제목만 고치러 온 기사(본문은 이미 있음)는 본문 추출이 실패해도 제목은 고친다.
            if not body:
                fixed = _fix_title_only(sb, article, resolved)
                print("📝 제목만 보정" if fixed else "⏭  본문 없음 (셀렉터 미매칭 또는 접근 차단)")
                if fixed:
                    ok += 1
                else:
                    skip += 1
                # 제목만 고친 경우도 본문은 여전히 없어 다음 실행에 또 대상이다 → 둘 다 한 시간 뒤에 다시(#251).
                # 기록을 지우는 것은 100자 이상 본문을 저장했거나 기사를 지웠을 때뿐이다.
                record_failure(failures, article["id"])
                continue

            # 실제 기사 날짜로 published_at 업데이트
            update_data = {
                "content": body,
                "url": resolved,
                "content_fetched_at": datetime.now(KST).isoformat()
            }

            # 잘린 제목이면 원문 제목으로 되돌린다(#161-보론15).
            # 교체 조건은 title_backfill.better()와 같다 — 더 길고, 말줄임이 아니고,
            # 기존 제목의 앞부분을 포함할 때만. 실패해도 본문 저장은 그대로 진행한다.
            if _TITLE_CUT_RE.search((article.get("title") or "").strip()):
                if _fix_title_only(sb, article, resolved):
                    print(" 📝 제목 보정", end="")

            # 실제 날짜 확인 → 60일 초과 시 삭제
            if actual_date:
                try:
                    from dateutil import parser as _dtp
                    pub_dt = _dtp.parse(actual_date)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=KST)
                    age_days = (datetime.now(KST) - pub_dt).days
                    # 해외는 발행일이 오래된 게 정상이라 제외 — 위 일괄 정리와 같은 이유 (#75)
                    if (age_days > 60 and not article.get("locked")
                            and article.get("category") != '해외'):
                        sb.table("news_feed").delete().eq("id", article["id"]).execute()
                        print(f"🗑  실제 발행일 {actual_date[:10]} ({age_days}일 전) — 60일 초과 삭제")
                        ok += 1
                        clear_failure(failures, article["id"])
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

            # 본문 수집 직후 요약 자동 생성 — **정부 공고만**(2026-09-10, #153; 종전은 '참고'만 제외).
            #   요약을 쓰는 곳은 대시보드 목록 미리보기·상세뿐인데 보통·긴급 읽힘률이 0.9%·0.8%라
            #   월 3,200건 요약($11~12)이 대부분 버려졌다. 06시 브리핑은 content를 직접 읽고 게재분(≤50건)에
            #   요약을 역저장하며, 텔레그램은 제목·링크만 쓴다 — 둘 다 영향 없음. 대시보드는 summary가
            #   없으면 첫 열람 때 그 자리에서 생성해 DB에 되쓴다(app.js summarizeNews, 실측 ~3초).
            #   정부 공고는 예외: event 라벨도 네이버 요약도 없어 미리보기 대체 텍스트가 전혀 없다.
            #   ★ 아래 '요약 백필'의 조건과 반드시 짝을 맞출 것 — 한쪽만 바꾸면 백필이 도로 만든다(#82).
            #   요약 실패(빈 값·예외)도 1시간에 1번만 다시(#251, 열쇠 sum:<id>) — 본문이 100자 미만으로 저장돼 다음 실행에
            #   또 오는 기사, 그리고 같은 실행 뒤쪽 요약 백필이 방금 실패한 기사를 곧바로 다시 부르는 것을 막는다.
            #   요약이 이미 있고 새로 긁은 본문이 저장된 본문과 같으면(앞뒤 공백 무시 — 위 100자 판정과 같은 strip)
            #   다시 만들지 않는다(#251): 100자 미만 본문(국립전파연구원 trafilatura 51~99자)은 성공해도 매 실행 대상에
            #   남아, 10분 주기에 같은 요약을 시간당 6번 만든다. --all도 같다(본문이 같으면 요약도 같다).
            if _is_gov_source(article.get("source", "")):
                sk = summary_key(article["id"])
                same_body = bool(body.strip()) and body.strip() == (article.get("content") or "").strip()
                if same_body and (article.get("summary") or "").strip():
                    print(" (요약 유지 — 본문 같음)", end="")
                elif should_skip(failures, sk):
                    print(" ⏳ 요약 미룸(한 시간 안에 실패)", end="")
                else:
                    try:
                        summary = crawler.generate_summary(
                            article.get("title", ""),
                            article.get("source", ""),
                            article.get("published_at", ""),
                            body
                        )
                    except Exception:
                        record_failure(failures, sk)
                        raise                                   # 흐름은 그대로 — 아래 ❌ 실패로 간다
                    if summary:
                        update_data["summary"] = summary
                        clear_failure(failures, sk)
                    else:
                        record_failure(failures, sk)

            sb.table("news_feed").update(update_data).eq("id", article["id"]).execute()
            print()
            ok += 1
            # 100자 미만 본문(국립전파연구원 trafilatura 51~99자 등)은 저장은 하되 다음 실행에 또 재수집 대상이다(위 <100
            # 판정과 같은 strip) → 실패처럼 기록해 1시간에 1번만 다시 긁는다(#251 — 10분 주기에 같은 정부 페이지를 시간당
            # 6번 두드리고 DB를 6번 고쳐 쓰지 않게, 사이트 차단 위험). 100자 이상을 저장했을 때만 기록을 지운다.
            if len(body.strip()) < 100:
                record_failure(failures, article["id"])
            else:
                clear_failure(failures, article["id"])

        except Exception as e:
            print(f"❌ 실패: {e}")
            fail += 1
            record_failure(failures, article["id"])    # 한 시간 뒤에 다시(#251)

        time.sleep(DELAY_BETWEEN)

    print(f"\n완료! 성공 {ok}건 · 실패 {fail}건 · 미매칭 {skip}건 · 상대경로 {invalid}건")

    # ── 뉴스 요약 백필 ───────────────────────────────────
    # 본문은 있지만 요약이 없는 **정부 공고**만 채운다(#153) — 위 신규분 조건과 짝이다. 여기를
    # 넓히면 생략한 요약을 이 백필이 시간당 30건씩 도로 만들어 절감이 0이 된다(#82의 함정).
    # ⚠️ 이 백필은 위에서 '할 일 없음'으로 끝나지 않은 실행에서만 돈다(재수집 대상이 모두 미뤄진 실행은 온다).
    # 요약 실패(빈 값·예외)는 1시간에 1번만 다시(#251, 열쇠 sum:<id>) — 10분 주기에 같은 공고가 시간당 6번 불리지 않게.
    # 30건 상한·정렬은 그대로이고, 미룬 공고는 조회 뒤에 뺀다(그 자리를 다른 공고로 채우지 않는다).
    try:
        sum_resp = sb.table("news_feed") \
            .select("id,title,source,published_at,content") \
            .is_("summary", "null") \
            .not_.is_("content", "null") \
            .or_(",".join("source.like.%s*" % p for p in GOV_SOURCE_PREFIXES)) \
            .order("published_at", desc=True) \
            .limit(30).execute()
        no_summary = [a for a in (sum_resp.data or []) if len((a.get("content") or "").strip()) >= 100]
        now_s = _utcnow()
        ready_s = [a for a in no_summary if not should_skip(failures, summary_key(a["id"]), now_s)]
        sum_wait = len(no_summary) - len(ready_s)
        no_summary = ready_s
        if sum_wait:
            print(f"\n⏳ 한 시간 안에 요약 실패한 정부 공고 {sum_wait}건 건너뜀")
        if no_summary:
            print(f"\n[요약 백필] summary 없는 기사 {len(no_summary)}건 생성 시작")
            for a in no_summary:
                sk = summary_key(a["id"])
                try:
                    s = crawler.generate_summary(
                        a.get("title", ""), a.get("source", ""),
                        a.get("published_at", ""), a.get("content", "")
                    )
                except Exception:
                    record_failure(failures, sk)
                    raise                                       # 흐름은 그대로 — 아래 [요약 백필 오류]
                if s:
                    sb.table("news_feed").update({"summary": s}).eq("id", a["id"]).execute()
                    print(f"  ✅ {a.get('title','')[:40]}")
                    clear_failure(failures, sk)
                else:
                    record_failure(failures, sk)
                time.sleep(0.5)
        elif not sum_wait:
            print("\n[요약 백필] 모든 기사에 summary 있음 — 건너뜀")
    except Exception as e:
        print(f"\n[요약 백필 오류] {e}")

    _persist_failures(failures, failures_before)       # 본문·요약 실패 기록을 한 번에(바뀐 게 있을 때만)

    # ── 기술 용어 설명 백필 — 제거(2026-09-10, #153) ──
    # 같은 용어를 여기(Haiku, 매시)와 backfill_term_details.py(Sonnet, 05:00, term_extract.yml 2단계)가
    # 두 번 만들고 있었다. 05:00 Sonnet 경로가 단일 생성원이다(신규 하루 ~2.4건 < limit 10, 지연 ≤24h).
    # 관리자는 용어 모달의 ↺재생성으로 즉시 생성할 수 있다.

    # ── heartbeat ── (운영 상태 탭 '본문 수집(refetch) 마지막 실행')
    # wait = 한 시간 안에 본문 수집이 실패해 이번에 미룬 기사(#251 — 요약 미룸은 세지 않는다).
    # note를 읽는 곳은 운영 상태 탭(그대로 표시)과 DB watchdog_scan(정규식 '(fail|failed)=[1-9]' — 위치 무관)뿐이라
    # 뒤에 붙여도 해석이 바뀌지 않는다.
    sb_heartbeat(sb, 'last_refetch_run', f'ok={ok} fail={fail} skip={skip} wait={wait}')


if __name__ == "__main__":
    main()
