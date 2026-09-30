# -*- coding: utf-8 -*-
"""
받는 단위별 알림(#252, 설계안 §10 E5·E6·E9·A2 — ⚠️ Fable 재검토 대상) — crawler.py·subscriber_notify.py 쪽 테스트.
표준 unittest, **네트워크 0**(Supabase = 아래 메모리 가짜 FakeDb, 사건 묶기 Haiku = 가짜 FakeGroup, 즉시 배달 = 가짜).

  - 공통 경로 동일성: suppress_repeat_alerts를 포장 + 핵심(_suppress_core)으로 나눈 뒤에도 입력·출력·로그 행·로그 줄·
    사건 묶기 호출·기보도 조회가 **나누기 전 본문(아래 _ref_suppress_repeat_alerts — HEAD b2c213c에서 글자 그대로 옮김)**과
    같다(키워드 억제·의미판정 억제·리마인드(사슬 포함)·실행내 묶음·의미 재묶기·fail-open 여러 갈래). 다른 것은 억제 사슬 조회의
    정렬(id 추가)·페이지(range)뿐이고, 그 행동 차이는 로그가 1,000행을 넘을 때만 난다(따로 확인).
    ※ #263(2026-09-30): 실행 간 재보도 억제(①-2)는 묶기 분류기(group_same_event)에서 재보도 대조(match_prior_reports)로
      옮겼다 — 기준본은 그대로 두고, 같은 시나리오에서 '같은 기사를 같은 기보도와 묶는' 가짜 대조기(FakeMatch)를 물려 결과가
      같음을 본다. 달라진 것(기보도 조회 칸 event·screen_text, 사건 묶기 호출 1번 → 2차 묶기만, 억제 사슬을 못 읽은 실행은
      대조를 건너뜀)은 따로 확인한다. 새 단계의 세부(대표만 견줌·오염 제외·리마인드 취소)는 tests/test_dedup_match.py.
  - format_news_item(표시 키 없음)·queue_news_items(trigger=False)의 행이 나누기 전과 바이트 단위로 같다.
  - 사건 묶기 메모, 받는 단위 만들기, 알림 등급(팀원 수정 min·실장 합침), 복사 지름길 조건, 채널별 후보·비교군,
    late 후보(requested_by null·되살림 제외), 로그 → 큐 순서(이미 있는 기록이면 큐 안 넣음), 행 키 집합, 표시 문구,
    즉시 배달 호출 한 번(팀 단계 예외에도)·헤더, alert_suppress_log 불가침.
"""
import contextlib
import copy
import io
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 실 DB 자격증명 없이 import (클라이언트 생성만, 접속 없음) — test_smoke.py와 같은 방식
os.environ.setdefault('SUPABASE_URL', 'http://localhost')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-service-key')

import crawler  # noqa: E402
import news_dedup  # noqa: E402
import subscriber_notify  # noqa: E402

KST = timezone(timedelta(hours=9))
_THIS = sys.modules[__name__]
sb = None                   # 기준본 _ref_suppress_repeat_alerts가 읽는 전역 — 테스트가 가짜 DB로 바꾼다
ANTHROPIC_API_KEY = ''      # 〃
_REF_TRIGGERS = []          # 기준본 _ref_queue_news_items의 즉시 배달 호출 기록
esc = subscriber_notify.esc  # 기준본 _ref_format_news_item이 쓰는 이스케이프(바뀌지 않은 함수)


# ══════════════════════════════════════════════════════════════════════════════════════════════
#  나누기 전 기준본 — HEAD(b2c213c) crawler.suppress_repeat_alerts · subscriber_notify.format_news_item ·
#  queue_news_items를 글자 그대로 옮기고 이름만 바꿨다(queue의 _trigger_delivery()는 _REF_TRIGGERS 기록으로).
#  **고치지 말 것** — 공통 경로가 나누기 전과 같다는 증거다.
# ══════════════════════════════════════════════════════════════════════════════════════════════
def _ref_suppress_repeat_alerts(urgent_items: list) -> list:
    """같은 사건 재보도의 재알림 억제 (배경역사 #44).

    ① 최근 3일 내 이미 DB에 있던 긴급 기사와 제목 유사(공유 키워드 3+) → 억제.
       단, 국면 신호 단어(소송·고발·상고…)가 새로 등장한 제목은 통과(새 전개).
    ② 이번 실행분 안에서도 유사 기사는 대표 1건으로 묶고 '(관련 보도 N건)' 병기.
    ③ 사건 대표(실제 알림이 나간 기사)가 24시간을 넘었으면 재보도 1건을 '리마인드'로 통과(#181, 2026-09-21).
       억제가 사슬로 이어져(실측 80%) 며칠짜리 사건이 영영 안 오던 것을 하루 1건으로 되살린다.
    ①·②·③ 모두 alert_suppress_log에 남긴다(②는 shared_keywords='[실행내묶음]', ③은 '[리마인드]', 2026-09-21~) —
       이 로그가 곧 '알림으로 나가지 않은 기사' 목록이고, 사내판 다리(export_news.py)가
       이것으로 TOKTOK 대표 1건을 가린다(#180). Haiku 판정 층 추가 여부는 계속 실측 후 결정.
    어떤 오류든 나면 원본 그대로 반환(fail-open) — 판정이 죽어서 알림까지 죽으면 안 된다."""
    if not urgent_items:
        return urgent_items
    try:
        from news_dedup import extract_keywords, is_followup, cluster_star

        # 이번 실행에서 방금 저장한 기사는 비교 대상에서 빼야 한다 (자기 자신과 비교 방지)
        batch_urls = {i.get('url') for i in urgent_items}
        cutoff_3d = (datetime.now(KST) - timedelta(days=3)).isoformat()
        prior, prior_at = [], {}
        # origin is null — 이슈맵 보강 옛 기사(created_at = 넣은 시각)가 긴급이 되면 3일간 같은 사건의 새 알림을 막는다(#236)
        resp = sb.table('news_feed').select('title,url,created_at') \
            .eq('urgency', '긴급').gte('created_at', cutoff_3d).is_('origin', 'null') \
            .order('created_at', desc=True).limit(1000).execute()
        for r in (resp.data or []):
            if r.get('url') not in batch_urls:
                prior.append({'title': r.get('title') or '', 'kw': extract_keywords(r.get('title') or '')})
                prior_at.setdefault(r.get('title') or '', r.get('created_at'))   # 정렬이 최신순 = 가장 최근 것

        # ── 하루 1회 리마인드 (2026-09-21 #181) ──────────────────────────────
        # 억제는 사슬로 이어진다 — 실측(30일) 억제 821건 중 660건(80%)이 '이미 억제된 기사'에
        # 걸려서 막혔다. 그래서 며칠씩 이어지는 사건은 첫 알림 뒤 영영 다시 오지 않는다
        # (9/21 LGU+ 해킹 은폐: 긴급 8건 전부 억제, 뿌리는 9/18 기사). 사건의 **대표**(실제로
        # 알림이 나간 기사)가 24시간을 넘었으면 재보도 1건을 '리마인드'로 통과시킨다.
        # 통과분은 alert_suppress_log에 `[리마인드]`로 남긴다 — 미발송이 아니라 발송 기록이며,
        # 사슬을 여기서 끊어 다음 24시간을 새로 센다. 사내판 다리도 이 접두사로 구분한다(#180).
        REMIND_AFTER_H = 24
        sup_chain = {}                       # 억제된 제목 → 그때 걸린 기존 제목(사슬 한 칸)
        try:
            cutoff_10d = (datetime.now(KST) - timedelta(days=10)).isoformat()
            _lg = (sb.table('alert_suppress_log').select('article_title,matched_title,shared_keywords')
                   .gte('created_at', cutoff_10d).order('created_at').execute().data) or []
            for r in _lg:
                if str(r.get('shared_keywords') or '').startswith('[리마인드]'):
                    continue                 # 리마인드는 '나간 기사' — 사슬을 끊는다
                if r.get('article_title'):
                    sup_chain[r['article_title']] = r.get('matched_title') or ''
        except Exception as e:
            print(f'[긴급 억제] 억제 사슬 조회 실패 — 이번 실행은 리마인드 없이 종전대로: {e}')

        def _rep_age_h(matched_title: str):
            """사건 대표(마지막으로 실제 알림이 나간 기사)의 경과 시간(h). 모르면 None(=3일 창 밖)."""
            cur, seen = matched_title, set()
            while cur and cur in sup_chain and cur not in seen:
                seen.add(cur)
                cur = sup_chain[cur]
            at = prior_at.get(cur)
            if not at:
                return None                  # 3일 창 밖의 대표 = 72시간 초과 → 리마인드 대상
            try:
                t = datetime.fromisoformat(str(at).replace('Z', '+00:00'))
                return (datetime.now(KST) - t).total_seconds() / 3600
            except Exception:
                return None

        def _remind_label(age_h):
            return '이어지는 사건' if age_h is None else f'{int(age_h // 24) + 1}일째'

        passed, sup_rows, remind_rows, passed_kw = [], [], [], []
        for it in urgent_items:
            kw = extract_keywords(it.get('title') or '')
            matched = None
            for pv in prior:
                if is_followup(kw, pv['kw'], it.get('title') or '', pv['title']):
                    matched = pv
                    break
            if matched:
                age_h = _rep_age_h(matched['title'])
                if age_h is None or age_h >= REMIND_AFTER_H:
                    it['_remind'] = _remind_label(age_h)          # 하루 1회 리마인드로 통과
                    remind_rows.append({
                        'article_title': it.get('title') or '',
                        'article_url': it.get('url') or '',
                        'matched_title': matched['title'],
                        'shared_keywords': f"[리마인드] {it['_remind']}",
                    })
                    passed.append(it)
                    passed_kw.append(kw)
                    continue
                sup_rows.append({
                    'article_title': it.get('title') or '',
                    'article_url': it.get('url') or '',
                    'matched_title': matched['title'],
                    'shared_keywords': ','.join(sorted(kw & matched['kw'])),
                })
            else:
                passed.append(it)
                passed_kw.append(kw)

        # ── ①-2: 키워드로 못 잡은 '실행이 갈린' 재보도를 의미 판정으로 한 번 더 거른다 (2026-09-14) ──
        #  왜 필요한가(실측): 네팔 구호인력 로밍 면제 사건은 같은 내용 기사가 10건 들어왔고 그중 2건이
        #  긴급으로 분류됐는데, 10:03·10:49 실행으로 갈려 ①의 키워드 문턱(3개)만 거쳤다. 공유는 2개
        #  (네팔·구호인력)뿐 — '로밍' vs '로밍요금', '통신업계' vs '이통'+'3사', '무료' vs '전액면제'로
        #  같은 말이 다른 토큰이 되어 통과했고 한 시간 간격으로 두 통이 나갔다.
        #  #92의 의미 판정은 아래 ②(같은 실행분 묶기)에만 붙어 있어 실행이 갈리면 적용되지 않았다.
        #  후보는 키워드를 1개라도 공유하는 기보도로 한정한다 — 무관한 제목까지 태우면 오판도 비용도 는다.
        #  실행당 Haiku 1회(후보가 있을 때만), 실패하면 원본 유지(fail-open).
        if passed and prior and ANTHROPIC_API_KEY:
            cand = []                                  # 후보 기보도(제목 중복 제거, 최대 10건)
            seen_t = set()
            for pv in prior:
                if len(seen_t) >= 10:
                    break
                if pv['title'] and pv['title'] not in seen_t and any(kw & pv['kw'] for kw in passed_kw):
                    seen_t.add(pv['title'])
                    cand.append(pv)
            if cand:
                from news_dedup import group_same_event
                titles = [it.get('title') or '' for it in passed] + [pv['title'] for pv in cand]
                gidx = group_same_event(titles, ANTHROPIC_API_KEY)
                if gidx:
                    base = len(passed)
                    drop = {}                          # passed 인덱스 → 묶인 기보도
                    for g in gidx:
                        news = [i for i in g if i < base]
                        olds = [i - base for i in g if i >= base]
                        if news and olds:
                            for i in news:
                                drop[i] = cand[olds[0]]
                    if drop:
                        kept, kept_kw = [], []
                        for i, it in enumerate(passed):
                            pv = drop.get(i)
                            if pv is None:
                                kept.append(it)
                                kept_kw.append(passed_kw[i])
                                continue
                            age_h = _rep_age_h(pv['title'])
                            if age_h is None or age_h >= REMIND_AFTER_H:
                                it['_remind'] = _remind_label(age_h)   # 여기서도 하루 1회는 통과
                                remind_rows.append({
                                    'article_title': it.get('title') or '',
                                    'article_url': it.get('url') or '',
                                    'matched_title': pv['title'],
                                    'shared_keywords': f"[리마인드] {it['_remind']}",
                                })
                                kept.append(it)
                                kept_kw.append(passed_kw[i])
                                continue
                            sup_rows.append({
                                'article_title': it.get('title') or '',
                                'article_url': it.get('url') or '',
                                'matched_title': pv['title'],
                                'shared_keywords': '[의미판정] ' + ','.join(sorted(passed_kw[i] & pv['kw'])),
                            })
                        print(f'[긴급 억제] 의미 판정으로 실행 간 재보도 {len(drop)}건 판정(리마인드 포함)')
                        passed, passed_kw = kept, kept_kw

        # 같은 실행분 내 유사 기사 묶기 — 사건 첫날 첫 실행에 재보도 수십 건이
        # 한꺼번에 들어오면 한 통에 수십 줄이 되는 것을 대표 1건으로 줄인다
        groups = []                      # [(대표, [묶인 것들])] — 아래 2차 묶기와 형태를 맞춘다
        for rep, members in cluster_star(passed):
            groups.append((rep, list(members)))

        # ── 2차: 키워드로 못 묶인 대표들을 Haiku가 의미로 다시 묶는다 (#92) ──
        # 매체마다 관점이 달라 제목에 공통 단어가 거의 없는 사건이 있다(공정위 불공정약관 4건:
        # 쌍별 공유 키워드 최대 1개). 어휘로는 못 넘으므로 여기서만 의미 판정을 쓴다.
        # 실패하면 1차 결과를 그대로 쓴다(fail-open) — 판정이 죽어서 알림이 죽으면 안 된다.
        if len(groups) >= 2 and ANTHROPIC_API_KEY:
            from news_dedup import group_same_event
            merged_idx = group_same_event([g[0].get('title') or '' for g in groups], ANTHROPIC_API_KEY)
            if merged_idx and len(merged_idx) < len(groups):
                regrouped = []
                for idxs in merged_idx:
                    head = groups[idxs[0]]
                    others = [m for i in idxs[1:] for m in ([groups[i][0]] + groups[i][1])]
                    regrouped.append((head[0], head[1] + others))
                print(f'[긴급 억제] 의미 판정으로 {len(groups)}묶음 → {len(merged_idx)}묶음')
                groups = regrouped

        reps = []
        for rep, members in groups:
            rep['_related'] = len(members)
            if not rep.get('_remind'):
                for m in members:                     # 묶음 안의 리마인드 표시는 대표가 이어받는다
                    if m.get('_remind'):
                        rep['_remind'] = m['_remind']
                        break
            reps.append(rep)
            # 대표에 병합된 기사도 '알림으로 나가지 않은 기사'다 — 2026-09-21부터 로그에 남긴다.
            # 사내판 다리(export_news.py)가 alert_suppress_log만 보고 대표 1건을 가려내기 때문이며,
            # 여기 없으면 같은 사건의 첫 실행분이 TOKTOK으로 여러 통 나간다(#180). 알림 내용은 그대로다.
            for m in members:
                sup_rows.append({
                    'article_title': m.get('title') or '',
                    'article_url': m.get('url') or '',
                    'matched_title': rep.get('title') or '',
                    'shared_keywords': '[실행내묶음]',
                })

        if remind_rows:
            print(f'[긴급 억제] 대표가 24시간을 넘겨 리마인드로 통과 {len(remind_rows)}건')
        if sup_rows or remind_rows:
            n_run = sum(1 for r in sup_rows if r['shared_keywords'] == '[실행내묶음]')
            print(f'[긴급 억제] 알림 미발송 {len(sup_rows)}건 기록 (3일 내 기보도 {len(sup_rows) - n_run}건 · 실행내 묶음 {n_run}건)')
            try:
                sb.table('alert_suppress_log').insert(sup_rows + remind_rows).execute()
            except Exception as e:
                print(f'[긴급 억제] 로그 저장 실패(무시): {e}')
        merged = len(passed) - len(reps)
        if merged:
            print(f'[긴급 억제] 실행분 내 유사 {merged}건 대표에 병합')
        return reps
    except Exception as e:
        print(f'[긴급 억제] 판정 오류 → 전부 알림(fail-open): {e}')
        return urgent_items


