# -*- coding: utf-8 -*-
"""긴급도 판정 실측 (순서표 4-2·4-3, 2026-10-02) — 운영과 같은 호출(Haiku 4.5·온도 0·캐시 1h)로 조건만 바꿔 다시 판정한다.
실제 Haiku 호출, DB 쓰기 없음(api_usage 기록 제외 — site 'tools_urgency_probe.py:judge' / 문장 판정은 운영 라벨 그대로).

설계 local_docs/긴급도_판정구조_설계_261002.md 9절. 고정 자료 tests/fixtures/urgency_probe_cases.json = 기사 id·제목·정답만
(본문은 실행 때 news_feed에서 읽어 --out 폴더의 inputs.json 스냅숏으로 굳힌다 — 같은 스냅숏이면 변형끼리 입력이 바이트 단위로 같다).

  py -3.12 tools_urgency_probe.py --dry-run                              # 호출 수·어림 비용(API 0회, DB 읽기만)
  py -3.12 tools_urgency_probe.py --allow-api --variants B0,R3,G1,T1     # 실측(변형별 기본 세트) — 운영자 고지 뒤
  py -3.12 tools_urgency_probe.py --allow-api --variants G1,T1 --sets B --rep 2   # 같은 프롬프트 재실행(흔들림 바닥)
  py -3.12 tools_urgency_probe.py --allow-api --sentence                  # 주파수 문장 규칙(T-S) — 운영 판정기 그대로
  py -3.12 tools_urgency_probe.py --report                                # 통과 기준(설계 9-3) 대조표(API 0회)

변형(설계 9-2):
  B0  지금 배포 조합 그대로(기준문·피드백 블록·한 낱말 출력)                         세트 A·B·C
  R3  B0에서 #264-보론 세 줄(해외 주파수·성과·집계)만 뺌                              세트 A·B·C
  G1  1단계: 도구 출력 scope → grade → basis(기준문 글자 그대로)                      세트 A·B·C·D·S
  G1b 영역 칸을 등급 뒤에(G1이 통과 기준 a·c에서 걸릴 때만)                           세트 A·B·C
  T1  2단계: G1 + 기준문 v0.1(설계 4-2) + 피드백 49~53을 「보통」으로 옮긴 블록(4-3)    세트 A·B·C·D·S
  상한(G1·T1 출력 위에서 호출 없이): raw 없음 / R1 타영역 긴급 → 보통 / R2 R1 + 언저리 긴급 중 basis가 R2_KEEP 밖이면 보통

읽는 법:
  · 피드백 블록은 '지금' 행으로 운영 함수와 같은 글자를 만들되(스냅숏 때 crawler._feedback_fixed_block과 대조), 기사마다
    **그 기사 자신의 피드백 행은 뺀다**(운영자가 고친 기사가 자기 정답을 보기로 보고 맞히는 일 방지 — 고정·유사 블록 둘 다).
  · 같은 프롬프트는 한 번만 부른다(결과 파일 results.jsonl의 key = 프롬프트 지문). --rep 2는 같은 글자로 새로 부른다.
  · 정답은 측정 전에 고정했다. 틀려 보이면 보고서에 목록으로 올리고 고정 자료의 changed에 적는다(직접 고치지 말 것).
  · 기준문 문안(V01_EDITS)·세 줄(R3_TEXTS)·도구(urgency_tool)는 배포 때 crawler.py에 **이 글자 그대로** 옮긴다(09-30처럼
    「잰 것과 다른 글자를 배포」하지 않게). 운영 글자가 바뀌어 앵커가 안 맞으면 도구가 멈춘다(앵커 1곳 검사).
세션에서 돌릴 때 HTTP(S)_PROXY는 도구가 비운다.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(ROOT, 'tests', 'fixtures', 'urgency_probe_cases.json')
OUT_DEFAULT = os.path.join(ROOT, 'local_docs', 'urgency_probe')
MODEL = 'claude-haiku-4-5-20251001'
PRICE = {'in': 1.00, 'out': 5.00, 'cache_read': 0.10, 'cache_write_1h': 2.00}   # $/백만 토큰
CHARS_PER_TOKEN = 1.03          # 한국어 기준문 실측(#264 도구와 같은 어림)
TOOL_OVERHEAD_TOK = 350         # 도구 강제 때 API가 덧붙이는 시스템 글 어림
GRADE_MAP = {'즉시대응': '긴급', '금주검토': '보통', '동향파악': '참고'}
RANK = {'참고': 0, '보통': 1, '긴급': 2}

# ── 1단계 도구(설계 3-1 v0.1) ───────────────────────────────────────────────────────────────
SCOPES = ['통신', '언저리', '타영역']
BASES = ['통신사·통신망 사고', '대규모 유출', '국감 증인', '제도', '주파수', '정부·통신3사 공동', 'SKT 당사자',
         '플랫폼 개인정보', '경쟁사 공통 규제', '없음']
R2_KEEP = {'대규모 유출', '플랫폼 개인정보', '국감 증인', '제도'}     # 언저리에서도 즉시대응을 허용하는 근거(설계 3-2)
_TOOL_PROPS = {
    'scope': {'type': 'string', 'enum': SCOPES,
              'description': '0단계 영역 게이트. 통신 = 이동통신·전파·통신정책이 본론 / '
                             '언저리 = 통신·방송·정보보호 언저리지만 이동통신 사안은 아님 / 타영역 = 완전히 다른 영역'},
    'grade': {'type': 'string', 'enum': ['즉시대응', '금주검토', '동향파악'], 'description': '1단계 등급'},
    'basis': {'type': 'string', 'enum': BASES,
              'description': 'grade가 즉시대응일 때 적용한 즉시대응 항목 하나. 통신사·통신망 사고 = 통신사·통신망의 해킹·유출·장애 / '
                             '대규모 유출 = 플랫폼·부가통신의 수백만 계정 이상 또는 통신 이용자 피해로 이어진 유출. 즉시대응이 아니면 없음'},
}
TOOL_ORDERS = {'sgb': ('scope', 'grade', 'basis'), 'gsb': ('grade', 'scope', 'basis')}


def urgency_tool(order: str = 'sgb') -> dict:
    """record_urgency 도구 정의. strict(문법 제약)라 enum 밖 값·빠진 칸이 나오지 않는다 — 칸 순서 = 생성 순서.
    order 끝에 '-ns'가 붙으면 strict 없이(G1ns — 등급 쏠림이 strict 탓인지 가르는 변형)."""
    ns = order.endswith('-ns')
    keys = TOOL_ORDERS[order[:-3] if ns else order]
    t = {'name': 'record_urgency',
         'description': '기사 한 건의 판정을 기록한다. 칸은 ' + ' → '.join(keys) + ' 순서로 채운다.',
         'strict': True,
         'input_schema': {'type': 'object', 'properties': {k: _TOOL_PROPS[k] for k in keys},
                          'required': list(keys), 'additionalProperties': False}}
    if ns:
        del t['strict']
    return t


WORD_LINE = '아래 기준으로 셋 중 하나만 출력하세요 (다른 말 없이 단어만):'
TOOL_LINE = '아래 기준으로 판정해 record_urgency 도구로 기록하세요:'
# W2(#267 뒤 후보): 등급 낱말을 지금처럼 첫 줄에 먼저 쓰게 하고 영역은 둘째 줄 — 등급을 만들 때의 문맥을 지금 출력과 가깝게 둔다
W2_LINE = ('아래 기준으로 셋 중 하나를 첫 줄에 출력하고, 둘째 줄에는 0단계 영역 게이트의 결과를 「통신」·「언저리」·「타영역」 중 '
           '한 낱말로 출력하세요 (다른 말 없이 단어만):')
HEAD_OLD = '당신은 SK텔레콤 Comm센터 기술정책팀의 전파정책 모니터링 AI입니다.'
HEAD_V01 = '당신은 SK텔레콤 Comm센터의 통신정책 뉴스 모니터링 AI입니다.'

# ── R3: #264-보론(2026-09-30)이 넣은 세 줄 — 이 글자를 빼면 그 전 기준문이 된다 ─────────────────────────
R3_TEXTS = (
    # B 해외·국제기구 주파수
    "  · 여기서 주파수는 **국내 주파수 제도**(과기정통부의 할당·재할당·경매·대가·회수)를 말한다.\n"
    "    **해외 정부의 경매·할당·회수(미국 FCC 등)와 국제기구·해외 기관의 촉구·지침·세미나(ITU·WMO 등)는\n"
    "    국내 제도가 움직인 것이 아니다 → 금주검토** — 국내 통신장비주 수혜 분석이 붙어도 같다.\n"
    "    국제 회의가 국내 이동통신 대역의 분배·이용 조건을 실제로 결정한 보도만 즉시대응이다\n"
    "    (실측: 미국 주파수 경매의 국내 장비주 수혜 기사, WMO·ITU의 기상 관측용 주파수 보호 촉구 기사가 즉시대응이 됐다)\n",
    # C SKT 성과·수상·순위
    "  · **수상·순위·고객만족도 1위·품질 평가 우수 같은 성과 보도는 부정적 사안도 재무 이벤트도 아니다 → 금주검토**\n"
    "    — 본문이 지난 해킹·제재를 배경으로 언급해도 같다. 정부의 **이용자보호 업무 평가** 결과 공표만 위 제도 항목대로 즉시대응\n"
    "    (실측: 민간 기관의 고객만족도 조사 1위 보도, 해외 조사기관의 5G 어워드 보도가 즉시대응이 됐다)\n",
    # D 이미 부과된 처분의 집계·순위
    "  · 여기서 과징금·제재·소송은 **새로 생긴** 처분·사건을 말한다. **이미 부과된 과징금·과태료를 다시 합산한 집계·순위 자료와\n"
    "    연도별 회고**는 SK텔레콤 수치가 들어 있어도 새 사안이 아니다 → 금주검토\n"
    "    (실측: 「최근 3년간 개인정보 과징금 1조 육박」 집계 기사 13건이 즉시대응 7·금주검토 6으로 갈렸다)\n",
)

# ── V01: 2단계 공통 기준문 문안 v0.1(설계 4-2) — (지금 글자, 바꿀 글자). 머리 문장은 HEAD_V01 ──────────────────
V01_EDITS = (
    ('이동통신 품질·기지국·공공 와이파이·재난안전망·철도 통신망 등 공공 통신망의',
     '이동통신 품질·기지국·재난안전망·철도 통신망 등 공공 통신망의'),
    ('- **주파수가 본론인 기사** — 할당·재할당·경매·대가 산정·효율·간섭·회수',
     '- **국내 이동통신 주파수 제도를 정부가 정한 기사** — 할당·재할당·경매·대가 산정·회수의 확정·공고·의결, 정부안 발표'),
    ('  · ⚠️ **주파수가 본론이면 아래 "정책 논의 단계"보다 이 항목이 우선한다** — 세미나·학회·연구·전문가 제언\n'
     '    단계라도 즉시대응이다. 재할당 대가는 회사 비용에 직결되고, 제도 변화는 논의 단계에서 먼저 드러난다.',
     '  · ⚠️ **즉시대응은 정부가 실제로 정한 것까지다** — 세미나·학회·연구·전문가 제언·전망처럼\n'
     '    정부 결정 전의 논의 단계는 주파수가 본론이어도 금주검토다(아래 "정책 논의 단계"와 같다).'),
    ('본론이 전혀 다른 기사만 예외다 → 금주검토', '본론이 전혀 다른 기사는 이 항목이 아니다 → 금주검토'),
    ('기지국 구축은 그 자체가 팀 소관 사안이다**', '기지국 구축은 그 자체가 회사 본업 사안이다**'),
    ('    ⚠️ 경매·재할당·대가가 **기사의 축이면 관점이 무엇이든 즉시대응**',
     '    ⚠️ 정부가 정한 경매·재할당·대가가 **기사의 축이면 관점이 무엇이든 즉시대응**'),
    ('경매·재할당 일정이나 대가 자체를 분석하면 즉시대응, **수혜 종목 나열이 전부면 동향파악**.',
     '경매·재할당 일정이나 대가 자체를 분석하면 금주검토(정부가 확정·공고한 일정·대가면 즉시대응), **수혜 종목 나열이 전부면 동향파악**.'),
    ('  (단, **주파수가 본론이면 즉시대응이 우선** — 위 즉시대응 주파수 항목 참조)',
     '  (주파수 논의도 여기다 — 정부가 정한 것만 위 즉시대응 주파수 항목)'),
)

# ── 주파수 문장 규칙(설계 5절 v0.1) — 기술정책팀 min 긴급 ─────────────────────────────────────────────
SPECTRUM_WORDS = ['주파수', '재할당', '할당대가', '스펙트럼']
SPECTRUM_SENTENCE = ('국내 주파수 제도(할당·재할당·경매·대가 산정·회수)가 기사의 주장·결론인 기사. 정부 결정 전의 세미나·제언·전망 '
                     '단계도 포함한다. 해외·국제기구의 주파수, 다른 주제 기사에서 스친 언급, 기업의 특화망 전용 주파수 할당, '
                     '수혜 종목 나열은 해당하지 않는다.')
SPECTRUM_RULE = {'id': 'probe-spectrum', 'mode': 'min', 'level': '긴급', 'any_words': SPECTRUM_WORDS, 'enabled': True}

VARIANTS = {
    'B0': {'rubric': 'cur', 'tool': None, 'fb': 'now', 'sets': 'ABC'},
    'R3': {'rubric': 'R3', 'tool': None, 'fb': 'now', 'sets': 'ABC'},
    'G1': {'rubric': 'cur', 'tool': 'sgb', 'fb': 'now', 'sets': 'ABCDS'},
    'G1b': {'rubric': 'cur', 'tool': 'gsb', 'fb': 'now', 'sets': 'ABC'},
    'T1': {'rubric': 'V01', 'tool': 'sgb', 'fb': 'T1', 'sets': 'ABCDS'},
    # #267 뒤 형식 후보(운영자 승인 +$2) — G1이 등급을 크게 바꾼 원인을 가른다
    'W2': {'rubric': 'cur', 'tool': None, 'fb': 'now', 'sets': 'ABC', 'out': 'w2'},
    'G1ns': {'rubric': 'cur', 'tool': 'sgb-ns', 'fb': 'now', 'sets': 'ABC'},
    # 짧은 본문 보완(#267-보론)의 기준선 — 짧은 본문도 본문으로 쓰던 그 전 입력. 세트 X = --extra 파일의 기사
    'B0L': {'rubric': 'cur', 'tool': None, 'fb': 'now', 'sets': 'X', 'in': 'legacy'},
}


def _replace_once(text: str, old: str, new: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f'기준문 앵커가 {n}곳 — 운영 글자가 바뀌었다(도구를 고친 뒤 다시): {old[:50]}')
    return text.replace(old, new)


def criteria_of(cur: str, rubric: str) -> str:
    if rubric == 'cur':
        return cur
    if rubric == 'R3':
        for t in R3_TEXTS:
            cur = _replace_once(cur, t, '')
        return cur
    if rubric == 'V01':
        for old, new in V01_EDITS:
            cur = _replace_once(cur, old, new)
        return cur
    raise ValueError(rubric)


def intro_of(prod_intro: str, rubric: str, tool, out: str = '') -> str:
    s = prod_intro
    if tool:
        s = _replace_once(s, WORD_LINE, TOOL_LINE)
    elif out == 'w2':
        s = _replace_once(s, WORD_LINE, W2_LINE)
    if rubric == 'V01':
        s = _replace_once(s, HEAD_OLD, HEAD_V01)
    return s


def ws(s) -> str:
    return re.sub(r'\s+', ' ', s or '').strip()


# ═══════════════════════════════════════════════════════════════════════════════════════════
#  스냅숏 — 기사 입력·피드백 행·공통 규칙
# ═══════════════════════════════════════════════════════════════════════════════════════════

def load_fixture() -> dict:
    with open(FIXTURE, encoding='utf-8') as f:
        return json.load(f)


def all_ids(fx: dict) -> list:
    seen, out = set(), []
    for k in ('A', 'B', 'C', 'D'):
        for c in fx['sets'][k]:
            if c['id'] not in seen:
                seen.add(c['id']); out.append(c['id'])
    return out


def build_snapshot(fx: dict, path: str) -> dict:
    """news_feed 입력 + importance_feedback 공통 행 + 공통 규칙을 한 번 읽어 굳힌다(DB 읽기만)."""
    import crawler
    sb = crawler.sb
    ids = all_ids(fx)
    arts = {}
    for i in range(0, len(ids), 80):
        rows = sb.table('news_feed').select('id,title,content,screen_text').in_('id', ids[i:i + 80]).execute().data or []
        for r in rows:
            arts[r['id']] = {'title': r['title'], 'content': r.get('content') or '', 'screen_text': r.get('screen_text') or ''}
    missing = [i for i in ids if i not in arts]
    if missing:
        raise SystemExit(f'news_feed에 없는 기사 {len(missing)}건: {missing[:5]}')
    # 운영 _load_feedback_rows와 같은 조회(공통 행·updated_at 내림차순·500) + 자기 행 빼기·옮기기에 쓸 칸
    fb = sb.table('importance_feedback').select('id,title,user_importance,updated_at,news_id') \
        .is_('team_id', 'null').order('updated_at', desc=True).limit(500).execute().data or []
    fb = [r for r in fb if r.get('title') and r.get('user_importance')]
    rules = crawler.load_urgency_rules()
    # 운영 글자와 대조 — 고정 블록·유사 블록이 운영 함수와 바이트 단위로 같아야 '지금 배포 조합'이다
    prod_fixed = crawler._feedback_fixed_block()
    mine_fixed, _ = fixed_block(fb)
    if prod_fixed != mine_fixed:
        raise SystemExit(f'고정 피드백 블록이 운영 함수와 다르다(증류 규칙이 켜졌거나 조회 차이) — 길이 {len(prod_fixed)} / {len(mine_fixed)}')
    bad = 0
    for i in ids:
        t = arts[i]['title']
        if crawler._feedback_similar_block(t) != similar_block(t, fb, mine_fixed):
            bad += 1
    if bad:
        raise SystemExit(f'유사 사례 블록이 운영 함수와 다른 제목 {bad}건')
    snap = {'made': time.strftime('%Y-%m-%dT%H:%M:%S'), 'articles': arts, 'feedback': fb, 'rules': rules,
            'criteria': crawler._URGENCY_CRITERIA, 'system': crawler._URGENCY_SYSTEM}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False)
    print(f'[스냅숏] 기사 {len(arts)} · 피드백 공통 행 {len(fb)} · 공통 규칙 {len(rules)} → {path} (운영 블록 대조 통과)')
    return snap


# ═══════════════════════════════════════════════════════════════════════════════════════════
#  프롬프트 — 운영 crawler.classify_urgency와 같은 모양
# ═══════════════════════════════════════════════════════════════════════════════════════════
FB_HEAD = "\n\n[담당자 분류 피드백 — 실제 담당자가 직접 수정한 사례. 유사한 기사는 반드시 이 기준을 우선 적용]\n"
SIM_HEAD = "\n\n[이 기사와 제목이 거의 같은 담당자 수정 사례 — 같은 사건의 기사면 이 등급을 따른다]\n"
_REV = {'긴급': '즉시대응', '보통': '금주검토', '참고': '동향파악'}


def fb_line(r: dict) -> str:          # crawler._fb_line과 같은 글자
    return f"- \"{r['title'][:70]}\" → {_REV.get(r['user_importance'], r['user_importance'])}"


def fixed_block(rows: list, per_class: int = 12):
    """crawler._feedback_fixed_block(증류 규칙 없음)과 같은 글자 + 실린 행의 news_id 집합."""
    picked, per = [], {}
    for r in rows:
        c = r['user_importance']
        if per.get(c, 0) >= per_class:
            continue
        picked.append(r); per[c] = per.get(c, 0) + 1
    if not picked:
        return '', set()
    return FB_HEAD + "\n".join(fb_line(r) for r in picked), {r.get('news_id') for r in picked}


_TOK_CACHE = {}


def _tokens(title: str) -> set:
    if title not in _TOK_CACHE:
        import crawler
        _TOK_CACHE[title] = crawler._fb_tokens(title)
    return _TOK_CACHE[title]


def similar_block(title: str, rows: list, fixed: str) -> str:
    """crawler._feedback_similar_block과 같은 규칙(#264) — rows를 받는다(자기 행 빼기·옮긴 블록용)."""
    import crawler
    common = crawler._FB_COMMON
    tt = _tokens(title) - common
    if not rows or len(tt) < crawler.FB_SIMILAR_MIN:
        return ''
    scored = []
    for r in rows:
        ft = _tokens(r['title']) - common
        ov = len(tt & ft)
        if ov >= crawler.FB_SIMILAR_MIN and ov / min(len(tt), len(ft)) >= crawler.FB_SIMILAR_RATIO:
            scored.append((ov, r))
    sim = [r for sc, r in sorted(scored, key=lambda x: -x[0])]
    lines = [fb_line(r) for r in sim if fb_line(r) not in fixed][:crawler.FB_SIMILAR_MAX]
    return (SIM_HEAD + "\n".join(lines)) if lines else ''


def feedback_rows(snap: dict, fx: dict, mode: str) -> list:
    rows = [dict(r) for r in snap['feedback']]
    if mode == 'now':
        return rows
    if mode == 'T1':           # 설계 4-3: 주파수 논의 보기 5건을 공통 「보통」으로 — 대시보드 수정처럼 updated_at이 가장 최근이 된다
        move = set(fx['feedback_moves']['T1'])
        found = {r['id'] for r in rows if r['id'] in move}
        if found != move:
            raise SystemExit(f'옮길 피드백 행이 공통 행에 없다: {sorted(move - found)}')
        for r in rows:
            if r['id'] in move:
                if r['user_importance'] != '긴급':
                    raise SystemExit(f'피드백 {r["id"]}가 이미 긴급이 아니다({r["user_importance"]}) — 4-3 데이터 변경이 끝났는지 확인')
                r['user_importance'] = '보통'
                r['updated_at'] = '9999-12-31T00:00:00+00:00'
        rows.sort(key=lambda r: r['updated_at'], reverse=True)
        return rows
    raise ValueError(mode)


SHORT_BODY = 200      # crawler.URGENCY_SHORT_BODY와 같은 값(시험이 대조)


def user_msg(art: dict, mode: str = '') -> str:
    """crawler.classify_urgency의 사용자 메시지 — 본문 600자, 없으면 검색 요약 300자, 둘 다 없으면 제목만.
    본문이 SHORT_BODY자 미만이고 요약이 있으면 본문 없는 기사처럼 요약으로(#267-보론 — 짧은 본문의 절반이 사이트 메뉴 글자).
    mode='legacy' = 그 전 운영(짧은 본문도 본문으로) — 보완 실측의 기준선(B0L)."""
    snippet = ws(art.get('content'))[:600]
    summ = ws(art.get('screen_text'))[:300]
    if mode != 'legacy' and snippet and len(snippet) < SHORT_BODY and summ:
        snippet = ''
    if snippet:
        return f"제목: {art['title']}\n본문: {snippet}"
    if summ:
        return f"제목: {art['title']}\n요약: {summ}"
    return f"제목: {art['title']}"


class Builder:
    """변형 × 사례 → 호출 한 건의 재료(system 글·유사 블록·도구·사용자 메시지)."""

    def __init__(self, snap: dict, fx: dict):
        self.snap, self.fx = snap, fx
        self.prod_intro = snap['system'][:len(snap['system']) - len(snap['criteria'])]
        assert self.prod_intro + snap['criteria'] == snap['system']
        self._rows, self._fixed = {}, {}
        self.synth = {s['id']: s for s in fx['synth']}

    def rows(self, fb: str) -> list:
        if fb not in self._rows:
            self._rows[fb] = feedback_rows(self.snap, self.fx, fb)
        return self._rows[fb]

    def fixed(self, fb: str, exclude: str):
        """그 기사 자신의 행이 고정 블록에 실리면 그 행을 뺀 블록(13번째 행이 채운다)."""
        rows = self.rows(fb)
        k = (fb, None)
        if any(r.get('news_id') == exclude for r in rows):
            rows = [r for r in rows if r.get('news_id') != exclude]
            k = (fb, exclude)
        if k not in self._fixed:
            self._fixed[k] = fixed_block(rows)
        return self._fixed[k][0], rows

    def article(self, cid: str) -> dict:
        if cid in self.synth:
            s = self.synth[cid]
            return {'title': s['title'], 'content': s['body'], 'screen_text': ''}
        return self.snap['articles'][cid]

    def call(self, var: str, cid: str) -> dict:
        v = VARIANTS[var]
        art = self.article(cid)
        fixed, rows = self.fixed(v['fb'], cid)
        crit = criteria_of(self.snap['criteria'], v['rubric'])
        sys_text = intro_of(self.prod_intro, v['rubric'], v['tool'], v.get('out', '')) + crit + fixed
        sim = similar_block(art['title'], rows, fixed)
        tool = urgency_tool(v['tool']) if v['tool'] else None
        um = user_msg(art, v.get('in', ''))
        mt = 150 if tool else (20 if v.get('out') == 'w2' else 10)
        key = hashlib.sha1('\x00'.join([MODEL, str(mt), json.dumps(tool, ensure_ascii=False, sort_keys=False) if tool else '',
                                        sys_text, sim, um]).encode('utf-8')).hexdigest()
        prefix = hashlib.sha1(((json.dumps(tool, ensure_ascii=False) if tool else '') + '\x00' + sys_text).encode('utf-8')).hexdigest()[:12]
        return {'var': var, 'id': cid, 'sys': sys_text, 'sim': sim, 'tool': tool, 'user': um, 'max_tokens': mt,
                'key': key, 'prefix': prefix, 'out': v.get('out', '')}


def set_ids(fx: dict, sets: str, snap: dict = None) -> list:
    seen, out = set(), []
    for k in sets:
        if k == 'X':                                 # 임시 세트(--extra) — 정답 없음, 변형끼리 등급만 견준다
            src = [{'id': i} for i in (snap or {}).get('extra', [])]
        else:
            src = fx['synth'] if k == 'S' else fx['sets'][k]
        for c in src:
            if c['id'] not in seen:
                seen.add(c['id']); out.append(c['id'])
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════
#  호출
# ═══════════════════════════════════════════════════════════════════════════════════════════

def parse_response(resp, tool, out: str = '') -> dict:
    """도구 변형: tool_use 블록의 scope·grade·basis(값 검사). 실패면 운영 폴백과 같은 글 낱말 찾기(영역 없음).
    낱말 변형: 운영과 같은 글 낱말 찾기(없으면 참고)."""
    texts = [getattr(b, 'text', '') for b in resp.content if getattr(b, 'type', '') == 'text']
    if tool:
        for b in resp.content:
            if getattr(b, 'type', '') == 'tool_use':
                inp = b.input or {}
                g, s, ba = inp.get('grade'), inp.get('scope'), inp.get('basis')
                if g in GRADE_MAP and s in SCOPES and ba in BASES:
                    return {'grade': GRADE_MAP[g], 'scope': s, 'basis': ba, 'parse': 'ok', 'order': list(inp.keys()),
                            'raw': json.dumps(inp, ensure_ascii=False)}
                return {'grade': None, 'scope': s if s in SCOPES else None, 'basis': ba, 'parse': 'bad-value',
                        'order': list(inp.keys()), 'raw': json.dumps(inp, ensure_ascii=False)}
    answer = ' '.join(texts).strip()
    if out == 'w2':                                  # 첫 줄 등급 · 둘째 줄 영역(타영역 → 언저리 → 통신 순으로 찾는다)
        lines = [x.strip() for x in '\n'.join(texts).strip().split('\n') if x.strip()]
        g = next((v for k, v in GRADE_MAP.items() if lines and k in lines[0]), None)
        rest = ' '.join(lines[1:])
        s = next((x for x in ('타영역', '언저리', '통신') if x in rest), None)
        return {'grade': g or '참고', 'scope': s, 'basis': None, 'parse': 'ok' if g and s else 'fail', 'raw': answer[:80]}
    for k, v in GRADE_MAP.items():
        if k in answer:
            return {'grade': v, 'scope': None, 'basis': None, 'parse': 'text' if tool else 'ok', 'raw': answer[:80]}
    return {'grade': '참고', 'scope': None, 'basis': None, 'parse': 'fail' if tool else 'none', 'raw': answer[:80]}


def judge(client, item: dict) -> dict:
    """한 건 호출. ⚠️ client.messages.create를 이 함수 안에서 직접 — api_usage 라벨 'tools_urgency_probe.py:judge'."""
    blocks = [{'type': 'text', 'text': item['sys']}]
    if item.get('cache', True):                      # 한 번만 쓰는 접두(자기 피드백 행을 뺀 기사)는 캐시 쓰기(2배)를 하지 않는다
        blocks[0]['cache_control'] = {'type': 'ephemeral', 'ttl': '1h'}
    if item['sim']:
        blocks.append({'type': 'text', 'text': item['sim']})
    kw = {}
    if item['tool']:
        kw = {'tools': [item['tool']], 'tool_choice': {'type': 'tool', 'name': 'record_urgency'}}
    last = None
    for attempt in range(4):
        try:
            resp = client.messages.create(model=MODEL, max_tokens=item['max_tokens'], temperature=0, system=blocks,
                                          messages=[{'role': 'user', 'content': item['user']}], **kw)
            out = parse_response(resp, item['tool'], item.get('out', ''))
            u = resp.usage
            out.update({'in': getattr(u, 'input_tokens', 0) or 0, 'out': getattr(u, 'output_tokens', 0) or 0,
                        'cr': getattr(u, 'cache_read_input_tokens', 0) or 0, 'cw': getattr(u, 'cache_creation_input_tokens', 0) or 0,
                        'stop': resp.stop_reason})
            return out
        except Exception as e:                      # 429·529·연결 — 기다렸다 다시(4번)
            last = e
            time.sleep(4 * (attempt + 1))
    return {'grade': None, 'scope': None, 'basis': None, 'parse': 'error', 'raw': str(last)[:160]}


def load_results(path: str) -> list:
    out = []
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    return out


def est_cost(items: list) -> float:
    by_prefix = {}
    cost = 0.0
    for it in items:
        ptok = (len(it['sys']) + (len(json.dumps(it['tool'], ensure_ascii=False)) if it['tool'] else 0)) / CHARS_PER_TOKEN \
            + (TOOL_OVERHEAD_TOK if it['tool'] else 0)
        if not it.get('cache', True):
            cost += ptok * PRICE['in'] / 1e6
        elif it['prefix'] not in by_prefix:
            by_prefix[it['prefix']] = 1
            cost += ptok * PRICE['cache_write_1h'] / 1e6
        else:
            cost += ptok * PRICE['cache_read'] / 1e6
        cost += (len(it['sim']) + len(it['user'])) / CHARS_PER_TOKEN * PRICE['in'] / 1e6
        cost += (45 if it['tool'] else 4) * PRICE['out'] / 1e6
    return cost


def run_variants(a, fx, snap):
    b = Builder(snap, fx)
    res_path = os.path.join(a.out, 'results.jsonl')
    old = load_results(res_path)
    done = {(r['var'], r['rep'], r['id']) for r in old if r.get('parse') != 'error'}
    by_key = {r['key']: r for r in old if r.get('rep', 1) == 1 and r.get('parse') != 'error'}
    plan, reuse = [], []
    for var in a.variants.split(','):
        sets = a.sets or VARIANTS[var]['sets']
        for cid in set_ids(fx, sets, snap):
            if (var, a.rep, cid) in done:
                continue
            it = b.call(var, cid)
            it['rep'] = a.rep
            if a.rep == 1 and it['key'] in by_key:
                reuse.append(it)
            else:
                plan.append(it)
                if a.rep == 1:
                    by_key[it['key']] = {'pending': True}
    pcount = Counter(it['prefix'] for it in plan)
    for it in plan:
        it['cache'] = pcount[it['prefix']] > 1
    cost = est_cost(plan)
    per = Counter(it['var'] for it in plan)
    print(f'[계획] 변형 {a.variants} · rep {a.rep} → 새 호출 {len(plan)}회 ({dict(per)}) · 같은 프롬프트 재사용 {len(reuse)} · '
          f'이미 끝남 {len(done)} · 어림 ${cost:.2f}')
    print(f'        캐시 접두 {sum(1 for v in pcount.values() if v > 1)}종 + 한 번만 쓰는 접두 {sum(1 for v in pcount.values() if v == 1)}건'
          f'(자기 피드백 행을 뺀 기사 — 캐시 없이) · 상위 {pcount.most_common(3)}')
    if not a.allow_api:
        print('dry-run — 실제 호출은 --allow-api(운영자 고지 뒤)')
        return
    if cost > a.cap:
        raise SystemExit(f'어림 ${cost:.2f} > 상한 ${a.cap} — --cap으로 올리기 전에 운영자에게 묻는다')
    import anthropic
    import api_usage
    api_usage.install()
    import crawler
    client = anthropic.Anthropic(api_key=crawler.ANTHROPIC_API_KEY)
    lock = threading.Lock()
    fout = open(res_path, 'a', encoding='utf-8')
    t0 = time.time()

    def work(it):
        out = judge(client, it)
        row = {'var': it['var'], 'rep': it['rep'], 'id': it['id'], 'key': it['key'], 'prefix': it['prefix'],
               'sim': it['sim'].count('\n- ') if it['sim'] else 0, **out}
        with lock:
            fout.write(json.dumps(row, ensure_ascii=False) + '\n'); fout.flush()
            if it['rep'] == 1 and row.get('parse') != 'error':
                by_key[it['key']] = row
        return row

    first, rest, seen = [], [], set()
    for it in plan:                                  # 접두마다 첫 호출은 혼자(캐시 쓰기) — 나머지는 병렬
        (rest if it['prefix'] in seen else first).append(it)
        seen.add(it['prefix'])
    big = [it for it in first if sum(1 for x in plan if x['prefix'] == it['prefix']) > 1]
    lone = [it for it in first if it not in big]
    for it in big:
        work(it)
    errs = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for i, row in enumerate(ex.map(work, rest + lone), 1):
            errs += row.get('parse') == 'error'
            if i % 100 == 0:
                print(f'  {i}/{len(rest) + len(lone)} · {time.time() - t0:.0f}s · 오류 {errs}')
    for it in reuse:
        src = by_key.get(it['key']) or {}
        if 'grade' not in src:                       # 원본 호출이 오류였으면 다음 실행에서 다시
            continue
        row = {k: v for k, v in src.items() if k not in ('in', 'out', 'cr', 'cw')}
        row.update({'var': it['var'], 'rep': it['rep'], 'id': it['id'], 'reused': True})
        fout.write(json.dumps(row, ensure_ascii=False) + '\n')
    fout.close()
    rows = [r for r in load_results(res_path) if not r.get('reused')]
    tot = Counter()
    for r in rows:
        for k in ('in', 'out', 'cr', 'cw'):
            tot[k] += r.get(k, 0) or 0
    real = (tot['in'] * PRICE['in'] + tot['out'] * PRICE['out'] + tot['cr'] * PRICE['cache_read'] + tot['cw'] * PRICE['cache_write_1h']) / 1e6
    print(f'[끝] 호출 {len(plan)}회 · 오류 {errs} · {time.time() - t0:.0f}s · 결과 파일 누적 실비 ≈${real:.2f} → {res_path}')


# ═══════════════════════════════════════════════════════════════════════════════════════════
#  주파수 문장 규칙(T-S) — 운영 판정기 crawler._judge_sentence_batch 그대로
# ═══════════════════════════════════════════════════════════════════════════════════════════

def sentence_rows(fx, snap):
    import urgency_rules
    import crawler
    out = []
    for c in fx['sets']['D']:
        art = snap['articles'][c['id']]
        hit = urgency_rules.match_urgency_rules([SPECTRUM_RULE], art['title'],
                                                urgency_rules.rule_input_text(art['screen_text'], ''))
        out.append({'id': c['id'], 'hit': bool(hit), 'title': art['title'], 'snippet': art['screen_text'],
                    'body': crawler._sentence_body(art['content'])})
    for s in fx['synth']:                            # 합성은 검색 요약이 없어 본문 앞 300자를 요약 자리에(낱말 적중용)
        snip = ws(s['body'])[:300]
        hit = urgency_rules.match_urgency_rules([SPECTRUM_RULE], s['title'], snip)
        out.append({'id': s['id'], 'hit': bool(hit), 'title': s['title'], 'snippet': snip, 'body': s['body']})
    return out


def run_sentence(a, fx, snap):
    rows = sentence_rows(fx, snap)
    path = os.path.join(a.out, 'sentence.jsonl')
    sh = hashlib.sha1(SPECTRUM_SENTENCE.encode('utf-8')).hexdigest()[:10]
    done = {r['id'] for r in load_results(path) if r.get('sent') == sh and r.get('rep', 1) == a.rep}
    todo = [r for r in rows if r['hit'] and r['id'] not in done]
    import crawler
    n_calls = (len(todo) + crawler.SENTENCE_BATCH - 1) // crawler.SENTENCE_BATCH
    print(f'[문장] 낱말 적중 {sum(r["hit"] for r in rows)}/{len(rows)} · 판정할 것 {len(todo)}건 → {n_calls}회 (어림 ${len(todo) * 0.0022:.2f})')
    if not a.allow_api or not todo:
        if not a.allow_api:
            print('dry-run — 실제 판정은 --allow-api')
        return
    client = crawler._sentence_client()
    if client is None:
        raise SystemExit('ANTHROPIC_API_KEY 없음')
    cost = 0.0
    with open(path, 'a', encoding='utf-8') as f:
        for i in range(0, len(todo), crawler.SENTENCE_BATCH):
            chunk = todo[i:i + crawler.SENTENCE_BATCH]
            got, c = crawler._judge_sentence_batch(client, SPECTRUM_SENTENCE, chunk)
            cost += c
            for k, r in enumerate(chunk, 1):
                m, why = (got or {}).get(k, (None, ''))
                f.write(json.dumps({'id': r['id'], 'sent': sh, 'rep': a.rep, 'match': m, 'why': why}, ensure_ascii=False) + '\n')
    print(f'[문장] 끝 — 실비 ≈${cost:.3f} → {path}')


# ═══════════════════════════════════════════════════════════════════════════════════════════
#  보고 — 통과 기준(설계 9-3, 측정 전 고정)
# ═══════════════════════════════════════════════════════════════════════════════════════════

def cap(r: dict, mode: str):
    """출력 한 건의 등급 — raw(상한 없음) / R1(타영역 긴급 → 보통) / R2(R1 + 언저리 긴급 중 근거가 R2_KEEP 밖이면 보통)."""
    if r is None:
        return None
    g = r.get('grade')
    if g != '긴급' or mode == 'raw':
        return g
    if r.get('scope') == '타영역':
        return '보통'
    if mode == 'R2' and r.get('scope') == '언저리' and r.get('basis') not in R2_KEEP:
        return '보통'
    return g


def report(a, fx, snap):
    import urgency_rules
    res = {}
    for r in load_results(os.path.join(a.out, 'results.jsonl')):
        if r.get('parse') == 'error':
            continue
        res.setdefault((r['var'], r.get('rep', 1)), {})[r['id']] = r
    sent = {}
    sh = hashlib.sha1(SPECTRUM_SENTENCE.encode('utf-8')).hexdigest()[:10]
    for r in load_results(os.path.join(a.out, 'sentence.jsonl')):
        if r.get('sent') == sh and r.get('rep', 1) == 1:
            sent[r['id']] = r
    print('결과 있는 변형:', ', '.join(f'{v}#{rep} {len(res[(v, rep)])}건' for v, rep in sorted(res)),
          f'· 문장 판정 {len(sent)}건')
    A = {c['id']: c for c in fx['sets']['A']}
    B = {c['id']: c for c in fx['sets']['B']}
    C = {c['id']: c for c in fx['sets']['C']}
    D = {c['id']: c for c in fx['sets']['D']}
    S = {c['id']: c for c in fx['synth']}
    title = lambda i: (snap['articles'].get(i) or S.get(i) or {}).get('title', '')[:58]
    rules = snap['rules']

    def with_rules(i, g):                           # 공통 낱말 규칙(set·min)까지 — 운영 저장값
        if g is None or i in S:
            return g
        art = snap['articles'][i]
        return urgency_rules.combine(urgency_rules.match_urgency_rules(rules, art['title'], art['screen_text']), g)[0]

    def grade(var, i, mode='raw', rep=1, rules_on=False):
        r = res.get((var, rep), {}).get(i)
        g = cap(r, mode) if r else None
        return with_rules(i, g) if rules_on else g

    GU = [i for i, c in A.items() if c['gold'] == 'U'] + [i for i, c in C.items() if c['gold'] == 'U']
    GN = [i for i, c in A.items() if c['gold'] == 'N'] + [i for i, c in C.items() if c['gold'] == 'N']
    LOW = [i for i, c in C.items() if c['lowered']]
    out = {}

    def stab(var_a, var_b, ma='raw', mb='raw', ids=None, rep_b=1):
        ids = ids if ids is not None else list(B)
        pairs = [(grade(var_a, i, ma), grade(var_b, i, mb, rep=rep_b)) for i in ids]
        pairs = [(x, y) for x, y in pairs if x and y]
        t = Counter(pairs)
        diff = sum(v for (x, y), v in t.items() if x != y)
        drift = t[('보통', '참고')] - t[('참고', '보통')]
        return len(pairs), diff, drift, t

    # ── 1단계 ──
    if ('B0', 1) in res and ('G1', 1) in res:
        print('\n━━ 1단계 (B0 대 G1 + 상한) ━━  정답 긴급 n=%d · 정답 긴급 아님 n=%d · 운영자가 내린 9건' % (len(GU), len(GN)))
        base_u = sum(grade('B0', i) == '긴급' for i in GU)
        base_n = sum(grade('B0', i) == '긴급' for i in GN)
        base_l = sum(grade('B0', i) not in ('긴급', None) for i in LOW)
        print(f'  {"":10} 정답긴급→긴급  정답아님→긴급  내린9건→보통이하   (규칙 반영 시: 정답긴급·정답아님)')
        rows_out = {}
        for name, var, mode in (('B0', 'B0', 'raw'), ('G1-raw', 'G1', 'raw'), ('G1-R1', 'G1', 'R1'), ('G1-R2', 'G1', 'R2')):
            u = sum(grade(var, i, mode) == '긴급' for i in GU)
            n = sum(grade(var, i, mode) == '긴급' for i in GN)
            low = sum(grade(var, i, mode) not in ('긴급', None) for i in LOW)
            ur = sum(grade(var, i, mode, rules_on=True) == '긴급' for i in GU)
            nr = sum(grade(var, i, mode, rules_on=True) == '긴급' for i in GN)
            lost = [i for i in GU if grade(var, i, 'raw') == '긴급' and grade(var, i, mode) != '긴급'] if mode != 'raw' else []
            lost_r = [i for i in lost if grade(var, i, mode, rules_on=True) != '긴급']
            ok_a = u >= base_u - 2 and not lost
            ok_b = n <= base_n and low >= 6
            rows_out[name] = {'U': u, 'N': n, 'low9': low, 'U_rules': ur, 'N_rules': nr, 'cap_lost': lost, 'a': ok_a, 'b': ok_b}
            print(f'  {name:10} {u:4} / {len(GU)}     {n:4} / {len(GN)}     {low} / 9          ({ur}·{nr})'
                  + ('' if name == 'B0' else f'   a {"통과" if ok_a else "걸림"} · b {"통과" if ok_b else "걸림"}')
                  + (f'  상한으로 내려간 정답긴급 {len(lost)}건(규칙 하한 뒤 {len(lost_r)})' if mode != 'raw' else ''))
            for i in lost:
                print(f'       ↳ 상한 손실: {title(i)}  [{res[("G1", 1)][i].get("scope")}·{res[("G1", 1)][i].get("basis")}]')
        out['stage1'] = rows_out
        n, diff, drift, t = stab('B0', 'G1')
        ok_c = diff <= 9 and drift <= 3
        print(f'  c 안정성 60건: B0→G1 다름 {diff}/{n} · (보통→참고)−(참고→보통) = {drift}  → {"통과" if ok_c else "걸림"}   '
              + ', '.join(f'{x}→{y} {v}' for (x, y), v in t.items() if x != y))
        g1 = res[('G1', 1)]
        fails = [r for r in g1.values() if r.get('parse') != 'ok']
        nos = [r for r in g1.values() if not r.get('scope')]
        orders = Counter(tuple(r.get('order') or ()) for r in g1.values())
        print(f'  d 해석 실패 {len(fails)} · 영역 칸 누락 {len(nos)} → {"통과" if not fails and not nos else "걸림"}   (칸 생성 순서 {dict(orders)})')
        if ('G1', 2) in res:
            n2, d2, _, t2 = stab('G1', 'G1', ids=list(B), rep_b=2)
            sc = sum(1 for i in B if res[('G1', 2)].get(i) and res[('G1', 1)].get(i)
                     and res[('G1', 2)][i].get('scope') != res[('G1', 1)][i].get('scope'))
            print(f'  e 같은 프롬프트 재실행(B) 등급 다름 {d2}/{n2} → {"통과" if d2 <= 2 else "걸림"} (영역 다름 {sc})')
            out['stage1_e'] = d2
        else:
            print('  e 재실행 없음 — --variants G1 --sets B --rep 2')
        out['stage1_c'] = (diff, drift); out['stage1_d'] = (len(fails), len(nos))
        sc_ids = [i for i, c in C.items() if c['scope']]
        hit = sum(1 for i in sc_ids if g1.get(i, {}).get('scope') == C[i]['scope'])
        print(f'  (참고) 영역 칸 정확도: 기대 영역 {len(sc_ids)}건 중 일치 {hit} — ' +
              ', '.join(f'{C[i]["scope"]}→{g1.get(i, {}).get("scope")}' for i in sc_ids if g1.get(i, {}).get('scope') != C[i]['scope']))
        print('  운영자가 내린 9건:')
        for i in LOW:
            r = g1.get(i, {})
            print(f'    B0 {grade("B0", i)} · G1 {r.get("grade")}[{r.get("scope")}·{r.get("basis")}] R1 {cap(r, "R1")} R2 {cap(r, "R2")} | {title(i)}')
        flips = [(i, grade('B0', i), grade('G1', i)) for i in GU + GN if grade('B0', i) != grade('G1', i)]
        print(f'  B0→G1(raw) 정답 세트에서 바뀐 것 {len(flips)}건:')
        for i, x, y in flips:
            gold = (A.get(i) or C.get(i))['gold']
            r = g1.get(i, {})
            print(f'    정답 {gold} | {x}→{y} [{r.get("scope")}·{r.get("basis")}] | {title(i)}')

    # ── R3 ──
    if ('B0', 1) in res and ('R3', 1) in res:
        print('\n━━ R3 (세 줄만 뺌) 대 B0 ━━')
        for lab, ids in (('정답 긴급', GU), ('정답 긴급 아님', GN)):
            print(f'  {lab}: B0 긴급 {sum(grade("B0", i) == "긴급" for i in ids)} · R3 긴급 {sum(grade("R3", i) == "긴급" for i in ids)} / {len(ids)}')
        for g, lab in (('G4a', 'SKT 고객만족도(성과)'), ('G4c', '과징금 집계'), ('G7b', '해외 주파수')):
            ids = [i for i, c in A.items() if g in c['grp'].split(',')]
            print(f'  {lab} {len(ids)}건: B0 긴급 {sum(grade("B0", i) == "긴급" for i in ids)} · R3 긴급 {sum(grade("R3", i) == "긴급" for i in ids)}')
        dist = lambda v: Counter(grade(v, i) for i in B)
        n, diff, drift, t = stab('B0', 'R3')
        print(f'  안정성 60건 분포: B0 {dict(dist("B0"))} · R3 {dict(dist("R3"))} · 다름 {diff} (보통→참고 − 참고→보통 = {drift})')

    # ── G1b ──
    if ('G1b', 1) in res and ('B0', 1) in res:
        print('\n━━ G1b (영역 칸을 등급 뒤에) ━━')
        for mode in ('raw', 'R1', 'R2'):
            u = sum(grade('G1b', i, mode) == '긴급' for i in GU); n = sum(grade('G1b', i, mode) == '긴급' for i in GN)
            low = sum(grade('G1b', i, mode) not in ('긴급', None) for i in LOW)
            print(f'  G1b-{mode}: 정답긴급 {u} · 정답아님 {n} · 내린9건 {low}')
        n, diff, drift, t = stab('B0', 'G1b')
        print(f'  안정성: B0→G1b 다름 {diff}/{n}, 쏠림 {drift}')

    # ── T-S ──
    srows = sentence_rows(fx, snap)
    hitmap = {r['id']: r['hit'] for r in srows}
    if sent:
        print('\n━━ 주파수 문장 규칙 (T-S) ━━')
        teamU = [i for i, c in D.items() if c['team'] == 'U']
        team_only = [i for i in teamU if D[i]['common'] == 'N']
        s1 = sum(hitmap[i] for i in teamU); s1o = sum(hitmap[i] for i in team_only)
        print(f'  s1 기술정책팀 긴급 정답 {len(teamU)}건 중 낱말 적중 {s1} ({s1 / max(1, len(teamU)):.0%}) · 팀 전용 {len(team_only)}건 중 {s1o}  '
              f'→ {"통과" if s1 / max(1, len(teamU)) >= 0.95 else "걸림"}')
        for i in teamU:
            if not hitmap[i]:
                print(f'       ↳ 낱말 못 잡음: {title(i)} ({D[i]["note"][:40]})')
        yes = [i for i, c in D.items() if c['sent'] == 'Y' and hitmap[i]]
        s2 = sum(1 for i in yes if (sent.get(i) or {}).get('match') is True)
        hit_to = [i for i in team_only if hitmap[i]]
        s2o = sum(1 for i in hit_to if (sent.get(i) or {}).get('match') is True)
        print(f'  s2 문장 정답 「해당」 중 낱말 적중 {len(yes)}건 → 판정 해당 {s2} ({s2 / max(1, len(yes)):.0%}) · 팀 전용 적중 {len(hit_to)}건 → {s2o}  '
              f'→ {"통과" if s2 / max(1, len(yes)) >= 0.9 else "걸림"}')
        no = [i for i, c in D.items() if c['sent'] == 'N' and hitmap[i]]
        s3 = [i for i in no if (sent.get(i) or {}).get('match') is True]
        print(f'  s3 문장 정답 「아님」 중 낱말 적중 {len(no)}건 → 판정 해당 {len(s3)}  → {"통과" if len(s3) <= 2 else "걸림"}')
        for i in s3:
            print(f'       ↳ 아님인데 해당: {title(i)} — {(sent.get(i) or {}).get("why")}')
        for i in yes:
            if (sent.get(i) or {}).get('match') is not True:
                print(f'       ↳ 해당인데 아님: {title(i)} — {(sent.get(i) or {}).get("why")}')
        bset = [i for i, c in D.items() if c['sent'] == 'B' and hitmap[i]]
        print(f'  (경계 {len(bset)}건: 해당 {sum(1 for i in bset if (sent.get(i) or {}).get("match") is True)}) · '
              f'합성: ' + ', '.join(f'{i[-2:]}:{S[i]["sent"]}→{(sent.get(i) or {}).get("match")}' for i in S))
        out['ts'] = {'s1': (s1, len(teamU)), 's2': (s2, len(yes)), 's3': len(s3)}

    # ── 2단계 ──
    if ('G1', 1) in res and ('T1', 1) in res:
        m = a.cap_mode
        print(f'\n━━ 2단계 (G1 대 T1, 상한 {m}) ━━')
        newgold = {}
        for i, c in A.items():
            newgold[i] = c['gold']
        for i, c in C.items():
            newgold[i] = c['gold']
        for i, c in D.items():
            newgold[i] = c['common']
        U2 = [i for i, g in newgold.items() if g == 'U']
        g1u = sum(grade('G1', i, m) == '긴급' for i in U2); t1u = sum(grade('T1', i, m) == '긴급' for i in U2)
        print(f'  a 새 공통 정답 긴급 {len(U2)}건: G1 긴급 {g1u} · T1 긴급 {t1u}  → {"통과" if t1u >= g1u - 2 else "걸림"}')
        for i in U2:
            if grade('G1', i, m) == '긴급' and grade('T1', i, m) != '긴급':
                print(f'       ↳ T1에서 내려감: {title(i)}')
        team_only = [i for i, c in D.items() if c['common'] == 'N' and c['team'] == 'U']
        t_to = sum(grade('T1', i, m) == '긴급' for i in team_only); g_to = sum(grade('G1', i, m) == '긴급' for i in team_only)
        print(f'  b 팀 전용(논의 단계) {len(team_only)}건 중 공통 긴급: G1 {g_to} · T1 {t_to} ({t_to / max(1, len(team_only)):.0%})  '
              f'→ {"통과" if t_to <= 0.2 * len(team_only) else "걸림"}')
        corp = [i for i, s in S.items() if s['common'] == 'U'] + [i for i, c in D.items() if c['common'] == 'U' and i.startswith('16d6a643')]
        miss = [i for i in corp if grade('T1', i, m) != '긴급']
        print(f'     전사(정부가 정한 것) 합성 {len(corp) - 1} + 실제 1: T1 긴급 {len(corp) - len(miss)}/{len(corp)} (G1 {sum(grade("G1", i, m) == "긴급" for i in corp)})  '
              f'→ {"통과" if not miss else "걸림"}')
        for i in miss:
            r = res[('T1', 1)].get(i, {})
            print(f'       ↳ 전사인데 T1 {r.get("grade")}[{r.get("scope")}·{r.get("basis")}]: {title(i)}')
        other = [i for i in list(A) + list(B) if i not in D]
        n, diff, drift, t = stab('G1', 'T1', m, m, ids=other)
        print(f'  c 주파수 무관 {n}건: G1→T1 다름 {diff} ({diff / max(1, n):.0%}) · 쏠림 {drift}  → {"통과" if diff <= 0.1 * n and drift <= 3 else "걸림"}')
        if sent:
            def team_view(var, i):
                g = grade(var, i, m)
                if var == 'T1' and hitmap.get(i) and (sent.get(i) or {}).get('match') is True:
                    return '긴급'
                return g
            tg = [(i, c['team']) for i, c in D.items() if c['team'] in ('U', 'N')]
            ok = lambda var: sum(1 for i, gld in tg if (team_view(var, i) == '긴급') == (gld == 'U'))
            print(f'  d 기술정책팀이 보는 등급의 옛 정답 일치({len(tg)}건): G1 {ok("G1")} · T1+문장 규칙 {ok("T1")}  '
                  f'→ {"통과" if ok("T1") >= ok("G1") - 1 else "걸림"}')
        else:
            print('  d 문장 판정 결과 없음 — --sentence 먼저')
        if ('T1', 2) in res:
            n2, d2, _, _ = stab('T1', 'T1', m, m, ids=list(B), rep_b=2)
            print(f'  재실행(B) T1 등급 다름 {d2}/{n2}')
        flips = [(i, grade('G1', i, m), grade('T1', i, m)) for i in D if grade('G1', i, m) != grade('T1', i, m)]
        print(f'  S-D에서 G1→T1 바뀐 것 {len(flips)}건:')
        for i, x, y in flips:
            print(f'    전사 {D[i]["common"]}·팀 {D[i]["team"]} | {x}→{y} | {title(i)}')
    with open(os.path.join(a.out, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=list)


def main() -> int:
    ap = argparse.ArgumentParser(description='긴급도 판정 구조 실측(순서표 4-2·4-3)')
    ap.add_argument('--dry-run', action='store_true', help='호출 수·어림 비용만(API 0회, 기본)')
    ap.add_argument('--allow-api', action='store_true', help='실제 Haiku 호출(비용 발생, 운영자 고지 뒤)')
    ap.add_argument('--variants', default='B0,R3,G1,T1')
    ap.add_argument('--sets', default='', help='세트 덮어쓰기(A·B·C·D·S 글자) — 없으면 변형별 기본')
    ap.add_argument('--rep', type=int, default=1, help='2 이상이면 같은 프롬프트를 새로 부른다(흔들림)')
    ap.add_argument('--sentence', action='store_true', help='주파수 문장 규칙 판정(T-S)')
    ap.add_argument('--report', action='store_true', help='통과 기준 대조표(API 0회)')
    ap.add_argument('--cap-mode', default='R1', choices=['raw', 'R1', 'R2'], help='2단계 비교에 쓸 상한')
    ap.add_argument('--out', default=OUT_DEFAULT)
    ap.add_argument('--refresh', action='store_true', help='스냅숏을 DB에서 다시 읽는다(결과 key가 바뀔 수 있다)')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--cap', type=float, default=5.0, help='한 번 실행의 어림 비용 상한($, 설계 D7)')
    ap.add_argument('--extra', default='', help='임시 세트 X — 기사 id를 쉼표·줄바꿈으로 적은 파일(스냅숏에 더해 읽는다)')
    a = ap.parse_args()
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        os.environ.pop(k, None)
    fx = load_fixture()
    snap_path = os.path.join(a.out, 'inputs.json')
    if a.refresh or not os.path.exists(snap_path):
        snap = build_snapshot(fx, snap_path)
    else:
        with open(snap_path, encoding='utf-8') as f:
            snap = json.load(f)
        print(f'[스냅숏] {snap_path} ({snap["made"]}) — 기사 {len(snap["articles"])} · 피드백 {len(snap["feedback"])}')
    if a.extra:
        ids = [x.strip() for x in re.split(r'[,\s]+', open(a.extra, encoding='utf-8').read()) if x.strip()]
        need = [i for i in ids if i not in snap['articles']]
        if need:
            import crawler
            for i in range(0, len(need), 80):
                for r in crawler.sb.table('news_feed').select('id,title,content,screen_text').in_('id', need[i:i + 80]).execute().data or []:
                    snap['articles'][r['id']] = {'title': r['title'], 'content': r.get('content') or '',
                                                 'screen_text': r.get('screen_text') or ''}
        snap['extra'] = [i for i in ids if i in snap['articles']]
        with open(snap_path, 'w', encoding='utf-8') as f:
            json.dump(snap, f, ensure_ascii=False)
        print(f'[임시 세트 X] {len(snap["extra"])}건(새로 읽음 {len(need)})')
    for c in fx['sets']['A'] + fx['sets']['B'] + fx['sets']['C'] + fx['sets']['D']:
        if snap['articles'][c['id']]['title'] != c['title']:
            print(f'⚠️ 제목이 고정 자료와 다르다: {c["id"][:8]} {c["title"][:30]} / {snap["articles"][c["id"]]["title"][:30]}')
    if a.report:
        report(a, fx, snap)
    elif a.sentence:
        run_sentence(a, fx, snap)
    else:
        run_variants(a, fx, snap)
    return 0


if __name__ == '__main__':
    sys.exit(main())
