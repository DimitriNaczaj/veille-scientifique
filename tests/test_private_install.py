import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class PrivateInstallerTests(unittest.TestCase):
    def test_installer_prepares_elsevier_key_without_embedding_it_in_config(self):
        script = (ROOT / "scripts" / "install-nas.sh").read_text(
            encoding="utf-8"
        )
        example = (ROOT / "veille-scientifique.ini.example").read_text(
            encoding="utf-8"
        )

        self.assertIn("[elsevier]", script)
        self.assertIn("api_key_env = ELSEVIER_API_KEY", script)
        self.assertIn("export ELSEVIER_API_KEY", script)
        self.assertIn("[elsevier]", example)
        self.assertIn("api_key_env = ELSEVIER_API_KEY", example)
        self.assertNotIn("api_key =", example)

    def test_installer_tries_public_archive_before_private_token_fallback(self):
        script = (ROOT / "scripts" / "install-nas.sh").read_text(encoding="utf-8")

        self.assertIn(
            'PUBLIC_REPOSITORY_ARCHIVE="https://github.com/'
            'DimitriNaczaj/veille-scientifique/archive/refs/heads/main.tar.gz"',
            script,
        )
        self.assertIn(
            'PRIVATE_REPOSITORY_ARCHIVE="https://api.github.com/repos/'
            'DimitriNaczaj/veille-scientifique/tarball/main"',
            script,
        )
        self.assertLess(
            script.index('"$PUBLIC_REPOSITORY_ARCHIVE"'),
            script.index('ask_secret GITHUB_TOKEN'),
        )
        self.assertIn('ask_secret GITHUB_TOKEN "Jeton GitHub temporaire :"', script)
        self.assertIn('Authorization: Bearer %s', script)
        self.assertIn('unset GITHUB_TOKEN', script)
        self.assertNotIn('write_env GITHUB_TOKEN', script)
        self.assertNotIn('GITHUB_TOKEN=', script.split('TOTAL_STAGES=8', 1)[1])

    def test_readme_bootstrap_hides_and_clears_the_private_token(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn(
            "https://raw.githubusercontent.com/DimitriNaczaj/"
            "veille-scientifique/main/scripts/install-nas.sh",
            readme,
        )
        self.assertIn('read -rsp "Jeton GitHub : " GITHUB_TOKEN', readme)
        self.assertIn('application/vnd.github.raw+json', readme)
        self.assertIn('GITHUB_TOKEN="$GITHUB_TOKEN" bash', readme)
        self.assertIn('unset GITHUB_TOKEN', readme)


if __name__ == "__main__":
    unittest.main()
