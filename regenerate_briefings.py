#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
과거 Daily Briefing 재생성 — 같은 사건 클러스터링 적용본으로 다시 만든다.

배경(#44·#46): 대형 사건 재보도가 하루 200건 넘게 쏟아지면 브리핑 입력 60건이
한 사건으로 도배돼 같은 내용이 6건씩 실리고 다른 뉴스는 밀려났다. 클러스터링을
넣은 뒤로 새 브리핑은 정상이지만, 이미 저장된 과거 브리핑은 그대로다.

사용:
    python regenerate_briefings.py 2026-07-16 2026-07-31        # 실제 재생성
    python regenerate_briefings.py 2026-07-16 2026-07-31 --dry  # 미리보기(DB 미변경)

주의:
- **원본은 반드시 daily_briefings_backup에 먼저 넣고 실행할 것.** 이 스크립트는
  백업하지 않는다(백업은 되돌리기 근거라 별도 단계로 남긴다).
- 뉴스는 60일 보관이므로 그보다 오래된 날짜는 재생성할 수 없다. 기사 0건이면 건너뛴다.
- 원본 앞머리의 📢 입법예고 섹션은 그대로 보존한다 — law_amendments를 다시 조회해
  재구성하면 당시 시점과 달라질 수 있어, 원본에서 잘라내 새 본문 앞에 다시 붙인다.
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import morning_briefing as mb   # sb 클라이언트·프롬프트·클러스터링을 그대로 재사용

KST = timezone(timedelta(hours=9))
sb = mb.sb


def fetch_day_items(day: datetime) -> list:
    """해당 날짜 브리핑이 봤을 24h 창(전날 06:00 ~ 당일 06:00 KST)의 본문 있는 기사."""
    end = day.replace(hour=6, minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=24)
    try:
        resp = sb.table('news_feed') \
            .select('id,title,source,url,published_at,content,urgency') \
            .gte('published_at', start.isoformat()) \
            .lt('published_at', end.isoformat()) \
            .not_.is_('content', 'null') \
            .order('published_at', desc=True) \
            .limit(300).execute()
        return [it for it in (resp.data or [])
                if it.get('content') and len(it['content'].strip()) > 50]
    except Exception as e:
        print(f'  [조회 오류] {e}')
        return []


def split_law_section(content: str) -> tuple:
    """원본에서 앞머리 📢 입법예고 섹션을 분리한다. 반환: (입법예고부, 나머지)"""
    # 제목이 바뀌어도 깨지지 않게 패턴으로 찾는다 (2026-08-05: '전파정책' → '통신·전파 정책').
    # 과거 저장분은 옛 제목이라, 문자열 고정 매칭이면 옛 브리핑에서 입법예고 분리가 통째로 실패한다.
    m = re.search(r'📡[^\n]*모닝 브리핑', content)
    idx = m.start() if m else -1
    if idx > 0:                       # 브리핑 본문 앞에 뭔가 있었다 = 입법예고 섹션
        return content[:idx].rstrip() + '\n\n', content[idx:]
    return '', content


def regenerate(day_str: str, dry: bool = False) -> bool:
    day = datetime.strptime(day_str, '%Y-%m-%d').replace(tzinfo=KST)
    cur = sb.table('daily_briefings').select('content,news_count,terms_count') \
        .eq('briefing_date', day_str).limit(1).execute()
    if not cur.data:
        print(f'{day_str}: 기존 브리핑 없음 — 건너뜀')
        return False
    original = cur.data[0]['content'] or ''

    items = fetch_day_items(day)
    if not items:
        print(f'{day_str}: 해당 창에 본문 기사 0건 (뉴스 보관기간 초과) — 건너뜀')
        return False

    # 날짜를 반드시 넘긴다 — 안 넘기면 '오늘' 기준이라 7/31 브리핑에 8/1이 찍히고
    # 전일 꼬리표도 엉뚱한 날과 비교된다 (#46에서 실제로 발생)
    clustered = mb.cluster_briefing_items(items, for_date=day)
    print(f'{day_str}: 기사 {len(items)}건 → {len(clustered)}묶음', end='')

    # 원본 대비 얼마나 줄어드는지 미리 보여준다 (효과 없는 날은 굳이 API를 쓰지 않기 위함)
    if len(clustered) == len(items):
        print(' — 중복 없음, 재생성 생략')
        return False

    if dry:
        top = sorted(clustered, key=lambda x: -(x.get('_related') or 0))[:5]
        print()
        for it in top:
            rel = it.get('_related', 0)
            print(f"    · {it['title'][:58]}" + (f'  (관련 {rel + 1}건)' if rel else ''))
        return True

    text = mb.generate_briefing(clustered, [], for_date=day)   # 용어는 원본 시점 값을 알 수 없어 생략
    if not text:
        print(' — 생성 실패, 원본 유지')
        return False

    text = mb.add_urgent_analyses(clustered, text)
    law_part, _ = split_law_section(original)    # 입법예고 섹션 보존
    final = law_part + text

    sb.table('daily_briefings').update({
        'content': final,
        'news_count': len(items),
    }).eq('briefing_date', day_str).execute()
    print(f' → 재생성 완료 ({len(original)}자 → {len(final)}자)')
    return True


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    start = datetime.strptime(sys.argv[1], '%Y-%m-%d')
    end = datetime.strptime(sys.argv[2], '%Y-%m-%d')
    dry = '--dry' in sys.argv

    print(f'{"="*60}')
    print(f'브리핑 재생성 {sys.argv[1]} ~ {sys.argv[2]}' + ('  [미리보기 — DB 미변경]' if dry else ''))
    print(f'{"="*60}')
    if not dry:
        chk = sb.table('daily_briefings_backup').select('briefing_date').execute()
        print(f'[백업] daily_briefings_backup {len(chk.data or [])}건 보관 중\n')

    done = 0
    d = start
    while d <= end:
        try:
            if regenerate(d.strftime('%Y-%m-%d'), dry):
                done += 1
        except Exception as e:
            print(f'{d:%Y-%m-%d}: 오류 — {e}')
        d += timedelta(days=1)

    print(f'\n{"="*60}')
    print(f'{"미리보기" if dry else "재생성"} 대상 {done}일')


if __name__ == '__main__':
    main()
