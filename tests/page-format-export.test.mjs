import './browser-env.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync,spawnSync} from 'node:child_process';
import JSZip from 'jszip';
import {chromium} from 'playwright-chromium';
import {slideHTML,slideCSS} from '../static/deck.mjs';
import {buildExports,measureLayouts,exportCanvasHeight} from '../scripts/export.mjs';

const root=fileURLToPath(new URL('..',import.meta.url));
const nominal={'16:9':720,'4:3':960,'16:10':800,'1:1':1280};
const title='Il formato resta coerente';
const body='Questo testo deve restare interamente leggibile e modificabile.';
const makeProject=(format,canvas_mode='fixed')=>({title:'Formati V2',engine:'v2',slide_format:format,canvas_mode,theme:'paper',font:'Arial',
  theme_design:{visual_family:'editorial',heading_font:'Georgia',background_style:'gradient',secondary_color:'#e7efff',decoration:'stripe'},
  slides:[{id:'one',status:'ready',content:{title,blocks:[],bullets:[],sources:[],diagram:{kind:'none'},page:{version:2,style:{gap:28},nodes:[
    {id:'title',parent:'root',kind:'heading',role:'title',text:title,style:{font_size:46}},
    {id:'text',parent:'root',kind:'text',role:'body',text:body,style:{font_size:26,padding:24,surface:'soft'}},
    {id:'end',parent:'root',kind:'text',role:'caption',text:'Ultima riga presente.',style:{font_size:18}},
  ]}}}]});
const runSource=project=>JSON.parse(execFileSync(process.execPath,[path.join(root,'scripts/slidev_source.mjs')],{input:JSON.stringify(project),encoding:'utf8',cwd:root,windowsHide:true,timeout:45000,maxBuffer:8*1024*1024}));
const measure=payload=>JSON.parse(execFileSync(process.execPath,[path.join(root,'scripts/measure_page.mjs')],{input:JSON.stringify(payload),encoding:'utf8',cwd:root,windowsHide:true,timeout:45000,maxBuffer:1024*1024}));
const pdfProbe='import fitz,json,sys; d=fitz.open(sys.argv[1]); print(json.dumps([{ "width":p.rect.width,"height":p.rect.height,"text":p.get_text()} for p in d]))';

test('fixed V2 formats match exactly in measurement, PDF, editable PowerPoint and Slidev',async()=>{
  await fs.mkdir(path.join(root,'logs'),{recursive:true});
  const out=await fs.mkdtemp(path.join(root,'logs/page-format-export-'));
  for(const [format,height] of Object.entries(nominal)){
    const project=makeProject(format),report=measure(project),directory=path.join(out,format.replace(':','-'));
    assert.equal(report.width,1280);assert.equal(report.height,height);assert.equal(report.baseHeight,height);
    assert.equal(report.maxHeight,height);assert.equal(report.overflow,false);assert.equal(report.fontScale,1);
    const pdf=await buildExports(project,out,path.join(directory,'pdf'),'pdf');
    const parsed=JSON.parse(execFileSync(path.join(root,'.venv/Scripts/python.exe'),['-B','-c',pdfProbe,pdf],{encoding:'utf8',windowsHide:true}).trim().split('\n').findLast(line=>line.startsWith('[')));
    assert.equal(parsed.length,1);assert.equal(parsed[0].width,960);assert.equal(parsed[0].height,height*.75);
    assert.ok(parsed[0].text.includes(title)&&parsed[0].text.includes(body)&&parsed[0].text.includes('Ultima riga presente.'));
    const pptx=await buildExports(project,out,path.join(directory,'pptx'),'pptx');
    const zip=await JSZip.loadAsync(await fs.readFile(pptx)),presentation=await zip.file('ppt/presentation.xml').async('string');
    assert.ok(presentation.includes('<p:sldSz cx="'+1280*9525+'" cy="'+height*9525+'"'));
    const xml=await zip.file('ppt/slides/slide1.xml').async('string');
    for(const value of [title,body,'Ultima riga presente.'])assert.ok(xml.includes('<a:t>'+value+'</a:t>'),'PowerPoint retains editable text');
    const slidev=runSource(project);
    assert.deepEqual(slidev.overflow,[]);
    assert.ok(slidev.markdown.includes('aspectRatio: '+(height===720?'16/9':'1280/'+height)));
    assert.ok(slidev.markdown.includes('data-page-base-height="'+height+'"'));
    assert.ok(slidev.markdown.includes(body)&&slidev.markdown.includes('Ultima riga presente.'));
  }
});

test('oversized V2 content stays bounded, reports node IDs without source text, and never exports clipped content',async()=>{
  const project=makeProject('16:9','adaptive'),secret='private-source-sentinel';
  project.slides[0].content.page.nodes.push({id:'too-long',parent:'root',kind:'text',text:(secret+' Una riga da conservare.\n').repeat(800),style:{font_size:26}});
  const report=measure({project,page:project.slides[0].content.page});
  assert.equal(report.baseHeight,720);assert.equal(report.maxHeight,828);assert.ok(report.height<=828);
  assert.equal(report.overflow,true);assert.ok(report.neededHeight>report.maxHeight);
  assert.ok(report.nodes.some(node=>node.id==='too-long'));
  assert.ok(!JSON.stringify(report).includes(secret));
  const out=await fs.mkdtemp(path.join(root,'logs/page-format-overflow-'));
  for(const format of ['pdf','pptx']){
    const target=path.join(out,format);
    await assert.rejects(buildExports(project,out,target,format),/Testo fuori dallo spazio/);
    await assert.rejects(fs.access(path.join(target,'presentazione.'+format)));
  }
  assert.throws(()=>runSource(project),/Testo fuori dallo spazio/);
  const fixed=measure({...project,canvas_mode:'fixed'});
  assert.equal(fixed.height,720);assert.equal(fixed.maxHeight,720);assert.equal(fixed.overflow,true);
});

