function desktopCreatePosterLoader(request) {
  const pending = new Map(), queue = [];
  let scheduled = false, active = 0;
  function schedule() {
    if (!scheduled) {scheduled=true;queueMicrotask(()=>{scheduled=false;pump();});}
  }
  function pump() {
    while (active < 2 && queue.length) {
      const batch=queue.splice(0,20);active++;
      Promise.resolve().then(()=>request(batch.map(row=>row.sid))).then(value=>{
        for (const row of batch) {
          const data=value.covers?.[row.sid];
          if (typeof data==='string' && /^data:image\/(jpeg|png|webp);base64,/.test(data)) row.resolve(data);
          else row.reject(Error('封面暂不可用'));
        }
      },error=>{for(const row of batch)row.reject(error);}).finally(()=>{
        for (const row of batch) pending.delete(row.sid);
        active--;schedule();
      });
    }
  }
  return sid=>{
    if (typeof sid!=='string' || !/^\d{8,24}$/.test(sid)) return Promise.reject(Error('无效的封面剧集 ID'));
    if (pending.has(sid)) return pending.get(sid);
    let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});
    pending.set(sid,promise);queue.push({sid,resolve,reject});schedule();return promise;
  };
}
