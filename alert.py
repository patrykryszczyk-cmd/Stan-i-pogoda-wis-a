import os
import csv
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests

from playwright.sync_api import sync_playwright

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec

# ==============================================================================
# KONFIGURACJA POSTERUNKU (WOPR TORUŃ - WISŁA)
# ==============================================================================
NTFY_TOPIC = os.getenv("NTFY_TOPIC")
HYDRO_STATION_ID = "153180090"  # Wisła - Toruń
URL_HYDRO = f"https://hydro.imgw.pl/#/station/hydro/{HYDRO_STATION_ID}"
SYNOP_STATION = "Toruń"

LATITUDE = 53.0078
LONGITUDE = 18.6075

STAN_SNW = 68
STAN_BEZPIECZNY = 120
STAN_OSTRZEGAWCZY = 530
STAN_ALARMOWY = 650

HISTORY_FILE = "history.csv"
LAST_LEVEL_FILE = "last_level.txt"
RAIN_STATE_FILE = "rain_state.txt"
MORNING_STATE_FILE = "morning_state.txt"
CARD_FILE = "raport.png"
TIMEZONE = ZoneInfo("Europe/Warsaw")
# ==============================================================================

def scrape_hydro_with_browser():
    stan = None
    temp_woda = None
    dt_pomiaru_str = None
    flow_q = None
    history_records = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        def handle_response(response):
            nonlocal stan, temp_woda, dt_pomiaru_str, flow_q, history_records
            try:
                if "station-data" in response.url:
                    data = response.json()
                    states = data.get("waterStateRecords", [])
                    if states:
                        states.sort(key=lambda x: x["date"])
                        latest = states[-1]
                        stan = float(latest["value"])
                        raw_dt = latest["date"]
                        dt_obj = datetime.fromisoformat(raw_dt.replace("Z", "+00:00")).astimezone(TIMEZONE)
                        dt_pomiaru_str = dt_obj.strftime("%d.%m.%Y, %H:%M")

                        for r in states[-60:]:
                            r_dt = datetime.fromisoformat(r["date"].replace("Z", "+00:00")).astimezone(TIMEZONE)
                            history_records.append((r_dt.strftime("%Y-%m-%d %H:%M"), float(r["value"])))

                    temps = data.get("waterTemperatureRecords", [])
                    if temps:
                        temps.sort(key=lambda x: x["date"])
                        temp_woda = float(temps[-1]["value"])

                    discharges = data.get("dischargeRecords", [])
                    if discharges:
                        discharges.sort(key=lambda x: x["date"])
                        flow_q = int(round(float(discharges[-1]["value"])))
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            print(f"[BROWSER] Pobieranie {URL_HYDRO}...")
            page.goto(URL_HYDRO, wait_until="networkidle", timeout=35000)
            page.wait_for_timeout(3000)

            if stan is None:
                body_text = page.inner_text("body")
                match_stan = re.search(r"(\d+)\s*cm", body_text)
                if match_stan:
                    stan = float(match_stan.group(1))

                match_temp = re.search(r"(\d+[\.,]\d+)\s*°C", body_text)
                if match_temp:
                    temp_woda = float(match_temp.group(1).replace(",", "."))

        except Exception as e:
            print(f"[BROWSER BŁĄD] {e}")
        finally:
            browser.close()

    if history_records:
        with open(HISTORY_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["datetime", "stan_wody", "temp_wody"])
            for h_date, h_val in history_records:
                writer.writerow([h_date, h_val, temp_woda or ""])

    if stan is None:
        stan = 78.0
    if temp_woda is None:
        temp_woda = 21.0
    if not dt_pomiaru_str:
        dt_pomiaru_str = datetime.now(TIMEZONE).strftime("%d.%m.%Y, %H:%M")

    return {
        "stan": stan,
        "temp_w": temp_woda,
        "dt_str": dt_pomiaru_str,
        "q": flow_q,
        "stacja": "Toruń",
        "rzeka": "Wisła"
    }

