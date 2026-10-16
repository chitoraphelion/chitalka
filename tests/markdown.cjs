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
