# -*- coding: utf-8 -*-
"""
텔레그램 구독자 봇 「주요 뉴스」의 2문장 AI 요약 줄 (#298, 2026-10-13 운영자 결정 6개)

왜: 구독자는 제목 한 줄만 보고 기사를 열지 정해야 했다. 판정 호출(긴급도)에 요약을 얹으면 그 호출의 출력 「셋 중 하나만」이
    보정점이라 판정이 흔들린다(#267 실측) — 그래서 **억제·리마인드까지 지나 실제로 나가는 기사에만** 별도 호출 하나.

규칙(운영자 결정 그대로):
  1. 두 문장(≈120자).
  2. 본문 없는 기사(수집 실패·SUMMARY_MIN_BODY 미만)는 요약 줄 생략 — 네이버 요약으로 만들지 않는다.
  3. 결과는 news_feed.ai_summary(새 칸)에 저장해 대시보드와 같이 쓴다. news_feed.summary(네이버 요약 — 목록·검색·
     긴급도 피드백 사례가 읽는 칸)는 덮지 않는다.
  4. 구독자 봇만(운영자 봇 긴급 알림은 그대로).
  5. 지시문은 실제 알림이 나간 기사 10건의 전문으로 실측한 뒤 고정(tools_news_summary_probe.py).
  6. 입력은 수집 때 받은 전문 앞 SUMMARY_INPUT_MAX자 — 같은 실행 안 메모리에서만. DB content는 1,500자 그대로.
지시문 방어 2가지: ① 원문에 없는 범위·확정 표현 금지, 추진·검토는 그대로, 발언엔 주체 ② 토큰 상한 + 「다.」로 안 끝나면
    버림(잘림 방어) — 실패·거절·잘림은 모두 요약 없이 제목만(fail-open, 발송을 막지 않는다).
샘플링 인자(온도류)는 넣지 않는다 — 지침 do-not(그 인자는 긴급도 콜·재보도 대조 콜 두 곳뿐, 테스트가 센다).
"""
import re

import api_usage; api_usage.install()   # Anthropic usage 기록(#152) — site 라벨 = 'news_summary.py:news_tg_summary'

# 모델 — 10-13 실측(실제 나간 긴급 10건 전문, 같은 지시문, 독립 점검)으로 운영자가 고정: Haiku 4.5는 실질 문제 3건·경미 9건
# (한정어·조건 탈락, 연도·기관이 섞인 문단 합치기), Sonnet 5는 1건·5건에 숫자·직함 틀림 0, 길이 91~146자. 건당 ≈$0.0066(월 $2~6).
# Sonnet 5 비스트리밍은 추론을 끈다(request_kwargs — 지침 #120). 모델을 바꾸려면 tools_news_summary_probe.py --model로 다시 잰다.
SUMMARY_MODEL = 'claude-sonnet-5'
SUMMARY_MAX_TOKENS = 300       # 두 문장 상한(한글 1자 ≈ 1.03~1.07토큰 실측, Sonnet 5 출력 최대 149) — 넘기면 잘려 「다.」로 안 끝나므로 버려진다(방어 ②)
SUMMARY_INPUT_MAX = 8000       # 요약 입력 = 수집 때 받은 전문 앞부분(메모리만)
SUMMARY_MIN_BODY = 200         # 이보다 짧은 본문은 요약하지 않는다 — 긴급도 판정의 URGENCY_SHORT_BODY(200자)와 같다
                               # (#267-보론: 짧은 본문의 절반이 사이트 메뉴 글자였다 — 그걸 요약하면 근거 없는 글이 된다)
SUMMARY_TIMEOUT_S = 15         # 호출 하나의 제한(재시도 1회) — 실패면 제목만

SUMMARY_SYSTEM = (
    '너는 통신·전파 정책 뉴스를 받아 보는 사람에게 기사 내용을 두 문장으로 알려 준다. '
    '받는 사람은 제목과 이 두 문장만 보고 기사를 열지 정한다.\n\n'
    '규칙:\n'
    '1. 기사 원문에 적힌 내용만 쓴다. 원문에 없는 사실·배경·전망·평가를 보태지 않는다.\n'
    '2. 원문보다 범위·정도를 키우지 않는다 — 「최대」「약」「일부」「~까지」 같은 한정어와 「~되면」「~할 경우」 같은 조건은 그대로 두고, '
    '원문에 없는 범위·확정 표현(전국·전면·모든·확정 등)을 만들지 않는다. 원문의 「추진」「검토」「계획」「예정」「의혹」「혐의」도 그 말을 그대로 둔다.\n'
    '3. 발언·주장·요구·전망·분석은 누가 했는지 주체를 밝히고 「~라고 밝혔다·지적했다·전망했다」처럼 그 주체의 말로 쓴다. '
    '주체를 바꾸거나 여러 주체를 하나로 합치지 않는다.\n'
    '4. 제목을 그대로 되풀이하지 말고, 제목에 없는 핵심(누가·무엇을·언제·수치·다음 절차)을 담는다. 숫자·날짜는 원문 그대로 쓴다.\n'
    '5. 정확히 두 문장, 합쳐 120자 이내로 쓴다(한 문장 60자 안팎). 줄여야 하면 덜 중요한 내용을 빼고(한정어·조건은 빼지 않는다), '
    '각 문장은 「다.」로 끝낸다.\n'
    '6. 요약 두 문장만 출력한다 — 머리말·따옴표·글머리 기호·줄바꿈 없이.\n'
    '7. 원문이 기사 본문이 아니면(사이트 메뉴·기사 목록·안내문뿐) 「없음」 한 낱말만 출력한다.'
)
# 받지 않는 응답 — 원문·요약을 가리키는 메타 응답(「제공된 원문에는 …없습니다.」도 「다.」로 끝난다, #99 「언급 없음」 저장 사고와 같은 꼴)
_META_WORDS = ('원문', '요약', '제공된', '제공되지')
_MIN_HANGUL = 0.3              # 공백 뺀 글자 중 한글 비율 — 영문 거절문 등(#99)


