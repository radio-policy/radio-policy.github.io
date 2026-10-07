// node tests/issue_news_body.test.js — 이슈맵 기사 본문 읽기 보기(app.js _newsBodyParts·_issueNewsTerms·_nbMarkRelevant·_nbBoldHtml) 검증
//   (2026-10-07, 프레임워크·네트워크 없음). 예문은 실제 수집 본문의 꼴(공유 버튼 글자·기자 줄·사진 설명·1,500자 잘림·메뉴 글자)을
//   본떠 지어낸 문장이다 — 공개 저장소라 기사 원문은 넣지 않는다.
var fs = require('fs');
var path = require('path');
var appSrc = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');

function grabFn(name) {
  var i = appSrc.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('app.js에 없음: ' + name);
  var j = appSrc.indexOf('{', i);
  for (var k = j, d = 0; k < appSrc.length; k++) {
    if (appSrc[k] === '{') d++;
    else if (appSrc[k] === '}') { d--; if (d === 0) return appSrc.slice(i, k + 1); }
  }
  throw new Error('괄호 짝 없음: ' + name);
}
function grabVar(name) {
  var m = appSrc.match(new RegExp('var ' + name + ' = ([\\s\\S]*?);[ \\t]*(?://[^\\n]*)?\\n'));
  if (!m) throw new Error('app.js에 없음: ' + name);
  return 'var ' + name + ' = ' + m[1] + ';';
}
var FNS = ['_nbNorm', '_nbSentences', '_newsBodyParts', '_nbWordSet', '_nbTokens', '_issueNewsTerms', '_nbHas', '_nbMarkRelevant', '_nbTitleMismatch', '_nbBoldHtml'];
var VARS = ['_NB_JUNK', '_NB_TAIL', '_NB_BYLINE', '_NB_PHOTO', '_NB_CAPTION_END', 'NB_BODY_MAX', '_NB_STOP', '_NB_ALIAS', '_NB_VERBY', 'NB_REL_LIGHT'];
function escHtml(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
var src = FNS.map(grabFn).concat(VARS.map(grabVar)).join('\n') + '\nreturn {' + FNS.join(',') + '};';
var L = new Function('escHtml', src)(escHtml);

var fails = 0, total = 0;
function ok(name, cond, extra) {
  total++;
  if (!cond) { fails++; console.log('✗ ' + name + (extra !== undefined ? ' — ' + JSON.stringify(extra) : '')); }
}
function sents(parts) { return parts.paras.map(function(p) { return p.map(function(s) { return (s.cap ? '[사진]' : '') + s.t; }); }); }

// ① 제목 반복·공유 버튼·입력 시각을 떼고, 기자 줄 앞은 머리(부제)로
var p1 = L._newsBodyParts(
  '"가나 통신 해킹 땐 위약금 면제"…구독료·위성 게이트웨이도 도마 가나 식별번호 15년간 노출…12월부터 원격 전환 ' +
  '공유하기 X 카카오톡 페이스북 트위터 복사하기 답글쓰기 2026-10-06 13:59:44 ㅣ 2026-10-06 13:59:44 [다라일보 홍길동 기자] ' +
  '통신 서비스의 보안부터 요금 부담까지 국정감사 도마에 올랐습니다. 정부는 증거 인멸이 확인되면 위약금 면제를 요청하겠다고 했습니다. ' +
  '6일 국회에서 국정감사가 열리고 있다. (사진=마바통신) 위성 게이트웨이가 일본에 있어 데이터가 해외를 거친다는 지적도 나왔습니다. 의원은 "구독료까지 넓혀야',
  '"가나 통신 해킹 땐 위약금 면제"…구독료·위성 게이트웨이...');
// 목록 제목이 「...」로 잘렸으면 원래 제목이 어디서 끝나는지 모른다 — 잘린 낱말 조각(「도」)만 떼고, 원래 제목의 남은 낱말(「도마」)은 남긴 채 앞에 …를 붙인다
ok('① 머리에서 제목·잡음이 빠지고 잘린 낱말 조각을 뗀다', p1.lead === '도마 가나 식별번호 15년간 노출…12월부터 원격 전환', p1.lead);
ok('① 잘린 제목 뒤라 머리 앞에 … 표시', p1.leadCut === true);
ok('① 사진 설명은 따로', JSON.stringify(sents(p1)).indexOf('[사진]6일 국회에서 국정감사가 열리고 있다.') >= 0, sents(p1));
ok('① 사진 출처 표시는 지운다', JSON.stringify(sents(p1)).indexOf('사진=') < 0);
ok('① 문장 중간에서 끝나면 잘림', p1.cut === true);
ok('① 메뉴 글자 아님', p1.junk === false);

// ② 연합뉴스형 기자 줄 + 줄바꿈 본문 + 끝의 관련기사·저작권 줄
var p2 = L._newsBodyParts('(서울=가나뉴스) 홍길동 김철수 기자 = 첫 문단입니다.\n둘째 문단은 여기서 끝납니다.\n관련기사 다른 기사 제목 저작권자 © 가나뉴스 무단전재', '아무 제목입니다 아주 다른 제목');
ok('② 줄바꿈 문단 그대로', JSON.stringify(sents(p2)) === JSON.stringify([['첫 문단입니다.'], ['둘째 문단은 여기서 끝납니다.']]), sents(p2));
ok('② 머리 없음·잘림 아님', p2.lead === '' && p2.cut === false);

// ③ 방송 원고의 [기자]는 기자 줄이 아니다(앵커 멘트가 머리로 숨지 않게)
var p3 = L._newsBodyParts('[앵커] 오늘부터 제재가 강해집니다. [기자] 크게 세 가지입니다.', '방송 기사 제목입니다 길게');
ok('③ [기자]로 머리를 나누지 않음', p3.lead === '' && sents(p3)[0][0] === '[앵커] 오늘부터 제재가 강해집니다.', p3);

// ④ 사이트 메뉴 글자만 수집된 본문
var p4 = L._newsBodyParts('정치 사회 경제 국제 스포츠 로그인 회원가입 전체메뉴 버튼 가요 방송 영화 셀럽 포토 동영상 이슈 종합 검색 기사검색 검색 전체 분야별 최신 오피니언 사설 칼럼 만평', '어떤 제목입니다 열글자넘게');
ok('④ 메뉴 글자는 junk', p4.junk === true);

// ⑤ 이슈 낱말 — 따옴표 묶음 3점·제목 2점·정의 첫 문장 1점, 조사·서술어·흔한 낱말 제외
var t5 = L._issueNewsTerms({ title: "정부 '모두의 AI' 사업 선정 경쟁", definition: '정부가 추진하는 전 국민 AI 서비스의 사업자 공모와 심사 절차. 해당: 기타' });
var w5 = {}; t5.forEach(function(o) { w5[o.t] = o.w; });
ok('⑤ 따옴표 묶음은 한 낱말 3점', w5['모두의 AI'] === 3, w5);
ok('⑤ 묶음 밖 제목 낱말 2점, 흔한 낱말(정부·사업·경쟁) 제외', w5['선정'] === 2 && !w5['정부'] && !w5['사업'] && !w5['경쟁'], w5);
ok('⑤ 정의 첫 문장 낱말 1점, 서술어(추진하는) 제외', w5['공모'] === 1 && w5['심사'] === 1 && !w5['추진하는'] && !w5['기타'], w5);

// ⑥ 영문은 낱말 경계로만, 넉 자 합성어는 두 자씩 나뉘어도
ok('⑥ KT는 SKT 안에서 안 맞음', !L._nbHas('SKT가 발표했다', 'KT') && L._nbHas('SKT·KT가 발표했다', 'KT'));
ok('⑥ 증거인멸 ↔ 증거를 인멸', L._nbHas('증거를 인멸했다', '증거인멸') && !L._nbHas('증거를 제출했다', '증거인멸'));

// ⑦ 같은 기사라도 이슈마다 핵심 문장이 다르다 + 약칭(LGU+ ↔ LG유플러스)
var body7 = '[가나일보 홍길동 기자] LGU+가 해킹 뒤 서버를 폐기했다는 의혹이 제기됐습니다. ' +
  '구독료를 통신비 부담 완화 정책에 넣어야 한다는 요금 요구도 나왔습니다. 스타링크 게이트웨이가 일본에 있어 보안 우려가 나왔습니다. ' +
  '의원들은 여러 현안을 두루 물었습니다. 장관은 검토하겠다고 답했습니다.';
var iss7a = { title: 'LG유플러스 해킹 증거인멸 의혹', definition: 'LG유플러스가 해킹 정황 통보 후 서버를 폐기·재설치해 증거를 인멸했다는 의혹. 해당: 수사' };
var iss7b = { title: '저궤도 위성통신 — 스타링크 국내 서비스(해외 게이트웨이)', definition: '해외 저궤도 위성통신의 국내 진입. 해당: 기타' };
function strongOf(issue) {
  var p = L._newsBodyParts(body7, '아무 상관 없는 긴 제목입니다');
  L._nbMarkRelevant(p, L._issueNewsTerms(issue));
  var out = [];
  p.paras.forEach(function(pp) { pp.forEach(function(s) { if (s.rel === 2) out.push(s.t.slice(0, 8)); }); });
  return out;
}
ok('⑦ 해킹 이슈 → 해킹 문장만', JSON.stringify(strongOf(iss7a)) === JSON.stringify(['LGU+가 해킹']), strongOf(iss7a));
ok('⑦ 위성 이슈 → 스타링크 문장만', JSON.stringify(strongOf(iss7b)) === JSON.stringify(['스타링크 게이트']), strongOf(iss7b));

// ⑦-2 거의 모든 문장에 나오는 제목 낱말은 점수에서 빼고(wide) 안내용으로 돌려준다
var p72 = L._newsBodyParts('[가나일보 홍길동 기자] 서울 요금이 가장 비쌌다. 도쿄 요금은 낮았다. 뉴욕 요금은 서울과 비슷했다. 런던 요금도 조사했다. 파리는 따로 봤다.', '요금 비교 기사 제목입니다 길게');
var r72 = L._nbMarkRelevant(p72, L._issueNewsTerms({ title: '5G·LTE 통합요금제와 요금 규제', definition: '' }));
ok('⑦-2 요금은 wide, 강조 0', JSON.stringify(r72.wide) === '["요금"]' && r72.strong === 0, r72);

// ⑦-3 다른 기사 본문 — 제목 낱말이 하나도 없으면 경고, 하나라도 있으면 아님
var p73 = L._newsBodyParts('[가나일보 홍길동 기자] 수입 전기차가 올해 판매 1위를 노리고 있다. 국산 SUV와의 격차가 좁혀졌다.', '계정 정보 유출 사업자 국감서 질타…보안 투자 약속');
ok('⑦-3 제목 낱말 0 → 경고', L._nbTitleMismatch('계정 정보 유출 사업자 국감서 질타…보안 투자 약속', p73) === true);
ok('⑦-3 하나라도 있으면 경고 안 함', L._nbTitleMismatch('전기차 판매 경쟁 국감서 질타…보안 투자 약속', p73) === false);

// ⑧ 굵게 — 맞은 낱말의 어절(괄호 앞까지)을 굵게, 나머지는 이스케이프
var b8 = L._nbBoldHtml('<i>LG유플러스(032640)는 게이트웨이를', ['LG유플러스', '게이트웨']);
ok('⑧ 어절 굵게 + 이스케이프', b8 === '&lt;i&gt;<b style="font-weight:700">LG유플러스</b>(032640)는 <b style="font-weight:700">게이트웨이를</b>', b8);
ok('⑧ 겹치는 표시는 한 번만', (L._nbBoldHtml('통합요금제 요금', ['요금', '통합요금제']).match(/<b /g) || []).length === 2);

console.log((fails ? '실패 ' + fails : '모두 통과') + ' (' + (total - fails) + '/' + total + ')');
process.exit(fails ? 1 : 0);
