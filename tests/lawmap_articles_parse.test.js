// node tests/lawmap_articles_parse.test.js — lawmap_articles.js 순수 함수 검증 (프레임워크 없음)
var fs = require('fs');
var path = require('path');
var vm = require('vm');

var src = fs.readFileSync(path.join(__dirname, '..', 'lawmap_articles.js'), 'utf8');
vm.runInThisContext(src);   // 전역 함수로 로드 (module은 미정의 → exports 분기 건너뜀)

var fails = 0, total = 0;
function eq(name, got, want) {
  total++;
  var g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { console.log('ok    ' + name); }
  else { fails++; console.log('FAIL  ' + name + '\n      got  ' + g + '\n      want ' + w); }
}
function has(name, arr, want) {   // arr에 want(부분 객체)와 일치하는 원소가 있는가
  total++;
  var found = arr.some(function (o) { return Object.keys(want).every(function (k) { return o[k] === want[k]; }); });
  if (found) console.log('ok    ' + name);
  else { fails++; console.log('FAIL  ' + name + '\n      missing ' + JSON.stringify(want) + '\n      in ' + JSON.stringify(arr)); }
}
function none(name, arr, want) {
  total++;
  var found = arr.some(function (o) { return Object.keys(want).every(function (k) { return o[k] === want[k]; }); });
  if (!found) console.log('ok    ' + name);
  else { fails++; console.log('FAIL  ' + name + '\n      unexpected ' + JSON.stringify(want)); }
}

// ── lmaNorm ──
eq('norm 공백·가운뎃점', lmaNorm('방송통신발전 기본법'), '방송통신발전기본법');
eq('norm ㆍ/·', lmaNorm('전기통신설비의 기술기준·ㆍ규칙'), '전기통신설비의기술기준규칙');
eq('norm .pdf', lmaNorm('전파법(법률)(제21553호).pdf'), '전파법(법률)(제21553호)');
eq('norm .MD', lmaNorm('무선설비규칙.MD'), '무선설비규칙');
eq('norm 기관 접두', lmaNorm('(과학기술정보통신부) 무선설비규칙'), '무선설비규칙');
eq('norm null', lmaNorm(null), '');

// ── lmaBasisKeys (지시된 예시) ──
eq('basis 행정절차법', lmaBasisKeys('청문(제22조①3호가)·사전 통지(제21조) — 선정취소(전파법 제15조의2)에 적용', '행정절차법'), ['22조', '21조']);
eq('basis 목록 제6·18조', lmaBasisKeys('등록·양수합병 인가 (제6·18조)', '전기통신사업법'), ['6조', '18조']);
eq('basis 연결부호 상속', lmaBasisKeys('전파법 제37조·제45조·제47조 위임, 제1조', '무선설비규칙'), ['1조']);
eq('basis 법 약칭 위임', lmaBasisKeys('법 제41조제2항 위임', '전기통신설비의 공동사용 등의 기준'), []);
eq('basis 조~조의N', lmaBasisKeys('2년 주기 확인 등 제50조 위임 세부 (제61조~제62조의3)', '정보통신망법 시행령'), ['61조', '62조의3']);
eq('basis 고시 대상 시행령 인용', lmaBasisKeys('중고단말 (제1조, 사업법 시행령 제37조의16·제64조의2제1호 위임)', '중고 이동통신단말장치 안심거래 사업자 인증기준 등에 관한 고시'), ['1조']);
// ── lmaBasisKeys (추가) ──
eq('basis 자기 법명', lmaBasisKeys('전파법 제9조 주파수분배', '전파법'), ['9조']);
eq('basis 범위 67~68', lmaBasisKeys('전파사용료 부과 (제67~68조)', '전파법'), ['67조', '68조']);
eq('basis 조 두 번 범위', lmaBasisKeys('기술기준 (제35조~제38조)', '전파법'), ['35조', '36조', '37조', '38조']);
eq('basis 범위 10 초과 미확장', lmaBasisKeys('(제1~50조)', '전파법'), []);
eq('basis 의N 범위에는 미부착', lmaBasisKeys('(제6·18조의2)', '전파법'), ['6조', '18조']);
eq('basis 중복 제거', lmaBasisKeys('제3조 정의, 제3조 재언급', '전파법'), ['3조']);
eq('basis 항·호 무시', lmaBasisKeys('제3항, 제2호, 제5조', '전파법'), ['5조']);
eq('basis 에 따른 → 교차', lmaBasisKeys('제9조에 따른 세부 기준, 제2조', '주파수분배표 고시'), ['2조']);
eq('basis 콤마는 상속 안 함', lmaBasisKeys('전파법 제9조, 제2조', '주파수분배표 고시'), ['2조']);
eq('basis 대상명 부분 포함', lmaBasisKeys('방송통신발전 기본법 제37조의2', '방송통신발전기본법'), ['37조의2']);
eq('basis 빈 입력', lmaBasisKeys('', '전파법'), []);

