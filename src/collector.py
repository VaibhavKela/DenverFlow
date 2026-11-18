
import requests
from google.transit import gtfs_realtime_pb2

TRIP_UPDATES_URL = (
    "https://open-data.rtd-denver.com/files/"
    "gtfs-rt/rtd/TripUpdate.pb"
)


def fetch_trip_updates():
    """Download and decode RTD's trip updates feed."""

    response = requests.get(
        TRIP_UPDATES_URL,
        timeout=30
    )

    response.raise_for_status()

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)

    return feed


if __name__ == "__main__":
    feed = fetch_trip_updates()

    print(f"Feed entities: {len(feed.entity)}")
    print(f"Feed timestamp: {feed.header.timestamp}")
