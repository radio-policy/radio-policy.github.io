// lawmap_articles.js — 법령 관계도 '조문 단위 보기' (파서 + 배치 + 조립). 테스트: node tests/lawmap_articles_*.test.js  (#125)

/* lawmap_articles_parse.js — 관계도용 한국 법령 조문 파서 (의존성 없음, 전역 함수, ES5)
 * lawmap_edge_check.py(own_articles/_expand_keys/art_key/nrm)의 JS 이식 + 조문 본문 내 인용 추출.
 * app.js와 연결(concat)해 쓰거나 node에서 new Function/vm로 로드해 테스트한다.
 */

// "제6조", "제19조의2", "제6·18조", "제67~68조" — 하나의 매치. "제18조의5~제18조의7"의 뒤 항은 별도 매치.
var LMA_ART_RE = /제\s*(\d+(?:\s*[·ㆍ,~∼\-]\s*\d+)*)\s*조(?:\s*의\s*(\d+))?/g;
// 조문 앞 낱말이 법령명으로 끝나는가 (교차 인용 판별)
var LMA_LAWWORD_RE = /([가-힣A-Za-z0-9·ㆍ]*(?:법|법률|령|영|규칙|고시|규정|기준|지침|조례|헌장|협정))\s*$/;
var LMA_LAW_ONLY_SUFFIX = /(?:법|법률|령|규칙)$/;   // 고시·지침이 '…법 제N조'를 자기 조문으로 가질 수는 없다
var LMA_GENERIC_LAWWORDS = { '법': 1, '령': 1, '영': 1, '규칙': 1, '고시': 1, '규정': 1, '기준': 1, '지침': 1 }; // 약칭 → 항상 교차
// 직전 조문에 연결부호(·, ~)로 이어진 조문은 앞 조문 판정을 그대로 따른다 (','는 새 문맥)
var LMA_CONNECT_RE = /[·ㆍ~∼\-]\s*$/;
var LMA_DELEG_AFTER_RE = /^\s*(?:제\d+항|제\d+호|[①-⑳])*\s*(?:의\s*)?(?:위임|에\s*따른|에\s*의한|근거)/;
// "제35조~제38조"(조가 두 번) → "제35~38조"로 접어 범위 확장에 태운다. 뒤가 '의N'이면(제61조~제62조의3) 접지 않는다.
var LMA_RANGE2_RE = /제\s*(\d+)\s*조\s*([~∼\-])\s*제\s*(\d+)\s*조(?!\s*의\s*\d)/g;

/** 이름 대조용 정규화 — 공백·가운뎃점(·/ㆍ) 제거, .pdf/.md 꼬리 제거, "(과학기술정보통신부) " 같은 기관 접두 제거 */
function lmaNorm(s) {
  s = String(s == null ? '' : s).replace(/\.(pdf|md)$/i, '').replace(/^\s*\([^)]*\)\s*/, '');
  return s.replace(/[\s·ㆍ]/g, '');
}

/** '6·18' → ['6조','18조'] ; '67~68' → ['67조','68조'](끝이 시작+10 이내일 때만) ; ('19','2') → ['19조의2'] */
function lmaExpandKeys(nums, ui) {
  var out = [], parts = nums.split(/[·ㆍ,]/), i, part, rng, a, b, n;
  for (i = 0; i < parts.length; i++) {
    part = parts[i].replace(/\s/g, '');
    rng = part.split(/[~∼\-]/);
    if (rng.length === 2 && /^\d+$/.test(rng[0]) && /^\d+$/.test(rng[1])) {
      a = parseInt(rng[0], 10); b = parseInt(rng[1], 10);
      if (a <= b && b <= a + 10) { for (n = a; n <= b; n++) out.push(n + '조'); continue; }
    }
    if (/^\d+$/.test(part)) out.push(part + '조');
  }
  if (ui && out.length === 1) out[0] = out[0] + '의' + ui;   // 목록·범위에는 '의N'을 붙이지 않는다
  return out;
}

/** 주제 엣지 설명에서 대상 문서 자기 조문 키('19조의2' 형태)만 추출 — 다른 법령 인용은 제외. own_articles() 이식 */
function lmaBasisKeys(description, targetName) {
  var text = String(description || '').replace(LMA_RANGE2_RE, '제$1$2$3조');
  var tname = lmaNorm(targetName);
  var own = [], seen = {}, prevEnd = null, prevOwn = null, m, before, after, keys, isOwn, lw, word, i;
  var re = new RegExp(LMA_ART_RE.source, 'g');
  while ((m = re.exec(text)) !== null) {
    before = text.slice(0, m.index);
    after = text.slice(m.index + m[0].length);
    keys = lmaExpandKeys(m[1], m[2]);
    if (prevEnd !== null && prevOwn !== null && LMA_CONNECT_RE.test(text.slice(prevEnd, m.index))) {
      isOwn = prevOwn;                       // "전파법 제37조·제45조" — 뒤 조문도 전파법 것
    } else if (LMA_DELEG_AFTER_RE.test(after)) {
      isOwn = false;                         // "제50조 위임", "제9조에 따른" — 상위법 조문
    } else {
      lw = LMA_LAWWORD_RE.exec(before);
      if (lw) {
        word = lmaNorm(lw[1]);
        if (!word || LMA_GENERIC_LAWWORDS[word]) isOwn = false;            // "법 제N조", "영 제N조" — 상위법 약칭
        else if (LMA_LAW_ONLY_SUFFIX.test(word) && !LMA_LAW_ONLY_SUFFIX.test(tname)) isOwn = false; // 대상이 고시·지침
        else isOwn = word.indexOf(tname) >= 0 || tname.indexOf(word) >= 0; // 대상 노드명(또는 일부)이면 자기 조문
      } else {
        isOwn = true;
      }
    }
    if (isOwn) for (i = 0; i < keys.length; i++) { if (!seen[keys[i]]) { seen[keys[i]] = 1; own.push(keys[i]); } }
    prevEnd = m.index + m[0].length; prevOwn = isOwn;
  }
  return own;
}

