/* Keep a checked KI selection local to this tab and its saved project. */
(()=>{
  let scope=new URLSearchParams(location.search).get("library_scope")||"";
  const original=window.fetch.bind(window);
  window.GeoForgeKIScope={get:()=>scope,set:value=>{scope=String(value||"")},
    url:value=>{const u=new URL(value,location.href);if(scope)u.searchParams.set("library_scope",scope);else u.searchParams.delete("library_scope");return u.pathname+u.search+u.hash}};
  if(typeof document!=="undefined")document.addEventListener("click",event=>{
    const link=event.target.closest?.("a[href]");if(!link)return;
    const u=new URL(link.href,location.href);
    if(u.origin===location.origin&&["/","/library","/setup"].includes(u.pathname)&&!u.searchParams.has("session"))
      link.href=window.GeoForgeKIScope.url(link.href);
  },true);
  window.fetch=(input,init)=>{
    const u=new URL(typeof input==="string"?input:input.url,location.href);
    // A saved project's server binding is authoritative. Never impose the
    // currently displayed project's scope on another sidebar entry.
    if(scope&&u.origin===location.origin&&u.pathname.startsWith("/api/")&&
       !/^\/api\/(?:observatory\/)?session\//.test(u.pathname)){
      const headers=new Headers(init?.headers||(typeof input!=="string"?input.headers:undefined));
      headers.set("X-GeoForge-KI-Scope",scope);
      init={...init,headers};
    }
    return original(input,init);
  };
})();
