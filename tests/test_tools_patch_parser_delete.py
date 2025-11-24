from lincona.tools.patch_parser import parse_unified_diff


def test_delete_file_header_sets_delete_flag():
    diff = """*** Delete File: path/to/file.txt"""
    patches = parse_unified_diff(diff)
    assert patches[0].delete is True
    assert patches[0].path.as_posix() == "path/to/file.txt"
