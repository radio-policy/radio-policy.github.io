// tools_lawmap_match.js — 관계도 질문 매칭(app.js lawmapMatchQuery) 기대값·전수 대조 (#285, 2026-10-06)
//   anon REST로 관계도를 읽기만 한다(대시보드와 같은 order=id). AI 0회, DB 무변경.
//   app.js에서 매칭 함수 원문을 잘라 와 실행하므로 대시보드와 같은 코드가 돈다. 고치기 전 app.js(lawmapMatchQuery 없음)는
//   준비자료(local_docs/관계도_IDC주제_재검토_준비_261006/match_sim.js)와 같은 재현 방식으로 돈다.
//
// 사용:
//   node tools_lawmap_match.js                         기대값(tests/fixtures/lawmap_match_cases.json) 대조 + 전수 요약
//   node tools_lawmap_match.js --app <파일>            다른 app.js로(예: git show HEAD:app.js > 파일 — 고치기 전 값)
//   node tools_lawmap_match.js --out <json>            사례별 결과·전수 1위 표 저장
//   node tools_lawmap_match.js --compare <json>        저장한 결과와 비교해 1위가 바뀐 (법령, 조)만 출력
//   node tools_lawmap_match.js --no-citeverify         CiteVerify 없이(사내 콘솔 조건 — 약칭 풀이 꺼짐)
//   node tools_lawmap_match.js --stubs                 원문 없는 citation 스텁 중 약칭 규칙으로 정식 노드 하나에 맞는 것 목록
//   node tools_lawmap_match.js --phantoms              다른 법령 조 번호로 건너뛴 인용 전부(앞머리 낱말별)
// 기대값과 다르면 종료 코드 1.
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const ROOT = __dirname;
const args = process.argv.slice(2);
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : null; };
const flag = (k) => args.includes(k);

const appPath = opt('--app') || path.join(ROOT, 'app.js');
const appSrc = fs.readFileSync(appPath, 'utf8');
const curSrc = fs.readFileSync(path.join(ROOT, 'app.js'), 'utf8');   // 접속 주소·키는 현재 app.js에서
require(path.join(ROOT, 'supabase/functions/_shared/cite_verify.js'));
require(path.join(ROOT, 'supabase/functions/_shared/rag_core.js'));
const CV = flag('--no-citeverify') ? undefined : globalThis.CiteVerify;

function grabFn(name) {   // function name(...) { ... } 원문을 괄호 짝으로
  const i = appSrc.indexOf('function ' + name + '(');
  if (i < 0) return null;
  const j = appSrc.indexOf('{', i);
  for (let k = j, d = 0; k < appSrc.length; k++) {
    if (appSrc[k] === '{') d++;
    else if (appSrc[k] === '}') { d--; if (d === 0) return appSrc.slice(i, k + 1); }
  }
  return null;
}
function grabVar(name) {
  const m = appSrc.match(new RegExp('(?:var|let) ' + name + ' = ([\\s\\S]*?);[ \\t]*(?://[^\\n]*)?\\n'));   // 줄 끝 주석 허용
  return m ? 'var ' + name + ' = ' + m[1] + ';' : null;
}
const NEW = appSrc.indexOf('function lawmapMatchQuery(') >= 0;
const FN_NAMES = NEW
  ? ['lmNormName', 'lawmapTopicWords', 'lawmapParseArticleQuery', 'lawmapNodeByName', 'lawmapDescOwnRefs', 'lawmapRefCovers', 'lawmapDescCites',
     'lawmapDescNormRange', 'lawmapDescArticleCount', 'lawmapIsAdjacent', 'lawmapArticleHits', 'lawmapTopicDegree', 'lawmapAliasNode',
     'lawmapTopicWordSet', 'lawmapWordShadowed', 'lawmapMatchQuery', 'lawmapArtNums']
  : ['lmNormName', 'lawmapTopicWords', 'lawmapParseArticleQuery', 'lawmapDescCites', 'lawmapDescNormRange', 'lawmapDescArticleCount', 'lawmapArtNums'];