def _ref_format_news_item(item) -> str:
    """기사 1건의 HTML — 헤더·번호·칩 **없이** 제목 링크 + (관련 보도 N건) + 출처만.

    format_urgent_html의 항목 조립부와 같은 모양을 유지할 것. 앞의 번호와 뒤의 칩 줄은
    발송 측(Edge)이 붙인다.
    """
    rel = item.get('_related', 0)
    rel_txt = f' <i>(관련 보도 {rel}건)</i>' if rel else ''
    rem = item.get('_remind') or ''                      # 하루 1회 리마인드 표시 (#181)
    title, url = esc(('🔁[' + rem + '] ' if rem else '') + str(item.get('title', ''))), esc(item.get('url', ''))
    head = f'<a href="{url}">{title}</a>' if url else f'<b>{title}</b>'
    return f'{head}{rel_txt}\n   <i>{esc(item.get("source", ""))}</i>'


def _ref_queue_news_items(sb, items: list) -> bool:
    """긴급 기사 목록 → subscriber_queue에 **기사당 1행**으로 한 번에 적재. 반환=성공 여부.

    어떤 예외도 밖으로 던지지 않는다(fail-open) — 큐 적재 실패가 크롤링·운영자 알림을 죽이면 안 된다.
    """
    if not items:
        return False

    # 최근 10분 내 같은 기사(news_url)가 이미 큐에 있으면 그 기사만 제외한다.
    # (queue_for_subscribers의 '10분 내 동일 내용 생략'과 같은 취지 — 크롤러 두 인스턴스가
    #  동시에 돌아 같은 기사를 각자 새 것으로 판단한 사고(2026-08-03) 방어. 묶음이 아니라
    #  기사 단위이므로 **중복분만 빼고 나머지는 넣는다** — 전체를 버리면 새 기사가 유실된다.)
    dup_urls = set()
    try:
        since = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        recent = (sb.table('subscriber_queue').select('news_url')
                  .eq('topic', 'urgent').gte('created_at', since).execute().data) or []
        dup_urls = {r.get('news_url') for r in recent if r.get('news_url')}
    except Exception as e:
        print(f'[구독자 큐] 중복 확인 실패(계속 진행): {e}')   # 확인 실패가 적재를 막으면 안 된다

    rows, skipped, seen = [], 0, set()
    for it in items:
        url = str(it.get('url') or '').strip()
        if url:
            if url in dup_urls or url in seen:
                skipped += 1
                continue
            seen.add(url)
        body = _ref_format_news_item(it)
        if not body.strip():
            continue
        tags = it.get('tags')
        if not isinstance(tags, list):
            tags = []
        # ★ 모든 행의 키 집합이 완전히 같아야 한다 ★ — PostgREST 벌크 insert는 객체 하나라도
        #   키가 다르면 전체가 실패한다. news_url은 빈 문자열이라도 NOT NULL(신·구형 판별자).
        rows.append({'topic': 'urgent', 'news_url': url,
                     'tags': [str(t) for t in tags], 'html': body[:3500]})

    if skipped:
        print(f'[구독자 큐] 10분 내 중복 기사 {skipped}건 제외')
    if not rows:
        print('[구독자 큐] 적재할 신규 기사 없음')
        return False

    try:
        sb.table('subscriber_queue').insert(rows).execute()
        print(f'[구독자 큐] urgent {len(rows)}건 기사 단위 적재 완료 — 각 구독자의 수신 시각에 발송됨')
    except Exception as e:
        print(f'[구독자 큐] 적재 실패(무시): {e}')
        return False
    _REF_TRIGGERS.append(1)   # 기준본의 _trigger_delivery() — 다음 정시(:25)를 기다리지 않고 바로 배달 시도
    return True


# ── 메모리 가짜 Supabase ─────────────────────────────────────────────────────────────────────────
def _tkey(v):
    """정렬·비교 열쇠 — ISO 시각은 시각으로(오프셋이 달라도), 나머지는 글자로. None은 뒤로."""
    if v is None:
        return (2, 0.0, '')
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (0, dt.timestamp(), '')
        except ValueError:
            return (1, 0.0, v)
    return (1, float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0, str(v))


class FakeDb:
    """표별 행 — select(eq·in_·gte·is_·or_·order·limit·range, **요청당 1,000행 상한**)·insert·upsert(PK 병합 /
    ignore_duplicates면 새 행만 응답)·update·delete. 모든 호출을 log에. fail = 표 이름 또는 (표, 동작).
    before = {(표, 동작): fn(db)} — 그 동작 직전에 한 번 부른다(동시 실행 흉내). flaky = {(표, 동작): n} — 처음 n번만 실패
    (일시 오류, 재시도 확인). fail_when = fn(쿼리) → 참이면 실패(예: 지워진 기사의 FK 오류)."""
    PK = {'subscriber_alert_log': ('audience', 'channel', 'news_id'), 'team_urgency': ('news_id', 'team_id'),
          'urgency_rule_verdicts': ('rule_id', 'sentence_rev', 'news_id'), 'app_config': ('key',),
          'news_feed': ('url',)}
    AUTO = ('subscriber_alert_log', 'subscriber_queue', 'alert_suppress_log')     # id·created_at 기본값이 있는 표
    MAX_ROWS = 1000

    def __init__(self, tables=None, fail=()):
        self.tables = {k: [dict(r) for r in v] for k, v in (tables or {}).items()}
        self.fail = set(fail)
        self.before = {}
        self.flaky = {}
        self.fail_when = None
        self.log = []
        self.seq = 0

    def table(self, name):
        return FakeQ(self, name)

    def calls(self, name, op=None):
        return [e for e in self.log if e['table'] == name and (op is None or e['op'] == op)]

    def rows(self, name, **key):
        return [r for r in self.tables.get(name, []) if all(r.get(k) == v for k, v in key.items())]


class FakeQ:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self.op, self.payload, self.kw, self.cols = 'select', None, {}, '*'
        self.filters, self.orders, self.lim, self.rng = [], [], None, None

    def select(self, cols='*', **_k):
        self.cols = cols
        return self

    def eq(self, c, v):
        self.filters.append(('eq', c, v))
        return self

    def in_(self, c, vs):
        self.filters.append(('in', c, list(vs)))
        return self

    def gte(self, c, v):
        self.filters.append(('gte', c, v))
        return self

    def is_(self, c, v):
        self.filters.append(('is', c, v))
        return self

    def or_(self, expr):
        import re as _re
        groups = []
        for m in _re.finditer(r'and\(([^()]*)\)', expr):
            conds = {}
            for part in m.group(1).split(','):
                col, op, val = part.split('.', 2)
                conds[col] = val
            groups.append(conds)
        self.filters.append(('or', groups, expr))
        return self

    def order(self, c, desc=False):
        self.orders.append((c, desc))
        return self

    def limit(self, n):
        self.lim = n
        return self

    def range(self, lo, hi):
        self.rng = (lo, hi)
        return self

    def insert(self, rows):
        self.op, self.payload = 'insert', [dict(r) for r in (rows if isinstance(rows, list) else [rows])]
        return self

    def upsert(self, rows, **kw):
        self.op, self.payload, self.kw = 'upsert', [dict(r) for r in (rows if isinstance(rows, list) else [rows])], dict(kw)
        return self

    def update(self, vals):
        self.op, self.payload = 'update', dict(vals)
        return self

    def delete(self):
        self.op = 'delete'
        return self

    def _ok(self, r):
        for kind, c, v in self.filters:
            if kind == 'or':
                if not any(all(str(r.get(col)) == val for col, val in g.items()) for g in c):
                    return False
                continue
            x = r.get(c)
            if kind == 'eq' and x != v:
                return False
            if kind == 'in' and x not in v:
                return False
            if kind == 'gte' and (x is None or _tkey(x) < _tkey(v)):
                return False
            if kind == 'is' and not (v == 'null' and x is None):
                return False
        return True

    def _new(self, r):
        new = dict(r)
        if self.name in FakeDb.AUTO:
            self.db.seq += 1
            new.setdefault('id', self.db.seq)
            new.setdefault('created_at', datetime.now(timezone.utc).isoformat())
        return new

    def execute(self):
        db = self.db
        hook = db.before.pop((self.name, self.op), None)
        if hook:
            hook(db)
        db.log.append({'table': self.name, 'op': self.op, 'rows': self.payload, 'kw': self.kw, 'cols': self.cols,
                       'filters': list(self.filters), 'orders': list(self.orders), 'limit': self.lim, 'range': self.rng})
        if self.name in db.fail or (self.name, self.op) in db.fail or (db.fail_when and db.fail_when(self)):
            raise RuntimeError(f'{self.name} {self.op} down')
        if db.flaky.get((self.name, self.op)):
            db.flaky[(self.name, self.op)] -= 1
            raise RuntimeError(f'{self.name} {self.op} 일시 오류')
        rows = db.tables.setdefault(self.name, [])
        if self.op == 'insert':
            out = [self._new(r) for r in self.payload]
            rows.extend(out)
            return mock.Mock(data=[dict(r) for r in out])
        if self.op == 'upsert':
            pk = FakeDb.PK[self.name]
            out = []
            for r in self.payload:
                cur = next((x for x in rows if all(x.get(k) == r.get(k) for k in pk)), None)
                if cur is None:
                    new = self._new(r)
                    rows.append(new)
                    out.append(dict(new))
                elif not self.kw.get('ignore_duplicates'):
                    cur.update(r)
                    out.append(dict(cur))
            return mock.Mock(data=out)
        if self.op == 'update':
            hit = [r for r in rows if self._ok(r)]
            for r in hit:
                r.update(self.payload)
            return mock.Mock(data=[dict(r) for r in hit])
        if self.op == 'delete':
            gone = [r for r in rows if self._ok(r)]
            db.tables[self.name] = [r for r in rows if not self._ok(r)]
            return mock.Mock(data=gone)
        got = [dict(r) for r in rows if self._ok(r)]
        for c, desc in reversed(self.orders):
            got.sort(key=lambda r: _tkey(r.get(c)), reverse=desc)
        if self.rng:
            got = got[self.rng[0]:self.rng[1] + 1]
        if self.lim is not None:
            got = got[:self.lim]
        return mock.Mock(data=got[:FakeDb.MAX_ROWS])        # PostgREST 요청당 상한


class FakeGroup:
    """news_dedup.group_same_event 가짜 — events {제목: 사건 열쇠}가 같은 제목끼리 묶는다(처음 나온 순서).
    진짜처럼 2건 미만이면 None, fail=True면 None(실패). 호출(제목 목록)을 calls에, 넘어온 키워드 인자를 kws에 남긴다
    (공통 경로는 인자 없이 = 종전과 같은 호출, 팀 경로는 timeout·max_retries)."""

    def __init__(self, events=None, fail=False):
        self.events = dict(events or {})
        self.fail = fail
        self.calls = []
        self.kws = []

    def __call__(self, titles, api_key, model=None, **kw):
        self.calls.append(list(titles))
        self.kws.append(dict(kw))
        if self.fail or len(titles) < 2 or not api_key:
            return None
        order, groups = [], {}
        for i, t in enumerate(titles):
            k = self.events.get(t, ('solo', i))
            if k not in groups:
                groups[k] = []
                order.append(k)
            groups[k].append(i)
        return [groups[k] for k in order]


class FakeMatch:
    """news_dedup.match_prior_reports 가짜(#263) — 새 기사마다, events {제목: 사건 열쇠}가 같은 「이미 알린 기사」 가운데 첫
    기사의 번호(없으면 None). 진짜처럼 키가 없거나 목록이 비면 None, fail=True면 None(실패). 호출(새 제목들, 기보도 제목들)을
    calls에, 넘어온 키워드 인자를 kws에 남긴다."""

    def __init__(self, events=None, fail=False):
        self.events = dict(events or {})
        self.fail = fail
        self.calls = []
        self.kws = []

    def __call__(self, new_items, prior_items, api_key, model=None, **kw):
        self.calls.append(([n.get('title') for n in new_items], [p.get('title') for p in prior_items]))
        self.kws.append(dict(kw))
        if self.fail or not api_key or not new_items or not prior_items:
            return None
        out = []
        for n in new_items:
            k = self.events.get(n.get('title'))
            out.append(next((j for j, p in enumerate(prior_items)
                             if k is not None and self.events.get(p.get('title')) == k), None))
        return out


def _ts(hours_ago: float) -> str:
    """KST ISO 시각(크롤러의 cutoff와 같은 꼴)."""
    return (datetime.now(KST) - timedelta(hours=hours_ago)).isoformat()


def _nf(nid, title, hours_ago, urgency='긴급', origin=None, pub=None, source='매체', tags=None):
    """news_feed 행."""
    return {'id': 'id-' + nid, 'url': 'https://n/' + nid, 'title': title, 'created_at': _ts(hours_ago),
            'urgency': urgency, 'origin': origin, 'source': source, 'tags': list(tags or ['market']),
            'published_at': _ts(hours_ago if pub is None else pub)}


def _item(nid, title, urgency='긴급', pub=1, source='매체', tags=None):
    """이번 실행 수집 기사(save_new_items가 돌려준 모양)."""
    return {'title': title, 'url': 'https://n/' + nid, 'source': source, 'tags': list(tags or ['market']),
            'urgency': urgency, 'published_at': _ts(pub)}


def _norm_filters(filters):
    """조회 조건 대조용 — gte 시각은 '지금부터 몇 시간 전'(반올림)으로 바꾼다(두 번 돌린 사이 마이크로초 차이 무시)."""
    out = []
    for f in filters:
        if f[0] == 'gte' and isinstance(f[2], str):
            try:
                dt = datetime.fromisoformat(f[2].replace('Z', '+00:00'))
                f = ('gte', f[1], round((datetime.now(timezone.utc) - dt).total_seconds() / 3600))
            except ValueError:
                pass
        out.append(f)
    return out


def _quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = fn(*a, **k)
    return out, buf.getvalue()


