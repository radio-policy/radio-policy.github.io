-- 20260814071133 admin_daily_report_cron

-- 시크릿은 Vault 에 둔다 (평문 하드코딩 금지 — 배경역사 #61 의 봇 토큰 사고와 같은 유형).
select vault.create_secret(
  '<REDACTED>',
  'admin_report_cron_secret',
  '운영자 일일 구독자 리포트 Edge Function 호출용 (2026-08-14)'
);

-- pg_cron → Edge Function. subscriber-briefing 과 같은 패턴.
create or replace function public.trigger_admin_report()
returns void
language plpgsql
security definer
as $$
begin
  perform net.http_post(
    url := 'https://zwkjedumfuhodckmtxxn.supabase.co/functions/v1/admin-daily-report',
    body := '{}'::jsonb,
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'x-cron-secret', (select decrypted_secret from vault.decrypted_secrets where name = 'admin_report_cron_secret')
    )
  );
end;
$$;

-- 매일 08:00 KST = 23:00 UTC (전날).
select cron.schedule('admin-daily-report', '0 23 * * *', $$select public.trigger_admin_report()$$);;
