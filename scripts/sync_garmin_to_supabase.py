#!/usr/bin/env python3
"""
sync_garmin_to_supabase.py
---------------------------
Syncs Garmin Connect data directly to Supabase for the Fuel & Run app.

Fetches:
  - Daily wellness: steps, resting kcal, active kcal, projected total kcal, resting HR
  - Activities: type, distance, duration, calories, avg/max HR, pace, splits (HR + pace per km)

Usage:
  python sync_garmin_to_supabase.py [days_back]
  python sync_garmin_to_supabase.py 14    # sync last 14 days (default)

Environment variables (copy .env.example to .env):
  GARMIN_EMAIL          Your Garmin Connect email
  GARMIN_PASSWORD       Your Garmin Connect password
  SUPABASE_URL          https://xxxx.supabase.co
  SUPABASE_SERVICE_KEY  sb_secret_... (service role key from Supabase -> Settings -> API)

Install dependencies:
  pip install garminconnect supabase python-dotenv
"""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Load .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / '.env')
except ImportError:
    pass

from garminconnect import Garmin, GarminConnectAuthenticationError
from supabase import create_client

# ── Config ────────────────────────────────────────────────────────────────────
GARMIN_EMAIL         = os.environ.get('GARMIN_EMAIL', '')
GARMIN_PASSWORD      = os.environ.get('GARMIN_PASSWORD', '')
SUPABASE_URL         = os.environ.get('SUPABASE_URL', '')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')
# GARMIN_PROFILE controls which Supabase tables to write to.
# 'michal'  → garmin_daily + garmin_activities  (default)
# 'marysia' → garmin_daily_marysia + garmin_activities_marysia
GARMIN_PROFILE       = os.environ.get('GARMIN_PROFILE', 'michal').lower()

if GARMIN_PROFILE == 'marysia':
    DAILY_TABLE      = 'garmin_daily_marysia'
    ACTIVITIES_TABLE = 'garmin_activities_marysia'
    TOKEN_FILE       = Path.home() / '.garminconnect_token_marysia.json'
else:
    DAILY_TABLE      = 'garmin_daily'
    ACTIVITIES_TABLE = 'garmin_activities'
    TOKEN_FILE       = Path.home() / '.garminconnect_token.json'

