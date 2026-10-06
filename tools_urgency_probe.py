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

개인정보 좁은 질문(실측 폴더 local_docs/긴급도_개인정보원칙_실측_261006/, --out은 그 안의 probe):
  py -3.12 tools_urgency_probe.py --out <probe> --extract-w2              # 국감 주간 새 표본 W(10-06~10-12 KST)를 굳힘 + 정답 매김 입력
  py -3.12 tools_urgency_probe.py --out <probe> --privacy --runs Q2:ABCX,Q2:W,L1:W   # 어림만 → --allow-api(운영자 고지 뒤, 한 번)
  py -3.12 tools_urgency_probe.py --out <probe> --privacy-report          # P1~P6(판정 §5) + R-a~R-d → 결과_Q2.md·probe/q2_join.json

변형(설계 9-2):
  B0  지금 배포 조합 그대로(기준문·피드백 블록·한 낱말 출력)                         세트 A·B·C
  R3  B0에서 #264-보론 세 줄(해외 주파수·성과·집계)만 뺌                              세트 A·B·C
  G1  1단계: 도구 출력 scope → grade → basis(기준문 글자 그대로)                      세트 A·B·C·D·S
  G1b 영역 칸을 등급 뒤에(G1이 통과 기준 a·c에서 걸릴 때만)                           세트 A·B·C
  T1  2단계: G1 + 기준문 v0.1(설계 4-2) + 피드백 49~53을 「보통」으로 옮긴 블록(4-3)    세트 A·B·C·D·S
  P1  B0 + 개인정보·해킹 원칙(2026-10-06 운영자 결정, P1_EDITS)                           세트 A·B·C·X
  좁은 질문(--privacy, 등급 호출은 그대로): L1 시제품(모델이 통신 연결까지 판단) / Q2 사실만 적고 내림은 코드(privacy_lower)
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

# ── P1: 개인정보·해킹 원칙(운영자 결정 2026-10-06) — (지금 글자, 바꿀 글자) ─────────────────────────────────────
# 통신과 연결되지 않은 유출은 새로 터진 대규모 사고의 첫 보도만 즉시대응, 후속은 금주검토. 통신사·통신망·통신 이용자 피해와
# 연결된 사건은 후속이어도 새 소식·비판이면 즉시대응. 근거 local_docs/긴급도_개인정보원칙_실측_261006/
P1_EDITS = (
    ('  · 통신사·통신망의 해킹·개인정보 유출·대규모 장애·먹통 — **자사·경쟁사를 가리지 않는다**\n',
     '  · 통신사·통신망의 해킹·개인정보 유출·대규모 장애·먹통 — **자사·경쟁사를 가리지 않는다**\n'
     '    — 통신사·통신망·통신 이용자 피해와 연결된 사건은 **후속이어도 새 소식이나 비판이 나오면 즉시대응**이다\n'),
    ('  · 플랫폼·부가통신 사업자의 **대규모** 개인정보 유출과 그 조사·보상·제재 경과\n',
     '  · 플랫폼·부가통신 사업자의 **대규모** 개인정보 유출이 **새로 터진 것**\n'),
    ('      (예: 3,954만 계정이 털린 OTT 유출, 통신사 보상으로 준 이용권 계정이 재유출된 사건 → 즉시대응)\n',
     '      (예: 3,954만 계정이 털린 OTT 유출, 통신사 보상으로 준 이용권 계정이 재유출된 사건 → 즉시대응)\n'
     '    — **통신과 연결되지 않은 유출은 새로 터진 사고의 첫 보도만 즉시대응이다**(유출 사실·규모·원인이 처음 드러난 보도).\n'
     '      그 뒤의 후속 — 보상안·보상 신청률, 국감·의원실 지적, 통계·집계, 기업의 문구·조직 변경, 규제기관의 권한 미행사 비판,\n'
     '      조사·수사 경과, 이용자 반응, 보안 대책 — 은 규모가 커도 → 금주검토\n'
     '      (실측: 쿠팡 유출 뒤 CPO 지정 문구 삭제 지적, 티빙 보상 신청률, 카카오페이 정보 국외이전에 중지명령 0건 기사가 즉시대응이 됐다)\n'),
    ('  · 사고 대응의 적정성이 쟁점이 된 보도 — 신고 지연, 로그 삭제, 증거인멸, 조사 방해 의혹\n'
     '  · 진행 중인 침해사고·제재 사건의 수사·조사·소송 경과와 선고·처분 일정\n',
     '  · **통신사·통신망 사고**에서 대응의 적정성이 쟁점이 된 보도 — 신고 지연, 로그 삭제, 증거인멸, 조사 방해 의혹\n'
     '  · 진행 중인 **통신사·통신망** 침해사고·제재 사건의 수사·조사·소송 경과와 선고·처분 일정\n'
     '    (통신과 연결되지 않은 사건의 이런 후속은 위 플랫폼 유출 항목대로 → 금주검토)\n'),
    ('  · **이용자보호 업무 평가의 결과·등급 공표**는 특정 사업자 성과 보도처럼 보여도 제도 사안이다 → 즉시대응\n',
     '  · **이용자보호 업무 평가의 결과·등급 공표**는 특정 사업자 성과 보도처럼 보여도 제도 사안이다 → 즉시대응\n'
     '  · 통신과 연결되지 않은 회사에 대한 처분(과징금 부과·시정명령 등)은 **처분이 처음 나온 보도만** 즉시대응이다.\n'
     '    그 뒤의 후속 — 불복·소송, 해설, 집계·비교, 재보도 — 은 → 금주검토\n'),
)

# ── 주파수 문장 규칙 — 기술정책팀 min 긴급 ─────────────────────────────────────────────────────────────
# v0.1(설계 5절): s3 「아님」 6건 해당으로 불통과(#267). v0.2(판정 local_docs/긴급도_2단구조_판정_261002.md 4절): 포함에서
# 「전망」을 빼고(증권 2건의 원인), 주어를 「한국 정부의 이동통신 주파수」로, 제외를 걸린 것 그대로(특화망·증권·무선충전) 적음.
# 결과 파일 sentence.jsonl은 문장 지문(sent)으로 갈리므로 옛 판 결과는 그대로 남는다.
SPECTRUM_WORDS = ['주파수', '재할당', '할당대가', '스펙트럼']
SPECTRUM_SENTENCE_V01 = ('국내 주파수 제도(할당·재할당·경매·대가 산정·회수)가 기사의 주장·결론인 기사. 정부 결정 전의 세미나·제언·전망 '
                         '단계도 포함한다. 해외·국제기구의 주파수, 다른 주제 기사에서 스친 언급, 기업의 특화망 전용 주파수 할당, '
                         '수혜 종목 나열은 해당하지 않는다.')