# ── 공통 억제 시나리오(키워드·의미판정·리마인드·사슬·실행내 묶음·의미 재묶기) ──────────────────────────
P1 = _nf('p1', '통신사 해킹 과징금 부과 결정', 2)
P2 = _nf('p2', '주파수 경매 일정 연기 발표', 30)
P3 = _nf('p3', '위성 통신 신규 사업자 선정', 5)
P4 = _nf('p4', '통신사 해킹 과징금 부과 결정 옛 보도', 1, origin='issuemap')        # 이슈맵 옛 기사 — 비교군 밖(#236)
P5 = _nf('p5', '해지 위약금 면제 방안 검토 착수', 3)
PQ = _nf('pq', '해지 위약금 면제 방안 검토', 50)
P6 = _nf('p6', '요금 인하 논의 시작', 4, urgency='보통')
N_ITEMS = [
    _item('n1', '통신사 해킹 과징금 부과 결정 후속 보도'),         # P1(2시간)과 키워드 5 → 억제
    _item('n2', '주파수 경매 일정 연기 발표 이후 업계 반응'),       # P2(30시간) → 리마인드 2일째
    _item('n3', '위성통신 새 사업자 뽑았다'),                       # 키워드 1 공유 → 의미판정으로 P3와 같은 사건 → 억제
    _item('n4', 'AI 기본법 시행령 초안 공개'),
    _item('n6', 'AI 기본법 시행령 초안 공개 반응'),                 # n4와 실행내 묶음(키워드)
    _item('n7', '알뜰폰 요금제 전면 개편'),
    _item('n8', '중소 통신사 가격 체계 손질'),                      # n7과 의미 재묶기
    _item('n5', '해지 위약금 면제 방안 검토 착수 소식'),            # P5 → 사슬 → PQ(50시간) → 리마인드 3일째
    _item('n9', '통신사 해킹 과징금 부과 결정 소송 제기'),          # 국면 신호(소송) → 통과
]
EVENTS = {'위성통신 새 사업자 뽑았다': 'sat', P3['title']: 'sat',
          '알뜰폰 요금제 전면 개편': 'mvno', '중소 통신사 가격 체계 손질': 'mvno'}


def _common_tables(chain_extra=()):
    news = [P1, P2, P3, P4, P5, PQ, P6] + [dict(_nf(i['url'].rsplit('/', 1)[1], i['title'], 0.01))
                                           for i in N_ITEMS]          # 방금 저장된 이번 실행분(자기 자신 — 빼야 함)
    chain = [{'id': 1, 'article_title': P5['title'], 'matched_title': PQ['title'], 'shared_keywords': '해지,위약금,면제',
              'created_at': _ts(3)},
             {'id': 2, 'article_title': P1['title'], 'matched_title': '다른 옛 기사', 'shared_keywords': '[리마인드] 2일째',
              'created_at': _ts(2)}] + list(chain_extra)
    return {'news_feed': news, 'alert_suppress_log': chain}


class TestCommonPathEquivalence(unittest.TestCase):
    """공통 포장(새) ≡ 나누기 전 본문(기준본) — 같은 가짜 DB·같은 가짜 사건 묶기로 두 번 돌려 전부 대조."""

    def _run(self, fn, tables, items, key, events, fail=(), group_fail=False):
        db = FakeDb(tables, fail=fail)
        grp = FakeGroup(events, fail=group_fail)
        mat = FakeMatch(events, fail=group_fail)
        its = copy.deepcopy(items)
        with mock.patch.object(_THIS, 'sb', db), mock.patch.object(_THIS, 'ANTHROPIC_API_KEY', key), \
                mock.patch.object(crawler, 'sb', db), mock.patch.object(crawler, 'ANTHROPIC_API_KEY', key), \
                mock.patch.object(news_dedup, 'group_same_event', grp), \
                mock.patch.object(news_dedup, 'match_prior_reports', mat), \
                mock.patch.dict(crawler._GROUP_MEMO, {}, clear=True), \
                mock.patch.dict(crawler._MATCH_MEMO, {}, clear=True), \
                mock.patch.object(crawler, '_COMMON_ALERT', None):
            reps, out = _quiet(fn, its)
            common = crawler._COMMON_ALERT
        return {'reps': copy.deepcopy(reps), 'rep_idx': [next(k for k, i in enumerate(its) if i is r) for r in reps],
                'items': its, 'out': out, 'db': db, 'grp': grp.calls, 'grp_kw': grp.kws, 'match': mat.calls,
                'match_kw': mat.kws, 'common': common}

    def assert_same(self, tables, items=N_ITEMS, key='k', events=EVENTS, fail=(), group_fail=False):
        ref = self._run(_ref_suppress_repeat_alerts, tables, items, key, events, fail, group_fail)
        new = self._run(crawler.suppress_repeat_alerts, tables, items, key, events, fail, group_fail)
        self.assertEqual(new['reps'], ref['reps'], '반환(대표·_related·_remind)')
        self.assertEqual(new['rep_idx'], ref['rep_idx'], '대표는 입력 dict 그 자체(같은 객체·같은 순서)')
        self.assertEqual(new['items'], ref['items'], '입력 dict 제자리 표시(_remind·_related)')
        self.assertEqual(new['out'], ref['out'], '로그 줄')
        # 사건 묶기(group_same_event) — 기준본은 ①-2와 2차 두 번, 새 코드는 2차만(①-2는 재보도 대조로 옮김, #263).
        # 2차 묶기의 입력(대표 제목 목록)은 그대로여야 한다.
        n_new = len(new['grp'])
        self.assertIn(len(ref['grp']) - n_new, (0, 1), '줄어든 호출은 ①-2 하나뿐')
        self.assertEqual(new['grp'], ref['grp'][len(ref['grp']) - n_new:], '2차 묶기 호출(제목 목록)')
        self.assertLessEqual(len(new['match']), 1, '재보도 대조는 실행당 많아야 한 번')
        self.assertTrue(all(k == {} for k in new['grp_kw']), '공통 경로 사건 묶기는 인자 없이(제한은 팀 경로만)')
        self.assertTrue(all(k == {} for k in new['match_kw']), '공통 경로 재보도 대조도 인자 없이')
        # 리마인드 문턱(#256, 2026-09-29)의 3일 창 전체 조회(칸 title,url,urgency,created_at)는 나누기 전에 없던 조회 —
        # 기보도(긴급) 조회는 그대로이고, 새 조회는 모양만 따로 확인한다(조건은 기보도 조회와 같고 등급 조건만 없다).
        _SHARE_COLS = 'title,url,urgency,created_at'
        _PRIOR_COLS = 'title,url,created_at,event,screen_text'          # 재보도 대조가 읽는 요지·요약 두 칸이 더해졌다(#263)
        for t in ('news_feed',):
            self.assertEqual([(e['op'], 'title,url,created_at' if e['cols'] == _PRIOR_COLS else e['cols'],
                               _norm_filters(e['filters']), e['orders'], e['limit'], e['range'])
                              for e in new['db'].calls(t) if e['cols'] != _SHARE_COLS],
                             [(e['op'], e['cols'], _norm_filters(e['filters']), e['orders'], e['limit'], e['range'])
                              for e in ref['db'].calls(t)], '기보도 조회 그대로(칸 둘만 더함)')
            self.assertTrue(all(e['cols'] in (_PRIOR_COLS, _SHARE_COLS) for e in new['db'].calls(t)))
            share_q = [e for e in new['db'].calls(t) if e['cols'] == _SHARE_COLS]
            prior_q = [e for e in ref['db'].calls(t)]
            if prior_q and ('news_feed', 'select') not in set(fail):   # 기보도 조회가 된 실행이면 3일 창 전체 조회도 한 번(#256)
                self.assertEqual(len(share_q), 1, '3일 창 전체 조회 1번')
                self.assertEqual(share_q[0]['orders'], [('created_at', True), ('id', True)])
                self.assertEqual(share_q[0]['range'], (0, 999))
                self.assertEqual({k: v for k, v in _norm_filters(share_q[0]['filters']).items() if k != 'urgency'}
                                 if isinstance(_norm_filters(share_q[0]['filters']), dict) else _norm_filters(share_q[0]['filters']),
                                 {k: v for k, v in _norm_filters(prior_q[0]['filters']).items() if k != 'urgency'}
                                 if isinstance(_norm_filters(prior_q[0]['filters']), dict) else
                                 [f for f in _norm_filters(prior_q[0]['filters']) if 'urgency' not in str(f)],
                                 '조건은 기보도 조회에서 등급만 뺀 것')
            else:
                self.assertEqual(share_q, [])
        self.assertEqual([e['rows'] for e in new['db'].calls('alert_suppress_log', 'insert')],
                         [e['rows'] for e in ref['db'].calls('alert_suppress_log', 'insert')], 'alert_suppress_log 행')
        rs = ref['db'].calls('alert_suppress_log', 'select')
        ns = new['db'].calls('alert_suppress_log', 'select')
        if rs:           # 사슬 조회 — 칸·조건은 같고 정렬에 id·페이지(range)만 더했다
            self.assertEqual([(e['cols'], _norm_filters(e['filters'])) for e in ns[:1]],
                             [(e['cols'], _norm_filters(e['filters'])) for e in rs])
            self.assertEqual(rs[0]['orders'], [('created_at', False)])
            self.assertEqual(ns[0]['orders'], [('created_at', False), ('id', False)])
            self.assertEqual(ns[0]['range'], (0, 999))
        self.assertEqual({e['table'] for e in new['db'].log}, {e['table'] for e in ref['db'].log}, '다른 표 무접촉')
        return ref, new

    def test_full_scenario(self):
        ref, new = self.assert_same(_common_tables())
        # 시나리오가 실제로 모든 갈래를 지났는지(기준본 쪽으로 확인)
        rows = {r['article_title']: r['shared_keywords'] for e in ref['db'].calls('alert_suppress_log', 'insert')
                for r in e['rows']}
        self.assertFalse(rows['통신사 해킹 과징금 부과 결정 후속 보도'].startswith('['), '키워드 억제')
        self.assertTrue(rows['위성통신 새 사업자 뽑았다'].startswith('[의미판정]'))
        self.assertEqual(rows['AI 기본법 시행령 초안 공개 반응'], '[실행내묶음]')
        self.assertEqual(rows['중소 통신사 가격 체계 손질'], '[실행내묶음]', '의미 재묶기')
        self.assertEqual(rows['주파수 경매 일정 연기 발표 이후 업계 반응'], '[리마인드] 2일째')
        self.assertEqual(rows['해지 위약금 면제 방안 검토 착수 소식'], '[리마인드] 3일째', '사슬을 따라 대표 나이')
        self.assertEqual([r['title'] for r in ref['reps']],
                         ['주파수 경매 일정 연기 발표 이후 업계 반응', 'AI 기본법 시행령 초안 공개', '알뜰폰 요금제 전면 개편',
                          '해지 위약금 면제 방안 검토 착수 소식', '통신사 해킹 과징금 부과 결정 소송 제기'])
        self.assertEqual(len(ref['grp']), 2, '의미 판정 두 단계 모두 불림')
        self.assertEqual((len(new['grp']), len(new['match'])), (1, 1), '새 코드: 2차 묶기 1번 + 재보도 대조 1번(#263)')
        new_titles, old_titles = new['match'][0]
        self.assertIn('위성통신 새 사업자 뽑았다', new_titles)
        self.assertNotIn('통신사 해킹 과징금 부과 결정 후속 보도', new_titles, '①에서 억제된 기사는 대조에 안 올린다')
        self.assertIn(P3['title'], old_titles)
        self.assertIn(P1['title'], old_titles, '리마인드로 나간 기사는 알림 대표다')
        self.assertNotIn(P5['title'], old_titles, '억제된 기사(사슬에 있는 제목)는 견줄 대상이 아니다')
        self.assertNotIn(P4['title'], old_titles)
        # 공통 포장 결과가 복사용으로 남는다
        c = new['common']
        self.assertEqual(c['urls'], [i['url'] for i in N_ITEMS])
        self.assertEqual([r['title'] for r in c['reps']], [r['title'] for r in ref['reps']])
        self.assertFalse(c['fail_open'])
        self.assertEqual(c['sup_rows'] + c['remind_rows'],
                         [r for e in new['db'].calls('alert_suppress_log', 'insert') for r in e['rows']])

    def test_no_api_key(self):
        _, new = self.assert_same(_common_tables(), key='')
        self.assertEqual(new['grp'], [])

    def test_group_failure(self):
        _, new = self.assert_same(_common_tables(), group_fail=True)
        self.assertEqual((len(new['grp']), len(new['match'])), (1, 1), '둘 다 불리고 둘 다 실패 → 원본 유지')

    def test_prior_query_failure_fail_open(self):
        ref, new = self.assert_same(_common_tables(), fail={('news_feed', 'select')})
        self.assertEqual(len(new['reps']), len(N_ITEMS))
        self.assertIn('판정 오류 → 전부 알림(fail-open)', new['out'])
        self.assertTrue(new['common']['fail_open'])
        self.assertEqual(len(new['common']['reps']), len(N_ITEMS))

    def test_chain_query_failure(self):
        """억제 사슬을 못 읽은 실행(#263): 리마인드는 종전대로(걸린 기사 자신의 나이), 재보도 대조(①-2)는 건너뛴다 — 어느 기사가
        알림으로 나갔는지 모르는 채로 AI 억제를 하지 않는다. 그래서 기준본(①-2가 묶기 분류기로 돌던 때)과는 '위성통신' 기사
        한 건이 다르다(억제 → 통과)."""
        fail = {('alert_suppress_log', 'select')}
        ref = self._run(_ref_suppress_repeat_alerts, _common_tables(), N_ITEMS, 'k', EVENTS, fail)
        new = self._run(crawler.suppress_repeat_alerts, _common_tables(), N_ITEMS, 'k', EVENTS, fail)
        self.assertIn('억제 사슬 조회 실패', new['out'])
        self.assertIn('재보도 대조(AI)는 건너뜀', new['out'])
        self.assertEqual(new['match'], [], '대조 호출 0')
        sat = '위성통신 새 사업자 뽑았다'
        ref_titles, new_titles = [r['title'] for r in ref['reps']], [r['title'] for r in new['reps']]
        self.assertNotIn(sat, ref_titles)
        self.assertIn(sat, new_titles, '대조를 건너뛰면 알림이 나가는 쪽')
        self.assertEqual([t for t in new_titles if t != sat], ref_titles, '나머지 대표는 그대로')

        def rows(r):
            return [x for e in r['db'].calls('alert_suppress_log', 'insert') for x in e['rows']]
        self.assertEqual(rows(new), [x for x in rows(ref) if x['article_title'] != sat], '다른 기록 행은 그대로')

    def test_log_insert_failure(self):
        _, new = self.assert_same(_common_tables(), fail={('alert_suppress_log', 'insert')})
        self.assertIn('로그 저장 실패(무시)', new['out'])

    def test_no_prior_single_item_and_empty(self):
        self.assert_same({'news_feed': [], 'alert_suppress_log': []}, items=N_ITEMS[:1])
        ref, new = self.assert_same(_common_tables(), items=[])
        self.assertEqual(new['common'], {'urls': [], 'reps': [], 'sup_rows': [], 'remind_rows': [], 'fail_open': False})
        self.assertEqual(new['db'].log, [])

    def test_origin_guard_source(self):
        """test_smoke 가드(#236) — 공통 포장 소스에 origin null 조건이 그대로 있다."""
        import inspect
        self.assertIn(".is_('origin', 'null')", inspect.getsource(crawler.suppress_repeat_alerts))


