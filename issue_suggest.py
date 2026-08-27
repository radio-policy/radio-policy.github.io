"""
이슈맵 — 자동 제안·단계 전환·휴면 파이프 (2026-08-26 신설, P4).

crawler.py 말미에서 매시 호출된다(try/except 격리 — 실패해도 수집을 죽이지 않는다).
완전 자동 '생성'은 하지 않는다: 후보를 state='proposed'로 만들고 텔레그램 [승인][기각]
버튼(operator-webhook이 처리)으로 운영자가 확정한다. 자동인 것은 ① 기존 이슈에의
기사 연결 ② 발생→현안 단계 전환 ③ 휴면 배지 ④ 90일 종결 '제안'뿐이다.

발제 트리거 2계열(계획 §2):
  ⓐ 뉴스 클러스터 — 최근 7일 긴급·보통 뉴스를 news_dedup.cluster_star로 재클러스터
     (event 라벨은 같은 사건이 6~7개 라벨로 갈라져 신뢰 불가 — 실측).
     기준: 기사 ≥5건 & 날짜 ≥2일, 또는 긴급 ≥3건 & 날짜 ≥3일.
  ⓑ 무보도 규제 — law_diffs urgency='high' 신규 건 + 국회 입법예고(핵심 법령 계열).
     언론이 안 떠들어도 이슈가 되게 한다(운영자 확정 2026-08-26).

중복 억제 3중:
  norm_key 일치 → skip / 임베딩 코사인 ≥0.80 → 신규 제안 대신 기존 active 이슈에
  자동 연결(잠금 포함), rejected와 일치하면 skip(재제안 금지).

비용: 제안 확정 시에만 Haiku 1콜(제목·정의·카테고리). 평시 매시 실행 비용 ≈ 0.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from news_dedup import extract_keywords, cluster_star

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
VOYAGE_API_KEY = os.environ.get('VOYAGE_API_KEY', '')
DASHBOARD_URL = 'https://radio-policy.gitlab.io/'   # 알림 링크는 GitLab 주소(정본) 사용

CLUSTER_MIN_ARTICLES = 5     # ⓐ 기준: 기사 수 & 서로 다른 날짜 수
CLUSTER_MIN_DAYS = 2
URGENT_MIN = 3               # 또는: 긴급 기사 수 & 날짜 수
URGENT_MIN_DAYS = 3
SIM_MERGE = 0.80             # 이 이상이면 확신 연결(Haiku 불요) — 신규 제안 금지
SIM_RELATED = 0.60           # 0.60~0.80은 '관련 후보' — Haiku가 이슈 정의 기준으로 최종 판정.
                             # "유사"가 아니라 "관련"을 잡는다(운영자 교정 2026-08-26):
                             # 표현이 달라도 관련인 기사(예: 3G 이슈의 '심사 착수' 보도)를 놓치지 않게
SIM_PROPOSED_DUP = 0.72      # 제안끼리의 교차 문턱 — 짧은 제목은 유사도가 낮게 나와 0.80로는
                             # 같은 주제 제안이 한 실행에 여럿 통과했다(실측: '모두의 AI' 2건)
MAX_PROPOSALS_PER_RUN = 5    # 1회 실행당 제안 상한 — 첫 가동·급증 시 텔레그램 폭주 방지.
                             # 넘친 후보는 버리는 게 아니라 다음 시간 실행에서 재평가된다.
DORMANT_DAYS = 30
RESOLVE_PROPOSE_DAYS = 90
CATEGORIES = ['주파수', '규제·CR', '사업·서비스', '보안·개인정보', '기타']

# 발생→현안 자동 전환 키워드(계획 §2 — 긴급도 판정 통과 기사 대상 저비용 규칙).
# ①공식 절차는 키워드가 아니라 bill/diff 링크 존재로 판정한다.
_STAGE_SANCTION = re.compile(r'과징금|시정명령|조사\s*착수|제재|처분|고발')
_STAGE_INCIDENT = re.compile(r'유출|해킹|침해|대규모\s*장애|먹통')
_STAGE_LAWSUIT = re.compile(r'판결|패소|승소|상고|항소|행정소송|집행정지')
_CORE_LAW = re.compile(r'전파|전기통신|정보통신|주파수|통신')


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _norm_key(title: str) -> str:
    return '|'.join(sorted(extract_keywords(title))[:6])


def _cosine(a, b):
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5
    db = sum(x * x for x in b) ** 0.5
    return num / (da * db) if da and db else 0.0


def _embed(texts, input_type='query'):
    from embed_util import get_embeddings
    return get_embeddings(texts, input_type=input_type, api_key=VOYAGE_API_KEY)


def _parse_vec(v):
    """supabase가 vector를 문자열('[0.1,...]')로 돌려줄 때 대비."""
    if v is None:
        return None
    if isinstance(v, list):
        return v
    try:
        return json.loads(v)
    except Exception:
        return None


def _haiku_profile(rep_title: str, member_titles: list) -> dict | None:
    """클러스터 → {title, definition, category}. 실패 시 None(제안 보류 — 다음 시간에 재시도)."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        listing = '\n'.join('- ' + t for t in ([rep_title] + member_titles)[:12])
        resp = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
            model='claude-haiku-4-5-20251001', max_tokens=300,
            system=('통신·전파 정책 이슈 관리 보조자다. 같은 사건의 기사 제목들을 보고 '
                    'JSON 하나만 출력한다: {"title": "이슈 제목(25자 이내, 사업자명 포함)", '
                    '"definition": "무엇이 쟁점인지 한 문장", "category": "' + '|'.join(CATEGORIES) + ' 중 하나"}. '
                    'JSON 외 다른 말 금지.'),
            messages=[{'role': 'user', 'content': listing}])
        text = ''.join(b.text for b in resp.content if getattr(b, 'text', None))
        m = re.search(r'\{[\s\S]*\}', text)
        prof = json.loads(m.group(0)) if m else None
        if prof and prof.get('title'):
            if prof.get('category') not in CATEGORIES:
                prof['category'] = '기타'
            return prof
    except Exception as e:
        print(f'  [Haiku 프로필 실패(보류)] {e}')
    return None


