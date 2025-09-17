"""Tests for FLAC library management functionality."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch
import tempfile

from pac.library_runner import cmd_manage_library
from pac.library_planner import plan_library_actions, LibraryPlanItem
from pac.config import PacSettings


def test_plan_library_actions_basic():
    """Test basic library planning functionality."""
    # Mock sources
    mock_sources = [
        Mock(flac_md5="md5_1", path=Path("/test/file1.flac"), rel_path=Path("file1.flac")),
        Mock(flac_md5="md5_2", path=Path("/test/file2.flac"), rel_path=Path("file2.flac")),
    ]

    # Mock config
    cfg = PacSettings(
        flac_target_compression=8,
        flac_resample_to_cd=True,
        flac_art_root="~/Music/_art",
        flac_art_pattern="{albumartist}/{album}/front.jpg"
    )

    # Mock DB
    mock_db = Mock()

    with patch('pac.library_planner.flac_stream_info') as mock_info, \
         patch('pac.library_planner.needs_cd_downmix', return_value=False), \
         patch('pac.library_planner.get_flac_tag', return_value="flac 1.4.3; level=8"), \
         patch('pac.library_planner.extract_art') as mock_extract, \
         patch('pac.library_planner._resolve_art_pattern', return_value=Path("/art/file1.jpg")):

        mock_info.return_value = {
            'sample_rate': 44100,
            'bit_depth': 16,
            'channels': 2,
            'md5': 'test_md5'
        }
        mock_extract.return_value = Path("/art/file1.jpg")

        plan = plan_library_actions(mock_sources, cfg, mock_db, 1234567890)

        # Should have plans for integrity test, recompress (skipped), and artwork extraction
        assert len(plan) >= 3

        # Check that we have test_integrity actions
        integrity_actions = [p for p in plan if p.action == "test_integrity"]
        assert len(integrity_actions) == 2

        # Check that we have extract_art actions (since artwork exists)
        art_actions = [p for p in plan if p.action == "extract_art"]
        assert len(art_actions) == 2


def test_cmd_manage_library_dry_run():
    """Test library management dry run."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root_path = Path(temp_dir)

        # Create a mock FLAC file
        flac_file = root_path / "test.flac"
        flac_file.write_bytes(b"mock flac data")

        cfg = PacSettings(
            flac_target_compression=8,
            flac_resample_to_cd=False,
            flac_art_root=str(root_path / "_art"),
            flac_art_pattern="front.jpg"
        )

        with patch('pac.library_runner.scan_flac_files') as mock_scan, \
             patch('pac.library_runner.plan_library_actions') as mock_plan:

            mock_scan.return_value = []
            mock_plan.return_value = []

            exit_code, summary = cmd_manage_library(cfg, str(root_path), dry_run=True)

            assert exit_code == 0
            assert "scanned" in summary
            assert "planned" in summary


def test_mirror_filtering_logic():
    """Test that mirror filtering logic works correctly."""
    from pac.library_runner import _was_held

    # Mock plan with held and non-held items
    plan = [
        LibraryPlanItem("hold", "test failed", Path("/test/held.flac"), Path("held.flac"), "held_md5", {}),
        LibraryPlanItem("test_integrity", "ok", Path("/test/clean.flac"), Path("clean.flac"), "clean_md5", {}),
    ]

    # Test held detection
    assert _was_held("held_md5", plan) == True
    assert _was_held("clean_md5", plan) == False
    assert _was_held("unknown_md5", plan) == False
