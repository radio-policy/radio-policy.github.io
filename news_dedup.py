# -*- coding: utf-8 -*-
"""뉴스 중복(같은 사건 재보도) 판정 공용 유틸 — API 비용 0, 제목 키워드 기반.

crawler.py(텔레그램·이메일 재알림 억제)와 morning_briefing.py(브리핑 클러스터링)가 공유한다.
대시보드 app.js `_extractKeywords()`의 파이썬 이식 + 확장(영문 토큰 KT/5G, 금액 정규화).

임계값 3(공유 키워드 3개 이상 = 같은 사건)의 근거 — 실데이터 검증(배경역사 #44):
  · 2개로 낮추면 「KT 해킹 과징금 540억」과 「KT 5G 과장광고 139억 소송」이
    'KT+과징금' 2개 공유로 한 사건이 되어, 두 번째 사건의 첫 알림이 삼켜진다.
  · 3개면 두 사건이 갈라지면서 같은 사건 재보도(8일 358건)는 잡힌다.

클러스터링은 별-형(씨앗과만 비교, 전이 연결 없음)만 제공한다 — 전이 연결은
"540억 이어 5G 소송도 패소" 같은 다리 기사가 서로 다른 두 사건을 한 묶음으로
이어버려(실측: 261건 묶음) 브리핑에서 사건 하나가 통째로 사라진다.

AI(Haiku)를 쓰는 함수는 둘이고 쓰임이 다르다 — **서로 바꿔 쓰지 말 것**(#263):
  · group_same_event     같은 실행분의 대표들을 묶는다(#92). 틀려도 대표 + '(관련 보도 N건)'으로 남는다.
  · match_prior_reports  새 기사가 「이미 알린 기사」의 재보도인지 가린다 — 실행이 갈린 재보도의 억제(①-2)용.
                         억제는 되돌릴 수 없어 확실할 때만 같다고 한다.
"""
import re
import api_usage; api_usage.install()   # Anthropic usage 기록(#152) — 호출부 무변경, fail-open

# 대시보드 _extractKeywords와 동일한 불용어 (양쪽을 함께 고칠 것)
STOPWORDS = {
    '관련', '대한', '위한', '통해', '대해', '기반', '위해', '이후', '이전',
    '지난', '오는', '올해', '내년', '지금', '현재', '새로운', '이번', '해당', '추진',
    '강화한다', '강화하는', '나선다', '밝혔다', '위해서',
}
_JOSA_RE = re.compile(r'(으로|에서|부터|까지|로서|로는|로도|에는|에도|이나|이며|이고|로|을|를|이|가|은|는|의|에|과|와|도|만)$')

# 국면 신호 단어 — 새 기사 제목에 처음 등장하면(비교 상대 제목에는 없으면) 억제를 해제한다.
# "본문에만 새 내용" 한계의 안전판. 상대 제목에도 있으면(그 국면 2일차부터) 다시 조용해진다.
SIGNAL_WORDS = [
    '소송', '고발', '상고', '항소', '기소', '압수수색', '구속', '영장',
    '사퇴', '사임', '해임', '경질', '청문회', '국정감사', '국감',
    '개정안', '개정', '입법예고', '시행', '폐지', '무효', '취소',
    '승소', '패소', '기각', '인용', '합의', '중재', '제재', '행정처분',
]


def extract_keywords(title: str) -> set:
    """제목 → 비교용 키워드 집합. 한글 2자+ / 숫자+한글(금액: '원' 제거) / 영문 토큰(KT·5G).

    ⚠️ 한글 토큰에도 **조사를 뗀다**(2026-08-06, #92). 종전에는 숫자+한글(금액)에만 떼서
    「약관」과 「약관에」, 「유플러스」와 「유플러스의」가 다른 키워드로 세어졌다 —
    같은 사건 기사끼리 공유 키워드가 실제보다 적게 나온다.
    조사를 떼도 2자 미만이 되면(예: '로는'→'') 원형을 살린다.
    """
    def _dejosa(w: str) -> str:
        s = _JOSA_RE.sub('', w)
        return s if len(s) >= 2 else w

    words = [_dejosa(w) for w in re.findall(r'[가-힣]{2,}', title or '')]
    mixed = [re.sub(r'원$', '', _JOSA_RE.sub('', w)) for w in re.findall(r'[0-9]+[가-힣]+', title or '')]
    alnum = [w.upper() for w in re.findall(r'[A-Za-z][A-Za-z0-9+]{1,}', title or '')]
    norm = [re.sub(r'([가-힣]{2,})(도|시|군|구|광장)$', r'\1', w) for w in words]
    return {w for w in norm + mixed + alnum if w not in STOPWORDS and len(w) >= 2}


