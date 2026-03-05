from logkit.core import get_logger
logger = get_logger("geo_gremlin", __name__)

import rasterio
import math

import numpy as np
import pandas as pd
import geopandas as gpd

from rasterio.features import rasterize
from rasterio.warp import (reproject,
                           Resampling)
from shapely.affinity import (scale,
                              affine_transform)
from shapely.geometry import Point


def get_bounds(poly, scale_factor, verbose=False):
    # Define image bounds
    bound = poly.minimum_rotated_rectangle
    bound = scale(bound, scale_factor, scale_factor)

    square_bounds = True
    if square_bounds:
        logger.info("use square bounds")
        bound_points = [Point(p[0], p[1]) for p in bound.exterior.coords]
        bound_points = list(reversed(bound_points))

        first_edge = (bound_points[1].x - bound_points[0].x,
                      bound_points[1].y - bound_points[0].y)
        second_edge = (bound_points[3].x - bound_points[0].x,
                       bound_points[3].y - bound_points[0].y)

        first_edge_len = math.sqrt(first_edge[0] ** 2 + first_edge[1] ** 2)
        second_edge_len = math.sqrt(second_edge[0] ** 2 + second_edge[1] ** 2)
        if first_edge_len >= second_edge_len:
            x_edge, y_edge = first_edge, second_edge
            aspect_ratio = first_edge_len / second_edge_len
        else:
            x_edge, y_edge = second_edge, first_edge
            aspect_ratio = second_edge_len / first_edge_len

        parallel_axes_transform = rasterio.Affine(
            a=x_edge[0],
            b=y_edge[0],
            c=0.0,
            d=x_edge[1],
            e=y_edge[1],
            f=0.0,
        )
        bound = affine_transform(bound, (~parallel_axes_transform).to_shapely())
        bound = scale(bound, yfact=aspect_ratio)
        bound = affine_transform(bound, parallel_axes_transform.to_shapely())

    return bound


def get_transform(
    bound,
    projected_width=1024,
    projected_height=1024,
    proportional_shape=False,
    verbose=False,
):
    bound_points = [Point(p[0], p[1]) for p in bound.exterior.coords]
    bound_points = list(reversed(bound_points))

    # TODO sort points clockwise, check if they are already always sorted
    # TODO select top left point, sometimes result reprojected image is roatates due to that

    # Define new transform matrix (map pixel coords on reprojected image with
    #                              real world coord in utm crs)
    # TODO rename, proportional out shape
    if proportional_shape:
        w_vec_len = math.sqrt((bound_points[1].x - bound_points[0].x) ** 2 +
                              (bound_points[1].y - bound_points[0].y) ** 2)
        h_vec_len = math.sqrt((bound_points[3].x - bound_points[0].x) ** 2 +
                              (bound_points[3].y - bound_points[0].y) ** 2)
        # projected_width = 512
        projected_height = int(projected_width * (h_vec_len / w_vec_len))
        logger.info(f"use proportional shape: {projected_width} {projected_height}")
    else:
        # projected_width, projected_height = 512, 512
        # projected_width, projected_height = 512, 1024
        # projected_width, projected_height = 1024, 1024
        logger.info(f"use static shape: {projected_width} {projected_height}")

    transform = rasterio.Affine(
        a=(bound_points[1].x - bound_points[0].x) / projected_width,
        b=(bound_points[3].x - bound_points[0].x) / projected_height,
        c=bound_points[0].x,
        d=(bound_points[1].y - bound_points[0].y) / projected_width,
        e=(bound_points[3].y - bound_points[0].y) / projected_height,
        f=bound_points[0].y
    )

    return transform, projected_width, projected_height


# Probably a duplicate
# def poly_to_raster(
#     poly,
#     projected_width,
#     projected_height,
# ):
#     raster = rasterize(
#         [(poly, 1)],
#         out_shape=(projected_height, projected_width),
#         fill=0,
#         all_touched=False,
#         dtype=rasterio.uint8,
#         default_value=1,
#     )
#     return raster


# TODO this is the function
def crop_raster(
    band,
    bands_crs,
    x_object_poly,
    projected_shape,
    scale_factor,
):
    """
    Allow to crop for any rectengular polygon, even  with rotation.
    """
    projected_height, projected_width = projected_shape

    bound = get_bounds(x_object_poly, scale_factor)
    crop_transform, _, _ = get_transform(bound, projected_width, projected_height)

    # Reproject satellite data
    band_data_projected = np.zeros(
        (projected_height, projected_width),
        np.uint16
    )
    band_data_projected, _ = reproject(
        band.read(1),
        band_data_projected,
        src_transform=band.transform,
        src_crs=band.crs,
        dst_transform=crop_transform,
        dst_crs=bands_crs,
        resampling=Resampling.nearest,
    )

    return band, crop_transform