/**
 * 조문 본문에서 조문 인용 추출 → [{ target, key, fromPara, snippet }]
 *   target: 「…」로 명시된 법령명 / '같은 법(시행령|시행규칙)' → 직전 「」명(+접미) / 맨 '법' → ctx.parentLawName('법')
 *           / '영'·'시행령' → ctx.parentDecreeName('영') / '규칙'·'시행규칙' → '규칙' / 법령 낱말 없는 제N조 → 'self'
 *   제한: "제23조의2부터 제23조의4까지"는 첫 키만 기록('부터' 뒤 조문은 건너뜀). 「」 없이 쓴 복합 법령명("방송통신발전 기본법 제N조")은
 *   마지막 낱말('기본법')만 target이 된다 — 법령 본문은 타법을 「」로 쓰므로 실무상 드물다.
 */
function lmaExtractCitations(content, ctx) {
  ctx = ctx || {};
  var text = String(content || '');
  var out = [], seen = {}, m, before, keys, target, lw, word, para, snip, i, k, bm, opens, closes;
  var prevEnd = -1, prevTarget = null, gap;
  // 나열 상속: "법 제35조제3항ㆍ제37조제3항ㆍ제38조의2제3항" / "법 제38조제5항, 제44조제1항" — 항·호 꼬리와 연결부호(·ㆍ, 및 또는)만
  //   사이에 있으면 뒤 조문도 앞 조문과 같은 법령의 것. (없으면 뒤 조문이 'self'로 잡혀 시행령 40조가 자기 44조를 인용한 것처럼 보였다)
  var LMA_LIST_GAP_RE = /^(?:\s*(?:제\s*\d+\s*항|제\s*\d+\s*호|[①-⑳]|의\s*\d+)\s*)*\s*(?:[·ㆍ,]|및|또는|\/)\s*(?:각\s*)?$/;
  var re = new RegExp(LMA_ART_RE.source, 'g');
  while ((m = re.exec(text)) !== null) {
    if (m.index === 0) continue;                                   // 조문 표제("제37조의2(…)") 자신
    before = text.slice(0, m.index);
    if (/부터\s*$/.test(before)) continue;                         // "제23조의2부터 제23조의4까지"의 뒤 조문
    opens = (before.match(/「/g) || []).length; closes = (before.match(/」/g) || []).length;
    if (opens > closes) continue;                                  // 「…」 안쪽(법령명에 포함된 조문)
    bm = /「([^「」]+)」\s*$/.exec(before);
    gap = prevEnd >= 0 ? text.slice(prevEnd, m.index) : null;
    if (bm) {
      target = bm[1].replace(/\s+/g, ' ').trim();
    } else if (prevTarget && gap !== null && LMA_LIST_GAP_RE.test(gap)) {
      target = prevTarget;
    } else if (/같은\s*법(?:\s*시행\s*(?:령|규칙))?\s*$/.test(before)) {
      var last = lmaLastBracketName(before);
      var suf = /시행\s*령\s*$/.test(before) ? ' 시행령' : (/시행\s*규칙\s*$/.test(before) ? ' 시행규칙' : '');
      target = last ? last + suf : '같은 법' + suf;
    } else {
      lw = LMA_LAWWORD_RE.exec(before);
      word = lw ? lmaNorm(lw[1]) : '';
      if (!word) target = 'self';
      else if (word === '법') target = /(?:^|[\s(「])이\s*법\s*$/.test(before) ? 'self' : (ctx.parentLawName || '법'); // "이 법 제N조"는 자기 법 — 단 "내용이 법 제N조"의 '이'는 조사(앞 경계 필요, 사업법 시행령 40조 실측)
      else if (word === '영' || word === '시행령') target = ctx.parentDecreeName || '영';
      else if (word === '규칙' || word === '시행규칙') target = '규칙';
      else target = lw[1].replace(/\s+/g, '');
    }
    keys = lmaExpandKeys(m[1], m[2]);
    para = lmaLastPara(before);
    prevEnd = m.index + m[0].length; prevTarget = target;
    snip = text.slice(Math.max(0, m.index - 30), m.index + m[0].length + 30).replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim();
    for (i = 0; i < keys.length; i++) {
      if (target === 'self' && ctx.selfKey && keys[i] === ctx.selfKey) continue;
      k = target + '|' + keys[i] + '|' + para;
      if (seen[k]) continue;
      seen[k] = 1;
      out.push({ target: target, key: keys[i], fromPara: para, snippet: snip });
    }
  }
  return out;
}

/** before 텍스트에서 가장 최근 「…」 이름 */
function lmaLastBracketName(before) {
  var re = /「([^「」]+)」/g, m, last = '';
  while ((m = re.exec(before)) !== null) last = m[1].replace(/\s+/g, ' ').trim();
  return last;
}

/** before 텍스트에서 가장 최근 항 번호(①…⑳), 없으면 '' */
function lmaLastPara(before) {
  var m = /([①-⑳])[^①-⑳]*$/.exec(before);
  return m ? m[1] : '';
}

/** '37조의2' → '제37조의2' */
function lmaKeyLabel(key) {
  key = String(key || '').replace(/\s/g, '');
  return key ? (/^제/.test(key) ? key : '제' + key) : '';
}

/** document_chunks.article_no('제19조(…)' / '19조(…)' / '19조의2(…)' / '19조') → '19조' / '19조의2'. art_key() 이식 */
function lmaArtKey(articleNo) {
  var a = String(articleNo || '').trim().replace(/^제/, '');
  a = a.split('(')[0];
  return a.replace(/\s/g, '');
}

/** article_no 값이 이 키를 가리키는가 */
function lmaArtNoMatches(articleNo, key) {
  var k = String(key || '').replace(/\s/g, '').replace(/^제/, '');
  return !!k && lmaArtKey(articleNo) === k;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    lmaNorm: lmaNorm, lmaExpandKeys: lmaExpandKeys, lmaBasisKeys: lmaBasisKeys,
    lmaExtractCitations: lmaExtractCitations, lmaKeyLabel: lmaKeyLabel,
    lmaArtKey: lmaArtKey, lmaArtNoMatches: lmaArtNoMatches
  };
}

// lawmap_articles_layout.js — 관계도 "주제 → 조문" 그래프의 고정 좌표 배치 + 법령 상자 그리기
// 의존성 없음. vis-network(physics:false)에 x/y를 넘기고, beforeDrawing에서 lmaDrawBoxes로 상자를 그린다.

var LMA_TYPE_COLORS = {
  fill:   { law: '#2ea060', decree: '#1f9e9e', rules: '#1f9e9e', notice: '#e08a3c', etc: '#d5486a' },
  stroke: { law: '#2ea060', decree: '#1f9e9e', rules: '#1f9e9e', notice: '#e08a3c', etc: '#d5486a' }
};

