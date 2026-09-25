# -*- coding: utf-8 -*-
"""DB 설계도(기준선) 덤프 — 실DB의 표·함수·권한·예약 작업 정의를 docs/db_baseline/에 파일로 남긴다
(§4-4-11, #227, 2026-09-26).

왜: DB 설계는 세션이 MCP·SQL Editor로 실DB에 직접 넣어 왔고 그 기록은 Supabase 안에만 있다
(2026-09-26: 표 49·함수 63·정책 79·cron 16·마이그레이션 164 vs 저장소 schema.sql 표 27·함수 14·정책 3·cron 0).
프로젝트가 망가지면 코드는 GitLab에 있어도 DB는 기억으로 다시 짜야 했다.

읽기 전용: Supabase Management API /database/query 로 카탈로그 SELECT만 보낸다(tools_release.py ⑥과 같은 경로).
SUPABASE_ACCESS_TOKEN은 계정 전권이라 PC .env에만 둔다 — GitHub Actions로 자동화하지 않는다(운영자 결정).

  py -3.12 tools_db_baseline.py --dry-run   # 개수·마스킹 결과만, 파일 안 씀
  py -3.12 tools_db_baseline.py             # docs/db_baseline/ 갱신(바뀐 파일만 다시 씀, 없어진 파일 삭제)
  py -3.12 tools_db_baseline.py --check     # 파일과 실DB 대조만(tools_release.py ⑦이 부른다)

비밀 마스킹 → fail-closed: 마스킹 뒤에도 비밀 후보가 남거나 .env 값이 출력에 들어 있으면 파일을 하나도 쓰지 않고 exit 2.
(실측: 옛 마이그레이션 원문에 운영자 봇 토큰 1건·vault.create_secret 리터럴 1건·운영자 chat_id·구 관리자 비번 해시가 있다.)
공개 저장소에 올라가므로 출력에 데이터 행은 없다(정의만). Vault·Edge 시크릿은 이름만.
"""
import os
import re
import sys
import json
import time
import argparse
import urllib.error
import urllib.request

from tools_release import load_env, PROJECT_REF, ROOT

OUT_DEFAULT = 'docs/db_baseline'

