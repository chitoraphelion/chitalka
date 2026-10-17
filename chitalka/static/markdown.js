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

  function parser(document, libraries = root) {
    const md = libraries.markdownit({ html: false, linkify: true, typographer: false });
    // Notebook outputs arrive as data: images; allow raster and SVG there (an <img>
    // cannot run SVG scripts), everything else goes through markdown-it's own check.
    const validate = md.validateLink;
    md.validateLink = url => /^data:image\/(png|jpe?g|gif|webp|svg\+xml);base64,/i.test(url.trim()) || validate(url);
    const macros = {};
    const math = (tex, display) => libraries.katex.renderToString(tex, {
      displayMode: display, throwOnError: false, trust: false, strict: "ignore", maxExpand: 1000, macros
    });
    const escape = md.utils.escapeHtml;
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
      while (open === "$" && end >= 0 && (/\s/.test(src[end - 1]) || /\d/.test(src[end + 1] || ""))) end = closing(src, close, end + 1);
      if (end < 0 || end === start + open.length || (!display && src.slice(start, end).includes("\n"))) return false;
      if (!silent) {
        const token = state.push(display ? "math_display_inline" : "math_inline", "", 0);
        token.content = src.slice(start + open.length, end);
      }
      state.pos = end + close.length;
      return true;
    });
    md.block.ruler.before("paragraph", "chitalka_math_block", (state, start, end, silent) => {
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
            check.content = `<input type="checkbox" disabled${/^\[[xX]\]/.test(first.content) ? " checked" : ""}> `;
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
        const cell = /(?:^|\s)nb-(in|out|err|raw)(?:\s+(\d+))?/.exec(token.info || "");
        const label = !cell ? "" : cell[1] === "in" ? `In [${cell[2] || " "}]` : cell[1] === "err" ? "stderr / ошибка" : cell[1] === "raw" ? "raw" : "";
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
      if (token.type === "heading_open" && token.level === 0) {
        if (section.tokens.length) sections.push(section);
        const inline = tokens[i + 1];
        const title = inline.children.map(t => t.type === "text" || t.type === "code_inline" || t.type.startsWith("math") ? t.content : "").join("") || inline.content;
        const base = title.toLowerCase().replace(/[^\p{L}\p{N}_\s-]/gu, "").trim().replace(/\s+/g, "-") || "section";
        const count = ids.get(base) || 0; ids.set(base, count + 1);
        token.attrSet("id", base + (count ? "-" + count : ""));
        section = { title, level: Number(token.tag.slice(1)) - 1, tokens: [], line: token.map[0] + 1 };
      }
      section.tokens.push(token);
    }
    if (section.tokens.length || !sections.length) sections.push(section);
    return sections.map(s => ({ title: s.title, level: s.level, line: s.line,
      html: md.renderer.render(s.tokens, md.options, env) || '<p class="md-empty">Документ пуст.</p>' }));
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
