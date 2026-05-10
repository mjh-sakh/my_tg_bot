import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.clients.sqlite_client import SQLiteClient
from bot.handlers import gpt_handlers, security
from bot.handlers.security import Feature, Role

pytestmark = pytest.mark.asyncio


class SpyLLM:
    def __init__(self, real_llm, *, captured_messages):
        self.real_llm = real_llm
        self.captured_messages = captured_messages

    async def astream_chat(self, *, messages):
        self.captured_messages.append(messages)
        stream = self.real_llm.astream_chat(messages=messages)
        if hasattr(stream, '__aiter__'):
            async for chunk in stream:
                yield chunk
            return
        stream = await stream
        async for chunk in stream:
            yield chunk


class SpyLLMFactory:
    def __init__(self, real_factory):
        self.real_factory = real_factory
        self.calls = []
        self.message_batches = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return SpyLLM(self.real_factory(**kwargs), captured_messages=self.message_batches)


@pytest.mark.skipif(
    os.getenv('RUN_OPENROUTER_E2E') != '1',
    reason='Set RUN_OPENROUTER_E2E=1 to run the real OpenRouter chat e2e test.',
)
async def test_real_grok_openrouter_branch_thread_reuses_same_affinity_header(tmp_path, monkeypatch):
    openrouter_key = os.getenv('OPENROUTER_KEY')
    if not openrouter_key:
        pytest.skip('OPENROUTER_KEY is not configured.')

    grok_model = os.getenv('OPENROUTER_GROK_MODEL') or os.getenv('DEFAULT_MODEL') or 'x-ai/grok-3-mini'
    if not gpt_handlers.is_grok_model(grok_model):
        pytest.skip(f'Configured e2e model is not a Grok model: {grok_model}')

    client = SQLiteClient(tmp_path / 'bot.sqlite')
    client.init_db()
    client.upsert_user(123456, Role.user.value)
    client.enable_feature(123456, Feature.chat.value)

    monkeypatch.setattr(gpt_handlers, 'SQLiteClient', lambda: client)
    monkeypatch.setattr(security, 'SQLiteClient', lambda: client)
    monkeypatch.setattr(security, 'ADMIN_ID', 0)
    monkeypatch.setattr(gpt_handlers, 'DEFAULT_MODEL', grok_model)
    monkeypatch.setattr(gpt_handlers, 'now', lambda: 10.0)

    real_llm = gpt_handlers.llm
    llm_factory = SpyLLMFactory(real_llm)
    monkeypatch.setattr(gpt_handlers, 'llm', llm_factory)

    wrapped = security.authorize_func(
        gpt_handlers.handle_text_chat,
        required_feature=Feature.chat,
    )

    root_bot_reply = SimpleNamespace(chat_id=999, message_id=200, edit_text=AsyncMock(), delete=AsyncMock())
    root_message = SimpleNamespace(
        chat_id=999,
        message_id=100,
        text='Reply in exactly three words: root prompt acknowledged',
        reply_to_message=None,
        reply_text=AsyncMock(return_value=root_bot_reply),
        from_user=SimpleNamespace(id=123456),
    )
    await wrapped(SimpleNamespace(message=root_message, effective_user=SimpleNamespace(id=123456)), object())

    branch_one_bot_reply = SimpleNamespace(chat_id=999, message_id=201, edit_text=AsyncMock(), delete=AsyncMock())
    branch_one_message = SimpleNamespace(
        chat_id=999,
        message_id=101,
        text='Reply in exactly three words: first branch acknowledged',
        reply_to_message=SimpleNamespace(chat_id=999, message_id=100),
        reply_text=AsyncMock(return_value=branch_one_bot_reply),
        from_user=SimpleNamespace(id=123456),
    )
    await wrapped(SimpleNamespace(message=branch_one_message, effective_user=SimpleNamespace(id=123456)), object())

    branch_two_bot_reply = SimpleNamespace(chat_id=999, message_id=202, edit_text=AsyncMock(), delete=AsyncMock())
    branch_two_message = SimpleNamespace(
        chat_id=999,
        message_id=102,
        text='Reply in exactly three words: second branch acknowledged',
        reply_to_message=SimpleNamespace(chat_id=999, message_id=100),
        reply_text=AsyncMock(return_value=branch_two_bot_reply),
        from_user=SimpleNamespace(id=123456),
    )
    await wrapped(SimpleNamespace(message=branch_two_message, effective_user=SimpleNamespace(id=123456)), object())

    expected_headers = {
        'x-grok-conv-id': gpt_handlers.build_grok_conv_id(chat_id=999, root_message_id=100)
    }
    assert llm_factory.calls == [
        {'model': grok_model, 'default_headers': expected_headers},
        {'model': grok_model, 'default_headers': expected_headers},
        {'model': grok_model, 'default_headers': expected_headers},
    ]

    assert [message.content for message in llm_factory.message_batches[1]] == [
        gpt_handlers.SYSTEM_PROMPT,
        root_message.text,
        branch_one_message.text,
    ]
    assert [message.content for message in llm_factory.message_batches[2]] == [
        gpt_handlers.SYSTEM_PROMPT,
        root_message.text,
        branch_two_message.text,
    ]

    for telegram_message in [root_message, branch_one_message, branch_two_message]:
        telegram_message.reply_text.assert_awaited_once()
        reply_args = telegram_message.reply_text.await_args
        assert reply_args.kwargs['parse_mode'] == 'HTML'
        assert reply_args.args[0].strip()

    assert branch_one_bot_reply.edit_text.await_count >= 1
    assert branch_two_bot_reply.edit_text.await_count >= 1
    assert client.get_history_record(999, 201)['text'].strip()
    assert client.get_history_record(999, 202)['text'].strip()
