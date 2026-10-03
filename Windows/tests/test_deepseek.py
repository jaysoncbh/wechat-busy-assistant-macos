import io
import json
import unittest
from unittest.mock import patch

from assistant.deepseek import generate


class DeepSeekTests(unittest.TestCase):
    def test_short_reply_uses_non_thinking_mode(self):
        response = io.BytesIO(json.dumps({
            "choices": [{"finish_reason": "stop", "message": {"content": "测试成功"}}]
        }).encode("utf-8"))
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "fake-test-key"}), \
                patch("assistant.deepseek.urlopen", return_value=response) as call:
            self.assertEqual(generate("deepseek-flash", "忙碌", "简短", "你好", True), "测试成功")
        request = call.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(body["model"], "deepseek-flash")


if __name__ == "__main__":
    unittest.main()
