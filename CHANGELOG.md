# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

- Restored compatibility with Anki 25.09 and Python 3.13.
- Removed the missing `ankiutils` and PyObjC runtime dependencies.
- Updated browser search and deck selection to current Anki APIs.
- Added a macOS URL helper app because current Anki bundles no longer declare
  the `anki` URL scheme themselves.
- Added support for `anki://x-callback-url/search?query=...` links.

## [0.0.1] - 2023-03-29

Initial release.

[0.0.1]: https://github.com/abdnh/anki-addon-template/commits/0.0.1
