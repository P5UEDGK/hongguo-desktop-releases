// One speculative next episode; React still owns episode identity/auto-continue.
const desktopStandbys = new WeakMap();

function desktopNativeSurfaceRect(media) {
  const rect = media.getBoundingClientRect(), scale = window.devicePixelRatio || 1;
  const stage = media.closest('.player-stage') || media.parentElement;
  const chrome = stage?.querySelector?.('.player-chrome')?.getBoundingClientRect();
  const reserved = chrome?.height > 0 ? rect.top + rect.height - chrome.top : 84;
  const bar = Math.min(Math.max(0, reserved), Math.max(0, rect.height - 1));
  return [Math.max(0, Math.round(rect.left * scale)), Math.max(0, Math.round(rect.top * scale)),
    Math.max(1, Math.round(rect.width * scale)), Math.max(1, Math.round((rect.height - bar) * scale))];
}

function desktopShouldPrewarm(media) {
  const duration = media.desktopTimelineDuration || media.duration;
  const position = media.currentTime + (media.desktopTimeOrigin || 0);
  return Number.isFinite(duration) && duration > 0 && !media.ended &&
    media.readyState >= 2 && !media.desktopBuffering &&
    (duration - position) / Math.max(.25, media.playbackRate || 1) <= 12;
}

// React calls this only when an ended episode has a next episode to resolve.
// Picture retention must not depend on successful speculative preparation.
function desktopHoldForNext(media) {
  if (!media) return null;
  const existing = desktopStandbys.get(media);
  if (existing && !existing.failed) return existing;
  let claimed = false, finished = false, timer;
  const releases = [];
  const holder = {
    retain(release) {
      if (finished) {release();return;}
      releases.push(release);
      timer ||= setTimeout(holder.finishRetained, 90000);
    },
    finishRetained() {
      if (finished) return;
      finished = true;clearTimeout(timer);
      for (const release of releases.splice(0)) release();
      if (desktopStandbys.get(media) === holder) desktopStandbys.delete(media);
    },
    dispose() {if (!claimed) holder.finishRetained();},
    cancelClaim(retainPicture = false) {if (!retainPicture) holder.finishRetained();},
    async claimRecord() {claimed = true;return null;},
    async claim() {claimed = true;return null;}
  };
  desktopStandbys.set(media, holder);
  return holder;
}

function desktopRetainPicture(media) {
  const preparation = desktopStandbys.get(media);
  if (!preparation || preparation.failed) return null;
  const display = media.desktopDisplayMedia || media;
  let cover = null;
  // Native video is a separate HWND: its session is retained below. HLS can
  // retain the last decoded frame after React removes the old video element.
  if (display.videoWidth > 0 && !media.desktopNativePicture) {
    try {
      cover = document.createElement('canvas');
      cover.width = display.videoWidth; cover.height = display.videoHeight;
      cover.className = 'validation-video';
      cover.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;object-fit:contain;pointer-events:none;z-index:1';
      cover.getContext('2d').drawImage(display, 0, 0, cover.width, cover.height);
      (media.closest('.player-stage') || media.parentElement).append(cover);
    } catch {cover?.remove(); cover = null;}
  }
  const cleanup = () => cover?.remove();
  preparation.retain(cleanup);
  return release => preparation.retain(release);
}

