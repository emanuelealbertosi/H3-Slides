import './browser-env.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {chromium} from 'playwright-chromium';
import JSZip from 'jszip';
import {slideHTML,slideCSS} from '../static/deck.mjs';
import {buildExports,measureLayouts} from '../scripts/export.mjs';

const root=fileURLToPath(new URL('..',import.meta.url));
const python=path.join(root,'.venv/Scripts/python.exe');
const title='Una gerarchia visiva chiara';
const body='Ogni parola rimane selezionabile e modificabile.';
const projectFor=design=>({title:'Verifica temi',theme:'paper',font:'Arial',engine:'v2',canvas_mode:'adaptive',
  background_color:'#fbf5ea',accent_color:'#304c8f',theme_design:design,visual_assets:[],slides:[{id:'one',status:'ready',content:{
    title,bullets:[],blocks:[],sources:[],diagram:{kind:'none'},page:{version:2,style:{gap:28},nodes:[
      {id:'heading',parent:'root',kind:'heading',role:'title',text:title,style:{font_size:44}},
      {id:'body',parent:'root',kind:'text',role:'body',text:body,style:{font_size:26}},
      {id:'card',parent:'root',kind:'group',role:'callout',style:{surface:'gradient',padding:26,radius:20,gap:16},text:''},
      {id:'card-heading',parent:'card',kind:'heading',role:'subtitle',text:'Un esempio concreto',style:{font_size:30}},
      {id:'card-body',parent:'card',kind:'text',role:'body',text:'Lo sfondo e il testo restano elementi separati.',style:{font_size:24}},
    ]}},revision:1}]});
const themes=[
  {visual_family:'editorial',background_style:'gradient',secondary_color:'#d8e9f5',heading_font:'Georgia',decoration:'stripe',shadow_style:'soft'},
  {visual_family:'modern',background_style:'flat',secondary_color:'#d3e7df',heading_font:'Verdana',decoration:'corner',shadow_style:'lifted'},
];
const rgb=value=>value.match(/\d+/g).slice(0,3).map(Number);
const hex=value=>rgb(value).map(v=>v.toString(16).padStart(2,'0')).join('').toUpperCase();
const probe=`import fitz,json,sys,base64
payload=json.load(sys.stdin)
doc=fitz.open(payload['pdf'])
pages=[]
for page in doc:
    pix=page.get_pixmap(matrix=fitz.Matrix(4/3,4/3),alpha=False)
    spans=[span for block in page.get_text('dict')['blocks'] if 'lines' in block for line in block['lines'] for span in line['spans']]
    pages.append({'text':page.get_text(),'fonts':[span['font'] for span in spans], 'edges':[pix.pixel(4,pix.height//2),pix.pixel(pix.width-5,pix.height//2)],'outside':[b for b in page.get_text('blocks') if b[6]==0 and (b[0]<-1 or b[1]<-1 or b[2]>page.rect.width+1 or b[3]>page.rect.height+1)]})
images=[]
for encoded in payload['images']:
    pix=fitz.Pixmap(base64.b64decode(encoded))
    samples=[]
    for rx in [.25,.5,.75]:
        for ry in [.25,.5,.75]:
            x,y=int(pix.width*rx),int(pix.height*ry)
            samples.append({'x':x,'y':y,'pixel':pix.pixel(x,y)})
    images.append({'width':pix.width,'height':pix.height,'samples':samples,'corner':pix.pixel(0,0)})
print(json.dumps({'pages':pages,'images':images}))`;

