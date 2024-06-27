import logging
import os
from abc import ABC, abstractmethod
from functools import lru_cache
from io import BytesIO
from typing import Optional

import httpx
import magic
import openai
import replicate
import requests

MODEL_NAME = os.getenv('WHISPER_REPLICATE_MODEL_NAME', 'vaibhavs10/incredibly-fast-whisper')
REPLICATE_API_SIZE_LIMIT = float(os.getenv('REPLICATE_API_SIZE_LIMIT', 2))  # in MB
REPLICATE_MIN_DURATION_LIMIT = int(os.getenv('REPLICATE_MIN_DURATION_LIMIT', 10))  # in sec


@lru_cache  # TODO: need to have TTL because versions change over time
def get_replicate_model_versions(model_owner: str, model_name: str) -> list[dict]:
    versions_uri = 'https://api.replicate.com/v1/models/{model_owner}/{model_name}/versions'
    headers = {'Authorization': f'Bearer {os.getenv("REPLICATE_API_TOKEN")}'}
    logging.info(f'Getting Replicate model versions for {model_owner}/{model_name}')
    resp = requests.get(versions_uri.format(model_owner=model_owner, model_name=model_name), headers=headers)
    if resp.status_code != 200:  # make sure to change caching strategy if not raising error
        raise ValueError(f'Error getting model versions: {resp.text}')
    model_versions = resp.json()['results']
    return model_versions


class BaseTranscribeClient(ABC):
    @abstractmethod
    async def transcribe(self, audio_data: BytesIO, language: Optional[str] = None, **kwargs) -> str:
        raise NotImplementedError


class TranscribeClientReplicate(BaseTranscribeClient):
    """
    Replicate client has file size limitation
    https://github.com/replicate/replicate-python/issues/135
    """

    def __init__(self):
        model_owner = MODEL_NAME.split('/')[0]
        model_name = MODEL_NAME.split('/')[1]
        model_version = get_replicate_model_versions(model_owner, model_name)[0]['id']
        self.model_name = f'{model_owner}/{model_name}:{model_version}'

    async def transcribe(self, audio_data: BytesIO, language: Optional[str] = None, **kwargs) -> str:
        input_ = {
            'task': 'transcribe',
            'audio': audio_data,
        }
        if language:
            input_['language'] = language
        try:
            output = await replicate.async_run(self.model_name, input=input_)
        except httpx.ConnectTimeout:  # trying one more time
            logging.warning('Timeout error, trying one more time')
            output = await replicate.async_run(self.model_name, input=input_)
        return output['text']


class TranscribeClientOpenAi(BaseTranscribeClient):
    def __init__(self):
        self.client = openai.AsyncClient()

    async def transcribe(self, audio_data: BytesIO, language: Optional[str] = None, **kwargs) -> str:
        audio_data.seek(0)
        mime_type = magic.from_buffer(audio_data.read(2048), mime=True)
        audio_data.seek(0)
        file = ('file', audio_data.getvalue(), mime_type)
        transcript = await self.client.audio.transcriptions.create(
            model="whisper-1",
            file=file,
            response_format="text"
        )
        return transcript


class AdaptiveTranscribeClient(BaseTranscribeClient):
    @staticmethod
    async def transcribe(audio_data: BytesIO, language: Optional[str] = None, **kwargs) -> str:
        size_mb = audio_data.getbuffer().nbytes / 1024 ** 2
        duration = kwargs.get('duration')
        logging.info(f'Audio size: {size_mb} MB; duration: {duration} sec.')
        if size_mb < REPLICATE_API_SIZE_LIMIT and (duration is None or duration > REPLICATE_MIN_DURATION_LIMIT):
            return await TranscribeClientReplicate().transcribe(audio_data, language=language)
        else:
            return await TranscribeClientOpenAi().transcribe(audio_data, language=language)
