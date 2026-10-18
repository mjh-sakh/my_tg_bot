import pytest

from bot.handlers.gpt_handlers import llm


@pytest.mark.parametrize('effort', [None, '', '   '])
def test_reasoning_effort_omitted_by_default(monkeypatch, effort):
    monkeypatch.setenv('OPENROUTER_KEY', 'test-key')
    if effort is None:
        monkeypatch.delenv('REASONING_EFFORT', raising=False)
    else:
        monkeypatch.setenv('REASONING_EFFORT', effort)

    client = llm(model='x-ai/grok-4.3')

    assert 'extra_body' not in client._get_model_kwargs()


@pytest.mark.parametrize('effort', ['low', 'medium', 'high', 'xhigh', 'none'])
def test_reasoning_effort_sent_in_openrouter_extra_body(monkeypatch, effort):
    monkeypatch.setenv('OPENROUTER_KEY', 'test-key')
    monkeypatch.setenv('REASONING_EFFORT', f' {effort} ')

    client = llm(model='x-ai/grok-4.3')

    assert client._get_model_kwargs()['extra_body'] == {'reasoning': {'effort': effort}}


def test_reasoning_effort_preserves_other_options(monkeypatch):
    monkeypatch.setenv('OPENROUTER_KEY', 'test-key')
    monkeypatch.setenv('REASONING_EFFORT', 'low')
    options = {
        'extra_body': {
            'provider': {'allow_fallbacks': False},
            'reasoning': {'exclude': True},
        },
        'seed': 42,
    }

    client = llm(model='x-ai/grok-4.3', additional_kwargs=options)
    payload = client._get_model_kwargs()

    assert payload['extra_body'] == {
        'provider': {'allow_fallbacks': False},
        'reasoning': {'exclude': True, 'effort': 'low'},
    }
    assert payload['seed'] == 42
    assert options['extra_body']['reasoning'] == {'exclude': True}
