"""Authenticity analysis tools for FLAC files."""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import re

from loguru import logger


class AuthToolResult:
    """Result of probing an authenticity tool."""

    def __init__(self, available: bool, version: Optional[str] = None, path: Optional[str] = None, error: Optional[str] = None):
        self.available = available
        self.version = version
        self.path = path
        self.error = error


def probe_aucdtect() -> AuthToolResult:
    """Probe for auCDtect binary."""
    try:
        result = subprocess.run(
            ["aucdtect", "-h"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 or "auCDtect" in result.stdout:
            # Try to get version
            version = None
            for line in result.stdout.split('\n'):
                if 'version' in line.lower():
                    version = line.strip()
                    break
            path = shutil.which("aucdtect")
            return AuthToolResult(available=True, version=version, path=path)
        return AuthToolResult(available=False, error="auCDtect not found")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return AuthToolResult(available=False, error=str(e))


def probe_lac() -> AuthToolResult:
    """Probe for Lossless Audio Checker (LAC)."""
    try:
        result = subprocess.run(
            ["lac", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip().split('\n')[0] if result.stdout.strip() else None
            path = shutil.which("lac")
            return AuthToolResult(available=True, version=version, path=path)
        return AuthToolResult(available=False, error="lac not found")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return AuthToolResult(available=False, error=str(e))


def run_aucdtect(src: Path) -> Dict[str, Any]:
    """Run auCDtect on a file and parse results."""
    try:
        result = subprocess.run(
            ["aucdtect", str(src)],
            capture_output=True,
            text=True,
            timeout=120,  # auCDtect can be slow
        )
        if result.returncode == 0:
            # Parse output - auCDtect typically outputs lines like:
            # "Result: Likely LOSSY (score: 85.2%)"
            output = result.stdout + result.stderr
            score = None
            classification = "unknown"

            # Look for score pattern
            score_match = re.search(r'score:\s*(\d+(?:\.\d+)?)', output, re.IGNORECASE)
            if score_match:
                score = float(score_match.group(1))

            # Look for classification
            if "lossy" in output.lower():
                classification = "lossy"
            elif "lossless" in output.lower():
                classification = "lossless"
            elif "transcoded" in output.lower():
                classification = "transcoded"

            return {
                "tool": "aucdtect",
                "score": score,
                "classification": classification,
                "raw_output": output.strip(),
                "success": True,
            }
        else:
            return {
                "tool": "aucdtect",
                "error": result.stderr.strip(),
                "success": False,
            }
    except (subprocess.TimeoutExpired, OSError) as e:
        return {
            "tool": "aucdtect",
            "error": str(e),
            "success": False,
        }


def run_lac(src: Path) -> Dict[str, Any]:
    """Run LAC on a file and parse results."""
    try:
        result = subprocess.run(
            ["lac", str(src)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            output = result.stdout + result.stderr
            result_status = "unknown"

            # LAC typically outputs "Lossless" or "Lossy" or detailed analysis
            if "lossy" in output.lower():
                result_status = "lossy"
            elif "lossless" in output.lower():
                result_status = "lossless"

            return {
                "tool": "lac",
                "result": result_status,
                "raw_output": output.strip(),
                "success": True,
            }
        else:
            return {
                "tool": "lac",
                "error": result.stderr.strip(),
                "success": False,
            }
    except (subprocess.TimeoutExpired, OSError) as e:
        return {
            "tool": "lac",
            "error": str(e),
            "success": False,
        }


def classify_authenticity(aucdtect: Dict[str, Any], lac: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Combine auCDtect and LAC results into overall authenticity status."""
    details = {
        "aucdtect": aucdtect,
        "lac": lac,
    }

    # Default to ok
    status = "ok"
    rationale = []

    # Check auCDtect
    if aucdtect.get("success"):
        if aucdtect.get("classification") in ["lossy", "transcoded"]:
            status = "suspect"
            rationale.append(f"auCDtect: {aucdtect['classification']}")
        elif aucdtect.get("score") and aucdtect["score"] > 50:  # Arbitrary threshold
            status = "suspect"
            rationale.append(f"auCDtect score: {aucdtect['score']}%")

    # Check LAC
    if lac.get("success"):
        if lac.get("result") == "lossy":
            status = "suspect"
            rationale.append("LAC: lossy")

    # If both failed, mark as error
    if not aucdtect.get("success") and not lac.get("success"):
        status = "error"
        rationale.append("Both tools failed")

    details["rationale"] = rationale
    return status, details