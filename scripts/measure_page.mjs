import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {slideHTML,slideCSS} from '../static/deck.mjs';

const object=value=>value&&typeof value==='object'&&!Array.isArray(value);
const validId=value=>typeof value==='string'&&/^[A-Za-z][A-Za-z0-9_-]{0,47}$/.test(value);

function measurementInput(payload){
  if(!object(payload))throw new Error('Invalid measurement');
  const project={...(object(payload.project)?payload.project:payload)};
  let slide=payload.slide;
  if(payload.page){
    slide={id:'measure',status:'ready',content:{title:project.title||'',page:payload.page}};
  }else if(!slide&&project.slides?.length===1)slide=project.slides[0];
  if(!object(slide))throw new Error('Expected one page');
  if(!slide.content&&slide.nodes)slide={id:'measure',status:'ready',content:{page:slide}};
  else if(!slide.content&&slide.page)slide={id:'measure',status:'ready',content:slide};
  const source=slide.page_draft||slide.content?.page;
  if(!object(source)||!Array.isArray(source.nodes)||!source.nodes.length||source.nodes.length>200)throw new Error('Expected V2 page');
  const page={...source,nodes:source.nodes.map(node=>object(node)?{...node,parent:node.parent||'root'}:node)};
  const tree=new Map([['root',{kind:'group',depth:0}]]);
  for(const node of page.nodes){
    if(!object(node)||!validId(node.id)||!['group','heading','text','code','image','diagram'].includes(node.kind))throw new Error('Invalid node');
    const parent=tree.get(node.parent||'root');
    if(tree.has(node.id)||parent?.kind!=='group'||parent.depth>=8)throw new Error('Invalid tree');
    tree.set(node.id,{kind:node.kind,depth:parent.depth+1});
  }
  if(page.nodes.reduce((length,node)=>length+String(node.text||'').length,0)>60000)throw new Error('Page too large');
  slide=slide.page_draft?{...slide,page_draft:page}:{...slide,content:{...slide.content,page}};
  project.slides=[slide];
  project._media_dimensions=payload._media_dimensions||project._media_dimensions||{};
  return {project,slide,page};
}

export async function measurePage(payload){
  const {project,slide,page:spec}=measurementInput(payload);
  process.env.PLAYWRIGHT_BROWSERS_PATH ||= fileURLToPath(new URL('../runtime/browsers',import.meta.url));
  const {chromium}=await import('playwright-chromium');
  const {loadMathStyles,measureLayouts,exportPageFormat}=await import('./export.mjs');
  const format=exportPageFormat(project),urls={assets:{}},unknownMedia=[];
  let knownMedia=0;
  for(const node of spec.nodes.filter(node=>['image','diagram'].includes(node.kind))){
    const dim=project._media_dimensions[node.asset_id]||project._media_dimensions[node.id];
    const valid=dim&&Number.isFinite(dim.width)&&Number.isFinite(dim.height)&&dim.width>0&&dim.height>0&&dim.width<=100000&&dim.height<=100000;
    if(!node.asset_id||!valid){unknownMedia.push(node.id);continue}
    // The placeholder contains no markup from the request: only two validated
    // dimensions. It measures known media proportions without loading files.
    urls.assets[node.asset_id]='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="'+dim.width+'" height="'+dim.height+'"></svg>');
    knownMedia++;
  }
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage({viewport:{width:format.width,height:format.height}});
    await page.route('**/*',route=>route.abort());
    await page.setContent('<!doctype html><meta charset="utf-8"><style>'+await loadMathStyles()+slideCSS+'html,body{margin:0}</style>'+slideHTML(project,slide,0,urls),{waitUntil:'load'});
    await page.evaluate(()=>document.fonts.ready);
    await page.evaluate(()=>Promise.all([...document.images].map(image=>image.decode())));
    const [layout]=await measureLayouts(page);
    const nodes=await page.locator('.slide-frame').evaluate(frame=>{
      const origin=frame.getBoundingClientRect(),footer=frame.querySelector('.footer').getBoundingClientRect();
      const rounded=value=>Math.round(value*100)/100;
      return [...frame.querySelectorAll('.v2-node')].flatMap(node=>{
        const bounds=node.getBoundingClientRect(),reasons=[];
        if(bounds.left<origin.left-2||bounds.right>origin.right+2||node.scrollWidth>node.clientWidth+2)reasons.push('horizontal');
        if(bounds.bottom>origin.bottom+2||bounds.top<origin.top-2)reasons.push('vertical');
        if(bounds.bottom>footer.top+2)reasons.push('footer');
        if(!reasons.length)return [];
        return [{id:node.dataset.pageNode,kind:node.dataset.nodeKind,reasons,
          x:rounded(bounds.x-origin.x),y:rounded(bounds.y-origin.y),width:rounded(bounds.width),height:rounded(bounds.height),
          scrollWidth:node.scrollWidth,scrollHeight:node.scrollHeight}];
      }).slice(0,30);
    });
    return {width:format.width,height:layout.height,overflow:layout.overflow||nodes.length>0,
      neededHeight:layout.neededHeight,baseHeight:layout.baseHeight,maxHeight:layout.maxHeight,fontScale:layout.fontScale,
      format:format.format,adjusted:layout.adjusted,compact:layout.compact,reflowed:layout.reflowed,
      mediaOverflow:layout.mediaOverflow,nodes,knownMedia,unknownMedia};
  }finally{await browser.close()}
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  try{
    let input='';
    for await(const chunk of process.stdin){input+=chunk;if(Buffer.byteLength(input)>4*1024*1024)throw new Error('Input too large')}
    process.stdout.write(JSON.stringify(await measurePage(JSON.parse(input))));
  }catch{
    process.stderr.write('Misurazione della pagina non riuscita.\n');process.exitCode=1;
  }
}
