// The host provides its existing managed-endpoint parser; no credentials persist.
function desktopCreateContinuationRequest(endpointOf,request=fetch) {
  return (session,parent,enabled,revision)=>{
    const endpoint=endpointOf(session.streamUrl);
    const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),8000);
    return request(endpoint.origin+'/desktop/hls/'+parent+'/continuation',{
      method:'POST',headers:{'x-api-key':endpoint.key,'content-type':'application/json'},
      body:JSON.stringify({enabled,revision}),credentials:'omit',redirect:'error',cache:'no-store',keepalive:!enabled,signal:abort.signal
    }).then(response=>{if(!response.ok)throw Error('Continuation unavailable');return response.json();}).finally(()=>clearTimeout(timer));
  };
}

// Owns only the next season's first episode. The host owns playback identity.
function desktopCreateSeasonPlayback({find,resolve,prepare,shouldPrewarm,prefetch=()=>{}}) {
  let current=null,epoch=0,searchEpoch=0,result=null,lookup=null,first=null,sourceWork=null,standby=null,attempted=false;
  const empty=()=>({items:[],automatic:false,incomplete:true});
  const cacheNotices=new WeakMap();
  function syncCache(config) {
    if(!config?.media)return;
    const previous=cacheNotices.get(config);
    const parent=config.enabled?config.media.desktopSessionId?.():previous?.parent;
    if(!parent)return;
    const enabled=!!config.enabled&&!config.media.seeking&&config.healthy();
    const key=parent+':'+enabled+':'+(result?.automatic?result.items[0]?.seriesId||'':'');
    const repeated=previous?.key===key;
    if(repeated&&(!previous.retryAt||Date.now()<previous.retryAt||previous.attempts>=2))return;
    const notice={parent,key,attempts:repeated?previous.attempts+1:1};
    cacheNotices.set(config,notice);
    const revision=desktopCreateSeasonPlayback.cacheRevision=(desktopCreateSeasonPlayback.cacheRevision||0)+1;
    const retry=delay=>{if(current===config&&config.enabled&&cacheNotices.get(config)===notice)notice.retryAt=Date.now()+delay;};
    Promise.resolve().then(()=>prefetch(config.session,parent,enabled,revision))
      .then(value=>{if(value?.accepted===false)retry(250);},()=>retry(5000));
  }
  function release() {standby?.preparation?.dispose();standby=null;first=null;sourceWork=null;attempted=false;}
  function cancel() {epoch++;searchEpoch++;if(current){current.enabled=false;syncCache(current);}lookup=null;release();}
  async function search(seed,live=()=>true,force=false) {
    if(!current?.enabled||current.series?.seriesId!==seed.seriesId||!live())return empty();
    if(!force&&result?.automatic)return result;
    if(lookup)return lookup;
    const version=searchEpoch,source=current.session.source;
    const valid=()=>version===searchEpoch&&!!current?.enabled&&current.series?.seriesId===seed.seriesId&&current.session.source===source&&live();
    const task=Promise.resolve().then(()=>find(seed,valid)).then(value=>{
      if(!valid())return empty();
      result=value;return value;
    },()=>{if(valid())result=empty();return empty();}).finally(()=>{if(lookup===task)lookup=null;});
    lookup=task;return task;
  }
  async function tick() {
    const config=current,version=epoch;
    syncCache(config);
    if(!config?.enabled||!config.media||config.media.paused||config.media.seeking||config.media.ended||!config.healthy())return;
    const {session,media,series}=config;
    if(!series||session.episode<Math.max(1,session.total-1))return;
    const valid=()=>epoch===version&&current===config&&config.enabled;
    const next=await search(series);
    if(valid())syncCache(config);
    if(!valid()||!next.automatic||next.items.length!==1||session.episode!==session.total)return;
    if(!first&&!sourceWork) {
      const candidate=next.items[0];
      const work=Promise.resolve().then(()=>resolve(candidate.seriesId,1)).then(value=>{
        if(!valid())return;
        if(value.seriesId!==candidate.seriesId||value.episode!==1||value.source!==session.source||
          !Number.isSafeInteger(value.total)||value.total<1||typeof value.streamUrl!=='string'||!value.streamUrl||
          (session.streamFormat==='hls'&&value.streamFormat!=='hls'))throw Error('下一季片源身份不一致');
        first=value;
      }).catch(()=>{if(valid())attempted=true;}).finally(()=>{if(sourceWork===work)sourceWork=null;});
      sourceWork=work;
    }
    if(sourceWork)await sourceWork;
    if(!valid()||!first||attempted||media.paused||media.seeking||!config.healthy()||!shouldPrewarm(media))return;
    attempted=true;
    try {standby={session:first,preparation:prepare(first.streamUrl,media)};} catch {standby=null;}
  }
  function attach(config) {
    const same=current?.session.seriesId===config.session.seriesId&&current?.session.source===config.session.source;
    epoch++;release();
    if(!same||!config.enabled){searchEpoch++;lookup=null;}
    if(!same)result=null;
    current=config;
    const update=()=>{void tick();};
    const events=['timeupdate','playing','waiting','seeking','seeked'];
    for(const event of events)config.media?.addEventListener(event,update);
    // Metadata can be resolved while the penultimate episode is loading.
    if(config.enabled&&config.series&&config.session.episode>=Math.max(1,config.session.total-1))
      void search(config.series);
    update();
    return ()=>{
      for(const event of events)config.media?.removeEventListener(event,update);
      if(current===config){epoch++;config.enabled=false;syncCache(config);release();}
    };
  }
  function take(candidate) {
    if(!current?.enabled||!result?.automatic||result.items[0]?.seriesId!==candidate.seriesId||!first)return null;
    const value=standby?.preparation&&!standby.preparation.failed?standby:{session:first,preparation:null};
    if(value.preparation?.claimRecord) {
      // Disposing an adopted HLS player restores the old placeholder element's
      // descriptors. Read controls before that happens, not from the retired
      // element later when the new player asynchronously claims its standby.
      const settings={rate:current.media.playbackRate||1,volume:current.media.volume,muted:current.media.muted};
      const original=value.preparation,prepared=Object.create(original);
      prepared.claimRecord=async(...args)=>{
        const record=await original.claimRecord(...args);
        if(!record)return null;
        return {...record,settings,adopt:record.adopt?((media,handlers)=>{
          const controller=record.adopt(media,handlers);
          media.playbackRate=settings.rate;media.volume=settings.volume;media.muted=settings.muted;
          return controller;
        }):undefined};
      };
      value.preparation=prepared;
    }
    if(standby?.preparation?.failed)standby.preparation.dispose();
    standby=null;first=null;sourceWork=null;attempted=true;
    return value;
  }
  return {attach,find:search,take,cancel,get result(){return result;}};
}

export { desktopCreateSeasonPlayback as createSeasonPlayback, desktopCreateContinuationRequest as createContinuationRequest };