class TestChainPaging(unittest.TestCase):
    """억제 사슬 조회(alert_suppress_log 10일)는 order(created_at, id) + range로 끝까지 — 종전(오름차순 1,000행 한 번)은
    **오래된 1,000행만** 남아 최근 사슬이 빠졌다. 행동 차이는 1,000행을 넘을 때만."""

    def test_newest_link_survives_past_1000_rows(self):
        old = [{'id': 10 + k, 'article_title': f'옛 억제 기사 {k}', 'matched_title': f'옛 기사 {k}',
                'shared_keywords': 'a,b,c', 'created_at': _ts(24 * 9)} for k in range(1000)]
        tables = _common_tables()
        tables['alert_suppress_log'] = old + [dict(tables['alert_suppress_log'][0], id=5000)]   # P5 → PQ 사슬이 가장 새것
        items = [_item('n5', '해지 위약금 면제 방안 검토 착수 소식')]
        eq = TestCommonPathEquivalence()
        ref = eq._run(_ref_suppress_repeat_alerts, tables, items, 'k', EVENTS)
        new = eq._run(crawler.suppress_repeat_alerts, tables, items, 'k', EVENTS)
        self.assertEqual(ref['reps'], [], '종전: 1,000행에서 잘려 사슬이 빠짐 → P5(3시간)에 걸려 억제')
        self.assertEqual([r.get('_remind') for r in new['reps']], ['3일째'], '페이지로 끝까지 → 사슬 → 리마인드')
        self.assertEqual([e['range'] for e in new['db'].calls('alert_suppress_log', 'select')], [(0, 999), (1000, 1999)])


class TestGroupMemo(unittest.TestCase):

    def test_same_titles_reuse_result_zero_calls(self):
        grp = FakeGroup({'가': 1, '나': 1})
        with mock.patch.object(news_dedup, 'group_same_event', grp), mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'), \
                mock.patch.dict(crawler._GROUP_MEMO, {}, clear=True):
            a = crawler._group_same_event_memo(['가', '나', '다'])
            a[0].append(99)                                   # 돌려준 값을 고쳐도 메모는 그대로
            b = crawler._group_same_event_memo(('가', '나', '다'))
            c = crawler._group_same_event_memo(['다', '가'])
        self.assertEqual(b, [[0, 1], [2]])
        self.assertEqual(c, [[0], [1]])
        self.assertEqual(len(grp.calls), 2, '같은 제목 목록은 호출 0')

    def test_failure_is_memoized_too(self):
        grp = FakeGroup(fail=True)
        with mock.patch.object(news_dedup, 'group_same_event', grp), mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'), \
                mock.patch.dict(crawler._GROUP_MEMO, {}, clear=True):
            self.assertIsNone(crawler._group_same_event_memo(['가', '나']))
            self.assertIsNone(crawler._group_same_event_memo(['가', '나']))
        self.assertEqual(len(grp.calls), 1)


# ── 받는 단위·알림 등급 ─────────────────────────────────────────────────────────────────────────
TEAMS = [{'id': 4, 'division': '정책개발실', 'name': 'Comm전략팀', 'sort_order': 5},
         {'id': 1, 'division': '사업협력실', 'name': '경쟁제도팀', 'sort_order': 10},
         {'id': 2, 'division': '사업협력실', 'name': '기술정책팀', 'sort_order': 20},
         {'id': 3, 'division': '사업협력실', 'name': 'AI정책팀', 'sort_order': 30}]
RULES = {'t2_up': {'id': 't2_up', 'team_id': 2, 'position': 10, 'mode': 'min', 'level': '긴급', 'any_words': ['위성'],
                   'enabled': True},
         't3_down': {'id': 't3_down', 'team_id': 3, 'position': 10, 'mode': 'set', 'level': '참고',
                     'any_words': ['야구'], 'enabled': True}}


def _sub(team_id=None, division=None, level='urgent'):
    return {'chat_id': 1, 'active': True, 'topic_urgent': True, 'team_id': team_id, 'division': division,
            'news_level': level}


class TestUnitsAndLevels(unittest.TestCase):

    def test_units(self):
        subs = [_sub(), _sub(level='urgent'), _sub(2), _sub(2, level='normal'), _sub(3), _sub(division='사업협력실'),
                _sub(division='없는실', level='normal')]
        u = crawler._alert_units(subs, TEAMS)
        self.assertNotIn('c', u, '공통·중요만 → 기존 경로(단위 없음)')
        self.assertEqual(u['t:2'], {'kind': 't', 'team_ids': [2], 'channels': ['긴급', '보통']})
        self.assertEqual(u['t:3'], {'kind': 't', 'team_ids': [3], 'channels': ['긴급']})
        self.assertEqual(u['d:사업협력실'], {'kind': 'd', 'team_ids': [1, 2, 3], 'channels': ['긴급']}, '팀 순서 = teams 순서')
        self.assertEqual(u['d:없는실']['team_ids'], [])
        u2 = crawler._alert_units([_sub(level='normal'), _sub()], [])
        self.assertEqual(u2, {'c': {'kind': 'c', 'team_ids': [], 'channels': ['보통']}})
        self.assertEqual(crawler._alert_units([], TEAMS), {})

    def test_levels_alert_vs_view(self):
        t1 = {'kind': 't', 'team_ids': [1], 'channels': ['긴급']}
        up = {1: {'team_id': 1, 'urgency': '긴급', 'source': 'human', 'rule_id': None}}
        down = {1: {'team_id': 1, 'urgency': '참고', 'source': 'human', 'rule_id': None}}
        self.assertEqual(crawler._unit_level(t1, '보통', up, RULES, alert=True), ('보통', [1]), '팀원이 올린 것은 알림 안 함')
        self.assertEqual(crawler._unit_level(t1, '보통', up, RULES, alert=False), ('긴급', [1]), '비교군은 지금 보는 등급')
        self.assertEqual(crawler._unit_level(t1, '긴급', down, RULES, alert=True), ('참고', [1]), '내린 것은 막음')
        d = {'kind': 'd', 'team_ids': [1, 2, 3], 'channels': ['긴급']}
        rows = {2: {'team_id': 2, 'urgency': '긴급', 'source': 'rule', 'rule_id': 't2_up'},
                3: {'team_id': 3, 'urgency': '긴급', 'source': 'ai', 'rule_id': None}}
        self.assertEqual(crawler._unit_level(d, '보통', rows, RULES), ('긴급', [2, 3]))
        c = {'kind': 'c', 'team_ids': [], 'channels': ['보통']}
        self.assertEqual(crawler._unit_level(c, '보통', rows, RULES), ('보통', []))

    def test_labels(self):
        names = {t['id']: t['name'] for t in TEAMS}
        t = {'kind': 't', 'team_ids': [2]}
        d = {'kind': 'd', 'team_ids': [1, 2, 3]}
        self.assertEqual(crawler._alert_label(t, '긴급', '보통', [2], names), '우리 팀 기준')
        self.assertEqual(crawler._alert_label(t, '긴급', '긴급', [2], names), '', '공통과 같으면 표시 없음')
        self.assertEqual(crawler._alert_label(d, '긴급', '참고', [2, 3], names), '기술정책팀·AI정책팀')
        self.assertEqual(crawler._alert_label(d, '긴급', '참고', [9], names), '팀 9')
        self.assertEqual(crawler._alert_label({'kind': 'c'}, '보통', '참고', [], names), '')

    def test_log_rows_mapping(self):
        reps = [{'title': 'A', 'url': 'ua'}, {'title': 'B', 'url': 'ub', '_remind': '2일째'},
                {'title': 'C', 'url': 'uc', '_remind': '이어지는 사건'}, {'title': 'Z', 'url': 'uz'}]
        sup = [{'article_title': 'D', 'article_url': 'ud', 'matched_title': 'P', 'shared_keywords': 'x,y,z'},
               {'article_title': 'E', 'article_url': 'ue', 'matched_title': 'Q', 'shared_keywords': '[의미판정] x'},
               {'article_title': 'F', 'article_url': 'uf', 'matched_title': 'A', 'shared_keywords': '[실행내묶음]'},
               {'article_title': 'G', 'article_url': 'ug', 'matched_title': 'C', 'shared_keywords': '[실행내묶음]'}]
        rem = [{'article_title': 'B', 'article_url': 'ub', 'matched_title': 'OLD', 'shared_keywords': '[리마인드] 2일째'},
               {'article_title': 'G', 'article_url': 'ug', 'matched_title': 'OLD2', 'shared_keywords': '[리마인드] 이어지는 사건'}]
        nid = {u: 'id-' + u for u in ('ua', 'ub', 'uc', 'ud', 'ue', 'uf', 'ug')}       # uz = news_id 모름 → 뺀다
        rows, out = crawler._alert_log_rows('t:2', '긴급', reps, sup, rem, nid)
        self.assertEqual(len({frozenset(r) for r in rows}), 1, '키 집합 동일')
        got = {r['article_title']: (r['outcome'], r['matched_title'], r['shared_keywords']) for r in rows}
        self.assertEqual(got, {'A': ('sent', None, None), 'B': ('remind', 'OLD', '[리마인드] 2일째'),
                               # 묶음 안 리마인드를 이어받은 대표인데 제 URL의 리마인드 행이 없을 때의 폴백(#263-보론부터
                               # 핵심 함수는 그 행을 대표로 옮겨 주므로 실제 흐름에서는 B 꼴이 된다 — test_dedup_match 참조)
                               'C': ('remind', None, '[리마인드] 이어지는 사건'),
                               'D': ('suppressed', 'P', 'x,y,z'), 'E': ('suppressed', 'Q', '[의미판정] x'),
                               'F': ('merged', 'A', '[실행내묶음]'), 'G': ('merged', 'C', '[실행내묶음]')})
        self.assertEqual([n for n, _ in out], ['id-ua', 'id-ub', 'id-uc'])
        self.assertTrue(all(r['audience'] == 't:2' and r['channel'] == '긴급' for r in rows))


