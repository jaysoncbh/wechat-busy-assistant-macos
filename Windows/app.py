"""Tkinter front end. Start is always explicit and defaults to draft review."""

from __future__ import annotations

import json
import os
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
from tkinter import messagebox, ttk

from assistant.core import BusySession, Candidate, Snapshot
from assistant.deepseek import generate
from assistant.wechat_db import WeChatDatabase
from assistant.wechat import WeChatError, WeChatUI


HERE = Path(__file__).resolve().parent


def load_config() -> dict:
    path = HERE / "config.json"
    if not path.exists():
        raise ValueError("请先复制 config.example.json 为 config.json，并填写目标好友")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("contact"), str) or not data["contact"].strip():
        raise ValueError("请填写目标好友的准确显示名")
    backend = data.get("backend", "database")
    if backend == "uia":
        selectors = data.get("selectors", {})
        for key in ("chat_title", "message_list", "input", "direct_chat_marker"):
            value = selectors.get(key)
            if not isinstance(value, dict) or not value.get("control_type") or not any(
                value.get(field) for field in ("automation_id", "name", "class_name")
            ) or "请用诊断工具" in str(value):
                raise ValueError(f"请填写 selectors.{key}，且保证它在窗口中唯一")
    elif backend != "database":
        raise ValueError("backend 只能是 database 或 uia")
    minutes = int(data.get("duration_minutes", 30))
    limit = int(data.get("max_replies", 5))
    if not 5 <= minutes <= 480 or not 1 <= limit <= 100:
        raise ValueError("时长须为 5–480 分钟，回复轮数须为 1–100")
    data["duration_minutes"] = minutes
    data["max_replies"] = limit
    data["poll_seconds"] = max(1, min(float(data.get("poll_seconds", 2)), 30))
    for key in ("model", "activity", "tone", "window_title_regex"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"请填写 {key}")
    return data


class AssistantApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("忙碌消息助手 · Windows")
        self.root.geometry("600x430")
        self.config: dict | None = None
        self.wechat: WeChatUI | WeChatDatabase | None = None
        self.session: BusySession | None = None
        self.reply: str | None = None
        self.waiting: Candidate | None = None
        self.results: Queue[tuple[Candidate, str | None, str | None]] = Queue()
        self.auto = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="请准备本机配置，再开始忙碌模式。")
        self.summary = tk.StringVar(value="尚未开始")
        self._layout()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(500, self.tick)

    def _layout(self) -> None:
        main = ttk.Frame(self.root, padding=18)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="Windows 个人微信 AI 回复助手", font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        ttk.Label(main, text="仅处理配置中指定的当前私聊；启动前的旧消息不会回复。", wraplength=550).pack(anchor="w", pady=(8, 12))
        ttk.Label(main, textvariable=self.summary).pack(anchor="w")
        ttk.Label(main, textvariable=self.status, wraplength=550, foreground="#225c5a").pack(anchor="w", pady=(8, 12))
        bar = ttk.Frame(main)
        bar.pack(fill="x")
        ttk.Button(bar, text="开始", command=self.start).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="停止", command=self.stop).pack(side="left", padx=(0, 8))
        self.send_button = ttk.Button(bar, text="5 秒后确认发送", command=self.confirm)
        self.send_button.pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="忽略草稿", command=self.discard).pack(side="left")
        ttk.Checkbutton(main, text="生成后自动发送（仅当前微信窗口在前台时）", variable=self.auto).pack(anchor="w", pady=(12, 4))
        ttk.Label(main, text="草稿（仅保存在本次程序内）").pack(anchor="w")
        self.draft = tk.Text(main, height=7, wrap="word", state="disabled")
        self.draft.pack(fill="both", expand=True, pady=(5, 0))
        self.root.after(0, self._buttons)

    def _buttons(self) -> None:
        self.send_button.configure(state="normal" if self.reply and self.session and self.session.active else "disabled")

    def _show_draft(self, text: str) -> None:
        self.draft.configure(state="normal")
        self.draft.delete("1.0", "end")
        self.draft.insert("1.0", text)
        self.draft.configure(state="disabled")
        self._buttons()

    def start(self) -> None:
        if self.session and self.session.active:
            self.status.set("忙碌模式已经运行。")
            return
        try:
            config = load_config()
            if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
                raise ValueError("请先设置 DEEPSEEK_API_KEY 环境变量")
            wechat = (WeChatDatabase(config["contact"])
                      if config.get("backend", "database") == "database"
                      else WeChatUI(config["window_title_regex"], config["selectors"]))
            first = wechat.snapshot()
            if first.contact != config["contact"] or not first.is_direct:
                raise ValueError("请先打开配置中指定好友的一对一私聊，并检查直聊标记")
            if first.draft:
                raise ValueError("微信输入框中已有文字，请先处理，避免覆盖")
            session = BusySession(config["contact"], config["duration_minutes"], config["max_replies"])
            session.observe(first)
            self.config, self.wechat, self.session = config, wechat, session
            self.reply = None
            self.waiting = None
            self._show_draft("")
            self.summary.set(f"目标：{session.contact} · {config['duration_minutes']} 分钟 · 最多 {session.max_replies} 轮")
            self.status.set("已建立当前聊天基线，等待新文字消息。")
        except (ValueError, WeChatError, KeyError, OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("无法开始", str(exc))

    def stop(self) -> None:
        self.session = None
        self.waiting = None
        self.reply = None
        self._show_draft("")
        self.summary.set("已停止")
        self.status.set("忙碌模式已停止。")

    def discard(self) -> None:
        if not self.session or not self.wechat:
            return
        try:
            current = self.wechat.snapshot()
        except WeChatError:
            current = None
        self.session.discard(current)
        self.waiting = None
        self.reply = None
        self._show_draft("")
        self.status.set("已忽略这条消息的草稿，继续等待。")

    def _generate(self, candidate: Candidate, config: dict, first_reply: bool) -> None:
        try:
            result = generate(config["model"], config["activity"], config["tone"], candidate.incoming, first_reply)
            self.results.put((candidate, result, None))
        except Exception as exc:
            self.results.put((candidate, None, str(exc)))

    def _receive_results(self) -> None:
        while True:
            try:
                candidate, reply, error = self.results.get_nowait()
            except Empty:
                break
            if not self.session or self.session.pending != candidate:
                continue
            self.waiting = None
            if error:
                self.session.paused = True
                self.status.set(f"生成失败，已暂停：{error}")
            else:
                self.reply = reply
                self._show_draft(reply or "")
                self.status.set("回复已生成；请检查草稿。" if not self.auto.get() else "等待微信窗口在前台以自动发送。")

    def confirm(self) -> None:
        if not self.reply or not self.session or not self.session.active:
            return
        self.status.set("请在 5 秒内切回目标好友的微信窗口；届时将重新核对后发送。")
        self.root.after(5000, self._send)

    def _send(self) -> None:
        if not self.session or not self.session.active or not self.reply or not self.wechat:
            return
        try:
            if not self.wechat.ready_to_send():
                self.status.set("微信未在前台，未发送；草稿仍可确认。")
                return
            current = self.wechat.snapshot()
            if not self.session.can_send(current):
                self.session.discard(current)
                self.reply = None
                self._show_draft("")
                self.status.set("聊天内容或输入框已变化，已丢弃旧草稿。")
                return
            after = self.wechat.send(current, self.reply)
            if not self.session.sent_reply(after, self.reply):
                self.status.set("发送结果未确认，已暂停；请人工检查微信，避免重复发送。")
                return
            self.reply = None
            self._show_draft("")
            self.status.set(f"已核对发送第 {self.session.sent} 条回复。")
        except WeChatError as exc:
            self.session.paused = True
            self.status.set(f"已暂停：{exc}")

    def tick(self) -> None:
        self._receive_results()
        if self.session:
            if not self.session.active:
                if not self.session.paused:
                    self.status.set("忙碌时长或回复轮数已达到上限，已停止。")
                self.session = None
                self.reply = None
                self._show_draft("")
            elif self.reply:
                if self.auto.get() and self.wechat:
                    try:
                        if self.wechat.ready_to_send():
                            self._send()
                    except WeChatError as exc:
                        self.status.set(f"等待微信界面恢复：{exc}")
            elif not self.waiting and self.wechat and self.config:
                try:
                    snapshot = self.wechat.snapshot()
                    candidate = self.session.observe(snapshot)
                    if candidate:
                        self.waiting = candidate
                        self.status.set("发现新文字，正在请求 DeepSeek…")
                        Thread(target=self._generate, args=(candidate, self.config, self.session.sent == 0), daemon=True).start()
                except WeChatError as exc:
                    self.status.set(f"等待微信界面恢复：{exc}")
        delay = int((self.config or {}).get("poll_seconds", 2) * 1000)
        self.root.after(delay, self.tick)

    def close(self) -> None:
        self.stop()
        self.root.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    AssistantApp(window)
    window.mainloop()
