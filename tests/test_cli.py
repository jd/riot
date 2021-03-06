import contextlib
import os
import re
import shutil
import typing


import click.testing
import mock
import pytest

import riot.cli
import riot.riot


HERE = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(HERE, "data")


@pytest.fixture
def cli() -> click.testing.CliRunner:
    return click.testing.CliRunner()


@contextlib.contextmanager
def with_riotfile(
    cli: click.testing.CliRunner, riotfile: str, dst_filename: str = "riotfile.py"
) -> typing.Generator[None, None, None]:
    with cli.isolated_filesystem() as fs_dir:
        shutil.copy(
            os.path.join(DATA_DIR, riotfile), os.path.join(fs_dir, dst_filename)
        )
        yield


@contextlib.contextmanager
def without_riotfile(
    cli: click.testing.CliRunner,
) -> typing.Generator[None, None, None]:
    with cli.isolated_filesystem():
        yield


def test_main(cli: click.testing.CliRunner):
    """Running main with no command returns usage"""
    result = cli.invoke(riot.cli.main)
    assert result.exit_code == 0
    assert result.stdout.startswith("Usage: main")


def test_main_help(cli: click.testing.CliRunner):
    """Running main with --help returns usage"""
    result = cli.invoke(riot.cli.main, ["--help"])
    assert result.exit_code == 0
    assert result.stdout.startswith("Usage: main")


