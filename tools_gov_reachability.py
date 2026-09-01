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
    ('ETRI 보도자료',      'https://www.etri.re.kr/kor/bbs/list.etri?b_board_id=ETRI06', 'table tbody tr, ul li'),
    ('KISDI',              'https://www.kisdi.re.kr/index.do', 'a'),
    # 쿼리스트링 없이는 빈 목록이 온다 — 실제 크롤러와 동일하게 맞춘다 (gov_notice_crawler.py:854)
    ('입법예고(lawmaking)', 'https://opinion.lawmaking.go.kr/gcom/ogLmPp?isOgYn=Y&opYn=Y&pageIndex=1', 'table tbody tr'),
]


def probe(name: str, url: str, selector: str) -> bool:
    try:
        if IMPERSONATE:
            res = requests.get(url, impersonate='chrome110', timeout=25)
        else:
            res = requests.get(url, timeout=25,
                               headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        if selector == 'RE:MSIT':
            # 목록 항목은 onclick="fn_detail(숫자)" 로만 드러난다
            rows = len(re.findall(r'onclick="fn_detail\((\d+)\);"', res.text))
        else:
            rows = len(BeautifulSoup(res.text, 'html.parser').select(selector))
        ok = res.status_code == 200 and rows > 0
        print('  %-22s HTTP %-3s  행 %-4d  %s'
              % (name, res.status_code, rows, 'OK' if ok else '의심 — 차단 또는 구조 변경'))
        return ok
    except Exception as e:
        print('  %-22s 실패: %s' % (name, str(e)[:90]))
        return False


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
        results.append((t[0], probe(*t)))
    ok_n = sum(1 for _, ok in results if ok)
    total = len(results)
    failed = [name for name, ok in results if not ok]

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

    # 전부 통과해야 성공으로 본다 — 원격에서는 conclusion만 보고도 판정할 수 있게.
    return 0 if ok_n == total else 1


if __name__ == '__main__':
    sys.exit(main())
