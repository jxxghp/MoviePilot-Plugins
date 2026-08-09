# PT Site Opener Cookie Reuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse each active MoviePilot site's stored cookie when opening it through remote CDP, with a default-on configuration switch and visible failure warnings.

**Architecture:** Keep the existing synchronous browser-level CDP client and add optional target session IDs to command messages. For sites with a stored cookie, create an `about:blank` target, attach to it, set cookies through the attached `Network` session, and navigate through the attached `Page` session. Sites without cookie reuse continue using the current direct target creation path; cookie failures are collected per site, logged without secrets, and optionally pushed through the existing notification channel.

**Tech Stack:** Python 3, MoviePilot V2 plugin API, synchronous Chrome DevTools Protocol over `websocket-client`, `unittest`, APScheduler form metadata.

---

### Task 1: Add failing cookie parsing and configuration tests

**Files:**
- Modify: `tests/v2/ptsiteopener/test_plugin.py`
- Test: `tests/v2/ptsiteopener/test_plugin.py`

- [ ] **Step 1: Write the failing tests**

Add these tests to `PluginTestCase`:

```python
def test_parse_site_cookie_preserves_equals_and_skips_invalid_segments(self):
    self.assertEqual(
        self.module.parse_site_cookie(
            "sid=abc==; invalid; theme=dark; =missing-name;"
        ),
        [("sid", "abc=="), ("theme", "dark")],
    )
    self.assertEqual(self.module.parse_site_cookie(None), [])

def test_cookie_reuse_switch_defaults_to_enabled(self):
    plugin = self.module.PTSiteOpener()
    plugin.init_plugin({"enabled": True})

    form, model = plugin.get_form()

    self.assertTrue(model["reuse_site_cookie"])
    switches = []

    def collect(items):
        for item in items:
            if item.get("component") == "VSwitch":
                switches.append(item)
            collect(item.get("content", []))

    collect(form)
    self.assertIn(
        "reuse_site_cookie",
        [item.get("props", {}).get("model") for item in switches],
    )
```

- [ ] **Step 2: Run the tests to verify the expected failure**

Run:

```powershell
python -m unittest tests.v2.ptsiteopener.test_plugin.PluginTestCase.test_parse_site_cookie_preserves_equals_and_skips_invalid_segments tests.v2.ptsiteopener.test_plugin.PluginTestCase.test_cookie_reuse_switch_defaults_to_enabled -q
```

Expected result: `FAIL` because `parse_site_cookie` and the `reuse_site_cookie` model field do not exist yet.

### Task 2: Implement cookie parsing and the default-on switch

**Files:**
- Modify: `plugins.v2/ptsiteopener/__init__.py:20-410`
- Test: `tests/v2/ptsiteopener/test_plugin.py`

- [ ] **Step 1: Add the minimal parser and configuration state**

Add a public helper near `select_site_urls`:

```python
def parse_site_cookie(cookie: Any) -> List[Tuple[str, str]]:
    if not isinstance(cookie, str):
        return []
    pairs = []
    for segment in cookie.split(";"):
        name, separator, value = segment.strip().partition("=")
        if not separator or not name:
            continue
        pairs.append((name.strip(), value.strip()))
    return pairs
```

In `__init__`, initialize `self._reuse_site_cookie = True`. In `init_plugin`, read it with `bool(config.get("reuse_site_cookie", True))`. Add a `VSwitch` using model `reuse_site_cookie` and label `复用站点 Cookie`, then add `"reuse_site_cookie": True` to the returned form model.

- [ ] **Step 2: Run the focused tests to verify they pass**

Run:

```powershell
python -m unittest tests.v2.ptsiteopener.test_plugin.PluginTestCase.test_parse_site_cookie_preserves_equals_and_skips_invalid_segments tests.v2.ptsiteopener.test_plugin.PluginTestCase.test_cookie_reuse_switch_defaults_to_enabled -q
```

Expected result: both tests pass.

- [ ] **Step 3: Commit the parser and switch**

```powershell
git add plugins.v2/ptsiteopener/__init__.py tests/v2/ptsiteopener/test_plugin.py
git commit -m "feat: add PT site cookie reuse setting"
```

### Task 3: Add target-session support to the CDP client

