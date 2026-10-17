// Дерево файлов в духе netrw (`<leader>e` → `:Explore`): <Space>e, j/k, Enter, -, :q.
// Только чтение: список папки приходит из /api/tree (внутри корня проекта); документы
// (PDF, Markdown, ноутбуки) открываются в читалке, остальные файлы — в nvim через /api/open.
(function () {
"use strict";
const SORTS = ["name", "time", "size"];
const RU = "йцукенгшщзхъфывапролджэячсмитьбюЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ";
const EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,.QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>";
const CODE = { Semicolon: ";:", Slash: "/?", Minus: "-_", Equal: "=+", Period: ".>", Comma: ",<", Quote: "'\"",
  BracketLeft: "[{", BracketRight: "]}", Backquote: "`~", Backslash: "\\|", Space: "  " };
const QUIT = new Set(["q", "qu", "qui", "quit", "qa", "qal", "qall", "quita", "quitall", "wq", "wqa", "wqall", "x", "xi", "xit",
  "xa", "xall", "exi", "exit", "clo", "clos", "close", "bd", "bdelete", "bw", "bwipeout", "ZZ", "ZQ"]);
const WRITE = new Set(["w", "wr", "wri", "writ", "write", "up", "update", "sav", "saveas"]);
const EDIT = new Set(["e", "ed", "edi", "edit", "E", "Ex", "Exp", "Explore", "Sex", "Vex", "Hex", "Lex", "Rex", "Sexplore", "Vexplore"]);
const TABEDIT = new Set(["tabe", "tabedit", "tabnew", "tabf", "tabfind", "Tex", "Texplore"]);
const HELP = [
  "chitalka · дерево файлов в духе netrw (только чтение)",
  "  <CR>            папка — войти; документ — открыть в читалке; другой файл — в nvim",
  "  -               на папку выше          t     открыть в новой вкладке браузера",
  "  j k  gg G  5j 12G  Ctrl-d Ctrl-u  Ctrl-f Ctrl-b  H M L  zz zt zb   — как в nvim",
  "  / ?  n N        поиск (:noh — снять подсветку)",
  "  s  r            сортировка: имя → время → размер; обратный порядок",
  "  gh  I  Ctrl-l   скрытые файлы; баннер; перечитать папку",
  "  :q  :e путь  :tabe путь  :12  ZZ   выйти, открыть, открыть во вкладке, строка 12",
];
const st = { open: false, ready: null, root: "", path: "", dir: "", entries: [], lines: [], cur: 0, top: 0, rows: 20,
  count: "", pend: "", mode: "normal", cmd: "", hist: [], hi: -1, tab: null, search: null, hl: null, inc: null,
  msg: null, box: null, sort: "name", rev: false, hide: false, banner: true, pos: {}, main: null, current: null, lh: 20 };
let el, buf, sl, cl, boxEl;

const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const join = (dir, name) => (dir ? dir + "/" : "") + name;
const parentOf = rel => rel.split("/").slice(0, -1).join("/");
const baseOf = rel => rel.split("/").pop();

// Символ клавиши в любой раскладке (как langmap): Cyrillic «о» на месте j — это j.
function chr(e) {
  if (e.key.length === 1 && e.key >= " " && e.key <= "~") return e.key;
  let m = /^Key([A-Z])$/.exec(e.code);
  if (m) return e.shiftKey ? m[1] : m[1].toLowerCase();
  m = /^Digit(\d)$/.exec(e.code);
  if (m) return e.shiftKey ? ")!@#$%^&*("[+m[1]] : m[1];
  if (CODE[e.code]) return CODE[e.code][e.shiftKey ? 1 : 0];
  return e.key;
}
const latin = s => [...s].map(c => { const i = RU.indexOf(c); return i < 0 ? c : EN[i]; }).join("");

// ---------------------------------------------------------------- модель
function build(keep) {
  const shown = st.entries.filter(x => !(st.hide && x.name.startsWith(".")));
  const key = { name: (a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0),
    time: (a, b) => b.mtime - a.mtime, size: (a, b) => b.size - a.size }[st.sort];
  shown.sort((a, b) => (b.dir - a.dir) || key(a, b) || (a.name < b.name ? -1 : 1));
  if (st.rev) shown.reverse();
  const L = [];
  if (st.banner) {
    const head = '" Netrw Directory Listing';
    L.push('" ' + "=".repeat(76), head + " ".repeat(Math.max(1, 78 - head.length - 10)) + "(chitalka)",
      '"   ' + st.path, '"   Sorted by      ' + (st.rev ? "reverse " : "") + st.sort, '"   Sort sequence: [\\/]$,*',
      '"   Quick Help: <F1>:help  -:go up dir  t:new tab  s:sort-by  gh:hidden  :q:quit', '" ' + "=".repeat(78));
  }
  st.lines = L.map(t => ({ t, k: "cm" }));
  st.first = st.lines.length;
  st.lines.push({ t: "../", k: "dir", up: true }, { t: "./", k: "dir", dot: true });
  for (const x of shown)
    st.lines.push({ t: x.name + (x.dir ? "/" : x.exec ? "*" : x.link ? "@" : ""), k: x.dir ? "dir" : x.exec ? "exe" : x.link ? "lnk" : "", e: x });
  const at = keep && st.lines.findIndex(l => l.e && l.e.name === keep);
  st.cur = at > 0 ? at : Math.min(st.first + (shown.length ? 2 : 0), st.lines.length - 1);
  fit(true);
}
async function load(dir, focus) {
  const r = await fetch("/api/tree?dir=" + encodeURIComponent(dir));
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const er = new Error(data.error || r.statusText); er.status = r.status; throw er; }
  if (st.lines[st.cur] && st.lines[st.cur].e) st.pos[st.dir] = st.lines[st.cur].e.name;
  Object.assign(st, { root: data.root, path: data.path, dir: data.dir, entries: data.entries, hl: st.hl });
  build(focus || st.pos[data.dir]);
  if (data.truncated) message(`Показаны первые ${data.entries.length} файлов`, true);
  render();
}
async function go(dir, focus) {
  try { await load(dir, focus); } catch (e) { message(e.message, true); render(); }
}

// ---------------------------------------------------------------- открыть
function documentURL(rel) { return rel === st.main ? "/" : "/?document=" + encodeURIComponent(rel); }
async function openEntry(line, tab) {
  if (!line || line.k === "cm") return;
  if (line.up) return up();
  if (line.dot) return go(st.dir);
  const x = line.e, rel = join(st.dir, x.name);
  if (x.dir) return go(rel);
  if (x.doc) {
    if (tab) { window.open(documentURL(rel), "_blank"); return message(`"${rel}" открыт в новой вкладке`); }
    if (rel === st.current) return close();
    location.href = documentURL(rel);
    return;
  }
  try {
    const r = await fetch("/api/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file: rel, line: 1 }) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || r.statusText);
    message(`"${rel}" открыт в nvim`);
  } catch (e) { message("Не открылось: " + e.message, true); }
  render();
}
function up() {
  if (!st.dir) { message("Выше корня проекта читалка не открывает", true); return render(); }
  return go(parentOf(st.dir), baseOf(st.dir));
}
function resolve(arg) {
  let p = arg.trim().replace(/^~\//, "/");
  if (p.startsWith(st.root + "/") || p === st.root) p = p.slice(st.root.length + 1);
  else if (p.startsWith("/")) return null;
  else p = join(st.dir, p);
  const out = [];
  for (const part of p.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") { if (!out.length) return null; out.pop(); } else out.push(part);
  }
  return out.join("/");
}
async function edit(arg, tab) {
  if (!arg) return go(st.dir);
  const rel = resolve(arg);
  if (rel === null) { message("Выше корня проекта читалка не открывает", true); return render(); }
  try { return await load(rel); } catch (e) { if (e.status !== 404) { message(e.message, true); return render(); } }
  try {
    const r = await fetch("/api/tree?dir=" + encodeURIComponent(parentOf(rel)));
    const data = await r.json();
    const x = r.ok && data.entries.find(y => y.name === baseOf(rel));
    if (!x) throw new Error(`E: нет такого файла: ${rel}`);
    if (parentOf(rel) !== st.dir) await load(parentOf(rel), x.name);
    else { const i = st.lines.findIndex(l => l.e && l.e.name === x.name); if (i >= 0) st.cur = i; }
    return openEntry({ e: x, k: "" }, tab);
  } catch (e) { message(e.message, true); render(); }
}

// ---------------------------------------------------------------- движение
function fit(center) {
  const n = st.lines.length;
  st.cur = Math.max(0, Math.min(st.cur, n - 1));
  if (center) st.top = Math.max(0, Math.min(st.cur - Math.floor(st.rows / 2), n - st.rows));
  if (st.cur < st.top) st.top = st.cur;
  if (st.cur >= st.top + st.rows) st.top = st.cur - st.rows + 1;
  st.top = Math.max(0, Math.min(st.top, Math.max(0, n - 1)));
}
function move(d) { st.cur += d; fit(); }
function scroll(d) {
  const n = st.lines.length;
  st.top = Math.max(0, Math.min(st.top + d, n - 1));
  st.cur = Math.max(st.top, Math.min(st.cur, st.top + st.rows - 1, n - 1));
}
function message(text, err) { st.msg = { text, err: !!err }; }

// ---------------------------------------------------------------- поиск
function regex(pat) { try { return new RegExp(pat, "g"); } catch (e) { return new RegExp(pat.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g"); } }
function find(re, from, dir, wrapMsg) {
  const n = st.lines.length;
  for (let s = 1; s <= n; s++) {
    const i = ((from + dir * s) % n + n) % n;
    re.lastIndex = 0;
    if (re.test(st.lines[i].t)) {
      if (wrapMsg) { const wrapped = dir > 0 ? i <= from : i >= from; if (wrapped) message(dir > 0 ? "search hit BOTTOM, continuing at TOP" : "search hit TOP, continuing at BOTTOM", true); }
      return i;
    }
  }
  return -1;
}
function searchNext(dir) {
  if (!st.search) return message("E35: No previous regular expression", true);
  const d = st.search.dir * dir, re = regex(st.search.pat);
  st.hl = st.search.pat;
  message((st.search.dir > 0 ? "/" : "?") + st.search.pat);
  const i = find(re, st.cur, d, true);
  if (i < 0) return message("E486: Pattern not found: " + st.search.pat, true);
  st.cur = i; fit();
}

// ---------------------------------------------------------------- команды
function ex(raw) {
  let s = raw.trim().replace(/^:+/, "");
  if (!s) return;
  st.hist = st.hist.filter(h => h !== raw); st.hist.push(raw);
  if (/^\d+$/.test(s)) { st.cur = +s - 1; return fit(); }
  if (s === "$") { st.cur = st.lines.length - 1; return fit(); }
  let m = /^([A-Za-zА-Яа-яЁё]+)(!?)\s*(.*)$/.exec(s);
  if (!m) return message("E492: Not an editor command: " + s, true);
  let [, name, , arg] = m;
  if (/[А-Яа-яЁё]/.test(name)) name = latin(name);
  if (QUIT.has(name)) return close();
  if (WRITE.has(name)) return message("E382: Cannot write, 'buftype' option is set", true);
  if (EDIT.has(name)) return edit(arg, false);
  if (TABEDIT.has(name)) return arg ? edit(arg, true) : message("E: укажите файл: :tabe путь", true);
  if (name === "noh" || name === "nohlsearch") { st.hl = null; return; }
  if (name === "h" || name === "help") { st.box = HELP; return; }
  message("E492: Not an editor command: " + s, true);
}
function complete(back) {
  const m = /^(\S+\s+)(.*)$/.exec(st.cmd);
  if (!m) return;
  if (!st.tab || st.tab.base !== m[1]) {
    const part = m[2], dir = part.includes("/") ? part.slice(0, part.lastIndexOf("/") + 1) : "";
    if (dir) return;                        // дополняем только в текущей папке
    const names = st.lines.filter(l => l.e && l.e.name.startsWith(part)).map(l => l.e.name + (l.e.dir ? "/" : ""));
    if (!names.length) return;
    st.tab = { base: m[1], names, i: -1 };
  }
  const t = st.tab; t.i = (t.i + (back ? -1 : 1) + t.names.length) % t.names.length;
  st.cmd = t.base + t.names[t.i];
}

// ---------------------------------------------------------------- клавиши
function key(e) {
  if (!st.open) return;
  e.stopImmediatePropagation();
  if (e.metaKey) return;                    // Cmd+… — браузеру
  const c = chr(e), ctrl = e.ctrlKey && !e.altKey;
  if (["Shift", "Control", "Alt", "Meta", "CapsLock"].includes(e.key)) return;
  e.preventDefault();
  if (st.mode !== "normal") return cmdKey(e, c, ctrl);
  if (st.box) { st.box = null; if (c !== ":") return render(); }
  if (ctrl) {
    const k = c.toLowerCase(), half = Math.max(1, Math.floor(st.rows / 2));
    if (k === "d") { scroll(half); st.cur = Math.min(st.cur + half, st.lines.length - 1); fit(); }
    else if (k === "u") { scroll(-half); st.cur = Math.max(st.cur - half, 0); fit(); }
    else if (k === "f") { scroll(st.rows - 2); st.cur = Math.max(st.cur, st.top); }
    else if (k === "b") { scroll(-(st.rows - 2)); st.cur = Math.min(st.cur, st.top + st.rows - 1); }
    else if (k === "e") scroll(1);
    else if (k === "y") scroll(-1);
    else if (k === "n" || k === "j") move(+st.count || 1);
    else if (k === "p") move(-(+st.count || 1));
    else if (k === "l") return go(st.dir);
    else if (k === "c") message("Type  :q  and press <Enter> to exit netrw");
    else if (k === "[") st.count = st.pend = "";
    st.count = ""; return render();
  }
  if (st.pend) {
    const p = st.pend; st.pend = "";
    const n = +st.count || 0; st.count = "";
    if (p === "g" && c === "g") { st.cur = (n || 1) - 1; fit(); }
    else if (p === "g" && c === "h") { st.hide = !st.hide; build(currentName()); }
    else if (p === "z" && (c === "z" || c === ".")) { st.top = Math.max(0, st.cur - Math.floor(st.rows / 2)); }
    else if (p === "z" && (c === "t" || c === "Enter")) { st.top = st.cur; }
    else if (p === "z" && (c === "b" || c === "-")) { st.top = Math.max(0, st.cur - st.rows + 1); }
    else if (p === "Z" && (c === "Z" || c === "Q")) return close();
    return render();
  }
  if (/^[1-9]$/.test(c) || (c === "0" && st.count)) { st.count += c; return render(); }
  const had = st.count !== "", n = +st.count || 1;
  st.count = "";
  switch (c) {
    case "j": case "ArrowDown": move(n); break;
    case "k": case "ArrowUp": move(-n); break;
    case "G": st.cur = had ? n - 1 : st.lines.length - 1; fit(); break;
    case "End": st.cur = st.lines.length - 1; fit(); break;
    case "Home": st.cur = 0; fit(); break;
    case "PageDown": scroll(st.rows - 2); st.cur = Math.max(st.cur, st.top); break;
    case "PageUp": scroll(-(st.rows - 2)); st.cur = Math.min(st.cur, st.top + st.rows - 1); break;
    case "H": st.cur = Math.min(st.top + n - 1, st.lines.length - 1); break;
    case "L": st.cur = Math.max(st.top, Math.min(st.top + st.rows, st.lines.length) - n); break;
    case "M": st.cur = st.top + Math.floor((Math.min(st.top + st.rows, st.lines.length) - st.top - 1) / 2); break;
    case "g": case "z": case "Z": st.pend = c; if (had) st.count = String(n); break;
    case "Enter": return openEntry(st.lines[st.cur], false);
    case "t": return openEntry(st.lines[st.cur], true);
    case "-": return up();
    case "s": st.sort = SORTS[(SORTS.indexOf(st.sort) + 1) % SORTS.length]; build(currentName()); break;
    case "r": st.rev = !st.rev; build(currentName()); break;
    case "I": { const name = currentName(); st.banner = !st.banner; build(name); break; }
    case "n": searchNext(1); break;
    case "N": searchNext(-1); break;
    case ":": st.mode = "cmd"; st.cmd = ""; st.hi = -1; st.msg = null; break;
    case "/": case "?": st.mode = c === "/" ? "search" : "rsearch"; st.sdir = c === "/" ? 1 : -1; st.cmd = ""; st.inc = { cur: st.cur, top: st.top }; st.msg = null; break;
    case "F1": st.box = HELP; break;
    case "Escape": st.pend = ""; break;
    default: break;
  }
  render();
}
function currentName() { const l = st.lines[st.cur]; return l && l.e ? l.e.name : null; }
function cmdKey(e, c, ctrl) {
  const search = st.mode !== "cmd";
  const cancel = () => { if (search && st.inc) { st.cur = st.inc.cur; st.top = st.inc.top; } st.mode = "normal"; st.cmd = ""; st.inc = null; st.tab = null; };
  if (e.key === "Escape" || (ctrl && (c === "[" || c.toLowerCase() === "c"))) cancel();
  else if (e.key === "Enter") {
    const text = st.cmd; st.mode = "normal"; st.cmd = ""; st.tab = null;
    if (search) {
      const pat = text || (st.search && st.search.pat);
      if (st.inc) { st.cur = st.inc.cur; st.top = st.inc.top; } st.inc = null;
      if (pat) { st.search = { pat, dir: st.sdir }; searchNext(1); } else message("E35: No previous regular expression", true);
    } else { const r = ex(text); if (r && r.then) return r.then(render); }
  } else if (e.key === "Backspace") { if (!st.cmd) cancel(); else st.cmd = st.cmd.slice(0, -1); st.tab = null; }
  else if (ctrl && c.toLowerCase() === "u") { st.cmd = ""; st.tab = null; }
  else if (ctrl && c.toLowerCase() === "w") { st.cmd = st.cmd.replace(/\S+\s*$/, ""); st.tab = null; }
  else if (!search && e.key === "Tab") complete(e.shiftKey);
  else if (!search && (e.key === "ArrowUp" || e.key === "ArrowDown") && st.hist.length) {
    st.hi = e.key === "ArrowUp" ? (st.hi < 0 ? st.hist.length - 1 : Math.max(0, st.hi - 1)) : (st.hi < 0 ? -1 : st.hi + 1);
    if (st.hi >= st.hist.length) st.hi = -1;
    st.cmd = st.hi < 0 ? "" : st.hist[st.hi];
  } else if (e.key.length === 1 && !ctrl) { st.cmd += e.key; st.tab = null; }
  if (search && st.mode !== "normal" && st.inc) {        // incsearch
    st.cur = st.inc.cur; st.top = st.inc.top;
    if (st.cmd) { const i = find(regex(st.cmd), st.inc.cur, st.sdir, false); if (i >= 0) { st.cur = i; fit(); } }
  }
  render();
}

// ---------------------------------------------------------------- отрисовка
function lineHTML(L, cursor) {
  const t = L.t, marks = new Array(t.length).fill(0);
  const pat = st.mode !== "normal" && st.mode !== "cmd" ? st.cmd : st.hl;
  if (pat) { const re = regex(pat); let m; re.lastIndex = 0;
    while ((m = re.exec(t))) { if (!m[0].length) { re.lastIndex++; continue; } for (let i = m.index; i < m.index + m[0].length; i++) marks[i] = 1; } }
  let out = "", i = 0;
  if (cursor) { out += `<span class="cur">${esc(t[0] || " ")}</span>`; i = 1; }
  while (i < t.length) {
    let j = i; while (j < t.length && marks[j] === marks[i]) j++;
    out += marks[i] ? `<span class="hl">${esc(t.slice(i, j))}</span>` : esc(t.slice(i, j));
    i = j;
  }
  return out;
}
function render() {
  if (!el) return;
  const n = st.lines.length, w = Math.max(3, String(n).length);
  let html = "";
  for (let i = st.top; i < Math.min(n, st.top + st.rows); i++) {
    const L = st.lines[i], cur = i === st.cur;
    const nr = cur ? String(i + 1).padEnd(w) : String(Math.abs(i - st.cur)).padStart(w);
    html += `<div class="tl${cur ? " cl" : ""}" data-i="${i}"><span class="nr">${nr} </span><span class="tx ${L.k}">${lineHTML(L, cur && st.mode === "normal")}</span></div>`;
  }
  for (let i = n - st.top; i < st.rows; i++) html += `<div class="tl eob"><span class="tx">~</span></div>`;
  buf.innerHTML = html;
  buf.style.setProperty("--nrw", (w + 1) + "ch");
  const line = st.cur + 1, prog = line === 1 ? "Top" : line === n ? "Bot" : Math.floor(line / n * 100) + "%";
  const mode = st.mode === "normal" ? "NORMAL" : "COMMAND";
  sl.innerHTML = `<span class="a ${st.mode === "normal" ? "" : "cmd"}"> ${mode} </span><span class="c"> ${esc(baseOf(st.path) || "/")} [-] </span>`
    + `<span class="fill"></span><span class="x">utf-8 │ unix │ netrw </span><span class="y"> ${prog} </span><span class="a z ${st.mode === "normal" ? "" : "cmd"}"> ${String(line).padStart(3)}:1 </span>`;
  const show = esc(st.count + st.pend);
  if (st.mode !== "normal") cl.innerHTML = `<span>${esc((st.mode === "cmd" ? ":" : st.mode === "search" ? "/" : "?") + st.cmd)}</span><span class="cur"> </span>`;
  else cl.innerHTML = (st.msg ? `<span class="${st.msg.err ? "err" : ""}">${esc(st.msg.text)}</span>` : "") + `<span class="showcmd">${show}</span>`;
  boxEl.hidden = !st.box;
  if (st.box) boxEl.innerHTML = st.box.map(esc).join("\n") + '\n<span class="more">Press ENTER or type command to continue</span>';
}
function measure() {
  const probe = document.createElement("div"); probe.className = "tl"; probe.textContent = "x"; buf.appendChild(probe);
  st.lh = probe.getBoundingClientRect().height || 20; probe.remove();
  st.rows = Math.max(3, Math.floor(buf.clientHeight / st.lh));
  fit();
}

// ---------------------------------------------------------------- открыть / закрыть
function mount() {
  el = document.createElement("div"); el.id = "tree"; el.tabIndex = -1; el.hidden = true;
  el.innerHTML = '<div class="buf"></div><pre class="box" hidden></pre><div class="sl"></div><div class="cmdline"></div>';
  document.body.appendChild(el);
  buf = el.querySelector(".buf"); sl = el.querySelector(".sl"); cl = el.querySelector(".cmdline"); boxEl = el.querySelector(".box");
  buf.addEventListener("click", e => {
    const row = e.target.closest(".tl[data-i]"); if (!row || st.mode !== "normal") return;
    st.cur = +row.dataset.i; st.box = null; render();
    if (st.lines[st.cur].k !== "cm") openEntry(st.lines[st.cur], e.metaKey || e.ctrlKey);
  });
  buf.addEventListener("wheel", e => { e.preventDefault(); scroll(Math.sign(e.deltaY) * 3); render(); }, { passive: false });
  window.addEventListener("keydown", key, true);
  window.addEventListener("resize", () => { if (st.open) { measure(); render(); } });
}
async function open() {
  if (!el) mount();
  if (st.main === null) {
    try { st.main = (await (await fetch("/api/info")).json()).document || ""; } catch (e) { st.main = ""; }
  }
  st.current = new URLSearchParams(location.search).get("document") || st.main;
  Object.assign(st, { open: true, mode: "normal", cmd: "", count: "", pend: "", msg: null, box: null, back: document.activeElement });
  el.hidden = false; el.focus({ preventScroll: true });
  measure();
  st.ready = go(parentOf(st.current), baseOf(st.current));
  return st.ready;
}
function close() {
  st.open = false; el.hidden = true;
  const back = st.back && document.contains(st.back) ? st.back : document.querySelector("#view");
  if (back && back.focus) back.focus({ preventScroll: true });
}
window.ChitalkaTree = { open, close, isOpen: () => st.open, state: st };
})();
