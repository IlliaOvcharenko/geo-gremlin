from logkit.core import (
    get_logger,
    add_handlers,
)
from logkit.handlers import (
    DefaultConsoleHandler,
    DefaultFileHandler,
)
from fire import Fire

from geo_gremlin.cli_commands.download_wms_tiles import download_wms_tiles


logger = get_logger("geo_gremlin", "__main__")


class GeoGremlinCli:
    download_wms_tiles = staticmethod(download_wms_tiles)


def main():
    global logger
    logger = add_handlers(
        logger,
        "geo-gremlin-cli",
        handlers=[
            DefaultConsoleHandler(),
            DefaultFileHandler("archive/logs/geo-gremlin-cli.log"),
        ],
    )
    Fire(GeoGremlinCli)
