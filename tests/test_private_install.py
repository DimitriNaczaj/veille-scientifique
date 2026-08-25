import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class PrivateInstallerTests(unittest.TestCase):
    def test_installer_uses_a_read_only_private_archive_without_persisting_token(self):
        script = (ROOT / "scripts" / "install-nas.sh").read_text(encoding="utf-8")

        self.assertIn(
            'REPOSITORY_ARCHIVE="https://api.github.com/repos/'
            'DimitriNaczaj/veille-scientifique/tarball/main"',
            script,
        )
        self.assertIn('ask_secret GITHUB_TOKEN "Jeton GitHub temporaire :"', script)
        self.assertIn('Authorization: Bearer %s', script)
        self.assertIn('unset GITHUB_TOKEN', script)
        self.assertNotIn('write_env GITHUB_TOKEN', script)
        self.assertNotIn('GITHUB_TOKEN=', script.split('TOTAL_STAGES=8', 1)[1])

    def test_readme_bootstrap_hides_and_clears_the_private_token(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn('read -rsp "Jeton GitHub : " GITHUB_TOKEN', readme)
        self.assertIn('application/vnd.github.raw+json', readme)
        self.assertIn('GITHUB_TOKEN="$GITHUB_TOKEN" bash', readme)
        self.assertIn('unset GITHUB_TOKEN', readme)


if __name__ == "__main__":
    unittest.main()