def has_new_signal(new_title: str, prior_title: str) -> bool:
    """새 제목에 국면 신호 단어가 '처음' 등장했는가 (비교 상대 제목에는 없던 단어)."""
    return any(s in (new_title or '') and s not in (prior_title or '') for s in SIGNAL_WORDS)


def is_followup(new_kw: set, prior_kw: set, new_title: str, prior_title: str,
                threshold: int = 3) -> bool:
    """new가 prior와 같은 사건의 재보도인가. 신호 단어가 새로 등장하면 재보도로 보지 않는다."""
    if len(new_kw & prior_kw) < threshold:
        return False
    if has_new_signal(new_title, prior_title):
        return False
    return True


def cluster_star(items: list, title_key='title', threshold: int = 3) -> list:
    """별-형 클러스터링(전이 없음): 순서대로 훑으며 기존 씨앗과 공유 키워드 threshold개
    이상이면 그 씨앗에 붙이고, 아니면 새 씨앗이 된다.
    반환: [(대표 item, [묶인 item들(대표 제외)]), ...] — 입력 순서 유지.
    입력 순서가 대표를 정하므로, 최신순으로 주면 최신 기사가 대표가 된다."""
    seeds = []   # [(item, kw, members)]
    for it in items:
        kw = extract_keywords(it.get(title_key) or '')
        for s in seeds:
            if len(kw & s[1]) >= threshold:
                s[2].append(it)
                break
        else:
            seeds.append((it, kw, []))
    return [(s[0], s[2]) for s in seeds]


# ── 2차 묶기: 키워드로 못 묶은 것만 Haiku에 묻는다 (2026-08-06, #92) ──────────────
#  왜 필요한가(실측): 공정위 통신3사 불공정약관 시정 사건을 4개 매체가 각자의 관점으로 써서
#  제목에 공통 단어가 거의 없었다 — 「이용자 개인정보 보호 등 권리 강화」(발표 관점),
#  「비암호화 와이파이 정보유출에 책임 없다」(약관 인용), 「면책 조항 신설」(약관 내용),
#  「불공정 약관에 철퇴」(제재 관점). 쌍별 공유 키워드가 **최대 1개**라 임계 3에 한참 못 미쳤고,
#  조사를 떼도 최대 2개였다. 어휘로는 넘을 수 없는 간극이라 의미 판정이 필요하다.
#
#  ⚠️ **이 함수는 클러스터링(같은 실행분 묶기)에만 쓴다. 억제(is_followup)에는 쓰지 않는다.**
#  묶기는 틀려도 대표 + '(관련 보도 N건)'으로 남지만, 억제는 알림 자체를 없애 되돌릴 수 없다.
#  (2026-09-14 #170이 이 금지를 넘어 실행 간 억제(①-2)에 이 분류기를 썼다가 17일 동안 기보도와 묶은 98건 중 56건의
#   짝이 틀렸다 — #263에서 억제는 아래 match_prior_reports로 옮겼다. 다시 빌려 쓰지 말 것.)
#  ★ 「한 처분을 여러 각도에서 쓴 것도 같은 사건」 문장이 결정적이었다(실측):
#    이 문장 없이는 공정위 4건이 「발표 관점(1·4)」과 「약관 내용 관점(2·3)」 2묶음으로 갈렸고,
#    넣은 뒤에는 다른 사건(KT 소송·LGU+ 인증)을 섞어 준 실전 조건에서 4건이 정확히 한 묶음이 됐다.
#    대조군이 있을 때 더 정확한 것은 「무엇이 다른 사건인지」 기준이 생기기 때문이다 —
#    실제 크롤링은 항상 여러 사건이 섞이므로 이쪽이 현실 조건이다. 오묶음은 실측 0건.
_GROUP_SYSTEM = (
    '너는 뉴스 제목만 보고 **같은 사건을 다룬 기사끼리** 묶는 분류기다.\n'
    '- 같은 사건 = 같은 발표·같은 처분·같은 사고를 다룬 것.\n'
    '- **하나의 처분·발표를 매체가 서로 다른 각도에서 쓴 것은 같은 사건이다.** 예: 규제기관의 한 제재를\n'
    '  ①보도자료 문구 인용 ②시정된 약관 조항 내용 ③제재 대상 기업명 ④제재 결과 로 각각 제목을 뽑아도 한 사건이다.\n'
    '- 다른 사건 = 사안 자체가 다른 것. 주체(회사·기관)가 같아도 사안이 다르면 묶지 않는다.\n'
    '  예: 같은 회사의 과징금 사건과 신제품 출시는 다른 사건이다.\n'
    '- 출력은 JSON 배열 하나만. 각 원소는 같은 사건인 기사 번호들의 배열이다. 예: [[1,3,4],[2]]\n'
    '- 모든 번호가 정확히 한 번씩. 설명·코드블록 없이 배열만.'
)


