import io
import os
import platform
import time
from unittest.mock import patch

import pytest

import click._termui_impl
from click._compat import WIN
from click._termui_impl import Editor


class FakeClock:
    def __init__(self):
        self.now = time.time()

    def advance_time(self, seconds=1):
        self.now += seconds

    def time(self):
        return self.now


def _create_progress(length=10, **kwargs):
    progress = click.progressbar(tuple(range(length)))
    for key, value in kwargs.items():
        setattr(progress, key, value)
    return progress


def test_progressbar_strip_regression(runner, monkeypatch):
    label = "    padded line"

    @click.command()
    def cli():
        with _create_progress(label=label) as progress:
            for _ in progress:
                pass

    monkeypatch.setattr(click._termui_impl, "isatty", lambda _: True)
    assert (
        label
        in runner.invoke(cli, [], standalone_mode=False, catch_exceptions=False).output
    )


def test_progressbar_length_hint(runner, monkeypatch):
    class Hinted:
        def __init__(self, n):
            self.items = list(range(n))

        def __length_hint__(self):
            return len(self.items)

        def __iter__(self):
            return self

        def __next__(self):
            if self.items:
                return self.items.pop()
            else:
                raise StopIteration

        next = __next__

    @click.command()
    def cli():
        with click.progressbar(Hinted(10), label="test") as progress:
            for _ in progress:
                pass

    monkeypatch.setattr(click._termui_impl, "isatty", lambda _: True)
    result = runner.invoke(cli, [])
    assert result.exception is None


def test_progressbar_hidden(runner, monkeypatch):
    @click.command()
    def cli():
        with _create_progress(label="working") as progress:
            for _ in progress:
                pass

    monkeypatch.setattr(click._termui_impl, "isatty", lambda _: False)
    assert runner.invoke(cli, []).output == "working\n"


@pytest.mark.parametrize("avg, expected", [([], 0.0), ([1, 4], 2.5)])
def test_progressbar_time_per_iteration(runner, avg, expected):
    with _create_progress(2, avg=avg) as progress:
        assert progress.time_per_iteration == expected


@pytest.mark.parametrize("finished, expected", [(False, 5), (True, 0)])
def test_progressbar_eta(runner, finished, expected):
    with _create_progress(2, finished=finished, avg=[1, 4]) as progress:
        assert progress.eta == expected


@pytest.mark.parametrize(
    "eta, expected",
    [
        (0, "00:00:00"),
        (30, "00:00:30"),
        (90, "00:01:30"),
        (900, "00:15:00"),
        (9000, "02:30:00"),
        (99999999999, "1157407d 09:46:39"),
        (None, ""),
    ],
)
def test_progressbar_format_eta(runner, eta, expected):
    with _create_progress(1, eta_known=eta is not None, avg=[eta]) as progress:
        assert progress.format_eta() == expected


@pytest.mark.parametrize("pos, length", [(0, 5), (-1, 1), (5, 5), (6, 5), (4, 0)])
def test_progressbar_format_pos(runner, pos, length):
    with _create_progress(length, pos=pos) as progress:
        result = progress.format_pos()
        assert result == f"{pos}/{length}"


@pytest.mark.parametrize(
    "length, finished, pos, avg, expected",
    [
        (8, False, 7, 0, "#######-"),
        (0, True, 8, 0, "########"),
    ],
)
def test_progressbar_format_bar(runner, length, finished, pos, avg, expected):
    with _create_progress(
        length, width=8, pos=pos, finished=finished, avg=[avg]
    ) as progress:
        assert progress.format_bar() == expected


@pytest.mark.parametrize(
    "length, show_percent, show_pos, pos, expected",
    [
        (0, True, True, 0, "  [--------]  0/0    0%"),
        (0, False, True, 0, "  [--------]  0/0"),
        (0, False, False, 0, "  [--------]"),
        (0, False, False, 0, "  [--------]"),
        (8, True, True, 8, "  [########]  8/8  100%"),
    ],
)
def test_progressbar_format_progress_line(
    runner, length, show_percent, show_pos, pos, expected
):
    with _create_progress(
        length,
        width=8,
        show_percent=show_percent,
        pos=pos,
        show_pos=show_pos,
    ) as progress:
        assert progress.format_progress_line() == expected


