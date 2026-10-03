"""WeChat 4.x adapter: local DB reads, UIA send, DB receipt verification.

Only one exact, unique personal contact can be selected. The UIA driver is
used only for the currently open chat; it never searches or switches chats.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import win32clipboard
import win32con
import win32gui

from .core import Message, Snapshot, new_messages
from .wechat import WeChatError


STATE_DIR = Path(__file__).resolve().parent.parent / ".state" / "wechatdb"


class ClipboardNotPlainText(WeChatError):
    pass


def resolve_contact(db, display_name: str) -> str:
    """Resolve the visible name to exactly one non-group username."""
    same_name = {
        hit["username"] for hit in db.search_contact(display_name)
        if hit.get("username")
        and (hit.get("remark") or hit.get("nick_name") or "").strip() == display_name
    }
    if any("@chatroom" in username for username in same_name):
        raise WeChatError("存在同名群聊，无法单凭标题安全区分；请给目标好友设置唯一备注名")
    if display_name == "文件传输助手":
        if same_name - {"filehelper"}:
            raise WeChatError("存在与文件传输助手同名的联系人，无法安全测试")
        return "filehelper"
    matches = {username for username in same_name if username != db.wxid}
    if len(matches) != 1:
        raise WeChatError(f"目标好友的准确显示名须唯一，当前匹配 {len(matches)} 位；请使用唯一备注名")
    return matches.pop()


def rows_to_messages(rows: list[dict], self_username: str) -> tuple[Message, ...]:
    messages = []
    # In some WeChat 4.1 chats the peer's sender_username is missing, while
    # outgoing rows still carry our wxid. Learn our numeric ID from those rows.
    self_sender_ids = {
        int(row.get("sender_id") or 0)
        for row in rows
        if row.get("sender_username") == self_username and int(row.get("sender_id") or 0) > 0
    }
    for row in reversed(rows):
        kind = "text" if row.get("type") == "文本" else "other"
        content = row.get("content")
        text = content if isinstance(content, str) else ""
        if not text or text == "[文本]":
            kind = "other"
            text = f"[{row.get('type') or '未知'}]"
        sender_id = int(row.get("sender_id") or 0)
        sender_username = row.get("sender_username") or ""
        if sender_username == self_username:
            sender = "outgoing"
        elif row.get("type") == "系统消息":
            sender = "system"
        elif sender_username and sender_id > 0:
            sender = "incoming"
        elif sender_id > 0 and self_sender_ids and sender_id not in self_sender_ids:
            sender = "incoming"
        else:
            sender = "system"
        identity = ":".join(str(row.get(k, "")) for k in ("sort_seq", "local_id", "create_time", "sender_id", "type"))
        messages.append(Message(sender, text, kind, identity))
    return tuple(messages)


def _read_clipboard_text() -> str | None:
    win32clipboard.OpenClipboard()
    try:
        formats = []
        fmt = 0
        while True:
            fmt = win32clipboard.EnumClipboardFormats(fmt)
            if not fmt:
                break
            formats.append(fmt)
        text_formats = {win32clipboard.CF_TEXT, win32clipboard.CF_OEMTEXT,
                        win32clipboard.CF_UNICODETEXT, win32clipboard.CF_LOCALE}
        if any(fmt not in text_formats for fmt in formats):
            raise ClipboardNotPlainText("剪贴板含图片或富文本")
        return (win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                if win32clipboard.CF_UNICODETEXT in formats else None)
    finally:
        win32clipboard.CloseClipboard()


def _restore_clipboard(old_text: str | None, reply: str) -> None:
    win32clipboard.OpenClipboard()
    try:
        current = (win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                   if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT) else None)
        if current == reply:
            win32clipboard.EmptyClipboard()
            if old_text is not None:
                win32clipboard.SetClipboardText(old_text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


class WeChatDatabase:
    def __init__(self, contact: str, limit: int = 80) -> None:
        from wechatauto import WeChatDB
        from wechatauto.logger import wxlog
        from wechatauto.param import WxParam
        from wechatauto.uia_driver import WeChatUIA

        # Third-party logs may contain account paths or messages; disable files.
        WxParam.ENABLE_FILE_LOGGER = False
        wxlog.console_handler.setLevel(logging.ERROR)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self.db = WeChatDB(workdir=str(STATE_DIR))
            self.contact = contact.strip()
            self.username = resolve_contact(self.db, self.contact)
            self.uia = WeChatUIA()
            if not self.uia.ensure_window():
                raise WeChatError("无法激活微信 4.x 的聊天无障碍控件")
        except WeChatError:
            raise
        except Exception as exc:
            raise WeChatError("无法读取本机微信数据库或激活聊天控件，请确认微信已登录且权限一致") from exc
        self.limit = limit

    def _editor(self):
        edit = self.uia._chat_input()
        if edit is None:
            raise WeChatError("无法定位当前聊天输入框")
        try:
            pattern = edit.GetValuePattern()
            if pattern is None or pattern.Value is None:
                raise ValueError("no value")
            return edit, pattern.Value
        except Exception as exc:
            raise WeChatError("无法确认微信输入框是否为空，已停止发送") from exc

    def _current_chat(self) -> str | None:
        if not self.uia.ensure_window():
            raise WeChatError("微信无障碍控件不可用")
        return self.uia.current_chat()

    def snapshot(self) -> Snapshot:
        try:
            current = self._current_chat()
            draft = self._editor()[1] if current == self.contact else ""
            rows = self.db.get_messages(self.username, limit=self.limit)
            return Snapshot(self.contact, rows_to_messages(rows, self.db.wxid), draft, current == self.contact)
        except WeChatError:
            raise
        except Exception as exc:
            raise WeChatError("无法可靠读取目标聊天的本机消息，请检查微信数据库状态") from exc

    def ready_to_send(self) -> bool:
        try:
            if self._current_chat() != self.contact:
                return False
            hwnd = self.uia._win.NativeWindowHandle
            foreground = win32gui.GetForegroundWindow()
            root = win32gui.GetAncestor(foreground, win32con.GA_ROOT) or foreground
            return bool(hwnd and root == hwnd)
        except Exception:
            return False

    def send(self, expected: Snapshot, reply: str) -> Snapshot:
        if not self.ready_to_send() or self.snapshot() != expected or expected.draft:
            raise WeChatError("发送前聊天对象、消息或输入框已变化，未发送")
        edit, draft = self._editor()
        if draft:
            raise WeChatError("微信输入框已有文字，未发送")
        use_clipboard = True
        try:
            old_clipboard = _read_clipboard_text()
        except ClipboardNotPlainText:
            # ValuePattern can write without replacing a user's image clipboard.
            use_clipboard = False
            old_clipboard = None
        try:
            if use_clipboard:
                # Paste without clearing so a concurrent human draft cannot be erased.
                self.uia._paste_into(edit, reply, clear=False)
            elif not self.uia._click_ctrl(edit) or not self.uia._set_text(edit, reply):
                raise WeChatError("无法不改动剪贴板地填写微信输入框，未发送")
            filled = self.snapshot()
            if (filled.contact != expected.contact or not filled.is_direct
                    or filled.messages != expected.messages or filled.draft != reply
                    or not self.ready_to_send()):
                raise WeChatError("粘贴后未能核对聊天和草稿，已暂停，请人工检查输入框")
            edit.SendKeys("{Enter}", waitTime=0.05)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                time.sleep(0.5)
                current = self.snapshot()
                added = new_messages(expected.messages, current.messages)
                if added and any(m.sender == "outgoing" and m.kind == "text" and m.text == reply for m in added):
                    return current
            raise WeChatError("已操作发送，但数据库未确认；请人工检查，程序不会重发")
        except WeChatError:
            raise
        except Exception as exc:
            raise WeChatError("发送结果不确定；请人工检查微信，程序不会重发") from exc
        finally:
            if use_clipboard:
                try:
                    _restore_clipboard(old_clipboard, reply)
                except Exception:
                    pass
