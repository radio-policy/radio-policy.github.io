"""
텔레그램 전송 공용 유틸 (2026-08-02 개선⑪ — 중복 전송부 통합).

각 스크립트의 send_telegram()/send_operator_alert()는 이름·시그니처·부가 동작을
그대로 두고 '전송부'만 이 모듈에 위임한다(회귀 0 원칙).
파일별 고유 동작(브리핑 가공, 구독자 큐 적재, 로그 문구)은 각 파일에 남는다.

동작:
  - 토큰/기본 chat_id는 환경변수 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (호출 시점에 읽음)
  - 4096자 절단 전 3800자에서 안전 분할 (개행 경계 우선)
  - 재시도 3회(지수 백오프), 429는 Retry-After 헤더 우선
  - 4xx(429 제외)는 영구 오류로 보고 재시도하지 않음 (HTML 파싱 400 등 — 호출자가 폴백)
  - 실패 시 False + print, 예외는 절대 전파하지 않음
"""

import os
import sys
import time

# cp949 콘솔·파이프에서 이모지 print 크래시 방지 (지침 가드레일 #19)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests

SPLIT_LIMIT = 3800   # 텔레그램 4096자 한도 전 안전 여유
MAX_RETRY = 3
TIMEOUT = 15


def split_message(text: str, limit: int = SPLIT_LIMIT) -> list:
    """limit 이하 조각 리스트로 분할. 개행 경계 우선, 한 줄이 limit 초과면 강제 절단.

    개행 경계 분할이면 '\\n'.join(조각들) == 원문 (내용 무손실).
    """
    text = text or ''
    if len(text) <= limit:
        return [text] if text else []
    chunks, cur = [], ''
    for line in text.split('\n'):
        while len(line) > limit:          # 초장문 한 줄은 강제 절단
            if cur:
                chunks.append(cur)
                cur = ''
            chunks.append(line[:limit])
            line = line[limit:]
        if cur and len(cur) + 1 + len(line) > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f'{cur}\n{line}' if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def send_telegram(text: str, *, chat_id=None, parse_mode=None,
                  disable_web_page_preview: bool = False,
                  reply_markup: dict | None = None) -> bool:
    """텔레그램 발송. 전 조각 성공 시 True, 하나라도 실패(또는 env 미설정) 시 False.

    예외를 전파하지 않는다 — 알림 실패가 크롤러 본연의 수집을 죽이면 안 된다.
    reply_markup(인라인 키보드 등, 2026-08-26 이슈맵 승인 버튼용)은 **마지막 조각에만**
    붙인다 — 분할 발송 시 버튼이 조각마다 복제되면 중복 클릭을 유발한다.
    """
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        print('[텔레그램] 환경변수 미설정 (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID) — 건너뜀')
        return False
    if not text:
        return False

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    ok = True
    chunks = split_message(text)
    for i, chunk in enumerate(chunks):
        payload = {'chat_id': chat_id, 'text': chunk}
        if parse_mode:
            payload['parse_mode'] = parse_mode
        if disable_web_page_preview:
            payload['disable_web_page_preview'] = True
        if reply_markup and i == len(chunks) - 1:
            payload['reply_markup'] = reply_markup

        sent = False
        for attempt in range(1, MAX_RETRY + 1):
            try:
                resp = requests.post(url, json=payload, timeout=TIMEOUT)
            except Exception as e:
                print(f'[텔레그램 오류] {e}')
                if attempt < MAX_RETRY:
                    time.sleep(2 ** attempt)
                continue
            if resp.status_code == 200:
                sent = True
                break
            print(f'[텔레그램 오류] HTTP {resp.status_code}: {resp.text[:200]}')
            if resp.status_code == 429:
                ra = resp.headers.get('Retry-After', '')
                wait = int(ra) + 1 if ra.isdigit() else 2 ** attempt
            elif 400 <= resp.status_code < 500:
                break                     # 영구 오류(파싱 실패 등) — 재시도 무의미
            else:
                wait = 2 ** attempt
            if attempt < MAX_RETRY:
                time.sleep(wait)
        if not sent:
            ok = False
    return ok
