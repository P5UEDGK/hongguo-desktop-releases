function desktopCreatePosterLoader(request) {
  const pending = new Map(), queues = {local:[], remote:[]}, active = {local:0, remote:0};
  let scheduled = false;
  function finish(row, data, error) {
    if (row.done) return;
    row.done=true;
    pending.delete(row.sid);
    error ? row.reject(error) : row.resolve(data);
  }
  function schedule() {
    if (!scheduled) {scheduled=true;queueMicrotask(()=>{scheduled=false;pump();});}
  }
  function pump(kind) {
    if (!kind) {pump('local');pump('remote');return;}
    while (active[kind] < 2 && queues[kind].length) {
      const batch=queues[kind].splice(0,20);active[kind]++;
      const progress=value=>{
        for (const row of batch) {
          const data=value.covers?.[row.sid];
          if (typeof data==='string' && /^data:image\/(jpeg|png|webp);base64,/.test(data)) finish(row,data);
        }
      };
      Promise.resolve().then(()=>request(batch.map(row=>row.sid),{localOnly:kind==='local'},kind==='remote'?progress:undefined)).then(value=>{
        for (const row of batch) {
          if (row.done) continue;
          const data=value.covers?.[row.sid];
          if (typeof data==='string' && /^data:image\/(jpeg|png|webp);base64,/.test(data)) finish(row,data);
          else if (kind==='local') queues.remote.push(row);
          else finish(row,null,Error('封面暂不可用'));
        }
      },error=>{for(const row of batch)finish(row,null,error);}).finally(()=>{
        active[kind]--;schedule();
      });
    }
  }
  return sid=>{
    if (typeof sid!=='string' || !/^\d{8,24}$/.test(sid)) return Promise.reject(Error('无效的封面剧集 ID'));
    if (pending.has(sid)) return pending.get(sid);
    let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});
    pending.set(sid,promise);queues.local.push({sid,resolve,reject});schedule();return promise;
  };
}

async function desktopReadPosterStream(response,onProgress) {
  const reader=response.body?.getReader();
  if (!reader) throw Error('封面响应不可读取');
  const decoder=new TextDecoder();let buffer='';
  function line(value) {
    if (!value.trim()) return;
    const part=JSON.parse(value);
    if (!part || typeof part!=='object' || !part.covers || typeof part.covers!=='object' || Array.isArray(part.covers))
      throw Error('封面响应格式无效');
    onProgress(part);
  }
  try {
    while (true) {
      const {done,value}=await reader.read();
      buffer+=decoder.decode(value,{stream:!done});
      let end;
      while ((end=buffer.indexOf('\n'))>=0) {
        if (end>4*1024*1024) throw Error('封面响应过大');
        line(buffer.slice(0,end));buffer=buffer.slice(end+1);
      }
      if (buffer.length>4*1024*1024) throw Error('封面响应过大');
      if (done) {if(buffer)line(buffer);return {covers:{}};}
    }
  } catch(error) {
    try {await reader.cancel();} catch {}
    throw error;
  } finally {reader.releaseLock();}
}