SPECTRUM_SENTENCE = ('한국 정부의 이동통신 주파수 할당·재할당·경매·대가 산정·회수 제도를 어떻게 정할지가 기사의 주장·결론인 기사. '
                     '정부 결정 전의 세미나·제언·연구반 검토도 포함한다. 해외 주파수, 5G 특화망(이음5G), 증권·종목 기사, '
                     '무선충전 등 이동통신 밖의 주파수, 다른 주제 기사에서 스친 언급은 해당하지 않는다.')
SPECTRUM_RULE = {'id': 'probe-spectrum', 'mode': 'min', 'level': '긴급', 'any_words': SPECTRUM_WORDS, 'enabled': True}

# ── 개인정보 좁은 질문(시제품, 2026-10-06 — 결과_P1.md 「다음 후보」) ─────────────────────────────────────────
# 등급 호출은 글자 그대로 두고, B0가 긴급이라 한 기사 중 제목·검색 요약에 아래 낱말이 있는 것만 따로 묻는다.
# 내리는 조건(privacy_lower): 개인정보·해킹 사건 + 통신 무관 + (후속 | 소규모 사고). 나머지는 긴급 그대로.
PRIV_WORDS = re.compile(r'(유출|해킹|개인정보|침해|털렸|털린|털려|랜섬|정보보호|보안|과징금|국외이전|크리덴셜|스미싱|피싱|도청|탈취|악성코드|디도스|사이버)')
PRIV_SYSTEM = (
    '당신은 SK텔레콤 Comm센터의 통신정책 뉴스 모니터링 AI입니다.\n'
    '아래 기사는 1차 판정에서 즉시대응(긴급)으로 분류됐습니다. 운영자의 개인정보·해킹 원칙에 따라 긴급을 유지할지 가리기 위해\n'
    '기사를 읽고 record_privacy_check 도구로 기록하세요.\n\n'
    '[운영자 원칙]\n'
    '1. 통신사·통신망·통신 서비스·통신 이용자 피해와 연결된 사건은 후속이어도 새 소식이나 비판이면 긴급이다.\n'
    '2. 통신과 연결되지 않은 사건(OTT·쇼핑몰·플랫폼·은행·금융사·공공기관·군·일반 기업 등)은\n'
    '   수백만 명·계정 이상의 유출이 새로 드러난 첫 보도와, 그 회사에 대한 정부 처분이 처음 나온 보도만 긴급이다.\n'
    '   그 뒤의 후속 — 보상안·보상 신청률, 국감·의원실 지적, 통계·집계, 기업의 문구·조직 변경, 규제기관의 권한 미행사 비판,\n'
    '   조사·수사 경과, 이용자·시민 반응, 보안 대책·해설·기고, 예방 캠페인·주의보 — 은 긴급이 아니다.\n'
    '   수백만 미만 규모의 유출·해킹은 첫 보도도 긴급이 아니다.\n'
    '3. 법·시행령·고시의 제개정과 시행, 정부가 통신 3사와 함께 하는 회동·사업은 이 원칙 밖이다.\n'
)
PRIV_TOPICS = ['개인정보·해킹 사건', '그 밖']
PRIV_TELECOM = ['통신 연결', '통신 무관']
PRIV_STAGES = ['대규모 새 사고 첫 보도', '처분 첫 보도', '제도·정부-통신3사', '후속', '소규모 사고']
PRIV_TOOL = {
    'name': 'record_privacy_check',
    'description': '기사 한 건의 개인정보·해킹 원칙 확인을 기록한다. 칸은 topic → telecom → stage → why 순서로 채운다.',
    'strict': True,
    'input_schema': {'type': 'object', 'additionalProperties': False,
                     'required': ['topic', 'telecom', 'stage', 'why'],
                     'properties': {
                         'topic': {'type': 'string', 'enum': PRIV_TOPICS,
                                   'description': '개인정보·해킹 사건 = 개인정보 유출·해킹·침해사고와 그 처분·보상·조사·후속이 기사의 본론 / '
                                                  '그 밖 = 그 외(보안이라는 낱말만 스친 기사 포함)'},
                         'telecom': {'type': 'string', 'enum': PRIV_TELECOM,
                                     'description': '통신 연결 = SK텔레콤·KT·LG유플러스 등 통신사, 통신망, 통신 서비스, 통신 이용자 피해가 '
                                                    '이 사건의 당사자·본론(여러 기업을 다루면 통신사가 당사자로 들어 있을 때) / '
                                                    '통신 무관 = 통신이 앞선 사건·비교 사례·배경으로만 스치거나 아예 없음'},
                         'stage': {'type': 'string', 'enum': PRIV_STAGES,
                                   'description': '대규모 새 사고 첫 보도 = 수백만 이상 유출이 새로 드러남 / 처분 첫 보도 = 정부 처분이 처음 나옴 / '
                                                  '제도·정부-통신3사 = 원칙 3번 / 후속 = 원칙 2번의 후속 목록 / 소규모 사고 = 수백만 미만 유출·해킹'},
                         'why': {'type': 'string', 'description': '판단 근거 한 줄(40자 안)'},
                     }},
}
PRIV_LOWER_STAGES = {'후속', '소규모 사고'}


def privacy_hit(art: dict) -> bool:
    return bool(PRIV_WORDS.search((art.get('title') or '') + ' ' + ws(art.get('screen_text'))))


def privacy_lower_l1(out: dict, art: dict = None) -> bool:
    """L1(시제품) 내림 조건 — 모델이 telecom 칸으로 통신 연결까지 정한다. Q2의 같은 표본 기준선."""
    return (out.get('topic') == '개인정보·해킹 사건' and out.get('telecom') == '통신 무관'
            and out.get('stage') in PRIV_LOWER_STAGES)


