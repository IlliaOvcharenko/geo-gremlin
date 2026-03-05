"""
Utils related to raster processing
Mainly  converting raster to a vector and preserve geo referencing
And vice verse

"""
from logkit.core import get_logger
logger = get_logger("geo_gremlin", __name__)

import cv2
import rasterio
from rasterio.features import rasterize
from shapely.geometry import Polygon, MultiPolygon

import numpy as np
import geopandas as gpd


def gdal_imread(filename, return_geotransform=True):
    try:
        from osgeo import gdal
    except:
        logger.info("GDAL installation is missing, exit")
        exit(0)

    filename = str(filename)
    ds = gdal.Open(filename)
    geotransform = ds.GetGeoTransform()
    channels_num = ds.RasterCount
    img = None

    if channels_num == 1:
        img = ds.GetRasterBand(1).ReadAsArray()
    else:
        channels = [
            ds.GetRasterBand(i).ReadAsArray() \
            for i in range(1, channels_num+1)
        ]
        img = np.stack(channels, axis=2)

    if return_geotransform:
        return img, geotransform
    return img


# TODO
#
# it seems to be a more elegant way to calculate inv geotransform :)
#
# ```python
#
#     # calculate inv geotrasform
#     a, d, b, e, c, f = tile_geot
#     tile_geot_M = np.array([
#         [a,   b,    c],
#         [d,   e,    f],
#         [0.0, 0.0, 1.0],
#     ])
#     tile_geot_M_inv = np.linalg.inv(tile_geot_M)
#     tile_geot_M_inv /= tile_geot_M[-1, -1]
# 
#     tile_geot_inv = [
#         tile_geot_M_inv[0, 0],
#         tile_geot_M_inv[0, 1],
#         tile_geot_M_inv[1, 0],
#         tile_geot_M_inv[1, 1],
#         tile_geot_M_inv[0, 2],
#         tile_geot_M_inv[1, 2],
#     ]
#     tile_geot_inv = [float(p) for p in tile_geot_inv]
#
#     # calculate bin mask for pixels to leave
#     tile_img = cv2.imread(str(tile_fn.with_suffix(".png")))
#     tile_shape = (tile_img.shape[0], tile_img.shape[1])
# 
#     mask_poly = tile_poly.intersection(shape_poly)
#     mask_poly = affine_transform(mask_poly, tile_geot_inv)
# 
#     mask = rasterize(
#         [(mask_poly, 1)],
#         out_shape=tile_shape,
#         fill=0,
#         all_touched=True,
#         dtype=np.uint8,
#         default_value=1,
#     )
#     mask = mask.astype(bool)
#     tile_img[~mask] = 0
# ```

def lat_lon_to_pixel_space(gdf, geotransform):
    """

    """
    if len(gdf) == 0:
        return gdf

    xoff, a, b, yoff, d, e  = geotransform
    # reverse affine transformation
    xoff = -xoff / a
    yoff = -yoff / e

    a = 0.0 if a == 0.0 else 1 / a
    b = 0.0 if b == 0.0 else 1 / b
    d = 0.0 if d == 0.0 else 1 / d
    e = 0.0 if e == 0.0 else 1 / e

    gdf = gdf.copy(deep=True)
    gdf["geometry"] = gdf["geometry"].affine_transform([
        a, b, d, e, xoff, yoff
    ])
    return gdf


def pixel_space_to_lat_lon(gdf, geotransform):
    if gdf.empty:
        return gdf
    xoff, a, b, yoff, d, e  = geotransform
    gdf = gdf.copy(deep=True)
    gdf["geometry"] = gdf["geometry"] \
                     .affine_transform([a, b, d, e, xoff, yoff])
    return gdf


def raster_to_gdf(raster):
    contours, _ = cv2.findContours(
        raster,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    geoms = []
    for contour in contours:
        points = contour[:, 0,  :]
        if len(points) >= 3:
            poly =  Polygon(points).buffer(1)
            if isinstance(poly, Polygon):
                geoms.append({ "geometry": poly})

            elif isinstance(poly, MultiPolygon):
                for subpoly in poly: # pyright: ignore
                     geoms.append({ "geometry": subpoly})
    gdf = gpd.GeoDataFrame(geoms)
    return gdf


def gdf_to_raster(gdf, out_shape, value=1):
    if len(gdf) == 0:
        return np.zeros(out_shape, dtype=np.uint8)

    raster = rasterize(
        [(g, 1) for g in gdf['geometry']],
        out_shape=out_shape,
        fill=0,
        all_touched=False,
        dtype=rasterio.uint8,
        default_value=value,
    )
    return raster


def get_img_bounds(img_shape, geotransform):
    nx = img_shape[1]
    ny = img_shape[0]
    x_min, xres, _, y_max, _, yres = geotransform
    yres = -yres

    x_max = (xres * nx) + x_min
    y_min = -((yres * ny) - y_max)

    bounds = Polygon([
        (x_min, y_min),
        (x_min, y_max),
        (x_max, y_max),
        (x_max, y_min),
    ])
    return bounds


def create_mask(
    img,
    geotransform,
    gdf,
):
    img_shape = img.shape[:-1]
    bounds = get_img_bounds(img_shape, geotransform)

    gdf = gdf[gdf.geometry.notna()]

    if gdf.intersects(bounds).any():
        clipped_gdf = gpd.clip(gdf, bounds)
        clipped_gdf = lat_lon_to_pixel_space(clipped_gdf, geotransform)
        mask = gdf_to_raster(clipped_gdf, img_shape)
    else:
        mask = np.zeros(img_shape, dtype=np.uint8)
    return mask