def fetch_synop_data():
    try:
        r = requests.get("https://danepubliczne.imgw.pl/api/data/synop/", timeout=10).json()
        for s in r:
            if s.get("stacja", "").strip().lower() == SYNOP_STATION.lower():
                return s
    except Exception as e:
        print(f"[OSTRZEŻENIE] synop: {e}")
    return {}

def fetch_meteo_forecast():
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={LATITUDE}&longitude={LONGITUDE}&"
            f"hourly=precipitation,precipitation_probability,wind_speed_10m,wind_gusts_10m,wind_direction_10m&"
            f"daily=sunrise,sunset&timezone=Europe%2FWarsaw&forecast_days=2"
        )
        return requests.get(url, timeout=10).json()
    except Exception as e:
        print(f"[OSTRZEŻENIE] open-meteo: {e}")
        return {}

def analyze_rain_alert(meteo_data):
    if not meteo_data or "hourly" not in meteo_data:
        return None
    hourly = meteo_data["hourly"]
    times = hourly.get("time", [])
    precip = hourly.get("precipitation", [])
    prob = hourly.get("precipitation_probability", [])
    now = datetime.now(TIMEZONE)

    for t_str, p_val, prob_val in zip(times, precip, prob):
        t = datetime.fromisoformat(t_str).replace(tzinfo=TIMEZONE)
        diff_mins = (t - now).total_seconds() / 60
        # Wykrywa deszcz za 20 - 95 minut
        if 20 <= diff_mins <= 95:
            if (p_val and p_val >= 0.2) or (prob_val and prob_val >= 60):
                return {
                    "time": t.strftime("%H:%M"),
                    "amount": round(p_val or 0.0, 1),
                    "prob": prob_val or 0
                }
    return None

def calculate_flow(level, raw_q):
    if raw_q:
        return raw_q
    if level <= 0:
        return 200
    q = 200 + (level ** 1.35) * 0.95
    return int(round(q, -1))

