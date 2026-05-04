import streamlit as st
import pickle
import numpy as np
import pandas as pd
import base64
import bcrypt

from streamlit_js_eval import get_geolocation

# --- Google Drive API imports ---
from google.oauth2 import service_account
from googleapiclient.discovery import build

from googleapiclient.http import MediaIoBaseDownload
import io

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = b"$2b$12$MPJl2FrXIPEqqkcP3oS/v.pHal3PeviaZZCIHyOMQQ/qYHpZmQWUO"

# ---------------------------------------------------------------
# REVERSE GEOCODING USING OPENSTREETMAP (NOMINATIM)
# ---------------------------------------------------------------
# This function takes latitude & longitude and returns:
# {
#     "city": "...",
#     "state": "...",
#     "country": "..."
# }
# If lookup fails, returns None safely.
# ---------------------------------------------------------------
def reverse_geocode(lat, lon, zoom=18, language="en"):
    """
    Improved reverse geocode using Nominatim with:
      - explicit addressdetails=1
      - configurable zoom (higher = more granular)
      - accept-language header (recommended)
    Returns None on failure or a dict:
    {
      "full_address": "...",
      "components": {...},   # keys like road, house_number, postcode, city, state, country
      "raw": {...}           # full JSON for debugging
    }
    """
    import requests
    try:
        # ensure high precision coordinates
        lat = float(lat)
        lon = float(lon)
        coords = f"{lat:.7f},{lon:.7f}"

        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            "format": "json",
            "lat": lat,
            "lon": lon,
            "addressdetails": 1,
            "zoom": zoom,             
            "namedetails": 0,
            "extratags": 0,
        }

        headers = {
            "User-Agent": "GeotunesApp/1.0 (+https://yourapp.example)",
            "Accept-Language": language
        }

        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        return {
            "full_address": data.get("display_name"),
            "components": data.get("address", {}),
            "raw": data
        }

    except requests.exceptions.RequestException as e:
        # network / HTTP errors
        print("Reverse geocode HTTP error:", e)
        return None
    except Exception as e:
        print("Reverse geocode error:", e)
        return None


# ---------------------------------------------------------------
# GOOGLE DRIVE MUSIC INTEGRATION
# ---------------------------------------------------------------

VIBE_FOLDER_MAP = {
    # granular folder names (use these exact keys when looking up Drive folders)
    "backwater": "1vST4yfCC7RHFtywLAsULWHZ3GdPmIX5d",      
    "beach": "1EbnPGTeVtCaKVT6VmWSCc3MDH_esd06a",   
    "city": "18asMRW6OeTRjTGcKquYkAyUakTfdvgwa",          
    "coastal-city": "14eyJ1LRP4feBueBjk8eIjwcrn3HaLtRY",  
    "cultural": "1ZyKQ95kvG0gaDncx7yujEgiHrRhIjI6d",
    "forests": "1n70OyFBRdRCr8iRQcQK09VpT2Mq488BE",
    "heritage": "1TSV_j-LWIqVJyLildF8TBf4AMJhWgVvR",
    "hilltown": "1PgTp06mE-7Tw-dUs4LiMu_Vs_9xCFNyZ",       
    "hill-town": "1PgTp06mE-7Tw-dUs4LiMu_Vs_9xCFNyZ",    
    "mountain": "1LNtmW4MB3o2e9Z_fXCpeJ5Esn4Mhd20Y",
    "rural": "1Mp1rOF8FEjNz-F90KmxsgHhk6lzxd4oj",
    "spiritual": "1wuwW1EgQwIDMPJWO9ZoyFs3ac2aG9I2p",
    "temple-town": "1XCIZPvp2XZOziQsXl51O1n8pe0qLtoo5",
    "urban": "1cEZ9dq7mR4I4Baj-mozk21pgNAlTqcMk",
    "intense":"1kHW6WQg2ZeC8UxpueuynIANFALg6jzlX",
    
}

