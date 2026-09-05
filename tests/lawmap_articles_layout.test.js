// node tests/lawmap_articles_layout.test.js — 프레임워크 없음
var path = require('path');
var L = require(path.join(__dirname, '..', 'lawmap_articles.js'));
var fails = 0, total = 0;
function check(name, cond, info) {
  total++;
  console.log((cond ? 'ok   ' : 'FAIL ') + name + (cond || info == null ? '' : '  ' + info));
  if (!cond) fails++;
}
// 결정적 난수(LCG)
var seed = 20260905;
function rnd(n) { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed % n; }

var TYPES = ['law', 'decree', 'rules', 'notice', 'etc'];
var MARGIN = 24, CLEAR = 90;
function distOrigin(r) {
  var dx = Math.max(r.x, 0, -(r.x + r.w)), dy = Math.max(r.y, 0, -(r.y + r.h));
  return Math.sqrt(dx * dx + dy * dy);
}

// (a)(b)(c) 상자 1~8개 × 반복
for (var bc = 1; bc <= 8; bc++) {
  for (var rep = 0; rep < 5; rep++) {
    var boxes = [];
    for (var i = 0; i < bc; i++) {
      var items = [];
      var cnt = 1 + rnd(6);
      for (var j = 0; j < cnt; j++) items.push({ id: 'b' + i + '_a' + j, label: (10 + j) + '조 예시 조문 제목', primary: j === 0 });
      boxes.push({ id: 'box' + i, label: '법령 ' + i, type: TYPES[i % TYPES.length], items: items });
    }
    var res = L.lmaLayout(boxes, { topicClearance: CLEAR, topicId: 'T' });
    var tag = 'boxes=' + bc + ' rep=' + rep;
    var overlap = false, tooClose = false, outside = [], missing = [];
    for (var a = 0; a < res.rects.length; a++) {
      if (distOrigin(res.rects[a]) < CLEAR) tooClose = true;
      for (var b = a + 1; b < res.rects.length; b++) if (L.lmaRectsOverlap(res.rects[a], res.rects[b], MARGIN)) overlap = true;
    }
    check(tag + ' rects count', res.rects.length === bc);
    check(tag + ' no overlap (radius=' + res.radius + ')', !overlap);
    check(tag + ' topic clearance', !tooClose);
    boxes.forEach(function (bx) {
      var r = res.rects.filter(function (q) { return q.id === bx.id; })[0];
      bx.items.forEach(function (it) {
        var p = res.positions[it.id];
        if (!p) { missing.push(it.id); return; }
        if (!(p.x > r.x && p.x < r.x + r.w && p.y > r.y && p.y < r.y + r.h)) outside.push(it.id);
        if (!(res.hints[it.id] && res.hints[it.id].labelBelow)) missing.push(it.id + ':hint');
      });
      // (c) 상자 중심 히트
      var hit = L.lmaHitRect(res.rects, r.x + r.w / 2, r.y + r.h / 2);
      if (!hit || hit.id !== bx.id) outside.push('hit:' + bx.id);
    });
    check(tag + ' items inside own rect', outside.length === 0 && missing.length === 0, JSON.stringify({ outside: outside, missing: missing }));
    check(tag + ' topic position', res.positions.T && res.positions.T.x === 0 && res.positions.T.y === 0);
    check(tag + ' hit far away null', L.lmaHitRect(res.rects, 99999, 99999) === null);
  }
}
check('empty boxes', L.lmaLayout([]).rects.length === 0);

// (d) 문자열 도우미
check('edgeLabel cross-law', L.lmaEdgeLabel('37조의2', '③', '사업법', '38조') === '37조의2③ → 사업법 38조', L.lmaEdgeLabel('37조의2', '③', '사업법', '38조'));
check('edgeLabel same-law', L.lmaEdgeLabel('27조의2', 4, null, '37조') === '27조의2④ → 37조', L.lmaEdgeLabel('27조의2', 4, null, '37조'));
check('edgeLabel no para', L.lmaEdgeLabel('27조', null, '', '37조') === '27조 → 37조');
check('short 사업법', L.lmaShortLawName('전기통신사업법') === '사업법');
check('short 방발법', L.lmaShortLawName('방송통신발전 기본법') === '방발법');
check('short 망법', L.lmaShortLawName('정보통신망 이용촉진 및 정보보호 등에 관한 법률') === '망법');
check('short 전파법', L.lmaShortLawName('전파법') === '전파법');
check('short 시행령', L.lmaShortLawName('전기통신사업법 시행령') === '사업법 영', L.lmaShortLawName('전기통신사업법 시행령'));
check('short 시행규칙', L.lmaShortLawName('방송통신발전 기본법 시행규칙') === '방발법 규칙');
check('short 전파법 시행령', L.lmaShortLawName('전파법 시행령') === '전파법 영');
check('short fallback long', L.lmaShortLawName('재난 시 무선통신시설 공동이용 범위 및 절차에 대한 고시') === '재난 시 무…', L.lmaShortLawName('재난 시 무선통신시설 공동이용 범위 및 절차에 대한 고시'));
check('short fallback short', L.lmaShortLawName('주파수분배표') === '주파수분배표');
var w = L.lmaWrapLabel('37조의2 재난 시 무선통신시설의 공동이용', 14);
check('wrap lines <=14', w.split('\n').every(function (l) { return l.length <= 14; }), JSON.stringify(w));
check('wrap keeps words', w.replace(/\n/g, ' ') === '37조의2 재난 시 무선통신시설의 공동이용', JSON.stringify(w));
check('wrap short unchanged', L.lmaWrapLabel('38조 통신재난') === '38조 통신재난');
var lw = L.lmaWrapLabel('가나다라마바사아자차카타파하가나다라', 8);
check('wrap hard-break long word', lw.split('\n').every(function (l) { return l.length <= 8; }), JSON.stringify(lw));
check('hexToRgba', L.lmaHexToRgba('#2ea060', 0.1) === 'rgba(46,160,96,0.1)', L.lmaHexToRgba('#2ea060', 0.1));

// lmaDrawBoxes: 가짜 ctx로 호출 회귀(캡션 잘라내기 포함)
var calls = [];
var fakeCtx = { save: function () {}, restore: function () {}, beginPath: function () {}, moveTo: function () {}, arcTo: function () {},
  closePath: function () {}, fill: function () {}, stroke: function () {}, measureText: function (s) { return { width: s.length * 12 }; },
  fillText: function (s) { calls.push(s); } };
L.lmaDrawBoxes(fakeCtx, [{ id: 'x', label: '매우매우매우매우긴법령이름입니다', type: 'law', x: 0, y: 0, w: 120, h: 80 }]);
check('drawBoxes truncates caption', calls.length === 1 && /…$/.test(calls[0]) && calls[0].length * 12 <= 100, JSON.stringify(calls));

console.log('\n' + (total - fails) + '/' + total + ' passed');
process.exit(fails ? 1 : 0);
