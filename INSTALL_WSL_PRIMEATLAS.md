# Setting up WSL for PrimeAtlas (manual guide)

PrimeAtlas's GUI runs natively on Windows, but its generation engines
(`prime_sieve/`, `constellation/`) run **inside WSL 2 (Ubuntu)**. On first
launch the **environment setup wizard** checks all of this and installs
whatever is missing after a single confirmation (and one UAC prompt) —
normally you never need this file.

Use this guide when the wizard cannot finish (it tells you so and offers
**Copy log**), or when you want to know exactly what it changes. Every step
below is what the wizard runs itself, in the same order
(`primeatlas/settings/env_setup.py`), and every step is safe to repeat.

Without WSL you can still use PrimeAtlas: click **Skip (run anyway)** in the wizard —
browsing existing data works, only generating new data needs WSL.

## 1. Requirements

- Windows 10 version 2004 (build 19041) or newer, or Windows 11, 64-bit.
- Hardware virtualization enabled in the BIOS/UEFI (Intel VT-x / AMD-V).
- **Inside a virtual machine** (VMware, VirtualBox, Hyper-V guest) WSL 2 needs
  *nested virtualization*: in VMware, enable "Virtualize Intel VT-x/EPT or
  AMD-V/RVI" in the VM's processor settings and power the VM off completely
  (not just restart the guest). Without it, `wsl --install` fails with errors
  such as `0x8007007E` or "the WSL 2 kernel file is not found".

## 2. Windows features

### 2.1 Enable the two required features

Run in an **administrator** PowerShell:

```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
```

### 2.2 Restart

Restart Windows if either command asks for it (exit code 3010), or if
`Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform`
reports `EnablePending`. WSL does not work until you do. After the restart,
start PrimeAtlas again — the wizard continues from here.

## 3. WSL and Ubuntu

### 3.1 Update WSL

The `wsl.exe` built into older Windows 10 has no Linux kernel and no
`--no-launch` option, so update it first (administrator PowerShell):

```powershell
wsl.exe --update --web-download
```

### 3.2 Install Ubuntu

```powershell
wsl.exe --install -d Ubuntu --no-launch
```

`--no-launch` skips Ubuntu's first-run prompt for a new UNIX user name and
password; PrimeAtlas does not need a personal account (see 3.3).

### 3.3 Make root the default user

PrimeAtlas runs every WSL command as `root` (`wsl -d Ubuntu -u root ...`).
To make a plain `wsl` terminal open as root too:

```powershell
wsl.exe -d Ubuntu -u root -e bash -c "printf '[user]\ndefault=root\n' > /etc/wsl.conf"
wsl.exe --terminate Ubuntu
```

## 4. Python inside WSL

```powershell
wsl.exe -d Ubuntu -u root -e bash -c "apt-get update -y && apt-get install -y python3-full python3-pip python3-numpy"
```

## 5. primesieve

### 5.1 Install the library

```powershell
wsl.exe -d Ubuntu -u root -e bash -c "apt-get install -y libprimesieve12 libprimesieve-dev && ldconfig"
```

### 5.2 Verify

```powershell
wsl.exe -d Ubuntu -u root -e bash -c "python3 -c 'import numpy' && python3 -c \"import ctypes; ctypes.CDLL('libprimesieve.so.12')\" && echo OK"
```

`OK` means the backend can run; this is the same check the wizard performs.

### 5.3 Optional: GMP / MPFR

Not installed by the wizard and not needed for generation — only for
research modules that may want arbitrary-precision C libraries:

```powershell
wsl.exe -d Ubuntu -u root -e bash -c "apt-get install -y libgmp-dev libmpfr-dev"
```

## 6. Why system packages, not a virtual environment

PrimeAtlas launches its WSL scripts with the distro's system `python3`
(`wsl -d Ubuntu -u root python3 ...`) and never activates a venv. Packages
installed into a venv, or with `pip install --user` for another user, are
invisible to it — install them system-wide with `apt` as shown above.

## 7. Afterwards

Start PrimeAtlas. The wizard re-checks everything; if all items are green it
does not appear again. If a step keeps failing, use **Copy log** in the
wizard and include that text when asking for help
(https://github.com/Flaman55/primeAtlas/issues).