# ── 카탈로그 질의(모두 SELECT — main에서 한 번 더 확인) ──
Q = {
 'extensions': "select format('create extension if not exists %I with schema %I;', e.extname, n.nspname) s "
               "from pg_extension e join pg_namespace n on n.oid=e.extnamespace where e.extname<>'plpgsql' order by 1",
 # identity 열이 스스로 만드는 시퀀스(deptype 'i')는 빼고, serial·default nextval용만
 'sequences': "select format('create sequence if not exists public.%I;', c.relname) s from pg_class c "
              "join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind='S' "
              "and not exists (select 1 from pg_depend d where d.objid=c.oid and d.deptype='i') order by 1",
 # 외래키는 표 생성 순서에 걸리므로 15_foreign_keys로 따로 뺀다
 'tables': r"""
select format(E'create table if not exists public.%I (\n%s%s\n);%s%s', c.relname,
  string_agg(format('  %I %s%s%s', a.attname, format_type(a.atttypid, a.atttypmod),
     case when a.attidentity in ('a','d') then ' generated '||case a.attidentity when 'a' then 'always' else 'by default' end||' as identity' else '' end
     || case when ad.adbin is not null and a.attgenerated='' then ' default '||pg_get_expr(ad.adbin, ad.adrelid) else '' end
     || case when a.attgenerated='s' then ' generated always as ('||pg_get_expr(ad.adbin, ad.adrelid)||') stored' else '' end,
     case when a.attnotnull then ' not null' else '' end), E',\n' order by a.attnum),
  coalesce((select E',\n'||string_agg(format('  constraint %I %s', co.conname, pg_get_constraintdef(co.oid)), E',\n' order by co.contype desc, co.conname)
            from pg_constraint co where co.conrelid=c.oid and co.contype in ('p','u','c','x')), ''),
  case when c.relrowsecurity then format(E'\nalter table public.%I enable row level security;', c.relname) else '' end,
  case when c.relforcerowsecurity then format(E'\nalter table public.%I force row level security;', c.relname) else '' end) s
from pg_class c join pg_namespace n on n.oid=c.relnamespace
join pg_attribute a on a.attrelid=c.oid and a.attnum>0 and not a.attisdropped
left join pg_attrdef ad on ad.adrelid=c.oid and ad.adnum=a.attnum
where n.nspname='public' and c.relkind in ('r','p') group by c.oid, c.relname, c.relrowsecurity, c.relforcerowsecurity order by c.relname""",
 'foreign_keys': "select format('alter table public.%I add constraint %I %s;', c.relname, co.conname, pg_get_constraintdef(co.oid)) s "
                 "from pg_constraint co join pg_class c on c.oid=co.conrelid join pg_namespace n on n.oid=c.relnamespace "
                 "where n.nspname='public' and co.contype='f' order by c.relname, co.conname",
 'functions': "select pg_get_functiondef(p.oid)||';' s from pg_proc p join pg_namespace n on n.oid=p.pronamespace "
              "where n.nspname='public' and p.prokind in ('f','p') "
              "and not exists (select 1 from pg_depend d where d.objid=p.oid and d.deptype='e') order by p.proname, p.oid",
 'views': "select format(E'create or replace view public.%I%s as\\n%s', c.relname, "
          "coalesce(' with ('||array_to_string(c.reloptions, ', ')||')',''), pg_get_viewdef(c.oid, true)) s "
          "from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind in ('v','m') order by 1",
 'indexes': "select i.indexdef||';' s from pg_indexes i join pg_class ic on ic.relname=i.indexname "
            "join pg_namespace n on n.oid=ic.relnamespace and n.nspname=i.schemaname "
            "where i.schemaname='public' and not exists (select 1 from pg_constraint co where co.conindid=ic.oid) order by i.tablename, i.indexname",
 # auth.users 위 가입 트리거(handle_new_user)까지 — public 함수를 부르는 비내부 트리거 전부
 'triggers': "select pg_get_triggerdef(t.oid, true)||';' s from pg_trigger t join pg_proc p on p.oid=t.tgfoid "
             "join pg_namespace pn on pn.oid=p.pronamespace join pg_class c on c.oid=t.tgrelid "
             "join pg_namespace cn on cn.oid=c.relnamespace "
             "where not t.tgisinternal and (cn.nspname='public' or pn.nspname='public') order by cn.nspname, c.relname, t.tgname",
 'policies': "select format('create policy %I on %I.%I as %s for %s to %s%s%s;', policyname, schemaname, tablename, "
             "permissive, cmd, array_to_string(roles, ', '), coalesce(E'\\n  using ('||qual||')',''), "
             "coalesce(E'\\n  with check ('||with_check||')','')) s from pg_policies "
             "where schemaname in ('public','storage') order by schemaname, tablename, policyname",
 # 권한은 '전부 회수 → 지금 것만 부여'로 적는다 — 새 프로젝트의 기본 권한(#214)과 무관하게 지금과 똑같아진다
 'grants': r"""
with rel as (
  select case when c.relkind='S' then 'sequence ' else '' end||format('public.%I', c.relname) obj, c.relname k,
         coalesce(c.relacl, acldefault((case when c.relkind='S' then 's' else 'r' end)::"char", c.relowner)) acl
  from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind in ('r','p','v','m','S')
), fn as (
  select format('function public.%I(%s)', p.proname, pg_get_function_identity_arguments(p.oid)) obj, p.proname||p.oid::text k,
         coalesce(p.proacl, acldefault('f', p.proowner)) acl
  from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.prokind in ('f','p')
    and not exists (select 1 from pg_depend d where d.objid=p.oid and d.deptype='e')
), o as (select obj, k, acl, 1 g from rel union all select obj, k, acl, 2 from fn)
select format('revoke all on %s from public, anon, authenticated, service_role;%s', o.obj,
  coalesce((select string_agg(format(E'\ngrant %s on %s to %s;', x.privs, o.obj, x.grantee), '' order by x.grantee)
            from (select coalesce(r.rolname, 'public') grantee, string_agg(a.privilege_type, ', ' order by a.privilege_type) privs
                  from aclexplode(o.acl) a left join pg_roles r on r.oid=a.grantee
                  where coalesce(r.rolname, 'public') in ('public','anon','authenticated','service_role') group by 1) x), '')) s
from o order by o.g, o.k""",
 # 값은 따옴표로('3s'는 따옴표 없이는 문법 오류). session_preload_libraries는 플랫폼 관리 목록이라 뺀다
 'role_settings': "select format('alter role %I set %s = %L;', rolname, split_part(cfg, '=', 1), substr(cfg, strpos(cfg, '=') + 1)) s "
                  "from pg_roles, unnest(rolconfig) cfg where rolname in ('anon','authenticated','service_role','authenticator') "
                  "and split_part(cfg, '=', 1) <> 'session_preload_libraries' order by 1",
 'cron': "select format('select cron.schedule(%L, %L, %L);%s', jobname, schedule, command, "
         "case when active then '' else format(E'\\nselect cron.alter_job((select jobid from cron.job where jobname=%L), active := false);', jobname) end) s "
         "from cron.job order by jobname",
 'storage': "select format('insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values (%L, %L, %s, %s, %L) on conflict (id) do nothing;', "
            "id, name, case when public then 'true' else 'false' end, coalesce(file_size_limit::text,'null'), allowed_mime_types) s "
            "from storage.buckets order by id",
 # Vault는 이름·설명만(값은 절대 조회하지 않는다)
 'vault_names': "select name||coalesce('  -- '||description,'') s from vault.secrets order by name",
 'migrations': "select version, name, array_to_string(statements, E';\\n\\n') s from supabase_migrations.schema_migrations order by version",
 # 마스킹용 — 출력하지 않는다
 'chat_ids': "select distinct chat_id::text c from public.telegram_subscribers where chat_id is not null",
}
FILES = [('extensions', '00_extensions.sql'), ('sequences', '05_sequences.sql'), ('tables', '10_tables.sql'),
         ('foreign_keys', '15_foreign_keys.sql'), ('functions', '20_functions.sql'), ('views', '25_views.sql'),
         ('indexes', '30_indexes.sql'), ('triggers', '40_triggers.sql'), ('policies', '50_policies.sql'),
         ('grants', '60_grants.sql'), ('role_settings', '65_role_settings.sql'), ('cron', '70_cron.sql'),
         ('storage', '80_storage.sql'), ('vault_names', '90_vault_names.txt')]