# ── 개인정보 좁은 질문 Q2(Fable 판정 2026-10-06, 실측 폴더 판정_좁은질문_261006.md §3) ─────────────────────────
# 모델은 사실만 적고 내릴지는 코드(privacy_lower)가 정한다. system·tool·user는 판정 문서의 글자 그대로 — 시험이 해시로 잠근다
# (tests/test_urgency_probe.py). 칸 순서(parties → topic → stage → scale → why)도 측정값이라 바꾸면 다시 잰다.
Q2_SYSTEM = (
    '당신은 SK텔레콤 Comm센터의 통신정책 뉴스 모니터링 AI입니다.\n'
    '아래 기사는 긴급(즉시대응)으로 분류돼 있습니다. 긴급을 유지할지는 프로그램이 정합니다 — 당신은 기사에서 읽히는\n'
    '사실만 record_privacy_check 도구의 칸에 그대로 적습니다. 결론을 먼저 정하고 칸을 거기에 맞추지 마세요.\n'
    '\n'
    '[칸 채우는 기준]\n'
    '· parties(당사자): 이 기사에서 당사자로 나오는 회사·기관 이름 — 사고가 난 회사, 증인·소환 대상, 제재·조사·점검 대상,\n'
    '  보상을 주는 회사, 비판받는 회사, 공동 선언·회동의 주체. 앞선 사건·비교·배경으로 한 줄 스치는 이름은 넣지 않는다.\n'
    '  기사에 쓰인 표기 그대로(「SK텔레콤」「통신 3사」 등), 없으면 빈 목록.\n'
    '· topic(본론): 「특정 유출·해킹 사건」 = 어느 회사·기관의 개인정보 유출·해킹·침해사고(또는 같은 시기의 몇 건)가 축인 기사 —\n'
    '  사고 자체만이 아니라 그 사건의 뒷이야기(보상·보상 신청률, 조사·수사 경과, 처분, 국감·의원실 지적, 소송, 통계,\n'
    '  회사의 사과·대책·문구 변경, 피해 사례, 이용자 반응)도 여기다 / 「법·제도·정책 일반」 = 법·시행령·고시의 제개정·시행,\n'
    '  정부·위원회의 정책·대책·예산·조직, 캠페인·주의보, 제도 해설·기고 / 「그 밖」 = 사업·실적·증권, 특정 사건이 축이 아닌\n'
    '  국감·정치 공방 등.\n'
    '· stage(단계) — 본론이 「특정 유출·해킹 사건」일 때만: 「사고 첫 보도」 = 유출·해킹 사실·규모·원인이 이 기사에서 처음 알려짐\n'
    '  (회사 공지, 정부 조사결과 발표, 같은 날의 사과 포함) / 「처분 첫 보도」 = 그 회사에 대한 과징금·과태료·시정명령 등 처분이\n'
    '  처음 나옴 / 「뒷이야기」 = 이미 알려진 사건의 그 밖의 모든 보도. 본론이 사건이 아니면 「해당 없음」.\n'
    '· scale(규모) — 본론이 사건일 때 기사에 적힌 유출·피해 규모: 「수백만 명·계정 이상」 / 「그 미만」 / 「규모 안 적힘」.\n'
    '  사건이 아니면 「해당 없음」.\n'
    '· why: 근거 한 줄(40자 안).\n'
)
Q2_TOOL = json.loads('''{"name": "record_privacy_check",
 "description": "기사 한 건에서 읽히는 사실을 기록한다. 칸은 parties → topic → stage → scale → why 순서로 채운다.",
 "strict": true,
 "input_schema": {"type": "object", "additionalProperties": false,
   "required": ["parties", "topic", "stage", "scale", "why"],
   "properties": {
     "parties": {"type": "array", "items": {"type": "string"},
                 "description": "당사자 회사·기관 이름 목록(기사 표기 그대로, 최대 8개, 없으면 빈 목록)"},
     "topic":   {"type": "string", "enum": ["특정 유출·해킹 사건", "법·제도·정책 일반", "그 밖"]},
     "stage":   {"type": "string", "enum": ["사고 첫 보도", "처분 첫 보도", "뒷이야기", "해당 없음"]},
     "scale":   {"type": "string", "enum": ["수백만 명·계정 이상", "그 미만", "규모 안 적힘", "해당 없음"]},
     "why":     {"type": "string", "description": "근거 한 줄(40자 안)"}}}}''')
_Q2P = Q2_TOOL['input_schema']['properties']
Q2_TOPICS, Q2_STAGES, Q2_SCALES = _Q2P['topic']['enum'], _Q2P['stage']['enum'], _Q2P['scale']['enum']
Q2_MAX_TOKENS = 300

TELCO_NAME = re.compile(r'(SK텔레콤|SKT|에스케이텔레콤|KT(?![A-Za-z&])|케이티|LG\s?유플러스|LGU\+|LG\s?U\+|엘지유플러스|유플러스'
                        r'|이통\s?3사|통신\s?3사|이동통신\s?3사)')
# 넓은 낱말(통신사·이통사·통신망·유심·알뜰폰)은 넣지 않는다 — 배경 언급과 못 가른다(이 세트: 맞게 내린 21건 중 3건을 막음)


def q2_user_msg(art: dict) -> str:
    """Q2 사용자 메시지(판정 §3-3) — 등급 호출의 user_msg와 다른 함수. 검색 요약 300자·본문 600자 둘 다(있을 때만),
    짧은 본문도 넣는다. 둘 다 없으면 제목만."""
    lines = [f"제목: {art['title']}"]
    summ = ws(art.get('screen_text'))[:300]
    body = ws(art.get('content'))[:600]
    if summ:
        lines.append(f'검색 요약: {summ}')
    if body:
        lines.append(f'본문: {body}')
    return '\n'.join(lines)


def telco_party(out, art):
    if any(TELCO_NAME.search(p or '') for p in out.get('parties') or []): return True
    return bool(TELCO_NAME.search((art.get('title') or '') + ' ' + ws(art.get('screen_text'))))   # 안전장치: rule_input_text와 같은 글


def privacy_lower(out, art):
    if out.get('topic') != '특정 유출·해킹 사건': return False
    if telco_party(out, art): return False
    if out.get('stage') == '뒷이야기': return True
    if out.get('stage') == '사고 첫 보도' and out.get('scale') == '그 미만': return True
    return False      # 처분 첫 보도 → 유지(규모 무관) · 규모 안 적힘 → 유지(R-a)


Q2_RULES = ('R-a', 'R-b', 'R-c', 'R-d')


def privacy_lower_rule(out: dict, art: dict, rule: str = 'R-a') -> bool:
    """오프라인 비교 변형(판정 §3-5, 같은 결과 행에서 API 0). R-a = privacy_lower 그대로 /
    R-b = 사고 첫 보도 & 규모 안 적힘도 내림 / R-c = topic 관문 없이 / R-d = 이름 안전장치 없이(parties만)."""
    if rule == 'R-a':
        return privacy_lower(out, art)
    if rule != 'R-c' and out.get('topic') != '특정 유출·해킹 사건':
        return False
    if rule == 'R-d':
        if any(TELCO_NAME.search(p or '') for p in out.get('parties') or []):
            return False
    elif telco_party(out, art):
        return False
    st, sc = out.get('stage'), out.get('scale')
    if st == '뒷이야기':
        return True
    if st == '사고 첫 보도' and (sc == '그 미만' or (rule == 'R-b' and sc == '규모 안 적힘')):
        return True
    return False


