import os
import csv
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec

# ================= KONFIGURACJA =================
NTFY_TOPIC = os.getenv("NTFY_TOPIC")
HYDRO_STATION = "Toruń"
SYNOP_STATION = "Toruń"

# Współrzędne geograficzne stacji (Toruń: 53.0138, 18.5984)
LATITUDE = 53.0138
LONGITUDE = 18.5984

# Progi dla Torunia (w cm)
STAN_OSTRZEGAWCZY = 530
STAN_ALARMOWY = 650

HISTORY_FILE = "history.csv"
RAIN_STATE_FILE = "rain_state.txt"
CARD_FILE = "raport.png"
TIMEZONE = ZoneInfo("Europe/Warsaw")
# ===============================================

def fetch_data():
    # 1. Stan wody IMGW
    try:
        r_hydro = requests.get("https://danepubliczne.imgw.pl/api/data/hydro/", timeout=10).json()
        hydro = next((s for s in r_hydro if s.get("stacja", "").strip().lower() == HYDRO_STATION.lower()), None)
    except Exception as e:
        print(f"Błąd hydro: {e}")
        hydro = None

    # 2. Bieżąca pogoda synoptyczna IMGW
    try:
        r_synop = requests.get("https://danepubliczne.imgw.pl/api/data/synop/", timeout=10).json()
        synop = next((s for s in r_synop if s.get("stacja", "").strip().lower() == SYNOP_STATION.lower()), None)
    except Exception as e:
        print(f"Błąd synop: {e}")
        synop = None

    # 3. Prognoza deszczu z wyprzedzeniem 1-2h (Open-Meteo)
    rain_forecast = fetch_rain_forecast()

    return hydro, synop, rain_forecast

def fetch_rain_forecast():
    """Sprawdza prognozę opadów na najbliższe 2 godziny."""
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={LATITUDE}&longitude={LONGITUDE}&"
            f"hourly=precipitation,precipitation_probability,rain,showers&"
            f"timezone=Europe%2FWarsaw&forecast_days=1"
        )
        res = requests.get(url, timeout=10).json()
        hourly = res.get("hourly", {})
        times = hourly.get("time", [])
        precip = hourly.get("precipitation", [])
        prob = hourly.get("precipitation_probability", [])

        now = datetime.now(TIMEZONE)
        
        # Szukamy opadów w oknie 20 - 100 minut od teraz
        for t_str, p_val, prob_val in zip(times, precip, prob):
            t = datetime.fromisoformat(t_str).replace(tzinfo=TIMEZONE)
            diff_mins = (t - now).total_seconds() / 60
            
            # Jeśli deszcz prognozowany jest w przedziale za ~30-90 min
            if 15 <= diff_mins <= 105:
                if (p_val and p_val >= 0.1) or (prob_val and prob_val >= 60):
                    return {
                        "time": t.strftime("%H:%M"),
                        "amount": p_val or 0.0,
                        "prob": prob_val or 0,
                        "mins_left": int(diff_mins)
                    }
    except Exception as e:
        print(f"Błąd pobierania prognozy deszczu: {e}")
    return None

def get_last_recorded_level():
    if not os.path.exists(HISTORY_FILE):
        return None
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            if reader:
                return float(reader[-1]["stan_wody"])
    except Exception:
        pass
    return None

def should_send_rain_alert(rain_info):
    """Zapobiega powtarzaniu alertu o ten sam deszcz co 30 minut."""
    if not rain_info:
        return False
    
    target_time = rain_info["time"]
    today_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    state_key = f"{today_str}_{target_time}"

    if os.path.exists(RAIN_STATE_FILE):
        with open(RAIN_STATE_FILE, "r", encoding="utf-8") as f:
            last_alerted = f.read().strip()
            if last_alerted == state_key:
                return False  # Już ostrzegaliśmy przed tą godziną opadu

    # Zapisujemy nowy stan
    with open(RAIN_STATE_FILE, "w", encoding="utf-8") as f:
        f.write(state_key)
    return True

def update_history(hydro):
    if not hydro or not hydro.get("stan_wody"):
        return
    now_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M")
    stan = float(hydro.get("stan_wody"))
    temp_w = hydro.get("temperatura_wody")
    temp_w_val = float(temp_w) if temp_w and temp_w != "null" else ""

    file_exists = os.path.exists(HISTORY_FILE)
    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["datetime", "stan_wody", "temp_wody"])
        writer.writerow([now_str, stan, temp_w_val])