PREAMBLE = {
    # SQL 함수 본문은 만들 때 표·뷰 존재를 검사한다 — 복구 순서에 걸리지 않게 끈다.
    # 함수 속성 SET hnsw.*·pg_trgm.*는 그 확장 라이브러리가 세션에 올라와 있어야 통과한다(#185 — 없으면
    # 'permission denied to set parameter'; 2026-09-26 복구 연습에서 벡터 검색 함수 3개가 이것으로 실패).
    'functions': ("set check_function_bodies = off;\n"
                  "select '[1,0]'::vector <=> '[0,1]'::vector;   -- vector 라이브러리 선로드\n"
                  "select extensions.word_similarity('a', 'a');   -- pg_trgm 라이브러리 선로드\n\n"),
}

README = """# DB 설계도 (docs/db_baseline) — 자동 생성, 손으로 고치지 말 것

`py -3.12 tools_db_baseline.py`가 실DB(Supabase `%(ref)s`)의 카탈로그에서 만든다(§4-4-11, 배경역사 #227).
정의만 있고 데이터는 없다. 비밀값(봇 토큰·Vault 값·운영자/구독자 chat_id·메일·해시)은 가려져 있다.
`docs/schema.sql`은 폐지됐다 — 이 폴더가 정본이다.

## 갱신
- DB를 바꾼 세션은 커밋 전에 `py -3.12 tools_release.py`를 돌린다 → ⑦이 이 폴더와 실DB가 다르면 알려 준다.
- `py -3.12 tools_db_baseline.py` → 바뀐 파일만 다시 쓴다 → `git add docs/db_baseline/<바뀐 파일>` → 3단계 검증.
- 월 1회(매월 1일 전후) 한 번 더 확인한다.

## 복구 순서 (새 Supabase 프로젝트 — SQL Editor에서 파일 순서대로)
1. `00_extensions.sql` → `05_sequences.sql` → `10_tables.sql` → `15_foreign_keys.sql`
2. `20_functions.sql`(맨 위 `set check_function_bodies = off`) → `25_views.sql` → `30_indexes.sql` → `40_triggers.sql`
3. `50_policies.sql` → `60_grants.sql`(전부 회수 후 지금 권한만 부여) → `65_role_settings.sql`(statement_timeout — 실행 뒤 `NOTIFY pgrst, 'reload config';`)
4. Vault 값 재입력: `90_vault_names.txt`의 이름마다 `vault.create_secret(값, 이름)` — 값은 운영자 보관분·재발급
   (`github_pat`는 조직 `radio-policy` 소유 fine-grained PAT, Actions R/W 필수 — 지침 #18·#116)
5. `70_cron.sql` — 1~4가 끝난 뒤(잡이 Vault·함수를 부른다). 파일의 `<OPERATOR_CHAT_ID>`는 실제 값으로 바꾼다(20_functions도 동일)
6. `80_storage.sql`(버킷) — 스토리지 정책은 50에 들어 있다
7. Edge Function: `supabase/functions/`의 폴더 전부 배포(verify_jwt는 지침 Edge 표) + Edge Secrets(지침 '외부 서비스·키')
8. Auth 설정(이메일 확인 끄기 `mailer_autoconfirm` — 지침 #104), GitHub Secrets·PC `.env`의 URL·키 교체
9. 데이터는 이 폴더에 없다 — Supabase 백업(Pro 일일 백업)에서 되살리거나 크롤러 재수집

복구 연습(2026-09-26, 빈 브랜치 DB에 1~3·6 적용, cron은 적용 후 되돌림): 다시 뜬 설계도가 표·외래키·함수·뷰·인덱스·
트리거·정책·권한·역할 설정·버킷까지 원본과 한 글자도 다르지 않았다. 다른 것은 예상한 셋뿐 — cron(되돌림)·Vault(값 재입력
전)·`pg_net` 위치(새 프로젝트엔 `extensions` 스키마에 미리 설치돼 `with schema public`이 건너뛰어짐; 함수는 `net.*`라 동작 같음).

`migrations/`는 참고용 변경 이력(Supabase `schema_migrations` 원문, 비밀 마스킹). 5/28 이전 표·SQL Editor 손 DDL이
빠져 있어 **이력을 재생해서는 복구되지 않는다** — 복구는 위 번호 파일로 한다(같은 복구 연습에서 브랜치가 이력 재생에
실패했다 — MIGRATIONS_FAILED).
"""


