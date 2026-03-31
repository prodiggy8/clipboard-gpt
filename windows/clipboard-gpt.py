#!/usr/bin/env python3
"""
Requirements: pyperclip for text out, & Gemini API key
"""
from __future__ import annotations
from google import genai
from google.genai import types
import hashlib
import io
import os
import sys
import time
from dotenv import load_dotenv
from PIL import Image, ImageGrab
import pyperclip

load_dotenv()

CLIPBOARD_PROMPT = "Please solve the following problem. Return the instructions to solve (no math, just text) and the final answer (latex)."
GEMINI_MODEL = "gemini-2.5-flash"
POLL_INTERVAL = 0.5


def _mime_for_ext(ext: str) -> str:
    ext = ext.lower()

    if ext == ".png":
        return "image/png"

    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"

    return "image/png"


def _client() -> genai.Client:
    key = os.environ.get("API_KEY")

    if not key:
        print("API_KEY missing.", file=sys.stderr)
        sys.exit(1)

    return genai.Client(api_key=key)


def _clipboard_image_from_pil(im: Image.Image) -> tuple[bytes, str]:
    bio = io.BytesIO()
    im.save(bio, format="PNG")
    return bio.getvalue(), ".png"


def read_clipboard_image() -> tuple[bytes, str] | None:
    """PNG/JPEG from clipboard: bitmap via PIL, or first image file if Explorer copied files."""
    got = ImageGrab.grabclipboard()

    if got is None:
        return None

    if isinstance(got, Image.Image):
        return _clipboard_image_from_pil(got)

    if isinstance(got, list):
        for path in got:
            if not isinstance(path, str):
                continue
            lower = path.lower()
            if lower.endswith((".png", ".jpg", ".jpeg")):
                ext = ".jpg" if lower.endswith((".jpg", ".jpeg")) else ".png"
                with open(path, "rb") as f:
                    return f.read(), ext
        return None

    return None


def _digest(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def describe_clipboard_image(client: genai.Client, data: bytes, ext: str) -> str:
    img = types.Part.from_bytes(data=data, mime_type=_mime_for_ext(ext))

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            CLIPBOARD_PROMPT,
            img,
        ],
    )

    if response.text is None:
        return ""

    return response.text


def write_clipboard_text(text: str) -> None:
    pyperclip.copy(text)


def run_forever() -> int:
    client = _client()
    last_digest = None

    try:
        while True:
            result = read_clipboard_image()

            if result is None:
                time.sleep(POLL_INTERVAL)
                continue

            data, ext = result
            d = _digest(data)

            if d == last_digest:
                time.sleep(POLL_INTERVAL)
                continue

            last_digest = d

            try:
                out = describe_clipboard_image(client, data, ext)
                print(out, flush=True)
                write_clipboard_text(out)
            except Exception as e:
                print(f"Gemini or clipboard failed: {e}", file=sys.stderr)

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        if sys.stderr.isatty():
            print("Stopped.", file=sys.stderr)
        return 0


def main() -> int:
    return run_forever()


if __name__ == "__main__":
    sys.exit(main())