function lmaHexToRgba(hex, alpha) {
  var h = String(hex || '#888').replace('#', '');
  if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
  var n = parseInt(h, 16);
  return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + (alpha == null ? 1 : alpha) + ')';
}

// 상자 크기 계산: 조문 격자(maxCols열) + 여백 + 캡션 + 라벨 여유
function lmaMeasureBox(box, o) {
  var n = Math.max(1, (box.items || []).length);
  var cols = Math.min(n, o.maxCols), rows = Math.ceil(n / cols);
  var gridW = (cols - 1) * o.itemGapX + o.nodeSize * 2;
  var gridH = (rows - 1) * o.itemGapY + o.nodeSize * 2;
  // minBoxW: 조문 1개짜리 상자도 라벨·캡션이 들어갈 폭 확보
  return { cols: cols, rows: rows, w: Math.max(gridW + o.padX * 2, o.minBoxW), h: o.captionH + gridH + o.padY * 2 + o.labelH };
}

// 두 사각형 겹침(margin 포함)
function lmaRectsOverlap(a, b, m) {
  return !(a.x + a.w + m <= b.x || b.x + b.w + m <= a.x || a.y + a.h + m <= b.y || b.y + b.h + m <= a.y);
}
// 원점에서 사각형까지의 최단 거리
function lmaRectDistToOrigin(r) {
  var dx = Math.max(r.x, 0, -(r.x + r.w)), dy = Math.max(r.y, 0, -(r.y + r.h));
  return Math.sqrt(dx * dx + dy * dy);
}

function lmaLayout(boxes, opts) {
  var o = { nodeSize: 14, itemGapX: 92, itemGapY: 46, padX: 18, padY: 30, captionH: 22, maxCols: 3,
            minRadius: 200, topicClearance: 90, labelH: 26, margin: 24, minBoxW: 120, topicId: null };
  for (var k in (opts || {})) if (opts[k] != null) o[k] = opts[k];
  boxes = boxes || [];
  var measured = boxes.map(function (b) { var m = lmaMeasureBox(b, o); m.box = b; return m; });

  // 배치 순서 휴리스틱: 상자 4개 이상이면 가장 큰 상자를 맨 위(-90°)에, 나머지는 크기 내림차순으로
  // 왼쪽(마지막 인덱스)·오른쪽(다음 인덱스)에 번갈아 놓아 큰 상자들이 서로 마주보도록 한다. 3개 이하는 입력 순서 유지.
  var order = measured.slice();
  if (order.length >= 4) {
    var sorted = measured.slice().sort(function (a, b) { return (b.w * b.h) - (a.w * a.h); });
    var n = sorted.length, slots = new Array(n), lo = 1, hi = n - 1;
    slots[0] = sorted[0];
    for (var i = 1; i < n; i++) { if (i % 2 === 1) slots[hi--] = sorted[i]; else slots[lo++] = sorted[i]; }
    order = slots;
  }

  // 반지름 증가 루프: 겹침 없음 + 주제 노드와의 간격 확보
  var count = order.length, radius = o.minRadius, rects = [];
  for (; radius <= 2000; radius += 20) {
    rects = order.map(function (m, idx) {
      var ang = -Math.PI / 2 + (2 * Math.PI * idx) / count;  // -90°부터 시계방향
      var cx = count === 1 ? 0 : Math.cos(ang) * radius, cy = count === 1 ? -radius : Math.sin(ang) * radius;
      return { id: m.box.id, label: m.box.label, type: m.box.type, x: cx - m.w / 2, y: cy - m.h / 2, w: m.w, h: m.h, _m: m };
    });
    var ok = true;
    for (var a = 0; a < rects.length && ok; a++) {
      if (lmaRectDistToOrigin(rects[a]) < o.topicClearance) ok = false;
      for (var b = a + 1; b < rects.length && ok; b++) if (lmaRectsOverlap(rects[a], rects[b], o.margin)) ok = false;
    }
    if (ok) break;
  }
  if (radius > 2000) radius = 2000;

  // 조문 좌표: 행 단위로 가운데 정렬(마지막 행이 덜 차도 중앙)
  var positions = {}, hints = {};
  if (o.topicId != null) positions[o.topicId] = { x: 0, y: 0 };
  rects.forEach(function (r) {
    var m = r._m, items = m.box.items || [];
    var top = r.y + o.captionH + o.padY + o.nodeSize;
    items.forEach(function (it, i) {
      var row = Math.floor(i / m.cols), inRow = Math.min(m.cols, items.length - row * m.cols);
      var rowW = (inRow - 1) * o.itemGapX;
      positions[it.id] = { x: r.x + r.w / 2 - rowW / 2 + (i % m.cols) * o.itemGapX, y: top + row * o.itemGapY };
      hints[it.id] = { labelBelow: true, primary: !!it.primary, boxId: r.id };
    });
    delete r._m;
  });
  return { positions: positions, hints: hints, rects: rects, topic: { x: 0, y: 0 }, radius: radius };
}

// beforeDrawing에서 호출: 둥근 상자 + 좌상단 캡션
function lmaDrawBoxes(ctx, rects, theme) {
  var t = theme || {};
  var fill = t.fill || LMA_TYPE_COLORS.fill, stroke = t.stroke || LMA_TYPE_COLORS.stroke;
  ctx.save();
  ctx.font = t.font || '12px sans-serif';
  ctx.textBaseline = 'alphabetic';
  (rects || []).forEach(function (r) {
    var rad = 10, x = r.x, y = r.y, w = r.w, h = r.h;
    ctx.beginPath();
    ctx.moveTo(x + rad, y);
    ctx.arcTo(x + w, y, x + w, y + h, rad);
    ctx.arcTo(x + w, y + h, x, y + h, rad);
    ctx.arcTo(x, y + h, x, y, rad);
    ctx.arcTo(x, y, x + w, y, rad);
    ctx.closePath();
    ctx.fillStyle = lmaHexToRgba(fill[r.type] || fill.etc, t.fillAlpha == null ? 0.10 : t.fillAlpha);
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.strokeStyle = lmaHexToRgba(stroke[r.type] || stroke.etc, t.strokeAlpha == null ? 0.55 : t.strokeAlpha);
    ctx.stroke();
    // 캡션: 폭 초과 시 '…' 잘라내기
    var label = String(r.label || ''), maxW = w - 20;
    if (ctx.measureText(label).width > maxW) {
      while (label.length > 1 && ctx.measureText(label + '…').width > maxW) label = label.slice(0, -1);
      label += '…';
    }
    ctx.fillStyle = t.captionColor || '#555';
    ctx.fillText(label, x + 10, y + 15);
  });
  ctx.restore();
}