# ── 마스킹 ──
def _operator_chat_ids():
    """운영자 chat_id는 코드에 적지 않고 .env에서 읽는다(공개 저장소)."""
    ids = [os.environ.get(k, '') for k in ('TELEGRAM_CHAT_ID', 'OPERATOR_CHAT_ID')]
    ids += os.environ.get('OPERATOR_CHAT_IDS', '').split(',')
    return sorted({i.strip() for i in ids if re.fullmatch(r'-?\d{6,15}', i.strip())})


REDACT = [
    # \b를 쓰면 안 된다 — URL 'bot<숫자>:<키>'는 t와 숫자 사이에 단어 경계가 없어 놓친다(초안 시험에서 실측)
    ('telegram_bot_token', re.compile(r'(?<![0-9])\d{8,10}:[A-Za-z0-9_-]{30,}')),
    ('vault_create_secret', re.compile(r"(vault\.(?:create|update)_secret\s*\(\s*)'[^']*'", re.I)),
    ('jwt', re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}')),
    ('github_pat', re.compile(r'\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}')),
    ('anthropic_key', re.compile(r'\bsk-ant-[A-Za-z0-9_-]{20,}')),
    ('supabase_pat', re.compile(r'\bsbp_[A-Za-z0-9]{20,}')),
    ('bearer_literal', re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{24,}")),
    ('hex_digest', re.compile(r"'[0-9a-f]{64}'")),                       # 구 관리자 비번 sha256 등
    ('email', re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')),
]
# 마스킹 뒤에도 걸리면 중단할 탐지기(보수적: 긴 무작위 문자열)
DETECT = REDACT[:7] + [('random_40', re.compile(r"'[A-Za-z0-9_-]{40,}'"))]
DETECT_ALLOW = re.compile(r"'(?:[a-z_]+|[0-9a-f-]{36})'")   # 식별자·uuid는 허용
ENV_NOT_SECRET = {'SUPABASE_URL', 'EMAIL_FROM', 'EMAIL_TO'}   # 메일은 email 규칙이 따로 가린다


def redact(text, counts, chat_ids):
    for label, ids in (('<OPERATOR_CHAT_ID>', _operator_chat_ids()), ('<CHAT_ID>', chat_ids)):
        for cid in ids:
            rx = re.compile(r'(?<!\d)%s(?!\d)' % re.escape(cid))
            text, n = rx.subn(label, text)
            if n:
                key = label.strip('<>').lower()
                counts[key] = counts.get(key, 0) + n
    for name, rx in REDACT:
        def _sub(m, name=name):
            counts[name] = counts.get(name, 0) + 1
            if name in ('vault_create_secret', 'bearer_literal'):
                return m.group(1) + ("'<REDACTED>'" if name == 'vault_create_secret' else '<REDACTED>')
            return "'<REDACTED:%s>'" % name if m.group(0).startswith("'") else '<REDACTED:%s>' % name
        text = rx.sub(_sub, text)
    return text


def leftovers(text):
    hits = []
    for name, rx in DETECT:
        for m in rx.finditer(text):
            if not DETECT_ALLOW.fullmatch(m.group(0)) and 'REDACTED' not in m.group(0):
                hits.append(name)
    # .env의 비밀값이 그대로 들어 있으면(어느 규칙에도 안 걸린 형태라도) 중단 — 값은 출력하지 않는다
    for k, v in _ENV_VALUES.items():
        if k not in ENV_NOT_SECRET and len(v) >= 12 and v in text:
            hits.append('env:' + k)
    return hits


_ENV_VALUES = {}


def _load_env_values():
    try:
        for line in open(os.path.join(ROOT, '.env'), encoding='utf-8'):
            m = re.match(r'\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)', line)
            if m:
                _ENV_VALUES[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass


_REF = PROJECT_REF   # --ref로 바꾼다(복구 연습 브랜치를 같은 규칙으로 떠서 원본과 대조할 때)


def query(sql):
    tok = os.environ.get('SUPABASE_ACCESS_TOKEN', '').strip()
    if not tok:
        raise SystemExit('SUPABASE_ACCESS_TOKEN 없음(.env) — 중단')
    req = urllib.request.Request('https://api.supabase.com/v1/projects/%s/database/query' % _REF,
                                 data=json.dumps({'query': sql}).encode('utf-8'), method='POST',
                                 headers={'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json',
                                          'User-Agent': 'tools_db_baseline'})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise SystemExit('카탈로그 질의 실패(HTTP %s): %s\n  질의 앞부분: %s'
                         % (e.code, e.read().decode('utf-8', 'replace')[:400], sql.strip()[:120]))


def _clean(text):
    # 윈도에서 넣은 함수 본문의 CRLF를 LF로 — 저장소는 LF, 대조(--check)가 줄바꿈 차이로 흔들리지 않게
    return text.replace('\r\n', '\n').replace('\r', '\n')


def build(verbose=False):
    """실DB → {상대경로: 마스킹된 본문}, 마스킹 개수, 비밀 후보(파일별). 파일은 쓰지 않는다."""
    for key, sql in Q.items():   # 안전장치: 모든 질의는 SELECT/WITH 한 문장
        assert re.match(r'\s*(select|with)\b', sql, re.I), key
    load_env()
    _load_env_values()
    chat_ids = sorted({r['c'] for r in query(Q['chat_ids']) if re.fullmatch(r'-?\d{6,15}', r.get('c') or '')})
    counts, out, manifest = {}, {}, []
    for key, fname in FILES:
        t0 = time.time()
        rows = query(Q[key])
        if verbose:
            print('  %-14s %4d행 %.1fs' % (key, len(rows), time.time() - t0), file=sys.stderr)
        body = '\n\n'.join(r['s'] for r in rows if r.get('s'))
        head = '-- %s — tools_db_baseline.py가 실DB에서 생성(손으로 고치지 말 것), 비밀 마스킹됨\n\n' % key
        out[fname] = redact(_clean(head + PREAMBLE.get(key, '') + body + '\n'), counts, chat_ids)
        manifest.append('%-14s %4d' % (key, len(rows)))
    for r in query(Q['migrations']):
        fn = 'migrations/%s_%s.sql' % (r['version'], re.sub(r'[^A-Za-z0-9_]+', '_', r['name'] or 'unnamed'))
        out[fn] = redact(_clean('-- %s %s\n\n%s;\n' % (r['version'], r['name'], r['s'])), counts, chat_ids)
    manifest.append('%-14s %4d' % ('migrations', sum(1 for k in out if k.startswith('migrations/'))))
    out['MANIFEST.txt'] = '\n'.join(manifest) + '\n'
    out['README.md'] = README % {'ref': PROJECT_REF}
    bad = {fn: sorted(set(v)) for fn, v in ((fn, leftovers(t)) for fn, t in out.items()) if v}
    return out, counts, bad


def _existing(base):
    have = {}
    for d, _, fs in os.walk(base):
        for f in fs:
            p = os.path.join(d, f)
            have[os.path.relpath(p, base).replace(os.sep, '/')] = p
    return have


def diff_against(base, out):
    """(바뀜, 새로 생김, 없어짐) 상대경로 목록."""
    have = _existing(base)
    changed, added = [], []
    for fn, t in out.items():
        if fn not in have:
            added.append(fn)
        elif open(have[fn], encoding='utf-8', newline='').read().replace('\r\n', '\n') != t:
            changed.append(fn)
    removed = sorted(set(have) - set(out))
    return sorted(changed), sorted(added), removed


def main():
    ap = argparse.ArgumentParser(description='DB 설계도 덤프(읽기 전용, 비밀 마스킹)')
    ap.add_argument('--out', default=OUT_DEFAULT, help='출력 폴더(저장소 기준 상대 또는 절대 경로)')
    ap.add_argument('--dry-run', action='store_true', help='개수·마스킹 결과만 출력')
    ap.add_argument('--check', action='store_true', help='파일과 실DB 대조만(쓰지 않음, 다르면 exit 1)')
    ap.add_argument('--ref', default=PROJECT_REF,
                    help='대상 프로젝트 ref(기본 운영 DB). 복구 연습 브랜치를 --check로 원본 파일과 대조할 때')
    a = ap.parse_args()
    global _REF
    _REF = a.ref
    if a.ref != PROJECT_REF and not (a.check or a.dry_run):
        raise SystemExit('--ref로 운영 외 DB를 뜰 때는 --check 또는 --dry-run만(설계도 폴더를 덮지 않게)')
    out, counts, bad = build(verbose=True)
    print(out['MANIFEST.txt'].rstrip())
    print('마스킹:', counts)
    if bad:
        print('중단 — 마스킹 뒤에도 비밀 후보가 남음(파일 안 씀):')
        for fn, v in bad.items():
            print('  %s: %s' % (fn, v))
        sys.exit(2)
    base = os.path.join(ROOT, a.out)
    changed, added, removed = diff_against(base, out)
    print('실DB 대비: 바뀜 %d · 새로 %d · 없어짐 %d' % (len(changed), len(added), len(removed)))
    for label, lst in (('바뀜', changed), ('새로', added), ('없어짐', removed)):
        for fn in lst:
            print('  %s %s' % (label, fn))
    if a.dry_run:
        return
    if a.check:
        sys.exit(1 if (changed or added or removed) else 0)
    for fn in changed + added:
        p = os.path.join(base, fn)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:   # 원자적 쓰기(#51)
            f.write(out[fn])
        os.replace(tmp, p)
    for fn in removed:
        os.remove(os.path.join(base, fn))
    n = len(changed) + len(added) + len(removed)
    print('%s — 커밋: git add %s/<바뀐 파일> → 3단계 검증' % ('변경 없음' if not n else '%d개 반영' % n, a.out))


if __name__ == '__main__':
    main()
