# BreakApp

> **💡 A Note on Customization & AI Assistance:**
> You are encouraged to download the raw source code directly from the `master` branch. This application is built with complete user freedom in mind—you can change, tweak, and control everything to suit your needs.
> 
> If you want a different behavior, want to adjust the design, or need help setting it up: **Don't hesitate to use AI!** Simply feed this code into ChatGPT, Claude, or Gemini and let it assist you in modifying the script or troubleshooting. If you want to contribute and improve the project, an AI assistant is also a great copilot to help you navigate the codebase. Open source thrives on collaboration!

> **Note on Windows SmartScreen:**
> Since this executable is not signed with a commercial developer certificate, Windows SmartScreen might show a warning when you run it for the first time. Simply click "More info" and then "Run anyway" to start the app.

## Important Notice: Multi-Instance Usage & Liability

* **Simultaneous Instances:** You can run multiple instances of this application from the exact same directory/location. It should function completely fine during your active session. 
* **System Restart Limitation:** However, please note that because instances in the same directory share the same path configuration, their autostart registry entries and setting files will conflict. Upon a system restart, only one instance will be successfully launched by Windows.
* **⚠️ DISCLAIMER:** If you choose to run multiple instances from the same location, you do so entirely at your own risk. The developer assumes **absolutely no liability** for any unexpected behavior, settings corruption, data loss, or system issues that may arise from this usage.

## What Does It Do?

BreakApp is an uncompromising break reminder for Windows. It runs discreetly in the background and prevents you from staring at your screen for hours without interruption by enforcing a strict screen break after a defined working period.

**The Typical Workflow:**
1. **Work Phase:** Your time between pauses.
2. **Grace Time (Warning):** A small warning window appears, signaling that your work time is coming to an end. Can be used when in the middle of a game or during deep focus.
3. **Force Pause:** All monitors are overlaid with a solid black screen. A countdown timer in the center displays the remaining break time.

## Key Features

* **Multi-Monitor Lock:** Reliably blocks all connected screens during the forced break.
* **Anti-Cheat (Blocked Apps):** If you try to open Task Manager, Command Prompt (CMD), or PowerShell during the grace period to kill the app, BreakApp intercepts it and enforces the full break **immediately**.
* **Password-Protected Settings:** Configuration data is securely stored using the native Windows DPAPI (Data Protection API). Changing timers or settings requires a password and enforces a mandatory waiting period.
* **Dynamic Break Calculation:** The duration of the break is calculated dynamically using a customizable mathematical formula (e.g., `0.5 + t / 20`) based on how much you exceeded your work time.
* **Session & Lock Tracking:** The app detects when you lock your PC or switch users, automatically pausing its internal timers.
* **Directory-Isolating Settings:** If run from different folders, the app generates a unique hash based on the path. This ensures that different installations keep their own isolated configuration profiles.
* **Automated Autostart:** Automatically creates clean registry entries in Windows to boot up on startup.

## Installation & Setup for Developers

Because the app hooks deeply into Windows system architecture (window management, process scanning, and event hooks), you will need Python and a few external libraries.

1. Clone or download the master branch.
2. Install the required dependencies via pip:
   ```bash
   pip install psutil pystray Pillow simpleeval sympy pywin32
   ```
3. Run the break_app.pyw file. The .pyw extension ensures that the application runs silently in the background without opening an annoying console window.