**Files:**
- Modify: `plugins.v2/ptsiteopener/__init__.py:100-140`
- Modify: `tests/v2/ptsiteopener/test_plugin.py:330-380`
- Test: `tests/v2/ptsiteopener/test_plugin.py`

- [ ] **Step 1: Add a failing session-message test**

Add a socket double and test that invokes `_CdpConnection.send` with a session ID and asserts the outgoing JSON contains it:

```python
def test_cdp_send_includes_target_session_id(self):
    socket = FakeSocket([json.dumps({"id": 1, "result": {}})])
    connection = self.module._CdpConnection(socket)

    connection.send("Network.enable", session_id="session-1")

    message = json.loads(socket.sent[0])
    self.assertEqual(message["sessionId"], "session-1")
```

`FakeSocket` should expose `sent`, implement `send`, `recv`, and `close`, and return the queued response from `recv`.

- [ ] **Step 2: Run the test to verify the expected failure**

Run:

```powershell
python -m unittest tests.v2.ptsiteopener.test_plugin.PluginTestCase.test_cdp_send_includes_target_session_id -q
```

Expected result: `ERROR` because `_CdpConnection.send` does not accept `session_id`.

- [ ] **Step 3: Implement optional session IDs**

Change the signature to `send(self, method, params=None, session_id=None)`. Build the existing message dictionary, add `message["sessionId"] = session_id` only when a session ID is supplied, and send it unchanged for all existing browser-level commands.

- [ ] **Step 4: Run the test to verify it passes**

Run the same focused unittest command. Expected result: `OK`.

- [ ] **Step 5: Commit the CDP transport change**

```powershell
git add plugins.v2/ptsiteopener/__init__.py tests/v2/ptsiteopener/test_plugin.py
git commit -m "feat: support CDP target sessions"
```

### Task 4: Inject cookies before site navigation and report failures

**Files:**
- Modify: `plugins.v2/ptsiteopener/__init__.py:460-620`
- Modify: `tests/v2/ptsiteopener/test_plugin.py:270-390`
- Test: `tests/v2/ptsiteopener/test_plugin.py`

- [ ] **Step 1: Extend the CDP fake and add failing integration tests**

Extend `FakeCdp.send` for these commands:

```python
if method == "Target.createTarget":
    self.next_target += 1
    self.created.append((params, session_id))
    return {"targetId": f"opened-{self.next_target}"}
if method == "Target.attachToTarget":
    return {"sessionId": "session-1"}
if method == "Network.setCookie":
    self.cookie_calls.append((params, session_id))
    return {"success": True}
if method == "Page.navigate":
    self.navigate_calls.append((params, session_id))
    return {"frameId": "frame-1"}
```

Add a cookie-enabled run test with a site object containing `cookie="sid=abc==; theme=dark;"`. Assert the command order is `Target.createTarget(about:blank)`, `Target.attachToTarget`, two `Network.setCookie` commands, then `Page.navigate` with the site URL and `session-1`; assert the run still creates its cleanup timer.

Add a failure test where `Network.setCookie` raises `RuntimeError("cookie rejected")`, with `notify_enabled=True`. Assert the site URL is returned as opened, the logger contains a warning identifying the site but not `abc==`, and one notification contains the site URL and failure reason but not the cookie value.

- [ ] **Step 2: Run the integration tests to verify the expected failure**

Run:

```powershell
python -m unittest tests.v2.ptsiteopener.test_plugin.PluginTestCase.test_run_once_injects_site_cookie_before_navigation tests.v2.ptsiteopener.test_plugin.PluginTestCase.test_cookie_injection_failure_logs_and_notifies_without_exposing_value -q
```

Expected result: `ERROR` or `FAIL` because the current run path opens URLs directly and the fake does not yet receive the new commands.

- [ ] **Step 3: Preserve site objects during filtering**

Add `select_sites(sites, site_mode, selected_site_ids)` that applies the existing active, selected-ID, valid HTTP(S), and URL de-duplication rules while returning site objects. Refactor `select_site_urls` to return `[site.url for site in select_sites(...)]` so existing tests and callers retain their current URL-only contract.

- [ ] **Step 4: Add the per-site open flow**

