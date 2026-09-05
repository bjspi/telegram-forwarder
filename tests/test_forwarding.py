from __future__ import annotations
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Tests never use a local account or open a Telegram connection.
os.environ.update(TG_ACCOUNT="test", TG_PHONE_NR="test", TG_API_ID="123", TG_API_HASH="test")
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

from pyrogram.errors import MessageIdInvalid  # noqa: E402
from telegram_forwarder.core.forward_index import ForwardIndex  # noqa: E402
from telegram_forwarder.core.models import ChatRef, ListenerRule  # noqa: E402
from telegram_forwarder.handlers.listeners import register_forward_handlers  # noqa: E402
from telegram_forwarder.services.forwarding import copy_or_replace_message, edit_forwarded_message  # noqa: E402


def message(text="", photo=None):
    return SimpleNamespace(id=1, chat=SimpleNamespace(id=10, has_protected_content=False),
                           text=text, caption=None, photo=photo, copy=AsyncMock(return_value=SimpleNamespace(id=2)))


def client():
    return SimpleNamespace(edit_message_text=AsyncMock(), edit_message_caption=AsyncMock(),
                           delete_messages=AsyncMock(), send_message=AsyncMock(return_value=SimpleNamespace(id=3)))


class ForwardingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.index = ForwardIndex()
        self.rule = ListenerRule(10, target_chats=[ChatRef(20)], store_edits=True)
        self.client = client()

    async def test_long_history_keeps_latest_version_within_limit(self):
        self.index.set_record(10, 1, {20: 2}, edit_mode="text", last_body="a" * 2200, edit_history=["a" * 2200])
        await edit_forwarded_message(self.client, message("b" * 2200), self.rule, self.index.get_record(10, 1), self.index)
        text = self.client.edit_message_text.call_args.args[2]
        self.assertLessEqual(len(text.encode("utf-16-le")) // 2, 4096)
        self.assertIn("b" * 2200, text)
        self.client.delete_messages.assert_not_awaited()

    async def test_failed_edit_and_replacement_preserve_archive_and_mapping(self):
        self.index.set_record(10, 1, {20: 2}, edit_mode="text", last_body="old")
        self.client.edit_message_text.side_effect = MessageIdInvalid()
        self.client.send_message.side_effect = OSError("offline")
        await edit_forwarded_message(self.client, message("new"), self.rule, self.index.get_record(10, 1), self.index)
        self.client.delete_messages.assert_not_awaited()
        self.assertEqual(self.index.get_record(10, 1).target_message_ids, {20: 2})
        self.assertEqual(self.index.get_record(10, 1).last_body, "old")

    async def test_replacement_is_confirmed_before_deleting_old_copy(self):
        self.index.set_record(10, 1, {20: 2}, edit_mode="text", last_body="old")
        self.client.edit_message_text.side_effect = MessageIdInvalid()

        async def sent(*args):
            self.client.delete_messages.assert_not_awaited()
            return SimpleNamespace(id=3)

        self.client.send_message.side_effect = sent
        await edit_forwarded_message(self.client, message("new"), self.rule, self.index.get_record(10, 1), self.index)
        self.client.delete_messages.assert_awaited_once_with(20, 2)
        self.assertEqual(self.index.get_record(10, 1).target_message_ids, {20: 3})

    async def test_transient_edit_error_does_not_trigger_replacement(self):
        self.index.set_record(10, 1, {20: 2}, edit_mode="text", last_body="old")
        self.client.edit_message_text.side_effect = TimeoutError()
        with self.assertLogs(level="WARNING"):
            await edit_forwarded_message(self.client, message("new"), self.rule, self.index.get_record(10, 1), self.index)
        self.client.send_message.assert_not_awaited()
        self.client.delete_messages.assert_not_awaited()

    async def test_paused_and_removed_targets_receive_no_edits(self):
        self.rule.target_chats.append(ChatRef(30))
        self.rule.disabled_target_ids = [30]
        self.index.set_record(10, 1, {20: 2, 30: 3, 40: 4}, edit_mode="text", last_body="old")
        await edit_forwarded_message(self.client, message("new"), self.rule, self.index.get_record(10, 1), self.index)
        self.assertEqual(self.client.edit_message_text.await_count, 1)
        self.assertEqual(self.client.edit_message_text.call_args.args[0], 20)

    async def test_failed_media_replacement_keeps_old_copy(self):
        self.index.set_record(10, 1, {20: 2}, media_signature="photo:old")
        with patch("telegram_forwarder.services.forwarding.copy_message_to_target", new=AsyncMock(return_value=None)):
            await copy_or_replace_message(self.client, message(photo=SimpleNamespace(file_unique_id="new")), self.rule, self.index)
        self.client.delete_messages.assert_not_awaited()
        self.assertEqual(self.index.get_record(10, 1).media_signature, "photo:old")

    def handlers(self):
        registered = {}

        def register(kind):
            def decorator(*args):
                def attach(fn):
                    registered[kind] = fn
                    return fn
                return attach
            return decorator

        app = SimpleNamespace(on_message=register("new"), on_edited_message=register("edit"), on_raw_update=register("raw"))
        register_forward_handlers(app, SimpleNamespace(get_listener=lambda _: self.rule), self.index)
        return registered

    async def test_replaced_captionless_photo_is_forwarded_but_reaction_is_not(self):
        self.index.set_record(10, 1, {20: 2}, media_signature="photo:old")
        edited = self.handlers()["edit"]
        photo = message(photo=SimpleNamespace(file_unique_id="new"))
        await edited(self.client, photo)
        photo.copy.assert_awaited_once()
        self.client.delete_messages.assert_awaited_once_with(20, 2)
        await edited(self.client, photo)
        photo.copy.assert_awaited_once()

    async def test_unknown_edit_is_not_copied(self):
        unknown = message("old message")
        await self.handlers()["edit"](self.client, unknown)
        unknown.copy.assert_not_awaited()

    async def test_caption_history_respects_utf16_limit_with_emoji(self):
        self.index.set_record(10, 1, {20: 2}, edit_mode="caption", last_body="old",
                              edit_history=["old"], media_signature="photo:one")
        photo = message(photo=SimpleNamespace(file_unique_id="one"))
        photo.caption = "🎉" * 600
        await edit_forwarded_message(self.client, photo, self.rule, self.index.get_record(10, 1), self.index)
        caption = self.client.edit_message_caption.call_args.args[2]
        self.assertLessEqual(len(caption.encode("utf-16-le")) // 2, 1024)
        self.client.delete_messages.assert_not_awaited()

    async def test_media_replacement_leaves_paused_target_untouched(self):
        self.rule.target_chats.append(ChatRef(30))
        self.rule.disabled_target_ids = [30]
        self.index.set_record(10, 1, {20: 2, 30: 3}, media_signature="photo:old")
        photo = message(photo=SimpleNamespace(file_unique_id="new"))
        await self.handlers()["edit"](self.client, photo)
        photo.copy.assert_awaited_once_with(chat_id=20)
        self.client.delete_messages.assert_awaited_once_with(20, 2)
        self.assertEqual(self.index.get_record(10, 1).target_message_ids[30], 3)

    async def test_reaction_after_restart_does_not_make_another_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.sqlite3"
            first = ForwardIndex(path)
            first.set_record(10, 1, {20: 2}, edit_mode="text", last_body="unchanged")
            first.close()
            self.index = ForwardIndex(path)
            try:
                unchanged = message("unchanged")
                await self.handlers()["edit"](self.client, unchanged)
                unchanged.copy.assert_not_awaited()
                self.client.edit_message_text.assert_not_awaited()
                unchanged.text = "changed"
                await self.handlers()["edit"](self.client, unchanged)
                self.client.edit_message_text.assert_awaited_once()
                unchanged.copy.assert_not_awaited()
            finally:
                self.index.close()


class PersistenceTests(unittest.TestCase):
    def test_mapping_survives_restart_and_memory_ttl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.sqlite3"
            first = ForwardIndex(path)
            first.set_record(10, 1, {20: 2}, edit_mode="text", last_body="old", media_signature="photo:one")
            first.close()
            second = ForwardIndex(path)
            try:
                record = second.get_record(10, 1)
                self.assertEqual(record.target_message_ids, {20: 2})
                record.stored_at = float("-inf")
                self.assertEqual(second.get_record(10, 1).media_signature, "photo:one")
                second.remove_record(10, 1)
                self.assertIsNone(second.get_record(10, 1))
            finally:
                second.close()


if __name__ == "__main__":
    unittest.main()
