// Optional end-to-end test: see README for Playwright setup. No model calls.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const assert = require('node:assert/strict'), { spawn, execFileSync } = require('node:child_process');
const repo = path.resolve(__dirname, '..'), python = process.env.PYTHON || 'python3';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'chitalka-markdown-test-'));
fs.writeFileSync(path.join(root, 'paper.md'), fs.readFileSync(path.join(repo, 'examples/optimization.md')));
fs.writeFileSync(path.join(root, 'other.md'), '# Другой документ\n\nОтдельный текст.\n');
fs.writeFileSync(path.join(root, 'image.svg'), '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="30"><rect width="120" height="30" fill="teal"/></svg>');
const server = spawn(python, ['-u', '-c', `
from pathlib import Path
import sys
from chitalka.server import Config, serve
from chitalka.store import Store
root=Path(sys.argv[1])
server=serve(Config(root, root/'paper.md', Store(root/'kommentarii/kommentarii.json'), 'system-ui, sans-serif'), 0)
print('http://127.0.0.1:%s/' % server.server_port, flush=True)
server.serve_forever()
`, root], {cwd: repo, stdio: ['ignore', 'pipe', 'inherit']});
(async () => {
let browser;
try {
 const url = await new Promise((resolve, reject) => {
   const timeout = setTimeout(() => reject(new Error('Reader startup timeout')), 10000);
   server.once('error', error => { clearTimeout(timeout); reject(error); });
   server.stdout.once('data', data => { clearTimeout(timeout); resolve(data.toString().trim()); });
 });
 const cfg = {root, url};
 const macChrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
 const executablePath = process.env.CHROME || (fs.existsSync(macChrome) ? macChrome : undefined);
 browser = await chromium.launch({executablePath, headless: true});
const context=await browser.newContext({viewport:{width:1600,height:1100},colorScheme:'light'});
context.setDefaultTimeout(12000);
const page=await context.newPage(), errors=[],failed=[];
page.on('pageerror',e=>{errors.push(String(e));console.log('PAGEERROR',String(e))});page.on('response',r=>{if(r.status()>=400&&!r.url().endsWith('/favicon.ico'))failed.push(r.url()+':'+r.status())});
await page.goto(cfg.url);await page.waitForSelector('.md-content .katex');await page.waitForFunction(()=>pageState.size===3);
assert.equal(await page.locator('.katex-error').count(),0);
// Opening is read-only: no agent folder, memo or notes sidecar before the first save.
assert.ok(!fs.existsSync(path.join(root,'kommentarii')),'open must not create kommentarii/');
assert.ok(!fs.existsSync(path.join(root,'paper.md.notes.json')),'open must not create a notes sidecar');
assert.equal(await page.locator('table.md-content').count(),0);
await page.screenshot({path:path.join(os.tmpdir(), 'chitalka-markdown-light.png')});
const pending=await page.evaluate(()=>{
 const p=document.querySelector('#p2 .md-content p'),r=document.createRange();r.selectNodeContents(p);const s=window.getSelection();s.removeAllRanges();s.addRange(r);onSelection();return {...window.eval('pending')};
});
assert.ok(pending.quote.includes('$f\\colon'));
assert.equal(pending.sourceLine,7);assert.equal(pending.sourceLineEnd,7);
await page.waitForSelector('#selbar.show');await page.keyboard.press('c');await page.locator('.composer textarea.main').fill('Уточнить условия оценки');await page.keyboard.press('Control+Enter');
await page.waitForFunction(()=>comments.length===1&&!composer);
const comment=await page.evaluate(()=>comments[0]);assert.equal(comment.source.file,'paper.md');assert.equal(comment.source.line,7);
assert.ok(await page.locator('#p2 .mark').count()>0,'comment highlight');
assert.ok(fs.existsSync(path.join(root,'kommentarii/HOW_TO_USE_CHITALKA.md')),'memo appears with the first agent comment');
// Personal note (N): own sidecar, own tab and highlight, never an agent task.
await page.evaluate(()=>{const p=document.querySelector('#p1 .md-content p'),r=document.createRange();r.selectNodeContents(p);const s=window.getSelection();s.removeAllRanges();s.addRange(r);onSelection();});
await page.waitForSelector('#selbar.show .notebtn');await page.keyboard.press('n');
await page.waitForSelector('.note-editor textarea');assert.equal(await page.evaluate(()=>sideTab),'notes');
await page.locator('.note-editor textarea').fill('Моя мысль, не для агента');await page.keyboard.press('Control+Enter');
await page.waitForFunction(()=>notes.length===1&&!noteEditor);
const sidecar=JSON.parse(fs.readFileSync(path.join(root,'paper.md.notes.json'),'utf8'));
assert.equal(sidecar.notes[0].text,'Моя мысль, не для агента');assert.ok(sidecar.notes[0].quote.length>2);
assert.ok(await page.locator('.mark.note').count()>0,'note highlight');assert.ok(await page.locator('.note-card').count()===1);
assert.equal(await page.evaluate(()=>comments.length),1);
const agentView=execFileSync(python,['-m','chitalka','list','--all','--json','--root',root],{cwd:repo}).toString();
assert.ok(!agentView.includes('не для агента'),'notes never reach chitalka list');
assert.ok(!fs.readFileSync(path.join(root,'kommentarii/kommentarii.json'),'utf8').includes('не для агента'));
await page.locator('.note-card [data-na=edit]').click();await page.locator('.note-editor textarea').fill('Исправленная мысль');await page.keyboard.press('Control+Enter');
await page.waitForFunction(()=>notes[0].text==='Исправленная мысль'&&!noteEditor);
// N without a selection: a note to the current place, no quote.
await page.evaluate(()=>{window.getSelection().removeAllRanges();view.focus();});await page.keyboard.press('n');
await page.locator('.note-editor textarea').fill('Без выделения');await page.keyboard.press('Control+Enter');
await page.waitForFunction(()=>notes.length===2&&!noteEditor);
assert.equal(JSON.parse(fs.readFileSync(path.join(root,'paper.md.notes.json'),'utf8')).notes.length,2);
await page.locator('#sidetabs [data-t=comments]').click();assert.equal(await page.locator('.note-card').count(),0);
// Formula-only selection keeps the full TeX expression and the source block range.
const math=await page.evaluate(()=>{
 const m=document.querySelector('#p2 .md-display'),r=document.createRange();r.selectNodeContents(m.querySelector('.katex-html'));const s=window.getSelection();s.removeAllRanges();s.addRange(r);onSelection();const result={...pending};hideSelbar();s.removeAllRanges();return result;
});
assert.equal(math.sourceLine,9);assert.equal(math.sourceLineEnd,14);assert.ok(math.quote.includes('\\begin{aligned}'));
// CLI reply is visible in the same sidebar.
execFileSync(python,['-m','chitalka','reply',comment.id,'Условия уточнены','--root',cfg.root],{cwd:repo});
await page.evaluate(()=>loadComments(false));await page.locator('[data-f=answered]').click();assert.ok((await page.locator('#list').innerText()).includes('Условия уточнены'));
await page.locator('#q').fill('гладкую');await page.waitForFunction(()=>sHits.length>0);assert.ok(await page.locator('#sres a').count()>0);
await page.locator('#q').fill('');await page.keyboard.press('Escape');await page.locator('#zin').click();assert.equal(await page.locator('#zval').innerText(),'115%');await page.locator('#zfit').click();
await page.evaluate(()=>cycleTheme());await page.screenshot({path:path.join(os.tmpdir(), 'chitalka-markdown-dark.png')});
await page.setViewportSize({width:760,height:1000});
await page.waitForFunction(()=>document.querySelector('#view').clientWidth>=750);
await page.screenshot({path:path.join(os.tmpdir(), 'chitalka-markdown-narrow.png')});
const widths=await page.locator('#view').evaluate(el=>({scroll:el.scrollWidth,width:el.clientWidth,page:document.querySelector('.markdown-page').getBoundingClientRect().toJSON(),content:document.querySelector('.md-content').getBoundingClientRect().toJSON()}));assert.ok(widths.scroll<=widths.width+1,JSON.stringify(widths));
await page.setViewportSize({width:1600,height:1100});
// Two documents share a server but comments stay scoped.
const other=await context.newPage();await other.goto(cfg.url+'?document=other.md');await other.waitForSelector('.md-content');assert.equal(await other.locator('.md-content').innerText(),'Другой документ\n\nОтдельный текст.');assert.equal(await other.evaluate(()=>comments.length),0);await other.close();
fs.appendFileSync(cfg.root+'/paper.md','\n\n![Local image](image.svg)\n\nАвтообновление проверено.\n');
await page.waitForSelector('.md-content img',{timeout:15000});await page.waitForFunction(()=>document.querySelector('.md-content img').naturalWidth>0);assert.equal(await page.locator('.md-content img').evaluate(n=>n.naturalWidth),120);assert.ok((await page.locator('#pages').innerText()).includes('Автообновление проверено.'));
// Changes while composing do not discard input; stale source anchors are rejected.
await page.evaluate(()=>{const p=document.querySelector('#p3 .md-content p'),r=document.createRange();r.selectNodeContents(p);const s=window.getSelection();s.removeAllRanges();s.addRange(r);onSelection();startComposer('ask')});
await page.locator('.composer textarea.main').fill('Черновик должен сохраниться');fs.appendFileSync(cfg.root+'/paper.md','\nИзменение во время комментария.\n');await page.evaluate(async()=>{await pollPdf();await pollPdf()});
assert.equal(await page.locator('.composer textarea.main').inputValue(),'Черновик должен сохраниться');await page.keyboard.press('Control+Enter');await page.waitForFunction(()=>document.querySelector('#toasts').textContent.includes('Markdown изменился'));assert.ok(await page.locator('.composer').count());
await page.evaluate(()=>closeComposer(false));
const current=fs.readFileSync(cfg.root+'/paper.md','utf8');
fs.writeFileSync(cfg.root+'/paper.md',current.replace(/^Рассмотрим гладкую.*$/m,'Новая постановка задачи.'));
await page.waitForFunction(()=>comments[0]._stale===true,{},{timeout:15000});
assert.deepEqual(errors,[]);assert.deepEqual(failed.filter(s=>!s.includes('/api/comments:409')),[]);
console.log(JSON.stringify({passed:true,pages:3,math:await page.locator('.md-math').count(),source:comment.source,errors,failed}));
} finally {
 if (browser) await browser.close();
 if (server.exitCode === null) { server.kill('SIGTERM'); await new Promise(resolve => server.once('exit', resolve)); }
 fs.rmSync(root, {recursive: true, force: true});
}
})().catch(error => { console.error(error); process.exitCode = 1; });
