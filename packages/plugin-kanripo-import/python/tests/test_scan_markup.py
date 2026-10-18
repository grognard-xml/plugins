from kanripo_import.parallel_punct import _clean_parallel_for_alignment


def test_scan_markers_are_removed_from_parallel_text():
    text = '<scanbegin file="82245" page="61"/>輶軒使者，<scanbreak file="82245" y="10"/>絕代<scanend file="82245" page="61"/>語釋'
    assert _clean_parallel_for_alignment(text) == "輶軒使者，絕代語釋"
