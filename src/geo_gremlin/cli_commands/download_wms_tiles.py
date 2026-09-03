import math
from pathlib import Path
from typing import Callable, Literal

import geopandas as gpd
import mercantile
from logkit.core import (
    get_logger,
    log_run,
    log_params
)

from geo_gremlin.raster.wms_tiles import (
    get_wms_tiles,
    download_tiles,
    refine_border_tiles,
)


logger = get_logger("geo_gremlin", __name__)

TileServer = Literal["google", "esri", "yandex", "mapbox", "bing"]


def esri_url(x: int, y: int, z: int) -> str:
    return (
        "https://server.arcgisonline.com/ArcGIS/"
        f"rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    )


def google_url(x: int, y: int, z: int) -> str:
    return f"https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"


def bing_url(x: int, y: int, z: int) -> str:
    q = mercantile.quadkey(x, y, z)
    return f"https://ecn.t3.tiles.virtualearth.net/tiles/a{q}.jpeg?g=1"


E = 0.0818191908426  # WGS84 eccentricity


def to_yandex_xyz(x: int, y: int, z: int):
    bounds = mercantile.bounds(x, y, z)

    lon = (bounds.west + bounds.east) / 2
    lat = (bounds.south + bounds.north) / 2

    lat_rad = math.radians(lat)
    sin_lat = math.sin(lat_rad)

    y_norm = (
        1
        - (
            math.atanh(sin_lat)
            - E * math.atanh(E * sin_lat)
        ) / math.pi
    ) / 2

    n = 2 ** z
    y_yandex = int(y_norm * n)
    x_yandex = x

    return x_yandex, y_yandex, z


def yandex_url(x: int, y: int, z: int) -> str:
    x, y, z = to_yandex_xyz(x, y, z)
    return (
        "https://core-sat.maps.yandex.net/tiles?"
        f"l=sat&v=3.1025.0&x={x}&y={y}&z={z}&scale=1&lang=ru_RU"
    )


def mapbox_url(x: int, y: int, z: int) -> str:
    return (
        "https://api.mapbox.com/v4/mapbox.satellite/"
        f"{z}/{x}/{y}.webp?sku=101ifSAcKcVFs"
        "&access_token="
        "pk.eyJ1IjoidW5mb2xkZWRpbmMiLCJhIjoiY2s5ZG90MjMzMDV6eDNkbnh2cDJvbHl4NyJ9."
        "BT2LAvHi31vNNEplsgxucQ"
    )


URL_BUILDERS: dict[TileServer, Callable[[int, int, int], str]] = {
    "esri": esri_url,
    "google": google_url,
    "bing": bing_url,
    "yandex": yandex_url,
    "mapbox": mapbox_url,
}

TILE_EXT: dict[TileServer, str] = {
    "esri": ".png",
    "google": ".png",
    "bing": ".png",
    "yandex": ".png",
    "mapbox": ".webp",
}


async def download_wms_tiles(
    wms_server: TileServer,
    zoom_level: int,
    bounds_fn: str,  # pyright: ignore
    ortho_folder: str,  # pyright: ignore
    n_workers: int = 100,
    first_n_tiles: int | None = None,
    wld_suffix: str = ".wld",
):
    logger.info("Download WMS tiles")
    log_params(logger, locals())
    # log_run(logger, __file__, locals())

    wms_url = URL_BUILDERS[wms_server]
    tile_ext = TILE_EXT[wms_server]

    bounds_fn: Path = Path(bounds_fn)
    shape = gpd.read_file(bounds_fn)
    if shape.crs != "EPSG:3857":
        shape = shape.to_crs("EPSG:3857")
    shape_poly = shape.union_all()

    ortho_folder: Path = Path(ortho_folder)

    shape_tiles = get_wms_tiles(
        shape_poly,
        zoom_level,
    )
    shape_tiles = list(sorted(shape_tiles, key=lambda t: (t.x, t.y)))
    logger.info(f"Number of tiles found: {len(shape_tiles)}")

    logger.info("- Download tiles")
    result_folder = ortho_folder / f"{wms_server}_{zoom_level}"
    result_folder.mkdir(exist_ok=True, parents=True)

    await download_tiles(
        shape_tiles,
        tile_ext,
        result_folder,
        wms_url,
        first_n_tiles,
        n_workers,
    )

    logger.info("- Refine border tiles")
    refine_border_tiles(
        shape_tiles,
        shape_poly,
        first_n_tiles,
        wld_suffix,
        result_folder,
        tile_ext,
    )

    logger.info("Processing is done!")
