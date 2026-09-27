# -*- coding: utf-8 -*-
"""과방위 회의록 발언 블록 분야 분류 (#248, 2026-09-27) — 낱말 규칙, AI 0회.

인물 화면의 '과방위 발언 분야별 %' 막대용. assembly_speeches(통신·전파·AI 관련 발언만 회의당 30개까지
골라 담은 표)와 달리, 회의록의 **모든 발언 블록**을 발언자별로 세어 분야 대분류에 나눠 담는다.
본문은 DB에 저장하지 않는다(건수·글자 수만) — 원문은 저장소 밖 로컬 폴더(raw_dir)에 두고,
규칙을 바꾸면 그 파일로 다시 센다(speech_fields_backfill.py --from-raw, 재수신 없이 몇 분).

규칙 정본: 저장소 밖 `과방위_발언분야_분류검토_260927.md`(운영자 PC frequence 폴더) §2·§4·§5·§6.
  0단계 오탐 지우기(STRIP) → 복합어 먼저 판정 후 지움 → 가중 득점(내용어 1, 사업자·언론사·겸임기관명 0.5·블록당
  분야별 상한 1) → 최다 1표, 2위가 1위의 0.8배 이상이면 반분(그중 회의 기본 분야가 있으면 그쪽 1표) —
  고정 분야 우선순위는 쓰지 않는다(한쪽 쏠림).
  무낱말 블록: 막대 밖(잡음·위원장 사회·의사진행) → 같은 위원 질의 턴 이어받기(150자 이상 무낱말은 끊고 미분류)
  → 답변은 질문 분야 → 단일 피감기관 날 기본값 → 미분류. 위원장 직위 블록은 낱말로만 판정.
분야 목록·색 순서는 대시보드(app.js SPEECH_FIELDS)와 같아야 한다.
"""
import json
import os
import re
from collections import defaultdict

RULES_VERSION = 'v3-260927'   # v2: 샌드위치 이어받기·청문회 약한 기본값·소위 안건 흐름·소위 이름 STRIP / v3: 오탐 점검 반영(약신호 단독 무효 등)

# 표시 순서 고정(모든 인물 같은 색·같은 순서). app.js SPEECH_FIELDS 와 1:1.
FIELDS = ['통신·전파', 'AI·디지털', '보안·개인정보', '방송·미디어', '과학기술·R&D', '원자력·우주', '우정·기타']

# ── 0단계: 판정 전에 지운다(오탐 낱말) ─────────────────────────────
_STRIP = [
    r'[^.?!\n]{0,60}국회의원\s*[가-힣]{2,4}\s*입니다',     # 의원 자기소개 구호("…AI 디지털 …도시 국회의원 ○○○입니다")
    r'듣도\s*보도', r'보도\s*자료', r'(?:언론|기사|인터넷)\s*보도|보도에\s*따르면',
    r'전파(?:하|했|시키|되|된|될|돼|력|를\s*타)',          # '퍼뜨리다' 뜻의 전파
    r'연구(?:해|하|를)\s*(?:보|봐)',
    r'(?:예산|사업비)\S{0,3}\s*편성|미편성|편성(?:받|했|된|돼)',
    r'(?:법안|안건|예산|우선)\s*심의',
    r'단말기\s*자료',                                       # 개회사 "보고사항은 단말기 자료를 참고"
    r'국가보안법', r'국가보안기술연구소', r'개인정보\s*(?:문제|때문)',   # 자료 미제출 사유
    r'양자\s*(?:간|회담|협상|협의|협정|관계|택일)', r'노벨\s*(?:문학|평화|경제|번역)',
    r'과학기술정보방송통신위원회|미래창조과학방송통신위원회|과방위|미방위',
    # 소위원회 이름 — '정보통신방송법안심사소위'의 '방송', '과학기술원자력법안심사소위'의 '과학기술·원자력'이 사회 발언마다
    # 분야 점수를 줬다(2026-09-27 전수 실측, 2소위 방송 55%·1소위 이름 자체 적중)
    r'(?:정보통신방송(?:미디어)?|과학기술원자력|예산결산(?:기금)?|청원)\s*(?:법안)?\s*심사\s*소위(?:원회)?|법안\s*심사\s*소위(?:원회)?|제?\s*[12]\s*소위',
    r'방송통신발전기금|방발기금|정보통신진흥기금|정보통신망법|플랫폼',
    r'한국방송통신전파진흥원|방송(?:미디어)?통신사무소',       # 기관명 속 '방송·전파'
    r'(?:국가기간\s*)?뉴스\s*통신사|국가\s*기간\s*통신사|통신\s*사실\s*확인|통신\s*자료',   # 연합뉴스·수사 통신자료의 '통신사'
    r'정보통신망\s*이용\s*촉진\s*및\s*정보\s*보호\s*등에\s*관한\s*법률',           # 법률 이름 속 '정보보호'(오탐 점검 2026-09-27)
    r'위성\s*정당', r'우편으로',
]
STRIP_RE = re.compile('|'.join('(?:%s)' % p for p in _STRIP))