def _notify(text, buttons=None):
    from notify import send_telegram
    markup = {'inline_keyboard': [buttons]} if buttons else None
    send_telegram(text, disable_web_page_preview=True, reply_markup=markup)


def _load_issues(sb):
    rows = sb.table('issues').select(
        'id,title,definition,category,state,stage,dormant,norm_key,embedding,stage_log,last_activity_at'
    ).execute().data or []
    for r in rows:
        r['embedding'] = _parse_vec(r.get('embedding'))
    return rows


def _backfill_issue_embeddings(sb, issues, dry):
    """수동 등록 등으로 임베딩이 빈 이슈 보충 — 중복 억제 비교의 전제."""
    todo = [i for i in issues if not i['embedding'] and i['state'] in ('active', 'proposed', 'rejected')]
    if not todo:
        return
    print(f'[이슈 임베딩 백필] {len(todo)}건')
    if dry:
        return
    vecs = _embed([f"{i['title']} {i.get('definition') or ''}" for i in todo], input_type='document')
    for i, v in zip(todo, vecs):
        sb.table('issues').update({'embedding': v}).eq('id', i['id']).execute()
        i['embedding'] = v


def _link_news(sb, issue_id, news_rows, added_by='auto'):
    """기사들을 이슈에 연결 + 잠금 + 최근활동 갱신. 반환: 신규 연결 수."""
    n = 0
    for r in news_rows:
        try:
            sb.table('issue_links').upsert({
                'issue_id': issue_id, 'item_type': 'news', 'item_id': str(r['id']),
                'item_date': (r.get('published_at') or '')[:10] or None,
                'title': r['title'], 'added_by': added_by,
            }, on_conflict='issue_id,item_type,item_id').execute()
            n += 1
        except Exception as e:
            print(f'  [연결 실패(무시)] {e}')
    ids = [str(r['id']) for r in news_rows]
    if ids:
        sb.table('news_feed').update({'locked': True}).in_('id', ids).eq('locked', False).execute()
        sb.table('issues').update({'last_activity_at': _iso(_now())}).eq('id', issue_id).execute()
    return n


