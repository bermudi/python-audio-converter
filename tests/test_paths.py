import unittest
from pathlib import Path
import tempfile
import os

from pac.paths import resolve_collisions, sanitize_rel_path


class TestPathsCollisionResolution(unittest.TestCase):
    def test_case_insensitive_collisions_among_candidates(self):
        # Candidates that collide on case-insensitive filesystems
        candidates = [
            Path("Artist/Album/Track.flac"),
            Path("artist/album/track.flac"),
        ]
        with tempfile.TemporaryDirectory() as td:
            out_root = Path(td)
            resolved = resolve_collisions(candidates, out_root=out_root)

        # Return order must match input order
        self.assertEqual(len(resolved), 2)

        # After sanitization, both should be .m4a
        self.assertTrue(all(p.suffix == ".m4a" for p in resolved))

        # Case-insensitive uniqueness
        keys = {p.as_posix().casefold() for p in resolved}
        self.assertEqual(len(keys), 2)

        # Exactly one should have a numeric suffix
        suffixed = [p for p in resolved if p.stem.endswith(")") and " (" in p.stem]
        self.assertEqual(len(suffixed), 1)

    def test_existing_outputs_block_candidates(self):
        candidates = [
            Path("Artist/Album/Track.flac"),
            Path("Artist/Album/Track.flac"),  # identical, will need suffix
        ]
        with tempfile.TemporaryDirectory() as td:
            out_root = Path(td)
            # Create an existing file that should occupy the base name
            existing = out_root / sanitize_rel_path(Path("Artist/Album/Track.flac"))
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_bytes(b"")

            resolved = resolve_collisions(candidates, out_root=out_root)

        # Base should be taken by existing, both candidates must be unique and not equal to existing
        keys = {p.as_posix().casefold() for p in resolved}
        self.assertEqual(len(keys), 2)
        self.assertNotIn(existing.as_posix().casefold(), keys)
        # Both should have suffixes now (since existing took the base)
        self.assertTrue(all(p.stem.endswith(")") and " (" in p.stem for p in resolved))

    def test_multiple_duplicates_get_incremental_suffixes(self):
        # Three candidates mapping to same rel path
        candidates = [
            Path("Dir/File.flac"),
            Path("dir/file.flac"),
            Path("DIR/FILE.flac"),
        ]
        with tempfile.TemporaryDirectory() as td:
            out_root = Path(td)
            resolved = resolve_collisions(candidates, out_root=out_root)

        # All unique under casefold
        keys = [p.as_posix().casefold() for p in resolved]
        self.assertEqual(len(set(keys)), 3)
        # One base + two with suffixes (order of suffix assignment determined by sorted(str))
        suffixed_count = sum(1 for p in resolved if p.stem.endswith(")") and " (" in p.stem)
        self.assertEqual(suffixed_count, 2)


if __name__ == "__main__":
    unittest.main()