@pytest.mark.parametrize("test_item", ["test", None])
def test_progressbar_format_progress_line_with_show_func(runner, test_item):
    def item_show_func(item):
        return item

    with _create_progress(
        item_show_func=item_show_func, current_item=test_item
    ) as progress:
        if test_item:
            assert progress.format_progress_line().endswith(test_item)
        else:
            assert progress.format_progress_line().endswith(progress.format_pct())


def test_progressbar_init_exceptions(runner):
    with pytest.raises(TypeError, match="iterable or length is required"):
        click.progressbar()


def test_progressbar_iter_outside_with_exceptions(runner):
    progress = click.progressbar(length=2)

    with pytest.raises(RuntimeError, match="with block"):
        iter(progress)


def test_progressbar_is_iterator(runner, monkeypatch):
    @click.command()
    def cli():
        with click.progressbar(range(10), label="test") as progress:
            while True:
                try:
                    next(progress)
                except StopIteration:
                    break

    monkeypatch.setattr(click._termui_impl, "isatty", lambda _: True)
    result = runner.invoke(cli, [])
    assert result.exception is None


def test_choices_list_in_prompt(runner, monkeypatch):
    @click.command()
    @click.option(
        "-g", type=click.Choice(["none", "day", "week", "month"]), prompt=True
    )
    def cli_with_choices(g):
        pass

    @click.command()
    @click.option(
        "-g",
        type=click.Choice(["none", "day", "week", "month"]),
        prompt=True,
        show_choices=False,
    )
    def cli_without_choices(g):
        pass

    result = runner.invoke(cli_with_choices, [], input="none")
    assert "(none, day, week, month)" in result.output

    result = runner.invoke(cli_without_choices, [], input="none")
    assert "(none, day, week, month)" not in result.output


@pytest.mark.parametrize(
    "file_kwargs", [{"mode": "rt"}, {"mode": "rb"}, {"lazy": True}]
)
def test_file_prompt_default_format(runner, file_kwargs):
    @click.command()
    @click.option("-f", default=__file__, prompt="file", type=click.File(**file_kwargs))
    def cli(f):
        click.echo(f.name)

    result = runner.invoke(cli)
    assert result.output == f"file [{__file__}]: \n{__file__}\n"


def test_secho(runner):
    with runner.isolation() as outstreams:
        click.secho(None, nl=False)
        bytes = outstreams[0].getvalue()
        assert bytes == b""


@pytest.mark.skipif(platform.system() == "Windows", reason="No style on Windows.")
@pytest.mark.parametrize(
    ("value", "expect"), [(123, b"\x1b[45m123\x1b[0m"), (b"test", b"test")]
)
def test_secho_non_text(runner, value, expect):
    with runner.isolation() as (out, _):
        click.secho(value, nl=False, color=True, bg="magenta")
        result = out.getvalue()
        assert result == expect


def test_progressbar_yields_all_items(runner):
    with click.progressbar(range(3)) as progress:
        assert len(list(progress)) == 3


def test_progressbar_update(runner, monkeypatch):
    fake_clock = FakeClock()

    @click.command()
    def cli():
        with click.progressbar(range(4)) as progress:
            for _ in progress:
                fake_clock.advance_time()
                print("")

    monkeypatch.setattr(time, "time", fake_clock.time)
    monkeypatch.setattr(click._termui_impl, "isatty", lambda _: True)
    output = runner.invoke(cli, []).output

    lines = [line for line in output.split("\n") if "[" in line]

    assert "  0%" in lines[0]
    assert " 25%  00:00:03" in lines[1]
    assert " 50%  00:00:02" in lines[2]
    assert " 75%  00:00:01" in lines[3]
    assert "100%          " in lines[4]


def test_progressbar_item_show_func(runner, monkeypatch):
    """item_show_func should show the current item being yielded."""

    @click.command()
    def cli():
        with click.progressbar(range(3), item_show_func=lambda x: str(x)) as progress:
            for item in progress:
                click.echo(f" item {item}")

    monkeypatch.setattr(click._termui_impl, "isatty", lambda _: True)
    lines = runner.invoke(cli).output.splitlines()

    for i, line in enumerate(x for x in lines if "item" in x):
        assert f"{i}    item {i}" in line


