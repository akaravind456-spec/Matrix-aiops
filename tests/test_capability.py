import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda'))
import matrix_capability as C


class CapabilityQuestion(unittest.TestCase):
    def test_asks_what_it_can_do(self):
        for t in ('what are the tools you have what all you can do', 'what are the features you have', 'What can you do?',
                  'what are the guardrails you have', 'how can you help me'):
            self.assertTrue(C.capability_question(t), t)

    def test_real_requests_go_to_the_model(self):
        for t in ('What is the disk status of matrix-linux-01? Read only.', 'Scan matrix-linux-01 for missing patches',
                  'what is the status of INC0010123', 'option 2', 'is it done', ''):
            self.assertFalse(C.capability_question(t), t)

    def test_reply_mentions_confirm_and_safety(self):
        self.assertIn('Confirm', C.CAPABILITY_REPLY)
        self.assertIn('matrix-managed=true', C.CAPABILITY_REPLY)


if __name__ == '__main__':
    unittest.main()
