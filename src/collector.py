
import io
import zipfile
import requests
from google.transit import gtfs_realtime_pb2

TRIP_UPDATES_URL = (
    "https://open-data.rtd-denver.com/files/"
    "gtfs-rt/rtd/TripUpdate.pb"
)

STATIC_GTFS_URL = (
    "https://www.rtd-denver.com/files/gtfs/"
    "google_transit.zip"
)


def fetch_trip_updates():
    """Download and decode RTD real-time trip updates."""
    response = requests.get(TRIP_UPDATES_URL, timeout=30)
    response.raise_for_status()

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)

    return feed


def fetch_static_gtfs():
    """Download RTD's static GTFS schedule ZIP."""
    response = requests.get(STATIC_GTFS_URL, timeout=60)
    response.raise_for_status()

    zip_file = zipfile.ZipFile(io.BytesIO(response.content))
    return zip_file


if __name__ == "__main__":
    realtime_feed = fetch_trip_updates()
    static_feed = fetch_static_gtfs()

    print(f"Real-time entities: {len(realtime_feed.entity)}")
    print(f"Static GTFS files: {static_feed.namelist()}")
