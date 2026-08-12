#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""8/11 과기정통부 보도자료 2건만 표적 백필 (#95).

  ① 독자 AI 파운데이션 모델 4개 정예팀 — Epoch AI 등재
     → SK텔레콤이 참여사라 관련. 종전 기준문에 「성과 홍보」로 걸러졌다.
  ② 과기정통부 인사(과장급)
     → 뉴스 경로는 부처 인사를 무조건 통과시키는데(is_ministry_personnel_news)
       보도자료 기준문에는 인사 항목이 아예 없어 누락됐다.

기준문(app_config.press_relevance_criteria)은 이미 갱신했으므로 AI 판정을 그대로 태운다
— 고친 기준문이 실제로 이 둘을 통과시키는지 확인하는 검증도 겸한다.
전량 백필(2024~)은 과하므로 최근 목록에서 제목으로 찾아 그 2건만 _collect_one에 넘긴다.
"""
import os
import sys
import time

sys.path.insert(0, r'C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai')
os.chdir(r'C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai')
sys.stdout.reconfigure(encoding='utf-8')

# 세션 셸의 사내 프록시는 정부 사이트 SSL을 깨뜨린다(지침 do-not)
for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
    os.environ.pop(k, None)

from dotenv import load_dotenv
# 경로 명시 — 인자 없이 부르면 dotenv가 이 스크립트(스크래치패드) 위치부터 훑어 .env를 못 찾는다
load_dotenv(r'C:\Users\SKTelecom\Desktop\frequence\radio-policy-ai\.env')

import press_ingest as pi
from sb_client import make_client

sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
DRY = '--dry-run' in sys.argv
WANT = ['파운데이션', '인사(과장급)']


def main():
    print('=' * 76)
    print('과기정통부 8/11 2건 표적 백필' + ('  [미리보기 — DB 무변경]' if DRY else ''))
    print('=' * 76)

    display, list_fn, extract_fn = pi.AGENCIES['과기정통부']

    found = []
    for page in range(1, 4):
        try:
            items = list_fn(page)
        except Exception as e:
            print('%d페이지 오류: %s' % (page, str(e)[:70]))
            break
        for it in items:
            if any(w in it['title'] for w in WANT) and \
               not any(f['url'] == it['url'] for f in found):
                found.append(it)
        if len(found) >= len(WANT):
            break

    print('\n대상 %d건 발견:' % len(found))
    for it in found:
        d = it.get('date')
        print('  · %-58s (%s)' % (it['title'][:58], d.strftime('%Y-%m-%d') if d else '?'))
    if not found:
        print('  대상 없음 — 목록에서 제목이 바뀌었거나 페이지가 넘어갔다')
        return

    judge = pi.make_ai_judge(sb, pi.load_press_keywords(sb))
    print('\n판정기: %s' % ('Haiku(갱신된 기준문)' if judge else '없음 → 키워드 폴백'))

    stats = {'new': 0, 'dup': 0, 'fail': 0, 'skip': 0}
    for it in found:
        print('\n■ %s' % it['title'][:58])
        pi._collect_one(sb, '과기정통부', it, extract_fn, stats, dry=DRY, judge=judge)
        time.sleep(1)

    print('\n' + '=' * 76)
    print('신규 %d · 중복 %d · 무관제외 %d · 실패 %d'
          % (stats['new'], stats['dup'], stats['skip'], stats['fail']))
    if stats['skip']:
        print('⚠️ 무관 판정이 남아 있다 — 기준문을 더 손봐야 한다')


if __name__ == '__main__':
    main()
