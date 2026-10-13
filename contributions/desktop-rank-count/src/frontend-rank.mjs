export function createDesktopRank(api){
const ge=api;
async function desktopRank(board,refresh=false,page=1){
  const status=await ge.validationStatus(),url=new URL(status.baseUrl);
  if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||!url.port||url.username||url.password||url.pathname!=='/'||url.search||url.hash)
    throw Error('本地排行榜服务暂不可用');
  url.pathname='/desktop/rank';
  url.search=new URLSearchParams({board,page:String(page),refresh:String(refresh)}).toString();
  const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),25000);
  try{
    const response=await fetch(url,{headers:{'x-desktop-rank-client':'1'},credentials:'omit',redirect:'error',cache:'no-store',signal:abort.signal});
    const value=await response.json();
    if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:'排行榜暂时不可用，请重试');
    if(!Array.isArray(value))throw Error('排行榜响应格式异常');
    return value;
  }catch(error){if(error.name==='AbortError')throw Error('排行榜请求超时，请重试');throw error;}
  finally{clearTimeout(timer);}
}

return desktopRank;
}
