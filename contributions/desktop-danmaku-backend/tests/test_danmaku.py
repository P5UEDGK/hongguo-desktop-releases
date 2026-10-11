import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from desktop_danmaku import *
from desktop_danmaku_track import DanmakuTrack

ITEM={'text':'safe{\\pos(0,0)}[unknown]👍','offset_ms':1000,'lane':0}
class Player:
    def __init__(self): self.commands=[]; self.sid=0; self.fail=False; self.properties={'sid':'no','secondary-sid':'no','secondary-sub-ass-override':'strip','sub-ass-override':'scale','sub-delay':'0','secondary-sub-delay':'0','sub-visibility':'yes','secondary-sub-visibility':'yes'};self.fail_remove=False
    def command(self,*args):
        if self.fail: raise RuntimeError('test failure')
        if self.fail_remove and args[0]=='sub-remove':raise RuntimeError('remove failure')
        self.commands.append(args)
        if args[0]=='sub-add': self.sid+=1;self.properties['sid']=str(self.sid)
        if args[0]=='set':
            # Real mpv refuses a single subtitle in both slots.
            if args[1]=='secondary-sid' and str(args[2])==self.properties['sid']:return
            self.properties[args[1]]=str(args[2])
    def get(self,key): return self.properties.get(key)
class DanmakuTests(unittest.TestCase):
    def test_disabled_primary_caption_remains_hidden_after_overlay_and_restore(self):
        p=Player();p.properties.update({'sid':'7','sub-visibility':'no','secondary-sub-visibility':'yes'})
        original=dict(p.properties);track=DanmakuTrack();track.update({'danmaku':[ITEM]});track.apply(p)
        self.assertEqual(p.get('sub-visibility'),'yes');self.assertEqual(p.get('secondary-sub-visibility'),'no')
        track.update({'danmaku':[]});track.apply(p);self.assertEqual(p.properties,original)

    def test_disabling_clears_live_track_despite_stale_removal_failure(self):
        p=Player();p.properties['sid']='7';clock=[0];track=DanmakuTrack(clock=lambda:clock[0])
        track.update({'danmaku':[ITEM]});track.apply(p)
        command=p.command
        def failed_old(*args):
            if args==('sub-remove','1'):raise RuntimeError('old unselected track removal failed')
            command(*args)
        p.command=failed_old
        track.update({'danmaku':[{**ITEM,'text':'replacement'}]});track.apply(p)
        self.assertEqual(track.track_id,'2');self.assertEqual(track.pending_removals,{'1'})
        track.update({'danmaku':[]});track.apply(p)
        self.assertIsNone(track.track_id);self.assertEqual(p.get('sid'),'7')
        self.assertIn(('sub-remove','2'),p.commands);self.assertEqual(track.pending_removals,{'1'})

    def test_retimed_negative_origin_matches_dom_phase_and_clips_ass_start(self):
        item={**ITEM,'offset_ms':0,'text':'甲乙','motion_start_ms':-5000}
        settings={**DEFAULT_SETTINGS,'duration':24}
        doc=ass_document([item],settings)
        self.assertIn('0:00:00.00,0:00:19.00',doc)
        self.assertIn(r'\move(779.167,25,-60,25,0,19000)',doc)
        self.assertEqual(len(active_danmaku([item],7,settings)),1)
        self.assertEqual(active_danmaku([item],19,settings),[])
        for bad in (True,-24001,86400001,1.5):
            with self.assertRaises(ValueError):validate_danmaku([{**item,'motion_start_ms':bad}])

    def test_caption_enabled_during_clean_overlay_is_promoted_and_overlay_reselected(self):
        p=Player();track=DanmakuTrack();track.update({'danmaku':[ITEM]});track.apply(p);owned=track.track_id
        p.command('set','sid','7');track.apply(p)
        self.assertEqual(p.get('sid'),owned);self.assertEqual(p.get('secondary-sid'),'7')
        self.assertFalse(track.failed);self.assertEqual(track.loads,1)
        track.update({'danmaku':[]});track.apply(p)
        self.assertEqual(p.get('sid'),'7');self.assertEqual(p.get('secondary-sid'),'no')

    def test_no_caption_overlay_neutralizes_and_restores_ass_override_and_delay(self):
        p=Player();p.properties.update({'sub-ass-override':'strip','sub-delay':'1.25','secondary-sub-delay':'-2'})
        original=dict(p.properties);track=DanmakuTrack();track.update({'danmaku':[ITEM]});track.apply(p)
        self.assertEqual(p.get('sub-ass-override'),'no');self.assertEqual(p.get('sub-delay'),'0')
        track.update({'danmaku':[]});track.apply(p)
        self.assertEqual(p.properties,original)

    def test_caption_delays_follow_slot_swap_and_restore(self):
        p=Player();p.properties.update(sid='7',**{'sub-delay':'2.5','secondary-sub-delay':'-1','sub-ass-override':'force'})
        original=dict(p.properties);track=DanmakuTrack();track.update({'danmaku':[ITEM]});track.apply(p)
        self.assertEqual(p.get('sub-delay'),'0');self.assertEqual(p.get('secondary-sub-delay'),'2.5')
        self.assertEqual(p.get('sub-ass-override'),'no');self.assertEqual(p.get('secondary-sub-ass-override'),'force')
        track.update({'danmaku':[]});track.apply(p)
        self.assertEqual(p.properties,original)

    def test_source_reload_does_not_recapture_temporary_option_values(self):
        p=Player();p.properties.update(sid='7',**{'sub-delay':'2','secondary-sub-delay':'-1'})
        track=DanmakuTrack();track.update({'danmaku':[ITEM]});track.apply(p)
        p.properties.update(sid='8',**{'secondary-sid':'no'}) # tracks reset, options persist
        track.source_reloaded();track.apply(p)
        self.assertEqual(p.get('secondary-sid'),'8');self.assertEqual(p.get('secondary-sub-delay'),'2')
        track.update({'danmaku':[]});track.apply(p)
        self.assertEqual(p.get('sid'),'8');self.assertEqual(p.get('sub-ass-override'),'scale')
        self.assertEqual(p.get('secondary-sub-ass-override'),'strip')
        self.assertEqual(p.get('sub-delay'),'2');self.assertEqual(p.get('secondary-sub-delay'),'-1')

    def test_cancel_failed_add_discards_old_caption_before_retry(self):
        clock=[0];p=Player();p.properties['sid']='7';p.fail=True
        track=DanmakuTrack(clock=lambda:clock[0]);track.update({'danmaku':[ITEM]});track.apply(p)
        self.assertTrue(track.failed)
        track.update({'danmaku':[]});track.apply(p)
        p.fail=False;p.properties['sid']='9';clock[0]=1
        track.update({'danmaku':[ITEM]});track.apply(p)
        self.assertFalse(track.failed);self.assertEqual(p.get('secondary-sid'),'9')

    def test_filtered_schedule_does_not_select_an_empty_ass_track(self):
        p=Player();p.properties['sid']='7';track=DanmakuTrack()
        track.update({'danmaku':[{**ITEM,'lane':5}], 'danmakuSettings':{**DEFAULT_SETTINGS,'lanes':1}})
        track.apply(p)
        self.assertEqual(track.loads,0);self.assertEqual(p.commands,[]);self.assertEqual(p.get('sid'),'7')
        track.update({'danmaku':[ITEM]});track.apply(p)
        self.assertEqual(track.loads,1)
        track.update({'danmaku':[{**ITEM,'lane':5}]});track.apply(p)
        self.assertIsNone(track.track_id);self.assertEqual(p.get('sid'),'7')

    def test_bounds(self):
        self.assertEqual(validate_settings(DEFAULT_SETTINGS),DEFAULT_SETTINGS)
        for bad in ({**DEFAULT_SETTINGS,'duration':True},{**DEFAULT_SETTINGS,'opacity':0},{'duration':14}):
            with self.assertRaises(ValueError): validate_settings(bad)
        for bad in ([ITEM]*301,[{**ITEM,'lane':6}],[{**ITEM,'offset_ms':True}],[{**ITEM,'text':'a'*201}]):
            with self.assertRaises(ValueError): validate_danmaku(bad)
    def test_timing_and_ass_injection(self):
        text=ass_document([ITEM])
        self.assertIn('0:00:01.00,0:00:15.00',text)
        self.assertIn('｛＼pos(0,0)｝',text); self.assertNotIn(r'\pos(0,0)',text)
        self.assertIn('[unknown]',text); self.assertIn('👍',text)
        self.assertEqual(len(active_danmaku([ITEM],1,DEFAULT_SETTINGS)),1)
        self.assertEqual(active_danmaku([ITEM],15,DEFAULT_SETTINGS),[])
        self.assertEqual(active_danmaku([ITEM],float('nan'),DEFAULT_SETTINGS),[])
    def test_long_cjk_text_moves_its_entire_width_offscreen(self):
        doc=ass_document([{**ITEM,'text':'字'*200}],{**DEFAULT_SETTINGS,'fontSize':36})
        self.assertIn(r'\move(1000,25,-7200,25,0,14000)',doc)
    def test_speed_opacity_and_lane_settings(self):
        for duration in (4,14,24):
            doc=ass_document([ITEM],{**DEFAULT_SETTINGS,'duration':duration,'opacity':50,'fontSize':36})
            self.assertIn(f',0,{duration*1000})',doc); self.assertIn('YaHei,36,&H80FFFFFF',doc)
        self.assertNotIn('Dialogue:',ass_document([{**ITEM,'lane':5}],{**DEFAULT_SETTINGS,'lanes':1}))
    def test_ordinary_poll_does_not_reload(self):
        p=Player(); track=DanmakuTrack(); track.update({'danmaku':[ITEM]}); track.apply(p)
        for _ in range(100): track.apply(p); track.update({'danmaku':[ITEM]})
        self.assertEqual(len([c for c in p.commands if c[0]=='sub-add']),1); self.assertEqual(track.loads,1)
        stable=len(p.commands);track.apply(p);self.assertEqual(len(p.commands),stable)
    def test_replace_adds_before_removing_owned_track(self):
        p=Player(); track=DanmakuTrack(); track.update({'danmaku':[ITEM]}); track.apply(p)
        track.update({'danmaku':[ITEM,{**ITEM,'offset_ms':3000}]}); track.apply(p)
        self.assertEqual([c[0] for c in p.commands if c[0] in ('sub-add','sub-remove')],['sub-add','sub-add','sub-remove'])
        self.assertEqual(p.commands[-1],('sub-remove','1'))
    def test_pause_seek_rate_use_absolute_media_timestamps(self):
        track=DanmakuTrack(); p=Player(); track.update({'danmaku':[ITEM]}); track.apply(p)
        for seconds in (2,2,8,3): self.assertTrue(track.snapshot(seconds)['danmakuVisible'])
        self.assertFalse(track.snapshot(16)['danmakuVisible']); self.assertEqual(track.loads,1)
    def test_reload_and_clear(self):
        track=DanmakuTrack(); p=Player(); track.update({'danmaku':[ITEM]}); track.apply(p)
        track.source_reloaded(); track.apply(p); self.assertEqual(track.loads,2)
        track.update({'danmaku':[]}); track.apply(p); self.assertFalse(track.snapshot(2)['danmakuVisible'])
        self.assertEqual(p.commands[-1],('sub-remove','2'))
    def test_failure_isolated_and_atomic_validation(self):
        track=DanmakuTrack(); p=Player(); p.fail=True
        track.update({'danmaku':[ITEM]}); track.apply(p); self.assertTrue(track.failed)
        with self.assertRaises(ValueError): track.update({'danmaku':[],'danmakuSettings':{}})
        self.assertEqual(track.items,[ITEM])
        p.fail=False; track.source_reloaded(); track.apply(p); self.assertFalse(track.failed)
    def test_existing_captions_preserved_and_restored(self):
        p=Player();p.sid=10;p.properties.update(sid='7',**{'sub-ass-override':'no'})
        track=DanmakuTrack();track.update({'danmaku':[ITEM]});track.apply(p)
        self.assertEqual(p.get('secondary-sid'),'7');self.assertEqual(p.get('secondary-sub-ass-override'),'no')
        self.assertEqual(p.get('sid'),'11')
        track.update({'danmaku':[]});track.apply(p)
        self.assertEqual(p.get('sid'),'7');self.assertEqual(p.get('secondary-sid'),'no')
        self.assertEqual(p.get('secondary-sub-ass-override'),'strip')
    def test_two_existing_subtitles_left_intact(self):
        p=Player();p.properties.update(sid='7',**{'secondary-sid':'8'})
        track=DanmakuTrack();track.update({'danmaku':[ITEM]});track.apply(p)
        self.assertTrue(track.failed);self.assertEqual(p.commands,[])
    def test_failed_clear_keeps_ownership_and_retries(self):
        clock=[0];track=DanmakuTrack(clock=lambda:clock[0]);p=Player()
        track.update({'danmaku':[ITEM]});track.apply(p);owned=track.track_id
        p.fail_remove=True;track.update({'danmaku':[]});track.apply(p)
        self.assertEqual(track.track_id,owned);self.assertTrue(track.dirty)
        p.fail_remove=False;clock[0]=1;track.apply(p)
        self.assertIsNone(track.track_id);self.assertFalse(track.failed)
    def test_failed_replacement_cleanup_retains_old_id(self):
        clock=[0];track=DanmakuTrack(clock=lambda:clock[0]);p=Player()
        track.update({'danmaku':[ITEM]});track.apply(p)
        p.fail_remove=True;track.update({'danmaku':[ITEM,{**ITEM,'offset_ms':5000}]});track.apply(p)
        self.assertEqual(track.track_id,'2');self.assertEqual(track.pending_removals,{'1'})
        p.fail_remove=False;clock[0]=1;track.apply(p)
        self.assertEqual(track.pending_removals,set());self.assertEqual(track.loads,2)
if __name__=='__main__': unittest.main()
