# IPMI Launcher

A drag-and-drop replacement for the legacy AMI/Supermicro JViewer KVM workflow.
Drop a `.jnlp` file from your BMC's web interface onto the window, click
**Launch IPMI**, and JViewer opens — no manual JAR signing, no batch scripts,
no Java Web Start fights.

> Built for legacy BMCs that still rely on Java 7 Web Start to deliver their KVM
> client. If your BMC's "Launch KVM" button downloads a `.jnlp` file, this app
> is for you.

## Why

Modern Java (8+) removed Java Web Start. Modern Java security blocks AMI's
2016-vintage signed JARs because their certs expired in 2017 and they don't
include timestamps. The traditional workaround — a batch file that re-signs
the JARs and patches the JNLP — fights an uphill battle against Java 7u80's
security model and breaks in subtle ways.

This app sidesteps all of that. It parses the JNLP, downloads the required
JARs straight from the BMC, extracts the native DLLs, and launches `java.exe`
**directly** with the right classpath and arguments. No `javaws`, no signing,
no security policy negotiation.

## Features

- Drag-and-drop a `.jnlp` from anywhere
- Auto-cleanup when JViewer closes — next launch is one drag away
- Synthwave dark theme
- Live status indicator and timestamped log
- Persistent settings (working folder override, JAR cache wipe)
- Uses a portable Java 7 alongside the .exe — no system Java install required
- Single-folder portable distribution

## Requirements

- **Windows 10 / 11** (64-bit). The app targets the JViewer Windows AMD64
  natives; other platforms aren't supported.
- **A Java 7 JRE.** Oracle's licensing doesn't allow me to redistribute it,
  so you provide your own. Any Oracle JDK 7u80 install works. See
  [Adding the JRE](#adding-the-jre) below — this is a one-time, ~5-minute setup.
- A BMC that uses AMI/Supermicro JViewer (test by downloading a `.jnlp` from
  its web UI).

## Quick start

1. Download the latest release from the [Releases page](../../releases),
   **OR** build from source (see [Build from source](#build-from-source)).
2. Extract the zip anywhere — you'll get an `IPMILauncher\` folder containing
   the .exe and an empty `jre7\` folder.
3. **Add a Java 7 JRE** into the empty `jre7\` folder — see
   [Adding the JRE](#adding-the-jre).
4. Double-click `IPMILauncher.exe`.
5. Drop a `.jnlp` from your BMC, click **Launch IPMI**.

## Adding the JRE

The app expects to find `java.exe` at: IPMILauncher\jre7\jre\bin\java.exe

The simplest way to get there:

1. Go to
   [Oracle's Java 7 archive downloads](https://www.oracle.com/java/technologies/javase/javase7-archive-downloads.html).
2. Sign in with a free Oracle account (required for archive downloads).
3. Download **Java SE Development Kit 7u80** for Windows x64
   (file name: `jdk-7u80-windows-x64.exe`).
4. Run the installer. It installs to `C:\Program Files\Java\jdk1.7.0_80\` by
   default.
5. **Copy** `C:\Program Files\Java\jdk1.7.0_80\` (the entire folder) into your
   `IPMILauncher\` folder, **renaming it to `jre7`**. After this, you should
   have:
   IPMILauncher
├── IPMILauncher.exe
├── jre7
│   ├── bin\           (jarsigner, keytool, etc.)
│   ├── jre
│   │   ├── bin
│   │   │   └── java.exe   <- the file the launcher looks for
│   │   └── lib
│   └── lib
├── _internal\         (PyInstaller files)
└── ... (other build artifacts)

6. Once copied, you can uninstall Java 7 from your system via
   **Settings → Apps** — the launcher uses its own copy at `IPMILauncher\jre7\`.

> **Why a JDK and not just a JRE?** Strictly, only the inner `jre\bin\java.exe`
> is used. A plain JRE 7 install also works as long as the path matches
> (`IPMILauncher\jre7\jre\bin\java.exe`). The full JDK is the cleanest single
> download from Oracle's archive.

## Build from source

Requires Python 3.11+ (3.13 recommended) installed from python.org with
**Add Python to PATH** ticked.

```bat
git clone https://github.com/<your-username>/ipmi-launcher.git
cd ipmi-launcher

REM Set up the venv
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

REM Add a Java 7 JRE at jre7\ (see "Adding the JRE" above)

REM Run from source
python main.py

REM Or build a portable .exe
.\build.bat
```

The build script outputs `dist\IPMILauncher\` — a portable folder you can zip
and share.

## Settings

A **Settings** dialog (top toolbar) lets you configure:

- **Working folder** — where downloaded JARs and native libraries are cached.
  Default is `working\` next to the .exe.
- **Wipe JAR cache before each launch** — forces a fresh download every time.
  Useful if your BMC firmware updates the JARs.

Settings persist in `settings.json` next to the .exe.

## Safety notes

- This app downloads code from your BMC over HTTP and runs it as Java with full
  filesystem permissions. **Only drop JNLPs from BMCs you trust.** Anyone who
  can write to your BMC's HTTP server can effectively run code on your machine
  through this tool.
- The Java 7 runtime is end-of-life and contains known vulnerabilities.
  The app uses it only to run JViewer; do not point it at arbitrary Java
  applications, and do not use it as a system Java.
- No credentials are stored. Session tokens (`kvmtoken`, `webcookie`) live only
  in memory while the JNLP is staged and are wiped when JViewer closes.
- Some antivirus tools flag PyInstaller-built `.exe` files as suspicious due to
  legitimate uses being mixed with malware in the wild. The source code is in
  this repo if you want to audit before running, or build it yourself.

## How it works

When you click **Launch IPMI**:

1. Parses the JNLP for the BMC's `codebase` URL, the JAR list, the main class,
   and the application arguments (kvmtoken, webcookie, etc.).
2. Downloads `JViewer.jar`, `JViewer-SOC.jar`, and `Win64.jar` from the BMC's
   HTTP endpoint into the working folder. Caches them across launches.
3. Extracts the `.dll` native libraries from `Win64.jar` into a `natives\`
   subfolder.
4. Launches `java.exe` with `-cp JViewer.jar`,
   `-Djava.library.path=<natives>`, the main class, and all the arguments
   parsed from the JNLP.
5. Polls the Java process; when it exits, captures stdout/stderr to the log
   panel and resets the UI.

No Java Web Start. No JNLP patching. No JAR re-signing. No exception site list
edits.

## Troubleshooting

**"java.exe not found at jre7\jre\bin\java.exe"** — The JRE isn't in place. See
[Adding the JRE](#adding-the-jre).

**JViewer launches but fails to connect** — The session tokens in your JNLP
are likely expired. Download a fresh JNLP from the BMC's web UI and try again.

**Antivirus quarantines IPMILauncher.exe** — False positive on the PyInstaller
bundle. Either add an exclusion or build from source.

**Drop does nothing** — Drag from File Explorer, not from a browser tab. Some
browsers don't expose drag-source URLs that File Explorer-style drops can use.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

- **JViewer** is a product of American Megatrends, Inc. This launcher is an
  unofficial wrapper; AMI is not affiliated.
- The "skip javaws and call java.exe directly" approach was suggested in a
  debugging session — credit where due.
