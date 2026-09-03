// Maintainer utility. Default: verify only, without network. --import: reproduce
// the small distribution-only patch from the pinned upstream npm tarball.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';

const root=fileURLToPath(new URL('../',import.meta.url));
const destination=path.join(root,'vendor','pptxgenjs');
const upstream={
  version:'4.0.1',
  url:'https://registry.npmjs.org/pptxgenjs/-/pptxgenjs-4.0.1.tgz',
  integrity:'sha512-TeJISr8wouAuXw4C1F/mC33xbZs/FuEG6nH9FG1Zj+nuPcGMP5YRHl6X+j3HSUnS1f3at6k75ZZXPMZlA5Lj9A==',
};
const files=['dist/pptxgen.cjs.js','dist/pptxgen.es.js','types/index.d.ts','LICENSE','README.md'];
const hash=data=>createHash('sha256').update(data).digest('hex');
const pretty=data=>JSON.stringify(data,null,2)+'\n';

export async function verifyVendor(){
  const manifest=JSON.parse(await fs.readFile(path.join(destination,'provenance.json'),'utf8'));
  if(JSON.stringify(manifest.upstream)!==JSON.stringify(upstream))throw Error('Unexpected vendor provenance');
  for(const file of [...files,'package.json']){
    const actual=hash(await fs.readFile(path.join(destination,file)));
    if(actual!==manifest.sha256[file])throw Error('Vendored file changed: '+file);
  }
  const pkg=JSON.parse(await fs.readFile(path.join(destination,'package.json'),'utf8'));
  if(pkg.name!=='pptxgenjs'||pkg.version!=='4.0.1-h3.1'||'image-size' in pkg.dependencies)
    throw Error('Unexpected patched package or vulnerable dependency');
  return manifest;
}

async function importVendor(){
  try{await fs.access(destination);throw Error('Vendor folder already exists: import never overwrites it');}
  catch(error){if(error.code!=='ENOENT')throw error;}
  const logs=path.join(root,'logs');
  await fs.mkdir(logs,{recursive:true});
  const staging=await fs.mkdtemp(path.join(logs,'vendor-import-'));
  const response=await fetch(upstream.url,{signal:AbortSignal.timeout(120000)});
  if(!response.ok)throw Error('Upstream download failed: '+response.status);
  const archive=Buffer.from(await response.arrayBuffer());
  if('sha512-'+createHash('sha512').update(archive).digest('base64')!==upstream.integrity)
    throw Error('Upstream tarball integrity mismatch');
  const archivePath=path.join(staging,'upstream.tgz');
  await fs.writeFile(archivePath,archive);
  // The verified archive is unpacked into a new task-owned folder; never the app.
  execFileSync('tar',['-xzf',archivePath,'-C',staging],{windowsHide:true});
  const source=path.join(staging,'package');
  const pkg=JSON.parse(await fs.readFile(path.join(source,'package.json'),'utf8'));
  if(pkg.name!=='pptxgenjs'||pkg.version!==upstream.version||pkg.dependencies['image-size']!=='^1.2.1')
    throw Error('Unexpected upstream metadata: review the patch before continuing');
  pkg.version='4.0.1-h3.1';
  delete pkg.dependencies['image-size'];
  delete pkg.browser['image-size'];
  // This checked-in distribution is consumed, not built or published to npm.
  delete pkg.devDependencies;
  delete pkg.scripts;
  pkg.private=true;
  const manifest={upstream,patch:'4.0.1-h3.1: remove unused image-size dependency; executable files unchanged',
    changes:['version','dependencies.image-size','browser.image-size','devDependencies','scripts','private'],sha256:{}};
  await fs.mkdir(destination,{recursive:true});
  for(const file of files){
    const bytes=await fs.readFile(path.join(source,file));
    manifest.sha256[file]=hash(bytes);
    await fs.mkdir(path.dirname(path.join(destination,file)),{recursive:true});
    await fs.copyFile(path.join(source,file),path.join(destination,file));
  }
  const metadata=pretty(pkg);
  manifest.sha256['package.json']=hash(metadata);
  await fs.writeFile(path.join(destination,'package.json'),metadata);
  await fs.writeFile(path.join(destination,'provenance.json'),pretty(manifest));
  await verifyVendor();
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  if(process.argv.includes('--import'))await importVendor();
  else await verifyVendor();
  console.log('PPTXGenJS vendored files verified; upstream executable bytes unchanged.');
}
