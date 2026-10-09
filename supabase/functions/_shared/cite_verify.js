// ============================================================================
//  cite_verify.js — 자문 답변의 「[원문 확인됨]」 표시를 기계가 검증한다 (#155, 2026-09-11)
//
//  배경: 이 표시는 프롬프트 지시로 모델이 스스로 붙이는 자기 신고였다. 9/10 텔레그램 자문이
//  전기통신사업법 제50조①5호·5호의2를 "차별적 지원금"으로 설명하며 표시를 붙였는데, 실제로
//  검색돼 모델 앞에 놓인 것은 제50조 뒷조각(8호~③)뿐이었고 5호·5호의2 본문은 없었다.
//  "표시가 붙었다 = 내가 따로 검증할 필요 없다"가 사용자에게 내건 약속이므로 코드가 보증해야 한다.
//
//  세 단계 (운영자 결정 2026-09-11):
//   1) expandArticles   — 검색된 조문이 여러 조각이면 나머지 조각을 붙여 조문을 통째로 모델에 준다
//                         (잘린 채 들어간 것이 이번 사고의 직접 원인).
//   2) checkCitation    — 답변의 각 표시 앞 인용(법령명·조·항·호·별표)을 파싱해, 그 원문이 실제로
//                         검색 결과(+시스템 프롬프트 핵심 조문)에 있었는지 대조. 없으면 표시를
//                         「[⚠️ 원문 미확인 — 검색 결과에 해당 조문 없음]」으로 바꾼다.
//   3) judge(Haiku)     — 원문이 있었던 인용은 원문과 답변 문장을 나란히 Haiku에 보내 "다르게 옮겼는가"를
//                         판정. 불일치면 「[⚠️ 원문과 다르게 설명됨 — 확인 필요]」로 바꾼다.
//                         판단불가·호출 실패는 표시를 그대로 둔다(fail-open).
//
//  #230(2026-09-26, 운영자 결정) — ① 역참조 발췌가 다른 법령 조문(「…」·같은 법·(시행령의) 법 제N조)을 가리킨 줄을 인용으로
//   치지 않고, 정의·목적·목록 조문을 빼고, 제재 조문(벌칙·과태료·과징금 등)은 별도 칸으로 먼저 싣는다(금액이 적힌 항 머리 포함)
//   ② 표시 없는 인용 문단·따옴표 인용도 같은 경로로 대조한다(tagUntaggedQuotes — 판정 기준은 그대로).
//
//  #288(2026-10-07, Fable 판정 local_docs/자문세문제_판정_261007.md §4·§5·§12 · 운영자 결정) — 판정 지시문·모델은 그대로, 구조만:
//   ⓐ 대상 없는 토막 표시 → 바로 앞 문단에 표시가 있으면 중복(dup) ⓑ 「<종류>고시 제YYYY-N호」는 그 번호의 문서가 자료에 하나일 때만(추측 등급)
//   ⓓ′ 표시 하나가 조문 둘 이상을 덮으면 자료에 있는 후보 조문 전부를 한 원문으로 ⓒ 이름 적은 조문이 자료에 없으면 DB에서 받아 대조
//   §5 항 구분이 없는 조문에 제2항 이상을 적으면(DB 저장본으로 확인) 회색.
//
//  #294(2026-10-09, 사내 선행 이식 — 사내 8c8c373c·35fd1814, 운영자 결정 「권고대로」 1단계, Fable 재검토 대기) — 판정 지시문·2차 모델·관문은 그대로, 입력 쪽만:
//   ② 판 표지로 판 고르기(같은 조 현행·시행예정 — 번호·시행일·「시행예정/현행」, 없으면 현행) + 외부 전용: 자료에 판이 하나뿐인데 표지가 다른 판을 가리키면
//     DB에서 판들을 받아 대조(ⓒ와 OUTSIDE_MAX 공유) ③ closed-before — 「…를 준용합니다.[표시]」는 그 줄이 인용문 ④ 「규정 제N조」·「동 규정」처럼 종류 낱말뿐인
//   이름은 앞에서 이름 나온 그 종류 법령을 이어받음 ㉠ 주황 이유 글 「X와 대조해 판정기가 다르다고 봄(직접 확인): …」. 「2차 불일치 → 다른 판 재판정」은 넣지 않았다.
//
//  한 파일을 세 곳이 그대로 쓴다 — Deno Edge(rag.ts, verify-citations), 브라우저(index.html <script>),
//  node 테스트(tests/cite_verify.test.js). 그래서 TS 문법·export 없이 globalThis.CiteVerify 에 붙인다.
//  GitLab Pages는 나열된 파일만 싣는다 — .gitlab-ci.yml의 cp 목록에 이 경로가 있어야 한다.
//  DB·API 호출은 전부 호출측이 콜백(fetchArticle, callHaiku)으로 넘긴다 — 이 파일은 순수 로직만.
// ============================================================================
(function (root) {
  'use strict';

  const TAG_RE = /\[원문\s*확인됨[^\]]*\]/g;
  const CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
  // 표시는 두 상태(#292, 2026-10-07 Fable 판정 + 운영자 승인 — 종전 세 상태 #176). 읽는 사람은 "믿어라 / 직접 확인해라" 둘 중
  // 하나로 읽는다. 주황 「원문과 다름」은 운영에서 낸 것이 전부 거짓이었고(#280·#284·#286) 진짜 틀린 인용은 회색으로도 잡혀,
  // 회색과 하나로 합쳤다. **안쪽 판정 상태(cite_verdicts[].status — ok/missing/mismatch/unclear …)는 그대로** — 바뀐 것은 글자뿐이다.
  //   ok       → [원문 확인됨: <조문>]                       법령 이름 없는 표시(「[원문 확인됨]」·「동법 제N조」)는 대조한 조문으로 채운다(#286-보론)
  //   missing  → [원문 미확인 — 검색 자료에 <조문> 없음]          AI 기억으로 쓴 것일 수 있으니 직접 확인
  //   mismatch → [원문 미확인 — <조문>와 대조해 판정기가 다르다고 봄(직접 확인): <2차 판정 근거>]
  //              (㉠, 2026-10-09 운영자 결정·사내 35fd1814와 같은 글자 — 종전 「…와 대조해 차이 있음, 직접 확인: …」. 사내 운영 「차이 있음」 13개 중
  //               9개가 맞는 인용이었다 — 차이가 있다고 단정하지 않고 판정기의 판단임을 적는다. 머리말·꼬리 메모·상태값은 그대로)
  //   그 밖(판정 보류·호출 실패·호 구조 못 찾음·대조할 문장 없음) → [원문 미확인 — 자동 대조 못 함, 직접 확인: <조문>]
  //   <조문>은 표시 안 글자가 아니라 **판정기가 실제로 대조한(찾은) 문서·조·항·호**(#286-보론, 운영자 결정 2026-10-07 「X와 대조」) —
  //   모델이 표시 안에 적은 대상이 그것과 다르면(법령·조 번호·별표 번호) 끝에 「(표시: …)」로 남긴다. 대시보드는 머리말
  //   「원문 확인됨」(초록)·「원문 미확인 — 」(회색)만 보고 색을 입히고 사내판 콘솔도 이 머리말을 열쇠로 쓰므로 머리말은 바꾸지 않는다.
  //   옛 머리말(「원문 없음 — 」·「원문과 다름 — 」)은 저장된 옛 답변에만 남는다 — 화면은 둘 다 회색, 재연(tools_cite_replay.js)은 계속 읽는다.
  const TAG_HEAD_UNVERIFIED = '[원문 미확인 — ';
  const TAG_MISSING = TAG_HEAD_UNVERIFIED + '검색 자료에 해당 조문 없음]';
  const TAG_UNCHECKED = TAG_HEAD_UNVERIFIED + '자동 대조 못 함, 직접 확인]';
  const TAG_MISMATCH_HEAD = TAG_HEAD_UNVERIFIED;
  // 검색 자료 밖 조문과 대조해 확인된 표시(#288 ⓒ) — 「[원문 확인됨(검색 자료 밖 조문과 대조): 전기통신사업법 제53조제1항]」. 머리말이 「원문 확인됨」이라
  // 색은 초록 그대로이고, 다시 읽을 때(재검증·재연)는 괄호를 떼고 대상만 읽는다.
  const OUTSIDE_TAG_HEAD = '[원문 확인됨(검색 자료 밖 조문과 대조): ';
  const OUTSIDE_HEAD_RE = /^\s*\(검색 자료 밖[^)]*\)/;
  const TAG_UNVERIFIED = TAG_MISSING;    // 옛 이름 유지(외부 참조 호환)
  const TAG_MISMATCH = TAG_MISMATCH_HEAD + '…]';
  function buildTag(status, reason, cmp, notes) {
    const ns = Array.isArray(notes) ? notes.filter(Boolean) : (notes ? [String(notes)] : []);
    const tail = (ns.length ? ' (' + ns.join(' · ') + ')' : '') + ']';
    const c = String(cmp || '').trim();
    if (status === 'mismatch') {
      const memo = String(reason || '').replace(/\s+/g, ' ').replace(/[\[\]]/g, '').trim().slice(0, 80) || '원문과 다르게 설명됨';
      return TAG_MISMATCH_HEAD + (c ? withWa(c) : '원문과') + ' 대조해 판정기가 다르다고 봄(직접 확인): ' + memo + tail;
    }
    if (status === 'missing') {
      const part = /조문 일부만 검색됨/.test(String(reason || '')) ? '(조문 일부만 검색됨)' : '';
      return (c ? TAG_HEAD_UNVERIFIED + '검색 자료에 ' + c + ' 없음' + part : TAG_MISSING.slice(0, -1)) + tail;
    }
    return TAG_UNCHECKED.slice(0, -1) + (c ? ': ' + c : '') + tail;
  }
  // 「X와 대조」·「X과 대조」 — 끝 글자의 받침(한글 종성, 숫자는 읽는 소리)으로 고른다
  function withWa(label) {
    const s = String(label || '');
    if (!s) return s;
    const ch = s.charAt(s.length - 1), code = ch.charCodeAt(0);
    let batchim = false;
    if (code >= 0xAC00 && code <= 0xD7A3) batchim = (code - 0xAC00) % 28 !== 0;
    else if (/\d/.test(ch)) batchim = '013678'.indexOf(ch) !== -1;
    return s + (batchim ? '과' : '와');
  }
  // 조문 이름표 「전기통신사업법 제19조제3항제3호」 — 판정기가 대조한(찾은) 조문을 표시에 적을 때
  function articleLabel(fam, key, paras, items) {
    let s = (fam ? fam + ' ' : '') + (key ? keyText(key) : '');   // 부칙 열쇠(#290)는 「부칙 제N호 제M조」
    if (paras && paras.length) s += paras.map(function (n) { return '제' + n + '항'; }).join('·');
    if (items && items.length) s += items.map(function (i) { return '제' + String(i).replace(/^(\d+)(의\d+)?$/, '$1호$2'); }).join('·');   // 5의2 → 제5호의2
    return s.trim();
  }
  // 법령 추측의 종류(#286 inherit·claim·any·weak, #288 number)를 읽는 사람에게 적는 머리
  function guessPrefix(how) { return how === 'weak' ? '법령 이름 못 맞춤 → ' : how === 'number' ? '고시 번호로 봄 → ' : '법령 이름 없음 → '; }
  // 판정 결과 하나가 대조한(찾은) 조문 — withGuess면 법령 추측 표기(#286)를 앞에 붙인다. 다중 원문(#288 ⓓ′)이면 대조한 조문을 모두 적는다
  function cmpLabelOf(r, withGuess) {
    const fam = r.lawDoc || (r.doc ? docFamily(r.doc) : '');
    let s;
    if (r.kind === 'annex') s = fam ? ((fam + ' ' + (r.annexType || '별표') + (r.annex ? ' ' + r.annex : '')).trim()) : (r.lookFor || ((r.annexType || '별표') + (r.annex ? ' ' + r.annex : '')));
    else if (r.multi && r.multi.length > 1) s = r.multi.map(function (m) { return articleLabel(m.lawDoc || docFamily(m.doc), m.key, m.paras, m.items); }).join('·');
    else if (r.key && (fam || r.doc)) s = articleLabel(fam, r.key, r.paras, r.items);
    else s = r.lookFor || r.guessLabel || (r.key ? articleLabel('', r.key, r.paras, r.items) : '');
    if (withGuess && r.lawGuess && s) s = guessPrefix(r.lawGuess) + s;
    return s || '';
  }
  // 표시 안에 법령 이름이 적혀 있는가(「동법」·「법」·「시행령 제N조」·번호만은 아니다) — 없으면 초록을 대조한 조문으로 채운다
  function tagNamesLaw(inner) {
    if (!inner || !(/제\s?\d+\s?조|별표|별지|부칙/.test(inner))) return false;
    const tp = parseTagInner(inner);
    return !!(tp && tp.lawInfo && tp.lawInfo.candidates);
  }
  // 모델이 표시 안에 적은 대상이 판정기가 대조한 조문과 다른가(법령·조 번호·별표 번호) — 다르면 「(표시: …)」로 남긴다
  function shownDiffers(tgt, r, fam) {
    if (!tgt || !(/제\s?\d+\s?조|별표|별지|부칙/.test(tgt))) return false;
    const tp = parseTagInner(tgt);
    if (!tp) return false;
    // 다중 원문(#288 ⓓ′): 표시에 적힌 조가 대조한 조문들 가운데 다 있으면 같다
    if (r.multi && r.multi.length > 1 && tp.kind === 'article') return (tp.mentions || []).some(function (x) { return !r.multi.some(function (m) { return m.key === x.key; }); });
    if (!fam) fam = String(r.lookFor || r.guessLabel || '').split(/\s제\d|\s별표|\s별지/)[0].trim();   // 못 찾은 조문은 찾아본 법령으로 견준다
    if (tp.kind === 'annex') return r.kind !== 'annex' || String(tp.annex || '') !== String(r.annex || '');
    // 번호 없이 적은 부칙 표시(「부칙 제2조」)를 자료의 부칙 하나로 푼 것(「부칙제20792호제2조」)은 같은 대상(#290)
    const sameAdd = isAddendumKey(tp.key) && isAddendumKey(r.key) && !parseAddKey(tp.key).unit && parseAddKey(tp.key).art === parseAddKey(r.key).art;
    if (r.key && tp.key && tp.key !== r.key && !sameAdd) return true;
    const li = tp.lawInfo;
    if (li && li.candidates && fam) {
      if (li.title && norm(li.title) === norm(fam)) return false;
      // 「동 가이드라인 제3조」·「같은 고시」의 「동·같은·이」는 이름이 아니다(사내 관찰 ④) — 떼고 견주고, 남은 한 낱말이 문서 이름 끝과 같으면 같은 문서
      return !li.candidates.some(function (c) {
        const bare = c.replace(/^(동|같은|이)\s+/, '');
        return familyMatches(fam, c) || familyMatches(fam, stripTypeTail(c) || '') || familyMatches(fam, bare) || norm(fam).endsWith(norm(bare));
      });
    }
    return false;
  }
  // 인용문 본문 길이(정규화) — 조 번호·괄호 제목·법령명을 뺀 나머지. 24자 미만이면 "번호·제목뿐"으로 본다.
  // 법령 이름은 **조·별표·별지 참조 바로 앞**(표 칸 경계 '|' 하나는 건너뜀)에 있고 줄 머리·구분 기호(| - * : , ( 「 [ .) 뒤에서 시작하는
  // 낱말 묶음만 지운다(Fable 재검토 #240, 2026-09-27). 종전 규칙은 '규정·기준·법'으로 끝나는 낱말 앞 40자를 문장 어디서든 지워
  // 「…재할당받은 경우 임대 가능 등 규정」(33자)이 4자, 「…할당할 수 있다고 규정」이 0자가 되어 충분한 인용문이 '대조할 내용 없음'(회색)이 됐다
  // (사내 실답변 2건). 참조가 뒤따르지 않는 이름은 지우지 않는다 — 내용을 더 세는 쪽이 안전하다(회색이 아니라 판정기로 간다).
  // 낱말 상한 12·줄표(— –) 구분(2026-09-28 PC 과거 답 75건 대조, Fable 재검토 대상): 7낱말 상한은 「주파수할당 신청 절차 및 방법 등 세부사항
  // 고시(…) 제14조」(8낱말) 이름 칸을 인용문으로 남겨 옛 코드가 판정기로 보내던 뒤 칸 조문 내용을 버렸고, 「… — 통신시설 등급 지정·관리 기준 제8조」
  // 소제목 줄도 줄표 뒤 이름을 못 지워 소제목이 인용문이 됐다.
  const LAW_NAME_BEFORE_REF_RE = /(^|[|\-*•:;,.(「『\[>—–])(\s*(?:\*\*)?)((?:[가-힣A-Za-z0-9·ㆍ]+\s+){0,11}?[가-힣A-Za-z0-9·ㆍ]*(?:법률|법|시행령|시행규칙|규칙|고시|규정|기준|세칙|지침)[」』\]]?(?:\*\*)?\s*(?:\([^)]*\))?)(?=\s*\|?\s*(?:제\s?\d+\s?조|\[?별표|\[?별지))/g;
  // 이름 범위만 지운다(S3, 2026-10-10 — 2단계 Fable 판정 §4-7, #294-보론): 위 정규식은 줄 머리·마지막 구분 기호부터 법령명 끝까지(최대 12낱말)를 통째로
  // 이름으로 잡아, 「…요건을 포함하여야 한다고 법 제32조의14제3항이 명시하고 있습니다」·「…알려야 한다고 전기통신사업법 제19조제1항이 정하고 있습니다」처럼
  // **내용이 앞·법령명이 뒤**인 문장(한국어의 흔한 어순)은 내용까지 지웠다(남은 몸통 12자·11자, claimRelevance 낱말 근거 0 → #286 낱말 고르기가 못 돌고
  // 24자 미만이라 「제목 줄」로 읽혀 다음 문단이 인용문이 되는 길). 잡힌 낱말 묶음에서 **법령 이름이 될 수 없는 낱말**(서술어·연결 어미·주제/목적 조사로
  // 끝나는 낱말, 「따라·해당·관련」 같은 가리키는 말) 뒤부터만 이름으로 보고 지운다 — lawNameBefore가 이름으로 읽는 범위(「법」·「동 규정」·「전기통신사업법」·
  // 낫표 제목)와 같고, 「경제적 이익 등 제공의 부당한 이용자 차별행위에 관한 세부기준」 같은 긴 이름은 그런 낱말이 없어 종전대로 통째로 지운다.
  // 대가: 「국가를 당사자로 하는 계약에 관한 법률」처럼 목적 조사·관형 어미가 든 이름은 앞 몇 낱말이 내용으로 남는다(내용을 더 세는 쪽 — 판정기로 간다).
  const NAME_STOP_RE = /^(?:관련|해당|위|상기|본|당해|그|각|따라|따르면|의하면|의하여|의해|의거하여|근거하여|위반하여|이에)$|(?:[한된있없았었였겠이했됐]다|는다|하다|[하되있없이았었였겠다라않]고|[하되있이으]며|면|[여해아어려]야|[하되]여|[어아여해]서|에서|로서|은|는|을|를|에게)$/;
  function lawNameKeep(g) {   // 정규식이 이름으로 잡은 글 g → 남길 앞 글(이름이 될 수 없는 낱말까지)
    const parts = String(g || '').split(/(\s+)/);   // 짝수 칸 = 낱말
    for (let i = parts.length - 3; i >= 0; i -= 2) {
      if (NAME_STOP_RE.test(parts[i].replace(/^[*「『[]+|[*」』\]]+$/g, ''))) return parts.slice(0, i + 2).join('');
    }
    return '';
  }
  function stripLawNames(s) {
    return String(s || '').replace(LAW_NAME_BEFORE_REF_RE, function (all, p1, p2, p3) { return p1 + p2 + lawNameKeep(p3); });
  }
  function stripCiteBody(s) {
    return normQ(stripLawNames(s)
      .replace(/제\s?\d+\s?조(?:\s?의\s?\d+)?(?:\s?\([^)]*\))?/g, ''));
  }
  // closed-before(아래 findCitations ③, 2026-10-09 사내 선행 이식) 줄의 내용 길이 — 조 번호만 뺀다. 위 법령명 지우기는 「- 신청절차·대가 산정·징수는
  // 시행령 제12조」의 앞 낱말 넷까지 법령명으로 보고 지워(내용 7자) 문장으로 닫힌 줄이 「번호·제목뿐」이 됐다. 문장 끝(「…준용합니다.」)으로 닫힌 줄은
  // 제목 줄이 아니므로 낱말을 지우지 않고 센다(사내 strip_ref_body와 같다).
  function stripRefBody(s) {
    return normQ(String(s || '').replace(/제\s?\d+\s?조(?:\s?의\s?\d+)?(?:\s?\([^)]*\))?/g, ''));
  }
  const LAW_SUFFIX_RE = /(법|법률|시행령|시행규칙|규칙|고시|규정|기준|세칙|지침|요령|훈령|예규|협정)$/;
  // 약칭 → 정식 문서명에 들어 있는 문자열 (family가 이 문자열을 포함하면 같은 법령으로 본다)
  const LAW_ALIASES = {
    '정보통신망법': '정보통신망 이용촉진', '망법': '정보통신망 이용촉진',
    '단통법': '이동통신단말장치 유통', '방발기금법': '방송통신발전 기본법', '방송통신발전기본법': '방송통신발전 기본법',
    '사업법': '전기통신사업법', '위치정보법': '위치정보의 보호', '개인정보법': '개인정보 보호법',
    '공정거래법': '독점규제 및 공정거래', '전자상거래법': '전자상거래 등에서의 소비자보호',
  };

  function articleKey(articleNo) {
    const m = String(articleNo || '').match(/^(\d+조(?:의\d+)?)/);
    return m ? m[1] : null;
  }
  function docFamily(docName) { return String(docName || '').split('(')[0].trim(); }
  function norm(s) { return String(s || '').replace(/[\s·ㆍ‧•]/g, ''); }

  // 조각 이어붙이기 — 청크는 앞뒤가 겹치게 잘려 있어(실측 제50조 136→137 조각이 ~90자 겹침)
  // 겹친 부분을 찾아 한 번만 남긴다. 겹침을 못 찾으면 줄바꿈으로 잇는다.
  function mergeChunkTexts(parts) {
    let out = '';
    for (const p of parts) {
      const t = String(p || '');
      if (!t) continue;
      if (!out) { out = t; continue; }
      const max = Math.min(400, out.length, t.length);
      let k = 0;
      for (let n = max; n >= 20; n--) {
        if (out.slice(out.length - n) === t.slice(0, n)) { k = n; break; }
      }
      out += k ? t.slice(k) : '\n' + t;
    }
    return out;
  }

  // ── 부칙 열쇠(#290, 2026-10-07 — Fable 판정 local_docs/자문세문제_판정_261007.md §13-3, Fable 재검토 대상) ──
  // 부칙 조각은 article_no가 「부칙 제20792호(20250318)」·「부칙 제2024-20호(20240523)」(번호가 없으면 「부칙(20240101)」·「부칙 #3」 — law_sync.py)라
  // articleKey가 null이다. 그래서 expandArticles·fetchNamedArticles·역참조·#283 덧붙이기는 부칙을 건너뛰고(그대로 둔다 — §13-3 ⑧), 판정기도 부칙 표시의
  // 원문을 못 찾았다: 「전기통신사업법 부칙 제20792호 제2조」 → 약한 이름 「…부칙 제20792호」 + 본칙 열쇠 「2조」 → 거짓 「원문 없음」, 맨 「부칙 제2조」 →
  // 앞 법령 본칙 제2조(정의)와 대조. 판정기 안에서만 부칙 열쇠를 따로 둔다 — 단위 「부칙제20792호」(고시 「부칙제2024-20호」, 하이픈 번호 그대로) ·
  // 조 「부칙제20792호제2조」 · 번호 없이 적은 「부칙제2조」(자료 안에서 그 법령 부칙이 하나일 때만 푼다).
  function isAddendumKey(key) { return /^부칙/.test(String(key || '')); }
  const ADD_NO_RE = /제\s?(\d{4}\s?[-‐–－]\s?\d{1,4}|\d+)\s?호/;
  function normAddNo(s) { return String(s || '').replace(/\s/g, '').replace(/[‐–－]/, '-'); }
  // 부칙 조각 article_no → { no, date, label(단위 열쇠) } — 부칙이 아니면 null
  function addendumUnitOf(articleNo) {
    const a = String(articleNo || '');
    if (!/^부칙/.test(a)) return null;
    const m = a.match(/^부칙\s*(?:제\s?(\d{4}\s?[-‐–－]\s?\d{1,4}|\d+)\s?호)?\s*(?:\((\d{8})\))?\s*(?:#\s?(\d+))?/) || [];
    const no = m[1] ? normAddNo(m[1]) : null;
    return { no: no, date: m[2] || null, label: no ? '부칙제' + no + '호' : m[3] ? '부칙#' + m[3] : '부칙' + (m[2] ? '(' + m[2] + ')' : '') };
  }
  // 부칙 열쇠 → { unit: 단위 열쇠(번호 없이 적었으면 null), art: '2조'·'2조의2'·null }
  function parseAddKey(key) {
    const m = String(key || '').match(/^(부칙(?:제[\d-]+호|#\d+|\(\d{8}\))?)(?:제(\d+조(?:의\d+)?))?$/);
    if (!m) return { unit: null, art: null };
    return { unit: m[1] === '부칙' ? null : m[1], art: m[2] || null };
  }
  // 열쇠를 사람이 읽는 꼴로 — '2조' → '제2조', '부칙제20792호제2조' → '부칙 제20792호 제2조', '부칙제2조' → '부칙 제2조'
  function keyText(key) {
    if (!isAddendumKey(key)) return '제' + key;
    const p = parseAddKey(key);
    const u = p.unit ? p.unit.replace(/^부칙/, '').replace(/^제/, ' 제').replace(/^#/, ' #') : '';
    return ('부칙' + u + (p.art ? ' 제' + p.art : '')).trim();
  }
  // 부칙 본문의 조 머리 「제M조(」 — 줄머리, 또는 문장 끝(.)·꺾쇠(>) 바로 뒤(고시 부칙은 줄바꿈 없이 「…23.>제1조(시행일) …시행한다.제2조(…」로 잇는다).
  // 번호가 앞 머리보다 커야 머리로 친다(본문 속 「제5조(…)에 따라」 같은 인용을 머리로 읽지 않게). 반환 [{key:'2조', title, start, end}] — end = 다음 머리 앞
  function addendumArticles(text) {
    const s = String(text || ''), out = [];
    const re = /(^|\n|[.>][ \t]*)[ \t]*제\s?(\d+)\s?조(?:\s?의\s?(\d+))?\s*\(/g;
    let m, last = [0, 0];
    while ((m = re.exec(s))) {
      const n = [Number(m[2]), Number(m[3] || 0)];
      if (n[0] < last[0] || (n[0] === last[0] && n[1] <= last[1])) continue;
      last = n;
      const start = s.indexOf('제', m.index + m[1].length);
      const open = m.index + m[0].length - 1, close = s.indexOf(')', open);
      out.push({ key: n[0] + '조' + (n[1] ? '의' + n[1] : ''), title: close > open && close - open < 80 ? s.slice(open + 1, close).trim() : '', start: start, end: s.length });
      if (out.length > 1) out[out.length - 2].end = start;
    }
    return out;
  }
  // 부칙 단위 글에서 그 조(artKey)만 — 조 머리가 하나도 없는 단위(「이 법은 공포한 날부터 시행한다.」 한 문장)는 단위 전체(§13-3 ④),
  // 머리는 있는데 그 조가 없으면 null(자료에 없는 조 — 일부 조각만 들어온 단위도 그렇다). artKey가 없으면(조 없는 「부칙 제N호」, §13-3 ⑥) 단위 전체.
  function addendumSlice(text, artKey) {
    const s = String(text || '');
    if (!artKey) return { text: s, title: '', whole: true };
    const arts = addendumArticles(s);
    if (!arts.length) return { text: s, title: '', whole: true };
    const a = arts.find(function (x) { return x.key === artKey; });
    return a ? { text: s.slice(a.start, a.end).trim(), title: a.title, whole: false } : null;
  }
  // 조 참조 바로 앞이 「부칙」(+ 번호 표기만)인가(§13-3 ⑤) — 「부칙 제2조」·「부칙 제20792호 제2조」·「부칙 <제20792호,2025.3.18> 제2조」·「부칙(제2024-20호) 제2조」·
  // 「부칙 제20792호(20250318) 제2조」. 사이에 다른 말이 있으면 본칙이다(「부칙 제20792호에 따라 등록 간주되므로 제22조제2항」).
  // 반환 { no(번호 또는 null), rest(「부칙」 앞 글 — 법령 이름은 여기서 읽는다, §13-3 ①) } 또는 null
  function addendumBefore(before) {
    let b = String(before || '').replace(/\s+$/, ''), no = null;
    for (let guard = 0; guard < 4; guard++) {
      let mm = b.match(/(?:<[^<>\n]{0,40}>|[(（][^()（）\n]{0,40}[)）])$/);
      if (mm) { const n = mm[0].match(ADD_NO_RE); if (n && !no) no = normAddNo(n[1]); b = b.slice(0, mm.index).replace(/\s+$/, ''); continue; }
      mm = b.match(/제\s?(\d{4}\s?[-‐–－]\s?\d{1,4}|\d+)\s?호$/);
      if (mm) { if (!no) no = normAddNo(mm[1]); b = b.slice(0, mm.index).replace(/\s+$/, ''); continue; }
      break;
    }
    if (!/(^|[^가-힣])부칙$/.test(b)) return null;
    return { no: no, rest: b.slice(0, -2) };
  }
  function addKey(no, art) { return '부칙' + (no ? '제' + no + '호' : '') + (art ? '제' + art : ''); }

  // 1) 인용 조문 통째 보강.
  //   chunks: [{id, doc_name, article_no, chunk_index, content, ...}] (순위순 — 앞쪽이 먼저 보강된다)
  //   fetchArticle(doc_name, key) → 같은 문서·같은 조의 모든 조각 [{id, article_no, chunk_index, content}]
  //   반환: chunks — 같은 조의 첫 원소가 병합 전문을 담고(_full=true) 나머지 원소는 제거됨,
  //         addedIds — 새로 들어온 조각 id(근거 기록용), expanded — 보강된 조 수
  async function expandArticles(chunks, fetchArticle, opts) {
    opts = opts || {};
    const maxArticles = opts.maxArticles != null ? opts.maxArticles : 10;
    const maxPer = opts.maxChunksPerArticle != null ? opts.maxChunksPerArticle : 4;
    let budget = opts.maxAddedChunks != null ? opts.maxAddedChunks : 14;   // 추가 조각 총량(토큰 상한)
    const groups = new Map();
    const order = [];
    (chunks || []).forEach(function (c) {
      const key = articleKey(c && c.article_no);
      if (!key || !c.doc_name) return;
      const gk = c.doc_name + '|' + key;
      if (!groups.has(gk)) { groups.set(gk, { doc: c.doc_name, key: key, members: [] }); order.push(gk); }
      groups.get(gk).members.push(c);
    });
    const full = new Map();
    // 조각 조회는 묶음(wave)으로 동시에 보내고 처리는 순위순으로 한다(B-2, #201, 2026-09-24). 종전에는 조문마다 한 번씩
    // await라 왕복이 줄줄이 더해졌다. 예산·선택 규칙이 순위순으로 그대로 적용되므로 결과는 동일하고, 상한에 걸려
    // 처리하지 않은 묶음 뒤쪽 조회 결과는 버린다(낭비 ≤ wave−1건).
    const wave = opts.fetchConcurrency != null ? opts.fetchConcurrency : 6;
    for (let w0 = 0; w0 < order.length && full.size < maxArticles && budget > 0; w0 += wave) {
      const batch = order.slice(w0, w0 + wave);
      const fetched = await Promise.all(batch.map(function (bk) {
        const bg = groups.get(bk);
        return Promise.resolve().then(function () { return fetchArticle(bg.doc, bg.key); })
          .then(function (r) { return r || []; }, function () { return []; });
      }));
      for (let bi = 0; bi < batch.length; bi++) {
      if (full.size >= maxArticles || budget <= 0) break;
      const gk = batch[bi];
      const g = groups.get(gk);
      let rows = fetched[bi];
      rows = rows.filter(function (r) { return articleKey(r.article_no) === g.key; })
        .sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      if (rows.length <= 1) continue;                     // 한 조각짜리 조문 — 보강할 것이 없다
      const memberIds = new Set(g.members.map(function (m) { return m.id; }));
      let picked = rows.slice(0, maxPer);
      const have = new Set(picked.map(function (r) { return r.id; }));
      // 검색이 실제로 집은 조각은 상한과 무관하게 반드시 포함 (그 조각을 빼면 검색 결과가 사라진다)
      for (const m of g.members) {
        if (typeof m.id === 'number' && !have.has(m.id)) {
          const r = rows.find(function (x) { return x.id === m.id; });
          if (r) { picked.push(r); have.add(r.id); }
        }
      }
      picked.sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      const added = picked.filter(function (r) { return !memberIds.has(r.id); }).length;
      if (added === 0) continue;                          // 이미 전부 검색돼 있었다
      if (added > budget) picked = picked.filter(function (r) { return memberIds.has(r.id); }).concat(
        picked.filter(function (r) { return !memberIds.has(r.id); }).slice(0, budget));
      picked.sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      budget -= picked.filter(function (r) { return !memberIds.has(r.id); }).length;
      // 연속 조각은 겹침 병합, 끊긴 자리는 (중략) 표시
      const runs = [];
      let cur = [], prev = null;
      for (const r of picked) {
        if (prev !== null && (r.chunk_index || 0) !== prev + 1) { runs.push(cur); cur = []; }
        cur.push(r.content || ''); prev = r.chunk_index || 0;
      }
      if (cur.length) runs.push(cur);
      let text = runs.map(mergeChunkTexts).join('\n…(중략)…\n');
      const omitted = rows.length - picked.length;
      if (omitted > 0) text += '\n(※ 이 조문은 전체 ' + rows.length + '조각 중 ' + picked.length + '조각만 실었습니다. 보이지 않는 항·호가 있을 수 있습니다.)';
      full.set(gk, { content: text, ids: picked.map(function (r) { return r.id; }), parts: picked.length, whole: omitted === 0 });
      }
    }
    const out = [], addedIds = [], done = new Set();
    const knownIds = new Set((chunks || []).map(function (c) { return c && c.id; }));
    for (const c of chunks || []) {
      const key = articleKey(c && c.article_no);
      const gk = key && c.doc_name ? c.doc_name + '|' + key : null;
      if (gk && full.has(gk)) {
        if (done.has(gk)) continue;                       // 같은 조의 다른 조각 — 첫 원소에 합쳐졌다
        done.add(gk);
        const f = full.get(gk);
        out.push(Object.assign({}, c, { content: f.content, _full: f.whole, _parts: f.parts }));
        for (const id of f.ids) if (typeof id === 'number' && !knownIds.has(id) && addedIds.indexOf(id) === -1) addedIds.push(id);
      } else out.push(c);
    }
    return { chunks: out, addedIds: addedIds, expanded: full.size };
  }

  // 역참조 발췌(#155-보론4, 운영자 결정 2026-09-11): 검색된 조문 X를 **인용하는** 같은 법령의 다른 조문에서
  // 인용 문장(그 줄)만 잘라 온다 — 제재(제20조 등록취소)·조사(제51조)·준용 조항은 질문 어휘로는 검색되지 않지만
  // "제32조의4제5항에 따른 …"처럼 검색된 조문을 가리키므로 이 경로로 닿는다. AI 요약이 아니라 원문 발췌라 비용 0·오류 0.
  //   chunks: 순위순 조문 청크(정밀검색분 먼저)
  //   fetchCiting(doc_name, key) → 같은 문서에서 content에 '제'+key가 든 조각 [{id, doc_name, article_no, chunk_index, content}]
  //   opts.fetchArticle(doc_name, key) → 그 조문의 모든 조각(제재 조문의 항 머리 문장을 찾는 데 쓴다, 없으면 인용 조각 안에서만 찾는다)
  //   반환 { text: 프롬프트 블록, chunks: 검증용 의사 청크(_excerpt=true), ids: 발췌 원본 조각 id, sanctions: 제재 조문 수 }
  //
  // #230(2026-09-26) 보강 — 96760b6b 자문(대리점·판매점 사이 개인사업자) 재현에서 8칸이 이렇게 쓰였다:
  //  ① 6칸이 **다른 법령** 조문을 가리킨 줄이었다 — 「정보통신망법」…같은 법 제52조, 「벤처투자 촉진에 관한 법률」 제2조를
  //     '제52조·제2조 인용'으로 잡았다(citeRegex는 앞의 법령명을 보지 않는다).
  //  ② 4칸이 정의 조문(제2조) 인용 — 법령 거의 모든 조문이 정의 조문을 가리켜 칸만 먹는다.
  //  ③ 제재 조문은 법령 끝(벌칙 장)에 있어 chunk_index 오름차순·조문당 4칸에서 늘 잘린다 — 제32조의14를 인용하는 조문 6개 중
  //     제104조(과태료)가 6번째, 제50조는 제53조(과징금)·제99조(벌칙)·제104조가 5~9번째. 같은 질문 세 번 모두 제104조 0건.
  //  그래서: 다른 법령 참조 줄은 인용으로 치지 않고, 정의·목적 조문은 대상에서 빼고, 제재 조문(벌칙·과태료·과징금·이행강제금·
  //  양벌·몰수·추징)은 별도 칸(maxSanction)으로 먼저 뽑아 그 호가 속한 항의 머리 문장(금액·형량)까지 붙인다.
  function citeRegex(key) {
    // '32조의4'는 '제32조의40'과, '32조'는 '제32조의4'와 구분한다
    const esc = key.replace(/조의(\d+)$/, '조의$1').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp('제' + esc + (/조의\d+$/.test(key) ? '(?!\\d)' : '(?!의\\d)(?!\\d)'));
  }
  const CITING_SKIP_TITLE_RE = /\((?:정의|목적|용어의\s*정의|용어정의|용어의\s*뜻)\)/;
  // 발췌하지 않는 인용 조문 — 조문 번호만 늘어놓은 목록 조문(규제 재검토 기한·고유식별정보 처리 사무)과 목적 조문.
  // 20문항 재현에서 이런 줄('제29조제9항 … 등록 요건: 2022년 1월 1일')이 칸을 차지했다(#230).
  const CITER_SKIP_TITLE_RE = /\((?:목적|규제의\s*재검토|(?:민감정보\s*및\s*)?고유식별정보의\s*처리)\)/;
  function isSanctionTitle(articleNo) {
    const t = String(articleNo || '');
    return /(벌칙|과태료|과징금|양벌|이행강제금|몰수|추징)/.test(t) && !/벌칙\s*적용/.test(t);   // '벌칙 적용에서 공무원 의제'는 제재가 아니다
  }
  // 같은 대상 안에서 먼저 뽑는 순서 — 위반 자체의 제재(벌칙·과태료·과징금·양벌)가 명령 불이행 강제(이행강제금)·몰수보다 앞.
  // 96760b6b 재현: 제50조를 인용하는 제재 조문은 문서 순서로 제51조의2(자료제출 이행강제금)가 제53조(금지행위 과징금)보다 앞이다.
  function sanctionTier(articleNo) { return /(벌칙|과태료|과징금|양벌)/.test(String(articleNo || '')) ? 0 : 1; }
  // 조문 번호 바로 앞(before)이 다른 법령을 가리키는가 — 「…」 제N조 / 같은 법·동법 제N조 / (시행령·고시 안의) 법·영 제N조 /
  // 「」 없이 적은 법령명(전파법 제10조). 자기 법령은 법령명 없이 '제N조' 또는 '이 법 제N조'로 적는다.
  function isOtherLawRef(before) {
    let b = String(before || '').replace(/\s+$/, '');
    // 나열의 뒷 조문은 나열 머리의 법령을 따른다 — 「법 제89조의2, 제89조의3 및 제90조부터」의 제90조는 법(상위 법률) 조문.
    // 앞의 조·항·호와 이음말(,ㆍ 및 또는 부터 까지)만으로 된 꼬리를 걷어 내고(그 안에 '제N조'가 있을 때만) 나열 머리 앞을 본다.
    const run = b.match(/(?:제\s?\d+\s?(?:조(?:의\s?\d+)?|항|호(?:의\s?\d+)?)|[가-하]목|각\s?호|본문|단서|전단|후단|[,ㆍ·]|및|또는|부터|까지|이나|와|과|\s)+$/);
    if (run && /제\s?\d+\s?조/.test(run[0])) b = b.slice(0, run.index).replace(/\s+$/, '');
    if (/[」』]$/.test(b)) return true;
    // 「위치정보의 보호 및 이용 등에 관한 법률 시행령」(이하 "영"이라 한다) 제3조 — 괄호 하나를 건너 다시 본다
    const pb = b.replace(/\([^()]*\)$/, '').replace(/\s+$/, '');
    if (pb !== b && /[」』]$/.test(pb)) return true;
    const m = b.match(/([가-힣A-Za-z0-9·ㆍ]+)$/);
    if (!m) return false;
    const w = m[1];
    // '법률'도 홀낱말로 본다(Fable 재검토 #230, 2026-09-27) — 낫표 없이 적은 「…등에 관한 법률 제45조」의 마지막 낱말이 두 글자라
    // 아래 '3자 이상' 규칙에 못 미쳐 자기 법령 인용으로 읽혔다. 자기 법령은 이름 없이 '제N조'로 적으므로 '법률'로 끝나는 앞말은 다른 법령이다.
    if (/^(법|영|령|규칙|시행령|시행규칙|고시|규정|동법|동령|법률)$/.test(w))
      return !/(^|[^가-힣])이$/.test(b.slice(0, b.length - w.length).replace(/\s+$/, ''));
    return w.length >= 3 && /(법|법률|시행령|시행규칙|고시|규정|기준|지침)$/.test(w);
  }
  // content에서 key를 **자기 법령으로** 인용한 위치들
  function selfCiteIndexes(content, key) {
    const s = String(content || '');
    const re = new RegExp(citeRegex(key).source, 'g');
    const out = [];
    let m;
    while ((m = re.exec(s)) !== null) if (!isOtherLawRef(s.slice(Math.max(0, m.index - 80), m.index))) out.push(m.index);
    return out;
  }
  function excerptAt(content, at, maxLen) {
    const s = String(content || '');
    let start = s.lastIndexOf('\n', at);
    start = start === -1 ? 0 : start + 1;
    let end = s.indexOf('\n', at);
    if (end === -1) end = s.length;
    let unit = s.slice(start, end).trim();
    if (unit.length > maxLen) {
      const rel = at - start;
      const from = Math.max(0, rel - Math.floor(maxLen / 2));
      unit = (from > 0 ? '…' : '') + unit.slice(from, from + maxLen) + (from + maxLen < unit.length ? '…' : '');
    }
    return unit;
  }
  function excerptAround(content, re, maxLen) {
    const s = String(content || '');
    const m = s.match(re);
    return m ? excerptAt(s, m.index, maxLen) : '';
  }
  // 제재 조문 발췌 — 인용 줄(호)마다 그 줄이 속한 항의 머리 문장을 앞에 둔다. 금액·형량은 머리 문장에 있다
  // (예: 제104조⑤ "다음 각 호의 어느 하나에 해당하는 자에게는 1천만원 이하의 과태료를 부과하고, …" + 4의11. 제32조의14제1항…).
  // 머리 = 인용 줄에서 위로 올라가 처음 만나는 '①~⑳' 줄 또는 '제N조(…) 본문' 줄. 인용 줄 자체가 항이면(제53조① …) 머리는 없다.
  // 길이 상한(maxLen) 안에서 고르는 순서: 순위가 높은 대상(keys 앞쪽)을 인용한 줄 → 그 조문을 '위반'한 자를 적은 줄 → 문서 순서.
  // 제104조처럼 호가 수십 개인 조문에서 질문과 무관한 줄(제50조를 곁가지로 언급한 ①5호)이 칸을 먹지 않게 한다. 표시는 문서 순서.
  function sanctionExcerpt(fullText, keys, maxLen) {
    const lines = String(fullText || '').split('\n');
    const hits = [];
    for (let i = 0; i < lines.length; i++) {
      const L = lines[i];
      let at = -1, rank = -1;
      for (let k = 0; k < keys.length && at < 0; k++) { const ix = selfCiteIndexes(L, keys[k]); if (ix.length) { at = ix[0]; rank = k; } }
      if (at < 0) continue;
      let h = -1;
      for (let j = i; j >= 0; j--) {
        if (/^\s*[①-⑳]/.test(lines[j]) || /^\s*제\d+조(?:의\d+)?\s*\([^)]*\)\s*\S/.test(lines[j])) { h = j; break; }
      }
      hits.push({ i: i, h: h !== i ? h : -1, rank: rank, viol: /위반|하지\s*아니한|거부|금지행위를\s*한/.test(L.slice(at)) ? 0 : 1,
        item: excerptAt(L, at, 220), head: h >= 0 && h !== i ? excerptAt(lines[h], 0, 260) : '' });
    }
    const order = hits.slice().sort(function (a, b) { return a.rank - b.rank || a.viol - b.viol || a.i - b.i; });
    const pickedHeads = new Set(), picked = [];
    let total = 0;
    for (const x of order) {
      const add = (x.head && !pickedHeads.has(x.h) ? x.head.length + 1 : 0) + x.item.length + 1;
      if (total + add > maxLen && picked.length) continue;
      picked.push(x); total += add;
      if (x.head) pickedHeads.add(x.h);
    }
    picked.sort(function (a, b) { return a.i - b.i; });
    const outLines = [];
    let lastHead = null;
    for (const x of picked) {
      if (x.head && x.h !== lastHead) { outLines.push(x.head); lastHead = x.h; }
      outLines.push(x.item);
    }
    const dropped = hits.length - picked.length;
    return outLines.join('\n') + (dropped ? '\n…(이 조문에서 같은 조문을 인용하는 줄 ' + dropped + '개 더 있음)' : '');
  }
  async function buildCitingExcerpts(chunks, fetchCiting, opts) {
    opts = opts || {};
    const maxPer = opts.maxPerArticle != null ? opts.maxPerArticle : 4;
    const maxTotal = opts.maxTotal != null ? opts.maxTotal : 8;
    const maxLen = opts.maxLen != null ? opts.maxLen : 300;
    const maxSanction = opts.maxSanction != null ? opts.maxSanction : 6;
    const maxSanctionPer = opts.maxSanctionPerArticle != null ? opts.maxSanctionPerArticle : 2;
    const sanctionLen = opts.sanctionMaxLen != null ? opts.sanctionMaxLen : 900;
    const fetchArticle = typeof opts.fetchArticle === 'function' ? opts.fetchArticle : null;
    const have = new Set();          // 이미 컨텍스트에 있는 doc|key — 발췌 불필요
    const targets = [];
    for (const c of chunks || []) {
      const k = articleKey(c && c.article_no);
      if (!k || !c.doc_name) continue;
      const gk = c.doc_name + '|' + k;
      if (have.has(gk)) continue;
      have.add(gk);
      if (CITING_SKIP_TITLE_RE.test(String(c.article_no || ''))) continue;   // 정의·목적 조문은 대상에서 뺀다(#230)
      targets.push({ doc: c.doc_name, key: k });
    }
    // 조회는 expandArticles와 같은 묶음(B-2, #201) — 필요한 묶음까지만 받는다(뒤 대상은 상한에 닿으면 조회하지 않는다).
    const wave = opts.fetchConcurrency != null ? opts.fetchConcurrency : 6;
    const fetched = new Array(targets.length);
    async function rowsOf(i) {
      if (fetched[i] === undefined) {
        const w0 = i - (i % wave);
        const batch = targets.slice(w0, w0 + wave);
        const res = await Promise.all(batch.map(function (bt) {
          return Promise.resolve().then(function () { return fetchCiting(bt.doc, bt.key); })
            .then(function (r) { return r || []; }, function () { return []; });
        }));
        res.forEach(function (r, j) {
          fetched[w0 + j] = r.slice().sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
        });
      }
      return fetched[i];
    }
    const citerOk = function (r, t) {
      const rk = articleKey(r.article_no);
      if (!rk || rk === t.key) return null;                                    // 자기 자신
      if (/^(부칙|별표|서식|별지|붙임)/.test(String(r.article_no || '')) || CITER_SKIP_TITLE_RE.test(String(r.article_no || ''))) return null;
      const gk = r.doc_name + '|' + rk;
      if (have.has(gk)) return null;                                           // 이미 실린 조문
      const at = selfCiteIndexes(r.content, t.key);
      return at.length ? { gk: gk, at: at[0] } : null;                         // 다른 법령 조문만 가리키면 인용 아님(#230)
    };
    // ① 제재 조문 — 대상 순위순, 대상당 새 조문 maxSanctionPer개, 전체 maxSanction개. 이미 뽑힌 제재 조문이 다음 대상도
    //    인용하면 칸을 더 쓰지 않고 인용 줄만 합친다(제104조가 제32조의13·제32조의14·제50조를 모두 인용).
    //    대상당 2개: 96760b6b 재현에서 3개면 제52조(시정조치) 하나가 이행강제금·과징금(사업정지 갈음)·벌칙으로 칸을 채워
    //    정작 제50조 위반 과징금(제53조)이 밀려났다.
    const sanc = new Map();           // gk → {doc_name, article_no, key, keys:[], rows:[]}
    for (let i = 0; i < targets.length; i++) {
      if (sanc.size >= maxSanction && fetched[i] === undefined) break;        // 칸이 찼으면 받은 결과 안에서만 합친다
      const t = targets[i];
      const rows = (await rowsOf(i)).filter(function (r) { return isSanctionTitle(r.article_no); })
        .sort(function (a, b) { return sanctionTier(a.article_no) - sanctionTier(b.article_no) || (a.chunk_index || 0) - (b.chunk_index || 0); });
      let n = 0;
      for (const r of rows) {
        const ok = citerOk(r, t);
        if (!ok) continue;
        let e = sanc.get(ok.gk);
        if (!e) {
          if (sanc.size >= maxSanction || n >= maxSanctionPer) continue;
          e = { doc_name: r.doc_name, article_no: r.article_no, key: articleKey(r.article_no), keys: [], rows: [] };
          sanc.set(ok.gk, e); n++;
        }
        if (e.keys.indexOf(t.key) === -1) e.keys.push(t.key);
        if (!e.rows.some(function (x) { return x.id === r.id; })) e.rows.push(r);
      }
    }
    const sList = Array.from(sanc.values());
    const fulls = await Promise.all(sList.map(function (e) {
      if (!fetchArticle) return Promise.resolve(null);
      return Promise.resolve().then(function () { return fetchArticle(e.doc_name, e.key); })
        .then(function (r) { return (r || []).filter(function (x) { return articleKey(x.article_no) === e.key; }); }, function () { return null; });
    }));
    const sOut = [], ids = [];
    sList.forEach(function (e, si) {
      const all = (fulls[si] && fulls[si].length ? fulls[si] : e.rows).slice().sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      const ex = sanctionExcerpt(mergeChunkTexts(all.map(function (x) { return x.content || ''; })), e.keys, sanctionLen);
      if (!ex) return;
      sOut.push({ doc_name: e.doc_name, article_no: e.article_no, cites: e.keys, excerpt: ex });
      // 원본 조각 id — 발췌에 들어간 줄(머리·인용 줄)이 있는 조각만(대시보드 검증이 이 조각들로 원문을 다시 읽는다)
      const exLines = ex.split('\n').map(function (l) { return l.replace(/^…|…$/g, '').slice(0, 40); }).filter(function (l) { return l.length >= 8; });
      for (const x of all) {
        if (typeof x.id !== 'number' || ids.indexOf(x.id) !== -1) continue;
        if (exLines.some(function (l) { return String(x.content || '').indexOf(l) !== -1; })) ids.push(x.id);
      }
    });
    // ② 그 밖의 역참조(조사·준용·시정명령 등) — 종전 규칙 그대로(대상당 maxPer, 전체 maxTotal), 제재 칸에 든 조문은 뺀다
    const out = [], seen = new Set(sanc.keys());
    for (let i = 0; i < targets.length && out.length < maxTotal; i++) {
      const t = targets[i];
      const rows = await rowsOf(i);
      const re = citeRegex(t.key);
      let n = 0;
      for (const r of rows) {
        if (n >= maxPer || out.length >= maxTotal) break;
        const ok = citerOk(r, t);
        if (!ok || seen.has(ok.gk)) continue;                                  // 중복
        const ex = excerptAt(r.content, ok.at, maxLen);
        if (!ex) continue;
        seen.add(ok.gk); n++;
        out.push({ doc_name: r.doc_name, article_no: r.article_no, cites: t.key, excerpt: ex });
        if (typeof r.id === 'number' && ids.indexOf(r.id) === -1) ids.push(r.id);
      }
    }
    if (!out.length && !sOut.length) return { text: '', chunks: [], ids: [], sanctions: 0 };
    let text = '';
    if (sOut.length) text += '\n\n---\n\n[검색된 조문을 위반했을 때의 제재 조문 — 발췌]\n' +
      '아래는 위 조문을 인용하는 같은 법령의 벌칙·과태료·과징금 등 제재 조문에서 **그 조문을 인용한 호와 그 호가 속한 항의 머리 문장(금액·형량)**만 ' +
      '잘라 온 것입니다. 위반 시 제재를 설명할 때는 이 발췌를 근거로 「법령명 제N조제M항제K호」까지 적고, 발췌에 없는 제재·금액을 기억으로 채우지 마세요.\n\n' +
      sOut.map(function (x, i) { return '[제재 ' + (i + 1) + '] ' + x.doc_name + ' 제' + x.article_no + ' — 제' + x.cites.join('·제') + ' 인용\n' + x.excerpt; }).join('\n\n');
    if (out.length) text += '\n\n---\n\n[검색된 조문을 인용하는 다른 조문 — 발췌]\n' +
      '아래는 위 조문을 가리키는 같은 법령의 다른 조문(조사·준용·시정명령 등)에서 **인용 문장만** 잘라 온 것입니다. 전문이 아니므로 ' +
      '이 발췌에 없는 항·호의 내용을 추정하지 마세요. 인용할 때는 「법령명 제N조」와 발췌에 보이는 항·호까지만 적으세요.\n\n' +
      out.map(function (x, i) { return '[역참조 ' + (i + 1) + '] ' + x.doc_name + ' 제' + x.article_no + ' — 제' + x.cites + ' 인용\n' + x.excerpt; }).join('\n\n');
    const pseudo = sOut.concat(out).map(function (x) { return { id: null, doc_name: x.doc_name, article_no: x.article_no, chunk_index: 0, content: x.excerpt, _excerpt: true }; });
    return { text: text, chunks: pseudo, ids: ids, sanctions: sOut.length };
  }

  // 시스템 프롬프트의 「■ 전파법 제16조(재할당) [원문 확인됨] …」 블록 → 의사 청크.
  // 이 조문들은 검색과 무관하게 매 자문에 실리므로, 대조 대상에 넣지 않으면 정당한 인용이 '미확인'이 된다.
  function pseudoChunksFromPrompt(prompt) {
    const out = [];
    const re = /■\s*(.+?)\s+제(\d+)조(?:의(\d+))?[^\n]*\n([\s\S]*?)(?=\n\s*■|$)/g;
    let m;
    const s = String(prompt || '');
    while ((m = re.exec(s))) {
      const head = s.slice(m.index, s.indexOf('\n', m.index));
      out.push({ id: null, doc_name: m[1].trim() + '(시스템 프롬프트 핵심 조문)', article_no: m[2] + '조' + (m[3] ? '의' + m[3] : ''),
        chunk_index: 0, content: head.replace(/^■\s*/, '') + '\n' + m[4].trim() });
    }
    return out;
  }
  const PROMPT_DOC_SUFFIX = '(시스템 프롬프트 핵심 조문)';
  const isPromptDoc = function (docName) { return String(docName || '').slice(-PROMPT_DOC_SUFFIX.length) === PROMPT_DOC_SUFFIX; };

  // 판정 원문이 지침서 글뿐인 조문 → 실DB 조문으로 바꾼다(#284, 2026-10-06 Fable 판정 §4-3 5). 지침서 「핵심 조문」이 원문보다 짧았을 때
  // (전파법 제16조③ 한정어 없음 등) 줄인 글을 옮긴 인용이 그 글과 「일치」해 초록으로 지나갔다 — 운영 69개 중 47개가 지침서 글로 채점됐다.
  // 인용 표시가 가리키는 조(cites의 key·후보 key)만, 검색 자료에 같은 법령군·조의 실제 조문이 없을 때만 받는다(있으면 그 조문이 이미 원문으로
  // 뽑힌다 — checkCitation은 같은 조의 문서 중 가장 긴 글을 고른다). 판 고르기: 지침서 머리줄의 「제N호」(제24조②는 시행예정판 제21553호)가
  // 있으면 그 판, 없으면 현행판(status 'current', 여럿이면 문서명 끝 날짜가 늦은 쪽).
  //   fetchLawArticle(family, key) → [{id, doc_name, article_no, chunk_index, content, status}] (현행·시행예정 판을 함께, 호출측 DB 조회)
  //   → { chunks, swapped: Set('법령군|조'), failed: Set('법령군|조') }
  async function swapPromptArticles(cites, chunks, fetchLawArticle) {
    const swapped = new Set(), failed = new Set();
    const pseudo = (chunks || []).filter(function (c) { return isPromptDoc(c.doc_name); });
    if (!pseudo.length || typeof fetchLawArticle !== 'function') return { chunks: chunks, swapped: swapped, failed: failed };
    const keys = new Set();
    for (const c of cites || []) {
      if (c.key) keys.add(c.key);
      for (const cand of c.candidates || []) if (cand && cand.key) keys.add(cand.key);
    }
    const dateOf = function (n) { const m = String(n || '').match(/\((\d{8})\)\s*$/); return m ? m[1] : ''; };
    const jobs = [], dropReal = new Set();
    for (const p of pseudo) {
      const fam = docFamily(p.doc_name), key = articleKey(p.article_no);
      if (!key || !keys.has(key)) continue;
      const hasReal = (chunks || []).some(function (c) { return !isPromptDoc(c.doc_name) && docFamily(c.doc_name) === fam && articleKey(c.article_no) === key; });
      // 검색 자료에 실제 조문이 있으면 지침서 조각은 뺀다 — checkCitation은 같은 조의 문서 중 **가장 긴 글**을 고르는데, 지침서 조각은
      // 「→ 핵심 기한」 주석 줄까지 붙어 짧은 실제 조문(시행령 제18조)보다 길어 원문으로 뽑혔다(10-06 배포본 확인 — 출처 kept)
      if (hasReal) { dropReal.add(p); continue; }
      const hint = (String(p.content || '').split('\n')[0].match(/제\s?(\d+)호/) || [])[1];
      jobs.push(Promise.resolve().then(function () { return fetchLawArticle(fam, key); }).then(function (rows) {
        const own = (rows || []).filter(function (r) { return r && !isPromptDoc(r.doc_name) && docFamily(r.doc_name) === fam && articleKey(r.article_no) === key && r.content; });
        const docs = [];
        for (const r of own) if (docs.indexOf(r.doc_name) === -1) docs.push(r.doc_name);
        let doc = hint ? docs.find(function (d) { return d.indexOf('(제' + hint + '호)') !== -1; }) : null;
        if (!doc) {
          const cur = docs.filter(function (d) { return own.some(function (r) { return r.doc_name === d && (r.status == null || r.status === 'current'); }); });
          cur.sort(function (a, b) { return dateOf(b).localeCompare(dateOf(a)); });
          doc = hint ? null : cur[0];
        }
        if (!doc) { failed.add(fam + '|' + key); return null; }
        swapped.add(fam + '|' + key);
        return { pseudo: p, rows: own.filter(function (r) { return r.doc_name === doc; }).map(function (r) {
          return { id: r.id, doc_name: r.doc_name, article_no: r.article_no, chunk_index: r.chunk_index, content: r.content };
        }) };
      }, function () { failed.add(fam + '|' + key); return null; }));
    }
    if (!jobs.length && !dropReal.size) return { chunks: chunks, swapped: swapped, failed: failed };
    const got = (await Promise.all(jobs)).filter(Boolean);
    const drop = new Set(got.map(function (g) { return g.pseudo; }).concat(Array.from(dropReal)));
    const out = (chunks || []).filter(function (c) { return !drop.has(c); });
    for (const g of got) for (const r of g.rows) out.push(r);
    return { chunks: out, swapped: swapped, failed: failed };
  }

  // 법령 이름의 일부가 아닌 앞 낱말 — 「규정·고시·기준…」 앞에 오면 이름 칸은 그 종류 낱말뿐(④, 사내 _NOT_NAME_WORD_RE와 같다)
  const NOT_NAME_WORD_RE = /^(?:관련|해당|위|상기|본|당해|그|및|또는|각|따라)$|(?:은|는|을|를|며|에서|으로)$/;
  // 발령 기관 + 고시·훈령·예규·공고 + 제YYYY-N호 (끝에 붙은 것만) — 기관 낱말은 위원회·부·청·처·원·소로 끝나야(「따라 고시」의 「따라」는 아니다)
  const NUMBERED_NOTICE_RE = /((?:[가-힣·ㆍ]*(?:위원회|부|청|처|원|소)\s?)?(?:고시|훈령|예규|공고))\s*제\s?(\d{4})\s?[-‐–－]\s?(\d{1,4})\s?호$/;
  // 인용 직전의 법령명 후보 — "실제로 판례에서 전기통신사업법 제32조의14"에서 뒤에서부터
  // ["전기통신사업법", "판례에서 전기통신사업법", ...] 순으로 돌려주고, 호출측이 문서명과 맞춰 본다.
  // "동법·같은 법·이 법·법 제N조"는 직전 인용의 법령을 이어받는다(inherit).
  function lawNameBefore(before) {
    // 「전기통신사업법」 제50조 — 낫표는 떼고 본다(#240: 종전에는 이름을 못 읽어 '법령 미상'이 되었다)
    let b = String(before || '').replace(/[「」『』]/g, ' ').replace(/\s+$/, '');
    while (/\)$/.test(b)) { const i = b.lastIndexOf('('); if (i < 0) break; b = b.slice(0, i).replace(/\s+$/, ''); }
    // 「방송미디어통신위원회고시 제2026-11호 제1조」 — 고시 번호로 적은 이름(#288 ⓑ). 종전엔 「-」에서 이름을 못 읽어(null) 앞 법령을 이어받았다
    // (c19c247f: 「전기통신사업법 제1조 없음」). 번호는 일괄개정이라 여러 문서가 같이 쓴다(제2026-11호 9문서·제2017-7호 19문서, 10-07 실DB) —
    // resolveLaw가 자료 안에서 그 번호의 문서가 하나일 때만 맞추고, 맞춰도 추측(guessKind 'number')이다.
    const nb = b.match(NUMBERED_NOTICE_RE);
    if (nb) {
      const label = nb[1].replace(/\s+/g, ' ').trim() + ' 제' + nb[2] + '-' + nb[3] + '호';
      return { candidates: [label], text: label, title: label, numbered: true, number: nb[2] + '-' + nb[3] };
    }
    const m = b.match(/([가-힣A-Za-z0-9·ㆍ‧\s]{1,80})$/);
    if (!m) return null;
    const words = m[1].trim().split(/\s+/).filter(Boolean);
    if (!words.length) return null;
    const last = words[words.length - 1];
    const nl = norm(last);
    // level: '법 제N조'는 앞 법령이 시행령이어도 그 모법, '영 제N조'는 시행령(#240 — 종전엔 앞 법령 그 자체였다)
    if (/^(동법|같은법|이법|법)$/.test(nl)) return { inherit: true, level: '법' };
    if (/^(동령|같은영|이영|영)$/.test(nl)) return { inherit: true, level: '시행령' };
    // 「같은 고시 제33조⑤」·「동 기준」·「이 규정」 — 띄어 쓴 꼴도 붙여 쓴 꼴(동고시·이고시)과 같이 이어받기(#288-보론, 사내 관찰 ④, 2026-10-07).
    // 종전엔 마지막 낱말(고시)만 봐서 이름 「같은 고시」로 읽혀 #240 ① 원문 없음이 됐다 — 「같은 법」(마지막 낱말 「법」)은 이어받는데 어긋났다.
    // 가이드라인 등 법령 종류 낱말이 아닌 이름은 넣지 않는다(「동 가이드라인」은 약한 이름 규칙이 맞춘다 — #286-보론2 ④)
    const nl2 = words.length >= 2 && /^(동|같은|이)$/.test(norm(words[words.length - 2])) ? norm(words[words.length - 2]) + nl : nl;
    if (/^(동|같은|이)법률$/.test(nl2)) return { inherit: true, level: '법' };
    // 종류 낱말 하나뿐인 이름(「규정 제10조제2항」·「동 규정 제10조제2항」·「납부방식은 고시 제7조」 — 2026-10-09 사내 선행 이식, 사내 8c8c373c)은 이름이
    // 아니라 이어받기 — 앞에서 이름이 나온 법령 중 문서군 끝 또는 문서명 종류 괄호 끝이 그 낱말인 가장 가까운 것(lawScope·suffixPick, prior는
    // findCitations가 붙인다). 종전엔 「규정」이 이름 후보가 되어 못 맞춰 원문 없음, 「동 규정」은 #288-보론대로 직전 법령(전파법)을 이어받아 원문 없음이었다.
    // 앞 낱말이 조사로 끝나거나(「납부방식은」) 가리키는 말(관련·해당·위·본…)이면 이름 칸은 종류 낱말뿐이다 — 「…에 관한 규정」 같은 이름은 그대로.
    // 「법」·「시행령」 단독은 이 규칙이 아니다(위 inherit 법 단계·아래 subord 그대로).
    if (TYPE_TAIL_RE.test(nl) && (words.length === 1 || nl2 !== nl || NOT_NAME_WORD_RE.test(norm(words[words.length - 2]))))
      return { inherit: true, suffix: nl, text: nl2 !== nl ? words.slice(-2).join(' ') : last };
    if (/^(동|같은|이)(규정|고시|기준|지침|세칙|요령|훈령|예규)$/.test(nl2)) return { inherit: true };
    // 낫표로 감싼 이름(「이동통신용 무선설비 예비전원설비 설치 가이드라인」 제1조)은 법령 종류 낱말로 끝나지 않아도 **문서 제목**이다
    // (2026-10-04 사내 인계) → 약한 후보에 quoted 표지: 못 맞추면 이어받지 않고 원문 없음(lawScope). 낫표 없는 약한 이름은
    // 「이와 관련하여 제50조」 같은 산문과 구별할 수 없어 종전대로 이어받는다.
    const qt = quotedTitleBefore(before);
    if (qt) {
      const tw = qt.split(' ');
      if (!LAW_SUFFIX_RE.test(tw[tw.length - 1])) {
        const qc = tw.length > 6 ? [qt] : [];
        for (let k = Math.min(6, tw.length); k >= 2; k--) qc.push(tw.slice(-k).join(' '));
        if (!qc.length) qc.push(qt);
        return { candidates: qc, text: tw[tw.length - 1], weak: true, quoted: true, title: qt };
      }
    }
    if (!LAW_SUFFIX_RE.test(last)) {
      // 법령 종류 낱말로 끝나지 않는 이름(「주파수할당 신청 절차 및 방법 등 세부사항」 제9조 — 사내 회신, Fable 재검토 #240·#246, 2026-09-27)
      // → **약한 후보**(weak): resolveLaw가 낱말 2개 이상이 문서명에 순서대로 다 있고 끝 낱말까지 같은 문서가 하나일 때만 맞추고,
      // 못 맞추면 lawScope가 이름 없는 것으로 본다(앞 법령 이어받기 — 종전과 같음). 앞 법령을 이어받을 '이름 나온 법령'으로는 치지 않는다.
      const wk = [];
      for (let k = Math.min(6, words.length); k >= 2; k--) wk.push(words.slice(-k).join(' '));
      return wk.length ? { candidates: wk, text: last, weak: true } : null;
    }
    // 「시행령 제42조」「같은 법 시행령 제5조」「및 시행령」 — 앞 낱말이 법령 이름이 아니면 이어받은 법령의 시행령·시행규칙(#240).
    // 종전에는 '시행령'·'법 시행령'이 이름 끝 일치로 검색 자료의 아무 '…법 시행령'에 붙었다.
    if (/^(시행령|시행규칙)$/.test(nl)) {
      const prev = words.length >= 2 ? words[words.length - 2] : '';
      const pn = norm(prev);
      if (!prev || !LAW_SUFFIX_RE.test(prev) || /^(동법|같은법|이법|법|동|같은|이)$/.test(pn) || /^(같은법|이법)$/.test(norm(words.slice(-3, -1).join(''))))
        return { subord: nl };
    }
    const cands = [];
    for (let k = Math.min(6, words.length); k >= 1; k--) cands.push(words.slice(-k).join(' '));
    return { candidates: cands, text: last };
  }
  // 조 참조 바로 앞이 「…」·『…』로 끝나면 그 안의 제목(뒤에 붙은 괄호 「(2023. 5.)」는 건너뜀), 아니면 null
  function quotedTitleBefore(before) {
    let b = String(before || '').replace(/\s+$/, '');
    while (/[)）]$/.test(b)) { const i = Math.max(b.lastIndexOf('('), b.lastIndexOf('（')); if (i < 0) break; b = b.slice(0, i).replace(/\s+$/, ''); }
    const close = b.slice(-1);
    if (close !== '」' && close !== '』') return null;
    const i = b.lastIndexOf(close === '」' ? '「' : '『');
    if (i < 0) return null;
    const t = b.slice(i + 1, -1).replace(/\s+/g, ' ').trim();
    return t || null;
  }
  function familyMatches(family, name) {
    const f = norm(family), n = norm(name);
    if (!f || !n) return false;
    if (f === n) return true;
    // "전기통신사업법" ≠ "전기통신사업법 시행령": 이름에 없는 하위법령 표지가 문서에 있으면 다른 문서
    if (/(시행령|시행규칙)$/.test(f) && !/(시행령|시행규칙)$/.test(n)) return false;
    if (f.endsWith(n)) return true;
    // 약칭은 **법률**의 것이다(Fable 재검토 #240·#246, 2026-09-27): 문서군 본체가 '법·법률'로 끝날 때만 붙인다 — 종전엔 「단통법」이
    // 그 법률 이름을 제목에 담은 고시(「…법률 위반 과징금 부과 세부기준」)에 붙었다(단통법은 폐지돼 현행 문서가 없다, 사내 회신).
    // 「정보통신망법 시행령」처럼 약칭 뒤에 시행령·시행규칙이 붙으면 본체를 약칭으로 맞추고 같은 꼬리의 문서만(종전엔 못 맞춰 '원문 없음').
    const sub = (n.match(/(시행령|시행규칙)$/) || [])[1] || '';
    const alias = LAW_ALIASES[sub ? n.slice(0, -sub.length) : n];
    if (!alias) return false;
    const fb = sub ? (f.endsWith(sub) ? f.slice(0, -sub.length) : '') : f;
    return !!fb && /(법|법률)$/.test(fb) && fb.indexOf(norm(alias)) !== -1;
  }
  // 낱말 하나짜리 일반어는 법령 이름으로 치지 않는다(#240) — 이름 끝 일치로 검색 자료의 아무 '…고시'·'…규정'에 붙었다.
  // 시행령·시행규칙만 적은 것은 lawNameBefore가 {subord}로 따로 돌려준다(앞에 나온 법령의 것, lawScope).
  const GENERIC_LAW_RE = /^(시행령|시행규칙|고시|규정|규칙|기준|지침|세칙|요령|훈령|예규|법률|협정|법령)$/;
  // 후보 목록을 문서군(family 목록)과 맞춰 하나로 확정. 못 맞추면 null — 그 뜻은 lawScope가 정한다.
  // #240에서 '이름을 못 맞추면 원문 없음'이 되었으므로 모델이 이름을 조금 달리 쓴 경우까지 맞춘다:
  //  1) 이름 그대로(끝 일치·약칭)  2) 끝에 덧붙인 종류 낱말을 뗀 이름 — 「…세부사항 고시」 → 문서명 「…세부사항」(dd26eb98 실측)
  //  3) 줄여 쓴 이름 — 낱말 2개 이상이 문서명에 순서대로 다 있고 그런 문서가 하나뿐일 때만(둘 이상이면 못 맞춘 것으로)
  const TYPE_TAIL_RE = /^(고시|규정|규칙|기준|지침|세칙|요령|훈령|예규|협정)$/;   // 시행령·시행규칙은 떼지 않는다(다른 문서다)
  function stripTypeTail(cand) {
    const w = String(cand || '').trim().split(/\s+/);
    return (w.length >= 2 && TYPE_TAIL_RE.test(norm(w[w.length - 1]))) ? w.slice(0, -1).join(' ') : null;
  }
  const isSubDoc = function (s) { return /(시행령|시행규칙)$/.test(norm(s)); };
  // strict(#288 ⓒ): 2) 종류 낱말을 뗀 이름도 맞는 문서가 하나일 때만 — DB 문서명 전체에서 고를 때(자료 안에서는 종전대로 첫 문서)
  // 고시 번호 이름(numbered, #288 ⓑ)은 families.numIndex(번호 → 그 번호를 문서명에 단 문서군, checkCitation이 조각의 doc_name으로 만든다)에서 하나일 때만
  function resolveLaw(nameInfo, families, strict) {
    if (!nameInfo || !nameInfo.candidates) return null;
    if (nameInfo.numbered) {
      const hits = (families && families.numIndex && families.numIndex.get(nameInfo.number)) || [];
      return hits.length === 1 ? hits[0] : null;
    }
    if (nameInfo.weak) {
      // 낫표 제목은 문서명과 글자가 같으면 그 문서(한 낱말 제목 「예비전원가이드라인」도) — 기계 표시가 맞춘 문서명을 낫표로 싣는 경로
      if (nameInfo.quoted) {
        const ex = families.find(function (f) { return norm(f) === norm(nameInfo.title); });
        if (ex) return ex;
      }
      // 약한 이름(법령 종류 낱말로 끝나지 않음): 순서대로 든 낱말 규칙 + 문서명이 후보의 끝 낱말로 끝나야 + 그런 문서가 하나
      const lastW = norm(nameInfo.text);
      for (const cand of nameInfo.candidates) {
        const words = cand.split(/[\s·ㆍ‧•]+/).map(norm).filter(Boolean);
        if (words.length < 2) continue;
        const hits = families.filter(function (f) {
          const nf = norm(f);
          if (!nf.endsWith(lastW) || LAW_SUFFIX_RE.test(nf)) return false;
          let pos = 0;
          for (const w of words) { const i = nf.indexOf(w, pos); if (i < 0) return false; pos = i + w.length; }
          return true;
        });
        if (hits.length === 1) return hits[0];
      }
      return null;
    }
    for (const cand of nameInfo.candidates) {
      if (GENERIC_LAW_RE.test(norm(cand))) continue;
      // 끝 일치가 여러 문서에 걸리면(「기술기준」 → 기술기준으로 끝나는 고시 여럿) 같은 이름이 있을 때만 — 아니면 더 긴/다른 후보로
      const hits = families.filter(function (f) { return familyMatches(f, cand); });
      if (hits.length === 1) return hits[0];
      const exact = hits.find(function (f) { return norm(f) === norm(cand); });
      if (exact) return exact;
    }
    for (const cand of nameInfo.candidates) {
      const s = stripTypeTail(cand);
      if (!s || GENERIC_LAW_RE.test(norm(s))) continue;
      const hits = families.filter(function (f) { return familyMatches(f, s); });
      if (hits.length === 1 || (hits.length && !strict)) return hits[0];
    }
    for (const cand of nameInfo.candidates) {
      // 가운뎃점도 낱말 경계 — 「통신시설 등급 지정·관리 기준」 ↔ 문서명 「주요통신사업자의 통신시설 등급 지정 및 관리 기준」(992c7fb8)
      const words = (stripTypeTail(cand) || cand).split(/[\s·ㆍ‧•]+/).map(norm).filter(Boolean);
      if (words.length < 2) continue;
      const hits = families.filter(function (f) {
        if (isSubDoc(f) && !isSubDoc(cand)) return false;
        const nf = norm(f);
        let pos = 0;
        for (const w of words) { const i = nf.indexOf(w, pos); if (i < 0) return false; pos = i + w.length; }
        return true;
      });
      if (hits.length === 1) return hits[0];
    }
    return null;
  }
  // 종류 낱말 하나뿐인 이름의 이어받기(④, 2026-10-09 사내 선행 이식): 앞에서 이름이 나온 법령(info.prior, 가까운 것부터 — findCitations가 붙인다) 중
  // 검색 자료의 문서군으로 맞춰지고 그 문서군 끝 또는 문서명 종류 괄호(「(과학기술정보통신부고시)」·「(대통령령)」 — families.typeIndex) 끝이 그 낱말인 첫 것.
  // 고시는 문서군이 「…세부사항」처럼 끝나고 종류 괄호가 「…고시」로 끝난다. 못 찾으면 null(lawScope → 원문 없음).
  function suffixFits(fam, sfx, families) {
    if (norm(fam).endsWith(sfx)) return true;
    const ts = families && families.typeIndex ? families.typeIndex.get(fam) : null;
    return !!ts && Array.from(ts).some(function (t) { return norm(t).endsWith(sfx); });
  }
  function suffixPick(info, families) {
    const sfx = info.suffix || '';
    for (const p of info.prior || []) {
      const f = resolveLaw(p, families);
      if (f && suffixFits(f, sfx, families)) return f;
    }
    return null;
  }
  function baseOf(s) { return String(s || '').replace(/\s*(시행령|시행규칙)\s*$/, '').trim(); }
  // 이름 적힌 법령과 같은 계열(법·시행령·시행규칙)의 문서군
  function groupFor(nameInfo, families) {
    if (!nameInfo || !nameInfo.candidates) return [];
    const own = resolveLaw(nameInfo, families);
    if (own) {
      const b = norm(baseOf(own));
      return families.filter(function (f) { return norm(baseOf(f)) === b; });
    }
    for (const cand of nameInfo.candidates) {
      const cb = baseOf(cand);
      if (!cb || GENERIC_LAW_RE.test(norm(cb))) continue;
      const hits = families.filter(function (f) { return familyMatches(baseOf(f), cb); });
      if (hits.length) return hits;
    }
    return [];
  }
  // 인용 하나를 대조할 수 있는 문서군 목록(앞이 우선). null = 법령 미상(어느 문서든, 종전), [] = 대조할 문서 없음(→ 원문 없음).
  // 번호만 같은 다른 법령 조문과 대조하던 오판(#240 — 전기통신사업법 제53조① 표시가 재난안전법 시행령 제50조와 대조돼
  // 맞는 인용이 '원문과 다름'이 되고, 다음 답이 그 표시를 보고 유효 근거를 버렸다)을 막는 규칙:
  //  ① 법령 이름을 적었으면 그 법령만 — 검색 자료에 없으면 원문 없음
  //  ② '동법·같은 법·법'은 이어받은 법령(ctx), '시행령·시행규칙'만 적었으면 이어받은 법령 계열의 시행령·시행규칙
  //  ③ 이름 없이 '제N조'만 있으면 이어받은 법령 → 같은 계열 순. 이어받을 법령이 없을 때만 어느 문서든
  function lawScope(info, ctx, families) {
    if (info && info.suffix) {   // 「규정 제N조」·「동 규정 제N조」 — 앞에서 이름 나온 그 종류의 법령, 없으면 원문 없음(④)
      const f = suffixPick(info, families);
      return f ? [f] : [];
    }
    if (info && info.inherit) {
      const level = info.level;
      info = ctx; ctx = null;
      if (level && info && info.candidates) {
        const grp = groupFor(info, families);
        const own = resolveLaw(info, families);
        if (level === '법') {
          const acts = grp.filter(function (f) { return !isSubDoc(f); });
          if (acts.length) return acts;
          if (own && isSubDoc(own)) return [];   // 앞 법령은 시행령인데 그 모법은 검색 자료에 없다
        } else {
          return grp.filter(function (f) { return /시행령$/.test(norm(f)); });
        }
      }
    }
    if (info && info.subord) {   // '시행령 제N조'·'같은 법 시행령' — 이어받은 법령 계열의 시행령·시행규칙
      const pool = ctx && ctx.candidates ? groupFor(ctx, families) : families;
      return pool.filter(function (f) { return norm(f).endsWith(info.subord); });
    }
    if (info && info.candidates) {
      const hit = resolveLaw(info, families);
      if (hit) return [hit];
      if (!info.weak) return [];   // 못 맞추면 원문 없음 — '관련 고시 제5조'처럼 막연한 이름도 아무 고시에 붙이지 않는다
      // 낫표 제목(quoted)도 못 맞추면 원문 없음 — 이어받으면 검색 자료의 다른 고시 제1조와 대조돼 거짓 '원문과 다름'이 났다(2026-10-04 사내 인계)
      if (info.quoted) return [];
      // 낫표 없는 약한 이름은 못 맞추면 이름이 없는 것과 같다 — 아래 이어받기 규칙으로(종전 동작)
    }
    if (!ctx || !ctx.candidates) return null;
    const own = resolveLaw(ctx, families);
    const out = own ? [own] : [];
    for (const f of groupFor(ctx, families)) if (out.indexOf(f) === -1) out.push(f);
    return out;
  }

  const ANNEX_RE = /별표\s*제?\s*(\d+(?:\s*의\s*\d+)?)|별지\s*(?:제\s*)?(\d+)\s*(?:호)?(?:\s*의\s*(\d+))?/;
  // 번호 없는 별표 — 별표가 하나뿐인 법령·고시는 원문이 「[별 표]」이고 적재 이름표는 「별표(제목)」(옛 적재는 「별표 ?(제목)」).
  // 꼬리표 안에서만 읽는다(인용문 본문의 「별표에 따른」 같은 말은 대상이 아니다). 뒤에 괄호·쉼표·끝이 와야 한다 — 「별표 3」·「별표에」는 아님
  const ANNEX_BARE_RE = /(?:\[\s*)?별\s*표(?:\s*\?)?\s*\]?\s*(?=[(（,，]|$)/;
  // 별표 공식 제목의 「(제8조관련)」「(제95조제1항 관련)」 → '8조' — 번호 없는 별표 꼬리표를 자료의 별표와 맞출 때 쓴다
  const ANNEX_REL_RE = /제\s?(\d+)\s?조(?:\s?의\s?(\d+))?(?:\s?제\s?\d+\s?항)?(?:\s?제\s?\d+\s?호)?\s*관\s*련/;
  function annexRelOf(s) { const m = String(s || '').match(ANNEX_REL_RE); return m ? m[1] + '조' + (m[2] ? '의' + m[2] : '') : null; }
  // 꼬리표 안(「[원문 확인됨: …]」의 …)의 대상 읽기 — 인용문 파싱(parseSegment)과 달리 별표·별지가 첫 조 언급보다 앞이면
  // 별표·별지가 대상이다. 별표 공식 제목의 괄호 「별표 12(제95조제1항 관련)」의 조 번호는 대상이 아니다(청크 article_no가
  // 이 꼴이라 모델이 제목째 옮긴다 — 종전엔 제95조로 읽혀 법령 이름까지 잃고, 별표가 자료에 있어도 '원문 없음'. 2026-09-27 사내 인계)
  // 번호 없는 별표 「집적정보 통신시설 보호지침 별표(제8조관련)」도 같다(2026-09-29 37d2d5c3 — 종전엔 ANNEX_RE가 숫자를 요구해
  // 제목 괄호의 제8조가 대상이 되고 법령 이름도 못 읽어 앞 꼬리표의 등급기준 고시를 이어받았다 → 자료에 있던 별표가 '원문 없음')
  function parseTagInner(inner) {
    const s = String(inner || '');
    const cm = s.match(/제\s?\d+\s?조/);
    let am = s.match(ANNEX_RE), bare = false;
    if (!am) { am = s.match(ANNEX_BARE_RE); bare = !!am; }
    if (am && (!cm || am.index < cm.index)) {
      const r = parseSegment(s.slice(0, am.index + am[0].length) + ' ', { bareAnnex: bare });
      if (r.kind === 'annex' && !r.annex) r.annexRel = annexRelOf(s.slice(am.index));
      return r;
    }
    return parseSegment(s + ' ', { addendumUnit: true });   // 조 없는 「부칙 제N호」 표시도 대상(#290 ⑥)
  }

  // 표시 하나의 앞 문단에서 인용 대상을 읽는다.
  // 반환 mentions = 등장 순서의 조 언급 목록(조마다 항·호·앞 법령명). key/paras/items/lawInfo는 첫 언급(primary) —
  // 실제 대상 선택은 checkCitation이 "컨텍스트에 있고 인용문과 가장 많이 겹치는 후보"로 한다(#155-보론3: 조문을 통째로
  // 인용하면 그 안의 교차참조(제52조·제53조)가 먼저 잡혀 정작 인용 대상(앞 줄 제목의 제50조)을 놓쳤다).
  function parseSegment(segment, opts) {
    const s = String(segment || '').replace(/\*\*/g, '');
    const artRe = /제\s?(\d+)\s?조(?:\s?의\s?(\d+))?/g;
    const raw = [];
    let a;
    while ((a = artRe.exec(s))) raw.push({ idx: a.index, end: a.index + a[0].length, key: a[1] + '조' + (a[2] ? '의' + a[2] : '') });
    if (!raw.length) {
      // 별표·별지(서식) — 앞의 법령 이름도 읽는다(#240: 존재 확인을 그 법령의 별표로 좁힌다). 「시행령 [별표 4]」의 '['는 떼고 본다
      // 번호 없는 별표(annex '')는 꼬리표 안(parseTagInner → opts.bareAnnex)에서만
      const bm = s.match(ANNEX_RE) || (opts && opts.bareAnnex ? s.match(ANNEX_BARE_RE) : null);
      if (!bm) {
        // 조 없이 「부칙 제20792호」만 적은 표시(#290, §13-3 ⑥) — 꼬리표 안(parseTagInner → opts.addendumUnit)에서만. 단위 전체와 대조한다
        const um = opts && opts.addendumUnit ? s.match(/(^|[^가-힣])부칙\s*(?:[<(（]\s*(?:법률|대통령령|[가-힣]*령|[가-힣]*고시)?\s*)?제\s?(\d{4}\s?[-‐–－]\s?\d{1,4}|\d+)\s?호/) : null;
        if (!um) return { kind: 'none' };
        const ukey = addKey(normAddNo(um[2]), null);
        const urec = { key: ukey, idx: um.index + um[1].length, paras: [], items: [], lawInfo: lawNameBefore(s.slice(0, um.index + um[1].length)), ctxLaw: null, addendum: { no: normAddNo(um[2]), art: null } };
        return { kind: 'article', key: ukey, paras: [], items: [], lawInfo: urec.lawInfo, mentions: [urec] };
      }
      const lawInfo = lawNameBefore(s.slice(0, bm.index).replace(/[\s\[【「『<(]+$/, ' '));
      if (bm[1] === undefined && bm[2] === undefined) return { kind: 'annex', annexType: '별표', annex: '', lawInfo: lawInfo };
      if (bm[1]) return { kind: 'annex', annexType: '별표', annex: bm[1].replace(/\s+/g, ''), lawInfo: lawInfo };
      return { kind: 'annex', annexType: '별지', annex: bm[2] + (bm[3] ? '의' + bm[3] : ''), lawInfo: lawInfo };
    }
    const byKey = new Map();
    const mentions = [];
    let lastNamed = null;   // 이 글에서 앞서 이름이 나온 법령 — 이름 없는 '제N조'·'동법'·'시행령'이 이어받는다(#240)
    for (let i = 0; i < raw.length; i++) {
      const m = raw[i];
      // 조 참조 바로 앞이 「부칙」(+번호)이면 부칙 조(#290, §13-3 ①⑤) — 열쇠 「부칙제N호제M조」, 법령 이름은 「부칙」 앞 글에서 읽는다
      // (「동법 부칙 제2조」·「같은 법 부칙 제2조」·「영 부칙 제2조」가 이어받기를 탄다)
      const ad = addendumBefore(s.slice(0, m.idx));
      const key = ad ? addKey(ad.no, m.key) : m.key;
      let rec = byKey.get(key);
      if (!rec) {
        rec = { key: key, idx: m.idx, paras: [], items: [], lawInfo: lawNameBefore(ad ? ad.rest : s.slice(0, m.idx)), ctxLaw: lastNamed };
        if (ad) rec.addendum = { no: ad.no, art: m.key };
        byKey.set(key, rec); mentions.push(rec);
        if (rec.lawInfo && rec.lawInfo.candidates && !rec.lawInfo.weak) lastNamed = rec.lawInfo;
      }
      const stop = i + 1 < raw.length ? raw[i + 1].idx : s.length;
      let tail = s.slice(m.end, stop);
      // 다음 참조가 부칙 조면 그 「부칙 제N호」 번호를 이 조의 호로 읽지 않는다(#290 — 「제22조의11·부칙 제97호 제2조」)
      const bi = tail.search(/(^|[^가-힣])부칙/);
      if (bi !== -1 && i + 1 < raw.length && addendumBefore(s.slice(0, raw[i + 1].idx))) tail = tail.slice(0, bi);
      let pm;
      const pRe = /제\s?(\d+)\s?항/g;
      while ((pm = pRe.exec(tail))) if (rec.paras.indexOf(+pm[1]) === -1) rec.paras.push(+pm[1]);
      // 원문자 항 표기(제5조①)는 조 바로 뒤에 붙은 것만 — 답변 본문의 ①②③ 나열과 섞이지 않게
      const cm = tail.match(/^\s*(?:\([^)]*\))?\s*([①-⑳])/);
      if (cm) { const n = CIRCLED.indexOf(cm[1]) + 1; if (rec.paras.indexOf(n) === -1) rec.paras.push(n); }
      const iRe = /(?:제\s?)?(\d+)\s?호(?:\s?의\s?(\d+))?/g;
      while ((pm = iRe.exec(tail))) {
        // 법령 번호는 호가 아니다(사내 관찰 ②, #286-보론2): 「(법률 제21553호)」·「고시 제2026-11호」 — 종류 낱말 뒤의 「제N호」, 「-」 뒤의 숫자, 4자리 이상 번호는 건너뛴다.
        // 지침서 핵심 조문 머리줄 「전파법 제24조제2항 — … 법률 제21553호 …」을 모델이 표시에 옮기면 제21553호가 「원문 없음(조문 일부만 검색됨)」이 됐다.
        const head = tail.slice(0, pm.index);
        if (pm[1].length >= 4 || /\d-\s*$/.test(head) || /(법률|대통령령|총리령|부령|[가-힣]+령|고시|훈령|예규|규칙|공고|지침)\s*$/.test(head)) continue;
        const it = pm[1] + (pm[2] ? '의' + pm[2] : '');
        if (rec.items.indexOf(it) === -1) rec.items.push(it);
      }
    }
    const p = mentions[0];
    return { kind: 'article', key: p.key, paras: p.paras, items: p.items, lawInfo: p.lawInfo, mentions: mentions };
  }

  // 인용문(답변 문장)이 원문 텍스트와 얼마나 그대로 겹치는가 — 0~1. 공백·가운뎃점·따옴표·괄호를 뗀 뒤
  // 18자 창을 8자씩 밀며 원문에 있는지 센다. 통째 인용은 ≈1, 바꿔 쓴 설명은 ≈0.
  function normQ(s) {
    return String(s || '').replace(/\*\*/g, '').replace(/\[[^\]]*\]/g, '')
      .replace(/[\s·ㆍ‧•'"“”‘’「」『』()（）\[\],.:;、。…\-—–|]/g, '');   // '|'(표 칸 경계)도 내용이 아니다(Fable 재검토 2026-09-27)
  }
  function quoteOverlap(claim, text) {
    const a = normQ(claim), b = normQ(text);
    if (a.length < 12 || !b) return 0;
    const W = 18, S = 8;
    let hits = 0, n = 0;
    if (a.length <= W) return b.indexOf(a) !== -1 ? 1 : 0;
    for (let i = 0; i + W <= a.length; i += S) { n++; if (b.indexOf(a.slice(i, i + W)) !== -1) hits++; }
    return n ? hits / n : 0;
  }
  // 0.85 (2026-09-14, #169-보론5). 종전 0.6은 18자 조각의 40%가 원문에 없어도 '원문 그대로'로
  // 보고 Haiku 판정을 건너뛰었다 — 실측: '1년 이내'→'2년 이내', 주체 '장관'→'방미통위'가 0.75다.
  // 그 구간(0.6~0.85)이 가장 위험하다: 뼈대는 원문인데 수치·주체 한 곳이 바뀐 문장이 여기 떨어진다.
  const VERBATIM_MIN = 0.85;
  // 1등과 2등 겹침이 이만큼도 차이 나지 않으면 어느 조문인지 단정하지 않는다.
  // 같은 문언이 두 조문에 있을 때 겹침 최대값은 동전 던지기가 된다(#169-보론4 실측).
  const AMBIG_MARGIN = 0.08;   // 이 이상 겹치면 "원문 그대로 인용" — 번호 파싱 없이 확인됨, Haiku 판정 생략

  // ── 법령 이름 없는 참조의 법령 추측(#286, 2026-10-07) ──
  // guessKind: 이 참조의 법령을 어떻게 정했나 — 'none' 이름을 적어 못 박음(맞췄든 못 맞췄든, 낫표 제목 포함 — #240 ①대로 그 법령만) /
  //   'inherit' 이름 없음(맨 「제N조」)·「법/영/동법」(inherit)·「시행령 제N조」(subord) → 이어받기로 추측한 것, 인용문 낱말로 바꿔 고를 수 있다 /
  //   'weak' 낫표 없는 약한 이름을 못 맞춰 lawScope가 이어받은 것 → 이름을 적긴 했으므로 다른 법령으로 바꾸지는 않고(「…고시 제2026-11호 제1조」가
  //   낱말 겹치는 다른 고시의 목적 조문에 붙는다), 추측이라 「불일치」 회색 규칙(ⓒ)만 받는다.
  //   'number' 고시 번호로 고른 문서(#288 ⓑ) — 같은 번호의 다른 일괄개정 고시(자료 밖)를 뜻했을 수 있어 「불일치」는 늘 회색, 바꿔 고르지도 않는다.
  function guessKind(info, families) {
    if (!info || !info.candidates) return 'inherit';
    if (info.inherit || info.subord) return 'inherit';
    if (info.numbered) return 'number';
    return (info.weak && !info.quoted && !resolveLaw(info, families)) ? 'weak' : 'none';
  }
  function isGuessedRef(info, families) { return guessKind(info, families) !== 'none'; }
  // 목적·정의 조문은 어느 법령이나 비슷한 낱말이라 인용문 낱말 근거로 다른 법령의 것으로 바꿔 고르지 않는다(1조는 제목이 없어도 목적으로 본다)
  function isBoilerplateArticle(articleNo, key) { return key === '1조' || /\((목적|정의|용어의\s*정의|적용\s*범위)\)/.test(String(articleNo || '')); }
  // claimRelevance: 인용문의 내용 낱말(법령명·조 번호·흔한 법령 어구를 뺀 2자 이상 낱말)이 조문 원문에 몇 개 드는가. 조사는 어간이 3자 이상
  //   남을 때만 1~2자 뗀다(이용자에게 → 이용자; 「이용자」를 「이용」으로 줄여 「이용계약」에 맞추지 않게), 조사로 끝나는 2자(장은·자는)는 세지 않는다.
  //   quoteOverlap(18자 창)은 바꿔 쓴 인용에 0이라 법령을 가르지 못한다 — 표 행 「폐업 예정일 60일 전까지 서류 제출」은 전기통신사업법 제19조에
  //   6/8, 전파법 제19조에 1/8(38abd528). 숫자만 남는 조각(60일 → 60)은 세지 않는다. 문턱(2낱말·20%)은 그 답변의 표 7행과 #240 반례로 맞춘 값 — 바꾸면 재연.
  const REL_STOP_RE = /^(경우|또는|이하|이상|이내|이전|따라|따른|바에|정하는|정한|대통령령|대통령령으로|과학기술정보통신부장관|과학기술정보통신부장관에게|과학기술정보통신부장관은|장관|규정|조항|내용|사항|하여야|한다|있다|없다|때에는|밖에|해당|관련|다음|각호|어느|하나에|해당하는|위하여|대하여|관하여|필요한|경우에는|가능|여부|기준|방법|절차|대한|의한|관한|있는|없는|하는|되는|하고|하며|받아야|받은|하거나|포함|제외|이를|그에|이에|대해|통해|위해|등을|등의|등에|경우로|경우에|때|및|등|수|것|그|이|로서|로써)$/;
  const REL_PARTICLE_RE = /[은는이가을를의에로와과도만]$/;
  function claimRelevance(claim, text) {
    const nt = normQ(text);
    const body = stripLawNames(String(claim || '').replace(/\[[^\]]*\]/g, ' ').replace(/\*\*/g, ' '))   // 이름 범위만 지운다(S3)
      .replace(/제\s?\d+\s?조(?:\s?의\s?\d+)?(?:\s?\([^)]*\))?/g, ' ')
      .replace(/제\s?\d+\s?[항호](?:\s?의\s?\d+)?/g, ' ').replace(/[①-⑳]/g, ' ');
    const seen = {}; let n = 0, hits = 0;
    for (const raw of body.split(/[^가-힣A-Za-z0-9]+/)) {
      const t = raw.trim();
      if (t.length < 2 || /^\d+$/.test(t) || REL_STOP_RE.test(t) || seen[t]) continue;
      if (t.length === 2 && REL_PARTICLE_RE.test(t)) continue;
      seen[t] = true; n++;
      let hit = false;
      for (let k = 0; k <= 2 && !hit; k++) {
        const s = t.slice(0, t.length - k);
        if (k > 0 && (s.length < 3 || /^\d+$/.test(s) || !/[가-힣]/.test(t.charAt(t.length - k)))) break;   // 조사(한글)만, 어간 3자 이상
        if (nt.indexOf(s) !== -1) hit = true;
      }
      if (hit) hits++;
    }
    return { n: n, hits: hits, score: n ? hits / n : 0 };
  }
  const REL_MIN_HITS = 2, REL_MIN_SCORE = 0.2;
  function relEvidence(x) { return !!x && x.hits >= REL_MIN_HITS && x.score >= REL_MIN_SCORE; }
  // 「…제19조로」·「…제1항으로」·「전기통신사업법으로」·「전파법 시행령으로」 — 끝 글자 받침(ㄹ 받침은 「로」)으로 조사를 고른다
  function withRo(label) {
    const s = String(label || '');
    const code = s.charCodeAt(s.length - 1);
    if (!(code >= 0xAC00 && code <= 0xD7A3)) return s + '로';
    const jong = (code - 0xAC00) % 28;
    return s + (jong === 0 || jong === 8 ? '로' : '으로');
  }

  // 줄 머리의 표 행·목록 항목 표시 — [1] 들여쓰기, [2] '|' · 글머리(-·*·•) · 번호(1. 1))
  const SIBLING_RE = /^([ \t]*)(\||[-*•](?=\s)|\d+[.)](?=\s))/;
  // 인용문 최소 길이(정규화 글자 수) — 이보다 짧으면 '번호·제목뿐'(noclaim). 표 행·형제 목록 항목은 12(위 sibling 설명).
  const MIN_CLAIM = 24;
  const MIN_CLAIM_SIBLING = 12;

  // 답변에서 표시를 전부 찾아 각 표시의 인용 대상을 붙인다
  // 답 안에서 이름이 나온 법령의 자리 — [{pos, info}], 조 참조 바로 앞 이름(앞 120자)과 낫표 제목. 「규정·고시」 이어받기(④)의 재료
  function namedLawsIn(text) {
    const out = [];
    const art = /제\s?(\d+)\s?조(?:\s?의\s?(\d+))?/g, qre = /[「『]([^」』\n]{2,80})[」』]/g;
    let m;
    while ((m = art.exec(text))) {
      const li = lawNameBefore(text.slice(Math.max(0, m.index - 120), m.index).replace(/\*\*/g, ''));
      if (li && li.candidates) out.push({ pos: m.index, info: li });
    }
    while ((m = qre.exec(text))) {
      const li = lawNameBefore(m[0] + ' ');
      if (li && li.candidates) out.push({ pos: m.index, info: li });
    }
    out.sort(function (a, b) { return a.pos - b.pos; });
    return out;
  }
  // closed-before(③): 「…를 준용합니다. [표시]」 — 표시 앞이 문장 끝(마침표 필수)이고 안내문이 아니면 그 줄이 인용문의 전부
  const SENT_END_RE = /(?:다|요|음|됨)\.$/;
  const GUIDE_END_RE = /(?:다음과\s*같|아래와\s*같|다음\s*각\s*호|정리하면|살펴보면|이하\s*참조)[^.\n]{0,16}\.$/;

  function findCitations(answer) {
    const text = String(answer || '');
    const cites = [];
    let m, prevEnd = 0, lastLaw = null;
    let namedAt = null;   // 「규정·고시」 이어받기가 있을 때만 센다(④)
    TAG_RE.lastIndex = 0;
    while ((m = TAG_RE.exec(text))) {
      const tagStart = m.index, tagEnd = m.index + m[0].length;
      // 범위는 좁은 것부터: 같은 줄(불릿 한 항목) → 같은 문단 → 직전 표시 이후 1,200자.
      // 불릿 목록은 줄마다 다른 조문이라, 문단 전체로 잡으면 앞 불릿의 조문이 '첫 인용'으로 잡힌다
      // (실측: 「- 제52조의3제2항: …」 다음 줄의 업무처리규정 제11조 표시가 제52조의3로 읽혔다).
      const li = text.lastIndexOf('\n', tagStart - 1);
      const lineStart = li === -1 ? 0 : li + 1;
      const pi = text.lastIndexOf('\n\n', tagStart);
      const paraStart = pi === -1 ? 0 : pi + 2;
      const floor = Math.max(prevEnd, tagStart - 1200);
      const starts = [Math.max(prevEnd, lineStart), Math.max(prevEnd, paraStart), floor]
        .filter(function (v, i, a) { return a.indexOf(v) === i; });
      let segStart = starts[0], parsed = parseSegment(text.slice(segStart, tagStart));
      for (let k = 1; k < starts.length && parsed.kind === 'none'; k++) {
        segStart = starts[k]; parsed = parseSegment(text.slice(segStart, tagStart));
      }
      // 후보 조문은 **앞의 비어 있지 않은 줄 2개**까지 더 본다(직전 표시 이후로 한정) — 「## 금지행위(제50조)」 제목이나
      // 「업무처리규정 제11조는 다음과 같이 규정합니다.」 다음 줄에 조문을 통째로 옮기는 답변 형식 때문. 인용문(segment)은 넓히지 않는다.
      let extStart = segStart, linesBack = 0;
      while (linesBack < 2 && extStart > prevEnd) {
        const j = text.lastIndexOf('\n', extStart - 2);        // 직전 줄의 시작(-1이면 문서 첫 줄)
        const start = Math.max(prevEnd, j === -1 ? 0 : j + 1);
        if (text.slice(start, extStart).trim()) linesBack++;    // 빈 줄은 세지 않는다
        extStart = start;
      }
      extStart = Math.max(prevEnd, extStart, tagStart - 1600);
      // 표시 뒤 문단(다음 표시·빈 줄·900자까지) — 꼬리표를 제목 줄에 붙이고 내용은 그 아래에 쓰는 답변 형식
      // (「**② 전기통신사업법 제32조의14(…) [원문 확인됨]**\n① 대리점은 …」)에서 인용문은 뒤에 있다(#155-보론5).
      const nextTag = (function () { TAG_RE.lastIndex = tagEnd; const nm = TAG_RE.exec(text); TAG_RE.lastIndex = tagEnd; return nm ? nm.index : text.length; })();
      const blank = text.indexOf('\n\n', tagEnd + 1);
      let after = text.slice(tagEnd, Math.min(nextTag, blank === -1 ? text.length : blank + 1, tagEnd + 900));
      // 표 행·목록 항목의 표시는 그 줄이 인용문이다 — 뒤 문단은 다음 행·다음 항목(형제)이라 인용문이 아니다. 행 본문이 짧으면
      // (24자 미만) 위 '제목 줄' 규칙이 다음 행을 인용문으로 가져가, 「| 제5항 | … [원문 확인됨: 전파법 제16조제5항] |」가 ⑥ 행 내용과
      // 제5항이 대조돼 '원문과 다름 — 제5항이 아닌 제6항 내용'이 됐다(2026-09-27 사내 반례). 표 행은 늘, 목록은 다음 줄이 같은 들여쓰기의
      // 같은 꼴 항목일 때만 이 줄로 끊는다(들여 쓴 내용이 이어지는 「- **제32조의14** [원문 확인됨]」 제목형 항목은 종전대로).
      const lineHead = text.slice(lineStart, tagStart).match(SIBLING_RE);
      let sibling = false;
      if (lineHead) {
        const eol = after.indexOf('\n');
        const rest = eol === -1 ? after : after.slice(0, eol);
        const nextLine = eol === -1 ? '' : (after.slice(eol + 1).split('\n').find(function (l) { return l.trim(); }) || '');
        const nextHead = nextLine.match(SIBLING_RE);
        const kind = function (h) { return h[2] === '|' ? '|' : /\d/.test(h[2]) ? '1' : '-'; };
        if (kind(lineHead) === '|' || (nextHead && kind(nextHead) === kind(lineHead) && nextHead[1].length === lineHead[1].length)) { after = rest; sibling = true; }
      }
      // 표시가 문장·구절·표 칸을 닫는 자리면(closed, 2026-10-05) 표시 뒤는 다음 문장·다음 칸이다 — 인용문은 표시 앞뿐.
      //  ① 표시 바로 뒤가 마침표·쉼표·쌍반점·빗금 ② 그 줄 나머지에 표 칸 경계 '|'(모델이 빈 줄로 끊은 표 행 포함 — 그 줄 나머지만).
      // c19c247f: 「…제99조제3호에 따라 **3억원 이하 벌금**에 처해질 수 있습니다[표시].\n- 제50조제1항 위반(금지행위) 시: …시정조치(제52조제1항) 및」 —
      // 앞 문장이 이름·번호를 빼면 22자라 '제목 줄'(#155-보론5)로 읽혀 다음 글머리가 인용문이 됐고, 판정기가 「제52조제1항을 언급하나 원문 제99조는
      // 벌칙만」으로 거짓 '원문과 다름'을 냈다. 과거 자문 61건·표시 225개 재연: 바뀐 표시 3개(모두 바로잡힘), 제목 줄 정상 꼴은 그대로.
      let closed = false, closedBefore = false;
      if (!sibling) {
        const eol0 = after.indexOf('\n');
        const rest0 = eol0 === -1 ? after : after.slice(0, eol0);
        if (/^[ \t*]*[.,;/。]/.test(after)) { after = ''; closed = true; }
        else if (rest0.indexOf('|') !== -1) { after = rest0; closed = true; }
        else {
          // ③ closed-before(2026-10-09 사내 선행 이식, 사내 8c8c373c): 표시 **앞** 글이 문장 끝(「다.」「요.」「음.」「됨.」, 마침표 필수)으로 닫히고
          // 내용(조 번호만 뺀 길이, stripRefBody)이 12자 이상이며 안내문(「다음과 같」·「아래와 같」·「다음 각 호」·「정리하면」·「살펴보면」·「이하 참조」로
          // 끝나는 문장 — 그 아래가 내용)이 아니면 그 줄이 인용문의 전부다. 사내 10/6: 「- 신청절차·대가 산정·징수는 시행령 제12조 및 제14조를 준용합니다. [표시]」의
          // 내용이 24자 미만이라 '제목 줄'(#155-보론5)로 읽혀 다음 문단(만료 1년 전 통지 이야기)이 인용문이 됐고, 판정기가 거짓 「원문에 없는 1년 전 사전통지」를 냈다.
          // 외부 재연(준비자료 §2)도 같은 꼴이었다. 이 표시는 #176 토막 규칙(앞 문단 가져오기)을 타지 않는다.
          const own = text.slice(starts[0], tagStart);   // 그 줄(직전 표시 뒤부터) — 아래 line과 같은 범위
          const pre = own.replace(/[\s*]+$/, '');
          if (SENT_END_RE.test(pre) && !GUIDE_END_RE.test(pre) && stripRefBody(own).length >= MIN_CLAIM_SIBLING) { after = ''; closed = true; closedBefore = true; }
        }
      }
      // line = 표시가 있는 줄만(조 번호가 없어 segment가 앞 문단으로 넓어졌어도 겹침 판정은 이 줄로도 본다)
      // sibling = 표 행·형제 목록 항목(#240-보론2): 그 줄이 인용문의 전부다 — 토막 문단 규칙(#176)으로 앞 문단을 가져오지 않고(표 앞 안내
      // 문장이 인용문이 되던 구멍, Fable 재검토 2026-09-27) 짧아도 12자부터 판정기로 보낸다(checkCitation MIN_CLAIM_SIBLING).
      // closed = 표시가 문장·칸을 닫음 — 최소 길이는 sibling과 같은 12자(그 앞이 인용문의 전부라는 같은 이유)
      const c = Object.assign({ tagStart: tagStart, tagEnd: tagEnd, tag: m[0], segment: text.slice(segStart, tagStart), line: text.slice(starts[0], tagStart), after: after, sibling: sibling, closed: closed }, parsed);
      if (closedBefore) c.closedBefore = true;
      // 표시가 있는 줄 자체에 적힌 조(#288 ⓓ′ 다중 원문의 후보 — 「| … | 법 제19조①, 영 제24조① [표시]」)
      const lineParsed = parseSegment(c.line);
      c.lineKeys = lineParsed.kind === 'article' ? lineParsed.mentions.map(function (x) { return x.key; }) : [];
      // 꼬리표 안에 대상이 적힌 형식(#155-보론6, 2026-09-11 운영자 결정): 「[원문 확인됨: 전기통신사업법 제32조의14제1항]」
      // 「[원문 확인됨: 전파법 시행령 별표 3]」 — 있으면 앞뒤 문장 추측 없이 이것이 1순위 후보. 옛 형식(「[원문 확인됨]」,
      // 「[원문 확인됨, 참조4]」)은 종전대로 앞뒤에서 추측한다.
      const inner = m[0].slice(1, -1).replace(/^원문\s*확인됨/, '').replace(OUTSIDE_HEAD_RE, '').replace(/^[\s:：—\-–,]+/, '').trim();
      // 인용문(과 앞 줄)에서 마지막으로 이름이 나온 법령 — 표시 대상이 이름 없이 '제N조'·'별표 N'만 적혔을 때 이어받는다
      const segNamed = (parsed.mentions || []).filter(function (x) { return x.lawInfo && x.lawInfo.candidates && !x.lawInfo.weak; });
      const segLaw = segNamed.length ? segNamed[segNamed.length - 1].lawInfo : (parsed.kind === 'annex' && parsed.lawInfo && parsed.lawInfo.candidates ? parsed.lawInfo : null);
      const tp = (inner && (/제\s?\d+\s?조|별표\s*제?\s*\d+|별지\s*(?:제\s*)?\d+|부칙\s*[<(（]?\s*(?:법률\s*)?제\s?\d/.test(inner) || ANNEX_BARE_RE.test(inner))) ? parseTagInner(inner) : null;
      if (tp && tp.kind === 'annex') {
        // 표시에 별표·별지가 적혀 있으면 그것이 대상 — 앞 문장의 조 번호(「법 제50조제1항제5호 및 시행령 [별표 4]」의 제50조)로
        // 넘어가지 않는다(#240: 「[원문 확인됨: 전기통신사업법 시행령 별표 4]」가 법 제50조와 대조돼 맞는 인용이 '원문과 다름')
        c.tagTarget = { key: null, annex: tp.annex, fromTag: true };
        Object.assign(c, { kind: 'annex', annexType: tp.annexType, annex: tp.annex, annexRel: tp.annexRel || null, lawInfo: tp.lawInfo, key: null, paras: [], items: [], mentions: [], candidates: null });
        c.ctxLaw = segLaw || lastLaw;
      } else if (tp && tp.kind === 'article') {
        c.tagTarget = Object.assign({}, tp.mentions[0], { fromTag: true });
        c.tagTargets = tp.mentions.map(function (x) { return Object.assign({}, x, { fromTag: true }); });
        if (c.kind !== 'article') Object.assign(c, { kind: 'article', key: tp.key, paras: tp.paras, items: tp.items, lawInfo: tp.lawInfo, mentions: [] });
      } else if (c.kind === 'annex') {
        c.ctxLaw = lastLaw;
      }
      if (c.kind === 'article') {
        if (c.lawInfo && c.lawInfo.candidates && !c.lawInfo.weak) c.lawText = c.lawInfo.text;
        // 후보 = 인용문 안의 조 + 앞 줄에만 있는 조(뒤에 붙임 — 겹침이 같으면 인용문 안의 조가 우선)
        const inSeg = new Set(c.mentions.map(function (x) { return x.key; }));
        const ext = extStart < segStart ? parseSegment(text.slice(extStart, tagStart)) : null;
        c.candidates = c.mentions.slice();
        if (ext && ext.kind === 'article') {
          for (const x of ext.mentions) if (!inSeg.has(x.key)) c.candidates.push(Object.assign({}, x, { extOnly: true }));
        }
        // 이름 없는 조·'동법'은 같은 글에서 앞서 이름이 나온 법령, 없으면 직전 인용의 법령을 이어받는다(lawScope)
        for (const x of c.candidates) x.ctxLaw = x.ctxLaw || lastLaw;
        if (c.tagTarget) {
          // 표시에 대상이 적혀 있으면 **그 대상만** 대조한다(#240). 종전에는 인용문 속 조 번호도 후보로 두어, 적힌 대상
          // (전기통신사업법 제53조)이 검색 자료에 없으면 인용한 조문 안의 교차참조(「제50조제1항을 위반한…」)로 넘어가
          // 번호만 같은 다른 법령 조문과 대조했다 — 있어야 할 결과는 '원문 없음'이다.
          const byKey = new Map(c.candidates.map(function (x) { return [x.key, x]; }));
          c.candidates = c.tagTargets.map(function (t) {
            if (!t.ctxLaw) {
              const s = byKey.get(t.key);
              t.ctxLaw = s ? ((s.lawInfo && s.lawInfo.candidates && !s.lawInfo.weak) ? s.lawInfo : s.ctxLaw) : (segLaw || lastLaw);
            }
            return t;
          });
          c.key = c.tagTarget.key; c.paras = c.tagTarget.paras; c.items = c.tagTarget.items;
          // 낫표 제목(quoted)은 그 제목이 법령명 — 인용문 속 다른 이름(「…에 관한 규정 제10조」의 '규정')이 기록에 남지 않게
          if (c.tagTarget.lawInfo && c.tagTarget.lawInfo.candidates) {
            c.lawInfo = c.tagTarget.lawInfo;
            if (!c.tagTarget.lawInfo.weak) c.lawText = c.tagTarget.lawInfo.text;
            else if (c.tagTarget.lawInfo.quoted) c.lawText = c.tagTarget.lawInfo.title;
          }
        }
      } else if (c.kind === 'none' && extStart < segStart) {
        // 인용문에 조 번호가 없어도 앞 줄에 있으면 그것이 대상 (「제11조는 다음과 같이 규정합니다.」 + 원문 줄)
        const ext = parseSegment(text.slice(extStart, tagStart));
        if (ext.kind === 'article') {
          Object.assign(c, ext, { kind: 'article' });
          c.candidates = ext.mentions.map(function (x) { return Object.assign({}, x, { extOnly: true }); });
          for (const x of c.candidates) x.ctxLaw = x.ctxLaw || lastLaw;
        }
      }
      // 토막 문단 표시(#176, 2026-09-20): 모델이 인용문을 한 문단에 쓰고 표시는 다음 문단의 토막("고 하면서,"·
      // "을 열거하고 있습니다.")에 붙이는 습관이 있다. 9/17 대시보드 답변의 '확인 안 됨' 5건이 전부 이 오탐이었다 —
      // 토막을 인용문으로 잡거나(내용 없음) 표시 뒤 문단(다음 절)을 인용문으로 잡았다(엉뚱한 불일치).
      // 규칙: 꼬리표에만 대상이 있고(줄 자체에 조 번호 없음) 그 줄의 본문이 24자 미만이면, **앞으로** 거슬러 올라가
      // 본문이 있는 첫 문단(최대 3개, 직전 표시 경계를 넘어도 됨)을 인용문으로 쓴다. 그 문단에 같은 조의 표시가
      // 이미 있으면(직전 인용문의 자동 확인 등) 이 표시는 중복이라 지운다. 제목 줄 표시(#155-보론5)는 줄에 조 번호가
      // 있어 여기 걸리지 않고 종전대로 뒤 문단을 본다. 표시가 문장·칸을 닫았으면(closed) 뒤 문단은 인용문이 아니므로 줄에 조 번호가 있어도
      // 본문이 12자 미만이면 이 규칙을 탄다(8a3a167a: 인용 문단 뒤 표 칸 「 (제53조) [표시] |」 — 직전 인용 문단의 같은 조 표시와 중복).
      // closed-before(문장으로 닫힌 줄, ③)는 그 줄이 인용문의 전부라 앞 문단으로 가지 않는다.
      if (c.tagTarget && !c.sibling && !c.closedBefore && (c.closed ? stripCiteBody(c.line).length < MIN_CLAIM_SIBLING
        : !(parsed.mentions && parsed.mentions.length) && stripCiteBody(c.line).length < 24)) {
        let pEnd = text.lastIndexOf('\n\n', tagStart), looked = 0;
        while (pEnd > 0 && looked < 3) {
          const pStart = text.lastIndexOf('\n\n', pEnd - 1);
          const para = text.slice(pStart === -1 ? 0 : pStart + 2, pEnd);
          // ⚠️ TAG_RE(전역 정규식)를 여기서 쓰면 lastIndex가 0으로 초기화돼 바깥 while이 처음부터 다시 돌며 무한 루프가 된다
          const body = para.replace(/\[원문\s*확인됨[^\]]*\]/g, '');
          if (stripCiteBody(body).length >= 24) {
            c.claimOverride = body;
            const prevKeys = [];
            const kre = /\[원문\s*확인됨[^\]]*?제\s*(\d+조(?:의\d+)?)/g;
            let km;
            while ((km = kre.exec(para)) !== null) prevKeys.push(km[1]);
            if (prevKeys.indexOf(c.tagTarget.key) !== -1) c.dupOfPrev = true;
            break;
          }
          if (para.trim()) looked++;
          pEnd = pStart;
        }
      }
      // 대상 없는 토막 표시(#288 ⓐ, Fable 판정 §4·§11-8·§12-5): 따옴표 인용 문단 다음 문단의 토막(「 등 금지행위와 연계될 소지가 있습니다[원문 확인됨]」·
      // 「고 규정합니다[원문 확인됨]」)에 붙은 대상 없는 표시는 꼬리표에도 줄에도 조 번호가 없어 위 #176 규칙(꼬리표에 대상이 있을 때만)에 안 걸리고
      // '인용 조문을 읽지 못함'(회색)이 됐다(3d984052 c08·c10 — 둘 다 바로 앞 인용 문단에 이름 적은 표시가 이미 있었다).
      // 표시 앞 문단 글이 24자 미만이면 **바로 앞 문단 하나**만 본다(세 문단까지 보면 c08 앞의 제2조제28호·제50조①이 섞인다): 거기 「[원문 확인됨…]」이
      // 있으면 이 표시는 중복이라 지우고(dup), 없으면 그 문단의 조 언급을 후보로·그 문단을 인용문으로 대조한다(조 언급이 없으면 종전대로 못 읽음).
      // 숫자가 든 토막(「과태료는 3천만원입니다[표시]」)은 건드리지 않는다 — 지우면 회색 경고가 아무 표시 없는 문장이 된다(§12-5).
      if (c.kind === 'none' && !tp && !c.sibling && m[0].indexOf(QUOTE_MARK) === -1 && pi !== -1) {
        const frag = text.slice(paraStart, tagStart);
        if (stripCiteBody(frag).length < MIN_CLAIM && !/\d/.test(frag.replace(/\[[^\]]*\]/g, ''))) {
          let pEnd = pi, prevPara = '';
          while (pEnd > 0) {
            const pStart = text.lastIndexOf('\n\n', pEnd - 1);
            const para = text.slice(pStart === -1 ? 0 : pStart + 2, pEnd);
            if (para.trim()) { prevPara = para; break; }
            if (pStart === -1) break;
            pEnd = pStart;
          }
          // ⚠️ TAG_RE(전역)를 여기서 쓰지 않는다 — lastIndex가 바뀌면 바깥 while이 처음부터 다시 돈다(위 #176과 같은 이유)
          const prevTag = prevPara.match(/\[원문\s*확인됨[^\]]*\]/);
          if (prevTag) {
            c.dupOfPrev = true;
            const km = prevPara.match(/\[원문\s*확인됨[^\]]*?제\s*(\d+조(?:의\d+)?)/);
            c.dupKey = km ? km[1] : null;
          } else if (prevPara && !/\[(학습 데이터 기반|요약 문서 기반|근거 조문 미확인)[^\]]*\]/.test(prevPara)) {
            const pp = parseSegment(prevPara);
            if (pp.kind === 'article' && stripCiteBody(prevPara).length >= MIN_CLAIM) {
              Object.assign(c, pp, { kind: 'article', claimOverride: prevPara, fragOf: true });
              c.candidates = pp.mentions.map(function (x) { return Object.assign({}, x); });
              for (const x of c.candidates) x.ctxLaw = x.ctxLaw || lastLaw;
              if (c.lawInfo && c.lawInfo.candidates && !c.lawInfo.weak) c.lawText = c.lawInfo.text;
            }
          }
        }
      }
      // 기계가 붙인 인용 대조 표시(#230)는 그 인용 문단(문장 안 따옴표 인용이면 따옴표 속)만 인용문으로 본다 — 인용 줄에 조 번호가 없으면
      // segment가 앞 문단들로 넓어져 모델의 해설까지 판정기에 넘어갔다(96760b6b 모의: 제50조 인용문에 앞 절의 장려금 해설이 섞임)
      if (m[0].indexOf(QUOTE_MARK) !== -1) {
        const pre = text.slice(Math.max(prevEnd, paraStart), tagStart).replace(/\s+$/, '');
        const qm = pre.match(/["“]([^"”\n]{25,})["”]$/);   // 문장 안 따옴표 인용이면 따옴표 속만
        c.claimOverride = qm ? qm[1] : pre;
      }
      // 「규정·고시」 이어받기(④): 그 참조보다 앞에서 이름이 나온 법령을 가까운 것부터 붙인다 — 고르기는 검색 자료의 문서명과 맞춰 보는 checkCitation(lawScope)
      const sfxInfos = (c.candidates || []).concat(c.tagTargets || [], [c]).map(function (x) { return x && x.lawInfo; }).filter(function (li) { return li && li.suffix; });
      if (sfxInfos.length) {
        if (!namedAt) namedAt = namedLawsIn(text);
        const prior = namedAt.filter(function (x) { return x.pos < tagStart; }).reverse().map(function (x) { return x.info; });
        for (const li of sfxInfos) li.prior = prior;
      }
      cites.push(c);
      prevEnd = tagEnd;
      if (c.kind === 'article' && c.lawInfo && c.lawInfo.candidates && !c.lawInfo.weak) lastLaw = c.lawInfo;
    }
    return cites;
  }

  // 2) 인용 하나를 검색 원문과 대조
  function checkCitation(cite, chunks, annexSources) {
    if (cite.kind === 'none') return { status: 'unparsed', reason: '인용 조문을 읽지 못함' };
    const families = [];
    const numIndex = new Map();   // 고시 번호 → 그 번호를 문서명에 단 문서군(#288 ⓑ — docFamily는 「(」 앞만 남겨 번호가 없다)
    const typeIndex = new Map();  // 문서군 → 문서명 종류 괄호(「대통령령」·「과학기술정보통신부고시」 — 「규정·고시」 이어받기 ④)
    for (const c of chunks || []) {
      const f = docFamily(c.doc_name);
      if (f && families.indexOf(f) === -1) families.push(f);
      const nm = String(c.doc_name || '').match(/\(제(\d{4}-\d+)호\)/);
      if (f && nm) { const a = numIndex.get(nm[1]) || []; if (a.indexOf(f) === -1) a.push(f); numIndex.set(nm[1], a); }
      const tm = String(c.doc_name || '').match(/^[^(]+\(([^)]+)\)/);
      if (f && tm) { if (!typeIndex.has(f)) typeIndex.set(f, new Set()); typeIndex.get(f).add(tm[1]); }
    }
    families.numIndex = numIndex;
    families.typeIndex = typeIndex;
    if (cite.kind === 'annex') {
      // 별표·별지는 있는지만 본다(판정기에 보내지 않음). 법령 이름이 있으면 그 법령의 것만(#240 — 종전엔 아무 법령의
      // 같은 번호 별표가 있어도 확인됨이었다). 별표 출처 문자열은 「<법령> 별표 4」「<법령> 별표 4 머리」 꼴
      const label = cite.annexType || '별표';
      const want = norm(label + (cite.annex || ''));
      // 옛 적재의 번호 없는 별표 이름표 「별표 ?(…)」의 '?'는 번호 자리표시 — 떼면 번호 없는 별표 「별표」(2026-09-29)
      const keyOf = function (s) { return norm(s).replace(/머리$/, '').replace(/\?$/, ''); };
      const pool = [];
      for (const s of annexSources || []) {
        const t = String(s), i = t.search(/별표|별지/);
        if (i >= 0) pool.push({ fam: t.slice(0, i).trim(), key: keyOf(t.slice(i)), rel: null });
      }
      for (const c of chunks || []) {
        const an = String(c.article_no || '');
        pool.push({ fam: docFamily(c.doc_name), key: keyOf(an.split('(')[0]), rel: /^(별표|별지)/.test(an) ? annexRelOf(an) : null });
      }
      const fams = families.slice();
      fams.numIndex = numIndex; fams.typeIndex = typeIndex;
      for (const p of pool) if (p.fam && fams.indexOf(p.fam) === -1) fams.push(p.fam);
      const scope = lawScope(cite.lawInfo, cite.ctxLaw, fams);
      const inScope = function (p) { return !scope || scope.indexOf(p.fam) !== -1; };
      // 번호 없는 별표는 그 법령의 번호 없는 별표, 없으면 꼬리표의 「(제N조관련)」이 같은 그 법령의 별표(모델이 번호를 빠뜨린 경우)
      const hit = pool.find(function (p) { return p.key === want && inScope(p); }) ||
        (!cite.annex && cite.annexRel ? pool.find(function (p) { return p.rel === cite.annexRel && p.key.indexOf(label) === 0 && inScope(p); }) : null);
      const lawLabel = (scope && scope[0]) || (cite.lawInfo && (cite.lawInfo.title || cite.lawInfo.text)) || '';
      return hit ? { status: 'ok', kind: 'annex', lawDoc: hit.fam || null }
        : { status: 'missing', reason: (lawLabel ? lawLabel + ' ' : '') + label + (cite.annex ? ' ' + cite.annex : '') + ' 원문 없음', lawDoc: (scope && scope[0]) || null,
            lookFor: ((lawLabel ? lawLabel + ' ' : '') + label + (cite.annex ? ' ' + cite.annex : '')).trim() };
    }
    // 문서·조별 정본 텍스트 (같은 조가 현행·시행예정 두 판으로 있을 수 있어 문서별로 묶는다)
    const articleText = new Map();   // doc_name|key → merged text
    for (const c of chunks || []) {
      const k = articleKey(c.article_no);
      if (!k) continue;
      const gk = c.doc_name + '|' + k;
      if (!articleText.has(gk)) articleText.set(gk, []);
      articleText.get(gk).push(c);
    }
    // 부칙(#290, §13-3): 단위(doc_name|「부칙제N호」)마다 조각을 chunk_index 순으로 잇고 「제M조(」 머리로 잘라 조 열쇠 「부칙제N호제M조」의 글을 만든다.
    // addText = doc_name|부칙 열쇠 → 글(조마다 + 단위 전체). famAddUnits = 법령군 → 자료 안 부칙 단위 열쇠들(번호 없이 적은 「부칙 제M조」 풀기, §13-3 ③)
    const addUnits = new Map(), famAddUnits = new Map(), addText = new Map(), addVerbatim = [];
    for (const c of chunks || []) {
      const u = addendumUnitOf(c.article_no);
      if (!u) continue;
      const gk = c.doc_name + '|' + u.label;
      if (!addUnits.has(gk)) addUnits.set(gk, { doc: c.doc_name, label: u.label, rows: [] });
      addUnits.get(gk).rows.push(c);
      const f = docFamily(c.doc_name);
      if (!famAddUnits.has(f)) famAddUnits.set(f, new Set());
      famAddUnits.get(f).add(u.label);
    }
    addUnits.forEach(function (u) {
      u.text = mergeChunkTexts(u.rows.slice().sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); }).map(function (c) { return c.content || ''; }));
      addendumArticles(u.text).forEach(function (a) {
        const gk = u.doc + '|' + u.label + '제' + a.key;
        addText.set(gk, u.text.slice(a.start, a.end).trim());
        // 「원문 그대로」 대조 후보는 부칙 조만, 「다른 법률의 개정」 조는 빼고 — 그 조는 본칙 문구를 「…」을 「…」으로 옮겨 적어 본칙 인용과 겹친다
        if (!/다른\s*법(?:률|령)의\s*개정/.test(a.title)) addVerbatim.push(gk);
      });
      addText.set(u.doc + '|' + u.label, u.text);
    });
    // 부칙 열쇠 하나가 자료에서 가리키는 글 — [{doc, key(번호를 푼 열쇠), text}]. 번호 없이 적었으면 그 법령군의 자료 안 부칙 단위가 하나일 때만
    const addendumHits = function (key) {
      const p = parseAddKey(key), out = [];
      addUnits.forEach(function (u) {
        if (p.unit ? u.label !== p.unit : famAddUnits.get(docFamily(u.doc)).size !== 1) return;
        const sl = addendumSlice(u.text, p.art);
        if (!sl) return;
        const rk = u.label + (p.art ? '제' + p.art : '');
        addText.set(u.doc + '|' + rk, sl.text);
        out.push({ doc: u.doc, key: rk, text: sl.text });
      });
      return out;
    };
    const mergedOf = function (gk) {
      if (addText.has(gk)) return addText.get(gk);
      const list = articleText.get(gk).slice().sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      return mergeChunkTexts(list.map(function (c) { return c.content || ''; }));
    };
    // 인용문: 표시 앞 문장. 앞이 제목·조 번호뿐(내용 40자 미만)이면 표시 뒤 문단이 인용문이다(#155-보론5).
    // 토막 문단 표시면 앞 문단(claimOverride, #176)이 인용문이다
    // 표 행·형제 목록 항목(sibling)은 그 줄만 — segment는 줄에 조 번호가 없으면 표 머리·앞 문단까지 넓어진다
    const before = cite.claimOverride || (cite.sibling ? cite.line : cite.segment) || '';
    // 내용 길이 = 조 번호·괄호 제목·법령명을 뺀 나머지(정규화 24자 미만이면 "제목·번호뿐"). 표 행·형제 목록 항목(sibling, #240-보론2)은
    // 한 줄이 인용문의 전부라 12자부터 판정기로 보낸다(Fable 재검토 2026-09-27) — 「| 제5항 | 재할당 시 … 조건을 붙일 수 있음 |」(22자)이
    // 24자 규칙으로는 '대조할 내용 없음'(회색)이 되어 맞는 인용도 직접 확인하라고 나갔다. 판정기 기준의 '번호·제목만 → 판단불가'가 짧은 줄을 받친다.
    const minClaim = (cite.sibling || cite.closed) ? MIN_CLAIM_SIBLING : MIN_CLAIM;   // closed(표시가 문장·칸을 닫음)도 그 앞이 인용문의 전부
    const stripCite = stripCiteBody;
    // closed-before(문장으로 닫힌 줄, ③)는 조 번호만 뺀 길이로 센다(stripRefBody — 법령명 지우기가 앞 낱말까지 지운다)
    const beforeBody = (cite.closedBefore && !cite.claimOverride) ? stripRefBody(before) : stripCite(before);
    const headingOnly = beforeBody.length < minClaim && normQ(cite.after || '').length >= 24;
    const claim = headingOnly ? cite.after : before;

    // 후보 조문과 각 후보가 대조될 수 있는 문서군(lawScope — 이름 적은 법령만 / 이어받은 법령 계열만, #240)
    const candidates = (cite.candidates && cite.candidates.length) ? cite.candidates : [{ key: cite.key, paras: cite.paras || [], items: cite.items || [], lawInfo: cite.lawInfo, ctxLaw: cite.ctxLaw }];
    const scopes = candidates.map(function (cand) { return lawScope(cand.lawInfo, cand.ctxLaw, families); });

    // ① 원문 그대로 인용이면 번호 파싱과 무관하게 확인됨 — 어느 조문(별표 포함)의 텍스트와 겹치는지 본다.
    //    (통째 인용 안의 교차참조가 엉뚱한 조를 가리켜 '미확인'이 되던 오판 방지, #155-보론3). 앞·뒤 중 큰 쪽.
    //    표시에 적힌 대상과 다른 조문이어도 확인됨(#155-보론6 '꼬리표 오기 교정') — 글자 그대로 일치는 거짓 '원문과 다름'을
    //    만들지 않으므로 #240의 대상 제한은 ②(번호로 고르는 경로)에만 건다.
    //    앞 줄(before·line)은 이름·번호·제목을 뺀 내용이 최소 길이 이상일 때만 센다(2026-09-28 PC 과거 답 대조, Fable 재검토 대상):
    //    표 칸 경계 '|'를 빼자 「| **전파법 시행령 제18조(재할당)** [원문 확인됨] | …내용… |」의 이름 칸이 시스템 프롬프트 핵심 조문의
    //    제목 줄과 13자 그대로 겹쳐(100%) 뒤 칸 내용을 판정하지 않고 초록이 됐다 — 제목만 맞는 거짓 초록.
    // ② 판 고르기(2026-10-09 사내 선행 이식, 사내 8c8c373c — 아래 versionMarks 설명): rows = 한 법령군·조의 조각들. 문서가 둘 이상이고 판 상태(status)를 알 때만 —
    // 지침서 글이 섞이거나 상태를 모르면(검색 자료 조각은 status를 싣지 않는다 — 외부 검색은 현행만이라 두 판이 함께 오지 않는다) 종전대로 긴 글.
    // 두 판이 함께 오는 길은 verifyCitations가 DB에서 받은 행(현행·시행예정 + status)뿐이다. 표지는 표시 안 글·인용문·그 줄에서만 읽는다.
    const verSrc = String(cite.tag || '') + '\n' + String(claim || '') + '\n' + String(cite.line || '');
    const verInfo = function (rows) {
      const docs = [];
      for (const c of rows) if (docs.indexOf(c.doc_name) === -1) docs.push(c.doc_name);
      if (docs.length < 2 || docs.some(isPromptDoc) || new Set(docs.map(docFamily)).size !== 1) return null;
      if (rows.some(function (c) { return c.status == null; })) return null;
      const def = pickVersion(rows, null);
      if (!def) return null;
      const pend = docs.filter(function (d) { return rows.some(function (c) { return c.doc_name === d && c.status === 'pending'; }); })
        .sort(function (a, b) { return docDate(a).localeCompare(docDate(b)); });
      return { docs: docs, def: def, pend: pend, mk: versionMarks(verSrc, docs, pend, def) };
    };
    const versionsOf = function (rows, key) {
      const vi = verInfo(rows);
      if (!vi) return null;
      const docs = vi.docs, def = vi.def, pend = vi.pend, mk = vi.mk;
      if (mk.hit.length >= 2) {   // 비교 문장 — 두 판을 한 원문으로(#288 ⓓ′ 꼴, 머리에 판·번호·시행일)
        const both = mk.hit.slice().sort(function (a, b) { return ((pend.indexOf(a) !== -1) - (pend.indexOf(b) !== -1)) || docDate(a).localeCompare(docDate(b)); });
        const text = both.map(function (d) {
          const t = mergedOf(d + '|' + key);
          return '■ ' + articleLabel(docFamily(d), key) + ' — ' + versionHead(d, pend.indexOf(d) !== -1) + '\n' + (t.length > MULTI_SRC_MAX ? t.slice(0, MULTI_SRC_MAX) + '\n…(이하 생략)' : t);
        }).join('\n\n');
        return { doc: both[0], text: text, mark: 'both', def: def, pend: pend, both: both, alt: [] };
      }
      const doc = mk.hit.length ? mk.hit[0] : def;
      return { doc: doc, text: mergedOf(doc + '|' + key), mark: mk.hit.length ? mk.kinds.join('+') : 'none', def: def, pend: pend, both: null,
        alt: docs.filter(function (d) { return d !== doc; }) };
    };
    // 고른 판이 잘렸나 — 조각이 다른 판보다 적거나 조각 번호가 끊기면(통째 보강본은 _full로) verifyCitations가 DB에서 그 판 전체를 받는다
    const verParts = function (d, key) {
      const rows = articleText.get(d + '|' + key) || [];
      if (rows.some(function (r) { return '_full' in r; })) {
        return { n: rows.reduce(function (s, r) { return s + (r._parts || 1); }, 0), whole: rows.every(function (r) { return !('_full' in r) || !!r._full; }) };
      }
      const ix = rows.map(function (r) { return r.chunk_index || 0; }).sort(function (a, b) { return a - b; });
      return { n: rows.length, whole: ix.every(function (v, i) { return i === 0 || v === ix[i - 1] + 1; }) };
    };
    // ① 원문 그대로 대조도 판 표지가 가리킨 판만 본다(② 외부 보탬, 2026-10-09): 같은 조의 판이 둘 이상이고 표지가 그중 일부를 가리키면 나머지 판은 ①에서 뺀다 —
    // 현행 글을 그대로 옮기고 「(법률 제N호)」로 시행예정 판을 단 인용이 현행과 그대로 일치해 초록이 되지 않게(그 판과 대조해 판정기로). 표지가 없으면 판을 빼지 않는다.
    const vbSkip = new Set(), vbInfo = new Map();   // vbInfo: 법령군|조 → verInfo(판이 둘 이상이고 상태를 아는 조 — S4)
    const fkOf = function (gk) { return docFamily(gk.slice(0, gk.lastIndexOf('|'))) + '|' + gk.slice(gk.lastIndexOf('|') + 1); };
    {
      const byFamKey = new Map();
      articleText.forEach(function (rows, gk) {
        const k = gk.slice(gk.lastIndexOf('|') + 1), fk = docFamily(rows[0].doc_name) + '|' + k;
        if (!byFamKey.has(fk)) byFamKey.set(fk, []);
        Array.prototype.push.apply(byFamKey.get(fk), rows);
      });
      byFamKey.forEach(function (rows, fk) {
        const vi = verInfo(rows);
        if (!vi) return;
        vbInfo.set(fk, vi);
        if (!vi.mk.hit.length) return;
        const k = fk.slice(fk.lastIndexOf('|') + 1);
        vi.docs.forEach(function (d) { if (vi.mk.hit.indexOf(d) === -1) vbSkip.add(d + '|' + k); });
      });
    }
    const vbBefore = stripCite(before).length >= minClaim, vbLine = !!cite.line && stripCite(cite.line).length >= minClaim;
    let vbBest = null, vbRatio = 0;
    for (const gk of Array.from(articleText.keys()).concat(addVerbatim)) {   // 본칙 조문 먼저(같은 겹침이면 본칙), 부칙 조는 뒤(#290)
      if (vbSkip.has(gk)) continue;
      const t = mergedOf(gk);
      const r = Math.max(vbBefore ? quoteOverlap(before, t) : 0, vbLine ? quoteOverlap(cite.line, t) : 0, cite.after ? quoteOverlap(cite.after, t) : 0);
      // S4(2026-10-10, 2단계 Fable 판정 §4-8): 같은 조의 두 판이 같은 겹침(글자가 같은 조문)이면 기본 판(현행) — 종전엔 앞에 잡힌 판이라
      // 7ebd328e 「전기통신사업법 제32조의13제3항」(두 판 md5까지 같음)이 시행예정판(제21652호) 문서로 적혔다(색은 같고 doc·citedDocs·집계만 어긋남)
      const tieToDefault = r > 0 && r === vbRatio && vbBest && !isAddendumKey(gk.slice(gk.lastIndexOf('|') + 1)) && fkOf(gk) === fkOf(vbBest) &&
        vbInfo.has(fkOf(gk)) && vbInfo.get(fkOf(gk)).def === gk.slice(0, gk.lastIndexOf('|'));
      if (r > vbRatio || tieToDefault) { vbRatio = r; vbBest = gk; }
    }
    if (vbBest && vbRatio >= VERBATIM_MIN) {
      const [doc, key] = [vbBest.slice(0, vbBest.lastIndexOf('|')), vbBest.slice(vbBest.lastIndexOf('|') + 1)];
      const vr = { status: 'ok', kind: 'article', lawDoc: docFamily(doc), doc: doc, key: key, text: mergedOf(vbBest), verbatim: true, overlap: vbRatio, claim: claim, reason: '원문 그대로 인용(' + Math.round(vbRatio * 100) + '%)' };
      // S4 덤: 판이 둘 이상인 조에서 그대로 일치한 판이 기본 판(현행)이 아니면 — 시행예정 글을 옮긴 것 — 판정 길과 같이 판 기록을 달아
      // 초록 이름표에 판 꼬리 「(… 시행 판)」가 붙게 한다(종전엔 그대로 일치 길에 verDefault가 없어 꼬리가 안 붙었다)
      const vbi = isAddendumKey(key) ? null : vbInfo.get(docFamily(doc) + '|' + key);
      if (vbi) { vr.verMark = vbi.mk.hit.length ? vbi.mk.kinds.join('+') : 'none'; vr.verDefault = vbi.def; vr.verPending = vbi.pend; }
      // 외부 ②: 그대로 일치한 판이 자료의 유일한 판인데 표지가 다른 판(시행예정)을 가리키면 그 판을 받아 다시 대조한다(verifyCitations — 현행 글 + 시행예정 번호)
      if (!isAddendumKey(key) && !isPromptDoc(doc) && !Array.from(articleText.keys()).some(function (g) { return g !== vbBest && g.slice(g.lastIndexOf('|') + 1) === key && docFamily(g.slice(0, g.lastIndexOf('|'))) === docFamily(doc); })) {
        const w = versionWanted(verSrc, doc, (articleText.get(vbBest) || []).some(function (c) { return c.status === 'pending'; }));
        if (w) vr.verFetch = { fam: docFamily(doc), key: key, want: w };
      }
      return vr;
    }

    // ② 후보 조문(표시에 적힌 대상, 없으면 인용문 안 → 앞 줄) 중 컨텍스트에 있는 것을 고른다 — 여럿이면 인용문과 가장 많이
    //    겹치는 것, 같으면 앞의 것. 문서는 lawScope 순서(이름 적은 법령 → 이어받은 법령 → 같은 계열)로 처음 있는 문서군
    //    법령 이름 없는 참조(「법 제N조」·「영 제N조」·「동법」·맨 「제N조」)의 법령은 **이어받기로 추측한 것**이다(#286, 2026-10-07):
    //    ⓐ 자료에 그 번호 조문이 둘 이상의 법령에 있고 이어받은 법령의 조문에는 인용문 낱말이 하나도 없는데 다른 법령의 조문에는
    //       들면(claimRelevance 2낱말·20%↑) 그쪽을 고른다 ⓑ 이어받은 법령에 그 조문이 없어도 낱말이 드는 법령이 있으면 그쪽(종전엔 원문 없음)
    //    ⓒ 추측한 법령의 조문에 인용문 낱말이 들지 않으면 판정기의 「불일치」를 주황으로 내지 않는다(verifyCitations — 회색 + 어느 조문으로
    //       봤는지 적음). 38abd528(10-06): 3절 끝 「전파법 제92조제3호」를 이어받은 5절 표의 「법 제19조①」(폐업 60일 전 서류 제출)·「법 제19조③3호」가
    //    전파법 제19조(무선국 개설허가)와 대조돼 거짓 '원문과 다름' 3개, 「영 제24조①」·「법 제96조②」는 전파법 시행령·전파법에서 찾아 거짓 '원문 없음'
    //    2개 — 전기통신사업법 제19조·시행령 제24조·제96조는 자료에 있었다. 이름을 적은 법령은 종전대로 그 법령만(#240 ① — 못 맞춘 이름도 원문 없음).
    let chosen = null, chosenRatio = -1, chosenDoc = null, chosenText = '', chosenLaw = null, chosenGuess = null, chosenRel = null, missGuess = null, chosenKey = null;
    const misses = [], missLabels = [];
    const found = [];   // 자료에 있는 후보(후보 순서) — 다중 원문(#288 ⓓ′)·후보별 구조 검사에 쓴다
    let numAmbig = 0, addAmbig = 0;
    const longestOf = function (rows, fam, keyOf) {
      let t = '';
      const docs = new Set(rows.filter(function (c) { return docFamily(c.doc_name) === fam; }).map(function (c) { return c.doc_name; }));
      for (const doc of docs) { const m = mergedOf(doc + '|' + keyOf(doc)); if (m.length > t.length) t = m; }
      return t;
    };
    for (let ci = 0; ci < candidates.length; ci++) {
      const cand = candidates[ci], scope = scopes[ci];
      const gk = guessKind(cand.lawInfo, families);              // 'none' 이름으로 못 박음 / 'inherit' 이어받기 추측 / 'weak' 못 맞춘 약한 이름
      const guessed = gk !== 'none', maySwitch = gk === 'inherit';
      // 부칙 열쇠(#290)는 자료의 부칙 단위에서 찾는다 — 조각 대신 {doc_name, _rk(번호를 푼 열쇠)}. 번호 없이 적은 「부칙 제M조」는 문서마다 푼 열쇠가 다르다
      const isAdd = isAddendumKey(cand.key);
      const addHits = isAdd ? addendumHits(cand.key) : null;
      const all = isAdd ? addHits.map(function (h) { return { doc_name: h.doc, article_no: null, _rk: h.key }; })
        : (chunks || []).filter(function (c) { return articleKey(c.article_no) === cand.key; });
      const rkOf = function (doc) { if (!isAdd) return cand.key; const h = addHits.find(function (x) { return x.doc === doc; }); return h ? h.key : cand.key; };
      let lawDoc = null, cands = all, guess = null;
      if (scope) {
        let picked = [];
        for (const f of scope) {
          const x = all.filter(function (c) { return docFamily(c.doc_name) === f; });
          if (x.length) { picked = x; lawDoc = f; break; }
        }
        cands = picked;
      }
      if (guessed && all.length) {
        let famsHere = [];
        for (const c of all) { const f = docFamily(c.doc_name); if (famsHere.indexOf(f) === -1) famsHere.push(f); }
        // 종류 낱말뿐인 이름(「규정 제N조」, ④)은 인용문 낱말로 바꿔 고를 때도 그 종류의 법령만 — 안 막으면 「앞에 규정 이름 없음」이 낱말로 다른 법령에 붙는다
        const sfx = cand.lawInfo && cand.lawInfo.suffix;
        if (sfx) famsHere = famsHere.filter(function (f) { return suffixFits(f, sfx, families); });
        const rel = famsHere.map(function (f) {
          const rows = all.filter(function (c) { return docFamily(c.doc_name) === f; });
          return Object.assign({ fam: f, boiler: rows.some(function (c) { return isBoilerplateArticle(c.article_no, cand.key); }) }, claimRelevance(claim, longestOf(all, f, rkOf)));
        });
        rel.sort(function (a, b) { return b.hits - a.hits || b.score - a.score; });
        const inh = lawDoc ? rel.filter(function (x) { return x.fam === lawDoc; })[0] : null;
        const top = rel.filter(function (x) { return !x.boiler; })[0] || null;   // 바꿔 고를 후보 — 목적·정의 조문은 아니다
        if (inh) {
          guess = { how: gk, fam: lawDoc, hits: inh.hits, score: inh.score, ambig: famsHere.length > 1 };   // 'inherit' 또는 'weak'(못 맞춘 약한 이름)
          if (maySwitch && top && top.fam !== lawDoc && !relEvidence(inh) && relEvidence(top)) {   // ⓐ 이어받은 조문엔 낱말 근거가 없고 다른 법령 조문엔 있다
            lawDoc = top.fam; cands = all.filter(function (c) { return docFamily(c.doc_name) === top.fam; });
            guess = { how: 'claim', fam: top.fam, hits: top.hits, score: top.score, ambig: true };
          }
        } else if (maySwitch && top && relEvidence(top)) {                   // ⓑ 이어받은 법령에 이 조문이 없다(또는 이어받을 법령이 없다) → 낱말 드는 법령
          lawDoc = top.fam; cands = all.filter(function (c) { return docFamily(c.doc_name) === top.fam; });
          guess = { how: scope ? 'claim' : 'any', fam: top.fam, hits: top.hits, score: top.score, ambig: famsHere.length > 1 };
        } else if (!scope) {                                                // 이어받을 법령도 낱말 근거도 없다 — 종전대로 아무 문서(가장 긴 조문), 추측 표시만
          guess = { how: 'any', fam: null, hits: rel[0].hits, score: rel[0].score, ambig: famsHere.length > 1 };
        }
      }
      if (!cands.length) {
        const ctxText = cand.ctxLaw && cand.ctxLaw.text;
        const lawLab = (scope && scope[0]) || (cand.lawInfo && (cand.lawInfo.title || cand.lawInfo.text)) || ctxText || '';
        misses.push(lawLab + ' ' + (isAdd ? keyText(cand.key) : cand.key));
        missLabels.push(articleLabel(lawLab, cand.key, cand.paras, cand.items));
        // 번호 없이 적은 부칙 조인데 그 법령의 자료 안 부칙 단위가 둘 이상 — 어느 부칙인지 몰라 대조하지 않았다(§13-3 ③, 검증기는 자료만 본다)
        if (isAdd && !parseAddKey(cand.key).unit && !addAmbig) {
          for (const f of (scope || Array.from(famAddUnits.keys()))) { const n = famAddUnits.has(f) ? famAddUnits.get(f).size : 0; if (n >= 2) { addAmbig = n; break; } }
        }
        // 고시 번호 이름(#288 ⓑ)인데 그 번호의 문서가 자료에 둘 이상 — 「없음」이 아니라 고르지 않은 것임을 적는다(c19c247f: 제2026-11호 고시 2개)
        if (cand.lawInfo && cand.lawInfo.numbered && !numAmbig) { const k = (numIndex.get(cand.lawInfo.number) || []).length; if (k >= 2) numAmbig = k; }
        if (guessed && scope && scope.length && !missGuess) missGuess = { how: gk, label: scope[0] + ' ' + keyText(cand.key) };
        continue;
      }
      let best = null, bestText = '';
      const docs = new Set(cands.map(function (c) { return c.doc_name; }));
      for (const doc of docs) { const t = mergedOf(doc + '|' + rkOf(doc)); if (t.length > bestText.length) { best = doc; bestText = t; } }
      const vinfo = isAdd ? null : versionsOf(cands, cand.key);   // 같은 법령군·조의 판이 둘 이상이면 표지로 고른다(종전: 긴 글, ②)
      if (vinfo) { best = vinfo.doc; bestText = vinfo.text; }
      const r = quoteOverlap(claim, bestText);
      // 겹침이 같으면(바꿔 쓴 인용은 둘 다 0): 인용문 낱말 수가 뚜렷이(3개 이상) 다르면 더 드는 조문 → 아니면 이름을 적은(추측 아닌) 후보 →
      // 그래도 같으면 앞의 것(사내 관찰 ①, #286-보론2). 종전 「같으면 앞의 것」은 #286 ⓑ로 이름 없는 의무 조문도 찾히게 되자
      // 「제N조제M항 위반 시 ○○법 제K조 … 과태료」 줄의 과태료 문장을 앞에 적힌 의무 조문과 대조했다(의무 조문 낱말 3/7이라 ⓒ 회색에도 안 걸림).
      // 뚜렷한 낱말 차이만 이름보다 앞세우는 까닭: 「…제19조①은 60일 전 고지를 정하며 벌칙은 ○○법 제96조 참조」처럼 이름 적은 조문이 곁가지일 때
      // 이름을 앞세우면 거짓 주황이 나지만, 제재 조문은 의무 조문의 말을 되풀이해 낱말 수가 비슷하기 일쑤라(표 행 「전파법 제25조의2①, 영 제51조」 5 대 7)
      // 작은 차이로 모델이 이름 적은 쪽을 버리면 안 된다.
      const rel = claimRelevance(claim, bestText);
      found.push({ cand: cand, doc: best, text: bestText, lawDoc: lawDoc, guess: guess, rkey: rkOf(best), ver: vinfo });
      let better = r > chosenRatio;
      if (!better && chosen && r === chosenRatio) {
        if (Math.abs(rel.hits - chosenRel.hits) >= 3) better = rel.hits > chosenRel.hits;
        else if (guessed !== !!chosenGuess) better = !guessed;
      }
      if (better) { chosen = cand; chosenRatio = r; chosenDoc = best; chosenText = bestText; chosenLaw = lawDoc; chosenGuess = guess; chosenRel = rel; chosenKey = rkOf(best); }
    }
    if (!chosen) return Object.assign({ status: 'missing', reason: misses.map(function (s) { return s.trim(); }).join('·') + ' 원문 없음', lawDoc: null, lookFor: missLabels.join('·') },
      missGuess ? { lawGuess: missGuess.how, guessLabel: missGuess.label } : {}, numAmbig ? { numAmbig: numAmbig } : {}, addAmbig ? { addAmbig: addAmbig } : {});
    const paras = chosen.paras || [], items = chosen.items || [];
    // 추측한 법령의 기록(#286): 어떻게 골랐나(inherit 이어받음 / claim 인용문 낱말 / any 아무 문서 / number 고시 번호)·인용문 낱말이 그 조문에 드는가(guessEvidence)
    const guessFieldsOf = function (f) {
      const g = f.guess;
      if (!g) return {};
      const gfam = g.fam || (f.doc ? docFamily(f.doc) : '');
      const ps = f.cand.paras || [];
      return { lawGuess: g.how, guessEvidence: relEvidence(g), guessHits: g.hits, guessAmbig: !!g.ambig, guessLabel: gfam + ' ' + keyText(f.rkey || f.cand.key) + (ps.length ? '제' + ps[0] + '항' : '') };
    };
    const chosenF = found.find(function (f) { return f.cand === chosen; });
    const guessFields = guessFieldsOf(chosenF);
    // 표시 하나가 조문 둘 이상을 덮으면(#288 ⓓ′, Fable 「최대」 재점검 §12-1) 판정기에 보내는 원문은 **자료에 있는 후보 조문 전부**(후보 순서, 조문마다
    // 「■ <법령> 제N조」 머리)이고 호출은 한 번이다. 후보 = 표시에 적힌 대상, 대상 없는 표시면 표시가 있는 줄에 적힌 조(앞 줄에서 가져온 후보는 아니다).
    // 38abd528 3G 표: 「법 제19조①, 영 제24조①」(c61)은 제19조만 보내 2차가 「시행령 확인 필요 → 판단불가」(회색), 「법 제96조②, 제104조⑤2호」(c66)는
    // 제96조만 보내 과태료 반쪽(1천만원)을 아무도 대조하지 않았다 — 단일 원문은 거짓 회색이자 거짓 초록의 구멍이었다. 위 동률 규칙(#286-보론2)은
    // 대표 조문(구조 검사 순서가 아닌 표시 이름표·기록의 key)을 고를 때만 남는다. 문턱 측정은 하지 않는다(둘 다 이름 없는 동률은 저장 자료에 1건).
    const multiKeys = (cite.tagTargets && cite.tagTargets.length) ? cite.tagTargets.map(function (t) { return t.key; }) : (cite.lineKeys || []);
    let members = found.filter(function (f) { return !f.cand.extOnly && multiKeys.indexOf(f.cand.key) !== -1; }).slice(0, MULTI_MAX);
    if (members.length < 2 || members.indexOf(chosenF) === -1) members = null;
    // 항·호는 원문에 그 구조가 있을 때만 검사 (단항 조문에 "제1항"이라고 쓴 것까지 잡지 않는다) — 다중 원문이면 후보마다, 하나라도 걸리면 그 상태
    const paraChecks = [];
    const structFail = function (f) {
      const text = f.text, key = f.rkey || f.cand.key, ps = f.cand.paras || [], its = f.cand.items || [];
      const gf = guessFieldsOf(f);
      if (ps.length && /[①-⑳]/.test(text)) {
        for (const n of ps) {
          if (n >= 1 && n <= 20 && text.indexOf(CIRCLED[n - 1]) === -1)
            return Object.assign({ status: 'missing', reason: key + ' 제' + n + '항 원문 없음(조문 일부만 검색됨)', lawDoc: f.lawDoc, doc: f.doc, key: key, paras: [n], items: [] }, gf);
        }
      } else if (!isAddendumKey(key) && ps.some(function (n) { return n >= 2; })) {   // 부칙 조(#290)는 DB 저장본 확인 길이 없다 — 판정기로
        // 항 구분(①…)이 전혀 없는 조문에 제2항 이상(#288 §5, c66 「법 제96조②」 — 제96조는 단항, 호만 있다). 자료 조각만으로는 청크가 ①을 잃은 것과
        // 가를 수 없으므로 여기서는 표지만 달고, verifyCitations가 DB 저장본(fetchLawArticle)에도 ①~⑳이 없을 때만 회색으로 바꾼다. 제1항은 종전대로
        // 통과(단항 조문을 「제1항」이라 부르는 관행). 실DB 현행 8,919조 중 스스로 제2항을 말하면서 ①이 없는 조문은 3개(§12-2) — 맞는 인용이 걸릴 일은 드물다.
        paraChecks.push({ doc: f.doc, lawDoc: f.lawDoc, key: key, n: ps.filter(function (n) { return n >= 2; })[0], paras: ps, items: its, gf: gf });
      }
      if (its.length && /(^|\n)\s*\d+(의\d+)?\.\s/.test(text)) {
        for (const it of its) {
          if (!new RegExp('(^|\\n)\\s*' + it + '\\.\\s').test(text))
            return Object.assign({ status: 'missing', reason: key + ' 제' + it + '호 원문 없음(조문 일부만 검색됨)', lawDoc: f.lawDoc, doc: f.doc, key: key, paras: ps, items: [it] }, gf);
        }
      } else if (its.length) {
        // 호를 주장했는데 원문에 호 구조가 없다 — 청크 경계에서 줄바꿈이 사라지면
        // ('…으로 한다.1. 가입자선로운영비용…') 위 정규식이 불발해 호 검사가 통째로 생략됐다(실측 12.4%).
        // 검사를 못 한 것이지 맞다는 뜻이 아니므로 초록을 주지 않는다. (#169-보론5)
        return Object.assign({ status: 'nocheck', reason: key + ' 제' + its.join('·') + '호 구조를 원문에서 찾지 못해 대조 불가',
                 lawDoc: f.lawDoc, doc: f.doc, key: key, paras: ps, items: its }, gf);
      }
      return null;
    };
    // ② 판: 고른 판에 인용한 항·호가 없고 다른 판에는 있으면 그 판으로(항 번호가 어긋나는 개정 — 전파법 제24조는 현행 ④ = 시행예정 ⑤).
    // 다중 원문(#288 ⓓ′)은 후보마다 판을 골랐고 그 밖(항·호 판 바꾸기·잘린 판 받기·다른 판 받기)은 하지 않는다.
    const vf = (!members && chosenF) ? chosenF.ver : null;
    if (vf && !vf.both && vf.alt.length) {
      const n0 = paraChecks.length;
      if (structFail(chosenF)) {
        for (const x of vf.alt) {
          const g = Object.assign({}, chosenF, { doc: x, text: mergedOf(x + '|' + chosenF.rkey) });
          if (!structFail(g)) {
            vf.alt = vf.alt.filter(function (y) { return y !== x; }).concat([chosenF.doc]);
            vf.doc = x; vf.mark = vf.mark + '+항호';
            chosenF.doc = x; chosenF.text = g.text;
            chosenDoc = x; chosenText = g.text;
            break;
          }
        }
      }
      paraChecks.length = n0;   // 시험 삼아 본 구조 검사의 §5 표지는 버린다(아래에서 다시 단다)
    }
    // 판 기록: verMark(number·date·word·none·both, 「+」로 잇는다)·verDefault(표지 없을 때의 판)·verPending·altDocs(다른 판)·verDocs(두 판 다중 원문)·
    // verFetch(verifyCitations가 DB에서 받아 다시 고른다 — {doc}: 고른 판이 잘렸다 / {want}: 자료에 판이 하나뿐인데 표지가 다른 판을 가리킨다)
    const vx = {};
    if (vf) {
      const rk = chosenF.rkey || chosen.key;
      vx.verMark = vf.mark; vx.verDefault = vf.def; vx.verPending = vf.pend;
      if (vf.both) vx.verDocs = vf.both;
      else {
        vx.altDocs = vf.alt.map(function (x) { return { doc: x, text: mergedOf(x + '|' + rk) }; });
        const p = verParts(vf.doc, rk);
        if (!p.whole || vf.alt.some(function (x) { return verParts(x, rk).n > p.n; })) vx.verFetch = { fam: docFamily(vf.doc), key: rk, doc: vf.doc };
      }
    } else if (!members && chosenF && !isAddendumKey(chosenKey) && !isPromptDoc(chosenDoc)) {
      // 외부 ②(외부 전용, 운영자 결정 2026-10-09): 검색 자료에 이 조의 판이 하나뿐(외부 검색은 현행만)인데 표지가 다른 판(시행예정)을 가리키면 그 판을 받아 대조한다.
      // 대시보드 「시행예정 개정본」 구역(buildPendingContext)은 검증 조각에 들지 않아, AI가 그 구역 글을 표지와 함께 옮기면 현행판과만 대조됐다(10-08 사내 화면 사례 1과 같은 꼴).
      const pendKnown = (articleText.get(chosenDoc + '|' + chosenKey) || []).some(function (c) { return c.status === 'pending'; });
      const w = versionWanted(verSrc, chosenDoc, pendKnown);
      if (w) vx.verFetch = { fam: docFamily(chosenDoc), key: chosenKey, want: w };
    }
    for (const f of members || [chosenF]) { const fail = structFail(f); if (fail) return Object.assign(fail, vx); }
    // 인용문에 내용이 없으면(제목·번호뿐) 판정할 것이 없다 — 표시를 그대로 둔다
    if ((headingOnly ? normQ(cite.after || '') : beforeBody).length < minClaim)
      // 번호·제목만 적고 내용을 옮기지 않았다 — 대조할 주장이 없으므로 '확인됨'이 될 수 없다.
      // (프롬프트에서도 이런 인용을 금지한다 — system_prompt [핵심 원칙] 1)
      return Object.assign({ status: 'noclaim', kind: 'article', lawDoc: chosenLaw, doc: chosenDoc, key: chosenKey, paras: paras, items: items, text: chosenText, overlap: chosenRatio, claim: claim, reason: '조문 번호·제목만 적혀 대조할 내용이 없음' }, guessFields, vx);
    const extra = {};
    if (paraChecks.length) extra.paraChecks = paraChecks;
    if (members) {
      extra.multi = members.map(function (f) { return { lawDoc: f.lawDoc, doc: f.doc, key: f.rkey || f.cand.key, paras: f.cand.paras || [], items: f.cand.items || [] }; });
      extra.text = members.map(function (f) {
        const t = f.text.length > MULTI_SRC_MAX ? f.text.slice(0, MULTI_SRC_MAX) + '\n…(이하 생략)' : f.text;
        return '■ ' + articleLabel(docFamily(f.doc), f.rkey || f.cand.key) + '\n' + t;   // 혼합 표시의 부칙 조는 부칙 조문으로(#290 ⑦)
      }).join('\n\n');
      // 추측 기록은 대표 조문의 것 그대로. 다른 후보가 낱말 근거 없이 추측한 조문이면(#286 ⓒ) 「불일치」를 주황으로 내지 않는다 — 그 조문을 대조 원문에
      // 넣은 것 자체가 틀렸을 수 있다(verifyCitations setMismatch). 무엇 때문인지 적으려고 그 후보 이름표를 남긴다.
      const weakG = members.find(function (f) { return f !== chosenF && f.guess && (f.guess.how === 'number' || !relEvidence(f.guess)); });
      if (weakG) extra.multiWeakGuess = guessFieldsOf(weakG).guessLabel;
    }
    return Object.assign({ status: 'ok', kind: 'article', lawDoc: chosenLaw, doc: chosenDoc, key: chosenKey, paras: paras, items: items, text: chosenText, overlap: chosenRatio, claim: claim }, guessFields, extra, vx);
  }
  const MULTI_MAX = 4;          // 다중 원문 후보 상한(표시 하나)
  const MULTI_SRC_MAX = 3000;   // 다중 원문의 조문당 글자 상한 — 단일 원문은 종전대로 4,000자(verifyCitations)

  // 3) Haiku 판정 — 원문이 있었던 인용만. callHaiku(system, user) → Promise<string(JSON 배열 텍스트)>
  const JUDGE_SYSTEM =
    '당신은 법령 인용 검증자입니다. 각 항목의 "인용문"(AI 답변의 한 대목)이 "원문"(법령·고시 조문)의 내용을 사실과 다르게 옮겼는지만 판정합니다.\n' +
    '불일치로 보는 경우: 조문 번호·항·호가 원문과 다르다 / 의무의 주체·상대방이 바뀌었다 / 요건·효과·기한·수치·예외가 원문과 다르다 / 원문에 없는 내용을 원문의 규정처럼 서술했다.\n' +
    '불일치가 아닌 경우: 요약·생략·표현 차이 / 원문에 근거한 해석·의견 / 다른 조문을 함께 언급 / 인용문이 원문의 일부만 다룸 / 인용문이 조문 번호·제목만 적고 내용을 옮기지 않음(→ "판단불가").\n' +
    '확신이 없으면 "판단불가". 출력은 JSON 배열만, 설명 금지: [{"id":1,"verdict":"일치|불일치|판단불가","reason":"30자 이내"}]';

  async function judgeCitations(items, callHaiku) {
    if (!items.length || typeof callHaiku !== 'function') return {};
    const user = items.map(function (it) {
      return '### 항목 ' + it.id + '\n[인용 대상] ' + it.target + '\n[인용문]\n' + it.claim + '\n[원문]\n' + it.source;
    }).join('\n\n');
    const raw = await callHaiku(JUDGE_SYSTEM, user);
    const s = String(raw || '');
    const i = s.indexOf('['), j = s.lastIndexOf(']');
    if (i === -1 || j <= i) throw new Error('판정 JSON 없음');
    const arr = JSON.parse(s.slice(i, j + 1));
    const out = {};
    for (const v of arr) if (v && v.id != null) out[String(v.id)] = { verdict: String(v.verdict || ''), reason: String(v.reason || '').slice(0, 120) };
    return out;
  }

  // 3-2) 2차 판정(2026-10-05) — 1차(위 Haiku)가 「불일치」라 한 항목만 더 강한 모델(호출측 callJudge2)이 다시 본다.
  //  외부판 판정기 주황은 전 기간 7개가 모두 거짓이었다(일부만 든 것을 불일치로·요약을 불일치로·원문 ② 오독·대상 오선택). 1차 지시문은
  //  글자 그대로 둔다 — 초록이 되는 「일치」의 보정을 건드리지 않고(#268 「1차 호출은 그대로, 양성만 따로 확인」과 같은 꼴) 주황만 걸러 낸다.
  //  1차 결과·메모는 보여 주지 않는다(앞선 판정에 끌리지 않게). 「불일치」면 어긋나는 구절을 원문·인용문에서 글자 그대로 내게 하고
  //  코드가 그 구절이 판정기에 보낸 원문·인용문에 실제로 있는지 본다(spanIn) — 없으면 주황이 아니라 회색.
  //  ⚠️ 이 글자를 고치면 tests/cite_judge_probe.js로 실측 세트를 다시 잰다(시험이 지문으로 잠근다).
  //  #284(2026-10-06)부터는 1차 결과와 상관없이 판정 대상 전부를 이 지시문으로 보낸다(verifyCitations 관문) — 지시문·모델·요청값은 그대로.
  const JUDGE2_SYSTEM =
    '당신은 법령 인용 검증자입니다. 각 항목의 "인용문"(AI 답변의 한 대목)이 "원문"(법령·고시 조문)의 내용을 사실과 다르게 옮겼는지만 판정합니다.\n' +
    '먼저 원문을 끝까지 읽고, 인용문이 말하는 것(누가·무엇을·어떤 요건에서·어떤 효과)을 원문의 해당 부분과 하나씩 맞춰 봅니다.\n' +
    '불일치로 보는 경우: 조문 번호·항·호가 원문과 다르다 / 의무의 주체·상대방이 바뀌었다(원문이 한정한 주체를 빼서 대상이 넓어진 경우 포함) / 요건·효과·기한·수치·예외가 원문과 다르다(원문이 적용 범위를 좁힌 말을 빼서 범위가 달라진 경우 포함) / 원문에 없는 내용을 원문의 규정처럼 서술했다.\n' +
    '불일치가 아닌 경우: 법적 의미가 그대로인 요약·생략·표현 차이 / 원문이 어느 하나에 해당하면 되는 대상·행위를 여럿 나열하는데 인용문이 그중 일부만 든 것(든 것이 원문 목록에 있으면 일치) / 원문에 근거한 해석·의견 / 다른 조문을 함께 언급 / 인용문이 조문 번호·제목만 적고 내용을 옮기지 않음(→ "판단불가").\n' +
    '"불일치"라고 답할 때는 어긋나는 곳을 원문과 인용문에서 각각 글자 그대로 옮겨 적습니다 — source_span(원문에서)·claim_span(인용문에서), 각 60자 이내, 고치거나 줄이지 말 것. 빠뜨린 것이 문제면 source_span에 빠진 원문 구절을, claim_span에 그 자리의 인용문 구절을 적습니다. 그런 두 구절을 댈 수 없으면 "불일치"가 아닙니다.\n' +
    '확신이 없으면 "판단불가". 출력은 JSON 배열만, 설명 금지: [{"id":1,"verdict":"일치|불일치|판단불가","source_span":"","claim_span":"","reason":"40자 이내"}]';

  // 2차 판정기 요청 — 운영(rag.ts·verify-citations → _shared/cite_judge2.ts)과 실측 도구(tests/cite_judge_probe.js)가 같은 값을 읽는다.
  // 실측(2026-10-05, 고정 사례 12개 × 4회): Opus 5.5(추론 medium) = 거짓 5개 주황 0 · 진짜 7개 주황 4/4. Sonnet 5(추론 끔)는 「목록 중 하나만 든」
  // 제51조를 6/8 주황(1차와 같은 오판), Sonnet 5.5(medium)는 「피해를 입은 자 → 피해 이용자」 요약의 제55조②를 4/8 주황. 호출당 ≈ $0.013.
  // Opus 5.5는 추론을 끌 수 없다(thinking 생략 = adaptive). 온도류 값은 넣지 않는다(온도류 금지 규칙 — 예외는 크롤러 긴급도·재보도 대조 두 곳뿐).
  const JUDGE2_MODEL = 'claude-opus-5-5';
  const JUDGE2_REQUEST = { output_config: { effort: 'medium' } };
  const JUDGE2_MAX_TOKENS = 8000;

  // 판정기가 옮겨 적은 구절이 hay(판정기에 보낸 원문·인용문)에 실제로 있는가 — 공백·문장부호·괄호 차이는 보지 않고(normQ),
  // 말줄임(… ...)으로 나눈 조각은 순서대로 있어야 한다. 조각 합 4자 미만은 근거로 치지 않는다.
  function spanIn(span, hay) {
    const parts = String(span || '').split(/…|\.{3}/).map(normQ).filter(function (p) { return p.length >= 2; });
    let total = 0;
    for (const p of parts) total += p.length;
    if (total < 4) return false;
    const h = normQ(hay);
    let pos = 0;
    for (const p of parts) { const i = h.indexOf(p, pos); if (i < 0) return false; pos = i + p.length; }
    return true;
  }

  // items: 1차와 같은 {id, target, claim, source} — callJudge2(system, user) → Promise<string(JSON 배열 텍스트)>
  // 반환 id → {verdict, reason, source_span, claim_span, grounded}(grounded = 불일치이고 두 구절이 모두 실재)
  async function judgeCitations2(items, callJudge2) {
    if (!items.length || typeof callJudge2 !== 'function') return {};
    const user = items.map(function (it) {
      return '### 항목 ' + it.id + '\n[인용 대상] ' + it.target + '\n[인용문]\n' + it.claim + '\n[원문]\n' + it.source;
    }).join('\n\n');
    const raw = await callJudge2(JUDGE2_SYSTEM, user);
    const s = String(raw || '');
    const i = s.indexOf('['), j = s.lastIndexOf(']');
    if (i === -1 || j <= i) throw new Error('2차 판정 JSON 없음');
    const arr = JSON.parse(s.slice(i, j + 1));
    const byId = new Map(items.map(function (it) { return [String(it.id), it]; }));
    const out = {};
    for (const v of arr) {
      if (!v || v.id == null || !byId.has(String(v.id))) continue;
      const it = byId.get(String(v.id));
      const verdict = String(v.verdict || ''), src = String(v.source_span || ''), clm = String(v.claim_span || '');
      out[String(v.id)] = { verdict: verdict, reason: String(v.reason || '').slice(0, 120), source_span: src.slice(0, 200), claim_span: clm.slice(0, 200),
        grounded: verdict === '불일치' && spanIn(src, it.source) && spanIn(clm, it.claim) };
    }
    return out;
  }

  // 관문 Pㄱ1(#284)의 2차 호출 꼴 — 항목 하나 = 호출 하나(id 1), 동시 JUDGE2_CONCURRENCY. 실패(throw)·결과 없음은 한 번 더 부르고,
  // 그래도 안 되면 {err}. 실측(2026-10-06, 53항목 × 2회): 호출당 중앙 5.5초·90% 8.7초·최대 12.5초 — 6개씩이면 판정 대상 24개 상한에서 약 40초.
  const JUDGE2_CONCURRENCY = 6;
  async function judgeEachSecond(items, callJudge2) {
    const out = new Array(items.length);
    const one = async function (it) {
      let err = null;
      for (let t = 0; t < 2; t++) {
        try {
          const v = await judgeCitations2([Object.assign({}, it, { id: 1 })], callJudge2);
          if (v['1']) return { v: v['1'] };
          err = '2차 판정 결과 없음';
        } catch (e) { err = String(e && e.message || e); }
      }
      return { err: err };
    };
    let next = 0;
    const worker = async function () { while (next < items.length) { const i = next++; out[i] = await one(items[i]); } };
    await Promise.all(Array.from({ length: Math.min(JUDGE2_CONCURRENCY, items.length) }, worker));
    return out;
  }

  // 표시 없는 통째 인용에 표시를 붙인다(#155-보론7, 11:39 답변 — 모델이 조문을 그대로 옮기고도 표시를 하나도 안 붙였다).
  // 원문과 60% 이상 그대로 겹치는 문단은 기계가 증명할 수 있으므로 「[원문 확인됨: 법령명 제N조]」를 문단 끝에 붙인다.
  // 제목(#)·표(|)·이미 표시가 있는 문단·짧은 문단은 건너뛴다. 항·호는 적지 않는다(어느 항인지 단정하지 않기 위해).
  // 바로 옆 문단에 **모델이 직접 쓴** 표시가 있으면 그 조문을 신뢰한다.
  //   실측(#169-보론4): 모델은 "…수리하여야 한다" 다음 문단에 '[원문 확인됨: 동법 제9조제5항]'을
  //   써 뒀는데, 기계는 같은 문단에 '제5조의2'를 붙였다. 둘이 어긋나면 어느 쪽이 맞는지 모르므로
  //   기계가 덧붙이지 않는다(모델 표시는 뒤이어 정상 검증 경로를 탄다).
  //   인용 **본문 안**의 조문 번호는 보지 않는다 — 법령 문장은 다른 조문을 흔히 인용한다
  //   (예: 전기통신사업법 제50조② 본문에 '제52조제1항과 제53조'가 나온다).
  function neighborTagKeys(parts, i) {
    const keys = [];
    const re = /\[원문\s*확인됨[^\]]*?제\s*(\d+조(?:의\d+)?)/g;
    for (const j of [i - 2, i + 2]) {
      const seg = String(parts[j] || '');
      let m;
      while ((m = re.exec(seg)) !== null) if (keys.indexOf(m[1]) < 0) keys.push(m[1]);
    }
    return keys;
  }

  function autoTagVerbatim(answer, chunks) {
    const text = String(answer || '');
    const arts = new Map();
    for (const c of chunks || []) {
      const k = articleKey(c && c.article_no);
      if (!k || !c.doc_name) continue;
      const gk = c.doc_name + '|' + k;
      if (!arts.has(gk)) arts.set(gk, []);
      arts.get(gk).push(c);
    }
    if (!arts.size) return { answer: text, added: 0 };
    const merged = new Map();
    for (const [gk, list] of arts) {
      list.sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); });
      merged.set(gk, mergeChunkTexts(list.map(function (c) { return c.content || ''; })));
    }
    let added = 0;
    const parts = text.split(/(\n[ \t]*\n)/);   // 문단과 구분자를 번갈아 보존
    for (let i = 0; i < parts.length; i += 2) {
      const p = parts[i];
      const body = p.replace(/^\s*[-*>]\s+/, '');
      if (!p.trim() || /^\s*#/.test(p) || /^\s*\|/.test(p)) continue;
      if (/\[(원문\s*확인됨|⚠️ 원문|학습 데이터 기반|요약 문서 기반|근거 조문 미확인)[^\]]*\]/.test(p)) continue;   // 요약 문서 기반: 시스템 프롬프트 3-⑧(#257)
      if (normQ(body).length < 40) continue;
      let best = null, bestR = 0, secondR = 0;
      for (const [gk, t] of merged) {
        const r = quoteOverlap(body, t);
        if (r > bestR) { secondR = bestR; bestR = r; best = gk; }
        else if (r > secondR) { secondR = r; }
      }
      if (!best || bestR < VERBATIM_MIN) continue;
      // ① 2등과 겨우 차이 나면 단정하지 않는다(같은 문언이 두 조문에 있는 경우)
      if (bestR - secondR < AMBIG_MARGIN) continue;
      const doc = best.slice(0, best.lastIndexOf('|')), key = best.slice(best.lastIndexOf('|') + 1);
      // ② 옆 문단에 모델이 쓴 표시가 있고 그 조문과 다르면 붙이지 않는다
      const nb = neighborTagKeys(parts, i);
      if (nb.length && nb.indexOf(key) < 0) continue;
      const tag = ' [원문 확인됨: ' + docFamily(doc) + ' 제' + key + ']';
      // 문단 끝의 굵게(**) 닫힘 안쪽에 넣지 않는다 — 끝 공백만 떼고 뒤에 붙인다
      parts[i] = p.replace(/\s+$/, '') + tag;
      added++;
    }
    return { answer: parts.join(''), added: added };
  }

  // 표시 없는 인용 대조(#230, 2026-09-26 운영자 결정 — 판정 기준은 그대로): 모델이 조문을 인용 문단이나 따옴표로 옮기고도
  // 표시를 붙이지 않으면 검증기가 보지 않았다. 96760b6b 답변은 「전기통신사업법 제2조는 / (인용 문단) / 으로 정의합니다」 꼴의
  // 무표시 인용 4개 중 2개가 원문과 달랐다(장려금 정의에서 '판매에 관하여'·'모든' 누락, 제50조①5의2와 ②를 섞은 합성문).
  // 조문 번호가 인용 바로 앞에 있는 것만 골라 보이지 않는 표지(QUOTE_MARK)가 든 표시를 붙이고, 모델 표시와 같은 경로
  // (원문 그대로 → 확인됨 / 아니면 Haiku 판정)로 보낸다. 끝에서 확인됨은 표시를 남기고(기계가 대조했으므로), 다름·원문 없음·대조 못 함은
  // 세 상태 표시로 바꾸고, 대조할 것이 없으면(번호 못 읽음·내용 없음·중복) 표시를 지운다 — 경고로 만들지 않는다(#155 unparsed 원칙).
  // 판정 기준에 '인용 형태면 생략도 불일치' 줄을 더하는 안은 기각: 시험에서 멀쩡한 요약 인용(제52조① 조치 나열을 '등'으로 줄임)까지
  // 불일치로 잡았다. 현행 기준으로는 장려금·제50조 2건 불일치, 제52조 일치.
  const QUOTE_MARK = '⁠';   // 단어 결합자(보이지 않음) — 기계가 붙인 표시 식별용, 결과 답변에는 남기지 않는다
  const ART_REF_RE = /제\s?\d+\s?조(?:\s?의\s?\d+)?(?:\s?제\s?\d+\s?항)?(?:\s?제\s?\d+\s?호(?:\s?의\s?\d+)?)?/g;
  const INTRO_TOPIC_RE = /(?:은|는|에서|에는|에\s?따르면|에\s?의하면)\s*[:：]?\s*$/;
  const INTRO_ASFOLLOWS_RE = /(?:다음과|아래와)\s?같이\s?(?:규정|정의|명시|정하)[가-힣\s]{0,12}[.:：]\s*$/;
  const CONT_RE = /^\s*(?:고|라고|이라고|로|으로|를|을|이라는|라는|와|과)(?=[\s,.]|$)/;
  // 인용 앞 문장의 마지막 조문 참조 → 표시 안에 적을 대상(법령명은 앞 낱말이 법령명일 때만, '동법'이면 이어받기)
  // 약한 이름(법령 종류 낱말로 끝나지 않는 「…가이드라인」, lawNameBefore weak)은 검색 자료의 문서군(families)과 모델 표시와 같은
  // 규칙(resolveLaw)으로 맞춰 그 문서 이름을 **낫표째** 적고(「…」 제1조 — 다시 읽을 때 quoted로 같은 문서에 맞는다. 낫표가 없으면
  // 한 낱말 제목은 이름으로 읽히지 않는다), 못 맞추면 표시하지 않는다(null). 종전엔 이름을 버리고 「제1조」만 적어, 대조 단계가
  // 앞 법령 이어받기·어느 문서든으로 읽고 번호만 같은 다른 고시(번호이동성 기준) 제1조와 대조해 거짓 '원문과 다름'을 냈다(사내 인계
  // 2026-10-04 — #240 「표시에 적힌 법령만 본다」와 어긋남). 못 맞춘 약한 이름은 이름이 아닌 말(「이 가운데 제16조는」)일 수도 있어
  // '원문 없음'으로도 단정하지 않는다 — 기계 표시는 대조할 것이 분명할 때만 붙인다(#155 unparsed 원칙).
  function introCiteLabel(intro, maxTail, families) {
    const s = String(intro || '').replace(/\*\*/g, '');
    let m, last = null;
    ART_REF_RE.lastIndex = 0;
    while ((m = ART_REF_RE.exec(s)) !== null) last = m;
    if (!last || s.length - (last.index + last[0].length) > maxTail) return null;
    const info = lawNameBefore(s.slice(0, last.index));
    let law = '';
    if (info && info.suffix) law = info.text;   // 「규정 제10조」·「동 규정 제10조」는 적힌 그대로 — 다시 읽을 때 같은 이어받기(④)
    else if (info && info.inherit) law = info.level === '시행령' ? '동령' : '동법';
    else if (info && info.subord) law = info.subord;
    else if (info && info.candidates && !info.weak) law = info.text;
    else if (info && info.weak) {
      const hit = families && families.length ? resolveLaw(info, families) : null;
      if (!hit) return null;
      law = '「' + hit + '」';
    }
    return (law ? law + ' ' : '') + last[0].replace(/\s+/g, '');
  }
  // families = 검색 자료의 문서군(docFamily) — 약한 이름 맞추기에만 쓴다. 없으면 약한 이름 인용은 표시하지 않는다.
  function tagUntaggedQuotes(answer, families) {
    const text = String(answer || '');
    const parts = text.split(/(\n[ \t]*\n)/);   // 문단과 구분자를 번갈아 보존
    const hasTag = function (p) { return /\[(원문\s*확인됨|원문 미확인|원문 없음|원문과 다름|⚠️ 원문|학습 데이터 기반|요약 문서 기반|근거 조문 미확인)[^\]]*\]/.test(p); };
    const skip = function (p) { return !p.trim() || /^\s*#/.test(p) || /^\s*\|/.test(p) || hasTag(p); };
    let added = 0;
    for (let i = 0; i < parts.length; i += 2) {
      const p = parts[i];
      if (skip(p)) continue;
      // ① 인용 문단: 앞 문단이 「…제N조제M항은」·「…제N조는 다음과 같이 규정합니다.」로 끝나는 따로 선 문단
      const prev = i >= 2 ? parts[i - 2] : '';
      const next = i + 2 < parts.length ? parts[i + 2] : '';
      if (stripCiteBody(p).length >= 24 && prev && !hasTag(prev)) {
        const pv = prev.replace(/\*\*/g, '').replace(/\s+$/, '');
        let label = null;
        if (INTRO_TOPIC_RE.test(pv) && CONT_RE.test(next)) label = introCiteLabel(pv.replace(INTRO_TOPIC_RE, ''), 12, families);
        else if (INTRO_ASFOLLOWS_RE.test(pv)) label = introCiteLabel(pv.replace(INTRO_ASFOLLOWS_RE, ''), 40, families);
        if (label) {
          parts[i] = p.replace(/\s+$/, '') + ' [원문 확인됨: ' + label + QUOTE_MARK + ']';
          added++;
          continue;
        }
      }
      // ② 문장 안 따옴표 인용: 「제N조제M항은 "…(25자 이상)…"고 규정」 — 닫는 따옴표 바로 뒤에 붙인다
      parts[i] = p.replace(/(제\s?\d+\s?조[^"“”\n]{0,24}?(?:은|는|에서|에는|에\s?따르면)\s*)(["“])([^"”\n]{25,}?)(["”])(?=\s*(?:고|라고|이라고|로|으로|를|을|이라는|라는)(?:[\s,.]|$))/g,
        function (all, intro, q1, body, q2, off) {
          const label = introCiteLabel(p.slice(0, off) + intro, 12, families);
          if (!label) return all;
          added++;
          return intro + q1 + body + q2 + ' [원문 확인됨: ' + label + QUOTE_MARK + ']';
        });
    }
    return { answer: parts.join(''), added: added };
  }

  // ⓒ 받은 조문의 판 — hint(「제N호」, 그 법령의 판일 때만) → 현행(날짜 늦은 판) → 시행예정(날짜 이른 판). 행: fetchLawArticle 결과(status 포함)
  function pickVersion(rows, hint) {
    const docs = [];
    for (const r of rows || []) if (docs.indexOf(r.doc_name) === -1) docs.push(r.doc_name);
    if (hint) { const d = docs.find(function (x) { return x.indexOf('(제' + hint + '호)') !== -1; }); if (d) return d; }
    const dateOf = function (n) { const m = String(n || '').match(/\((\d{8})\)\s*$/); return m ? m[1] : ''; };
    const has = function (d, st) { return (rows || []).some(function (r) { return r.doc_name === d && (st === 'current' ? (r.status == null || r.status === 'current') : r.status === st); }); };
    const cur = docs.filter(function (d) { return has(d, 'current'); }).sort(function (a, b) { return dateOf(b).localeCompare(dateOf(a)); });
    if (cur.length) return cur[0];
    const pend = docs.filter(function (d) { return has(d, 'pending'); }).sort(function (a, b) { return dateOf(a).localeCompare(dateOf(b)); });
    return pend[0] || null;
  }
  // ── ② 판 고르기(2026-10-09 사내 선행 이식 — 사내 8c8c373c, 설계 docs/인용판정기_거짓차이_설계_261009.md §2-1, 외부 준비자료 local_docs/인용판정기_오판_사내인계_준비자료_261009.md §7) ──
  // checkCitation ②는 같은 법령군·조가 문서 둘 이상(현행·시행예정)이면 **글이 긴 쪽**을 원문으로 골랐다 — 어느 판이 길지는 몇 조각이 실렸느냐에 달려 흔들렸다.
  // 사내 10/8 첨부 자문은 「전파법 제24조제2항(법률 제21553호, 2026.10.22 시행)」을 현행판(②준공기한 연장)과 대조해 거짓 「차이 있음」 2개. 표지를 읽어 판을 고른다 —
  // 표시 안 글·인용문·그 줄에서:
  //   번호 「법률 제N호」·「…고시 제YYYY-N호」·괄호 「(제N호)」(4자리 이상 또는 YYYY-N) → 문서명 「(제N호)」가 같은 판 /
  //   시행일 「YYYY.M.D 시행」·「시행 YYYY-MM-DD」 → 문서명 끝 날짜가 같은 판 / 「시행예정」·「시행 예정」, 현행판 날짜보다 뒤의 「신설」·「개정」+날짜
  //   → 시행예정판(조문 안 「<개정 2013.3.23>」 같은 옛 날짜는 아니다) / 「현행」 → 현행판.
  // 한 판만 가리키면 그 판, 둘 다 가리키면(비교 문장) 두 판을 한 원문으로(머리에 판·번호·시행일), 표지가 없으면 현행판(pickVersion과 같은 순서).
  // 「개정안」은 표지가 아니다(2단계 Fable 판정 S1, 2026-10-09 — 이 체계에서 개정안은 국회 계류 법안이라 KB의 어느 판도 아니고, 시행예정판을 고르면 맞는 현행 인용이
  // 시행예정판과 대조됐다. 외부 답 3건 모두 계류안 뜻, 사내 1702debe와 같은 정규식). 「2차 불일치 → 다른 판으로 한 번 더 판정」은 규칙 B(verifyCitations 관문 뒤).
  const VER_NO_RE = /(?:(?:법률|대통령령|총리령|부령|[가-힣]*령|[가-힣]*고시|훈령|예규|공고)\s*제\s?|[(（]\s*제\s?)(\d{4}\s?[-‐–－]\s?\d{1,4}|\d{4,})\s?호/g;
  const VER_DATE_RE = /(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*(?:일|\.)?/g;
  const VER_EFF_BEFORE_RE = /시행\s*(?:일자|일)?\s*[:：(]?\s*$/;
  const VER_EFF_AFTER_RE = /^\s*\)?\s*(?:부터\s*)?시행/;
  const VER_AMEND_BEFORE_RE = /(?:신설|개정)\s*[,<(]?\s*$/;
  const VER_AMEND_AFTER_RE = /^\s*[)>]?\s*(?:신설|개정)/;
  const VER_PENDING_RE = /시행\s?예정/;
  function docDate(n) { const m = String(n || '').match(/\((\d{8})\)\s*$/); return m ? m[1] : ''; }
  function dotDate(d) { return d.slice(0, 4) + '.' + Number(d.slice(4, 6)) + '.' + Number(d.slice(6, 8)); }
  function normVerNo(s) { return String(s || '').replace(/\s/g, '').replace(/[‐–－]/g, '-'); }
  function ymdOf(m) { return m[1] + ('0' + Number(m[2])).slice(-2) + ('0' + Number(m[3])).slice(-2); }
  // 판 머리 「현행(법률 제21065호, 시행 2026.1.2)」 — 두 판 다중 원문에 쓴다
  function versionHead(doc, pending) {
    const s = String(doc || ''), tm = s.match(/^[^(]+\(([^)]+)\)/), nm = s.match(/\(제([^)]+)호\)/), d = docDate(s);
    const no = nm ? (tm ? tm[1] + ' ' : '') + '제' + nm[1] + '호' : '';
    const parts = [no, d ? '시행 ' + dotDate(d) : ''].filter(Boolean);
    return (pending ? '시행예정' : '현행') + (parts.length ? '(' + parts.join(', ') + ')' : '');
  }
  // 초록 이름표의 판 「(2026.10.22 시행 판)」 — 대조한 판이 현행(표지 없을 때 고를 판)이 아닐 때만
  function versionTail(doc) { const d = docDate(doc); return d ? '(' + dotDate(d) + ' 시행 판)' : '(다른 판)'; }
  // 표지가 가리키는 판들 — s: 표시 안 글 + 인용문 + 그 줄, docs: 같은 법령군·조의 판 문서명, pend: 그중 시행예정(날짜순), def: 표지 없을 때의 판(현행)
  function versionMarks(s, docs, pend, def) {
    const S = String(s || ''), hit = [], kinds = [];
    const add = function (d, k) { if (d && hit.indexOf(d) === -1) hit.push(d); if (d && kinds.indexOf(k) === -1) kinds.push(k); };
    const nr = new RegExp(VER_NO_RE.source, 'g'), dr = new RegExp(VER_DATE_RE.source, 'g');
    let m;
    while ((m = nr.exec(S))) { const no = normVerNo(m[1]); add(docs.find(function (x) { return x.indexOf('(제' + no + '호)') !== -1; }) || null, 'number'); }
    const curDate = pend.indexOf(def) === -1 ? docDate(def) : '';
    while ((m = dr.exec(S))) {
      const ymd = ymdOf(m), b = S.slice(Math.max(0, m.index - 12), m.index), a = S.slice(m.index + m[0].length, m.index + m[0].length + 8);
      if (VER_EFF_BEFORE_RE.test(b) || VER_EFF_AFTER_RE.test(a)) add(docs.find(function (x) { return docDate(x) === ymd; }) || null, 'date');
      else if (pend.length && curDate && ymd > curDate && (VER_AMEND_BEFORE_RE.test(b) || VER_AMEND_AFTER_RE.test(a))) add(pend[0], 'word');
    }
    if (pend.length && VER_PENDING_RE.test(S)) add(pend[0], 'word');
    if (pend.indexOf(def) === -1 && S.indexOf('현행') !== -1) add(def, 'word');
    return { hit: hit, kinds: kinds };
  }
  // 외부 ②(외부 전용): 검색 자료에 이 조의 판이 하나(doc)뿐일 때 표지가 다른 판을 가리키는가 — 받아 보기 전엔 다른 판의 문서명을 모르므로 표지 꼴만 본다
  // (받은 뒤의 고르기는 versionMarks). 헛조회를 줄이려고 이 판보다 **뒤** 것만 센다(DB에 남는 판은 현행·시행예정뿐이고 시행예정은 번호·시행일이 현행보다 뒤다):
  //  번호 — 이 판 번호가 아니고, 종류 낱말이 있으면 문서명 종류 괄호와 같고(「대통령령 제N호」는 법률 문서의 판이 아니다), 이 판 번호보다 큼 /
  //  시행일 — 이 판 날짜보다 뒤 / 「신설·개정」+날짜 — 이 판 날짜보다 뒤 / 「시행예정」 낱말. 이 판이 시행예정이면 낱말·개정 날짜는 보지 않는다.
  //  반환: 'number'·'date'·'word' 또는 null
  function verNoCmp(a, b) {
    const pa = a.split('-').map(Number), pb = b.split('-').map(Number);
    if (pa.length !== pb.length) return 1;
    for (let i = 0; i < pa.length; i++) if (pa[i] !== pb[i]) return pa[i] - pb[i];
    return 0;
  }
  function versionWanted(s, doc, pendKnown) {
    const S = String(s || ''), d = String(doc || '');
    const curNo = normVerNo((d.match(/\(제([^)]+)호\)/) || [])[1] || ''), curType = norm((d.match(/^[^(]+\(([^)]+)\)/) || [])[1] || ''), cur = docDate(d);
    const nr = new RegExp(VER_NO_RE.source, 'g'), dr = new RegExp(VER_DATE_RE.source, 'g');
    let m;
    while ((m = nr.exec(S))) {
      const no = normVerNo(m[1]);
      if (d.indexOf('(제' + no + '호)') !== -1) continue;
      const tw = norm((m[0].match(/^([가-힣]+)\s*제/) || [])[1] || '');   // 종류 낱말 — 괄호 꼴 「(제N호)」면 없음
      if (tw && curType && curType !== tw && !curType.endsWith(tw)) continue;
      if (curNo && verNoCmp(no, curNo) <= 0) continue;
      return 'number';
    }
    if (cur) {
      while ((m = dr.exec(S))) {
        const ymd = ymdOf(m), b = S.slice(Math.max(0, m.index - 12), m.index), a = S.slice(m.index + m[0].length, m.index + m[0].length + 8);
        if (ymd <= cur) continue;
        if (VER_EFF_BEFORE_RE.test(b) || VER_EFF_AFTER_RE.test(a)) return 'date';
        if (!pendKnown && (VER_AMEND_BEFORE_RE.test(b) || VER_AMEND_AFTER_RE.test(a))) return 'word';
      }
    }
    if (!pendKnown && VER_PENDING_RE.test(S)) return 'word';
    return null;
  }

  // 법령·고시 문서명 꼴 「이름(종류)(제N호)(YYYYMMDD)」 — 보도자료·이슈사례·회의록·논문 등은 ⓒ의 이름 맞추기 대상이 아니다(10-07 실DB 현행 489문서 중 276)
  const LAW_DOC_NAME_RE = /^[^(]+\([^)]+\)\(제[^)]*호\)\(\d{8}\)$/;
  const OUTSIDE_MAX = 4;      // ⓒ 자문당 받는 조문 수(조문 단위)
  const PARA_FETCH_MAX = 4;   // §5 항 구분 확인으로 받는 조문 수

  // 종합: 답변 → 표시 검증·교체
  //   { answer, chunks, annexSources, systemPrompt, callHaiku, callJudge2, fetchLawArticle, maxJudge, autoTag, quoteTag }
  //   callJudge2(system, user) — 2차 판정기(선택, 3-2). 있으면 판정 대상 전부를 항목 하나씩 보내고 2차가 표시를 정한다(#284 관문 Pㄱ1,
  //     1차는 기록·예비). 없으면 1차가 표시를 정한다(1차 불일치 = 주황).
  //   fetchLawArticle(family, key) — 지침서 핵심 조문만 있는 인용을 실DB 조문으로 바꿔 대조(선택, #284 swapPromptArticles).
  //     #288부터 §5 항 구분 확인(DB 저장본)과 ⓒ 검색 자료 밖 조문 대조에도 쓴다.
  //   listLawDocs() — DB 문서명 목록(현행·시행예정, 선택 — #288 ⓒ). 없으면 ⓒ를 하지 않는다(종전대로 원문 없음).
  //   → { answer, verdicts: [{tag, kind, key, law, status, reason, judge, auto}], changed, autoTagged, quoteTagged, citedDocs }
  async function verifyCitations(args) {
    const chunks = ((args && args.chunks) || []).concat(args && args.systemPrompt ? pseudoChunksFromPrompt(args.systemPrompt) : []);
    // 표시 없는 통째 인용에 먼저 표시를 붙인다(autoTag=false로 끌 수 있음) — 그 뒤 검증은 모델이 붙인 표시와 같은 경로
    const at = (args && args.autoTag === false) ? { answer: String((args && args.answer) || ''), added: 0 } : autoTagVerbatim((args && args.answer) || '', chunks);
    // 그다음 표시 없는 인용 문단·따옴표 인용에 대조용 표시(#230, quoteTag=false로 끌 수 있음)
    const fams = [];
    for (const c of chunks) { const f = docFamily(c.doc_name); if (f && fams.indexOf(f) === -1) fams.push(f); }   // checkCitation과 같은 문서군
    const qt = (args && args.quoteTag === false) ? { answer: at.answer, added: 0 } : tagUntaggedQuotes(at.answer, fams);
    const answer = qt.answer;
    const cites = findCitations(answer);
    if (!cites.length) return { answer: answer, verdicts: [], changed: 0, autoTagged: at.added, quoteTagged: 0, citedDocs: [] };
    // 인용이 가리키는 조문이 지침서 글뿐이면 실DB 조문으로 바꿔 대조한다(#284 — fetchLawArticle이 없으면 종전대로 지침서 글)
    const sw = await swapPromptArticles(cites, chunks, args && args.fetchLawArticle);
    const results = cites.map(function (c) {
      const auto = String(c.tag).indexOf(QUOTE_MARK) !== -1;
      // 직전 인용 문단에 같은 조의 표시가 이미 있는 토막 표시는 중복 — 판정하지 않고 지운다(#176)
      if (c.dupOfPrev) return Object.assign({}, c, { status: 'dup', reason: '직전 인용 문단의 표시와 중복', key: c.tagTarget ? c.tagTarget.key : (c.dupKey || null), auto: auto });
      const r = Object.assign({}, c, checkCitation(c, sw.chunks, (args && args.annexSources) || []), { auto: auto });
      // 판정 원문의 출처를 남긴다(10-12 집계용): swap = 지침서 대신 받은 실DB 조문, kept = 지침서 글 그대로(바꿀 수단 없음), failed = 받지 못함
      const fk = r.doc ? docFamily(r.doc) + '|' + r.key : '';
      if (r.doc && isPromptDoc(r.doc)) {
        r.srcPrompt = sw.failed.has(fk) ? 'failed' : 'kept';
        // 실DB 조문을 받으려 했으나 못 받았다 — 줄인 지침서 글과만 맞춰 본 초록은 내지 않는다(Fable 판정 §4-3 5 「못 받으면 회색」)
        if (r.srcPrompt === 'failed' && r.status === 'ok') { r.status = 'unclear'; r.reason = '법령 원문을 받지 못해 지침서 요약과만 대조됨'; }
      } else if (fk && sw.swapped.has(fk)) r.srcPrompt = 'swap';
      return r;
    });
    // DB 조문 조회(법령군|조 → 현행·시행예정 행, 실패 = null) — ⓒ와 §5가 같이 쓴다(같은 조문을 두 번 받지 않게)
    const canFetch = !!(args && typeof args.fetchLawArticle === 'function');
    const dbMemo = new Map();
    const dbRows = function (fam, key) {
      const k = fam + '|' + key;
      if (!dbMemo.has(k)) dbMemo.set(k, Promise.resolve().then(function () { return args.fetchLawArticle(fam, key); }).then(function (rows) {
        return (rows || []).filter(function (x) { return x && !isPromptDoc(x.doc_name) && docFamily(x.doc_name) === fam && articleKey(x.article_no) === key && x.content; });
      }, function () { return null; }));
      return dbMemo.get(k);
    };
    // ⓒ 검색 자료 밖 조문 받아 대조(#288, 운영자 결정 2026-10-07 「한다」 — Fable 판정 §4·§12-4·§12-7 2): 법령 이름을 적은 참조(guessKind 'none')인데 그 조문이
    // 검색 자료에 없으면(「원문 없음 — 검색 자료에 X 없음」) DB 문서명 목록에서 그 이름에 **하나만** 맞는 법령의 조문을 받아 같은 경로(그대로 인용 → 판정기)로
    // 대조한다 — 맞게 인용했으면 「[원문 확인됨(검색 자료 밖 조문과 대조): …]」, 다르면 주황. 저장 자문 c11·c21·c22·c23·c25(모두 정확한 기억 인용)가 회색이었다.
    // 이름 없는·추측한 참조(이어받기·약한 이름·고시 번호)는 그대로 원문 없음(법령을 모르니 받을 수 없다), 「조문 일부만 검색됨」(자료에 조문은 있음)도 그대로.
    // 판 고르기: 받은 판(현행·시행예정)을 모두 checkCitation에 넘겨 ② 표지 규칙(versionMarks — 번호·시행일·「시행예정/현행」, 2026-10-09)으로 고른다.
    // 표지가 없으면 현행(여럿이면 날짜가 늦은 판), 현행이 없으면 시행예정(pickVersion 순서 — 종전 「인용 줄·표시의 (법률 제N호)면 그 판」은 번호 표지가 맡는다).
    // 받은 조문은 그 표시 전용(공용 자료에 넣으면 다른 추측 참조의 법령 고르기가 바뀐다), 조문 단위 상한 OUTSIDE_MAX(답변 순서, 같은 조문은 한 번 받아 함께 씀 —
    // ② 판 받기와 함께 센다).
    //   listLawDocs() → 문서명 목록(현행·시행예정 — 호출측 RPC kb_doc_names), 법령·고시 꼴(「이름(종류)(제N호)(YYYYMMDD)」)만 쓴다.
    const picked = new Set();   // DB에서 받은 조문(법령군|조) — ⓒ와 ② 판 받기가 상한 OUTSIDE_MAX를 함께 쓴다
    if (canFetch && typeof args.listLawDocs === 'function') {
      const ctxFams = [];
      for (const c of sw.chunks || []) { const f = docFamily(c.doc_name); if (f && ctxFams.indexOf(f) === -1) ctxFams.push(f); }
      const elig = [];
      results.forEach(function (r, i) {
        if (r.status !== 'missing' || r.kind !== 'article' || r.lawGuess || /조문 일부만/.test(r.reason || '')) return;
        // 부칙 열쇠(#290)는 DB에서 받지 않는다 — fetchLawArticle은 본칙 조 열쇠로 찾는다(부칙은 검색 자료 안에서만 대조)
        const named = (cites[i].candidates || []).filter(function (x) { return x && x.key && !isAddendumKey(x.key) && guessKind(x.lawInfo, ctxFams) === 'none'; });
        if (named.length) elig.push({ i: i, named: named });
      });
      if (elig.length) {
        let names = null;
        try { names = await args.listLawDocs(); } catch (e) { names = null; }
        const dbFams = [];
        for (const n of names || []) if (LAW_DOC_NAME_RE.test(String(n))) { const f = docFamily(n); if (dbFams.indexOf(f) === -1) dbFams.push(f); }
        for (const e of elig) {
          if (!names) { results[e.i].srcFetched = 'error'; continue; }
          let capped = false;
          e.jobs = [];
          for (const x of e.named) {
            const fam = resolveLaw(x.lawInfo, dbFams, true);
            if (!fam) continue;
            const id = fam + '|' + x.key;
            if (!picked.has(id)) { if (picked.size >= OUTSIDE_MAX) { capped = true; continue; } picked.add(id); }
            e.jobs.push({ fam: fam, key: x.key });
          }
          if (!e.jobs.length) results[e.i].srcFetched = capped ? 'cap' : 'nodoc';
        }
        await Promise.all(elig.filter(function (e) { return e.jobs && e.jobs.length; }).map(async function (e) {
          const c = cites[e.i], r = results[e.i];
          const priv = [];
          for (const j of e.jobs) {
            const rows = await dbRows(j.fam, j.key);
            if (rows === null) { r.srcFetched = 'error'; return; }
            // 상태 없는 행은 현행으로 본다(pickVersion과 같다) — 판 고르기(versionsOf)는 상태를 아는 행에서만 돈다
            for (const x of rows) priv.push({ id: x.id, doc_name: x.doc_name, article_no: x.article_no, chunk_index: x.chunk_index, content: x.content, status: x.status || 'current' });
          }
          if (!priv.length) { r.srcFetched = 'norows'; return; }
          const r2 = checkCitation(c, priv, []);
          // 받은 조문에서도 항·호가 없으면(「조문 일부만」) 종전 「원문 없음」 그대로 — 판정기 길(ok)·대조 못 함(nocheck·noclaim)만 바꾼다
          if (r2.status === 'ok' || r2.status === 'nocheck' || r2.status === 'noclaim') {
            const nr = Object.assign({}, c, r2, { auto: r.auto, srcFetched: 'db', srcRows: priv });
            delete nr.verFetch;   // 받은 판들로 이미 골랐다 — ② 판 받기를 다시 하지 않는다
            results[e.i] = nr;
          } else r.srcFetched = 'partial';
        }));
      }
    }
    // ② 판 받기(2026-10-09): checkCitation이 verFetch를 단 표시 — DB에서 그 법령군·조의 판(현행·시행예정)을 받아 **그 표시 전용** 자료로 다시 대조한다(ⓒ와 같은 방식,
    // 상한 OUTSIDE_MAX 공유, 답변 순서). 두 꼴:
    //  {doc}  고른 판이 잘렸다(조각이 다른 판보다 적거나 끊김 — 사내 c6) → 그 판 전체로 갈아 끼움, 받은 것이 더 많지 않으면 그대로('same')
    //  {want} 외부 전용 — 자료에 판이 하나뿐인데 표지가 다른 판을 가리킨다 → 자료의 그 조 조각을 받은 판들로 갈아 끼우고 versionMarks로 다시 고른다.
    //         다시 고른 판이 처음 판과 같으면(번호가 다른 법령 것이었다 등) 처음 결과 그대로('same').
    // 못 받으면 처음 결과 그대로('error'), 상한이면 'cap'. verdicts[].ver.fetched에 남긴다.
    // 답변 순서로 하나씩 받는다(S5, 2026-10-10 — 2단계 Fable 판정 §4-2): {want} 조회가 'same'(다른 판 없음·같은 판을 다시 고름 — 다른 법령의 시행일 같은 헛조회)이면
    // 이 표시가 잡은 자리를 돌려줘 뒤 표시가 OUTSIDE_MAX에 막히지 않게 한다(동시에 돌리면 자리 판단이 조회 결과보다 먼저라 돌려줘도 쓸 데가 없다). 판 받기는 드물다(25답 129표시 중 1).
    if (canFetch) {
      for (let i = 0; i < results.length; i++) {
        const r = results[i], vf = r.verFetch;
        if (!vf || ['ok', 'missing', 'nocheck', 'noclaim'].indexOf(r.status) === -1) continue;
        const id = vf.fam + '|' + vf.key;
        const took = !picked.has(id);
        if (took) { if (picked.size >= OUTSIDE_MAX) { r.verFetched = 'cap'; continue; } picked.add(id); }
        const release = function () { if (took && vf.want) picked.delete(id); };
        const rows = await dbRows(vf.fam, vf.key);
        if (rows === null) { r.verFetched = 'error'; continue; }
        const asRow = function (x) { return { id: x.id, doc_name: x.doc_name, article_no: x.article_no, chunk_index: x.chunk_index, content: x.content, status: x.status || 'current' }; };
        let priv;
        if (vf.want) {
          const docs = [];
          for (const x of rows) if (docs.indexOf(x.doc_name) === -1) docs.push(x.doc_name);
          if (!docs.some(function (d) { return d !== r.doc; })) { r.verFetched = 'same'; release(); continue; }   // 다른 판이 DB에도 없다
          priv = sw.chunks.filter(function (x) { return !(docFamily(x.doc_name) === vf.fam && articleKey(x.article_no) === vf.key); }).concat(rows.map(asRow));
        } else {
          const own = rows.filter(function (x) { return x.doc_name === vf.doc; });
          const have = sw.chunks.filter(function (x) { return x.doc_name === vf.doc && articleKey(x.article_no) === vf.key; });
          if (own.length <= have.reduce(function (s, x) { return s + (x._parts || 1); }, 0)) { r.verFetched = 'same'; continue; }
          priv = sw.chunks.filter(function (x) { return !(x.doc_name === vf.doc && articleKey(x.article_no) === vf.key); }).concat(own.map(asRow));
        }
        const r2 = checkCitation(cites[i], priv, (args && args.annexSources) || []);
        if (vf.want && r2.doc === r.doc && !r2.verDocs) { r.verFetched = 'same'; release(); continue; }
        const nr = Object.assign({}, cites[i], r2, { auto: r.auto, verFetched: 'db' });
        if (vf.want) nr.verWant = vf.want;
        delete nr.verFetch;
        if (r.srcPrompt) nr.srcPrompt = r.srcPrompt;
        results[i] = nr;
      }
    }
    // §5 항 구분 확인(#288): 자료 조문에 ①~⑳이 없는데 제2항 이상을 적은 인용 — DB 저장본에도 없으면 회색 「조문에 항 구분 없음(제N항 표기)」,
    // 호가 있는 조문이면 「제N호를 뜻했을 수 있음」(c66 「법 제96조②」 = 제96조제2호). 못 받으면 종전대로(판정기로). 조문 단위 상한 PARA_FETCH_MAX.
    const paraFetched = new Set();
    await Promise.all(results.map(async function (r) {
      if (r.status !== 'ok' || !r.paraChecks || !r.paraChecks.length) return;
      for (const pc of r.paraChecks) {
        let rows = null;
        if (r.srcRows) rows = r.srcRows.filter(function (x) { return x.doc_name === pc.doc && articleKey(x.article_no) === pc.key; });
        else {
          if (!canFetch || isPromptDoc(pc.doc)) continue;
          const id = docFamily(pc.doc) + '|' + pc.key;
          if (!paraFetched.has(id)) { if (paraFetched.size >= PARA_FETCH_MAX) continue; paraFetched.add(id); }
          const all = await dbRows(docFamily(pc.doc), pc.key);
          rows = all ? all.filter(function (x) { return x.doc_name === pc.doc; }) : null;
        }
        if (!rows || !rows.length) continue;
        const full = mergeChunkTexts(rows.slice().sort(function (a, b) { return (a.chunk_index || 0) - (b.chunk_index || 0); }).map(function (x) { return x.content || ''; }));
        if (/[①-⑳]/.test(full)) continue;
        // 대표 조문의 추측 기록을 지우고 이 후보의 것으로(다중 원문이면 걸린 후보 하나만 남긴다 — 무엇이 걸렸는지 표시에 적으려고)
        Object.assign(r, { lawGuess: null, guessEvidence: null, guessHits: null, guessAmbig: null, guessLabel: null }, pc.gf, {
          status: 'unclear', reason: pc.key + ' — 조문에 항 구분 없음(제' + pc.n + '항 표기)', nopara: { n: pc.n, items: /(^|\n)\s*\d+(의\d+)?\.\s/.test(full) },
          lawDoc: pc.lawDoc, doc: pc.doc, key: pc.key, paras: pc.paras, items: pc.items, multi: null, multiWeakGuess: null });
        return;
      }
    }));
    // 8 → 24 (#169-보론5). 실측 답변 하나에 표시가 22개였는데 9번째부터 판정 없이 초록이었다.
    // 판정은 여러 인용을 한 콜에 묶어 보내므로 상한을 올려도 호출 수는 늘지 않는다.
    const maxJudge = args && args.maxJudge != null ? args.maxJudge : 24;
    // 원문 그대로 인용(verbatim, 겹침 0.85↑)은 판정할 것이 없다 — Haiku에 보내지 않는다.
    const judgeable = results.filter(function (r) { return r.status === 'ok' && r.text && !r.verbatim; });
    const toJudge = judgeable.slice(0, maxJudge);
    // 상한을 넘긴 것·판정기가 없는 것은 '대조 못 함'으로 남긴다 — 조용히 초록으로 두지 않는다.
    judgeable.slice(maxJudge).forEach(function (r) { r.status = 'unjudged'; r.reason = '문구 판정 상한(' + maxJudge + '건) 초과'; });
    const useJ2 = !!(args && typeof args.callJudge2 === 'function');
    // 「불일치」 → 주황. 다만 이름 없는 참조를 이어받기로 추측한 법령의 조문에 인용문 낱말이 들지 않으면(#286 ⓒ) 대상을 잘못 고른
    // 「불일치」일 가능성이 커 회색으로 내고 어느 조문으로 봤는지 적는다(10-06 「법 제19조①」이 전파법 제19조와 대조된 거짓 주황 3개).
    // 고시 번호로 고른 문서(#288 ⓑ)는 낱말 근거와 상관없이 늘 회색 — 같은 번호의 다른 일괄개정 고시(자료 밖)를 뜻했을 수 있다(§12-5)
    const setMismatch = function (r, reason) {
      if (r.lawGuess && (r.lawGuess === 'number' || !r.guessEvidence)) {
        r.status = 'unclear'; r.guessGrey = true;
        r.reason = (r.lawGuess === 'weak' ? '법령 이름을 못 맞춘 인용 — ' : r.lawGuess === 'number' ? '고시 번호로 문서를 고른 인용 — ' : '법령 이름 없는 인용 — ') + withRo(r.guessLabel || '') + ' 보고 대조하면 다름' +
          (r.lawGuess === 'number' ? '(같은 번호의 다른 고시일 수 있음)' : '(인용문 낱말이 그 조문에 없음)');
        return;
      }
      if (r.multiWeakGuess) {   // 다중 원문(#288 ⓓ′)에 근거 없이 추측한 조문이 섞였다
        r.status = 'unclear'; r.guessGrey = true;
        r.reason = '대조 원문에 법령을 추측한 조문(' + r.multiWeakGuess + ')이 섞여 대조하면 다름(인용문 낱말이 그 조문에 없음)';
        return;
      }
      r.status = 'mismatch'; r.reason = reason;
    };
    if (toJudge.length && !(args && typeof args.callHaiku === 'function'))
      toJudge.forEach(function (r) { r.status = 'unjudged'; r.reason = '판정기 미가동'; });
    if (toJudge.length && args && typeof args.callHaiku === 'function') {
      const items = toJudge.map(function (r, i) {
        const claim = String(r.claim || r.segment || '').replace(/\*\*/g, '').replace(/\s+/g, ' ').trim();
        const tgtOf = function (law, key, ps, its) { return (law || '') + ' ' + key + (ps.length ? ' 제' + ps.join('·') + '항' : '') + (its.length ? ' 제' + its.join('·') + '호' : ''); };
        // 다중 원문(#288 ⓓ′)은 대상도 후보 모두, 원문은 조문마다 MULTI_SRC_MAX로 잘라 이미 묶었다 — 단일 원문은 종전 그대로(4,000자)
        return {
          id: i + 1,
          target: r.multi ? r.multi.map(function (x) { return tgtOf(x.lawDoc || docFamily(x.doc), x.key, x.paras, x.items); }).join(' · ') : tgtOf(r.lawDoc || r.lawText, r.key, r.paras, r.items),
          claim: claim.length > 900 ? '…' + claim.slice(-900) : claim,
          source: (r.multi || r.verDocs) ? r.text : (r.text.length > 4000 ? r.text.slice(0, 4000) + '\n…(이하 생략)' : r.text),   // 두 판 다중 원문(②)도 판마다 이미 잘랐다
        };
      });
      if (!useJ2) {
        // 2차 판정기가 없는 호출측(시험·옛 도구): 1차가 표시를 정한다 — #280 이전 동작
        try {
          const verdicts = await judgeCitations(items, args.callHaiku);
          toJudge.forEach(function (r, i) {
            const v = verdicts[String(i + 1)];
            if (!v) { r.status = 'unjudged'; r.reason = '판정 결과 없음'; return; }
            r.judge = v;
            if (v.verdict === '불일치') setMismatch(r, v.reason);
            else if (v.verdict !== '일치') r.status = 'unclear';
          });
        } catch (e) {
          // 종전에는 judgeError 만 남기고 status 를 ok 로 두어, 판정기가 죽어도 전건이 초록이었다.
          toJudge.forEach(function (r) {
            if (r.status === 'ok') { r.status = 'unjudged'; r.reason = '판정 호출 실패'; }
            r.judgeError = String(e && e.message || e);
          });
        }
      } else {
        // 관문(#284, 2026-10-06 Fable 판정 Pㄱ1·운영자 결정): 판정 대상 **전부**를 2차로 보내고 2차가 표시를 정한다.
        // #280은 1차(Haiku) 「불일치」만 2차로 보냈는데, 틀린 인용 19개 중 10개를 Haiku가 3번 모두 「일치」라 해 2차까지 못 가고 초록이 됐다
        // (재량 「할 수 있다」→「한다」·한정어 생략). 전부 보내면 19개 중 18개 주황, 맞는 인용의 거짓 주황 0 → 약 1%.
        // 2차는 **항목 하나 = 호출 하나**(잰 꼴 그대로, 동시 JUDGE2_CONCURRENCY) — 한 답의 항목을 묶어 보내는 꼴은 잰 적이 없고
        // 예전 1차 오판(다른 항목 원문을 읽음)·출력 잘림(#281)이 다시 날 수 있다.
        // 1차는 지시문 그대로 함께 돌려 judge에 남긴다(1·2차 갈림 집계용) — 2차가 두 번 다 실패한 항목만 1차 결과로 물러난다(일치 → 초록, 그 밖 → 회색).
        // 2차: 불일치 + 두 구절 실재(grounded) → 주황, 일치 → 초록(D2), 판단불가·구절 확인 실패 → 회색.
        const both = await Promise.all([
          judgeCitations(items, args.callHaiku).then(function (v) { return { v: v }; }, function (e) { return { err: String(e && e.message || e) }; }),
          judgeEachSecond(items, args.callJudge2),
        ]);
        const r1 = both[0], r2 = both[1];
        toJudge.forEach(function (r, i) {
          const v1 = r1.v ? r1.v[String(i + 1)] : null;
          if (v1) r.judge = v1;
          if (r1.err) r.judgeError = r1.err;
          const s = r2[i];
          if (s && s.v) {
            const v = s.v;
            r.judge2 = v;
            if (v.verdict === '불일치' && v.grounded) setMismatch(r, v.reason || (v1 && v1.reason) || '2차 판정 불일치');
            else if (v.verdict === '일치') { r.status = 'ok'; r.reason = null; }
            else { r.status = 'unclear'; r.reason = v.verdict === '불일치' ? '2차 판정의 근거 구절을 원문·인용문에서 못 찾음' : '2차 판정 보류'; }
            return;
          }
          r.judge2Error = (s && s.err) || '2차 판정 결과 없음';
          if (!v1) { r.status = 'unjudged'; r.reason = r1.err ? '판정 호출 실패' : '판정 결과 없음'; }
          else if (v1.verdict === '일치') { r.status = 'ok'; r.reason = null; }
          else { r.status = 'unclear'; r.reason = '2차 판정 실패'; }
        });
        // ② 다른 판 재판정 — 규칙 B(2026-10-10, 2단계 Fable 판정 §3-3 · 사내 1702debe와 같은 조건): 같은 조의 판이 둘 이상인데 **표지 없이 기본 판(현행)을
        // 고른 것**(verMark를 「+」로 자른 첫 토막이 none — none·none+항호)이 2차 「불일치」(근거 구절 실재 여부 무관)면 다른 판(첫 것) 원문으로 1차(묶음 한 호출)·
        // 2차(항목 하나씩)를 한 번 더 돌린다. **2차 「일치」 ∧ 1차 「불일치」 아님**일 때만 그 판으로 바꿔 초록 + 판 꼬리 「(… 시행 판)」(이 길만 D2 예외 —
        // 이미 한 번 불일치가 난 항목이라 1차를 초록을 막는 쪽으로만 쓴다), 아니면 첫 판 판정·메모 그대로(주황이면 「현행 판과 대조 — 」 머리). altJudged에 남긴다.
        // 표지(번호·시행일·낱말)가 고른 판의 불일치는 답의 판 표기 오류라 재판정하지 않는다 — 「현행 ② 글 그대로 + (법률 제21553호)」가 vbSkip으로 시행예정판과
        // 대조돼 불일치인데 다른 판(현행)에서 일치하면 번호째 초록이 됐다(판정 §3-2 반례 1, 사내 재현). 두 판 다중 원문(verDocs)·조문 여럿(multi)은 하지 않는다.
        // 2차가 두 번 다 실패하면 초록이 아니다(사내 _judge_gate는 그때 1차 일치로 초록 — 다른 점, 사내에 알림).
        const alts = [];
        toJudge.forEach(function (r, i) {
          if (r.altDocs && r.altDocs.length && !r.multi && !r.verDocs && String(r.verMark || '').split('+')[0] === 'none' && r.judge2 && r.judge2.verdict === '불일치') alts.push({ r: r, it: items[i] });
        });
        if (alts.length) {
          const its2 = alts.map(function (a, k) { const t = a.r.altDocs[0].text; return Object.assign({}, a.it, { id: k + 1, source: t.length > 4000 ? t.slice(0, 4000) + '\n…(이하 생략)' : t }); });
          const both2 = await Promise.all([
            judgeCitations(its2, args.callHaiku).then(function (v) { return { v: v }; }, function (e) { return { err: String(e && e.message || e) }; }),
            judgeEachSecond(its2, args.callJudge2),
          ]);
          alts.forEach(function (a, k) {
            const r = a.r, alt = r.altDocs[0];
            const v1 = both2[0].v ? both2[0].v[String(k + 1)] : null, s = both2[1][k], v2 = s && s.v ? s.v : null;
            const ok = !!(v2 && v2.verdict === '일치' && !(v1 && v1.verdict === '불일치'));
            // 다른 판 결과의 상태(기록용) — 관문과 같은 규칙: 불일치+구절 실재 → mismatch(추측 법령이면 setMismatch처럼 회색), 일치인데 1차 불일치 → unclear
            let st = ok ? 'ok' : 'unclear';
            if (v2 && v2.verdict === '불일치' && v2.grounded) {
              const tmp = { lawGuess: r.lawGuess, guessEvidence: r.guessEvidence, guessLabel: r.guessLabel };
              setMismatch(tmp, v2.reason); st = tmp.status;
            } else if (!v2) st = 'unjudged';
            r.altJudged = { doc: alt.doc, status: st, judge: v1 ? v1.verdict : null, judge2: v2 ? v2.verdict : null, reason: (v2 && v2.reason) || (s && s.err) || null };
            if (ok) { r.status = 'ok'; r.reason = null; r.doc = alt.doc; r.text = alt.text; delete r.guessGrey; }
          });
        }
      }
    }
    // 판이 둘 이상인 조문의 주황은 어느 판과 대조했는지 메모 머리에 적는다(② — 사내와 같은 글자 「현행 판과 대조 — 」·「시행예정 판과 대조 — 」·「현행·시행예정 두 판과 대조 — 」).
    // 같은 조의 다른 판이 있다는 사실과 어느 판을 봤는지는 읽는 사람이 알아야 직접 확인할 판을 고른다.
    for (const r of results) {
      if (r.status === 'mismatch' && ((r.altDocs && r.altDocs.length) || r.verDocs)) {
        r.reason = (r.verDocs ? '현행·시행예정 두 판과 대조 — ' : (r.verPending || []).indexOf(r.doc) !== -1 ? '시행예정 판과 대조 — ' : '현행 판과 대조 — ') + String(r.reason || '');
      }
    }
    let out = answer, changed = 0, quoteTagged = 0, filled = 0;
    const cut = function (r) {   // 표시를 지운다(앞 공백 하나 포함)
      const lead = /\s$/.test(out.slice(0, r.tagStart)) ? r.tagStart - 1 : r.tagStart;
      out = out.slice(0, lead) + out.slice(r.tagEnd);
    };
    for (const r of results.slice().reverse()) {
      // 표시 안 글자(모델이 적은 대상)와 판정기가 실제로 대조한(찾은) 조문(cmp) — 바뀐 표시는 cmp를 적고, 둘이 다르면 「(표시: …)」(#286-보론)
      const inner = String(r.tag).replace(QUOTE_MARK, '').slice(1, -1).replace(/^원문\s*확인됨/, '').replace(OUTSIDE_HEAD_RE, '').replace(/^[\s:：—\-–,]+/, '').trim();
      const tgt = r.tagTarget ? inner : '';
      const fam = r.lawDoc || (r.doc ? docFamily(r.doc) : '');
      let cmpPlain = cmpLabelOf(r, false), cmp = cmpLabelOf(r, true);
      // 이름을 적었는데 자료에 그 법령이 없어 못 찾은 것(#240 ①)은 찾아본 조문 이름표가 「시행령 제24조」처럼 토막이 된다 — 모델이 적은 대상 그대로
      if (r.status === 'missing' && !fam && tgt && !r.lawGuess) { cmpPlain = tgt; cmp = tgt; }
      const notes = [];
      // 원문 없음은 「검색 자료에 <조문> 없음」 뒤 괄호에 법령 추측을 적는다(앞에 붙이면 「검색 자료에 법령 이름 없음 → …」로 읽혀 어색)
      if (r.status === 'missing' && r.lawGuess) {
        const gfam = fam || String(r.guessLabel || r.lookFor || '').split(/\s제\d/)[0].trim();
        if (gfam) notes.push(guessPrefix(r.lawGuess) + withRo(gfam) + ' 봄');
      }
      // §5(#288): 항 구분 없는 조문에 제N항 — 호가 있는 조문이면 번호를 호로 뜻했을 수 있다
      if (r.nopara) { notes.push('조문에 항 구분 없음(제' + r.nopara.n + '항 표기)'); if (r.nopara.items) notes.push('제' + r.nopara.n + '호를 뜻했을 수 있음'); }
      if (r.srcFetched === 'db' && r.status !== 'ok') notes.push('검색 자료 밖 조문');   // ⓒ(#288)로 받은 조문과 대조한 결과
      if (r.status === 'missing' && r.numAmbig) notes.push('번호가 같은 고시 ' + r.numAmbig + '개 — 어느 것인지 몰라 대조하지 않음');   // ⓑ(#288)
      if (r.status === 'missing' && r.addAmbig) notes.push('부칙 번호 없음 — 자료에 이 법령 부칙 ' + r.addAmbig + '개');   // 번호 없이 적은 부칙 조(#290 ③)
      if (r.status !== 'ok' && tgt && cmpPlain !== tgt && shownDiffers(tgt, r, fam)) notes.push('표시: ' + tgt);
      // ⓒ(#286) 추측한 조문에 인용문 낱말이 없어 회색이 된 「불일치」 — 무엇과 대조하면 다른지까지 적는다(고시 번호 추측은 그 까닭을)
      const cmpG = r.status === 'missing' ? cmpPlain : (r.guessGrey && cmp ? withWa(cmp) + ' 대조하면 다름(' + (r.lawGuess === 'number' ? '같은 번호의 다른 고시일 수 있음'
        : !r.lawGuess && r.multiWeakGuess ? '법령을 추측한 ' + r.multiWeakGuess + '에 인용문 낱말이 없음' : '인용문 낱말이 그 조문에 없음') + ')' : cmp);
      // 초록의 머리 — 검색 자료 밖 조문(ⓒ)과 대조해 확인된 것은 출처를 숨기지 않는다(「[원문 확인됨(검색 자료 밖 조문과 대조): …]」)
      const okHead = r.srcFetched === 'db' ? OUTSIDE_TAG_HEAD : '[원문 확인됨: ';
      // 초록인데 대조한 판이 현행(표지 없을 때의 판)이 아니면 이름표에 판을 적는다 — 「[원문 확인됨: 전파법 제24조제2항(2026.10.22 시행 판)]」(②, 사내와 같은 글자)
      const verTail = (r.status === 'ok' && r.verDefault && r.doc && r.doc !== r.verDefault && !r.verDocs && r.kind === 'article' && cmpPlain) ? versionTail(r.doc) : '';
      if (r.auto) {
        // 기계가 붙인 인용 대조 표시(#230): 대조할 것이 없던 것은 흔적 없이 지우고, 확인된 것은 법령명을 채워 남긴다
        if (r.status === 'dup' || r.status === 'unparsed' || r.status === 'noclaim') { cut(r); continue; }
        quoteTagged++;
        if (r.status === 'ok') {
          const law = r.lawDoc || (r.doc ? docFamily(r.doc) : '');
          // 약한 이름을 맞춘 표시(「…가이드라인」 제1조)는 낫표를 떼고, 문서 이름이 이미 적혀 있으면 두 번 붙이지 않는다
          const tg = tgt.replace(/^「([^」]+)」\s*/, '$1 ');
          const named = (!!law && tg.indexOf(law + ' ') === 0) || (/(법|법률|령|규칙|고시|규정|기준|세칙|지침)\s/.test(tg + ' ') && !/^동법\s/.test(tg));
          const label = law && !named ? law + ' ' + tg.replace(/^동법\s*/, '') : tg;
          out = out.slice(0, r.tagStart) + okHead + (verTail ? cmpPlain + verTail : label) + ']' + out.slice(r.tagEnd);
          continue;
        }
        out = out.slice(0, r.tagStart) + buildTag(r.status, r.reason, cmpG, notes) + out.slice(r.tagEnd); changed++;
        continue;
      }
      if (r.status === 'ok') {
        // 초록: 법령 이름 없는 표시(「[원문 확인됨]」·「[원문 확인됨: 제19조제1항]」·「동법 제N조」)는 대조한 조문으로 채운다(#286-보론, 운영자 결정) —
        // 이름이 있으면 모델 글자 그대로(글자 그대로 일치가 번호 오기를 바로잡은 #155-보론6도 그대로). 별표 표시는 건드리지 않는다.
        if (r.srcFetched === 'db') { out = out.slice(0, r.tagStart) + okHead + (verTail ? cmpPlain + verTail : tagNamesLaw(inner) ? inner : cmpPlain) + ']' + out.slice(r.tagEnd); filled++; }
        else if (verTail) { out = out.slice(0, r.tagStart) + '[원문 확인됨: ' + cmpPlain + verTail + ']' + out.slice(r.tagEnd); filled++; }
        else if (r.kind === 'article' && cmpPlain && !tagNamesLaw(inner)) { out = out.slice(0, r.tagStart) + '[원문 확인됨: ' + cmpPlain + ']' + out.slice(r.tagEnd); filled++; }
        continue;
      }
      // 나머지는 회색 「원문 미확인 — <이유>」 표시(#292, 종전 세 상태 #176)로 바꾸고, 중복(dup)은 지운다.
      if (r.status === 'dup') { cut(r); changed++; continue; }
      out = out.slice(0, r.tagStart) + buildTag(r.status, r.reason, cmpG, notes) + out.slice(r.tagEnd); changed++;
    }
    // 답변이 실제로 인용해 확인된 문서 — 출처 목록을 이 순서로 앞세우는 데 쓴다(#176)
    const citedDocs = [];
    for (const r of results) {
      if (r.status !== 'ok') continue;
      for (const d of r.multi ? r.multi.map(function (x) { return x.doc; }) : [r.doc]) if (d && citedDocs.indexOf(d) === -1) citedDocs.push(d);
    }
    // 지운 기계 표시는 기록에서도 뺀다(판정 대상이 아니었다)
    const kept = results.filter(function (r) { return !(r.auto && (r.status === 'dup' || r.status === 'unparsed' || r.status === 'noclaim')); });
    return {
      answer: out, changed: changed, filled: filled, autoTagged: at.added, quoteTagged: quoteTagged, citedDocs: citedDocs,
      verdicts: kept.map(function (r) {
        // kind: 부칙 조·단위 표시는 'addendum'(#290 ⑨ — 배포 뒤 끄는 조건 「부칙 표시의 거짓 원문 없음·거짓 주황」을 셀 근거)
        const v = { tag: String(r.tag).replace(QUOTE_MARK, ''), kind: r.kind === 'article' && isAddendumKey(r.key) ? 'addendum' : r.kind, key: r.key || (r.kind === 'annex' ? (r.annexType || '별표') + (r.annex ? ' ' + r.annex : '') : null), law: r.lawDoc || r.lawText || null,
          paras: r.paras || [], items: r.items || [], status: r.status, reason: r.reason || null, judge: r.judge || null, doc: r.doc || null,
          verbatim: !!r.verbatim, overlap: typeof r.overlap === 'number' ? Math.round(r.overlap * 100) / 100 : null, cmp: cmpLabelOf(r, false) || null };
        if (r.auto) v.auto = 'quote';
        if (r.judge2) v.judge2 = r.judge2;                    // 2차 판정(#284부터 판정 대상 전부, #280은 1차 불일치만) — 1·2차가 갈린 건수를 나중에 셀 수 있게
        if (r.judge2Error) v.judge2Error = r.judge2Error.slice(0, 200);   // 2차가 두 번 다 실패 → 1차 결과로 물러남
        if (r.srcPrompt) v.srcPrompt = r.srcPrompt;           // 판정 원문 출처(#284): swap 지침서 대신 실DB 조문 · kept 지침서 글 · failed 못 받음(회색)
        if (r.lawGuess) { v.lawGuess = r.lawGuess; v.guessEvidence = !!r.guessEvidence; v.guessLabel = r.guessLabel || null; }   // 이름 없는 참조의 법령 추측(#286, number #288)
        if (r.multi) v.multi = r.multi.map(function (x) { return articleLabel(x.lawDoc || docFamily(x.doc), x.key, x.paras, x.items); });   // 다중 원문(#288 ⓓ′)
        if (r.nopara) v.nopara = r.nopara.n;                  // 항 구분 없는 조문에 제N항(#288 §5)
        // 검색 자료 밖 조문 대조(#288 ⓒ, 10-12 집계용): db 받아 대조함 · nodoc DB 문서명 유일 일치 없음 · norows 그 조문·판 없음 · cap 상한 · partial 받은 조문에도 항·호 없음 · error 조회 실패
        if (r.srcFetched) v.srcFetched = r.srcFetched;
        // ② 판(2026-10-09, 사내와 같은 열쇠 + 외부 want): mark 표지 종류 · default 표지 없을 때의 판 · alt 다른 판 · both 두 판 다중 원문 ·
        // fetched DB에서 판 받기(db·same·cap·error) · want 자료에 판이 하나뿐인데 표지가 다른 판을 가리킴(number·date·word — 외부 전용)
        const want = r.verWant || (r.verFetch && r.verFetch.want) || null;
        if (r.verMark || r.verFetched || want) {
          const ver = {};
          if (r.verMark) ver.mark = r.verMark;
          if (r.verDefault) ver.default = r.verDefault;
          if (r.altDocs && r.altDocs.length) ver.alt = r.altDocs.map(function (a) { return a.doc; });
          if (r.verDocs) ver.both = r.verDocs;
          if (r.verFetched) ver.fetched = r.verFetched;
          if (want) ver.want = want;
          v.ver = ver;
        }
        if (r.altJudged) v.altJudged = r.altJudged;            // ② 다른 판 재판정(규칙 B, 2026-10-10): doc·status·1차·2차 verdict·메모 — 사내 alt_judged와 같은 칸
        if (r.closedBefore) v.closedBefore = true;              // ③ closed-before 줄(S6, 10-21 집계용 — 회색 「자동 대조 못 함」 + 다음 문단 낫표 인용 꼴을 셀 근거)
        return v;
      }),
    };
  }

  const CiteVerify = {
    TAG_UNVERIFIED: TAG_UNVERIFIED, TAG_MISSING: TAG_MISSING, TAG_MISMATCH: TAG_MISMATCH, TAG_UNCHECKED: TAG_UNCHECKED, buildTag: buildTag,
    articleKey: articleKey, docFamily: docFamily, mergeChunkTexts: mergeChunkTexts,
    // 부칙 열쇠(#290) — rag_core.js 경과조치 덧붙이기(L8)도 같은 단위 읽기·조 머리 자르기를 쓴다
    isAddendumKey: isAddendumKey, addendumUnitOf: addendumUnitOf, parseAddKey: parseAddKey, keyText: keyText,
    addendumArticles: addendumArticles, addendumSlice: addendumSlice, addendumBefore: addendumBefore,
    expandArticles: expandArticles, pseudoChunksFromPrompt: pseudoChunksFromPrompt,
    buildCitingExcerpts: buildCitingExcerpts, citeRegex: citeRegex, excerptAround: excerptAround,
    isOtherLawRef: isOtherLawRef, isSanctionTitle: isSanctionTitle, selfCiteIndexes: selfCiteIndexes, sanctionExcerpt: sanctionExcerpt,
    tagUntaggedQuotes: tagUntaggedQuotes, introCiteLabel: introCiteLabel, QUOTE_MARK: QUOTE_MARK, stripCiteBody: stripCiteBody,
    lawNameBefore: lawNameBefore, familyMatches: familyMatches, resolveLaw: resolveLaw, lawScope: lawScope, quoteOverlap: quoteOverlap,
    parseSegment: parseSegment, findCitations: findCitations, checkCitation: checkCitation,
    judgeCitations: judgeCitations, verifyCitations: verifyCitations, autoTagVerbatim: autoTagVerbatim,
    JUDGE_SYSTEM: JUDGE_SYSTEM, JUDGE2_SYSTEM: JUDGE2_SYSTEM, judgeCitations2: judgeCitations2, spanIn: spanIn,
    JUDGE2_MODEL: JUDGE2_MODEL, JUDGE2_REQUEST: JUDGE2_REQUEST, JUDGE2_MAX_TOKENS: JUDGE2_MAX_TOKENS,
    JUDGE2_CONCURRENCY: JUDGE2_CONCURRENCY, judgeEachSecond: judgeEachSecond, swapPromptArticles: swapPromptArticles, isPromptDoc: isPromptDoc,
    guessKind: guessKind, isGuessedRef: isGuessedRef, isBoilerplateArticle: isBoilerplateArticle, claimRelevance: claimRelevance, relEvidence: relEvidence,
    REL_MIN_HITS: REL_MIN_HITS, REL_MIN_SCORE: REL_MIN_SCORE,
    withWa: withWa, articleLabel: articleLabel, cmpLabelOf: cmpLabelOf, tagNamesLaw: tagNamesLaw, shownDiffers: shownDiffers,
    guessPrefix: guessPrefix, pickVersion: pickVersion, LAW_DOC_NAME_RE: LAW_DOC_NAME_RE, OUTSIDE_TAG_HEAD: OUTSIDE_TAG_HEAD,
    // ② 판 고르기·③ closed-before·④ 종류 낱말 이어받기(#294, 2026-10-09 사내 선행 이식)
    versionMarks: versionMarks, versionWanted: versionWanted, versionHead: versionHead, versionTail: versionTail, stripRefBody: stripRefBody,
    suffixPick: suffixPick, suffixFits: suffixFits, namedLawsIn: namedLawsIn,
    OUTSIDE_MAX: OUTSIDE_MAX, MULTI_MAX: MULTI_MAX, MULTI_SRC_MAX: MULTI_SRC_MAX,
  };
  root.CiteVerify = CiteVerify;
  if (typeof module !== 'undefined' && module.exports) module.exports = CiteVerify;
})(typeof globalThis !== 'undefined' ? globalThis : this);