// 캔버스 좌표(params.pointer.canvas)가 들어있는 상자
function lmaHitRect(rects, x, y) {
  for (var i = 0; i < (rects || []).length; i++) {
    var r = rects[i];
    if (x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h) return r;
  }
  return null;
}

var LMA_SHORT_NAMES = {
  '전기통신사업법': '사업법', '방송통신발전 기본법': '방발법', '방송통신발전기본법': '방발법',
  '정보통신망 이용촉진 및 정보보호 등에 관한 법률': '망법', '전파법': '전파법'
};
function lmaShortLawName(name) {
  var s = String(name || '').trim();
  if (!s) return '';
  if (LMA_SHORT_NAMES[s]) return LMA_SHORT_NAMES[s];
  var m = /^(.*?)\s*시행(령|규칙)$/.exec(s);
  if (m) return lmaShortLawName(m[1]) + (m[2] === '령' ? ' 영' : ' 규칙');
  return s.length > 8 ? s.slice(0, 6) + '…' : s;
}

var LMA_CIRCLED = ['⓪', '①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩', '⑪', '⑫', '⑬', '⑭', '⑮', '⑯', '⑰', '⑱', '⑲', '⑳'];
// fromPara: 3 또는 '③' 모두 허용. toLawShort가 비어 있으면(같은 법령) 법령명 생략
function lmaEdgeLabel(fromKey, fromPara, toLawShort, toKey) {
  var para = '';
  if (fromPara != null && fromPara !== '') {
    var num = typeof fromPara === 'number' ? fromPara : parseInt(fromPara, 10);
    para = (!isNaN(num) && LMA_CIRCLED[num]) ? LMA_CIRCLED[num] : String(fromPara);
  }
  var to = (toLawShort ? toLawShort + ' ' : '') + String(toKey || '');
  return String(fromKey || '') + para + ' → ' + to;
}

// 라벨 줄바꿈: 공백 우선, 공백 없는 긴 단어는 강제 절단
function lmaWrapLabel(text, max) {
  max = max || 14;
  var words = String(text || '').split(/\s+/).filter(Boolean), lines = [], cur = '';
  words.forEach(function (w) {
    while (w.length > max) {  // 단어 자체가 너무 길면 조각내기
      if (cur) { lines.push(cur); cur = ''; }
      lines.push(w.slice(0, max)); w = w.slice(max);
    }
    if (!cur) cur = w;
    else if ((cur + ' ' + w).length <= max) cur += ' ' + w;
    else { lines.push(cur); cur = w; }
  });
  if (cur) lines.push(cur);
  return lines.join('\n');
}

if (typeof module !== 'undefined') module.exports = {
  lmaLayout: lmaLayout, lmaDrawBoxes: lmaDrawBoxes, lmaHitRect: lmaHitRect, lmaEdgeLabel: lmaEdgeLabel,
  lmaShortLawName: lmaShortLawName, lmaWrapLabel: lmaWrapLabel, lmaHexToRgba: lmaHexToRgba,
  lmaMeasureBox: lmaMeasureBox, lmaRectsOverlap: lmaRectsOverlap, LMA_TYPE_COLORS: LMA_TYPE_COLORS
};

// ═══════════════════════════════════════════════════════════════════════════════════════
//  법령 관계도 — 주제 포커스의 "조문 단위 보기" (2026-09-06, 배경역사 #125)
//  주제 화면에서 동그라미를 법령이 아니라 근거 조문으로, 법령은 조문을 담는 배경 상자로 그린다.
//  회색 선은 근거 조문 본문이 다른 근거 조문을 실제로 인용하는 곳에만, 조문 라벨과 함께.
//  전체 인용망·법령 포커스는 종전 그대로(법령 단위). 토글(localStorage lawmap_article_mode)로 끄면 종전 화면.
//  데이터는 노드 카드가 이미 쓰는 document_chunks 조문 청크만 — AI 호출 0회.
//  실패하면 조용히 종전 화면으로 돌아가고 상태줄에 사유를 남긴다(fail-open: 화면이 비는 것보다 종전 화면이 낫다).
//  파서(lmaBasisKeys·lmaExtractCitations)·배치(lmaLayout·lmaDrawBoxes)는 같은 파일 앞부분.
// ═══════════════════════════════════════════════════════════════════════════════════════

var _lmaMode = (function() {
  try { var v = localStorage.getItem('lawmap_article_mode'); return v === null ? true : v === '1'; } catch(e) { return true; }
})();
var _lmaBypass = false;          // 폴백 재진입 방지
var _lmaCache = {};              // topicId → 모델 (같은 세션 안 재조회 방지)
var _lmaModel = null;            // 현재 화면 모델 (클릭 처리용)
var LMA_MAX_ITEMS_PER_BOX = 6;   // 상자당 조문 상한 (근거 조문 우선, 나머지 "외 N개")

function lmaShouldHandle(focusId) {
  if (!_lmaMode || _lmaBypass || !focusId) return false;
  var f = _lawMapNodes.find(function(n) { return n.id === focusId; });
  return !!(f && f.node_type === 'topic');
}

function lmaSetMode(on) {
  _lmaMode = !!on;
  try { localStorage.setItem('lawmap_article_mode', _lmaMode ? '1' : '0'); } catch(e) {}
  lmaUpdateToggle();
  if (_lawMapFocusId) {
    var f = _lawMapNodes.find(function(n) { return n.id === _lawMapFocusId; });
    if (f && f.node_type === 'topic') { renderLawMapGraph(_lawMapFocusId); showLawMapNodeDetail(_lawMapFocusId); }
  }
}

