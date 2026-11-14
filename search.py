from datetime import datetime, timezone
import pystac
from rtree import index
import argparse

class Search:
    def __init__(self, catalog_path):
        # Configure R-tree properties for 3 dimensions (X, Y, Time)
        p = index.Property()
        p.dimension = 3
        
        # Initialize the R-tree index (storing item objects directly)
        self.idx = index.Index(properties=p, interleaved=True)
        self.item_lookup = {}  # Fallback dictionary to map internal integer IDs if needed
        
        catalog = pystac.Catalog.from_file(catalog_path)
        self._build_index(catalog)

    def _datetime_to_timestamp(self, dt: datetime) -> float:
        """Converts a datetime object to UTC epoch seconds for numeric R-tree indexing."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    def _build_index(self, catalog: pystac.Catalog):
        counter = 0
        for item in catalog.get_items(recursive=True):
            # 1. Extract Bounding Box [minx, miny, maxx, maxy]
            bbox = item.bbox
            if not bbox or len(bbox) != 4:
                continue  # Skip items without valid spatial extents
            minx, miny, maxx, maxy = bbox

            # 2. Extract Temporal Extents (Point in time vs Interval)
            if item.datetime:
                t_start = self._datetime_to_timestamp(item.datetime)
                t_end = t_start
            elif item.common_metadata.start_datetime and item.common_metadata.end_datetime:
                t_start = self._datetime_to_timestamp(item.common_metadata.start_datetime)
                t_end = self._datetime_to_timestamp(item.common_metadata.end_datetime)
            else:
                continue  # Skip items without temporal data

            # 3. Define 3D bounding box: (minx, miny, tmin, maxx, maxy, tmax)
            spatial_temporal_box = (minx, miny, t_start, maxx, maxy, t_end)

            # Insert into R-tree (passing the PySTAC item object directly)
            self.idx.insert(counter, spatial_temporal_box, obj=item)
            counter += 1

        print(f"Successfully indexed {counter} items into 3D Spatiotemporal R-tree.")
    
    def search_rtree(self, query_bbox: tuple, query_start: datetime = None, query_end: datetime = None):
        """
        Performs a joint spatio-temporal range search.
        query_bbox: (minx, miny, maxx, maxy)
        query_start, query_end: datetime objects defining the time window
        """
        minx, miny, maxx, maxy = query_bbox
        t_start = self._datetime_to_timestamp(query_start) if query_start else float('-inf')
        t_end = self._datetime_to_timestamp(query_end) if query_end else float('inf')

        # Construct the 3D search query box
        search_box = (minx, miny, t_start, maxx, maxy, t_end)

        # Query the R-tree for intersecting 3D bounds (objects=True returns the stored item objects)
        results = [item for item in self.idx.intersection(search_box, objects=True)]
        
        # Return the stac item
        results = [item.object for item in results]
        
        return results
        
    def search(self, query_bbox: tuple = None, query_start: datetime = None, query_end: datetime = None, product_type: str = None):
        if not query_bbox:
            query_bbox = (float('-inf'), float('-inf'), float('inf'), float('inf'))
        results = self.search_rtree(query_bbox, query_start, query_end)
        if product_type:
            results = [item for item in results if item.properties.get("product_type") == product_type]
        return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query a STAC catalog using spatial, temporal, and attribute filters.")
    
    parser.add_argument("--catalog", help="Path or URL to the STAC catalog JSON file.")
    parser.add_argument("--bbox", nargs=4, type=float, metavar=('MINX', 'MINY', 'MAXX', 'MAXY'), help="Bounding box coordinates.")
    parser.add_argument("--start", type=str, help="Query start time in ISO format (e.g., 2026-01-01T00:00:00Z).")
    parser.add_argument("--end", type=str, help="Query end time in ISO format (e.g., 2026-12-31T23:59:59Z).")
    parser.add_argument("--product-type", type=str, help="Filter by product type string.")

    args = parser.parse_args()
    
    catalog_path="catalog/catalog.json"
    if args.catalog:
        catalog_path = args.catalog
    search_engine = Search(catalog_path)
    
    # Parse ISO string dates into timezone-aware datetime objects if provided
    query_start = datetime.fromisoformat(args.start.replace('Z', '+00:00')) if args.start else None
    query_end = datetime.fromisoformat(args.end.replace('Z', '+00:00')) if args.end else None
    
    results = search_engine.search(
        query_bbox=tuple(args.bbox) if args.bbox else None,
        query_start=query_start,
        query_end=query_end,
        product_type=args.product_type
    )

    item_ids = [item.id for item in results]

    print(item_ids)