VIBE_ALIAS = {
    # beach-ish
    "beach": "beach",
    "coastal": "coastal-city",      # map generic coastal -> coastal-city folder
    "coastal-city": "coastal-city",
    "backwater": "backwater",

    # mountain-ish / forest / hill
    "mountain": "mountain",
    "hill-town": "hilltown",
    "hilltown": "hilltown",
    "hill town": "hilltown",
    "forest": "forests",
    "forests": "forests",

    # urban-ish / city / cultural / heritage
    "urban": "urban",
    "urban city": "urban",
    "city": "city",
    "city tour": "city",
    "coastal city": "coastal-city",
    "industrial": "urban",
    "cultural": "cultural",
    "heritage": "heritage",

    # others
    "rural": "rural",
    "spiritual": "spiritual",
    "temple-town": "temple-town",
    "temple town": "temple-town",
}

def normalize_vibe_label(label: str) -> str:
    """Normalize model's label into one of our 3 main keys if possible."""
    key = label.lower().strip()
    key = key.replace("_", " ")
    return VIBE_ALIAS.get(key, key)  # fall back to itself if not aliased


SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
SERVICE_ACCOUNT_FILE = "C:\\Users\\ASUS\\Downloads\\geotuness\\geotunesss\\geotunes-481516-811a7cd06d9a.json"


@st.cache_resource
def get_drive_service():
    """Create a Google Drive API service client (cached)."""
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    service = build("drive", "v3", credentials=creds)
    return service



