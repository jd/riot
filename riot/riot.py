import importlib.abc
import importlib.util
import itertools
import logging
import os
import shutil
import subprocess
import sys
import typing as t

import attr


logger = logging.getLogger(__name__)


SHELL = "/bin/bash"
ENCODING = "utf-8"


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self


@attr.s
class Venv:
    name: t.Optional[str] = attr.ib(default=None)
    command: t.Optional[str] = attr.ib(default=None)
    pys: t.List[float] = attr.ib(default=[])
    pkgs: t.Dict[str, t.List[str]] = attr.ib(default={})
    env: t.Dict[str, t.List[str]] = attr.ib(default={})
    venvs: t.List["Venv"] = attr.ib(default=[])

    def resolve(self, parents: t.List["Venv"]) -> "Venv":
        if not parents:
            return self
        else:
            venv = Venv()
            for parent in parents + [self]:
                if parent.name:
                    venv.name = parent.name
                if parent.pys:
                    venv.pys = parent.pys
                if parent.command:
                    venv.command = parent.command
                venv.env.update(parent.env)
                venv.pkgs.update(parent.pkgs)
            return venv

    def instances(
        self,
        pattern: t.Pattern,
        parents: t.List["Venv"] = [],
    ) -> t.Generator["VenvInstance", None, None]:
        for venv in self.venvs:
            if venv.name and not pattern.match(venv.name):
                logger.debug("Skipping venv '%s' due to mismatch.", venv.name)
                continue
            else:
                for inst in venv.instances(parents=parents + [self], pattern=pattern):
                    if inst:
                        yield inst
        else:
            resolved = self.resolve(parents)

            # If the venv doesn't have a command or python then skip it.
            if not resolved.command or not resolved.pys:
                logger.debug("Skipping venv %r as it's not runnable.", self)
                return

            # Expand out the instances for the venv.
            for env in expand_specs(resolved.env):
                for py in resolved.pys:
                    for pkgs in expand_specs(resolved.pkgs):
                        yield VenvInstance(
                            name=resolved.name,
                            command=resolved.command,
                            py=py,
                            env=env,
                            pkgs=pkgs,
                        )


@attr.s
class VenvInstance:
    name: t.Optional[str] = attr.ib()
    py: float = attr.ib()
    command: str = attr.ib()
    env: t.List[t.Tuple[str, str]] = attr.ib()
    pkgs: t.List[t.Tuple[str, str]] = attr.ib()


@attr.s
class VenvInstanceResult:
    instance: VenvInstance = attr.ib()
    venv_name: str = attr.ib()
    pkgstr: str = attr.ib()
    code: int = attr.ib(default=1)


class CmdFailure(Exception):
    def __init__(self, msg, completed_proc):
        self.msg = msg
        self.proc = completed_proc
        self.code = completed_proc.returncode
        super().__init__(self, msg)