# ── 1단계: 복합어(긴 말 먼저) — 판정 후 지운다 ──────────────────────
_COMPOUND = {
    '통신·전파': r'위성\s*통신|저궤도(?:\s*위성)?|스타링크|해저\s*케이블',
    '방송·미디어': r'위성\s*방송|케이블\s*(?:TV|방송|SO)|딥\s*페이크|디지털\s*성\s*범죄',
    '보안·개인정보': r'유심\s*(?:해킹|복제|정보\s*유출)|양자\s*암호|(?:불법|초소형|가짜)\s*기지국',
    'AI·디지털': r'AI\s*반도체|AIDC|AI\s*데이터\s*센터',
}
COMPOUND_RE = {f: re.compile(p) for f, p in _COMPOUND.items()}

# ── 2단계: 내용어(1점) ─────────────────────────────────────────
_CONTENT = {
    '통신·전파': (r'통신사|이통\s*3사|통신\s*3사|이동\s*통신|알뜰폰|요금제|통신\s*(?:요금|비)|가계\s*통신비|(?<!전기)요금\s*인하|'
               r'단말(?:기)?\s*(?:지원금|보조금|유통|출고가)|단통법|번호\s*이동|주파수|전파|(?<![A-Za-z0-9])[56]G(?![A-Za-z])|'
               r'(?<![A-Za-z])LTE(?![A-Za-z])|기지국|(?<!정보)통신망|망\s*(?:사용료|이용\s*대가|중립)|전기\s*통신|기간\s*통신|부가\s*통신|'
               r'로밍|초고속\s*인터넷|와이파이|통신\s*장애|제4\s*이동|재난\s*문자|도메인|인터넷\s*주소'),
    'AI·디지털': (r'(?<![A-Za-z])AI(?![A-Za-z])|인공\s*지능|생성형|데이터\s*센터|(?<![A-Za-z])[GN]PU(?![A-Za-z])|'
                r'클라우드(?!\s*플레어)|소프트웨어|(?<![A-Za-z])SW(?![A-Za-z])|초거대|(?<![A-Za-z])LLM(?![A-Za-z])|'
                r'파운데이션\s*모델|소버린|챗\s*GPT|디지털\s*(?:전환|포용|격차|인프라|트윈)|메타버스|블록\s*체인|빅\s*데이터|'
                r'데이터\s*(?:산업|경제|기본법)|인앱\s*결제|앱\s*마켓'),
    # '보안' 단독은 '보안 프로그램(직원 사찰)'·'보안 직원'·'문서 보안'에 6/8 틀려(오탐 점검 2026-09-27) 복합형만 인정
    '보안·개인정보': (r'해킹|정보\s*보호|(?:정보|사이버|네트워크|통신|망|데이터|클라우드|국가|산업|기술)\s*보안|'
                  r'보안\s*(?:취약|사고|패치|인증|점검|관제|투자|업데이트|위협|강화|체계|기술|업체|솔루션|대책|인력|조치|정책|수준|역량|예산|공시|위기)|'
                  r'개인\s*정보\s*(?:유출|침해|보호\s*조치)|정보\s*유출|유출\s*사고|침해\s*사고|'
                  r'사이버\s*(?:공격|보안|안보|위협)|랜섬\s*웨어|디도스|악성\s*코드|'
                  r'스팸|스미싱|보이스\s*피싱|BPF\s*도어|펨토셀|무단\s*소액\s*결제|(?<![A-Za-z])ISMS|변작|대포폰'),
    '방송·미디어': (r'방송(?!\s*(?:미디어\s*)?통신\s*(?:위원회|심의\s*위원회|발전\s*기금|사무소))|공영\s*방송|지상파|종편|유료\s*방송|'
                 r'(?<![A-Za-z])IPTV(?![A-Za-z])|(?<![A-Za-z])OTT(?![A-Za-z])|(?<![A-Za-z])FAST(?![A-Za-z])|홈쇼핑|'
                 r'송출\s*수수료|수신료|방문진|(?:방송|통신|광고)\s*심의|심의\s*(?:제재|규정)|민원\s*사주|방심위|방미심위|'
                 r'허위\s*조작\s*정보|가짜\s*뉴스|포털\s*뉴스|유튜브|언론\s*(?:장악|자유|탄압|중재)|보도\s*(?:본부|책임|지침|개입)|'
                 r'편성\s*(?:책임|권|비율)|재허가|재승인|시청자|불법\s*(?:촬영물|사이트|정보)|코바코|댓글|여론\s*조작'),
    '과학기술·R&D': (r'R\s*&\s*D|연구\s*개발|출연연|국가과학기술연구회|(?<![A-Za-z])NST(?![A-Za-z])|연구\s*재단|연구자|연구진|'
                   r'연구\s*과제|연구비|과학\s*기술(?!\s*정보\s*(?:통신|방송))|기초\s*(?:과학|연구)|이공계|과학\s*기술인|'
                   r'(?<![A-Za-z])[GDU]IST(?![A-Za-z])|'
                   r'(?<![A-Za-z])IBS(?![A-Za-z])|예타|예비\s*타당성|(?<![A-Za-z])PBS(?![A-Za-z])|양자|바이오|반도체|'
                   r'국가\s*전략\s*기술|과학관|과학고|영재고|노벨\s*(?:물리|화학|생리|의학)|카르텔|박사\s*후|포닥|두뇌\s*유출|석\s*·?\s*박사'),
    '원자력·우주': (r'원자력|원전|원안위|(?<![A-Za-z])SMR(?![A-Za-z])|소형\s*모듈|방사선|방사능|후쿠시마|오염수|'
                 r'핵\s*(?:융합|연료|재처리|물질|비확산)|사용\s*후\s*핵\s*연료|(?<![A-Za-z])KINS(?![A-Za-z])|라돈|'
                 r'(?:고리|한빛|월성)\s*(?:원전|\d\s*호기)|우주|(?<![A-Za-z])KASA(?![A-Za-z])|누리호|발사체|(?<!우)위성|다누리|'
                 r'달\s*탐사|항우연|천문'),
    '우정·기타': r'우체국|우정\s*사업|우편|집배원',
}
CONTENT_RE = {f: re.compile(p) for f, p in _CONTENT.items()}

