"""Cross-season admission uses local relationships plus the active episode list."""
from pathlib import Path
import sys,tempfile,threading,unittest
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from desktop_library import LibraryRelations
from desktop_season_playback import make_season_prewarm

SID='8800000000000002001';NEXT='8800000000000002002';OTHER='8800000000000002003';ALBUM='7619198149772446782'
class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.relations=LibraryRelations(self.root,None)
        with self.relations.connect() as db:
            db.executemany("INSERT INTO relations VALUES (?,?,?,?,?,?)",[
                (SID,ALBUM,1,'作品第一季','resolved',0),(NEXT,ALBUM,2,'作品：副标题第二季','resolved',0),(OTHER,ALBUM,3,'作品第三季','resolved',0)])
        self.prefetch=SimpleNamespace(condition=threading.Condition(),closed=False,generation=7,current={'seriesId':SID,'episode':3},latest_episodes=[(1,'12345678'),(2,'12345679'),(3,'12345680')])
        self.allow=make_season_prewarm(self.prefetch,self.relations)
        self.parent=SimpleNamespace(series_id=SID,episode=3,prefetch_generation=7)
    def test_reliable_local_relationship_and_last_episode_allow_first_next_season(self):
        self.assertTrue(self.allow(self.parent,NEXT,1));self.assertFalse(self.allow(self.parent,OTHER,1))
    def test_non_last_wrong_target_unknown_relation_and_old_generation_rejected(self):
        for field,value in [('episode',2),('prefetch_generation',6)]:
            original=getattr(self.parent,field);setattr(self.parent,field,value)
            self.assertFalse(self.allow(self.parent,NEXT,1));setattr(self.parent,field,original)
        for ep in (0,2,True):self.assertFalse(self.allow(self.parent,NEXT,ep))
        self.assertFalse(self.allow(self.parent,'8800000000000002099',1))
        self.prefetch.latest_episodes=[];self.assertFalse(self.allow(self.parent,NEXT,1))
    def test_closed_or_replaced_foreground_cannot_admit(self):
        self.prefetch.closed=True;self.assertFalse(self.allow(self.parent,NEXT,1))
        self.prefetch.closed=False;self.prefetch.current={'seriesId':OTHER,'episode':3}
        self.assertFalse(self.allow(self.parent,NEXT,1))
    def test_ambiguous_conflicting_unknown_or_failed_relationship_denies(self):
        with self.relations.connect() as db:db.execute("UPDATE relations SET season=2 WHERE series_id=?",(OTHER,))
        self.assertFalse(self.allow(self.parent,NEXT,1))
        with self.relations.connect() as db:
            db.execute("UPDATE relations SET season=3 WHERE series_id=?",(OTHER,))
            db.execute("UPDATE relations SET state='failed' WHERE series_id=?",(NEXT,))
        self.assertFalse(self.allow(self.parent,NEXT,1))
        with self.relations.connect() as db:db.execute("UPDATE relations SET state='resolved',album_id='7619198149772446799' WHERE series_id=?",(NEXT,))
        self.assertFalse(self.allow(self.parent,NEXT,1))

if __name__=='__main__':unittest.main()
