"""Run with unittest on a clean Linux runner, without the app or Qt installed."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('ci_checks', Path(__file__).resolve().parents[1] / 'tools/ci_checks.py')
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)


class ChangeChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'ci@example.test')
        self.git('config', 'user.name', 'CI fixture')
        self.git('config', 'core.autocrlf', 'false')
        self.write('README.md', '# Example\n')
        self.write('src/app.py', 'pass\n')
        self.base = self.commit()

    def git(self, *args):
        return ci.git(self.root, *args).decode().strip()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def commit(self):
        self.git('add', '-A')
        self.git('commit', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def push_plan(self, base=None):
        return ci.make_plan(self.root, 'push', {'before': base or self.base, 'after': self.commit()})

    def errors(self, plan):
        with contextlib.redirect_stdout(io.StringIO()):
            return ci.check_docs(self.root, plan)

    def test_readmes_guides_and_images_skip_windows(self):
        self.write('README.md', '# Example\n\n[guide](docs/guide.md)\n')
        self.write('docs/guide.md', '![cat](cat.svg)\n')
        self.write('docs/cat.svg', '<svg xmlns="http://www.w3.org/2000/svg"/>\n')
        plan = self.push_plan()
        self.assertFalse(plan['windows'])
        self.assertEqual(self.errors(plan), [])

    def test_non_documentation_and_packaged_text_require_windows(self):
        for path in ('src/app.py', 'src/readme.md', 'tests/test_app.py', 'tools/helper.py',
                     'packaging/licenses/NOTICE.txt', 'requirements-lock.txt', 'pyproject.toml',
                     '.github/workflows/checks.yml', 'LICENSE', 'unknown.config',
                     'docs/demo.py', 'docs/privacy-policy.md', 'docs/privacy-policy.en.md',
                     'docs/licensing/SOURCES.md'):
            with self.subTest(path=path):
                self.assertFalse(ci.documentation_only(path))

    def test_mixed_change_requires_windows(self):
        self.write('docs/guide.md', '# Guide\n')
        self.write('src/app.py', 'print(1)\n')
        self.assertTrue(self.push_plan()['windows'])

    def test_code_renamed_to_documentation_requires_windows(self):
        (self.root / 'src/app.py').rename(self.root / 'README.en.md')
        plan = self.push_plan()
        self.assertTrue(plan['windows'])
        self.assertIn('src/app.py', plan['changed'])
        self.assertIn('README.en.md', plan['changed'])

    def test_code_deletion_requires_windows(self):
        (self.root / 'src/app.py').unlink()
        self.assertTrue(self.push_plan()['windows'])

    def test_push_checks_every_commit_not_only_the_last(self):
        self.write('src/app.py', 'print(1)\n')
        self.commit()
        self.write('README.md', '# Final docs commit\n')
        self.assertTrue(self.push_plan()['windows'])

    def test_pull_request_uses_merge_base_not_unrelated_main_change(self):
        self.git('checkout', '-qb', 'topic')
        self.write('README.md', '# Branch docs\n')
        head = self.commit()
        self.git('checkout', '-q', 'main')
        self.write('src/app.py', 'print(2)\n')
        base_tip = self.commit()
        self.git('checkout', '-q', 'topic')
        plan = ci.make_plan(self.root, 'pull_request', {
            'pull_request': {'base': {'sha': base_tip}, 'head': {'sha': head}}})
        self.assertFalse(plan['windows'])
        self.assertEqual(plan['base'], self.base)
        self.assertEqual(plan['changed'], ['README.md'])

    def test_no_changed_file_limit(self):
        for index in range(305):
            self.write(f'docs/{index:03}.md', '# Guide\n')
        self.write('zzz-build.config', 'changed\n')
        plan = self.push_plan()
        self.assertEqual(len(plan['changed']), 306)
        self.assertTrue(plan['windows'])

    def test_manual_missing_base_and_empty_diff_require_windows(self):
        events = [
            ('workflow_dispatch', {}),
            ('push', {'before': '0' * 40, 'after': self.base}),
            ('push', {'before': 'a' * 40, 'after': self.base}),
            ('push', {'before': self.base, 'after': self.base}),
            ('pull_request', {}),
        ]
        for name, event in events:
            with self.subTest(event=event):
                self.assertTrue(ci.make_plan(self.root, name, event)['windows'])

    def test_broken_link_and_html_image_fail(self):
        self.write('README.md', '[missing](docs/missing.md)\n<img src="docs/missing.png">\n')
        errors = self.errors(self.push_plan())
        self.assertEqual(len(errors), 2)
        self.assertIn('docs/missing.md', '\n'.join(errors))
        self.assertIn('docs/missing.png', '\n'.join(errors))

    def test_deleted_asset_is_checked_from_unchanged_document(self):
        self.write('docs/image.svg', '<svg/>\n')
        self.write('README.md', '![image](docs/image.svg)\n')
        base = self.commit()
        (self.root / 'docs/image.svg').unlink()
        self.assertIn('missing local target', self.errors(self.push_plan(base))[0])

    def test_external_links_code_examples_and_anchors_do_not_use_network(self):
        self.write('README.md', '''# Example
[web](https://example.invalid/no-network) [heading](#example)
`[inline example](missing.md)`
```markdown
![example](missing.png)
```
<!-- [comment](missing.md) -->
''')
        self.assertEqual(self.errors(self.push_plan()), [])

    def test_reference_links_and_encoded_paths(self):
        self.write('docs/한글 file.md', '# Guide\n')
        self.write('README.md', '''[guide][ref]
[ref]: <docs/한글 file.md> "Title"
![image](docs/image%20(1).svg)
''')
        self.write('docs/image (1).svg', '<svg/>\n')
        self.assertEqual(self.errors(self.push_plan()), [])

    def test_uppercase_document_extensions_are_not_skipped(self):
        self.write('docs/GUIDE.MD', '[missing](missing.md)\n')
        self.write('docs/IMAGE.SVG', '<svg>')
        plan = self.push_plan()
        self.assertFalse(plan['windows'])
        errors = '\n'.join(self.errors(plan))
        self.assertIn('docs/GUIDE.MD: missing local target', errors)
        self.assertIn('docs/IMAGE.SVG: invalid SVG', errors)

    def test_invalid_svg_conflicts_and_invalid_utf8_fail(self):
        self.write('docs/image.svg', '<svg>')
        self.write('README.md', '# Example  \n<<<<<<< current\n')
        errors = '\n'.join(self.errors(self.push_plan()))
        self.assertIn('invalid SVG', errors)
        self.assertIn('merge conflict', errors)
        (self.root / 'README.md').write_bytes(b'\xff\xfe')
        self.assertIn('utf-8', '\n'.join(self.errors(self.push_plan())))

    def test_missing_unrelated_historical_reference_does_not_block_new_doc(self):
        self.write('docs/history.md', '[local evidence](../research/private/example.txt)\n')
        base = self.commit()
        self.write('docs/new.md', '# New guide\n')
        self.assertEqual(self.errors(self.push_plan(base)), [])

    def test_plan_cli_writes_github_output(self):
        # The CLI locates its repository from __file__, so copy it to the fixture.
        self.write('tools/ci_checks.py', Path(ci.__file__).read_text(encoding='utf-8'))
        self.commit()
        base = self.git('rev-parse', 'HEAD')
        self.write('README.md', '# New title\n')
        head = self.commit()
        event = self.root / 'event.json'
        event.write_text(json.dumps({'before': base, 'after': head}))
        output = self.root / 'output.txt'
        plan_file = self.root / 'plan.json'
        env = dict(os.environ, GITHUB_EVENT_NAME='push', GITHUB_EVENT_PATH=str(event),
                   GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(self.root / 'summary.md'))
        result = subprocess.run([sys.executable, str(self.root / 'tools/ci_checks.py'),
                                 'plan', '--output', str(plan_file)], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_text().strip(), 'windows=false')
        self.assertFalse(json.loads(plan_file.read_text())['windows'])


if __name__ == '__main__':
    unittest.main()
