"""
Utils to visualize polygons with matplotlib
"""

from logkit.core import get_logger
logger = get_logger("geo_gremlin", __name__)

import geopandas as gpd

from pathlib import Path
from dataclasses import dataclass
from shapely.geometry import Polygon

from .utils import polygon_to_points

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


@dataclass
class PolyVizConfig:
    """Visualization config for drawing one polygon.

    Attributes:
        poly (Polygon): Polygon to draw.
        color (str): Any matplotlib-compatible color.
        enumerate_vert (bool): If ``True``, put vertex indices near points.
    """
    poly: Polygon
    color: str
    enumerate_vert: bool = True


@dataclass
class GdfVizConfig:
    """Visualization config for drawing all geometries from one GeoDataFrame.

    This helper is mostly a convenient input object for ``plot_gdf`` and
    ``subplot_gdf``.

    Attributes:
        gdf (gpd.GeoDataFrame): GeoDataFrame to visualize.
        color (str): Any matplotlib-compatible color.
        title (str | None): Optional title (used in subplots).
        enumerate_vert (bool): If ``True``, put vertex indices near points.
    """
    gdf: gpd.GeoDataFrame
    color: str
    title: str | None = None
    enumerate_vert: bool = True

    def get_polys(self, ) -> list[Polygon]:
        return self.gdf.geometry.tolist()

    def get_viz_configs(self, ) -> list[PolyVizConfig]:
        return [
            PolyVizConfig(p, self.color, self.enumerate_vert)
            for p in self.get_polys()
        ]


def _plot_poly(pc: PolyVizConfig) -> None:
    points = polygon_to_points(pc.poly)
    plt.plot(
        [p.x for p in points],
        [p.y for p in points],
        ".-",
        color=pc.color
    )


    if pc.enumerate_vert:
        for p in set(points):
            idx = [str(i) for i, pp in enumerate(points) if p == pp]
            plt.text(p.x-0.5, p.y+0.5, ", ".join(idx))


def plot_polygons(
    polys: list[PolyVizConfig],
    fig_fn: str | Path,
    *,
    fig_size: tuple[int, int] | None = None,
) -> None:
    """Plot polygons on a single figure and save it.

    For side-by-side comparison, use ``subplot_polygons``.

    Args:
        polys (list[PolyVizConfig]): Polygon configs to draw.
        fig_fn (str | Path): Output image path.
        fig_size (tuple[int, int] | None): Figure size in inches. Defaults to
            ``(10, 10)``.

    Returns:
        None

    Example:
        ```python
        plot_polygons(
            polys=[PolyVizConfig(poly, "red", enumerate_vert=False)],
            fig_fn="archive/figs/poly.png",
            fig_size=(8, 8),
        )
        ```
    """
    fig_size = (10, 10) if fig_size is None else fig_size
    plt.figure(figsize=fig_size)

    for pc in polys:
        _plot_poly(pc)

    plt.axis("equal")
    plt.savefig(fig_fn, bbox_inches="tight")


def plot_gdf(
    gdf_config: GdfVizConfig,
    fig_fn: str | Path,
    *,
    fig_size: tuple[int, int] | None = None,
) -> None:
    """Plot a polygons from GeoDataFrame.

    This is a convenience wrapper over ``plot_polygons``.
    For multiple panels, see ``subplot_gdf``.

    Args:
        gdf_config (GdfVizConfig): What to plot and how.
        fig_fn (str | Path): Output image path.
        fig_size (tuple[int, int] | None): Figure size in inches.

    Returns:
        None
    """

    plot_polygons(
        polys=gdf_config.get_viz_configs(),
        fig_fn=fig_fn,
        fig_size=fig_size
    )


def subplot_polygons(
    polys_per_plot: list[list[PolyVizConfig]],
    fig_fn: str | Path,
    titles: list[str | None],
    *,
    fig_size: tuple[int, int] | None = None,
    borders: bool = True,
) -> None:
    """Plot several polygon groups as side-by-side subplots.

    This is useful when you want to compare stages of processing on one image.

    Args:
        polys_per_plot (list[list[PolyVizConfig]]): Polygons per subplot.
        fig_fn (str | Path): Output image path.
        titles (list[str | None]): Title per subplot.
        fig_size (tuple[int, int] | None): Figure size in inches.
        borders (bool): If ``False``, hide axes for cleaner visuals.

    Returns:
        None
    """
    fig_size = (10, 10) if fig_size is None else fig_size
    plt.figure(figsize=fig_size)
    for p_idx, polys in enumerate(polys_per_plot):
        plt.subplot(1, len(polys_per_plot), p_idx+1)

        for pc in polys:
            _plot_poly(pc)

        if not borders:
            plt.axis('off')

        plt.axis("equal")
        if titles[p_idx] is not None:
            plt.title(titles[p_idx], y=-0.05, ha='center', fontsize=20)
    plt.savefig(fig_fn, bbox_inches="tight")


def subplot_gdf(
    gdf_configs: list[GdfVizConfig],
    fig_fn: str | Path,
    *,
    fig_size: tuple[int, int] | None = None,
    borders: bool = True,
) -> None:
    """Plot several GeoDataFrames as side-by-side subplots.

    This wraps ``subplot_polygons`` and converts each config automatically.

    Args:
        gdf_configs (list[GdfVizConfig]): Configs to draw.
        fig_fn (str | Path): Output image path.
        fig_size (tuple[int, int] | None): Figure size in inches.
        borders (bool): If ``False``, hide subplot axes.

    Returns:
        None

    Example:
        ```python
        subplot_gdf(
            [
                GdfVizConfig(gdf, "blue", "input", False),
                GdfVizConfig(overlap, "green", "overlap", False),
                GdfVizConfig(ortho, "red", "ortho", False),
            ],
            "archive/figs/demo.png",
            fig_size=(30, 15),
            borders=False,
        )
        ```
    """
    subplot_polygons(
        [gc.get_viz_configs() for gc in gdf_configs],
        fig_fn,
        [gc.title for gc in gdf_configs],
        fig_size=fig_size,
        borders=borders,
    )