# ── run_audience_alerts('collect') ───────────────────────────────────────────────────────────────
class _AudBase(unittest.TestCase):
    RULES = RULES

    def setUp(self):
        self.grp = FakeGroup(EVENTS)
        self.match = FakeMatch(EVENTS)
        self.trig = []
        patches = [mock.patch.object(crawler, 'ANTHROPIC_API_KEY', 'k'),
                   mock.patch.object(news_dedup, 'group_same_event', self.grp),
                   mock.patch.object(news_dedup, 'match_prior_reports', self.match),
                   mock.patch.dict(crawler._GROUP_MEMO, {}, clear=True),
                   mock.patch.dict(crawler._MATCH_MEMO, {}, clear=True),
                   mock.patch.dict(crawler._INSERTED_IDS, {}, clear=True),
                   mock.patch.dict(crawler._LATE_ALERT_PAIRS, {}, clear=True),
                   mock.patch.dict(crawler._AUD_CTX, {}, clear=True),
                   mock.patch.dict(crawler._AUD_STATS, {'units': 0, '긴급': 0, '보통': 0, '오류': 0, 'ai': 0}, clear=True),
                   mock.patch.object(crawler, '_COMMON_ALERT', None),
                   mock.patch.object(crawler, '_URGENCY_RULES', []),          # 규칙은 이미 읽은 것으로(조회 0번)
                   mock.patch.object(crawler, '_TEAM_URGENCY_RULES', {}),
                   mock.patch.object(crawler, '_TEAM_RULES_ENABLED', dict(self.RULES)),
                   mock.patch.object(crawler, 'SENTENCE_DB_RETRY_DELAY_S', 0),
                   mock.patch.object(subscriber_notify, '_trigger_delivery', lambda: self.trig.append(1) or True)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def collect(self, new_items, subs, prior=(), team_rows=(), alert_log=(), inserted=None, extra=None):
        """공통 억제(suppress_repeat_alerts) → run_audience_alerts('collect') — main과 같은 순서. inserted = 새로 저장된
        url(None = 전부). 반환 (긴급 행 수, db, 공통 대표, 팀 단계 출력)."""
        news = [dict(p) for p in prior]
        for k, it in enumerate(new_items):
            nid = it['url'].rsplit('/', 1)[-1] or f'nourl{k}'
            news.append(dict(it, id='id-' + nid, created_at=_ts(0.01), origin=it.get('origin')))
            if inserted is None or it['url'] in inserted:
                crawler._INSERTED_IDS[it['url']] = 'id-' + nid
        tables = {'news_feed': news, 'telegram_subscribers': list(subs), 'teams': TEAMS, 'team_urgency': list(team_rows),
                  'subscriber_alert_log': list(alert_log), 'alert_suppress_log': [], 'subscriber_queue': []}
        tables.update(extra or {})
        self.db = FakeDb(tables)
        with mock.patch.object(crawler, 'sb', self.db):
            cut = datetime.now(KST) - timedelta(hours=24)
            urgent = [i for i in new_items if i.get('urgency') == '긴급' and crawler.is_within_24h(i, cut)]
            reps, _ = _quiet(crawler.suppress_repeat_alerts, urgent)
            self.n_common_calls = len(self.db.log)
            self.n_grp_common = len(self.grp.calls)
            self.n_match_common = len(self.match.calls)
            n, out = _quiet(crawler.run_audience_alerts, 'collect', new_items=new_items, cutoff_24h=cut)
        return n, reps, out

    def team_log(self):
        return self.db.log[self.n_common_calls:]

    def queue(self, audience=None, level=None):
        return [r for r in self.db.tables.get('subscriber_queue', [])
                if (audience is None or r['audience'] == audience) and (level is None or r['level'] == level)]

    def alog(self, audience=None, channel=None):
        return [r for r in self.db.tables.get('subscriber_alert_log', [])
                if (audience is None or r['audience'] == audience) and (channel is None or r['channel'] == channel)]

    def assert_uniform(self):
        """큐 insert 행은 모두 같은 키(topic 'news'·audience·level·news_url·tags·html), 기록 upsert 행도 키 집합 하나."""
        keys = frozenset(['topic', 'audience', 'level', 'news_url', 'tags', 'html'])
        for e in self.db.calls('subscriber_queue', 'insert'):
            self.assertEqual({frozenset(r) for r in e['rows']}, {keys})
            self.assertTrue(all(r['topic'] == 'news' and r['news_url'] for r in e['rows']))
        for e in self.db.calls('subscriber_alert_log', 'upsert'):
            self.assertEqual(len({frozenset(r) for r in e['rows']}), 1)
            self.assertEqual(e['kw'], {'on_conflict': 'audience,channel,news_id', 'ignore_duplicates': True})


class TestCollect(_AudBase):

    def test_no_candidates_zero_queries(self):
        items = [_item('x1', '기지국 소식', urgency='긴급')]
        n, _, out = self.collect(items, [_sub(2)], inserted=set())          # 동시 실행이 먼저 넣음 → 후보 아님
        self.assertEqual((n, out, self.team_log()), (0, '', []))

    def test_no_units_one_query(self):
        items = [_item('x1', '기지국 소식', urgency='긴급')]
        n, _, out = self.collect(items, [_sub(), _sub()])                    # 공통·중요만 = 기존 경로뿐
        self.assertEqual((n, out), (0, ''))
        self.assertEqual([(e['table'], e['op']) for e in self.team_log()], [('telegram_subscribers', 'select')])
        self.assertEqual(self.team_log()[0]['filters'], [('eq', 'active', True), ('eq', 'topic_urgent', True)])
        self.assertEqual(crawler.audience_note(), '', '단위가 없으면 heartbeat 메모 꼬리 없음(종전 그대로)')

    def test_copy_when_levels_equal_common(self):
        """팀 행이 등급을 바꾼 기사가 없으면 공통 결과를 복사 — AI 호출 0, 로그 행은 그 단위 이름으로, 큐 html은 공통과 같다."""
        items = [dict(i) for i in N_ITEMS] + [_item('b1', '보통 기사 하나', urgency='보통')]
        n, reps, out = self.collect(items, [_sub(1), _sub(division='사업협력실')], prior=[P1, P2, P3, P4, P5, PQ, P6],
                                    extra={'alert_suppress_log': _common_tables()['alert_suppress_log']})
        self.assertIn('[팀 알림] t:1 긴급 후보 9 → 보냄 5(리마인드 2)·억제 2·묶음 2 (복사) · AI 0회', out)
        self.assertIn('[팀 알림] d:사업협력실 긴급 후보 9 → 보냄 5(리마인드 2)·억제 2·묶음 2 (복사) · AI 0회', out)
        self.assertIn('[팀 알림] 합계(collect·긴급) — 큐 긴급 10건 · AI 0회', out)
        self.assertEqual(len(self.grp.calls), self.n_grp_common, '복사 = 사건 묶기 호출 0')
        self.assertEqual(len(self.match.calls), self.n_match_common, '복사 = 재보도 대조 호출 0')
        self.assertEqual(n, 10)
        common_html = [subscriber_notify.format_news_item(r) for r in reps]
        self.assertEqual([r['html'] for r in self.queue('t:1', '긴급')], common_html, '표시 없음 — 공통과 같은 html')
        self.assertEqual([r['html'] for r in self.queue('d:사업협력실', '긴급')], common_html)
        got = {r['article_title']: r['outcome'] for r in self.alog('t:1', '긴급')}
        self.assertEqual(got['통신사 해킹 과징금 부과 결정 후속 보도'], 'suppressed')
        self.assertEqual(got['위성통신 새 사업자 뽑았다'], 'suppressed')
        self.assertEqual(got['AI 기본법 시행령 초안 공개 반응'], 'merged')
        self.assertEqual(got['주파수 경매 일정 연기 발표 이후 업계 반응'], 'remind')
        self.assertEqual(got['AI 기본법 시행령 초안 공개'], 'sent')
        self.assertNotIn('보통 기사 하나', got)
        self.assertEqual(len(self.db.calls('alert_suppress_log', 'insert')), 1, 'alert_suppress_log 쓰기는 공통 포장 한 번뿐')
        self.assertFalse([e for e in self.team_log() if e['table'] == 'alert_suppress_log'], '팀 단계는 alert_suppress_log 무접촉')
        self.assertEqual(self.trig, [], '즉시 배달 호출은 main 몫')
        self.assertEqual(crawler.audience_note(), ' team=긴급10/보통0/오류0')
        self.assert_uniform()

    def test_team_rule_raises_compute_with_label_short_limit_ai_count(self):
        items = [_item('s1', '위성 주파수 공급 계획 확정', urgency='보통'), _item('c1', '기지국 전력 절감', urgency='긴급')]
        rows = [{'news_id': 'id-s1', 'team_id': 2, 'urgency': '긴급', 'source': 'rule', 'rule_id': 't2_up'}]
        n, _, out = self.collect(items, [_sub(2)], team_rows=rows)
        self.assertIn('[팀 알림] t:2 긴급 후보 2 → 보냄 2(리마인드 0)·억제 0·묶음 0 (계산) · AI 1회', out)
        self.assertIn('[팀 알림] 합계(collect·긴급) — 큐 긴급 2건 · AI 1회', out)
        self.assertEqual(self.grp.kws[self.n_grp_common:], [{'timeout': 20, 'max_retries': 1}],
                         '팀 경로의 사건 묶기는 짧은 제한(20초·재시도 1회)')
        self.assertTrue(all(k == {} for k in self.grp.kws[:self.n_grp_common]), '공통 경로는 인자 없이')
        q = self.queue('t:2', '긴급')
        self.assertEqual([r['news_url'] for r in q], ['https://n/s1', 'https://n/c1'])
        self.assertTrue(q[0]['html'].endswith('<i>매체 · 🏷 우리 팀 기준</i>'), q[0]['html'])
        self.assertTrue(q[1]['html'].endswith('<i>매체</i>'), '공통도 긴급인 기사는 표시 없음')
        self.assertEqual((n, crawler._AUD_STATS['ai']), (2, 1))
        self.assert_uniform()

    def test_team_view_prior_suppresses(self):
        """팀이 이미 긴급으로 본 기사(규칙 행)가 비교군 — 같은 사건의 새 기사는 그 팀에서 억제, 공통 구독자에게는 새 사건."""
        w = _nf('w1', '위성 주파수 공급 계획 발표', 2, urgency='보통')
        items = [_item('s2', '위성 주파수 공급 계획 발표 후속', urgency='긴급')]
        rows = [{'news_id': 'id-w1', 'team_id': 2, 'urgency': '긴급', 'source': 'rule', 'rule_id': 't2_up'},
                {'news_id': 'id-s2', 'team_id': 2, 'urgency': '긴급', 'source': 'rule', 'rule_id': 't2_up'}]
        n, reps, out = self.collect(items, [_sub(2)], prior=[w], team_rows=rows)
        self.assertEqual([r['title'] for r in reps], ['위성 주파수 공급 계획 발표 후속'], '공통: 비교군에 없음 → 보냄')
        self.assertIn('[팀 알림] t:2 긴급 후보 1 → 보냄 0(리마인드 0)·억제 1·묶음 0 (계산)', out)
        self.assertEqual(self.alog('t:2')[0]['matched_title'], '위성 주파수 공급 계획 발표')
        self.assertEqual((n, self.queue()), (0, []))

    def test_human_raise_not_alerted_lower_blocks_and_view_prior(self):
        w2 = _nf('w2', '알뜰폰 도매대가 협상 타결', 5, urgency='보통')
        items = [_item('h1', '통신 분쟁 조정 신청 급증', urgency='보통'),       # 팀원이 긴급으로 올림 → 알림 안 함
                 _item('h2', '단말 보조금 공시 변경', urgency='긴급'),          # 팀원이 참고로 내림 → 막음
                 _item('h3', '알뜰폰 도매대가 협상 타결 이후 전망', urgency='긴급')]
        rows = [{'news_id': 'id-h1', 'team_id': 1, 'urgency': '긴급', 'source': 'human', 'rule_id': None},
                {'news_id': 'id-h2', 'team_id': 1, 'urgency': '참고', 'source': 'human', 'rule_id': None},
                {'news_id': 'id-w2', 'team_id': 1, 'urgency': '긴급', 'source': 'human', 'rule_id': None}]
        n, reps, out = self.collect(items, [_sub(1)], prior=[w2], team_rows=rows)
        self.assertEqual({r['title'] for r in reps}, {'단말 보조금 공시 변경', '알뜰폰 도매대가 협상 타결 이후 전망'})
        self.assertIn('[팀 알림] t:1 긴급 후보 1 → 보냄 0(리마인드 0)·억제 1·묶음 0 (계산)', out)
        self.assertEqual([r['article_title'] for r in self.alog('t:1')], ['알뜰폰 도매대가 협상 타결 이후 전망'],
                         '비교군은 팀이 지금 보는 등급(팀원이 올린 w2 포함)')
        self.assertEqual(n, 0)

    def test_division_same_article_once_with_team_names(self):
        items = [_item('m1', '위성 기반 AI 정책 발표', urgency='보통')]
        rows = [{'news_id': 'id-m1', 'team_id': 2, 'urgency': '긴급', 'source': 'rule', 'rule_id': 't2_up'},
                {'news_id': 'id-m1', 'team_id': 3, 'urgency': '긴급', 'source': 'ai', 'rule_id': None}]
        n, _, out = self.collect(items, [_sub(division='사업협력실'), _sub(division='사업협력실')], team_rows=rows)
        q = self.queue('d:사업협력실', '긴급')
        self.assertEqual(len(q), 1, '두 팀이 골라도 한 번')
        self.assertTrue(q[0]['html'].endswith('<i>매체 · 🏷 기술정책팀·AI정책팀</i>'), q[0]['html'])
        self.assertEqual(len(self.alog('d:사업협력실')), 1)
        self.assertEqual(n, 1)

    def test_normal_channel(self):
        """보통 채널 — 비교군은 긴급+보통(중요로 이미 간 사건의 뒤 보통은 안 보냄), 'c' 보통은 한 번 계산하고 같은 입력의 팀은 복사.
        채널 순서: 긴급(전 단위) 먼저, 그다음 보통. 큐는 단위·채널마다 기록 직후 바로."""
        w3 = _nf('w3', '해킹 사고 후속 대책 발표', 2, urgency='긴급')
        items = [_item('v1', '와이파이 품질 평가 결과 공개', urgency='보통'),
                 _item('v2', '와이파이 품질 평가 결과 공개 반응', urgency='보통'),
                 _item('v3', '해킹 사고 후속 대책 발표 이후 과제', urgency='보통'),
                 _item('v4', '기지국 전력 절감 기술', urgency='긴급')]
        n, _, out = self.collect(items, [_sub(level='normal'), _sub(2, level='normal'), _sub(2)], prior=[w3])
        self.assertIn('[팀 알림] c 보통 후보 3 → 보냄 1(리마인드 0)·억제 1·묶음 1 (계산)', out)
        self.assertIn('[팀 알림] t:2 보통 후보 3 → 보냄 1(리마인드 0)·억제 1·묶음 1 (복사)', out)
        self.assertIn('[팀 알림] t:2 긴급 후보 1 → 보냄 1(리마인드 0)·억제 0·묶음 0 (복사)', out)
        self.assertLess(out.index('합계(collect·긴급)'), out.index(' c 보통 후보'), '긴급 채널이 먼저')
        self.assertEqual([(r['audience'], r['level'], r['news_url']) for r in self.queue()],
                         [('t:2', '긴급', 'https://n/v4'), ('c', '보통', 'https://n/v1'), ('t:2', '보통', 'https://n/v1')])
        self.assertEqual(len(self.db.calls('subscriber_queue', 'insert')), 3, '단위·채널마다 기록 직후 바로 큐')
        self.assertIn('(관련 보도 1건)', self.queue('c')[0]['html'])
        self.assertEqual([r['matched_title'] for r in self.alog('c', '보통') if r['outcome'] == 'suppressed'],
                         ['해킹 사고 후속 대책 발표'], '보통 채널 비교군에 긴급 기사가 들어간다(B-1)')
        chains = [e for e in self.team_log() if e['table'] == 'subscriber_alert_log' and e['op'] == 'select'
                  and ('in', 'outcome', ['suppressed', 'merged']) in e['filters']]
        self.assertEqual([[f for f in e['filters'] if f[0] == 'eq'] for e in chains],
                         [[('eq', 'audience', 'c'), ('eq', 'channel', '보통')]], "사슬 조회는 계산한 'c' 보통 한 번")
        self.assertIn('[팀 알림] 합계(collect·긴급) — 큐 긴급 1건', out)
        self.assertIn('[팀 알림] 합계(collect·보통) — 큐 보통 2건', out)
        self.assertEqual(n, 1)
        self.assertEqual(crawler.audience_note(), ' team=긴급1/보통2/오류0')
        self.assert_uniform()

    def test_split_calls_reuse_preparation(self):
        """main처럼 긴급 → 보통으로 나눠 불러도 준비(구독자·팀 행·기록 확인)는 한 번만 읽는다."""
        items = [_item('v1', '와이파이 품질 평가 결과 공개', urgency='보통'), _item('v4', '기지국 전력 절감 기술', urgency='긴급')]
        for k, it in enumerate(items):
            crawler._INSERTED_IDS[it['url']] = 'id-' + it['url'].rsplit('/', 1)[1]
        self.db = FakeDb({'news_feed': [dict(i, id='id-' + i['url'].rsplit('/', 1)[1], created_at=_ts(0.01), origin=None)
                                        for i in items],
                          'telegram_subscribers': [_sub(2, level='normal')], 'teams': TEAMS, 'team_urgency': [],
                          'subscriber_alert_log': [], 'subscriber_queue': []})
        with mock.patch.object(crawler, 'sb', self.db):
            n1, _ = _quiet(crawler.run_audience_alerts, 'collect', new_items=items, channels=('긴급',))
            q1 = [r['level'] for r in self.queue()]
            n2, _ = _quiet(crawler.run_audience_alerts, 'collect', new_items=items, channels=('보통',))
        self.assertEqual((n1, q1, n2), (1, ['긴급'], 0))
        self.assertEqual([r['level'] for r in self.queue()], ['긴급', '보통'])
        self.assertEqual(len(self.db.calls('telegram_subscribers')), 1)
        self.assertEqual(len([e for e in self.db.calls('news_feed') if e['range']]), 1, '비교군 창도 한 번')

    def test_normal_base_not_computed_when_no_copy(self):
        """팀 보통 후보가 'c'와 다르면 'c' 기준은 계산하지 않는다('c' 단위가 없을 때 — 헛 계산·AI 호출 없음)."""
        items = [_item('s3', '위성 발사 일정 공개', urgency='참고')]
        rows = [{'news_id': 'id-s3', 'team_id': 2, 'urgency': '보통', 'source': 'ai', 'rule_id': None}]
        n, _, out = self.collect(items, [_sub(2, level='normal')], team_rows=rows)
        self.assertIn('[팀 알림] t:2 보통 후보 1 → 보냄 1(리마인드 0)·억제 0·묶음 0 (계산)', out)
        self.assertNotIn(' c 보통', out)
        self.assertEqual(self.alog('c'), [], "기준을 계산하지 않았으면 'c' 기록도 없다")
        chains = [e for e in self.team_log() if e['table'] == 'subscriber_alert_log' and e['op'] == 'select'
                  and ('in', 'outcome', ['suppressed', 'merged']) in e['filters']]
        self.assertEqual(len(chains), 1)
        self.assertTrue(self.queue('t:2', '보통')[0]['html'].endswith('🏷 우리 팀 기준</i>'))
        self.assertEqual(n, 0, '보통만 — 즉시 배달 몫 아님')

    def test_normal_base_logged_as_c_even_when_c_inactive(self):
        """R6 — 'c'가 활성 단위가 아니어도 계산한 보통 기준은 'c' 이름으로 기록(사슬), 큐에는 없음."""
        items = [_item('v1', '와이파이 품질 평가 결과 공개', urgency='보통'),
                 _item('v2', '와이파이 품질 평가 결과 공개 반응', urgency='보통')]
        n, _, out = self.collect(items, [_sub(2, level='normal')])
        self.assertIn('[팀 알림] t:2 보통 후보 2 → 보냄 1(리마인드 0)·억제 0·묶음 1 (복사)', out)
        self.assertEqual(sorted((r['article_title'], r['outcome']) for r in self.alog('c', '보통')),
                         [('와이파이 품질 평가 결과 공개', 'sent'), ('와이파이 품질 평가 결과 공개 반응', 'merged')])
        self.assertEqual([r['audience'] for r in self.queue()], ['t:2'])

    def test_normal_excludes_articles_logged_urgent_for_same_unit(self):
        """R7 — 같은 단위에 긴급 기록이 있는 기사는 보통 채널 후보에서 뺀다(긴급으로 간 기사가 보통 묶음으로 또 가지 않게)."""
        items = [_item('r1', '해저 케이블 장애 복구 지연', urgency='보통'), _item('r2', '기지국 전력 절감 기술', urgency='보통')]
        n, _, out = self.collect(items, [_sub(2, level='normal')], alert_log=[
            {'id': 1, 'audience': 't:2', 'channel': '긴급', 'news_id': 'id-r1', 'outcome': 'sent', 'article_title': 'x',
             'created_at': _ts(0.01)}])
        self.assertEqual([r['news_url'] for r in self.queue('t:2', '보통')], ['https://n/r2'])

    def test_log_first_existing_record_not_queued(self):
        """기록 upsert 응답에 없는(= 그 사이 다른 실행이 먼저 기록한) 대표는 큐에 넣지 않는다. 기록이 큐보다 먼저."""
        items = [_item('d1', '기지국 전력 절감', urgency='긴급'), _item('d2', '해저 케이블 장애 복구', urgency='긴급')]

        def racer(db):
            db.tables['subscriber_alert_log'].append({'id': 999, 'audience': 't:1', 'channel': '긴급', 'news_id': 'id-d1',
                                                      'outcome': 'sent', 'article_title': '기지국 전력 절감'})
        for it in items:
            crawler._INSERTED_IDS[it['url']] = 'id-' + it['url'].rsplit('/', 1)[1]
        self.db = FakeDb({'news_feed': [], 'telegram_subscribers': [_sub(1)], 'teams': TEAMS, 'team_urgency': [],
                          'subscriber_alert_log': [], 'alert_suppress_log': [], 'subscriber_queue': []})
        self.db.before[('subscriber_alert_log', 'upsert')] = racer
        with mock.patch.object(crawler, 'sb', self.db):
            n, out = _quiet(crawler.run_audience_alerts, 'collect', new_items=items)
        self.assertEqual([r['news_url'] for r in self.queue()], ['https://n/d2'])
        self.assertIn('보냄 1', out)
        i_log = next(k for k, e in enumerate(self.db.log) if e['table'] == 'subscriber_alert_log' and e['op'] == 'upsert')
        i_q = next(k for k, e in enumerate(self.db.log) if e['table'] == 'subscriber_queue')
        self.assertLess(i_log, i_q)
        self.assertEqual(n, 1)

    def test_already_logged_excluded(self):
        items = [_item('e1', '기지국 전력 절감', urgency='긴급')]
        n, _, out = self.collect(items, [_sub(1)], alert_log=[
            {'id': 1, 'audience': 't:1', 'channel': '긴급', 'news_id': 'id-e1', 'outcome': 'sent', 'article_title': 'x',
             'created_at': _ts(0.01)}])
        self.assertEqual((n, out, self.queue()), (0, '', []))
        self.assertFalse([e for e in self.team_log() if e['table'] == 'news_feed'], '후보가 없으면 비교군 창도 안 읽음')

    def test_rules_failure_team_levels_are_common(self):
        """R3 — 팀 규칙 표 조회가 실패한 실행은 팀 규칙 행을 안 썼으므로 팀 등급 = 공통값(규칙 없이 계산 → 대개 복사).
        팀·실장 단위를 건너뛰지 않는다. 옛 규칙 행은 규칙 정의가 없으니 공통값으로 본다."""
        items = [_item('f1', '와이파이 요금 개편', urgency='보통'), _item('f2', '기지국 전력 절감', urgency='긴급')]
        rows = [{'news_id': 'id-f1', 'team_id': 2, 'urgency': '긴급', 'source': 'rule', 'rule_id': 't2_up'}]
        with mock.patch.object(crawler, '_TEAM_RULES_ENABLED', None):
            n, _, out = self.collect(items, [_sub(1), _sub(division='사업협력실'), _sub(level='normal')], team_rows=rows)
        self.assertIn('[팀 알림] 규칙 조회 실패 — 이번 실행 팀 등급은 공통값으로', out)
        self.assertIn('[팀 알림] t:1 긴급 후보 1 → 보냄 1(리마인드 0)·억제 0·묶음 0 (복사)', out)
        self.assertIn('[팀 알림] d:사업협력실 긴급 후보 1 → 보냄 1(리마인드 0)·억제 0·묶음 0 (복사)', out)
        self.assertEqual(sorted((r['audience'], r['news_url']) for r in self.queue()),
                         [('c', 'https://n/f1'), ('d:사업협력실', 'https://n/f2'), ('t:1', 'https://n/f2')])
        self.assertEqual(n, 2)

    def test_candidates_only_inserted_fresh_origin_null_with_url(self):
        items = [_item('g1', '기지국 전력 절감', urgency='긴급'),
                 _item('g2', '해저 케이블 장애', urgency='긴급'),                   # 동시 실행이 먼저 넣음
                 _item('g3', '위성 통신 표준 확정', urgency='긴급', pub=30),        # 발행 24시간 초과
                 dict(_item('g4', '옛 보도 되살림', urgency='긴급'), origin='issuemap'),
                 dict(_item('g5', '주소 없는 기사', urgency='긴급'), url='')]
        n, _, out = self.collect(items, [_sub(1)], inserted={'https://n/g1', 'https://n/g3', 'https://n/g4', ''})
        self.assertEqual([r['news_url'] for r in self.queue()], ['https://n/g1'])
        self.assertIn('후보 1 →', out)

    def test_window_not_read_without_unit_candidates(self):
        items = [_item('k1', '보통 기사', urgency='보통')]
        n, _, out = self.collect(items, [_sub(1)])
        self.assertEqual((n, out), (0, ''))
        self.assertEqual([e['table'] for e in self.team_log()],
                         ['telegram_subscribers', 'team_urgency', 'subscriber_alert_log'])

    def test_chunk_sizes_stay_under_1000_rows(self):
        """R8 — in_ 두 개를 곱한 조회는 묶음 = 1,000 // (기사당 최대 행 수)."""
        self.assertEqual([crawler._id_chunk(k) for k in (0, 1, 2, 12, 40, 2000)], [100, 100, 100, 83, 25, 1])
        teams = [{'id': 100 + k, 'division': '큰실', 'name': f'팀{k}', 'sort_order': k} for k in range(40)]
        items = [_item(f'q{k}', f'고유 제목 {k}번 기사', urgency='긴급') for k in range(60)]
        self.collect(items, [_sub(division='큰실')], extra={'teams': teams})
        tu = [e for e in self.db.calls('team_urgency', 'select')]
        self.assertTrue(tu and all(len(dict((f[1], f[2]) for f in e['filters'] if f[0] == 'in')['news_id']) <= 25
                                   for e in tu))
        lg = [e for e in self.db.calls('subscriber_alert_log', 'select')
              if ('in', 'outcome', ['suppressed', 'merged']) not in e['filters']]
        self.assertTrue(lg and all(len(dict((f[1], f[2]) for f in e['filters'] if f[0] == 'in')['news_id'])
                                   <= crawler._id_chunk(2 * 2) for e in lg))


class TestResilience(_AudBase):
    """R5·R9 — 읽기 재시도, 계산 불가면 'collect' 긴급은 공통 결과 복사(대체), 기록 한 행씩 폴백, 큐 실패 경고."""

    def test_transient_read_errors_are_retried(self):
        items = [_item('t1', '기지국 전력 절감', urgency='긴급')]
        crawler._INSERTED_IDS[items[0]['url']] = 'id-t1'
        self.db = FakeDb({'news_feed': [dict(items[0], id='id-t1', created_at=_ts(0.01), origin=None)],
                          'telegram_subscribers': [_sub(1)], 'teams': TEAMS, 'team_urgency': [],
                          'subscriber_alert_log': [], 'subscriber_queue': []})
        self.db.flaky = {('telegram_subscribers', 'select'): 1, ('team_urgency', 'select'): 1,
                         ('subscriber_alert_log', 'select'): 1, ('news_feed', 'select'): 1}
        with mock.patch.object(crawler, 'sb', self.db):
            n, out = _quiet(crawler.run_audience_alerts, 'collect', new_items=items)
        self.assertEqual(n, 1)
        self.assertEqual(out.count('[재시도 1/2]'), 4)
        self.assertEqual(crawler._AUD_STATS['오류'], 0)

    def test_subscribers_unreadable_no_team_alerts(self):
        items = [_item('z1', '기지국 전력 절감', urgency='긴급')]
        crawler._INSERTED_IDS['https://n/z1'] = 'id-z1'
        self.db = FakeDb({'news_feed': []}, fail={'telegram_subscribers'})
        with mock.patch.object(crawler, 'sb', self.db):
            n, out = _quiet(crawler.run_audience_alerts, 'collect', new_items=items)
        self.assertEqual(n, 0)
        self.assertIn('[팀 알림] 구독자 목록 조회 실패 — 이번 실행은 팀 알림 없음', out)
        self.assertEqual(crawler._AUD_STATS['오류'], 1)
        self.assertEqual(crawler.audience_note(), ' team=긴급0/보통0/오류1 fail=1', '단위를 몰라도 오류는 메모에 남긴다(fail=K — 워치독 경보)')

    def test_unexpected_exception_fail_open(self):
        items = [_item('z2', '기지국 전력 절감', urgency='긴급')]
        crawler._INSERTED_IDS['https://n/z2'] = 'id-z2'
        self.db = FakeDb({'telegram_subscribers': [_sub(1)]})
        with mock.patch.object(crawler, 'sb', self.db), \
                mock.patch.object(crawler, '_alert_units', mock.Mock(side_effect=ValueError('뜻밖'))):
            n, out = _quiet(crawler.run_audience_alerts, 'collect', new_items=items)
        self.assertEqual(n, 0)
        self.assertIn('[팀 알림] collect 오류(무시 — 수집·공통 알림은 그대로): 뜻밖', out)

    def _fallback_setup(self, fail, subs=None, team_rows=()):
        items = [_item('a1', '기지국 전력 절감', urgency='긴급'), _item('a2', '기지국 전력 절감 기술 공개', urgency='긴급'),
                 _item('a3', '보통 기사', urgency='보통')]
        news = [dict(i, id='id-' + i['url'].rsplit('/', 1)[1], created_at=_ts(0.01), origin=None) for i in items]
        for i in items:
            crawler._INSERTED_IDS[i['url']] = 'id-' + i['url'].rsplit('/', 1)[1]
        self.db = FakeDb({'news_feed': news, 'telegram_subscribers': subs or [_sub(1, level='normal')], 'teams': TEAMS,
                          'team_urgency': list(team_rows), 'subscriber_alert_log': [], 'alert_suppress_log': [],
                          'subscriber_queue': []})
        with mock.patch.object(crawler, 'sb', self.db):
            reps, _ = _quiet(crawler.suppress_repeat_alerts, [i for i in items if i['urgency'] == '긴급'])
            self.db.fail |= set(fail)
            n, out = _quiet(crawler.run_audience_alerts, 'collect', new_items=items)
        return n, reps, out

    def test_window_failure_urgent_falls_back_to_common_copy(self):
        n, reps, out = self._fallback_setup({('news_feed', 'select')})
        self.assertIn('[팀 알림] 비교군 조회 실패', out)
        self.assertIn('[팀 알림] t:1 긴급 후보 2 → 보냄 1(리마인드 0)·억제 0·묶음 1 (대체: 공통 복사) · AI 0회', out)
        self.assertIn('[팀 알림] t:1 보통 건너뜀 — 비교군 조회 실패', out)
        self.assertEqual([r['html'] for r in self.queue('t:1')], [subscriber_notify.format_news_item(r) for r in reps])
        self.assertEqual(sorted(r['shared_keywords'] for r in self.alog('t:1')), ['[대체]', '[대체] [실행내묶음]'])
        self.assertEqual((n, crawler._AUD_STATS['오류']), (1, 1))

    def test_team_rows_failure_team_units_fall_back(self):
        n, _, out = self._fallback_setup({('team_urgency', 'select')}, subs=[_sub(1), _sub(division='사업협력실')])
        self.assertIn('[팀 알림] 팀 등급 조회 실패 — 이번 실행 팀·실장 단위는 긴급만 공통 결과로 대체', out)
        self.assertIn('d:사업협력실 긴급 후보 2 → 보냄 1(리마인드 0)·억제 0·묶음 1 (대체: 공통 복사)', out)
        self.assertIn('t:1 긴급 후보 2 → 보냄 1(리마인드 0)·억제 0·묶음 1 (대체: 공통 복사)', out)
        self.assertEqual(n, 2)

    def test_teams_failure_division_falls_back_team_unit_computes(self):
        n, _, out = self._fallback_setup({('teams', 'select')}, subs=[_sub(1), _sub(division='사업협력실')])
        self.assertIn('팀 목록 조회 실패 — 이번 실행 실장 단위는 긴급만 공통 결과로 대체', out)
        self.assertIn('d:사업협력실 긴급 후보 2 → 보냄 1(리마인드 0)·억제 0·묶음 1 (대체: 공통 복사)', out)
        self.assertIn('t:1 긴급 후보 2 → 보냄 1(리마인드 0)·억제 0·묶음 1 (복사)', out)
        self.assertEqual(n, 2)

    def test_unit_error_falls_back_others_untouched(self):
        items = [_item('i1', '기지국 전력 절감', urgency='긴급')]
        real = crawler._aud_same_inputs

        def boom(ctx, aud, *a):
            if aud == 't:2':
                raise RuntimeError('unit boom')
            return real(ctx, aud, *a)
        with mock.patch.object(crawler, '_aud_same_inputs', boom):
            n, _, out = self.collect(items, [_sub(1), _sub(2), _sub(3)])
        self.assertIn('[팀 알림] t:2 긴급 판정 오류 → 공통 결과로 대체: unit boom', out)
        self.assertIn('[팀 알림] t:2 긴급 후보 1 → 보냄 1(리마인드 0)·억제 0·묶음 0 (대체: 공통 복사)', out)
        self.assertEqual([r['audience'] for r in self.queue()], ['t:1', 't:2', 't:3'])
        self.assertEqual([r['shared_keywords'] for r in self.alog('t:2')], ['[대체]'])
        self.assertEqual([r['shared_keywords'] for r in self.alog('t:1')], [None])
        self.assertEqual((n, crawler._AUD_STATS['오류']), (3, 1))

    def test_fallback_failure_and_normal_error_skip_only_that_unit(self):
        items = [_item('i1', '기지국 전력 절감', urgency='긴급'), _item('i2', '해저 케이블 장애', urgency='보통')]
        real_rows, real_same = crawler._alert_log_rows, crawler._aud_same_inputs

        def rows_boom(aud, *a):
            if aud == 't:2':
                raise RuntimeError('rows boom')
            return real_rows(aud, *a)

        def same_boom(ctx, aud, u, ch, *a):
            if aud == 't:3' and ch == '보통':
                raise RuntimeError('normal boom')
            return real_same(ctx, aud, u, ch, *a)
        with mock.patch.object(crawler, '_alert_log_rows', rows_boom), \
                mock.patch.object(crawler, '_aud_same_inputs', same_boom):
            n, _, out = self.collect(items, [_sub(1), _sub(2), _sub(3, level='normal')])
        self.assertIn('[팀 알림] t:2 긴급 대체도 실패 — 이번 실행은 보내지 않음(무시): rows boom', out)
        self.assertIn('[팀 알림] t:3 보통 판정 오류 — 이번 실행은 보내지 않음(무시): normal boom', out)
        self.assertEqual(sorted((r['audience'], r['level']) for r in self.queue()), [('t:1', '긴급'), ('t:3', '긴급')])
        self.assertEqual(n, 2)

    def test_log_rows_fall_back_one_by_one(self):
        """R9 — 묶음이 FK 오류(수집 직후 지워진 기사)로 실패하면 한 행씩 — 그 행만 빠진다."""
        db = FakeDb({'subscriber_alert_log': []})
        db.fail_when = lambda q: q.name == 'subscriber_alert_log' and q.op == 'upsert' and \
            any(r.get('news_id') == 'gone' for r in q.payload)
        rows = [{'audience': 't:1', 'channel': '긴급', 'news_id': n, 'article_title': n, 'article_url': n,
                 'outcome': o, 'matched_title': None, 'shared_keywords': None}
                for n, o in (('a', 'sent'), ('gone', 'sent'), ('c', 'suppressed'))]
        with mock.patch.object(crawler, 'sb', db):
            (fresh, ok, bad, err), _ = _quiet(crawler._save_alert_log, rows)
            self.assertEqual((fresh, ok, bad), ({'a'}, {'a', 'c'}, 1))
            db.fail.add('subscriber_alert_log')
            with self.assertRaises(RuntimeError):
                _quiet(crawler._save_alert_log, rows)

    def test_queue_failure_warns_records_not_resent(self):
        crawler._INSERTED_IDS['https://n/w2'] = 'id-w2'
        db = FakeDb({'news_feed': [], 'telegram_subscribers': [_sub(1)], 'teams': TEAMS, 'team_urgency': [],
                     'subscriber_alert_log': [], 'subscriber_queue': []}, fail={('subscriber_queue', 'insert')})
        with mock.patch.object(crawler, 'sb', db):
            n2, out2 = _quiet(crawler.run_audience_alerts, 'collect', new_items=[_item('w2', '해저 케이블 장애')])
        self.assertEqual(n2, 0)
        self.assertIn('[팀 알림] t:1 긴급 기록 1건은 들어갔으나 큐 적재 실패 — 이 기사들은 다시 가지 않음', out2)
        self.assertEqual(len(db.tables['subscriber_alert_log']), 1)

    def test_log_write_failure_sends_nothing_for_that_unit(self):
        crawler._INSERTED_IDS['https://n/y2'] = 'id-y2'
        db = FakeDb({'news_feed': [], 'telegram_subscribers': [_sub(1)], 'teams': TEAMS, 'team_urgency': [],
                     'subscriber_alert_log': [], 'subscriber_queue': []}, fail={('subscriber_alert_log', 'upsert')})
        with mock.patch.object(crawler, 'sb', db):
            n2, out2 = _quiet(crawler.run_audience_alerts, 'collect', new_items=[_item('y2', '해저 케이블 장애')])
        self.assertEqual(n2, 0)
        self.assertIn('기록 실패 — 이번 실행은 보내지 않음', out2)
        self.assertEqual(db.tables['subscriber_queue'], [])


# ── 늦은 판정(late) ──────────────────────────────────────────────────────────────────────────────
S_WIFI = {'id': 's_wifi', 'team_id': 7, 'position': 10, 'mode': 'set', 'level': '긴급',
          'any_words': ['공공와이파이'], 'and_any': [], 'none_words': [], 'enabled': True,
          'sentence': '공공와이파이 문제를 제기하는 기사', 'sentence_rev': 1}
S_MID = {'id': 's_mid', 'team_id': 7, 'position': 20, 'mode': 'set', 'level': '보통',
         'any_words': ['지하철와이파이'], 'and_any': [], 'none_words': [], 'enabled': True,
         'sentence': '지하철 와이파이 장애 기사', 'sentence_rev': 0}
TEAMS_LATE = [{'id': 7, 'division': '대외지원실', 'name': 'CR지원팀', 'sort_order': 10},
              {'id': 8, 'division': '대외지원실', 'name': '정책분석팀', 'sort_order': 20}]
BODY = '서울 지하철 공공와이파이가 잦은 끊김으로 이용자 불만이 커지고 있다. ' * 6


def _vrow(nid, status, requested_by, created_h=0.1, attempts=0, rev=1, rule='s_wifi'):
    return {'rule_id': rule, 'sentence_rev': rev, 'news_id': nid, 'team_id': 7, 'status': status, 'verdict': None,
            'reason': '', 'input_kind': '', 'model': '', 'cost_usd': 0, 'attempts': attempts,
            'requested_by': requested_by, 'created_at': (datetime.now(timezone.utc) - timedelta(hours=created_h)).isoformat(),
            'judged_at': None}


class TestLate(_AudBase):
    RULES = {'s_wifi': S_WIFI, 's_mid': S_MID}
    # 기사(생성 시각 h 전) — 판정 행은 모두 0.1시간 전에 생김
    NEWS = {'l1': ('서울 지하철 공공와이파이 먹통 불만 폭주', 0.2),   # 수집 경로·참 → 알림
            'l2': ('부산 공공와이파이 설치 확대 발표', 0.2),           # 대시보드 요청 → 화면만
            'l3': ('대전 공공와이파이 보안 점검 결과', 0.2),           # 되살림 → 화면만
            'l4': ('인천 공공와이파이 요금 논란', 5),                  # requested_by null이지만 기사보다 한참 뒤 요청(재대기) → 없음
            'l5': ('광주 공공와이파이 속도 저하', 0.2),                # 거짓 판정 → 없음
            'l6': ('울산 공공와이파이 끊김 민원', 0.2),                # 참이지만 팀원 수정 행 → 없음
            'l7': ('대구 지하철와이파이 장애 민원', 0.2),              # 팀 7 보통(s_mid)·팀 8 AI 긴급 → 실장 최고 팀에 7 없음 → 없음
            'l8': ('포항 공공와이파이 해킹 우려', 0.2)}                # 참이지만 팀 행이 AI 긴급(규칙 행 아님) → 없음(R1)
    FALSE = {'광주 공공와이파이 속도 저하'}

    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(crawler, '_TEAM_URGENCY_RULES', {7: [S_WIFI, S_MID]}),
                  mock.patch.object(crawler, '_RULES_LOADED_AT', datetime.now(timezone.utc) - timedelta(hours=1)),
                  mock.patch.object(crawler.anthropic, 'Anthropic', lambda **kw: 'fake-client'),
                  mock.patch.object(crawler, '_judge_sentence_batch', self._judge),
                  mock.patch.object(crawler, '_add_run_cost', lambda rows: None),
                  mock.patch.dict(crawler._SENTENCE_RUN, {'judged': 0, 'nokey_logged': False, 'broken': False},
                                  clear=True)):
            p.start()
            self.addCleanup(p.stop)

    def _judge(self, client, sentence, rows):
        return {k: (r['title'] not in self.FALSE, '판정') for k, r in enumerate(rows, 1)}, 0.003

    def _tables(self, alert_log=()):
        news = [dict(_nf(n, t, h, urgency='참고'), content=BODY, screen_text='', summary='')
                for n, (t, h) in self.NEWS.items()]
        return {'news_feed': news,
                'urgency_rule_verdicts': [_vrow('id-l1', 'pending', None), _vrow('id-l2', 'pending', 'user-1'),
                                          _vrow('id-l3', 'stale', None), _vrow('id-l4', 'pending', None),
                                          _vrow('id-l5', 'pending', None), _vrow('id-l6', 'pending', None),
                                          _vrow('id-l7', 'pending', None, rev=0, rule='s_mid'),
                                          _vrow('id-l8', 'pending', None)],
                'team_urgency': [{'news_id': 'id-l6', 'team_id': 7, 'urgency': '참고', 'source': 'human', 'rule_id': None},
                                 {'news_id': 'id-l7', 'team_id': 8, 'urgency': '긴급', 'source': 'ai', 'rule_id': None},
                                 {'news_id': 'id-l8', 'team_id': 7, 'urgency': '긴급', 'source': 'ai', 'rule_id': None}],
                'telegram_subscribers': [_sub(7), _sub(division='대외지원실'), _sub(8), _sub()],
                'teams': TEAMS_LATE, 'subscriber_alert_log': list(alert_log), 'subscriber_queue': []}

    def test_late_only_true_collect_verdicts_that_set_the_team_row(self):
        self.db = FakeDb(self._tables())
        with mock.patch.object(crawler, 'sb', self.db):
            st, _ = _quiet(crawler._process_open_sentence_rows)
            self.assertEqual(st['judged'], 8, '여덟 다 판정됨(되살림 포함)')
            self.assertEqual({t: {n: set(r) for n, r in m.items()} for t, m in crawler._LATE_ALERT_PAIRS.items()},
                             {7: {'id-l1': {'s_wifi'}, 'id-l4': {'s_wifi'}, 'id-l6': {'s_wifi'}, 'id-l7': {'s_mid'},
                                  'id-l8': {'s_wifi'}}},
                             '참 판정 + requested_by null만(대시보드 요청·되살림·거짓 제외)')
            self.n_common_calls = len(self.db.log)
            n, out = _quiet(crawler.run_audience_alerts, 'late')
        self.assertEqual(crawler._LATE_ALERT_PAIRS, {}, '조회에 성공한 뒤 비운다')
        self.assertEqual(sorted((r['audience'], r['level'], r['news_url']) for r in self.queue()),
                         [('d:대외지원실', '긴급', 'https://n/l1'), ('t:7', '긴급', 'https://n/l1')])
        self.assertTrue(self.queue('t:7')[0]['html'].endswith('🏷 우리 팀 기준</i>'))
        self.assertTrue(self.queue('d:대외지원실')[0]['html'].endswith('🏷 CR지원팀</i>'))
        self.assertNotIn(' t:8 ', out, '그 팀이 없는 단위는 안 봄')
        self.assertIn('[팀 알림] 합계(late·긴급) — 큐 긴급 2건', out)
        self.assertEqual(n, 2)
        self.assert_uniform()

    def test_gap_rule(self):
        a = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
        self.assertTrue(crawler._late_gap_ok((a + timedelta(minutes=15)).isoformat(), a.isoformat()))
        self.assertFalse(crawler._late_gap_ok((a + timedelta(minutes=16)).isoformat(), a.isoformat()))
        self.assertFalse(crawler._late_gap_ok(None, a.isoformat()))
        self.assertEqual(crawler.LATE_COLLECT_MAX_GAP_MIN, 15)

    def test_late_skips_already_logged_and_no_pairs_zero_queries(self):
        self.db = FakeDb(self._tables(alert_log=[
            {'id': 1, 'audience': 't:7', 'channel': '긴급', 'news_id': 'id-l1', 'outcome': 'sent', 'article_title': 'x',
             'created_at': _ts(0.3)}]))
        with mock.patch.object(crawler, 'sb', self.db):
            _quiet(crawler._process_open_sentence_rows)
            n, out = _quiet(crawler.run_audience_alerts, 'late')
            self.assertEqual([(r['audience']) for r in self.queue()], ['d:대외지원실'])
            k = len(self.db.log)
            n2, out2 = _quiet(crawler.run_audience_alerts, 'late')
        self.assertEqual((n2, out2, len(self.db.log)), (0, '', k), '늦은 후보 없음 → 조회 0번')

    def test_pairs_kept_when_read_fails(self):
        self.db = FakeDb(self._tables())
        with mock.patch.object(crawler, 'sb', self.db):
            _quiet(crawler._process_open_sentence_rows)
            self.db.fail.add(('news_feed', 'select'))
            n, out = _quiet(crawler.run_audience_alerts, 'late')
            self.assertEqual(n, 0)
            self.assertIn('[팀 알림] 늦은 판정 기사 조회 실패 — 이번 실행 늦은 알림 없음', out)
            self.assertTrue(crawler._LATE_ALERT_PAIRS, '읽지 못했으면 비우지 않는다')
            self.db.fail.clear()
            n2, _ = _quiet(crawler.run_audience_alerts, 'late')
        self.assertEqual((n2, crawler._LATE_ALERT_PAIRS), (2, {}))

    def test_open_cols_include_requested_by(self):
        self.assertIn('requested_by', crawler._OPEN_VERDICT_COLS.split(','))


