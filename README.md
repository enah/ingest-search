# ingest-search
Ingest and search stac items

Ingest items: usage
python3 ingest.py upload_json_file_path assets_files_dir_path catalog_dir_path

Search items: usage example
python search.py --catalog catalog_file_path --bbox -122.5 37.7 -122.3 37.9 --start 2026-06-01T00:00:00Z --end 2026-06-30T23:59:59Z --product-type flood-extent

Duplicates are identified when two items have identical geometry. This is is detected by generating uuid that is serialized from the geometry.
