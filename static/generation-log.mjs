// Follow new events inside the log, without scrolling the page or interrupting
// someone reading earlier lines. Hidden/collapsed panels catch up when shown.
export function createGenerationLog(element){
  let jobId=null,follow=true,pending=0;
  const visible=()=>element.clientHeight>0&&element.getClientRects().length>0;
  const atBottom=()=>element.scrollHeight-element.clientHeight-element.scrollTop<=12;
  const tail=()=>{
    if(!follow||pending)return;
    pending=requestAnimationFrame(()=>{
      pending=0;
      if(follow&&visible())element.scrollTop=element.scrollHeight;
    });
  };
  element.addEventListener('scroll',()=>{
    if(visible()&&!pending)follow=atBottom();
  },{passive:true});
  element.closest('details')?.addEventListener('toggle',tail);
  const observer=new ResizeObserver(tail);
  observer.observe(element);
  return {
    update(id,text){
      const changedJob=id!==jobId,previousTop=element.scrollTop;
      if(changedJob){jobId=id;follow=true}
      else if(visible()&&!pending)follow=atBottom();
      // Leave unchanged text nodes and user selections intact on normal polls.
      if(element.textContent!==text)element.textContent=text;
      if(follow)tail();
      else if(visible())element.scrollTop=previousTop;
    },
  };
}
