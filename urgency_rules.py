"""뉴스 긴급도 공통 낱말 규칙 매처 (#216, 2026-09-25) — 표준 라이브러리만.

규칙 표 `urgency_rules`(공통 = team_id null)의 행을 받아 기사 제목 + 네이버 요약에 돌린다.
같은 규칙을 `supabase/functions/_shared/urgency_rules.js`(대시보드 미리보기)가 그대로 구현하고,
두 구현은 `tests/fixtures/urgency_rules_cases.json` 한 파일을 함께 돈다. 사내판도 이 파일 둘과
케이스 파일을 그대로 복사해 쓴다 — **한쪽만 고치지 말 것.**

매처 계약(설계안 docs/뉴스중요도_공통팀별_설계안_260925.md §3):
  - 입력 텍스트 = NFC(제목 + ' ' + 요약). 부분 문자열, 대소문자 그대로. 본문은 보지 않는다.
  - 적중 = any 하나 이상 AND and_any 각 그룹마다 하나 이상(평면 배열은 그룹 하나) AND none 없음.
  - 목록 순서(= position 순)의 **첫 적중 규칙 하나가 정한다** — 첫 적중이 min이고 이미 그 이상이면
    값 그대로 두고 뒤 규칙으로 넘어가지 않는다.
  - min = 하한(올리기만), set = 지정(AI 값 무시). 적중 id는 값이 안 바뀌어도 돌려준다.
  - team_id·enabled·position은 매처가 보지 않는다 — 목록을 만드는 쪽(로더)이 거르고 정렬한다.

규칙 한 개는 표 행 모양(any_words/none_words/mode/level)과 JSON 모양(any/none/"min": 등급 또는
"set": 등급) 둘 다 받는다.
"""
import unicodedata

LEVELS = ('참고', '보통', '긴급')          # 등급 순서 = 인덱스
_RANK = {lv: i for i, lv in enumerate(LEVELS)}
MODES = ('min', 'set')


def normalize_text(title, summary=''):
    """매처 입력 — NFC(제목 + ' ' + 요약)."""
    return unicodedata.normalize('NFC', f'{title or ""} {summary or ""}')


def _nfc(s):
    return unicodedata.normalize('NFC', s) if isinstance(s, str) else ''


def _rule_view(r):
    """표 행·JSON 두 모양을 (id, mode, level, any, groups, none)로 읽는다."""
    mode = r.get('mode')
    level = r.get('level')
    if not mode:
        for m in MODES:
            if r.get(m):
                mode, level = m, r.get(m)
                break
    any_w = r.get('any_words') if r.get('any_words') is not None else r.get('any')
    and_any = r.get('and_any') or []
    none_w = r.get('none_words') if r.get('none_words') is not None else r.get('none')
    if and_any and all(isinstance(x, str) for x in and_any):
        groups = [list(and_any)]                     # 평면 배열 = 그룹 하나(요청안 형식 호환)
    else:
        groups = [list(g) for g in and_any if isinstance(g, list)]
    return r.get('id'), mode, level, list(any_w or []), groups, list(none_w or [])


def _has_any(text, words):
    return any(w and _nfc(w) in text for w in words)


def match_urgency_rules(rules, title, summary=''):
    """position 순 첫 적중 규칙 → {'id', 'mode', 'level'}. 없으면 None."""
    text = normalize_text(title, summary)
    for r in rules or []:
        rid, mode, level, any_w, groups, none_w = _rule_view(r)
        if not any_w or not _has_any(text, any_w):
            continue
        if not all(_has_any(text, g) for g in groups):
            continue
        if none_w and _has_any(text, none_w):
            continue
        return {'id': rid, 'mode': mode, 'level': level}
    return None


def combine(hit, ai_level):
    """적중 결과와 AI 값을 합친다 → (등급, 규칙 id|None, 값 변경 여부)."""
    if not hit:
        return ai_level, None, False
    if hit['mode'] == 'set':
        level = hit['level']
    else:                                            # min — 하한만, AI가 더 높으면 AI 값
        level = hit['level'] if _RANK.get(hit['level'], -1) > _RANK.get(ai_level, -1) else ai_level
    return level, hit['id'], level != ai_level


def apply_urgency_rules(rules, title, summary, ai_level):
    """(등급, 규칙 id|None, 값 변경 여부). 미적중이면 (ai_level, None, False)."""
    return combine(match_urgency_rules(rules, title, summary), ai_level)


def _is_word_list(v, allow_empty=True):
    return isinstance(v, list) and (allow_empty or len(v) > 0) and \
        all(isinstance(w, str) and w.strip() for w in v)


