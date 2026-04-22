from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.clients.sqlite_client import SQLiteClient
from bot.handlers import gpt_handlers, voice_handler
from bot.handlers.security import Feature, Role


class DummyReplyMessage:
    def __init__(self, *, chat_id: int, message_id: int, text: str):
        self.chat_id = chat_id
        self.message_id = message_id
        self.text = text
        self.edit_text = AsyncMock(side_effect=self._edit_text)
        self.delete = AsyncMock()

    async def _edit_text(self, text, **kwargs):
        self.text = text
        return self


class DummyMessage:
    def __init__(
        self,
        *,
        voice=None,
        audio=None,
        message_id=123,
        chat_id=55,
        forward_origin=None,
        is_automatic_forward=False,
        from_user=None,
    ):
        self.voice = voice
        self.audio = audio
        self.message_id = message_id
        self.chat_id = chat_id
        self.forward_origin = forward_origin
        self.is_automatic_forward = is_automatic_forward
        self.from_user = from_user or SimpleNamespace(id=123456)
        self.reply_to_message = None
        self.reply_text = AsyncMock(side_effect=self._reply_text)
        self._next_reply_message_id = message_id + 1
        self.sent_replies = []

    async def _reply_text(self, text, **kwargs):
        reply = DummyReplyMessage(
            chat_id=self.chat_id,
            message_id=self._next_reply_message_id,
            text=text,
        )
        self.sent_replies.append(reply)
        self._next_reply_message_id += 1
        return reply


@pytest.mark.asyncio
async def test_handle_voice_replies_with_transcript_chunks():
    file_handle = SimpleNamespace(download_to_memory=AsyncMock(side_effect=lambda buffer: buffer.write(b'audio')))
    bot = SimpleNamespace(get_file=AsyncMock(return_value=file_handle))
    context = SimpleNamespace(bot=bot)
    client = SimpleNamespace(transcribe=AsyncMock(return_value='x' * 5000))
    message = DummyMessage(voice=SimpleNamespace(file_id='file-1', duration=12))
    update = SimpleNamespace(message=message, effective_user=message.from_user)

    await voice_handler.handle_voice(update, context, client)

    client.transcribe.assert_awaited_once()
    assert message.reply_text.await_count == 2
    first_call = message.reply_text.await_args_list[0]
    second_call = message.reply_text.await_args_list[1]
    assert len(first_call.args[0]) == 4096
    assert len(second_call.args[0]) == 904


@pytest.mark.asyncio
async def test_handle_voice_reports_transcription_errors():
    file_handle = SimpleNamespace(download_to_memory=AsyncMock(side_effect=lambda buffer: buffer.write(b'audio')))
    bot = SimpleNamespace(get_file=AsyncMock(return_value=file_handle))
    context = SimpleNamespace(bot=bot)
    client = SimpleNamespace(transcribe=AsyncMock(side_effect=RuntimeError('boom')))
    message = DummyMessage(voice=SimpleNamespace(file_id='file-1', duration=12))
    update = SimpleNamespace(message=message, effective_user=message.from_user)

    await voice_handler.handle_voice(update, context, client)

    message.reply_text.assert_awaited_once()
    assert 'Ошибочка: boom' in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_voice_stores_canonical_and_alias_history_and_generates_assistant_reply(
    tmp_path,
    monkeypatch,
):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    client.upsert_user(123456, Role.user.value)
    client.enable_feature(123456, Feature.chat.value)
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)
    monkeypatch.setattr(voice_handler, 'find_role', AsyncMock(return_value=Role.user))
    monkeypatch.setattr(voice_handler, 'has_feature', AsyncMock(return_value=True))
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: FakeLLM('assistant reply'))
    monkeypatch.setattr(gpt_handlers, 'now', Clock([0.0, 2.0, 2.0]))

    file_handle = SimpleNamespace(download_to_memory=AsyncMock(side_effect=lambda buffer: buffer.write(b'audio')))
    bot = SimpleNamespace(get_file=AsyncMock(return_value=file_handle))
    context = SimpleNamespace(bot=bot)
    transcribe_client = SimpleNamespace(transcribe=AsyncMock(return_value='voice transcript'))
    message = DummyMessage(voice=SimpleNamespace(file_id='file-1', duration=12), message_id=100)
    update = SimpleNamespace(message=message, effective_user=message.from_user)

    await voice_handler.handle_voice(update, context, transcribe_client)

    assert message.reply_text.await_count == 2
    transcript_call = message.reply_text.await_args_list[0]
    assistant_call = message.reply_text.await_args_list[1]
    assert transcript_call.args[0] == 'voice transcript'
    assert assistant_call.args[0] == '...🤔'
    assert message.sent_replies[1].edit_text.await_args_list[-1].args[0] == 'assistant reply'

    canonical_record = client.get_history_record(message.chat_id, 100)
    alias_record = client.get_history_record(message.chat_id, 101)
    assistant_record = client.get_history_record(message.chat_id, 102)

    assert canonical_record is not None
    assert canonical_record['text'] == 'voice transcript'
    assert canonical_record['canonical_message_id'] == 100

    assert alias_record is not None
    assert alias_record['canonical_message_id'] == 100
    assert alias_record['text'] is None

    assert assistant_record is not None
    assert assistant_record['reply_message_id'] == 100