def analyze_tactical_data(hydro, synop, meteo):
    stan = hydro["stan"]
    temp_woda = hydro["temp_w"]
    data_str = hydro["dt_str"]
    godzina_str = data_str.split(", ")[-1] if ", " in data_str else data_str[-5:]

    flow_q = calculate_flow(stan, hydro["q"])
    if flow_q < 450:
        flow_note = "nurt umiarkowany"
    elif flow_q < 1200:
        flow_note = "nurt wartki"
    else:
        flow_note = "BARDZO SILNY UCIĄG"

    if stan < STAN_SNW:
        nav_risk = "(!) Odsłonięte ostrogi i mielizny"
        nav_risk_color = "#EF4444"
    elif stan < STAN_BEZPIECZNY:
        nav_risk = "(!) Odsłonięte ostrogi i mielizny"
        nav_risk_color = "#F59E0B"
    elif stan >= STAN_OSTRZEGAWCZY:
        nav_risk = "(!) Niesione pnie, wiry, zalane główki"
        nav_risk_color = "#EF4444"
    else:
        nav_risk = "Tor wodny: Głębokość żeglowna"
        nav_risk_color = "#10B981"

    if temp_woda < 10.0:
        soi_text = "ŚOI: BEZWZGLĘDNIE SUCHAR"
        soi_color = "#EF4444"
        hypo_text = "Hipotermia: < 15-30 min!"
    elif temp_woda < 15.0:
        soi_text = "ŚOI: Suchar / Pianka 5mm+"
        soi_color = "#F59E0B"
        hypo_text = "Okno hipotermii: ok. 1-2h"
    elif temp_woda < 19.0:
        soi_text = "ŚOI: Pianka 3-5mm / Kamizelka"
        soi_color = "#FBBF24"
        hypo_text = "Okno hipotermii: ok. 2-6h"
    else:
        soi_text = "ŚOI: Pianka 3mm / Asekuracja"
        soi_color = "#34D399"
        hypo_text = "Okno hipotermii: > 6-12h"

    temp_pow = float(synop.get("temperatura", 20.0)) if synop else 20.0
    wiatr_v = float(synop.get("predkosc_wiatru", 3.0)) if synop else 3.0
    kierunek_kat = float(synop.get("kierunek_wiatru", 290.0)) if synop else 290.0
    cisnienie = synop.get("cisnienie", "1016") if synop else "1016"

    porywy_v = int(round(wiatr_v * 1.6))
    if meteo and "hourly" in meteo:
        gusts = meteo["hourly"].get("wind_gusts_10m", [])
        if gusts:
            porywy_v = max(int(round(float(gusts[0]))), porywy_v)

    if 240 <= kierunek_kat <= 360 or 0 <= kierunek_kat <= 20:
        if wiatr_v >= 7 or porywy_v >= 12:
            wave_text = "~ SZKWAŁ POD PRĄD (Fala >0.8m)"
            wave_color = "#EF4444"
        else:
            wave_text = "~ Wiatr pod prąd (krótka fala)"
            wave_color = "#38BDF8"
    else:
        wave_text = "~ Wiatr z prądem (szybki dryf)"
        wave_color = "#34D399"

    sunset_str = "20:00"
    dusk_str = "20:38"
    if meteo and "daily" in meteo:
        daily_sunset = meteo["daily"].get("sunset", [])
        if daily_sunset:
            dt_sunset = datetime.fromisoformat(daily_sunset[0]).replace(tzinfo=TIMEZONE)
            sunset_str = dt_sunset.strftime("%H:%M")
            dusk_str = (dt_sunset + timedelta(minutes=38)).strftime("%H:%M")

    if stan >= STAN_ALARMOWY:
        status_text = "ALARM POWODZIOWY"
        status_bg = "#DC2626"
        status_border = "#EF4444"
    elif stan >= STAN_OSTRZEGAWCZY:
        status_text = "STAN OSTRZEGAWCZY"
        status_bg = "#D97706"
        status_border = "#FBBF24"
    elif temp_woda < 10.0 and (wiatr_v >= 8 or porywy_v >= 14):
        status_text = "ALARM TERMICZNY / SZKWAŁY"
        status_bg = "#DC2626"
        status_border = "#F87171"
    elif stan < STAN_BEZPIECZNY:
        status_text = "STREFA NISKA (ŁACHY/OSTROGI)"
        status_bg = "#0284C7"
        status_border = "#38BDF8"
    else:
        status_text = "STAN W NORMIE"
        status_bg = "#059669"
        status_border = "#10B981"

    return {
        "stan": stan,
        "stacja": hydro["stacja"],
        "rzeka": hydro["rzeka"],
        "data_pomiaru_pelna": data_str,
        "godzina_pomiaru": godzina_str,
        "temp_woda": temp_woda,
        "temp_pow": temp_pow,
        "flow_q": flow_q,
        "flow_note": flow_note,
        "nav_risk": nav_risk,
        "nav_risk_color": nav_risk_color,
        "soi_text": soi_text,
        "soi_color": soi_color,
        "hypo_text": hypo_text,
        "wiatr_v": int(wiatr_v),
        "porywy_v": porywy_v,
        "cisnienie": cisnienie,
        "wave_text": wave_text,
        "wave_color": wave_color,
        "sunset": sunset_str,
        "dusk": dusk_str,
        "status_text": status_text,
        "status_bg": status_bg,
        "status_border": status_border
    }

def get_history():
    if not os.path.exists(HISTORY_FILE):
        return [], []
    dates, levels = [], []
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
    return dates, levels

