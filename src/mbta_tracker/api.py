import os
import time
from copy import deepcopy

import dotenv
import numpy as np
import pandas as pd
import requests
from loguru import logger

dotenv.load_dotenv()

API_KEY = os.getenv("MBTA_API_KEY")
BASE_URL = "https://api-v3.mbta.com"
REQUEST_TIMEOUT = 10  # seconds
CACHE_TTL = 3600  # seconds; how long Stops/Routes metadata is considered fresh

_session = requests.Session()
if API_KEY:
    _session.headers.update({"x-api-key": API_KEY})
else:
    logger.warning("No API key set. Requests will be strictly rate-limited.")


def request(path, params=None):
    """GET a path (relative or absolute) against the MBTA API using the shared session."""
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    try:
        resp = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        logger.error(f"Request to {url} failed: {e}")
        raise


def _normalize_and_drop(df, cols):
    if not isinstance(cols, list):
        cols = [cols]
    if not cols:
        return df
    normalized = [df.drop(columns=cols)]
    for c in cols:
        normalized.append(pd.json_normalize(df[c]))
    return pd.concat(normalized, axis=1)


def _time_to_now(schedule):
    """
    Compute minutes-from-now for each schedule row.

    Not every schedule entry has an arrival_time (e.g. the first stop on a
    trip may only have a departure_time), so we fall back to
    departure_time when arrival_time is missing. Rows where neither is
    parseable end up as NaN in 'wait' rather than raising, and are stored
    as a nullable float/Int64 column so downstream numeric comparisons
    (e.g. `waits < next_min`) keep working.
    """
    try:
        arrival = pd.to_datetime(
            schedule.get("arrival_time"), utc=True, errors="coerce"
        )
        departure = pd.to_datetime(
            schedule.get("departure_time"), utc=True, errors="coerce"
        )
        times = arrival.fillna(departure)
        now = pd.Timestamp.now(tz="UTC")
        minutes = (times - now).dt.total_seconds() / 60
        schedule["wait"] = round(minutes)
    except Exception as e:
        logger.warning(f"Failed to compute wait times: {e}")
        schedule["wait"] = np.nan
    return schedule


def schedules_for_stop_ids(stop_ids, current_time=None):
    """
    Fetch schedules for one or many stop ids in a single API call.

    stop_ids: a single id (str) or a list/iterable of ids.
    Returns a DataFrame with a 'stop_id' column (extracted from the
    relationships) plus a 'wait' column (minutes from now).
    """
    if isinstance(stop_ids, (str, int)):
        stop_ids = [stop_ids]
    stop_ids = [str(s) for s in stop_ids]

    if current_time is None:
        h, m = time.strftime("%H"), time.strftime("%M")
    else:
        h, m = current_time.split(":")

    params = {
        "filter[min_time]": f"{h}:{m}",
        "filter[stop]": ",".join(stop_ids),
    }
    try:
        resp = request("/schedules", params=params)
        data = resp.json().get("data", [])
    except (requests.RequestException, ValueError) as e:
        logger.error(f"Failed to fetch schedules for stops {stop_ids}: {e}")
        return pd.DataFrame(columns=["arrival_time", "wait", "stop_id"])

    if not data:
        return pd.DataFrame(columns=["arrival_time", "wait", "stop_id"])

    schedule = pd.DataFrame.from_dict(data)
    schedule = _normalize_and_drop(schedule, ["attributes"])
    schedule["stop_id"] = schedule["relationships"].apply(
        lambda r: r.get("stop", {}).get("data", {}).get("id")
    )
    schedule = _time_to_now(schedule)
    return schedule


def routes_for_stop_ids(stop_ids):
    """Fetch routes serving one or many stop ids in a single API call."""
    if isinstance(stop_ids, (str, int)):
        stop_ids = [stop_ids]
    stop_ids = [str(s) for s in stop_ids]

    params = {"filter[stop]": ",".join(stop_ids)}
    try:
        resp = request("/routes", params=params)
        data = resp.json().get("data", [])
    except (requests.RequestException, ValueError) as e:
        logger.error(f"Failed to fetch routes for stops {stop_ids}: {e}")
        return pd.DataFrame()

    return pd.DataFrame.from_dict(data)


