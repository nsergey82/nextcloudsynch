"""Two-way synch. of calendar events
Will first fetch from sources (atm: evault and nextcloud)
For each event will figure out the sources that do not have it
and write the event to the source, using appropriate api.
TODO: updated entries are not synched
"""

from icalendar import Calendar
import os
from w3ds.utils import VaultIO, envelope_to_py
import caldav
import base64
import datetime

PP_JWT_TOKEN = os.getenv("PP_JWT_TOKEN", "secret")
EVENT_ONTOLOGY = "880e8400-e29b-41d4-a716-446655440099"

ename = "@82f7a77a-f03a-52aa-88fc-1b1e488ad498"
nc_user = "admin"
NXT_PASSWORD = os.getenv("NXT_PASSWORD", "secret")
base_url = "https://radikal.no-ip.info"


def _gen_events_from_ical(vevents: str):
    """One or more events serialized as ical string"""
    cal = Calendar.from_ical(vevents)
    for event in cal.events:
        uid = str(event.get("UID"))
        if uid is not None:
            yield uid, event


def get_events_from_evault(token, ename):
    vio = VaultIO(token, ename)
    ids_to_events = {}
    for menv in vio.get_envelopes_for_ontology(EVENT_ONTOLOGY):
        data = envelope_to_py(menv)
        uid = data.get("uid")
        if uid is None:
            uid = menv["id"]
            data["uid"] = uid
        ids_to_events[uid] = data
    return ids_to_events


def _get_calendar_from_nextcloud(
    base_url: str, password: str, userId: str, calendarName: str
):
    headers = {
        "AA-VERSION": "2.3.0",
        "EX-APP-ID": "flow",
        "EX-APP-VERSION": "1.0.0",
        "AUTHORIZATION-APP-API": base64.b64encode(
            f"{userId}:{password}".encode("utf-8")
        ).decode("utf-8"),
    }

    with caldav.DAVClient(
        url=base_url + "/remote.php/dav/calendars/" + userId + "/",
        username=userId,
        password=password,
        headers=headers,
    ) as client:
        my = client.principal()
        calendar = next(filter(lambda c: c.name == calendarName, my.calendars()))
        if calendar is None:
            raise ValueError("Could not find calendar" + calendarName)
        return calendar


def get_events_from_nextcloud(calendar):
    """
    One can also run:
        select CONVERT_FROM(calendardata, 'UTF8') from oc_calendarobjects limit 1
    via pql in the db container
    or docker exec nextcloud-aio-nextcloud php occ calendar:export {user} {uri}
    """
    ids_to_events = {}
    for e in calendar.events():
        for uid, event in _gen_events_from_ical(e.data):
            ids_to_events[uid] = event
    return ids_to_events


def store_evault_event_in_nextcloud(calendar, evault_event):
    print("store", evault_event, "in nextcloud")
    event = calendar.add_event(
        dtstart=datetime.datetime.fromisoformat(evault_event["start"]),
        dtend=datetime.datetime.fromisoformat(evault_event["end"]),
        summary=evault_event["title"],
        uid=evault_event.get("uid", "-1"),
        color=evault_event.get("color", "blue"),
    )
    # "description": description.replace("\n", "__"),
    # "recurrence": False,  # RRULE
    print(event)


def store_nc_event_in_evault(token, ename, event):
    vio = VaultIO(token, ename)

    title = event.get("SUMMARY")
    color = event.get("COLOR", "blue")
    start = event.get("DTSTART").dt
    end = event.get("DTEND").dt
    description = event.get("DESCRIPTION", "")
    uid = str(event.get("UID"))

    vio.store_envelopes(
        EVENT_ONTOLOGY,
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "title": title,
            "description": description.replace("\n", "__"),
            "recurrence": False,  # RRULE
            "color": color,
            "uid": uid,
        },
    )
    print("store", uid, "in evault")


evault_events = get_events_from_evault(PP_JWT_TOKEN, ename)
print(evault_events)
nc_calendar = _get_calendar_from_nextcloud(base_url, NXT_PASSWORD, nc_user, "Personal")
nextcloud_events = get_events_from_nextcloud(nc_calendar)

for uid, evt in nextcloud_events.items():
    if uid not in evault_events:
        print(uid, "not in evault")
        store_nc_event_in_evault(PP_JWT_TOKEN, ename, evt)

for uid, evt in evault_events.items():
    print(uid)
    if uid not in nextcloud_events:
        print(uid, "not in nextcloud")
        store_evault_event_in_nextcloud(nc_calendar, evt)
