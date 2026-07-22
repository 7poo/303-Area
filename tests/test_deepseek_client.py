import json
import unittest
from unittest.mock import patch

from src.deepseek_client import DeepSeekClient, DeepSeekError


class FakeHTTPResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({
            "id": "test-1",
            "model": "deepseek-chat",
            "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        }).encode()


class DeepSeekClientTest(unittest.TestCase):
    def test_missing_key_is_explicit(self):
        with self.assertRaises(DeepSeekError):
            DeepSeekClient(api_key="").complete([{"role": "user", "content": "hi"}])

    @patch("src.deepseek_client.urllib.request.urlopen", return_value=FakeHTTPResponse())
    def test_openai_compatible_response_is_normalized(self, mocked):
        client = DeepSeekClient(api_key="test-key", max_retries=0)
        result = client.complete([{"role": "user", "content": "hi"}])
        self.assertEqual(result["message"]["content"], "ok")
        self.assertEqual(mocked.call_count, 1)


if __name__ == "__main__":
    unittest.main()
