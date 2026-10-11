import unittest
from desktop_native import OutputLossWatch

class OutputLossTests(unittest.TestCase):
    def test_transient_output_loss_after_long_playback_gets_its_own_deadline(self):
        watch=OutputLossWatch();self.assertFalse(watch.observe(100,True,False))
        self.assertFalse(watch.observe(101,False,False));self.assertFalse(watch.observe(101.1,True,False))
        self.assertFalse(watch.observe(200,False,False));self.assertFalse(watch.observe(209.9,False,False))
        self.assertTrue(watch.observe(210.1,False,False));self.assertFalse(watch.observe(211,True,False))
        self.assertFalse(watch.observe(300,False,False))

    def test_healthy_read_ahead_cannot_mask_post_ready_output_loss(self):
        watch=OutputLossWatch();self.assertTrue(watch.buffering(False,True,False))
        watch.observe(0,True,False)
        for now in (1,5,11.1):
            buffering=watch.buffering(False,True,False);self.assertFalse(buffering)
            expired=watch.observe(now,False,buffering)
        self.assertTrue(expired)
        self.assertTrue(watch.buffering(True,True,False),'real cache pause remains buffering')

    def test_expected_buffering_resets_unbuffered_loss(self):
        watch=OutputLossWatch();watch.observe(0,False,False);self.assertFalse(watch.observe(20,False,True))
        self.assertFalse(watch.observe(40,False,False));self.assertTrue(watch.observe(51,False,False))
