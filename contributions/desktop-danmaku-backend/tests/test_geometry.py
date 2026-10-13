import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from desktop_danmaku import ass_document, danmaku_resolution
from desktop_danmaku_track import DanmakuTrack
from test_danmaku import Player, ITEM

class GeometryTests(unittest.TestCase):
    def test_square_units_for_portrait_landscape_and_extremes(self):
        for aspect in (16/9,9/16,1,4/3,3/4):
            width,height=danmaku_resolution(aspect)
            self.assertEqual(min(width,height),562)
            self.assertAlmostEqual(width/height,aspect,delta=.002)
        for bad in (None,0,-1,float('inf'),float('nan')):
            self.assertEqual(danmaku_resolution(bad),(1000,562))
        self.assertEqual(max(danmaku_resolution(1e9)),5620)

    def test_text_vector_and_motion_share_canvas(self):
        # Hand-authored colored square, independent of product emoji assets.
        assets={'[square]':{'resolution':48,'drawing':[{'color':[255,160,0],
            'alpha':1,'paths':[[[0,0],[48,0],[48,48],[0,48]]]}]}}
        row={'text':'口口[square]','offset_ms':1000,'lane':1}
        for aspect in (16/9,9/16):
            width,height=danmaku_resolution(aspect)
            doc=ass_document([row],assets=assets,resolution=(width,height))
            self.assertIn(f'PlayResX: {width}\nPlayResY: {height}',doc)
            self.assertIn(f'LayoutResX: {width}\nLayoutResY: {height}',doc)
            self.assertIn(f'\\move({width},68,',doc)
            self.assertIn(f'\\clip(0,0,{width},{height})',doc)
            self.assertIn(r'\p1}',doc)
            self.assertNotIn('[square]',doc)
            self.assertIn('0:00:01.00,0:00:15.00',doc)

    def test_first_metadata_rotation_and_ordinary_polls(self):
        player=Player();track=DanmakuTrack();track.update({'danmaku':[ITEM]})
        track.apply(player);self.assertEqual(track.loads,1)
        player.properties['video-out-params/aspect']='0.5625'
        track.apply(player);self.assertEqual(track.loads,2)
        self.assertEqual(track.resolution,(562,999))
        for _ in range(100):track.apply(player)
        self.assertEqual(track.loads,2)
        player.properties.update({'video-out-params/aspect':'1.77777778','video-params/rotate':'90'})
        track.apply(player);self.assertEqual(track.loads,2,'Same display geometry keeps the track')
        player.properties['video-params/rotate']='0'
        track.apply(player);self.assertEqual(track.loads,3)
        track.source_reloaded();track.apply(player);self.assertEqual(track.loads,4)

    def test_geometry_changes_preserve_caption_owner(self):
        player=Player();player.properties['sid']='27'
        track=DanmakuTrack();track.update({'danmaku':[ITEM]});track.apply(player)
        player.properties['video-out-params/aspect']='0.5625';track.apply(player)
        self.assertEqual(player.get('secondary-sid'),'27')
        track.update({'danmaku':[]});track.apply(player)
        self.assertEqual(player.get('sid'),'27')
        self.assertEqual(player.get('secondary-sid'),'no')

if __name__=='__main__':unittest.main()
