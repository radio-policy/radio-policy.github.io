"""
Supabase 클라이언트 공용 생성기.

supabase-py 2.31.0 / postgrest 2.31.0가 httpx[http2]를 끌어오면서 Supabase REST 호출이
HTTP/2 로 협상되고, Supabase 엔드포인트가 HTTP/2 연결을 끊어 `httpx.RemoteProtocolError:
Server disconnected`로 죽는 알려진 버그(supabase-py #1064, HTTP/2 keepalive 문제)를 회피한다.

해결: HTTP/1.1 강제(http2 미사용) + 재시도 3회 + keepalive 연결 1개로 제한.
모든 스크립트는 `create_client(...)` 대신 이 `make_client(...)`를 사용한다.
※ ClientOptions(httpx_client=...) 전달은 supabase-py 2.16.0+ 에서 지원.
"""
import datetime
import httpx
from supabase import create_client, Client, ClientOptions


def heartbeat(sb: Client, key: str, note: str) -> None:
    """system_health[key] 갱신. 실패해도 본작업에 영향 없음(fail-open).

    watchdog_scan 은 watchdog_targets 에 등록된 키의 이 값을 읽어 지연·무음실패를 잡는다.
    하트비트를 남기지 않는 스크립트는 구조적으로 감시 대상이 될 수 없다 — 실제로 법령
    현행화 3종이 그래서 감시 밖이었고, 고시 하나가 4개월째 구버전인 것을 아무도 몰랐다(#169-보론2).
    note 에는 건수를 남긴다(`fail=N`·`outdated=N` 이 N>0면 워치독이 '돌았지만 실패'로 본다).
    """
    import datetime as _dt
    try:
        sb.table('system_health').upsert(
            {'key': key,
             'updated_at': _dt.datetime.now(_dt.timezone.utc).isoformat(),
             'note': note},
            on_conflict='key').execute()
        print('[heartbeat] system_health.%s 갱신 — %s' % (key, note))
    except Exception as e:
        print('[heartbeat 오류 — 무시] %s: %s' % (key, str(e)[:80]))


def ran_recently(sb: Client, key: str, hours: float) -> bool:
    """system_health[key]가 `hours` 시간 안에 갱신됐으면 True.

    pg_cron(주 트리거)과 GitHub Actions cron(백업)이 같은 시각에 걸려 하루 두 번 전량
    실행되던 것을 막는 가드다(2026-09-14 실측: foreign_press 4일 연속 2회, 전체 API 로그의
    19.6%). 시각을 어긋내는 것만으로는 주 트리거가 성공해도 백업이 또 도는 것을 못 막는다.
    조회 실패는 False(=실행)로 fail-open — 가드 때문에 수집이 통째로 빠지면 안 된다.
    """
    try:
        r = sb.table('system_health').select('updated_at').eq('key', key).maybe_single().execute()
        ts = (getattr(r, 'data', None) or {}).get('updated_at')
        if not ts:
            return False
        prev = datetime.datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - prev).total_seconds() < hours * 3600
    except Exception as e:
        print('[가드 조회 실패 — 실행 계속] %s' % e)
        return False


def make_client(url: str, key: str) -> Client:
    # transport를 명시하면 protocol(HTTP/1.1)·retries·limits가 transport 기준으로 적용된다.
    # HTTPTransport는 기본 http2=False → HTTP/1.1 사용(=Server disconnected 버그 원인 제거).
    transport = httpx.HTTPTransport(
        retries=3,
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=1,   # keepalive 소켓 재사용 최소화(끊긴 연결 재사용 방지)
            keepalive_expiry=30,
        ),
    )
    http_client = httpx.Client(transport=transport, timeout=httpx.Timeout(30.0))
    return create_client(url, key, options=ClientOptions(httpx_client=http_client))