test('measurement accepts compact page input and uses only known media proportions',()=>{
  const project=makeProject('4:3','adaptive'),page=project.slides[0].content.page,asset='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jpg';
  page.nodes=page.nodes.map(({parent,...node})=>node);
  page.nodes.push({id:'photo',kind:'image',asset_id:asset,text:'',style:{}});
  const unknown=measure({project,page});
  assert.equal(unknown.knownMedia,0);assert.deepEqual(unknown.unknownMedia,['photo']);
  const known=measure({project,page,_media_dimensions:{[asset]:{width:1800,height:900}}});
  assert.equal(known.knownMedia,1);assert.deepEqual(known.unknownMedia,[]);
  assert.equal(known.baseHeight,960);assert.equal(known.maxHeight,1104);assert.ok(known.height<=1104);
  const invalid=spawnSync(process.execPath,[path.join(root,'scripts/measure_page.mjs')],{input:JSON.stringify({project,page:{nodes:[{id:'bad',kind:'script',text:'do-not-echo-this'}]}}),encoding:'utf8',cwd:root,windowsHide:true,timeout:45000});
  assert.equal(invalid.status,1);assert.equal(invalid.stdout,'');assert.equal(invalid.stderr,'Misurazione della pagina non riuscita.\n');
});

test('common export canvas cannot enlarge V2 beyond its allowed format to accommodate classic slides',async()=>{
  const project=makeProject('16:9','adaptive');
  assert.throws(()=>exportCanvasHeight(project,[{engine:'v2',height:828,maxHeight:828},{engine:'classic',height:1008}]),/limite del 15%/);
  assert.equal(exportCanvasHeight(project,[{engine:'v2',height:800,maxHeight:828},{engine:'classic',height:720}]),800);
  const classic={content:{title:'Una slide classica',bullets:[body],blocks:[],diagram:{kind:'none'}}};
  const mixed={...makeProject('4:3'),slides:[classic,...project.slides]};
  await assert.rejects(buildExports(mixed,'unused','unused','pdf'),/richiedono pagine V2/);
});

test('repeated V2 measurement keeps the same bounded geometry and font sizes',async()=>{
  const project=makeProject('1:1','adaptive'),browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage();
    await page.setContent('<style>'+slideCSS+'</style>'+slideHTML(project,project.slides[0],0));
    await page.evaluate(()=>document.fonts.ready);
    const [first]=await measureLayouts(page),[second]=await measureLayouts(page,{targetHeight:first.height});
    assert.equal(first.height,1280);assert.equal(first.maxHeight,1472);assert.equal(second.height,first.height);
    assert.equal(second.fontScale,first.fontScale);assert.deepEqual(second.texts.map(text=>text.size),first.texts.map(text=>text.size));
  }finally{await browser.close()}
});

test('adaptive V2 PDF keeps bounded page heights while PowerPoint and Slidev share one bounded canvas',async()=>{
  const project={...makeProject('16:9','adaptive'),theme_design:{}};
  const code='def esempio():\n'+Array.from({length:30},(_,i)=>'    print("riga '+i+'")').join('\n');
  const long=structuredClone(project.slides[0]);
  long.id='long';long.content.page.nodes=[
    {id:'title',parent:'root',kind:'heading',text:'Codice completo',style:{font_size:46}},
    {id:'code',parent:'root',kind:'code',language:'python',text:code,style:{font_size:24,padding:24,surface:'dark'}},
  ];
  project.slides.push(long);
  const report=measure({project,slide:long});
  assert.equal(report.overflow,false);assert.ok(report.height>720&&report.height<=828);assert.ok(report.fontScale<1);
  const out=await fs.mkdtemp(path.join(root,'logs/page-format-adaptive-'));
  await buildExports(project,out,path.join(out,'pdf'),'pdf');
  const pdfLayout=JSON.parse(await fs.readFile(path.join(out,'pdf/layout-report.json'),'utf8'));
  assert.equal(pdfLayout[0].height,720);assert.equal(pdfLayout[1].height,report.height);
  const pptx=await buildExports(project,out,path.join(out,'pptx'),'pptx');
  const pptxLayout=JSON.parse(await fs.readFile(path.join(out,'pptx/layout-report.json'),'utf8'));
  assert.ok(pptxLayout.every(page=>page.height===report.height&&!page.overflow&&page.height<=page.maxHeight));
  const zip=await JSZip.loadAsync(await fs.readFile(pptx));
  assert.ok((await zip.file('ppt/slides/slide2.xml').async('string')).includes('riga 29'),'The final code line remains native PowerPoint text');
  const source=runSource(project),articles=source.markdown.match(/<article\b[\s\S]*?<\/article>/g);
  assert.ok(source.markdown.includes('aspectRatio: 1280/'+report.height));
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage();
    await page.setContent('<style>'+source.css+'</style>'+articles.join(''));
    await page.evaluate(()=>document.fonts.ready);
    const frozen=await page.locator('.slide-frame').evaluateAll(frames=>frames.map(frame=>({height:frame.offsetHeight,fonts:[...frame.querySelectorAll('.v2-text')].map(text=>getComputedStyle(text).fontSize)})));
    const loaded=await measureLayouts(page,{targetHeight:report.height});
    assert.ok(loaded.every(layout=>layout.height===report.height&&!layout.overflow));
    assert.deepEqual(loaded.map(layout=>layout.texts.filter(text=>!['Formati V2','01','02'].includes(text.value)).map(text=>text.size/.75+'px')),frozen.map(frame=>frame.fonts),'Frozen Slidev text does not shrink again');
  }finally{await browser.close()}
});
