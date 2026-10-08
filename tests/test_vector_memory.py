"""Test vector memory: truy xuất ngữ nghĩa và chịu được phản hồi thiếu dữ liệu."""

from __future__ import annotations

from lifeos.memory.vector import VectorMemory


class _FakeCollection:
    """Bộ sưu tập giả trả về đúng thứ mà kiểu dữ liệu của chromadb cho phép.

    Chữ ký `query()` của chromadb khai báo các khoá là `Optional`, tức là mặt
    kiểu dữ liệu có thừa nhận khả năng trả `None`. Bản chromadb đang dùng trả
    `[[]]` khi bộ sưu tập rỗng, nên không tái hiện được `None` bằng chroma thật
    — phải giả lập để khoá hành vi phòng vệ lại.
    """

    def __init__(self, response):
        self._response = response

    def query(self, **_kwargs):
        return self._response

    def count(self) -> int:
        return 0


def _memory_with(response) -> VectorMemory:
    memory = VectorMemory.__new__(VectorMemory)
    memory._collection = _FakeCollection(response)
    return memory


# --- hành vi thật với chroma ---


def test_search_on_empty_collection_returns_empty_list(tmp_path):
    memory = VectorMemory(str(tmp_path / "chroma"))

    assert memory.count() == 0
    assert memory.search("bất kỳ", k=4) == []


def test_search_returns_text_and_metadata(tmp_path):
    memory = VectorMemory(str(tmp_path / "chroma"))
    doc_id = memory.add("nội dung thử nghiệm", {"nguồn": "test"})

    hits = memory.search("thử nghiệm", k=2)

    assert len(hits) == 1
    assert hits[0]["id"] == doc_id
    assert hits[0]["text"] == "nội dung thử nghiệm"
    assert hits[0]["metadata"] == {"nguồn": "test"}


# --- phòng vệ khi chromadb trả None ---


def test_search_survives_none_for_every_key():
    """`None` ở cả ba khoá phải cho kết quả rỗng, không phải `TypeError`."""
    memory = _memory_with({"ids": None, "documents": None, "metadatas": None})

    assert memory.search("bất kỳ") == []


def test_search_survives_missing_keys():
    memory = _memory_with({})

    assert memory.search("bất kỳ") == []


def test_search_survives_none_documents_with_present_ids():
    """Có id nhưng thiếu văn bản: vẫn trả về bản ghi với phần văn bản rỗng."""
    memory = _memory_with(
        {"ids": [["a", "b"]], "documents": None, "metadatas": None}
    )

    hits = memory.search("bất kỳ")

    assert [h["id"] for h in hits] == ["a", "b"]
    assert [h["text"] for h in hits] == ["", ""]
    assert [h["metadata"] for h in hits] == [{}, {}]
