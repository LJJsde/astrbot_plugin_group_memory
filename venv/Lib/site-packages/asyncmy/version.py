from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth is `version` in pyproject.toml; reading it back
    # from the installed metadata keeps this file from drifting out of sync.
    __VERSION__ = version("asyncmy")
except PackageNotFoundError:  # imported from a source tree with no install
    __VERSION__ = "0.0.0.dev0"

__version__ = __VERSION__