def _parse_l1(inp: dict):
    if inp.get('topic') in PRIV_TOPICS and inp.get('telecom') in PRIV_TELECOM and inp.get('stage') in PRIV_STAGES:
        return {k: inp.get(k) for k in ('topic', 'telecom', 'stage', 'why')}
    return None


def _parse_q2(inp: dict):
    pa = inp.get('parties')
    if (isinstance(pa, list) and all(isinstance(p, str) for p in pa) and inp.get('topic') in Q2_TOPICS
            and inp.get('stage') in Q2_STAGES and inp.get('scale') in Q2_SCALES and isinstance(inp.get('why'), str)):
        return {'parties': pa, **{k: inp.get(k) for k in ('topic', 'stage', 'scale', 'why')}}
    return None


# 좁은 질문 변형 — 결과 privacy.jsonl의 pv 칸(옛 L1 행에는 pv가 없다 = L1). key 공식은 L1 때와 같다(옛 행이 '이미 끝남'으로 잡히게)
PRIV_VARIANTS = {
    'L1': {'system': PRIV_SYSTEM, 'tool': PRIV_TOOL, 'max_tokens': 200, 'user': lambda art: user_msg(art),
           'parse': _parse_l1, 'lower': privacy_lower_l1, 'out_tok': 140},   # out_tok = 출력 어림(L1 실측 평균 140)
    'Q2': {'system': Q2_SYSTEM, 'tool': Q2_TOOL, 'max_tokens': Q2_MAX_TOKENS, 'user': q2_user_msg,
           'parse': _parse_q2, 'lower': privacy_lower, 'out_tok': 190},   # parties 목록만큼 더 잡음
}


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
    # 개인정보·해킹 원칙(2026-10-06) — 세트 X = --extra 개인정보 세트(정답은 실측 폴더의 gold.json)
    'P1': {'rubric': 'P1', 'tool': None, 'fb': 'now', 'sets': 'ABCX'},
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
    if rubric == 'P1':
        for old, new in P1_EDITS:
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


def privacy_judge(client, pv: str, user: str) -> dict:
    """개인정보 좁은 질문 한 건(pv = L1·Q2). ⚠️ create를 이 함수 안에서 직접 — api_usage 라벨 'tools_urgency_probe.py:privacy_judge'."""
    spec = PRIV_VARIANTS[pv]
    last = None
    for attempt in range(4):
        try:
            resp = client.messages.create(model=MODEL, max_tokens=spec['max_tokens'], temperature=0, system=spec['system'],
                                          tools=[spec['tool']], tool_choice={'type': 'tool', 'name': 'record_privacy_check'},
                                          messages=[{'role': 'user', 'content': user}])
            u = resp.usage
            out = {'in': getattr(u, 'input_tokens', 0) or 0, 'out': getattr(u, 'output_tokens', 0) or 0, 'parse': 'bad',
                   'stop': resp.stop_reason}
            for b in resp.content:
                if getattr(b, 'type', '') == 'tool_use':
                    got = spec['parse'](b.input or {})
                    if got is not None:
                        out.update(got, parse='ok')
                    else:
                        out['raw'] = json.dumps(b.input, ensure_ascii=False)[:300]
            return out
        except Exception as e:
            last = e
            time.sleep(4 * (attempt + 1))
    return {'parse': 'error', 'raw': str(last)[:160]}


# ── 국감 주간 새 표본(세트 W, 판정 §5) — w2_sample.json에 기사 글을 굳힌다 ─────────────────────────────────────────
W2_FILE = 'w2_sample.json'


def load_w2(out_dir: str) -> dict:
    p = os.path.join(out_dir, W2_FILE)
    if not os.path.exists(p):
        raise SystemExit(f'새 표본이 없다: {p} — 먼저 --extract-w2')
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def parse_runs(s: str) -> list:
    """'Q2:ABCX,Q2:W,L1:W' → [('Q2','ABCX'), ...]. 세트 W = 새 표본(질문 대상만), 나머지는 B0 긴급 + 낱말 적중."""
    out = []
    for part in [x.strip() for x in (s or 'L1:ABCX').split(',') if x.strip()]:
        pv, _, sets = part.partition(':')
        if pv not in PRIV_VARIANTS:
            raise SystemExit(f'좁은 질문 변형 {pv}가 없다({", ".join(PRIV_VARIANTS)})')
        out.append((pv, sets or 'ABCX'))
    return out


def privacy_plan(a, fx, snap) -> tuple:
    """--runs의 실행 계획 — (새 호출 목록, 건너뜀 집계). 같은 key(변형·글자 같음)는 한 번만 부른다."""
    b0 = {}
    for r in load_results(os.path.join(a.out, 'results.jsonl')):
        if r['var'] == 'B0' and r.get('rep', 1) == 1 and r.get('parse') != 'error':
            b0[r['id']] = r['grade']
    path = os.path.join(a.out, 'privacy.jsonl')
    done = {r['key'] for r in load_results(path) if r.get('parse') != 'error'}
    w2 = None
    plan, skipped, seen = [], Counter(), set()
    for pv, sets in parse_runs(a.runs):
        spec = PRIV_VARIANTS[pv]
        tool_js = json.dumps(spec['tool'], ensure_ascii=False)
        for k in sets:
            if k == 'W':
                w2 = w2 or load_w2(a.out)
                pairs = [(cid, w2['articles'][cid]) for cid in w2['order'] if w2['articles'][cid]['asked']]
            else:
                pairs = []
                for cid in set_ids(fx, k, snap):
                    art = snap['articles'].get(cid)
                    if not art:
                        skipped[f'{pv}:{k} 합성'] += 1; continue
                    if b0.get(cid) != '긴급':
                        skipped[f'{pv}:{k} B0 긴급 아님'] += 1; continue
                    pairs.append((cid, art))
            for cid, art in pairs:
                if not privacy_hit(art):
                    skipped[f'{pv}:{k} 낱말 없음'] += 1; continue
                um = spec['user'](art)
                key = hashlib.sha1('\x00'.join([MODEL, spec['system'], tool_js, um]).encode('utf-8')).hexdigest()
                if key in done or key in seen:
                    skipped[f'{pv}:{k} 이미 끝남'] += 1; continue
                seen.add(key)
                plan.append({'id': cid, 'key': key, 'user': um, 'pv': pv, 'set': k,
                             'est_in': (len(spec['system']) + len(tool_js) + len(um)) / CHARS_PER_TOKEN + PRIV_TOOL_OVERHEAD_TOK,
                             'est_out': spec['out_tok']})
    return plan, skipped


PRIV_TOOL_OVERHEAD_TOK = 1430   # strict 도구 강제 때 API가 덧붙이는 글 + 글자 어림 차 — L1 150건 실측(입력 토큰 − 글자 어림, 중앙값 1,427)
LABEL_BODY = 1200               # 정답 매김 입력의 본문 길이(모델 입력 600자보다 길게 — 정답은 잣대)


