# Changelog

本文件记录本地功能变更。新功能先写入 `Unreleased`，待手动测试确认后再询问是否提交 commit。

当本文件过长时，将较早的已发布条目移动到 `docs/changelog-archive/`，这里只保留近期记录和归档链接。

## Unreleased

### Added

- Added a local changelog workflow: completed work is recorded here before commit, then waits for manual testing confirmation.
- Added preview artifacts for the 02 media-hub direction under `design-demos/`.

### Changed

- Restyled the Vue frontend toward the 02 media-hub layout with a left navigation rail, central media workspace, and right activity rail.
- Updated public-facing documentation wording to use more neutral media-library language.

### Fixed

- Made local no-backend preview safer by handling non-array `/api/videos` responses and non-JSON weekly/queue preview responses.
