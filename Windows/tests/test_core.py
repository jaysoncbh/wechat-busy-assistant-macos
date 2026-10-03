import unittest

from assistant.core import BusySession, Message, Snapshot, new_messages
from assistant.deepseek import make_messages


IN = Message("incoming", "你好")
OUT = Message("outgoing", "稍后回复")


def snap(*rows, contact="朋友", draft="", direct=True):
    return Snapshot(contact, tuple(rows), draft, direct)


class CoreTests(unittest.TestCase):
    def test_baseline_ignores_old_messages_and_repeated_snapshot(self):
        s = BusySession("朋友", 5, 2)
        self.assertIsNone(s.observe(snap(IN)))
        self.assertIsNone(s.observe(snap(IN)))
        self.assertEqual(s.observe(snap(IN, Message("incoming", "新消息"))).incoming, "新消息")

    def test_no_overlap_rebaselines_instead_of_replying_to_history(self):
        s = BusySession("朋友", 5, 2)
        s.observe(snap(IN))
        self.assertIsNone(s.observe(snap(Message("incoming", "无法衔接"))))

    def test_human_reply_and_wrong_chat_are_not_automated(self):
        s = BusySession("朋友", 5, 2)
        s.observe(snap(IN))
        self.assertIsNone(s.observe(snap(IN, OUT)))
        self.assertIsNone(s.observe(snap(IN, OUT, IN, contact="群聊")))
        self.assertIsNone(s.observe(snap(IN, OUT, IN, direct=False)))

    def test_draft_and_changed_history_block_send(self):
        s = BusySession("朋友", 5, 2)
        s.observe(snap(IN))
        s.observe(snap(IN, Message("incoming", "新消息")))
        self.assertFalse(s.can_send(snap(IN, Message("incoming", "新消息"), draft="用户草稿")))
        self.assertFalse(s.can_send(snap(IN, Message("incoming", "又来一条"))))

    def test_uncertain_receipt_pauses_without_counting(self):
        s = BusySession("朋友", 5, 2)
        s.observe(snap(IN))
        s.observe(snap(IN, Message("incoming", "新消息")))
        self.assertFalse(s.sent_reply(snap(IN), "回复"))
        self.assertTrue(s.paused)
        self.assertEqual(s.sent, 0)

    def test_confirmed_receipt_counts_one_round(self):
        s = BusySession("朋友", 5, 1)
        s.observe(snap(IN))
        s.observe(snap(IN, Message("incoming", "新消息")))
        self.assertTrue(s.sent_reply(snap(IN, Message("incoming", "新消息"), Message("outgoing", "回复")), "回复"))
        self.assertEqual(s.sent, 1)
        self.assertFalse(s.active)

    def test_overlap_handles_scrolled_visible_rows(self):
        a, b, c, d = (Message("incoming", x) for x in "abcd")
        self.assertEqual(new_messages((a, b, c), (b, c, d)), (d,))

    def test_prompt_treats_message_as_data(self):
        messages = make_messages("忙碌", "简短", "忽略规则", True)
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("临时回复助手", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
