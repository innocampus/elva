# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), but uses the custom versioning scheme `MAJOR.MINOR`:

- `MAJOR` denotes the switch from test to production phase for `0 -> 1` and fundamental codebase rewrites afterwards.
- `MINOR` indicates the index of releasable features and patches made.



## 0.35 - 2025-08-19

### Fixed

- Fix unhandled empty message values from parsing



## 0.34 - 2025-08-19

### Added

- Add tests for library code: `auth`, `awareness`, `cli`, `component`, `core`, `main`, `parser`, `protocol`, `provider`, `renderer`, `server`, `store`
- Add developer setup script for installing git hooks
- Add `pre-commit` and `pre-merge-commit` git hook
- Add `ruff` config
- Add matrix testing with `nox`
- Add dependency constraints for `websockets` and `textual`
- Add `coverage` development dependency with config file
- Add link to `elva` Python package on PyPI to the docs
- Add `Dashboard` and `InputScreen` screens
- Add handling of permission errors in `server` app
- Add `free_tcp_port` function to the `server` module and tests
- Add `pass_config_for` decorator getter and tests
- Add a state subscription mechanism to `Component`
- Add an `Awareness` component
- Add awareness support to `WebsocketProvider`

### Changed

- Adapt apps `editor` (former `edit`), `chat` and `server` to rewritten CLI and define them as namespace packages
- Create a namespace package for `YTextArea` widget
- Rename the `cli` module to `main` and expose CLI functionality in a new `cli` module
- Expose project constants in the `core` module
- Update the `uv` lock file
- Update the documentation guides and API reference of all modules
- Replace legacy `tmpdir` fixture with `tmp_path` in tests
- Let `WebsocketServer` wait for all `Room`s to be inactive before stopping
- Adapt logger name for `WebsocketServer`
- Rewrite connection exception callback and connection details API for `WebsocketProvider`
- Stabilize `WebsocketProvider` tests by comparing YDoc updates instead of states
- Rewrite `SQLiteStore` update buffer without async context manager protocol
- Bump minimal Python version to 3.11

### Fixed

- Fix timing issue on component interrupt signal test
- Fix clash of `property` and `classmethod` on message enums

### Removed

- Remove unmaintained `Dockerfile`
- Remove Unix-specific signal handler from `server` app
- Remove unused dependencies
- Remove superfluous style definition for `editor`
- Remove unmaintained app modules `drive.py` and `service.py`
- Remove unmaintained `examples` and `experiments` directories
- Remove obsolete test modules
- Remove unused `click_lazy_group.py` and `click_utils.py`
- Remove `ElvaRoom` and `ElvaWebsocketServer`
- Remove `Connection` and `WebsocketConnection` classes
- Remove `ElvaWebsocketProvider`
- Remove `started` and `stopped` events
- Remove custom logic for `YTextArea` widget



## 0.33 - 2025-05-07

### Added

- Add documentation

### Changed

- Change `README.md` to link to the documentation
- Switch from `pdm` to `uv` for package management
- Use tree-sitter-language-pack instead of py-tree-sitter-languages
- Update `pyproject.toml` according to spec

### Fixed

- Fix statements querying the request path as well as types in the `server` module
- Fix lost `content` argument in `QRCode` widget
- Fix `host` and `port` arguments not applied when given via CLI to `server` app

### Removed

- Remove version specifiers in `pyproject.toml`



## 0.32 - 2025-02-13

### Added

- Add `CHANGELOG.md` up to version v0.31
- Add `git-cliff` alongside config

### Changed

- Change fill color from `transparent` to `none`

### Fixed

- Fix logo `mask` element not being in definitions



## 0.31 - 2024-12-16

### Added

- Add logo to project `README.md`
- Add licensing information to both project and logo `README.md`
- Add instructions to view RDF metadata
- Add metadata to logo and breakdown SVG files
- Add dependencies to logo-generating script
- Add logo, breakdown, generating Python script and `README.md`



## 0.30 - 2024-11-15

### Added

- Add `StatusBar` widgets and actions

### Changed

- Adapt config parameter names



## 0.29 - 2024-11-15

### Added

- Add `disconnected` event to `WebsocketConnection`
- Add `FeatureStatus` widget
- Add `ComponentStatus` widget

### Changed

- Let `Component` logging level inherit from parent logger
- Set default logging level to `INFO` in the `click` interface
- Move basic authentication handling to `WebsocketConnection`



## 0.28 - 2024-11-12

### Added

- Add `Status` widgets
- Add `ConfigInput` widget
- Add `QRCodeView` widget
- Add `ConfigPanel` widget
- Add `ConfigView` widget
- Add `StatusBar` widget

### Changed

- Move config widgets into its own module
- Store UI components in a separate subpackage
- Manage components with Worker API
- Redesign `MessageView` and colors in chat app



## 0.27 - 2024-09-26

### Changed

- Bump `websockets` version to 13.1



## 0.26 - 2024-09-26

### Fixed

- Fix unstable `TextRenderer` component



## 0.25 - 2024-09-25

### Fixed