def test_progressbar_update_with_item_show_func(runner, monkeypatch):
    @click.command()
    def cli():
        with click.progressbar(
            length=6, item_show_func=lambda x: f"Custom {x}"
        ) as progress:
            while not progress.finished:
                progress.update(2, progress.pos)
                click.echo()

    monkeypatch.setattr(click._termui_impl, "isatty", lambda _: True)
    output = runner.invoke(cli, []).output

    lines = [line for line in output.split("\n") if "[" in line]

    assert "Custom 0" in lines[0]
    assert "Custom 2" in lines[1]
    assert "Custom 4" in lines[2]


def test_progress_bar_update_min_steps(runner):
    bar = _create_progress(update_min_steps=5)
    bar.update(3)
    assert bar._completed_intervals == 3
    assert bar.pos == 0
    bar.update(2)
    assert bar._completed_intervals == 0
    assert bar.pos == 5


@pytest.mark.parametrize("key_char", ("h", "H", "é", "À", " ", "字", "àH", "àR"))
@pytest.mark.parametrize("echo", [True, False])
@pytest.mark.skipif(not WIN, reason="Tests user-input using the msvcrt module.")
def test_getchar_windows(runner, monkeypatch, key_char, echo):
    monkeypatch.setattr(click._termui_impl.msvcrt, "getwche", lambda: key_char)
    monkeypatch.setattr(click._termui_impl.msvcrt, "getwch", lambda: key_char)
    monkeypatch.setattr(click.termui, "_getchar", None)
    assert click.getchar(echo) == key_char


@pytest.mark.parametrize(
    "special_key_char, key_char", [("\x00", "a"), ("\x00", "b"), ("\xe0", "c")]
)
@pytest.mark.skipif(
    not WIN, reason="Tests special character inputs using the msvcrt module."
)
def test_getchar_special_key_windows(runner, monkeypatch, special_key_char, key_char):
    ordered_inputs = [key_char, special_key_char]
    monkeypatch.setattr(
        click._termui_impl.msvcrt, "getwch", lambda: ordered_inputs.pop()
    )
    monkeypatch.setattr(click.termui, "_getchar", None)
    assert click.getchar() == f"{special_key_char}{key_char}"


@pytest.mark.parametrize(
    ("key_char", "exc"), [("\x03", KeyboardInterrupt), ("\x1a", EOFError)]
)
@pytest.mark.skipif(not WIN, reason="Tests user-input using the msvcrt module.")
def test_getchar_windows_exceptions(runner, monkeypatch, key_char, exc):
    monkeypatch.setattr(click._termui_impl.msvcrt, "getwch", lambda: key_char)
    monkeypatch.setattr(click.termui, "_getchar", None)

    with pytest.raises(exc):
        click.getchar()


@pytest.mark.skipif(platform.system() == "Windows", reason="No sed on Windows.")
def test_fast_edit(runner):
    result = click.edit("a\nb", editor="sed -i~ 's/$/Test/'")
    assert result == "aTest\nbTest\n"


