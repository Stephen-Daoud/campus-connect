"""Campus Connect — CISC 106 final project (Python Drafter).

A social scheduling website for University of Delaware students.
Create an account, mark when you are free on a weekly calendar, add
friends by username, see when you are both free, and send activity
invitations that friends can accept or decline.

Pages (8):   Home, Create Account, Forgot Password, Profile, Calendar,
             Friends, Plan Activity, Inbox
Routes (24): index, sign_in, join, create_account, sign_out, verify_email,
             forgot_password, send_reset, profile, save_profile, change_password,
             delete_account, calendar,
             toggle_slot, set_hours, friends, send_friend_request,
             answer_friend_request, remove_friend, suggest, send_suggestion,
             inbox, respond, cancel_invitation

Two storage modes, chosen by the settings below:
  * FIREBASE MODE (settings filled in): real accounts with Firebase
    Authentication, and data in the Firebase Realtime Database, so friends
    see each other's changes from different devices. The database's
    security rules are in firebase_rules.json.
  * LOCAL DEMO MODE (settings blank): the same features, saved only in
    this browser, with sample students Alex, Jordan and Sam
    (password demo123). The automatic tests always use this mode.

Run in Thonny with the "drafter" package installed.
AI assistance was used to develop this code. Review it, test it, and
disclose the assistance according to your course instructions.
"""

from dataclasses import dataclass, field, asdict
import json
import sys
import hashlib

# Set this to True and press Run in Thonny to build the static website
# (a dist/ folder for GitHub Pages) instead of starting the local test server.
BUILD_FOR_DEPLOYMENT = False
if BUILD_FOR_DEPLOYMENT and sys.platform != "emscripten":
    import os
    os.environ["DRAFTER_MODE"] = "compile_site"     # Drafter reads this when imported

from drafter import *


# ------------------------------------------------------------
# Settings
# The Web API key identifies the project; it is not a password. Security
# comes from the database rules. Still, keep it out of public GitHub repos.
# NEVER put a service-account private key in this file.
# Leave both blank to use local demo mode instead of Firebase.
# ------------------------------------------------------------
FIREBASE_API_KEY = "AIzaSyBGdi_4qIydROoM8EJcVvQifJZDKS_S-gk"
FIREBASE_DATABASE_URL = "https://campus-connect-ud-default-rtdb.firebaseio.com"
ALLOWED_EMAIL_DOMAIN = ""      # for example "udel.edu" to allow only UD emails
# Students must click the link in their verification email before they can
# send friend requests or invitations (the database rules check this too).
REQUIRE_VERIFIED_EMAIL = True

DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
FIRST_HOUR = 7     # 7 AM
LAST_HOUR = 22     # the last block starts at 10 PM and ends at 11 PM
ACTIVITIES = ["Coffee", "Study", "Food", "Gym", "Sports", "Movie", "Walk", "Club meeting"]
REFRESH_MS = 30000             # friends' updates appear about every 30 seconds


def hour_label(hour: int) -> str:
    """Turn a 24-hour number into a label, for example 13 -> '1:00 PM'."""
    if hour < 12:
        suffix = "AM"
    else:
        suffix = "PM"
    shown = hour % 12
    if shown == 0:
        shown = 12
    return str(shown) + ":00 " + suffix


def make_times() -> list[str]:
    """Build the list of hourly time blocks shown on the calendar."""
    times = []
    for hour in range(FIRST_HOUR, LAST_HOUR + 1):
        times.append(hour_label(hour))
    return times


TIMES = make_times()   # "7:00 AM" ... "10:00 PM" (16 one-hour blocks)
END_TIMES = TIMES[1:] + [hour_label(LAST_HOUR + 1)]     # "8:00 AM" ... "11:00 PM"
DAY_GROUPS = {"Every day": DAYS,
              "Weekdays (Mon-Fri)": DAYS[1:6],
              "Weekend": ["Sunday", "Saturday"]}


def days_for(choice: str) -> list[str]:
    """'Tuesday' -> ['Tuesday']; 'Weekend' -> ['Sunday', 'Saturday']."""
    if choice in DAYS:
        return [choice]
    return DAY_GROUPS.get(choice, [])


def hours_between(start: str, end: str) -> list[str]:
    """Hour blocks from start up to (not including) end, e.g. 9 AM to 11 AM -> 9, 10."""
    if start not in TIMES or end not in END_TIMES:
        return []
    first = TIMES.index(start)
    last = END_TIMES.index(end)
    if last < first:
        return []
    return TIMES[first:last + 1]


# ------------------------------------------------------------
# Dataclasses
# ------------------------------------------------------------
@dataclass
class ActivityInvitation:
    sender_id: str
    recipient_id: str
    activity: str
    day: str
    time_slot: str
    status: str = "Pending"     # Pending, Accepted, or Declined


@dataclass
class State:
    session: dict[str, str] = field(default_factory=dict)        # signed-in student
    selected_day: str = "Monday"                                   # day compared with friends
    available_slots: list[str] = field(default_factory=list)      # "Tuesday|4:00 PM", ...
    invitations: list[ActivityInvitation] = field(default_factory=list)


# ------------------------------------------------------------
# Small helper functions
# ------------------------------------------------------------
def firebase_enabled() -> bool:
    return bool(FIREBASE_API_KEY.strip() and FIREBASE_DATABASE_URL.strip())


def current_user(state: State) -> str:
    return state.session.get("uid", "")


def signed_in(state: State) -> bool:
    return current_user(state) != ""


def slot_key(day: str, time: str) -> str:
    return day + "|" + time


def valid_slot(slot: str) -> bool:
    parts = slot.split("|")
    return len(parts) == 2 and parts[0] in DAYS and parts[1] in TIMES


def sorted_slots(slots: list[str]) -> list[str]:
    order = {slot_key(d, t): (i, j)
             for i, d in enumerate(DAYS) for j, t in enumerate(TIMES)}
    return sorted(set(slots), key=lambda s: order.get(s, (99, 99)))


def format_slot(slot: str) -> str:
    return slot.replace("|", " at ")


def short_slot(slot: str) -> str:
    day, time = slot.split("|")
    return day[:3] + " " + time


def shared_slots(my_slots: list[str], their_slots: list[str]) -> list[str]:
    """Return the time slots that appear in both lists, in calendar order."""
    both = []
    for slot in my_slots:
        if slot in their_slots:
            both.append(slot)
    return sorted_slots(both)


def slots_to_text(slots: list[str]) -> str:
    """Store a schedule as one string, for example 'Monday|9:00 AM;Tuesday|4:00 PM'."""
    return ";".join(sorted_slots(slots))


def text_to_slots(text) -> list[str]:
    if not isinstance(text, str) or text == "":
        return []
    slots = []
    for slot in text.split(";"):
        if valid_slot(slot):
            slots.append(slot)
    return slots


def clean_username(username: str) -> str:
    return username.strip().lower().lstrip("@")


def valid_username(username: str) -> bool:
    if len(username) < 3 or len(username) > 20:
        return False
    for letter in username:
        if not (letter.isdigit() or letter == "_" or ("a" <= letter <= "z")):
            return False
    return True


def invitation_id(invite: ActivityInvitation) -> str:
    """The same sender, friend, activity and time always gives the same ID,
    so sending twice cannot create two copies."""
    text = "|".join([invite.sender_id, invite.recipient_id, invite.activity,
                     invite.day, invite.time_slot])
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def friend_label(profile: dict) -> str:
    return profile.get("name", "Student") + " (@" + profile.get("username", "?") + ")"


# ------------------------------------------------------------
# Storage layer
# Every feature reads and writes "paths" like "friends/<uid>/<friend uid>".
# Firebase mode sends them to the Realtime Database; local demo mode keeps
# them in LOCAL_DB (saved in this browser's localStorage).
# ------------------------------------------------------------
LOCAL_DB = {}
LOCAL_STORAGE_KEY = "campus_connect_local_db_v3"
USE_BROWSER_STORAGE = True       # the tests turn this off
USE_LOCAL_FOR_TESTS = False      # the tests turn this on
# Login tokens live here, not in State, so they never show in Drafter's debug panel.
TOKENS = {"id_token": "", "refresh_token": "", "uid": ""}
SAVED_LOGIN_KEY = "campus_connect_saved_login"


def local_mode() -> bool:
    return USE_LOCAL_FOR_TESTS or not firebase_enabled()


def browser_storage():
    if USE_BROWSER_STORAGE and sys.platform == "emscripten":
        from js import localStorage
        return localStorage
    return None


def local_load():
    """Load the demo database (also picks up changes made in another tab)."""
    storage = browser_storage()
    if storage is not None:
        try:
            raw = storage.getItem(LOCAL_STORAGE_KEY)
            if raw:
                saved = json.loads(str(raw))
                if isinstance(saved, dict):
                    LOCAL_DB.clear()
                    LOCAL_DB.update(saved)
        except Exception:
            pass
    if not LOCAL_DB:
        local_seed()
        local_save()


def local_save() -> str:
    storage = browser_storage()
    if storage is None:
        return ""
    try:
        storage.setItem(LOCAL_STORAGE_KEY, json.dumps(LOCAL_DB))
        return ""
    except Exception:
        return "Could not save. Allow site storage in your browser and try again."


def path_parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def local_get(path: str):
    node = LOCAL_DB
    for part in path_parts(path):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return json.loads(json.dumps(node))      # a copy, like data from the internet


def local_set(path: str, value):
    parts = path_parts(path)
    node = LOCAL_DB
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            if value is None:
                return
            node[part] = {}
        node = node[part]
    if value is None:
        node.pop(parts[-1], None)
    else:
        node[parts[-1]] = json.loads(json.dumps(value))


