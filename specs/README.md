# Project Spec Files

`specs/*.json` describes the current coverage project's implementation
contract: where the coverage Spike lives, how it is run, which source tree and
gcov artifacts are authoritative, and which implementation surfaces targets may
select from.

Keep this layer project-level. Do not put "analyze MemBlock non-H" or another
coverage slice here. That belongs in `targets/*.json`.

Recommended split:

- `specs/*.json`: project implementation, runner boundary, environment
  interface, coverage Spike default arguments, available implementation
  surfaces.
- `targets/*.json`: one concrete coverage slice under a project spec, such as
  MemBlock non-H, frontend fetch, vector memory, AMO, or trigger paths.

## Coverage Spike Defaults

Each project spec must define `coverage_spike`. The case matrix runner uses
this block when `--command-template` is omitted:

```json
"coverage_spike": {
  "default_isa": "rv64imafdc_zicsr_zicntr_zihpm",
  "default_priv": "MSU",
  "default_args": [
    "--isa={default_isa}",
    "--priv={default_priv}"
  ],
  "must_include_isa_tokens": [
    "zicsr"
  ],
  "notes": []
}
```

`default_args` is a list of Spike command-line arguments inserted between
`{spike_bin}` and `{elf}`. Items may reference scalar fields in the same
`coverage_spike` object with Python format placeholders, such as
`{default_isa}`.

`must_include_isa_tokens` is a validation contract for project-supported
Spike ISA tokens that must not be dropped from `default_isa`. This is useful
when the support table uses a project/table label instead of the exact Spike
token, for example a row such as `non_RVA23_smrnmi` whose runner token is
`smrnmi`.

Keep these defaults project-owned rather than script-owned. For example, a
target such as `targets/memblock_non_h.json` points to
`specs/nanhu_v5_1_ap.json`; the runner then automatically uses the NanHu spec's
ISA/profile without every command spelling out `--isa`.

Do not blindly serialize every `isa_profile.support == "YES"` row into
`--isa`. The matrix can include platform rows such as PLIC/ACLINT/Debug and
implementation attributes that are not Spike ISA tokens. Some labels may also
be project-supported but rejected by the current coverage Spike parser. Keep
those rows in `isa_profile.support`, document them in `coverage_spike.notes`,
and include only parser-accepted runner tokens in `default_args`.

Use `--command-template` for a one-off experiment that intentionally overrides
the project default, such as adding `-l --log-commits` or trying a temporary
Spike flag.

## Unsupported Features

Use `unsupported_feature_rules` in the project spec for implementation features
whose support matrix value is `NO`. Each rule can provide:

- `tokens`: words that must not appear in a target's active
  `coverage_focus`/`scope_in`/`dimensions`/`inspection_hints`.
- `summary_exclude_regex`: summary-entry filters automatically merged with the
  target's own `summary_exclude_regex`.
- `line_exclude_regex`: `.gcov` evidence filters automatically merged with the
  target's own `line_exclude_regex`.
- `scope_warning_regex`: runner-log warning filters used by the per-case matrix
  script to flag unexpected out-of-scope execution evidence.

This keeps unsupported implementation behavior in the spec. Targets only need
to say which coverage slice they want; they do not need to duplicate every
unsupported feature regex.

For a mature project spec, every `isa_profile.support` item marked `NO` should
have an `unsupported_feature_rules` entry. Rules may be broad for non-target
areas, but keep tokens explicit enough that active target checks do not match
ordinary words or short abbreviations by accident.

After creating or editing a project spec, run:

```bash
python3 scripts/validate_spec.py specs/<name>.json
```

This validates `coverage_spike.default_args`, support status values, regex
syntax, and that every `support == "NO"` row has an
`unsupported_feature_rules` entry.

Target files refer to a project spec with:

```json
"project_spec": "specs/nanhu_v5_1_ap.json"
```

Paths are resolved as absolute paths first, then relative to the skill root, and
finally relative to the target file.