def group_same_event(titles: list, api_key: str, model: str = 'claude-haiku-4-5-20251001',
                     timeout=None, max_retries=None) -> list | None:
    """제목 목록 → 같은 사건끼리의 인덱스 그룹. 실패하면 None(호출부는 원본 유지 = fail-open).

    반환 예: [[0, 2, 3], [1]]  (0-based, 입력 순서 유지)
    timeout·max_retries(#252): 주면 클라이언트에 그대로 건다 — 크롤러의 받는 단위별 알림이 짧은 제한(20초·재시도 1회)으로
    부른다(멈춘 호출 하나가 공통 즉시 배달을 붙잡지 않게). **둘 다 None(기본)이면 종전과 같은 호출**(Anthropic(api_key=…)만).
    """
    if not api_key or len(titles) < 2:
        return None
    try:
        import json as _json
        import anthropic
        listing = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(titles))
        client_kw = {}
        if timeout is not None:
            client_kw['timeout'] = timeout
        if max_retries is not None:
            client_kw['max_retries'] = max_retries
        resp = anthropic.Anthropic(api_key=api_key, **client_kw).messages.create(
            model=model, max_tokens=400, system=_GROUP_SYSTEM,
            messages=[{'role': 'user', 'content': f'[기사 {len(titles)}건]\n{listing}'}],
        )
        # Sonnet5 적응형 추론 함정 회피와 같은 이유로 text 블록만 골라 잇는다
        raw = ''.join(b.text for b in resp.content if getattr(b, 'type', '') == 'text').strip()
        m = re.search(r'\[.*\]', raw, re.S)
        if not m:
            return None
        groups = _json.loads(m.group(0))
        # 검증: 1..N이 정확히 한 번씩 — 하나라도 어긋나면 통째로 버린다(부분 신뢰 금지)
        flat = [n for g in groups for n in g]
        if sorted(flat) != list(range(1, len(titles) + 1)):
            print(f'[사건 묶기] 응답 번호 불일치 — 무시 (기대 1~{len(titles)}, 받음 {sorted(flat)})')
            return None
        return [[n - 1 for n in g] for g in groups]
    except Exception as e:
        print(f'[사건 묶기] 실패(원본 유지): {e}')
        return None


