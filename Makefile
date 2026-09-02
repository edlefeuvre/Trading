.PHONY: help new check hooks install uninstall status logs test mirror

TS ?=
SLUG = $(shell ls -d strategies/TS$(TS)_* 2>/dev/null | head -1 | xargs -r basename)
UNIT_DIR ?= /etc/systemd/system
REPO := $(shell pwd)

help:
	@echo "make new TS=02 NAME=Funding_Fade TF=1H PLATFORM=Binance UNIVERSE=USDCp"
	@echo "make check            # STRATEGY.md vs folder consistency, all strategies"
	@echo "make hooks            # enable the pre-commit hook"
	@echo "make test TS=01       # pytest for one strategy"
	@echo "make install TS=01    # render env path into units, link, enable"
	@echo "make uninstall TS=01"
	@echo "make status           # every TS* unit"
	@echo "make logs TS=01       # follow the runner's journal"
	@echo "make mirror TS=01     # copy STRATEGY.md to mirror/ for the Claude project"

new:
	@test -n "$(TS)" -a -n "$(NAME)" -a -n "$(TF)" -a -n "$(PLATFORM)" -a -n "$(UNIVERSE)" || \
	  { echo "need TS NAME TF PLATFORM UNIVERSE"; exit 2; }
	bin/new-strategy $(TS) $(NAME) $(TF) $(PLATFORM) $(UNIVERSE)

check:
	bin/check-strategy --all

hooks:
	git config core.hooksPath .githooks
	chmod +x .githooks/pre-commit bin/*
	@echo "pre-commit hook enabled"

test:
	@test -n "$(SLUG)" || { echo "no strategy for TS=$(TS)"; exit 2; }
	cd strategies/$(SLUG) && python3 -m pytest -q src/tests

install:
	@test -n "$(SLUG)" || { echo "no strategy for TS=$(TS)"; exit 2; }
	@test -f /etc/trading/TS$(TS).env || echo "WARNING: /etc/trading/TS$(TS).env missing (see deploy/README.md)"
	mkdir -p deploy/systemd
	for u in strategies/$(SLUG)/systemd/*; do \
	  sed -e "s#{{REPO}}#$(REPO)#g" "$$u" > deploy/systemd/$$(basename $$u); \
	  sudo ln -sf $(REPO)/deploy/systemd/$$(basename $$u) $(UNIT_DIR)/$$(basename $$u); \
	done
	sudo systemctl daemon-reload
	sudo systemctl enable --now TS$(TS)-runner.service
	-sudo systemctl enable --now TS$(TS)-weekly.timer
	systemctl --no-pager status 'TS$(TS)-*' || true

uninstall:
	@test -n "$(SLUG)" || { echo "no strategy for TS=$(TS)"; exit 2; }
	-sudo systemctl disable --now 'TS$(TS)-*'
	for u in strategies/$(SLUG)/systemd/*; do sudo rm -f $(UNIT_DIR)/$$(basename $$u); done
	sudo systemctl daemon-reload

status:
	systemctl --no-pager list-units 'TS*' --all
	systemctl --no-pager list-timers 'TS*' --all

logs:
	journalctl -fu TS$(TS)-runner.service

mirror:
	@test -n "$(SLUG)" || { echo "no strategy for TS=$(TS)"; exit 2; }
	mkdir -p mirror
	cp strategies/$(SLUG)/STRATEGY.md mirror/TS$(TS)-strategy.md
	@echo "mirror/TS$(TS)-strategy.md ready — upload to the Claude Trading project as claude/TS$(TS)-strategy.md"
