import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";

const browser = await chromium.launch({ channel: "msedge", headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1080 },
  locale: "zh-CN",
  timezoneId: "Asia/Shanghai",
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await mkdir("test-results", { recursive: true });
try {
  const health = await (
    await context.request.get("http://127.0.0.1:8000/api/health")
  ).json();
  await page.goto("http://127.0.0.1:5173");
  await page.getByText("设备数据已同步", { exact: true }).waitFor();
  await page.screenshot({ path: "test-results/overview.png", fullPage: true });
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "设备管理" })
    .click();
  await page.getByPlaceholder("搜索设备名称、编号或区域").fill("P-101");
  await page.getByRole("button", { name: "详情", exact: true }).click();
  await page.getByRole("dialog").waitFor();
  await page.getByRole("button", { name: "模拟一次采样" }).click();
  await page.getByText("模拟采样已完成，数据已入库。").waitFor();
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: /监控告警/ })
    .click();
  const acknowledge = page.getByRole("button", { name: "确认", exact: true });
  if (await acknowledge.count()) {
    await acknowledge.first().click();
    await page.getByText("告警已确认，异常原因仍需进一步检查。").waitFor();
  }
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "运维知识库" })
    .click();
  await page.getByRole("button", { name: "导入文档", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByPlaceholder("例如：循环水泵维修手册")
    .fill("浏览器测试密封手册");
  await page
    .getByPlaceholder("粘贴手册、案例或操作规程正文，至少 20 个字符…")
    .fill(
      "密封泄漏检查应核对冲洗管路堵塞情况、密封面磨损记录，以及现场漏液变化。记录采集时间与设备编号。",
    );
  await page.getByRole("button", { name: "导入并建立索引" }).click();
  await page.getByRole("heading", { name: "浏览器测试密封手册" }).waitFor();
  await page
    .getByPlaceholder("输入故障现象，例如：水泵轴承温升与振动异常")
    .fill("密封泄漏冲洗管路堵塞");
  await page.getByRole("button", { name: "检索知识", exact: true }).click();
  await page.getByRole("heading", { name: /检索结果/ }).waitFor();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "删除 浏览器测试密封手册" }).click();
  await page
    .getByRole("heading", { name: "浏览器测试密封手册" })
    .waitFor({ state: "detached" });
  await page
    .getByRole("navigation")
    .getByRole("button", { name: /智能运维助手/ })
    .click();
  await page
    .getByRole("button", {
      name: "分析 P-101 最近的温度与振动异常",
      exact: true,
    })
    .click();
  await page
    .locator(".evidence-details summary")
    .first()
    .waitFor({ timeout: 180_000 });
  const firstReport = page
    .locator(".chat-message.assistant .message-content")
    .first();
  if ((await firstReport.innerText()).length < 50)
    throw new Error("Diagnosis report is empty");
  if (health.llm_mode === "ark") {
    await page.getByText("方舟模型分析", { exact: true }).waitFor();
    if ((await firstReport.innerText()).includes("此结果来自本地规则演示")) {
      throw new Error("Ark mode unexpectedly returned a demo report");
    }
  }
  await page.locator(".evidence-details summary").first().click();
  await page.screenshot({ path: "test-results/assistant.png", fullPage: true });
  await page
    .getByPlaceholder("描述你对 P-101 的问题，Enter 发送，Shift + Enter 换行")
    .fill("继续整理人工巡检建议");
  await page.getByRole("button", { name: "发送问题" }).click();
  await page
    .locator(".evidence-details summary")
    .nth(1)
    .waitFor({ timeout: 180_000 });
  if (
    (
      await page
        .locator(".chat-message.assistant .message-content")
        .nth(1)
        .innerText()
    ).length < 50
  ) {
    throw new Error("Follow-up report is empty");
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "运行总览" })
    .click();
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  if (overflow) throw new Error("Mobile page has horizontal overflow");
  if (errors.length) throw new Error(errors.join("\n"));
  console.log(
    "Browser smoke passed: overview, device sampling, alert acknowledgement, knowledge import/search/delete, diagnosis/follow-up, mobile layout.",
  );
} finally {
  await browser.close();
}
