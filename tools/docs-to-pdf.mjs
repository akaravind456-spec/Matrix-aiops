// Usage: npm i marked@12.0.2 ; node docs-to-pdf.mjs <docs folder> <output folder>   (needs Google Chrome; diagrams load mermaid from the internet)
import { marked } from 'marked';
import fs from 'fs'; import path from 'path'; import { execFileSync } from 'child_process'; import { pathToFileURL } from 'url';
const SRC = process.argv[2], OUT = process.argv[3];
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const css = `body{font-family:Segoe UI,Arial,sans-serif;font-size:11pt;line-height:1.45;color:#1b1f24;margin:0}
h1{font-size:22pt;border-bottom:2px solid #4458d8;padding-bottom:6px}h2{font-size:15pt;margin-top:22px;color:#2b3aa0}h3{font-size:12.5pt}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:9.5pt}th,td{border:1px solid #c9ced8;padding:5px 7px;text-align:left;vertical-align:top}th{background:#eef0fb}
code{background:#f1f3f6;padding:1px 4px;border-radius:3px;font-size:9.5pt}pre{background:#f1f3f6;padding:10px;border-radius:6px;overflow:auto;white-space:pre-wrap;font-size:9pt}
img{max-width:100%;border:1px solid #d5d9e2;border-radius:4px;margin:8px 0;page-break-inside:avoid}blockquote{border-left:4px solid #c9ced8;margin-left:0;padding-left:12px;color:#444}
.mermaid{text-align:center;page-break-inside:avoid}@page{margin:16mm 14mm}`;
function walk(d){return fs.readdirSync(d,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(path.join(d,e.name)):[path.join(d,e.name)]);}
const files = walk(SRC).filter(f=>f.endsWith('.md'));
const tmp = path.join(OUT,'_tmp'); fs.mkdirSync(tmp,{recursive:true});
for (const f of files) {
  const rel = path.relative(SRC,f); const outPdf = path.join(OUT, rel.replace(/\.md$/,'.pdf'));
  fs.mkdirSync(path.dirname(outPdf),{recursive:true});
  let md = fs.readFileSync(f,'utf8');
  const renderer = new marked.Renderer();
  const origCode = renderer.code.bind(renderer);
  renderer.code = (text, lang) => lang==='mermaid' ? `<div class="mermaid">${text}</div>` : `<pre><code>${String(text).replace(/&/g,'&amp;').replace(/</g,'&lt;')}</code></pre>`;
  let html = marked.parse(md,{renderer, gfm:true});
  html = html.replace(/href="([^"#:]+)\.md(#[^"]*)?"/g,(m,p,h)=>`href="${p}.pdf${h||''}"`);
  const doc = `<!doctype html><html><head><meta charset="utf-8"><base href="${pathToFileURL(path.dirname(f)).href}/"><style>${css}</style></head><body>${html}
<script type="module">import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.esm.min.mjs';mermaid.initialize({startOnLoad:false,theme:'neutral'});await mermaid.run();document.title='done';</script></body></html>`;
  const hp = path.join(tmp, rel.split(path.sep).join('_')+'.html'); fs.writeFileSync(hp,doc);
  const hasM = md.includes('```mermaid');
  try { execFileSync(CHROME,['--headless=new','--disable-gpu','--no-sandbox','--allow-file-access-from-files',`--virtual-time-budget=${hasM?20000:6000}`,'--no-pdf-header-footer',`--print-to-pdf=${outPdf}`,pathToFileURL(hp).href],{stdio:'ignore',timeout:90000}); console.log('ok',rel,fs.statSync(outPdf).size); }
  catch(e){ console.log('FAIL',rel,String(e.message).slice(0,80)); }
}