@attr.s
class Session:
    venv: Venv = attr.ib()

    @classmethod
    def from_config_file(cls, path: str) -> "Session":
        spec = importlib.util.spec_from_file_location("riotfile", path)
        config = importlib.util.module_from_spec(spec)

        # DEV: MyPy has `ModuleSpec.loader` as `Optional[_Loader`]` which doesn't have `exec_module`
        # https://github.com/python/typeshed/blob/fe58699ca5c9ee4838378adb88aaf9323e9bbcf0/stdlib/3/_importlib_modulespec.pyi#L13-L44
        t.cast(importlib.abc.Loader, spec.loader).exec_module(config)

        venv = getattr(config, "venv", Venv())
        return cls(venv=venv)

    def run(
        self,
        pattern: t.Pattern,
        skip_base_install=False,
        recreate_venvs=False,
        out: t.TextIO = sys.stdout,
        pass_env=False,
        cmdargs=None,
        pythons=[],
    ):
        results = []

        self.generate_base_venvs(
            pattern,
            recreate=recreate_venvs,
            skip_deps=skip_base_install,
            pythons=pythons,
        )

        for inst in self.venv.instances(pattern=pattern):
            if pythons and inst.py not in pythons:
                logger.debug("Skipping venv instance %s due to Python version", inst)
                continue

            base_venv = get_base_venv_path(inst.py)

            # Resolve the packages required for this instance.
            pkgs: t.Dict[str, str] = {
                name: version for name, version in inst.pkgs if version is not None
            }

            if pkgs:
                # Strip special characters for the venv directory name.
                venv_postfix = "_".join(
                    [f"{n}{rmchars('<=>.,', v)}" for n, v in pkgs.items()]
                )
                venv_name = f"{base_venv}_{venv_postfix}"
                pkg_str = " ".join(
                    [f"'{get_pep_dep(lib, version)}'" for lib, version in pkgs.items()]
                )
            else:
                venv_name = base_venv
                pkg_str = ""

            # Result which will be updated with the test outcome.
            result = VenvInstanceResult(
                instance=inst, venv_name=venv_name, pkgstr=pkg_str
            )

            try:
                if pkgs:
                    # Copy the base venv to use for this venv.
                    logger.info(
                        "Copying base virtualenv '%s' into virtualenv '%s'.",
                        base_venv,
                        venv_name,
                    )
                    try:
                        run_cmd(
                            ["cp", "-r", base_venv, venv_name], stdout=subprocess.PIPE
                        )
                    except CmdFailure as e:
                        raise CmdFailure(
                            f"Failed to create virtualenv '{venv_name}'\n{e.proc.stdout}",
                            e.proc,
                        )

                    logger.info("Installing venv dependencies %s.", pkg_str)
                    try:
                        run_cmd_venv(
                            venv_name,
                            f"pip --disable-pip-version-check install {pkg_str}",
                        )
                    except CmdFailure as e:
                        raise CmdFailure(
                            f"Failed to install venv dependencies {pkg_str}\n{e.proc.stdout}",
                            e.proc,
                        )

                # Generate the environment for the instance.
                env = os.environ.copy() if pass_env else {}

                # Add in the instance env vars.
                for k, v in inst.env:
                    resolved_val = v(AttrDict(pkgs=pkgs)) if callable(v) else v
                    if resolved_val is not None:
                        if k in env:
                            logger.debug("Venv overrides environment variable %s", k)
                        env[k] = resolved_val

                # Finally, run the test in the venv.
                cmd = inst.command
                env_str = " ".join(f"{k}={v}" for k, v in env.items())
                logger.info("Running command '%s' with environment '%s'.", cmd, env_str)
                try:
                    # Pipe the command output directly to `out` since we
                    # don't need to store it.
                    run_cmd_venv(venv_name, cmd, stdout=out, env=env, cmdargs=cmdargs)
                except CmdFailure as e:
                    raise CmdFailure(
                        f"Test failed with exit code {e.proc.returncode}", e.proc
                    )
            except CmdFailure as e:
                result.code = e.code
                print(e.msg, file=out)
            except KeyboardInterrupt:
                result.code = 1
                break
            except Exception as e:
                logger.error("Test runner failed: %s", e, exc_info=True)
                sys.exit(1)
            else:
                result.code = 0
            finally:
                results.append(result)

        print("\n-------------------summary-------------------", file=out)
        for r in results:
            failed = r.code != 0
            status_char = "✖️" if failed else "✔️"
            env_str = get_env_str(r.instance.env)
            s = f"{status_char}  {r.instance.name}: {env_str} python{r.instance.py} {r.pkgstr}"
            print(s, file=out)

        if any(True for r in results if r.code != 0):
            sys.exit(1)

    def list_venvs(self, pattern, out=sys.stdout):
        for inst in self.venv.instances(pattern=pattern):
            pkgs_str = " ".join(
                f"'{get_pep_dep(name, version)}'" for name, version in inst.pkgs
            )
            env_str = get_env_str(inst.env)
            py_str = f"Python {inst.py}"
            print(f"{inst.name} {env_str} {py_str} {pkgs_str}", file=out)

    def generate_base_venvs(self, pattern: t.Pattern, recreate, skip_deps, pythons):
        """Generate all the required base venvs."""
        # Find all the python versions used.
        required_pys = set([inst.py for inst in self.venv.instances(pattern=pattern)])
        # Apply Python filters.
        if pythons:
            required_pys = required_pys.intersection(pythons)

        logger.info(
            "Generating virtual environments for Python versions %s",
            ",".join(str(s) for s in required_pys),
        )

        for py in required_pys:
            try:
                venv_path = create_base_venv(py, recreate=recreate)
            except CmdFailure as e:
                logger.error("Failed to create virtual environment.\n%s", e.proc.stdout)
            except FileNotFoundError:
                logger.error("Python version '%s' not found.", py)
            else:
                if skip_deps:
                    logger.info("Skipping global deps install.")
                    continue

                # Install the dev package into the base venv.
                logger.info("Installing dev package.")
                try:
                    run_cmd_venv(
                        venv_path, "pip --disable-pip-version-check install -e ."
                    )
                except CmdFailure as e:
                    logger.error("Dev install failed, aborting!\n%s", e.proc.stdout)
                    sys.exit(1)