def firebase_call(method: str, path: str, value=None, params=None):
    """Send one request to the Realtime Database. Returns (data, error)."""
    try:
        import requests
    except ImportError:
        return None, "The requests package is missing."
    url = FIREBASE_DATABASE_URL.rstrip("/") + "/" + path.strip("/") + ".json"
    for attempt in range(2):
        if not TOKENS["id_token"]:
            return None, "Your login expired. Please sign in again."
        query = {"auth": TOKENS["id_token"]}
        if params:
            query.update(params)
        try:
            response = requests.request(method, url, params=query, timeout=15,
                                        json=value if method in ("PUT", "PATCH") else None)
        except Exception:
            return None, "Could not reach Firebase. Check your internet connection."
        if response.status_code == 401 and attempt == 0 and refresh_login():
            continue                       # the login token was renewed; try again
        if response.status_code in (401, 403):
            return None, "Permission denied by the database rules."
        if not response.ok:
            return None, "Database error (" + str(response.status_code) + ")."
        try:
            return response.json(), ""
        except Exception:
            return None, "Firebase sent back something unexpected."
    return None, "Your login expired. Please sign in again."


def db_get(path: str):
    """Read one location. Returns (data or None, error)."""
    if local_mode():
        local_load()
        return local_get(path), ""
    return firebase_call("GET", path)


def db_set(path: str, value) -> str:
    """Write (or delete, when value is None) one location. Returns an error message or ''."""
    if local_mode():
        local_load()
        local_set(path, value)
        return local_save()
    if value is None:
        result, error = firebase_call("DELETE", path)
    else:
        result, error = firebase_call("PUT", path, value)
    return error


def db_update(changes: dict) -> str:
    """Write several locations at once: all succeed or none do."""
    if local_mode():
        local_load()
        for path, value in changes.items():
            local_set(path, value)
        return local_save()
    result, error = firebase_call("PATCH", "", changes)
    return error


def db_find(path: str, child: str, value: str):
    """Find records under path whose child equals value. Returns (dict, error)."""
    if local_mode():
        local_load()
        data = local_get(path) or {}
        found = {}
        for key, record in data.items():
            if isinstance(record, dict) and record.get(child) == value:
                found[key] = record
        return found, ""
    data, error = firebase_call("GET", path, params={"orderBy": json.dumps(child),
                                                     "equalTo": json.dumps(value)})
    return (data if isinstance(data, dict) else {}), error


def db_keys_starting_with(path: str, prefix: str, limit: int):
    """Find up to `limit` keys under path that start with prefix. Returns (dict, error)."""
    if local_mode():
        local_load()
        data = local_get(path) or {}
        found = {}
        for key in sorted(data):
            if key.startswith(prefix) and len(found) < limit:
                found[key] = data[key]
        return found, ""
    data, error = firebase_call("GET", path, params={
        "orderBy": json.dumps("$key"), "startAt": json.dumps(prefix),
        "endAt": json.dumps(prefix + ""), "limitToFirst": str(limit)})
    return (data if isinstance(data, dict) else {}), error


# ------------------------------------------------------------
# Accounts (Firebase Authentication, or demo accounts in LOCAL_DB)
# ------------------------------------------------------------
AUTH_MESSAGES = {
    "EMAIL_EXISTS": "An account with this email already exists. Try signing in.",
    "EMAIL_NOT_FOUND": "Wrong email or password.",
    "INVALID_PASSWORD": "Wrong email or password.",
    "INVALID_LOGIN_CREDENTIALS": "Wrong email or password.",
    "INVALID_EMAIL": "That email address doesn't look right.",
    "USER_DISABLED": "This account has been disabled.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts. Wait a few minutes and try again.",
}


def auth_request(action: str, payload: dict):
    """Call Firebase Authentication. Returns (result dict, error message)."""
    try:
        import requests
        response = requests.post("https://identitytoolkit.googleapis.com/v1/accounts:" + action,
                                 params={"key": FIREBASE_API_KEY}, json=payload, timeout=15)
        result = response.json()
    except Exception:
        return {}, "Could not reach Firebase. Check your internet connection."
    if not response.ok:
        code = str(result.get("error", {}).get("message", "UNKNOWN"))
        if code.startswith("WEAK_PASSWORD"):
            return {}, "Choose a password with at least 6 characters."
        return {}, AUTH_MESSAGES.get(code.split(" ")[0], "Sign in problem: " + code)
    return result, ""


def refresh_login() -> bool:
    """Firebase login tokens last one hour; trade the refresh token for a new one."""
    if not TOKENS["refresh_token"]:
        return False
    try:
        import requests
        response = requests.post("https://securetoken.googleapis.com/v1/token",
                                 params={"key": FIREBASE_API_KEY},
                                 data={"grant_type": "refresh_token",
                                       "refresh_token": TOKENS["refresh_token"]},
                                 timeout=15)
        if not response.ok:
            return False
        data = response.json()
        TOKENS["id_token"] = data["id_token"]
        TOKENS["refresh_token"] = data["refresh_token"]
        TOKENS["uid"] = data["user_id"]
        if saved_login()["uid"] == TOKENS["uid"]:
            remember_login()           # keep this student's saved copy up to date
        return True
    except Exception:
        return False


def remember_login():
    """Keep this browser signed in by saving the refresh token (like Firebase's own
    website library does), together with whose token it is. Signing out deletes it."""
    storage = browser_storage()
    if storage is not None and TOKENS["refresh_token"]:
        storage.setItem(SAVED_LOGIN_KEY, json.dumps({"uid": TOKENS["uid"],
                                                     "token": TOKENS["refresh_token"]}))


def saved_login() -> dict:
    """The login saved in this browser: {"uid": ..., "token": ...} (empty if none)."""
    storage = browser_storage()
    if storage is None or not storage.getItem(SAVED_LOGIN_KEY):
        return {"uid": "", "token": ""}
    try:
        saved = json.loads(str(storage.getItem(SAVED_LOGIN_KEY)))
        return {"uid": str(saved["uid"]), "token": str(saved["token"])}
    except Exception:
        return {"uid": "", "token": ""}


def forget_login(only_uid: str = ""):
    """Delete the saved login. With only_uid, only if it belongs to that student
    (so signing out in one tab doesn't sign out a different student's tab)."""
    storage = browser_storage()
    if storage is None:
        return
    if only_uid and saved_login()["uid"] not in ["", only_uid]:
        return
    storage.removeItem(SAVED_LOGIN_KEY)


def saved_login_exists() -> bool:
    return saved_login()["token"] != ""


def account_details():
    """Ask Firebase for the signed-in account's email and whether it is verified.
    Returns (email, verified, error)."""
    if local_mode():
        return "", True, ""
    result, error = auth_request("lookup", {"idToken": TOKENS["id_token"]})
    if error or not result.get("users"):
        return "", False, error or "Account not found."
    user = result["users"][0]
    return user.get("email", ""), bool(user.get("emailVerified", False)), ""


def send_verification_email() -> str:
    if local_mode():
        return ""
    result, error = auth_request("sendOobCode", {"requestType": "VERIFY_EMAIL",
                                                 "idToken": TOKENS["id_token"]})
    return error


def send_password_reset(email: str) -> str:
    if local_mode():
        return "Password reset emails only work when Firebase is connected."
    result, error = auth_request("sendOobCode", {"requestType": "PASSWORD_RESET",
                                                 "email": email})
    if error and "Wrong email" not in error:
        return error
    return ""        # same answer whether or not the account exists (privacy)


def account_key(email: str) -> str:
    return hashlib.sha256(email.encode()).hexdigest()[:20]


def password_hash(email: str, password: str) -> str:
    return hashlib.sha256(("campus-connect|" + email + "|" + password).encode()).hexdigest()


def create_login(email: str, password: str):
    """Make a new login. Returns (user ID, error)."""
    if local_mode():
        local_load()
        key = "accounts/" + account_key(email)
        if local_get(key) is not None:
            return "", AUTH_MESSAGES["EMAIL_EXISTS"]
        uid = "u_" + account_key(email)[:12]
        local_set(key, {"uid": uid, "password": password_hash(email, password)})
        return uid, local_save()
    result, error = auth_request("signUp", {"email": email, "password": password,
                                            "returnSecureToken": True})
    if error:
        return "", error
    TOKENS["id_token"] = result["idToken"]
    TOKENS["refresh_token"] = result["refreshToken"]
    TOKENS["uid"] = result["localId"]
    return result["localId"], ""


def check_login(email: str, password: str):
    """Check an email and password. Returns (user ID, error)."""
    if local_mode():
        local_load()
        account = local_get("accounts/" + account_key(email))
        if not account or account.get("password") != password_hash(email, password):
            return "", "Wrong email or password."
        return account["uid"], ""
    result, error = auth_request("signInWithPassword", {"email": email, "password": password,
                                                        "returnSecureToken": True})
    if error:
        return "", error
    TOKENS["id_token"] = result["idToken"]
    TOKENS["refresh_token"] = result["refreshToken"]
    TOKENS["uid"] = result["localId"]
    return result["localId"], ""


def delete_login(email: str):
    """Undo a half-finished sign up (for example, if the username was taken)."""
    if local_mode():
        db_set("accounts/" + account_key(email), None)
    else:
        auth_request("delete", {"idToken": TOKENS["id_token"]})
    TOKENS["id_token"] = ""
    TOKENS["refresh_token"] = ""
    TOKENS["uid"] = ""


