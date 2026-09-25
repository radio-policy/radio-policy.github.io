-- 20260923160540 revoke_public_exec_sender_fns

REVOKE EXECUTE ON FUNCTION public.trigger_subscriber_briefing(), public.trigger_admin_report(), public.watchdog_scan(boolean)
  FROM PUBLIC, anon, authenticated;;
