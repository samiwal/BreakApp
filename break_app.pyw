import sys
import os
import json
import threading
import ctypes
import winreg
import psutil
import tkinter as tk
from tkinter import messagebox
import pystray
from PIL import Image, ImageDraw
import win32gui
from simpleeval import simple_eval
import traceback
from sympy import sympify, diff, solve, lambdify
import win32ts
from sympy.abc import t
import datetime
import hashlib

GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_EX_NOACTIVATE = 0x08000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
SWP_NOACTIVATE = 0x0010
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020   
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST = -1
HWND_BOTTOM = 1
GA_ROOT = 2
WS_EX_TOOLWINDOW = 0x00000080
 
user32 = ctypes.windll.user32

## Installer muss noch geschrieben werden.

# Wenn die Datei bewegt wird, wird sie so lange weiterfunktionieren bis man sie neu startet. Dann werden alle Settings zurückgesetzt.
# Ich finde keine bessere Methode, die gleichzeitig erlaubt, mehrere instanzen laufen zu lassen, die nicht auf die gleichen settings zugreifen.

class BreakApp:
    """
    Pausen App (Während dem Programmstart muss man einen moment warten und NICHT den Desktop wechseln)
    """
    def __init__(self):
        self.path = os.path.abspath(__file__)
        self.path_hash = hashlib.md5(self.path.encode()).hexdigest()[:8] #Falls der Digest zufällig gleich ist, einfach Dateinamen ändern.
        self.config_file = os.path.join(os.environ["APPDATA"], "BreakApp" , f"{self.path_hash}_settings.dat")
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        self.window = None
        self.pause_end_time = datetime.datetime.now().isoformat()
        self.elapsed = 0
        self.timer_stopped = False
        self.is_paused = False
        self.debug_file = True # Wenn das true ist bekommt man eine datei mit den fehlermeldungen. Kann problematisch sein, wenn die App in Admin-geschützten Orten liegt.
        self.loop_time = 500 #ms
        self.settings = None
        self.preview_window_ready = False
        self.force_window_ready = False
        self.pre_warning_window_ready = False
        self.normal_window_ready = False
        
        # Generelles Setup
        self.setup_autostart()
        self.save_lock = threading.Lock()
        
        # Root Initialisieren
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.update()
        def tk_exception_handler(exc, val, tb):
            if self.debug_file:
                with open((self.path + "_error.log"), "a") as f:
                    f.write("".join(traceback.format_exception(exc, val, tb)) + "\n---\n")
        self.root.report_callback_exception = tk_exception_handler
        
        self.setup_main_win()
        self.settings = self.load_settings()
        self.elapsed = self.settings.get("Elapsed Work Time")
        hwnd_child = self.window.winfo_id()
        hwnd = ctypes.windll.user32.GetAncestor(hwnd_child, GA_ROOT)
        x, y = self.settings.get("Warn Window Position")
        user32.SetWindowPos(hwnd, None,x, y, 0, 0, SWP_FRAMECHANGED | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

        #Lock handling starten
        self.start_session_monitor()

        # Tray Setup
        self.tray_thread = threading.Thread(target=self.setup_tray, daemon=True)
        self.tray_thread.start()
        
        # Loops
        self.run_monitor()
        self.root.mainloop()

    def start_session_monitor(self):
        def monitor_thread():
            wc = win32gui.WNDCLASS()
            wc.lpszClassName = "BreakAppSessionMonitor"
            wc.lpfnWndProc = self.wnd_proc
            win32gui.RegisterClass(wc)
            hwnd = win32gui.CreateWindow(
                "BreakAppSessionMonitor", "", 0,
                0, 0, 0, 0, 0, 0, None, None
            )
            win32ts.WTSRegisterSessionNotification(hwnd, win32ts.NOTIFY_FOR_THIS_SESSION)
            
            msg = ctypes.wintypes.MSG()
            while ctypes.windll.user32.GetMessageA(ctypes.byref(msg), None, 0, 0) != 0:
                ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                ctypes.windll.user32.DispatchMessageA(ctypes.byref(msg))
        
        threading.Thread(target=monitor_thread, daemon=True).start()

    # --- SETUP & LIFECYCLE ---
    def setup_autostart(self):
        """Registriert die App in Windows Autostart."""
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            try:
                winreg.QueryValueEx(key, "BreakApp_" + self.path_hash)
                winreg.CloseKey(key)
                return
            except OSError:
                pass

            # Prüft, ob die App mit PyInstaller eingefroren wurde
            if getattr(sys, 'frozen', False):
                # Als .exe: sys.executable ist direkt der Pfad zur ausführbaren Datei
                command = f'"{sys.executable}"'
            else:
                # Als Python-Skript im Entwicklungsmodus
                python_exe = sys.executable.replace("python.exe", "pythonw.exe")
                script_path = os.path.abspath(sys.argv[0])
                command = f'"{python_exe}" "{script_path}"'

            winreg.SetValueEx(key, "BreakApp_" + self.path_hash, 0, winreg.REG_SZ, command)
            winreg.CloseKey(key)
            print("Autostart erfolgreich registriert.")

        except Exception as e:
            print(f"Fehler beim Autostart-Setup: {e}")
    
    def load_settings(self):
        """Lädt verschlüsselte Settings oder setzt Defaults."""
        defaults = {
            "Work Time": 20.0,
            "Grace Time": 40.0,
            "Pause Time Formula": "0.5 + t / 20",
            "Lock Settings": 0.5,
            "Password": "admin",
            "Blocked Apps": ['taskmgr.exe', 'cmd.exe', 'powershell.exe'],
            "Warn Window Position": [100,100],
            "Elapsed Work Time": 0,
            "Pause End Time": datetime.datetime.now().isoformat()
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'rb') as f:
                    encrypted = f.read()
                json_str = decrypt_data(encrypted).decode('utf-8')
                loaded = json.loads(json_str)
                defaults.update(loaded)
                settings = defaults
                if not self.validate_settings(settings):
                    settings = defaults
            except Exception:
                settings = defaults
        else:
            settings = defaults
        return settings

    def validate_settings(self, data):
        try:
            for key in ["Work Time", "Grace Time", "Lock Settings"]:
                if data.get(key, 0) < 0:
                    self.show_error(f"{key} can't be negative")
                    return False
            
            pos = data.get("Warn Window Position")
            if not isinstance(pos, list) or len(pos) != 2:
                self.show_error("Warn Window Position needs X and Y!")
                return False
            
            if not isinstance(data.get("Blocked Apps"), list):
                self.show_error("Blocked Apps has to be a list!")
                return False
            
            formula = data.get("Pause Time Formula", "")
            test = 5.0
            try:
                test_val = simple_eval(
                    formula,
                    names={"t": test})
                if not isinstance(test_val, (int, float)):
                    return messagebox.askyesno(
                        "Formula warning",
                        f"Formula did not return an int or float value with test time '{test}'min\n\n"
                        "Continue?")
            except Exception as e:
                self.show_error(e)
                return False
            return True
        except Exception as e:
            self.show_error(e)
            return False

    def save_to_disk(self, settings_data):
        """Speichert verschlüsselt mit DPAPI."""
        with self.save_lock:
            old_settings = self.load_settings()
            for key in settings_data:
                old_settings[key] = settings_data[key]
            try:
                json_str = json.dumps(old_settings, indent=4)
                encrypted = encrypt_data(json_str.encode('utf-8'))
                with open(self.config_file, 'wb') as f:
                    f.write(encrypted)
            except Exception as e:
                self.show_error(e)

    def get_time_string(self, seconds: float):
        """
        Rechnet die Sekunden in einen String mit Stunden, Minuten und Sekunden um.
        """
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        string = ""
        if hours > 0:
            string += f"{int(hours)}h "
        if minutes > 0 or hours > 0:
            string += f"{int(minutes)}m "
        string += f"{seconds:.0f}s"
        return string
    
    def show_error(self, msg):
        """Zeigt Fehlermeldung sicher im Tkinter-Hauptthread."""
        if self.debug_file:
            with open((self.path + "_error.log"), "a") as f:
                f.write(f"{msg}\n{traceback.format_exc()}\n---\n")
        if hasattr(self, 'root'):
            self.root.after(0, lambda: messagebox.showerror("Fehler", str(msg)))

    # --- UI: TRAY UND SETTINGS---
    def setup_tray(self):
        """Erstellt Tray-Icon mit Mond-Symbol."""
        img = Image.new('RGB', (64, 64), color=(0, 0, 0))
        d = ImageDraw.Draw(img)
        
        # Größere Mondsichel
        d.ellipse((8, 5, 56, 53), fill=(200, 200, 0))    # Gelber Kreis
        d.ellipse((18, 5, 66, 53), fill=(40, 49, 40))    # Dunkel überlagern = Sichelform
        
        icon = pystray.Icon("BreakApp", img, "Break App")
        icon.menu = pystray.Menu(pystray.MenuItem("Controls", lambda:self.root.after(0, self.show_guard_ui)),
                                 pystray.MenuItem("Pause", lambda:self.root.after(0, self.start_pause_from_settings)),
                                 pystray.MenuItem("Position",  lambda:self.root.after(0, self.change_position_ui), default=True))
        icon.run()

    def start_pause_from_settings(self):
        self.set_pause_end_time(self.elapsed)
        self.is_paused = True

    def show_guard_ui(self):
        """Zeigt Password-Gate für Settings-Zugriff."""
        settings_win = tk.Toplevel(self.root)
        settings_win.attributes("-alpha", 0.0)
        settings_win.withdraw()
        settings_win.title("Safety Gate")
        
        pw_ok = False
        time_ok = False
        
        pw_frame = tk.Frame(settings_win)
        pw_frame.pack()
        
        pw_ent = tk.Entry(pw_frame, show="*")
        pw_ent.pack(side="left")

        eye_btn = tk.Button(pw_frame, text="👁️")
        eye_btn.pack(side="left")
        
        def on_eye_press(_):
            pw_ent.config(show='')
        
        def on_eye_release(_):
            pw_ent.config(show='*')
        
        eye_btn.bind("<ButtonPress-1>", on_eye_press)
        eye_btn.bind("<ButtonRelease-1>", on_eye_release)

        btn_unlock = tk.Button(settings_win, width=12)
        btn_unlock.pack()

        def check_pw(e=None):
            nonlocal pw_ok
            if pw_ent.get() == str(self.settings.get("Password")):
                pw_ok = True
                pw_ent.config(state="disabled")
                btn_unlock.config(fg="green")
                attempt_unlock()
            else:
                btn_unlock.config(fg="red")
                pw_ent.delete(0, tk.END)

        def attempt_unlock():
            if pw_ok and time_ok:
                for entry in settings_win.winfo_children():
                    entry.destroy()
                self.open_config(settings_win)

        def countdown(n):
            nonlocal time_ok
            if n > 0 and settings_win.winfo_exists():
                btn_unlock.config(text=f"Timer: {self.get_time_string(n)}" if not pw_ok else f"Ready in {self.get_time_string(n)}")
                settings_win.after(1000, countdown, n - 1)
            elif settings_win.winfo_exists():
                btn_unlock.config(text="Enter")
                time_ok = True
                attempt_unlock()

        btn_unlock.config(command=check_pw)
        pw_ent.bind("<Return>", check_pw)
        countdown(int(self.settings["Lock Settings"]*60))
        settings_win.update_idletasks()
        settings_win.deiconify()
        settings_win.attributes("-alpha", 1.0)
        pw_ent.focus_force()

    # --- UI: CONFIG ---
    def open_config(self, settings_win, data = None):
        """Zeigt Konfiguration-Editor."""
        settings_win.title("Configuration")
        if data is None: data = list(self.settings.items())
        inputs = {}
        for key, val in data:
            if key == "Elapsed Work Time":
                continue
            f = tk.Frame(settings_win)
            f.pack(fill="x")
            tk.Label(f, text=(key + ":")).pack(side="left")
            
            if key == "Blocked Apps":
                val_str = ", ".join(val) if isinstance(val, list) else str(val)
                ent = tk.Entry(f)
                ent.insert(0, val_str)  
                ent.pack(side="right", expand=True, fill="x")
                inputs[key] = ent

            elif key == "Password":
                pw_frame = tk.Frame(f)
                pw_frame.pack(side="right", expand=True, fill="x")
                pw = tk.Entry(pw_frame, show="*")
                pw.insert(0, str(val))
                pw.pack(side="left", fill="x", expand=True, padx=2)
                eye_btn = tk.Button(pw_frame, text="👁️")
                def on_eye_press(event):
                    pw.config(show='')
                def on_eye_release(event):
                    pw.config(show='*')
                eye_btn.bind("<ButtonPress-1>", on_eye_press)
                eye_btn.bind("<ButtonRelease-1>", on_eye_release)
                eye_btn.pack(side="left")
                inputs[key] = pw

            elif key == "Pause Time Formula":
                tk.Label(f, text="t=Overhead").pack(side="left")
                ent = tk.Entry(f)
                ent.insert(0, str(val))
                ent.pack(side="right", expand=True, fill="x")
                inputs[key] = ent

            elif key == "Warn Window Position":
                frame = tk.Frame(f)
                frame.pack(side="right", expand=True, fill="x")
                fx = tk.Frame(frame)
                fx.pack(side="left", expand=True, fill="x")
                tk.Label(fx, text="x").pack(side="left")
                ent1 = tk.Entry(fx)
                ent1.insert(0, val[0])
                ent1.pack(side="right")
                fy = tk.Frame(frame)
                fy.pack(side="right", expand=True, fill="x")
                tk.Label(fy, text="y").pack(side="left")
                ent2 = tk.Entry(fy)
                ent2.insert(0, val[1])
                ent2.pack(side="right")
                inputs[key] = [ent1, ent2]

            else:
                ent = tk.Entry(f)
                ent.insert(0, str(val))
                ent.pack(side="right", expand=True, fill="x")
                inputs[key] = ent
        
        tk.Label(settings_win, text="every time is measured in minutes").pack()

        def prep_summary():
            try:
                new_data = {}
                for k, v in inputs.items():
                    if k == "Blocked Apps":
                        apps = [app.strip() for app in v.get().split(",") if app.strip()]
                        new_data[k] = apps
                    elif k == "Warn Window Position":
                        new_data[k] = [int(v[0].get()), int(v[1].get())]
                    elif k not in ("Password","Pause Time Formula"):
                        new_data[k] = float(v.get())
                    else:
                        new_data[k] = v.get()
                
                if not self.validate_settings(new_data): return
                
                for entry in settings_win.winfo_children(): entry.destroy()
                self.show_summary(settings_win, new_data)
            except Exception as e:
                self.show_error(e)

        tk.Button(settings_win, text="Continue to preview", bg="blue", fg="white", command=prep_summary).pack()
        tk.Button(settings_win,text="Cancel",command=lambda: settings_win.destroy()).pack()
        btn_exit = tk.Button(settings_win, text="Start Program stopping Timer", bg="black", fg="red")
        btn_exit.pack()

        def countdown(n):
            if n > 0:
                btn_exit.config(text=f"Stop Program (in {n}s)")
                settings_win.after(1000, countdown, n - 1)
            else:
                btn_exit.config(text="Stop Program", command=self.disable_autostart_and_exit)

        btn_exit.config(command=lambda: countdown(60))

    # -- Beenden mittels beenden button
    def disable_autostart_and_exit(self):
        """Entfernt App aus Autostart und beendet."""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                                r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_WRITE)
            winreg.DeleteValue(key, "BreakApp_" + self.path_hash)
            winreg.CloseKey(key)
        except Exception as e:
            self.show_error(e)
        os._exit(0)

    # --- UI: SUMMARY ---
    def show_summary(self, settings_win, data):
        """Zeigt Zusammenfassung und Warnung vor risikanten Settings."""
        settings_win.title("Check your settings")

        z_max = data["Grace Time"]
        formula = data["Pause Time Formula"]

        actual_max_p = self.get_max_pause(formula, z_max)
        total_time = data["Work Time"] + z_max
        is_risky_time = total_time < 5
        is_risky_pause = actual_max_p > 600
        
        bg_color = "#ff7f7f" if (is_risky_time or is_risky_pause) else "#c9ffbb"
        settings_win.config(bg=bg_color)

        tk.Label(settings_win, text="Summary", bg=bg_color).pack()

        txt = f"Total time until Force: {self.get_time_string(total_time*60)}\n"
        if is_risky_time:
            txt += "⚠️ EXTREMELY SHORT CYCLE!\n"
        txt += f"\nHighest possible pause: {self.get_time_string(actual_max_p*60)}\n"
        if is_risky_pause:
            txt += "⚠️ EXTREME PAUSE DURATION!\n"

        tk.Label(settings_win, text=txt, justify="center", bg=bg_color, 
                fg="red" if (is_risky_time or is_risky_pause) else "black").pack()
        
        def back_to_settings():
            for entry in settings_win.winfo_children():
                entry.destroy()
            self.open_config(settings_win,data.items())

        btn = tk.Button(settings_win, state="disabled")
        btn.pack()
        tk.Button(settings_win, text="Back", command= back_to_settings).pack()
    
        def final_apply():
            self.save_to_disk(data)
            settings_win.destroy()
        def wait_btn(n):
            try:
                if n > 0 and settings_win.winfo_exists():
                    btn.config(text=f"Are you Sure? ({n}s)")
                    settings_win.after(1000, wait_btn, n - 1)
                elif settings_win.winfo_exists():
                    btn.config(state="normal", text="Save", bg=bg_color, command=final_apply)
            except tk.TclError:
                pass
        wait_btn(10)

    def get_max_pause(self, formula, z_max):
        try:
            expr = sympify(formula)
            deriv = diff(expr, t)
            critical = solve(deriv, t)
            candidates = [0, z_max]
            for p in critical:
                p_val = float(p.evalf())
                if 0 <= p_val <= z_max:
                    candidates.append(p_val)
            
            f = lambdify(t, expr, 'math')
            return max(f(c) for c in candidates)
        except Exception as e:
            self.show_error(e)
            return 0

    # -- Position des hinweisfensters ändern --
    def change_position_ui(self):
        """Ermöglicht das Verschieben des Warnfensters."""
        if self.is_paused:
            return
        self.window.withdraw()
        w = tk.Toplevel(self.root)
        w.attributes("-alpha", 0.1)
        
        vx, vy, vw, vh = self.get_vscreen_bounds()
        w.protocol("WM_DELETE_WINDOW", lambda: None)
        w.geometry(f"{vw}x{vh}+{vx}+{vy}") 
        
        w.attributes("-topmost", True)
        w.overrideredirect(True)    
        w.config(cursor="cross", bg="black")
        
        def on_click(e):
            self.window.deiconify()
            abs_x = vx + e.x
            abs_y = vy + e.y
            
            self.settings["Warn Window Position"] = [abs_x, abs_y]
            self.save_to_disk({"Warn Window Position": [abs_x, abs_y]})
            w.destroy()
            hwnd_child = self.window.winfo_id()
            hwnd = ctypes.windll.user32.GetAncestor(hwnd_child, GA_ROOT)
            user32.SetWindowPos(hwnd, None, abs_x, abs_y, 0, 0, SWP_FRAMECHANGED | SWP_NOSIZE | SWP_NOACTIVATE)
        
        def on_cancel(e):
            w.destroy()
            self.window.deiconify()
                
                
        w.bind("<ButtonRelease-1>", on_click)
        w.bind("<ButtonRelease-3>", on_cancel)
        
        w.lift()
        w.focus_force()

    def wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == 0x02B1:
            self.handle_session_change(wparam)
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
    
    def handle_session_change(self, event_code):
        """Bestimmt wann das programm laufen soll"""
        # Codes: 0x7 = Lock, 0x8 = Unlock, 3/4 benutzer wechseln
        try:
            if event_code in [0x7, 0x4]: self.timer_stopped = True
            elif event_code in [0x8, 0x3]: 
                self.timer_stopped = False 
                self.root.after(0,self.run_monitor) # Wenn das programm hier abstürzt kann es helfen nach dem anmelden ein bisschen zeit zu geben
        except Exception as e:
            if self.debug_file:
                with open((self.path + "_error.log"), "a") as f:
                    f.write(f"session_change: {e}\n{traceback.format_exc()}\n")

    def setup_main_win(self):
        self.window = tk.Toplevel(self.root)
        self.window.attributes("-topmost", True)
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)  
        self.window.update_idletasks()
        hwnd_child = self.window.winfo_id()
        hwnd = ctypes.windll.user32.GetAncestor(hwnd_child, 2)
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        style &= ~WS_CAPTION
        style &= ~WS_THICKFRAME
        user32.SetWindowLongW(hwnd, GWL_STYLE, style)
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE)
        user32.SetWindowPos(hwnd_child, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_NOACTIVATE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_TOOLWINDOW)
        
    def set_pause_end_time(self, time):
        self.pause_end_time = (datetime.datetime.now() + datetime.timedelta(minutes=self.calculate_pause(time))).isoformat()
        self.save_to_disk({"Pause End Time": self.pause_end_time})

    def run_monitor(self):
        """Hauptmonitor-Loop - prüft alle 500ms Pausenzustände."""
        if self.timer_stopped: return
        try:    
            if datetime.datetime.fromisoformat(self.pause_end_time) > datetime.datetime.now():
                self.is_paused = True
            self.root.after(self.loop_time, self.run_monitor) ## Bei sehr schnellem aus und wieder einloggen könnte eine doppelte loop entstehen. Einfach flag setzen oder kleinere loop time (loop time emofehlung 500ms)
            self.window.attributes("-topmost",True)
            if self.is_paused:
                self.show_force()
            else:
                self.elapsed += (self.loop_time / 60000) #ms zu min
                self.settings["Elapsed Work Time"] = self.elapsed
                if self.elapsed % 1 < (self.loop_time / 60000): self.save_to_disk({"Elapsed Work Time":self.elapsed}) #einmal pro minute um neustart zu kontern
                work_time = self.settings.get("Work Time")
                grace_time = self.settings.get("Grace Time")
                total_time = work_time + grace_time
                self.window.update_idletasks()
                rw = self.window.winfo_reqwidth()
                rh = self.window.winfo_reqheight()
                w = self.window.winfo_width()
                h = self.window.winfo_height()
                if rw != w or rh != h:
                    hwnd = ctypes.windll.user32.GetAncestor(self.window.winfo_id(), 2)
                    user32.SetWindowPos(hwnd, None, 0, 0, rw, rh, SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE) # Größe aktualisieren

                if self.elapsed >= (total_time):
                    self.set_pause_end_time(total_time)
                    self.is_paused = True
                elif self.elapsed +  (self.loop_time / 60000) > work_time:
                    if self.using_blocked_app():
                        self.set_pause_end_time(self.elapsed)
                        self.is_paused = True
                    else:
                        self.show_pre(total_time)
                elif self.elapsed +  (self.loop_time / 60000) + 0.05 > work_time:
                    self.show_pre_warning()
                else:
                    self.show_normal()

        except Exception as e:
            self.show_error(e)
    
    def show_normal(self):
        if not self.normal_window_ready:
            self.window.config(bg="green")
            tk.Label(self.window,text="Take A Break!",bg="green").pack()
            self.normal_window_ready = True

    def show_pre_warning(self):
        ## Sollte nur etwas machen, wenn blocked apps konfiguriert sind.
        if not self.pre_warning_window_ready:
            for entry in self.window.winfo_children(): entry.destroy()
            self.window.config(bg="red")
            tk.Label(self.window, text="Close Blocked Apps",bg="red").pack()
            self.pre_warning_window_ready = True

    # --- UI: PREVIEW (Ermahnung) ---
    def show_pre(self, total_time): 
        """Zeigt Ermahnung vor erzwungener Pause."""
        pause_duration = self.calculate_pause(self.elapsed)
        if not self.preview_window_ready: 
            for entry in self.window.winfo_children(): entry.destroy()
            self.window.config(bg="#aefa62")
            self.window.lbl = tk.Label(self.window, bg="#2ad7be", fg="#8d004b")
            self.window.lbl.pack()
            def set_paused(): 
                self.set_pause_end_time(self.elapsed)
                self.is_paused = True
            tk.Button(self.window, text="Pause", bg="#aefa62", fg="#8d004b", command=set_paused).pack()
            self.preview_window_ready = True

        self.window.lbl.config(text=f"Pause: {self.get_time_string(pause_duration*60)}\nForce: {self.get_time_string((total_time-self.elapsed)*60)}")

    def get_all_monitors_info(self):
        """Ermittelt die genauen Koordinaten aller einzelnen Monitore."""
        monitors = []
        def monitor_enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
            # lprcMonitor ist ein RECT-Zeiger: [left, top, right, bottom]
            rect = lprcMonitor.contents
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            monitors.append((rect.left, rect.top, width, height))
            return True

        # Definition des Callback-Typs für Windows API
        MonitorEnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_ulong)
        callback = MonitorEnumProc(monitor_enum_proc)
        
        ctypes.windll.user32.EnumDisplayMonitors(None, None, callback, 0)
        return monitors
    
    def get_vscreen_bounds(self):
        """Ermittelt die virtuellen Gesamtabmessungen aller Monitore."""
        # SM_XVIRTUALSCREEN = 76, SM_YVIRTUALSCREEN = 77
        # SM_CXVIRTUALSCREEN = 78, SM_CYVIRTUALSCREEN = 79
        x = user32.GetSystemMetrics(76)
        y = user32.GetSystemMetrics(77)
        w = user32.GetSystemMetrics(78)
        h = user32.GetSystemMetrics(79)
        return x, y, w, h

    # --- UI: FORCE PAUSE ---
    def show_force(self): 
        def cleanup():
            self.force_window_ready = False
            self.preview_window_ready = False
            self.pre_warning_window_ready = False
            self.normal_window_ready = False
            self.is_paused = False
            hwnd_child = self.window.winfo_id()
            hwnd = ctypes.windll.user32.GetAncestor(hwnd_child, GA_ROOT)
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE)
            for entry in self.window.winfo_children(): entry.destroy()
            self.window.config(cursor="")
            self.reset_timer()

        if datetime.datetime.fromisoformat(self.pause_end_time) < datetime.datetime.now():
                cleanup()
                return
        try:
            if not self.force_window_ready:
                for entry in self.window.winfo_children(): entry.destroy()
                vx, vy, vw, vh = self.get_vscreen_bounds()
                hwnd_child = self.window.winfo_id()
                hwnd = ctypes.windll.user32.GetAncestor(hwnd_child, GA_ROOT)
                user32.SetWindowPos(hwnd, None, vx, vy, vw, vh, SWP_FRAMECHANGED | SWP_NOACTIVATE)
                self.window.config(cursor="none")
                self.window.config(bg="black")
                self.force_labels = []
                monitors = self.get_all_monitors_info()
                for mx, my, mw, mh in monitors:
                    frame = tk.Frame(self.window, bg="black", width=mw, height=mh)
                    frame.place(x=mx - vx, y=my - vy)
                    frame.pack_propagate(False)
                    lbl = tk.Label(frame, fg="white", bg="black", font=("Arial", 40))
                    lbl.pack(expand=True)
                    self.force_labels.append(lbl)
                self.force_window_ready = True

            self.window.focus_force()
            time_txt = f"Breathe\n\n{self.get_time_string((datetime.datetime.fromisoformat(self.pause_end_time) - datetime.datetime.now()).total_seconds())}"
            for lbl in self.force_labels:
                lbl.config(text=time_txt)

        except Exception as e:
            cleanup()
            self.show_error(e)

    # --- LOGIC ---
    def calculate_pause(self, elapsed_min) -> float:
        """Berechnet Pausendauer basierend auf Formel und Zeit t."""
        elapsed_min = max(elapsed_min,self.settings.get("Work Time"))
        try:
            result = (float)(simple_eval(
                self.settings.get("Pause Time Formula"),
                names={"t": elapsed_min-self.settings.get("Work Time")}
            ))
            return max(result, 0.0)
        except Exception as e:
            self.show_error(e)
            return 0.0

    def using_blocked_app(self):
        """Prüft ob blockierte App im Vordergrund ist - sofort Force."""
        blocked_apps = self.settings.get("Blocked Apps", [])
        if not blocked_apps:
            return False
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow() # Hat manchmal false-positives bei desktopwechsel 
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            
            active_name = psutil.Process(pid.value).name().lower()
            blocked_list = [app.lower() for app in blocked_apps]
            
            if active_name in blocked_list:
                return True
        except Exception as e:
            if self.debug_file:
                with open((self.path + "_error.log"), "a") as f:
                    f.write(f"using_blocked_app: {e}\n")
        return False

    def reset_timer(self):
        self.save_to_disk({"Elapsed Work Time": 0.0})
        self.settings = self.load_settings()
        hwnd_child = self.window.winfo_id()
        hwnd = ctypes.windll.user32.GetAncestor(hwnd_child, GA_ROOT)
        x, y = self.settings.get("Warn Window Position")
        user32.SetWindowPos(hwnd, None, x, y, 0, 0,
            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        self.elapsed = 0.0

class DATA_BLOB(ctypes.Structure): 
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]

def encrypt_data(data_bytes):
    blob_in = DATA_BLOB(len(data_bytes), ctypes.cast(ctypes.c_char_p(data_bytes), ctypes.c_void_p))
    blob_out = DATA_BLOB()
    
    result = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0x01, ctypes.byref(blob_out)
    )
    if not result: raise Exception("CryptProtectData failed")
    
    encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    return encrypted

def decrypt_data(encrypted_bytes):
    blob_in = DATA_BLOB(len(encrypted_bytes), ctypes.cast(ctypes.c_char_p(encrypted_bytes), ctypes.c_void_p))
    blob_out = DATA_BLOB()
    
    result = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0x01, ctypes.byref(blob_out)
    )
    if not result: raise Exception("CryptUnprotectData failed")
    
    decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    return decrypted

if __name__ == "__main__":
    app = BreakApp()