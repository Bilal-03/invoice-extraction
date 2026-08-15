"""Small compatibility shims for the Python versions used by the containers."""

from datetime import timezone
from enum import Enum

UTC = timezone.utc

try:  # Python 3.11+
    from enum import StrEnum as StrEnum
except ImportError:  # Python 3.10

    class StrEnum(str, Enum):
        """Backport of :class:`enum.StrEnum` for the Paddle 3.3 image."""

        def __str__(self) -> str:
            return self.value
