from io import BytesIO
from types import SimpleNamespace

import pytest

from bot.clients import transcription_clients


@pytest.mark.asyncio
async def test_together_client_uses_parakeet_model_and_audio_file(monkeypatch):
    monkeypatch.setattr(transcription_clients, 'MODEL_NAME', 'nvidia/parakeet-tdt-0.6b-v3')

    class DummyTogether:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.audio = SimpleNamespace(
                transcriptions=SimpleNamespace(create=self.create)
            )
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(text='transcribed text')

    monkeypatch.setattr(transcription_clients, 'Together', DummyTogether)

    client = transcription_clients.TranscribeClientTogether()
    audio_data = BytesIO(b'audio-bytes')

    transcript = await client.transcribe(audio_data)

    assert transcript == 'transcribed text'
    assert len(client.client.calls) == 1
    call = client.client.calls[0]
    assert call['model'] == 'nvidia/parakeet-tdt-0.6b-v3'
    assert call['file'] is audio_data
    assert audio_data.name == 'audio.ogg'


@pytest.mark.asyncio
async def test_together_client_retries_once_on_timeout(monkeypatch):
    monkeypatch.setattr(transcription_clients, 'MODEL_NAME', 'nvidia/parakeet-tdt-0.6b-v3')

    class DummyTogether:
        def __init__(self, api_key=None):
            self.calls = 0
            self.audio = SimpleNamespace(
                transcriptions=SimpleNamespace(create=self.create)
            )

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise transcription_clients.httpx.ConnectTimeout('timeout')
            return {'text': 'retry success'}

    monkeypatch.setattr(transcription_clients, 'Together', DummyTogether)

    client = transcription_clients.TranscribeClientTogether()

    transcript = await client.transcribe(BytesIO(b'audio-bytes'))

    assert transcript == 'retry success'
    assert client.client.calls == 2
