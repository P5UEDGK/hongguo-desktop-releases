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
    def test_palette_preserves_opaque_foreground_over_translucent_noise(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'weighted.png';image=Image.new('RGBA',(48,48))
            image.putdata([(230,20,20,255)]*64+[(int((i%24)*255/24),20,20,36) for i in range(2304-64)])
            image.save(path);row=compiler.compile_assets({'[测试]':path})['[测试]']
            self.assertEqual({tuple(group['color']) for group in row['drawing'] if group['alpha']==1},{(230,20,20)})
            with Image.open(io.BytesIO(base64.b64decode(row['src'].split(',',1)[1]))) as png:self.assertEqual(png.convert('RGBA').tobytes(),image.tobytes())

    def test_surrogate_mapping_rejected_before_opening_images(self):
        import json
        for point in (0xD800,0xDBFF,0xDC00,0xDFFF):
            tag=json.loads('"[\\u%04x]"'%point)
            with self.subTest(point=point),patch('PIL.Image.open') as opened:
                with self.assertRaisesRegex(ValueError,'name'):
                    compiler.compile_assets({tag:'never-open.png'})
                opened.assert_not_called()
        compiler.validate_mapping({'[😀]':'valid.png'})

    def test_generated_png_strips_non_orientation_exif(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            for format in ('PNG','JPEG'):
                path=Path(directory)/('exif.'+format.lower());image=Image.new('RGB',(8,4),'blue')
                exif=image.getexif();exif[274]=6;exif[315]='owned author';exif[270]='private fixture metadata'
                image.save(path,format=format,exif=exif)
                row=compiler.compile_assets({'[测试]':path})['[测试]'];raw=base64.b64decode(row['src'].split(',',1)[1])
                self.assertNotIn(b'eXIf',raw)
                with Image.open(io.BytesIO(raw)) as result:self.assertEqual(result.size,(4,8));self.assertEqual(len(result.getexif()),0)
                validate_assets({'[测试]':row})


    def test_invalid_tag_rejected_before_any_image_open(self):
        with patch('PIL.Image.open') as opened:
            for tag in ('bad','[line\nfeed]','['+'x'*17+']',7):
                with self.assertRaisesRegex(ValueError,'name'):compiler.compile_assets({tag:'unused.png'})
            opened.assert_not_called()

    def test_exif_orientation_normalizes_png_and_native_vectors(self):
        from PIL import Image, ImageOps
        with tempfile.TemporaryDirectory() as directory:
            for orientation in (2,6):
                path=Path(directory)/f'oriented-{orientation}.png'
                image=Image.new('RGB',(8,4),'red')
                for x in range(4):
                    for y in range(4):image.putpixel((x,y),(0,0,255))
                exif=image.getexif();exif[274]=orientation;image.save(path,exif=exif)
                with Image.open(path) as source:expected=ImageOps.exif_transpose(source).convert('RGBA')
                row=compiler.compile_assets({'[测试]':path})['[测试]']
                with Image.open(io.BytesIO(base64.b64decode(row['src'].split(',',1)[1]))) as output:
                    self.assertEqual(output.size,expected.size);self.assertEqual(output.convert('RGBA').tobytes(),expected.tobytes());self.assertIsNone(output.getexif().get(274))
                points=[point for group in row['drawing'] if group['color'][2]>group['color'][0] for contour in group['paths'] for point in contour];xs,ys=zip(*points)
                self.assertEqual((min(xs),max(xs),min(ys),max(ys)),(24,48,12,36) if orientation==2 else (12,36,0,24))

    def test_generated_png_strips_embedded_icc_profile(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            for format in ('PNG','JPEG'):
                path=Path(directory)/('profile.'+format.lower())
                Image.new('RGB',(4,4),'red').save(path,format=format,icc_profile=b'owned readable profile metadata')
                row=compiler.compile_assets({'[测试]':path})['[测试]']
                raw=base64.b64decode(row['src'].split(',',1)[1]);self.assertNotIn(b'iCCP',raw)
                validate_assets({'[测试]':row})

    def test_mapping_cardinality_and_type_rejected_before_image_open(self):
        with patch('PIL.Image.open') as opened:
            for mapping in ([],{'[x'+str(n)+']':'unused.png' for n in range(257)}):
                with self.assertRaisesRegex(ValueError,'mapping'):compiler.compile_assets(mapping)
            opened.assert_not_called()

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