function desktopPrepareNext(url, currentMedia) {
  if (!currentMedia || !currentMedia.desktopSessionId?.())
    return {dispose() {}, claim: async () => null};
  const endpoint = w0(url), parent = currentMedia.desktopSessionId();
  const previous = desktopStandbys.get(currentMedia);
  previous?.dispose();
  let disposed = false, claimed = false, id = null, controller = null, video = null;
  let mode = null, consumer = null, retained = [], retireTimer = null, expiryTimer = null;
  let known = {}, failed = false, resumePosition = null, resumeFailed = false, resumeInvalid = false;
  const headers = {'x-api-key': endpoint.key};
  const options = {credentials: 'omit', redirect: 'error', cache: 'no-store'};
  const abort = new AbortController();
  const deadline = Date.now() + 90000;
  async function fetchJson(url, init = {}, budget = 15000) {
    const remaining = Math.min(15000, budget, deadline - Date.now());
    if (disposed || remaining <= 0) throw Error('Standby request expired');
    const local = new AbortController();
    let timer, cancel;
    try {
      return await Promise.race([
        (async () => {
          const response = await fetch(url, {...options, ...init, signal:local.signal,
            headers:{...headers,...init.headers}});
          if (!response.ok) throw Error('Standby unavailable');
          return response.status === 204 ? null : response.json();
        })(),
        new Promise((_, reject) => {
          cancel = () => {local.abort();reject(Error('Standby request cancelled'));};
          abort.signal.addEventListener('abort',cancel,{once:true});
          timer = setTimeout(cancel,remaining);
          if (abort.signal.aborted) cancel();
        })
      ]);
    } finally {clearTimeout(timer);abort.signal.removeEventListener('abort',cancel);}
  }
  function request(path, init = {}, budget = 15000) {
    return fetchJson(endpoint.origin + '/desktop/hls' + path, init, budget);
  }
  async function release() {
    if (!id) return;
    const old = id; id = null;
    try {await fetch(endpoint.origin + '/desktop/hls/' + old,
      {...options, method:'DELETE', headers, keepalive:true});} catch {}
  }
  function finishRetained() {
    clearTimeout(retireTimer); retireTimer = null;
    for (const cleanup of retained.splice(0)) cleanup();
    if (desktopStandbys.get(currentMedia) === preparation) desktopStandbys.delete(currentMedia);
  }
  function cleanup(retainPicture = false) {
    if (disposed) {if (!retainPicture) finishRetained();return;}
    clearTimeout(expiryTimer); expiryTimer = null;
    disposed = true; abort.abort(); controller?.(); video?.remove(); release();
    if (!retainPicture) finishRetained();
  }
  async function seekToResume(result, position) {
    const duration = result.mode === 'native' ? result.duration : known.onTimeline?.[0] || video.duration;
    if (!Number.isFinite(duration) || position >= duration) throw Error('Invalid standby resume position');
    const until = Math.min(deadline, Date.now() + 2000);
    if (result.mode === 'native') {
      const applied = await request('/' + id + '/control', {method:'POST',
        headers:{'content-type':'application/json'},
        body:JSON.stringify({seek:position,visible:false,paused:true,muted:true})}, until-Date.now());
      while (!disposed && !failed && Date.now() < until) {
        const status = await request('/' + id + '/status', {}, until-Date.now());
        const frame = status.native;
        if (status.state === 'failed' || frame?.state === 'failed') break;
        if (frame?.revision >= applied.revision && frame.outputReady && !frame.seeking &&
            frame.paused && frame.muted && !frame.visible && Math.abs(frame.time-position) <= .05) return;
        await new Promise(resolve => setTimeout(resolve, 20));
      }
    } else {
      let targetFrame = false, frameRequest = null;
      const origin = () => known.onWindowOrigin?.[0] || 0;
      const seeked = () => {if (!video.requestVideoFrameCallback) targetFrame = true;};
      const onFrame = (_, metadata) => {
        targetFrame = Math.abs(metadata.mediaTime + origin() - position) <= .05;
        if (!targetFrame && !disposed && Date.now() < until)
          frameRequest = video.requestVideoFrameCallback(onFrame);
      };
      video.addEventListener('seeked',seeked);
      try {
        if (video.requestVideoFrameCallback) frameRequest = video.requestVideoFrameCallback(onFrame);
        delete known.onReady;
        controller.seek(position);
        while (!disposed && !failed && Date.now() < until) {
          if (targetFrame && known.onReady && !video.seeking && video.paused && video.readyState >= 2 &&
              Math.abs(video.currentTime + origin() - position) <= .05) return;
          await new Promise(resolve => setTimeout(resolve, 20));
        }
      } finally {
        video.removeEventListener('seeked',seeked);
        if (frameRequest !== null) video.cancelVideoFrameCallback?.(frameRequest);
      }
    }
    throw Error('Standby resume frame timed out');
  }
  const preparation = {
    get failed() {return failed;},
    get settings() {return {rate:currentMedia.playbackRate || 1, volume:currentMedia.volume, muted:currentMedia.muted};},
    get resumePosition() {return resumePosition;},
    get resumeFailed() {return resumeFailed;},
    get resumeInvalid() {return resumeInvalid;},
    dispose() {if (!claimed) cleanup();},
    retain(fn) {
      retained.push(fn);
      // A stalled resolver/failed transfer cannot retain old sessions forever.
      retireTimer ||= setTimeout(finishRetained, 90000);
    },
    finishRetained,
    cancelClaim: cleanup,
    claim: async () => null,
    async claimRecord(wanted, position = 0) {
      if (disposed || claimed || Date.now() >= deadline || wanted !== url) {preparation.dispose(); return null;}
      claimed = true; clearTimeout(expiryTimer); expiryTimer = null;
      resumePosition = position;
      if (!Number.isFinite(position) || position < 0 || position > 86400) {
        resumeInvalid = resumeFailed = true; resumePosition = 0; cleanup(true); return null;
      }
      const result = await prepared;
      if (!result || disposed) {cleanup(true); return null;}
      const duration = result.mode === 'native' ? result.duration : known.onTimeline?.[0] || video.duration;
      if (Number.isFinite(duration) && duration > 0 && position >= duration) {
        resumeInvalid = resumeFailed = true; resumePosition = 0; cleanup(true); return null;
      }
      if (position > .05) {
        try {await seekToResume(result,position);} catch {resumeFailed = true;cleanup(true);return null;}
        if (disposed) return null;
      }
      return {...result, settings:preparation.settings};
    }
  };
  expiryTimer = setTimeout(() => {if (!claimed) {failed = true; cleanup();}}, 90000);
  desktopStandbys.set(currentMedia, preparation);
  const callbacks = Object.fromEntries(['onTimeline','onPlayableRange','onComplete','onWindowOrigin',
    'onReady','onError','onAcceptanceHlsTransition'].map(name => [name, (...args) => {
    known[name] = args;
    if (name === 'onError') {failed = true; if (!claimed) cleanup();}
    consumer?.[name]?.(...args);
  }]));
  const prepared = (async () => {
    try {
      const capability = await request('/capabilities');
      if (capability.standbyPlayback !== 1 || disposed) return null;
      const created = await fetchJson(endpoint.url, {method:'POST',
        headers:{'x-desktop-codec-negotiation':'1','x-desktop-prewarm-parent':parent}});
      const identifier = created.id;
      if (!/^[a-f0-9]{32}$/.test(identifier)) throw Error('Invalid standby');
      id = identifier;
      if (disposed) {release(); return null;}
      let value;
      while (!disposed && Date.now() < deadline) {
        value = await request('/' + id + '/status');
        if (value.state === 'failed') throw Error('Standby source failed');
        if (value.source) break;
        await new Promise(resolve => setTimeout(resolve, 200));
      }
      if (disposed || !value?.source) throw Error('Standby source timed out');
      mode = capability.nativePlayback === 1 && value.source.video?.contentType?.startsWith('video/mp4; codecs="hvc1.')
        ? 'native' : await desktopSupportsSource(value.source) ? 'copy' : 'h264';
      await request('/' + id + '/mode', {method:'POST', headers:{'content-type':'application/json'},body:JSON.stringify({mode})});
      if (mode === 'native') {
        let placement = null;
        while (!disposed && Date.now() < deadline) {
          value = await request('/' + id + '/status');
          if (value.state === 'failed' || value.native?.state === 'failed') throw Error('Standby decoder failed');
          if (Number.isInteger(value.native?.revision) && placement === null) {
            placement=(await request('/'+id+'/control',{method:'POST',headers:{'content-type':'application/json'},
              body:JSON.stringify({rect:desktopNativeSurfaceRect(currentMedia),
                visible:false,paused:true,muted:true,rate:currentMedia.playbackRate || 1})})).revision;
          }
          if (value.native?.outputReady && placement !== null && value.native.revision >= placement) {
            if (value.native.time > .05 || value.native.paused === false || value.native.muted === false || value.native.visible === true)
              throw Error('Standby advanced beyond its opening frame');
            return {id, mode, source:value.source, duration:value.native.duration || value.duration, dispose:cleanup};
          }
          await new Promise(resolve => setTimeout(resolve, 100));
        }
        throw Error('Standby frame timed out');
      }
      video = document.createElement('video');
      video.className = 'validation-video'; video.playsInline = true;
      video.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;object-fit:contain;pointer-events:none;opacity:0';
      video.muted = true; video.volume = 0; video.playbackRate = currentMedia.playbackRate || 1;
      (currentMedia.closest('.player-stage') || currentMedia.parentElement).append(video);
      controller = desktopCodecHls(video, url, 0, callbacks,
        {claim:async()=>id,dispose(){}}, false, {paused:true,standbyParent:parent});
      while (!disposed && !failed && Date.now() < deadline) {
        if (video.readyState >= 2 && video.videoWidth > 0 && known.onReady) break;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      if (disposed || failed || video.readyState < 2 || video.videoWidth <= 0 || !known.onReady ||
          !video.paused || video.currentTime > .05) throw Error('Standby video timed out');
      id = controller.sessionId?.() || id;
      return {id, mode, dispose:cleanup, adopt(media, handlers, onFailure) {
        if (disposed) return null;
        const saved = new Map(), listeners = [];
        let closed = false, activationComplete = false, wantsPlayback = true;
        const settings = {rate:currentMedia.playbackRate || 1,volume:currentMedia.volume,muted:currentMedia.muted};
        const property = (name, descriptor) => {
          saved.set(name,Object.getOwnPropertyDescriptor(media,name));
          Object.defineProperty(media,name,{configurable:true,...descriptor});
        };
        for (const name of ['currentTime','playbackRate','volume','muted'])
          property(name,{get:()=>video[name],set:v=>{video[name]=v;}});
        for (const name of ['paused','ended','duration','readyState','videoWidth','videoHeight','buffered','seeking','error'])
          property(name,{get:()=>video[name]});
        property('play',{value:()=>{wantsPlayback=true;return activationComplete ? video.play() : Promise.resolve();}});
        property('pause',{value:()=>{wantsPlayback=false;video.pause();}});
        property('desktopDisplayMedia',{value:video});
        property('desktopSessionId',{value:()=>controller?.sessionId?.() ?? null});
        for (const name of ['play','playing','pause','ended','timeupdate','waiting','seeking','seeked','progress','volumechange','ratechange','error','loadedmetadata','durationchange']) {
          const forward=()=>{if(!closed)media.dispatchEvent(new Event(name));};
          video.addEventListener(name,forward);listeners.push([name,forward]);
        }
        consumer = handlers;
        video.playbackRate=settings.rate;video.volume=settings.volume;video.muted=settings.muted;
        video.style.opacity='1';
        for (const name of ['onTimeline','onPlayableRange','onComplete','onWindowOrigin','onReady','onAcceptanceHlsTransition'])
          if (known[name]) handlers[name]?.(...known[name]);
        media.dispatchEvent(new Event('loadedmetadata'));media.dispatchEvent(new Event('durationchange'));
        const restoreAdoption = () => {
          if (closed) return false;
          const live = {playbackRate:video.playbackRate,volume:video.volume,muted:video.muted};
          closed=true;consumer=null;
          for(const [name,fn] of listeners)video.removeEventListener(name,fn);
          for(const [name,descriptor] of saved){if(descriptor)Object.defineProperty(media,name,descriptor);else delete media[name];}
          Object.assign(media,live);
          return true;
        };
        (async () => {
          const until = Math.min(deadline, Date.now()+2000);
          const sessionId = () => controller?.sessionId ? controller.sessionId() : id;
          while (!disposed && !closed && Date.now() < until) {
            const activeId = sessionId();
            if (activeId) {
              try {
                await request('/'+activeId+'/activate',{method:'POST'},until-Date.now());
              } catch (error) {
                if (sessionId() === activeId) throw error;
              }
              if (disposed || closed) return;
              if (sessionId() === activeId) {
                controller?.activate?.();activationComplete=true;return;
              }
            }
            await new Promise(resolve=>setTimeout(resolve,20));
          }
          if (!disposed && !closed) throw Error('Standby activation timed out');
        })().then(async () => {
          if (disposed || closed || !wantsPlayback) return;
          try {await video.play();} catch (error) {if (wantsPlayback) throw error;}
        }).then(() => {
          if (disposed) return;
          if (!wantsPlayback) finishRetained();
          else if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(finishRetained);
          else requestAnimationFrame(finishRetained);
        }).catch(()=>{
          if (closed || disposed) return;
          restoreAdoption();cleanup(true);
          if (onFailure) onFailure(); else handlers.onError?.();
        });
        return Object.assign(() => {
          if(restoreAdoption())cleanup();
        },{seek:value=>controller?.seek(value),sessionId:()=>controller?.sessionId?.() ?? null});
      }};
    } catch {
      failed = true; if (!claimed) cleanup(); else {release();video?.remove();}
      return null;
    }
  })();
  return preparation;
}