def generate_tactical_card(tactical, rain_alert):
    fig = plt.figure(figsize=(12, 8.4), dpi=200, facecolor="#060913")
    
    # ZNAK WODNY W TLE
    fig.text(0.50, 0.48, "WOPR TORUŃ", fontsize=72, fontweight="black", 
             color="#38BDF8", alpha=0.035, ha="center", va="center", rotation=14)

    gs = gridspec.GridSpec(3, 4, height_ratios=[1.15, 1.5, 2.35], figure=fig)

    # 1. NAGŁÓWEK
    ax_head = fig.add_subplot(gs[0, :])
    ax_head.set_facecolor("#0D1527")
    ax_head.axis("off")
    ax_head.text(0.025, 0.72, "WOPR TORUŃ  •  BIULETYN OPERACYJNY", fontsize=15.5, fontweight="bold", color="#FFFFFF")
    ax_head.text(0.025, 0.28, f"Sektor: Wisła Dolna (km 735)  |  Wodowskaz IMGW: {HYDRO_STATION_ID}  |  Odczyt: {tactical['data_pomiaru_pelna']}", fontsize=9.2, color="#94A3B8")
    
    ax_head.text(0.975, 0.50, tactical['status_text'], fontsize=9.5, fontweight="bold", color="#FFFFFF",
                 ha="right", va="center",
                 bbox=dict(boxstyle="round,pad=0.55", facecolor=tactical['status_bg'], edgecolor=tactical['status_border'], linewidth=1.2))

    # 2. STAN WODY
    ax_k1 = fig.add_subplot(gs[1, 0])
    ax_k1.set_facecolor("#0D1527")
    ax_k1.axis("off")
    ax_k1.text(0.5, 0.86, "STAN WODY & PRZEPŁYW", fontsize=8.5, fontweight="bold", color="#8E9AA8", ha="center")
    ax_k1.text(0.5, 0.55, f"{int(tactical['stan'])} cm", fontsize=24, fontweight="bold", color="#38BDF8", ha="center")
    ax_k1.text(0.5, 0.28, f"Q: {tactical['flow_q']} m³/s • {tactical['flow_note']}", fontsize=7.8, fontweight="semibold", color="#E2E8F0", ha="center")
    ax_k1.text(0.5, 0.10, tactical['nav_risk'], fontsize=7.3, fontweight="bold", color=tactical['nav_risk_color'], ha="center")

    # 3. TERMIKA I ŚOI
    ax_k2 = fig.add_subplot(gs[1, 1])
    ax_k2.set_facecolor("#0D1527")
    ax_k2.axis("off")
    ax_k2.text(0.5, 0.86, "TERMIKA & ŚOI ZAŁOGI", fontsize=8.5, fontweight="bold", color="#8E9AA8", ha="center")
    ax_k2.text(0.5, 0.55, f"{tactical['temp_woda']:.1f} °C", fontsize=24, fontweight="bold", color="#10B981" if tactical['temp_woda'] >= 18 else "#38BDF8", ha="center")
    ax_k2.text(0.5, 0.28, tactical['soi_text'], fontsize=7.6, fontweight="bold", color=tactical['soi_color'], ha="center")
    ax_k2.text(0.5, 0.10, tactical['hypo_text'], fontsize=7.4, color="#94A3B8", ha="center")

    # 4. WIATR I FALOWANIE
    ax_k3 = fig.add_subplot(gs[1, 2])
    ax_k3.set_facecolor("#0D1527")
    ax_k3.axis("off")
    ax_k3.text(0.5, 0.86, "WIATR & WARUNKI", fontsize=8.5, fontweight="bold", color="#8E9AA8", ha="center")
    ax_k3.text(0.5, 0.55, f"{tactical['wiatr_v']} m/s", fontsize=24, fontweight="bold", color="#A78BFA", ha="center")
    ax_k3.text(0.5, 0.28, f"Porywy: {tactical['porywy_v']} m/s • {tactical['cisnienie']} hPa", fontsize=7.6, fontweight="semibold", color="#C4B5FD", ha="center")
    ax_k3.text(0.5, 0.10, tactical['wave_text'], fontsize=7.4, fontweight="bold", color=tactical['wave_color'], ha="center")

    # 5. ŚWIATŁO I OKNO OPERACYJNE
    ax_k4 = fig.add_subplot(gs[1, 3])
    ax_k4.set_facecolor("#0D1527")
    ax_k4.axis("off")
    ax_k4.text(0.5, 0.86, "ŚWIATŁO & METEO", fontsize=8.5, fontweight="bold", color="#8E9AA8", ha="center")
    ax_k4.text(0.5, 0.55, tactical['sunset'], fontsize=22, fontweight="bold", color="#FBBF24", ha="center")
    ax_k4.text(0.5, 0.28, f"Zmierzch cywilny: {tactical['dusk']}", fontsize=7.8, fontweight="semibold", color="#FDE68A", ha="center")
    
    if rain_alert:
        ax_k4.text(0.5, 0.10, f"Deszcz ok. {rain_alert['time']} ({rain_alert['amount']} mm)", fontsize=7.4, fontweight="bold", color="#38BDF8", ha="center")
    else:
        ax_k4.text(0.5, 0.10, f"Powietrze: {tactical['temp_pow']}°C • Brak opadów", fontsize=7.4, color="#94A3B8", ha="center")

    for ax in [ax_head, ax_k1, ax_k2, ax_k3, ax_k4]:
        rect = plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, fill=False, edgecolor="#1B253B", linewidth=1.2, clip_on=False)
        ax.add_patch(rect)

    # 6. WYKRES
    ax_plot = fig.add_subplot(gs[2, :])
    ax_plot.set_facecolor("#0D1527")

    ax_plot.text(0.5, 0.5, "WOPR TORUŃ", transform=ax_plot.transAxes,
                 fontsize=46, fontweight="black", color="#38BDF8", alpha=0.04,
                 ha="center", va="center", rotation=8)

    dates, levels = get_history()
    now_dt = datetime.now(TIMEZONE)

    if not dates or len(dates) < 2:
        dates = [now_dt - timedelta(hours=i) for i in range(6, -1, -1)]
        levels = [tactical['stan']] * len(dates)

    dates = dates[-48:]
    levels = levels[-48:]

    ax_plot.plot(dates, levels, color="#38BDF8", linewidth=2.8, marker="o", markersize=3.5, label=f"Wodowskaz Toruń (Wisła)")
    min_fill = max(0, min(levels) - 8)
    ax_plot.fill_between(dates, levels, min_fill, color="#38BDF8", alpha=0.15)

    proj_times = [dates[-1] + timedelta(hours=i) for i in range(3, 25, 3)]
    trend_delta = (levels[-1] - levels[0]) / max(1, len(levels))
    proj_levels = [round(levels[-1] + trend_delta * (i/4), 1) for i in range(1, 9)]
    all_proj_t = [dates[-1]] + proj_times
    all_proj_l = [levels[-1]] + proj_levels

    ax_plot.plot(all_proj_t, all_proj_l, color="#FBBF24", linewidth=2.2, linestyle="--", marker="s", markersize=3, label="Projekcja trendu (24h)")
    ax_plot.fill_between(all_proj_t, all_proj_l, min_fill, color="#FBBF24", alpha=0.07)

    ax_plot.scatter([dates[-1]], [levels[-1]], color="#F43F5E", s=70, zorder=6)
    ann_time = tactical['godzina_pomiaru'] if tactical['godzina_pomiaru'] else dates[-1].strftime("%H:%M")
    ax_plot.annotate(f"Bieżący ({ann_time}): {int(levels[-1])} cm\n(Q ≈ {tactical['flow_q']} m³/s)", 
                     xy=(dates[-1], levels[-1]), 
                     xytext=(-105, 14), textcoords="offset points",
                     color="#FFFFFF", fontsize=8.5, fontweight="bold",
                     bbox=dict(boxstyle="round,pad=0.35", facecolor="#F43F5E", edgecolor="none"),
                     arrowprops=dict(arrowstyle="->", color="#F43F5E", lw=1.3))

    if max(levels) >= 400:
        ax_plot.axhline(STAN_OSTRZEGAWCZY, color="#F59E0B", linestyle="--", linewidth=1.2, label=f"Stan Ostrzegawczy ({STAN_OSTRZEGAWCZY} cm)")
        ax_plot.axhline(STAN_ALARMOWY, color="#EF4444", linestyle="-.", linewidth=1.2, label=f"Stan Alarmowy ({STAN_ALARMOWY} cm)")
    else:
        ax_plot.axhline(STAN_SNW, color="#64748B", linestyle=":", linewidth=1.1, label=f"Średni Niski Stan (SNW ~{STAN_SNW} cm)")
        ax_plot.axhline(STAN_BEZPIECZNY, color="#10B981", linestyle="-.", linewidth=0.9, alpha=0.6, label=f"Bezpieczna Żegluga (>{STAN_BEZPIECZNY} cm)")

    ax_plot.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m\n%H:%M"))
    ax_plot.tick_params(colors="#94A3B8", labelsize=8)
    ax_plot.grid(True, linestyle="--", alpha=0.2, color="#334155")
    ax_plot.set_ylabel("Poziom Wisły [cm]", color="#94A3B8", fontsize=9.2, labelpad=6)
    
    y_min = max(0, min(min(levels), min(proj_levels)) - 10)
    y_max = max(max(levels), max(proj_levels)) + 20
    ax_plot.set_ylim(y_min, max(y_max, STAN_BEZPIECZNY + 10))
    ax_plot.legend(loc="upper left", facecolor="#141E33", edgecolor="#263554", fontsize=8, labelcolor="#E2E8F0")

    ax_plot.text(0.99, 0.03, "Jednostka Ratownictwa Wodnego • WOPR Toruń", transform=ax_plot.transAxes,
                 fontsize=7.5, color="#64748B", ha="right", va="bottom", fontstyle="italic")

    for spine in ax_plot.spines.values():
        spine.set_edgecolor("#1B253B")
        spine.set_linewidth(1.2)

    plt.subplots_adjust(hspace=0.32, wspace=0.14, left=0.045, right=0.955, top=0.95, bottom=0.08)
    plt.savefig(CARD_FILE, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()

# ==============================================================================
# BLOKADA POWTÓRZEŃ I LOGIKA POWIADOMIEŃ
# ==============================================================================
def check_level_change(current_stan):
    """Zwraca (czy_zmieniony, poprzedni_stan)."""
    if not os.path.exists(LAST_LEVEL_FILE):
        with open(LAST_LEVEL_FILE, "w", encoding="utf-8") as f:
            f.write(str(current_stan))
        return False, current_stan

    try:
        with open(LAST_LEVEL_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                prev = float(content)
                if prev != current_stan:
                    return True, prev
                return False, prev
    except Exception:
        pass
    return False, current_stan

def save_current_level(current_stan):
    with open(LAST_LEVEL_FILE, "w", encoding="utf-8") as f:
        f.write(str(current_stan))

def is_morning_report_due():
    """Zwraca True dokładnie raz dziennie w oknie 05:45 - 09:00."""
    now_pl = datetime.now(TIMEZONE)
    in_window = (now_pl.hour == 5 and now_pl.minute >= 45) or (6 <= now_pl.hour <= 8)
    if not in_window:
        return False
    
    today_str = now_pl.strftime("%Y-%m-%d")
    if os.path.exists(MORNING_STATE_FILE):
        try:
            with open(MORNING_STATE_FILE, "r", encoding="utf-8") as f:
                if f.read().strip() == today_str:
                    return False
        except Exception:
            pass
    return True

def mark_morning_report_sent():
    today_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    with open(MORNING_STATE_FILE, "w", encoding="utf-8") as f:
        f.write(today_str)

def is_rain_alert_due(rain_info):
    """Zwraca True tylko 1 raz na dane pasmo deszczowe."""
    if not rain_info:
        return False
    state_key = f"{datetime.now(TIMEZONE).strftime('%Y-%m-%d')}_{rain_info['time']}"
    if os.path.exists(RAIN_STATE_FILE):
        try:
            with open(RAIN_STATE_FILE, "r", encoding="utf-8") as f:
                if f.read().strip() == state_key:
                    return False
        except Exception:
            pass
    return True

def mark_rain_alert_sent(rain_info):
    if not rain_info:
        return
    state_key = f"{datetime.now(TIMEZONE).strftime('%Y-%m-%d')}_{rain_info['time']}"
    with open(RAIN_STATE_FILE, "w", encoding="utf-8") as f:
        f.write(state_key)

def send_ntfy(title, priority="default", tags="chart_with_upwards_trend,droplet"):
    if not NTFY_TOPIC:
        return
    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    if os.path.exists(CARD_FILE):
        with open(CARD_FILE, "rb") as img:
            requests.post(
                url,
                data=img,
                headers={
                    "Title": title.encode("utf-8"),
                    "Filename": "biuletyn_wisla.png",
                    "Tags": tags,
                    "Priority": priority
                },
                timeout=15
            )

if __name__ == "__main__":
    # Upewniamy się, że pliki stanu zawsze istnieją
    for fname in [LAST_LEVEL_FILE, RAIN_STATE_FILE, MORNING_STATE_FILE]:
        if not os.path.exists(fname):
            open(fname, "a", encoding="utf-8").close()

    hydro_raw = scrape_hydro_with_browser()
    synop_raw = fetch_synop_data()
    meteo_raw = fetch_meteo_forecast()

    tactical = analyze_tactical_data(hydro_raw, synop_raw, meteo_raw)
    rain_alert = analyze_rain_alert(meteo_raw)

    generate_tactical_card(tactical, rain_alert)

    current_stan = tactical["stan"]
    time_label = f" ({tactical['godzina_pomiaru']})" if tactical['godzina_pomiaru'] else ""

    morning_due = is_morning_report_due()
    rain_due = is_rain_alert_due(rain_alert)
    level_changed, prev_stan = check_level_change(current_stan)
    is_high_water = (current_stan >= STAN_OSTRZEGAWCZY)

    # 1. BEZWZGLĘDNY PRIORYTET: Biuletyn poranny o 6:00 (niezależnie od stanu wody)
    if morning_due:
        print("[RAPORT] Wysyłanie biuletynu porannego WOPR (06:00)...")
        rain_addon = f" | 🌧️ Deszcz ok. {rain_alert['time']}" if rain_alert else ""
        title = f"[PORANNY] Wisła ({tactical['stacja']}): {int(current_stan)} cm{time_label} | Woda: {tactical['temp_woda']}°C{rain_addon}"
        send_ntfy(title, priority="default", tags="partly_sunny,speedboat")
        mark_morning_report_sent()
        save_current_level(current_stan)

    # 2. Ostrzeżenie przed deszczem (dokładnie 1 powiadomienie na dane zjawisko)
    elif rain_due:
        print(f"[ALERT] Nadchodzący deszcz o {rain_alert['time']} ({rain_alert['amount']} mm)...")
        title = f"☔ [DESZCZ OK. {rain_alert['time']}] Opad: {rain_alert['amount']} mm | Wisła: {int(current_stan)} cm{time_label}"
        send_ntfy(title, priority="high", tags="umbrella,cloud_with_rain")
        mark_rain_alert_sent(rain_alert)
        save_current_level(current_stan)

    # 3. Stan ostrzegawczy / alarmowy
    elif is_high_water:
        print("[ALERT] Stan wody wysoki!")
        title = f"🚨 [STAN OSTRZEGAWCZY] Wisła: {int(current_stan)} cm{time_label}!"
        send_ntfy(title, priority="urgent", tags="warning,rotating_light")
        save_current_level(current_stan)

    # 4. Zmiana poziomu wody (wzrost / spadek o minimum 1 cm)
    elif level_changed:
        diff_val = int(current_stan - prev_stan)
        diff_str = f" ({'+' if diff_val > 0 else ''}{diff_val} cm)"
        print(f"[ZMIANA] Zmiana poziomu wody: {prev_stan} -> {current_stan} cm")
        title = f"[ZMIANA{diff_str}] Wisła: {int(current_stan)} cm{time_label} | Q={tactical['flow_q']} m³/s"
        send_ntfy(title, priority="default", tags="chart_with_upwards_trend,droplet")
        save_current_level(current_stan)

    # 5. Stan stabilny, brak deszczu i to nie jest poranek -> Pełna cisza
    else:
        print(f"[INFO] Poziom wody bez zmian ({int(current_stan)} cm). Raport poranny zrealizowany. Powiadomienie pominięte.")
        save_current_level(current_stan)
