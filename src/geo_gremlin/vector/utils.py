from logkit.core import get_logger
logger = get_logger("geo_gremlin", __name__)

import numpy as np
import pandas as pd
import geopandas as gpd

from pathlib import Path
from shapely.validation import make_valid
from shapely.geometry import (
    Point,
    Polygon,
    MultiPolygon
)


def simplify_geometry(gdf, *_, eps=0.9):
    if gdf.empty:
        return gdf

    gdf.geometry = gdf.simplify(eps)
    # logger.info(f"Geomerty simplified with eps {eps}")
    return gdf


def area_filter(gdf, *_, min_area=1.0):
    if gdf.empty:
        return gdf

    selected_geom = gdf.area > min_area
    gdf = gdf[selected_geom]
    gdf = gdf.reset_index(drop=True)
    # logger.info(f"Apply area filter, min area: {min_area}")
    return gdf


def add_area(gdf, *_):
    if gdf.empty:
        return gdf

    gdf["area"] = gdf.geometry.apply(lambda sh: sh.area)
    return gdf


# TODO move to geometry.map(make_valid)
def make_geometry_valid(gdf, *_):
    if gdf.empty:
        return gdf

    for item_idx, item in gdf.iterrows():
        gdf.at[item_idx, "geometry"] = make_valid(item.geometry)

    # logger.info("Make geometry valid")
    return gdf


def save_gdf(
    gdf: gpd.GeoDataFrame,
    save_filename: str | Path,
    *,
    proj_name: str | None = None,
):
    if gdf.empty:
        # logger.info(f"geodataframe is empty")
        return
    assert not (gdf.crs is None and proj_name is None), \
        f"Projection is not specified for gdf"

    if (proj_name is not None):
        gdf = gdf.set_crs(proj_name)

    gdf.to_file(save_filename, driver="GeoJSON")


# TODO consider to replace with geopandas explode
def replace_multipolygons(gdf, *_):
    if gdf.empty:
        return gdf

    gdf = gdf.copy(deep=True)
    is_multipolygon = gdf.geometry.apply(
        lambda x: isinstance(x, MultiPolygon)
    )

    multipolygons = gdf[is_multipolygon]
    res = gdf[~is_multipolygon]

    for poly in multipolygons.geometry:
        for subpoly in poly.geoms:
                # res = res.append({"geometry": subpoly}, ignore_index=True)
                res = pd.concat([
                    res, gpd.GeoDataFrame({ "geometry": [subpoly] })
                ])

    res = res.reset_index(drop=True)
    # logger.info("Replace multipolygons")
    return res


def iou_with_polygons(p1, p2):
    intersection  = p1.intersection(p2).area
    union = p1.union(p2).area

    if union == 0.0:
        return 0.0
    return intersection / union


def polygon_to_points(polygon):
    return [Point(p[0], p[1]) for p in polygon.exterior.coords]


def points_to_polygon(points):
    return Polygon([(p.x, p.y) for p in points])