def local_seed():
    """Sample data for local demo mode (fictional students only)."""
    people = [("alex", "Alex Kim", "Computer Science"),
              ("jordan", "Jordan Lee", "Biology"),
              ("sam", "Sam Patel", "Business")]
    for username, name, major in people:
        email = username + "@campusconnect.demo"
        uid = "demo_" + username
        local_set("accounts/" + account_key(email),
                  {"uid": uid, "password": password_hash(email, "demo123")})
        local_set("users/" + uid, {"username": username, "name": name, "major": major})
        local_set("usernames/" + username, uid)
    local_set("availability/demo_alex", slots_to_text(
        ["Monday|12:00 PM", "Tuesday|3:00 PM", "Tuesday|4:00 PM",
         "Thursday|7:00 PM", "Saturday|11:00 AM"]))
    local_set("availability/demo_jordan", slots_to_text(
        ["Monday|12:00 PM", "Tuesday|4:00 PM", "Tuesday|5:00 PM",
         "Wednesday|3:00 PM", "Saturday|11:00 AM"]))
    local_set("availability/demo_sam", slots_to_text(
        ["Tuesday|3:00 PM", "Thursday|7:00 PM", "Thursday|8:00 PM", "Sunday|2:00 PM"]))
    local_set("friends/demo_alex/demo_jordan", True)
    local_set("friends/demo_jordan/demo_alex", True)
    local_set("friend_requests/demo_alex/demo_sam", {"username": "sam", "name": "Sam Patel"})
    sample = ActivityInvitation("demo_jordan", "demo_alex", "Study", "Tuesday", "4:00 PM")
    local_set("invitations/" + invitation_id(sample), asdict(sample))


# ------------------------------------------------------------
# Reading and saving Campus Connect data
# ------------------------------------------------------------
def get_profile(uid: str) -> dict:
    data, error = db_get("users/" + uid)
    if isinstance(data, dict):
        return data
    return {"username": "unknown", "name": "Unknown student"}


def get_slots(uid: str):
    """Return (list of free slots, error)."""
    data, error = db_get("availability/" + uid)
    return text_to_slots(data), error


def save_slots(uid: str, slots: list[str]) -> str:
    return db_set("availability/" + uid, slots_to_text(slots))


def get_friend_ids(uid: str):
    data, error = db_get("friends/" + uid)
    if isinstance(data, dict):
        return list(data.keys()), error
    return [], error


def get_requests(uid: str):
    """Friend requests sent TO this student: {sender uid: {"username", "name"}}."""
    data, error = db_get("friend_requests/" + uid)
    return (data if isinstance(data, dict) else {}), error


def search_students(prefix: str):
    """Usernames starting with prefix: {username: uid}. Returns (dict, error)."""
    prefix = clean_username(prefix)
    if not prefix:
        return {}, ""
    return db_keys_starting_with("usernames", prefix, 8)


def friendship(me: str, other: str, friend_ids: list[str], incoming: dict) -> str:
    """Describe how two students are connected."""
    if other == me:
        return "you"
    if other in friend_ids:
        return "friends"
    if other in incoming:
        return "they asked"
    sent, error = db_get("friend_requests/" + other + "/" + me)
    if sent:
        return "requested"
    return "none"


def get_invitations(uid: str):
    """All invitations this student sent or received. Returns (list, error)."""
    received, error1 = db_find("invitations", "recipient_id", uid)
    sent, error2 = db_find("invitations", "sender_id", uid)
    invitations = []
    for record in list(received.values()) + list(sent.values()):
        try:
            invitations.append(ActivityInvitation(
                record["sender_id"], record["recipient_id"], record["activity"],
                record["day"], record["time_slot"], record.get("status", "Pending")))
        except (KeyError, TypeError):
            continue
    return invitations, error1 or error2


def friend_choices(state: State) -> dict:
    """Drop-down label -> friend uid, for example 'Jordan Lee (@jordan)' -> 'abc123'."""
    ids, error = get_friend_ids(current_user(state))
    choices = {}
    for friend_id in ids:
        choices[friend_label(get_profile(friend_id))] = friend_id
    return choices


# ------------------------------------------------------------
# Styling and repeated page parts
# ------------------------------------------------------------
STYLES = """
:root { --blue:#00539f; --blue-dark:#003b73; --gold:#ffd200; --ink:#1d2b40;
        --muted:#62738a; --line:#dde5ef; --bg:#f3f6fb; --green:#2e9d5b; }
body { background:var(--bg); color:var(--ink); font-family:"Segoe UI",Roboto,Arial,sans-serif; }
.cc-shell { max-width:1040px; margin:18px auto; padding:0 16px; font-size:16px; line-height:1.45; }
.cc-top { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap;
          gap:10px; background:var(--blue); color:white; border-radius:16px;
          padding:14px 20px; box-shadow:0 6px 18px #00539f33; }
.cc-brand { font-size:22px; font-weight:800; letter-spacing:.3px; }
.cc-brand span { color:var(--gold); }
.cc-user { font-size:14px; color:#dbe9ff; }
.cc-nav { display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 6px; }
.cc-nav a { padding:9px 14px; background:white; border:1px solid var(--line); border-radius:999px;
            text-decoration:none; color:var(--blue); font-weight:600; font-size:15px; }
.cc-nav a:hover { background:#e8f1ff; }
.cc-nav a.cc-here { background:var(--blue); color:white; border-color:var(--blue); }
.cc-title { font-size:26px; font-weight:800; margin:16px 2px 4px; color:var(--ink); }
.cc-hero { background:linear-gradient(120deg,var(--blue),#2f7fd0); color:white;
           border-radius:18px; padding:28px 30px; margin:14px 0; }
.cc-hero h1 { color:white; margin:0 0 8px; font-size:30px; }
.cc-panel { border:1px solid var(--line); background:white; border-radius:16px;
            padding:20px 22px; margin:14px 0; box-shadow:0 2px 10px #1d2b400d; }
.cc-panel h2 { margin:0 0 10px; font-size:20px; color:var(--ink); }
.cc-panel h3 { margin:0 0 6px; font-size:17px; color:var(--ink); }
.cc-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:0 14px; }
.cc-stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }
.cc-stat { background:white; border:1px solid var(--line); border-radius:14px; padding:14px 16px;
           color:var(--muted); font-size:14px; }
.cc-num { display:block; font-size:30px; font-weight:800; color:var(--blue); }
.cc-tile { padding:12px 14px; border:1px solid var(--line); border-radius:12px;
           background:#fbfdff; margin:8px 0; font-size:15px; }
.cc-muted { color:var(--muted); font-size:14px; }
.cc-alert { padding:12px 14px; background:#e7f6ed; color:#185532; border-radius:10px; margin:12px 0; }
.cc-warn { padding:12px 14px; background:#fff6d6; color:#5c4500; border-radius:10px;
           margin:12px 0; border:1px solid #f1d67a; }
.cc-error { padding:12px 14px; background:#fdeeee; color:#9a3030; border-radius:10px; margin:12px 0; }
.cc-field { margin-top:12px; }
.cc-status { font-weight:700; }
.cc-pending { color:#9a6b00; } .cc-accepted { color:#1f7a45; } .cc-declined { color:#9a3030; }
.cc-shell button { background:var(--blue); color:white; border:0; padding:10px 16px; font-weight:600;
         border-radius:10px; margin:6px 6px 6px 0; cursor:pointer; }
.cc-shell button:hover { background:var(--blue-dark); }
input,select { max-width:100%; padding:9px 10px; border:1px solid #c6d3e4;
               border-radius:9px; margin:5px 8px 8px 0; font-size:15px; }
.cc-quick select { margin-right:4px; }
.cc-footer { color:var(--muted); font-size:12px; padding:14px 2px 30px; }
.cc-legend span { display:inline-block; padding:3px 10px; border-radius:7px;
                  margin:0 8px 6px 0; font-size:13px; }
.cc-week { overflow-x:auto; }
.cc-week table { width:100%; border-collapse:separate; border-spacing:3px; font-size:13px; }
.cc-week th { background:var(--blue); color:white; padding:7px 4px; border-radius:7px; }
.cc-week td { padding:0; text-align:center; white-space:nowrap; }
.cc-week td:first-child { color:var(--muted); font-weight:700; padding-right:6px; text-align:right; }
.cc-shell .cc-week button { width:100%; min-width:62px; margin:0; padding:7px 2px; font-size:12px;
                  border-radius:7px; font-weight:600; }
.cc-shell button.cc-free, .cc-legend .cc-free { background:var(--green); color:white; }
.cc-shell button.cc-free:hover { background:#227a46; }
.cc-shell button.cc-both, .cc-legend .cc-both { background:#155c34; color:var(--gold); }
.cc-shell button.cc-busy, .cc-legend .cc-busy { background:#eef2f7; color:#8a99ad; }
.cc-shell button.cc-busy:hover { background:#d9e7fb; color:var(--blue); }
.cc-shell button.cc-gold { background:var(--gold); color:var(--ink); }
.cc-shell button.cc-gold:hover { background:#e6bc00; }
.cc-shell button.cc-light { background:#eef2f7; color:var(--ink); }
.cc-shell button.cc-light:hover { background:#dde5ef; }
.cc-shell button.cc-danger { background:#b3261e; }
.cc-shell button.cc-danger:hover { background:#8c1d17; }
.cc-shell button.cc-chip { font-size:13px; padding:6px 10px; }
@media (max-width:600px) {
  .cc-shell { margin:8px auto; padding:0 4px; }
  .cc-panel { padding:14px 12px; }
  .cc-hero { padding:20px; } .cc-hero h1 { font-size:24px; }
  .cc-shell .cc-week button { min-width:42px; }
}
"""

