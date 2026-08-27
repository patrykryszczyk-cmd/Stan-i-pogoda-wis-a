import os
import csv
from datetime import datetime
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

# Progi dla Torunia (w cm)
STAN_OSTRZEGAWCZY = 530
STAN_ALARMOWY = 650

HISTORY_FILE = "history.csv"
CARD_FILE = "raport.png"
# ===============================================

def fetch_data():
    try:
        r_hydro = requests.get("https://danepubliczne.imgw.pl/api/data/hydro/", timeout=10).json()
        hydro = next((s for s in r_hydro if s.get("stacja", "").strip().lower() == HYDRO_STATION.lower()), None)
    except Exception as e:
        print(f"Błąd pobierania hydro: {e}")
        hydro = None

    try:
        r_synop = requests.get("https://danepubliczne.imgw.pl/api/data/synop/", timeout=10).json()
        synop = next((s for s in r_synop if s.get("stacja", "").strip().lower() == SYNOP_STATION.lower()), None)
    except Exception as e:
        print(f"Błąd pobierania pogody: {e}")
        synop = None

    return hydro, synop

def update_history(hydro):
    if not hydro or not hydro.get("stan_wody"):
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    stan = float(hydro.get("stan_wody"))
    temp_w = hydro.get("temperatura_wody")
    temp_w_val = float(temp_w) if temp_w and temp_w != "null" else ""

    file_exists = os.path.exists(HISTORY_FILE)
    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["datetime", "stan_wody", "temp_wody"])
        writer.writerow([now_str, stan, temp_w_val])

def generate_graphic_card(hydro, synop):
    stan = float(hydro.get("stan_wody", 0)) if hydro and hydro.get("stan_wody") else 0
    temp_w = hydro.get("temperatura_wody", "-") if hydro else "-"
    rzeka = hydro.get("rzeka", "Wisła") if hydro else "Wisła"
    data_pomiaru = hydro.get("stan_wody_data_pomiaru", datetime.now().strftime("%Y-%m-%d %H:%M")) if hydro else ""

    temp_powietrza = synop.get("temperatura", "-") if synop else "-"
    wiatr = synop.get("predkosc_wiatru", "-") if synop else "-"
    opad = synop.get("suma_opadu", "-") if synop else "-"
    cisnienie = synop.get("cisnienie", "-") if synop else "-"

    # Dynamiczny kolor i status
    if stan >= STAN_ALARMOWY:
        status_color = "#EF4444"
        status_text = "ALARM POWODZIOWY"
    elif stan >= STAN_OSTRZEGAWCZY:
        status_color = "#F97316"
        status_text = "STAN OSTRZEGAWCZY"
    else:
        status_color = "#10B981"
        status_text = "STAN W NORMIE"

    # Tworzenie grafiki dashboardu
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

    # 3. Kafelek 2: Pogoda / Opad
    ax_k2 = fig.add_subplot(gs[1, 1])
    ax_k2.set_facecolor("#1C2541")
    ax_k2.axis("off")
    ax_k2.text(0.5, 0.80, "POGODA / OPADY", fontsize=9.5, fontweight="bold", color="#9CA3AF", ha="center")
    ax_k2.text(0.5, 0.44, f"{temp_powietrza} °C", fontsize=22, fontweight="bold", color="#FBBF24", ha="center")
    ax_k2.text(0.5, 0.16, f"Opad: {opad} mm", fontsize=9, color="#CBD5E1", ha="center")

    # 4. Kafelek 3: Wiatr / Ciśnienie
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

def send_ntfy(hydro, synop):
    if not NTFY_TOPIC:
        raise ValueError("Brak zdefiniowanego sekretu NTFY_TOPIC!")

    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    stan = hydro.get("stan_wody", "?") if hydro else "?"
    temp = synop.get("temperatura", "?") if synop else "?"
    
    title = f"Raport {HYDRO_STATION}: {stan} cm | {temp}°C"

    if os.path.exists(CARD_FILE):
        with open(CARD_FILE, "rb") as img:
            requests.post(
                url,
                data=img,
                headers={
                    "Title": title.encode("utf-8"),
                    "Filename": "raport.png",
                    "Tags": "chart_with_upwards_trend,droplet",
                    "Priority": "default"
                },
                timeout=15
            )

if __name__ == "__main__":
    h_data, s_data = fetch_data()
    update_history(h_data)
    generate_graphic_card(h_data, s_data)
    send_ntfy(h_data, s_data)
