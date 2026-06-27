from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.locker_http import create_locker_http_app


@pytest.mark.asyncio
async def test_auth_returns_keep_going_by_default_and_notifies_admin():
    client_state = FakeSQLiteClient(restricted=False)
    bot = FakeBot()

    async with make_client(client_state, bot, admin_id=123) as http_client:
        response = await http_client.get('/locker/auth')
        response_text = await response.text()

    assert response.status == 200
    assert response_text == 'keep going'
    bot.send_message.assert_awaited_once_with(
        chat_id=123,
        text='Windows locker auth check: keep going.',
    )


@pytest.mark.asyncio
async def test_auth_returns_restricted_when_enabled():
    client_state = FakeSQLiteClient(restricted=True)
    bot = FakeBot()

    async with make_client(client_state, bot, admin_id=123) as http_client:
        response = await http_client.get('/locker/auth')
        response_text = await response.text()

    assert response.status == 200
    assert response_text == 'restricted'


@pytest.mark.asyncio
async def test_auth_notification_failure_still_returns_mode():
    client_state = FakeSQLiteClient(restricted=True)
    bot = FakeBot()
    bot.send_message.side_effect = RuntimeError('telegram down')

    async with make_client(client_state, bot, admin_id=123) as http_client:
        response = await http_client.get('/locker/auth')
        response_text = await response.text()

    assert response.status == 200
    assert response_text == 'restricted'


@pytest.mark.asyncio
async def test_logs_forward_to_admin_and_return_ok():
    client_state = FakeSQLiteClient()
    bot = FakeBot()

    async with make_client(client_state, bot, admin_id=123) as http_client:
        response = await http_client.post('/locker/logs', data=b'{"event":"test"}\n')
        response_text = await response.text()

    assert response.status == 200
    assert response_text == 'ok'
    bot.send_message.assert_awaited_once()
    sent_message = bot.send_message.await_args.kwargs
    assert sent_message['chat_id'] == 123
    assert sent_message['text']


@pytest.mark.asyncio
async def test_logs_decode_invalid_utf8_with_replacement():
    client_state = FakeSQLiteClient()
    bot = FakeBot()

    async with make_client(client_state, bot, admin_id=123) as http_client:
        response = await http_client.post('/locker/logs', data=b'bad\xffbytes')

    assert response.status == 200
    sent_text = bot.send_message.await_args.kwargs['text']
    assert 'bad\ufffdbytes' in sent_text


@pytest.mark.asyncio
async def test_logs_truncate_to_one_telegram_message():
    client_state = FakeSQLiteClient()
    bot = FakeBot()

    async with make_client(client_state, bot, admin_id=123) as http_client:
        response = await http_client.post('/locker/logs', data='x' * 10000)

    assert response.status == 200
    sent_text = bot.send_message.await_args.kwargs['text']
    assert len(sent_text) <= 4096
    assert sent_text.endswith('[truncated]')


@pytest.mark.asyncio
async def test_logs_return_non_200_when_admin_id_is_missing():
    client_state = FakeSQLiteClient()
    bot = FakeBot()

    async with make_client(client_state, bot, admin_id=0) as http_client:
        response = await http_client.post('/locker/logs', data=b'{"event":"test"}\n')

    assert response.status == 503
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_logs_return_non_200_when_forwarding_fails():
    client_state = FakeSQLiteClient()
    bot = FakeBot()
    bot.send_message.side_effect = RuntimeError('telegram down')

    async with make_client(client_state, bot, admin_id=123) as http_client:
        response = await http_client.post('/locker/logs', data=b'{"event":"test"}\n')

    assert response.status == 502


class make_client:
    def __init__(self, sqlite_client, bot, admin_id):
        self._app = create_locker_http_app(
            bot,
            sqlite_client=sqlite_client,
            admin_id=admin_id,
        )
        self._client = TestClient(TestServer(self._app))

    async def __aenter__(self):
        await self._client.start_server()
        return self._client

    async def __aexit__(self, exc_type, exc, tb):
        await self._client.close()


class FakeBot:
    def __init__(self):
        self.send_message = AsyncMock()


class FakeSQLiteClient:
    def __init__(self, restricted=False):
        self.restricted = restricted

    def get_locker_restricted(self):
        return self.restricted
