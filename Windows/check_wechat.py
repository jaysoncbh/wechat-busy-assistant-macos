"""Read-only local readiness check; never prints contacts or message bodies."""

from app import load_config
from assistant.wechat_db import WeChatDatabase


def main() -> None:
    config = load_config()
    if config.get("backend", "database") != "database":
        raise SystemExit("这个检查只适用于 database 后端")
    chat = WeChatDatabase(config["contact"])
    snapshot = chat.snapshot()
    print("本机数据库读取成功")
    print("目标单人聊天已打开：", "是" if snapshot.is_direct else "否")
    print("微信输入框为空：", "是" if not snapshot.draft else "否")
    print("最近消息数量：", len(snapshot.messages))
    print("检查仅仅读取状态，没有发送消息，也没有输出聊天正文。")


if __name__ == "__main__":
    main()
