#!/usr/bin/env node
// DEMO-only laptop launcher (macOS, Windows, Linux). Runs a pinned, isolated OpenCode
// 2.0.21 with the Tarkado delivery plugin against a Tarkado stack hosted elsewhere.
// Your own OpenCode install, its config, providers and MCP servers are not used or touched.
//
//   node demo/laptop/start-demo.mjs check <bundle.json>   install + preflight, no task
//   node demo/laptop/start-demo.mjs start <bundle.json>   preflight, then open OpenCode
//
// The bundle comes from `run_loop.py laptop ...` on the stack host. It contains DEMO
// credentials: keep it private, never commit it. Nothing here prints them.

import { spawn, spawnSync } from "node:child_process"
import { createHash } from "node:crypto"
import fs from "node:fs"
import http from "node:http"
import path from "node:path"
import { fileURLToPath } from "node:url"

const VERSION = "2.0.21"
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..")
const HOST = path.join(ROOT, "integrations", "opencode")
const OPENCODE = path.join(HOST, "node_modules", "@opencode", "cli", "bin", "opencode.exe")
const WINDOWS = process.platform === "win32"

function fail(message) {
  console.error("\n[tarkado-demo] STOP: " + message)
  process.exit(1)
}
const say = message => console.log("[tarkado-demo] " + message)

function readBundle(file) {
  if (!file) fail("Give the bundle file: node demo/laptop/start-demo.mjs check <bundle.json>")
  let bundle
  try { bundle = JSON.parse(fs.readFileSync(path.resolve(file), "utf8")) } catch { fail(`Cannot read bundle ${file}.`) }
  if (bundle.schema !== "tarkado-demo-laptop-v1") fail("Not a Tarkado laptop bundle (schema mismatch).")
  return bundle
}

function install() {
  const [major] = process.versions.node.split(".").map(Number)
  if (major < 20) fail(`Node.js 20 or newer is required (found ${process.versions.node}).`)
  const pkg = path.join(HOST, "node_modules", "@opencode", "cli", "package.json")
  if (!fs.existsSync(pkg) || !fs.existsSync(path.join(HOST, "node_modules", "@opencode", "plugin"))) {
    say(`Installing OpenCode ${VERSION} + plugin SDK into integrations/opencode/node_modules (one time)...`)
    // cwd instead of --prefix: no quoting of paths through the Windows shell.
    const done = spawnSync("npm", ["install", "--no-save", "--no-package-lock", "--no-audit", "--no-fund",
      `@opencode/cli@${VERSION}`, `@opencode/plugin@${VERSION}`], { cwd: HOST, stdio: "inherit", shell: WINDOWS })
    if (done.status !== 0) fail("npm install failed; see the output above.")
  }
  const installed = JSON.parse(fs.readFileSync(pkg, "utf8")).version
  if (installed !== VERSION) fail(`integrations/opencode has OpenCode ${installed}; the plugin is validated only on ${VERSION}. Delete integrations/opencode/node_modules and re-run.`)
  if (!fs.existsSync(OPENCODE)) fail("OpenCode binary missing after install (npm postinstall blocked?). Re-run npm install with scripts enabled.")
}

// The same canonical form as engine.delivery_contract.function_fingerprint.
function canonical(value) {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]"
  if (value && typeof value === "object") {
    return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}"
  }
  return JSON.stringify(value)
}
const fingerprint = value => createHash("sha256").update(canonical(value), "utf8").digest("hex")

function isolatedEnv(base, extra) {
  // Drop anything that could point OpenCode at your own config, data or providers.
  const drop = /^(HOME|USERPROFILE|APPDATA|LOCALAPPDATA|XDG_.*|OPENCODE_.*)$/i
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !drop.test(key)))
  const dirs = { HOME: "home", USERPROFILE: "home", APPDATA: "appdata", LOCALAPPDATA: "localappdata", XDG_CONFIG_HOME: "config",
    XDG_DATA_HOME: "data", XDG_CACHE_HOME: "cache", XDG_STATE_HOME: "state" }
  for (const [key, name] of Object.entries(dirs)) {
    env[key] = path.join(base, name)
    fs.mkdirSync(env[key], { recursive: true })
  }
  return { ...env, OPENCODE_DISABLE_AUTOUPDATE: "1", ...extra }
}

function writeConfig(base, config) {
  const file = path.join(base, "config", "opencode", "opencode.json")
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, JSON.stringify(config, null, 1))
  return file
}

