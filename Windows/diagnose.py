"""List WeChat UIA structure without printing contact names or message text."""

from __future__ import annotations

from assistant.wechat import wechat_windows


def walk(control, depth: int = 0) -> None:
    if depth > 6:
        return
    info = control.element_info
    print("  " * depth + f"{info.control_type} id={info.automation_id!r} "
          f"class={info.class_name!r} name_length={len(control.window_text())}")
    for child in control.children():
        walk(child, depth + 1)


if __name__ == "__main__":
    windows = list(wechat_windows())
    print(f"可见微信窗口：{len(windows)}。以下不显示好友名和消息正文。")
    for item in windows:
        print(f"window handle={item.handle} title_length={len(item.window_text())}")
        walk(item)
