# ==============================================================================
# Xattendo Desktop Widget
# Standalone GTK3 widget — zero website, zero GNOME Shell extension
# ==============================================================================

BIN_DIR        := $(HOME)/.local/bin
INSTALL_BIN    := $(BIN_DIR)/xattendo-widget
DATA_DIR       := $(HOME)/.local/share/xattendo-widget
AUTOSTART_DIR  := $(HOME)/.config/autostart
AUTOSTART_FILE := $(AUTOSTART_DIR)/xattendo-desktop-widget.desktop
BUNDLE         := dist/xattendo-widget.pyz

.PHONY: all build install uninstall run stop autostart disable-autostart check test sim-active sim-locked sim-done sim-unlinked sim-update help

all: run

# Build single-file bytecode-only executable bundle (no source code inside)
build:
	@python3 scripts/build_bundle.py

# Install standalone executable to ~/.local/bin/xattendo-widget + autostart (survives deleting source repo)
install: build
	@mkdir -p "$(BIN_DIR)" "$(AUTOSTART_DIR)"
	@cp -f "$(BUNDLE)" "$(INSTALL_BIN)"
	@chmod +x "$(INSTALL_BIN)"
	@printf '[Desktop Entry]\nType=Application\nName=Xattendo Desktop Widget\nComment=Standalone 42 Logtime & Attendo Widget\nExec=%s\nTerminal=false\nX-GNOME-Autostart-enabled=true\n' "$(INSTALL_BIN)" > "$(AUTOSTART_FILE)"
	@pkill -f "xattendo-widget/[r]un.py" 2>/dev/null || true
	@pkill -f "\.local/bin/[x]attendo-widget" 2>/dev/null || true
	@nohup "$(INSTALL_BIN)" >/dev/null 2>&1 </dev/null &
	@echo "✔ Installed standalone app to $(INSTALL_BIN)"
	@echo "✔ Autostart enabled at $(AUTOSTART_FILE)"
	@echo "✔ Safe to delete source folder — app runs independently!"

uninstall:
	@pkill -f "\.local/bin/[x]attendo-widget" 2>/dev/null || true
	@pkill -f "xattendo-widget/[r]un.py" 2>/dev/null || true
	@rm -f "$(INSTALL_BIN)" "$(AUTOSTART_FILE)"
	@rm -rf "$(DATA_DIR)"
	@echo "✔ Uninstalled Xattendo Desktop Widget."

run:
	@pkill -f "xattendo-widget/[r]un.py" 2>/dev/null || true
	@pkill -f "\.local/bin/[x]attendo-widget" 2>/dev/null || true
	@nohup python3 "$(CURDIR)/run.py" >/dev/null 2>&1 </dev/null &
	@echo "✔ Xattendo Desktop Widget started from source! (Left-click: details, Right-click: settings, Drag: move)"

stop:
	@pkill -f "xattendo-widget/[r]un.py" 2>/dev/null || true
	@pkill -f "\.local/bin/[x]attendo-widget" 2>/dev/null || true
	@echo "✔ Widget stopped."

autostart: install

disable-autostart:
	@rm -f "$(AUTOSTART_FILE)"
	@echo "✔ Autostart disabled."

check:
	@python3 -m compileall -q run.py xattendo_widget scripts/build_bundle.py
	@echo "✔ Syntax check passed."

test: check
	@python3 -m unittest discover -s tests -v

sim-active:
	@pkill -f "xattendo-widget/[r]un.py" 2>/dev/null || true
	@nohup python3 "$(CURDIR)/run.py" --simulate active >/dev/null 2>&1 </dev/null &
	@echo "✔ Simulating active session + linked 42 Intra & Attendo..."

sim-locked:
	@pkill -f "xattendo-widget/[r]un.py" 2>/dev/null || true
	@nohup python3 "$(CURDIR)/run.py" --simulate locked >/dev/null 2>&1 </dev/null &
	@echo "✔ Simulating locked workstation (amber pill)..."

sim-done:
	@pkill -f "xattendo-widget/[r]un.py" 2>/dev/null || true
	@nohup python3 "$(CURDIR)/run.py" --simulate done >/dev/null 2>&1 </dev/null &
	@echo "✔ Simulating period target reached (emerald green pill)..."

sim-unlinked:
	@pkill -f "xattendo-widget/[r]un.py" 2>/dev/null || true
	@nohup python3 "$(CURDIR)/run.py" --simulate unlinked >/dev/null 2>&1 </dev/null &
	@echo "✔ Simulating active local session with unlinked Intra & Attendo..."

sim-update:
	@pkill -f "xattendo-widget/[r]un.py" 2>/dev/null || true
	@nohup python3 "$(CURDIR)/run.py" --simulate update >/dev/null 2>&1 </dev/null &
	@echo "✔ Simulating forced in-home update screen..."

help:
	@echo "Available commands:"
	@echo "  make build             - Build single-file bytecode-only dist/xattendo-widget.pyz"
	@echo "  make install           - Build & install to ~/.local/bin/xattendo-widget + autostart"
	@echo "  make uninstall         - Remove installed app, extracted assets, and autostart"
	@echo "  make run               - Run directly from source (dev mode)"
	@echo "  make stop              - Stop the running widget"
	@echo "  make test              - Run automated unit tests"
	@echo "  make sim-active        - Live test: active session + linked Intra & Attendo"
	@echo "  make sim-locked        - Live test: locked workstation (amber)"
	@echo "  make sim-done          - Live test: period target reached (green)"
	@echo "  make sim-unlinked      - Live test: local session without linked accounts"
