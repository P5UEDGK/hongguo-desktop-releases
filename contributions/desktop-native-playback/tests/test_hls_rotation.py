"""Real MP4 display transform and incremental budget regressions."""
from pathlib import Path
from fractions import Fraction
import tempfile, unittest
from unittest.mock import patch
import av
from desktop_hls import encode_hls
class RotationTests(unittest.TestCase):
    def test_h264_preserves_display_matrix_and_sample_aspect_ratio(self):
        for degrees,flip in ((90,False),(-90,True),(180,False)):
            with self.subTest(degrees=degrees,flip=flip),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'source.mp4'
                with av.open(str(source),'w') as output:
                    stream=output.add_stream('libx264',rate=10);stream.width=64;stream.height=32;stream.pix_fmt='yuv420p';stream.codec_context.sample_aspect_ratio=Fraction(2);stream.set_display_rotation(degrees,hflip=flip)
                    for n in range(40):
                        frame=av.VideoFrame(64,32,'rgb24');frame.pts=n
                        for packet in stream.encode(frame):output.mux(packet)
                    for packet in stream.encode():output.mux(packet)
                with av.open(str(source)) as reader:
                    expected=bytes(next(reader.decode(video=0)).side_data.get('DISPLAYMATRIX'))
                encode_hls(source,root/'hls')
                with av.open(str(root/'hls/index.m3u8'),options={'allowed_extensions':'ALL'}) as reader:
                    frame=next(reader.decode(video=0));actual=frame.side_data.get('DISPLAYMATRIX')
                    self.assertIsNotNone(actual);self.assertEqual(bytes(actual),expected);self.assertEqual(reader.streams.video[0].sample_aspect_ratio,Fraction(2))
    def test_output_directory_is_scanned_only_once_after_encoding(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.mp4'
            with av.open(str(source),'w') as output:
                stream=output.add_stream('libx264',rate=30);stream.width=64;stream.height=32;stream.pix_fmt='yuv420p'
                for n in range(180):
                    frame=av.VideoFrame(64,32,'rgb24');frame.pts=n
                    for packet in stream.encode(frame):output.mux(packet)
                for packet in stream.encode():output.mux(packet)
            scans=[];original=Path.iterdir
            def counted(path):
                if path==root/'hls':scans.append(True)
                return original(path)
            with patch.object(Path,'iterdir',counted):encode_hls(source,root/'hls')
            self.assertEqual(len(scans),1,'output byte guard must not rescan accumulated segments per packet batch')
