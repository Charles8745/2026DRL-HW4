from harness.retrieval.bm25 import BM25Index, tokenize


def test_tokenize_chinese_drops_blanks():
    toks = tokenize("速克達 通勤 省油")
    assert "速克達" in toks
    assert "" not in toks and " " not in toks


def test_bm25_ranks_relevant_doc_first():
    idx = BM25Index(
        ["scooter", "sport"],
        ["速克達 都市通勤 省油 好停 輕巧", "仿賽 賽道 高馬力 戰鬥坐姿"],
    )
    ranked = idx.search("通勤省油的速克達")
    assert ranked[0][0] == "scooter"


def test_bm25_returns_all_docs():
    idx = BM25Index(["a", "b", "c"], ["x", "y", "z"])
    assert len(idx.search("x")) == 3