const VAR_NAMES = NEW
  ? ['LAWMAP_MATCH_STOP', 'LAWMAP_DESC_ART_RE', 'LAWMAP_KIND_WORDS', 'LAWMAP_PREFIX_WORD_RE', 'LAWMAP_LAWISH_RE', 'LAWMAP_LIST_GAP_RE', '_lawMapTopicDeg', '_lawMapTopicWordSet']
  : ['LAWMAP_MATCH_STOP', 'LAWMAP_DESC_ART_RE'];
const parts = [];
for (const v of VAR_NAMES) { const s = grabVar(v); if (!s) throw new Error('app.js에 없음: ' + v); parts.push(s); }
for (const f of FN_NAMES) { const s = grabFn(f); if (!s) throw new Error('app.js에 없음: ' + f); parts.push(s); }
const L = new Function('extractKeywords', 'CiteVerify', parts.join('\n') + '\nreturn {' + FN_NAMES.join(',') + '};')(globalThis.RagCore.extractKeywords, CV);

const SB_URL = curSrc.match(/const DEFAULT_SB_URL = '([^']+)'/)[1];
const SB_KEY = curSrc.match(/const DEFAULT_SB_KEY = '([^']+)'/)[1];
async function get(table, qs) {
  const out = [];
  for (let off = 0; ; off += 1000) {
    const r = await fetch(`${SB_URL}/rest/v1/${table}?${qs}&order=id.asc&limit=1000&offset=${off}`, { headers: { apikey: SB_KEY, Authorization: 'Bearer ' + SB_KEY } });
    if (!r.ok) throw new Error(table + ' ' + r.status + ' ' + (await r.text()).slice(0, 200));
    const rows = await r.json(); out.push(...rows);
    if (rows.length < 1000) return out;
  }
}

// ── 고치기 전 app.js의 askLawMap 재현(준비자료 match_sim.js와 같음 — 동점은 목록 순 첫 주제) ──
function legacyMatch(q, nodes, edges) {
  const artQ = L.lawmapParseArticleQuery(q);
  if (artQ) {
    const k = L.lmNormName(artQ.law);
    const lawNode = nodes.find(n => n.node_type !== 'topic' && L.lmNormName(n.name) === k);
    if (lawNode) return { mode: 'article', artQ, lawNode, via: 'name', hits: legacyHits(lawNode, artQ.key, nodes, edges) };
  }
  const qStripped = q.replace(/(^|\s)[가-힣A-Za-z0-9·ㆍ]*(?:법|법률|시행령|시행규칙|규칙|고시)(?=\s|$|\d)/g, '$1 ');
  const qns = qStripped.replace(/\s+/g, '').toLowerCase();
  const kws = globalThis.RagCore.extractKeywords(q).filter(k => !L_STOP[k]);
  let best = null, bestScore = 0;
  nodes.filter(n => n.node_type === 'topic').forEach(n => {
    const nameHits = L.lawmapTopicWords(n.name).filter(w => qns.indexOf(w.toLowerCase()) !== -1);
    if (!nameHits.length) return;
    let s = nameHits.length * 3;
    const desc = (n.description || '').toLowerCase();
    kws.forEach(k => { if (desc.indexOf(k.toLowerCase()) !== -1) s += 1; });
    if (s > bestScore) { bestScore = s; best = n; }
  });
  return { mode: 'topic', best, score: bestScore };
}
let L_STOP = {};
function legacyHits(lawNode, key, nodes, edges) {
  const hits = [];
  edges.forEach(e => {
    if (e.source_id !== lawNode.id && e.target_id !== lawNode.id) return;
    const oid = e.source_id === lawNode.id ? e.target_id : e.source_id;
    const t = nodes.find(x => x.id === oid);
    if (t && t.node_type === 'topic' && L.lawmapDescCites(e.description, key)) hits.push({ topic: t, edge: e, adj: /^\s*\[인접 제도\]/.test(e.description || '') });
  });
  hits.sort((a, b) => L.lawmapDescArticleCount(a.edge.description) - L.lawmapDescArticleCount(b.edge.description) || (b.edge.weight || 0) - (a.edge.weight || 0));
  return hits;
}
const match = NEW ? L.lawmapMatchQuery : legacyMatch;
const articleHits = NEW ? L.lawmapArticleHits : legacyHits;

