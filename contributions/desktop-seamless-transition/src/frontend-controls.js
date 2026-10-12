// Media teardown may reset `ended` before the controls receive the EOF event.
// Episode loading is internal; only ordinary pause/end should reveal controls.
function desktopControlsShouldReveal(event, media, {
  disabled = false, autoContinue = false, transitioning = false
} = {}) {
  const type = event?.type;
  if (disabled || transitioning || !media?.paused ||
      (type !== 'pause' && type !== 'ended')) return false;
  return !(autoContinue && (type === 'ended' || media.ended));
}
