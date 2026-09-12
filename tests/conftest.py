from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def fx():
    return fixture
