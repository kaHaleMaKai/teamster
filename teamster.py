from __future__ import annotations

import os
import re
import json
from typing import TypeAlias, Iterable, TypedDict, Literal, Any
from pathlib import Path

import click
from flask import Flask, send_from_directory, Response as FlaskResponse, render_template
from PIL import Image
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).absolute().parent
DEFAULT_IMAGE_DIR = "images"
DEFAULT_THUMBNAIL_DIR = "thumbs"
DEFAULT_THUMBNAIL_SIZE = (128, 128)
V2_API_PREFIX = "/evergreen-assets/backgroundimages"
ACCEPTED_SUFFIXES = ("png", "jpg", "jpeg", "gif")
EXTENSION_MAPPING = {"jpeg": "jpg", "gif": "jpg"}


if xdg_conf_dir := os.environ.get("XDG_CONFIG_DIR"):
    CONF_BASE_DIR = Path(xdg_conf_dir)
else:
    CONF_BASE_DIR = Path.home() / ".config"
DEFAULT_CONFIG_FILE = CONF_BASE_DIR / "teamster" / "config.json"
TEAMS_CONFIG_FILE = CONF_BASE_DIR / "teams-for-linux" / "config.json"

Response: TypeAlias = FlaskResponse | str


class ImageEntry(TypedDict):
    filetype: str
    id: str
    name: str
    src: str
    thumb_src: str


class Config(BaseModel):
    image_dir: Path = Field(default=Path(BASE_DIR / DEFAULT_IMAGE_DIR))
    thumbnail_dir: Path = Field(default=Path(BASE_DIR / DEFAULT_THUMBNAIL_DIR))
    thumbnail_size: (tuple[int, int]) = Field(default=DEFAULT_THUMBNAIL_SIZE)
    listen_address: str = Field(default="::1")
    port: int = Field(default=6789)
    teams_version: Literal[1, 2] = Field(default=2)
    debug: bool = Field(default=True)
    fetch_interval: int = Field(default=60)
    ignore_teams_images: bool = Field(default=True)
    update_teams_config: bool = Field(default=False)


def import_config(path: Path) -> Config:
    text = path.read_text()
    return Config.model_validate_json(text)


def create_thumbnail(img: Path, thumb: Path, size: tuple[int, int]) -> None:
    print(f"creating thumbnail thumb {thumb} from img {img}")
    if not thumb.parent.exists():
        thumb.parent.mkdir()
    with Image.open(img) as f:
        try:
            f.thumbnail(size)
            f.save(thumb)
        except Exception as e:
            raise IOError(f"could not create thumbnail for {img}") from e


def get_file_listing(config: Config, base_dir: Path | None = None) -> Iterable[ImageEntry]:
    base = base_dir or config.image_dir
    for p in base.iterdir():
        if p.is_dir():
            yield from get_file_listing(config, p)

        else:
            img = p.relative_to(config.image_dir)
            ext = img.suffix.replace(".", "").lower()
            if ext not in ACCEPTED_SUFFIXES:
                continue
            new_ext = EXTENSION_MAPPING.get(ext)

            thumb = config.thumbnail_dir / img
            if not thumb.exists():
                create_thumbnail(p, thumb, config.thumbnail_size)

            prefix = V2_API_PREFIX if config.teams_version == 2 else ""

            img_name = str(img) + (f".{new_ext}" if new_ext else "")

            yield {
                    "filetype": new_ext or ext,
                    "id": img.stem,
                    "name": img.stem,
                    "src":       f"{prefix}/images/{img_name}",
                    "thumb_src": f"{prefix}/thumbnails/{img_name}",
                    }


def find_file(path: Path) -> Path:
    if path.exists():
        return path
    return path.with_suffix("")


def create_app(config: Config) -> Flask:
    app = Flask("teamster")

    @app.after_request
    def add_headers(resp: FlaskResponse) -> FlaskResponse:
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["access-control-allow-origin"] = "*"
        return resp

    @app.get("/")
    def index() -> Response:
        return render_template("index.html", listen_address=config.listen_address, port=config.port)

    @app.get("/images")
    def list_images() -> Response:
        images = (p.relative_to(config.image_dir) for p in config.image_dir.iterdir())
        imgs = "\n".join(f"""<li><a href="/images/{p.name}">{p}</a></li>""" for p in images)
        return f"<ul>{imgs}</ul>"

    @app.get("/images/<path:path>")
    def serve_images(path: str) -> Response:
        p = find_file(config.image_dir / path)
        return send_from_directory(config.image_dir, p.relative_to(config.image_dir))

    @app.get("/thumbnails")
    def list_thumbnails() -> Response:
        thumbnails = (p.relative_to(config.thumbnail_dir) for p in config.thumbnail_dir.iterdir())
        imgs = "\n".join(f"""<li><a href="/thumbnails/{p.name}">{p}</a></li>""" for p in thumbnails)
        return f"<ul>{imgs}</ul>"

    @app.get("/thumbnails/<path:path>")
    def serve_thumbnails(path: str) -> Response:
        p = find_file(config.thumbnail_dir / path)
        return send_from_directory(config.thumbnail_dir, p.relative_to(config.thumbnail_dir))

    @app.get("/config.json")
    def serve_config_json() -> Response:
        files = list(get_file_listing(config))
        resp: list[ImageEntry] | dict[str, list[ImageEntry]]
        if config.teams_version == 1:
            resp = files
        else:
            resp = {"videoBackgroundImages": files}
        return json.dumps(resp)

    return app


def update_config(config: Config) -> None:
    TEAMS_CONFIG_FILE.parent.mkdir(exist_ok=True)

    teams_config: dict[str, Any]

    if TEAMS_CONFIG_FILE.exists():
        with TEAMS_CONFIG_FILE.open("r") as f:
            teams_config = json.load(f)
    else:
        teams_config = {}

    new_config = teams_config | {
        "customBGServiceBaseUrl": f"http://localhost:{config.port}",
        "customBGServiceIgnoreMSDefaults": config.ignore_teams_images,
        "customBGServiceConfigFetchInterval": config.fetch_interval,
    }

    if new_config != teams_config:
        with TEAMS_CONFIG_FILE.open("w") as f:
            json.dump(new_config, f)
        print("++++++++++++++++++++++++++++++++++++++++")
        print("")
        print("please restart Teams app due to config changes")
        print("")
        print("++++++++++++++++++++++++++++++++++++++++")


def main(config: Config) -> None:
    config.image_dir.mkdir(exist_ok=True)
    config.thumbnail_dir.mkdir(exist_ok=True)
    create_app(config).run(host=config.listen_address, port=config.port, debug=config.debug)


@click.command()
@click.option("--config", "-c", default=DEFAULT_CONFIG_FILE, type=Path, show_default=True, help="path to config file")
def run_cli(config: Path) -> None:
    print(f"reading config file {config}")
    if config.exists():
        config_object = import_config(config)
    else:
        print("config file does not exist, using default values")
        config_object = Config()
    if config_object.update_teams_config:
        update_config(config_object)
    main(config_object)


if __name__ == "__main__":
    run_cli()