SUMMARY_TAIL = '(두 문장, 합쳐 120자 이내)'   # 원문 뒤 길이 재확인 — 10-13 1차 실측: 지시문만으로는 10건 중 4건이 200자를 넘겨 잘렸다


def build_user(title, source, body) -> str:
    """요청 본문 — 제목·출처·원문(앞 SUMMARY_INPUT_MAX자)·길이 재확인 한 줄."""
    text = re.sub(r'\s+', ' ', str(body or '')).strip()[:SUMMARY_INPUT_MAX]
    return f'제목: {str(title or "").strip()}\n출처: {str(source or "").strip()}\n\n기사 원문:\n{text}\n\n{SUMMARY_TAIL}'


def request_kwargs(title, source, body, model: str = '') -> dict:
    """Messages.create 인자 — 운영 호출·실측 도구가 같은 것을 쓴다(테스트가 모양을 잠근다). model = 실측 도구의 비교용(기본 운영 모델).
    Sonnet 5는 적응형 추론이 기본이라 비스트리밍에서 꺼야 content가 글이고 추론 토큰이 청구되지 않는다(지침 #120)."""
    m = model or SUMMARY_MODEL
    kw = {'model': m, 'max_tokens': SUMMARY_MAX_TOKENS, 'system': SUMMARY_SYSTEM,
          'messages': [{'role': 'user', 'content': build_user(title, source, body)}]}
    if m.startswith('claude-sonnet-5') and not m.startswith('claude-sonnet-5-5'):
        kw['thinking'] = {'type': 'disabled'}
    return kw


def accept(text, stop_reason) -> str:
    """응답 → 붙일 요약('' = 버림). 끝까지 쓴 응답(end_turn)이고 공백을 고른 뒤 「다.」로 끝날 때만 받는다(방어 ②).
    「없음」(본문 아님, 지시문 7)·메타 응답(_META_WORDS)·한글이 적은 응답도 버린다 — 저장 전 검사가 유일한 방어선(#99)."""
    if stop_reason != 'end_turn':
        return ''
    s = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not s.endswith('다.') or any(w in s for w in _META_WORDS):
        return ''
    chars = re.sub(r'\s', '', s)
    if len(re.findall(r'[가-힣]', chars)) < _MIN_HANGUL * len(chars):
        return ''
    return s


def usable_body(body) -> bool:
    return len(str(body or '').strip()) >= SUMMARY_MIN_BODY


def news_tg_summary(client, title, source, body) -> dict:
    """기사 1건 요약 — {'summary': 붙일 글('' = 없음), 'why': ''|'본문 없음'|'버림'|'실패: …', 'raw', 'stop', 'usage'}.
    ⚠️ client.messages.create는 **이 함수 안에서 직접** 부른다 — api_usage가 부른 함수 이름으로 비용 라벨을 단다.
    어떤 예외도 밖으로 던지지 않는다(fail-open)."""
    out = {'summary': '', 'why': '', 'raw': '', 'stop': '', 'usage': None}
    if not usable_body(body):
        out['why'] = '본문 없음'
        return out
    try:
        resp = client.messages.create(**request_kwargs(title, source, body))
    except Exception as e:                      # noqa: BLE001 — 요약 실패는 제목만으로 보낸다
        out['why'] = f'실패: {str(e)[:80]}'
        return out
    try:
        out['raw'] = ''.join(getattr(b, 'text', '') or '' for b in (resp.content or [])
                             if getattr(b, 'type', '') == 'text')
        out['stop'] = str(getattr(resp, 'stop_reason', '') or '')
        out['usage'] = getattr(resp, 'usage', None)
        out['summary'] = accept(out['raw'], out['stop'])
        if not out['summary']:
            out['why'] = '본문 아님' if out['raw'].strip().rstrip('.') == '없음' else '버림'
    except Exception as e:                      # noqa: BLE001
        out['why'] = f'실패: {str(e)[:80]}'
    return out
