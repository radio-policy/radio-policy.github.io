#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""정부·기관 사이트 접속 가능성 진단 (읽기 전용).

왜 필요한가:
  gov_notice_crawler.py는 "정부 사이트가 해외 IP를 차단한다"는 가정 아래 PC 전용으로
  묶여 있었다. 그런데 2026-08-28~31 운영자가 PC를 필리핀에 두고 실행했을 때 나흘 내내
  정상 수집됐다(총 68~71건, 평소와 동일) — **해외 일반 IP는 막히지 않는다**는 실측.
  남은 미확인은 **GitHub Actions의 데이터센터 IP**다. 봇 차단이 클라우드 대역만 따로
  막는 경우가 흔해, 호텔 IP 성공이 곧 Actions 성공을 뜻하지 않는다.

이 스크립트가 하는 일:
  gov_notice_crawler.py가 긁는 10개 페이지에 **똑같은 방식**(curl_cffi
  impersonate='chrome110')으로 접속해 HTTP 상태와 표 행 수만 보고한다.

안전:
  - DB에 쓰지 않는다. 텔레그램·메일을 보내지 않는다. 환경변수도 안 읽는다.
  - 순수 GET만 하므로 어디서 돌려도 부작용이 없다.

사용:  python tools_gov_reachability.py
"""
import re
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')   # 스케줄러 cp949 캡처 대비(지침 #19)

try:
    from curl_cffi import requests
    IMPERSONATE = True
except ImportError:
    import requests
    IMPERSONATE = False

from bs4 import BeautifulSoup

# gov_notice_crawler.py의 대상과 동일 (2026-09-01 기준)
TARGETS = [
    ('RRA 고시·공고',      'https://www.rra.go.kr/ko/reference/lawList.do',   'table.board_list tbody tr, table tbody tr'),
    ('RRA 행정예고',       'https://www.rra.go.kr/ko/notice/atnList.do',      'table.board_list tbody tr, table tbody tr'),
    ('RRA 공지사항',       'https://www.rra.go.kr/ko/notice/noticeList.do',   'table.board_list tbody tr, table tbody tr'),
    ('RRA 보도자료',       'https://www.rra.go.kr/ko/notice/newsList.do',     'table.board_list tbody tr, table tbody tr'),
    # MSIT는 2026-07 개편으로 목록 DOM이 빈 껍데기이고 제목을 인라인 스크립트가 채운다
    # → CSS 선택자가 아니라 정규식으로 세어야 한다 (gov_notice_crawler.py:269 참조, 배경역사 #39)
    ('MSIT 보도자료',      'https://www.msit.go.kr/bbs/list.do?sCode=user&mPid=208&mId=307', 'RE:MSIT'),
    ('MSIT 입법행정예고',  'https://www.msit.go.kr/bbs/list.do?sCode=user&mPid=103&mId=109', 'RE:MSIT'),
    ('CRMS 보도자료',      'https://www.crms.go.kr/lay1/bbs/S1T30C34/A/77/list.do', 'table tbody tr'),
    ('CRMS 공지사항',      'https://www.crms.go.kr/lay1/bbs/S1T30C31/A/10/list.do', 'table tbody tr'),
    ('KCC 보도자료',       'https://www.kcc.go.kr/user.do?boardId=1113&page=A05030000&dc=K05030000', 'table tbody tr, ul li'),
    # 방미통위 회의 게시판 + 첨부 다운로드 (kmcc_meeting.py, 2026-09-11 #154) — 목록은 #113 에서 열림이 확인됐지만
    # download.do 는 미실측이었다. 'RE:PDF' 는 Referer 를 붙여 받은 바이트가 %PDF 로 시작하면 행 1 로 센다.
    ('KMCC 위원회회의',    'https://www.kmcc.go.kr/user.do?boardId=1003&page=A02010100&dc=K02010100', 'table tbody tr'),
    ('KMCC download.do',   'https://www.kmcc.go.kr/download.do?fileSeq=71864', 'RE:PDF'),
    ('ETRI 보도자료',      'https://www.etri.re.kr/kor/bbs/list.etri?b_board_id=ETRI06', 'table tbody tr, ul li'),
    ('KISDI',              'https://www.kisdi.re.kr/index.do', 'a'),
    # 쿼리스트링 없이는 빈 목록이 온다 — 실제 크롤러와 동일하게 맞춘다 (gov_notice_crawler.py:854)
    ('입법예고(lawmaking)', 'https://opinion.lawmaking.go.kr/gcom/ogLmPp?isOgYn=Y&opYn=Y&pageIndex=1', 'table tbody tr'),
]

# ── 뉴스 본문 (2026-09-24 추가) ────────────────────────────────────────────────
# crawler.py는 Actions에서 본문 수집을 건너뛴다(2026-06-04 커밋 334ff2c, 사유 "한국 뉴스 사이트 차단" —
# 실측 기록 없음). 그 결과 10분 크롤의 긴급도 판정이 제목(+네이버 요약)만 보게 됐다(#188).
# 여기서는 크롤러와 같은 조건(일반 파이썬 HTTP + 브라우저 UA, TLS 위장 없음)으로 먼저 열어 보고,
# 실패하면 curl_cffi 위장으로 한 번 더 열어 본다 — "막힌다"와 "위장하면 열린다"를 가른다.
# 판정: 본문 후보 요소의 텍스트가 300자 이상이면 성공. 표본은 최근 7일 news_feed 상위 도메인.
NEWS_BODY_CSS = ('#dic_area, #article-view-content-div, #articleBody, div.article_body, '
                 '#news-contents, div.article-body, div[itemprop="articleBody"], article')
NEWS_TARGETS = [
    ('네이버 뉴스',     'https://n.news.naver.com/mnews/article/666/0000124771?sid=103'),
    ('디지털투데이',    'https://www.digitaltoday.co.kr/news/articleView.html?idxno=702579'),
    ('이투데이',        'https://www.etoday.co.kr/news/view/2629191'),
    ('아주경제',        'https://www.ajunews.com/view/20260924105444887'),
    ('뉴스핌',          'https://www.newspim.com/news/view/20260923000857'),
    ('서울경제TV',      'https://www.sentv.co.kr/article/view/sentv202609230083'),
    ('IT조선',          'https://it.chosun.com/news/articleView.html?idxno=2023092170777'),
]
NEWS_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'


def _body_len(html: str) -> int:
    soup = BeautifulSoup(html, 'html.parser')
    best = 0
    for el in soup.select(NEWS_BODY_CSS):
        best = max(best, len(re.sub(r'\s+', ' ', el.get_text(' ', strip=True))))
    return best


def _plain_get(url: str):
    """crawler.py의 requests.get과 같은 부류(파이썬 TLS 지문, 브라우저 UA만)."""
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': NEWS_UA, 'Accept-Language': 'ko,en;q=0.8'})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read()
        enc = r.headers.get_content_charset() or 'utf-8'
        return r.status, raw.decode(enc, errors='replace')


def probe_news(name: str, url: str):
    """(일반 성공, 위장 성공|None, 메모). 위장은 일반이 실패했을 때만 시도한다."""
    plain_ok, plain_note = False, ''
    try:
        status, html = _plain_get(url)
        n = _body_len(html)
        plain_ok = status == 200 and n >= 300
        plain_note = 'HTTP %s/본문%d자' % (status, n)
    except Exception as e:
        plain_note = type(e).__name__ + (':' + str(getattr(e, 'code', '') or '')).rstrip(':')
    imp_ok, imp_note = None, ''
    if not plain_ok and IMPERSONATE:
        try:
            res = requests.get(url, impersonate='chrome110', timeout=25)
            n = _body_len(res.text)
            imp_ok = res.status_code == 200 and n >= 300
            imp_note = 'HTTP %s/본문%d자' % (res.status_code, n)
        except Exception as e:
            imp_ok, imp_note = False, type(e).__name__
    print('  %-14s 일반 %-4s %-22s' % (name, 'OK' if plain_ok else '실패', plain_note)
          + ('' if imp_ok is None else '  위장 %-4s %s' % ('OK' if imp_ok else '실패', imp_note)))
    return plain_ok, imp_ok, plain_note


def probe(name: str, url: str, selector: str):
    """(성공여부, 실패사유) 반환. 실패사유는 Actions 주석에 실어 원격에서 읽는다."""
    try:
        hdr = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        if selector == 'RE:PDF':
            hdr['Referer'] = 'https://www.kmcc.go.kr/user.do'
        if IMPERSONATE:
            res = requests.get(url, impersonate='chrome110', timeout=25,
                               headers=({'Referer': hdr['Referer']} if 'Referer' in hdr else None))
        else:
            res = requests.get(url, timeout=25, headers=hdr)
        if selector == 'RE:PDF':
            rows = 1 if res.content[:4] == b'%PDF' else 0
        elif selector == 'RE:MSIT':
            # 목록 항목은 onclick="fn_detail(숫자)" 로만 드러난다
            rows = len(re.findall(r'onclick="fn_detail\((\d+)\);"', res.text))
        else:
            rows = len(BeautifulSoup(res.text, 'html.parser').select(selector))
        ok = res.status_code == 200 and rows > 0
        print('  %-22s HTTP %-3s  본문 %-7d 행 %-4d  %s'
              % (name, res.status_code, len(res.text), rows,
                 'OK' if ok else '의심 — 차단 또는 구조 변경'))
        if ok:
            return True, ''
        return False, 'HTTP %s/본문%dB/행%d' % (res.status_code, len(res.text), rows)
    except Exception as e:
        print('  %-22s 실패: %s' % (name, str(e)[:90]))
        return False, type(e).__name__


def main() -> int:
    print('=' * 62)
    print('정부·기관 사이트 접속 진단 (읽기 전용, DB 무변경)')
    print('TLS 지문 위장:', '활성(curl_cffi)' if IMPERSONATE else '없음(일반 requests)')
    print('=' * 62)

    results = []
    for i, t in enumerate(TARGETS):
        # 사이트 간 간격 — 쉼 없이 연속 요청하면 opinion.lawmaking.go.kr이
        # HTTP 200에 빈 목록을 돌려준다(단독 요청은 20행). 실제 크롤러도 요청
        # 사이에 time.sleep(1)을 둔다(gov_notice_crawler.py:904).
        if i:
            time.sleep(1)
        ok, why = probe(*t)
        results.append((t[0], ok, why))
    ok_n = sum(1 for _, ok, _w in results if ok)
    total = len(results)
    failed = ['%s(%s)' % (name, why) for name, ok, why in results if not ok]

    print('=' * 62)
    print('결과: %d/%d 정상' % (ok_n, total))
    if ok_n == total:
        print('판정: 이 실행 환경에서 전부 접속 가능 — 차단 없음')
    elif ok_n == 0:
        print('판정: 전부 실패 — IP 차단 가능성 높음(이 환경에서는 수집 불가)')
    else:
        print('판정: 일부만 실패 — 사이트별 개별 문제(구조 변경/일시 장애) 가능성')
    print('=' * 62)

    # GitHub Actions 주석으로도 남긴다 — 로그 API가 리다이렉트라 원격에서 읽기 어렵기 때문.
    # 주석은 check-runs API로 바로 조회된다.
    summary = '%d/%d 정상' % (ok_n, total)
    if failed:
        summary += ' | 실패: ' + ', '.join(failed)
    print('::notice title=gov-reachability::' + summary)

    # ── 뉴스 본문 진단 — 결과는 별도 주석(news-reachability)으로만 남기고 종료 코드에는 안 넣는다
    #    (정부 진단의 conclusion 의미를 그대로 두기 위해).
    print()
    print('뉴스 본문 접속 진단 (crawler.py가 Actions에서 건너뛰는 단계)')
    news = []
    for i, (name, url) in enumerate(NEWS_TARGETS):
        if i:
            time.sleep(1)
        news.append((name,) + probe_news(name, url))
    plain_n = sum(1 for _n, p, _i, _w in news if p)
    imp_n = sum(1 for _n, _p, im, _w in news if im)
    news_summary = '일반 %d/%d' % (plain_n, len(news))
    if IMPERSONATE:
        news_summary += ' | 위장 추가성공 %d' % imp_n
    news_summary += ' | ' + ', '.join('%s=%s' % (n, '일반OK' if p else ('위장OK' if im else '실패:' + w))
                                      for n, p, im, w in news)
    print('결과:', news_summary)
    print('::notice title=news-reachability::' + news_summary)

    # 전부 통과해야 성공으로 본다 — 원격에서는 conclusion만 보고도 판정할 수 있게.
    return 0 if ok_n == total else 1


if __name__ == '__main__':
    sys.exit(main())
