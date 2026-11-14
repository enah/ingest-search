from datetime import datetime, timezone
import pystac
from rtree import index

class Search:
    def __init__(self, catalog_path):
        # Configure R-tree properties for 3 dimensions (X, Y, Time)
        p = index.Property()
        p.dimension = 3
        
        # Initialize the R-tree index (storing item objects directly)
        self.idx = index.Index(properties=p, interleaved=True)
        self.item_lookup = {}  # Fallback dictionary to map internal integer IDs if needed
        
        self._build_index(catalog)

    def _datetime_to_timestamp(self, dt: datetime) -> float:
        """Converts a datetime object to UTC epoch seconds for numeric R-tree indexing."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    def _build_index(self, catalog: pystac.Catalog):
        counter = 0
        for item in catalog.get_all_items():
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
    
    def search(self, query_bbox: tuple, query_start: datetime, query_end: datetime):
        """
        Performs a joint spatio-temporal range search.
        query_bbox: (minx, miny, maxx, maxy)
        query_start, query_end: datetime objects defining the time window
        """
        minx, miny, maxx, maxy = query_bbox
        t_start = self._datetime_to_timestamp(query_start)
        t_end = self._datetime_to_timestamp(query_end)

        # Construct the 3D search query box
        search_box = (minx, miny, t_start, maxx, maxy, t_end)

        # Query the R-tree for intersecting 3D bounds (objects=True returns the stored item objects)
        results = [item for item in self.idx.intersection(search_box, objects=True)]
        return results

if __name__ == "__main__":

