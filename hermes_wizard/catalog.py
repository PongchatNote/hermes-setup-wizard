"""Load step, setting, gateway, and health catalogs from YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hermes_wizard.paths import data_dir

DENYLIST_ENV = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "PYTHONPATH",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "HERMES_YOLO_MODE",
    }
)


@dataclass
class Link:
    label_en: str
    label_th: str
    url: str


@dataclass
class Step:
    id: str
    title_en: str
    title_th: str
    summary_en: str
    summary_th: str
    shell: str
    privilege: str = "none"  # none | root | sudo-cache
    optional: bool = False
    source: str = ""
    fix_hint_en: str = ""
    fix_hint_th: str = ""
    command_hint: str = ""
    where_en: str = ""
    where_th: str = ""
    example: str = ""
    links: list[Link] = field(default_factory=list)


@dataclass
class Setting:
    key: str
    group: str
    type: str
    title_en: str
    title_th: str
    help_en: str
    help_th: str
    storage: str = "yaml"  # yaml | env
    secret: bool = False
    optional: bool = True
    default: Any = None
    choices: list[str] = field(default_factory=list)
    source: str = ""
    placeholder: str = ""
    where_en: str = ""
    where_th: str = ""
    example: str = ""
    links: list[Link] = field(default_factory=list)


@dataclass
class Group:
    id: str
    title_en: str
    title_th: str


@dataclass
class GatewayField:
    key: str
    title_en: str
    title_th: str
    help_en: str
    help_th: str
    secret: bool = False
    storage: str = "env"
    placeholder: str = ""
    where_en: str = ""
    where_th: str = ""
    example: str = ""
    links: list[Link] = field(default_factory=list)


@dataclass
class Gateway:
    id: str
    title_en: str
    title_th: str
    doc: str
    steps_en: str
    steps_th: str
    enabled_key: str = ""
    test: str = "none"
    token_key: str = ""
    banner_en: str = ""
    banner_th: str = ""
    fields: list[GatewayField] = field(default_factory=list)


@dataclass
class Check:
    id: str
    title_en: str
    title_th: str
    kind: str
    fix_page: str
    optional: bool = False
    shell: str = ""
    detail_en: str = ""
    detail_th: str = ""


# Sidebar order for the path the owner follows. Other pages hang off this.
MAIN_FLOW = ("install", "provider", "telegram", "discord", "line", "health")


def _links(raw: Any) -> list[Link]:
    links: list[Link] = []
    for item in raw or []:
        if isinstance(item, str):
            links.append(Link(item, item, item))
            continue
        url = str(item.get("url", "")).strip()
        if not url:
            continue
        label_en = str(item.get("label_en") or url)
        label_th = str(item.get("label_th") or label_en)
        links.append(Link(label_en, label_th, url))
    return links


def _hint_from(item: dict[str, Any], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    src = dict(meta or {})
    src.update(item)
    return {
        "where_en": str(src.get("where_en") or "").strip(),
        "where_th": str(src.get("where_th") or "").strip(),
        "example": str(src.get("example") or "").strip(),
        "links": _links(src.get("links")),
    }


def _load(name: str, root: Path | None = None) -> dict[str, Any]:
    path = (root or data_dir()) / name
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a mapping")
    return data


def load_steps(root: Path | None = None) -> list[Step]:
    raw = _load("steps.yaml", root).get("steps") or []
    steps: list[Step] = []
    for item in raw:
        steps.append(
            Step(
                id=str(item["id"]),
                title_en=str(item.get("title_en", item["id"])),
                title_th=str(item.get("title_th", item["id"])),
                summary_en=str(item.get("summary_en", "")).strip(),
                summary_th=str(item.get("summary_th", "")).strip(),
                shell=str(item.get("shell", "")).strip(),
                privilege=str(item.get("privilege", "none")),
                optional=bool(item.get("optional", False)),
                source=str(item.get("source", "")),
                fix_hint_en=str(item.get("fix_hint_en", "")).strip(),
                fix_hint_th=str(item.get("fix_hint_th", "")).strip(),
                command_hint=str(item.get("command_hint", "")).strip(),
                **_hint_from(item),
            )
        )
    ids = [step.id for step in steps]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate step id")
    for step in steps:
        if step.privilege not in {"none", "root", "sudo-cache"}:
            raise ValueError(f"step {step.id} has unknown privilege {step.privilege}")
        if not step.shell:
            raise ValueError(f"step {step.id} has no shell")
    return steps


def load_groups(root: Path | None = None) -> list[Group]:
    raw = _load("settings.yaml", root).get("groups") or []
    return [
        Group(
            id=str(item["id"]),
            title_en=str(item.get("title_en", item["id"])),
            title_th=str(item.get("title_th", item["id"])),
        )
        for item in raw
    ]


def load_settings(root: Path | None = None) -> list[Setting]:
    raw = _load("settings.yaml", root).get("settings") or []
    settings: list[Setting] = []
    for item in raw:
        settings.append(
            Setting(
                key=str(item["key"]),
                group=str(item.get("group", "more")),
                type=str(item.get("type", "str")),
                title_en=str(item.get("title_en", item["key"])),
                title_th=str(item.get("title_th", item["key"])),
                help_en=str(item.get("help_en", "")).strip(),
                help_th=str(item.get("help_th", "")).strip(),
                storage=str(item.get("storage", "yaml")),
                secret=bool(item.get("secret", False)),
                optional=bool(item.get("optional", True)),
                default=item.get("default", None),
                choices=[str(choice) for choice in (item.get("choices") or [])],
                source=str(item.get("source", "")),
                placeholder=str(item.get("placeholder", "")),
                **_hint_from(item),
            )
        )
    _validate_settings(settings)
    return settings


def load_secrets(root: Path | None = None) -> list[Setting]:
    loaded = _load("secrets.yaml", root)
    raw = loaded.get("secrets") or []
    meta = loaded.get("field_meta") or {}
    settings: list[Setting] = []
    for item in raw:
        settings.append(
            Setting(
                key=str(item["key"]),
                group="secrets",
                type=str(item.get("type", "str")),
                title_en=str(item.get("title_en", item["key"])),
                title_th=str(item.get("title_th", item["key"])),
                help_en=str(item.get("help_en", "")).strip(),
                help_th=str(item.get("help_th", "")).strip(),
                storage="env",
                secret=bool(item.get("secret", True)),
                optional=bool(item.get("optional", True)),
                default=item.get("default", None),
                choices=[str(choice) for choice in (item.get("choices") or [])],
                source=str(item.get("source", "")),
                placeholder=str(item.get("placeholder", "")),
                **_hint_from(item, meta.get(item["key"])),
            )
        )
    _validate_settings(settings)
    return settings


def load_gateways(root: Path | None = None) -> list[Gateway]:
    loaded = _load("gateways.yaml", root)
    raw = loaded.get("gateways") or []
    meta = loaded.get("field_meta") or {}
    gateways: list[Gateway] = []
    for item in raw:
        fields = []
        for field_item in item.get("fields") or []:
            fields.append(
                GatewayField(
                    key=str(field_item["key"]),
                    title_en=str(field_item.get("title_en", field_item["key"])),
                    title_th=str(field_item.get("title_th", field_item["key"])),
                    help_en=str(field_item.get("help_en", "")).strip(),
                    help_th=str(field_item.get("help_th", "")).strip(),
                    secret=bool(field_item.get("secret", False)),
                    storage=str(field_item.get("storage", "env")),
                    placeholder=str(field_item.get("placeholder", "")),
                    **_hint_from(field_item, meta.get(field_item["key"])),
                )
            )
        gateways.append(
            Gateway(
                id=str(item["id"]),
                title_en=str(item.get("title_en", item["id"])),
                title_th=str(item.get("title_th", item["id"])),
                doc=str(item.get("doc", "")),
                steps_en=str(item.get("steps_en", "")).strip(),
                steps_th=str(item.get("steps_th", "")).strip(),
                enabled_key=str(item.get("enabled_key", "")),
                test=str(item.get("test", "none")),
                token_key=str(item.get("token_key", "")),
                banner_en=str(item.get("banner_en", "")).strip(),
                banner_th=str(item.get("banner_th", "")).strip(),
                fields=fields,
            )
        )
    return gateways


def load_checks(root: Path | None = None) -> list[Check]:
    raw = _load("checks.yaml", root).get("checks") or []
    return [
        Check(
            id=str(item["id"]),
            title_en=str(item.get("title_en", item["id"])),
            title_th=str(item.get("title_th", item["id"])),
            kind=str(item.get("kind", "command")),
            fix_page=str(item.get("fix_page", "health")),
            optional=bool(item.get("optional", False)),
            shell=str(item.get("shell", "")).strip(),
            detail_en=str(item.get("detail_en", "")).strip(),
            detail_th=str(item.get("detail_th", "")).strip(),
        )
        for item in raw
    ]


def _validate_settings(settings: list[Setting]) -> None:
    seen: set[str] = set()
    for setting in settings:
        if setting.key in seen:
            raise ValueError(f"duplicate setting {setting.key}")
        seen.add(setting.key)
        if setting.key in DENYLIST_ENV:
            raise ValueError(f"{setting.key} is on the env denylist")
        if setting.storage not in {"yaml", "env"}:
            raise ValueError(f"{setting.key} storage must be yaml or env")
        if setting.type not in {"str", "int", "float", "bool", "choice", "text"}:
            raise ValueError(f"{setting.key} has unknown type {setting.type}")
        if setting.secret and setting.storage != "env":
            raise ValueError(f"secret {setting.key} must use env storage")
        if not setting.title_en or not setting.title_th:
            raise ValueError(f"{setting.key} needs Thai and English titles")
        if not setting.help_en or not setting.help_th:
            raise ValueError(f"{setting.key} needs Thai and English help")


@dataclass
class Provider:
    id: str
    title_en: str
    title_th: str
    about_en: str
    about_th: str
    config_provider: str
    key_env: str = ""
    key_required: bool = False
    base_url_env: str = ""
    default_base_url: str = ""
    base_in_config: bool = False
    show_context: bool = False
    test: str = "none"
    recommended: bool = False
    default_model: str = ""
    example_key: str = ""
    example_model: str = ""
    where_en: str = ""
    where_th: str = ""
    low_spec_en: str = ""
    low_spec_th: str = ""
    source: str = ""
    links: list[Link] = field(default_factory=list)
    allow_typed_provider: bool = False
    allow_typed_key_env: bool = False


@dataclass
class FaqItem:
    id: str
    q_en: str
    q_th: str
    a_en: str
    a_th: str
    command: str = ""


def load_providers(root: Path | None = None) -> list[Provider]:
    raw = _load("providers.yaml", root).get("providers") or []
    providers: list[Provider] = []
    for item in raw:
        providers.append(
            Provider(
                id=str(item["id"]),
                title_en=str(item.get("title_en", item["id"])),
                title_th=str(item.get("title_th", item["id"])),
                about_en=str(item.get("about_en", "")).strip(),
                about_th=str(item.get("about_th", "")).strip(),
                config_provider=str(item.get("config_provider", item["id"])),
                key_env=str(item.get("key_env", "")),
                key_required=bool(item.get("key_required", False)),
                base_url_env=str(item.get("base_url_env", "")),
                default_base_url=str(item.get("default_base_url", "")),
                base_in_config=bool(item.get("base_in_config", False)),
                show_context=bool(item.get("show_context", False)),
                test=str(item.get("test", "none")),
                recommended=bool(item.get("recommended", False)),
                default_model=str(item.get("default_model", "")),
                example_key=str(item.get("example_key", "")),
                example_model=str(item.get("example_model", "")),
                where_en=str(item.get("where_en", "")).strip(),
                where_th=str(item.get("where_th", "")).strip(),
                low_spec_en=str(item.get("low_spec_en", "")).strip(),
                low_spec_th=str(item.get("low_spec_th", "")).strip(),
                source=str(item.get("source", "")),
                links=_links(item.get("links")),
                allow_typed_provider=bool(item.get("allow_typed_provider", False)),
                allow_typed_key_env=bool(item.get("allow_typed_key_env", False)),
            )
        )
    ids = [item.id for item in providers]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate provider id")
    return providers


def load_faq(root: Path | None = None) -> list[FaqItem]:
    raw = _load("faq.yaml", root).get("faq") or []
    return [
        FaqItem(
            id=str(item["id"]),
            q_en=str(item.get("q_en", "")).strip(),
            q_th=str(item.get("q_th", "")).strip(),
            a_en=str(item.get("a_en", "")).strip(),
            a_th=str(item.get("a_th", "")).strip(),
            command=str(item.get("command", "")).strip(),
        )
        for item in raw
    ]


def is_denied_key(key: str) -> bool:
    head = key.split(".", 1)[0]
    return key in DENYLIST_ENV or head in DENYLIST_ENV


def key_is_secret_name(key: str) -> bool:
    upper = key.upper()
    markers = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")
    return any(marker in upper for marker in markers)
