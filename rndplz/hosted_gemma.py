"""Opt-in local Gemma alongside the existing hosted runtime default."""
from .llm_runtime import RuntimeChatModels
from .model_conversation import ObservedRuntimeChatModels, runtime_messages
from .redis_gemma_relay import RedisGemmaRelay


class HostedGemmaModels(ObservedRuntimeChatModels):
    scoped_bridge = True

    def __init__(self, env=None, *, bridge=None, **kwargs):
        super().__init__(env, **kwargs)
        self.bridge = bridge if bridge is not None else RedisGemmaRelay(env or {}, model='gemma4:e4b')

    def _bridge_option(self):
        try:
            status = self.bridge.control('status')
            enabled = self.bridge.model in status['models'] and not status['draining']
        except ValueError:
            # A disconnected local worker must not hide the existing GPT option.
            enabled = False
        return {'id': 'bridge', 'provider': 'bridge', 'model': self.bridge.model,
                'name': self.bridge.model + ' · 운영자 PC' + ('' if enabled else ' · 연결 대기'),
                'enabled': enabled, 'local': False, 'vision': False, 'public_scope': True}

    def catalog(self, refresh=False):
        result = RuntimeChatModels.catalog(self, refresh=refresh)
        result['models'].append(self._bridge_option())
        result['public'] = True
        return result

    def get(self, identifier):
        if identifier == 'runtime':
            # Keep normal hosted requests independent of relay availability.
            return RuntimeChatModels.catalog(self)['models'][0]
        if identifier != 'bridge':
            raise ValueError('현재 연결된 모델을 선택해 주세요.')
        option = self._bridge_option()
        if not option['enabled']:
            raise ValueError('운영자 PC의 Gemma 연결을 기다리고 있습니다.')
        return option

    def has_call_capacity(self, identifier, *, provider, required_calls=1):
        if identifier == 'bridge':
            return provider == 'bridge' and type(required_calls) is int and required_calls >= 1
        return super().has_call_capacity(identifier, provider=provider, required_calls=required_calls)

    def stream(self, identifier, messages, *, contract=None):
        if identifier != 'bridge':
            yield from super().stream(identifier, messages, contract=contract)
            return
        self.get(identifier)
        messages = runtime_messages(messages, self, getattr(messages, 'runtime_dispatch_observation', None))
        with self.lock:
            self.calls['bridge'] = self.calls.get('bridge', 0) + 1
        yield from self.bridge.stream(messages, model=self.bridge.model, contract=contract)