set_website_title("Campus Connect")
# Site-wide styles (pages with a Clock ignore Page(css=...), so add them here).
add_website_css(STYLES)
set_website_framed(False)
set_site_information(
    author="Stephen Daoud (sdaoud@udel.edu)",
    description="""Campus Connect: a social scheduling website for UD students.
    Mark your weekly free time, add friends, see when you're both free,
    and send activity invitations they can accept or decline.""",
    sources=["Official Drafter documentation",
             "Firebase Authentication and Realtime Database REST API documentation",
             "AI assistance: ChatGPT (early planning and first draft) and Claude "
             "(debugging, Firebase integration, testing)"],
    planning="plan.pdf",
    links=["https://github.com/Stephen-Daoud/campus-connect", "Demo video URL goes here"],
)


def running_on_public_site() -> bool:
    """True on the deployed website (not localhost), where the debug panel is hidden."""
    if sys.platform != "emscripten":
        return False
    from js import location
    return str(location.hostname) not in ["localhost", "127.0.0.1", ""]


if running_on_public_site():
    hide_debug_information()


def alert(message: str, is_error: bool = False):
    return Div(message, classes="cc-error" if is_error else "cc-alert")


def panel(title: str, *parts):
    return Div(Header(title, 2), *parts, classes="cc-panel")


def tile(*parts):
    return Div(*parts, classes="cc-tile")


def stat(number: int, label: str):
    return Div(Span(str(number), classes="cc-num"), label, classes="cc-stat")


def looks_like_error(message: str) -> bool:
    words = ["could not", "can't", "not ", "wrong", "invalid", "please", "denied",
             "taken", "already", "expired", "missing", "first"]
    lowered = message.lower()
    for word in words:
        if word in lowered:
            return True
    return False


def navigation(state: State, here: str):
    """Top navigation. Shows waiting friend requests and invitations as counts."""
    if not signed_in(state):
        pages = [("Home", "index", 0), ("Create account", "join", 0)]
    else:
        requests_waiting, _ = get_requests(current_user(state))
        received, _ = db_find("invitations", "recipient_id", current_user(state))
        pending = 0
        for record in received.values():
            if isinstance(record, dict) and record.get("status") == "Pending":
                pending += 1
        pages = [("Home", "index", 0), ("Calendar", "calendar", 0),
                 ("Friends", "friends", len(requests_waiting)),
                 ("Plan Activity", "suggest", 0), ("Inbox", "inbox", pending),
                 ("Profile", "profile", 0), ("Sign out", "sign_out", 0)]
    links = []
    for label, route_name, count in pages:
        if count > 0:
            label = label + " (" + str(count) + ")"
        if label.startswith(here):
            links.append(Link(label, route_name, classes="cc-here"))
        else:
            links.append(Link(label, route_name))
    return Div(*links, classes="cc-nav")


def verify_banner():
    return Div(Span("Check your inbox:", classes="cc-status"),
               " we sent you a link to verify your email. Until then you can set up your "
               "calendar, but you can't add friends or send invitations.",
               Div(Button("I've verified", "verify_email", {"resend": False}, classes="cc-chip"),
                   Button("Resend email", "verify_email", {"resend": True},
                          classes="cc-light cc-chip")),
               classes="cc-warn")


def make_page(state: State, here: str, heading: str, parts: list):
    if signed_in(state):
        who = state.session.get("name", "") + "  ·  @" + state.session.get("username", "")
    else:
        who = "Not signed in"
    if local_mode():
        mode = "Local demo mode: data is saved only in this browser."
    else:
        mode = "Connected to Firebase: your data syncs across devices."
    return Page(state, [
        Div(
            Div(Div("Campus ", Span("Connect"), classes="cc-brand"),
                Div(who, classes="cc-user"), classes="cc-top"),
            navigation(state, here),
            *([verify_banner()] if signed_in(state) and needs_verification(state) else []),
            *([Div(heading, classes="cc-title")] if heading else []),
            *parts,
            Div(mode + " Calendar times repeat every week.", classes="cc-footer"),
            classes="cc-shell",
        )
    ])


def needs_verification(state: State) -> bool:
    return (REQUIRE_VERIFIED_EMAIL and not local_mode()
            and state.session.get("verified") != "yes")


VERIFY_FIRST = "Please verify your email first: click the link we emailed you, then press \"I've verified\"."


def require_login(state: State):
    if signed_in(state):
        return None
    return index(state, "Please sign in first.")


# ------------------------------------------------------------
# Page sections that are built from loops
# ------------------------------------------------------------
def friends_free_counts(state: State) -> dict:
    """For every slot, how many friends are free then (used to color the calendar)."""
    counts = {}
    friend_ids, error = get_friend_ids(current_user(state))
    for friend_id in friend_ids:
        slots, problem = get_slots(friend_id)
        for slot in slots:
            counts[slot] = counts.get(slot, 0) + 1
    return counts


def week_grid(state: State):
    """The weekly calendar: one row per hour, one column per day.
    Each cell is a button; clicking it marks that hour free or busy."""
    counts = friends_free_counts(state)
    rows = []
    for time in TIMES:
        row = [time]
        for day in DAYS:
            key = slot_key(day, time)
            friends_free = counts.get(key, 0)
            if key in state.available_slots and friends_free > 0:
                row.append(Button("Free +" + str(friends_free), "toggle_slot",
                                  {"slot": key}, classes="cc-both"))
            elif key in state.available_slots:
                row.append(Button("Free", "toggle_slot", {"slot": key}, classes="cc-free"))
            else:
                row.append(Button("—", "toggle_slot", {"slot": key}, classes="cc-busy"))
        rows.append(row)
    header = ["Time"]
    for day in DAYS:
        header.append(day[:3])
    return Div(Table(rows, header=header), classes="cc-week")


def friends_on_day(state: State) -> list:
    """Calendar's friend panel: who is free on the selected day, and when you overlap."""
    friend_ids, error = get_friend_ids(current_user(state))
    if error:
        return [alert(error, True)]
    cards = []
    for friend_id in friend_ids:
        profile = get_profile(friend_id)
        slots, problem = get_slots(friend_id)
        if problem:
            cards.append(tile(Header(profile["name"], 3), alert(problem, True)))
            continue
        free = [time for time in TIMES if slot_key(state.selected_day, time) in slots]
        common = [time for time in free
                  if slot_key(state.selected_day, time) in state.available_slots]
        cards.append(tile(Header(profile["name"], 3),
                          "Free: " + (", ".join(free) or "nothing marked"),
                          Div("You're both free: " + (", ".join(common) or "no shared times"),
                              classes="cc-muted")))
    if not cards:
        return [Div("Add friends on the Friends page to compare schedules.", classes="cc-muted")]
    return cards


def friend_cards(state: State) -> list:
    """Friends page: each friend's free time, shared hours, and one-click invites."""
    friend_ids, error = get_friend_ids(current_user(state))
    if error:
        return [alert(error, True)]
    cards = []
    for friend_id in friend_ids:
        profile = get_profile(friend_id)
        slots, problem = get_slots(friend_id)
        if problem:
            cards.append(tile(Header(profile["name"], 3), alert(problem, True)))
            continue
        common = shared_slots(state.available_slots, slots)
        about = "@" + profile.get("username", "")
        if profile.get("major"):
            about = about + "  ·  " + profile["major"]
        parts = [Header(profile["name"], 3), Div(about, classes="cc-muted"),
                 Div("Free " + str(len(slots)) + " hour(s) a week  ·  you overlap " +
                     str(len(common)) + " hour(s)", classes="cc-field")]
        for slot in common[:6]:
            day, time = slot.split("|")
            parts.append(Button("Invite · " + short_slot(slot), "suggest",
                                {"friend_choice": friend_label(profile), "day": day,
                                 "time_slot": time}, classes="cc-gold cc-chip"))
        if len(common) > 6:
            parts.append(Div("+ " + str(len(common) - 6) + " more shared hours.", classes="cc-muted"))
        if not common:
            parts.append(Div("No shared free time yet.", classes="cc-muted"))
        parts.append(Div(Button("Remove friend", "remove_friend", {"friend_uid": friend_id},
                                classes="cc-light cc-chip")))
        cards.append(tile(*parts))
    if not cards:
        return [Div("No friends yet. Search for a classmate's username above.", classes="cc-muted")]
    return cards


def invitation_tiles(state: State, received: bool) -> list:
    """Inbox lists. received=True: invitations to me; False: ones I sent."""
    me = current_user(state)
    result = []
    # Required loop over the list of ActivityInvitation objects in State.
    for invitation in state.invitations:
        if received and invitation.recipient_id == me:
            other = get_profile(invitation.sender_id)
            parts = [Header(other["name"] + " invited you: " + invitation.activity, 3),
                     invitation.day + " at " + invitation.time_slot + "\n"]
            if invitation.status == "Pending":
                parts.append(Button("Accept", "respond",
                                    {"invite_id": invitation_id(invitation), "answer": "Accepted"}))
                parts.append(Button("Decline", "respond",
                                    {"invite_id": invitation_id(invitation), "answer": "Declined"},
                                    classes="cc-light"))
            else:
                parts.append(Div("You " + invitation.status.lower() + " this invitation.",
                                 classes="cc-status cc-" + invitation.status.lower()))
            result.append(tile(*parts))
        elif not received and invitation.sender_id == me:
            other = get_profile(invitation.recipient_id)
            parts = [Header(invitation.activity + " with " + other["name"], 3),
                     invitation.day + " at " + invitation.time_slot + "\n",
                     Div("Status: " + invitation.status,
                         classes="cc-status cc-" + invitation.status.lower())]
            if invitation.status == "Pending":
                parts.append(Button("Cancel invitation", "cancel_invitation",
                                    {"invite_id": invitation_id(invitation)},
                                    classes="cc-light cc-chip"))
            result.append(tile(*parts))
    if not result:
        if received:
            return [Div("No invitations yet.", classes="cc-muted")]
        return [Div("You haven't sent any invitations yet.", classes="cc-muted")]
    return result


