from __future__ import annotations

import configparser
import enum
import os
from pathlib import Path
from typing import IO, Any, Dict, TypeVar, Union

import attr
from attr import validators

from .compat import gt


class ConfigurationError(Exception):
    def __init__(self, filename: str, *args: Any) -> None:
        super().__init__(*args)
        self.filename = filename

    @property
    def message(self) -> str:
        return super().__str__()

    def __str__(self) -> str:
        return f"invalid configuration '{self.filename}': {self.message}"


class InvalidSection(ConfigurationError):
    def __init__(self, section: str, *args: Any) -> None:
        super().__init__(*args)
        self.section = section

    @property
    def message(self) -> str:
        return f"invalid section '{self.section}'"


class InvalidOptions(ConfigurationError):
    def __init__(self, section: str, message: str, *args: Any) -> None:
        super().__init__(*args)
        self.section = section
        self._message = message

    @property
    def message(self) -> str:
        return f"invalid option(s) in '{self.section}': {self._message}"


class Flag(enum.Flag):
    """Column flag.

    >>> Flag.names()
    ['database', 'appname', 'client', 'user', 'cpu', 'mem', 'read', 'write', 'time', 'wait', 'relation', 'type', 'mode', 'iowait', 'pid']
    >>> Flag.all()  # doctest: +ELLIPSIS
    <Flag...: 32767>
    """

    DATABASE = enum.auto()
    APPNAME = enum.auto()
    CLIENT = enum.auto()
    USER = enum.auto()
    CPU = enum.auto()
    MEM = enum.auto()
    READ = enum.auto()
    WRITE = enum.auto()
    TIME = enum.auto()
    WAIT = enum.auto()
    RELATION = enum.auto()
    TYPE = enum.auto()
    MODE = enum.auto()
    IOWAIT = enum.auto()
    PID = enum.auto()

    @classmethod
    def names(cls) -> list[str]:
        rv = []
        for f in cls:
            assert f.name
            rv.append(f.name.lower())
        return rv

    @classmethod
    def all(cls) -> Flag:
        value = cls(0)
        for f in cls:
            value |= f
        return value

    @classmethod
    def from_config(cls, config: Configuration) -> Flag:
        value = cls(0)
        for f in cls:
            assert f.name is not None
            try:
                cfg = config[f.name.lower()]
            except KeyError:
                pass
            else:
                assert isinstance(cfg, UISection)
                if cfg.hidden:
                    continue
            value |= f
        return value

    @classmethod
    def load(
        cls,
        config: Configuration | None,
        *,
        is_local: bool,
        noappname: bool,
        noclient: bool,
        nocpu: bool,
        nodb: bool,
        nomem: bool,
        nopid: bool,
        noread: bool,
        notime: bool,
        nouser: bool,
        nowait: bool,
        nowrite: bool,
        **kwargs: Any,
    ) -> Flag:
        """Build a Flag value from command line options."""
        if config:
            flag = cls.from_config(config)
        else:
            flag = cls.all()
        if nodb:
            flag ^= cls.DATABASE
        if nouser:
            flag ^= cls.USER
        if nocpu:
            flag ^= cls.CPU
        if noclient:
            flag ^= cls.CLIENT
        if nomem:
            flag ^= cls.MEM
        if noread:
            flag ^= cls.READ
        if nowrite:
            flag ^= cls.WRITE
        if notime:
            flag ^= cls.TIME
        if nowait:
            flag ^= cls.WAIT
        if noappname:
            flag ^= cls.APPNAME
        if nopid:
            flag ^= cls.PID

        # Remove some if no running against local pg server.
        if not is_local and (flag & cls.CPU):
            flag ^= cls.CPU
        if not is_local and (flag & cls.MEM):
            flag ^= cls.MEM
        if not is_local and (flag & cls.READ):
            flag ^= cls.READ
        if not is_local and (flag & cls.WRITE):
            flag ^= cls.WRITE
        if not is_local and (flag & cls.IOWAIT):
            flag ^= cls.IOWAIT
        return flag


class BaseSectionMixin:
    @classmethod
    def check_options(
        cls: type[attr.AttrsInstance], section: configparser.SectionProxy
    ) -> list[str]:
        """Check that items of 'section' conform to known attributes of this class and
        return the list of know options.
        """
        known_options = {f.name for f in attr.fields(cls)}
        unknown_options = set(section) - set(known_options)
        if unknown_options:
            raise ValueError(f"invalid option(s): {', '.join(sorted(unknown_options))}")
        return list(sorted(known_options))


