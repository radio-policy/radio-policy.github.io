"""
뉴스 중복 대조 공용 (2026-09-26, #234 — 개선안 §2-13 2단계).

크롤러는 새로 모은 후보가 '이미 있는 기사'인지 보려고 실행마다 news_feed(url·제목)·deleted_news·
news_screen_cache 전량을 1,000행씩 내려받았다(10분 크롤 1회 47요청·약 5초, 하루 ≈6,700요청).
판정은 후보 각각의 '정확 일치 여부'뿐이므로, 후보만 DB 함수에 넘겨 겹치는 것만 돌려받아도 결과가 같다.
  ① known_or_full     — 후보 url·제목 중 이미 있는 것(news_known_items). 실패하면 전량 조회로 되돌아간다.
  ② screen_cache      — 후보 url 중 같은 기준문으로 '무관' 판정된 것(news_screen_cache_lookup). 실패하면 전량 조회.
  ③ fetch_all_rows    — 전량 조회(되돌아갈 길). 정렬은 유일 열이어야 한다(#233).

지키는 것:
  - '최근 N일' 창으로 좁히지 않는다 — 정확 일치 전수 대조(2026-08-03 재발송 사고: 잘린 명단 → 이미 알린 긴급 기사 재발송).
  - 기사 명단을 끝내 못 받으면 예외를 그대로 올린다. 빈 명단으로 진행하면 모든 후보가 '새 기사'가 되어
    재알림·AI 재판정이 쏟아진다. (삭제 목록·선별 캐시는 종전처럼 실패해도 진행 — 전자는 재수집, 후자는 비용만 늘어난다.)
  - DB 함수는 service_role 전용(anon·authenticated 실행 불가). 호출하는 세 곳 모두 SUPABASE_SERVICE_KEY.
"""

RPC_CHUNK = 1000          # 한 번에 넘기는 후보 수 — 평소 한 실행 후보 ≈1,100건이라 1~2왕복
SUSPECT_MIN = 200         # 후보가 이만큼 이상인데 기존 url이 0건이면 이상으로 보고 전량 조회로 확인


def fetch_all_rows(sb, table: str, columns: str, order: str = 'id') -> list:
    """PostgREST는 요청당 최대 1,000행 — 반드시 페이지로 나눠 받는다(#66).
    order는 표의 유일 열(기본 id, news_screen_cache는 url) — 정렬이 없거나 겹치면 요청마다
    행 순서가 달라져 페이지 경계에서 행이 빠지거나 겹친다(#233)."""
    rows, page, step = [], 0, 1000
    while True:
        res = (sb.table(table).select(columns).order(order)
               .range(page * step, (page + 1) * step - 1).execute())
        chunk = res.data or []
        rows.extend(chunk)
        if len(chunk) < step:
            return rows
        page += 1


def full_existing(sb, *, include_deleted: bool) -> tuple:
    """(url 집합, 제목 집합) — news_feed 전량(+deleted_news). news_feed 조회 실패는 그대로 raise."""
    data = fetch_all_rows(sb, 'news_feed', 'url,title')
    urls = {r['url'] for r in data if r.get('url')}
    titles = {r['title'] for r in data if r.get('title')}
    if include_deleted:
        try:
            ddata = fetch_all_rows(sb, 'deleted_news', 'url,title')
            urls |= {r['url'] for r in ddata if r.get('url')}
            titles |= {r['title'] for r in ddata if r.get('title')}
        except Exception as e:
            print(f'[삭제목록] deleted_news 조회 실패(무시): {e}')
    return urls, titles


def known(sb, urls, titles, *, include_deleted: bool) -> tuple:
    """후보 중 이미 있는 (url 집합, 제목 집합) — DB 함수 news_known_items. 실패는 raise."""
    urls = sorted({u for u in urls if u})
    titles = sorted({t for t in titles if t})
    ku, kt = set(), set()
    for i in range(0, max(len(urls), len(titles)), RPC_CHUNK):
        r = sb.rpc('news_known_items', {
            'p_urls': urls[i:i + RPC_CHUNK],
            'p_titles': titles[i:i + RPC_CHUNK],
            'p_include_deleted': include_deleted,
        }).execute().data
        if not isinstance(r, dict):
            raise ValueError(f'news_known_items 응답 형식 이상: {type(r).__name__}')
        ku |= set(r.get('urls') or [])
        kt |= set(r.get('titles') or [])
    return ku, kt


def known_or_full(sb, items, *, include_deleted: bool, label: str = '기존') -> tuple:
    """items(후보 dict 목록)의 url·title 중 이미 있는 것 → (url 집합, 제목 집합).

    반환 집합은 후보에 든 것만 담는다 — 호출부는 후보의 포함 여부만 보므로 전량 집합과 판정이 같다.
    DB 함수가 실패하거나, 후보가 SUSPECT_MIN 이상인데 기존 url이 0건이면(10분 전 실행과 겹치는 기사가
    하나도 없을 수는 없다) 전량 조회로 되돌아간다."""
    urls = [(it.get('url') or '') for it in items]
    titles = [(it.get('title') or '') for it in items]
    n_url = len({u for u in urls if u})
    try:
        ku, kt = known(sb, urls, titles, include_deleted=include_deleted)
        if n_url >= SUSPECT_MIN and not ku:
            print(f'[{label}] DB 대조 결과 이상(후보 url {n_url}건 중 기존 0건) — 전량 조회로 확인')
        else:
            print(f'[{label}] 후보 url {n_url}건 중 기존 {len(ku)}건 · 제목 기존 {len(kt)}건 (DB 대조)')
            return ku, kt
    except Exception as e:
        print(f'[{label}] DB 대조 실패 — 전량 조회로 진행: {str(e)[:160]}')
    eu, et = full_existing(sb, include_deleted=include_deleted)
    print(f'[{label}] 전량 조회 url {len(eu)}건 · 제목 {len(et)}건')
    return eu, et


def screen_cache(sb, urls, criteria_hash: str) -> dict:
    """{url: title_hash} — 후보 url 중 현재 기준문 지문으로 무관 판정된 것. DB 함수 실패 시 전량 조회,
    그것도 실패하면 빈 dict(전량 AI 판정으로 진행 — 돈만 더 쓰고 기사는 안 놓친다)."""
    urls = sorted({u for u in urls if u})
    try:
        out = {}
        for i in range(0, len(urls), RPC_CHUNK):
            r = sb.rpc('news_screen_cache_lookup', {
                'p_urls': urls[i:i + RPC_CHUNK], 'p_criteria_hash': criteria_hash,
            }).execute().data
            if not isinstance(r, dict):
                raise ValueError(f'news_screen_cache_lookup 응답 형식 이상: {type(r).__name__}')
            out.update(r)
        return out
    except Exception as e:
        print(f'[선별 캐시] DB 대조 실패 — 전량 조회로 진행: {str(e)[:160]}')
    try:
        rows = fetch_all_rows(sb, 'news_screen_cache', 'url,title_hash,criteria_hash', order='url')
        return {r['url']: r['title_hash'] for r in rows if r.get('criteria_hash') == criteria_hash}
    except Exception as e:
        print(f'[선별 캐시] 로드 실패(전량 판정으로 진행): {str(e)[:80]}')
        return {}
