// Paint the existing DOM controls into libmpv's alpha overlay. The original
// DOM remains the only input, focus, playback and accessibility owner.
export function desktopControlsCanHide(stage, dragging) {
  return !dragging && !stage?.querySelector('.player-chrome:hover,.player-chrome :focus-visible,.player-chrome :active,.desktop-danmaku-panel');
}

export function desktopNativeControlsOverlay(media, stage, send, onReady) {
  const paintProperties = ('display position left right top bottom width height min-width max-width min-height max-height box-sizing flex flex-direction flex-wrap align-items align-self justify-content gap margin padding border border-radius font-family font-size font-weight font-style line-height letter-spacing text-align text-decoration white-space vertical-align color background outline box-shadow opacity transform transform-origin filter overflow appearance accent-color color-scheme fill stroke stroke-width').split(' ');
  let disposed = false, busy = false, ready = false, previous = '', css = null;
  // paint() compares the resolved control image, including time and layout.
  // Status-driven DOM mutations alone must not reset that comparison.
  const headObserver = new MutationObserver(() => {css = null;});
  headObserver.observe(document.head, {subtree:true, childList:true, characterData:true});
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d', {willReadFrequently:true});
  async function paint() {
    if (disposed || busy || document.hidden) return;
    const chrome = stage.querySelector('.player-chrome');
    if (!chrome || !context) return;
    const rect = stage.getBoundingClientRect(), box = chrome.getBoundingClientRect();
    const scale = devicePixelRatio || 1;
    const width = Math.ceil(rect.width * scale), height = Math.ceil(box.height * scale);
    if (width < 1 || height < 1 || width > 8192 || height > 512 || width * height > 1048576) return;
    busy = true;
    try {
      if (css === null) css = [...document.styleSheets].flatMap(sheet => {
        try { return [...sheet.cssRules].map(rule => rule.cssText); } catch { return []; }
      }).join('\n');
      const wrapper = document.createElement('div');
      wrapper.className = 'desktop-player';
      wrapper.style.cssText = `background:transparent;width:${rect.width}px;height:${rect.height}px`;
      const styles = document.createElement('style'); styles.textContent = css; wrapper.append(styles);
      const stageClone = document.createElement('div'); stageClone.className = stage.className;
      stageClone.style.cssText = `background:transparent;width:${rect.width}px;height:${rect.height}px`;
      for (const original of [stage.querySelector('.player-idle-progress'), chrome].filter(Boolean)) {
        const clone = original.cloneNode(true);
        // The panel keeps its real DOM surface and its intentional opaque card.
        clone.querySelectorAll('.desktop-danmaku-panel').forEach(node => node.remove());
        const nodes = [original, ...original.querySelectorAll('*')].filter(node => !node.closest('.desktop-danmaku-panel'));
        [clone, ...clone.querySelectorAll('*')].forEach((node,index) => {
          const source = nodes[index], computed = getComputedStyle(source);
          // Freeze the host's resolved layout as well as its colors. The SVG
          // has its own viewport; reevaluating vw/media/container rules there
          // can move buttons away from their real DOM input targets.
          for (const property of paintProperties)
            node.style.setProperty(property, computed.getPropertyValue(property));
          node.style.transition = 'none'; node.style.animation = 'none';
          if (source instanceof HTMLInputElement) node.setAttribute('value', source.value);
          if (source instanceof HTMLSelectElement) for (const option of node.options)
            option.toggleAttribute('selected', option.value === source.value);
        });
        if (original === chrome) clone.style.background = 'transparent';
        stageClone.append(clone);
      }
      wrapper.append(stageClone);
      // Host :root styles also match an SVG document's root. Override its
      // background explicitly so a light application theme cannot paint a slab.
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" style="background:transparent!important" width="${width}" height="${height}" viewBox="0 0 ${rect.width} ${box.height}"><foreignObject x="0" y="${-(box.top-rect.top)}" width="${rect.width}" height="${rect.height}">${new XMLSerializer().serializeToString(wrapper)}</foreignObject></svg>`;
      if (svg === previous) return;
      const image = new Image();
      image.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svg)));
      await image.decode();
      if (disposed) return;
      canvas.width = width; canvas.height = height; context.clearRect(0,0,width,height);
      context.drawImage(image,0,0,width,height);
      const pixels = context.getImageData(0,0,width,height).data;
      for (let i=0;i<pixels.length;i+=4) {
        const red=pixels[i], alpha=pixels[i+3]/255;
        pixels[i]=Math.round(pixels[i+2]*alpha); pixels[i+1]=Math.round(pixels[i+1]*alpha); pixels[i+2]=Math.round(red*alpha);
      }
      const compressed = new Uint8Array(await new Response(new Blob([pixels]).stream().pipeThrough(new CompressionStream('deflate'))).arrayBuffer());
      if (disposed || compressed.length > 393216) return;
      let encoded='';
      for(let i=0;i<compressed.length;i+=8192) encoded+=String.fromCharCode(...compressed.subarray(i,i+8192));
      send({controlsOverlay:{x:0,y:Math.max(0,Math.floor((box.top-rect.top)*scale)),width,height,data:btoa(encoded)}});
      const recovered = !!media.desktopControlsOverlayError;
      delete media.desktopControlsOverlayError;
      previous=svg;
      if (!ready || recovered) {ready=true;onReady();}
    } catch (error) {
      // Keep the original DOM cutout operable if this runtime cannot rasterize.
      media.desktopControlsOverlayError = String(error);
      onReady();
    } finally { busy=false; }
  }
  const timer = setInterval(paint,120);
  paint();
  return {get ready(){return ready;}, dispose(){disposed=true;clearInterval(timer);headObserver.disconnect();}};
}
