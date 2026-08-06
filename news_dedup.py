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
"""
import re

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


def group_same_event(titles: list, api_key: str, model: str = 'claude-haiku-4-5-20251001') -> list | None:
    """제목 목록 → 같은 사건끼리의 인덱스 그룹. 실패하면 None(호출부는 원본 유지 = fail-open).

    반환 예: [[0, 2, 3], [1]]  (0-based, 입력 순서 유지)
    """
    if not api_key or len(titles) < 2:
        return None
    try:
        import json as _json
        import anthropic
        listing = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(titles))
        resp = anthropic.Anthropic(api_key=api_key).messages.create(
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