_proposed_this_run = 0


def _propose(sb, issues, title, definition, category, norm_key, reason, dry,
             stage_hint='발생', news_rows=None):
    """제안 1건 생성 + 텔레그램 [승인][기각]. 반환: 생성 여부."""
    global _proposed_this_run
    if _proposed_this_run >= MAX_PROPOSALS_PER_RUN:
        print(f'[제안 상한 도달 — 이월] {title}')
        return False
    vec = _embed([f'{title} {definition or ""}'], input_type='document')[0]
    # 같은 실행에서 방금 만든 제안과의 교차 검사 — 스캔 단계(②)는 기존 제안만 보므로
    # 여기서 재검사하지 않으면 한 실행에 같은 주제 제안이 여럿 통과한다(실측: LGU+ 2건).
    for i in issues:
        if i['state'] == 'proposed' and i.get('embedding') \
                and _cosine(vec, i['embedding']) >= SIM_PROPOSED_DUP:
            print(f'[제안 중복 — 건너뜀] {title}  (≈ [{i["id"]}] {i["title"][:20]})')
            return False
    _proposed_this_run += 1
    print(f'[제안] {title}  ({reason.get("kind")}, stage_hint={stage_hint})')
    if dry:
        # dry에서도 가짜 항목을 쌓아 교차 검사가 live와 같게 동작하게 한다
        issues.append({'id': f'dry{_proposed_this_run}', 'title': title, 'state': 'proposed',
                       'stage': stage_hint, 'norm_key': norm_key, 'embedding': vec,
                       'dormant': False, 'stage_log': []})
        return True
    row = sb.table('issues').insert({
        'title': title, 'definition': definition, 'category': category,
        'state': 'proposed', 'stage': stage_hint, 'norm_key': norm_key,
        'proposal_reason': reason, 'source': 'auto', 'embedding': vec,
    }).select('id').execute().data
    iid = row[0]['id'] if row else None
    if not iid:
        return False
    issues.append({'id': iid, 'title': title, 'state': 'proposed', 'stage': stage_hint,
                   'norm_key': norm_key, 'embedding': vec, 'dormant': False, 'stage_log': []})
    if news_rows:
        # 승인 전에도 근거 기사는 연결해 둔다(승인 시 재작업 불필요). 잠금은 승인 후가 원칙이나
        # 60일 삭제 경쟁이 있으므로 여기서 잠근다 — 기각 시 webhook이 잠금을 해제한다.
        _link_news(sb, iid, news_rows, added_by='auto')
    body = (f'📌 이슈 제안: {title}\n'
            f'{definition or ""}\n'
            f'근거: {reason.get("detail", "")}\n{DASHBOARD_URL}')
    _notify(body, buttons=[
        {'text': '✅ 승인', 'callback_data': f'iss|approve|{iid}'},
        {'text': '❌ 기각', 'callback_data': f'iss|reject|{iid}'},
    ])
    return True


def _match_states(issues, norm_key, vec):
    """상태별 최적 매칭. active를 다른 상태와 분리해 계산한다 —
    기각 이슈가 best로 잡히면 후속 기사가 어디에도 안 붙는 구멍(운영자 승인 개선 2)."""
    nk_state = None
    for i in issues:
        if norm_key and i.get('norm_key') == norm_key:
            nk_state = (i['state'], i)
            break
    best_active, sim_active = None, 0.0
    sim_proposed, sim_rejected = 0.0, 0.0
    for i in issues:
        if not i.get('embedding'):
            continue
        sim = _cosine(vec, i['embedding'])
        if i['state'] == 'active':
            if sim > sim_active:
                best_active, sim_active = i, sim
        elif i['state'] == 'proposed':
            sim_proposed = max(sim_proposed, sim)
        elif i['state'] == 'rejected':
            sim_rejected = max(sim_rejected, sim)
    return nk_state, best_active, sim_active, sim_proposed, sim_rejected