# ------------------------------------------------------------
# Routes: Home, sign in, create account, sign out
# Drafter sends the current page's fields even when a link is clicked;
# **unused_fields collects those extra values.
# ------------------------------------------------------------
def restore_saved_login(state: State) -> bool:
    """'Stay signed in': use the refresh token saved in this browser, if any."""
    if local_mode() or signed_in(state) or not saved_login_exists():
        return False
    TOKENS["refresh_token"] = saved_login()["token"]
    if not refresh_login():
        forget_login()
        return False
    start_session(state, TOKENS["uid"], "")
    return True


@route
def index(state: State, message: str = "", **unused_fields) -> Page:
    if not message and restore_saved_login(state):
        message = "Welcome back! You're still signed in on this device."
    body = []
    if message:
        body.append(alert(message, looks_like_error(message)))
    if signed_in(state):
        me = current_user(state)
        friend_ids, _ = get_friend_ids(me)
        incoming, _ = get_requests(me)
        invitations, _ = get_invitations(me)
        waiting = 0
        for invitation in invitations:
            if invitation.recipient_id == me and invitation.status == "Pending":
                waiting += 1
        overlaps = []
        for friend_id in friend_ids:
            slots, problem = get_slots(friend_id)
            for slot in shared_slots(state.available_slots, slots):
                overlaps.append(tile(get_profile(friend_id)["name"] + "  ·  " + format_slot(slot)))
        body.append(Div(Header("Hi, " + state.session.get("name", "student") + "!", 1),
                        "Here's your week at a glance.", classes="cc-hero"))
        body.append(Div(stat(len(state.available_slots), "free hours a week"),
                        stat(len(friend_ids), "friends"),
                        stat(len(incoming), "friend requests"),
                        stat(waiting, "invitations waiting"),
                        classes="cc-stats"))
        if not overlaps:
            overlaps = [Div("Nothing yet. Mark free time on your Calendar and add friends.",
                            classes="cc-muted")]
        body.append(panel("When you and your friends are both free", *overlaps[:8],
                          Div(Link("Open your calendar", "calendar"), classes="cc-field")))
        return make_page(state, "Home", "", body)

    body.append(Div(Header("Find time for friends at UD", 1),
                    "Mark when you're free, see when friends are free, and plan coffee, "
                    "study sessions, workouts and more.", classes="cc-hero"))
    body.append(panel("Sign in",
                      "Email\n", TextBox("email", "", "email", placeholder="you@udel.edu"),
                      "\nPassword\n", TextBox("password", "", "password", placeholder="Password"),
                      Div(CheckBox("remember", True), " Keep me signed in on this device",
                          classes="cc-muted"),
                      Button("Sign in", "sign_in"),
                      Div(Link("Forgot your password?", "forgot_password"), classes="cc-field"),
                      Div("New here? ", Link("Create an account", "join"), classes="cc-field")))
    if local_mode():
        body.append(panel("Demo accounts",
                          "alex@campusconnect.demo, jordan@campusconnect.demo or "
                          "sam@campusconnect.demo, password demo123.",
                          Div("Local demo mode: data stays in this browser.", classes="cc-muted")))
    return make_page(state, "Home", "", body)


def start_session(state: State, uid: str, email: str) -> Page:
    """Shared by sign in, create account and 'stay signed in': load the student's data."""
    profile_data, error = db_get("users/" + uid)
    if not isinstance(profile_data, dict):
        profile_data = {}
    account_email, verified, problem = account_details()
    if account_email:
        email = account_email
    state.session = {"uid": uid, "email": email,
                     "name": profile_data.get("name", email.split("@")[0]),
                     "username": profile_data.get("username", ""),
                     "verified": "yes" if verified else "no"}
    state.selected_day = "Monday"
    state.invitations = []
    slots, error = get_slots(uid)
    state.available_slots = slots
    if error:
        return index(state, "Signed in, but your calendar could not load: " + error)
    return calendar(state)


@route
def sign_in(state: State, email: str = "", password: str = "", remember: bool = False,
            **unused_fields) -> Page:
    email = email.strip().lower()
    if not email or not password:
        return index(state, "Please enter your email and password.")
    uid, error = check_login(email, password)
    if error:
        return index(state, error)
    if remember:
        remember_login()
    else:
        forget_login(uid)
    return start_session(state, uid, email)


@route
def join(state: State, message: str = "", email: str = "", username: str = "",
         name: str = "", major: str = "", **unused_fields) -> Page:
    body = []
    if message:
        body.append(alert(message, looks_like_error(message)))
    rules = "Usernames use 3–20 lowercase letters, numbers or _. Passwords need 6+ characters."
    if ALLOWED_EMAIL_DOMAIN:
        rules = "Use your @" + ALLOWED_EMAIL_DOMAIN + " email. " + rules
    body.append(panel("Create your account",
                      "Full name\n", TextBox("name", name, placeholder="First Last"),
                      "\nUsername (friends search for this)\n",
                      TextBox("username", username, placeholder="blue_hen_24"),
                      "\nMajor (optional)\n", TextBox("major", major, placeholder="Computer Science"),
                      "\nEmail\n", TextBox("email", email, "email", placeholder="you@udel.edu"),
                      "\nPassword\n", TextBox("password", "", "password", placeholder="6+ characters"),
                      "\n", Button("Create account", "create_account"),
                      Div(rules, classes="cc-muted"),
                      Div("Already have an account? ", Link("Sign in", "index"), classes="cc-field")))
    return make_page(state, "Create account", "Create account", body)


@route
def create_account(state: State, email: str = "", password: str = "", username: str = "",
                   name: str = "", major: str = "", **unused_fields) -> Page:
    email = email.strip().lower()
    username = clean_username(username)
    name = name.strip()
    major = major.strip()

    def again(message: str) -> Page:
        return join(state, message, email, username, name, major)

    if not name or len(name) > 40:
        return again("Please enter your name (up to 40 characters).")
    if not valid_username(username):
        return again("Please choose a username with 3–20 lowercase letters, numbers or _.")
    if "@" not in email or "." not in email:
        return again("Please enter a valid email address.")
    if ALLOWED_EMAIL_DOMAIN and not email.endswith("@" + ALLOWED_EMAIL_DOMAIN):
        return again("Please use your @" + ALLOWED_EMAIL_DOMAIN + " email address.")
    if len(password) < 6:
        return again("Please choose a password with at least 6 characters.")
    if len(major) > 60:
        return again("Please shorten your major (up to 60 characters).")

    uid, error = create_login(email, password)
    if error:
        return again(error)
    owner, error = db_get("usernames/" + username)
    if owner or error:
        delete_login(email)
        return again("The username @" + username + " is already taken. Try another.")
    error = db_set("usernames/" + username, uid)
    if error:
        delete_login(email)
        return again("The username @" + username + " is already taken. Try another.")
    error = db_set("users/" + uid, {"username": username, "name": name, "major": major})
    if not error:
        error = save_slots(uid, [])
    if error:
        return again("Your account was created, but saving your profile failed: " + error)
    send_verification_email()
    remember_login()
    return start_session(state, uid, email)


@route
def sign_out(state: State, **unused_fields) -> Page:
    state.session = {}
    state.selected_day = "Monday"
    state.available_slots = []
    state.invitations = []
    TOKENS["id_token"] = ""
    TOKENS["refresh_token"] = ""
    forget_login(TOKENS["uid"])
    TOKENS["uid"] = ""
    return index(state, "You signed out. See you soon!")


# ------------------------------------------------------------
# Routes: Profile
# ------------------------------------------------------------
@route
def profile(state: State, message: str = "", **unused_fields) -> Page:
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    me = get_profile(current_user(state))
    body = []
    if message:
        body.append(alert(message, looks_like_error(message)))
    body.append(panel("Your profile",
                      Div("Username: @" + me.get("username", ""), classes="cc-status"),
                      Div("Email: " + state.session.get("email", ""), classes="cc-muted"),
                      "\nFull name\n", TextBox("profile_name", me.get("name", "")),
                      "\nMajor\n", TextBox("profile_major", me.get("major", "")),
                      "\n", Button("Save profile", "save_profile"),
                      Div("Friends see your name, username and major. Only friends can see "
                          "your calendar.", classes="cc-muted")))
    if not local_mode():
        body.append(panel("Password",
                          "We'll email you a link to choose a new password.",
                          Div(Button("Email me a password-change link", "change_password",
                                     classes="cc-light"))))
    body.append(panel("Delete account",
                      "This permanently deletes your profile, calendar, friends list and "
                      "invitations. Type your username to confirm.",
                      TextBox("confirm_username", "", placeholder=me.get("username", "")),
                      Button("Delete my account", "delete_account", classes="cc-danger")))
    return make_page(state, "Profile", "Profile", body)


@route
def change_password(state: State, **unused_fields) -> Page:
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    error = send_password_reset(state.session.get("email", ""))
    if error:
        return profile(state, "Could not send the email: " + error)
    return profile(state, "Sent! Check " + state.session.get("email", "your inbox") +
                   " for a link to choose a new password.")