# ── 약신호(0.5점, 블록당 분야별 상한 1) — 사업자·언론사·겸임 기관명 ────────
_WEAK = {
    '통신·전파': r'SKT|SK\s*텔레콤|(?<![A-Za-z])KT(?![A-Za-z&])|LG\s*유플러스|LGU\+|유심(?!히)',
    '방송·미디어': (r'(?<![A-Za-z])(?:KBS|MBC|EBS|YTN|TBS|SBS|JTBC|KTV)(?![A-Za-z])|'
                 r'방송(?:미디어)?통신위원회|방통위|방미통위'),
    '보안·개인정보': r'(?<![A-Za-z])KISA(?![A-Za-z])|인터넷\s*진흥원',
    '과학기술·R&D': r'과학\s*기술원|(?<![A-Za-z])KAIST(?![A-Za-z])|카이스트',
}
WEAK_RE = {f: re.compile(p) for f, p in _WEAK.items()}
WEAK_ALONE = True    # 약신호만 있는 블록도 그 분야로 판정(정본 초안 그대로). False(v3) 비교: 낱말 91%↑이나 공방 턴 오판(막대 밖 일치 57%)·미분류 9.4% — 정답 대조 550블록 전체 일치 76.0% vs 78.4%(True). 배경역사 #248

# ── 막대 밖(건수만) ────────────────────────────────────────────
# 의사진행·자료요구·증인 채택·신상 — 득점 0일 때만. 강표지(사회를 보·위원장 자격·신상)는 득점 2 이하 무시.
PROC_RE = re.compile(r'의사\s*진행|자료\s*(?:제출|요구)|증인\s*(?:채택|출석)|동행\s*명령|고발|정회|산회|질의\s*시간|'
                     r'위원장석|사회를\s*보|신상|의결|이의\s*없')
