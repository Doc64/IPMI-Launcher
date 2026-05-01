# IPMI Launcher

A drag-and-drop replacement for the legacy Java Web Start KVM workflow used by AMI/Supermicro and ATEN BMCs.

Drop a `.jnlp` file onto the window (or use **Fetch JNLP** to log in and download one automatically), and the KVM viewer opens — no Java Web Start, no browser plugins, no JAR signing fights.

Built for servers whose BMC firmware is too old to support modern browsers or modern Java, but whose KVM client still works fine if you can get it launched.

---

## Supported BMCs

| Vendor | Firmware | Auto-fetch |
|--------|----------|-----------|
| AMI / Supermicro (MegaRAC) | Legacy (2008–2012 era) | Yes |
| ATEN iKVM | Legacy (2010 era) | Yes |
| Any BMC | Any — if you can download the `.jnlp` manually | Drag & drop |

---

## Getting started (pre-built release)

1. Download the latest zip from the [Releases](https://github.com/Doc64/IPMI-Launcher/releases) page and extract it
2. Set up the JRE — see **JRE Setup** below
3. Run `IPMILauncher.exe`

### JRE Setup

The app requires Oracle JDK 7u80 placed next to the executable. Oracle no longer distributes JDK 7 publicly without an account:

1. Go to [Oracle JDK 7 Archive](https://www.oracle.com/java/technologies/javase/javase7-archive-downloads.html)
2. Create a free Oracle account if you don't have one
3. Download **Java SE Development Kit 7u80** → **Windows x64** (`jdk-7u80-windows-x64.exe`)
4. Run the installer — it installs to `C:\Program Files\Java\jdk1.7.0_80\` by default
5. Copy that entire `jdk1.7.0_80` folder next to `IPMILauncher.exe` and rename it `jre7`

The final folder layout should look like this:

```
IPMILauncher.exe
jre7\
  jre\
    bin\
      java.exe
      unpack200.exe
```

---

## Usage

### Auto-fetch (recommended)

1. Click **+** to add a BMC profile — enter a name, BMC type, hostname/IP, username, and password
2. Select the profile from the dropdown
3. Click **Fetch JNLP** — the app logs into your BMC, downloads the KVM launcher, and stages it
4. Click **Launch IPMI**

Passwords are encrypted with Windows DPAPI and can only be decrypted by the same Windows user on the same machine.

### Manual / drag-and-drop

1. Open your BMC web interface in a browser, navigate to the KVM/iKVM page, and download the `.jnlp` file it offers
2. Drag the `.jnlp` file onto the drop zone (or use **Browse files...**)
3. Click **Launch IPMI**

---

## Known issues

- **Screen flickering** — a rendering artifact from the Java 7 runtime on modern Windows. The KVM session is fully functional; the flicker is cosmetic. No fix is available without replacing the JRE.
- **AMI launch dialog** — after auto-fetch, JViewer opens a one-click launch dialog with all fields pre-filled. Click **Remote KVM / vMedia** to connect.

---

## Building from source

```
pip install -r requirements.txt
build.bat
```

Output is in `dist\IPMILauncher\`. Add your `jre7\` folder there, then zip the whole thing to distribute.

Requires Python 3.11+, PySide6, and PyInstaller (installed automatically by `build.bat`).

---

## License

MIT
