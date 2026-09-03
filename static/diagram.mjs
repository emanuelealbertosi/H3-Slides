const escapeXml=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function diagramGeometry(spec) {
  const labels=(spec?.labels||[]).slice(0,5), n=labels.length;
  if(!['flow','cycle','comparison'].includes(spec?.kind)||n<2)return null;
  let nodes=[];
  if(spec.kind==='flow')nodes=labels.map((label,i)=>({label,x:280,y:40+i*320/(n-1),w:420,h:58}));
  if(spec.kind==='comparison')nodes=labels.map((label,i)=>({label,x:n===2?280:145+(i%2)*270,y:n===2?105+i*190:65+Math.floor(i/2)*130,w:n===2?450:245,h:104}));
  if(spec.kind==='cycle')nodes=labels.map((label,i)=>({label,x:280+180*Math.cos(-Math.PI/2+2*Math.PI*i/n),y:200+136*Math.sin(-Math.PI/2+2*Math.PI*i/n),w:172,h:58}));
  const edges=[];
  if(spec.kind!=='comparison'){
    for(let i=0;i<(spec.kind==='cycle'?n:n-1);i++){
      const a=nodes[i],b=nodes[(i+1)%n],dx=b.x-a.x,dy=b.y-a.y;
      const ta=1/Math.max(Math.abs(dx)/(a.w/2+4),Math.abs(dy)/(a.h/2+4));
      const tb=1/Math.max(Math.abs(dx)/(b.w/2+7),Math.abs(dy)/(b.h/2+7));
      edges.push({x1:a.x+dx*ta,y1:a.y+dy*ta,x2:b.x-dx*tb,y2:b.y-dy*tb});
    }
  }
  return {nodes,edges};
}
export function diagramSVG(spec,theme={bg:'#fff',fg:'#17243a',accent:'#18794e'}){
  const g=diagramGeometry(spec);if(!g)return '';
  const safeColor=(v,f)=>/^#[0-9a-f]{6}$/i.test(v)?v:f;
  const bg=safeColor(theme.bg,'#ffffff'),fg=safeColor(theme.fg,'#17243a'),accent=safeColor(theme.accent,'#18794e');
  const lines=label=>{
    const words=String(label).split(/\s+/),result=[''];const width=spec.kind==='cycle'?16:spec.kind==='comparison'?22:38;
    for(const word of words){let last=result.length-1;if(result[last].length&&result[last].length+word.length+1>width)result.push(word);else result[last]+=(result[last]?' ':'')+word}
    return result;
  };
  return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 400" role="img" aria-label="'+escapeXml(spec.labels.join(' → '))+'">'+
    '<defs><marker id="h3arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="'+accent+'"/></marker></defs>'+
    g.edges.map(e=>'<line x1="'+e.x1+'" y1="'+e.y1+'" x2="'+e.x2+'" y2="'+e.y2+'" stroke="'+accent+'" stroke-width="3" marker-end="url(#h3arrow)"/>').join('')+
    g.nodes.map(a=>{const rows=lines(a.label),step=Math.min(20,(a.h-12)/rows.length),font=Math.min(18,step*.9,(a.w-16)/Math.max(...rows.map(r=>r.length))/.62);return '<rect x="'+(a.x-a.w/2)+'" y="'+(a.y-a.h/2)+'" width="'+a.w+'" height="'+a.h+'" rx="12" fill="'+bg+'" stroke="'+accent+'" stroke-width="2"/><text x="'+a.x+'" y="'+(a.y-(rows.length-1)*step/2)+'" text-anchor="middle" dominant-baseline="middle" fill="'+fg+'" font-family="Arial" font-size="'+font+'">'+rows.map((line,i)=>'<tspan x="'+a.x+'" dy="'+(i?step:'0')+'">'+escapeXml(line)+'</tspan>').join('')+'</text>'}).join('')+'</svg>';
}