@pytest.mark.parametrize(
    ("editor_cmd", "filename", "expected_args"),
    [
        pytest.param(
            "myeditor --wait --flag",
            "file1.txt",
            ["myeditor", "--wait", "--flag", "file1.txt"],
            id="editor with args",
        ),
        pytest.param(
            "vi",
            'file"; rm -rf / ; echo "',
            ["vi", 'file"; rm -rf / ; echo "'],
            id="shell metacharacters in filename",
        ),
        # The editor command comes from VISUAL/EDITOR, so metacharacters in
        # it must be passed through as plain argv items, never interpreted.
        pytest.param(
            "vi ; touch pwned",
            "f.txt",
            ["vi", ";", "touch", "pwned", "f.txt"],
            id="shell metacharacters in editor command",
        ),
        pytest.param(
            "vi && touch pwned",
            "f.txt",
            ["vi", "&&", "touch", "pwned", "f.txt"],
            id="shell and-operator in editor command",
        ),
        pytest.param(
            "vi $(touch pwned)",
            "f.txt",
            ["vi", "$(touch", "pwned)", "f.txt"],
            id="shell substitution in editor command",
        ),
        # Issue #1026: editor path with spaces must be quoted.
        pytest.param(
            '"C:\\Program Files\\Sublime Text 3\\sublime_text.exe"',
            "f.txt",
            ["C:\\Program Files\\Sublime Text 3\\sublime_text.exe", "f.txt"],
            id="quoted windows path with spaces",
        ),
        # PR #1477: pager/editor command with flags, like ``less -FRSX``.
        pytest.param(
            "less -FRSX",
            "f.txt",
            ["less", "-FRSX", "f.txt"],
            id="command with flags",
        ),
        # Issue #1026: quoted command with an option.
        pytest.param(
            '"my command" --option value arg',
            "f.txt",
            ["my command", "--option", "value", "arg", "f.txt"],
            id="quoted command with args",
        ),
        # PR #1477: unquoted unix path.
        pytest.param(
            "/usr/bin/vim",
            "f.txt",
            ["/usr/bin/vim", "f.txt"],
            id="unix absolute path",
        ),
        # Issue #1026: macOS path with escaped space.
        pytest.param(
            "/Applications/Sublime\\ Text.app/Contents/SharedSupport/bin/subl",
            "f.txt",
            ["/Applications/Sublime Text.app/Contents/SharedSupport/bin/subl", "f.txt"],
            id="escaped space in unix path",
        ),
        pytest.param(
            "  vim  ",
            "f.txt",
            ["vim", "f.txt"],
            id="leading and trailing whitespace",
        ),
        pytest.param(
            "vim\t-N",
            "f.txt",
            ["vim", "-N", "f.txt"],
            id="tab-separated tokens",
        ),
        pytest.param(
            "'/Applications/My Editor.app/Contents/MacOS/editor'",
            "f.txt",
            ["/Applications/My Editor.app/Contents/MacOS/editor", "f.txt"],
            id="single-quoted path with spaces",
        ),
        pytest.param(
            '"my editor" --wait --new-window',
            "file 1.txt",
            ["my editor", "--wait", "--new-window", "file 1.txt"],
            id="quoted editor with flags and filename with spaces",
        ),
        pytest.param(
            "vim -u NONE -N",
            "f.txt",
            ["vim", "-u", "NONE", "-N", "f.txt"],
            id="multiple short flags",
        ),
        pytest.param(
            "editor",
            'file"name.txt',
            ["editor", 'file"name.txt'],
            id="filename with double quote",
        ),
        pytest.param(
            "editor",
            "file'name.txt",
            ["editor", "file'name.txt"],
            id="filename with single quote",
        ),
    ],
)
def test_editor_path_normalization(editor_cmd, filename, expected_args):
    """The editor command is split into an argv list and passed to
    ``Popen`` without a shell, so its content is never interpreted.
    """
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value.wait.return_value = 0
        Editor(editor=editor_cmd).edit_file(filename)

        mock_popen.assert_called_once()
        args = mock_popen.call_args[1].get("args") or mock_popen.call_args[0][0]
        assert args == expected_args
        assert mock_popen.call_args[1].get("shell") is None


@pytest.mark.parametrize("env_key", ["VISUAL", "EDITOR"])
def test_editor_env_var_not_shell_interpreted(monkeypatch, env_key):
    """An editor taken from ``VISUAL``/``EDITOR`` is not run through a
    shell, so it cannot be used to inject commands.
    """
    monkeypatch.delitem(os.environ, "VISUAL", raising=False)
    monkeypatch.delitem(os.environ, "EDITOR", raising=False)
    monkeypatch.setitem(os.environ, env_key, "vi ; touch pwned")

    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value.wait.return_value = 0
        Editor().edit_file("f.txt")

        args = mock_popen.call_args[1].get("args") or mock_popen.call_args[0][0]
        assert args == ["vi", ";", "touch", "pwned", "f.txt"]
        assert mock_popen.call_args[1].get("shell") is None


@pytest.mark.skipif(WIN, reason="Uses POSIX shell syntax and the echo command.")
def test_editor_no_command_injection(monkeypatch, tmp_path):
    """An ``EDITOR`` value carrying shell metacharacters must not execute
    the injected command.
    """
    marker = tmp_path / "pwned.txt"
    monkeypatch.delitem(os.environ, "VISUAL", raising=False)
    monkeypatch.setitem(os.environ, "EDITOR", f"echo ; touch {marker}")

    click.edit("a\nb")

    assert not marker.exists()


