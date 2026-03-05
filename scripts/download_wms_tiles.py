from logkit.core import (
    get_logger,
    add_handlers,
    log_run,
)
from logkit.handlers import (
    DefaultConsoleHandler,
    DefaultFileHandler,
)

logger = get_logger("geo_gremlin", __name__)

import geopandas as gpd

from pathlib import Path
from fire import Fire

from geo_gremlin.raster.wms_tiles import (
    get_wms_tiles,
    download_tiles,
    refine_border_tiles,
    run_gdal_retiling,
    update_and_remove_tiles,
)


async def main(
    shape_fn: str, # pyright: ignore
    data_folder: str = "./data", # pyright: ignore
    n_workers: int = 100,
    first_n_tiles: int | None = None,
    subfolder_name: str | None = None,
    wld_suffix: str = ".wld",
    tile_size: tuple[int, int] | None = None,
    tile_overlap: int = 0,
):
    wms_url = "https://server.arcgisonline.com/ArcGIS/" \
              "rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"

    zoom_level = 19
    log_run(logger, __file__, locals())

    # read and check input shape file
    shape_fn: Path = Path(shape_fn)
    shape = gpd.read_file(shape_fn)
    if shape.crs != "EPSG:3857":
        shape = shape.to_crs("EPSG:3857")
    shape_poly = shape.union_all()

    data_folder: Path = Path(data_folder)
    subfolder_name = shape_fn.stem \
                     if subfolder_name is None \
                     else subfolder_name

    # define list of tiles to be downloaded
    shape_tiles = get_wms_tiles(
        shape_poly,
        zoom_level,
    )
    shape_tiles = list(sorted(shape_tiles, key=lambda t: (t.x, t.y)))
    logger.info(f"Number of tiles found: {len(shape_tiles)}")

    # download tiles
    logger.info("- Download tiles")
    esri_folder = data_folder / subfolder_name / "esri"
    esri_folder.mkdir(exist_ok=True, parents=True)

    await download_tiles(
        shape_tiles,
        esri_folder,
        wms_url,
        first_n_tiles,
        n_workers,
    )


    # update tiles that located on border
    # remove part that is out of shape
    logger.info("- Refine border tiles")
    refine_border_tiles(
        shape_tiles,
        shape_poly,
        first_n_tiles,
        wld_suffix,
        esri_folder,
    )

    # retile
    if tile_size is not None:
        logger.info("- Retile")
        retile_folder = data_folder / subfolder_name / \
                        f"retile-{tile_size[0]}-{tile_size[1]}"
        retile_folder.mkdir(exist_ok=True, parents=True)
        run_gdal_retiling(
            esri_folder,
            retile_folder,
            tile_size,
            tile_overlap,
        )

        # Update non-square tiles and remove empty tiles
        logger.info(f"- Update and remove tiles from folder: {retile_folder}") 
        update_and_remove_tiles(
            retile_folder,
            tile_shape=tile_size,
        )

    # Done
    logger.info("Processing is done!")


if __name__ == "__main__":
    logger = add_handlers(
        logger,
        __file__,
        handlers=[
            DefaultConsoleHandler(),
            DefaultFileHandler("archive/logs/dewnload_wms_tiles.log")
        ]
    )
    Fire(main)
