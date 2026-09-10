"""
Anthropic API 토큰 사용량 기록 (배경역사 #152, 2026-09-10).

왜: 월 $75~90의 정기 청구가 어느 호출에서 나오는지 어디에도 기록이 없었다(횟수 한도만 있음).
    콘솔은 키 하나를 Actions·PC·Edge가 같이 써서 용도 구분이 안 된다. 절감안(요약 지연 생성,
    그림자 판정, 프롬프트 캐시)의 효과를 확인하려면 호출별 usage가 필요하다.

어떻게: `install()`이 anthropic SDK의 `Messages.create`를 한 번 감싸서(멱등) 응답의 `usage`를
    `api_usage` 표에 1행 insert 한다. 호출부 코드는 바꾸지 않는다 — site 라벨은 호출한 함수 이름에서
    자동으로 뽑는다('crawler.py:classify_urgency'). 스트리밍 응답(usage 없음)은 건너뛴다.
    Message Batches 결과는 SDK 경로가 달라 `record_usage()`로 명시 기록한다(press_ingest).

규약: **어떤 예외도 밖으로 내지 않는다(fail-open)**. 기록 실패가 판정·수집을 죽이면 안 된다.
    원본 응답은 그대로 돌려준다(반환 규약 무변경).
"""
import os
import sys
import inspect
from datetime import datetime, timezone

HOST = 'actions' if os.environ.get('GITHUB_ACTIONS', '').lower() == 'true' else 'pc'
_sb = None
_installed = False
_fail_count = 0
_MAX_FAIL = 5          # 연속 실패가 쌓이면 이 프로세스에서는 기록을 포기(네트워크 장애 시 지연 방지)


def _client():
    global _sb
    if _sb is None:
        from sb_client import make_client
        _sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    return _sb


def _usage_row(site: str, usage, model) -> dict | None:
    if usage is None:
        return None
    g = (lambda k: int(getattr(usage, k, None) or (usage.get(k) if isinstance(usage, dict) else 0) or 0))
    return {
        'host': HOST,
        'site': (site or 'unknown')[:120],
        'model': (str(model) if model else None),
        'input_tokens': g('input_tokens'),
        'cache_read': g('cache_read_input_tokens'),
        'cache_write': g('cache_creation_input_tokens'),
        'output_tokens': g('output_tokens'),
        'ts': datetime.now(timezone.utc).isoformat(),
    }


def record_usage(site: str, usage, model=None) -> None:
    """usage 객체(또는 dict)를 1행 기록. 실패는 삼킨다."""
    global _fail_count
    if _fail_count >= _MAX_FAIL:
        return
    try:
        row = _usage_row(site, usage, model)
        if row is None:
            return
        _client().table('api_usage').insert(row).execute()
        _fail_count = 0
    except Exception as e:                       # noqa: BLE001 — fail-open이 규약
        _fail_count += 1
        try:
            print(f'[api_usage] 기록 실패(무시 {_fail_count}/{_MAX_FAIL}): {str(e)[:80]}')
        except Exception:
            pass


def record(site: str, resp, model=None):
    """응답 객체의 usage를 기록하고 **응답을 그대로 반환**한다 (감싸 쓰기용)."""
    try:
        record_usage(site, getattr(resp, 'usage', None), model or getattr(resp, 'model', None))
    except Exception:
        pass
    return resp


def _caller_site(depth: int = 2) -> str:
    """래퍼를 부른 스크립트 파일명:함수명 — 'crawler.py:classify_urgency'."""
    try:
        fr = inspect.currentframe()
        for _ in range(depth):
            fr = fr.f_back if fr is not None else None
        if fr is None:
            return 'unknown'
        return f'{os.path.basename(fr.f_code.co_filename)}:{fr.f_code.co_name}'
    except Exception:
        return 'unknown'


def install() -> None:
    """anthropic SDK `Messages.create`를 감싼다. 여러 모듈이 불러도 한 번만 적용된다."""
    global _installed
    if _installed:
        return
    try:
        from anthropic.resources.messages import Messages
        if getattr(Messages, '_api_usage_wrapped', False):
            _installed = True
            return
        orig = Messages.create

        def create(self, *args, **kwargs):
            resp = orig(self, *args, **kwargs)
            try:
                if not kwargs.get('stream'):
                    record_usage(_caller_site(2), getattr(resp, 'usage', None), kwargs.get('model'))
            except Exception:
                pass
            return resp

        Messages.create = create
        Messages._api_usage_wrapped = True
        _installed = True
    except Exception as e:                       # SDK 구조가 바뀌어도 스크립트는 살아야 한다
        try:
            print(f'[api_usage] install 실패(기록 없이 진행): {str(e)[:80]}')
        except Exception:
            pass
