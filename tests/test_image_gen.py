"""Offline tests for the image-gen helper functions.

image-gen is stdlib-only; these tests exercise key resolution and PNG saving
without any network call or API key. (The actual HTTP request path needs a live
OpenAI key and is covered by the manual examples in the SKILL, not unit tests.)
"""

import argparse
import base64
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "image-gen" / "scripts" / "image_gen.py"
_spec = importlib.util.spec_from_file_location("image_gen", SCRIPT)
image_gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(image_gen)


def _save_quiet(resp, out):
    """save_images prints 'saved <path>' — swallow it so test output stays clean."""
    with contextlib.redirect_stdout(io.StringIO()):
        return image_gen.save_images(resp, out)


class SaveImagesTests(unittest.TestCase):
    def test_single_image_keeps_name(self):
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / "o.png")
            resp = {"data": [{"b64_json": base64.b64encode(b"PNGDATA").decode()}]}
            paths = _save_quiet(resp, out)
            self.assertEqual([Path(p).name for p in paths], ["o.png"])
            self.assertEqual(Path(out).read_bytes(), b"PNGDATA")

    def test_multiple_images_get_suffixes(self):
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / "o.png")
            b64 = base64.b64encode(b"X").decode()
            resp = {"data": [{"b64_json": b64}, {"b64_json": b64}]}
            paths = _save_quiet(resp, out)
            self.assertEqual(sorted(Path(p).name for p in paths), ["o_1.png", "o_2.png"])

    def test_empty_response_exits(self):
        with self.assertRaises(SystemExit):
            image_gen.save_images({"data": []}, "/tmp/whatever.png")


class ResolveKeyTests(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ("OPENAI_API_KEY", "IMAGE_GEN_ENV_FILE")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_cli_flag_wins(self):
        args = argparse.Namespace(api_key="cli-key", env_file=None)
        self.assertEqual(image_gen.resolve_key(args), "cli-key")

    def test_env_var_used(self):
        os.environ["OPENAI_API_KEY"] = "env-key"
        args = argparse.Namespace(api_key=None, env_file=None)
        self.assertEqual(image_gen.resolve_key(args), "env-key")

    def test_env_file_used(self):
        with tempfile.TemporaryDirectory() as d:
            ef = Path(d) / "k.env"
            ef.write_text('OPENAI_API_KEY="file-key"\n')
            args = argparse.Namespace(api_key=None, env_file=str(ef))
            self.assertEqual(image_gen.resolve_key(args), "file-key")


if __name__ == "__main__":
    unittest.main()
