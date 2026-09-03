import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {verifyVendor} from './vendor-pptxgenjs.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
export async function verifyDependencies(){
  await verifyVendor();
  const lock=JSON.parse(await fs.readFile(path.join(root,'package-lock.json'),'utf8'));
  for(const [name,pkg] of Object.entries(lock.packages)){
    if(/(^|\/)node_modules\/image-size$/.test(name)||pkg.dependencies?.['image-size'])
      throw Error('image-size ancora presente nel lock: riesegui l aggiornamento delle dipendenze.');
  }
  const expected=await fs.realpath(path.join(root,'vendor/pptxgenjs/dist/pptxgen.cjs.js'));
  const consumers=['package.json','node_modules/@slidev/cli/package.json','node_modules/@slidev/client/package.json'];
  for(const consumer of consumers){
    const context=createRequire(path.join(root,consumer));
    const resolved=await fs.realpath(context.resolve('pptxgenjs'));
    if(resolved!==expected)throw Error('PPTXGenJS non aggiornato per '+consumer+': esegui Installa-H3-slides.bat.');
    let legacy;
    try{legacy=context.resolve('image-size');}
    catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
    if(legacy)throw Error('Vecchia image-size ancora raggiungibile: esegui una installazione pulita (npm ci).');
    // Resolve and load the exact package consumed by each caller, not just the lock.
    if(typeof context('pptxgenjs')!=='function')throw Error('PPTXGenJS non caricabile');
  }
  return {consumers:consumers.length,version:'4.0.1-h3.1',imageSize:false};
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  await verifyDependencies();
  console.log('H3-Slides e Slidev usano PPTXGenJS verificato; image-size assente dal lock e dalla risoluzione runtime.');
}
