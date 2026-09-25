#!/usr/bin/env python3
"""전파정책 외부 헬스 워치독 (GitHub Actions에서 실행 — Supabase와 독립).

목적: 파이프라인이 '조용히' 멈추는 것을 잡는다.
  ① Supabase 데이터 신선도: 뉴스(news_feed) 최신 입력, 오늘자 브리핑 존재
  ② 각 워크플로우의 '마지막 성공 실행'(GitHub Actions run 이력 = heartbeat)
     → 데이터가 안 바뀌어도 '돌았다 vs 안 돌았다'를 정확히 구분(법령·국회처럼 변동이 드문 것도 커버)
  ③ PC 예약작업 heartbeat(system_health): 정부고시 체인·본문 재수집은 Actions에 없어 ②로 못 본다.
     lampmanH-pc(24시간, 본선 — #179)가 서면 여기서 잡아 "lampmanH-pc 확인"으로 알린다.
이상이 하나라도 있으면 텔레그램으로 경고. 모두 정상이면 조용히 종료(무음).
Supabase가 통째로 다운이면 그 접속 실패 자체도 경고로 발송 → 단일 장애점 커버.

이 스크립트는 GitHub Actions에서 도므로 Supabase와 독립적이다. Supabase 내부의
pg_cron 워치독(check_news_health)과 서로의 사각지대를 덮는다(이중 안전망).

필요 env(모두 GitHub Secrets에 이미 존재): SUPABASE_URL, SUPABASE_SERVICE_KEY,
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GITHUB_TOKEN(Actions 자동 제공), GITHUB_REPOSITORY(자동).
표준 라이브러리만 사용(pip 설치 불필요).
"""
import os
import sys
import json
import datetime
import urllib.request
import urllib.error

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "radio-policy/radio-policy.github.io")

NOW = datetime.datetime.now(datetime.timezone.utc)
KST = datetime.timezone(datetime.timedelta(hours=9))


def http_get_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def hours_since(iso):
    """ISO8601 문자열로부터 현재까지 경과 시간(시간)."""
    s = (iso or "").replace("Z", "+00:00")
    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return (NOW - dt).total_seconds() / 3600.0


problems = []

# GitHub Actions 헤더 (워크플로우 성공 이력 조회용)
gh_headers = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "radiopolicy-watchdog",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GH_TOKEN:
    gh_headers["Authorization"] = "Bearer " + GH_TOKEN


def workflow_last_success_hours(wf):
    """워크플로우의 마지막 '성공' 실행 이후 경과 시간(시간). 알 수 없으면 None.

    `?status=success`로 걸러 묻지 않는다(#225, 2026-09-26) — GitHub 문서상 status·event·created 등으로 거른
    목록은 **검색 색인**을 거쳐 늦게 갱신될 수 있고, 09-25 21:35 실행이 morning_briefing.yml의 '최신 성공'으로
    09-01 실행을 받아 "591.5시간 전" 오경보를 냈다(같은 시각 거르지 않은 목록엔 09-25 성공이 있었다).
    거르지 않은 최근 100개에서 conclusion=success 첫 행을 찾고, 100개 안에 없을 때만 걸러 묻는다(나이 계산용).
    """
    base = "https://api.github.com/repos/%s/actions/workflows/%s/runs" % (REPO, wf)
    try:
        runs = http_get_json(base + "?per_page=100", gh_headers).get("workflow_runs", [])
        ok = [r for r in runs if r.get("conclusion") == "success"]
        if not ok:
            ok = http_get_json(base + "?status=success&per_page=1", gh_headers).get("workflow_runs", [])
        if not ok:
            return None
        return min(hours_since(r["created_at"]) for r in ok)
    except Exception:
        return None


# 크롤러가 '실제로 도는지' 먼저 확인 → '새 뉴스 없음'과 '크롤러 고장'을 구분(주말 오경보 방지)
crawl_h = workflow_last_success_hours("daily_crawl.yml")
crawl_running = (crawl_h is not None and crawl_h < 14)

