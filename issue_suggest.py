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

중복 억제 3중(뉴스 클러스터):
  norm_key 일치 → skip / 임베딩 코사인 ≥0.80 → 신규 제안 대신 기존 active 이슈에
  자동 연결(잠금 포함), proposed·rejected와 ≥0.72면 skip(재제안 금지 — 기각도
  0.72를 쓴다, 0.80은 클러스터 벡터 특성상 새는 것 실측 2026-09-03).
  제안 직전 생성 제목·정의 벡터로 한 번 더: active ≥0.80 → 연결, 그다음 rejected ≥0.80 → skip(#206).
  묶음 기사 과반이 한 active 이슈에 이미 붙어 있으면 그 이슈로 연결, 과반 미달이어도 3건(OVERLAP_JUDGE_MIN)
  이상이면 제안하지 않고 그 이슈와 관련 판정(#243). 세션이 기각하며 다른 이슈로 합친 제안
  (proposal_reason.merged_into)과 같은 주제면 skip하지 않고 합친 곳과 관련 판정(#243).

규제 계열(법안·DIFF)은 법령 이름을 동일성 열쇠로 쓰지 않는다(#231, 2026-09-26):
  ① 번호 — 같은 의안번호·국회 개정안 조문대비↔그 법안·같은 공포번호면 같은 항목(active는 연결, 대기·기각은 skip)
  ② 요약 내용 벡터 — active ≥0.80 연결(배제 기준 이슈는 판정), proposed·rejected ≥0.72 skip
  ③ active와 0.40~0.80이면 Sonnet 관련 판정 → 속하면 연결, 아니면 제안
  ④ 제안 제목은 Haiku 주제형(법령명만의 제목 금지 — 승인 시 과거 뉴스 검색어가 된다)

비용: 제안 확정 시에만 Haiku 1콜(제목·정의·카테고리). 평시 매시 실행 비용 ≈ 0.
"""

import argparse
import json
import os
import api_usage; api_usage.install()   # Anthropic usage 기록(#152) — 호출부 무변경, fail-open
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from news_dedup import extract_keywords, cluster_star

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
VOYAGE_API_KEY = os.environ.get('VOYAGE_API_KEY', '')
DASHBOARD_URL = 'https://radio-policy.github.io/?p=issuemap'   # 알림 링크는 GitHub 주소(정본) 사용 — 압축·인천 캐시로 GitLab보다 빠르다(#170-보론5)

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
SIM_REJECTED_REPROPOSE = 0.80  # 생성 제목·정의 벡터 기준 기각 재제안 문턱(#206). 실측 2026-09-24:
                             # 재제안 3건 0.853~0.861, 활성·대기 이슈 vs 그보다 먼저 기각된 이슈 최대 0.716
OVERLAP_JUDGE_MIN = 3        # 과반 미달이어도 묶음 기사 이만큼이 한 active 이슈에 이미 연결돼 있으면 제안하지 않고
                             # 그 이슈와 관련 판정(#243). 실측 2026-09-26(지난 30일 매일 20시 재현): 과반 미달·겹침 ≥3
                             # 묶음 근처에서 나온 제안 21건 전부 기각(승인 0) — #199(8/26 ↔ #171)·#196(7/20 ↔ #5)·
                             # #194(6/17 ↔ #46)·#174(3/8 ↔ #119). 2건 겹침은 44·65건짜리 뒤섞인 묶음에도 흔해 뺀다.
SIM_REG_RELATED = 0.40       # 규제 항목(법안·DIFF) 요약 벡터가 active 이슈와 이 이상·SIM_MERGE 미만이면 Sonnet
                             # 관련 판정(#231). 실측 2026-09-26: 실제 소속 0.49~0.67(2220816→#119 0.49,
                             # diff 70→#51 0.60, diff 6→#121 0.67), 무관 0.33~0.45 — 문턱 아래는 판정 없이 제안으로 간다.
                             # 같은 법·다른 내용끼리는 요약 벡터 0.29~0.62, 기각 이슈 vs 원래 법안 0.86~0.88
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

# 제안하지 않는 유형 — 기각 105건의 다수를 차지한 홍보·행사성 보도(#161-보론3).
# 실측(2026-09): 서울세계불꽃축제 통신망 지원이 제안 8건, 피지컬 AI·AI-RAN 실증 5건,
# GSMA 참석 2건, 아이폰 사전예약 혜택 2건 — 전부 운영자가 기각했다.
_NON_ISSUE = re.compile(
    r'불꽃축제|축제|행사장|실증|시연|테스트베드|PoC|MOU|업무협약|맞손|파트너십|'
    r'협력\s*강화|컨소시엄\s*구성|참가|참석|컨퍼런스|포럼|전시회|GSMA|MWC|CES|'
    r'인재\s*확보|채용|조직\s*개편|자회사\s*협업|그룹사\s*연계|'
    r'사전예약|프로모션|혜택\s*경쟁|이벤트|출시\s*기념|수상|우수사례|공모전|시상')
# 위 낱말이 있어도 제도가 걸려 있으면 제안을 막지 않는다(홍보 기사와 정책 기사의 경계).
_POLICY_SIGNAL = re.compile(
    r'법률|법안|시행령|시행규칙|고시|개정|제정|입법|국회|상임위|과방위|'
    r'과징금|시정명령|제재|처분|조사\s*착수|고발|소송|판결|'
    r'주파수\s*(?:할당|재할당|경매|회수|대가)|의결|행정지도|규제|의무화|'
    r'국책\s*사업|사업자?\s*선정|공모\s*결과|예산\s*편성')


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _norm_key(title: str) -> str:
    return '|'.join(sorted(extract_keywords(title))[:6])


# 법령 이름뿐인 제목 — 승인 시 과거 뉴스 검색어가 되면 그 법의 온갖 기사를 끌어온다(#198 실측: 법령명 검색
# 후보 150건 중 주제 기사 0건, 주제형 제목은 23건 중 9건). 끝이 '…법·령·규칙·고시·규정 (일부|전부)개정·제정(안)'이고
# 주제 구분자(—·:·,)가 없는 제목, 또는 정식 명칭('…에 관한 법률')을 담은 제목(#231).
_LAW_ONLY_TITLE_RE = re.compile(
    r'^[^—–:,]*?(?:법|법률|령|규칙|고시|규정)\s*(?:일부|전부)?\s*(?:개정|제정)(?:법률안|령안|안)?\s*$')


def _is_law_only_title(title: str, law_name: str = '') -> bool:
    t = (title or '').strip()
    flat = re.sub(r'\s+', '', t)
    if not flat:
        return True
    ln = re.sub(r'\s+', '', law_name or '')
    if ln and flat in (ln, ln + '개정', ln + '개정안', ln + '일부개정법률안'):
        return True
    return bool(_LAW_ONLY_TITLE_RE.search(t)) or '에관한법률' in flat


def _fetch_all(build):
    """PostgREST 1,000행 절단 대비 전량 페이징 — build()가 정렬을 포함한 새 쿼리를 만든다(정렬 없는 range는 행을 흘린다)."""
    out, ofs = [], 0
    while True:
        page = build().range(ofs, ofs + 999).execute().data or []
        out.extend(page)
        if len(page) < 1000:
            return out
        ofs += 1000


def _has_exclusion(iss):
    """정의문에 배제 기준("해당 없음")이 있는 이슈 — 어휘 직결·유사도 0.80·과반 겹침 같은
    결정적 연결로 붙이지 않고 관련 판정(정의문을 읽는 유일한 경로)을 거친다. 배제 기준을
    넣어도 세 경로가 정의문을 안 봐서 #9(GSMA 행사 50건)·#30(불꽃축제 53건)이 재오염된
    실측(2026-09-12, #157)."""
    return '해당 없음' in ((iss or {}).get('definition') or '')


def _merge_target(iss, by_id):
    """세션이 기각하며 합친 곳(proposal_reason.merged_into)을 따라가 active 이슈를 돌려준다(#243).
    합친 곳이 없거나 active가 아니면 None — 그때는 종전대로 기각 재제안 금지만 한다."""
    cur, seen = iss, {iss.get('id')}
    for _ in range(5):
        mi = (cur.get('proposal_reason') or {}).get('merged_into')
        if mi in (None, ''):
            return None
        try:
            cur = by_id.get(int(mi))
        except (TypeError, ValueError):
            return None
        if cur is None or cur.get('id') in seen:
            return None
        if cur.get('state') == 'active':
            return cur
        seen.add(cur.get('id'))
    return None


def _merged_hit(issues, by_id, vec, norm_key=None, kw_rep=None):
    """합친 곳이 있는 기각 이슈 중 이 후보와 같은 주제로 보이는 것 → (기각 이슈, 합친 active 이슈), 없으면 None.
    같은 주제 = norm_key 일치·벡터 ≥SIM_PROPOSED_DUP·제목 어휘 3개 이상 공유(kw_rep를 줄 때만) — 기각 재제안을
    막는 세 대조와 같은 잣대. 여럿이면 벡터가 가장 가까운 것."""
    best, best_sim = None, -1.0
    for i in issues:
        if i.get('state') != 'rejected' or not (i.get('proposal_reason') or {}).get('merged_into'):
            continue
        sim = _cosine(vec, i['embedding']) if (vec and i.get('embedding')) else 0.0
        if (norm_key and i.get('norm_key') == norm_key) or sim >= SIM_PROPOSED_DUP \
                or (kw_rep and len(kw_rep & extract_keywords(i['title'])) >= 3):
            tgt = _merge_target(i, by_id)
            if tgt is not None and sim > best_sim:
                best, best_sim = (i, tgt), sim
    return best


def _clip_sentence(text, limit=500):
    """정의문 절단은 문장 경계에서 — [:120] 하드컷이 "…실질적 제"처럼 화면에 남았다(#129-보론).
    limit 안의 마지막 '다.'까지 취하고, 문장 종결이 너무 앞이면 하드컷 폴백."""
    t = (text or '').strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    idx = cut.rfind('다.')
    if idx >= limit // 3:
        return cut[:idx + 2]
    return cut


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
    # 이슈맵 메시지는 무음 — 운영자봇 소리는 긴급 뉴스·워치독 몫으로 남긴다(운영자 지시 2026-09-01)
    send_telegram(text, disable_web_page_preview=True, disable_notification=True,
                  reply_markup=markup)


def _load_issues(sb):
    # 전량 페이징 — 기각 이슈가 하루 수 건씩 쌓여 1,000행을 넘는 날 오래된 기각분이 조용히 빠지면
    # 재제안 억제가 풀린다. proposal_reason은 규제 항목 동일성(의안번호·diff_id)의 근거(#231).
    rows = _fetch_all(lambda: sb.table('issues').select(
        'id,title,definition,category,state,stage,dormant,norm_key,embedding,stage_log,last_activity_at,'
        'proposal_reason').order('id'))
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


def _link_reg(sb, issue_id, link):
    """법안·DIFF를 이슈에 연결 — link: {item_type, item_id, item_date, title}. 중복은 upsert가 흡수한다."""
    sb.table('issue_links').upsert({'issue_id': issue_id, **link, 'added_by': 'auto'},
                                   on_conflict='issue_id,item_type,item_id').execute()


def _propose(sb, issues, title, definition, category, norm_key, reason, dry,
             stage_hint='발생', news_rows=None, link_item=None):
    """제안 1건 생성 + 텔레그램 [승인][기각]. 반환: 만든 이슈 id(dry면 'dryN'), 만들지 않았으면 False.
    link_item: 규제 계열의 근거 법안·DIFF 링크(#231) — 제안과 함께 연결해 두고(기각 시 webhook이 지운다),
    병합 재검사로 기존 이슈에 붙을 때는 그 이슈에 연결한다."""
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
    # 생성 제목 재검사 — 매칭은 지저분한 클러스터 대표 제목으로 하지만, 여기서 만든 제목·정의는
    # 깨끗해서 유사도가 제대로 나온다(실측: 제안 25가 대표 기준으론 경계, 생성 기준 0.887).
    # 병합선을 넘으면 제안 대신 그 이슈로 연결한다.
    for i in issues:
        if i['state'] == 'active' and i.get('embedding') \
                and _cosine(vec, i['embedding']) >= SIM_MERGE:
            if link_item and _has_exclusion(i):
                # 배제 기준 이슈에는 결정적 연결을 하지 않는다(#157) — 규제 항목은 판정 경로(③)에서만 붙는다
                print(f'[제안→병합 재검사] "{title}" ≈ active [{i["id"]}] {i["title"][:20]} — 배제 기준 이슈라 '
                      f'연결·제안 모두 보류(세션 확인)')
                return False
            print(f'[제안→병합 재검사] "{title}" ≈ active [{i["id"]}] {i["title"][:20]} — 제안 대신 연결')
            if not dry and news_rows:
                _link_news(sb, i['id'], news_rows, added_by='auto')
            if not dry and link_item:
                _link_reg(sb, i['id'], link_item)
            return False
    # 기각 재제안 재검사(#206) — 클러스터 단계의 기각 대조(대표 제목 벡터 0.72·어휘 3개)는
    # 지저분한 대표 제목 탓에 새는데, 생성 제목은 기각 이슈와 거의 같게 나온다(실측: 9/24 10:29 기각분이
    # 11:02 실행에서 0.853~0.861로 재제안). active 병합 검사 뒤에 둬야 활성 이슈 후속이 기각에 막히지 않는다.
    rej, rej_sim = None, 0.0
    for i in issues:
        if i['state'] == 'rejected' and i.get('embedding'):
            sim = _cosine(vec, i['embedding'])
            if sim >= SIM_REJECTED_REPROPOSE and sim > rej_sim:
                rej, rej_sim = i, sim
    if rej is not None:
        # 합친 기각(#243) — 세션이 다른 active 이슈로 합친 제안이면 그 후속은 건너뛰지 말고 합친 곳에 판정 연결.
        # 종전엔 여기서 조용히 빠져 합친 이슈에 후속 보도가 쌓이지 않았다. 판정은 이 한 건만 즉석 1콜(드묾).
        tgt = _merge_target(rej, {x['id']: x for x in issues})
        if tgt is not None:
            if link_item:
                ok = _haiku_relate_batch([(0, f'{title} — {definition or ""}'[:400], tgt)], None, kind='reg')
            else:
                ok = _haiku_relate_batch([(0, title, tgt)], [news_rows or []])
            if ok and 0 in ok:
                print(f'[기각 병합처 연결] "{title}" ≈ 기각 [{rej["id"]}] ({rej_sim:.3f}) → 합친 곳 '
                      f'[{tgt["id"]}] {tgt["title"][:20]}')
                if not dry and news_rows:
                    _link_news(sb, tgt['id'], news_rows, added_by='auto')
                if not dry and link_item:
                    _link_reg(sb, tgt['id'], link_item)
                return False
            print(f'[기각 재제안 — 건너뜀] {title}  (≈ [{rej["id"]}] {rej["title"][:20]}, {rej_sim:.3f}; '
                  f'합친 곳 [{tgt["id"]}] 판정 {"실패(보류)" if ok is None else "소속 아님"})')
            return False
        print(f'[기각 재제안 — 건너뜀] {title}  (≈ [{rej["id"]}] {rej["title"][:20]}, {rej_sim:.3f})')
        return False
    _proposed_this_run += 1
    print(f'[제안] {title}  ({reason.get("kind")}, stage_hint={stage_hint})')
    if dry:
        # dry에서도 가짜 항목을 쌓아 교차 검사가 live와 같게 동작하게 한다
        issues.append({'id': f'dry{_proposed_this_run}', 'title': title, 'state': 'proposed',
                       'stage': stage_hint, 'norm_key': norm_key, 'embedding': vec,
                       'dormant': False, 'stage_log': [], 'proposal_reason': reason})
        return f'dry{_proposed_this_run}'
    row = sb.table('issues').insert({
        'title': title, 'definition': definition, 'category': category,
        'state': 'proposed', 'stage': stage_hint, 'norm_key': norm_key,
        'proposal_reason': reason, 'source': 'auto', 'embedding': vec,
    }).select('id').execute().data
    iid = row[0]['id'] if row else None
    if not iid:
        return False
    issues.append({'id': iid, 'title': title, 'state': 'proposed', 'stage': stage_hint,
                   'norm_key': norm_key, 'embedding': vec, 'dormant': False, 'stage_log': [],
                   'proposal_reason': reason})
    if news_rows:
        # 승인 전에도 근거 기사는 연결해 둔다(승인 시 재작업 불필요). 잠금은 승인 후가 원칙이나
        # 60일 삭제 경쟁이 있으므로 여기서 잠근다 — 기각 시 webhook이 잠금을 해제한다.
        _link_news(sb, iid, news_rows, added_by='auto')
    if link_item:
        # 근거 법안·DIFF도 제안과 함께 연결 — 종전엔 승인 뒤 다음 실행의 이름표 일치로만 붙어,
        # 제목을 고친 이슈는 제 법안을 영영 못 찾았다(#231)
        _link_reg(sb, iid, link_item)
    body = (f'📌 이슈 제안: {title}\n'
            f'{definition or ""}\n'
            f'근거: {reason.get("detail", "")}\n{DASHBOARD_URL}')
    _notify(body, buttons=[
        {'text': '✅ 승인', 'callback_data': f'iss|approve|{iid}'},
        {'text': '❌ 기각', 'callback_data': f'iss|reject|{iid}'},
    ])
    return iid


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


def _haiku_relate_batch(pairs, groups, kind='news'):
    """경계(0.60~0.80) 후보를 Sonnet 1콜로 일괄 판정.
    pairs: [(idx, 제목·내용, candidate_issue)] → 관련 확정된 idx 집합.
    kind='news'(뉴스 클러스터): 실패 시 빈 집합(보수적 — 관련이 아니라고 보고 다음 시간에 재평가).
    kind='reg'(법안·DIFF, #231): 실패·파싱 불가면 None — 판정 대상은 '관련 없음'이면 곧장 제안으로 가므로,
    실패를 '관련 없음'과 구별해 호출부가 다음 실행으로 미룬다."""
    fail = set() if kind == 'news' else None
    if not pairs:
        return set()
    if not ANTHROPIC_API_KEY:
        return fail
    try:
        import anthropic
        lines = []
        for k, (ci, title, iss) in enumerate(pairs):
            if kind == 'reg':
                lines.append(f'{k + 1}. 법안·개정: "{title}"'
                             + f'\n   이슈: [{iss["id"]}] {iss["title"]}'
                             + (f' — {iss.get("definition") or ""}' if iss.get('definition') else ''))
                continue
            extra = ' / '.join(r['title'][:40] for r in groups[ci][1:3])
            lines.append(f'{k + 1}. 기사: "{title}"'
                         + (f' (같은 묶음: {extra})' if extra else '')
                         + f'\n   이슈: [{iss["id"]}] {iss["title"]}'
                         + (f' — {iss.get("definition") or ""}' if iss.get('definition') else ''))
        if kind == 'reg':
            system = ('통신·전파 정책 이슈 관리 보조자다. 각 항목의 법안·개정이 짝지어진 이슈에 '
                      '**직접 속하는지**(그 이슈가 다루는 제도·사건의 입법·개정·하위법령인지) 판정한다. '
                      '이슈 정의문에 "해당 없음"으로 적힌 범위면 아니오다. '
                      '같은 법령·같은 분야라는 이유만으로는 아니오다. 애매하면 아니오다. '
                      'JSON 하나만 출력한다: {"belong": [속하는 항목 번호]} — 없으면 {"belong": []}. '
                      '다른 말 금지.')
        else:
            system = ('통신·전파 정책 이슈 관리 보조자다. 각 항목의 기사가 짝지어진 이슈에 '
                      '**직접 속하는지**(같은 사건·같은 절차의 후속 보도인지) 판정한다. '
                      '같은 회사·같은 업계·같은 분야라는 이유만으로는 아니오다. 애매하면 아니오다. '
                      # 자유 텍스트에서 숫자를 줍는 파싱은 "1번은 아님" 같은 부정문의 숫자까지 주워
                      # 오연결을 만든다(실측: 무관 클러스터 31건이 잘못 붙을 뻔) — JSON으로 고정.
                      'JSON 하나만 출력한다: {"belong": [속하는 항목 번호]} — 없으면 {"belong": []}. '
                      '다른 말 금지.')
        # 관련 판정은 Sonnet(운영자 승인 2026-08-26) — 결과가 영구 잠금·이슈 오염으로 이어지는
        # 고부담 판정이고 시간당 1콜이라 비용 미미. 대량 1차 선별(크롤러)과 다른 비용 구조.
        # Sonnet 5는 temperature를 거부하고 적응형 추론이 기본 ON — thinking을 명시적으로 끈다
        # (판정은 짧은 결정이라 추론 불필요, 켜두면 지연·비용만 늘고 content 파싱이 꼬인다)
        resp = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
            model='claude-sonnet-5', max_tokens=400, thinking={'type': 'disabled'},
            system=system,
            messages=[{'role': 'user', 'content': '\n'.join(lines)}])
        text = ''.join(b.text for b in resp.content if getattr(b, 'text', None))
        m = re.search(r'\{[\s\S]*\}', text)
        if kind == 'reg' and (not m or getattr(resp, 'stop_reason', None) == 'max_tokens'):
            print(f'  [관련 판정 응답 불가(보류)] {text[:80]!r}')
            return None
        nums = (json.loads(m.group(0)).get('belong') or []) if m else []
        keep = set()
        for n in nums:
            k = int(n) - 1
            if 0 <= k < len(pairs):
                keep.add(pairs[k][0])
        return keep
    except Exception as e:
        print(f'  [관련 판정 실패(보류)] {e}')
        return fail


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
    # 기사→연결 이슈 지도. PostgREST 1,000행 절단 대비 페이징(가드레일 — 링크가 이미 700행대).
    linked_to = {}
    _ofs = 0
    while True:
        _page = (sb.table('issue_links').select('item_id,issue_id').eq('item_type', 'news')
                 .order('id').range(_ofs, _ofs + 999).execute().data or [])
        for r in _page:
            linked_to.setdefault(str(r['item_id']), set()).add(r['issue_id'])
        if len(_page) < 1000:
            break
        _ofs += 1000
    already = set(linked_to)
    active_ids = {i['id'] for i in issues if i['state'] == 'active'}
    by_id = {i['id']: i for i in issues}

    for ci, group in enumerate(groups):
        # 전부 이미 연결된 클러스터는 볼 것 없음 (매시 재스캔의 공회전 방지)
        if all(str(r['id']) in already for r in group):
            continue
        # 과반 겹침 가드 — 멤버 과반이 이미 같은 active 이슈에 연결돼 있으면 그 이슈의
        # 후속 흐름이다. 임베딩(짧은 제목이라 0.6대로 낮게 나옴)·AI 판정보다 앞서는 결정적
        # 신호라 제안 경로를 원천 차단하고 미연결분만 그 이슈로 붙인다.
        # (무임승차 거품 하루 4건 실측: 제안 25·29·32·33, 2026-08-27)
        _cnt = Counter(iid for r in group for iid in linked_to.get(str(r['id']), ()) if iid in active_ids)
        _top_iss, _top_n = _cnt.most_common(1)[0] if _cnt else (None, 0)
        if _cnt:
            # 겹침 최소 2건 — 2건짜리 클러스터의 1건 겹침(1/2)까지 무판정 연결하면 과확장
            if _top_n >= 2 and _top_n * 2 >= len(group):
                _fresh = [r for r in group if _top_iss not in linked_to.get(str(r['id']), ())]
                if _has_exclusion(by_id.get(_top_iss)):
                    # 오염이 오염을 부르는 증폭 경로 — 배제 기준 이슈는 판정을 받고 붙는다
                    borderline.append((ci, group[0]['title'], by_id[_top_iss]))
                    print(f'[과반겹침→판정] "{group[0]["title"][:28]}" → [{_top_iss}] (배제 기준 이슈)')
                    continue
                if _fresh and not dry:
                    _link_news(sb, _top_iss, _fresh)
                print(f'[연결·과반겹침] "{group[0]["title"][:28]}" → [{_top_iss}] '
                      f'(겹침 {_top_n}/{len(group)}, 신규 {len(_fresh)}건)')
                continue
        nk = _norm_key(group[0]['title'])
        nk_state, best_active, sim_a, sim_p, sim_r = _match_states(issues, nk, vecs[ci])
        titles_all = ' '.join(r['title'] for r in group)

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
            if _has_exclusion(target):
                borderline.append((ci, group[0]['title'], target))
                print(f'[직결→판정] "{group[0]["title"][:28]}" → [{target["id"]}] (배제 기준 이슈)')
                continue
            n = 0 if dry else _link_news(sb, target['id'], group)
            print(f'[연결] "{group[0]["title"][:28]}" → [{target["id"]}] ({len(group)}건, sim {sim_a:.2f})')
            continue
        # ①-2 겹침 판정(#243) — 과반은 못 돼도 묶음 기사 OVERLAP_JUDGE_MIN건 이상이 한 active 이슈에 이미 붙어
        #    있으면 그 이슈의 후속 물결이다. 대표 제목이 낚시형이면 대표 벡터(0.28)도 생성 제목 재검사(0.664 — 세션이
        #    승인하며 제목·정의를 넓혀 벡터가 원래 보도에서 멀어졌다)도 놓쳐 중복 제안이 됐다(#199: 26건 중 8건이
        #    #171에 연결돼 있었다). 제안하지 않고 그 이슈와 관련 판정만 — 떨어지면 다음 실행에서 다시 본다(아래 경계 후보와 같다).
        if _top_n >= OVERLAP_JUDGE_MIN:
            borderline.append((ci, group[0]['title'], by_id[_top_iss]))
            print(f'[겹침→판정] "{group[0]["title"][:28]}" → [{_top_iss}] (겹침 {_top_n}/{len(group)})')
            continue
        if best_active is not None and sim_a >= SIM_RELATED:
            borderline.append((ci, group[0]['title'], best_active))
            # 관련 판정 결과를 기다린다 — 판정에서 떨어지면 아래 제안 후보로도 안 간다
            # (관련도 아니고 제안 기준도 못 넘는 어중간한 클러스터는 다음 시간에 재평가)
            continue

        # ②-0 합친 기각(#243) — 세션이 기각하며 다른 active 이슈로 합친 제안(proposal_reason.merged_into)과 같은
        #    주제면 아래 기각 대조에 막혀 어디에도 안 붙고 조용히 빠지던 것을, 합친 곳과 관련 판정으로 돌린다.
        #    어휘 3개 대조는 아래 파편 대조처럼 제도 신호가 없을 때만(정책 이슈가 기각 파편 어휘에 막히지 않게).
        _mh = _merged_hit(issues, by_id, vecs[ci], nk,
                          None if _POLICY_SIGNAL.search(titles_all) else kw_rep)
        if _mh is not None:
            borderline.append((ci, group[0]['title'], _mh[1]))
            print(f'[기각 병합처→판정] "{group[0]["title"][:28]}" ≈ 기각 [{_mh[0]["id"]}] → 합친 곳 [{_mh[1]["id"]}]')
            continue

        # ② 제안 판정 — 발제 기준 + 제안·기각과의 중복 억제
        if nk_state and nk_state[0] in ('proposed', 'rejected'):
            continue
        # 기각 재제안도 0.72로 막는다 — 클러스터 벡터는 최종 이슈 벡터보다 유사도가
        # 낮게 나와 0.80으로는 새는 것을 실측(기각 #57~59가 하루 만에 0.84~0.92짜리
        # 쌍둥이 #65~67로 재제안, 2026-09-03)
        if sim_p >= SIM_PROPOSED_DUP or sim_r >= SIM_PROPOSED_DUP:
            continue
        days = {(r.get('published_at') or '')[:10] for r in group if r.get('published_at')}
        urgent = sum(1 for r in group if r.get('urgency') == '긴급')
        # 홍보·행사성 차단 — 제도 신호가 없으면 아무리 많이 보도돼도 이슈가 아니다(#161-보론3).
        # 연결 경로(⓪·①·과반겹침)는 이미 위에서 끝났으므로 여기서 막아도 기존 이슈의 후속은 안 잃는다.
        if _NON_ISSUE.search(titles_all) and not _POLICY_SIGNAL.search(titles_all):
            print(f'[제안 보류 — 홍보·행사성] "{group[0]["title"][:30]}"')
            continue
        # 기존 제안·기각 제목과 어휘가 3개 이상 겹치면 같은 사건의 파편이다.
        # 임베딩 교차(SIM_PROPOSED_DUP)는 사업자명만 다른 쌍둥이를 놓친다 — 실측: 불꽃축제 제안 8건이
        # 서로 0.72를 넘지 못해 모두 통과했다. ⓪ 어휘 직결과 같은 결정적 규칙을 제안 쪽에도 둔다.
        # 기각분과의 대조는 후보에 제도 신호가 없을 때만 — 기각된 홍보 파편과 어휘가 겹친다는
        # 이유로 진짜 정책 이슈가 막히면 안 된다(실측: 이 예외가 없으면 활성 #13·#30·#46이 차단됐다).
        _cand_policy = bool(_POLICY_SIGNAL.search(titles_all))
        _frag = next((i for i in issues
                      if (i['state'] == 'proposed' or (i['state'] == 'rejected' and not _cand_policy))
                      and len(kw_rep & extract_keywords(i['title'])) >= 3), None)
        if _frag is not None:
            print(f'[제안 보류 — 파편/재제안] "{group[0]["title"][:28]}" ≈ '
                  f'[{_frag["id"]}·{_frag["state"]}] {_frag["title"][:24]}')
            continue
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
        else:
            print(f'[관련 판정 — 소속 아님] "{title[:28]}" ≠ [{iss["id"]}]')

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
        # 생성된 제목에도 같은 잣대 — Haiku가 홍보 기사에서 그럴듯한 이슈 제목을 지어낼 수 있다
        if _NON_ISSUE.search(prof['title']) and not _POLICY_SIGNAL.search(prof['title'] + ' ' + titles_all):
            print(f'[제안 보류 — 홍보·행사성(생성 제목)] {prof["title"]}')
            continue
        hint = '현안' if (_STAGE_SANCTION.search(titles_all) or _STAGE_INCIDENT.search(titles_all)
                          or _STAGE_LAWSUIT.search(titles_all)) else '발생'
        _propose(sb, issues, prof['title'], prof.get('definition'), prof.get('category', '기타'),
                 nk, {'kind': 'news_cluster', 'cluster_size': len(group), 'urgent_count': urgent,
                      'days': len(days), 'sample_news_ids': [str(r['id']) for r in group[:10]],
                      'detail': f'기사 {len(group)}건 · {len(days)}일 · 긴급 {urgent}'},
                 dry, stage_hint=hint, news_rows=group)


def _reg_keys(item_type, item_id, law_by_id):
    """규제 항목의 동일성 열쇠(#231) — 법령 '이름'이 아니라 번호로 같은 항목을 가린다.
    종전 열쇠(법령명 제목의 norm_key)는 같은 법의 다른 내용을 한 항목으로 봐서, #27 기각 뒤 정보통신망법
    법안 3건이 조용히 빠지고 diff 70(유출 통지·CPO 시행령)이 이름표만 같은 #52(마이데이터)에 붙었다.
      · 법안: bill:<의안번호>
      · DIFF: diff:<id> + 국회 개정안 조문 대비(origin=assembly)면 그 법안 bill:<new_doc>,
              정부 판이면 같은 공포 법령 act:<법령명>|<공포번호>(시행일만 다른 판 — diff 41·42)"""
    keys = {f'{item_type}:{item_id}'}
    if item_type == 'diff':
        d = law_by_id.get(str(item_id)) or {}
        if d.get('origin') == 'assembly' and d.get('new_doc'):
            keys.add('bill:' + str(d['new_doc']))
        elif d.get('law_no'):
            keys.add('act:' + re.sub(r'\s+', '', d.get('law_name') or '') + '|' + str(d['law_no']))
    return keys


def _issue_reg_keys(issues, reg_links, law_by_id):
    """이슈별 규제 열쇠 — 제안 사유(기각하면 링크는 webhook이 지우지만 사유는 남는다) + 연결된 법안·DIFF."""
    keys = {}
    for i in issues:
        pr = i.get('proposal_reason') or {}
        ks = set()
        if pr.get('bill_no'):
            ks |= _reg_keys('bill', pr['bill_no'], law_by_id)
        if pr.get('diff_id') is not None:
            ks |= _reg_keys('diff', pr['diff_id'], law_by_id)
        keys[i['id']] = ks
    for r in reg_links:
        keys.setdefault(r['issue_id'], set()).update(_reg_keys(r['item_type'], r['item_id'], law_by_id))
    return keys


def _reg_identity(issues, issue_keys, keys):
    """같은 항목이 이미 들어 있는 이슈 — active 우선(개선 2), 그다음 proposed·rejected. 없으면 None."""
    found = {}
    for i in issues:
        if issue_keys.get(i['id'], set()) & keys:
            found.setdefault(i['state'], i)
    for st in ('active', 'proposed', 'rejected'):
        if st in found:
            return st, found[st]
    return None


def _reg_title(law_name: str, summary: str):
    """규제 항목 → 주제형 이슈 제목(#231). 제목은 승인 시 과거 뉴스 검색어가 된다 — 법령명 제목은 그 법의
    온갖 기사를 끌어와 #198이 무관 기사 7건·출처 틀린 요약으로 오염됐다. '무엇이 바뀌는지'를 제목으로 쓴다.
    실패·잘림·법령명만 나온 제목은 None — 제안을 미루고 다음 실행에서 다시 짓는다(법령명 폴백 금지)."""
    if not ANTHROPIC_API_KEY or not (summary or '').strip():
        return None
    try:
        import anthropic
        resp = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
            model='claude-haiku-4-5-20251001', max_tokens=200,
            system=('통신·전파 정책 이슈 관리 보조자다. 법령 개정안·입법예고 한 건의 요지를 보고 이슈 제목을 짓는다. '
                    'JSON 하나만 출력한다: {"title": "무엇이 바뀌는지 드러나는 주제형 제목(25자 이내)"}. '
                    '법령 이름·"개정"·"일부개정법률안"만으로 된 제목은 금지 — 바뀌는 의무·금지·권한·대상을 제목에 쓴다. '
                    '요지에 없는 숫자·날짜·대상은 쓰지 않는다. JSON 외 다른 말 금지.'),
            messages=[{'role': 'user', 'content': f'법령: {law_name}\n요지: {(summary or "")[:800]}'}])
        if getattr(resp, 'stop_reason', None) == 'max_tokens':
            print('  [제목 생성 잘림(보류)]')
            return None
        text = ''.join(b.text for b in resp.content if getattr(b, 'text', None))
        m = re.search(r'\{[\s\S]*\}', text)
        title = ((json.loads(m.group(0)).get('title') or '') if m else '').strip()
        if not title or not re.search(r'[가-힣]', title) or _is_law_only_title(title, law_name):
            print(f'  [제목 부적합(보류)] {title!r}')
            return None
        return title[:60]
    except Exception as e:
        print(f'  [제목 생성 실패(보류)] {e}')
        return None


def _reg_process(sb, issues, items, law_by_id, reg_links, dry):
    """규제 후보 판정(#231): ① 번호 동일성 → ② 요약 내용 벡터 → ③ 경계 Sonnet 관련 판정 → ④ 주제형 제목 제안.
    items: [{label, name, summary, keys, link, reason}] — 이미 연결된 항목은 호출부가 뺀다."""
    if not items:
        return
    issue_keys = _issue_reg_keys(issues, reg_links, law_by_id)
    by_id = {i['id']: i for i in issues}
    todo = []
    for it in items:
        hit = _reg_identity(issues, issue_keys, it['keys'])
        if hit:
            st, iss = hit
            tgt = _merge_target(iss, by_id) if st == 'rejected' else None   # 합친 기각(#243) — 같은 번호면 합친 곳에
            if st == 'active' or tgt is not None:
                if not dry:
                    _link_reg(sb, (tgt or iss)['id'], it['link'])
                print(f'[기존 이슈 연결·같은 항목{"(합친 곳)" if tgt else ""}] {it["label"]} → '
                      f'[{(tgt or iss)["id"]}] {(tgt or iss)["title"][:24]}')
            else:
                print(f'[건너뜀 — 같은 항목이 {st} 이슈에 있음] {it["label"]} ≈ [{iss["id"]}] {iss["title"][:24]}')
            continue
        if not it['summary']:
            print(f'[보류 — 요약 없음] {it["label"]} {it["name"][:30]}')
            continue
        todo.append(it)
    if not todo:
        return
    # 법령 이름 없이 요약 내용만 — 이름을 넣으면 같은 법의 다른 내용끼리 유사도가 올라간다(실측 +0.03~0.08)
    vecs = _embed([it['summary'][:300] for it in todo])
    judge = []
    for k, (it, vec) in enumerate(zip(todo, vecs)):
        _, best_a, sim_a, sim_p, sim_r = _match_states(issues, None, vec)
        it['sim'] = (sim_a, sim_p, sim_r)
        if best_a is not None and sim_a >= SIM_MERGE and not _has_exclusion(best_a):
            if not dry:
                _link_reg(sb, best_a['id'], it['link'])
            it['done'] = True
            print(f'[기존 이슈 연결·내용] {it["label"]} → [{best_a["id"]}] {best_a["title"][:24]} (sim {sim_a:.2f})')
        elif best_a is not None and sim_a >= SIM_REG_RELATED:
            # 0.80 이상인데 배제 기준 이슈인 경우도 여기로 — 정의문을 읽는 판정만 붙일 수 있다(#157)
            judge.append((k, f'{it["name"]} — {it["summary"][:300]}', best_a))
        else:
            # 합친 기각과 내용이 같으면(≥0.72) 아래 '내용 중복'으로 빠지기 전에 합친 곳과 판정(#243)
            mh = _merged_hit(issues, by_id, vec)
            if mh is not None:
                judge.append((k, f'{it["name"]} — {it["summary"][:300]}', mh[1]))
                print(f'[기각 병합처→판정] {it["label"]} ≈ 기각 [{mh[0]["id"]}] → 합친 곳 [{mh[1]["id"]}]')
    if judge:
        related = _haiku_relate_batch(judge, None, kind='reg')
        for k, _, iss in judge:
            it = todo[k]
            if related is None:
                it['done'] = True   # 판정 실패는 '관련 없음'이 아니다 — 제안하지 않고 다음 실행에서 다시 본다
                print(f'[보류 — 관련 판정 실패] {it["label"]} (후보 [{iss["id"]}])')
            elif k in related:
                if not dry:
                    _link_reg(sb, iss['id'], it['link'])
                it['done'] = True
                print(f'[기존 이슈 연결·관련판정] {it["label"]} → [{iss["id"]}] {iss["title"][:24]} '
                      f'(sim {it["sim"][0]:.2f})')
            else:
                print(f'[관련 판정 — 소속 아님] {it["label"]} ≠ [{iss["id"]}] (sim {it["sim"][0]:.2f})')
    for it in todo:
        if it.get('done'):
            continue
        sim_a, sim_p, sim_r = it['sim']
        if sim_p >= SIM_PROPOSED_DUP or sim_r >= SIM_PROPOSED_DUP:
            print(f'[건너뜀 — 내용 중복] {it["label"]} (대기 {sim_p:.2f} · 기각 {sim_r:.2f})')
            continue
        hit = _reg_identity(issues, issue_keys, it['keys'])   # 같은 실행에서 방금 제안된 짝(국회 DIFF↔법안)
        if hit:
            print(f'[건너뜀 — 같은 항목이 {hit[0]} 이슈에 있음] {it["label"]} ≈ [{hit[1]["id"]}]')
            continue
        if _proposed_this_run >= MAX_PROPOSALS_PER_RUN:
            print(f'[제안 상한 도달 — 이월] {it["label"]}')   # 제목 생성(AI) 전에 끊는다 — 버릴 결과를 만들지 않는다
            continue
        title = _reg_title(it['name'], it['summary'])
        if not title:
            print(f'[제안 보류 — 제목 생성 불가] {it["label"]}')
            continue
        iid = _propose(sb, issues, title, _clip_sentence(it['summary']) or None, '규제·CR', _norm_key(title),
                       it['reason'], dry, stage_hint='현안', link_item=it['link'])
        if iid:
            issue_keys[iid] = set(it['keys'])


def _reg_items(diffs, bills, law_by_id, linked):
    """판정 후보 목록 — 이미 어느 이슈에든 연결된 항목과 핵심 법령 밖 법안은 뺀다."""
    items = []
    for d in diffs:
        if ('diff', str(d['id'])) in linked:
            continue
        kind = d.get('diff_kind')
        enf = _fmt_enf(d.get('enf_date')) or '?'
        # proposed(입법예고안)의 enf_date는 의견 마감일이다 — '시행'으로 적으면 오독(#198 알림 '시행 20261002')
        if d.get('origin') == 'assembly':
            detail = f'국회 개정안 조문 대비 · {d["law_name"]}(의안 {d.get("new_doc")}) · 의견 마감 {enf}'
        elif kind == 'proposed':
            detail = f'정부 입법예고 · {d["law_name"]} · 의견 마감 {enf} — 보도 유무와 무관'
        else:
            detail = f'중요 개정 · {d["law_name"]}({kind}) · 시행 {enf} — 보도 유무와 무관'
        items.append({
            'label': f'diff {d["id"]}', 'name': d['law_name'], 'summary': (d.get('summary') or '').strip(),
            'keys': _reg_keys('diff', d['id'], law_by_id),
            'link': {'item_type': 'diff', 'item_id': str(d['id']), 'item_date': _fmt_enf(d.get('enf_date')),
                     'title': f'{d["law_name"]} 개정 ({kind})'},
            'reason': {'kind': 'law_diff_high', 'diff_id': d['id'], 'law_name': d['law_name'], 'detail': detail},
        })
    for b in bills:
        if ('bill', b['bill_no']) in linked or not _CORE_LAW.search(b.get('bill_name') or ''):
            continue
        items.append({
            'label': f'bill {b["bill_no"]}', 'name': b['bill_name'], 'summary': (b.get('summary') or '').strip(),
            'keys': _reg_keys('bill', b['bill_no'], law_by_id),
            'link': {'item_type': 'bill', 'item_id': b['bill_no'],
                     'item_date': (b.get('notice_end_dt') or '')[:10] or None, 'title': b['bill_name']},
            'reason': {'kind': 'assembly_notice', 'bill_no': b['bill_no'],
                       'detail': f'국회 입법예고 · {b["bill_name"]}(의안 {b["bill_no"]}) · 의견 마감 {b.get("notice_end_dt")}'},
        })
    return items


def _suggest_from_regs(sb, issues, dry):
    """ⓑ 무보도 규제 — 보도가 없어도 중요 개정·입법예고는 이슈가 된다. 판정은 _reg_process(#231)."""
    since = _iso(_now() - timedelta(days=7))
    law_rows = _fetch_all(lambda: sb.table('law_diffs').select('id,law_name,law_no,origin,new_doc').order('id'))
    law_by_id = {str(r['id']): r for r in law_rows}
    reg_links = _fetch_all(lambda: sb.table('issue_links').select('id,issue_id,item_type,item_id')
                           .in_('item_type', ['bill', 'diff']).order('id'))
    linked = {(r['item_type'], str(r['item_id'])) for r in reg_links}
    diffs = sb.table('law_diffs').select('id,law_name,summary,enf_date,diff_kind,origin,new_doc') \
        .eq('urgency', 'high').gte('created_at', since).order('id').execute().data or []
    bills = sb.table('assembly_bills').select('bill_no,bill_name,notice_end_dt,summary') \
        .not_.is_('notice_end_dt', 'null').gte('notice_end_dt', _now().strftime('%Y-%m-%d')) \
        .order('bill_no').execute().data or []
    _reg_process(sb, issues, _reg_items(diffs, bills, law_by_id, linked), law_by_id, reg_links, dry)


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
        # 단, 세션이 붙이는 이해관계자·법령·사례 링크는 '활동'이 아니다 — 큐레이션이 휴면
        # 배지를 지워 4개월 무활동 이슈(#7)가 현안으로 남는 실측(2026-09-13, #157-보론2).
        recent = sb.table('issue_links').select('created_at').eq('issue_id', i['id']) \
            .in_('item_type', ['news', 'press_chunk', 'minutes', 'bill', 'diff']) \
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
