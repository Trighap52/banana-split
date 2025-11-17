from banana_split.diff_parser import parse_unified_diff, render_partial_diff


def _collect_hunk_ids(diff):
    return [h.id for f in diff.files for h in f.hunks]


def test_parse_simple_modify():
    raw = """\
diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1,2 +1,2 @@
-a = 1
+a = 2
 b = 3
"""
    diff = parse_unified_diff(raw)
    assert len(diff.files) == 1
    file = diff.files[0]
    assert file.path_old == "foo.py"
    assert file.path_new == "foo.py"
    assert file.change_type == "modify"
    assert not file.is_binary
    assert len(file.hunks) == 1
    hunk = file.hunks[0]
    # Expect two changed lines plus one context line.
    assert any(l.line_type == "-" for l in hunk.lines)
    assert any(l.line_type == "+" for l in hunk.lines)
    assert any(l.line_type == " " for l in hunk.lines)


def test_parse_add_and_delete_files():
    raw = """\
diff --git a/new.txt b/new.txt
new file mode 100644
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+hello
+world
diff --git a/old.txt b/old.txt
deleted file mode 100644
--- a/old.txt
+++ /dev/null
@@ -1,2 +0,0 @@
-bye
-world
"""
    diff = parse_unified_diff(raw)
    assert len(diff.files) == 2
    add_file = next(f for f in diff.files if f.path_new == "new.txt")
    del_file = next(f for f in diff.files if f.path_old == "old.txt")

    assert add_file.change_type == "add"
    assert del_file.change_type == "delete"


def test_render_partial_diff_round_trip():
    raw = """\
diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 a = 1
-b = 2
+b = 3
 c = 4
"""
    diff = parse_unified_diff(raw)
    all_ids = _collect_hunk_ids(diff)

    out = render_partial_diff(diff, all_ids)
    # Parsing the rendered diff should give us the same structure
    # in terms of files and number of hunks.
    diff2 = parse_unified_diff(out)
    assert len(diff2.files) == len(diff.files)
    assert _collect_hunk_ids(diff2)


def test_hunk_meta_language_and_symbol():
    raw = """\
diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1,2 +1,3 @@ def foo
-a = 1
+a = 2
 b = 3
"""
    diff = parse_unified_diff(raw)
    assert len(diff.files) == 1
    file = diff.files[0]
    assert len(file.hunks) == 1
    hunk = file.hunks[0]
    assert hunk.meta.get("language") == "python"
    assert hunk.meta.get("symbol") == "def foo"
