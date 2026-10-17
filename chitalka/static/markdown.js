/* Offline Markdown + TeX renderer. The UI adapter lives in index.html. */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ChitalkaMarkdown = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  function escaped(s, at) { let n = 0; while (at > 0 && s[--at] === "\\") n++; return n % 2 === 1; }
  function closing(s, delimiter, from) {
    for (let at = s.indexOf(delimiter, from); at >= 0; at = s.indexOf(delimiter, at + delimiter.length)) {
      if (!escaped(s, at)) return at;
    }
    return -1;
  }

  // HTML ноутбуков — markdown-ячейки и выводы (таблицы pandas, Styler, оформление курсов),
  // как в Jupyter, но очищенный: поток тегов пересобирается по белому списку. Скрипты,
  // стили, формы, svg и т. п. выбрасываются вместе с содержимым; id и class не выводятся
  // (не задеть разметку и глобальные имена читалки); ссылки — http(s) или внутри проекта,
  // картинки — data:, http(s) или файлы проекта; встроенный стиль — безопасные свойства
  // без url(). Правила Styler вида `#T_x_row0_col1 {…}` переносятся во встроенный стиль.
  const HTML_KEEP = new Set(("table thead tbody tfoot tr th td caption colgroup col div span p br hr b strong i em u s del ins " +
    "sub sup small mark code pre kbd samp var blockquote q cite abbr ul ol li dl dt dd h1 h2 h3 h4 h5 h6 a img figure figcaption " +
    "details summary section article header footer aside nav main").split(" "));
  const HTML_VOID = new Set(["br", "hr", "img", "col"]);
  const HTML_SKIP = new Set(("script style noscript template iframe frame frameset object embed applet button select " +
    "textarea datalist svg math canvas video audio picture map title xmp plaintext noembed noframes dialog head").split(" "));
  const CSS_PROPS = new Set(("color background background-color background-image border border-top border-bottom border-left " +
    "border-right border-color border-width border-style border-radius border-collapse margin margin-top margin-bottom margin-left " +
    "margin-right padding padding-top padding-bottom padding-left padding-right display flex flex-wrap flex-direction flex-grow " +
    "flex-shrink flex-basis align-items justify-content gap row-gap column-gap font-size font-weight font-style line-height " +
    "letter-spacing text-transform text-align text-decoration text-decoration-color text-decoration-thickness text-underline-offset " +
    "vertical-align white-space word-break overflow-wrap width min-width max-width height max-height box-sizing opacity list-style " +
    "list-style-type").split(" "));
  const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
  const decode = s => String(s).replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => e[0] !== "#" ? (ENTITIES[e.toLowerCase()] ?? m)
    : String.fromCodePoint(Math.min(0x10ffff, parseInt(e[1] === "x" || e[1] === "X" ? e.slice(2) : e.slice(1), e[1] === "x" || e[1] === "X" ? 16 : 10) || 0xfffd)));
  const attr = s => String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  const htmlText = s => String(s).replace(/&(?!(#x[0-9a-f]+|#\d+|[a-z][a-z0-9]*);)/gi, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  function cssDecls(text, into = new Map()) {
    for (const part of decode(text || "").split(";")) {
      const at = part.indexOf(":"); if (at < 0) continue;
      const prop = part.slice(0, at).trim().toLowerCase(), value = part.slice(at + 1).replace(/!\s*important/gi, "").trim();
      if (!CSS_PROPS.has(prop) || !value || value.length > 200 || !/^[#\w\s.,%()+\-/'"]+$/.test(value)) continue;
      if (/url|expression|javascript|image-set|element\(|attr\(|@/i.test(value)) continue;
      if (prop === "display" && !/^(block|inline|inline-block|flex|inline-flex|grid|none|list-item|table|table-cell|table-row)$/.test(value)) continue;
      into.set(prop, value);
    }
    return into;
  }
  const ATTR = /([^\s"'>\/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;
  const TAG = /<!--[\s\S]*?(?:-->|$)|<!\[CDATA\[[\s\S]*?(?:\]\]>|$)|<[!?][^>]*>|<(\/?)([A-Za-z][\w:-]*)((?:\s+[^\s"'>\/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*)\s*(\/?)>/g;
  // cleaner(link, math): (html, {stack, source, text}) → безопасный HTML; stack — открытые теги
  function cleaner(link, mathText) {
    return function clean(html, o = {}) {
      const stack = o.stack || [], rules = [];
      String(html).replace(/<style\b[^>]*>([\s\S]*?)(<\/style>|$)/gi, (_, css) => {
        for (const m of css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{([^{}]*)\}/g))
          for (const sel of m[1].split(",").map(x => x.trim())) {
            const q = /^#([A-Za-z_][\w-]*)(?:\s+([a-z][a-z0-9]*))?$/.exec(sel);
            if (q) rules.push({ id: q[1], tag: q[2] || null, decls: m[2] });
          }
        return "";
      });
      let out = "", at = 0, skip = null, depth = 0, m;
      const text = t => { if (!skip && t) out += o.text ? o.text(t) : htmlText(t); };
      TAG.lastIndex = 0;
      while ((m = TAG.exec(html))) {
        text(html.slice(at, m.index)); at = TAG.lastIndex;
        if (!m[2]) continue;                                   // комментарии, <!doctype>, <?…>
        const close = m[1] === "/", raw = m[2].toLowerCase();
        if (skip) { if (raw === skip) depth += close ? -1 : (m[4] ? 0 : 1); if (!depth) skip = null; continue; }
        if (HTML_SKIP.has(raw)) { if (!close && !m[4]) { skip = raw; depth = 1; } continue; }
        const tag = raw === "font" || raw === "center" ? (raw === "font" ? "span" : "div") : raw;
        if (!HTML_KEEP.has(tag)) continue;                    // html, body, form, label, input… — только содержимое
        if (close) {                                           // закрываем только то, что открыли сами
          const i = stack.map(x => x.tag).lastIndexOf(tag);
          if (i >= 0) { for (const x of stack.splice(i).reverse()) out += `</${x.tag}>`; }
          continue;
        }
        const a = {};
        for (const [, name, v1, v2, v3] of (m[3] || "").matchAll(ATTR)) a[name.toLowerCase()] = decode(v1 ?? v2 ?? v3 ?? "");
        const style = new Map(), id = a.id || null, ids = stack.map(x => x.id);
        for (const r of rules) if (r.tag ? r.tag === tag && ids.includes(r.id) : r.id === id) cssDecls(r.decls, style);
        if (raw === "font" && /^#?\w{1,20}$/.test(a.color || "")) style.set("color", a.color);
        if (raw === "center") style.set("text-align", "center");
        cssDecls(a.style, style);
        let attrs = "";
        for (const name of ["colspan", "rowspan", "width", "height"]) if (/^\d{1,4}(px|%)?$/.test(a[name] || "")) attrs += ` ${name}="${a[name]}"`;
        for (const name of ["align", "valign"]) if (/^[a-z]{1,10}$/i.test(a[name] || "")) attrs += ` ${name}="${a[name]}"`;
        for (const name of ["title", "alt"]) if (a[name]) attrs += ` ${name}="${attr(a[name].slice(0, 300))}"`;
        if (tag === "details" && "open" in a) attrs += " open";
        if (tag === "a") {
          const href = (a.href || "").trim(), safe = /^https?:\/\//i.test(href) ? href : /^[a-z][a-z0-9+.-]*:|^\/\//i.test(href) ? null : link(href, false);
          if (safe) attrs += ` href="${attr(safe)}"` + (/^https?:/i.test(safe) ? ' target="_blank" rel="noopener noreferrer"' : "");
        }
        if (tag === "img") {
          const src = (a.src || "").trim();
          const safe = /^data:image\/(png|jpe?g|gif|webp|svg\+xml);base64,[\w+/=\s]+$/i.test(src) ? src.replace(/\s+/g, "")
            : /^https?:\/\//i.test(src) ? src : /^[a-z][a-z0-9+.-]*:|^\/\//i.test(src) || !src ? null : link(src, true);
          if (!safe) continue;
          attrs += ` src="${attr(safe)}"`;
        }
        if (style.size) attrs += ` style="${attr([...style].map(([k, v]) => `${k}:${v}`).join(";"))}"`;
        if (o.source) attrs += o.source;
        out += `<${tag}${attrs}>`;
        if (!HTML_VOID.has(tag) && !m[4]) stack.push({ tag, id });
      }
      text(html.slice(at));
      if (!o.stack) for (const x of stack.reverse()) out += `</${x.tag}>`;
      return out;
    };
  }

  function parser(document, libraries = root) {
    // HTML разрешён только в ноутбуках (как в Jupyter) и всегда проходит через clean();
    // в .md он по-прежнему показывается как текст.
    const notebook = /\.ipynb$/i.test(document);
    const md = libraries.markdownit({ html: notebook, linkify: true, typographer: false });
    // Notebook outputs arrive as data: images; allow raster and SVG there (an <img>
    // cannot run SVG scripts), everything else goes through markdown-it's own check.
    const validate = md.validateLink;
    md.validateLink = url => /^data:image\/(png|jpe?g|gif|webp|svg\+xml);base64,/i.test(url.trim()) || validate(url);
    const macros = {};
    const math = (tex, display) => libraries.katex.renderToString(tex, {
      displayMode: display, throwOnError: false, trust: false, strict: "ignore", maxExpand: 1000, macros
    });
    const escape = md.utils.escapeHtml;
    // формулы в тексте HTML-блоков (Jupyter рисует MathJax поверх всей ячейки)
    function mathText(t) {
      let out = "", i = 0;
      for (;;) {
        const j = t.slice(i).search(/\$|\\\(|\\\[/);
        if (j < 0) break;
        const at = i + j;
        if (escaped(t, at)) { out += htmlText(t.slice(i, at + 1)); i = at + 1; continue; }
        const [open, close, display] = t.startsWith("$$", at) ? ["$$", "$$", true] : t.startsWith("\\(", at) ? ["\\(", "\\)", false]
          : t.startsWith("\\[", at) ? ["\\[", "\\]", true] : ["$", "$", false];
        const end = closing(t, close, at + open.length);
        if (end < 0 || end === at + open.length || (open === "$" && /\s/.test(t[at + 1]))) { out += htmlText(t.slice(i, at + open.length)); i = at + open.length; continue; }
        const tex = decode(t.slice(at + open.length, end));
        out += htmlText(t.slice(i, at)) + `<span class="md-math${display ? " md-display" : ""}" data-tex="${attr(tex)}">${math(tex, display)}</span>`;
        i = end + close.length;
      }
      return out + htmlText(t.slice(i));
    }
    const clean = cleaner((value, image) => link(value, image), mathText);
    md.renderer.rules.html_block = (tokens, i, _options, env) => {
      const token = tokens[i], stack = env.htmlStack || (env.htmlStack = []);
      // граница ячейки ноутбука (chitalka/notebook.py): незакрытые теги ячейки закрываются, как в Jupyter
      if (/^<!--\s*chitalka:cell\s*-->\s*$/.test(token.content)) return stack.splice(0).reverse().map(x => `</${x.tag}>`).join("");
      const source = token.map ? ` data-source-start="${token.map[0] + 1}" data-source-end="${token.map[1]}"` : "";
      return clean(token.content, { stack, source, text: mathText });
    };
    md.renderer.rules.html_inline = (tokens, i, _options, env) =>
      tokens[i].meta === "chitalka" ? tokens[i].content : clean(tokens[i].content, { stack: env.htmlStack || (env.htmlStack = []) });
    function renderMath(token, display) {
      const tag = token.block ? "div" : "span";
      const source = token.map ? ` data-source-start="${token.map[0] + 1}" data-source-end="${token.map[1]}"` : "";
      return `<${tag} class="md-math${display ? " md-display" : ""}" data-tex="${escape(token.content)}"${source}>${math(token.content, display)}</${tag}>`;
    }
    // Parse math before Markdown escape/emphasis rules so TeX underscores and
    // backslashes are preserved. Code fences and code spans retain their own rules.
    md.inline.ruler.before("escape", "chitalka_math", (state, silent) => {
      const start = state.pos, src = state.src;
      let open, close, display = false;
      if (src.startsWith("\\(", start)) { open = "\\("; close = "\\)"; }
      else if (src.startsWith("\\[", start)) { open = "\\["; close = "\\]"; display = true; }
      else if (src.startsWith("$$", start)) { open = close = "$$"; display = true; }
      else if (src[start] === "$" && !/\s/.test(src[start + 1] || " ")) open = close = "$";
      else return false;
      let end = closing(src, close, start + open.length);
      // в .md «$5 и $10» — не формула (как в pandoc); в ноутбуке, как в Jupyter, `$x = 0 $` — формула
      while (open === "$" && end >= 0 && ((!notebook && /\s/.test(src[end - 1])) || /\d/.test(src[end + 1] || ""))) end = closing(src, close, end + 1);
      if (end < 0 || end === start + open.length || (!display && src.slice(start, end).includes("\n"))) return false;
      if (!silent) {
        const token = state.push(display ? "math_display_inline" : "math_inline", "", 0);
        token.content = src.slice(start + open.length, end);
      }
      state.pos = end + close.length;
      return true;
    });
    // до lheading: иначе «$$ / \\operatorname{A} / = / …» становится setext-заголовком
    md.block.ruler.before("lheading", "chitalka_math_block", (state, start, end, silent) => {
      if (state.sCount[start] - state.blkIndent >= 4) return false;
      const first = state.src.slice(state.bMarks[start] + state.tShift[start], state.eMarks[start]);
      const delimiter = first.startsWith("$$") ? "$$" : first.startsWith("\\[") ? "\\[" : null;
      if (!delimiter) return false;
      const close = delimiter === "$$" ? "$$" : "\\]";
      let line = start, body = first.slice(delimiter.length), at = closing(body, close, 0);
      // A display formula never spans a blank line (as in LaTeX): one stray "$$"
      // must not swallow the following paragraphs and headings.
      while (at < 0 && line + 1 < end && !state.isEmpty(line + 1)) {
        line++;
        body += "\n" + state.src.slice(state.bMarks[line] + state.tShift[line], state.eMarks[line]);
        at = closing(body, close, 0);
      }
      if (at < 0 || body.slice(at + close.length).trim()) return false;
      if (silent) return true;
      const token = state.push("math_block", "", 0);
      token.block = true; token.content = body.slice(0, at).trim(); token.map = [start, line + 1];
      state.line = line + 1;
      return true;
    }, { alt: ["paragraph", "reference", "blockquote", "list"] });
    md.renderer.rules.math_inline = (tokens, i) => renderMath(tokens[i], false);
    md.renderer.rules.math_display_inline = (tokens, i) => renderMath(tokens[i], true);
    md.renderer.rules.math_block = (tokens, i) => renderMath(tokens[i], true) + "\n";

    // Relative links resolve against the document inside the project root. URL()
    // would silently clamp "../../x.md" to "/x.md" — a different file — so the path
    // is normalised by hand and links leaving the root are disabled (null).
    function link(value, image) {
      if (!value || value.startsWith("#")) return value;
      if (/^[a-z][a-z0-9+.-]*:/i.test(value) || value.startsWith("//")) return value;  // external, mailto: …
      const [, rawPath, hash = ""] = value.match(/^([^?#]*)(?:\?[^#]*)?(#.*)?$/) || [];
      const parts = rawPath.startsWith("/") ? [] : document.split("/").slice(0, -1);
      for (const segment of rawPath.split("/")) {
        let name;
        try { name = decodeURIComponent(segment); } catch (_) { return null; }
        if (!name || name === ".") continue;
        if (name === "..") { if (!parts.length) return null; parts.pop(); }
        else parts.push(name);
      }
      const path = parts.join("/"), encoded = parts.map(encodeURIComponent).join("/");
      if (!path) return null;
      if (image) return "/assets/" + encoded;
      if (/\.(md|markdown|ipynb|pdf)$/i.test(path)) return "/?document=" + encodeURIComponent(path) + hash;
      return "/assets/" + encoded + hash;
    }
    const outside = "Ссылка ведёт за пределы проекта и отключена";
    const imageRule = md.renderer.rules.image;
    md.renderer.rules.image = (tokens, i, options, env, renderer) => {
      const src = link(tokens[i].attrGet("src"), true);
      if (src === null) { tokens[i].attrSet("src", ""); tokens[i].attrSet("title", outside); tokens[i].attrJoin("class", "md-outside"); }
      else tokens[i].attrSet("src", src);
      return imageRule(tokens, i, options, env, renderer);
    };
    md.renderer.rules.link_open = (tokens, i, options, _env, renderer) => {
      const token = tokens[i], href = link(token.attrGet("href"), false);
      if (href === null) {
        token.attrs = (token.attrs || []).filter(([name]) => name !== "href");
        token.attrSet("title", outside); token.attrJoin("class", "md-outside");
        return renderer.renderToken(tokens, i, options);
      }
      token.attrSet("href", href);
      if (/^(https?:)?\/\//i.test(token.attrGet("href") || "")) {
        token.attrSet("target", "_blank"); token.attrSet("rel", "noopener noreferrer");
      }
      return renderer.renderToken(tokens, i, options);
    };
    md.core.ruler.push("chitalka_source", state => {
      for (const [i, token] of state.tokens.entries()) {
        if (token.map && token.nesting !== -1) {
          token.attrSet("data-source-start", String(token.map[0] + 1));
          token.attrSet("data-source-end", String(token.map[1]));
        }
        if (token.type === "inline" && state.tokens[i - 2]?.type === "list_item_open" && token.children && /^\[[ xX]\] /.test(token.content)) {
          const first = token.children[0];
          if (first && first.type === "text" && /^\[[ xX]\] /.test(first.content)) {
            const check = new state.Token("html_inline", "", 0);
            check.content = `<input type="checkbox" disabled${/^\[[xX]\]/.test(first.content) ? " checked" : ""}> `; check.meta = "chitalka";
            first.content = first.content.slice(4); token.children.unshift(check);
          }
        }
      }
    });
    // The default fence renderer does not always put source-map attributes on <pre>.
    for (const name of ["fence", "code_block"]) {
      const original = md.renderer.rules[name];
      md.renderer.rules[name] = (tokens, i, ...rest) => {
        const token = tokens[i], map = token.map || [0, 1];
        // Jupyter cells (see chitalka/notebook.py): "python nb-in 3", "text nb-out", "text nb-err".
        const cell = /(?:^|\s)nb-(in|out|err|raw|html|widget)(?:\s+(\d+))?/.exec(token.info || "");
        const label = !cell ? "" : cell[1] === "in" ? `In [${cell[2] || " "}]` : cell[1] === "err" ? "stderr / ошибка" : cell[1] === "raw" ? "raw"
          : cell[1] === "widget" ? "виджет Jupyter · состояние в файле не сохранено" : "";
        if (cell && cell[1] === "html")
          return `<div class="nb-cell nb-html" data-source-start="${map[0] + 1}" data-source-end="${map[1]}">${clean(token.content)}</div>`;
        return `<div${cell ? ` class="nb-cell nb-${cell[1]}"` : ""} data-source-start="${map[0] + 1}" data-source-end="${map[1]}">` +
          (label ? `<span class="nb-label">${label}</span>` : "") + original(tokens, i, ...rest) + `</div>`;
      };
    }
    return md;
  }

  function render(text, document, libraries = root) {
    const md = parser(document, libraries), env = {}, tokens = md.parse(text, env);
    const sections = [], ids = new Map();
    let section = { title: document.split("/").pop(), level: 0, tokens: [], line: 1 };
    for (let i = 0; i < tokens.length; i++) {
      const token = tokens[i];
      // заголовок из HTML ноутбука (<h2>…</h2> в markdown-ячейке) тоже начинает раздел оглавления
      const html = token.type === "html_block" && token.level === 0 && /^\s*<h([1-6])\b[^>]*>([\s\S]*?)<\/h\1\s*>/i.exec(token.content);
      const htmlTitle = html && decode(html[2].replace(/<[^>]*>/g, "")).replace(/\s+/g, " ").trim();
      if ((token.type === "heading_open" && token.level === 0) || htmlTitle) {
        if (section.tokens.length) sections.push(section);
        let title = htmlTitle, level = html ? Number(html[1]) - 1 : Number(token.tag.slice(1)) - 1;
        if (!htmlTitle) {
          const inline = tokens[i + 1];
          title = inline.children.map(t => t.type === "text" || t.type === "code_inline" || t.type.startsWith("math") ? t.content : "").join("") || inline.content;
          const base = title.toLowerCase().replace(/[^\p{L}\p{N}_\s-]/gu, "").trim().replace(/\s+/g, "-") || "section";
          const count = ids.get(base) || 0; ids.set(base, count + 1);
          token.attrSet("id", base + (count ? "-" + count : ""));
        }
        section = { title, level, tokens: [], line: token.map[0] + 1 };
      }
      section.tokens.push(token);
    }
    if (section.tokens.length || !sections.length) sections.push(section);
    // каждый раздел разбирается браузером отдельно: незакрытый HTML не переходит в следующий
    return sections.map(s => ({ title: s.title, level: s.level, line: s.line,
      html: (env.htmlStack = [], md.renderer.render(s.tokens, md.options, env)) || '<p class="md-empty">Документ пуст.</p>' }));
  }

  const ignored = element => element.matches?.(".katex-mathml,annotation,.pnum,.hlLayer,.selLayer,.nb-label");
  function text(node) {
    if (node.nodeType === 3) return node.data;
    if (ignored(node)) return "";
    if (node.matches?.(".md-math")) return "$" + node.dataset.tex + "$";
    return Array.from(node.childNodes || []).map(text).join("");
  }
  function index(content, normChars) {
    let norm = ""; const own = [];
    function visit(node) {
      if (ignored(node)) return;
      const math = node.matches?.(".md-math");
      if (node.nodeType === 3 || math) {
        for (const [c, a, b] of normChars(math ? "$" + node.dataset.tex + "$" : node.data)) {
          norm += c; own.push({ node, a, b, math: !!math });
        }
      } else for (const child of node.childNodes || []) visit(child);
    }
    visit(content);
    return { norm, own, raw: text(content) };
  }
  function position(range, entry, start) {
    if (entry.math) { if (start) range.setStartBefore(entry.node); else range.setEndAfter(entry.node); }
    else if (start) range.setStart(entry.node, entry.a); else range.setEnd(entry.node, entry.b);
  }
  function rangeFor(ix, from, to) {
    if (!ix.own[from] || !ix.own[to - 1]) return null;
    const range = document.createRange();
    position(range, ix.own[from], true); position(range, ix.own[to - 1], false);
    return range;
  }
  function selection(range, states, normChars) {
    const spans = {};
    for (const [n, st] of states) {
      const ix = st.idx || (st.idx = index(st.el.querySelector(".md-content"), normChars));
      let from = -1, to = -1;
      ix.own.forEach((entry, at) => {
        let selected = false;
        try { selected = entry.math ? range.intersectsNode(entry.node)
          : range.comparePoint(entry.node, entry.a) >= 0 && range.comparePoint(entry.node, entry.b) <= 0; } catch (_) {}
        if (selected) { if (from < 0) from = at; to = at + 1; }
      });
      if (from >= 0) spans[n] = [from, to];
    }
    const pages = Object.keys(spans).map(Number);
    if (!pages.length) return null;
    const quote = pages.map(n => text(rangeFor(states.get(n).idx, ...spans[n]).cloneContents())).join(" ").replace(/\s+/g, " ").trim();
    const sourceNode = (entry, end) => {
      const element = entry.node.nodeType === 1 ? entry.node : entry.node.parentElement;
      const block = element.closest("[data-source-start]");
      return block ? Number(block.dataset[end ? "sourceEnd" : "sourceStart"]) : 1;
    };
    const first = pages[0], last = pages[pages.length - 1];
    const ix1 = states.get(first).idx, ix2 = states.get(last).idx;
    return { page: first, pageEnd: last, quote, spans,
      sourceLine: sourceNode(ix1.own[spans[first][0]], false),
      sourceLineEnd: sourceNode(ix2.own[spans[last][1] - 1], true),
      ctx: { before: ix1.norm.slice(Math.max(0, spans[first][0] - 30), spans[first][0]),
             after: ix2.norm.slice(spans[last][1], spans[last][1] + 30) } };
  }
  return { parser, render, text, index, rangeFor, selection };
});
