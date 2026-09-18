import unittest
from caption_pool import parse_captions,plan_captions

class CaptionPoolTests(unittest.TestCase):
    def test_parse_blank_lines_duplicates_and_emoji(self):
        self.assertEqual(parse_captions('  好吃🍊\r\n爆汁\r\n \r\n第二组\n\n好吃🍊\n爆汁\n'),[['好吃🍊','爆汁'],['第二组']])
    def test_limit_and_shortage(self):
        with self.assertRaises(ValueError):parse_captions('一\n二\n三\n四')
        with self.assertRaises(ValueError):plan_captions(dict(batch_caption_enabled=True,batch_caption_text='一\n\n一'),2)
    def test_order_random_and_legacy(self):
        text='\n\n'.join(str(i) for i in range(100))
        cfg=dict(batch_caption_enabled=True,batch_caption_text=text)
        self.assertEqual(plan_captions(cfg,2),[['0'],['1']])
        cfg['batch_caption_shuffle']=True
        self.assertEqual(len({tuple(g) for g in plan_captions(cfg,100)}),100)
        self.assertEqual(plan_captions(dict(caption=['固定']),2),[['固定'],['固定']])