def _haiku_relate_batch(pairs, groups):
    """경계(0.60~0.80) 후보를 Haiku 1콜로 일괄 판정.
    pairs: [(cluster_idx, rep_title, candidate_issue)] → 관련 확정된 cluster_idx 집합.
    실패 시 빈 집합(보수적 — 관련이 아니라고 보고 다음 시간에 재평가)."""
    if not pairs or not ANTHROPIC_API_KEY:
        return set()
    try:
        import anthropic
        lines = []
        for k, (ci, title, iss) in enumerate(pairs):
            extra = ' / '.join(r['title'][:40] for r in groups[ci][1:3])
            lines.append(f'{k + 1}. 기사: "{title}"'
                         + (f' (같은 묶음: {extra})' if extra else '')
                         + f'\n   이슈: [{iss["id"]}] {iss["title"]}'
                         + (f' — {iss.get("definition") or ""}' if iss.get('definition') else ''))
        # 관련 판정은 Sonnet(운영자 승인 2026-08-26) — 결과가 영구 잠금·이슈 오염으로 이어지는
        # 고부담 판정이고 시간당 1콜이라 비용 미미. 대량 1차 선별(크롤러)과 다른 비용 구조.
        # Sonnet 5는 temperature를 거부하고 적응형 추론이 기본 ON — thinking을 명시적으로 끈다
        # (판정은 짧은 결정이라 추론 불필요, 켜두면 지연·비용만 늘고 content 파싱이 꼬인다)
        resp = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
            model='claude-sonnet-5', max_tokens=400, thinking={'type': 'disabled'},
            system=('통신·전파 정책 이슈 관리 보조자다. 각 항목의 기사가 짝지어진 이슈에 '
                    '**직접 속하는지**(같은 사건·같은 절차의 후속 보도인지) 판정한다. '
                    '같은 회사·같은 업계·같은 분야라는 이유만으로는 아니오다. 애매하면 아니오다. '
                    # 자유 텍스트에서 숫자를 줍는 파싱은 "1번은 아님" 같은 부정문의 숫자까지 주워
                    # 오연결을 만든다(실측: 무관 클러스터 31건이 잘못 붙을 뻔) — JSON으로 고정.
                    'JSON 하나만 출력한다: {"belong": [속하는 항목 번호]} — 없으면 {"belong": []}. '
                    '다른 말 금지.'),
            messages=[{'role': 'user', 'content': '\n'.join(lines)}])
        text = ''.join(b.text for b in resp.content if getattr(b, 'text', None))
        m = re.search(r'\{[\s\S]*\}', text)
        nums = (json.loads(m.group(0)).get('belong') or []) if m else []
        keep = set()
        for n in nums:
            k = int(n) - 1
            if 0 <= k < len(pairs):
                keep.add(pairs[k][0])
        return keep
    except Exception as e:
        print(f'  [관련 판정 실패(보류)] {e}')
        return set()


# 주간 모음·브리핑류 기사 — 통신 3사 이름이 늘 나열돼 회사명만으로 클러스터 임계(3)를
# 충족하는 오염원. 실측: "[위클리오늘] 이동통신 소식_LG유플러스, SK텔레콤, KT"가 별이 되어
# 진짜 3G 기사를 끌어들인 채 "3G 종료" 중복 제안을 만들었다(이슈 29, 2026-08-27).
# 이슈 제안 입력에서만 제외 — 뉴스 목록·브리핑에는 그대로 남는다.
_DIGEST_RE = re.compile(r'위클리|주간\s*브리핑|\[통신 브리핑\]|소식_|뉴스\s*모음')

def _is_digest(title):
    return bool(_DIGEST_RE.search(title or ''))