PROC_STRONG_RE = re.compile(r'사회를\s*보|위원장\s*자격|신상\s*발언')
SUBCOMMITTEE_KINDS = ('1소위', '2소위', '예결소위', '청원소위')
AGENDA_POS_RE = re.compile(r'전문위원|입법조사관')           # 안건을 소개·검토보고하는 직위(소위 안건 흐름)
AGENDA_START_RE = re.compile(r'상정|의사\s*일정\s*제')
INHERIT_BREAK_LEN = 150       # 이보다 긴 무낱말 위원 블록은 이어받지 않고 끊는다(주제 전환 — 쿠팡→301조 통상 사례)
SPLIT_RATIO = 0.8             # 2위 ≥ 1위×0.8 이면 접전(반분)

# 과방위원 직위 — 질의 턴을 여는 쪽. 위원장 계열은 사회자라 턴을 끊지 않고, 낱말로만 판정한다.
MEMBER_POS = {'위원', '의원', '간사', '반장'}
CHAIR_POS = {'위원장', '위원장대리', '조정위원장', '소위원장', '소위원장대리', '소위원장직무대리', '위원장직무대리',
             '조정위원장직무대행', '위원장직무대행', '소위원장직무대행'}   # app.js _MEMBER_POS_SET 과 맞춘다

# 민간 증인·참고인(막대를 두지 않는다 — 질문→답변 연결에는 쓴다)
WITNESS_POS_RE = re.compile(r'증인|참고인|진술인|공술인')

# ── 회의 기본 분야: 단일 피감기관 날(국감)·단일 기관 인사청문 ───────────────
# 피감기관명 → 분야. 과기정통부처럼 여러 분야를 맡는 기관은 None(기본값 없음).
_AGENCY_FIELD = [
    (r'원자력|한국수력원자력|방사선', '원자력·우주'),
    (r'우주|위성운영|항공우주|천문', '원자력·우주'),
    (r'방송|시청자미디어|방송문화진흥회|언론', '방송·미디어'),
    (r'우정|우체국|우편', '우정·기타'),
    (r'인터넷진흥원|개인정보', '보안·개인정보'),
    (r'소프트웨어|정보통신산업진흥원|데이터산업진흥원|지능정보사회진흥원', 'AI·디지털'),
    (r'전파|전파관리소', '통신·전파'),
    (r'연구회|연구원|연구소|과학기술원|과학관|연구재단|기술원|과학기술기획평가원|과학창의재단|기초과학', '과학기술·R&D'),
]
_AGENCY_MULTI = re.compile(r'과학기술정보통신부|과기정통부|정보통신정책연구원')


def agency_field(name: str):
    """피감기관 1개 → 분야 or None(여러 분야 기관·모름)."""
    n = (name or '').strip()
    if not n or _AGENCY_MULTI.search(n):
        return None
    # '한국방송통신전파진흥원'은 방송·전파가 다 들어 있어 순서로 가르면 안 된다 — 통신·전파 기관(전파 관리)로 본다.
    if '방송통신전파진흥원' in n:
        return '통신·전파'
    for pat, f in _AGENCY_FIELD:
        if re.search(pat, n):
            return f
    return None


