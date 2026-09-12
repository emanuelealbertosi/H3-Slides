import {slideHTML,fitSlide} from './deck.mjs';

// Measure edited content with exactly the renderer used by preview and export.
// The stage never replaces the live DOM, selection or in-progress text edit.
export function fitEditedContent(project,slide,index=0,{rejectOverflow=true,anchorKey,resizeKey,resizeHandle,resizeFallback}={}){
  const content=structuredClone(slide.content);
  const stage=document.createElement('div');
  stage.style.cssText='position:fixed;left:-100000px;top:0;width:1280px;visibility:hidden;pointer-events:none';
  const asset=id=>id?'/api/assets/'+encodeURIComponent(project.id)+'/'+encodeURIComponent(id):'';
  stage.innerHTML=slideHTML(project,{...slide,content},index,{
    diagram:asset(slide.diagram_render?.asset),image:asset(content.image_id)});
  document.body.append(stage);
  try{
    const result=fitSlide(stage.querySelector('.slide-frame'),{anchorKey,resizeKey,resizeHandle,resizeFallback});
    if(result.overflow&&rejectOverflow)throw new Error(
      'Il contenuto non entra senza tagli o sovrapposizioni. Allarga il box, scegli Adattivo o usa Dividi in più slide. La modifica non è stata salvata.');
    content.canvas_height=result.height;
    if(content.layout==='freeform'&&result.placements){
      content.freeform={...(content.freeform||{}),...result.placements};
      // Inactive media positions also remain legal when switching to 16:9.
      for(const [key,placement] of Object.entries(content.freeform)){
        if(Object.hasOwn(result.placements,key))continue;
        const bottom=result.height-40,w=Math.min(1280,placement.w),h=Math.min(bottom,placement.h);
        content.freeform[key]={x:Math.max(0,Math.min(1280-w,placement.x)),
          y:Math.max(0,Math.min(bottom-h,placement.y)),w,h};
      }
    }
    return {content,result};
  }finally{stage.remove()}
}

export function layoutUpdatesFor(project){
  return project.slides.filter(slide=>slide.content?.layout==='freeform').map(slide=>{
    const {content}=fitEditedContent(project,slide,project.slides.indexOf(slide));
    return {id:slide.id,revision:slide.revision,canvas_height:content.canvas_height,freeform:content.freeform};
  });
}
