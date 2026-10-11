import os,tempfile,unittest
from contextlib import closing
from pathlib import Path
from desktop_hls_budget import OutputBudget,EncodingBudgetExceeded

class OutputBudgetTests(unittest.TestCase):
    def test_repeated_event_playlist_replacement_counts_live_extent(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);budget=OutputBudget(root,1000)
            with closing(budget.open(str(root/'init.mp4'),2,{})) as output:output.write(b'i'*400)
            for i in range(40):
                with closing(budget.open(str(root/'index.m3u8.tmp'),2,{})) as output:output.write(b'p'*(100+i))
                os.replace(root/'index.m3u8.tmp',root/'index.m3u8')
            self.assertGreater(budget.remaining,300)
            with closing(budget.open(str(root/'seg000000.m4s'),2,{})) as output:
                with self.assertRaises(EncodingBudgetExceeded):output.write(b's'*600)
            self.assertEqual((root/'seg000000.m4s').stat().st_size,0)

    def test_seek_overwrite_and_sparse_growth_are_accounted_before_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);budget=OutputBudget(root,100)
            with closing(budget.open(str(root/'init.mp4'),2,{})) as output:
                output.write(b'a'*30);remaining=budget.remaining
                output.seek(0);output.write(b'b'*30);self.assertEqual(budget.remaining,remaining)
                output.seek(100)
                with self.assertRaises(EncodingBudgetExceeded):output.write(b'x')
            self.assertEqual((root/'init.mp4').stat().st_size,30)