function summarize(r) {
  if (r.mode === 'article') {
    return { mode: 'article', law: r.lawNode.name, via: r.via, pick: r.hits.length ? r.hits[0].topic.name : null,
      others: r.hits.slice(1).map(h => h.topic.name + (h.adj ? ' (인접)' : '')) };
  }
  return { mode: 'topic', pick: r.best && r.score >= 3 ? r.best.name : null, score: r.score };
}

(async () => {
  const nodes = await get('law_graph_nodes', 'select=id,name,node_type,description,doc_name,source');
  const edges = await get('law_graph_edges', 'select=id,source_id,target_id,relation_type,description,source,weight');
  if (!NEW) { const m = appSrc.match(/var LAWMAP_MATCH_STOP = ([\s\S]*?);\n/); L_STOP = new Function('return ' + m[1])(); }
  const byId = new Map(nodes.map(n => [n.id, n]));
  console.log(`app.js: ${path.relative(ROOT, appPath) || appPath} (${NEW ? '새 코드 lawmapMatchQuery' : '고치기 전 재현'})${CV ? '' : ' · CiteVerify 없음'} · 노드 ${nodes.length} · 선 ${edges.length}`);

  // ── ① 기대값 ──
  const cases = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests/fixtures/lawmap_match_cases.json'), 'utf8'));
  const results = [];
  let fail = 0;
  const show = (c, kind) => {
    let got;
    if (c.law) {   // 질문 해석을 거치지 않고 (법령, 조) 정렬을 직접 — 이름이 종류 낱말로 끝나지 않는 고시
      const k = L.lmNormName(c.law), lawNode = nodes.find(n => n.node_type !== 'topic' && L.lmNormName(n.name) === k);
      if (!lawNode) throw new Error('법령 노드 없음: ' + c.law);
      got = summarize({ mode: 'article', lawNode, via: 'direct', hits: articleHits(lawNode, c.key, nodes, edges) });
    } else got = summarize(match(c.q, nodes, edges));
    const probs = [];
    if (kind === 'article' && c.mode && got.mode !== c.mode) probs.push(`갈래 ${got.mode}≠${c.mode}`);
    if ((got.pick || null) !== (c.want || null)) probs.push(`1위 「${got.pick}」≠「${c.want}」`);
    const oth = (got.others || []).map(s => s.replace(/ \(인접\)$/, ''));
    (c.othersInclude || []).forEach(t => { if (!oth.includes(t)) probs.push(`다른 주제에 「${t}」 없음`); });
    (c.othersExclude || []).forEach(t => { if (oth.includes(t)) probs.push(`다른 주제에 「${t}」 있음`); });
    if (probs.length) fail++;
    results.push({ kind, q: c.q, want: c.want, got, ok: !probs.length, probs });
    console.log(`${probs.length ? 'FAIL' : 'ok  '}  [${kind === 'article' ? '조문' : '주제'}] ${c.q} → ${got.pick || '(없음)'}` +
      (got.via === 'alias' ? ` [약칭→${got.law}]` : '') + (got.others && got.others.length ? `  · 다른: ${got.others.join(', ')}` : '') +
      (probs.length ? `\n        ${probs.join(' / ')}` : ''));
  };
  console.log('\n── ① 기대값 대조 ──');
  cases.article.forEach(c => show(c, 'article'));
  cases.topic.forEach(c => show(c, 'topic'));
  const nCases = cases.article.length + cases.topic.length;
  console.log(`기대값: ${nCases - fail}/${nCases} 일치`);

  // ── ② 전수: (법령, 조) — 주제 선 설명에 나오는 모든 조 번호(준비자료 adj_rank.js와 같은 뽑기) ──
  const isTopic = id => (byId.get(id) || {}).node_type === 'topic';
  const topicEdges = edges.filter(e => byId.get(e.source_id) && byId.get(e.target_id) && isTopic(e.source_id) !== isTopic(e.target_id));
  const lawOf = e => byId.get(isTopic(e.source_id) ? e.target_id : e.source_id);
  const byLaw = new Map();
  topicEdges.forEach(e => { const l = lawOf(e); if (!byLaw.has(l.id)) byLaw.set(l.id, []); byLaw.get(l.id).push(e); });
  const oldNorm = d => String(d || '').replace(/조\s*([~∼\-])\s*제?\s*(\d+)\s*조/g, '$1$2조');
  let matches = 0, pairs = 0, multi = 0, adjWins = 0;
  const top = {}, adjWinList = [];
  for (const [lid, list] of byLaw) {
    const law = byId.get(lid), keys = new Set();
    list.forEach(e => { const re = /제\s*(\d+)\s*조(?:\s*의\s*(\d+))?/g; let m; const d = oldNorm(e.description); while ((m = re.exec(d))) keys.add(m[1] + '조' + (m[2] ? '의' + m[2] : '')); });
    for (const key of keys) {
      const hits = articleHits(law, key, nodes, edges);
      pairs++; matches += hits.length;
      if (hits.length) top[law.name + ' 제' + key] = hits[0].topic.name;
      if (hits.length >= 2) {
        multi++;
        if (hits[0].adj && hits.some(h => !h.adj)) { adjWins++; adjWinList.push(`${law.name} 제${key} → ${hits[0].topic.name}`); }
      }
    }
  }
  const adjCount = topicEdges.filter(e => /^\s*(?:\[[^\]]*\]\s*)*\[인접 제도\]/.test(e.description || '')).length;
  const adjMid = topicEdges.filter(e => /\[인접 제도\]/.test(e.description || '') && !/^\s*(?:\[[^\]]*\]\s*)*\[인접 제도\]/.test(e.description || '')).length;
  console.log('\n── ② 전수(주제 선) ──');
  console.log(`주제 선 ${topicEdges.length} · [인접 제도]로 시작 ${adjCount} · 중간에만 ${adjMid}`);
  console.log(`(법령, 조) ${pairs}쌍 · 매치(그 조를 인용하는 선) ${matches} · 1위 있는 쌍 ${Object.keys(top).length} · 둘 이상 주제 ${multi}쌍 · 인접 선이 본래 선을 앞지름 ${adjWins}쌍`);
  adjWinList.forEach(s => console.log('    ' + s));

  let phantom = null;
  if (NEW) {   // 다른 법령 앞머리로 건너뛴 조 번호(허상)·앞머리가 붙었는데 자기 법령으로 친 것
    let skipRefs = 0, ownPrefixed = 0, listMulti = 0;
    const skipEdges = new Set(), byPrefix = {}, ownPref = [], skipList = [];
    topicEdges.forEach(e => {
      const law = lawOf(e);
      L.lawmapDescOwnRefs(e.description, law).forEach(r => {
        if (r.own && r.list) listMulti++;
        if (!r.own) { skipRefs++; skipEdges.add(e.id); byPrefix[r.prefix || '(목록 물려받음)'] = (byPrefix[r.prefix || '(목록 물려받음)'] || 0) + 1; skipList.push(`${law.name} | ${r.prefix || '…'} 제${r.lo}${r.hi !== r.lo ? '~' + r.hi : ''}조${r.ui !== null ? '의' + r.ui : ''} | ${(e.description || '').slice(0, 90)}`); }
        else if (r.prefix) { ownPrefixed++; ownPref.push(`${law.name} ← 「${r.prefix} 제${r.lo}조」`); }
      });
    });
    phantom = { skipRefs, skipEdges: skipEdges.size, ownPrefixed, byPrefix };
    console.log(`다른 법령 조로 건너뛴 인용 ${skipRefs}개 / 그런 선 ${skipEdges.size}개 · 앞머리가 붙었지만 자기 법령으로 친 인용 ${ownPrefixed}개 · 자기 조 목록형(「제35·37조」) ${listMulti}개`);
    console.log('  건너뛴 앞머리 낱말(상위 25): ' + Object.entries(byPrefix).sort((a, b) => b[1] - a[1]).slice(0, 25).map(([k, v]) => `${k} ${v}`).join(' · '));
    ownPref.forEach(s => console.log('  [자기 법령으로 침] ' + s));
    if (flag('--phantoms')) skipList.forEach(s => console.log('  [건너뜀] ' + s));

    // 관계도 '조문 단위 보기'의 lmaBasisKeys(lawmap_articles.js)와 자기 조 번호가 다른 선 — 참고(합치지 않음)
    const ctx = vm.createContext({});
    vm.runInContext(fs.readFileSync(path.join(ROOT, 'lawmap_articles.js'), 'utf8'), ctx);
    let diff = 0; const diffEx = [];
    topicEdges.forEach(e => {
      const law = lawOf(e);
      const a = new Set(); L.lawmapDescOwnRefs(e.description, law).filter(r => r.own).forEach(r => r.parts.forEach(p => { if (p.hi - p.lo <= 10) for (let n = p.lo; n <= p.hi; n++) a.add(n); }));
      const b = new Set(ctx.lmaBasisKeys(e.description, law.name).map(k => parseInt(k, 10)));
      const same = a.size === b.size && [...a].every(x => b.has(x));
      if (!same) { diff++; if (diffEx.length < 12) diffEx.push(`${law.name}: 새 [${[...a].join(',')}] / lma [${[...b].join(',')}] — ${(e.description || '').slice(0, 70)}`); }
    });
    console.log(`참고 — lmaBasisKeys(조문 단위 보기)와 자기 조 번호가 다른 주제 선: ${diff}/${topicEdges.length}`);
    diffEx.forEach(s => console.log('    ' + s));
  }

  if (opt('--compare')) {
    const prev = JSON.parse(fs.readFileSync(opt('--compare'), 'utf8'));
    const keys = new Set([...Object.keys(prev.top || {}), ...Object.keys(top)]);
    const changed = [...keys].filter(k => (prev.top || {})[k] !== top[k]).sort();
    console.log(`\n── ③ 1위가 바뀐 (법령, 조): ${changed.length} ──`);
    changed.forEach(k => console.log(`    ${k}: ${(prev.top || {})[k] || '(없음)'} → ${top[k] || '(없음)'}`));
    const pc = {}; (prev.results || []).forEach(r => { pc[r.kind + '|' + r.q] = r.got.pick; });
    const cc = results.filter(r => pc[r.kind + '|' + r.q] !== undefined && pc[r.kind + '|' + r.q] !== r.got.pick);
    console.log(`── 기대값 질문 중 답이 바뀐 것: ${cc.length} ──`);
    cc.forEach(r => console.log(`    ${r.q}: ${pc[r.kind + '|' + r.q] || '(없음)'} → ${r.got.pick || '(없음)'}`));
  }

  if (flag('--stubs') && CV) {   // Q4 (c) 준비 — 원문 없는 citation 스텁이 약칭 규칙으로 doc_name 있는 정식 노드 하나에 맞는가
    const real = nodes.filter(n => n.node_type !== 'topic' && n.doc_name);
    const stubs = nodes.filter(n => n.node_type !== 'topic' && !n.doc_name && n.source === 'citation');
    const deg = {}; edges.forEach(e => { deg[e.source_id] = (deg[e.source_id] || 0) + 1; deg[e.target_id] = (deg[e.target_id] || 0) + 1; });
    let one = 0;
    console.log(`\n── 스텁 ${stubs.length}개 중 약칭 규칙으로 정식 노드 하나에 맞는 것 ──`);
    stubs.forEach(s => {
      const hit = real.filter(r => CV.familyMatches(r.name, s.name));
      if (hit.length === 1) { one++; console.log(`    ${s.name} (선 ${deg[s.id] || 0}) → ${hit[0].name}`); }
    });
    console.log(`    합계 ${one}개`);
  }

  if (opt('--out')) {
    fs.writeFileSync(opt('--out'), JSON.stringify({ app: appPath, newCode: NEW, at: new Date().toISOString(), nodes: nodes.length, edges: edges.length,
      summary: { pairs, matches, multi, adjWins, topicEdges: topicEdges.length, adjCount, adjMid, phantom, casesOk: nCases - fail, cases: nCases }, results, top }, null, 1));
    console.log('\n저장: ' + opt('--out'));
  }
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