// 토글 버튼은 index.html을 건드리지 않고 '보강' 버튼 옆에 심는다 (없으면 상태줄 뒤)
function lmaEnsureToggle() {
  if (document.getElementById('lma-toggle')) return;
  var anchor = document.getElementById('lawmap-enrich-btn') || document.getElementById('lawmap-status');
  if (!anchor) return;
  var b = document.createElement('button');
  b.id = 'lma-toggle'; b.className = 'btn';
  b.style.cssText = 'font-size:11px;padding:2px 8px;margin-left:6px;display:none';
  b.title = '주제 화면을 법령 단위/조문 단위로 전환';
  b.onclick = function() { lmaSetMode(!_lmaMode); };
  anchor.insertAdjacentElement('afterend', b);
  lmaUpdateToggle();
}
function lmaUpdateToggle() {
  var b = document.getElementById('lma-toggle');
  if (!b) return;
  var f = _lawMapFocusId ? _lawMapNodes.find(function(n) { return n.id === _lawMapFocusId; }) : null;
  b.style.display = (f && f.node_type === 'topic') ? 'inline-flex' : 'none';
  b.innerHTML = '<i class="ti ' + (_lmaMode ? 'ti-toggle-right' : 'ti-toggle-left') + '"></i> 조문 단위 보기 ' + (_lmaMode ? '켬' : '끔');
}

// ── 문서명 확정 (노드 카드와 같은 규칙: doc_name → document_chunks ilike) ──
async function lmaResolveDocName(n) {
  if (n.doc_name) return n.doc_name;
  try {
    var dq = await sb.from('document_chunks').select('doc_name').ilike('doc_name', n.name + '%').limit(20);
    var nrm = lmaNorm(n.name);
    var ok = (dq.data || []).map(function(x) { return x.doc_name; }).filter(function(d) {
      var nd = lmaNorm(d); return nd === nrm || nd.indexOf(nrm + '(') === 0;
    });
    if (ok.length) return ok.sort().pop();
  } catch(e) {}
  return null;
}

// ── 조문 청크 조회: 한 문서의 여러 조문을 한 번에 (article_no '제19조(…)'/'19조(…)' 두 형태) ──
async function lmaFetchArticles(docName, keys) {
  var out = {};
  if (!docName || !keys.length) return out;
  var ors = [];
  keys.forEach(function(k) {
    ors.push('article_no.eq.' + k, 'article_no.eq.제' + k, 'article_no.ilike."' + k + '(%"', 'article_no.ilike."제' + k + '(%"');
  });
  var r = await sb.from('document_chunks').select('article_no,chunk_index,content').eq('doc_name', docName).or(ors.join(',')).order('chunk_index').limit(200);
  if (r.error) throw new Error(r.error.message);
  (r.data || []).forEach(function(c) {
    var k = keys.find(function(kk) { return lmaArtNoMatches(c.article_no, kk); });
    if (!k) return;
    if (!out[k]) out[k] = { key: k, articleNo: c.article_no, title: lmaTitleOf(c.article_no), content: '' };
    out[k].content = lmaJoinChunks(out[k].content, c.content || '');
  });
  return out;
}
// 인접 청크는 앞뒤 100자가 겹친다(청킹 overlap, 정답표 실측) — 겹치는 머리를 잘라 이어 붙인다(그대로 붙이면 문장 조각이 두 번 나옴)
function lmaJoinChunks(acc, next) {
  if (!acc) return next;
  var max = Math.min(140, acc.length, next.length);
  for (var k = max; k >= 20; k--) { if (acc.slice(-k) === next.slice(0, k)) return acc + next.slice(k); }
  return acc + '\n' + next;
}
function lmaTitleOf(articleNo) {
  var m = String(articleNo || '').match(/\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*$/);
  return m ? m[1] : '';
}

// ── 상위법·시행령 판별: 계열 이름(시행령/시행규칙은 이름 접두) → 위임·계열 엣지 → 없음 ──
function lmaParentLaw(lawNode, laws) {
  var base = lmaNorm(lawNode.name).replace(/(시행령|시행규칙)$/, '');
  var byName = laws.find(function(L) { return L.node.id !== lawNode.id && L.node.node_type === 'law' && lmaNorm(L.node.name) === base; });
  if (byName) return byName;
  var ids = laws.map(function(L) { return L.node.id; });
  var e = _lawMapEdges.find(function(x) {
    return (x.source === 'delegation' || x.source === 'thdcmp' || x.source === 'family') &&
      ((x.source_id === lawNode.id && ids.indexOf(x.target_id) >= 0) || (x.target_id === lawNode.id && ids.indexOf(x.source_id) >= 0));
  });
  if (!e) return null;
  var otherId = e.source_id === lawNode.id ? e.target_id : e.source_id;
  var other = laws.find(function(L) { return L.node.id === otherId; });
  return (other && other.node.node_type === 'law') ? other : null;
}

function lmaResolveTarget(cit, L, laws) {
  if (cit.target === 'self') return L;
  if (cit.target === '법' || cit.target === L.parentLawName) return L.parent || null;
  if (cit.target === '영' || cit.target === L.parentDecreeName) return L.parentDecree || null;
  if (cit.target === '규칙') return null;
  var k = lmaNorm(cit.target);
  return laws.find(function(X) { var nx = lmaNorm(X.node.name); return nx === k || nx.indexOf(k) === 0 && nx.length - k.length <= 2; }) || null;
}

