# -*- coding: utf-8 -*-
"""인물 명부(people) 집계 갱신 — assembly_speeches 재수집 후 실행.
발언 수·기간·현역(22대) 여부·직함을 다시 계산하고, 새로 등장한 발언자(4건 이상)를 추가한다.
stance_summary(AI 입장 요약)는 건드리지 않는다."""
import os, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
for _p in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'): os.environ.pop(_p, None)
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
from sb_client import make_client

MEMBER_POS = {'위원','위원장','의원','위원장대리','조정위원장','간사','소위원장'}
NAME_FIX = {'金炳旭':'김병욱','金成泰':'김성태','曺明姬':'조명희'}

def fetch_all(sb, table, cols):
    out, off = [], 0
    while True:
        page = sb.table(table).select(cols).order('id').range(off, off+999).execute().data or []
        out += page
        if len(page) < 1000: break
        off += 1000
    return out

def main():
    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    sp = fetch_all(sb, 'assembly_speeches', 'speaker,position,meeting_date')
    agg = defaultdict(lambda: {'n':0,'mn':None,'mx':None,'pos':None,'t20':False,'t21':False,'t22':False})
    for r in sp:
        k = r['speaker']; d = (r['meeting_date'] or '')
        a = agg[k]; a['n'] += 1
        if d:
            a['mn'] = d if not a['mn'] or d < a['mn'] else a['mn']
            if not a['mx'] or d > a['mx']:
                a['mx'] = d; a['pos'] = r['position'] or a['pos']
            if d < '2020-05-30': a['t20'] = True
            elif d < '2024-05-30': a['t21'] = True
            else: a['t22'] = True
    people = fetch_all(sb, 'people', 'id,speaker_key,position')
    known = {p['speaker_key']: p for p in people}
    upd = ins = zero = 0
    for k, a in agg.items():
        if k == '미상': continue
        terms = '·'.join(t for t, f in (('20',a['t20']),('21',a['t21']),('22',a['t22'])) if f)
        row = {'speech_count':a['n'], 'first_speech':a['mn'], 'last_speech':a['mx'],
               'is_22':a['t22'], 'terms':(terms + '대') if terms else None,
               'position':a['pos'] or (known.get(k) or {}).get('position')}
        if k in known:
            sb.table('people').update(row).eq('id', known[k]['id']).execute(); upd += 1
        elif a['n'] >= 4:
            row.update({'speaker_key':k, 'name':NAME_FIX.get(k, k),
                        'kind':'의원' if (a['pos'] in MEMBER_POS) else '정부·참고인'})
            sb.table('people').insert(row).execute(); ins += 1
    for k, p in known.items():
        if k not in agg:
            sb.table('people').update({'speech_count':0}).eq('id', p['id']).execute(); zero += 1
    print('[명부 갱신] 갱신 %d · 신규 %d · 발언0 처리 %d' % (upd, ins, zero))

if __name__ == '__main__':
    main()
