import unittest
from unittest.mock import patch

from assistant.core import BusySession, Message, Snapshot
from assistant.wechat import WeChatError
from assistant.wechat_db import ClipboardNotPlainText, WeChatDatabase, resolve_contact, rows_to_messages


class FakeDB:
    wxid = "wxid_self"

    def __init__(self, rows):
        self.rows = rows

    def search_contact(self, _):
        return self.rows


def row(seq, sender, text, kind="文本"):
    return {"sort_seq": seq, "local_id": seq, "create_time": seq,
            "sender_id": sender, "sender_username": "wxid_self" if sender == 2 else "wxid_friend",
            "type": kind, "content": text}


class DatabaseAdapterTests(unittest.TestCase):
    def test_self_identity_does_not_depend_on_numeric_sender_id(self):
        outgoing = row(5, 1, "测试消息")
        outgoing["sender_username"] = "wxid_self"
        incoming = row(4, 16, "你好")
        self.assertEqual(rows_to_messages([outgoing, incoming], "wxid_self")[-1].sender, "outgoing")

    def test_unmapped_peer_sender_is_incoming_when_self_id_is_known(self):
        outgoing = row(3, 1, "我发的")
        outgoing["sender_username"] = "wxid_self"
        incoming = row(4, 521, "新消息")
        incoming["sender_username"] = ""
        messages = rows_to_messages([incoming, outgoing], "wxid_self")
        self.assertEqual(messages[-1].sender, "incoming")
        self.assertEqual(messages[0].sender, "outgoing")

    def test_unmapped_sender_without_known_self_id_stays_system(self):
        incoming = row(4, 521, "无法核对")
        incoming["sender_username"] = ""
        self.assertEqual(rows_to_messages([incoming], "wxid_self")[-1].sender, "system")

    def test_non_text_clipboard_failed_direct_input_does_not_press_enter(self):
        class FakeEdit:
            sent = False

            def SendKeys(self, *_args, **_kwargs):
                self.sent = True

        class FakeUIA:
            def _click_ctrl(self, _edit):
                return True

            def _set_text(self, _edit, _text):
                return False

        edit = FakeEdit()
        adapter = WeChatDatabase.__new__(WeChatDatabase)
        adapter.uia = FakeUIA()
        expected = Snapshot("朋友", (Message("incoming", "你好"),), "", True)
        adapter.ready_to_send = lambda: True
        adapter.snapshot = lambda: expected
        adapter._editor = lambda: (edit, "")
        with patch("assistant.wechat_db._read_clipboard_text", side_effect=ClipboardNotPlainText()):
            with self.assertRaises(WeChatError):
                adapter.send(expected, "测试")
        self.assertFalse(edit.sent)

    def test_filehelper_is_allowed_only_without_name_collision(self):
        db = FakeDB([])
        self.assertEqual(resolve_contact(db, "文件传输助手"), "filehelper")
        db.rows.append({"username": "wxid_other", "remark": "文件传输助手", "nick_name": "其他人"})
        with self.assertRaises(WeChatError):
            resolve_contact(db, "文件传输助手")

    def test_contact_must_resolve_to_one_person(self):
        db = FakeDB([
            {"username": "wxid_friend", "remark": "朋友", "nick_name": "原名"},
            {"username": "group@chatroom", "remark": "其他群", "nick_name": "其他群"},
        ])
        self.assertEqual(resolve_contact(db, "朋友"), "wxid_friend")
        db.rows.append({"username": "wxid_other", "remark": "朋友", "nick_name": "另一人"})
        with self.assertRaises(WeChatError):
            resolve_contact(db, "朋友")
        db.rows.pop()
        db.rows[1]["remark"] = "朋友"
        with self.assertRaises(WeChatError):
            resolve_contact(db, "朋友")

    def test_same_text_has_distinct_database_identity(self):
        older = rows_to_messages([row(1, 3, "你好")], "wxid_self")
        newer = rows_to_messages([row(2, 3, "你好"), row(1, 3, "你好")], "wxid_self")
        session = BusySession("朋友", 5, 2)
        session.observe(Snapshot("朋友", older, "", True))
        candidate = session.observe(Snapshot("朋友", newer, "", True))
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.incoming, "你好")

    def test_media_does_not_become_ai_prompt_and_sent_row_is_verified(self):
        older = rows_to_messages([row(1, 3, "旧消息")], "wxid_self")
        media = rows_to_messages([row(2, 3, "[图片]", "图片"), row(1, 3, "旧消息")], "wxid_self")
        text = rows_to_messages([row(3, 3, "新消息"), row(2, 3, "[图片]", "图片"), row(1, 3, "旧消息")], "wxid_self")
        sent = rows_to_messages([row(4, 2, "收到"), row(3, 3, "新消息"),
                                 row(2, 3, "[图片]", "图片"), row(1, 3, "旧消息")], "wxid_self")
        session = BusySession("朋友", 5, 2)
        session.observe(Snapshot("朋友", older, "", True))
        self.assertIsNone(session.observe(Snapshot("朋友", media, "", True)))
        self.assertEqual(session.observe(Snapshot("朋友", text, "", True)).incoming, "新消息")
        self.assertTrue(session.sent_reply(Snapshot("朋友", sent, "", True), "收到"))


if __name__ == "__main__":
    unittest.main()
