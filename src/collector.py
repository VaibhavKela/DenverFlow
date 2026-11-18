import os
from supabase import create_client
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
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
    valid_delays = 0
    examples = []
    records = []

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

            # Some RTD stop updates have no arrival prediction.
            if not stop_update.HasField("arrival"):
                continue

            if not stop_update.arrival.HasField("time"):
                continue

            predicted_timestamp = stop_update.arrival.time

            service_date = trip_update.trip.start_date

            delay_minutes = calculate_predicted_delay(
                service_date,
                scheduled_time,
                predicted_timestamp
            )

            if delay_minutes is None:
                continue
            valid_delays += 1
            
            # Convert the scheduled arrival into a full timestamp.
            scheduled_arrival = get_scheduled_arrival(
                service_date,
                scheduled_time
            )

            if scheduled_arrival is None:
                continue

            # Convert RTD's Unix prediction into an ISO timestamp.
            predicted_arrival = datetime.fromtimestamp(
                predicted_timestamp,
                tz=timezone.utc
            ).isoformat()

            # Prepare only 10 observations for our database test.
            if len(records) < 10:
                records.append({
                    "feed_timestamp": datetime.fromtimestamp(
                        trip_update.timestamp,
                        tz=timezone.utc
                    ).isoformat() if trip_update.timestamp else None,
                    "trip_id": trip_id,
                    "route_id": trip_update.trip.route_id,
                    "service_date": service_date,
                    "stop_id": stop_update.stop_id,
                    "stop_sequence": stop_update.stop_sequence,
                    "scheduled_arrival": scheduled_arrival,
                    "predicted_arrival": predicted_arrival,
                    "predicted_delay_minutes": delay_minutes,
                    "vehicle_id": trip_update.vehicle.id
                })


            if len(examples) < 5:
                examples.append({
                    "trip_id": trip_id,
                    "stop_id": stop_update.stop_id,
                    "scheduled_arrival": scheduled_time,
                    "predicted_delay_minutes": delay_minutes
                })


    return total_updates, matched_updates, valid_delays, examples, records


DENVER_TZ = ZoneInfo("America/Denver")


def calculate_predicted_delay(
    service_date,
    scheduled_time,
    predicted_timestamp
):
    """Calculate RTD's predicted delay in minutes."""

    if not service_date or not scheduled_time or not predicted_timestamp:
        return None

    # GTFS times may exceed 24 hours.
    hours, minutes, seconds = map(
        int, scheduled_time.split(":")
    )

    service_day = datetime.strptime(
        service_date, "%Y%m%d"
    ).date()

    # GTFS schedules use service-day time, not Unix time.
    scheduled_local = (
        datetime.combine(
            service_day,
            datetime.min.time()
        )
        + timedelta(
            hours=hours,
            minutes=minutes,
            seconds=seconds
        )
    )

    # Convert RTD's Unix timestamp into Denver time.
    predicted_local = datetime.fromtimestamp(
        predicted_timestamp,
        tz=timezone.utc
    ).astimezone(DENVER_TZ)

    # Resolve the scheduled local time to a UTC instant.
    # Ambiguous/nonexistent DST times need separate validation.
    scheduled_local = scheduled_local.replace(
        tzinfo=DENVER_TZ
    )

    if scheduled_local.utcoffset() != (
        scheduled_local.replace(fold=1).utcoffset()
    ):
        return None

    # Reject nonexistent local times during the spring DST change.
    roundtrip = (
        scheduled_local.astimezone(timezone.utc)
        .astimezone(DENVER_TZ)
    )

    if roundtrip.replace(tzinfo=None) != scheduled_local.replace(
        tzinfo=None
    ):
        return None

    delay = (
        predicted_local.astimezone(timezone.utc)
        - scheduled_local.astimezone(timezone.utc)
    ).total_seconds() / 60

    return round(delay, 2)


def get_scheduled_arrival(service_date, scheduled_time):
    """Convert a GTFS service date and time into an ISO timestamp."""

    if not service_date or not scheduled_time:
        return None

    hours, minutes, seconds = map(
        int, scheduled_time.split(":")
    )

    service_day = datetime.strptime(
        service_date, "%Y%m%d"
    )

    scheduled_local = (
        service_day
        + timedelta(
            hours=hours,
            minutes=minutes,
            seconds=seconds
        )
    ).replace(tzinfo=DENVER_TZ)

    # Skip ambiguous or nonexistent local times during DST changes.
    if scheduled_local.utcoffset() != (
        scheduled_local.replace(fold=1).utcoffset()
    ):
        return None

    roundtrip = (
        scheduled_local.astimezone(timezone.utc)
        .astimezone(DENVER_TZ)
    )

    if roundtrip.replace(tzinfo=None) != scheduled_local.replace(
        tzinfo=None
    ):
        return None

    return scheduled_local.isoformat()


def connect_supabase():
    """Create a secure connection to our Supabase project."""

    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_SECRET_KEY"]

    client = create_client(
        supabase_url,
        supabase_key
    )

    return client



if __name__ == "__main__":
    realtime_feed = fetch_trip_updates()
    static_feed = fetch_static_gtfs()

    total, matched, valid, examples, records = match_trip_updates(
        realtime_feed,
        static_feed
    )

    print(f"Total real-time stop updates: {total}")
    print(f"Matched schedule records: {matched}")
    print(f"Valid delay calculations: {valid}")

    if total > 0:
        print(f"Schedule match rate: {matched / total * 100:.2f}%")
        print(f"Valid delay rate: {valid / total * 100:.2f}%")

    print(f"Database records prepared: {len(records)}")
    
    # Insert only our 10 prepared test observations.
    if records:
        supabase = connect_supabase()

        response = (
            supabase.table("rtd_trip_updates")
            .upsert(
                records,
                on_conflict="feed_timestamp,trip_id,stop_id,stop_sequence",
                ignore_duplicates=True
            )
            .execute()
        )

        print(f"Records inserted into Supabase: {len(response.data)}")


    print("Sample matches:")
    for example in examples:
        print(example)
