import logging
import os
from abc import ABC, abstractmethod
from functools import lru_cache
from io import BytesIO
from typing import Optional

import httpx
import replicate
import requests

MODEL_NAME = os.getenv('REPLICATE_TRANSCRIBE_MODEL') or os.getenv(
    'WHISPER_REPLICATE_MODEL_NAME',
    'nvidia/parakeet-rnnt-1.1b',
)


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
    def __init__(self):
        model_owner, model_name = MODEL_NAME.split('/', maxsplit=1)
        model_version = get_replicate_model_versions(model_owner, model_name)[0]['id']
        self.model_name = f'{model_owner}/{model_name}:{model_version}'

    async def transcribe(self, audio_data: BytesIO, language: Optional[str] = None, **kwargs) -> str:
        audio_data.seek(0)
        input_ = {
            'audio_file': audio_data,
        }
        try:
            output = await replicate.async_run(self.model_name, input=input_)
        except httpx.ConnectTimeout:  # trying one more time
            logging.warning('Timeout error, trying one more time')
            output = await replicate.async_run(self.model_name, input=input_)
        return output


class AdaptiveTranscribeClient(TranscribeClientReplicate):
    pass