def _suggest_from_news(sb, issues, dry):
    since = _iso(_now() - timedelta(days=7))
    rows = sb.table('news_feed') \
        .select('id,title,published_at,urgency') \
        .gte('published_at', since).in_('urgency', ['긴급', '보통']) \
        .order('published_at', desc=True).limit(1000).execute().data or []
    rows = [r for r in rows if not _is_digest(r.get('title'))]
    if not rows:
        return
    clusters = cluster_star(rows)   # 임계 3 유지 — 3→2 금지 가드레일(#44)
    groups = [[rep] + members for rep, members in clusters]

    # 대표 제목 임베딩은 배치 1콜 — 클러스터가 100개여도 호출은 한 번
    reps = [g[0]['title'] for g in groups]
    vecs = _embed(reps)

    borderline = []   # (cluster_idx, rep_title, candidate_issue) — Haiku 관련 판정 대기
    to_propose = []   # (cluster_idx, nk) — 발제 기준 통과 & 어디에도 안 붙은 클러스터
    already = {str(r['item_id']) for r in (sb.table('issue_links').select('item_id')
               .eq('item_type', 'news').execute().data or [])}

    for ci, group in enumerate(groups):
        # 전부 이미 연결된 클러스터는 볼 것 없음 (매시 재스캔의 공회전 방지)
        if all(str(r['id']) in already for r in group):
            continue
        nk = _norm_key(group[0]['title'])
        nk_state, best_active, sim_a, sim_p, sim_r = _match_states(issues, nk, vecs[ci])

        # ⓪ 어휘 직결 — 대표 제목과 active 이슈 제목의 공유 키워드 ≥3이면 판정 없이 연결.
        #    cluster_star와 같은 원칙의 결정적 규칙. AI 경계 판정이 놓친 명백한 후속
        #    ("SK텔레콤·KT, 3G 서비스 종료 추진" ↔ 이슈 "SKT 3G 서비스 종료 추진",
        #     공유 4개)이 중복 제안으로 새는 것을 막는다(2026-08-26 실사고).
        lex_hit = None
        kw_rep = extract_keywords(group[0]['title'])
        for iss in issues:
            if iss['state'] == 'active' and len(kw_rep & extract_keywords(iss['title'])) >= 3:
                lex_hit = iss
                break

        # ① 연결 판정 — 발제 기준과 무관하게 **모든** 클러스터 대상(개선 3):
        #    낱개 후속 기사도 기간과 무관하게 이슈에 붙어야 연대기가 자란다.
        if lex_hit is not None or (nk_state and nk_state[0] == 'active') or sim_a >= SIM_MERGE:
            target = lex_hit or (nk_state[1] if (nk_state and nk_state[0] == 'active') else best_active)
            n = 0 if dry else _link_news(sb, target['id'], group)
            print(f'[연결] "{group[0]["title"][:28]}" → [{target["id"]}] ({len(group)}건, sim {sim_a:.2f})')
            continue
        if best_active is not None and sim_a >= SIM_RELATED:
            borderline.append((ci, group[0]['title'], best_active))
            # 관련 판정 결과를 기다린다 — 판정에서 떨어지면 아래 제안 후보로도 안 간다
            # (관련도 아니고 제안 기준도 못 넘는 어중간한 클러스터는 다음 시간에 재평가)
            continue

        # ② 제안 판정 — 발제 기준 + 제안·기각과의 중복 억제
        if nk_state and nk_state[0] in ('proposed', 'rejected'):
            continue
        if sim_p >= SIM_PROPOSED_DUP or sim_r >= SIM_MERGE:
            continue
        days = {(r.get('published_at') or '')[:10] for r in group if r.get('published_at')}
        urgent = sum(1 for r in group if r.get('urgency') == '긴급')
        if (len(group) >= CLUSTER_MIN_ARTICLES and len(days) >= CLUSTER_MIN_DAYS) or \
           (urgent >= URGENT_MIN and len(days) >= URGENT_MIN_DAYS):
            # 발제 기준을 넘어도 기존 이슈와 조금이라도 닮았으면(≥0.35) 먼저 관련 판정을 받는다 —
            # 짧은 제목은 유사도가 실제 관련성보다 낮게 나와(실측: 3G 후속 0.6 미만),
            # 이 판정 없이는 같은 이슈의 후속이 별도 제안으로 새어 나간다.
            if best_active is not None and sim_a >= 0.35:
                borderline.append((ci, group[0]['title'], best_active))
            to_propose.append((ci, nk))

    # ③ 경계 후보 일괄 관련 판정(Haiku 1콜) → 확정분 연결
    related = _haiku_relate_batch(borderline, groups)
    for ci, title, iss in borderline:
        if ci in related:
            n = 0 if dry else _link_news(sb, iss['id'], groups[ci])
            print(f'[연결·관련판정] "{title[:28]}" → [{iss["id"]}] ({len(groups[ci])}건)')

    # ④ 제안 생성 — 관련 판정으로 기존 이슈에 붙은 클러스터는 제외
    for ci, nk in to_propose:
        if ci in related:
            continue
        group = groups[ci]
        days = {(r.get('published_at') or '')[:10] for r in group if r.get('published_at')}
        urgent = sum(1 for r in group if r.get('urgency') == '긴급')
        prof = _haiku_profile(group[0]['title'], [m['title'] for m in group[1:]])
        if not prof:
            continue
        titles_all = ' '.join(r['title'] for r in group)
        hint = '현안' if (_STAGE_SANCTION.search(titles_all) or _STAGE_INCIDENT.search(titles_all)
                          or _STAGE_LAWSUIT.search(titles_all)) else '발생'
        _propose(sb, issues, prof['title'], prof.get('definition'), prof.get('category', '기타'),
                 nk, {'kind': 'news_cluster', 'cluster_size': len(group), 'urgent_count': urgent,
                      'days': len(days), 'sample_news_ids': [str(r['id']) for r in group[:10]],
                      'detail': f'기사 {len(group)}건 · {len(days)}일 · 긴급 {urgent}'},
                 dry, stage_hint=hint, news_rows=group)


