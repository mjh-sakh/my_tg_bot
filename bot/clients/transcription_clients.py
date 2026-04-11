import asyncio
import logging
import os
from abc import ABC, abstractmethod
from io import BytesIO
from typing import Optional

import httpx
from together import Together

MODEL_NAME = os.getenv(
    'TOGETHER_TRANSCRIBE_MODEL',
    'nvidia/parakeet-tdt-0.6b-v3',
)


class BaseTranscribeClient(ABC):
    @abstractmethod
    async def transcribe(self, audio_data: BytesIO, language: Optional[str] = None, **kwargs) -> str:
        raise NotImplementedError


class TranscribeClientTogether(BaseTranscribeClient):
    def __init__(self):
        self.client = Together(api_key=os.getenv('TOGETHER_API_KEY'))
        self.model_name = MODEL_NAME

    def _transcribe_sync(self, audio_data: BytesIO, language: Optional[str] = None) -> str:
        audio_data.seek(0)
        if not getattr(audio_data, 'name', None):
            audio_data.name = 'audio.ogg'

        params = {
            'model': self.model_name,
            'file': audio_data,
        }
        if language:
            params['language'] = language

        response = self.client.audio.transcriptions.create(**params)
        if hasattr(response, 'text'):
            return response.text
        if isinstance(response, dict) and 'text' in response:
            return response['text']
        raise ValueError(f'Unexpected Together transcription response: {response!r}')

    async def transcribe(self, audio_data: BytesIO, language: Optional[str] = None, **kwargs) -> str:
        try:
            return await asyncio.to_thread(self._transcribe_sync, audio_data, language)
        except httpx.ConnectTimeout:
            logging.warning('Timeout error, trying Together transcription one more time')
            return await asyncio.to_thread(self._transcribe_sync, audio_data, language)


class AdaptiveTranscribeClient(TranscribeClientTogether):
    pass