@pytest.mark.skipif(not WIN, reason="Windows-specific editor paths")
@pytest.mark.parametrize(
    ("editor_cmd", "expected_cmd"),
    [
        pytest.param(
            "notepad",
            ["notepad"],
            id="plain notepad",
        ),
        pytest.param(
            '"C:\\Program Files\\Sublime Text 3\\sublime_text.exe" --wait',
            ["C:\\Program Files\\Sublime Text 3\\sublime_text.exe", "--wait"],
            id="quoted path with flag",
        ),
    ],
)
def test_editor_windows_path_normalization(editor_cmd, expected_cmd):
    """Windows-specific tests: verify ``Popen`` receives unquoted paths that
    ``subprocess.list2cmdline`` can re-quote for ``CreateProcess``."""
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value.wait.return_value = 0
        Editor(editor=editor_cmd).edit_file("f.txt")

        args = mock_popen.call_args[1].get("args") or mock_popen.call_args[0][0]
        assert args == expected_cmd + ["f.txt"]
        assert mock_popen.call_args[1].get("shell") is None


def test_editor_env_passed_through():
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value.wait.return_value = 0
        Editor(editor="vi", env={"MY_VAR": "1"}).edit_file("f.txt")

        env = mock_popen.call_args[1].get("env")
        assert env is not None
        assert env["MY_VAR"] == "1"


def test_editor_failure_exception():
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value.wait.return_value = 1
        with pytest.raises(click.ClickException, match="Editing failed"):
            Editor(editor="vi").edit_file("f.txt")


def test_editor_nonexistent_exception():
    with patch("subprocess.Popen", side_effect=OSError("not found")):
        with pytest.raises(click.ClickException, match="not found"):
            Editor(editor="nonexistent").edit_file("f.txt")


def test_editor_unclosed_quote():
    """An unclosed quote in the editor command raises ValueError."""
    with pytest.raises(ValueError, match="No closing quotation"):
        Editor(editor='"unclosed').edit_file("f.txt")


@pytest.mark.parametrize(
    ("pager_env", "expected_parts"),
    [
        # Simple commands.
        pytest.param("cat", ["cat"], id="simple command"),
        pytest.param("less", ["less"], id="less"),
        pytest.param("less -FRSX", ["less", "-FRSX"], id="command with flags"),
        # Whitespace handling.
        pytest.param("  less  ", ["less"], id="leading and trailing spaces"),
        pytest.param("less\t-R", ["less", "-R"], id="tab as separator"),
        # Quoted Windows paths: quotes are stripped in POSIX mode (the
        # default), preserving backslashes inside quoted tokens (issue #1026).
        pytest.param(
            '"C:\\Program Files\\Git\\usr\\bin\\less.exe"',
            ["C:\\Program Files\\Git\\usr\\bin\\less.exe"],
            id="quoted windows path with spaces",
        ),
        pytest.param(
            '"C:\\Program Files\\Git\\usr\\bin\\less.exe" -R',
            ["C:\\Program Files\\Git\\usr\\bin\\less.exe", "-R"],
            id="quoted windows path with flag",
        ),
        # Single-quoted path.
        pytest.param(
            "'/usr/local/bin/my pager'",
            ["/usr/local/bin/my pager"],
            id="single-quoted path with spaces",
        ),
        # Unix paths.
        pytest.param("/usr/bin/less", ["/usr/bin/less"], id="unix absolute path"),
        pytest.param(
            "/usr/bin/my\\ pager",
            ["/usr/bin/my pager"],
            id="escaped space in unix path",
        ),
        # PR #1477: POSIX mode (the default) eats unquoted backslashes.
        # On Windows, users must quote paths that contain backslashes.
        pytest.param(
            "C:\\path\\to\\exe /test other\\path",
            ["C:pathtoexe", "/test", "otherpath"],
            id="unquoted backslashes eaten in POSIX mode",
        ),
        # The injected command must survive as inert argv items.
        pytest.param(
            "less -R ; touch pwned",
            ["less", "-R", ";", "touch", "pwned"],
            id="shell metacharacters in pager command",
        ),
    ],
)
def test_pager_env_passed_to_popen_as_argv(monkeypatch, pager_env, expected_parts):
    """The ``PAGER`` value is normalized into an ``argv`` list and handed to
    ``subprocess.Popen`` without a shell.

    Covers the splitting logic used by :func:`click._termui_impl.pager` to
    turn the ``PAGER`` environment variable into an ``argv`` list. See
    issue #1026, PR #1477, PR #1543, PR #2775.
    """
    monkeypatch.setattr(click._termui_impl, "WIN", False)
    monkeypatch.setattr(click._termui_impl, "isatty", lambda x: True)
    # Resolve every command to itself so the expected argv is exact and the
    # test doesn't depend on which binaries the runner happens to have.
    monkeypatch.setattr(click._termui_impl, "which", lambda cmd: cmd)
    monkeypatch.setitem(os.environ, "PAGER", pager_env)

    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value.stdin = io.StringIO()
        mock_popen.return_value.wait.return_value = 0
        click.echo_via_pager("hello")

    mock_popen.assert_called_once()
    assert mock_popen.call_args[0][0] == expected_parts
    assert mock_popen.call_args[1]["shell"] is False