# ── 재보도 대조(억제용): 새 기사가 「이미 알린 기사」의 재보도인가 (2026-09-30, #263) ─────────────────────────
#  억제(실행이 갈린 재보도 ①-2)는 위 묶기 분류기가 아니라 이 판정기가 맡는다. 다른 점:
#   · 묻는 방식 — 제목 뭉치를 한꺼번에 나누지 않는다. 새 기사마다 「이미 알린 기사」 가운데 가장 가까운 하나를 고르고,
#     두 기사의 「계기」(그 기사가 나오게 된 일)를 나란히 적은 뒤 같은지 따로 답한다. 새 기사끼리는 견주지 않는다
#     (분할 방식은 중간 기사를 다리로 무관한 기사를 한 묶음에 넣는다 — 파일 머리말의 전이 연결 금지와 같은 이유).
#   · 확실할 때만 같음 — 억제는 되돌릴 수 없다(#92). 애매하면 다름(= 알림이 나간다).
#   · 입력 — 제목 + 요지(news_feed.event) + 요약(screen_text 앞 120자). 제목만 주면 '주제가 같은 글'과
#     '같은 일의 재보도'를 가르지 못한다(실측: 요약을 빼면 새 소식을 기보도와 묶는 일이 29 → 34건).
#   · 부르는 쪽(crawler._suppress_core)은 「이미 알린 기사」로 **실제로 알림이 나간 대표만** 넘긴다.
#  ★ 지시문·도구는 tests/test_dedup_match.py가 글자 그대로 잠근다 — 고치려면 tools_dedup_probe.py로
#    tests/fixtures/dedup_match_cases.json(09-13~09-30 실제 실행 173회·Fable 정답표)을 다시 재고 함께 고친다.
#  ★ 온도 0(temperature 0) — 온도류 금지 규칙의 **둘째 예외**(첫째는 crawler.classify_urgency, 운영자 결정 2026-09-30).
#    기본값에서는 같은 입력을 두 번 물으면 20건 중 5건의 답이 갈렸고(온도 0은 44건 중 1건), 갈린 답이 '같음'이면
#    알림이 우연히 사라진다. 이 파일에서 온도 값을 주는 호출은 이 한 곳뿐이다(테스트가 센다).
MATCH_MODEL = 'claude-haiku-4-5-20251001'
MATCH_MAX_NEW = 12          # 한 호출에 싣는 새 기사 수 — 넘으면 나눠 부른다(「이미 알린 기사」 목록은 같다)
MATCH_MAX_PRIOR = 10        # 「이미 알린 기사」 수(부르는 쪽이 맞춰 넘긴다 — 기호 A~J)
MATCH_SNIP = 120            # 기사 한 줄에 붙이는 요약 글자 수
_MATCH_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

_MATCH_SYSTEM = (
    '너는 통신·전파 정책 뉴스 알림의 중복 거름 판정기다. [새 기사]마다 [이미 알린 기사] 가운데 같은 소식이 있는지 가린다.\n'
    '같다고 하면 그 새 기사는 알림에서 빠진다. 확실할 때만 같다고 하고, 애매하면 다르다고 한다.\n'
    '새 기사끼리는 견주지 않는다 — 이미 알린 기사하고만 견준다.\n'
    '\n'
    '기사마다 「계기」를 본다. 계기 = 그 기사가 나오게 된 일: 어느 기관·회사·의원이 무엇을 발표·공개·결정·발언했는지, 어떤 사고·판결·회의가 있었는지. 계기 없이 '
    '기자가 스스로 정리·해설·전망한 글이면 「자체 정리: 무엇에 관한」이라고 적는다.\n'
    '\n'
    '새 기사마다 네 칸을 차례로 채운다\n'
    '1) peg — 새 기사의 계기 한 줄.\n'
    '2) closest — 이미 알린 기사 가운데 계기가 가장 가까운 것의 기호. 없으면 "0".\n'
    '3) closest_peg — 그 기사의 계기 한 줄(closest가 "0"이면 빈 칸).\n'
    '4) same — 두 계기가 같은 일이면 true, 아니면 false.\n'
    '\n'
    'same = true\n'
    '- 계기가 같다: 같은 발표·자료 공개·발언·처분·판결·사고·회의·통계에서 나온 기사다. 매체가 다르거나 제목이 뽑은 대목·각도가 달라도 같다(한 발표의 다른 항목을 '
    '앞세운 기사, 같은 자료를 해설한 기사 포함).\n'
    '- 둘 다 같은 대상을 새 계기 없이 정리·전망한 글이다(같은 국정감사의 일정·증인·전망, 같은 제도 시행 안내).\n'
    '\n'
    'same = false — 하나라도 해당하면 false\n'
    '- 새 기사의 계기가 이미 알린 기사보다 뒤에 새로 생긴 일이다: 새 발표·새 발언, 의원·기관이 새로 내놓은 자료·수치, [단독]으로 처음 밝힌 사실, 소송 제기·법안 '
    '발의, 증인 채택·철회, 시행 연기, 새 제재·처분·조사 착수. 같은 사건·같은 회사를 다루더라도 계기가 새로우면 false다(예: 과징금 부과 기사 뒤에 나온 취소 소송 '
    '제기 기사, 해킹 사고 해설 뒤에 나온 의원의 새 폭로 기사).\n'
    '- 주제·분야·시기만 같다(둘 다 개인정보 유출, 둘 다 과징금, 둘 다 AI, 둘 다 국정감사 철 기사).\n'
    '- 같은 회사·기관·의원·위원회의 다른 사안이다(같은 의원이 낸 다른 자료, 같은 기관의 다른 결정).\n'
    '- 다른 회사·기관에서 일어난 비슷한 일이다.\n'
    '- 연속 기획의 다른 회차(상·중·하)이고 다루는 내용이 다르다.\n'
    '- 제목 머리말([단독]·[기획]·[국감])이나 낱말 몇 개만 같다.\n'
    '\n'
    '「요지」는 자동으로 붙인 참고 줄이라 틀릴 수 있다 — 제목과 내용을 앞세운다.'
)

