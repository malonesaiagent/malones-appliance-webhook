
"""
Malone's Appliance Repair - Scheduling System (NO SMS VERSION)
This version works without Telnyx SMS verification
SMS confirmation will be added later when Telnyx is verified
"""

import os
import json
from datetime import datetime, timedelta
import pytz
import requests

# ==================== CONFIGURATION ====================

HOME_BASE_ZIP = "81039"
TIMEZONE = "America/Denver"

# Geographic Zones
PUEBLO_ZIPS = {
    "81001", "81003", "81004", "81005", "81006", "81007", "81008", "81009",
    "81010", "81011", "81012", "81019", "81020", "81021", "81022", "81023",
    "81025"
}

VALLEY_ZIPS = {
    "81020", "81021", "81022", "81024", "81027", "81030", "81041", "81043",
    "81050", "81054", "81055", "81059", "81062", "81063", "81071", "81073",
    "81082", "81089", "81090", "81091"
}

# Business hours and excluded appliances
BUSINESS_HOURS = {"start": 9, "end": 16, "slot_duration_hours": 2}
EXCLUDED_APPLIANCES = ["microwave", "toaster", "coffee maker", "blender", "mixer",
                        "air fryer", "slow cooker", "pressure cooker", "rice cooker"]

# Reference for alternating pattern - CORRECTED: December 2, 2025 is TUESDAY
REFERENCE_DATE = datetime(2025, 12, 2, tzinfo=pytz.timezone(TIMEZONE))  # TUESDAY Dec 2 = Pueblo
REFERENCE_ZONE = "pueblo"

# ==================== ZONE FUNCTIONS ====================

def determine_zone(zip_code):
    """Determine geographic zone from ZIP code"""
    zip_code = zip_code.strip()
    if zip_code == HOME_BASE_ZIP:
        return "home"
    elif zip_code in PUEBLO_ZIPS:
        return "pueblo"
    elif zip_code in VALLEY_ZIPS:
        return "valley"
    return None

def get_zone_for_date(target_date):
    """Calculate which zone is serviced on a given date"""
    tz = pytz.timezone(TIMEZONE)
    if target_date.tzinfo is None:
        target_date = tz.localize(target_date)

    target_normalized = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    reference_normalized = REFERENCE_DATE.replace(hour=0, minute=0, second=0, microsecond=0)

    business_days_diff = 0
    current = reference_normalized
    direction = 1 if target_normalized >= reference_normalized else -1

    while current != target_normalized:
        current += timedelta(days=direction)
        if current.weekday() < 5:
            business_days_diff += direction

    if business_days_diff % 2 == 0:
        return REFERENCE_ZONE
    return "valley" if REFERENCE_ZONE == "pueblo" else "pueblo"

def get_available_time_slots(zone):
    """Get available time slots for a zone"""
    if zone == "home":
        return ["9:00 AM", "4:00 PM"]

    slots = []
    for hour in range(BUSINESS_HOURS["start"], BUSINESS_HOURS["end"], 
                     BUSINESS_HOURS["slot_duration_hours"]):
        slots.append(format_time_slot(hour))
    return slots

def format_time_slot(hour):
    """Format hour to readable time string"""
    if hour == 12:
        return "12:00 PM"
    elif hour > 12:
        return f"{hour - 12}:00 PM"
    return f"{hour}:00 AM"

def parse_time_slot(time_str):
    """Parse time string to hour integer"""
    time_str = time_str.strip().upper()
    time_part = time_str.replace("AM", "").replace("PM", "").strip()
    hour = int(time_part.split(":")[0])

    if "PM" in time_str and hour != 12:
        hour += 12
    elif "AM" in time_str and hour == 12:
        hour = 0

    return hour

# ==================== VALIDATION ====================

def validate_appointment_request(zip_code, requested_date, requested_time, appliance_type):
    """Validate appointment against business rules"""
    tz = pytz.timezone(TIMEZONE)

    # Check appliance type
    appliance_lower = appliance_type.lower()
    for excluded in EXCLUDED_APPLIANCES:
        if excluded in appliance_lower:
            return False, f"Sorry, we don't service {appliance_type}. We only service major appliances.", None, []

    # Determine zone
    zone = determine_zone(zip_code)
    if zone is None:
        return False, f"Sorry, ZIP code {zip_code} is outside our service area.", None, []

    # Parse and validate date
    if isinstance(requested_date, str):
        requested_date = datetime.strptime(requested_date, "%Y-%m-%d")
    if requested_date.tzinfo is None:
        requested_date = tz.localize(requested_date)

    # Check weekend
    if requested_date.weekday() >= 5:
        return False, "We only schedule appointments Monday through Friday.", zone, []

    # Check past date
    now = datetime.now(tz)
    if requested_date.date() < now.date():
        return False, "Cannot schedule appointments in the past.", zone, []

    # Check zone/day match
    if zone != "home":
        scheduled_zone = get_zone_for_date(requested_date)
        if zone != scheduled_zone:
            return False, f"We service the {zone.title()} zone on different days.", zone, []

    # Validate time slot
    available_slots = get_available_time_slots(zone)
    if requested_time:
        requested_hour = parse_time_slot(requested_time)
        requested_time_formatted = format_time_slot(requested_hour)

        if requested_time_formatted not in available_slots:
            return False, f"Time {requested_time} not available. Options: {', '.join(available_slots)}", zone, available_slots

    return True, None, zone, available_slots