def validate_rules(rows):
    """형식 오류 문장 목록(빈 목록 = 정상)."""
    errs = []
    seen = set()
    for i, r in enumerate(rows or []):
        if not isinstance(r, dict):
            errs.append(f'{i + 1}번: 규칙이 객체가 아님')
            continue
        rid, mode, level, _, _, _ = _rule_view(r)
        tag = f'{i + 1}번({rid or "id 없음"})'
        if not isinstance(rid, str) or not rid.strip():
            errs.append(f'{tag}: id가 비어 있음')
        elif rid in seen:
            errs.append(f'{tag}: id 중복')
        else:
            seen.add(rid)
        if mode not in MODES:
            errs.append(f'{tag}: mode는 min 또는 set')
        if level not in LEVELS:
            errs.append(f'{tag}: level은 긴급·보통·참고 중 하나')
        any_w = r.get('any_words') if r.get('any_words') is not None else r.get('any')
        if not _is_word_list(any_w, allow_empty=False):
            errs.append(f'{tag}: any 낱말이 비어 있거나 형식 오류')
        and_any = r.get('and_any') or []
        if not isinstance(and_any, list):
            errs.append(f'{tag}: and_any는 배열')
        elif and_any and not (_is_word_list(and_any, allow_empty=False) or
                              all(_is_word_list(g, allow_empty=False) for g in and_any)):
            errs.append(f'{tag}: and_any는 낱말 배열 또는 비지 않은 낱말 배열들의 배열')
        none_w = r.get('none_words') if r.get('none_words') is not None else r.get('none')
        if none_w is not None and not _is_word_list(none_w):
            errs.append(f'{tag}: none 형식 오류')
    return errs


# ── 비상용 사본 — 표 조회 실패·형식 오류일 때만 쓴다(정본은 표 urgency_rules, #53과 같은 구조) ──
# 표를 고치면 이 사본은 따라오지 않는다(비상용이라 의도). 규칙 id는 영구 불변 — 이름을 바꿔도 id 유지.
_MINISTRY = ['과기정통부', '과학기술정보통신부', '방통위', '방미통위', '방송통신위', '전파연구원', '중앙전파관리소']
URGENCY_RULES_FALLBACK = [
    {'id': 'obituary', 'position': 10, 'mode': 'min', 'level': '보통',
     'any_words': ['부고', '모친상', '부친상', '빙모상', '장인상', '조모상', '조부상'],
     'and_any': [], 'none_words': [],
     'note': '부고 — 부처·업계 인사 경조사는 최소 보통(기관명이 든 부고가 아래 규칙으로 가지 않게 맨 앞)'},
    {'id': 'skt_gukgam_witness', 'position': 20, 'mode': 'min', 'level': '긴급',
     'any_words': ['SK텔레콤', 'SKT', '통신3사', '이통3사', '통신 3사', '이통 3사', '이동통신 3사'],
     'and_any': [['국감', '국정감사'], ['증인', '참고인', '소환', '출석', '국감행', '국감장']],
     'none_words': [],
     'note': '국정감사 증인·참고인 채택·소환·출석(SKT·통신3사 일괄) — 전 팀 공통 최소 긴급'},
    {'id': 'ministry_personnel', 'position': 30, 'mode': 'min', 'level': '보통',
     'any_words': list(_MINISTRY),
     'and_any': [['인사', '인사이동', '인사 발령', '인사발령', '임명', '취임', '내정', '발탁', '승진', '전보', '보직']],
     'none_words': [],
     'note': '소관 부처·기관 인사 — 최소 보통'},
    {'id': 'assembly_law', 'position': 40, 'mode': 'min', 'level': '보통',
     'any_words': ['과방위', '국정감사', '전기통신사업법'],
     'and_any': [], 'none_words': [],
     'note': '과방위·국정감사·전기통신사업법 — 최소 보통'},
    {'id': 'ministry_telecom', 'position': 50, 'mode': 'min', 'level': '보통',
     'any_words': list(_MINISTRY),
     'and_any': [['이동통신', '통신사', '통신3사', '이통3사', 'SK텔레콤', 'SKT', 'LG유플러스', '5G', '6G',
                  '기지국', '주파수', '전파', '통신망', '전기통신', '알뜰폰', '요금제', '통신요금', '단말',
                  '로밍', '와이파이', '무선국', '방송통신', '위성통신']],
     'none_words': [],
     'note': '소관 부처·기관 + 통신 사안 — 최소 보통'},
]