def meeting_info(m: dict) -> dict:
    """회의 종류·기본 분야. m 은 assembly_minutes 의 회의 dict(title, agenda, is_audit, audit_nm)."""
    title = m.get('title') or ''
    items = [re.sub(r'^\s*\d+\.\s*', '', a).strip() for a in (m.get('agenda') or [])]
    agenda = ' '.join(items)
    # 소위 이름만 본다 — 제목의 상위 위원회 이름('과학기술정보방송통신위원회')에 '과학기술'·'방송'이 다 들어 있다.
    sub = re.search(r'(\S+)소위원회', title)
    sub = sub.group(1) if sub else ''
    kind = '전체회의'
    if m.get('is_audit'):
        kind = '국정감사'
    elif sub:
        if '예산' in sub or '결산' in sub:
            kind = '예결소위'
        elif '청원' in sub:
            kind = '청원소위'
        elif '과학기술원자력' in sub:
            kind = '1소위'
        elif '정보통신방송' in sub:
            kind = '2소위'
        else:
            kind = '소위'
    # **첫(대표) 안건**이 청문회·공청회 자체인 날만('청문회 증인 출석요구의 건'·'인사청문요청안'·'공청회 개최의 건'이나
    # 법안 심사 뒤에 붙은 청문 안건은 아님) — 인사청문은 기본 분야를 주므로 섞인 날에 붙으면 무낱말 발언이 끌려간다.
    elif items and re.search(r'인사청문회$', items[0]):
        kind = '인사청문'
    elif items and re.search(r'공청회$', items[0]):
        kind = '공청회'
    elif items and re.search(r'청문회$', items[0]):
        kind = '청문회'
    default = None
    agencies = []
    if m.get('is_audit'):
        agencies = [a.strip() for a in re.split(r'[·,]', m.get('audit_nm') or '') if a.strip()]
        # 목록이 잘려 '…'로 끝나면 마지막 항목은 온전한 기관명이 아니다 — 빼고 본다
        agencies = [a for a in agencies if '…' not in a]
        fs = {agency_field(a) for a in agencies}
        if agencies and len(fs) == 1 and None not in fs:
            default = fs.pop()
    elif kind == '인사청문':
        mm = re.search(r'([가-힣]+(?:위원회|공사|부|청))\s*(?:위원장|사장|장관|청장)?\s*후보자', agenda)
        if mm:
            default = agency_field(mm.group(1))
    weak = False
    if not default and kind in ('청문회', '공청회') and items:
        # 한 주제 청문회·공청회('SK텔레콤 해킹 관련 청문회' → 보안·개인정보) — 대표 안건 제목이 한 분야로만 읽히면 그날의
        # **약한** 기본값(무낱말 블록의 마지막 기댈 곳, 공방 턴은 흡수하지 않음). 2026-09-27 전수 실측 뒤 추가(Fable 재검토).
        d = decide(score_text(items[0]))
        if len(d) == 1:
            default, weak = next(iter(d)), True
    return {'kind': kind, 'default': default, 'default_weak': weak, 'agencies': agencies}


