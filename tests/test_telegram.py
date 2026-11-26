import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cbh import telegram


class TelegramConfigTests(unittest.TestCase):
    def test_config_is_saved_outside_repo_with_restricted_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "private" / "telegram.json"
            with patch.dict("os.environ", {"CBH_TELEGRAM_CONFIG": str(target)}):
                saved = telegram.configure("123456:" + "A" * 30, "987654")
                self.assertEqual(saved, target)
                self.assertEqual(telegram.load_config(), {
                    "token": "123456:" + "A" * 30,
                    "chat_id": "987654",
                })
                self.assertEqual(target.stat().st_mode & 0o077, 0)

    def test_invalid_token_and_chat_id_rejected(self):
        with self.assertRaises(ValueError):
            telegram.validate_token("not-a-token")
        with self.assertRaises(ValueError):
            telegram.configure("123456:" + "A" * 30, "not-a-chat")

    def test_get_chats_extracts_private_chat(self):
        with patch.object(telegram, "_api", return_value=[{
            "message": {"chat": {"id": 123, "type": "private", "first_name": "Tester"}}
        }]):
            chats = telegram.get_chats("123456:" + "A" * 30)
        self.assertEqual(chats[0]["id"], "123")
        self.assertEqual(chats[0]["name"], "Tester")

    def test_send_message_uses_saved_configuration(self):
        config = {"token": "123456:" + "A" * 30, "chat_id": "123"}
        with patch.object(telegram, "_api", return_value=[]) as api:
            self.assertTrue(telegram.send_message("hello", config))
        self.assertEqual(api.call_args.args[1], "sendMessage")
        self.assertEqual(api.call_args.args[2]["chat_id"], "123")


if __name__ == "__main__":
    unittest.main()
