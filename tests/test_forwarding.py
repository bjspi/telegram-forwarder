from __future__ import annotations
import json
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
from telegram_forwarder.connection.chats import resolve_target_ref  # noqa: E402
from telegram_forwarder.core.config_store import BotConfigStore  # noqa: E402
from telegram_forwarder.core.forward_index import ForwardIndex  # noqa: E402
from telegram_forwarder.core.models import ChatRef, ListenerRule  # noqa: E402
from telegram_forwarder.handlers.listeners import register_forward_handlers  # noqa: E402
from telegram_forwarder.services.forwarding import (  # noqa: E402
    copy_or_replace_message,
    edit_forwarded_message,
    resend_message_with_fallback,
    send_media_from_path,
)


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

        async def sent(*args, **kwargs):
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
        photo.copy.assert_awaited_once_with(chat_id=20, message_thread_id=None)
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


TOPIC_ID = 10
MEDIA_TYPES = ("document", "photo", "video", "audio", "voice", "animation", "sticker", "video_note")


class TopicTargetTests(unittest.IsolatedAsyncioTestCase):
    """A topic target must never be posted to without its thread id (it would land in General)."""

    async def asyncSetUp(self):
        self.index = ForwardIndex()
        self.target = ChatRef(20, "Group", topic_id=TOPIC_ID, topic_name="Preview")
        self.rule = ListenerRule(10, target_chats=[self.target])
        self.client = client()

    async def test_copy_goes_into_the_topic(self):
        source = message("hi")
        await copy_or_replace_message(self.client, source, self.rule, self.index)
        source.copy.assert_awaited_once_with(chat_id=20, message_thread_id=TOPIC_ID)

    async def test_text_fallback_after_failed_copy_keeps_the_topic(self):
        source = message("hi")
        source.copy.side_effect = OSError("copy blocked")
        with self.assertLogs(level="WARNING"):
            await copy_or_replace_message(self.client, source, self.rule, self.index)
        self.client.send_message.assert_awaited_once_with(20, "hi", message_thread_id=TOPIC_ID)

    async def test_name_prefix_resend_keeps_the_topic(self):
        self.rule.name_prefix = True
        with patch("telegram_forwarder.services.forwarding.maybe_prefix_text", new=lambda _m, text, _p: text):
            await copy_or_replace_message(self.client, message("hi"), self.rule, self.index)
        self.assertEqual(self.client.send_message.call_args.kwargs, {"message_thread_id": TOPIC_ID})

    async def test_media_reupload_keeps_the_topic_for_every_media_type(self):
        for media_type in MEDIA_TYPES:
            send = AsyncMock(return_value=SimpleNamespace(id=3))
            sender = SimpleNamespace(**{f"send_{media_type}": send})
            await send_media_from_path(sender, self.target, media_type, "file.bin", "caption")
            self.assertEqual(send.call_args.args[0], 20, media_type)
            self.assertEqual(send.call_args.kwargs["message_thread_id"], TOPIC_ID, media_type)

    async def test_downloaded_media_fallback_keeps_the_topic(self):
        photo = message(photo=SimpleNamespace(file_unique_id="one"))
        photo.download = AsyncMock(return_value="file.jpg")
        self.client.send_photo = AsyncMock(return_value=SimpleNamespace(id=3))
        with patch("telegram_forwarder.services.forwarding.safe_unlink"):
            await resend_message_with_fallback(self.client, photo, self.target)
        self.assertEqual(self.client.send_photo.call_args.kwargs["message_thread_id"], TOPIC_ID)

    async def test_edit_replacement_keeps_the_topic(self):
        self.index.set_record(10, 1, {20: 2}, edit_mode="text", last_body="old")
        self.client.edit_message_text.side_effect = MessageIdInvalid()
        await edit_forwarded_message(self.client, message("new"), self.rule, self.index.get_record(10, 1), self.index)
        self.assertEqual(self.client.send_message.call_args.kwargs, {"message_thread_id": TOPIC_ID})
        self.client.delete_messages.assert_awaited_once_with(20, 2)

    async def test_target_reference_with_topic_is_verified(self):
        chat = SimpleNamespace(id=-100123, title="Group")
        topic = SimpleNamespace(name="Preview", is_deleted=False)
        resolver = SimpleNamespace(get_chat=AsyncMock(return_value=chat), get_forum_topic=AsyncMock(return_value=topic))
        target = await resolve_target_ref(resolver, "-100123:10")
        self.assertEqual((target.chat_id, target.topic_id, target.topic_name), (-100123, 10, "Preview"))
        resolver.get_forum_topic.return_value = None
        with self.assertRaises(ValueError):
            await resolve_target_ref(resolver, "-100123:11")


class TopicConfigTests(unittest.TestCase):
    def store(self, directory, listeners):
        path = Path(directory) / "bot_config.json"
        path.write_text(json.dumps({"settings": {}, "listeners": listeners, "keepalives": []}), encoding="utf-8")
        store = BotConfigStore(path)
        store.load()
        return store

    def test_topic_survives_reload_and_old_targets_default_to_no_topic(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, [{"source_chat_id": 10, "target_chats": [
                {"chat_id": 20, "chat_name": "Old"},
                {"chat_id": 30, "chat_name": "Forum", "topic_id": 10, "topic_name": "Preview"},
            ]}])
            reloaded = BotConfigStore(store.path)
            reloaded.load()
            targets = reloaded.get_listener(10).target_chats
            self.assertEqual([(t.chat_id, t.topic_id) for t in targets], [(20, 0), (30, 10)])
            self.assertEqual(targets[1].topic_name, "Preview")

    def test_same_chat_with_other_topic_moves_the_target(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory, [{"source_chat_id": 10, "target_chats": [{"chat_id": 30, "topic_id": 10}]}])
            _, unchanged = store.upsert_listener(ChatRef(10), [ChatRef(30, topic_id=10)])
            self.assertEqual(unchanged, [])
            rule, moved = store.upsert_listener(ChatRef(10), [ChatRef(30, topic_id=12)])
            self.assertEqual([(t.chat_id, t.topic_id) for t in rule.target_chats], [(30, 12)])
            self.assertEqual(len(moved), 1)


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
