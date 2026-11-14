from pydantic import BaseModel
from typing import Optional
from pathlib import Path
import re
from datetime import datetime, timezone

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
        pass
        
    def validate_geojson(self, file_path):
        pass

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
        
        elif metadata.product_type == "flood_extent":
            reject_reason = self.validate_geojson(file_path)
            if reject_reason:
                return reject_reason
        
        elif metadata.product_type == "change_detection":
            reject_reason = self.validate_geojson(file_path)
            if reject_reason:
                return reject_reason
        
        else:
            return "Rejected: unknown product_type"
            
        # open catalog if exists, store in catalog
        
        # copy file to storage path
        self.copy_to_storage(file_path, storage_path)
        
        return "Success"

    def copy_to_storage(self, file_path, storage_path):
        pass # implement later

if __name__ == "__main__":
