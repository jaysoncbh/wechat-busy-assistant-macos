"""Strict, configurable UI Automation adapter for an already open direct chat.

WeChat builds expose different accessibility trees. The user supplies four
unique selectors from diagnose.py; ambiguous or missing controls fail closed.
"""

from __future__ import annotations

import ctypes
import re
import time
from typing import Any

import psutil
from pywinauto import Desktop

from .core import Message, Snapshot


class WeChatError(RuntimeError):
    pass


def wechat_windows():
    for window in Desktop(backend="uia").windows():
        try:
            name = psutil.Process(window.element_info.process_id).name().lower()
            if name in {"weixin.exe", "wechat.exe"} and window.is_visible():
                yield window
        except (psutil.Error, RuntimeError):
            continue


class WeChatUI:
    def __init__(self, title_pattern: str, selectors: dict[str, dict[str, str]]) -> None:
        self.title_pattern = re.compile(title_pattern)
        self.selectors = selectors

    def window(self):
        matches = [w for w in wechat_windows() if self.title_pattern.search(w.window_text())]
        if len(matches) != 1:
            raise WeChatError(f"需要恰好一个匹配的微信主窗口，当前找到 {len(matches)} 个")
        return matches[0]

    def _control(self, window: Any, key: str):
        selector = self.selectors[key]
        matches = []
        for control in window.descendants():
            info = control.element_info
            if selector.get("automation_id") and info.automation_id != selector["automation_id"]:
                continue
            if selector.get("control_type") and info.control_type != selector["control_type"]:
                continue
            if selector.get("class_name") and info.class_name != selector["class_name"]:
                continue
            if selector.get("name") and control.window_text() != selector["name"]:
                continue
            if control.is_visible():
                matches.append(control)
        if len(matches) != 1:
            raise WeChatError(f"控件 {key} 匹配数量为 {len(matches)}，请检查 config.json 中的选择器")
        return matches[0]

    def _read(self, window: Any) -> Snapshot:
        title = self._control(window, "chat_title").window_text().strip()
        direct = self._control(window, "direct_chat_marker").is_visible()
        message_list = self._control(window, "message_list")
        edit = self._control(window, "input")
        try:
            draft = edit.get_value()
        except (AttributeError, RuntimeError) as exc:
            raise WeChatError("输入框不支持读取内容，已停止处理") from exc
        if draft is None:
            raise WeChatError("无法确认输入框是否为空")
        rows: list[Message] = []
        box = message_list.rectangle()
        middle = (box.left + box.right) / 2
        for row in message_list.children():
            if row.element_info.control_type not in {"ListItem", "DataItem"}:
                continue
            visible_text = []
            for child in row.descendants():
                if child.element_info.control_type not in {"Text", "Document"}:
                    continue
                value = child.window_text().strip()
                if value and child.is_visible():
                    visible_text.append((value, child.rectangle()))
            # More than one label may be a sender, timestamp or media caption.
            # Do not guess which label is the message body.
            if len(visible_text) != 1:
                continue
            value, rect = visible_text[0]
            if not value or value.startswith(("[图片]", "[表情]", "[语音]", "[视频]")):
                continue
            if len(value) > 2000 or re.fullmatch(r"\d{1,2}:\d{2}", value):
                continue
            x = (rect.left + rect.right) / 2
            if x < middle - box.width() * 0.05:
                sender = "incoming"
            elif x > middle + box.width() * 0.05:
                sender = "outgoing"
            else:
                continue
            rows.append(Message(sender, value))
        return Snapshot(title, tuple(rows), draft, direct)

    def snapshot(self) -> Snapshot:
        try:
            return self._read(self.window())
        except WeChatError:
            raise
        except Exception as exc:
            raise WeChatError("无法可靠读取微信窗口，请检查界面和选择器") from exc

    def ready_to_send(self) -> bool:
        window = self.window()
        return ctypes.windll.user32.GetForegroundWindow() == window.handle

    def send(self, expected: Snapshot, reply: str) -> Snapshot:
        window = self.window()
        if ctypes.windll.user32.GetForegroundWindow() != window.handle:
            raise WeChatError("请先切到微信窗口，未发送")
        current = self._read(window)
        if current != expected or current.draft:
            raise WeChatError("好友、消息或输入框发生变化，未发送")
        edit = self._control(window, "input")
        try:
            edit.set_edit_text(reply)
            check = self._read(window)
            if check.contact != expected.contact or check.messages != expected.messages or check.draft != reply:
                raise WeChatError("填写后状态改变，已暂停，请人工检查输入框")
            if ctypes.windll.user32.GetForegroundWindow() != window.handle:
                raise WeChatError("填写后微信失去焦点，已暂停，请人工检查输入框")
            edit.set_focus()
            edit.type_keys("{ENTER}", set_foreground=False)
            time.sleep(1.2)
            return self._read(window)
        except WeChatError:
            raise
        except Exception as exc:
            raise WeChatError("发送结果不确定，已暂停，请人工检查微信") from exc
