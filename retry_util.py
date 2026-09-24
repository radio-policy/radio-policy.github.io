"""
재시도 공용 틀 (2026-09-25, #217 — 개선안 §4-2-12 단계 C).

정부 사이트·국회/법제처 API 호출마다 "3회 시도, 사이 5초 대기, 마지막 실패는 그대로 raise" 루프가
7개 파일 11곳에 복사돼 있었다(배경역사 #23의 재시도 정책). 요청 자체(curl_cffi 위장 여부·헤더·
Referer·인코딩)는 곳마다 달라 각 파일에 남기고, 반복 틀만 여기 하나로 모은다.

쓰지 않는 곳(의미가 다름): law_watch.drf_law_search(실패 시 None·대기 2/4초),
notify(429 Retry-After), embed_util(429·배치 분할).
"""
import time


def with_retry(fn, *, retries: int = 3, delay: float = 5, label: str = None,
               raise_status: bool = True):
    """fn()을 최대 retries번 부른다. 예외가 나면 delay초 쉬고 다시, 마지막 실패는 그대로 raise.

    raise_status: fn이 HTTP 응답(raise_for_status 보유)을 돌려주면 그 검사도 재시도 안에서 한다
                  — 5xx·4xx도 일시 오류로 보고 다시 시도하던 종전 루프와 같다.
    label: 주면 재시도마다 '  [재시도 i/n] label: 오류' 한 줄을 찍는다(없으면 조용히).
    """
    for attempt in range(1, retries + 1):
        try:
            res = fn()
            if raise_status and hasattr(res, 'raise_for_status'):
                res.raise_for_status()
            return res
        except Exception as e:
            if attempt >= retries:
                raise
            if label is not None:
                print('  [재시도 %d/%d] %s: %s' % (attempt, retries, label, str(e)[:120]))
            time.sleep(delay)