def _norm(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()


def score_text(text: str) -> dict:
    """블록 본문 → {분야: 점수}. 0점 분야는 없음."""
    t = STRIP_RE.sub(' ', _norm(text))
    sc = defaultdict(float)
    for f, rx in COMPOUND_RE.items():
        n = len(rx.findall(t))
        if n:
            sc[f] += n
            t = rx.sub(' ', t)
    for f, rx in CONTENT_RE.items():
        n = len(rx.findall(t))
        if n:
            sc[f] += n
    if not sc and not WEAK_ALONE:
        # 약신호(사업자·언론사·기관 이름)만 있는 블록은 분야를 정하지 않는다 — 증인 소개·호명·인사말에서 대량으로 틀렸다
        # (오탐 점검 2026-09-27: SK텔레콤 7/8·KT 4/8·쿠팡 7/8 틀림). 이런 블록은 이어받기·기본값으로 간다.
        return {}
    for f, rx in WEAK_RE.items():
        n = len(rx.findall(t))
        if n:
            sc[f] += min(1.0, 0.5 * n)
    return {f: v for f, v in sc.items() if v > 0}


def decide(scores: dict, default=None) -> dict:
    """점수 → {분야: 표}. 최다 1표, 접전(2위 ≥ 1위×0.8)은 반분, 접전에 회의 기본 분야가 끼면 그쪽 1표."""
    if not scores:
        return {}
    best = max(scores.values())
    close = [f for f, v in scores.items() if v >= best * SPLIT_RATIO]
    if len(close) == 1:
        return {close[0]: 1.0}
    if default and default in close:
        return {default: 1.0}
    w = 1.0 / len(close)
    return {f: w for f in close}


def role_of(pos: str) -> str:
    p = (pos or '').strip()
    if p in MEMBER_POS:
        return 'member'
    if p in CHAIR_POS:
        return 'chair'
    return 'other'


def _is_noise(text: str) -> bool:
    # 발언 이력 적재와 같은 잡음 판정(assembly_minutes.is_noise_speech) — 순환 import 를 피해 늦게 부른다.
    from assembly_minutes import is_noise_speech
    return is_noise_speech(text)


def classify_blocks(blocks: list, info: dict) -> list:
    """블록별 판정. 반환 [{'kind': direct|inherit|agenda|default|unclassified|offtopic|noise|chair|proc, 'w': {분야: 표}}]."""
    default = info.get('default')
    res = []
    for b in blocks:
        t = _norm(b.get('text'))
        r = role_of(b.get('pos'))
        if _is_noise(t):
            res.append({'kind': 'noise', 'w': {}, 'role': r})
            continue
        sc = score_text(t)
        total = sum(sc.values())
        if PROC_STRONG_RE.search(t) and total <= 2:
            res.append({'kind': 'proc', 'w': {}, 'role': r})
            continue
        if sc:
            res.append({'kind': 'direct', 'w': decide(sc, default), 'role': r})
            continue
        if r == 'chair':
            res.append({'kind': 'chair', 'w': {}, 'role': r})
        elif PROC_RE.search(t):
            res.append({'kind': 'proc', 'w': {}, 'role': r})
        else:
            res.append({'kind': 'none', 'w': {}, 'role': r, 'len': len(t)})

    # 질의 턴: 과방위원이 말을 시작해 다른 위원이 말할 때까지(정부·증인 답변 포함, 위원장 사회는 경계 아님).
    turn, cur, k = [], None, -1
    for b, x in zip(blocks, res):
        if x['role'] == 'member' and (b.get('name') or '') != cur:
            cur = b.get('name') or ''
            k += 1
        turn.append(k)

    last = None          # 이 턴에서 질의자의 직전 판정(이어받기 원천)
    q = None             # 답변이 물려받을 질문 분야
    # 분야 낱말이 하나도 없는 턴(정쟁·사회 공방·진행만 오간 턴)은 '공방·진행'으로 막대 밖에 둔다(정본 §5 —
    # 22대 위원장 공방은 한 위원 국감 블록의 절반을 넘기도 한다). 턴 밖(첫 위원 발언 전) 블록은 여기 해당 없음.
    topical = set(turn[i] for i, x in enumerate(res) if x['kind'] == 'direct' and turn[i] >= 0)
    # 소위 안건 흐름(#248, 2026-09-27 전수 실측 뒤 추가 — 정본에 없는 확장, Fable 재검토): 법안·예산 심사 소위는 위원 질의 턴이
    # 아니라 '위원장 상정 → 전문위원 검토보고 → 차관·위원 조문 논의'로 흐른다. 조문 논의("22조 3항 삭제")는 분야 낱말이 없어
    # 턴 이어받기로는 미분류가 19~24%였다. 위원장·전문위원 블록의 판정을 '현재 안건 분야'로 두고, 무낱말 블록이 물려받는다.
    sub = info.get('kind') in SUBCOMMITTEE_KINDS
    weak = bool(info.get('default_weak'))
    agenda = None
    for i, (b, x) in enumerate(zip(blocks, res)):
        if i == 0 or turn[i] != turn[i - 1]:
            last, q = None, None
        if sub and (x['role'] == 'chair' or AGENDA_POS_RE.search(b.get('pos') or '')):
            if x['kind'] == 'direct':
                agenda = x['w']
            elif AGENDA_START_RE.search(_norm(b.get('text'))):
                agenda = None                    # 낱말 없는 안건 상정 — 앞 안건 분야를 끌고 가지 않는다
        # 기본 분야가 있는 날(단일 피감기관 국감·인사청문)도 공방 턴은 흡수하지 않는다 — 정답 대조(2026-09-27, 판정자 눈가림 550블록)에서
        # 규칙 오답의 대부분이 '기본값·이어받기로 분야를 받은 정쟁·신상 공방'(판정자 = 미분류)이었다.
        if x['kind'] == 'none' and turn[i] >= 0 and turn[i] not in topical and not (sub and agenda):
            x['kind'] = 'offtopic'
            continue
        if x['kind'] == 'direct':
            if x['role'] == 'member':
                last = q = x['w']
            continue
        if x['kind'] != 'none':
            continue
        if x['role'] == 'member':
            if x['len'] >= INHERIT_BREAK_LEN:
                # 긴 무낱말 발언은 주제 전환일 수 있다(쿠팡 → 미국 무역법 301조 통상, 정본 §5). 다만 같은 턴의 **앞뒤 판정이
                # 같으면** 주제가 이어진 것으로 보고 물려받는다(샌드위치 — 쿠팡 청문회의 '퇴사자 키 관리' 질의처럼 낱말만 없는
                # 같은 주제 발언이 22대 전수 2,865건 끊기고 있었다, 2026-09-27 실측 뒤 추가·Fable 재검토). 뒤가 없거나 다르면 끊는다.
                nxt = None
                for j in range(i + 1, len(blocks)):
                    if turn[j] != turn[i]:
                        break
                    if res[j]['kind'] == 'direct' and res[j]['role'] == 'member':
                        nxt = res[j]['w']
                        break
                if last and nxt and max(last, key=last.get) == max(nxt, key=nxt.get):
                    x['kind'], x['w'] = 'inherit', dict(last)
                    q = last
                    continue
                x['kind'] = 'unclassified'
                last = q = None
                continue
            src = last
            if src is None:
                # 턴 첫머리의 짧은 도입 발언("장관님, 하나 여쭙겠습니다") — 같은 턴 뒤쪽 첫 판정을 앞으로 당겨 쓴다
                for j in range(i + 1, len(blocks)):
                    if turn[j] != turn[i]:
                        break
                    if res[j]['role'] == 'member' and res[j]['kind'] == 'direct':
                        src = res[j]['w']
                        break
            if src:
                x['kind'], x['w'] = 'inherit', dict(src)
                last = q = src
                continue
        elif x['role'] == 'other' and turn[i] >= 0 and q:
            x['kind'], x['w'] = 'inherit', dict(q)
            continue
        if sub and agenda:
            x['kind'], x['w'] = 'agenda', dict(agenda)
            continue
        if default:
            x['kind'], x['w'] = 'default', {default: 1.0}
        else:
            x['kind'] = 'unclassified'
    return res


def speaker_key(name: str) -> str:
    from assembly_minutes import normalize_speaker
    return normalize_speaker(name)


def aggregate(blocks: list, res: list) -> dict:
    """(발언자, 직위)별 합계."""
    agg = {}
    for b, x in zip(blocks, res):
        key = (speaker_key(b.get('name')), (b.get('pos') or '').strip())
        a = agg.get(key)
        if a is None:
            a = agg[key] = {'n_blocks': 0, 'n_chars': 0, 'fields': defaultdict(float), 'field_chars': defaultdict(float),
                            'n_noise': 0, 'n_chair': 0, 'n_proc': 0, 'n_unclassified': 0,
                            'n_direct': 0.0, 'n_inherit': 0.0, 'n_default': 0.0}
        ln = len(_norm(b.get('text')))
        a['n_blocks'] += 1
        a['n_chars'] += ln
        # 공방·진행 턴은 의사진행과 같은 칸(막대 밖), 소위 안건 흐름은 이어받기 칸
        kd = {'offtopic': 'proc', 'agenda': 'inherit'}.get(x['kind'], x['kind'])
        if kd in ('noise', 'chair', 'proc', 'unclassified'):
            a['n_' + kd] += 1
            continue
        for f, w in x['w'].items():
            a['fields'][f] += w
            a['field_chars'][f] += ln * w
        a['n_' + kd] += 1
    return agg


def build_rows(m: dict, blocks: list, src: str = '') -> list:
    info = meeting_info(m)
    res = classify_blocks(blocks, info)
    rows = []
    for (spk, pos), a in aggregate(blocks, res).items():
        if not spk or spk == '미상':
            continue
        rows.append({
            'confer_num': str(m['confer_num']),
            'meeting_date': (m.get('conf_date') or None),
            'meeting_title': (m.get('title') or '')[:300] or None,
            'meeting_kind': info['kind'],
            'meeting_default': info['default'],
            'speaker': spk,
            'position': pos,
            'n_blocks': a['n_blocks'],
            'n_chars': a['n_chars'],
            'fields': {f: round(v, 2) for f, v in a['fields'].items() if v},
            'field_chars': {f: int(round(v)) for f, v in a['field_chars'].items() if v},
            'n_noise': a['n_noise'], 'n_chair': a['n_chair'], 'n_proc': a['n_proc'],
            'n_unclassified': a['n_unclassified'],
            'n_direct': round(a['n_direct'], 2), 'n_inherit': round(a['n_inherit'], 2),
            'n_default': round(a['n_default'], 2),
            'src': src or None,
            'rules_version': RULES_VERSION,
        })
    return rows


def default_raw_dir() -> str:
    """원문 보관 폴더 — **저장소 밖**(저장소는 공개, Pages가 모든 파일을 내보낸다). 환경변수로 바꿀 수 있다."""
    env = os.environ.get('SPEECH_RAW_DIR', '').strip()
    if env:
        return env
    repo = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(repo), '과방위_발언원문')


