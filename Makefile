# Simple Makefile for appimage-installer

BINDIR = $(HOME)/.local/bin

install:
	mkdir -p $(BINDIR)
	install -m 755 appimage-installer.py $(BINDIR)/appimage-installer
	@echo "Installed to $(BINDIR)/appimage-installer"
	@if ! echo $$PATH | grep -q "$(BINDIR)"; then \
		echo 'export PATH="$$HOME/.local/bin:$$PATH"' >> ~/.zshrc; \
		echo "Added $(BINDIR) to PATH in ~/.zshrc"; \
		echo "Run 'source ~/.zshrc' or restart your terminal"; \
	fi

uninstall:
	rm -f $(BINDIR)/appimage-installer

.PHONY: install uninstall