// Host validation: capture the tool definitions this OpenCode sends, against a loopback
// stub (no network, no model), and compare with the stack's reviewed fingerprints.
async function checkTools(bundle) {
  const captured = {}
  const server = http.createServer((request, response) => {
    let body = ""
    request.on("data", chunk => { body += chunk })
    request.on("end", () => {
      if (request.method !== "POST") { response.writeHead(404); response.end(); return }
      try { for (const tool of JSON.parse(body).tools ?? []) captured[tool.function.name] = tool.function } catch {}
      const usage = { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2, prompt_tokens_details: { cached_tokens: 0 },
        completion_tokens_details: { reasoning_tokens: 0 } }
      const chunk = (delta, finish, extra = {}) => "data: " + JSON.stringify({ id: "s", object: "chat.completion.chunk", created: 0,
        model: "stub", choices: delta ? [{ index: 0, delta, finish_reason: finish }] : [], ...extra }) + "\n\n"
      response.writeHead(200, { "Content-Type": "text/event-stream", Connection: "close" })
      response.end(chunk({ role: "assistant", content: "OK" }, null) + chunk({}, "stop") + chunk(null, null, { usage }) + "data: [DONE]\n\n")
    })
  })
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve))
  const scratch = path.join(ROOT, "local", "laptop", "host-check")
  fs.rmSync(scratch, { recursive: true, force: true })
  const project = path.join(scratch, "project")
  fs.mkdirSync(project, { recursive: true })
  spawnSync("git", ["init", "-q"], { cwd: project })
  const config = { ...bundle.opencode_config }
  config.providers = JSON.parse(JSON.stringify(config.providers))
  config.providers.company.settings.baseURL = `http://127.0.0.1:${server.address().port}/v1`
  const configFile = writeConfig(scratch, config)
  const env = isolatedEnv(scratch, { OPENCODE_CONFIG: configFile, COMPANY_GATEWAY_KEY: "host-validation-stub" })
  const run = spawn(OPENCODE, ["run", "--standalone", "--format", "json", "-m", "company/company-cheap", "Reply OK."],
    { cwd: project, env, stdio: "ignore" })
  const code = await new Promise(resolve => {
    const timer = setTimeout(() => { run.kill(); resolve("timeout") }, 180000)
    run.on("exit", value => { clearTimeout(timer); resolve(value) })
  })
  server.close()
  fs.rmSync(scratch, { recursive: true, force: true })
  const expected = bundle.tool_fingerprints
  const names = Object.keys(expected).sort()
  const missing = names.filter(name => !captured[name])
  if (missing.length) fail(`OpenCode did not offer tools ${missing.join(", ")} (exit ${code}). The gateway would refuse routed requests.`)
  const different = names.filter(name => fingerprint(captured[name]) !== expected[name])
  if (different.length) {
    fail(`This OpenCode describes tools differently from the reviewed host (${different.join(", ")}). ` +
      "The gateway would refuse every routed request (safely, before any model call). Report this; do not demo routed tasks on this machine.")
  }
  say(`Tool definitions match the reviewed host (${names.join(", ")}).`)
}

async function checkReachable(bundle) {
  let page
  try { page = await fetch(bundle.company_origin + "/login/", { redirect: "manual" }) } catch (error) {
    fail(`Cannot reach the company app at ${bundle.company_origin} (${error.cause?.code ?? error.message}). Is the stack running?`)
  }
  const html = page.status === 200 ? await page.text() : ""
  if (!html.includes("Tarkado")) {
    fail(`The company app answered ${page.status} without the Tarkado login page: the stack URL is private or down. ` +
      "Make the development URL reachable for the demo (see docs/FULL_LOOP.md, Laptop demo).")
  }
  const gateway = await fetch(bundle.plugin_options.gatewayOrigin + "v1/chat/completions", { method: "POST", redirect: "manual",
    headers: { "Content-Type": "application/json" }, body: "{}" }).catch(() => null)
  if (!gateway || gateway.status !== 401 || !(gateway.headers.get("content-type") ?? "").includes("json")) {
    fail(`The model gateway did not answer as expected (${gateway?.status ?? "no answer"}); it must reject a keyless request with 401 JSON.`)
  }
  say("Company app and model gateway are reachable.")
}

function prepareRepo(bundle) {
  const directory = bundle.directory
  if (!path.isAbsolute(directory)) fail(`Bundle directory ${directory} is not absolute.`)
  if (!fs.existsSync(directory)) {
    say(`Creating the DEMO inventory repository at ${directory}`)
    fs.cpSync(path.join(ROOT, "demo", "full_loop", "sample_repo"), directory, { recursive: true, filter: source => !source.includes("__pycache__") })
    fs.writeFileSync(path.join(directory, ".gitignore"), "__pycache__/\n")
    const git = (...args) => {
      const done = spawnSync("git", args, { cwd: directory, encoding: "utf8" })
      if (done.status !== 0) fail(`git ${args[0]} failed in ${directory}: ${done.stderr || done.error?.message}`)
    }
    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("-c", "user.name=demo", "-c", "user.email=demo@demo.invalid", "commit", "-q", "-m", "Inventory demo repository")
  }
  if (fs.realpathSync.native(directory) !== directory) {
    fail(`The bundle names ${directory} but the real path is ${fs.realpathSync.native(directory)}. ` +
      "Pairing is bound to the exact path OpenCode reports: ask for a new bundle with the real path.")
  }
  return directory
}

async function main() {
  const [action, file] = process.argv.slice(2)
  if (!["check", "start"].includes(action)) fail("Usage: node demo/laptop/start-demo.mjs check|start <bundle.json>")
  const bundle = readBundle(file)
  install()
  const directory = prepareRepo(bundle)
  await checkReachable(bundle)
  await checkTools(bundle)
  const base = path.join(ROOT, "local", "laptop", bundle.persona)
  fs.mkdirSync(base, { recursive: true })
  const credentialFile = path.join(base, "connector.json")
  fs.writeFileSync(credentialFile, JSON.stringify(bundle.connector), { mode: 0o600 })
  const config = { ...bundle.opencode_config,
    plugins: [{ package: path.join(HOST, "delivery"), options: { ...bundle.plugin_options, credentialFile } }] }
  const configFile = writeConfig(base, config)
  say(`Ready: persona ${bundle.persona}, repository ${directory}.`)
  if (action === "check") {
    say("Preflight passed. Start with: node demo/laptop/start-demo.mjs start <bundle.json>")
    return
  }
  const env = isolatedEnv(base, { OPENCODE_CONFIG: configFile, COMPANY_GATEWAY_KEY: bundle.gateway_key })
  say("Opening OpenCode. In OpenCode type /tarkado-delivery-start to begin a routed task.")
  const child = spawn(OPENCODE, ["--standalone"], { cwd: directory, env, stdio: "inherit" })
  child.on("exit", code => process.exit(code ?? 0))
}

main().catch(error => fail(error.message))
