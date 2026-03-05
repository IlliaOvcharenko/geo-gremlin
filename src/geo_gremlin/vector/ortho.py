from logkit.core import get_logger
logger = get_logger("geo_gremlin", __name__)

import numpy as np
import numpy.typing as npt
import geopandas as gpd
import multiprocessing as mp

from typing import Any
from shapely.geometry import (
    Polygon,
    Point,
)
from tqdm.cli import tqdm # pyright: ignore


from .utils import (
    replace_multipolygons,
    polygon_to_points,
    points_to_polygon,
    iou_with_polygons,
)


__all__ = [
    "orthogonalize_poly",
    "orthogonalize",
]


def shift_items(
    list_to_shift: list[Any],
    n: int
) -> list[Any]:

    list_to_shift = list_to_shift[:-1]
    list_to_shift = list_to_shift[n:] + list_to_shift[:n]
    list_to_shift.append(list_to_shift[0])
    return list_to_shift


def p_to_v(p): return np.array([p.x, p.y]).reshape(-1, 1) # points to vectors
def v_to_p(v): return Point(v[0, 0], v[1, 0]) # vectors to points


def orthogonalize_vectors(vectors: list[npt.NDArray]) -> list[npt.NDArray]:
    """
    Polygons are represented as a list points vectors.
    Such format make it easy to work with point via linalg functions.

    Walk through every consecutive triplets of points (a, b, c).
    Update middle point (b) to be a projection of last point (c)
        into a line a-b.

    That should enforce a 90 deg angle between every consecutive pair
        of lines in polygon.

    """

    vectors = vectors[:]

    try:
        for i in range(len(vectors) - 3 + 1):
            av, bv, cv = vectors[i:i+3]

            # v1 is a-b vector
            v1 = bv - av

            # v2 is a-c vector
            v2 = cv - av

            # project v2 on v1 (new_v1) if v1 and v2 are not collinear
            # otherwise do not move any point

            v1_len = np.linalg.norm(v1)
            if v1_len == 0.0:
                continue

            v2_len = np.linalg.norm(v2)
            if v2_len == 0.0:
                continue

            v1_norm = v1 / v1_len
            new_v1_len = v1_norm.T @ v2

            # collinear check
            if np.isclose(
                np.abs(new_v1_len), v2_len,
                rtol=0.0, atol=1e-7
            ):
                continue

            new_v1 = v1_norm * new_v1_len
            new_bv = new_v1 + av
            vectors[i+1] = new_bv

    except Exception as e:
        logger.debug(e)

    return vectors


def orthogonalize_poly(poly: Polygon) -> Polygon:
    """ Othogonalize single polygon.

    Args:
        poly (Polygon): A shapely Polygon to orthogonalize
    Returns:
        Polygon: An orthogonalized version of the input polygon


    Basic idea is to generate a bunch of orthognolized
    polygons (proposals) and then select the best one based on
    better IoU with original polygon

    Proposals generated based on original polygon with different
    starting points, and convex hull version of the original polygon

    Points should be sorted in a same direction for code to work properly
    (for example clock wise). It should always be the case for shapely
    Polygons.
    """

    if not poly.is_valid:
        return poly

    proposals = []

    points = polygon_to_points(poly)
    vectors = [p_to_v(p) for p in points]
    proposals += [
        orthogonalize_vectors(shift_items(vectors, shift))
        for shift in range(len(points))
    ]

    points_convex_hull = polygon_to_points(poly.convex_hull)
    vectors_convex_hull = [p_to_v(p) for p in points_convex_hull]
    proposals += [
        orthogonalize_vectors(
            shift_items(vectors_convex_hull, shift)
        )
        for shift in range(len(points))
    ]

    # Convert proposals from a list of vectors to a polygons
    proposals = [
        points_to_polygon([v_to_p(v) for v in proposal])
        for proposal in proposals
    ]
    proposals = [
        proposal for proposal in proposals
        if proposal.is_valid
    ]

    # Select best proposal based on intersection with original polygon.
    proposals = sorted(
        proposals,
        key=lambda p: iou_with_polygons(poly, p),
        reverse=True
    )
    best_proposal = proposals[0] if len(proposals) > 0 else poly

    return best_proposal


def orthogonalize(
    gdf: gpd.GeoDataFrame,
    *,
    n_workers: int = 6,
    verbose: bool = False,
):
    """Orthogonalize all polygon geometries in a GeoDataFrame.

    This is a batch wrapper over ``orthogonalize_poly``. It also replaces
    multipolygons first, then runs either single-process or multiprocessing
    execution depending on ``n_workers``.

    Args:
        gdf (gpd.GeoDataFrame): Input GeoDataFrame with polygon geometries.
        n_workers (int): Number of worker processes. Use ``1`` for sequential
            processing.
        verbose (bool): If ``True``, show tqdm progress bars.

    Returns:
        gpd.GeoDataFrame: A GeoDataFrame with orthogonalized geometries.
    """
    if gdf.empty:
        return gdf

    gdf = replace_multipolygons(gdf)

    geoms = gdf["geometry"].tolist()
    ortho_geoms = []

    pbar_desc = "ortho processing"

    if n_workers <= 1:
        for g in tqdm(geoms, desc=pbar_desc, disable=(not verbose)):
            ortho_geoms.append(orthogonalize_poly(g))

    else:
        with mp.Pool(n_workers) as p:
            ortho_geoms += list(tqdm(p.imap(
                orthogonalize_poly,
                geoms,
            ), total=len(geoms), desc=pbar_desc, disable=(not verbose)))

    gdf["geometry"] = gpd.GeoSeries(ortho_geoms)
    return gdf