# ── 큐 행·표시·즉시 배달 ────────────────────────────────────────────────────────────────────────
class TestQueueAndFormat(unittest.TestCase):
    ITEMS = [{'title': '제목 <b>&', 'url': 'https://a/?x=1&y=2', 'source': '매체&'},
             {'title': 'T', 'url': '', 'source': ''},
             {'title': 'T2', 'url': 'u2', 'source': 'S', '_related': 3},
             {'title': 'T3', 'url': 'u3', 'source': 'S', '_remind': '2일째', '_related': 0},
             {'title': 'T4', 'url': 'u4', 'source': 'S', '_label': ''},
             {'url': 'u5'}]

    def test_format_without_label_is_byte_identical(self):
        for it in self.ITEMS:
            self.assertEqual(subscriber_notify.format_news_item(it), _ref_format_news_item(it))

    def test_label(self):
        f = subscriber_notify.format_news_item
        self.assertEqual(f({'title': 'T', 'url': 'u', 'source': 'S', '_label': '우리 팀 기준'}),
                         '<a href="u">T</a>\n   <i>S · 🏷 우리 팀 기준</i>')
        self.assertEqual(f({'title': 'T', 'url': 'u', 'source': '', '_label': '기술정책팀·AI정책팀'}),
                         '<a href="u">T</a>\n   <i>🏷 기술정책팀·AI정책팀</i>')
        self.assertIn('🏷 A&amp;B', f({'title': 'T', 'url': 'u', 'source': 'S', '_label': 'A&B'}))

    def test_news_row(self):
        r = subscriber_notify.news_row('t:2', '긴급', {'title': 'T', 'url': 'u', 'source': 'S', 'tags': ['ai', 3]})
        self.assertEqual(r, {'topic': 'news', 'audience': 't:2', 'level': '긴급', 'news_url': 'u', 'tags': ['ai', '3'],
                             'html': '<a href="u">T</a>\n   <i>S</i>'})
        self.assertEqual(subscriber_notify.news_row('c', '보통', {'title': 'T', 'url': 'u', 'tags': None})['tags'], [])
        self.assertIsNone(subscriber_notify.news_row('t:2', '긴급', {'title': 'T', 'url': ''}), '빈 url 금지')
        self.assertIsNone(subscriber_notify.news_row('x:1', '긴급', {'title': 'T', 'url': 'u'}))
        self.assertIsNone(subscriber_notify.news_row('t:2', '참고', {'title': 'T', 'url': 'u'}))
        self.assertIsNotNone(subscriber_notify.news_row('d:사업협력실', '보통', {'title': 'T', 'url': 'u'}))

    def test_queue_audience_rows(self):
        db = FakeDb({'subscriber_queue': []})
        rows = [subscriber_notify.news_row('t:2', '긴급', {'title': 'A', 'url': 'a'}), None,
                subscriber_notify.news_row('c', '보통', {'title': 'B', 'url': 'b'})]
        trig = []
        with mock.patch.object(subscriber_notify, '_trigger_delivery', lambda: trig.append(1)):
            got, _ = _quiet(subscriber_notify.queue_audience_rows, db, rows)
            self.assertEqual(got, {'긴급': 1, '보통': 1})
            self.assertEqual(trig, [], '즉시 배달은 부르는 쪽(main) 몫')
            bad, out = _quiet(subscriber_notify.queue_audience_rows, db, [rows[0], dict(rows[2], extra=1)])
            self.assertEqual(bad, {})
            self.assertIn('키 집합이 서로 다름', out)
            fail = FakeDb(fail={'subscriber_queue'})
            got2, out2 = _quiet(subscriber_notify.queue_audience_rows, fail, [rows[0]])
            self.assertEqual(got2, {})
            self.assertIn('적재 실패(무시)', out2)
            self.assertEqual(_quiet(subscriber_notify.queue_audience_rows, db, [])[0], {})

    def test_queue_news_items_rows_identical_and_trigger_flag(self):
        items = [{'title': 'A', 'url': 'a', 'source': 'S', 'tags': ['ai'], '_related': 2},
                 {'title': 'B', 'url': 'a', 'source': 'S'},                     # 같은 url — 한 번만
                 {'title': 'C <x>', 'url': '', 'source': 'S', 'tags': 'x', '_remind': '2일째'}]
        ref_db, db1, db2 = FakeDb({'subscriber_queue': []}), FakeDb({'subscriber_queue': []}), FakeDb({'subscriber_queue': []})
        trig = []
        _REF_TRIGGERS.clear()
        with mock.patch.object(subscriber_notify, '_trigger_delivery', lambda: trig.append(1)):
            r0, _ = _quiet(_ref_queue_news_items, ref_db, copy.deepcopy(items))
            r1, _ = _quiet(subscriber_notify.queue_news_items, db1, copy.deepcopy(items))
            self.assertEqual(trig, [1], '기본값 = 종전처럼 한 번 호출')
            r2, _ = _quiet(subscriber_notify.queue_news_items, db2, copy.deepcopy(items), trigger=False)
            self.assertEqual(trig, [1], 'trigger=False = 호출 없음')
        self.assertEqual((r0, r1, r2), (True, True, True))
        want = ref_db.calls('subscriber_queue', 'insert')[0]['rows']
        self.assertEqual(db1.calls('subscriber_queue', 'insert')[0]['rows'], want)
        self.assertEqual(db2.calls('subscriber_queue', 'insert')[0]['rows'], want)
        self.assertEqual({(r['topic'], 'audience' in r, 'level' in r) for r in want}, {('urgent', False, False)})
        self.assertEqual(_REF_TRIGGERS, [1])

    def test_trigger_header(self):
        posts = []

        class _Resp:
            status_code, text = 200, 'ok'

        def fake_post(url, headers=None, timeout=None):
            posts.append((url, dict(headers or {})))
            return _Resp()
        with mock.patch.dict(os.environ, {'SUPABASE_URL': 'https://x.supabase.co', 'CRON_SECRET': 'sec'}), \
                mock.patch('requests.post', fake_post):
            ok, _ = _quiet(subscriber_notify._trigger_delivery)
        self.assertTrue(ok)
        self.assertEqual(posts, [('https://x.supabase.co/functions/v1/send-subscriber-briefing',
                                  {'x-cron-secret': 'sec', 'x-delivery': 'immediate'})])

    def test_news_topic_only_via_audience_rows(self):
        self.assertIn('news', subscriber_notify._VALID_TOPICS)
        db = FakeDb({'subscriber_queue': []})
        ok, out = _quiet(subscriber_notify.queue_for_subscribers, db, 'news', '<b>x</b>')
        self.assertFalse(ok)
        self.assertEqual(db.log, [])
        self.assertIn('queue_audience_rows로만', out)


