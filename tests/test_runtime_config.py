import tempfile
import unittest
from pathlib import Path

from runtime_config import load_openai_environment, read_env_file


class PrivateConfigurationTests(unittest.TestCase):
    def test_shared_credentials_without_inheriting_sibling_model(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            (parent / 'tools').mkdir()
            (parent / 'tools' / '.env').write_text(
                'OPENAI_API_KEY=synthetic-shared\nOPENAI_MODEL=sibling-model\n'
                'OPENAI_PROJECT=synthetic-project\nUNRELATED_SECRET=ignore\n')
            root = parent / 'house'
            root.mkdir()
            result = load_openai_environment(root, {})
            self.assertEqual(result, {'OPENAI_API_KEY': 'synthetic-shared',
                                      'OPENAI_PROJECT': 'synthetic-project'})
            (root / '.env').write_text('OPENAI_API_KEY=synthetic-local\nHOUSE_OPENAI_MODEL=house-model\n')
            result = load_openai_environment(root, {'OPENAI_PROJECT': 'process-project'})
            self.assertEqual(result['OPENAI_API_KEY'], 'synthetic-local')
            self.assertEqual(result['OPENAI_PROJECT'], 'process-project')
            self.assertEqual(result['HOUSE_OPENAI_MODEL'], 'house-model')
            result = load_openai_environment(root, {'OPENAI_API_KEY': 'synthetic-process'})
            self.assertEqual(result['OPENAI_API_KEY'], 'synthetic-process')

    def test_explicit_relative_file_and_literal_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('OPENAI_ENV_FILE=shared.env\n')
            (root / 'shared.env').write_text(
                '\ufeffexport OPENAI_API_KEY="synthetic # literal" # comment\n'
                "OPENAI_ORG_ID='$(never-execute)'\nBROKEN='unterminated\n", encoding='utf-8')
            result = load_openai_environment(root, {})
            self.assertEqual(result['OPENAI_API_KEY'], 'synthetic # literal')
            self.assertEqual(result['OPENAI_ORG_ID'], '$(never-execute)')
            self.assertNotIn('BROKEN', read_env_file(root / 'shared.env'))
            self.assertEqual(read_env_file(root / 'missing'), {})


if __name__ == '__main__':
    unittest.main()
