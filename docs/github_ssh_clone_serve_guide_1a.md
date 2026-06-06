
## Quick Reference (Cheat Sheet)

### WSL2

```bash
# Phase 1 — SSH setup (one-time)
ssh-keygen -t rsa -b 2048
cat ~/.ssh/id_rsa.pub              # copy → GitHub Settings → SSH Keys
ssh -T git@github.com               # verify

# Phase 2 — Clone and install
git clone git@github.com:<owner>/<repo>.git
cd <repo>
make install

# Phase 3 — Serve
make serve                          # leave running
# try http://localhost:<port> first
# if needed:  hostname -I  →  http://<IP>:<port>
```

### Native Windows (Git Bash)

```bash
# Phase 1 — SSH setup (one-time)
ssh-keygen -t rsa -b 2048
cat ~/.ssh/id_rsa.pub              # copy → GitHub Settings → SSH Keys
ssh -T git@github.com               # verify

# Phase 2 — Clone and install
git clone git@github.com:<owner>/<repo>.git
cd <repo>
make install                        # needs 'make' installed via Chocolatey

# Phase 3 — Serve
make serve                          # leave running
# open browser → http://localhost:<port>
```

### Native Windows (PowerShell)

```powershell
# Phase 1 — SSH setup (one-time)
ssh-keygen -t rsa -b 2048
Get-Content $env:USERPROFILE\.ssh\id_rsa.pub   # copy → GitHub Settings → SSH Keys
ssh -T git@github.com                           # verify

# Phase 2 — Clone and install
git clone git@github.com:<owner>/<repo>.git
cd <repo>
make install                        # needs 'make' installed via Chocolatey

# Phase 3 — Serve
make serve                          # leave running
# open browser → http://localhost:<port>
```

# Setting Up SSH Authentication with GitHub, Cloning a Repository, and Serving It Locally

Four steps:
1. Authenticate with GitHub with SSH keys
2. Clone a repository
3. Install any dependencies
4. Serve content in a browser (locally)

Two options re environment:

- **Path A — WSL2**: More powerful environment, needs extra networking step.
- **Path B — Native Windows**: PowerShell, Command Prompt, or Git Bash; Simpler, but requires additional installs.

Identical steps for both paths are written once.
Steps that differ are marked **[WSL2]** or **[Windows]**.

## Prerequisites

**Both paths:**

- **GitHub account**.
- Web browser.

**Path A — WSL2 (additional):**

- Windows 10 or 11 with WSL2 and Linux distribution (e.g. Ubuntu)
- Use `wsl --status`to verify.

**Path B — Native Windows (additional):**