@route
def delete_account(state: State, confirm_username: str = "", **unused_fields) -> Page:
    """Remove everything this student stored, then the login itself."""
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    me = current_user(state)
    username = state.session.get("username", "")
    if clean_username(confirm_username) != username or not username:
        return profile(state, "Not deleted: type your username exactly to confirm.")
    friend_ids, error = get_friend_ids(me)
    for friend_id in friend_ids:
        db_update({"friends/" + me + "/" + friend_id: None,
                   "friends/" + friend_id + "/" + me: None})
    invitations, error = get_invitations(me)
    for invitation in invitations:
        db_set("invitations/" + invitation_id(invitation), None)
    incoming, error = get_requests(me)
    for sender_uid in incoming:
        db_set("friend_requests/" + me + "/" + sender_uid, None)
    db_set("availability/" + me, None)
    db_set("users/" + me, None)
    error = db_set("usernames/" + username, None)
    if error:
        return profile(state, "Could not finish deleting your account: " + error)
    forget_login(me)
    delete_login(state.session.get("email", ""))
    state.session = {}
    state.selected_day = "Monday"
    state.available_slots = []
    state.invitations = []
    return index(state, "Your account and all of its data were deleted.")


@route
def save_profile(state: State, profile_name: str = "", profile_major: str = "",
                 **unused_fields) -> Page:
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    profile_name = profile_name.strip()
    profile_major = profile_major.strip()
    if not profile_name or len(profile_name) > 40:
        return profile(state, "Please enter a name (up to 40 characters).")
    if len(profile_major) > 60:
        return profile(state, "Please shorten your major (up to 60 characters).")
    me = get_profile(current_user(state))
    if me.get("username", "unknown") == "unknown":
        return profile(state, "Your account is missing a username. Please create a new account.")
    error = db_set("users/" + current_user(state),
                   {"username": me["username"], "name": profile_name, "major": profile_major})
    if error:
        return profile(state, "Could not save your profile: " + error)
    state.session["name"] = profile_name
    return profile(state, "Profile saved!")


# ------------------------------------------------------------
# Routes: Calendar
# ------------------------------------------------------------
@route
def calendar(state: State, compare_day: str = "", notice: str = "",
             interval: int = 0, **unused_fields):
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    if interval:      # the Clock asks every 30 seconds for friends' latest times
        return Fragment(state, friends_on_day(state), target="#friend_peek")
    if compare_day in DAYS:
        state.selected_day = compare_day
    body = []
    if notice:
        body.append(alert(notice, looks_like_error(notice)))
    body.append(panel(
        "Your weekly availability",
        "Click any hour to switch it between free and busy, or use Quick set below. "
        "Changes save right away.",
        Div(Span("Free", classes="cc-free"), Span("Free +2 = two friends free too", classes="cc-both"),
            Span("Busy / not set", classes="cc-busy"), classes="cc-legend cc-field"),
        week_grid(state),
        Div(Span("Quick set: ", classes="cc-status"),
            SelectBox("range_days", DAYS + list(DAY_GROUPS.keys()), state.selected_day),
            " from ", SelectBox("range_start", TIMES, "9:00 AM"),
            " to ", SelectBox("range_end", END_TIMES, "5:00 PM"),
            Button("Mark free", "set_hours", {"make_free": True}),
            Button("Mark busy", "set_hours", {"make_free": False}, classes="cc-light"),
            classes="cc-field cc-quick"),
        Div("Tip: choose \"Every day\", 7:00 AM to 11:00 PM, then Mark busy to clear your week.",
            classes="cc-muted"),
        Div("You are free " + str(len(state.available_slots)) + " hour(s) each week.",
            classes="cc-muted"),
    ))
    body.append(panel(
        "Compare with friends",
        Div("Day: ", SelectBox("compare_day", DAYS, state.selected_day),
            Button("Show friends", "calendar")),
        Output("friend_peek", friends_on_day(state)),
        Clock(REFRESH_MS, "calendar", show=False),
    ))
    return make_page(state, "Calendar", "Weekly Calendar", body)


@route
def toggle_slot(state: State, slot: str = "", **unused_fields) -> Page:
    """Clicking a calendar cell: if the hour is free, make it busy; otherwise make it free."""
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    if not valid_slot(slot):
        return calendar(state, notice="Not saved: that time is not on the calendar.")
    current, error = get_slots(current_user(state))
    if error:
        return calendar(state, notice="Not saved: " + error)
    if slot in current:
        current.remove(slot)
    else:
        current.append(slot)
    error = save_slots(current_user(state), current)
    if error:
        return calendar(state, notice="Not saved: " + error)
    state.available_slots = sorted_slots(current)
    return calendar(state)


@route
def set_hours(state: State, range_days: str = "", range_start: str = "", range_end: str = "",
              make_free: bool = False, **unused_fields) -> Page:
    """Quick set: mark a block of hours free (or busy) on one day or a group of days."""
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    days = days_for(range_days)
    hours = hours_between(range_start, range_end)
    if not days or not hours:
        return calendar(state, notice="Not saved: pick a day and an end time after the start time.")
    current, error = get_slots(current_user(state))
    if error:
        return calendar(state, notice="Not saved: " + error)
    chosen = []
    for day in days:
        for time in hours:
            chosen.append(slot_key(day, time))
    updated = [slot for slot in current if slot not in chosen]
    if make_free:
        updated = updated + chosen
    error = save_slots(current_user(state), updated)
    if error:
        return calendar(state, notice="Not saved: " + error)
    state.available_slots = sorted_slots(updated)
    if len(days) == 1:
        state.selected_day = days[0]
    word = "free" if make_free else "busy"
    return calendar(state, notice="Marked " + range_days + " " + range_start + " – " +
                    range_end + " as " + word + ".")


# ------------------------------------------------------------
# Routes: Friends
# ------------------------------------------------------------
@route
def friends(state: State, search_text: str = "", message: str = "", interval: int = 0,
            **unused_fields):
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    me = current_user(state)
    own, error = get_slots(me)
    if not error:
        state.available_slots = own
    if interval:      # the Clock asks every 30 seconds for friends' latest times
        return Fragment(state, friend_cards(state), target="#friends_live")
    friend_ids, _ = get_friend_ids(me)
    incoming, _ = get_requests(me)
    body = []
    if message:
        body.append(alert(message, looks_like_error(message)))

    # Search for students by username
    search = clean_username(search_text)
    results = []
    if search:
        found, error = search_students(search)
        if error:
            results.append(alert(error, True))
        for username, uid in found.items():
            other = get_profile(uid)
            link = friendship(me, uid, friend_ids, incoming)
            if link == "you":
                action = Div("That's you!", classes="cc-muted")
            elif link == "friends":
                action = Div("Already friends", classes="cc-status cc-accepted")
            elif link == "requested":
                action = Div("Request sent", classes="cc-status cc-pending")
            elif link == "they asked":
                action = Button("Accept their request", "answer_friend_request",
                                {"friend_uid": uid, "accept": True})
            else:
                action = Button("Add friend", "send_friend_request", {"friend_uid": uid},
                                classes="cc-gold")
            results.append(tile(Header(other["name"], 3), Div("@" + username, classes="cc-muted"),
                                action))
        if not found and not error:
            results.append(Div("No students found with a username starting with \"" +
                               search + "\".", classes="cc-muted"))
    body.append(panel("Find classmates",
                      TextBox("search_text", search, placeholder="Search by username"),
                      Button("Search", "friends"), *results))

    # Friend requests waiting for me
    if incoming:
        request_tiles = []
        for sender_uid, info in incoming.items():
            request_tiles.append(tile(
                Header(str(info.get("name", "A student")), 3),
                Div("@" + str(info.get("username", "")) + " wants to be friends.",
                    classes="cc-muted"),
                Button("Accept", "answer_friend_request", {"friend_uid": sender_uid, "accept": True}),
                Button("Decline", "answer_friend_request", {"friend_uid": sender_uid, "accept": False},
                       classes="cc-light")))
        body.append(panel("Friend requests (" + str(len(incoming)) + ")", *request_tiles))

    body.append(panel("Your friends (" + str(len(friend_ids)) + ")",
                      Div("Friends' calendars refresh automatically.", classes="cc-muted"),
                      Output("friends_live", friend_cards(state)),
                      Clock(REFRESH_MS, "friends", show=False)))
    return make_page(state, "Friends", "Friends", body)


@route
def send_friend_request(state: State, friend_uid: str = "", **unused_fields) -> Page:
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    if needs_verification(state):
        return friends(state, message=VERIFY_FIRST)
    me = current_user(state)
    if not friend_uid or friend_uid == me:
        return friends(state, message="Could not send: that student was not found.")
    other, error = db_get("users/" + friend_uid)
    if not isinstance(other, dict):
        return friends(state, message="Could not send: that student was not found.")
    friend_ids, _ = get_friend_ids(me)
    if friend_uid in friend_ids:
        return friends(state, message="You're already friends with " + other["name"] + ".")
    incoming, _ = get_requests(me)
    if friend_uid in incoming:
        return answer_friend_request(state, friend_uid, True)
    error = db_set("friend_requests/" + friend_uid + "/" + me,
                   {"username": state.session.get("username", ""),
                    "name": state.session.get("name", "")})
    if error:
        return friends(state, message="Could not send the request: " + error)
    return friends(state, message="Friend request sent to " + other["name"] + "!")


