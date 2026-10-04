"""Test DeepSeek with synthetic text, without opening WeChat or saving a key."""

from __future__ import annotations

from getpass import getpass
import os

from assistant.deepseek import generate


def main() -> None:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        os.environ["DEEPSEEK_API_KEY"] = getpass("DeepSeek API Key（输入时不显示）：")
    try:
        reply = generate("deepseek-flash", "正在测试连接", "简短", "你好，请回复一条测试消息。", True)
        print("连接成功。模型回复：", reply)
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)


if __name__ == "__main__":
    main()
