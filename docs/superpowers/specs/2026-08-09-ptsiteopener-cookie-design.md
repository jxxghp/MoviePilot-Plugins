# PT Site Opener Cookie Reuse Design

## Goal

When PT Site Opener opens a MoviePilot site through the remote Chrome DevTools Protocol, reuse the cookie stored in MoviePilot site management so the first request uses the saved login session.

## Confirmed Requirements

- Add a configuration switch named `reuse_site_cookie`.
- The switch defaults to enabled for new installations and for existing configurations that do not contain the field.
- Read the cookie from the active MoviePilot site object's `cookie` field.
- MoviePilot stores the cookie as a semicolon-separated string such as `name=value; name2=value2;`.
- Cookie values may contain `=` and must be split only at the first equals sign.
- Cookie injection must happen before navigating to the site URL.
- Cookie injection failures always create a MoviePilot warning log.
- When the existing `notify_enabled` switch is enabled, cookie injection failures also produce a notification; when it is disabled, no push notification is sent.
- Logs and notifications must not include cookie values.
- A cookie injection failure must not prevent the site tab from opening. The site-level failure reason is recorded and the run continues.
- Existing tab lifetime and cleanup behavior remains unchanged.

## Recommended Architecture

The plugin currently sends browser-level `Target.createTarget` commands and opens each URL immediately. The recommended flow for a site with cookie reuse enabled is:

1. Create an `about:blank` target in the background.
2. Attach to that target with `Target.attachToTarget` and `flatten: true`.
3. Parse the site's cookie string into non-empty `name=value` pairs.
4. Send one `Network.setCookie` command per pair through the attached target session, using the site URL as the cookie URL.
5. Navigate the attached target with `Page.navigate`.
6. Keep the target ID in the existing run state so the existing timer closes it after the configured TTL.

The CDP connection helper will accept an optional session ID and include it in command messages. Sites with the switch disabled, no stored cookie, or an empty cookie string will keep the existing direct `Target.createTarget` path. Site selection will retain the current active-site, selected-site, URL validation, and de-duplication behavior while preserving the site object needed for cookie access.

## Failure Handling and Notifications

Cookie parsing ignores empty segments and malformed segments without a non-empty name. A value containing additional equals signs is preserved. If attaching, setting a cookie, or navigating fails, the failure is handled at the site level and the plugin continues with the remaining sites where possible.

Each cookie injection failure is logged with warning level and only identifies the site name, URL, and sanitized error reason. Cookie names and values are never logged. When notification push is enabled, failures from one run are aggregated into one notification listing the affected site names/URLs and sanitized reasons. The normal success or completion result notification remains separate.

## Configuration and Metadata

- Add a `VSwitch` for `reuse_site_cookie` to the configuration form.
- Set the form model default to `True`.
- Read the field with a true-by-default fallback in `init_plugin` so existing saved configurations gain the feature without a migration.
- Update the README with the cookie behavior and warning rules.
- Bump the plugin and package metadata version to `1.2.0`.

## Test Plan

- Parse an empty cookie, malformed segments, values containing `=`, and multiple valid pairs.
- Verify the configuration switch is present and defaults to enabled.
- Verify a normal cookie-enabled run creates a blank target, attaches a session, sets all cookies before `Page.navigate`, and still schedules cleanup.
- Verify the direct URL path remains available when cookie reuse is disabled or no cookie is stored.
- Verify a cookie-setting failure still opens the site, logs a warning, and produces a notification only when notification push is enabled.
- Verify cookie values do not appear in warning logs or notification text.
- Preserve all existing site filtering, manual execution, cleanup, and notification tests.

## Acceptance Criteria

The configuration can enable or disable cookie reuse, active sites with stored cookies are navigated only after those cookies are set, failed injections are visible through warning logs and the configured notification channel, and no cookie secret is exposed in logs or notifications. All plugin tests, Python syntax checks, and package JSON validation pass.
