"""Genuine Edge/Playwright QA. Tokens never enter renderer inputs, URLs or headers."""

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


class QA:
    def __init__(self, root, browser):
        root.mkdir(parents=True, exist_ok=False)
        self.root, self.browser = root, browser
        self.checks, self.console, self.network, self.findings = [], [], [], []
        self.frames = {"received": 0, "sent": 0}
        self.secrets = [
            p.read_text().strip() for p in Path("artifacts/phase7/secrets").glob("*") if p.is_file()
        ]
        self.secrets.append(Path(".env.phase4").read_text().strip())
        self.contexts = []
        self.current_page = None

    def sanitize(self, text):
        for value in self.secrets:
            if value and value in text:
                self.findings.append("Credential found in browser-visible content")
                text = text.replace(value, "<redacted>")
        return text

    def page(self, url, width=1440, height=1000, timezone=None):
        context = self.browser.new_context(
            viewport={"width": width, "height": height},
            accept_downloads=True,
            **({"timezone_id": timezone} if timezone else {}),
        )
        self.contexts.append(context)

        def network(route):
            parsed = urlparse(route.request.url)
            if parsed.scheme in {"http", "https"} and parsed.hostname not in {
                "127.0.0.1",
                "localhost",
            }:
                self.network.append({"path": parsed.path, "external_request_blocked": True})
                route.abort()
            else:
                route.continue_()

        context.route("**/*", network)
        page = context.new_page()
        self.current_page = page

        def websocket(socket):
            def inspect(payload, direction):
                self.frames[direction] += 1
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8", errors="ignore")
                self.sanitize(payload)

            socket.on("framereceived", lambda payload: inspect(payload, "received"))
            socket.on("framesent", lambda payload: inspect(payload, "sent"))

        page.on("websocket", websocket)
        page.on(
            "console",
            lambda message: self.console.append(
                {"type": message.type, "text": self.sanitize(message.text)}
            ),
        )
        page.on(
            "pageerror",
            lambda error: self.console.append(
                {"type": "pageerror", "text": self.sanitize(str(error))}
            ),
        )

        def response(r):
            parsed = urlparse(r.url)
            self.network.append({"path": parsed.path, "status": r.status})
            # Inspect in memory; save no HTML, cookies, authorization headers or body dumps.
            try:
                self.sanitize(r.text())
            except Exception:
                pass

        page.on("response", response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        expect(page.get_by_role("heading", name="FactoryGraph AI", exact=True)).to_be_visible(
            timeout=60000
        )
        return page

    def check(self, name, operation):
        started = time.perf_counter()
        try:
            detail = operation()
            self.checks.append(
                {
                    "name": name,
                    "status": "PASS",
                    "seconds": time.perf_counter() - started,
                    "detail": detail,
                }
            )
            print({"check": name, "status": "PASS"}, flush=True)
        except Exception as error:
            self.checks.append(
                {
                    "name": name,
                    "status": "FAIL",
                    "seconds": time.perf_counter() - started,
                    "error": self.sanitize(str(error)),
                }
            )
            if self.current_page and not self.findings:
                self.shot(self.current_page, "failure-" + name)
            raise

    def shot(self, page, name):
        self.sanitize(page.locator("body").inner_text())
        page.screenshot(path=str(self.root / (name + ".png")), full_page=True)
        return name + ".png"

    def navigate(self, page, name, heading):
        page.get_by_text(name, exact=True).click()
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible(timeout=60000)

    def select(self, page, label, value):
        box = page.get_by_role("combobox", name=label, exact=True)
        box.click()
        if label == "Historical snapshot (UTC)":
            box.fill(value)
            expect(box).to_have_value(value)
            expect(page.get_by_role("option")).to_have_count(1, timeout=30000)
        elif page.get_by_role("option", name=value, exact=True).count() == 0:
            box.press("Control+A")
            box.press_sequentially(value, delay=100)
        page.get_by_role("option", name=value, exact=True).click()
        if label == "Machine":
            expect(page.get_by_text(f"Machine {value} · cutoff", exact=False)).to_be_visible(
                timeout=60000
            )
        elif label == "Historical snapshot (UTC)":
            expect(page.get_by_text(f"cutoff {value} · mode:", exact=False)).to_be_visible(
                timeout=60000
            )
        expect(page.locator(".stApp")).to_have_attribute(
            "data-test-script-state", "notRunning", timeout=60000
        )

    def desktop(self):
        page = self.page("http://127.0.0.1:18501")
        expect(page.get_by_role("heading", name="Fleet replay", exact=True)).to_be_visible(
            timeout=60000
        )
        self.check("desktop_initial_banner", lambda: self.shot(page, "desktop-fleet-initial"))
        self.check("fleet_genuine_replay", lambda: self.run_fleet(page))
        self.check("machine_new_alert", lambda: self.machine(page))
        self.check("cooldown", lambda: self.cooldown(page))
        self.check("below_threshold", lambda: self.below(page))
        self.check("machine_selection", lambda: self.machine17(page))
        # Fresh session for evidence/export, keeping picker tests independent.
        page = self.page("http://127.0.0.1:18501")
        self.navigate(page, "Machine analysis", "Machine analysis")
        expect(
            page.get_by_text("ALERT GENERATED · Human assessment suggested", exact=True)
        ).to_be_visible(timeout=60000)
        self.check("historical_events", lambda: self.events(page))
        self.check("graph_evidence", lambda: self.graph(page))
        self.check("report_and_json_export", lambda: self.export(page))
        self.check("transparency", lambda: self.transparency(page))
        self.check("evidence_only_missing_forecast", lambda: self.missing(page))
        self.check("keyboard_focus", lambda: self.keyboard(page))
        return page

    def run_fleet(self, page):
        self.select(page, "Cohort size", "100")
        page.get_by_role("button", name="Run verified fleet replay", exact=True).click()
        expect(
            page.get_by_text(re.compile("Building evidence-backed historical cases"))
        ).to_be_visible(timeout=10000)
        self.shot(page, "fleet-loading")
        self.checks.append({"name": "genuine_fleet_loading_indicator", "status": "PASS"})
        print({"check": "genuine_fleet_loading_indicator", "status": "PASS"}, flush=True)
        expect(page.get_by_text("Machines replayed", exact=True)).to_be_visible(timeout=120000)
        assert page.locator('[data-testid="stDataFrame"]').count() > 0
        return self.shot(page, "desktop-fleet-results")

    def machine(self, page):
        self.navigate(page, "Machine analysis", "Machine analysis")
        expect(page.get_by_text("99.983069%", exact=True)).to_be_visible(timeout=60000)
        expect(page.get_by_text("0.9996602309282403", exact=True)).to_be_visible()
        expect(
            page.get_by_text("ALERT GENERATED · Human assessment suggested", exact=True)
        ).to_be_visible()
        expect(page.locator('[data-testid="stVegaLiteChart"]')).to_have_count(4, timeout=60000)
        return self.shot(page, "desktop-machine-new-alert")

    def cooldown(self, page):
        self.select(page, "Historical snapshot (UTC)", "2015-10-16T15:00:00+00:00")
        expect(
            page.get_by_text("ALERT SUPPRESSED · Existing 24h cooldown; no new alert", exact=True)
        ).to_be_visible(timeout=60000)
        return self.shot(page, "desktop-cooldown")

    def below(self, page):
        self.select(page, "Historical snapshot (UTC)", "2015-10-01T00:00:00+00:00")
        expect(
            page.get_by_text(
                "Below threshold · Absence of an alert is not proof of equipment safety", exact=True
            )
        ).to_be_visible(timeout=60000)
        return self.shot(page, "desktop-below-threshold")

    def machine17(self, page):
        self.select(page, "Machine", "17")
        expect(page.get_by_text("Machine 17 · cutoff", exact=False)).to_be_visible(timeout=60000)
        return self.shot(page, "desktop-machine-17")

    def events(self, page):
        self.navigate(page, "Historical events", "Recorded historical events")
        assert page.locator('[data-testid="stDataFrame"]').count() > 0
        expect(page.get_by_text("Cutoff exclusive:", exact=False)).to_be_visible()
        return self.shot(page, "desktop-historical-events")

    def graph(self, page):
        self.navigate(page, "Knowledge-graph evidence", "Source-grounded graph context")
        expect(
            page.get_by_text("Model peers share a recorded category.", exact=False)
        ).to_be_visible()
        return self.shot(page, "desktop-graph-evidence")

    def export(self, page):
        self.navigate(page, "Decision-support report", "Decision-support report")
        page.get_by_text("Provenance, unknowns and limitations", exact=True).click()
        expect(page.get_by_text("Provenance, unknowns and limitations", exact=True)).to_be_visible()
        with page.expect_download(timeout=30000) as event:
            page.get_by_role("button", name="Download sanitized case JSON", exact=True).click()
        download = event.value
        dest = self.root / "download-new-alert.json"
        download.save_as(dest)
        payload = json.loads(dest.read_text())
        assert payload["request"]["machine_id"] == 1
        assert payload["prediction"]["probability"] == 0.9998306894970957
        assert "artifact_path" not in json.dumps(payload)
        return self.shot(page, "desktop-decision-report")

    def transparency(self, page):
        self.navigate(page, "Research & transparency", "Research, decisions and boundaries")
        expect(page.get_by_text("Phase 5 decision:", exact=False)).to_be_visible()
        expect(page.get_by_text("NO-GO", exact=False).first).to_be_visible()
        return self.shot(page, "desktop-transparency")

    def missing(self, page):
        self.select(page, "Snapshot eligibility", "evidence_only")
        expect(
            page.get_by_role("combobox", name="Historical snapshot (UTC)", exact=True)
        ).to_have_value("2015-01-08T00:00:00+00:00", timeout=60000)
        self.navigate(page, "Machine analysis", "Machine analysis")
        expect(page.get_by_text("Unavailable", exact=True).first).to_be_visible(timeout=60000)
        expect(
            page.get_by_text(
                "Evidence Only · Absence of an alert is not proof of equipment safety", exact=True
            )
        ).to_be_visible()
        page.get_by_text(
            "Supplementary historical forecast context · does not modify probability", exact=True
        ).click()
        expect(
            page.get_by_text("insufficient historical forecast context", exact=False).first
        ).to_be_visible()
        return self.shot(page, "desktop-evidence-only-missing-forecast")

    def keyboard(self, page):
        page.get_by_role("combobox", name="Machine", exact=True).focus()
        page.keyboard.press("Tab")
        detail = page.evaluate("""() => {const e=document.activeElement;const s=getComputedStyle(e);
          return {tag:e.tagName,role:e.getAttribute('role'),label:e.getAttribute('aria-label'),
          outline:s.outline,boxShadow:s.boxShadow};}""")
        assert detail["tag"] != "BODY"
        self.shot(page, "desktop-keyboard-focus")
        return detail

    def other_modes(self):
        page = self.page("http://127.0.0.1:18502")
        expect(page.get_by_text("1 authorized machine identities", exact=True)).to_be_visible(
            timeout=60000
        )
        assert page.get_by_role("combobox", name="Machine", exact=True).input_value() == "17"
        self.checks.append(
            {
                "name": "viewer_dashboard",
                "status": "PASS",
                "detail": self.shot(page, "viewer-machine-17"),
            }
        )
        page = self.page("http://127.0.0.1:18503")
        expect(page.get_by_text("api_unreachable", exact=False)).to_be_visible(timeout=60000)
        self.checks.append(
            {
                "name": "api_unavailable_UI",
                "status": "PASS",
                "detail": self.shot(page, "api-unavailable"),
            }
        )
        page = self.page("http://127.0.0.1:18504")
        expect(page.get_by_text("server_credential_unavailable", exact=False)).to_be_visible(
            timeout=60000
        )
        self.checks.append(
            {
                "name": "missing_credential_UI",
                "status": "PASS",
                "detail": self.shot(page, "missing-credential"),
            }
        )
        page = self.page("http://127.0.0.1:18505")
        expect(
            page.get_by_text("Verified saved-case gallery · no live graph queries", exact=True)
        ).to_be_visible(timeout=60000)
        self.select(page, "Machine", "10001")
        self.navigate(page, "Machine analysis", "Machine analysis")
        expect(
            page.get_by_text(
                "Abstained · Absence of an alert is not proof of equipment safety", exact=True
            )
        ).to_be_visible(timeout=60000)
        expect(page.get_by_text("Unavailable", exact=True).first).to_be_visible()
        self.checks.append(
            {
                "name": "explicit_gallery_unknown_abstention",
                "status": "PASS",
                "detail": self.shot(page, "gallery-unknown-abstention"),
            }
        )

    def narrow(self):
        page = self.page("http://127.0.0.1:18501", 390, 844)
        expect(page.get_by_role("heading", name="Fleet replay", exact=True)).to_be_visible(
            timeout=60000
        )
        self.shot(page, "narrow-fleet")
        # Record actual layout/focus semantics. Manual accessibility review is separate.
        detail = page.evaluate("""() => ({width:innerWidth,
          documentWidth:document.documentElement.scrollWidth,
          buttons:[...document.querySelectorAll('button')].map(e=>({label:e.getAttribute('aria-label'),
          title:e.getAttribute('title'),text:e.innerText})).slice(0,15)})""")
        self.checks.append({"name": "narrow_initial_render", "status": "PASS", "detail": detail})
        buttons = page.get_by_role("button", name=re.compile("sidebar", re.I))
        for button in buttons.all():
            if button.is_visible():
                button.click()
                break
        self.navigate(page, "Machine analysis", "Machine analysis")
        collapse = page.get_by_role("button", name="Collapse sidebar", exact=True)
        if collapse.is_visible():
            collapse.click()
        expect(page.get_by_text("99.983069%", exact=True)).to_be_visible(timeout=60000)
        expect(page.locator('[data-testid="stVegaLiteChart"]')).to_have_count(4, timeout=60000)
        page.locator('[data-testid="stVegaLiteChart"]').nth(2).scroll_into_view_if_needed()
        self.shot(page, "narrow-chart-detail")
        self.checks.append(
            {
                "name": "narrow_machine_charts",
                "status": "PASS",
                "detail": self.shot(page, "narrow-machine-charts"),
            }
        )

    def timezones(self):
        axes = []
        for timezone in ["UTC", "Europe/Berlin"]:
            page = self.page("http://127.0.0.1:18501", timezone=timezone)
            self.navigate(page, "Machine analysis", "Machine analysis")
            charts = page.locator('[data-testid="stVegaLiteChart"]')
            expect(charts).to_have_count(4, timeout=60000)
            page.wait_for_load_state("networkidle", timeout=30000)
            labels = charts.all_inner_texts()
            assert all("Timestamp (UTC)" in label for label in labels)
            axes.append(labels)
            self.shot(page, "timezone-" + timezone.replace("/", "-"))
        assert axes[0] == axes[1]
        self.checks.append(
            {
                "name": "UTC_axes_independent_of_browser_timezone",
                "status": "PASS",
                "zones": ["UTC", "Europe/Berlin"],
                "identical_axis_text": axes[0],
            }
        )

    def fault_ui(self):
        control = self.root.parent / "native-fixed"
        flag = control / "graph-unavailable"
        flag.touch()
        try:
            page = self.page("http://127.0.0.1:18506")
            page.get_by_text("Machine analysis", exact=True).click()
            expect(page.get_by_text("dependency_unavailable", exact=False)).to_be_visible(
                timeout=60000
            )
            self.checks.append(
                {
                    "name": "controlled_graph_failure_UI_no_gallery",
                    "status": "PASS",
                    "detail": self.shot(page, "graph-unavailable"),
                }
            )
        finally:
            flag.unlink()
        flag = control / "slow-case"
        flag.touch()
        try:
            page = self.page("http://127.0.0.1:18506")
            page.get_by_text("Machine analysis", exact=True).click()
            expect(page.get_by_text("case_deadline_exceeded", exact=False)).to_be_visible(
                timeout=60000
            )
            self.checks.append(
                {
                    "name": "controlled_deadline_UI",
                    "status": "PASS",
                    "detail": self.shot(page, "request-timeout"),
                }
            )
        finally:
            flag.unlink()

    def contrast(self):
        page = self.page("http://127.0.0.1:18501")
        expect(page.get_by_role("heading", name="Fleet replay", exact=True)).to_be_visible(
            timeout=60000
        )
        values = page.locator('[data-testid="stCaptionContainer"] p').evaluate_all("""
        nodes=>nodes.map(e=>{
          const p=e.closest('[data-testid="stCaptionContainer"]');
          const s=getComputedStyle(p);
          const b=e.closest('[data-testid="stSidebar"]')||document.querySelector('.stApp');
          return {text:e.innerText,color:s.color,opacity:s.opacity,
                  background:getComputedStyle(b).backgroundColor};})""")

        def rgb(s):
            return [float(v) for v in re.findall(r"[0-9.]+", s)[:3]]

        def luminance(c):
            v = [x / 255 for x in c]
            v = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
            return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]

        assert len(values) >= 3
        for value in values:
            a = float(value["opacity"])
            bg = rgb(value["background"])
            fg = rgb(value["color"])
            visible = [a * f + (1 - a) * b for f, b in zip(fg, bg, strict=True)]
            l1, l2 = sorted([luminance(visible), luminance(bg)])
            value["contrast_ratio"] = (l2 + 0.05) / (l1 + 0.05)
            assert value["contrast_ratio"] >= 4.5
        self.checks.append(
            {
                "name": "sampled_caption_contrast",
                "status": "PASS",
                "observations": values,
                "scope": "Selected captions only; no accessibility certification",
            }
        )

    def protocol(self):
        page = self.page("http://127.0.0.1:18501")
        self.check("protocol_machine", lambda: self.machine(page))
        descriptions = page.locator('[data-testid="stVegaLiteChart"]').evaluate_all("""
        nodes=>nodes.map(e=>[e,...e.querySelectorAll('[aria-label]')].map(n=>({
          role:n.getAttribute('role'),label:n.getAttribute('aria-label')})))""")
        assert len(descriptions) == 4
        for channel, labels in zip(
            ["volt", "rotate", "pressure", "vibration"], descriptions, strict=True
        ):
            assert any(channel in (r["label"] or "").lower() for r in labels)
        self.checks.append(
            {"name": "chart_accessible_names", "status": "PASS", "observations": descriptions}
        )
        self.check("protocol_events", lambda: self.events(page))
        self.check("protocol_graph", lambda: self.graph(page))
        self.check("protocol_export", lambda: self.export(page))
        self.check("protocol_transparency", lambda: self.transparency(page))
        assert self.frames["received"] > 0 and self.frames["sent"] > 0
        assert not self.findings
        self.checks.append({"name": "HTTP_websocket_console_secret_scan", "status": "PASS"})

    def save(self, status):
        result = {
            "status": status,
            "browser": self.browser.version,
            "channel": "msedge",
            "headless": True,
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "checks": self.checks,
            "console": self.console,
            "network": self.network,
            "websocket_frames_inspected_in_memory": self.frames,
            "security_findings": self.findings,
            "accessibility_certified": False,
            "actual_screenshots": [p.name for p in self.root.glob("*.png")],
            "export_file": "download-new-alert.json"
            if (self.root / "download-new-alert.json").exists()
            else None,
        }
        with (self.root / "browser_results.json").open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--scope", choices=["full", "protocol"], default="full")
    args = parser.parse_args()
    if (args.run_dir / "browser_results.json").exists():
        raise ValueError("Browser evidence exists")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        qa = QA(args.run_dir, browser)
        status = "FAIL"
        try:
            if args.scope == "protocol":
                qa.protocol()
            else:
                qa.desktop()
                qa.other_modes()
                qa.narrow()
                qa.timezones()
                qa.fault_ui()
                qa.contrast()
            assert not qa.findings
            status = "PASS"
        finally:
            qa.save(status)
            browser.close()
        print({"status": status, "checks": len(qa.checks)})