@pytest.mark.parametrize("pager_env", ["", "   ", "\t"])
def test_pager_env_empty_selects_no_command(monkeypatch, pager_env):
    """An empty or whitespace-only ``PAGER`` yields no command parts, so no
    pager is invoked with it.
    """
    recorded = []

    def record(generator, cmd_parts, color):
        recorded.append(cmd_parts)

    monkeypatch.setattr(click._termui_impl, "WIN", False)
    monkeypatch.setattr(click._termui_impl, "_pipepager", record)
    monkeypatch.setattr(click._termui_impl, "_tempfilepager", record)
    monkeypatch.setattr(click._termui_impl, "isatty", lambda x: True)
    monkeypatch.setitem(os.environ, "PAGER", pager_env)
    # Stop before the platform probing that follows an unset pager command.
    monkeypatch.setitem(os.environ, "TERM", "dumb")

    click.echo_via_pager("hello")

    assert recorded == []


@pytest.mark.parametrize("win", [False, True])
def test_pager_env_split_into_argv(monkeypatch, win):
    """``pager()`` hands the ``PAGER`` value to its helpers as an argv
    list, never as a shell command string.
    """
    recorded = []

    def record(generator, cmd_parts, color):
        recorded.append(cmd_parts)
        return True

    monkeypatch.setattr(click._termui_impl, "WIN", win)
    monkeypatch.setattr(click._termui_impl, "_pipepager", record)
    monkeypatch.setattr(click._termui_impl, "_tempfilepager", record)
    monkeypatch.setattr(click._termui_impl, "isatty", lambda x: True)
    monkeypatch.setitem(os.environ, "PAGER", "less -R ; touch pwned")

    click.echo_via_pager("hello")

    assert recorded == [["less", "-R", ";", "touch", "pwned"]]


@pytest.mark.skipif(WIN, reason="Uses POSIX shell syntax and the cat command.")
def test_echo_via_pager_no_command_injection(monkeypatch, tmp_path):
    """A ``PAGER`` value carrying shell metacharacters must not execute the
    injected command when the text is piped to the pager.
    """
    marker = tmp_path / "pwned.txt"
    monkeypatch.setattr(click._termui_impl, "isatty", lambda x: True)
    monkeypatch.setitem(os.environ, "PAGER", f"cat - ; touch {marker}")

    click.echo_via_pager("hello")

    assert not marker.exists()


