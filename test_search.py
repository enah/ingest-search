import os
from datetime import datetime, timezone
import pytest
import pystac

from search import Search


@pytest.fixture
def mock_catalog_dir(tmp_path):
    """Fixture that creates a temporary STAC catalog with diverse items for testing."""
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()

    # Create a STAC Catalog root
    catalog = pystac.Catalog(id="test-catalog", description="Test catalog for R-tree search")

    # Item 1: Point datetime, standard bbox, product_type = "displacement_points"
    item1 = pystac.Item(
        id="item-point-1",
        geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]]},
        bbox=[0.0, 0.0, 2.0, 2.0],
        datetime=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        properties={"product_type": "displacement_points"}
    )

    # Item 2: Interval datetime (start/end), different bbox, product_type = "flood_extent"
    item2 = pystac.Item(
        id="item-interval-2",
        geometry={"type": "Polygon", "coordinates": [[[10, 10], [10, 12], [12, 12], [12, 10], [10, 10]]]},
        bbox=[10.0, 10.0, 12.0, 12.0],
        datetime=None,
        properties={
            "start_datetime": "2026-06-01T00:00:00Z",
            "end_datetime": "2026-06-05T23:59:59Z",
            "product_type": "flood_extent"
        }
    )

    # Item 3: Invalid/Skipped item (missing bbox or temporal data)
    item_invalid = pystac.Item(
        id="item-invalid",
        geometry={"type": "Point", "coordinates": [0, 0]},
        bbox=None,  # Missing bbox should be skipped by _build_index
        datetime=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        properties={"product_type": "displacement_points"}
    )

    catalog.add_items([item1, item2, item_invalid])
    
    # Normalize hrefs and save catalog locally
    catalog.normalize_hrefs(str(catalog_dir))
    catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)

    return catalog_dir


@pytest.fixture
def search_engine(mock_catalog_dir):
    catalog_json_path = os.path.join(mock_catalog_dir, "catalog.json")
    return Search(catalog_json_path)


# --- 1. Timestamp Conversion Tests ---

def test_datetime_to_timestamp_aware(search_engine):
    dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    ts = search_engine._datetime_to_timestamp(dt)
    assert ts == 1767225600.0


def test_datetime_to_timestamp_naive(search_engine):
    dt = datetime(2026, 1, 1, 0, 0, 0)  # Naive datetime
    ts = search_engine._datetime_to_timestamp(dt)
    # Should automatically convert assuming UTC
    assert ts == 1767225600.0


# --- 2. Index Building Tests ---

def test_build_index_skips_invalid_items(search_engine):
    # Only item1 and item2 should be indexed; item_invalid should be skipped
    assert len(search_engine.idx) == 2


# --- 3. Spatio-Temporal Search Tests (`search_rtree`) ---

def test_search_rtree_spatial_and_temporal_match(search_engine):
    # Query covering Item 1 spatially and temporally
    query_bbox = (0.0, 0.0, 2.0, 2.0)
    query_start = datetime(2026, 5, 30, tzinfo=timezone.utc)
    query_end = datetime(2026, 6, 2, tzinfo=timezone.utc)

    results = search_engine.search_rtree(query_bbox, query_start, query_end)
    
    assert len(results) == 1
    assert results[0].id == "item-point-1"


def test_search_rtree_spatial_match_temporal_miss(search_engine):
    # Query covering Item 1 spatially, but out of its time window
    query_bbox = (0.0, 0.0, 2.0, 2.0)
    query_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    query_end = datetime(2026, 7, 10, tzinfo=timezone.utc)

    results = search_engine.search_rtree(query_bbox, query_start, query_end)
    assert len(results) == 0


def test_search_rtree_interval_matching(search_engine):
    # Query covering interval Item 2
    query_bbox = (10.0, 10.0, 12.0, 12.0)
    query_start = datetime(2026, 6, 3, tzinfo=timezone.utc)
    query_end = datetime(2026, 6, 4, tzinfo=timezone.utc)

    results = search_engine.search_rtree(query_bbox, query_start, query_end)
    
    assert len(results) == 1
    assert results[0].id == "item-interval-2"


# --- 4. High-Level Filtered Search Tests (`search`) ---

def test_search_with_product_type_filter(search_engine):
    # Broad spatial/temporal query that would capture both items, filtered by product type
    query_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    query_end = datetime(2026, 6, 10, tzinfo=timezone.utc)

    results = search_engine.search(
        query_start=query_start,
        query_end=query_end,
        product_type="flood_extent"
    )

    assert len(results) == 1
    assert results[0].id == "item-interval-2"
    assert results[0].properties.get("product_type") == "flood_extent"


def test_search_default_loose_bbox(search_engine):
    # Omitting bbox should default to infinite bounds (-inf to +inf)
    results = search_engine.search(
        query_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
        query_end=datetime(2026, 6, 2, tzinfo=timezone.utc)
    )
    
    # Should find item-point-1
    assert any(item.id == "item-point-1" for item in results)