// ── 모델 구축 ──
async function lmaBuildModel(topicId) {
  var topic = _lawMapNodes.find(function(n) { return n.id === topicId; });
  var laws = [];
  _lawMapEdges.forEach(function(e) {
    if (e.source_id !== topicId && e.target_id !== topicId) return;
    var otherId = e.source_id === topicId ? e.target_id : e.source_id;
    var n = _lawMapNodes.find(function(x) { return x.id === otherId; });
    if (!n || n.node_type === 'topic') return;
    if (laws.some(function(L) { return L.node.id === n.id; })) return;
    laws.push({ node: n, edge: e, docName: null, keys: [], articles: {}, primaries: [], followers: [], outside: [] });
  });
  if (!laws.length) throw new Error('주제에 연결된 법령이 없습니다');

  // 문서명·근거 조문 (병렬 조회는 4개씩)
  for (var i = 0; i < laws.length; i += 4) {
    await Promise.all(laws.slice(i, i + 4).map(async function(L) {
      L.docName = await lmaResolveDocName(L.node);
      L.keys = lmaBasisKeys(L.edge.description || '', L.node.name);
      if (L.docName && !L.keys.length) L.keys = ['1조'];          // 고시 전체가 주제일 때: 목적 조항으로 대표
      if (L.docName && L.keys.length) L.articles = await lmaFetchArticles(L.docName, L.keys);
      L.primaries = L.keys.filter(function(k) { return !!L.articles[k]; });
      L.missing = L.keys.filter(function(k) { return !L.articles[k]; });
    }));
  }
  laws.forEach(function(L) {
    L.parent = lmaParentLaw(L.node, laws);
    L.parentLawName = L.parent ? L.parent.node.name : null;
    L.parentDecree = L.parent ? laws.find(function(X) { return X.node.node_type === 'decree' && lmaNorm(X.node.name) === lmaNorm(L.parent.node.name) + '시행령'; }) || null : null;
    L.parentDecreeName = L.parentDecree ? L.parentDecree.node.name : null;
  });

  // 인용 추출 → 화면 안 조문으로 해소
  var cites = [];    // {from:{L,key,para}, to:{L,key}, snippet}
  var followerKeys = {};   // lawId → Set(keys)
  laws.forEach(function(L) {
    L.primaries.forEach(function(k) {
      var a = L.articles[k];
      var found = lmaExtractCitations(a.content, { selfName: L.node.name, selfKey: k, parentLawName: L.parentLawName, parentDecreeName: L.parentDecreeName });
      found.forEach(function(c) {
        var T = lmaResolveTarget(c, L, laws);
        if (!T) { L.outside.push(c); return; }
        if (T === L && c.key === k) return;
        cites.push({ from: { L: L, key: k, para: c.fromPara || '' }, to: { L: T, key: c.key }, snippet: c.snippet });
        // 따라온 조문(1홉)은 **법률 본문이 인용한 것만** 동그라미로 — 준용·정의 같은 실질 연결.
        //   시행령·고시가 "법 제35조·제37조·제38조…"로 나열하는 것은 위임 근거 목록이라 다 그리면 상자가 넘친다(사업법 시행령 40조 실측) → 카드에만.
        if (L.node.node_type === 'law' && T.primaries.indexOf(c.key) < 0) { (followerKeys[T.node.id] = followerKeys[T.node.id] || {})[c.key] = 1; }
      });
    });
  });
  // 따라온 조문(1홉) 본문 조회 — 카드 표시·제목용. 정의·목적 조항은 제외(「사업법」 제2조제18호 같은 용어 참조), 상자 상한을 넘는 것은 버림
  for (var j = 0; j < laws.length; j += 4) {
    await Promise.all(laws.slice(j, j + 4).map(async function(L) {
      var fk = Object.keys(followerKeys[L.node.id] || {});
      if (!fk.length || !L.docName) return;
      var got = await lmaFetchArticles(L.docName, fk);
      var room = Math.max(0, LMA_MAX_ITEMS_PER_BOX - L.primaries.length);
      fk.filter(function(k) { return got[k] && !/정의|목적/.test(got[k].title || ''); }).slice(0, room)
        .forEach(function(k) { L.articles[k] = got[k]; L.followers.push(k); });
    }));
  }
  // 화면에 없는 조문으로 가는 인용은 선으로 그리지 않고 카드의 "이 조문이 인용하는 다른 조문"에만 남긴다
  laws.forEach(function(L) { L.moreCites = []; });
  cites.forEach(function(c) {
    if (!c.to.L.articles[c.to.key] || !c.from.L.articles[c.from.key]) c.from.L.moreCites.push(c);
  });
  cites = cites.filter(function(c) { return !!c.to.L.articles[c.to.key] && !!c.from.L.articles[c.from.key]; });
  // 같은 (from,to) 중복 병합 — 항 라벨은 첫 것
  var seen = {}, edges = [];
  cites.forEach(function(c) {
    var id = c.from.L.node.id + '#' + c.from.key + '>' + c.to.L.node.id + '#' + c.to.key;
    if (seen[id]) { seen[id].count++; return; }
    seen[id] = { id: id, from: c.from, to: c.to, para: c.from.para, snippet: c.snippet, count: 1, kind: 'cite' };
    edges.push(seen[id]);
  });
  // 위임 폴백: 하위법령·고시가 상위법 근거 조문을 본문에서 인용하지 않으면 위임 엣지로 점선 연결
  laws.forEach(function(L) {
    if (!L.parent || !L.primaries.length || !L.parent.primaries.length) return;
    // 상위법 또는 상위 시행령 조문을 본문에서 이미 인용하면 위임 점선 불필요(시행규칙 11조의4 → 영 46조의2 실측)
    var has = edges.some(function(e) { return e.from.L === L && (e.to.L === L.parent || (L.parentDecree && e.to.L === L.parentDecree)); });
    if (has) return;
    var deleg = _lawMapEdges.some(function(x) {
      return (x.source === 'delegation' || x.source === 'thdcmp' || x.source === 'family') &&
        ((x.source_id === L.node.id && x.target_id === L.parent.node.id) || (x.target_id === L.node.id && x.source_id === L.parent.node.id));
    });
    if (!deleg) return;
    edges.push({ id: L.node.id + '>deleg>' + L.parent.node.id, from: { L: L, key: L.primaries[0], para: '' }, to: { L: L.parent, key: L.parent.primaries[0] }, kind: 'deleg', count: 1 });
  });

  // 상자·조문 항목
  var boxes = laws.map(function(L) {
    var items = L.primaries.map(function(k) { return { id: L.node.id + '#' + k, key: k, label: lmaWrapLabel(lmaKeyLabel(k).replace(/^제/, '') + (L.articles[k].title ? ' ' + L.articles[k].title : ''), 11), primary: true }; })
      .concat(L.followers.map(function(k) { return { id: L.node.id + '#' + k, key: k, label: lmaWrapLabel(lmaKeyLabel(k).replace(/^제/, '') + (L.articles[k].title ? ' ' + L.articles[k].title : ''), 11), primary: false }; }));
    if (!items.length) {
      items.push({ id: L.node.id + '#none', key: null, primary: true,
        label: !L.docName ? '원문 KB 미보유' : (L.missing && L.missing.length ? lmaKeyLabel(L.missing[0]) + ' 원문에 없음' : '조문 체계 없음') });
    }
    return { id: L.node.id, label: L.node.name, type: L.node.node_type, items: items, L: L };
  });
  var layout = lmaLayout(boxes, { itemGapX: 150, itemGapY: 70, maxCols: 3, minRadius: 230, topicClearance: 110, topicId: topic.id });
  var primaryCount = laws.reduce(function(s, L) { return s + L.primaries.length; }, 0);
  var outsideCount = laws.reduce(function(s, L) { return s + L.outside.length; }, 0);
  return { topic: topic, laws: laws, boxes: boxes, edges: edges, layout: layout, primaryCount: primaryCount, outsideCount: outsideCount, builtAt: Date.now() };
}