def _reg_dedup(issues, norm_key, vec):
    """규제 계열(법령명 — 고정 명칭이라 고정밀)의 중복 판정. active 우선(개선 2)."""
    nk_state, best_active, sim_a, sim_p, sim_r = _match_states(issues, norm_key, vec)
    if nk_state and nk_state[0] == 'active':
        return ('norm_key', nk_state[1])
    if sim_a >= SIM_MERGE:
        return (f'sim={sim_a:.2f}', best_active)
    if (nk_state and nk_state[0] in ('proposed', 'rejected')) \
            or sim_p >= SIM_PROPOSED_DUP or sim_r >= SIM_MERGE:
        return ('dup', None)
    return (None, None)


def _suggest_from_regs(sb, issues, dry):
    """ⓑ 무보도 규제 — 보도가 없어도 중요 개정·입법예고는 이슈가 된다."""
    since = _iso(_now() - timedelta(days=7))
    linked = {r['item_id'] for r in (sb.table('issue_links').select('item_id')
              .eq('item_type', 'diff').execute().data or [])}
    diffs = sb.table('law_diffs').select('id,law_name,summary,enf_date,diff_kind') \
        .eq('urgency', 'high').gte('created_at', since).execute().data or []
    for d in diffs:
        if str(d['id']) in linked:
            continue
        title = f'{d["law_name"]} 개정'
        nk = _norm_key(title)
        vec = _embed([title + ' ' + (d.get('summary') or '')[:200]])[0]
        skip, target = _reg_dedup(issues, nk, vec)
        if target is not None:
            if not dry:
                sb.table('issue_links').upsert({
                    'issue_id': target['id'], 'item_type': 'diff', 'item_id': str(d['id']),
                    'item_date': _fmt_enf(d.get('enf_date')),
                    'title': f'{d["law_name"]} 개정 ({d.get("diff_kind")})', 'added_by': 'auto',
                }, on_conflict='issue_id,item_type,item_id').execute()
            print(f'[기존 이슈 연결·diff] {title} → [{target["id"]}]')
            continue
        if skip:
            continue
        _propose(sb, issues, title[:60], (d.get('summary') or '')[:120] or None, '규제·CR', nk,
                 {'kind': 'law_diff_high', 'diff_id': d['id'],
                  'detail': f'중요 개정(urgency high) · 시행 {d.get("enf_date") or "?"} — 보도 유무와 무관'},
                 dry, stage_hint='현안')

    bills = sb.table('assembly_bills').select('bill_no,bill_name,notice_end_dt,summary') \
        .not_.is_('notice_end_dt', 'null').gte('notice_end_dt', _now().strftime('%Y-%m-%d')) \
        .execute().data or []
    linked_bills = {r['item_id'] for r in (sb.table('issue_links').select('item_id')
                    .eq('item_type', 'bill').execute().data or [])}
    for b in bills:
        if b['bill_no'] in linked_bills or not _CORE_LAW.search(b.get('bill_name') or ''):
            continue
        nk = _norm_key(b['bill_name'])
        vec = _embed([b['bill_name']])[0]
        skip, target = _reg_dedup(issues, nk, vec)
        if target is not None:
            if not dry:
                sb.table('issue_links').upsert({
                    'issue_id': target['id'], 'item_type': 'bill', 'item_id': b['bill_no'],
                    'item_date': (b.get('notice_end_dt') or '')[:10] or None,
                    'title': b['bill_name'], 'added_by': 'auto',
                }, on_conflict='issue_id,item_type,item_id').execute()
            print(f'[기존 이슈 연결·bill] {b["bill_name"][:30]} → [{target["id"]}]')
            continue
        if skip:
            continue
        _propose(sb, issues, b['bill_name'][:60], (b.get('summary') or '')[:120] or None, '규제·CR', nk,
                 {'kind': 'assembly_notice', 'bill_no': b['bill_no'],
                  'detail': f'국회 입법예고 · 의견 마감 {b.get("notice_end_dt")}'},
                 dry, stage_hint='현안')


