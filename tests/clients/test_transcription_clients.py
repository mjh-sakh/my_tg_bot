from io import BytesIO
from unittest.mock import AsyncMock

import pytest

from bot.clients import transcription_clients


@pytest.mark.asyncio
async def test_replicate_client_uses_parakeet_payload(monkeypatch):
    monkeypatch.setattr(transcription_clients, 'MODEL_NAME', 'nvidia/parakeet-rnnt-1.1b')
    monkeypatch.setattr(
        transcription_clients,
        'get_replicate_model_versions',
        lambda owner, name: [{'id': 'version-123'}],
    )
    async_run = AsyncMock(return_value='transcribed text')
    monkeypatch.setattr(transcription_clients.replicate, 'async_run', async_run)

    client = transcription_clients.TranscribeClientReplicate()
    audio_data = BytesIO(b'audio-bytes')

    transcript = await client.transcribe(audio_data)

    assert transcript == 'transcribed text'
    async_run.assert_awaited_once()
    model_name = async_run.await_args.args[0]
    payload = async_run.await_args.kwargs['input']
    assert model_name == 'nvidia/parakeet-rnnt-1.1b:version-123'
    assert payload['audio_file'] is audio_data


@pytest.mark.asyncio
async def test_replicate_client_retries_once_on_timeout(monkeypatch):
    monkeypatch.setattr(transcription_clients, 'MODEL_NAME', 'nvidia/parakeet-rnnt-1.1b')
    monkeypatch.setattr(
        transcription_clients,
        'get_replicate_model_versions',
        lambda owner, name: [{'id': 'version-123'}],
    )
    async_run = AsyncMock(
        side_effect=[transcription_clients.httpx.ConnectTimeout('timeout'), 'retry success']
    )
    monkeypatch.setattr(transcription_clients.replicate, 'async_run', async_run)

    client = transcription_clients.TranscribeClientReplicate()

    transcript = await client.transcribe(BytesIO(b'audio-bytes'))

    assert transcript == 'retry success'
    assert async_run.await_count == 2