// ── 렌더 ──
async function lmaRenderTopic(topicId) {
  var el = document.getElementById('lawmap-graph');
  if (!el) return;
  lmaEnsureToggle();
  updateLawMapNoticeToggle(false);
  var enrichBtn = document.getElementById('lawmap-enrich-btn');
  if (enrichBtn) enrichBtn.style.display = 'inline-flex';
  lmaUpdateToggle();
  var model = _lmaCache[topicId];
  if (!model) {
    el.innerHTML = '<div style="color:var(--text-secondary);font-size:12px;padding:16px">근거 조문을 원문과 대조하는 중…</div>';
    try {
      model = await lmaBuildModel(topicId);
      _lmaCache[topicId] = model;
    } catch(e) {
      console.warn('조문 단위 보기 실패 → 법령 단위로 폴백:', e);
      _lmaBypass = true;
      try { renderLawMapGraph(topicId); } finally { _lmaBypass = false; }
      setLawMapStatus('조문 단위 보기를 만들지 못해 법령 단위로 표시합니다 (' + lmEsc(e && e.message ? e.message : e) + ')');
      return;
    }
    if (_lawMapFocusId !== topicId) return;   // 대조 중 다른 곳으로 이동함
  }
  _lmaModel = model;
  var css = getComputedStyle(document.documentElement);
  var textColor = (css.getPropertyValue('--text-primary') || '').trim() || '#333';
  var subColor = (css.getPropertyValue('--text-secondary') || '').trim() || '#666';
  var bgColor = (css.getPropertyValue('--bg-primary') || '').trim() || '#fff';
  var pos = model.layout.positions;
  var visNodes = [{
    id: model.topic.id, label: lawmapWrapLabel(model.topic.name), shape: 'dot', size: 22, x: 0, y: 0, fixed: true,
    color: { background: LAWMAP_COLORS.topic, border: 'rgba(0,0,0,0.22)', highlight: { background: LAWMAP_COLORS.topic, border: textColor } },
    font: { color: textColor, size: 15, strokeWidth: 4, strokeColor: bgColor, bold: true }
  }];
  model.boxes.forEach(function(b) {
    var col = LAWMAP_COLORS[b.type] || '#999';
    b.items.forEach(function(it) {
      var p = pos[it.id] || { x: 0, y: 0 };
      visNodes.push({
        id: it.id, label: it.label, shape: 'dot', size: it.primary ? 12 : 9, x: p.x, y: p.y, fixed: true,
        color: { background: it.primary ? col : lmaHexToRgba(col, 0.45), border: it.primary ? 'rgba(0,0,0,0.22)' : lmaHexToRgba(col, 0.8),
                 highlight: { background: col, border: textColor } },
        font: { color: it.primary ? textColor : subColor, size: 11, strokeWidth: 4, strokeColor: bgColor }
      });
    });
  });
  var visEdges = [];
  model.laws.forEach(function(L) {
    L.primaries.forEach(function(k) {
      visEdges.push({ id: 't>' + L.node.id + '#' + k, from: model.topic.id, to: L.node.id + '#' + k, dashes: [4, 4], width: 1,
        color: { color: LAWMAP_COLORS.topic, opacity: 0.45 }, arrows: { to: { enabled: false } }, smooth: false, title: L.edge.description || '' });
    });
  });
  model.edges.forEach(function(e) {
    var fromId = e.from.L.node.id + '#' + e.from.key, toId = e.to.L.node.id + '#' + e.to.key;
    var sameLaw = e.from.L === e.to.L;
    var label = e.kind === 'deleg' ? '위임' : lmaEdgeLabel(e.from.key, e.para, sameLaw ? null : lmaShortLawName(e.to.L.node.name), e.to.key);
    visEdges.push({
      id: e.id, from: fromId, to: toId, label: label, arrows: { to: { enabled: true, scaleFactor: 0.6 } },
      width: e.kind === 'deleg' ? 1 : Math.min(1.2 + (e.count - 1) * 0.6, 3), dashes: e.kind === 'deleg' ? [6, 4] : false,
      color: { color: '#8a8f98', opacity: 0.75, highlight: '#5b7ff5' },
      font: { size: 10, color: subColor, strokeWidth: 3, strokeColor: bgColor, align: 'middle' },
      smooth: { type: 'curvedCW', roundness: 0.12 },
      title: e.snippet ? ('“' + e.snippet + '”') : (e.kind === 'deleg' ? '위임 관계(본문 인용 없음)' : '')
    });
  });
  el.innerHTML = '';
  var data = { nodes: new vis.DataSet(visNodes), edges: new vis.DataSet(visEdges) };
  var options = {
    physics: false,
    interaction: { hover: true, tooltipDelay: 120, dragNodes: false },
    layout: { improvedLayout: false },
    nodes: { scaling: { label: { enabled: false } } }
  };
  if (_lawMapNet) { try { _lawMapNet.destroy(); } catch(e) {} }
  _lawMapNet = new vis.Network(el, data, options);
  var theme = { captionColor: subColor, font: '12px ' + ((css.getPropertyValue('--font-sans') || '').trim() || 'sans-serif') };
  _lawMapNet.on('beforeDrawing', function(ctx) { try { lmaDrawBoxes(ctx, model.layout.rects, theme); } catch(e) {} });
  _lawMapNet.on('click', function(p) {
    if (p.nodes && p.nodes.length) {
      var id = p.nodes[0];
      if (id === model.topic.id) { showLawMapNodeDetail(id); return; }
      var lawId = id.split('#')[0], key = id.split('#')[1];
      var L = model.laws.find(function(x) { return x.node.id === lawId; });
      if (!L) return;
      if (key === 'none' || !L.articles[key]) { showLawMapNodeDetail(lawId); return; }
      lmaShowArticleCard(L, key, model);
      return;
    }
    var hit = p.pointer && p.pointer.canvas ? lmaHitRect(model.layout.rects, p.pointer.canvas.x, p.pointer.canvas.y) : null;
    if (hit) showLawMapNodeDetail(hit.id);
  });
  try { _lawMapNet.fit({ animation: false }); } catch(e) {}
  var citeCount = model.edges.filter(function(e) { return e.kind === 'cite'; }).length;
  var delegCount = model.edges.length - citeCount;
  // lawMapSelectTopic이 renderLawMapGraph 직후 자기 상태줄을 쓰므로(캐시 경로는 동기 실행) 한 틱 늦게 덮어쓴다
  setTimeout(function() {
    if (_lawMapFocusId !== topicId) return;
    setLawMapStatus('주제 <b>' + lmEsc(model.topic.name) + '</b> — 조문 단위 보기: 근거 조문 ' + model.primaryCount + '개 · 조문 인용 ' + citeCount + '건' +
      (delegCount ? ' · 위임 ' + delegCount + '건' : '') + (model.outsideCount ? ' · 주제 밖 법령 인용 ' + model.outsideCount + '건(카드에서 확인)' : '') +
      (citeCount === 0 ? ' · <span style="color:var(--text-tertiary)">근거 조문 사이 직접 인용 없음 — 각 법령이 독립적으로 규정</span>' : '') +
      ' · <span style="color:var(--text-tertiary)">동그라미=조문, 상자=법령, 진한 동그라미=근거 조문</span>');
  }, 0);
}

