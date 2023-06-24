#NOTE: using -C for container context
#The action is run on the submodule .github as an example
ubuntu-mk-three:## 	
	@export $(cat ~/GH_TOKEN.txt) && act -C $(PWD) -vr -W $(PWD)/.github/workflows/$@.yml
ubuntu-mk-four:## 	
	@export $(cat ~/GH_TOKEN.txt) && act -C $(PWD) -vr -W $(PWD)/.github/workflows/$@.yml