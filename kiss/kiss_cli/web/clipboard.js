/* GeoForge desktop clipboard bridge.
   Provides keyboard shortcuts and the context menu pywebview hides on macOS. */
(()=>{
  const editable=el=>el&&el.closest&&el.closest('textarea,input:not([type="button"]):not([type="file"]),[contenteditable="true"]');
  const selectionText=(el)=>{
    if(el&&typeof el.selectionStart==="number") return el.value.slice(el.selectionStart,el.selectionEnd);
    return String(window.getSelection()||"");
  };
  async function write(text){
    text=String(text??""); if(!text)return false;
    try{if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(text);return true;}}
    catch{}
    if(location.protocol==='file:')return false;
    try{const r=await fetch('/api/clipboard',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});return r.ok;}
    catch{return false;}
  }
  async function read(){
    try{if(navigator.clipboard&&window.isSecureContext)return await navigator.clipboard.readText();}
    catch{}
    if(location.protocol==='file:')return "";
    try{const r=await fetch('/api/clipboard',{cache:'no-store'}),d=await r.json();return r.ok?String(d.text||""):"";}
    catch{return "";}
  }
  function replace(el,text){
    if(!el)return;
    el.focus();
    if(typeof el.selectionStart==="number"){
      el.setRangeText(text,el.selectionStart,el.selectionEnd,'end');
    }else{
      document.execCommand('insertText',false,text);
    }
    el.dispatchEvent(new Event('input',{bubbles:true}));
  }
  async function act(name,target){
    const direct=editable(target),focused=editable(document.activeElement),el=direct||focused;
    if(name==='copy'){
      const text=direct?selectionText(direct):(String(window.getSelection()||"")||selectionText(focused));
      return write(text);
    }
    if(name==='cut'){
      const text=selectionText(el); if(!el||!text)return false;
      if(await write(text)){replace(el,"");return true;} return false;
    }
    if(name==='paste'){
      if(!el)return false; replace(el,await read()); return true;
    }
    if(name==='select'){
      if(el&&typeof el.select==='function')el.select();
      else if(el){const r=document.createRange();r.selectNodeContents(el);const s=getSelection();s.removeAllRanges();s.addRange(r);}
      else document.execCommand('selectAll');
      return true;
    }
    return false;
  }

  const style=document.createElement('style');
  style.textContent=`#gf-clipboard-menu{position:fixed;z-index:1000;display:none;min-width:142px;padding:5px;background:var(--raised,#fff);color:var(--fg,#111);border:1px solid var(--line,rgba(0,0,0,.14));border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,.18)}#gf-clipboard-menu button{display:block;width:100%;padding:6px 10px;border:0;border-radius:6px;background:transparent;color:inherit;text-align:left;font:13px/19px -apple-system,system-ui,sans-serif}#gf-clipboard-menu button:hover{background:var(--hover,rgba(0,0,0,.06))}#gf-clipboard-menu hr{border:0;border-top:1px solid var(--line,rgba(0,0,0,.1));margin:4px 0}`;
  document.head.appendChild(style);
  const menu=document.createElement('div'); menu.id='gf-clipboard-menu';
  menu.innerHTML='<button data-a="cut">Cut</button><button data-a="copy">Copy</button><button data-a="paste">Paste</button><hr><button data-a="select">Select All</button>';
  document.body.appendChild(menu);
  let menuTarget=null;
  const hide=()=>menu.style.display='none';
  document.addEventListener('contextmenu',e=>{
    const el=editable(e.target),selected=String(getSelection()||"");
    if(!el&&!selected)return;
    e.preventDefault();menuTarget=e.target;
    menu.querySelector('[data-a="cut"]').style.display=el?'block':'none';
    menu.querySelector('[data-a="paste"]').style.display=el?'block':'none';
    menu.querySelector('[data-a="copy"]').style.display=(selected||selectionText(el))?'block':'none';
    menu.style.display='block';
    const w=menu.offsetWidth,h=menu.offsetHeight;
    menu.style.left=Math.min(e.clientX,innerWidth-w-8)+'px';menu.style.top=Math.min(e.clientY,innerHeight-h-8)+'px';
  });
  menu.addEventListener('click',e=>{const b=e.target.closest('button[data-a]');if(!b)return;act(b.dataset.a,menuTarget);hide();});
  document.addEventListener('pointerdown',e=>{if(!menu.contains(e.target))hide();});
  addEventListener('blur',hide);addEventListener('scroll',hide,true);

  document.addEventListener('keydown',e=>{
    if(!(e.metaKey||e.ctrlKey)||e.altKey)return;
    const key=e.key.toLowerCase(),el=editable(e.target);
    const canBridge=location.protocol!=='file:'||(navigator.clipboard&&window.isSecureContext);
    if(!canBridge)return;
    if(key==='v'&&el){e.preventDefault();act('paste',el);}
    else if(key==='x'&&el){e.preventDefault();act('cut',el);}
    else if(key==='c'&&(selectionText(el)||String(getSelection()||""))){e.preventDefault();act('copy',el||e.target);}
    else if(key==='a'&&el){e.preventDefault();act('select',el);}
  },true);
  window.GeoForgeClipboard={read,write,act};
})();