def get_next_available_dates(zone, count=5):
    """Get next available dates for a zone"""
    tz = pytz.timezone(TIMEZONE)
    available_dates = []
    current = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)

    if datetime.now(tz).hour >= BUSINESS_HOURS["end"]:
        current += timedelta(days=1)

    while len(available_dates) < count:
        if current.weekday() < 5:
            if zone == "home":
                available_dates.append(current)
            else:
                scheduled_zone = get_zone_for_date(current)
                if scheduled_zone == zone:
                    available_dates.append(current)
        current += timedelta(days=1)

    return available_dates

# ==================== COMPOSIO INTEGRATION ====================

def check_calendar_availability(appointment_date, appointment_time, composio_api_key):
    """Check Google Calendar for conflicts"""
    tz = pytz.timezone(TIMEZONE)
    hour = parse_time_slot(appointment_time)

    if isinstance(appointment_date, str):
        appointment_date = datetime.strptime(appointment_date, "%Y-%m-%d")

    start_dt = appointment_date.replace(hour=hour, minute=0, second=0, microsecond=0)
    if start_dt.tzinfo is None:
        start_dt = tz.localize(start_dt)

    end_dt = start_dt + timedelta(hours=2)

    try:
        response = requests.post(
            'https://backend.composio.dev/api/v2/actions/GOOGLECALENDAR_FIND_EVENT/execute',
            json={
                "input": {
                    "calendar_id": "primary",
                    "timeMin": start_dt.isoformat(),
                    "timeMax": end_dt.isoformat(),
                    "single_events": True
                }
            },
            headers={
                'X-API-Key': composio_api_key,
                'Content-Type': 'application/json'
            }
        )

        if response.status_code == 200:
            data = response.json()
            events = data.get('data', {}).get('data', {}).get('items', [])
            return len(events) == 0, events
        return True, []

    except Exception as e:
        print(f"Calendar check error: {e}")
        return True, []

def create_calendar_appointment(customer_name, phone, zip_code, appliance_type,
                               appointment_date, appointment_time, composio_api_key):
    """Create appointment in Google Calendar"""
    tz = pytz.timezone(TIMEZONE)
    hour = parse_time_slot(appointment_time)

    if isinstance(appointment_date, str):
        appointment_date = datetime.strptime(appointment_date, "%Y-%m-%d")

    start_dt = appointment_date.replace(hour=hour, minute=0, second=0, microsecond=0)
    if start_dt.tzinfo is None:
        start_dt = tz.localize(start_dt)

    description = f"""Appliance: {appliance_type}
Customer: {customer_name}
Phone: {phone}
ZIP: {zip_code}
Arrival Window: {appointment_time} - {format_time_slot(hour + 2)}

NOTE: SMS confirmation not sent (Telnyx verification pending)
"""

    try:
        response = requests.post(
            'https://backend.composio.dev/api/v2/actions/GOOGLECALENDAR_CREATE_EVENT/execute',
            json={
                "input": {
                    "calendar_id": "primary",
                    "start_datetime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    "timezone": TIMEZONE,
                    "event_duration_hour": 2,
                    "event_duration_minutes": 0,
                    "summary": f"Repair: {appliance_type} - {customer_name}",
                    "description": description
                }
            },
            headers={
                'X-API-Key': composio_api_key,
                'Content-Type': 'application/json'
            }
        )

        if response.status_code == 200:
            return True, response.json()
        return False, response.text

    except Exception as e:
        return False, str(e)

# ==================== MAIN BOOKING FUNCTION (NO SMS) ====================

def book_appointment(customer_name, phone, zip_code, appliance_type,
                    appointment_date, appointment_time, composio_api_key):
    """
    Complete appointment booking flow WITHOUT SMS
    SMS will be added later when Telnyx is verified

    Returns: (success, message, event_data)
    """

    # Step 1: Validate
    is_valid, error, zone, slots = validate_appointment_request(
        zip_code, appointment_date, appointment_time, appliance_type
    )

    if not is_valid:
        return False, error, None

    # Step 2: Check calendar availability
    available, conflicts = check_calendar_availability(
        appointment_date, appointment_time, composio_api_key
    )

    if not available:
        return False, "That time slot is already booked. Please choose another time.", None

    # Step 3: Create calendar event
    success, event_data = create_calendar_appointment(
        customer_name, phone, zip_code, appliance_type,
        appointment_date, appointment_time, composio_api_key
    )

    if not success:
        return False, f"Failed to create appointment: {event_data}", None

    # Step 4: SMS SKIPPED - Telnyx not verified yet
    confirmation_msg = f"Appointment booked for {customer_name}! Calendar event created. SMS confirmation will be available once Telnyx is verified."

    return True, confirmation_msg, event_data

# ==================== HELPER FUNCTIONS ====================

def format_date_options(dates):
    """Format dates for conversation"""
    return [f"{i+1}. {d.strftime('%A, %B %d')}" for i, d in enumerate(dates)]

def parse_natural_language_date(text, available_dates=None):
    """Parse natural language date input"""
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    text_lower = text.lower()

    if "today" in text_lower:
        return now
    elif "tomorrow" in text_lower:
        return now + timedelta(days=1)

    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    for i, day in enumerate(day_names):
        if day in text_lower:
            days_ahead = i - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return now + timedelta(days=days_ahead)

    if available_dates:
        for i in range(len(available_dates)):
            if str(i + 1) in text or ["first", "second", "third", "fourth", "fifth"][i] in text_lower:
                return available_dates[i]

    return None