@st.cache_data
def list_songs_for_vibe(vibe_label: str):
    service = get_drive_service()

    main_key = normalize_vibe_label(vibe_label)
    folder_id = VIBE_FOLDER_MAP.get(main_key)

    if not folder_id:
        return []

    query = f"'{folder_id}' in parents and trashed = false"

    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType)"
    ).execute()

    files = results.get("files", [])
    songs = []

    for f in files:
        file_id = f["id"]
        name = f["name"]

        # Download file bytes
        request = service.files().get_media(fileId=file_id)
        file_stream = io.BytesIO()
        downloader = MediaIoBaseDownload(file_stream, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()

        file_stream.seek(0)

        songs.append({"name": name, "bytes": file_stream.read()})

    return songs





# -------------------------------
# BACKGROUND IMAGE
# -------------------------------
def set_background_image(image_file: str, offset_y: str = "0px"):
    """
    Sets the background image with a vertical offset so that
    the logo inside the image can be visually aligned at the top.
    offset_y is like "0px", "-120px", "50px", etc.
    """
    try:
        with open(image_file, "rb") as img:
            encoded = base64.b64encode(img.read()).decode()

        st.markdown(
            f"""
            <style>
            .stApp {{
                background-color: #fdf0d8;
                background-image: url("data:image/png;base64,{encoded}");
                background-repeat: no-repeat;
                background-size: cover;
                background-position: center {offset_y};
                background-attachment: fixed;

                animation: bgZoom 20s ease-in-out infinite alternate;
            }}

            @keyframes bgZoom {{
                0% {{
                    background-size: 100%;
                }}
                100% {{
                    background-size: 110%;
                }}
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
    except Exception as e:
        st.error(f"Background image error: {e}")


# -------------------------------
# LOAD MODEL
# -------------------------------
vibe_model = None
encoder = None
emoji_map = {}

try:
    with open("vibe_knn_model.pkl", "rb") as f:
        bundle = pickle.load(f)
        vibe_model = bundle.get("model", None)
        encoder = bundle.get("encoder", None)

    emoji_map = {
        "backwater": "Backwater ",
        "beach": "Beach ",
        "city": "City Tour ",
        "coastal": "Coastal Breeze ",
        "coastal-city": "Coastal City ",
        "cultural": "Cultural Heritage ",
        "desert": "Desert ",
        "forest": "Forest ",
        "heritage": "Heritage Site ",
        "hill-town": "Hill Town ",
        "industrial": "Industrial Zone ",
        "mountain": "Mountain ",
        "pilgrim-town": "Pilgrim Town ",
        "rural": "Rural Countryside ",
        "spiritual": "Spiritual Place ",
        "temple-town": "Temple Town ",
        "urban": "Urban City ",
    }
except Exception as e:
    print(f"Failed to load vibe_knn_model.pkl: {e}")
    vibe_model = None
    encoder = None
    emoji_map = {}


# -------------------------------
# VIBE PREDICTION
# -------------------------------
def predict_vibe(lat, lon):
    if vibe_model is None or encoder is None:
        st.error("KNN model or encoder could not be loaded.")
        return None
    try:
        coords = np.radians([[float(lat), float(lon)]])
        pred_numeric = vibe_model.predict(coords)[0]
        label_name = encoder.inverse_transform([pred_numeric])[0]
        vibe_display = emoji_map.get(label_name.lower(), label_name)
        return {"label": label_name, "display": vibe_display}
    except Exception as e:
        st.error(f"Prediction error: {e}")
        return None
    
# -------------------------------
# Detect Weather
# -------------------------------

import requests

API_KEY = "d88b94316ad15e3f1cc9e8457ce34d3b"

def get_current_weather(lat, lon):
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={API_KEY}&units=metric"
    response = requests.get(url)
    data = response.json()

    weather_info = {
        "temperature": data["main"]["temp"],
        "humidity": data["main"]["humidity"],
        "wind_speed": data["wind"]["speed"],
        "weather_main": data["weather"][0]["main"],  # Rain, Clear, Clouds etc.
        "description": data["weather"][0]["description"]
    }

    return weather_info

def normalize_weather(main_weather):
    main_weather = main_weather.lower()

    # Clear / Sunny
    if "clear" in main_weather:
        return "sunny"

    # Clouds
    elif "cloud" in main_weather:
        return "cloudy"

    # Rain types
    elif "rain" in main_weather or "drizzle" in main_weather:
        return "rainy"

    # Thunderstorm
    elif "thunder" in main_weather:
        return "storm"

    # Snow / cold
    elif "snow" in main_weather:
        return "cold"

    # Fog / Mist / Haze / Smoke (visibility issues)
    elif (
        "mist" in main_weather or
        "fog" in main_weather or
        "haze" in main_weather or
        "smoke" in main_weather
    ):
        return "foggy"

    # Dust / Sand / Ash (dry harsh weather)
    elif (
        "dust" in main_weather or
        "sand" in main_weather or
        "ash" in main_weather
    ):
        return "dry"

    # Extreme wind conditions
    elif "squall" in main_weather:
        return "windy"

    # Tornado / extreme
    elif "tornado" in main_weather:
        return "extreme"

    else:
        return "unknown"

# -------------------------------
# WEATHER TO MOOD MAPPING
# -------------------------------

WEATHER_TO_MOOD = {
    "sunny": "energetic",
    "cloudy": "calm",
    "rainy": "romantic",
    "storm": "intense",
    "foggy": "thoughtful",
    "cold": "cozy",
    "dry": "tired",
    "windy": "free",
    "extreme": "tense",
    "unknown": "neutral"
}

def get_mood_from_weather(weather_category):
    return WEATHER_TO_MOOD.get(weather_category, "calm")

# -------------------------------
# LOGIN CHECK
# -------------------------------
def login(username, password):
    if username != ADMIN_USERNAME:
        return False
    
    return bcrypt.checkpw(password.encode(), ADMIN_PASSWORD_HASH)


# -------------------------------
# CUSTOM CSS
# -------------------------------
def apply_custom_css(logged_in):
    if not logged_in:
        # LOGIN PAGE STYLES
        st.markdown(
            """
            <style>
            /* Disable scrolling on login page */
            .stApp {
                overflow: hidden;
            }

            /* Main login block: full width, left aligned, margin top */
            .main-block {
                width: 90%;
                max-width: 600px;
                display: flex;
                flex-direction: column;
                align-items: flex-start !important;
                justify-content: flex-start;
                margin-top: 150px;  /* controls gap below the logo in bg */
                margin-left: 0px !important;
            }

            /* Title left aligned, shifted more to the left */
            .login-title {
                width: 100%;
                text-align: left !important;
                font-size: 2.8rem;
                font-weight: 800;
                color: #222222;
                margin: 0 0 20px 0;
                white-space: nowrap;
                margin-left: -140px !important;  /* shift title further left */
            }

            /* Login card */
            .login-box {
                background: rgba(255, 255, 255, 0.92);
                padding: 24px 26px;
                border-radius: 16px;
                width: 100%;
                box-shadow: 0px 4px 18px rgba(0, 0, 0, 0.18);
                text-align: left;
                font-family: "Georgia", serif;
            }

            .stTextInput>div>div>input {
                border-radius: 10px !important;
                background: #ffffff !important;
            }

            .stButton>button {
                background: #d88a3d !important;
                color: #ffffff !important;
                font-weight: 700;
                width: 120px;
                border-radius: 10px;
                height: 45px;
                border: none;
                margin-top: 8px;
            }

            .stButton>button:hover {
                background: #c17228 !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
    else:
        # INSIDE PAGES STYLES + FLOATING SIDEBAR
        st.markdown(
            """
            <style>
            /* ---------- FLOATING SIDEBAR BOX (SOFT BEIGE) ---------- */
            [data-testid="stSidebar"] {
                background: rgba(255, 245, 235, 0.96) !important;
                border-radius: 20px !important;
                margin-top: 30px !important;
                margin-left: 20px !important;
                margin-bottom: 30px !important;
                padding: 20px 18px !important;
                width: 260px !important;
                height: auto !important;
                box-shadow: 0px 6px 30px rgba(110, 56, 11, 0.28) !important;
                border: 2px solid rgba(166, 90, 26, 0.35) !important;
                position: fixed !important;   /* floating effect */
                top: 60px !important;
                left: 15px !important;
                z-index: 999 !important;
            }

            /* Avoid sidebar content being cramped */
            [data-testid="stSidebar"] > div {
                padding: 0 !important;
            }

            /* Sidebar text + fonts */
            [data-testid="stSidebar"] * {
                color: #5a3213 !important;
                font-family: "Georgia", serif !important;
            }

            /* "Navigation" title */
            [data-testid="stSidebar"] h2 {
                font-weight: 800;
                font-size: 1.1rem;
                letter-spacing: 0.03em;
                margin-bottom: 0.75rem;
            }

            /* Radio group styling */
            [data-testid="stSidebar"] div[role="radiogroup"] label {
                display: flex;
                align-items: center;
                gap: 6px;
                padding: 8px 12px;
                border-radius: 999px;
                transition: background 0.25s ease, transform 0.1s ease;
            }

            [data-testid="stSidebar"] div[role="radiogroup"] label:hover {
                background: rgba(255, 230, 200, 0.7);
                transform: translateX(4px);
            }

            /* Radio bullet accent */
            [data-testid="stSidebar"] input[type="radio"] {
                accent-color: #d98c47;
            }

            /* ---------- MAIN CARD / BUTTON STYLES ---------- */
            .card {
                background: rgba(255, 245, 235, 0.85);
                border-radius: 20px;
                padding: 30px;
                margin: 20px auto;
                max-width: 900px;
                box-shadow: 0 10px 30px rgba(110, 56, 11, 0.4);
                color: #5a3213;
                font-weight: bold;
                font-size: 1.1em;
                font-family: 'Georgia', serif;
            }

            a, a:hover {
                color: #a45c11 !important;
                text-decoration: none;
                font-weight: bold;
            }

            .stButton>button {
                background: linear-gradient(135deg, #d98c47, #bc6c4c);
                color: white;
                border:none;
                font-weight: bold;
                font-size: 1.2em;
                height: 48px;
                border-radius: 15px;
                box-shadow: 0 5px 18px rgba(135, 71, 15, 0.6);
                transition: all 0.3s ease;
            }

            .stButton>button:hover {
                background: linear-gradient(135deg, #bc6c4c, #d98c47);
                transform: translateY(-3px);
                box-shadow: 0 10px 30px rgba(135, 71, 15, 0.8);
            }

            .stTextInput>div>div>input {
                background: rgba(255, 245, 235, 0.9) !important;
                color: #5a3213 !important;
                border-radius: 15px !important;
                border: 2px solid #c88a40 !important;
                font-weight: bold;
                font-size: 1.05em;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )


# -------------------------------
# MAIN APP
# -------------------------------
def main():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "predicted_vibe" not in st.session_state:
        st.session_state.predicted_vibe = None

    logged_in = st.session_state.logged_in

    # --------- LOGIN PAGE ---------
    if not logged_in:
        set_background_image("login_page.png", offset_y="-120px")
        apply_custom_css(logged_in=False)

        st.markdown('<div class="main-block">', unsafe_allow_html=True)
        st.markdown(
            '<div class="login-title">🎶 Personalized Music Recommendation System</div>',
            unsafe_allow_html=True,
        )

        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Login"):
            if login(username, password):
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("Invalid username or password")

        st.markdown("</div>", unsafe_allow_html=True)
        return

    # --------- AFTER LOGIN (FULL WEBSITE) ---------
    set_background_image("inside_pages.png", offset_y="0px")
    apply_custom_css(logged_in=True)
    st.markdown("""
    <style>

    [data-testid="stAudioControls"] {
        display: none !important;
    }

    /* NEW FIX — hides Streamlit's internal grey overlay */
    [data-testid="audio-controls"] {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        width: 0 !important;
        height: 0 !important;
    }

    audio::-internal-media-controls-overflow-button {
        display: none !important;
    }
    audio::-webkit-media-controls-panel {
        background: transparent !important;
    }

    </style>
    """, unsafe_allow_html=True)
    #  Improved Audio Player UI
    st.markdown("""
    <style>

    .track-card {
        background: rgba(255, 245, 235, 0.88);
        padding: 18px 22px;
        border-radius: 16px;
        margin-bottom: 25px;
        box-shadow: 0 4px 14px rgba(120, 60, 20, 0.25);
        transition: transform .2s ease, box-shadow .2s ease;
    }

    .track-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 8px 22px rgba(120, 60, 20, 0.35);
    }

    .track-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #6b3c1b;
        margin-bottom: 10px;
        font-family: "Georgia";
    }

    .audio-wrapper {
        border-radius: 12px !important;
        overflow: hidden !important;
    }

    </style>
    """, unsafe_allow_html=True)

    # SIDEBAR
    menu = st.sidebar.radio(
    "Navigation",
    [
        "Home",
        "Location",
        "Geo-Tunes",
        "Weather",
        "Atmos-Tunes",
        "Membership",
        "Logout"
    ]
)
    # CARD DECORATOR
    def card_wrap(func):
        def wrapped():
            #st.markdown('<div class="card">', unsafe_allow_html=True)
            func()
            st.markdown("</div>", unsafe_allow_html=True)
        return wrapped

    @card_wrap
    def page_home():
        st.markdown("### Welcome to Your Music Journey!")
        st.write(
            "Discover music that matches your vibe based on your location. "
            "Use the sidebar to detect your location and generate personalized playlists."
        )
        st.image(
            "audio.jpg",
            caption="Explore the world through music!",
            width=None,
        )
        st.markdown("Features:")
        st.markdown("-  Location-based vibe detection")
        st.markdown("-  Google Drive–based playlists")
        st.markdown("-  Multi-language / multi-vibe support")

    @card_wrap
    def page_location():
        st.markdown("###  Detect Your Location & Vibe")
        st.write(
            "We'll attempt to use your browser's Geolocation API (you'll be prompted to allow). "
            "If you deny permission or it's unavailable, please enter coordinates manually."
        )

        col1, col2 = st.columns(2)

        # LEFT IMAGE SECTION
        with col1:
            st.image(
                "https://images.unsplash.com/photo-1524661135-423995f22d0b"
                "?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80",
                caption="Location Detection",
                width=None,
            )

        # RIGHT SIDE — LOCATION LOGIC
        with col2:
            loc = get_geolocation()

            lat = None
            lon = None

            if isinstance(loc, dict) and "coords" in loc:
                coords = loc["coords"]
                lat = coords.get("latitude")
                lon = coords.get("longitude")

            # -------------------------------
            # CASE 1: Browser geolocation SUCCESS
            # -------------------------------
            if lat is not None and lon is not None:

                st.success(f"Browser geolocation: {lat}, {lon}")

                geo = reverse_geocode(lat, lon)

                if geo:
                    full_addr = geo.get("full_address", "Unknown")
                    components = geo.get("components", {})

                    # Expand fallback logic for street detection
                    neighbourhood = (
                        components.get("neighbourhood")
                        or components.get("suburb")
                        or components.get("quarter")
                        or "Not available"
                    )

                    postcode = (
                        components.get("postcode")
                        or components.get("postcode:source")
                        or "Not available"
                    )

                    city = (
                        components.get("city")
                        or components.get("town")
                        or components.get("village")
                        or components.get("municipality")
                        or "Not available"
                    )

                    state = components.get("state") or "Not available"
                    country = components.get("country") or "Not available"

                    st.info(f"""
                *Full Address:*  
                {full_addr}

                ### Detailed Address:
                - *Neighbourhood:* {neighbourhood}
                - *Postcode:* {postcode}
                - *City:* {city}
                - *State:* {state}
                - *Country:* {country}
                """)


                else:
                    st.warning("Could not fetch address from coordinates.")

                # Predict vibe
                vibe = predict_vibe(lat, lon)
                st.session_state.predicted_vibe = vibe

                if vibe:
                    st.info(f"Predicted Vibe: {vibe['display']}")
                    st.caption(f"(raw label: {vibe['label']})")
                else:
                    st.error("Couldn't predict vibe from browser coordinates.")

            # -------------------------------
            # CASE 2: Browser Geolocation FAILED → Manual Coordinates
            # -------------------------------
            else:
                st.warning(
                    "Browser geolocation unavailable or permission denied. "
                    "Please provide coordinates manually below."
                )

                lat_in = st.text_input("Latitude", key="manual_lat")
                lon_in = st.text_input("Longitude", key="manual_lon")

                if st.button("Predict from Coordinates"):
                    if lat_in and lon_in:

                        geo = reverse_geocode(lat_in, lon_in)
                        if geo:
                            full_addr = geo.get("full_address", "Unknown")
                            components = geo.get("components", {})


                            neighbourhood = (
                                components.get("neighbourhood")
                                or components.get("suburb")
                                or components.get("quarter")
                                or "Not available"
                            )

                            postcode = (
                                components.get("postcode")
                                or components.get("postcode:source")
                                or "Not available"
                            )

                            city = (
                                components.get("city")
                                or components.get("town")
                                or components.get("village")
                                or components.get("municipality")
                                or "Not available"
                            )

                            state = components.get("state") or "Not available"
                            country = components.get("country") or "Not available"

                            st.info(f"""
                        *Full Address:*  
                        {full_addr}

                        ### Detailed Address:
                        - *Neighbourhood:* {neighbourhood}
                        - *Postcode:* {postcode}
                        - *City:* {city}
                        - *State:* {state}
                        - *Country:* {country}
                        """)


                        # Predict vibe
                        vibe = predict_vibe(lat_in, lon_in)
                        st.session_state.predicted_vibe = vibe

                        if vibe:
                            st.info(f"🎵 Predicted Vibe: {vibe['display']}")
                            st.caption(f"(raw label: {vibe['label']})")
                        else:
                            st.error("Couldn't predict vibe from provided coordinates.")

                    else:
                        st.warning("Please enter both latitude & longitude.")

        # Retry button
        if st.button("Retry Browser Geolocation"):
            st.rerun()

    @card_wrap
    def page_playlist():
        st.markdown("### Vibe-Based Songs ")

        vibe = st.session_state.predicted_vibe

        if not vibe:
            st.warning("Please detect location first (go to Location).")
            return

        st.info(f"Using vibe: {vibe['display']} (raw: {vibe['label']})")

        songs = list_songs_for_vibe(vibe["label"])

        if not songs:
            st.error(
                "No songs found in Google Drive for this vibe. "
                "Check your folder mapping or add more tracks."
            )
            return

        st.markdown("####  Recommended Tracks")
        for s in songs:
            st.markdown(f"""
            <div class="track-card">
                <div class="track-title">{s['name']}</div>
                <div class="audio-wrapper">
            """, unsafe_allow_html=True)

            st.audio(s["bytes"])

            st.markdown("</div></div>", unsafe_allow_html=True)

    @card_wrap
    def page_weather():
        st.markdown("### Current Weather")

        loc = get_geolocation()

        lat = None
        lon = None

        if isinstance(loc, dict) and "coords" in loc:
            lat = loc["coords"].get("latitude")
            lon = loc["coords"].get("longitude")

        if lat and lon:
            weather_data = get_current_weather(lat, lon)

            weather_category = normalize_weather(weather_data["weather_main"])
            mood = get_mood_from_weather(weather_category)

            st.session_state.weather_mood = mood

            st.info(f"Temperature: {weather_data['temperature']}°C")
            st.info(f"Weather: {weather_data['description']}")
            st.success(f"Detected Weather Type: {weather_category}")
            st.success(f"Predicted Mood: {mood}")

        else:
            st.warning("Unable to detect location for weather.")

    @card_wrap
    def page_atmos():
        st.markdown("### Atmos-Tunes (Weather Based)")

        mood = st.session_state.get("weather_mood", None)

        if not mood:
            st.warning("Please check Weather section first.")
            return

        st.info(f"Using mood: {mood}")

        # OPTIONAL: If you want mood-based folders,
        # you can create MOOD_FOLDER_MAP.
        # For now we reuse vibe folder logic if names match.

        songs = list_songs_for_vibe(mood)

        if not songs:
            st.error("No songs found for this mood.")
            return

        for s in songs:
            st.markdown(f"""
            <div class="track-card">
                <div class="track-title">{s['name']}</div>
                <div class="audio-wrapper">
            """, unsafe_allow_html=True)

            st.audio(s["bytes"])

            st.markdown("</div></div>", unsafe_allow_html=True)

    @card_wrap
    def page_membership():
        st.markdown("### Premium Membership")
        st.markdown(
            "Upgrade to unlock exclusive features and elevate your music experience!"
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("#### Basic Plan")
            st.markdown("- Access personalized playlists")
            st.markdown("- Normal speed recommendations")
            st.markdown("Price: ₹99 / month")
            if st.button("Choose Basic"):
                st.success("You selected: Basic Membership")

        with col2:
            st.markdown("#### Pro Plan")
            st.markdown("- Everything in Basic")
            st.markdown("- Faster playlist generation")
            st.markdown("- Multi-vibe recommendations")
            st.markdown("Price: ₹199 / month")
            if st.button("Choose Pro"):
                st.success("You selected: Pro Membership")

        with col3:
            st.markdown("#### Ultra Plan")
            st.markdown("- Everything in Pro")
            st.markdown("- Unlimited playlist fetch")
            st.markdown("- Priority support")
            st.markdown("- Custom vibe themes")
            st.markdown("Price: ₹299 / month")
            if st.button("Choose Ultra"):
                st.success("You selected: Ultra Membership")

        st.info("Membership purchase system coming soon!")

    # ROUTING
    if menu == "Home":
        page_home()
    elif menu == "Location":
        page_location()
    elif menu == "Geo-Tunes":
        page_playlist()
    elif menu == "Weather":
        page_weather()
    elif menu == "Atmos-Tunes":
        page_atmos()
    elif menu == "Membership":
        page_membership()
    elif menu == "Logout":
        st.session_state.logged_in = False
        st.session_state.predicted_vibe = None
        st.rerun()


if __name__ == "__main__":
    main()