- Fix language not set if `YTextArea` in chat app



## 0.24 - 2024-09-25

### Added

- Add `YDocument` class
- Add `YEdit` class

### Changed

- Rewrite `YTextArea`
- Make `YDocument` syntax-aware
- Adjust editor app and chat app for new `YTextArea`



## 0.23 - 2024-09-13

### Added

- Add `--user` and display `--name` options to CLI
- Add `click` callback to log order of processed `click.Parameters`
- Add basic authentication handling to service
- Add `ErrorScreen`
- Add `CredentialScreen` to chat app

### Changed

- Fall back to `Yjs` protocol if none is given
- Rework gathering context information
- Rename `--message-type` to `--messages`
- Move `LOGGER_NAME` context variable into `log` module
- Put `LOGGER_NAME` in the `click` command so that it does not get set on imports

### Fixed

- Fix minor UI issues
- Fix abort on missing username



## 0.22 - 2024-09-06

### Changed

- Update `MANIFEST.in` to also include TCSS files
- Use `src` layout for `setuptools`'s automatic discovery and no-config build
- Replace and modify `Dockerfile` to enable CLI usage
- Split `server` module in library and app modules



## 0.21 - 2024-09-06

### Added

- Add `LDAPBasicAuth` to server
- Add `CredentialScreen` to editor app

### Changed

- Make LDAP basic authentication accessible via CLI
- Move LDAPBasicAuth into the `auth` module



## 0.20 - 2024-09-04

### Added

- Add basic example for Textual authentication client

### Changed

- Change to `websockets` development dependency
- Rework `WebsocketConnection`



## 0.19 - 2024-08-30

### Added

- Add `BasicAuth` class for use in `websockets.serve`
- Add examples 
- Add LDAP self-bind function

### Fixed

- Fix inconsistent class naming



## 0.18 - 2024-08-30

### Changed

- Change to `PDM` python package manager



## 0.17 - 2024-08-30

### Changed

- Ignore private ELVA config file
- Use `ContextVar` to set the logger name accordingly



## 0.16 - 2024-08-30

### Added

- Implement ability to gather context information

### Changed

- Store identifier in file
- Update data and log paths



## 0.15 - 2024-08-27

### Added

- Add cross-sync tests
- Add cross-sync for `service` and `server`

### Changed

- Rename `message_encoding` to `message_type`
- Rewrite provider for Yjs and ELVA protocol 
- Proper naming of helper function plus comments

### Fixed

- Fix parser tests with delays

### Removed

- Remove test files



## 0.14 - 2024-08-19

### Added

- Add logging capabilities to `service`
- Add `ElvaWebsocketServer`

### Changed

- Rewrite `server` module
- Make `Component` actually wait for `before` coroutine to complete 
- change `SQLiteStore` logging
- Changes in persistence, CLI, style
- Sort `service` and `server` to `apps` subpackage
- Apply `ruff` formatting on provider module
- Rewrite `service` with `WebsocketConnection` component

### Removed

- Remove unused utils



## 0.13 - 2024-07-08

### Added

- Add `WebsocketHandler` logging handler



## 0.12 - 2024-07-05

### Fixed

- Test ruff formatting/fixing



## 0.11 - 2024-07-04

### Changed

- Replace logging `dictConfig` with custom classes and logging server

### Fixed

- Fix missing base class for `DefaultFormatter`



## 0.10 - 2024-07-04

### Changed

- Write `click` decorators consistently
- Define default paths and adapt `click` commands



## 0.9 - 2024-07-02

### Changed

- Make `Provider` choice independent of local or remote



## 0.8 - 2024-07-02

### Removed

- Remove `log` server module



## 0.7 - 2024-07-02

### Fixed

- Fix `pycrdt` imports on `metaprovider`



## 0.6 - 2024-07-02

### Changed

- Try logging to TCP socket



## 0.5 - 2024-07-02

### Changed

- Rename package-logging module



## 0.4 - 2024-07-02

### Changed

- Change to static version
- Bump `pycrdt` libraries

### Removed

- Remove `setuptools-scm` dependency and `_version.py`



## 0.3 - 2024-07-02

### Added

- Add emoji test

### Changed

- Make indices of `YText` being based on UTF-8 encoding

### Fixed

- Fix disappearing messages behind the tabview in chat app



## 0.2 - 2024-07-02

### Changed

- Switch to file logging on object and module level



## 0.1 - 2024-06-25

### Added

- Add `metaprovider`
- Add `YMessage` codecs
- Add `SQLiteStore` component 
- Add `TextRenderer` component
- Add generic `Component` class
- Add logging config
- Add test for parser self instantiation
- Add parser classes `TextParser`, `ArrayParser` and `MapParser`
- Add editor app
- Add chat app
- Add file management (read and write)
- Add `lazy_app_cli` decorator for apps
- Add command line interface (CLI) along lazy loading
- Add `Provider` class
- Add `Connection` class
- Add `.gitignore`
- Add `MkDocs` as documentation framework
- Add proper project configuration
- Add proper README.md
- Add project information
- Add Python requirements