def raw_path(m: dict, raw_dir: str = None) -> str:
    d = raw_dir or default_raw_dir()
    year = (m.get('conf_date') or '0000')[:4]
    return os.path.join(d, year, '%s.json' % m['confer_num'])


def save_raw(m: dict, blocks: list, src: str, raw_dir: str = None) -> str:
    p = raw_path(m, raw_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    meta = {k: m.get(k) for k in ('confer_num', 'viewer_id', 'title', 'conf_date', 'agenda', 'is_audit',
                                  'audit_nm', 'pdf_url', 'dae_num')}
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fp:
        json.dump({'meeting': meta, 'src': src, 'blocks': blocks}, fp, ensure_ascii=False)
    os.replace(tmp, p)
    return p


def load_raw(path: str):
    with open(path, encoding='utf-8') as fp:
        d = json.load(fp)
    return d['meeting'], d['blocks'], d.get('src') or ''


def write_rows(sb, confer_num: str, rows: list) -> int:
    """회의 단위 통째 교체(발언자 구성이 바뀌어도 옛 행이 남지 않게)."""
    sb.table('speech_field_stats').delete().eq('confer_num', str(confer_num)).execute()
    for i in range(0, len(rows), 200):
        sb.table('speech_field_stats').insert(rows[i:i + 200]).execute()
    return len(rows)


def record_meeting(sb, m: dict, blocks: list, src: str = '', raw_dir: str = None) -> int:
    """수집 경로(assembly_minutes.run)에서 부르는 한 줄 — 원문 보관 + 분류 + 적재. 실패는 호출부가 삼킨다."""
    try:
        save_raw(m, blocks, src, raw_dir)
    except Exception as e:                       # 원문 보관 실패는 분류를 막지 않는다
        print('  [분야 원문 보관 실패(무시)] %s' % str(e)[:80])
    rows = build_rows(m, blocks, src)
    return write_rows(sb, m['confer_num'], rows)