def rmchars(chars: str, s: str):
    for c in chars:
        s = s.replace(c, "")
    return s


def get_pep_dep(libname: str, version: str):
    """Returns a valid PEP 508 dependency string.

    ref: https://www.python.org/dev/peps/pep-0508/
    """
    return f"{libname}{version}"


def get_env_str(envs: t.List[t.Tuple[str, str]]):
    return " ".join(f"{k}={v}" for k, v in envs)


def get_base_venv_path(pyversion):
    """Given a python version return the base virtual environment path relative
    to the current directory.
    """
    pyversion = str(pyversion).replace(".", "")
    return f".riot/.venv_py{pyversion}"


def run_cmd(*args, **kwargs):
    # Provide our own defaults.
    if "shell" in kwargs and "executable" not in kwargs:
        kwargs["executable"] = SHELL
    if "encoding" not in kwargs:
        kwargs["encoding"] = ENCODING
    if "stdout" not in kwargs:
        kwargs["stdout"] = subprocess.PIPE

    # insert command args if passed
    if "cmdargs" in kwargs:
        cmd = args[0]
        args = (cmd.format(cmdargs=kwargs["cmdargs"]),) + args[1:]
        del kwargs["cmdargs"]

    logger.debug("Running command %s", args[0])
    r = subprocess.run(*args, **kwargs)
    logger.debug(r.stdout)

    if r.returncode != 0:
        raise CmdFailure("Command %s failed with code %s." % (args[0], r.returncode), r)
    return r


def create_base_venv(pyversion, path=None, recreate=True):
    """Attempts to create a virtual environment for `pyversion`.

    :param pyversion: string or int representing the major.minor Python
                      version. eg. 3.7, "3.8".
    """
    path = path or get_base_venv_path(pyversion)

    if os.path.isdir(path) and not recreate:
        logger.info("Skipping creation of virtualenv '%s' as it already exists.", path)
        return path

    py_ex = f"python{pyversion}"
    py_ex = shutil.which(py_ex)

    if not py_ex:
        logger.debug("%s interpreter not found", py_ex)
        raise FileNotFoundError
    else:
        logger.info("Found Python interpreter '%s'.", py_ex)

    logger.info("Creating virtualenv '%s' with Python '%s'.", path, py_ex)
    r = run_cmd(["virtualenv", f"--python={py_ex}", path], stdout=subprocess.PIPE)
    return path


def get_venv_command(venv_path, cmd):
    """Return the command string used to execute `cmd` in virtual env located
    at `venv_path`.
    """
    return f"source {venv_path}/bin/activate && {cmd}"


def run_cmd_venv(venv, cmd, **kwargs):
    env = kwargs.get("env") or {}
    env_str = " ".join(f"{k}={v}" for k, v in env.items())
    cmd = get_venv_command(venv, cmd)

    logger.debug("Executing command '%s' with environment '%s'", cmd, env_str)
    r = run_cmd(cmd, shell=True, **kwargs)
    return r


def expand_specs(specs):
    """
    [(X, [X0, X1, ...]), (Y, [Y0, Y1, ...)] ->
      ((X, X0), (Y, Y0)), ((X, X0), (Y, Y1)), ((X, X1), (Y, Y0)), ((X, X1), (Y, Y1))
    """
    all_vals = []

    for name, vals in specs.items():
        all_vals.append([(name, val) for val in vals])

    all_vals = itertools.product(*all_vals)
    return all_vals