# ── ① Supabase 데이터 신선도 (접속 실패 시 그 자체가 경고) ──
sb_headers = {"apikey": SUPABASE_KEY, "Authorization": "Bearer " + SUPABASE_KEY}
try:
    rows = http_get_json(
        SUPABASE_URL + "/rest/v1/news_feed?select=created_at&order=created_at.desc&limit=1",
        sb_headers,
    )
    if not rows:
        problems.append("news_feed가 비어 있음")
    else:
        h = hours_since(rows[0]["created_at"])
        if h >= 14 and not crawl_running:
            # 뉴스도 멈췄고 크롤러도 미성공 → 진짜 고장
            problems.append("뉴스 %.1f시간째 미입력 + 크롤러도 미성공 → 크롤러/트리거 점검" % h)
        elif h >= 30 and crawl_running:
            # 크롤러는 정상인데 30h+ 새 뉴스 0건 → NAVER 키·필터 등 '조용한 실패' 의심
            problems.append("크롤러는 정상인데 %.1f시간째 새 뉴스 0건 → NAVER 키·필터 점검 권장" % h)
        elif h >= 14:
            # 크롤러는 도는데 새 뉴스만 없음(주말 등) → 정상으로 보고 경고 안 함
            print("[워치독] 뉴스 %.1fh 미입력이나 크롤러 정상(%s) → 새 뉴스 없음으로 판단(경고 생략)"
                  % (h, ("%.1fh 전 성공" % crawl_h) if crawl_h is not None else "상태불명"))

    now_kst = datetime.datetime.now(KST)
    # 브리핑은 06:05 생성 → KST 09시 이후에만 '미생성'을 이상으로 판정(새벽 오탐 방지)
    if now_kst.hour >= 9:
        today_kst = now_kst.date().isoformat()
        br = http_get_json(
            SUPABASE_URL + "/rest/v1/daily_briefings?select=briefing_date&briefing_date=eq." + today_kst,
            sb_headers,
        )
        if not br:
            problems.append("오늘(%s) 모닝 브리핑 미생성" % today_kst)
except Exception as e:  # 접속 불가 = Supabase 다운 의심
    problems.append("⛔ Supabase 접속 불가: %s" % e)

# ── ② GitHub Actions 워크플로우별 마지막 성공 실행(heartbeat) ──
# daily_crawl은 위 ①에서 crawl_running으로 이미 판정 → 여기선 제외(중복 경고 방지)
checks = {
    "morning_briefing.yml": 26,   # 하루 1회 → 26h
    "law_crawl.yml": 26,          # 하루 1회
    "assembly_crawl.yml": 26,     # 하루 1회
}
for wf, thresh in checks.items():
    h = workflow_last_success_hours(wf)
    if h is None:
        problems.append("%s 성공 실행 기록 확인 실패" % wf)
    elif h >= thresh:
        problems.append("%s 마지막 성공 %.1f시간 전 (임계 %dh)" % (wf, h, thresh))

