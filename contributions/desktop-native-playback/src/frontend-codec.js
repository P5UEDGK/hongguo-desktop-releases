// Inserted into the recovered bundle; original HLS controllers keep their lifecycle.
async function desktopSupportsSource(source) {
  try {
    if (!source?.copyEligible || !source.video || !Array.isArray(source.audio) || source.audio.length > 1) return false;
    const types = [source.video.contentType, ...source.audio.map(a => a.contentType)];
    if (!globalThis.MediaSource || !types.every(t => MediaSource.isTypeSupported(t))) return false;
    if (!navigator.mediaCapabilities?.decodingInfo) return false;
    const config = {type: 'media-source', video: source.video};
    if (source.audio.length) config.audio = source.audio[0];
    const info = await Promise.race([
      navigator.mediaCapabilities.decodingInfo(config),
      new Promise(resolve => setTimeout(() => resolve({supported: false}), 2000))
    ]);
    return info?.supported === true;
  } catch { return false; }
}

function desktopCreateCodecFetch(forceH264 = false) {
  let closed = false, usedCopy = false, failureCode = null;
  const pending = new Map();
  const request = async (input, init = {}) => {
    const url = new URL(input);
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' ||
        !url.pathname.startsWith('/desktop/hls')) throw Error('Invalid codec endpoint');
    if (closed && init.method !== 'DELETE') throw Error('Expired codec controller');
    const headers = new Headers(init.headers);
    if (!forceH264 && init.method === 'POST' && url.pathname === '/desktop/hls')
      headers.set('x-desktop-codec-negotiation', '1');
    const response = await fetch(input, {...init, headers});
    if (!response.ok || init.method === 'DELETE' || !/\/desktop\/hls\/[a-f0-9]{32}\/status$/.test(url.pathname))
      return response;
    const status = await response.clone().json();
    failureCode = status.failureCode || null;
    if (closed || init.signal?.aborted) return response;
    if (status.videoMode) usedCopy = status.videoMode === 'copy';
    if (!forceH264 && status.source && status.videoMode === null) {
      if (!pending.has(url.pathname)) pending.set(url.pathname, (async () => {
        const copy = !status.startSeconds && await desktopSupportsSource(status.source);
        if (closed || init.signal?.aborted) return;
        const selected = await fetch(url.href.replace(/\/status$/, '/mode'), {
          method: 'POST', headers: new Headers([...headers, ['content-type', 'application/json']]),
          body: JSON.stringify({mode: copy ? 'copy' : 'h264'}),
          credentials: 'omit', redirect: 'error', cache: 'no-store', signal: init.signal
        });
        if (selected.ok) usedCopy = (await selected.json()).mode === 'copy';
        else if (selected.status !== 409) throw Error('Codec selection failed');
      })());
      await pending.get(url.pathname);
    }
    return response;
  };
  request.usedCopy = () => usedCopy;
  request.failureCode = () => failureCode;
  request.close = () => {closed = true;};
  return request;
}

