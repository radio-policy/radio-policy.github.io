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
    """제목 → 비교용 키워드 집합. 한글 2자+ / 숫자+한글(금액: '원' 제거) / 영문 토큰(KT·5G)."""
    words = re.findall(r'[가-힣]{2,}', title or '')
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
