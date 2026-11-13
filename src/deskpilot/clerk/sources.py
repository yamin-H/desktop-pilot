from pathlib import Path

import soupsieve
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class SourceConfigError(ValueError):
    """The sources file is not valid."""


class SourceConfig(BaseModel):
    """One announcement page and how to read it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    url: str
    item_selector: str = Field(min_length=1)  # CSS selector: one match per announcement
    title_selector: str = "a"  # inside an item
    link_selector: str = "a"  # inside an item
    date_selector: str | None = None  # inside an item (optional)
    date_attribute: str | None = "datetime"  # read the date from this attribute, else the text
    wait_for_selector: str | None = None  # JS-heavy pages: wait until this appears

    @field_validator("url")
    @classmethod
    def _url_scheme(cls, value: str) -> str:
        if not value.startswith(("http://", "https://", "file://")):
            raise ValueError("url must start with http://, https:// or file://")
        return value

    @field_validator(
        "item_selector", "title_selector", "link_selector", "date_selector", "wait_for_selector"
    )
    @classmethod
    def _valid_css(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                soupsieve.compile(value)
            except (SyntaxError, ValueError, soupsieve.SelectorSyntaxError) as error:
                raise ValueError(f"{value!r} is not a valid CSS selector: {error}") from None
        return value


def load_sources(path: Path, root: Path | None = None) -> list[SourceConfig]:
    """Read the sources YAML. `{ROOT_URI}` in a url becomes the project folder as a file:// URI."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise SourceConfigError(f"{path}: not valid YAML: {error}") from None
    if not isinstance(data, list) or not data:
        raise SourceConfigError(f"{path}: expected a non-empty list of sources")

    sources: list[SourceConfig] = []
    for index, item in enumerate(data, start=1):
        if isinstance(item, dict) and isinstance(item.get("url"), str) and root is not None:
            item = {**item, "url": item["url"].replace("{ROOT_URI}", root.resolve().as_uri())}
        label = item.get("name", "?") if isinstance(item, dict) else "?"
        try:
            sources.append(SourceConfig.model_validate(item))
        except ValidationError as error:
            raise SourceConfigError(f"source #{index} ({label}): {error}") from None
    names = [source.name for source in sources]
    if len(set(names)) != len(names):
        raise SourceConfigError("source names must be unique")
    return sources
