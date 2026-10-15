import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const output = process.env.TEST_RESULTS_DIR || "test-results/acceptance";
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: "msedge", headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1080 }, locale: "zh-CN", timezoneId: "Asia/Shanghai",
});
const results = [];
const runtimeErrors = [];
const health = await (await context.request.get("http://127.0.0.1:8000/api/health")).json();
const deviceId = `QA-UI-${Date.now().toString().slice(-7)}`;
const docTitle = `文件导入验收-${Date.now()}`;
let page;

async function fresh() {
  if (page) await page.close();
  page = await context.newPage();
  page.setDefaultTimeout(10_000);
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  await page.goto("http://127.0.0.1:5173");
  await page.getByText("设备数据已同步", { exact: true }).waitFor();
}
async function nav(title) {
  await page.getByRole("navigation").getByRole("button", { name: title, exact: true }).click();
}
async function check(name, run) {
  const start = Date.now();
  try {
    await run();
    results.push({ name, status: "passed", ms: Date.now() - start });
    console.log(`PASS ${name}`);
  } catch (error) {
    results.push({ name, status: "failed", ms: Date.now() - start, error: error.message });
    if (page && !page.isClosed()) {
      await page.screenshot({ path: `${output}/failure-${results.length}.png`, fullPage: true }).catch(() => {});
    }
    console.log(`FAIL ${name}: ${error.message}`);
  }
}
async function fillRegistration(id) {
  await page.getByPlaceholder("例如 P-109，仅字母、数字、下划线和短横线").fill(id);
  await page.getByPlaceholder("设备名称", { exact: true }).fill("浏览器登记验收电机");
  await page.getByPlaceholder("所属区域", { exact: true }).fill("浏览器验收区域");
  await page.getByRole("dialog").getByRole("combobox").selectOption("motor");
}