- **Git for Windows** — Default install [https://git-scm.com/download/win](https://git-scm.com/download/win).
- This gives the `git` command, an SSH client, and **Git Bash** (a lightweight Linux-like terminal).
- **A way to run `make`** 

Windows does not have `make` by default. The easiest installation via **Chocolatey** (a Windows package manager; see Appendix A). Once installed, open **Administrator** PowerShell, run: `choco install make`. If the project offers npm or pip commands as alternatives to `make`, you can skip this.

## Overview

Regardless of which path you follow, the workflow has three phases:

1. **Identity** — Generate SSH key pair, register the public key with GitHub (required).
2. **Code** — Clone the target repository, install dependencies.
3. **Serve** — Start local web server, view result in browser.

---

## Phase 1 — SSH Key Generation and GitHub Registration

### 1.1 Open a terminal

**[WSL2]** Launch Linux from Start menu (e.g. "Ubuntu") or type `wsl` in a Windows terminal.

**[Windows]** Open **Git Bash** (installed with Git for Windows — find it in the Start menu) or open **PowerShell**. Git Bash is recommended because its commands are closest to the Linux examples in most online tutorials.

> **Which terminal on Windows?** Git Bash gives you a Linux-like environment (`ls`, `cat`, `~` for your home directory). PowerShell uses Windows conventions (`dir`, `Get-Content`, `$env:USERPROFILE`). This guide provides commands for both where they differ.

### 1.2 Generate an SSH key pair

Run the following command (identical in all terminals):

```bash
ssh-keygen -t rsa -b 2048
```

**What this does:** It creates two files — a matched pair:

- A **private key** (`id_rsa`) — this never leaves your machine. Treat it like a password.
- A **public key** (`id_rsa.pub`) — this is safe to share; you will give it to GitHub.

**What you will see:** The tool asks three questions:

1. **"Enter file in which to save the key"** — press Enter to accept the default location.
   - WSL2 default: `/home/<your-username>/.ssh/id_rsa`
   - Windows default: `C:\Users\<your-username>\.ssh\id_rsa`
2. **"Enter passphrase"** — press Enter for no passphrase (convenient but less secure), or type a passphrase you will be asked for each time the key is used.
3. **"Enter same passphrase again"** — confirm.

You should see output ending with a "randomart image" — this confirms the keys were created.

> **Modern alternative:** `ssh-keygen -t ed25519` generates shorter keys with equivalent or better security. GitHub's own documentation now recommends this. If you use it, the filenames become `id_ed25519` and `id_ed25519.pub` — adjust the commands below accordingly.

### 1.3 Display the public key

You need to print the public key so you can copy it.

**[WSL2] or [Git Bash]:**

```bash
cat ~/.ssh/id_rsa.pub
```

**[PowerShell]:**

```powershell
Get-Content $env:USERPROFILE\.ssh\id_rsa.pub
```

**[Command Prompt]:**

```cmd
type %USERPROFILE%\.ssh\id_rsa.pub
```

The output will look something like:

```
ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQ... (long string) ...username@hostname
```

**Select and copy the entire output**, from `ssh-rsa` through the trailing `username@hostname`.

> **Copy/paste tips:**
>
> - **WSL2 / Git Bash**: Select text, then right-click to copy (or Ctrl+Shift+C in some terminals).
> - **PowerShell / CMD**: Select text, then press Enter to copy.

### 1.4 Register the public key on GitHub

This step is the same regardless of your environment.

1. Open your browser and go to [https://github.com](https://github.com). Log in.
2. Click your profile picture (top-right) → **Settings**.
3. In the left sidebar, click **SSH and GPG keys**.
4. Click the green **New SSH key** button.
5. Fill in the form:
   - **Title**: A name you will recognise later, e.g. `Work-laptop-WSL2` or `Home-PC-Windows`. This helps you identify which machine the key belongs to if you have several.
   - **Key type**: Leave as "Authentication Key".
   - **Key**: Paste the public key you copied in step 1.3.
6. Click **Add SSH key**. GitHub may ask you to confirm your account password.

### 1.5 Verify the connection

Back in your terminal, run:

```bash
ssh -T git@github.com
```

**First time only:** You will see a message asking whether to trust the host `github.com`. Type `yes` and press Enter. This is normal — it adds GitHub's fingerprint to your machine's list of known hosts so you are not asked again.

If everything is configured correctly, you will see:

```
Hi <your-username>! You've successfully authenticated, but GitHub does not provide shell access.
```

This confirms your machine can now authenticate with GitHub over SSH.

---

## Phase 2 — Cloning the Repository and Installing Dependencies

### 2.1 Elevated privileges (if needed)

Some projects need elevated privileges during installation. **Try without elevation first** — only escalate if you encounter "permission denied" errors.

**[WSL2]** Right-click your distribution in the Start menu → **Run as administrator**, or prefix individual commands with `sudo`.

**[Windows]** Right-click PowerShell or Git Bash in the Start menu → **Run as administrator**.

### 2.2 Navigate to where you want the project

Choose a directory. For example:

**[WSL2] or [Git Bash]:**

```bash
cd ~
mkdir -p projects
cd projects
```

**[PowerShell]:**

```powershell
cd $env:USERPROFILE
mkdir projects -ErrorAction SilentlyContinue
cd projects
```

### 2.3 Clone the repository

On the GitHub repository page, click the green **Code** button and select the **SSH** tab. Copy the URL shown (it looks like `git@github.com:<owner>/<repo>.git`). Then run:

```bash
git clone git@github.com:<owner>/<repository-name>.git
```

Replace `<owner>/<repository-name>` with the actual path.

**What this does:** It creates a local directory named `<repository-name>` containing the full repository — all files, all branches, complete version history.

After cloning, enter the directory:

```bash
cd <repository-name>
```

### 2.4 Install dependencies

```bash
make install
```

**What this does:** `make` is a build automation tool. It reads a file called `Makefile` in the current directory and executes the recipe defined under the `install` target. What that recipe actually *does* depends on the project — it might install Python packages, run `npm install`, download assets, compile code, or any combination.

**[Windows] If `make` is not recognised:** You either have not installed it yet (see Prerequisites — Path B), or the project does not use a Makefile. Check the project's `README` for alternative instructions — common alternatives include:

- `pip install -r requirements.txt` (Python projects)
- `npm install` (Node.js projects)
- `bundle install` (Ruby projects)

> **If `make install` fails**, read the error output carefully. Common causes on both platforms:
>
> - Missing system packages or runtimes (Python, Node.js, Ruby, etc.).
> - Permission issues — try running with elevation (step 2.1).
> - Missing dependencies of dependencies — the error message usually names the missing piece.

---

## Phase 3 — Serving Locally and Viewing in the Browser

### 3.1 Start the local server

```bash
make serve
```

The terminal will show output indicating the server is running, typically including a port number (e.g. `Serving on port 8000` or `Listening on 0.0.0.0:4000`). **Leave this terminal open** — closing it stops the server.

> **Note the port number.** You need it in the next step. Common defaults: 4000, 8000, 8080.

As with `make install`, if `make serve` is not available, check the project's README for the equivalent command (e.g. `npm run serve`, `python -m http.server`, `bundle exec jekyll serve`).

### 3.2 Open in your browser

**[Windows — native]** Open your browser and go to:

```
http://localhost:<port>
```

For example: `http://localhost:8000`. That is all — on native Windows the server and the browser share the same network, so `localhost` just works.

**[WSL2]** WSL2 runs inside a lightweight virtual machine with its own network interface, separate from your Windows host. This means `localhost` on the Windows side does not always reach the server inside WSL2.

**Try `localhost` first** — recent versions of Windows do forward it automatically, and it is simpler. If that does not work, fall back to the explicit IP method:

1. Open a **second** WSL2 terminal (keep the server running in the first one).
2. Run:

   ```bash
   hostname -I
   ```

   This prints the IP address of the WSL2 virtual machine, e.g. `172.25.123.45`. Copy the first address shown.

3. In your Windows browser, navigate to:

   ```
   http://172.25.123.45:<port>
   ```

You should now see the served content.

### 3.3 Stopping the server

In the terminal where the server is running, press **Ctrl+C**.

---

## Troubleshooting

### "Permission denied (publickey)" when cloning

This means GitHub did not accept your SSH key. Check the following:

- **Does the key file exist?**
  - WSL2 / Git Bash: `ls -la ~/.ssh/id_rsa.pub`
  - PowerShell: `Test-Path $env:USERPROFILE\.ssh\id_rsa.pub`
- **Does the SSH agent know about it?** Run `ssh-add -l`. If it shows "no identities", add the key manually:
  - `ssh-add ~/.ssh/id_rsa` (WSL2 / Git Bash)
  - In PowerShell, you may need to start the ssh-agent service first: `Get-Service ssh-agent | Set-Service -StartupType Manual; Start-Service ssh-agent; ssh-add $env:USERPROFILE\.ssh\id_rsa`
- **Does the key on GitHub match?** Compare the output of step 1.3 with what GitHub shows under Settings → SSH Keys. They must be character-for-character identical.

### Browser cannot reach the server

- Confirm the server is still running (check the terminal for errors or an exit message).
- Confirm you are using the correct port number.
- **[WSL2]**: Try `localhost:<port>` first. If that fails, use `hostname -I` to get the WSL2 IP and try `http://<IP>:<port>`.
- **[Windows]**: Check whether Windows Firewall is blocking the connection. Temporarily disabling it can help diagnose this.

### `make` is not recognised (Windows)

- If you installed `make` via Chocolatey, close and reopen your terminal — the `PATH` update only takes effect in new sessions.
- Verify: `make --version`. If still not found, check that `C:\ProgramData\chocolatey\bin` is in your system `PATH`.
- As an alternative, open the project's `Makefile` in a text editor, find the `install` and `serve` targets, and run the underlying commands directly (they are listed on the indented lines below each target name).

### `make: *** No rule to make target 'install'. Stop.`

The project's Makefile does not define an `install` target. Check the project's README for the correct installation command.

---

---

## Appendix A — Installing Chocolatey (Windows Package Manager)

Chocolatey lets you install command-line tools on Windows the way `apt` does on Ubuntu. You only need to do this once.

1. Open **PowerShell as Administrator** (right-click → Run as administrator).
2. Run the following command (one line):

   ```powershell
   Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
   ```

3. Close and reopen PowerShell.
4. Verify: `choco --version` should print a version number.

You can now install tools with `choco install <package>`, e.g. `choco install make`.

---

## Appendix B — Background Concepts

**SSH key pairs** work on the principle of asymmetric cryptography. The public key is like a padlock you distribute — anyone can lock a message with it. The private key is the only key that can open that padlock. When you connect to GitHub, your machine proves it holds the private key without ever transmitting it (via a challenge–response protocol). This is why the private key must never be shared or copied to another machine without good reason.

**`make`** is a decades-old Unix build tool. A `Makefile` defines named "targets" (like `install` or `serve`), each with a recipe of shell commands. When you run `make install`, it simply executes those commands in order. You can open the `Makefile` in any text editor to see exactly what a target does — there is no hidden magic.

**`git clone` vs `git pull`**: `clone` creates a brand-new local copy of a remote repository (you use this the first time). `pull` updates an existing local copy with the latest changes from the remote (you use this every time after the first).

**WSL2 networking**: WSL2 runs a real Linux kernel inside a Hyper-V virtual machine. This VM has its own virtual network adapter and IP address. When you start a server in WSL2, it listens on that VM's IP — not on your Windows host's network. Windows often sets up automatic port forwarding from `localhost` into the VM, but this forwarding can be unreliable depending on your Windows version and network configuration. The `hostname -I` approach bypasses the forwarding entirely by connecting directly to the VM's IP address.