_MATCH_TOOL = {
    'name': 'record_matches',
    'description': '새 기사마다 계기가 가장 가까운 이미 알린 기사와, 두 기사의 계기가 같은 일인지를 기록한다. 입력된 모든 새 기사에 대해 한 줄씩.',
    'input_schema': {
        'type': 'object',
        'properties': {'results': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'id': {'type': 'integer', 'description': '새 기사 번호'},
                'peg': {'type': 'string', 'description': '새 기사의 계기 한 줄(40자 이내)'},
                'closest': {'type': 'string', 'description': '계기가 가장 가까운 이미 알린 기사의 기호 하나(A, B, C …). 없으면 "0". 새 기사 번호는 적지 않는다.'},
                'closest_peg': {'type': 'string', 'description': '그 기사의 계기 한 줄(40자 이내). closest가 "0"이면 빈 문자열.'},
                'same': {'type': 'boolean', 'description': '두 계기가 같은 일이면 true. 회사·주제·시기만 같으면 false.'},
            },
            'required': ['id', 'peg', 'closest', 'closest_peg', 'same']}}},
        'required': ['results'],
    },
}


def _match_line(tag: str, it: dict) -> str:
    """기사 한 줄 — '기호. 제목 | 요지: … | 내용: …'(요지·내용은 있을 때만, 내용은 공백을 눌러 MATCH_SNIP자)."""
    s = f"{tag}. {(it.get('title') or '').strip()}"
    ev = (it.get('event') or '').strip()
    sn = ' '.join(str(it.get('snip') or '').split())[:MATCH_SNIP]
    if ev:
        s += f' | 요지: {ev}'
    if sn:
        s += f' | 내용: {sn}'
    return s


def build_match_prompt(new_items: list, prior_items: list) -> str:
    """재보도 대조의 사용자 글 — 이미 알린 기사는 기호(A, B …), 새 기사는 번호(1, 2 …)."""
    prior = '\n'.join(_match_line(_MATCH_LETTERS[i], p) for i, p in enumerate(prior_items))
    new = '\n'.join(_match_line(str(i + 1), n) for i, n in enumerate(new_items))
    return f'[이미 알린 기사 {len(prior_items)}건]\n{prior}\n\n[새 기사 {len(new_items)}건]\n{new}'


