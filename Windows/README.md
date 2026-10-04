# 忙碌消息助手 · Windows

Windows 端使用 Python、Tkinter、DeepSeek API 和本机微信 4.x 数据库。它针对**一个已打开的单人聊天**建立消息基线，只处理启动后的新文字消息。默认仅生成草稿，点击“5 秒后确认发送”并切回微信后才尝试发送。经过人工测试后，也可以主动勾选“生成后自动发送”；自动模式仍要求目标聊天保持打开、微信位于前台、输入框为空。

这个版本不遍历好友，不处理群聊、公众号、图片、语音、视频或转账。媒体及系统消息会参与“聊天是否变化”的核对，但不会作为 AI 提示词。可以先在微信自带的「文件传输助手」中验证发送流程；再与同意测试的好友验证真实对话。

## 实现方式与代码结构

| 文件 | 作用 |
| --- | --- |
| `app.py` | Tkinter 界面、限时会话、草稿确认和自动发送开关 |
| `assistant/core.py` | 新消息识别、启动基线、轮数上限和发送回执规则 |
| `assistant/wechat_db.py` | 从本机数据库读取指定好友的最近消息；通过微信 UIA 输入；回读数据库核对发送 |
| `assistant/deepseek.py` | 使用环境变量中的 API Key 请求 DeepSeek |
| `assistant/wechat.py` | 旧版微信可用的 UIA 适配器；作为可选后端保留 |
| `check_connection.py` | 用虚构文本检查 DeepSeek 连接，不读取微信 |
| `check_wechat.py` | 只读检查数据库、目标聊天和空输入框；不输出聊天正文 |
| `diagnose.py` | 只列微信控件结构，不输出聊天正文；主要用于旧 UIA 后端 |
| `config.example.json` | 不含密钥的本机配置样例 |
| `tests/` | 不发送消息的离线测试 |

