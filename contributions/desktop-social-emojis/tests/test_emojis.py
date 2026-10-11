import copy
import base64,struct,zlib
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from desktop_emoji_assets import validate_assets,catalog
FIXTURE={'[测试]':{'src':'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgQIAK32fWQAAAABJRU5ErkJggg==','resolution':1,'drawing':[{'color':[255,0,0],'alpha':1,'paths':[[[0,0],[1,0],[1,1],[0,1]]]}]}}
class EmojiTests(unittest.TestCase):
    def test_catalog_checks_ihdr_before_accepting_decoded_dimensions(self):
        for width,height in ((0,1),(1,0),(257,1),(1,257),(16384,16384)):
            header=b'IHDR'+struct.pack('>IIBBBBB',width,height,8,0,0,0,0)
            png=b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+header+struct.pack('>I',zlib.crc32(header))
            row=copy.deepcopy(FIXTURE);row['[测试]']['src']='data:image/png;base64,'+base64.b64encode(png).decode()
            with self.subTest(width=width,height=height),self.assertRaisesRegex(ValueError,'dimensions'):
                validate_assets(row)
        for raw in (b'\x89PNG\r\n\x1a\n',base64.b64decode(FIXTURE['[测试]']['src'].split(',')[1])[:29]+b'bad!'):
            row=copy.deepcopy(FIXTURE);row['[测试]']['src']='data:image/png;base64,'+base64.b64encode(raw).decode()
            with self.assertRaisesRegex(ValueError,'header'):validate_assets(row)
    def test_catalog(self): self.assertEqual(catalog(validate_assets(FIXTURE))['[测试]'],FIXTURE['[测试]']['src'])
    def test_bad_url(self):
        row=copy.deepcopy(FIXTURE); row['[测试]']['src']='https://example.invalid/tracker'
        with self.assertRaises(ValueError): validate_assets(row)
    def test_ass_coordinate_injection(self):
        for value in ('0}\\pos(0,0)',True,float('nan'),-1,2):
            row=copy.deepcopy(FIXTURE); row['[测试]']['drawing'][0]['paths'][0][0][0]=value
            with self.assertRaises(ValueError): validate_assets(row)
    def test_unknown_label(self):
        with self.assertRaises(ValueError): validate_assets({'not-a-tag':FIXTURE['[测试]']})
if __name__=='__main__': unittest.main()