// ── lmaExtractCitations ──
var law = '제37조의2(재난 시 무선통신시설의 공동이용 등)\n① 이동통신서비스(「전기통신사업법」 제2조제18호에 따른 이동통신서비스를 말한다. 이하 같다)를 제공하는 주요통신사업자는 … 무선통신시설의 공동이용을 위하여 필요한 조치를 취하여야 한다.\n② 과학기술정보통신부장관은 다음 각 호의 요건에 모두 해당하는 경우 … 명할 수 있다.\n1.  「재난 및 안전관리 기본법」 제38조에 따라 경계 이상의 방송통신재난 경보가 발령된 경우\n2.  …\n③ 제2항에 따른 무선통신시설의 공동이용 대가는 … 「전기통신사업법」 제38조에 따라 다른 전기통신사업자(「전기통신사업법」 제2조제8호의 전기통신사업자를 말한다)와 협정을 체결한 해당연도의 도매제공 대가를 기준으로 하는 것을 원칙으로 한다.';
var c1 = lmaExtractCitations(law, { selfName: '방송통신발전 기본법', selfKey: '37조의2' });
has('cite 사업법 2조 ①', c1, { target: '전기통신사업법', key: '2조', fromPara: '①' });
has('cite 재난안전법 38조 ②', c1, { target: '재난 및 안전관리 기본법', key: '38조', fromPara: '②' });
has('cite 사업법 38조 ③', c1, { target: '전기통신사업법', key: '38조', fromPara: '③' });
has('cite 사업법 2조 ③', c1, { target: '전기통신사업법', key: '2조', fromPara: '③' });
none('cite 제2항 self 없음', c1, { target: 'self' });
eq('cite 총 4건', c1.length, 4);
eq('cite snippet 존재·공백 압축', c1[0].snippet.indexOf('\n') < 0 && c1[0].snippet.length > 0, true);

var dec = '제27조의2(방송통신재난관리책임자의 지정 등)\n① 주요방송통신사업자는 법 제39조의2제1항에 따라 …\n④ 제3항에 따른 통신재난관리 전담부서 및 전담인력이 총괄하는 재난관리 업무는 다음 각 호와 같다.\n1.  법 제35조의3제1항에 따른 통신시설의 등급 분류\n4.  법 제37조에 따른 방송통신설비의 통합 운용과 법 제37조의2에 따른 무선통신시설의 공동이용에 필요한 조치';
var c2 = lmaExtractCitations(dec, { selfName: '방송통신발전 기본법 시행령', selfKey: '27조의2', parentLawName: '방송통신발전 기본법' });
has('cite 법 39조의2 ①', c2, { target: '방송통신발전 기본법', key: '39조의2', fromPara: '①' });
has('cite 법 35조의3 ④', c2, { target: '방송통신발전 기본법', key: '35조의3', fromPara: '④' });
has('cite 법 37조 ④', c2, { target: '방송통신발전 기본법', key: '37조', fromPara: '④' });
has('cite 법 37조의2 ④', c2, { target: '방송통신발전 기본법', key: '37조의2', fromPara: '④' });
none('cite 제3항 self 없음', c2, { target: 'self' });
eq('cite 시행령 총 4건', c2.length, 4);

