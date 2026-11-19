"""FakeExtractor: canned results for tests. CI never calls a real LLM (DESIGN §4.3)."""

from app.services.extraction.schema import ExtractionResult


class FakeExtractor:
    def __init__(self, result: ExtractionResult) -> None:
        self.result = result
        self.calls: list[str] = []  # the raw texts it was asked to read

    async def extract(self, raw_text: str) -> ExtractionResult:
        self.calls.append(raw_text)
        return self.result