def _fmt_enf(enf):
    s = re.sub(r'\D', '', enf or '')
    return f'{s[:4]}-{s[4:6]}-{s[6:8]}' if len(s) >= 8 else None


def _stage_and_dormancy(sb, issues, dry):
    """발생→현안 자동 전환 / 휴면 배지 / 90일 종결 제안."""
    now = _now()
    for i in issues:
        if i['state'] != 'active':
            continue
        # 휴면 판정 기준은 last_activity_at(콘텐츠의 날짜)가 아니라 **링크가 실제로 추가된 시각**.
        # 과거 기사를 보강하면 item_date는 옛날이지만 이슈는 방금 활동한 것이다 — 혼동하면
        # 만든 당일 이슈가 '36일 무활동'으로 오판된다(dry-run 실측).
        recent = sb.table('issue_links').select('created_at').eq('issue_id', i['id']) \
            .order('created_at', desc=True).limit(1).execute().data
        last_touch = (recent[0]['created_at'] if recent else None) or i.get('last_activity_at')
        last_dt = datetime.fromisoformat(last_touch.replace('Z', '+00:00')) if last_touch else now
        log = i.get('stage_log') or []

        # 발생→현안: ①절차(bill/diff 링크) ②제재 ③사고 ④소송 키워드(최근 연결 기사 제목)
        if i['stage'] == '발생':
            links = sb.table('issue_links').select('item_type,title,item_date') \
                .eq('issue_id', i['id']).execute().data or []
            signal = None
            if any(l['item_type'] in ('bill', 'diff') for l in links):
                signal = '공식 절차(법안/개정) 연결'
            else:
                recent = ' '.join((l.get('title') or '') for l in links
                                  if l['item_type'] == 'news' and (l.get('item_date') or '') >= (now - timedelta(days=30)).strftime('%Y-%m-%d'))
                if _STAGE_SANCTION.search(recent):
                    signal = '제재·처분 키워드 감지'
                elif _STAGE_INCIDENT.search(recent):
                    signal = '침해·장애 사건 키워드 감지'
                elif _STAGE_LAWSUIT.search(recent):
                    signal = '소송·판결 키워드 감지'
            if signal:
                print(f'[현안 전환] [{i["id"]}] {i["title"][:24]} — {signal}')
                if not dry:
                    log = log + [{'at': _iso(now), 'from': '발생', 'to': '현안', 'signal': signal}]
                    sb.table('issues').update({'stage': '현안', 'stage_log': log,
                                               'updated_at': _iso(now)}).eq('id', i['id']).execute()
                    _notify(f'⚠️ 이슈 현안 전환: {i["title"]}\n신호: {signal}\n{DASHBOARD_URL}')
                i['stage'], i['stage_log'] = '현안', log

        # 휴면 배지 (가역)
        idle_days = (now - last_dt).days
        if i['stage'] != '해소':
            if idle_days >= DORMANT_DAYS and not i.get('dormant'):
                print(f'[휴면] [{i["id"]}] {i["title"][:24]} ({idle_days}일 무활동)')
                if not dry:
                    sb.table('issues').update({'dormant': True}).eq('id', i['id']).execute()
                i['dormant'] = True
            elif idle_days < DORMANT_DAYS and i.get('dormant'):
                print(f'[휴면 해제] [{i["id"]}] {i["title"][:24]}')
                if not dry:
                    sb.table('issues').update({'dormant': False}).eq('id', i['id']).execute()
                i['dormant'] = False

        # 90일 종결 제안 — 재발송 방지: stage_log의 resolve_proposed 마커 30일 쿨다운
        if i.get('dormant') and idle_days >= RESOLVE_PROPOSE_DAYS and i['stage'] != '해소':
            recent_prop = [e for e in log if e.get('type') == 'resolve_proposed'
                           and e.get('at', '') >= _iso(now - timedelta(days=30))]
            if not recent_prop:
                print(f'[종결 제안] [{i["id"]}] {i["title"][:24]} ({idle_days}일)')
                if not dry:
                    log = log + [{'at': _iso(now), 'type': 'resolve_proposed'}]
                    sb.table('issues').update({'stage_log': log}).eq('id', i['id']).execute()
                    _notify(f'🕊️ 종결 제안: {i["title"]}\n{idle_days}일째 새 항목이 없습니다. '
                            f'\'자연 소멸\'로 해소할까요?\n{DASHBOARD_URL}',
                            buttons=[{'text': '🕊️ 자연 소멸로 해소', 'callback_data': f'iss|resolve|{i["id"]}'},
                                     {'text': '유지', 'callback_data': f'iss|keep|{i["id"]}'}])


def run_suggest(sb, dry: bool = False):
    print(f'[이슈 제안 파이프] 시작 (dry={dry})')
    issues = _load_issues(sb)
    try:
        _backfill_issue_embeddings(sb, issues, dry)
    except Exception as e:
        print(f'[이슈 임베딩 백필 실패(계속)] {e}')
    for step, fn in (('뉴스 클러스터', _suggest_from_news),
                     ('무보도 규제', _suggest_from_regs),
                     ('단계·휴면', _stage_and_dormancy)):
        try:
            fn(sb, issues, dry)
        except Exception as e:
            print(f'[{step} 단계 실패(다음 단계 계속)] {e}')
    print('[이슈 제안 파이프] 완료')


def main():
    ap = argparse.ArgumentParser(description='이슈맵 자동 제안 파이프')
    ap.add_argument('--dry-run', action='store_true', help='DB·텔레그램 무변경, 판정만 출력')
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    global ANTHROPIC_API_KEY, VOYAGE_API_KEY
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
    VOYAGE_API_KEY = os.environ.get('VOYAGE_API_KEY', '')
    from sb_client import make_client
    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    run_suggest(sb, dry=args.dry_run)


if __name__ == '__main__':
    main()