def _kst(ts: str) -> str:
    """ISO 시각 → KST 'YYYY-MM-DD HH:MM'."""
    from datetime import datetime, timedelta, timezone
    if not ts:
        return ''
    d = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    return d.astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M')


def extract_w2(a, fx, snap):
    """판정 §5의 새 표본 — [from, to) KST에 들어온 운영 기사(origin null) 중
      ① 2차 확인 뒤 저장 등급(관리자 수정 전 = importance_feedback.ai_importance, 없으면 news_feed.urgency)이 긴급
         그리고 privacy_hit → 좁은 질문 대상(asked)
      ② 그 기간 관리자가 공통 등급을 바꾼 기사 전부(내린 것·올린 것 — 기사 날짜 무관)
    옛 세트(A~D·X) 기사는 뺀다. DB 읽기만. 기사 글·등급·관리자 수정을 w2_sample.json에 굳히고 정답 매김 입력을 만든다."""
    from datetime import datetime, timedelta, timezone
    import crawler
    sb = crawler.sb
    kst = timezone(timedelta(hours=9))
    t_from = datetime.fromisoformat(a.w2_from).replace(tzinfo=kst)
    t_to = datetime.fromisoformat(a.w2_to).replace(tzinfo=kst)
    path = os.path.join(a.out, W2_FILE)
    if os.path.exists(path) and not a.refresh:
        raise SystemExit(f'{path}가 이미 있다 — 표본은 한 번만 굳힌다(다시 뽑으려면 --refresh, 결과 key는 그대로)')
    if datetime.now(kst) < t_to and not a.partial:
        raise SystemExit(f'표본 기간이 아직 안 끝났다(끝 {t_to:%m-%d %H:%M} KST) — 시험 추출은 --partial(다른 --out 폴더에)')
    old = set(all_ids(fx)) | set(snap.get('extra', []))
    cols = 'id,title,screen_text,urgency,urgency_rule,urgency_check_scope,urgency_check_capped,published_at,created_at'
    feed, i = [], 0
    while True:                                      # 1000행씩(PostgREST 상한)
        rows = sb.table('news_feed').select(cols).is_('origin', 'null') \
            .gte('created_at', t_from.isoformat()).lt('created_at', t_to.isoformat()) \
            .order('created_at').range(i, i + 999).execute().data or []
        feed += rows
        if len(rows) < 1000:
            break
        i += 1000
    fb = sb.table('importance_feedback').select('news_id,ai_importance,user_importance,updated_at,created_at') \
        .is_('team_id', 'null').gte('updated_at', t_from.isoformat()).execute().data or []
    fb_by = {r['news_id']: r for r in fb if r.get('news_id')}
    # 기간 안 기사의 관리자 수정 행(수정 시각이 기간 밖이어도 수정 전 등급을 읽기 위해)
    ids_in = [r['id'] for r in feed]
    for j in range(0, len(ids_in), 150):
        for r in sb.table('importance_feedback').select('news_id,ai_importance,user_importance,updated_at,created_at') \
                .is_('team_id', 'null').in_('news_id', ids_in[j:j + 150]).execute().data or []:
            fb_by.setdefault(r['news_id'], r)
    changed = {nid for nid, r in fb_by.items() if r.get('user_importance') and t_from <= datetime.fromisoformat(
        r['updated_at'].replace('Z', '+00:00')) < t_to}
    by_id = {r['id']: r for r in feed}
    extra = [nid for nid in changed if nid not in by_id]          # ② 중 기간 밖에 들어온 기사
    for j in range(0, len(extra), 80):
        for r in sb.table('news_feed').select(cols + ',origin').in_('id', extra[j:j + 80]).execute().data or []:
            if r.get('origin') is None:
                by_id[r['id']] = r
    rules = {r['id']: r for r in (sb.table('urgency_rules').select('id,mode,level,team_id').execute().data or [])}
    arts, cnt = {}, Counter()
    for nid, r in by_id.items():
        if nid in old:
            cnt['옛 세트라 뺌'] += 1; continue
        f = fb_by.get(nid)
        pipe = (f or {}).get('ai_importance') or r.get('urgency')
        art = {'title': r['title'], 'screen_text': r.get('screen_text') or ''}
        in1 = pipe == '긴급' and privacy_hit(art)
        in2 = nid in changed
        if not (in1 or in2):
            continue
        rule = rules.get(r.get('urgency_rule')) if r.get('urgency_rule') else None
        skip = None                                  # 운영이라면 좁은 질문을 건너뛸 기사(2차 확인과 같은 건너뜀 — 참고용)
        if in1:
            if rule and rule.get('level') == '긴급':
                skip = 'rule'
            elif not r.get('urgency_check_scope'):
                skip = 'no_check'                    # 2차 확인을 안 부름(사람 즉시대응 유사 사례·실패) — 3차도 같은 자리
        arts[nid] = {**art, 'published_at': r.get('published_at'), 'created_at': r.get('created_at'),
                     'urgency': r.get('urgency'), 'pipe': pipe, 'urgency_rule': r.get('urgency_rule'),
                     'check_scope': r.get('urgency_check_scope'), 'capped': r.get('urgency_check_capped'),
                     'admin': ({'ai': f.get('ai_importance'), 'user': f.get('user_importance'), 'at': f.get('updated_at')}
                               if in2 else None),
                     'in1': in1, 'in2': in2, 'asked': in1, 'prod_skip': skip}
        cnt['①'] += in1; cnt['②'] += in2; cnt['①∩②'] += in1 and in2
    ids = list(arts)
    for j in range(0, len(ids), 60):                 # 본문은 표본만
        for r in sb.table('news_feed').select('id,content').in_('id', ids[j:j + 60]).execute().data or []:
            arts[r['id']]['content'] = r.get('content') or ''
    order = sorted(ids, key=lambda x: (arts[x]['created_at'] or '', x))
    w2 = {'made': time.strftime('%Y-%m-%dT%H:%M:%S'), 'window': [a.w2_from, a.w2_to], 'partial': bool(a.partial),
          'feed_rows': len(feed), 'counts': dict(cnt), 'order': order, 'articles': arts}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(w2, f, ensure_ascii=False)
    # 정답 매김 입력 — 등급·관리자 수정·모델 출력은 넣지 않는다(눈가림). 날짜순(같은 사건의 첫 보도를 가리게)
    lab = []
    for nid in order:
        x = arts[nid]
        t = [f"제목: {x['title']}"]
        if ws(x['screen_text']):
            t.append(f"검색 요약: {ws(x['screen_text'])[:300]}")
        if ws(x.get('content')):
            t.append(f"본문: {ws(x.get('content'))[:LABEL_BODY]}")
        lab.append({'id': nid, 'date': _kst(x['published_at'] or x['created_at']), 'text': '\n'.join(t)})
    lab.sort(key=lambda r: (r['date'], r['id']))     # 매기는 쪽이 보는 날짜 순
    with open(os.path.join(a.out, 'label_input_w2.json'), 'w', encoding='utf-8') as f:
        json.dump(lab, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, 'label_titles_w2.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(f"{x['date']}  {x['text'].split(chr(10))[0][4:]}" for x in lab) + '\n')
    asked = sum(x['asked'] for x in arts.values())
    print(f'[새 표본] 기간 {a.w2_from} ~ {a.w2_to} KST · 운영 기사 {len(feed)}행 → 표본 {len(arts)}건 {dict(cnt)} · '
          f'질문 대상 {asked} (운영이라면 건너뜀 {Counter(x["prod_skip"] for x in arts.values() if x["asked"] and x["prod_skip"])}) '
          f'→ {path} · 정답 매김 입력 label_input_w2.json')


def run_privacy(a, fx, snap):
    """--runs(기본 L1:ABCX)의 좁은 질문 — 결과 privacy.jsonl(key = 프롬프트 지문, pv = 변형, set = 세트 글자)."""
    path = os.path.join(a.out, 'privacy.jsonl')
    plan, skipped = privacy_plan(a, fx, snap)
    cost = sum(it['est_in'] * PRICE['in'] / 1e6 + it['est_out'] * PRICE['out'] / 1e6 for it in plan)
    per = Counter(f"{it['pv']}:{it['set']}" for it in plan)
    print(f'[개인정보 질문] 새 호출 {len(plan)}회 {dict(per)} · 건너뜀 {dict(skipped)} · 어림 ${cost:.2f} (상한 ${a.cap})')
    if not a.allow_api:
        print('dry-run — 실제 호출은 --allow-api(운영자 고지 뒤)')
        return
    if cost > a.cap:
        raise SystemExit(f'어림 ${cost:.2f} > 상한 ${a.cap}')
    import anthropic
    import api_usage
    api_usage.install()
    import crawler
    client = anthropic.Anthropic(api_key=crawler.ANTHROPIC_API_KEY)
    lock = threading.Lock()
    fout = open(path, 'a', encoding='utf-8')
    t0 = time.time()

    def work(it):
        row = {'id': it['id'], 'key': it['key'], 'pv': it['pv'], 'set': it['set'], **privacy_judge(client, it['pv'], it['user'])}
        with lock:
            fout.write(json.dumps(row, ensure_ascii=False) + '\n'); fout.flush()
        return row
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        rows = list(ex.map(work, plan))
    fout.close()
    real = sum(r.get('in', 0) * PRICE['in'] + r.get('out', 0) * PRICE['out'] for r in rows) / 1e6
    # 결과를 열지 않는다 — 건수·실패·비용만(내림 판단은 --privacy-report가 정답과 함께 표로)
    print(f'[끝] 호출 {len(rows)}회 · 오류 {sum(r.get("parse") == "error" for r in rows)} · 해석 실패 '
          f'{sum(r.get("parse") == "bad" for r in rows)} · 잘림 {sum(r.get("stop") == "max_tokens" for r in rows)} · '
          f'{time.time() - t0:.0f}s · 실비 ≈${real:.2f} → {path}')


# ── 좁은 질문 보고 — 판정 §5 통과 기준 P1~P6(측정 전 고정), API 0 ─────────────────────────────────────────────
# 10-02 정답이 U지만 새 원칙(비통신 사건의 후속)으로는 N이 맞는 2건 — 결과_P1.md 2차 절·판정 §2-1. 옛 세트 「U 손실」에서만 N으로 센다
# (「L1이 맞게 내린 21건」은 이 둘을 넣지 않은 수 — 정답 그대로 N인 것만).
NEWP_N = {'97e60a1b-6d6b-4848-984e-089614adf280',      # 윤상현 CJENM 대표 국감 증인 안 나간다
          '75028355-4cbe-42a1-b6f2-b9a4bec95320'}      # [단독] 티빙 유출 후…포털 털리고 보이스피싱 엮이고


def _load_gold(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return {g['id']: g for g in json.load(f)}


def privacy_report(a, fx, snap):
    rows = {}
    for r in load_results(os.path.join(a.out, 'privacy.jsonl')):
        if r.get('parse') == 'error':
            continue
        rows[(r.get('pv') or 'L1', r['id'])] = r
    errs = Counter(r.get('pv') or 'L1' for r in load_results(os.path.join(a.out, 'privacy.jsonl')) if r.get('parse') == 'error')
    w2 = load_w2(a.out)
    W = w2['articles']
    gx, gw = _load_gold(a.gold_x), _load_gold(a.gold_w)
    # 옛 세트 정답: A·C(10-02 정답) + X(gold.json, 개인정보 원칙). B(안정성)는 정답 없음
    og, otel = {}, {}
    for k in ('A', 'C'):
        for c in fx['sets'][k]:
            og.setdefault(c['id'], c['gold'])
    for i, g in gx.items():
        og[i], otel[i] = g['gold'], g.get('telecom')
    og_adj = {i: ('N' if i in NEWP_N else g) for i, g in og.items()}
    wg = {i: g['gold'] for i, g in gw.items()}
    wtel = {i: bool(g.get('telecom')) for i, g in gw.items()}
    miss = [i for i in W if i not in gw]
    old_art = lambda i: snap['articles'][i]

    def tally(pv, ids, art_of, gold, tel, rule='R-a'):
        asked = [i for i in ids if (pv, i) in rows]
        ok = [i for i in asked if rows[(pv, i)].get('parse') == 'ok']
        lower = (lambda o, ar: privacy_lower_rule(o, ar, rule)) if pv == 'Q2' else PRIV_VARIANTS[pv]['lower']
        low = [i for i in ok if lower(rows[(pv, i)], art_of(i))]
        U = [i for i in asked if gold.get(i) == 'U']
        N = [i for i in asked if gold.get(i) == 'N']
        cost = sum(rows[(pv, i)].get('in', 0) * PRICE['in'] + rows[(pv, i)].get('out', 0) * PRICE['out'] for i in asked) / 1e6
        return {'n': len(asked), 'bad': len(asked) - len(ok), 'low': low, 'U': U, 'N': N,
                'B': [i for i in asked if gold.get(i) == 'B'], 'nogold': [i for i in asked if i not in gold],
                'lowU': [i for i in low if gold.get(i) == 'U'], 'lowUT': [i for i in low if gold.get(i) == 'U' and tel.get(i)],
                'lowN': [i for i in low if gold.get(i) == 'N'], 'cost': cost,
                'cut': sum(rows[(pv, i)].get('stop') == 'max_tokens' for i in asked)}

    old_ids = [i for i in dict.fromkeys(all_ids(fx) + list(snap.get('extra', []))) if i in snap['articles']]
    w_ids = [i for i in w2['order'] if W[i]['asked']]
    wart = lambda i: W[i]
    qw = {r: tally('Q2', w_ids, wart, wg, wtel, r) for r in Q2_RULES}
    lw = tally('L1', w_ids, wart, wg, wtel)
    qo = {r: tally('Q2', old_ids, old_art, og_adj, otel, r) for r in Q2_RULES}
    lo = tally('L1', old_ids, old_art, og_adj, otel)
    l1_ok21 = [i for i in tally('L1', old_ids, old_art, og, otel)['lowN']]
    pct = lambda x, n: f'{x}/{n} ({x / n:.0%})' if n else f'{x}/0'
    L = []
    p = L.append
    p(f'# 개인정보 좁은 질문 Q2 측정 결과 — P1~P6 (생성 {time.strftime("%Y-%m-%d %H:%M")}, `tools_urgency_probe.py --privacy-report`)\n')
    p('판정 문서: `판정_좁은질문_261006.md` §5(통과 기준은 측정 전 고정). 이 표는 도구가 만든 것이고, 결과를 보고 문안·규칙을 고치지 않았다.\n')
    p(f'- 새 표본 W: {w2["window"][0]} ~ {w2["window"][1]} KST{" (⚠️ 부분 추출)" if w2.get("partial") else ""} · 표본 {len(W)}건 {w2["counts"]} · '
      f'질문 대상 {len(w_ids)}건 · 정답 {len(gw)}건(빠짐 {len(miss)}) · 정답 분포(질문 대상) U {len(qw["R-a"]["U"])} · N {len(qw["R-a"]["N"])} · '
      f'B {len(qw["R-a"]["B"])}(채점 제외)')
    p(f'- 옛 세트(ⓐ 회귀): 질문 대상 {qo["R-a"]["n"]}건(10-02 A·C 정답 + X gold.json, 새 원칙 N 2건 반영) · L1이 맞게 내린 {len(l1_ok21)}건')
    p(f'- 호출 오류(결과 파일, 재시도 대상) {dict(errs) or 0}\n')
    nW = qw['R-a']['n']
    p2_thr = 1 if nW <= 100 else 0.01 * nW
    r, l = qw['R-a'], lw
    q2o = qo['R-a']
    keep21 = sum(1 for i in l1_ok21 if i in q2o['low'])
    tel_u = [i for i in r['U'] if wtel.get(i) and rows[('Q2', i)].get('parse') == 'ok']
    tel_named = [i for i in tel_u if any(TELCO_NAME.search(x or '') for x in rows[('Q2', i)].get('parties') or [])]
    q2_all = [rows[k] for k in rows if k[0] == 'Q2']
    per_call = sum(x.get('in', 0) * PRICE['in'] + x.get('out', 0) * PRICE['out'] for x in q2_all) / 1e6 / max(1, len(q2_all))
    bad_all = sum(x.get('parse') != 'ok' for x in q2_all) + errs.get('Q2', 0)
    ok = lambda b: '통과' if b else '**못 미침**'
    p('## 통과 기준 (새 표본 W, R-a)\n')
    p('| | 기준 | 측정 | 판정 |')
    p('|---|---|---|---|')
    p(f'| P1 | 정답 U·통신 연결 내림 0 | {len(r["lowUT"])} | {ok(not r["lowUT"])} |')
    p(f'| P2 | 정답 U 내림 ≤1건(n>100이면 ≤1 %) | {len(r["lowU"])} (n={nW}, 한도 {p2_thr:g}) | {ok(len(r["lowU"]) <= p2_thr)} |')
    p(f'| P3 | 정답 N 내림 ≥60 %, 같은 표본 L1보다 많음 | Q2 {pct(len(r["lowN"]), len(r["N"]))} · L1 {pct(len(l["lowN"]), len(l["N"]))} | '
      f'{ok(r["N"] and len(r["lowN"]) / len(r["N"]) >= 0.6 and len(r["lowN"]) > len(l["lowN"]))} |')
    p(f'| P4 | 옛 세트: L1이 맞게 내린 {len(l1_ok21)}건 중 Q2도 내림 ≥19, 정답 U 손실 ≤ L1({len(lo["lowU"])}) | '
      f'{keep21}/{len(l1_ok21)} · U 손실 {len(q2o["lowU"])} | {ok(keep21 >= 19 and len(q2o["lowU"]) <= len(lo["lowU"]))} |')
    p(f'| P5 | 정답 U·통신 연결 중 parties에 통신사 이름 ≥85 % (R-d) | {pct(len(tel_named), len(tel_u))} | '
      f'{ok(tel_u and len(tel_named) / len(tel_u) >= 0.85) if tel_u else "해당 없음(0건)"} |')
    p(f'| P6 | 질문당 비용 ≤ $0.01, 해석 실패 0 | ${per_call:.4f} · 실패 {bad_all} (Q2 {len(q2_all)}회, 잘림 '
      f'{sum(x.get("stop") == "max_tokens" for x in q2_all)}) | {ok(per_call <= 0.01 and bad_all == 0)} |')
    p('')
    p('## 오프라인 비교 (같은 결과 행, API 0)\n')
    p('| 세트 | 규칙 | 질문 | 내림 | 정답 U 내림 | 그중 통신 연결 | 정답 N 내림 | 해석 실패 |')
    p('|---|---|---|---|---|---|---|---|')
    for lab, d in (('W', qw), ('옛 세트', qo)):
        for rule in Q2_RULES:
            t = d[rule]
            p(f'| {lab} | Q2 {rule} | {t["n"]} | {len(t["low"])} | {len(t["lowU"])} | {len(t["lowUT"])} | {pct(len(t["lowN"]), len(t["N"]))} | {t["bad"]} |')
        t = lw if lab == 'W' else lo
        p(f'| {lab} | L1 | {t["n"]} | {len(t["low"])} | {len(t["lowU"])} | {len(t["lowUT"])} | {pct(len(t["lowN"]), len(t["N"]))} | {t["bad"]} |')
    p('')
    sk = Counter(W[i]['prod_skip'] for i in r['low'] if W[i]['prod_skip'])
    p(f'- W에서 R-a가 내린 {len(r["low"])}건 중 운영이라면 질문을 건너뛸 기사(낱말 하한 긴급·2차 확인 안 부름) {dict(sk) or 0}')
    outside = [i for i in w2['order'] if not W[i]['asked']]
    od = Counter((wg.get(i), (W[i].get('admin') or {}).get('ai'), (W[i].get('admin') or {}).get('user')) for i in outside)
    p(f'- 질문 밖(② 관리자 수정만, 운영 등급이 긴급이 아니었거나 낱말 없음) {len(outside)}건 — (정답, 수정 전, 수정 후): '
      + ', '.join(f'{k} {v}' for k, v in od.most_common()))
    if miss:
        p(f'- ⚠️ 정답 없는 표본 {len(miss)}건 — 채점에서 빠짐')
    p('')

    def line(i, art, gold_row, pv='Q2'):
        o = rows.get((pv, i)) or {}
        return (f'  - {art["title"][:70]} — parties {o.get("parties")} · {o.get("topic")}·{o.get("stage")}·{o.get("scale")} · '
                f'「{o.get("why")}」 / 정답 근거 「{(gold_row or {}).get("why", "")}」')
    p('## 정답 U인데 내린 기사 (P1·P2·P4 대상)\n')
    p(f'- 새 표본 W (R-a) {len(r["lowU"])}건')
    for i in r['lowU']:
        p(line(i, W[i], gw.get(i)) + (' · **통신 연결**' if wtel.get(i) else ''))
    p(f'- 옛 세트 (R-a) {len(q2o["lowU"])}건')
    for i in q2o['lowU']:
        p(line(i, old_art(i), gx.get(i)))
    p(f'- 옛 세트: L1이 맞게 내렸는데 Q2(R-a)가 안 내린 것 {len(l1_ok21) - keep21}건')
    for i in l1_ok21:
        if i not in q2o['low']:
            p(line(i, old_art(i), gx.get(i)))
    md = '\n'.join(L) + '\n'
    with open(a.md, 'w', encoding='utf-8') as f:
        f.write(md)
    # 판정 세션용 기사별 묶음(칸·내림 규칙별·정답) — 원인 분류는 판정 세션 몫
    join = []
    for lab, ids, art_of, gold, grow, tel in (('W', [i for i in w2['order']], wart, wg, gw, wtel),
                                              ('old', [i for i in old_ids if ('Q2', i) in rows or ('L1', i) in rows], old_art, og_adj, gx, otel)):
        for i in ids:
            ar = art_of(i)
            q, l1 = rows.get(('Q2', i)), rows.get(('L1', i))
            join.append({'set': lab, 'id': i, 'title': ar['title'], 'gold': gold.get(i), 'gold_telecom': tel.get(i),
                         'gold_why': (grow.get(i) or {}).get('why'), 'gold_kind': (grow.get(i) or {}).get('kind'),
                         'q2': {k: q.get(k) for k in ('parties', 'topic', 'stage', 'scale', 'why', 'parse')} if q else None,
                         'q2_lower': {rule: privacy_lower_rule(q, ar, rule) for rule in Q2_RULES} if q and q.get('parse') == 'ok' else None,
                         'telco_title_summary': bool(TELCO_NAME.search((ar.get('title') or '') + ' ' + ws(ar.get('screen_text')))),
                         'l1': {k: l1.get(k) for k in ('topic', 'telecom', 'stage', 'why')} if l1 else None,
                         'l1_lower': privacy_lower_l1(l1) if l1 and l1.get('parse') == 'ok' else None,
                         **({k: ar.get(k) for k in ('pipe', 'urgency', 'admin', 'prod_skip', 'asked', 'in1', 'in2')} if lab == 'W' else {})})
    with open(os.path.join(a.out, 'q2_join.json'), 'w', encoding='utf-8') as f:
        json.dump(join, f, ensure_ascii=False, indent=1)
    print(md)
    print(f'→ {a.md} · 기사별 묶음 {os.path.join(a.out, "q2_join.json")}')


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
    ap.add_argument('--privacy', action='store_true', help='개인정보 좁은 질문(B0 긴급 + 낱말 적중 / 세트 W는 새 표본 질문 대상)')
    ap.add_argument('--runs', default='L1:ABCX', help="좁은 질문 실행 목록 '변형:세트,…' — 예 Q2:ABCX,Q2:W,L1:W (한 번에 어림·상한)")
    ap.add_argument('--extract-w2', action='store_true', help='국감 주간 새 표본(세트 W)을 DB에서 뽑아 굳힌다(읽기만, 판정 §5)')
    ap.add_argument('--w2-from', default='2026-10-06T00:00', help='새 표본 시작(KST, 포함)')
    ap.add_argument('--w2-to', default='2026-10-13T00:00', help='새 표본 끝(KST, 제외)')
    ap.add_argument('--partial', action='store_true', help='기간이 안 끝났어도 추출(시험용 — 다른 --out 폴더에)')
    ap.add_argument('--privacy-report', action='store_true', help='좁은 질문 통과 기준 P1~P6 + R-a~R-d(API 0회)')
    ap.add_argument('--gold-x', default='', help='옛 세트 X 정답(기본 --out 위 폴더의 gold.json)')
    ap.add_argument('--gold-w', default='', help='새 표본 정답(기본 --out 위 폴더의 gold_w2.json)')
    ap.add_argument('--md', default='', help='좁은 질문 보고 파일(기본 --out 위 폴더의 결과_Q2.md)')
    ap.add_argument('--report', action='store_true', help='통과 기준 대조표(API 0회)')
    ap.add_argument('--cap-mode', default='R1', choices=['raw', 'R1', 'R2'], help='2단계 비교에 쓸 상한')
    ap.add_argument('--out', default=OUT_DEFAULT)
    ap.add_argument('--refresh', action='store_true', help='스냅숏을 DB에서 다시 읽는다(결과 key가 바뀔 수 있다)')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--cap', type=float, default=5.0, help='한 번 실행의 어림 비용 상한($, 설계 D7)')
    ap.add_argument('--extra', default='', help='임시 세트 X — 기사 id를 쉼표·줄바꿈으로 적은 파일(스냅숏에 더해 읽는다)')
    a = ap.parse_args()
    up = os.path.dirname(os.path.abspath(a.out))
    a.gold_x = a.gold_x or os.path.join(up, 'gold.json')
    a.gold_w = a.gold_w or os.path.join(up, 'gold_w2.json')
    a.md = a.md or os.path.join(up, '결과_Q2.md')
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
    elif a.extract_w2:
        extract_w2(a, fx, snap)
    elif a.privacy_report:
        privacy_report(a, fx, snap)
    elif a.sentence:
        run_sentence(a, fx, snap)
    elif a.privacy:
        run_privacy(a, fx, snap)
    else:
        run_variants(a, fx, snap)
    return 0


if __name__ == '__main__':
    sys.exit(main())
