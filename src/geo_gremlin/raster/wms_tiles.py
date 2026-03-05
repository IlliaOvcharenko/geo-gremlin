from logkit.core import get_logger
logger = get_logger("geo_gremlin", __name__)

import cv2
import asyncio
import aiohttp
import aiofiles
import mercantile

import numpy as np

from pathlib import Path
from shapely.geometry import Polygon
from shapely.affinity import affine_transform
from itertools import chain
from tqdm.cli import tqdm # pyright: ignore
from rasterio.features import rasterize


def tile_to_poly(
    tile: mercantile.Tile
) -> Polygon:

    left, top, right, bottom = mercantile.xy_bounds(tile)
    return Polygon([
        (left, top),
        (right, top),
        (right, bottom),
        (left, bottom),
        (left, top),
    ])


def get_wms_tiles(
    shape: Polygon,
    zoom: int,
    tile=mercantile.Tile(0, 0, 0)
) -> list[mercantile.Tile]:

    subtiles = []
    tile_poly = tile_to_poly(tile)
    if tile_poly.intersects(shape):

        if tile.z >= zoom:
            return [tile, ]

        subtiles += mercantile.children(tile)


    results = []
    for subtile in subtiles:
        results.append(get_wms_tiles(shape, zoom, subtile))
    return list(chain(*results))


def get_world_file_content(
    tile: mercantile.Tile,
    img_shape: tuple[int, int],
) -> list[str]:

    left, top, right, bottom = mercantile.xy_bounds(tile)
    x_px_size = (right - left) / (img_shape[0])
    y_px_size = (top - bottom) / (img_shape[1])
    geo_transform = [
        x_px_size,
        0,
        0,
        y_px_size,
        left + x_px_size / 2,
        bottom + y_px_size / 2,
    ]
    return [f"{l}\n" for l in geo_transform]


async def download_worker(
    session: aiohttp.ClientSession,
    queue: asyncio.Queue,
    pbar,
    wms_url: str,
    save_folder: Path,
    worker_id: int = -1,
    wld_suffix: str = ".wld",
    img_shape: tuple[int, int] = (256, 256),
) -> None:

    while True:
        tile = await queue.get()

        if tile is None:
            queue.task_done()
            break

        url = wms_url.format(x=tile.x, y=tile.y, z=tile.z)
        save_fn = save_folder / f"tile_{tile.x}_{tile.y}_{tile.z}"

        # logger.info(f"Worker {worker_id}, item {save_fn.stem}")

        async with session.get(url) as resp:
            if resp.status == 200:
                # save img
                img_f = await aiofiles.open(
                    save_fn.with_suffix(".png"),
                    mode="wb"
                )
                await img_f.write(await resp.read())
                await img_f.close()

                # save corresponding world file
                world_f = await aiofiles.open(
                    save_fn.with_suffix(wld_suffix),
                    mode="w"
                )
                # TODO: hardcoded img shape
                await world_f.writelines(
                    get_world_file_content(tile, img_shape)
                )
                await world_f.close()

                # update progress bar
                pbar.update(1)

        queue.task_done()


async def download_tiles(
    tiles: list[mercantile.Tile],
    save_folder: Path,
    wms_url: str,
    first_n_tiles: int | None,
    n_workers: int,

):
    url_queue = asyncio.Queue()
    for tile in tiles[:first_n_tiles]:
        await url_queue.put(tile)

    download_pbar = tqdm(total=len(tiles))

    async with aiohttp.ClientSession() as sess:

        workers =  [
            asyncio.create_task(download_worker(
                sess, url_queue, download_pbar, 
                wms_url, save_folder, worker_id,
            ))
            for worker_id in range(n_workers)
        ]


        for _ in range(n_workers):
            await url_queue.put(None)

        # Await all done
        await url_queue.join()
        download_pbar.close()
        for worker in workers:
            await worker