@route
def answer_friend_request(state: State, friend_uid: str = "", accept: bool = False,
                          **unused_fields) -> Page:
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    me = current_user(state)
    incoming, error = get_requests(me)
    if friend_uid not in incoming:
        return friends(state, message="Could not answer: that request was not found.")
    name = str(incoming[friend_uid].get("name", "your friend"))
    if accept and needs_verification(state):
        return friends(state, message=VERIFY_FIRST)
    if accept:
        # Both friend links and the removed request are saved together.
        error = db_update({"friends/" + me + "/" + friend_uid: True,
                           "friends/" + friend_uid + "/" + me: True,
                           "friend_requests/" + me + "/" + friend_uid: None})
        if error:
            return friends(state, message="Could not accept: " + error)
        return friends(state, message="You and " + name + " are now friends!")
    error = db_set("friend_requests/" + me + "/" + friend_uid, None)
    if error:
        return friends(state, message="Could not decline: " + error)
    return friends(state, message="Declined the request from " + name + ".")


@route
def remove_friend(state: State, friend_uid: str = "", **unused_fields) -> Page:
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    me = current_user(state)
    friend_ids, error = get_friend_ids(me)
    if friend_uid not in friend_ids:
        return friends(state, message="Could not remove: not in your friends list.")
    name = get_profile(friend_uid)["name"]
    error = db_update({"friends/" + me + "/" + friend_uid: None,
                       "friends/" + friend_uid + "/" + me: None})
    if error:
        return friends(state, message="Could not remove: " + error)
    return friends(state, message="Removed " + name + " from your friends.")


# ------------------------------------------------------------
# Routes: Plan an activity (send an invitation)
# ------------------------------------------------------------
@route
def suggest(state: State, friend_choice: str = "", message: str = "",
            activity: str = "", day: str = "", time_slot: str = "",
            **unused_fields) -> Page:
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    choices = friend_choices(state)
    labels = list(choices.keys())
    if friend_choice not in labels and labels:
        friend_choice = labels[0]
    if activity not in ACTIVITIES:
        activity = ACTIVITIES[0]
    if day not in DAYS:
        day = state.selected_day
    if time_slot not in TIMES:
        time_slot = "3:00 PM"
    body = []
    if message:
        body.append(alert(message, looks_like_error(message)))
    if not labels:
        body.append(panel("No friends yet",
                          "Add friends first, then you can invite them to activities.",
                          Div(Link("Find classmates", "friends"), classes="cc-field")))
        return make_page(state, "Plan Activity", "Plan an Activity", body)
    body.append(panel("Send an invitation",
                      "Friend\n", SelectBox("friend_choice", labels, friend_choice),
                      "\nActivity\n", SelectBox("activity", ACTIVITIES, activity),
                      "\nDay\n", SelectBox("day", DAYS, day),
                      "\nTime\n", SelectBox("time_slot", TIMES, time_slot), "\n",
                      Button("Send invitation", "send_suggestion"),
                      Div("Your friend can accept or decline it from their Inbox.",
                          classes="cc-muted")))
    own, _ = get_slots(current_user(state))
    tips = []
    for label, friend_id in choices.items():
        slots, problem = get_slots(friend_id)
        both = shared_slots(own, slots) if not problem else []
        tips.append(tile(Header(label, 3), "Both free: " +
                         (", ".join(short_slot(s) for s in both) or "no shared times yet")))
    body.append(panel("When you're both free", *tips))
    return make_page(state, "Plan Activity", "Plan an Activity", body)


@route
def send_suggestion(state: State, friend_choice: str = "", activity: str = "",
                    day: str = "", time_slot: str = "", **unused_fields) -> Page:
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in

    # Keep the chosen values so the form does not reset after a message.
    def again(message: str) -> Page:
        return suggest(state, friend_choice, message, activity, day, time_slot)

    if needs_verification(state):
        return again(VERIFY_FIRST)
    me = current_user(state)
    choices = friend_choices(state)
    if friend_choice not in choices:
        return again("Please choose one of your friends.")
    friend_id = choices[friend_choice]
    if activity not in ACTIVITIES or day not in DAYS or time_slot not in TIMES:
        return again("Please choose a valid activity, day, and time.")
    chosen = slot_key(day, time_slot)
    own, error = get_slots(me)
    if error:
        return again("Could not check your calendar: " + error)
    state.available_slots = own
    if chosen not in own:
        return again("You're not marked free then. Mark it free on your Calendar first.")
    theirs, error = get_slots(friend_id)
    if error:
        return again("Could not check your friend's calendar: " + error)
    name = get_profile(friend_id)["name"]
    if chosen not in theirs:
        return again(name + " is not free then. Pick a time you're both free.")
    invitation = ActivityInvitation(me, friend_id, activity, day, time_slot)
    existing, error = get_invitations(me)
    for old in existing:
        if invitation_id(old) == invitation_id(invitation):
            return again("You already sent this invitation. It's in " + name + "'s inbox.")
    error = db_set("invitations/" + invitation_id(invitation), asdict(invitation))
    if error:
        return again("Could not send the invitation: " + error)
    return again("Invitation sent to " + name + ": " + activity + " on " + day +
                 " at " + time_slot + "!")


# ------------------------------------------------------------
# Routes: Inbox
# ------------------------------------------------------------
@route
def inbox(state: State, message: str = "", interval: int = 0, **unused_fields):
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    invitations, error = get_invitations(current_user(state))
    if not error:
        # This route MEANINGFULLY changes State: it loads the latest invitations.
        state.invitations = invitations
    received = invitation_tiles(state, True)
    if error:
        received.insert(0, alert("Inbox could not refresh: " + error, True))
    if interval:      # the Clock asks every 30 seconds for new invitations
        return Fragment(state, received, target="#inbox_live")
    body = []
    if message:
        body.append(alert(message, looks_like_error(message)))
    body.append(Div(
        panel("Invitations to you", Output("inbox_live", received),
              Clock(REFRESH_MS, "inbox", show=False)),
        panel("Invitations you sent", *invitation_tiles(state, False)),
        classes="cc-grid"))
    body.append(panel("Plan something new", Link("Plan an activity", "suggest")))
    return make_page(state, "Inbox", "Inbox", body)


@route
def respond(state: State, invite_id: str = "", answer: str = "", **unused_fields) -> Page:
    """Accept or decline an invitation that was sent to the signed-in student."""
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    if answer not in ["Accepted", "Declined"]:
        return inbox(state, "Could not answer: choose Accept or Decline.")
    invitations, error = get_invitations(current_user(state))
    if error:
        return inbox(state, "Could not answer: " + error)
    for invitation in invitations:
        if invitation_id(invitation) == invite_id:
            if invitation.recipient_id != current_user(state):
                return inbox(state, "Could not answer: that invitation isn't addressed to you.")
            error = db_set("invitations/" + invite_id + "/status", answer)
            if error:
                return inbox(state, "Could not answer: " + error)
            return inbox(state, "You " + answer.lower() + " " + invitation.activity + " on " +
                         invitation.day + " at " + invitation.time_slot + ".")
    return inbox(state, "Could not answer: invitation not found.")


@route
def cancel_invitation(state: State, invite_id: str = "", **unused_fields) -> Page:
    """The sender can take back an invitation that hasn't been answered yet."""
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    invitations, error = get_invitations(current_user(state))
    for invitation in invitations:
        if invitation_id(invitation) == invite_id and invitation.sender_id == current_user(state):
            if invitation.status != "Pending":
                return inbox(state, "Could not cancel: your friend already answered.")
            error = db_set("invitations/" + invite_id, None)
            if error:
                return inbox(state, "Could not cancel: " + error)
            return inbox(state, "Cancelled the " + invitation.activity + " invitation.")
    return inbox(state, "Could not cancel: invitation not found.")


# ------------------------------------------------------------
# Routes: Email verification and password reset
# ------------------------------------------------------------
@route
def verify_email(state: State, resend: bool = False, **unused_fields) -> Page:
    not_logged_in = require_login(state)
    if not_logged_in:
        return not_logged_in
    if resend:
        error = send_verification_email()
        if error:
            return index(state, "Could not resend the email: " + error)
        return index(state, "Sent! Check your inbox (and spam folder) for the link.")
    refresh_login()                    # get a new login token that includes the update
    email, verified, error = account_details()
    if error:
        return index(state, "Could not check right now: " + error)
    state.session["verified"] = "yes" if verified else "no"
    if verified:
        return index(state, "Your email is verified. You can add friends and send invitations!")
    return index(state, "Your email isn't verified yet. Click the link in the email, then try again.")


@route
def forgot_password(state: State, message: str = "", **unused_fields) -> Page:
    body = []
    if message:
        body.append(alert(message, looks_like_error(message)))
    body.append(panel("Reset your password",
                      "Enter the email you signed up with. We'll email you a link to "
                      "choose a new password.\n",
                      TextBox("reset_email", "", "email", placeholder="you@udel.edu"),
                      Button("Send reset link", "send_reset"),
                      Div(Link("Back to sign in", "index"), classes="cc-field")))
    return make_page(state, "Home", "Forgot password", body)


@route
def send_reset(state: State, reset_email: str = "", **unused_fields) -> Page:
    email = reset_email.strip().lower()
    if "@" not in email or "." not in email:
        return forgot_password(state, "Please enter a valid email address.")
    error = send_password_reset(email)
    if error:
        return forgot_password(state, "Could not send the email: " + error)
    return forgot_password(state, "If an account uses " + email + ", a reset link is on its "
                           "way. Check your inbox and spam folder.")


