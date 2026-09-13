# -*- coding: utf-8 -*-
"""인물 명부(people) 집계 갱신 — assembly_speeches 재수집 후 실행.
발언 수·기간·현역(22대) 여부·직함을 다시 계산하고, 새로 등장한 발언자를 추가한다.
등록 문턱: 의원·위원장 1건 이상 / 통신사 임원·전파통신 소관 라인 무조건 / 그 외 정부·참고인 4건 이상.
stance_summary(AI 입장 요약)는 건드리지 않는다."""
import os, re, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
for _p in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'): os.environ.pop(_p, None)
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
from sb_client import make_client

# 의원석 직함. '소위원장대리'·'소위원장직무대리'·'반장'은 2026-09-13까지 빠져 있어
# 이 직함만 가진 의원이 '정부·참고인'으로 분류될 수 있었다(실측 5명, #166).
MEMBER_POS = {'위원','위원장','의원','위원장대리','조정위원장','간사','소위원장',
              '소위원장대리','소위원장직무대리','위원장직무대리','반장'}
NAME_FIX = {'金炳旭':'김병욱','金成泰':'김성태','曺明姬':'조명희','柳榮夏':'유영하'}

# 등록 문턱(2026-09-13): 의원·위원장은 1건이라도 등록(회의 1회만 참석해도 소관 인물),
# 통신사 임원·전파통신 소관 실무 라인도 무조건 등록. 그 외 정부·참고인만 4건 이상.
# 통신사 임원은 회의록 직함이 '증인' 하나뿐인 경우가 대부분이라(김영섭·황현식·하현회·최택진)
# 직함만으로는 못 거른다 → 소속이 드러난 직함(TELCO_ORG)과 이름 명단(TELCO_NAMES)을 병행한다.
TELCO_ORG = re.compile(r'KT|케이티|SK텔레콤|에스케이텔레콤|SKT|SK브로드밴드|LG유플러스|엘지유플러스|유플러스|LG U\+')
TELCO_NAMES = {'황창규','구현모','김영섭','박정호','유영상','하현회','황현식','홍범식',
               '권영수','이상철','장동현','강국현','오성목','최택진','박형일','이인찬',
               '강종렬','김철수','정재헌','류정환'}
# 동명이인 오등록 방지 — 이름 명단은 증인·참고인 자격으로 나온 발언에만 적용한다.
WITNESS_POS = ('증인','참고인','대리')

# 팀 소관(전파·통신·네트워크·이용자보호) 실무 라인은 1건이라도 등록한다(2026-09-13 운영자 결정).
# 전파정책국장·통신정책관은 우리 팀 카운터파트라 발언이 적어도 인물 축으로 묶을 값어치가 있다.
# 반면 원자력·기초과학 출연연 기관장(1건짜리 120명의 몸통)은 소관이 아니라 4건 문턱을 유지한다.
POLICY_POS = re.compile(r'전파|통신정책|네트워크정책|이용자정책|시장조사|주파수')

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
    agg = defaultdict(lambda: {'n':0,'mn':None,'mx':None,'pos':None,'poss':set(),'t20':False,'t21':False,'t22':False})
    for r in sp:
        k = r['speaker']; d = (r['meeting_date'] or '')
        a = agg[k]; a['n'] += 1
        if r['position']: a['poss'].add(r['position'])
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
        is_member = bool(a['poss'] & MEMBER_POS)
        # kind는 **현재 자격**(최신 발언 직함)으로 정한다. 과거 자격은 대시보드가 발언에서
        # 역할 이력으로 계산해 보여 준다(#166) — 한 사람을 두 행으로 쪼개지 않는 설계다.
        row['kind'] = '의원' if (a['pos'] in MEMBER_POS) else '정부·참고인'
        if k in known:
            sb.table('people').update(row).eq('id', known[k]['id']).execute(); upd += 1
            continue
        is_telco = (any(TELCO_ORG.search(p) for p in a['poss'])
                    or (k in TELCO_NAMES and any(w in p for p in a['poss'] for w in WITNESS_POS)))
        is_policy = any(POLICY_POS.search(p) for p in a['poss'])
        if is_member or is_telco or is_policy or a['n'] >= 4:
            row.update({'speaker_key':k, 'name':NAME_FIX.get(k, k)})
            sb.table('people').insert(row).execute(); ins += 1
    for k, p in known.items():
        if k not in agg:
            sb.table('people').update({'speech_count':0}).eq('id', p['id']).execute(); zero += 1
    print('[명부 갱신] 갱신 %d · 신규 %d · 발언0 처리 %d' % (upd, ins, zero))

if __name__ == '__main__':
    main()
