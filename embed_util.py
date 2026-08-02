"""
Voyage AI 임베딩 공용 유틸 (2026-08-02 개선⑪ — 중복 3벌 통합).

backfill_embeddings.get_voyage_embeddings / backfill_report_embeddings.get_voyage_embeddings /
import_regulatory_kb.voyage_embed 이 이름·시그니처를 유지한 채 여기로 위임한다.

동작:
  - API 키: 인자 api_key 우선, 없으면 환경변수 VOYAGE_API_KEY (호출 시점에 읽음)
  - 429는 Retry-After 헤더 우선 대기, 그 외 HTTP 오류는 지수 대기
  - 재시도 5회, 소진 시 RuntimeError (import_regulatory_kb.voyage_embed 기존 동작과 동일)
  - timeout 기본 60초
  - 입력 검증(빈 리스트 → [], 비문자열 → ValueError)은 네트워크 접근 전에 수행
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

VOYAGE_URL = 'https://api.voyageai.com/v1/embeddings'
MAX_RETRY = 5


def get_embeddings(texts, *, input_type='document', model='voyage-4-lite',
                   dim=1024, api_key=None, timeout=60) -> list:
    """texts(문자열 리스트) → 임베딩(list[list[float]]) 리스트.

    dim은 응답 차원 검증용(요청 파라미터로 보내지 않는다 — 기존 3벌 모두 미전송).
    재시도 소진 시 RuntimeError. 호출자가 자체 재시도 루프를 가진 경우(백필 스크립트)
    그 루프의 generic except 분기에서 그대로 잡힌다.
    """
    if texts is None or isinstance(texts, str):
        raise ValueError('texts는 문자열 리스트여야 합니다')
    texts = list(texts)
    if not texts:
        return []
    if any(not isinstance(t, str) for t in texts):
        raise ValueError('texts 원소는 모두 문자열이어야 합니다')

    key = api_key or os.getenv('VOYAGE_API_KEY', '')
    if not key:
        raise RuntimeError('VOYAGE_API_KEY 미설정 (.env에 VOYAGE_API_KEY=pa-... 추가)')

    headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
    body = {'model': model, 'input': texts, 'input_type': input_type}

    last_err = ''
    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = requests.post(VOYAGE_URL, headers=headers, json=body, timeout=timeout)
        except Exception as e:
            last_err = str(e)
            print(f'\n  Voyage 오류 (재시도 {attempt}/{MAX_RETRY}): {e}')
            if attempt < MAX_RETRY:
                time.sleep(5)
            continue

        if resp.status_code == 200:
            embs = [d['embedding'] for d in resp.json()['data']]
            if dim and any(len(e) != dim for e in embs):
                raise RuntimeError(
                    f'임베딩 차원 불일치: 기대 {dim}, 응답 {len(embs[0]) if embs else 0} (model={model})')
            return embs

        last_err = f'HTTP {resp.status_code}: {resp.text[:200]}'
        if resp.status_code == 429:
            ra = resp.headers.get('Retry-After', '')
            wait = int(ra) + 1 if ra.isdigit() else min(30 * attempt, 120)
        else:
            wait = 5 * attempt
        print(f'\n  Voyage HTTP {resp.status_code} (재시도 {attempt}/{MAX_RETRY}, {wait}s)')
        if attempt < MAX_RETRY:
            time.sleep(wait)

    raise RuntimeError(f'Voyage 임베딩 실패(재시도 소진): {last_err}')