# ------------------------------------------------------------
# Automatic tests (always run in local demo mode on temporary data,
# so they never touch Firebase or your saved data).
# Drafter lists them on the debug panel's Tests tab; Thonny prints them.
# ------------------------------------------------------------
def run_tests():
    global USE_BROWSER_STORAGE, USE_LOCAL_FOR_TESTS
    saved_db = json.loads(json.dumps(LOCAL_DB))
    saved_tokens = dict(TOKENS)
    USE_BROWSER_STORAGE = False
    USE_LOCAL_FOR_TESTS = True
    LOCAL_DB.clear()
    local_seed()
    try:
        # Helper functions
        assert_equal(hour_label(7), "7:00 AM")
        assert_equal(hour_label(12), "12:00 PM")
        assert_equal(hour_label(22), "10:00 PM")
        assert_equal(len(TIMES), 16)
        assert_equal(len(DAYS), 7)
        assert_equal(valid_slot("Sunday|7:00 AM"), True)
        assert_equal(valid_slot("Funday|7:00 AM"), False)
        assert_equal(sorted_slots(["Saturday|10:00 PM", "Sunday|7:00 AM"]),
                     ["Sunday|7:00 AM", "Saturday|10:00 PM"])
        assert_equal(text_to_slots(slots_to_text(["Monday|9:00 AM", "Sunday|7:00 AM"])),
                     ["Sunday|7:00 AM", "Monday|9:00 AM"])
        assert_equal(shared_slots(["Tuesday|4:00 PM", "Monday|3:00 PM"], ["Tuesday|4:00 PM"]),
                     ["Tuesday|4:00 PM"])
        assert_equal(valid_username("blue_hen_24"), True)
        assert_equal(valid_username("No Spaces!"), False)
        assert_equal(clean_username(" @Alex "), "alex")
        assert_equal(days_for("Weekend"), ["Sunday", "Saturday"])
        assert_equal(days_for("Tuesday"), ["Tuesday"])
        assert_equal(days_for("Someday"), [])
        assert_equal(hours_between("9:00 AM", "11:00 AM"), ["9:00 AM", "10:00 AM"])
        assert_equal(hours_between("7:00 AM", "11:00 PM"), TIMES)
        assert_equal(hours_between("5:00 PM", "9:00 AM"), [])

        # Sign in rules
        state = State()
        sign_in(state, "", "")
        assert_equal(state.session, {})
        sign_in(state, "alex@campusconnect.demo", "wrong")
        assert_equal(state.session, {})
        assert_equal(require_login(state) is None, False)

        # Create account: bad input is refused, a good account signs in
        create_account(state, "taylor@udel.edu", "123", "taylor", "Taylor Reed")
        assert_equal(state.session, {})
        create_account(state, "taylor@udel.edu", "secret1", "Bad Name!", "Taylor Reed")
        assert_equal(state.session, {})
        create_account(state, "taylor@udel.edu", "secret1", "alex", "Taylor Reed")
        assert_equal(state.session, {})            # username already taken
        create_account(state, "Taylor@UDel.edu ", "secret1", "taylor", "Taylor Reed", "Nursing")
        assert_equal(state.session["username"], "taylor")
        taylor = current_user(state)
        assert_equal(get_profile(taylor)["major"], "Nursing")
        sign_out(state)
        create_account(state, "taylor@udel.edu", "secret2", "taylor2", "Copy")
        assert_equal(state.session, {})            # email already used

        # Calendar: click to add and remove, quick fill
        sign_in(state, "taylor@udel.edu", "secret1")
        assert_equal(current_user(state), taylor)
        toggle_slot(state, "Thursday|7:00 PM")
        toggle_slot(state, "Tuesday|3:00 PM")
        toggle_slot(state, "Tuesday|5:00 PM")
        toggle_slot(state, "Tuesday|5:00 PM")
        assert_equal(state.available_slots, ["Tuesday|3:00 PM", "Thursday|7:00 PM"])
        toggle_slot(state, "Someday|3:00 PM")
        assert_equal(len(state.available_slots), 2)
        set_hours(state, "Saturday", "7:00 AM", "11:00 PM", True)
        assert_equal(len(state.available_slots), 2 + 16)
        set_hours(state, "Saturday", "7:00 AM", "11:00 PM", False)
        assert_equal(get_slots(taylor)[0], ["Tuesday|3:00 PM", "Thursday|7:00 PM"])
        set_hours(state, "Weekdays (Mon-Fri)", "9:00 AM", "11:00 AM", True)
        assert_equal(len(state.available_slots), 2 + 5 * 2)
        assert_equal("Friday|10:00 AM" in state.available_slots, True)
        set_hours(state, "Every day", "9:00 AM", "11:00 AM", False)
        assert_equal(state.available_slots, ["Tuesday|3:00 PM", "Thursday|7:00 PM"])
        set_hours(state, "Monday", "5:00 PM", "9:00 AM", True)        # end before start
        assert_equal(len(state.available_slots), 2)
        calendar(state, "Friday")
        assert_equal(state.selected_day, "Friday")

        # Profile edits
        save_profile(state, "Taylor R.", "Nursing")
        assert_equal(get_profile(taylor)["name"], "Taylor R.")

        # Friends: search, request, accept
        assert_equal(search_students("sa")[0], {"sam": "demo_sam"})
        assert_equal(len(search_students("")[0]), 0)
        send_suggestion(state, "Sam Patel (@sam)", "Coffee", "Tuesday", "3:00 PM")
        assert_equal(get_invitations(taylor)[0], [])     # not friends yet
        send_friend_request(state, "demo_sam")
        assert_equal(get_requests("demo_sam")[0][taylor]["username"], "taylor")
        send_friend_request(state, taylor)               # can't friend yourself
        assert_equal(taylor in get_requests(taylor)[0], False)
        sign_out(state)
        sign_in(state, "sam@campusconnect.demo", "demo123")
        answer_friend_request(state, taylor, True)
        assert_equal(taylor in get_friend_ids("demo_sam")[0], True)
        assert_equal("demo_sam" in get_friend_ids(taylor)[0], True)
        assert_equal(taylor in get_requests("demo_sam")[0], False)

        # Invitations: checks both calendars, sends once, recipient answers
        sign_out(state)
        sign_in(state, "taylor@udel.edu", "secret1")
        send_suggestion(state, "Sam Patel (@sam)", "Coffee", "Tuesday", "4:00 PM")   # Taylor busy
        send_suggestion(state, "Sam Patel (@sam)", "Coffee", "Thursday", "8:00 PM")  # Taylor busy
        send_suggestion(state, "Jordan Lee (@jordan)", "Coffee", "Tuesday", "3:00 PM")  # not a friend
        assert_equal(get_invitations(taylor)[0], [])
        send_suggestion(state, "Sam Patel (@sam)", "Gym", "Thursday", "7:00 PM")
        send_suggestion(state, "Sam Patel (@sam)", "Gym", "Thursday", "7:00 PM")
        assert_equal(get_invitations(taylor)[0],
                     [ActivityInvitation(taylor, "demo_sam", "Gym", "Thursday", "7:00 PM")])
        gym_id = invitation_id(ActivityInvitation(taylor, "demo_sam", "Gym", "Thursday", "7:00 PM"))
        respond(state, gym_id, "Accepted")              # Taylor can't answer her own
        assert_equal(get_invitations(taylor)[0][0].status, "Pending")
        sign_out(state)
        sign_in(state, "sam@campusconnect.demo", "demo123")
        inbox(state)
        assert_equal(len(state.invitations), 1)
        respond(state, gym_id, "Accepted")
        assert_equal(get_invitations("demo_sam")[0][0].status, "Accepted")

        # Sender can cancel a pending invitation, but not an answered one
        sign_out(state)
        sign_in(state, "taylor@udel.edu", "secret1")
        send_suggestion(state, "Sam Patel (@sam)", "Walk", "Tuesday", "3:00 PM")
        walk_id = invitation_id(ActivityInvitation(taylor, "demo_sam", "Walk", "Tuesday", "3:00 PM"))
        assert_equal(len(get_invitations(taylor)[0]), 2)
        cancel_invitation(state, gym_id)                # already accepted
        cancel_invitation(state, walk_id)
        assert_equal(get_invitations(taylor)[0],
                     [ActivityInvitation(taylor, "demo_sam", "Gym", "Thursday", "7:00 PM", "Accepted")])
        sign_out(state)
        sign_in(state, "sam@campusconnect.demo", "demo123")

        # Removing a friend removes both links
        remove_friend(state, taylor)
        assert_equal(taylor in get_friend_ids("demo_sam")[0], False)
        assert_equal("demo_sam" in get_friend_ids(taylor)[0], False)
        sign_out(state)
        assert_equal(state.session, {})
        # Deleting an account removes the student everywhere
        sign_in(state, "taylor@udel.edu", "secret1")
        delete_account(state, "wrong_name")
        assert_equal(current_user(state), taylor)        # not deleted without confirmation
        delete_account(state, "taylor")
        assert_equal(state.session, {})
        assert_equal(db_get("users/" + taylor)[0], None)
        assert_equal(db_get("usernames/taylor")[0], None)
        assert_equal(get_invitations("demo_sam")[0], [])
        sign_in(state, "taylor@udel.edu", "secret1")
        assert_equal(state.session, {})                  # the login is gone too

        # Demo mode: no email checks, and reset emails need Firebase
        assert_equal(needs_verification(state), False)
        assert_equal(send_password_reset("a@b.edu") != "", True)
    finally:
        LOCAL_DB.clear()
        LOCAL_DB.update(saved_db)
        TOKENS.update(saved_tokens)
        USE_BROWSER_STORAGE = True
        USE_LOCAL_FOR_TESTS = False


run_tests()

if __name__ == "__main__":
    start_server(State())
