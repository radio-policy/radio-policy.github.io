# -*- coding: utf-8 -*-
"""소개 PPT에 넣을 화면 캡처 — 로컬 미리보기(http://127.0.0.1:8765)에서 뜬다.

왜 로컬인가: 배포본은 캐시 때문에 방금 고친 화면이 아직 안 보일 수 있다.
왜 스크립트인가: 화면을 고치면 이 스크립트를 다시 돌려 같은 구도로 다시 뜬다
                 (사람이 손으로 뜨면 구도·배율이 매번 달라져 장표가 들쭉날쭉해진다).

전제: .claude/launch.json 의 local-preview(python -m http.server 8765)가 떠 있어야 한다.
실행: C:/Users/SKTelecom/AppData/Local/Programs/Python/Python312/python.exe tools_deck_shots.py
산출: docs/shots/*.png  (PPT 생성기 make_intro_deck.py 가 이 경로를 읽는다)
"""
import os, sys, time
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8765'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs', 'shots')
# 장표 본문 영역이 가로로 길어(약 2.3:1), 세로가 긴 캡처는 양옆이 비어 작아 보인다.
VIEW = {'width': 1720, 'height': 860}


def shot(page, path, clip=None):
    os.makedirs(OUT, exist_ok=True)
    full = os.path.join(OUT, path)
    page.screenshot(path=full, clip=clip)
    print('  저장 %s (%d KB)' % (path, os.path.getsize(full) // 1024))


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport=VIEW, device_scale_factor=2)   # 2배율 — 장표에서 또렷하게
        pg.goto(BASE, wait_until='networkidle', timeout=60000)
        pg.wait_for_timeout(3000)
        # 앱 본문이 고정 폭이라 뷰포트만 넓히면 양옆 여백만 는다 — 화면의 '넓게 보기'를 켠다.
        try:
            pg.click('button:has-text("넓게 보기")', timeout=4000)
            pg.wait_for_timeout(1500)
            print('  넓게 보기 켬')
        except Exception:
            print('  (넓게 보기 버튼 없음 — 그대로 진행)')

        # ── 1) 법령 관계도 — 주제 하나를 펼친 모습 ──────────────
        pg.evaluate("go('lawmap', document.querySelector('[data-nav=\"lawmap\"]'))")
        pg.wait_for_timeout(6000)
        try:
            pg.evaluate("""(() => {
              const sel = document.querySelector('#lawmap-topic, select[id*=topic]');
              if (sel) {
                const opt = [...sel.options].find(o => /주파수 재할당/.test(o.textContent));
                if (opt) { sel.value = opt.value; sel.dispatchEvent(new Event('change', {bubbles:true})); }
              }
            })()""")
            pg.wait_for_timeout(6000)
        except Exception as e:
            print('  (주제 선택 건너뜀: %s)' % str(e)[:80])
        shot(pg, 'lawmap.png')

        # ── 2) 통합 모니터링 — 뉴스 목록(중요도 색 구분이 보이는 자리) ──
        pg.evaluate("go('news', document.querySelector('[data-nav=\"monitor\"]'), 'media')")
        pg.wait_for_timeout(6000)
        shot(pg, 'monitor.png')

        # ── 3) 과방위 회의록 — 발언 검색 결과 ──────────────────
        pg.evaluate("go('minutes', document.querySelector('[data-nav=\"minutes\"]'))")
        pg.wait_for_timeout(4000)
        pg.fill('#asm-search-q', '주파수 재할당')
        pg.click('button:has-text("발언 찾기")')
        pg.wait_for_timeout(9000)
        shot(pg, 'minutes_search.png')

        b.close()
    print('완료 — %s' % OUT)


if __name__ == '__main__':
    main()
