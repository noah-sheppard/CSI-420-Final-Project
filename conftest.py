import pytest

class Suite:
    def __init__(self, label):
        self.label = label
        self.results = []

@pytest.fixture
def old_suite():
    return Suite("ORIGINAL")

@pytest.fixture
def new_suite():
    return Suite("REFACTORED")