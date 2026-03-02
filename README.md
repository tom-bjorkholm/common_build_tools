# Common build tools

This git repository is **not** intended to be used as a standalone git repo.

It is usually **not** useful to `git clone` this repository.

## Common build tools as submodule

This repo is intended as a submodule for some specific git repos that share
the same common build tools.

### Use in a repo already set up with this submodule

For a repo that is already set up to use this submodule clone that repo
with the command:

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

## How these common build tools are designed

### Target project characteristics

These common build tools are designed to be shared between a few projects
that share some specific requirements. These requirements are:

- pytest, pylint (inside pytest) and mypy are used to check the code.

- each project is building one or more .whl files. The .whl files are configured
  by either a `pyproject.toml` file, a `setup.py` file or both.

- the .whl files are installed in venv (virtual environment) before testing and
  the testing is performed on the installed packages in the venv.

- the project may also contain other python code (src and test folders) than
  the code that goes into the .whl files (for instance usage examples or other
  code related to documentation).

- the project has a `README.md` file in the main repo root written for developers
  of the project, and it has a `README_pypi.md` file for each package that will
  be the presentation on PyPI.org to users considering to install the package.

  - Each of these README file (README.md and README_pypi.md) shall have a test
    summary at the end.

- the results of building and testing is stored in folder `./reports` under the
  main repo root. The test summary is updated in the README files.

- there is a file `./reports/index.html` to provide easy access to build and test
  results for the programmer.

### Use and constraints

The common build tools submodule is folder `./common_build_tools` under the
main repo root.

Project specific configuration and adaptations are in folder `./custom_build_tools`
under the main repo root.

The build scripts are intended to be run from the git repo with this folder
structure. There is no installable package with the build scripts.

When the build scripts in `./common_build_tools` start they try to read
project specific information from return value (of type `BuildSpec`) from
function `custom_spec()` in file `./custom_build_tools/custom_spec.py`.
If this file is not found, this function is not found, or if the function
returns `None` the default configuration is used.
The configuration returned by `custom_spec()` only need to include the
changed compared to the default configuration.

### The build flow

After getting the default or custom `BuildSpec` the main steps in the
build flow are (from a user's point of view):

1. Discover package and folder information.
   If `BuildSpec` specifies `package_folders` only those will be built
   as .whl packages. If `package_folders` is not specified any folder that
   contains a `pyproject.toml` file, or a `setup.py` file or both is
   a folder to be built into a .whl package.

2. Verify consistency.
   Information about the packages to be built is read from `pyproject.toml`
   and `setup.py` and the information is checked for consistency.

3. Run `custom_before_clean` hooks.
   If `custom_before_clean` hooks are configured in the `BuildSpec` they
   are run.

4. Clean build artifacts.
   Temporary build folder, dist folder, `./reports` folder, pycache etc.
   are deleted,

5. Run `custom_before_build` hooks.
   If `custom_before_build` hooks are configured in the `BuildSpec` they
   are run.

6. Build discovered packages.
   The specified of discovered packages are built into .whl files.

7. Run `custom_before_install` hooks.
   If `custom_before_install` hooks are configured in the `BuildSpec` they
   are run.

8. Install built wheel packages in the virtual environment (venv)
   in dependency order.

9. Run `custom_before_test` hooks.
   If `custom_before_test` hooks are configured in the `BuildSpec` they
   are run.

10. Run flake8, pylint and mypy on discovered folders, with the virtual
    environment (venv) active. (This means that imports from the
    installed packages are working.)

11. Run pytest on discovered test folders, with the virtual
    environment (venv) active. (This means that imports from the
    installed packages are working.)

12. Run `custom_after_test` hooks.
    If `custom_after_test` hooks are configured in the `BuildSpec` they
    are run.

13. Run pydoc-markdown for every `./custom_build_tools/pydoc-markdown*.yml`
    in project root, if any.

14. Run `custom_final` hooks.
    If `custom_final` hooks are configured in the `BuildSpec` they
    are run.

15. Restore generated files with line-ending-only git changes.

16. Generate reports under `./reports/` and update README summaries.


### Building application

There are 3 entry point scripts (and 2 extra convenience scripts) for building the application:

- `./common_build_tools/src/setup_build_environment.py` Run this script first to get the environment
  set up for building and for IDE to be able to find installed dependent packages.
  This script is called internally from `do_build.py` if the environment is not already set up.


- `./common_build_tools/src/do_build.py` Run this script to build an installation package (.whl) and
  to run the tests on it in a venv (virtual environment).

- `./common_build_tools/src/clean.py` Deletes all files that was produced by the build to start over
  from a clean state.

- `./common_build_tools/src/clean_build.py` Combines the use of `clean.py`, `setup_build_environment.py`
  and `do_build.py` into one script. Pylint discover some duplicate code warnings only on a clean
  build so this is useful.

- `./common_build_tools/src/do_pypi_build.py` Builds for PyPI upload and can do the upload too.
  As the test status is added to the `README_pypi.md` only at the end of the test of the installed
  .whl file, and the `README_pypi.md` is packaged into the .whl file, this requires two consecutive
  runs of `clean_build.py`.

#### Convenience wrapper scripts

Names like `./common_build_tools/src/setup_build_environment.py` are a bit long to type.
To save some typing the script `./common_build_tools/src/create_wrappers.py` can be run once
to create thin wrapper scripts in main repo root:

- `./setup_build_environment.py`

- `./do_build.py`

- `./clean_build.py`

- `./do_pypi_build.py`

- `./clean.py`

- `./setup_build_environment.py`


#### Tests in build

The "testing" includes pytest, pylint, flake8 and mypy.

After running `do_build.py` you can open `./reports/index.html` to see all test reports.
