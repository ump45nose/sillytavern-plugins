import {useEffect,useLayoutEffect,useState} from "react";

export const motionAllowed=()=>!matchMedia("(prefers-reduced-motion: reduce)").matches&&!document.body.classList.contains("reduced-motion");
/** Retain the real component through its exit; do not clone its native inputs or handlers. */
export function usePresence<T>(value:T|null, duration=180){
 const [retained,setRetained]=useState(value),[exiting,setExiting]=useState(false);
 useLayoutEffect(()=>{
  if(value!==null){setRetained(value);setExiting(false);return;}
  if(!motionAllowed()){setRetained(null);setExiting(false);return;}
  setExiting(true);const timer=setTimeout(()=>{setRetained(null);setExiting(false);},duration);
  return()=>clearTimeout(timer);
 },[value,duration]);
 return {value:value??retained,exiting:value===null&&exiting};
}

/** Make a short click visible after pointer-up, without delaying the native action. */
export function ClickFeedback(){
 useEffect(()=>{
  const running=new Map<HTMLElement,Animation>();
  const clear=()=>{running.forEach((a,node)=>{delete node.dataset.wbClickMotion;a.cancel();});running.clear();};
  const click=(event:MouseEvent)=>{
   const node=event.target instanceof Element?event.target.closest<HTMLElement>('button,[role=button],.menu_button,.qr--action,input[type=checkbox],input[type=radio]'):null;
   if(!node||!motionAllowed()||!node.closest('.wb-ui,#send_form,#chat .mes')||node.closest('#tavern_helper,[inert]')||node.matches(':disabled,[aria-disabled=true]'))return;
   // Keep long row labels fixed; pulse their icon or their paper surface instead.
   const wide=node.getBoundingClientRect().width>100,surface=wide?node.querySelector<HTMLElement>('svg')||node:node;
   running.get(surface)?.cancel();const base=getComputedStyle(surface).boxShadow;
   const frames=wide&&surface===node?[{boxShadow:base},{boxShadow:'inset 0 0 0 1px color-mix(in srgb,var(--wb-accent) 35%,transparent)',offset:.4},{boxShadow:base}]:[{scale:.94},{scale:1.015,offset:.65},{scale:1}];
   const animation=surface.animate(frames,{duration:240,easing:'cubic-bezier(.22,.8,.3,1)'});
   running.set(surface,animation);surface.dataset.wbClickMotion='true';
   const finish=()=>{if(running.get(surface)===animation){running.delete(surface);delete surface.dataset.wbClickMotion;}};animation.onfinish=finish;animation.oncancel=finish;
  };
  const media=matchMedia('(prefers-reduced-motion: reduce)'),reduce=()=>{if(!motionAllowed())clear();};
  const observer=new MutationObserver(reduce);observer.observe(document.body,{attributes:true,attributeFilter:['class']});
  document.addEventListener('click',click,true);media.addEventListener('change',reduce);
  return()=>{document.removeEventListener('click',click,true);media.removeEventListener('change',reduce);observer.disconnect();clear();};
 },[]);
 return null;
}
