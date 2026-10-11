"""Validated injectable PNG catalog and ASS vector shapes; no network or APK access."""
import base64
import json
import math
import re
import struct
import zlib
from pathlib import Path

def load_assets(path):
    with Path(path).open("rb") as stream:
        data=stream.read(16*1024*1024+1)
    if len(data)>16*1024*1024: raise ValueError('Emoji catalog too large')
    return validate_assets(json.loads(data.decode('utf-8')))


def validate_png(png, width, height):
    """Validate the bounded PNG stream, CRCs and complete inflated scanlines."""
    depth,color,compression,filtering,interlace=png[24:29]
    depths={0:(1,2,4,8,16),2:(8,16),3:(1,2,4,8),4:(8,16),6:(8,16)}
    if color not in depths or depth not in depths[color] or compression or filtering or interlace not in (0,1):
        raise ValueError('Invalid emoji PNG format')
    cursor=8; compressed=bytearray(); palette=None; ended=False; idat=False; idat_closed=False
    while cursor<len(png):
        if cursor+12>len(png): raise ValueError('Truncated emoji PNG')
        length=int.from_bytes(png[cursor:cursor+4],'big');kind=png[cursor+4:cursor+8];end=cursor+12+length
        if end>len(png) or not re.fullmatch(b'[A-Za-z]{4}',kind) or kind[2]&32:
            raise ValueError('Invalid emoji PNG chunk')
        content=png[cursor+8:end-4]
        if zlib.crc32(kind+content)!=int.from_bytes(png[end-4:end],'big'):
            raise ValueError('Invalid emoji PNG CRC')
        if kind==b'IHDR':
            if cursor!=8 or length!=13: raise ValueError('Invalid emoji PNG header')
        elif kind==b'PLTE':
            if palette is not None or idat or color in (0,4) or length%3 or not 3<=length<=768 or color==3 and length//3>2**depth:
                raise ValueError('Invalid emoji PNG palette')
            palette=length//3
        elif kind==b'IDAT':
            if idat_closed or color==3 and palette is None: raise ValueError('Invalid emoji PNG data order')
            idat=True;compressed.extend(content)
        elif kind==b'IEND':
            if length or not idat or end!=len(png): raise ValueError('Invalid emoji PNG end')
            ended=True
        elif not kind[0]&32:
            raise ValueError('Unknown critical emoji PNG chunk')
        if idat and kind!=b'IDAT': idat_closed=True
        cursor=end
    if not ended: raise ValueError('Missing emoji PNG end')
    channels={0:1,2:3,3:1,4:2,6:4}[color];bits=channels*depth
    passes=[(0,0,1,1)] if not interlace else [(0,0,8,8),(4,0,8,8),(0,4,4,8),(2,0,4,4),(0,2,2,4),(1,0,2,2),(0,1,1,2)]
    shapes=[(max(0,(width-x+dx-1)//dx),max(0,(height-y+dy-1)//dy)) for x,y,dx,dy in passes]
    size=sum(h*(1+(w*bits+7)//8) for w,h in shapes if w and h)
    try:
        decoder=zlib.decompressobj();raw=decoder.decompress(compressed,size+1)
        if len(raw)!=size or not decoder.eof or decoder.unconsumed_tail: raise ValueError('Invalid emoji PNG pixels')
    except zlib.error: raise ValueError('Invalid emoji PNG compression') from None
    offset=0;bpp=max(1,(bits+7)//8)
    for w,h in shapes:
        if not w or not h: continue
        stride=(w*bits+7)//8;prior=bytearray(stride)
        for _ in range(h):
            method=raw[offset];offset+=1;row=bytearray(raw[offset:offset+stride]);offset+=stride
            if method>4: raise ValueError('Invalid emoji PNG filter')
            # Every non-indexed sample bit pattern is valid. Only palette
            # indices need reconstruction before checking their value range.
            if color!=3: continue
            for i in range(stride):
                a=row[i-bpp] if i>=bpp else 0;b=prior[i];c=prior[i-bpp] if i>=bpp else 0
                if method==1: predictor=a
                elif method==2: predictor=b
                elif method==3: predictor=(a+b)//2
                elif method==4:
                    p=a+b-c;distances=(abs(p-a),abs(p-b),abs(p-c));predictor=(a,b,c)[distances.index(min(distances))]
                else: predictor=0
                row[i]=(row[i]+predictor)&255
            if color==3 and any((row[(i*depth)//8]>>(8-depth-(i*depth)%8))&((1<<depth)-1)>=palette for i in range(w)):
                raise ValueError('Invalid emoji PNG palette index')
            prior=row

def validate_assets(assets):
    if not isinstance(assets,dict) or len(assets)>256: raise ValueError('Invalid emoji assets')
    output={}; points_total=0
    for name,row in assets.items():
        if not isinstance(name,str) or not re.fullmatch(r'\[[^\[\]\r\n]{1,16}\]',name): raise ValueError('Invalid emoji name')
        if not isinstance(row,dict) or set(row)!={'src','resolution','drawing'}: raise ValueError('Invalid emoji shape')
        src=row['src']; resolution=row['resolution']
        if not isinstance(src,str) or not src.startswith('data:image/png;base64,') or len(src)>1024*1024: raise ValueError('Invalid emoji PNG')
        try: png=base64.b64decode(src.split(',',1)[1],validate=True)
        except (ValueError,TypeError): raise ValueError('Invalid emoji base64') from None
        if (len(png)<33 or not png.startswith(b'\x89PNG\r\n\x1a\n')
                or png[8:16]!=b'\x00\x00\x00\x0dIHDR'
                or zlib.crc32(png[12:29])!=int.from_bytes(png[29:33],'big')):
            raise ValueError('Invalid emoji PNG header')
        width,height=struct.unpack('>II',png[16:24])
        if not 1<=width<=256 or not 1<=height<=256:
            raise ValueError('Emoji PNG dimensions exceed 256 pixels')
        validate_png(png,width,height)
        if type(resolution) is not int or not 1<=resolution<=256: raise ValueError('Invalid emoji resolution')
        if not isinstance(row['drawing'],list) or len(row['drawing'])>128: raise ValueError('Invalid emoji drawing')
        for group in row['drawing']:
            if not isinstance(group,dict) or set(group)!={'color','alpha','paths'}: raise ValueError('Invalid emoji group')
            if not isinstance(group['color'],list) or len(group['color'])!=3 or any(type(c) is not int or not 0<=c<=255 for c in group['color']): raise ValueError('Invalid emoji color')
            if type(group['alpha']) not in (int,float) or not math.isfinite(group['alpha']) or not 0<=group['alpha']<=1: raise ValueError('Invalid emoji alpha')
            if not isinstance(group['paths'],list) or not group['paths']: raise ValueError('Empty emoji paths')
            for path in group['paths']:
                if not isinstance(path,list) or len(path)<3: raise ValueError('Invalid emoji path')
                points_total+=len(path)
                if points_total>2000000: raise ValueError('Emoji paths too large')
                for point in path:
                    if not isinstance(point,list) or len(point)!=2 or any(type(n) not in (int,float) or not math.isfinite(n) or not 0<=n<=resolution for n in point): raise ValueError('Invalid emoji coordinate')
        output[name]=row
    return output

def catalog(assets):
    return {name:row['src'] for name,row in assets.items()}
