# ingest-search
Ingest and search stac items

## Ingest items: usage
python3 ingest.py upload_json_file_path assets_files_dir_path catalog_dir_path

## Search items: usage example
python search.py --catalog catalog_file_path --bbox -122.5 37.7 -122.3 37.9 --start 2026-06-01T00:00:00Z --end 2026-06-30T23:59:59Z --product-type flood-extent

Note: setting start and end time to the same time, or minx and maxx to the same degree, will not work as it will be 0 dimensional and not intersect anything. Maybe something to fix?

## Tests:
pytest test_ingest.py

pytest test_search.py

## Design decisions

If metadata disagrees with the file, the file is rejected. This is to make sure that only correct and intentional data gets uploaded in the case of user error.

Duplicates are identified when two items have identical geometry. This is is detected by generating uuid deterministically from serialized geometry.

## Things to change when running in production with many teams and larger files
If files are larger, they may have to be processed in chunks. Support asynchronous upload with event-driven architecture. The rtree for search is built in memeory, so a different technology will need to be used (pgSTAC).

## Time taken
5 hours