# ── ③ PC 예약작업 heartbeat (system_health) — lampmanH-pc 본선(#179, 2026-09-20) ──
# gov 체인(16:30)·본문 재수집(매시 22분)은 GitHub Actions 밖(한국 IP 필요)이라 ②의 run 이력이 없다.
# 내부 watchdog_scan(pg_cron)도 같은 키를 보지만 Supabase cron이 서면 함께 서므로 여기서도 본다.
# ①에서 Supabase 접속 불가로 이미 경고했으면 중복 경고를 피해 건너뛴다.
PC_HEARTBEATS = {
    "last_gov_notice_run": (26, "정부고시·입법예고 체인(lampmanH-pc 16:30)"),   # 하루 1회 → 26h
    "last_refetch_run":    (3,  "뉴스 본문 재수집(lampmanH-pc 매시 22분)"),     # 매시 → 3h
}
if not any(p.startswith("⛔") for p in problems):
    try:
        rows = http_get_json(
            SUPABASE_URL + "/rest/v1/system_health?select=key,updated_at&key=in.(%s)"
            % ",".join(PC_HEARTBEATS),
            sb_headers,
        )
        seen = {r.get("key"): r.get("updated_at") for r in rows}
        for key, (thresh, label) in PC_HEARTBEATS.items():
            if not seen.get(key):
                problems.append("%s heartbeat(%s) 기록 없음 — lampmanH-pc 확인" % (label, key))
                continue
            h = hours_since(seen[key])
            if h >= thresh:
                problems.append("%s 마지막 실행 %.1f시간 전 (임계 %dh) — lampmanH-pc 확인" % (label, h, thresh))
            else:
                print("[워치독] %s %.1fh 전 실행 (정상)" % (label, h))
    except Exception as e:
        problems.append("system_health heartbeat 조회 실패: %s" % e)

# ── ③-2 봇 지침서 동기화 (B-9, #210) ──
# 텔레그램 /ask·인용 검증기는 app_config.system_prompt를, 대시보드는 저장소 system_prompt.js를 쓴다.
# 파일만 고치고 sync_system_prompt.py를 잊으면 봇만 옛 프롬프트로 돈다 — 체크아웃된 파일과 DB 값을 대조한다.
# 추출 규칙은 sync_system_prompt.extract_prompt와 같다(첫 " ~ 마지막 " 을 JSON 문자열로). 대시보드 운영 상태에도 같은 줄.
if not any(p.startswith("⛔") for p in problems):
    try:
        import hashlib
        _js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_prompt.js"), encoding="utf-8").read()
        _file_prompt = json.loads(_js[_js.index('"'):_js.rindex('"') + 1])
        rows = http_get_json(SUPABASE_URL + "/rest/v1/app_config?select=value&key=eq.system_prompt", sb_headers)
        _db_prompt = rows[0].get("value") if rows else None
        if not _db_prompt:
            problems.append("봇 지침서(app_config.system_prompt) 없음 — python sync_system_prompt.py 실행 필요")
        elif hashlib.sha256(_db_prompt.encode("utf-8")).digest() != hashlib.sha256(_file_prompt.encode("utf-8")).digest():
            problems.append("봇 지침서가 system_prompt.js와 다름(파일 %d자 / 봇 %d자) — python sync_system_prompt.py 실행 필요"
                            % (len(_file_prompt), len(_db_prompt)))
        else:
            print("[워치독] 봇 지침서 동기화 정상 (%d자)" % len(_file_prompt))
    except Exception as e:
        problems.append("봇 지침서 동기화 확인 실패: %s" % e)

# ── ③-3 AI 비용 계측 경보 (§4-2-8) ──
# api_usage는 기록만 하고 아무도 안 보면 캐시가 깨져도 모른다 — 9/18~19에 선별·긴급도 콜의 캐시가
# 100% 빗나가 호출당 입력이 4,800~13,700토큰이었는데, 표를 직접 열어 보기 전까지 몰랐다(#174·#175로 해결).
#   ⓐ 캐시 적중률: 1시간 캐시를 쓰는 두 콜의 최근 24시간 적중(cache_read>0) 비율 < 80%면 경고(표본 10건 이상).
#   ⓑ 비용 급증: 최근 24시간 추정 비용 > 그 전 7일(24시간 단위) 중앙값 × 2 이고 $1 이상이면 경고 + 상위 3곳.
# 단가는 추정용(청구서 아님). 캐시 쓰기는 1시간 캐시 기준 입력 2배, 읽기 0.1배.
CACHED_SITES = ("crawler.py:_screen_batch_haiku", "crawler.py:classify_urgency")
PRICES = {"haiku": (1.0, 5.0), "sonnet": (2.0, 10.0), "opus": (5.0, 25.0)}   # $/백만 토큰 (입력, 출력)
# 실행마다 자기 비용을 텔레그램으로 알리는 작업은 급증 계산에서 뺀다(중복 경고 방지) — okf_refresh(#198, 교체 있는 날만 ≈$2)
SELF_REPORTED = ("okf_refresh.py:",)


