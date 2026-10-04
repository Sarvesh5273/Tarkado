import { lstat } from "node:fs/promises"
import { createHash } from "node:crypto"

export const fingerprint = (value) => createHash("sha256").update(value).digest("hex")

export function origin(value) {
  let url
  try { url = new URL(value) } catch { throw new Error("Invalid Tarkado origin. No supplied values were printed.") }
  if (url.username || url.password || url.search || url.hash || url.pathname !== "/" || url.origin !== value) {
    throw new Error("Use an exact Tarkado origin without credentials, path, query, or fragment.")
  }
  if (url.protocol !== "https:" && !(url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname))) {
    throw new Error("Tarkado requires HTTPS, except explicit loopback laptop development.")
  }
  return url.origin
}

export async function credentialFile(path) {
  if (typeof path !== "string" || !path.startsWith("/")) throw new Error("Configure an explicit private connector credential file.")
  const info = await lstat(path)
  if (!info.isFile() || (info.mode & 0o077) || info.uid !== process.getuid() || info.size > 4096) {
    throw new Error("Connector credential must be a small owner-only regular file; existing permissions are not changed.")
  }
  const file = await import("node:fs/promises")
  const fs = await import("node:fs")
  const handle = await file.open(path, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW)
  let data
  try {
    const actual = await handle.stat()
    if (actual.ino !== info.ino || actual.dev !== info.dev || (actual.mode & 0o077) || actual.size > 4096) throw new Error("Credential file changed while opening.")
    try { data = JSON.parse(await handle.readFile("utf8")) }
    catch { throw new Error("Invalid private connector JSON. No credential content was printed.") }
  } finally { await handle.close() }
  if (!data || Object.keys(data).sort().join(",") !== "credential,origin" || typeof data.credential !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(data.credential)) {
    throw new Error("Invalid private Tarkado credential file. No values were printed.")
  }
  return { origin: origin(data.origin), credential: data.credential }
}

export class CompanyClient {
  constructor(configuration, transport = fetch) {
    if (typeof configuration.credential !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(configuration.credential)) throw new Error("Invalid scoped connector credential shape.")
    this.configuration = { ...configuration, origin: origin(configuration.origin) }
    this.transport = transport
  }
  async call(method, value) {
    if (!["status", "start", "task", "observation", "feedback", "conditional-select", "conditional-claim", "conditional-settle", "delivery-preflight", "delivery-bind", "delivery-options", "delivery-task", "tool-status"].includes(method)) throw new Error("Unsupported connector method.")
    const response = await this.transport(`${this.configuration.origin}/api/connectors/v1/${method}/`, {
      method: "POST", redirect: "error", credentials: "omit", signal: AbortSignal.timeout(5000),
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${this.configuration.credential}` },
      body: JSON.stringify(value),
    })
    if (!response.ok) {
      // Do not print upstream response bodies, credential values, or private diagnostics.
      throw new Error(response.status === 403 ? "Connector access refused/revoked; pair again in the browser." : "Connector operation refused; review task/scope in the browser.")
    }
    const text = await response.text()
    if (text.length > 131072) throw new Error("Connector response exceeds the supported metadata size.")
    return JSON.parse(text)
  }
}
