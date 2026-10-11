"""One owned ASS track; ordinary position polls never replace it."""
import time
from desktop_danmaku import DEFAULT_SETTINGS, validate_danmaku, validate_settings, ass_document, active_danmaku

class DanmakuTrack:
    def __init__(self, *, assets=None, clock=time.monotonic):
        self.assets = assets or {}
        self.clock = clock
        self.items = []
        self.settings = dict(DEFAULT_SETTINGS)
        self.track_id = None
        self.document = ''
        self.dirty = False
        self.failed = False
        self.loads = 0
        self.saved = None
        self.saved_options = None
        self.modified_options = {}
        self.reload_options = False
        self.promoted = False
        self.pending_removals = set()
        self.retry_at = 0

    def update(self, command):
        items = validate_danmaku(command['danmaku']) if 'danmaku' in command else self.items
        settings = validate_settings(command['danmakuSettings']) if 'danmakuSettings' in command else self.settings
        if items != self.items or settings != self.settings or self.failed:
            self.items, self.settings = items, settings
            self.dirty = True
            if not items: self.retry_at = 0

    def source_reloaded(self):
        # Old IDs belong to the discarded file, never remove them in the new one.
        self.track_id, self.document, self.dirty = None, '', True
        self.saved = None
        self.reload_options = self.saved_options is not None
        self.promoted = False
        self.pending_removals.clear()
        self.retry_at = 0

    @staticmethod
    def selected(value):
        return str(value or '').isdigit() and int(value) > 0

    def preserve_captions(self, player):
        if self.saved is not None:
            return
        primary = player.get('sid') or 'no'
        secondary = player.get('secondary-sid') or 'no'
        if self.selected(primary) and self.selected(secondary):
            # mpv has two subtitle slots. Leave both user caption tracks intact.
            raise RuntimeError('Both subtitle slots are in use')
        self.saved = (primary, secondary, player.get('secondary-sub-ass-override') or 'strip')
        self.saved_options = {name:player.get(name) or default for name,default in (
            ('sub-ass-override','scale'),('secondary-sub-ass-override','strip'),
            ('sub-delay','0'),('secondary-sub-delay','0'),
            ('sub-visibility','yes'),('secondary-sub-visibility','yes'),
            ('sub-pos','100'),('secondary-sub-pos','0'))}

    def set_option(self, player, name, value):
        if str(player.get(name)) != str(value):
            self.modified_options[name] = str(value)
            player.command('set', name, value)
            # mpv canonicalizes numeric properties (e.g. 0 -> 0.000000).
            self.modified_options[name] = str(player.get(name))

    def restore_options(self, player, *, retain=False):
        for name,value in self.modified_options.items():
            if str(player.get(name)) == value:
                player.command('set', name, self.saved_options[name])
        if not retain: self.saved_options = None
        self.modified_options = {}
        self.reload_options = False

    def show_captions(self, player):
        if self.saved is None:
            return
        live = player.get('sid') or 'no'
        secondary = player.get('secondary-sid') or 'no'
        if str(live) != str(self.track_id):
            if self.selected(live) and self.selected(secondary) and (
                    not self.promoted or str(secondary) != str(self.saved[0])):
                raise RuntimeError('Both subtitle slots are in use')
            if self.promoted and str(secondary) == str(self.saved[0]):
                player.command('set', 'secondary-sid', self.saved[1])
            self.saved = (live, self.saved[1], self.saved[2])
            self.promoted = False
            player.command('set', 'sid', self.track_id)
            if str(player.get('sid')) != str(self.track_id):
                raise RuntimeError('Native danmaku track selection failed')
        # ASS motion is absolute video time, independent of caption overrides.
        self.set_option(player, 'sub-ass-override', 'no')
        self.set_option(player, 'sub-delay', '0')
        self.set_option(player, 'sub-visibility', 'yes')
        if not self.selected(self.saved[0]):
            return
        primary = self.saved[0]
        secondary = player.get('secondary-sid') or 'no'
        if self.selected(secondary) and str(secondary) != str(primary):
            raise RuntimeError('Secondary subtitle slot changed')
        # mpv refuses the same track in both slots. Select the overlay first,
        # then move the saved caption; assigning it before sub-add loses it.
        self.promoted = True
        self.set_option(player, 'secondary-sub-ass-override', self.saved_options['sub-ass-override'])
        self.set_option(player, 'secondary-sub-delay', self.saved_options['sub-delay'])
        self.set_option(player, 'secondary-sub-visibility', self.saved_options['sub-visibility'])
        self.set_option(player, 'secondary-sub-pos', self.saved_options['sub-pos'])
        if str(player.get('secondary-sid')) != str(primary):
            player.command('set', 'secondary-sid', primary)

    def restore_captions(self, player, *, retain=False):
        if self.saved is None:
            if self.saved_options is not None: self.restore_options(player)
            return
        primary, secondary, override = self.saved
        if self.promoted and str(player.get('secondary-sid')) in (str(primary),str(secondary)):
            player.command('set', 'secondary-sid', secondary)
        if str(player.get('sid')) == str(self.track_id):
            player.command('set', 'sid', primary)
        self.restore_options(player, retain=retain)

    def remove_pending(self, player):
        for identifier in tuple(self.pending_removals):
            try:
                player.command('sub-remove', identifier)
                self.pending_removals.remove(identifier)
            except RuntimeError:
                self.dirty = True
                self.retry_at = self.clock() + 1

    def close(self, player):
        # Called before stop/pool release while the file and its caption IDs exist.
        self.restore_captions(player)
        if self.track_id: self.pending_removals.add(self.track_id)
        for identifier in tuple(self.pending_removals):
            player.command('sub-remove', identifier)
            self.pending_removals.remove(identifier)
        self.track_id, self.document, self.saved = None, '', None
        self.promoted = False

    def apply(self, player):
        if self.track_id and str(player.get('sid')) != str(self.track_id):
            self.dirty = True
        if not self.dirty or self.clock() < self.retry_at and (self.track_id or self.items or self.pending_removals):
            return
        self.dirty = False
        try:
            if self.reload_options: self.restore_options(player)
            document = ass_document(self.items, self.settings, assets=self.assets) if self.items else ''
            if not any(line.startswith('Dialogue:') for line in document.splitlines()):
                document = ''
            if document == self.document:
                if document:
                    self.show_captions(player)
                    self.remove_pending(player)
                else:
                    self.restore_captions(player)
                    self.saved = None
                    self.promoted = False
                    self.remove_pending(player)
                self.failed = False
                return
            previous = self.track_id
            if document:
                self.preserve_captions(player)
                if previous: self.show_captions(player)
                player.command('sub-add', 'memory://' + document, 'select', 'Hongguo danmaku')
                selected = str(player.get('sid') or '')
                if not selected.isdigit():
                    raise RuntimeError('Native danmaku track unavailable')
                self.track_id = selected
                self.loads += 1
                self.document = document
                if previous and previous != self.track_id:
                    self.pending_removals.add(previous)
                self.show_captions(player)
                if self.pending_removals:
                    self.remove_pending(player)
            else:
                self.restore_captions(player, retain=True)
                # Keep the ID until removal succeeds, including transient errors.
                if previous:
                    player.command('sub-remove', previous)
                self.track_id, self.document, self.saved = None, '', None
                self.saved_options = None
                self.promoted = False
                self.remove_pending(player)
            self.failed = False
        except (RuntimeError, ValueError, TypeError, KeyError):
            # Retry on the video owner thread at most once a second; never stop A/V.
            self.failed = True
            self.dirty = True
            self.retry_at = self.clock() + 1

    def snapshot(self, seconds):
        return {'danmakuVisible': bool(self.track_id) and not self.failed and bool(active_danmaku(self.items, seconds, self.settings)),
                'danmakuFailed': self.failed, 'danmakuRenderer': 'ass-timeline',
                'danmakuLoads': self.loads, 'danmakuSettings': dict(self.settings)}