def generate_graphic_card(hydro, synop, rain_forecast):
    stan = float(hydro.get("stan_wody", 0)) if hydro and hydro.get("stan_wody") else 0
    temp_w = hydro.get("temperatura_wody", "-") if hydro else "-"
    rzeka = hydro.get("rzeka", "Wisła") if hydro else "Wisła"
    data_pomiaru = hydro.get("stan_wody_data_pomiaru", datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M")) if hydro else ""

    temp_powietrza = synop.get("temperatura", "-") if synop else "-"
    wiatr = synop.get("predkosc_wiatru", "-") if synop else "-"
    opad_biezacy = synop.get("suma_opadu", "-") if synop else "-"
    cisnienie = synop.get("cisnienie", "-") if synop else "-"

    if stan >= STAN_ALARMOWY:
        status_color = "#EF4444"
        status_text = "ALARM POWODZIOWY"
    elif stan >= STAN_OSTRZEGAWCZY:
        status_color = "#F97316"
        status_text = "STAN OSTRZEGAWCZY"
    else:
        status_color = "#10B981"
        status_text = "STAN W NORMIE"

    fig = plt.figure(figsize=(10, 6.5), dpi=180, facecolor="#0B132B")
    gs = gridspec.GridSpec(3, 3, height_ratios=[1.1, 1.2, 2.2], figure=fig)

    # 1. Nagłówek
    ax_head = fig.add_subplot(gs[0, :])
    ax_head.set_facecolor("#1C2541")
    ax_head.axis("off")
    ax_head.text(0.03, 0.65, f"RAPORT HYDRO-METEO: {rzeka.upper()} ({HYDRO_STATION.upper()})", fontsize=15, fontweight="bold", color="#FFFFFF")
    ax_head.text(0.03, 0.22, f"Posterunek: {HYDRO_STATION} • Odczyt IMGW: {data_pomiaru}", fontsize=10, color="#9CA3AF")
    ax_head.text(0.97, 0.50, status_text, fontsize=11, fontweight="bold", color="#FFFFFF",
                 ha="right", va="center",
                 bbox=dict(boxstyle="round,pad=0.55", facecolor=status_color, edgecolor="none"))

    # 2. Kafelek 1: Stan Wody
    ax_k1 = fig.add_subplot(gs[1, 0])
    ax_k1.set_facecolor("#1C2541")
    ax_k1.axis("off")
    ax_k1.text(0.5, 0.80, "POZIOM WODY", fontsize=9.5, fontweight="bold", color="#9CA3AF", ha="center")
    ax_k1.text(0.5, 0.44, f"{int(stan)} cm", fontsize=22, fontweight="bold", color="#38BDF8", ha="center")
    ax_k1.text(0.5, 0.16, f"Temp. wody: {temp_w} °C", fontsize=9, color="#CBD5E1", ha="center")

    # 3. Kafelek 2: Pogoda i Ostrzeżenie o Opadach
    ax_k2 = fig.add_subplot(gs[1, 1])
    ax_k2.set_facecolor("#1C2541")
    ax_k2.axis("off")
    ax_k2.text(0.5, 0.80, "POGODA / OPADY", fontsize=9.5, fontweight="bold", color="#9CA3AF", ha="center")
    ax_k2.text(0.5, 0.44, f"{temp_powietrza} °C", fontsize=22, fontweight="bold", color="#FBBF24", ha="center")
    
    if rain_forecast:
        rain_sub = f"🌧️ Deszcz ok. {rain_forecast['time']} ({rain_forecast['amount']} mm)"
        ax_k2.text(0.5, 0.16, rain_sub, fontsize=8.5, fontweight="bold", color="#38BDF8", ha="center")
    else:
        ax_k2.text(0.5, 0.16, f"Opad biezacy: {opad_biezacy} mm", fontsize=9, color="#CBD5E1", ha="center")

    # 4. Kafelek 3: Wiatr i Ciśnienie
    ax_k3 = fig.add_subplot(gs[1, 2])
    ax_k3.set_facecolor("#1C2541")
    ax_k3.axis("off")
    ax_k3.text(0.5, 0.80, "WIATR / CIŚNIENIE", fontsize=9.5, fontweight="bold", color="#9CA3AF", ha="center")
    ax_k3.text(0.5, 0.44, f"{wiatr} m/s", fontsize=22, fontweight="bold", color="#A78BFA", ha="center")
    ax_k3.text(0.5, 0.16, f"Ciśnienie: {cisnienie} hPa", fontsize=9, color="#CBD5E1", ha="center")

    for ax in [ax_head, ax_k1, ax_k2, ax_k3]:
        rect = plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, fill=False, edgecolor="#334155", linewidth=1.2, clip_on=False)
        ax.add_patch(rect)

    # 5. Wykres trendu
    ax_plot = fig.add_subplot(gs[2, :])
    ax_plot.set_facecolor("#1C2541")

    dates, levels = [], []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    d = datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M")
                    l = float(row["stan_wody"])
                    dates.append(d)
                    levels.append(l)
                except Exception:
                    continue

    if dates:
        dates = dates[-48:]
        levels = levels[-48:]
        ax_plot.plot(dates, levels, color="#38BDF8", linewidth=2.6, marker="o", markersize=3.5)
        min_y = min(levels) - 5
        ax_plot.fill_between(dates, levels, min_y, color="#38BDF8", alpha=0.18)

        ax_plot.scatter([dates[-1]], [levels[-1]], color="#F43F5E", s=50, zorder=5)
        ax_plot.annotate(f"Aktualnie: {int(levels[-1])} cm", 
                         xy=(dates[-1], levels[-1]), 
                         xytext=(-80, 10), textcoords="offset points",
                         color="#FFFFFF", fontsize=8.5, fontweight="bold",
                         bbox=dict(boxstyle="round,pad=0.3", facecolor="#F43F5E", edgecolor="none"),
                         arrowprops=dict(arrowstyle="->", color="#F43F5E", lw=1.2))

        ax_plot.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m\n%H:%M"))
        ax_plot.tick_params(colors="#9CA3AF", labelsize=8)
        ax_plot.grid(True, linestyle="--", alpha=0.25, color="#64748B")
        ax_plot.set_ylabel("Poziom [cm]", color="#9CA3AF", fontsize=9)
    else:
        ax_plot.text(0.5, 0.5, "Pierwszy pomiar – zbieranie historii...", ha="center", va="center", color="#9CA3AF")

    for spine in ax_plot.spines.values():
        spine.set_edgecolor("#334155")
        spine.set_linewidth(1.2)

    plt.subplots_adjust(hspace=0.32, wspace=0.18, left=0.05, right=0.95, top=0.95, bottom=0.10)
    plt.savefig(CARD_FILE, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()

def send_ntfy(title, tags="chart_with_upwards_trend,droplet", priority="default"):
    if not NTFY_TOPIC:
        raise ValueError("Brak sekretu NTFY_TOPIC!")

    url = f"https://ntfy.sh/{NTFY_TOPIC}"

    if os.path.exists(CARD_FILE):
        with open(CARD_FILE, "rb") as img:
            requests.post(
                url,
                data=img,
                headers={
                    "Title": title.encode("utf-8"),
                    "Filename": "raport.png",
                    "Tags": tags,
                    "Priority": priority
                },
                timeout=15
            )

if __name__ == "__main__":
    now_pl = datetime.now(TIMEZONE)
    hydro_data, synop_data, rain_data = fetch_data()
    
    if hydro_data and hydro_data.get("stan_wody"):
        current_stan = float(hydro_data.get("stan_wody"))
        last_stan = get_last_recorded_level()

        # Generujemy kartę graficzną i zapisujemy stan
        update_history(hydro_data)
        generate_graphic_card(hydro_data, synop_data, rain_data)

        # 1. Raport poranny (06:00)
        is_morning = (now_pl.hour == 6 and now_pl.minute < 35)
        # 2. Zmiana poziomu wody
        level_changed = (last_stan is None or current_stan != last_stan)
        # 3. Stan ostrzegawczy / alarmowy
        is_high_water = (current_stan >= STAN_OSTRZEGAWCZY)
        # 4. Nowy alert o deszczu za ~1h
        is_rain_alert = should_send_rain_alert(rain_data)

        temp_str = synop_data.get('temperatura', '?') if synop_data else '?'

        if is_rain_alert:
            print(f"Wykryto nadchodzący deszcz o {rain_data['time']}! Wysyłam ostrzeżenie.")
            title = f"☔ [DESZCZ OK. {rain_data['time']}] Opad: {rain_data['amount']} mm | {current_stan} cm"
            send_ntfy(title, tags="umbrella,cloud_with_rain", priority="high")

        elif is_morning:
            print("Wysyłam raport poranny (06:00)...")
            title = f"[PORANNY] Raport {HYDRO_STATION}: {current_stan} cm | {temp_str}°C"
            send_ntfy(title, tags="partly_sunny,droplet", priority="default")

        elif level_changed:
            diff = f" ({'+' if current_stan > last_stan else ''}{int(current_stan - last_stan)} cm)" if last_stan is not None else ""
            print(f"Zmiana stanu wody: {last_stan} -> {current_stan} cm.")
            title = f"[ZMIANA{diff}] Raport {HYDRO_STATION}: {current_stan} cm | {temp_str}°C"
            send_ntfy(title, tags="chart_with_upwards_trend,droplet", priority="default")

        elif is_high_water:
            print("Stan wysoki! Wysyłam alert.")
            title = f"🚨 [ALERT WODNY] {HYDRO_STATION}: {current_stan} cm!"
            send_ntfy(title, tags="warning,droplet", priority="urgent")

        else:
            print(f"Brak zmian (stan: {current_stan} cm), brak deszczu. Powiadomienie pominięte.")
