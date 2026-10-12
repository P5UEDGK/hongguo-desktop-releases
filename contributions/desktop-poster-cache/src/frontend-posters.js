function desktopCreatePosterLoader(request) {
  const pending = new Map(), queues = {local:[], remote:[]}, active = {local:0, remote:0};
  let scheduled = false;
  function finish(row, data, error) {
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
      Promise.resolve().then(()=>request(batch.map(row=>row.sid),{localOnly:kind==='local'})).then(value=>{
        for (const row of batch) {
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