@attr.s(auto_attribs=True, frozen=True, slots=True)
class HeaderSection(BaseSectionMixin):
    show_instance: bool = True
    show_system: bool = True
    show_workers: bool = True

    _T = TypeVar("_T", bound="HeaderSection")

    @classmethod
    def from_config_section(cls: type[_T], section: configparser.SectionProxy) -> _T:
        values: dict[str, bool] = {}
        for optname in cls.check_options(section):
            value = section.getboolean(optname)
            if value is not None:
                values[optname] = value
        return cls(**values)


@attr.s(auto_attribs=True, frozen=True, slots=True)
class UISection(BaseSectionMixin):
    hidden: bool = False
    width: int | None = attr.ib(default=None, validator=validators.optional(gt(0)))

    _T = TypeVar("_T", bound="UISection")

    @classmethod
    def from_config_section(cls: type[_T], section: configparser.SectionProxy) -> _T:
        cls.check_options(section)
        values: dict[str, Any] = {}
        hidden = section.getboolean("hidden")
        if hidden is not None:
            values["hidden"] = hidden
        values["width"] = section.getint("width")
        return cls(**values)


USER_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
ETC = Path("/etc")


class Configuration(Dict[str, Union[HeaderSection, UISection]]):
    _T = TypeVar("_T", bound="Configuration")

    def header(self) -> HeaderSection | None:
        return self.get("header")  # type: ignore[return-value]

    @classmethod
    def parse(cls: type[_T], f: IO[str], name: str) -> _T:
        r"""Parse configuration from 'f'.

        >>> from io import StringIO
        >>> from pprint import pprint

        >>> f = StringIO('[header]\nshow_workers=false\n[client]\nhidden=true\n')
        >>> cfg = Configuration.parse(f, "f.ini")
        >>> pprint(cfg)
        {'client': UISection(hidden=True, width=None),
         'header': HeaderSection(show_instance=True, show_system=True, show_workers=False)}

        >>> bad = StringIO("[global]\nx=1")
        >>> Configuration.parse(bad, "bad.ini")
        Traceback (most recent call last):
          ...
        pgactivity.config.InvalidSection: invalid configuration 'bad.ini': invalid section 'global'
        >>> bad = StringIO("[xxx]\n")
        >>> Configuration.parse(bad, "bad.ini")
        Traceback (most recent call last):
          ...
        pgactivity.config.InvalidSection: invalid configuration 'bad.ini': invalid section 'xxx'
        >>> bad = StringIO("[cpu]\nx=1")
        >>> Configuration.parse(bad, "bad.ini")
        Traceback (most recent call last):
          ...
        pgactivity.config.InvalidOptions: invalid configuration 'bad.ini': invalid option(s) in 'cpu': invalid option(s): x
        >>> bad = StringIO("[mem]\nwidth=-2")
        >>> Configuration.parse(bad, "bad.ini")
        Traceback (most recent call last):
          ...
        pgactivity.config.InvalidOptions: invalid configuration 'bad.ini': invalid option(s) in 'mem': 'width' must be > 0: -2
        >>> bad = StringIO("[mem]\nwidth=xyz")
        >>> Configuration.parse(bad, "bad.ini")
        Traceback (most recent call last):
          ...
        pgactivity.config.InvalidOptions: invalid configuration 'bad.ini': invalid option(s) in 'mem': invalid literal for int() with base 10: 'xyz'
        >>> bad = StringIO("not some INI??")
        >>> Configuration.parse(bad, "bad.txt")
        Traceback (most recent call last):
          ...
        pgactivity.config.ConfigurationError: invalid configuration 'bad.txt': failed to parse INI: File contains no section headers.
        file: '<???>', line: 1
        'not some INI??'
        """
        p = configparser.ConfigParser(default_section="global", strict=True)
        try:
            p.read_file(f)
        except configparser.Error as e:
            raise ConfigurationError(name, f"failed to parse INI: {e}") from None
        known_sections = set(Flag.names())
        config: dict[str, HeaderSection | UISection] = {}
        for sname, section in p.items():
            if sname == p.default_section:
                if section:
                    raise InvalidSection(p.default_section, name)
                continue
            if sname == "header":
                config[sname] = HeaderSection.from_config_section(section)
                continue
            if sname not in known_sections:
                raise InvalidSection(sname, name)
            try:
                config[sname] = UISection.from_config_section(section)
            except ValueError as e:
                raise InvalidOptions(sname, str(e), name) from None
        return cls(**config)

    @classmethod
    def lookup(
        cls: type[_T],
        *,
        user_config_home: Path = USER_CONFIG_HOME,
        etc: Path = ETC,
    ) -> _T | None:
        for base in (user_config_home, etc):
            fpath = base / "pg_activity.conf"
            if fpath.exists():
                with fpath.open() as f:
                    value = cls.parse(f, str(fpath))
                    return value
        return None
