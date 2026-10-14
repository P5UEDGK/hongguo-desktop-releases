let desktopCacheAccess = null;
async function desktopCacheRequest(path = "", value) {
  const status = await ge.validationStatus();
  const url = new URL(status.baseUrl);
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || !url.port || url.username || url.password || url.pathname !== "/" || url.search || url.hash) throw new Error("缓存设置暂不可用");
  if (value !== undefined && desktopCacheAccess?.origin !== url.origin) await desktopCacheRequest();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), path === "/choose" ? 190000 : 10000);
  try {
    const response = await fetch(`${url.origin}/desktop/cache-settings${path}`, {
      method:value === undefined ? "GET" : "POST",
      headers:{"x-desktop-cache-client":"1", "x-desktop-cache-token":desktopCacheAccess?.token || "", "content-type":"application/json"},
      credentials:"omit", redirect:"error", cache:"no-store", signal:controller.signal,
      body:value === undefined ? undefined : JSON.stringify(value)
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || "缓存设置暂不可用");
    }
    const result = await response.json();
    if (result.requestToken) desktopCacheAccess = {origin:url.origin, token:result.requestToken};
    return result;
  } finally { clearTimeout(timer); }
}

function DesktopCacheSettings() {
  const [directory, setDirectory] = O.useState("");
  const [draftDirectory, setDraftDirectory] = O.useState("");
  const [defaultDirectory, setDefaultDirectory] = O.useState("");
  const [count, setCount] = O.useState("3");
  const [all, setAll] = O.useState(false);
  const [limit, setLimit] = O.useState("10");
  const [loaded, setLoaded] = O.useState(false);
  const [busy, setBusy] = O.useState(false);
  const [message, setMessage] = O.useState("");
  const saved = O.useRef("");
  const revision = O.useRef(0);
  const chain = O.useRef(Promise.resolve());
  const alive = O.useRef(true);
  const latest = O.useRef(null);
  O.useEffect(() => {
    let live = true;
    alive.current = true;
    desktopCacheRequest().then(value => {
      if (!live) return;
      setDirectory(value.directory); setDraftDirectory(value.directory);
      setDefaultDirectory(value.defaultDirectory);
      setAll(value.ahead === "all"); setCount(value.ahead === "all" ? "3" : String(value.ahead));
      setLimit(String(value.limitGB || 10));
      saved.current = JSON.stringify({directory:value.directory, ahead:value.ahead, limitGB:value.limitGB || 10});
      setLoaded(true);
    }).catch(error => { if (live) setMessage(error.message); });
    return () => { live = false; alive.current = false; };
  }, []);
  O.useEffect(() => {
    if (!loaded) return;
    const version = ++revision.current;
    if (!directory.trim() || (!all && (!/^[1-9]\d*$/.test(count) || Number(count) > 100000)) || !/^[1-9]\d*$/.test(limit) || Number(limit) > 100000) {
      latest.current = null;
      setMessage("集数和缓存上限须为正整数"); return;
    }
    const value = {directory:directory.trim(), ahead:all ? "all" : Number(count), limitGB:Number(limit)};
    latest.current = {value, version};
    setMessage("");
    if (JSON.stringify(value) === saved.current) return;
    const timer = setTimeout(() => {
      chain.current = chain.current.catch(() => {}).then(async () => {
        if (version !== revision.current || JSON.stringify(value) === saved.current) return;
        try {
          const result = await desktopCacheRequest("", value);
          saved.current = JSON.stringify({directory:result.directory, ahead:result.ahead, limitGB:result.limitGB});
          if (alive.current && version === revision.current) {
            setDirectory(result.directory); setDraftDirectory(result.directory); setMessage("");
          }
        } catch (error) { if (alive.current && version === revision.current) setMessage(error.message); }
      });
    }, 350);
    // The bounded write may finish after navigating away; revision rejects stale edits.
  }, [directory, count, all, limit, loaded]);
  async function choose() {
    setBusy(true); setMessage("");
    try {
      const result = await desktopCacheRequest("/choose", {});
      if (result.directory) { setDraftDirectory(result.directory); setDirectory(result.directory); }
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  async function clear() {
    setBusy(true); setMessage("");
    try {
      await chain.current;
      const pending = latest.current;
      if (!pending) throw new Error("请先填写有效设置");
      if (JSON.stringify(pending.value) !== saved.current) {
        const result = await desktopCacheRequest("", pending.value);
        saved.current = JSON.stringify({directory:result.directory, ahead:result.ahead, limitGB:result.limitGB});
      }
      const result = await desktopCacheRequest("/clear", {});
      const clearedGB = result.clearedBytes / 1024**3;
      setMessage(result.clearedBytes ? `已清理 ${clearedGB < 0.01 ? "<0.01" : clearedGB.toFixed(2)} GB` : "缓存已全部清理");
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  const row = {display:"flex", alignItems:"center", flexWrap:"wrap", gap:"10px", padding:"8px 0", borderBottom:"1px solid #eceef1"};
  const field = {padding:"4px 8px", height:"32px", boxSizing:"border-box", border:"1px solid #dfe1e5", borderRadius:"7px", minWidth:0, font:"inherit", background:"transparent", color:"inherit"};
  const label = {flex:"1 1 170px"};
  const button = {font:"inherit", padding:"6px 12px", border:"1px solid #dfe1e5", borderRadius:"7px", background:"transparent", color:"inherit", cursor:"pointer"};
  return b.jsxs("div", {"aria-label":"缓存设置", children:[
    b.jsx("style", {children:".settings-page h1{margin-bottom:16px}.settings-page h2{margin-top:18px}.settings-page .settings-row{min-height:48px;gap:16px}"}),
    b.jsxs("h2", {style:{marginBottom:"8px", display:"flex", alignItems:"center", gap:"12px", whiteSpace:"nowrap"}, children:[
      b.jsx("span", {children:"缓存"}),
      b.jsx("small", {title:"可先手动清理缓存再切换目录", style:{fontSize:"12px", fontWeight:"normal", color:"#8a8f98", minWidth:0, overflow:"hidden", textOverflow:"ellipsis"}, children:"可先手动清理缓存再切换目录"})
    ]}),
    b.jsxs("div", {style:row, children:[
      b.jsx("label", {htmlFor:"video-cache-directory", style:label, children:"视频缓存目录"}),
      b.jsx("input", {id:"video-cache-directory", value:draftDirectory, onChange:event=>setDraftDirectory(event.target.value), onBlur:()=>setDirectory(draftDirectory), disabled:busy||!loaded, style:{...field, flex:"3 1 280px"}}),
      b.jsx("button", {type:"button", style:button, onClick:choose, disabled:busy||!loaded, children:"选择目录"}),
      b.jsx("button", {type:"button", style:button, onClick:()=>{setDraftDirectory(defaultDirectory);setDirectory(defaultDirectory);}, disabled:busy||!loaded, children:"恢复默认"})
    ]}),
    b.jsxs("div", {style:row, children:[
      b.jsx("label", {htmlFor:"video-cache-count", style:label, children:"缓存集数"}),
      b.jsxs("label", {style:{display:"flex", alignItems:"center", gap:"7px", whiteSpace:"nowrap"}, children:[
        b.jsx("input", {id:"video-cache-all", type:"checkbox", checked:all, onChange:event=>setAll(event.target.checked), disabled:busy||!loaded, style:{accentColor:"#ff6b98"}}), "剩余集数"
      ]}),
      b.jsxs("div", {style:{display:"flex", alignItems:"center", gap:"5px", marginLeft:"17px"}, children:[
        b.jsx("label", {htmlFor:"video-cache-count", style:{whiteSpace:"nowrap"}, children:"指定集数："}),
        b.jsx("input", {id:"video-cache-count", "aria-label":"指定集数", type:"number", min:1, max:100000, step:1, value:count, onChange:event=>setCount(event.target.value), disabled:busy||!loaded||all, style:{...field, width:"90px", opacity:all?0.45:1}})
      ]}),
      b.jsx("small", {style:{color:"#8a8f98"}, children:"推荐 3 集"})
    ]}),
    b.jsxs("div", {style:row, children:[
      b.jsxs("div", {style:{...label, display:"flex", alignItems:"center", gap:"12px", minWidth:0}, children:[
        b.jsx("label", {htmlFor:"video-cache-limit", style:{whiteSpace:"nowrap"}, children:"缓存上限"}),
        b.jsx("span", {role:"status", title:message, style:{fontSize:"13px", height:"18px", lineHeight:"18px", flex:"1 1 0", minWidth:0, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis"}, children:message || "\u00a0"})
      ]}),
      b.jsx("input", {id:"video-cache-limit", "aria-label":"缓存上限", type:"number", min:1, max:100000, step:1, value:limit, onChange:event=>setLimit(event.target.value), disabled:busy||!loaded, style:{...field, width:"90px"}}),
      b.jsx("span", {children:"GB"}),
      b.jsx("small", {style:{color:"#8a8f98"}, children:"满额停止缓存"}),
      b.jsx("button", {type:"button", style:button, onClick:clear, disabled:busy||!loaded, children:"手动清理缓存"})
    ]})
  ]});
}
