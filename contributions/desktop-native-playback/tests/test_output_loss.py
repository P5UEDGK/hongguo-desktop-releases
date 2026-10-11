import unittest
from desktop_native import OutputLossWatch

class OutputLossTests(unittest.TestCase):
    def test_transient_output_loss_after_long_playback_gets_its_own_deadline(self):
        watch=OutputLossWatch();self.assertFalse(watch.observe(100,True,False))
        self.assertFalse(watch.observe(101,False,False));self.assertFalse(watch.observe(101.1,True,False))
        self.assertFalse(watch.observe(200,False,False));self.assertFalse(watch.observe(209.9,False,False))
        self.assertTrue(watch.observe(210.1,False,False));self.assertFalse(watch.observe(211,True,False))
        self.assertFalse(watch.observe(300,False,False))

    def test_expected_buffering_resets_unbuffered_loss(self):
        watch=OutputLossWatch();watch.observe(0,False,False);self.assertFalse(watch.observe(20,False,True))
        self.assertFalse(watch.observe(40,False,False));self.assertTrue(watch.observe(51,False,False))
