# Teamster

driving background images to M$ Teams

# what is this about?

As Linux users, we were only able to envy Windows users for applying custom virtual background images
in video conferences. But _behold_, this time is now over.

The inofficial Teams client [Teams for Linux](https://github.com/IsmaelMartinez/teams-for-linux) (highly recommendable) exposes the same API that
Teams uses to fetch the default images from the Microsoft CDN. This is documented [in the readme](https://github.com/IsmaelMartinez/teams-for-linux/blob/develop/app/config/README.md#custom-backgrounds).

By changing from the default CDN to _Teamster_, you can use your own backgrounds!!!

# how to install?

We have not yet built a `wheel` package. Thus, clone this repo, and install requirements
into a new virtual environment:

```bash
git clone https://github.com/kaHaleMaKai/teamster.git
cd teamster

# setup the project with uv
# for pip die-hards, please cf. below
uv venv .venv
source .venv/bin/activate
uv pip install -r pyproject.toml

# old-school pip setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r pyproject.toml

# run it
python teamster.py
```

## dbus

If you want to receive desktop notifications from Teamster, please run `pip install dbus-python` after
activating your virtual environment (`source .venv/bin/activate`).

# beware

You will _always_ have to start _Teamster_ before starting _Teams-for-Linux_. Else you might not be able to
see any backgrounds in it. In case _Teamster_ crashes during your use of _Teams-for-Linux_, you might need to stop _Teams-for-Linux_ and start _Teamster_ first.

# how to configure?

## Teams for Linux

You will have to start the Teams client with a cli flag:

```bash
teams-for-linux --isCustomBackgroundEnabled=true
```

## Teamster

Teamster consumes a JSON config file, `${XDG_CONFIG_DIR}/teamster/config.json`, and falls back to `${HOME}/.config/teamster/config.json`.

The config file accepts the following options:

```json
{
  "port": 6789,
  "debug": false,
  "teams_version": 2,
  "update_teams_config": true,
  "ignore_teams_images": true,
  "image_dir": "/home/lars/Pictures/video-backgrounds",
  "thumbnail_dir": "/home/lars/.cache/teamster",
  "fetch_interval": 60
}
```

The individual options are

* `port`: the port to run the service on (host is restricted to `localhost`)
* `debug`: whether to run in `Flask` debug mode or not (only useful for Python development)
* `teams_version`: the Teams API version. should be set to `2`, usually
* `update_teams_config`: whether to sync some config options into the config file of _Teams for Linux_
* `ignore_teams_images`: whether to ignore the default Teams images – mirrored option from _Teams for Linux_
* `image_dir`: where to store images. defaults to `images/` subdir of checked out repository
* `thumbnail_dir`: where to store thumbnails. default to `teamster/` below `$XDG_CACHE_DIR` (or `${HOME}/.cache`)
* `fetch_interval`: how often _Teams for Linux_ should look for new background images – again, a mirrored config option

When setting `update_teams_config=true`, then some options such the URL of the Teamster service will be automatically
written into the _Teams for Linux_ config. If you do not wish that, please add it manually (e.g.
`{"customBGServiceBaseUrl": "http://localhost:6789"}`).

## Systemd

If you wish to run this web service via `systemd`, you can execute `./install-service.sh` from this repository. It will
create a user-scoped service called `teamster.service`, that you can start/stop via

```bash
systemctl --user start teamster
systemctl --user stop teamster
```

You can check the logs via

```bash
journalctl --user -u teamster

# or, for a quick overview
systemctl --user status teamster
```

# endpoints

When opening the _Teamster_ base url (per default: `http://localhost:6789`), you will see
a simple HTML page that looks likes this

* `config.json` – exposes the complete list of images to _Teams-for-Linux_
`* images/` – simple directory serving of your image folder for debugging
`* thumbnails/` – simple directory serving of your thumbnail folder for debugging

The `config.json` endpoint is required by Teams itself. It delivers both the information what
images are served, and their URLs. Additionally, Teams wants to show a thumbnail of the background
images. Those are get on-the-fly when calling `config.json` ifn ot existent. Thus, on subsequent calls
the thumbnails will get served from disk.

# debugging

If you do not see any custom backgrounds in _Teams-for-Linux_, please check if

* _Teamster_ running,
* _Teamster_ serves the images,
* _Teamster_ hasn't crashed

When in doubt, please stop _Teams-for-Linux_, start _Teamster_ and only then again
_Teams-for-Linux_.
