import './browser-env.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright-chromium';
import JSZip from 'jszip';
import {verifyVendor} from '../scripts/vendor-pptxgenjs.mjs';
import {verifyDependencies} from '../scripts/dependency-check.mjs';
import {buildExports,measureLayouts} from '../scripts/export.mjs';
import {slideCSS,slideHTML} from '../static/deck.mjs';

process.env.PLAYWRIGHT_BROWSERS_PATH ||= fileURLToPath(new URL('../runtime/browsers',import.meta.url));

test('upstream executable bytes and license remain intact in the local distribution',async()=>{
  const manifest=await verifyVendor();
  assert.equal(manifest.upstream.version,'4.0.1');
  assert.match(manifest.upstream.integrity,/^sha512-/);
  assert.ok(manifest.sha256.LICENSE);
});

test('H3-Slides and both Slidev consumers resolve the patched distribution without image-size',async()=>{
  assert.deepEqual(await verifyDependencies(),{consumers:3,version:'4.0.1-h3.1',imageSize:false});
});

const makeProject=id=>({title:'Immagine di prova',theme:'paper',template:'auto',use_source_images:true,slides:[{content:{
  title:'Una figura mantiene le proporzioni',subtitle:'Dimensioni lette dall immagine decodificata.',
  layout:'visual-left',bullets:['Il contenuto rimane modificabile.'],blocks:[],sources:[],image_id:id,
  diagram:{kind:'none',labels:[]},
}}]});

test('decoded image dimensions preserve portrait and landscape ratios in native PPTX and PDF',async()=>{
  const browser=await chromium.launch({headless:true});
  const out=await fs.mkdtemp(path.join(os.tmpdir(),'h3-dimensions-'));
  try{
    const page=await browser.newPage();
    for(const [width,height] of [[240,120],[90,270]]){
      const data=await page.evaluate(([w,h])=>{
        const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;
        const ctx=canvas.getContext('2d');ctx.fillStyle='#246890';ctx.fillRect(0,0,w,h);
        return canvas.toDataURL('image/jpeg');
      },[width,height]);
      const id=width+'-'+height+'.jpg',project=makeProject(id);
      await fs.writeFile(path.join(out,id),Buffer.from(data.split(',')[1],'base64'));
      await page.setContent('<style>'+slideCSS+'</style>'+slideHTML(project,project.slides[0],0,data));
      await page.evaluate(()=>Promise.all([...document.images].map(i=>i.decode())));
      const [layout]=await measureLayouts(page);
      assert.deepEqual(layout.image,{width,height});
      const output=await buildExports(project,out,path.join(out,id+'-export'),'pptx');
      const zip=await JSZip.loadAsync(await fs.readFile(output));
      const xml=await zip.file('ppt/slides/slide1.xml').async('string');
      const picture=xml.match(/<p:pic>[\s\S]*?<\/p:pic>/)?.[0];
      assert.ok(picture,'Native image missing from PPTX');
      const [,cx,cy]=picture.match(/<a:ext cx="(\d+)" cy="(\d+)"/);
      assert.ok(Math.abs(Number(cx)/Number(cy)-width/height)<.001,'PPTX image stretched');
      assert.ok((await fs.stat(await buildExports(project,out,path.join(out,id+'-export'),'pdf'))).size>500);
    }
  }finally{await browser.close();}
});

test('malformed ICNS, HEIF and JXL data is rejected without entering the removed parsers', {timeout:30000},async()=>{
  const out=await fs.mkdtemp(path.join(os.tmpdir(),'h3-rejected-formats-'));
  const icns=Buffer.alloc(16);icns.write('icns');icns.writeUInt32BE(16,4);icns.write('icp4',8);
  const heif=Buffer.alloc(32);heif.writeUInt32BE(24,0);heif.write('ftypheic',4);heif.write('meta',28);
  const jxl=Buffer.alloc(20);Buffer.from([0,0,0,12,74,88,76,32,13,10,135,10]).copy(jxl);jxl.write('jxlc',16);
  for(const [i,bytes] of [icns,heif,jxl].entries()){
    const id=(i+1)+'.jpg';
    await fs.writeFile(path.join(out,id),bytes);
    for(const format of ['pdf','pptx'])
      await assert.rejects(()=>buildExports(makeProject(id),out,path.join(out,id+'-export'),format),/decod/i);
  }
});
