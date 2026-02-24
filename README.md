# Common build tools

This git repository is **not** intended to be used as a standalone git repo.

It is usually *not* useful to `git clone` this repository.

## Common build tools as submodule

This repo is intended as a submodule for some specific git repos that share
the same same common build tools.

### Use in a repo already set up with this submodule

For a repo that is already set up to use
this submodule clone that repo with the command:

````sh
git clone --recurse-submodules <repo-url> 
````

If you forgot to include the `--recurse-submodules` in your `git clone` command
you can fix it later with the command:

````sh
git submodule update --init --recursive 
````

To update the version of this submodule repo that you see in your main repo use the command:

````sh
git submodule update --remote --merge
````

### Set up a repo to start using this repo as submodule

To set up another git repo to start using this repo as submodule use the command:

````sh
cd root_of_repo
git submodule add -b master git@bitbucket.org:tom-bjorkholm/common_build_tools.git common_build_tools
````