var misc = '제5조(준용)\n① 「전파법」 제19조 및 같은 법 시행령 제30조, 같은 법 시행규칙 제7조를 준용한다.\n② 영 제12조와 시행규칙 제3조, 규칙 제4조를 따른다.\n③ 제3조 및 제5조에 따른다. 제1항부터 제3항까지의 규정은 제23조의2부터 제23조의4까지에 준용한다.\n④ 이 법 제9조를 따른다.';
var c3 = lmaExtractCitations(misc, { selfKey: '5조', parentLawName: '전파법', parentDecreeName: '전파법 시행령' });
has('cite 「전파법」 19조', c3, { target: '전파법', key: '19조', fromPara: '①' });
has('cite 같은 법 시행령', c3, { target: '전파법 시행령', key: '30조', fromPara: '①' });
has('cite 같은 법 시행규칙', c3, { target: '전파법 시행규칙', key: '7조', fromPara: '①' });
has('cite 영 → parentDecreeName', c3, { target: '전파법 시행령', key: '12조', fromPara: '②' });
has('cite 시행규칙 → 규칙', c3, { target: '규칙', key: '3조', fromPara: '②' });
has('cite 규칙 → 규칙', c3, { target: '규칙', key: '4조', fromPara: '②' });
has('cite bare 제3조 → self', c3, { target: 'self', key: '3조', fromPara: '③' });
none('cite 자기 조문(5조) 제외', c3, { target: 'self', key: '5조' });
has('cite 부터…까지 첫 키만', c3, { target: 'self', key: '23조의2', fromPara: '③' });
none('cite 부터 뒤 조문 건너뜀', c3, { key: '23조의4' });
has('cite 이 법 → self', c3, { target: 'self', key: '9조', fromPara: '④' });
var c4 = lmaExtractCitations('제1조(목적)\n영 제3조 및 법 제2조', {});
has('cite 영 기본값', c4, { target: '영', key: '3조', fromPara: '' });
has('cite 법 기본값·표제 줄 fromPara 빈값', c4, { target: '법', key: '2조', fromPara: '' });
eq('cite 빈 본문', lmaExtractCitations('', {}), []);

// ── lmaKeyLabel / lmaArtNoMatches ──
eq('label', lmaKeyLabel('37조의2'), '제37조의2');
eq('label 이미 제', lmaKeyLabel('제5조'), '제5조');
eq('artno 제19조(제목)', lmaArtNoMatches('제19조(제목)', '19조'), true);
eq('artno 19조(제목)', lmaArtNoMatches('19조(제목)', '19조'), true);
eq('artno 19조의2(…)', lmaArtNoMatches('19조의2(정의)', '19조의2'), true);
eq('artno 19조 vs 19조의2', lmaArtNoMatches('19조(제목)', '19조의2'), false);
eq('artno bare', lmaArtNoMatches('19조', '19조'), true);
eq('artno key에 제', lmaArtNoMatches('제19조(x)', '제19조'), true);
eq('artno null', lmaArtNoMatches(null, '19조'), false);


