import importlib.util
import sys
import tempfile
import unittest
import base64
import io
from unittest.mock import patch, MagicMock
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from desktop_emoji_assets import validate_assets
spec=importlib.util.spec_from_file_location('compile_assets',ROOT/'tools/compile_assets.py')
compiler=importlib.util.module_from_spec(spec);spec.loader.exec_module(compiler)

class CompileTests(unittest.TestCase):
    def test_mapping_read_is_bounded_before_decode(self):
        stream=MagicMock();stream.__enter__.return_value=stream;stream.read.return_value=b' '*(1024*1024+1);path=MagicMock();path.open.return_value=stream
        with patch.object(compiler.json,'loads') as decode:
            with self.assertRaisesRegex(ValueError,'mapping exceeds'):compiler.load_mapping(path)
            stream.read.assert_called_once_with(1024*1024+1);decode.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'mapping.json';source.write_text('{"[测试]":"owned.png"}',encoding='utf8')
            self.assertEqual(compiler.load_mapping(source),{'[测试]':'owned.png'})

    def test_transparent_rgb_does_not_consume_visible_palette(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'hidden-rgb.png';image=Image.new('RGBA',(48,48))
            visible=[(250,20,20),(20,250,20),(20,20,250),(250,250,20)]
            for y in range(48):
                for x in range(48):image.putpixel((x,y),((x*43)%256,(y*47)%256,((x+y)*31)%256,0))
            for x,color in enumerate(visible):image.putpixel((20+x,20),(*color,255))
            image.save(path);row=compiler.compile_assets({'[测试]':path})['[测试]']
            colors={tuple(group['color']) for group in row['drawing']}
            self.assertTrue(set(visible)<=colors,(visible,colors))

    def test_small_non_square_vector_is_upscaled_to_native_canvas(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'small.png';Image.new('RGBA',(4,2),'red').save(path)
            row=compiler.compile_assets({'[测试]':path})['[测试]']
            points=[point for group in row['drawing'] for contour in group['paths'] for point in contour]
            xs,ys=zip(*points)
            self.assertEqual((min(xs),max(xs),min(ys),max(ys)),(0,48,12,36))
    def test_non_square_native_vectors_keep_the_png_aspect_ratio(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'wide.png';Image.new('RGBA',(96,48),'red').save(path)
            row=compiler.compile_assets({'[测试]':path})['[测试]']
            points=[point for group in row['drawing'] for contour in group['paths'] for point in contour]
            xs,ys=zip(*points)
            self.assertEqual((min(xs),max(xs),min(ys),max(ys)),(0,48,12,36))
            raw=base64.b64decode(row['src'].split(',',1)[1])
            with Image.open(io.BytesIO(raw)) as image:self.assertEqual(image.size,(96,48))

    def test_excessive_dimensions_rejected_before_pixel_conversion(self):
        source=MagicMock();source.size=(8000,8000)
        source.__enter__.return_value=source
        with patch('PIL.Image.open',return_value=source):
            with self.assertRaisesRegex(ValueError,'dimensions'):
                compiler.compile_assets({'[测试]':'oversized.png'})
        source.convert.assert_not_called()
    def test_authored_image_compiles_to_png_and_vectors(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.png'
            image=Image.new('RGBA',(4,4),(255,0,0,255));image.putpixel((0,0),(0,0,0,0));image.save(path)
            assets=validate_assets(compiler.compile_assets({'[测试]':path}))
            row=assets['[测试]']
            self.assertEqual(row['resolution'],48)
            self.assertTrue(row['drawing'])
            self.assertTrue(any(group['color']==[255,0,0] for group in row['drawing']))
    def test_large_host_image_is_bounded_before_encoding(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.png'
            Image.effect_noise((2048,2048),100).convert('RGBA').save(path)
            assets=compiler.compile_assets({'[测试]':path})
            self.assertLess(len(assets['[测试]']['src']),1024*1024)
            raw=base64.b64decode(assets['[测试]']['src'].split(',',1)[1])
            with Image.open(io.BytesIO(raw)) as image:self.assertLessEqual(max(image.size),256)
    def test_invalid_mapping_rejected_before_output(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.png';Image.new('RGBA',(2,2),'red').save(path)
            with self.assertRaises(ValueError):compiler.compile_assets({'bad':path})

if __name__=='__main__':unittest.main()
