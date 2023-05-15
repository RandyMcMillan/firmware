##	:
##	:		funcs-1		additional function 1
funcs-1:
	@echo "funcs-1"
.PHONY: install-dotfiles-on-remote
install-dotfiles-on-remote:
	./install-dotfiles-on-remote.sh
.PHONY: submodule submodules
submodule: submodules
##	:	submodules		git submodule --init --recursive
.ONESHELL:
submodules:
	@bash -c "rm -rf external && git submodule update --init --recursive --force || echo '.......'"
	#git submodule foreach 'git fetch --all || echo "..."; git submodule update --init --recursive || echo "............"; || echo "ignoring error..."'
#git clean -dfx'
##	:	submodules-deinit	git submodule deinit --all -f
submodules-deinit:
	@git submodule foreach 'git submodule deinit --all -f'

# vim: set noexpandtab:
# vim: set setfiletype make