@pytest.mark.skipif(WIN, reason="Uses POSIX shell syntax and a shell script pager.")
def test_echo_via_pager_no_shell_for_resolved_pager(monkeypatch, tmp_path):
    """The resolved pager path is executed directly, never handed to a
    shell, so metacharacters in it can't start a second command.
    """
    monkeypatch.chdir(tmp_path)
    # A directory whose name carries shell command separators. A shell would
    # split the resolved pager path on them and run "touch pwned.txt".
    bin_dir = tmp_path / "bin;touch pwned.txt;true"
    bin_dir.mkdir()
    pager_exe = bin_dir / "clickpager"
    pager_exe.write_text("#!/bin/sh\ncat > /dev/null\n")
    pager_exe.chmod(0o755)

    monkeypatch.setitem(
        os.environ, "PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    )
    monkeypatch.setattr(click._termui_impl, "isatty", lambda x: True)
    monkeypatch.setitem(os.environ, "PAGER", "clickpager")

    click.echo_via_pager("hello")

    assert not (tmp_path / "pwned.txt").exists()


@pytest.mark.skipif(WIN, reason="Uses POSIX shell syntax and the cat command.")
def test_echo_via_pager_tempfile_no_command_injection(monkeypatch, tmp_path):
    """The temp-file pager strategy, used on Windows, must not execute
    commands injected through ``PAGER`` either.
    """
    marker = tmp_path / "pwned.txt"
    monkeypatch.setattr(click._termui_impl, "WIN", True)
    monkeypatch.setattr(click._termui_impl, "isatty", lambda x: True)
    monkeypatch.setitem(os.environ, "PAGER", f"cat ; touch {marker}")

    click.echo_via_pager("hello")

    assert not marker.exists()


def test_pager_passes_arguments_to_pipe_pager(monkeypatch):
    """The pager's own arguments must reach it, they are not dropped."""
    monkeypatch.setattr(click._termui_impl, "WIN", False)
    monkeypatch.setattr(click._termui_impl, "isatty", lambda x: True)
    monkeypatch.setattr(click._termui_impl, "which", lambda cmd: cmd)
    monkeypatch.setitem(os.environ, "PAGER", "less -R")
    monkeypatch.setitem(os.environ, "LESS", "")

    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value.stdin = io.StringIO()
        mock_popen.return_value.wait.return_value = 0
        click.echo_via_pager("hello")

    assert mock_popen.call_args[0][0] == ["less", "-R"]
    # The -R flag was seen, so colors are kept rather than LESS being set.
    assert mock_popen.call_args[1]["env"]["LESS"] == ""


def test_pager_no_command_parts_falls_through():
    """The pager helpers refuse an empty argv list instead of invoking
    something unexpected.
    """
    with patch("subprocess.Popen") as mock_popen:
        assert click._termui_impl._pipepager(iter(["x"]), [], None) is False
        assert click._termui_impl._tempfilepager(iter(["x"]), [], None) is False

    mock_popen.assert_not_called()


@pytest.mark.parametrize(
    ("prompt_required", "required", "args", "expect"),
    [
        (True, False, None, "prompt"),
        (True, False, ["-v"], "Option '-v' requires an argument."),
        (False, True, None, "prompt"),
        (False, True, ["-v"], "prompt"),
    ],
)
def test_prompt_required_with_required(runner, prompt_required, required, args, expect):
    @click.command()
    @click.option("-v", prompt=True, prompt_required=prompt_required, required=required)
    def cli(v):
        click.echo(str(v))

    result = runner.invoke(cli, args, input="prompt")
    assert expect in result.output


@pytest.mark.parametrize(
    ("args", "expect"),
    [
        # Flag not passed, don't prompt.
        pytest.param(None, None, id="no flag"),
        # Flag and value passed, don't prompt.
        pytest.param(["-v", "value"], "value", id="short sep value"),
        pytest.param(["--value", "value"], "value", id="long sep value"),
        pytest.param(["-vvalue"], "value", id="short join value"),
        pytest.param(["--value=value"], "value", id="long join value"),
        # Flag without value passed, prompt.
        pytest.param(["-v"], "prompt", id="short no value"),
        pytest.param(["--value"], "prompt", id="long no value"),
        # Don't use next option flag as value.
        pytest.param(["-v", "-o", "42"], ("prompt", "42"), id="no value opt"),
    ],
)
def test_prompt_required_false(runner, args, expect):
    @click.command()
    @click.option("-v", "--value", prompt=True, prompt_required=False)
    @click.option("-o")
    def cli(value, o):
        if o is not None:
            return value, o

        return value

    result = runner.invoke(cli, args=args, input="prompt", standalone_mode=False)
    assert result.exception is None
    assert result.return_value == expect


@pytest.mark.parametrize(
    ("prompt", "input", "default", "expect"),
    [
        (True, "password\npassword", None, "password"),
        ("Confirm Password", "password\npassword\n", None, "password"),
        (True, "", "", ""),
        (False, None, None, None),
    ],
)
def test_confirmation_prompt(runner, prompt, input, default, expect):
    @click.command()
    @click.option(
        "--password",
        prompt=prompt,
        hide_input=True,
        default=default,
        confirmation_prompt=prompt,
    )
    def cli(password):
        return password

    result = runner.invoke(cli, input=input, standalone_mode=False)
    assert result.exception is None
    assert result.return_value == expect

    if prompt == "Confirm Password":
        assert "Confirm Password: " in result.output