# ── main — 긴급 채널 → 즉시 배달 한 번(팀 단계 예외에도) → 보통 채널, late는 긴급 행이 있고 앞 호출이 실패하지 않았을 때만 ─────
class TestMainDelivery(unittest.TestCase):

    def run_main(self, new_items, collect=0, late=0, collect_raises=False, late_raises=False, trigger_ok=True,
                 stats=None):
        ev = []
        db = FakeDb({'news_feed': [], 'alert_suppress_log': [], 'subscriber_queue': []})
        real_q = subscriber_notify.queue_news_items

        def q(sb_, items, trigger=True):
            ev.append(('queue_common', trigger))
            return real_q(sb_, items, trigger=trigger)

        def fake_run(stage, new_items=None, cutoff_24h=None, channels=None):
            ev.append(('run', stage, channels))
            if stats:
                crawler._AUD_STATS.update(stats)
            if stage == 'collect' and channels == ('긴급',) and collect_raises:
                raise RuntimeError('boom')
            if stage == 'late' and late_raises:
                raise RuntimeError('late boom')
            if stage == 'collect':
                return collect if channels == ('긴급',) else 0
            return late

        patches = [mock.patch.object(crawler, 'sb', db),
                   mock.patch.object(crawler, 'crawl_naver_news', lambda: (list(new_items), 0)),
                   mock.patch.object(crawler, 'crawl_google_news_rss', lambda: []),
                   mock.patch.object(crawler, 'get_existing_urls', lambda items: (set(), set())),
                   mock.patch.object(crawler, 'save_new_items', lambda items, ex: list(new_items)),
                   mock.patch.object(crawler, 'send_telegram', lambda items: ev.append(('op_telegram', len(items)))),
                   mock.patch.object(crawler, 'send_urgent_email', lambda items: ev.append(('op_email', len(items)))),
                   mock.patch.object(crawler, 'process_open_sentence_verdicts', lambda: ev.append(('verdicts',))),
                   mock.patch.object(crawler, 'sb_heartbeat', lambda sb_, key, note: ev.append(('heartbeat', key, note))),
                   mock.patch.object(crawler, 'ISSUE_SUGGEST_HOURS', set()),
                   mock.patch.object(crawler, 'ANTHROPIC_API_KEY', ''),
                   mock.patch.object(crawler, 'run_audience_alerts', fake_run),
                   mock.patch.object(subscriber_notify, 'queue_news_items', q),
                   mock.patch.object(subscriber_notify, '_trigger_delivery',
                                     lambda: ev.append(('trigger',)) or trigger_ok),
                   mock.patch.dict(crawler._GROUP_MEMO, {}, clear=True),
                   mock.patch.dict(crawler._AUD_CTX, {}, clear=True),
                   mock.patch.dict(crawler._AUD_STATS, {}, clear=False),
                   mock.patch.object(crawler, '_COMMON_ALERT', None)]
        with contextlib.ExitStack() as st:
            for p in patches:
                st.enter_context(p)
            _, out = _quiet(crawler.main)
        return ev, out, db

    @staticmethod
    def kinds(ev, *names):
        return [e for e in ev if e[0] in names]

    def test_common_and_team_urgent_then_trigger_then_normal(self):
        ev, _, db = self.run_main([_item('a1', '기지국 전력 절감')], collect=2)
        self.assertEqual([e[:2] if e[0] == 'heartbeat' else e for e in ev],
                         [('op_telegram', 1), ('op_email', 1), ('queue_common', False), ('run', 'collect', ('긴급',)),
                          ('trigger',), ('run', 'collect', ('보통',)), ('verdicts',), ('run', 'late', None),
                          ('heartbeat', 'last_crawl_run')])
        self.assertEqual(len(db.calls('subscriber_queue', 'insert')), 1)

    def test_team_step_raises_trigger_still_once(self):
        ev, out, _ = self.run_main([_item('a1', '기지국 전력 절감')], collect_raises=True)
        self.assertEqual([e[0] for e in self.kinds(ev, 'trigger', 'heartbeat', 'verdicts', 'run')],
                         ['run', 'trigger', 'run', 'verdicts', 'run', 'heartbeat'])
        self.assertIn('[팀 알림] 실패(무시): boom', out)

    def test_only_team_urgent_triggers(self):
        ev, _, _ = self.run_main([_item('b1', '보통 기사', urgency='보통')], collect=1)
        self.assertEqual(ev.count(('trigger',)), 1)
        self.assertNotIn(('queue_common', False), ev)

    def test_no_urgent_rows_no_trigger(self):
        ev, _, _ = self.run_main([_item('b1', '보통 기사', urgency='보통')], collect=0)
        self.assertEqual(ev.count(('trigger',)), 0, '보통 행만(또는 없음) — :25 정기 발송 몫')

    def test_late_urgent_triggers_once_more(self):
        ev, _, _ = self.run_main([_item('a1', '기지국 전력 절감')], collect=0, late=1)
        self.assertEqual([e[:2] for e in self.kinds(ev, 'trigger', 'run')],
                         [('run', 'collect'), ('trigger',), ('run', 'collect'), ('run', 'late'), ('trigger',)])

    def test_late_trigger_skipped_when_first_failed(self):
        """R10 — 앞 즉시 호출이 200이 아니면(그 발송 실행이 아직 돌 수 있다) 두 번째는 생략, :25가 받친다."""
        ev, out, _ = self.run_main([_item('a1', '기지국 전력 절감')], collect=0, late=1, trigger_ok=False)
        self.assertEqual(ev.count(('trigger',)), 1)
        self.assertIn('앞 즉시 호출이 성공하지 않아 두 번째 호출 생략', out)

    def test_late_trigger_when_no_first_call(self):
        ev, _, _ = self.run_main([_item('b1', '보통 기사', urgency='보통')], collect=0, late=1, trigger_ok=False)
        self.assertEqual(ev.count(('trigger',)), 1, '앞 호출이 없었으면 겹칠 발송도 없다')

    def test_late_raises_heartbeat_still(self):
        ev, out, _ = self.run_main([], late_raises=True)
        self.assertTrue(self.kinds(ev, 'heartbeat'))
        self.assertEqual(ev.count(('trigger',)), 0)
        self.assertIn('[팀 알림] 늦은 판정 알림 실패(무시)', out)

    def test_heartbeat_note_tail(self):
        """R11 — 받는 단위가 있으면 메모 끝에 ' team=긴급N/보통M/오류K'(오류가 있으면 ' fail=K' — 워치독 경보), 없으면 종전 그대로."""
        ev, _, _ = self.run_main([_item('a1', '기지국 전력 절감')])
        self.assertEqual(self.kinds(ev, 'heartbeat'), [('heartbeat', 'last_crawl_run', 'new=1 total=1')])
        ev, _, _ = self.run_main([_item('a1', '기지국 전력 절감')],
                                 stats={'units': 2, '긴급': 3, '보통': 5, '오류': 1})
        self.assertEqual(self.kinds(ev, 'heartbeat'),
                         [('heartbeat', 'last_crawl_run', 'new=1 total=1 team=긴급3/보통5/오류1 fail=1')])
        note = self.kinds(ev, 'heartbeat')[0][2]
        self.assertIsNotNone(re.search(r'(fail|failed)=[1-9]|실패\s+[1-9]', note),
                             '오류가 있으면 watchdog_scan 실패 정규식에 걸린다(운영자 결정 — 경보 받기)')
        ev, _, _ = self.run_main([_item('a1', '기지국 전력 절감')],
                                 stats={'units': 2, '긴급': 3, '보통': 5, '오류': 0})
        note = self.kinds(ev, 'heartbeat')[0][2]
        self.assertEqual(note, 'new=1 total=1 team=긴급3/보통5/오류0')
        self.assertIsNone(re.search(r'(fail|failed)=[1-9]|실패\s+[1-9]', note), '오류 0이면 경보 없음')

    def test_common_path_unchanged_through_main(self):
        """main을 거친 공통 경로: 운영자 알림·공통 큐 행은 기준본(나누기 전 억제 + 종전 큐)과 같다."""
        items = [_item('a1', '기지국 전력 절감'), _item('a2', '기지국 전력 절감 기술 공개'), _item('a3', '보통 기사', urgency='보통')]
        ev, _, db = self.run_main(items)
        rows = db.calls('subscriber_queue', 'insert')[0]['rows']
        ref_db = FakeDb({'news_feed': [], 'alert_suppress_log': [], 'subscriber_queue': []})
        with mock.patch.object(_THIS, 'sb', ref_db), mock.patch.object(_THIS, 'ANTHROPIC_API_KEY', ''):
            reps, _ = _quiet(_ref_suppress_repeat_alerts,
                             [i for i in copy.deepcopy(items) if i['urgency'] == '긴급'])
            _quiet(_ref_queue_news_items, ref_db, reps)
        self.assertEqual(rows, ref_db.calls('subscriber_queue', 'insert')[0]['rows'])
        self.assertEqual(db.calls('alert_suppress_log', 'insert')[0]['rows'],
                         ref_db.calls('alert_suppress_log', 'insert')[0]['rows'])
        self.assertEqual(('op_telegram', 1), ev[0])


