"""Named, indexed complete MP4 originals; no media URL or credentials are persisted."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import unicodedata

OWNER = 'hongguo-video-library-v1'
IDENTITY = re.compile(r'[0-9]{8,24}').fullmatch


def safe_name(value):
    value = unicodedata.normalize('NFC', str(value or ''))
    value = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', value)
    value = re.sub(r'\s+', ' ', value).strip(' .')[:36].rstrip(' .') or '未命名短剧'
    if re.fullmatch(r'(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', value):
        value = '_' + value
    return value


def series_names(meta):
    title = str(meta.get('title') or '未命名短剧')
    season = meta.get('season_number', meta.get('season'))
    if isinstance(season, str) and season.isdecimal():
        season = int(season)
    match = re.search(r'第([0-9一二三四五六七八九十百两]{1,5})季', title)
    if not (type(season) is int and 1 <= season <= 999):
        season = None
        if match:
            text = match[1]
            if text.isdecimal():
                season = int(text)
            else:
                digits = dict(zip('一二三四五六七八九两', (1,2,3,4,5,6,7,8,9,2)))
                result, current = 0, 0
                for char in text:
                    if char in digits:
                        current = digits[char]
                    else:
                        result += (current or 1) * {'十':10, '百':100}[char]
                        current = 0
                season = result + current
    if match and type(season) is int and 1 <= season <= 999:
        title = title[:match.start()] + title[match.end():]
    return safe_name(title), f'第{season:02d}季' if type(season) is int and 1 <= season <= 999 else '未分季'


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


class VideoLibrary:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        self.path = self.root/'.video-library.json'
        self.guard = threading.RLock()
        self.verified = {}
        self.value = {'owner':OWNER, 'series':{}, 'files':{}}
        self.index_digest = None
        if self.path.exists() or self.path.is_symlink():
            self._plain(self.path)
            if self.path.stat().st_size > 8*1024*1024:
                raise OSError('Video library index is too large')
            try:
                value = json.loads(self.path.read_text(encoding='utf8'))
                if (value.get('owner') != OWNER or set(value) != {'owner','series','files'}
                        or not isinstance(value['series'], dict) or not isinstance(value['files'], dict)):
                    raise ValueError('Unknown library owner')
                for sid, details in value['series'].items():
                    if not IDENTITY(sid) or set(details) != {'title','name','season','episodes'}:
                        raise ValueError('Invalid series identity')
                    if (not isinstance(details['title'], str) or details['name'] != safe_name(details['name'])
                            or not re.fullmatch(r'第[0-9]{2,3}季|未分季', details['season'])
                            or not isinstance(details['episodes'], list)):
                        raise ValueError('Invalid series names')
                    for item in details['episodes']:
                        if set(item) != {'index','vid'} or type(item['index']) is not int or not 1 <= item['index'] <= 100000 or not IDENTITY(item['vid']):
                            raise ValueError('Invalid episode identity')
                for vid, record in value['files'].items():
                    self._relative(vid, record)
                self.value = value
                self.index_digest = digest(self.path)
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                raise OSError('Invalid video library index; existing content preserved') from exc

    def _plain(self, path):
        path = Path(path)
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            raise OSError('Video path is outside its library') from None
        current = self.root
        for name in (None, *relative.parts):
            if name is not None:
                current = current/name
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise OSError('Linked video library content is preserved')
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise OSError('Unknown video library content')
        return path

    @staticmethod
    def _relative(vid, record):
        if (not IDENTITY(vid) or set(record) != {'seriesId','name','season','episode','relative','bytes','sha256'}
                or not IDENTITY(record['seriesId']) or record['name'] != safe_name(record['name'])
                or not re.fullmatch(r'第[0-9]{2,3}季|未分季', record['season'])
                or type(record['episode']) is not int or not 1 <= record['episode'] <= 100000
                or type(record['bytes']) is not int or record['bytes'] <= 0
                or not re.fullmatch('[0-9a-f]{64}',record['sha256'])):
            raise ValueError('Invalid complete original record')
        name, season, episode = record['name'],record['season'],record['episode']
        base = f'{name} [{record["seriesId"]}]/{season}/{name}_{season}_第{episode:03d}集'
        if record['relative'] not in (base+'.mp4', base+f'_{vid}.mp4'):
            raise ValueError('Invalid original path')
        return Path(*record['relative'].split('/'))

    def _save(self):
        # Refuse to replace unknown/linked metadata introduced during this session.
        if self.path.exists() or self.path.is_symlink():
            self._plain(self.path)
            if digest(self.path) != self.index_digest:
                raise OSError('Video library index changed outside this session')
        elif self.index_digest is not None:
            raise OSError('Video library index was removed outside this session')
        data = json.dumps(self.value,ensure_ascii=False,indent=2).encode('utf8')
        if len(data) > 8*1024*1024:
            raise OSError('Video library index is too large')
        fd, temporary = tempfile.mkstemp(prefix='.video-library-', dir=self.root)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,self.path)
            self.index_digest = hashlib.sha256(data).hexdigest()
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def register(self, series_id, meta, episodes):
        sid = str(series_id)
        if not IDENTITY(sid):
            raise ValueError('Invalid series identity')
        name, season = series_names(meta)
        items = [];seen = set()
        for item in episodes:
            index,vid = item.get('index'),str(item.get('vid',''))
            if type(index) is int and 1 <= index <= 100000 and IDENTITY(vid) and index not in seen:
                items.append({'index':index,'vid':vid});seen.add(index)
        details = {'title':str(meta.get('title') or '未命名短剧')[:500], 'name':name, 'season':season, 'episodes':sorted(items,key=lambda item:item['index'])}
        with self.guard:
            if self.value['series'].get(sid) != details:
                previous = self.value['series'].get(sid)
                self.value['series'][sid] = details
                try:
                    self._save()
                except OSError:
                    if previous is None:self.value['series'].pop(sid,None)
                    else:self.value['series'][sid] = previous
                    raise

    def _identity(self, vid):
        for sid,details in self.value['series'].items():
            for episode in details['episodes']:
                if episode['vid'] == vid:
                    return sid,details,episode['index']
        raise OSError('Episode naming metadata unavailable')

    def target(self, vid):
        with self.guard:
            sid,details,index = self._identity(vid)
            name,season = details['name'],details['season']
            folder = self.root/f'{name} [{sid}]'/season
            # Create one component at a time, checking existing components first.
            for path in (folder.parent,folder):
                if path.exists() or path.is_symlink():self._plain(path)
                else:path.mkdir()
                self._plain(path)
            output = folder/f'{name}_{season}_第{index:03d}集.mp4'
            if (output.exists() or output.is_symlink()) and self.value['files'].get(vid,{}).get('relative') != output.relative_to(self.root).as_posix():
                output = folder/f'{name}_{season}_第{index:03d}集_{vid}.mp4'
            self._plain(output.parent)
            return output

    def prepare_publish(self, vid, staged, output):
        """Persist identity first; a crash before MP4 publication leaves no valid hit."""
        with self.guard:
            sid,details,index = self._identity(vid)
            record = {'seriesId':sid,'name':details['name'],'season':details['season'],'episode':index,
                      'relative':Path(output).relative_to(self.root).as_posix(),
                      'bytes':Path(staged).stat().st_size,'sha256':digest(staged)}
            self._relative(vid,record);self._plain(Path(output).parent)
            previous = self.value['files'].get(vid)
            self.value['files'][vid] = record
            try:self._save()
            except OSError:
                if previous is None:self.value['files'].pop(vid,None)
                else:self.value['files'][vid] = previous
                raise
            self.verified.pop(vid,None)

    def lookup(self, vid):
        with self.guard:
            record = self.value['files'].get(vid)
            if record is None:return None
            path = self.root/self._relative(vid,record)
            try:
                self._plain(path)
                info = path.stat()
                fingerprint = (info.st_size,info.st_mtime_ns,info.st_ctime_ns)
                if not path.is_file() or info.st_size != record['bytes']:return None
                if self.verified.get(vid) != fingerprint:
                    if digest(path) != record['sha256']:return None
                    self.verified[vid] = fingerprint
                return path
            except (OSError,ValueError):
                return None

    def originals(self):
        with self.guard:
            return {path:vid for vid in self.value['files'] if (path:=self.lookup(vid)) is not None}

    def forget(self, paths):
        paths = {Path(p) for p in paths}
        with self.guard:
            removed = {vid:record for vid,record in self.value['files'].items() if self.root/self._relative(vid,record) in paths}
            for vid in removed:self.value['files'].pop(vid);self.verified.pop(vid,None)
            if removed:
                try:self._save()
                except OSError:
                    self.value['files'].update(removed)
                    raise
            for path in paths:
                # Only remove the two now-empty named directories, never unknown content.
                if path.parent.parent.parent != self.root:continue
                for folder in (path.parent,path.parent.parent):
                    try:self._plain(folder);folder.rmdir()
                    except OSError:pass