def test_main_version(cli: click.testing.CliRunner):
    """Running main with --version returns version string"""
    result = cli.invoke(riot.cli.main, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("main, version ")


def test_list_empty(cli: click.testing.CliRunner):
    """Running list with an empty riotfile prints nothing"""
    with with_riotfile(cli, "empty_riotfile.py"):
        result = cli.invoke(riot.cli.main, ["list"])
        assert result.exit_code == 0
        assert result.stdout == ""


def test_list_no_riotfile(cli: click.testing.CliRunner):
    """Running list with no riotfile fails with an error"""
    with without_riotfile(cli):
        result = cli.invoke(riot.cli.main, ["list"])
        assert result.exit_code == 2
        assert result.stdout.startswith("Usage: main")
        assert result.stdout.endswith(
            "Error: Invalid value for '-f' / '--file': Path 'riotfile.py' does not exist.\n"
        )


def test_list_default_pattern(cli: click.testing.CliRunner):
    """Running list with no pattern passes through the default pattern"""
    with mock.patch("riot.cli.Session.list_venvs") as list_venvs:
        with with_riotfile(cli, "empty_riotfile.py"):
            result = cli.invoke(riot.cli.main, ["list"])
            # Success, but no output because we don't have a matching pattern
            assert result.exit_code == 0
            assert result.stdout == ""

            list_venvs.assert_called_once()
            assert list_venvs.call_args.args[0].pattern == ".*"


def test_list_with_pattern(cli: click.testing.CliRunner):
    """Running list with a pattern passes through the pattern"""
    with mock.patch("riot.cli.Session.list_venvs") as list_venvs:
        with with_riotfile(cli, "empty_riotfile.py"):
            result = cli.invoke(riot.cli.main, ["list", "^pattern.*"])
            # Success, but no output because we don't have a matching pattern
            assert result.exit_code == 0
            assert result.stdout == ""

            list_venvs.assert_called_once()
            assert list_venvs.call_args.args[0].pattern == "^pattern.*"


def test_run(cli: click.testing.CliRunner):
    """Running run with default options"""
    with mock.patch("riot.cli.Session.run") as run:
        with with_riotfile(cli, "empty_riotfile.py"):
            result = cli.invoke(riot.cli.main, ["run"])
            # Success, but no output because we mock run
            assert result.exit_code == 0
            assert result.stdout == ""

            run.assert_called_once()
            kwargs = run.call_args.kwargs
            assert set(kwargs.keys()) == set(
                [
                    "pattern",
                    "recreate_venvs",
                    "skip_base_install",
                    "pass_env",
                    "cmdargs",
                    "pythons",
                ]
            )
            assert kwargs["pattern"].pattern == ".*"
            assert kwargs["recreate_venvs"] == False
            assert kwargs["skip_base_install"] == False
            assert kwargs["pass_env"] == False


def test_run_with_long_args(cli: click.testing.CliRunner):
    """Running run with long option names uses those options"""
    with mock.patch("riot.cli.Session.run") as run:
        with with_riotfile(cli, "empty_riotfile.py"):
            result = cli.invoke(
                riot.cli.main,
                ["run", "--recreate-venvs", "--skip-base-install", "--pass-env"],
            )
            # Success, but no output because we mock run
            assert result.exit_code == 0
            assert result.stdout == ""

            run.assert_called_once()
            kwargs = run.call_args.kwargs
            assert set(kwargs.keys()) == set(
                [
                    "pattern",
                    "recreate_venvs",
                    "skip_base_install",
                    "pass_env",
                    "cmdargs",
                    "pythons",
                ]
            )
            assert kwargs["pattern"].pattern == ".*"
            assert kwargs["recreate_venvs"] == True
            assert kwargs["skip_base_install"] == True
            assert kwargs["pass_env"] == True


def test_run_with_short_args(cli: click.testing.CliRunner):
    """Running run with short option names uses those options"""
    with mock.patch("riot.cli.Session.run") as run:
        with with_riotfile(cli, "empty_riotfile.py"):
            result = cli.invoke(riot.cli.main, ["run", "-r", "-s"])
            # Success, but no output because we mock run
            assert result.exit_code == 0
            assert result.stdout == ""

            run.assert_called_once()
            kwargs = run.call_args.kwargs
            assert set(kwargs.keys()) == set(
                [
                    "pattern",
                    "recreate_venvs",
                    "skip_base_install",
                    "pass_env",
                    "cmdargs",
                    "pythons",
                ]
            )
            assert kwargs["pattern"].pattern == ".*"
            assert kwargs["recreate_venvs"] == True
            assert kwargs["skip_base_install"] == True
            assert kwargs["pass_env"] == False


def test_run_with_pattern(cli: click.testing.CliRunner):
    """Running run with pattern passes in that pattern"""
    with mock.patch("riot.cli.Session.run") as run:
        with with_riotfile(cli, "empty_riotfile.py"):
            result = cli.invoke(riot.cli.main, ["run", "^pattern.*"])
            # Success, but no output because we mock run
            assert result.exit_code == 0
            assert result.stdout == ""

            run.assert_called_once()
            kwargs = run.call_args.kwargs
            assert set(kwargs.keys()) == set(
                [
                    "pattern",
                    "recreate_venvs",
                    "skip_base_install",
                    "pass_env",
                    "cmdargs",
                    "pythons",
                ]
            )
            assert kwargs["pattern"].pattern == "^pattern.*"
            assert kwargs["recreate_venvs"] == False
            assert kwargs["skip_base_install"] == False
            assert kwargs["pass_env"] == False


def test_generate_suites_with_long_args(cli: click.testing.CliRunner):
    """Generatening generate with long option names uses those options"""
    with mock.patch("riot.cli.Session.generate_base_venvs") as generate_base_venvs:
        with with_riotfile(cli, "empty_riotfile.py"):
            result = cli.invoke(
                riot.cli.main,
                ["generate", "--recreate-venvs", "--skip-base-install"],
            )
            # Success, but no output because we mock generate_base_venvs
            assert result.exit_code == 0
            assert result.stdout == ""

            generate_base_venvs.assert_called_once()
            kwargs = generate_base_venvs.call_args.kwargs
            assert set(kwargs.keys()) == set(
                ["pattern", "recreate", "skip_deps", "pythons"]
            )
            assert kwargs["pattern"].pattern == ".*"
            assert kwargs["recreate"] == True
            assert kwargs["skip_deps"] == True


def test_generate_base_venvs_with_short_args(cli: click.testing.CliRunner):
    """Generatening generate with short option names uses those options"""
    with mock.patch("riot.cli.Session.generate_base_venvs") as generate_base_venvs:
        with with_riotfile(cli, "empty_riotfile.py"):
            result = cli.invoke(riot.cli.main, ["generate", "-r", "-s"])
            # Success, but no output because we mock generate_base_venvs
            assert result.exit_code == 0
            assert result.stdout == ""

            generate_base_venvs.assert_called_once()
            kwargs = generate_base_venvs.call_args.kwargs
            assert set(kwargs.keys()) == set(
                ["pattern", "recreate", "skip_deps", "pythons"]
            )
            assert kwargs["pattern"].pattern == ".*"
            assert kwargs["recreate"] == True
            assert kwargs["skip_deps"] == True


def test_generate_base_venvs_with_pattern(cli: click.testing.CliRunner):
    """Generatening generate with pattern passes in that pattern"""
    with mock.patch("riot.cli.Session.generate_base_venvs") as generate_base_venvs:
        with with_riotfile(cli, "empty_riotfile.py"):
            result = cli.invoke(riot.cli.main, ["generate", "^pattern.*"])
            # Success, but no output because we mock generate_base_venvs
            assert result.exit_code == 0
            assert result.stdout == ""

            generate_base_venvs.assert_called_once()
            kwargs = generate_base_venvs.call_args.kwargs
            assert set(kwargs.keys()) == set(
                ["pattern", "recreate", "skip_deps", "pythons"]
            )
            assert kwargs["pattern"].pattern == "^pattern.*"
            assert kwargs["recreate"] == False
            assert kwargs["skip_deps"] == False


@pytest.mark.parametrize(
    "name,cmdargs,cmdrun",
    [
        ("test_cmdargs", None, "echo cmdargs="),
        ("test_cmdargs", "-k filter", "echo cmdargs=-k filter"),
        ("test_nocmdargs", None, "echo no cmdargs"),
        ("test_nocmdargs", "-k filter", "echo no cmdargs"),
    ],
)
def test_run_suites_cmdargs_not_set(
    cli: click.testing.CliRunner, name: str, cmdargs: str, cmdrun: str
):
    """Running command with optional infix cmdargs"""
    with cli.isolated_filesystem():
        with open("riotfile.py", "w") as f:
            f.write(
                """
from riot import Venv

venv = Venv(
    venvs=[
        Venv(
            name="test_nocmdargs",
            command="echo no cmdargs",
            venvs=[
                Venv(
                    pys=[3.8],
                ),
            ],
        ),
        Venv(
            name="test_cmdargs",
            command="echo cmdargs={cmdargs}",
            venvs=[
                Venv(
                    pys=[3.8],
                ),
            ],
        ),
    ]
)
            """
            )
        with mock.patch("subprocess.run") as subprocess_run:
            subprocess_run.return_value.returncode = 0
            args = ["run", name]
            if cmdargs:
                args += ["--cmdargs", cmdargs]
            result = cli.invoke(riot.cli.main, args, catch_exceptions=False)
            assert result.exit_code == 0
            assert result.stdout == ""

            subprocess_run.assert_called()

            cmd = subprocess_run.call_args_list[-1].args[0]
            assert cmd.endswith(cmdrun)


def test_nested_venv(cli: click.testing.CliRunner):
    with cli.isolated_filesystem():
        with open("riotfile.py", "w") as f:
            f.write(
                """
from riot import Venv

venv = Venv(
    pys=[3],
    pkgs={
        "pytest": [""],
    },
    venvs=[
        Venv(
            name="success",
            command="pytest test_success.py",
        ),
        Venv(
            name="failure",
            command="pytest test_failure.py",
        ),
    ],
)
            """
            )

        with open("test_success.py", "w") as f:
            f.write(
                """
def test_success():
    assert 1 == 1
            """
            )

        with open("test_failure.py", "w") as f:
            f.write(
                """
def test_failure():
    assert 1 == 0
            """
            )

        result = cli.invoke(riot.cli.main, ["run", "-s", "success"])
        assert result.exit_code == 0
        assert result.stdout == ""

        result = cli.invoke(riot.cli.main, ["run", "-s", "failure"])
        assert result.exit_code == 1
        assert result.stdout == ""