// ── 나열 상속 (2026-09-06 실측: 사업법 시행령 40조) ──
(function() {
  var t1 = lmaExtractCitations('제40조(상호접속 등에 관한 협정신고 등) ① 법 제38조제5항, 제44조제1항부터 제3항까지의 규정에 따라 신고한다.\n② 그 내용이 법 제35조제3항ㆍ제37조제3항ㆍ제38조의2제3항ㆍ제39조제2항ㆍ제41조제2항 또는 제44조제2항에 적합한지 심사한다.',
    { selfName: '전기통신사업법 시행령', selfKey: '40조', parentLawName: '전기통신사업법' });
  var selfs = t1.filter(function(c) { return c.target === 'self'; });
  var laws = t1.filter(function(c) { return c.target === '전기통신사업법'; }).map(function(c) { return c.key + c.fromPara; }).sort();
  var ok1 = selfs.length === 0 && laws.join(',') === ['38조①','44조①','35조②','37조②','38조의2②','39조②','41조②','44조②'].sort().join(',');
  console.log((ok1 ? 'ok  ' : 'FAIL') + ' list inheritance (law 제N조ㆍ제M조 / 제N조제5항, 제M조)', ok1 ? '' : JSON.stringify(t1));
  total++; if (!ok1) fails++;
  var t2 = lmaExtractCitations('제5조(범위) ① 「전기통신사업법」 제37조에 따른 협정. 제6조에 따른 절차를 따른다.', { selfKey: '5조', parentLawName: '방송통신발전 기본법' });
  var ok2 = t2.some(function(c) { return c.target === '전기통신사업법' && c.key === '37조'; }) && t2.some(function(c) { return c.target === 'self' && c.key === '6조'; });
  console.log((ok2 ? 'ok  ' : 'FAIL') + ' no inheritance across sentence (self 제6조 stays self)', ok2 ? '' : JSON.stringify(t2));
  total++; if (!ok2) fails++;
})();

// ── 별표·별지 인용 (#127) ──
(function() {
  var t = lmaExtractAnnexRefs('제90조(전파사용료의 산정기준 등)\n① 법 제68조제1항 단서에 따라 … 전파사용료는 별표 8에 따라 산정한다.\n② … 산정기준은 별표 9와 같다. 2. … 별표 10과 같다. 3. … 산정은 별표 11과 같다.');
  var keys = t.map(function(r) { return r.key + r.fromPara; }).join(',');
  var ok1 = keys === '별표8①,별표9②,별표10②,별표11②';
  total++; if (!ok1) fails++; console.log((ok1 ? 'ok  ' : 'FAIL') + ' annex refs from 90조', ok1 ? '' : keys);
  var t2 = lmaExtractAnnexRefs('제26조(전파사용료 일시납부신청서) 영 제91조제3항에 따른 전파사용료 일시납부신청서는 별지 제57호서식과 같다.');
  var ok2 = t2.length === 1 && t2[0].key === '별지57';
  total++; if (!ok2) fails++; console.log((ok2 ? 'ok  ' : 'FAIL') + ' 별지 제57호서식 → 별지57', ok2 ? '' : JSON.stringify(t2));
  var t3 = lmaExtractAnnexRefs('제91조(전파사용료의 징수기간 등)\n① 전파사용료는 분기별로 부과ㆍ징수하며, 분기별 징수기간은 별표 11의2와 같다.');
  var ok3 = t3.length === 1 && t3[0].key === '별표11의2' && lmaAnnexLabelOf('별표11의2') === '별표 11의2' && lmaAnnexLabelOf('별지57') === '별지 제57호';
  total++; if (!ok3) fails++; console.log((ok3 ? 'ok  ' : 'FAIL') + ' 별표 11의2 · 라벨', ok3 ? '' : JSON.stringify(t3));
  var ok4 = lmaExtractAnnexRefs('별표 8(전파사용료 산정기준(제90조제1항 관련)) 무선데이터통신 가입자당').length === 0;
  total++; if (!ok4) fails++; console.log((ok4 ? 'ok  ' : 'FAIL') + ' 별표 표제 자신은 제외');
})();

console.log('\n' + (total - fails) + '/' + total + ' passed' + (fails ? ', ' + fails + ' FAILED' : ''));
process.exit(fails ? 1 : 0);
