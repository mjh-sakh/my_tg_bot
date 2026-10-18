import os
import re
from io import BytesIO
from pathlib import Path

import pytest

from bot.clients.transcription_clients import TranscribeClientTogether


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv('RUN_TOGETHER_E2E') != '1',
    reason='Set RUN_TOGETHER_E2E=1 to run the real Together transcription e2e test.',
)
async def test_real_together_transcription():
    assert os.getenv('TOGETHER_API_KEY'), 'TOGETHER_API_KEY is required.'
    # Synthetic speech: "The quick brown fox jumps over the lazy dog."
    fixture = Path(__file__).parent / 'fixtures' / 'quick_brown_fox.ogg'
    audio = BytesIO(fixture.read_bytes())
    audio.name = fixture.name
    client = TranscribeClientTogether()
    try:
        transcript = await client.transcribe(audio)
    finally:
        client.client.close()

    words = re.findall(r'\w+', transcript.lower())
    assert words == 'the quick brown fox jumps over the lazy dog'.split(), transcript