@pytest.mark.asyncio
async def test_handle_voice_stores_all_transcript_chunks_and_reply_to_last_chunk_continues_chain(
    tmp_path,
    monkeypatch,
):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    client.upsert_user(123456, Role.user.value)
    client.enable_feature(123456, Feature.chat.value)
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)
    monkeypatch.setattr(voice_handler, 'find_role', AsyncMock(return_value=Role.user))
    monkeypatch.setattr(voice_handler, 'has_feature', AsyncMock(return_value=True))

    fake_llm = FakeLLM('assistant reply')
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)
    monkeypatch.setattr(gpt_handlers, 'now', Clock([0.0, 2.0, 2.0]))

    transcript = 'x' * 9000
    file_handle = SimpleNamespace(download_to_memory=AsyncMock(side_effect=lambda buffer: buffer.write(b'audio')))
    bot = SimpleNamespace(get_file=AsyncMock(return_value=file_handle))
    context = SimpleNamespace(bot=bot)
    transcribe_client = SimpleNamespace(transcribe=AsyncMock(return_value=transcript))
    voice_message = DummyMessage(voice=SimpleNamespace(file_id='file-1', duration=12), message_id=100)
    voice_update = SimpleNamespace(message=voice_message, effective_user=voice_message.from_user)

    await voice_handler.handle_voice(voice_update, context, transcribe_client)

    transcript_chunk_records = [
        client.get_history_record(voice_message.chat_id, 101),
        client.get_history_record(voice_message.chat_id, 102),
        client.get_history_record(voice_message.chat_id, 103),
    ]
    assert [record is not None for record in transcript_chunk_records] == [True, True, True]
    assert [record['canonical_message_id'] for record in transcript_chunk_records] == [100, 100, 100]
    canonical_record = client.get_history_record(voice_message.chat_id, 100)
    assert canonical_record is not None
    assert canonical_record['text'] == transcript

    assert [record['text'] for record in transcript_chunk_records] == [None, None, None]

    follow_up_message = SimpleNamespace(
        chat_id=55,
        message_id=200,
        text='follow-up to the last visible transcript chunk',
        reply_to_message=SimpleNamespace(chat_id=55, message_id=103),
        reply_text=AsyncMock(return_value=DummyReplyMessage(chat_id=55, message_id=201, text='...🤔')),
    )
    follow_up_update = SimpleNamespace(message=follow_up_message)

    await gpt_handlers.handle_text_chat(follow_up_update, object())

    sent_messages = fake_llm.calls[-1]
    assert [entry.content for entry in sent_messages] == [
        gpt_handlers.SYSTEM_PROMPT,
        transcript,
        'follow-up to the last visible transcript chunk',
    ]


