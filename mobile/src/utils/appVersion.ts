/**
 * App version surface helper.
 *
 * The value is injected at build time from `mobile/package.json` `version`
 * (see `vite.config.ts` `define.__APP_VERSION__`), keeping a single source of
 * truth for the semantic version (MAJOR.MINOR.PATCH). The release/version-bump
 * step (spec task 18.1) maintains that package version, and this surface
 * reflects whatever it is set to. (R19.4)
 *
 * A defensive guard keeps the value safe in any context where the compile-time
 * constant is not substituted (e.g. an isolated unit test runner), falling back
 * to a valid semver placeholder instead of throwing a ReferenceError.
 */
export const APP_VERSION: string =
  typeof __APP_VERSION__ === 'string' && __APP_VERSION__.length > 0
    ? __APP_VERSION__
    : '0.0.0'