class Stops:
    def __init__(self, force_refresh=True):
        self._last_refresh = 0
        if force_refresh:
            self._refresh()

    def _refresh(self):
        try:
            stops = request("/stops")
            stop_info = pd.DataFrame.from_dict(stops.json()["data"])
            stop_info = _normalize_and_drop(
                stop_info, ["attributes", "links", "relationships"]
            )
            stop_info.set_index("id", inplace=True)
            stop_info = stop_info.fillna(-1)
            stop_info.vehicle_type = stop_info.vehicle_type.astype(int)
            self.info = stop_info
            self._last_refresh = time.time()
        except (requests.RequestException, ValueError, KeyError) as e:
            logger.error(f"Failed to refresh stops: {e}")
            if not hasattr(self, "info"):
                self.info = pd.DataFrame()

    def _ensure_fresh(self):
        if time.time() - self._last_refresh > CACHE_TTL:
            self._refresh()

    def lookup(self, name="", vehicle="rapid", desc="", full=False):
        self._ensure_fresh()
        df = self.info[self.info.name.str.contains(name)]
        df = self._filter_vehicle(df, vehicle)
        try:
            df = df[df.description.str.contains(desc, na=False)]
        except AttributeError:
            if desc != "":
                logger.warning(f"No descriptions matching {desc}")
        return df if full else _clean_view(df)

    def localize(self, coords, vehicle="rapid", dist=1, full=False):
        self._ensure_fresh()
        df = deepcopy(self.info)
        df = self._filter_vehicle(df, vehicle)
        # Latitude: 1 degree = 68.72219 mi
        # Longitude: 1 degree = 69.18583 mi * cos(Latitude deg)
        lat, lon = coords
        distlat = (df.latitude.to_numpy() - lat) * 68.72219
        distlon = (df.longitude.to_numpy() - lon) * (69.18583 * np.cos(np.radians(lat)))
        df["dist"] = np.sqrt(distlat**2 + distlon**2)
        if full:
            return df[df.dist < dist]
        else:
            return _clean_view(df[df.dist < dist])

    def _filter_vehicle(self, df, vehicle):
        if vehicle == "rapid":
            df = df[df.vehicle_type.between(0, 1)]
        elif vehicle == "commuter":
            df = df[df.vehicle_type == 2]
        elif vehicle == "bus":
            df = df[df.vehicle_type == 3]
        return df


class Routes:
    def __init__(self, force_refresh=True):
        self._last_refresh = 0
        if force_refresh:
            self._refresh()

    def _refresh(self):
        try:
            routes = request("/routes")
            route_info = pd.DataFrame.from_dict(routes.json()["data"])
            route_info = _normalize_and_drop(
                route_info, ["attributes", "links", "relationships"]
            )
            route_info.set_index("id", inplace=True)
            route_info.fillna(-1, inplace=True)
            route_info.vehicle_type = route_info.vehicle_type.astype(int)
            self.info = route_info
            self._last_refresh = time.time()
        except (requests.RequestException, ValueError, KeyError) as e:
            logger.error(f"Failed to refresh routes: {e}")
            if not hasattr(self, "info"):
                self.info = pd.DataFrame()


def _clean_view(df):
    if "dist" in df.columns:
        return df[["name", "description", "dist"]]
    else:
        return df[["name", "description"]]


def schedule_for_stops(stops_df, next_min=30):
    """
    Given a DataFrame of stops (as returned by Stops.localize(full=True)),
    attach route, schedule, direction and wait-time info.

    This batches the route and schedule lookups into a single API call
    each, rather than one call per stop.
    """
    stop_ids = list(stops_df.index)

    routes_df = routes_for_stop_ids(stop_ids)
    schedules_df = schedules_for_stop_ids(stop_ids)

    # Group schedules by stop so we can pull each stop's waits/direction.
    if "stop_id" in schedules_df.columns:
        sched_by_stop = {k: v for k, v in schedules_df.groupby("stop_id")}
    else:
        sched_by_stop = {}

    route_list, waits_list, direction_list, toward_list = [], [], [], []

    for stop_id in stop_ids:
        stop_schedules = sched_by_stop.get(stop_id, pd.DataFrame())

        if routes_df.empty:
            route_list.append(None)
            direction_list.append(None)
            toward_list.append(None)
            waits_list.append(np.array([]))
            continue

        route_row = routes_df.iloc[0]
        route_id = route_row.get("id")

        if not stop_schedules.empty and "wait" in stop_schedules.columns:
            waits = (
                pd.to_numeric(stop_schedules["wait"], errors="coerce")
                .astype(int)
                .dropna()
                .to_list()
            )
            waits = sorted(waits)
            waits = [w for w in waits if w < next_min]
            waits = ["ARR" if w < 1 else w for w in waits]
        else:
            waits = []

        direction_id = 0
        if not stop_schedules.empty and "direction_id" in stop_schedules.columns:
            direction_id = stop_schedules["direction_id"].iloc[0]

        attrs = (
            route_row.get("attributes", {})
            if isinstance(route_row.get("attributes"), dict)
            else {}
        )
        direction_names = attrs.get("direction_names", [None, None])
        direction_destinations = attrs.get("direction_destinations", [None, None])

        route_list.append(route_id)
        waits_list.append(waits)
        try:
            direction_list.append(direction_names[direction_id])
            toward_list.append(direction_destinations[direction_id])
        except (IndexError, TypeError):
            direction_list.append(None)
            toward_list.append(None)

    stops_df = stops_df.copy()
    stops_df["route"] = route_list
    stops_df["waits"] = waits_list
    stops_df["direction"] = direction_list
    stops_df["toward"] = toward_list

    return stops_df[
        ["name", "route", "direction", "toward", "dist", "waits"]
    ].sort_values("dist")