function desktopCodecHls(media, url, initialPosition, callbacks, preparation, windowed = false, initialState = null) {
  let disposed = false, retried = false, epoch = 0, controller, transport;
  let position = initialPosition || 0, origin = 0, ready = false, wantedPlaying = initialState?.paused !== true;
  let rate = media.playbackRate || 1, watchdog, pauseUntil = 0, internalPause = false, internalPlay = false;
  const savedPause = Object.getOwnPropertyDescriptor(media, "pause"), originalPause = media.pause;
  const savedPlay = Object.getOwnPropertyDescriptor(media, "play"), originalPlay = media.play;
  const play = function(...args) {
    if (!internalPause && !internalPlay) {wantedPlaying = true; pauseUntil = 0;}
    return originalPlay.apply(media, args);
  };
  if (typeof originalPlay === "function") Object.defineProperty(media, "play", {configurable:true, writable:true, value:play});
  const pause = function(...args) {
    if (!internalPause) wantedPlaying = false;
    return originalPause.apply(media, args);
  };
  Object.defineProperty(media, "pause", {configurable:true, writable:true, value:pause});
  const rememberTime = () => {
    if (ready && Number.isFinite(media.currentTime)) position = media.currentTime + origin;
  };
  const onPlay = () => {
    if (!ready || internalPlay) return;
    if (Date.now() < pauseUntil) {media.pause(); return;}
    wantedPlaying = true;
  };
  const onPause = () => {if (ready && !internalPause) wantedPlaying = false;};
  const onPreparingPlaying = () => {
    if (!ready) {internalPause = true; queueMicrotask(() => {internalPause = false;});}
  };
  const onRateChange = () => {rate = media.playbackRate || rate;};
  function fallback() {
    if (disposed || retried || !transport?.usedCopy() || transport.failureCode?.() === 'source-read') return false;
    retried = true;
    rememberTime();
    const resume = position;
    rate = media.playbackRate || rate;
    start(true, Math.max(0, resume));
    return true;
  }
  function start(force, target) {
    const ownEpoch = ++epoch;
    clearTimeout(watchdog);
    ready = false;
    transport?.close();
    internalPause = true;
    try {controller?.();} finally {internalPause = false;}
    position = target;
    origin = 0;
    transport = desktopCreateCodecFetch(force);
    const active = () => !disposed && epoch === ownEpoch;
    const wrapped = {...callbacks,
      onReady() {
        if (!active()) return;
        ready = true;
        // The legacy controller invokes play synchronously after onReady.
        internalPlay = true;
        queueMicrotask(() => {internalPlay = false;});
        media.playbackRate = rate;
        callbacks.onReady();
        if (!wantedPlaying) {
          pauseUntil = Date.now() + 500;
          queueMicrotask(() => {if (active() && !wantedPlaying) media.pause();});
        }
        // A media element can play audio while silently failing video decoding.
        clearTimeout(watchdog);
        if (transport.usedCopy()) watchdog = setTimeout(() => {
          if (active() && !media.videoWidth) fallback();
        }, 8000);
      },
      onWindowOrigin(value) {if (active()) {origin = value; callbacks.onWindowOrigin?.(value);}},
      onAcceptanceHlsTransition(event) {
        if (!active()) return;
        if (['controllerFailPause', 'controllerSeekPause', 'controllerWaitResumePause',
             'controllerWaitDurationPause'].includes(event.kind)) {
          rememberTime(); ready = false; internalPause = true;
          queueMicrotask(() => {internalPause = false;});
        }
        callbacks.onAcceptanceHlsTransition?.(event);
      },
      onError() {if (active() && !fallback()) callbacks.onError();}
    };
    // Guard all remaining callbacks against a failed/replaced controller.
    for (const name of Object.keys(callbacks)) {
      if (!(name in wrapped) || wrapped[name] !== callbacks[name]) continue;
      if (typeof callbacks[name] === 'function') wrapped[name] = (...args) => {
        if (active()) callbacks[name](...args);
      };
    }
    internalPause = true;
    try {
      controller = windowed ? ek(media, url, target, wrapped, force ? null : preparation, transport)
        : desktopLegacyHls(media, url, target, wrapped, force ? null : preparation, false, transport);
    } finally {internalPause = false;}
  }
  const onError = event => {
    if (!disposed && !retried && transport?.usedCopy() && transport.failureCode?.() !== 'source-read') {
      event.stopImmediatePropagation();
      fallback();
    }
  };
  media.addEventListener('play', onPlay);
  media.addEventListener('pause', onPause);
  media.addEventListener('playing', onPreparingPlaying);
  media.addEventListener('ratechange', onRateChange);
  media.addEventListener('error', onError, true);
  media.addEventListener('timeupdate', rememberTime);
  start(initialState?.forceH264 === true, position);
  return Object.assign(() => {
    if (disposed) return;
    disposed = true; epoch++;
    clearTimeout(watchdog);
    transport?.close(); controller?.(); preparation?.dispose();
    media.removeEventListener('play', onPlay);
    media.removeEventListener('pause', onPause);
    media.removeEventListener('playing', onPreparingPlaying);
    media.removeEventListener('ratechange', onRateChange);
    if (media.pause === pause) {if (savedPause) Object.defineProperty(media, 'pause', savedPause); else delete media.pause;}
    if (media.play === play) {if (savedPlay) Object.defineProperty(media, 'play', savedPlay); else delete media.play;}
    media.removeEventListener('error', onError, true);
    media.removeEventListener('timeupdate', rememberTime);
  }, {seek(value) {if (!disposed) {
      position = value; internalPause = true;
      try {controller?.seek(value);} finally {internalPause = false; internalPlay = false;}
    }}});
}

// Complete backend prefetch owns speculative media. Keep the resolved episode
// metadata, but do not create a second legacy H264 session before negotiation.
function ik() {return {dispose() {}, claim: async () => null};}