# Garmin sport type → Fuel&Run session type
SPORT_MAP = {
    'running': 'run', 'trail_running': 'run', 'indoor_running': 'run',
    'treadmill_running': 'run', 'virtual_run': 'run',
    'walking': 'walk', 'hiking': 'walk',
    'cycling': 'bike', 'road_biking': 'bike', 'mountain_biking': 'bike',
    'indoor_cycling': 'bike', 'virtual_ride': 'bike',
    'swimming': 'swim', 'lap_swimming': 'swim', 'open_water_swimming': 'swim',
    'strength_training': 'strength', 'fitness_equipment': 'strength',
    'weight_training': 'strength', 'cardio': 'strength',
    'yoga': 'breathwork', 'pilates': 'breathwork', 'breathwork': 'breathwork',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def format_pace(speed_ms):
    """Convert m/s to MM:SS/km string, or None if invalid."""
    if not speed_ms or speed_ms <= 0:
        return None
    secs_per_km = 1000 / speed_ms
    m, s = divmod(int(secs_per_km), 60)
    return f"{m}:{s:02d}"


def _get(obj, *keys, default=None):
    """Safely get a value from a nested dict trying multiple keys."""
    for k in keys:
        v = obj.get(k) if isinstance(obj, dict) else None
        if v is not None:
            return v
    return default


# ── Garmin auth ───────────────────────────────────────────────────────────────

def garmin_login() -> Garmin:
    """Login to Garmin Connect.

    Priority:
    1. If a saved token file exists, load it (no network login needed — avoids 429/MFA).
    2. Otherwise fall back to credential login (works for accounts without MFA).
       Accounts with MFA must pre-generate a token locally and store it as a GitHub secret.
    """
    if TOKEN_FILE.exists():
        try:
            api = Garmin()
            api.client.load(str(TOKEN_FILE))
            print(f"Reusing saved Garmin session from {TOKEN_FILE}")
            try:
                api.client.dump(str(TOKEN_FILE))
            except Exception:
                pass
            return api
        except Exception:
            print("Saved token invalid or expired, falling back to credential login...")

    # Credential fallback (no MFA accounts only)
    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        print(f"ERROR: No token file at {TOKEN_FILE} and no credentials provided.")
        print("For MFA accounts: run scripts/garmin_save_token.py locally and store the result as a GitHub secret.")
        sys.exit(1)

    print(f"Logging in to Garmin Connect as {GARMIN_EMAIL} ...")
    api = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    try:
        api.login()
    except GarminConnectAuthenticationError as e:
        print(f"Login failed: {e}")
        sys.exit(1)
    except Exception as e:
        msg = str(e)
        if '429' in msg or 'rate' in msg.lower():
            print("WARNING: Garmin rate-limited (429) — skipping this run. Will retry next cron cycle.")
            sys.exit(0)
        raise

    try:
        api.client.dump(str(TOKEN_FILE))
    except Exception:
        pass

    print("Logged in to Garmin Connect")
    return api


# ── Garmin API fetchers ───────────────────────────────────────────────────────

def fetch_daily_summary(api: Garmin, date_str: str) -> dict:
    try:
        return api.get_stats(date_str) or {}
    except Exception as e:
        print(f"  WARNING: Daily summary failed for {date_str}: {e}")
        return {}


def fetch_activities(api: Garmin, start_date: str, end_date: str) -> list:
    try:
        return api.get_activities_by_date(start_date, end_date) or []
    except Exception as e:
        print(f"  WARNING: Activity list failed: {e}")
        return []


def fetch_laps(api: Garmin, activity_id: int) -> list:
    try:
        result = api.get_activity_splits(activity_id)
        if isinstance(result, dict):
            return result.get('lapDTOs') or result.get('laps') or []
        return result or []
    except Exception as e:
        print(f"  WARNING: Laps failed for activity {activity_id}: {e}")
        return []


def extract_laps(raw_laps: list) -> list:
    """Parse garminconnect lap data into our app format."""
    laps = []
    for i, lap in enumerate(raw_laps):
        dist_m    = _get(lap, 'distanceInMeters', 'distance', default=0) or 0
        elapsed   = _get(lap, 'elapsedDuration', 'duration', default=0) or 0
        avg_speed = _get(lap, 'averageSpeed', 'speedInMetersPerSecond', default=None)
        avg_hr    = _get(lap, 'averageHR', 'averageHeartRate', default=None)
        max_hr    = _get(lap, 'maxHR', 'maxHeartRate', default=None)
        cadence   = _get(lap, 'averageRunCadence', 'averageCadence', default=None)
        elevation = _get(lap, 'elevationGain', 'total_elevation_gain', default=0) or 0
        laps.append({
            'num':        i + 1,
            'dist':       round(float(dist_m) / 1000, 3),
            'time':       round(float(elapsed)),
            'avgHr':      round(float(avg_hr)) if avg_hr else None,
            'maxHr':      round(float(max_hr)) if max_hr else None,
            'pace':       format_pace(avg_speed),
            'avgCadence': round(float(cadence) * 2) if cadence else None,
            'elevation':  round(float(elevation), 1),
        })
    return laps


# ── Supabase sync ─────────────────────────────────────────────────────────────

def sync_daily(api: Garmin, sb, days_back: int):
    today = date.today()
    print(f"\nSyncing {days_back} days of wellness data → {DAILY_TABLE}...")

    for i in range(days_back):
        d = today - timedelta(days=i)
        date_str = d.strftime('%Y-%m-%d')
        s = fetch_daily_summary(api, date_str)

        steps          = int(s.get('totalSteps') or 0)
        resting_kcal   = round(float(s.get('bmrKilocalories') or 0))
        active_kcal    = round(float(s.get('activeKilocalories') or s.get('burnedKilocalories') or 0))
        projected_kcal = round(float(s.get('totalKilocalories') or 0))
        resting_hr     = s.get('restingHeartRate') or None

        # Skip the upsert when Garmin returned empty/zero data (e.g. token expired or
        # day not yet synced to Garmin servers) — avoids overwriting good existing data with zeros.
        if not steps and not projected_kcal and not resting_kcal and not resting_hr:
            print(f"  [--] {date_str}: Garmin returned no data — skipping upsert")
            continue

        sb.table(DAILY_TABLE).upsert(
            {
                'date': date_str,
                'steps': steps,
                'resting_kcal': resting_kcal,
                'active_kcal': active_kcal,
                'projected_kcal': projected_kcal,
                'resting_hr': resting_hr,
            },
            on_conflict='date',
        ).execute()

        tag = 'OK' if steps or projected_kcal else '--'
        print(
            f"  [{tag}] {date_str}: {steps:,} steps | "
            f"{resting_kcal} rest + {active_kcal} active = {projected_kcal} kcal | "
            f"HR {resting_hr}"
        )


def sync_activities(api: Garmin, sb, days_back: int):
    today = date.today()
    start_str = (today - timedelta(days=days_back)).strftime('%Y-%m-%d')
    end_str   = today.strftime('%Y-%m-%d')

    print(f"\nSyncing activities {start_str} to {end_str} → {ACTIVITIES_TABLE}...")
    activities = fetch_activities(api, start_str, end_str)
    print(f"  Found {len(activities)} activities")

    for act in activities:
        activity_id = act.get('activityId')
        if not activity_id:
            continue

        start_time = act.get('startTimeLocal', '') or ''
        act_date   = start_time[:10] if start_time else ''

        type_key    = (act.get('activityType') or {}).get('typeKey', 'other')
        sport       = SPORT_MAP.get(type_key, 'cross')
        avg_hr      = act.get('averageHR') or None
        max_hr      = act.get('maxHR') or None
        avg_speed   = act.get('averageSpeed') or None
        dist_m      = float(act.get('distance', 0) or 0)
        avg_cadence = float(act.get('averageRunCadence') or
                            act.get('averageBikingCadenceInRevPerMinute') or 0)

        laps = []
        if sport == 'run' and dist_m >= 1000:
            raw_laps = fetch_laps(api, int(activity_id))
            laps = extract_laps(raw_laps)

        sb.table(ACTIVITIES_TABLE).upsert(
            {
                'activity_id': int(activity_id),
                'date': act_date,
                'type': sport,
                'name': (act.get('activityName') or '').strip(),
                'distance_m': dist_m,
                'duration_s': float(act.get('duration', 0) or 0),
                'calories': int(act.get('calories', 0) or 0),
                'avg_hr': float(avg_hr) if avg_hr else None,
                'max_hr': float(max_hr) if max_hr else None,
                'avg_speed_ms': float(avg_speed) if avg_speed else None,
                'total_ascent': float(act.get('elevationGain', 0) or 0),
                'total_descent': float(act.get('elevationLoss', 0) or 0),
                'avg_cadence': round(avg_cadence * 2) if avg_cadence else None,
                'laps': json.dumps(laps),
                'start_time_local': start_time,
            },
            on_conflict='activity_id',
        ).execute()

        name = act.get('activityName') or type_key
        print(f"  OK  {name} on {act_date} ({sport}, {dist_m/1000:.1f} km, {len(laps)} splits)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 14

    missing = [name for var, name in [
        (SUPABASE_URL,         'SUPABASE_URL'),
        (SUPABASE_SERVICE_KEY, 'SUPABASE_SERVICE_KEY'),
    ] if not var]

    if missing:
        print(f"Missing environment variables: {', '.join(missing)}")
        print("   Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    api = garmin_login()
    sb  = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    print(f"Profile: {GARMIN_PROFILE} → tables: {DAILY_TABLE}, {ACTIVITIES_TABLE}")

    sync_daily(api, sb, days_back)
    sync_activities(api, sb, days_back)

    print("\nSync complete!")


if __name__ == '__main__':
    main()
