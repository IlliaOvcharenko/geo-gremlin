from logkit.core import get_logger
logger = get_logger("geo_gremlin", __name__)

import numpy as np
import numpy.typing as npt
import pandas as pd
import geopandas as gpd

from typing import Literal
from rtree import index
from shapely.geometry import shape as shapely_shape
from tqdm.cli import tqdm # pyright: ignore

from .utils import iou_with_polygons


__all__ = [
    "resolve_overlaps",
]

ResolveMode = Literal[
    "union",
    "intersection",
    "largest",
    "iou_select",
]

def resolve_overlaps(
    gdf: gpd.GeoDataFrame,
    mode: ResolveMode = "union",
    verbose: bool = False,
    **params,
) -> gpd.GeoDataFrame:
    """Resolve intersecting polygons inside a GeoDataFrame.

    The function builds an overlap graph, groups connected polygons, and then
    merges each group pair-by-pair using the selected strategy.

    Args:
        gdf (gpd.GeoDataFrame): Input GeoDataFrame with polygon geometries.
        mode (ResolveMode): Merge strategy:
            - ``"union"``: keep combined area.
            - ``"intersection"``: keep only shared area.
            - ``"largest"``: keep the bigger polygon.
            - ``"iou_select"``: use intersection when IoU is above threshold,
              otherwise union.
        verbose (bool): If ``True``, show tqdm progress bars.
        **params: Extra parameters for selected mode. For ``"iou_select"``,
            supports ``iou_threshold`` (float, default ``0.5``).

    Returns:
        gpd.GeoDataFrame: A new GeoDataFrame where overlaps are resolved and
        merged rows are dropped.
    """

    if gdf.empty:
        return gdf

    gdf = gdf.copy(deep=True)
    gdf = gdf.reset_index(drop=True)

    geom = gdf.geometry.tolist()

    n = len(gdf)
    graph = [set() for _ in range(n)]
    is_used = [False] * n
    parents = list(range(n))

    indx = index.Index()
    for i in tqdm(range(n), "build index", disable=not verbose):
        indx.insert(i, shapely_shape(geom[i]).bounds)


    for i in tqdm(range(n), "create graph", disable=not verbose):
        poly1 = geom[i]

        for j in indx.intersection(shapely_shape(poly1).bounds):
            if i == j:
                continue

            poly2 = geom[j]

            if poly1.intersects(poly2):
                graph[j].add(i)
                graph[i].add(j)

    def dfs(v, p, graph, is_used):
        is_used[v] = True
        parents[v] = p

        for child in graph[v]:
            if not is_used[child]:
                dfs(child, p, graph, is_used)

    for v in tqdm(range(n), "find roots", disable=not verbose):
        if is_used[v]:
            continue
        dfs(v, v, graph, is_used)

    mask = [True] * n
    for i in tqdm(range(n), "process overlapping", disable=not verbose):

        if parents[i] != i:
            try:
                if mode == "union":
                    merged = geom[parents[i]].union(geom[i])

                elif mode == "intersection":
                    merged = geom[parents[i]].intersection(geom[i])

                elif mode == "largest":
                    merged = geom[parents[i]] \
                             if geom[parents[i]].area > geom[i].area \
                             else geom[i]

                elif mode == "iou_select":
                    iou_threshold = params["iou_threshold"] \
                                    if "iou_threshold" in params \
                                    else 0.5

                    if iou_with_polygons(geom[parents[i]], geom[i]) \
                        > iou_threshold:

                        merged = geom[parents[i]].intersection(geom[i])
                    else:
                        merged = geom[parents[i]].union(geom[i])

                geom[parents[i]] = merged # pyright: ignore
                mask[i] = False

            except Exception as e:
                logger.info("Resolve overlappig error")
                logger.info(
                    f"First geom location " \
                    f"x: {geom[parents[i]].centroid.x}, " \
                    f"y: {geom[parents[i]].centroid.y}"
                )
                logger.info(
                    f"Second geom location " \
                    f"x: {geom[i].centroid.x}, " \
                    f"y: {geom[i].centroid.y}"
                )
                logger.info(e)

    gdf["geometry"] = gpd.GeoSeries(geom)
    gdf = gdf[mask]
    gdf = gdf.reset_index(drop=True)
    return gdf
