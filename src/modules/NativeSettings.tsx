import React,{useEffect,useLayoutEffect,useReducer,useRef,useState} from "react";
import {createPortal} from "react-dom";
import type {HostAdapter} from "../host/adapter";
import {Select} from "../ui/Select";
import {Notice,Field} from "../ui/common";
import {nativeGlyphs} from "../ui/NativeGlyph";
import type {LucideIcon} from "lucide-react";
type Section={label:string;selectors:string[]};
export const nativePages:Record<string,{id:string;sections:Section[]}>={
 connection:{id:"rm_api_block",sections:[{label:"服务与凭据",selectors:[]}]},
 formatting:{id:"AdvancedFormatting",sections:[{label:"上下文",selectors:["#ContextSettings"]},{label:"指令模板",selectors:["#InstructSettingsColumn"]},{label:"系统提示词",selectors:["#SystemPromptBlock","#sysprompt_enabled_label"]},{label:"停止与分词",selectors:['[name="tokenizerSettingsBlock"]',"#custom_stopping_strings","#custom_stopping_strings_macro"]},{label:"推理格式",selectors:["#SystemPromptColumn > div:has(#reasoning_select)"]},{label:"其他",selectors:[]}]},
 settings:{id:"user-settings-block",sections:[{label:"外观与阅读",selectors:["#UI-Theme-Block","#CustomCSS-block","#MovingUI-presets-block"]},{label:"消息与输入",selectors:['[name="ChatMessageHandlingToggles"]','[name="MiscellaneousToggles"]']},{label:"角色与群聊",selectors:['[name="CharacterHandlingToggles"]']},{label:"声音与通知",selectors:["#play_message_sound","#play_sound_unfocused"]},{label:"脚本补全",selectors:['[name="AutoCompleteToggle"]','[name="STscriptToggles"]']},{label:"账户",selectors:["#account_controls","#UI-language-block"]},{label:"其他设置",selectors:[]}]},
 note:{id:"floatingPrompt",sections:[{label:"作者注释",selectors:[]}]},
 cfg:{id:"cfgConfig",sections:[{label:"CFG 引导",selectors:[]}]},
 generation:{id:"left-nav-panel",sections:[{label:"高级参数",selectors:[]}]},
 background:{id:"Backgrounds",sections:[{label:"全局与聊天背景",selectors:[]}]},
 extensions:{id:"rm_extensions_block",sections:[{label:"已安装",selectors:[]},{label:"扩展设置",selectors:["#extensions_settings > div:not(#qr_container):not(#regex_container)","#extensions_settings2 > div:not(#qr_container):not(#regex_container)"]},{label:"快捷回复",selectors:["#qr_container"]},{label:"正则",selectors:["#regex_container"]},{label:"Extras",selectors:["#extensions_url","#extensions_status","#extensions_autoconnect","#extensions_api_key","#extensions_connect"]}]},
 world:{id:"WorldInfo",sections:[{label:"绑定与全局设置",selectors:[]}]},
 character:{id:"right-nav-panel",sections:[{label:"群组",selectors:[]}]},
};
function NativeSelect({node,host}:{node:HTMLSelectElement;host:HostAdapter}){
 const [,redraw]=useReducer(v=>v+1,0);
 useEffect(()=>{let frame=0;const sync=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(redraw);};const observer=new MutationObserver(sync);observer.observe(node,{childList:true,subtree:true,attributes:true});node.addEventListener("change",sync);const unsub=host.subscribe(sync);return()=>{observer.disconnect();cancelAnimationFrame(frame);node.removeEventListener("change",sync);unsub();};},[node]);
 const names:Record<string,string>={avatar_style:"头像样式",themes:"界面主题",media_display:"媒体显示",ui_language_select:"界面语言",context_presets:"上下文模板",instruct_presets:"指令模板"};
 const label=node.labels?.[0]?.cloneNode(true) as HTMLElement|undefined;label?.querySelectorAll("select,input,textarea,button,.menu_button").forEach(n=>n.remove());
 return <Select aria-label={node.getAttribute("aria-label")||names[node.id]||label?.textContent?.trim()||node.title||node.id} value={node.value} disabled={node.disabled} onChange={e=>{node.value=e.target.value;node.dispatchEvent(new Event("input",{bubbles:true}));node.dispatchEvent(new Event("change",{bubbles:true}));host.refresh();}}>{[...node.options].map((o,i)=><option key={o.value+":"+i} value={o.value} disabled={o.disabled}>{o.textContent}</option>)}</Select>;
}
/** Mount complete native sections; rearrange whole blocks, never rebuild their inputs. */
export default function NativeSettings({host,page,group,extensionId}:{host:HostAdapter;page:string;group:string;extensionId?:string}){
 const ref=useRef<HTMLDivElement>(null),[error,setError]=useState(""),[bridges,setBridges]=useState<{node:HTMLSelectElement;slot:HTMLElement}[]>([]),sections=useRef<HTMLElement[]>([]),config=nativePages[page];
 const [glyphs,setGlyphs]=useState<{node:HTMLElement;slot:HTMLElement;Icon:LucideIcon}[]>([]);
 const [extensions,setExtensions]=useState<{id:string;label:string}[]>([]),[extension,setExtension]=useState(extensionId||""),nativeRoot=useRef<HTMLElement|null>(null);
 useLayoutEffect(()=>{
  if(!config)return;const container=ref.current!;let restore:(()=>void)|undefined,frame=0;const origins:{node:Node;mark:Comment}[]=[],selects:{node:HTMLSelectElement;slot:HTMLElement}[]=[],added:HTMLElement[]=[],moved=new Set<Element>(),decorations:{node:HTMLElement;slot:HTMLElement;Icon:LucideIcon}[]=[],semantics:{node:HTMLElement;role:string|null;tab:string|null;key:(e:KeyboardEvent)=>void}[]=[];
  try{
   // Initialize the native editor immediately before leasing it, so lazy loading
   // cannot briefly display its original floating window behind our popover.
   if(page==="note"||page==="cfg"){
    const node=document.getElementById(config.id);
    if(node&&getComputedStyle(node).display!=="flex")host.click(page==="note"?"#option_toggle_AN":"#option_toggle_CFG");
   }
   restore=host.leaseNative(config.id,container);const root=container.firstElementChild as HTMLElement;root.classList.add("wb-native-settings-root");nativeRoot.current=root;
   const hiddenStates=new Map<HTMLElement,boolean>(),grids=new Set<HTMLElement>(),labels=new Map<HTMLElement,string|null>();
   const buckets=config.sections.map(section=>{const el=document.createElement("section");el.className="wb-settings-native-group";el.dataset.group=section.label;return el;});
   const take=(node:HTMLElement,bucket:HTMLElement)=>{if(moved.has(node))return;const mark=document.createComment("Workbench setting section origin");node.before(mark);origins.push({node,mark});bucket.append(node);moved.add(node);};
   // Pull smaller sections first, so broad native columns cannot swallow another tab.
   for(let i=config.sections.length-1;i>=0;i--)for(const selector of config.sections[i].selectors)for(const found of [...root.querySelectorAll<HTMLElement>(selector)]){
    let node=found;if(node.id==="reasoning_select")node=found.closest<HTMLElement>("details")!.parentElement!.parentElement!;
    else if(node.id==="custom_stopping_strings")node=found.parentElement!.parentElement!;
    else if(node.id==="extensions_url")node=found.parentElement!;
    else if(node.id==="extensions_status")node=found.parentElement!.parentElement!;
    else if(node.matches("input,textarea,select")){node=found.closest<HTMLElement>(".inline-drawer")||found.closest<HTMLElement>("label")||found.parentElement!;}
    if(node.id==="SystemPromptBlock"&&node.previousElementSibling?.matches("h4"))take(node.previousElementSibling as HTMLElement,buckets[i]);
    if(node!==root&&root.contains(node))take(node,buckets[i]);
   }
   const fallback=buckets[config.sections.findIndex(s=>!s.selectors.length)]||buckets[buckets.length-1];
   for(const node of [...root.childNodes]){if(node.nodeType===Node.COMMENT_NODE)continue;const mark=document.createComment("Workbench remaining settings origin");node.before(mark);origins.push({node,mark});fallback.append(node);}
   root.append(...buckets);sections.current=buckets;
   if(page==="background"){
    const folders=root.querySelector<HTMLElement>("#bg_folder_grid");
    if(folders){const rail=document.createElement("aside");rail.className="wb-native-bg-directory";const title=document.createElement("small");title.textContent="背景库";const all=document.createElement("button");all.type="button";all.textContent="全部背景";all.className="wb-background-all";all.addEventListener("click",()=>root.querySelector<HTMLElement>("#bg_back_to_folders")?.click());rail.append(title,all);folders.before(rail);take(folders,rail);added.push(rail);}
   }
   for(const node of root.querySelectorAll<HTMLElement>(".inline-drawer-toggle")){
    const role=node.getAttribute("role"),tab=node.getAttribute("tabindex"),key=(e:KeyboardEvent)=>{if(e.target===node&&(e.key==="Enter"||e.key===" ")){e.preventDefault();node.click();}};
    node.setAttribute("role","button");node.tabIndex=0;node.addEventListener("keydown",key);semantics.push({node,role,tab,key});
   }
   const scan=()=>{
    for(const node of root.querySelectorAll<HTMLElement>(".menu_button.fa-solid,.menu_button > i.fa-solid,.right_menu_button > .fa-solid,.qr--action.fa-solid,.jg-button.fa-solid,.jg-button > .fa-solid")){
     if(node.classList.contains("wb-component-icon")||node.matches(".qr--set-itemIcon")||node.closest('.wb-settings-native-group[data-group="扩展设置"]'))continue;
     const Icon=Object.entries(nativeGlyphs).find(([name])=>node.classList.contains(name))?.[1];if(!Icon)continue;
     const slot=document.createElement("span");slot.className="wb-component-glyph";slot.setAttribute("aria-hidden","true");node.classList.add("wb-component-icon");node.append(slot);decorations.push({node,slot,Icon});
    }
    const next=decorations.filter(x=>x.node.isConnected);setGlyphs(prev=>prev.length===next.length&&prev.every((x,i)=>x===next[i])?prev:next);

    if(page==="background")for(const node of root.querySelectorAll<HTMLElement>(".mobile-only-menu-toggle,.jg-button")){
     if(node.hasAttribute("data-wb-keyboard"))continue;
     const role=node.getAttribute("role"),tab=node.getAttribute("tabindex"),key=(e:KeyboardEvent)=>{if(e.target===node&&(e.key==="Enter"||e.key===" ")){e.preventDefault();node.click();}};
     node.setAttribute("data-wb-keyboard","");node.setAttribute("role","button");node.tabIndex=0;if(node.matches(".mobile-only-menu-toggle"))node.setAttribute("aria-label","背景操作");node.addEventListener("keydown",key);semantics.push({node,role,tab,key});
    }

    // Keep dynamically rendered extension descendants inside their stable owner.
    if(page==="extensions"){
     const blocks=[...root.querySelectorAll<HTMLElement>('.wb-settings-native-group[data-group="扩展设置"] > div')].filter(n=>n.id!=="qr_container"&&n.id!=="regex_container"&&n.querySelector("input,textarea,select,button,.menu_button"));
     setExtensions(blocks.map(n=>({id:n.id,label:n.querySelector(".inline-drawer-header b,.inline-drawer-header strong,h4,h3")?.textContent?.trim()||n.id})));
     for(const n of blocks)if(!hiddenStates.has(n))hiddenStates.set(n,n.hidden);
    }
    if(page==="settings"||page==="formatting"||page==="generation")for(const parent of root.querySelectorAll<HTMLElement>("div")){
     if(parent.matches(".inline-drawer-content,[hidden],.displayNone")||getComputedStyle(parent).display==="none")continue;
     const children=[...parent.children] as HTMLElement[];
     const short=(n:HTMLElement)=>!n.matches(".inline-drawer,.menu_button,.wb-select,.wb-native-select-slot")&&!n.querySelector(".inline-drawer,.extension_container,.menu_button,textarea")&&n.querySelectorAll("input:not([type=hidden]),select:not(.wb-select-native)").length>0&&n.querySelectorAll("input:not([type=hidden]),select:not(.wb-select-native)").length<=2;
     if(children.filter(short).length>=3){parent.classList.add("wb-component-grid");grids.add(parent);}
    }
    if(page!=="extensions"&&page!=="background")for(const control of root.querySelectorAll<HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement>("input:not([type=hidden]):not([type=file]),textarea,select:not(.wb-select-native)")){
     if(control.hasAttribute("aria-label"))continue;
     const known:Record<string,string>={custom_stopping_strings:"自定义停止字符串",sysprompt_enabled:"启用系统提示词",context_derived:"从模型推导上下文",instruct_enabled:"启用指令模板"};
     const label=control.labels?.[0]?.cloneNode(true) as HTMLElement|undefined;label?.querySelectorAll("input,textarea,select,button,.menu_button").forEach(n=>n.remove());
     const previous=control.previousElementSibling;
     const text=known[control.id]||label?.textContent?.trim()||control.closest(".range-block")?.querySelector(".range-block-title")?.textContent?.trim()||control.title||(previous?.matches("small,label,span")?previous.textContent?.trim():"")||control.getAttribute("placeholder")||control.id;
     if(text){labels.set(control,null);control.setAttribute("aria-label",text.replace(/\s+/g," "));}
    }
    if(page==="extensions"||page==="background")return;

    for(const node of root.querySelectorAll<HTMLSelectElement>("select:not([multiple]):not(.wb-select-native):not(.wb-leased-select):not(.select2-hidden-accessible)")){
     if(node.hidden||node.style.display==="none")continue;const slot=document.createElement("span");slot.className="wb-native-select-slot";node.after(slot);node.classList.add("wb-leased-select");selects.push({node,slot});
    }
    setBridges([...selects].filter(b=>b.node.isConnected));
   };
   scan();const observer=new MutationObserver(records=>{if(!records.some(r=>[...r.addedNodes].some(n=>n instanceof Element&&(page==="extensions"||page==="background"||n.matches("select")||n.querySelector("select:not(.wb-select-native)")))))return;cancelAnimationFrame(frame);frame=requestAnimationFrame(scan);});observer.observe(root,{childList:true,subtree:true});
   const dispose=restore;restore=()=>{observer.disconnect();cancelAnimationFrame(frame);semantics.forEach(({node,role,tab,key})=>{node.removeEventListener("keydown",key);node.removeAttribute("data-wb-keyboard");if(node.matches(".mobile-only-menu-toggle"))node.removeAttribute("aria-label");role===null?node.removeAttribute("role"):node.setAttribute("role",role);tab===null?node.removeAttribute("tabindex"):node.setAttribute("tabindex",tab);});for(const {node,slot} of decorations){node.classList.remove("wb-component-icon");slot.remove();}for(const b of selects){b.node.classList.remove("wb-leased-select");b.slot.remove();}for(const {node,mark} of origins.reverse())mark.replaceWith(node);buckets.forEach(b=>b.remove());added.forEach(n=>n.remove());grids.forEach(n=>n.classList.remove("wb-component-grid"));labels.forEach((value,n)=>value===null?n.removeAttribute("aria-label"):n.setAttribute("aria-label",value));hiddenStates.forEach((hidden,n)=>n.hidden=hidden);root.classList.remove("wb-native-settings-root");nativeRoot.current=null;dispose();if(page==="note"||page==="cfg")root.style.display="none";};
  }catch(e){setError(String(e));}
  return()=>{restore?.();sections.current=[];setGlyphs([]);};
 },[host,page]);
 useEffect(()=>{if(extensionId)setExtension(extensionId);},[extensionId]);
 const currentExtension=extensions.some(x=>x.id===extension)?extension:extensions[0]?.id;
 useLayoutEffect(()=>{if(page!=="extensions")return;nativeRoot.current?.querySelectorAll<HTMLElement>('.wb-settings-native-group[data-group="扩展设置"] > div').forEach(n=>n.hidden=n.id!==currentExtension);},[page,extensions,currentExtension]);
 useLayoutEffect(()=>{sections.current.forEach(section=>{section.hidden=section.dataset.group!==group;});},[group,page,bridges]);
 return <><Notice error={error}/>{page==="extensions"&&group==="扩展设置"&&<div className="wb-component-extension-picker"><Field label="选择扩展"><Select aria-label="选择扩展" value={currentExtension||""} onChange={e=>setExtension(e.target.value)}>{extensions.map(x=><option key={x.id} value={x.id}>{x.label}</option>)}</Select></Field></div>}<div className={`wb-native-settings-slot page-${page}`} ref={ref}/>{bridges.map(({node,slot})=>createPortal(<NativeSelect node={node} host={host}/>,slot,node.id))}{glyphs.map(({slot,Icon},i)=>createPortal(<Icon size={16} strokeWidth={1.7} aria-hidden="true"/>,slot,"glyph-"+i))}</>;
}