def _parse_match(rows, n_new: int, n_prior: int) -> list:
    """도구 출력 results → 새 기사마다 「이미 알린 기사」 인덱스(0부터) 또는 None.
    **기사별로 읽는다** — same이 true이고 closest가 올바른 기호일 때만 그 기사를 '같은 소식'으로 친다. 번호가 범위 밖이거나
    기호가 어긋난 줄(새 기사 번호를 적은 경우 등), 같은 번호가 두 번 나와 답이 다른 경우는 그 기사만 '대조 없음'(None = 알림이
    나가는 쪽)이다. 묶기 분류기와 달리 통째로 버리지 않는 이유: 기사별 답은 서로 독립이라 한 줄의 흠이 다른 줄을 못 믿게
    하지 않고, 흠 있는 줄을 None으로 두는 것이 곧 fail-open이다."""
    got, seen = [None] * n_new, {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            i = int(r.get('id'))
        except (TypeError, ValueError):
            continue
        if not 1 <= i <= n_new:
            continue
        v = str(r.get('closest', '')).strip().upper()
        ans = _MATCH_LETTERS.index(v) if (r.get('same') is True and len(v) == 1 and v in _MATCH_LETTERS[:n_prior]) else None
        if i in seen and seen[i] != ans:
            ans = None                                   # 같은 번호에 다른 답 — 믿지 않는다
        seen[i] = ans
        got[i - 1] = ans
    return got


def match_prior_reports(new_items: list, prior_items: list, api_key: str, model: str = MATCH_MODEL,
                        timeout=None, max_retries=None, trace=None) -> list | None:
    """새 기사마다 같은 소식인 「이미 알린 기사」의 인덱스(0부터) 또는 None(새 소식)을 돌려준다. 기사 = {'title', 'event', 'snip'}.

    실패(호출 오류·응답 잘림·도구 출력 없음)한 묶음의 기사는 모두 None — 억제하지 않는다(fail-open). 모든 호출이 실패하면
    None(부르는 쪽은 원본 유지). 새 기사가 MATCH_MAX_NEW를 넘으면 나눠 부른다. timeout·max_retries는 group_same_event와 같은
    뜻(받는 단위별 알림의 짧은 제한) — 둘 다 None이면 SDK 기본값. trace(list)를 주면 묶음마다 (시작 위치, 도구 출력 줄들)을
    덧붙인다 — 실측 도구(tools_dedup_probe.py)가 판정기가 적은 계기를 보려고 쓴다(운영 경로는 주지 않는다)."""
    if not api_key or not new_items or not prior_items:
        return None
    prior_items = list(prior_items)[:len(_MATCH_LETTERS)]
    out, ok_any = [None] * len(new_items), False
    try:
        import anthropic
        client_kw = {}
        if timeout is not None:
            client_kw['timeout'] = timeout
        if max_retries is not None:
            client_kw['max_retries'] = max_retries
        client = anthropic.Anthropic(api_key=api_key, **client_kw)
    except Exception as e:
        print(f'[재보도 대조] 실패(원본 유지): {e}')
        return None
    for lo in range(0, len(new_items), MATCH_MAX_NEW):
        part = new_items[lo:lo + MATCH_MAX_NEW]
        try:
            resp = client.messages.create(
                model=model, max_tokens=min(4000, 300 + 260 * len(part)), temperature=0, system=_MATCH_SYSTEM,
                tools=[_MATCH_TOOL], tool_choice={'type': 'tool', 'name': _MATCH_TOOL['name']},
                messages=[{'role': 'user', 'content': build_match_prompt(part, prior_items)}],
            )
            if getattr(resp, 'stop_reason', '') == 'max_tokens':
                print(f'[재보도 대조] 응답이 잘림 — 이 묶음 {len(part)}건은 대조 없이 통과')
                continue
            blk = next((b for b in resp.content if getattr(b, 'type', '') == 'tool_use'), None)
            rows = (getattr(blk, 'input', None) or {}).get('results') if blk is not None else None
            if not isinstance(rows, list):
                print(f'[재보도 대조] 도구 출력 없음 — 이 묶음 {len(part)}건은 대조 없이 통과')
                continue
            out[lo:lo + len(part)] = _parse_match(rows, len(part), len(prior_items))
            ok_any = True
            if trace is not None:
                trace.append((lo, rows))
        except Exception as e:
            print(f'[재보도 대조] 실패(원본 유지): {e}')
    return out if ok_any else None
