"""Native menus contain enabled aliases and keep each model's served budget."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/common'))
import harness_config
import unified_config
from test_unified import MODELS


class NativeConfigTest(unittest.TestCase):
    def test_opencode_uses_responses_for_gpt_and_local_qwen(self):
        models = [*MODELS, {**MODELS[2], 'id': 'team/gpt-6-luna', 'model': 'gpt-6-luna'},
                  {**MODELS[2], 'id': 'team/other', 'model': 'other-chat-model'}]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            outputs = harness_config.files(home,
                unified_config.catalog(models, 'openai')['data'],
                unified_config.catalog(models, 'anthropic')['data'], 8080, 8081)
            providers = json.loads(outputs[home / '.config/opencode/opencode.json'])['provider']
            openai = providers['praxis-openai']
            self.assertEqual(openai['npm'], '@ai-sdk/openai-compatible')
            for alias in ('vllm/qwen3-8b', 'openai/gpt-5.4-mini', 'team/gpt-5.4-mini', 'team/gpt-6-luna'):
                model = openai['models'][alias]
                self.assertEqual(model['provider']['npm'], '@ai-sdk/openai')
                self.assertEqual(model['options']['include'], ['reasoning.encrypted_content'])
                self.assertFalse(model['options']['store'])
                self.assertTrue(model['reasoning'])
                self.assertNotIn('interleaved', model)
            self.assertNotIn('provider', openai['models']['team/other'])
            self.assertEqual(providers['praxis-messages']['npm'], '@ai-sdk/anthropic')

    def test_native_files_share_listener_and_keep_per_model_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            outputs = harness_config.files(home,
                unified_config.catalog([m for m in MODELS if 'openai' in m['apis']], 'openai')['data'],
                unified_config.catalog([m for m in MODELS if 'anthropic' in m['apis']], 'anthropic')['data'],
                8080, 8081)
            codex = outputs[home / '.codex/praxis.config.toml']
            self.assertIn('http://127.0.0.1:8080/v1', codex)
            self.assertNotIn('model_context_window', codex)
            catalog = json.loads(outputs[home / '.codex/model-catalogs/praxis.json'])['models']
            self.assertEqual([m['context_window'] for m in catalog], [16384, 128000, 128000])
            claude = json.loads(outputs[home / '.claude/settings.json'])
            self.assertEqual(claude['env']['CLAUDE_CODE_MAX_CONTEXT_TOKENS'], '16384')
            self.assertEqual(claude['permissions']['defaultMode'], 'default')
            self.assertEqual(len(claude['modelPicker']['options']), 2)
            self.assertNotIn('CLAUDE_CODE_DISABLE_THINKING', claude['env'])
            opencode = json.loads(outputs[home / '.config/opencode/opencode.json'])
            self.assertEqual(opencode['enabled_providers'], ['praxis-openai', 'praxis-messages'])
            self.assertNotIn('/providers/', str(outputs))


if __name__ == '__main__':
    unittest.main()
