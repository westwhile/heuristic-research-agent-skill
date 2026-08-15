"""Unit tests for safe relative-path validation.

Stored locators are POSIX-form only: validation never normalizes, so two
spellings of the same path cannot validate yet hash differently.
"""

import unittest

from research_evolution.core import UnsafePathError, validate_safe_relative_path


class ValidateSafeRelativePathTest(unittest.TestCase):
    def test_valid_paths_returned_unchanged(self) -> None:
        for raw in (
            "file.txt",
            "a/b/c.json",
            "dir.with.dots/file_name-01.txt",
            "中文目录/文件.json",
            ".hidden/file",
            "a/..x/b",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(validate_safe_relative_path(raw), raw)

    def test_backslash_rejected_not_normalized(self) -> None:
        for raw in ("a\\b", "a\\b\\c.json", "\\\\server\\share\\file"):
            with self.subTest(raw=raw), self.assertRaises(UnsafePathError):
                validate_safe_relative_path(raw)

    def test_empty_and_whitespace_rejected(self) -> None:
        for raw in ("", "   ", " a/b", "a/b ", "\ta/b"):
            with self.subTest(raw=raw), self.assertRaises(UnsafePathError):
                validate_safe_relative_path(raw)

    def test_non_string_rejected(self) -> None:
        for raw in (123, None, b"a/b"):
            with self.subTest(raw=raw), self.assertRaises(UnsafePathError):
                validate_safe_relative_path(raw)  # type: ignore[arg-type]

    def test_absolute_and_root_anchored_rejected(self) -> None:
        for raw in ("/abs/path", "/", "//server/share/file"):
            with self.subTest(raw=raw), self.assertRaises(UnsafePathError):
                validate_safe_relative_path(raw)

    def test_drive_letter_rejected(self) -> None:
        for raw in ("C:/data", "C:\\data", "c:/data", "C:relative", "d:x"):
            with self.subTest(raw=raw), self.assertRaises(UnsafePathError):
                validate_safe_relative_path(raw)

    def test_dot_and_dotdot_components_rejected(self) -> None:
        for raw in ("..", "a/../b", "a/./b", "a/..", "a/.. /b"):
            with self.subTest(raw=raw), self.assertRaises(UnsafePathError):
                validate_safe_relative_path(raw)

    def test_empty_components_rejected(self) -> None:
        with self.assertRaises(UnsafePathError):
            validate_safe_relative_path("a//b")

    def test_component_trailing_dot_or_space_rejected(self) -> None:
        for raw in ("a/name./b", "a/name. /b", "a/name /b", "a/ name/b"):
            with self.subTest(raw=raw), self.assertRaises(UnsafePathError):
                validate_safe_relative_path(raw)

    def test_windows_device_names_rejected(self) -> None:
        for raw in (
            "a/CON/file.txt",
            "a/con/file.txt",
            "CON",
            "a/PRN",
            "a/AUX",
            "a/NUL",
            "a/COM1/x",
            "a/COM9/x",
            "a/LPT1/x",
            "a/con.txt/b",
        ):
            with self.subTest(raw=raw), self.assertRaises(UnsafePathError):
                validate_safe_relative_path(raw)

    def test_device_lookalikes_accepted(self) -> None:
        for raw in ("a/content/file.txt", "a/COM10/x", "a/console/x"):
            with self.subTest(raw=raw):
                self.assertEqual(validate_safe_relative_path(raw), raw)

    def test_control_characters_rejected(self) -> None:
        for raw in ("a\x00b", "a/b\nc", "a/b\rc", "a/b\x7fc"):
            with self.subTest(raw=repr(raw)), self.assertRaises(UnsafePathError):
                validate_safe_relative_path(raw)

    def test_windows_forbidden_characters_rejected(self) -> None:
        for char in '<>:"|?*':
            with self.subTest(char=char), self.assertRaises(UnsafePathError):
                validate_safe_relative_path(f"a{char}b")


if __name__ == "__main__":
    unittest.main()