本机数据库读写适配由 [wechatauto-replica](https://github.com/fanyuantaier/wechatauto-replica) 提供，依赖版本固定为 `1.2.4.4`。该库文档说明支持微信 4.1.13.65：读取端解密微信本地 SQLCipher 数据库，发送端激活微信进程中的无障碍控件。本项目只使用单人聊天消息读取、UIA 输入和数据库回读，不使用它的全局监听、历史导出或媒体下载功能。

## 运行环境与安装

- Windows 10/11、**64 位 Python 3.11 或 3.12**、已登录的 Windows 个人微信 4.1.x。微信版本变化可能导致数据库或控件适配失效。
- 电脑保持解锁，微信主窗口能正常显示。微信与本程序使用相同的普通用户权限运行。
- 微信设为 **Enter 发送**。如当前设置为 Ctrl+Enter 发送，请先在微信设置中调整。
- 你自己的 DeepSeek API Key。仅将新文字消息及忙碌说明发给 DeepSeek，不发送本机数据库文件。

在 PowerShell 中先进入仓库根目录，再运行：

```powershell
cd .\Windows
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.json
notepad config.json
```

如果 `python` 命令找不到，但已安装 Python，可把上面的 `python -m venv .venv` 改为安装版 Python 的绝对路径，例如 `& 'C:\Path\To\Python312\python.exe' -m venv .venv`。此项目无需 `py` 启动器，也无需便携版 Python。虚拟环境创建后始终使用 `.\.venv\Scripts\python.exe`。

在 `config.json` 中把 `contact` 改为微信当前单人聊天标题里显示的**准确名称**。如果有同名好友，先在微信中给目标好友设置唯一备注；程序遇到同名会拒绝开始。`activity` 是你当前忙碌状态，`tone` 是回复语气，`duration_minutes` 为 5–480 分钟，`max_replies` 为 1–100 轮。`backend` 保持 `database`。`window_title_regex` 供旧 UIA 后端使用，数据库后端无需修改。

## 配置 DeepSeek API Key

密钥只通过当前 PowerShell 会话的环境变量传递，不写入 `config.json`、源代码或 Git。可用下面的方式隐藏输入：

```powershell
$secret = Read-Host 'DeepSeek API Key' -AsSecureString
$env:DEEPSEEK_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
.\.venv\Scripts\python.exe check_connection.py
```

连接检查只发送虚构测试文本。关闭这个 PowerShell 窗口后，环境变量会失效；再次运行时重新设置即可。若密钥曾在聊天或截图中公开，建议去 DeepSeek 控制台撤销并生成新密钥。默认模型是 `deepseek-flash`，请求显式关闭思考模式以生成简短回复；可在 `config.json` 中改成账号可用的其他模型。

## 使用与测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe check_wechat.py
.\.venv\Scripts\python.exe app.py
```

1. 在微信打开目标好友的**单人聊天**，确认输入框为空。配置中不要填群名。
2. 在助手点击“开始”。程序读取最近消息作为基线，旧消息不会触发回复。开始时需要能确认当前聊天标题与配置中的好友名称相同。
3. 请同意测试的好友发一条新的纯文字消息。助手会显示 AI 草稿，默认不会发送。
4. 检查草稿内容后，点击“5 秒后确认发送”，并在倒计时内切回这个好友的微信窗口。程序会重新核对聊天、消息、输入框，再粘贴、按 Enter，并从本机数据库读取回执。无法确认时会暂停，**不会自动重发**。
5. 确认这一流程在你的微信上正常后，才考虑勾选自动发送。自动发送也只在目标聊天已打开且微信位于前台时生效。
6. 点击“停止”或关闭程序结束；达到时长或轮数上限也会结束。

若你切换聊天、手动输入草稿、微信失去焦点、消息发生变化，程序会跳过或暂停。发送后如果数据库未能确认，请人工查看微信聊天记录，避免重复发送。

## 隐私与本机数据

- `config.json`、`.venv/` 和 `.state/` 已被 `Windows/.gitignore` 忽略，不会随正常的 `git add .` 提交。不要把真实 Key、聊天正文、数据库缓存或截图手动加入仓库。
- `wechatauto-replica` 首次读取时会扫描已登录微信进程内存以提取数据库密钥，并在 `Windows/.state/wechatdb/` 缓存**解密后的本机数据库和密钥**。这个目录可能包含全部本机微信聊天，不限于目标好友；请像保护微信数据目录一样保护它。停止程序后，可自行删除 `.state/` 来清除缓存，下次启动会重新提取。
- 发送时库会在微信进程中启用无障碍控件。本项目在发送前检查输入框为空、当前聊天名称准确、微信在前台；发送后从数据库查找新发出的完整文字。通常使用剪贴板粘贴并尝试恢复原有纯文字；如果剪贴板含图片或富文本，则尝试直接通过无障碍控件填写，不改动剪贴板。填写后核对不通过就不按发送键。
- 本程序只把目标好友触发回复的**新文字消息**和你设置的忙碌说明发送给 DeepSeek。日志不保存聊天正文，AI 草稿只保留在本次程序内存中。
- 这类个人微信自动化依赖客户端内部实现；微信更新、账号状态或桌面布局变化都可能导致失效。请在自己的账号上谨慎测试，并遵守所用服务的规则。

## 常见问题

- **“无法读取本机微信数据库”**：确认微信已登录、Python 为 64 位，且微信和本程序以相同用户权限运行。多账号登录时，先只保留要使用的账号。
- **“目标好友的准确显示名须唯一”**：给目标好友设置唯一备注名，并把 `contact` 写成相同名称。
- **“微信无障碍控件不可用”**：确认微信版本与适配库兼容，重启微信后再试。`diagnose.py` 只读控件树，可用于排查。
- **没有生成草稿**：确认目标单人聊天保持打开、输入框为空；旧消息不会触发。先让测试好友发送新纯文字。
- **已操作发送但未确认**：不要再次点击发送；先在微信中人工核对。发送方式须为 Enter 发送。

旧版微信若本身提供完整 UIA 树，可在配置中选择 `backend: "uia"` 并提供四个唯一控件选择器（`chat_title`、`message_list`、`input`、`direct_chat_marker`）。当前微信 4.1.13.65 建议使用默认 `database` 后端。
