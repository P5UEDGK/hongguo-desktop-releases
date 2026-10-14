export function createDesktopNovelfmSearch(api) {
const ge = api;
async function desktopNovelfmSearch(query,page,mode){
  const status=await ge.validationStatus(), url=new URL(status.baseUrl);
  if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||!url.port||url.username||url.password||url.pathname!=='/'||url.search||url.hash)
    throw Error('本地搜索服务暂不可用');
  const send=async(body,token)=>{
    const abort=new AbortController(), timer=setTimeout(()=>abort.abort(),30000);
    try{
      const response=await fetch(url.origin+'/desktop/search',{
        method:body===undefined?'GET':'POST',body:body===undefined?undefined:JSON.stringify(body),
        headers:{'content-type':'application/json','x-desktop-search-client':'1','x-desktop-search-token':token||''},
        credentials:'omit',redirect:'error',cache:'no-store',signal:abort.signal});
      const value=await response.json();
      if(!response.ok){const error=Error(typeof value.detail==='string'?value.detail:'搜索服务暂时不可用，请重试');error.status=response.status;throw error;}
      return value;
    }catch(error){if(error.name==='AbortError')throw Error('搜索请求超时，请重试');throw error;}
    finally{clearTimeout(timer);}
  };
  for(let attempt=0;attempt<2;attempt++){
    let access=desktopNovelfmSearch.access;
    if(!access||access.origin!==url.origin){
      const value=await send();
      if(typeof value.requestToken!=='string'||!value.requestToken)throw Error('搜索会话未就绪，请重试');
      desktopNovelfmSearch.access=access={origin:url.origin,token:value.requestToken};
    }
    try{return await send({query,page,mode},access.token);}
    catch(error){if(error.status!==401||attempt)throw error;desktopNovelfmSearch.access=null;}
  }
}

return desktopNovelfmSearch;
}
