"""Bounded, plain-text danmaku rendered in libmpv's video surface."""
import math
import re

DEFAULT_SETTINGS = {"opacity": 80, "lanes": 3, "fontSize": 28, "duration": 14}


def emoji_parts(text):
    return [part for part in re.split(r'(\[[^\[\]\r\n]{1,16}\])',text) if part]


def validate_settings(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_SETTINGS):
        raise ValueError("Invalid danmaku settings")
    for key, low, high in (("opacity", 10, 100), ("lanes", 1, 6),
                           ("fontSize", 18, 36), ("duration", 4, 24)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("Invalid danmaku setting")
    return dict(value)


def validate_danmaku(items):
    if not isinstance(items, list) or len(items) > 300:
        raise ValueError("Invalid danmaku list")
    result = []
    for row in items:
        if not isinstance(row, dict) or set(row) not in ({"text", "offset_ms", "lane"}, {"text", "offset_ms", "lane", "motion_start_ms"}):
            raise ValueError("Invalid danmaku item")
        text, offset, lane = row["text"], row["offset_ms"], row["lane"]
        if (not isinstance(text, str) or len(text) > 200 or "\x00" in text
                or type(offset) is not int or not 0 <= offset <= 86400000
                or type(lane) is not int or not 0 <= lane < 6):
            raise ValueError("Invalid danmaku value")
        if "motion_start_ms" in row and (type(row["motion_start_ms"]) is not int
                or not -24000 <= row["motion_start_ms"] <= 86400000):
            raise ValueError("Invalid danmaku motion origin")
        result.append(dict(row))
    return result


def active_danmaku(items, seconds, settings):
    if not math.isfinite(seconds):
        return []
    return [row for row in items if row['lane'] < settings['lanes']
            and 0 <= seconds - row.get('motion_start_ms', row['offset_ms']) / 1000 < settings['duration']]


def ass_document(items, settings=None, *, assets=None, subtitle_speed=1, on_emitted=lambda row: None):
    """One timed track lets libass move glyphs on the video's presentation clock."""
    settings = validate_settings(DEFAULT_SETTINGS if settings is None else settings)
    items = validate_danmaku(items)
    assets = {} if assets is None else assets
    if not isinstance(subtitle_speed,(int,float)) or isinstance(subtitle_speed,bool) or not math.isfinite(subtitle_speed) or not .1<=subtitle_speed<=10:raise ValueError("Invalid subtitle speed")
    duration, size = settings["duration"], settings["fontSize"]
    alpha = f'{round(255 * (1 - settings["opacity"] / 100)):02X}'
    lines = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1000", "PlayResY: 562",
             "WrapStyle: 2", "ScaledBorderAndShadow: yes", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
             "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
             "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
             f"Style: Default,Microsoft YaHei,{size},&H{alpha}FFFFFF,&H{alpha}FFFFFF,&H{alpha}000000,"
             "&HFF000000,0,0,0,0,100,100,0,0,1,1.5,0,7,0,0,0,1", "[Events]",
             "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    def stamp(milliseconds):
        centiseconds = round(milliseconds / subtitle_speed / 10)
        hours, rest = divmod(centiseconds, 360000)
        minutes, rest = divmod(rest, 6000)
        seconds, fraction = divmod(rest, 100)
        return f'{hours}:{minutes:02}:{seconds:02}.{fraction:02}'
    event_count=0
    for row in items:
        if row["lane"] >= settings["lanes"]:
            continue
        origin = row.get('motion_start_ms', row['offset_ms'])
        start, end = max(0, origin), origin + duration * 1000
        if round(end / subtitle_speed / 10) <= round(start / subtitle_speed / 10):
            continue
        # ASS syntax cannot be supplied by comment text. Fullwidth equivalents
        # preserve readability, including literal backslashes and braces.
        text = row["text"].replace("\\", "＼").replace("{", "｛").replace("}", "｝")
        text = " ".join(text.split())
        parts=[]
        for part in emoji_parts(text):
            if part not in assets and parts and parts[-1] not in assets:parts[-1]+=part
            else:parts.append(part)
        events=sum(len(assets[part]['drawing']) if part in assets else 1 for part in parts)
        if not events:continue
        if event_count+events>2048:break
        event_count+=events
        on_emitted(row)
        width = max(60,sum(size+4 if part in assets else len(part)*size for part in parts))
        y = 25 + row["lane"] * (size + 15)
        progress = (start - origin) / (duration * 1000)
        prefix=f'Dialogue: 0,{stamp(start)},{stamp(end)},Default,,0,0,0,,'
        def movement(x,top):
            return r'{\an7\move(' + f'{1000-(1000+width)*progress+x:g},{top:g},{-width+x:g},{top:g},0,{round((end-start)/subtitle_speed)}' + r')\clip(0,0,1000,562)'
        x=0
        for part in parts:
            if part not in assets:
                lines.append(prefix+movement(x,y)+'}'+part)
                x+=len(part)*size
                continue
            scale=size/assets[part]['resolution']
            for group in assets[part]['drawing']:
                red,green,blue=group['color']
                opacity=round(255*(1-settings['opacity']/100*group['alpha']))
                points=[point for path in group['paths'] for point in path]
                min_x=min(point[0] for point in points); min_y=min(point[1] for point in points)
                shapes=[]
                for path in group['paths']:
                    pairs=[f'{(px-min_x)*scale:g} {(py-min_y)*scale:g}' for px,py in path]
                    shapes.append('m '+pairs[0]+' l '+' '.join(pairs[1:]))
                lines.append(prefix+movement(x+min_x*scale,y+min_y*scale)
                    +rf'\bord0\shad0\1c&H{blue:02X}{green:02X}{red:02X}&\1a&H{opacity:02X}&\p1'+'}'+' '.join(shapes))
            x+=size+4
    return '\n'.join(lines) + '\n'