class TestNewsDedupLimits(unittest.TestCase):
    """R4 ③ — group_same_event의 선택 인자: 기본값이면 종전과 같은 클라이언트(Anthropic(api_key=…)만), 주면 그대로 건다."""

    def _call(self, **kw):
        made = []

        class _Resp:
            content = [mock.Mock(type='text', text='[[1, 2]]')]

        class _Client:
            def __init__(self, **k):
                made.append(k)
                self.messages = mock.Mock(create=mock.Mock(return_value=_Resp()))
        import anthropic
        with mock.patch.object(anthropic, 'Anthropic', _Client):
            got = news_dedup.group_same_event(['가', '나'], 'key', **kw)
        return got, made

    def test_default_client_unchanged(self):
        self.assertEqual(self._call(), ([[0, 1]], [{'api_key': 'key'}]))

    def test_limits_passed(self):
        self.assertEqual(self._call(timeout=20, max_retries=1)[1], [{'api_key': 'key', 'timeout': 20, 'max_retries': 1}])



class TestReviewFollowups(unittest.TestCase):
    """재검토 경미 1·2 — 늦은 판정은 규칙이 등급을 스스로 정했을 때만, 채널 묶음 AI 예산."""

    def _ctx(self, mode, level, source='rule'):
        return {'late_ok': {(2, 'n1'): {'r_s'}},
                'trows': {'n1': {2: {'source': source, 'rule_id': 'r_s'}}},
                'rules_by_id': {'r_s': {'id': 'r_s', 'team_id': 2, 'enabled': True, 'mode': mode, 'level': level}}}

    def test_late_ok_requires_rule_raise(self):
        ok = crawler._aud_late_team_ok
        self.assertTrue(ok(self._ctx('min', '긴급'), 2, 'n1', '보통'))    # 규칙이 올림
        self.assertFalse(ok(self._ctx('min', '보통'), 2, 'n1', '긴급'))   # 관리자가 공통을 올린 뒤 — 규칙은 못 올림
        self.assertFalse(ok(self._ctx('min', '긴급'), 2, 'n1', '긴급'))   # 이미 공통 긴급 — 규칙 몫 아님
        self.assertTrue(ok(self._ctx('set', '긴급'), 2, 'n1', '긴급'))    # set은 규칙이 정함
        self.assertFalse(ok(self._ctx('set', '긴급', source='human'), 2, 'n1', '보통'))
        self.assertFalse(ok(self._ctx('min', '긴급'), 3, 'n1', '보통'))   # 참 판정 없는 팀

    def test_ai_budget_drops_group_fn(self):
        calls = []
        ctx = {'group_fn': lambda titles: calls.append(titles) or None, 'match_fn': lambda new, old: None,
               't0': 0.0, 'window': [], 'window_err': '', 'view': {}, 'stage': 'collect'}
        seen = {}

        def fake_core(items, prior, prior_at, chain, group_fn, log=None, remind_share=None, match_fn=None,
                      sem_titles=None):
            seen['group_fn'] = group_fn
            seen['match_fn'] = match_fn
            seen['remind_share'] = remind_share
            return list(items), [], [], 0
        with mock.patch.object(crawler, '_aud_window', lambda c: []),                 mock.patch.object(crawler, '_audience_chain', lambda a, ch: ({}, set(), True)),                 mock.patch.object(crawler, '_suppress_core', fake_core),                 mock.patch.object(crawler.time, 'monotonic', lambda: crawler.ALERT_AI_BUDGET_S + 1.0):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                crawler._aud_compute(ctx, 't:2', {'team_ids': [2]}, '긴급', [({'url': 'u1', 'title': 't'}, '긴급', [2])])
        self.assertIsNone(seen['group_fn'], '예산을 넘으면 AI 없이')
        self.assertIsNone(seen['match_fn'], '재보도 대조도 AI — 같이 뺀다(#263)')
        self.assertIn('AI 예산', out.getvalue())
        ctx['t0'] = crawler.ALERT_AI_BUDGET_S          # 예산 안
        with mock.patch.object(crawler, '_aud_window', lambda c: []),                 mock.patch.object(crawler, '_audience_chain', lambda a, ch: ({}, set(), True)),                 mock.patch.object(crawler, '_suppress_core', fake_core),                 mock.patch.object(crawler.time, 'monotonic', lambda: crawler.ALERT_AI_BUDGET_S + 1.0):
            crawler._aud_compute(ctx, 't:2', {'team_ids': [2]}, '긴급', [({'url': 'u1', 'title': 't'}, '긴급', [2])])
        self.assertIs(seen['group_fn'], ctx['group_fn'])
        self.assertIs(seen['match_fn'], ctx['match_fn'])


if __name__ == '__main__':
    unittest.main()
