"""Actual installed Edge acceptance. Never save credentials, cookies, headers or raw HTML."""

import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


class BrowserQA:
    def __init__(self, root, browser):
        root.mkdir(parents=True, exist_ok=False)
        self.root, self.browser = root, browser
        self.checks, self.console, self.network, self.findings = [], [], [], []
        self.telemetry_receipts = []
        self.current_page = None
        source = Path(__file__).read_bytes()
        (root / "harness.py").write_bytes(source)
        self.harness_hash = hashlib.sha256(source).hexdigest()
        self.secrets = [
            Path(p).read_text().strip()
            for p in [
                "artifacts/phase7/secrets/operator.token",
                "artifacts/phase7/secrets/viewer.token",
                ".env.phase4",
            ]
        ]

    def inspect(self, value):
        if any(secret and secret in value for secret in self.secrets):
            self.findings.append("Backend credential in browser-visible material")

    def page(self, role="operator", width=1440, height=900, zone="UTC", port=18601, ready=True):
        context = self.browser.new_context(
            viewport={"width": width, "height": height}, timezone_id=zone, accept_downloads=True
        )
        page = context.new_page()
        self.current_page = page

        def response(r):
            self.network.append({"path": urlparse(r.url).path, "status": r.status})
            try:
                self.inspect(r.text())
                if urlparse(r.url).path == "/api/data/telemetry" and r.status == 200:
                    payload = r.json()
                    cutoff = datetime.fromisoformat(payload["cutoff_exclusive"])
                    assert all(
                        datetime.fromisoformat(row["timestamp"]) < cutoff
                        for row in payload["observations"]
                    )
                    self.telemetry_receipts.append(
                        {
                            "machine": payload["machine_id"],
                            "cutoff": payload["cutoff_exclusive"],
                            "rows": len(payload["observations"]),
                            "strict_before_cutoff": True,
                            "source_sha256": payload["source_sha256"],
                        }
                    )
            except Exception:
                if urlparse(r.url).path == "/api/data/telemetry" and r.status == 200:
                    self.findings.append("Telemetry receipt failed historical clock validation")

        def request(r):
            self.inspect(json.dumps(r.headers))
            if urlparse(r.url).hostname not in {"localhost", "127.0.0.1", None}:
                self.findings.append("Unexpected external browser request")

        page.on("request", request)
        page.on("response", response)
        page.on(
            "console", lambda m: self.console.append({"type": m.type, "text": self.redact(m.text)})
        )
        page.on(
            "pageerror",
            lambda error: self.console.append(
                {"type": "pageerror", "text": self.redact(str(error))}
            ),
        )
        page.goto(f"http://localhost:{port}", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Open your workspace")).to_be_visible()
        page.get_by_label("Account", exact=True).select_option(role)
        page.get_by_label("Console password", exact=True).fill(
            Path(f"artifacts/operations_console_v2/secrets/{role}.login").read_text().strip()
        )
        page.get_by_role("button", name="Enter operations console").click()
        expect(page.get_by_role("heading", name="Fleet Overview", exact=True)).to_be_visible(
            timeout=30000
        )
        expect(page.get_by_label("Selected machine")).to_be_enabled()
        if ready:
            expect(page.get_by_role("button", name="API / graph ready", exact=False)).to_be_visible(
                timeout=30000
            )
        cookies = context.cookies()
        assert (
            len(cookies) == 1
            and cookies[0]["httpOnly"]
            and cookies[0]["secure"]
            and cookies[0]["sameSite"] == "Strict"
        )
        return context, page

    def redact(self, value):
        self.inspect(value)
        for secret in self.secrets:
            value = value.replace(secret, "<redacted>")
        return value

    def shot(self, page, name, full=False):
        self.inspect(page.locator("body").inner_text())
        assert not self.findings
        page.screenshot(path=str(self.root / (name + ".png")), full_page=full)

    def check(self, name, operation):
        tick = time.perf_counter()
        try:
            operation()
            self.checks.append(
                {"name": name, "status": "PASS", "seconds": time.perf_counter() - tick}
            )
            print({"check": name, "status": "PASS"}, flush=True)
        except Exception as error:
            self.checks.append({"name": name, "status": "FAIL", "error": self.redact(str(error))})
            if self.current_page and not self.current_page.is_closed():
                self.shot(self.current_page, "failure-" + name)
            raise

    def nav(self, page, name):
        button = page.get_by_role("button", name="Open navigation", exact=True)
        if button.is_visible():
            button.click()
        page.get_by_role("navigation", name="Main navigation").get_by_role(
            "button", name=name, exact=True
        ).click()
        expect(page.get_by_role("heading", name=name, exact=True)).to_be_visible(timeout=30000)

    def select(self, page, machine=None, snapshot=None):
        if machine:
            page.get_by_label("Selected machine", exact=True).select_option(str(machine))
        if snapshot:
            page.get_by_label("Historical snapshot UTC", exact=True).select_option(snapshot)

    def desktop(self):
        context, page = self.page()
        self.shot(page, "fleet-initial-1440x900")
        page.get_by_role("button", name="Run verified replay", exact=True).click()
        expect(page.get_by_text("Source verified", exact=True).first).to_be_visible(timeout=30000)
        self.shot(page, "fleet-replay-1440x900")
        fleet_count = sum(item["path"] == "/api/data/fleet" for item in self.network)
        page.get_by_label("Search machines").fill("17")
        expect(
            page.get_by_role("button", name="Investigate Machine 17", exact=True)
        ).to_be_visible()
        page.get_by_label("Search machines").fill("")
        page.get_by_label("Filter policy state").select_option("alert")
        expect(page.locator(".asset-table tbody tr")).to_have_count(1)
        page.get_by_label("Filter policy state").select_option("all")
        page.locator(".asset-table").get_by_role("button", name="Machine", exact=True).click()
        if page.locator(".asset-table th").first.get_attribute("aria-sort") == "descending":
            page.locator(".asset-table").get_by_role("button", name="Machine", exact=True).click()
        assert sum(item["path"] == "/api/data/fleet" for item in self.network) == fleet_count
        page.get_by_role("button", name="Investigate Machine 1", exact=True).click()
        expect(page.get_by_test_id("risk-probability")).to_have_text("99.983069%", timeout=30000)
        expect(page.get_by_test_id("threshold")).to_have_text("0.9996602309282403")
        self.shot(page, "investigation-new-alert-1440x900")
        self.checks.append(
            {"name": "fleet_filters_sort_navigation_no_replay_refetch", "status": "PASS"}
        )
        fixtures = {
            name: json.loads(Path(f"docs/examples/phase6/{name}.json").read_text())
            for name in ["new_alert", "cooldown", "non_alert", "missing_forecast"]
        }
        self.select(page, snapshot=fixtures["cooldown"]["request"]["snapshot"])
        expect(page.locator(".risk-panel .badge")).to_have_text(
            "Cooldown suppressed", timeout=30000
        )
        self.shot(page, "investigation-cooldown")
        self.select(page, snapshot=fixtures["non_alert"]["request"]["snapshot"])
        expect(page.locator(".risk-panel .badge")).to_have_text("Below threshold", timeout=30000)
        self.shot(page, "investigation-below-threshold")
        page.get_by_label("Snapshot eligibility").select_option("evidence_only")
        expect(page.locator(".risk-panel .badge")).to_have_text("Evidence only", timeout=30000)
        expect(page.get_by_test_id("risk-probability")).to_have_text("Unavailable")
        self.nav(page, "Machine Intelligence")
        page.get_by_role("tab", name="Chronos context", exact=True).click()
        expect(
            page.get_by_text("insufficient historical forecast context", exact=False)
        ).to_be_visible()
        self.shot(page, "evidence-only-missing-chronos")
        page.get_by_label("Snapshot eligibility").select_option("primary")
        expect(page.get_by_label("Historical snapshot UTC")).not_to_have_value("")
        expect(
            page.get_by_label("Historical snapshot UTC")
            .locator("option")
            .filter(has_text="16 Oct 2015, 12:00")
        ).to_have_count(1, timeout=30000)
        self.select(page, snapshot=fixtures["new_alert"]["request"]["snapshot"])
        page.get_by_role("tab", name="Sensor history", exact=True).click()
        expect(page.locator(".sensor-chart")).to_have_count(4, timeout=30000)
        self.shot(page, "machine-sensors-24h")
        for hours in [72, 168, 24]:
            page.get_by_role("button", name=f"{hours}h", exact=True).click()
            expect(page.get_by_text(f"{hours} source observations", exact=False)).to_be_visible(
                timeout=30000
            )
        for title in ["Historical errors", "Maintenance events", "Prior failures", "Provenance"]:
            page.get_by_role("tab", name=title, exact=True).click()
            expect(page.locator(".error-state")).to_have_count(0)
        self.nav(page, "Knowledge Graph Evidence")
        expect(page.locator(".graph-node").first).to_be_visible(timeout=30000)
        self.shot(page, "graph-source-projection")
        page.locator(".node-errors").first.click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_text("PdM_errors.csv", exact=True)).to_be_visible()
        expect(dialog.get_by_text("source row", exact=True)).to_be_visible()
        self.shot(page, "graph-source-drawer")
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        self.nav(page, "Alert Investigation")
        expect(page.get_by_test_id("risk-probability")).to_have_text("99.983069%", timeout=30000)
        page.get_by_role("button", name="Verified report", exact=False).click()
        expect(page.get_by_text("Provenance and audit details", exact=True)).to_be_visible()
        with page.expect_download() as event:
            page.get_by_role("button", name="Export verified JSON", exact=True).first.click()
        path = self.root / "verified-report.json"
        event.value.save_as(path)
        expected = fixtures["new_alert"]
        expected["temporal_context"]["supplementary_chronos_context"].pop("artifact_path")
        assert json.loads(path.read_text()) == expected
        self.shot(page, "verified-report", full=True)
        self.nav(page, "System and Provenance")
        page.get_by_role("button", name="Load authorized metrics", exact=False).click()
        expect(
            page.get_by_text(
                "Per-process observation; not isolated model memory or a production SLA", exact=True
            )
        ).to_be_visible(timeout=30000)
        self.shot(page, "system-provenance")
        self.nav(page, "Research Information")
        expect(page.get_by_text("Phase 5 · NO-GO", exact=True)).to_be_visible()
        self.shot(page, "research-information")
        self.nav(page, "Assets")
        assert sum(item["path"] == "/api/data/fleet" for item in self.network) == fleet_count
        self.nav(page, "Machine Intelligence")
        page.get_by_role("tab", name="Sensor history", exact=True).click()
        expect(page.locator(".sensor-chart")).to_have_count(4, timeout=30000)
        page.reload(wait_until="networkidle")
        expect(page.get_by_role("heading", name="Machine Intelligence", exact=True)).to_be_visible(
            timeout=30000
        )
        expect(page.get_by_label("Historical snapshot UTC")).to_have_value(
            fixtures["new_alert"]["request"]["snapshot"]
        )
        page.get_by_role("button", name="Refresh case", exact=True).focus()
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.tagName") == "BUTTON"
        self.shot(page, "keyboard-focus")
        self.checks.append(
            {"name": "navigation_selection_persistence_export_exact_parity", "status": "PASS"}
        )
        page.goto(
            "http://localhost:18601/?workspace=alerts&machine=10001&snapshot=2015-10-16T12%3A00%3A00%2B00%3A00"
        )
        expect(page.get_by_text("unknown_machine", exact=True).first).to_be_visible(timeout=30000)
        expect(page.locator(".risk-panel")).to_have_count(0)
        self.shot(page, "unknown-machine-full-mode")
        context.close()

    def viewports(self):
        for width, height in [(1920, 1080), (390, 844)]:
            context, page = self.page(width=width, height=height)
            self.shot(page, f"fleet-{width}x{height}")
            self.nav(page, "Machine Intelligence")
            expect(page.locator(".sensor-chart")).to_have_count(4, timeout=30000)
            self.shot(page, f"machine-{width}x{height}")
            if width == 390:
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.locator(".sensor-chart").nth(2).scroll_into_view_if_needed()
                self.shot(page, "mobile-sensor-detail")
                self.nav(page, "Knowledge Graph Evidence")
                page.locator(".graph-scroll").scroll_into_view_if_needed()
                self.shot(page, "mobile-graph-bounded-scroll")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            context.close()

    def viewer(self):
        context, page = self.page(role="viewer")
        assert page.get_by_label("Selected machine").input_value() == "17"
        expect(page.get_by_label("Selected machine").locator("option")).to_have_count(1)
        denied = page.evaluate(
            """async()=>{const r=await fetch(
            '/api/data/case?machine_id=1&snapshot_time=2015-10-16T12:00Z');
            return {status:r.status,body:await r.json()}}"""
        )
        assert denied["status"] == 403 and denied["body"]["error"] == "machine_not_authorized"
        self.nav(page, "Machine Intelligence")
        expect(page.locator(".sensor-chart")).to_have_count(4, timeout=30000)
        self.shot(page, "viewer-machine-17")
        self.nav(page, "System and Provenance")
        expect(
            page.get_by_text("Metrics are not authorized for this role", exact=True)
        ).to_be_visible(timeout=30000)
        assert page.evaluate("async()=> (await fetch('/api/data/metrics')).status") == 403
        page.get_by_role("button", name="Sign out", exact=True).click()
        expect(page.get_by_role("heading", name="Open your workspace")).to_be_visible()
        assert page.evaluate("async()=> (await fetch('/api/data/metadata')).status") == 401
        context.close()

    def timezones(self):
        axes = []
        for zone in ["UTC", "Europe/Berlin"]:
            context, page = self.page(zone=zone)
            self.nav(page, "Machine Intelligence")
            expect(page.locator(".sensor-chart")).to_have_count(4, timeout=30000)
            expect(page.get_by_text("24 source observations", exact=True)).to_be_visible(
                timeout=30000
            )
            axes.append(page.locator(".recharts-xAxis").all_inner_texts())
            self.shot(page, "timezone-" + zone.replace("/", "-"))
            context.close()
        assert axes[0] and axes[0] == axes[1]
        self.checks.append(
            {"name": "UTC_Berlin_axis_equality", "status": "PASS", "axis_text": axes[0]}
        )

    def faults(self):
        control = self.control_directory
        for flag_name, error, screenshot in [
            ("graph-unavailable", "dependency_unavailable", "graph-unavailable-no-gallery"),
            ("slow-case", "case_deadline_exceeded", "request-deadline"),
            ("busy-case", "service_busy", "safe-busy-response"),
        ]:
            flag = control / flag_name
            flag.touch(exist_ok=False)
            try:
                context, page = self.page(port=18603, ready=flag_name != "graph-unavailable")
                self.nav(page, "Alert Investigation")
                expect(page.get_by_text(error, exact=True).first).to_be_visible(timeout=30000)
                expect(page.locator(".risk-panel")).to_have_count(0)
                self.shot(page, screenshot)
                context.close()
            finally:
                flag.unlink()
            time.sleep(1.1)
        context, page = self.page(port=18603)
        statuses = page.evaluate(
            """async()=>{const a=[];for(let i=0;i<45;i++)
            a.push((await fetch('/api/data/metadata')).status);return a;}"""
        )
        assert 429 in statuses
        self.nav(page, "Alert Investigation")
        expect(page.get_by_text("rate_limit", exact=True).first).to_be_visible(timeout=30000)
        self.shot(page, "backend-rate-limit")
        context.close()
        context, page = self.page(port=18604, ready=False)
        expect(page.get_by_text("api_unreachable", exact=True).first).to_be_visible(timeout=30000)
        self.shot(page, "API-outage")
        context.close()
        context, page = self.page(port=18605, ready=False)
        expect(page.get_by_text("Explicit saved-case gallery", exact=True)).to_be_visible(
            timeout=30000
        )
        self.select(page, machine=10001)
        unknown = json.loads(Path("docs/examples/phase6/unknown_machine.json").read_text())[
            "request"
        ]["snapshot"]
        expect(page.get_by_label("Historical snapshot UTC").locator("option")).to_have_count(
            2, timeout=30000
        )
        self.select(page, snapshot=unknown)
        self.nav(page, "Alert Investigation")
        expect(page.locator(".risk-panel .badge")).to_have_text("Abstained", timeout=30000)
        self.shot(page, "explicit-gallery-abstention")
        self.nav(page, "Knowledge Graph Evidence")
        expect(page.get_by_text("Verified graph evidence unavailable", exact=True)).to_be_visible()
        expect(page.locator(".graph-node")).to_have_count(0)
        assert not any(item["type"] == "pageerror" for item in self.console)
        context.close()

    def quality(self):
        context, page = self.page()
        observations = []
        for workspace in [
            "Fleet Overview",
            "Machine Intelligence",
            "Knowledge Graph Evidence",
            "Alert Investigation",
            "Research Information",
        ]:
            self.nav(page, workspace)
            if workspace == "Machine Intelligence":
                expect(page.locator(".sensor-chart")).to_have_count(4, timeout=30000)
                box = page.locator(".sensor-chart").first.bounding_box()
                page.mouse.move(box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.45)
                expect(page.locator(".recharts-tooltip-wrapper:visible")).to_have_count(4)
                labels = page.locator(".recharts-tooltip-label").all_inner_texts()
                assert len(labels) == 4 and len(set(labels)) == 1 and labels[0].endswith("UTC")
                self.checks.append(
                    {"name": "synchronized_UTC_tooltips", "status": "PASS", "label": labels[0]}
                )
                self.shot(page, "synchronized-telemetry-tooltips")
                page.mouse.move(0, 0)
            elif workspace == "Knowledge Graph Evidence":
                expect(page.locator(".graph-node").first).to_be_visible(timeout=30000)
                boxes = page.locator(".node-errors,.node-maint,.node-failures").evaluate_all(
                    """nodes=>nodes.map(e=>{const r=e.getBoundingClientRect();
                    return {top:r.top,bottom:r.bottom}}).sort((a,b)=>a.top-b.top)"""
                )
                assert all(a["bottom"] <= b["top"] for a, b in zip(boxes, boxes[1:], strict=False))
                self.checks.append(
                    {
                        "name": "graph_event_cards_do_not_overlap",
                        "status": "PASS",
                        "event_cards": len(boxes),
                    }
                )
            elif workspace == "Alert Investigation":
                expect(page.get_by_test_id("risk-probability")).to_have_text(
                    "99.983069%", timeout=30000
                )
            values = page.evaluate("""() => {
              const rgb=s=>(s.match(/[0-9.]+/g)||[]).map(Number);
              const lum=c=>{const v=c.slice(0,3).map(x=>{
                x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4});
                return v[0]*.2126+v[1]*.7152+v[2]*.0722};
              const nodes=document.querySelectorAll(
                'p,span,small,button,a,th,td,dt,dd,h1,h2,h3,label');
              return [...nodes].filter(e=>{
                const r=e.getBoundingClientRect(),s=getComputedStyle(e);
                return !e.children.length&&e.innerText.trim()&&r.width&&r.height
                  &&r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight
                  &&s.visibility!=='hidden'&&!e.closest('button:disabled');
              }).map(e=>{const s=getComputedStyle(e);let p=e,bg;
                while(p){bg=rgb(getComputedStyle(p).backgroundColor);if(bg.length===3||bg[3]===1)break;p=p.parentElement;}
                bg=bg&&bg.length>=3?bg:[243,245,248];const fg=rgb(s.color);
                const a=lum(fg),b=lum(bg),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
                const large=parseFloat(s.fontSize)>=24
                  ||(parseFloat(s.fontSize)>=18.66&&parseInt(s.fontWeight)>=700);
                return {text:e.innerText.slice(0,70),className:e.className,color:s.color,
                  background:bg,ratio,minimum:large?3:4.5};
              });}""")
            observations.append(
                {
                    "workspace": workspace,
                    "sampled_text_elements": len(values),
                    "failures": [v for v in values if v["ratio"] < v["minimum"]],
                    "minimum_ratio": min(v["ratio"] for v in values),
                }
            )
        with (self.root / "contrast.json").open("x", encoding="utf-8") as output:
            json.dump(observations, output, indent=2)
        self.shot(page, "quality-research")
        context.close()
        assert not any(value["failures"] for value in observations), (
            "Visible text contrast samples need correction"
        )
        self.checks.append(
            {
                "name": "visible_text_contrast_samples",
                "status": "PASS",
                "scope": "Bounded visible text, no accessibility certification",
            }
        )

    def probe(self):
        context, page = self.page()
        expect(page.get_by_text("Registered machines", exact=True)).to_be_visible()
        self.shot(page, "fleet-before-replay-desktop")
        page.get_by_role("button", name="Run verified replay", exact=True).click()
        expect(page.get_by_text("Source verified", exact=True).first).to_be_visible(timeout=30000)
        self.shot(page, "fleet-after-replay-desktop")
        page.get_by_role("button", name="Investigate Machine 1", exact=True).click()
        expect(page.get_by_test_id("risk-probability")).to_have_text("99.983069%", timeout=30000)
        expect(page.get_by_test_id("threshold")).to_have_text("0.9996602309282403")
        self.shot(page, "alert-investigation-desktop")
        context.close()

    def save(self, status):
        with (self.root / "browser_results.json").open("x", encoding="utf-8") as output:
            json.dump(
                {
                    "status": status,
                    "checks": self.checks,
                    "browser": self.browser.version,
                    "headless": True,
                    "console": self.console,
                    "network": self.network,
                    "security_findings": self.findings,
                    "telemetry_receipts": self.telemetry_receipts,
                    "screenshots": [p.name for p in self.root.glob("*.png")],
                    "harness_sha256": self.harness_hash,
                },
                output,
                indent=2,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--scope", choices=["probe", "full", "fault", "quality"], default="full")
    parser.add_argument(
        "--control-dir",
        type=Path,
        default=Path("artifacts/operations_console_v2/study/fault-control"),
    )
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        qa = BrowserQA(args.run_dir, browser)
        qa.control_directory = args.control_dir
        status = "FAIL"
        try:
            if args.scope == "probe":
                qa.check("genuine_operator_fleet_investigation", qa.probe)
            elif args.scope == "fault":
                qa.check("genuine_BFF_controlled_error_contracts", qa.faults)
            elif args.scope == "quality":
                qa.check("bounded_accessibility_quality", qa.quality)
            else:
                qa.check("genuine_desktop_workflow", qa.desktop)
                qa.check("responsive_viewports", qa.viewports)
                qa.check("viewer_role_and_revocation", qa.viewer)
                qa.check("browser_timezones", qa.timezones)
            assert not qa.findings
            status = "PASS"
        finally:
            qa.save(status)
            browser.close()
