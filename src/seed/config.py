"""Read and validate Seed configuration without connecting to a database."""

import os
import re
import tomllib
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from ipaddress import ip_address
from pathlib import Path
from typing import Annotated, Literal, Self

from faker.config import AVAILABLE_LOCALES
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

type Identifier = Annotated[str, Field(min_length=1, pattern=r"^[^\x00]+$")]
type Rows = Annotated[int, Field(ge=0, le=100_000)]
type Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
type Scalar = str | bool | int | date | datetime
type Generator = Literal[
    "integer", "decimal", "boolean", "text", "date", "datetime", "uuid",
    "choice", "constant", "email", "phone", "first_name", "last_name",
    "name", "address", "city", "country", "description",
]


class ConfigError(Exception):
    """A configuration failure with a message safe to render."""


class ConfigModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class DatabaseConfig(ConfigModel):
    driver: Literal["postgresql"] = "postgresql"
    url_env: Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
    schema_name: Identifier = Field(default="public", alias="schema")
    connect_timeout: Annotated[int, Field(ge=2, le=60)] = 5


class GenerationConfig(ConfigModel):
    locale: str = "en_US"
    random_seed: Annotated[int, Field(ge=0, le=2**64 - 1)] = 0
    default_rows: Rows = 100
    batch_size: Annotated[int, Field(ge=1, le=10_000)] = 1000
    reference_time: datetime = datetime(2025, 1, 1, tzinfo=UTC)
    null_rate: Probability = 0.05

    @field_validator("locale")
    @classmethod
    def check_locale(cls, value: str) -> str:
        if value not in AVAILABLE_LOCALES:
            raise ValueError("Expected a supported Faker locale")
        return value

    @field_validator("reference_time")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Expected an offset datetime")
        try:
            utc_value = value.astimezone(UTC)
            utc_value - timedelta(days=365)
        except OverflowError:
            raise ValueError("Expected a reference time with a preceding 365-day window") from None
        return utc_value


class WriteTarget(ConfigModel):
    host: str
    port: Annotated[int, Field(ge=1, le=65_535)]
    database: Identifier
    schema_name: Identifier = Field(alias="schema")

    @field_validator("host")
    @classmethod
    def check_host(cls, value: str) -> str:
        try:
            return str(ip_address(value))
        except ValueError:
            host = value.lower().removesuffix(".")
            label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
            if len(host) > 253 or not re.fullmatch(rf"{label}(?:\.{label})*", host):
                raise ValueError("Expected one DNS name or IP address") from None
            return host


class SafetyConfig(ConfigModel):
    environment: Literal["development", "test"] | None = None
    allow_existing_data: bool = False
    target: WriteTarget | None = None


class TableConfig(ConfigModel):
    rows: Rows | None = None
    reuse_existing: bool = False

    @model_validator(mode="after")
    def check_reuse(self) -> Self:
        if self.reuse_existing and self.rows != 0:
            raise ValueError("Existing parent reuse requires an explicit zero row count")
        return self


class GeneratorRule(ConfigModel):
    generator: Generator | None = None
    min: int | str | None = None
    max: int | str | None = None
    value: Scalar | None = None
    values: list[Scalar] | None = None
    unique: bool = False
    null_rate: Probability | None = None

    @model_validator(mode="after")
    def check_parameters(self) -> Self:
        if (self.value is not None) != (self.generator == "constant"):
            raise ValueError("The constant generator requires a value")
        if self.generator == "choice":
            if not self.values or len({(type(value), value) for value in self.values}) != len(self.values):
                raise ValueError("The choice generator requires distinct values")
        elif self.values is not None:
            raise ValueError("Values are only valid with the choice generator")

        bounds = [bound for bound in (self.min, self.max) if bound is not None]
        if bounds:
            if self.generator == "integer" and all(isinstance(bound, int) for bound in bounds):
                numeric = [Decimal(bound) for bound in bounds]
            elif self.generator == "decimal":
                try:
                    numeric = [Decimal(bound) for bound in bounds]
                except InvalidOperation:
                    raise ValueError("Expected exact decimal bounds") from None
            else:
                raise ValueError("Expected bounds for a compatible numeric generator")
            if not all(bound.is_finite() for bound in numeric) or (
                len(numeric) == 2 and numeric[0] > numeric[1]
            ):
                raise ValueError("Expected finite bounds in ascending order")
        return self


class SeedConfig(ConfigModel):
    version: Literal[1]
    database: DatabaseConfig
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    tables: dict[Identifier, TableConfig] = Field(default_factory=dict)
    rules: dict[Identifier, dict[Identifier, GeneratorRule]] = Field(default_factory=dict)

    @field_validator("version", mode="before")
    @classmethod
    def check_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Expected an integer configuration version")
        return value


def parse_config(
    text: str,
    *,
    schema: str | None = None,
    locale: str | None = None,
    random_seed: int | None = None,
) -> SeedConfig:
    """Parse TOML and validate both the file and requested overrides."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise ConfigError("Configuration is not valid TOML.") from None
    config = _validate(data)
    try:
        return SeedConfig(
            version=config.version,
            database=DatabaseConfig.model_validate({
                **config.database.model_dump(by_alias=True),
                **({"schema": schema} if schema is not None else {}),
            }),
            generation=GenerationConfig.model_validate({
                **config.generation.model_dump(),
                **({"locale": locale} if locale is not None else {}),
                **({"random_seed": random_seed} if random_seed is not None else {}),
            }),
            safety=config.safety,
            tables=config.tables,
            rules=config.rules,
        )
    except ValidationError as error:
        raise _safe_validation_error(error) from None


def load_config(path: Path) -> SeedConfig:
    """Read and validate a UTF-8 configuration file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise ConfigError("Could not read the UTF-8 configuration file.") from None
    return parse_config(text)


def resolve_database_url(config: SeedConfig, environ: Mapping[str, str] | None = None) -> str:
    """Resolve the explicitly named environment variable without displaying its value."""
    values = os.environ if environ is None else environ
    url = values.get(config.database.url_env, "")
    if not url.strip():
        raise ConfigError("The environment variable configured by database.url_env is missing or empty.")
    return url


def _validate(data: object) -> SeedConfig:
    try:
        return SeedConfig.model_validate(data)
    except ValidationError as error:
        raise _safe_validation_error(error) from None


def _safe_validation_error(error: ValidationError) -> ConfigError:
    first = error.errors(include_input=False, include_context=False, include_url=False)[0]
    root = first["loc"][0] if first["loc"] else ""
    known_sections = {"version", "database", "generation", "safety", "tables", "rules"}
    scope = f" in {root}" if isinstance(root, str) and root in known_sections else ""
    return ConfigError(f"Invalid configuration field{scope}.")
