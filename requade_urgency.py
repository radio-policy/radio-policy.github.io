"""통합 판정(#82) 구간에 잘못 매겨진 긴급도 재판정 — DB만 갱신, 알림 없음 (#84).

2026-08-04 14:30(UTC 05:30) 이후 저장분은 긴급도를 선별 콜이 매겼고, 그 결과 긴급률이
9.9% → 0.7%로 무너졌다. 개별 판정으로 원복했으므로 그 구간을 다시 매긴다.

⚠️ 알림은 보내지 않는다 — 지난 뉴스라 이제 와서 울리면 소음이다.
   이 스크립트는 news_feed.urgency/importance만 update한다. subscriber_queue·send_telegram 미사용.
"""
import os, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv()
import sb_client, crawler

CUTOFF = "2026-08-03T14:30:00+00:00"   # 통합 판정 배포 시각(UTC)

sb = sb_client.make_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
rows = (sb.table("news_feed").select("id,title,content,urgency")
        .gte("created_at", CUTOFF).order("created_at").limit(1000).execute().data or [])
print(f"대상 {len(rows)}건 (배포 시각 {CUTOFF} 이후)")

changed, same, err = [], 0, 0
for i, r in enumerate(rows, 1):
    try:
        new = crawler.classify_urgency(r.get("title") or "", r.get("content") or "")
    except Exception as e:
        err += 1
        print(f"  [오류] {str(e)[:60]} — {(r.get('title') or '')[:36]}")
        continue
    if new != r.get("urgency"):
        sb.table("news_feed").update({"urgency": new, "importance": new}).eq("id", r["id"]).execute()
        changed.append((r.get("urgency"), new, r.get("title") or ""))
    else:
        same += 1
    if i % 25 == 0:
        print(f"  … {i}/{len(rows)} 처리 (변경 {len(changed)})")
    time.sleep(0.15)

print(f"\n=== 완료: 변경 {len(changed)} / 유지 {same} / 오류 {err} ===")
up = [c for c in changed if c[1] == "긴급"]
print(f"  긴급으로 승격: {len(up)}건")
for old, new, t in up:
    print(f"    {old} → {new}  {t[:52]}")
down = [c for c in changed if c[0] == "긴급" and c[1] != "긴급"]
if down:
    print(f"  긴급에서 강등: {len(down)}건")
    for old, new, t in down:
        print(f"    {old} → {new}  {t[:52]}")