Add `_open_site(cdp, site, run) -> Tuple[Optional[str], Optional[str]]`. When cookie reuse is disabled or `parse_site_cookie(site.cookie)` is empty, call the existing direct `Target.createTarget` URL path and return `(target_id, None)`. Otherwise:

1. Create `about:blank` in the background.
2. Attach with `Target.attachToTarget` and capture `sessionId`.
3. Call `Network.setCookie` for each parsed pair with `name`, `value`, and the site URL.
4. On each set failure, collect a site-level sanitized reason and log a warning without the cookie value. Build the reason with `_sanitize_error(error, [value for _, value in cookie_pairs])`, which replaces every non-empty cookie value in `str(error)` with `[redacted]`.
5. Call `Page.navigate` with the site URL and target session, even when a cookie set failed.
6. If attachment itself fails, close the blank target best-effort and fall back to direct URL target creation so the site still opens.

Return the created target ID and an optional cookie failure description. Append only the target ID to `run.target_ids`.

- [ ] **Step 5: Aggregate warning notifications**

Add `_record_cookie_failures(failures: List[Tuple[str, str, str]])`. For each `(site_name, url, reason)`, call `logger.warning(f"站点 Cookie 注入失败 {site_name} ({url})：{reason}")`. When `self._notify_enabled` is true, send one aggregated `NotificationType.Plugin` message for the run. Do not include `site.cookie`, cookie names, or cookie values in the message. Call it after the site-open loop and before the normal result notification.

- [ ] **Step 6: Run the integration tests to verify they pass**

Run the two focused tests again. Expected result: `OK`.

- [ ] **Step 7: Run the complete plugin test module**

```powershell
python -m unittest tests.v2.ptsiteopener.test_plugin -q
```

Expected result: all existing and new tests pass.

- [ ] **Step 8: Commit the CDP cookie flow**

```powershell
git add plugins.v2/ptsiteopener/__init__.py tests/v2/ptsiteopener/test_plugin.py
git commit -m "feat: reuse MoviePilot site cookies in CDP"
```

### Task 5: Update user-facing documentation and metadata

**Files:**
- Modify: `plugins.v2/ptsiteopener/README.md`
- Modify: `package.v2.json`
- Modify: `plugins.v2/ptsiteopener/__init__.py`

- [ ] **Step 1: Document the switch and warning behavior**

Add the `复用站点 Cookie` option, explain that it uses the cookie saved in MoviePilot site management before the first request, and state that failed injections are logged and optionally pushed through the existing notification switch without exposing cookie values.

- [ ] **Step 2: Bump metadata to 1.2.0**

Set `plugin_version` and the `PTSiteOpener` package entry to `1.2.0`, and add a `1.2.0` history item describing cookie reuse and failure notifications.

- [ ] **Step 3: Validate metadata**

```powershell
python -m json.tool package.v2.json > $null
python -m py_compile plugins.v2/ptsiteopener/__init__.py
git diff --check
```

Expected result: all commands exit successfully.

- [ ] **Step 4: Commit documentation and metadata**

```powershell
git add plugins.v2/ptsiteopener/README.md plugins.v2/ptsiteopener/__init__.py package.v2.json
git commit -m "docs: document PT site cookie reuse"
```

### Task 6: Final verification

**Files:**
- Verify: `plugins.v2/ptsiteopener/__init__.py`
- Verify: `tests/v2/ptsiteopener/test_plugin.py`
- Verify: `package.v2.json`

- [ ] **Step 1: Run the complete focused verification set**

```powershell
python -m unittest tests.v2.ptsiteopener.test_plugin -q
python -m py_compile plugins.v2/ptsiteopener/__init__.py
python -m json.tool package.v2.json > $null
git diff --check
git status --short --branch
```

Expected result: all tests pass, both validators exit successfully, `git diff --check` is clean, and status lists only intentional commits with no uncommitted changes.

- [ ] **Step 2: Inspect the final behavior contract**

Confirm that the form model defaults `reuse_site_cookie` to `True`, direct opening remains available when disabled, `Network.setCookie` precedes `Page.navigate`, cookie values are absent from log/notification assertions, and cleanup still closes only the run's target IDs.

- [ ] **Step 3: Record the final commit and test output**

Use the fresh command output and `git log --oneline -5` in the handoff. Do not claim completion without the verification output.