test('rich V2 themes retain gradient backgrounds, native decorations and editable text in PDF and PowerPoint',async()=>{
  await fs.mkdir(path.join(root,'logs'),{recursive:true});
  const out=await fs.mkdtemp(path.join(root,'logs/theme-v2-export-'));
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:720}});
    for(const design of themes){
      const project=projectFor(design);
      await page.setContent('<style>'+slideCSS+'html,body{margin:0}</style>'+slideHTML(project,project.slides[0],0));
      await page.evaluate(()=>document.fonts.ready);
      const [layout]=await measureLayouts(page);
      assert.equal(layout.overflow,false);
      const heading=layout.texts.find(item=>item.value===title);
      assert.equal(heading.font,design.heading_font,'Heading font must come from the rendered theme');
      assert.equal(Boolean(layout.background.gradient),design.background_style==='gradient');
      const decoration=layout.boxes.find(box=>box.decoration===design.decoration);
      assert.ok(decoration,'The real decoration element is included in export measurements');
      const gradients=[layout.background,...layout.boxes].filter(box=>box.gradient);
      assert.ok(gradients.some(box=>box!==layout.background),'A rounded card gradient is measured separately');
      const pdf=await buildExports(project,out,path.join(out,design.visual_family,'pdf'),'pdf');
      const pptx=await buildExports(project,out,path.join(out,design.visual_family,'pptx'),'pptx');
      const zip=await JSZip.loadAsync(await fs.readFile(pptx));
      const xml=await zip.file('ppt/slides/slide1.xml').async('string');
      const nativeTexts=[...xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)].map(match=>match[0]);
      for(const text of layout.texts){
        const shape=nativeTexts.find(shape=>shape.includes('<a:t>'+text.value+'</a:t>'));
        assert.ok(shape,'Native editable text is missing: '+text.value);
        assert.ok(shape.includes('typeface="'+text.font+'"'));
        assert.ok(shape.toUpperCase().includes('VAL="'+hex(text.color)+'"'),'Text color agrees with the browser');
      }
      assert.equal((xml.match(/<p:pic>/g)||[]).length,gradients.length,'Only gradient backgrounds become images');
      assert.match(xml,new RegExp('<a:outerShdw[^>]*dist="'+(design.shadow_style==='lifted'?16:8)*9525+'"'),'Native shadows preserve the theme offset');
      if(design.decoration==='stripe')assert.ok(nativeTexts.some(shape=>shape.toUpperCase().includes('VAL="'+hex(decoration.color)+'"')),'Stripe is a native shape');
      else assert.ok((xml.match(/<a:ln w="28575"/g)||[]).length>=2,'Corner has two native 3px border lines');
      const images=await Promise.all(Object.values(zip.files).filter(file=>/^ppt\/media\/.*\.png$/.test(file.name)).map(file=>file.async('base64')));
      const result=JSON.parse(execFileSync(python,['-B','-c',probe],{input:JSON.stringify({pdf,images}),encoding:'utf8',windowsHide:true}).trim().split('\n').findLast(line=>line.startsWith('{')));
      assert.equal(result.pages.length,1);
      assert.ok(result.pages[0].text.includes(title)&&result.pages[0].text.includes(body),'PDF text remains selectable');
      assert.deepEqual(result.pages[0].outside,[]);
      assert.ok(result.pages[0].fonts.some(font=>font.includes(design.heading_font)),'PDF preserves the heading font');
      if(layout.background.gradient)assert.notDeepEqual(...result.pages[0].edges,'PDF prints the actual gradient');
      else assert.deepEqual(...result.pages[0].edges,'The flat theme remains flat');
      assert.equal(result.images.length,gradients.length);
      result.images.forEach((image,index)=>{
        const box=gradients[index],[start,end]=box.gradient.map(rgb);
        assert.equal(image.width,Math.ceil(box.w*192));
        assert.equal(image.height,Math.ceil(box.h*192));
        if(box.radii.every(radius=>radius>0))assert.equal(image.corner[3],0,'Rounded backgrounds keep transparent corners');
        for(const sample of image.samples){
          const t=((sample.x+.5)*box.w/image.width+(sample.y+.5)*box.h/image.height)/(box.w+box.h);
          start.forEach((value,channel)=>assert.ok(Math.abs(sample.pixel[channel]-(value+(end[channel]-value)*t))<=2,
            'Background pixels contain only the smooth gradient, including beneath the editable text'));
        }
      });
    }
  }finally{await browser.close()}
});

test('PowerPoint measurements accept only application-generated two-stop gradients',async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage();
    const project=projectFor(themes[0]);
    await page.setContent('<style>'+slideCSS+'</style>'+slideHTML(project,project.slides[0],0));
    const frame=page.locator('.slide-frame');
    for(const backgroundImage of ['linear-gradient(90deg,#112233 0%,#445566 100%)','radial-gradient(#112233,#445566)','linear-gradient(135deg,#112233 0%,#445566 50%,#778899 100%)']){
      await frame.evaluate((element,value)=>{element.dataset.v2Gradient='true';element.style.backgroundImage=value},backgroundImage);
      assert.equal((await measureLayouts(page))[0].background.gradient,null);
    }
    await frame.evaluate(element=>{element.dataset.v2Gradient='true';element.style.backgroundImage='linear-gradient(135deg,#112233 0%,#445566 100%)'});
    assert.deepEqual((await measureLayouts(page))[0].background.gradient,['rgb(17, 34, 51)','rgb(68, 85, 102)']);
    await frame.evaluate(element=>delete element.dataset.v2Gradient);
    assert.equal((await measureLayouts(page))[0].background.gradient,null,'Unmarked background images are not reused');
  }finally{await browser.close()}
});