def _usage_cost(r):
    m = (r.get("model") or "").lower()
    pin, pout = next((v for k, v in PRICES.items() if k in m), PRICES["sonnet"])
    n = lambda k: r.get(k) or 0
    return (n("input_tokens") * pin + n("cache_read") * pin * 0.1
            + n("cache_write") * pin * 2 + n("output_tokens") * pout) / 1e6


if not any(p.startswith("⛔") for p in problems):
    try:
        since = (NOW - datetime.timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows, off = [], 0
        while True:   # PostgREST 1,000행 상한 — 나눠 읽는다(하루 ≈700행)
            page = http_get_json(
                SUPABASE_URL + "/rest/v1/api_usage?select=ts,site,model,input_tokens,cache_read,cache_write,output_tokens"
                "&ts=gte.%s&order=id&limit=1000&offset=%d" % (since, off), sb_headers)
            rows += page
            if len(page) < 1000:
                break
            off += 1000
        day_cost = [0.0] * 8          # [0] = 최근 24시간, [1..7] = 그 전 날들
        site_cost, hit = {}, {s: [0, 0] for s in CACHED_SITES}
        for r in rows:
            d = int(hours_since(r["ts"]) // 24)
            if not 0 <= d < 8:
                continue
            if (r.get("site") or "").startswith(SELF_REPORTED):
                continue
            c = _usage_cost(r)
            day_cost[d] += c
            if d == 0:
                site_cost[r.get("site") or "?"] = site_cost.get(r.get("site") or "?", 0) + c
                if r.get("site") in hit:
                    hit[r["site"]][1] += 1
                    hit[r["site"]][0] += 1 if (r.get("cache_read") or 0) > 0 else 0
        for s, (h, t) in hit.items():
            if t >= 10 and h / t < 0.8:
                problems.append("AI 캐시 적중률 저하: %s %d/%d(%.0f%%) — system 블록이 매번 바뀌거나 최소 길이 미달 의심(#175)"
                                % (s.split(":")[1], h, t, 100.0 * h / t))
        prev = sorted(day_cost[1:])
        median = prev[3]
        if day_cost[0] >= 1.0 and day_cost[0] > median * 2:
            top = sorted(site_cost.items(), key=lambda kv: -kv[1])[:3]
            problems.append("AI 비용 급증: 최근 24시간 ≈$%.2f (직전 7일 중앙값 $%.2f) — 상위 %s"
                            % (day_cost[0], median, ", ".join("%s $%.2f" % kv for kv in top)))
        print("[워치독] AI 비용 24h ≈$%.2f (7일 중앙값 $%.2f), 캐시 적중 %s"
              % (day_cost[0], median, ", ".join("%s %d/%d" % (s.split(":")[1], h, t) for s, (h, t) in hit.items())))
    except Exception as e:
        problems.append("AI 비용 계측 확인 실패: %s" % e)

# ── ④ 결과 → 텔레그램(이상 있을 때만, 정상이면 무음) ──
if problems:
    msg = "⚠️ [전파정책 헬스 워치독] 이상 감지 (%s KST):\n- %s" % (
        datetime.datetime.now(KST).strftime("%m-%d %H:%M"),
        "\n- ".join(problems),
    )
    body = json.dumps({"chat_id": TG_CHAT, "text": msg}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendMessage" % TG_TOKEN,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=20)
        print("[워치독] 경고 발송:", problems)
    except Exception as e:
        print("[워치독] 텔레그램 발송 실패:", e)
        sys.exit(1)
else:
    print("[워치독] 모든 파이프라인 정상")
