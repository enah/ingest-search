import os
import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
import pystac

from ingest import Metadata, Ingest


@pytest.fixture
def temp_catalog(tmp_path):
    """Fixture providing an Ingest instance with a temporary catalog directory."""
    return Ingest(catalog_dir=str(tmp_path / "catalog"))


@pytest.fixture
def sample_metadata_standard():
    return Metadata(
        product_type="displacement_points",
        classification="standard",
        contract_id="CT-123456",
        datetime=datetime.now(timezone.utc)
    )


@pytest.fixture
def sample_metadata_restricted():
    return Metadata(
        product_type="flood_extent",
        classification="restricted",
        contract_id="CT-987654",
        datetime=datetime.now(timezone.utc)
    )


# --- 1. Metadata Validation Tests ---

def test_validate_metadata_success(temp_catalog, sample_metadata_standard):
    assert temp_catalog.validate_metadata(sample_metadata_standard) is None


def test_validate_metadata_invalid_product_type(temp_catalog, sample_metadata_standard):
    sample_metadata_standard.product_type = "invalid_type"
    assert temp_catalog.validate_metadata(sample_metadata_standard) == "Rejected: unknown product_type"


def test_validate_metadata_invalid_classification(temp_catalog, sample_metadata_standard):
    sample_metadata_standard.classification = "secret"
    assert temp_catalog.validate_metadata(sample_metadata_standard) == "Rejected: unknown classification"


@pytest.mark.parametrize("bad_id", ["CT-12345", "CT-1234567", "AB-123456", "123456"])
def test_validate_metadata_invalid_contract_id(temp_catalog, sample_metadata_standard, bad_id):
    sample_metadata_standard.contract_id = bad_id
    assert temp_catalog.validate_metadata(sample_metadata_standard) == "Rejected: bad contract_id"


# --- 2. Storage Path Building Tests ---

def test_build_storage_path_standard(temp_catalog, sample_metadata_standard):
    path = temp_catalog.build_storage_path(sample_metadata_standard)
    now = datetime.now()
    expected = f"storage/datalake/displacement_points/{now.year}/{now.month}/"
    assert path == expected


def test_build_storage_path_restricted(temp_catalog, sample_metadata_restricted):
    path = temp_catalog.build_storage_path(sample_metadata_restricted)
    expected = "storage/restricted/CT-987654/flood_extent/"
    assert path == expected


# --- 3. CSV File Validation Tests ---

def test_validate_csv_success(temp_catalog, tmp_path):
    csv_file = tmp_path / "test.csv"
    csv_file.write_text(
        "point_id,lat,lon,displacement_mm,velocity_mm_yr,measured_at\n"
        "1,34.05,-118.24,1.5,2.0,2026-01-01T00:00:00Z",
        encoding="utf-8"
    )
    assert temp_catalog.validate_csv(csv_file) is None


def test_validate_csv_wrong_header(temp_catalog, tmp_path):
    csv_file = tmp_path / "bad_header.csv"
    csv_file.write_text(
        "wrong,header,format\n"
        "1,2,3",
        encoding="utf-8"
    )
    assert temp_catalog.validate_csv(csv_file) == "Rejected: wrong header"


def test_validate_csv_no_data(temp_catalog, tmp_path):
    csv_file = tmp_path / "empty.csv"
    csv_file.write_text(
        "point_id,lat,lon,displacement_mm,velocity_mm_yr,measured_at\n",
        encoding="utf-8"
    )
    assert temp_catalog.validate_csv(csv_file) == "Rejected: no data"


# --- 4. GeoJSON File Validation Tests ---

def test_validate_geojson_success(temp_catalog, tmp_path):
    geojson_file = tmp_path / "test.geojson"
    geojson_file.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    assert temp_catalog.validate_geojson(geojson_file) is None


def test_validate_geojson_invalid_json(temp_catalog, tmp_path):
    geojson_file = tmp_path / "invalid.geojson"
    geojson_file.write_text('not valid json', encoding="utf-8")
    assert temp_catalog.validate_geojson(geojson_file) == "Rejected: file is not valid json"


def test_validate_geojson_file_not_found(temp_catalog, tmp_path):
    missing_file = tmp_path / "missing.geojson"
    assert temp_catalog.validate_geojson(missing_file) == "Rejected: file is not valid json"


# --- 5. End-to-End Ingestion Tests ---

def test_ingest_displacement_points_success(temp_catalog, sample_metadata_standard, tmp_path, monkeypatch):
    csv_file = tmp_path / "points.csv"
    csv_file.write_text(
        "point_id,lat,lon,displacement_mm,velocity_mm_yr,measured_at\n"
        "1,34.05,-118.24,1.5,2.0,2026-01-01T00:00:00Z\n"
        "2,35.05,-117.24,2.5,3.0,2026-01-02T00:00:00Z",
        encoding="utf-8"
    )
    
    monkeypatch.setattr(Ingest, "copy_to_storage", lambda self, file_path, storage_path: None)

    result = temp_catalog.ingest(str(csv_file), sample_metadata_standard)
    assert result == "Success"

    # Verify STAC catalog has item stored
    catalog = pystac.Catalog.from_file(os.path.join(temp_catalog.catalog_dir, "catalog.json"))
    assert len(list(catalog.get_items())) == 1


def test_ingest_duplicate_item(temp_catalog, sample_metadata_standard, tmp_path):
    csv_file = tmp_path / "points.csv"
    csv_file.write_text(
        "point_id,lat,lon,displacement_mm,velocity_mm_yr,measured_at\n"
        "1,34.05,-118.24,1.5,2.0,2026-01-01T00:00:00Z",
        encoding="utf-8"
    )

    # First ingest
    assert temp_catalog.ingest(str(csv_file), sample_metadata_standard) == "Success"
    # Second ingest of the exact same data should be rejected as duplicate
    assert temp_catalog.ingest(str(csv_file), sample_metadata_standard) == "Rejected: duplicate"


def test_ingest_flood_extent_success(temp_catalog, sample_metadata_restricted, tmp_path, monkeypatch):
    geojson_file = tmp_path / "flood.geojson"
    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]
                },
                "properties": {
                    "acquired": "2026-05-01T12:00:00Z"
                }
            }
        ]
    }
    geojson_file.write_text(json.dumps(feature_collection), encoding="utf-8")
    
    monkeypatch.setattr(Ingest, "copy_to_storage", lambda self, file_path, storage_path: None)

    result = temp_catalog.ingest(str(geojson_file), sample_metadata_restricted)
    assert result == "Success"


def test_ingest_file_does_not_exist(temp_catalog, sample_metadata_standard):
    result = temp_catalog.ingest("non_existent_file.csv", sample_metadata_standard)
    assert result == "Rejected: file does not exist"
