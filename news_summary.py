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
  7. (#324, 2026-10-20 운영자 요청·제안) 원문에 SK텔레콤이 나오면 그 내용이 받는 사람에게 닿아야 한다 — 두 문장 요약은 **그대로 두고**
     (모든 기사의 요약 요청이 10-13 고정본과 바이트 단위로 같다, 테스트 LOCK_1013), 언급 기사(제목 + 요약 입력 글에 SKT_RE)에만 **두 번째
     짧은 호출**(news_skt_line — 이미 만든 요약을 보여 주고 「거기 없는 SK텔레콤만의 내용 한 문장, 없으면 「없음」」)로 줄 하나를 받아
     요약 아래 「SKT 언급: …」으로 붙인다(tg_text — 텔레그램은 둘째 인용구 줄, 대시보드 ai_summary는 줄바꿈 뒤 둘째 글머리).
     10-20 실측(같은 36건, Opus 점검): 두 문장 안에 넣는 세 문안(반드시/셋째 문장/구절로)은 모두 기사의 둘째 축을 2/3에서 밀어냈고
     억지 서술 1~9건; 별도 줄은 밀어냄 0, 조인 문안(D′) 줄 21/36·실질 0·오류 0·억지 1·되풀이 0 → 채택. 줄 호출의 실패·잘림·「없음」은
     줄만 빠지고 요약은 그대로(fail-open) — 결과 skt 칸('ok'|'없음'|'버림'|'실패: …'). 첫 주 실측: 언급 34건 중 21건에 SK텔레콤이 없었다.
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

# ── SK텔레콤 언급 줄(규칙 7, #324) ────────────────────────────────────────────────────────────────────────────────────
# 언급 검사: 제목 + 요약 입력(앞 SUMMARY_INPUT_MAX자, 모델이 보는 글 그대로). SK브로드밴드·SK텔링크·SK하이닉스 같은 다른 SK 계열은 해당
# 없음(운영자 요청은 SK텔레콤). 줄 문안은 10-20 실측 D′(같은 36건: 줄 21/36, 실질 0·오류 0·억지 1·되풀이 0, 평균 57자) → 같은 날 저녁 사내 실측
# 회신(30건 중 실패가 「둘 사업자가 함께 받은 지적」 한 꼴에 몰림)으로 규칙 2·3을 보강한 D″(36건 줄 21/36·바뀐 15건 실질 0·억지 0·누락 0,
# 사내 사례 4건 모두 「없음」) → 사내 2차 회신(줄이 길어지며 사실 여럿을 한 문장에 몰아 순위·조건·사유가 틀림; 운영자 「70자 넘어도 의미가 중요」)으로
# D‴: 사실 하나만, 조건·한정어·비교 유지(그래서 70자 안팎·넘어도 됨, 상한 토큰 260), 순위는 원문 수치에 붙은 것만, 사유·인과 그대로(바뀐 14건 실질 0·억지 0,
# 사내 2차 사례 2건 실질 0) — 운영자 대조표 local_docs/텔레그램요약_SKT_261020/. 두 문장 요약 요청(SUMMARY_SYSTEM·SUMMARY_TAIL)은 손대지 않는다.
SKT_RE = re.compile(r'SK\s?텔레콤|에스케이\s?텔레콤|SKT|SK\s?[Tt]elecom')
SKT_LINE_MAX_TOKENS = 260      # 한 문장 70자 안팎, 조건·비교 때문이면 넘어도 됨(실측 최대 85자·출력 ≤ 100토큰) — 넘기면 「다.」로 안 끝나 버린다
SKT_LINE_SYSTEM = (
    '너는 통신·전파 정책 뉴스를 받아 보는 SK텔레콤 사람에게, 기사에서 SK텔레콤에 관한 내용을 한 줄 덧붙여 준다. 기사 전체 요약(두 문장)은 이미 보냈고 그 아래에 붙는 줄이다.\n'
    '\n'
    '규칙:\n'
    '1. 기사 원문에 적힌 SK텔레콤만의 내용 — SK텔레콤이 한 일·밝힌 것, SK텔레콤에 내려진 조치·요구·판단, SK텔레콤 몫의 수치(금액·순위·비율) — 가운데 **이미 보낸 요약에 없는 것 하나**(가장 중요한 것 — 조치·제재·수치가 발언·배경보다 앞선다)만 쓴다. 여러 사실을 한 문장에 몰지 않고, 요약에 이미 있는 내용을 되풀이하지 않는다.\n'
    '2. 다음은 SK텔레콤만의 내용이 아니다 — 있어도 「없음」: 여러 사업자의 합산·공통 사실(「통신 3사 합산 투자」「3사 보안 책임자 출석」「공동 선정」), 둘 이상 사업자가 함께 받은 지적·비판·조치·평가(「SK텔레콤과 LG유플러스의 외주화」「SKT·KT의 3G 종료 준비」처럼 이름이 나란히 붙은 것 — SK텔레콤 몫이 따로 적혀 있을 때만 그 몫을 쓴다), 사업자 이름 나열, 시점·계기 표지(「SK텔레콤 사고 이후」「…를 계기로」), 관련기사 목록·광고·기자 소개.\n'
    '3. 원문에 없는 사실·배경·평가·인과(「…해서 …했다」)를 보태지 않는다. 원문의 사유·인과는 그대로 쓴다 — 원문이 「A를 이유로 B」면 그 사유 A를 쓰고, 다른 사실을 사유처럼 잇지 않는다. 조건·한정어·기준(선착순·기종·기간·「이상」·「약」·「최대」)은 빼지 않고, 수치에는 원문의 기간(분기·상반기·최근 1년 등)을 붙인다. 순위·비교·「가장」은 원문에서 그 수치에 붙은 것만 쓰고, 여러 수치를 한 순위로 묶지 않는다. 원문이 다른 사업자와 견준 말이면 그 비교(「LG유플러스는 전화번호를 그대로 쓰는 것과 달리」)를 함께 적는다. 집계·추산·전망·보도는 「집계됐다」「전망했다」처럼 그 말 그대로 쓰고, 「밝혔다」는 SK텔레콤이 직접 밝힌 것에만, 관계자의 말은 「SK텔레콤 관계자는 …라고 말했다」로 쓴다. 다른 사업자의 것을 SK텔레콤 것으로 쓰지 않고, 둘 이상 사업자의 공통 사실은 규칙 2대로 「없음」이지 SK텔레콤만의 일로 바꿔 쓰지 않는다.\n'
    '4. 쓸 내용이 없으면 「없음」 한 낱말만 출력한다.\n'
    '5. 쓸 내용이 있으면 「SK텔레콤은/SK텔레콤의 …」로 시작하는 한 문장, 70자 안팎으로 쓴다 — 조건·한정어·비교를 빼야만 줄어들면 넘어도 된다. 「다.」로 끝내고, 머리말·따옴표·글머리 기호·줄바꿈 없이 그 문장만 출력한다.'
)
SKT_LINE_TAIL = '(이미 보낸 요약에 없는 SK텔레콤만의 내용 하나를 한 문장으로, 70자 안팎 — 조건·비교를 빼야 하면 넘어도 됨, 없으면 「없음」)'
SKT_LINE_LABEL = 'SKT 언급: '    # 저장(ai_summary)·텔레그램 둘째 줄의 머리 — 텔레그램은 앞에 작대기(subscriber_notify)


def input_text(body) -> str:
    """요약 입력 = 공백 정리 뒤 앞 SUMMARY_INPUT_MAX자 — 언급 검사도 이 글로 한다(모델이 보는 것과 같게)."""
    return re.sub(r'\s+', ' ', str(body or '')).strip()[:SUMMARY_INPUT_MAX]


def skt_mentioned(title, text) -> bool:
    return bool(SKT_RE.search(f'{str(title or "")} {str(text or "")}'))


def build_user(title, source, body) -> str:
    """요청 본문 — 제목·출처·원문(앞 SUMMARY_INPUT_MAX자)·길이 재확인 한 줄."""
    return f'제목: {str(title or "").strip()}\n출처: {str(source or "").strip()}\n\n기사 원문:\n{input_text(body)}\n\n{SUMMARY_TAIL}'


def _thinking(kw: dict, m: str) -> dict:
    if m.startswith('claude-sonnet-5-5'):
        kw['thinking'] = {'type': 'between_tools'}   # 비교 실측용(2026-10-14): 5.5는 disabled가 400 — 추론 끔은 between_tools(effort high 이하)
    elif m.startswith('claude-sonnet-5') or m.startswith('claude-haiku-5-5'):
        kw['thinking'] = {'type': 'disabled'}        # Haiku 5.5도 추론 기본 켬 — 300토큰 상한을 추론이 먹어 10건 중 6건이 빈 답(10-14 실측)
    return kw


def request_kwargs(title, source, body, model: str = '') -> dict:
    """Messages.create 인자 — 운영 호출·실측 도구가 같은 것을 쓴다(테스트가 모양을 잠근다). model = 실측 도구의 비교용(기본 운영 모델).
    모든 기사가 같은 요청(10-13 고정본) — SK텔레콤 언급 줄은 따로 skt_line_kwargs.
    Sonnet 5는 적응형 추론이 기본이라 비스트리밍에서 꺼야 content가 글이고 추론 토큰이 청구되지 않는다(지침 #120)."""
    m = model or SUMMARY_MODEL
    return _thinking({'model': m, 'max_tokens': SUMMARY_MAX_TOKENS, 'system': SUMMARY_SYSTEM,
                      'messages': [{'role': 'user', 'content': build_user(title, source, body)}]}, m)


def skt_line_kwargs(title, source, body, summary, model: str = '') -> dict:
    """SK텔레콤 언급 줄 요청 — 제목·출처·**이미 만든 두 문장 요약**·원문(같은 입력 글)·꼬리. 모델·추론 인자는 요약 호출과 같다."""
    m = model or SUMMARY_MODEL
    user = (f'제목: {str(title or "").strip()}\n출처: {str(source or "").strip()}\n\n이미 보낸 요약:\n{str(summary or "").strip()}\n\n'
            f'기사 원문:\n{input_text(body)}\n\n{SKT_LINE_TAIL}')
    return _thinking({'model': m, 'max_tokens': SKT_LINE_MAX_TOKENS, 'system': SKT_LINE_SYSTEM,
                      'messages': [{'role': 'user', 'content': user}]}, m)


def accept_line(text, stop_reason) -> tuple:
    """줄 응답 → (붙일 문장, why) — ('', '없음') = 줄 없이 나감(정상), ('', '버림'|'잘림') = 줄만 빠짐. 받는 조건은 accept()와 같다."""
    if stop_reason != 'end_turn':
        return '', '잘림'
    s = re.sub(r'\s+', ' ', str(text or '')).strip()
    if s.rstrip('.') == '없음':
        return '', '없음'
    if not s.endswith('다.') or any(w in s for w in _META_WORDS):
        return '', '버림'
    chars = re.sub(r'\s', '', s)
    if len(re.findall(r'[가-힣]', chars)) < _MIN_HANGUL * len(chars):
        return '', '버림'
    return s, ''


def tg_text(summary, line) -> str:
    """저장·발송 글 = 두 문장 요약 + (줄이 있으면) 줄바꿈 뒤 「SKT 언급: …」. 줄바꿈이 둘을 가르는 유일한 표지다(accept()가 요약 안 공백을 다 접는다)."""
    s = str(summary or '').strip()
    if not s:
        return ''
    return s + ('\n' + SKT_LINE_LABEL + line if line else '')


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


def news_skt_line(client, title, source, body, summary) -> dict:
    """SK텔레콤 언급 줄 1건 — {'line': 붙일 문장('' = 없음), 'why': ''|'없음'|'버림'|'잘림'|'실패: …', 'raw', 'stop', 'usage'}.
    ⚠️ client.messages.create는 **이 함수 안에서 직접** 부른다 — api_usage 라벨 'news_summary.py:news_skt_line'(요약 호출과 따로 센다).
    어떤 예외도 밖으로 던지지 않는다 — 줄이 빠질 뿐 요약은 그대로 나간다(fail-open)."""
    out = {'line': '', 'why': '', 'raw': '', 'stop': '', 'usage': None}
    try:
        resp = client.messages.create(**skt_line_kwargs(title, source, body, summary))
        out['raw'] = ''.join(getattr(b, 'text', '') or '' for b in (resp.content or [])
                             if getattr(b, 'type', '') == 'text')
        out['stop'] = str(getattr(resp, 'stop_reason', '') or '')
        out['usage'] = getattr(resp, 'usage', None)
        out['line'], out['why'] = accept_line(out['raw'], out['stop'])
    except Exception as e:                      # noqa: BLE001
        out['why'] = f'실패: {str(e)[:80]}'
    return out


def news_tg_summary(client, title, source, body, on_summary=None) -> dict:
    """기사 1건 요약 — {'summary': 두 문장('' = 없음), 'text': 저장·발송 글(요약 + 줄, tg_text), 'why': ''|'본문 없음'|'버림'|'실패: …',
    'raw', 'stop', 'usage', 'skt': ''(언급 없음)|'ok'(줄 붙음)|'없음'(SK텔레콤만의 내용 없음)|'버림'|'잘림'|'실패: …', 'skt_line'}.
    언급 기사(규칙 7)는 요약이 된 뒤 news_skt_line을 한 번 더 부른다 — on_summary(summary)는 그 사이에 불려 호출부가 요약만이라도 먼저
    잡아 둘 수 있게 한다(줄 호출이 늦어 실행 예산을 넘겨도 요약은 나간다).
    ⚠️ client.messages.create는 **이 함수 안에서 직접** 부른다 — api_usage가 부른 함수 이름으로 비용 라벨을 단다.
    어떤 예외도 밖으로 던지지 않는다(fail-open)."""
    out = {'summary': '', 'text': '', 'why': '', 'raw': '', 'stop': '', 'usage': None, 'skt': '', 'skt_line': ''}
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
            return out
        out['text'] = tg_text(out['summary'], '')
        if on_summary:
            try:
                on_summary(out['text'])
            except Exception:                   # noqa: BLE001
                pass
        if skt_mentioned(title, input_text(body)):
            ln = news_skt_line(client, title, source, body, out['summary'])
            out['skt_line'], out['skt'] = ln['line'], ('ok' if ln['line'] else ln['why'])
            out['text'] = tg_text(out['summary'], out['skt_line'])
    except Exception as e:                      # noqa: BLE001
        out['why'] = f'실패: {str(e)[:80]}'
    return out
