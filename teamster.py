from __future__ import annotations

import os
import re
import json
from typing import TypeAlias, Iterable, TypedDict, Literal, Any, TypeVar
from pathlib import Path
from functools import wraps

import dbus
import click
from flask import Flask, send_from_directory, Response as FlaskResponse, render_template
from PIL import Image
from pydantic import BaseModel, Field
from werkzeug.exceptions import HTTPException, NotFound


BASE_DIR = Path(__file__).absolute().parent
DEFAULT_IMAGE_DIR = "images"
DEFAULT_THUMBNAIL_SIZE = (128, 128)
V2_API_PREFIX = "/evergreen-assets/backgroundimages"
ACCEPTED_SUFFIXES = ("png", "jpg", "jpeg", "gif")
EXTENSION_MAPPING = {"jpeg": "jpg", "gif": "jpg"}


if xdg_conf_dir := os.environ.get("XDG_CONFIG_DIR"):
    CONF_BASE_DIR = Path(xdg_conf_dir)
else:
    CONF_BASE_DIR = Path.home() / ".config"

if xdg_cache_dir := os.environ.get("XDG_CACHE_DIR"):
    CACHE_BASE_DIR = Path(xdg_cache_dir)
else:
    CACHE_BASE_DIR = Path.home() / ".cache"

DEFAULT_CONFIG_FILE = CONF_BASE_DIR / "teamster" / "config.json"
DEFAULT_CACHE_DIR = CACHE_BASE_DIR / "teamster"
TEAMS_CONFIG_FILE = CONF_BASE_DIR / "teams-for-linux" / "config.json"

E = TypeVar("E", bound=HTTPException)
Response: TypeAlias = FlaskResponse | str


class ImageEntry(TypedDict):
    filetype: str
    id: str
    name: str
    src: str
    thumb_src: str


class Config(BaseModel):
    image_dir: Path = Field(default=BASE_DIR / DEFAULT_IMAGE_DIR)
    thumbnail_dir: Path = Field(default=DEFAULT_CACHE_DIR)
    thumbnail_size: tuple[int, int] = Field(default=DEFAULT_THUMBNAIL_SIZE)
    listen_address: str = Field(default="::1")
    port: int = Field(default=6789)
    teams_version: Literal[1, 2] = Field(default=2)
    debug: bool = Field(default=False)
    fetch_interval: int = Field(default=60)
    ignore_teams_images: bool = Field(default=True)
    update_teams_config: bool = Field(default=False)
    notify: bool = Field(default=True)

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        self.image_dir = (
            self.image_dir if self.image_dir.is_absolute() else BASE_DIR / self.image_dir
        )
        self.thumbnail_dir = (
            self.thumbnail_dir
            if self.thumbnail_dir.is_absolute()
            else BASE_DIR / self.thumbnail_dir
        )

    def get_base_dir(self, prefix: str) -> Path:
        if prefix == "images":
            return self.image_dir
        elif prefix == "thumbnails":
            return self.thumbnail_dir
        else:
            raise KeyError(
                f"bad value for prefix. exptected: 'images' or 'thumbnails'. got: {prefix}"
            )


class Notifier:
    item = "org.freedesktop.Notifications"
    low = 0
    average = 1
    critical = 2

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        if enabled:
            self._sender = dbus.Interface(
                dbus.SessionBus().get_object(
                    self.item, f"/{self.item}".replace(".", "/")
                ),
                self.item,
            )

            import atexit

            atexit.register(self.send, "web server stoppinng…")

    def send(
        self, msg: str, title: str = "Teamster", urgency: int = 1, timeout: int = 3000
    ) -> None:
        if self._enabled:
            self._sender.Notify("", 0, "", title, msg, [], {"urgency": urgency}, timeout)


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


def get_file_listing(
    config: Config, base_dir: Path | None = None
) -> Iterable[ImageEntry]:
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
                "src": f"{prefix}/images/{img_name}",
                "thumb_src": f"{prefix}/thumbnails/{img_name}",
            }


def find_file(path: Path) -> Path:
    if path.exists():
        return path
    return path.with_suffix("")


def create_app(config: Config, notifier: Notifier) -> Flask:
    app = Flask("teamster")

    def list_files(dir: Path, prefix: Literal["images", "thumbnails"]) -> Response:
        rel_dir = config.get_base_dir(prefix)
        files = (p.relative_to(rel_dir) for p in dir.iterdir())
        return render_template(
            "file-listing.html", prefix=prefix, paths=files, back=dir.relative_to(rel_dir)
        )

    @app.errorhandler(HTTPException)
    def handle_exception(e: E) -> E:
        if e.code != 404:
            msg = f"{e.code} error in Teamster\n{e.description}"
            notifier.send(msg, urgency=notifier.critical, timeout=5_000)
        return e

    @app.after_request
    def add_headers(resp: FlaskResponse) -> FlaskResponse:
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["access-control-allow-origin"] = "*"
        return resp

    @app.get("/")
    def index() -> Response:
        return render_template(
            "index.html", listen_address=config.listen_address, port=config.port
        )

    @app.get("/images")
    @app.get("/images/")
    def list_images() -> Response:
        return list_files(config.image_dir, prefix="images")

    @app.get("/thumbnails")
    @app.get("/thumbnails/")
    def list_thumbnails() -> Response:
        return list_files(config.thumbnail_dir, prefix="thumbnails")

    @app.get("/<prefix>/<path:path>")
    def serve_images(prefix: str, path: str) -> Response:
        try:
            rel_dir = config.get_base_dir(prefix)
        except KeyError as e:
            raise NotFound(str(e))
        if (dir := rel_dir / path).is_dir():
            return list_files(dir, prefix=prefix)  # type: ignore[arg-type]
        else:
            p = find_file(rel_dir / path)
            return send_from_directory(rel_dir, p.relative_to(rel_dir))

    @app.get("/config.json")
    def serve_config_json() -> Response:
        files = list(get_file_listing(config))
        resp: list[ImageEntry] | dict[str, list[ImageEntry]]
        if config.teams_version == 1:
            resp = files
        else:
            resp = {"videoBackgroundImages": files}
        response = FlaskResponse(json.dumps(resp))
        response.content_type = "application/json"
        return response

    return app


def update_config(config: Config, notifier: Notifier) -> None:
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
        notifier.send("restart Teams app due to config change")
        print("++++++++++++++++++++++++++++++++++++++++")
        print("")
        print("please restart Teams app due to config changes")
        print("")
        print("++++++++++++++++++++++++++++++++++++++++")


def main(config: Config, notifier: Notifier) -> None:
    config.image_dir.mkdir(exist_ok=True)
    config.thumbnail_dir.mkdir(exist_ok=True)
    create_app(config, notifier).run(
        host=config.listen_address, port=config.port, debug=config.debug
    )


@click.command()
@click.option(
    "--config",
    "-c",
    default=DEFAULT_CONFIG_FILE,
    type=Path,
    show_default=True,
    help="path to config file",
)
def run_cli(config: Path) -> None:
    print(f"reading config file {config}")
    if config.exists():
        config_object = import_config(config)
    else:
        print("config file does not exist, using default values")
        config_object = Config()

    notifier = Notifier(enabled=config_object.notify)
    notifier.send("starting web server…")
    if config_object.update_teams_config:
        update_config(config_object, notifier)
    main(config_object, notifier)


if __name__ == "__main__":
    run_cli()
