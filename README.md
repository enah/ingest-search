# ingest-search
Ingest and search stac items

Ingest items: usage
python3 ingest.py upload_json_file_path assets_files_dir_path catalog_dir_path

Duplicates are identified when two items have identical geometry. This is is detected by generating uuid that is serialized from the geometry.