def refine_border_tiles(
    shape_tiles: list[mercantile.Tile],
    shape_poly: Polygon,
    first_n_tiles: int | None,
    wld_suffix: str,
    save_folder: Path,
) -> None:
    """ Go through all border tiles (ones that intersects with a target shape)
    and fill with 0 area that is out of target shape.

    """

    for tile in tqdm(shape_tiles[:first_n_tiles]):
        tile_poly = tile_to_poly(tile)
        if not shape_poly.contains(tile_poly):
            tile_fn = save_folder / f"tile_{tile.x}_{tile.y}_{tile.z}"
            with open(tile_fn.with_suffix(wld_suffix), "r") as tile_geot_f:
                tile_geot = tile_geot_f.readlines()
                tile_geot = [float(v.strip()) for v in tile_geot]

                # calculate inv geotrasform
                a, d, b, e, c, f = tile_geot
                tile_geot_M = np.array([
                    [a,   b,    c],
                    [d,   e,    f],
                    [0.0, 0.0, 1.0],
                ])
                tile_geot_M_inv = np.linalg.inv(tile_geot_M)
                tile_geot_M_inv /= tile_geot_M[-1, -1]

                tile_geot_inv = [
                    tile_geot_M_inv[0, 0],
                    tile_geot_M_inv[0, 1],
                    tile_geot_M_inv[1, 0],
                    tile_geot_M_inv[1, 1],
                    tile_geot_M_inv[0, 2],
                    tile_geot_M_inv[1, 2],
                ]
                tile_geot_inv = [float(p) for p in tile_geot_inv]

                # calculate bin mask for pixels to leave
                tile_img = cv2.imread(str(tile_fn.with_suffix(".png")))
                tile_shape = (tile_img.shape[0], tile_img.shape[1])

                mask_poly = tile_poly.intersection(shape_poly)
                mask_poly = affine_transform(mask_poly, tile_geot_inv)
                mask = rasterize(
                    [(mask_poly, 1)],
                    out_shape=tile_shape,
                    fill=0,
                    all_touched=True,
                    dtype=np.uint8,
                    default_value=1,
                )
                mask = mask.astype(bool)
                tile_img[~mask] = 0

                cv2.imwrite(str(tile_fn.with_suffix(".png")), tile_img)


def run_gdal_retiling(
    in_folder: Path, # pyright: ignore
    out_folder: Path, # pyright: ignore
    tile_size: tuple[int, int],
    tile_overlap: int = 0,
    tile_base_name: str = "tile",
) -> None:
    """ Run gdal_retile.py directly from python, that is similar to

    ```bash
    gdal_retile.py -ps 512 512 \
                   -targetDir ../test-tiles-directly/ \
                   -of PNG \
                   -co WORLDFILE=YES \
                   *.png
    ```

    """
    try:
        import warnings
        warnings.filterwarnings('ignore',  category=FutureWarning)

        from osgeo import gdal
        from osgeo_utils.gdal_retile import (
            RetileGlobals,
            getTileIndexFromFiles,
            mosaic_info,
            tile_info,
            tileImage,
        )
    except:
        logger.info("GDAL installation is missing, exit")
        exit(0)

    g = RetileGlobals()

    g.Format = "PNG"
    g.CreateOptions.append("WORLDFILE=YES")
    g.Verbose = False
    g.TargetDir = str(out_folder) + "/" # pyright: ignore
    g.TileWidth = tile_size[1]
    g.TileHeight = tile_size[0]
    g.Overlap = tile_overlap

    tile_fns = list(map(str, sorted(in_folder.glob("*.png"))))
    for fn in tile_fns:
        g.Names.append(fn)

    g.Driver = gdal.GetDriverByName(g.Format)

    DriverMD = g.Driver.GetMetadata()
    g.Extension = DriverMD.get(gdal.DMD_EXTENSION)
    if "DCAP_CREATE" not in DriverMD:
        g.MemDriver = gdal.GetDriverByName("MEM")

    tileIndexDS = getTileIndexFromFiles(g)
    # minfo = mosaic_info(g.Names[0], tileIndexDS)
    minfo = mosaic_info(tile_base_name, tileIndexDS)
    ti = tile_info(
        minfo.xsize,
        minfo.ysize,
        g.TileWidth,
        g.TileHeight,
        g.Overlap
    )

    # minfo.report()
    # ti.report()

    dsCreatedTileIndex = tileImage(g, minfo, ti)
    tileIndexDS.Close() # pyright: ignore

def update_and_remove_tiles(
    tile_folder: Path, # pyright: ignore
    img_suffix: str = ".png",
    wld_suffix: str = ".wld",
    tile_shape: tuple[int, int] | None = None,
):
    tile_fns = list(sorted(tile_folder.glob("*" + img_suffix)))

    updated_count = 0
    removed_count = 0
    for tile_fn in tqdm(tile_fns):
        # TODO switch to a gdal for spatial img read/write
        # tile, geot = gdal_imread(tile_fn)
        # logger.info(geot)

        tile = cv2.imread(str(tile_fn))
        is_tile_empty = (tile == 0).all()
        if is_tile_empty:
            tile_fn.unlink()
            tile_fn.with_suffix(wld_suffix).unlink()
            # logger.info(f"Remove empty tile: {tile_fn.stem}")
            removed_count += 1
        else:
            if (tile_shape is not None):
                if (tile.shape[0] < tile_shape[0]) or \
                   (tile.shape[1] < tile_shape[1]):
                    tile = np.pad(
                        tile,
                        (
                            (0, tile_shape[0] - tile.shape[0]),
                            (0, tile_shape[1] - tile.shape[1]),
                            (0, 0)
                        )
                    )
                    cv2.imwrite(str(tile_fn), tile)
                    updated_count += 1
                    # logger.info(f"Update non square tile: {tile_fn.stem}")
    logger.info(f"Files removed: {removed_count}, updated: {updated_count}")
