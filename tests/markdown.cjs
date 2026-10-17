const assert = require('node:assert/strict');
const { render } = require('../chitalka/static/markdown.js');
const libraries = { markdownit: require('../chitalka/static/vendor/markdown-it.min.js'), katex: require('../chitalka/static/vendor/katex.min.js') };
const html = source => render(source, 'notes/paper.md', libraries).map(s => s.html).join('');
let result = html('# Заголовок\n\n**bold** *italic* ~~removed~~ `x_i`\n\n> quote\n\n- [x] done\n- [ ] todo\n\na | b\n--|--\n1 | 2\n\n```python\nprint("$x$")\n```');
for (const tag of ['<strong>', '<em>', '<s>', '<blockquote', '<table', 'class="language-python"', 'type="checkbox" disabled checked']) assert.ok(result.includes(tag), tag);
assert.ok(!html('[x] ordinary paragraph').includes('checkbox'));
result = html(String.raw`Inline $x_i^2$ and \(\alpha\), display $$\sum_{i=1}^n i$$ and \[\frac{a}{b}\].

$$
\begin{aligned}
f(x)&=\|Ax-b\|^2\\
\nabla f(x)&=2A^\top(Ax-b)
\end{aligned}
$$`);
assert.equal((result.match(/class="md-math/g) || []).length, 5);
assert.equal((result.match(/md-display/g) || []).length, 3);
assert.ok(!result.includes('katex-error'));
assert.ok(!html('`$x$`\n\n```tex\n$$x$$\n```').includes('md-math'));
assert.ok(!html(String.raw`Cost \$5 and $10, then $20.`).includes('md-math'));
result = html('<script>alert(1)</script>\n\n[x](javascript:alert%281%29)\n\n$\\href{javascript:alert(1)}{x}$');
assert.ok(!result.includes('<script>'));
assert.ok(!result.includes('href="javascript:'));
result = html('![image](fig/a.png) [next](next.md#part) [pdf](../paper.pdf) [web](https://example.org)');
assert.ok(result.includes('src="/assets/notes/fig/a.png"'));
assert.ok(result.includes('href="/?document=notes%2Fnext.md#part"'));
assert.ok(result.includes('href="/?document=paper.pdf"'));
assert.ok(result.includes('rel="noopener noreferrer"'));
const sections = render('# A\n\nText\n\n## B\n\nMore\n\n## B', 'paper.md', libraries);
assert.deepEqual(sections.map(s => [s.title, s.level, s.line]), [['A', 0, 1], ['B', 1, 5], ['B', 1, 9]]);
assert.ok(sections[1].html.includes('id="b"'));
assert.ok(sections[2].html.includes('id="b-1"'));
assert.ok(sections[0].html.includes('data-source-start="3" data-source-end="3"'));
assert.ok(html('$\\frac{$').includes('katex-error'));
assert.ok(html('').includes('Документ пуст'));
// A stray "$$" must not swallow the following paragraphs and headings.
const stray = render('$$ typo\n\nParagraph.\n\n## Head\n\nMore\n\n$$\n', 'paper.md', libraries);
assert.equal(stray.length, 2); assert.ok(stray[1].html.includes('<h2'));
// Links leaving the project root are disabled instead of silently retargeted.
result = html('[up](../../../etc/x.md) ![img](../../../etc/p.png) [ok](../paper.pdf)');
assert.ok(!result.includes('etc%2Fx.md') && !result.includes('/assets/etc/p.png'));
assert.equal((result.match(/md-outside/g) || []).length, 2);
assert.ok(result.includes('href="/?document=paper.pdf"'));
console.log('Markdown renderer: formatting, math, source maps, links and untrusted input passed');
// Notebooks (.ipynb): HTML as in Jupyter, but rebuilt from a whitelist; .md keeps HTML as text.
{
  const nb = source => render(source, 'hw/nb.ipynb', libraries).map(s => s.html).join('');
  let out = nb('<div onclick="alert(1)" id="view" class="page" style="color:red;position:fixed;background:url(//x)"><script>alert(1)</script>' +
    '<img src=x onerror=alert(1)><img src="javascript:alert(1)"><a href="java&#115;cript:alert(1)">x</a><a href="https://e.com/">ok</a><iframe src="//e"></iframe></div>');
  for (const bad of ['onclick', 'onerror', 'id="view"', 'class="page"', 'position', 'url(', '<script', 'alert(1)<', 'javascript', '<iframe']) assert.ok(!out.includes(bad), bad + ' in ' + out);
  assert.ok(out.includes('style="color:red"') && out.includes('href="https://e.com/" target="_blank"'));
  out = nb('<details>\n<summary>Подсказка $x^2$</summary>\n\nТекст $y$.\n\n</details>');
  assert.ok(/<details[^>]*>\s*<summary[^>]*>Подсказка <span class="md-math"[\s\S]*<p[^>]*>Текст <span class="md-math"[\s\S]*<\/p>\s*<\/details>/.test(out), out);
  out = nb('<div style="color:red">\n\nвнутри\n\n<!-- chitalka:cell -->\n\nследующая');
  assert.ok(/<\/div><p[^>]*>следующая/.test(out), 'unclosed HTML is closed at the cell boundary');
  out = nb('<style>#T_a_row0_col0 { background-color: #3787c0 }</style><table id="T_a"><tr><td id="T_a_row0_col0">1</td></tr></table>');
  assert.ok(/<td style="background-color:#3787c0"[^>]*>1<\/td>/.test(out) && !out.includes('<style'), out);
  assert.equal(render('<h2>Задание <b>1</b></h2>\n\nтекст', 'nb.ipynb', libraries)[0].title, 'Задание 1');
  assert.ok(!nb('$a = 0 $, то $b$').includes('katex-error'), 'Jupyter-style $…$ with inner trailing space');
  assert.ok(html('<b>x</b>').includes('&lt;b&gt;'), '.md keeps HTML as text');
  assert.ok(!html('Cost $5 and $10.').includes('md-math'));
}
console.log('Notebook HTML: whitelist, cell boundaries, Styler, headings passed');
assert.ok(!render('$$\n\\operatorname{A}\n=\n\\frac{1}{2}\n$$', 'x.md', libraries)[0].html.includes('<h1'), 'a "=" line inside $$ is not a setext heading');
assert.equal(render('$$\n\\operatorname{A}\n=\n1\n$$\n\n# H', 'x.md', libraries).length, 2);
console.log('Display math before setext headings passed');