@pytest.mark.asyncio
async def test_handle_voice_skips_ai_chat_for_forwarded_messages(tmp_path, monkeypatch):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)
    fake_llm = FakeLLM('assistant reply')
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)

    file_handle = SimpleNamespace(download_to_memory=AsyncMock(side_effect=lambda buffer: buffer.write(b'audio')))
    bot = SimpleNamespace(get_file=AsyncMock(return_value=file_handle))
    context = SimpleNamespace(bot=bot)
    transcribe_client = SimpleNamespace(transcribe=AsyncMock(return_value='forwarded transcript'))
    message = DummyMessage(
        voice=SimpleNamespace(file_id='file-1', duration=12),
        message_id=100,
        forward_origin=SimpleNamespace(type='user'),
    )
    update = SimpleNamespace(message=message, effective_user=message.from_user)

    await voice_handler.handle_voice(update, context, transcribe_client)

    message.reply_text.assert_awaited_once()
    assert client.get_history_record(message.chat_id, 100) is None
    assert fake_llm.calls == []


@pytest.mark.asyncio
async def test_reply_to_transcript_alias_continues_same_canonical_chain(tmp_path, monkeypatch):
    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)

    await gpt_handlers.write_history_record(
        chat_id=55,
        message_id=100,
        canonical_message_id=100,
        text='voice transcript',
        role='user',
    )
    await gpt_handlers.write_history_record(
        chat_id=55,
        message_id=101,
        canonical_message_id=100,
        text=None,
        reply_chat_id=55,
        reply_message_id=100,
        role='user',
    )
    await gpt_handlers.write_history_record(
        chat_id=55,
        message_id=102,
        canonical_message_id=102,
        text='assistant reply',
        reply_chat_id=55,
        reply_message_id=100,
        role='assistant',
    )

    fake_llm = FakeLLM('voice follow-up reply')
    monkeypatch.setattr(gpt_handlers, 'llm', lambda: fake_llm)
    monkeypatch.setattr(gpt_handlers, 'now', Clock([0.0, 2.0, 2.0]))
    monkeypatch.setattr(voice_handler, 'find_role', AsyncMock(return_value=Role.user))
    monkeypatch.setattr(voice_handler, 'has_feature', AsyncMock(return_value=True))

    file_handle = SimpleNamespace(download_to_memory=AsyncMock(side_effect=lambda buffer: buffer.write(b'audio')))
    bot = SimpleNamespace(get_file=AsyncMock(return_value=file_handle))
    context = SimpleNamespace(bot=bot)
    transcribe_client = SimpleNamespace(transcribe=AsyncMock(return_value='voice follow-up'))
    message = DummyMessage(
        voice=SimpleNamespace(file_id='file-1', duration=12),
        message_id=103,
    )
    message.reply_to_message = SimpleNamespace(chat_id=55, message_id=101)
    update = SimpleNamespace(message=message, effective_user=message.from_user)

    await voice_handler.handle_voice(update, context, transcribe_client)

    sent_messages = fake_llm.calls[0]
    assert [entry.content for entry in sent_messages] == [
        gpt_handlers.SYSTEM_PROMPT,
        'voice transcript',
        'voice follow-up',
    ]

    follow_up_record = client.get_history_record(55, 103)
    assert follow_up_record is not None
    assert follow_up_record['reply_message_id'] == 100


class Clock:
    def __init__(self, values):
        self.values = list(values)
        self.last = values[-1] if values else 0.0

    def __call__(self):
        if self.values:
            self.last = self.values.pop(0)
        return self.last


class FakeLLM:
    def __init__(self, content: str):
        self.streams = [[content]]
        self.calls = []

    async def astream_chat(self, *, messages):
        self.calls.append(messages)
        stream = self.streams.pop(0)
        for chunk in stream:
            yield SimpleNamespace(delta=chunk)
        yield SimpleNamespace(delta='', raw={'usage': {'total_tokens': 1}})
