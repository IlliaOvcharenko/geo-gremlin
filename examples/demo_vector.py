from logkit.core import (
    get_logger,
    add_handlers,
)
from logkit.handlers import (
    DefaultConsoleHandler,
    DefaultFileHandler,
)

logger = get_logger("geo_gremlin", __name__)

import geopandas as gpd

from pathlib import Path
from fire import Fire

from geo_gremlin.vector.overlap import resolve_overlaps
from geo_gremlin.vector.ortho import orthogonalize
from geo_gremlin.vector.utils import save_gdf
from geo_gremlin.vector.vis import (
    GdfVizConfig,
    subplot_gdf,
)


def main():
    test_file_fn = Path("data/suburban-1.geojson")
    test_gdf: gpd.GeoDataFrame = gpd.read_file(test_file_fn)

    overlap_gdf = resolve_overlaps(test_gdf)

    ortho_gdf = orthogonalize(overlap_gdf, n_workers=1, verbose=False)

    subplot_gdf(
        [
            GdfVizConfig(test_gdf, "blue", "input", False),
            GdfVizConfig(overlap_gdf, "green", "overlap", False),
            GdfVizConfig(ortho_gdf, "red", "ortho", False),
        ],
        "archive/figs/demo.png",
        fig_size=(30, 15),
        borders=False,
    )

    save_gdf(
        ortho_gdf,
        "archive/tmp/demo.geojson",
    )


if __name__ == "__main__":
    logger = add_handlers(
        logger,
        __file__,
        handlers=[
            DefaultConsoleHandler(),
            DefaultFileHandler("archive/logs/demo_overlap.log")
        ]
    )

    main()
