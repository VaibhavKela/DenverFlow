import csv
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


def match_trip_updates(realtime_feed, static_feed):
    """Match RTD real-time stop updates with GTFS schedules."""

    # Build a lookup of scheduled arrival times.
    schedule_lookup = {}

    with static_feed.open("stop_times.txt") as file:
        reader = csv.DictReader(
            io.TextIOWrapper(file, encoding="utf-8-sig")
        )

        for row in reader:
            key = (
                row["trip_id"],
                row["stop_sequence"],
                row["stop_id"]
            )

            schedule_lookup[key] = row["arrival_time"]

    # Match real-time updates against the schedule.
    total_updates = 0
    matched_updates = 0
    examples = []

    for entity in realtime_feed.entity:
        if not entity.HasField("trip_update"):
            continue

        trip_update = entity.trip_update
        trip_id = trip_update.trip.trip_id

        for stop_update in trip_update.stop_time_update:
            total_updates += 1

            key = (
                trip_id,
                str(stop_update.stop_sequence),
                stop_update.stop_id
            )

            scheduled_time = schedule_lookup.get(key)

            if scheduled_time is None:
                continue

            matched_updates += 1

            if len(examples) < 5:
                examples.append({
                    "trip_id": trip_id,
                    "stop_id": stop_update.stop_id,
                    "scheduled_arrival": scheduled_time
                })

    return total_updates, matched_updates, examples



if __name__ == "__main__":
    realtime_feed = fetch_trip_updates()
    static_feed = fetch_static_gtfs()

    total, matched, examples = match_trip_updates(
        realtime_feed,
        static_feed
    )

    print(f"Total real-time stop updates: {total}")
    print(f"Matched schedule records: {matched}")

    if total > 0:
        print(f"Match rate: {matched / total * 100:.2f}%")

    print("Sample matches:")
    for example in examples:
        print(example)

