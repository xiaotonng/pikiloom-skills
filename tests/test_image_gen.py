"""Offline tests for the image-gen helper functions.

image-gen is stdlib-only; these tests exercise key/provider resolution, model-alias
mapping and PNG saving without any network call or API key. (The live HTTP paths —
OpenAI Images API and OpenRouter chat-completions — need a real key and are covered
by the SKILL examples, not unit tests.)
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


def _args(**kw):
    kw.setdefault("api_key", None)
    kw.setdefault("env_file", None)
    kw.setdefault("provider", "auto")
    return argparse.Namespace(**kw)


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


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "IMAGE_GEN_ENV_FILE")}
        for k in self._saved:
            os.environ.pop(k, None)
        # Isolate from the developer's real ~/.pikiloom/skills.env (which may hold both keys).
        self._fallback = image_gen.FALLBACK_ENV_FILES
        image_gen.FALLBACK_ENV_FILES = []

    def tearDown(self):
        image_gen.FALLBACK_ENV_FILES = self._fallback
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_cli_flag_wins_and_infers_openai(self):
        self.assertEqual(image_gen.resolve(_args(api_key="cli-key")),
                         ("cli-key", "openai", image_gen.OPENAI_BASE))

    def test_cli_flag_sk_or_prefix_infers_openrouter(self):
        key, prov, base = image_gen.resolve(_args(api_key="sk-or-abc"))
        self.assertEqual((prov, base), ("openrouter", image_gen.OPENROUTER_BASE))

    def test_openai_env_used(self):
        os.environ["OPENAI_API_KEY"] = "env-key"
        key, prov, _ = image_gen.resolve(_args())
        self.assertEqual((key, prov), ("env-key", "openai"))

    def test_openrouter_env_when_no_openai(self):
        os.environ["OPENROUTER_API_KEY"] = "or-key"
        self.assertEqual(image_gen.resolve(_args()),
                         ("or-key", "openrouter", image_gen.OPENROUTER_BASE))

    def test_auto_prefers_openai_when_both_present(self):
        os.environ["OPENAI_API_KEY"] = "oa"
        os.environ["OPENROUTER_API_KEY"] = "or"
        key, prov, _ = image_gen.resolve(_args())
        self.assertEqual((key, prov), ("oa", "openai"))

    def test_force_openrouter_with_both_present(self):
        os.environ["OPENAI_API_KEY"] = "oa"
        os.environ["OPENROUTER_API_KEY"] = "or"
        key, prov, _ = image_gen.resolve(_args(provider="openrouter"))
        self.assertEqual((key, prov), ("or", "openrouter"))

    def test_missing_key_exits(self):
        with self.assertRaises(SystemExit):
            image_gen.resolve(_args())

    def test_env_file_used(self):
        with tempfile.TemporaryDirectory() as d:
            ef = Path(d) / "k.env"
            ef.write_text('OPENAI_API_KEY="file-key"\n')
            key, prov, _ = image_gen.resolve(_args(env_file=str(ef)))
            self.assertEqual((key, prov), ("file-key", "openai"))


class ModelAliasTests(unittest.TestCase):
    def test_bare_gpt_image_2_maps_to_slug(self):
        self.assertEqual(image_gen.or_model("gpt-image-2"), "openai/gpt-5.4-image-2")

    def test_bare_mini_maps(self):
        self.assertEqual(image_gen.or_model("gpt-image-1-mini"), "openai/gpt-5-image-mini")

    def test_explicit_slug_passes_through(self):
        self.assertEqual(image_gen.or_model("google/gemini-2.5-flash-image"),
                         "google/gemini-2.5-flash-image")

    def test_unknown_bare_falls_back_to_default(self):
        self.assertEqual(image_gen.or_model("whatever"), "openai/gpt-5.4-image-2")


class SizeAspectTests(unittest.TestCase):
    def test_known_sizes_map_to_aspect(self):
        self.assertEqual(image_gen.SIZE_TO_ASPECT["1024x1024"], "1:1")
        self.assertEqual(image_gen.SIZE_TO_ASPECT["1536x1024"], "3:2")
        self.assertEqual(image_gen.SIZE_TO_ASPECT["1024x1536"], "2:3")

    def test_auto_size_has_no_aspect(self):
        self.assertNotIn("auto", image_gen.SIZE_TO_ASPECT)


class FallbackChainTests(unittest.TestCase):
    def test_gpt_image_2_is_top_priority(self):
        # The user's requirement: gpt-image-2 (its OpenRouter slug) is tried first.
        self.assertEqual(image_gen.OPENROUTER_FALLBACK[0], "openai/gpt-5.4-image-2")

    def test_default_model_walks_full_chain(self):
        self.assertEqual(image_gen.or_chain("gpt-image-2"), list(image_gen.OPENROUTER_FALLBACK))

    def test_explicit_slug_pins_single_model(self):
        self.assertEqual(image_gen.or_chain("google/gemini-2.5-flash-image"),
                         ["google/gemini-2.5-flash-image"])

    def test_backups_are_non_openai(self):
        # Backups must be reachable without the OpenAI data-policy opt-in.
        self.assertTrue(image_gen.OPENROUTER_FALLBACK[1:])
        self.assertTrue(all(not m.startswith("openai/") for m in image_gen.OPENROUTER_FALLBACK[1:]))


if __name__ == "__main__":
    unittest.main()
