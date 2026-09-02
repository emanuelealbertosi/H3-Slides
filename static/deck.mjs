export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const themes = {
  ink: {bg:'#141b2c',fg:'#f6f7fb',muted:'#c1c9d8',accent:'#b1f1ce'},
  paper: {bg:'#ffffff',fg:'#17243a',muted:'#526078',accent:'#18794e'},
  forest: {bg:'#153e35',fg:'#f6faf5',muted:'#d0dfd7',accent:'#e2edb0'}
};
export const slideCSS = '*{box-sizing:border-box}.slide-frame{width:1280px;height:720px;position:relative;padding:58px 70px;overflow:hidden;font-family:Arial,sans-serif;background:var(--bg);color:var(--fg)}'+
'.slide-frame h1{font-size:50px;line-height:1.1;letter-spacing:-1.5px;margin:0 0 22px;max-height:116px;overflow:hidden}.slide-frame.cover h1{font-size:66px;max-height:224px;max-width:1050px}'+
'.slide-frame.cover{display:flex;flex-direction:column;justify-content:center}.slide-frame.statement{display:flex;flex-direction:column;justify-content:center}.slide-frame .subtitle{font-size:26px;line-height:1.35;color:var(--muted);margin:0 0 24px}'+
'.slide-frame .slide-columns{display:flex;gap:44px;flex:1;min-height:0}.slide-frame .copy{flex:1;min-width:0}.slide-frame ul{padding-left:28px;margin:6px 0;display:grid;gap:20px}'+
'.slide-frame li{font-size:26px;line-height:1.3;padding-left:7px}.slide-frame li::marker{color:var(--accent)}.slide-frame .visual{width:43%;height:380px;object-fit:contain;align-self:center}'+
'.slide-frame .footer{position:absolute;bottom:24px;left:70px;right:70px;display:flex;justify-content:space-between;font-size:14px;color:var(--muted)}';
export function slideHTML(project, slide, index, imageUrl='') {
  const c=slide.content, theme=themes[project.theme]||themes.ink;
  const style=Object.entries(theme).map(([k,v])=>'--'+k+':'+v).join(';');
  return '<article class="slide-frame '+esc(c.layout)+'" style="'+style+'">'+
    '<h1>'+esc(c.title)+'</h1>'+
    (c.subtitle?'<p class="subtitle">'+esc(c.subtitle)+'</p>':'')+
    '<div class="slide-columns"><div class="copy"><ul>'+c.bullets.map(b=>'<li>'+esc(b)+'</li>').join('')+'</ul></div>'+
    (imageUrl?'<img class="visual" src="'+esc(imageUrl)+'" alt="">':'')+'</div>'+
    '<div class="footer"><span>'+esc(project.title)+'</span><span>'+String(index+1).padStart(2,'0')+'</span></div></article>';
}
