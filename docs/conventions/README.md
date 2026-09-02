# Conventions

`strategy-project-naming.md` and `asset-classes.md` are copies of the Board
conventions from `github.com/edlefeuvre/investment-portfolio/config/conventions/`
(the firm repo is canonical; only the Board amends them). They name **mandates**
(Paperclip projects): `[ASSET_CLASS]-[account]-[Type]`.

This repo names **systems**: `TS<nn>_<Strategy>_<TF>_<Platform>_<Universe>`. A
mandate holds several systems; a system belongs to exactly one mandate, recorded
as `mandate:` in its `STRATEGY.md` frontmatter. Systems are referred to by ID
(`TS01`) outside this repo. TS folders are underscores-only because they are
Python package paths; mandate names keep the Board's `-`/`_` rule.
