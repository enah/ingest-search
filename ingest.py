from pydantic import BaseModel
from typing import Optional
from pathlib import Path
import re
from datetime import datetime, timezone
import json
import uuid
from shapely.geometry import shape, MultiPolygon, MultiPoint, mapping, box
from shapely.ops import unary_union
import pystac
import csv
import os
import sys
import shutil

now = datetime.now()

current_year = now.year
current_month = now.month

class Metadata(BaseModel):
    product_type: str
    classification: str
    contract_id: str
    datetime: Optional[datetime]
    
class Ingest:
    def __init__(self, catalog_dir):
        self.catalog_dir = catalog_dir
        
    def validate_metadata(self, metadata):
        if metadata.product_type not in ('displacement_points', 'flood_extent', 'change_detection'):
            return "Rejected: unknown product_type"
        if metadata.classification not in ('standard', 'restricted'):
            return "Rejected: unknown classification"
        contract_pattern = r"^CT-\d{6}$"
        if not re.match(contract_pattern, metadata.contract_id):
            return "Rejected: bad contract_id"
        return None
        
    def build_storage_path(self, metadata):
        if metadata.classification == 'standard':
            return f"storage/datalake/{metadata.product_type}/{current_year}/{current_month}/"
        elif metadata.classification == 'restricted':
            return f"storage/restricted/{metadata.contract_id}/{metadata.product_type}/"
        return None
        
    def validate_csv(self, file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            first_line = next(f, None)
            if first_line.strip() != "point_id,lat,lon,displacement_mm,velocity_mm_yr,measured_at":
                return "Rejected: wrong header"
            if not next(f, None):
                return "Rejected: no data"
        return None
    
    def validate_geojson(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                json.load(f)
            return None
        except (json.JSONDecodeError, FileNotFoundError):
            return "Rejected: file is not valid json"

    def ingest(self, file_path, metadata):
        # validate metadata
        reject_reason = self.validate_metadata(metadata)
        if reject_reason:
            return reject_reason
            
        # check file exits
        if not Path(file_path).is_file():
            return "Rejected: file does not exist"
        
        # build storage path
        storage_path = self.build_storage_path(metadata)
        if not storage_path:
            return "Rejected: unknown classification"
        
        if metadata.product_type == "displacement_points":
            reject_reason = self.validate_csv(file_path)
            if reject_reason:
                return reject_reason
            item = self.ingest_csv(file_path, storage_path, metadata)
        
        elif metadata.product_type == "flood_extent":
            reject_reason = self.validate_geojson(file_path)
            if reject_reason:
                return reject_reason
            timestamp_lambda = lambda feature_list: [datetime.fromisoformat(feature["properties"]["acquired"]) for feature in feature_list]
            item = self.ingest_geojson(file_path, storage_path, metadata, timestamp_lambda)
        
        elif metadata.product_type == "change_detection":
            reject_reason = self.validate_geojson(file_path)
            if reject_reason:
                return reject_reason
            timestamp_lambda = lambda feature_list: [datetime.fromisoformat(timestamp) for feature in feature_list for timestamp in (feature["properties"]["before_acquired"], feature["properties"]["after_acquired"])]
            item = self.ingest_geojson(file_path, storage_path, metadata, timestamp_lambda)
        
        else:
            return "Rejected: unknown product_type"
            
        # open catalog if exists, store in catalog
        if not self.store_stac_item(item):
            return "Rejected: duplicate"
        
        # copy file to storage path
        self.copy_to_storage(file_path, storage_path)
        
        return "Success"
        
    def create_stac_item(self, geom_mapping, bbox, timestamps, metadata):
        start_time = min(timestamps)
        end_time = max(timestamps)
        
        geom_string = json.dumps(geom_mapping, sort_keys=True)
        NAMESPACE_STAC = uuid.NAMESPACE_URL
        item_id = str(uuid.uuid5(NAMESPACE_STAC, geom_string))
        
        item = pystac.Item(
            id=item_id,
            geometry=geom_mapping,
            bbox=bbox,
            datetime=None,  # Set to None when using start/end intervals
            properties={
                "start_datetime": start_time.isoformat(),
                "end_datetime": end_time.isoformat(),
                "product_type": metadata.product_type,
                "classification": metadata.classification,
                "contract_id": metadata.contract_id
            }
        )
        
        return item
        
    def ingest_csv(self, csv_file, storage_path, metadata):

        # 1. Read points and parse attributes from the CSV file
        points = []
        longitudes = []
        latitudes = []
        timestamps = []

        with open(csv_file, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # skip row if invalid
                lon = float(row["lon"])
                lat = float(row["lat"])
                points.append((lon, lat))
                longitudes.append(lon)
                latitudes.append(lat)
                timestamps.append(datetime.fromisoformat(row["measured_at"].replace("Z", "+00:00")))

        # 2. Construct GeoJSON MultiPoint geometry
        multipoint_geom = MultiPoint(points)
        geom_mapping = mapping(multipoint_geom)

        # 3. Calculate bounding box [xmin, ymin, xmax, ymax]
        bbox = [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]

        # 4. Create the STAC Item
        item = self.create_stac_item(geom_mapping, bbox, timestamps, metadata)
        
        # 5. Add the stored file as an asset
        item.add_asset(
            key="data",
            asset=pystac.Asset(
                href=storage_path + Path(csv_file).name,
                media_type="text/csv",
                roles=["data"],
                title="Source CSV Measurement Data"
            )
        )
    
        return item
        
    def ingest_geojson(self, geojson_file, storage_path, metadata, timestamps_lambda):
        # 1. Load the GeoJSON FeatureCollection
        with open(geojson_file, "r") as f:
            fc = json.load(f)

        # 2. Extract and union all geometries
        geometries = [shape(feature["geometry"]) for feature in fc["features"]]
        combined_geom = unary_union(geometries)

        # Ensure it's treated as a MultiPolygon correctly
        if combined_geom.geom_type == "Polygon":
            combined_geom = MultiPolygon([combined_geom])
        geom_mapping = mapping(combined_geom)

        # 3. Calculate bounding box [xmin, ymin, xmax, ymax]
        bbox = list(combined_geom.bounds)
    
        # 4. Timestamps
        timestamps = timestamps_lambda(fc["features"])

        # 5. Create the STAC Item
        item = self.create_stac_item(geom_mapping, bbox, timestamps, metadata)

        # 6. Add the original GeoJSON file as an asset
        item.add_asset(
            key="data",
            asset=pystac.Asset(
                href=storage_path + Path(geojson_file).name,
                media_type=pystac.MediaType.GEOJSON,
                roles=["data"],
                title="Source GeoJSON FeatureCollection"
            )
        )
    
        return item
        
    def store_stac_item(
            self,
            item: pystac.Item,
            catalog_id: str = "stac-catalog",
            catalog_description: str = "STAC Catalog root"
        ) -> str:
        """Stores a STAC item in a catalog, initializing the catalog if it does not exist.
    
        Args:
            item: The pystac.Item instance to store.
            catalog_id: ID for the catalog if it needs to be initialized.
            catalog_description: Description for the catalog if it needs to be initialized.
        
        Returns:
        Success str if success.
        """
        catalog_file = os.path.join(self.catalog_dir, "catalog.json")
        
        # Initialize catalog if it doesn't exist
        if not os.path.exists(catalog_file):
            os.makedirs(self.catalog_dir, exist_ok=True)
            catalog = pystac.Catalog(
                id=catalog_id,
                description=catalog_description
            )
            print(f"Initialized new STAC catalog at {self.catalog_dir}")
        else:
            # Load existing catalog
            catalog = pystac.Catalog.from_file(catalog_file)
            print(f"Loaded existing STAC catalog from {self.catalog_dir}")
        
        # Check if the item is already added to avoid duplicates
        existing_item = catalog.get_item(item.id, recursive=False)
        if existing_item is not None:
            print(f"Item '{item.id}' already existed in catalog.")
            return

        # Add the item to the catalog
        catalog.add_item(item)
    
        # Normalize hrefs to ensure self-contained relative paths
        catalog.normalize_hrefs(self.catalog_dir)
    
        # Save the catalog and all modified/new items
        catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)
        print(f"Successfully stored item '{item.id}' in catalog at {self.catalog_dir}")
    
        return "Success"

    def copy_to_storage(self, file_path, storage_path):
        Path(storage_path).mkdir(parents=True, exist_ok=True)
        shutil.copy(file_path, storage_path)

if __name__ == "__main__":
    root_path="dx-pipeline-assignment/files/"
    uploads_json="dx-pipeline-assignment/uploads.json"
    catalog_path="catalog/"
    if len(sys.argv) >= 4:
        uploads_json = sys.argv[1]
        root_path = sys.argv[2]
        catalog_path = sys.argv[3]
    ingestion = Ingest(catalog_path)
    with open(uploads_json, 'r', encoding='utf-8') as file:
        uploads = json.load(file)
    for upload in uploads:
        metadata = Metadata(
            product_type=upload["product_type"],
            classification=upload["classification"],
            contract_id=upload["contract_id"],
            datetime=upload.get("datetime")
        )
        try:
            print(upload["file"] + " " + ingestion.ingest(root_path+upload["file"], metadata))
        except Exception as e:
            print(f"Error ingesting {upload['file']}: {e}")