try {
  await check("overview statistics and temperature/vibration chart", async () => {
    await fresh();
    assert.equal(await page.locator(".stat-card").count(), 4);
    await page.getByRole("button", { name: "振动", exact: true }).click();
    await page.getByText("单位 mm/s", { exact: true }).waitFor();
    await page.getByRole("button", { name: "温度", exact: true }).click();
    await page.getByText("单位 °C", { exact: true }).waitFor();
  });
  await check("device filters, area search and empty result", async () => {
    await fresh();
    await nav("设备管理");
    const devices = await (await context.request.get("http://127.0.0.1:8000/api/devices")).json();
    for (const [label, kind] of [["水泵", "pump"], ["电机", "motor"]]) {
      await page.getByRole("button", { name: label, exact: true }).click();
      assert.equal(await page.locator("tbody tr").count(), devices.filter((item) => item.kind === kind).length);
    }
    await page.getByRole("button", { name: "全部设备", exact: true }).click();
    await page.getByPlaceholder("搜索设备名称、编号或区域").fill(devices[0].area);
    assert.equal(await page.locator("tbody tr").count(), devices.filter((item) => `${item.id}${item.name}${item.area}`.includes(devices[0].area)).length);
    await page.getByPlaceholder("搜索设备名称、编号或区域").fill("no-such-device-qa");
    await page.getByText("没有匹配的设备", { exact: true }).waitFor();
  });
  await check("register motor and show offline details", async () => {
    await fresh();
    await nav("设备管理");
    await page.getByRole("button", { name: "添加设备", exact: true }).click();
    assert(await page.getByRole("button", { name: "登记设备", exact: true }).isDisabled());
    await fillRegistration(deviceId);
    await page.getByRole("button", { name: "登记设备", exact: true }).click();
    await page.getByText("设备已登记，等待首条采样数据。", { exact: true }).waitFor();
    await page.getByPlaceholder("搜索设备名称、编号或区域").fill(deviceId);
    assert.equal(await page.locator("tbody tr").count(), 1);
    assert((await page.locator("tbody tr").innerText()).includes("暂无采样"));
    await page.getByRole("button", { name: "详情", exact: true }).click();
    await page.getByRole("dialog").waitFor();
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({ state: "detached" });
  });
  await check("duplicate registration surfaces server conflict", async () => {
    await fresh();
    await nav("设备管理");
    await page.getByRole("button", { name: "添加设备", exact: true }).click();
    await fillRegistration(deviceId);
    await page.getByRole("button", { name: "登记设备", exact: true }).click();
    await page.getByText("设备编号已存在", { exact: true }).waitFor();
    await page.getByRole("button", { name: "关闭", exact: true }).click();
  });
  await check("alert status filters, search and device analysis shortcut", async () => {
    await fresh();
    await nav("监控告警");
    const alerts = await (await context.request.get("http://127.0.0.1:8000/api/alerts")).json();
    for (const [label, status] of [["待确认", "open"], ["已确认", "acknowledged"]]) {
      await page.getByRole("button", { name: label, exact: true }).click();
      assert.equal(await page.locator("tbody tr").count(), alerts.filter((item) => item.status === status).length);
    }
    await page.getByRole("button", { name: "全部告警", exact: true }).click();
    await page.getByPlaceholder("搜索设备编号或告警内容").fill("P-101");
    assert.equal(await page.locator("tbody tr").count(), alerts.filter((item) => `${item.device_id}${item.message}`.includes("P-101")).length);
    if (await page.locator("tbody tr").count()) {
      await page.locator("tbody tr").first().getByRole("button", { name: /分析/ }).click();
      assert.equal(await page.getByRole("combobox", { name: "分析设备" }).inputValue(), "P-101");
    }
  });
  await check("knowledge .md file import, category and original content", async () => {
    await fresh();
    await nav("运维知识库");
    await page.getByRole("button", { name: "导入文档", exact: true }).click();
    assert(await page.getByRole("button", { name: "导入并建立索引", exact: true }).isDisabled());
    const content = "浏览器文件验收：检查水泵轴承润滑，复核振动传感器位置，记录维护时间、设备编号和巡检结论。";
    await page.locator('input[type="file"]').setInputFiles({ name: `${docTitle}.md`, mimeType: "text/markdown", buffer: Buffer.from(content) });
    assert.equal(await page.getByPlaceholder("例如：循环水泵维修手册").inputValue(), docTitle);
    await page.getByRole("dialog").getByRole("combobox").selectOption("procedure");
    await page.getByRole("button", { name: "导入并建立索引", exact: true }).click();
    const card = page.locator(".document-card").filter({ has: page.getByRole("heading", { name: docTitle, exact: true }) });
    await card.waitFor({ timeout: 90_000 });
    assert((await card.innerText()).includes("操作规程"));
    await card.getByRole("button", { name: "查看原文" }).click();
    assert.equal(await page.locator(".document-content").innerText(), content);
    await page.keyboard.press("Escape");
  });
  await check("knowledge oversized upload is rejected", async () => {
    await fresh();
    await nav("运维知识库");
    await page.getByRole("button", { name: "导入文档", exact: true }).click();
    await page.locator('input[type="file"]').setInputFiles({ name: "oversize.txt", mimeType: "text/plain", buffer: Buffer.alloc(300_001, 65) });
    await page.getByText("请选择小于 300KB 的文本文件。", { exact: true }).waitFor();
    assert.equal(await page.getByPlaceholder("粘贴手册、案例或操作规程正文，至少 20 个字符…").inputValue(), "");
  });
  await check("knowledge delete cancel preserves document; accept removes it", async () => {
    await fresh();
    await nav("运维知识库");
    const remove = page.getByRole("button", { name: `删除 ${docTitle}`, exact: true });
    page.once("dialog", (dialog) => dialog.dismiss());
    await remove.click();
    assert(await page.getByRole("heading", { name: docTitle, exact: true }).isVisible());
    page.once("dialog", (dialog) => dialog.accept());
    await remove.click();
    await page.getByRole("heading", { name: docTitle, exact: true }).waitFor({ state: "detached" });
  });
  await check("saved real diagnosis and follow-up reload with evidence", async () => {
    await fresh();
    await nav("智能运维助手");
    const sessions = await (await context.request.get("http://127.0.0.1:8000/api/sessions")).json();
    const session = sessions.find((item) => item.device_id === "P-101");
    assert(session, "Smoke test did not save a P-101 session");
    await page.locator(".session-list button").filter({ hasText: session.title }).first().click();
    await page.locator(".chat-message.assistant").first().waitFor();
    assert((await page.locator(".chat-message.assistant").count()) >= 2);
    if (health.llm_mode === "ark") assert((await page.locator(".report-markdown").count()) >= 2);
    await page.locator(".evidence-details summary").first().click();
    assert((await page.locator(".evidence-item").count()) >= 1);
    await page.screenshot({ path: `${output}/saved-analysis.png`, fullPage: true });
    for (const width of [320, 390]) {
      await page.setViewportSize({ width, height: 844 });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      assert.equal(overflow, false, `Saved report overflows at ${width}px`);
      await page.screenshot({ path: `${output}/saved-analysis-${width}.png`, fullPage: true });
    }
    await page.setViewportSize({ width: 1440, height: 1080 });
    await page.getByRole("combobox", { name: "分析设备" }).selectOption(deviceId);
    assert.equal(await page.locator(".chat-message").count(), 0);
    await page.getByRole("heading", { name: "从一个问题，开始了解设备。", exact: true }).waitFor();
  });
  await check("assistant keyboard and explicit SSE error handling (injected response)", async () => {
    await fresh();
    await nav("智能运维助手");
    await page.route("**/api/analysis", (route) => route.fulfill({
      status: 200, contentType: "text/event-stream",
      body: 'event: error\ndata: {"message":"验收注入：模型服务暂不可用"}\n\n',
    }));
    const input = page.locator(".composer textarea");
    assert(await page.getByRole("button", { name: "发送问题", exact: true }).isDisabled());
    await input.fill("键盘发送验收");
    await input.press("Shift+Enter");
    assert.equal(await page.locator(".chat-message.user").count(), 0);
    await input.press("Enter");
    await page.getByText("验收注入：模型服务暂不可用", { exact: true }).waitFor();
    assert.equal(await page.locator(".chat-message.assistant").count(), 0);
    assert(await page.getByRole("button", { name: "发送问题", exact: true }).isVisible());
  });
  await check("assistant cancellation releases UI (injected delayed request)", async () => {
    await fresh();
    await nav("智能运维助手");
    let release;
    const pending = new Promise((resolve) => { release = resolve; });
    await page.route("**/api/analysis", async (route) => {
      await pending;
      await route.fulfill({ status: 503, body: '{"detail":"验收延迟请求"}', contentType: "application/json" }).catch(() => {});
    });
    try {
      await page.locator(".composer textarea").fill("取消任务验收");
      await page.getByRole("button", { name: "发送问题", exact: true }).click();
      await page.getByRole("button", { name: "停止分析", exact: true }).click();
      await page.getByText("分析已停止。", { exact: true }).waitFor();
      assert(await page.getByRole("combobox", { name: "分析设备" }).isEnabled());
      assert(await page.getByRole("button", { name: "新建对话", exact: true }).isEnabled());
    } finally { release(); }
  });
  await check("backend outage shows reconnect and recovers (injected HTTP failure)", async () => {
    await fresh();
    await page.route("**/api/overview", (route) => route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"验收注入：后端不可用"}' }));
    await page.reload();
    await page.getByText("数据服务尚未连接", { exact: true }).waitFor();
    await page.unroute("**/api/overview");
    await page.getByRole("button", { name: "重新连接", exact: true }).click();
    await page.getByText("设备数据已同步", { exact: true }).waitFor();
  });
  for (const width of [320, 390, 768, 1440]) {
    for (const title of ["运行总览", "设备管理", "监控告警", "运维知识库", "智能运维助手"]) {
      await check(`${title}: no page overflow at ${width}px`, async () => {
        await fresh();
        await page.setViewportSize({ width, height: width < 768 ? 844 : 1080 });
        await nav(title);
        const layout = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: innerWidth }));
        assert(layout.content <= layout.viewport, JSON.stringify(layout));
        if (width === 390) await page.screenshot({ path: `${output}/mobile-${title}.png`, fullPage: true });
        if (width === 320 && title === "设备管理") await page.screenshot({ path: `${output}/devices-320.png`, fullPage: true });
      });
    }
  }
  await check("no uncaught browser runtime errors", async () => assert.deepEqual(runtimeErrors, []));
} finally {
  await browser.close();
  await writeFile(`${output}/results.json`, JSON.stringify({ health, results, runtimeErrors }, null, 2));
}
const failures = results.filter((item) => item.status === "failed");
console.log(`${results.length - failures.length} passed, ${failures.length} failed; artifacts: ${output}`);
if (failures.length) process.exitCode = 1;
