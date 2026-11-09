"""Guard rail: the public repo must never contain names from the real-world system this demo is based on.

The forbidden terms are stored only as SHA-256 hashes, so this file doesn't leak them itself.
Every window of matching length in every tracked text file is hashed and compared.
"""
import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", "vendor", ".venv", "venv", ".pytest_cache"}
TEXT_SUFFIXES = {".py", ".html", ".css", ".js", ".md", ".txt", ".yaml", ".yml", ".toml", ".cfg", ".svg", ".json", ".bat", ""}

FORBIDDEN = {
    "32dba4b43d0f394887ad54003cc49e3ccd720c2e3478d928c90c3846b4891691": 3,
    "fc2775e7c57f7e484a6dc9328769386eeee46a0bcc149038e64f3500d6ad7d89": 7,
    "b08d5f766c96d3ae04a26dd7ff73788ab1d07b943a6448022a536458b0e2a5a0": 10,
    "29633609c8390c1d73aea1464bf2ff97ecac3173b3f041a573c51dd716416771": 7,
    "7e01f270eb135b13e59ff894a9543c077966d1e5b067db861ce290badb27518b": 15,
    "6c2a546ea82eddae12f8b040ea8e6b1ba8cb59cd5e76c1c1d9bf2d2693b72c79": 15,
    "188ad308361d1164221d11de25e5f2b09484677bf45b7e941fedd3c39611b248": 4,
    "de5a1adf4fedcce1533915edc60177547f1057b61b7119fd130e1f7428705f73": 9,
    "72cad35f15f59e44409511f0ac0a5703743bd892788e00a97b6b2dcd24674d51": 8,
    "1552923c04da97247020bf979249f3f16f85205ea489fce22ab750b06866746b": 10,
    "d8a0d9c8dae348975563a260eb126f29c491bc97e2aae2dc23fded2e1388c98d": 13,
    "e7c010e0e77cd1e47af93b69f55102c37a8e4d267d2dafa9c9d190034aa5ebf6": 4,
    "4b79be6a5c777ed09b7b10b6601f002f10149444bd37b98b6f3706e0018767d7": 3,
    "30fba9ec34d4372a85d4fa253d4d7c02f8d96de5e90a01b8f6686f6a448207da": 3,
    "7e2db47e76b90667da18e46f9b9445e15db1e30b996679c8c9de389715b118e5": 3,
}
SHORT = 4  # terms this short only count as whole words, to avoid random substrings


def files():
    for p in ROOT.rglob("*"):
        if p.is_file() and not SKIP_DIRS & set(p.relative_to(ROOT).parts) and p.suffix.lower() in TEXT_SUFFIXES:
            yield p


def hits(text: str):
    text = text.lower()
    lengths = sorted(set(FORBIDDEN.values()))
    words = set(re.findall(r"[a-z0-9]+", text))
    for word in words:
        if len(word) <= SHORT and hashlib.sha256(word.encode()).hexdigest() in FORBIDDEN:
            yield word
    for n in (l for l in lengths if l > SHORT):
        seen = set()
        for i in range(len(text) - n + 1):
            chunk = text[i:i + n]
            if chunk in seen:
                continue
            seen.add(chunk)
            if hashlib.sha256(chunk.encode()).hexdigest() in FORBIDDEN:
                yield chunk


class NoLeaksTest(unittest.TestCase):
    def test_repository_is_clean(self):
        problems = []
        for p in files():
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for h in hits(text):
                problems.append(f"{p.relative_to(ROOT)}: forbidden term ({len(h)} chars)")
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
