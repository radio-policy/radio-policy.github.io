# -*- coding: utf-8 -*-
"""잘린 기사 제목을 원문에서 다시 가져와 채운다 (#161-보론15, 2026-09-14).

왜 필요한가(실측 2026-09-14): `news_feed.title`의 **17.9%(11,495건 중 2,063건)가
'…' 또는 '...'로 끝난다.** 길이가 40~50자에 몰려 있고 정상 제목의 최대 길이는 76자다.
크롤러에는 제목을 자르는 코드가 없으니, 언론사가 목록·RSS용으로 축약해 주는 제목을
그대로 받는 것이다. 브리핑 화면은 제목에 링크를 거는 구조라, 인용부호가 열린 채 끊긴
제목이 그대로 클릭 대상이 되고 발언 취지가 반대로 읽히는 일이 반복 지적됐다.

`refetch_content.py`는 '본문이 없거나 100자 미만'인 기사만 다시 받으므로,
본문이 멀쩡한 채 제목만 잘린 이 기사들은 그 대상에 걸리지 않는다. 그래서 별도 백필이 필요하다.

안전 원칙(덮어쓰기 사고 방지):
  - 새 제목이 **더 길고**, **말줄임으로 끝나지 않고**, **기존 제목의 앞부분을 포함**할 때만 교체한다.
    (언론사가 나중에 바꾼 제목이나 추출 실패값이 멀쩡한 제목을 덮는 것을 막는다)
  - 길이 상한 200자, 최소 10자. 추출값에 사이트명 꼬리표('- OO신문')가 붙으면 떼어낸다.
  - AI 호출 0회. 페이지 HTML의 og:title → twitter:title → <title> 순으로만 읽는다.

사용법:
  python title_backfill.py --dry-run            # 변경 없이 표본 확인
  python title_backfill.py --limit 50           # 50건만
  python title_backfill.py --workers 12         # 동시 요청 수(기본 8)
  python title_backfill.py                      # 전체
"""
import argparse
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding='utf-8')
for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
    os.environ.pop(_k, None)

from dotenv import load_dotenv

load_dotenv()
import sb_client
import crawler

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = sb_client.make_client(SUPABASE_URL, SUPABASE_KEY)

CUT_RE = re.compile('(' + chr(0x2026) + r'|\.\.\.)\s*$')
# '제목 - 전자신문', '제목 | 연합뉴스', '제목 :: OO일보' 꼴의 매체명 꼬리표
TAIL_RE = re.compile(r'\s*[-|:]{1,2}\s*[^-|:]{2,20}$')

_lock = threading.Lock()
_stat = {'ok': 0, 'keep': 0, 'fail': 0}


def _clean(t: str) -> str:
    t = re.sub(r'\s+', ' ', (t or '')).strip()
    # 매체명 꼬리표는 한 번만 떼어낸다 — 제목 자체에 '-'가 들어간 경우를 과하게 깎지 않도록
    cut = TAIL_RE.sub('', t).strip()
    return cut if len(cut) >= 10 else t


def extract_title(html: str) -> str:
    """og:title → twitter:title → <title> 순으로 제목을 읽는다."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    for attrs in ({'property': 'og:title'}, {'name': 'twitter:title'},
                  {'property': 'twitter:title'}):
        tag = soup.find('meta', attrs=attrs)
        if tag and tag.get('content'):
            t = _clean(tag['content'])
            if len(t) >= 10:
                return t
    if soup.title and soup.title.string:
        return _clean(soup.title.string)
    return ''


def better(old: str, new: str) -> bool:
    """새 제목으로 바꿔도 되는가 — 보수적으로 판단한다."""
    if not new or len(new) < 10 or len(new) > 200:
        return False
    if CUT_RE.search(new):          # 새 것도 잘려 있으면 의미 없다
        return False
    if len(new) <= len(old):        # 더 짧아지면 교체하지 않는다
        return False
    # 기존 제목의 앞부분(말줄임 제거, 여유 있게 12자)이 새 제목에 들어 있어야 같은 기사다
    head = CUT_RE.sub('', old).strip()[:12]
    head = re.sub(r'\s+', '', head)
    return bool(head) and head in re.sub(r'\s+', '', new)


def work(row: dict, dry: bool) -> tuple:
    url = row.get('url') or ''
    old = (row.get('title') or '').strip()
    try:
        resp = crawler._http_get(url, timeout=8)
        resp.raise_for_status()
        if 'rra.go.kr' in url:
            resp.encoding = 'euc-kr'
        new = extract_title(resp.text)
    except Exception as e:
        with _lock:
            _stat['fail'] += 1
        return ('fail', old, str(e)[:40])

    if not better(old, new):
        with _lock:
            _stat['keep'] += 1
        return ('keep', old, new)

    if not dry:
        try:
            sb.table('news_feed').update({'title': new}).eq('id', row['id']).execute()
        except Exception as e:
            with _lock:
                _stat['fail'] += 1
            return ('fail', old, str(e)[:40])
    with _lock:
        _stat['ok'] += 1
    return ('ok', old, new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()

    rows, page = [], 0
    while True:
        r = sb.table('news_feed').select('id,title,url') \
            .order('published_at', desc=True).order('id').range(page * 1000, page * 1000 + 999).execute().data or []
        rows += r
        if len(r) < 1000 or page > 14:
            break
        page += 1

    todo = [r for r in rows if r.get('url') and CUT_RE.search((r.get('title') or '').strip())]
    if a.limit:
        todo = todo[:a.limit]
    print(f'전체 {len(rows)}건 / 제목 잘림 {len(todo)}건' + (' (dry-run)' if a.dry_run else ''))
    if not todo:
        print('할 일 없음')
        return

    shown = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for kind, old, new in ex.map(lambda r: work(r, a.dry_run), todo):
            done = _stat['ok'] + _stat['keep'] + _stat['fail']
            if kind == 'ok' and shown < 25:
                shown += 1
                print(f'  [교체] {old[:44]}')
                print(f'      -> {new[:64]}')
            if done % 200 == 0:
                print(f'  ... {done}/{len(todo)} 진행 (교체 {_stat["ok"]} / 유지 {_stat["keep"]} / 실패 {_stat["fail"]})')

    print(f'\n완료 — 교체 {_stat["ok"]} / 유지 {_stat["keep"]} / 실패 {_stat["fail"]}')


if __name__ == '__main__':
    main()
