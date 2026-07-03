"""Module docstring for the fixture."""

import os
from typing import Any

CONST = 42


def top_level(x: int) -> int:
    """A top-level function."""
    return x + CONST


@staticmethod
def decorated(y):
    return y


class Widget:
    """A widget."""

    kind = "button"

    def __init__(self, name: str) -> None:
        self.name = name

    def render(self) -> str:
        return f"<{self.kind}:{self.name}>"
