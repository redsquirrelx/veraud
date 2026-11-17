"""Checkout verification shared by verification-suite generators."""

import subprocess
from pathlib import Path

__all__ = ["check_checkout"]


def check_checkout(repo_path: str | Path | None, expected_commit: str) -> tuple[bool, list[str]]:
    """Compare a local checkout with the audited commit, when possible."""

    limitations: list[str] = []
    if repo_path is None:
        return False, ["No repository checkout was provided; baseline validation is unavailable."]
    root = Path(repo_path)
    if not root.is_dir():
        return False, [f"Repository checkout not found: {root}; baseline validation is unavailable."]
    git_dir = root / ".git"
    if git_dir.exists():
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return False, [f"Could not read the git revision of the checkout: {error}"]
        if result.returncode:
            return False, ["Could not read the git revision of the checkout; baseline validation is unavailable."]
        head = result.stdout.strip().lower()
        if head != expected_commit.lower():
            limitations.append(
                f"Checkout HEAD ({head}) does not match the audited commit ({expected_commit}); "
                "the suite is still usable for checking corrections, but it is not validated against the original version."
            )
            return True, limitations
        return True, limitations
    limitations.append("The checkout has no .git metadata; the commit cannot be verified and baseline validation is unavailable.")
    return True, limitations