// ── 조문 카드 ──
function lmaShowArticleCard(L, key, model) {
  var el = document.getElementById('lawmap-detail');
  if (!el) return;
  var a = L.articles[key];
  var color = LAWMAP_COLORS[L.node.node_type] || '#999';
  var isPrimary = L.primaries.indexOf(key) >= 0;
  var outs = model.edges.filter(function(e) { return e.from.L === L && e.from.key === key; });
  var ins = model.edges.filter(function(e) { return e.to.L === L && e.to.key === key; });
  function edgeLine(e, dir) {
    var other = dir === 'out' ? e.to : e.from;
    var lab = lmaShortLawName(other.L.node.name) + ' ' + lmaKeyLabel(other.key);
    return '<li>' + (dir === 'out' ? '→ ' : '← ') + '<b>' + lmEsc(lab) + '</b>' + (e.kind === 'deleg' ? ' (위임)' : (e.para ? ' <span style="color:var(--text-tertiary)">' + lmEsc(e.para) + '에서 인용</span>' : '')) +
      (e.snippet ? '<div style="font-size:11px;color:var(--text-tertiary);margin-left:14px">“' + lmEsc(e.snippet) + '”</div>' : '') + '</li>';
  }
  var more = (isPrimary ? (L.moreCites || []).filter(function(c) { return c.from.key === key; }) : []);
  var moreSeen = {};
  more = more.filter(function(c) { var id = c.to.L.node.id + '#' + c.to.key; if (moreSeen[id]) return false; moreSeen[id] = 1; return true; }).slice(0, 12);
  var moreHtml = more.map(function(c) {
    return '<li>' + lmEsc(lmaShortLawName(c.to.L.node.name)) + ' ' + lmEsc(lmaKeyLabel(c.to.key)) + (c.from.para ? ' <span style="color:var(--text-tertiary)">' + lmEsc(c.from.para) + '</span>' : '') + '</li>';
  }).join('');
  var outside = (isPrimary ? L.outside : []).slice(0, 6).map(function(c) {
    return '<li>' + lmEsc(c.target === 'self' ? L.node.name : c.target) + ' ' + lmEsc(lmaKeyLabel(c.key)) + (c.fromPara ? ' <span style="color:var(--text-tertiary)">' + lmEsc(c.fromPara) + '</span>' : '') + '</li>';
  }).join('');
  var body = lawmapCleanText(a.content, L.node.name);
  var html =
    '<div style="font-weight:700;color:var(--text-primary)">' + lmEsc(L.node.name) +
      ' <span style="font-size:10px;padding:1px 7px;border-radius:999px;background:' + color + '22;border:1px solid ' + color + '66;color:var(--text-secondary)">' + (LAWMAP_TYPE_LABEL[L.node.node_type] || '') + '</span>' +
      ' <span style="font-size:11px;color:var(--text-tertiary)">' + (isPrimary ? '근거 조문' : '근거 조문이 인용한 조문') + '</span></div>' +
    '<div style="margin:5px 0;padding:6px 10px;border-left:3px solid ' + color + ';background:var(--bg-secondary);border-radius:0 6px 6px 0;font-size:12.5px;color:var(--text-primary)"><b>' +
      lmEsc(lmaKeyLabel(key)) + (a.title ? '(' + lmEsc(a.title) + ')' : '') + '</b>' +
      (isPrimary && L.edge.description ? '<div style="font-size:11.5px;color:var(--text-secondary);margin-top:2px">🎯 ' + lmEsc(model.topic.name) + '에서의 역할: ' + lmEsc(L.edge.description) + '</div>' : '') + '</div>' +
    '<pre style="white-space:pre-wrap;font-family:inherit;font-size:12px;line-height:1.55;color:var(--text-primary);background:var(--bg-secondary);padding:8px 10px;border-radius:6px;max-height:260px;overflow:auto;margin:6px 0">' + lmEsc(body.slice(0, 2400)) + (body.length > 2400 ? '\n…' : '') + '</pre>' +
    ((outs.length || ins.length) ? '<div style="font-size:11px;color:var(--text-tertiary);margin-top:4px">이 조문의 인용 관계 (화면 안)</div><ul style="margin:2px 0 0 18px;padding:0;font-size:12px;color:var(--text-secondary)">' +
      outs.map(function(e) { return edgeLine(e, 'out'); }).join('') + ins.map(function(e) { return edgeLine(e, 'in'); }).join('') + '</ul>' : '') +
    (moreHtml ? '<div style="font-size:11px;color:var(--text-tertiary);margin-top:6px">이 조문이 인용하는 다른 조문 (위임 근거 나열 — 화면에 그리지 않음)</div><ul style="margin:2px 0 0 18px;padding:0;font-size:12px;color:var(--text-secondary)">' + moreHtml + '</ul>' : '') +
    (outside ? '<div style="font-size:11px;color:var(--text-tertiary);margin-top:6px">주제 밖 법령 인용 (화면에 그리지 않음)</div><ul style="margin:2px 0 0 18px;padding:0;font-size:12px;color:var(--text-secondary)">' + outside + '</ul>' : '') +
    '<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">' +
      '<button class="btn" style="font-size:11px;padding:3px 9px" onclick="showLawMapNodeDetail(\'' + L.node.id + '\')"><i class="ti ti-book"></i> 법령 카드</button>' +
      (L.docName ? '<button class="btn" style="font-size:11px;padding:3px 9px" onclick="openLawMapDoc(' + JSON.stringify(L.docName).replace(/"/g, '&quot;') + ')"><i class="ti ti-file-text"></i> 원문 열기</button>' : '') +
    '</div>';
  el.innerHTML = html;
}
